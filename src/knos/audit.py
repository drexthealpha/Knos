"""The audit export: every work order of one organisation, for the person who approves the invoice.

`knos audit export --owner <org> [--from --to] --format csv|json` and `knos audit verify <file>`.

Everything is recomputed from the second escrow's own log lines (knos.records: `events_of`, `orders_of`), never from a
database and never from an account's state today. So the file is a function of the chain and the period alone: two
parties who export the same owner and the same period get the same bytes, and compare one hash (the head) instead of
the file. Nothing is asked of GitHub: accounts and repositories are their numeric ids.

One row is one LINE of an order: a payment (one paying transaction, all its payees), a holdback released after its
warranty, a kill fee, a refund, a revert, or `open` / `held` for an order nothing has happened to by the end of the
period. Events after the last day (`--to`) are not read at all: the file says what was true at the end of that day.

    seq, date, time           the line's number in this file, and the UTC day and time of its transaction
    kind                      paid, released, kill, refunded, reverted, open, held
    order                     the order's address; funded_transaction says which funding of that address (an address
                              is used again once an order is closed)
    owner_id, funder          the Balance's owner (0: none), and gh:<id> or wallet:<address>; commenter_id: who funded by comment
    repository_id, issue      what was commissioned (0 and 0 for a private order: its line on chain names neither)
    private, standing, mode   1 or 0; 1 or 0 (a standing offer pays once per pull request); merge or tests
    price_units, price        what the order holds for its payees; funder_fee_units: what its funder put in on top
    currency                  "test USDC" (devnet money, never real), or `mint <address>`
    terms_hash                sha256 of the terms JSON the funding logged: the policy the order was accepted under
                              (empty for a private order: its terms are a hash in the order account, not in a log line)
    pull_request, artifact    the pull request the paying line names, and the artifact as the log gives it:
                              `pull:<repository id>#<number>`, and `commit:<sha>` on a revert (the only line that prints one)
    supplier_ids, wallets     who supplied: every GitHub id paid in this transaction, and where (`;` between several)
    judge, evaluator          who evaluated: the rule of the program that accepted the signed token (JUDGES)
    verdict                   accepted, pending, expired (no accepted work by the deadline), reverted, none (a kill fee)
    paid_units, paid          what reached the suppliers in this line
    held_units                what the order still holds after this line (a holdback in warranty; an order held for a wallet)
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

import csv
import hashlib
import io
import json
import sys
from pathlib import Path

from . import records
from .settle.v2 import pay as pay2

TYPE, VERSION = "knos.audit-export", 1
COLUMNS = ("seq", "date", "time", "kind", "order", "funded_transaction", "owner_id", "funder", "commenter_id", "repository_id", "issue",
           "private", "standing", "mode", "price_units", "price", "funder_fee_units", "currency", "terms_hash", "pull_request", "artifact",
           "supplier_ids", "wallets", "judge", "evaluator", "verdict", "paid_units", "paid", "held_units", "refunded_units", "reverted_units",
           "fee_units", "fee", "transaction", "billing_key", "billed_before", "exception", "resolved_by", "prev")
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
        elif name in ("order_refunded", "order_reverted", "order_cancelled", "order_held"):
            f.setdefault(name[6:], ev)
    return out


def _mine(o: dict, owner_id: int, wallets: frozenset) -> bool:
    return (o["owner"] or o["by"]) == owner_id if o["from_balance"] else o["source"] in wallets


def lines(events: list[dict], owner_id: int, wallets=(), first: str = "", last: str = "") -> list[dict]:
    """Every line of `owner_id`'s work orders, in the file's order, without `seq` and `prev`. An order is the owner's
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
    out = [r for r in out if r["kind"] in _STATE or ((not first or r["date"] >= first) and (not last or r["date"] <= last))]
    out.sort(key=lambda r: (r["time"], r["order"], r["funded_transaction"], KINDS.index(r["kind"]), r["transaction"]))
    seen: set[str] = set()
    for r in out:       # a second line can never bill the same order and milestone: said per line, and checked by `verify`
        r["billed_before"] = int(bool(r["billing_key"]) and r["billing_key"] in seen)
        seen.add(r["billing_key"])
    return out


