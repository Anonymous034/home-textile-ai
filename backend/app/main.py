from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import shutil
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from PIL import Image, ImageFilter, UnidentifiedImageError
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from .database import RESULT_DIR, UPLOAD_DIR, connect, expires_at, initialize, row_to_dict, utc_now
from .providers import MockProvider
from .providers.ark import AgentPlanSeedreamSkillProvider
from .providers.plan_connection import probe as probe_plan_connection, snapshot as plan_connection_snapshot
from .providers.replicate import connectivity as replica_connectivity, current_configuration as replica_configuration
from .user_key import UserKeyScope, current_user_key, valid_user_key
from .key_health import KeyHealthError, inspect_key
from .providers.base import ProviderRequest
from .quality import inspect_mock_output
from .replicate import router as replicate_router, initialize_replica, start_replica_connectivity, shutdown_replica
from .replicate_guard import ReplicaGuard
from .detail import router as detail_router, initialize_detail, shutdown_detail
from .buyer_show import router as buyer_show_router, initialize_buyer_show, shutdown_buyer_show
from .local_edit import router as local_edit_router
from .upscale import router as upscale_router
from .template_compose import router as template_compose_router
from .pattern import router as pattern_router, shutdown_pattern
from .sketch import router as sketch_router
from .account import router as account_router, initialize_account, record_work

ASPECTS = {"1:1": (1, 1), "3:4": (3, 4), "4:3": (4, 3), "9:16": (9, 16), "16:9": (16, 9)}
LONG_EDGES = {"1K": 1024, "2K": 2048, "4K": 4096}
STAGES = [
    (8, "校验三张必传素材"),
    (18, "提取模特身份、体型与服装条件"),
    (31, "提取家具结构、材质与保护区域"),
    (43, "分析场景透视、深度与光照"),
    (55, "绑定姿态、深度和区域蒙版"),
    (72, "提交第三方生成任务"),
    (86, "检查接触、遮挡和家具保真"),
    (96, "整理候选结果"),
]

BACKEND_DIR = Path(__file__).resolve().parents[1]
PRESET_HD_DIR = BACKEND_DIR / "data" / "preset-hd"
PRESET_THUMB_DIR = BACKEND_DIR / "data" / "preset-thumbs"
TEMPLATE_THUMB_DIR = BACKEND_DIR / "data" / "template-thumbs"
# 本地安全配置窗口写入此文件；开发环境中它应覆盖可能残留的旧用户环境变量。
# 托管环境没有这个文件，仍会正常使用平台注入的环境变量。
load_dotenv(BACKEND_DIR / ".env", override=True)


def allowed_frontend_origins() -> set[str]:
    """Return the configured browser origins plus the local development origins."""
    configured = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000").strip().rstrip("/")
    return {
        origin
        for origin in {
            configured,
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        }
        if origin
    }


def valid_ark_key(value: str) -> bool:
    """方舟推理 Key 可能是 UUID 或其他控制台签发格式，不强制添加前缀。"""
    return len(value) >= 20 and not any(character.isspace() for character in value) and "replace_with" not in value


def local_ark_key() -> str:
    """读取环境变量，或读取不会提交到 Git 的本机密钥文本。"""
    key = os.getenv("ARK_API_KEY", "").strip()
    if valid_ark_key(key):
        return key
    local_key_file = BACKEND_DIR / "本机API密钥.txt"
    if local_key_file.is_file():
        for line in local_key_file.read_text(encoding="utf-8-sig").splitlines():
            candidate = line.strip()
            if valid_ark_key(candidate):
                os.environ["ARK_API_KEY"] = candidate
                return candidate
    return ""


ark_api_key = local_ark_key()
provider = AgentPlanSeedreamSkillProvider() if valid_ark_key(ark_api_key) else MockProvider()


def active_provider():
    return AgentPlanSeedreamSkillProvider() if current_user_key.get() else provider
subscribers: dict[str, set[WebSocket]] = {}
running_tasks: dict[str, asyncio.Task[None]] = {}
studio_connectivity_monitor: asyncio.Task[None] | None = None
plan_connectivity_monitor: asyncio.Task[None] | None = None
logger = logging.getLogger(__name__)


async def probe_studio_connection() -> dict[str, object]:
    if not isinstance(provider, AgentPlanSeedreamSkillProvider):
        return {"connected": False, "error_code": "not_configured", "message": "尚未配置 Agent Plan 图片密钥。"}
    return await provider.probe_connection()


async def monitor_studio_connection() -> None:
    while True:
        await asyncio.sleep(5)
        try:
            state = await probe_studio_connection()
            if not state["connected"]:
                logger.warning("Studio AI connectivity: %s", state["error_code"])
        except Exception:
            logger.exception("Studio AI connectivity monitor failed")


