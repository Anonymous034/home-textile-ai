"""Phone OTP authentication with a small, provider-agnostic SMS boundary.

The default ``DEMO_SMS_MODE=mock`` mode is intentionally safe for local
testing: it stores only a hash of the code and never returns or logs the
verification value.  Production deployments should provide an SMS adapter
behind ``send_sms_code`` (for example Aliyun SMS, Tencent Cloud SMS, or an
internal gateway) and set ``DEMO_SMS_MODE=provider``.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .database import connect, utc_now

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "studio_session"
SESSION_TTL_DAYS = 30
OTP_TTL_SECONDS = 300
OTP_MAX_ATTEMPTS = 5
OTP_PHONE_COOLDOWN_SECONDS = 60
OTP_HOURLY_LIMIT = 5
E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
CN_MOBILE_RE = re.compile(r"^1\d{10}$")


def normalize_phone(value: str) -> str:
    """Return an E.164 phone value while accepting common mainland input."""
    raw = re.sub(r"[\s().-]+", "", str(value or ""))
    if CN_MOBILE_RE.fullmatch(raw):
        raw = "+86" + raw
    if not E164_RE.fullmatch(raw):
        raise HTTPException(422, "请输入有效的 E.164 手机号，例如 +8613812345678")
    return raw


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _otp_hash(phone: str, code: str) -> str:
    # Include the normalized phone so a code copied to another number cannot
    # be reused.  The server secret makes database-only offline guessing less
    # useful if the default mock code is changed in a deployment.
    secret = os.getenv("AUTH_OTP_PEPPER", "local-development-otp-pepper")
    return _hash(f"{secret}:{phone}:{code}")


def _utc_after(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _cookie_secure() -> bool:
    return os.getenv("AUTH_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes", "on"}


def _masked_phone(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}"


def _client_ip(request: Request) -> str | None:
    # Do not trust forwarded headers by default; deployments behind a trusted
    # proxy can add their own normalized value before the app receives it.
    return request.client.host if request.client else None


def initialize_auth() -> None:
    """Create and migrate the auth tables without disturbing existing data."""
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY, account_id TEXT NOT NULL UNIQUE,
              role TEXT NOT NULL DEFAULT 'user', status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS auth_sessions (
              id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
              token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL, revoked_at TEXT,
              last_seen_at TEXT NOT NULL, user_agent TEXT, ip_address TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_token
              ON auth_sessions(token_hash, expires_at, revoked_at);
            CREATE INDEX IF NOT EXISTS idx_auth_sessions_account
              ON auth_sessions(account_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS otp_challenges (
              id TEXT PRIMARY KEY, phone TEXT NOT NULL, code_hash TEXT NOT NULL,
              created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0, consumed_at TEXT,
              request_ip TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_otp_phone_created
              ON otp_challenges(phone, created_at DESC);
            """
        )
        columns = {str(row[1]) for row in db.execute("PRAGMA table_info(users)")}
        for name, declaration in (
            ("phone", "TEXT"),
            ("phone_verified_at", "TEXT"),
            ("display_name", "TEXT"),
        ):
            if name not in columns:
                db.execute(f"ALTER TABLE users ADD COLUMN {name} {declaration}")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone) WHERE phone IS NOT NULL")


def session_user_from_token(token: str | None) -> dict[str, Any] | None:
    """Resolve a bearer cookie to a minimal user record, or return ``None``."""
    if not token or len(token) < 32:
        return None
    token_hash = _hash(token)
    now = utc_now()
    with connect() as db:
        row = db.execute(
            """
            SELECT u.id,u.account_id,u.phone,u.phone_verified_at,u.display_name,u.role,u.status,
                   s.id AS session_id
            FROM auth_sessions s JOIN users u ON u.account_id=s.account_id
            WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>? AND u.status='active'
            """,
            (token_hash, now),
        ).fetchone()
    return dict(row) if row else None


def _session_token(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_TTL_DAYS * 24 * 60 * 60,
        expires=SESSION_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )


class PhoneBody(BaseModel):
    phone: str = Field(min_length=3, max_length=32)


class RequestCodeBody(PhoneBody):
    # Optional challenge fields preserve the existing login page's lightweight
    # anti-bot check while keeping this API usable by native clients.
    human_answer: str | None = Field(default=None, max_length=12)
    challenge_id: str | None = Field(default=None, max_length=40)


class VerifyCodeBody(PhoneBody):
    code: str = Field(min_length=4, max_length=8)


