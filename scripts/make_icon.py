"""Render the integration icon: a TV with an Ambilight glow (left/top/right,
like the 65PQS8651 – no LEDs at the bottom). Original artwork, no logos.

    .venv/bin/python scripts/make_icon.py
"""

import colorsys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 2048  # draw large, downscale for anti-aliasing
OUT = Path(__file__).resolve().parents[1] / "custom_components/philips_titan/brand"


def render() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # TV body geometry
    w, h = int(S * 0.54), int(S * 0.33)
    x0, y0 = (S - w) // 2, int(S * 0.31)
    x1, y1 = x0 + w, y0 + h

    # Ambilight: coloured dots along left -> top -> right, blurred into a glow
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    pts = []
    n_side, n_top = 10, 22
    for i in range(n_side):                       # left, bottom -> top
        pts.append((x0, y1 - (h * i) // (n_side - 1)))
    for i in range(1, n_top - 1):                 # top, left -> right
        pts.append((x0 + (w * i) // (n_top - 1), y0))
    for i in range(n_side):                       # right, top -> bottom
        pts.append((x1, y0 + (h * i) // (n_side - 1)))
    r = int(S * 0.085)
    for k, (px, py) in enumerate(pts):
        hue = 0.55 + 0.45 * k / (len(pts) - 1)   # cyan -> blue -> violet -> magenta -> orange
        cr, cg, cb = colorsys.hsv_to_rgb(hue % 1.0, 0.95, 1.0)
        gd.ellipse((px - r, py - r, px + r, py + r), fill=(int(cr * 255), int(cg * 255), int(cb * 255), 235))
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.04))
    img.alpha_composite(glow)

    d = ImageDraw.Draw(img)
    # stand
    sw = int(S * 0.20)
    d.rounded_rectangle((S // 2 - S // 60, y1, S // 2 + S // 60, y1 + int(S * 0.10)), radius=S // 80, fill=(52, 58, 70, 255))
    d.rounded_rectangle((S // 2 - sw // 2, y1 + int(S * 0.09), S // 2 + sw // 2, y1 + int(S * 0.125)),
                        radius=S // 60, fill=(52, 58, 70, 255))
    # bezel + screen
    d.rounded_rectangle((x0, y0, x1, y1), radius=int(S * 0.035), fill=(34, 38, 48, 255))
    m = int(S * 0.022)
    d.rounded_rectangle((x0 + m, y0 + m, x1 - m, y1 - m), radius=int(S * 0.018), fill=(16, 19, 26, 255))
    # subtle screen reflection
    refl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(refl).polygon(
        [(x0 + m, y0 + m), (x0 + int(w * 0.42), y0 + m), (x0 + int(w * 0.18), y1 - m), (x0 + m, y1 - m)],
        fill=(255, 255, 255, 18),
    )
    img.alpha_composite(refl)
    return img


def trim_square(img: Image.Image) -> Image.Image:
    """Crop to content and pad to a square (HA brands guideline)."""
    alpha = img.getchannel("A").point(lambda a: 255 if a > 8 else 0)  # ignore faint blur tails
    bbox = alpha.getbbox()
    img = img.crop(bbox)
    side = max(img.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return sq


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    icon = trim_square(render())
    icon.resize((512, 512), Image.LANCZOS).save(OUT / "icon@2x.png", optimize=True)
    icon.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png", optimize=True)
    print("geschrieben:", *(p.name for p in sorted(OUT.glob("*.png"))))
