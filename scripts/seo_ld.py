"""The public pages' JSON-LD (schema.org): on the front door, Knos as a SoftwareApplication with the one line and an Offer
in the pricing page's own words, and the Organization; on each inner page, its BreadcrumbList. Each block sits in the
page's head between markers, so a second run rewrites the same block.

    python scripts/seo_ld.py            write them
    python scripts/seo_ld.py --check    exit 1 when a page differs
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SITE = "https://drexthealpha.github.io/Knos/"
START, END = "<!-- ld:start -->", "<!-- ld:end -->"
# each inner page: its file, its name in the breadcrumb and its address
INNER = {"proof/index.html": ("Proof", "proof/"), "status/index.html": ("Status", "status/"), "calls/index.html": ("Qloo calls", "calls/"),
         "demo/index.html": ("Demo", "demo/"), "how-we-test.html": ("How we test Knos", "how-we-test.html"), "pricing.html": ("Pricing", "pricing.html"),
         "faq.html": ("Questions", "faq.html"), "privacy.html": ("Privacy and terms", "privacy.html"), "check/index.html": ("Check a pull request", "check/")}


def sentence() -> str:
    return json.loads((ROOT / "docs" / "facts.json").read_text(encoding="utf-8"))["sentence"]


def offer_words() -> str:
    """The pricing page's opening line, as the page says it."""
    s = (WEB / "pricing.html").read_text(encoding="utf-8")
    first = re.search(r"<h1[^>]*>.*?</h1>\s*<p[^>]*>(.*?)</p>", s, re.S)
    assert first, "pricing.html has no line under its heading"
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", first.group(1)))).strip()


def front() -> dict:
    org = {"@type": "Organization", "@id": SITE + "#org", "name": "Knos", "url": SITE, "sameAs": ["https://github.com/drexthealpha/Knos"]}
    app = {"@type": "SoftwareApplication", "name": "Knos", "description": sentence(), "url": SITE, "applicationCategory": "BusinessApplication",
           "operatingSystem": "Web", "license": "https://opensource.org/licenses/MIT", "publisher": {"@id": SITE + "#org"},
           "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD", "description": offer_words(), "url": SITE + "pricing.html"}}
    return {"@context": "https://schema.org", "@graph": [app, org]}


def crumbs(name: str, path: str) -> dict:
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Knos", "item": SITE}, {"@type": "ListItem", "position": 2, "name": name, "item": SITE + path}]}


def put(text: str, doc: dict) -> str:
    block = f'{START}<script type="application/ld+json">{json.dumps(doc, ensure_ascii=False)}</script>{END}'
    if START in text:
        return text[:text.index(START)] + block + text[text.index(END) + len(END):]
    return text.replace("</head>", block + "\n</head>", 1)


def pages() -> dict[Path, str]:
    out = {WEB / "home.html": put((WEB / "home.html").read_text(encoding="utf-8"), front())}
    for rel, (name, path) in INNER.items():
        f = WEB / rel
        out[f] = put(f.read_text(encoding="utf-8"), crumbs(name, path))
    return out


def main(argv: list[str]) -> int:
    got = pages()
    if "--check" in argv:
        stale = [str(f.relative_to(ROOT)) for f, t in got.items() if f.read_text(encoding="utf-8") != t]
        print("JSON-LD is current" if not stale else f"JSON-LD differs on {', '.join(stale)}: run python scripts/seo_ld.py")
        return 1 if stale else 0
    for f, t in got.items():
        f.write_text(t, encoding="utf-8", newline="\n")
    print(f"JSON-LD written on {len(got)} pages")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
