"""The page of one crossing, for the front door (web/crossing/<id>/index.html): the demand behind it, the hashed Ready
brief (the hash recomputed here from the brief the project holds), each pre-order held on devnet, the check that
counted them, and each release with what released it, read from its own transaction. Static: it asks nothing when read.

    python scripts/crossing_page.py <project id> [--check]
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "apps" / "wanted")]
from knos import chain, ready  # noqa: E402

APP = "https://knos.onrender.com"
TX = "https://explorer.solana.com/tx/{}?cluster=devnet"
ADDR = "https://explorer.solana.com/address/{}?cluster=devnet"
# what the demand check said for this idea: the D2 run (scripts/test_qloo_sets_terms.py, live Qloo, 24-25 Oct 2026)
DEMAND = {"7b4ed16b8c2903dc": {"idea": "a graphene-coated cycling jacket", "city": "Boulder, CO", "cells": 3,
                               "population": 326_831, "target": 10, "when": "24-25 Oct 2026",
                               "script": "https://github.com/drexthealpha/Knos/blob/main/scripts/test_qloo_sets_terms.py"}}


# Qloo's launch cities for the idea as the D2 run kept them (its log keeps each idea's top metro only), and the second
# worked example: of the D2 run's ideas, the largest target at or below 200 where the floor of 10 does not bind
LAUNCH = {"7b4ed16b8c2903dc": [{"city": "Boulder, CO", "raw": 3, "cells": 3, "population": 326_831}]}
SECOND = {"idea": "a smart water bottle that glows to remind you to drink", "city": "New York-Newark-Jersey City, NY-NJ",
          "raw": 195, "cells": 3, "population": 19_498_249}


def target(raw: int) -> tuple[int, int]:
    """D2's pre-order target, max(10, round(population / 100,000 x mean affinity)), from the formula's own value as the
    run recorded it (Qloo's affinity stays on the app's server, never in the site)."""
    return max(10, raw), raw


def targets_table(rows: list[dict]) -> str:
    """One row per launch city: its population and target; "floor" where max(10, ...) binds."""
    body = []
    for r in rows:
        t, raw = target(r["raw"])
        mark = f' <span class="floor" title="the formula gives {raw}; the floor of 10 binds">floor</span>' if raw < 10 else ""
        body.append(f'<tr data-pop="{r["population"]}" data-t="{t}"><td>{html.escape(r["city"])}</td>'
                    f'<td>{r["population"]:,}</td><td><b>{t}</b>{mark}</td></tr>')
    return ('<div class="tw"><table class="targets"><thead><tr><th scope="col">Launch city</th>'
            f'<th scope="col">Population</th><th scope="col">Target</th></tr></thead><tbody>{"".join(body)}</tbody></table></div>')


def get(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "knos-crossing-page"}), timeout=120) as r:
        return json.loads(r.read())


def tx(sig: str) -> dict | None:
    return chain.call(chain.DEVNET_URL, "getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])


def facts(pid: str) -> dict:
    from knos_wanted.server import released_by
    from knos_wanted.valley import _brief
    p = get(f"{APP}/api/project?id={pid}")
    m = p["milestones"][0]
    brief = _brief(p)
    rows = []
    for o in m["orders"]:
        lock, rel = (o.get("signatures") or {}).get("lock"), (o.get("signatures") or {}).get("referee_group_pass")
        lt, rt = tx(lock) if lock else None, tx(rel) if rel else None
        rows.append({"order": o["order"], "wallet": o["funder"], "units": o["units"], "status": o["status"],
                     "lock": lock, "lock_ok": bool(lt) and (lt.get("meta") or {}).get("err") is None,
                     "release": rel, "release_ok": bool(rt) and (rt.get("meta") or {}).get("err") is None,
                     "released_by": released_by(rt), "check_run": (o.get("trust") or {}).get("run")})
    said = [h["what"] for h in m["history"]]
    ci = next((re.search(r"at ([0-9a-f]{12})", w).group(1) for w in said if "passed in CI" in w), None)
    return {"project": pid, "title": p["title"], "milestone": m, "status": m["status"], "brief": brief,
            "criteria_hash": p["ready"]["criteria_hash"], "recomputed": ready.criteria_hash(brief), "orders": rows,
            "ci_commit": ci, "demand": DEMAND.get(pid), "wallets": sorted({r["wallet"] for r in rows})}


def page(f: dict) -> str:
    e = html.escape
    d, m = f["demand"], f["milestone"]
    t = d["target"]
    rows = "".join(
        f'<tr><td>{i}</td><td><a href="{ADDR.format(r["wallet"])}">{e(r["wallet"][:6])}…</a></td><td>{r["units"]}</td>'
        f'<td><a href="{TX.format(r["lock"])}">held</a></td>'
        f'<td>{f"""<a href="{TX.format(r["release"])}">{e(r["released_by"] or "released")}</a>""" if r["release"] else e(r["status"])}</td></tr>'
        for i, r in enumerate(f["orders"], 1))
    run = next((r["check_run"] for r in f["orders"] if r["check_run"]), None)
    same = f["criteria_hash"] == f["recomputed"]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Knos. One crossing: {e(d["idea"])}</title>
<meta name="description" content="One idea carried from a demand check to a hashed brief, pre-orders held on Solana devnet and their release on proof.">
<link rel="canonical" href="https://drexthealpha.github.io/Knos/crossing/{e(f["project"])}/">
<meta name="color-scheme" content="light dark">
<link rel="stylesheet" href="../../brand/tokens.css">
<link rel="icon" href="../../icon.svg" type="image/svg+xml">
<style>body{{margin:0;background:var(--paper);color:var(--ink);font:400 var(--s0)/1.5 var(--text)}}main{{max-width:960px;margin:0 auto;padding:16px 16px 48px}}
h1{{font:600 var(--s3)/1.15 var(--head);margin:8px 0 12px}}h2{{font:600 var(--s1)/1.3 var(--head);margin:28px 0 8px}}.mono{{font-family:var(--mono);overflow-wrap:anywhere}}
table{{border-collapse:collapse;width:100%;font-size:var(--s-1)}}td,th{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left}}.tw{{overflow-x:auto}}.floor{{font-size:var(--s-1);padding:1px 6px;border:1px solid var(--line);border-radius:99px;margin-left:4px}}.fine{{color:var(--muted);font-size:var(--s-1)}}</style>
</head>
<body>
<main>
<p class="fine"><a href="../../">Knos</a> · <a href="../../try/">Try it</a></p>
<h1>{e(d["idea"])}</h1>
<ol>
<li id="demand"><h2>Demand</h2><p>Qloo's heatmap: <b>{e(d["city"])}</b> over {d["cells"]} cells, population {d["population"]:,}.
Target = max(10, round({d["population"]:,} / 100,000 × mean affinity)) = <b>{t}</b> pre-orders.</p>
<p class="fine">Recorded from a live demand check, {e(d["when"])} (<a href="{e(d["script"])}">the run</a>). Qloo has refused Knos's key since 25 Oct.</p></li>
<li><h2>Ready brief</h2><p>{e(m["name"])}: {e(m["target"])}. Checked by <span class="mono">{e(m["verifier"]["check"])}</span>.</p>
<p>Criteria hash <span class="mono">{e(f["criteria_hash"])}</span>. {"Recomputed here from the brief: the same." if same else "Recomputed here from the brief: different."}</p></li>
<li><h2>Money held</h2><p>{len(f["orders"])} pre-orders of 5 test units each, from {len(f["wallets"])} test wallets of Knos, held on Solana devnet.</p></li>
<li><h2>Paid on proof</h2><p>The check counted them on devnet{f' at <span class="mono">{e(f["ci_commit"])}</span>' if f["ci_commit"] else ""}{f' (<a href="{e(run)}">the signing run</a>)' if run else ""}. Milestone: {e(f["status"])}.</p></li>
</ol>
<section id="targets"><h2>Targets in Qloo's launch cities</h2>{targets_table(LAUNCH.get(f["project"], []))}
<p class="fine">The run kept the top launch city for each idea. A larger city raises the target: the same formula in the next example.</p>
<h3>{e(SECOND["idea"])}</h3>{targets_table([SECOND])}
<p class="fine">Target = max(10, round({SECOND["population"]:,} / 100,000 × mean affinity)) = {target(SECOND["raw"])[0]}, from the same run.</p></section>
<div class="tw"><table><thead><tr><th>#</th><th>Wallet</th><th>Units</th><th>Held</th><th>Released</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="fine">Devnet, test money. The wallets are Knos's own test wallets; where their owners live is not checked on chain.</p>
</main>
</body>
</html>
"""


