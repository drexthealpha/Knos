"""What a paid record lookup adds to the free file (docs/RECORD.md section 5; served by knos.record_api).

    knos record verify ANSWER          checks a paid answer with no network: fresh, stale, unsigned or invalid
    knos record grant <slug>           the supplier signs a grant: a named reader may read named fields of its history
    knos record history <supplier>     writes <slug>.history.json: the fields that are not in the free file

The free file is a static page: no signature, and the day it was built. A paid answer is three more things.

    freshness    the server signs (Ed25519, a key the operator supplies) the record's hash, the time and slot it read
                 the chain, when it produced the answer and when the answer expires. The shape is the one a
                 certificate status answer has (RFC 6960: thisUpdate, producedAt, nextUpdate): a reader holds the
                 answer to its own clock, and an answer past its expiry is stale whoever signed it.
    history      per-buyer breakdown, dispute and appeal outcomes, corrections, time to accept. Not in the free file.
                 The supplier releases each field to a named reader with a grant it signs; without a grant the
                 answer says "not granted" and never the data. A grant costs the supplier nothing.
    summary      the same counts for every supplier, each with its sample and its 95% Wilson interval, computed as the
                 Agent PR Index computes its intervals. No score: every figure names its numerator and denominator.

Revenue from lookups is budgeted at zero until someone buys one. Standard library at import; solders when a
signature is made or checked.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any, Iterable

ANSWER, GRANT, HISTORY, SUMMARY = "knos.record-answer/1", "knos.record-grant/1", "knos.record-history/1", "knos.record-summary/1"
FIELDS = ("per_buyer", "disputes", "corrections", "time_to_accept")       # the history a supplier can release, field by field
FIELD_WORDS = {"per_buyer": "the counts buyer by buyer", "disputes": "disputes and appeals, with how each ended",
               "corrections": "every correction made to the supplier's events", "time_to_accept": "how long acceptance took"}
TTL = 3600                                                               # seconds an answer stays fresh, unless the operator says otherwise
NOT_GRANTED = "not granted"
NOT_A_RATING = "Counts with samples and intervals. Not a rating of defect-free work, and not a score."
BUDGET = "Revenue from record lookups is budgeted at zero until someone buys one."
PROMISE = {"uptime": "none", "support": "none", "retention": "none", "cluster": "devnet",
           "words": "The operator of this server promises nothing about availability. On devnet nothing is promised by anyone."}
FRESH, STALE, UNSIGNED, INVALID = "fresh", "stale", "unsigned", "invalid"
STATE_WORDS = {FRESH: "Fresh: signed, and inside its expiry.", STALE: "Stale: signed, and past its expiry. Ask again.",
               UNSIGNED: "Unsigned: nobody signed this answer. It is worth what the free file is.",
               INVALID: "Invalid: do not rely on this answer."}


def canon(o: Any) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(o: Any) -> str:
    return hashlib.sha256(canon(o).encode()).hexdigest()


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    """The 95% Wilson score interval of k in n, as scripts/agent_pr_index.py `wilson` gives it; None when n is 0."""
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, mid - half), 4), round(min(1.0, mid + half), 4)]


def _rate(k: int, n: int, of: str) -> dict:
    return {"k": int(k), "n": int(n), "of": of, "share": round(k / n, 4) if n else None, "ci95": wilson(k, n)}


# ---- the summary: the same arithmetic for every supplier -------------------------------------------------------------

def summary(doc: dict) -> dict:
    """A record (knos.supplier-record/1) as rates, each `{k, n, of, share, ci95}`. The denominators never change with
    the supplier: verdicts over deliverables that have a verdict, reverted over the sample, overturned over appealed,
    failed checks over the merged pull requests that claimed passing tests. Nothing is weighted and nothing is added
    into one figure."""
    c = {k: int(v["n"]) for k, v in doc["orders"]["counts"].items()}
    decided = c["accepted"] + c["rejected"] + c["insufficient_evidence"] + c["disputed"]
    p = doc.get("public")
    return {"schema": SUMMARY, "supplier": doc["supplier"], "as_of": doc["as_of"], "note": NOT_A_RATING, "score": None,
            "orders": {"category": doc["orders"]["category"], "sample": int(doc["orders"]["sample"]), "period": doc["orders"]["period"],
                       "accepted": _rate(c["accepted"], decided, "deliverables with a verdict"),
                       "rejected": _rate(c["rejected"], decided, "deliverables with a verdict"),
                       "insufficient_evidence": _rate(c["insufficient_evidence"], decided, "deliverables with a verdict"),
                       "disputed": _rate(c["disputed"], decided, "deliverables with a verdict"),
                       "reverted": _rate(c["reverted"], decided + c["reverted"], "deliverables on record"),
                       "overturned": _rate(c["overturned"], c["appealed"], "rejections appealed")},
            "public": {"category": p["category"], "week": p["week"], "weeks": p["weeks"],
                       "failed_at_merge": _rate(p["failed_at_merge"], p["sample"], "merged pull requests that claimed passing tests")} if p else None,
            "method": "Wilson score interval, z 1.96, rounded to four places: scripts/agent_pr_index.py wilson."}


# ---- the history: what is not in the free file -----------------------------------------------------------------------

def _spread(seconds: list[int]) -> dict:
    """How long acceptance took: nearest-rank percentiles and four buckets. With no times, it says so."""
    s = sorted(int(x) for x in seconds if int(x) >= 0)
    if not s:
        return {"n": 0, "unit": "seconds", "why": "no delivery and acceptance times were given: the events log keeps none"}
    rank = lambda q: s[max(0, math.ceil(q * len(s)) - 1)]      # noqa: E731
    return {"n": len(s), "unit": "seconds", "min": s[0], "p50": rank(0.5), "p90": rank(0.9), "max": s[-1],
            "buckets": {"under_1_hour": sum(x < 3600 for x in s), "under_1_day": sum(3600 <= x < 86_400 for x in s),
                        "under_7_days": sum(86_400 <= x < 604_800 for x in s), "7_days_or_more": sum(x >= 604_800 for x in s)}}


def history(supplier: str, *, log=None, supplier_ids: Iterable[str] = (), store=None, repos: Iterable[str] = (), times: Iterable[dict] = (),
            as_of: str | None = None) -> dict:
    """The permissioned history of `supplier` (knos.record-history/1), from the same sources a record is built from:
    the events log, the supplier's memory in the Sibyl engine, and `times` ({deliverable, delivered, accepted}, unix
    seconds, from whoever holds them: the log keeps none)."""
    from . import record_page
    who = record_page.slug(supplier)
    buyers: list[dict] = []
    appeals: list[dict] = []
    if store is not None:
        from .proof import history as memory
        for repo in sorted({str(r).strip("/") for r in repos}):
            got = memory.supplier_record(store, repo, supplier)
            if any(got[k] for k in memory.SUPPLIER_EVENTS):
                buyers.append({"buyer": repo.split("/")[0], "repository": repo, **{k: got[k] for k in memory.SUPPLIER_EVENTS}})
            appeals += [{"id": a["id"], "repository": repo, "pull_request": a["pull"], "state": a["state"], "reason": a["reason"], "why": a["why"],
                         "at": int(a["at"])} for a in memory.appeals(store, repo, supplier)]
    months: dict[int, dict[str, int]] = {}
    disputed: list[dict] = []
    fixes: list[dict] = []
    if log is not None:
        ids = tuple(supplier_ids) or (supplier, who)
        lines = sorted({n for s in ids for n in log.by_supplier.get(str(s), ())})
        seen: dict[str, int] = {}
        for n in lines:
            e = log.events[n]
            if e.first is not None:
                continue
            for f in log.fixes.get(e.id, ()):
                c = log.events[f]
                fixes.append({"correction": c.id, "corrects": e.id, "deliverable": e.deliverable, "void": c.void, "verdict": c.verdict, "amount": c.amount,
                              "unit": c.unit, "reason": c.reason, "line": f, "line_sha256": log.hashes[f]})
            if e.kind in ("evaluation", "acceptance") and e.deliverable and not log.state(e)[3]:
                seen.setdefault(e.deliverable, e.month)
        for dlv, month in sorted(seen.items()):
            verdict = log.verdict_of(dlv)[0]
            row = months.setdefault(month, {"accepted": 0, "rejected": 0, "insufficient_evidence": 0, "disputed": 0})
            row[verdict] += 1
            if verdict == "disputed":
                disputed.append({"deliverable": dlv, "month": month})
    fields: dict[str, Any] = {"per_buyer": {"by_repository": buyers, "by_month": [{"month": f"{m // 100:04d}-{m % 100:02d}" if m else None, **v} for m, v in sorted(months.items())],
                            "note": "A buyer is the owner of the repository an order was funded in. The events log names no buyer: it is counted by month."},
              "disputes": {"disputed": disputed, "appeals": sorted(appeals, key=lambda a: (a["at"], a["id"]))},
              "corrections": sorted(fixes, key=lambda f: f["line"]),
              "time_to_accept": _spread([int(t["accepted"]) - int(t["delivered"]) for t in times])}
    doc = {"schema": HISTORY, "supplier": who, "as_of": as_of or time.strftime("%Y-%m-%d", time.gmtime()), "fields": fields,
           "sources": {"events": {"read": log is not None, **({"head": log.head, "lines": len(log.events)} if log is not None else {})},
                       "memory": {"read": store is not None, "repositories": sorted({str(r).strip("/") for r in repos}) if store is not None else []},
                       "times": {"n": fields["time_to_accept"]["n"]}}}
    return {**doc, "sha256": sha(doc)}


def check_history(doc, supplier: str | None = None) -> str | None:
    if not isinstance(doc, dict) or doc.get("schema") != HISTORY or tuple(doc.get("fields") or ()) != FIELDS:
        return f"not a {HISTORY} file"
    if sha({k: v for k, v in doc.items() if k != "sha256"}) != doc.get("sha256"):
        return "the history does not hash to the sha256 it states"
    return None if supplier in (None, doc["supplier"]) else "the history is another supplier's"


# ---- keys, and the grant a supplier signs ----------------------------------------------------------------------------

def load_key(path: Path):
    """A signing key from a file: the JSON list of 64 numbers solana-keygen writes."""
    from solders.keypair import Keypair
    return Keypair.from_bytes(bytes(json.loads(Path(path).read_text(encoding="utf-8"))))


def _signed(body: dict, tag: str, key) -> dict:
    out = {**body, "key": str(key.pubkey())}
    return {**out, "signature": str(key.sign_message(f"{tag}\n{canon(out)}".encode()))}


def _signer_ok(doc: dict, tag: str) -> bool:
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    body = {k: v for k, v in doc.items() if k != "signature"}
    try:
        return bool(Signature.from_string(str(doc["signature"])).verify(Pubkey.from_string(str(doc["key"])), f"{tag}\n{canon(body)}".encode()))
    except (ValueError, TypeError, KeyError):
        return False


def grant(key, supplier: str, reader: str, fields: Iterable[str], issued: int, not_after: int) -> dict:
    """The supplier's grant: `reader` (the wallet that pays for lookups) may read `fields` of `supplier`'s history
    until `not_after`. Signed with the supplier's key; whoever serves must already hold that key for the supplier."""
    from . import record_page
    want = sorted(set(fields))
    if not want or set(want) - set(FIELDS):
        raise ValueError(f"a grant names one or more of: {', '.join(FIELDS)}")
    if int(not_after) <= int(issued):
        raise ValueError("a grant ends after it starts")
    return _signed({"schema": GRANT, "supplier": record_page.slug(supplier), "reader": str(reader), "fields": want, "issued": int(issued),
                    "not_after": int(not_after)}, GRANT, key)


