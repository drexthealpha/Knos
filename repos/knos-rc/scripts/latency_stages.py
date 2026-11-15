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

THE FIVE STATES. A payment is received, accepted, submitted, confirmed, finalized (docs/reference/RELAY.md has the table), and
the second table says how long each state took to reach from the one before it:

    received    the merge                              -> the workflow run's start         (runner_queue: GitHub's)
    accepted    the run's start                        -> the token posted for a relay     (`workflow=`; ends at `queued_at=`)
    submitted   the token posted (`queued_at=`)        -> the relay's first send (`sent_at=`)
    confirmed   the first send                         -> the last confirmation (`confirmed_at=`)
    finalized   the last confirmation                  -> the cluster finalized it         (the settle comment's `knos-states`
                                                          line, when --log holds those comments too; no relay waits for it)

Every ok line written since release 0.3.16 (October 2026) carries queued_at, seen_at, sent_at and confirmed_at, whoever relayed. A payment whose line
has none of them (an older line), or whose relay sent nothing itself (`sent_at=-`: someone else carried it first), is
NOT in that table and is NOT dropped: it is listed under it, by token, with its whole wait.

Then the attempts (network_stats.attempts): the payments asked for, the ones that completed, the lines that failed,
the ones that took more than one try, the ones completed only after a failed line. That is "successful completion
across all attempts, including interrupted ones". The log holds what a relay answered: a token no relay picked up
has no line.

