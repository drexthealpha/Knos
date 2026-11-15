"""python -m knos.labs catalogue              every lab adapter: field, live-ready or not, the key it needs
   python -m knos.labs try LAB                one order of LAB's example through quote, order, status, results and the two
                                              verdicts, on the lab's FIXTURES (no network, no money). LAB is one of:
                                              adaptyv, b12_selenium, b12_foundry, materials_project, pcbway, xometry, pylabrobot
                                              (jlcpcb and manual are listed by catalogue but have no example to try)
   python -m knos.labs try pylabrobot --live  robotics on a real PyLabRobot install instead of the recorded runs
                                              (install it once: sh scripts/install_pylabrobot.sh)"""
from __future__ import annotations

import json
import sys

from . import LabError, catalogue


def _try(name: str, live: bool) -> int:
    from .contract import adapters
    labs = adapters()
    if name not in labs:
        print(f"no lab {name!r}: one of {', '.join(labs)}", file=sys.stderr)
        return 2
    lab = labs[name]
    q = lab.quote(lab.example)
    o = lab.order(lab.example, "no-held-money (fixture try)")
    out = {"lab": name, "field": lab.field, "quote": q, "order": o["order_id"]}
    if name in ("xometry", "b12_foundry"):
        out["manual"] = ("ordered by a person: the request below goes to the lab by its own channel, and its files come back "
                         "through knos.labs.manual.Manual.deliver; then the same two verdicts apply")
        out["request"] = o.get("raw", {}).get("request")
        print(json.dumps(out, indent=1))
        return 0
    if name == "pylabrobot" and live:
        from . import robotics, verdicts
        a = robotics.PyLabRobot("live")
        try:
            r = a.results(a.order(lab.example, "no-held-money (live try)"), lab.example)
        except LabError as why:
            print(f"{why}\nInstall it once with: sh scripts/install_pylabrobot.sh", file=sys.stderr)
            return 2
        lv = verdicts.lab_verdict(lab.example, r)
        res = {"mode": "live", "label": a.label, "lab_verdict": lv.verdict,
               "outcome_verdict": verdicts.outcome_verdict(lab.example, r, lv).verdict, "qc": r.qc}
    else:
        got = lab.results(o)
        res = {k: got[k] for k in ("state", "qc", "lab_verdict", "outcome_verdict", "settle", "source")}
        res["mode"] = "fixture"
    print(json.dumps({**out, "results": res}, indent=1, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "catalogue":
        print(json.dumps(catalogue(), indent=1))
        return 0
    if args[0] == "try" and len(args) >= 2:
        return _try(args[1], "--live" in args[2:])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
