"""The published site's product pages, after scripts/build_site.sh has copied web/ and near/web/ into the site:

- index.html: the front door (web/door.html): one line, the paste box, one button, the sample answered on that screen.
- prove/: the whole proof on NEAR (near/web/index.html), its files read from near/.
- labs/: the same check inside a lab's InterSystems IRIS (web/iris/index.html), its video and poster read from iris/.
- check/: the pull request checker exactly as entered at Colosseum (tag v0.3.28), from web/check-v0328/: the tag's own
  check.js and check_rules.js beside it, and its paying step on Knos's programs on Solana devnet.
- near/ and iris/: old addresses, sent on to prove/ and labs/ at once, with the front door's title and preview.

Every page carries one header: the logo (the front door) and the product's pages. The source pages stay as they are
(their tests and the local NEAR server use them); only the published site is composed.

    python3 scripts/site_pages.py <site dir>
"""
import json
import re
import sys
from pathlib import Path

import site_product

ROOT = Path(__file__).resolve().parents[1]
PAGES = [("claims/", "Claims"), ("prove/", "Prove"), ("agents/", "For agents"), ("labs/", "For labs"), ("check/", "Check a PR")]
# the product's pages; every other page of the build leaves the published site, each old address sent to the front door
KEEP = {"index.html", "404.html", "privacy.html", "near/embed.html"}
CSS = ("#ask label a { display: inline !important; min-height: 0 !important; padding: 0 !important; }\n"   # the Prove page's Claims link sits in its sentence
       ".kh { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; max-width: 760px; margin: 0 auto; padding: 8px 16px; }\n"
       ".kh .logo { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; margin-right: auto; color: var(--ink); text-decoration: none; font: 600 20px/1 var(--head); }\n"
       ".kh .mark { display: block; width: 28px; height: 27px; background: currentColor; -webkit-mask: var(--m) center / contain no-repeat; mask: var(--m) center / contain no-repeat; }\n"
       ".kh nav { display: flex; flex-wrap: wrap; }\n"
       ".kh nav a { display: inline-flex; align-items: center; min-height: 44px; padding: 0 10px; color: var(--ink); text-decoration: none; font-size: 16px; }\n"
       ".kh nav a:hover, .kh nav a[aria-current] { text-decoration: underline; }\n")


def header(up: str, here: str = "") -> str:
    cur = ' aria-current="page"'
    links = "".join(f'<a href="{up}{p}"{cur if p == here else ""}>{name}</a>' for p, name in PAGES)
    return (f'<header class="kh" id="kh">\n  <a class="logo" href="{up or "./"}"><span class="mark" aria-hidden="true" style="--m: url({up}brand/mark.svg)"></span>Knos</a>\n'
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


def retitle(html: str, title: str, desc: str) -> str:
    """A page's own plain title and description, in its tab and its link preview."""
    html = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1, flags=re.S)
    for attr, value in (('name="description"', desc), ('property="og:title"', title), ('property="og:description"', desc),
                        ('name="twitter:title"', title), ('name="twitter:description"', desc)):
        html = re.sub(rf'<meta {attr} content="[^"]*"', f'<meta {attr} content="{value}"', html, count=1)
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