def check_grant(doc, supplier: str, reader: str, supplier_key: str | None, now: int) -> tuple[list[str], str | None]:
    """(the fields a grant releases, None) or ([], why not). `supplier_key`: the key the server holds for the
    supplier, from its operator; the grant's own word for who signed it is never enough."""
    if not isinstance(doc, dict) or doc.get("schema") != GRANT:
        return [], "no grant was shown"
    if supplier_key is None:
        return [], "this server holds no key for the supplier, so it can check no grant"
    if doc.get("key") != supplier_key or not _signer_ok(doc, GRANT):
        return [], "the grant is not signed by the supplier's key"
    if doc.get("supplier") != supplier:
        return [], "the grant is for another supplier"
    if doc.get("reader") != reader:
        return [], "the grant names another reader"
    if not (int(doc.get("issued", 0)) <= int(now) <= int(doc.get("not_after", 0))):
        return [], "the grant is not in force at this time"
    return [f for f in doc.get("fields", []) if f in FIELDS], None


# ---- the answer ------------------------------------------------------------------------------------------------------
FIVE = ("identity", "execution", "acceptance", "consequence", "assurance")      # knos.receipt.FIVE: every answer carries all five


def parts_of(doc: dict, read_time: int, slot: int | None) -> dict:
    """The five parts of a paid answer, one line each, written from the record and the read: who produced the evidence,
    what was read, what was accepted, what the answer authorises, and what stays trusted."""
    c = {k: int(v["n"]) for k, v in doc["orders"]["counts"].items()}
    decided = c["accepted"] + c["rejected"] + c["insufficient_evidence"] + c["disputed"]
    head = (doc["orders"]["parts"]["events"] or {}).get("head")
    when = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(int(read_time)))
    return {"identity": f"The record of {doc['supplier']} (sha256 {doc['sha256']}), as of {doc['as_of']}, built from "
                        + (f"the log of events with head {head}" if head else "no log of events") + "; the answer is signed by the server's operator, or unsigned.",
            "execution": f"The server read the chain at {when}" + (f", slot {slot}" if slot is not None else ", at no slot it names") + ", and ran the arithmetic every record gets.",
            "acceptance": f"{c['accepted']} of {decided} deliverables with a verdict were accepted, each under its own terms; this answer accepts nothing itself.",
            "consequence": "The reader paid for this lookup. It authorises no payment to the supplier and moves no money.",
            "assurance": "reported: each count is the record's word, as built from the log and the chain; the signature says when it was read, not that the work was good. "
                         + NOT_A_RATING}


