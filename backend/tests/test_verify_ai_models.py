from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image, ImageDraw

from backend.scripts.verify_ai_models import inspect_restored_models, purple_marker_ratio


class VerifyAiModelsTest(unittest.TestCase):
    def make_image(self, path: Path, size: int, marker_diameter: int) -> None:
        image = Image.new("RGB", (size, size), "#e8e9ed")
        draw = ImageDraw.Draw(image)
        draw.ellipse((24, 24, 24 + marker_diameter, 24 + marker_diameter), fill="#8457ff")
        image.save(path)

    def test_accepts_twenty_large_images_with_source_sized_markers(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for number in range(1, 21):
                self.make_image(root / f"approved_model_{number:02d}-ai-hd.png", 1200, 120)
            failures, ratios = inspect_restored_models(root)
            self.assertEqual(failures, [])
            self.assertEqual(len(ratios), 20)

    def test_rejects_missing_images_low_resolution_and_large_marker(self) -> None:
        with TemporaryDirectory() as folder:
            root = Path(folder)
            self.make_image(root / "approved_model_01-ai-hd.png", 800, 160)
            failures, _ = inspect_restored_models(root)
            self.assertTrue(any("expected 20" in failure for failure in failures))
            self.assertTrue(any("only 800x800" in failure for failure in failures))
            self.assertTrue(any("purple marker ratio" in failure for failure in failures))

    def test_marker_ratio_ignores_non_purple_content(self) -> None:
        with TemporaryDirectory() as folder:
            path = Path(folder) / "plain.png"
            Image.new("RGB", (1200, 1200), "white").save(path)
            self.assertEqual(purple_marker_ratio(path), 0)


if __name__ == "__main__":
    unittest.main()
