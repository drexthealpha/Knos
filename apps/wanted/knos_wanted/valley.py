"""Projects: the valley of death's risks built into the money (devnet test units, Solana devnet only).

A PROJECT is one product's road, made from a milestone template (AI model eval, hardware prototype, internal tool,
paper to pilot, vendor deliverable) plus, for a regulated product, the regulatory milestones of OpenRegulatory's open
templates (ISO 13485, EU MDR). Every milestone is a TRANCHE: its own knos_pay panel order, funded by anyone, and

  released   only when the maker's result AND an independent check of it are both posted: two public https pages that
             contain the milestone's claim id, from two different sites, by two different signed-in people (the checker
             is never the maker). The server fetches both, the 2-of-3 panel signs PASS over the pair, the program pays.
  parallel   several makers may attempt one milestone at once (up to MAX_ATTEMPTS); the first independently checked
             result is paid, so one failed attempt does not kill the product. Code-scored milestones also open a
             knos.game round (the Contribute tab).
  refunded   past its deadline, by the sweeper thread in this server (sweep, every SWEEP_S): knos_pay RefundOrder sends
  + reopened the money back to the funder, the milestone REOPENS to other makers (the maker who missed it is excluded),
             and its funders are listed to re-fund it in one tap.

Money in, all real devnet transactions the funder's own wallet signs (the server only co-signs the test-unit top-up,
as the test mint's authority): a funder's escrow, a GRANT (the same order, labelled with the grant's agency and id),
a POOL (one funder spreads one amount over many milestones of many projects: the megafund), and an AMC COMMITMENT
(advance-market-commitment style: the buyer's wallet approves a token allowance to the relayer; nothing moves until the
milestone verifies, then the relayer pays the maker from it; the buyer can revoke the allowance until then, and the
page says so). A referral link names a referrer wallet: on release, the referrer's share is a second knos_pay payee.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct
import threading
import time
from pathlib import Path

from . import company, escrow

MAX_ATTEMPTS = 3
REFERRAL_BPS = 500                    # the referrer's share of a release paid through its link (5%)
SWEEP_S = int(os.environ.get("KNOS_VALLEY_SWEEP_S", "60"))
MIN_DEADLINE_S = 60                   # knos_pay's shortest stage deadline (pay.MIN_WORK)


def _token():
    from knos.settle.v2 import pay
    return pay.TOKEN                  # the SPL Token program (the test mint is a classic SPL mint)
_lock = threading.RLock()


class Refused(ValueError):
    pass


# ---- storage ---------------------------------------------------------------------------------------------------------
def _dir(kind: str) -> Path:
    d = escrow._state_dir() / "valley" / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save(kind: str, key: str, obj: dict, chain: bool = True) -> dict:
    if kind == "projects" and obj.get("report") and not obj.get("grounding_snapshot"):
        g = grounding(obj)                         # kept on the project: its report file does not survive a redeploy
        if g:
            obj["grounding_snapshot"] = g
    f = _dir(kind) / f"{key}.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, f)
    if kind in ("projects", "orders"):
        _list_cache.clear()                        # the public list shows this change at once
        _json_cache.clear()
        _sum_stale.update(_sum_cache.keys() | {10})  # the summary is built again on its next call; its file stays till then
    if chain:
        from . import chainstate
        chainstate.queue_save(kind, key, obj)      # and on devnet, so it survives a redeploy (KNOS_STATE_ON_CHAIN=1)
    return obj


def _load(kind: str, key: str) -> dict:
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", key):
        raise Refused(f"{kind}: unknown id")
    f = _dir(kind) / f"{key}.json"
    if not f.exists():
        raise Refused(f"{kind}: unknown id")
    return json.loads(f.read_text(encoding="utf-8"))


def _safe_load(kind: str, key: str) -> dict | None:
    try:
        return _load(kind, key)
    except Refused:
        return None


def _all(kind: str) -> list[dict]:
    out = []
    for f in sorted(_dir(kind).glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def _id(*parts) -> str:
    return hashlib.sha256(json.dumps([*parts, time.time_ns(), os.urandom(8).hex()]).encode()).hexdigest()[:16]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _journal(kind: str, data: dict, tenant: dict | None = None) -> dict:
    """The decision log (Sibyl COLD, through the Knos Record): every funding, claim, release, refund and reopen, and
    every brief version and criteria hash. A project's lines go to its own tenant claim and to its owner's."""
    rec = company._record()
    if rec is None:
        return {"recorded": False, "why": "the knos package is not installed"}
    claims = [company.claim_id(data.get("project", "0" * 64))]
    if tenant and tenant.get("user"):
        claims.append(company.claim_id("user:" + tenant["user"]))
    body = {**data, "cluster": "devnet", "money": "devnet test units", **({"tenant": {"project": tenant["project"]}} if tenant else {})}

    def write() -> dict:
        lines = [rec.append(kind, body, claim=c, domain=company.DOMAIN, root=company.root()) for c in claims]
        return {"recorded": True, "seq": lines[0]["seq"], "sibyl": remembered(lines[0])}
    return company._safe(write)


def remembered(entry: dict) -> dict:
    """What Sibyl keeps of a line just written: its tier, and the verdict code Sibyl's own search gives for the line's
    hash (sibyl_memory_client verdicts: why it returned what it did), as the receipt's "Remembered by Sibyl" line."""
    code = None
    try:
        from knos.record import search as rsearch
        got = rsearch.search(entry["hash"][:16], root=company.root(), limit=1)
        code = (got.get("verdict") or {}).get("code")
    except Exception:  # noqa: BLE001 - a search Sibyl cannot answer is said as none, never guessed
        code = None
    return {"tier": entry.get("tier"), "verdict": code, "hash": entry.get("hash")}


# ---- templates -------------------------------------------------------------------------------------------------------
def catalogue() -> dict:
    import copy

    from .templates_data import CATALOGUE
    return copy.deepcopy(CATALOGUE)


def templates() -> dict:
    c = catalogue()
    reg = c["regulatory"]
    return {"templates": [{"key": k, "name": t["name"], "for": t["for"], "route": t["route"],
                           "milestones": [{"key": m["key"], "name": m["name"], "days": m["days"], "share_bps": m["bps"]} for m in t["milestones"]]}
                          for k, t in c["templates"].items()],
            "regulatory": {"sets": [{"key": k, "name": s["name"], "milestones": [{"key": m["key"], "name": m["name"],
                                                                                  "template": f"{reg['source']}/blob/{reg['commit']}/{m['path']}"}
                                                                                 for m in s["milestones"]]}
                                    for k, s in reg["sets"].items()],
                           "attribution": reg["attribution"], "licence": reg["licence"], "source": reg["source"], "commit": reg["commit"]},
            "rules": {"release": "the maker's result + an independent check (another person, another site), both containing the claim id",
                      "parallel_attempts": MAX_ATTEMPTS, "missed_deadline": "refunded to the funder and reopened to other makers by this server's sweeper",
                      "referral_share_bps": REFERRAL_BPS}}


# ---- projects --------------------------------------------------------------------------------------------------------
def _user_key(user: dict) -> str:
    return str(user.get("sub") or f"{user.get('kind')}:{user.get('label')}")[:120]


def create_project(user: dict, template: str, title: str, regulatory: list[str] | None = None, report: str | None = None,
                   team: str | None = None, deadline_s: int | None = None, brief: dict | None = None) -> dict:
    """A project from a template (+ regulatory sets), or from the buyer's own brief (template "custom"). `deadline_s`
    shortens every milestone's deadline (the one-day sandbox, and the reopen demonstration): at least 60 s.
    Every milestone carries its acceptance criteria (target, verifier, deadline); money locks only on a Ready brief."""
    c = catalogue()
    if template == "custom" or brief is not None:
        return _create_custom(user, title, brief or {}, report, team)
    if template not in c["templates"]:
        raise Refused(f"template: one of {', '.join(c['templates'])}, or custom with a brief")
    title = (title or "").strip()[:120]
    if len(title) < 3:
        raise Refused("title: what the project makes (3 to 120 characters)")
    regulatory = [r for r in (regulatory or []) if r]
    for r in regulatory:
        if r not in c["regulatory"]["sets"]:
            raise Refused(f"regulatory: any of {', '.join(c['regulatory']['sets'])}")
    if deadline_s is not None and (isinstance(deadline_s, bool) or not isinstance(deadline_s, int) or not MIN_DEADLINE_S <= deadline_s <= 90 * 86_400):
        raise Refused("deadline_s: 60 to 7,776,000 seconds")
    t = c["templates"][template]
    ms = []
    from .templates_data import CRITERIA, REGULATORY_CRITERIA
    for m in t["milestones"]:
        cr = CRITERIA[(template, m["key"])]
        ms.append({"key": m["key"], "name": m["name"], "kind": "build", "share_bps": m["bps"], "route": m.get("route") or t["route"],
                   "game": bool(m.get("game")), "deadline_s": deadline_s or m["days"] * 86_400, "target": cr["target"],
                   "verifier": cr["verifier"]})
    reg = c["regulatory"]
    for r in regulatory:
        for m in reg["sets"][r]["milestones"]:
            ms.append({"key": f"{r}_{m['key']}", "name": m["name"], "kind": "regulatory", "share_bps": 0, "route": "none", "game": False,
                       "deadline_s": deadline_s or 60 * 86_400, "standard": reg["sets"][r]["name"],
                       "template": f"{reg['source']}/blob/{reg['commit']}/{m['path']}", "attribution": reg["attribution"],
                       "target": REGULATORY_CRITERIA["target"], "verifier": dict(REGULATORY_CRITERIA["verifier"], what=f"{m['name']} ({reg['sets'][r]['name']})")})
    return _open(user, template, t["name"], title, regulatory, report, team, ms, deadline_s is not None and deadline_s <= 86_400)


def _create_custom(user: dict, title: str, brief: dict, report: str | None, team: str | None) -> dict:
    title = (title or "").strip()[:120]
    if len(title) < 3:
        raise Refused("title: what the project makes (3 to 120 characters)")
    if not isinstance(brief.get("milestones"), list) or not 1 <= len(brief["milestones"]) <= 12:
        raise Refused("brief.milestones: 1 to 12 milestones")
    from knos import ready
    long = ready.science_brief(brief)
    rows = [ready.normal(m if isinstance(m, dict) else {}, i, long) for i, m in enumerate(brief["milestones"])]
    share = 10_000 // len(rows)
    ms = [{"key": n["key"], "name": n["name"] or n["key"], "kind": "build", "share_bps": share, "route": "none", "game": False,
           "deadline_s": n["deadline_s"] or ready.MIN_DEADLINE_S, "target": n["target"], "verifier": n["verifier"]} for n in rows]
    lt = ready.launch(brief)                  # the launch terms Qloo set (metros.brief): kept, and hashed with the milestones
    return _open(user, "custom", "Your brief", title, [], report, team, ms, False, {**ready.terms(brief), **({"launch": lt} if lt else {})})


def _brief(p: dict) -> dict:
    """The project's brief in the ready module's shape: its milestones' criteria, the kill fee and the challenge window."""
    return {"milestones": [{"key": m["key"], "name": m["name"], "target": m.get("target", ""), "verifier": m.get("verifier") or {},
                            "deadline_s": m["deadline_s"]} for m in p["milestones"]],
            "kill_fee_bps": p.get("kill_fee_bps", 0), "challenge_s": p.get("challenge_s", _ready().DEFAULT_CHALLENGE_S),
            **({"launch": p["launch"]} if p.get("launch") else {})}


def _ready():
    from knos import ready
    return ready


def readiness(p: dict) -> dict:
    return _ready().check(_brief(p))


def _version(p: dict, why: str) -> dict:
    r = readiness(p)
    v = {"n": len(p.get("versions") or []) + 1, "at": _now(), "why": why, "ready": r["ready"],
         "criteria_hash": _ready().criteria_hash(_brief(p)), "missing": r["missing"][:20]}
    p.setdefault("versions", []).append(v)
    _journal("experiment", {"project": p["id"], "what": "brief version", "version": v["n"], "why": why, "ready": v["ready"],
                            "criteria_hash": v["criteria_hash"], "brief": _brief(p)}, tenant_of(p))
    return v


