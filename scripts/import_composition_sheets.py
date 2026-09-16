from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "backend" / "data"
COMPOSITION_DIR = DATA_DIR / "compositions"
SOURCE_DIR = COMPOSITION_DIR / "sources"
PREVIEW_DIR = COMPOSITION_DIR / "previews"
DB_PATH = DATA_DIR / "studio.sqlite3"


def active_ranges(flags: list[bool], minimum: int = 24) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for index, active in enumerate(flags + [False]):
        if active and start is None:
            start = index
        elif not active and start is not None:
            if index - start >= minimum:
                ranges.append((start, index))
            start = None
    return ranges


def find_tiles(image: Image.Image) -> list[tuple[int, int, int, int]]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()

    # 深色背景是总表间隔；只要一列/行中存在足够多的亮色像素，就属于构图卡片。
    columns = [sum(max(pixels[x, y]) > 48 for y in range(height)) > 18 for x in range(width)]
    rows = [sum(max(pixels[x, y]) > 48 for x in range(width)) > 18 for y in range(height)]
    x_ranges = active_ranges(columns)
    y_ranges = active_ranges(rows)

    tiles: list[tuple[int, int, int, int]] = []
    for top, bottom in y_ranges:
        for left, right in x_ranges:
            bright = 0
            for y in range(top, bottom, max(1, (bottom - top) // 18)):
                for x in range(left, right, max(1, (right - left) // 18)):
                    bright += max(pixels[x, y]) > 48
            if bright >= 32:
                tiles.append((left, top, right, bottom))
    return tiles


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute(
        """
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
        )
        """
    )


def import_sheets(paths: list[Path]) -> int:
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    records: list[tuple[object, ...]] = []
    global_index = 1
    now = datetime.now(UTC).isoformat()
    mask_meaning = json.dumps(
        {
            "white": "model_pose_and_position",
            "blue": "furniture_and_bedding_placement",
            "gray": "scene_and_spatial_reference",
            "source": "user_provided_composition_sheet",
        },
        ensure_ascii=False,
    )

    for sheet_index, source in enumerate(paths, start=1):
        if not source.is_file():
            raise FileNotFoundError(source)
        copied_source = SOURCE_DIR / f"composition-sheet-{sheet_index:02d}{source.suffix.lower()}"
        shutil.copy2(source, copied_source)

        with Image.open(source) as opened:
            image = opened.convert("RGB")
            tiles = find_tiles(image)
            if not tiles:
                raise RuntimeError(f"没有在 {source.name} 中识别到构图方格")
            for sheet_tile_index, box in enumerate(tiles, start=1):
                composition_id = f"bed_composition_{global_index:03d}"
                preview = PREVIEW_DIR / f"{composition_id}.png"
                image.crop(box).save(preview, "PNG", optimize=True)
                records.append(
                    (
                        composition_id,
                        f"床品构图 {global_index:02d}",
                        str(preview.resolve()),
                        "白色剪影指定模特动作与位置，蓝色区域指定家具和床品摆放。",
                        str(preview.resolve()),
                        None,
                        mask_meaning,
                        1,
                        global_index,
                        now,
                        now,
                    )
                )
                global_index += 1

    with sqlite3.connect(DB_PATH) as db:
        ensure_schema(db)
        db.execute("DELETE FROM composition_presets WHERE id LIKE 'bed_composition_%'")
        db.executemany(
            """
            INSERT INTO composition_presets(
              id,name,preview_path,description,pose_path,depth_path,masks_json,
              enabled,sort_order,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            records,
        )
        db.commit()
    return len(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="把构图总表拆成独立构图预设并写入本地 SQLite。")
    parser.add_argument("sheets", nargs="+", type=Path)
    args = parser.parse_args()
    count = import_sheets(args.sheets)
    print(f"Imported {count} composition presets into {DB_PATH}")


if __name__ == "__main__":
    main()