BEACON = """<script>
// first-party only (knos_wanted.visits): a random visit id that resets every day, no cookie, no IP stored; Do Not Track sends nothing
(() => { if (navigator.doNotTrack === "1" || window.doNotTrack === "1") return;
  const H = "https://knos.onrender.com", day = new Date().toISOString().slice(0, 10); let v, back = false;
  try { const s = JSON.parse(localStorage.getItem("knos.visit") || "{}"); back = !!s.day && s.day !== day && Date.now() - (s.at || 0) < 7 * 864e5;
    v = s.day === day ? s.v : [...crypto.getRandomValues(new Uint8Array(8))].map((b) => b.toString(16).padStart(2, "0")).join("");
    localStorage.setItem("knos.visit", JSON.stringify({ v, day, at: s.day === day ? s.at : Date.now() })); } catch { v = [...crypto.getRandomValues(new Uint8Array(8))].map((b) => b.toString(16).padStart(2, "0")).join(""); }
  const page = location.pathname.replace(/^\\/Knos/, "") || "/", t0 = Date.now();
  const send = (e, x) => { try { navigator.sendBeacon(H + "/api/visit", new Blob([JSON.stringify({ v, e, p: page, back, ...(x || {}) })], { type: "application/json" })); } catch { /* no beacon */ } };
  send("view");
  let presses = [];
  addEventListener("click", (ev) => { const at = performance.now(), n = presses.filter((p) => at - p.t < 1000 && Math.abs(p.x - ev.clientX) < 30 && Math.abs(p.y - ev.clientY) < 30).length;
    presses = [...presses.slice(-5), { t: at, x: ev.clientX, y: ev.clientY }]; if (n >= 2) send("rage");
    const target = ev.target.closest("button, a"); if (!target) return; send("press");
    let seen = false; const mo = new MutationObserver(() => { if (!seen) { seen = true; mo.disconnect(); const ms = Math.round(performance.now() - at); if (ms > 400) send("slow", { ms }); } });
    mo.observe(document.body, { subtree: true, childList: true, characterData: true }); setTimeout(() => { if (!seen) { mo.disconnect(); send("slow", { ms: 400 }); } }, 2000);
    if (/download/i.test(target.textContent)) send("download"); }, { capture: true });
  const seenText = new Set();
  setInterval(() => { const t = document.body.textContent;
    for (const [k, re] of [["result", /Yes, the claim holds|Answer: Yes|Answer: No|Nothing proved matches|cannot prove this paper/], ["proof", /Receipt for proof|Receipt: paid/], ["backed", /Bought .* shares|test USDC behind this proof/], ["error", /Not read|No answer this time|did not answer/]])
      if (!seenText.has(k) && re.test(t)) { seenText.add(k); send(k); } }, 1500);   // a light check, off the press path
  addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") send("leave", { s: Math.round((Date.now() - t0) / 1000) }); });
})();
</script>
"""


def beacon(out: Path) -> None:
    """The first-party visit script on every product page (knos_wanted.visits), just before </body>."""
    pages = [out / "index.html", out / "prove" / "index.html", out / "labs" / "index.html", out / "check" / "index.html",
             *[out / p for p in ("claims/index.html", "agents/index.html", "pricing/index.html", "status/index.html")], *(out / "claim").rglob("index.html")]
    for p in pages:
        if p.is_file():
            t = p.read_text(encoding="utf-8")
            if "knos.visit" not in t and "</body>" in t:
                p.write_text(t.replace("</body>", BEACON + "</body>", 1), encoding="utf-8")


def sweep(out: Path) -> int:
    """Every page of the build that is not the product's becomes an old address: it sends a visitor to the front door
    (pricing.html to pricing/). Run again by the pages workflow after its own steps write pages (rank/)."""
    head = head_of((ROOT / "web" / "door.html").read_text(encoding="utf-8"))
    keep = KEEP | {f"{p}index.html" for p, _ in PAGES} | {"pricing/index.html", "status/index.html", "near/index.html", "iris/index.html"}
    keep |= {p.relative_to(out).as_posix() for p in (out / "claim").rglob("index.html")} if (out / "claim").is_dir() else set()
    moved = {"pricing.html": "pricing/"}
    gone = 0
    for p in sorted(out.rglob("*.html")):
        rel = p.relative_to(out).as_posix()
        if rel in keep or rel.startswith("near/vendor/") or 'http-equiv="refresh"' in p.read_text(encoding="utf-8", errors="replace")[:600]:
            continue
        to = "../" * rel.count("/") + moved.get(rel, "")
        p.write_text(redirect(to or "./", head), encoding="utf-8")
        gone += 1
    return gone