def _open(user, template, template_name, title, regulatory, report, team, ms, sandbox, t=None) -> dict:
    t = t or {"kill_fee_bps": 0, "challenge_s": _ready().DEFAULT_CHALLENGE_S}
    for m in ms:
        m.update(status="open", fundings=[], attempts=[], excluded=[], history=[{"at": _now(), "what": "opened"}])
    pid = _id(template, title, _user_key(user))
    if _safe_load("projects", pid) is not None and template == "custom":
        pid = _id(template, title, _user_key(user), _now(), os.urandom(4).hex())
    p = {"id": pid, "title": title, "template": template, "template_name": template_name, "regulatory": regulatory, "report": report,
         "team": (team or "").strip()[:80] or None, "owner": _user_key(user), "owner_label": str(user.get("label") or "")[:80],
         "made": _now(), "milestones": ms, "cluster": "devnet", "money": "devnet test units of this app's test mint: no real money",
         "sandbox": sandbox, "kill_fee_bps": t["kill_fee_bps"], "challenge_s": t["challenge_s"], "frozen": None, "changes": [],
         "status": "open", **({"launch": t["launch"]} if t.get("launch") else {})}
    _version(p, "opened")
    _save("projects", pid, p)
    _journal("experiment", {"project": pid, "what": "project opened", "template": template, "regulatory": regulatory, "milestones": len(ms)},
             tenant_of(p))
    return public_project(p)


def tenant_of(p: dict) -> dict:
    """Sibyl tenants: one per user and one per project (each its own claim in the record)."""
    return {"user": p.get("owner") or "", "project": p["id"]}


def check_brief(brief: dict) -> dict:
    """The free Ready-to-fund check (POST /api/ready, knos_ready on /mcp): nothing is stored or sent. With it, the
    IDT view of the brief (knos.idt): its intent sketch, ambiguity, readings to tap, at most one question, the route
    (fast path or rewrite), the effort and token budget an agent run gets, and the milestones' tiers."""
    from knos import idt
    r = _ready().check(brief)                 # names what is malformed, from the brief as it was sent
    if r.get("ready"):
        from . import usage
        usage.bump(briefs=1)
    brief = _ready().clean(brief)              # the rest reads a clean shape: a malformed brief is never a server error
    rt = idt.route(brief)
    if rt["interpretations"]:
        rt["interpretations"] = idt.interpretations(" ".join(json.dumps(m) for m in (brief or {}).get("milestones") or []), patterns())
    return {**r, "idt": {**rt, "sketch": idt.sketch(brief), "tiers": idt.tiers(brief), "benchmark": idt.benchmark_for(brief)}}


def patterns() -> dict:
    """Resolved ambiguity patterns: the reading a buyer tapped for a vague word, offered first next time."""
    f = _dir("patterns") / "resolved.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def resolve(word: str, reading: str, target: str, user: dict | None = None) -> dict:
    """Keep the reading a buyer chose for a vague word (stored here and in the Sibyl record's reference line)."""
    from knos import ready
    word, reading, target = (str(x or "").strip()[:80] for x in (word, reading, target))
    if word not in ready.VAGUE or not reading or not target:
        raise Refused("resolve: a vague word, the reading chosen and its target")
    with _lock:
        got = patterns()
        rows = [x for x in got.get(word, []) if x[1] != target]
        got[word] = [[reading, target]] + rows[:4]
        (_dir("patterns") / "resolved.json").write_text(json.dumps(got, indent=1), encoding="utf-8")
    _journal("verdict", {"what": "ambiguity pattern resolved", "word": word, "reading": reading, "target": target})
    return {"word": word, "patterns": got[word]}


def grounding(p: dict) -> dict | None:
    """The Qloo facts of the crossing a project came from (its decision report): audience, launch cities, price tier."""
    h = p.get("report")
    f = escrow._state_dir() / "reports" / f"{h}.report" if isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h) else None
    if not f or not f.exists():
        return p.get("grounding_snapshot")         # the report is gone (a redeploy): the line as it was when saved
    try:
        rep = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return p.get("grounding_snapshot")
    plan = (rep.get("decision") or {}).get("plan") or {}
    fam = rep.get("grounding") or {}                # the families' answers (knos_wanted.families.grounding)
    who = plan.get("who") or {}
    out = {"audience": {k: who.get(k) for k in ("age", "gender") if who.get(k)} | ({"segments": (who.get("segments") or fam.get("segments") or [])[:3]}
                                                                                   if who.get("segments") or fam.get("segments") else {}),
           "launch_cities": (plan.get("where") or fam.get("cities") or [])[:3], "price_tier": plan.get("tier") or fam.get("price_tier"),
           "unit_price": plan.get("unit_price"), "comparables": (fam.get("comparables") or [])[:4],
           "asked": {k: v for k, v in (rep.get("options") or {}).items() if k not in ("qloo", "qloo_calls")}, "source": "Qloo"}
    return {k: v for k, v in out.items() if v}


def milestone_prompt(pid: str, key: str) -> dict:
    """What an agent working on a milestone is handed (knos.idt.agent_prompt): the locked intent and its hash, the
    effort level and token budget, Chain-of-Draft steps and the stop rule."""
    from knos import idt
    p = project(pid)
    _milestone(p, key)
    h = (p.get("frozen") or {}).get("criteria_hash")
    out = idt.agent_prompt(_brief(p), key, h, patterns(), grounding(p))
    return {**out, "locked": bool(h), "project": pid, "grounding": grounding(p)}


def gate(p: dict) -> dict:
    """Money locks only on a Ready brief, and only before the buyer cancels."""
    if p.get("status") == "cancelled":
        raise Refused("this project was cancelled by its buyer")
    r = readiness(p)
    if not r["ready"]:
        raise Refused("Not ready to fund: " + "; ".join(r["missing"][:8]))
    if p.get("frozen") and p["frozen"]["criteria_hash"] != r["criteria_hash"]:
        raise Refused("the brief changed after it was locked without an accepted change request")
    return r


def _freeze(p: dict, order: str) -> None:
    if not p.get("frozen"):
        r = readiness(p)
        p["frozen"] = {"criteria_hash": r["criteria_hash"], "at": _now(), "order": order, "kill_fee_bps": p.get("kill_fee_bps", 0),
                       "challenge_s": p.get("challenge_s")}
        _journal("experiment", {"project": p["id"], "what": "criteria locked", "criteria_hash": r["criteria_hash"], "order": order},
                 tenant_of(p))


def _set_brief(p: dict, brief: dict) -> None:
    rd = _ready()
    rows = [rd.normal(m if isinstance(m, dict) else {}, i) for i, m in enumerate(brief.get("milestones") or [])]
    by = {m["key"]: m for m in p["milestones"]}
    if {n["key"] for n in rows} != set(by):
        raise Refused("brief: the same milestone keys as the project (" + ", ".join(by) + ")")
    for n in rows:
        m = by[n["key"]]
        m.update(name=n["name"] or m["name"], target=n["target"], verifier=n["verifier"], deadline_s=n["deadline_s"] or m["deadline_s"])
    t = rd.terms(brief)
    p["kill_fee_bps"], p["challenge_s"] = t["kill_fee_bps"], t["challenge_s"]


def edit_brief(pid: str, user: dict, brief: dict) -> dict:
    """The owner edits the brief until money locks; after that only a change request the maker accepts."""
    with _lock:
        p = project(pid)
        if p.get("owner") != _user_key(user):
            raise Refused("only the project's buyer edits its brief")
        if p.get("frozen"):
            raise Refused("money is locked on this brief: propose a change request; the maker accepts or rejects it")
        _set_brief(p, brief)
        v = _version(p, "edited")
        _save("projects", pid, p)
    return {**public_project(p), "version": v}


def _makers(p: dict) -> set:
    return {a["maker_sub"] for m in p["milestones"] for a in m["attempts"]}


def change_request(pid: str, user: dict, brief: dict, why: str = "") -> dict:
    with _lock:
        p = project(pid)
        if p.get("owner") != _user_key(user):
            raise Refused("only the project's buyer proposes a change")
        if not p.get("frozen"):
            raise Refused("nothing is locked yet: edit the brief directly")
        trial = json.loads(json.dumps(p))
        _set_brief(trial, brief)
        r = readiness(trial)
        if not r["ready"]:
            raise Refused("the changed brief is Not ready: " + "; ".join(r["missing"][:8]))
        cr = {"id": _id("change", pid, _now(), len(p["changes"]))[:10], "brief": _brief(trial), "criteria_hash": r["criteria_hash"],
              "from_hash": p["frozen"]["criteria_hash"], "why": str(why or "")[:300], "status": "proposed", "at": _now()}
        p["changes"].append(cr)
        _save("projects", pid, p)
    _journal("experiment", {"project": pid, "what": "change request", "change": cr["id"], "criteria_hash": cr["criteria_hash"]}, tenant_of(p))
    return cr


def decide_change(pid: str, user: dict, cid: str, accept: bool) -> dict:
    with _lock:
        p = project(pid)
        cr = next((c for c in p["changes"] if c["id"] == cid), None)
        if cr is None or cr["status"] != "proposed":
            raise Refused("change: not an open change request on this project")
        who = _user_key(user)
        if who == p.get("owner") or who not in _makers(p):
            raise Refused("the maker of this project (someone with an attempt on it) accepts or rejects a change")
        cr["status"], cr["decided"], cr["by"] = ("accepted" if accept else "rejected"), _now(), str(user.get("label") or "maker")[:80]
        if accept:
            _set_brief(p, cr["brief"])
            p["frozen"] = {**p["frozen"], "criteria_hash": cr["criteria_hash"], "at": _now(), "change": cid,
                           "kill_fee_bps": p["kill_fee_bps"], "challenge_s": p["challenge_s"]}
            _version(p, f"change {cid} accepted")
        _save("projects", pid, p)
    _journal("experiment", {"project": pid, "what": f"change {cr['status']}", "change": cid, "criteria_hash": cr["criteria_hash"]}, tenant_of(p))
    return {**cr, "project": public_project(p)}


def cancel(pid: str, user: dict, led=None, base: str | None = None) -> dict:
    """The buyer cancels. A milestone a maker is working on releases the agreed kill fee to that maker and the rest
    back to the funder, through the same referee panel; an untaken one is refunded to the funder at its deadline."""
    with _lock:
        p = project(pid)
        if p.get("owner") != _user_key(user):
            raise Refused("only the project's buyer cancels it")
        if p.get("status") == "cancelled":
            raise Refused("already cancelled")
        p["status"] = "cancelled"
        _save("projects", pid, p)
    led = _ledger(led)
    kf = int(p.get("kill_fee_bps") or 0)
    out = []
    for m in p["milestones"]:
        a = next((x for x in m["attempts"] if x["status"] in ("working", "result posted", "verdict posted", "checked")), None)
        for oid in m["fundings"]:
            o = _safe_order(oid)
            if not o or o["status"] != "locked":
                continue
            if a is None or kf == 0:
                out.append({"order": oid, "status": "refunded at the deadline", "kill_fee_units": 0})
                continue
            from knos.ideas import commit as C
            mk, fu = C.parse_payee(a["wallet"]), C.parse_payee(o["funder"])
            o["doc"]["payee"] = {**mk, "split": [{"payee_id": mk["payee_id"], "bps": kf, "wallet": mk["wallet"]},
                                                  {"payee_id": fu["payee_id"], "bps": 10_000 - kf, "wallet": fu["wallet"]}]}
            o["kill_fee"] = {"bps": kf, "maker": a["wallet"], "units": o["units"] * kf / 10_000}
            _save("orders", oid, o)
            rv = {"project": pid, "milestone": m["key"], "attempt": a["id"], "result": a.get("result"), "check": a.get("check"),
                  "rule": f"cancelled by the buyer: the maker keeps the agreed kill fee ({kf / 100:g}%), the rest returns to the funder"}
            try:
                got = _frost_start(pid, m["key"], a, o, rv, led, base)
            except Refused as why:
                got = {"order": oid, "status": f"kill fee due, not sent: {why}"}
            out.append({**got, "kill_fee_units": o["kill_fee"]["units"]})
    _journal("experiment", {"project": pid, "what": "cancelled by the buyer", "kill_fee_bps": kf, "orders": out}, tenant_of(p))
    archive(pid)
    return {"project": pid, "status": "cancelled", "kill_fee_bps": kf, "orders": out}


