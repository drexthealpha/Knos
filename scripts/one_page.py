"""One page: the site's root carries the whole product. After scripts/build_site.sh has written the front door as the
site's index.html, this puts the live NEAR proof flow (near/web/index.html) under the first line as #near, then the IRIS
proof check (web/iris/index.html) as #iris, and turns /near/ and /iris/ into pages that send a visitor on to those
sections, so every link already posted keeps working. The source pages stay as they are (their tests and the local
NEAR server use them); only the published site is composed.

    python3 scripts/one_page.py <site dir>
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRST_END = "<!-- /k-first -->"


def body_of(html: str) -> str:
    m = re.search(r"<main\b[^>]*>(.*)</main>", html, re.S)
    assert m, "no <main>"
    inner = re.sub(r"<!-- k-first -->.*?<!-- /k-first -->\n?", "", m.group(1), flags=re.S)
    return inner


def scoped_css(html: str, scope: str) -> str:
    """The page's own styles, kept to its section: every rule nested under the section's id; keyframes stay global."""
    css = "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", html, re.S))
    frames = []
    def keep(m):
        frames.append(m.group(0))
        return ""
    depth_re = re.compile(r"@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", re.S)
    css = depth_re.sub(keep, css)
    css = re.sub(r"(?m)^\s*(html, body|body|html|\*|:focus-visible)\s*\{[^{}]*\}\s*$", "", css)   # the page's own document rules
    return "\n".join(frames) + f"\n{scope} {{\n{css}\n}}\n"


def inline_scripts(html: str) -> list[str]:
    """The page's own scripts that run its sections (not the bar's, the head's early one or speculation rules)."""
    after = html[html.index("</main>"):]
    out = []
    for attrs, code in re.findall(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", after, re.S):
        if "speculationrules" in attrs or "application/ld+json" in attrs or 'document.createElement("script")' in code:
            continue
        out.append(code)
    return out


def head_of(page: str) -> str:
    """The one page's own title, description and preview tags: a tab, a link preview or a search result of an old
    address shows the one page, never a page of its own."""
    tags = re.findall(r'<title>.*?</title>|<meta (?:name|property)="(?:description|og:[a-z:_]+|twitter:[a-z:_]+)"[^>]*>', page, re.S)
    return "\n".join(tags)


def redirect(to: str, head: str) -> str:
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
            f'<script>location.replace("{to}");</script>\n'
            f'<meta http-equiv="refresh" content="0; url={to}">\n{head}\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<meta name="robots" content="noindex">\n'
            f'<link rel="canonical" href="https://drexthealpha.github.io/Knos/">\n'
            f'</head><body><p><a href="{to}">Knos</a></p></body></html>\n')


def main(site: str) -> int:
    out = Path(site)
    page = (out / "index.html").read_text(encoding="utf-8")
    assert FIRST_END in page, "the front door has no first line"
    near = (ROOT / "near" / "web" / "index.html").read_text(encoding="utf-8")
    iris = (ROOT / "web" / "iris" / "index.html").read_text(encoding="utf-8")
    # NEAR: its files stay under near/; its links to the shared brand are the root's own
    nb = body_of(near).replace("../brand/", "brand/").replace('href="embed.html"', 'href="near/embed.html"')
    njs = [c.replace('fetch("latest.json"', 'fetch("near/latest.json"').replace("../brand/", "brand/") for c in inline_scripts(near)]
    ib = body_of(iris).replace("../brand/", "brand/").replace('"knos-iris.mp4"', '"iris/knos-iris.mp4"').replace('poster="poster.png"', 'poster="iris/poster.png"')
    block = (f'\n<section id="near-flow" class="one-near" aria-label="Prove a paper\'s claim on NEAR">\n{nb}\n</section>\n'
             f'<section id="iris" class="one-iris iris-page" aria-label="The proof check in InterSystems IRIS">\n{ib}\n</section>\n')
    # the IRIS page's rules start at its own <main class="iris-page">, which is the #iris section here: "&" is that section
    css = scoped_css(near, "#near-flow") + scoped_css(iris, "#iris").replace(".iris-page ", "& ").replace(".iris-page{", "&{")
    page = page.replace(FIRST_END, FIRST_END + block, 1)
    # the front door's own tools follow, named as more tools of the same product, so nobody reads them as a second one
    page = page.replace("<!-- k-hero -->", '<h2 class="one-more" id="more-tools">More Knos tools: see who would buy what a proof makes possible, and fund the work it needs</h2>\n<!-- k-hero -->', 1)
    page = page.replace("<!-- k-first -->", '<span id="near"></span>\n<!-- k-first -->', 1)
    page = page.replace('href="./near/"', 'href="#near-flow"').replace('href="./iris/"', 'href="#iris"')   # the bar jumps within the one page, no hop   # /near/ lands on the first line, the flow under it
    css += "#near, #near-flow, #iris { scroll-margin-top: 80px; }\n"
    css += ".one-more { font: 600 clamp(22px, 2.4vw, 30px)/1.2 var(--head); max-width: 40em; margin: 96px auto 0; padding-top: 32px; border-top: 1px solid var(--line); text-align: center; }\n"   # a section a link opens is not hidden under the bar
    page = page.replace("</head>", f"<style id=\"one-page\">\n{css}</style>\n</head>", 1)
    page = page.replace("</body>", "".join(f"<script>\n{c}\n</script>\n" for c in njs) + "</body>", 1)
    (out / "index.html").write_text(page, encoding="utf-8")
    head = head_of(page)
    (out / "near" / "index.html").write_text(redirect("../#near", head), encoding="utf-8")
    (out / "iris" / "index.html").write_text(redirect("../#iris", head), encoding="utf-8")
    print(f"one page: #near ({len(nb)} bytes) and #iris ({len(ib)} bytes) under the first line; /near/ and /iris/ send on")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
