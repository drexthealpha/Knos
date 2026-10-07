"""The statement a person who approves invoices attaches in their accounts-payable system: `knos statement`.

    knos statement make <evidence>      one statement as JSON (canonical), CSV and PDF
    knos statement approve <file> --agreed --by NAME --role ROLE
    knos statement pay <file> --line inv_... --method bank --ref REF --on DATE
    knos statement grn <file> --line inv_...   the goods-received note of one line: order, acceptance and invoice line, matched
    knos statement show <file>          what was authorised, delivered, passed, already billed, approved, disputed, owed
    knos statement export <file> --format quickbooks|netsuite|generic
    knos statement verify <file>        make it again from its evidence: "same", or the first line that differs

It is made from one of two things, and only from them:

    a shadow run     `evidence.json` as `knos shadow --out` writes it: the supplier's invoice and every answer GitHub
                     gave about its lines. GitHub does not sign those answers; the statement says so.
    a closed month   the archive `knos meter export --bundle` writes: both ledgers, the close record and each party's
                     token, signed by GitHub. Its signatures are checked here with the keys in the archive; neither
                     the chain nor the network is asked.

Each invoice line carries the four ids of knos.ids (deliverable, evaluations, invoice line, and a settlement once one
is recorded), one state of ids.LINE_STATES, its amount, why (for a line that is not agreed, in plain words) and where
its evidence is. A deliverable that an earlier statement agreed (`--prior`) is a duplicate here: already billed.

The JSON is the statement. It holds its own SHA-256 (of its canonical bytes with that one field empty) and the
SHA-256 of every piece of evidence, and the evidence itself unless `--reference` kept it in a file beside. The CSV and
the PDF are written from `cells`, so they say the same thing in the same words, and both carry the JSON's hash.

Approvals and payment status are appended to `<name>.status.json`, never to the statement: the statement does not
change after it is made. Nothing here moves money. A payment made by bank is recorded with the payer's own reference.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import re
from pathlib import Path

from . import ids, pdf, shadow
from . import ledger as L

KIND, VERSION = "knos-statement", 1
NAME = "ap-statement"                            # the files: ap-statement.json, .csv, .pdf and .status.json (statement.json is the shadow run's own)
STATUS_KIND = "knos-statement-status"
POLICY_SHADOW = "github-checks-at-merge.v1"       # what shadow mode evaluates a line by: the checks at the merged commit
PAY_STATES = ("payable", "paid_outside", "held", "refunded", "devnet_demonstration")
PAY_WORDS = {"payable": "payable", "paid_outside": "paid outside Knos", "held": "held", "refunded": "refunded",
             "devnet_demonstration": "devnet demonstration"}
METHODS = {"bank": "paid_outside", "other": "paid_outside", "chain": "devnet_demonstration"}
NOTES = {"shadow": shadow.NOTE + " GitHub's answers are kept as they were read; GitHub does not sign them.",
         "month": "Made from a closed month of the meter. The tokens in the archive are GitHub's signatures of the close record; the chain was not asked.",
         "events": "Made from a log of events (knos events). The log's own chain of hashes was checked; what each event's evidence names was not read again."}
HEAD = ("line", "reference", "supplier", "state", "amount", "why", "deliverable", "evaluations", "invoice_line", "settlement", "payment",
        "evidence", "evidence_sha256", "duplicate_of", "assurance", "po_reference", "grn_reference")
GRN_KIND = "knos-grn"
NOT_EVALUATED = "not evaluated"                    # what the assurance column says of a line no evaluation stands behind
NO_ORDER = {"shadow": "no purchase order on record: a shadow run reads the invoice and GitHub, not the order; give the payment's receipt (--receipt)",
            "month": "no purchase order on record: a closed month names each order by its deliverable, not its terms or approver; give the payment's receipt (--receipt)",
            "events": "no purchase order on record: the log of events does not carry the order's terms or approver; give the payment's receipt (--receipt)"}
MONTH_WHY = {"missing from the buyer's ledger": "the buyer's ledger has no record of this evaluation",
             "missing from the seller's ledger": "the supplier's ledger has no record of this evaluation",
             "verdict differs": "the two ledgers give this evaluation different verdicts",
             "rate differs": "the two ledgers give this evaluation different prices",
             "month differs": "the two ledgers put this evaluation in different months"}


class Refused(ValueError):
    """A statement that cannot be made, read or checked, in words."""


def canonical(doc) -> bytes:
    """JSON with sorted keys and no spaces, UTF-8, one final newline: the bytes that are hashed."""
    return (json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8", "surrogatepass")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(st: dict) -> str:
    """The statement's own SHA-256: of its canonical bytes with the `sha256` field empty."""
    return sha(canonical({**st, "sha256": ""}))


def units(amount: str | None, scale: int) -> int:
    """"1200.50" as 120050 when the scale is 2. An empty amount is 0."""
    if not amount:
        return 0
    whole, _, part = amount.lstrip("-").partition(".")
    return (-1 if amount.startswith("-") else 1) * int(whole + part.ljust(scale, "0")[:scale])


def amount_of(value: int, scale: int) -> str:
    """120050 as "1200.50": at least two places, never rounded."""
    whole, part = divmod(abs(value), 10 ** scale)
    text = f"{part:0{scale}d}".rstrip("0")
    return f"{'-' if value < 0 else ''}{whole}.{text:0<2}"


# ---- what an earlier statement already billed -----------------------------------------------------------------------

def billed_before(prior: dict) -> dict:
    """What a later statement keeps of an earlier one: its hash, its invoice and day, and each deliverable it agreed
    with the line that billed it. A line that was disputed there and is billed again is not a duplicate."""
    if not isinstance(prior, dict) or prior.get("kind") != KIND or digest(prior) != prior.get("sha256"):
        raise Refused("--prior is not a Knos statement, or it was changed after it was made (its sha256 is not its own).")
    return {"sha256": prior["sha256"], "invoice": prior["invoice"], "date": prior["date"],
            "deliverables": {ln["deliverable"]: {"line": ln["line"], "invoice_line": ln["invoice_line"]}
                             for ln in reversed(prior["lines"]) if ln["state"] == "agreed"}}


def _earlier(lines: list[dict], prior: list[dict]) -> None:
    """Mark as duplicate every line whose deliverable an earlier statement agreed."""
    for ln in lines:
        for p in prior:
            was = p["deliverables"].get(ln["deliverable"])
            if was and ln["state"] != "duplicate":
                ln.update({"state": "duplicate", "payment": "held", "duplicate_of": f"statement {p['sha256'][:12]} line {was['line']}",
                           "why": f"already billed: invoice {p['invoice']} line {was['line']} agreed this deliverable on {p['date']}"})


def _finish(meta: dict, source: str, scale: int, lines: list[dict], prior: list[dict], evidence: dict) -> dict:
    _earlier(lines, prior)
    priced = all(ln["amount"] for ln in lines)
    totals = {"billed": {"lines": len(lines), "amount": amount_of(sum(units(ln["amount"], scale) for ln in lines), scale) if priced else ""}}
    for state in ids.LINE_STATES:
        mine = [ln for ln in lines if ln["state"] == state]
        totals[state] = {"lines": len(mine), "amount": amount_of(sum(units(ln["amount"], scale) for ln in mine), scale) if priced else ""}
    st = {"kind": KIND, "version": VERSION, "sha256": "", "date": meta["date"], "invoice": meta["invoice"], "supplier": meta["supplier"],
          "buyer": meta["buyer"], "currency": meta["currency"], "scale": scale, "source": source, "note": NOTES[source], "prior": prior,
          "lines": lines, "totals": totals, "evidence": evidence}
    st["sha256"] = digest(st)
    return st


