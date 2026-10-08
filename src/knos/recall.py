"""`knos recall exception`: how the same exception under the same terms ended before, answered from the memory engine.

    knos recall exception --buyer ORG --terms HASH --reason CODE [--supplier ID] [--memory DIR] [--json]

An exception is a statement line, an appeal or a correction that was not simply agreed. The answer says how often the
same one (the same reason, under the terms with the same hash, for one supplier or for all) was seen, how each ended
(accepted on appeal, corrected and passed, refused), how long it took and which evidence ids stand behind it.

Everything it says is read from the memory engine through knos.proof.history, and nothing is kept anywhere else: no
side file, no cache. Each buyer organisation has a tenant of its own (knos.store.buyer_tenant). With no memory
(history.NullStore) the answer is the empty one: seen 0 times.

    exception(store, terms, reason, supplier)   the answer, as the row the approver's exception queue draws
                                                (web/recall.js `renderRecall(el, rows)`): SCHEMA below
    queue(store)                                one row for every exception open now, each with its recall
    words(row)                                  the row in one plain sentence

    appeal_moved(store, appeal)                 the hooks: what knos.appeal, knos.statement and knos.ledger call when
    line_opened / line_resolved                 an appeal moves, a statement line is set aside or ends, and a correction
    correction_made                             is written. Each writes through knos.proof.history.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .proof import history

SCHEMA = "knos.recall/1"
ENDING_WORDS = {"accepted_on_appeal": "accepted on appeal", "corrected_and_passed": "corrected and passed", "refused": "refused"}
# how an appeal's state (knos.appeal) and a correction's kind (knos.ledger) end an exception
_APPEAL_ENDS = {"accepted": "accepted_on_appeal", "rejected": "refused"}


def took(seconds: float | None) -> str:
    """A length of time in plain words: "40 s", "12 min", "5 h", "3 days". Empty for None."""
    if seconds is None:
        return ""
    for size, unit in ((86400, "day"), (3600, "h"), (60, "min")):
        if seconds >= size:
            n = int(seconds // size)
            return f"{n} {unit}{'s' if unit == 'day' and n != 1 else ''}"
    return f"{int(seconds)} s"


def exception(store, terms: str, reason: str, supplier: str | None = None) -> dict:
    """The recall row for one exception (SCHEMA): what knos.proof.history.exceptions_before holds, plus `kind`, the
    endings in words, whether the text of the terms is kept, and `memory` (False when the store keeps nothing)."""
    got = history.exceptions_before(store, terms, reason, supplier)
    try:
        known = bool(history.terms_text(store, terms))
    except ValueError:
        known = False
    row = {"kind": SCHEMA, **got, "terms_text_kept": known, "memory": not isinstance(store, history.NullStore)}
    row["words"] = words(row)
    return row


def words(row: dict) -> str:
    """One recall row in one sentence."""
    if not row.get("seen"):
        return "Not seen before under these terms."
    parts = [f"{n} {ENDING_WORDS[e]}" for e, n in row["endings"].items() if n]
    said = f"Seen {row['seen']} time{'' if row['seen'] == 1 else 's'} under these terms: {', '.join(parts)}."
    if row.get("seconds"):
        said += f" Median time to end: {took(row['seconds']['median'])}."
    return said


def queue(store) -> list[dict]:
    """Every exception open now (the live queue), oldest first, each with what memory says of the same one before:
    [{"id", "opened_at", "evidence", ...the recall row}]. This is what the approver's exception queue draws."""
    return [{**exception(store, r["terms"], r["reason"], r["supplier"]), "id": r["id"], "opened_at": r["at"], "open_evidence": r["evidence"]}
            for r in history.exception_queue(store)]


# ---- the hooks: one call where an exception opens or ends --------------------------------------------------------------

def unnamed_terms(buyer, supplier) -> str:
    """The id an exception is recalled by when no hash of terms is at hand (a statement made from an invoice, a meter
    ledger: neither names terms): a hash of the two parties' names. It stands for "whatever this buyer and this supplier
    agreed", so a recall under it is of the same pair and never of another. A real hash, given with --terms, is used
    instead whenever there is one."""
    return hashlib.sha256(f"knos-recall:unnamed-terms:{buyer}|{supplier}".encode()).hexdigest()


