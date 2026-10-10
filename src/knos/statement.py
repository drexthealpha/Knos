"""The statement a person who approves invoices attaches in their accounts-payable system: `knos statement`.

    knos statement make <evidence>      one statement as JSON (canonical), CSV and PDF
    knos statement accept <file> --by NAME --role ROLE    a party accepts the lines whose policy is met
    knos statement refuse <file> --line inv_... --by NAME --role ROLE --why TEXT
    knos statement approve <file> --agreed --by NAME --role ROLE      authorises payment of those lines
    knos statement pay <file> --line inv_... --method bank --ref REF --on DATE
    knos statement pay <file> --rail bank --payer-name N --payer-account IBAN --payees payees.csv
                                        a payment file for the payer's own bank (ISO 20022 pain.001): the approved lines whose policy is met
    knos statement status <file> --from <the bank's status report>     marks the lines of each transfer paid, or payable again
    knos statement complete <file> --sources sources.json
                                        the statement against the orders the chain paid and the GitHub sources its lines
                                        name: deleted, omitted, late and duplicated, each an exception (knos.completeness)
    knos statement grn <file> --line inv_...   the goods-received note of one line: order, acceptance and invoice line, matched
    knos statement show <file>          what was authorised, delivered, passed, already billed, approved, disputed, owed
    knos statement export <file> --format quickbooks|netsuite|generic|match|ariba
    knos statement verify <file>        make it again from its evidence: "same", or the first line that differs

It is made from one of two things, and only from them:

    a shadow run     `evidence.json` as `knos shadow --out` writes it: the supplier's invoice and every answer GitHub
                     gave about its lines. GitHub does not sign those answers; the statement says so.
    a closed month   the archive `knos meter export --bundle` writes: both ledgers, the close record and each party's
                     token, signed by GitHub. Its signatures are checked here with the keys in the archive; neither
                     the chain nor the network is asked.

Each invoice line carries the four ids of knos.ids (deliverable, evaluations, invoice line, and a settlement once one
is recorded), one state of ids.LINE_STATES, its amount, why (for a line that is not agreed, in plain words) and where
its evidence is. The state `agreed` is the file's key for "policy met": the evidence met the terms, nothing more.
Every line has four steps, each recorded apart (ids.STEPS, `steps_of`): policy satisfied, parties accepted (who,
when), payment authorised (by whom, under which policy) and settled (the transaction or the bank's reference). A
line whose policy is met that the buyer refused, or left unauthorised past the acceptance window, is owed to the
supplier: a wrongful refusal, counted beside the unsupported charges, with the supplier's appeal.

A deliverable that an earlier statement agreed (`--prior`) is a duplicate here: already billed.

The JSON is the statement. It holds its own SHA-256 (of its canonical bytes with that one field empty) and the
SHA-256 of every piece of evidence, and the evidence itself unless `--reference` kept it in a file beside. The CSV and
the PDF are written from `cells`, so they say the same thing in the same words, and both carry the JSON's hash.

Approvals and payment status are appended to `<name>.status.json`, never to the statement: the statement does not
change after it is made. Nothing here moves money. A payment made by bank is recorded with the payer's own reference, or
through the payment file and the bank's answer to it (knos.rails; docs/RAILS.md).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import re
from pathlib import Path

from . import assurance as _assure
from . import ids, pdf, shadow
from . import ledger as L

KIND, VERSION = "knos-statement", 1
NAME = "ap-statement"                            # the files: ap-statement.json, .csv, .pdf and .status.json (statement.json is the shadow run's own)
STATUS_KIND = "knos-statement-status"
POLICY_SHADOW = "github-checks-at-merge.v1"       # what shadow mode evaluates a line by: the checks at the merged commit
PAY_STATES = ("payable", "paid_outside", "held", "refunded", "devnet_demonstration")
ACCEPT_DAYS = 30                                  # the acceptance window when none is given: days after the statement's day
APPROVE_POLICY = "knos statement approve: lines whose policy is met, not refused"     # the policy an approval authorises under
PAID = ("paid_outside", "devnet_demonstration")
PAY_WORDS = {"payable": "payable", "paid_outside": "paid outside Knos", "held": "held", "refunded": "refunded",
             "devnet_demonstration": "devnet demonstration", "unknown": "held as unknown"}     # unknown: the bank's answer was not clear (knos.rails)
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
    """The status with one more approval: `by`, in `role`, authorises payment of every line whose policy is met that nobody approved or refused yet. The lines
    that are disputed, duplicate or without enough evidence stay open. The role is recorded as it was stated."""
    status = _status(st, status)
    if not by.strip() or not role.strip():
        raise Refused("An approval names who approved and in which role: --by and --role.")
    done = {i for e in status["events"] if e["type"] == "approval" for i in e["lines"]} | refused_lines(status)
    mine = [ln for ln in st["lines"] if ln["state"] == "agreed" and ln["invoice_line"] not in done]
    if not mine:
        raise Refused("There is no line left to approve whose policy is met." if done else "No line of this statement meets its policy, so there is nothing to approve.")
    event = {"type": "approval", "scope": "agreed", "by": by.strip(), "role": role.strip(), "on": _day(on), "lines": [ln["invoice_line"] for ln in mine],
             "amount": amount_of(sum(units(ln["amount"], st["scale"]) for ln in mine), st["scale"])}
    return {**status, "events": [*status["events"], event]}


def _decided(status: dict) -> dict[str, dict]:
    """The last acceptance or refusal recorded for each invoice line: {invoice line: event}."""
    out: dict[str, dict] = {}
    for e in status["events"]:
        if e["type"] in ("acceptance", "refusal"):
            for line in e["lines"]:
                out[line] = e
    return out


def refused_lines(status: dict | None) -> set[str]:
    """The invoice lines whose last decision is a refusal."""
    return {line for line, e in _decided(status or {"events": []}).items() if e["type"] == "refusal"}


def accept(st: dict, status: dict | None, by: str, role: str, on: str, lines: list[str] | tuple = ()) -> dict:
    """The status with one more acceptance: `by`, in `role`, accepts `lines` (invoice line ids), or every line whose
    policy is met that nobody accepted or refused yet. This is the parties' acceptance, and only that: it authorises
    no payment (`approve` does) and pays nothing."""
    status = _status(st, status)
    if not by.strip() or not role.strip():
        raise Refused("An acceptance names who accepted and in which role: --by and --role.")
    known, decided = {ln["invoice_line"]: ln for ln in st["lines"]}, _decided(status)
    for line in lines:
        if line not in known:
            raise Refused(f"No line of this statement has the id {line}. The ids are in the invoice_line column.")
    mine = list(lines) or [ln["invoice_line"] for ln in st["lines"] if ln["state"] == "agreed" and ln["invoice_line"] not in decided]
    if not mine:
        raise Refused("There is no line left to accept whose policy is met.")
    return {**status, "events": [*status["events"], {"type": "acceptance", "by": by.strip(), "role": role.strip(), "on": _day(on), "lines": mine}]}


def refuse(st: dict, status: dict | None, line: str, by: str, role: str, on: str, why: str) -> dict:
    """The status with one more refusal: `by`, in `role`, refuses the invoice line `line`, for `why`. A refused line
    whose policy is met is owed to the supplier all the same (`steps_of`): the refusal is recorded, never hidden."""
    status = _status(st, status)
    if not by.strip() or not role.strip() or not why.strip():
        raise Refused("A refusal names who refused, in which role and why: --by, --role and --why.")
    if line not in {ln["invoice_line"] for ln in st["lines"]}:
        raise Refused(f"No line of this statement has the id {line}. The ids are in the invoice_line column.")
    return {**status, "events": [*status["events"], {"type": "refusal", "by": by.strip(), "role": role.strip(), "on": _day(on), "lines": [line],
                                                     "why": " ".join(why.split())[:300]}]}


def _days(a: str, b: str) -> int:
    import datetime
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def steps_of(st: dict, ln: dict, events: list[dict], today: str = "", window: int = ACCEPT_DAYS) -> tuple[list[dict], bool]:
    """The four steps of one line (ids.STEPS), each {"step", "state": done | open | failed, "said"}, and whether the
    line is owed to the supplier: its policy is met, it is not paid, and it was refused, or nobody authorised it and
    `today` is more than `window` days after the statement's day. Read from the statement and its status events."""
    line = ln["invoice_line"]
    met = ln["state"] == "agreed"
    policy = {"step": "policy", "state": "done" if met else "open" if ln["state"] == "insufficient_evidence" else "failed",
              "said": f"under {RULE[st['source']]}" if met else f"{ids.LINE_WORDS[ln['state']]}" + (f": {ln['why']}" if ln["why"] else "")}
    last = None
    for e in events:
        if e["type"] in ("acceptance", "refusal") and line in e["lines"]:
            last = e
    if last and last["type"] == "refusal":
        accepted = {"step": "accepted", "state": "failed", "said": f"refused by {last['by']} ({last['role']}) on {last['on']}: {last['why']}"}
    elif last:
        accepted = {"step": "accepted", "state": "done", "said": f"by {last['by']} ({last['role']}) on {last['on']}"}
    elif st["source"] == "month" and met:
        accepted = {"step": "accepted", "state": "done", "said": f"by the buyer and the supplier: both ledgers, month closed {st['date']}"}
    else:
        accepted = {"step": "accepted", "state": "open", "said": "nobody yet"}
    ok = next((e for e in events if e["type"] == "approval" and line in e["lines"]), None)
    authorised = ({"step": "authorised", "state": "done", "said": f"by {ok['by']} ({ok['role']}) on {ok['on']}, under {APPROVE_POLICY}"} if ok
                  else {"step": "authorised", "state": "open", "said": "nobody yet"})
    paid = [e for e in events if e["type"] == "settlement" and e["line"] == line]
    end = paid[-1] if paid else None
    slot = f", slot {end['chain']['slot']}" if end and isinstance(end.get("chain"), dict) else ""
    settled = ({"step": "settled", "state": "done", "said": f"{PAY_WORDS[end['state']]} by {end['method']}, reference {end['reference']}{slot}, on {end['on']}"}
               if end and end["state"] in PAID else
               {"step": "settled", "state": "failed" if end and end["state"] == "refunded" else "open",
                "said": f"{PAY_WORDS[end['state']]}, reference {end['reference']}" if end else "not paid"})
    late = bool(today) and not ok and _days(st["date"], today) > window
    owed = met and settled["state"] != "done" and (accepted["state"] == "failed" or late)
    return [policy, accepted, authorised, settled], owed


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


