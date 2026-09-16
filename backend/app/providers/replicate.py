"""Agent Plan replica adapter; independent of the studio's fusion/cropping adapter."""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import io
import ipaddress
import json
import os
import re
import socket
import random
import ssl
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from ..replicate_rules import MAX_PIXELS, proportional_size, replica_prompt
from ..user_key import current_user_key
from ..account import record_work

ENDPOINT = "https://ark.cn-beijing.volces.com/api/plan/v3/images/generations"
MAX_RESPONSE = 64 * 1024 * 1024
CONNECT_ATTEMPTS = 3
DOWNLOAD_ATTEMPTS = 3
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_COOLDOWN_SECONDS = 30
# The Agent Plan endpoint can hand results off to Volcengine's object-storage
# CDN.  Those CDN names may resolve through an enterprise DNS proxy to an
# address Python classifies as non-global, even though the HTTPS origin is a
# provider-owned public endpoint.  Keep this exception intentionally narrow:
# it applies only to the provider's registered DNS suffixes, never to a URL
# supplied by a user or another API.
TRUSTED_RESULT_HOST_SUFFIXES = (".volces.com", ".volcengine.com")


class ReplicaProviderError(Exception):
    def __init__(self, code: str, message: str, uncertain: bool = False, *, retryable: bool = False, phase: str = "failed", attempts: int = 0):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain
        self.retryable = retryable
        self.phase = phase
        self.attempts = attempts


class ConnectivityState:
    def __init__(self) -> None:
        self.consecutive_failures = 0
        self.circuit_open_until = 0.0
        self.last_success_at: str | None = None
        self.last_failure_at: str | None = None
        self.last_error_code: str | None = None

    def success(self) -> None:
        self.consecutive_failures = 0
        self.circuit_open_until = 0.0
        self.last_success_at = datetime.now(UTC).isoformat()
        self.last_error_code = None

    def failure(self, code: str) -> None:
        self.consecutive_failures += 1
        self.last_failure_at = datetime.now(UTC).isoformat()
        self.last_error_code = code
        if self.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
            self.circuit_open_until = time.monotonic() + CIRCUIT_COOLDOWN_SECONDS

    def snapshot(self) -> dict[str, object]:
        remaining = max(0, round(self.circuit_open_until - time.monotonic()))
        return {
            "connected": bool(self.last_success_at) and self.consecutive_failures == 0 and remaining == 0,
            "circuit_open": remaining > 0,
            "retry_after_seconds": remaining,
            "consecutive_failures": self.consecutive_failures,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "last_error_code": self.last_error_code,
        }


connectivity = ConnectivityState()


def current_configuration() -> tuple[str, str, str]:
    key = current_user_key.get() or os.getenv("ARK_API_KEY", "").strip()
    if len(key) < 20 or any(c.isspace() for c in key) or "replace_with" in key:
        raise ReplicaProviderError("not_configured", "未配置有效的本机 API 密钥，请先完成安全配置。")
    endpoint = os.getenv("ARK_IMAGE_ENDPOINT", ENDPOINT).strip()
    if endpoint != ENDPOINT:
        raise ReplicaProviderError("unsupported_endpoint", "复刻目前仅支持已核对的火山方舟 Agent Plan 专用接口，请检查本机配置。")
    model = os.getenv("ARK_IMAGE_MODEL", "doubao-seedream-5.0-lite").strip()
    return key, endpoint, model


def new_http_client() -> httpx.AsyncClient:
    """Create the provider client without inheriting an injected process proxy.

    The local desktop runtime can inject a proxy that accepts CONNECT and then
    terminates TLS, which httpx reports as an immediate network interruption.
    This adapter talks only to the fixed, validated Ark endpoint and its
    validated result URLs, so a direct connection is both narrower and more
    reliable here.
    """
    proxy_mode = os.getenv("ARK_PROXY_MODE", "direct").strip().lower()
    if proxy_mode not in {"direct", "environment"}:
        raise ReplicaProviderError("invalid_proxy_mode", "ARK_PROXY_MODE 只能是 direct 或 environment。")
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=20, read=300, write=60, pool=20),
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=2, keepalive_expiry=30),
        follow_redirects=False,
        trust_env=proxy_mode == "environment",
    )


async def backoff(attempt: int) -> None:
    await asyncio.sleep(min(4.0, 0.4 * (2 ** (attempt - 1))) + random.uniform(0, 0.2))


