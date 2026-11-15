"""A supplier's public record, the badge it gives, and the receipt a supplier sends with an invoice.

    knos record build <supplier>      writes docs/records/<slug>.json (docs/reference/RECORD.md): what is on record for one agent
                                      builder, agency or vendor, each figure with its sample, period and category
    knos badge record <slug>          an SVG from that file, and the Markdown that links it to the record's page
    knos record receipt <receipt>     one PDF page and its JSON for an acceptance receipt (docs/reference/RECEIPT.md): what was
                                      agreed, delivered and accepted, by which evaluator, the evidence, how to check it

    python -m knos.record_api         the same files behind a paid lookup, 0.10 test USDC a call (knos.record_api,
                                      examples/record_api): a server anyone can run, and Knos hosts none. Its answer
                                      adds a signature with an expiry, a summary, and the history a supplier grants
                                      (knos.record_answer); this file stays free and unsigned

A record has two parts, kept apart and each labelled with where it came from:

    orders    work settled through Knos. Counted from the events log (knos.events: deliverables accepted, rejected,
              left with insufficient evidence, disputed, reverted by a correction) and from the supplier's memory in
              the Sibyl engine (knos.proof.history `supplier_record`, `appeals`: pull requests accepted and rejected
              under funded orders, appeals, rejections overturned). Every count lists the evidence behind it.
    public    for an agent the Agent PR Index measures, its row (docs/index.json): from public pull requests, not from
              Knos orders. The interval and the dispute link stay beside the rate.

Nothing here is a score, and nothing here reads a payment to Knos: the supplier never pays for a record and cannot
pay to change one. The file is not signed; the evidence each count links to is (docs/reference/RECORD.md says which).

Standard library only at import: the script that writes the index (scripts/agent_pr_board.py) imports this module.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

SCHEMA = "knos.supplier-record/1"
RECEIPT_SCHEMA = "knos.invoice-receipt/1"
SITE = "https://drexthealpha.github.io/Knos"
REPO = "https://github.com/drexthealpha/Knos"
RAW = "https://raw.githubusercontent.com/drexthealpha/Knos/main/docs/records"
TEMPLATE = "dispute-index-row.yml"
RULE = "The supplier never pays for this record and cannot pay to change it."
NOT_A_SCORE = "Counts with their samples. Nothing here is a score."
PUBLIC_LABEL = "from public pull requests, not from Knos orders"
ORDERS_LABEL = "work settled through Knos"
ORDER_COUNTS = ("accepted", "rejected", "insufficient_evidence", "disputed", "appealed", "overturned", "reverted")
COUNT_WORDS = {"accepted": "accepted", "rejected": "rejected", "insufficient_evidence": "insufficient evidence", "disputed": "disputed",
               "appealed": "appealed", "overturned": "overturned on appeal", "reverted": "reverted"}
EVENTS_CATEGORY = "deliverables evaluated under Knos orders and meters"
MEMORY_CATEGORY = "pull requests judged under funded Knos orders"
PUBLIC_CATEGORY = "merged pull requests whose description claimed passing tests"
LIMITS = (
    "Knos wrote this file and nobody outside Knos has reviewed it: dispute it with the link in it.",
    "The file is not signed. The evidence a count links to is: a transaction, a batch root, or a log line's hash.",
    "A failed check is not always a failed test or a false claim.",
    "Accepted means the agreed checks passed. It does not show that the work has no defect.",
    "Nothing recorded is not the same as nothing done.",
)
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def slug(name: str) -> str:
    """The record's file name for a supplier: lower case letters, digits and single dashes, 64 at most. ValueError
    when nothing is left."""
    s = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")[:64].strip("-")
    if not _SLUG.fullmatch(s):
        raise ValueError("a supplier's name needs a letter or a digit")
    return s


def canon(o: Any) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def dispute_url(who: str, week: str | None = None) -> str:
    """A new issue with the supplier filled in: the same form a row of the index is disputed with."""
    from urllib.parse import urlencode
    return f"{REPO}/issues/new?" + urlencode({"template": TEMPLATE, "title": f"Dispute a record: {who}", "agent": who, **({"week": week} if week else {})})


def page_url(who: str) -> str:
    return f"{SITE}/#record={who}"


# ---- the public part: the agent's row of the index -------------------------------------------------------------------

def public_part(index: dict | None, who: str) -> dict | None:
    """The agent's row of the newest week of docs/index.json, with the week, the day it was read and the sample. None
    when the index does not measure this supplier."""
    if not index or not index.get("weeks"):
        return None
    top = index["weeks"][0]
    row = next((r for r in top["rows"] if slug(r["agent"]) == who), None)
    if row is None:
        return None
    return {"label": PUBLIC_LABEL, "source": "docs/index.json", "source_sha256": (index.get("source") or {}).get("sha256_of_canonical_json"),
            "category": PUBLIC_CATEGORY, "week": top["week"], "read": top.get("read"), "weeks": row["weeks"],
            "period": {"from": index["weeks"][-1]["week"], "to": top["week"], "unit": "week starting"},
            "claimed_passing": row["claimed_passing"], "sample": row["merged"], "failed_at_merge": row["failed_at_merge"],
            "share": row["share"], "ci95": row["ci95"], "rank": row["rank"], "status": row["status"], "min_sample_to_rank": top.get("min_claims_to_rank"),
            "overlaps_above": row.get("overlaps_above", False), "disputed": row.get("disputed", []), "dispute": row["dispute"],
            "method": (index.get("links") or {}).get("page", f"{REPO}/blob/main/docs/reference/INDEX.md")}


# ---- the orders part: the events log, and the supplier's memory -----------------------------------------------------

def _empty() -> dict:
    return {k: {"n": 0, "from": "nothing on record", "evidence": []} for k in ORDER_COUNTS}


def from_events(log, supplier_ids) -> dict:
    """What the events log holds for a supplier (knos.events.Log; `supplier_ids`: the names its events carry). A
    deliverable is counted once, under the verdict it has after every correction; one whose acceptance, evaluation or
    payment a correction voided is counted as reverted and under no verdict. Each piece of evidence is the line, its hash in the chain, and where the issuer's evidence is."""
    lines = sorted({n for s in supplier_ids for n in log.by_supplier.get(str(s), ())})
    seen: dict[str, dict] = {}
    reverted: list[dict] = []
    months: list[int] = []
    for n in lines:
        e = log.events[n]
        if e.first is not None or e.kind not in ("evaluation", "acceptance", "settlement"):
            continue
        if e.month:
            months.append(e.month)
        where = {"deliverable": e.deliverable, "event": e.id, "line": n, "line_sha256": log.hashes[n], "evidence": e.evidence, "month": e.month, "source": e.source}
        if log.state(e)[3]:
            fix = log.events[log.fixes[e.id][-1]]
            reverted.append({**where, "correction": fix.id, "reason": fix.reason})
        elif e.kind != "settlement" and e.deliverable:
            if e.kind == "acceptance" or e.deliverable not in seen:
                seen[e.deliverable] = where
    gone = {r["deliverable"] for r in reverted}           # a deliverable whose acceptance or payment was voided is reverted, whatever its evaluation said
    seen = {dlv: where for dlv, where in seen.items() if dlv not in gone}
    counts: dict[str, list[dict]] = {k: [] for k in ("accepted", "rejected", "insufficient_evidence", "disputed")}
    for dlv, where in sorted(seen.items()):
        counts[log.verdict_of(dlv)[0]].append(where)
    counts["reverted"] = reverted
    return {"read": True, "source": "the events log (knos.events)", "head": log.head, "lines": len(log.events), "category": EVENTS_CATEGORY,
            "sample": len(seen) + len(gone),
            "period": {"from": _month(min(months)) if months else None, "to": _month(max(months)) if months else None, "unit": "month"},
            "counts": {k: {"n": len(v), "evidence": v} for k, v in counts.items()}}


