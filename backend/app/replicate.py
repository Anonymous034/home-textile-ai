from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from .database import UPLOAD_DIR, RESULT_DIR, connect, utc_now, expires_at
from .providers.replicate import ReplicaProvider, ReplicaProviderError, check_connectivity, connectivity, current_configuration, new_http_client
from .replicate_rules import target_size, validate_size
from .user_key import current_user_key

router = APIRouter(prefix="/api/replicate", tags=["爆款复刻"])
tasks: dict[str, asyncio.Task] = {}
generation_lock: asyncio.Semaphore | None = None
provider_client = None
connectivity_monitor: asyncio.Task | None = None
logger = logging.getLogger(__name__)
ACTIVE = ("queued", "connecting", "submitting", "receiving", "generating", "downloading", "validating")
MAX_BYTES = 20 * 1024 * 1024


def initialize_replica() -> None:
    global generation_lock
    generation_lock = asyncio.Semaphore(1)
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS replica_jobs (
            id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE,
            fingerprint TEXT NOT NULL, parent_id TEXT,
            main_path TEXT NOT NULL, reference_path TEXT NOT NULL, extra_paths TEXT NOT NULL,
            reference_width INTEGER NOT NULL, reference_height INTEGER NOT NULL,
            target_width INTEGER NOT NULL, target_height INTEGER NOT NULL,
            remove_text INTEGER NOT NULL, custom_notes TEXT NOT NULL,
            status TEXT NOT NULL, stage TEXT NOT NULL, error_code TEXT, error TEXT,
            uncertain INTEGER NOT NULL DEFAULT 0, output_path TEXT, metadata TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL
        );
        DROP INDEX IF EXISTS idx_replica_active_fingerprint;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_replica_active_fingerprint ON replica_jobs(fingerprint)
            WHERE status IN ('queued','connecting','submitting','receiving','generating','downloading','validating');
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(replica_jobs)")}
        additions = {
            "phase": "TEXT NOT NULL DEFAULT 'queued'",
            "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "retryable": "INTEGER NOT NULL DEFAULT 0",
            "claimed_at": "TEXT",
            "uses_personal_key": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, declaration in additions.items():
            if name not in columns:
                db.execute(f"ALTER TABLE replica_jobs ADD COLUMN {name} {declaration}")
        now = utc_now()
        db.execute("UPDATE replica_jobs SET status='interrupted',phase='interrupted',stage='个人密钥会话已结束',error_code='personal_key_expired',error='请返回首页重新验证个人密钥，再提交新任务。',retryable=0,updated_at=? WHERE uses_personal_key=1 AND status IN ('queued','connecting')", (now,))
        db.execute("UPDATE replica_jobs SET status='queued',phase='queued',stage='服务已恢复，等待重新进入队列',claimed_at=NULL,updated_at=? WHERE status='connecting'", (now,))
        db.execute("UPDATE replica_jobs SET status='interrupted',phase='interrupted',stage='服务已重启，任务提交状态不确定',error_code='interrupted',error='调用结果可能不确定，请先核查供应商记录；重试可能再次计费。',uncertain=1,retryable=0,updated_at=? WHERE status IN ('submitting','receiving','generating','downloading','validating')", (now,))
        queued = [row[0] for row in db.execute("SELECT id FROM replica_jobs WHERE status='queued' ORDER BY created_at")]
    for job_id in queued:
        schedule(job_id)


async def start_replica_connectivity() -> None:
    """Probe once during startup, then keep reconnecting in the background."""
    global connectivity_monitor
    if os.getenv("REPLICA_DISABLE_MONITOR") == "1":
        return
    try:
        result = await asyncio.wait_for(check_connectivity(get_provider_client()), timeout=8)
        logger.info("AI service connectivity ready (HTTP %s)", result["http_status"])
    except (ReplicaProviderError, httpx.RequestError, TimeoutError) as error:
        logger.warning("AI service unavailable at startup: %s; retrying in background", error)
    connectivity_monitor = asyncio.create_task(monitor_connectivity(initial_delay=5))


def get_provider_client():
    global provider_client
    if provider_client is None or provider_client.is_closed:
        provider_client = new_http_client()
    return provider_client


async def monitor_connectivity(initial_delay: float = 0) -> None:
    if initial_delay:
        await asyncio.sleep(initial_delay)
    while True:
        try:
            await check_connectivity(get_provider_client())
        except (ReplicaProviderError, httpx.RequestError) as error:
            logger.warning("AI service connectivity retry failed: %s", error)
        await asyncio.sleep(5)


async def shutdown_replica() -> None:
    global provider_client, connectivity_monitor
    if connectivity_monitor:
        connectivity_monitor.cancel()
    pending = list(tasks.values())
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    if connectivity_monitor:
        await asyncio.gather(connectivity_monitor, return_exceptions=True)
        connectivity_monitor = None
    if provider_client is not None and not provider_client.is_closed:
        await provider_client.aclose()
    provider_client = None


def require_provider() -> None:
    try:
        current_configuration()
    except ReplicaProviderError as error:
        raise HTTPException(503, str(error)) from None


def row_for(job_id: str) -> dict:
    with connect() as db:
        row = db.execute("SELECT * FROM replica_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "没有找到该复刻任务")
    return dict(row)


def public_job(row: dict) -> dict:
    return {
        **{key: row[key] for key in ("id", "parent_id", "status", "stage", "error_code", "error", "target_width", "target_height", "reference_width", "reference_height", "custom_notes", "created_at", "updated_at", "expires_at")},
        "remove_text": bool(row["remove_text"]), "uncertain": bool(row["uncertain"]),
        "phase": row.get("phase") or row["status"],
        "attempt_count": int(row.get("attempt_count") or 0),
        "retryable": bool(row.get("retryable")),
        "quality_status": "pending_review" if row["status"] == "completed" else None,
        "metadata": json.loads(row["metadata"]) if row["metadata"] else None,
        "result_metadata": json.loads(row["metadata"]) if row["metadata"] else None,
        "preview_url": f"/api/replicate/jobs/{row['id']}/result" if row["status"] == "completed" else None,
        "download_url": f"/api/replicate/jobs/{row['id']}/result?download=true" if row["status"] == "completed" else None,
        "source_urls": {"main": f"/api/replicate/jobs/{row['id']}/sources/main", "reference": f"/api/replicate/jobs/{row['id']}/sources/reference"},
    }


def set_stage(job_id: str, status: str, stage: str) -> None:
    with connect() as db:
        increment = 1 if status == "submitting" else 0
        db.execute("UPDATE replica_jobs SET status=?,phase=?,stage=?,attempt_count=attempt_count+?,claimed_at=COALESCE(claimed_at,?),updated_at=? WHERE id=?", (status, status, stage, increment, utc_now(), utc_now(), job_id))


async def process(job_id: str) -> None:
    try:
        if generation_lock is None:
            raise RuntimeError("replica lifecycle not initialized")
        async with generation_lock:
            row = row_for(job_id)
            paths = [Path(row["main_path"]), *map(Path, json.loads(row["extra_paths"])), Path(row["reference_path"])]
            if any(not path.is_file() for path in paths):
                raise ReplicaProviderError("missing_source", "任务素材已过期或缺失，请重新上传。")
            folder = RESULT_DIR / "replicate" / job_id
            folder.mkdir(parents=True, exist_ok=True)
            output = folder / "result.png"
            try:
                async with asyncio.timeout(420):
                    set_stage(job_id, "connecting", "正在检查 AI 服务连接")
                    await check_connectivity(get_provider_client())
                    metadata = await ReplicaProvider(get_provider_client()).generate(paths, (row["target_width"], row["target_height"]), bool(row["remove_text"]), row["custom_notes"], output, lambda status, stage: set_stage(job_id, status, stage))
            except TimeoutError:
                raise ReplicaProviderError("timeout", "任务等待超时，结果可能不确定，未自动重试；请先核查供应商记录。", True) from None
            with connect() as db:
                db.execute("UPDATE replica_jobs SET status='completed',phase='completed',stage='生成完成，待人工确认 Logo、材质与融合效果',output_path=?,metadata=?,uncertain=0,retryable=0,updated_at=? WHERE id=?", (str(output), json.dumps(metadata), utc_now(), job_id))
    except asyncio.CancelledError:
        row = row_for(job_id)
        with connect() as db:
            if row.get("phase") in {"queued", "connecting"}:
                db.execute("UPDATE replica_jobs SET status='queued',phase='queued',stage='服务停止，任务将在下次启动时恢复',claimed_at=NULL,updated_at=? WHERE id=?", (utc_now(), job_id))
            else:
                db.execute("UPDATE replica_jobs SET status='interrupted',phase='interrupted',stage='任务中断，未自动重新提交',error_code='interrupted',error='结果可能不确定，重试前请核查供应商记录。',uncertain=1,retryable=0,updated_at=? WHERE id=?", (utc_now(), job_id))
        raise
    except Exception as error:
        # Never expose provider bodies, URLs, prompts, credentials or raw exceptions.
        safe = error if isinstance(error, ReplicaProviderError) else ReplicaProviderError("internal", "任务处理异常，未自动重新提交；请检查本地服务。", True)
        with connect() as db:
            db.execute("UPDATE replica_jobs SET status='failed',phase=?,stage='生成失败',error_code=?,error=?,uncertain=?,retryable=?,attempt_count=MAX(attempt_count,?),updated_at=? WHERE id=?", (safe.phase, safe.code, str(safe), int(safe.uncertain), int(safe.retryable), safe.attempts, utc_now(), job_id))
    finally:
        tasks.pop(job_id, None)


def schedule(job_id: str) -> None:
    if job_id in tasks and not tasks[job_id].done():
        return
    tasks[job_id] = asyncio.create_task(process(job_id))


def identity(value: str) -> tuple[str, str]:
    try:
        key = str(UUID(value))
    except (ValueError, AttributeError):
        raise HTTPException(422, "缺少有效的请求标识") from None
    return key, "rep_" + UUID(key).hex


def normalize_image(content: bytes) -> tuple[bytes, int, int]:
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"} or getattr(image, "n_frames", 1) != 1:
                raise ValueError("仅支持单帧 JPG、PNG、WEBP 图片。")
            validate_size(*image.size)
            normalized = ImageOps.exif_transpose(image)
            normalized.load()
            normalized = normalized.convert("RGBA" if "A" in normalized.getbands() or "transparency" in image.info else "RGB")
            buffer = io.BytesIO()
            normalized.save(buffer, "PNG")
            if buffer.tell() > MAX_BYTES:
                raise ValueError("图片无损归一化后超过 20MB，请选择较小的素材。")
            return buffer.getvalue(), normalized.width, normalized.height
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("图片已损坏或无法安全读取，请重新选择。") from None


async def read_upload(upload: UploadFile) -> tuple[bytes, int, int]:
    if upload.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(415, "仅支持 JPG、PNG、WEBP 图片")
    content = await upload.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "单张图片不能超过 20MB")
    try:
        return await asyncio.to_thread(normalize_image, content)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


class PrepareBody(BaseModel):
    reference_width: int = Field(ge=64, le=16384)
    reference_height: int = Field(ge=64, le=16384)
    custom_notes: str = Field(default="", max_length=800)


@router.get("/capabilities")
def capabilities():
    try:
        _, _, model = current_configuration()
        state = connectivity.snapshot()
        return {"configured": True, "ready": bool(state["connected"] and not state["circuit_open"]), "model": model, "max_references": 1, "key_verified": False, "connectivity": state, "message": "本机配置已读取；生成前会执行不计费的联网检查。"}
    except ReplicaProviderError as error:
        return {"configured": False, "max_references": 1, "key_verified": False, "message": str(error)}


@router.get("/connectivity")
async def connectivity_status(refresh: bool = False):
    if not refresh:
        return connectivity.snapshot()
    try:
        return await check_connectivity(get_provider_client())
    except ReplicaProviderError as error:
        return {**connectivity.snapshot(), "connected": False, "phase": error.phase, "error_code": error.code, "message": str(error)}


@router.post("/prepare")
def prepare(body: PrepareBody):
    try:
        width, height, override = target_size(body.reference_width, body.reference_height, body.custom_notes)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return {"target_width": width, "target_height": height, "overridden": override}


@router.post("/jobs", status_code=202)
async def create_job(request: Request):
    require_provider()
    request_key, job_id = identity(request.headers.get("Idempotency-Key", ""))
    async with request.form(max_files=4, max_fields=5, max_part_size=MAX_BYTES) as form:
        allowed = {"main_image", "reference_image", "extra_images", "remove_text", "custom_notes", "confirmed_width", "confirmed_height"}
        if set(form.keys()) - allowed:
            raise HTTPException(422, "请求包含不支持的字段")
        main, reference, extras = form.getlist("main_image"), form.getlist("reference_image"), form.getlist("extra_images")
        if len(main) != 1 or len(reference) != 1 or len(extras) > 2 or any(not isinstance(item, UploadFile) for item in [*main, *reference, *extras]):
            raise HTTPException(422, "必须选择一张主产品图、一张参考图，最多两张补充视角。")
        for name in ("remove_text", "custom_notes", "confirmed_width", "confirmed_height"):
            if len(form.getlist(name)) > 1:
                raise HTTPException(422, "设置字段不能重复")
        if form.get("remove_text", "true") not in ("true", "false"):
            raise HTTPException(422, "remove_text 必须为 true 或 false")
        remove_text = form.get("remove_text", "true") == "true"
        notes = form.get("custom_notes", "")
        if not isinstance(notes, str) or len(notes) > 800:
            raise HTTPException(422, "补充说明不能超过 800 字")
        normalized = [await read_upload(item) for item in [*main, *extras, *reference]]
        ref_width, ref_height = normalized[-1][1:]
        try:
            width, height, _ = target_size(ref_width, ref_height, notes)
            if (int(str(form.get("confirmed_width"))), int(str(form.get("confirmed_height")))) != (width, height):
                raise ValueError("确认的尺寸与后端读取的图片尺寸不同，请重新检查并确认。")
        except (ValueError, TypeError) as error:
            raise HTTPException(422, str(error)) from None
    digest = hashlib.sha256(json.dumps([notes, remove_text, width, height], ensure_ascii=False).encode())
    for content, _, _ in normalized:
        digest.update(hashlib.sha256(content).digest())
    personal_key = current_user_key.get()
    if personal_key:
        digest.update(hashlib.sha256(personal_key.encode()).digest())
    fingerprint = digest.hexdigest()
    # Idempotent replays must remain readable while the provider is offline. This
    # check happens before connectivity preflight; the transaction below repeats
    # it to close the race with another request using the same key.
    with connect() as db:
        existing = db.execute("SELECT * FROM replica_jobs WHERE request_key=?", (request_key,)).fetchone()
    if existing:
        if existing["fingerprint"] != fingerprint:
            raise HTTPException(409, "同一请求标识不能用于不同素材或设置")
        return public_job(dict(existing))
    try:
        await check_connectivity(get_provider_client())
    except ReplicaProviderError as error:
        raise HTTPException(503, {"message": str(error), "error_code": error.code, "retryable": error.retryable}) from None
    upload_root = UPLOAD_DIR / "replicate"
    upload_root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="source-", dir=upload_root))
    keep = False
    try:
        paths = []
        for index, (content, _, _) in enumerate(normalized):
            path = folder / f"input-{index}.png"
            path.write_bytes(content)
            paths.append(str(path))
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM replica_jobs WHERE request_key=?", (request_key,)).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise HTTPException(409, "同一请求标识不能用于不同素材或设置")
                return public_job(dict(existing))
            active = db.execute("SELECT id FROM replica_jobs WHERE fingerprint=? AND status IN ('queued','connecting','submitting','receiving','generating','downloading','validating')", (fingerprint,)).fetchone()
            if active:
                raise HTTPException(409, {"message": "同样的素材已有进行中的任务", "job_id": active["id"]})
            now = utc_now()
            db.execute("INSERT INTO replica_jobs(id,request_key,fingerprint,main_path,reference_path,extra_paths,reference_width,reference_height,target_width,target_height,remove_text,custom_notes,status,phase,stage,created_at,updated_at,expires_at,uses_personal_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, request_key, fingerprint, paths[0], paths[-1], json.dumps(paths[1:-1]), ref_width, ref_height, width, height, int(remove_text), notes, "queued", "queued", "等待生成队列", now, now, expires_at(), int(bool(personal_key))))
        keep = True
        schedule(job_id)
        return public_job(row_for(job_id))
    finally:
        if not keep:
            # Only this request's server-created temporary folder, never a client path.
            shutil.rmtree(folder)


@router.get("/jobs/{job_id}")
def job_detail(job_id: str):
    return public_job(row_for(job_id))


@router.get("/jobs/{job_id}/sources/{kind}")
def source_file(job_id: str, kind: str):
    if kind not in {"main", "reference"}:
        raise HTTPException(404, "素材不存在")
    row = row_for(job_id)
    path = Path(row[f"{kind}_path"])
    if row["expires_at"] < utc_now() or not path.is_file():
        raise HTTPException(410, "素材已过期或缺失")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/jobs/{job_id}/result")
def result_file(job_id: str, download: bool = False):
    row = row_for(job_id)
    if row["status"] != "completed" or not row["output_path"]:
        raise HTTPException(409, "任务尚无可下载结果")
    if row["expires_at"] < utc_now() or not Path(row["output_path"]).is_file():
        raise HTTPException(410, "结果已过期或缺失")
    return FileResponse(row["output_path"], media_type="image/png", filename=f"{job_id}.png" if download else None, headers={"Cache-Control": "no-store"})


class RetryBody(BaseModel):
    confirm_possible_charge: bool = False


@router.post("/jobs/{job_id}/retry", status_code=202)
async def retry_job(job_id: str, body: RetryBody, request: Request):
    require_provider()
    key, next_id = identity(request.headers.get("Idempotency-Key", ""))
    # A repeated retry request returns the already-created child even when Ark is
    # currently unreachable, so browser refreshes cannot create duplicate charges.
    with connect() as db:
        existing = db.execute("SELECT * FROM replica_jobs WHERE request_key=?", (key,)).fetchone()
        old = db.execute("SELECT * FROM replica_jobs WHERE id=?", (job_id,)).fetchone()
    if existing:
        if existing["parent_id"] != job_id:
            raise HTTPException(409, "该请求标识已被其他任务使用")
        return public_job(dict(existing))
    if not old:
        raise HTTPException(404, "任务不存在")
    try:
        await check_connectivity(get_provider_client())
    except ReplicaProviderError as error:
        raise HTTPException(503, {"message": str(error), "error_code": error.code, "retryable": error.retryable}) from None
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT * FROM replica_jobs WHERE id=?", (job_id,)).fetchone()
        if not old:
            raise HTTPException(404, "任务不存在")
        existing = db.execute("SELECT * FROM replica_jobs WHERE request_key=?", (key,)).fetchone()
        if existing:
            if existing["parent_id"] != job_id:
                raise HTTPException(409, "该请求标识已被其他任务使用")
            return public_job(dict(existing))
        if old["status"] not in ("failed", "interrupted"):
            raise HTTPException(409, "只有失败或中断任务可以重试")
        if bool(old["uncertain"]) and not body.confirm_possible_charge:
            raise HTTPException(422, "请先确认重试可能产生新的供应商费用")
        paths = [old["main_path"], old["reference_path"], *json.loads(old["extra_paths"])]
        if old["expires_at"] < utc_now() or any(not Path(p).is_file() for p in paths):
            raise HTTPException(410, "素材已过期或缺失，请重新上传")
        if bool(old["uses_personal_key"]) != bool(current_user_key.get()):
            raise HTTPException(403, "请使用原来的密钥模式重试此任务")
        if db.execute("SELECT 1 FROM replica_jobs WHERE fingerprint=? AND status IN ('queued','connecting','submitting','receiving','generating','downloading','validating')", (old["fingerprint"],)).fetchone():
            raise HTTPException(409, "同一组素材已有进行中的任务")
        now = utc_now()
        db.execute("INSERT INTO replica_jobs(id,request_key,parent_id,fingerprint,main_path,reference_path,extra_paths,reference_width,reference_height,target_width,target_height,remove_text,custom_notes,status,phase,stage,created_at,updated_at,expires_at,uses_personal_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (next_id, key, job_id, old["fingerprint"], *[old[k] for k in ("main_path", "reference_path", "extra_paths", "reference_width", "reference_height", "target_width", "target_height", "remove_text", "custom_notes")], "queued", "queued", "等待重试队列", now, now, old["expires_at"], old["uses_personal_key"]))
    schedule(next_id)
    return public_job(row_for(next_id))
