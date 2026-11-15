"""docs_index.json: the title of every document under docs/, for the site's command palette (web/palette.js).

    python scripts/docs_index.py <out file>

One entry a Markdown file directly under docs/ or docs/reference/: its first `# ` heading and its path under docs/
(`STORY.md`, `reference/MARKET.md`), the front pages first, each folder sorted by file name. A file
with no such heading is left out. Nothing else is read and nothing is fetched.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def index() -> list[dict[str, str]]:
    out = []
    docs = ROOT / "docs"
    for path in [*sorted(docs.glob("*.md")), *sorted((docs / "reference").glob("*.md"))]:
        m = re.search(r"^# +(.+?)\s*$", path.read_text(encoding="utf-8"), re.M)
        if m:
            out.append({"title": re.sub(r"[`*_]", "", m[1]), "file": path.relative_to(docs).as_posix()})
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    Path(argv[1]).write_text(json.dumps(index(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