def dispute(pid: str, key: str, attempt: str, user: dict, url: str) -> dict:
    """Inside the challenge window, the buyer or the maker disputes a referee verdict with an evidence page: the
    automatic release stops and the money stays locked (refunded at the deadline unless the panel decides again)."""
    with _lock:
        p = project(pid)
        m = _milestone(p, key)
        a = next((x for x in m["attempts"] if x["id"] == attempt), None)
        if a is None or a["status"] != "verdict posted":
            raise Refused("dispute: only a posted verdict inside its challenge window")
        who = _user_key(user)
        if who not in (p.get("owner"), a["maker_sub"]):
            raise Refused("the buyer or the maker disputes a verdict")
        if not re.fullmatch(r"https://[^\s]{4,2000}", url or ""):
            raise Refused("url: the public https page with your evidence")
        a["status"], a["dispute"] = "disputed", {"url": url, "by": str(user.get("label") or "")[:80], "at": _now()}
        m["history"].append({"at": _now(), "what": f"verdict on attempt {attempt} disputed", "url": url})
        _save("projects", pid, p)
    _journal("experiment", {"project": pid, "milestone": key, "what": "verdict disputed", "attempt": attempt, "url": url}, tenant_of(p))
    return {"attempt": attempt, "status": "disputed", "money": "stays locked"}


def archive(pid: str) -> dict:
    """A closed project (every milestone released, or cancelled) is archived in its Sibyl tenant."""
    p = project(pid)
    if p.get("archived"):
        return {"archived": True}
    if p.get("status") != "cancelled" and not all(m["status"] == "released" for m in p["milestones"]):
        return {"archived": False}
    p["archived"] = _now()
    _save("projects", pid, p)
    return _journal("verdict", {"project": pid, "what": "project archived", "status": p.get("status"),
                                "versions": [v["criteria_hash"] for v in p.get("versions") or []]}, tenant_of(p))


def project(pid: str) -> dict:
    p = _load("projects", pid)
    if "versions" not in p and p.get("template") in catalogue()["templates"]:
        from .templates_data import CRITERIA, REGULATORY_CRITERIA
        with _lock:
            for m in p["milestones"]:
                cr = CRITERIA.get((p["template"], m["key"])) or {**REGULATORY_CRITERIA, "verifier": dict(REGULATORY_CRITERIA["verifier"], what=m["name"])}
                m.setdefault("target", cr["target"])
                m.setdefault("verifier", cr["verifier"])
            p.setdefault("kill_fee_bps", 0)
            p.setdefault("challenge_s", _ready().DEFAULT_CHALLENGE_S)
            p.setdefault("frozen", None)
            p.setdefault("changes", [])
            p.setdefault("status", "open")
            _version(p, "acceptance criteria added")
            _save("projects", pid, p)
    return p


def _milestone(p: dict, key: str) -> dict:
    for m in p["milestones"]:
        if m["key"] == key:
            return m
    raise Refused("milestone: not in this project")


def public_project(p: dict) -> dict:
    out = {k: v for k, v in p.items() if k != "owner"}
    out["ready"] = readiness(p) if "versions" in p else {"ready": False, "label": "Not ready", "missing": ["brief: opened before the check"]}
    out.setdefault("changes", [])
    out["grounding"] = grounding(p)                 # the Ready brief's "Grounding (Qloo)" line: who, where, price tier, comparables
    from . import chainx
    out["credits"] = chainx.credits_of(p["id"])     # the project's credit mint: moves only into its escrow (the transfer hook)
    out["milestones"] = []
    for m in p["milestones"]:
        raw = [o for o in (_safe_order(x) for x in m["fundings"]) if o]
        orders = [_order_public(o) for o in raw]
        locked = sum(o["units"] * o["unit_price"] for o in raw if o["status"] == "locked")
        pledged = sum(a["units"] for a in amc_of(p["id"], m["key"]) if a["status"] == "approved")
        out["milestones"].append({**{k: v for k, v in m.items() if k not in ("fundings", "excluded")},
                                  "attempts": [{k: v for k, v in a.items() if k not in ("maker_sub", "check_sub")} for a in m["attempts"]],
                                  "orders": orders, "locked_units": locked, "amc_units": pledged, "excluded_makers": len(m["excluded"]),
                                  "route": route(m)})
    return out


_list_cache: dict[int, tuple[float, list[dict]]] = {}


def _one_each(ps: list[dict]) -> list[dict]:
    """Each idea once in the public list: of the projects with the same title, the one furthest along (released
    milestones, then units held), else the newest. The others stay readable by their own id."""
    def ahead(p: dict) -> tuple[int, int]:
        ms = p.get("milestones") or []
        return (sum(m.get("status") == "released" for m in ms), sum(int(m.get("locked_units") or 0) for m in ms))
    best: dict[str, dict] = {}
    order: list[str] = []
    for p in ps:
        k = " ".join(str(p.get("title") or p.get("id") or "").lower().split())
        if k not in best:
            best[k] = p
            order.append(k)
        elif ahead(p) > ahead(best[k]):
            best[k] = p
    return [best[k] for k in order]


# kept off the public list (each still opens by its id): test rows, Knos's own plan, and the older products' rows (the
# sealed-classifier round, a company's ledger integration), which no research idea crossed into (sweep 22, CODE.md 2.16)
OFF_LIST = re.compile(r"\(test\)\s*$|^Knos:|sealed classifier|autoresearch|syncs our invoices to the ledger", re.I)


def listed(p: dict) -> bool:
    return not p.get("unlisted") and not OFF_LIST.search(str(p.get("title") or ""))


def projects(n: int = 50) -> list[dict]:
    """The public list: every project not archived, newest first. An archived one stays readable by its id. Built at
    most once every 30 s (it read every project file and made ~800 KB; under a page test's load that took 17 s), and
    again at once after any project is saved (_save clears it)."""
    hit = _list_cache.get(n)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    out = _one_each([public_project(p) for p in _all("projects") if listed(p)])[:n]
    _list_cache[n] = (time.time(), out)
    _json_cache.pop(n, None)
    return out


_json_cache: dict[int, tuple[float, bytes]] = {}
_sum_cache: dict[int, tuple[float, bytes]] = {}
_sum_stale: set[int] = set()                       # takes whose summary a save since has made old


def summary(p: dict) -> dict:
    """A project as the list draws it: its title, template and each milestone's state and held units. No devnet read
    (the credit mint, the readiness and the grounding are on GET /api/project?id=)."""
    ms = []
    for m in p["milestones"]:
        raw = [o for o in (_safe_order(x) for x in m["fundings"]) if o]
        ms.append({"key": m["key"], "name": m.get("name"), "status": m.get("status"),
                   "locked_units": sum(o["units"] * o["unit_price"] for o in raw if o["status"] == "locked")})
    return {"id": p["id"], "title": p.get("title"), "template_name": p.get("template_name"), "regulatory": p.get("regulatory") or [],
            "sandbox": p.get("sandbox"), "milestones": ms}


def summaries_json(take: int = 10) -> bytes:
    """GET /api/projects: the newest `take` projects not archived, as summaries. Built at boot (warm_summaries) and again
    only after a project or order is saved (_save marks it old); otherwise answered from memory, else from the file the
    last build wrote beside the projects (a deploy or a sleep empties memory). A sweep that changes nothing rewrites nothing."""
    if take in _sum_stale:
        return _build_summaries(take)
    hit = _sum_cache.get(take)
    if hit:
        return hit[1]
    f = _dir("pages") / f"projects-summary-{take}.json"
    try:
        body = f.read_bytes()
    except OSError:
        return _build_summaries(take)
    _sum_cache[take] = (time.time(), body)
    return body


def warm_summaries() -> None:
    """At boot: the list's summary is built once, so the first visitor to /app/#projects reads a file, never all projects."""
    try:
        _build_summaries(10)
    except Exception as why:  # noqa: BLE001 - the list is then built on its first call
        print(f"knos projects summary: {type(why).__name__}: {str(why)[:200]}", flush=True)


def list_html(take: int = 10) -> str:
    """The projects list as static/valley.js draws it (#projList), for the page itself: there at the first paint."""
    from html import escape as e
    rows = json.loads(summaries_json(take)).get("projects") or []
    out = []
    for p in rows:
        ms = p.get("milestones") or []
        locked, done = sum(m.get("locked_units") or 0 for m in ms), sum(1 for m in ms if m.get("status") == "released")
        reg = p.get("regulatory") or []
        out.append(f'<li class="card pcard"><a href="#projects={e(str(p["id"]))}"><strong>{e(str(p.get("title") or ""))}</strong></a>'
                   f'<p class="small muted">{e(str(p.get("template_name") or ""))}{" · regulated (" + e(", ".join(reg).upper()) + ")" if reg else ""}'
                   f'{" · one-day sandbox" if p.get("sandbox") else ""}</p><p class="small">{done} of {len(ms)} milestones released · {locked} test units held</p></li>')
    return "".join(out)


def _build_summaries(take: int) -> bytes:
    rows = _one_each([summary(p) for p in _all("projects") if listed(p)])[:take]
    body = json.dumps({"projects": rows, "take": take, "shape": "summary", "one": "/api/project?id=<id>"}, default=str).encode()
    _sum_stale.discard(take)
    _sum_cache[take] = (time.time(), body)
    try:
        f = _dir("pages") / f"projects-summary-{take}.json"
        if not f.is_file() or f.read_bytes() != body:   # written only when the list changed
            tmp = f.with_suffix(".tmp")
            tmp.write_bytes(body)
            tmp.replace(f)
    except OSError:
        pass
    return body


def projects_json(n: int = 50) -> bytes:
    """GET /api/projects as bytes, encoded once for every request in the same 30 s: each request had made its own copy
    of ~800 KB, and many at once ran the free instance out of memory (Render killed it at 512 MB, 23 Oct 2026)."""
    lst = projects(n)                              # refreshes _list_cache (and drops this one) when it is stale
    built = (_list_cache.get(n) or (0.0, None))[0]  # a save in another thread may have cleared it: then build anew
    hit = _json_cache.get(n)
    if hit and built and hit[0] == built:
        return hit[1]
    body = json.dumps({"projects": lst}, default=str).encode()
    if built:
        _json_cache[n] = (built, body)
    return body


def unlist(pid: str, user: dict | None = None, admin: bool = False, why: str = "") -> dict:
    """POST /api/project/archive: take a project off the public list (it stays readable by id). Its buyer archives their own; the operator's admin
    key (KNOS_ADMIN_KEY on the server, never shown) archives any, e.g. a test project left by a proof run. Money is
    untouched: a project with locked funding is refused, cancel it first."""
    with _lock:
        p = project(pid)
        if not admin and p.get("owner") != _user_key(user or {}):
            raise Refused("only the project's buyer (or the operator) archives it")
        if any(o and o.get("status") == "locked" for m in p["milestones"] for o in (_safe_order(x) for x in m["fundings"])):
            raise Refused("money is locked on this project: cancel it first, then archive it")
        if not p.get("unlisted"):      # apart from `archived` (a closed project's Sibyl record), which stays listed
            p["unlisted"] = {"at": _now(), "by": "operator" if admin else "buyer", "why": str(why or "")[:200]}
            _save("projects", pid, p)
    return {"project": pid, "archived": p["unlisted"], "listed": False, "readable_at": f"/api/project?id={pid}"}


# ---- routing to existing capacity ---- -------------------------------------------------------------------------------
def route(m: dict) -> dict:
    """Where this milestone's work can be bought: the knos.labs adapters (live with the maker's own key, else a labelled
    fixture quote), knos.game for code-scored work, or the maker's own shop. Work is routed only once committed money
    (escrow + AMC allowances) covers the quote: buyers commit first."""
    cap = catalogue()["capacity"].get(m.get("route") or "none", [])
    out = []
    for c in cap:
        row = {k: v for k, v in c.items()}
        if c.get("adapter"):
            try:
                from knos.labs import contract
                q = contract.adapters()[c["adapter"]].quote()
                row["quote"] = {k: q.get(k) for k in ("price", "currency", "turnaround_days", "mode", "fixture", "price_basis", "source")}
            except Exception as why:  # noqa: BLE001 - a lab that cannot quote here says why
                row["quote"] = {"error": f"{type(why).__name__}: {str(why)[:120]}"}
        out.append(row)
    return {"kind": m.get("route") or "none", "capacity": out,
            "rule": "work is ordered from a lab only when held money + AMC commitments cover its quote; a fixture quote is labelled and never ordered"}


# ---- funding: a funder's escrow, a grant, a pool (the funder's wallet signs) ---------------------------------------
def _safe_order(oid: str) -> dict | None:
    try:
        return _load("orders", oid)
    except Refused:
        return None


def _order_public(o: dict) -> dict:
    return {k: o.get(k) for k in ("order", "project", "milestone", "units", "unit_price", "kind", "funder", "grant", "pool", "referral",
                                  "status", "signatures", "made", "deadline_s", "claim_id", "criteria_hash", "kill_fee", "receipt", "finality",
                                  "private", "sibyl")} | ({"units": None} if o.get("private") else {}) | {
        "explorer": escrow.explorer(o["order"], "address"), "trust": _trust(o)}


