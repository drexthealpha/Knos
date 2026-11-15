"""Completeness: a statement set against the sources it names, and every difference listed as an exception.

Two ledgers that agree with each other can both miss the same event. So a statement is also compared with the
sources themselves: the orders the chain holds and paid in the period, and the GitHub pull requests and workflow runs
its lines name. What does not match is never fixed in place; it is listed, one exception per difference:

    deleted      a line names a pull request or a run that GitHub no longer has: the line is held
    omitted      the chain paid an order in the period and no line of the statement bills it
    late         the chain paid an order in the period, but the record saw it after the period closed: it is carried
                 to the next period, never added to this one; a line that bills it anyway is held
    duplicated   one deliverable under two ids (two lines, or two orders, naming the same pull request or order):
                 counted once, the others flagged and left out of the count

    check(st, sources, store, terms, supplier)  the report: exceptions, what is counted once, what is carried
    remember(store, exc, resolution, ...)       how an exception was resolved, kept in the buyer's memory through
                                                knos.proof.history (Sibyl); `check` recalls it when the same source
                                                comes back. NullStore keeps and recalls nothing.
    contradictions(st, status)                  records of one line that cannot all be true (paid under two ids;
                                                booked from a transaction that was not final)
    stored_terms(data)                          what an order account funded earlier holds: its amount, its fee and
                                                its rate, which an upgrade of the program does not rewrite

`sources` is a JSON document (`knos-sources`): {"period": "YYYY-MM", "closed_at": ISO time or "", "terms": a terms
hash, "orders": [{"order", "reference", "deliverable", "amount", "signature", "at", "seen", "terms", "data"}] ("data":
the order account's bytes in hex; its amount and terms hash are then read from them), "github":
{reference: "present" | "deleted" | "unknown"}}. Reading it from the cluster and from GitHub is the caller's work;
this module decides from what it is given and asks nothing.
"""
from __future__ import annotations

import datetime
import hashlib
import importlib
import json
import re

KIND, VERSION = "knos-completeness", 1
SOURCES_KIND = "knos-sources"
KINDS = ("deleted", "omitted", "late", "duplicated")
GITHUB = ("present", "deleted", "unknown")
# How a person resolves an exception, and the ending knos.proof.history keeps it under (EXCEPTION_ENDINGS).
RESOLUTIONS = {"corrected": "corrected_and_passed",      # a correction or the next statement takes it
               "accepted": "accepted_on_appeal",         # looked at and accepted as it stands
               "refused": "refused"}                     # not paid, or the second payment asked back
ENDING_RESOLUTION = {v: k for k, v in RESOLUTIONS.items()}
PAID = ("paid_outside", "devnet_demonstration")

_PULL = re.compile(r"(?:https?://github\.com/)?([\w.-]+/[\w.-]+)(?:#|/pull/|/issues/)(\d+)\b", re.I)
_RUN = re.compile(r"(?:https?://github\.com/)?([\w.-]+/[\w.-]+)/actions/runs/(\d+)", re.I)
_HASH = re.compile(r"[0-9a-f]{64}")


class Bad(ValueError):
    """A sources document that cannot be read."""


def _time(text, what: str) -> datetime.datetime | None:
    if not text:
        return None
    try:
        got = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        raise Bad(f"{what}: {str(text)[:40]!r} is not a time (YYYY-MM-DDTHH:MM:SSZ)") from None
    return got if got.tzinfo else got.replace(tzinfo=datetime.timezone.utc)


def _next(period: str) -> str:
    year, month = int(period[:4]), int(period[5:7])
    return f"{year + month // 12:04d}-{month % 12 + 1:02d}"


def github_refs(text) -> list[str]:
    """The GitHub sources a text names, each as `owner/repo#n` (a pull request or an issue) or `owner/repo/actions/
    runs/n` (a workflow run), lower case."""
    text = str(text or "")
    runs = [f"{r.lower()}/actions/runs/{n}" for r, n in _RUN.findall(text)]
    pulls = [f"{r.lower()}#{n}" for r, n in _PULL.findall(_RUN.sub(" ", text))]
    return list(dict.fromkeys(runs + pulls))