def door_claims() -> list[dict]:
    """The claims registry as the front door answers from it: each claim, its paper (DOI, arXiv id) and its locked test
    with the test file's sha256."""
    import hashlib
    out = []
    for c in json.loads((ROOT / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]:
        doi = str(c.get("doi") or "")
        ax = re.search(r"arxiv\.(\d{4}\.\d{4,5})", doi, re.I)
        test = ROOT / "near" / "agents" / "job" / c["test"]
        out.append({k: c[k] for k in ("name", "plain", "quote", "paper", "authors", "year", "test")} |
                   {"doi": doi, "arxiv": ax.group(1) if ax else "", "sha256": hashlib.sha256(test.read_bytes()).hexdigest()})
    return out


def main(site: str) -> int:
    out = Path(site)
    door = (ROOT / "web" / "door.html").read_text(encoding="utf-8")
    door = door.replace("/*CLAIMS*/[]/*END*/", json.dumps(door_claims(), ensure_ascii=False).replace("</", "<\\/"))
    (out / "index.html").write_text(with_header(door, "", ""), encoding="utf-8")
    (out / "door.html").unlink(missing_ok=True)
    near = (ROOT / "near" / "web" / "index.html").read_text(encoding="utf-8")
    near = near.replace('fetch("latest.json"', 'fetch("../near/latest.json"').replace('href="embed.html"', 'href="../near/embed.html"')
    # the proof page opens on the proof: its heading says what the page does, the front door asks the question
    near, n = re.subn(r"<!-- k-first -->.*?<!-- /k-first -->", '<h1 class="k-first" id="k-first">Prove a paper\'s claim on NEAR</h1>', near, count=1, flags=re.S)
    assert n == 1, "the NEAR page has no first block"
    near = retitle(near, "Knos: prove a paper's claim on NEAR", "Order a proof of a paper's claim on NEAR testnet: the verdict, the verified code and its receipt.")
    near = re.sub(r'\s*<p class="vision"[^>]*>.*?</p>', "", near, flags=re.S)
    (out / "prove").mkdir(exist_ok=True)
    (out / "prove" / "index.html").write_text(with_header(near, "../", "prove/"), encoding="utf-8")
    iris = (ROOT / "web" / "iris" / "index.html").read_text(encoding="utf-8")
    iris = iris.replace('"knos-iris.mp4"', '"../iris/knos-iris.mp4"').replace('poster="poster.png"', 'poster="../iris/poster.png"')
    # the labs page opens on its own heading (its section names the check inside IRIS)
    iris, n = re.subn(r"<!-- k-first -->.*?<!-- /k-first -->", '<h1 class="k-first" id="k-first">For labs</h1>', iris, count=1, flags=re.S)
    assert n == 1, "the IRIS page has no first block"
    iris = retitle(iris, "Knos for labs: the check inside InterSystems IRIS", "The proof check inside a lab's own InterSystems IRIS, with its install steps and video.")
    (out / "labs").mkdir(exist_ok=True)
    (out / "labs" / "index.html").write_text(with_header(iris, "../", "labs/"), encoding="utf-8")
    # the checker as entered at Colosseum: the tag's page and files, under the one header, dated as the build
    chk = (ROOT / "web" / "check-v0328" / "index.html").read_text(encoding="utf-8")
    built = re.search(r'datetime="(\d{4}-\d{2}-\d{2})"', (out / "check" / "index.html").read_text(encoding="utf-8"))
    chk = chk.replace("KNOS_BUILD_DATE", built.group(1) if built else "2026-11-12")
    chk, n = re.subn(r'<header class="bar">.*?</header>', lambda m: header("../", "check/"), chk, count=1, flags=re.S)
    assert n == 1, "the check page has no header to replace"
    chk = chk.replace("</head>", f'<style id="kh-css">\n{CSS}</style>\n</head>', 1)
    (out / "check" / "index.html").write_text(chk, encoding="utf-8")
    for f in (ROOT / "web" / "check-v0328").rglob("*.js"):   # the tag's check.js and every module it loads (share, badge, motion)
        to = out / "check" / f.relative_to(ROOT / "web" / "check-v0328")
        to.parent.mkdir(parents=True, exist_ok=True)
        to.write_bytes(f.read_bytes())
    head = head_of(door)
    (out / "near" / "index.html").write_text(redirect("../prove/", head), encoding="utf-8")
    (out / "iris" / "index.html").write_text(redirect("../labs/", head), encoding="utf-8")
    site_product.HEADER_CSS = CSS
    made = site_product.write(out, header)
    (out / "tools.html").write_text(redirect("./", head), encoding="utf-8")   # linked from earlier posts: sends to the front door
    beacon(out)
    gone = sweep(out)
    print(f"product pages: the front door, {len(made) + 2} pages ({', '.join(['prove/', 'labs/'] + made)}); near/ and iris/ send on; {gone} older pages send to the front door")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--sweep"]:
        print(f"older pages sent to the front door: {sweep(Path(sys.argv[2]))}")
        sys.exit(0)
    sys.exit(main(sys.argv[1]))