def _order_lines(o: dict, f: dict) -> list[dict]:
    cur = records._currency(o)
    text = records.units_text if cur == records.TEST else (lambda n: "")
    terms = o.get("terms")
    cancelled = f.get("cancelled")
    base = {"order": o["address"], "funded_transaction": o["tx"] or "", "owner_id": o["owner"], "funder": o["funder"], "commenter_id": o["by"],
            "repository_id": o["repo"] or 0, "issue": o["issue"] or 0, "private": int(o["private"]), "standing": int(o["standing"]),
            "mode": "tests" if o["mode"] else "merge", "price_units": o["amount"], "price": text(o["amount"]), "funder_fee_units": o["fee_escrowed"],
            "currency": cur, "terms_hash": pay2.terms_hash(terms.encode()).hex() if terms else ""}

    def line(kind: str, at: int, tx, verdict: str, *, pr=None, ids=(), tos=(), judge: int | None = None, paid: int = 0, held: int = 0,
             refunded: int = 0, reverted: int = 0, fee: int = 0, artifact: str = "", exception: tuple = (), resolved: tuple = ()) -> dict:
        if cancelled:       # every line of a cancelled order says so
            exception = (*exception, f"cancelled on {records._day(cancelled['at'])} ({cancelled.get('tx') or ''})")
            resolved = (*resolved, "cancel: the funding wallet's signature, or a command token of the funder or the Balance's owner")
        kind_, who = JUDGES.get(judge, ("", "")) if judge is not None else ("", "")
        billing = f"{o['address']}:{o['tx'] or ''}:{(pr or 0) if o['standing'] else 0}" if kind == "paid" else ""
        return {**base, "date": records._day(at), "time": records._stamp(at), "kind": kind, "pull_request": "" if pr is None else pr,
                "artifact": artifact or (f"pull:{o['repo'] or 0}#{pr}" if pr else ""), "supplier_ids": ";".join(str(i) for i in ids),
                "wallets": ";".join(t for t in tos if t), "judge": kind_, "evaluator": who, "verdict": verdict, "paid_units": paid, "paid": text(paid),
                "held_units": held, "refunded_units": refunded, "reverted_units": reverted, "fee_units": fee, "fee": text(fee),
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
                        held=f["warranty"].get(tx, 0), fee=sum(p["fee"] for p in rows), exception=exc, resolved=res))
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
        out.append(line("held", h["at"], h.get("tx"), "accepted", pr=h.get("pr") or None, ids=[h.get("payee", 0)], held=o["amount"] - o["net"],
                        exception=("held: the payee has bound no wallet",), resolved=("the payee binds a wallet, then anyone settles",)))
    elif o["state"] == "open" and not out:
        out.append(line("open", o["at"], o["tx"], "pending", held=o["amount"]))
    return out


# ---- the hash chain ----------------------------------------------------------------------------------------------------

