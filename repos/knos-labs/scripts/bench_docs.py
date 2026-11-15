"""Write every benchmark number in the docs from docs/bench.json, the one source.

    python scripts/bench_docs.py           rewrite the marked blocks
    python scripts/bench_docs.py --check   exit 1 if a doc has drifted from the source (the test suite runs this)

A block is `<!-- bench:NAME -->` ... `<!-- /bench:NAME -->` in README.md, docs/BENCH.md or docs/WHY.md.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "docs/BENCH.md", "docs/WHY.md"]
RETIRED = ["acceptance-headline", "acceptance-table", "models"]  # modelled or headline numbers, removed from every doc


def blocks(src: dict) -> dict[str, str]:
    rc = src["recall"]
    recall = [f"{rc['benchmark']}, measured {rc['date']}.", "",
              "| | baseline (0.3.1) | dev | **held-out** |", "|---|---|---|---|"]
    recall += [f"| {r['what']} | {r['baseline']} | {r['dev']} | **{r['heldout']}** |" for r in rc["rows"]]
    out = {"recall-table": "\n".join(recall)}
    if src.get("market"):
        m = src["market"]
        out["market"] = (market_index(m["index"]) + "\n\n" if m.get("index") else "") + m["sentence"]
    return out


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def market_index(ix: dict) -> str:
    """The Agent PR Index scan (scripts/agent_pr_index.py): shares with 95% Wilson intervals, per agent and overall."""
    o = ix["overall"]
    lines = [f"**Agent PR Index, {ix['date']}:** {ix['n_prs']:,} PRs by AI coding agents claiming tests or CI pass "
             f"(created {ix['window'][0]} – {ix['window'][1]}); {ix['excluded_self_repo']:,} PRs on repos owned by "
             f"the PR's author or the human who assigned the agent were excluded. Of the {o['claimed_green']:,} whose "
             f"CI had finished at the head commit, **{o['actually_failed']:,} ({_pct(o['share'])}) had a failing "
             f"check** (95% Wilson interval {_pct(o['ci95'][0])}–{_pct(o['ci95'][1])}). Published as `index.json` "
             f"on the Pages site; built every 6 hours by `.github/workflows/index.yml`.", "",
             "| agent | claiming PRs with finished CI | CI failed | 95% interval |", "|---|---|---|---|"]
    for label, a in ix["agents"]:
        if a["claimed_green"]:
            lines.append(f"| {label} | {a['claimed_green']:,} | {a['actually_failed']:,} ({_pct(a['share'])}) | "
                         f"{_pct(a['ci95'][0])}–{_pct(a['ci95'][1])} |")
    lines.append(f"| **all** | **{o['claimed_green']:,}** | **{o['actually_failed']:,} ({_pct(o['share'])})** | "
                 f"**{_pct(o['ci95'][0])}–{_pct(o['ci95'][1])}** |")
    return "\n".join(lines) + "\n\nEarlier sample (0.3.4):"


def apply(text: str, gen: dict[str, str]) -> str:
    def repl(m):
        name = m.group(1)
        return f"<!-- bench:{name} -->\n{gen[name]}\n<!-- /bench:{name} -->" if name in gen else m.group(0)
    text = re.sub(r"<!-- bench:([\w-]+) -->.*?<!-- /bench:\1 -->", repl, text, flags=re.S)
    # Retired blocks are removed outright and never regenerated.
    for name in RETIRED:
        text = re.sub(rf"(?:- )?<!-- bench:{name} -->.*?<!-- /bench:{name} -->\n\n?", "", text, flags=re.S)
    return text


def main(check: bool = False) -> int:
    gen = blocks(json.loads((ROOT / "docs" / "bench.json").read_text(encoding="utf-8")))
    drift = []
    for d in DOCS:
        p = ROOT / d
        old = p.read_text(encoding="utf-8")
        new = apply(old, gen)
        if new != old:
            drift.append(d)
            if not check:
                p.write_text(new, encoding="utf-8")
    if check and drift:
        print("benchmark numbers drifted from docs/bench.json in: " + ", ".join(drift))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--check" in sys.argv))
