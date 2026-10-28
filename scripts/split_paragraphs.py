"""Docs legibility: a prose paragraph of more than 60 words is split between its sentences into
paragraphs of 60 words at most. No word changes: lists, tables, headings, code, HTML and quotes are left as they are.

    python scripts/split_paragraphs.py [--check] [files...]     (default: README.md, docs/*.md, docs/reference/*.md)
    python scripts/split_paragraphs.py --check --strict           every prose paragraph of every one of them, the
                                                                  generated documents too, is 60 words at most
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX = 60
SKIP = ("|", "#", "<", "- ", "* ", "+ ", ">", "![", "    ", "\t", "[[")      # a bold lead-in (**Word.**) is prose
# documents whose figures must stay in the paragraph that carries their sample, ids and date (scripts/rate_claims.py)
KEEP_WHOLE = ("docs/reference/LOAD.md", "docs/reference/BENCH.md",
              # written whole by their generators (each has its own --check): changed there, never here
              "docs/reference/MANIFEST.md",
              "docs/reference/QLOO-COVERAGE.md")
# a test's plan is committed with its sha256 before the test runs (scripts/test_taste_truth.py, test_where_truth.py):
# its bytes stay as recorded, so it is neither split nor counted
FIXED_PLANS = ("docs/reference/taste_truth_plan.md", "docs/reference/where_truth_plan.md", "docs/reference/forecast_plan.md",
               "docs/reference/forecast_plan_v2.md", "docs/reference/evidence_plan.md")
SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(`\"'0-9])")


def _skip(body: str) -> bool:
    """Not prose: a list, table, heading, quote, HTML, or an indented code block (its own indent, before any strip)."""
    return body.startswith(("    ", "\t")) or body.lstrip().startswith(SKIP)


def words(text: str) -> int:
    return len(re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text).split())


def split(para: str) -> list[str]:
    if words(para) <= MAX:
        return [para]
    # cut only where a sentence ends: every other line break stays where it was (a phrase a test or a reader looks for
    # keeps its lines), and the cut's own whitespace becomes the blank line
    cuts = [m.span() for m in SENT.finditer(para)]
    out, start, last = [], 0, None
    for a, b in cuts + [(len(para), len(para))]:
        if last is not None and words(para[start:a]) > MAX:
            out.append(para[start:last[0]].strip())
            start = last[1]
        last = (a, b)
    out.append(para[start:].strip())
    return [c for c in out if c]


def fix(text: str) -> str:
    parts = re.split(r"(```.*?```)", text, flags=re.S)
    for i in range(0, len(parts), 2):
        paras = re.split(r"(\n\s*\n)", parts[i])
        for j in range(0, len(paras), 2):
            p = paras[j]
            body = p.strip("\n")
            if not body.strip() or _skip(body) or re.match(r"\s*\d+\.\s", body):
                continue
            new = "\n\n".join(split(body))
            if new != body:
                paras[j] = p.replace(body, new)
        parts[i] = "".join(paras)
    return "".join(parts)


def long_paragraphs(text: str) -> list[tuple[int, int]]:
    """(line, words) of each prose paragraph over MAX words: what no sentence split can fix is rewritten by hand."""
    out, line = [], 1
    for i, part in enumerate(re.split(r"(```.*?```)", text, flags=re.S)):
        if i % 2:
            line += part.count("\n")
            continue
        for chunk in re.split(r"(\n\s*\n)", part):
            body = chunk.strip("\n")
            if body.strip() and not _skip(body) and not re.match(r"\s*\d+\.\s", body) and words(body) > MAX:
                out.append((line + len(chunk) - len(chunk.lstrip("\n")), words(body)))
            line += chunk.count("\n")
    return out


def main(argv: list[str]) -> int:
    check = "--check" in argv
    if "--strict" in argv:
        files = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), *sorted((ROOT / "docs" / "reference").glob("*.md"))]
        files = [f for f in files if f.relative_to(ROOT).as_posix() not in FIXED_PLANS]
        bad = [(f.relative_to(ROOT).as_posix(), n, w) for f in files for n, w in long_paragraphs(f.read_text(encoding="utf-8"))]
        for f, n, w in bad:
            print(f"{f}:{n}: {w} words")
        print(f"paragraphs over {MAX} words: {len(bad)} in {len({b[0] for b in bad})} files of {len(files)}")
        return 1 if bad else 0
    files = [Path(a) for a in argv if not a.startswith("--")] or [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")),
                                                                     *sorted((ROOT / "docs" / "reference").glob("*.md"))]
    off = []
    files = [f.resolve() for f in files if f.resolve().relative_to(ROOT).as_posix() not in KEEP_WHOLE + FIXED_PLANS]
    for f in files:
        s = f.read_text(encoding="utf-8")
        new = fix(s)
        if new != s:
            off.append(str(f.relative_to(ROOT)))
            if not check:
                f.write_text(new, encoding="utf-8", newline="\n")
    print(("over 60 words: " if check else "split: ") + (f"{len(off)} files" if off else "nothing"))
    return 1 if check and off else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
