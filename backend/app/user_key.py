"""Request-scoped BYOK credential. Never persist or log a visitor's key."""
from __future__ import annotations

from contextvars import ContextVar

from starlette.responses import JSONResponse


current_user_key: ContextVar[str | None] = ContextVar("current_user_key", default=None)


def valid_user_key(value: str) -> bool:
    return 20 <= len(value) <= 300 and not any(char.isspace() for char in value)


class UserKeyScope:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        raw = headers.get(b"x-user-ark-key")
        if raw is None:
            return await self.app(scope, receive, send)
        try:
            key = raw.decode("ascii")
        except UnicodeDecodeError:
            key = ""
        if not valid_user_key(key):
            return await JSONResponse({"detail": "个人 API Key 格式无效"}, 400)(scope, receive, send)
        token = current_user_key.set(key)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user_key.reset(token)
