"""Non-generating connectivity checks for the configured visual planning API."""
from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx

from .replicate import ReplicaProviderError

_state: dict[str, object] = {
    "connected": False, "checked_at": None, "http_status": None,
    "error_code": "not_checked", "message": "尚未检查视觉策划服务。",
}


def plan_http_client(timeout: httpx.Timeout) -> httpx.AsyncClient:
    mode = os.getenv("DETAIL_PLAN_PROXY_MODE", "direct").strip().lower()
    if mode not in {"direct", "environment"}:
        raise ReplicaProviderError("invalid_proxy_mode", "DETAIL_PLAN_PROXY_MODE 只能是 direct 或 environment。")
    return httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=mode == "environment")


def snapshot() -> dict[str, object]:
    return dict(_state)


def _record(connected: bool, message: str, *, error_code: str | None = None, http_status: int | None = None) -> dict[str, object]:
    global _state
    _state = {
        "connected": connected, "checked_at": datetime.now(UTC).isoformat(),
        "http_status": http_status, "error_code": error_code, "message": message,
    }
    return snapshot()


async def probe() -> dict[str, object]:
    from .detail import plan_configuration

    try:
        _, endpoint, _ = plan_configuration()
        # No key and no POST body: any HTTP response proves this client's
        # DNS/TCP/TLS route, not authentication or generation permission.
        async with plan_http_client(httpx.Timeout(6.0)) as client:
            response = await client.get(endpoint, headers={"Accept": "application/json"})
        return _record(True, "视觉策划服务可连接；密钥和模型权限尚未验证。", http_status=response.status_code)
    except ReplicaProviderError as error:
        return _record(False, str(error), error_code=error.code)
    except httpx.ConnectTimeout:
        return _record(False, "视觉策划服务连接超时，后端会自动重试。", error_code="connect_timeout")
    except httpx.RequestError:
        return _record(False, "视觉策划服务无法连接，后端会自动重试；请检查网络或代理。", error_code="connect_failed")
