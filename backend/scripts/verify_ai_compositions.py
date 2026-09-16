from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
RESTORED_DIR = ROOT / "data" / "compositions" / "ai-restored"


def purple_marker_ratio(path: Path) -> float:
    with Image.open(path) as image:
        hsv = image.convert("HSV")
        width, height = hsv.size
        points: list[tuple[int, int]] = []
        for y in range(max(1, round(height * 0.24))):
            for x in range(max(1, round(width * 0.24))):
                hue, saturation, value = hsv.getpixel((x, y))
                if 175 <= hue <= 235 and saturation >= 80 and value >= 90:
                    points.append((x, y))
        if not points:
            return 0
        marker_width = max(x for x, _ in points) - min(x for x, _ in points) + 1
        marker_height = max(y for _, y in points) - min(y for _, y in points) + 1
        return max(marker_width / width, marker_height / height)


def main() -> None:
    files = sorted(RESTORED_DIR.glob("bed_composition_*-ai-hd.png"))
    if len(files) != 61:
        raise SystemExit(f"expected 61 restored images, found {len(files)}")

    failures: list[str] = []
    ratios: list[float] = []
    for path in files:
        with Image.open(path) as image:
            width, height = image.size
        if min(width, height) < 1000:
            failures.append(f"{path.name}: only {width}x{height}")
        number = int(path.name.split("_")[2].split("-")[0])
        if number >= 21:
            ratio = purple_marker_ratio(path)
            ratios.append(ratio)
            if not 0.06 <= ratio <= 0.18:
                failures.append(f"{path.name}: purple marker ratio {ratio:.3f}")

    print(f"images={len(files)} marker_ratio={min(ratios):.3f}..{max(ratios):.3f}")
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