def memory_of(buyer_org: str | None, memory: Path | None = None):
    """The store a command remembers in: one buyer organisation's tenant (--remember ORG [--memory DIR]), or no memory
    (history.NullStore) when no organisation is named or the memory engine is not installed. ValueError: not a name."""
    if not buyer_org:
        return history.NullStore()
    try:
        return history.SibylStore.for_buyer(buyer_org, memory)
    except ImportError:
        return history.NullStore()


# How a settlement recorded on a line that was set aside ends its exception (knos.statement PAY_STATES): the line was
# paid after all, or the money came back. `payable` and `held` end nothing.
_PAY_ENDS = {"paid_outside": "accepted_on_appeal", "devnet_demonstration": "accepted_on_appeal", "refunded": "refused"}


def statement_made(store, statement: dict, terms: str = "", at: float | None = None) -> list[dict]:
    """Every line of a statement that is not agreed goes on the live queue (line_opened), under `terms` or, with none,
    under unnamed_terms(buyer, supplier of the line). Returns what was opened; [] with no memory."""
    if isinstance(store, history.NullStore):
        return []
    out = []
    for ln in statement.get("lines", []):
        got = line_opened(store, terms or unnamed_terms(statement.get("buyer", ""), ln.get("supplier", "")), ln, at)
        if got is not None:
            out.append(got)
    return out


def statement_paid(store, statement: dict, event: dict, terms: str = "", at: float | None = None) -> dict | None:
    """A settlement recorded on a line (knos.statement `pay`): when the line had been set aside and the record says it
    was paid, its exception ends "accepted on appeal"; when it says refunded, "refused". None for an agreed line, a
    state that ends nothing, or no memory."""
    ending = _PAY_ENDS.get(str(event.get("state")))
    ln = next((x for x in statement.get("lines", []) if x.get("invoice_line") == event.get("line")), None)
    if ending is None or ln is None or isinstance(store, history.NullStore):
        return None
    return line_resolved(store, terms or unnamed_terms(statement.get("buyer", ""), ln.get("supplier", "")), ln, ending, at=at,
                         period=str(statement.get("date", ""))[:7].replace("-", ""))


def appeal_moved(store, appeal: dict) -> dict | None:
    """An appeal's record (knos.appeal) as an exception: open or rerun puts it on the live queue; accepted ends it
    "accepted on appeal", rejected ends it "refused". The reason is the verdict that was contested; the evidence is the
    evaluation and the deliverable. None for an appeal with no terms hash: there are no "same terms" to recall it by."""
    terms, state = str(appeal.get("terms_hash") or ""), appeal.get("state")
    if not terms or not appeal.get("supplier"):
        return None
    reason, evidence = str(appeal.get("was") or "rejected"), [appeal.get("evaluation"), appeal.get("deliverable")]
    opened = float(appeal["at"]) if appeal.get("at") is not None else None
    if state in _APPEAL_ENDS:
        last = (appeal.get("history") or [{}])[-1].get("at")
        return history.exception_resolved(store, terms, reason, appeal["supplier"], str(appeal["id"]), _APPEAL_ENDS[state], evidence,
                                          opened_at=opened, at=float(last) if last is not None else None)
    return history.exception_opened(store, terms, reason, appeal["supplier"], str(appeal["id"]), evidence, at=opened)


def _line(line: dict) -> tuple[str, str, str, list]:
    return (str(line.get("state") or ""), str(line.get("supplier") or ""), str(line.get("invoice_line") or ""),
            [line.get("deliverable"), *(line.get("evaluations") or [] if isinstance(line.get("evaluations"), list) else [line.get("evaluations")])])


def line_opened(store, terms: str, line: dict, at: float | None = None) -> dict | None:
    """A statement line (knos.statement) that is not agreed goes on the live queue: its state (disputed, duplicate,
    insufficient_evidence) is the reason, its invoice line id the exception's id. None for an agreed line."""
    state, supplier, eid, evidence = _line(line)
    if state in ("", "agreed") or not supplier or not eid:
        return None
    return history.exception_opened(store, terms, state, supplier, eid, evidence, at=at)


def line_resolved(store, terms: str, line: dict, ending: str, at: float | None = None, opened_at: float | None = None,
                  period: str = "") -> dict | None:
    """The same line, ended: `ending` is one of history.EXCEPTION_ENDINGS. `line` as it stood when it was set aside (its
    state then is the reason). None for a line that was agreed all along."""
    state, supplier, eid, evidence = _line(line)
    if state in ("", "agreed") or not supplier or not eid:
        return None
    return history.exception_resolved(store, terms, state, supplier, eid, ending, evidence, opened_at=opened_at, at=at, period=period)


