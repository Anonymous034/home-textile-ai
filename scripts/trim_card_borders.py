from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
FINAL_DIR = ROOT / "output" / "feature-cards-final"
OUTPUT_DIR = ROOT / "output" / "feature-cards-trimmed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

INPUTS = [
    (Path(r"C:\Users\马翾\Pictures\Screenshots\屏幕截图 2026-08-12 212742.png"), "reference-ai-studio.png"),
    (Path(r"C:\Users\马翾\Pictures\Screenshots\屏幕截图 2026-08-12 212755.png"), "reference-bestseller-replication.png"),
    (Path(r"C:\Users\马翾\Pictures\Screenshots\屏幕截图 2026-08-12 212802.png"), "reference-detail-page.png"),
    (Path(r"C:\Users\马翾\Pictures\Screenshots\屏幕截图 2026-08-12 212808.png"), "reference-template.png"),
    (FINAL_DIR / "pattern-creation.png", "pattern-creation.png"),
    (FINAL_DIR / "viral-video.png", "viral-video.png"),
    (FINAL_DIR / "sketch-to-image.png", "sketch-to-image.png"),
    (FINAL_DIR / "local-edit.png", "local-edit.png"),
    (FINAL_DIR / "buyer-show.png", "buyer-show.png"),
    (FINAL_DIR / "one-click-hd.png", "one-click-hd.png"),
]


def content_box(image: Image.Image) -> tuple[int, int, int, int]:
    rgb = image.convert("RGB")
    pixels = rgb.load()
    xs: list[int] = []
    ys: list[int] = []

    # 外围是接近纯黑的截图底色；卡片最深的区域仍比它更亮。
    # 用很低的亮度门槛只去掉外围黑边，不会误删卡片里的黑色说明区。
    for y in range(rgb.height):
        for x in range(rgb.width):
            r, g, b = pixels[x, y]
            if max(r, g, b) >= 12:
                xs.append(x)
                ys.append(y)

    if not xs:
        return (0, 0, rgb.width, rgb.height)

    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


for source, output_name in INPUTS:
    image = Image.open(source).convert("RGB")
    box = content_box(image)
    trimmed = image.crop(box)
    output = OUTPUT_DIR / output_name
    trimmed.save(output, quality=96)
    print(f"{output_name}: {image.size} -> {trimmed.size}, crop={box}")
