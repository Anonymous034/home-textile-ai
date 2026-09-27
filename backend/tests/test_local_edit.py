import tempfile
import unittest
from pathlib import Path

from PIL import Image

from backend.app.local_edit import keep_changes_inside_mask


class LocalEditScopeTests(unittest.TestCase):
    def test_selected_only_restores_every_pixel_outside_mask(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.png"
            mask_path = root / "mask.png"
            output_path = root / "result.png"

            Image.new("RGBA", (8, 8), (210, 40, 30, 255)).save(source_path)
            mask = Image.new("L", (8, 8), 0)
            for y in range(2, 6):
                for x in range(2, 6):
                    mask.putpixel((x, y), 255)
            mask.save(mask_path)
            Image.new("RGBA", (8, 8), (20, 60, 240, 255)).save(output_path)

            keep_changes_inside_mask(source_path, mask_path, output_path)

            with Image.open(output_path) as result:
                self.assertEqual(result.size, (8, 8))
                self.assertEqual(result.getpixel((0, 0)), (210, 40, 30, 255))
                self.assertEqual(result.getpixel((7, 7)), (210, 40, 30, 255))
                self.assertEqual(result.getpixel((3, 3)), (20, 60, 240, 255))


if __name__ == "__main__":
    unittest.main()
