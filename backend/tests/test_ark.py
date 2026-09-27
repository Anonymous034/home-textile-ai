import os
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch

from backend.app.providers.ark import AgentPlanSeedreamSkillProvider


class ArkNetworkTests(unittest.TestCase):
    def test_default_generation_client_ignores_injected_proxy(self):
        with patch.dict(os.environ, {"ARK_PROXY_MODE": "direct"}), patch(
            "urllib.request.getproxies", return_value={"https": "http://127.0.0.1:7897"}
        ):
            opener = AgentPlanSeedreamSkillProvider._opener()
        handlers = [handler for handler in opener.handlers if isinstance(handler, urllib.request.ProxyHandler)]
        self.assertEqual(handlers, [])

    def test_environment_mode_uses_configured_proxy(self):
        with patch.dict(os.environ, {"ARK_PROXY_MODE": "environment"}), patch(
            "urllib.request.getproxies", return_value={"https": "http://127.0.0.1:7897"}
        ):
            opener = AgentPlanSeedreamSkillProvider._opener()
        handlers = [handler for handler in opener.handlers if isinstance(handler, urllib.request.ProxyHandler)]
        self.assertEqual(handlers[0].proxies["https"], "http://127.0.0.1:7897")


class ArkSelfCheckTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.key = patch.dict(os.environ, {"ARK_API_KEY": "test-key-that-is-never-sent"})
        self.key.start()
        self.provider = AgentPlanSeedreamSkillProvider()

    async def asyncTearDown(self):
        self.key.stop()

    async def test_probe_records_reachable_without_generation(self):
        with patch.object(self.provider, "_probe_sync", return_value=401) as probe:
            state = await self.provider.probe_connection()
        self.assertTrue(state["connected"])
        self.assertEqual(state["http_status"], 401)
        probe.assert_called_once()

    async def test_offline_preflight_does_not_submit_generation(self):
        with patch.object(self.provider, "_probe_sync", side_effect=urllib.error.URLError(PermissionError(5, "denied"))), \
             patch.object(self.provider, "_request_sync") as generation:
            state = await self.provider.probe_connection()
            self.assertEqual(state["error_code"], "network_denied")
            with self.assertRaises(RuntimeError):
                await self.provider.submit_job(object())
            generation.assert_not_called()

    async def test_connection_state_recovers_after_network_returns(self):
        with patch.object(self.provider, "_probe_sync", side_effect=[urllib.error.URLError(TimeoutError()), 401]):
            self.assertFalse((await self.provider.probe_connection())["connected"])
            recovered = await self.provider.probe_connection()
        self.assertTrue(recovered["connected"])
        self.assertIsNone(recovered["error_code"])


if __name__ == "__main__":
    unittest.main()
