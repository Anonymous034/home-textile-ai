import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import auth, database


class SmsLoginTests(unittest.TestCase):
    def test_aliyun_adapter_submits_only_to_configured_template(self):
        from alibabacloud_dysmsapi20170525 import client as sms_client

        with patch.dict("os.environ", {
            "ALIBABA_CLOUD_ACCESS_KEY_ID": "test-id",
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test-secret",
            "ALIYUN_SMS_SIGN_NAME": "测试签名",
            "ALIYUN_SMS_TEMPLATE_CODE": "SMS_123456789",
            "AUTH_OTP_PEPPER": "test-only-secret",
        }), patch.object(sms_client, "Client") as client_class:
            client_class.return_value.send_sms_with_options_async = AsyncMock(
                return_value=SimpleNamespace(body=SimpleNamespace(code="OK"))
            )
            import asyncio

            result = asyncio.run(auth.ConfiguredSmsProvider().send("+8613800138000", "246810"))
            self.assertEqual(result, "aliyun")
            request = client_class.return_value.send_sms_with_options_async.await_args.args[0]
            self.assertEqual(request.phone_numbers, "13800138000")
            self.assertEqual(request.template_param, '{"code":"246810"}')
            self.assertEqual(request.sign_name, "测试签名")

    def test_aliyun_failure_exposes_only_error_code(self):
        from alibabacloud_dysmsapi20170525 import client as sms_client

        with patch.dict("os.environ", {
            "ALIBABA_CLOUD_ACCESS_KEY_ID": "test-id",
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test-secret",
            "ALIYUN_SMS_SIGN_NAME": "测试签名",
            "ALIYUN_SMS_TEMPLATE_CODE": "SMS_123456789",
            "AUTH_OTP_PEPPER": "test-only-secret",
        }), patch.object(sms_client, "Client") as client_class:
            client_class.return_value.send_sms_with_options_async = AsyncMock(
                return_value=SimpleNamespace(body=SimpleNamespace(code="isv.SMS_SIGNATURE_ILLEGAL", message="phone and code must stay private"))
            )
            import asyncio
            from fastapi import HTTPException

            with self.assertRaises(HTTPException) as caught:
                asyncio.run(auth.ConfiguredSmsProvider().send("+8613800138000", "246810"))
            self.assertIn("isv.SMS_SIGNATURE_ILLEGAL", caught.exception.detail)
            self.assertNotIn("phone and code", caught.exception.detail)

    def test_code_is_not_returned_and_is_one_time(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(database, "DB_PATH", Path(folder) / "auth.sqlite3"), \
                 patch.dict("os.environ", {
                     "AUTH_OTP_PEPPER": "test-only-secret", "DEMO_SMS_MODE": "aliyun",
                     "ALIBABA_CLOUD_ACCESS_KEY_ID": "test-id",
                     "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "test-secret",
                     "ALIYUN_SMS_SIGN_NAME": "测试签名",
                     "ALIYUN_SMS_TEMPLATE_CODE": "SMS_123456789",
                 }), \
                 patch.object(auth, "send_sms_code", new_callable=AsyncMock) as sender, \
                 patch.object(auth.secrets, "randbelow", return_value=246810):
                sender.return_value = "aliyun"
                auth.initialize_auth()
                app = FastAPI()
                app.include_router(auth.router)
                client = TestClient(app)

                sent = client.post("/api/auth/request-code", json={
                    "phone": "13800138000", "challenge_id": "add-8-4", "human_answer": "12",
                })
                self.assertEqual(sent.status_code, 200)
                self.assertNotIn("246810", sent.text)
                sender.assert_awaited_once_with("+8613800138000", "246810")
                self.assertEqual(client.post("/api/auth/request-code", json={"phone": "13800138000"}).status_code, 429)

                wrong = client.post("/api/auth/verify-code", json={"phone": "13800138000", "code": "000000"})
                self.assertEqual(wrong.status_code, 400)
                valid = client.post("/api/auth/verify-code", json={"phone": "13800138000", "code": "246810"})
                self.assertEqual(valid.status_code, 200)
                self.assertIn("studio_session=", valid.headers.get("set-cookie", ""))
                self.assertEqual(client.post("/api/auth/verify-code", json={"phone": "13800138000", "code": "246810"}).status_code, 400)

    def test_mock_mode_uses_random_six_digit_code_and_validates_it(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(database, "DB_PATH", Path(folder) / "auth.sqlite3"), \
                 patch.dict("os.environ", {"DEMO_SMS_MODE": "mock", "DEMO_SMS_CODE": "123456"}), \
                 patch.object(auth.secrets, "randbelow", return_value=7), \
                 patch.object(auth, "send_sms_code", new_callable=AsyncMock) as sender:
                sender.return_value = "mock"
                auth.initialize_auth()
                app = FastAPI()
                app.include_router(auth.router)
                client = TestClient(app)

                sent = client.post("/api/auth/request-code", json={"phone": "13800138000"})
                self.assertEqual(sent.status_code, 200)
                self.assertNotIn("000007", sent.text)
                sender.assert_awaited_once_with("+8613800138000", "000007")
                for invalid in ("7", "1234567", "abcdef", "１２３４５６"):
                    self.assertEqual(client.post("/api/auth/verify-code", json={"phone": "13800138000", "code": invalid}).status_code, 422)
                self.assertEqual(client.post("/api/auth/verify-code", json={"phone": "13800138000", "code": "000007"}).status_code, 200)
                self.assertEqual(client.post("/api/auth/verify-code", json={"phone": "13800138000", "code": "000007"}).status_code, 400)

    def test_missing_aliyun_settings_never_attempts_send(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(database, "DB_PATH", Path(folder) / "auth.sqlite3"), \
                 patch.dict("os.environ", {"DEMO_SMS_MODE": "aliyun", "ALIBABA_CLOUD_ACCESS_KEY_ID": "", "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "", "ALIYUN_SMS_SIGN_NAME": "", "ALIYUN_SMS_TEMPLATE_CODE": ""}), \
                 patch.object(auth.secrets, "randbelow", return_value=123456):
                auth.initialize_auth()
                app = FastAPI()
                app.include_router(auth.router)
                result = TestClient(app).post("/api/auth/request-code", json={"phone": "13800138000"})
                self.assertEqual(result.status_code, 503)
                self.assertNotIn("123456", result.text)
                # Configuration errors must not consume the phone's cooldown.
                retry = TestClient(app).post("/api/auth/request-code", json={"phone": "13800138000"})
                self.assertEqual(retry.status_code, 503)


if __name__ == "__main__":
    unittest.main()