def _day(text: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", text or ""):
        raise Refused(f"A day is written YYYY-MM-DD; {text!r} is not one.")
    return text


# ---- from a shadow run ----------------------------------------------------------------------------------------------

def from_shadow(bundle: dict, meta: dict, prior: list[dict] | tuple = (), embed: bool = True) -> dict:
    """The statement of a shadow run. `bundle`: {"invoice": the invoice's text, "answers": {path: GitHub's answer}}.
    `meta`: invoice, supplier, buyer, currency, date (each may be empty: the supplier is then the invoice's own, the
    day the last merge's)."""
    try:
        text, answers = bundle["invoice"], bundle["answers"]
        invoice = shadow.parse(text)
    except (KeyError, TypeError, ValueError) as err:
        raise Refused(f"This is not the evidence of a shadow run (the invoice and GitHub's answers): {err}") from None
    get, used = shadow.keeping(shadow.recorded(answers))
    facts = shadow.gather(invoice, get)
    sh = shadow.statement(invoice, facts)
    items = {"invoice": sha(text.encode("utf-8", "surrogatepass")), **{path: sha(canonical(answer)) for path, answer in sorted(used.items())}}
    number = meta.get("invoice") or f"sha256:{items['invoice'][:16]}"
    lines: list[dict] = []
    for r in sh["lines"]:
        supplier = r["supplier"] or meta.get("supplier") or sh["supplier"]
        mine = ids.invoice_line(supplier, number, r["line"])
        got = facts.get(r["pr"].lower()) or {"paths": []}
        if r["class"] == "duplicate":
            deliverable = lines[r["duplicate_of"] - 1]["deliverable"]
        elif r["issues"]:
            deliverable = ids.deliverable("github:" + r["issues"][0].split("#")[0].lower(), "issue " + r["issues"][0].split("#")[1])
        elif r["url"]:
            deliverable = ids.deliverable("github:" + r["pr"].split("#")[0].lower(), "pull " + r["pr"].split("#")[1])
        else:
            deliverable = ids.deliverable("invoice:" + number, mine)        # a line that names no change: nothing to tie it to but itself
        judged = r["merged"] and r["class"] != "unreadable"
        state, why = {"clean": ("agreed", ""),
                      "failed": ("disputed", "a check failed when this change was merged: " + ", ".join(f["name"] for f in r["failed"])),
                      "not_merged": ("disputed", "the pull request is not merged"),
                      "duplicate": ("duplicate", f"billed twice on this invoice: {r['why']}"),
                      "unverified": ("insufficient_evidence", f"the checks give no verdict: {r['why']}"),
                      "unreadable": ("insufficient_evidence", f"GitHub could not be read for this line: {r['why']}")}[r["class"]]
        link = r["failed"][0]["url"] if r["failed"] and r["failed"][0]["url"] else r["url"]
        lines.append({"line": r["line"], "reference": r["pr"], "supplier": supplier, "deliverable": deliverable,
                      "evaluations": [ids.evaluation(deliverable, r["head"], POLICY_SHADOW, "github", sha(canonical(r["checks"]))[:16])] if judged else [],
                      "invoice_line": mine, "settlement": None, "state": state, "payment": "payable" if state == "agreed" else "held",
                      "amount": r["amount"] or "", "why": why, "evidence": link,
                      "evidence_sha256": sha("".join(f"{p} {items[p]}\n" for p in got["paths"]).encode()) if got["paths"] else "",
                      "duplicate_of": "" if r["duplicate_of"] is None else f"line {r['duplicate_of']}"})
    merged = sorted(r["merged_at"][:10] for r in sh["lines"] if r["merged_at"])
    kept = {"answers": dict(sorted(used.items())), "invoice": text}
    evidence: dict = {"kind": "github-answers", "signed": [], "sha256": sha(canonical(kept)), "items": items, "embedded": kept if embed else None}
    full = {"invoice": number, "supplier": meta.get("supplier") or sh["supplier"], "buyer": meta.get("buyer") or "", "currency": meta.get("currency") or "",
            "date": _day(meta.get("date") or (merged[-1] if merged else "1970-01-01"))}
    return _finish(full, "shadow", 2, lines, list(prior), evidence)


# ---- from a closed month of the meter -------------------------------------------------------------------------------

def _files(blob: bytes) -> dict[str, bytes]:
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as tar:
        return {m.name: (tar.extractfile(m) or io.BytesIO()).read() for m in tar.getmembers()}


def _month_why(said: str) -> str:
    """The close record's reason for a line in dispute, in an approver's words."""
    for role, name in (("buyer", "buyer"), ("seller", "supplier")):
        if said.startswith(f"duplicate in the {role}'s ledger"):
            return f"the {name}'s ledger holds this evaluation twice and no correction settles it"
    return MONTH_WHY.get(said, said)


def from_month(blob: bytes, meta: dict, prior: list[dict] | tuple = (), embed: bool = True) -> dict:
    """The statement of a closed month. `blob`: the archive of `knos meter export --bundle`. One line is one deliverable
    the supplier's ledger accepted in the month, at the price of the evaluation that first accepted it. The archive is
    checked first (ledger.verify_month): every file, both ledgers, the close record and GitHub's signatures."""
    try:
        record, _done = L.verify_month(blob)
        files = _files(blob)
    except L.Bad as err:
        raise Refused(f"The month's archive does not hold: {err}") from None
    if "ledger.seller.jsonl" not in files:
        raise Refused("The archive holds no supplier's ledger. The supplier's count is the invoice: ask for an archive with it.")
    month, both = record["month"], "ledger.buyer.jsonl" in files
    listed = json.loads(files["MANIFEST.json"])["files"]
    book = L.canonical(L.load(files["ledger.seller.jsonl"].decode("utf-8")))
    first = L.outcomes(book)
    open_lines = {d["id"]: d["why"] for d in record["disputed"]}
    by: dict[str, list] = {}
    for x in book.kept:
        if x.month == month:
            by.setdefault(x.e.deliverable, []).append(x)
    supplier = meta.get("supplier") or f"gh:{record['seller']}"
    number = meta.get("invoice") or f"meter {month}"
    lines: list[dict] = []
    for entries in sorted(by.values(), key=lambda es: (es[0].seq, es[0].e.id)):
        won = [x for x in entries if x.e.accepted]
        if not won:
            continue        # a rejection that ran correctly is an evaluation, not an outcome: nothing is billed for it
        e = won[0].e
        deliverable = ids.deliverable(e.order, e.milestone)
        argued = [_month_why(open_lines[x.e.id.hex()]) for x in entries if x.e.id.hex() in open_lines]
        earlier = first[e.deliverable].month
        if earlier < month:
            state, why = "duplicate", f"already billed: this deliverable was accepted in {earlier}, and an accepted deliverable is billed once"
        elif argued:
            state, why = "disputed", argued[0]
        elif not both:
            state, why = "insufficient_evidence", "only the supplier's ledger is in the archive, so the buyer's count cannot be made again"
        else:
            state, why = "agreed", ""
        n = len(lines) + 1
        lines.append({"line": n, "reference": f"order {e.order[:16]} milestone {e.milestone}", "supplier": supplier, "deliverable": deliverable,
                      "evaluations": [ids.evaluation(deliverable, x.e.artifact, x.e.policy, "knos-meter", x.e.id.hex()) for x in entries],
                      "invoice_line": ids.invoice_line(supplier, number, n), "settlement": None, "state": state,
                      "payment": "payable" if state == "agreed" else "held", "amount": amount_of(e.rate, 6), "why": why,
                      "evidence": f"ledger.seller.jsonl evaluation {won[0].e.id.hex()}", "evidence_sha256": listed["ledger.seller.jsonl"],
                      "duplicate_of": f"month {earlier}" if earlier < month else ""})
    year, mon = divmod(month, 100)
    last = (31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[mon - 1]
    evidence: dict = {"kind": "meter-month", "signed": [r for r in L.ROLES if f"{r}.jwt" in files], "sha256": sha(blob), "items": dict(sorted(listed.items())),
                "embedded": base64.b64encode(blob).decode("ascii") if embed else None}
    full = {"invoice": number, "supplier": supplier, "buyer": meta.get("buyer") or f"gh:{record['buyer']}", "currency": meta.get("currency") or "",
            "date": _day(meta.get("date") or f"{year:04d}-{mon:02d}-{last:02d}")}
    return _finish(full, "month", 6, lines, list(prior), evidence)


# ---- from the one log of events -------------------------------------------------------------------------------------

def is_events(data: bytes) -> bool:
    """Whether a file is a log of `knos events`: its first line is one event (a shadow run's evidence is one document)."""
    try:
        first = json.loads(data.lstrip().split(b"\n", 1)[0].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(first, dict) and {"id", "kind", "prev", "seq", "source"} <= set(first)


def from_events(data: bytes, meta: dict, prior: list[dict] | tuple = (), embed: bool = True) -> dict:
    """The statement of one month of a log of events (knos.events), whichever modes wrote it: the month of `meta`'s
    date, or the log's last month. One line is one invoice line the log counts, in the state the log gives it
    (knos.events.statement). What arrived more than once and was counted once is listed under `repeats`, each with
    every source it came by, and `accepted_deliverables` is how many deliverables the month accepted: billed once
    each, however many evaluations and arrivals it took."""
    from . import events as E
    try:
        log, wrong = E.read(data.decode("utf-8"))
    except (UnicodeDecodeError, L.Bad) as err:
        raise Refused(f"The events log cannot be read: {err}") from None
    if wrong:
        raise Refused(f"The events log does not check. {wrong[0]}")
    month = int(_day(meta["date"])[:7].replace("-", "")) if meta.get("date") else max(log.by_month, default=0)
    if not month:
        raise Refused("The events log names no month: there is nothing to state.")
    got = E.statement(log, month, meta.get("supplier") or "")
    spoken = sorted({x["unit"] for x in got["invoice_lines"] if x["unit"]})
    if len(spoken) > 1:
        raise Refused(f"The month's invoice lines are in more than one unit ({', '.join(spoken)}): make one statement a supplier (--supplier).")
    scale = {"cents": 2, "units": 6}.get(spoken[0] if spoken else "cents", 0)
    number = meta.get("invoice") or f"events:{month}"
    at: dict[str, int] = {}                 # deliverable -> the statement line that bills it first
    lines: list[dict] = []
    for x in got["invoice_lines"]:
        e, n = log.events[x["line"]], len(lines) + 1
        mine = [log.events[k] for k in log.by_deliverable.get(x["deliverable"], ()) if log.events[k].first is None] if x["deliverable"] else []
        first = at.setdefault(x["deliverable"], n) if x["deliverable"] else n
        lines.append({"line": n, "reference": e.evidence, "supplier": x["supplier"], "deliverable": x["deliverable"],
                      "evaluations": [k.id for k in mine if k.kind == "evaluation"], "invoice_line": x["id"],
                      "settlement": next((k.id for k in mine if k.kind == "settlement"), None), "state": x["state"],
                      "payment": "payable" if x["state"] == "agreed" else "held", "amount": "" if x["amount"] is None else amount_of(x["amount"], scale),
                      "why": x["why"], "evidence": f"event {x['line']} of the log ({e.source})", "evidence_sha256": sha(e.line().encode("utf-8")),
                      "duplicate_of": f"line {first}" if x["state"] == "duplicate" and first != n else ""})
    year, mon = divmod(month, 100)
    last = (31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[mon - 1]
    evidence: dict = {"kind": "events-log", "signed": [], "sha256": sha(data), "items": {"head": log.head, "log": sha(data)},
                      "embedded": base64.b64encode(data).decode("ascii") if embed else None}
    full = {"invoice": number, "supplier": meta.get("supplier") or "", "buyer": meta.get("buyer") or "", "currency": meta.get("currency") or "",
            "date": _day(meta.get("date") or f"{year:04d}-{mon:02d}-{last:02d}")}
    st = _finish(full, "events", scale, lines, list(prior), evidence)
    st.update({"accepted_deliverables": got["accepted_deliverables"], "repeats": [d for d in log.dupes() if log.events[d["counted_at"]].month == month], "sha256": ""})
    st["sha256"] = digest(st)
    return st


def make(data: bytes, meta: dict, prior: list[dict] | tuple = (), embed: bool = True) -> dict:
    """A statement from an evidence file's bytes, whichever of the three it is."""
    if is_events(data):
        return from_events(data, meta, prior, embed)
    if data.lstrip()[:1] == b"{":
        try:
            return from_shadow(json.loads(data.decode("utf-8-sig")), meta, prior, embed)
        except (ValueError, UnicodeDecodeError) as why:
            if isinstance(why, Refused):
                raise
            raise Refused(f"The evidence file is not JSON: {why}") from None
    return from_month(data, meta, prior, embed)


# ---- approvals and payment status: a file beside the statement, appended to ----------------------------------------------

def new_status(st: dict) -> dict:
    return {"kind": STATUS_KIND, "version": VERSION, "statement": st["sha256"], "events": []}


def _status(st: dict, status: dict | None) -> dict:
    status = status or new_status(st)
    if status.get("kind") != STATUS_KIND or status.get("statement") != st["sha256"]:
        raise Refused("The status file is another statement's: it names another sha256.")
    return status


def approve(st: dict, status: dict | None, by: str, role: str, on: str) -> dict:
    """The status with one more approval: `by`, in `role`, approves every agreed line nobody approved yet. The lines
    that are disputed, duplicate or without enough evidence stay open. The role is recorded as it was stated."""
    status = _status(st, status)
    if not by.strip() or not role.strip():
        raise Refused("An approval names who approved and in which role: --by and --role.")
    done = {i for e in status["events"] if e["type"] == "approval" for i in e["lines"]}
    mine = [ln for ln in st["lines"] if ln["state"] == "agreed" and ln["invoice_line"] not in done]
    if not mine:
        raise Refused("There is no agreed line left to approve." if done else "No line of this statement is agreed, so there is nothing to approve.")
    event = {"type": "approval", "scope": "agreed", "by": by.strip(), "role": role.strip(), "on": _day(on), "lines": [ln["invoice_line"] for ln in mine],
             "amount": amount_of(sum(units(ln["amount"], st["scale"]) for ln in mine), st["scale"])}
    return {**status, "events": [*status["events"], event]}


_COUNT = {2: "two", 3: "three", 4: "four"}


def not_independent(receipt) -> str:
    """What a comment and a statement line say of a quorum whose evaluators share a controller, from the receipt's own
    field (`evaluator_observed.same_controller`, which knos.receipt computes and checks): "two evaluations, one
    controller: not independent". Empty for every other receipt, and for what is not a receipt."""
    seen = receipt.get("evaluator_observed") if isinstance(receipt, dict) else None
    judges = seen.get("evaluators") if isinstance(seen, dict) else None
    if not isinstance(seen, dict) or not isinstance(judges, list) or len(judges) < 2 or seen.get("same_controller") is not True:
        return ""
    return f"{_COUNT.get(len(judges), str(len(judges)))} evaluations, one controller: not independent"


def pay(st: dict, status: dict | None, line: str, method: str, reference: str, on: str, state: str = "", receipt: dict | None = None) -> dict:
    """The status with one more settlement record for the invoice line `line`. `method`: bank, chain or other; `state`:
    one of PAY_STATES (a bank payment is "paid outside Knos" unless said otherwise). It records; it moves nothing.
    `receipt`: the acceptance receipt of a payment made on chain (its transaction is the reference). When the quorum
    it records was of evaluators that share a controller, the record carries that in a `note`, and the line says it."""
    status = _status(st, status)
    ln = next((x for x in st["lines"] if x["invoice_line"] == line), None)
    if ln is None:
        raise Refused(f"No line of this statement has the id {line}. The ids are in the invoice_line column.")
    if method not in METHODS:
        raise Refused(f"--method is one of {', '.join(METHODS)}; {method!r} is none of them.")
    state = (state or METHODS[method]).strip().lower().replace(" ", "_")
    state = {"paid_outside_knos": "paid_outside"}.get(state, state)
    if state not in PAY_STATES:
        raise Refused(f"--state is one of: {', '.join(PAY_WORDS.values())}.")
    if not reference.strip():
        raise Refused("A settlement record needs the payer's own reference: --ref.")
    settlement = ids.settlement(ln["deliverable"], method, reference.strip())
    if any(e["type"] == "settlement" and e["settlement"] == settlement and e["state"] == state for e in status["events"]):
        raise Refused(f"This is already recorded ({settlement}). Nothing was changed.")
    event = {"type": "settlement", "line": line, "deliverable": ln["deliverable"], "settlement": settlement, "method": method,
             "reference": reference.strip(), "on": _day(on), "state": state}
    if receipt is not None:
        from . import receipt as rc
        why = rc.check(receipt)
        paid = receipt.get("transaction") if isinstance(receipt, dict) and not why else None
        if why or method != "chain" or not isinstance(paid, dict) or paid.get("signature") != reference.strip():
            raise Refused(f"--receipt is not a valid acceptance receipt of this payment{': ' + why if why else ''}. It goes with --method chain, and its "
                          "transaction is the reference.")
        if not_independent(receipt):
            event["note"] = not_independent(receipt)
    return {**status, "events": [*status["events"], event]}


def grn_reference(ln: dict) -> str:
    """The reference of a line's goods-received note: the id of the first evaluation that stands behind it, as a note's
    (`grn_` and the same 24 hex characters). Empty for a line nothing evaluated: no goods were received on record."""
    return "grn_" + ln["evaluations"][0].split("_", 1)[1] if ln["evaluations"] else ""


def lines_now(st: dict, status: dict | None = None) -> list[dict]:
    """The statement's lines with what the status file adds: the last settlement recorded for each, and who approved it.
    Each line also says its assurance level (knos.receipt.LEVELS), computed and never typed: the level of the receipt a
    recorded goods-received note was made from; without one, `reported` for a line an evaluation stands behind (the
    evidence is a record of what a workflow reported) and "not evaluated" for a line with none. `po_reference` is the
    purchase order a recorded note names, `grn_reference` the note's own reference."""
    events = _status(st, status)["events"]
    out = []
    for ln in st["lines"]:
        noted = [e["grn"] for e in events if e["type"] == "grn" and e["line"] == ln["invoice_line"]]
        ln = {**ln, "assurance": noted[-1]["receipt_of_goods"]["assurance"] if noted else "reported" if ln["evaluations"] else NOT_EVALUATED,
              "po_reference": (noted[-1]["purchase_order"] or {}).get("number", "") if noted else "", "grn_reference": grn_reference(ln)}
        paid = [e for e in events if e["type"] == "settlement" and e["line"] == ln["invoice_line"]]
        ok = next((e for e in events if e["type"] == "approval" and ln["invoice_line"] in e["lines"]), None)
        note = paid[-1].get("note", "") if paid else ""       # a quorum of one controller, from the payment's receipt (`pay`)
        out.append({**ln, "settlement": paid[-1]["settlement"] if paid else None, "payment": paid[-1]["state"] if paid else ln["payment"],
                    "approved_by": f"{ok['by']} ({ok['role']}) on {ok['on']}" if ok else "",
                    **({"why": f"{ln['why']}; {note}" if ln["why"] else note} if note else {})})
    return out


def answers(st: dict, status: dict | None = None) -> list[tuple[str, str]]:
    """What whoever approves the invoice asks, answered from the statement and its status, in order."""
    now, scale, t = lines_now(st, status), st["scale"], st["totals"]
    priced = bool(t["billed"]["amount"])
    unit = f" {st['currency']}" if st["currency"] else ""

    def said(rows: list[dict]) -> str:
        n = len(rows)
        return f"{n} {'line' if n == 1 else 'lines'}" + (f", {amount_of(sum(units(r['amount'], scale) for r in rows), scale)}{unit}" if priced else "")

    of = lambda state: [r for r in now if r["state"] == state]                     # noqa: E731
    approvals = [e for e in _status(st, status)["events"] if e["type"] == "approval"]
    agreed = of("agreed")
    waiting = [r for r in agreed if not r["approved_by"]]
    paid = [r for r in now if r["payment"] in ("paid_outside", "devnet_demonstration")]
    wrongly = [r for r in paid if r["state"] != "agreed"]
    approved = "; ".join(f"{len(e['lines'])} agreed {'line' if len(e['lines']) == 1 else 'lines'}" + (f", {e['amount']}{unit}" if priced else "")
                         + f" by {e['by']} ({e['role']}) on {e['on']}, role as stated" for e in approvals) or "nobody yet"
    if approvals and waiting:
        approved += f"; {len(waiting)} agreed not yet approved"
    return [
        ("Authorised", "not known here: a shadow run reads the invoice and GitHub, not the order" if st["source"] == "shadow"
         else f"{st['accepted_deliverables']} {'deliverable' if st['accepted_deliverables'] == 1 else 'deliverables'} accepted in the log this month, each billable once"
         if st["source"] == "events" else f"{len({r['deliverable'] for r in now})} deliverables, each a milestone of an order both ledgers name"),
        *([("Arrived twice", "; ".join(f"{d['kind'].replace('_', ' ')} {d['id']} by {' and '.join(x['source'] for x in d['sources'])}, counted once"
                                         for d in st["repeats"]) or "nothing")] if st["source"] == "events" else []),
        ("Billed", said(now) + f" on invoice {st['invoice']}" + (f" from {st['supplier']}" if st["supplier"] else "")),
        ("Delivered", f"{sum(1 for r in now if r['evaluations'])} of {len(now)} lines name work that was evaluated"),
        ("Passed", said(agreed) + " agreed"),
        ("Already billed", said(of("duplicate")) + (": " + "; ".join(f"line {r['line']} ({r['duplicate_of']})" for r in of("duplicate")) if of("duplicate") else "")),
        ("Approved", approved),
        ("Disputed", said(of("disputed")) + ", open"),
        ("Insufficient evidence", said(of("insufficient_evidence")) + ", open"),
        ("Credited", said([r for r in now if r["payment"] == "refunded"]) + " refunded"
         + (f"; {said(wrongly)} paid though not agreed, to be credited or settled" if wrongly else "")),
        ("Paid", said(paid) + (" (" + ", ".join(sorted({PAY_WORDS[r["payment"]] for r in paid})) + ")" if paid else "")),
        ("Owed", said([r for r in agreed if r["payment"] == "payable"]) + " payable"),
    ]


# ---- the goods-received note: the three-way match accounts payable performs, for one line --------------------------------

def grn_said(note: dict) -> str:
    """A goods-received note's result in one sentence: "match", or every mismatch."""
    return "match" if note["match"] else "mismatch: " + "; ".join(note["mismatches"])


def grn(st: dict, status: dict | None, line: str, receipt: dict | None = None, po: str = "") -> dict:
    """The goods-received note of the invoice line `line`: three legs side by side and whether they match.

        purchase_order     the funded order or standing offer: its number (`po`, the buyer's own, or the order's address),
                           the hash of its terms, who approved the money and the price. It is read from the payment's
                           acceptance receipt (`receipt`); a statement alone does not carry it.
        receipt_of_goods   the acceptance: the evaluator, the assurance level computed from the receipt's evidence
                           (knos.receipt.assurance_of), who is still trusted, and the evidence.
        invoice_line       the supplier's line: its id, reference, amount, state and payment.

    `match` is true when all three are there and agree; `mismatches` says each thing that is not, in words. With no
    receipt given, the note recorded for the line (`grn_record`) is returned as it was recorded; with none recorded, a
    note with no purchase order, which never matches. It reads; it moves and approves nothing."""
    from decimal import Decimal

    from . import receipt as rc
    events = _status(st, status)["events"]
    ln = next((x for x in lines_now(st, status) if x["invoice_line"] == line), None)
    if ln is None:
        raise Refused(f"No line of this statement has the id {line}. The ids are in the invoice_line column.")
    kept = [e for e in events if e["type"] == "grn" and e["line"] == line]
    if receipt is None and kept:
        return {**kept[-1]["grn"], "recorded": kept[-1]["on"]}
    order, goods, wrong = None, None, []
    leg = {"id": ln["invoice_line"], "line": ln["line"], "reference": ln["reference"], "supplier": ln["supplier"], "amount": ln["amount"],
           "currency": st["currency"], "state": ln["state"], "payment": ln["payment"]}
    if receipt is not None:
        why = rc.check(receipt)
        if why:
            raise Refused(f"--receipt is not a valid acceptance receipt: {why}")
        seen, level = rc.exposed(receipt), rc.assurance_of(receipt, receipt["assurance"]["declared_related"] if receipt["version"] == 5 else ())
        c, m = (receipt.get("commercial_authorisation") if receipt["version"] >= 3 else None), receipt["amounts"]
        f = c["funder"] if c else None
        price = Decimal(m["of"]) / (10 ** m["decimals"])
        order = {"number": po.strip() or receipt["order"], "order": receipt["order"], "terms_hash": seen["policy"]["terms_hash"],
                 "approver": ("not recorded in a receipt of this version" if f is None else f"GitHub account {f['github_id']}"
                              + (f" ({f['login']})" if f["login"] else "") if f["github_id"] else f"wallet {f['wallet']}"),
                 "price": f"{price:.2f}" if price == price.quantize(Decimal("0.01")) else format(price.normalize(), "f"), "funded": c["funded"] if c else None}
        src = seen["evidence_source"]
        goods = {"reference": ln["grn_reference"] or "grn_" + rc.ids_of(receipt, c["deliverable"]["milestone"] if c else 0)["evaluation"].split("_", 1)[1],
                 "verdict": seen["verdict"], "evaluator": f"{seen['evaluator']['kind']}@{seen['evaluator']['version']}",
                 "controllers": [{"kind": e["kind"], "owner_id": e["owner_id"], "actor_id": e["actor_id"]} for e in seen["evaluator"]["controllers"]],
                 "assurance": level["level"], "trusted": level["trusted"], "declared_related": level["declared_related"],
                 "evidence": f"{src['kind'].replace('_', ' ')} {src['reference'] or 'not kept'}", "receipt_sha256": rc.digest(receipt)}
        paid = receipt["transaction"]["signature"] if receipt.get("transaction") else None
        four = receipt.get("ids") or {}
        tied = (four.get("invoice_line") == line or four.get("deliverable") == ln["deliverable"]
                or (paid is not None and any(e["type"] == "settlement" and e["line"] == line and e["reference"] == paid for e in events)))
        if not tied:
            wrong.append("nothing ties this receipt to this line: it names another invoice line and deliverable, and no payment recorded for the line is its transaction")
        if seen["verdict"] != "accepted":
            wrong.append(f"the receipt's verdict is {ids.VERDICT_WORDS[seen['verdict']]}: it authorises no payment")
        if ln["amount"] and Decimal(ln["amount"]) > price:
            wrong.append(f"the invoice line bills {ln['amount']}; the order's price is {order['price']}")
    else:
        wrong.append(NO_ORDER[st["source"]])
        goods = {"reference": ln["grn_reference"], "verdict": "accepted" if ln["evaluations"] and ln["state"] == "agreed" else "none",
                 "evaluator": {"shadow": "GitHub's checks at the merged commit", "month": "the meter, as both ledgers recorded it",
                               "events": "the log of events"}[st["source"]],
                 "controllers": [], "assurance": ln["assurance"], "trusted": [st["note"]] if ln["evaluations"] else [], "declared_related": [],
                 "evidence": ln["evidence"], "receipt_sha256": None}
    if not ln["evaluations"] and receipt is None:
        wrong.append("no receipt of goods: no evaluation of this line is on record")
    if ln["state"] != "agreed":
        wrong.append(f"the invoice line is {ids.LINE_WORDS[ln['state']]}" + (f": {ln['why']}" if ln["why"] else ""))
    return {"kind": GRN_KIND, "version": 1, "statement": st["sha256"], "reference": goods["reference"], "purchase_order": order, "receipt_of_goods": goods,
            "invoice_line": leg, "match": not wrong, "mismatches": wrong, "recorded": None}


def grn_record(st: dict, status: dict | None, line: str, on: str, receipt: dict, po: str = "") -> dict:
    """The status with one more record: the goods-received note of `line`, made from the payment's `receipt`, as it was
    on the day `on`. The line then says the note's assurance level and purchase order in every form and export."""
    status = _status(st, status)
    note = {k: v for k, v in grn(st, status, line, receipt, po).items() if k != "recorded"}
    return {**status, "events": [*status["events"], {"type": "grn", "line": line, "on": _day(on), "grn": note}]}


def grn_lines(note: dict) -> list[str]:
    """A goods-received note for a person: the three legs side by side, then "match" or each mismatch."""
    o, g, i = note["purchase_order"], note["receipt_of_goods"], note["invoice_line"]
    legs = [["PURCHASE ORDER", *([f"number {o['number']}", f"terms {o['terms_hash'][:16]}...", f"approver {o['approver']}", f"price {o['price']}"]
                                 if o else ["none on record"])],
            ["RECEIPT OF GOODS", f"note {g['reference'] or 'none'}", f"verdict {ids.VERDICT_WORDS.get(g['verdict'], g['verdict'])}", f"evaluator {g['evaluator']}",
             f"assurance {g['assurance']}", f"evidence {g['evidence']}"],
            ["INVOICE LINE", f"id {i['id']}", f"line {i['line']} {i['reference']}".rstrip(), f"amount {i['amount'] or 'not priced'} {i['currency']}".rstrip(),
             f"state {ids.LINE_WORDS[i['state']]}", f"payment {PAY_WORDS[i['payment']]}"]]
    cut = lambda text: text if len(text) <= 38 else text[:35] + "..."                # noqa: E731
    rows = [" | ".join(f"{cut(leg[n]) if n < len(leg) else '':<38}" for leg in legs).rstrip() for n in range(max(len(leg) for leg in legs))]
    return [f"Goods-received note {note['reference'] or '(no evaluation on record)'}, statement sha256 {note['statement'][:16]}..."
            + (f", recorded {note['recorded']}" if note.get("recorded") else ""), *rows,
            *(["Still trusted at this assurance level:", *(f"  - {t}" for t in g["trusted"])] if g["trusted"] else []),
            "MATCH" if note["match"] else "MISMATCH", *(f"  - {w}" for w in note["mismatches"])]


# ---- the three forms ------------------------------------------------------------------------------------------------

def cells(st: dict, status: dict | None = None) -> dict:
    """Everything the CSV and the PDF say, as text, in one place: {"top": [[name, value]], "head", "rows", "totals":
    [[state, lines, amount]], "answers": [[question, answer]], "events": [[...]]}. Both forms are written from this."""
    status = _status(st, status)
    ev = st["evidence"]
    top = [["invoice", st["invoice"]], ["date", st["date"]], ["supplier", st["supplier"]], ["buyer", st["buyer"]], ["currency", st["currency"]],
           ["made from", {"shadow": "a shadow run: the invoice against GitHub's record", "month": "a closed month of the meter",
                         "events": "a log of events: every recording mode's records, each counted once"}[st["source"]]],
           ["evidence sha256", ev["sha256"]],
           ["evidence", ("inside the statement" if ev["embedded"] is not None else "in a file beside the statement") + "; "
            + (f"signed through GitHub by the {' and the '.join(ev['signed'])}" if ev["signed"] else "not signed")],
           ["status sha256", sha(canonical(status)) if status["events"] else "none recorded"]]
    rows = [[str(r["line"]), r["reference"], r["supplier"], ids.LINE_WORDS[r["state"]], r["amount"], r["why"], r["deliverable"], " ".join(r["evaluations"]),
             r["invoice_line"], r["settlement"] or "", PAY_WORDS[r["payment"]], r["evidence"], r["evidence_sha256"], r["duplicate_of"],
             r["assurance"], r["po_reference"], r["grn_reference"]]
            for r in lines_now(st, status)]
    totals = [[name if name == "billed" else ids.LINE_WORDS[name], str(st["totals"][name]["lines"]), st["totals"][name]["amount"]]
              for name in ("billed", *ids.LINE_STATES)]
    events = [["approval", e["on"], f"{e['by']} ({e['role']})", f"{len(e['lines'])} agreed lines", e["amount"]] if e["type"] == "approval" else
              ["goods-received note", e["on"], e["line"], grn_said(e["grn"]), e["grn"]["reference"]] if e["type"] == "grn" else
              ["settlement", e["on"], e["line"], f"{PAY_WORDS[e['state']]} by {e['method']}, reference {e['reference']}", e["settlement"]]
              for e in status["events"]]
    return {"top": top, "head": list(HEAD), "rows": rows, "totals": totals, "answers": [list(a) for a in answers(st, status)], "events": events}


def _cell(text: str) -> str:
    """One CSV cell. Text a spreadsheet would run as a formula gets a quote in front; a plain number does not."""
    return shadow._cell(text, not re.fullmatch(r"-?\d+(\.\d+)?", text))


def as_csv(st: dict, status: dict | None = None) -> str:
    """The CSV: the statement's kind, version and sha256 first, then what it is of, the lines under their header, the
    totals, the answers and what the status file records. A cell a spreadsheet would run as a formula gets a quote."""
    c = cells(st, status)
    out = [[KIND, str(VERSION), st["sha256"]], *c["top"], c["head"], *c["rows"], *(["total", *t] for t in c["totals"]),
           *(["answer", *a] for a in c["answers"]), *c["events"], ["note", st["note"]]]
    return "".join(",".join(_cell(cell) for cell in row) + "\n" for row in out)


def as_pdf(st: dict, status: dict | None = None) -> bytes:
    """The PDF: the same cells on paper, wide, with the statement's sha256 at the foot of every page."""
    c = cells(st, status)
    doc = pdf.Doc(f"Statement for invoice {st['invoice']}", created=st["date"], footer=f"Knos statement sha256 {st['sha256']}")
    doc.text(f"Statement for invoice {st['invoice']}", size=15, bold=True)
    doc.text("Each line of the invoice set against the evidence. Nothing here moves money.", size=8)
    doc.space(6)
    doc.table(["", ""], c["top"], [1, 5], size=7.5)
    doc.space(10)
    doc.text("What this statement answers", size=10, bold=True)
    doc.space(2)
    doc.table(["question", "answer"], c["answers"], [1, 5], size=7.5)
    doc.space(10)
    doc.text("Totals", size=10, bold=True)
    doc.space(2)
    doc.table(["state", "lines", "amount"], c["totals"], [2, 1, 3], size=7.5)
    doc.space(10)
    doc.text("Lines", size=10, bold=True)
    doc.space(2)
    doc.table(["line", "reference", "supplier", "state", "amount", "why", "ids: deliverable, evaluations, invoice line, settlement, purchase order, note",
               "payment, assurance", "evidence and its sha256", "duplicate of"],
              [[r[0], r[1], r[2], r[3], r[4], r[5], "\n".join(x for x in (r[6], *r[7].split(" "), r[8], r[9], r[15], r[16]) if x), f"{r[10]}\n{r[14]}",
                "\n".join(x for x in (r[11], r[12]) if x), r[13]] for r in c["rows"]],
              [22, 104, 50, 52, 42, 128, 118, 48, 150, 56], size=6.5)
    if c["events"]:
        doc.space(10)
        doc.text("Approvals and payment status", size=10, bold=True)
        doc.space(2)
        doc.table(["record", "on", "who or which line", "what", "amount or settlement id"], c["events"], [1, 1, 2.6, 4, 2.6], size=7)
    doc.space(8)
    doc.text(st["note"], size=7.5)
    return doc.render()


def write(st: dict, out: Path, status: dict | None = None, name: str = NAME) -> list[Path]:
    """<name>.json (only when it is not there yet: a statement is never rewritten), <name>.csv and <name>.pdf in `out`."""
    out.mkdir(parents=True, exist_ok=True)
    files = [(out / f"{name}.json", canonical(st)), (out / f"{name}.csv", as_csv(st, status).encode("utf-8", "surrogatepass")),
             (out / f"{name}.pdf", as_pdf(st, status))]
    for path, data in files:
        path.write_bytes(data)
    return [path for path, _ in files]


# ---- made again, years later ----------------------------------------------------------------------------------------

def verify(st: dict, bundle: bytes | None = None) -> tuple[bool, str]:
    """(True, "same") when the statement made again from its evidence is this statement; else (False, what differs
    first). `bundle`: the evidence file's bytes, for a statement that references its evidence. No network, no chain."""
    if not isinstance(st, dict) or st.get("kind") != KIND or st.get("version") != VERSION:
        raise Refused("This is not a Knos statement of this version.")
    if digest(st) != st.get("sha256"):
        return False, "differs: the statement is not the one its own sha256 names; it was changed after it was made"
    ev = st["evidence"]
    if ev["embedded"] is None and bundle is None:
        raise Refused(f"The statement references its evidence (sha256 {ev['sha256']}) and does not hold it. Give the file: --bundle.")
    try:
        if ev["embedded"] is not None:
            data = canonical(ev["embedded"]) if st["source"] == "shadow" else base64.b64decode(ev["embedded"], validate=True)
        else:
            data = canonical(json.loads((bundle or b"").decode("utf-8-sig"))) if st["source"] == "shadow" else bundle or b""
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return False, "differs: the evidence cannot be read"
    if sha(data) != ev["sha256"]:
        return False, "differs: the evidence is not the evidence the statement names (its sha256 is another)"
    meta = {k: st[k] for k in ("invoice", "supplier", "buyer", "currency", "date")}
    try:
        again = make(data, meta, st["prior"], ev["embedded"] is not None)
    except Refused as why:
        return False, f"differs: the statement cannot be made again from its evidence: {why}"
    for name, got in sorted(again["evidence"]["items"].items()):
        if ev["items"].get(name) != got:
            return False, f"differs: the evidence item {name} is not the one the statement names"
    for old, new in zip(st["lines"], again["lines"]):
        if old != new:
            key = next(k for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k))
            return False, f"differs: line {old.get('line')}: {key} is {old.get(key)!r} in the statement and {new.get(key)!r} from the evidence"
    if len(st["lines"]) != len(again["lines"]):
        return False, f"differs: the statement has {len(st['lines'])} lines and the evidence gives {len(again['lines'])}"
    for key in sorted(set(st) | set(again)):
        if st.get(key) != again.get(key):
            return False, f"differs: {key} is not what the evidence gives"
    return True, "same"


# ---- the commands ---------------------------------------------------------------------------------------------------

def _beside(path: Path) -> Path:
    return path.with_name(path.name[:-5] + ".status.json" if path.name.endswith(".json") else path.name + ".status.json")


def load(path: Path) -> tuple[dict, dict | None]:
    """(the statement, its status file's content or None)."""
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
        beside = _beside(path)
        status = json.loads(beside.read_text(encoding="utf-8")) if beside.is_file() else None
    except (OSError, ValueError) as why:
        raise Refused(f"{path} could not be read: {why}") from None
    if not isinstance(st, dict) or st.get("kind") != KIND:
        raise Refused(f"{path} is not a Knos statement. `knos statement make` writes one.")
    if digest(st) != st.get("sha256"):
        raise Refused(f"{path} was changed after it was made: its sha256 is not its own. Run `knos statement verify` on a copy you trust.")
    return st, status


def register(app, help_lines: list | None = None) -> None:
    """`knos statement make | approve | pay | grn | show | export | verify`, on the main app. `help_lines`: cli._HELP."""
    import datetime

    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    sub = typer.Typer(add_completion=False, no_args_is_help=True,
                      help="The statement for accounts payable: every invoice line agreed, disputed, duplicate or without enough evidence, as JSON, CSV and PDF.")
    app.add_typer(sub, name="statement")
    if help_lines is not None:
        help_lines.append(("statement", "For money", "An invoice's statement for accounts payable: JSON, CSV and PDF; approve, record payment, verify."))
    file_arg = typer.Argument(..., help="the statement's JSON file")
    on_opt = typer.Option("", "--on", help="the day, YYYY-MM-DD (today when left out)")

    def stop(why: Exception):
        from . import cli
        return cli.Stop(str(why))

    def today(on: str) -> str:
        return on or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    def say(st: dict, status: dict | None) -> None:
        for question, answer in answers(st, status):
            typer.echo(f"{question + ':':<23}{answer}")

    def save(path: Path, st: dict, status: dict) -> None:
        _beside(path).write_bytes(canonical(status))
        name = path.name[:-5] if path.name.endswith(".json") else path.name
        (path.parent / f"{name}.csv").write_bytes(as_csv(st, status).encode("utf-8", "surrogatepass"))
        (path.parent / f"{name}.pdf").write_bytes(as_pdf(st, status))
        typer.echo(f"wrote {_beside(path)}; {name}.csv and {name}.pdf now show it. The statement itself is unchanged (sha256 {st['sha256']}).")

    @sub.command("make")
    def make_(evidence: Path = typer.Argument(..., help="evidence.json of `knos shadow --out`, a month's archive of `knos meter export --bundle`, or a log of `knos events`"),
              out: Path = typer.Option(None, "--out", help="the folder to write ap-statement.json, .csv and .pdf in (beside the evidence when left out)"),
              prior: list[Path] = typer.Option([], "--prior", help="an earlier statement's JSON: a deliverable it agreed is a duplicate here (repeat for more)"),
              invoice: str = typer.Option("", "--invoice", help="the supplier's invoice number"),
              supplier: str = typer.Option("", "--supplier", help="the supplier's name, when the invoice does not say"),
              buyer: str = typer.Option("", "--buyer", help="the buyer's name"),
              currency: str = typer.Option("", "--currency", help="what the amounts are in, for example USD or test USDC"),
              date: str = typer.Option("", "--date", help="the statement's day, YYYY-MM-DD (the last merge's day, or the month's last day, when left out)"),
              reference: bool = typer.Option(False, "--reference", help="keep the evidence in its own file and name it by sha256, instead of inside the statement"),
              name: str = typer.Option(NAME, "--name", help="the files' name")) -> None:
        """Make one statement in three forms that say the same: JSON (the statement itself), CSV and PDF. Each line of the invoice is agreed, disputed, a duplicate, or has insufficient evidence, with why in plain words, its ids and where its evidence is. It reads the evidence file and nothing else: no network, no chain. Nothing is paid."""
        try:
            data = evidence.read_bytes()
            before = [billed_before(json.loads(p.read_text(encoding="utf-8"))) for p in prior]
            st = make(data, {"invoice": invoice, "supplier": supplier, "buyer": buyer, "currency": currency, "date": date}, before, not reference)
        except (OSError, ValueError) as why:
            raise stop(why) from None
        files = write(st, out or evidence.parent, None, name)
        t = st["totals"]
        typer.echo(f"Statement for invoice {st['invoice']}: {t['billed']['lines']} lines" + (f", {t['billed']['amount']}" if t["billed"]["amount"] else ""))
        for state in ids.LINE_STATES:
            typer.echo(f"  {ids.LINE_WORDS[state]:<24}{t[state]['lines']:>5}{t[state]['amount']:>16}")
        typer.echo(f"sha256 {st['sha256']}")
        typer.echo("wrote " + ", ".join(str(f) for f in files))
        if reference:
            whole = make(data, {k: st[k] for k in ("invoice", "supplier", "buyer", "currency", "date")}, before)["evidence"]["embedded"]
            kept = (out or evidence.parent) / f"{name}.evidence.{ {'shadow': 'json', 'events': 'jsonl'}.get(st['source'], 'tar')}"
            kept.write_bytes(canonical(whole) if st["source"] == "shadow" else data)
            typer.echo(f"The evidence is in {kept} (sha256 {st['evidence']['sha256']}): keep it with the statement; `verify` needs it as --bundle.")

    @sub.command("approve")
    def approve_(file: Path = file_arg, agreed: bool = typer.Option(False, "--agreed", help="approve the agreed lines; the others stay open"),
                 by: str = typer.Option(..., "--by", help="who approves"), role: str = typer.Option(..., "--role", help="in which role, as they state it"),
                 on: str = on_opt) -> None:
        """Record who approved the agreed lines. Disputed and duplicate lines, and lines without enough evidence, stay open: nothing approves them here. The approval is appended to the status file beside the statement; the statement does not change, and nothing is paid."""
        if not agreed:
            raise stop(Refused("Say what is approved: --agreed approves the agreed lines and leaves every exception open. Nothing else can be approved here."))
        try:
            st, status = load(file)
            status = approve(st, status, by, role, today(on))
        except Refused as why:
            raise stop(why) from None
        save(file, st, status)
        say(st, status)

    @sub.command("pay")
    def pay_(file: Path = file_arg, line: str = typer.Option(..., "--line", help="the invoice line's id (inv_...)"),
             method: str = typer.Option("bank", "--method", help="bank, chain or other"),
             ref: str = typer.Option(..., "--ref", help="the payer's own reference, or the transaction"),
             on: str = on_opt, state: str = typer.Option("", "--state", help="payable, paid outside Knos, held, refunded or devnet demonstration"),
             receipt: Path = typer.Option(None, "--receipt", help="with --method chain: the payment's acceptance receipt (JSON); a quorum of one controller is then said on the line")) -> None:
        """Record the payment status of one line that was paid, held or refunded outside Knos. It appends a settlement record with an id of its own to the status file. It moves no money and checks no bank: it writes down what the payer says, with the payer's reference."""
        try:
            st, status = load(file)
            try:
                held = json.loads(receipt.read_text(encoding="utf-8")) if receipt else None
            except (OSError, ValueError):
                raise Refused(f"Cannot read {receipt} as a receipt's JSON.") from None
            status = pay(st, status, line, method, ref, today(on), state, held)
        except Refused as why:
            raise stop(why) from None
        last = status["events"][-1]
        typer.echo(f"recorded {last['settlement']}: line {line} is {PAY_WORDS[last['state']]} ({method}, reference {last['reference']}, {last['on']}). No money moved.")
        save(file, st, status)

    @sub.command("grn")
    def grn_(file: Path = file_arg, line: str = typer.Option(..., "--line", help="the invoice line's id (inv_...)"),
             receipt: Path = typer.Option(None, "--receipt", help="the acceptance receipt of the line's payment (JSON): the purchase order and the acceptance are read from it"),
             po: str = typer.Option("", "--po", help="the buyer's own purchase order number (the order's address when left out)"),
             record: bool = typer.Option(False, "--record", help="append this note to the status file: the line's exports then carry its PO, note and assurance level"),
             on: str = on_opt, as_json: bool = typer.Option(False, "--json", help="print the note as JSON")) -> None:
        """Show the goods-received note of one line: the purchase order, the receipt of goods (the acceptance, with its assurance level and evidence) and the invoice line side by side, then "MATCH" or each mismatch. This is the three-way match accounts payable performs. It reads; it moves and approves nothing. Exit code 1 on a mismatch."""
        try:
            st, status = load(file)
            try:
                held = json.loads(receipt.read_text(encoding="utf-8")) if receipt else None
            except (OSError, ValueError):
                raise Refused(f"Cannot read {receipt} as a receipt's JSON.") from None
            if record and held is None:
                raise Refused("--record keeps a note made from the payment's receipt: give --receipt.")
            kept = grn_record(st, status, line, today(on), held, po) if record and held is not None else None
            note = grn(st, kept or status, line, None if kept else held, po)
        except Refused as why:
            raise stop(why) from None
        typer.echo(canonical(note).decode() if as_json else "\n".join(grn_lines(note)), nl=not as_json)
        if kept:
            save(file, st, kept)
        if not note["match"]:
            raise typer.Exit(1)

    @sub.command("show")
    def show_(file: Path = file_arg, as_json: bool = typer.Option(False, "--json", help="print the lines with their status as JSON")) -> None:
        """Answer what an approver asks: what was authorised, billed, delivered and passed, what was already billed, who approved, what is disputed, credited, paid and owed."""
        try:
            st, status = load(file)
            if as_json:
                typer.echo(canonical({"statement": st["sha256"], "lines": lines_now(st, status), "answers": [list(a) for a in answers(st, status)]}).decode(), nl=False)
                return
            say(st, status)
            for r in lines_now(st, status):
                if r["state"] != "agreed":
                    typer.echo(f"  line {r['line']} {r['reference'] or '(no reference)'}: {ids.LINE_WORDS[r['state']]}: {r['why']}")
        except Refused as why:
            raise stop(why) from None

    @sub.command("export")
    def export_(file: Path = file_arg, fmt: str = typer.Option(..., "--format", help="quickbooks, netsuite or generic"),
                out: Path = typer.Option(None, "--out", help="write the file here and not to standard output"),
                account: str = typer.Option("", "--account", help="the expense account every bill is booked to"),
                tax_code: str = typer.Option("", "--tax-code", help="QuickBooks' Line Tax Code"),
                date_format: str = typer.Option("", "--date-format", help="another date format than the product's default, written with YYYY, MM, DD, M and D")) -> None:
        """Write the statement as a file an accounting system imports. QuickBooks Online and NetSuite get one bill per agreed line, with the line's state, payment status and ids in the memo; a line that is disputed, duplicate or without enough evidence is never a bill. The generic file lists every line. Each is a file export, not an integration: nobody has imported one into the product yet."""
        from . import audit, exports
        try:
            st, status = load(file)
            text = exports.write_statement(fmt, st, status, {"account": account, "tax_code": tax_code, "date_format": date_format})
        except (Refused, audit.Refused) as why:
            raise stop(why) from None
        typer.echo(f"{exports.FORMATS[fmt]['name']}: {exports.label(fmt)}." + (f" Unverified: {exports.FORMATS[fmt]['unverified']}." if exports.FORMATS[fmt]["unverified"] else ""), err=True)
        if out:
            out.write_bytes(text.encode("utf-8"))
            typer.echo(f"wrote {out}", err=True)
        else:
            typer.echo(text, nl=False)

    @sub.command("verify")
    def verify_(file: Path = file_arg,
                bundle: Path = typer.Option(None, "--bundle", help="the evidence file, for a statement that references its evidence")) -> None:
        """Make the statement again from the evidence it holds or names, and say "same" or the first line that differs. For a month's archive GitHub's signatures are checked with the keys in the archive. No network and no chain are asked."""
        try:
            st = json.loads(file.read_text(encoding="utf-8"))
            ok, said = verify(st, bundle.read_bytes() if bundle else None)
        except (OSError, ValueError) as why:
            raise stop(why) from None
        typer.echo(said)
        if not ok:
            raise typer.Exit(1)
        beside = _beside(file)
        name = file.name[:-5] if file.name.endswith(".json") else file.name
        status = json.loads(beside.read_text(encoding="utf-8")) if beside.is_file() else None
        for path, want in ((file.parent / f"{name}.csv", as_csv(st, status).encode("utf-8", "surrogatepass")), (file.parent / f"{name}.pdf", as_pdf(st, status))):
            if path.is_file():
                same = path.read_bytes() == want
                typer.echo(f"{path.name}: {'same' if same else 'differs from what the statement and its status give'}")
                if not same:
                    raise typer.Exit(1)
