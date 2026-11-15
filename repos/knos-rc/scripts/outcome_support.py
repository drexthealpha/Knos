"""A second outcome that is not code: SUPPORT RESOLUTIONS, counted by the meter under terms agreed before the work.
docs/reference/OUTCOMES.md, "Support resolutions", is the page; examples/outcomes/support-resolution holds the made-up data.

    python scripts/outcome_support.py evaluate  --tickets T --terms TERMS [--out DIR]   a verdict for every ticket
    python scripts/outcome_support.py batch     --tickets T --terms TERMS --month YYYY-MM [--seq N] [--buyer ID --seller ID] --out DIR
                                                the seller's ledger file, and the audience a workflow has GitHub sign
    python scripts/outcome_support.py statement --tickets T --terms TERMS --invoice CSV --month YYYY-MM --out DIR
                                                the supplier's invoice set against the count: an AP statement
    python scripts/outcome_support.py receipt   --token JWT --jwks JWKS --tickets T --terms TERMS --month YYYY-MM --out FILE
                                                offline: GitHub's signature, and that it signed exactly this count

THE DEFINITION (the terms file states it; its hash is the policy every evaluation names). A ticket is one accepted
resolution when all of these hold, read from the help desk's own record of the ticket:

  1. the agent marked it solved;
  2. no person took it over: no escalation and no reply by a human agent, up to the end of the window;
  3. the customer did not come back: no reopening and no further customer message inside the window after `solved`;
  4. the window has closed (terms `window_hours`, counted from `solved`). Until then the ticket has NO verdict and is
     not in the count: nothing is billed on a resolution that can still be undone;
  5. where the terms require it (`confirmation`: "required"), the customer said it was solved; with "or_silence" a
     customer who left without asking for more counts as well.

A ticket is one deliverable whatever number of times it is exported or judged: accepted and billed once. A reopening
after the window does not take the resolution back; it is a new deliverable only when the terms say so
(`new_after_window`), which is `knos.ledger.reopened`'s rule.

This mirrors how two vendors that bill per resolution publish their own count. Intercom counts a resolution when the
customer confirms or leaves without asking for more, does not count one when the customer asks for a person, takes it
back when the customer returns to the conversation, and bills a conversation at most once
(https://www.intercom.com/help/en/articles/8205718-fin-ai-agent-resolutions). Zendesk evaluates only conversations
that were not escalated, after a period of inactivity (72 hours for email and web forms), and counts per
conversation (https://support.zendesk.com/hc/en-us/articles/5352026794010). Both read 7 October 2026.

WHAT THIS DOES NOT SHOW. The tickets are made up. The script reads a FILE: it does not read a help desk, and nothing
here proves that a file is a help desk's true record. Whether an answer was right is in no ticket state. LIMITATIONS
below goes into every receipt.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from knos import events as E  # noqa: E402
from knos import ids, statement  # noqa: E402
from knos import ledger as L  # noqa: E402

EXAMPLE = ROOT / "examples" / "outcomes" / "support-resolution"
BUYER, SELLER = 424242, 555000              # sample ids, as in examples/outcomes/evaluation.py
KIND, VERSION = "support-resolution", 1
EVENT_TYPES = ("agent_answer", "solved", "customer_confirmed", "customer_message", "reopened", "escalated", "human_reply")
CONFIRMATION = ("required", "or_silence")
GITHUB = "https://token.actions.githubusercontent.com"
WORKFLOW = ".github/workflows/outcome-support.yml"
LIMITATIONS = (
    "The tickets are made-up data in a file of this repository. No help desk was read and no customer exists.",
    "GitHub signed which workflow ran, at which commit, and the count it asked to have signed. It did not sign that the ticket file is true.",
    "The terms say when a ticket counts. Whether the answer was right is in no ticket state: a buyer who pays per resolution reads a sample.",
    "The buyer and the seller are sample ids. Nobody bought this.",
)


class Refused(ValueError):
    """Why a terms file, a ticket file or a token is not taken, in one sentence."""


def canonical(doc) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# -- the terms and the tickets -----------------------------------------------------------------------------------------
def read_terms(doc: dict) -> dict:
    """The terms as agreed, checked: {"kind", "v", "window_hours", "confirmation", "new_after_window", "rate"} and nothing else."""
    want = {"kind", "v", "window_hours", "confirmation", "new_after_window", "rate"}
    if not isinstance(doc, dict) or set(doc) != want:
        raise Refused(f"the terms name exactly: {', '.join(sorted(want))}")
    if doc["kind"] != KIND or doc["v"] != VERSION:
        raise Refused(f"these are not terms of kind {KIND}, version {VERSION}")
    if isinstance(doc["window_hours"], bool) or not isinstance(doc["window_hours"], int) or not 1 <= doc["window_hours"] <= 24 * 90:
        raise Refused("window_hours is a whole number of hours, from 1 to 2160")
    if doc["confirmation"] not in CONFIRMATION or not isinstance(doc["new_after_window"], bool):
        raise Refused("confirmation is `required` or `or_silence`, and new_after_window is true or false")
    if isinstance(doc["rate"], bool) or not isinstance(doc["rate"], int) or doc["rate"] < 0:
        raise Refused("rate is what one accepted resolution bills, in millionths of the unit the two settle in")
    return doc


def policy_of(terms: dict) -> str:
    """The policy every evaluation names: sha256 of the terms, so a changed window or rule is another policy."""
    return hashlib.sha256(canonical(read_terms(terms))).hexdigest()


def read_tickets(doc: dict) -> tuple[str, int, list[dict]]:
    """(the help desk's name, when the file was exported, the tickets): each record once. The same record twice is one
    ticket; two records of one ticket that differ are refused, because a count says one thing about each ticket."""
    if not isinstance(doc, dict) or not isinstance(doc.get("desk"), str) or not doc["desk"] or isinstance(doc.get("exported_at"), bool) \
            or not isinstance(doc.get("exported_at"), int) or not isinstance(doc.get("tickets"), list):
        raise Refused("a ticket file names its desk, exported_at (seconds) and a list of tickets")
    seen: dict[str, dict] = {}
    for t in doc["tickets"]:
        if not isinstance(t, dict) or not isinstance(t.get("id"), str) or not t["id"] or not isinstance(t.get("events"), list):
            raise Refused("a ticket has an id and a list of events")
        last = -1
        for e in t["events"]:
            if not isinstance(e, dict) or e.get("type") not in EVENT_TYPES or isinstance(e.get("at"), bool) or not isinstance(e.get("at"), int) or e["at"] < last:
                raise Refused(f"ticket {t['id']}: an event has a type of {', '.join(EVENT_TYPES)} and a time `at` in seconds, in order")
            last = e["at"]
        if last > doc["exported_at"]:
            raise Refused(f"ticket {t['id']}: an event is later than the export")
        if seen.setdefault(t["id"], t) != t:
            raise Refused(f"ticket {t['id']} is in the file twice with different contents: keep one")
    return doc["desk"], doc["exported_at"], [seen[k] for k in sorted(seen)]


def judge(ticket: dict, terms: dict, as_of: int) -> dict:
    """One ticket under the terms at the time of the export: {"ticket", "verdict", "why", "basis", "solved_at"}.
    `verdict` is accepted, rejected, or None while the window is still open (no evaluation is made)."""
    window = terms["window_hours"] * 3600
    at = lambda *types: [e["at"] for e in ticket["events"] if e["type"] in types]  # noqa: E731
    out = {"ticket": ticket["id"], "verdict": "rejected", "basis": "", "solved_at": None}
    solved = at("solved")
    if not solved:
        return {**out, "why": "the agent never marked it solved"}
    start = out["solved_at"] = solved[0]
    if any(t <= start + window for t in at("escalated", "human_reply")):
        return {**out, "why": "a person took it over: an escalation or a human reply"}
    back = [t for t in at("reopened", "customer_message") if t > start]
    if back and L.reopened(start, back[0], window, terms["new_after_window"]) == L.CORRECTION:
        return {**out, "why": "the customer came back inside the window"}
    if as_of < start + window:
        return {**out, "verdict": None, "why": f"the window is open until {start + window}: not judged yet, not billed"}
    confirmed = any(start - window <= t <= start + window for t in at("customer_confirmed"))
    if terms["confirmation"] == "required" and not confirmed:
        return {**out, "why": "the terms require the customer's confirmation, and there is none"}
    return {**out, "verdict": "accepted", "basis": "confirmed" if confirmed else "silent", "why": "solved, nobody took it over, the customer did not come back"}


def order_of(desk: str, ticket: str) -> str:
    """The work order a ticket is: one per ticket of one help desk, whatever is in its record."""
    return hashlib.sha256(f"knos support ticket: {desk}/{ticket}".encode()).hexdigest()


def evaluate(tickets: dict, terms: dict, buyer: int = BUYER, seller: int = SELLER) -> tuple[list[dict], list[L.Evaluation]]:
    """(a verdict for every ticket, the meter's evaluation for every ticket that has one). The artifact is the record
    that was judged: 40 hex characters of its hash, the size of the meter's field."""
    desk, as_of, each = read_tickets(tickets)
    policy = policy_of(terms)
    verdicts, evals = [], []
    for t in each:
        v = judge(t, terms, as_of)
        v["deliverable"] = ids.deliverable(order_of(desk, t["id"]), 0)
        verdicts.append(v)
        if v["verdict"] is not None:
            evals.append(L.Evaluation(buyer, seller, order_of(desk, t["id"]), hashlib.sha256(canonical(t)).hexdigest()[:40], policy, 0,
                                      v["verdict"] == "accepted", terms["rate"], verdict=v["verdict"]))
    return verdicts, evals


def summary(verdicts: list[dict], terms: dict) -> dict:
    count = lambda word: sum(1 for v in verdicts if v["verdict"] == word)  # noqa: E731
    return {"tickets": len(verdicts), "accepted": count("accepted"), "rejected": count("rejected"), "not_judged_yet": count(None),
            "value": count("accepted") * terms["rate"], "policy": policy_of(terms)}


# -- the meter's count ------------------------------------------------------------------------------------------------
def the_batch(tickets: dict, terms: dict, month: str, seq: int = 0, buyer: int = BUYER, seller: int = SELLER) -> L.Batch:
    _verdicts, evals = evaluate(tickets, terms, buyer, seller)
    if not evals:
        raise Refused("no ticket has a verdict yet: there is nothing to count")
    return L.batch(evals, seq, month)


def audience(b: L.Batch) -> str:
    """What the workflow has GitHub sign: the seller's own count of the month (`knosm:claim:...`), the audience
    knos_meter's ClaimBatch reads when the seller is the owner of the repository that ran."""
    return L.batch_audience(b, claim=True)


# -- the statement ----------------------------------------------------------------------------------------------------
def read_invoice(text: str) -> list[tuple[str, int]]:
    """The supplier's invoice: a CSV with the columns `ticket` and `amount` (in the unit's millionths: 990000 is 0.99)."""
    rows = list(csv.DictReader(io.StringIO(text)))
    try:
        return [(r["ticket"].strip(), int(r["amount"])) for r in rows]
    except (KeyError, ValueError, AttributeError):
        raise Refused("the invoice is a CSV with the columns `ticket` and `amount`, the amount a whole number of millionths") from None


def events_log(tickets: dict, terms: dict, invoice: str, month: str, number: str, buyer: int = BUYER, seller: int = SELLER) -> E.Log:
    """The one log of events both sides can make again: the batch's evaluations, then the invoice's lines."""
    desk, _as_of, _each = read_tickets(tickets)
    b = the_batch(tickets, terms, month, 0, buyer, seller)
    log, m = E.Log(), L.month_of(month)
    digest = hashlib.sha256(invoice.encode("utf-8")).hexdigest()
    report = E.ingest(log, E.from_ledger(L.dump([b])))
    lines = [E.invoice_line(str(seller), number, n, "import", deliverable=ids.deliverable(order_of(desk, ticket), 0), month=m, amount=amount, unit="units",
                            evidence=f"invoice:{digest}#{n}") for n, (ticket, amount) in enumerate(read_invoice(invoice), 1)]
    report2 = E.ingest(log, lines)
    if not (report.ok and report2.ok):
        raise Refused(f"the events could not be recorded: {[*report.json().get('refused', []), *report2.json().get('refused', [])][:1]}")
    return log


def make_statement(tickets: dict, terms: dict, invoice: str, month: str, number: str = "SUPPORT-1", currency: str = "test USDC") -> tuple[dict, E.Log]:
    log = events_log(tickets, terms, invoice, month, number)
    year, mon = month.split("-")
    meta = {"invoice": number, "supplier": str(SELLER), "buyer": f"gh:{BUYER}", "currency": currency, "date": f"{year}-{mon}-28"}
    return statement.from_events(log.text().encode("utf-8"), meta), log


# -- the receipt: GitHub's signature on exactly this count ---------------------------------------------------------------
def receipt(jwt: str, jwks: dict, tickets: dict, terms: dict, month: str, now: int, seq: int = 0) -> dict:
    """Checks the token with the on-chain verifier's rule (scripts/outcome_k8s.py `verify_token`: RS256, strict JSON),
    then what a reader of this count asks: GitHub signed it, for this workflow file, and the audience is the count this
    script makes again from the ticket file and the terms, with the repository's owner as the seller."""
    import outcome_k8s as k8s
    try:
        seen = k8s.verify_token(jwt, jwks, GITHUB, now)
    except k8s.Refused as why:
        raise Refused(f"the token is not one GitHub signed: {why}") from None
    c = seen["claims"]
    try:
        owner = int(str(c["repository_owner_id"]))
    except (KeyError, ValueError):
        raise Refused("the token names no repository owner") from None
    b = the_batch(tickets, terms, month, seq, BUYER, owner)
    aud = c.get("aud")
    if aud != audience(b):
        raise Refused("the token's audience is not this count: the ticket file, the terms, the month or the seller differ from what was signed")
    if int(c.get("exp", 0)) + k8s.LATE <= now:
        raise Refused("the token expired over an hour ago")
    if f"/{WORKFLOW}@" not in str(c.get("job_workflow_ref") or c.get("workflow_ref") or ""):
        raise Refused(f"the token is not of a run of {WORKFLOW}")
    verdicts, _evals = evaluate(tickets, terms, BUYER, owner)
    return {"type": "knos.outcome-support-receipt", "version": 1, "issuer": GITHUB, "audience": aud, "token_sha256": hashlib.sha256(jwt.encode()).hexdigest(),
            "workflow": c.get("job_workflow_ref") or c.get("workflow_ref"), "commit": c.get("sha"), "repository": c.get("repository"), "seller": owner,
            "buyer": BUYER, "month": b.month, "seq": b.seq, "count": b.count, "accepted": b.accepted, "value": b.value, "root": b.root.hex(),
            "policy": policy_of(terms), "terms": terms, "tickets_sha256": hashlib.sha256(canonical(tickets)).hexdigest(),
            "summary": summary(verdicts, terms), "on_chain": None, "limitations": list(LIMITATIONS)}


# -- the command line -------------------------------------------------------------------------------------------------
def _json(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as why:
        raise Refused(f"{path} cannot be read as JSON: {why}") from None


def _write(out: Path, name: str, text: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(text, encoding="utf-8", newline="\n")
    return out / name


def main(argv: list[str] | None = None, say=print) -> int:
    ap = argparse.ArgumentParser(description="Support resolutions, counted under agreed terms.")
    ap.add_argument("command", choices=("evaluate", "batch", "statement", "receipt"))
    ap.add_argument("--tickets", default=str(EXAMPLE / "tickets.json"))
    ap.add_argument("--terms", default=str(EXAMPLE / "terms.json"))
    ap.add_argument("--invoice", default=str(EXAMPLE / "invoice.csv"))
    ap.add_argument("--month", default="2026-10")
    ap.add_argument("--seq", type=int, default=0)
    ap.add_argument("--buyer", type=int, default=BUYER)
    ap.add_argument("--seller", type=int, default=SELLER)
    ap.add_argument("--token")
    ap.add_argument("--jwks")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        tickets, terms = _json(a.tickets), read_terms(_json(a.terms))
        if a.command == "evaluate":
            verdicts, evals = evaluate(tickets, terms, a.buyer, a.seller)
            for v in verdicts:
                say(f"{v['ticket']}  {v['verdict'] or 'not judged yet':<14}  {v['why']}")
            s = summary(verdicts, terms)
            say(f"{s['tickets']} tickets: {s['accepted']} accepted, {s['rejected']} rejected, {s['not_judged_yet']} not judged yet; "
                f"value {statement.amount_of(s['value'], 6)}; policy {s['policy']}")
            if a.out:
                _write(Path(a.out), "verdicts.json", json.dumps({"summary": s, "verdicts": verdicts}, indent=1, sort_keys=True) + "\n")
                _write(Path(a.out), "evaluations.jsonl", "".join(e.line() + "\n" for e in evals))
            return 0
        if a.command == "batch":
            b = the_batch(tickets, terms, a.month, a.seq, a.buyer, a.seller)
            say(f"audience {audience(b)}")
            say(f"{b.count} evaluations, {b.accepted} accepted, value {statement.amount_of(b.value, 6)}, root {b.root.hex()}")
            if a.out:
                _write(Path(a.out), "ledger.seller.jsonl", L.dump([b]))
                _write(Path(a.out), "audience", audience(b) + "\n")
            return 0
        if a.command == "statement":
            st, log = make_statement(tickets, terms, Path(a.invoice).read_text(encoding="utf-8"), a.month)
            for ln in st["lines"]:
                say(f"line {ln['line']}  {ln['state']:<21}  {ln['amount']:>6}  {ln['why']}")
            say("  ".join(f"{k} {v['lines']} ({v['amount']})" for k, v in st["totals"].items() if isinstance(v, dict) and "lines" in v))
            if a.out:
                _write(Path(a.out), "events.jsonl", log.text())
                statement.write(st, Path(a.out))
                say(f"wrote {a.out}/ap-statement.json, .csv, .pdf and events.jsonl")
            return 0
        if not (a.token and a.jwks):
            raise Refused("receipt needs --token and --jwks")
        r = receipt(Path(a.token).read_text(encoding="utf-8").strip(), _json(a.jwks), tickets, terms, a.month, int(time.time()), a.seq)
        say(f"GitHub signed this count: {r['accepted']} accepted of {r['count']} evaluations, value {statement.amount_of(r['value'], 6)}, for {r['workflow']}")
        if a.out:
            Path(a.out).write_text(json.dumps(r, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        return 0
    except (Refused, L.Bad, statement.Refused) as why:
        say(f"refused: {why}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
