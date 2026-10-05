"""Where the seconds of a payment went, stage by stage, and how many attempts did not go through the first time.

    python scripts/latency_stages.py [--events e.json] [--log comments.json] [--repo drexthealpha/Knos] [--rpc URL] [--json]

The headline wait (merge to paid: scripts/network_stats.py, measure()) says how long a person waited. This script
splits each of those payments with what the public relay log and GitHub already give, and nothing else:

    runner_queue   the merge (GitHub's merged_at)        -> the workflow run's start
    workflow       the run's start                       -> the token's comment
    relay_wait     the token's comment                   -> the relay picking it up
    first_send     pickup                                -> the block of the token's first transaction
    confirm        that block                            -> the block of the transaction that paid

`workflow`, `relay_wait` and the relay's own `chain` seconds (pickup to its last confirmation) are on the token's log
line (`workflow=`, `wait=`, `chain=`; `queue=` is the part of runner_queue that GitHub records as the run waiting for
a runner, printed beside it). runner_queue is what is left of the measured wait before the run began: the whole wait,
less workflow, relay_wait and chain. It also holds the time GitHub took to start the run at all, and a run that was
asked for again later. first_send and confirm split `chain` by the block times of the line's transactions; the log
names the last three of a token's transactions, so "first" is the first of those (`--rpc` reads their block times;
without it the two are left out and `chain` stands for both). A stage is measured only where the line carries it:
every stage prints its own n.

THE FIVE STATES. A payment is received, accepted, submitted, confirmed, finalized (docs/RELAY.md has the table), and
the second table says how long each state took to reach from the one before it:

    received    the merge                              -> the workflow run's start         (runner_queue: GitHub's)
    accepted    the run's start                        -> the token posted for a relay     (`workflow=`; ends at `queued_at=`)
    submitted   the token posted (`queued_at=`)        -> the relay's first send (`sent_at=`)
    confirmed   the first send                         -> the last confirmation (`confirmed_at=`)
    finalized   the last confirmation                  -> the cluster finalized it         (the settle comment's `knos-states`
                                                          line, when --log holds those comments too; no relay waits for it)

Since 0.3.16 every ok line carries queued_at, seen_at, sent_at and confirmed_at, whoever relayed. A payment whose line
has none of them (an older line), or whose relay sent nothing itself (`sent_at=-`: someone else carried it first), is
NOT in that table and is NOT dropped: it is listed under it, by token, with its whole wait.

Then the attempts (network_stats.attempts): the payments asked for, the ones that completed, the lines that failed,
the ones that took more than one try, the ones completed only after a failed line. That is "successful completion
across all attempts, including interrupted ones". The log holds what a relay answered: a token no relay picked up
has no line.

At release time it runs against the live log and chain (GH_TOKEN for GitHub's rate limit; --events is what
`scripts/network_stats.py --events-out` wrote, else the chain is read). tests/test_latency_stages.py runs it on a
recorded sample.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "src", ROOT / "scripts"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import network_stats as ns  # noqa: E402

STAGES = ("runner_queue", "workflow", "relay_wait", "first_send", "confirm")
ALSO = ("queued", "chain")      # GitHub's own record of the wait for a runner (inside runner_queue); the relay's pickup-to-confirmed (first_send + confirm)
_PART = {"queue": "queued", "workflow": "workflow", "wait": "relay_wait", "chain": "chain", "tries": "tries"}
STATES = ("received", "accepted", "submitted", "confirmed", "finalized")       # each: seconds from the state before it (received: from the merge)
TIMES = ("queued_at", "seen_at", "sent_at", "confirmed_at")                     # on every ok line since 0.3.16 (src/knos/proof/ghrelay.py)
_STATES_LINE = re.compile(r"<!-- knos-states ([^\n]*)")                          # the settle comment's own line: since= received= ... tx=<signature>


def _head(rest: str) -> list[list[str]]:
    """The `key=value` fields of an ok line, read before `note=`: the note is free text."""
    return [p.split("=", 1) for p in re.split(r"(?:^| )note=", rest, maxsplit=1)[0].split() if "=" in p]


def times_of(comments: list[dict]) -> dict[str, dict[str, float | None]]:
    """token id -> the four times its ok line carries, in Unix seconds (None for one the line gives as `-`). A token
    whose line has none of the four is not in the answer."""
    out: dict[str, dict[str, float | None]] = {}
    for c in comments:
        for line in (c.get("body") or "").splitlines():
            m = ns._RELAY.match(line.strip())
            got = {k: (float(v) if re.fullmatch(r"\d+(\.\d+)?", v) else None) for k, v in (_head(m.group(5)) if m else []) if k in TIMES}
            if got:
                out[m.group(4)] = got
    return out


def finalized_of(comments: list[dict]) -> dict[str, float]:
    """signature -> seconds from confirmed to finalized, from the `knos-states` line of each settle comment that names
    its paying transaction (`tx=`) and reached both states."""
    out: dict[str, float] = {}
    for c in comments:
        for m in _STATES_LINE.finditer(c.get("body") or ""):
            f = dict(p.split("=", 1) for p in m.group(1).split() if "=" in p)
            try:
                if f.get("tx") and float(f["finalized"]) >= float(f["confirmed"]):
                    out[f["tx"]] = float(f["finalized"]) - float(f["confirmed"])
            except (KeyError, ValueError):
                continue
    return out


def states(sample: dict, parts: dict[str, int], at: dict[str, float | None] | None, final: dict[str, float] | None = None) -> dict[str, int] | None:
    """One payment's five states, each in seconds from the state before it and only where it can be told; None when
    its line cannot say when it was submitted and confirmed (no `_at` fields, or a relay that sent nothing itself)."""
    if not at or any(at.get(k) is None for k in TIMES):
        return None
    queued, sent, confirmed = float(at["queued_at"] or 0), float(at["sent_at"] or 0), float(at["confirmed_at"] or 0)
    out = {"submitted": max(0, round(sent - queued)), "confirmed": max(0, round(confirmed - sent))}
    if "workflow" in parts:
        out["accepted"] = parts["workflow"]
        out["received"] = max(0, int(sample["seconds"]) - parts["workflow"] - out["submitted"] - out["confirmed"])
    done = next((final[s] for s in sample.get("sigs") or [] if final and s in final), None)
    if done is not None:
        out["finalized"] = round(done)
    return out


def parts_of(comments: list[dict]) -> dict[str, dict[str, int]]:
    """token id -> what its ok line says of its stages: {queued, workflow, relay_wait, chain, tries}, each when the
    line carries it. Read before `note=`: the note is free text."""
    out: dict[str, dict[str, int]] = {}
    for c in comments:
        for line in (c.get("body") or "").splitlines():
            m = ns._RELAY.match(line.strip())
            if m:
                out[m.group(4)] = {_PART[k]: int(v) for k, v in _head(m.group(5)) if k in _PART and v.isdigit()}
    return out


def split(sample: dict, parts: dict[str, int], when: Callable[[str], int | None] | None = None) -> dict[str, int]:
    """One payment's stages, in seconds, each only where it can be told. `sample`: one of measure()'s (`seconds`: the
    merge to the paying block; `sigs`: the line's transactions). `when(signature)`: its block time, or None."""
    out = {k: parts[k] for k in ("workflow", "relay_wait", "queued", "chain") if k in parts}
    if all(k in parts for k in ("workflow", "relay_wait", "chain")):
        out["runner_queue"] = max(0, int(sample["seconds"]) - parts["workflow"] - parts["relay_wait"] - parts["chain"])
    times = [t for t in (when(s) for s in sample.get("sigs") or []) if t is not None] if when else []
    if "chain" in parts and times:
        out["confirm"] = min(parts["chain"], max(times) - min(times))
        out["first_send"] = parts["chain"] - out["confirm"]
    return out


def spread(values: list[int]) -> dict:
    """{n, p50, p95, max}: the median, the 95th percentile by nearest rank (as measure() takes it), the longest."""
    took = sorted(values)
    if not took:
        return {"n": 0, "p50": None, "p95": None, "max": None}
    return {"n": len(took), "p50": int(statistics.median(took)), "p95": took[max(0, math.ceil(0.95 * len(took)) - 1)], "max": took[-1]}


def report(comments: list[dict], events: list[dict], get=None, when: Callable[[str], int | None] | None = None, most: int = ns.MOST) -> dict:
    """{"whole": merge to paid as measure() gives it, "stages": {stage: {n, p50, p95, max}}, "states": the same for
    each of the five states, "without_times": the payments whose line cannot place them in that table ([{token, at,
    seconds, why}], every one of them), "slowest": the slowest payments with their own stages, "attempts":
    network_stats.attempts(...)}."""
    m = ns.measure("merge_to_paid", ns.relay_lines(comments), events, get, most)
    parts, at, final = parts_of(comments), times_of(comments), finalized_of(comments)
    rows = [{"token": s["token"], "at": s["at"], "seconds": s["seconds"], **split(s, parts.get(s["token"], {}), when)} for s in m["samples"]]
    five = {s["token"]: states(s, parts.get(s["token"], {}), at.get(s["token"]), final) for s in m["samples"]}
    apart = [{"token": s["token"], "at": s["at"], "seconds": s["seconds"],
              "why": "its line has no stage times (written before 0.3.16)" if s["token"] not in at else "its relay sent nothing itself: another relayer carried it first"}
             for s in m["samples"] if five[s["token"]] is None]
    return {"whole": {**spread([r["seconds"] for r in rows]), "lines": m["lines"], "not_timed": m["not_timed"], "window": m["window"]},
            "stages": {name: spread([r[name] for r in rows if name in r]) for name in (*STAGES, *ALSO)},
            "states": {name: spread([f[name] for f in five.values() if f and name in f]) for name in STATES},
            "without_times": apart,
            "slowest": sorted(rows, key=lambda r: -r["seconds"])[:5],
            "attempts": ns.attempts(comments, ns.ATTEMPTS["pay"])}


def render(r: dict) -> list[str]:
    """The report as lines a person reads."""
    w, a = r["whole"], r["attempts"]
    cell = lambda v: "-" if v is None else str(v)  # noqa: E731
    out = [f"merge to paid, {w['n']} payments" + (f" ({w['window']['from']} to {w['window']['to']})" if w.get("window") else "")
           + f": p50 {cell(w['p50'])} s, p95 {cell(w['p95'])} s, max {cell(w['max'])} s; {w['not_timed']} of {w['lines']} log lines could not be timed",
           "", f"{'stage':<14}{'n':>5}{'p50':>7}{'p95':>7}{'max':>7}   seconds"]
    for name in (*STAGES, *ALSO):
        s = r["stages"][name]
        out.append(f"{name:<14}{s['n']:>5}{cell(s['p50']):>7}{cell(s['p95']):>7}{cell(s['max']):>7}"
                   + ("   (inside runner_queue: GitHub's record of the run waiting for a runner)" if name == "queued" else
                      "   (first_send + confirm: the relay's pickup to its last confirmation)" if name == "chain" else ""))
    covered = w["n"] - len(r["without_times"])
    out += ["", f"the five states, {covered} of {w['n']} payments (the ones whose log line carries queued_at, seen_at, sent_at and confirmed_at):",
            f"{'state':<14}{'n':>5}{'p50':>7}{'p95':>7}{'max':>7}   seconds from the state before"]
    notes = {"received": "from the merge: GitHub starting the run", "accepted": "the run: install, checks read, GitHub's signature",
             "submitted": "the token waiting for a relay, and its first send", "confirmed": "the cluster confirming",
             "finalized": "the cluster finalizing (from settle comments in --log)"}
    for name in STATES:
        s = r["states"][name]
        out.append(f"{name:<14}{s['n']:>5}{cell(s['p50']):>7}{cell(s['p95']):>7}{cell(s['max']):>7}   ({notes[name]})")
    out += [f"not in that table, {len(r['without_times'])} payment{'' if len(r['without_times']) == 1 else 's'}:"]
    out += [f"  token {x['token']}  {x['seconds']:>6} s  {x['why']}" for x in r["without_times"]] or ["  none"]
    out += ["", "the slowest, each with its own stages:"]
    out += [f"  {x['seconds']:>6} s  token {x['token']}  " + " ".join(f"{k}={x[k]}" for k in (*STAGES, *ALSO) if k in x) for x in r["slowest"]] or ["  none"]
    share = "-" if a["completion"] is None else f"{a['completion'] * 100:.1f}%"
    out += ["", f"successful completion across all attempts, including interrupted ones: {a['completed']} of {a['asked']} payments ({share})",
            f"  {a['lines']} log lines with a token; {a['failed']} failed; {a['retried']} took more than one try ({a['tries']} tries in all); "
            f"{a['after_failure']} completed only after a failed line; {a['never']} never completed; {a['misposted']} comments could not carry their token"]
    out += [f"  failed {n}x: {why}" for why, n in list(a["reasons"].items())[:8]]
    return out


def block_times(rpc: str) -> Callable[[str], int | None]:
    """signature -> its block time on the cluster at `rpc`, asked once each; None when the cluster does not say."""
    from knos import chain
    kept: dict[str, int | None] = {}

    def when(sig: str) -> int | None:
        if sig not in kept:
            try:
                kept[sig] = (chain.call(rpc, "getTransaction", [sig, {"commitment": "confirmed", "maxSupportedTransactionVersion": 1}], timeout=20) or {}).get("blockTime")
            except Exception:  # noqa: BLE001 - the public endpoint throttles: that payment's last two stages are left out
                kept[sig] = None
        return kept[sig]
    return when


def main(argv: list[str] | None = None, say: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--log", type=Path, help="the relay log's comments as GitHub returns them (JSON); default: read from --repo")
    ap.add_argument("--events", type=Path, help="the escrows' history, as scripts/network_stats.py --events-out wrote it; default: read from the chain")
    ap.add_argument("--repo", default=ns.RELAY_LOG_REPO, help="the repository whose relay log is read")
    ap.add_argument("--rpc", default=os.environ.get("KNOS_RPC", ""), help="a cluster to read block times (and, without --events, the history) from")
    ap.add_argument("--offline", action="store_true", help="ask GitHub nothing: only lines that carry their own start are timed")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    a = ap.parse_args(argv)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    get = None if a.offline else (lambda path: ns.github(path, token))
    if a.log:
        comments = json.loads(a.log.read_text(encoding="utf-8"))
        comments = comments.get("comments", comments) if isinstance(comments, dict) else comments
    elif get is None:
        say("stopped: --offline needs --log FILE (the relay log's comments).")
        return 1
    else:
        comments = ns.relay_log(get, a.repo)
    if a.events:
        events = json.loads(a.events.read_text(encoding="utf-8"))
    elif a.rpc:
        from knos.settle import pay
        from knos.settle.v2 import pay as pay2
        events = sorted((ev for program in (pay.PAY_ID, pay2.PAY_ID) for ev in ns.history(a.rpc, program, 1000)[0]), key=lambda ev: ev["at"])
    else:
        say("stopped: give --events FILE (python scripts/network_stats.py --events-out FILE) or --rpc URL: the paying blocks' times are the chain's.")
        return 1
    r = report(comments, events, get, block_times(a.rpc) if a.rpc else None)
    for line in ([json.dumps(r, indent=1)] if a.json else render(r)):
        say(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
