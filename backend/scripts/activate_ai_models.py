from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "studio.sqlite3"
BACKUP_PATH = ROOT / "data" / "studio.before-model-ai-restoration.sqlite3"
RESTORED_DIR = ROOT / "data" / "model-ai-restored"
EXPECTED_COUNT = 20


def restored_files(root: Path) -> list[Path]:
    files = sorted(root.glob("approved_model_??-ai-hd.png"))
    expected_ids = {f"approved_model_{number:02d}" for number in range(1, 21)}
    actual_ids = {path.name.removesuffix("-ai-hd.png") for path in files}
    if len(files) != EXPECTED_COUNT or actual_ids != expected_ids:
        raise ValueError(f"expected 20 restored model images, found {len(files)}")
    return files


def activate(database: Path, restored_root: Path, backup: Path) -> int:
    files = restored_files(restored_root)
    if not database.is_file():
        raise FileNotFoundError(database)
    if not backup.exists():
        shutil.copy2(database, backup)

    updated_at = datetime.now(UTC).isoformat()
    with closing(sqlite3.connect(database)) as db:
        db.execute("BEGIN IMMEDIATE")
        for path in files:
            preset_id = path.name.removesuffix("-ai-hd.png")
            cursor = db.execute(
                "UPDATE model_presets SET avatar_path=?, updated_at=? "
                "WHERE id=? AND enabled=1",
                (str(path.resolve()), updated_at, preset_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"missing enabled model preset: {preset_id}")
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"database integrity check failed: {integrity}")
        db.commit()
    return len(files)


def main() -> None:
    count = activate(DB_PATH, RESTORED_DIR, BACKUP_PATH)
    print(f"activated={count} integrity=ok backup={BACKUP_PATH}")


if __name__ == "__main__":
    main()
