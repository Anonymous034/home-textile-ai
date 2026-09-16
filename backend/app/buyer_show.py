"""Durable buyer-show planning and explicit-confirmation rendering API."""
import asyncio
import json
import re
import zipfile
from uuid import uuid4

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

from . import detail
from .buyer_show_models import BuyerPlanRequest, BuyerRenderRequest, LifestylePlan
from .database import connect, utc_now
from .providers.buyer_show import generate, planner_mode, render_item
from .providers.replicate import ReplicaProviderError, current_configuration

router = APIRouter(prefix="/api/buyer-show", tags=["buyer-show"])
jobs: dict[str, asyncio.Task] = {}
KIND = "buyer_plan"
TASK_KIND = "buyer_task"
CONFIRMED_KIND = "buyer_confirmed"
render_slots = asyncio.Semaphore(2)


def initialize_buyer_show():
    # detail.initialize_detail owns the common local record store and runs first.
    with connect() as db:
        records = db.execute("SELECT kind,id,fingerprint,payload FROM detail_records WHERE kind IN (?,?)", (KIND, TASK_KIND)).fetchall()
    for record in records:
        data = json.loads(record["payload"])
        if record["kind"] == KIND and data["state"] == "running":
            data.update(state="failed", message="服务重启，买家秀策划结果未确认；请核查供应商记录，未自动重试。", uncertain=True, updatedAt=utc_now())
            detail.save(KIND, record["id"], record["fingerprint"], data)
        elif record["kind"] == TASK_KIND and data.get("status") in ("queued", "running"):
            for item in data["items"]:
                if item["status"] in ("queued", "rendering"):
                    item.update(status="failed", error={"code": "interrupted", "message": "服务重启，未自动重复提交。请核查供应商记录。", "retryable": False})
            data.update(status="partial" if any(item["status"] == "completed" for item in data["items"]) else "failed", updatedAt=utc_now())
            detail.save(TASK_KIND, record["id"], record["fingerprint"], data)


async def shutdown_buyer_show():
    pending = list(jobs.values())
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    jobs.clear()


@router.get("/capabilities")
def capabilities():
    message = ""
    try:
        mode = planner_mode()
    except ReplicaProviderError as error:
        mode = "invalid_configuration"
        message = str(error)
    try:
        current_configuration()
        rendering_available = True
    except ReplicaProviderError:
        rendering_available = False
    return {"planner_available": not message, "planner_mode": mode, "external_planner_configured": mode == "external_vision", "message": message, "rendering_available": rendering_available,
            "styles": ["更真实", "更精致"], "aspect_ratios": ["3:4", "16:9", "1:1", "4:3", "9:16"],
            "resolutions": ["1K", "2K", "4K"], "max_images": 12}


@router.get("/schema")
def schema():
    return LifestylePlan.model_json_schema()


# Share the validated local product asset store, without adding a second upload format.
router.add_api_route("/assets", detail.upload_asset, methods=["POST"])


async def worker(key: str, signature: str, request: BuyerPlanRequest, paths: dict):
    try:
        plan = await generate(request, paths)
        data = {"state": "completed", "plan": plan.model_dump(), "request": request.model_dump(), "updatedAt": utc_now()}
    except ReplicaProviderError as error:
        data = {"state": "failed", "message": str(error), "uncertain": error.uncertain, "updatedAt": utc_now()}
    except asyncio.CancelledError:
        data = {"state": "failed", "message": "买家秀策划已中断，结果可能已计费；请核查供应商记录。", "uncertain": True, "updatedAt": utc_now()}
    except Exception:
        data = {"state": "failed", "message": "买家秀策划处理异常，未自动重试；请核查供应商记录。", "uncertain": True, "updatedAt": utc_now()}
    detail.save(KIND, key, signature, data)
    return data


@router.post("/plans", response_model=LifestylePlan)
async def create_plan(request: BuyerPlanRequest, key: detail.IdempotencyKey, response: Response):
    signature = detail.fingerprint(request.model_dump())
    previous = detail.read(KIND, key)
    response.headers["X-Plan-Id"] = key
    if previous:
        if previous["fingerprint"] != signature:
            raise detail.failure(409, "同一个策划请求编号不能提交不同产品参数。")
        data = previous["data"]
        if data["state"] == "completed":
            return data["plan"]
        if data["state"] == "running":
            raise detail.failure(409, "买家秀方案仍在策划，请查询原请求编号。", True)
        raise detail.failure(422, data["message"], data.get("uncertain", False))
    try:
        mode = planner_mode()
    except ReplicaProviderError as error:
        raise detail.failure(503, str(error)) from None
    if len(jobs) >= 2:
        raise detail.failure(429, "最多同时处理两个买家秀策划请求，请稍后再试。")
    paths = detail.asset_paths(request)
    detail.save(KIND, key, signature, {"state": "running", "createdAt": utc_now()})
    task = asyncio.create_task(worker(key, signature, request, paths))
    jobs[key] = task
    task.add_done_callback(lambda _: jobs.pop(key, None))
    data = await asyncio.shield(task)
    if data["state"] != "completed":
        raise detail.failure(422, data["message"], data.get("uncertain", False))
    response.headers["X-Planner-Mode"] = mode
    return data["plan"]


@router.get("/plans/{plan_id}")
def get_plan_status(plan_id: str):
    record = detail.read(KIND, plan_id)
    if not record:
        raise detail.failure(404, "未找到此买家秀策划请求。")
    return record["data"]