def _hash(doc: dict) -> str:
    return hashlib.sha256(json.dumps({k: _text(v) for k, v in doc.items()}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _text(value) -> str:
    return "" if value is None else str(int(value)) if isinstance(value, bool) else str(value)


def scope_of(owner_id: int, first: str = "", last: str = "", wallets=(), partial: bool = False) -> dict:
    """What a file is an export OF. Its hash is the first row's `prev`, so a row cannot be moved to another export."""
    return {"type": TYPE, "version": VERSION, "program": str(pay2.PAY_ID), "owner_id": int(owner_id), "from": first, "to": last,
            "wallets": ";".join(sorted(str(w) for w in wallets)), "partial": int(partial)}


def chained(rows: list[dict], scope: dict) -> tuple[list[dict], str]:
    """(the rows with `seq` and `prev`, the head). The head of an empty export is the hash of its scope."""
    prev, out = _hash(scope), []
    for n, r in enumerate(rows, 1):
        row = {c: {**r, "seq": n, "prev": prev}[c] for c in COLUMNS}
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
    sums = totals(rows)
    if fmt == "json":
        return json.dumps({"scope": scope, "columns": list(COLUMNS), "rows": rows, "totals": sums, "head": head, "rows_count": len(rows)},
                          sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    if fmt != "csv":
        raise Refused(f"--format is csv or json; {fmt!r} is neither.")
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\n")
    out.writerow(COLUMNS)
    for r in rows:
        out.writerow([records._cell(_text(r[c])) for c in COLUMNS])
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
            return d["scope"], [{c: _text(r[c]) for c in COLUMNS} for r in d["rows"]], d["totals"], str(d["head"]), int(d["rows_count"])
        except (ValueError, KeyError, TypeError) as why:
            raise Refused(f"This is not an audit export: {type(why).__name__}: {why}. Export it again with `knos audit export`.") from None
    got = list(csv.reader(io.StringIO(text)))
    if not got or tuple(got[0]) != COLUMNS:
        raise Refused("This is not an audit export: its first line is not the columns of one. Export it again with `knos audit export`.")
    rows, sums, head, count, scope = [], {}, "", -1, None
    for cells in got[1:]:
        if cells[:1] == ["total"] and len(cells) == 3 + len(SUMS):
            sums[cells[1]] = {"lines": int(cells[2]), **{c: int(v) for c, v in zip(SUMS, cells[3:])}}
        elif cells[:1] == ["head"] and len(cells) == 4:
            head, count, scope = cells[1], int(cells[2]), json.loads(cells[3])
        elif len(cells) == len(COLUMNS) and not sums and scope is None:
            rows.append({c: (v[1:] if v[:1] == "'" else v) for c, v in zip(COLUMNS, cells)})
        else:
            raise Refused(f"This is not an audit export: line {len(rows) + 2} is not a row, a total or the head.")
    if scope is None:
        raise Refused("This audit export has no last line (`head`): it was cut short. Export it again.")
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


# ---- the command line ---------------------------------------------------------------------------------------------------

def register(app, help_lines: list | None = None) -> None:
    """`knos audit export` and `knos audit verify`, on the main app. `help_lines`: cli._HELP, which gets the group's line."""
    import typer

    audit_app = typer.Typer(add_completion=False, no_args_is_help=True, help="Every work order of an organisation as a hash-chained file, and its check.")
    app.add_typer(audit_app, name="audit")
    if help_lines is not None:
        help_lines.append(("audit", "For money", "Every order of an organisation as a hash-chained CSV or JSON; `audit verify` checks one."))

    @audit_app.command("export")
    def export_(owner: str = typer.Option(..., "--owner", help="the GitHub login or id of the organisation whose money paid"),
                first: str = typer.Option("", "--from", help="first UTC day, like 2026-09-01"),
                last: str = typer.Option("", "--to", help="last UTC day, like 2026-09-30 (inclusive). Name it: a file with an end is the same whoever exports it"),
                fmt: str = typer.Option("csv", "--format", help="csv or json"),
                wallet: list[str] = typer.Option([], "--wallet", help="also the orders this wallet funded itself (repeat for several)"),
                limit: int = typer.Option(1000, "--limit", help="how many of the escrow's newest transactions to read (at most 1000)"),
                partial: bool = typer.Option(False, "--partial", help="write the file even when the cluster did not give the whole history; it then says so"),
                to_file: Path = typer.Option(None, "--out", help="write the file here instead of printing it")) -> None:
        """Every work order of an organisation, one line per payment, refund, revert or open order: what was commissioned, the price, the terms' hash, the artifact, who supplied, which rule evaluated, the verdict, what was paid, held, refunded and reverted, the fee and the transaction. Each row carries the hash of the row before and the file ends with the totals and the head, so two exports of the same period are the same bytes. Devnet: test USDC."""
        from . import cli
        if fmt not in ("csv", "json"):
            raise cli.Stop(f"--format is csv or json; {fmt!r} is neither.")
        a, b = cli._days(first, last)
        got = cli._history(limit)
        short = bool(got.unread or 2 in got.cut)        # the second escrow's history is the one a work order is in
        if short and not partial:
            raise cli.Stop("The cluster did not give the escrow's whole history (see above), so the file would not be the one another party gets.",
                           "Run it again, or with --partial for a file that says it is partial.")
        text = export(got.events, cli._owner(owner), fmt, a, b, wallet, short)
        if to_file:
            to_file.write_text(text, encoding="utf-8", newline="")
        else:
            sys.stdout.write(text)
        scope, rows, _sums, head, _n = parse(text)
        cli.err.print(f"{len(rows)} line(s) for GitHub id {scope['owner_id']}. Head: {head}" + (" (partial: not a head to compare)" if short else ""), markup=False)

    @audit_app.command("verify")
    def verify_(path: str = typer.Argument(..., help="an audit export (CSV or JSON); - reads standard input")) -> None:
        """Check an audit export: every row's hash, the totals and the head. An edited, removed, added or reordered row is found. To check it against the chain, export the same period yourself and compare the heads."""
        from . import cli
        try:
            text = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
            said = verify(text)
            head = parse(text)[3]
        except OSError as why:
            raise cli.Stop(f"Could not read {path}: {why}.") from None
        except Refused as why:
            raise cli.Stop(str(why)) from None
        if said:
            for s in said:
                typer.echo(s)
            raise typer.Exit(1)
        typer.echo(f"valid. head sha256:{head}")

