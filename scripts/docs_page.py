"""The docs index as a page of the front door (/docs/): docs/reference/README.md's six questions, each answered by the
page to read first, then every document under it with its one line, linked to the file on GitHub. All in the served HTML.

    python scripts/docs_page.py            write web/docs/index.html
    python scripts/docs_page.py --check    exit 1 when it differs
"""
from __future__ import annotations

import html
import json
import posixpath
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT / "docs" / "reference" / "README.md"
OUT = ROOT / "web" / "docs" / "index.html"
SITE = "https://drexthealpha.github.io/Knos/"
BLOB = "https://github.com/drexthealpha/Knos/blob/main/"
ROW = re.compile(r"^\| \[([^\]]+)\]\(([^)]+)\) \| (.+?) \|\s*$")


def sections() -> list[dict]:
    text = MAP.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"^## (\d)\. (.+?)\n(.*?)(?=^## |\Z)", text, re.M | re.S):
        rows = [ROW.match(line) for line in m.group(3).splitlines()]
        docs = [{"name": r.group(1), "href": BLOB + posixpath.normpath(posixpath.join("docs/reference", r.group(2))), "what": r.group(3).replace("`", "").replace("**", "")} for r in rows if r]
        if docs:
            out.append({"q": m.group(2).strip(), "docs": docs})
    return out


def page(ss: list[dict]) -> str:
    e = html.escape
    crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Knos", "item": SITE}, {"@type": "ListItem", "position": 2, "name": "Docs", "item": SITE + "docs/"}]}
    def item(d: dict) -> str:
        return '<li><a href="' + e(d["href"]) + '">' + e(d["name"]) + "</a>: " + e(d["what"]) + "</li>"

    def section(s: dict) -> str:
        first = s["docs"][0]
        return (f'    <section data-q="{e(s["q"])}">\n      <h2>{e(s["q"])}</h2>\n'
                f'      <p>Read <a href="{e(first["href"])}">{e(first["name"])}</a> first: {e(first["what"])}.</p>\n'
                f'      <ul>{"".join(item(d) for d in s["docs"][1:])}</ul>\n    </section>')
    body = "\n".join(section(s) for s in ss)
    n = sum(len(s["docs"]) for s in ss)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Knos. Docs</title>
<meta name="description" content="Every Knos document once, under six questions, each answered by the page to read first.">
<meta name="author" content="drexthealpha">
<link rel="canonical" href="{SITE}docs/">
<meta name="color-scheme" content="light dark">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Knos">
<meta property="og:title" content="Knos. Docs">
<meta property="og:url" content="{SITE}docs/">
<meta property="og:image" content="{SITE}brand/card.png">
<link rel="stylesheet" href="../brand/tokens.css">
<link rel="stylesheet" href="../app.css">
<!-- written by scripts/docs_page.py from docs/reference/README.md -->
<script type="application/ld+json">{json.dumps(crumbs)}</script>
<link rel="icon" href="../icon.svg" type="image/svg+xml">
</head>
<body>
<header class="bar">
  <a class="brand" href="../" aria-label="Knos home"><span class="wordmark" aria-hidden="true"></span><span class="name">Knos</span></a>
</header>
<main>
  <article class="view">
    <h1>Docs</h1>
    <p>{n} documents, each listed once under the question it answers.</p>
{body}
  </article>
</main>
<footer class="foot">
  <span>Devnet is test mode: the money is test USDC.</span>
  <span><a href="../">Knos home</a> · <a href="../proof/">Proof</a> · <a href="../status/">Status</a> · <a href="https://github.com/drexthealpha/Knos">Source (MIT)</a></span>
</footer>
</body>
</html>
"""


def main(argv: list[str]) -> int:
    new = page(sections())
    if "--check" in argv:
        same = OUT.is_file() and OUT.read_text(encoding="utf-8") == new
        print("docs page is current" if same else "docs page differs: run python scripts/docs_page.py")
        return 0 if same else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(new, encoding="utf-8", newline="\n")
    print("docs page written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
