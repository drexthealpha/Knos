"""Qloo's own measured contribution: the 10 research tasks of the IDT benchmark (r01-r10), each Ready
brief run twice through the same model and effort, once as it is and once with a "Grounding (Qloo)" line made from a live
demand check of that brief's own product (Qloo's audience, cities, price tier and comparables).

    python scripts/qloo_bench.py [--model sonnet] [--effort medium] [--only r01,r07] [--out docs/idt]

Measured with `claude -p --output-format json` (Claude Code print mode on the operator's subscription; never --bare),
exactly as scripts/idt_bench.py measures the IDT ratio: output tokens and the cost estimate as the API returned them, pass
or fail by the same check (the brief is Ready), each run cross-checked against its session transcript in
~/.claude/projects. The demand check needs QLOO_API_KEY (and QLOO_BASE_URL) in the environment; nothing prints it.
The IDT ratio is Knos's own (clear briefs), not Qloo's; this file measures only what the Qloo line adds, whatever it is.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "apps" / "wanted"))
sys.path.insert(0, str(ROOT / "scripts"))

import idt_bench as B  # noqa: E402


def product(ready: str) -> str:
    """The product a Ready brief is for: "Make a Knos brief for <this>. Output ..." (the paper reference dropped)."""
    m = re.match(r"\s*Make a Knos brief (?:for|to) (.+?)\. Output", ready, re.S)
    text = m.group(1) if m else ready[:120]
    return re.sub(r"\s*\([^)]*\)", "", text).strip()[:200]


def grounding(idea: str) -> tuple[dict, str | None]:
    """A live demand check of the product: the Qloo facts the brief would be grounded on, and the report's hash."""
    from knos_wanted import check
    rep = check.demand_check(idea)
    plan = ((rep.get("decision") or {}).get("plan") or {})
    who = plan.get("who") or {}
    g = {"audience": {k: who.get(k) for k in ("age", "gender") if who.get(k)} | (
             {"segments": who.get("segments")[:3]} if who.get("segments") else {}),
         "launch_cities": (plan.get("where") or [])[:3], "price_tier": plan.get("tier"),
         "comparables": [m["name"] for m in (rep.get("matches") or []) if m.get("name")][:4]}
    if not g["audience"]:
        w = rep.get("who") or {}
        g["audience"] = {k: v for k, v in (("age", w.get("top_age")), ("gender", w.get("top_gender"))) if v}
    if not g["launch_cities"]:
        g["launch_cities"] = [c["name"] for c in (rep.get("cities") or []) if c.get("name")][:3]
    return {k: v for k, v in g.items() if v}, rep.get("hash")


def with_line(ready: str, g: dict) -> str:
    """The same brief, with the line every agent on a grounded milestone is handed (knos.idt.agent_prompt's form)."""
    return ready + "\nGrounding (Qloo): " + json.dumps(g, separators=(",", ":"), ensure_ascii=False)


def summary(rows: list[dict], model: str, effort: str) -> dict:
    ok = [r for r in rows if not r["without"].get("error") and not r["with"].get("error")]
    tot = lambda side, k: sum((r[side].get(k) or 0) for r in ok)  # noqa: E731
    out_wo, out_w = tot("without", "output_tokens"), tot("with", "output_tokens")
    return {"v": 1, "tasks": len(ok), "model": model, "effort": effort,
            "measured_with": "claude -p --output-format json (Claude Code print mode, the operator's subscription); usage as the API returned it",
            "without_output_tokens": out_wo, "with_output_tokens": out_w, "delta_output_tokens": out_w - out_wo,
            "delta_share": round((out_w - out_wo) / out_wo, 3) if out_wo else None,
            "without_pass": sum(bool(r["without"].get("passed")) for r in ok), "with_pass": sum(bool(r["with"].get("passed")) for r in ok),
            "without_cost_usd": round(tot("without", "cost_usd"), 4), "with_cost_usd": round(tot("with", "cost_usd"), 4),
            "transcripts_match": all(r[s].get("transcript_matches") for r in ok for s in ("without", "with")),
            "rows": [{"task": r["task"], "product": r["product"], "without_output_tokens": r["without"].get("output_tokens"),
                      "with_output_tokens": r["with"].get("output_tokens"), "without_passed": r["without"].get("passed"),
                      "with_passed": r["with"].get("passed"), "without_cost_usd": r["without"].get("cost_usd"),
                      "with_cost_usd": r["with"].get("cost_usd"), "grounded_on": r["grounding"]} for r in ok],
            "qloo_data": "not kept here: Qloo's answers stay server side; each line is named by its fields and sha256",
            "honest": "the Qloo line's effect on reasoning tokens and on Ready briefs for these 10 tasks, whatever it is; "
                      "the IDT ratio is Knos's own and is not credited to Qloo"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default=str(ROOT / "docs" / "idt"))
    a = ap.parse_args(argv)
    tasks = [t for t in json.loads((ROOT / "bench" / "idt" / "tasks.json").read_text(encoding="utf-8"))["tasks"] if t["id"].startswith("r")]
    if a.only:
        tasks = [t for t in tasks if t["id"] in a.only.split(",")]
    out = Path(a.out)
    rows = []
    cwd = Path(tempfile.mkdtemp(prefix="knos-qloo-bench-"))
    for t in tasks:
        idea = product(t["ready"])
        g, h = grounding(idea)
        line = json.dumps(g, separators=(",", ":"), ensure_ascii=False)
        # Qloo's answers stay server side: the committed run names the line by its fields and hash, never its values
        row = {"task": t["id"], "product": idea, "grounding": {"fields": sorted(g), "sha256": hashlib.sha256(line.encode()).hexdigest()}}
        for side, brief in (("without", t["ready"]), ("with", with_line(t["ready"], g))):
            r = B.run(brief, a.model, a.effort, cwd)
            if not r.get("error"):
                r["passed"], r["why"] = B.check(t, r.get("reply") or "")
                tu = B.transcript_usage(r["session_id"]) if r.get("session_id") else None
                r["transcript_output_tokens"] = (tu or {}).get("output_tokens")
                r["transcript_matches"] = bool(tu) and tu["output_tokens"] == r["output_tokens"]
            r.pop("reply", None)
            row[side] = r
            print(t["id"], side, r.get("output_tokens"), "passed" if r.get("passed") else f"failed: {r.get('why') or r.get('error')}", flush=True)
        rows.append(row)
    out.mkdir(parents=True, exist_ok=True)
    (out / "qloo_runs.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    s = summary(rows, a.model, a.effort)
    (out / "qloo_summary.json").write_text(json.dumps(s, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in s.items() if k != "rows"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
