"""Non-generating, per-key Ark authentication and connectivity checks."""
from __future__ import annotations

import hashlib
import time
from collections import deque
from datetime import UTC, datetime

import httpx

from .providers.replicate import ENDPOINT, ReplicaProviderError, new_http_client


class KeyHealthError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


_history: dict[str, deque[tuple[float, bool]]] = {}


def _record(key: str, passed: bool) -> dict[str, object]:
    # Retain only hashes and short-lived pass/fail timestamps, never raw keys.
    digest = hashlib.sha256(key.encode()).hexdigest()
    now = time.monotonic()
    if len(_history) > 256 and digest not in _history:
        _history.pop(next(iter(_history)))
    checks = _history.setdefault(digest, deque(maxlen=5))
    checks.append((now, passed))
    recent = [value for at, value in checks if now - at <= 75]
    successes = 0
    for value in reversed(recent):
        if not value:
            break
        successes += 1
    return {
        "connected": passed,
        "stable": passed and successes >= 3,
        "consecutive_successes": successes,
        "checked_at": datetime.now(UTC).isoformat(),
    }


async def inspect_key(key: str) -> dict[str, object]:
    """Check auth before any billable request. An empty body cannot generate an image."""
    try:
        async with new_http_client() as client:
            authenticated = await client.post(ENDPOINT, json={}, headers={"Authorization": f"Bearer {key}"}, timeout=12)
            if authenticated.status_code in {401, 403}:
                raise KeyHealthError(401, "authentication", "API Key 无效或没有图片服务权限")
            if authenticated.status_code not in {400, 422}:
                raise KeyHealthError(503, "uncertain", "图片服务未返回明确的鉴权结果")
            anonymous = await client.post(ENDPOINT, json={}, timeout=12)
    except KeyHealthError:
        _record(key, False)
        raise
    except (httpx.RequestError, ReplicaProviderError, ValueError):
        _record(key, False)
        raise KeyHealthError(503, "connection", "图片服务暂时无法连接，请稍后重试") from None
    if anonymous.status_code not in {401, 403}:
        _record(key, False)
        raise KeyHealthError(503, "uncertain", "图片服务无法明确区分密钥鉴权结果")
    try:
        error = authenticated.json().get("error", {})
        message = str(error.get("message", "")).lower()
    except (ValueError, AttributeError, TypeError):
        message = ""
    if not any(word in message for word in ("model", "prompt", "missing", "required", "参数", "缺少")):
        _record(key, False)
        raise KeyHealthError(503, "uncertain", "图片服务未确认密钥可用")
    return _record(key, True)
