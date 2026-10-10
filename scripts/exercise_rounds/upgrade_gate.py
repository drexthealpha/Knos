"""The round `gate`: upgrade_gate's record, at its public id, that GitHub's runner built exactly the bytes a program now
runs. scripts/governance.mjs refuses to propose a buffer whose build has no such record, and the builds of proposals
7 and 8 (knos_oidc and knos_pay 2.2) were proposed through it, so their records exist: this round reads them and the
transaction that wrote each one. It sends nothing.

    python scripts/exercise_public.py run --only gate --rpc URL --keys DIR

The build hashes are docs/provenance.json's `on_chain_hash`, and each must also be the hash the program runs now
(read again here). `xp` is scripts/exercise_public.py, put here by its loader.
"""
from __future__ import annotations

from typing import Any

ROUND = {"name": "gate", "needs": ("public",), "caps": ("upgrade_gate",), "phase": "any"}


def _xp() -> Any:
    return globals()["xp"]


def run(book, st: dict) -> None:
    """upgrade_gate holds, at its public id, GitHub's word that its runner built the bytes each program runs now."""
    from solders.pubkey import Pubkey
    x, w = _xp(), book.w
    if "records" in st:
        return
    seen = x._json(x.ROOT / "docs" / "provenance.json") or {}
    live = {n: p for n, p in (book.ev.get("programs") or {}).items() if p.get("hash")}
    rows = []
    for name, entry in sorted((seen.get("programs") or {}).items()):
        h = str(entry.get("on_chain_hash") or "")
        if not h or name not in live or live[name]["hash"] != h:
            continue            # only a build the public id runs now
        program = Pubkey.from_string(entry["address"])
        at = x.gate.record_pda(program, bytes.fromhex(h))
        rec = x.gate.read_record(w.account(at))
        if rec is None:
            continue
        x._check(rec.executable.hex() == h and rec.program == program, f"upgrade_gate's record {at} is for another build or program")
        sigs = list(w.ledger.history(at))
        x._check(bool(sigs), f"no transaction wrote upgrade_gate's record {at}")
        sig = sigs[-1]          # the oldest: the one that wrote it
        x._on_chain(w, sig, (), (str(x.gate.GATE_ID), str(at)))
        rows.append({"program": name, "hash": h, "record": str(at), "signature": sig, "commit": rec.sha, "run": rec.run_id})
    if not rows:
        raise x.Cannot("upgrade_gate holds no record for a build a public id runs now: the builds live were proposed before the gate, or with --ungated")
    st["records"] = rows
    for r in rows:
        book.tx(st, f"upgrade_gate records that run {r['run']} built {r['program']}'s live bytes ({r['hash'][:12]}...) from commit {r['commit'][:12]}",
                r["signature"], "upgrade_gate")
    book.done(st, "upgrade_gate", "upgrade_gate", rows[0]["signature"],
              [f"{r['program']} runs build {r['hash'][:16]}... at its public id, and upgrade_gate's record {r['record']} ties it to commit {r['commit']} "
               f"and run {r['run']} of program.yml" for r in rows])
