"""python -m knos.autoresearch run <task dir> [--out DIR] [--iterations N] [--proposer local|cmd:<command>|sdk:claude] [--seed S]
                                          [--sealed FILE] [--record DIR] [--no-knos-record] [--anchor]"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from . import loop, proposers, task


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m knos.autoresearch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the loop on a task folder")
    r.add_argument("task")
    r.add_argument("--out", default="")
    r.add_argument("--iterations", type=int, default=12)
    r.add_argument("--proposer", default="local", help="local (default, deterministic, no key), cmd:<command line> or sdk:claude")
    r.add_argument("--seed", type=int, default=0, help="the local proposer's seed")
    r.add_argument("--sealed", default=None, help="the referee's sealed file (default: the one task.json names)")
    r.add_argument("--record", default=None, help="Knos Record directory (default: <out>/record)")
    r.add_argument("--no-knos-record", action="store_true", help="keep the record locally even if knos.record is installed")
    r.add_argument("--anchor", action="store_true", help="anchor the record's Merkle root on devnet via knos.record")
    r.add_argument("--anchor-keypair", default=None, help="the devnet keypair file that pays the anchor (default: knos.record's own)")
    a = ap.parse_args(argv)
    try:
        t = task.load(a.task, a.sealed)
        p = proposers.from_spec(a.proposer, a.seed)
    except (task.TaskError, ValueError, OSError) as why:
        print(f"knos autoresearch: {why}", file=sys.stderr)
        return 2
    out = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="knos-autoresearch-"))
    rep = loop.run(t, p, out, a.iterations, Path(a.record) if a.record else None,
                   use_knos_record=not a.no_knos_record, anchor=a.anchor, anchor_keypair=a.anchor_keypair)
    f = rep.final
    print(json.dumps({"graduated": rep.graduated, "experiments": rep.iterations, "kept": rep.kept,
                      "discarded": rep.discarded, "refused": rep.refused, "failed": rep.failed,
                      "dev": [rep.baseline_dev, rep.best_dev], "final_baseline": f["baseline"]["scores"],
                      "final_best": f["best"]["scores"], "lift": f["lift"], "reasons": f["reasons"],
                      "record": rep.record, "wall_s": rep.wall_s, "out": str(out)}, indent=2, default=str))
    return 0 if rep.graduated else 1


if __name__ == "__main__":
    sys.exit(main())