def private_pledge(order: str, body: dict, led=None) -> dict:
    """The encrypted amount of a private order and its two proofs (knos_wanted.chainx.private_pledge), from the backer's
    browser: verified on devnet by the ZK ElGamal program, kept on the order as its receipt."""
    from . import chainx
    o = _load("orders", order)
    if not o.get("private"):
        raise Refused("this order was not funded as private")
    if o["status"] == "pending":
        raise Refused("lock the funding first: the proofs go on chain after the lock")
    if (o.get("receipt") or {}).get("private"):
        return _order_public(o)
    try:
        ct, pv, rp = (base64.b64decode(str(body.get(k) or ""), validate=True) for k in ("ciphertext", "pubkey_proof", "range_proof"))
        got = chainx.private_pledge(order, ct, pv, rp, led)
    except ValueError as why:
        raise Refused(str(why)) from None
    with _lock:
        o = _load("orders", order)
        o.setdefault("receipt", {})["private"] = got
        _save("orders", order, o)
    return _order_public(o)


def _trust(o: dict) -> dict | None:
    """The code referee's run, its knos_oidc verification on devnet, its Sigstore attestation and the FROST release of
    this order's referee session (knos_wanted.referee.trust); None when the order has none."""
    from . import referee
    try:
        return referee.trust((o.get("referee_session") or {}).get("id"))
    except Exception:  # noqa: BLE001 - a page never fails on what it only shows
        return None


def _ledger(led=None):
    return led or escrow.ledger()


