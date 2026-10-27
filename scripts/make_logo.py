#!/usr/bin/env python3
"""Draw the Lantern Works mark (original, code-generated): logo.png 400x400, favicon-32.png, favicon.ico.
Deterministic; rerun to regenerate. Usage: python3 scripts/make_logo.py"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
BG, INK, GLOW, FLAME, CORE = (17, 24, 39), (245, 158, 11), (251, 191, 36), (252, 211, 77), (255, 247, 214)


def draw(size: int = 1600) -> Image.Image:
    s = size / 400
    S = lambda *v: [round(x * s) for x in v]
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(S(0, 0, 400, 400), radius=round(84 * s), fill=BG)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(S(130, 150, 270, 300), fill=GLOW + (150,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(40 * s)))
    d = ImageDraw.Draw(img)
    w = round(14 * s)
    d.arc(S(165, 50, 235, 120), 180, 360, fill=INK, width=w)            # handle
    d.rounded_rectangle(S(140, 98, 260, 128), radius=round(10 * s), fill=INK)   # cap
    d.rounded_rectangle(S(130, 128, 270, 300), radius=round(28 * s), outline=INK, width=w)  # glass
    d.line(S(200, 135, 200, 160), fill=INK, width=round(6 * s))
    d.rounded_rectangle(S(120, 300, 280, 330), radius=round(10 * s), fill=INK)  # base
    d.polygon(S(200, 165, 232, 228, 222, 262, 200, 272, 178, 262, 168, 228), fill=FLAME)  # flame
    d.ellipse(S(186, 222, 214, 262), fill=CORE)
    return img


def main() -> None:
    big = draw()
    big.resize((400, 400), Image.LANCZOS).save(ROOT / "logo.png", optimize=True)
    big.resize((32, 32), Image.LANCZOS).save(ROOT / "favicon-32.png", optimize=True)
    big.resize((256, 256), Image.LANCZOS).save(ROOT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    big.resize((180, 180), Image.LANCZOS).save(ROOT / "apple-touch-icon.png", optimize=True)


if __name__ == "__main__":
    main()
