from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import socket
import ssl
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps

from ..database import RESULT_DIR
from ..user_key import current_user_key
from .base import GenerationProvider, ProviderOutput, ProviderRequest


class AgentPlanSeedreamSkillProvider(GenerationProvider):
    """Agent Plan 内置 Seedream Skill 的多图融合适配器。"""

    def __init__(self) -> None:
        self.api_key = current_user_key.get() or os.environ["ARK_API_KEY"]
        # Agent Plan 使用套餐资源名，不使用标准方舟数据面的日期版模型 ID。
        self.model = os.getenv("ARK_IMAGE_MODEL", "doubao-seedream-5.0-lite")
        self.endpoint = os.getenv(
            "ARK_IMAGE_ENDPOINT",
            "https://ark.cn-beijing.volces.com/api/plan/v3/images/generations",
        )
        self._responses: dict[str, dict[str, object]] = {}
        self._job_to_provider: dict[str, str] = {}
        self._connection_lock = threading.Lock()
        self._connection_state: dict[str, object] = {
            "connected": False, "checked_at": None, "http_status": None,
            "error_code": None, "message": "尚未检查 Agent Plan 图片服务。",
        }

    @staticmethod
    def _data_url(path: Path) -> str:
        """压缩参考图，避免浏览器上传的大图超过供应商限制。"""
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            image.thumbnail((1536, 1536), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=90, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    @staticmethod
    def _prompt(guidance: str | None = None) -> str:
        prompt = (
            "生成一张真实、自然、可用于家纺商品展示的商业摄影照片。"
            "参考图按顺序解释：图1是家具或床品主视角，是商品主体，必须最高优先级保留其轮廓、结构、材质、"
            "花型、缝线和颜色，不得改款；随后若有补充视角，仅用于补足同一商品细节；倒数第3张是模特参考，"
            "保留模特脸部、发型、体型和服装；倒数第2张是卧室场景，作为最终背景并保持空间透视；最后1张是"
            "构图示意图，白色区域代表模特动作和位置，蓝色区域代表家具摆放，只学习姿态、相对位置、镜头角度"
            "和遮挡关系，不要复制示意图的蓝白颜色、线稿或圆点。将模特自然放入场景，并按照构图动作与商品互动。"
            "统一人物、家具和场景的光线方向、色温、透视、阴影、清晰度和景深；人物不得悬浮、穿模，手脚正常，"
            "接触边缘自然。画面中只出现一个模特和一件主商品，不要文字、标志、水印、拼图或说明图。"
        )
        if guidance:
            prompt += f"用户补充要求：{guidance.strip()[:800]}。补充要求不得覆盖商品主视角保真和构图动作约束。"
        return prompt

    @staticmethod
    def _opener() -> urllib.request.OpenerDirector:
        """Use the same explicit proxy policy as the connectivity probe."""
        proxy_mode = os.getenv("ARK_PROXY_MODE", "direct").strip().lower()
        if proxy_mode == "direct":
            return urllib.request.build_opener(urllib.request.ProxyHandler({}))
        if proxy_mode == "environment":
            return urllib.request.build_opener()
        raise RuntimeError("ARK_PROXY_MODE 只能是 direct 或 environment。")

    def connection_status(self) -> dict[str, object]:
        with self._connection_lock:
            return dict(self._connection_state)

    def _record_connection(self, *, connected: bool, http_status: int | None = None, error_code: str | None = None, message: str) -> dict[str, object]:
        state: dict[str, object] = {
            "connected": connected, "checked_at": datetime.now(UTC).isoformat(),
            "http_status": http_status, "error_code": error_code, "message": message,
        }
        with self._connection_lock:
            self._connection_state = state
            return dict(state)

    @staticmethod
    def _connection_error(error: BaseException) -> tuple[str, str]:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        if isinstance(reason, (PermissionError,)) or getattr(reason, "winerror", None) in {5, 10013}:
            return "network_denied", "当前运行环境拒绝外网连接；请从 Windows 直接启动网站。"
        if isinstance(reason, socket.gaierror):
            return "dns_failed", "Agent Plan 域名解析失败，后端会自动重试。"
        if isinstance(reason, ssl.SSLError):
            return "tls_failed", "Agent Plan HTTPS 握手失败，请检查证书或代理。"
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "connect_timeout", "连接 Agent Plan 超时，后端会自动重试。"
        return "connect_failed", "无法连接 Agent Plan 图片服务，后端会自动重试。"

    def _probe_sync(self) -> int:
        # No key, image, or POST body: an HTTP 401 still proves this exact
        # urllib client can reach the provider without creating a generation.
        request = urllib.request.Request(self.endpoint, method="GET", headers={"Accept": "application/json"})
        try:
            with self._opener().open(request, timeout=6) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    async def probe_connection(self) -> dict[str, object]:
        try:
            status = await asyncio.to_thread(self._probe_sync)
            return self._record_connection(connected=True, http_status=status, message="Agent Plan 图片服务可连接；密钥和生成权限尚未验证。")
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            code, message = self._connection_error(error)
            return self._record_connection(connected=False, error_code=code, message=message)
        except RuntimeError:
            return self._record_connection(connected=False, error_code="invalid_proxy_mode", message="ARK_PROXY_MODE 只能是 direct 或 environment。")

    def _request_sync(self, request: ProviderRequest) -> dict[str, object]:
        references = [request.furniture_path, *request.extra_paths, request.model_path, request.scene_path]
        if request.composition_path:
            references.append(request.composition_path)
        resolution = {1024: "1K", 2048: "2K", 4096: "4K"}.get(max(request.width, request.height), "2K")
        body = {
            "model": self.model,
            "prompt": self._prompt(request.guidance),
            "image": [self._data_url(path) for path in references],
            "size": resolution,
            "sequential_image_generation": "disabled",
            "stream": False,
            "response_format": "url",
            "output_format": "png",
            "watermark": False,
        }
        encoded = json.dumps(body).encode("utf-8")
        http_request = urllib.request.Request(
            self.endpoint,
            data=encoded,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with self._opener().open(http_request, timeout=240) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Agent Plan 图片服务拒绝请求（HTTP {error.code}）；请检查密钥、额度或提交参数。") from None
        except urllib.error.URLError as error:
            code, message = self._connection_error(error)
            self._record_connection(connected=False, error_code=code, message=message)
            raise RuntimeError(message) from error

    async def submit_job(self, request: ProviderRequest) -> str:
        if current_user_key.get():
            from ..key_health import KeyHealthError, inspect_key
            try:
                await inspect_key(self.api_key)
            except KeyHealthError as error:
                raise RuntimeError(str(error)) from None
        connection = await self.probe_connection()
        if not connection["connected"]:
            raise RuntimeError(str(connection["message"]))
        provider_job_id = f"ark_{uuid4().hex}"
        self._responses[provider_job_id] = await asyncio.to_thread(self._request_sync, request)
        self._job_to_provider[request.job_id] = provider_job_id
        return provider_job_id

    async def get_outputs(self, request: ProviderRequest) -> list[ProviderOutput]:
        provider_job_id = self._job_to_provider.pop(request.job_id, "")
        payload = self._responses.pop(provider_job_id, {})
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or not data:
            raise RuntimeError("Agent Plan Seedream Skill 没有返回生成图片")

        item = data[0]
        if not isinstance(item, dict):
            raise RuntimeError("Agent Plan Seedream Skill 返回了无法识别的图片数据")
        folder = RESULT_DIR / request.job_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "result.png"
        if isinstance(item.get("b64_json"), str):
            path.write_bytes(base64.b64decode(item["b64_json"]))
        elif isinstance(item.get("url"), str):
            with self._opener().open(item["url"], timeout=90) as response:
                path.write_bytes(response.read())
        else:
            raise RuntimeError("Agent Plan Seedream Skill 响应中没有图片内容")
        with Image.open(path) as opened:
            image = opened.convert("RGB")
            if image.size != (request.width, request.height):
                image = ImageOps.fit(image, (request.width, request.height), method=Image.Resampling.LANCZOS)
            image.save(path, "PNG", optimize=True)
        return [ProviderOutput(path=path, metadata={"provider": "agent-plan-seedream-skill", "model": self.model, "size": f"{request.width}x{request.height}"})]

    async def cancel_job(self, provider_job_id: str) -> None:
        self._responses.pop(provider_job_id, None)
        stale_jobs = [job_id for job_id, current_id in self._job_to_provider.items() if current_id == provider_job_id]
        for job_id in stale_jobs:
            self._job_to_provider.pop(job_id, None)

    def get_capabilities(self) -> dict[str, object]:
        return {
            "provider": "volcengine-agent-plan-seedream-skill",
            "ready_for_commercial_generation": False,
            "supported_resolutions": ["1K", "2K", "4K"],
            "supported_aspect_ratios": ["1:1", "3:4", "4:3", "9:16", "16:9"],
            "max_outputs": 1,
            "supports_multiple_references": True,
            "supports_masks": False,
            "supports_pose": True,
            "supports_depth": False,
            "supports_inpainting": False,
            "message": "已接入 Agent Plan 内置 Seedream 5.0 lite Skill；正式商用前仍需用真实素材完成保真度验收。",
        }


# 兼容旧导入名；新代码应使用 AgentPlanSeedreamSkillProvider。
ArkProvider = AgentPlanSeedreamSkillProvider
