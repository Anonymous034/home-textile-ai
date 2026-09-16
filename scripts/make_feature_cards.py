from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "public" / "feature-cards"
OUTPUT = ROOT / "output" / "feature-cards-final"
OUTPUT.mkdir(parents=True, exist_ok=True)

S = 2
W, H = 526 * S, 432 * S
CARD = (18 * S, 2 * S, 508 * S, 414 * S)
TOP = (18 * S, 2 * S, 508 * S, 277 * S)
BOTTOM = (18 * S, 277 * S, 508 * S, 414 * S)
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REGULAR = "C:/Windows/Fonts/msyh.ttc"

ITEMS = [
    ("pattern-creation.png", "花型创作", "从花型灵感到家具面料效果图。", "pattern"),
    ("viral-video.png", "爆款视频", "将家具图片生成多角度展示视频。", "video"),
    ("sketch-to-image.png", "画稿生图", "将家具设计画稿生成真实效果图。", "sketch"),
    ("local-edit.png", "局部编辑", "选中局部区域，只修改需要调整的内容。", "edit"),
    ("buyer-show.png", "买家秀", "将家具产品图生成真实家居展示图。", "buyer"),
    ("one-click-hd.png", "一键高清", "提升家具图片清晰度，保留材质细节。", "hd"),
]


def cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    source_ratio = image.width / image.height
    target_ratio = size[0] / size[1]
    if source_ratio > target_ratio:
        new_h = size[1]
        new_w = round(new_h * source_ratio)
    else:
        new_w = size[0]
        new_h = round(new_w / source_ratio)
    image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - size[0]) // 2
    top = (new_h - size[1]) // 2
    return image.crop((left, top, left + size[0], top + size[1]))


def rounded_mask(size: tuple[int, int], radius: int, corners: str) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((0, 0, size[0], size[1]), fill=255)
    r = radius
    if "tl" in corners:
        draw.rectangle((0, 0, r, r), fill=0)
        draw.pieslice((0, 0, r * 2, r * 2), 180, 270, fill=255)
    if "tr" in corners:
        draw.rectangle((size[0] - r, 0, size[0], r), fill=0)
        draw.pieslice((size[0] - r * 2, 0, size[0], r * 2), 270, 360, fill=255)
    if "bl" in corners:
        draw.rectangle((0, size[1] - r, r, size[1]), fill=0)
        draw.pieslice((0, size[1] - r * 2, r * 2, size[1]), 90, 180, fill=255)
    if "br" in corners:
        draw.rectangle((size[0] - r, size[1] - r, size[0], size[1]), fill=0)
        draw.pieslice((size[0] - r * 2, size[1] - r * 2, size[0], size[1]), 0, 90, fill=255)
    return mask