def _month(m: int) -> str:
    return f"{m // 100:04d}-{m % 100:02d}"


def from_memory(store, repos, supplier) -> dict:
    """What the Sibyl engine remembers of a supplier in `repos` (knos.proof.history): pull requests accepted and
    rejected under funded orders, appeals opened and rejections overturned. The evidence of a count is the pull
    requests behind it, and for an appeal its id."""
    from .proof import history
    counts: dict[str, list[dict]] = {k: [] for k in history.SUPPLIER_EVENTS}
    named = {history.repo_key(r): str(r).strip("/") for r in sorted(map(str, repos), reverse=True)}      # the memory keys a repository by its name
    for _key, repo in sorted(named.items()):
        got = history.supplier_record(store, repo, supplier)
        ids = {b["pull"]: b["id"] for b in history.appeals(store, repo, supplier)}
        for event in history.SUPPLIER_EVENTS:
            for pull in got["pulls"][event]:
                where = {"repository": repo, "pull_request": pull, "url": f"https://github.com/{repo}/pull/{pull}" if repo.count("/") == 1 else None}
                counts[event].append({**where, **({"appeal": ids[pull]} if event in ("appealed", "overturned") and pull in ids else {})})
    judged = {(w["repository"], w["pull_request"]) for k in ("accepted", "rejected") for w in counts[k]}
    return {"read": True, "source": "the supplier's memory in the Sibyl engine (knos.proof.history supplier_record, appeals)",
            "repositories": sorted(named.values()), "category": MEMORY_CATEGORY, "sample": len(judged),
            "period": {"from": None, "to": None, "unit": "not kept: the memory holds the pull requests, not a calendar"},
            "counts": {k: {"n": len(v), "evidence": v} for k, v in counts.items()}}