async def monitor_plan_connection() -> None:
    while True:
        await asyncio.sleep(5)
        try:
            state = await probe_plan_connection()
            if not state["connected"]:
                logger.warning("Visual planner connectivity: %s", state["error_code"])
        except Exception:
            logger.exception("Visual planner connectivity monitor failed")


def ai_connection_snapshot() -> dict[str, object]:
    return {
        "studio_image": provider.connection_status() if isinstance(provider, AgentPlanSeedreamSkillProvider) else {"connected": False, "error_code": "not_configured", "message": "尚未配置 Agent Plan 图片密钥。"},
        "replicate_image": replica_connectivity.snapshot(),
        "template_plan": plan_connection_snapshot(),
    }


class JobCreate(BaseModel):
    model_asset_id: str
    furniture_asset_id: str
    scene_asset_id: str
    composition_id: str
    aspect_ratio: Literal["1:1", "3:4", "4:3", "9:16", "16:9"]
    resolution: Literal["1K", "2K", "4K"]
    output_count: int = Field(default=4, ge=1, le=4)
    guidance: str | None = Field(default=None, max_length=800)


class EvaluationCreate(BaseModel):
    scores: dict[str, float] = Field(default_factory=dict)
    notes: str | None = None


class LocalArkKeyCreate(BaseModel):
    api_key: str = Field(min_length=20, max_length=300)