def pay(st: dict, status: dict | None, line: str, method: str, reference: str, on: str, state: str = "", receipt: dict | None = None,
        terms_doc: dict | None = None) -> dict:
    """The status with one more settlement record for the invoice line `line`. `method`: bank, chain or other; `state`:
    one of PAY_STATES (a bank payment is "paid outside Knos" unless said otherwise). It records; it moves nothing.
    `receipt`: the acceptance receipt of a payment made on chain (its transaction is the reference). When the quorum
    it records was of evaluators that share a controller, the record carries that in a `note`, and the line says it.
    `terms_doc`: the Knos Terms 3 document of the order. When it requires a minimum assurance level (`checks.min_assurance`)
    a payment below it is refused: the level is the receipt's (`receipt`), else the one the line says."""
    status = _status(st, status)
    ln = next((x for x in st["lines"] if x["invoice_line"] == line), None)
    if ln is None:
        raise Refused(f"No line of this statement has the id {line}. The ids are in the invoice_line column.")
    if method not in METHODS:
        raise Refused(f"--method is one of {', '.join(METHODS)}; {method!r} is none of them.")
    state = (state or METHODS[method]).strip().lower().replace(" ", "_")
    state = {"paid_outside_knos": "paid_outside"}.get(state, state)
    if state not in PAY_STATES:
        raise Refused(f"--state is one of: {', '.join(PAY_WORDS[s] for s in PAY_STATES)}.")
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
    if terms_doc is not None and state in ("paid_outside", "devnet_demonstration"):
        from . import receipt as rc
        from . import terms3
        level = (rc.assurance_of(receipt, receipt["assurance"]["declared_related"] if receipt["version"] == 5 else terms3.declared(terms_doc))["level"]
                 if receipt is not None else next(x["assurance"] for x in lines_now(st, status) if x["invoice_line"] == line))
        try:
            refused = terms3.payment_refusal(terms_doc, level)
        except terms3.Refused as why:
            raise Refused(f"--terms-file is not a Knos Terms 3 document: {why}") from None
        if refused:
            raise Refused(refused)
    return {**status, "events": [*status["events"], event]}


