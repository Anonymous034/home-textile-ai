"""Only the new local replica surface: origin protection and streaming upload limit."""
import os

from starlette.responses import JSONResponse


class ReplicaGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(("/api/replicate", "/api/detail", "/api/buyer-show", "/api/local-edit", "/api/upscale", "/api/template-compose", "/api/pattern", "/api/sketch")):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        configured = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000").strip().rstrip("/")
        origins = {
            value.encode()
            for value in {
                configured,
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:3001",
                "http://127.0.0.1:3001",
            }
            if value
        }
        request_origin = headers.get(b"origin", b"").rstrip(b"/")
        if request_origin and request_origin not in origins:
            return await JSONResponse({"detail": "不允许此来源访问本机生成服务"}, 403)(scope, receive, send)
        if scope.get("client", ("",))[0] not in {"127.0.0.1", "::1"}:
            return await JSONResponse({"detail": "生成接口仅在本机可用"}, 403)(scope, receive, send)
        maximum = 81 * 1024 * 1024
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = maximum + 1
        if declared > maximum:
            return await JSONResponse({"detail": "上传总大小超过限制"}, 413)(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > maximum:
                from fastapi import HTTPException
                raise HTTPException(413, "上传总大小超过限制")
            return message

        await self.app(scope, limited_receive, send)