@router.post("/demo-login")
def demo_login(body: VerifyCodeBody, request: Request, response: Response) -> dict[str, Any]:
    """Allow the local demo account to use the normal session cookie."""
    if (os.getenv("DEMO_LOGIN_ENABLED", "0").strip() != "1"
            or _client_ip(request) not in {"127.0.0.1", "::1"}
            or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}):
        raise HTTPException(404, "演示登录未启用")
    if body.phone.strip() != "123":
        raise HTTPException(400, "演示手机号不正确，请填写 123")
    if not hmac.compare_digest(body.code.strip(), "123456"):
        raise HTTPException(400, "演示验证码不正确，请填写 123456")

    now_iso = utc_now()
    account_id = "demo-user-123"
    with connect() as db:
        user = db.execute("SELECT id,status FROM users WHERE account_id=?", (account_id,)).fetchone()
        if user:
            if user["status"] != "active":
                raise HTTPException(403, "该账号已被停用")
            user_id = str(user["id"])
            db.execute("UPDATE users SET last_seen_at=? WHERE account_id=?", (now_iso, account_id))
        else:
            user_id = f"usr_{uuid4().hex}"
            db.execute(
                "INSERT INTO users(id,account_id,role,status,created_at,last_seen_at,display_name) VALUES(?,?,?,?,?,?,?)",
                (user_id, account_id, "user", "active", now_iso, now_iso, "演示用户"),
            )
        raw_token = secrets.token_urlsafe(48)
        db.execute(
            "INSERT INTO auth_sessions(id,account_id,token_hash,created_at,expires_at,last_seen_at,user_agent,ip_address) VALUES(?,?,?,?,?,?,?,?)",
            (f"ses_{uuid4().hex}", account_id, _hash(raw_token), now_iso, _utc_after(SESSION_TTL_DAYS * 24 * 60 * 60), now_iso, request.headers.get("user-agent"), _client_ip(request)),
        )
    _set_session_cookie(response, raw_token)
    return {"ok": True, "user": {"id": user_id, "account_id": account_id, "display_name": "演示用户", "role": "user"}}


def _validate_optional_challenge(body: RequestCodeBody) -> None:
    answers = {"subtract-17-1": "16", "add-8-4": "12", "subtract-9-3": "6"}
    if body.human_answer is None and body.challenge_id is None:
        return
    if answers.get(body.challenge_id or "") != (body.human_answer or "").strip():
        raise HTTPException(400, "人机验证答案不正确")


class SmsProvider(Protocol):
    async def send(self, phone: str, code: str) -> str:
        """Deliver one SMS and return a provider label for diagnostics."""


class MockSmsProvider:
    async def send(self, phone: str, code: str) -> str:
        # Values are deliberately unused here.  Keeping this method silent is
        # what prevents a mock code from leaking into logs or JSON responses.
        _ = (phone, code)
        return "mock"


class ConfiguredSmsProvider:
    async def send(self, phone: str, code: str) -> str:
        _ = (phone, code)
        raise HTTPException(503, "短信服务尚未配置，请设置短信供应商适配器")


async def send_sms_code(phone: str, code: str) -> str:
    """Send a code through the configured adapter.

    This repository deliberately does not bundle a vendor SDK or make an
    implicit paid network call.  ``mock`` is the safe default for staging;
    production wiring should replace this function with the selected provider.
    """
    provider = MockSmsProvider() if os.getenv("DEMO_SMS_MODE", "mock").strip().lower() == "mock" else ConfiguredSmsProvider()
    return await provider.send(phone, code)


@router.post("/request-code")
async def request_code(body: RequestCodeBody, request: Request) -> dict[str, Any]:
    _validate_optional_challenge(body)
    phone = normalize_phone(body.phone)
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    one_minute_ago = (now - timedelta(seconds=OTP_PHONE_COOLDOWN_SECONDS)).isoformat()
    one_hour_ago = (now - timedelta(hours=1)).isoformat()
    with connect() as db:
        recent = db.execute(
            "SELECT created_at FROM otp_challenges WHERE phone=? AND created_at>? ORDER BY created_at DESC LIMIT 1",
            (phone, one_minute_ago),
        ).fetchone()
        if recent:
            raise HTTPException(429, "验证码发送过于频繁，请稍后再试", headers={"Retry-After": str(OTP_PHONE_COOLDOWN_SECONDS)})
        hourly = db.execute(
            "SELECT COUNT(*) FROM otp_challenges WHERE phone=? AND created_at>?",
            (phone, one_hour_ago),
        ).fetchone()[0]
        if int(hourly) >= OTP_HOURLY_LIMIT:
            raise HTTPException(429, "验证码发送次数已达上限，请稍后再试", headers={"Retry-After": "3600"})

    configured_code = os.getenv("DEMO_SMS_CODE", "123456").strip()
    if os.getenv("DEMO_SMS_MODE", "mock").strip().lower() == "mock" and re.fullmatch(r"\d{6}", configured_code):
        code = configured_code
    else:
        code = f"{secrets.randbelow(1_000_000):06d}"
    delivery = await send_sms_code(phone, code)
    challenge_id = f"otp_{uuid4().hex}"
    with connect() as db:
        db.execute(
            "INSERT INTO otp_challenges(id,phone,code_hash,created_at,expires_at,request_ip) VALUES(?,?,?,?,?,?)",
            (challenge_id, phone, _otp_hash(phone, code), now_iso, _utc_after(OTP_TTL_SECONDS), _client_ip(request)),
        )
    # Never return or log ``code``.  In mock mode the operator supplies the
    # same value through DEMO_SMS_CODE when testing a local/staging instance.
    return {"ok": True, "delivery": delivery, "expires_in": OTP_TTL_SECONDS, "message": f"验证码已发送至 {_masked_phone(phone)}"}


