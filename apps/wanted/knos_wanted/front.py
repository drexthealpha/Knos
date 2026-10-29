"""The front door's list: research products people can back now (GET /api/front), and the seeds that keep it full.

The app runs on a free instance whose disk is wiped when it restarts, so a stranger could find an empty app. At start
(serve, a background thread) this server crosses each SEED (a landmark paper and the product it enables) on live
Qloo exactly as a researcher's crossing does, and opens a PROJECT for each one that decides OPEN, so its milestones
can be funded before any maker claims them (the payee is bound when a maker claims). Nothing is invented: a seed whose
crossing does not decide OPEN is not listed, and every number on the list is read from this server's own files.

Every product is named by a SLUG that outlives a restart (the report's hash changes when Qloo's data does), so the
front door's links (#back=<slug>) keep working.
Each product carries ONE-TAP actions: back it (pre-order, or the first milestone's escrow while no maker has
claimed it), fund a milestone (the project), contribute (the open work).
"""
from __future__ import annotations

import os
import re
import threading
import time

SEEDS = [
    {"slug": "sweat-glucose-watch", "ref": "10.1038/nature16521", "product": "a fitness watch with a sweat glucose sensor",
     "place": None, "template": "hardware_prototype", "paper": "Nature, 2016", "tech": "biotech"},
    {"slug": "air-water-bottle", "ref": "10.1126/science.aam8743", "product": "a water bottle that harvests drinking water from desert air",
     "place": "Phoenix", "template": "hardware_prototype", "paper": "Science, 2017", "tech": "materials"},
    {"slug": "ai-recipe-planner", "ref": None, "idea": "An AI recipe planner for families",
     "product": None, "place": None, "template": "internal_tool", "paper": None, "tech": "ai"},
    {"slug": "glow-hydration-bottle", "ref": None, "idea": "A smart water bottle that glows to remind you to drink",
     "product": None, "place": "Lagos", "template": "hardware_prototype", "paper": None, "tech": None},
]
# the seven technologies of the fields page (static/fields.json), as a product names them: shown on its card
TECH = {"ai": "AI", "web3": "Web3", "quantum": "Quantum", "energy": "Energy", "biotech": "Biotech", "materials": "Materials", "pqc": "PQC"}
TECH_WORDS = {"ai": ("ai", "machine learning", "model", "llm"), "web3": ("crypto", "blockchain", "nft", "dao", "web3", "on chain", "token"),
              "quantum": ("quantum",), "energy": ("battery", "solar", "grid", "reactor", "energy", "power"),
              "biotech": ("glucose", "protein", "gene", "crispr", "probiotic", "fermented", "biotech", "drug", "enzyme", "sweat"),
              "materials": ("material", "graphene", "concrete", "coating", "carbon fiber", "metamaterial", "perovskite", "harvests"),
              "pqc": ("post-quantum", "post quantum", "lattice")}


def tech_of(text: str, slug: str | None = None) -> str | None:
    """A product's technology: its seed's, else the first of the seven whose words its title uses (pqc before quantum)."""
    seed = next((s for s in SEEDS if s["slug"] == slug), None)
    if seed and "tech" in seed:
        return seed["tech"]
    t = f" {(text or '').lower()} "
    for k in ("pqc", "quantum", "web3", "ai", "energy", "biotech", "materials"):
        if any(re.search(r"\b" + re.escape(w) + r"\b", t) for w in TECH_WORDS[k]):
            return k
    return None


SEED_OWNER = {"sub": "knos:seed", "kind": "seed", "label": "Knos (seeded at start)"}
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS", "Cache-Control": "public, max-age=30"}
_lock = threading.RLock()
_seeded: dict[str, dict] = {}          # slug -> {"job": id, "report": hash, "project": id, "state": ..., "at": t}
_started = False


def seeds_on() -> bool:
    return os.environ.get("KNOS_WANTED_SEED", "1") != "0"


def seeded() -> dict[str, dict]:
    with _lock:
        return {k: dict(v) for k, v in _seeded.items()}


def _project_for(report_hash: str, title: str, template: str) -> str | None:
    from . import valley
    for p in valley._all("projects"):
        if p.get("report") == report_hash:
            return p["id"]
    try:
        return valley.create_project(SEED_OWNER, template, title[:120], report=report_hash)["id"]
    except valley.Refused:
        return None


def seed_one(state, s: dict) -> dict:
    """Cross one seed on this server's Qloo (synchronously) and open its project when it decides OPEN."""
    from . import agent
    with _lock:
        _seeded[s["slug"]] = {"state": "crossing", "at": time.time()}
    job = agent.start(state, ref=s.get("ref"), idea=s.get("idea"), place=s.get("place"), product=s.get("product"), wait=True)
    job["seed"] = s["slug"]
    rep = state.report(job.get("report")) if job.get("report") else None
    d = (rep or {}).get("decision") or {}
    out = {"job": job["id"], "report": job.get("report"), "verdict": d.get("verdict"), "at": time.time(),
           "state": "open" if d.get("verdict") == "OPEN" else "not open" if rep else f"error: {job.get('error') or 'no report'}"}
    if d.get("verdict") == "OPEN":
        out["project"] = _project_for(rep["hash"], rep.get("idea") or s.get("product") or s.get("idea") or s["slug"], s["template"])
    with _lock:
        _seeded[s["slug"]] = out
    return out


