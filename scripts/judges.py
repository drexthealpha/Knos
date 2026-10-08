#!/usr/bin/env python3
"""docs/judges.json is docs/JUDGES.md as data, for the site.

    python scripts/judges.py            write docs/judges.json from docs/JUDGES.md
    python scripts/judges.py --check    fail when the file differs from the page, or the page breaks its own rules

The page is typed by hand and is the source. Its rules: the one sentence, then the winning claim, then the one number;
at most 350 words outside the table; thirteen rows (the six criteria in the rules, then the seven factors Colosseum's
hackathon page lists), each one sentence and one link; a definition of days to approve that gives no figure; five
lines under "What is not real yet". The shape of the file, which the site's "For judges" page (web/judges.js) reads
as it is (scripts/build_site.sh copies it into the build):

    {"title", "sentence", "pitch", "number", "claim", "why_solana", "source": "docs/JUDGES.md", "columns": [...],
     "rows": [{"id", "thing", "sentence", "link", "label"}],                        thirteen, in the page's order
     "wait": "...",                                                                 the paragraph on days to approve
     "not_real": ["...", ...],                                                      five lines
     "page": "https://github.com/.../docs/JUDGES.md"}

`thing` and `sentence` are a row's first two cells as the page words them; `link` is the row's first link made
absolute (a relative one is a file of the repository on GitHub), so a page that is not in docs/ can use it, and
`label` its words. `not_real` is the list under the first heading whose words hold "not real".
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE, DATA = "docs/JUDGES.md", "docs/judges.json"
BLOB = "https://github.com/drexthealpha/Knos/blob/main/docs/"
CRITERIA = ["How well it works", "Potential impact", "Novelty", "User experience", "Open source and composition", "Business plan"]
# the factors https://colosseum.com/hackathon lists for judging, in its order
FACTORS = ["Founder and market fit", "Insight", "Product and execution", "Potential market size", "Founder communication",
           "Viability", "Traction"]
JUDGED = CRITERIA + FACTORS
PITCH = ("Knos lets buyers and suppliers agree what AI work earned payment, and independently prove that agreement "
         "later.")
DAYS = ("Days to approve is defined as the days from the day the buyer receives a supplier's invoice to the day a person "
        "with authority approves it.")
WHY_SOLANA = "Money is released with no custodian, and the count is anchored where neither side can alter it."
LIMIT_WORDS, ZEROS = 350, 5
WORD = re.compile(r"[A-Za-z0-9][\w'%.,-]*")
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
MAIN = "https://github.com/drexthealpha/Knos/blob/main/"


def flat(text: str) -> str:
    return " ".join(text.split())


def prose(page: str) -> str:
    """The page without its table and without link targets: what the 350 words count."""
    kept = [line for line in page.splitlines() if not line.startswith("|")]
    return re.sub(r"\]\([^)]*\)", "]", "\n".join(kept))


def _plain(cell: str) -> str:
    return re.sub(r"[*`]", "", LINK.sub(r"\1", cell)).strip()


def _address(href: str, root: Path = ROOT) -> str:
    """A link of the page as an address the site can open: a relative one is a file of the repository on GitHub."""
    if re.match(r"https?://", href):
        return href
    path = (root / "docs" / href.split("#")[0]).resolve().relative_to(root.resolve()).as_posix()
    return MAIN + path + ("#" + href.split("#", 1)[1] if "#" in href else "")


def read(text: str, root: Path = ROOT) -> dict:
    """The rows of a page's first table, cell for cell, and the list under its "not real" heading."""
    lines = text.splitlines()
    table = [i for i, line in enumerate(lines) if line.startswith("|")]
    rows: list[dict] = []
    columns: list[str] = []
    if table:
        block = []
        for line in lines[table[0]:]:
            if not line.startswith("|"):
                break
            block.append([c.strip() for c in line.strip().strip("|").split("|")])
        columns = [_plain(c) for c in block[0]]
        for cells in block[2:]:
            link = LINK.search(" ".join(cells))
            rows.append({"thing": _plain(cells[0]), "sentence": _plain(cells[1]) if len(cells) > 1 else "",
                         "link": _address(link[2], root) if link else "", "label": link[1] if link else ""})
    not_real: list[str] = []
    for i, line in enumerate(lines):
        if line.startswith("#") and "not real" in line.lower():
            for item in lines[i + 1:]:
                if item.startswith("#"):
                    break
                m = re.match(r"\s*(?:[-*]|\d+\.)\s+(.*)", item)
                if m:
                    not_real.append(_plain(m[1]))
            break
    return {"source": PAGE, "columns": columns, "rows": rows, "not_real": not_real}