def answer(doc: dict, *, reader: str, read_time: int, slot: int | None, produced: int, ttl: int = TTL, key=None, past: dict | None = None,
           granted: Iterable[str] = (), why: str | None = None, grant_doc: dict | None = None, promise: dict | None = None) -> dict:
    """The paid answer for one record. `key`: the operator's signing key, or None (then the answer is unsigned and says
    so). `past`: the supplier's history file, or None. `granted`: the fields a checked grant released to `reader`."""
    released = set(granted)
    hist: dict[str, dict] = {}
    for f in FIELDS:
        if f not in released:
            hist[f] = {"granted": False, "state": NOT_GRANTED, "what": FIELD_WORDS[f]}
        elif past is None:
            hist[f] = {"granted": True, "state": "nothing on file", "what": FIELD_WORDS[f]}
        else:
            hist[f] = {"granted": True, "state": "released", "what": FIELD_WORDS[f], "data": past["fields"][f]}
    body = {"schema": ANSWER, "supplier": doc["supplier"], "reader": str(reader),
            "root": {"record_sha256": doc["sha256"], "events_head": (doc["orders"]["parts"]["events"] or {}).get("head"),
                     "history_sha256": past["sha256"] if past is not None and released else None},
            "read": {"time": int(read_time), "slot": slot, "source": "the cluster's clock, as the programs see it"},
            "produced": int(produced), "expires": int(produced) + int(ttl),
            "summary": summary(doc), "parts": parts_of(doc, read_time, slot),
            "history": hist, "grant": {"sha256": sha(grant_doc) if grant_doc is not None and released else None, "refused": None if released else (why or "no grant was shown")},
            "availability": dict(promise or PROMISE), "who_pays": "The reader pays. The rated supplier never pays, for the record or for a grant.",
            "budget": BUDGET}
    if key is None:
        return {**body, "key": None, "signature": None}
    return _signed(body, ANSWER, key)


