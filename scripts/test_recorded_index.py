"""test_recorded_index (R1), live: the answered-idea index the server holds privately. /status/qloo lists how many
distinct ideas, entities and tags it holds; both ramen inputs are offered a recorded reading with the words that
differ; no Qloo response body is in the repository or the built Pages site.

    python scripts/test_recorded_index.py <built site dir> [result file]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = "https://knos.onrender.com"
# what a stored Qloo body looks like: its results envelope, an entity urn with an affinity, an audience urn
BODY = re.compile(r'"results"\s*:\s*\{\s*"entities"|"affinity"\s*:\s*0\.\d{3,}|urn:audience:[a-z_]+|"popularity"\s*:\s*0\.\d{6,}')


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(APP + path, json.dumps(body).encode(), {"Content-Type": "application/json", "User-Agent": "knos-r1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def main(argv: list[str]) -> int:
    site = Path(argv[0])
    out = Path(argv[1]) if len(argv) > 1 else None
    lines, fails = [], []

    def ok(c, what):
        lines.append(f"{'ok  ' if c else 'FAIL'} {what}")
        if not c:
            fails.append(what)

    with urllib.request.urlopen(urllib.request.Request(APP + "/status/qloo", headers={"User-Agent": "knos-r1"}), timeout=120) as r:
        page = re.sub(r"<[^>]+>", " ", r.read().decode("utf-8", "replace"))
    m = re.search(r"Answered ideas held privately\s+(\d+) \((\d+) full cards\)", page)
    e = re.search(r"Entities and tags Qloo confirmed\s+(\d+) entities, (\d+) tags", page)
    n = int(m.group(1)) if m else 0
    ok(bool(m and e) and n > 0, f"/status/qloo lists {n} distinct answered ideas ({m.group(2) if m else 0} full cards), "
       f"{e.group(1) if e else 0} entities, {e.group(2) if e else 0} tags")
    for idea in ("a vegan ramen food truck", "a late night ramen spot"):
        w = post("/api/check", {"idea": idea})
        rec = [r for r in w.get("readings") or [] if r.get("kind") == "recorded"]
        ok(w.get("kind") == "which_one" and rec and all((r.get("differs") or {}).get("theirs") or (r.get("differs") or {}).get("yours") for r in rec),
           f"{idea}: {len(rec)} recorded reading(s): " + "; ".join(f"{r['text']} ({r['differs']['theirs']} against {r['differs']['yours']})" for r in rec))
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    hits = []
    for f in files:
        p = ROOT / f
        if p.suffix.lower() in (".json", ".html", ".md", ".js", ".txt", ".jsonl") and p.is_file() and not f.startswith(("tests/", "apps/wanted/tests/")):
            if BODY.search(p.read_text(encoding="utf-8", errors="replace")):
                hits.append(f)
    for p in site.rglob("*"):
        if p.is_file() and p.suffix.lower() in (".json", ".html", ".js", ".txt") and BODY.search(p.read_text(encoding="utf-8", errors="replace")):
            hits.append("site:" + str(p.relative_to(site)))
    ok(not hits, f"{len(hits)} Qloo bodies in the repository or the Pages site" + (f": {', '.join(hits[:8])}" if hits else ""))
    lines.append(f"PASS test_recorded_index: {n} distinct answered ideas indexed on the server, both ramen inputs offered a recorded reading, 0 Qloo bodies in the repo or Pages"
                 if not fails else f"FAIL test_recorded_index: {len(fails)} check(s) failed")
    print("\n".join(lines))
    if out:
        with out.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