TX_REF = re.compile(r"tx:([1-9A-HJ-NP-Za-km-z]{64,90})")       # a line whose evidence is a transaction (knos.events.from_audit, the witness)


def chain_payment(tx: dict | None, ln: dict, scale: int, order: str = "") -> tuple[dict | None, str]:
    """What a confirmed transaction (getTransaction's JSON) paid for the statement line `ln`, read from knos_pay's own
    log lines (knos.records.events_of): ({signature, slot, on, amount, fee, order, payee, to}, "") when it paid the
    line's amount to the line's supplier (and, given `order`, from that order); (None, why) otherwise."""
    from . import records
    if not isinstance(tx, dict):
        return None, "the cluster did not give the transaction"
    if (tx.get("meta") or {}).get("err") is not None:
        return None, "the transaction failed on chain"
    got = records.events_of(tx)
    want, who = units(ln.get("amount"), scale), str(ln.get("supplier") or "")
    paid = [e for e in got if e["event"] in ("order_paid", "paid")]
    if not paid:
        return None, "the transaction paid nothing through knos_pay"
    if order:
        paid = [e for e in paid if str(e.get("order") or "") == order]
        if not paid:
            return None, f"the transaction paid no one from the order {order}"
    if who.isdigit():
        paid = [e for e in paid if str(e.get("payee")) == who]
        if not paid:
            return None, f"the transaction paid someone other than the line's supplier {who}"
    hit = next((e for e in paid if int(e.get("amount") or 0) == want), None)
    if hit is None:
        return None, f"the transaction paid {amount_of(int(paid[0].get('amount') or 0), scale)}, and the line says {ln.get('amount')}"
    end = next((e for e in got if e["event"] == "order_settled" and e.get("order") == hit.get("order")), None)
    fee = int(end.get("fee") or 0) + int(end.get("tip") or 0) if end else int(hit.get("fee") or 0)
    sig = str(((tx.get("transaction") or {}).get("signatures") or [""])[0])
    import datetime
    on = datetime.datetime.fromtimestamp(int(tx.get("blockTime") or 0), datetime.timezone.utc).strftime("%Y-%m-%d")
    return ({"signature": sig, "slot": int(tx.get("slot") or 0), "on": on, "amount": amount_of(want, scale), "fee": amount_of(fee, scale),
             "order": str(hit.get("order") or ""), "payee": str(hit.get("payee") or ""), "to": str(hit.get("to") or "")}, "")


def settle_sync(st: dict, status: dict | None, read, find=None, order: str = "", final=None) -> tuple[dict, list[tuple[str, str]]]:
    """Close the "settled" step of every line the chain paid: the status with one settlement record (method chain,
    devnet demonstration) per such line, carrying the transaction as `chain` (signature, slot, amount, fee, order,
    payee), and what was done for each line [(invoice line, words)]. The transaction is the one the line's evidence
    names (`tx:<signature>`), else, given `order` and `find(order)` (its signatures, newest first), the first of them
    that paid the line. `read(signature)` gives getTransaction's JSON, or None. Each payment is checked against the
    line (amount, supplier, order) before it is written; a line already recorded settled is left as it is. Nothing moves.
    `final(signature)`: the cluster's confirmation status of it (processed, confirmed, finalized, or None when the
    cluster does not know it). Given, a payment is booked only once it is finalized: one seen only as processed or
    confirmed is said and left for a later run, and one the cluster dropped is never booked (knos.completeness)."""
    status = _status(st, status)
    said: list[tuple[str, str]] = []
    for ln in st["lines"]:
        line = ln["invoice_line"]
        if ln["state"] != "agreed":
            continue
        steps, _owed = steps_of(st, ln, status["events"])
        if steps[3]["state"] == "done":
            said.append((line, "already settled"))
            continue
        named = TX_REF.fullmatch(str(ln.get("reference") or ""))
        sigs = [named.group(1)] if named else list(find(order) if find and order else [])
        why = "its evidence names no transaction (give --order)" if not sigs else ""
        for sig in sigs:
            got, why = chain_payment(read(sig), ln, st["scale"], order)
            if got is None:
                continue
            seen = final(got["signature"] or sig) if final is not None else None
            if final is not None and seen != "finalized":
                why = f"{got['signature'] or sig} is {seen or 'not known to the cluster'}, not finalized: it is booked once it is"
                break
            status = pay(st, status, line, "chain", got["signature"] or sig, got["on"], "devnet_demonstration")
            status["events"][-1]["chain"] = {**got, "commitment": seen} if seen else got
            said.append((line, f"settled by {got['signature'] or sig} in slot {got['slot']}: {got['amount']} to {got['payee']}, fee {got['fee']}"))
            break
        else:
            said.append((line, f"not settled: {why}"))
            continue
        if not said or said[-1][0] != line:
            said.append((line, f"not settled: {why}"))
    return status, said


def grn_reference(ln: dict) -> str:
    """The reference of a line's goods-received note: the id of the first evaluation that stands behind it, as a note's
    (`grn_` and the same 24 hex characters). Empty for a line nothing evaluated: no goods were received on record."""
    return "grn_" + ln["evaluations"][0].split("_", 1)[1] if ln["evaluations"] else ""


FIVE = ("identity", "execution", "acceptance", "consequence", "assurance")      # knos.receipt.FIVE: the five parts, in this order
IDENTITY = {"shadow": "GitHub's answers about this line's pull request, as they were read: GitHub does not sign them.",
            "month": "GitHub signed the month's close record (the tokens in the archive); the meter's two ledgers name the evaluations.",
            "events": "The log of events, its chain of hashes checked; the evidence each event names was not read again."}
RULE = {"shadow": f"the policy {POLICY_SHADOW} (GitHub's checks at the merged commit)", "month": "the meter's verdicts, as both ledgers recorded them",
        "events": "the verdicts the log records"}
LEVEL_SAYS = {"reported": "a workflow reported the result", "rerun": "an evaluator outside the supplier's control ran the pinned suite again",
              "agreed": "two evaluators with different owners each ran the suite and agree", "attested": "an attestation of the execution itself stands behind the result"}


