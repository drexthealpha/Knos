"""The sitemap's lastmod for each page, from git: web/sitemap.xml names each page's source file (<lastmod>git:web/...</lastmod>),
and the build writes the date of the last commit that changed that file, at or before the commit it builds; a file this
clone has no history for gets the build's date.

    python scripts/sitemap_dates.py <built site> <build date>
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def last(path: str, fallback: str) -> str:
    got = subprocess.run(["git", "log", "-1", "--format=%cs", "--", path], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    return got if DATE.match(got) else fallback


def main(argv: list[str]) -> int:
    site, stamp = Path(argv[0]), argv[1]
    f = site / "sitemap.xml"
    text = f.read_text(encoding="utf-8")
    out = re.sub(r"<lastmod>git:([^<]+)</lastmod>", lambda m: f"<lastmod>{last(m.group(1), stamp)}</lastmod>", text)
    if "git:" in out or not re.search(r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>", out):
        print("sitemap: a lastmod was not written")
        return 1
    f.write_text(out, encoding="utf-8", newline="\n")
    print(f"sitemap: {out.count('<url>')} pages dated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
