from collections import deque
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output" / "feature-cards-trimmed"
OUTPUT = ROOT / "output" / "feature-cards-colorful"
OUTPUT.mkdir(parents=True, exist_ok=True)

# 文件名: (上半部分环境色, 下半部分深色)
PALETTES = {
    "reference-ai-studio.png": ((178, 202, 179), (24, 52, 43)),
    "reference-bestseller-replication.png": ((220, 181, 183), (67, 35, 45)),
    "reference-detail-page.png": ((207, 194, 221), (48, 42, 70)),
    "reference-template.png": ((184, 204, 216), (34, 52, 65)),
    "pattern-creation.png": ((198, 201, 164), (43, 54, 34)),
    "viral-video.png": ((229, 193, 157), (72, 43, 33)),
    "sketch-to-image.png": ((181, 207, 218), (34, 57, 72)),
    "local-edit.png": ((199, 181, 221), (54, 42, 76)),
    "buyer-show.png": ((207, 172, 139), (66, 45, 33)),
    "one-click-hd.png": ((164, 201, 199), (29, 57, 58)),
}


def panel_start(image: Image.Image) -> int:
    rgb = image.convert("RGB")
    start = int(rgb.height * 0.48)
    for y in range(start, rgb.height):
        dark = 0
        for x in range(rgb.width):
            if max(rgb.getpixel((x, y))) < 58:
                dark += 1
        if dark / rgb.width > 0.72:
            return y
    return int(rgb.height * 0.67)


def clear_outer_black(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    queue: deque[tuple[int, int]] = deque()
    seen: set[tuple[int, int]] = set()

    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))

    while queue:
        x, y = queue.popleft()
        if (x, y) in seen:
            continue
        seen.add((x, y))
        r, g, b, _ = pixels[x, y]
        if max(r, g, b) >= 12:
            continue
        pixels[x, y] = (r, g, b, 0)
        if x > 0:
            queue.append((x - 1, y))
        if x + 1 < width:
            queue.append((x + 1, y))
        if y > 0:
            queue.append((x, y - 1))
        if y + 1 < height:
            queue.append((x, y + 1))
    return rgba


def recolor(source: Path, top_color: tuple[int, int, int], bottom_color: tuple[int, int, int]) -> Image.Image:
    image = clear_outer_black(Image.open(source))
    pixels = image.load()
    split = panel_start(image)

    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue

            if y < split:
                # 亮背景着色更明显，深色家具和人物只受很轻的环境色影响。
                lightness = (r + g + b) / 765
                strength = 0.08 + 0.14 * lightness
                nr = round(r * (1 - strength) + top_color[0] * strength)
                ng = round(g * (1 - strength) + top_color[1] * strength)
                nb = round(b * (1 - strength) + top_color[2] * strength)
                pixels[x, y] = (nr, ng, nb, a)
            else:
                brightness = max(r, g, b)
                # 只替换深色底板，图标、标题和简介等亮内容保持原样。
                if brightness < 72:
                    detail = brightness / 72
                    nr = min(255, round(bottom_color[0] + detail * 13))
                    ng = min(255, round(bottom_color[1] + detail * 13))
                    nb = min(255, round(bottom_color[2] + detail * 13))
                    pixels[x, y] = (nr, ng, nb, a)

    return image


for filename, (top, bottom) in PALETTES.items():
    result = recolor(SOURCE / filename, top, bottom)
    target = OUTPUT / filename
    result.save(target)
    print(f"{filename}: {result.size}, top={top}, bottom={bottom}")
