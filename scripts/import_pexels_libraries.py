from __future__ import annotations

import json
import sqlite3
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "backend" / "data"
MODEL_DIR = DATA_DIR / "preset-models"
SCENE_DIR = DATA_DIR / "preset-scenes"
DB_PATH = DATA_DIR / "studio.sqlite3"
SOURCE_MANIFEST = DATA_DIR / "library-sources.json"


# 最终模特库：年轻成年女性、正面或接近正面、脸部清楚、完整睡衣/家居服。
# 排除睡觉、背影、情侣、遮脸、内衣/吊带和过度生活化抓拍。
MODEL_PHOTOS = [
    32636070, 20356181, 33308351, 34857594, 6976393,
    6625422, 36287324, 6625420, 6975939, 19162230,
    20356223, 8747015, 36126856, 32232283, 8667730,
    15692972, 6976312, 36287320, 6976822, 6976317,
]

# 卧室场景只选择没有人物、床和空间关系清楚的室内照片。
SCENE_PHOTOS = [
    3933240, 8251598, 35236647, 37833409, 34766501,
    6527045, 7614411, 19836795, 7033676, 14101565,
    37460678, 29120674, 20390778, 14788378, 6489083,
    5883725, 12805883, 6956846, 28542174, 2030119,
]


def page_url(photo_id: int) -> str:
    return f"https://www.pexels.com/photo/{photo_id}/"


def image_url(photo_id: int) -> str:
    return f"https://images.pexels.com/photos/{photo_id}/pexels-photo-{photo_id}.jpeg?auto=compress&cs=tinysrgb&w=1200"


def download_preview(photo_id: int, destination: Path) -> None:
    if destination.is_file() and destination.stat().st_size > 20_000:
        return
    request = urllib.request.Request(
        image_url(photo_id),
        headers={"User-Agent": "Mozilla/5.0 (compatible; local-preset-importer/1.0)"},
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        destination.write_bytes(response.read())
    with Image.open(destination) as opened:
        image = opened.convert("RGB")
        image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        image.save(destination, "JPEG", quality=88, optimize=True)


def ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS model_presets (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, avatar_path TEXT, gender TEXT,
          style_tag TEXT, prompt TEXT, enabled INTEGER NOT NULL DEFAULT 1,
          sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scene_presets (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, preview_path TEXT, scene_type TEXT,
          prompt TEXT, enabled INTEGER NOT NULL DEFAULT 1,
          sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
    )


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    SCENE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    manifest: dict[str, list[dict[str, object]]] = {"models": [], "scenes": []}

    model_rows: list[tuple[object, ...]] = []
    for index, photo_id in enumerate(MODEL_PHOTOS, start=1):
        path = MODEL_DIR / f"pajama-model-{index:02d}.jpg"
        download_preview(photo_id, path)
        source = page_url(photo_id)
        model_rows.append((
            f"pajama_model_{index:02d}", f"睡衣模特 {index:02d}", str(path.resolve()),
            "female", "年轻成年女性 · 正面/近正面 · 完整睡衣/家居服 · 非擦边",
            f"source={source}; license=Pexels License", 1, index, now, now,
        ))
        manifest["models"].append({"id": f"pajama_model_{index:02d}", "pexels_photo_id": photo_id, "source_page": source, "license": "Pexels License"})

    scene_rows: list[tuple[object, ...]] = []
    for index, photo_id in enumerate(SCENE_PHOTOS, start=1):
        path = SCENE_DIR / f"bedroom-scene-{index:02d}.jpg"
        download_preview(photo_id, path)
        source = page_url(photo_id)
        scene_rows.append((
            f"bedroom_scene_{index:02d}", f"卧室场景 {index:02d}", str(path.resolve()),
            "真实卧室 · 无人物", f"source={source}; license=Pexels License",
            1, index, now, now,
        ))
        manifest["scenes"].append({"id": f"bedroom_scene_{index:02d}", "pexels_photo_id": photo_id, "source_page": source, "license": "Pexels License"})

    with sqlite3.connect(DB_PATH) as db:
        ensure_schema(db)
        db.execute("DELETE FROM model_presets WHERE id LIKE 'pajama_model_%'")
        db.execute("DELETE FROM scene_presets WHERE id LIKE 'bedroom_scene_%'")
        db.executemany(
            "INSERT INTO model_presets(id,name,avatar_path,gender,style_tag,prompt,enabled,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            model_rows,
        )
        db.executemany(
            "INSERT INTO scene_presets(id,name,preview_path,scene_type,prompt,enabled,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            scene_rows,
        )
        db.commit()

    SOURCE_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Imported {len(model_rows)} pajama models and {len(scene_rows)} bedroom scenes")


if __name__ == "__main__":
    main()