def _key(text: str) -> str:
    """A source's name as memory keeps it: itself when short, else a hash of it (an exception id is at most 120)."""
    return text if len(text) <= 120 else "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def read_sources(doc) -> dict:
    """The sources document, checked: ValueError (Bad) with one line saying what is wrong."""
    if not isinstance(doc, dict) or doc.get("kind", SOURCES_KIND) != SOURCES_KIND:
        raise Bad("this is not a sources document (kind knos-sources)")
    period = str(doc.get("period") or "")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
        raise Bad("period is written YYYY-MM")
    terms = str(doc.get("terms") or "").lower()
    if terms and not _HASH.fullmatch(terms):
        raise Bad("terms is a terms hash: 64 hex characters")
    orders = doc.get("orders") or []
    gh = doc.get("github") or {}
    if not isinstance(orders, list) or not all(isinstance(o, dict) and str(o.get("order") or "") for o in orders):
        raise Bad("orders is a list, each with its order address")
    if not isinstance(gh, dict) or any(v not in GITHUB for v in gh.values()):
        raise Bad(f"github maps each reference to {', '.join(GITHUB)}")
    closed = _time(doc.get("closed_at"), "closed_at")
    rows = []
    for o in orders:
        if o.get("data"):               # the order's account as the chain holds it: its amount and terms are read from the bytes
            try:
                held = stored_terms(bytes.fromhex(str(o["data"])))
            except ValueError as why:
                raise Bad(f"order {str(o['order'])[:16]}: {why}") from None
            from . import statement as S
            o = {**o, "amount": S.amount_of(held["amount"], held["decimals"]), "terms": held["terms"]}
        t = str(o.get("terms") or terms).lower()
        if t and not _HASH.fullmatch(t):
            raise Bad(f"order {str(o['order'])[:16]}: terms is a terms hash")
        rows.append({"order": str(o["order"]), "reference": str(o.get("reference") or ""), "deliverable": str(o.get("deliverable") or ""),
                     "amount": str(o.get("amount") or ""), "signature": str(o.get("signature") or ""), "terms": t,
                     "at": _time(o.get("at"), f"order {str(o['order'])[:16]} at"), "seen": _time(o.get("seen"), f"order {str(o['order'])[:16]} seen")})
    return {"period": period, "closed_at": closed, "terms": terms, "orders": rows,
            "github": {r: v for k, v in gh.items() for r in (github_refs(k) or [str(k).lower()])}}


def _names(ln: dict) -> set[str]:
    """Every source a line names: its deliverable, its GitHub references, and any order or transaction in its text."""
    text = " ".join(str(ln.get(k) or "") for k in ("reference", "evidence", "duplicate_of"))
    return {f"deliverable:{ln['deliverable']}"} | {f"github:{r}" for r in github_refs(text) if "/actions/runs/" not in r} | \
        {f"text:{w}" for w in re.findall(r"[1-9A-HJ-NP-Za-km-z]{32,90}", text)}


def _order_names(o: dict) -> set[str]:
    out = {f"text:{o['order']}"}
    if o["signature"]:
        out.add(f"text:{o['signature']}")
    if o["deliverable"]:
        out.add(f"deliverable:{o['deliverable']}")
    out |= {f"github:{r}" for r in github_refs(o["reference"]) if "/actions/runs/" not in r}
    return out


def _id(kind: str, source: str) -> str:
    return "cx_" + hashlib.sha256(f"{kind}|{source}".encode()).hexdigest()[:24]


def _units(amount: str, scale: int) -> int:
    from . import statement as S
    try:
        return S.units(amount, scale) if amount else 0
    except Exception:  # noqa: BLE001 - an amount the statement cannot read counts as nothing here, and is said
        return 0


