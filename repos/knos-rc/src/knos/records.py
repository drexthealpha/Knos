"""What the escrows' log lines say, read the one way for everything that counts money: the public numbers
(scripts/network_stats.py), the receipts, statements, SIEM export and invoices of `knos receipts`, the check that a refund
has executed (`knos status`) and the funder's record the MCP tools quote.

The programs print one line per fact, `knos:` lines on the first deployment and `knos2:` lines on the second, as
`<prefix>:<event> key=value key=value`; `knos2:terms <json>` carries a job's terms. A line counts only when the escrow
itself logged it in a transaction that succeeded: a line another program prints in the same transaction is not one.
`events_of` turns a transaction into events, `history` reads a program's transactions, `jobs_of` folds the events into jobs
(what was funded and what became of each). New fields in a line (a pull request number, an order) are read as they come:
every `key=value` becomes a key of the event.

Work orders (knos_pay 2.1) are the second escrow's `knos3:` lines. Their events are named `order_<event>` (order_funded,
order_terms, order_paid, order_settled, order_held, order_refunded, order_warranty, order_released, order_reverted,
order_reserved, order_cancelled, order_kill, order_topup, order_assigned), and `knos3:bound` is `org_bound`, so nothing
that reads jobs takes one for a job's. `orders_of` folds them into orders, each in the shape of a job with what an order
has beside it, and `work_of` gives jobs and orders together: what every count of money reads. knos_meter's `knosm:`
lines are `meter_<event>` (meter_eval, ...); `meter_months` counts the evaluations of each month from them.

The records for the person who signs off spend are recomputed from the same lines, never kept anywhere else:

    payments(events)      one row per payment (RECEIPT_COLUMNS), oldest first; receipts_csv / receipts_jsonl write them
    statement(...)        what one seller was paid in a month; invoice(...) one owner's month, as HTML and CSV
    evaluations(events)   one row per evaluation knos_meter counted (EVAL_COLUMNS): an invoice lists its buyer's
    meter_statement(...)  one buyer's and one seller's month at the meter (`knos statement --meter`)
    siem_events(events)   every escrow event as one JSON object (SIEM_FIELDS); siem_lines writes JSON Lines
    month_spent(...)      what an owner funded in a month (jobs and work orders), the figure `policy.allows` counts
                          against a monthly budget

Amounts are the mint's smallest unit, as the log prints them. Circle's devnet USDC and the faucet's test USDC have six
decimals, so 19500000 is 19.500000 test USDC and the files say "test USDC": devnet money, never real. The log does not
name the mint of a job a wallet funded itself; those are read as test USDC too, the only money `knos fund-wallet` sends
unless told another mint. A Balance on another mint is labelled `mint <address>`, and its text amount is left empty.
A payment whose funding is older than the history read still has a receipt (its funder and terms are left empty).
"""

from __future__ import annotations

import calendar
import csv
import html
import io
import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from solders.pubkey import Pubkey

from . import chain, ghwords
from .settle import pay
from .settle.v2 import meter
from .settle.v2 import pay as pay2

PROGRAMS = {str(pay.PAY_ID): 1, str(pay2.PAY_ID): 2}      # the escrow of each deployment
METER = str(meter.METER_ID)         # knos_meter: no escrow, a count of evaluations (its events are of deployment 2)
# What each program's lines are called as events: {log prefix: what goes in front of the line's own word}. An escrow
# of the second deployment prints jobs (knos2) and work orders (knos3); the meter prints knosm.
_NAMES = {1: {"knos": ""}, 2: {"knos2": "", "knos3": "order_"}}
_METER_NAMES = {"knosm": "meter_"}
_RENAMED = {"order_bound": "org_bound"}     # knos3:bound is an organisation's wallet, not an order's event

_INVOKE = re.compile(r"Program (\w+) invoke \[(\d+)\]$")
_DONE = re.compile(r"Program (\w+) (?:success|failed)")
_LOG = re.compile(r"Program log: (knos[23m]?):(\w+)(?: (.*))?$")



# ---- the chain's log, as events ---------------------------------------------------------------------------------------
def events_of(tx: dict | None, programs: dict[str, int] | None = None) -> list[dict]:
    """The escrow's log lines in one confirmed transaction, as dicts: "event" (funded, paid, ...; order_funded,
    order_paid, ... for a work order's; meter_eval, ... for the meter's), "v" (1 or 2: the deployment), "at" (block
    time), "signer" (the fee payer), "keys" (every account of the transaction), and the line's own fields; a `terms`
    line carries its JSON as "json". Only lines the program printed itself, in a transaction that succeeded.
    `programs`: {program address: deployment} (default: both escrows, and the meter)."""
    if not tx or (tx.get("meta") or {}).get("err") is not None:
        return []
    programs = {**PROGRAMS, METER: 2} if programs is None else programs
    meta, message = tx.get("meta") or {}, tx["transaction"]["message"]
    loaded = meta.get("loadedAddresses") or {}
    keys = [k if isinstance(k, str) else k.get("pubkey") for k in message["accountKeys"]] + list(loaded.get("writable") or []) + list(loaded.get("readonly") or [])
    out: list[dict] = []
    stack: list = []
    for line in meta.get("logMessages") or []:
        m = _INVOKE.match(line)
        if m:
            del stack[int(m.group(2)) - 1:]
            stack.append(m.group(1))
            continue
        if _DONE.match(line):
            if stack:
                stack.pop()
            continue
        m = _LOG.match(line)
        v = programs.get(stack[-1]) if stack else None
        named = (_METER_NAMES if stack and stack[-1] == METER else _NAMES.get(v, {})) if v is not None else {}
        if not m or m.group(1) not in named:
            continue
        name = named[m.group(1)] + m.group(2)
        ev = {"event": _RENAMED.get(name, name), "v": v, "at": tx.get("blockTime") or 0, "signer": keys[0], "keys": keys}
        if m.group(2) == "terms":
            ev["json"] = m.group(3) or ""
        else:
            for part in (m.group(3) or "").split():
                k, _, value = part.partition("=")
                ev[k] = int(value) if value.lstrip("-").isdigit() else value
        out.append(ev)
    return out


def history(url: str, program, limit: int = 1000) -> tuple[list[dict], int, bool]:
    """(events oldest first, transactions left unread because the public RPC throttled, whether `limit` cut the
    history short) for one program: its newest `limit` transactions."""
    got = chain.call(url, "getSignaturesForAddress", [str(program), {"limit": limit}], timeout=30) or []
    sigs = [s["signature"] for s in got if s.get("err") is None]
    events, unread = [], 0
    for sig in reversed(sigs):
        try:
            # version 1: what the relay sends to a 2.1 cluster. Asked with 0, the cluster refuses each of those, and
            # every payment and evaluation a relay carried would be counted as unread
            tx = chain.call(url, "getTransaction", [sig, {"encoding": "json", "commitment": "confirmed",
                                                          "maxSupportedTransactionVersion": 1}], timeout=30)
        except Exception:  # noqa: BLE001 - still throttled after the backoff: counted, never guessed
            unread += 1
            continue
        events += [{**ev, "tx": sig} for ev in events_of(tx)]
    return events, unread, len(got) >= limit


