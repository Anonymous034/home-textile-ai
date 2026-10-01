import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, Request, Response

from backend.app import auth, database, main


def request_for(host: str) -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/test",
        "query_string": b"",
        "headers": [(b"host", host.encode("ascii"))],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
        "scheme": "https",
    })


class LocalOnlyRouteTests(unittest.TestCase):
    def test_demo_login_still_works_on_local_host(self):
        with tempfile.TemporaryDirectory() as folder:
            with (patch.object(database, "DB_PATH", Path(folder) / "test.sqlite3"),
                  patch.dict("os.environ", {"DEMO_LOGIN_ENABLED": "1"})):
                auth.initialize_auth()
                response = Response()
                result = auth.demo_login(
                    auth.VerifyCodeBody(phone="123", code="123456"),
                    request_for("localhost:8000"),
                    response,
                )
                self.assertTrue(result["ok"])
                self.assertIn(auth.SESSION_COOKIE, response.headers["set-cookie"])

    def test_demo_login_rejects_public_host_even_behind_loopback_proxy(self):
        body = auth.VerifyCodeBody(phone="123", code="123456")
        with patch.dict("os.environ", {"DEMO_LOGIN_ENABLED": "1"}):
            with self.assertRaises(HTTPException) as error:
                auth.demo_login(body, request_for("public.example"), Response())
        self.assertEqual(error.exception.status_code, 404)

    def test_key_configuration_rejects_public_host_and_disabled_gate(self):
        body = main.LocalArkKeyCreate(api_key="x" * 24)
        for host, enabled in (("public.example", "1"), ("localhost", "0")):
            with self.subTest(host=host, enabled=enabled):
                with patch.dict("os.environ", {"LOCAL_CONFIG_ENABLED": enabled}):
                    with self.assertRaises(HTTPException) as error:
                        main.configure_local_ark_key(body, request_for(host))
                self.assertEqual(error.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
