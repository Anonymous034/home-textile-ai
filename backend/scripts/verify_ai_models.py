from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
RESTORED_DIR = ROOT / "data" / "model-ai-restored"
EXPECTED_COUNT = 20
MIN_SHORT_EDGE = 1000
# The enabled source portraits measure 0.098..0.102. Keep a narrow allowance
# for AI-restoration antialiasing while rejecting composition-library large dots.
MIN_MARKER_RATIO = 0.075
MAX_MARKER_RATIO = 0.125


def purple_marker_ratio(path: Path) -> float:
    with Image.open(path) as image:
        hsv = image.convert("HSV")
        width, height = hsv.size
        search_width = max(1, round(width * 0.18))
        search_height = max(1, round(height * 0.18))
        points: list[tuple[int, int]] = []
        for y in range(search_height):
            for x in range(search_width):
                hue, saturation, value = hsv.getpixel((x, y))
                if 165 <= hue <= 235 and saturation >= 80 and value >= 90:
                    points.append((x, y))
        if not points:
            return 0
        marker_width = max(x for x, _ in points) - min(x for x, _ in points) + 1
        marker_height = max(y for _, y in points) - min(y for _, y in points) + 1
        return max(marker_width / width, marker_height / height)


def inspect_restored_models(root: Path) -> tuple[list[str], list[float]]:
    files = sorted(root.glob("approved_model_??-ai-hd.png"))
    failures: list[str] = []
    ratios: list[float] = []
    if len(files) != EXPECTED_COUNT:
        failures.append(f"expected 20 restored images, found {len(files)}")

    for path in files:
        with Image.open(path) as image:
            width, height = image.size
        if min(width, height) < MIN_SHORT_EDGE:
            failures.append(f"{path.name}: only {width}x{height}")
        ratio = purple_marker_ratio(path)
        ratios.append(ratio)
        if not MIN_MARKER_RATIO <= ratio <= MAX_MARKER_RATIO:
            failures.append(f"{path.name}: purple marker ratio {ratio:.3f}")

    return failures, ratios


def main() -> None:
    failures, ratios = inspect_restored_models(RESTORED_DIR)
    if ratios:
        print(f"images={len(ratios)} marker_ratio={min(ratios):.3f}..{max(ratios):.3f}")
    else:
        print("images=0 marker_ratio=n/a")
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
