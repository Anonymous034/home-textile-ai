"""Request-scoped BYOK credential and authenticated account identity.

Personal API keys are supplied by the browser for a request and are never
persisted by this middleware. Phone sessions are resolved from the signed
HttpOnly cookie and only their account identity is exposed downstream.
"""
from __future__ import annotations

from contextvars import ContextVar

from starlette.responses import JSONResponse


current_user_key: ContextVar[str | None] = ContextVar("current_user_key", default=None)
current_account_id: ContextVar[str | None] = ContextVar("current_account_id", default=None)
current_auth_user: ContextVar[dict | None] = ContextVar("current_auth_user", default=None)


def valid_user_key(value: str) -> bool:
    return 20 <= len(value) <= 300 and not any(char.isspace() for char in value)


def _cookie_value(headers: dict[bytes, bytes], cookie_name: str) -> str | None:
    raw = headers.get(b"cookie", b"").decode("latin-1")
    for part in raw.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name == cookie_name:
            return value
    return None


class UserKeyScope:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        raw = headers.get(b"x-user-ark-key")
        key = None
        if raw is not None:
            try:
                key = raw.decode("ascii")
            except UnicodeDecodeError:
                key = ""
            if not valid_user_key(key):
                return await JSONResponse({"detail": "个人 API Key 格式无效"}, 400)(scope, receive, send)

        # Keep authentication lookup lazy to avoid an import cycle while the
        # auth router imports database helpers during application startup.
        session_user = None
        session_token = _cookie_value(headers, "studio_session")
        if session_token:
            try:
                from .auth import session_user_from_token

                session_user = session_user_from_token(session_token)
            except Exception:
                # An expired or malformed cookie behaves like a signed-out
                # visitor and must never make unrelated API requests fail.
                session_user = None

        key_token = current_user_key.set(key)
        account_token = current_account_id.set(session_user["account_id"] if session_user else None)
        auth_user_token = current_auth_user.set(session_user)
        try:
            await self.app(scope, receive, send)
        finally:
            current_auth_user.reset(auth_user_token)
            current_account_id.reset(account_token)
            current_user_key.reset(key_token)
