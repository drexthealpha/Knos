"""The upgrade proposals of the Knos programs, as a file and a feed people can subscribe to.

    python scripts/upgrade_feed.py [--rpc URL] [--out web] [--check]

Every change to a program of the second deployment is a proposal of the upgrade multisig (Squads v4), public on chain
for 48 hours before it can run. This script reads every proposal the multisig has made and writes

    web/upgrades.json   one entry per upgrade proposal: program, proposed build hash, source commit, earliest execution
                        time, status (pending, executed, cancelled, replaced)
    web/upgrades.xml    the same entries as an Atom feed: subscribe to it and a new proposal arrives in a feed reader

Where each fact is read from (all through `account(address) -> (owner, data) or None`, so the tests need no network):

    the proposals       the multisig account's transaction_index, then ["multisig", multisig, "transaction", index,
                        "proposal"] and the transaction beside it, with the readers of src/knos/mainnet_check.py (the
                        same layouts scripts/governance.mjs writes and web/upgrade.js reads)
    the build hash      sha256 of the proposal's buffer without its header and trailing zeros: what
                        `solana-verify get-executable-hash` prints. A buffer is closed when its upgrade runs, so for a
                        proposal that has run the hash comes from the entry this script wrote while it was pending
                        (the previous upgrades.json), else from the program itself when it is the newest upgrade that
                        ran, else it is not known and the entry says so
    the source commit   upgrade_gate's record ["build", program, hash] (examples/upgrade_gate): the commit GitHub's
                        runner built those bytes from. No record: the entry says nobody but the members vouches for it
    the earliest time   the proposal's approval time + the multisig's time lock; none until it is approved

Status: `pending` is Draft, Active, Approved or Executing; `executed` ran; a proposal that was cancelled, rejected or
made void (at or below the multisig's stale index) is `replaced` when a later proposal upgrades the same program,
else `cancelled`.

The network read runs at release time and whenever the site is built; a run that cannot read the cluster
writes nothing and exits 2, so a stale file is never passed off as a fresh one. --check exits 1 while a proposal is
pending.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from solders.pubkey import Pubkey  # noqa: E402

from knos import chain, mainnet_check as mc  # noqa: E402
from knos.settle.v2 import gate  # noqa: E402

SITE = "https://drexthealpha.github.io/Knos/"
FEED = SITE + "upgrades.xml"
PROGRAMS = ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")      # every program whose upgrade authority is the multisig's vault
MOST = 200                                                             # proposals read, newest first: far more than a release makes
PENDING = ("Draft", "Active", "Approved", "Executing")
EXPLORER = "https://explorer.solana.com/address/{}?cluster=devnet"


@dataclass
class Entry:
    index: int
    program: str                    # knos_pay, ...
    program_address: str
    buffer: str
    build_hash: str | None          # hex; None: the buffer is closed and no earlier read of it is on file
    hash_from: str | None           # "buffer", "earlier feed" or "program": where build_hash was read
    source_commit: str | None       # the commit upgrade_gate recorded for build_hash; None: no record
    gate_run: int | None            # the GitHub Actions run that built it
    status: str                     # pending, executed, cancelled, replaced
    squads_status: str              # the multisig's own word: Draft, Active, Approved, Executing, Executed, Rejected, Cancelled
    approved: int
    threshold: int
    earliest_execution: int | None  # unix seconds; None until the proposal is approved
    since: int                      # when the proposal entered squads_status (0: Executing holds no time)
    proposal: str                   # the proposal account


def utc(t: int | None) -> str | None:
    return None if t is None else datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def buffer_hash(account: mc.Account, buffer: str) -> str | None:
    """The executable hash of a program buffer; None when the account is not one (closed, or never written)."""
    got = account(buffer)
    if not got or str(got[0]) != str(mc.LOADER) or len(got[1]) < gate.BUFFER_HEADER or got[1][:4] != (1).to_bytes(4, "little"):
        return None
    return gate.executable_hash(got[1][gate.BUFFER_HEADER:]).hex()


def program_hash(account: mc.Account, program: str) -> str | None:
    """The executable hash of what the program runs now; None when it is not deployed."""
    got = account(str(mc.programdata_address(program)))
    if not got or len(got[1]) <= mc.PROGRAMDATA_HEADER:
        return None
    return gate.executable_hash(got[1][mc.PROGRAMDATA_HEADER:]).hex()


def gate_record(account: mc.Account, program: str, build_hash: str | None) -> gate.Record | None:
    if build_hash is None:
        return None
    at = gate.record_pda(Pubkey.from_string(program), bytes.fromhex(build_hash))
    got = account(str(at))
    r = gate.read_record(got[1]) if got and str(got[0]) == str(gate.GATE_ID) else None
    return r if r is not None and r.executable.hex() == build_hash and str(r.program) == program else None


def status_of(squads_status: str, void: bool, later: bool) -> str:
    """`void`: at or below the multisig's stale index. `later`: a proposal with a higher index upgrades the same program."""
    if squads_status == "Executed":
        return "executed"
    if squads_status in PENDING and not void:
        return "pending"
    return "replaced" if later else "cancelled"