def verify(reply: dict, now: int, operator: str | None = None) -> dict:
    """A paid reply ({record, answer, ...}) checked with no network. Returns {state, why, ...}: `fresh` only when the
    record hashes to what was signed, the summary is the record's, the signature is the key's, the key is `operator`
    when one is named, and `now` is inside produced..expires."""
    from . import record_page
    out: dict[str, Any] = {"state": INVALID, "why": "", "key": None, "produced": None, "expires": None, "read": None}

    def end(state: str, why: str) -> dict:
        return {**out, "state": state, "why": why, "words": STATE_WORDS[state]}
    if isinstance(reply, dict) and reply.get("schema") == record_page.SCHEMA:
        return end(UNSIGNED, "this is the free record file: it carries no signature and no expiry")
    if not isinstance(reply, dict) or not isinstance(reply.get("answer"), dict) or reply["answer"].get("schema") != ANSWER:
        return end(INVALID, f"not a {ANSWER} reply")
    a, doc = reply["answer"], reply.get("record")
    out.update(key=a.get("key"), produced=a.get("produced"), expires=a.get("expires"), read=a.get("read"))
    bad = record_page.check(doc)
    if bad or not isinstance(doc, dict):
        return end(INVALID, f"the record in the reply does not check: {bad}")
    try:
        if a["root"]["record_sha256"] != doc["sha256"] or a["supplier"] != doc["supplier"]:
            return end(INVALID, "the answer is about another record than the one it came with")
        if a["summary"] != summary(doc):
            return end(INVALID, "the summary is not the one this record gives")
        if a.get("parts") != parts_of(doc, a["read"]["time"], a["read"]["slot"]):
            return end(INVALID, "the answer does not carry its five parts (identity, execution, acceptance, consequence, assurance), or they are not this record's")
        produced, expires = int(a["produced"]), int(a["expires"])
        for f in FIELDS:
            h = a["history"][f]
            if ("data" in h) != (h["state"] == "released") or (not h["granted"] and h["state"] != NOT_GRANTED):
                return end(INVALID, f"the history field {f} does not say plainly whether it was granted")
    except (KeyError, TypeError, ValueError):
        return end(INVALID, "the answer lacks a field every answer has")
    if a.get("signature") is None and a.get("key") is None:
        return end(UNSIGNED, "the server that gave this answer had no signing key")
    if not _signer_ok(a, ANSWER):
        return end(INVALID, "the signature is not the key's over this answer")
    if operator is not None and a["key"] != operator:
        return end(INVALID, f"signed by {a['key']}, not by the operator named ({operator})")
    if expires <= produced or int(now) < produced - 300:
        return end(INVALID, "the answer's times do not stand: it expires before it was produced, or it is from the future")
    if int(now) > expires:
        return end(STALE, f"it expired {int(now) - expires} seconds ago")
    return end(FRESH, f"signed by {a['key']}" + ("" if operator else ": check that this is the operator you trust (--operator)") + f"; {expires - int(now)} seconds left")


