"""Companies mode: a company states its need in one sentence and gets, in one call, a Ready brief, a
private demand check and an opened milestone. Anyone anywhere answers an open milestone; its test money is released only when the check
Knos chose for the field passes, after the 72-hour challenge window; each verified result becomes an attestation on the solver
(knos_wanted.track), so the next company sees proven solvers first.

    need(sentence, user, open_, state)   POST /api/company/need (signed in: company SSO, or any Knos session)
    solvers()                            GET /api/solvers: wallets by verified milestones, each read back from devnet

The proof per field (Knos chooses, the company does not fill a form):
  software       signed CI: the named test passes in the repository's GitHub Actions (a machine check)
  data / models  a reproducible run: the pipeline re-run from a fresh checkout gives the reported metric
  wet lab        the lab protocol and a QC attestation (SAS) by the lab that ran it
  hardware       a signed test report from an independent test lab
"""
from __future__ import annotations

import re
import time

from knos import ready as kr

FIELDS = {
    "software": {"words": ("app", "api", "software", "code", "website", "web", "backend", "frontend", "service", "integration", "bug",
                           "feature", "sdk", "plugin", "dashboard", "mobile", "ios", "android", "deploy"),
                 "proof": "Signed CI: the named test passes in the repository's GitHub Actions run"},
    "data": {"words": ("model", "data", "dataset", "ml", "machine learning", "forecast", "prediction", "classifier", "llm", "ai",
                       "benchmark", "training", "pipeline", "analytics"),
             "proof": "A reproducible run: re-run from a fresh checkout gives the reported metric"},
    "wetlab": {"words": ("assay", "protein", "enzyme", "cell", "cells", "strain", "drug", "compound", "antibody", "lab", "sample",
                         "samples", "biology", "chemistry", "catalyst", "fermentation", "crispr", "molecule", "formulation"),
               "proof": "The lab protocol and a QC attestation (SAS) by the lab that ran it"},
    "hardware": {"words": ("device", "sensor", "battery", "motor", "prototype", "hardware", "circuit", "pcb", "robot", "drone",
                           "material", "coating", "panel", "machine", "engine", "cooling", "reactor", "turbine"),
                 "proof": "A signed test report from an independent test lab"},
}
CHALLENGE_S = 72 * 3600


def classify(sentence: str) -> str:
    s = f" {sentence.lower()} "
    score = {f: sum(1 for w in v["words"] if re.search(rf"\b{re.escape(w)}\b", s)) for f, v in FIELDS.items()}
    best = max(score, key=lambda f: (score[f], -list(FIELDS).index(f)))
    return best if score[best] else "software"


def _plain(sentence: str) -> str:
    """The need without the words Knos's Ready check refuses as vague (it names the deliverable, not its adjectives)."""
    words = [w for w in re.findall(r"[\w'-]+", sentence) if w.lower() not in kr.VAGUE]
    return " ".join(words)[:90] or "The deliverable"


def draft(sentence: str, field: str) -> dict:
    """A brief Knos's Ready check can pass, from one sentence: one milestone, its measurable target and its verifier."""
    name = _plain(sentence)
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40] or "deliverable"
    if field == "software":
        ms = {"name": name, "target": f"test_{slug} passes in the repository's CI", "verifier": {"kind": "machine", "check": f"test_{slug}"}}
    elif field == "data":
        ms = {"name": name, "target": "1 run from a fresh checkout reproduces the reported metric within 1%",
              "verifier": {"kind": "machine", "check": f"reproduce_{slug}"}}
    elif field == "wetlab":
        ms = {"name": name, "target": "3 samples meet the QC specification of the lab protocol",
              "verifier": {"kind": "human", "what": "the QC result of each sample", "how": "the published lab protocol, run on 3 samples",
                           "who": "the lab that ran it, attested on Solana (SAS)", "where": "the protocol and QC report linked on the milestone"}}
    else:
        ms = {"name": name, "target": "the unit passes 1 test, in a signed test report",
              "verifier": {"kind": "human", "what": "the test result of the unit", "how": "the named test procedure of the report",
                           "who": "an independent test lab, signed", "where": "the signed report linked on the milestone"}}
    return {"title": sentence.strip()[:120], "milestones": [{"key": "m1", **ms, "deadline_days": 30}], "kill_fee_bps": 0,
            "challenge_s": CHALLENGE_S}


def need(sentence: str, user: dict, open_: bool, state) -> dict:
    """One sentence -> a Ready brief, a private demand check and an opened milestone (private unless open_)."""
    from . import check, privacy, track, valley
    t0 = time.perf_counter()
    sentence = (sentence or "").strip()
    if len(sentence.split()) < 3:
        raise ValueError("need: one sentence saying what your company needs")
    privacy.check({"need": sentence})
    field = classify(sentence)
    brief = draft(sentence, field)
    r = kr.check(brief)
    rep = check.demand_check(sentence, None, None, client=state.rest)
    rep["private"] = not open_
    state.keep_check(rep)
    d = rep.get("decision") or {}
    project = valley.create_project(user, "custom", brief["title"], [], rep.get("hash"), None, None, brief) if r.get("ready") else None
    if project and not open_:
        valley.unlist(project["id"], user)                     # private: off the public list, readable by its link
    card = None
    if r.get("ready"):
        try:
            card = track.ready_card(brief).get("card")
        except Exception as why:  # noqa: BLE001 - the card is the shareable proof; the brief and the project stand without it
            card = {"error": f"{type(why).__name__}: {str(why)[:120]}"}
    return {"field": field, "proof": FIELDS[field]["proof"], "challenge_hours": CHALLENGE_S // 3600,
            "brief": brief, "ready": r.get("ready"), "missing": r.get("missing") or [], "criteria_hash": r.get("criteria_hash"),
            "demand": {"hash": rep.get("hash"), "verdict": d.get("verdict"), "reasons": (d.get("reasons") or [])[:2], "private": not open_},
            "project": {"id": project["id"], "page": f"/app/#projects={project['id']}", "open": open_,
                        "milestone": (project.get("milestones") or [{}])[0].get("key")} if project else None,
            "ready_card": card, "steps": 3, "elapsed_ms": round((time.perf_counter() - t0) * 1000)}


def solvers() -> dict:
    """Wallets with verified milestones, most first: each attestation read back from devnet (track.record)."""
    from . import track, valley
    idx = valley._safe_load("pages", "solvers") or {"wallets": {}}
    wallets = list(idx["wallets"])
    for p in valley._all("projects"):                # the makers each project paid, should the index be behind
        for m in p.get("milestones") or []:
            for a in m.get("attempts") or []:
                wallets += [t["wallet"] for t in a.get("attestations") or [] if t.get("role") == "maker" and t.get("wallet")]
    rows = []
    for wallet in list(dict.fromkeys(wallets))[:100]:
        try:
            rec = track.record(wallet)
        except Exception:  # noqa: BLE001 - a wallet the chain cannot answer for is not listed as proven
            continue
        if rec["verified_milestones"]:
            rows.append({"wallet": wallet, "verified_milestones": rec["verified_milestones"],
                         "latest": rec["attestations"][-1]["explorer"] if rec["attestations"] else None})
    rows.sort(key=lambda r: -r["verified_milestones"])
    return {"solvers": rows, "count": len(rows), "rule": "proven solvers first: verified milestones, each an attestation on devnet"}