# ---- jobs: what was funded and what became of each --------------------------------------------------------------------
def _address(build, *args) -> str | None:
    try:
        return str(build(*args))
    except Exception:  # noqa: BLE001 - not an address (a test's stand-in name): the job is found by repository and issue
        return None


def _key(text) -> Pubkey:
    return Pubkey.from_string(str(text))


JOB_EVENTS = ("funded", "terms", "paid", "held", "proven", "refunded", "vetoed")     # the lines of an issue's bounty (a job)


def jobs_of(events: list[dict]) -> tuple[list[dict], dict]:
    """(every job the logs show, oldest first; counts of what is not about one job). A job:

        v, repo, issue, amount, faucet, at, tx      the deployment, where, how much, free test money or not, when
        by, owner, source, funder                   the commenter's GitHub id (0: a wallet), the Balance's owner id,
                                                    the Balance or the wallet, and who the record counts as funder
        state                                       open, held, proven (first deployment), paid, refunded
        mint                                        the Balance's mint (second deployment) when the log names it, else ""
        payee, to, net, fee, paid_at, paid_tx       once paid (payee also once held or proven)
        pr, order                                   the pull request and order a paid line names, when it names them (else None)
        terms                                       the terms JSON the funding logged (second deployment)

    An event is matched to its job by the job's address among the transaction's accounts; when the address cannot be
    told, by repository and issue, oldest open job first."""
    jobs: list[dict] = []
    live: dict[int, dict] = {}       # id(job) -> job, while it is open, held or proven
    balances: dict[str | None, dict] = {}   # a Balance's address -> its owner id and authority (second deployment)
    other = {"refunded": 0, "unmatched_paid": 0, "claimed": 0, "claimed_amount": 0, "vetoed": 0, "bound": 0, "balances": 0, "withdrawn": 0, "paused": 0}
    faucet_mint = {1: str(pay.faucet_mint()), 2: str(pay2.faucet_mint())}
    faucet_authority = str(pay2.auth_pda())
    job: dict | None

    def which(ev: dict) -> dict | None:
        mine = [j for j in live.values() if j["v"] == ev["v"]]
        named = [j for j in mine if j["address"] and j["address"] in ev["keys"]]
        if "repo" in ev:
            named = [j for j in named if (j["repo"], j["issue"]) == (ev["repo"], ev["issue"])]
            mine = [j for j in mine if (j["repo"], j["issue"]) == (ev["repo"], ev["issue"])]
        elif not named:
            return None
        if "amount" in ev and len(named or mine) > 1:      # two jobs on one issue: the one whose money this is
            whole = ev["amount"] + ev.get("fee", 0)
            exact = [j for j in (named or mine) if j["amount"] == whole]
            return (exact or named or mine)[0]
        found = named or mine
        return found[0] if found else None

    for ev in events:
        v, name = ev["v"], ev["event"]
        if name == "balance":
            address = _address(lambda e=ev: pay2.balance_pda(e["owner"], _key(e["authority"]), _key(e["mint"])))
            balances[address] = {"owner": ev["owner"], "authority": str(ev["authority"])}        # the wallet whose money it is
            other["balances"] += str(ev["authority"]) != faucet_authority
        elif name == "funded":
            job = {"v": v, "repo": ev.get("repo"), "issue": ev.get("issue"), "amount": ev.get("amount", 0), "at": ev["at"], "tx": ev.get("tx"),
                   "state": "open", "payee": 0, "terms": None}
            if v == 1:      # the repository's own bounty (a comment, faucet money), or a wallet's
                wallet = None if "by" in ev else ev["signer"]
                job.update(by=ev.get("by", 0), owner=0, source=wallet or "", mint="", funder=f"gh:{ev['by']}" if "by" in ev else f"wallet:{wallet}",
                           faucet="by" in ev or faucet_mint[1] in ev["keys"],
                           address=_address(lambda e=ev, w=wallet: pay.job_pda(e["repo"], e["issue"], _key(w) if w else None)))
            else:
                source, known = str(ev.get("source", "")), balances.get(str(ev.get("source", "")))
                from_balance = known is not None or bool(ev.get("by"))
                owner = known["owner"] if known else 0
                job.update(by=ev.get("by", 0), owner=owner, source=source, mint=(known or {}).get("mint", ""), faucet=bool(ev.get("faucet")),
                           funder=f"gh:{owner or ev.get('by', 0)}" if from_balance else f"wallet:{source}",
                           wallet=(known or {}).get("authority") if from_balance else source, from_balance=from_balance,
                           address=_address(lambda e=ev, s=source: pay2.job_pda(e["repo"], e["issue"], _key(s))))
            jobs.append(job)
            live[id(job)] = job
        elif name == "terms":
            if jobs and jobs[-1]["tx"] == ev.get("tx") and jobs[-1]["terms"] is None:
                jobs[-1]["terms"] = ev["json"]
        elif name in ("paid", "held", "proven", "refunded", "vetoed"):
            job = which(ev)
            if name in ("vetoed", "refunded"):
                other[name] += 1
            if job is None:      # its funding is older than the history that was read: counted, and in no one's column
                other["unmatched_paid"] += name == "paid"
                continue
            if name == "paid":
                payee = ev.get("payee", ev.get("author", 0))
                job.update(state="paid", payee=payee, to=str(ev.get("to", "")), net=ev.get("amount", 0), fee=ev.get("fee", 0),
                           paid_at=ev["at"], paid_tx=ev.get("tx"), pr=ev.get("pr"), order=ev.get("order"))
                del live[id(job)]
            elif name == "refunded":
                job.update(state="refunded", refunded_at=ev["at"])
                del live[id(job)]
            elif name == "vetoed":
                job.update(state="open", payee=0)
            else:
                job.update(state=name, payee=ev.get("payee", ev.get("author", 0)))
        elif name == "claimed":
            other["claimed"] += 1
            other["claimed_amount"] += ev.get("amount", 0)
        elif name in ("bound", "withdrawn", "paused"):
            other[name] += 1
    return jobs, other


