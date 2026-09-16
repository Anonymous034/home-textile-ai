import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from starlette.requests import Request

from backend.app.main import PersonalKeyCheck, verify_user_key, personal_key_status
from backend.app.providers.replicate import current_configuration, ReplicaProvider, ReplicaProviderError
from backend.app.providers.ark import AgentPlanSeedreamSkillProvider
from backend.app.providers.detail import plan_configuration
from backend.app.providers.buyer_show import configuration as buyer_configuration
from backend.app.user_key import current_user_key
from backend.app.key_health import inspect_key, KeyHealthError, _history


class FakeClient:
    def __init__(self, statuses):
        self.statuses = iter(statuses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, *_args, **_kwargs):
        status = next(self.statuses)
        return httpx.Response(status, json={"error": {"message": "missing model"}}, request=httpx.Request("POST", "https://example.com"))


def local_request(origin: str | None = None):
    headers = [] if origin is None else [(b"origin", origin.encode())]
    return Request({"type": "http", "method": "POST", "path": "/api/access/verify-user-key", "headers": headers, "client": ("127.0.0.1", 1234)})


class PersonalKeyTests(unittest.IsolatedAsyncioTestCase):
    async def test_verified_only_when_unauthenticated_request_is_rejected(self):
        key = PersonalKeyCheck(api_key="a" * 32)
        with patch("backend.app.key_health.new_http_client", return_value=FakeClient([400, 401])):
            self.assertEqual(await verify_user_key(key, local_request()), {"ok": True})
        with patch("backend.app.key_health.new_http_client", return_value=FakeClient([400, 400])):
            with self.assertRaises(HTTPException) as caught:
                await verify_user_key(key, local_request())
            self.assertEqual(caught.exception.status_code, 503)

    async def test_invalid_key_is_rejected(self):
        with patch("backend.app.key_health.new_http_client", return_value=FakeClient([401, 401])):
            with self.assertRaises(HTTPException) as caught:
                await verify_user_key(PersonalKeyCheck(api_key="a" * 32), local_request())
            self.assertEqual(caught.exception.status_code, 401)

    async def test_configured_public_origin_is_allowed_but_unknown_origin_is_rejected(self):
        key = PersonalKeyCheck(api_key="a" * 32)
        with patch.dict("os.environ", {"FRONTEND_ORIGIN": "http://49.232.95.85"}):
            with patch("backend.app.key_health.new_http_client", return_value=FakeClient([400, 401])):
                self.assertEqual(await verify_user_key(key, local_request("http://49.232.95.85/")), {"ok": True})
            with self.assertRaises(HTTPException) as caught:
                await verify_user_key(key, local_request("https://evil.example"))
            self.assertEqual(caught.exception.status_code, 403)

    async def test_repeated_probe_establishes_and_loses_stability(self):
        _history.clear()
        key = "s" * 32
        for expected in (False, False, True):
            with patch("backend.app.key_health.new_http_client", return_value=FakeClient([400, 401])):
                self.assertEqual((await inspect_key(key))["stable"], expected)
        with patch("backend.app.key_health.new_http_client", return_value=FakeClient([401])):
            with self.assertRaises(KeyHealthError):
                await inspect_key(key)
        with patch("backend.app.key_health.new_http_client", return_value=FakeClient([400, 401])):
            status = await inspect_key(key)
            self.assertFalse(status["stable"])
            self.assertNotIn(key, str(status))

    async def test_status_endpoint_requires_a_personal_key(self):
        with self.assertRaises(HTTPException) as caught:
            await personal_key_status(local_request())
        self.assertEqual(caught.exception.status_code, 400)
        token = current_user_key.set("m" * 32)
        try:
            with patch("backend.app.key_health.new_http_client", return_value=FakeClient([400, 401])):
                self.assertTrue((await personal_key_status(local_request()))["connected"])
        finally:
            current_user_key.reset(token)

    async def test_personal_key_overrides_owner_only_in_scope(self):
        with patch.dict("os.environ", {"ARK_API_KEY": "o" * 32}):
            token = current_user_key.set("u" * 32)
            try:
                self.assertEqual(current_configuration()[0], "u" * 32)
            finally:
                current_user_key.reset(token)
            self.assertEqual(current_configuration()[0], "o" * 32)

    async def test_personal_key_is_reused_for_planning(self):
        settings = {"DETAIL_PLAN_ENDPOINT": "https://example.com/chat", "DETAIL_PLAN_MODEL": "vision-model", "DETAIL_PLAN_API_KEY": "o" * 32}
        with patch.dict("os.environ", settings):
            image_token = current_user_key.set("i" * 32)
            try:
                self.assertEqual(plan_configuration()[0], "i" * 32)
                self.assertEqual(buyer_configuration()[0], "i" * 32)
            finally:
                current_user_key.reset(image_token)
            self.assertEqual(plan_configuration()[0], "o" * 32)

    async def test_generation_stops_before_submission_when_recheck_fails(self):
        token = current_user_key.set("x" * 32)
        try:
            with patch("backend.app.key_health.inspect_key", side_effect=KeyHealthError(401, "authentication", "invalid")):
                with self.assertRaises(ReplicaProviderError) as replica_error:
                    await ReplicaProvider().generate([], (1024, 1024), False, "", Path("unused.png"), lambda *_: None)
                self.assertEqual(replica_error.exception.code, "authentication")
                with self.assertRaises(RuntimeError):
                    await AgentPlanSeedreamSkillProvider().submit_job(None)
        finally:
            current_user_key.reset(token)
