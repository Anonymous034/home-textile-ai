"""Local-only, durable detail-page planning and explicit-confirmation render API.

Provider requests are never automatically repeated. Restarted in-flight jobs are
marked failed/uncertain, not replayed. Run this local service with one worker.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError

from .database import DATA_DIR, connect, utc_now
from .detail_models import PlanDocument, PlanRequest, RenderRequest
from .providers.detail import generate_plan, plan_configuration, render_item
from .providers.replicate import ReplicaProviderError, current_configuration

router = APIRouter(prefix="/api/detail", tags=["detail-page"])
FILES = DATA_DIR / "detail"
jobs: dict[str, asyncio.Task] = {}
render_slots = asyncio.Semaphore(2)
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", pattern=r"^[a-zA-Z0-9_-]{1,80}$")]


def failure(status: int, message: str, uncertain: bool = False):
    return HTTPException(status, {"message": message, "uncertain": uncertain})


def fingerprint(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read(kind: str, record_id: str) -> dict | None:
    with connect() as db:
        row = db.execute("SELECT fingerprint, payload FROM detail_records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
    return {"fingerprint": row["fingerprint"], "data": json.loads(row["payload"])} if row else None


def save(kind: str, record_id: str, signature: str, data: dict):
    with connect() as db:
        db.execute("INSERT INTO detail_records(kind,id,fingerprint,payload) VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload", (kind, record_id, signature, json.dumps(data, ensure_ascii=False)))


def initialize_detail():
    FILES.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS detail_records(kind TEXT NOT NULL, id TEXT NOT NULL, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,id))")
        rows = db.execute("SELECT * FROM detail_records WHERE kind IN ('plan','task')").fetchall()
    for row in rows:
        data = json.loads(row["payload"])
        if row["kind"] == "plan" and data.get("state") == "running":
            data.update(state="failed", message="服务重启，策划结果未确认；请核查供应商记录，未自动重试。", uncertain=True)
        elif row["kind"] == "task" and data.get("status") in ("queued", "running"):
            for item in data["items"]:
                if item["status"] in ("queued", "rendering"):
                    item.update(status="failed", error={"code": "interrupted", "message": "服务重启，未自动重复提交。请核查供应商记录后再决定是否重新生成。", "retryable": False})
            data.update(status="partial" if any(item["status"] == "completed" for item in data["items"]) else "failed", updatedAt=utc_now())
        else:
            continue
        save(row["kind"], row["id"], row["fingerprint"], data)


async def shutdown_detail():
    pending = list(jobs.values())
    for job in pending:
        job.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    jobs.clear()


def launch(key: str, coroutine):
    job = asyncio.create_task(coroutine)
    jobs[key] = job
    job.add_done_callback(lambda _: jobs.pop(key, None))
    return job


def asset_paths(request: PlanRequest) -> dict[str, Path]:
    paths = {}
    for asset in request.assets:
        record = read("asset", asset.assetId)
        if not record or record["data"]["clientId"] != asset.id:
            raise failure(422, "产品素材不存在或编号不匹配，请重新上传。")
        path = FILES / (asset.assetId + ".png")
        if not path.is_file():
            raise failure(422, "产品素材文件已不可用，请重新上传。")
        paths[asset.id] = path
    return paths


@router.post("/assets")
async def upload_asset(key: IdempotencyKey, file: Annotated[UploadFile, File()], clientId: Annotated[str, Form(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]):
    if key != clientId:
        raise failure(409, "素材请求标识不一致。")
    try:
        content = await file.read(20 * 1024 * 1024 + 1)
    finally:
        await file.close()
    if len(content) > 20 * 1024 * 1024:
        raise failure(413, "单张产品图不能超过 20MB。")
    signature = hashlib.sha256(content).hexdigest()
    previous = read("upload", key)
    if previous:
        if previous["fingerprint"] != signature:
            raise failure(409, "同一个素材编号不能上传不同图片。")
        return {"assetId": previous["data"]["assetId"]}
    try:
        with Image.open(io.BytesIO(content)) as original:
            if original.format not in ("JPEG", "PNG", "WEBP") or original.width * original.height > 24_000_000:
                raise ValueError()
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise failure(422, "图片损坏、格式不支持或超过 2400 万像素。") from None
    asset_id = str(uuid4())
    path = FILES / (asset_id + ".png")
    image.save(path, "PNG")
    data = {"assetId": asset_id, "clientId": clientId, "createdAt": utc_now()}
    save("asset", asset_id, signature, data)
    save("upload", key, signature, data)
    return {"assetId": asset_id}


async def plan_worker(key: str, signature: str, request: PlanRequest, paths: dict[str, Path]):
    try:
        plan = await generate_plan(request.input, [(asset.id, asset.role, paths[asset.id]) for asset in request.assets], key)
        data = {"state": "completed", "plan": plan.model_dump(), "assets": [asset.model_dump() for asset in request.assets]}
    except ReplicaProviderError as error:
        data = {"state": "failed", "message": str(error), "uncertain": error.uncertain}
    except asyncio.CancelledError:
        data = {"state": "failed", "message": "策划已中断，结果可能已计费，请核查供应商记录。", "uncertain": True}
    except Exception:
        data = {"state": "failed", "message": "策划处理异常，未自动重试；请核查供应商记录。", "uncertain": True}
    save("plan", key, signature, data)
    return data


@router.post("/plans")
async def create_plan(request: PlanRequest, key: IdempotencyKey):
    signature = fingerprint(request.model_dump())
    previous = read("plan", key)
    if previous:
        if previous["fingerprint"] != signature:
            raise failure(409, "策划标识已被其他参数使用。")
        data = previous["data"]
        if data["state"] == "completed":
            return data["plan"]
        if data["state"] == "running":
            raise failure(409, "策划请求仍在处理，请查询原请求。", True)
        raise failure(422, data["message"], data.get("uncertain", False))
    try:
        plan_configuration()
    except ReplicaProviderError as error:
        raise failure(503, str(error)) from None
    if sum(key.startswith("plan:") for key in jobs) >= 2:
        raise failure(429, "同时最多处理两个策划请求，请稍后再试。")
    paths = asset_paths(request)
    save("plan", key, signature, {"state": "running"})
    data = await asyncio.shield(launch("plan:" + key, plan_worker(key, signature, request, paths)))
    if data["state"] != "completed":
        raise failure(422, data["message"], data.get("uncertain", False))
    return data["plan"]


@router.get("/plans/{plan_id}")
def plan_status(plan_id: str):
    record = read("plan", plan_id)
    if not record:
        raise failure(404, "未查询到策划记录；图片生成尚未启动。")
    return {key: value for key, value in record["data"].items() if key != "assets"}


async def render_worker(request: RenderRequest, signature: str, paths: dict[str, Path], task: dict):
    directory = FILES / request.taskId
    directory.mkdir(exist_ok=True)

    def persist():
        task["updatedAt"] = utc_now()
        save("task", request.taskId, signature, task)

    async def one(index: int):
        item = task["items"][index]
        page = request.plan.items[index]
        async with render_slots:
            item.update(status="rendering", attempt=1)
            task["status"] = "running"
            persist()
            try:
                width, height = await render_item(request.plan, page, [paths[source] for source in page.sourceImageIds], directory / (page.id + ".png"))
                url = f"/api/detail/tasks/{request.taskId}/images/{page.id}"
                item.update(status="completed", previewUrl=url, downloadUrl=url + "?download=true", width=width, height=height)
            except ReplicaProviderError as error:
                item.update(status="failed", error={"code": error.code, "message": str(error), "retryable": not error.uncertain})
            except Exception:
                item.update(status="failed", error={"code": "internal", "message": "图片生成处理异常，结果可能已计费；请核查供应商记录，未自动重试。", "retryable": False})
            persist()

    try:
        await asyncio.gather(*(one(index) for index in range(len(task["items"]))))
    except asyncio.CancelledError:
        for item in task["items"]:
            if item["status"] in ("queued", "rendering"):
                item.update(status="failed", error={"code": "interrupted", "message": "生成中断，未自动重复提交。请核查供应商记录。", "retryable": False})
    finally:
        completed = sum(item["status"] == "completed" for item in task["items"])
        task["status"] = "completed" if completed == len(task["items"]) else "partial" if completed else "failed"
        if completed:
            task["exportUrl"] = f"/api/detail/tasks/{request.taskId}/export"
        persist()


@router.post("/tasks", status_code=202)
async def create_task(request: RenderRequest, key: IdempotencyKey):
    if key != request.taskId:
        raise failure(409, "任务编号与请求标识不一致。")
    signature = fingerprint(request.model_dump())
    previous = read("task", key)
    if previous:
        if previous["fingerprint"] != signature:
            raise failure(409, "此任务编号已经提交过其他版本方案。")
        return previous["data"]
    stored = read("plan", request.plan.planId)
    if not stored or stored["data"].get("state") != "completed":
        raise failure(422, "请先完成 AI 文字策划并确认方案。")
    original = PlanDocument.model_validate(stored["data"]["plan"])
    if request.plan.revision < original.revision or request.input.model_dump(exclude={"imageCount"}) != original.input.model_dump(exclude={"imageCount"}) or [asset.model_dump() for asset in request.assets] != stored["data"]["assets"]:
        raise failure(422, "产品参数或素材已改变，请重新生成文字方案。")
    try:
        current_configuration()
    except ReplicaProviderError as error:
        raise failure(503, str(error)) from None
    if sum(key.startswith("render:") for key in jobs) >= 2:
        raise failure(429, "已有两套图片正在生成，请完成后再提交。")
    paths = asset_paths(request)
    task = {"id": key, "planId": request.plan.planId, "planRevision": request.plan.revision, "status": "queued", "createdAt": utc_now(), "updatedAt": utc_now(),
            "items": [{"planItemId": item.id, "status": "queued", "attempt": 0} for item in request.plan.items]}
    save("task", key, signature, task)
    # Persist the confirmed JSON separately for ordered export and task recovery.
    save("confirmed", key, signature, request.plan.model_dump())
    launch("render:" + key, render_worker(request, signature, paths, task))
    return task


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    record = read("task", task_id)
    if not record:
        raise failure(404, "尚未查询到此图片任务，请核查原请求；不要重复提交。")
    return record["data"]


@router.get("/tasks/{task_id}/images/{item_id}")
def get_image(task_id: str, item_id: str, download: bool = False):
    task = get_task(task_id)
    item = next((item for item in task["items"] if item["planItemId"] == item_id and item["status"] == "completed"), None)
    if not item or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", task_id) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", item_id):
        raise failure(404, "图片尚未完成或不存在。")
    path = FILES / task_id / (item_id + ".png")
    if not path.is_file():
        raise failure(404, "结果文件已不可用。")
    return FileResponse(path, media_type="image/png", filename=item_id + ".png" if download else None)


@router.get("/tasks/{task_id}/export")
async def export_task(task_id: str):
    task = get_task(task_id)
    if task["status"] not in ("completed", "partial") or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", task_id):
        raise failure(409, "请等待图片生成结束后导出。")
    confirmed = read("confirmed", task_id)
    plan = confirmed["data"]
    path = FILES / task_id / "detail-suite.zip"

    def pack():
        temporary = path.with_name(str(uuid4()) + ".zip")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("confirmed-plan.json", json.dumps(plan, ensure_ascii=False, indent=2))
            archive.writestr("task-status.json", json.dumps(task, ensure_ascii=False, indent=2))
            for index, item in enumerate(task["items"]):
                if item["status"] == "completed":
                    archive.write(FILES / task_id / (item["planItemId"] + ".png"), f"{index + 1:02d}.png")
        temporary.replace(path)

    await asyncio.to_thread(pack)
    return FileResponse(path, filename="detail-suite.zip", media_type="application/zip")