def connection_failure(error: Exception) -> tuple[str, str]:
    """Give a safe, actionable diagnosis without exposing network or key details."""
    causes: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in causes:
        causes.append(current)
        current = current.__cause__ or current.__context__
    if any(isinstance(cause, PermissionError) or getattr(cause, "winerror", None) in {5, 10013} for cause in causes):
        return "network_denied", "当前运行环境拒绝 AI 服务的外网连接；后端会自动重试，但需要允许此程序访问网络。"
    if any(isinstance(cause, socket.gaierror) for cause in causes):
        return "dns_failed", "AI 服务域名解析失败；后端会自动重试，请检查 DNS 或网络连接。"
    if any(isinstance(cause, ssl.SSLError) for cause in causes):
        return "tls_failed", "已连到 AI 服务，但 HTTPS 握手失败；请检查本机证书、代理或安全软件。"
    if isinstance(error, httpx.ConnectTimeout) or any(isinstance(cause, TimeoutError) for cause in causes):
        return "tcp_timeout", "连接 AI 服务的 443 端口超时；后端会自动重试，请检查网络或防火墙。"
    if any(isinstance(cause, OSError) and getattr(cause, "winerror", None) in {10051, 10060, 10061, 10065} for cause in causes):
        return "tcp_unreachable", "无法连接 AI 服务的 443 端口；后端会自动重试，请检查网络或防火墙。"
    return "connect_failed", "无法连接 AI 服务；后端会自动重试，请检查本机网络、防火墙或代理设置。"


async def check_connectivity(client: httpx.AsyncClient | None = None) -> dict[str, object]:
    """Perform a non-generating HTTP/TLS probe against the fixed Ark endpoint."""
    _, endpoint, _ = current_configuration()
    state = connectivity.snapshot()
    personal = current_user_key.get() is not None
    if state["circuit_open"] and not personal:
        raise ReplicaProviderError("circuit_open", "AI 服务连接暂时熔断，请稍后重试。", retryable=True, phase="connecting")
    owned = client is None
    probe_client = client or new_http_client()
    try:
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            try:
                response = await probe_client.get(endpoint, headers={"Accept": "application/json"})
                # Any HTTP response proves DNS, TCP and TLS connectivity.  The
                # unauthenticated probe normally returns 401 and never creates
                # a generation task.
                if personal:
                    return {"connected": True, "http_status": response.status_code, "phase": "ready"}
                connectivity.success()
                return {**connectivity.snapshot(), "http_status": response.status_code, "phase": "ready"}
            except (httpx.ConnectError, httpx.ConnectTimeout) as error:
                if attempt == CONNECT_ATTEMPTS:
                    code, message = connection_failure(error)
                    if not personal:
                        connectivity.failure(code)
                    raise ReplicaProviderError(code, message, retryable=True, phase="connecting", attempts=attempt) from None
                await backoff(attempt)
    finally:
        if owned:
            await probe_client.aclose()


def explicit_size_bounds(payload: object) -> tuple[int, int] | None:
    """Do not borrow standard Ark limits. Only use a size rejection from this endpoint."""
    if not isinstance(payload, dict) or not isinstance(payload.get("error"), dict):
        return None
    error = payload["error"]
    code = str(error.get("code", "")).lower()
    message = str(error.get("message", "")).lower()
    if "invalidparameter" not in code or not re.search(r"\bsize\b|像素", message):
        return None
    if re.search(r"input|reference|image\[|参考|输入", message):
        return None
    # Known explicit validation wording; unrecognised errors never trigger another call.
    between = re.search(r"(?:between|range|范围)\D{0,15}(\d{6,9})\D{1,15}(\d{6,9})", message)
    if between:
        minimum, maximum = map(int, between.groups())
    else:
        low = re.search(r"(?:at least|no less than|minimum(?: is)?|不小于|至少)\D{0,5}(\d{6,9})", message)
        high = re.search(r"(?:at most|no more than|maximum(?: is)?|不超过|至多)\D{0,5}(\d{6,9})", message)
        if not low and not high:
            return None
        minimum = int(low[1]) if low else 4096
        maximum = int(high[1]) if high else MAX_PIXELS
    if not 4096 <= minimum <= maximum:
        return None
    return minimum, min(maximum, MAX_PIXELS)


