"""Local account gallery and transparent credit ledger."""
from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .database import RESULT_DIR, connect, utc_now
from .alipay_gateway import AlipayGatewayError, get_alipay_gateway, load_alipay_settings
from .user_key import current_account_id, current_user_key

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
    session_account = current_account_id.get()
    if session_account:
        return session_account
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
        payment_columns = {row[1] for row in db.execute("PRAGMA table_info(payment_orders)")}
        additions = {
            "provider": "TEXT NOT NULL DEFAULT 'mock'",
            "environment": "TEXT NOT NULL DEFAULT 'mock'",
            "checkout_url": "TEXT",
            "alipay_trade_no": "TEXT",
            "paid_amount_cents": "INTEGER",
            "last_notify_at": "TEXT",
            "failure_code": "TEXT",
        }
        for column, definition in additions.items():
            if column not in payment_columns:
                db.execute(f"ALTER TABLE payment_orders ADD COLUMN {column} {definition}")
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
    value["provider"] = value.get("provider") or "mock"
    value["environment"] = value.get("environment") or "mock"
    value["payment_mode"] = "mock" if value["provider"] == "mock" else f"alipay_{value['environment']}"
    return value


def _response(row, **extra) -> dict:
    value = _order_dict(row)
    is_mock = value["provider"] == "mock" or value["environment"] == "sandbox"
    return {"is_mock": is_mock, "provider": value["provider"], "environment": value["environment"], "order": value, **extra}


def _owned_order(db, order_id: str):
    row = db.execute(
        "SELECT * FROM payment_orders WHERE id=? AND account_id=?",
        (order_id, account_id()),
    ).fetchone()
    if not row:
        raise HTTPException(404, "支付订单不存在")
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
    settings = load_alipay_settings()
    gateway = get_alipay_gateway()
    provider = "alipay" if gateway else "mock"
    environment = settings.mode if gateway else "mock"
    prefix = "ALI" if gateway else "MOCK"
    order_id = prefix + created.strftime("%Y%m%d%H%M%S") + uuid4().hex[:10].upper()
    checkout_url = None
    if gateway:
        try:
            checkout_url = gateway.create_checkout(order_id, amount_cents, f"{package_name} · {points} 积分")
        except AlipayGatewayError as exc:
            raise HTTPException(502, str(exc)) from exc
    with connect() as db:
        db.execute(
            """INSERT INTO payment_orders(
                id,account_id,amount_cents,points,package_id,package_name,is_custom,status,
                created_at,completed_at,expires_at,provider,environment,checkout_url
            ) VALUES(?,?,?,?,?,?,?,'pending',?,NULL,?,?,?,?)""",
            (order_id, account_id(), amount_cents, points, package_id, package_name, is_custom,
             created.isoformat(), (created + ORDER_TTL).isoformat(), provider, environment, checkout_url),
        )
        row = db.execute("SELECT * FROM payment_orders WHERE id=?", (order_id,)).fetchone()
    return _response(row)


@router.get("/payment-orders/{order_id}")
def get_payment_order(order_id: str) -> dict:
    with connect() as db:
        row = _mark_expired(db, _owned_order(db, order_id))
    return _response(row)


@router.post("/payment-orders/{order_id}/complete")
def complete_payment_order(order_id: str) -> dict:
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = _mark_expired(db, _owned_order(db, order_id))
        if row["provider"] != "mock":
            raise HTTPException(409, "支付宝订单只能由支付宝验签结果确认，不能手动完成")
        if row["status"] == "succeeded":
            account = db.execute("SELECT balance FROM credit_accounts WHERE account_id=?", (account_id(),)).fetchone()
            return _response(row, already_completed=True, balance=account["balance"])
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
    return _response(completed_row, already_completed=False, balance=balance)


def amount_to_cents(value: str | None) -> int:
    try:
        amount = Decimal(value or "")
    except InvalidOperation as exc:
        raise ValueError("支付金额格式无效") from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError("支付金额格式无效")
    return int(amount * 100)


