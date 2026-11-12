"""The published site's product pages, after scripts/build_site.sh has copied web/ and near/web/ into the site:

- index.html: the front door (web/door.html): one line, the paste box, one button, the sample answered on that screen.
- prove/: the whole proof on NEAR (near/web/index.html), its files read from near/.
- labs/: the same check inside a lab's InterSystems IRIS (web/iris/index.html), its video and poster read from iris/.
- near/ and iris/: old addresses, sent on to prove/ and labs/ at once, with the front door's title and preview.

Every page carries one header: the logo (the front door) and the product's pages. The source pages stay as they are
(their tests and the local NEAR server use them); only the published site is composed.

    python3 scripts/site_pages.py <site dir>
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = [("prove/", "Prove"), ("labs/", "For labs")]
CSS = (".kh { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; max-width: 760px; margin: 0 auto; padding: 8px 16px; }\n"
       ".kh .logo { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; margin-right: auto; color: var(--ink); text-decoration: none; font: 600 20px/1 var(--head); }\n"
       ".kh nav { display: flex; flex-wrap: wrap; }\n"
       ".kh nav a { display: inline-flex; align-items: center; min-height: 44px; padding: 0 10px; color: var(--ink); text-decoration: none; font-size: 16px; }\n"
       ".kh nav a:hover, .kh nav a[aria-current] { text-decoration: underline; }\n")


def header(up: str, here: str = "") -> str:
    cur = ' aria-current="page"'
    links = "".join(f'<a href="{up}{p}"{cur if p == here else ""}>{name}</a>' for p, name in PAGES)
    return (f'<header class="kh" id="kh">\n  <a class="logo" href="{up or "./"}"><img src="{up}brand/mark.svg" width="26" height="26" alt="">Knos</a>\n'
            f'  <nav aria-label="Pages">{links}</nav>\n</header>')


def with_header(html: str, up: str, here: str) -> str:
    """The page's own bar (or the front door's header) replaced by the one header; the bar's script and its prerender
    rules go with it."""
    html, n = re.subn(r'<header class="(?:bar k-bar|kh)" id="(?:k-bar|kh)">.*?</header>', lambda m: header(up, here), html, count=1, flags=re.S)
    assert n == 1, "the page has no header to replace"
    html = re.sub(r'<script type="speculationrules">.*?</script>\n?', "", html, flags=re.S)
    html = re.sub(r'<script>addEventListener\("load", \(\) => \{ const s = document\.createElement\("script"\); s\.src = "[./]*brand/bar\.js";.*?</script>\n?', "", html, flags=re.S)
    if ".kh .logo" not in html:
        html = html.replace("</head>", f'<style id="kh-css">\n{CSS}</style>\n</head>', 1)
    return html


def head_of(page: str) -> str:
    tags = re.findall(r'<title>.*?</title>|<meta (?:name|property)="(?:description|og:[a-z:_]+|twitter:[a-z:_]+)"[^>]*>', page, re.S)
    return "\n".join(tags)


def redirect(to: str, head: str) -> str:
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
            f'<script>location.replace("{to}" + location.hash);</script>\n'
            f'<meta http-equiv="refresh" content="0; url={to}">\n{head}\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<meta name="robots" content="noindex">\n'
            f'<link rel="canonical" href="https://drexthealpha.github.io/Knos/{to.lstrip("./")}">\n'
            f'</head><body><p><a href="{to}">Knos</a></p></body></html>\n')


def main(site: str) -> int:
    out = Path(site)
    door = (ROOT / "web" / "door.html").read_text(encoding="utf-8")
    (out / "index.html").write_text(with_header(door, "", ""), encoding="utf-8")
    (out / "door.html").unlink(missing_ok=True)
    near = (ROOT / "near" / "web" / "index.html").read_text(encoding="utf-8")
    near = near.replace('fetch("latest.json"', 'fetch("../near/latest.json"').replace('href="embed.html"', 'href="../near/embed.html"')
    (out / "prove").mkdir(exist_ok=True)
    (out / "prove" / "index.html").write_text(with_header(near, "../", "prove/"), encoding="utf-8")
    iris = (ROOT / "web" / "iris" / "index.html").read_text(encoding="utf-8")
    iris = iris.replace('"knos-iris.mp4"', '"../iris/knos-iris.mp4"').replace('poster="poster.png"', 'poster="../iris/poster.png"')
    (out / "labs").mkdir(exist_ok=True)
    (out / "labs" / "index.html").write_text(with_header(iris, "../", "labs/"), encoding="utf-8")
    head = head_of(door)
    (out / "near" / "index.html").write_text(redirect("../prove/", head), encoding="utf-8")
    (out / "iris" / "index.html").write_text(redirect("../labs/", head), encoding="utf-8")
    print("product pages: index.html (the front door), prove/, labs/; near/ and iris/ send on")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
