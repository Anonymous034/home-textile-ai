"""AI-backed detail enhancement and proportional enlargement."""
from __future__ import annotations

import math
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from .database import RESULT_DIR, UPLOAD_DIR
from .providers.replicate import ReplicaProvider, ReplicaProviderError, current_configuration

router = APIRouter(prefix="/api/upscale", tags=["upscale"])
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def target_size(width: int, height: int, mode: str) -> tuple[int, int]:
    factor = 2 if mode == "detail" else 4
    maximum_edge = 4096
    maximum_pixels = 16_000_000
    scale = min(factor, maximum_edge / max(width, height), math.sqrt(maximum_pixels / (width * height)))
    scale = max(1.0, scale)
    return max(64, round(width * scale / 8) * 8), max(64, round(height * scale / 8) * 8)


def enhancement_prompt(mode: str, width: int, height: int) -> str:
    common = (
        "Enhance the supplied image only, preserve the exact composition, crop, objects, geometry, identity, colors, materials, patterns, "
        "logos and all readable text. Restore natural photographic detail without redesigning or adding anything. No hallucinated objects, "
        "no changed product structure, no altered faces, no oversharpening, no halos, no plastic texture, no new text or watermark."
    )
    if mode == "detail":
        return common + " Remove compression artifacts and mild blur, recover subtle fabric and surface texture, clean edges and noise, maintain natural grain."
    return common + f" Produce a faithful high-resolution enlargement at {width}x{height}, reconstruct fine detail conservatively and keep edges clean and natural."


@router.get("/capabilities")
def capabilities():
    try:
        _, _, model = current_configuration()
        return {"configured": True, "model": model, "modes": ["detail", "upscale"], "max_images": 12}
    except ReplicaProviderError as error:
        return {"configured": False, "modes": ["detail", "upscale"], "max_images": 12, "message": str(error)}


@router.post("/generate")
async def generate(image: UploadFile = File(...), mode: str = Form(...)):
    if mode not in {"detail", "upscale"}:
        raise HTTPException(422, "处理方式无效。")
    data = await image.read(MAX_UPLOAD_BYTES + 1)
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "图片为空或超过 20MB。")
    job_id = uuid4().hex
    source = UPLOAD_DIR / "upscale" / job_id / "source.png"
    output = RESULT_DIR / "upscale" / job_id / "result.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)
    try:
        with Image.open(source) as opened:
            opened.verify()
        with Image.open(source) as opened:
            width, height = opened.size
    except (UnidentifiedImageError, OSError) as error:
        raise HTTPException(422, "无法读取这张图片。") from error
    target = target_size(width, height, mode)
    try:
        metadata = await ReplicaProvider().generate([source], target, False, "", output, lambda *_: None, prompt=enhancement_prompt(mode, *target))
    except ReplicaProviderError as error:
        raise HTTPException(503 if error.retryable else 502, str(error)) from error
    return {"id": job_id, "mode": mode, "source_size": [width, height], "output_size": list(target), "result_url": f"/api/upscale/results/{job_id}", "metadata": metadata}


@router.get("/results/{job_id}")
def result(job_id: str):
    if not job_id.isalnum() or len(job_id) != 32:
        raise HTTPException(404, "结果不存在。")
    path = RESULT_DIR / "upscale" / job_id / "result.png"
    if not path.is_file():
        raise HTTPException(404, "结果不存在。")
    return FileResponse(path, media_type="image/png", filename=f"enhanced-{job_id}.png")