def check(st: dict, sources: dict, store=None, supplier: str = "") -> dict:
    """The completeness report of the statement `st` against `sources` (read_sources' input). With `store` (the buyer's
    memory, knos.proof.history), each exception says how the same source was resolved before (`before`), when it was."""
    from . import statement as S
    src = read_sources(sources)
    period, closed = src["period"], src["closed_at"]
    scale = int(st.get("scale") or 2)
    lines = st["lines"]
    names = [_names(ln) for ln in lines]
    out: list[dict] = []

    def add(kind: str, source: str, why: str, action: str, line: dict | None = None, amount: str = "", terms: str = "") -> None:
        source = _key(source)
        assert kind in KINDS, kind
        if any(x["kind"] == kind and x["source"] == source for x in out):
            return
        out.append({"id": _id(kind, source), "kind": kind, "source": source, "line": line["line"] if line else None,
                    "invoice_line": line["invoice_line"] if line else "", "amount": amount or (line or {}).get("amount", "") or "",
                    "why": why, "action": action, "terms": terms or src["terms"]})

    # deleted: a pull request or a run a line names that GitHub no longer has
    for ln in lines:
        text = " ".join(str(ln.get(k) or "") for k in ("reference", "evidence"))
        for ref in github_refs(text):
            if src["github"].get(ref) == "deleted":
                add("deleted", f"github:{ref}", f"line {ln['line']} names {ref}, which GitHub no longer has", "held until someone resolves it", ln)

    # the orders of the period: omitted, late, and two orders for one deliverable
    start = datetime.datetime(int(period[:4]), int(period[5:7]), 1, tzinfo=datetime.timezone.utc)
    nxt = _next(period)
    end = datetime.datetime(int(nxt[:4]), int(nxt[5:7]), 1, tzinfo=datetime.timezone.utc)
    carried: list[dict] = []
    seen_for: dict[str, dict] = {}
    for o in src["orders"]:
        if o["at"] is None or not (start <= o["at"] < end):
            continue
        mine = _order_names(o)
        billed = [ln for ln, ns in zip(lines, names) if ns & mine]
        if closed is not None and o["seen"] is not None and o["seen"] > closed:
            carried.append({"order": o["order"], "to": nxt, "amount": o["amount"]})
            for ln in billed:
                add("late", f"order:{o['order']}", f"line {ln['line']} bills order {o['order'][:16]}, which the record saw after the period closed",
                    f"held: it belongs to the statement of {nxt}", ln, o["amount"], o["terms"])
            if not billed:
                add("late", f"order:{o['order']}", f"order {o['order'][:16]} was paid in {period} and seen after the period closed",
                    f"carried to {nxt}; not added to {period}", None, o["amount"], o["terms"])
            continue
        twin = next((k for k in mine - {f"text:{o['order']}", f"text:{o['signature']}"} if k in seen_for), None)
        if twin is not None:
            first = seen_for[twin]
            add("duplicated", f"order:{o['order']}", f"order {o['order'][:16]} pays the same deliverable as order {first['order'][:16]}",
                "counted once; ask for one payment back", None, o["amount"], o["terms"])
            continue
        for k in mine - {f"text:{o['order']}", f"text:{o['signature']}"}:
            seen_for.setdefault(k, o)
        if not billed:
            add("omitted", f"order:{o['order']}", f"order {o['order'][:16]} was paid in {period} and no line bills it",
                "listed: a correction or the next statement takes it", None, o["amount"], o["terms"])

    # duplicated lines: one deliverable under two ids (two lines naming the same pull request, order or deliverable)
    first_of: dict[str, dict] = {}
    for ln, ns in zip(lines, names):
        if ln["state"] == "duplicate":
            continue                    # the statement already bills it once
        ns = {n for n in ns if not n.startswith("text:")} | {n for n in ns if n.startswith("text:") and any(n == f"text:{o['order']}" for o in src["orders"])}
        same = next((first_of[n] for n in sorted(ns) if n in first_of), None)
        if same is not None and same["invoice_line"] != ln["invoice_line"]:
            add("duplicated", f"line:{ln['invoice_line']}", f"line {ln['line']} bills the deliverable line {same['line']} bills, under another id",
                f"counted once (line {same['line']})", ln)
            continue
        for n in ns:
            first_of.setdefault(n, ln)

    left_out = {x["invoice_line"] for x in out if x["kind"] in ("duplicated", "late") and x["invoice_line"]}
    held = {x["invoice_line"] for x in out if x["kind"] == "deleted"}
    counted = [ln for ln in lines if ln["state"] != "duplicate" and ln["invoice_line"] not in left_out]
    if store is not None:
        for x in out:
            x["before"] = recall(store, x, supplier or str(st.get("supplier") or ""))
    report = {"kind": KIND, "version": VERSION, "statement": st.get("sha256", ""), "period": period,
              "closed_at": closed.strftime("%Y-%m-%dT%H:%M:%SZ") if closed else "",
              "sources": {"orders": len(src["orders"]), "github": len(src["github"]),
                          "unknown": sorted(r for r, v in src["github"].items() if v == "unknown"),
                          "sha256": hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()},
              "exceptions": out, "carried": carried,
              "counted": {"lines": len(counted), "amount": S.amount_of(sum(_units(ln.get("amount") or "", scale) for ln in counted), scale),
                          "held": len(held)},
              "complete": not out}
    return report


def check_status(st: dict, status: dict | None, report: dict) -> dict:
    """The report with what the statement's status file says that cannot all be true (`contradictions`): a report with
    one is not complete."""
    said = contradictions(st, status)
    return {**report, "contradictions": said, "complete": report["complete"] and not said}


def words(report: dict) -> list[str]:
    """The report in lines a person reads."""
    if report["complete"]:
        head = f"complete: every order of {report['period']} is billed once and every source a line names is there"
    else:
        head = f"{len(report['exceptions'])} exception{'s' if len(report['exceptions']) != 1 else ''} in {report['period']}"
    out = [head]
    for x in report["exceptions"]:
        before = x.get("before")
        was = f" (resolved before: {before['resolution']})" if before else ""
        out.append(f"  {x['kind']:<10} {x['why']}: {x['action']}{was}")
    c = report["counted"]
    out += [f"  contradiction {x}" for x in report.get("contradictions", [])]
    out.append(f"counted once: {c['lines']} line{'s' if c['lines'] != 1 else ''}, {c['amount']}; held: {c['held']}")
    if report["sources"]["unknown"]:
        out.append(f"not checked (GitHub did not answer): {', '.join(report['sources']['unknown'][:5])}")
    return out


