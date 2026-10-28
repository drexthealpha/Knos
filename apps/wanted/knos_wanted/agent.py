"""The Knos agent: one crossing from a paper to a funded product, run on the server, calling Qloo at every decision.

    job = start(state, ref="10.1038/nature16521")          # or idea="..." for an idea without a paper
    poll(job_id) -> {"status": "running" | "done" | "error", "steps": [...], "report": hash, "card": hash}

Each step: {n, kind (memory | paper | qloo | decision), title, tool, input, output, effect, at}. Qloo steps stream as the
calls return (check.demand_check(on_call=...)), so the page shows the crossing live by polling GET /api/cross?id=.
Sibyl is the agent's WORKING MEMORY: before a crossing the agent recalls what it learned about the same paper (the
product phrase the maker settled on, the last decision); after it, it remembers this crossing. Memory never moves or
blocks money: escrow rules live in knos_pay on chain.

The same agent answers Model Context Protocol calls at POST /mcp (JSON-RPC over HTTP, tools/list + tools/call), an
optional door for other people's agents; the product is the web page.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import threading
import time

from knos import qloo_families

from . import check, company, preorder, research

JOBS: dict[str, dict] = {}
_lock = threading.Lock()
MAX_JOBS = 200



def _knos_version() -> str:
    """The knos package's version: from the checkout's pyproject.toml when knos is imported from a source tree (where
    installed metadata may be another release's), else knos.version(), the same answer as `knos --version`."""
    try:
        import re
        from pathlib import Path

        import knos
        root = Path(knos.__file__).resolve().parents[2]
        if (root / "src" / "knos").is_dir() and (root / "pyproject.toml").is_file():
            m = re.search(r'(?m)^version = "([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"))
            if m:
                return m.group(1)
        return knos.version()
    except Exception:  # noqa: BLE001 - the handshake still answers without knos
        return "unknown"

def _trim(text, n: int) -> str:
    """At most `n` characters, cut at a word boundary with an ellipsis (never mid-word)."""
    t = str(text or "")
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0].rstrip(",;:")
    return cut + "\u2026"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S")


def memory_key(ref: str | None, idea: str | None) -> str:
    return "crossing:" + hashlib.sha256((ref or idea or "").strip().lower().encode()).hexdigest()[:40]


def recall(key: str) -> dict:
    try:
        rec = company._record()
        if rec is None:
            return {}
        got = rec.claim_state(key, root=company.root()) or {}
        return {k: v for k, v in got.items() if not k.startswith("_")}
    except Exception:  # noqa: BLE001 - no memory is a fresh start, never an error
        return {}


def _store():
    rec = company._record()
    if rec is None:
        return None
    try:
        from knos.record import journal
        return journal.sibyl(company.root())
    except Exception:  # noqa: BLE001
        return None


def hot_get(key: str) -> dict:
    st = _store()
    try:
        return (st.state(key) if st else None) or {}
    except Exception:  # noqa: BLE001
        return {}


def hot_set(key: str, body: dict) -> bool:
    st = _store()
    try:
        if st is None:
            return False
        st.set_state(key, body)
        return True
    except Exception:  # noqa: BLE001
        return False


def shelve_paper(card: dict) -> dict:
    """The paper joins the agent's REFERENCE shelf (title, ids, counts: public literature facts, never idea text)."""
    rec = company._record()
    if rec is None:
        return {"shelved": False, "why": "no record here"}
    return company._safe(lambda: {"shelved": True, "seq": rec.paper("paper:" + (card["ids"].get("doi") or card["ref"]),
                                  {"title": card["title"], "year": card.get("year"), "cited_by_count": card.get("cited_by_count"),
                                   "doi": card["ids"].get("doi"), "card_hash": card["hash"], "product": card["product"]},
                                  domain=company.DOMAIN, root=company.root())["seq"]})


def remember(key: str, state: dict) -> dict:
    rec = company._record()
    if rec is None:
        return {"remembered": False, "why": "Sibyl is not installed here"}
    return company._safe(lambda: {"remembered": True, "seq": rec.claim(key, state, domain=company.DOMAIN, root=company.root())["seq"]})


def _step(job: dict, kind: str, title: str, *, tool: str = "", inp=None, out="", effect: str = "") -> dict:
    s = {"n": len(job["steps"]) + 1, "kind": kind, "title": title, "tool": tool, "input": inp, "output": out, "effect": effect, "at": _now()}
    with _lock:
        job["steps"].append(s)
    return s


def _qloo_step(job: dict):
    def on_call(c: dict) -> None:
        effect = next((e for k, e in check.EFFECTS if c["what"].startswith(k)), "evidence")
        st = _step(job, "qloo", c["what"], tool=c["call"], inp=c.get("params"), out=c.get("error") or c.get("body_digest") or "", effect=effect)
        st["call"] = c.get("n")            # the report's call number: the page links the step to its trace (/trace.html#call-n)
    return on_call


def run(job: dict, state) -> None:
    refused = False
    key = memory_key(job.get("ref"), job.get("idea"))
    try:
        held = hot_get("lock:" + key)
        other = held.get("running")
        if other and other != job["id"] and JOBS.get(other, {}).get("status") == "running":
            refused = True
            _step(job, "memory", "another agent holds this crossing", tool="Sibyl HOT state (the shared working plan)",
                  inp="lock:" + key, out=f"crossing {other} is running the same paper now: this agent's conflicting "
                  "writes are REFUSED; it reads along and writes nothing",
                  effect="one plan per crossing; memory stays consistent")
        else:
            hot_set("lock:" + key, {"running": job["id"], "started": job["started"],
                                    "plan": ["recall memory", "read the paper", "name the product", "ask Qloo (who, where, "
                                             "price, trend, leader)", "decide by code", "remember the crossing"]})
            _step(job, "memory", "the agent's plan, in shared memory", tool="Sibyl HOT state (crossing plan + cursor)",
                  inp="lock:" + key, out="plan written: recall -> paper -> product -> Qloo evidence -> decision -> remember",
                  effect="a second agent on the same paper is refused while this one runs")
        try:
            from . import qloo_rest
            if getattr(state.q, "mode", "") == "live" and qloo_rest.held() > 0:
                _step(job, "qloo", "Qloo asked for a pause: the harness is not asked", tool="qloo mcp (official @qloo/qloo-harness)",
                      out=f"nothing sent to Qloo for {qloo_rest.held():.0f} s more", effect="REST carries this crossing, labelled")
            elif getattr(state.q, "mode", "") == "live":
                words = " ".join((job.get("product") or job.get("idea") or job.get("ref") or "").split()[:6]) or "research product"
                box: dict = {}
                t = threading.Thread(target=lambda: box.update(cap=state.q.call(
                    "qloo_find_tags", {"query": words}, why="the official qloo-harness MCP server reads Qloo beside the REST steps",
                    step="harness")), daemon=True)
                t.start()
                t.join(HARNESS_WAIT_S)                # a slow harness never holds the crossing: REST carries it, said so
                if "cap" not in box:
                    raise TimeoutError(f"the harness had not answered in {HARNESS_WAIT_S:.0f} s")
                cap = box["cap"]
                names = ", ".join(str(r.get("name")) for r in (cap.get("results") or [])[:4])
                _step(job, "qloo", "the Qloo harness answers (live)", tool="qloo mcp (official @qloo/qloo-harness, via the Node bridge)",
                      inp={"tool": "qloo_find_tags", "query": words}, out=f"status {cap.get('status')}: {names}"[:200],
                      effect="the ten harness tools answer at /mcp as qloo_*; the decision reads below run on the REST API, labelled")
        except Exception:  # noqa: BLE001 - a harness that is down never stops a crossing; REST carries it, labelled
            _step(job, "qloo", "the Qloo harness is down: REST carries this crossing", tool="qloo mcp (not reachable)",
                  out="falling back to the REST API, labelled on every step", effect="same evidence, same rules")
        mem = recall(key)
        product = job.get("product")
        if mem:
            if not product and mem.get("product"):
                product = mem["product"]
            _step(job, "memory", "the agent remembers this paper", tool="Sibyl (agent memory)", inp=key,
                  out=f"last crossed {mem.get('when')}: product '{mem.get('product')}', decision {mem.get('verdict')}",
                  effect="reuses the product phrase it settled on last time" if product == mem.get("product") else "noted")
        else:
            _step(job, "memory", "nothing remembered about this paper yet", tool="Sibyl (agent memory)", inp=key, out="first crossing",
                  effect="starts fresh")
        card = None
        if job.get("ref"):
            card = research.research_card(job["ref"], product=product)
            with _lock:
                state.cards[card["hash"]] = card
            job["card"] = card["hash"]
            _step(job, "paper", "read the paper", tool="OpenAlex, Crossref (knos.ideas.sources)", inp=job["ref"],
                  out=f"{_trim(card['title'], 120)} ({card.get('year')}), cited {card.get('cited_by_count')}, "
                      f"retracted: {card['retraction']['retracted']}"
                      + (f", Nobel {card['nobel']['prize']} {card['nobel']['year']}" if card.get("nobel") else "")
                      + (f"; regulated: the source cites {card['regulator']}" if card.get("regulator") else ""),
                  effect=f"proven result: \"{_trim(card['proven_result']['quote'], 160)}\"")
            _step(job, "decision", "the product this result enables", tool="research.product_phrase", inp=card.get("topics"),
                  out=card["product"], effect=card["product_source"])
            if not refused:
                shelf = shelve_paper(card)
                _step(job, "memory", "the paper on the reference shelf", tool="Sibyl REFERENCE tier (knos.record paper line)",
                      inp=card["ids"].get("doi") or job.get("ref"),
                      out=f"seq {shelf.get('seq')}" if shelf.get("shelved") else shelf.get("why", "not shelved"),
                      effect="later crossings and searches find this paper without re-reading it")
            if not refused:
                hot_set("lock:" + key, {**hot_get("lock:" + key), "cursor": "qloo evidence"})
        idea = (product or (card or {}).get("product") or job.get("idea") or "").strip()
        rep = check.demand_check(idea, job.get("place"), job.get("leader"), client=state.rest, on_call=_qloo_step(job),
                                 options=job.get("options"))
        from . import recorded                       # Qloo not answering: said, or the sample's last real card
        rep = recorded.honest(job.get("ref") or idea, rep)
        rep["fees"] = preorder.fee_line()
        if card:
            rep["research"] = {**card, "why_never_crossed": research.why_never_crossed(card, rep)}
        rep["record"] = company.record_check(rep)
        rep["elapsed_ms"] = round((time.time() - job["started"]) * 1000)      # from the paper asked for to the verdict
        state.keep_check(rep)
        job["report"] = rep["hash"]
        from . import vectors
        vectors.note("crossing", rep["elapsed_ms"], rep, state)
        d = rep["decision"]
        plan = d.get("plan") or {}
        if plan:
            w = plan["who"]
            _step(job, "decision", "WHO: the target audience", tool="from /v2/insights urn:demographics + urn:audience",
                  out=f"{(w.get('age') or '').replace('_', ' ')}, {w.get('gender')}; segments: {', '.join(w.get('segments') or [])}",
                  effect="the product page and the Blink speak to this audience")
            _step(job, "decision", "WHERE: the launch cities", tool="from /v2/insights urn:entity:destination (explainability on)",
                  out=", ".join(plan.get("where") or []) or "none returned", effect="pre-orders open first in these cities")
            _step(job, "decision", "PRICE: the tier", tool="from Qloo's spending-habit segments (urn:audience)",
                  out=f"{plan['tier']}: {plan['unit_price']} test units per unit", effect="sets the pre-order's unit price")
            _step(job, "decision", "HELD: target and reserve", tool="check.RULES units_formula", inp=d.get("formula"),
                  out=f"target {plan['target_units']} units ({plan['escrow_target']} test units), reserve {plan['reserve_units']} "
                      f"({plan['escrow_reserve']} test units)", effect="the maker is paid on proof once the reserve is pre-ordered")
            if plan.get("unserved_audience"):
                _step(job, "decision", "the audience the leader does not serve", tool="from /v2/analysis/compare or the leader's segments",
                      out=", ".join(plan["unserved_audience"]), effect="the product page leads with it")
        _step(job, "decision", f"DECISION: {d['verdict']}", tool="check.decide (code, no language model)", out="; ".join(d["reasons"])[:600],
              effect="pre-orders open" if d["verdict"] == "OPEN" else "no pre-orders")
        if card:
            for w in rep["research"]["why_never_crossed"]:
                _step(job, "decision", f"why it never crossed: {w['wall']}", tool="research.why_never_crossed", out=w["evidence"],
                      effect="flagged" if w["flag"] else "not flagged")
        if refused:
            _step(job, "memory", "nothing written: the other agent holds this crossing", tool="Sibyl (agent memory)", inp=key,
                  out="conflicting write refused", effect="the running agent's record stays the one record")
        else:
            r = remember(key, {"when": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"), "product": idea, "verdict": d["verdict"],
                               "report": rep["hash"], "target_units": d.get("target_units")})
            hot_set("lock:" + key, {"running": None, "last_report": rep["hash"]})
            _step(job, "memory", "the agent remembers this crossing", tool="Sibyl (agent memory: WARM state + COLD journal)", inp=key,
                  out="remembered" if r.get("remembered") else r.get("why", "not remembered"), effect="the next crossing of this paper starts from here")
        job["status"] = "done"
    except Exception as e:  # noqa: BLE001 - the page shows one plain line; the log has the rest
        job["status"] = "error"
        job["error"] = str(e)[:300] if isinstance(e, ValueError) else "the crossing stopped on a server error"
        print(f"knos agent error {job['id']}: {type(e).__name__}: {str(e)[:300]}", flush=True)
    finally:
        job["finished"] = time.time()


def start(state, *, ref: str | None = None, idea: str | None = None, place: str | None = None, product: str | None = None,
          leader: str | None = None, wait: bool = False, options: dict | None = None) -> dict:
    if not (ref or idea):
        raise ValueError("paste a paper id (DOI, arXiv, PubMed, OpenAlex) or describe an idea")
    options = qloo_families.options(options)          # checked before the crossing starts, so a bad field is said at once
    kept = None if wait or idea or place or product or leader else _kept(state, ref, options)
    if kept:                                          # the same paper crossed here lately: its answer at once, said so
        at = time.strftime("%H:%M UTC", time.gmtime(kept["started"]))
        job = {**{k: kept[k] for k in ("ref", "idea", "place", "product", "leader", "options", "status", "report", "card")},
               "id": secrets.token_hex(8), "started": time.time(), "kept_from": kept["id"],
               "steps": [*kept["steps"], {"title": f"kept from the crossing of this paper at {at}", "at": time.time()}]}
        with _lock:
            JOBS[job["id"]] = job
        return job
    job = {"id": secrets.token_hex(8), "ref": ref, "idea": idea, "place": place, "product": product, "leader": leader, "options": options,
           "status": "running", "steps": [], "started": time.time(), "report": None, "card": None}
    with _lock:
        JOBS[job["id"]] = job
        for k in sorted(JOBS, key=lambda k: JOBS[k]["started"])[:-MAX_JOBS]:
            JOBS.pop(k)
    if wait:
        run(job, state)
    else:
        threading.Thread(target=run, args=(job, state), daemon=True).start()
    return job


KEEP_CROSSING_S = 6 * 3600   # a paper crossed in the last 6 hours is answered from that crossing (it reads the same paper)
HARNESS_WAIT_S = 4.0         # the official harness's one call waits this long at most (on 26 Oct, refused by Qloo, it took 12 s)


def _kept(state, ref: str | None, options: dict) -> dict | None:
    """The newest finished crossing of this paper, with the same options and a demand report Qloo answered in full,
    from the last 6 hours (one that met a Qloo outage is crossed again)."""
    if not ref:
        return None
    with _lock:
        done = [j for j in JOBS.values() if j.get("ref") == ref and j.get("status") == "done" and j.get("report") and not j.get("idea")
                and not j.get("kept_from") and j.get("options") == options and time.time() - j["started"] < KEEP_CROSSING_S]
    from . import qloo_rest
    held = qloo_rest.held() > 0                       # Qloo asked for a pause: a new crossing could not ask it either
    for j in sorted(done, key=lambda j: j["started"], reverse=True):
        rep = state.report(j["report"]) or {}
        if rep and (held or not (rep.get("qloo_down") or rep.get("stale"))):
            return j
    return None


def crossings(state, n: int = 30) -> list[dict]:
    """Every crossing this server ran, newest first: what the Buyer view lists so a result is never lost."""
    out = []
    with _lock:
        jobs = sorted(JOBS.values(), key=lambda j: j["started"], reverse=True)[:n]
    for j in jobs:
        rep = state.report(j["report"]) if j.get("report") else None
        d = (rep or {}).get("decision") or {}
        out.append({"id": j["id"], "status": j["status"], "ref": j.get("ref"), "idea": (rep or {}).get("idea") or j.get("idea"),
                    "report": j.get("report"), "verdict": d.get("verdict"), "target_units": d.get("target_units"),
                    "reserve_units": d.get("reserve_units"), "started": j["started"]})
    return out


def poll(job_id: str, since: int = 0) -> dict | None:
    job = JOBS.get(job_id)
    if job is None:
        return None
    with _lock:
        return {k: v for k, v in job.items() if k != "steps"} | {"steps": job["steps"][since:], "total": len(job["steps"])}


# ---- MCP over HTTP (an optional door for other agents) ----------------------------------------------------------------
PROTOCOL = "2025-06-18"
CONFIRM = ("CONFIRM FIRST: this moves devnet TEST money or posts work. Ask the human you work for before calling. Needs "
           "Authorization: Bearer in the HTTP header (an agent key's OAuth token), or the session token knos_sign_in returned. "
           "Test money only; no real funds.")
DISCOVERY = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Knos MCP</title><link rel="stylesheet" href="/static/style.css"></head><body><main class="wrap">
<h1>Knos over MCP</h1>
<p>This endpoint speaks the Model Context Protocol (Streamable HTTP, JSON-RPC): <code class="url">POST /mcp</code>.
Add it by URL in Claude, Cursor or any MCP client. Reading needs no key; money tools take a session token from
<span class="mono">knos_sign_in</span> and say in their descriptions to confirm with your human first. Everything is
Solana devnet test money.</p>
<p>Tools: knos_cross, knos_research_card, knos_demand_check, knos_crossings, knos_milestones, knos_tasks,
knos_memory_recall, knos_sign_in, knos_preorder, knos_evidence, knos_task_submit, knos_templates, knos_projects,
knos_project_open, knos_project_claim, knos_project_post, knos_milestone_submit, knos_openapi. The same API as OpenAPI:
<a href="/openapi.json">/openapi.json</a>.</p>
<p>An agent with no person present: a person makes it a capped, revocable agent key; the key is an OAuth 2.0 client
(<a href="/.well-known/oauth-authorization-server">client credentials</a>) and its token goes in the Authorization header.
<a href="/.well-known/agent-card.json">Agent Card</a>.</p>
<p><a href="/">The app</a> · <a href="/verify">How we verify</a></p></main></body></html>"""
TOOLS = [
    {"name": "knos_cross", "title": "Cross a paper to a funded product",
     "description": "Paper id (DOI, arXiv, PubMed, OpenAlex) -> research card -> Qloo evidence at every decision -> who, where, price "
                    "tier, held-money target and reserve, and OPEN or REFUSE. Returns every step with its Qloo call, input, output and effect.",
     "inputSchema": {"type": "object", "properties": {"ref": {"type": "string"}, "idea": {"type": "string"}, "place": {"type": "string"},
                                                       "product": {"type": "string"}, **{k: qloo_families.schema(k) for k in qloo_families.FIELDS}},
                     "additionalProperties": False}},
    {"name": "knos_research_card", "title": "Read a landmark paper",
     "description": "Paper id -> the proven result (quoted), citations, retraction status, Nobel recognition, the product it enables.",
     "inputSchema": {"type": "object", "properties": {"ref": {"type": "string"}}, "required": ["ref"], "additionalProperties": False}},
    {"name": "knos_demand_check", "title": "Is this product wanted? (Qloo)",
     "description": "A product idea -> Qloo evidence -> a decision made by code. Every Qloo demand family is a typed argument: "
                    "who (age, gender, audiences), gaps (hide_leader, exclude, popularity_max), where (near, radius, location, geohash, "
                    "region names), price tier (price_level, price range), who serves it (references_brand, quality, sort, ratings), "
                    "product kind and years (film/TV/book/person), look up (lookup, entity_id), and `qloo` for any other documented parameter.",
     "inputSchema": {"type": "object", "properties": {"idea": {"type": "string", "description": "the product idea or a paper's DOI (8-500 characters)"},
                                                      "picked": {"type": "boolean", "description": "true when idea is the exact reading picked from the readings a first call returned (which one do you mean?)"},
                                                      "place": {"type": "string", "description": "the launch market"},
                                                      "leader": {"type": "string", "description": "the market leader to compare"},
                                                      **{k: qloo_families.schema(k) for k in qloo_families.FIELDS}},
                     "required": ["idea"], "additionalProperties": False}},
    {"name": "knos_crossings", "title": "Crossings on this server",
     "description": "Every crossing this server ran, newest first: id, paper or idea, verdict, report hash.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "knos_milestones", "title": "Open milestones",
     "description": "Every commitment on this server: held order, units, status, claim id. A locked one needs an evidence page.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "knos_tasks", "title": "Open work for contributors",
     "description": "Open game rounds and milestones a person or agent can work on; checked and paid on devnet (test money).",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "knos_memory_search", "title": "Search everything this Knos remembers",
     "description": "FTS5 search (multilingual) over the agents' memory and the Knos Record: papers, crossings, decisions, events.",
     "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"], "additionalProperties": False}},
    {"name": "knos_memory_recall", "title": "What the agent remembers about a paper",
     "description": "Sibyl, the crossing agent's working memory: the last crossing of a paper or idea (product phrase, verdict, report).",
     "inputSchema": {"type": "object", "properties": {"ref": {"type": "string"}, "idea": {"type": "string"}}, "additionalProperties": False}},
    {"name": "knos_sign_in", "title": "A session for the money tools",
     "description": "Returns a session token the money tools need. " + CONFIRM,
     "inputSchema": {"type": "object", "properties": {"label": {"type": "string", "description": "a note on who opened it; never shown (the session shows as Guest and 4 characters of its id)"}},
                     "required": ["label"], "additionalProperties": False}},
    {"name": "knos_preorder", "title": "Pre-order (your human's passkey signs)",
     "description": "Prepares a pre-order of an OPEN report: no server key buys for anyone, so it returns the page where "
                    "your human's passkey approves it (devnet test money). " + CONFIRM,
     "inputSchema": {"type": "object", "properties": {"report": {"type": "string"}, "units": {"type": "integer"},
                                                       "session": {"type": "string"}}, "required": ["report", "units"],
                     "additionalProperties": False}},
    {"name": "knos_evidence", "title": "Post milestone evidence",
     "description": "Posts a milestone's public evidence page; verified evidence releases the held money to the maker. " + CONFIRM,
     "inputSchema": {"type": "object", "properties": {"commitment": {"type": "string"}, "evidence_url": {"type": "string"},
                                                       "session": {"type": "string"}}, "required": ["commitment", "evidence_url"],
                     "additionalProperties": False}},
    {"name": "knos_task_submit", "title": "Submit work to an open round",
     "description": "Submits the whole train.py to the open round (knos_tasks says what to change and links the task's README); "
                    "the sealed referee checks it at once; several attempts per round. A scored attempt with a devnet `wallet` "
                    "is paid in test units. " + CONFIRM,
     "inputSchema": {"type": "object", "properties": {"round": {"type": "string"}, "name": {"type": "string"}, "code": {"type": "string"},
                                                       "wallet": {"type": "string"},
                                                       "session": {"type": "string"}}, "required": ["round", "code"],
                     "additionalProperties": False}},
]


def _task_submit(args: dict, who: dict) -> dict:
    """knos_task_submit. An agent key's demo prize is paid only at its payout wallet and only within its spend cap."""
    from . import agentkeys, tasks
    wallet = str(args.get("wallet") or "") or None
    kid = who.get("agent_key") if who.get("kind") == "agent" else None
    capped = None
    if kid:
        if wallet and wallet != who.get("payout_wallet"):
            raise ValueError("an agent key is paid only at its payout wallet: leave wallet out")
        try:
            agentkeys.can_spend(kid, tasks.PRIZE_UNITS)
            wallet = who.get("payout_wallet")
        except ValueError as why:                    # judged all the same; no prize over the cap
            wallet, capped = None, str(why)
    out = tasks.submit(str(args.get("round") or ""), str(args.get("name") or ""), str(args.get("code") or ""),
                       f"{who.get('kind')}: {who.get('label')}", sub=str(who.get("sub") or ""), wallet=wallet)
    if kid and ((out.get("prize") or {}).get("paid") or (out.get("prize") or {}).get("status") == "signing"):   # FROST pays it later
        agentkeys.spent(kid, tasks.PRIZE_UNITS)
    return {**out, **({"prize": {"paid": False, "why": capped}} if capped else {})}


# each tool's description as the MCP registry lists it: one sentence of what it does and returns (under 160 characters);
# a tool that moves devnet test money ends with "ask your human first"
DESCRIPTIONS = {
    "knos_cross": "Turns a paper id (DOI, arXiv, PubMed or OpenAlex) into a research card and a demand check, and returns each step with the Qloo call behind it.",
    "knos_demand_check": "Checks who wants a product idea with Qloo taste data and returns the verdict with its audience and launch city, each traced to its Qloo call.",
    "knos_milestones": "Lists every commitment on this server with its held order and its status.",
    "knos_sign_in": "Returns a guest session token that the tools moving devnet test money accept; ask your human first.",
    "knos_preorder": "Prepares a pre-order of an OPEN report and returns the page where your human's passkey approves it with devnet test money; ask your human first.",
    "knos_evidence": "Posts a milestone's public evidence page, whose verified evidence releases the held devnet test money to the maker; ask your human first.",
    "knos_task_submit": "Submits a whole train.py to the open round's sealed referee and returns its verdict, with a payout in devnet test money when it scores; ask your human first.",
    "knos_templates": "Returns the brief templates Knos offers, from AI model evals to regulatory milestones taken from OpenRegulatory's open templates.",
    "knos_project_open": "Opens a project whose milestones each hold devnet test money until a result and an independent check arrive; ask your human first.",
    "knos_project_claim": "Claims a milestone as its maker and binds the wallet it pays in devnet test money; ask your human first.",
    "knos_project_post": "Posts a result or a check page for a milestone, and the referee panel releases its devnet test money when both are in; ask your human first.",
    "knos_milestone_submit": "Sends your whole train.py to a milestone's sealed referee and releases its devnet test money to you when the verdict meets the target; ask your human first.",
    "knos_ready": "Checks a brief before any money locks and returns Ready, or the missing fields with a rewrite template, sending nothing.",
    "knos_usage": "Returns how many times each Knos tool was called over MCP since this server started.",
    "knos_milestone_prompt": "Returns the locked intent of a milestone you work on, with its criteria hash and the token budget for answering it.",
}


OPEN = {"knos_sign_in"}              # writes nothing anyone relies on: it is how a person gets the session the others need


def _caller(args: dict) -> dict | None:
    """Who a write tool acts for: the Bearer credential in the HTTP header (an agent key, its OAuth access token, or a
    person's session), else, for people for now, the `session` argument. None: no credential. A revoked or expired
    key raises (auth.AuthError) with which it is."""
    from . import agentkeys, auth, outside
    headers = getattr(outside.CTX, "headers", None)
    who = agentkeys.principal(headers.get("Authorization")) if headers is not None else None
    return who or (auth.who("Bearer " + str(args.get("session"))) if args.get("session") else None)


def _agent() -> dict | None:
    """The agent key the HTTP header carries (Bearer), or None: no header, a person's session, or a dead key. The qloo_*
    tools answer only such a caller (Qloo's terms: no Qloo credential behind a public MCP)."""
    from . import agentkeys, auth, outside
    headers = getattr(outside.CTX, "headers", None)
    try:
        who = agentkeys.principal(headers.get("Authorization"), count=False) if headers is not None else None
    except auth.AuthError:
        return None
    return who if who and who.get("kind") == "agent" else None


def _product_tools() -> set:
    """The names product_routes.MCP_TOOLS lists, each answered by product_routes.mcp_call."""
    from .product_routes import MCP_TOOLS
    return {t["name"] for t in MCP_TOOLS}


# MCP tool annotations (the Claude connector directory asks each tool for a title and readOnlyHint or destructiveHint):
# what reads, what writes, what moves money. And the app-store profile (POST /mcp/store): only the read-only tools an
# AI app store may list (no sign-in, no money inside the assistant; a pre-order is a link out to the site), each call
# within a daily cap.
READ_ONLY = {"knos_research_card", "knos_demand_check", "knos_crossings", "knos_milestones", "knos_tasks", "knos_memory_search",
             "knos_memory_recall", "knos_templates", "knos_projects", "knos_openapi", "knos_ready", "knos_usage",
             "knos_milestone_prompt"}
MONEY = {"knos_preorder"}
STORE = {"knos_ready", "knos_demand_check"}           # no qloo_* tool: those answer an agent key only
STORE_DAILY_CAP = 2000                                 # tool calls a day through /mcp/store, all callers together
_store_day = {"day": "", "n": 0}


def annotate(tool: dict) -> dict:
    name = tool["name"]
    ro = name in READ_ONLY or name.startswith("qloo_")
    return {**tool, "annotations": {"title": tool.get("title") or name.replace("_", " "), "readOnlyHint": ro,
                                    "destructiveHint": name in MONEY, "idempotentHint": ro,
                                    "openWorldHint": name.startswith("qloo_") or name in ("knos_demand_check", "knos_cross", "knos_research_card")}}


def in_store(name: str) -> bool:
    return name in STORE


def store_spend() -> bool:
    """One more call within today's cap of the store profile (UTC day); False once the cap is reached."""
    import time as _t
    day = _t.strftime("%Y-%m-%d", _t.gmtime())
    if _store_day["day"] != day:
        _store_day.update(day=day, n=0)
    if _store_day["n"] >= STORE_DAILY_CAP:
        return False
    _store_day["n"] += 1
    return True


def mcp(state, msg: dict, profile: str = "full") -> dict | None:
    """One JSON-RPC message of the Streamable HTTP transport (POST /mcp, or /mcp/store: the app-store profile).
    Notifications get no answer (None)."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None
    store = profile == "store"
    if store and method == "tools/call":
        name = (params or {}).get("name")
        if not (isinstance(name, str) and in_store(name)):
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"{name} is not offered here: the app-store "
                    "profile lists read-only tools only; money moves on the Knos site"}}
        if not store_spend():
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32000, "message": f"today's cap of {STORE_DAILY_CAP} calls is reached; "
                    "try again tomorrow (UTC)"}}
        if name == "knos_demand_check":
            from . import privacy
            try:
                privacy.check({"idea": (params.get("arguments") or {}).get("idea"), "place": (params.get("arguments") or {}).get("place")})
            except ValueError as why:
                return {"jsonrpc": "2.0", "id": mid, "result": {"isError": True, "content": [{"type": "text", "text": str(why)[:300]}]}}

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if method == "initialize":
        return ok({"protocolVersion": PROTOCOL, "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "knos", "version": _knos_version()},
                   "instructions": "Knos carries research across the valley of death: see who wants it and where, then get paid only on proof. Start with knos_demand_check (is it wanted: who, where, at what price) or "
                                                   "knos_cross with a paper id; every step names the Qloo call behind it. knos_ready says whether a brief is "
                                                   "clear enough to lock money on. Devnet, test money, no customers yet."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        extra = []
        try:
            if store or not _agent():                    # Qloo's tools are listed to an agent key only
                raise LookupError
            from .qloo_mcp import WORKFLOWS
            mode = getattr(state.q, "mode", "mock")
            extra = [{"name": n, "title": n.replace("_", " "),
                      "description": f"The official qloo-harness tool {n}, proxied from this server's `qloo mcp` "
                                     f"({'LIVE' if mode == 'live' else 'MOCK synthetic data, labelled in every answer'}).",
                      "inputSchema": {"type": "object", "properties": {}, "additionalProperties": True}}
                     for n in ("qloo_capabilities",) + WORKFLOWS]
        except Exception:  # noqa: BLE001
            extra = []
        from .product_routes import MCP_TOOLS
        tools = [annotate({**t, "description": DESCRIPTIONS.get(t["name"], t["description"])}) for t in TOOLS + MCP_TOOLS + extra]
        return ok({"tools": [t for t in tools if in_store(t["name"])] if store else tools})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if isinstance(name, str) and name.startswith("qloo_"):
            from .qloo_mcp import WORKFLOWS, QlooUnavailable
            if name not in ("qloo_capabilities",) + WORKFLOWS:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
            agent_who = _agent()
            if not agent_who:
                from . import agentkeys, tasks
                return ok({"isError": True, "content": [{"type": "text", "text": f"{name} answers an agent key only (Authorization: Bearer); "
                           + agentkeys.needs(name, tasks.public_base())}]})
            from . import agentkeys, valley
            try:
                agentkeys.take_qloo(agent_who["agent_key"])
            except valley.Refused as why:
                return ok({"isError": True, "content": [{"type": "text", "text": str(why)[:300]}]})
            import json as _json
            if name == "qloo_capabilities":            # not a workflow: what the qloo server said at its handshake
                got = {"mode": getattr(state.q, "mode", "mock"), "server": getattr(state.q, "server", None),
                       "tools": getattr(state.q, "tools", []), "capabilities": getattr(state.q, "capabilities", {})}
                return ok({"content": [{"type": "text", "text": _json.dumps(got, default=str)[:60_000]}], "structuredContent": got})
            try:
                got = state.q.call(name, dict(args), why="proxied for an outside agent over Knos's MCP", step=name)
            except QlooUnavailable as e:
                return ok({"isError": True, "content": [{"type": "text", "text": str(e)[:300]}]})
            return ok({"content": [{"type": "text", "text": _json.dumps(got, default=str)[:60_000]}], "structuredContent": got})
        if name == "knos_milestone_submit" and isinstance(args, dict) and args.get("kind") in ("observation", "oru"):
            # a lab's proof (a FHIR Observation, or an HL7 ORU message) checked by the one rules referee IRIS runs too
            # (knos.referee_rules): the decision only, against the brief given; nothing is signed and no money moves
            import json as _json
            from knos import ready, referee_rules
            brief = args.get("brief") if isinstance(args.get("brief"), dict) else None
            if brief is None:
                return ok({"isError": True, "content": [{"type": "text", "text": "brief: the locked brief the proof answers (its milestones and verifiers)"}]})
            proof = args.get("proof")
            payload = proof if isinstance(proof, str) else _json.dumps(proof or {})
            got = _json.loads(referee_rules.decide(_json.dumps(brief), args["kind"], payload, ready.criteria_hash(brief)))
            return ok({"content": [{"type": "text", "text": _json.dumps(got)}], "structuredContent": got})
        who: dict = {}
        if isinstance(name, str) and name not in READ_ONLY | OPEN and name in {t["name"] for t in TOOLS} | _product_tools():
            from . import agentkeys, auth, tasks
            try:
                who = _caller(args) or {}
            except auth.AuthError as why:                # a revoked or expired agent key, or an expired token
                return ok({"isError": True, "content": [{"type": "text", "text": str(why)[:300]}]})
            if not who:
                meta = tasks.public_base() + "/.well-known/oauth-protected-resource"
                return ok({"isError": True, "content": [{"type": "text", "text": agentkeys.needs(name, tasks.public_base())}],
                           "structuredContent": {"needs": "authorization", "resource_metadata": meta}})
        try:
            if name == "knos_cross":
                job = start(state, ref=args.get("ref"), idea=args.get("idea"), place=args.get("place"), product=args.get("product"), wait=True,
                            options={k: args[k] for k in qloo_families.FIELDS if k in args})
                rep = state.report(job["report"]) if job.get("report") else None
                out = {"status": job["status"], "error": job.get("error"), "steps": job["steps"], "report": job.get("report"),
                       "decision": (rep or {}).get("decision")}
            elif name == "knos_research_card":
                out = research.research_card(str(args.get("ref") or ""))
                if str(out.get("product_source") or "").startswith("generic phrase"):    # Knos's own guess, not a product
                    out = {**out, "product": None, "suggested_product": None, "product_line": "Name the product this result enables"}
            elif name == "knos_demand_check":
                opts = {k: args[k] for k in qloo_families.FIELDS if k in args}
                idea = " ".join(str(args.get("idea") or "").split())
                picked = args.get("picked") is True
                from . import recorded, which            # which one do you mean? asked first, as on the front door
                w = None if picked else which.step(idea)
                if w:
                    out = {**w, "next": "call knos_demand_check again with idea set to the text of the reading you mean and picked: true"}
                else:
                    t0 = time.perf_counter()
                    rep = check.demand_check(idea, args.get("place"), args.get("leader"), client=state.rest, options=opts)
                    rep = recorded.honest(idea, rep, picked=picked)
                    rep["qloo_calls"] = {**rep.get("qloo_calls", {}), "ms": round((time.perf_counter() - t0) * 1000)}
                    state.keep_check(rep)
                    out = {"report": rep["hash"], "idea": rep.get("idea"), "decision": rep["decision"], "families": rep.get("families") or {},
                           "grounding": rep.get("grounding") or {}, "calls": rep["calls"], "label": rep.get("label"), "qloo_calls": rep.get("qloo_calls"),
                           **{k: rep[k] for k in ("stale", "nearest", "nearest_next", "nearest_options", "qloo_limit", "qloo_reset", "queued", "stand_in",
                                                  "read_as", "also_matched", "result_line", "brief", "ready") if rep.get(k)}}
            elif name == "knos_crossings":
                out = {"crossings": crossings(state)}
            elif name == "knos_milestones":
                out = {"commitments": preorder.all_public(50)}
            elif name == "knos_tasks":
                from . import tasks as _tasks
                out = _tasks.listing()
            elif name == "knos_memory_search":
                from knos.record import search as rsearch
                q = str(args.get("q") or "")[:200]
                got = rsearch.search(q, root=company.root())
                rows, said = got.get("rows", [])[:20], got.get("said")
                if not rows and q.strip():           # as /api/memory/search: the crossings and checks that name it
                    from .server import named
                    try:
                        rows = named(state, q)
                    except (AttributeError, TypeError):  # a server state without its reports (a test's): Sibyl's answer stands
                        rows = []
                    if rows:                         # none found either: Sibyl's own words stand
                        said = f"{len(rows)} crossing{'s' if len(rows) != 1 else ''} and checks name \"{q}\"."
                # Sibyl's verdict object and its code, as Sibyl gave them (why these rows, or why none)
                out = {"said": said, "rows": rows, "verdict": got.get("verdict"),
                       "verdict_code": (got.get("verdict") or {}).get("code")}
            elif name == "knos_memory_recall":
                out = recall(memory_key(args.get("ref"), args.get("idea"))) or {"remembered": False}
            elif name == "knos_sign_in":
                from . import auth
                out = auth.guest(str(args.get("label") or "agent") + " (via MCP)")
            elif name == "knos_preorder":
                rep = state.report(str(args.get("report") or ""))
                if rep is None:
                    raise ValueError("unknown report: run knos_cross first")
                units = int(args.get("units") or 0)
                if not 5 <= units <= 1000 or (rep.get("decision") or {}).get("verdict") != "OPEN":
                    raise ValueError("units: 5 to 1000, on a report whose decision is OPEN")
                out = {"needs": "the buyer's own passkey: an agent cannot sign for its human", "approve_at": f"/app/#buy={rep['hash']}",
                       "units": units, "how": "open the page, sign in with a passkey, press 'Pre-order with my passkey'",
                       "money": "devnet test money", "by": f"{who.get('kind')}: {who.get('label')}"}
            elif name == "knos_evidence":
                rec = preorder.load(str(args.get("commitment") or ""))
                out = preorder.milestone(state.report(rec["report"]) or {}, rec["order"], str(args.get("evidence_url") or ""))
            elif name == "knos_task_submit":
                out = _task_submit(args, who)
            elif name in _product_tools():          # every tool product_routes lists is answered by it (knos_ready, knos_usage, ...)
                from .product_routes import mcp_call
                out = mcp_call(name, args, lambda _a: who)
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {name}"}}
        except ValueError as e:
            return ok({"isError": True, "content": [{"type": "text", "text": str(e)[:300]}]})
        import json
        return ok({"content": [{"type": "text", "text": json.dumps(out, default=str)[:60_000]}], "structuredContent": out})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