def settle_alipay_order(order_id: str, trade_no: str, paid_amount_cents: int, notify_time: str | None = None) -> dict:
    """Credit an Alipay order once. The caller must verify the provider signature first."""
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM payment_orders WHERE id=?", (order_id,)).fetchone()
        if not row or row["provider"] != "alipay":
            raise ValueError("支付宝订单不存在")
        if row["amount_cents"] != paid_amount_cents:
            db.execute("UPDATE payment_orders SET failure_code=? WHERE id=?", ("amount_mismatch", order_id))
            raise ValueError("支付金额与订单不一致")
        if row["status"] == "succeeded":
            if row["alipay_trade_no"] and row["alipay_trade_no"] != trade_no:
                raise ValueError("支付宝交易号不一致")
            return {"already_completed": True, "order": _order_dict(row)}

        completed = utc_now()
        event_id = f"alipay:{order_id}"
        updated = db.execute(
            """UPDATE payment_orders SET status='succeeded',completed_at=?,alipay_trade_no=?,
               paid_amount_cents=?,last_notify_at=?,failure_code=NULL
               WHERE id=? AND status!='succeeded'""",
            (completed, trade_no, paid_amount_cents, notify_time or completed, order_id),
        )
        if updated.rowcount != 1:
            raise ValueError("订单状态更新失败")
        reason = "支付宝沙箱充值" if row["environment"] == "sandbox" else "支付宝充值"
        db.execute(
            """INSERT OR IGNORE INTO credit_events(id,account_id,delta,reason,work_id,created_at)
               VALUES(?,?,?,?,?,?)""",
            (event_id, row["account_id"], row["points"], f"{reason} · ¥{paid_amount_cents / 100:.2f}", order_id, completed),
        )
        if db.execute("SELECT changes()").fetchone()[0] == 1:
            db.execute(
                """INSERT INTO credit_accounts(account_id,balance,updated_at) VALUES(?,?,?)
                   ON CONFLICT(account_id) DO UPDATE SET
                     balance=COALESCE(credit_accounts.balance,0)+excluded.balance,
                     updated_at=excluded.updated_at""",
                (row["account_id"], row["points"], completed),
            )
        completed_row = db.execute("SELECT * FROM payment_orders WHERE id=?", (order_id,)).fetchone()
    return {"already_completed": False, "order": _order_dict(completed_row)}


@router.post("/payment-orders/{order_id}/sync")
def sync_payment_order(order_id: str) -> dict:
    with connect() as db:
        row = _mark_expired(db, _owned_order(db, order_id))
    if row["provider"] == "mock" or row["status"] == "succeeded":
        return _response(row)
    gateway = get_alipay_gateway()
    if not gateway:
        raise HTTPException(503, "支付宝沙箱配置不可用，暂时无法查询订单")
    try:
        result = gateway.query(order_id)
    except AlipayGatewayError as exc:
        raise HTTPException(502, str(exc)) from exc
    if result.get("success") and result.get("trade_status") in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
        try:
            settle_alipay_order(order_id, str(result.get("trade_no") or ""), amount_to_cents(str(result.get("total_amount") or "")))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
    elif result.get("trade_status") == "TRADE_CLOSED":
        with connect() as db:
            db.execute("UPDATE payment_orders SET status='cancelled' WHERE id=? AND status!='succeeded'", (order_id,))
    with connect() as db:
        refreshed = _owned_order(db, order_id)
        balance_row = db.execute("SELECT balance FROM credit_accounts WHERE account_id=?", (account_id(),)).fetchone()
    return _response(refreshed, balance=balance_row["balance"] if balance_row else None)


@router.post("/payment-orders/{order_id}/cancel")
def cancel_payment_order(order_id: str) -> dict:
    with connect() as db:
        row = _mark_expired(db, _owned_order(db, order_id))
    if row["status"] != "pending":
        return _response(row)
    if row["provider"] == "alipay":
        gateway = get_alipay_gateway()
        if not gateway:
            raise HTTPException(503, "支付宝沙箱配置不可用，暂时无法取消订单")
        try:
            query = gateway.query(order_id)
            if query.get("success") and query.get("trade_status") in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
                settle_alipay_order(order_id, str(query.get("trade_no") or ""), amount_to_cents(str(query.get("total_amount") or "")))
            else:
                close = gateway.close(order_id)
                if not close.get("success") and close.get("sub_code") not in {"ACQ.TRADE_NOT_EXIST", "ACQ.TRADE_STATUS_ERROR"}:
                    raise AlipayGatewayError("支付宝订单关闭失败")
        except (AlipayGatewayError, ValueError) as exc:
            raise HTTPException(502, str(exc)) from exc
    with connect() as db:
        db.execute("UPDATE payment_orders SET status='cancelled' WHERE id=? AND status='pending'", (row["id"],))
        row = db.execute("SELECT * FROM payment_orders WHERE id=?", (row["id"],)).fetchone()
    return _response(row)