def draw_icon(draw: ImageDraw.ImageDraw, kind: str, box: tuple[int, int, int, int]) -> None:
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    u = S
    black = (15, 15, 17, 255)
    line = 3 * u

    if kind == "video":
        draw.rounded_rectangle((x1 + 12*u, y1 + 16*u, x2 - 15*u, y2 - 16*u), 5*u, outline=black, width=line)
        draw.polygon([(cx-4*u, cy-9*u), (cx-4*u, cy+9*u), (cx+10*u, cy)], fill=black)
        draw.line((x2-14*u, cy-7*u, x2-7*u, cy-12*u, x2-7*u, cy+12*u, x2-14*u, cy+7*u), fill=black, width=line)
    elif kind == "pattern":
        draw.line((cx, y2-12*u, cx, cy+4*u), fill=black, width=line)
        draw.arc((cx-16*u, cy+1*u, cx, y2-9*u), 190, 350, fill=black, width=line)
        draw.arc((cx, cy+1*u, cx+16*u, y2-9*u), 190, 350, fill=black, width=line)
        for dx, dy in [(0,-13),(-9,-6),(9,-6),(-6,4),(6,4)]:
            draw.ellipse((cx+(dx-6)*u, cy+(dy-6)*u, cx+(dx+6)*u, cy+(dy+6)*u), outline=black, width=2*u)
        draw.ellipse((cx-4*u, cy-4*u, cx+4*u, cy+4*u), fill=black)
    elif kind == "sketch":
        draw.rounded_rectangle((x1+12*u, y1+13*u, x2-12*u, y2-13*u), 4*u, outline=black, width=line)
        draw.line((x1+17*u, y2-20*u, cx-4*u, cy+2*u, cx+5*u, cy+10*u), fill=black, width=2*u)
        draw.line((cx+3*u, y2-14*u, x2-8*u, cy+3*u), fill=black, width=5*u)
        draw.ellipse((x2-17*u, y1+16*u, x2-10*u, y1+23*u), fill=black)
    elif kind == "edit":
        draw.line((x1+13*u, y1+22*u, x1+13*u, y1+13*u, x1+22*u, y1+13*u), fill=black, width=line)
        draw.line((x2-13*u, y1+22*u, x2-13*u, y1+13*u, x2-22*u, y1+13*u), fill=black, width=line)
        draw.line((x1+13*u, y2-22*u, x1+13*u, y2-13*u, x1+22*u, y2-13*u), fill=black, width=line)
        draw.line((x2-13*u, y2-22*u, x2-13*u, y2-13*u, x2-22*u, y2-13*u), fill=black, width=line)
        draw.line((cx-8*u, cy+9*u, cx+12*u, cy-11*u), fill=black, width=4*u)
    elif kind == "buyer":
        draw.rounded_rectangle((x1+11*u, y1+14*u, x2-11*u, y2-13*u), 4*u, outline=black, width=line)
        draw.ellipse((cx-5*u, cy-11*u, cx+5*u, cy-1*u), outline=black, width=2*u)
        draw.arc((cx-11*u, cy-1*u, cx+11*u, cy+16*u), 180, 360, fill=black, width=2*u)
    else:
        for angle in range(0, 360, 90):
            import math
            dx = math.cos(math.radians(angle))
            dy = math.sin(math.radians(angle))
            draw.line((cx+dx*4*u, cy+dy*4*u, cx+dx*17*u, cy+dy*17*u), fill=black, width=line)
        draw.ellipse((cx-5*u, cy-5*u, cx+5*u, cy+5*u), outline=black, width=2*u)
        draw.line((x1+14*u, y2-15*u, x1+25*u, y2-15*u), fill=black, width=2*u)


def make_card(filename: str, title: str, description: str, icon: str) -> Path:
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    card_w = CARD[2] - CARD[0]
    top_h = TOP[3] - TOP[1]
    source = Image.open(SOURCE / filename).convert("RGB")
    visual = cover(source, (card_w, top_h)).convert("RGBA")
    top_mask = rounded_mask((card_w, top_h), 22*S, "tl tr")
    canvas.paste(visual, (TOP[0], TOP[1]), top_mask)

    lower = Image.new("RGBA", (card_w, BOTTOM[3] - BOTTOM[1]), (23, 23, 26, 255))
    lower_mask = rounded_mask(lower.size, 22*S, "bl br")
    canvas.paste(lower, (BOTTOM[0], BOTTOM[1]), lower_mask)

    draw = ImageDraw.Draw(canvas)
    icon_box = (42*S, 247*S, 102*S, 307*S)
    draw.rounded_rectangle(icon_box, 16*S, fill=(255,255,255,255))
    draw_icon(draw, icon, icon_box)

    title_font = ImageFont.truetype(FONT_BOLD, 26*S)
    body_font = ImageFont.truetype(FONT_REGULAR, 16*S)
    draw.text((42*S, 327*S), title, font=title_font, fill=(250,250,252,255), anchor="la")
    draw.text((42*S, 374*S), description, font=body_font, fill=(133,133,145,255), anchor="la")

    output = OUTPUT / filename
    canvas.resize((526, 432), Image.Resampling.LANCZOS).convert("RGB").save(output, quality=95)
    return output


if __name__ == "__main__":
    for item in ITEMS:
        print(make_card(*item))
