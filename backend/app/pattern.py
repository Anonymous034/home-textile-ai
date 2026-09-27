"""Generate controlled pattern and color variants of the largest visible item."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .database import RESULT_DIR, UPLOAD_DIR
from .providers.replicate import ReplicaProvider, ReplicaProviderError, current_configuration
from .replicate import read_upload

router = APIRouter(prefix="/api/pattern", tags=["pattern"])
logger = logging.getLogger(__name__)
jobs: dict[str, dict] = {}
running: dict[str, asyncio.Task] = {}

STRENGTH = {
    "轻微": "Make a subtle, restrained pattern change; preserve most of the original surface appearance.",
    "适度": "Make a clearly visible but commercially plausible pattern change.",
    "明显": "Make a bold, clearly different pattern while preserving the item's shape and material realism.",
}
COLORS = {
    "保持配色": "Preserve the original colors of the target item; change its pattern only.",
    "智能配色": "Change the target item's colors to a harmonious new palette that suits the scene.",
    "同色系变化": "Change the target item's colors to distinct shades within its original color family.",
}


def extraction_prompt() -> str:
    return (
        "Analyze the supplied photograph and identify the single distinct object occupying the largest visible area, "
        "regardless of category. Curtains, bedding, rugs, garments and furniture all qualify; walls, floor and sky "
        "are background, not objects. Extract only the target object's existing surface pattern and colors into a "
        "clean, flat, front-facing, square textile or surface-design swatch. Reproduce the visible motif faithfully, "
        "including its scale, spacing and palette, and extend it naturally to fill the square. Remove the object's "
        "silhouette, folds, shadows, perspective, room and all other objects. If the target is plain, show its actual "
        "plain color and material texture without inventing a motif. No product photo, mockup, border, text or watermark."
    )


def variant_prompt(index: int, count: int, strength: str, color_mode: str, notes: str, action: str) -> str:
    emphasis = (
        "Prioritize recoloring the target item and coordinate its pattern with the new palette."
        if action == "recolor" else
        "Prioritize adding or changing the target item's decorative pattern."
    )
    return (
        "Edit the supplied photograph. First identify the single distinct object occupying the largest visible area "
        "in the image, regardless of category; it may be a curtain, bedding, sofa, rug, garment, or another object. "
        "Compare visible object area, not centrality, and ignore the background surfaces such as walls, floor and sky. "
        "Modify ONLY that identified object. Add a new decorative pattern if it is plain, or replace its "
        "existing pattern if patterned. Keep its silhouette, construction, folds, perspective, lighting, and realistic "
        "material texture. Do not change any other object, background, people, logos, or text. "
        f"{emphasis} {STRENGTH[strength]} {COLORS[color_mode]} "
        f"Create distinct design variant {index} of {count}; vary the motif from the other variants while honoring the "
        "selected strength and palette rule. "
        f"Additional user requirements for the target object: {notes.strip() if notes.strip() else 'none'}. "
        "Do not add any caption, watermark or new objects. Return the full edited photograph at the original framing."
    )


def public_job(job: dict) -> dict:
    return {key: job[key] for key in ("id", "status", "requested", "completed", "stage", "error", "result_urls")}


def save_job(job: dict) -> None:
    path = RESULT_DIR / "pattern" / job["id"] / "status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps(public_job(job), ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_job(job_id: str) -> dict | None:
    if len(job_id) != 32 or any(character not in "0123456789abcdef" for character in job_id):
        return None
    path = RESULT_DIR / "pattern" / job_id / "status.json"
    if not path.is_file():
        return None
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if job.get("id") != job_id:
        return None
    if job.get("status") in {"queued", "generating"}:
        job["status"] = "failed"
        job["stage"] = "后端重启，任务已中断"
        job["error"] = "后端已重启；已完成的图片仍可下载。请确认供应商任务记录后再重新生成。"
        save_job(job)
    jobs[job_id] = job
    return job


async def process(job_id: str, source: Path, target: tuple[int, int], strength: str, color_mode: str, notes: str, action: str) -> None:
    job = jobs[job_id]
    job["status"] = "generating"
    save_job(job)
    try:
        for index in range(1, job["requested"] + 1):
            job["stage"] = "正在提取最大物品的图案" if action == "design_extract" else f"正在生成第 {index} / {job['requested']} 张"
            save_job(job)
            output = RESULT_DIR / "pattern" / job_id / f"{index}.png"
            output.parent.mkdir(parents=True, exist_ok=True)
            await ReplicaProvider().generate(
                [source], target, False, "", output, lambda *_: None,
                prompt=extraction_prompt() if action == "design_extract" else variant_prompt(index, job["requested"], strength, color_mode, notes, action),
            )
            job["result_urls"].append(f"/api/pattern/jobs/{job_id}/results/{index}")
            job["completed"] = index
            save_job(job)
        job["status"] = "completed"
        job["stage"] = "图案提取完成" if action == "design_extract" else f"已完成 {job['requested']} 张"
    except ReplicaProviderError as error:
        job["status"] = "failed"
        job["stage"] = "生成中断"
        job["error"] = str(error)
    except asyncio.CancelledError:
        job["status"] = "failed"
        job["stage"] = "后端已停止"
        job["error"] = "后端停止了生成任务，请检查已完成的结果。"
        raise
    except Exception:
        logger.exception("Pattern generation failed for job %s", job_id)
        job["status"] = "failed"
        job["stage"] = "生成失败"
        job["error"] = "生成时发生错误，请检查后端日志。"
    finally:
        save_job(job)
        running.pop(job_id, None)


@router.post("/jobs", status_code=202)
async def create_job(
    image: UploadFile = File(...),
    count: int = Form(...),
    strength: str = Form(...),
    color_mode: str = Form(...),
    notes: str = Form(""),
    action: str = Form("extract"),
    request_id: str = Form(...),
):
    try:
        job_id = UUID(request_id).hex
    except (ValueError, AttributeError):
        raise HTTPException(422, "缺少有效的请求标识。") from None
    if (action == "design_extract" and count != 1) or (action != "design_extract" and count not in {2, 4, 6, 8}):
        raise HTTPException(422, "生成张数无效。")
    if strength not in STRENGTH or color_mode not in COLORS or action not in {"extract", "recolor", "design_extract"}:
        raise HTTPException(422, "生成参数无效。")
    if len(notes) > 500:
        raise HTTPException(422, "补充要求不能超过 500 字。")
    existing = jobs.get(job_id) or load_job(job_id)
    if existing is not None:
        return public_job(existing)
    if running:
        raise HTTPException(409, "已有花型任务正在生成，请等待完成。")
    try:
        current_configuration()
    except ReplicaProviderError as error:
        raise HTTPException(503, str(error)) from None
    content, width, height = await read_upload(image)
    source = UPLOAD_DIR / "pattern" / job_id / "source.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    jobs[job_id] = {
        "id": job_id, "status": "queued", "requested": count, "completed": 0,
        "stage": "准备连接 AI 服务", "error": None, "result_urls": [],
    }
    save_job(jobs[job_id])
    target = (1024, 1024) if action == "design_extract" else (width, height)
    running[job_id] = asyncio.create_task(process(job_id, source, target, strength, color_mode, notes, action))
    return public_job(jobs[job_id])


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id) or load_job(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在或后端已重启。")
    return public_job(job)


@router.get("/jobs/{job_id}/results/{index}")
def result(job_id: str, index: int):
    job = jobs.get(job_id) or load_job(job_id)
    if job is None or index < 1 or index > job["completed"]:
        raise HTTPException(404, "结果不存在。")
    path = RESULT_DIR / "pattern" / job_id / f"{index}.png"
    if not path.is_file():
        raise HTTPException(404, "结果不存在。")
    return FileResponse(path, media_type="image/png", filename=f"pattern-{index}.png")


async def shutdown_pattern() -> None:
    for task in list(running.values()):
        task.cancel()
    await asyncio.gather(*running.values(), return_exceptions=True)
