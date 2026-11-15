"""Kept for its record: the 0.3.x front door's snapshot of the research products open for backing, written into
web/index.html. That page is no longer published (the front door is web/door.html); tests/test_site_home.py still
holds the two together.

    python scripts/front_snapshot.py [https://knos.onrender.com/api/front | a saved JSON file]   (write)
    python scripts/front_snapshot.py --check                                                    (held by tests)

The first screen (#home-products) must be whole before anything answers: the app is a free instance that sleeps. So
the page ships the cards themselves, drawn here from the app's own list (GET /api/front), and web/home.js redraws them
from the live list once the app answers. The snapshot's rows sit beside the cards (<script id="home-snapshot">), and
--check draws the cards again from those rows: the two cannot drift apart. Only what Knos computes is kept (the
product's name, the paper's venue and year, the reserve and the units pre-ordered); no Qloo response data.
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web" / "index.html"
SLUG = re.compile(r"^[a-z0-9-]{3,64}$")
BEGIN, END = "<!-- home:products (scripts/front_snapshot.py) -->", "<!-- /home:products -->"
KEEP = ("slug", "title", "paper", "reserve_units", "backed_units", "maker", "tech_name")


def title(t: str) -> str:
    """A product's name on the first screen: twelve words at most (web/home.js title)."""
    w = str(t or "").split()
    return " ".join(w[:11]) + "…" if len(w) > 12 else " ".join(w)


def card(p: dict) -> str:
    """The markup web/home.js cardHTML draws, character for character."""
    slug = p["slug"] if SLUG.match(str(p.get("slug", ""))) else ""
    reserve, backed = max(0, int(p.get("reserve_units") or 0)), max(0, int(p.get("backed_units") or 0))
    fill = max(2, min(100, int(100 * backed / reserve + 0.5))) if reserve else 2        # Math.round, not banker's rounding
    e = lambda s: html.escape(str(s if s is not None else ""), quote=True).replace("&#x27;", "&#39;")  # noqa: E731

    def act(what: str, label: str, cls: str) -> str:
        return f'<a class="k-btn{cls}" href="wanted.html#{what}={slug}" data-app="#{what}={slug}">{label}</a>'
    return (f'<li class="hp" data-slug="{e(slug)}"><p class="hp-src">{e(p["tech_name"]) + " · " if p.get("tech_name") else ""}{e(p.get("paper") or "Your idea")}{"" if p.get("maker") else " · maker wanted"}</p>'
            f'<h3 class="hp-t">{e(title(p["title"]))}</h3>'
            + (f'<div class="hp-bar" aria-hidden="true"><i style="width:{fill}%"></i></div>' if backed else '')
            + f'<p class="hp-act">{act("back", "Back it", "")} {act("fund", "Fund the work", " quiet")} {act("contribute", "Contribute", " quiet")}</p></li>')


def rows_of(board: dict) -> list[dict]:
    out = []
    for p in board.get("products") or []:
        if SLUG.match(str(p.get("slug", ""))) and p.get("title"):
            out.append({k: p.get(k) for k in KEEP})
    return out[:3]


def block(rows: list[dict], taken: str) -> str:
    data = json.dumps({"taken": taken, "rows": rows}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return (f'{BEGIN}\n      <script type="application/json" id="home-snapshot">{data}</script>\n      '
            + "\n      ".join(card(r) for r in rows) + f"\n      {END}")


def current(page: str) -> tuple[dict, str]:
    i, j = page.index(BEGIN), page.index(END) + len(END)
    found = re.search(r'<script type="application/json" id="home-snapshot">(.*?)</script>', page[i:j], re.S)
    return (json.loads(found[1].replace("<\\/", "</")) if found else {"taken": "", "rows": []}), page[i:j]


def check() -> list[str]:
    page = PAGE.read_text(encoding="utf-8")
    snap, have = current(page)
    want = block(snap["rows"], snap["taken"])
    bad = [] if have == want else ["web/index.html: the cards are not the ones the snapshot's rows draw (run scripts/front_snapshot.py)"]
    if not 1 <= len(snap["rows"]) <= 3:
        bad.append("the snapshot holds 1 to 3 products")
    return bad


def main(argv: list[str]) -> int:
    if argv[:1] == ["--check"]:
        bad = check()
        print("\n".join(bad) or "front snapshot: ok")
        return 1 if bad else 0
    src = argv[0] if argv else "https://knos.onrender.com/api/front"
    if src.startswith("https://"):
        with urllib.request.urlopen(src, timeout=60) as r:          # noqa: S310 - the app's own public list
            board = json.loads(r.read())
    else:
        board = json.loads(Path(src).read_text(encoding="utf-8"))
    rows = rows_of(board)
    if not rows:
        print("the list holds no product open for backing: the snapshot is kept as it is")
        return 1
    page = PAGE.read_text(encoding="utf-8")
    _, have = current(page)
    PAGE.write_text(page.replace(have, block(rows, str(board.get("at") or "")[:10])), encoding="utf-8", newline="\n")
    print(f"front snapshot: {len(rows)} products from {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
