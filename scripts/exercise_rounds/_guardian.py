"""What the rounds `guardian` and `pause` share: the guardian multisig's member keys and scripts/governance.mjs, run
against the round's cluster. Not a round itself (scripts/exercise_public.py skips files whose name starts with `_`).

The member keys are <keys>/governance, or the folder <keys>/exercise.json names as "governance_keys": member-1.json,
member-2.json and payer.json, as governance.mjs reads them. The guardian is 2 of 3 keys, all the founder's
(docs/GOVERNANCE.md), so one owner can sign for it.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


def keys(x: Any, w: Any) -> Path:
    folder = Path(w.cfg.get("governance_keys") or w.keys / "governance")
    if not folder.is_dir():
        raise x.Skip(f"{folder} is missing: the guardian's member keys (member-1.json, member-2.json, payer.json) sign through scripts/governance.mjs")
    return folder


def run_node(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", check=False, timeout=600)  # noqa: S603


def govern(x: Any, w: Any, args: list[str], runner=None) -> str:
    """`node scripts/governance.mjs <args> --rpc <the round's cluster> --keys <the member keys>`: its output. A test
    gives `runner` (or sets `RUNNER`) in place of node."""
    folder = keys(x, w)
    runner = runner or RUNNER
    node = shutil.which("node") if runner is run_node else "node"
    if not node:
        raise x.Skip("node is not installed: scripts/governance.mjs signs the guardian's proposals")
    done = runner([node, str(x.ROOT / "scripts" / "governance.mjs"), *args, "--rpc", str(w.url), "--keys", str(folder)])
    if done.returncode:
        raise x.Failed(f"governance.mjs {' '.join(args)}: {(done.stderr or done.stdout).strip()[-300:]}")
    return str(done.stdout)


RUNNER = run_node

