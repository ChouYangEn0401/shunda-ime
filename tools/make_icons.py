"""Render the IME icons (.ico) with Microsoft JhengHei.

The generated icons are committed; re-run only when changing the design.
Run: uv run python tools/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "backend" / "input_methods" / "smartime" / "icons"
FONT = "C:/Windows/Fonts/msjhbd.ttc"
SIZES = [16, 20, 24, 32, 40, 48, 64, 256]

ICONS = {
    # file: (text, background, foreground)
    "ime.ico": ("智", "#2563EB", "#FFFFFF"),
    # tray icons, one per mode
    "auto.ico": ("自", "#2563EB", "#FFFFFF"),  # 中英自動
    "chinese.ico": ("中", "#0F766E", "#FFFFFF"),  # 純中文
    "english.ico": ("英", "#4B5563", "#FFFFFF"),  # 純英文
}


def render(text: str, bg: str, fg: str, size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = size // 5
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=bg)
    font = ImageFont.truetype(FONT, int(size * 0.72))
    box = d.textbbox((0, 0), text, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]), text, font=font, fill=fg)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (text, bg, fg) in ICONS.items():
        render(text, bg, fg).save(OUT / name, sizes=[(s, s) for s in SIZES])
        print("wrote", OUT / name)


if __name__ == "__main__":
    main()
