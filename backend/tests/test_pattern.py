import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image
from starlette.datastructures import Headers, UploadFile

from backend.app import pattern
from backend.app.providers.replicate import ReplicaProviderError


def upload():
    data = io.BytesIO()
    Image.new("RGB", (128, 128), "beige").save(data, "PNG")
    data.seek(0)
    return UploadFile(file=data, filename="source.png", headers=Headers({"content-type": "image/png"}))


class PatternTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = TemporaryDirectory()
        root = Path(self.folder.name)
        self.patches = [
            patch.object(pattern, "UPLOAD_DIR", root / "uploads"),
            patch.object(pattern, "RESULT_DIR", root / "results"),
            patch.object(pattern, "current_configuration", return_value=("test-key", "endpoint", "model")),
        ]
        for item in self.patches:
            item.start()
        pattern.jobs.clear()
        pattern.running.clear()

    async def asyncTearDown(self):
        await pattern.shutdown_pattern()
        pattern.jobs.clear()
        pattern.running.clear()
        for item in reversed(self.patches):
            item.stop()
        self.folder.cleanup()

    async def test_generates_requested_variants_for_largest_visible_object(self):
        prompts = []

        class FakeProvider:
            async def generate(self, paths, target, remove_text, notes, output, stage, *, prompt):
                prompts.append(prompt)
                self_test.assertEqual(target, (128, 128))
                self_test.assertEqual(len(paths), 1)
                Image.new("RGB", target, "blue").save(output, "PNG")
                return {"quality_status": "pending_review"}

        self_test = self
        with patch.object(pattern, "ReplicaProvider", FakeProvider):
            created = await pattern.create_job(upload(), 2, "明显", "智能配色", "蓝色几何纹", "recolor", str(uuid4()))
            await pattern.running[created["id"]]
            replay = await pattern.create_job(upload(), 2, "明显", "智能配色", "蓝色几何纹", "recolor", created["id"])
        completed = pattern.job_status(created["id"])
        self.assertEqual(replay["id"], created["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["completed"], 2)
        self.assertEqual(len(completed["result_urls"]), 2)
        self.assertIn("largest visible area", prompts[0])
        self.assertIn("regardless of category", prompts[0])
        self.assertIn("Change the target item's colors", prompts[0])
        self.assertIn("蓝色几何纹", prompts[0])
        self.assertIn("variant 2 of 2", prompts[1])
        pattern.jobs.clear()
        self.assertEqual(pattern.job_status(created["id"])["completed"], 2)

    async def test_invalid_parameters_never_start_generation(self):
        with self.assertRaises(HTTPException) as error:
            await pattern.create_job(upload(), 3, "适度", "保持配色", "", "extract", str(uuid4()))
        self.assertEqual(error.exception.status_code, 422)
        self.assertFalse(pattern.running)

    async def test_design_extraction_returns_one_square_swatch_for_largest_object(self):
        calls = []

        class FakeProvider:
            async def generate(self, paths, target, remove_text, notes, output, stage, *, prompt):
                calls.append((target, prompt))
                Image.new("RGB", target, "beige").save(output, "PNG")
                return {}

        with patch.object(pattern, "ReplicaProvider", FakeProvider):
            created = await pattern.create_job(upload(), 1, "适度", "保持配色", "", "design_extract", str(uuid4()))
            await pattern.running[created["id"]]
        completed = pattern.job_status(created["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["completed"], 1)
        self.assertEqual(len(completed["result_urls"]), 1)
        self.assertEqual(calls[0][0], (1024, 1024))
        self.assertIn("largest visible area", calls[0][1])
        self.assertIn("regardless of category", calls[0][1])
        self.assertIn("without inventing a motif", calls[0][1])
        with self.assertRaises(HTTPException):
            await pattern.create_job(upload(), 2, "适度", "保持配色", "", "design_extract", str(uuid4()))

    async def test_provider_failure_preserves_completed_results_without_retrying(self):
        calls = 0

        class FailingProvider:
            async def generate(self, paths, target, remove_text, notes, output, stage, *, prompt):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise ReplicaProviderError("network_uncertain", "提交后连接中断", True)
                Image.new("RGB", target, "green").save(output, "PNG")
                return {}

        with patch.object(pattern, "ReplicaProvider", FailingProvider):
            created = await pattern.create_job(upload(), 4, "轻微", "保持配色", "", "extract", str(uuid4()))
            await pattern.running[created["id"]]
        failed = pattern.job_status(created["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["completed"], 1)
        self.assertEqual(len(failed["result_urls"]), 1)
        self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()
