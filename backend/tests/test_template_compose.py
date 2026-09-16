import unittest
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from PIL import Image
from pydantic import ValidationError

from backend.app import database, template_compose
from backend.app.template_compose import CompositionPlan


def image_bytes(color):
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, "PNG")
    return buffer.getvalue()


PLAN = {
    "prompt": "exact product structure, detailed textile, natural integration",
    "negative_prompt": "deformed product, missing logo, pasted edges",
    "composition_strategy": {
        "control_mode": "ip-adapter + controlnet_depth + inpainting",
        "denoising_strength": 0.55,
        "blend_mode": "seamless integration, match template lighting and shadows",
    },
}


class TemplateCompositionContractTests(unittest.TestCase):
    def test_valid_strategy_contract(self):
        plan = CompositionPlan.model_validate({
            "prompt": "exact product structure, detailed textile, natural integration",
            "negative_prompt": "deformed product, missing logo, pasted edges",
            "composition_strategy": {
                "control_mode": "ip-adapter + controlnet_depth + inpainting",
                "denoising_strength": 0.55,
                "blend_mode": "seamless integration, match template lighting and shadows",
            },
        })
        self.assertEqual(plan.composition_strategy.denoising_strength, 0.55)

    def test_strength_outside_safe_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            CompositionPlan.model_validate({
                "prompt": "exact product structure and detailed natural material",
                "negative_prompt": "deformation and inconsistent lighting",
                "composition_strategy": {"control_mode": "ip-adapter", "denoising_strength": 0.8, "blend_mode": "seamless integration"},
            })


class TemplateCompositionGenerationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        self.root = Path(self.folder.name)
        app = FastAPI()
        app.include_router(template_compose.router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.folder.cleanup()

    async def submit(self, template_field, colors):
        files = [("product_images", ("product.png", image_bytes("red"), "image/png"))]
        files += [(template_field, (f"reference-{index}.png", image_bytes(color), "image/png")) for index, color in enumerate(colors)]
        with patch.object(template_compose, "UPLOAD_DIR", self.root / "uploads"), patch.object(template_compose, "RESULT_DIR", self.root / "results"), \
             patch.object(template_compose, "probe_plan_connection", new=AsyncMock(return_value={"connected": True})), \
             patch.object(template_compose, "check_connectivity", new=AsyncMock(return_value={"connected": True})), \
             patch.object(template_compose, "create_plan", new=AsyncMock(return_value=CompositionPlan.model_validate(PLAN))) as planner, \
             patch.object(template_compose.ReplicaProvider, "generate", new=AsyncMock(return_value={"quality_status": "pending_review"})) as renderer:
            response = await self.client.post("/api/template-compose/generate", files=files)
            if response.status_code == 200:
                paths = renderer.await_args.args[0]
                self.assertEqual([path.read_bytes() for path in paths], [image_bytes("red"), *[image_bytes(color) for color in colors]])
                self.assertEqual(planner.await_args.args[2], paths[1:])
                return response, renderer.await_args.kwargs["prompt"]
            return response, None

    async def test_multiple_library_references_reach_planner_and_renderer_in_order(self):
        response, prompt = await self.submit("template_images", ["blue", "green", "yellow"])
        self.assertEqual(response.status_code, 200)
        self.assertIn("Reference images 2 through 4 are decorative templates", prompt)
        self.assertIn("Use every template", prompt)

    async def test_single_library_reference_and_legacy_uploaded_template(self):
        for field in ("template_images", "template_image"):
            with self.subTest(field=field):
                response, prompt = await self.submit(field, ["blue"])
                self.assertEqual(response.status_code, 200)
                self.assertIn("Reference images 2 through 2", prompt)

    async def test_library_ids_use_local_files_without_browser_reupload(self):
        ids = ["img_first", "img_second"]
        colors = ["blue", "green"]
        db_root = self.root / "db"
        db_root.mkdir()
        with patch.object(database, "DATA_DIR", db_root), patch.object(database, "DB_PATH", db_root / "studio.sqlite3"):
            with database.connect() as db:
                db.execute("CREATE TABLE template_images (id TEXT PRIMARY KEY, local_path TEXT NOT NULL)")
                for image_id, color in zip(ids, colors):
                    path = self.root / f"{image_id}.png"
                    path.write_bytes(image_bytes(color))
                    db.execute("INSERT INTO template_images(id,local_path) VALUES(?,?)", (image_id, str(path)))
            files = [("product_images", ("product.png", image_bytes("red"), "image/png"))]
            files += [("template_image_ids", (None, image_id)) for image_id in ids]
            with patch.object(template_compose, "UPLOAD_DIR", self.root / "uploads"), \
                 patch.object(template_compose, "RESULT_DIR", self.root / "results"), \
                 patch.object(template_compose, "probe_plan_connection", new=AsyncMock(return_value={"connected": True})), \
                 patch.object(template_compose, "check_connectivity", new=AsyncMock(return_value={"connected": True})), \
                 patch.object(template_compose, "create_plan", new=AsyncMock(return_value=CompositionPlan.model_validate(PLAN))) as planner, \
                 patch.object(template_compose.ReplicaProvider, "generate", new=AsyncMock(return_value={})) as renderer:
                response = await self.client.post("/api/template-compose/generate", files=files)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual([path.read_bytes() for path in renderer.await_args.args[0]], [image_bytes("red"), *[image_bytes(color) for color in colors]])
            self.assertEqual(planner.await_args.args[2], renderer.await_args.args[0][1:])

    async def test_missing_or_ambiguous_template_is_rejected(self):
        product = ("product.png", image_bytes("red"), "image/png")
        reference = ("reference.png", image_bytes("blue"), "image/png")
        for files in (
            [("product_images", product)],
            [("product_images", product), ("template_image", reference), ("template_images", reference)],
        ):
            response = await self.client.post("/api/template-compose/generate", files=files)
            self.assertEqual(response.status_code, 422)

    async def test_offline_planner_stops_before_billable_request(self):
        files = [
            ("product_images", ("product.png", image_bytes("red"), "image/png")),
            ("template_image", ("template.png", image_bytes("blue"), "image/png")),
        ]
        with patch.object(template_compose, "probe_plan_connection", new=AsyncMock(return_value={"connected": False, "message": "策划服务离线"})), \
             patch.object(template_compose, "create_plan", new=AsyncMock()) as planner:
            response = await self.client.post("/api/template-compose/generate", files=files)
        self.assertEqual(response.status_code, 503)
        planner.assert_not_awaited()

    async def test_planner_receives_every_template_on_both_api_formats(self):
        real_client = httpx.AsyncClient
        for endpoint in ("https://planner.test/responses", "https://planner.test/chat/completions"):
            with self.subTest(endpoint=endpoint):
                def respond(request):
                    body = json.loads(request.content)
                    content = body["input"][0]["content"] if endpoint.endswith("/responses") else body["messages"][1]["content"]
                    images = [item.get("image_url") for item in content if item["type"] == "input_image"] if endpoint.endswith("/responses") else [item["image_url"]["url"] for item in content if item["type"] == "image_url"]
                    self.assertEqual(images, ["product.png", "template-1.png", "template-2.png", "template-3.png"])
                    self.assertIn("Use every template", body.get("instructions", body.get("messages", [{}])[0].get("content", "")))
                    if endpoint.endswith("/responses"):
                        return httpx.Response(200, json={"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(PLAN)}]}]})
                    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(PLAN)}}]})

                def planner_client(*args, **kwargs):
                    return real_client(*args, transport=httpx.MockTransport(respond), **kwargs)

                with patch.object(template_compose, "plan_configuration", return_value=("test-key", endpoint, "test-model")), \
                     patch.object(template_compose, "reference_data", side_effect=lambda path: path.name), \
                     patch.object(template_compose.httpx, "AsyncClient", side_effect=planner_client):
                    plan = await template_compose.create_plan("keep warm", Path("product.png"), [Path(f"template-{i}.png") for i in range(1, 4)])
                self.assertEqual(plan.composition_strategy.denoising_strength, 0.55)


if __name__ == "__main__":
    unittest.main()
