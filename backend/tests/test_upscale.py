import unittest

from backend.app.upscale import enhancement_prompt, target_size


class UpscaleRulesTests(unittest.TestCase):
    def test_detail_and_upscale_preserve_ratio_with_different_targets(self):
        self.assertEqual(target_size(800, 600, "detail"), (1600, 1200))
        self.assertEqual(target_size(800, 600, "upscale"), (3200, 2400))

    def test_large_target_is_capped_for_provider(self):
        width, height = target_size(2000, 1500, "upscale")
        self.assertLessEqual(max(width, height), 4096)
        self.assertLessEqual(width * height, 16_000_000)

    def test_prompts_require_identity_and_composition_preservation(self):
        detail = enhancement_prompt("detail", 1600, 1200)
        upscale = enhancement_prompt("upscale", 3200, 2400)
        self.assertIn("preserve the exact composition", detail)
        self.assertIn("compression artifacts", detail)
        self.assertIn("3200x2400", upscale)


if __name__ == "__main__":
    unittest.main()