def http_failure(status: int) -> ReplicaProviderError:
    if status in (401, 403):
        return ReplicaProviderError("authentication", "密钥鉴权或模型权限失败，请检查 Agent Plan 密钥和套餐权限。")
    if status == 429:
        return ReplicaProviderError("rate_limited", "接口限流或套餐额度不足，未自动重试。请稍后检查额度再决定是否重试。")
    if status == 400:
        return ReplicaProviderError("invalid_parameters", "接口拒绝了图片或生成参数，未生成结果。请检查素材；当前请求未自动重复提交。")
    if status >= 500:
        return ReplicaProviderError("provider_unavailable", "生成服务暂不可用，调用结果可能不确定。请先核查供应商记录，重试可能重复计费。", True)
    return ReplicaProviderError("provider_rejected", f"生成接口返回 HTTP {status}，未自动重试。")


async def public_download_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ReplicaProviderError("unsafe_result_url", "接口返回了不安全的图片下载地址，已停止下载。", True)
    hostname = parsed.hostname.rstrip(".").lower()
    # Result links from the only supported provider can legitimately use its
    # CDN, whose DNS response is not reliable evidence of Internet routability
    # on every local network.  Restricting the bypass to a dot-prefixed suffix
    # avoids matching lookalikes such as ``notvolces.com``.
    if hostname.endswith(TRUSTED_RESULT_HOST_SUFFIXES):
        return
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError()
    except (OSError, ValueError):
        raise ReplicaProviderError("unsafe_result_url", "无法安全验证图片下载地址，请核查供应商结果。", True) from None


async def read_limited(response: httpx.Response, limit: int = MAX_RESPONSE) -> bytes:
    content = bytearray()
    async for part in response.aiter_bytes():
        content.extend(part)
        if len(content) > limit:
            raise ReplicaProviderError("result_too_large", "接口返回数据过大，已停止接收；重试可能再次计费。", True)
    return bytes(content)


def finish_image(content: bytes, path: Path, target: tuple[int, int]) -> dict[str, object]:
    try:
        with Image.open(io.BytesIO(content)) as original:
            if original.width * original.height > MAX_PIXELS:
                raise ValueError()
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ReplicaProviderError("invalid_image", "接口返回的图片损坏或超出安全像素限制；未标记为生成成功。", True) from None
    width, height = image.size
    if width * target[1] != height * target[0]:
        raise ReplicaProviderError("ratio_mismatch", "生成结果的宽高比与目标不符。为避免裁剪或拉伸，已停止交付；重试可能再次计费。", True)
    if image.size != target:
        image = image.resize(target, Image.Resampling.LANCZOS)
    temporary = path.with_suffix(path.suffix + ".part")
    image.save(temporary, "PNG", optimize=True)
    temporary.replace(path)
    delivered = path.read_bytes()
    return {
        "returned_size": [width, height],
        "target_size": list(target),
        "bytes": len(delivered),
        "sha256": hashlib.sha256(delivered).hexdigest(),
        "format": "png",
    }