# ---- work orders (knos_pay 2.1): the same shape, and what an order has beside it --------------------------------------
def orders_of(events: list[dict]) -> tuple[list[dict], dict]:
    """(every work order the logs show, oldest first; counts of what is not about one order). An order has every key
    a job of `jobs_of` has, read the same way by everything that counts money:

        v (2), repo, issue, amount, faucet, at, tx, by, owner, source, funder, wallet, from_balance, mint, terms, address
        state       open, held, warranty (paid, and holding a part back), paid, refunded
        payee, to, net, fee, paid_at, paid_tx, pr      the first payee and wallet, everything its payees received so
                    far (releases among it), the fee and tips taken so far, and the first payment's time, transaction
                    and pull request. `paid_at` is there once anything was paid: a standing order is paid and open.

    and, an order's own:

        order, seq, mode, flags, standing, neutral, private, deadline, fee_escrowed (what its funder put in on top)
        payees, tos                         every GitHub id paid and every wallet that received (a split has several)
        payments                            one per payee per payment: {at, tx, pr, payee, amount, to, fee, kind}; kind
                                            is paid, released (a holdback after its warranty) or kill (a kill fee);
                                            `fee` is the fee and tip of its transaction, on the first row of it
        held_back, warranty_until           while in warranty
        reserved_by, reserved_until, cancelled_at
        refunded_amount, reverted_amount    what went back to its funder (at the deadline; on a revert)

    A private order's line names repository 0 and issue 0: it is counted, and belongs to no repository."""
    orders: list[dict] = []
    live: dict[str, dict] = {}       # an order's address -> the order at it now (an address is used again once it is closed)
    balances = _balances(events)
    other = {"refunded": 0, "bound": 0, "reverted": 0, "released": 0, "cancelled": 0, "reserved": 0, "assigned": 0, "topped_up": 0, "kill_fees": 0,
             "unmatched_paid": 0}
    tx_rows: dict[tuple, list[dict]] = {}        # (order, transaction) -> the payment rows of that transaction, for its fee
    o: dict | None
    for ev in events:
        name = ev["event"]
        if name == "org_bound":
            other["bound"] += 1
            continue
        if not name.startswith("order_"):
            continue
        name, address = name[6:], str(ev.get("order", ""))
        if name == "funded":
            source, flags = str(ev.get("source", "")), int(ev.get("flags") or 0)
            known = balances.get(source)
            from_balance = known is not None or bool(ev.get("by"))
            owner = known["owner"] if known else 0
            o = {"v": 2, "order": address, "address": address, "repo": ev.get("repo"), "issue": ev.get("issue"), "seq": ev.get("seq", 0),
                 "amount": ev.get("amount", 0), "fee_escrowed": ev.get("fee", 0), "mode": ev.get("mode", 0), "flags": flags,
                 "faucet": bool(flags & pay2.F_FAUCET), "private": bool(flags & pay2.F_PRIVATE), "neutral": bool(flags & pay2.F_NEUTRAL),
                 "standing": bool(flags & pay2.F_STANDING), "deadline": ev.get("deadline"), "at": ev["at"], "tx": ev.get("tx"), "state": "open",
                 "by": ev.get("by", 0), "owner": owner, "source": source, "mint": (known or {}).get("mint", ""), "from_balance": from_balance,
                 "funder": f"gh:{owner or ev.get('by', 0)}" if from_balance else f"wallet:{source}",
                 "wallet": (known or {}).get("authority") if from_balance else source, "terms": None,
                 "payee": 0, "payees": [], "tos": [], "payments": [], "net": 0, "fee": 0}
            orders.append(o)
            live[address] = o
            continue
        if name == "terms":
            if orders and orders[-1]["tx"] == ev.get("tx") and orders[-1]["terms"] is None:
                orders[-1]["terms"] = ev["json"]
            continue
        o = live.get(address)
        if o is None:        # its funding is older than the history that was read: counted, and in no one's column
            other["unmatched_paid"] += name == "paid"
            other["refunded"] += name == "refunded"
            continue
        if name in ("paid", "released"):
            kill = name == "paid" and o.get("kill_held")       # a kill fee held for its taker, settled once he bound a wallet
            row = {"at": ev["at"], "tx": ev.get("tx"), "pr": ev.get("pr"), "payee": ev.get("payee", 0), "amount": ev.get("amount", 0),
                   "to": str(ev.get("to", "")), "fee": 0, "kind": "kill" if kill else name}
            o["payments"].append(row)
            tx_rows.setdefault((address, ev.get("tx")), []).append(row)
            if kill:
                continue
            if not o.get("paid_at"):
                o.update(payee=row["payee"], to=row["to"], paid_at=ev["at"], paid_tx=ev.get("tx"), pr=ev.get("pr"))
            o["net"] += row["amount"]
            o["payees"] += [row["payee"]] if row["payee"] not in o["payees"] else []
            o["tos"] += [row["to"]] if row["to"] not in o["tos"] else []
            other["released"] += name == "released"
        elif name == "settled":      # the fee and the tip of this transaction's payment; with the last of the amount the order is closed
            took = ev.get("fee", 0) + ev.get("tip", 0)
            rows = tx_rows.get((address, ev.get("tx"))) or []
            if rows:
                rows[0]["fee"] += took
            if o.get("kill_held"):       # the taker's kill fee, settled: the order went back long before
                del live[address]
                continue
            o["fee"] += took
            if ev.get("paid", 0) >= ev.get("of", 0):
                o["state"] = "paid"
                del live[address]
        elif name == "warranty":     # logged after the settled line of the same payment: the order stays, holding a part back
            o.update(state="warranty", held_back=ev.get("held", 0), warranty_until=ev.get("until"))
        elif name == "held":
            if o.get("refunded_at") is None:
                o.update(state="held", payee=ev.get("payee", 0), held_until=ev.get("until"))
            else:                    # what is held is the taker's kill fee: the order itself went back in this transaction
                o["kill_held"] = True
        elif name == "kill":
            other["kill_fees"] += 1
            o["kill"] = {"taker": ev.get("taker", 0), "amount": ev.get("amount", 0), "held": bool(ev.get("held"))}
            if not ev.get("held"):   # sent to the taker's bound wallet at once (the line does not name the wallet)
                o["payments"].append({"at": ev["at"], "tx": ev.get("tx"), "pr": None, "payee": ev.get("taker", 0), "amount": ev.get("amount", 0),
                                      "to": "", "fee": 0, "kind": "kill"})
        elif name == "refunded":
            if o.get("kill_held"):   # the held kill fee went back too, after its hold: nothing more to count
                del live[address]
                continue
            other["refunded"] += 1
            # an order that paid a part first (a standing offer) is a paid one whose rest went back. It stays findable:
            # a kill fee held for its taker follows in the same transaction and is settled later
            o.update(state="paid" if o.get("paid_at") else "refunded", refunded_at=ev["at"], refunded_amount=ev.get("amount", 0))
        elif name == "reverted":
            other["reverted"] += 1
            o.update(state="paid", reverted_at=ev["at"], reverted_amount=ev.get("amount", 0), held_back=0)
            del live[address]
        elif name == "reserved":
            other["reserved"] += 1
            o.update(reserved_by=ev.get("taker", 0), reserved_until=ev.get("until"))
        elif name == "cancelled":
            other["cancelled"] += 1
            o.update(cancelled_at=ev["at"], deadline=ev.get("deadline", o["deadline"]))
        elif name == "topup":
            other["topped_up"] += 1
            o.update(amount=ev.get("amount", o["amount"]), fee_escrowed=ev.get("fee", o["fee_escrowed"]))
        elif name == "assigned":
            other["assigned"] += 1
    return orders, other


