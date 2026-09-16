import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend.app import account, database
from backend.app.user_key import current_user_key


class AccountTests(unittest.TestCase):
    def test_works_are_scoped_and_balance_is_not_invented(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = root / "results" / "pattern" / "job" / "1.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"image")
            with patch.object(database, "DB_PATH", root / "test.sqlite3"), patch.object(account, "RESULT_DIR", root / "results"):
                account.initialize_account()
                # Existing output is owned by the demo account.
                owner_works = account.list_works()["items"]
                self.assertEqual(len(owner_works), 1)
                self.assertIsNone(account.credits()["balance"])
                token = current_user_key.set("personal-key-" + "x" * 24)
                try:
                    self.assertEqual(account.list_works()["items"], [])
                    with self.assertRaises(HTTPException) as denied:
                        account.work_image(owner_works[0]["id"])
                    self.assertEqual(denied.exception.status_code, 404)
                    other = root / "results" / "sketch" / "new" / "result.png"
                    other.parent.mkdir(parents=True)
                    other.write_bytes(b"image")
                    account.record_work(other)
                    self.assertEqual(len(account.list_works()["items"]), 1)
                    self.assertEqual(account.credits()["pending_usage"][0]["points"], 8)
                finally:
                    current_user_key.reset(token)
                self.assertEqual(len(account.list_works()["items"]), 1)
