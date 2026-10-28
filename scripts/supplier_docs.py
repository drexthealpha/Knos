"""Write what is printed from knos.ghwords.REFUSALS: the table in docs/reference/SUPPLIER.md (between its two markers) and
web/refusals.json, which the site's supplier page reads; and from knos.preflight.PROTECTIONS, the table of the four
protections in docs/reference/SUPPLIER.md (between its own markers). `--check` writes nothing and exits 1 when either is behind.

    python scripts/supplier_docs.py [--check]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from knos import ghwords, preflight  # noqa: E402

BEGIN, END = "<!-- refusals: begin (scripts/supplier_docs.py) -->\n", "<!-- refusals: end -->\n"
OWED_BEGIN, OWED_END = "<!-- protections: begin (scripts/supplier_docs.py) -->\n", "<!-- protections: end -->\n"
MERGE = {"accept": "", "checks": [], "deny": [], "mode": "merge", "paths": [], "reserve": 7, "v": 1}        # terms that lack what terms can lack


def protections_table() -> str:
    """The four protections (and the netted form of the fourth): what each is, how it is enforced when the terms hold
    it, and the sentence `knos preflight` prints when they do not."""
    from knos import terms
    lacked = {p["id"]: p["warning"] for p in preflight.protections(preflight.read_terms(terms.canonical(MERGE).decode("ascii")))}
    netted = preflight.protections(preflight.read_terms(terms.canonical(MERGE).decode("ascii")), netted=True)[3]["warning"]
    rows = ["| You are owed | How | Enforced by | When the terms lack it, preflight says |", "| --- | --- | --- | --- |"]
    for key, title, how, line in preflight.PROTECTIONS:
        rows.append(f"| {title} | {line} | {how} | {lacked.get(key) or 'Not checked from a terms file: an order holds its whole price from funding. Read a funded one with `--issue`.'} |")
    key, title, how, line = preflight.NETTED
    rows.append(f"| {title}, netted work | {line} | {how} | {netted} |")
    return "\n".join(rows) + "\n"


def main(argv: list[str]) -> int:
    doc_path, site_path = ROOT / "docs" / "reference" / "SUPPLIER.md", ROOT / "web" / "refusals.json"
    doc = doc_path.read_text(encoding="utf-8")
    head, rest = doc.split(BEGIN, 1)
    new_doc = head + BEGIN + ghwords.refusal_table() + END + rest.split(END, 1)[1]
    head, rest = new_doc.split(OWED_BEGIN, 1)
    new_doc = head + OWED_BEGIN + protections_table() + OWED_END + rest.split(OWED_END, 1)[1]
    new_site = json.dumps({"kind": "knos-refusals", "v": 1, "rows": ghwords.refusal_rows()}, indent=1, ensure_ascii=False) + "\n"
    behind = [str(p.relative_to(ROOT)) for p, want in ((doc_path, new_doc), (site_path, new_site))
              if not p.is_file() or p.read_text(encoding="utf-8") != want]
    if "--check" in argv:
        print("up to date" if not behind else "behind: " + ", ".join(behind))
        return 1 if behind else 0
    doc_path.write_text(new_doc, encoding="utf-8")
    site_path.write_text(new_site, encoding="utf-8")
    print(f"wrote {len(ghwords.REFUSALS)} refusals and {len(preflight.PROTECTIONS)} protections to docs/reference/SUPPLIER.md, and web/refusals.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