def entries(account: mc.Account, ids: dict, previous: list[dict] | None = None, most: int = MOST) -> tuple[mc.Multisig, list[Entry]]:
    """Every upgrade proposal of a Knos program, newest first. `previous`: the entries of the last upgrades.json, which
    keep what the chain forgets (a buffer is closed when its upgrade runs; a transaction account can be closed too)."""
    squads, multisig = ids["squads_program"], ids["upgrade_multisig"]
    ms, why = mc.multisig_at(account, multisig, squads)
    if ms is None:
        raise SystemExit(f"stopped: the upgrade multisig could not be read ({why}). Nothing was written.")
    names = {ids[n]: n for n in PROGRAMS if n in ids}
    before = {e["index"]: e for e in previous or []}
    squads_key, ms_key = Pubkey.from_string(squads), Pubkey.from_string(multisig)
    found: list[tuple[int, mc.Proposal, str, str, str]] = []
    for index in range(ms.transaction_index, max(0, ms.transaction_index - most), -1):
        at = str(mc.proposal_address(ms_key, index, squads_key))
        got = account(at)
        p = mc.read_proposal(got[1]) if got and str(got[0]) == squads else None
        if p is None:
            continue                                            # a transaction nobody proposed, or an account closed since
        tx = account(str(mc.transaction_address(ms_key, index, squads_key)))
        kind, program, buffer = mc.read_transaction(tx[1] if tx and str(tx[0]) == squads else None)
        old = before.get(index)
        if kind != "upgrade" and old and tx is None:            # the transaction account was closed after it ran: what it was is on file
            kind, program, buffer = "upgrade", old["program_address"], old["buffer"]
        if kind == "upgrade" and program in names:
            found.append((index, p, at, program, buffer))
    newest_ran = {}                                             # program -> the index of the newest upgrade that ran
    for index, p, _at, program, _buffer in found:
        if p.status == "Executed":
            newest_ran.setdefault(program, index)
    out = []
    for index, p, at, program, buffer in found:
        old = before.get(index) if before.get(index, {}).get("buffer") == buffer else None
        h, where = buffer_hash(account, buffer), "buffer"
        if h is None and old and old.get("build_hash"):
            h, where = old["build_hash"], "earlier feed"
        if h is None and p.status == "Executed" and newest_ran.get(program) == index:
            h, where = program_hash(account, program), "program"
        rec = gate_record(account, program, h)
        void = index <= ms.stale_transaction_index
        later = any(i > index and prog == program for i, _p, _a, prog, _b in found)
        out.append(Entry(index=index, program=names[program], program_address=program, buffer=buffer, build_hash=h,
                         hash_from=where if h else None, source_commit=rec.sha if rec else None, gate_run=rec.run_id if rec else None,
                         status=status_of(p.status, void, later), squads_status=p.status, approved=p.approved, threshold=ms.threshold,
                         earliest_execution=p.at + ms.time_lock if p.status == "Approved" else (old or {}).get("earliest_execution")
                         if p.status in ("Executing", "Executed", "Cancelled") else None,
                         since=p.at, proposal=at))
    return ms, out


def words(e: Entry) -> str:
    """One entry in plain words: what is proposed, by which build, and what a reader can do about it."""
    build = (f"build {e.build_hash}" if e.build_hash else "a build whose hash can no longer be read (its buffer is closed and no earlier read is on file)")
    source = (f"GitHub's runner built it from commit {e.source_commit} (run {e.gate_run}, recorded on chain by upgrade_gate)" if e.source_commit else
              "upgrade_gate holds no record of this build: no GitHub run vouches for these bytes" if e.build_hash else "its source commit is not known")
    if e.status == "pending":
        state = (f"The multisig approved it ({e.approved} of {e.threshold}); it can run from {utc(e.earliest_execution)}." if e.earliest_execution else
                 f"{e.approved} of {e.threshold} approvals so far; it can run 48 hours after the vote that approves it.")
        todo = (" Until then: read the diff at that commit, compare the hash with your own build (docs/ASSURANCE.md), and if you do not "
                "accept it, withdraw a Balance now and cancel a wallet-funded order (docs/GOVERNANCE.md).")
    elif e.status == "executed":
        state, todo = f"It ran: {e.program} now runs this build (the multisig marked it executed at {utc(e.since)}).", ""
    elif e.status == "replaced":
        state, todo = "It was withdrawn before it ran, and a later proposal for the same program took its place.", ""
    else:
        state, todo = "It was cancelled before it ran. The program is unchanged by it.", ""
    return f"Proposal {e.index} would replace the code of {e.program} ({e.program_address}) with {build}; {source}. {state}{todo}"


