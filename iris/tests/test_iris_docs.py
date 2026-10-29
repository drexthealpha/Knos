"""I5 test_iris_readme, I7 test_iris_articles, I8 test_iris_one_product: the README's sections and the rules' items, the
two articles, and the one product's three links to iris/.

    python iris/tests/test_iris_docs.py readme|articles|one_product [result file] [the I1 result line]
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IRIS = ROOT / "iris"
ONE = "Knos carries research across the valley of death: see who wants it and where, then get paid only on proof."
LINK = "Proof checked inside IRIS for Health"
SECTIONS = ["What it decides", "Why it is technically interesting", "Requirements", "The image used", "LLM provider and key", "Start",
            "Check that it works", "Walkthrough of the three inputs", "The Workflow approval", "Solana devnet", "The trace",
            "Contest bonuses", "Platform findings", "Tests", "Architecture", "Known limitations", "How it fits Knos",
            "Developer Community profile and license"]


def readme(lines, i1: str) -> int:
    t = (IRIS / "README.md").read_text(encoding="utf-8")
    heads = re.findall(r"(?m)^## \d+\. (.+)$", t)
    fails = 0
    order = [h for h in heads if h in SECTIONS]
    ok = order == SECTIONS
    fails += not ok
    lines.append(f"{'ok  ' if ok else 'FAIL'} sections: {len(order)} of {len(SECTIONS)} of the build spec's 4.12, in its order")
    items = {"the image name": "irishealth-community:2026.3.0AI.154.0" in t, "load and retag": "scripts/load-image.sh" in t and "retag" in t,
             "the LLM provider and its variable": "KNOS_LLM_PROVIDER" in t and "ANTHROPIC_API_KEY" in t,
             "start": "docker compose up -d --build" in t, "health check": "/api/knos/health" in t,
             "IRIS never releases money alone": "IRIS never releases money alone" in t,
             "the Developer Community profile": "https://community.intersystems.com/user/zulqarnain-abubakar" in t,
             "the idea DPI-I-689, linked": "https://ideas.intersystems.com/ideas/DPI-I-689" in t,
             "the measured memory": bool(re.search(r"peak[^.\n]{0,80}\d+ MiB", t)),
             "the rules-against-agent table, the agent column needing a model key": "needs a model key" in t and "| Rules referee |" in t}
    for k, v in items.items():
        fails += not v
        lines.append(f"{'ok  ' if v else 'FAIL'} the rules' item: {k}")
    fresh = i1.startswith("PASS")
    fails += not fresh
    lines.append(f"{'ok  ' if fresh else 'FAIL'} a fresh clone followed by the README alone reaches I1's pass: {i1 or 'I1 not given'}")
    lines.append("PASS test_iris_readme: every section and item" if not fails else f"FAIL test_iris_readme: {fails} check(s) failed")
    return fails


def articles(lines) -> int:
    fails = 0
    want = {"article-1.md": ["can only say no", "The production", "decision contract", "Replay and live", "How to run it", "What I would change"],
            "article-2.md": ["DPI-I-689", "The Span message", "%AI.Policy.Audit", "Langfuse", "Tokens and cost", "IRIS Agentic Dev"]}
    for f, parts in want.items():
        p = IRIS / "docs" / f
        t = p.read_text(encoding="utf-8") if p.is_file() else ""
        have = [x for x in parts if x in t]
        ok = p.is_file() and len(have) == len(parts)
        fails += not ok
        lines.append(f"{'ok  ' if ok else 'FAIL'} iris/docs/{f}: {len(t.split())} words, {len(have)} of {len(parts)} parts of 4.13")
    lines.append("PASS test_iris_articles: both articles exist with every part of 4.13 (the founder posts them)" if not fails else f"FAIL test_iris_articles: {fails} failed")
    return fails


def one_product(lines) -> int:
    fails = 0
    for f in ("README.md", "docs/START.md", "web/llms.txt"):
        t = (ROOT / f).read_text(encoding="utf-8")
        hit = f"[{LINK}](https://github.com/drexthealpha/Knos/tree/main/iris)" in t
        fails += not hit
        lines.append(f"{'ok  ' if hit else 'FAIL'} {f} links iris/ as \"{LINK}\"")
    one = ONE in (IRIS / "README.md").read_text(encoding="utf-8")
    fails += not one
    lines.append(f"{'ok  ' if one else 'FAIL'} iris/README.md carries the one line")
    grep = subprocess.run(["git", "-C", str(ROOT), "grep", "-nIiE", "Knos ?Referee ?on ?IRIS|IRIS ?Referee|KnosIRIS", "--", ".", ":!iris"], capture_output=True, text=True).stdout.strip()
    names = [ln for ln in grep.splitlines() if ln]
    fails += bool(names)
    lines.append(f"{'ok  ' if not names else 'FAIL'} second product names outside iris/: {len(names)}" + (f" ({names[:2]})" if names else ""))
    lines.append("PASS test_iris_one_product: the 3 links, the one line, 0 second product names" if not fails else f"FAIL test_iris_one_product: {fails} failed")
    return fails


def main(argv) -> int:
    what, out = argv[0], (Path(argv[1]) if len(argv) > 1 else None)
    lines: list[str] = []
    fails = {"readme": lambda: readme(lines, argv[2] if len(argv) > 2 else ""), "articles": lambda: articles(lines), "one_product": lambda: one_product(lines)}[what]()
    print("\n".join(lines))
    if out:
        with out.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
