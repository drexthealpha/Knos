"""The six sample results as static pages, /results/<id>/ on the front door: each card's text in the served HTML (the
verdict, the model's city beside Qloo's, the launch terms, what would flip it, what Knos rejected), so a reader or a
crawler with no JavaScript reads it. Read from the private recordings as the app loads them (knos_wanted.recorded);
derived values only, never a Qloo answer.

    python scripts/results_pages.py <private recordings file>            write web/results/<id>/index.html and web/results/index.json
    python scripts/results_pages.py <private recordings file> --check    exit 1 when any differs
"""
from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps" / "wanted"), str(ROOT / "src")]
OUT = ROOT / "web" / "results"
SITE = "https://drexthealpha.github.io/Knos/"
WORD = {"OPEN": "Open for pre-orders", "REFUSE": "Not yet: pre-orders stay closed", "CANNOT_DECIDE": "Qloo cannot decide this one"}


def cards(file: str) -> list[dict]:
    os.environ["KNOS_RECORDED_FILE"] = file
    from knos_wanted import metros, recorded
    recorded.load()
    out = []
    for chip in recorded.CHIPS:
        r = recorded._last.get(recorded.key(chip))
        if not r:
            continue
        t = metros.launch_terms(r)
        v = (r.get("decision") or {}).get("verdict")
        word = "Not yet: Qloo sets no launch city for this idea" if v == "OPEN" and not t else WORD.get(v, str(v))
        g = r.get("gap") or {}
        who = r.get("who") or {}
        out.append({"id": str(r.get("hash") or "")[:16], "idea": r.get("idea") or chip, "made": str(r.get("made") or "")[:10], "word": word,
                    "sentence": g.get("sentence"), "flip": (g.get("flip") or {}).get("said"), "rejected": g.get("rejected") or [],
                    "terms": {"city": t["city"], "target": t["target"], "rule": t["rule"]} if t else None,
                    "cities": [c.get("name") for c in r.get("cities") or [] if isinstance(c, dict) and c.get("name")][:5],
                    "who": ", ".join(x for x in (str(who.get("top_age") or "").replace("_", " "), str(who.get("top_gender") or "")) if x),
                    "calls": len(r.get("calls") or []), "headline": g.get("headline")})
    return out


def _cap(t: str) -> str:
    return t[:1].upper() + t[1:]


def page(c: dict) -> str:
    e = html.escape
    url = f"{SITE}results/{c['id']}/"
    crumbs = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Knos", "item": SITE},
        {"@type": "ListItem", "position": 2, "name": "Results", "item": f"{SITE}results/"},
        {"@type": "ListItem", "position": 3, "name": c["idea"], "item": url}]}
    where = (f"Launch in {e(c['terms']['city'])}: {e(str(c['terms']['target']))} pre-orders. {e(c['terms']['rule'])}" if c["terms"]
             else "No launch city: Qloo gave no heatmap for this idea, so pre-orders cannot open." + (f" The cities Qloo named: {e(', '.join(c['cities']))}." if c["cities"] else ""))
    rej = "; ".join(f"{e(o['name'])} ({e(o['code'])}: {e(o['why'])})" for o in c["rejected"]) or "none, as Qloo offered no city or product to weigh"
    head = c.get("headline") or {}
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Knos. {e(c['idea'])}</title>
<meta name="description" content="{e(c['word'])}. {e(c['sentence'] or '')}">
<meta name="author" content="drexthealpha">
<link rel="canonical" href="{url}">
<meta name="color-scheme" content="light dark">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Knos">
<meta property="og:title" content="Knos. {e(c['idea'])}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}brand/card.png">
<link rel="stylesheet" href="../../brand/tokens.css">
<link rel="stylesheet" href="../../app.css">
<script type="application/ld+json">{json.dumps(crumbs, ensure_ascii=False)}</script>
<link rel="icon" href="../../icon.svg" type="image/svg+xml">
</head>
<body>
<header class="bar">
  <a class="brand" href="../../" aria-label="Knos home"><span class="wordmark" aria-hidden="true"></span><span class="name">Knos</span></a>
</header>
<main>
  <article class="view" data-result="{e(c['id'])}">
    <h1>{e(c['idea'])}</h1>
    <p class="k-verdict-line"><b>{e(c['word'])}.</b> Recorded {e(c['made'])} from {c['calls']} Qloo calls.</p>
    <h2>What does Qloo say beside the model alone?</h2>
    <p>{e(c['sentence'] or 'No model answer was recorded for this idea.')}</p>
    {f'<p class="fine"><a href="{e(head["href"])}">{e(head["said"])}</a></p>' if head else ''}
    <h2>Where would it launch?</h2>
    <p>{where}</p>
    <h2>Who wants it?</h2>
    <p>{e(('Qloo reads ' + c['who'] + ' as the core audience.') if c['who'] else 'Qloo named no age or gender for it.')}</p>
    <h2>What would flip this verdict?</h2>
    <p>{e(_cap((c['flip'] or '').removeprefix('What would flip this verdict: ')))}</p>
    <h2>What did Knos reject?</h2>
    <p>{rej}.</p>
    <p><a href="https://knos.onrender.com/r/{e(c['id'])}">The full card, its calls and its receipt</a></p>
  </article>
</main>
<footer class="foot">
  <span>Devnet is test mode: the money is test USDC. Aggregate taste from Qloo, never about one person.</span>
  <span><a href="../../">Knos home</a> · <a href="../../proof/">Proof</a> · <a href="../../status/">Status</a></span>
</footer>
</body>
</html>
"""


def main(argv: list[str]) -> int:
    cs = cards(argv[0])
    files = {OUT / c["id"] / "index.html": page(c) for c in cs}
    files[OUT / "index.json"] = json.dumps({"about": "the sample results' static pages (scripts/results_pages.py)",
                                            "results": [{"id": c["id"], "idea": c["idea"], "path": f"results/{c['id']}/"} for c in cs]}, indent=1, ensure_ascii=False) + "\n"
    if "--check" in argv:
        same = all(f.is_file() and f.read_text(encoding="utf-8") == t for f, t in files.items())
        print("result pages are current" if same else "result pages differ: run python scripts/results_pages.py <file>")
        return 0 if same else 1
    for f, t in files.items():
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(t, encoding="utf-8", newline="\n")
    print(f"{len(cs)} result pages written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
