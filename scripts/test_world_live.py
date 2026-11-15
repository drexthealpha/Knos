"""Live checks against the hosted app and the Pages site (test_hero_needs, test_refuse_list):

- the refuse list: GET /api/refuse is the published list (dated, with its source); 0 of 30 bad briefs (tests/test_refuse.py) come
  back Ready from POST /api/ready/card, and a harmless one still does.
- the hero: the live home page's examples cover housing, food, energy and health across >= 5 technologies, and the housing
  brief (a test report from an accredited lab as its proof) is Ready and attested on devnet, read back from the chain.

    KNOS_ADMIN_KEY=... python scripts/test_world_live.py <housing-brief.json>
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "src")]
from test_hero_needs import NEEDS, chips  # noqa: E402
from test_refuse import bad_briefs  # noqa: E402

APP, SITE = "https://knos.onrender.com", "https://drexthealpha.github.io/Knos/"
OP = {"X-Knos-Admin": os.environ.get("KNOS_ADMIN_KEY", "")}          # the operator's run: past the per-address limits


def get(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=OP), timeout=120) as r:
        body = r.read().decode("utf-8")
        return json.loads(body) if body.lstrip().startswith("{") else body


def card(brief: dict) -> dict:
    req = urllib.request.Request(APP + "/api/ready/card", json.dumps({"brief": brief}).encode(), {"Content-Type": "application/json", **OP})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def main(argv: list[str]) -> int:
    ok = True
    pub = get(APP + "/api/refuse")
    cats = sorted(pub.get("categories") or pub.get("refuse") or {})
    print(f"/api/refuse: {len(cats)} categories {cats}, as of {pub.get('as_of')}, source {pub.get('sanctions_source')}")
    passed = [b["title"] for _cat, b in bad_briefs() if card(b).get("ready")]
    ok &= not passed and len(cats) == 4
    good = card({"title": "Low-carbon cement blocks for homes", "milestones": [{"name": "Lab test", "target": "6 cubes reach 33 MPa",
                 "key": "lab", "verifier": {"kind": "ci", "check": "test_cubes"}, "deadline_days": 30}]})
    ok &= bool(good.get("ready"))
    print(f"{'PASS' if ok else 'FAIL'} test_refuse_list: {len(passed)} of 30 bad briefs Ready {passed}; harmless brief Ready: {bool(good.get('ready'))}")

    c = chips(get(SITE))
    needs, techs = {x.get("need") for x in c} & NEEDS, {x["tech"] for x in c if x.get("tech")}
    house = card(json.loads(Path(argv[0]).read_text(encoding="utf-8")))
    h = (house.get("card") or {}).get("criteria_sha256")
    back = get(f"{APP}/api/ready/card?hash={h}") if h else {}
    good4 = needs == NEEDS and len(techs) >= 5 and bool(house.get("ready")) and bool(back.get("found"))
    print(f"live hero: needs {sorted(needs)}, {len(techs)} technologies {sorted(techs)}")
    print(f"housing brief: Ready {house.get('ready')}, criteria {h}, on devnet {back.get('found')}, {json.dumps(back)[:400]}")
    print(f"{'PASS' if good4 else 'FAIL'} test_hero_needs")
    return 0 if ok and good4 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