def output_size(aspect: str, resolution: str) -> tuple[int, int]:
    a, b = ASPECTS[aspect]
    edge = LONG_EDGES[resolution]
    if a >= b:
        width, height = edge, round(edge * b / a)
    else:
        width, height = round(edge * a / b), edge
    return max(64, width // 64 * 64), max(64, height // 64 * 64)


async def broadcast(job_id: str, payload: dict[str, object]) -> None:
    stale: list[WebSocket] = []
    for socket in subscribers.get(job_id, set()):
        try:
            await socket.send_json(payload)
        except Exception:
            stale.append(socket)
    for socket in stale:
        subscribers.get(job_id, set()).discard(socket)


def get_job(job_id: str) -> dict[str, object]:
    with connect() as db:
        job = row_to_dict(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())
        if not job:
            raise HTTPException(404, "任务不存在")
        outputs = [row_to_dict(row) for row in db.execute("SELECT * FROM outputs WHERE job_id = ? ORDER BY created_at", (job_id,))]
        for output in outputs:
            output["preview_url"] = f"/api/files/{output['id']}"
        job["outputs"] = outputs
        return job


def update_job(job_id: str, status: str, progress: int, stage: str, error: str | None = None) -> None:
    now = utc_now()
    with connect() as db:
        db.execute(
            "UPDATE jobs SET status=?, progress=?, stage=?, error=?, updated_at=? WHERE id=?",
            (status, progress, stage, error, now, job_id),
        )
        db.execute(
            "INSERT INTO job_events(job_id,status,progress,stage,created_at) VALUES(?,?,?,?,?)",
            (job_id, status, progress, stage, now),
        )


async def process_job(job_id: str) -> None:
    job_provider = active_provider()
    try:
        job = get_job(job_id)
        with connect() as db:
            assets = {
                kind: row_to_dict(db.execute("SELECT * FROM assets WHERE id = ?", (job[f"{kind}_asset_id"],)).fetchone())
                for kind in ("model", "furniture", "scene")
            }
            composition = row_to_dict(
                db.execute(
                    "SELECT preview_path FROM composition_presets WHERE id=? AND enabled=1",
                    (job["composition_id"],),
                ).fetchone()
            )
            if not composition:
                composition = row_to_dict(
                    db.execute(
                        "SELECT path AS preview_path FROM composition_uploads WHERE id=?",
                        (job["composition_id"],),
                    ).fetchone()
                )
        for progress, stage in STAGES:
            await asyncio.sleep(0.45)
            update_job(job_id, "rendering", progress, stage)
            await broadcast(job_id, get_job(job_id))
        request = ProviderRequest(
            job_id=job_id,
            model_path=Path(assets["model"]["path"]),
            furniture_path=Path(assets["furniture"]["path"]),
            scene_path=Path(assets["scene"]["path"]),
            composition_id=str(job["composition_id"]),
            composition_path=Path(composition["preview_path"]) if composition and composition.get("preview_path") else None,
            width=int(job["output_width"]),
            height=int(job["output_height"]),
            output_count=int(job["output_count"]),
            extra_paths=tuple(sorted(Path(assets["furniture"]["path"]).parent.glob("extra-*"))),
            guidance=str(job["guidance"]) if job.get("guidance") else None,
        )
        provider_job_id = await job_provider.submit_job(request)
        with connect() as db:
            db.execute("UPDATE jobs SET provider_job_id=?, attempts=attempts+1 WHERE id=?", (provider_job_id, job_id))
        outputs = await job_provider.get_outputs(request)
        for output in outputs:
            if not isinstance(job_provider, MockProvider):
                record_work(output.path)
        with connect() as db:
            db.execute("DELETE FROM outputs WHERE job_id=?", (job_id,))
            for item in outputs:
                if isinstance(job_provider, MockProvider):
                    quality_status, scores = inspect_mock_output(item.path)
                else:
                    quality_status, scores = "pending_review", {"provider_returned": 1.0}
                db.execute(
                    "INSERT INTO outputs(id,job_id,path,quality_status,quality_scores,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                    (f"out_{uuid4().hex}", job_id, str(item.path), quality_status, json.dumps(scores), utc_now(), expires_at()),
                )
        final_status = "completed_mock" if isinstance(job_provider, MockProvider) else "completed"
        final_stage = "模拟流程完成：结果不可用于商拍质量验收" if isinstance(job_provider, MockProvider) else "生成完成，等待人工质量确认"
        update_job(job_id, final_status, 100, final_stage)
        await broadcast(job_id, get_job(job_id))
    except asyncio.CancelledError:
        update_job(job_id, "cancelled", 0, "任务已取消")
    except Exception as error:
        update_job(job_id, "failed", 0, "任务失败", str(error))
        await broadcast(job_id, get_job(job_id))
    finally:
        running_tasks.pop(job_id, None)


def cleanup_expired() -> None:
    now = datetime.now(UTC).isoformat()
    with connect() as db:
        output_rows = db.execute("SELECT id,path FROM outputs WHERE expires_at < ?", (now,)).fetchall()
        asset_rows = db.execute("SELECT id,path FROM assets WHERE expires_at < ?", (now,)).fetchall()
        composition_rows = db.execute("SELECT id,path FROM composition_uploads WHERE expires_at < ?", (now,)).fetchall()
        for row in output_rows:
            Path(row["path"]).unlink(missing_ok=True)
        for row in asset_rows:
            Path(row["path"]).unlink(missing_ok=True)
        for row in composition_rows:
            Path(row["path"]).unlink(missing_ok=True)
        db.execute("DELETE FROM outputs WHERE expires_at < ?", (now,))
        db.execute("DELETE FROM assets WHERE expires_at < ? AND id NOT IN (SELECT model_asset_id FROM jobs UNION SELECT furniture_asset_id FROM jobs UNION SELECT scene_asset_id FROM jobs)", (now,))
        db.execute("DELETE FROM composition_uploads WHERE expires_at < ?", (now,))


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    initialize_account()
    initialize_replica()
    await start_replica_connectivity()
    global studio_connectivity_monitor, plan_connectivity_monitor
    await probe_studio_connection()
    await probe_plan_connection()
    studio_connectivity_monitor = asyncio.create_task(monitor_studio_connection())
    plan_connectivity_monitor = asyncio.create_task(monitor_plan_connection())
    initialize_detail()
    initialize_buyer_show()
    cleanup_expired()
    yield
    if studio_connectivity_monitor is not None:
        studio_connectivity_monitor.cancel()
        await asyncio.gather(studio_connectivity_monitor, return_exceptions=True)
        studio_connectivity_monitor = None
    if plan_connectivity_monitor is not None:
        plan_connectivity_monitor.cancel()
        await asyncio.gather(plan_connectivity_monitor, return_exceptions=True)
        plan_connectivity_monitor = None
    await shutdown_replica()
    await shutdown_detail()
    await shutdown_buyer_show()
    await shutdown_pattern()
    for task in list(running_tasks.values()):
        task.cancel()


app = FastAPI(title="家具 AI 商拍后端", version="0.1.0", lifespan=lifespan)
app.include_router(replicate_router)
app.include_router(detail_router)
app.include_router(buyer_show_router)
app.include_router(local_edit_router)
app.include_router(upscale_router)
app.include_router(template_compose_router)
app.include_router(pattern_router)
app.include_router(sketch_router)
app.include_router(account_router)
app.add_middleware(ReplicaGuard)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(allowed_frontend_origins()),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(UserKeyScope)


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"ok": True, "provider": provider.get_capabilities()["provider"]}


@app.get("/api/health/live")
def health_live() -> dict[str, object]:
    return {"ok": True, "service": "furniture-ai-backend"}