def _balances(events: list[dict]) -> dict[str | None, dict]:
    """Every Balance the second escrow's log shows opened: {its address: {owner, authority, mint}}."""
    out: dict[str | None, dict] = {}
    for ev in events:
        if ev["event"] == "balance" and ev["v"] == 2:
            address = _address(lambda e=ev: pay2.balance_pda(e["owner"], _key(e["authority"]), _key(e["mint"])))
            out[address] = {"owner": ev["owner"], "authority": str(ev["authority"]), "mint": str(ev.get("mint", ""))}
    return out


def work_of(events: list[dict]) -> tuple[list[dict], dict]:
    """(jobs and work orders together, oldest first; the counts of both). What the public numbers, the receipts and a
    budget count: a work order is one funded task, as a job is."""
    jobs, other = jobs_of(events)
    orders, more = orders_of(events)
    both = sorted([*jobs, *orders], key=lambda j: j["at"])
    return both, {**other, **{k: other.get(k, 0) + n for k, n in more.items()}}


def meter_months(events: list[dict]) -> dict[str, dict]:
    """What knos_meter counted, per month (UTC, "2026-10"), from its `knosm:eval` lines: {evaluations, accepted,
    rejected, value (the sum of the rates of the accepted ones), fees, buyers, sellers}. An evaluation is billed once,
    so a retry prints no such line and is not here."""
    out: dict[str, dict] = {}
    seen: dict[str, tuple[set, set]] = {}
    for ev in events:
        if ev["event"] != "meter_eval":
            continue
        raw = str(ev.get("month") or "")
        month = f"{raw[:4]}-{raw[4:6]}" if len(raw) == 6 and raw.isdigit() else time.strftime("%Y-%m", time.gmtime(ev["at"]))
        m = out.setdefault(month, {"evaluations": 0, "accepted": 0, "rejected": 0, "value": 0, "fees": 0, "buyers": 0, "sellers": 0})
        ok = bool(ev.get("verdict"))
        m["evaluations"] += 1
        m["accepted" if ok else "rejected"] += 1
        m["value"] += int(ev.get("rate") or 0) if ok else 0
        m["fees"] += int(ev.get("fee") or 0)
        buyers, sellers = seen.setdefault(month, (set(), set()))
        buyers.add(ev.get("buyer"))
        sellers.add(ev.get("seller"))
        m["buyers"], m["sellers"] = len(buyers), len(sellers)
    return dict(sorted(out.items()))


def count_events(url: str, program, event: str, limit: int = 200, workers: int = 8) -> tuple[int, int]:
    """(how many `event` lines `program` logged, how many transactions were read) in its newest `limit` successful
    transactions, newest first, a batch at a time, stopping after the first batch that holds one. A transaction the
    cluster would not give is not counted as read; when none could be read at all, this raises."""
    got = chain.call(url, "getSignaturesForAddress", [str(program), {"limit": limit}], timeout=30) or []
    sigs = [x["signature"] for x in got if x.get("err") is None]

    def read(sig: str):
        try:
            return events_of(chain.call(url, "getTransaction", [sig, {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 1}], timeout=30),
                             {str(program): 2})
        except Exception:  # noqa: BLE001 - throttled or dropped: not read
            return None
    found = looked = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(sigs), workers * 2):
            for events in pool.map(read, sigs[start:start + workers * 2]):
                if events is not None:
                    looked += 1
                    found += sum(1 for ev in events if ev["event"] == event)
            if found:
                break
    if sigs and not looked:
        raise chain.Refused(f"none of the {len(sigs)} newest transactions of {program} could be read")
    return found, looked


# ---- reading the history, and GitHub's names for the ids in it --------------------------------------------------------
@dataclass(frozen=True)
class Record:
    """What the escrows' logs and the meter's say: events oldest first, and what could not be read (so a total is never
    taken for complete)."""
    events: list[dict]
    unread: int = 0                 # transactions the public RPC would not give
    cut: tuple = ()                 # whose history is longer than `limit`: a deployment (1, 2), or "meter"
    limit: int = 1000

    def notes(self) -> list[str]:
        said = [f"{self.unread} transactions could not be read (the public RPC throttled): what follows is a lower bound."] if self.unread else []
        return said + [f"Only the newest {self.limit} transactions of knos_meter were read: older evaluations are not here." if v == "meter" else
                       f"Only the newest {self.limit} transactions of the {('first', 'second')[v - 1]} deployment's escrow were read: older payments are not here."
                       for v in self.cut]


def read(url: str, limit: int = 1000, with_meter: bool = True) -> Record:
    """Both escrows' history and knos_meter's from the cluster at `url`: payments, and the evaluations the meter
    counted (`evaluations`). A transaction that named two of the programs is in two histories and read into the
    events once. `with_meter=False` leaves the meter's out, for a caller that only counts money (it saves the
    requests). Raises what `chain.call` raises when the cluster cannot be asked at all."""
    events: list[dict] = []
    unread, cut, seen = 0, [], set()
    for v, program in ((1, pay.PAY_ID), (2, pay2.PAY_ID), *((("meter", meter.METER_ID),) if with_meter else ())):
        got, lost, short = history(url, program, limit)
        events += [ev for ev in got if ev.get("tx") not in seen]
        seen |= {ev.get("tx") for ev in got}
        unread += lost
        if short:
            cut.append(v)
    events.sort(key=lambda ev: ev["at"])      # stable: one transaction's lines stay in order
    return Record(events, unread, tuple(cut), limit)


class Names:
    """GitHub's names for the ids the chain holds, asked once each. `get(path)` is GitHub's API (None: names are not
    asked for). After the first refusal that is not a 404 it stops asking, since more requests only prolong a rate limit;
    what went wrong is in `problems`, and a name it could not get is empty."""

    def __init__(self, get: Callable[[str], dict] | None = None):
        self._get, self._stopped = get, False
        self._seen: dict[str, dict] = {}
        self.problems: list[str] = []

    def _ask(self, path: str) -> dict:
        if path not in self._seen:
            got = None
            if self._get is not None and not self._stopped:
                try:
                    got = self._get(path)
                except Exception as why:  # noqa: BLE001 - a missing account is a 404 and is just unnamed; anything else stops the asking
                    if ghwords.code_of(why) != 404:
                        self._stopped = True
                        self.problems.append(ghwords.failed(path, why))
            self._seen[path] = got if isinstance(got, dict) else {}
        return self._seen[path]

    def repo(self, repo_id) -> dict:
        """The repository as GitHub describes it ("full_name", "owner": {"id"}); {} when unknown."""
        return self._ask(f"repositories/{int(repo_id)}") if repo_id else {}

    def user(self, user_id) -> str:
        return str(self._ask(f"user/{int(user_id)}").get("login", "")) if user_id else ""


# ---- payments: one row per payment ----------------------------------------------------------------------------------------
TEST = "test USDC"
RECEIPT_COLUMNS = ("date", "time", "deployment", "repository_id", "repository", "issue", "pull_request", "payee_id", "payee", "wallet",
                   "amount", "fee", "total", "currency", "amount_units", "fee_units", "total_units", "funder", "owner_id", "terms_hash",
                   "funded_transaction", "transaction")
