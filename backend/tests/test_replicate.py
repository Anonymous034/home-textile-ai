import asyncio
import base64
import io
import json
import os
import socket
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import FastAPI
from PIL import Image

from backend.app import database, replicate
from backend.app.replicate_guard import ReplicaGuard
from backend.app.replicate_rules import target_size, proportional_size, replica_prompt
from backend.app.providers.replicate import ReplicaProvider, ReplicaProviderError, ENDPOINT, check_connectivity, connection_failure, connectivity, finish_image, explicit_size_bounds, new_http_client


def image_bytes(size=(120, 160), color="blue", exif=False):
    buffer = io.BytesIO()
    image = Image.new("RGB", size, color)
    if exif:
        metadata = Image.Exif()
        metadata[274] = 6
        image.save(buffer, "JPEG", exif=metadata)
    else:
        image.save(buffer, "PNG")
    return buffer.getvalue()


class RuleTests(unittest.TestCase):
    def test_size_defaults_and_explicit_override(self):
        self.assertEqual(target_size(1200, 1600, "保持参考图尺寸，背景更明亮"), (1200, 1600, False))
        self.assertEqual(target_size(1200, 1600, "输出尺寸：800×1200 px"), (800, 1200, True))
        self.assertEqual(target_size(1200, 1600, "800x1200像素，800×1200 px"), (800, 1200, True))
        for notes in ["800×1200", "800×1200 px 或 1600×1200 px", "改成 4K", "画布改成正方形", "比例为 3:4", "输出尺寸更大", "输出宽800高1200", "放大图片"]:
            with self.subTest(notes=notes), self.assertRaises(ValueError):
                target_size(1200, 1600, notes)

    def test_exact_proportions_only(self):
        width, height = proportional_size(600, 800, 3_686_400, 16_777_216)
        self.assertEqual(width * 800, height * 600)
        self.assertGreaterEqual(width * height, 3_686_400)
        with self.assertRaises(ValueError):
            proportional_size(4093, 4091, 3_686_400, 10_000_000)

    def test_text_and_notes_priority(self):
        for extras in [0, 1, 2]:
            prompt = replica_prompt(True, "把产品改为红色并移除 Logo", extras, 600, 800)
            self.assertIn(f"图{extras + 2}是唯一场景参考图", prompt)
            self.assertIn("去除参考图中的叠加文字", prompt)
            self.assertIn("不得删除新产品自身的品牌 Logo", prompt)
            self.assertIn("最高优先级", prompt)
            self.assertIn("把产品改为红色并移除 Logo", prompt)
            self.assertIn("优先参考图角度", prompt)
        self.assertIn("旧产品上的包装文字随旧产品一起移除", replica_prompt(False, "", 0, 600, 800))

    def test_exif_and_corrupt_images(self):
        content, width, height = replicate.normalize_image(image_bytes((120, 160), exif=True))
        self.assertEqual((width, height), (160, 120))
        with Image.open(io.BytesIO(content)) as image:
            self.assertEqual(image.size, (160, 120))
            self.assertIsNone(image.getexif().get(274))
        with self.assertRaises(ValueError):
            replicate.normalize_image(b"not an image")

    def test_output_never_crops_or_stretches(self):
        with TemporaryDirectory() as folder:
            output = Path(folder) / "out.png"
            finish_image(image_bytes((240, 320)), output, (120, 160))
            with Image.open(output) as image:
                self.assertEqual(image.size, (120, 160))
            with self.assertRaises(ReplicaProviderError) as error:
                finish_image(image_bytes((160, 160)), output, (120, 160))
            self.assertEqual(error.exception.code, "ratio_mismatch")
            with self.assertRaises(ReplicaProviderError):
                finish_image(b"broken", output, (120, 160))

    def test_limits_only_from_explicit_parameter_rejection(self):
        rejection = {"error": {"code": "InvalidParameter", "message": "image size must be at least 3686400 pixels"}}
        self.assertEqual(explicit_size_bounds(rejection)[0], 3686400)
        self.assertIsNone(explicit_size_bounds({"error": {"code": "AuthenticationError", "message": "size at least 3686400"}}))
        self.assertIsNone(explicit_size_bounds({"error": {"code": "InvalidParameter", "message": "input image is invalid"}}))
        self.assertIsNone(explicit_size_bounds({"error": {"code": "InvalidParameter", "message": "input image size must be at least 3686400 pixels"}}))


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        connectivity.__init__()
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.paths = [self.root / "main.png", self.root / "reference.png"]
        for path in self.paths:
            path.write_bytes(image_bytes())
        self.env = patch.dict(os.environ, {"ARK_API_KEY": "test-secret-never-send-outside-mock", "ARK_IMAGE_ENDPOINT": ENDPOINT, "ARK_IMAGE_MODEL": "doubao-seedream-5.0-lite"})
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
        self.folder.cleanup()

    async def generate(self, handler):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ReplicaProvider(client).generate(self.paths, (120, 160), True, "", self.root / "output.png", lambda *args: None)

    async def test_owned_client_ignores_injected_process_proxy(self):
        client = new_http_client()
        try:
            self.assertFalse(client._trust_env)
        finally:
            await client.aclose()

    async def test_connectivity_diagnoses_dns_and_tcp_failures(self):
        try:
            raise httpx.ConnectError("denied") from PermissionError(5, "Access denied")
        except httpx.ConnectError as error:
            self.assertEqual(connection_failure(error)[0], "network_denied")
        try:
            raise httpx.ConnectError("failed") from socket.gaierror("DNS unavailable")
        except httpx.ConnectError as error:
            self.assertEqual(connection_failure(error)[0], "dns_failed")
        try:
            raise httpx.ConnectTimeout("timed out")
        except httpx.ConnectTimeout as error:
            self.assertEqual(connection_failure(error)[0], "tcp_timeout")

    async def test_connectivity_probe_and_circuit_breaker(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401))) as client:
            result = await check_connectivity(client)
        self.assertTrue(result["connected"])
        self.assertEqual(result["http_status"], 401)

        def offline(request):
            raise httpx.ConnectError("offline", request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(offline)) as client:
            with patch("backend.app.providers.replicate.backoff", new=AsyncMock()):
                for _ in range(3):
                    with self.assertRaises(ReplicaProviderError):
                        await check_connectivity(client)
                calls_before = connectivity.consecutive_failures
                with self.assertRaises(ReplicaProviderError) as error:
                    await check_connectivity(client)
        self.assertEqual(error.exception.code, "circuit_open")
        self.assertEqual(connectivity.consecutive_failures, calls_before)

    async def test_startup_probes_before_serving_and_retries_after_failure(self):
        with patch.dict(os.environ, {"REPLICA_DISABLE_MONITOR": "0"}), \
             patch.object(replicate, "get_provider_client", return_value=object()), \
             patch.object(replicate, "check_connectivity", new=AsyncMock(side_effect=ReplicaProviderError("connect_failed", "offline"))) as probe:
            await replicate.start_replica_connectivity()
            probe.assert_awaited_once()
            self.assertIsNotNone(replicate.connectivity_monitor)
            await replicate.shutdown_replica()
            self.assertIsNone(replicate.connectivity_monitor)

    async def test_success_and_image_roles(self):
        def handler(request):
            self.assertEqual(str(request.url), ENDPOINT)
            body = json.loads(request.content)
            self.assertEqual(body["size"], "120x160")
            self.assertEqual(len(body["image"]), 2)
            self.assertEqual(body["sequential_image_generation"], "disabled")
            self.assertEqual(body["response_format"], "b64_json")
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]})
        metadata = await self.generate(handler)
        self.assertEqual(metadata["quality_status"], "pending_review")
        self.assertEqual(len(metadata["sha256"]), 64)
        self.assertGreater(metadata["bytes"], 0)

    async def test_connect_failures_retry_before_submission_only(self):
        calls = []
        def handler(request):
            calls.append(request)
            if len(calls) < 3:
                raise httpx.ConnectError("offline", request=request)
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]})
        with patch("backend.app.providers.replicate.backoff", new=AsyncMock()):
            metadata = await self.generate(handler)
        self.assertEqual(metadata["quality_status"], "pending_review")
        self.assertEqual(len(calls), 3)

    async def test_read_failure_is_uncertain_and_never_retried(self):
        calls = []
        def handler(request):
            calls.append(request)
            raise httpx.ReadError("response interrupted", request=request)
        with self.assertRaises(ReplicaProviderError) as error:
            await self.generate(handler)
        self.assertEqual(error.exception.code, "network_uncertain")
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(len(calls), 1)

    async def test_only_explicit_size_rejection_allows_one_fallback(self):
        calls = []
        def handler(request):
            body = json.loads(request.content)
            calls.append(body["size"])
            if len(calls) == 1:
                return httpx.Response(400, json={"error": {"code": "InvalidParameter", "message": "image size must be at least 3686400 pixels"}})
            width, height = map(int, body["size"].split("x"))
            self.assertEqual(width * 160, height * 120)
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(image_bytes((width, height))).decode()}]})
        result = await self.generate(handler)
        self.assertEqual(len(calls), 2)
        self.assertIn("endpoint_rejection", result["size_evidence"])
        with Image.open(self.root / "output.png") as image:
            self.assertEqual(image.size, (120, 160))

    async def test_auth_rate_limit_server_error_and_timeout_never_retry(self):
        for status, code in [(401, "authentication"), (403, "authentication"), (429, "rate_limited"), (503, "provider_unavailable"), (400, "invalid_parameters")]:
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(status, json={"error": {"message": "SECRET-DO-NOT-ECHO"}})
            with self.subTest(status=status), self.assertRaises(ReplicaProviderError) as error:
                await self.generate(handler)
            self.assertEqual(error.exception.code, code)
            self.assertNotIn("SECRET", str(error.exception))
            self.assertEqual(len(calls), 1)
        calls = []
        def timeout(request):
            calls.append(request)
            raise httpx.ReadTimeout("contains secret", request=request)
        with self.assertRaises(ReplicaProviderError) as error:
            await self.generate(timeout)
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(len(calls), 1)

    async def test_private_download_url_rejected_without_get(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"data": [{"url": "http://127.0.0.1:8000/private"}]})
        with self.assertRaises(ReplicaProviderError) as error:
            await self.generate(handler)
        self.assertEqual(error.exception.code, "unsafe_result_url")
        self.assertEqual(len(calls), 1)

    async def test_provider_cdn_result_url_does_not_depend_on_local_dns_classification(self):
        calls = []

        def handler(request):
            calls.append(request)
            if request.method == "POST":
                return httpx.Response(200, json={"data": [{"url": "https://result.tos-cn-beijing.volces.com/generated.png"}]})
            self.assertEqual(str(request.url), "https://result.tos-cn-beijing.volces.com/generated.png")
            return httpx.Response(200, content=image_bytes())

        with patch("backend.app.providers.replicate.socket.getaddrinfo", side_effect=AssertionError("trusted provider CDN must not require local DNS validation")):
            metadata = await self.generate(handler)

        self.assertEqual(metadata["quality_status"], "pending_review")
        self.assertEqual(len(calls), 2)

    async def test_untrusted_https_result_url_still_requires_public_dns(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"data": [{"url": "https://untrusted.example/generated.png"}]})

        with patch("backend.app.providers.replicate.socket.getaddrinfo", side_effect=OSError("DNS unavailable")):
            with self.assertRaises(ReplicaProviderError) as error:
                await self.generate(handler)

        self.assertEqual(error.exception.code, "unsafe_result_url")
        self.assertEqual(len(calls), 1)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        root = Path(self.folder.name)
        self.patches = [patch.object(database, "DB_PATH", root / "db.sqlite3"), patch.object(database, "DATA_DIR", root), patch.object(database, "UPLOAD_DIR", root / "uploads"), patch.object(database, "RESULT_DIR", root / "results"), patch.object(replicate, "UPLOAD_DIR", root / "uploads"), patch.object(replicate, "RESULT_DIR", root / "results"), patch.dict(os.environ, {"ARK_API_KEY": "test-key-no-network-allowed", "ARK_IMAGE_ENDPOINT": ENDPOINT, "REPLICA_DISABLE_MONITOR": "1"})]
        for item in self.patches:
            item.start()
        database.initialize()
        replicate.initialize_replica()
        app = FastAPI()
        app.include_router(replicate.router)
        app.add_middleware(ReplicaGuard)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1234)), base_url="http://test")
        self.scheduled = []
        self.schedule = patch.object(replicate, "schedule", side_effect=self.scheduled.append)
        self.schedule.start()
        # Any accidental use of real outbound HTTP in these API tests fails immediately.
        self.network = patch("backend.app.providers.replicate.ReplicaProvider.generate", side_effect=AssertionError("Real network prohibited"))
        self.network.start()
        self.connectivity = patch("backend.app.replicate.check_connectivity", new=AsyncMock(return_value={"connected": True}))
        self.connectivity.start()

    async def asyncTearDown(self):
        self.connectivity.stop()
        self.network.stop()
        self.schedule.stop()
        await replicate.shutdown_replica()
        await self.client.aclose()
        for item in reversed(self.patches):
            item.stop()
        self.folder.cleanup()

    async def create(self, key=None, files=None, data=None):
        return await self.client.post("/api/replicate/jobs", headers={"Idempotency-Key": key or str(uuid4())}, files=files or [("main_image", ("main.png", image_bytes(), "image/png")), ("reference_image", ("ref.png", image_bytes(), "image/png"))], data=data or {"remove_text": "true", "confirmed_width": "120", "confirmed_height": "160"})

    async def test_single_reference_and_no_mock_on_missing_key(self):
        response = await self.create(files=[("main_image", ("main.png", image_bytes(), "image/png")), ("reference_image", ("ref.png", image_bytes(), "image/png")), ("reference_image", ("ref2.png", image_bytes(), "image/png"))])
        self.assertEqual(response.status_code, 422)
        with patch.dict(os.environ, {"ARK_API_KEY": ""}):
            self.assertEqual((await self.create()).status_code, 503)
        self.assertEqual(self.scheduled, [])

    async def test_idempotency_and_active_deduplication(self):
        key = str(uuid4())
        first = await self.create(key)
        self.assertEqual(first.status_code, 202, first.text)
        second = await self.create(key)
        self.assertEqual(second.json()["id"], first.json()["id"])
        conflict = await self.create()
        self.assertEqual(conflict.status_code, 409)
        changed = await self.create(key, data={"remove_text": "false", "confirmed_width": "120", "confirmed_height": "160"})
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(len(self.scheduled), 1)
        self.assertNotIn("main_path", first.json())
        self.assertNotIn("test-key", first.text)

    async def test_idempotent_replay_does_not_require_provider_connectivity(self):
        key = str(uuid4())
        first = await self.create(key)
        outage = ReplicaProviderError("connect_failed", "provider offline", retryable=True, phase="connecting")
        with patch.object(replicate, "check_connectivity", new=AsyncMock(side_effect=outage)) as probe:
            replay = await self.create(key)
        self.assertEqual(replay.status_code, 202, replay.text)
        self.assertEqual(replay.json()["id"], first.json()["id"])
        probe.assert_not_awaited()

    async def test_preflight_dimensions_upload_validation_and_origin_guard(self):
        response = await self.client.post("/api/replicate/prepare", json={"reference_width": 120, "reference_height": 160, "custom_notes": "输出尺寸：800×1200 px"})
        self.assertEqual(response.json()["target_width"], 800)
        self.assertEqual((await self.create(data={"confirmed_width": "121", "confirmed_height": "160"})).status_code, 422)
        invalid = [("main_image", ("bad.png", b"bad", "image/png")), ("reference_image", ("ref.png", image_bytes(), "image/png"))]
        self.assertEqual((await self.create(files=invalid)).status_code, 422)
        invalid[0] = ("main_image", ("huge.png", b"a" * (20 * 1024 * 1024 + 1), "image/png"))
        self.assertEqual((await self.create(files=invalid)).status_code, 413)
        response = await self.client.post("/api/replicate/prepare", headers={"Origin": "https://untrusted.example"}, json={"reference_width": 120, "reference_height": 160})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.scheduled, [])

    async def test_restart_and_retry_with_deduplicated_charge_confirmation(self):
        original = (await self.create()).json()
        with database.connect() as db:
            db.execute("UPDATE replica_jobs SET status='submitting',phase='submitting' WHERE id=?", (original["id"],))
        replicate.initialize_replica()
        interrupted = (await self.client.get("/api/replicate/jobs/" + original["id"])).json()
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertTrue(interrupted["uncertain"])
        key = str(uuid4())
        url = "/api/replicate/jobs/" + original["id"] + "/retry"
        self.assertEqual((await self.client.post(url, headers={"Idempotency-Key": key}, json={})).status_code, 422)
        response = await self.client.post(url, headers={"Idempotency-Key": key}, json={"confirm_possible_charge": True})
        self.assertEqual(response.status_code, 202, response.text)
        again = await self.client.post(url, headers={"Idempotency-Key": key}, json={"confirm_possible_charge": True})
        self.assertEqual(again.json()["id"], response.json()["id"])
        self.assertEqual(response.json()["parent_id"], original["id"])
        self.assertEqual(len(self.scheduled), 2)

    async def test_restart_reschedules_only_never_submitted_jobs(self):
        original = (await self.create()).json()
        self.assertEqual(original["phase"], "queued")
        replicate.initialize_replica()
        recovered = (await self.client.get("/api/replicate/jobs/" + original["id"])).json()
        self.assertEqual(recovered["status"], "queued")
        self.assertFalse(recovered["uncertain"])
        self.assertEqual(self.scheduled, [original["id"], original["id"]])

    async def test_safe_connection_failure_can_retry_without_charge_confirmation(self):
        original = (await self.create()).json()
        with database.connect() as db:
            db.execute("UPDATE replica_jobs SET status='failed',phase='connecting',error_code='connect_failed',error='offline',uncertain=0,retryable=1 WHERE id=?", (original["id"],))
        response = await self.client.post("/api/replicate/jobs/" + original["id"] + "/retry", headers={"Idempotency-Key": str(uuid4())}, json={})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["phase"], "queued")

    async def test_mock_transport_full_job_lifecycle_and_download(self):
        row = (await self.create()).json()
        self.network.stop()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(image_bytes()).decode()}]}))) as provider_client:
            with patch.object(replicate, "ReplicaProvider", return_value=ReplicaProvider(provider_client)):
                await replicate.process(row["id"])
        self.network.start()
        completed = (await self.client.get("/api/replicate/jobs/" + row["id"])).json()
        self.assertEqual(completed["status"], "completed", completed)
        self.assertEqual(completed["quality_status"], "pending_review")
        response = await self.client.get(completed["download_url"])
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["content-disposition"])
        with Image.open(io.BytesIO(response.content)) as image:
            self.assertEqual(image.size, (120, 160))
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)

    async def test_provider_failures_persist_without_success_or_resubmission(self):
        for status, code in [(401, "authentication"), (429, "rate_limited"), (503, "provider_unavailable")]:
            row = (await self.create()).json()
            self.network.stop()
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(status, json={"error": {"message": "secret must not leak"}}))) as client:
                with patch.object(replicate, "ReplicaProvider", return_value=ReplicaProvider(client)):
                    await replicate.process(row["id"])
            self.network.start()
            result = (await self.client.get("/api/replicate/jobs/" + row["id"])).json()
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["error_code"], code)
            self.assertIsNone(result["preview_url"])
            self.assertNotIn("secret", json.dumps(result))
            self.assertEqual((await self.client.get("/api/replicate/jobs/" + row["id"] + "/result")).status_code, 409)

    async def test_exif_confirmed_dimensions_and_extras(self):
        files = [("main_image", ("main.png", image_bytes(), "image/png")), ("extra_images", ("extra1.png", image_bytes(), "image/png")), ("extra_images", ("extra2.png", image_bytes(), "image/png")), ("reference_image", ("ref.jpg", image_bytes(exif=True), "image/jpeg"))]
        response = await self.create(files=files, data={"confirmed_width": "160", "confirmed_height": "120", "remove_text": "false"})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["reference_width"], 160)
        self.assertFalse(response.json()["remove_text"])
        self.assertEqual(len(json.loads(replicate.row_for(response.json()["id"])["extra_paths"])), 2)


if __name__ == "__main__":
    unittest.main()