def as_json(ms: mc.Multisig, got: list[Entry], ids: dict, now: int, cluster: str) -> str:
    return json.dumps({
        "note": "Written by scripts/upgrade_feed.py from the upgrade multisig's accounts. Do not edit.",
        "generated": utc(now), "cluster": cluster, "feed": FEED, "multisig": ids["upgrade_multisig"],
        "time_lock": ms.time_lock, "threshold": ms.threshold, "members": len(ms.members),
        "pending": sum(e.status == "pending" for e in got),
        "entries": [{**asdict(e), "earliest_execution_utc": utc(e.earliest_execution), "words": words(e)} for e in got],
    }, indent=1) + "\n"


def as_atom(got: list[Entry], ids: dict, now: int) -> str:
    """Atom 1.0 (RFC 4287). An entry keeps its id for life; its title and `updated` change with its status, which is
    how a feed reader shows that a pending proposal ran or was withdrawn."""
    def one(e: Entry) -> str:
        changed = max(e.since, 0) or now
        title = f"{e.program}: upgrade proposal {e.index} is {e.status}" + (f", can run from {utc(e.earliest_execution)}" if e.status == "pending" and e.earliest_execution else "")
        return ("<entry>"
                f"<id>tag:drexthealpha.github.io,2026:knos/upgrade/{ids['upgrade_multisig']}/{e.index}</id>"
                f"<title>{escape(title)}</title><updated>{utc(changed)}</updated>"
                f'<link rel="alternate" href="{escape(EXPLORER.format(e.proposal), {chr(34): "&quot;"})}"/>'
                f'<category term="{e.status}"/><category term="{e.program}"/>'
                f"<summary>{escape(words(e))}</summary></entry>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
            f"<id>tag:drexthealpha.github.io,2026:knos/upgrades/{ids['upgrade_multisig']}</id>"
            "<title>Knos: upgrade proposals of the programs</title>"
            "<subtitle>Every proposal to change a Knos program, from the upgrade multisig on Solana devnet. A proposal can run 48 hours after it is approved.</subtitle>"
            f'<link rel="self" href="{FEED}"/><link rel="alternate" href="{SITE}"/>'
            f"<author><name>Knos</name></author><updated>{utc(now)}</updated>"
            + "".join(one(e) for e in got) + "</feed>\n")


def write(out: Path, account: mc.Account, ids: dict, now: int, cluster: str) -> list[Entry]:
    old = out / "upgrades.json"
    previous = json.loads(old.read_text(encoding="utf-8")).get("entries") if old.exists() else None
    ms, got = entries(account, ids, previous)
    old.write_text(as_json(ms, got, ids, now, cluster), encoding="utf-8", newline="")
    (out / "upgrades.xml").write_text(as_atom(got, ids, now), encoding="utf-8", newline="")
    return got


def main(argv: list[str] | None = None, say: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rpc", default=mc.PUBLIC["devnet"], help="the cluster the multisig is read from")
    ap.add_argument("--out", type=Path, default=ROOT / "web", help="where upgrades.json and upgrades.xml go")
    ap.add_argument("--check", action="store_true", help="exit 1 while a proposal is pending")
    a = ap.parse_args(argv)
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text(encoding="utf-8"))
    try:
        now, cluster = chain.Ledger(a.rpc).now(), mc._cluster(a.rpc)
        got = write(a.out, mc._rpc(a.rpc), ids, now, cluster)
    except SystemExit:
        raise
    except Exception as why:  # noqa: BLE001 - no network is not an empty feed
        say(f"stopped: {a.rpc} could not be read ({type(why).__name__}: {why}). Nothing was written; run it again when the cluster answers.")
        return 2
    for e in got:
        say(words(e))
    pending = sum(e.status == "pending" for e in got)
    say(f"{len(got)} upgrade proposals, {pending} pending; wrote {a.out / 'upgrades.json'} and {a.out / 'upgrades.xml'}")
    return 1 if a.check and pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
