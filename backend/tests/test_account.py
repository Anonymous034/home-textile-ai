import tempfile
import unittest
from datetime import UTC, datetime, timedelta
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

    def test_mock_payment_packages_custom_amount_and_idempotent_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            results = root / "results"
            results.mkdir()
            with patch.object(database, "DB_PATH", root / "test.sqlite3"), patch.object(account, "RESULT_DIR", results):
                account.initialize_account()

                expected = {
                    "starter": (19_900, 2_200),
                    "popular": (48_000, 6_600),
                    "pro": (144_000, 26_400),
                }
                for package_id, (amount, points) in expected.items():
                    response = account.create_payment_order(account.PaymentOrderCreate(package_id=package_id))
                    self.assertTrue(response["is_mock"])
                    self.assertEqual(response["order"]["amount_cents"], amount)
                    self.assertEqual(response["order"]["points"], points)

                custom = account.create_payment_order(account.PaymentOrderCreate(custom_amount_yuan=321))["order"]
                self.assertEqual(custom["amount_cents"], 32_100)
                self.assertEqual(custom["points"], 3_210)

                first = account.complete_payment_order(custom["id"])
                second = account.complete_payment_order(custom["id"])
                self.assertFalse(first["already_completed"])
                self.assertTrue(second["already_completed"])
                self.assertEqual(first["balance"], 3_210)
                self.assertEqual(second["balance"], 3_210)

                ledger = account.credits()
                self.assertEqual(ledger["balance"], 3_210)
                self.assertEqual(len(ledger["events"]), 1)
                self.assertEqual(ledger["events"][0]["delta"], 3_210)
                self.assertIn("模拟微信支付充值", ledger["events"][0]["reason"])

    def test_mock_payment_rejects_invalid_cancelled_expired_and_missing_orders(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            results = root / "results"
            results.mkdir()
            with patch.object(database, "DB_PATH", root / "test.sqlite3"), patch.object(account, "RESULT_DIR", results):
                account.initialize_account()

                for request in (
                    account.PaymentOrderCreate(),
                    account.PaymentOrderCreate(package_id="missing"),
                    account.PaymentOrderCreate(custom_amount_yuan=0),
                    account.PaymentOrderCreate(custom_amount_yuan=5001),
                    account.PaymentOrderCreate(package_id="starter", custom_amount_yuan=10),
                ):
                    with self.assertRaises(HTTPException) as invalid:
                        account.create_payment_order(request)
                    self.assertEqual(invalid.exception.status_code, 400)

                cancelled = account.create_payment_order(account.PaymentOrderCreate(package_id="starter"))["order"]
                account.cancel_payment_order(cancelled["id"])
                with self.assertRaises(HTTPException) as cancelled_error:
                    account.complete_payment_order(cancelled["id"])
                self.assertEqual(cancelled_error.exception.status_code, 409)

                expired = account.create_payment_order(account.PaymentOrderCreate(package_id="popular"))["order"]
                past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
                with database.connect() as db:
                    db.execute("UPDATE payment_orders SET expires_at=? WHERE id=?", (past, expired["id"]))
                with self.assertRaises(HTTPException) as expired_error:
                    account.complete_payment_order(expired["id"])
                self.assertEqual(expired_error.exception.status_code, 409)
                self.assertEqual(account.get_payment_order(expired["id"])["order"]["status"], "expired")

                with self.assertRaises(HTTPException) as missing:
                    account.complete_payment_order("not-found")
                self.assertEqual(missing.exception.status_code, 404)
                self.assertIsNone(account.credits()["balance"])