"""A receipt, a row of `knos receipts`, in this order:

    date, time          UTC day and ISO 8601 time of the paying transaction's block
    deployment          1 or 2: which escrow paid
    repository_id       GitHub's id of the repository; `repository` its owner/name (empty when GitHub was not asked or could not say)
    issue               the issue the bounty was on; pull_request the pull request when the log line names it (else empty)
    payee_id, payee     the paid GitHub account's id, and its login (as for the repository)
    wallet              the Solana address that received the money (empty for the first deployment, whose log does not print it)
    amount, fee, total  what reached the wallet, what the escrow kept, and the two together: decimals of `currency`
                        (empty for a mint that is not test USDC); `*_units` the same as integers, the mint's smallest unit.
                        A work order's payee receives the whole amount: its fee is what its funder paid on top, written
                        on the first row of each paying transaction (0 on the other payees' rows of a split)
    funder              gh:<id> for an account (a Balance's owner, or a commenter), wallet:<address> for a wallet
    owner_id            the Balance's owner id (0: no Balance)
    terms_hash          sha256 of the terms JSON the funding logged: the terms the payment was made under (empty before the second deployment)
    funded_transaction  the transaction that funded the job (empty when older than the history read); transaction: the one that paid it
"""


def units_text(units: int, places: int = 6) -> str:
    """19500000 as "19.500000": integer arithmetic, so the sum of a column is the sum of what the chain says, to the unit."""
    units = int(units)
    return f"{'-' if units < 0 else ''}{abs(units) // 10 ** places}.{abs(units) % 10 ** places:0{places}d}"


def _day(t: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(t))


def _stamp(t: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _currency(job: dict) -> str:
    known = {str(pay2.USDC_DEVNET), str(pay2.faucet_mint()), str(pay.faucet_mint())}
    mint = job.get("mint") or ""
    return TEST if job.get("faucet") or not mint or mint in known else f"mint {mint}"


def _row(job: dict) -> dict:
    net, fee, cur = job["net"], job["fee"], _currency(job)
    text = units_text if cur == TEST else (lambda n: "")
    terms = job.get("terms")
    return {"unix": job["paid_at"], "date": _day(job["paid_at"]), "time": _stamp(job["paid_at"]), "deployment": job["v"],
            "repository_id": job["repo"], "repository": "", "issue": job["issue"], "pull_request": job.get("pr"),
            "payee_id": job["payee"], "payee": "", "wallet": job.get("to", ""),
            "amount": text(net), "fee": text(fee), "total": text(net + fee), "currency": cur,
            "amount_units": net, "fee_units": fee, "total_units": net + fee,
            "funder": job["funder"], "owner_id": job["owner"], "commenter_id": job["by"],
            "terms_hash": pay2.terms_hash(terms.encode()).hex() if terms else "",
            "funded_transaction": job["tx"] or "", "transaction": job["paid_tx"] or ""}


def payments(events: list[dict]) -> list[dict]:
    """Every payment the events show, oldest first, one dict per payment (RECEIPT_COLUMNS, and `unix`, `commenter_id`).
    A paid line whose funding is older than the history read is still a payment: it is listed with no funder."""
    jobs, _ = jobs_of(events)
    rows = [_row(j) for j in jobs if j["state"] == "paid"]
    for o in orders_of(events)[0]:       # a work order: one row per payee per payment; its fee is the funder's, on the first row of a transaction
        rows += [_row({**o, "net": p["amount"], "fee": p["fee"], "paid_at": p["at"], "paid_tx": p["tx"], "payee": p["payee"], "to": p["to"], "pr": p["pr"] or None})
                 for p in o["payments"]]
    have = {(r["transaction"], r["repository_id"], r["issue"]) for r in rows}
    for ev in events:
        if ev["event"] == "paid" and (ev.get("tx") or "", ev.get("repo"), ev.get("issue")) not in have:
            rows.append(_row({"v": ev["v"], "repo": ev.get("repo", 0), "issue": ev.get("issue", 0), "net": ev.get("amount", 0), "fee": ev.get("fee", 0),
                              "paid_at": ev["at"], "payee": ev.get("payee", ev.get("author", 0)), "to": str(ev.get("to", "")), "funder": "", "owner": 0,
                              "by": 0, "tx": None, "paid_tx": ev.get("tx"), "terms": None, "faucet": False, "mint": "", "pr": ev.get("pr")}))
    return sorted(rows, key=lambda r: r["unix"])


def month_days(month: str) -> tuple[str, str]:
    """("2026-09-01", "2026-09-30") for "2026-09". ValueError, in words, for anything else."""
    m = re.fullmatch(r"(\d{4})-(0[1-9]|1[0-2])", str(month or ""))
    if not m or int(m[1]) < 1970:
        raise ValueError(f"A month is written YYYY-MM, like 2026-09; {month!r} is not one.")
    return f"{month}-01", f"{month}-{calendar.monthrange(int(m[1]), int(m[2]))[1]:02d}"


def day_of(text: str, what: str = "a date") -> str:
    """A day as YYYY-MM-DD. ValueError, in words, for anything else."""
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(text)):
            raise ValueError(text)
        return date.fromisoformat(str(text)).isoformat()
    except ValueError:
        raise ValueError(f"{what} is a day like 2026-09-30; {text!r} is not one.") from None


def select(rows: list[dict], owner_id: int = 0, payee_id: int = 0, first: str = "", last: str = "", names: Names | None = None) -> list[dict]:
    """The rows of one owner (the account whose money it was: a Balance's owner, or the commenter who funded; for a job
    a wallet funded, the owner of its repository when `names` can say) and/or paid to one payee, between two UTC days
    inclusive, with the repository's and payee's names added when `names` is given."""
    def mine(r: dict) -> bool:
        account = r["owner_id"] or r["commenter_id"]
        if account:
            return account == owner_id
        return names is not None and (names.repo(r["repository_id"]).get("owner") or {}).get("id") == owner_id
    out = [r for r in rows if (not first or r["date"] >= first) and (not last or r["date"] <= last)
           and (not payee_id or r["payee_id"] == payee_id) and (not owner_id or mine(r))]
    if names is None:
        return out
    return [{**r, "repository": names.repo(r["repository_id"]).get("full_name", ""), "payee": names.user(r["payee_id"])} for r in out]


def totals(rows: list[dict]) -> dict[str, dict]:
    """Per currency (never added across mints): {payments, amount_units, fee_units, total_units}."""
    out: dict[str, dict] = {}
    for r in rows:
        t = out.setdefault(r["currency"], {"payments": 0, "amount_units": 0, "fee_units": 0, "total_units": 0})
        t["payments"] += 1
        t["amount_units"] += r["amount_units"]
        t["fee_units"] += r["fee_units"]
        t["total_units"] += r["total_units"]
    return out


