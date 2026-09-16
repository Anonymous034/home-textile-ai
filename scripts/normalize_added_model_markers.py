from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "backend" / "data" / "preset-models"
BACKUP_DIR = MODEL_DIR / "before-marker-normalization"
DB_PATH = ROOT / "backend" / "data" / "studio.sqlite3"
MODEL_IDS = ("approved_model_21", "approved_model_22", "approved_model_23")


def remove_new_badge(image: Image.Image) -> Image.Image:
    """Replace the top-left New pill with the adjacent plain studio backdrop."""
    image = image.convert("RGB")
    width, _ = image.size
    scale = width / 462
    right, bottom = round(112 * scale), round(82 * scale)
    blend_start = round(55 * scale)

    # Extrapolate each background scanline from the unobstructed strip to the
    # right. This preserves the source's subtle horizontal backdrop gradient.
    sample_left = round(118 * scale)
    sample_right = round(170 * scale)
    fill = image.copy()
    fill_pixels = fill.load()
    source_pixels = image.load()
    sample_xs = list(range(sample_left, sample_right))
    mean_x = sum(sample_xs) / len(sample_xs)
    denominator = sum((x - mean_x) ** 2 for x in sample_xs)
    for y in range(0, bottom + 1):
        channel_lines: list[tuple[float, float]] = []
        for channel in range(3):
            values = [source_pixels[x, y][channel] for x in sample_xs]
            mean_value = sum(values) / len(values)
            slope = sum((x - mean_x) * (value - mean_value) for x, value in zip(sample_xs, values)) / denominator
            intercept = mean_value - slope * mean_x
            channel_lines.append((slope, intercept))
        for x in range(0, right + 1):
            predicted = tuple(
                max(0, min(255, round(slope * x + intercept)))
                for slope, intercept in channel_lines
            )
            if y > blend_start:
                alpha = max(0.0, (bottom - y) / max(1, bottom - blend_start))
                original = source_pixels[x, y]
                predicted = tuple(round(alpha * value + (1 - alpha) * original[channel]) for channel, value in enumerate(predicted))
            fill_pixels[x, y] = predicted
    return fill


def add_standard_marker(image: Image.Image) -> Image.Image:
    """Draw the same proportional purple marker used by the approved model library."""
    image = image.convert("RGBA")
    width, _ = image.size
    outer_diameter = round(width * 0.112)
    inner_diameter = round(width * 0.096)
    left = round(width * 0.053)
    top = round(width * 0.068)
    inset = (outer_diameter - inner_diameter) // 2

    marker = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.ellipse(
        (left, top + 2, left + outer_diameter, top + outer_diameter + 2),
        fill=(0, 0, 0, 70),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, round(width * 0.006))))
    marker.alpha_composite(shadow)

    draw = ImageDraw.Draw(marker)
    draw.ellipse(
        (left, top, left + outer_diameter, top + outer_diameter),
        fill=(248, 248, 250, 255),
    )
    draw.ellipse(
        (
            left + inset,
            top + inset,
            left + inset + inner_diameter,
            top + inset + inner_diameter,
        ),
        fill=(132, 70, 247, 255),
    )
    image.alpha_composite(marker)
    return image.convert("RGB")


def main() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for number in (21, 22, 23):
        path = MODEL_DIR / f"approved-model-{number}.png"
        backup = BACKUP_DIR / path.name
        if not backup.exists():
            shutil.copy2(path, backup)

        with Image.open(backup) as source:
            edited = remove_new_badge(source) if number == 23 else source.convert("RGB")
            edited = add_standard_marker(edited)
            edited.save(path, "PNG", optimize=True)

    updated_at = datetime.now(UTC).isoformat()
    with sqlite3.connect(DB_PATH) as db:
        db.execute("BEGIN IMMEDIATE")
        placeholders = ",".join("?" for _ in MODEL_IDS)
        cursor = db.execute(
            f"UPDATE model_presets SET updated_at=? WHERE id IN ({placeholders}) AND enabled=1",
            (updated_at, *MODEL_IDS),
        )
        if cursor.rowcount != 3:
            raise RuntimeError(f"expected 3 enabled presets, updated {cursor.rowcount}")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("database integrity check failed")
        db.commit()

    print("normalized=3 new_badge_removed=1 database=ok")


if __name__ == "__main__":
    main()
