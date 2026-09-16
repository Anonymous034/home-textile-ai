from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
RESULT_DIR = DATA_DIR / "results"
DB_PATH = DATA_DIR / "studio.sqlite3"


def relocate_gallery_paths(db: sqlite3.Connection) -> None:
    """Resolve portable gallery paths in a packaged database after checkout."""
    project_root = ROOT.parent.resolve()
    gallery_roots = (DATA_DIR.resolve(), (project_root / "public" / "template-library").resolve())
    fields = (
        ("composition_presets", "preview_path"),
        ("composition_presets", "pose_path"),
        ("composition_presets", "depth_path"),
        ("model_presets", "avatar_path"),
        ("scene_presets", "preview_path"),
        ("template_images", "local_path"),
    )
    for table, column in fields:
        for row in db.execute(f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL"):
            value = row[column]
            if not value or Path(value).is_file():
                continue
            candidate = (project_root / value).resolve()
            if not any(candidate.is_relative_to(root) for root in gallery_roots) or not candidate.is_file():
                continue
            db.execute(f"UPDATE {table} SET {column}=? WHERE rowid=?", (str(candidate), row["rowid"]))


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def expires_at(days: int = 7) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS assets (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL CHECK(kind IN ('model','furniture','scene')),
              original_name TEXT NOT NULL,
              mime_type TEXT NOT NULL,
              path TEXT NOT NULL,
              width INTEGER NOT NULL,
              height INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY,
              model_asset_id TEXT NOT NULL,
              furniture_asset_id TEXT NOT NULL,
              scene_asset_id TEXT NOT NULL,
              composition_id TEXT NOT NULL,
              aspect_ratio TEXT NOT NULL,
              resolution TEXT NOT NULL,
              output_width INTEGER NOT NULL,
              output_height INTEGER NOT NULL,
              output_count INTEGER NOT NULL DEFAULT 4,
              status TEXT NOT NULL,
              progress INTEGER NOT NULL DEFAULT 0,
              stage TEXT NOT NULL,
              provider_job_id TEXT,
              error TEXT,
              is_mock INTEGER NOT NULL DEFAULT 1,
              attempts INTEGER NOT NULL DEFAULT 0,
              guidance TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              FOREIGN KEY(model_asset_id) REFERENCES assets(id),
              FOREIGN KEY(furniture_asset_id) REFERENCES assets(id),
              FOREIGN KEY(scene_asset_id) REFERENCES assets(id)
            );
            CREATE TABLE IF NOT EXISTS outputs (
              id TEXT PRIMARY KEY,
              job_id TEXT NOT NULL,
              path TEXT NOT NULL,
              quality_status TEXT NOT NULL,
              quality_scores TEXT NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS job_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id TEXT NOT NULL,
              status TEXT NOT NULL,
              progress INTEGER NOT NULL,
              stage TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS evaluations (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              output_id TEXT NOT NULL,
              scores TEXT NOT NULL,
              notes TEXT,
              created_at TEXT NOT NULL,
              FOREIGN KEY(output_id) REFERENCES outputs(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS model_presets (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              avatar_path TEXT,
              gender TEXT,
              style_tag TEXT,
              prompt TEXT,
              enabled INTEGER NOT NULL DEFAULT 1,
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scene_presets (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              preview_path TEXT,
              scene_type TEXT,
              prompt TEXT,
              enabled INTEGER NOT NULL DEFAULT 1,
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS composition_presets (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              preview_path TEXT,
              description TEXT,
              pose_path TEXT,
              depth_path TEXT,
              masks_json TEXT,
              enabled INTEGER NOT NULL DEFAULT 1,
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS composition_uploads (
              id TEXT PRIMARY KEY,
              original_name TEXT NOT NULL,
              mime_type TEXT NOT NULL,
              path TEXT NOT NULL,
              width INTEGER NOT NULL,
              height INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS template_categories (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL UNIQUE,
              sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS template_presets (
              id TEXT PRIMARY KEY,
              source_id TEXT NOT NULL,
              category_id TEXT NOT NULL,
              name TEXT NOT NULL,
              sort_order INTEGER NOT NULL DEFAULT 0,
              image_count INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY(category_id) REFERENCES template_categories(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS template_images (
              id TEXT PRIMARY KEY,
              template_id TEXT NOT NULL,
              slot_index INTEGER NOT NULL,
              original_url TEXT NOT NULL,
              local_path TEXT NOT NULL,
              FOREIGN KEY(template_id) REFERENCES template_presets(id) ON DELETE CASCADE,
              UNIQUE(template_id, slot_index)
            );
            CREATE INDEX IF NOT EXISTS idx_template_presets_category_sort
              ON template_presets(category_id, sort_order, name);
            CREATE INDEX IF NOT EXISTS idx_template_images_template_slot
              ON template_images(template_id, slot_index);
            """
        )
        job_columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
        if "guidance" not in job_columns:
            db.execute("ALTER TABLE jobs ADD COLUMN guidance TEXT")
        relocate_gallery_paths(db)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    value = dict(row)
    if "quality_scores" in value:
        value["quality_scores"] = json.loads(value["quality_scores"])
    value["is_mock"] = bool(value.get("is_mock", False))
    return value
