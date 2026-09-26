"""Local account gallery and transparent credit ledger."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .database import RESULT_DIR, connect, utc_now
from .user_key import current_user_key

router = APIRouter(prefix="/api/account", tags=["account"])

TOOL_NAMES = {
    "replicate": "爆款复刻", "pattern": "花型创作", "sketch": "画稿生图",
    "local-edit": "局部编辑", "upscale": "一键高清", "template-compose": "使用模板",
    "detail": "详情页制作", "buyer-show": "买家秀",
}
POINTS_PER_IMAGE = {"buyer-show": 8, "local-edit": 8, "sketch": 8, "template-compose": 8, "detail": 12, "upscale": 5}
PAYMENT_PACKAGES = {
    "starter": {"name": "轻享包", "amount_cents": 19_900, "points": 2_200},
    "popular": {"name": "进阶包", "amount_cents": 48_000, "points": 6_600},
    "pro": {"name": "专业包", "amount_cents": 144_000, "points": 26_400},
}
ORDER_TTL = timedelta(minutes=15)


class PaymentOrderCreate(BaseModel):
    package_id: str | None = None
    custom_amount_yuan: int | None = None


def account_id() -> str:
    key = current_user_key.get()
    return "key:" + hashlib.sha256(key.encode()).hexdigest() if key else "demo-user-123"


def initialize_account() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS account_works (
            id TEXT PRIMARY KEY, account_id TEXT NOT NULL, tool TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_account_works_owner_time
            ON account_works(account_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS credit_accounts (
            account_id TEXT PRIMARY KEY, balance INTEGER, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS credit_events (
            id TEXT PRIMARY KEY, account_id TEXT NOT NULL, delta INTEGER NOT NULL,
            reason TEXT NOT NULL, work_id TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_credit_events_owner_time
            ON credit_events(account_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS payment_orders (
            id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
            amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
            points INTEGER NOT NULL CHECK(points > 0),
            package_id TEXT, package_name TEXT NOT NULL,
            is_custom INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL CHECK(status IN ('pending','succeeded','cancelled','expired')),
            created_at TEXT NOT NULL, completed_at TEXT, expires_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_payment_orders_owner_time
            ON payment_orders(account_id, created_at DESC);
        """)
        # Existing local outputs predate account tracking. Keep them available
        # to the demo owner; future personal-key outputs are attributed at save.
        for path in RESULT_DIR.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            relative = path.relative_to(RESULT_DIR)
            if path.name not in {"result.png", "result.jpg"} and not path.name.startswith("candidate_") and relative.parts[0] != "pattern":
                continue
            tool = relative.parts[0] if relative.parts[0] in TOOL_NAMES else "studio"
            created = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
            db.execute("INSERT OR IGNORE INTO account_works(id,account_id,tool,path,created_at) VALUES(?,?,?,?,?)", (uuid4().hex, "demo-user-123", tool, str(path.resolve()), created))


def record_work(path: Path) -> None:
    resolved = path.resolve()
    root = RESULT_DIR.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file() or resolved.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return
    relative = resolved.relative_to(root)
    tool = relative.parts[0] if relative.parts[0] in TOOL_NAMES else "studio"
    with connect() as db:
        db.execute(
            "INSERT OR IGNORE INTO account_works(id,account_id,tool,path,created_at) VALUES(?,?,?,?,?)",
            (uuid4().hex, account_id(), tool, str(resolved), utc_now()),
        )


@router.get("/works")
def list_works() -> dict:
    with connect() as db:
        rows = db.execute(
            "SELECT id,tool,created_at FROM account_works WHERE account_id=? ORDER BY created_at DESC LIMIT 300",
            (account_id(),),
        ).fetchall()
    return {"items": [{**dict(row), "tool_name": TOOL_NAMES.get(row["tool"], "AI 虚拟影棚"), "image_url": f"/api/account/works/{row['id']}/image"} for row in rows]}


@router.get("/works/{work_id}/image")
def work_image(work_id: str):
    with connect() as db:
        row = db.execute("SELECT path FROM account_works WHERE id=? AND account_id=?", (work_id, account_id())).fetchone()
    if not row:
        raise HTTPException(404, "作品不存在")
    path = Path(row["path"])
    if not path.resolve().is_relative_to(RESULT_DIR.resolve()) or not path.is_file():
        raise HTTPException(410, "作品文件已过期或不存在")
    return FileResponse(path, media_type="image/png" if path.suffix.lower() == ".png" else "image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.get("/credits")
def credits() -> dict:
    with connect() as db:
        account = db.execute("SELECT balance FROM credit_accounts WHERE account_id=?", (account_id(),)).fetchone()
        events = db.execute("SELECT id,delta,reason,work_id,created_at FROM credit_events WHERE account_id=? ORDER BY created_at DESC LIMIT 200", (account_id(),)).fetchall()
        works = db.execute("SELECT id,tool,created_at FROM account_works WHERE account_id=? ORDER BY created_at DESC LIMIT 200", (account_id(),)).fetchall()
    pending = [{"id": row["id"], "reason": TOOL_NAMES[row["tool"]], "points": POINTS_PER_IMAGE[row["tool"]], "created_at": row["created_at"]} for row in works if row["tool"] in POINTS_PER_IMAGE]
    return {"balance": account["balance"] if account else None, "events": [dict(row) for row in events], "pending_usage": pending}


def _order_dict(row) -> dict:
    value = dict(row)
    value["is_custom"] = bool(value["is_custom"])
    return value


def _owned_order(db, order_id: str):
    row = db.execute(
        "SELECT * FROM payment_orders WHERE id=? AND account_id=?",
        (order_id, account_id()),
    ).fetchone()
    if not row:
        raise HTTPException(404, "模拟支付订单不存在")
    return row


def _mark_expired(db, row):
    if row["status"] == "pending" and datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC):
        db.execute("UPDATE payment_orders SET status='expired' WHERE id=? AND status='pending'", (row["id"],))
        return db.execute("SELECT * FROM payment_orders WHERE id=?", (row["id"],)).fetchone()
    return row