def line_parts(st: dict, ln: dict, noted: dict | None = None) -> dict:
    """The five parts of one statement line, one line each, and the sha256 of the receipt they were read from (None when
    no receipt stands behind the line: they are then read from the statement and say so). `noted`: the goods-received
    note recorded for the line, whose receipt's parts (`knos statement grn --record --receipt`) are used when it has them."""
    kept = ((noted or {}).get("receipt_of_goods") or {}).get("parts")
    if kept:
        return {k: kept[k] for k in ("receipt_sha256", *FIVE)}
    level = ln.get("assurance") or ("reported" if ln["evaluations"] else NOT_EVALUATED)
    money = f"{ln['amount']} {st['currency']}" if ln["amount"] else "no amount"
    return {"receipt_sha256": None, "identity": IDENTITY[st["source"]],
            "execution": (f"{len(ln['evaluations'])} evaluation(s): {' '.join(ln['evaluations'])}; evidence {ln['evidence'] or 'not named'}."
                          if ln["evaluations"] else "No evaluation stands behind this line."),
            "acceptance": f"{ids.LINE_WORDS[ln['state']].capitalize()}" + (f": {ln['why']}" if ln["why"] else "") + f", by {RULE[st['source']]}.",
            "consequence": f"{money} for {ln['supplier']}: {PAY_WORDS.get(ln['payment'], ln['payment'])}" + (f", settlement {ln['settlement']}" if ln.get("settlement") else "") + ".",
            "assurance": (f"{level}: {LEVEL_SAYS[level]}. No receipt was read for this line: `knos statement grn --record --receipt` reads one."
                          if level in LEVEL_SAYS else "Not evaluated: nothing stands behind this line.")}


def lines_now(st: dict, status: dict | None = None, today: str = "", window: int = ACCEPT_DAYS) -> list[dict]:
    """The statement's lines with what the status file adds: the last settlement recorded for each, and who approved it.
    Each line also says its assurance level (knos.receipt.LEVELS), computed and never typed: the level of the receipt a
    recorded goods-received note was made from; without one, `reported` for a line an evaluation stands behind (the
    evidence is a record of what a workflow reported) and "not evaluated" for a line with none. `po_reference` is the
    purchase order a recorded note names, `grn_reference` the note's own reference. `steps` are the line's four steps
    and `owed` whether it is owed to the supplier (`steps_of`; `today` and `window` decide when silence counts)."""
    events = _status(st, status)["events"]
    out = []
    for ln in st["lines"]:
        noted = [e["grn"] for e in events if e["type"] == "grn" and e["line"] == ln["invoice_line"]]
        ln = {**ln, "assurance": noted[-1]["receipt_of_goods"]["assurance"] if noted else "reported" if ln["evaluations"] else NOT_EVALUATED,
              "po_reference": (noted[-1]["purchase_order"] or {}).get("number", "") if noted else "", "grn_reference": grn_reference(ln)}
        paid = [e for e in events if e["type"] == "settlement" and e["line"] == ln["invoice_line"]]
        ok = next((e for e in events if e["type"] == "approval" and ln["invoice_line"] in e["lines"]), None)
        note = paid[-1].get("note", "") if paid else ""       # a quorum of one controller, from the payment's receipt (`pay`)
        row = {**ln, "settlement": paid[-1]["settlement"] if paid else None, "payment": paid[-1]["state"] if paid else ln["payment"],
               "approved_by": f"{ok['by']} ({ok['role']}) on {ok['on']}" if ok else "",
               **({"why": f"{ln['why']}; {note}" if ln["why"] else note} if note else {})}
        steps, owed = steps_of(st, ln, events, today, window)
        out.append({**row, "parts": line_parts(st, row, noted[-1] if noted else None), "steps": steps, "owed": owed,
                    "assured": _assure.of_line(row, (noted[-1] if noted else {}).get("receipt_of_goods"), st["source"])})
    return out


