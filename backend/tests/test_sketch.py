import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from PIL import Image

from backend.app import sketch


def upload(name="sketch.png"):
    data = io.BytesIO()
    Image.new("RGB", (160, 120), "white").save(data, "PNG")
    return UploadFile(filename=name, file=io.BytesIO(data.getvalue()), headers={"content-type": "image/png"})


class FakeProvider:
    calls = []

    async def generate(self, paths, target, _remove_text, _notes, output, _stage, *, prompt):
        self.calls.append((list(paths), target, prompt))
        Image.new("RGB", target, "blue").save(output, "PNG")
        return {"model": "fake"}


class SketchTests(unittest.IsolatedAsyncioTestCase):
    def test_size_and_prompt(self):
        self.assertEqual(sketch.output_size("3:4", "1K"), (768, 1024))
        with self.assertRaises(HTTPException):
            sketch.output_size("2:3", "1K")
        prompt = sketch.generation_prompt("四件套", "棉", "刺绣", "color", "#ff0000", False, True, (768, 1024))
        self.assertIn("Image 1 is the authoritative", prompt)
        self.assertIn("#ff0000", prompt)
        self.assertIn("final image is a visual reference", prompt)

    async def test_generation_passes_a_b_and_reference_to_provider(self):
        FakeProvider.calls = []
        with tempfile.TemporaryDirectory() as temp, patch.object(sketch, "UPLOAD_DIR", Path(temp) / "uploads"), patch.object(sketch, "RESULT_DIR", Path(temp) / "results"), patch.object(sketch, "current_configuration", return_value=("key", "endpoint", "model")), patch.object(sketch, "ReplicaProvider", FakeProvider):
            value = await sketch.generate(upload("a.png"), upload("b.png"), upload("reference.png"), "image", "#ffffff", "四件套", "棉", "刺绣", "3:4", "1K")
            self.assertEqual(value["output_size"], [768, 1024])
            self.assertEqual(len(FakeProvider.calls[0][0]), 3)
            self.assertIn("B-version", FakeProvider.calls[0][2])
            self.assertTrue((Path(temp) / "results" / "sketch" / value["id"] / "result.png").is_file())


if __name__ == "__main__":
    unittest.main()