def _cell(value) -> str:
    """A spreadsheet runs a cell that starts with = + - @ as a formula; a name from GitHub gets a quote in front of one."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def receipts_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    out.writerow(RECEIPT_COLUMNS)
    for r in rows:
        out.writerow([_cell(r[c]) if c in ("repository", "payee") else ("" if r[c] is None else r[c]) for c in RECEIPT_COLUMNS])
    return buf.getvalue()


def receipts_jsonl(rows: list[dict]) -> str:
    return "".join(json.dumps({c: r[c] for c in RECEIPT_COLUMNS}, separators=(",", ":")) + "\n" for r in rows)


def money_text(units: int, currency: str) -> str:
    return f"{units_text(units)} {TEST}" if currency == TEST else f"{units} units of {currency}"


def _where(r: dict) -> str:
    pr = f", pull request #{r['pull_request']}" if r.get("pull_request") else ""
    return f"{r['repository'] or 'repository ' + str(r['repository_id'])}#{r['issue']}{pr}"


# ---- a seller's statement, an owner's invoice --------------------------------------------------------------------------------
def statement(rows: list[dict], seller_id: int, seller: str, month: str, names: Names | None = None) -> dict:
    """What one payee was paid in a month: {seller, seller_id, month, from, to, payments, totals}. A zero `seller_id` is no seller."""
    first, last = month_days(month)
    mine = select(rows, payee_id=seller_id, first=first, last=last, names=names) if seller_id else []
    return {"seller": seller, "seller_id": seller_id, "month": month, "from": first, "to": last, "payments": mine, "totals": totals(mine)}


def statement_lines(st: dict) -> list[str]:
    lines = [f"Statement for {st['seller']} (GitHub id {st['seller_id']}), {st['month']}: UTC days {st['from']} to {st['to']}, "
             "recomputed from the escrows' log lines on Solana devnet."]
    for r in st["payments"]:
        lines.append(f"  {r['date']}  {_where(r)}  {money_text(r['amount_units'], r['currency'])} received, fee {money_text(r['fee_units'], r['currency'])}  "
                     f"funded by {r['funder'] or 'a funder older than the history read'}  {r['transaction']}")
    for cur, t in st["totals"].items():
        lines.append(f"  {t['payments']} payment{'' if t['payments'] == 1 else 's'}: {money_text(t['amount_units'], cur)} received, "
                     f"{money_text(t['fee_units'], cur)} in fees, {money_text(t['total_units'], cur)} out of escrow.")
    if not st["payments"]:
        lines.append("  No payment to this account in that month.")
    return lines


def invoice(rows: list[dict], owner_id: int, owner: str, month: str, names: Names | None = None, issued: float | None = None,
            evals: list[dict] | None = None) -> dict:
    """An owner's month: {number, owner, owner_id, month, from, to, issued, lines, totals, evaluations, meter}. `lines`
    are the payments made out of the owner's money (see `select`) in that month. `evals` (what `evaluations` gave):
    `evaluations` are then the ones knos_meter billed this owner for as their buyer in that month, and `meter` their
    totals (`meter_totals`); without it both are empty."""
    first, last = month_days(month)
    lines = select(rows, owner_id=owner_id, first=first, last=last, names=names) if owner_id else []
    counted = [{**e, "seller": names.user(e["seller_id"]) if names else ""} for e in evals or [] if owner_id and e["buyer_id"] == owner_id and e["month"] == month]
    return {"number": f"KNOS-{re.sub(r'[^A-Za-z0-9_.-]', '', owner) or owner_id}-{month.replace('-', '')}", "owner": owner, "owner_id": owner_id, "month": month,
            "from": first, "to": last, "issued": _day(int(time.time() if issued is None else issued)), "lines": lines, "totals": totals(lines),
            "evaluations": counted, "meter": meter_totals(counted)}


def invoice_csv(inv: dict) -> str:
    return receipts_csv(inv["lines"])


# ---- the meter: evaluations counted, not money escrowed ---------------------------------------------------------------------
EVAL_COLUMNS = ("date", "time", "month", "buyer_id", "seller_id", "seller", "order", "artifact", "policy", "milestone", "verdict", "rate_units", "fee_units",
                "transaction")
"""An evaluation knos_meter counted, a row of an invoice's second table and of its `-evaluations.csv`, in this order:

    date, time      UTC day and ISO 8601 time of the block that counted it; month: the month the meter billed it in (YYYY-MM)
    buyer_id        the GitHub owner whose credits paid; seller_id, seller: the GitHub account whose work was evaluated, and
                    its login (empty when GitHub was not asked or could not say)
    order           the work order the evaluation was for (64 hex characters), artifact: the commit evaluated,
                    policy: the hash of the policy it was held to, milestone: its number within the order
    verdict         accepted or rejected
    rate_units      the value the evaluation's token declared, fee_units: what the meter took from the buyer's credits;
                    both in the smallest unit of the credits' mint, as the log prints them (the line does not name the mint)
    transaction     the signature of the transaction that counted it
