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
# Why: iris/README.md carries the long form of the one line ("Knos carries any research across the valley of death (...)").
ONE = "Knos carries any research across the valley of death"
# Why: README.md and docs/START.md (outside iris/, not edited here) link iris/ with their own words; the link is what counts.
IRIS_URL = "](https://github.com/drexthealpha/Knos/tree/main/iris)"
# Why: the README's real headings. The spec's "Why it is technically interesting" is "How it works", its "Contest
# bonuses" is "Where each part lives" (the README names no contest), and its profile and license are two sections.
SECTIONS = ["What it decides", "How it works", "Requirements", "The image used", "LLM provider and key", "Start",
            "Check that it works", "Walkthrough of the three inputs", "The Workflow approval", "Solana devnet", "The trace",
            "Where each part lives", "Platform findings", "Tests", "Architecture", "Known limitations", "How it fits Knos",
            "Team", "License"]
# paths the README names that live in a running instance, not in the repository
RUNTIME = {"inbox/oru/", "mgr/python", ".env", "Knos/iris"}   # Knos/iris: the folder a fresh clone makes
EXT = (".cls", ".md", ".sh", ".py", ".java", ".yml", ".xml", ".cpf", ".txt", ".script", ".json", ".html")


def named_paths(t: str) -> list[str]:
    """Every repository path the README names in backticks, alone or inside a command."""
    out = []
    for tok in re.findall(r"`([^`\n]+)`", t):
        for w in tok.split():
            w = w.strip("\"'")
            w = w.rstrip(";,")
            w = w[2:] if w.startswith("./") else w
            if not w or w[0] in "/<{^" or ":" in w or "<" in w or w in RUNTIME:
                continue
            if "/" in w or w.endswith(EXT) or w == "Dockerfile":
                out.append(w)
    return sorted(set(out))


def exists(p: str) -> bool:
    bases = [IRIS, IRIS / "src" / "Knos" / "Iris", ROOT]
    if "*" in p:
        return any(list(b.glob(p)) for b in bases)
    if "/" not in p.rstrip("/"):
        return any((b / p).exists() for b in bases) or any(IRIS.rglob(p))
    return any((b / p).exists() for b in bases)


def readme(lines, i1: str) -> int:
    t = (IRIS / "README.md").read_text(encoding="utf-8")
    heads = re.findall(r"(?m)^## \d+\. (.+)$", t)
    fails = 0
    order = [h for h in heads if h in SECTIONS]
    ok = order == SECTIONS
    fails += not ok
    lines.append(f"{'ok  ' if ok else 'FAIL'} sections: {len(order)} of {len(SECTIONS)}, in order")
    paths = named_paths(t)
    missing = [p for p in paths if not exists(p)]
    fails += bool(missing) or not paths
    lines.append(f"{'ok  ' if not missing else 'FAIL'} files the README names: {len(paths) - len(missing)} of {len(paths)} exist" + (f"; missing {missing}" if missing else ""))
    claims = [c for c in ("fixtures/replay", "recorded live answer", "recorded answer") if c in t]
    fails += bool(claims)
    lines.append(f"{'ok  ' if not claims else 'FAIL'} no claim of recorded live answers" + (f": {claims}" if claims else ""))
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
        hit = IRIS_URL in t
        fails += not hit
        lines.append(f"{'ok  ' if hit else 'FAIL'} {f} links iris/")
    one = ONE in (IRIS / "README.md").read_text(encoding="utf-8")
    fails += not one
    lines.append(f"{'ok  ' if one else 'FAIL'} iris/README.md carries the one line")
    # Why: "the IRIS referee" outside iris/ (a CI comment, a test docstring) describes the step; only the folder's own name counts
    grep = subprocess.run(["git", "-C", str(ROOT), "grep", "-nIiE", "Knos ?Referee ?on ?IRIS|KnosIRIS", "--", ".", ":!iris"], capture_output=True, text=True).stdout.strip()
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