def lines(v: dict) -> list[str]:
    day = lambda t: time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(int(t)))      # noqa: E731
    out = [v["words"], f"Why: {v['why']}."]
    if v.get("produced") is not None:
        read = v.get("read") or {}
        out.append(f"Read the chain at {day(read.get('time', 0))}" + (f", slot {read['slot']}" if read.get("slot") is not None else "")
                   + f". Produced {day(v['produced'])}. Expires {day(v['expires'])}.")
    return out


# ---- the commands (knos.badge hands `knos record verify|grant|history` here) -----------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="knos record", description="A paid record answer: check one, grant a reader, write the history. " + BUDGET)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="check a paid answer with no network")
    v.add_argument("answer", type=Path)
    v.add_argument("--operator", default=None, help="the key the operator you trust signs with")
    v.add_argument("--at", type=int, default=None, help="the time to hold it to, unix seconds (default: now)")
    v.add_argument("--json", action="store_true")
    g = sub.add_parser("grant", help="the supplier lets a named reader read fields of its history")
    g.add_argument("supplier")
    g.add_argument("--reader", required=True, help="the wallet that pays for the reader's lookups")
    g.add_argument("--field", action="append", default=[], choices=FIELDS)
    g.add_argument("--key", type=Path, required=True, help="the supplier's signing key (a solana-keygen file)")
    g.add_argument("--days", type=int, default=30)
    g.add_argument("--at", type=int, default=None)
    g.add_argument("--out", type=Path, default=None)
    h = sub.add_parser("history", help="write <slug>.history.json")
    h.add_argument("supplier")
    h.add_argument("--events", type=Path, default=None)
    h.add_argument("--id", action="append", default=[])
    h.add_argument("--memory", type=Path, default=None)
    h.add_argument("--repo", action="append", default=[])
    h.add_argument("--times", type=Path, default=None, help="a JSON list of {deliverable, delivered, accepted} in unix seconds")
    h.add_argument("--as-of", default=None)
    h.add_argument("--out", type=Path, default=Path("record-history"))
    a = ap.parse_args(argv)
    try:
        if a.cmd == "verify":
            got = verify(json.loads(a.answer.read_text(encoding="utf-8")), a.at if a.at is not None else int(time.time()), a.operator)
            print(json.dumps(got, indent=1) if a.json else "\n".join(lines(got)))
            return 0 if got["state"] == FRESH else 1
        if a.cmd == "grant":
            at = a.at if a.at is not None else int(time.time())
            doc = grant(load_key(a.key), a.supplier, a.reader, a.field or FIELDS, at, at + a.days * 86_400)
            out = a.out or Path(f"{doc['supplier']}.grant.json")
            out.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
            print(f"Wrote {out}: {doc['reader']} may read {', '.join(doc['fields'])} for {a.days} days. Signed by {doc['key']}. The supplier paid nothing.")
            return 0
        log = store = None
        if a.events is not None:
            from . import events
            log = events.load(a.events)
        if a.memory is not None:
            from .proof import history as memory
            store = memory.SibylStore.local(a.memory)
        times = json.loads(a.times.read_text(encoding="utf-8")) if a.times else []
        doc = history(a.supplier, log=log, supplier_ids=a.id, store=store, repos=a.repo, times=times, as_of=a.as_of)
        a.out.mkdir(parents=True, exist_ok=True)
        path = a.out / f"{doc['supplier']}.history.json"
        path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"Wrote {path}. Keep it out of the free folder: it is served only against the supplier's grant.")
        return 0
    except (OSError, ValueError) as why:
        print(f"Nothing was done: {why}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
