from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from ..database import RESULT_DIR
from .base import GenerationProvider, ProviderOutput, ProviderRequest


class MockProvider(GenerationProvider):
    """流程演示供应商。生成结果明确带有 MOCK 标识，不能用于质量验收。"""

    async def submit_job(self, request: ProviderRequest) -> str:
        return f"mock_{uuid4().hex}"

    async def get_outputs(self, request: ProviderRequest) -> list[ProviderOutput]:
        target = RESULT_DIR / request.job_id
        target.mkdir(parents=True, exist_ok=True)
        scene = Image.open(request.scene_path).convert("RGB")
        outputs: list[ProviderOutput] = []
        for index in range(request.output_count):
            canvas = scene.copy()
            canvas.thumbnail((min(request.width, 1536), min(request.height, 1536)))
            if index == 1:
                canvas = ImageEnhance.Color(canvas).enhance(0.88)
            elif index == 2:
                canvas = ImageEnhance.Contrast(canvas).enhance(1.08)
            elif index == 3:
                canvas = canvas.filter(ImageFilter.GaussianBlur(0.35))
            draw = ImageDraw.Draw(canvas, "RGBA")
            draw.rectangle((0, 0, canvas.width, 42), fill=(4, 10, 18, 210))
            draw.text((14, 13), f"MOCK FLOW PREVIEW {index + 1}/4 - NOT AI OUTPUT", fill=(0, 242, 254, 255))
            output_path = target / f"candidate_{index + 1}.jpg"
            canvas.save(output_path, quality=92)
            outputs.append(ProviderOutput(path=output_path, metadata={"mock": True, "index": index + 1}))
        return outputs

    async def cancel_job(self, provider_job_id: str) -> None:
        return None

    def get_capabilities(self) -> dict[str, object]:
        return {
            "provider": "mock",
            "ready_for_commercial_generation": False,
            "supported_resolutions": ["1K", "2K"],
            "supported_aspect_ratios": ["1:1", "3:4", "4:3", "9:16", "16:9"],
            "max_outputs": 4,
            "supports_masks": False,
            "supports_pose": False,
            "supports_depth": False,
            "supports_inpainting": False,
            "message": "当前为流程模拟服务；API Key和专业构图模板接入后才能进行真实商拍生成。",
        }