def orders_part(events: dict | None, memory: dict | None) -> dict:
    """The two sources as one set of counts, each saying where it came from. Accepted and rejected come from the
    events log when it holds this supplier, from memory otherwise (never added: they count the same work twice).
    Insufficient evidence, disputed and reverted are the log's; appealed and overturned are the memory's."""
    counts = _empty()
    use_log = bool(events and events["sample"])
    for part, keys in ((events if use_log else None, ("accepted", "rejected", "insufficient_evidence", "disputed", "reverted")),
                       (memory, ("appealed", "overturned") if use_log else ("accepted", "rejected", "appealed", "overturned"))):
        for k in keys if part else ():
            c = part["counts"].get(k)        # type: ignore[index]
            if c is not None and (c["n"] or part is events):
                counts[k] = {"n": c["n"], "from": "events" if part is events else "memory", "evidence": c["evidence"]}
    main = events if use_log else memory
    none = {"read": False, "why": "not given when this file was built"}
    return {"label": ORDERS_LABEL, "category": main["category"] if main else EVENTS_CATEGORY, "sample": main["sample"] if main else 0,
            "period": main["period"] if main else {"from": None, "to": None, "unit": "month"}, "counts": counts,
            "parts": {"events": {k: v for k, v in (events or none).items() if k != "counts"}, "memory": {k: v for k, v in (memory or none).items() if k != "counts"}}}


# ---- the record ------------------------------------------------------------------------------------------------------

def build(supplier: str, *, index: dict | None = None, log=None, supplier_ids=(), store=None, repos=(), as_of: str | None = None) -> dict:
    """The record of `supplier`. `index`: docs/index.json as read. `log`: an events log, and `supplier_ids` the names
    its events carry for this supplier (default: the supplier's name). `store`, `repos`: the Sibyl store and the
    repositories to recall the supplier in. `as_of`: the day written in the file (default: the day the index was read
    when only the index is used, so the same index gives the same bytes)."""
    who = slug(supplier)
    public = public_part(index, who)
    events = from_events(log, tuple(supplier_ids) or (supplier, who)) if log is not None else None
    memory = from_memory(store, repos, supplier) if store is not None and repos else None
    orders = orders_part(events, memory)
    day = as_of or (public["read"] if public and not orders["sample"] else None) or time.strftime("%Y-%m-%d", time.gmtime())
    doc = {"schema": SCHEMA, "supplier": who, "name": str(supplier), "as_of": day, "rule": RULE, "not_a_score": NOT_A_SCORE,
           "orders": orders, "public": public, "limits": list(LIMITS),
           "links": {"page": page_url(who), "file": f"{RAW}/{who}.json", "dispute": dispute_url(who, public["week"] if public else None),
                     "specification": f"{REPO}/blob/main/docs/reference/RECORD.md"}}
    return {**doc, "sha256": hashlib.sha256(canon(doc).encode()).hexdigest()}