def answers(st: dict, status: dict | None = None, today: str = "", window: int = ACCEPT_DAYS) -> list[tuple[str, str]]:
    """What whoever approves the invoice asks, answered from the statement and its status, in order. The unsupported
    charges (disputed or billed before) and the wrongful refusals (owed to the supplier) are counted side by side."""
    now, scale, t = lines_now(st, status, today, window), st["scale"], st["totals"]
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
    approved = "; ".join(f"{len(e['lines'])} {'line' if len(e['lines']) == 1 else 'lines'}" + (f", {e['amount']}{unit}" if priced else "")
                         + f" by {e['by']} ({e['role']}) on {e['on']}, role as stated" for e in approvals) or "nobody yet"
    if approvals and waiting:
        approved += f"; {len(waiting)} with the policy met not yet approved"
    took = [r for r in now if r["steps"][1]["state"] == "done"]
    owed = [r for r in now if r["owed"]]
    return [
        ("Authorised", "not known here: a shadow run reads the invoice and GitHub, not the order" if st["source"] == "shadow"
         else f"{st['accepted_deliverables']} {'deliverable' if st['accepted_deliverables'] == 1 else 'deliverables'} accepted in the log this month, each billable once"
         if st["source"] == "events" else f"{len({r['deliverable'] for r in now})} deliverables, each a milestone of an order both ledgers name"),
        *([("Arrived twice", "; ".join(f"{d['kind'].replace('_', ' ')} {d['id']} by {' and '.join(x['source'] for x in d['sources'])}, counted once"
                                         for d in st["repeats"]) or "nothing")] if st["source"] == "events" else []),
        ("Billed", said(now) + f" on invoice {st['invoice']}" + (f" from {st['supplier']}" if st["supplier"] else "")),
        ("Delivered", f"{sum(1 for r in now if r['evaluations'])} of {len(now)} lines name work that was evaluated"),
        ("Policy met", said(agreed) + ": the evidence met the terms, nothing more"),
        ("Accepted", said(took) + (" by a party" if took else "")),
        ("Already billed", said(of("duplicate")) + (": " + "; ".join(f"line {r['line']} ({r['duplicate_of']})" for r in of("duplicate")) if of("duplicate") else "")),
        ("Approved", approved),
        ("Disputed", said(of("disputed")) + ", open"),
        ("Insufficient evidence", said(of("insufficient_evidence")) + ", open"),
        ("Unsupported charges", said(of("disputed") + of("duplicate")) + ", not owed"),
        ("Wrongful refusals", said(owed) + (f", {ids.OWED_WORDS}: refused, or not authorised {window} days after {st['date']}; the supplier may appeal"
                                            if owed else "")),
        ("Credited", said([r for r in now if r["payment"] == "refunded"]) + " refunded"
         + (f"; {said(wrongly)} paid though the policy was not met, to be credited or settled" if wrongly else "")),
        ("Paid", said(paid) + (" (" + ", ".join(sorted({PAY_WORDS[r["payment"]] for r in paid})) + ")" if paid else "")),
        ("Payable", said([r for r in agreed if r["payment"] == "payable" and r["approved_by"]]) + " authorised, not paid"),
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
                 "evidence": f"{src['kind'].replace('_', ' ')} {src['reference'] or 'not kept'}", "receipt_sha256": rc.digest(receipt),
                 "assured": _assure.of_receipt(receipt)}
        if receipt["version"] >= 3:      # the five parts the line then links (knos.receipt.parts reads versions 3 to 5)
            goods["parts"] = rc.five_cells(receipt, level["declared_related"])
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
    events = [["approval", e["on"], f"{e['by']} ({e['role']})", f"{len(e['lines'])} {'line' if len(e['lines']) == 1 else 'lines'} authorised, policy met", e["amount"]] if e["type"] == "approval" else
              ["acceptance", e["on"], f"{e['by']} ({e['role']})", f"{len(e['lines'])} {'line' if len(e['lines']) == 1 else 'lines'} accepted", " ".join(e["lines"])] if e["type"] == "acceptance" else
              ["refusal", e["on"], f"{e['by']} ({e['role']})", f"refused: {e['why']}", " ".join(e["lines"])] if e["type"] == "refusal" else
              ["goods-received note", e["on"], e["line"], grn_said(e["grn"]), e["grn"]["reference"]] if e["type"] == "grn" else
              ["payment file", e["on"], e["message"], f"{len(e['transfers'])} {'transfer' if len(e['transfers']) == 1 else 'transfers'} by bank ({e['format']}), "
               f"{e['amount']} {e['currency']}, to pay on {e['execute']}", f"sha256 {e['sha256']}"] if e["type"] == "instruction" else
              ["settlement", e["on"], e["line"], f"returned by the bank ({e['returned']}): payable again, reference {e['reference']}", e["settlement"]]
              if e.get("returned") else
              ["settlement", e["on"], e["line"], f"{PAY_WORDS['unknown']}: the bank's answer is not clear ({e['unknown']}); no new payment file names this line", e["settlement"]]
              if e.get("unknown") else
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
    """`knos statement make | approve | pay | settle-sync | complete | status | grn | show | export | verify`, on the main app. `help_lines`: cli._HELP."""
    import datetime

    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    sub = typer.Typer(add_completion=False, no_args_is_help=True,
                      help="The statement for accounts payable: every invoice line: policy met, disputed, duplicate or without enough evidence, then accepted, authorised and settled, as JSON, CSV and PDF.")
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

    def memory(remember: str, where: Path | None):
        """The buyer organisation's memory (--remember ORG [--memory DIR]); no memory when none is named."""
        recall = importlib.import_module(f"{__package__}.recall")       # named, not imported: the relay reaches this module, and its job installs no memory engine
        try:
            return recall, recall.memory_of(remember, where)
        except ValueError as why:
            raise stop(Refused(f"No memory was opened: {why}. --remember names the buyer organisation, for example acme.")) from None

    def terms_or_stop(terms: str) -> str:
        if terms and not re.fullmatch(r"[0-9a-f]{64}", terms.lower()):
            raise stop(Refused("--terms is the hash of the terms: 64 hex characters."))
        return terms.lower()

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
              name: str = typer.Option(NAME, "--name", help="the files' name"),
              remember: str = typer.Option("", "--remember", metavar="ORG", help="the buyer organisation whose memory keeps each line whose policy is not met, for `knos recall`; nothing is remembered when left out"),
              memory_dir: Path = typer.Option(None, "--memory", metavar="DIR", help="with --remember: the directory of the memory store; default: the memory engine's shared store on this machine"),
              terms: str = typer.Option("", "--terms", metavar="HASH", help="with --remember: the hash of the terms the lines fall under; without it they are kept under the buyer and supplier's names")) -> None:
        """Make one statement in three forms that say the same: JSON (the statement itself), CSV and PDF. Each line of the invoice has its policy met, is disputed, a duplicate, or has insufficient evidence, with why in plain words, its ids and where its evidence is. It reads the evidence file and nothing else: no network, no chain. Nothing is paid."""
        try:
            data = evidence.read_bytes()
            before = [billed_before(json.loads(p.read_text(encoding="utf-8"))) for p in prior]
            st = make(data, {"invoice": invoice, "supplier": supplier, "buyer": buyer, "currency": currency, "date": date}, before, not reference)
        except (OSError, ValueError) as why:
            raise stop(why) from None
        terms = terms_or_stop(terms)
        files = write(st, out or evidence.parent, None, name)
        t = st["totals"]
        typer.echo(f"Statement for invoice {st['invoice']}: {t['billed']['lines']} lines" + (f", {t['billed']['amount']}" if t["billed"]["amount"] else ""))
        for state in ids.LINE_STATES:
            typer.echo(f"  {ids.LINE_WORDS[state]:<24}{t[state]['lines']:>5}{t[state]['amount']:>16}")
        typer.echo(f"sha256 {st['sha256']}")
        typer.echo("wrote " + ", ".join(str(f) for f in files))
        if remember:
            recall, store = memory(remember, memory_dir)
            opened = recall.statement_made(store, st, terms)
            typer.echo(f"Remembered for {remember}: {len(opened)} {'line' if len(opened) == 1 else 'lines'} set aside. `knos recall exception` says how the same ended before.")
        if reference:
            whole = make(data, {k: st[k] for k in ("invoice", "supplier", "buyer", "currency", "date")}, before)["evidence"]["embedded"]
            kept = (out or evidence.parent) / f"{name}.evidence.{ {'shadow': 'json', 'events': 'jsonl'}.get(st['source'], 'tar')}"
            kept.write_bytes(canonical(whole) if st["source"] == "shadow" else data)
            typer.echo(f"The evidence is in {kept} (sha256 {st['evidence']['sha256']}): keep it with the statement; `verify` needs it as --bundle.")

    remember_opt = typer.Option("", "--remember", metavar="ORG", help="the buyer organisation whose memory keeps this decision, recalled when the same supplier and terms come back")
    memory_opt = typer.Option(None, "--memory", metavar="DIR", help="with --remember: the directory of the memory store")
    terms_opt = typer.Option("", "--terms", metavar="HASH", help="with --remember: the hash of the terms, as given to `knos statement make`")

    def decided(st: dict, status: dict, remember: str, memory_dir: Path | None, terms: str) -> None:
        if remember:
            recall, store = memory(remember, memory_dir)
            kept = recall.decision_made(store, st, status["events"][-1], terms_or_stop(terms))
            typer.echo(f"Remembered for {remember}: {len(kept)} {'decision' if len(kept) == 1 else 'decisions'}. `knos recall decisions` says them when this supplier and these terms come back.")

    @sub.command("approve")
    def approve_(file: Path = file_arg, agreed: bool = typer.Option(False, "--agreed", help="authorise payment of the lines whose policy is met; the others stay open"),
                 by: str = typer.Option(..., "--by", help="who approves"), role: str = typer.Option(..., "--role", help="in which role, as they state it"),
                 on: str = on_opt, remember: str = remember_opt, memory_dir: Path = memory_opt, terms: str = terms_opt) -> None:
        """Authorise payment of the lines whose policy is met and that nobody refused. Disputed and duplicate lines, and lines without enough evidence, stay open: nothing approves them here. The approval is appended to the status file beside the statement; the statement does not change, and nothing is paid."""
        if not agreed:
            raise stop(Refused("Say what is approved: --agreed authorises the lines whose policy is met and leaves every exception open. Nothing else can be approved here."))
        try:
            st, status = load(file)
            status = approve(st, status, by, role, today(on))
        except Refused as why:
            raise stop(why) from None
        save(file, st, status)
        decided(st, status, remember, memory_dir, terms)
        say(st, status)

    @sub.command("accept")
    def accept_(file: Path = file_arg, by: str = typer.Option(..., "--by", help="who accepts"), role: str = typer.Option(..., "--role", help="in which role, as they state it"),
                line: list[str] = typer.Option([], "--line", help="an invoice line's id (inv_...); repeat for more; every line whose policy is met when left out"),
                on: str = on_opt, remember: str = remember_opt, memory_dir: Path = memory_opt, terms: str = terms_opt) -> None:
        """Record that a party accepted lines. This is acceptance only: it authorises no payment (`approve` does) and pays nothing."""
        try:
            st, status = load(file)
            status = accept(st, status, by, role, today(on), line)
        except Refused as why:
            raise stop(why) from None
        save(file, st, status)
        decided(st, status, remember, memory_dir, terms)
        say(st, status)

    @sub.command("refuse")
    def refuse_(file: Path = file_arg, line: str = typer.Option(..., "--line", help="the invoice line's id (inv_...)"),
                by: str = typer.Option(..., "--by", help="who refuses"), role: str = typer.Option(..., "--role", help="in which role, as they state it"),
                why: str = typer.Option(..., "--why", help="why, in one sentence"), on: str = on_opt,
                remember: str = remember_opt, memory_dir: Path = memory_opt, terms: str = terms_opt) -> None:
        """Record that a party refused one line. A refused line whose evidence met its policy is shown as owed to the supplier, counted as a wrongful refusal, with the supplier's appeal."""
        try:
            st, status = load(file)
            status = refuse(st, status, line, by, role, today(on), why)
        except Refused as err:
            raise stop(err) from None
        save(file, st, status)
        decided(st, status, remember, memory_dir, terms)
        say(st, status)

    @sub.command("pay")
    def pay_(file: Path = file_arg, line: str = typer.Option("", "--line", help="the invoice line's id (inv_...)"),
             method: str = typer.Option("bank", "--method", help="bank, chain or other"),
             ref: str = typer.Option("", "--ref", help="the payer's own reference, or the transaction"),
             on: str = on_opt, state: str = typer.Option("", "--state", help="payable, paid outside Knos, held, refunded or devnet demonstration"),
             receipt: Path = typer.Option(None, "--receipt", help="with --method chain: the payment's acceptance receipt (JSON); a quorum of one controller is then said on the line"),
             terms_file: Path = typer.Option(None, "--terms-file", help="the order's Knos Terms 3 file: a payment below the assurance level it requires is refused"),
             rail: str = typer.Option("", "--rail", help="bank: write a payment file (ISO 20022 pain.001) for the approved lines whose policy is met. usdc: record a devnet payment of --line (its transaction is --ref)"),
             payer_name: str = typer.Option("", "--payer-name", help="with --rail bank: who pays, as the bank knows them"),
             payer_account: str = typer.Option("", "--payer-account", help="with --rail bank: the account that pays (an IBAN, or an account number)"),
             payer_bic: str = typer.Option("", "--payer-bic", help="with --rail bank: the payer's bank (BIC), when the bank asks for it"),
             payees: Path = typer.Option(None, "--payees", help="with --rail bank: a CSV, one row a supplier: supplier,name,account,bic"),
             execute: str = typer.Option("", "--execute", help="with --rail bank: the day the bank is asked to pay, YYYY-MM-DD (the file's day when left out)"),
             out: Path = typer.Option(None, "--out", help="with --rail bank: where the payment file is written (<name>.pain001.xml beside the statement when left out)"),
             remember: str = typer.Option("", "--remember", metavar="ORG", help="the buyer organisation whose memory keeps how a line that was set aside ended (paid: accepted on appeal; refunded: refused)"),
             memory_dir: Path = typer.Option(None, "--memory", metavar="DIR", help="with --remember: the directory of the memory store"),
             terms: str = typer.Option("", "--terms", metavar="HASH", help="with --remember: the hash of the terms, as given to `knos statement make`")) -> None:
        """Record the payment status of one line that was paid, held or refunded outside Knos; or, with --rail bank, write the payment file the payer uploads to their own bank: one transfer per supplier for the lines whose policy is met, approved and still payable, each carrying its settlement id end to end. It moves no money and checks no bank. No bank has taken a file this command wrote: try it in the bank's test channel first."""
        from . import rails
        try:
            st, status = load(file)
            if rail and rail not in rails.RAILS:
                raise Refused(f"--rail is {' or '.join(rails.RAILS)}; {rail!r} is neither.")
            if rail == "bank" and not line:
                try:
                    whom = rails.read_payees(payees.read_text(encoding="utf-8-sig")) if payees else {}
                except OSError as why:
                    raise Refused(f"Cannot read the payees file: {why}") from None
                made = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if not on else ""
                status, xml, found = rails.instruct(st, status, {"name": payer_name, "account": payer_account, "bic": payer_bic, "on": today(on),
                                                                "execute": execute, "created": made, "payees": whom})
                name = file.name[:-5] if file.name.endswith(".json") else file.name
                where = out or file.parent / f"{name}.pain001.xml"
                where.write_bytes(xml.encode("utf-8"))
                for t in found:
                    typer.echo(f"  {t['end_to_end']}  {t['amount']:>14} {t['currency']}  {t['supplier']}  ({len(t['lines'])} {'line' if len(t['lines']) == 1 else 'lines'})")
                typer.echo(f"wrote {where}: {len(found)} {'transfer' if len(found) == 1 else 'transfers'} ({rails.MESSAGE}), message {status['events'][-1]['message']}. "
                           "No money moved: upload it to the payer's bank, then `knos statement status` reads the bank's answer.")
                save(file, st, status)
                return
            if not line or not ref:
                raise Refused("A settlement record names its line and the payer's reference: --line and --ref. (--rail bank, with no --line, writes a payment file instead.)")
            try:
                held = json.loads(receipt.read_text(encoding="utf-8")) if receipt else None
            except (OSError, ValueError):
                raise Refused(f"Cannot read {receipt} as a receipt's JSON.") from None
            try:
                floor = json.loads(terms_file.read_text(encoding="utf-8")) if terms_file else None
            except (OSError, ValueError):
                raise Refused(f"Cannot read {terms_file} as a terms file's JSON.") from None
            status = pay(st, status, line, "chain" if rail == "usdc" else method, ref, today(on), state, held, floor)
        except (Refused, rails.Refused) as why:
            raise stop(why) from None
        last = status["events"][-1]
        typer.echo(f"recorded {last['settlement']}: line {line} is {PAY_WORDS[last['state']]} ({last['method']}, reference {last['reference']}, {last['on']}). No money moved.")
        save(file, st, status)
        if remember:
            recall, store = memory(remember, memory_dir)
            ended = recall.statement_paid(store, st, last, terms_or_stop(terms))
            if ended is not None:
                typer.echo(f"Remembered for {remember}: this line had been set aside, and it ended {recall.ENDING_WORDS[ended['ending']]}.")

    @sub.command("settle-sync")
    def settle_sync_(file: Path = file_arg,
                     order: str = typer.Option("", "--order", help="the work order's address: only its payments count, and a line whose evidence names no transaction is looked for among its signatures"),
                     tx: list[Path] = typer.Option([], "--tx", help="a recorded transaction (getTransaction's JSON) to read instead of asking the cluster; repeat for more"),
                     rpc: str = typer.Option("", "--rpc", help="the cluster's RPC URL (devnet's when left out)")) -> None:
        """Record the chain's payment of each line whose policy is met and that is not settled yet: the knos_pay transaction is read, its amount, payee and order are checked against the line, and its signature, slot, amount and fee are written to the status file. It moves no money."""
        from . import chain
        try:
            st, status = load(file)
            given: dict[str, dict] = {}
            for p in tx:
                try:
                    doc = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    raise Refused(f"Cannot read {p} as a transaction's JSON.") from None
                doc = doc.get("result", doc) if isinstance(doc, dict) else doc
                for sig in (doc.get("transaction") or {}).get("signatures") or [] if isinstance(doc, dict) else []:
                    given[str(sig)] = doc
            url = rpc or chain.ledger().url

            def read(sig: str) -> dict | None:
                if sig in given or tx:
                    return given.get(sig)
                return chain.call(url, "getTransaction", [sig, {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 1}], timeout=30)

            def find(address: str) -> list[str]:
                if tx:
                    return list(given)
                return [str(x["signature"]) for x in chain.call(url, "getSignaturesForAddress", [address, {"limit": 100}], timeout=30) or [] if not x.get("err")]

            def final(sig: str) -> str | None:
                got = (chain.call(url, "getSignatureStatuses", [[sig], {"searchTransactionHistory": True}], timeout=30) or {}).get("value") or [None]
                return (got[0] or {}).get("confirmationStatus")
            status, said = settle_sync(st, status, read, find, order, None if tx else final)
        except Refused as why:
            raise stop(why) from None
        except Exception as why:  # noqa: BLE001 - the cluster did not answer: nothing was written
            raise stop(Refused(f"The cluster did not answer ({' '.join(str(why).split())[:200]}); nothing was written.")) from None
        for line, words in said:
            typer.echo(f"{line}  {words}")
        if any(w.startswith("settled by") for _l, w in said):
            save(file, st, status)

    @sub.command("complete")
    def complete_(file: Path = file_arg,
                  sources: Path = typer.Option(..., "--sources", help="the sources document (kind knos-sources): the orders the chain paid in the period and what GitHub answered for each reference"),
                  resolve: str = typer.Option("", "--resolve", metavar="ID=HOW", help="resolve one exception (cx_...): corrected, accepted or refused; kept in the buyer's memory"),
                  as_json: bool = typer.Option(False, "--json", help="print the report as JSON"),
                  remember: str = remember_opt, memory_dir: Path = memory_opt) -> None:
        """Compare the statement with its sources and list every exception: a source deleted, an order omitted, an order seen after the period closed (carried, never added), one deliverable under two ids (counted once). With --remember, each exception says how the same source was resolved before."""
        from . import completeness as C
        try:
            st, status = load(file)
            try:
                doc = json.loads(sources.read_text(encoding="utf-8"))
            except (OSError, ValueError) as why:
                raise Refused(f"Cannot read {sources} as a sources document: {why}") from None
            store = memory(remember, memory_dir)[1] if remember else None
            report = C.check_status(st, status, C.check(st, doc, store))
            if resolve:
                eid, _, how = resolve.partition("=")
                exc = next((x for x in report["exceptions"] if x["id"] == eid.strip()), None)
                if exc is None or store is None:
                    raise Refused(f"--resolve names an exception of this report and needs --remember: {eid.strip() or '(none)'} is not one here." if exc is None
                                  else "--resolve keeps the resolution in the buyer's memory: name it with --remember ORG.")
                C.remember(store, exc, how.strip(), str(st.get("supplier") or ""), period=report["period"])
                exc["before"] = C.recall(store, exc, str(st.get("supplier") or ""))
        except (Refused, C.Bad, ValueError) as why:
            raise stop(why) from None
        if as_json:
            typer.echo(json.dumps(report, indent=1, sort_keys=True))
            return
        for row in C.words(report):
            typer.echo(row)

    @sub.command("status")
    def status_(file: Path = file_arg,
                source: Path = typer.Option(..., "--from", help="the bank's answer: a payment status report (pain.002 XML), or a CSV: end_to_end_id,status,reference,date,reason"),
                on: str = on_opt) -> None:
        """Read the bank's answer to a payment file and record it: each line of a settled transfer becomes paid outside Knos, each line of a rejected one payable again with the bank's reason, each line of an unclear answer (a timeout, \"unknown\") held as unknown until a later answer says paid or returned, and a transfer still with the bank changes nothing. Reading the same answer twice changes nothing. It records what the bank's file says; it asks no bank."""
        from . import rails
        try:
            st, status = load(file)
            try:
                rows = rails.read_status(source.read_bytes())
            except OSError as why:
                raise Refused(f"Cannot read {source}: {why}") from None
            after, said = rails.apply(st, status, rows, today(on))
        except (Refused, rails.Refused) as why:
            raise stop(why) from None
        for words in said:
            typer.echo(words)
        if len(after["events"]) != len((status or {}).get("events", [])):
            save(file, st, after)
        say(st, after)

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
    def show_(file: Path = file_arg, as_json: bool = typer.Option(False, "--json", help="print the lines with their status as JSON"),
              on: str = typer.Option("", "--on", help="the day to judge the acceptance window on, YYYY-MM-DD (today when left out)"),
              window: int = typer.Option(ACCEPT_DAYS, "--window", help="the acceptance window, in days after the statement's day")) -> None:
        """Answer what an approver asks: what was authorised, billed and delivered, whose policy is met, who accepted and who approved, what is unsupported, what is owed to the supplier, credited and paid. Each line shows its four steps."""
        try:
            st, status = load(file)
            day = _day(today(on))
            if as_json:
                now = lines_now(st, status, day, window)
                typer.echo(canonical({"statement": st["sha256"], "lines": now, "assurance": _assure.words(st, now),
                                      "answers": [list(a) for a in answers(st, status, day, window)]}).decode(), nl=False)
                return
            for question, answer in answers(st, status, day, window):
                typer.echo(f"{question + ':':<23}{answer}")
            for r in lines_now(st, status, day, window):
                if r["state"] != "agreed":
                    typer.echo(f"  line {r['line']} {r['reference'] or '(no reference)'}: {ids.LINE_WORDS[r['state']]}: {r['why']}")
                    continue
                typer.echo(f"  line {r['line']} {r['reference'] or '(no reference)'}: " + "; ".join(f"{ids.STEP_WORDS[x['step']]}: {x['said']}" if x["state"] != "failed"
                                                                                                   else f"NOT {ids.STEP_WORDS[x['step']]}: {x['said']}" for x in r["steps"]))
                if r["owed"]:
                    typer.echo(f"    {ids.OWED_WORDS.upper()}: the evidence met the terms. The supplier may appeal: knos appeal \"<reason>\" --repo OWNER/NAME --pull N --by LOGIN")
        except Refused as why:
            raise stop(why) from None

    @sub.command("export")
    def export_(file: Path = file_arg, fmt: str = typer.Option("", "--format", help="quickbooks, netsuite, generic, match (every line with its purchase order and 2-way or 3-way match) or ariba (cXML invoice)"),
                supplier_id: str = typer.Option("", "--supplier-id", help="ariba: the supplier's identity on the network"),
                buyer_id: str = typer.Option("", "--buyer-id", help="ariba: the buyer's identity on the network"),
                out: Path = typer.Option(None, "--out", help="write the file here and not to standard output"),
                account: str = typer.Option("", "--account", help="the expense account every bill is booked to"),
                tax_code: str = typer.Option("", "--tax-code", help="QuickBooks' Line Tax Code"),
                date_format: str = typer.Option("", "--date-format", help="another date format than the product's default, written with YYYY, MM, DD, M and D"),
                to: str = typer.Option("", "--to", help="xero, quickbooks, netsuite or csv: that system's bill-import file of the payable lines, and a held sheet beside it")) -> None:
        """Write the statement as a file an accounting system imports. QuickBooks Online and NetSuite get one bill per line whose policy is met, with the line's state, payment status and ids in the memo; a line that is disputed, duplicate or without enough evidence is never a bill. The generic file lists every line. Each is a file export, not an integration: nobody has imported one into the product yet."""
        if to:
            from . import erp
            try:
                for said in erp.export_file(file, to, out, {"account": account, "tax_code": tax_code, "date_format": date_format}):
                    typer.echo(said, err=True)
            except Refused as why:
                raise stop(why) from None
            return
        if not fmt:
            raise stop(Refused("--format or --to: --to xero, quickbooks, netsuite or csv writes your accounting system's file."))
        from . import audit, exports
        try:
            st, status = load(file)
            import datetime
            today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")     # a line nobody authorised in time is owed: never a bill
            text = exports.write_statement(fmt, st, status, {"account": account, "tax_code": tax_code, "date_format": date_format,
                                                             "supplier_id": supplier_id, "buyer_id": buyer_id, "today": today})
        except (Refused, audit.Refused) as why:
            raise stop(why) from None
        f = {**exports.FORMATS, **exports.STATEMENT_MORE}[fmt]
        typer.echo(f"{f['name']}: {exports.label(fmt)}." + (f" Unverified: {f['unverified']}." if f["unverified"] else ""), err=True)
        name = file.name[:-5] if file.name.endswith(".json") else file.name
        beside = exports.parts_path(out) if out else file.parent / f"{name}.{fmt}.parts.csv"      # the five parts of every line, always beside the file
        try:
            beside.write_bytes(exports.parts_file(exports.statement_parts_rows(st, status), exports.sha_of(text)).encode("utf-8"))
        except audit.Refused as why:
            raise stop(why) from None
        typer.echo(f"wrote {beside}: the five parts of every line (identity, execution, acceptance, consequence, assurance)", err=True)
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
