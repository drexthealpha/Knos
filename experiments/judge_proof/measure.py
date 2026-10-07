"""Run a command; write its wall-clock seconds and the largest resident memory of any process it waited for.

    python measure.py <out.json> <command> [arguments...]

The memory figure is the kernel's `ru_maxrss` for this process's finished children (Linux: kilobytes): the largest
single process in the tree, which for a proof is the prover, not the sum of the tree.
"""
from __future__ import annotations

import json
import resource
import subprocess
import sys
import time


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: measure.py <out.json> <command> [arguments...]", file=sys.stderr)
        return 2
    started = time.monotonic()
    done = subprocess.run(argv[2:], check=False)
    seconds = time.monotonic() - started
    used = resource.getrusage(resource.RUSAGE_CHILDREN)
    with open(argv[1], "w", encoding="utf-8") as f:
        json.dump({"seconds": round(seconds, 2), "max_rss_kb": used.ru_maxrss,
                   "cpu_seconds": round(used.ru_utime + used.ru_stime, 2), "exit": done.returncode}, f)
        f.write("\n")
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
