import os
import unittest
from unittest.mock import patch

import httpx

from backend.app.providers import detail, plan_connection


class PlanConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_client_ignores_injected_proxy(self):
        with patch.dict(os.environ, {"DETAIL_PLAN_PROXY_MODE": "direct", "HTTPS_PROXY": "http://127.0.0.1:7897"}):
            client = plan_connection.plan_http_client(httpx.Timeout(6.0))
        try:
            self.assertFalse(client._trust_env)
        finally:
            await client.aclose()

    async def test_probe_accepts_http_response_without_auth_or_generation(self):
        def respond(request):
            self.assertEqual(request.method, "GET")
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(401)

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch.object(detail, "plan_configuration", return_value=("secret", "https://planner.test/responses", "model")), \
             patch.object(plan_connection, "plan_http_client", return_value=client):
            state = await plan_connection.probe()
        self.assertTrue(state["connected"])
        self.assertEqual(state["http_status"], 401)


if __name__ == "__main__":
    unittest.main()
