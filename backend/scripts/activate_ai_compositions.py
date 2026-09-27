from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "studio.sqlite3"
BACKUP_PATH = ROOT / "data" / "studio.before-ai-restoration.sqlite3"
RESTORED_DIR = ROOT / "data" / "compositions" / "ai-restored"


def main() -> None:
    files = sorted(RESTORED_DIR.glob("bed_composition_*-ai-hd.png"))
    if len(files) != 61:
        raise SystemExit(f"expected 61 restored images, found {len(files)}")
    if not BACKUP_PATH.exists():
        shutil.copy2(DB_PATH, BACKUP_PATH)

    updated_at = datetime.now(UTC).isoformat()
    with sqlite3.connect(DB_PATH) as db:
        db.execute("BEGIN IMMEDIATE")
        for path in files:
            preset_id = path.name.removesuffix("-ai-hd.png")
            cursor = db.execute(
                "UPDATE composition_presets SET preview_path=?, updated_at=? WHERE id=?",
                (str(path.resolve()), updated_at, preset_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"missing composition preset: {preset_id}")
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"database integrity check failed: {integrity}")

    print(f"activated={len(files)} integrity=ok backup={BACKUP_PATH}")


if __name__ == "__main__":
    main()