# ---- memory: how an exception was resolved, through knos.proof.history (Sibyl) ----------------------------------------

def _history():
    """knos.proof.history, named and not imported: `knos statement` is reached from the relay, whose install has no
    memory engine (tests/test_signing_path.py)."""
    return importlib.import_module(f"{__package__}.proof.history")


def _reason(kind: str) -> str:
    return f"completeness-{kind}"


def remember(store, exc: dict, resolution: str, supplier: str, terms: str = "", at: float | None = None, period: str = "") -> dict:
    """Keep how the exception `exc` (one of a report's) was resolved: `resolution` is one of RESOLUTIONS, under the
    terms hash (the exception's own, else `terms`) and for `supplier`. Kept as one of the buyer's exceptions
    (knos.proof.history.exception_resolved): an entity per supplier and terms, and one journal event. ValueError when
    the resolution is not one of RESOLUTIONS or no terms hash is known."""
    history = _history()
    if resolution not in RESOLUTIONS:
        raise ValueError(f"an exception's resolution must be one of: {', '.join(RESOLUTIONS)}")
    t = str(exc.get("terms") or terms).lower()
    when = period.replace("-", "") if period else ""
    return history.exception_resolved(store, t, _reason(exc["kind"]), supplier, exc["source"], RESOLUTIONS[resolution],
                                      evidence=[exc["id"], exc.get("invoice_line") or ""], at=at, period=when)


def recall(store, exc: dict, supplier: str, terms: str = "") -> dict | None:
    """How the same source, under the same kind, terms and supplier, was resolved before: {"resolution", "ending",
    "at", "period"}, or None (always None with NullStore, or with no terms hash)."""
    history = _history()
    t = str(exc.get("terms") or terms).lower()
    if not _HASH.fullmatch(t) or not supplier:
        return None
    got = history.exceptions_before(store, t, _reason(exc["kind"]), supplier)
    case = next((c for c in got["cases"] if c["id"] == exc["source"]), None)
    if case is None:
        return None
    return {"resolution": ENDING_RESOLUTION[case["ending"]], "ending": case["ending"], "at": case["at"], "period": case["period"]}


# ---- records that cannot all be true ----------------------------------------------------------------------------------

def contradictions(st: dict, status: dict | None) -> list[str]:
    """What a statement's status file says that cannot all be true, in words: a line paid under two settlement ids with
    no return between them; a line booked from a transaction the cluster had not finalized. Empty when it holds."""
    out: list[str] = []
    paid: dict[str, str] = {}
    for e in (status or {}).get("events", []):
        if e.get("type") != "settlement":
            continue
        line = e["line"]
        chain = e.get("chain") if isinstance(e.get("chain"), dict) else {}
        if e.get("state") in PAID and chain.get("commitment") not in (None, "finalized"):
            out.append(f"{line}: booked from a transaction seen only at {chain['commitment']}")
        if e.get("state") in PAID:
            if line in paid and paid[line] != e["settlement"]:
                out.append(f"{line}: paid under {paid[line]} and again under {e['settlement']}")
            paid.setdefault(line, e["settlement"])
        elif e.get("returned") or e.get("state") == "refunded":
            paid.pop(line, None)
    return out


# ---- an order funded before an upgrade ----------------------------------------------------------------------------------

def stored_terms(data: bytes) -> dict:
    """What an order's account holds of its schedule, read byte for byte (knos.settle.v2.pay.read_order): the amount,
    the fee it was funded with, the rate fixed at funding, its deadline, whether it has the presentation grace, and the
    build that funded it (2.1 writes no incarnation). A refund returns `amount + fee`; a payment takes `fee`. ValueError
    for bytes that are not an order."""
    from .settle.v2 import pay
    o = pay.read_order(data)
    if o is None:
        raise ValueError("these bytes are not an order account of knos_pay")
    return {"state": o.state, "amount": o.amount, "fee": o.fee, "fee_bps": o.fee_bps, "decimals": o.decimals, "deadline": o.deadline,
            "grace": o.grace, "terms": o.terms.hex(), "funded_under": "2.1" if o.inc == 0 else "2.2 or later",
            "refund": o.amount + o.fee, "fee_now": pay.order_fee(o.amount, pay.FEE_BPS, o.decimals)}