@app.get("/api/health/ready")
def health_ready() -> JSONResponse:
    database_ok = False
    configured = False
    try:
        with connect() as db:
            database_ok = db.execute("SELECT 1").fetchone()[0] == 1
        replica_configuration()
        configured = True
    except Exception:
        pass
    state = replica_connectivity.snapshot()
    studio_state = provider.connection_status() if isinstance(provider, AgentPlanSeedreamSkillProvider) else {"connected": False, "error_code": "not_configured"}
    ready = bool(database_ok and configured and state["connected"] and not state["circuit_open"] and studio_state["connected"])
    return JSONResponse({"ready": ready, "database": database_ok, "configured": configured, "connectivity": state, "studio_image": studio_state, "template_plan": plan_connection_snapshot()}, status_code=200 if ready else 503)


@app.get("/api/ai/connections")
async def ai_connections(refresh: bool = False) -> dict[str, object]:
    if refresh:
        await asyncio.gather(probe_studio_connection(), probe_plan_connection())
    return ai_connection_snapshot()


@app.get("/api/ai/connections/stream")
async def ai_connection_stream() -> StreamingResponse:
    async def events():
        previous = ""
        elapsed = 0
        yield "retry: 3000\n\n"
        while True:
            current = json.dumps(ai_connection_snapshot(), ensure_ascii=False, sort_keys=True)
            if current != previous:
                yield f"data: {current}\n\n"
                previous = current
                elapsed = 0
            elif elapsed >= 15:
                yield ": keepalive\n\n"
                elapsed = 0
            await asyncio.sleep(1)
            elapsed += 1
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/local-config/ark-key")
def configure_local_ark_key(body: LocalArkKeyCreate, request: Request) -> dict[str, object]:
    """仅供本机开发使用；密钥不会返回给网页，也不会写入数据库。"""
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(403, "这个配置入口只能在本机使用")
    api_key = body.api_key.strip()
    if not valid_ark_key(api_key):
        raise HTTPException(400, "密钥格式不正确，请粘贴方舟 API Key 管理页面复制的完整原始值")
    env_path = BACKEND_DIR / ".env"
    env_path.write_text(
        "\n".join(
            [
                f"ARK_API_KEY={api_key}",
                "ARK_IMAGE_MODEL=doubao-seedream-5.0-lite",
                "ARK_IMAGE_ENDPOINT=https://ark.cn-beijing.volces.com/api/plan/v3/images/generations",
                "FRONTEND_ORIGIN=http://localhost:3000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    os.environ["ARK_API_KEY"] = api_key
    global provider
    provider = AgentPlanSeedreamSkillProvider()
    return {"ok": True, "provider": provider.get_capabilities()["provider"]}


class PersonalKeyCheck(BaseModel):
    api_key: str = Field(min_length=20, max_length=300)


@app.post("/api/access/verify-user-key")
async def verify_user_key(body: PersonalKeyCheck, request: Request) -> dict[str, bool]:
    """Check this visitor's key without creating an image or saving the key."""
    if request.client is None or request.client.host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(403, "个人密钥验证仅在本机开放")
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in allowed_frontend_origins():
        raise HTTPException(403, "不允许此来源验证密钥")
    key = body.api_key.strip()
    if not valid_user_key(key):
        raise HTTPException(400, "请填写完整的火山方舟 Agent Plan API Key")
    try:
        await inspect_key(key)
    except KeyHealthError as error:
        raise HTTPException(error.status_code, str(error)) from None
    return {"ok": True}


@app.get("/api/access/key-status")
async def personal_key_status(request: Request) -> dict[str, object]:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(403, "个人密钥状态仅在本机开放")
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in allowed_frontend_origins():
        raise HTTPException(403, "不允许此来源查询密钥状态")
    key = current_user_key.get()
    if not key:
        raise HTTPException(400, "当前请求没有个人 API Key")
    try:
        return await inspect_key(key)
    except KeyHealthError as error:
        raise HTTPException(error.status_code, {"code": error.code, "message": str(error)}) from None


@app.get("/api/provider-capabilities")
def capabilities() -> dict[str, object]:
    return active_provider().get_capabilities()


def preset_items(table: str) -> list[dict[str, object]]:
    """只返回启用的预设；网页永远不会直接访问 SQLite 文件。"""
    allowed = {"model_presets", "scene_presets", "composition_presets"}
    if table not in allowed:
        raise HTTPException(400, "未知的预设库")
    with connect() as db:
        rows = db.execute(
            f"SELECT * FROM {table} WHERE enabled = 1 ORDER BY sort_order, created_at DESC"
        ).fetchall()
    items = [dict(row) for row in rows]
    preset_type = {
        "model_presets": "models",
        "scene_presets": "scenes",
        "composition_presets": "compositions",
    }[table]
    for item in items:
        item["enabled"] = bool(item.get("enabled"))
        preview_path = item.get("avatar_path") or item.get("preview_path")
        item["preview_url"] = f"/api/preset-files/{preset_type}/{item['id']}" if preview_path else None
        if item.get("masks_json"):
            item["masks"] = json.loads(str(item.pop("masks_json")))
    return items


def hd_preset_preview(source: Path, preset_type: str, preset_id: str) -> Path:
    """为确认窗口生成高清预览缓存，不覆盖数据库中的原始预设图片。"""
    target_dir = PRESET_HD_DIR / preset_type
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{preset_id}.png"
    if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
        return target
    with Image.open(source) as image:
        image = image.convert("RGB")
        if max(image.size) < 1024:
            scale = 1024 / max(image.size)
            size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
            image = image.resize(size, Image.Resampling.LANCZOS)
            image = image.filter(ImageFilter.UnsharpMask(radius=1.25, percent=135, threshold=3))
        image.save(target, "PNG", optimize=True)
    return target


def thumbnail_preset_preview(source: Path, preset_type: str, preset_id: str) -> Path:
    """为资料库网格生成轻量缩略图，避免一次下载所有高清原图。"""
    target_dir = PRESET_THUMB_DIR / preset_type
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{preset_id}.png"
    if target.is_file() and target.stat().st_mtime >= source.stat().st_mtime:
        return target
    with Image.open(source) as image:
        image = image.convert("RGB")
        image.thumbnail((256, 256), Image.Resampling.LANCZOS)
        image.save(target, "PNG", optimize=True)
    return target


@app.get("/api/preset-files/{preset_type}/{preset_id}")
def preset_file(
    preset_type: Literal["models", "scenes", "compositions"],
    preset_id: str,
    quality: Literal["original", "thumb", "hd"] = "original",
) -> FileResponse:
    config = {
        "models": ("model_presets", "avatar_path"),
        "scenes": ("scene_presets", "preview_path"),
        "compositions": ("composition_presets", "preview_path"),
    }
    table, column = config[preset_type]
    with connect() as db:
        row = db.execute(f"SELECT {column} AS path FROM {table} WHERE id=? AND enabled=1", (preset_id,)).fetchone()
    if not row or not row["path"] or not Path(row["path"]).is_file():
        raise HTTPException(404, "预设图片不存在")
    source = Path(row["path"])
    if quality == "thumb":
        source = thumbnail_preset_preview(source, preset_type, preset_id)
    elif quality == "hd":
        source = hd_preset_preview(source, preset_type, preset_id)
    return FileResponse(source, headers={"Cache-Control": "no-store"})


@app.get("/api/presets/models")
def model_presets() -> dict[str, object]:
    items = preset_items("model_presets")
    return {"type": "model", "items": items, "empty": not items}


@app.get("/api/presets/scenes")
def scene_presets() -> dict[str, object]:
    items = preset_items("scene_presets")
    return {"type": "scene", "items": items, "empty": not items}


@app.get("/api/presets/compositions")
def composition_presets() -> dict[str, object]:
    items = preset_items("composition_presets")
    return {"type": "composition", "items": items, "empty": not items}


@app.get("/api/compositions")
def compositions() -> dict[str, object]:
    items = preset_items("composition_presets")
    return {"items": items, "ready": bool(items), "message": "构图库暂无内容" if not items else ""}


@app.get("/api/template-library/categories")
def template_library_categories() -> dict[str, object]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT c.id,c.name,c.sort_order,COUNT(p.id) AS template_count
            FROM template_categories c
            LEFT JOIN template_presets p ON p.category_id=c.id
            GROUP BY c.id,c.name,c.sort_order
            ORDER BY c.sort_order,c.name
            """
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/template-library/templates")
def template_library_templates(category: str) -> dict[str, object]:
    with connect() as db:
        templates = db.execute(
            """
            SELECT p.id,p.name,p.image_count,c.id AS category_id,c.name AS category_name
            FROM template_presets p
            JOIN template_categories c ON c.id=p.category_id
            WHERE c.id=?
            ORDER BY p.sort_order,p.name
            """,
            (category,),
        ).fetchall()
        items: list[dict[str, object]] = []
        for template in templates:
            value = dict(template)
            images = db.execute(
                "SELECT id,slot_index FROM template_images WHERE template_id=? ORDER BY slot_index LIMIT 4",
                (template["id"],),
            ).fetchall()
            value["previews"] = [
                {"id": row["id"], "url": f"/api/template-library/images/{row['id']}?quality=thumb"}
                for row in images
            ]
            items.append(value)
    return {"items": items}


@app.get("/api/template-library/templates/{template_id}")
def template_library_template(template_id: str) -> dict[str, object]:
    with connect() as db:
        template = db.execute(
            """
            SELECT p.id,p.name,p.image_count,c.id AS category_id,c.name AS category_name
            FROM template_presets p
            JOIN template_categories c ON c.id=p.category_id
            WHERE p.id=?
            """,
            (template_id,),
        ).fetchone()
        if not template:
            raise HTTPException(404, "模板不存在")
        images = db.execute(
            "SELECT id,slot_index FROM template_images WHERE template_id=? ORDER BY slot_index",
            (template_id,),
        ).fetchall()
    value = dict(template)
    value["images"] = [
        {
            "id": row["id"],
            "slot": row["slot_index"],
            "thumbnail_url": f"/api/template-library/images/{row['id']}?quality=thumb",
            "image_url": f"/api/template-library/images/{row['id']}?quality=original",
        }
        for row in images
    ]
    return value


@app.get("/api/template-library/images/{image_id}")
def template_library_image(image_id: str, quality: Literal["thumb", "original"] = "original") -> FileResponse:
    with connect() as db:
        row = db.execute("SELECT local_path FROM template_images WHERE id=?", (image_id,)).fetchone()
    if not row or not Path(row["local_path"]).is_file():
        raise HTTPException(404, "模板图片不存在")
    source = Path(row["local_path"])
    if quality == "thumb":
        TEMPLATE_THUMB_DIR.mkdir(parents=True, exist_ok=True)
        target = TEMPLATE_THUMB_DIR / f"{image_id}.jpg"
        if not target.is_file() or target.stat().st_mtime < source.stat().st_mtime:
            with Image.open(source) as image:
                image = image.convert("RGB")
                image.thumbnail((420, 420), Image.Resampling.LANCZOS)
                image.save(target, "JPEG", quality=82, optimize=True)
        source = target
    return FileResponse(source, headers={"Cache-Control": "public, max-age=86400"})


async def save_upload(kind: Literal["model", "furniture", "scene"], file: UploadFile) -> dict[str, object]:
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(415, "仅支持 JPG、PNG、WebP 图片")
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "单张图片不能超过20MB")
    asset_id = f"asset_{uuid4().hex}"
    suffix = mimetypes.guess_extension(file.content_type) or ".img"
    folder = UPLOAD_DIR / asset_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"source{suffix}"
    path.write_bytes(content)
    try:
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
    except (UnidentifiedImageError, OSError):
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(400, "图片文件已损坏或无法读取")
    if min(width, height) < 512:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(400, "图片短边至少需要512像素")
    with connect() as db:
        db.execute(
            "INSERT INTO assets(id,kind,original_name,mime_type,path,width,height,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (asset_id, kind, file.filename or "image", file.content_type, str(path), width, height, utc_now(), expires_at()),
        )
    return {"id": asset_id, "kind": kind, "width": width, "height": height, "preview_url": f"/api/files/{asset_id}"}


async def save_composition_upload(file: UploadFile) -> dict[str, object]:
    """保存用户直接上传的构图参考；它只用于动作、布局、机位和遮挡控制。"""
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(415, "构图参考仅支持 JPG、PNG、WebP 图片")
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(413, "构图参考不能超过20MB")
    composition_id = f"composition_upload_{uuid4().hex}"
    suffix = mimetypes.guess_extension(file.content_type) or ".img"
    folder = UPLOAD_DIR / composition_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"source{suffix}"
    path.write_bytes(content)
    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            source_format = image.format
            if min(width, height) < 256:
                # 构图卡片是动作/位置示意图，允许低分辨率输入并在服务端等比放大。
                # NEAREST 可保持色块、线条和区域边界，不引入照片式模糊。
                scale = 256 / min(width, height)
                width = max(256, round(width * scale))
                height = max(256, round(height * scale))
                image.resize((width, height), Image.Resampling.NEAREST).save(path, format=source_format)
    except (UnidentifiedImageError, OSError):
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(400, "构图参考已损坏或无法读取")
    with connect() as db:
        db.execute(
            "INSERT INTO composition_uploads(id,original_name,mime_type,path,width,height,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?)",
            (composition_id, file.filename or "composition", file.content_type, str(path), width, height, utc_now(), expires_at()),
        )
    return {"id": composition_id, "width": width, "height": height}


def copy_preset_asset(
    preset_id: str,
    kind: Literal["model", "scene"],
) -> dict[str, object]:
    table, column = ("model_presets", "avatar_path") if kind == "model" else ("scene_presets", "preview_path")
    with connect() as db:
        row = db.execute(
            f"SELECT name,{column} AS path FROM {table} WHERE id=? AND enabled=1",
            (preset_id,),
        ).fetchone()
    if not row or not row["path"] or not Path(row["path"]).is_file():
        raise HTTPException(400, "选择的模特或场景素材不存在")
    source = Path(row["path"])
    asset_id = f"asset_{uuid4().hex}"
    folder = UPLOAD_DIR / asset_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"source{source.suffix.lower()}"
    shutil.copy2(source, path)
    with Image.open(path) as image:
        width, height = image.size
        mime_type = Image.MIME.get(image.format or "", "image/jpeg")
    with connect() as db:
        db.execute(
            "INSERT INTO assets(id,kind,original_name,mime_type,path,width,height,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (asset_id, kind, str(row["name"]), mime_type, str(path), width, height, utc_now(), expires_at()),
        )
    return {"id": asset_id, "kind": kind, "width": width, "height": height, "preview_url": f"/api/files/{asset_id}"}


def create_job_record(
    model_asset_id: str,
    furniture_asset_id: str,
    scene_asset_id: str,
    composition_id: str,
    aspect_ratio: str,
    resolution: str,
    output_count: int,
    guidance: str | None = None,
) -> dict[str, object]:
    job_provider = active_provider()
    caps = job_provider.get_capabilities()
    if resolution not in caps["supported_resolutions"]:
        raise HTTPException(400, f"当前供应商不支持直接{resolution}生成")
    if aspect_ratio not in ASPECTS:
        raise HTTPException(400, "不支持这个图片比例")
    with connect() as db:
        valid_preset = db.execute("SELECT 1 FROM composition_presets WHERE id=? AND enabled=1", (composition_id,)).fetchone()
        valid_upload = db.execute("SELECT 1 FROM composition_uploads WHERE id=?", (composition_id,)).fetchone()
        if not valid_preset and not valid_upload:
            raise HTTPException(400, "请选择有效的构图模板")
    width, height = output_size(aspect_ratio, resolution)
    job_id = f"job_{uuid4().hex}"
    now = utc_now()
    with connect() as db:
        db.execute(
            "INSERT INTO jobs(id,model_asset_id,furniture_asset_id,scene_asset_id,composition_id,aspect_ratio,resolution,output_width,output_height,output_count,status,progress,stage,is_mock,guidance,created_at,updated_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, model_asset_id, furniture_asset_id, scene_asset_id, composition_id, aspect_ratio, resolution, width, height, output_count, "queued", 0, "任务已进入生成队列", int(isinstance(job_provider, MockProvider)), guidance, now, now, expires_at()),
        )
    running_tasks[job_id] = asyncio.create_task(process_job(job_id))
    return get_job(job_id)


@app.post("/api/assets")
async def upload_asset(
    kind: Annotated[Literal["model", "furniture", "scene"], Form()],
    file: Annotated[UploadFile, File()],
) -> dict[str, object]:
    return await save_upload(kind, file)


@app.post("/api/studio/jobs")
async def create_studio_job(
    main_image: Annotated[UploadFile, File()],
    model_preset_id: Annotated[str, Form()],
    scene_preset_id: Annotated[str, Form()],
    composition_id: Annotated[str, Form()],
    aspect_ratio: Annotated[str, Form()] = "3:4",
    resolution: Annotated[str, Form()] = "2K",
    extra_image: Annotated[UploadFile | None, File()] = None,
) -> dict[str, object]:
    furniture = await save_upload("furniture", main_image)
    if extra_image and extra_image.filename:
        if extra_image.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise HTTPException(415, "补充图仅支持 JPG、PNG、WebP")
        content = await extra_image.read()
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(413, "补充图不能超过20MB")
        with connect() as db:
            row = db.execute("SELECT path FROM assets WHERE id=?", (furniture["id"],)).fetchone()
        folder = Path(row["path"]).parent
        suffix = mimetypes.guess_extension(extra_image.content_type) or ".jpg"
        extra_path = folder / f"extra-01{suffix}"
        extra_path.write_bytes(content)
        try:
            with Image.open(extra_path) as image:
                image.verify()
        except (UnidentifiedImageError, OSError):
            extra_path.unlink(missing_ok=True)
            raise HTTPException(400, "补充图已损坏或无法读取")
    model = copy_preset_asset(model_preset_id, "model")
    scene = copy_preset_asset(scene_preset_id, "scene")
    return create_job_record(
        str(model["id"]),
        str(furniture["id"]),
        str(scene["id"]),
        composition_id,
        aspect_ratio,
        resolution,
        1,
    )


@app.post("/api/fusion/jobs")
async def create_fusion_job(
    main_view: Annotated[UploadFile, File(description="商品/家具主视角，最高优先级")],
    model_image: Annotated[UploadFile, File(description="要放入场景的模特参考")],
    scene_image: Annotated[UploadFile, File(description="最终照片的背景场景")],
    composition_image: Annotated[UploadFile, File(description="动作、位置、镜头和遮挡参考")],
    aspect_ratio: Annotated[str, Form()] = "3:4",
    resolution: Annotated[str, Form()] = "2K",
    guidance: Annotated[str | None, Form(max_length=800)] = None,
    extra_view: Annotated[UploadFile | None, File(description="同一商品的可选补充视角")] = None,
) -> dict[str, object]:
    """以主视角为最高优先级，融合模特、场景与构图参考生成照片。"""
    furniture = await save_upload("furniture", main_view)
    model = await save_upload("model", model_image)
    scene = await save_upload("scene", scene_image)
    composition = await save_composition_upload(composition_image)
    if extra_view and extra_view.filename:
        if extra_view.content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise HTTPException(415, "补充视角仅支持 JPG、PNG、WebP")
        content = await extra_view.read()
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(413, "补充视角不能超过20MB")
        with connect() as db:
            row = db.execute("SELECT path FROM assets WHERE id=?", (furniture["id"],)).fetchone()
        folder = Path(row["path"]).parent
        suffix = mimetypes.guess_extension(extra_view.content_type) or ".jpg"
        extra_path = folder / f"extra-01{suffix}"
        extra_path.write_bytes(content)
        try:
            with Image.open(extra_path) as image:
                image.verify()
        except (UnidentifiedImageError, OSError):
            extra_path.unlink(missing_ok=True)
            raise HTTPException(400, "补充视角已损坏或无法读取")
    return create_job_record(
        str(model["id"]),
        str(furniture["id"]),
        str(scene["id"]),
        str(composition["id"]),
        aspect_ratio,
        resolution,
        1,
        guidance.strip() if guidance else None,
    )


@app.get("/api/files/{item_id}")
def serve_file(item_id: str) -> FileResponse:
    with connect() as db:
        row = db.execute("SELECT path,mime_type FROM assets WHERE id=?", (item_id,)).fetchone()
        if not row:
            row = db.execute("SELECT path,NULL AS mime_type FROM outputs WHERE id=?", (item_id,)).fetchone()
    if not row or not Path(row["path"]).is_file():
        raise HTTPException(404, "文件不存在或已过期")
    return FileResponse(row["path"], media_type=row["mime_type"])


@app.post("/api/jobs")
async def create_job(body: JobCreate) -> dict[str, object]:
    with connect() as db:
        for asset_id, kind in ((body.model_asset_id, "model"), (body.furniture_asset_id, "furniture"), (body.scene_asset_id, "scene")):
            asset = db.execute("SELECT kind FROM assets WHERE id=?", (asset_id,)).fetchone()
            if not asset or asset["kind"] != kind:
                raise HTTPException(400, f"缺少有效的{kind}图片")
    return create_job_record(
        body.model_asset_id,
        body.furniture_asset_id,
        body.scene_asset_id,
        body.composition_id,
        body.aspect_ratio,
        body.resolution,
        body.output_count,
        body.guidance.strip() if body.guidance else None,
    )


@app.get("/api/jobs")
def list_jobs() -> dict[str, object]:
    with connect() as db:
        rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100").fetchall()
    return {"items": [row_to_dict(row) for row in rows]}


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict[str, object]:
    return get_job(job_id)


@app.get("/api/jobs/{job_id}/outputs")
def job_outputs(job_id: str) -> dict[str, object]:
    job = get_job(job_id)
    return {"items": job["outputs"], "is_mock": job["is_mock"]}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, object]:
    get_job(job_id)
    task = running_tasks.get(job_id)
    if task:
        task.cancel()
    update_job(job_id, "cancelled", 0, "任务已取消")
    return get_job(job_id)


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str) -> dict[str, object]:
    job = get_job(job_id)
    if job["status"] not in {"failed", "cancelled", "quality_failed", "completed_mock"}:
        raise HTTPException(409, "当前任务状态不允许重试")
    update_job(job_id, "queued", 0, "任务重新进入队列")
    running_tasks[job_id] = asyncio.create_task(process_job(job_id))
    return get_job(job_id)


@app.post("/api/outputs/{output_id}/evaluation")
def save_evaluation(output_id: str, body: EvaluationCreate) -> dict[str, object]:
    with connect() as db:
        if not db.execute("SELECT 1 FROM outputs WHERE id=?", (output_id,)).fetchone():
            raise HTTPException(404, "候选图片不存在")
        db.execute(
            "INSERT INTO evaluations(output_id,scores,notes,created_at) VALUES(?,?,?,?)",
            (output_id, json.dumps(body.scores), body.notes, utc_now()),
        )
    return {"ok": True}


@app.websocket("/ws/jobs/{job_id}")
async def job_socket(socket: WebSocket, job_id: str) -> None:
    await socket.accept()
    subscribers.setdefault(job_id, set()).add(socket)
    try:
        await socket.send_json(get_job(job_id))
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        subscribers.get(job_id, set()).discard(socket)
