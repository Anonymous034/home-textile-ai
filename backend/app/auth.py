"""Phone OTP authentication backed by Alibaba Cloud SMS."""
from __future__ import annotations

import hashlib
import hmac
import json
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
OTP_IP_HOURLY_LIMIT = 20
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
    # be reused. The server secret limits database-only offline guessing.
    secret = os.getenv("AUTH_OTP_PEPPER", "local-development-otp-pepper")
    return _hash(f"{secret}:{phone}:{code}")


def _new_otp_code() -> str:
    """Generate a uniformly random six-digit code, including leading zeros."""
    return f"{secrets.randbelow(1_000_000):06d}"


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
    code: str = Field(pattern=r"^[0-9]{6}$")


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


def _aliyun_sms_configuration() -> tuple[str, str, str, str]:
    access_key_id = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "").strip()
    access_key_secret = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "").strip()
    sign_name = os.getenv("ALIYUN_SMS_SIGN_NAME", "").strip()
    template_code = os.getenv("ALIYUN_SMS_TEMPLATE_CODE", "").strip()
    if not all((access_key_id, access_key_secret, sign_name, template_code)) or not re.fullmatch(r"SMS_\d+", template_code):
        raise HTTPException(503, "阿里云短信尚未配置，请填写服务端 AccessKey、短信签名和模板编号")
    if not os.getenv("AUTH_OTP_PEPPER", "").strip():
        raise HTTPException(503, "验证码服务端密钥尚未配置")
    return access_key_id, access_key_secret, sign_name, template_code


class ConfiguredSmsProvider:
    async def send(self, phone: str, code: str) -> str:
        access_key_id, access_key_secret, sign_name, template_code = _aliyun_sms_configuration()
        try:
            from alibabacloud_dysmsapi20170525.client import Client
            from alibabacloud_dysmsapi20170525 import models as sms_models
            from alibabacloud_tea_openapi import models as open_api_models
            from alibabacloud_tea_util import models as util_models
        except ImportError as exc:
            raise HTTPException(503, "阿里云短信 SDK 尚未安装") from exc

        config = open_api_models.Config(access_key_id=access_key_id, access_key_secret=access_key_secret)
        config.endpoint = "dysmsapi.aliyuncs.com"
        client = Client(config)
        sms_request = sms_models.SendSmsRequest(
            phone_numbers=phone.removeprefix("+86"),
            sign_name=sign_name,
            template_code=template_code,
            template_param=json.dumps({"code": code}, separators=(",", ":")),
        )
        runtime = util_models.RuntimeOptions(autoretry=False, max_attempts=1, connect_timeout=3000, read_timeout=5000)
        try:
            result = await client.send_sms_with_options_async(sms_request, runtime)
        except Exception as exc:
            # Never expose SDK errors: they may include request parameters.
            raise HTTPException(502, "短信服务暂时无法连接，请稍后再试") from exc
        provider_code = getattr(getattr(result, "body", None), "code", None)
        if provider_code != "OK":
            # Alibaba Cloud error codes are safe to show after constraining the
            # format; never return the provider message or request parameters.
            safe_code = provider_code if isinstance(provider_code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", provider_code) else "UNKNOWN"
            raise HTTPException(502, f"短信发送失败（阿里云错误码：{safe_code}）")
        return "aliyun"


async def send_sms_code(phone: str, code: str) -> str:
    """Send a code through the configured adapter.

    Mock mode is explicit and only intended for local automated tests.
    """
    provider = MockSmsProvider() if os.getenv("DEMO_SMS_MODE", "aliyun").strip().lower() == "mock" else ConfiguredSmsProvider()
    return await provider.send(phone, code)


@router.post("/request-code")
async def request_code(body: RequestCodeBody, request: Request) -> dict[str, Any]:
    _validate_optional_challenge(body)
    phone = normalize_phone(body.phone)
    if not phone.startswith("+86") or not CN_MOBILE_RE.fullmatch(phone[3:]):
        raise HTTPException(422, "目前仅支持中国内地手机号")
    # A missing configuration must fail before reserving a rate-limit slot.
    if os.getenv("DEMO_SMS_MODE", "aliyun").strip().lower() != "mock":
        _aliyun_sms_configuration()
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    one_minute_ago = (now - timedelta(seconds=OTP_PHONE_COOLDOWN_SECONDS)).isoformat()
    one_hour_ago = (now - timedelta(hours=1)).isoformat()
    code = _new_otp_code()
    challenge_id = f"otp_{uuid4().hex}"
    with connect() as db:
        # Reserve the rate-limit slot atomically before an external paid call.
        db.execute("BEGIN IMMEDIATE")
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
        ip = _client_ip(request)
        if ip:
            ip_count = db.execute(
                "SELECT COUNT(*) FROM otp_challenges WHERE request_ip=? AND created_at>?",
                (ip, one_hour_ago),
            ).fetchone()[0]
            if int(ip_count) >= OTP_IP_HOURLY_LIMIT:
                raise HTTPException(429, "请求过于频繁，请稍后再试", headers={"Retry-After": "3600"})
        db.execute(
            "INSERT INTO otp_challenges(id,phone,code_hash,created_at,expires_at,request_ip) VALUES(?,?,?,?,?,?)",
            (challenge_id, phone, _otp_hash(phone, code), now_iso, _utc_after(OTP_TTL_SECONDS), _client_ip(request)),
        )
    delivery = await send_sms_code(phone, code)
    # Never return or log ``code``; the provider receives it only for sending.
    return {"ok": True, "delivery": delivery, "expires_in": OTP_TTL_SECONDS, "message": f"验证码发送请求已提交至 {_masked_phone(phone)}，5 分钟内有效"}


@router.post("/verify-code")
def verify_code(body: VerifyCodeBody, request: Request, response: Response) -> dict[str, Any]:
    phone = normalize_phone(body.phone)
    code = body.code.strip()
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    with connect() as db:
        # Serialize read/consume so concurrent requests cannot redeem one code twice.
        db.execute("BEGIN IMMEDIATE")
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
