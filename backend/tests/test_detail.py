import asyncio
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4
import zipfile

import httpx
from fastapi import FastAPI
from PIL import Image

from backend.app import database, detail
from backend.app.detail_models import PlanDocument, InputParams
from backend.app.providers.detail import plan_configuration, provider_error_summary, render_prompt
from backend.app.providers.replicate import ReplicaProviderError
from backend.app.replicate_guard import ReplicaGuard


class ProviderErrorTests(unittest.TestCase):
    def test_only_exposes_structured_error_fields(self):
        raw = json.dumps({"error": {"code": "NotFound", "message": "model missing"}, "secret": "hidden"}).encode()
        self.assertEqual(provider_error_summary(raw), "；供应商：NotFound / model missing")
        self.assertEqual(provider_error_summary(b"not-json"), "")


class DetailTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = TemporaryDirectory()
        directory = Path(self.temp.name)
        self.patches = [patch.object(database, name, value) for name, value in {
            "DATA_DIR": directory, "UPLOAD_DIR": directory / "uploads", "RESULT_DIR": directory / "results", "DB_PATH": directory / "test.sqlite3"}.items()]
        self.patches += [patch.object(detail, "FILES", directory / "detail"), patch.object(detail, "render_slots", asyncio.Semaphore(2))]
        for p in self.patches:
            p.start()
        detail.initialize_detail()
        app = FastAPI()
        app.include_router(detail.router)
        app.add_middleware(ReplicaGuard)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 1234)), base_url="http://test")
        self.input = {"productName": "全棉床品", "fabric": "", "craftsmanship": "", "specifications": "", "sellingPoints": "", "notes": "", "language": "zh-CN", "imageCount": 2, "aspectRatio": "9:16", "resolution": "1K"}
        self.calls = []

    async def asyncTearDown(self):
        await detail.shutdown_detail()
        await self.client.aclose()
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    async def asset(self):
        buffer = io.BytesIO()
        Image.new("RGB", (32, 32), "blue").save(buffer, "PNG")
        identifier = str(uuid4())
        response = await self.client.post("/api/detail/assets", headers={"Idempotency-Key": identifier}, data={"clientId": identifier}, files={"file": ("input.png", buffer.getvalue(), "image/png")})
        self.assertEqual(response.status_code, 200, response.text)
        return {"id": identifier, "assetId": response.json()["assetId"], "role": "main"}

    async def fake_plan(self, input, assets, plan_id):
        self.calls.append("plan")
        return PlanDocument(planId=plan_id, revision=1, input=input, items=[{
            "id": f"card_{index}", "order": index + 1, "theme": f"主题{index}", "visualDescription": "产品特写", "stylePrompt": "自然柔光", "textOverlay": {"headline": "产品字样", "body": "说明", "placement": "bottom"}, "sourceImageIds": [assets[0][0]]
        } for index in range(input.imageCount)])

    async def fake_render(self, plan, item, paths, output):
        self.calls.append((item.order, item.textOverlay.headline, item.visualDescription))
        await asyncio.sleep(.01 if item.order == 1 else 0)
        Image.new("RGB", (18, 32), "blue").save(output, "PNG")
        return (18, 32)

    async def planned(self):
        asset = await self.asset()
        key = str(uuid4())
        with patch.object(detail, "plan_configuration", return_value=("key", "url", "model")), patch.object(detail, "generate_plan", side_effect=self.fake_plan):
            response = await self.client.post("/api/detail/plans", headers={"Idempotency-Key": key}, json={"input": self.input, "assets": [asset]})
        self.assertEqual(response.status_code, 200, response.text)
        return asset, response.json()

    async def test_confirmed_edits_order_and_export_and_no_render_before_confirm(self):
        asset, plan = await self.planned()
        self.assertEqual(self.calls, ["plan"])
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM detail_records WHERE kind='task'").fetchone()[0], 0)
        plan["items"].reverse()
        for index, item in enumerate(plan["items"]):
            item["order"] = index + 1
        plan["items"][0]["textOverlay"]["headline"] = "用户修改后的字样"
        plan["items"][0]["visualDescription"] = "用户指定展示面料细节"
        plan["revision"] = 2
        identifier = str(uuid4())
        body = {"taskId": identifier, "input": self.input, "assets": [asset], "plan": plan}
        with patch.object(detail, "current_configuration", return_value=("key", "url", "model")), patch.object(detail, "render_item", side_effect=self.fake_render):
            response = await self.client.post("/api/detail/tasks", headers={"Idempotency-Key": identifier}, json=body)
            self.assertEqual(response.status_code, 202, response.text)
            await asyncio.gather(*list(detail.jobs.values()))
            repeated = await self.client.post("/api/detail/tasks", headers={"Idempotency-Key": identifier}, json=body)
            self.assertEqual(repeated.status_code, 202)
        self.assertEqual(len(self.calls), 3)
        self.assertIn((1, "用户修改后的字样", "用户指定展示面料细节"), self.calls)
        task = (await self.client.get(f"/api/detail/tasks/{identifier}")).json()
        self.assertEqual(task["status"], "completed")
        self.assertEqual([item["planItemId"] for item in task["items"]], ["card_1", "card_0"])
        export = await self.client.get(task["exportUrl"])
        with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
            self.assertEqual(archive.namelist(), ["confirmed-plan.json", "task-status.json", "01.png", "02.png"])
            saved = json.loads(archive.read("confirmed-plan.json"))
            self.assertEqual(saved["items"][0]["textOverlay"]["headline"], "用户修改后的字样")
        body["plan"]["items"][0]["theme"] = "changed"
        conflict = await self.client.post("/api/detail/tasks", headers={"Idempotency-Key": identifier}, json=body)
        self.assertEqual(conflict.status_code, 409)

    async def test_missing_planner_is_explicit_and_creates_no_task(self):
        asset = await self.asset()
        with patch.dict(os.environ, {"DETAIL_PLAN_ENDPOINT": "", "DETAIL_PLAN_MODEL": "", "DETAIL_PLAN_API_KEY": ""}):
            response = await self.client.post("/api/detail/plans", headers={"Idempotency-Key": str(uuid4())}, json={"input": self.input, "assets": [asset]})
        self.assertEqual(response.status_code, 503)
        self.assertIn("DETAIL_PLAN_MODEL", response.json()["detail"]["message"])
        self.assertFalse(response.json()["detail"]["uncertain"])

    async def test_unknown_plan_stale_input_invalid_order_and_unknown_sources_rejected(self):
        asset, plan = await self.planned()
        for mutation, status in [("planId", 422), ("productName", 422), ("sourceImageIds", 422), ("order", 422)]:
            body = {"taskId": str(uuid4()), "input": dict(self.input), "assets": [asset], "plan": json.loads(json.dumps(plan))}
            if mutation == "planId":
                body["plan"]["planId"] = "unknown"
            elif mutation == "productName":
                body["plan"]["input"][mutation] = "different"
                body["input"][mutation] = "different"
            elif mutation == "sourceImageIds":
                body["plan"]["items"][0][mutation] = ["not_uploaded"]
            else:
                body["plan"]["items"][0][mutation] = 2
            response = await self.client.post("/api/detail/tasks", headers={"Idempotency-Key": body["taskId"]}, json=body)
            self.assertEqual(response.status_code, status, response.text)

    async def test_plan_idempotency_avoids_duplicate_provider_calls(self):
        asset, plan = await self.planned()
        with patch.object(detail, "generate_plan") as provider:
            response = await self.client.post("/api/detail/plans", headers={"Idempotency-Key": plan["planId"]}, json={"input": self.input, "assets": [asset]})
            self.assertEqual(response.status_code, 200)
            provider.assert_not_called()

    async def test_partial_failure_preserves_success_without_retries(self):
        asset, plan = await self.planned()
        async def fail_one(plan, item, paths, output):
            if item.order == 1:
                raise ReplicaProviderError("timeout", "结果不确定，请核查供应商记录", True)
            return await self.fake_render(plan, item, paths, output)
        identifier = str(uuid4())
        with patch.object(detail, "current_configuration"), patch.object(detail, "render_item", side_effect=fail_one) as provider:
            await self.client.post("/api/detail/tasks", headers={"Idempotency-Key": identifier}, json={"taskId": identifier, "plan": plan, "input": self.input, "assets": [asset]})
            await asyncio.gather(*list(detail.jobs.values()))
            self.assertEqual(provider.call_count, 2)
        task = (await self.client.get(f"/api/detail/tasks/{identifier}")).json()
        self.assertEqual(task["status"], "partial")
        self.assertFalse(task["items"][0]["error"]["retryable"])
        self.assertEqual((await self.client.get(task["items"][1]["previewUrl"])).status_code, 200)

    async def test_restart_does_not_replay_uncertain_jobs(self):
        detail.save("task", "pending", "hash", {"status": "running", "items": [{"planItemId": "one", "status": "rendering"}]})
        detail.save("plan", "pending_plan", "hash", {"state": "running"})
        detail.initialize_detail()
        self.assertEqual(detail.read("task", "pending")["data"]["status"], "failed")
        self.assertTrue(detail.read("plan", "pending_plan")["data"]["uncertain"])
        self.assertFalse(detail.jobs)

    async def test_foreign_origin_and_corrupt_upload_rejected(self):
        response = await self.client.get("/api/detail/plans/any", headers={"Origin": "https://attacker.example"})
        self.assertEqual(response.status_code, 403)
        response = await self.client.post("/api/detail/assets", headers={"Idempotency-Key": "asset"}, data={"clientId": "asset"}, files={"file": ("fake.png", b"bad", "image/png")})
        self.assertEqual(response.status_code, 422)

    async def test_render_prompt_uses_confirmed_overlay_and_not_replica_instructions(self):
        _, data = await self.planned()
        plan = PlanDocument.model_validate(data)
        plan.items[0].textOverlay.headline = "手动编辑的中文标题"
        prompt = render_prompt(plan, plan.items[0])
        self.assertIn("手动编辑的中文标题", prompt)
        self.assertIn("产品特写", prompt)
        self.assertNotIn("唯一场景参考图", prompt)

    def test_planner_never_borrows_image_key(self):
        with patch.dict(os.environ, {"ARK_API_KEY": "image-key", "DETAIL_PLAN_ENDPOINT": "https://example.com/chat", "DETAIL_PLAN_MODEL": "vision", "DETAIL_PLAN_API_KEY": ""}):
            with self.assertRaises(ReplicaProviderError):
                plan_configuration()


if __name__ == "__main__":
    unittest.main()