@router.get("/plans/{plan_id}/output", response_model=LifestylePlan)
def get_plan_output(plan_id: str):
    data = get_plan_status(plan_id)
    if data["state"] != "completed":
        raise detail.failure(409, "此买家秀策划尚未完成，请先查询状态。", data["state"] == "running")
    return data["plan"]


async def render_worker(request: BuyerRenderRequest, signature: str, paths: dict, task: dict):
    directory = detail.FILES / request.taskId
    directory.mkdir(exist_ok=True)

    def persist():
        task["updatedAt"] = utc_now()
        detail.save(TASK_KIND, request.taskId, signature, task)

    async def one(index: int):
        result = task["items"][index]
        async with render_slots:
            result.update(status="rendering", attempt=1)
            task["status"] = "running"
            persist()
            try:
                width, height = await render_item(request.input, request.plan, index, list(paths.values()), directory / f"{index + 1:02d}.png")
                url = f"/api/buyer-show/tasks/{request.taskId}/images/{index + 1}"
                result.update(status="completed", previewUrl=url, downloadUrl=url + "?download=true", width=width, height=height)
            except ReplicaProviderError as error:
                result.update(status="failed", error={"code": error.code, "message": str(error), "retryable": not error.uncertain})
            except Exception:
                result.update(status="failed", error={"code": "internal", "message": "图片生成处理异常，结果可能已计费；请核查供应商记录，未自动重试。", "retryable": False})
            persist()

    try:
        await asyncio.gather(*(one(index) for index in range(len(task["items"]))))
    except asyncio.CancelledError:
        for item in task["items"]:
            if item["status"] in ("queued", "rendering"):
                item.update(status="failed", error={"code": "interrupted", "message": "图片生成已中断，未自动重复提交。", "retryable": False})
    finally:
        completed = sum(item["status"] == "completed" for item in task["items"])
        task["status"] = "completed" if completed == len(task["items"]) else "partial" if completed else "failed"
        if completed:
            task["exportUrl"] = f"/api/buyer-show/tasks/{request.taskId}/export"
        persist()


@router.post("/tasks", status_code=202)
async def create_task(request: BuyerRenderRequest, key: detail.IdempotencyKey):
    if key != request.taskId:
        raise detail.failure(409, "任务编号与请求标识不一致。")
    signature = detail.fingerprint(request.model_dump())
    previous = detail.read(TASK_KIND, key)
    if previous:
        if previous["fingerprint"] != signature:
            raise detail.failure(409, "此任务编号已经提交过其他版本方案。")
        return previous["data"]
    stored = detail.read(KIND, request.planId)
    if not stored or stored["data"].get("state") != "completed" or "request" not in stored["data"]:
        raise detail.failure(422, "请先生成并确认生活场景文字方案。")
    original = BuyerPlanRequest.model_validate(stored["data"]["request"])
    if request.input != original:
        raise detail.failure(422, "产品参数或素材已改变，请重新生成文字方案。")
    try:
        current_configuration()
    except ReplicaProviderError as error:
        raise detail.failure(503, str(error)) from None
    if sum(name.startswith("render:") for name in jobs) >= 2:
        raise detail.failure(429, "已有两套买家秀图片正在生成，请完成后再提交。")
    paths = detail.asset_paths(request.input)
    task = {"id": key, "planId": request.planId, "status": "queued", "createdAt": utc_now(), "updatedAt": utc_now(),
            "items": [{"index": item.index, "shotType": item.shot_type, "status": "queued", "attempt": 0} for item in request.plan.image_plan]}
    detail.save(TASK_KIND, key, signature, task)
    detail.save(CONFIRMED_KIND, key, signature, request.plan.model_dump())
    job = asyncio.create_task(render_worker(request, signature, paths, task))
    jobs["render:" + key] = job
    job.add_done_callback(lambda _: jobs.pop("render:" + key, None))
    return task


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    record = detail.read(TASK_KIND, task_id)
    if not record:
        raise detail.failure(404, "尚未查询到此图片任务，请核查原请求；不要重复提交。")
    return record["data"]


@router.get("/tasks/{task_id}/images/{index}")
def get_image(task_id: str, index: int, download: bool = False):
    task = get_task(task_id)
    item = next((item for item in task["items"] if item["index"] == index and item["status"] == "completed"), None)
    if not item or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", task_id):
        raise detail.failure(404, "图片尚未完成或不存在。")
    path = detail.FILES / task_id / f"{index:02d}.png"
    if not path.is_file():
        raise detail.failure(404, "结果文件已不可用。")
    return FileResponse(path, media_type="image/png", filename=f"buyer-show-{index:02d}.png" if download else None)


@router.get("/tasks/{task_id}/export")
async def export_task(task_id: str):
    task = get_task(task_id)
    if task["status"] not in ("completed", "partial") or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", task_id):
        raise detail.failure(409, "请等待图片生成结束后导出。")
    confirmed = detail.read(CONFIRMED_KIND, task_id)
    path = detail.FILES / task_id / "buyer-show-suite.zip"

    def pack():
        temporary = path.with_name(str(uuid4()) + ".zip")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("confirmed-plan.json", json.dumps(confirmed["data"], ensure_ascii=False, indent=2))
            archive.writestr("task-status.json", json.dumps(task, ensure_ascii=False, indent=2))
            for item in task["items"]:
                if item["status"] == "completed":
                    archive.write(detail.FILES / task_id / f"{item['index']:02d}.png", f"{item['index']:02d}.png")
        temporary.replace(path)

    await asyncio.to_thread(pack)
    return FileResponse(path, filename="buyer-show-suite.zip", media_type="application/zip")
