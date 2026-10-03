import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request

from backend.app import main


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