def fund_tx(pid: str, key: str, units: int, account: str, kind: str = "funder", grant: dict | None = None, ref: str | None = None,
            pool: str | None = None, led=None, private: bool = False) -> dict:
    """The devnet transaction a funder's wallet signs to lock `units` test units on one milestone (its own panel order).
    The server co-signs only the test-unit top-up (it is the test mint's authority) and keeps the pending order."""
    from solders.hash import Hash
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction

    from knos import chain, ideas
    from knos.ideas import commit as C
    from knos.settle.v2 import pay

    from . import blink, preorder
    if kind not in ("funder", "grant", "pool"):
        raise Refused("kind: funder, grant or pool")
    if isinstance(units, bool) or not isinstance(units, int) or not 5 <= units <= 1000:
        raise Refused("units: 5 to 1,000 test units")
    try:
        wallet = Pubkey.from_string(str(account))
    except ValueError:
        raise Refused("account: the funder's Solana wallet address") from None
    if kind == "grant":
        grant = {k: str((grant or {}).get(k) or "").strip()[:120] for k in ("agency", "id", "url")}
        if not grant["agency"] or not grant["id"]:
            raise Refused("grant: the agency and the grant's id (the award it comes from)")
    referral = load_referral(ref) if ref else None
    p = project(pid)
    m = _milestone(p, key)
    if m["status"] == "released":
        raise Refused("this milestone is already released")
    crit = gate(p)["criteria_hash"]
    preorder._need()
    led = _ledger(led)
    authority, pan = escrow.demo_key(), preorder.panel()        # the FROST group key (1 of 1) when configured
    mint = escrow.mint(led, create=False)
    claim = ideas.claim(memo(p, m, crit), field_name=preorder.FIELD, kind="person", by={"app": "knos projects", "project": pid, "milestone": key})
    tok = pay.ata(wallet, mint)
    cap = blink._Capture(led)
    # the payee is bound when a maker claims the milestone (claim); until then the funder's own wallet stands in the
    # document (never paid: a release needs a claimed attempt, a refund always goes back to the funder)
    from knos import ready
    tranches = ready.tranches(int(m["deadline_s"]))       # an order holds money 90 days at most: a long milestone, in tranches
    doc = C.commit(claim, units=units, price=1, payee=C.parse_payee(str(wallet)), funder=blink._Wallet(wallet), funder_token=tok,
                   mint=mint, led=cap, stages=[("referee_pass", 10_000)], stage_work_s=[tranches[0]],
                   panel=pan, program=preorder.program(), demand_hash=p.get("report"), unlisted_panel=True, criteria=_brief(p))
    amount = units * escrow.UNIT
    setup = [pay.create_ata_ix(authority.pubkey(), w, mint) for w in (pay.FEE_OWNER,) if led.account(pay.ata(w, mint)) is None]
    if setup:
        led.send(setup, authority)
    ixs = [pay.create_ata_ix(wallet, wallet, mint)] if led.account(tok) is None else []
    ixs.append(escrow._mint_to_ix(mint, tok, authority.pubkey(), -(-(amount + pay.order_fee(amount)) // escrow.UNIT)))
    ixs += [ix for batch in cap.sent for ix in batch if ix.program_id == preorder.program()]
    bh = Hash.from_string(chain.call(led.url, "getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])
    tx = Transaction.new_unsigned(Message.new_with_blockhash(ixs, wallet, bh))
    tx.partial_sign([authority], bh)
    raw = bytes(tx)
    if len(raw) > preorder.TX_BUDGET:
        raise Refused(f"the funding transaction is {len(raw)} bytes, above Knos's budget of {preorder.TX_BUDGET}")
    st = doc["orders"]["stage1"]
    o = {"order": st["order"], "project": pid, "milestone": key, "claim_id": claim["id"], "units": units, "unit_price": 1, "kind": kind,
         "funder": str(wallet), "grant": grant if kind == "grant" else None, "pool": pool,
         "referral": {"code": referral["code"], "wallet": referral["wallet"]} if referral else None,
         "status": "pending", "deadline_s": int(m["deadline_s"]), "tranches": tranches, "tranche": 1,
         "doc": doc, "made": _now(), "signatures": {}, "criteria_hash": crit,
         "private": private is True}
    _save("orders", st["order"], o)
    with _lock:
        p = project(pid)
        _milestone(p, key)["fundings"].append(st["order"])
        _save("projects", pid, p)
    return {"transaction": base64.b64encode(raw).decode(), "bytes": len(raw), "order": st["order"], "claim_id": claim["id"],
            "message": f"Locks {units} test units on '{m['name']}' (devnet). Paid to the maker only on a result and an independent check; "
                       "refunded to you after the deadline otherwise."}


def _finality_async(order: str, sig: str | None, sent_at: float, url: str) -> None:
    """A release's finality, measured: the seconds from sending it to its finalized notification (signatureSubscribe),
    kept on the order and shown on its project page."""
    if not sig:
        return

    def run():
        from knos.platform import priority
        try:
            priority.wait_ws(url, sig, within=120.0, commitment="finalized")
            got = {"seconds": round(time.time() - sent_at, 2), "commitment": "finalized", "via": "signatureSubscribe"}
        except Exception as why:  # noqa: BLE001
            got = {"error": f"{type(why).__name__}: {str(why)[:120]}"}
        with _lock:
            o = _safe_order(order)
            if o is not None:
                o["finality"] = got
                _save("orders", order, o)
    threading.Thread(target=run, daemon=True, name="knos-finality").start()


def _receipt_async(kind: str, order: str, claim: str = "", units: int = 0, pid: str = "") -> None:
    """The order's Token-2022 pledge receipt (knos_wanted.chainx): written on lock, burned on refund, off the request's
    path: a receipt that cannot be written never holds up the money, it is said in the log and kept on the order."""
    def run():
        from . import chainx
        try:
            got = chainx.pledge_receipt(order, claim, units) if kind == "pledge" else chainx.receipt_refund(order)
        except Exception as why:  # noqa: BLE001
            got = {"error": f"{type(why).__name__}: {str(why)[:160]}"}
            print(f"knos projects: pledge receipt ({kind}) of {order}: {got['error']}", flush=True)
        credits = None
        if kind == "pledge" and pid:            # the units as project credits, moved into the escrow through the transfer hook
            try:
                credits = chainx.project_credits(pid, order, units)
            except Exception as why:  # noqa: BLE001
                credits = {"error": f"{type(why).__name__}: {str(why)[:160]}"}
                print(f"knos projects: project credits of {order}: {credits['error']}", flush=True)
        with _lock:
            o = _safe_order(order)
            if o is not None:
                o.setdefault("receipt", {})[kind] = got
                if credits is not None:
                    o["receipt"]["credits"] = credits
                _save("orders", order, o)
    threading.Thread(target=run, daemon=True, name="knos-receipt").start()


def memo(p: dict, m: dict, crit: str) -> str:
    """The order's memo (its claim statement, committed on chain in the order's commitment hash): names the criteria hash."""
    return (f"Milestone '{m['name']}' of the Knos project '{p['title']}' ({p['id']}, funding {len(m['fundings']) + 1}); "
            f"criteria sha256:{crit}")


def confirm(order: str, signature: str | None = None, led=None) -> dict:
    """A pending funding becomes locked once its order account exists on chain."""
    from solders.pubkey import Pubkey
    o = _load("orders", order)
    if o["status"] == "pending":
        led = _ledger(led)
        if led.account(Pubkey.from_string(o["order"])) is None:
            raise Refused("the order is not on devnet yet: send the signed transaction first")
        o["status"] = "locked"
        if signature and re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{64,90}", signature):
            o["signatures"]["lock"] = signature
        _save("orders", order, o)
        from . import outside
        outside.note("commitment", order, "milestone funding")
        with _lock:
            p = project(o["project"])
            m = _milestone(p, o["milestone"])
            if m["status"] in ("open", "reopened"):
                m["status"] = "funded"
            m["history"].append({"at": _now(), "what": f"funded privately ({o['kind']})" if o.get("private") else
                                 f"funded {o['units']} test units ({o['kind']})", "order": order})
            _freeze(p, order)
            _save("projects", p["id"], p)
        if not o.get("private"):                # a private order's amount goes on chain only encrypted (private_pledge)
            _receipt_async("pledge", order, o.get("claim_id") or "", o["units"], o["project"])
        j = _journal("funding", {"project": o["project"], "milestone": o["milestone"], "order": order, "kind": o["kind"],
                                 "amount_units": o["units"], "signature": o["signatures"].get("lock"), "grant": o.get("grant"),
                                 "criteria_hash": o.get("criteria_hash")}, tenant_of(p))
        if j.get("sibyl"):                    # kept on the order (read again: the receipt's thread may have saved it)
            with _lock:
                o = _safe_order(order) or o
                o["sibyl"] = j["sibyl"]
                _save("orders", order, o)
    return _order_public(o)


def pool_txs(allocations: list[dict], units: int, account: str, ref: str | None = None, led=None) -> dict:
    """The megafund: one funder spreads `units` over many milestones of many projects, by weight. One transaction per
    milestone (each its own order), signed together by the wallet (signAllTransactions)."""
    if not isinstance(allocations, list) or not 2 <= len(allocations) <= 8:
        raise Refused("allocations: 2 to 8 {project, milestone, weight}")
    w = [max(1, int(a.get("weight") or 1)) for a in allocations]
    if isinstance(units, bool) or not isinstance(units, int) or units < 5 * len(allocations):
        raise Refused(f"units: at least 5 per milestone ({5 * len(allocations)})")
    share = [max(5, units * x // sum(w)) for x in w]
    pool = _id("pool", account)
    txs = [fund_tx(str(a["project"]), str(a["milestone"]), s, account, kind="pool", ref=ref, pool=pool, led=led)
           for a, s in zip(allocations, share)]
    _save("pools", pool, {"id": pool, "funder": account, "units": sum(share), "orders": [t["order"] for t in txs], "made": _now()})
    return {"pool": pool, "transactions": txs, "units": sum(share)}


# ---- referrals ---- --------------------------------------------------------------------------------------------------
def make_referral(user: dict, wallet: str, target: str) -> dict:
    from solders.pubkey import Pubkey
    try:
        Pubkey.from_string(str(wallet))
    except ValueError:
        raise Refused("wallet: the referrer's Solana wallet (its share is paid there on release)") from None
    if not re.fullmatch(r"(p|b)=[0-9a-f]{16,64}", str(target or "")):
        raise Refused("target: p=<project id> or b=<report hash>")
    code = _id("ref", wallet, target)[:12]
    r = {"code": code, "wallet": str(wallet), "target": target, "by": _user_key(user), "label": str(user.get("label") or "")[:80],
         "made": _now(), "share_bps": REFERRAL_BPS}
    _save("referrals", code, r)
    return {"code": code, "link": f"/r/{code}", "share_bps": REFERRAL_BPS, "target": target,
            "rule": "when a sale or funding made through this link is released on proof, your share is a second knos_pay payee"}


def load_referral(code: str) -> dict:
    try:
        return _load("referrals", str(code))
    except Refused:
        raise Refused("ref: unknown referral code") from None


def split_payee(maker_wallet: str, referral: dict | None, maker_payee: dict | None = None) -> dict:
    """The payee of a release: the maker, and the referrer's share as a second knos_pay payee (one payee each, bps sum
    10,000). The program pays every payee named in the panel's verdicts."""
    from knos.ideas import commit as C
    base = maker_payee or C.parse_payee(maker_wallet)
    if not referral or referral.get("wallet") == maker_wallet:
        return base
    ref = C.parse_payee(referral["wallet"])
    return {**base, "split": [{"payee_id": base["payee_id"], "bps": 10_000 - REFERRAL_BPS, "wallet": base["wallet"]},
                              {"payee_id": ref["payee_id"], "bps": REFERRAL_BPS, "wallet": ref["wallet"]}]}


# ---- attempts: claim, result, independent check, release ---- -------------------------------------------------------
def claim(pid: str, key: str, user: dict, wallet: str) -> dict:
    """A maker takes the milestone (parallel attempts allowed) and binds the wallet it is paid at. An agent key's claim
    is paid only at the key's payout wallet and counts against its claim cap (knos_wanted.agentkeys)."""
    from solders.pubkey import Pubkey
    kid = user.get("agent_key") if user.get("kind") == "agent" else None
    if kid:
        if wallet and wallet != user.get("payout_wallet"):
            raise Refused("an agent key is paid only at its payout wallet: leave wallet out")
        wallet = str(user.get("payout_wallet") or "")
    try:
        Pubkey.from_string(str(wallet))
    except ValueError:
        raise Refused("wallet: your Solana wallet (the payee bound at claim)") from None
    if kid:
        from . import agentkeys
        agentkeys.take_claim(kid)                   # counted first, given back below when the claim is refused
        try:
            a = _claim(pid, key, user, wallet)
        except Exception:
            agentkeys.give_back(kid)
            raise
        agentkeys.note_attempt(kid, pid, key, a["id"])
        return a
    return _claim(pid, key, user, wallet)


def _claim(pid: str, key: str, user: dict, wallet: str) -> dict:
    who = _user_key(user)
    kid = user.get("agent_key") if user.get("kind") == "agent" else None
    with _lock:
        p = project(pid)
        m = _milestone(p, key)
        if m["status"] == "released":
            raise Refused("this milestone is already released")
        if kid:                                     # a payout the key could never take is refused now, not at release
            from . import agentkeys
            agentkeys.can_spend(kid, _payout_units(p, m))
        if who in m["excluded"]:
            raise Refused("you missed this milestone's deadline once: it is reopened to other makers")
        live = [a for a in m["attempts"] if a["status"] in ("working", "result posted")]
        if any(a["maker_sub"] == who for a in live):
            raise Refused("you already have an attempt on this milestone")
        if len(live) >= MAX_ATTEMPTS:
            raise Refused(f"{MAX_ATTEMPTS} makers are already attempting this milestone")
        refs = _referee_keys()
        if wallet in refs:
            raise Refused("a referee's key cannot be a payee")
        a = {"id": _id("attempt", who, key)[:10], "maker_sub": who, "maker": str(user.get("label") or "maker")[:80], "wallet": str(wallet),
             "status": "working", "claimed": _now(), "result": None, "check": None, **({"agent_key": kid} if kid else {})}
        m["attempts"].append(a)
        if m["status"] in ("open", "funded", "reopened"):
            m["status"] = "claimed" if m["fundings"] else m["status"]
        m["history"].append({"at": _now(), "what": f"attempt {a['id']} claimed by {a['maker']}"})
        _save("projects", pid, p)
    _journal("experiment", {"project": pid, "milestone": key, "what": "attempt claimed", "attempt": a["id"], "payee_wallet": wallet})
    return {k: v for k, v in a.items() if k != "maker_sub"}


def _referee_keys() -> list[str]:
    keys: list[str] = []
    from . import preorder
    try:
        keys += preorder.panel()[1]
    except Exception:  # noqa: BLE001
        pass
    try:
        keys += [str(r.pubkey()) for r in preorder.referees()]
    except Exception:  # noqa: BLE001
        pass
    return keys


def _evidence_id(pid: str, key: str, attempt: str) -> str:
    return hashlib.sha256(f"{pid}|{key}|{attempt}".encode()).hexdigest()[:16]


def project_evidence(eid: str) -> bytes | None:
    """The public review page of one verified attempt (both pages' URLs and sha256s, and every funded order's claim id):
    what each FROST referee host fetches and re-checks before it signs a project milestone's release."""
    if not (isinstance(eid, str) and len(eid) == 16 and all(c in "0123456789abcdef" for c in eid)):
        return None
    f = _dir("evidence") / f"{eid}.public.json"
    return f.read_bytes() if f.exists() else None


def _claim_ids(p: dict, m: dict) -> list[str]:
    return [o["claim_id"] for o in (_safe_order(x) for x in m["fundings"]) if o and o["status"] == "locked"]


def _payout_units(p: dict, m: dict) -> int:
    """The test units a release of this milestone pays: its locked orders and its approved AMC allowances (an agent key's
    spend cap is checked against this before any money moves)."""
    locked = sum(o["units"] * o.get("unit_price", 1) for o in (_safe_order(x) for x in m["fundings"]) if o and o["status"] == "locked")
    return locked + sum(int(a["units"]) for a in amc_of(p["id"], m["key"]) if a["status"] == "approved")


def _paid_units(pid: str, key: str, paid: list[dict], collected: list[dict]) -> int:
    got = sum(o["units"] * o.get("unit_price", 1) for o in (_safe_order(x.get("order")) for x in paid if x.get("status") == "released") if o)
    ids = {c["amc"] for c in collected if c.get("status") == "collected"}
    return int(got + sum(float(a.get("collected_units") or 0) for a in amc_of(pid, key) if a["id"] in ids))


def post(pid: str, key: str, attempt: str, user: dict, url: str, role: str, fetch=None) -> dict:
    """Post evidence on an attempt: role "result" (the maker) or "check" (an independent replicator, never the maker).
    Both are fetched now; the check must come from another person on another site. Both in: the milestone releases."""
    from . import preorder
    if role not in ("result", "check"):
        raise Refused("role: result (the maker) or check (an independent replication)")
    fetch = fetch or preorder.fetch_evidence
    who = _user_key(user)
    with _lock:
        p = project(pid)
        m = _milestone(p, key)
        a = next((x for x in m["attempts"] if x["id"] == attempt), None)
        retry = a is not None and role == "check" and a["status"] == "checked" and a.get("check_sub") == who
    if retry:                                          # both pages are in and the release did not finish: send it again
        return release(pid, key, attempt)
    with _lock:
        if a is None or a["status"] not in ("working", "result posted"):
            raise Refused("attempt: not an open attempt on this milestone")
        if role == "result" and a["maker_sub"] != who:
            raise Refused("only the maker of this attempt posts its result")
        if role == "check":
            if a["maker_sub"] == who:
                raise Refused("an independent check is made by someone other than the maker")
            if not a.get("result"):
                raise Refused("the maker posts the result first")
        ids = _claim_ids(p, m)
        if not ids:
            raise Refused("this milestone has no locked funding yet: nothing to release")
        body = preorder.static_evidence(url, fetch)
        missing = [c for c in ids if c.encode() not in body]
        if missing:
            raise preorder.NotVerified(f"the page does not contain the milestone's claim id(s): {', '.join(missing)}")
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
        if role == "check" and _site(host) == _site(a["result"]["host"]):
            raise Refused("the independent check must be published on another site than the maker's result")
        ev = {"url": url, "host": host, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "by": str(user.get("label") or "")[:80],
              "at": _now()}
        a[role] = ev
        if role == "check":
            a["check_sub"] = who
        a["status"] = "result posted" if role == "result" else "checked"
        human = (m.get("verifier") or {}).get("kind") == "human"
        if role == "check" and human:
            win = int((p.get("frozen") or {}).get("challenge_s") or p.get("challenge_s") or _ready().DEFAULT_CHALLENGE_S)
            a["status"] = "verdict posted"
            a["verdict"] = {"pass": True, "at": _now(), "at_s": int(time.time()), "window_s": win, "ends_s": int(time.time()) + win,
                            "by": "the referee panel (result + independent check verified)"}
        rv = _dir("evidence") / f"{pid}-{key}-{a['id']}-{role}.page"
        rv.write_bytes(body)
        m["history"].append({"at": _now(), "what": f"{role} posted on attempt {a['id']}", "sha256": ev["sha256"]})
        _save("projects", pid, p)
    if role == "check" and a["status"] == "verdict posted":
        _journal("experiment", {"project": pid, "milestone": key, "what": "referee verdict posted", "attempt": attempt,
                                "window_s": a["verdict"]["window_s"]}, tenant_of(p))
        return {"attempt": attempt, "posted": role, "evidence": ev, "verdict": a["verdict"],
                "next": f"releases automatically after the {a['verdict']['window_s']} s challenge window unless the buyer or maker disputes"}
    if role == "check":
        return release(pid, key, attempt)
    return {"attempt": attempt, "posted": role, "evidence": ev, "next": "an independent check of this result, by another person on another site"}


def release_due(now: int | None = None, led=None) -> list[dict]:
    """Undisputed verdicts whose challenge window has ended are released (the sweeper calls this every SWEEP_S)."""
    now = int(time.time()) if now is None else now
    out = []
    for p in _all("projects"):
        for m in p["milestones"]:
            for a in m["attempts"]:
                if a["status"] == "verdict posted" and a.get("verdict", {}).get("ends_s", 1 << 62) <= now:
                    with _lock:
                        q = project(p["id"])
                        aa = next(x for x in _milestone(q, m["key"])["attempts"] if x["id"] == a["id"])
                        if aa["status"] != "verdict posted":
                            continue
                        aa["status"] = "checked"
                        _milestone(q, m["key"])["history"].append({"at": _now(), "what": f"challenge window ended undisputed: releasing attempt {a['id']}"})
                        _save("projects", p["id"], q)
                    try:
                        out.append({"project": p["id"], "milestone": m["key"], "attempt": a["id"], **release(p["id"], m["key"], a["id"], led=led)})
                    except Exception as why:  # noqa: BLE001 - one failed release never stops the others
                        out.append({"project": p["id"], "milestone": m["key"], "attempt": a["id"], "error": f"{type(why).__name__}: {str(why)[:160]}"})
    return out


def _site(host: str) -> str:
    """The registrable part of a host, roughly (last two labels; three for well-known shared hosts)."""
    parts = host.split(".")
    shared = ("github.io", "gitlab.io", "pages.dev", "netlify.app", "vercel.app", "onrender.com", "githubusercontent.com")
    for s in shared:
        if host.endswith("." + s):
            return ".".join(parts[-3:])
    return ".".join(parts[-2:])


class _V1Ledger:
    """The ledger, sending a transaction as a v1 transaction (SIMD-0385, up to 4,096 bytes) when it does not fit the
    legacy 1,232 bytes: a verdict that pays two payees (the maker and a referrer) carries both in its signed digest."""

    def __init__(self, led):
        self.led, self.url, self.v1_sent = led, getattr(led, "url", ""), []

    def __getattr__(self, name):
        return getattr(self.led, name)

    def send(self, ixs, payer, signers=None):
        try:
            from knos import chain
            big = chain.tx_size(list(ixs), payer.pubkey(), False) > 1232
        except Exception:  # noqa: BLE001 - a ledger without size checks sends as it always did
            big = False
        if big:
            sig = self.led.send(ixs, payer, signers, v1=True) if signers else self.led.send(ixs, payer, v1=True)
            self.v1_sent.append(sig)
            return sig
        return self.led.send(ixs, payer, signers) if signers else self.led.send(ixs, payer)


def release(pid: str, key: str, attempt: str, led=None, sign=None, release_fn=None, base: str | None = None) -> dict:
    """Both pages are in: for every locked order on the milestone, the referee panel signs PASS over the pair (one
    review: the two pages' hashes and bytes) and the program pays the attempt's maker (+ the referrer's share).
    An order pinned to the FROST group key (1 of 1) is released when 2 of the 3 referee hosts have fetched the
    published review (/api/project/evidence) and signed (knos_wanted.referee); an older order pinned to the server's
    3 keys is signed by 2 of them at once. Then AMC allowances on the milestone are collected to the maker."""
    from solders.pubkey import Pubkey

    from knos.ideas import commit as C

    from . import preorder
    led = _ledger(led)
    sign = sign or C.sign
    release_fn = release_fn or C.release
    p = project(pid)
    m = _milestone(p, key)
    a = next(x for x in m["attempts"] if x["id"] == attempt)
    if a["status"] != "checked":
        raise Refused("release needs the result and its independent check")
    if a.get("agent_key"):                             # an agent key's spend cap, before any money moves
        from . import agentkeys
        agentkeys.can_spend(a["agent_key"], _payout_units(p, m))
    review = _dir("evidence") / f"{pid}-{key}-{a['id']}-review.json"
    rv = {"project": pid, "milestone": key, "attempt": a["id"], "result": a["result"], "check": a["check"],
          "rule": "result + independent check, two people, two sites"}
    review.write_text(json.dumps(rv, sort_keys=True, indent=1), encoding="utf-8")
    refs = None
    paid = []
    for oid in list(m["fundings"]):
        o = _safe_order(oid)
        if not o or o["status"] != "locked":
            continue
        if led.account(Pubkey.from_string(o["order"])) is None:
            o["status"] = "closed"
            _save("orders", oid, o)
            continue
        doc = o["doc"]
        doc["payee"] = split_payee(a["wallet"], o.get("referral"))
        if (doc.get("panel") or {}).get("m") == 1:
            paid.append(_frost_start(pid, key, a, o, rv, led, base))
            continue
        if refs is None:
            refs = preorder.referees()
        recs = [sign(doc, "stage1", r, led, passed=True, review=review) for r in refs[:2]]
        vled = _V1Ledger(led)
        got = release_fn(doc, "stage1", recs, preorder.relayer(), vled)
        if vled.v1_sent:
            o["v1_transactions"] = vled.v1_sent
        o["status"] = got["status"] if got["status"] in ("released", "refunded") else "locked"
        o["doc"] = doc
        o["paid_to"] = {"maker": a["wallet"], "referrer": (o.get("referral") or {}).get("wallet"),
                        "split": doc["payee"].get("split")}
        for i, s in enumerate(got["sent"], 1):
            o["signatures"][f"referee_{i}_pass"] = s["signature"]
        _save("orders", oid, o)
        paid.append({"order": oid, "status": o["status"], "signatures": [s["signature"] for s in got["sent"]]})
    if any(x["status"] == "signing" for x in paid):
        with _lock:
            p = project(pid)
            m = _milestone(p, key)
            m["history"].append({"at": _now(), "what": f"attempt {attempt} verified: the FROST referee group is signing", "orders": paid})
            _save("projects", pid, p)
        from . import referee as _referee
        threading.Thread(target=_referee.wake_host2, daemon=True).start()   # host 2 starts now, not at its next timer
        return {"released": paid, "amc_collected": [], "milestone": "signing",
                "review_sha256": hashlib.sha256(review.read_bytes()).hexdigest()}
    return _settle(pid, key, attempt, paid, led, review)


def _frost_start(pid: str, key: str, a: dict, o: dict, rv: dict, led, base: str | None) -> dict:
    """Publish the attempt's review (with every funded order's claim id) and open a FROST signing session for one order."""
    from . import referee, tasks
    open_ = o.get("referee_session") or {}
    if o.get("release_attempt") == a["id"] and open_.get("id") and not open_.get("signature"):
        try:
            st = referee.coordinator().get(open_["id"]).get("state")
        except Exception:  # noqa: BLE001 - an unknown or expired session: open a new one
            st = None
        if st in ("round1", "round2") and referee.host1_alive(open_["id"]):   # already signing: no second session
            return {"order": o["order"], "status": "signing", "session": open_["id"], "evidence": open_.get("evidence")}
    if not referee.enabled():
        raise Refused("this milestone's referee group (FROST) is not configured on this server")
    eid = _evidence_id(pid, key, a["id"])
    f = _dir("evidence") / f"{eid}.public.json"
    if not f.exists():
        m = _milestone(project(pid), key)
        page = {"kind": "knos-project-milestone-review", "claims": _claim_ids(project(pid), m), **rv}
        f.write_text(json.dumps(page, sort_keys=True, indent=1), encoding="utf-8")
    url = f"{tasks.public_base(base)}/api/project/evidence?id={eid}"
    sig = referee.start({"order": o["order"], "doc": o["doc"]}, url, led, kind="project")
    o["referee_session"] = {"id": sig["session"], "github": sig["github"], "evidence": url}
    o["release_attempt"] = a["id"]
    _save("orders", o["order"], o)
    return {"order": o["order"], "status": "signing", "session": sig["session"], "evidence": url}


def frost_released(s: dict) -> dict:
    """The second FROST share of a project order's session arrived: send the group signature as the order's verdict
    (to the maker and the referrer's share, as the session's commitment says); settle the milestone when it is the last."""
    from knos.ideas import commit as C
    from knos.threshold import check

    from . import preorder
    o = _load("orders", s["meta"]["order"])
    doc, led = o["doc"], _ledger(None)
    oo = C._order(doc, "stage1", led)[1]
    v = check.verdict_record(doc, "stage1", {**s["meta"]["evidence"]}, bytes.fromhex(s["digest"]), s["signature"], s["group_key"], oo.stamp)
    vled = _V1Ledger(led)
    sent_at = time.time()
    got = C.release(doc, "stage1", [v], preorder.relayer(), vled)
    if vled.v1_sent:
        o["v1_transactions"] = vled.v1_sent
    o["status"] = got["status"] if got["status"] in ("released", "refunded") else "locked"
    pid, key, attempt = o["project"], o["milestone"], o.get("release_attempt")
    m = _milestone(project(pid), key)
    att = next((x for x in m["attempts"] if x["id"] == attempt), {})
    o["paid_to"] = {"maker": att.get("wallet"), "referrer": (o.get("referral") or {}).get("wallet"), "split": doc["payee"].get("split")}
    o["signatures"]["referee_group_pass"] = (got["sent"] or [{}])[0].get("signature")
    _finality_async(o["order"], o["signatures"]["referee_group_pass"], sent_at, led.url)
    o["referee_session"] = {**(o.get("referee_session") or {}), "signers": s["signers"], "signature": s["signature"]}
    _save("orders", o["order"], o)
    rest = [x for x in (_safe_order(i) for i in m["fundings"]) if x and x["status"] == "locked" and x.get("release_attempt") == attempt]
    out = {"status": o["status"], "signatures": [x["signature"] for x in got["sent"]]}
    if not rest and attempt:
        paid = [{"order": x["order"], "status": x["status"], "signatures": [x["signatures"].get("referee_group_pass")]}
                for x in (_safe_order(i) for i in m["fundings"]) if x and x.get("release_attempt") == attempt]
        out["milestone"] = _settle(pid, key, attempt, paid, led, None)["milestone"]
    return out


def _settle(pid: str, key: str, attempt: str, paid: list[dict], led, review) -> dict:
    """Every order of the verified attempt is decided: collect AMC allowances, close the other attempts, record it."""
    p = project(pid)
    a = next(x for x in _milestone(p, key)["attempts"] if x["id"] == attempt)
    collected = collect_amc(pid, key, a["wallet"], led=led)
    with _lock:
        p = project(pid)
        m = _milestone(p, key)
        aa = next(x for x in m["attempts"] if x["id"] == attempt)
        aa["status"] = "paid" if any(x["status"] == "released" for x in paid) or collected else "checked"
        for other in m["attempts"]:
            if other is not aa and other["status"] in ("working", "result posted"):
                other["status"] = "closed: another attempt was verified first"
        if aa["status"] == "paid":
            m["status"] = "released"
        m["history"].append({"at": _now(), "what": f"released to attempt {attempt}", "orders": paid, "amc": collected})
        _save("projects", pid, p)
    if aa.get("agent_key") and aa["status"] == "paid":
        from . import agentkeys
        agentkeys.spent(aa["agent_key"], _paid_units(pid, key, paid, collected))
    j = _journal("payout", {"project": pid, "milestone": key, "attempt": attempt, "orders": paid, "amc": collected,
                            "evidence_sha256": [a["result"]["sha256"], a["check"]["sha256"]]}, tenant_of(p))
    att = _attest(p, key, aa, paid, led) if m["status"] == "released" else []
    archive(pid)
    return {"released": paid, "amc_collected": collected, "milestone": m["status"], "attestations": att, "sibyl": j.get("sibyl"),
            "review_sha256": hashlib.sha256(review.read_bytes()).hexdigest() if review is not None else None}


def _attest(p: dict, key: str, a: dict, paid: list[dict], led=None) -> list[dict]:
    """The verified milestone's track record: a Solana Attestation Service attestation to the maker's wallet and to
    the referee group's key. A failed attestation never undoes a release; it is logged and left out."""
    from . import preorder, track
    try:
        refs = [k for k in preorder.panel()[1]]
    except Exception:  # noqa: BLE001 - a server without a panel attests the maker only
        refs = []
    sig = next((s for x in paid for s in (x.get("signatures") or []) if s), "")
    try:
        rows = track.attest(p["id"], key, a["id"], [("maker", a["wallet"])] + [("referee", k) for k in refs],
                            (p.get("frozen") or {}).get("criteria_hash") or "", sig, led=led)
    except Exception as why:  # noqa: BLE001
        print(f"knos projects: attestation of {p['id']}/{key} failed: {type(why).__name__}: {str(why)[:200]}", flush=True)
        return []
    with _lock:
        q = project(p["id"])
        x = next(x for x in _milestone(q, key)["attempts"] if x["id"] == a["id"])
        x["attestations"] = [{k: r[k] for k in ("role", "wallet", "attestation", "signature")} for r in rows]
        _save("projects", q["id"], q)
    x["onchain"] = _onchain(p, key, a, rows, sig, led)
    with _lock:
        q = project(p["id"])
        next(y for y in _milestone(q, key)["attempts"] if y["id"] == a["id"])["onchain"] = x["onchain"]
        _save("projects", q["id"], q)
    return rows


def _onchain(p: dict, key: str, a: dict, rows: list[dict], release_sig: str, led=None) -> dict:
    """Beside the attestations: the maker's Token-2022 badge (non-transferable, in the project's group), a leaf in the
    compressed track-record log, a release memo naming the brief and criteria hashes, and the rent the release gave
    back. Each step is independent; one that fails is said, never retried in a loop and never undoes the release."""
    from . import chainx
    out: dict = {}
    m = _milestone(p, key)
    crit = (p.get("frozen") or {}).get("criteria_hash") or ""
    brief = hashlib.sha256(json.dumps(_brief(p), sort_keys=True).encode()).hexdigest()
    steps = {"badge": lambda: chainx.badge(p["id"], p["title"], key, m["name"], a["wallet"], f"https://knos.onrender.com/app/#projects={p['id']}", led=led),
             "log": lambda: chainx.log_leaf(f"{p['id']}|{key}|{a['id']}|{','.join(r['attestation'] for r in rows)}", led=led),
             "memo": lambda: {"signature": chainx.memo(f"knos release {release_sig} brief sha256:{brief} criteria sha256:{crit}", led=led)},
             "rent": lambda: chainx.rent_returned(release_sig) if release_sig else None}
    for name, run in steps.items():
        try:
            out[name] = run()
        except Exception as why:  # noqa: BLE001
            out[name] = {"error": f"{type(why).__name__}: {str(why)[:160]}"}
    return out


# ---- the sweeper: missed deadlines refund and reopen ---- ------------------------------------------------------------
def sweep(led=None, refund_fn=None) -> dict:
    """Every locked order past its on-chain deadline is refunded (knos_pay RefundOrder) and its milestone reopened to
    other makers: the makers whose attempts missed it are excluded from it. Runs in the server every SWEEP_S."""
    from solders.pubkey import Pubkey

    from knos.ideas import commit as C
    from knos.settle.v2 import pay

    from . import preorder
    led = _ledger(led)
    refund_fn = refund_fn or C.refund
    done = []
    now = led.now()
    for o in _all("orders"):
        if o.get("status") != "locked":
            continue
        data = led.account(Pubkey.from_string(o["order"]))
        if data is None:
            continue
        od = pay.read_order(data)
        if od is None or now <= od.pay_until:
            continue
        try:
            got = refund_fn(o["doc"], "stage1", [], preorder.relayer(), led)
        except Exception as why:  # noqa: BLE001 - one stuck order never stops the sweep
            done.append({"order": o["order"], "error": f"{type(why).__name__}: {str(why)[:160]}"})
            continue
        o["status"] = got["status"]
        if got["sent"]:
            o["signatures"]["refund"] = got["sent"][0]["signature"]
        _save("orders", o["order"], o)
        reopened = reopen(o["project"], o["milestone"], o["order"])
        done.append({"order": o["order"], "status": o["status"], "signature": o["signatures"].get("refund"), "reopened": reopened})
        if o["status"] == "refunded":
            _receipt_async("refund", o["order"])
        j = _journal("refund", {"project": o["project"], "milestone": o["milestone"], "order": o["order"],
                                "signature": o["signatures"].get("refund"), "why": "deadline passed; milestone reopened"})
        done[-1]["sibyl"] = j.get("sibyl")
    return {"swept": done, "at": _now()}


def reopen(pid: str, key: str, order: str) -> dict:
    with _lock:
        p = project(pid)
        m = _milestone(p, key)
        if m["status"] == "released":
            return {"reopened": False, "why": "released"}
        missed = [a for a in m["attempts"] if a["status"] in ("working", "result posted")]
        for a in missed:
            a["status"] = "missed the deadline"
            if a["maker_sub"] not in m["excluded"]:
                m["excluded"].append(a["maker_sub"])
        m["status"] = "reopened"
        m["history"].append({"at": _now(), "what": "deadline missed: refunded to the funder and reopened to other makers",
                             "order": order, "excluded": len(missed)})
        _save("projects", pid, p)
    return {"reopened": True, "excluded_makers": len(missed)}


_sweeper_started = False


def start_sweeper() -> None:
    global _sweeper_started
    if _sweeper_started or SWEEP_S <= 0:
        return
    _sweeper_started = True

    def loop():
        while True:
            time.sleep(SWEEP_S)
            try:
                from . import preorder
                if preorder.ready()[0] and _all("orders"):
                    due = release_due()
                    from . import wallets
                    wallets.retire_tables(_ledger())          # retired lookup tables: deactivate, then close (rent back)
                    if due:
                        print(f"knos projects sweeper: {len(due)} verdict(s) released after their challenge window", flush=True)
                    got = sweep()
                    if got["swept"]:
                        print(f"knos projects sweeper: {len(got['swept'])} order(s) refunded and reopened", flush=True)
            except Exception as why:  # noqa: BLE001
                print(f"knos projects sweeper: {type(why).__name__}: {str(why)[:200]}", flush=True)
    threading.Thread(target=loop, daemon=True, name="knos-valley-sweeper").start()


# ---- AMC commitments: fund only when the milestone verifies ---- ----------------------------------------------------
def _approve_ix(source, delegate, owner, amount: int):
    from solders.instruction import AccountMeta, Instruction
    return Instruction(_token(), bytes([4]) + struct.pack("<Q", amount),
                       [AccountMeta(source, False, True), AccountMeta(delegate, False, False), AccountMeta(owner, True, False)])


def _transfer_ix(source, dest, authority, amount: int):
    from solders.instruction import AccountMeta, Instruction
    return Instruction(_token(), bytes([3]) + struct.pack("<Q", amount),
                       [AccountMeta(source, False, True), AccountMeta(dest, False, True), AccountMeta(authority, True, False)])


def amc_tx(pid: str, key: str, units: int, account: str, led=None) -> dict:
    """An advance-market-commitment: the buyer's wallet approves the relayer to spend `units` test units from its token
    account. Nothing moves now; when the milestone verifies, the relayer pays the maker from it."""
    from solders.hash import Hash
    from solders.message import Message
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction

    from knos import chain
    from knos.settle.v2 import pay

    from . import preorder
    if isinstance(units, bool) or not isinstance(units, int) or not 1 <= units <= 1000:
        raise Refused("units: 1 to 1,000 test units")
    try:
        wallet = Pubkey.from_string(str(account))
    except ValueError:
        raise Refused("account: the buyer's Solana wallet") from None
    p = project(pid)
    m = _milestone(p, key)
    gate(p)
    if m["status"] == "released":
        raise Refused("this milestone is already released")
    preorder._need()
    led = _ledger(led)
    authority, relayer = escrow.demo_key(), preorder.relayer()
    mint = escrow.mint(led, create=False)
    tok = pay.ata(wallet, mint)
    ixs = [pay.create_ata_ix(wallet, wallet, mint)] if led.account(tok) is None else []
    ixs.append(escrow._mint_to_ix(mint, tok, authority.pubkey(), units))
    ixs.append(_approve_ix(tok, relayer.pubkey(), wallet, units * escrow.UNIT))
    bh = Hash.from_string(chain.call(led.url, "getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])
    tx = Transaction.new_unsigned(Message.new_with_blockhash(ixs, wallet, bh))
    tx.partial_sign([authority], bh)
    aid = _id("amc", account, pid, key)
    _save("amc", aid, {"id": aid, "project": pid, "milestone": key, "buyer": str(wallet), "token": str(tok), "units": units,
                       "delegate": str(relayer.pubkey()), "status": "pending", "made": _now(), "signatures": {}})
    return {"transaction": base64.b64encode(bytes(tx)).decode(), "amc": aid,
            "message": f"Commits {units} test units to '{m['name']}': an allowance from your wallet, collected only when the milestone "
                       "verifies. You can revoke it until then (an AMC is a promise, weaker than held money)."}


def amc_confirm(aid: str, signature: str | None = None, led=None) -> dict:
    from solders.pubkey import Pubkey
    a = _load("amc", aid)
    if a["status"] == "pending":
        led = _ledger(led)
        acc = led.account(Pubkey.from_string(a["token"]))
        if acc is None or len(acc) < 121 or acc[72:76] != b"\x01\x00\x00\x00" or str(Pubkey.from_bytes(acc[76:108])) != a["delegate"]:
            raise Refused("the allowance is not on devnet yet: send the signed transaction first")
        a["status"] = "approved"
        if signature and re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{64,90}", signature):
            a["signatures"]["approve"] = signature
        from . import outside
        outside.note("commitment", str(a.get("token") or a.get("id") or ""), "advance market commitment")
        _save("amc", aid, a)
        _journal("funding", {"project": a["project"], "milestone": a["milestone"], "amc": aid, "kind": "amc", "amount_units": a["units"],
                             "signature": a["signatures"].get("approve")})
    return {k: v for k, v in a.items()}


def amc_of(pid: str, key: str) -> list[dict]:
    return [a for a in _all("amc") if a.get("project") == pid and a.get("milestone") == key]


def collect_amc(pid: str, key: str, maker_wallet: str, led=None) -> list[dict]:
    """The milestone verified: the relayer, as delegate, pays the maker from each approved allowance (what is still
    delegated; a revoked or spent allowance pays what is left, and says so)."""
    from solders.pubkey import Pubkey

    from knos.settle.v2 import pay

    from . import preorder
    out = []
    pend = [a for a in amc_of(pid, key) if a["status"] == "approved"]
    if not pend:
        return out
    led = _ledger(led)
    relayer, mint = preorder.relayer(), escrow.mint(led, create=False)
    dest = pay.ata(Pubkey.from_string(maker_wallet), mint)
    if led.account(dest) is None:
        led.send([pay.create_ata_ix(relayer.pubkey(), Pubkey.from_string(maker_wallet), mint)], relayer)
    for a in pend:
        acc = led.account(Pubkey.from_string(a["token"]))
        left = struct.unpack("<Q", acc[121:129])[0] if acc and len(acc) >= 129 and acc[72:76] == b"\x01\x00\x00\x00" else 0
        bal = struct.unpack("<Q", acc[64:72])[0] if acc else 0
        amt = min(left, bal, a["units"] * escrow.UNIT)
        if amt <= 0:
            a["status"] = "revoked or spent before the milestone verified"
        else:
            sig = led.send([_transfer_ix(Pubkey.from_string(a["token"]), dest, relayer.pubkey(), amt)], relayer)
            a["status"], a["signatures"]["collect"], a["collected_units"] = "collected", sig, amt / escrow.UNIT
        _save("amc", a["id"], a)
        out.append({"amc": a["id"], "status": a["status"], "signature": a["signatures"].get("collect")})
    return out


# Knos builds Knos: a project bound to a GitHub repository, whose machine-verified milestones release when their check
# passes in CI. The operator opens it, funds each milestone with the app's devnet test wallet (test units it mints itself)
# and claims each for the maker's wallet; anyone may then ask for a release at a commit, and only GitHub's own record
# of that commit decides it.
OPERATOR = {"sub": "knos-operator", "label": "Knos (operator)"}
CI_MAKER = {"sub": "knos-ci-maker", "label": "Knos builds Knos"}
CI_APP = "github-actions"
_REPO = re.compile(r"[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100}")


def operator_open(brief: dict, title: str, repo: str) -> dict:
    """A project from a Ready brief, bound to `repo` (owner/name on GitHub)."""
    if not isinstance(repo, str) or not _REPO.fullmatch(repo):
        raise Refused("repo: owner/name on GitHub")
    if not _ready().check(brief)["ready"]:
        raise Refused("the brief is not Ready: POST /api/ready says what is missing")
    out = create_project(OPERATOR, "custom", title, brief=brief)
    with _lock:
        p = project(out["id"])
        p["repo"] = repo
        p["release_rule"] = f"each milestone releases when its check passes on {repo}'s default branch (GitHub Actions)"
        _save("projects", p["id"], p)
    return public_project(project(out["id"]))


def operator_fund(pid: str, key: str, units: int = 5, led=None, wait_s: float = 60) -> dict:
    """Fund one milestone from the app's devnet test wallet: it is the funder and the test mint's authority, so the
    server signs the whole funding, sends it and confirms the lock (refunded to that wallet after the deadline)."""
    from knos import chain
    led = _ledger(led)
    got = fund_tx(pid, key, units, str(escrow.demo_key().pubkey()), led=led)
    sig = chain.call(led.url, "sendTransaction", [got["transaction"], {"encoding": "base64", "preflightCommitment": "confirmed"}])
    end = time.monotonic() + wait_s
    while True:
        try:
            return {**confirm(got["order"], sig, led=led), "signature": sig}
        except Refused:
            if time.monotonic() >= end:
                raise
            time.sleep(2)


def operator_claim(pid: str, key: str, wallet: str) -> dict:
    """The CI attempt on one milestone, paid at `wallet` when its check passes."""
    a = claim(pid, key, CI_MAKER, wallet)
    with _lock:
        p = project(pid)
        _milestone(p, key)["ci_attempt"] = a["id"]
        _save("projects", pid, p)
    return a


_gh: dict[str, tuple[float, object]] = {}
GH_CACHE_S = 300.0


def _cached(get):
    """GitHub's answers kept for GH_CACHE_S: one CI run asks for ten milestones at one commit (and the app's address
    shares GitHub's 60 unauthenticated requests an hour)."""
    def got(path: str):
        hit = _gh.get(path)
        if hit and time.monotonic() - hit[0] < GH_CACHE_S:
            return hit[1]
        value = get(path)
        _gh[path] = (time.monotonic(), value)
        return value
    return got


def _on_branch(repo: str, sha: str, get) -> str | None:
    """The default branch when `sha` is on it (GitHub's compare of the commit with the branch), else None."""
    branch = (get(f"repos/{repo}") or {}).get("default_branch") or "main"
    cmp = get(f"repos/{repo}/compare/{sha}...{branch}") or {}
    return branch if cmp.get("status") in ("ahead", "identical") else None


def ci_release(pid: str, key: str, sha: str, get=None, led=None, base: str | None = None) -> dict:
    """Release a milestone whose machine check passed in CI: `sha` is on the bound repository's default branch and a
    GitHub Actions check run there, named exactly the milestone's verifier check, completed with success. The check run
    is the result; this server's re-reading of GitHub's record, published with the order's claim ids, is the check the
    referee hosts fetch before they sign."""
    from urllib.parse import urlparse

    from knos import judge, terms

    from . import preorder, tasks
    get = get or _cached(judge.github)
    p = project(pid)
    m = _milestone(p, key)
    repo, v = p.get("repo"), m.get("verifier") or {}
    if not repo:
        raise Refused("this project is not bound to a GitHub repository")
    if v.get("kind") != "machine" or not v.get("check"):
        raise Refused("this milestone is not verified by a machine check")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise Refused("sha: the commit's full 40-character id")
    a = next((x for x in m["attempts"] if x["id"] == m.get("ci_attempt")), None)
    if a is None:
        raise Refused("no CI attempt is claimed on this milestone")
    if m["status"] == "released":
        return {"milestone": key, "status": "released", "ci": a.get("ci")}
    if a["status"] == "checked":                       # verified before and the release did not finish: send it again
        return release(pid, key, a["id"], led=led, base=base)
    if a["status"] != "working":
        raise Refused(f"the CI attempt is {a['status']}")
    try:
        branch = _on_branch(repo, sha, get)
        runs = terms.pages(f"repos/{repo}/commits/{sha}/check-runs", get, "check_runs")
    except OSError as why:
        raise escrow.EscrowUnavailable(f"GitHub could not be read now: {str(why)[:120]}") from None
    if runs is None:
        raise escrow.EscrowUnavailable("GitHub could not be read now: try again in a minute")
    if branch is None:
        raise preorder.NotVerified(f"{sha[:12]} is not on {repo}'s default branch")
    run = next((r for r in runs if r.get("name") == v["check"] and (r.get("app") or {}).get("slug") == CI_APP
                and r.get("status") == "completed" and r.get("conclusion") == "success"), None)
    if run is None:
        seen = [f"{r.get('conclusion') or r.get('status')}" for r in runs if r.get("name") == v["check"]]
        raise preorder.NotVerified(f"no successful {v['check']} check run at {sha[:12]} in {repo}" + (f" (seen: {', '.join(seen)})" if seen else ""))
    ids = _claim_ids(p, m)
    if not ids:
        raise Refused("this milestone has no locked funding yet: nothing to release")
    ci = {"repo": repo, "branch": branch, "sha": sha, "check": v["check"], "check_run": run.get("html_url"), "run_id": run.get("id"),
          "conclusion": run["conclusion"], "completed_at": run.get("completed_at")}
    eid = _evidence_id(pid, key, a["id"])
    page = {"kind": "knos-ci-verified-milestone", "project": pid, "milestone": key, "target": m.get("target"), "claims": ids, **ci}
    f = _dir("evidence") / f"{eid}.public.json"
    f.write_text(json.dumps(page, sort_keys=True, indent=1), encoding="utf-8")
    body, url = f.read_bytes(), f"{tasks.public_base(base)}/api/project/evidence?id={eid}"
    raw = json.dumps(run, sort_keys=True).encode()
    with _lock:
        p = project(pid)
        m = _milestone(p, key)
        a = next(x for x in m["attempts"] if x["id"] == a["id"])
        if a["status"] != "working":
            raise Refused(f"the CI attempt is {a['status']}")
        a["result"] = {"url": ci["check_run"], "host": "github.com", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                       "by": "GitHub Actions", "at": _now()}
        a["check"] = {"url": url, "host": (urlparse(url).hostname or "").lower(), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                      "by": "Knos, re-reading GitHub's record of the commit", "at": _now()}
        a["ci"], a["status"] = ci, "checked"
        m["history"].append({"at": _now(), "what": f"{v['check']} passed in CI at {sha[:12]}: releasing attempt {a['id']}", "check_run": ci["check_run"]})
        _save("projects", pid, p)
    _journal("experiment", {"project": pid, "milestone": key, "what": "CI-verified", "attempt": a["id"], **ci}, tenant_of(p))
    return {**release(pid, key, a["id"], led=led, base=base), "ci": ci}


# Paid with no human step: a milestone whose verifier is the sealed referee of an open knos.game round
# ("knos-referee:<round>"). The maker's code goes to the round as knos_task_submit's does; when the verdict meets the
# milestone's margin over the baseline, the verdict is the result, this server's published re-reading of it (with the
# orders' claim ids) is the check the referee hosts fetch, and the milestone releases, as ci_release does for CI.
REFEREE_CHECK = re.compile(r"knos-referee:([A-Za-z0-9_.-]{3,80})")
_MARGIN = re.compile(r"(\d+(?:\.\d+)?)\s*percentage points?", re.I)


def referee_round(m: dict) -> str | None:
    """The round a milestone's machine verifier names (knos-referee:<round>), else None."""
    v = m.get("verifier") or {}
    got = REFEREE_CHECK.fullmatch(str(v.get("check") or "")) if v.get("kind") == "machine" else None
    return got.group(1) if got else None


def min_margin(m: dict) -> float | None:
    """The lift over the baseline the verdict must reach, read from the target (so it is in the criteria hash):
    "0.5 percentage points" is 0.005 of accuracy."""
    got = _MARGIN.search(str(m.get("target") or ""))
    return float(got.group(1)) / 100 if got else None


def referee_release(pid: str, key: str, attempt: str, submission: str, user: dict, led=None, base: str | None = None) -> dict:
    """Submit the attempt's code to the milestone's round and release on a verdict that meets the target. The attempt
    plays as its own player in the round, so its shown score is this attempt's own, and it passes only when this
    submission moved that score to at least the baseline's shown score plus the margin (the Ladder rounds both down)."""
    from urllib.parse import urlparse

    from . import preorder, tasks
    p = project(pid)
    m = _milestone(p, key)
    rnd, margin = referee_round(m), min_margin(m)
    if rnd is None:
        raise Refused("this milestone is not judged by a referee round (verifier knos-referee:<round>)")
    if margin is None:
        raise Refused("this milestone's target names no margin over the baseline (percentage points)")
    a = next((x for x in m["attempts"] if x["id"] == attempt), None)
    if a is None:
        raise Refused("attempt: not on this milestone")
    if a["maker_sub"] != _user_key(user):
        raise Refused("only the maker of this attempt submits to its round")
    if m["status"] == "released":
        return {"milestone": key, "status": "released", "referee": a.get("referee")}
    if a["status"] == "checked":                       # verified before and the release did not finish: send it again
        return {**release(pid, key, a["id"], led=led, base=base), "referee": a.get("referee")}
    if a["status"] != "working":
        raise Refused(f"the attempt is {a['status']}")
    ids = _claim_ids(p, m)
    if not ids:
        raise Refused("this milestone has no locked funding yet: nothing to release")
    st = tasks.round_state()
    if st["id"] != rnd:
        raise Refused(f"this milestone is judged by round {rnd}, which is not the open round ({st['id']}): it cannot be verified now")
    kind = "agent" if user.get("kind") == "agent" else "human"
    name = re.sub(r"[^A-Za-z0-9 _.-]", "", str(user.get("label") or "")).strip()[:40] or "maker"    # the board's name rule
    got = tasks.submit(rnd, name, submission, f"{kind}: {user.get('label')}",
                       sub=f"{a['maker_sub']}|{pid}|{key}|{a['id']}", wallet=None, base=base)
    r = got["result"]
    shown, floor = r.get("shown"), st.get("baseline_shown")
    sign = -1 if st.get("direction") == "min" else 1
    lift = round(sign * (shown - floor), 10) if r.get("decision") == "scored" and isinstance(shown, (int, float)) and isinstance(floor, (int, float)) else None
    passed = lift is not None and bool(r.get("moved")) and lift >= margin - 1e-9
    verdict = {"round": rnd, "decision": r.get("decision"), "shown": shown, "baseline_shown": floor, "lift": lift, "min_margin": margin,
               "moved": r.get("moved"), "attempt_n": r.get("n"), "referee_sha256": r.get("sha256"), "submitted_sha256": got["submitted_sha256"],
               "rules": r.get("rules"), "reasons": r.get("reasons"), "eta": st.get("eta"), "at": _now(), "pass": passed}
    if not passed:
        with _lock:
            p = project(pid)
            aa = next(x for x in _milestone(p, key)["attempts"] if x["id"] == a["id"])
            aa.setdefault("referee_tries", []).append(verdict)
            _milestone(p, key)["history"].append({"at": _now(), "what": f"attempt {a['id']}: the referee's verdict did not meet the target",
                                                  "decision": r.get("decision"), "lift": lift})
            _save("projects", pid, p)
        raise preorder.NotVerified(f"round {rnd}: {r.get('decision')}, shown {shown} against the baseline's {floor} (lift {lift}); "
                                   f"the target needs a lift of {margin} moved by this submission" + (f"; {'; '.join(r.get('reasons') or [])}" if r.get("reasons") else ""))
    eid = _evidence_id(pid, key, a["id"])
    page = {"kind": "knos-referee-verified-milestone", "project": pid, "milestone": key, "target": m.get("target"), "claims": ids,
            "verdict": verdict, "rule": "the round's sealed referee scored this submission; its shown score is at least the baseline's plus the margin"}
    f = _dir("evidence") / f"{eid}.public.json"
    f.write_text(json.dumps(page, sort_keys=True, indent=1), encoding="utf-8")
    body, url = f.read_bytes(), f"{tasks.public_base(base)}/api/project/evidence?id={eid}"
    raw = json.dumps(verdict, sort_keys=True).encode()
    host = (urlparse(url).hostname or "").lower()
    with _lock:
        p = project(pid)
        m = _milestone(p, key)
        a = next(x for x in m["attempts"] if x["id"] == a["id"])
        if a["status"] != "working":
            raise Refused(f"the attempt is {a['status']}")
        a["result"] = {"url": url + "#verdict", "host": host, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                       "by": f"the sealed referee of round {rnd}", "at": _now()}
        a["check"] = {"url": url, "host": host, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                      "by": "Knos, re-reading the referee's verdict against the milestone's target", "at": _now()}
        a["referee"], a["status"] = verdict, "checked"
        m["history"].append({"at": _now(), "what": f"the referee of round {rnd} verified attempt {a['id']} (lift {lift}): releasing"})
        _save("projects", pid, p)
    _journal("experiment", {"project": pid, "milestone": key, "what": "referee-verified", "attempt": a["id"], "round": rnd, "lift": lift,
                            "submitted_sha256": verdict["submitted_sha256"]}, tenant_of(p))
    return {**release(pid, key, a["id"], led=led, base=base), "referee": verdict, "evidence": url}


def solve(pid: str, key: str, code: str, user: dict, wallet: str = "", led=None, base: str | None = None) -> dict:
    """knos_milestone_submit: claim the referee-judged milestone when the caller has no attempt on it yet (an agent key:
    paid at its payout wallet, one claim of its cap), then submit to its round and release on a passing verdict."""
    m = _milestone(project(pid), key)
    if referee_round(m) is None:
        raise Refused("this milestone is not judged by a referee round: claim it and post a result instead")
    who = _user_key(user)
    a = next((x for x in m["attempts"] if x["maker_sub"] == who and x["status"] in ("working", "checked")), None)
    claimed = claim(pid, key, user, wallet) if a is None else None
    aid = (claimed or a or {})["id"]
    return {"attempt": aid, "claimed": claimed is not None, **referee_release(pid, key, aid, code, user, led=led, base=base)}


# The three open, computer-checkable briefs an AI scientist can win (knos_wanted.solver_briefs): the operator opens
# them as projects through the custom-brief path and funds them from the app's devnet test wallet, as the champion
# project is.
def solver_briefs(round_id: str | None = None) -> list[dict]:
    """The briefs as data; `round_id` fills the referee round of the one judged by the sealed referee."""
    import copy

    from .solver_briefs import BRIEFS
    rows = copy.deepcopy(BRIEFS["briefs"])
    for b in rows:
        for m in b["brief"]["milestones"]:
            if round_id and "{round}" in m["verifier"].get("check", ""):
                m["verifier"]["check"] = m["verifier"]["check"].replace("{round}", round_id)
    return rows


def open_solver_briefs(which: list[str] | None = None, round_id: str | None = None) -> list[dict]:
    """The operator opens the solver briefs as projects (each Ready first). The referee one is bound to the open round."""
    rows = [b for b in solver_briefs() if not which or b["id"] in which]
    if any("{round}" in m["verifier"].get("check", "") for b in rows for m in b["brief"]["milestones"]) and not round_id:
        from . import tasks
        round_id = tasks.round_state()["id"]
    out = []
    for b in solver_briefs(round_id):
        if which and b["id"] not in which:
            continue
        if not _ready().check(b["brief"])["ready"]:
            raise Refused(f"solver brief {b['id']} is not Ready: POST /api/ready says what is missing")
        got = create_project(OPERATOR, "custom", b["title"], brief=b["brief"])
        with _lock:
            p = project(got["id"])
            p.update(solver_brief=b["id"], release_rule=b["release"], note=b["note"])
            _save("projects", p["id"], p)
        out.append(public_project(project(got["id"])))
    return out


def operator_fund_solver(pid: str, units: int = 5, led=None, wait_s: float = 60) -> dict:
    """Fund the referee-judged milestone of a solver project from the app's devnet test wallet (operator_fund)."""
    m = next((m for m in project(pid)["milestones"] if referee_round(m)), None)
    if m is None:
        raise Refused("this project has no referee-judged milestone")
    return operator_fund(pid, m["key"], units, led=led, wait_s=wait_s)
