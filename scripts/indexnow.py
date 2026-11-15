"""IndexNow (https://www.indexnow.org/documentation): after a Pages deploy, the front door's changed pages are sent to
api.indexnow.org, with the key file the site serves (web/indexnow.txt) as keyLocation. No account is needed.
The pages are the ones web/sitemap.xml lists (scripts/site_product.py writes it); each names its source file in
<lastmod>git:<path></lastmod>, and a page is sent when its source file is among the changed files.

    python scripts/indexnow.py [changed file ...]     changed files, paths from the repository root (none: the front door alone)

Prints "indexnow: <HTTP status> for <n> pages"; exits 0 on 200 or 202.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://drexthealpha.github.io/Knos/"
KEY = ROOT / "web" / "indexnow.txt"


def listed() -> list[tuple[str, str]]:
    """(page URL, source file) for each page of the published sitemap."""
    xml = (ROOT / "web" / "sitemap.xml").read_text(encoding="utf-8")
    return re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>git:([^<]+)</lastmod>", xml)


def urls_of(changed: list[str]) -> list[str]:
    files = {c.replace("\\", "/") for c in changed}
    return sorted({url for url, src in listed() if src in files})


def main(argv: list[str]) -> int:
    key = KEY.read_text(encoding="utf-8").strip()
    urls = urls_of(argv) or [SITE]
    body = json.dumps({"host": "drexthealpha.github.io", "key": key, "keyLocation": SITE + "indexnow.txt", "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            code = r.status
    except urllib.error.HTTPError as e:
        code = e.code
    print(f"indexnow: {code} for {len(urls)} pages: {' '.join(u.removeprefix(SITE) or '/' for u in urls)}")
    return 0 if code in (200, 202) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