@router.post("/payment-orders")
def create_payment_order(request: PaymentOrderCreate) -> dict:
    has_package = request.package_id is not None
    has_custom = request.custom_amount_yuan is not None
    if has_package == has_custom:
        raise HTTPException(400, "请选择一个充值套餐或填写自定义金额")

    if has_package:
        package = PAYMENT_PACKAGES.get(request.package_id or "")
        if not package:
            raise HTTPException(400, "充值套餐不存在")
        amount_cents = package["amount_cents"]
        points = package["points"]
        package_name = package["name"]
        package_id = request.package_id
        is_custom = 0
    else:
        amount_yuan = request.custom_amount_yuan
        if isinstance(amount_yuan, bool) or amount_yuan is None or not 1 <= amount_yuan <= 5000:
            raise HTTPException(400, "自定义金额须为 1–5000 元的整数")
        amount_cents = amount_yuan * 100
        points = amount_yuan * 10
        package_name = "自定义充值"
        package_id = None
        is_custom = 1

    created = datetime.now(UTC)
    order_id = "MOCK" + created.strftime("%Y%m%d%H%M%S") + uuid4().hex[:10].upper()
    with connect() as db:
        db.execute(
            """INSERT INTO payment_orders(
                id,account_id,amount_cents,points,package_id,package_name,is_custom,status,
                created_at,completed_at,expires_at
            ) VALUES(?,?,?,?,?,?,?,'pending',?,NULL,?)""",
            (order_id, account_id(), amount_cents, points, package_id, package_name, is_custom,
             created.isoformat(), (created + ORDER_TTL).isoformat()),
        )
        row = db.execute("SELECT * FROM payment_orders WHERE id=?", (order_id,)).fetchone()
    return {"is_mock": True, "order": _order_dict(row)}

@router.get("/payment-orders/{order_id}")
def get_payment_order(order_id: str) -> dict:
    with connect() as db:
        row = _mark_expired(db, _owned_order(db, order_id))
    return {"is_mock": True, "order": _order_dict(row)}


@router.post("/payment-orders/{order_id}/complete")
def complete_payment_order(order_id: str) -> dict:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = _mark_expired(db, _owned_order(db, order_id))
        if row["status"] == "succeeded":
            account = db.execute("SELECT balance FROM credit_accounts WHERE account_id=?", (account_id(),)).fetchone()
            return {"is_mock": True, "already_completed": True, "balance": account["balance"], "order": _order_dict(row)}
        if row["status"] == "expired":
            db.commit()
            raise HTTPException(409, "模拟支付订单已过期，请重新创建")
        if row["status"] == "cancelled":
            raise HTTPException(409, "模拟支付订单已取消")

        completed = utc_now()
        db.execute(
            """INSERT INTO credit_accounts(account_id,balance,updated_at) VALUES(?,?,?)
            ON CONFLICT(account_id) DO UPDATE SET
                balance=COALESCE(credit_accounts.balance,0)+excluded.balance,
                updated_at=excluded.updated_at""",
            (account_id(), row["points"], completed),
        )
        db.execute(
            "INSERT INTO credit_events(id,account_id,delta,reason,work_id,created_at) VALUES(?,?,?,?,?,?)",
            (uuid4().hex, account_id(), row["points"],
             f"模拟微信支付充值 · ¥{row['amount_cents'] / 100:.2f}", row["id"], completed),
        )
        db.execute(
            "UPDATE payment_orders SET status='succeeded',completed_at=? WHERE id=? AND status='pending'",
            (completed, row["id"]),
        )
        completed_row = db.execute("SELECT * FROM payment_orders WHERE id=?", (row["id"],)).fetchone()
        balance = db.execute("SELECT balance FROM credit_accounts WHERE account_id=?", (account_id(),)).fetchone()["balance"]
    return {"is_mock": True, "already_completed": False, "balance": balance, "order": _order_dict(completed_row)}


@router.post("/payment-orders/{order_id}/cancel")
def cancel_payment_order(order_id: str) -> dict:
    with connect() as db:
        row = _mark_expired(db, _owned_order(db, order_id))
        if row["status"] == "pending":
            db.execute("UPDATE payment_orders SET status='cancelled' WHERE id=?", (row["id"],))
            row = db.execute("SELECT * FROM payment_orders WHERE id=?", (row["id"],)).fetchone()
    return {"is_mock": True, "order": _order_dict(row)}
