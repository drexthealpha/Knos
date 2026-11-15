"""The raven icon set from web/icon.svg: web/brand/icon-192.png, icon-512.png and apple-touch-icon.png (180 px) on the
site's light square, and web/favicon.ico (16, 32 and 48 px). scripts/sync_brand.py copies them into the app.

    python scripts/make_icons.py        needs cairosvg and Pillow (pip install cairosvg pillow)
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
BG = "#f6f4ef"        # the site's paper colour; the raven is drawn dark on it, as on the light front door
INK = "#15171c"


def png(size: int) -> bytes:
    import cairosvg
    from PIL import Image
    svg = (WEB / "icon.svg").read_text(encoding="utf-8")
    svg = re.sub(r"<style>.*?</style>", "", svg, flags=re.S).replace('fill="currentColor"', f'fill="{INK}"')   # no media queries here
    pad = round(size * 0.12)
    raven = Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode(), output_width=size - 2 * pad, output_height=size - 2 * pad)))
    out = Image.new("RGBA", (size, size), BG)
    out.alpha_composite(raven.convert("RGBA"), (pad, pad))
    b = io.BytesIO()
    out.convert("RGB").save(b, "PNG", optimize=True)
    return b.getvalue()


def main() -> int:
    from PIL import Image
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
        (WEB / "brand" / name).write_bytes(png(size))
    big = Image.open(io.BytesIO(png(256)))
    big.save(WEB / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print("wrote web/brand/icon-192.png, icon-512.png, apple-touch-icon.png and web/favicon.ico")
    return 0


if __name__ == "__main__":
    sys.exit(main())