def build(root: Path = ROOT) -> dict:
    page = (root / PAGE).read_text(encoding="utf-8")
    lines = [line for line in page.splitlines() if line.strip()]
    got = read(page, root)
    rows = [{"id": re.sub(r"[^a-z]+", "_", r["thing"].lower()).strip("_"), **r} for r in got["rows"]]
    wait = flat(page.split("## Days to approve, not seconds to pay")[1].split("\n## ")[0])
    return {"title": lines[0].lstrip("# "), "sentence": lines[1].strip("*"), "pitch": lines[2], "number": lines[3],
            "claim": flat(page.split("The claim: ")[1].split("\n\n")[0]), "why_solana": WHY_SOLANA,
            "source": PAGE, "columns": got["columns"], "rows": rows, "wait": wait, "not_real": got["not_real"],
            "page": BLOB + "JUDGES.md"}


def problems(root: Path = ROOT) -> list[str]:
    page = (root / PAGE).read_text(encoding="utf-8")
    data, out = build(root), []
    words = len(WORD.findall(prose(page)))
    if words > LIMIT_WORDS:
        out.append(f"{PAGE}: {words} words outside the table; the limit is {LIMIT_WORDS}")
    if page.count("\n|---") != 1:
        out.append(f"{PAGE}: one table, not {page.count(chr(10) + '|---')}")
    if [r["thing"] for r in data["rows"]] != JUDGED:
        out.append(f"{PAGE}: the rows are {[r['thing'] for r in data['rows']]}, not {JUDGED}")
    for row in data["rows"]:
        if len(re.findall(r"[.!?](?:\s|$)", row["sentence"])) != 1 or not row["sentence"].endswith("."):
            out.append(f"{PAGE}: {row['thing']}: one sentence, not {row['sentence']!r}")
        if not row["link"]:
            out.append(f"{PAGE}: {row['thing']}: no link")
        elif row["link"].startswith(MAIN) and not (root / row["link"][len(MAIN):].split("#")[0]).exists():
            out.append(f"{PAGE}: {row['thing']}: {row['link'][len(MAIN):]} is not a file")
    if data["pitch"] != PITCH:
        out.append(f"{PAGE}: the second line is not the pitch line")
    if DAYS not in data["wait"] or "Not measured." not in data["wait"] or re.search(r"\d+(\.\d+)? days", data["wait"]):
        out.append(f"{PAGE}: days to approve is defined, said to be not measured, and given no figure")
    if len(data["not_real"]) != ZEROS:
        out.append(f"{PAGE}: {len(data['not_real'])} lines under 'What is not real yet'; it is {ZEROS}")
    if f"Why Solana: {WHY_SOLANA}" not in flat(page):
        out.append(f"{PAGE}: the line on why Solana is not the one every page uses")
    file = root / DATA
    if not file.exists() or json.loads(file.read_text(encoding="utf-8")) != data:
        out.append(f"{DATA} is not what {PAGE} says: run python scripts/judges.py")
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--check" in args:
        found = problems()
        for line in found:
            print("FAIL ", line)
        print("ok" if not found else f"{len(found)} problem(s)")
        return 1 if found else 0
    (ROOT / DATA).write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {DATA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