@router.post("/verify-code")
def verify_code(body: VerifyCodeBody, request: Request, response: Response) -> dict[str, Any]:
    phone = normalize_phone(body.phone)
    code = body.code.strip()
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    with connect() as db:
        challenge = db.execute(
            "SELECT * FROM otp_challenges WHERE phone=? AND consumed_at IS NULL ORDER BY created_at DESC LIMIT 1",
            (phone,),
        ).fetchone()
        if not challenge or challenge["expires_at"] <= now_iso:
            raise HTTPException(400, "验证码已过期，请重新获取")
        if int(challenge["attempts"]) >= OTP_MAX_ATTEMPTS:
            raise HTTPException(429, "验证码尝试次数过多，请重新获取")
        if not hmac.compare_digest(str(challenge["code_hash"]), _otp_hash(phone, code)):
            db.execute("UPDATE otp_challenges SET attempts=attempts+1 WHERE id=?", (challenge["id"],))
            # The database context intentionally rolls back on exceptions;
            # commit the failed-attempt counter before returning the error so
            # the attempt limit cannot be bypassed by repeated bad codes.
            db.commit()
            remaining = max(0, OTP_MAX_ATTEMPTS - int(challenge["attempts"]) - 1)
            raise HTTPException(400, f"验证码不正确，还可尝试 {remaining} 次")
        db.execute("UPDATE otp_challenges SET consumed_at=? WHERE id=?", (now_iso, challenge["id"]))
        account = "phone:" + _hash(phone)
        user = db.execute("SELECT * FROM users WHERE phone=? OR account_id=? LIMIT 1", (phone, account)).fetchone()
        if user:
            if user["status"] != "active":
                raise HTTPException(403, "该账号已被停用")
            db.execute("UPDATE users SET phone=?,phone_verified_at=?,last_seen_at=? WHERE account_id=?", (phone, now_iso, now_iso, user["account_id"]))
            account_id = str(user["account_id"])
            role = str(user["role"])
            user_id = str(user["id"])
            display_name = user["display_name"] or _masked_phone(phone)
        else:
            user_id = f"usr_{uuid4().hex}"
            account_id = account
            role = "user"
            display_name = _masked_phone(phone)
            db.execute(
                "INSERT INTO users(id,account_id,role,status,created_at,last_seen_at,phone,phone_verified_at,display_name) VALUES(?,?,?,?,?,?,?,?,?)",
                (user_id, account_id, role, "active", now_iso, now_iso, phone, now_iso, display_name),
            )
        raw_token = secrets.token_urlsafe(48)
        db.execute(
            "INSERT INTO auth_sessions(id,account_id,token_hash,created_at,expires_at,last_seen_at,user_agent,ip_address) VALUES(?,?,?,?,?,?,?,?)",
            (f"ses_{uuid4().hex}", account_id, _hash(raw_token), now_iso, _utc_after(SESSION_TTL_DAYS * 24 * 60 * 60), now_iso, request.headers.get("user-agent"), _client_ip(request)),
        )
    _set_session_cookie(response, raw_token)
    return {"ok": True, "user": {"id": user_id, "account_id": account_id, "phone": phone, "display_name": display_name, "role": role}}


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    user = session_user_from_token(_session_token(request))
    if not user:
        return {"authenticated": False, "user": None}
    return {
        "authenticated": True,
        "user": {
            "id": user["id"],
            "account_id": user["account_id"],
            "phone": user.get("phone"),
            "display_name": user.get("display_name") or _masked_phone(str(user.get("phone") or "")),
            "role": user.get("role", "user"),
        },
    }


@router.post("/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    token = _session_token(request)
    if token:
        with connect() as db:
            db.execute("UPDATE auth_sessions SET revoked_at=? WHERE token_hash=?", (utc_now(), _hash(token)))
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=_cookie_secure())
    return {"ok": True}
