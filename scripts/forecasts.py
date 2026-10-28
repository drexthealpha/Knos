"""The forecast ledger (/forecasts/ on the front door): for each recorded idea with a recorded model answer, Knos's city
and pre-order target, the model-alone city, a placebo city and the date made, graded later by
docs/reference/forecast_plan.md, whose sha256 the page shows. Read from the private recordings as the app loads them
(knos_wanted.recorded); what it writes holds derived values only (city names, targets, dates), never a Qloo answer.

    python scripts/forecasts.py <private recordings file>            write web/forecasts/index.html and docs/reference/forecasts.json
    python scripts/forecasts.py <private recordings file> --check    exit 1 when either differs
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps" / "wanted"), str(ROOT / "src")]
PLAN = ROOT / "docs" / "reference" / "forecast_plan.md"
DATA = ROOT / "docs" / "reference" / "forecasts.json"
PAGE = ROOT / "web" / "forecasts" / "index.html"
CRUMBS = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
    {"@type": "ListItem", "position": 1, "name": "Knos", "item": "https://drexthealpha.github.io/Knos/"},
    {"@type": "ListItem", "position": 2, "name": "Forecasts", "item": "https://drexthealpha.github.io/Knos/forecasts/"}]}
ORDER = ["a solar powered music festival", "an ai recipe planner for families", "a crypto podcast for beginners", "a probiotic kombucha brand",
         "a recycled ocean plastic swimwear brand", "a quantum physics book for kids", "a smart water bottle that glows to remind you to drink"]


def rows(file: str) -> list[dict]:
    os.environ["KNOS_RECORDED_FILE"] = file
    from knos_wanted import metros, recorded
    recorded.load()
    pool = {recorded.key(v.get("idea") or ""): v for v in [*recorded._answered.values(), *recorded._last.values()]}
    rng, out = random.Random(4), []
    for idea in ORDER:
        r = pool[recorded.key(idea)]
        t = metros.launch_terms(r)
        named = [c.get("name") for c in r.get("cities") or [] if isinstance(c, dict) and c.get("name")]
        candidates = sorted({m.get("city") for m in (r.get("terms") or {}).get("metros") or [] if m.get("city")} or set(named))
        out.append({"idea": idea, "made": str(r.get("made") or "")[:10],
                    "knos": {"city": t["city"] if t else (named[0] if named else None), "target": t["target"] if t else None,
                             "from": "launch terms" if t else "Qloo's first named city"},
                    "model": (r.get("model_alone") or {}).get("city"),
                    "placebo": rng.choice(candidates) if candidates else None, "candidates": len(candidates)})
    return out


def page(rs: list[dict], sha: str) -> str:
    e = lambda v: html.escape("none" if v is None else str(v))  # noqa: E731
    target = lambda r: "" if r["knos"]["target"] is None else " (target " + e(r["knos"]["target"]) + " pre-orders)"  # noqa: E731
    body = "\n".join(f'        <tr data-idea="{e(r["idea"])}"><td data-h="Idea">{e(r["idea"])}</td><td data-h="Knos with Qloo">{e(r["knos"]["city"])}'
                     f'{target(r)}</td><td data-h="Model alone">{e(r["model"])}</td>'
                     f'<td data-h="Placebo">{e(r["placebo"])}</td><td data-h="Made">{e(r["made"])}</td></tr>' for r in rs)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Knos. Forecasts</title>
<meta name="description" content="Where Knos, the model alone and a placebo say each recorded idea's business is densest, written down before the Census counts them.">
<meta name="author" content="drexthealpha">
<link rel="canonical" href="https://drexthealpha.github.io/Knos/forecasts/">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#07080c">
<meta name="theme-color" content="#f4f4f0" media="(prefers-color-scheme: light)">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Knos">
<meta property="og:title" content="Knos. Forecasts">
<meta property="og:url" content="https://drexthealpha.github.io/Knos/forecasts/">
<meta property="og:image" content="https://drexthealpha.github.io/Knos/brand/card.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="stylesheet" href="../brand/tokens.css">
<link rel="stylesheet" href="../app.css">
<!-- written by scripts/forecasts.py from the private recordings: derived values only -->
<script type="application/ld+json">{json.dumps(CRUMBS)}</script>
<style>
:where(a[href]){{padding-block:max(0px,calc((24px - 1em) / 2))}}
.fc .k-table{{overflow-x:auto}}
@media (max-width: 479.98px) {{
  .fc .k-table thead {{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }}
  .fc .k-table table, .fc .k-table tbody, .fc .k-table tr, .fc .k-table td {{ display: block; min-width: 0; width: auto; }}
  .fc .k-table tr {{ border: 1px solid var(--line); border-radius: var(--radius, 8px); padding: 8px 12px; margin: 0 0 8px; }}
  .fc .k-table td {{ border: 0; padding: 2px 0; overflow-wrap: anywhere; }}
  .fc .k-table td[data-h]::before {{ content: attr(data-h) ": "; color: var(--muted); }}
}}
</style>
<link rel="icon" href="../icon.svg" type="image/svg+xml">
<link rel="icon" href="../favicon.ico" sizes="16x16 32x32 48x48">
<link rel="apple-touch-icon" href="../brand/apple-touch-icon.png">
</head>
<body>
<header class="bar">
  <a class="brand" href="../" aria-label="Knos home"><span class="wordmark" aria-hidden="true"></span><span class="name">Knos</span></a>
</header>
<main>
  <section class="view fc">
    <h1>Forecasts</h1>
    <h2>Where is each idea's business densest?</h2>
    <p>Three answers per idea, written down before the Census counts the businesses. The placebo draws from Knos's own candidate cities.</p>
    <div class="k-table"><table>
      <thead><tr><th scope="col">Idea</th><th scope="col">Knos with Qloo</th><th scope="col">Model alone</th><th scope="col">Placebo</th><th scope="col">Made</th></tr></thead>
      <tbody>
{body}
      </tbody>
    </table></div>
    <h2>How is it graded?</h2>
    <p>By the plan fixed before this page: Census County Business Patterns 2024, hit at 5 by establishments per resident. <a href="https://github.com/drexthealpha/Knos/blob/main/docs/reference/forecast_plan.md" rel="noopener">The plan</a>, sha256 <code data-plan-sha>{sha}</code>.</p>
    <p class="fine">The Census has set no release date for 2024 yet, so no grade is shown.</p>
  </section>
</main>
<footer class="foot">
  <span>Devnet is test mode: the money is test USDC.</span>
  <span><a href="../">Knos home</a> · <a href="../proof/">Proof</a> · <a href="../status/">Status</a> · <a href="https://github.com/drexthealpha/Knos">Source (MIT)</a></span>
</footer>
</body>
</html>
"""


def main(argv: list[str]) -> int:
    rs = rows(argv[0])
    sha = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    data = json.dumps({"about": "derived values only: each recorded idea's three forecast cities, Knos's target and the date made",
                       "plan": "docs/reference/forecast_plan.md", "plan_sha256": sha, "rows": rs}, indent=1, ensure_ascii=False) + "\n"
    new = page(rs, sha)
    if "--check" in argv:
        same = DATA.is_file() and DATA.read_text(encoding="utf-8") == data and PAGE.is_file() and PAGE.read_text(encoding="utf-8") == new
        print("forecasts are current" if same else "forecasts differ: run python scripts/forecasts.py <file>")
        return 0 if same else 1
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(data, encoding="utf-8", newline="\n")
    PAGE.write_text(new, encoding="utf-8", newline="\n")
    print(f"{len(rs)} ideas written; plan sha256 {sha[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
