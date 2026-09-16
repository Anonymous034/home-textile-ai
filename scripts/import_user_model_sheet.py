from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "backend" / "data"
SOURCE_SHEET = DATA_DIR / "model-source-sheets" / "user-approved-models-01.png"
OUTPUT_DIR = DATA_DIR / "preset-models"
DB_PATH = DATA_DIR / "studio.sqlite3"
SOURCE_MANIFEST = DATA_DIR / "library-sources.json"

# 这张用户确认的拼图不是紧贴画布边缘，所以按实际卡片边界切割。
X_RANGES = [(10, 146), (155, 285), (297, 427), (439, 569), (581, 711)]
Y_RANGES = [(10, 146), (155, 285), (297, 427), (439, 569)]


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS model_presets (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, avatar_path TEXT, gender TEXT,
          style_tag TEXT, prompt TEXT, enabled INTEGER NOT NULL DEFAULT 1,
          sort_order INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )
        """
    )


def crop_models() -> list[Path]:
    if not SOURCE_SHEET.is_file():
        raise FileNotFoundError(f"找不到模特总图：{SOURCE_SHEET}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source = Image.open(SOURCE_SHEET).convert("RGB")
    outputs: list[Path] = []

    index = 0
    for top, bottom in Y_RANGES:
        for left, right in X_RANGES:
            index += 1
            crop = source.crop((left, top, right, bottom))
            crop = crop.resize((512, 512), Image.Resampling.LANCZOS)
            output = OUTPUT_DIR / f"approved-model-{index:02d}.jpg"
            crop.save(output, "JPEG", quality=92, optimize=True)
            outputs.append(output)

    return outputs


def update_database(outputs: list[Path]) -> None:
    now = datetime.now(UTC).isoformat()
    rows = []
    for index, output in enumerate(outputs, start=1):
        rows.append(
            (
                f"approved_model_{index:02d}",
                f"精选模特 {index:02d}",
                str(output.resolve()),
                "mixed",
                "用户确认 · 正面模特",
                "source=user-provided contact sheet; usage=local demo preset",
                1,
                index,
                now,
                now,
            )
        )

    with sqlite3.connect(DB_PATH) as db:
        ensure_schema(db)
        db.execute("DELETE FROM model_presets")
        db.executemany(
            "INSERT INTO model_presets(id,name,avatar_path,gender,style_tag,prompt,enabled,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        db.commit()


def update_manifest(outputs: list[Path]) -> None:
    manifest = {"models": [], "scenes": []}
    if SOURCE_MANIFEST.is_file():
        manifest.update(json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8")))

    manifest["models"] = [
        {
            "id": f"approved_model_{index:02d}",
            "source_type": "user_provided",
            "source_sheet": str(SOURCE_SHEET.resolve()),
            "crop_index": index,
            "local_file": str(output.resolve()),
        }
        for index, output in enumerate(outputs, start=1)
    ]
    SOURCE_MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    outputs = crop_models()
    update_database(outputs)
    update_manifest(outputs)
    print(f"Imported {len(outputs)} user-approved model presets")


if __name__ == "__main__":
    main()