THE SIX STAGES, ONE TABLE (`--md` prints it alone, as Markdown; the JSON report carries it as `six`). The same
measurements under the names a reader asks for, each with its own n, p50 and p95:

    workflow scheduling   the merge                      -> the workflow run's start        (runner_queue)
    evaluation            the run's start                -> the token's comment             (workflow)
    relay pickup          the token's comment            -> a relay taking it up            (relay_wait)
    submission            pickup                         -> the first transaction's block   (first_send; needs --rpc)
    confirmation          that block                     -> the paying transaction's block  (confirm; needs --rpc)
    finality              the last confirmation          -> the cluster finalized it        (the settle comment's line)

A stage no line recorded prints "not recorded" in every cell. Nothing is filled in from another stage or guessed.

THE FIVE CLOCKS (`--clocks` prints the table; the JSON report carries it as `clocks`; docs/reference/LOAD.md has it). The six
stages are one wait cut in six. A reader who asks "how fast is it" asks about five different clocks, and only one of
them is Knos's own to shorten:

    work execution               the forge starts a runner and runs the job    workflow scheduling, evaluation
    evidence availability        the signed token reaches whoever acts on it   relay pickup
    Knos decision processing     the token in hand -> accepted or not          `knos decide` (scripts/decide_bench.py:
                                                                               measured on one machine, no network; on
                                                                               devnet 4.3 to 32.6 s, four runs of the release 0.3.18 command, October 2026)
    chain inclusion              the first send -> the paying transaction at   submission, confirmation; and finality,
                                 the commitment level `confirmed`              which is the level `finalized`
    bank availability            not applicable: no bank route                 nothing: Knos pays test USDC on devnet

Every row carries its own n and says where it was measured. A clock nothing measured says so. No row is a sum of
two others: percentiles of different samples do not add.

THE SIX LATENCIES, EACH ON ITS OWN (`--separate`; docs/reference/BENCH.md, "Every latency, apart"). The names a buyer
asks by, and no row is a sum of others:

    evidence arrival      the merge -> the run's start, and the token's comment -> a relay holding it (two rows: two samples)
    evaluation            the run's start -> the token's comment (the judging job, and the forge's signature)
    decision              the token in hand -> the provisional receipt (`knos decide`: scripts/decide_bench.py here,
                          and the last release run's sample on devnet; docs/bench.json `decision`)
    chain confirmation    pickup -> the first transaction's block -> the paying transaction's block, at `confirmed`
    finality              the last confirmation -> the cluster finalized it
    payout                the paying transaction IS the payout (test USDC into the payee's token account): nothing
                          comes after it to time. To a bank: not applicable, there is no bank route

    python scripts/latency_stages.py --separate --recorded             # from docs/bench.json: no network
    python scripts/latency_stages.py --separate --rpc URL --write      # THE RELEASE RUN'S ONE COMMAND: measures the live log
                                                                       # and chain, keeps it in docs/bench.json (`stages`)
                                                                       # and rewrites the block in docs/reference/BENCH.md

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
import time
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


# the six stages a reader asks for: (name, where report() holds it, its key there, what it runs from and to)
SIX = (("workflow scheduling", "stages", "runner_queue", "the merge to the start of the workflow run"),
       ("evaluation", "stages", "workflow", "the start of the run to the token's comment"),
       ("relay pickup", "stages", "relay_wait", "the token's comment to a relay taking it up"),
       ("submission", "stages", "first_send", "pickup to the block of the first transaction"),
       ("confirmation", "stages", "confirm", "that block to the block of the paying transaction"),
       ("finality", "states", "finalized", "the last confirmation to the cluster finalizing it"))
NOT_RECORDED = "not recorded"


def six(r: dict) -> list[dict]:
    """The six stages of `report()`'s answer, in order: [{stage, n, p50, p95, what}]. A stage with no sample has n 0
    and no figures."""
    out = []
    for name, part, key, what in SIX:
        got = (r.get(part) or {}).get(key) or {}
        n = int(got.get("n") or 0)
        out.append({"stage": name, "n": n, "p50": got.get("p50") if n else None, "p95": got.get("p95") if n else None,
                    "p99": got.get("p99") if n else None, "max": got.get("max") if n else None, "what": what})
    return out


COMMITMENT = "confirmed"        # the level the relay waits for and `block_times` asks at; `finalized` is the finality row
NO_BANK = "not applicable: no bank route"
# the five clocks: (clock, the six-stage rows that measure it, whose wait it is, the target)
CLOCKS = (("work execution", ("workflow scheduling", "evaluation"),
           "GitHub's: starting a runner, and the job. Knos's share is the job's install and its reads",
           "none set: the forge must run a job and sign, so this clock cannot reach zero"),
          ("evidence availability", ("relay pickup",),
           "Knos's own, all of it: a relay finding the token (a pass over the comments every 3 s)",
           "0 s for a run that relays its own token; otherwise one pass"),
          ("Knos decision processing", (),
           "Knos's own, all of it",
           "targets on one machine with no network, not measurements: 100 ms at p95 for the offline decision once the evidence is in hand, 200 ms for a cached one. No target is set for a decision that reads a cluster: that took 4.3 to 32.6 s on devnet"),
          (f"chain inclusion, at `{COMMITMENT}`", ("submission", "confirmation"),
           "the cluster's, and the relay's sends: two verification transactions for a 2048-bit RSA key, then the payment",
           "none set: measured apart, at this commitment level"),
          ("chain inclusion, at `finalized`", ("finality",),
           "the cluster's; no relay waits for it",
           "none set"),
          ("bank availability", (), NO_BANK, NO_BANK))


def clocks(six_rows: list[dict], decision: dict | None = None, whole: dict | None = None) -> list[dict]:
    """The five clocks as rows, each with its own sample: [{clock, part, where, n, p50, p95, unit, whose, target}].
    `six_rows`: `six()`'s. `decision`: what scripts/decide_bench.py measured ({rows: {name: {n, p50, p95}}, machine}),
    in milliseconds, or None (then that clock says it was not measured). `whole`: the payments timed at all, so a
    row can say "5 of 41"."""
    by = {row["stage"]: row for row in six_rows}
    of = f" of {whole['n']} payments" if whole and whole.get("n") else ""
    out: list[dict] = []
    for name, parts, whose, target in CLOCKS:
        if name == "Knos decision processing":
            got = (decision or {}).get("rows") or {}
            for part in ("fresh, accepted", "cached, accepted"):
                d = got.get(part) or {}
                n = int(d.get("n") or 0)
                out.append({"clock": name, "part": f"`knos decide`, {part.split(',')[0]}: the token in hand to the provisional receipt", "n": n,
                            "p50": round(d["p50"], 1) if n else None, "p95": round(d["p95"], 1) if n else None, "unit": "ms",
                            "where": f"locally, {n} decisions on one machine with the chain simulated in the same process: no network. Not measured on devnet in this row: the devnet sample stands under the table"
                                     if n else "not measured", "whose": whose, "target": target})
            continue
        if not parts:
            out.append({"clock": name, "part": NO_BANK, "n": 0, "p50": None, "p95": None, "unit": "s", "where": NO_BANK, "whose": whose, "target": target})
            continue
        for part in parts:
            row = by.get(part) or {}
            n = int(row.get("n") or 0)
            out.append({"clock": name, "part": f"{part}: {row.get('what') or ''}".rstrip(": "), "n": n, "p50": row.get("p50") if n else None,
                        "p95": row.get("p95") if n else None, "unit": "s", "where": f"devnet, {n}{of}" if n else NOT_RECORDED, "whose": whose, "target": target})
    return out


BENCH_JSON, BENCH_MD = ROOT / "docs" / "bench.json", ROOT / "docs" / "reference" / "BENCH.md"
SEP_OPEN, SEP_CLOSE = "<!-- latency:separate -->", "<!-- /latency:separate -->"
RELEASE_COMMAND = "python scripts/latency_stages.py --separate --rpc https://api.devnet.solana.com --write"
NO_GAP = "not a wait: the paying transaction is the payout"
# the six latencies: (name, the six-stage rows that measure it, whose wait it is)
FEW = "none: fewer than 30 samples"
PART_WHOSE = {"workflow scheduling": "the forge's: starting a runner", "relay pickup": "Knos's own: a relay finding the token"}
SEPARATE = (("evidence arrival", ("workflow scheduling", "relay pickup"), ""),
            ("evaluation", ("evaluation",), "the forge's runner: the judging job, then the forge signs what it found"),
            ("decision", (), "Knos's own, all of it"),
            (f"chain confirmation, at `{COMMITMENT}`", ("submission", "confirmation"), "the cluster's, and the relay's sends"),
            ("finality, at `finalized`", ("finality",), "the cluster's; no relay waits for it"),
            ("payout", (), "nobody's"))


def separate(six_rows: list[dict], decision: dict | None = None, whole: dict | None = None) -> list[dict]:
    """The six latencies as rows, each with its own sample: [{latency, part, where, n, p50, p95, unit, whose}].
    `six_rows`: `six()`'s. `decision`: docs/bench.json's `decision` ({local: what scripts/decide_bench.py measured on
    one machine, devnet: the last release run's sample}), or None (then the decision says it was not measured). A
    devnet sample of fewer than 30 has a median and no p95."""
    by = {row["stage"]: row for row in six_rows}
    of = f" of {whole['n']} payments" if whole and whole.get("n") else ""
    out: list[dict] = []
    for name, parts, whose in SEPARATE:
        if name == "decision":
            local, dev = (decision or {}).get("local") or {}, (decision or {}).get("devnet") or {}
            warm = (local.get("rows") or {}).get("offline, warm") or {}
            n = int(warm.get("n") or 0)
            out.append({"latency": name, "part": "warm: the token in hand to the provisional receipt, the rules loaded before it arrived (`knos decide --stream`)", "n": n,
                        "p50": round(warm["p50"], 1) if n else None, "p95": round(warm["p95"], 1) if n else None,
                        "max": round(warm["max"], 1) if n and warm.get("max") is not None else None, "unit": "ms", "whose": whose,
                        "where": f"here, on one machine, no network ({local.get('machine')})" if n else "not measured"})
            for key, part in (("offline", "a new process for each token: the rules loaded, then the offline decision"),
                              ("chain_check", "the chain check after it: one request, left behind after 2 s")):
                got = dev.get(key) or {}
                m = int(got.get("n") or 0)
                out.append({"latency": name, "part": part, "n": m, "p50": got.get("median") if m else None, "p95": got.get("p95") if m else None,
                            "max": got.get("slowest") if m else None, "unit": "ms",
                            "whose": whose, **({"p95_note": FEW} if m and got.get("p95") is None else {}), "where": f"devnet, {dev.get('when')}, program ids not recorded: {m} real tokens" if m else "not measured on devnet"})
            continue
        if not parts:
            out.append({"latency": name, "part": "the paying transaction's block to test USDC in the payee's token account", "n": 0, "p50": None, "p95": None,
                        "unit": "s", "where": NO_GAP, "whose": whose})
            out.append({"latency": name, "part": "to a bank account", "n": 0, "p50": None, "p95": None, "unit": "s", "where": NO_BANK, "whose": whose})
            continue
        for part in parts:
            row = by.get(part) or {}
            n = int(row.get("n") or 0)
            out.append({"latency": name, "part": f"{part}: {row.get('what') or ''}".rstrip(": "), "n": n, "p50": row.get("p50") if n else None,
                        "p95": row.get("p95") if n else None, "p99": row.get("p99") if n else None, "max": row.get("max") if n else None,
                        "unit": "s", "where": f"devnet, public program ids, {n}{of}" if n else NOT_RECORDED, "whose": PART_WHOSE.get(part, whose)})
    return out


FEW99 = "none: fewer than 100 samples"
NOT_KEPT = "not kept"


def tail(row: dict, k: str) -> str:
    """The p99 or worst cell of a row: below 100 samples the 99th percentile by nearest rank is the worst one, so it
    is not printed as a band; a figure the record did not keep says so."""
    if k == "p99" and row.get("n", 0) < 100:
        return FEW99
    return NOT_KEPT if row.get(k) is None else f"{row[k]} {row.get('unit', 's')}"


def separate_table(rows: list[dict]) -> list[str]:
    """`separate()`'s rows as a Markdown table, p50, p95, p99 and the worst apart. A row with no sample has no figure,
    and says why."""
    fixed = (NO_BANK, NO_GAP)
    cell = lambda row, k: ("-" if row["where"] in fixed else row["p95_note"] if k == "p95" and row.get("p95_note") else  # noqa: E731
                           NOT_RECORDED if not row["n"] else tail(row, k) if k in ("p99", "max") else
                           NOT_RECORDED if row.get(k) is None else f"{row[k]} {row['unit']}")
    out = ["| latency | what is timed | measured | n | p50 | p95 | p99 | worst | whose wait |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    out += [f"| {r['latency']} | {r['part']} | {r['where']} | {r['n'] if r['n'] else '-' if r['where'] in fixed else NOT_RECORDED} | {cell(r, 'p50')} | {cell(r, 'p95')} | "
            f"{cell(r, 'p99')} | {cell(r, 'max')} | {r['whose']} |" for r in rows]
    return out


ATTEMPT_KEYS = ("asked", "completed", "lines", "failed", "retried", "after_failure", "never")


def attempts_of(kept: dict) -> dict:
    """The pay attempts docs/bench.json keeps: `stages.attempts` (what `--separate --write` keeps since 0.3.21, with
    `reasons`), else the release run's `pay_attempts_*` facts (counts only), else {}. {counts, reasons, source}."""
    st, rel = kept.get("stages") or {}, kept.get("release") or {}
    if st.get("attempts"):
        a = st["attempts"]
        return {**{k: a.get(k) for k in ATTEMPT_KEYS}, "reasons": a.get("reasons"), "source": st.get("source")}
    got = {k: (rel.get(f"pay_attempts_{k}") or {}).get("value") for k in ATTEMPT_KEYS}
    if got["asked"] is None:
        return {}
    whole = {k: (rel.get(f"stage_whole_{k}") or {}).get("value") for k in ("payments", "median", "ninety_fifth", "slowest")}
    return {**got, "reasons": None, "source": (rel.get("pay_attempts_asked") or {}).get("source"), "whole": whole}


def _share(part: int | None, whole: int | None) -> str:
    return "-" if part is None or not whole else f"{part} of {whole} ({part * 100 / whole:.1f}%)"


def attempts_block(kept: dict) -> list[str]:
    """Every payment asked for, with the failures and the ones that never completed: a rate printed with its
    denominator. The waits above are of payments that completed; these are the ones they leave out."""
    a = attempts_of(kept)
    if not a:
        return ["Pay attempts: not recorded. The release run's command keeps them (`stages.attempts` in docs/bench.json)."]
    out = [f"Every payment asked for, on the public program ids, the failed and the unfinished counted ({a['source']}):", "",
           "| pay attempts | count | what is counted |", "| --- | --- | --- |",
           f"| asked for | {a['asked']} | pull requests whose payment the public relay log has a line for |",
           f"| completed | {_share(a['completed'], a['asked'])} | a line says ok |",
           f"| never completed | {_share(a['never'], a['asked'])} | no line says ok: no wait is timed for them, and no percentile counts them |",
           f"| completed only after a failed line | {a['after_failure']} | asked again with a fresh token, then ok |",
           f"| log lines that failed | {_share(a['failed'], a['lines'])} | one line per token a relay answered for |",
           f"| ok lines that took more than one try | {a['retried']} | |"]
    reasons = a.get("reasons")
    if reasons:
        out += ["", "Why each failed line failed, as the line says (its first words):", "", "| reason | lines |", "| --- | --- |",
                *[f"| {why.replace('|', '/')} | {n} |" for why, n in reasons.items()]]
    else:
        out += ["", "Why they failed: that reading kept the counts and not the reasons. The release run's command keeps each line's "
                "reason (`stages.attempts.reasons` in docs/bench.json) and prints it here."]
    w = a.get("whole")
    if w and w.get("payments"):
        out += ["", f"The same reading timed {w['payments']} of the {a['completed']} completed payments from the merge: p50 {w['median']} s, "
                f"p95 {w['ninety_fifth']} s, p99 {FEW99 if w['payments'] < 100 else NOT_KEPT}, worst {w['slowest']} s."]
    return out


def recorded() -> dict:
    """What docs/bench.json keeps: {stages: {source, whole, six, attempts?}, decision: {local, devnet}, release: the
    release run's facts} (any may be missing)."""
    kept = json.loads(BENCH_JSON.read_text(encoding="utf-8"))
    return {"stages": kept.get("stages") or {}, "decision": kept.get("decision") or {}, "release": kept.get("release") or {}}


def separate_block(kept: dict) -> list[str]:
    """The block of docs/reference/BENCH.md between SEP_OPEN and SEP_CLOSE, from `recorded()`'s answer."""
    st, dec = kept.get("stages") or {}, kept.get("decision") or {}
    w = st.get("whole") or {}
    local = dec.get("local") or {}
    out = [f"Stages: {st.get('source') or NOT_RECORDED}. Decision, here: {local.get('source') or 'not measured'}. Decision, on devnet: "
           f"{(dec.get('devnet') or {}).get('source') or 'not measured'}.", "",
           *separate_table(separate(st.get("six") or [], dec, w)), ""]
    if w.get("n"):
        day = re.search(r"\d{4}-\d{2}-\d{2}", st.get("source") or "")
        worst = f"{w['max']} s" if w.get("max") is not None else NOT_KEPT
        out += [f"The one number a person feels, the merge to the payment, on the public program ids ({day.group(0) if day else NOT_RECORDED} reading): "
                f"p50 {w['p50']} s, p95 {w['p95']} s, p99 {FEW99 if w['n'] < 100 else w.get('p99') or NOT_KEPT}, worst {worst}, over the {w['n']} payments "
                "that completed and could be timed; it is not the sum of the rows above, which are different samples (a stage is timed only where the "
                "relay's log line carries it). The payments that failed or never completed are in the next table, not in these percentiles.", ""]
    out += [*attempts_block(kept), ""]
    out += [f"The release run measures every row with a sample again, on the live relay log and devnet, and rewrites this block: `{RELEASE_COMMAND}` "
            "(GH_TOKEN for GitHub's rate limit), then `python scripts/decide_bench.py --write` for the decision here. "
            "`python scripts/latency_stages.py --separate --recorded` prints this table from docs/bench.json with no network."]
    return out


def write_separate(kept: dict) -> None:
    """Rewrites the block in docs/reference/BENCH.md; a document that has none yet gets the section at its end."""
    doc = BENCH_MD.read_text(encoding="utf-8")
    block = "\n".join([SEP_OPEN, *separate_block(kept), SEP_CLOSE])
    if SEP_OPEN not in doc:
        doc = doc.rstrip("\n") + "\n\n## Every latency, apart\n\nNo single number says how fast a payment is. Six waits, each with its own sample and its own owner; none is a sum of others.\n\n" + f"{SEP_OPEN}\n{SEP_CLOSE}\n"
    BENCH_MD.write_text(re.sub(re.escape(SEP_OPEN) + r".*?" + re.escape(SEP_CLOSE), lambda _m: block, doc, flags=re.S), encoding="utf-8")


def clock_table(rows: list[dict]) -> list[str]:
    """`clocks()`'s rows as a Markdown table. A row with no sample has no figure."""
    cell = lambda row, k: "-" if row["where"] == NO_BANK else NOT_RECORDED if not row["n"] or row.get(k) is None else f"{row[k]} {row['unit']}"  # noqa: E731
    out = ["| clock | what is timed | measured | n | p50 | p95 | whose wait | target |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    out += [f"| {r['clock']} | {r['part']} | {r['where']} | {r['n'] if r['n'] else '-' if r['where'] == NO_BANK else NOT_RECORDED} | {cell(r, 'p50')} | {cell(r, 'p95')} | "
            f"{r['whose']} | {r['target']} |" for r in rows]
    return out


def table(rows: list[dict], whole: dict | None = None) -> list[str]:
    """`six()`'s rows as a Markdown table, the whole wait first when `whole` is given. A stage nobody recorded says
    so in every cell: no figure is ever put where none was measured."""
    cell = lambda row, k: NOT_RECORDED if not row.get("n") or row.get(k) is None else f"{row[k]} s"  # noqa: E731
    out = ["| stage | from, to | n | p50 | p95 |", "| --- | --- | --- | --- | --- |"]
    if whole is not None:
        out.append(f"| merge to paid, the whole wait | GitHub's `merged_at` to the block that paid | {whole.get('n') or NOT_RECORDED} | {cell(whole, 'p50')} | {cell(whole, 'p95')} |")
    out += [f"| {row['stage']} | {row['what']} | {row['n'] or NOT_RECORDED} | {cell(row, 'p50')} | {cell(row, 'p95')} |" for row in rows]
    return out


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
            if got and m:
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
    """{n, p50, p95, p99, max}: the median, the 95th and 99th percentiles by nearest rank (as measure() takes them), the
    longest. Below 100 samples the 99th percentile by nearest rank is the longest; it is still printed apart."""
    took = sorted(values)
    if not took:
        return {"n": 0, "p50": None, "p95": None, "p99": None, "max": None}
    rank = lambda q: took[max(0, math.ceil(q * len(took)) - 1)]  # noqa: E731
    return {"n": len(took), "p50": int(statistics.median(took)), "p95": rank(0.95), "p99": rank(0.99), "max": took[-1]}


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
    out: dict = {"whole": {**spread([r["seconds"] for r in rows]), "lines": m["lines"], "not_timed": m["not_timed"], "window": m["window"]},
           "stages": {name: spread([r[name] for r in rows if name in r]) for name in (*STAGES, *ALSO)},
           "states": {name: spread([f[name] for f in five.values() if f and name in f]) for name in STATES},
           "without_times": apart,
           "slowest": sorted(rows, key=lambda r: -r["seconds"])[:5],
           "attempts": ns.attempts(comments, ns.ATTEMPTS["pay"])}
    out = {**out, "six": six(out)}
    return {**out, "clocks": clocks(out["six"], whole=out["whole"])}


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
    out += ["", "the six stages, one table (a stage no line recorded says so):", *table(r.get("six") or six(r))]
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
    ap.add_argument("--md", action="store_true", help="print only the table of the six stages (n, p50, p95 each), as Markdown")
    ap.add_argument("--clocks", action="store_true", help="print only the five clocks, each row with its own sample, as Markdown (the decision clock is measured by scripts/decide_bench.py, not here)")
    ap.add_argument("--separate", action="store_true", help="print only the six latencies, each on its own (evidence arrival, evaluation, decision, chain confirmation, finality, payout), as Markdown")
    ap.add_argument("--recorded", action="store_true", help="with --separate: from docs/bench.json (the last recorded runs), asking no network")
    ap.add_argument("--write", action="store_true", help="with --separate: keep what was measured in docs/bench.json (`stages`) and rewrite the block in docs/reference/BENCH.md")
    ap.add_argument("--source", default="", help="with --separate --write: the sentence that says when and against what this was measured")
    a = ap.parse_args(argv)
    if a.separate and a.recorded:
        kept = recorded()
        for line in separate_block(kept):
            say(line)
        if a.write:
            write_separate(kept)
        return 0
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
        events = sorted((ev for program in (pay.PAY_ID, pay2.PAY_ID) for ev in ns.read_history(a.rpc, program)["events"]), key=lambda ev: ev["at"])
    else:
        say("stopped: give --events FILE (python scripts/network_stats.py --events-out FILE) or --rpc URL: the paying blocks' times are the chain's.")
        return 1
    r = report(comments, events, get, block_times(a.rpc) if a.rpc else None)
    if a.separate:
        kept = recorded()
        day = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
        w = r["whole"]
        window = f" of {w['window']['from']} to {w['window']['to']}" if w.get("window") else ""
        kept["stages"] = {"source": a.source or f"`{RELEASE_COMMAND}`, run on {day} against the relay log of {a.repo}: {w['n']} payments{window}",
                          "whole": {k: w[k] for k in ("n", "p50", "p95", "p99", "max")}, "six": r["six"], "attempts": r["attempts"]}
        for line in separate_block(kept):
            say(line)
        if a.write:
            doc = json.loads(BENCH_JSON.read_text(encoding="utf-8"))
            doc["stages"] = kept["stages"]
            BENCH_JSON.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            write_separate(kept)
        return 0
    for line in ([json.dumps(r, indent=1)] if a.json else clock_table(r["clocks"]) if a.clocks else table(r["six"], r["whole"]) if a.md else render(r)):
        say(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
