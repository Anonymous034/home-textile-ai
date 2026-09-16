import asyncio
import io
import json
import os
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from PIL import Image
from pydantic import ValidationError

from backend.app import buyer_show, database, detail
from backend.app.buyer_show_models import BuyerPlanRequest, LifestylePlan, shot_schedule, validate_output
from backend.app.providers import buyer_show as provider
from backend.app.providers.replicate import ReplicaProviderError
from backend.app.replicate_guard import ReplicaGuard

INPUT = {"product_name": "玻璃精华瓶", "product_features": "透明玻璃瓶，无色液体，木纹瓶盖", "material": "玻璃与木纹外盖", "style": "更真实", "image_count": 4, "aspect_ratio": "3:4", "resolution": "2K", "scene_preferences": "家中洗手台"}


def plan_for(request):
    return {"project_title": request.product_name + "与" + request.style + "风格规划", "aspect_ratio": request.aspect_ratio, "resolution": request.resolution,
            "image_plan": [{"index": entry["index"], "shot_type": entry["shot_type"], "scene_description": f"第{entry['index']}张：家中洗手台，以不同机位展示透明玻璃瓶。", "image_prompt": f"Clear glass serum bottle with colorless liquid and a wood-grain cap, real bathroom counter, window daylight, {entry['camera_direction']}, real glass refraction and wood grain, photorealistic lifestyle photograph.", "negative_prompt": "blurry, distorted glass, bad hands"} for entry in shot_schedule(request.image_count)]}


