from pathlib import Path
from contextlib import closing
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from backend.scripts.activate_ai_models import activate


class ActivateAiModelsTest(unittest.TestCase):
    def make_database(self, path: Path) -> None:
        with closing(sqlite3.connect(path)) as db:
            db.execute(
                "CREATE TABLE model_presets (id TEXT PRIMARY KEY, avatar_path TEXT, "
                "enabled INTEGER NOT NULL, updated_at TEXT NOT NULL)"
            )
            for number in range(1, 21):
                db.execute(
                    "INSERT INTO model_presets VALUES(?,?,1,'old')",
                    (f"approved_model_{number:02d}", f"old-{number:02d}.jpg"),
                )
            db.execute("INSERT INTO model_presets VALUES('disabled_model','disabled.jpg',0,'old')")
            db.commit()

    def make_restored_files(self, root: Path, count: int = 20) -> None:
        root.mkdir()
        for number in range(1, count + 1):
            Image.new("RGB", (1000, 1000), "purple").save(
                root / f"approved_model_{number:02d}-ai-hd.png"
            )

    def test_activates_twenty_enabled_rows_and_preserves_disabled_row(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / "studio.sqlite3"
            restored = root / "restored"
            backup = root / "backup.sqlite3"
            self.make_database(database)
            self.make_restored_files(restored)

            activated = activate(database, restored, backup)
            backup_mtime = backup.stat().st_mtime_ns
            activated_again = activate(database, restored, backup)

            self.assertEqual((activated, activated_again), (20, 20))
            self.assertEqual(backup.stat().st_mtime_ns, backup_mtime)
            with closing(sqlite3.connect(database)) as db:
                rows = db.execute(
                    "SELECT id,avatar_path FROM model_presets WHERE enabled=1 ORDER BY id"
                ).fetchall()
                disabled = db.execute(
                    "SELECT avatar_path FROM model_presets WHERE id='disabled_model'"
                ).fetchone()[0]
                integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual(len(rows), 20)
            self.assertTrue(all("restored" in path for _, path in rows))
            self.assertEqual(disabled, "disabled.jpg")
            self.assertEqual(integrity, "ok")

    def test_missing_file_fails_before_database_or_backup_changes(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / "studio.sqlite3"
            restored = root / "restored"
            backup = root / "backup.sqlite3"
            self.make_database(database)
            self.make_restored_files(restored, count=19)

            with self.assertRaisesRegex(ValueError, "expected 20"):
                activate(database, restored, backup)

            self.assertFalse(backup.exists())
            with closing(sqlite3.connect(database)) as db:
                paths = [
                    row[0]
                    for row in db.execute(
                        "SELECT avatar_path FROM model_presets WHERE enabled=1 ORDER BY id"
                    )
                ]
            self.assertTrue(all(path.startswith("old-") for path in paths))


if __name__ == "__main__":
    unittest.main()
