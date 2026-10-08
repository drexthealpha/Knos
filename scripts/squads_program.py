#!/usr/bin/env python3
"""Fetch the deployed Squads v4 program, so the boundary tests can run it in LiteSVM next to knos_pay.

    python scripts/squads_program.py fetch [--rpc URL] [--out FILE]     reads the program from the cluster and checks it
    python scripts/squads_program.py path                               prints where the tests look for it

The program is Squads Labs' (SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf), not Knos's: it is read from devnet, its
bytes are checked against the sha256 below (the build deployed at slot 446638068 on devnet), and it is kept outside the
repository's history (tests/fixtures/squads/squads_v4.so, which .gitignore there keeps out, or KNOS_SQUADS_SO). tests/test_boundary.py skips the Squads tests without it.
A program that changes on the cluster changes the hash: the fetch then refuses, and a person checks the new build
before this pin moves.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

PROGRAM = "SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf"
PROGRAM_DATA = "Fy3YMJCvwbAXUgUM5b91ucUVA3jYzwWLHL3MwBqKsh8n"     # the loader's ProgramData account of PROGRAM
SHA256 = "97fb2a5c08e5df5e862d8354ac5b97d3587117f98c4457754ca12e30bef0664d"
SLOT = 446_638_068
HEADER = 45                                                     # ProgramData: tag u32, slot u64, Option<authority>


def default_path() -> Path:
    named = os.environ.get("KNOS_SQUADS_SO", "").strip()
    return Path(named) if named else Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "squads" / "squads_v4.so"


def ok(path: Path) -> bool:
    """Whether `path` holds exactly the pinned build."""
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == SHA256


def fetch(rpc: str, out: Path) -> int:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo", "params": [PROGRAM_DATA, {"encoding": "base64"}]}).encode()
    req = urllib.request.Request(rpc, data=body, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:       # noqa: S310 (an https RPC endpoint the caller names)
        value = json.load(r)["result"]["value"]
    data = base64.b64decode(value["data"][0])
    slot = int.from_bytes(data[4:12], "little")
    program = data[HEADER:]
    got = hashlib.sha256(program).hexdigest()
    if got != SHA256:
        print(f"refused: the Squads program at {rpc} (deployed at slot {slot}) is not the pinned build: sha256 {got}, pinned {SHA256}. Nothing written.",
              file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(program)
    print(f"Wrote {out}: Squads v4, deployed at slot {slot}, sha256 {got}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("what", choices=("fetch", "path"))
    ap.add_argument("--rpc", default=os.environ.get("KNOS_RPC", "https://api.devnet.solana.com"))
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    out = a.out or default_path()
    if a.what == "path":
        print(out)
        return 0 if ok(out) else 1
    return fetch(a.rpc, out)


if __name__ == "__main__":
    sys.exit(main())
