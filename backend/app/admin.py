"""运营管理后台接口。

所有 /api/admin/* 都要求 HttpOnly 会话对应的账号拥有 role='admin'。
读取类接口只聚合既有表，不复制数据；写操作统一留痕到 admin_audit。
"""
from __future__ import annotations

import json
import os
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .database import connect, utc_now
from .user_key import current_auth_user

router = APIRouter(prefix="/api/admin", tags=["admin"])

VALID_ROLES = {"user", "admin"}
VALID_STATUS = {"active", "disabled"}
PRESET_TABLES = {
    "models": "model_presets",
    "scenes": "scene_presets",
    "compositions": "composition_presets",
}


def initialize_admin() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS admin_audit (
              id TEXT PRIMARY KEY,
              actor_account_id TEXT NOT NULL,
              actor_label TEXT NOT NULL,
              action TEXT NOT NULL,
              target TEXT NOT NULL,
              detail TEXT,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_admin_audit_time
              ON admin_audit(created_at DESC);
            """
        )


def _admin() -> dict[str, Any]:
    user = current_auth_user.get()
    if not user:
        raise HTTPException(401, "请先登录管理账号")
    if str(user.get("role") or "") != "admin":
        raise HTTPException(403, "该账号没有管理权限")
    return user


def _actor_label(user: dict[str, Any]) -> str:
    phone = str(user.get("phone") or "")
    masked = f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 8 else phone
    return str(user.get("display_name") or masked or user.get("account_id") or "")


def _audit(action: str, target: str, detail: str = "") -> None:
    user = current_auth_user.get() or {}
    with connect() as db:
        db.execute(
            "INSERT INTO admin_audit(id,actor_account_id,actor_label,action,target,detail,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                f"aud_{uuid4().hex}",
                str(user.get("account_id") or ""),
                _actor_label(user),
                action,
                target,
                detail,
                utc_now(),
            ),
        )


def _scalar(db, sql: str, params: tuple = ()) -> int:
    row = db.execute(sql, params).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _env_flag(name: str) -> bool:
    value = os.getenv(name, "").strip()
    return bool(value) and "replace_with" not in value


# ---------------------------------------------------------------- 概览


@router.get("/overview")
def overview() -> dict[str, Any]:
    _admin()
    now = utc_now()
    day_start = now[:10] + "T00:00:00+00:00"
    with connect() as db:
        users_total = _scalar(db, "SELECT COUNT(*) FROM users")
        users_today = _scalar(db, "SELECT COUNT(*) FROM users WHERE created_at>=?", (day_start,))
        users_disabled = _scalar(db, "SELECT COUNT(*) FROM users WHERE status!='active'")
        admins = _scalar(db, "SELECT COUNT(*) FROM users WHERE role='admin'")
        sessions_live = _scalar(
            db,
            "SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL AND expires_at>?",
            (now,),
        )
        sessions_today = _scalar(db, "SELECT COUNT(*) FROM auth_sessions WHERE created_at>=?", (day_start,))
        credits_total = _scalar(db, "SELECT COALESCE(SUM(balance),0) FROM credit_accounts")
        orders_total = _scalar(db, "SELECT COUNT(*) FROM payment_orders")
        orders_paid = _scalar(db, "SELECT COUNT(*) FROM payment_orders WHERE status='succeeded'")
        revenue_cents = _scalar(
            db,
            "SELECT COALESCE(SUM(COALESCE(paid_amount_cents,amount_cents)),0) FROM payment_orders WHERE status='succeeded'",
        )
        replica_total = _scalar(db, "SELECT COUNT(*) FROM replica_jobs")
        replica_running = _scalar(
            db,
            "SELECT COUNT(*) FROM replica_jobs WHERE status IN ('queued','running','preparing')",
        )
        studio_total = _scalar(db, "SELECT COUNT(*) FROM jobs")
        detail_total = _scalar(db, "SELECT COUNT(*) FROM detail_records WHERE kind='detail'")
        buyer_total = _scalar(db, "SELECT COUNT(*) FROM detail_records WHERE kind='buyer'")
        works_total = _scalar(db, "SELECT COUNT(*) FROM account_works")
        recent_users = db.execute(
            "SELECT id,phone,display_name,role,status,created_at,last_seen_at FROM users"
            " ORDER BY created_at DESC LIMIT 6"
        ).fetchall()
        top_credit = db.execute(
            "SELECT c.account_id, COALESCE(c.balance,0) AS balance, u.phone, u.display_name"
            " FROM credit_accounts c LEFT JOIN users u ON u.account_id=c.account_id"
            " ORDER BY balance DESC LIMIT 6"
        ).fetchall()
        gallery = {
            "categories": _scalar(db, "SELECT COUNT(*) FROM template_categories"),
            "templates": _scalar(db, "SELECT COUNT(*) FROM template_presets"),
            "template_images": _scalar(db, "SELECT COUNT(*) FROM template_images"),
            "models": _scalar(db, "SELECT COUNT(*) FROM model_presets"),
            "scenes": _scalar(db, "SELECT COUNT(*) FROM scene_presets"),
            "compositions": _scalar(db, "SELECT COUNT(*) FROM composition_presets"),
        }
    return {
        "users": {
            "total": users_total,
            "today": users_today,
            "disabled": users_disabled,
            "admins": admins,
            "sessions_live": sessions_live,
            "sessions_today": sessions_today,
        },
        "credits": {"balance_total": credits_total},
        "orders": {"total": orders_total, "paid": orders_paid, "revenue_cents": revenue_cents},
        "tasks": {
            "replicate": replica_total,
            "replicate_running": replica_running,
            "studio": studio_total,
            "detail": detail_total,
            "buyer_show": buyer_total,
            "works": works_total,
        },
        "gallery": gallery,
        "config": {
            "ark_key": _env_flag("ARK_API_KEY"),
            "plan_api": _env_flag("DETAIL_PLAN_API_KEY") and bool(os.getenv("DETAIL_PLAN_ENDPOINT", "").strip()),
            "sms_mode": os.getenv("DEMO_SMS_MODE", "aliyun").strip() or "aliyun",
            "local_config": os.getenv("LOCAL_CONFIG_ENABLED", "0").strip() == "1",
        },
        "recent_users": [dict(row) for row in recent_users],
        "top_credits": [dict(row) for row in top_credit],
    }


# ---------------------------------------------------------------- 用户


@router.get("/users")
def list_users(
    q: str = "",
    role: str = "",
    status: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    _admin()
    where = ["1=1"]
    params: list[Any] = []
    keyword = q.strip()
    if keyword:
        like = f"%{keyword}%"
        where.append("(u.phone LIKE ? OR u.display_name LIKE ? OR u.id LIKE ? OR u.account_id LIKE ?)")
        params.extend([like, like, like, like])
    if role in VALID_ROLES:
        where.append("u.role=?")
        params.append(role)
    if status in VALID_STATUS:
        where.append("u.status=?")
        params.append(status)
    clause = " AND ".join(where)
    now = utc_now()
    with connect() as db:
        total = _scalar(db, f"SELECT COUNT(*) FROM users u WHERE {clause}", tuple(params))
        rows = db.execute(
            f"""
            SELECT u.id,u.account_id,u.phone,u.display_name,u.role,u.status,
                   u.created_at,u.last_seen_at,
                   COALESCE(c.balance,0) AS balance,
                   (SELECT COUNT(*) FROM account_works w WHERE w.account_id=u.account_id) AS works,
                   (SELECT COUNT(*) FROM auth_sessions s
                      WHERE s.account_id=u.account_id AND s.revoked_at IS NULL AND s.expires_at>?) AS sessions,
                   (SELECT COUNT(*) FROM credit_events e WHERE e.account_id=u.account_id) AS credit_events
            FROM users u LEFT JOIN credit_accounts c ON c.account_id=u.account_id
            WHERE {clause}
            ORDER BY u.created_at DESC
            LIMIT ? OFFSET ?
            """,
            tuple([now] + params + [page_size, (page - 1) * page_size]),
        ).fetchall()
    return {"total": total, "page": page, "page_size": page_size, "items": [dict(r) for r in rows]}


@router.get("/users/{user_id}")
def user_detail(user_id: str) -> dict[str, Any]:
    _admin()
    now = utc_now()
    with connect() as db:
        user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "用户不存在")
        account_id = str(user["account_id"])
        balance = _scalar(db, "SELECT COALESCE(balance,0) FROM credit_accounts WHERE account_id=?", (account_id,))
        events = db.execute(
            "SELECT id,delta,reason,work_id,created_at FROM credit_events WHERE account_id=?"
            " ORDER BY created_at DESC LIMIT 30",
            (account_id,),
        ).fetchall()
        works = db.execute(
            "SELECT id,tool,path,created_at FROM account_works WHERE account_id=?"
            " ORDER BY created_at DESC LIMIT 20",
            (account_id,),
        ).fetchall()
        sessions = db.execute(
            "SELECT id,created_at,expires_at,revoked_at,last_seen_at,user_agent,ip_address"
            " FROM auth_sessions WHERE account_id=? ORDER BY created_at DESC LIMIT 20",
            (account_id,),
        ).fetchall()
    return {
        "user": dict(user),
        "balance": balance,
        "credit_events": [dict(r) for r in events],
        "works": [dict(r) for r in works],
        "sessions": [dict(r) for r in sessions],
        "now": now,
    }


class RoleBody(BaseModel):
    role: str = Field(pattern=r"^(user|admin)$")


@router.post("/users/{user_id}/role")
def set_role(user_id: str, body: RoleBody) -> dict[str, Any]:
    current = _admin()
    with connect() as db:
        user = db.execute("SELECT id,account_id,phone,role FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "用户不存在")
        if str(user["account_id"]) == str(current.get("account_id")) and body.role != "admin":
            raise HTTPException(400, "不能取消自己的管理员权限")
        db.execute("UPDATE users SET role=? WHERE id=?", (body.role, user_id))
    _audit("user.role", user_id, f"{user['role']} -> {body.role}")
    return {"ok": True, "id": user_id, "role": body.role}


class StatusBody(BaseModel):
    status: str = Field(pattern=r"^(active|disabled)$")


@router.post("/users/{user_id}/status")
def set_status(user_id: str, body: StatusBody) -> dict[str, Any]:
    current = _admin()
    with connect() as db:
        user = db.execute("SELECT id,account_id,status FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "用户不存在")
        if str(user["account_id"]) == str(current.get("account_id")) and body.status != "active":
            raise HTTPException(400, "不能停用自己的账号")
        db.execute("UPDATE users SET status=? WHERE id=?", (body.status, user_id))
        if body.status == "disabled":
            db.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL",
                (utc_now(), user["account_id"]),
            )
    _audit("user.status", user_id, f"{user['status']} -> {body.status}")
    return {"ok": True, "id": user_id, "status": body.status}


class CreditBody(BaseModel):
    delta: int = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(default="管理员调整", max_length=120)


@router.post("/users/{user_id}/credits")
def adjust_credits(user_id: str, body: CreditBody) -> dict[str, Any]:
    _admin()
    if body.delta == 0:
        raise HTTPException(400, "调整数量不能为 0")
    now = utc_now()
    with connect() as db:
        user = db.execute("SELECT id,account_id FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "用户不存在")
        account_id = str(user["account_id"])
        current_balance = _scalar(db, "SELECT COALESCE(balance,0) FROM credit_accounts WHERE account_id=?", (account_id,))
        if current_balance + body.delta < 0:
            raise HTTPException(400, f"余额不足，当前 {current_balance} 积分")
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "INSERT INTO credit_accounts(account_id,balance,updated_at) VALUES(?,?,?)"
            " ON CONFLICT(account_id) DO UPDATE SET balance=COALESCE(credit_accounts.balance,0)+excluded.balance,"
            " updated_at=excluded.updated_at",
            (account_id, body.delta, now),
        )
        db.execute(
            "INSERT INTO credit_events(id,account_id,delta,reason,work_id,created_at) VALUES(?,?,?,?,?,?)",
            (f"cre_{uuid4().hex}", account_id, body.delta, body.reason, None, now),
        )
        balance = _scalar(db, "SELECT COALESCE(balance,0) FROM credit_accounts WHERE account_id=?", (account_id,))
    _audit("user.credits", user_id, f"{body.delta:+d} {body.reason} -> {balance}")
    return {"ok": True, "id": user_id, "balance": balance}


@router.post("/users/{user_id}/sessions/revoke")
def revoke_sessions(user_id: str) -> dict[str, Any]:
    _admin()
    with connect() as db:
        user = db.execute("SELECT id,account_id FROM users WHERE id=?", (user_id,)).fetchone()
        if not user:
            raise HTTPException(404, "用户不存在")
        cursor = db.execute(
            "UPDATE auth_sessions SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL",
            (utc_now(), user["account_id"]),
        )
        count = cursor.rowcount
    _audit("user.sessions.revoke", user_id, f"撤销 {count} 个会话")
    return {"ok": True, "revoked": count}


# ---------------------------------------------------------------- 任务


@router.get("/jobs")
def list_jobs(
    tool: str = "",
    status: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    _admin()
    tool = tool.strip()
    status = status.strip()
    limit = page_size
    offset = (page - 1) * page_size
    items: list[dict[str, Any]] = []
    with connect() as db:
        if tool in {"", "replicate"}:
            where = ["1=1"]
            params: list[Any] = []
            if status:
                where.append("status=?")
                params.append(status)
            rows = db.execute(
                "SELECT id,status,phase,stage,error_code,uncertain,created_at,updated_at,"
                "target_width,target_height,output_path FROM replica_jobs"
                f" WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                tuple(params + [limit, offset]),
            ).fetchall()
            for r in rows:
                items.append(
                    {
                        "id": r["id"],
                        "tool": "爆款复刻",
                        "tool_key": "replicate",
                        "status": r["status"],
                        "stage": r["phase"] or r["stage"],
                        "created_at": r["created_at"],
                        "summary": f"{r['target_width']}×{r['target_height']}",
                        "error": r["error_code"],
                        "has_output": bool(r["output_path"]),
                    }
                )
        if tool in {"", "studio"}:
            where = ["1=1"]
            params = []
            if status:
                where.append("status=?")
                params.append(status)
            rows = db.execute(
                "SELECT id,status,stage,progress,output_count,created_at,updated_at,is_mock"
                f" FROM jobs WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                tuple(params + [limit, offset]),
            ).fetchall()
            for r in rows:
                items.append(
                    {
                        "id": r["id"],
                        "tool": "影棚成片",
                        "tool_key": "studio",
                        "status": r["status"],
                        "stage": r["stage"],
                        "created_at": r["created_at"],
                        "summary": f"{r['output_count']} 张 · {r['progress']}%"
                        + (" · mock" if r["is_mock"] else ""),
                        "error": None,
                        "has_output": r["progress"] == 100,
                    }
                )
        if tool in {"", "detail", "buyer"}:
            rows = db.execute(
                "SELECT kind,id,payload FROM detail_records ORDER BY rowid DESC LIMIT 200"
            ).fetchall()
            for r in rows:
                if tool and r["kind"] != tool:
                    continue
                try:
                    payload = json.loads(r["payload"])
                except Exception:
                    payload = {}
                state = str(payload.get("status") or payload.get("state") or "unknown")
                if status and state != status:
                    continue
                items.append(
                    {
                        "id": r["id"],
                        "tool": "详情页" if r["kind"] == "detail" else "买家秀",
                        "tool_key": r["kind"],
                        "status": state,
                        "stage": payload.get("stage") or payload.get("current_stage") or "",
                        "created_at": payload.get("created_at") or payload.get("updated_at") or "",
                        "summary": str(payload.get("title") or payload.get("name") or "")[:60],
                        "error": payload.get("error") or payload.get("error_code"),
                        "has_output": bool(payload.get("output_url") or payload.get("images")),
                    }
                )
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    total = len(items)
    return {"total": total, "page": page, "page_size": page_size, "items": items[offset : offset + limit]}


# ---------------------------------------------------------------- 订单


@router.get("/orders")
def list_orders(
    status: str = "",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    _admin()
    where = ["1=1"]
    params: list[Any] = []
    if status:
        where.append("o.status=?")
        params.append(status)
    clause = " AND ".join(where)
    with connect() as db:
        total = _scalar(db, f"SELECT COUNT(*) FROM payment_orders o WHERE {clause}", tuple(params))
        rows = db.execute(
            f"""
            SELECT o.id,o.account_id,o.amount_cents,o.points,o.package_name,o.status,
                   o.provider,o.environment,o.created_at,o.completed_at,o.paid_amount_cents,
                   o.alipay_trade_no,u.phone,u.display_name
            FROM payment_orders o LEFT JOIN users u ON u.account_id=o.account_id
            WHERE {clause}
            ORDER BY o.created_at DESC LIMIT ? OFFSET ?
            """,
            tuple(params + [page_size, (page - 1) * page_size]),
        ).fetchall()
    return {"total": total, "page": page, "page_size": page_size, "items": [dict(r) for r in rows]}


# ---------------------------------------------------------------- 图库


@router.get("/gallery")
def gallery() -> dict[str, Any]:
    _admin()
    with connect() as db:
        categories = db.execute(
            "SELECT c.id,c.name,c.sort_order,"
            " (SELECT COUNT(*) FROM template_presets t WHERE t.category_id=c.id) AS templates"
            " FROM template_categories c ORDER BY c.sort_order,c.name"
        ).fetchall()
        models = db.execute(
            "SELECT id,name,gender,style_tag,enabled,sort_order,avatar_path FROM model_presets"
            " ORDER BY sort_order,name LIMIT 200"
        ).fetchall()
        scenes = db.execute(
            "SELECT id,name,scene_type,enabled,sort_order,preview_path FROM scene_presets"
            " ORDER BY sort_order,name LIMIT 200"
        ).fetchall()
        compositions = db.execute(
            "SELECT id,name,description,enabled,sort_order,preview_path FROM composition_presets"
            " ORDER BY sort_order,name LIMIT 200"
        ).fetchall()
        images = _scalar(db, "SELECT COUNT(*) FROM template_images")
    return {
        "categories": [dict(r) for r in categories],
        "models": [dict(r) for r in models],
        "scenes": [dict(r) for r in scenes],
        "compositions": [dict(r) for r in compositions],
        "images": images,
    }


class EnabledBody(BaseModel):
    enabled: bool


@router.post("/gallery/{kind}/{preset_id}/enabled")
def toggle_preset(kind: str, preset_id: str, body: EnabledBody) -> dict[str, Any]:
    _admin()
    table = PRESET_TABLES.get(kind)
    if not table:
        raise HTTPException(400, "不支持的图库类型")
    with connect() as db:
        row = db.execute(f"SELECT id,name FROM {table} WHERE id=?", (preset_id,)).fetchone()
        if not row:
            raise HTTPException(404, "条目不存在")
        db.execute(f"UPDATE {table} SET enabled=?,updated_at=? WHERE id=?", (1 if body.enabled else 0, utc_now(), preset_id))
    _audit("gallery.enabled", f"{kind}/{preset_id}", f"{row['name']} -> {'启用' if body.enabled else '停用'}")
    return {"ok": True, "id": preset_id, "enabled": body.enabled}


# ---------------------------------------------------------------- 审计


@router.get("/audit")
def audit(page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100)) -> dict[str, Any]:
    _admin()
    with connect() as db:
        total = _scalar(db, "SELECT COUNT(*) FROM admin_audit")
        rows = db.execute(
            "SELECT id,actor_label,action,target,detail,created_at FROM admin_audit"
            " ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (page_size, (page - 1) * page_size),
        ).fetchall()
    return {"total": total, "page": page, "page_size": page_size, "items": [dict(r) for r in rows]}
