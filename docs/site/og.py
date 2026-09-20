"""Render docs/site/og.png, the social share image for the product site.

One static 1200x630 PNG, drawn with Pillow from the same palette and copy as
index.html. Re-run it whenever the headline changes:

    python docs/site/og.py

It uses Cascadia Mono if the machine has it and falls back to any monospace
Pillow can find, so the output differs slightly across machines. That is
fine: the image is a card, not evidence.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE / "og.png"
W, H = 1200, 630

# The evidence page's dark tokens, so the card matches the site.
BG, PANEL, LINE = "#0d1117", "#161b22", "#30363d"
INK, DIM, GOOD, BAD = "#e6edf3", "#8b949e", "#3fb950", "#f85149"

FONTS = [
    r"C:\Windows\Fonts\CascadiaMono.ttf",
    r"C:\Windows\Fonts\consola.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in FONTS:
        p = Path(path)
        if p.exists():
            try:
                f = ImageFont.truetype(str(p), size)
                if bold and "Cascadia" in path:
                    f.set_variation_by_name("Bold")
                return f
            except Exception:
                continue
    return ImageFont.load_default()


def main() -> None:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    # A faint panel on the right, like the terminal in the hero.
    d.rounded_rectangle((720, 88, 1140, 542), radius=14, fill=PANEL, outline=LINE, width=2)
    d.rounded_rectangle((720, 88, 1140, 128), radius=14, fill="#11161d")
    d.rectangle((720, 114, 1140, 128), fill="#11161d")
    for i, x in enumerate((744, 764, 784)):
        d.ellipse((x, 102, x + 12, 114), fill=LINE)
    d.text((812, 100), "knos demo", font=font(15), fill=DIM)

    mono = font(18)
    y = 150
    lines = [
        ("$ knos claim \"the guard\"", "#58a6ff"),
        ("  Claimed the guard.", GOOD),
        ("", INK),
        ("$ Cursor: what do we know", "#58a6ff"),
        ("  about the guard?", "#58a6ff"),
        ("  Withheld. held by Claude Code", BAD),
        ("", INK),
        ("$ Cursor: edit guard.py", "#58a6ff"),
        ("  refused before the write", BAD),
        ("", INK),
        ("$ /brief ETH", "#58a6ff"),
        ("  Free. Nobody paid twice.", GOOD),
        ("", INK),
        ("$ rm ~/.knos/*/memory.db", "#58a6ff"),
        ("  everything above stops.", "#d29922"),
    ]
    for text, col in lines:
        d.text((748, y), text, font=mono, fill=col)
        y += 25

    # Left: the promise.
    d.text((64, 96), "LOCAL-FIRST · ONE SQLITE FILE · NO SERVER", font=font(16), fill=GOOD)

    head = font(46, bold=True)
    for i, t in enumerate(("One memory every", "coding agent on", "your machine shares.")):
        d.text((64, 144 + i * 56), t, font=head, fill=INK)

    body = font(21)
    d.text((64, 336), "Refuses the answer.", font=body, fill=INK)
    d.text((64, 366), "Refuses the edit before it lands.", font=body, fill=INK)
    d.text((64, 396), "Refuses the purchase.", font=body, fill=INK)
    d.text((64, 440), "Delete the file and there is no product.", font=font(19), fill=DIM)

    # Footer strip.
    d.line((64, 520, 660, 520), fill=LINE, width=1)
    d.text((64, 536), "drexthealpha.github.io/Knos/site", font=font(18), fill=DIM)
    d.text((64, 566), "pip install \"git+https://github.com/drexthealpha/Knos\"  ·  knos demo",
           font=font(15), fill=DIM)

    im.save(OUT, "PNG", optimize=True)
    print(f"wrote {OUT.relative_to(HERE.parent.parent)}  {W}x{H}  {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