"""


def evaluations(events: list[dict]) -> list[dict]:
    """Every evaluation the events show (knos_meter's `knosm:eval` lines), oldest first, one dict each (EVAL_COLUMNS and
    `unix`). The meter bills an evaluation once, so a retry printed no line and is not here."""
    out = []
    for ev in events:
        if ev["event"] != "meter_eval":
            continue
        raw = str(ev.get("month") or "")
        month = f"{raw[:4]}-{raw[4:6]}" if len(raw) == 6 and raw.isdigit() else time.strftime("%Y-%m", time.gmtime(ev["at"]))
        out.append({"unix": ev["at"], "date": _day(ev["at"]), "time": _stamp(ev["at"]), "month": month, "buyer_id": int(ev.get("buyer") or 0),
                    "seller_id": int(ev.get("seller") or 0), "seller": "", "order": str(ev.get("order", "")), "artifact": str(ev.get("artifact", "")),
                    "policy": str(ev.get("policy", "")), "milestone": int(ev.get("milestone") or 0), "verdict": "accepted" if ev.get("verdict") else "rejected",
                    "rate_units": int(ev.get("rate") or 0), "fee_units": int(ev.get("fee") or 0), "transaction": ev.get("tx") or ""})
    return sorted(out, key=lambda e: e["unix"])


def meter_totals(evals: list[dict]) -> dict:
    """{evaluations, accepted, rejected, value_units (the declared rates of the accepted ones), fee_units} of some rows."""
    ok = [e for e in evals if e["verdict"] == "accepted"]
    return {"evaluations": len(evals), "accepted": len(ok), "rejected": len(evals) - len(ok), "value_units": sum(e["rate_units"] for e in ok),
            "fee_units": sum(e["fee_units"] for e in evals)}


def evaluations_csv(evals: list[dict]) -> str:
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    out.writerow(EVAL_COLUMNS)
    for e in evals:
        out.writerow([_cell(e[c]) if c == "seller" else e[c] for c in EVAL_COLUMNS])
    return buf.getvalue()


def meter_statement(ledger, buyer_id: int, buyer: str, seller_id: int, seller: str, month: str) -> dict:
    """One buyer's and one seller's month at knos_meter: {buyer, buyer_id, seller, seller_id, month, from, to, totals,
    account, agrees}. `totals` is recomputed from the meter's own log lines (knos.settle.v2.meter.statement, which
    reads every transaction that named the month's account: `ledger.history`, `ledger.logs`); `account` is the count
    the program keeps on chain for that month; `agrees` says whether they are the same. When they are not, the
    cluster no longer has every transaction, and the account is the count."""
    first, last = month_days(month)
    yyyymm = int(month.replace("-", ""))
    as_dict = lambda st: {"evaluations": st.evaluations, "accepted": st.accepted, "rejected": st.rejected, "value_units": st.value, "fee_units": st.fees}  # noqa: E731
    if not (buyer_id and seller_id):
        empty = as_dict(meter.Statement(buyer_id, seller_id, yyyymm))
        return {"buyer": buyer, "buyer_id": buyer_id, "seller": seller, "seller_id": seller_id, "month": month, "from": first, "to": last, "totals": empty,
                "account": empty, "agrees": True}
    logged = as_dict(meter.statement(ledger, buyer_id, seller_id, yyyymm))
    kept = as_dict(meter.read_month(ledger.account(meter.month_pda(buyer_id, seller_id, yyyymm)), buyer_id, seller_id, yyyymm))
    return {"buyer": buyer, "buyer_id": buyer_id, "seller": seller, "seller_id": seller_id, "month": month, "from": first, "to": last, "totals": logged,
            "account": kept, "agrees": logged == kept}


def _count(n: int, one: str) -> str:
    return f"{n} {one}{'' if n == 1 else 's'}"


def meter_statement_lines(st: dict) -> list[str]:
    t, a = st["totals"], st["account"]
    lines = [f"Meter statement for buyer {st['buyer']} (GitHub id {st['buyer_id']}) and seller {st['seller']} (GitHub id {st['seller_id']}), {st['month']}: "
             f"UTC days {st['from']} to {st['to']}, recomputed from knos_meter's log lines on Solana devnet."]
    if not t["evaluations"] and not a["evaluations"]:
        return lines + ["  No evaluation was counted for this buyer and this seller in that month."]
    lines.append(f"  {_count(t['evaluations'], 'billable evaluation')}: {t['accepted']} accepted, {t['rejected']} rejected.")
    lines.append(f"  Declared value of the accepted ones: {units_text(t['value_units'])} ({t['value_units']} units). "
                 f"Fees from the buyer's credits: {units_text(t['fee_units'])} ({t['fee_units']} units).")
    lines.append("  Both are in the smallest unit of the credits' mint, written with six decimals as test USDC has; the log does not name the mint.")
    lines.append("  The month's account on chain says the same." if st["agrees"] else
                 f"  The month's account on chain says {_count(a['evaluations'], 'evaluation')} ({a['accepted']} accepted, {a['rejected']} rejected), value "
                 f"{units_text(a['value_units'])}, fees {units_text(a['fee_units'])}: the cluster no longer has every transaction, and the account is the count.")
    return lines


def meter_statement_csv(st: dict) -> str:
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    out.writerow(("month", "buyer_id", "buyer", "seller_id", "seller", "evaluations", "accepted", "rejected", "value_units", "fee_units", "agrees_with_account"))
    out.writerow((st["month"], st["buyer_id"], _cell(st["buyer"]), st["seller_id"], _cell(st["seller"]), *(st["totals"][k] for k in
                  ("evaluations", "accepted", "rejected", "value_units", "fee_units")), "yes" if st["agrees"] else "no"))
    return buf.getvalue()


_STYLE = ("body{font:15px/1.45 system-ui,sans-serif;max-width:64rem;margin:2rem auto;padding:0 1rem;color:#111}"
          "table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{border-bottom:1px solid #bbb;padding:.35rem .5rem;text-align:left;vertical-align:top}"
          "td.n,th.n{text-align:right;white-space:nowrap}code{font-size:12px;word-break:break-all}")


def invoice_html(inv: dict) -> str:
    """A plain HTML page: no script, no outside file. Everything that came from GitHub or the chain is escaped."""
    e = html.escape
    body = "".join(
        f"<tr><td>{e(r['date'])}</td><td>{e(_where(r))}</td><td>{e(r['payee'] or str(r['payee_id']))}</td>"
        f"<td class=n>{e(money_text(r['amount_units'], r['currency']))}</td><td class=n>{e(money_text(r['fee_units'], r['currency']))}</td>"
        f"<td class=n>{e(money_text(r['total_units'], r['currency']))}</td><td><code>{e(r['transaction'])}</code></td></tr>" for r in inv["lines"])
    foot = "".join(f"<tr><th colspan=3>{e(str(t['payments']))} payment{'' if t['payments'] == 1 else 's'}</th><th class=n>{e(money_text(t['amount_units'], c))}</th>"
                   f"<th class=n>{e(money_text(t['fee_units'], c))}</th><th class=n>{e(money_text(t['total_units'], c))}</th><th></th></tr>" for c, t in inv["totals"].items())
    empty = "" if inv["lines"] else "<p>No payment was made out of this owner's money in that month.</p>"
    test = "<p><strong>These amounts are test USDC on Solana devnet: test money, not money.</strong></p>" if any(c == TEST for c in inv["totals"]) or not inv["lines"] else ""
    return (f"<!doctype html>\n<html lang=en><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\">"
            f"<title>Invoice {e(inv['number'])}</title><style>{_STYLE}</style>\n"
            f"<h1>Invoice {e(inv['number'])}</h1>\n<p>For <strong>{e(inv['owner'])}</strong> (GitHub id {e(str(inv['owner_id']))}). "
            f"Period {e(inv['from'])} to {e(inv['to'])} (UTC). Issued {e(inv['issued'])}.</p>\n{test}"
            "<table><thead><tr><th>Date</th><th>Issue</th><th>Paid to</th><th class=n>Received by the payee</th><th class=n>Escrow fee</th><th class=n>Taken from escrow</th>"
            f"<th>Transaction</th></tr></thead><tbody>{body}</tbody><tfoot>{foot}</tfoot></table>\n{empty}"
            "<p>Each line is one payment the escrow made out of this owner's money in the period. It is read from the escrows' own log lines on Solana "
            f"devnet, and names the transaction that holds it. No tax is calculated and none is included.</p>\n{_evaluations_html(inv)}")


def _evaluations_html(inv: dict) -> str:
    """The evaluations knos_meter billed this owner for in the period, as a second table; nothing when there are none."""
    evals, e = inv.get("evaluations") or [], html.escape
    if not evals:
        return ""
    t = inv["meter"]
    body = "".join(
        f"<tr><td>{e(x['date'])}</td><td>{e(x['seller'] or str(x['seller_id']))}</td><td><code>{e(x['order'])}</code> milestone {e(str(x['milestone']))}</td>"
        f"<td><code>{e(x['artifact'])}</code></td><td>{e(x['verdict'])}</td><td class=n>{e(units_text(x['rate_units']))}</td>"
        f"<td class=n>{e(units_text(x['fee_units']))}</td><td><code>{e(x['transaction'])}</code></td></tr>" for x in evals)
    return ("<h2>Evaluations counted by knos_meter</h2>\n"
            "<table><thead><tr><th>Date</th><th>Seller</th><th>Work order</th><th>Commit</th><th>Verdict</th><th class=n>Declared value</th>"
            f"<th class=n>Fee from credits</th><th>Transaction</th></tr></thead><tbody>{body}</tbody>"
            f"<tfoot><tr><th colspan=4>{e(_count(t['evaluations'], 'evaluation'))}</th><th>{e(str(t['accepted']))} accepted, {e(str(t['rejected']))} rejected</th>"
            f"<th class=n>{e(units_text(t['value_units']))}</th><th class=n>{e(units_text(t['fee_units']))}</th><th></th></tr></tfoot></table>\n"
            "<p>Each line is one evaluation the meter billed this owner for as its buyer in the period, read from the meter's own log lines. The fees were "
            "taken from the credits this owner prepaid, not from an escrow; they and the declared values are in the units of the credits' mint, written with "
            "six decimals as test USDC has.</p>\n")


def month_spent(events: list[dict], owner_id: int, month: str) -> Decimal:
    """Whole units (like 20, or 12.5) this owner funded in `month` (UTC) and has not had refunded, jobs and work orders alike:
    what `policy.allows` counts against a monthly budget. The owner is the account whose money it was: a Balance's owner, or
    the commenter who funded."""
    first, last = month_days(month)
    work, _ = work_of(events)
    # a work order that went back after paying a part (a standing offer) counts for what it paid
    spent = lambda j: 0 if j["state"] == "refunded" else j["net"] if j.get("refunded_at") else j["amount"]  # noqa: E731
    units = sum(spent(j) for j in work if owner_id and (j["owner"] or j["by"]) == owner_id and first <= _day(j["at"]) <= last)
    return Decimal(units) / 10 ** 6


# ---- every event, for a SIEM --------------------------------------------------------------------------------------------------
SIEM_FIELDS = ("time", "unix", "actor", "action", "deployment", "repository", "repository_id", "issue", "amount", "fee", "transaction")
"""One JSON object per line (`knos export --siem`), the same keys on every line, null where an event has none:

    time, unix      ISO 8601 UTC and unix seconds of the block (null when the cluster gave none)
    actor           who did it: gh:<id> (a commenter who funded, an account that named a wallet), else wallet:<address>
                    (the transaction's fee payer: for a payment, the relay that sent it; the money moves by the escrow's rules, not the payer's)
    action          the escrow's own event: funded, terms, paid, held, proven, vetoed, refunded, balance, bound, claimed, withdrawn, paused;
                    a work order's as order_<event> (order_funded, order_paid, order_settled, order_held, order_refunded, order_warranty,
                    order_released, order_reverted, order_reserved, order_cancelled, order_kill, order_topup, order_assigned), org_bound
                    (an organisation's wallet), and the meter's as meter_<event> (meter_eval, meter_credits, ...)
    deployment      1 or 2
    repository      owner/name when GitHub was asked and knew it; repository_id GitHub's id of it; issue
    amount, fee     the mint's smallest unit, as the line prints them (for a payment: what reached the wallet, and the fee kept)
    transaction     the signature of the transaction that logged it

and, only on the lines that have them: payee, to (the receiving wallet), by (the commenter's GitHub id), source, mode, owner, authority, mint, user,
wallet, until, test_money (true: the funding was the faucet's free money), terms_hash (sha256 of the terms the `terms` line carried; the terms
themselves are not copied); a work order's: order (its address), seq, pr, flags, deadline, taker, head, judge, tip, held, paid, of, add, org; the
meter's: buyer, seller, artifact, policy, milestone, verdict, rate, month, n. Nothing is inferred: a field is in the line the program printed, or
it is not here.
"""
_SIEM_EXTRA = ("payee", "to", "by", "source", "mode", "owner", "authority", "mint", "user", "wallet", "until",
               "order", "seq", "pr", "flags", "deadline", "taker", "head", "judge", "tip", "held", "paid", "of", "add", "org",
               "buyer", "seller", "artifact", "policy", "milestone", "verdict", "rate", "month", "n")


def actor_of(ev: dict) -> str:
    if ev["event"] in ("funded", "terms", "order_funded", "order_terms") and ev.get("by"):
        return f"gh:{ev['by']}"
    if ev["event"] == "bound" and ev.get("user"):
        return f"gh:{ev['user']}"
    if ev["event"] == "org_bound" and ev.get("by"):         # the member who ran the organisation's claim
        return f"gh:{ev['by']}"
    return f"wallet:{ev['authority']}" if ev["event"] in ("balance", "withdrawn") and ev.get("authority") else f"wallet:{ev['signer']}"


def siem_events(events: list[dict], names: Names | None = None, first: str = "", last: str = "") -> list[dict]:
    """The events as dicts (SIEM_FIELDS first, then the fields a line has), oldest first, between two UTC days inclusive."""
    out, funder = [], {}
    for ev in events:
        at = ev["at"] or 0
        if (first and at and _day(at) < first) or (last and at and _day(at) > last):
            continue
        fixed = {"time": _stamp(at) if at else None, "unix": at or None, "actor": actor_of(ev), "action": ev["event"], "deployment": ev["v"],
                 "repository": (names.repo(ev["repo"]).get("full_name") or None) if names and ev.get("repo") else None,
                 "repository_id": ev.get("repo"), "issue": ev.get("issue"), "amount": ev.get("amount"), "fee": ev.get("fee"), "transaction": ev.get("tx")}
        item = {k: fixed[k] for k in SIEM_FIELDS}      # every line has these keys, in this order, whatever else it has
        item.update({k: ev[k] for k in _SIEM_EXTRA if k in ev})
        if ev["event"] in ("funded", "order_funded"):
            funder[ev.get("tx")] = item["actor"]
        elif ev["event"] in ("terms", "order_terms") and ev.get("tx") in funder:      # the terms line has no `by`: it is the funding's, in the same transaction
            item["actor"] = funder[ev["tx"]]
        if "author" in ev:
            item["payee"] = ev["author"]
        if ev["event"] == "funded" and "faucet" in ev:
            item["test_money"] = bool(ev["faucet"])
        if ev["event"] == "order_funded" and "flags" in ev:
            item["test_money"] = bool(int(ev["flags"] or 0) & pay2.F_FAUCET)
        if ev["event"] in ("terms", "order_terms"):
            item["terms_hash"] = pay2.terms_hash((ev.get("json") or "").encode()).hex()
        out.append(item)
    return out


def siem_lines(events: list[dict], names: Names | None = None, first: str = "", last: str = "") -> str:
    return "".join(json.dumps(x, separators=(",", ":")) + "\n" for x in siem_events(events, names, first, last))