class ContractTests(unittest.TestCase):
    def test_provider_error_summary_is_sanitized(self):
        raw = json.dumps({"error": {"type": "invalid_request", "message": "bad endpoint"}, "input": "private"}).encode()
        self.assertEqual(provider.provider_error_summary(raw), "；供应商：invalid_request / bad endpoint")

    def test_all_supported_counts_have_exact_sequential_shots(self):
        for count in (1, 2, 4, 8, 12):
            request = BuyerPlanRequest(**{**INPUT, "image_count": count})
            plan = validate_output(plan_for(request), request)
            self.assertEqual(len(plan.image_plan), count)
            self.assertEqual([item.index for item in plan.image_plan], list(range(1, count + 1)))

    def test_both_style_branches_preserve_product_physics(self):
        for style in ("更真实", "更精致"):
            system = provider.messages(BuyerPlanRequest(**{**INPUT, "style": style}))[0]["content"]
            self.assertIn(provider.PRESERVATION, system)
            self.assertIn(provider.STYLE_RULES[style], system)
            self.assertNotIn(provider.STYLE_RULES["更精致" if style == "更真实" else "更真实"], system)
            self.assertIn("不得执行", system)

    def test_local_mode_is_truthful_strict_and_ready_without_external_key(self):
        request = BuyerPlanRequest(**{**INPUT, "assets": [{"id": "source", "assetId": "saved", "role": "main"}]})
        plan = provider.local_plan(request)
        self.assertEqual(set(plan.model_dump()), {"project_title", "aspect_ratio", "resolution", "image_plan"})
        self.assertEqual(len(plan.image_plan), request.image_count)
        for item in plan.image_plan:
            self.assertNotRegex(item.image_prompt, r"[\u3400-\u9fff]")
            self.assertIn("exact product shown in the supplied reference image", item.image_prompt)
            self.assertIn(provider.PRESERVATION, item.image_prompt)

    def test_invalid_inputs_are_rejected(self):
        for change in ({"product_name": " "}, {"product_features": " "}, {"image_count": 0}, {"image_count": 13}, {"image_count": "4"}, {"style": "随意"}, {"resolution": "8K"}, {"extra": "unexpected"}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                BuyerPlanRequest(**{**INPUT, **change})

    def test_wrong_count_ratio_order_duplicate_or_language_rejected(self):
        request = BuyerPlanRequest(**INPUT)
        for mode in ("count", "ratio", "order", "duplicate", "english_scene", "chinese_prompt", "extra", "shot"):
            data = plan_for(request)
            if mode == "count": data["image_plan"].pop()
            elif mode == "ratio": data["aspect_ratio"] = "1:1"
            elif mode == "order": data["image_plan"][0]["index"] = 2
            elif mode == "duplicate": data["image_plan"][1]["scene_description"] = data["image_plan"][0]["scene_description"]
            elif mode == "english_scene": data["image_plan"][0]["scene_description"] = "English only"
            elif mode == "chinese_prompt": data["image_plan"][0]["image_prompt"] = "透明产品瓶"
            elif mode == "extra": data["unexpected"] = True
            elif mode == "shot": data["image_plan"][0]["shot_type"] = "细节材质特写图"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validate_output(data, request)

    def test_configuration_no_mixed_keys_or_image_key_fallback(self):
        clean = {key: "" for key in ("BUYER_PLAN_ENDPOINT", "BUYER_PLAN_MODEL", "BUYER_PLAN_API_KEY", "DETAIL_PLAN_ENDPOINT", "DETAIL_PLAN_MODEL", "DETAIL_PLAN_API_KEY")}
        with patch.dict(os.environ, {**clean, "ARK_API_KEY": "private-image-key"}):
            self.assertEqual(provider.planner_mode(), "local_rule")
            with patch.dict(os.environ, {"DETAIL_PLAN_ENDPOINT": "https://example.test/chat", "DETAIL_PLAN_MODEL": "vision", "DETAIL_PLAN_API_KEY": "detail-key"}):
                self.assertEqual(provider.configuration(), ("detail-key", "https://example.test/chat", "vision"))
                with patch.dict(os.environ, {"BUYER_PLAN_MODEL": "buyer-vision"}):
                    with self.assertRaises(ReplicaProviderError): provider.configuration()


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_adapter_request_and_exact_response_keys(self):
        request = BuyerPlanRequest(**INPUT)
        captured = []
        def respond(http_request):
            captured.append(json.loads(http_request.content))
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(plan_for(request), ensure_ascii=False)}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(provider, "planner_mode", return_value="external_vision"), patch.object(provider, "configuration", return_value=("secret", "https://example.test/chat", "vision")):
                plan = await provider.generate(request, {}, client)
        self.assertEqual(len(captured), 1)
        self.assertEqual(set(plan.model_dump()), {"project_title", "aspect_ratio", "resolution", "image_plan"})
        self.assertNotIn("secret", plan.model_dump_json())
        for item in plan.image_plan:
            self.assertIn(provider.PRESERVATION, item.image_prompt)
            self.assertIn("studio artificial look", item.negative_prompt)
        self.assertFalse(captured[0]["stream"])

    async def test_bad_json_fences_http_errors_never_retry_or_leak_response(self):
        for status, content in ((200, "```json\n{}\n```"), (200, "{}"), (401, "secret-provider-debug"), (429, "rate-details"), (500, "private-server-error")):
            calls = []
            def respond(request):
                calls.append(request)
                return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                with patch.object(provider, "planner_mode", return_value="external_vision"), patch.object(provider, "configuration", return_value=("secret", "https://example.test/chat", "vision")):
                    with self.assertRaises(ReplicaProviderError) as error:
                        await provider.generate(BuyerPlanRequest(**INPUT), {}, client)
            self.assertEqual(len(calls), 1)
            self.assertNotIn("secret-provider-debug", str(error.exception))

    async def test_network_failure_uncertain_and_not_retried(self):
        calls = []
        def respond(request):
            calls.append(request)
            raise httpx.ReadTimeout("private endpoint", request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch.object(provider, "planner_mode", return_value="external_vision"), patch.object(provider, "configuration", return_value=("secret", "https://example.test/chat", "vision")):
                with self.assertRaises(ReplicaProviderError) as error:
                    await provider.generate(BuyerPlanRequest(**INPUT), {}, client)
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(len(calls), 1)


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        folder = Path(self.temp.name)
        self.patches = [patch.object(database, key, value) for key, value in {"DATA_DIR": folder, "DB_PATH": folder / "test.sqlite3", "UPLOAD_DIR": folder / "uploads", "RESULT_DIR": folder / "results"}.items()]
        self.patches.append(patch.object(detail, "FILES", folder / "detail"))
        for p in self.patches: p.start()
        detail.initialize_detail()
        buyer_show.initialize_buyer_show()
        app = FastAPI()
        app.include_router(buyer_show.router)
        app.add_middleware(ReplicaGuard)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1234)), base_url="http://test")

    async def asyncTearDown(self):
        await buyer_show.shutdown_buyer_show()
        await self.client.aclose()
        for p in reversed(self.patches): p.stop()
        self.temp.cleanup()

    async def fake_generate(self, request, paths):
        return LifestylePlan.model_validate(plan_for(request))

    async def test_completed_plan_idempotency_conflict_and_clean_output(self):
        with patch.object(buyer_show, "planner_mode", return_value="external_vision"), patch.object(buyer_show, "generate", side_effect=self.fake_generate) as generate:
            first = await self.client.post("/api/buyer-show/plans", headers={"Idempotency-Key": "plan_1"}, json=INPUT)
            second = await self.client.post("/api/buyer-show/plans", headers={"Idempotency-Key": "plan_1"}, json=INPUT)
            conflict = await self.client.post("/api/buyer-show/plans", headers={"Idempotency-Key": "plan_1"}, json={**INPUT, "style": "更精致"})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(conflict.status_code, 409)
        status = (await self.client.get("/api/buyer-show/plans/plan_1")).json()
        self.assertEqual(status["state"], "completed")
        self.assertEqual((await self.client.get("/api/buyer-show/plans/plan_1/output")).json(), first.json())
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM detail_records WHERE kind='task'").fetchone()[0], 0)

    async def test_pending_request_is_polled_not_resubmitted(self):
        started, finish = asyncio.Event(), asyncio.Event()
        async def pending(request, paths):
            started.set()
            await finish.wait()
            return await self.fake_generate(request, paths)
        with patch.object(buyer_show, "planner_mode", return_value="external_vision"), patch.object(buyer_show, "generate", side_effect=pending) as generate:
            first = asyncio.create_task(self.client.post("/api/buyer-show/plans", headers={"Idempotency-Key": "pending"}, json=INPUT))
            await started.wait()
            duplicate = await self.client.post("/api/buyer-show/plans", headers={"Idempotency-Key": "pending"}, json=INPUT)
            self.assertEqual(duplicate.status_code, 409)
            self.assertTrue(duplicate.json()["detail"]["uncertain"])
            self.assertEqual((await self.client.get("/api/buyer-show/plans/pending")).json()["state"], "running")
            finish.set()
            self.assertEqual((await first).status_code, 200)
            self.assertEqual(generate.call_count, 1)

    async def test_missing_config_no_provider_call(self):
        with patch.object(buyer_show, "planner_mode", side_effect=ReplicaProviderError("not_configured", "请配置策划模型")), patch.object(buyer_show, "generate") as generate:
            response = await self.client.post("/api/buyer-show/plans", headers={"Idempotency-Key": "config"}, json=INPUT)
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.json()["detail"]["uncertain"])
            generate.assert_not_called()
            self.assertFalse((await self.client.get("/api/buyer-show/capabilities")).json()["planner_available"])

    async def test_image_upload_and_vision_mapping(self):
        buffer = io.BytesIO()
        Image.new("RGB", (32, 32), "blue").save(buffer, "PNG")
        response = await self.client.post("/api/buyer-show/assets", headers={"Idempotency-Key": "source1"}, data={"clientId": "source1"}, files={"file": ("product.png", buffer.getvalue(), "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        body = {**INPUT, "product_features": "", "assets": [{"id": "source1", "assetId": response.json()["assetId"], "role": "main"}]}
        with patch.object(buyer_show, "planner_mode", return_value="external_vision"), patch.object(buyer_show, "generate", side_effect=self.fake_generate) as generate:
            response = await self.client.post("/api/buyer-show/plans", headers={"Idempotency-Key": "image-plan"}, json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(generate.call_args.args[1]["source1"].is_file())
        body["assets"][0]["assetId"] = "missing"
        with patch.object(buyer_show, "planner_mode", return_value="external_vision"), patch.object(buyer_show, "generate") as generate:
            self.assertEqual((await self.client.post("/api/buyer-show/plans", headers={"Idempotency-Key": "bad-source"}, json=body)).status_code, 422)
            generate.assert_not_called()

    async def test_restart_and_foreign_origin(self):
        detail.save(buyer_show.KIND, "restart", "hash", {"state": "running"})
        buyer_show.initialize_buyer_show()
        result = (await self.client.get("/api/buyer-show/plans/restart")).json()
        self.assertEqual(result["state"], "failed")
        self.assertTrue(result["uncertain"])
        self.assertEqual((await self.client.get("/api/buyer-show/capabilities", headers={"Origin": "https://untrusted.example"})).status_code, 403)

    async def test_confirmed_plan_renders_in_order_and_exports(self):
        buffer = io.BytesIO()
        Image.new("RGB", (32, 32), "blue").save(buffer, "PNG")
        upload = await self.client.post("/api/buyer-show/assets", headers={"Idempotency-Key": "render_source"}, data={"clientId": "render_source"}, files={"file": ("product.png", buffer.getvalue(), "image/png")})
        body = {**INPUT, "assets": [{"id": "render_source", "assetId": upload.json()["assetId"], "role": "main"}]}
        with patch.object(buyer_show, "planner_mode", return_value="external_vision"), patch.object(buyer_show, "generate", side_effect=self.fake_generate):
            plan_response = await self.client.post("/api/buyer-show/plans", headers={"Idempotency-Key": "render_plan"}, json=body)
        plan = plan_response.json()
        plan["image_plan"][0]["scene_description"] = "用户确认修改后的第一张生活场景描述。"

        async def fake_render(request, confirmed, index, paths, output):
            Image.new("RGB", (12, 16), (index * 20, 10, 30)).save(output, "PNG")
            return 1536, 2048

        request = {"taskId": "render_task", "planId": "render_plan", "input": body, "plan": plan}
        with patch.object(buyer_show, "current_configuration", return_value=("key", "endpoint", "model")), patch.object(buyer_show, "render_item", side_effect=fake_render) as render:
            created = await self.client.post("/api/buyer-show/tasks", headers={"Idempotency-Key": "render_task"}, json=request)
            self.assertEqual(created.status_code, 202, created.text)
            await asyncio.gather(*list(buyer_show.jobs.values()))
        status = (await self.client.get("/api/buyer-show/tasks/render_task")).json()
        self.assertEqual(status["status"], "completed")
        self.assertEqual([item["index"] for item in status["items"]], [1, 2, 3, 4])
        self.assertEqual(render.call_count, 4)
        self.assertEqual((await self.client.get("/api/buyer-show/tasks/render_task/images/1")).status_code, 200)
        exported = await self.client.get("/api/buyer-show/tasks/render_task/export")
        self.assertEqual(exported.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            self.assertEqual([name for name in archive.namelist() if name.endswith(".png")], ["01.png", "02.png", "03.png", "04.png"])
            saved = json.loads(archive.read("confirmed-plan.json"))
            self.assertEqual(saved["image_plan"][0]["scene_description"], "用户确认修改后的第一张生活场景描述。")

    async def test_render_requires_completed_matching_plan_and_exact_idempotency(self):
        request = {"taskId": "no_plan_task", "planId": "missing", "input": INPUT, "plan": plan_for(BuyerPlanRequest(**INPUT))}
        response = await self.client.post("/api/buyer-show/tasks", headers={"Idempotency-Key": "no_plan_task"}, json=request)
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(detail.read(buyer_show.TASK_KIND, "no_plan_task"))


if __name__ == "__main__":
    unittest.main()