class ReplicaProvider:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client

    async def generate(self, paths: list[Path], target: tuple[int, int], remove_text: bool, notes: str, output: Path, stage, *, prompt: str | None = None) -> dict:
        key, endpoint, model = current_configuration()
        personal = current_user_key.get() is not None
        if personal:
            from ..key_health import KeyHealthError, inspect_key
            stage("connecting", "正在重新验证个人 API Key")
            try:
                await inspect_key(key)
            except KeyHealthError as error:
                raise ReplicaProviderError(error.code, str(error), retryable=error.status_code == 503, phase="connecting") from None
        images = []
        for path in paths:
            if path.stat().st_size > 20 * 1024 * 1024:
                raise ReplicaProviderError("input_too_large", "图片归一化后超过 20MB，请使用更小的素材。")
            images.append("data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii"))
        body = {
            "model": model, "image": images,
            "prompt": prompt if prompt is not None else replica_prompt(remove_text, notes, len(paths) - 2, *target),
            "size": f"{target[0]}x{target[1]}", "sequential_image_generation": "disabled",
            "stream": False, "response_format": "b64_json", "output_format": "png", "watermark": False,
        }
        client = self.client or new_http_client()
        generation_size = target
        size_evidence = "requested_original"
        try:
            if self.client is None:
                stage("connecting", "正在检查 AI 服务连接")
                await check_connectivity(client)
            for attempt in range(2):
                content = None
                response_status = None
                for connect_attempt in range(1, CONNECT_ATTEMPTS + 1):
                    try:
                        stage("submitting", "正在向 AI 服务提交生成任务")
                        async with client.stream("POST", endpoint, json=body, headers={"Authorization": f"Bearer {key}"}) as response:
                            stage("receiving", "AI 已接收请求，正在等待生成结果")
                            response_status = response.status_code
                            content = await read_limited(response)
                        if not personal:
                            connectivity.success()
                        break
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        if connect_attempt == CONNECT_ATTEMPTS:
                            if not personal:
                                connectivity.failure("connect_failed")
                            raise ReplicaProviderError("connect_failed", "提交前无法连接 AI 服务，未产生生成请求。", retryable=True, phase="connecting", attempts=connect_attempt) from None
                        await backoff(connect_attempt)
                    except (httpx.WriteError, httpx.ReadError, httpx.ReadTimeout, httpx.WriteTimeout):
                        if not personal:
                            connectivity.failure("network_uncertain")
                        raise ReplicaProviderError("network_uncertain", "AI 服务连接在提交后中断，结果不确定；未自动重试。", True, phase="receiving", attempts=connect_attempt) from None
                if content is None or response_status is None:
                    raise ReplicaProviderError("network", "AI 服务没有返回响应。", retryable=True, phase="connecting")
                try:
                    payload = json.loads(content)
                except (ValueError, UnicodeError):
                    if response_status != 200:
                        raise http_failure(response_status)
                    raise ReplicaProviderError("invalid_response", "接口未返回可识别的结果，未自动重试。", True) from None
                if response_status == 400 and attempt == 0:
                    bounds = explicit_size_bounds(payload)
                    if bounds:
                        try:
                            generation_size = proportional_size(*target, *bounds)
                        except ValueError as error:
                            raise ReplicaProviderError("unsupported_size", str(error)) from None
                        if generation_size != target:
                            body["size"] = f"{generation_size[0]}x{generation_size[1]}"
                            size_evidence = f"endpoint_rejection_pixel_bounds:{bounds[0]}..{bounds[1]}"
                            stage("connecting", "原尺寸被接口明确拒绝，准备按等比例尺寸重新提交")
                            continue
                if response_status != 200:
                    raise http_failure(response_status)
                break
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
                raise ReplicaProviderError("invalid_response", "接口没有返回唯一的一张结果图片，未自动重试。", True)
            item = data[0]
            stage("downloading", "AI 已返回结果，正在下载图片")
            if isinstance(item.get("b64_json"), str):
                try:
                    image_bytes = base64.b64decode(item["b64_json"], validate=True)
                except (ValueError, binascii.Error):
                    raise ReplicaProviderError("invalid_image", "接口返回了无效图片编码。", True) from None
            elif isinstance(item.get("url"), str):
                url = item["url"]
                image_bytes = None
                for redirect in range(4):
                    await public_download_url(url)
                    for download_attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
                        try:
                            async with client.stream("GET", url) as response:
                                if response.status_code in (301, 302, 303, 307, 308) and redirect < 3:
                                    url = urljoin(url, response.headers.get("location", ""))
                                    break
                                if response.status_code != 200:
                                    raise ReplicaProviderError("download_failed", "AI 已返回结果，但下载失败。请核查供应商记录。", True, phase="downloading")
                                image_bytes = await read_limited(response)
                                break
                        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError, httpx.ReadTimeout):
                            if download_attempt == DOWNLOAD_ATTEMPTS:
                                raise ReplicaProviderError("download_failed", "AI 已返回结果，但图片下载连接失败。", True, retryable=True, phase="downloading", attempts=download_attempt) from None
                            await backoff(download_attempt)
                    if image_bytes is not None:
                        break
                if image_bytes is None:
                    raise ReplicaProviderError("download_failed", "AI 已返回结果，但未能下载图片。", True, retryable=True, phase="downloading")
            else:
                raise ReplicaProviderError("invalid_response", "接口结果中没有图片内容。", True)
            stage("validating", "正在校验图片完整性与像素尺寸")
            result = await asyncio.to_thread(finish_image, image_bytes, output, target)
            record_work(output)
            return {"model": model, "generation_size": list(generation_size), **result, "size_evidence": size_evidence, "quality_status": "pending_review"}
        except httpx.TimeoutException:
            raise ReplicaProviderError("timeout", "等待接口超时，结果不确定，未自动重试。请先核查供应商记录，重试可能重复计费。", True) from None
        except httpx.RequestError:
            if not personal:
                connectivity.failure("network_uncertain")
            raise ReplicaProviderError("network_uncertain", "与 AI 服务的连接中断，结果不确定，未自动重试。请先核查供应商记录。", True, phase="receiving") from None
        finally:
            if self.client is None:
                await client.aclose()
