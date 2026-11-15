"""Find retired figures that a public file still states as current.

Usage: python scripts/stale_check.py [--root PATH] [--json]

A public file is the README, every Markdown file under docs/, and the site's HTML and scripts under web/. The
changelog is history and is not read. Each rule names a retired figure and the words that mark a mention of it as
history or as a dated reading (a date, "was", "the scan", "version 1"...). A paragraph (in Markdown: the lines
between blank lines, or one table row; elsewhere: one line) that states the figure without such a word is stale.
Exit status 1 when anything is found.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DATED = r"\b\d{1,2} (?:Sep|Oct)\w*|2026-\d\d-\d\d|\breading\b|\bread on\b"


@dataclass(frozen=True)
class Rule:
    name: str
    says: str  # the retired figure
    allow: str  # words that mark the mention as history or as a dated reading
    why: str


RULES = (
    Rule(
        "lead",
        r"\b30 of (?:the |those )?241\b|\b30 \(12\.4%\)|\b12\.4 ?%|\b16 of 241\b",
        r"\bscan\b|second reading|first reading|excluded|version 1|\bwas\b|\bwere\b|earlier|retired|before the re-?read",
        "the lead is 9 of 241 (3.7%, 95% interval 2.0% to 6.9%) after the second reading",
    ),
    Rule(
        "merge-to-paid",
        r"\b2[56] seconds\b|(?:median|p50)[^.|]{0,40}\b2[56] s\b|\|\s*2[56] s\s*\|",
        DATED + r"|\b(?:39|4[1-7]) payments\b|\|\s*(?:39|4[1-7])\s*\|\s*25 s|\bwas\b|earlier",
        "merge to paid is 28 s at the median over 56 payments, measured 10 Oct 2026 (26 s over 51 is an earlier reading: date it)",
    ),
    Rule(
        "disclosure-0.3.11",
        r"\b209 commits\b|\b39,778\b|\b423 of\b|\b98\.9%",
        r"\bAt Knos 0\.3\.11, commit `f3dfd3d`, the same count was\b",
        "docs/reference/DISCLOSURE.md counts at Knos 0.3.25: 229 commits, 412 of 428,405 lines (0.1%)",
    ),
    Rule(
        "fee-upgrade-pending",
        r"[Uu]ntil (?:the|that) upgrade to knos_pay 2\.2 executes|still charges the 0\.3\.14 fee",
        r"\bwas\b",
        "knos_pay 2.2 runs at the public ids; an order funded under 2.1 keeps its stored fee",
    ),
    Rule(
        "meter-price",
        r"\b0\.002(?: USD)?\b[^.|]{0,60}evaluation|evaluation[^.|]{0,60}\b0\.002\b",
        r"\b0\.05\b|\b10,000\b|propos|upgrade|\bknos_meter\b|\bknos-meter\b",
        "the deployed knos_meter charges 0.05 after 10,000 free; say so beside the price book's 0.002 after 100,000",
    ),
)

SKIP = ("CHANGELOG.md",)


def public_files(root: Path) -> list[Path]:
    out = [root / "README.md"] if (root / "README.md").exists() else []
    out += sorted((root / "docs").rglob("*.md"))
    web = root / "web"
    if web.is_dir():
        out += sorted(p for p in web.rglob("*") if p.suffix in (".html", ".js") and "vendor" not in p.parts)
    return [p for p in out if p.name not in SKIP]


def paragraphs(path: Path, text: str) -> list[tuple[int, str]]:
    """(first line number, text) of each paragraph; a Markdown table row is its own paragraph."""
    lines = text.splitlines()
    if path.suffix != ".md":
        return [(i + 1, line) for i, line in enumerate(lines)]
    out: list[tuple[int, str]] = []
    start, buf = 0, []  # type: int, list[str]
    for i, line in enumerate(lines + [""]):
        if not line.strip() or line.lstrip().startswith("|"):
            if buf:
                out.append((start + 1, " ".join(buf)))
                buf = []
            if line.strip():
                out.append((i + 1, line))
            continue
        if not buf:
            start = i
        buf.append(line)
    return out


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    rule: str
    text: str


def check_text(name: str, path: Path, text: str) -> list[Finding]:
    found = []
    for line, para in paragraphs(path, text):
        for r in RULES:
            m = re.search(r.says, para)
            if m and not re.search(r.allow, para):
                found.append(Finding(name, line, r.name, para[max(0, m.start() - 60): m.end() + 60].strip()))
    return found


def check(root: Path) -> list[Finding]:
    found = []
    for p in public_files(root):
        found += check_text(p.relative_to(root).as_posix(), p, p.read_text(encoding="utf-8", errors="replace"))
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    found = check(Path(a.root))
    if a.json:
        print(json.dumps([f.__dict__ for f in found], indent=1))
    else:
        why = {r.name: r.why for r in RULES}
        for f in found:
            print(f"{f.file}:{f.line}: {f.rule}: ...{f.text}...\n    now: {why[f.rule]}")
        print(f"{len(found)} stale statement(s)" if found else "no retired figure stated as current")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