def correction_made(store, terms: str, supplier: str, evaluation: str, kind: str, accepted: bool | None = None,
                    at: float | None = None, opened_at: float | None = None, period: str = "") -> dict:
    """A correction of one anchored evaluation (knos.ledger `knos meter correct`): the reason is `correction-<kind>`
    (duplicate, verdict, withdrawn). A verdict corrected to accepted ends "corrected and passed"; every other
    correction ends "refused": the evaluation is not billed."""
    ending = "corrected_and_passed" if kind == "verdict" and accepted else "refused"
    return history.exception_resolved(store, terms, f"correction-{kind}", supplier, f"evl_{evaluation}" if not str(evaluation).startswith("evl_") else str(evaluation),
                                      ending, [evaluation], opened_at=opened_at, at=at, period=period)


# ---- the command ------------------------------------------------------------------------------------------------------

def register(app: Any, help_lines: list | None = None) -> None:
    """`knos recall exception`. `help_lines`: cli._HELP, which gets the command's line."""
    import importlib
    typer = importlib.import_module("typer")
    if help_lines is not None:
        help_lines.append(("recall", "For money", "How the same exception under the same terms ended before, from memory."))
    group = typer.Typer(help="What the buyer's memory holds: how the same exception under the same terms ended before.", no_args_is_help=True)
    app.add_typer(group, name="recall", rich_help_panel="For money")

    def _open(buyer: str, memory: Path | None):
        from . import cli
        try:
            return history.SibylStore.for_buyer(buyer, memory)
        except ValueError as why:
            raise cli.Stop(f"No memory was opened: {why}.", "Name the buyer organisation: --buyer acme") from None

    @group.command("exception")
    def exception_(terms: str = typer.Option(..., "--terms", metavar="HASH", help="the hash of the terms, 64 hex characters"),
                   reason: str = typer.Option(..., "--reason", metavar="CODE", help="the reason: a refusal code, a line state (disputed, duplicate, insufficient_evidence) or correction-<kind>"),
                   supplier: str = typer.Option(None, "--supplier", metavar="ID", help="one supplier; default: every supplier under these terms"),
                   buyer: str = typer.Option(..., "--buyer", metavar="ORG", help="the buyer organisation whose memory answers (one tenant each)"),
                   memory: Path = typer.Option(None, "--memory", metavar="DIR", help="the directory of the memory store; default: the memory engine's shared store on this machine"),
                   as_json: bool = typer.Option(False, "--json", help="the row the approver's exception queue reads")) -> None:
        """How the same exception under the same terms ended before: how often, each ending, how long it took, and the evidence ids. Read from the memory engine; nothing is sent anywhere."""
        from . import cli
        try:
            history._exception_key(terms.lower(), reason, supplier or "any")
            row = exception(_open(buyer, memory), terms.lower(), reason, supplier)
        except ValueError as why:
            raise cli.Stop(f"Nothing was recalled: {why}.", "Give --terms as 64 hex characters and --reason as a code, for example disputed.") from None
        if as_json:
            typer.echo(json.dumps(row, indent=1, sort_keys=True))
            return
        typer.echo(row["words"])
        for c in row["cases"]:
            typer.echo(f"  {c['id']}: {ENDING_WORDS[c['ending']]}" + (f" after {took(c['seconds'])}" if c["seconds"] is not None else "")
                       + (f" ({c['supplier']})" if not supplier else "") + (f"; evidence {', '.join(c['evidence'])}" if c["evidence"] else ""))
        if row["open"]:
            typer.echo(f"Open now: {row['open']}.")

    @group.command("queue")
    def queue_(buyer: str = typer.Option(..., "--buyer", metavar="ORG", help="the buyer organisation whose memory answers"),
               memory: Path = typer.Option(None, "--memory", metavar="DIR", help="the directory of the memory store"),
               as_json: bool = typer.Option(False, "--json", help="the rows the approver's exception queue reads")) -> None:
        """Every exception open now, each with how the same one ended before."""
        rows = queue(_open(buyer, memory))
        if as_json:
            typer.echo(json.dumps(rows, indent=1, sort_keys=True))
            return
        if not rows:
            typer.echo("No exception is open.")
        for r in rows:
            typer.echo(f"{r['id']} ({r['reason']}, {r['supplier']}): {r['words']}")
