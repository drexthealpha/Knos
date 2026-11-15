"""The audit export: everything one organisation's money paid for, for the person who approves the invoice.

`knos audit export --owner <org> [--from --to] --format csv|json` and `knos audit verify <file>` write and check the
statement. `knos audit show <order>` prints one deliverable as four linked objects (authorisation, acceptance,
commercial record, settlement status), `knos audit owed --payee <login>` is the supplier's side, and
`knos audit export --format netsuite|sap|coupa|quickbooks|generic` writes the files of knos.exports.

Version 2 of the file (this one) lists the bounties on issues (the second escrow's jobs, `knos2:` lines) beside the
work orders (`knos3:` lines): `record` says which a line is. A version 1 file listed work orders only, so an
organisation that had only posted bounties got an empty one. Version 2 also adds `source`, `terms_version`,
`paid_each` and `held_until`. The file names its version in its first line (CSV) or in `version` (JSON), and `verify`
checks a file of either version by that version's columns.

Everything is recomputed from the second escrow's own log lines (knos.records: `events_of`, `orders_of`), never from a
database and never from an account's state today. So the file is a function of the chain and the period alone: two
parties who export the same owner and the same period get the same bytes, and compare one hash (the head) instead of
the file. Nothing is asked of GitHub: accounts and repositories are their numeric ids.

One row is one LINE of an order: a payment (one paying transaction, all its payees), a holdback released after its
warranty, a kill fee, a refund, a revert, or `open` / `held` for an order nothing has happened to by the end of the
period. Events after the last day (`--to`) are not read at all: the file says what was true at the end of that day.

    seq, date, time           the line's number in this file, and the UTC day and time of its transaction
    kind                      paid, released, kill, refunded, reverted, open, held
    record                    order (a work order) or bounty (a bounty on an issue). A bounty has no holdback, no
                              revert, no kill fee and one payee; those cells are 0 or empty on its lines
    order                     the order's address; funded_transaction says which funding of that address (an address
                              is used again once an order is closed)
    owner_id, funder          the Balance's owner (0: none), and gh:<id> or wallet:<address>; commenter_id: who funded by comment
    source                    the address the money came from: the Balance, or the wallet that funded
    authorised_by             who had authority over the money, and in which role, as the program found at funding:
                              `gh:<id> (owner)`, `gh:<id> (spender)` (an id the Balance's owner had listed),
                              `gh:<id> (faucet)` (test money any commenter spends), or `wallet:<address>` (knos.controls.authority_of)
    repository_id, issue      what was commissioned (0 and 0 for a private order: its line on chain names neither)
    private, standing, mode   1 or 0; 1 or 0 (a standing offer pays once per pull request); merge or tests
    price_units, price        what the order holds for its payees; funder_fee_units: what its funder put in on top
    currency                  "test USDC" (devnet money, never real), or `mint <address>`
    terms_hash                sha256 of the terms JSON the funding logged: the policy the order was accepted under
                              (empty for a private order: its terms are a hash in the order account, not in a log line)
    terms_version             the `v` of that terms JSON (empty when the log does not carry the terms)
    pull_request, artifact    the pull request the paying line names, and the artifact as the log gives it:
                              `pull:<repository id>#<number>`, and `commit:<sha>` on a revert (the only line that prints one)
    supplier_ids, wallets     who supplied: every GitHub id paid in this transaction, and where (`;` between several)
    paid_each                 what each of them received, in the order of supplier_ids (`;` between several)
    judge, evaluator          who evaluated: the rule of the program that accepted the signed token (JUDGES)
    verdict                   accepted, pending, expired (no accepted work by the deadline), reverted, none (a kill fee)
    paid_units, paid          what reached the suppliers in this line. A work order's fee is paid by its funder on top
                              (funder_fee_units); a bounty's fee is taken out of its price, so price = paid + fee
    held_units                what the order still holds after this line (a holdback in warranty; an order held for a wallet)
    held_until                until when: the end of a holdback's review window, of a hold for a wallet, or an open
                              order's deadline (empty when the log does not say)
    refunded_units, reverted_units   what went back to the funder: at the deadline, or on a revert inside the warranty
    fee_units, fee            the fee and tip this line's transaction took
    transaction               its signature
    billing_key               order:funded transaction:milestone, on a paid line. The milestone of a standing order is
                              the pull request (the program pays one once: ["done", order, pr]); any other order has one: 0
    billed_before             1 when an earlier line of this file has the same billing key. The program refuses that,
                              so 1 is a finding, and `verify` fails on it
    exception, resolved_by    what was not the plain path (cancelled, reverted, arbiter ruling, kill fee, held for a
                              wallet, refunded after a part was paid) and whose act the program required for it
    prev                      the hash of the row before (the first row's is the hash of the file's scope)

A row's hash is sha256 of its canonical JSON (every column as text, keys sorted). The file ends with the totals per
currency and the HEAD: the last row's hash. `verify` recomputes every hash, the totals and the head, so an edited,
removed, added or reordered row is found. What it cannot find: a file rewritten whole, hashes and all. That is what
the head is for: export the same period yourself and compare.

What the log does not say, and this file therefore does not: the commit of the workflows that signed (it is in the
order account while the order is open, and in the signed token of the paying transaction, which `transaction` names);
the head commit of an accepted pull request; names. A history the cluster did not give whole is refused unless
`--partial`, and then the scope says "partial" and the head is not one to compare.
The command reads the escrow's newest 1000 transactions at most (knos.records.read): an owner whose orders go further back
gets a partial file until the reader pages further.
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import json
import sys
import time
from pathlib import Path

from . import controls, ids, records
from .settle.v2 import pay as pay2

TYPE, VERSION = "knos.audit-export", 3         # files of versions 1 and 2 are still read, verified and written back as they were
COLUMNS_V1 = ("seq", "date", "time", "kind", "order", "funded_transaction", "owner_id", "funder", "commenter_id", "authorised_by", "repository_id",
              "issue", "private", "standing", "mode", "price_units", "price", "funder_fee_units", "currency", "terms_hash", "pull_request", "artifact",
              "supplier_ids", "wallets", "judge", "evaluator", "verdict", "paid_units", "paid", "held_units", "refunded_units", "reverted_units",
              "fee_units", "fee", "transaction", "billing_key", "billed_before", "exception", "resolved_by", "prev")
_ADDED = {"kind": ("record",), "funder": ("source",), "terms_hash": ("terms_version",), "wallets": ("paid_each",), "held_units": ("held_until",)}
COLUMNS_V2 = tuple(x for c in COLUMNS_V1 for x in (c, *_ADDED.get(c, ())))        # version 2: each new column after the one it explains
# version 3: the verdict in one of the four words (knos.ids.VERDICTS), and the four ids, each after the column it explains
_ADDED3 = {"verdict": ("outcome",), "billing_key": ("deliverable_id", "evaluation_id", "invoice_line_id", "settlement_id")}
COLUMNS = tuple(x for c in COLUMNS_V2 for x in (c, *_ADDED3.get(c, ())))
COLUMNS_OF = {1: COLUMNS_V1, 2: COLUMNS_V2, 3: COLUMNS}
# The log's word for a line -> the verdict that stands, in one of the four. `expired`: nothing was accepted by the deadline,
# so nothing shows acceptance. `reverted`: the acceptance was taken back inside the warranty. `none` (a kill fee) has no verdict.
OUTCOMES = {"accepted": "accepted", "pending": "insufficient_evidence", "expired": "insufficient_evidence", "reverted": "rejected", "none": ""}
MOVES = ("paid", "released", "kill", "refunded", "reverted")       # the kinds of line in which money moved
BOUNTY_JUDGE = ("repository", "prove.yml of the pinned workflows, run in the bounty's own repository")
SUMS = ("paid_units", "fee_units", "refunded_units", "reverted_units")
# knos3:settled judge=N (programs-v2/knos_pay/src/order_pay.rs, `Judge`), and what order_judge.rs requires of each
JUDGES = {0: ("repository", "prove.yml of the pinned workflows, run in the order's own repository"),
          1: ("neutral", "attest.yml of the pinned workflows, started by hand by the owner of the repository it ran in"),
          2: ("attestor", "prove.yml or attest.yml of the pinned workflows, run in the judge repository the order named at funding"),
          3: ("arbiter", "attest.yml of the pinned workflows, started by hand by the arbiter the order named at funding"),
          9: ("none", "no token: a payment the program had already accepted (a held payment settled, or a holdback released)")}
KINDS = ("paid", "released", "kill", "refunded", "reverted", "open", "held")
_STATE = ("open", "held")       # lines that say what an order is at the end of the period, whenever it was funded


class Refused(ValueError):
    """An export that cannot be made, or a file that is not one. The message says what happened and what to do."""


# ---- the lines ---------------------------------------------------------------------------------------------------------

def _facts(events: list[dict]) -> dict[tuple, dict]:
    """What `records.orders_of` does not keep, per order (address, funding transaction): the judge of each paying
    transaction, what each payment left held, and the transactions of a refund, a revert, a cancellation and a hold."""
    out: dict[tuple, dict] = {}
    live: dict[str, str | None] = {}
    for ev in events:
        name = ev["event"]
        if not name.startswith("order_"):
            continue
        address = str(ev.get("order", ""))
        if name == "order_funded":
            live[address] = ev.get("tx")
        f = out.setdefault((address, live.get(address)), {"judge": {}, "warranty": {}})
        if name == "order_settled":
            f["judge"][ev.get("tx")] = int(ev.get("judge", 9))
        elif name == "order_warranty":
            f["warranty"][ev.get("tx")] = int(ev.get("held", 0))
            f.setdefault("until", {})[ev.get("tx")] = ev.get("until")
        elif name in ("order_refunded", "order_reverted", "order_cancelled", "order_held"):
            f.setdefault(name[6:], ev)
    return out


def _mine(o: dict, owner_id: int, wallets: frozenset) -> bool:
    return (o["owner"] or o["by"]) == owner_id if o["from_balance"] else o["source"] in wallets


def lines(events: list[dict], owner_id: int, wallets=(), first: str = "", last: str = "", receipts: dict | None = None) -> list[dict]:
    """`receipts`: {transaction: its version 4 acceptance receipt}, when held; a line then carries that receipt's
    evaluation and invoice line ids (`four_of`).

    Every line of `owner_id`'s work orders, in the file's order, without `seq` and `prev`. An order is the owner's
    when its Balance is (or, for a comment that funded with no Balance on record, when the commenter is), or when a
    wallet in `wallets` funded it. `first`, `last`: UTC days, inclusive; events after `last` are not read."""
    if last:
        end = records.day_of(last, "--to")
        events = [ev for ev in events if records._day(ev["at"]) <= end]
    orders, _other = records.orders_of(events)
    facts, wallets = _facts(events), frozenset(str(w) for w in wallets)
    out: list[dict] = []
    for o in orders:
        if o["v"] == 2 and _mine(o, owner_id, wallets):
            out += _order_lines(o, facts.get((o["address"], o["tx"])) or {"judge": {}, "warranty": {}})
    for j in records.jobs_of(events)[0]:       # the bounties on issues: the second escrow's jobs
        if j["v"] == 2 and _mine(j, owner_id, wallets):
            out += _bounty_lines(j, events)
    out = [r for r in out if r["kind"] in _STATE or ((not first or r["date"] >= first) and (not last or r["date"] <= last))]
    out.sort(key=lambda r: (r["time"], r["order"], r["funded_transaction"], KINDS.index(r["kind"]), r["transaction"]))
    seen: set[str] = set()
    for r in out:       # a second line can never bill the same order and milestone: said per line, and checked by `verify`
        r["billed_before"] = int(bool(r["billing_key"]) and r["billing_key"] in seen)
        seen.add(r["billing_key"])
        r.update(four_of(r, (receipts or {}).get(r["transaction"])))
    return out


def four_of(row: dict, receipt: dict | None = None) -> dict:
    """What version 3 adds to a line: `outcome`, the verdict in one of the four words, and the four ids (knos.ids).

        deliverable_id     the order and the milestone (a standing order's is the pull request). Empty for a standing
                           order's line that names no pull request: money that is no deliverable's.
        settlement_id      this deliverable and this transaction, on the lines in which money moved; else empty.
        evaluation_id      the log does not carry the commit or the run, so a line has it only from `receipt`: the
                           version 4 acceptance receipt of the line's transaction (it is that receipt's own id).
        invoice_line_id    the supplier's line. The chain never sees an invoice: from `receipt`, else empty.

    A receipt that is of another deliverable or settlement than the line is refused."""
    said = {k: _text(row.get(k, "")) for k in ("order", "standing", "pull_request", "kind", "transaction", "verdict")}
    known = said["standing"] != "1" or bool(said["pull_request"])
    try:
        scope = ids.order_scope(said["order"])
    except ValueError:          # a bounty with no address on record is named `bounty:<repository>#<issue>`
        scope = said["order"]
    dlv = ids.deliverable(scope, int(said["pull_request"]) if said["standing"] == "1" else 0) if known else ""
    out = {"outcome": OUTCOMES.get(said["verdict"], ""), "deliverable_id": dlv, "evaluation_id": "", "invoice_line_id": "",
           "settlement_id": ids.settlement(dlv, "chain", said["transaction"]) if dlv and said["transaction"] and said["kind"] in MOVES else ""}
    if receipt is not None and receipt.get("version") in (4, 5):
        got = receipt["ids"]
        if got["deliverable"] != dlv or (got["settlement"] or "") not in ("", out["settlement_id"]):
            raise Refused(f"The receipt given for transaction {said['transaction']} is of another deliverable or settlement than the line it is given for.")
        out.update(evaluation_id=got["evaluation"], invoice_line_id=got["invoice_line"] or "", outcome=receipt["evaluator_observed"]["verdict"])
    return out


def _order_lines(o: dict, f: dict) -> list[dict]:
    cur = records._currency(o)
    text = records.units_text if cur == records.TEST else (lambda n: "")
    terms = o.get("terms")
    cancelled = f.get("cancelled")
    base = {"record": "order", "order": o["address"], "funded_transaction": o["tx"] or "", "owner_id": o["owner"], "funder": o["funder"],
            "source": o["source"], "commenter_id": o["by"], "terms_version": _terms_version(terms),
            "authorised_by": controls.authority_of(o)["authorised_by"], "repository_id": o["repo"] or 0, "issue": o["issue"] or 0, "private": int(o["private"]), "standing": int(o["standing"]),
            "mode": "tests" if o["mode"] else "merge", "price_units": o["amount"], "price": text(o["amount"]), "funder_fee_units": o["fee_escrowed"],
            "currency": cur, "terms_hash": pay2.terms_hash(terms.encode()).hex() if terms else ""}

    def line(kind: str, at: int, tx, verdict: str, *, pr=None, ids=(), tos=(), judge: int | None = None, paid: int = 0, held: int = 0,
             refunded: int = 0, reverted: int = 0, fee: int = 0, artifact: str = "", exception: tuple = (), resolved: tuple = (), each=(),
             until=None) -> dict:
        if cancelled:       # every line of a cancelled order says so
            exception = (*exception, f"cancelled on {records._day(cancelled['at'])} ({cancelled.get('tx') or ''})")
            resolved = (*resolved, "cancel: the funding wallet's signature, or a command token of the funder or the Balance's owner")
        kind_, who = JUDGES.get(judge, ("", "")) if judge is not None else ("", "")
        billing = f"{o['address']}:{o['tx'] or ''}:{(pr or 0) if o['standing'] else 0}" if kind == "paid" else ""
        return {**base, "date": records._day(at), "time": records._stamp(at), "kind": kind, "pull_request": "" if pr is None else pr,
                "artifact": artifact or (f"pull:{o['repo'] or 0}#{pr}" if pr else ""), "supplier_ids": ";".join(str(i) for i in ids),
                "wallets": ";".join(t for t in tos if t), "paid_each": ";".join(str(n) for n in each), "judge": kind_, "evaluator": who,
                "verdict": verdict, "paid_units": paid, "paid": text(paid), "held_units": held, "held_until": records._stamp(until) if until else "", "refunded_units": refunded, "reverted_units": reverted, "fee_units": fee, "fee": text(fee),
                "transaction": tx or "", "billing_key": billing, "billed_before": 0, "exception": "; ".join(exception), "resolved_by": "; ".join(resolved)}

    out: list[dict] = []
    by_tx: dict[tuple, list[dict]] = {}
    for p in o["payments"]:
        by_tx.setdefault((p["tx"], p["kind"]), []).append(p)
    for (tx, kind), rows in by_tx.items():
        judge = f["judge"].get(tx, 9)
        exc: tuple[str, ...] = ()
        res: tuple[str, ...] = ()
        if judge == 3:
            exc, res = ("arbiter ruling",), ("rule: the arbiter the order named at funding",)
        if kind == "kill":
            exc, res = ("kill fee to the taker of a cancelled order",), ("the order's own terms, at its refund",)
        out.append(line(kind, rows[0]["at"], tx, "none" if kind == "kill" else "accepted", pr=rows[0]["pr"] or None, ids=[p["payee"] for p in rows],
                        tos=[p["to"] for p in rows], judge=None if kind == "kill" else judge, paid=sum(p["amount"] for p in rows),
                        held=f["warranty"].get(tx, 0), fee=sum(p["fee"] for p in rows), exception=exc, resolved=res, each=[p["amount"] for p in rows],
                        until=f.get("until", {}).get(tx) if f["warranty"].get(tx) else None))
    if o.get("refunded_at") is not None and f.get("refunded"):
        part = bool(o.get("paid_at"))
        out.append(line("refunded", o["refunded_at"], f["refunded"].get("tx"), "accepted" if part else "expired", refunded=o.get("refunded_amount", 0),
                        exception=("refunded after a part was paid",) if part else (), resolved=("refund: anyone, once the deadline has passed",) if part else ()))
    if o.get("reverted_at") is not None and f.get("reverted"):
        head = str(f["reverted"].get("head") or "")
        out.append(line("reverted", o["reverted_at"], f["reverted"].get("tx"), "reverted", reverted=o.get("reverted_amount", 0),
                        artifact=f"commit:{head}" if head else "", exception=("reverted inside the warranty",),
                        resolved=("revert: a token of the order's own repository, a neutral attest run or its judge repository",)))
    if o["state"] == "held" and f.get("held"):
        h = f["held"]
        out.append(line("held", h["at"], h.get("tx"), "accepted", pr=h.get("pr") or None, ids=[h.get("payee", 0)], held=o["amount"] - o["net"], until=h.get("until"),
                        exception=("held: the payee has bound no wallet",), resolved=("the payee binds a wallet, then anyone settles",)))
    elif o["state"] == "open" and not out:
        out.append(line("open", o["at"], o["tx"], "pending", held=o["amount"], until=o.get("deadline")))
    return out


def _terms_version(terms) -> str:
    try:
        v = json.loads(terms).get("v") if terms else None
    except (ValueError, AttributeError):
        v = None
    return "" if v is None else str(v)


def _bounty_lines(j: dict, events: list[dict]) -> list[dict]:
    """The lines of one bounty on an issue (a job of knos.records.jobs_of): paid, refunded, held for a wallet, or open.
    The escrow pays a bounty once, to one payee, on a prove token of the bounty's own repository, and keeps its fee out
    of the price. `order` is the job's address, so a bounty's billing key reads like an order's."""
    cur = records._currency(j)
    text = records.units_text if cur == records.TEST else (lambda n: "")
    terms, address = j.get("terms"), j.get("address") or f"bounty:{j['repo']}#{j['issue']}"

    def event(name: str, at=None) -> dict:
        """The job's own line of that name: logged in a transaction that names the job's address, after its funding."""
        found = [ev for ev in events if ev["event"] == name and ev["v"] == 2 and ev["at"] >= j["at"] and (at is None or ev["at"] == at)
                 and (j.get("address") in ev.get("keys", ()) or (ev.get("repo"), ev.get("issue")) == (j["repo"], j["issue"]))]
        return found[-1] if found else {}
    funded = next((ev for ev in events if ev["event"] == "funded" and ev.get("tx") == j["tx"] and ev["v"] == 2), {})
    base = {"record": "bounty", "order": address, "funded_transaction": j["tx"] or "", "owner_id": j["owner"], "funder": j["funder"], "source": j["source"],
            "commenter_id": j["by"], "authorised_by": controls.authority_of(j)["authorised_by"], "repository_id": j["repo"] or 0, "issue": j["issue"] or 0,
            "private": 0, "standing": 0, "mode": "tests" if funded.get("mode") else "merge", "price_units": j["amount"], "price": text(j["amount"]),
            "funder_fee_units": 0, "currency": cur, "terms_hash": pay2.terms_hash(terms.encode()).hex() if terms else "",
            "terms_version": _terms_version(terms)}

    def line(kind: str, at: int, tx, verdict: str, *, paid: int = 0, held: int = 0, refunded: int = 0, fee: int = 0, judged: bool = False,
             until=None, exception: str = "", resolved: str = "") -> dict:
        pr, payee = j.get("pr") if kind == "paid" else None, j.get("payee") if kind in ("paid", "held") else 0
        return {**base, "date": records._day(at), "time": records._stamp(at), "kind": kind, "pull_request": pr or "",
                "artifact": f"pull:{j['repo'] or 0}#{pr}" if pr else "", "supplier_ids": str(payee) if payee else "",
                "wallets": str(j.get("to") or "") if kind == "paid" else "", "paid_each": str(paid) if kind == "paid" else "",
                "judge": BOUNTY_JUDGE[0] if judged else "", "evaluator": BOUNTY_JUDGE[1] if judged else "", "verdict": verdict, "paid_units": paid,
                "paid": text(paid), "held_units": held, "held_until": records._stamp(until) if until else "", "refunded_units": refunded,
                "reverted_units": 0, "fee_units": fee, "fee": text(fee), "transaction": tx or "",
                "billing_key": f"{address}:{j['tx'] or ''}:0" if kind == "paid" else "", "billed_before": 0, "exception": exception, "resolved_by": resolved}

    if j["state"] == "paid":
        return [line("paid", j["paid_at"], j.get("paid_tx"), "accepted", paid=j["net"], fee=j["fee"], judged=True)]
    if j["state"] == "refunded":
        ev = event("refunded", j["refunded_at"])
        return [line("refunded", j["refunded_at"], ev.get("tx"), "expired", refunded=int(ev.get("amount", j["amount"])))]
    if j["state"] == "held":
        ev = event("held")
        return [line("held", ev.get("at", j["at"]), ev.get("tx"), "accepted", held=j["amount"], until=ev.get("until"), judged=True,
                     exception="held: the payee has bound no wallet", resolved="the payee binds a wallet, then anyone settles")]
    return [line("open", j["at"], j["tx"], "pending", held=j["amount"])]


