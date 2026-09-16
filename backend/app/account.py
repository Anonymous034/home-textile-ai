"""Local account gallery and transparent credit ledger."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .database import RESULT_DIR, connect, utc_now
from .user_key import current_user_key

router = APIRouter(prefix="/api/account", tags=["account"])

TOOL_NAMES = {
    "replicate": "爆款复刻", "pattern": "花型创作", "sketch": "画稿生图",
    "local-edit": "局部编辑", "upscale": "一键高清", "template-compose": "使用模板",
    "detail": "详情页制作", "buyer-show": "买家秀",
}
POINTS_PER_IMAGE = {"buyer-show": 8, "local-edit": 8, "sketch": 8, "template-compose": 8, "detail": 12, "upscale": 5}


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
