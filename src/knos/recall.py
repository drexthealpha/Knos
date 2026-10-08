"""`knos recall`: what a buyer's memory holds, answered from the memory engine only.

    knos recall exception --buyer ORG --terms HASH --reason CODE [--supplier ID] [--memory DIR] [--json]
    knos recall keep-approval FILE --buyer ORG [--memory DIR]        keep one approval record (the approver's file)
    knos recall approval COMMITMENT --buyer ORG [--evidence FILE] [--memory DIR] [--json]
    knos recall grant --supplier ID --buyer ORG --terms HASH --outcome accepted --ref DLV [--value N] [--memory DIR]
    knos recall supplier ID --buyer ORG [--memory DIR] [--json]

`approval` answers the approver's question six months later: who approved this commitment, what amount, under which
policy version and why, whether the record is intact (it agrees with the engine's append-only journal) and, given the
evidence as it stands now, whether it still matches the evidence the approver saw. `supplier` answers what a supplier
brings from its other buyers (only what each of them granted) and how long its first and second buyers took from
first order to first payment.

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


# ---- the approver's defence and supplier reuse ---------------------------------------------------------------------

def amount_words(amount) -> str:
    """An amount with thousands separators: "1200.5" -> "1,200.50"; what is not a number is returned as it was."""
    try:
        return f"{float(str(amount).replace(',', '')):,.2f}"
    except ValueError:
        return str(amount)


def approval(store, commitment: str, evidence=None) -> dict:
    """The approver's defence (history.approval_recalled), with `words`."""
    row = history.approval_recalled(store, commitment, evidence)
    row["words"] = approval_words(row)
    return row


def approval_words(row: dict) -> str:
    if not row.get("approvals"):
        return "No approval of this commitment is remembered."
    said = []
    for a in row["approvals"]:
        line = f"{a['approver']} approved {amount_words(a['amount'])} on {a['at']} under policy {a['policy_version']}"
        line += f" for {a['beneficiary']}" if a.get("beneficiary") else ""
        line += f" against {a['purchase_order']}" if a.get("purchase_order") else ""
        line += "." if a["intact"] else "; this record does not match the journal."
        said.append(line)
    if row.get("journal_only"):
        said.append(f"The journal holds {len(row['journal_only'])} approval(s) the record has lost.")
    if row.get("matches") is True:
        said.append("The evidence still matches what was approved.")
    elif row.get("matches") is False:
        said.append("The evidence has changed since it was approved.")
    return " ".join(said)


def supplier(store, supplier_id: str, buyer: str) -> dict:
    """What a supplier brings from its other buyers (history.supplier_brings), with `words`."""
    row = history.supplier_brings(store, supplier_id, buyer)
    row["words"] = supplier_words(row)
    return row


def supplier_words(row: dict) -> str:
    if not row.get("from"):
        said = "No other buyer granted a record of this supplier."
    else:
        o = row["outcomes"]
        said = (f"{row['buyers']} other buyer{'' if row['buyers'] == 1 else 's'} granted: {o['accepted']} accepted, {o['refused']} refused, "
                f"{o['disputed']} disputed, {o['reverted']} reverted; {amount_words(row['value'] / 1e6)} accepted.")
    r = row["reuse"]
    if r["saved_seconds"] is not None:
        said += f" First buyer onboarded in {took(r['first_seconds'])}, second in {took(r['second_seconds'])}."
    return said


def order_funded(buyer: str, supplier_id: str, at: float | None = None, memory: Path | None = None) -> dict | None:
    """The hook where a buyer's order to a supplier is funded: the supplier's memory keeps when this buyer first
    ordered. None when the memory engine is not installed or a name is missing."""
    return _onboard(buyer, supplier_id, memory, ordered_at=at)


def order_paid(buyer: str, supplier_id: str, at: float | None = None, memory: Path | None = None) -> dict | None:
    """The hook where a buyer first pays a supplier: the supplier's memory keeps when this buyer first paid."""
    return _onboard(buyer, supplier_id, memory, paid_at=at)


def _onboard(buyer, supplier_id, memory, **when) -> dict | None:
    if not buyer or not supplier_id:
        return None
    try:
        st = history.SibylStore.for_supplier(supplier_id, memory)
    except ImportError:
        return None
    import time as _time
    return history.onboarded(st, buyer, **{k: (v if v is not None else _time.time()) for k, v in when.items()})


# ---- the command ------------------------------------------------------------------------------------------------------

