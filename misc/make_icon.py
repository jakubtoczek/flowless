"""Generate the Flowless app icon: two overlaid fluorescence histograms on a dark rounded
tile - a grey control peak and a blue stained one shifted right. Run: python misc/make_icon.py"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "src" / "flowless" / "assets"


def _peak(ss, centre, width, height, base):
    pts = []
    for i in range(0, 101):
        x = ss * 0.12 + ss * 0.76 * i / 100
        y = base - height * math.exp(-0.5 * ((x - centre) / width) ** 2)
        pts.append((x, y))
    return [(ss * 0.12, base)] + pts + [(ss * 0.88, base)]


def render(size: int) -> Image.Image:
    ss = size * 4                                   # supersampled, then downscaled
    im = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, ss - 1, ss - 1], radius=ss // 6, fill=(35, 35, 35, 255))
    base = ss * 0.80
    lw = max(4, ss // 48)
    grey = _peak(ss, ss * 0.33, ss * 0.075, ss * 0.58, base)
    blue = _peak(ss, ss * 0.64, ss * 0.10, ss * 0.44, base)
    d.polygon(grey, fill=(138, 137, 132, 255))
    layer = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    ImageDraw.Draw(layer).polygon(blue, fill=(42, 120, 214, 215))
    im = Image.alpha_composite(im, layer)
    d = ImageDraw.Draw(im)
    d.line(blue[1:-1], fill=(120, 175, 240, 255), width=lw, joint="curve")
    d.line([(ss * 0.10, base), (ss * 0.90, base)], fill=(220, 220, 220, 255), width=lw)
    return im.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 48, 64, 128, 256]
    imgs = [render(s) for s in sizes]
    imgs[-1].save(OUT / "flowless.png")
    imgs[-1].save(OUT / "flowless.ico", sizes=[(s, s) for s in sizes])
    print("wrote", OUT / "flowless.ico", "and flowless.png")


if __name__ == "__main__":
    main()