# ---- the hash chain ----------------------------------------------------------------------------------------------------

def _hash(doc: dict) -> str:
    return hashlib.sha256(json.dumps({k: _text(v) for k, v in doc.items()}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _text(value) -> str:
    return "" if value is None else str(int(value)) if isinstance(value, bool) else str(value)


def scope_of(owner_id: int, first: str = "", last: str = "", wallets=(), partial: bool = False) -> dict:
    """What a file is an export OF. Its hash is the first row's `prev`, so a row cannot be moved to another export."""
    return {"type": TYPE, "version": VERSION, "program": str(pay2.PAY_ID), "owner_id": int(owner_id), "from": first, "to": last,
            "wallets": ";".join(sorted(str(w) for w in wallets)), "partial": int(partial)}


def columns_of(scope: dict) -> tuple:
    """The columns of a file of this scope's version. Refused, in words, for a version this release does not know."""
    try:
        return COLUMNS_OF[int(scope["version"])]
    except (KeyError, TypeError, ValueError):
        raise Refused(f"This audit export says it is of version {scope.get('version') if isinstance(scope, dict) else '?'}; this release reads "
                      f"versions {', '.join(str(v) for v in COLUMNS_OF)}. Update knos, or export it again.") from None


def chained(rows: list[dict], scope: dict) -> tuple[list[dict], str]:
    """(the rows with `seq` and `prev`, the head). The head of an empty export is the hash of its scope."""
    prev, out = _hash(scope), []
    for n, r in enumerate(rows, 1):
        row = {c: {**r, "seq": n, "prev": prev}.get(c, "") for c in columns_of(scope)}
        out.append(row)
        prev = _hash(row)
    return out, prev


def totals(rows: list[dict]) -> dict[str, dict]:
    """Per currency (never added across mints): how many lines, and the sum of each money column."""
    out: dict[str, dict] = {}
    for r in rows:
        t = out.setdefault(_text(r["currency"]), {"lines": 0, **{c: 0 for c in SUMS}})
        t["lines"] += 1
        for c in SUMS:
            t[c] += int(r[c] or 0)
    return dict(sorted(out.items()))


def export(events: list[dict], owner_id: int, fmt: str = "csv", first: str = "", last: str = "", wallets=(), partial: bool = False) -> str:
    """The file. The same events, owner and period give the same bytes."""
    scope = scope_of(owner_id, first, last, wallets, partial)
    rows, head = chained(lines(events, owner_id, wallets, first, last), scope)
    return write(scope, rows, head, fmt)


def write(scope: dict, rows: list[dict], head: str, fmt: str) -> str:
    """The file. A version 2 file names its version: the first line of the CSV is `knos.audit-export,version,2`, and
    the JSON has `version`. A scope of version 1 is written as version 1 was: its columns first, and no version line."""
    sums, columns, version = totals(rows), columns_of(scope), int(scope["version"])
    if fmt == "json":
        doc = {"scope": scope, "columns": list(columns), "rows": rows, "totals": sums, "head": head, "rows_count": len(rows)}
        return json.dumps({**doc, **({"version": version} if version > 1 else {})}, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    if fmt != "csv":
        raise Refused(f"--format is csv or json; {fmt!r} is neither.")
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    if version > 1:
        out.writerow([TYPE, "version", version])
    out.writerow(columns)
    for r in rows:
        out.writerow([records._cell(_text(r[c])) for c in columns])
    for cur, t in sums.items():
        out.writerow(["total", cur, t["lines"], *(t[c] for c in SUMS)])
    out.writerow(["head", head, len(rows), json.dumps(scope, sort_keys=True, separators=(",", ":"))])
    return buf.getvalue()


# ---- verify ------------------------------------------------------------------------------------------------------------

def parse(text: str) -> tuple[dict, list[dict], dict, str, int]:
    """(scope, rows as text, totals, head, the row count the file states) of a file `write` made, CSV or JSON."""
    if text.lstrip().startswith("{"):
        try:
            d = json.loads(text)
            columns = columns_of(d["scope"])
            if int(d.get("version", 1)) != int(d["scope"]["version"]):
                raise Refused(f"This audit export says version {d.get('version', 1)} and its scope says {d['scope']['version']}: it was edited.")
            return d["scope"], [{c: _text(r[c]) for c in columns} for r in d["rows"]], d["totals"], str(d["head"]), int(d["rows_count"])
        except (ValueError, KeyError, TypeError) as why:
            raise Refused(f"This is not an audit export: {type(why).__name__}: {why}. Export it again with `knos audit export`.") from None
    got = list(csv.reader(io.StringIO(text)))
    version = 1
    if got and got[0][:2] == [TYPE, "version"] and len(got[0]) == 3 and got[0][2].isdigit():       # the line that names the version (2 and later)
        version, got = int(got[0][2]), got[1:]
    columns = columns_of({"version": version})
    if not got or tuple(got[0]) != columns:
        raise Refused("This is not an audit export: its first line is not the columns of one. Export it again with `knos audit export`.")
    rows, sums, head, count, scope = [], {}, "", -1, None
    for cells in got[1:]:
        if cells[:1] == ["total"] and len(cells) == 3 + len(SUMS):
            sums[cells[1]] = {"lines": int(cells[2]), **{c: int(v) for c, v in zip(SUMS, cells[3:])}}
        elif cells[:1] == ["head"] and len(cells) == 4:
            head, count, scope = cells[1], int(cells[2]), json.loads(cells[3])
        elif len(cells) == len(columns) and not sums and scope is None:
            rows.append({c: (v[1:] if v[:1] == "'" else v) for c, v in zip(columns, cells)})
        else:
            raise Refused(f"This is not an audit export: line {len(rows) + 2} is not a row, a total or the head.")
    if scope is None:
        raise Refused("This audit export has no last line (`head`): it was cut short. Export it again.")
    if not isinstance(scope, dict) or scope.get("version") != version:
        raise Refused(f"This audit export's columns are those of version {version} and its last line says another version: it was edited.")
    return scope, rows, sums, head, count


def verify(text: str) -> list[str]:
    """What is wrong with an export, in words; empty when every hash, the totals and the head hold."""
    scope, rows, sums, head, count = parse(text)
    said: list[str] = []
    prev, seen = _hash(scope), set()
    for n, r in enumerate(rows, 1):
        if r["seq"] != str(n):
            said.append(f"Row {n} is numbered {r['seq']}: a row was removed, added or moved before it.")
        if r["prev"] != prev:
            said.append(f"Row {n} does not follow the row before it (its `prev` is not that row's hash): row {n - 1 or 'scope'} was edited or "
                        f"removed, or this row was moved.")
        if "deliverable_id" in r:       # version 3: an id of one kind is never taken where another is expected, and two follow from the line
            for col, kind in (("deliverable_id", "deliverable"), ("evaluation_id", "evaluation"), ("invoice_line_id", "invoice_line"), ("settlement_id", "settlement")):
                if r[col] and ids.kind_of(r[col]) != kind:
                    said.append(f"Row {n}: {col} holds {r[col][:40]!r}, which is not the id of {'an' if kind[0] in 'aei' else 'a'} {kind.replace('_', ' ')}.")
            want = four_of(r)
            if (r["deliverable_id"], r["settlement_id"]) != (want["deliverable_id"], want["settlement_id"]):
                said.append(f"Row {n}: its deliverable or settlement id is not the one its order, milestone and transaction give.")
            if r["outcome"] not in ("", *ids.VERDICTS) or (r["outcome"] in ids.BILLABLE) != (r["verdict"] == "accepted" and r["outcome"] != ""):
                said.append(f"Row {n}: its outcome is not one of the four verdicts, or says accepted where the line does not.")
        if r["billing_key"] and (r["billing_key"] in seen or r["billed_before"] != "0"):
            said.append(f"Row {n} bills {r['billing_key']} a second time. The program pays an order's milestone once: this file is wrong, or the "
                        "program is. Compare the transactions on chain.")
        seen.add(r["billing_key"])
        prev = _hash(r)
    if prev != head:
        said.append("The head does not match the last row: the last row was edited or removed, or rows were added after it.")
    if count != len(rows):
        said.append(f"The file says it has {count} rows and has {len(rows)}.")
    if {k: {c: int(v) for c, v in t.items()} for k, t in sums.items()} != totals(rows):
        said.append("The totals are not the sums of the rows.")
    return said


# ---- the four linked objects ---------------------------------------------------------------------------------------------
# What a finance reader needs on one screen for one deliverable: who authorised it and under which budget, why it was
# accepted, what it is as a billable line, and where its money is. Everything is made from the rows of a statement (as
# text, the way `parse` gives them), so whoever holds the same statement holds the same records. Three things the
# statement cannot say are passed in when they are known, and are null with a sentence when they are not:
#     ref        the buyer's own reference for the deliverable (a purchase order or an invoice line), and a payment made
#                by bank. From a side file (`--refs refs.csv`): the terms an order is paid under are hashed on chain and
#                have no free-text field, so a reference is never put there.
#     receipt    the acceptance receipt of the paying transaction (knos.receipt, version 3): the Balance's limits when
#                it funded, and each evaluator's owner, starter and independence flags.
#     approval   for an order a Squads vault funded: the multisig, its threshold, its members and who approved
#                (`squads_approval` reads them from the chain).
# web/finance_data.js is the same shaping for the console; tests/data/finance holds the cases both must answer alike.
OBJECTS = ("authorisation", "acceptance", "commercial", "settlement")
SETTLEMENTS = ("paid on devnet (test money)", "held", "refunded", "reverted", "payable", "paid outside Knos")        # a record's status is one of these
PAID, HELD, REFUNDED, REVERTED, PAYABLE, OUTSIDE = SETTLEMENTS
REF_COLUMNS = ("order", "ref", "paid_outside", "dispute")
NO_SECOND = ("One account funded this by comment, within the Balance's limits. No second person approved: Knos has no approval step of its own.")
ONE_WALLET = ("One wallet signed the funding. If that wallet is a multisig's vault, the multisig's threshold is the approval, and "
              "`knos audit show` reads it from the chain.")
FAUCET = "Test money from the devnet faucet, which any commenter in the owner's repositories may spend. Nobody approved it, and nothing real was spent."
MULTISIG = ("A Squads vault funded this: {threshold} of its {members} members had to approve{approved}. This is the two-person approval Knos has "
            "today. It is the multisig's own rule, not a workflow inside Knos.")
ONE_OF = ("A Squads vault funded this, and its threshold is 1 of {members}: one member alone could approve. That is not a two-person approval.")
NO_LIMITS = ("The log lines do not carry a Balance's limits. The acceptance receipt of the paying transaction has them as they were at funding "
             "(`knos receipt`), and `knos budget show` reads today's.")
NO_EVALUATORS = ("The log line names the program's rule, not the accounts. The acceptance receipt names each evaluator's owner and starter, and "
                 "whether either is the buyer's or the seller's.")
EXPLORER = "https://explorer.solana.com/tx/{}?cluster=devnet"


def deliverable_of(row: dict) -> str:
    """The billable deliverable a line belongs to: order:funded transaction:milestone. A paid line's is its billing key.
    A standing order pays once per pull request, so its milestone is the pull request, and its lines that name none
    (the rest that went back, the order while open) are `-`: money that is no deliverable's. Any other order has one, 0."""
    if row["billing_key"]:
        return str(row["billing_key"])
    milestone = (_text(row["pull_request"]) or "-") if _text(row["standing"]) == "1" else "0"
    return f"{row['order']}:{row['funded_transaction']}:{milestone}"


def deliverables(rows: list[dict]) -> dict[str, list[dict]]:
    """The rows of a statement by deliverable, in the file's order."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(deliverable_of(r), []).append({k: _text(v) for k, v in r.items()})
    return out


def read_refs(text: str) -> dict[str, dict]:
    """A refs file: CSV with the columns order, ref, paid_outside, dispute (the last two may be left out).

        order          a deliverable (order:funded transaction:milestone, as `billing_key` prints it), or an order's
                       address alone for every deliverable of it
        ref            the buyer's purchase order or invoice line for it
        paid_outside   empty, or how the buyer paid it outside Knos (a date, a bank reference): the settlement status
                       is then `paid outside Knos`
        dispute        empty, or what is disputed, in the party's own words

    It is the party's own statement, not the chain's: it changes no row and no hash of the statement."""
    got = list(csv.reader(io.StringIO(text)))
    if not got or got[0][:2] != ["order", "ref"] or any(c not in REF_COLUMNS for c in got[0]):
        raise Refused("A refs file is a CSV whose first line is order,ref,paid_outside,dispute (the last two may be left out).")
    out = {}
    for n, cells in enumerate(got[1:], 2):
        if not any(c.strip() for c in cells):
            continue
        row = {**{c: "" for c in REF_COLUMNS}, **{c: v.strip() for c, v in zip(got[0], cells)}}
        if not row["order"] or len(cells) > len(got[0]):
            raise Refused(f"Line {n} of the refs file names no order, or has more cells than the first line has columns.")
        out[row["order"]] = row
    return out


def ref_of(refs: dict | None, deliverable: str) -> dict | None:
    """What the refs file says of a deliverable: its own line, else the line of its order's address."""
    return (refs or {}).get(deliverable) or (refs or {}).get(deliverable.split(":")[0])


def _money(units: int, currency: str) -> str:
    return records.units_text(units) if currency == records.TEST else ""


def _each(rows: list[dict]) -> list[dict]:
    """Who was paid what for a deliverable: [{github_id, wallet, units}], one per supplier, in the order first paid."""
    out: dict[str, dict] = {}
    for r in rows:
        ids, tos, each = (r["supplier_ids"].split(";") if r["supplier_ids"] else []), r["wallets"].split(";"), r.get("paid_each", "").split(";")
        for n, who in enumerate(ids):
            e = out.setdefault(who, {"github_id": who, "wallet": "", "units": 0})
            e["wallet"] = e["wallet"] or (tos[n] if n < len(tos) else "")
            if r["kind"] in ("paid", "released"):       # a version 1 line does not say each share: one supplier has it all
                e["units"] += int(each[n]) if n < len(each) and each[n] else int(r["paid_units"]) if len(ids) == 1 else 0
    return list(out.values())


def record(rows: list[dict], ref: dict | None = None, receipt: dict | None = None, approval: dict | None = None) -> dict:
    """One deliverable as four linked objects, from its rows of a statement (text, in the file's order; all of one
    `deliverable_of`). See the comment above for `ref`, `receipt` and `approval`.

        authorisation   buyer, supplier, scope (repository, issue, deliverable), budget (which Balance or wallet, its
                        limits at funding when a receipt has them), approved_by (who funded, in which role, and whether
                        a second person had to approve)
        acceptance      artifact, policy (the terms' hash and version, the mode), evaluators with their independence
                        flags, evidence (a link per transaction), verdict
        commercial      deliverable, amount accepted, fee, currency, the buyer's reference, billed_before, dispute,
                        correction (a credit after a revert, a refund of the rest)
        settlement      status: one of SETTLEMENTS, and the amounts behind it"""
    blank = {c: "" for c in COLUMNS}        # a row of a version 1 statement has fewer columns: what it does not say is empty
    rows = [{**blank, **{k: _text(v) for k, v in r.items()}} for r in rows]
    first, last, cur = rows[0], rows[-1], rows[0]["currency"]
    total = lambda col, kinds=None: sum(int(r[col] or 0) for r in rows if kinds is None or r["kind"] in kinds)   # noqa: E731
    paid, refunded, reverted = total("paid_units", ("paid", "released")), total("refunded_units"), total("reverted_units")
    still = int(last["held_units"] or 0)
    waiting = last["kind"] == "held"                                   # accepted, and held for a wallet the supplier has not bound
    accepted = any(r["verdict"] == "accepted" and r["kind"] in ("paid", "released", "held") for r in rows)
    amount = paid + (still if waiting else 0)
    outside = (ref or {}).get("paid_outside") or ""
    funder, _, role = first["authorised_by"].partition(" (")
    role = role.rstrip(")") or "wallet"

    if approval:
        k, n, who = int(approval["threshold"]), len(approval["members"]), approval.get("approved")
        said = (MULTISIG.format(threshold=k, members=n, approved="" if who is None else f", and {len(who)} did") if k >= 2 else ONE_OF.format(members=n))
    else:
        said = {"wallet": ONE_WALLET, "faucet": FAUCET}.get(role, NO_SECOND)
    c3 = (receipt or {}).get("commercial_authorisation") if (receipt or {}).get("version") in (3, 4) else None
    seen = (receipt or {}).get("evaluator_observed") if c3 else None
    judged = [r for r in rows if r["judge"]]
    evaluators = ([{k: e.get(k) for k in ("kind", "repository_id", "owner_id", "actor_id", "runner", "independent_of_buyer", "independent_of_seller")}
                   for e in seen["evaluators"]] if seen else
                  [{"kind": r["judge"], "rule": r["evaluator"], "independent_of_buyer": False if r["judge"] == "repository" else None,
                    "independent_of_seller": None} for r in judged[:1]])
    evidence, linked = [], set()
    for what, tx in [("funded", first["funded_transaction"]), *((r["kind"], r["transaction"]) for r in rows)]:
        if tx and tx not in linked:
            linked.add(tx)
            evidence.append({"what": what, "transaction": tx, "link": EXPLORER.format(tx)})

    ruling = next((r for r in rows if "arbiter ruling" in r["exception"]), None)
    ref = ref or {}
    dispute = (f"open, as the refs file says: {ref['dispute']}" if ref.get("dispute")
               else f"ruled by the arbiter the order named (line {ruling['seq']}, {ruling['transaction']})" if ruling else None)
    back = next((r for r in rows if r["kind"] == "reverted"), None) or next((r for r in rows if r["kind"] == "refunded" and paid), None)
    correction = None if back is None else {
        "kind": "credit" if back["kind"] == "reverted" else "refund", "units": int(back[f"{back['kind']}_units"]), "line": int(back["seq"] or 0),
        "transaction": back["transaction"],
        "said": ("Reverted inside the review window: what the order still held went back to the funder. What was already paid stays paid."
                 if back["kind"] == "reverted" else "The rest of the order went back to the funder after a part was paid.")}

    if reverted:
        status, why = REVERTED, f"{_units(reverted, cur)} went back to the funder on {back['date'] if back else last['date']}; {_units(paid, cur)} stays paid."
    elif outside:
        status = OUTSIDE
        why = f"The buyer says it paid outside Knos: {outside}." + (" The chain also shows a payment on devnet: check that it was not paid twice." if paid else "")
    elif waiting:
        status, why = PAYABLE, (f"Accepted, and {_units(still, cur)} is owed. Held for the supplier's wallet"
                                f"{' until ' + last['held_until'] if last['held_until'] else ''}: the supplier binds a wallet, then anyone settles.")
    elif paid:
        status = PAID
        why = f"{_units(paid, cur)} reached the supplier on {next(r['date'] for r in rows if r['kind'] in ('paid', 'released'))}." + (
            f" {_units(still, cur)} is held back in a review window{' until ' + last['held_until'] if last['held_until'] else ''}." if still else "")
    elif refunded:
        status, why = REFUNDED, f"{_units(refunded, cur)} went back to the funder on {last['date']}. Nothing was accepted."
    else:
        status, why = HELD, (f"Funded, and nothing is accepted yet. The escrow holds {_units(still, cur)}"
                             f"{' until ' + last['held_until'] if last['held_until'] else ''}.")
    return {
        "id": deliverable_of(first), "record": first.get("record") or "order",
        "authorisation": {
            "buyer": {"owner_id": first["owner_id"], "funder": first["funder"], "login": ((c3 or {}).get("funder") or {}).get("login")},
            "supplier": _each(rows),
            "scope": {"repository_id": first["repository_id"], "issue": first["issue"], "deliverable": deliverable_of(first), "private": first["private"] == "1"},
            "budget": {"kind": "wallet" if role == "wallet" else "faucet Balance" if role == "faucet" else "Balance",
                       "address": first.get("source") or (funder[7:] if funder.startswith("wallet:") else None),
                       "limits_at_funding": c3["limit"] if c3 else None,
                       "said": None if c3 else "A wallet has no limits of Knos's: it spends what it holds." if role == "wallet" else NO_LIMITS},
            "approved_by": {"funder": funder, "role": role, "two_person": bool(approval and int(approval["threshold"]) >= 2),
                            "multisig": approval or None, "said": said}},
        "acceptance": {
            "accepted": accepted,
            "artifact": next((r["artifact"] for r in reversed(rows) if r["artifact"] and r["kind"] != "reverted"), "") or None,
            "policy": {"terms_hash": first["terms_hash"] or None, "version": first.get("terms_version") or None, "mode": first["mode"]},
            "evaluators": evaluators,
            "independence": seen["independence"] if seen else NO_EVALUATORS if evaluators else None,
            "evidence": evidence, "verdict": last["verdict"]},
        "commercial": {
            "deliverable": deliverable_of(first), "amount_units": amount, "amount": _money(amount, cur), "price_units": int(first["price_units"] or 0),
            "fee_units": total("fee_units"), "fee": _money(total("fee_units"), cur), "currency": cur, "invoice_ref": (ref or {}).get("ref") or None,
            "billed_before": any(r["billed_before"] == "1" for r in rows), "dispute": dispute, "correction": correction,
            "lines": [int(r["seq"] or 0) for r in rows]},
        "settlement": {"status": status, "said": why, "paid_units": paid, "held_units": still, "refunded_units": refunded, "reverted_units": reverted,
                       "held_until": last["held_until"] or None, "paid_outside": outside or None}}


def _units(units: int, currency: str) -> str:
    return f"{records.units_text(units)} {currency}" if currency == records.TEST else f"{units} units of {currency}"


def records_of(rows: list[dict], refs: dict | None = None, receipts: dict | None = None, approvals: dict | None = None) -> list[dict]:
    """Every deliverable of a statement as `record` gives it, in the order each first appears. `receipts`: {paying
    transaction: receipt}; `approvals`: {funding transaction: approval}."""
    out = []
    for key, mine in deliverables(rows).items():
        have = receipts or {}
        receipt = next((have[r["transaction"]] for r in mine if r["transaction"] in have), None)
        out.append(record(mine, ref_of(refs, key), receipt, (approvals or {}).get(mine[0]["funded_transaction"])))
    return out


def record_lines(rec: dict) -> list[str]:
    """A record as `knos audit show` prints it: four blocks, each a heading and its lines."""
    a, c, m, s = (rec[k] for k in OBJECTS)
    cur = m["currency"]
    ms = a["approved_by"]["multisig"]
    limit = a["budget"]["limits_at_funding"]
    out = [f"Deliverable {rec['id']} ({'a bounty on an issue' if rec['record'] == 'bounty' else 'a work order'})", "",
           "AUTHORISATION",
           f"  Buyer        GitHub id {a['buyer']['owner_id']}" + (f" ({a['buyer']['login']})" if a["buyer"]["login"] else "") + f"; funded by {a['buyer']['funder']}",
           "  Supplier     " + ("; ".join(f"GitHub id {e['github_id']}" + (f" to {e['wallet']}" if e["wallet"] else "") for e in a["supplier"]) or "nobody yet"),
           "  Scope        " + ("a private order: the chain names no repository" if a["scope"]["private"]
                                else f"repository id {a['scope']['repository_id']}, issue {a['scope']['issue']}"),
           f"  Budget       {a['budget']['kind']} {a['budget']['address'] or ''}".rstrip(),
           "  Limits       " + (a["budget"]["said"] if limit is None else limit if isinstance(limit, str) else
                                f"cap per order {limit['cap_per_order']}, daily {limit['daily']}, total {limit['total']} (units; 0: none), "
                                f"repositories {limit['repositories'] or 'any of the owner'}"),
           f"  Approved by  {a['approved_by']['funder']} as {a['approved_by']['role']}",
           *([f"  Multisig     {ms['multisig']}, vault {ms['vault']}: {ms['threshold']} of {len(ms['members'])}",
              "  Approved     " + ("the proposal's account is closed: who approved is no longer on chain" if ms.get("approved") is None else ", ".join(ms["approved"]))]
             if ms else []),
           f"               {a['approved_by']['said']}", "",
           "ACCEPTANCE",
           f"  Artifact     {c['artifact'] or 'none yet'}",
           f"  Policy       terms sha256:{c['policy']['terms_hash'] or '(not in the log: a private order)'}, version {c['policy']['version'] or 'unknown'}, paid on {c['policy']['mode']}",
           *(f"  Evaluator    {e['kind']}" + (f": {e['rule']}" if e.get("rule") else f": repository {e['repository_id']}, owner {e['owner_id']}, started by {e['actor_id']}")
             + f" (independent of the buyer: {_flag(e['independent_of_buyer'])}; of the seller: {_flag(e['independent_of_seller'])})" for e in c["evaluators"]),
           *([f"               {c['independence']}"] if c["independence"] else ["  Evaluator    none yet"]),
           *(f"  Evidence     {e['what']}: {e['link']}" for e in c["evidence"]),
           f"  Verdict      {c['verdict']}", "",
           "COMMERCIAL RECORD",
           f"  Deliverable  {m['deliverable']}",
           f"  Amount       {_units(m['amount_units'], cur)} accepted, of a price of {_units(m['price_units'], cur)}; fee {_units(m['fee_units'], cur)}",
           f"  Invoice line {m['invoice_ref'] or 'none given (a refs file can name the purchase order or invoice line: --refs)'}",
           f"  Billed before  {'YES: an earlier line bills this deliverable' if m['billed_before'] else 'no'}",
           f"  Dispute      {m['dispute'] or 'none on record'}",
           f"  Correction   {m['correction']['kind'] + ' of ' + _units(m['correction']['units'], cur) + ' (line ' + str(m['correction']['line']) + '). ' + m['correction']['said'] if m['correction'] else 'none'}",
           "",
           "SETTLEMENT STATUS",
           f"  {s['status']}",
           f"  {s['said']}"]
    return out


def _flag(v) -> str:
    return "not recorded" if v is None else "yes" if v else "no"


# ---- who approved, when a Squads vault funded -----------------------------------------------------------------------------
def squads_approval(account, keys, vault: str, squads: str) -> dict | None:
    """The approval behind an order a Squads vault funded, read from the chain: {multisig, vault, threshold, members,
    time_lock, proposal, approved}. `account(address)` -> (owner, data) or None; `keys`: the accounts of the funding
    transaction (a Squads execution names its multisig and its proposal among them). None when no account among them is
    a Squads multisig whose vault is `vault`: the wallet is then an ordinary one, as far as the chain shows. `approved`
    is None when the proposal's account has been closed since: the members who approved are then no longer on chain."""
    from solders.pubkey import Pubkey

    from . import mainnet_check as mc
    program = Pubkey.from_string(squads)
    for address in dict.fromkeys(str(k) for k in keys):
        got = account(address)
        ms = mc.read_multisig(got[1]) if got and got[0] == squads else None
        if ms is None:
            continue
        key = Pubkey.from_string(address)
        vaults = [str(Pubkey.find_program_address([b"multisig", bytes(key), b"vault", bytes([n])], program)[0]) for n in range(4)]
        if vault not in vaults:
            continue
        out = {"multisig": address, "vault": vault, "threshold": ms.threshold, "members": [str(m) for m in ms.members], "time_lock": ms.time_lock,
               "proposal": None, "approved": None}
        for other in dict.fromkeys(str(k) for k in keys):
            data = bytes((account(other) or (None, b""))[1] or b"") if other != address else b""
            p = mc.read_proposal(data)
            if p is None or data[8:40] != bytes(key):
                continue
            at = 49 + (0 if data[48] == 4 else 8) + 1
            count = int.from_bytes(data[at:at + 4], "little")
            out.update(proposal=p.index, approved=[str(Pubkey.from_bytes(data[at + 4 + 32 * n:at + 36 + 32 * n])) for n in range(count)])
            break
        return out
    return None


# ---- the supplier's side ---------------------------------------------------------------------------------------------------
NOT_VISIBLE = ("What a supplier cannot see without the buyer:",
               "  the evidence of a private order: the repository, the issue, the check names and the terms' text (the chain has a hash only);",
               "  the run logs and the pull request of a private repository, once the buyer takes the supplier's access away;",
               "  the buyer's own reference for a line (a purchase order, an invoice line): it is in the buyer's refs file, not on chain;",
               "  a payment the buyer made outside Knos: the chain cannot show it.",
               "What stays with the supplier whatever the buyer does: every line above, the transactions it names, and the acceptance receipt of "
               "each payment (`knos receipt mirror` keeps a copy that verifies from the issuer's signature with no chain).")


def all_lines(events: list[dict], last: str = "") -> list[dict]:
    """Every line of every work order and bounty of the second escrow, whoever funded it, numbered in time order:
    what `owed` and `knos audit show` read when no owner is named. Not a statement: it has no scope and no head."""
    if last:
        end = records.day_of(last, "--to")
        events = [ev for ev in events if records._day(ev["at"]) <= end]
    facts = _facts(events)
    out: list[dict] = []
    for o in records.orders_of(events)[0]:
        if o["v"] == 2:
            out += _order_lines(o, facts.get((o["address"], o["tx"])) or {"judge": {}, "warranty": {}})
    for j in records.jobs_of(events)[0]:
        if j["v"] == 2:
            out += _bounty_lines(j, events)
    out.sort(key=lambda r: (r["time"], r["order"], r["funded_transaction"], KINDS.index(r["kind"]), r["transaction"]))
    return [{**r, "seq": n, "prev": ""} for n, r in enumerate(out, 1)]


def owed(events: list[dict], payee_id: int, last: str = "", refs: dict | None = None) -> list[dict]:
    """What the escrow's own lines say is owed to one supplier and not paid yet, and what was taken back, oldest
    first. Made from the chain's records alone: no owner is named and no repository is read, so a supplier gets it
    with no access to anything of the buyer's. One row per line:

        reason       held for a wallet | in a review window | reverted | disputed (a refs file says so, and which
                     deliverable: the chain has no line for an open dispute)
        units        what is owed (or, for `reverted`, what went back to the funder)
        until        when the hold or the review window ends (empty when the log does not say)
        deliverable, line, record, funder, evidence (a link to the transaction)

    `line` is the row's place in THIS list of the supplier's lines; `transaction` is what both parties can name."""
    mine = all_lines(events, last)
    out = []
    for rows in deliverables(mine).values():
        who = {i for r in rows for i in r["supplier_ids"].split(";") if i}
        if str(int(payee_id)) not in who:
            continue
        lastrow, cur = rows[-1], rows[0]["currency"]
        still = int(lastrow["held_units"] or 0)

        def row(reason: str, units: int, r: dict, said: str) -> dict:
            return {"reason": reason, "units": units, "amount": _money(units, cur), "currency": cur, "until": r["held_until"], "date": r["date"],
                    "deliverable": deliverable_of(rows[0]), "record": r["record"], "funder": r["funder"], "transaction": r["transaction"],
                    "evidence": EXPLORER.format(r["transaction"]) if r["transaction"] else "", "said": said}
        if lastrow["kind"] == "held":
            out.append(row("held for a wallet", still, lastrow, "Accepted. Name a wallet (`knos claim <address>`), then anyone can settle it."))
        elif lastrow["kind"] in ("paid", "released") and still:
            # a holdback is the order's, not one payee's: with several payees the log does not say whose share it is
            out.append(row("in a review window", still, lastrow, "Accepted and partly paid. The rest is held back until the review window ends; "
                           "a revert inside it sends the rest back to the funder." + (" Shared between the order's payees." if len(who) > 1 else "")))
        elif lastrow["kind"] == "reverted":
            out.append(row("reverted", int(lastrow["reverted_units"] or 0), lastrow, "Reverted inside the review window: this part went back to the "
                           "funder and is not owed. What was already paid stays paid."))
        said = (ref_of(refs, deliverable_of(rows[0])) or {}).get("dispute")
        if said:
            out.append(row("disputed", int(lastrow["price_units"] or 0), lastrow, f"The refs file says: {said}"))
    out.sort(key=lambda r: (r["date"], r["deliverable"]))
    return [{**r, "line": n} for n, r in enumerate(out, 1)]


def owed_lines(rows: list[dict], payee: str) -> list[str]:
    said = [f"Owed to {payee}, from the escrow's own records on devnet (test USDC; nothing here is real money):"]
    if not rows:
        said.append("  Nothing is held for this account, in a review window or reverted in the history that was read.")
    for r in rows:
        said += [f"  {r['line']}. {r['reason']}{' until ' + r['until'] if r['until'] else ''}: {_units(r['units'], r['currency'])} ({r['record']}, funded by {r['funder']})",
                 f"     {r['said']}", f"     deliverable {r['deliverable']}", f"     evidence {r['evidence']}"]
    disputed = "  A dispute is not a line on chain. An arbiter's ruling is (`knos audit show`); an open dispute is whatever the parties' refs files say."
    return [*said, disputed, "", *NOT_VISIBLE]


# ---- reading only what one owner's lines need -------------------------------------------------------------------------
# Every line of the file comes from the second escrow, and only from the transactions that touched one of the owner's
# Balances (or a wallet named with --wallet) or one of the orders and bounties funded from them. Reading those, and not
# the escrow's newest 1,000 transactions (and the first escrow's and the meter's, which no line uses), is what makes an
# export take seconds: the public devnet endpoint answers at most 40 calls of one method per 10 s
# (https://solana.com/docs/references/clusters), so 1,000 transactions alone take over 4 minutes.
WORKERS = 4                     # transactions asked for at once; chain.call backs off on a 429


def _blocks(url: str, sigs: list[dict], workers: int = WORKERS) -> dict[str, list[dict]]:
    """{signature: its events (knos.records.events_of)} for each signature; a transaction the cluster would not give
    is left out (the caller counts it unread)."""
    from concurrent.futures import ThreadPoolExecutor

    from . import chain

    def one(sig: str):
        try:
            return sig, records.events_of(chain.call(url, "getTransaction", [sig, {"encoding": "json", "commitment": "confirmed",
                                                                                   "maxSupportedTransactionVersion": 1}], timeout=30))
        except Exception:  # noqa: BLE001 - still throttled after the backoff: counted, never guessed
            return sig, None
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return {sig: got for sig, got in pool.map(one, [s["signature"] for s in sigs]) if got is not None}


def owner_history(url: str, owner_id: int, wallets=(), limit: int = 1000, last: str = "", workers: int = WORKERS) -> records.Record | None:
    """The second escrow's events that one owner's lines can name, as knos.records.Record: the owner's Balances (found
    with one getProgramAccounts by the owner id they hold), the wallets in `wallets`, and every order or bounty funded
    from them, each address's own history up to `limit` transactions. Transactions after the day `last` are not read.
    None when the cluster will not list the Balances (the caller then reads the whole escrow)."""
    from solders.pubkey import Pubkey

    from . import chain
    try:
        found = chain.call(url, "getProgramAccounts", [str(pay2.PAY_ID), {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}, "filters": [
            {"dataSize": pay2.BALANCE_LEN}, {"memcmp": {"offset": 8, "bytes": chain.b58(int(owner_id).to_bytes(8, "little"))}}]}], timeout=30)
    except Exception:  # noqa: BLE001 - an endpoint that does not list program accounts: read the whole escrow instead
        return None
    sources = sorted({str(a["pubkey"]) for a in found or []} | {str(w) for w in wallets})
    end = calendar.timegm(time.strptime(records.day_of(last, "--to"), "%Y-%m-%d")) + 86_400 if last else None
    todo, asked, cut = list(sources), set(), False
    sigs: dict[str, dict] = {}
    while todo:
        address = todo.pop(0)
        if address in asked:
            continue
        asked.add(address)
        got = chain.call(url, "getSignaturesForAddress", [address, {"limit": limit}], timeout=30) or []
        cut = cut or len(got) >= limit
        fresh = [s for s in got if s.get("err") is None and s["signature"] not in sigs and (end is None or int(s.get("blockTime") or 0) < end)]
        sigs.update({s["signature"]: s for s in fresh})
        for sig, evs in _blocks(url, fresh, workers).items():
            sigs[sig]["events"] = evs
            for ev in evs:
                if ev.get("v") != 2:
                    continue
                if str(ev.get("order") or "") and str(ev["event"]).startswith("order_"):
                    todo.append(str(ev["order"]))
                elif ev["event"] == "funded" and "repo" in ev and "issue" in ev:
                    for src in sources:
                        if src in ev.get("keys", ()):
                            todo.append(str(pay2.job_pda(int(ev["repo"]), int(ev["issue"]), Pubkey.from_string(src))))
    read = sorted((s for s in sigs.values() if "events" in s), key=lambda s: (int(s.get("blockTime") or 0), int(s.get("slot") or 0)))
    events = [{**ev, "tx": s["signature"]} for s in read for ev in s["events"]]
    return records.Record(events, len(sigs) - len(read), (2,) if cut else (), limit)


def escrow_history(url: str, limit: int = 1000, last: str = "", workers: int = WORKERS) -> records.Record:
    """The second escrow's newest `limit` transactions (up to the day `last`), several at a time: what an export reads
    when the cluster will not list an owner's Balances."""
    from . import chain
    got = chain.call(url, "getSignaturesForAddress", [str(pay2.PAY_ID), {"limit": limit}], timeout=30) or []
    end = calendar.timegm(time.strptime(records.day_of(last, "--to"), "%Y-%m-%d")) + 86_400 if last else None
    sigs = [s for s in reversed(got) if s.get("err") is None and (end is None or int(s.get("blockTime") or 0) < end)]
    blocks = _blocks(url, sigs, workers)
    events = [{**ev, "tx": s["signature"]} for s in sigs if s["signature"] in blocks for ev in blocks[s["signature"]]]
    events.sort(key=lambda ev: ev["at"])
    return records.Record(events, len(sigs) - len(blocks), (2,) if len(got) >= limit else (), limit)


def history_for(owner_id: int, wallets=(), limit: int = 1000, last: str = "") -> records.Record:
    """What `knos audit export` reads: the owner's own part of the escrow, else the escrow's newest `limit`."""
    from . import chain, cli, ghwords
    if limit < 1:
        raise cli.Stop("--limit is a number of transactions, at least 1.")
    url = cli._ledger().url
    try:
        got = owner_history(url, owner_id, wallets, min(limit, 1000), last) or escrow_history(url, min(limit, 1000), last)
    except (chain.Refused, OSError, ValueError) as why:
        raise cli.Stop(f"Solana did not give the escrow's history: {ghwords.first_line(why)}.") from None
    for note in got.notes():
        cli.err.print(note, markup=False)
    return got


# ---- the command line ---------------------------------------------------------------------------------------------------

def register(app, help_lines: list | None = None) -> None:
    """`knos audit export | verify | show | owed`, on the main app. `help_lines`: cli._HELP, which gets the group's line."""
    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    audit_app = typer.Typer(add_completion=False, no_args_is_help=True,
                            help="Everything an organisation's money paid for as a hash-chained file, its check, one deliverable as four records, and what a supplier is owed.")
    app.add_typer(audit_app, name="audit")
    if help_lines is not None:
        help_lines.append(("audit", "For money", "An organisation's orders and bounties as a hash-chained file or a finance system's import; `audit show`, `owed`, `verify`."))

    def refs_of(path) -> dict | None:
        from . import cli
        if not path:
            return None
        try:
            return read_refs(Path(path).read_text(encoding="utf-8"))
        except OSError as why:
            raise cli.Stop(f"Could not read {path}: {why}.") from None
        except Refused as why:
            raise cli.Stop(str(why)) from None

    @audit_app.command("export")
    def export_(owner: str = typer.Option(..., "--owner", help="the GitHub login or id of the organisation whose money paid"),
                first: str = typer.Option("", "--from", help="first UTC day, like 2026-09-01"),
                last: str = typer.Option("", "--to", help="last UTC day, like 2026-09-30 (inclusive). Name it: a file with an end is the same whoever exports it"),
                fmt: str = typer.Option("csv", "--format", help="csv or json (the statement), or a finance system's import: netsuite, sap, coupa, quickbooks, generic"),
                wallet: list[str] = typer.Option([], "--wallet", help="also the orders this wallet funded itself (repeat for several)"),
                limit: int = typer.Option(1000, "--limit", help="how many transactions to read for each of the owner's balances, orders and bounties (at most 1000)"),
                partial: bool = typer.Option(False, "--partial", help="write the file even when the cluster did not give the whole history; it then says so"),
                refs: Path = typer.Option(None, "--refs", help="a CSV of your own references: order,ref,paid_outside,dispute (for the finance formats)"),
                account: str = typer.Option("", "--account", help="finance formats: the expense or general-ledger account every line is booked to"),
                entity: str = typer.Option("", "--entity", help="finance formats: SAP's company code, Coupa's chart of accounts"),
                tax_code: str = typer.Option("", "--tax-code", help="finance formats: the tax code of every line (QuickBooks, SAP)"),
                date_format: str = typer.Option("", "--date-format", help="finance formats: another date format, like DD/MM/YYYY or M/D/YYYY"),
                to_file: Path = typer.Option(None, "--out", help="write the file here instead of printing it"),
                events_log: Path = typer.Option(None, "--events", help="also take the paid lines into this log of events (`knos events`); default: the file KNOS_EVENTS names, else none")) -> None:
        """Export everything an organisation's money paid for, one line per payment, refund, revert or open order. Each
        line says what was bought, the price, the terms' hash, who supplied it, the verdict, the fee and the
        transaction. Each row carries the hash of the row before it, so two exports of the same period are
        byte-identical. With --format netsuite, sap, coupa, quickbooks or generic, it writes one line per
        accepted deliverable in that system's import format. Devnet: test USDC."""
        from . import cli, exports
        if fmt not in ("csv", "json", *exports.FORMATS):
            raise cli.Stop(f"--format is csv or json, or {', '.join(exports.FORMATS)}; {fmt!r} is none of them.")
        mine = refs_of(refs)
        a, b = cli._days(first, last)
        owner_id = cli._owner(owner)
        got = history_for(owner_id, wallet, limit, b)
        short = bool(got.unread or 2 in got.cut)        # the second escrow's history is the one a work order is in
        if short and not partial:
            raise cli.Stop("The cluster did not give the escrow's whole history (see above), so the file would not be the one another party gets.",
                           "Run it again, or with --partial for a file that says it is partial.")
        scope = scope_of(owner_id, a, b, wallet, short)
        rows, head = chained(lines(got.events, scope["owner_id"], wallet, a, b), scope)
        if fmt in exports.FORMATS:
            text = exports.write(fmt, scope, rows, head, mine, {"account": account, "entity": entity, "tax_code": tax_code, "date_format": date_format})
            f = exports.FORMATS[fmt]
            cli.err.print(f"{f['name']}. Columns from {f['source']}." + (f" Not confirmed there: {f['unverified']}." if f["unverified"] else ""), markup=False)
        else:
            text = write(scope, rows, head, fmt)
        if to_file:
            to_file.write_text(text, encoding="utf-8", newline="")
            if fmt in exports.FORMATS:      # the five parts of every bill, in a file beside it that names this export by its sha256
                exports.parts_path(to_file).write_text(exports.parts_file(exports.parts_rows(scope, rows, head, mine), exports.sha_of(text)),
                                                       encoding="utf-8", newline="")
        else:
            sys.stdout.write(text)
        cli.err.print(f"{len(rows)} line(s) for GitHub id {scope['owner_id']}. Head: {head}" + (" (partial: not a head to compare)" if short else ""), markup=False)
        from . import events
        events.keep(events.where(events_log), lambda: events.from_audit(rows))      # best effort: the export is written whatever the log says

    @audit_app.command("verify")
    def verify_(path: str = typer.Argument(..., help="an audit export (CSV or JSON) or a generic finance export; - reads standard input")) -> None:
        """Check an audit export: every row's hash, the totals and the head. An edited, removed, added or reordered row is found. A file of version 1 is checked by version 1's columns. To check it against the chain, export the same period yourself and compare the heads."""
        from . import cli, exports
        try:
            text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
            if text.startswith(exports.TYPE + ","):
                text = exports.statement_of(text)
            said = verify(text)
            scope, _rows, _sums, head, _n = parse(text)
        except OSError as why:
            raise cli.Stop(f"Could not read {path}: {why}.") from None
        except Refused as why:
            raise cli.Stop(str(why)) from None
        if said:
            for s in said:
                typer.echo(s)
            raise typer.Exit(1)
        typer.echo(f"valid. version {scope['version']}. head sha256:{head}")

    @audit_app.command("show")
    def show_(order: str = typer.Argument(..., help="an order's or a bounty's address, or a deliverable (order:funded transaction:milestone)"),
              refs: Path = typer.Option(None, "--refs", help="a CSV of your own references: order,ref,paid_outside,dispute"),
              limit: int = typer.Option(1000, "--limit", help="how many of the escrow's newest transactions to read (at most 1000)"),
              offline: bool = typer.Option(False, "--chain-lines-only", help="do not rebuild the acceptance receipt or read a multisig: the log lines alone"),
              as_json: bool = typer.Option(False, "--json", help="the records as JSON")) -> None:
        """One deliverable as four linked records: who authorised it and under which budget, why it was accepted, what it is as a billable line, and where its money is. Read from the chain; your references come from --refs."""
        from . import cli
        mine = refs_of(refs)
        got = cli._history(limit)
        rows = [r for r in all_lines(got.events) if order in (r["order"], deliverable_of(r))]
        if not rows:
            raise cli.Stop(f"The escrow's history that was read shows no order, bounty or deliverable {order}.",
                           "Name an order's address as `knos audit export` prints it, or read further back with --limit.")
        receipts: dict = {}
        approvals: dict = {}
        notes: list[str] = []
        if not offline:
            receipts, approvals, notes = _beside(cli._ledger().url, got.events, rows)
        found = records_of(rows, mine, receipts, approvals)
        if as_json:
            typer.echo(json.dumps(found, sort_keys=True, indent=1))
            return
        for n, rec in enumerate(found):
            typer.echo(("\n" if n else "") + "\n".join(record_lines(rec)))
        for note in notes:
            cli.err.print(note, markup=False)

    def owed_(payee: str = typer.Option(..., "--payee", help="the supplier's GitHub login or id"),
              last: str = typer.Option("", "--to", help="as of the end of this UTC day (default: now)"),
              refs: Path = typer.Option(None, "--refs", help="a CSV of references and disputes: order,ref,paid_outside,dispute"),
              limit: int = typer.Option(1000, "--limit", help="how many of the escrow's newest transactions to read (at most 1000)"),
              as_json: bool = typer.Option(False, "--json", help="the lines as JSON")) -> None:
        """What is owed to a supplier and why it is not paid yet: held for a wallet, in a review window until a date, reverted, or disputed, with the transaction as evidence for each line. Read from the chain's records alone: it needs no access to the buyer's repository."""
        from . import cli
        mine = refs_of(refs)
        _a, b = cli._days("", last)
        got = cli._history(limit)
        rows = owed(got.events, cli._owner(payee), b, mine)
        typer.echo(json.dumps(rows, sort_keys=True, indent=1) if as_json else "\n".join(owed_lines(rows, payee)))
    audit_app.command("owed")(owed_)


def _beside(url: str, events: list[dict], rows: list[dict]) -> tuple[dict, dict, list[str]]:
    """What the log lines do not carry, read from the cluster for the rows of one order: ({paying transaction: receipt},
    {funding transaction: Squads approval}, notes on what could not be read). Nothing here raises."""
    from . import bundle, chain, ghwords
    from . import mainnet_check as mc
    from .settle import v2
    receipts: dict = {}
    approvals: dict = {}
    notes: list[str] = []
    call = lambda method, params: chain.call(url, method, params, timeout=30)       # noqa: E731
    for r in rows:
        if r["kind"] == "paid" and r["record"] == "order" and r["transaction"] not in receipts:
            try:
                receipts[r["transaction"]] = bundle.gather(call, events, r["transaction"], None)[0]
            except Exception as why:  # noqa: BLE001 - a record without its receipt says so and is still a record
                notes.append(f"The acceptance receipt of {r['transaction']} was not rebuilt ({ghwords.first_line(why)}): its limits and evaluators are not shown.")
    first = rows[0]
    if first["funder"].startswith("wallet:"):
        funded = next((ev for ev in events if ev.get("tx") == first["funded_transaction"] and ev["event"] in ("order_funded", "funded")), None)
        try:
            found = squads_approval(mc._rpc(url), (funded or {}).get("keys", ()), first["funder"][7:], str(v2.load_ids()["squads_program"]))
            if found:
                approvals[first["funded_transaction"]] = found
        except Exception as why:  # noqa: BLE001
            notes.append(f"Whether a multisig funded this could not be read ({ghwords.first_line(why)}).")
    return receipts, approvals, notes