def main(pid: str, check: bool = False) -> int:
    f = facts(pid)
    old = ROOT / "web" / "crossing" / pid / "facts.json"
    if old.is_file():                                 # a signing run the app no longer holds (a redeploy) stays as published
        was = {o["order"]: o for o in json.loads(old.read_text(encoding="utf-8")).get("orders") or []}
        for o in f["orders"]:
            if not o.get("check_run") and (was.get(o["order"]) or {}).get("check_run"):
                o["check_run"] = was[o["order"]]["check_run"]
    ok = (f["criteria_hash"] == f["recomputed"] and all(r["lock_ok"] for r in f["orders"])
          and all(r["release_ok"] and r["released_by"] for r in f["orders"]) and f["status"] == "released")
    out = ROOT / "web" / "crossing" / pid / "index.html"
    if not check:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page(f), encoding="utf-8", newline="\n")
        (out.parent / "facts.json").write_text(json.dumps({k: v for k, v in f.items() if k != "milestone"}, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"hash": f["criteria_hash"], "recomputed_same": f["criteria_hash"] == f["recomputed"], "orders": len(f["orders"]),
                      "locks_ok": sum(r["lock_ok"] for r in f["orders"]), "releases_ok": sum(r["release_ok"] for r in f["orders"]),
                      "labels": sorted({str(r["released_by"]) for r in f["orders"]}), "wallets": len(f["wallets"]), "status": f["status"], "ok": ok}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], "--check" in sys.argv))