def register(app: Any, help_lines: list | None = None) -> None:
    """`knos recall exception`. `help_lines`: cli._HELP, which gets the command's line."""
    import importlib
    typer = importlib.import_module("typer")
    if help_lines is not None:
        help_lines.append(("recall", "For money", "What memory holds: past exceptions, who approved what, what a supplier brings."))
    group = typer.Typer(help="What memory holds: how the same exception ended before, who approved a commitment and under which policy, what a supplier brings from other buyers.", no_args_is_help=True)
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

    def _json_file(path: Path, what: str):
        from . import cli
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as why:
            raise cli.Stop(f"Could not read {what} {path}: {why}.") from None

    @group.command("keep-approval")
    def keep_approval_(record: Path = typer.Argument(..., metavar="FILE", help="the approval record: a JSON object (commitment, approver, policy_version, amount, at, why, evidence_sha256)"),
                       buyer: str = typer.Option(..., "--buyer", metavar="ORG", help="the buyer organisation whose memory keeps it"),
                       memory: Path = typer.Option(None, "--memory", metavar="DIR", help="the directory of the memory store")) -> None:
        """Keep one approval record in the buyer's memory, so it can be recalled and checked later."""
        from . import cli
        try:
            got = history.approval_kept(_open(buyer, memory), _json_file(record, "the approval record"))
        except ValueError as why:
            raise cli.Stop(f"Nothing was kept: {why}.") from None
        typer.echo(f"Kept: {got['approver']} approved {amount_words(got['amount'])} for {got['commitment']} under policy {got['policy_version']}.")

    @group.command("approval")
    def approval_(commitment: str = typer.Argument(..., metavar="COMMITMENT", help="what was approved: an order's or offer's commitment id"),
                  buyer: str = typer.Option(..., "--buyer", metavar="ORG", help="the buyer organisation whose memory answers"),
                  evidence: Path = typer.Option(None, "--evidence", metavar="FILE", help="the evidence as it stands now (JSON), to check it still matches"),
                  memory: Path = typer.Option(None, "--memory", metavar="DIR", help="the directory of the memory store"),
                  as_json: bool = typer.Option(False, "--json", help="print the answer as JSON")) -> None:
        """Who approved this commitment, what amount, under which policy version, and whether the evidence still matches. Exit status 1 when nothing is remembered, the record disagrees with the journal, or the evidence changed."""
        from . import cli
        try:
            row = approval(_open(buyer, memory), commitment, _json_file(evidence, "the evidence") if evidence is not None else None)
        except ValueError as why:
            raise cli.Stop(f"Nothing was recalled: {why}.") from None
        typer.echo(json.dumps(row, indent=1, sort_keys=True) if as_json else row["words"])
        if not row["approvals"] or not row["intact"] or row["matches"] is False:
            raise typer.Exit(1)

    @group.command("grant")
    def grant_(supplier_id: str = typer.Option(..., "--supplier", metavar="ID", help="the supplier"),
               buyer: str = typer.Option(..., "--buyer", metavar="ORG", help="the buyer organisation that grants"),
               terms: str = typer.Option(..., "--terms", metavar="HASH", help="the hash of the terms, 64 hex characters"),
               outcome: str = typer.Option(..., "--outcome", help="accepted, refused, disputed or reverted"),
               ref: str = typer.Option(..., "--ref", metavar="DLV", help="the deliverable's id: one result is counted once"),
               value: int = typer.Option(0, "--value", help="the value accepted, in base units (6 decimals)"),
               memory: Path = typer.Option(None, "--memory", metavar="DIR", help="the directory of the memory store")) -> None:
        """Let a supplier show one of your results to its other buyers. Nothing is shared that was not granted this way."""
        from . import cli
        try:
            history._buyer_key(buyer)
            got = history.outcome_granted(history.SibylStore.for_supplier(supplier_id, memory), supplier_id, buyer, terms.lower(), outcome, ref, value)
        except ValueError as why:
            raise cli.Stop(f"Nothing was granted: {why}.") from None
        typer.echo(f"Granted: {sum(got['outcomes'].values())} result(s) of {supplier_id} under these terms can be shown to its other buyers.")

    @group.command("supplier")
    def supplier_(supplier_id: str = typer.Argument(..., metavar="ID", help="the supplier"),
                  buyer: str = typer.Option(..., "--buyer", metavar="ORG", help="the buyer organisation asking (its own results are left out)"),
                  memory: Path = typer.Option(None, "--memory", metavar="DIR", help="the directory of the memory store"),
                  as_json: bool = typer.Option(False, "--json", help="print the answer as JSON")) -> None:
        """What this supplier brings from its other buyers, as they granted it, and how long its first and second buyers took to onboard it."""
        from . import cli
        try:
            row = supplier(history.SibylStore.for_supplier(supplier_id, memory), supplier_id, buyer)
        except ValueError as why:
            raise cli.Stop(f"Nothing was recalled: {why}.") from None
        typer.echo(json.dumps(row, indent=1, sort_keys=True) if as_json else row["words"])