def check(doc) -> str | None:
    """None when `doc` is a record this version wrote and nobody changed; else why not, in one sentence."""
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return f"not a {SCHEMA} file"
    body = {k: v for k, v in doc.items() if k != "sha256"}
    if hashlib.sha256(canon(body).encode()).hexdigest() != doc.get("sha256"):
        return "the file does not hash to the sha256 it states"
    if tuple(doc["orders"]["counts"]) != ORDER_COUNTS or any(c["n"] != len(c["evidence"]) for c in doc["orders"]["counts"].values()):
        return "a count does not list the evidence behind it"
    return None


def text(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def index_records(index: dict) -> dict[str, str]:
    """Every agent of the index's newest week as a record file's text and its badge, by file name: what
    scripts/agent_pr_board.py writes beside the index, from the index alone."""
    out: dict[str, str] = {}
    for r in index["weeks"][0]["rows"]:
        doc = build(r["agent"], index=index)
        out[f"{doc['supplier']}.json"] = text(doc)
        out[f"{doc['supplier']}.svg"] = badge_svg(doc)
    return out


def lines(doc: dict) -> list[str]:
    """The record in words, for the command line."""
    o, p = doc["orders"], doc["public"]
    span = f"{o['period']['from']} to {o['period']['to']}" if o["period"]["from"] else "no period on record"
    out = [f"{doc['name']}: record as of {doc['as_of']}. {NOT_A_SCORE}",
           f"Work settled through Knos ({o['category']}; sample {o['sample']}; {span}): "
           + ", ".join(f"{c['n']} {COUNT_WORDS[k]}" for k, c in o["counts"].items()) + "."]
    if p:
        out.append(f"From public pull requests, not from Knos orders: {p['failed_at_merge']} of {p['sample']} {p['category']} had a failed check"
                   + (f" ({p['share'] * 100:.1f}%, 95% interval {p['ci95'][0] * 100:.1f}% to {p['ci95'][1] * 100:.1f}%)" if p["ci95"] else "")
                   + f", over {p['weeks']} weeks to the week of {p['week']}.")
    return [*out, RULE, f"Dispute it: {doc['links']['dispute']}"]


# ---- the badge -------------------------------------------------------------------------------------------------------

RECORD_LABEL = "Knos record"


def badge_data(doc: dict) -> dict:
    """What the badge says, from the record alone: {label, message, title, colour}. With work settled through Knos it
    is "Knos-verified" and counts it; without, it says so and gives the public row. The sample is always stated.
    web/badge.js `recordBadge` gives the same four strings."""
    from . import badge
    o, p = doc["orders"], doc["public"]
    c = {k: v["n"] for k, v in o["counts"].items()}
    if o["sample"]:
        span = f", {o['period']['from']} to {o['period']['to']}" if o["period"]["from"] else f", as of {doc['as_of']}"
        label, msg = badge.VERIFIED_LABEL, f"{c['accepted']} accepted, {c['reverted']} reverted, sample {o['sample']}{span}"
    elif p and p["sample"]:
        label, msg = RECORD_LABEL, f"no Knos orders yet; public PRs: {p['failed_at_merge']} of {p['sample']} had a failed check, week of {p['week']}"
    else:
        label, msg = RECORD_LABEL, f"nothing on record, as of {doc['as_of']}"
    tip = f"{label}: {doc['name']}. {msg}. {NOT_A_SCORE} {RULE}"
    return {"label": label, "message": msg, "title": tip, "colour": "#1a7f37" if o["sample"] and c["accepted"] else "#57606a"}


def badge_svg(doc: dict) -> str:
    """The record's badge: the same drawing as every Knos badge (knos.badge._draw). Green only with accepted work
    settled through Knos; grey otherwise. web/badge.js `recordBadgeSvg` writes the same bytes."""
    from . import badge
    b = badge_data(doc)
    return badge._draw(b["label"], b["message"], b["title"], b["colour"])


def badge_markdown(doc: dict, image: str) -> str:
    b = badge_data(doc)
    return f"[![{b['label']}: {b['message']}]({image})]({doc['links']['page']})"


# ---- the receipt a supplier sends with an invoice --------------------------------------------------------------------

VERIFY = "knos receipt {file}"
RECEIPT_LIMIT = "This page restates an acceptance receipt. The receipt file is the evidence; check it with the command above."


def _money(units, decimals: int) -> str:
    """Base units as money is written: two decimals, or as many as it takes."""
    whole, part = divmod(int(units), 10 ** decimals)
    return f"{whole:,}.{str(part).rjust(decimals, '0').rstrip('0').ljust(2, '0')}"


def invoice_receipt(receipt: dict, file_name: str = "receipt.json", invoice: str = "") -> dict:
    """One acceptance receipt (docs/reference/RECEIPT.md, version 2 or later) as what a finance operator reads: what was agreed,
    delivered and accepted, by which evaluator, the evidence, and the one command that checks the file with no
    network. ValueError for a receipt that does not check: there is nothing to send for it."""
    from . import ids
    from . import receipt as rc
    why = rc.check(receipt)
    if why is None and receipt.get("version", 1) < 2:
        why = "a version 1 receipt names no verdict"
    if why:
        raise ValueError(f"the receipt does not check: {why}")
    seen, policy, amounts = receipt["evaluator_observed"], receipt["policy"], receipt.get("amounts") or {}
    auth, tx = receipt.get("issuer_authenticated") or {}, receipt.get("transaction") or {}
    dec = int(amounts.get("decimals", 6))
    money = "test USDC" if str(receipt.get("cluster")) != "mainnet" else "USDC"
    verdict = ids.verdict(seen["verdict"])
    doc = {"schema": RECEIPT_SCHEMA, "invoice": invoice, "receipt_sha256": rc.digest(receipt), "receipt_version": receipt.get("version"),
           "cluster": receipt.get("cluster"), "money": money,
           "agreed": {"order": receipt["order"], "terms_sha256": policy["terms_hash"], "mode": policy["mode"],
                      "allowed_paths": policy.get("allowed_paths", []), "denied_paths": policy.get("denied_paths", []),
                      "amount": _money(amounts["of"], dec) if amounts.get("of") is not None else None},
           "delivered": {"repository_id": (receipt.get("repository") or {}).get("id"), "pull_request": seen["artifact"].get("pull_request"),
                         "commit": seen["artifact"].get("commit")},
           "accepted": {"verdict": verdict, "words": ids.VERDICT_WORDS[verdict], "checks": seen.get("checks", []),
                        "at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(tx["time"])) if tx.get("time") else None,
                        "paid": _money(amounts["paid"], dec) if amounts.get("paid") is not None and tx else None},
           "evaluator": {"kind": seen["judge"]["kind"], "version": seen["judge"]["version"], "issuer": auth.get("issuer"),
                         "workflow": (auth.get("claims") or {}).get("job_workflow_ref") or (auth.get("claims") or {}).get("ci_config_ref_uri"),
                         "independence": seen.get("independence", "")},
           "evidence": {"receipt_sha256": rc.digest(receipt), "terms_sha256": policy["terms_hash"], "token_sha256": auth.get("token_sha256"),
                        "signature_verified_in": (auth.get("verified") or {}).get("transaction"), "payment": tx.get("signature"),
                        "ids": receipt.get("ids")},
           "verify": {"command": VERIFY.format(file=file_name), "needs": "the receipt file and Knos installed; no network", "expect": rc.digest(receipt)},
           "limits": [RECEIPT_LIMIT, *(receipt.get("limitations") or receipt.get("trust_remaining") or [])[:3]]}
    return {**doc, "sha256": hashlib.sha256(canon(doc).encode()).hexdigest()}


def invoice_pdf(doc: dict) -> bytes:
    """`invoice_receipt` as one A4 page (knos.pdf: the same calls give the same bytes)."""
    from . import pdf
    a, d, acc, ev, e = doc["agreed"], doc["delivered"], doc["accepted"], doc["evaluator"], doc["evidence"]
    day = (acc["at"] or "1970-01-01")[:10]
    page = pdf.Doc(f"Verified receipt {doc['receipt_sha256'][:12]}", created=day, size=pdf.A4, footer=f"Knos verified receipt  {doc['receipt_sha256']}")
    page.text("Verified receipt" + (f" for invoice {doc['invoice']}" if doc["invoice"] else ""), size=15, bold=True)
    page.text(f"Verdict: {acc['words']}." + (f" Paid {acc['paid']} {doc['money']}." if acc["paid"] else " No payment is recorded."), size=11, bold=True)
    page.space()
    w = [110.0, 413.0]
    none = "not stated"
    for head, rows in (
        ("Agreed", [["order", a["order"]], ["terms (sha256)", a["terms_sha256"]], ["accepted on", "a merge" if a["mode"] == "merge" else "the named checks"],
                    ["paths", ", ".join(a["allowed_paths"]) or "any"], ["amount", f"{a['amount']} {doc['money']}" if a["amount"] else none]]),
        ("Delivered", [["repository id", str(d["repository_id"] or none)], ["pull request", str(d["pull_request"] or none)], ["commit", str(d["commit"] or none)]]),
        ("Accepted", [["verdict", acc["words"]], ["when", acc["at"] or none],
                      ["checks", ", ".join(f"{c['name']}: {c['conclusion']}" for c in acc["checks"]) or "none named"]]),
        ("Evaluator", [["kind", f"{ev['kind']} at {ev['version']}"], ["signed by", str(ev["issuer"] or "nobody: the run's own record")],
                       ["workflow", str(ev["workflow"] or none)], ["independence", ev["independence"] or none]]),
        ("Evidence", [["receipt (sha256)", e["receipt_sha256"]], ["token (sha256)", str(e["token_sha256"] or none)],
                      ["signature verified in", str(e["signature_verified_in"] or none)], ["payment", str(e["payment"] or none)],
                      *[[k.replace("_", " "), str(v)] for k, v in (e["ids"] or {}).items() if v]]),
    ):
        page.text(head, size=10, bold=True)
        page.table(["", ""], rows, w, size=7.5)
        page.space(6)
    page.text("Check it yourself, with no network", size=10, bold=True)
    page.text(doc["verify"]["command"], size=10)
    page.text(f"It prints the digest {doc['verify']['expect']}.", size=8)
    page.space(6)
    for line in doc["limits"]:
        page.text(line, size=7.5)
    return page.render()


# ---- the commands (registered by knos.badge, which owns `knos record` and `knos badge`) ------------------------------

def run_build(supplier: str, out_dir: Path, index_path: Path | None, events_path: Path | None, ids_: list[str], memory: Path | None, repos: list[str],
              as_of: str | None) -> tuple[Path, dict]:
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path and index_path.is_file() else None
    log = store = None
    if events_path is not None:
        from . import events
        log = events.load(events_path)
    if memory is not None:
        from .proof import history
        store = history.SibylStore.local(memory)
    doc = build(supplier, index=index, log=log, supplier_ids=ids_, store=store, repos=repos, as_of=as_of)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{doc['supplier']}.json"
    path.write_text(text(doc), encoding="utf-8", newline="\n")
    path.with_suffix(".svg").write_text(badge_svg(doc), encoding="utf-8", newline="\n")
    return path, doc


def run_receipt(source: Path, out: Path | None, invoice: str) -> tuple[Path, Path, dict]:
    receipt = json.loads(source.read_text(encoding="utf-8"))
    doc = invoice_receipt(receipt, source.name, invoice)
    stem = out or source.with_name(source.stem + ".verified")
    pdf_path, json_path = Path(f"{stem}.pdf"), Path(f"{stem}.json")
    pdf_path.write_bytes(invoice_pdf(doc))
    json_path.write_text(text(doc), encoding="utf-8", newline="\n")
    return pdf_path, json_path, doc
