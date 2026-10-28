"""IndexNow (https://www.indexnow.org/documentation): after a Pages deploy, the front door's changed pages are sent to
api.indexnow.org, with the key file the site serves (web/indexnow.txt) as keyLocation. No account is needed.

    python scripts/indexnow.py [changed file ...]     the changed files of web/ (none: the front door alone)

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


def listed() -> set[str]:
    return set(re.findall(r"<loc>([^<]+)</loc>", (ROOT / "web" / "sitemap.xml").read_text(encoding="utf-8")))


def url_of(path: str) -> str | None:
    p = path.replace("\\", "/").removeprefix("web/")
    if p == "home.html":
        return SITE
    if p.endswith("/index.html"):
        return SITE + p.removesuffix("index.html")
    return SITE + p if p.endswith(".html") else None


def main(argv: list[str]) -> int:
    key = KEY.read_text(encoding="utf-8").strip()
    pages = listed()
    urls = sorted({u for u in map(url_of, argv) if u and u in pages}) or [SITE]
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
