"""The forecast ledger (/forecasts/ on the front door), second plan (docs/reference/forecast_plan_v2.md): each recorded
idea with its NAICS code, its three forecast counties (Knos's, the model's with no Qloo data, a placebo), the grading
date and the source. Knos's picks come from Qloo's answers, so they are never in the site: the page reads the rows
from the app's server when it is viewed (GET /api/forecasts) and recomputes their sha256 in the browser against the
plan's. What this writes holds the public part only: the ideas, codes, the model's and the placebo's counties.

    python scripts/forecasts.py <private forecast rows (forecasts_v2.json)>           write the page and docs/reference/forecasts.json
    python scripts/forecasts.py <private forecast rows> --check                       exit 1 when either differs
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "reference" / "forecast_plan_v2.md"
DATA = ROOT / "docs" / "reference" / "forecasts.json"
PAGE = ROOT / "web" / "forecasts" / "index.html"
GRADE_DAY = "2 Dec 2026"
SOURCE = "https://data.bls.gov/cew/data/api/2026/2/industry/{naics}.csv"
CALENDAR = "https://www.bls.gov/cew/release-calendar.htm"
CRUMBS = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
    {"@type": "ListItem", "position": 1, "name": "Knos", "item": "https://drexthealpha.github.io/Knos/"},
    {"@type": "ListItem", "position": 2, "name": "Forecasts", "item": "https://drexthealpha.github.io/Knos/forecasts/"}]}


def canon(rows: list[dict]) -> str:
    return json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def public(rows: list[dict]) -> list[dict]:
    return [{k: r[k] for k in ("idea", "made", "naics", "naics_name", "graded", "model", "placebo") if k in r}
            | ({"not_graded": r["not_graded"]} if r.get("not_graded") else {}) for r in rows]


def build(private: dict) -> tuple[str, str]:
    rows, e = private["rows"], html.escape
    sha = hashlib.sha256(canon(rows).encode("utf-8")).hexdigest()
    plan_text = PLAN.read_text(encoding="utf-8")
    assert sha in plan_text, "the rows are not the ones the plan fixed"
    plan_sha = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    pub = public(rows)
    data = json.dumps({"about": "the forecast ledger's public part: Knos's picks are read from the app's server (GET /api/forecasts)",
                       "plan": "docs/reference/forecast_plan_v2.md", "plan_sha256": plan_sha, "rows_sha256": sha, "grading_day": GRADE_DAY,
                       "rows": pub}, indent=1, ensure_ascii=False) + "\n"
    body = []
    for r in pub:
        src = SOURCE.format(naics=r["naics"])
        body.append(f'<tr data-idea="{e(r["idea"])}"><td>{e(r["idea"])}</td><td><span class="mono">{e(r["naics"])}</span> {e(r["naics_name"])}</td>'
                    f'<td data-knos>read from the app</td><td>{e((r.get("model") or {}).get("county") or "outside US data")}</td>'
                    f'<td>{e((r.get("placebo") or {}).get("county") or "not graded")}</td>'
                    f'<td>{e(GRADE_DAY) if r["graded"] else e(r.get("not_graded") or "not graded")}</td><td><a href="{e(src)}" rel="noopener">QCEW {e(r["naics"])}</a></td></tr>')
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Knos. Forecasts</title>
<meta name="description" content="Three forecasts for each recorded idea, fixed before the Bureau of Labor Statistics publishes the outcome on {GRADE_DAY}.">
<link rel="canonical" href="https://drexthealpha.github.io/Knos/forecasts/">
<meta name="color-scheme" content="light dark">
<link rel="stylesheet" href="../brand/tokens.css">
<link rel="icon" href="../icon.svg" type="image/svg+xml">
<script type="application/ld+json">{json.dumps(CRUMBS, ensure_ascii=False)}</script>
<style>body{{margin:0;background:var(--paper);color:var(--ink);font:400 var(--s0)/1.5 var(--text)}}main{{max-width:1100px;margin:0 auto;padding:16px 16px 48px}}
h1{{font:600 var(--s3)/1.15 var(--head);margin:8px 0 12px}}.mono{{font-family:var(--mono);overflow-wrap:anywhere}}.tw{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:var(--s-1)}}td,th{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
.fine{{font-size:var(--s-1);color:var(--muted)}}</style>
</head>
<body>
<main>
<p class="fine"><a href="../">Knos</a> · <a href="../proof/">Proof</a></p>
<h1>Forecasts</h1>
<p>Graded on {e(GRADE_DAY)}, when the Bureau of Labor Statistics publishes county business counts (<a href="{CALENDAR}" rel="noopener">its calendar</a>).</p>
<div class="tw"><table><thead><tr><th scope="col">Idea</th><th scope="col">NAICS</th><th scope="col">Knos</th><th scope="col">Model alone</th><th scope="col">Placebo</th><th scope="col">Graded</th><th scope="col">Source</th></tr></thead>
<tbody>{"".join(body)}</tbody></table></div>
<p class="fine" id="f-check" data-rows-sha256="{sha}" data-not-prose>Rows sha256 <span class="mono">{sha}</span>: <span id="f-match">reading the app</span></p>
<p class="fine">Plan <a href="https://github.com/drexthealpha/Knos/blob/main/docs/reference/forecast_plan_v2.md">forecast_plan_v2.md</a>, sha256 <span class="mono" id="f-plan">{plan_sha}</span>.</p>
</main>
<script>
(async () => {{
  const want = document.getElementById("f-check").dataset.rowsSha256, out = document.getElementById("f-match");
  try {{
    const doc = await fetch("https://knos.onrender.com/api/forecasts").then((r) => (r.ok ? r.json() : null));
    if (!doc || !Array.isArray(doc.rows)) {{ out.textContent = "the app did not answer"; return; }}
    const sort = (v) => Array.isArray(v) ? v.map(sort) : v && typeof v === "object" ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sort(v[k])])) : v;
    const bytes = new TextEncoder().encode(JSON.stringify(sort(doc.rows)));
    const got = [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((b) => b.toString(16).padStart(2, "0")).join("");
    out.textContent = got === want ? "the app's rows match the plan" : `the app's rows differ (${{got.slice(0, 12)}})`;
    out.dataset.match = String(got === want);
    for (const r of doc.rows) {{
      const cell = document.querySelector(`tr[data-idea="${{CSS.escape(r.idea)}}"] [data-knos]`);
      if (cell) cell.textContent = r.knos && r.knos.county ? r.knos.county : (r.not_graded || "outside US data");
    }}
  }} catch {{ out.textContent = "the app did not answer"; }}
}})();
</script>
</body>
</html>
"""
    return page, data


def main(argv: list[str]) -> int:
    private = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    page, data = build(private)
    if "--check" in argv:
        same = PAGE.read_text(encoding="utf-8") == page and DATA.read_text(encoding="utf-8") == data
        print("the forecast ledger is current" if same else "the forecast ledger differs: run python scripts/forecasts.py <rows>")
        return 0 if same else 1
    PAGE.write_text(page, encoding="utf-8", newline="\n")
    DATA.write_text(data, encoding="utf-8", newline="\n")
    assert not re.search(r'"knos"', data)
    print(f"{len(private['rows'])} forecast rows; rows sha256 {hashlib.sha256(canon(private['rows']).encode()).hexdigest()[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
