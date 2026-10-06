"""Write what is printed from knos.ghwords.REFUSALS: the table in docs/SUPPLIER.md (between its two markers) and
web/refusals.json, which the site's supplier page reads. `--check` writes nothing and exits 1 when either is behind.

    python scripts/supplier_docs.py [--check]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from knos import ghwords  # noqa: E402

BEGIN, END = "<!-- refusals: begin (scripts/supplier_docs.py) -->\n", "<!-- refusals: end -->\n"


def main(argv: list[str]) -> int:
    doc_path, site_path = ROOT / "docs" / "SUPPLIER.md", ROOT / "web" / "refusals.json"
    doc = doc_path.read_text(encoding="utf-8")
    head, rest = doc.split(BEGIN, 1)
    new_doc = head + BEGIN + ghwords.refusal_table() + END + rest.split(END, 1)[1]
    new_site = json.dumps({"kind": "knos-refusals", "v": 1, "rows": ghwords.refusal_rows()}, indent=1, ensure_ascii=False) + "\n"
    behind = [str(p.relative_to(ROOT)) for p, want in ((doc_path, new_doc), (site_path, new_site))
              if not p.is_file() or p.read_text(encoding="utf-8") != want]
    if "--check" in argv:
        print("up to date" if not behind else "behind: " + ", ".join(behind))
        return 1 if behind else 0
    doc_path.write_text(new_doc, encoding="utf-8")
    site_path.write_text(new_site, encoding="utf-8")
    print(f"wrote {len(ghwords.REFUSALS)} refusals to docs/SUPPLIER.md and web/refusals.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
