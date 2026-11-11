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


def redirect(to: str, title: str) -> str:
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><title>{title}</title>\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta http-equiv="refresh" content="0; url={to}">\n<link rel="canonical" href="https://drexthealpha.github.io/Knos/{to[3:]}">\n'
            f'<script>location.replace("{to}" + (location.hash && location.hash !== "#" ? "" : ""));</script>\n'
            f'</head><body><p><a href="{to}">{title}</a></p></body></html>\n')


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
    css = scoped_css(near, "#near-flow") + scoped_css(iris, "#iris")
    page = page.replace(FIRST_END, FIRST_END + block, 1)
    page = page.replace("<!-- k-first -->", '<span id="near"></span>\n<!-- k-first -->', 1)   # /near/ lands on the first line, the flow under it
    page = page.replace("</head>", f"<style id=\"one-page\">\n{css}</style>\n</head>", 1)
    page = page.replace("</body>", "".join(f"<script>\n{c}\n</script>\n" for c in njs) + "</body>", 1)
    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "near" / "index.html").write_text(redirect("../#near", "Knos: prove a paper's claim on NEAR"), encoding="utf-8")
    (out / "iris" / "index.html").write_text(redirect("../#iris", "Knos: the proof check in InterSystems IRIS"), encoding="utf-8")
    print(f"one page: #near ({len(nb)} bytes) and #iris ({len(ib)} bytes) under the first line; /near/ and /iris/ send on")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
