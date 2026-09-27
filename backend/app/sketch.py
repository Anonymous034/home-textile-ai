"""Sketch-to-image generation through the configured Agent Plan image provider."""
from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from .database import RESULT_DIR, UPLOAD_DIR
from .providers.replicate import ReplicaProvider, ReplicaProviderError, current_configuration

router = APIRouter(prefix="/api/sketch", tags=["sketch"])
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ASPECTS = {"3:4": (3, 4), "1:1": (1, 1), "4:3": (4, 3), "9:16": (9, 16), "16:9": (16, 9)}
EDGES = {"1K": 1024, "2K": 2048, "4K": 4096}


def output_size(aspect_ratio: str, resolution: str) -> tuple[int, int]:
    if aspect_ratio not in ASPECTS or resolution not in EDGES:
        raise HTTPException(422, "图片比例或分辨率无效。")
    x, y = ASPECTS[aspect_ratio]
    edge = EDGES[resolution]
    return (edge, round(edge * y / x / 64) * 64) if x >= y else (round(edge * x / y / 64) * 64, edge)


def generation_prompt(category: str, fabric: str, craft: str, b_mode: str, color: str, has_b: bool, has_reference: bool, target: tuple[int, int]) -> str:
    material = f"Fabric: {fabric or 'follow image 1'}. Craft: {craft or 'follow image 1'}."
    second = (
        "Image 2 is the B-version material/colorway reference; apply its design to the product shown in image 1."
        if b_mode == "image" and has_b else
        f"Apply solid B-version color {color} to the product while preserving its structure and pattern placement."
        if b_mode == "color" else
        "Keep the original colorway from image 1."
    )
    reference = "The final image is a visual reference for scene, lighting and styling only; do not copy its product identity." if has_reference else "Use a clean, realistic ecommerce product setting."
    return (
        f"Generate one photorealistic product image at {target[0]}x{target[1]} from the supplied design sketch. "
        f"Image 1 is the authoritative A-version sketch for product shape, composition, pattern placement and construction. "
        f"Product category: {category}. {material} {second} {reference} "
        "Convert drawn regions into realistic textile and product materials. Preserve the intended silhouettes, seams, print motifs and proportions. "
        "Natural fabric texture, coherent perspective and lighting, professional ecommerce photography. "
        "No extra objects obscuring the product, no invented logos or text, no watermark."
    )


async def save_image(upload: UploadFile, path: Path) -> None:
    if upload.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(415, "仅支持 JPG、PNG、WEBP 图片。")
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "图片为空或超过 20MB。")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from io import BytesIO
        with Image.open(BytesIO(data)) as opened:
            if opened.format not in {"JPEG", "PNG", "WEBP"}:
                raise HTTPException(415, "图片格式不受支持。")
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            image.save(path, "PNG", optimize=True)
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            path.unlink(missing_ok=True)
            raise HTTPException(413, "图片处理后超过 20MB，请缩小素材后重试。")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise HTTPException(422, "无法读取上传的图片。") from error


@router.get("/capabilities")
def capabilities() -> dict[str, object]:
    try:
        _, _, model = current_configuration()
        return {"configured": True, "model": model, "max_references": 12}
    except ReplicaProviderError as error:
        return {"configured": False, "max_references": 12, "message": str(error)}


@router.post("/generate")
async def generate(
    a_image: UploadFile = File(...),
    b_image: UploadFile | None = File(None),
    reference_image: UploadFile | None = File(None),
    b_mode: str = Form("image"),
    color: str = Form("#ffffff"),
    category: str = Form("四件套", max_length=100),
    fabric: str = Form("", max_length=100),
    craft: str = Form("", max_length=200),
    aspect_ratio: str = Form("3:4"),
    resolution: str = Form("1K"),
) -> dict[str, object]:
    if b_mode not in {"image", "color"} or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise HTTPException(422, "B 版配色参数无效。")
    if not category.strip():
        raise HTTPException(422, "请填写产品品类。")
    target = output_size(aspect_ratio, resolution)
    try:
        current_configuration()
    except ReplicaProviderError as error:
        raise HTTPException(503, str(error)) from error
    job_id = uuid4().hex
    folder = UPLOAD_DIR / "sketch" / job_id
    output = RESULT_DIR / "sketch" / job_id / "result.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    a_path = folder / "a.png"
    await save_image(a_image, a_path)
    paths: list[Path] = [a_path]
    if b_mode == "image" and b_image and b_image.filename:
        b_path = folder / "b.png"
        await save_image(b_image, b_path)
        paths.append(b_path)
    if reference_image and reference_image.filename:
        reference_path = folder / "reference.png"
        await save_image(reference_image, reference_path)
        paths.append(reference_path)
    prompt = generation_prompt(category.strip(), fabric.strip(), craft.strip(), b_mode, color, bool(b_mode == "image" and b_image and b_image.filename), bool(reference_image and reference_image.filename), target)
    try:
        metadata = await ReplicaProvider().generate(paths, target, False, "", output, lambda *_: None, prompt=prompt)
    except ReplicaProviderError as error:
        raise HTTPException(503 if error.retryable else 502, str(error)) from error
    return {"id": job_id, "result_url": f"/api/sketch/results/{job_id}", "output_size": list(target), "metadata": metadata}


@router.get("/results/{job_id}")
def result(job_id: str) -> FileResponse:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(404, "结果不存在。")
    path = RESULT_DIR / "sketch" / job_id / "result.png"
    if not path.is_file():
        raise HTTPException(404, "结果不存在。")
    return FileResponse(path, media_type="image/png", filename=f"sketch-{job_id}.png")