def ensure_seeded(state, tries: int = 3, wait_s: float = 120.0) -> None:
    """Every seed crossed once per start (a failed one is tried again, at most `tries` times)."""
    for s in SEEDS:
        for n in range(tries):
            try:
                got = seed_one(state, s)
                print(f"knos front: seed {s['slug']}: {got['state']}", flush=True)
                if not got["state"].startswith("error"):
                    break
            except Exception as why:  # noqa: BLE001 - a seed that fails never stops the server
                with _lock:
                    _seeded[s["slug"]] = {"state": f"error: {type(why).__name__}", "at": time.time()}
                print(f"knos front: seed {s['slug']} failed: {type(why).__name__}: {str(why)[:200]}", flush=True)
            time.sleep(wait_s * (n + 1))


def start(state) -> None:
    global _started
    if _started or not seeds_on():
        return
    _started = True
    def seed():
        try:
            ensure_seeded(state)
        finally:
            idle = getattr(state.q, "idle", None)        # the seeds' crossings started `qloo mcp`: stopped until next asked
            if callable(idle) and os.environ.get("KNOS_WANTED_MOCK") != "1":
                idle()
    threading.Thread(target=seed, daemon=True, name="knos-front-seeds").start()


# ---- the list ------------------------------------------------------------------------------------------------------
def _slug_of(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:48] or "product"


def _paper(rep: dict, seed: dict | None) -> str | None:
    r = rep.get("research") or {}
    if r.get("title"):
        venue = r.get("venue") or ""
        return f"{venue}, {r.get('year')}".strip(", ") if (venue or r.get("year")) else None
    return (seed or {}).get("paper")


def product(state, rep: dict, slug: str, project_id: str | None) -> dict:
    """One product as the front door shows it: what it is, the research behind it, how far its backing is."""
    from . import preorder, valley, wallets
    d = rep.get("decision") or {}
    plan = d.get("plan") or {}
    res = preorder.reserve_status(rep)
    maker = wallets.maker_of(rep["hash"]) is not None
    escrow_units, open_ms, first = 0, 0, None
    if project_id:
        try:
            p = valley.public_project(valley.project(project_id))
            if not p["ready"]["ready"]:
                raise valley.Refused("its generated milestones are Not ready to fund")
            for m in p["milestones"]:
                escrow_units += m["locked_units"]
                if m["status"] != "released" and m["kind"] == "build":
                    open_ms += 1
                    first = first or m["key"]
        except valley.Refused:
            project_id = None
    r = rep.get("research") or {}
    title = str(rep.get("idea") or slug).strip()
    tech = tech_of(title, slug)
    return {"slug": slug, "report": rep["hash"], "title": title[:1].upper() + title[1:], "paper": _paper(rep, None),
            "tech": tech, "tech_name": TECH.get(tech or ""),
            "paper_title": r.get("title"), "where": (plan.get("where") or [])[:3], "unit_price": plan.get("unit_price"),
            "target_units": d.get("target_units"), "reserve_units": d.get("reserve_units"),
            "backed_units": res["pre_ordered_units"], "escrow_units": escrow_units, "held_units": escrow_units, "maker": maker, "project": project_id,
            "first_milestone": first, "open_milestones": open_ms,
            "actions": {"back": f"#back={slug}", "fund": f"#fund={slug}", "contribute": f"#contribute={slug}"}}


def board(state, n: int = 6) -> dict:
    """The products open for backing now: the seeds first (in their order), then every other OPEN crossing, newest first."""
    from . import agent, valley
    if not seeded():
        start(state)                      # the seeds cross when a reader first asks for the board, never at boot
    out, seen = [], set()
    by_report = {p.get("report"): p["id"] for p in valley._all("projects") if p.get("report")}
    def listed(rep) -> bool:             # OPEN on LIVE Qloo evidence: the only decisions pre-orders open on
        return bool(rep) and (rep.get("decision") or {}).get("verdict") == "OPEN" and str(rep.get("label") or "").startswith("LIVE")
    for s in SEEDS:
        got = seeded().get(s["slug"]) or {}
        rep = state.report(got.get("report")) if got.get("report") else None
        if listed(rep):
            out.append(product(state, rep, s["slug"], got.get("project") or by_report.get(rep["hash"])))
            seen.add(rep["hash"])
    for c in agent.crossings(state, 60):
        if len(out) >= n:
            break
        if c.get("verdict") != "OPEN" or not c.get("report") or c["report"] in seen:
            continue
        rep = state.report(c["report"])
        if listed(rep):
            seen.add(c["report"])
            out.append(product(state, rep, c["report"][:16], by_report.get(c["report"])))
    waking = [s["slug"] for s in SEEDS if (seeded().get(s["slug"]) or {}).get("state") == "crossing"]
    return {"products": out[:n], "crossing_now": waking, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "this server's own files (live Qloo decisions, money held on devnet)", "money": "devnet test units: no real money",
            "app": "https://knos.onrender.com"}


def resolve(state, slug: str) -> dict | None:
    """A slug (or a report hash, or its first 16 hex) -> the product, or the seed still being crossed."""
    slug = str(slug or "")[:64]
    for p in board(state, 50)["products"]:
        if slug in (p["slug"], p["report"], p["report"][:16]):
            return p
    s = next((s for s in SEEDS if s["slug"] == slug), None)
    if s:
        st = (seeded().get(slug) or {}).get("state") or ("waiting to cross" if seeds_on() else "seeds are off on this server")
        return {"slug": slug, "pending": True, "state": st, "title": s.get("product") or s.get("idea")}
    return None
