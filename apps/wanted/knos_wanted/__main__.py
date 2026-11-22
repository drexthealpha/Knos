"""python -m knos_wanted serve | check "an idea" [--in PLACE] [--json] | anchor"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m knos_wanted")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the web app (HOST, PORT)")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    c = sub.add_parser("check", help="a demand check from a terminal, on the open signals")
    c.add_argument("idea")
    c.add_argument("--in", dest="location")
    c.add_argument("--json", action="store_true")
    sub.add_parser("anchor", help="anchor every unanchored Record line on devnet (KNOS_WANTED_DEVNET_KEYPAIR signs)")
    a = ap.parse_args(argv)
    if a.cmd == "serve":
        from .server import serve
        serve(a.host, a.port)
        return 0
    if a.cmd == "anchor":
        from .company import anchor
        print(json.dumps(anchor(), indent=1))
        return 0
    from .check import demand_check
    rep = demand_check(a.idea, a.location)
    if a.json:
        print(json.dumps(rep, indent=1, default=str))
        return 0
    fb = rep["open_demand"]
    print(f"{rep['decision']['verdict']}: {fb['head']}")
    for r in fb["rows"]:
        print(f"- {r['name']}: {r['value']:,} {r['unit']}" + (" (counts)" if r["counts"] else ""))
    print(fb["line"], fb["rule"])
    print(f"Report sha256: {rep['hash']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
