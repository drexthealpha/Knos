"""Wanted? Step 2 of the one flow, wall 1 (money comes before proof): demand evidence, then money locked before proof
and released in stages as the proof arrives.

Demand evidence, two kinds:
  1. the demand check (apps/wanted, knos_wanted): Qloo taste evidence for the product the idea would become, through
     Qloo's official MCP harness. With no Qloo key it runs Knos's labelled MOCK server; every report says which.
     Directional demand evidence, not a sales forecast.
  2. money: buyers' PRE-ORDERS (the claim's pre-order pool, scope 0 of knos.graduation: paid to the makers when the
     product is delivered) and PULL COMMITMENTS, advance-market-commitment style: "I buy N units at price P if the
     result is verified". A pull commitment is locked as one knos_pay private order per STAGE (milestone k = scope k of
     the claim), each holding its share of N x P and each released when its milestone oracle is met and the judge signs:

        preprint_posted    the claim's preprint exists on arXiv / bioRxiv / medRxiv (read live)
        journal_published  bioRxiv/medRxiv `pubs` names a journal DOI, or the DOI resolves at Crossref, not retracted
        trial_registered   ClinicalTrials.gov has the study and it is not withdrawn
        results_posted     ClinicalTrials.gov `hasResults` is true
        not_retracted      Crossref's Retraction Watch data shows no retraction for the claim's DOI
        referee_pass       a Knos referee verdict for this claim passed (sealed tests, independent re-runs)
        lab_qc             a Knos lab adapter verdict for this claim passed protocol + QC

     A stage nobody meets by its deadline refunds the buyer (anyone may send RefundOrder). This is the advance market
     commitment pattern (Gavi's pneumococcal AMC) on a public vault, priced by config/fees.yaml (payout fee on top of
     each order, the graduation fee on release).

Who releases a stage. knos_pay pays an order on a token its judge signs. Today that is the research repository's
pinned
prove.yml, signed by GitHub (`release_audience` gives the exact audience); the issuer-agnostic path (an m-of-n signed
referee verdict, ORCID and Confidential Space tokens) is V34PAY's knos_pay change. `check()` produces the oracle's
evidence and its sha256, which is what either judge signs over. Nothing in this module signs a release.

Pure builders and readers; `ledger` is knos.chain.Ledger or a test stand-in. Devnet only for anything sent.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from solders.instruction import Instruction
from solders.pubkey import Pubkey

from .. import graduation
from ..money import fees_config
from ..settle.v2 import pay
from . import IdeaError, Names, check as check_record, now, release_schedule
from .http import FetchError, Fetcher

TERMS_V = 1
DAY = 86_400
ORACLES = ("preprint_posted", "journal_published", "trial_registered", "results_posted", "not_retracted", "referee_pass", "lab_qc")
ORACLE = Names(" ".join(ORACLES))         # ORACLE.results_posted == "results_posted"
DEFAULT_STAGES = {  # (oracle, share of N x P in basis points): literature claims and clinical claims
    "literature": [("preprint_posted", 2000), ("referee_pass", 5000), ("lab_qc", 3000)],
    "clinical": [("trial_registered", 2000), ("results_posted", 3000), ("referee_pass", 5000)],
    "published": [("not_retracted", 2000), ("referee_pass", 5000), ("lab_qc", 3000)],
}
DEFAULT_JUDGE_REPO = 1401439243      # drexthealpha/knos-e2e: the judge repository of Knos's devnet demos
RETRACTED_WORD = "retracted: do not fund"


def default_stages(c: dict) -> list[tuple[str, int]]:
    """The stages a claim gets unless the buyer names them: a trial's registry milestones; a preprint's posting; and
    for a paper already published in a journal (a DOI, no preprint id) a first stage it can actually complete (no
    retraction on record), never "preprint posted", which would stay pending forever."""
    ids = c.get("ids", {})
    if ids.get("nct"):
        return list(DEFAULT_STAGES["clinical"])
    if ids.get("doi") and not any(ids.get(k) for k in ("arxiv", "biorxiv", "medrxiv", "epmc")):
        return list(DEFAULT_STAGES["published"])
    return list(DEFAULT_STAGES["literature"])


def retraction_warning(c: dict) -> str | None:
    """A clear warning when the claim's paper carries a retraction notice (Retraction Watch via Crossref)."""
    if (c.get("retraction") or {}).get("retracted") or "retracted" in (c.get("risk") or []):
        return ("RETRACTED: this paper carries a retraction notice (Retraction Watch via Crossref). Demand for it is not "
                "evidence for the claim; Knos will not lock a commitment on it unless the buyer insists (--allow-retracted).")
    return None


# ---- 1. demand evidence: the Qloo demand check -------------------------------------------------------------------
def _knos_wanted():
    try:
        import knos_wanted  # noqa: F401
    except ImportError:
        app = Path(__file__).resolve().parents[3] / "apps" / "wanted"
        if app.is_dir() and str(app) not in sys.path:
            sys.path.insert(0, str(app))
    from knos_wanted import demand, qloo_mcp
    return demand, qloo_mcp


def product_phrase(c: dict) -> str:
    """The product the idea would become, in the words the demand planner reads (a maker can give their own)."""
    words = c["statement"].rstrip(".")
    return f"a product from this research: {words[:160]}"


def demand(c: dict, product: str | None = None, place: str | None = None, rivals: list[str] | None = None, q=None) -> dict:
    """Run Knos's demand check on the product the idea would become. Live through `qloo mcp` when Qloo's credential
    is configured; else Knos's MOCK server (labelled). Candidates are confirmed FIRST-pick here (a maker confirms each
    in the demand-check page); that is said in the result."""
    try:
        dm, qm = _knos_wanted()
    except Exception as why:  # noqa: BLE001 - not installed here (a wheel): the hosted check answers instead
        return hosted(c, product, place, why)
    own = q is None
    if own:
        if os.environ.get("QLOO_API_KEY") or os.environ.get("KNOS_WANTED_LIVE") == "1":
            q = qm.Qloo()
        else:
            q = qm.Qloo(qm.InProcess(), mode="mock", reason="QLOO_API_KEY missing: Knos's MOCK server")
    try:
        s = dm.start(q, product or product_phrase(c), rivals or [], place)
        choices = {qn["key"]: qn["candidates"][0]["id"] for qn in s["questions"] if qn["candidates"]}
        rep = dm.confirm(q, s, choices)
    except Exception as why:  # noqa: BLE001
        return {"status": "error", "why": f"{type(why).__name__}: {why}", "mode": getattr(q, "mode", None)}
    finally:
        if own:
            q.close()
    lean = rep["lean"]
    warn = retraction_warning(c)
    if warn:      # taste data says nothing about whether a retracted result holds: never "leans wanted"
        lean = {**lean, "word": RETRACTED_WORD, "taste_word": lean.get("word"), "why": [warn, *lean.get("why", [])]}
    return {"status": "ok", "mode": rep["mode"], "label": rep["label"], "framing": rep["framing"], "idea": rep["idea"],
            "lean": lean, "hash": rep["hash"], "steps": len(rep.get("trail", [])), **({"warning": warn} if warn else {}),
            "confirmed": "first candidate of each question (demo); a maker confirms each match in the demand-check page",
            "key": "QLOO_API_KEY (live when set; MOCK otherwise)"}


LEAN = {"OPEN": "leans wanted", "REFUSE": "leans not wanted", "CANNOT_DECIDE": "cannot decide"}


def hosted(c: dict, product: str | None, place: str | None, missing: Exception) -> dict:
    """The demand check as the hosted app runs it (POST /api/check, knos.demand_cli.ask), labelled "hosted"."""
    from ..demand_cli import ask
    from ..demand_tool import base_url
    try:
        rep = ask(product or product_phrase(c), place, None, {})
    except Exception as why:  # noqa: BLE001 - neither here nor hosted: said, with both reasons
        return {"status": "unavailable", "why": f"knos_wanted not importable ({type(missing).__name__}); the hosted check did not answer ({str(why)[:120]})"}
    d = rep.get("decision") or {}
    reasons = [rep["qloo_limit"]] if rep.get("qloo_limit") else list(d.get("reasons") or [])[:2]
    near = (rep.get("nearest") or {}).get("idea")
    return {"status": "ok", "mode": "hosted", "label": f"hosted: {base_url()}/api/check" + (f", the nearest idea Qloo has answered: {near}" if near else ""),
            "idea": rep.get("idea"), "lean": {"word": LEAN.get(str(d.get("verdict")), "cannot decide"), "why": reasons},
            "hash": rep.get("hash"), "steps": len(rep.get("calls") or []), "key": "the hosted check: knos_wanted is not installed here"}


# ---- 2. milestone oracles -----------------------------------------------------------------------------------------
def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _file_verdict(path: str | None, claim_id: str, kind: str) -> dict:
    if not path:
        return {"met": None, "why": f"no {kind} verdict for this claim yet (pending)"}
    try:
        v = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"met": False, "why": f"the {kind} verdict file cannot be read ({type(e).__name__})"}
    if v.get("claim") not in (None, claim_id):
        return {"met": False, "why": f"the {kind} verdict is for another claim"}
    ok = v.get("passed") is True if kind == "referee" else str(v.get("qc", "")).lower() == "pass" or v.get("passed") is True
    return {"met": ok, "why": f"{kind} verdict {'passed' if ok else 'did not pass'}", "verdict_sha256": _h(v),
            "synthetic": bool(v.get("synthetic"))}


def _signed_verdict(path: str, c: dict, oracle: str, panel: tuple[int, list[str]] | None) -> dict:
    """A referee_pass / lab_qc verdict that counts: m of the committed panel's referees signed it (`knos idea sign`
    records, as a JSON list or {"signatures": [...]}). Each signature is checked against its digest and its key
    against the panel; they must agree on the verdict and the evidence."""
    from . import commit as C
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"met": None, "accepted": False, "why": f"the verdict file cannot be read ({type(e).__name__})"}
    recs = raw if isinstance(raw, list) else raw.get("signatures") if isinstance(raw, dict) else None
    if not recs:
        return {"met": None, "accepted": False, "signed": False,
                "why": "an unsigned verdict file is refused: it needs m signatures of the committed referee panel (knos idea sign)"}
    if panel is None:
        return {"met": None, "accepted": False, "signed": True, "why": "signed verdicts need the committed panel to be checked (give the commitment file)"}
    try:
        got = C.count_signatures(recs, c, oracle, panel)
    except IdeaError as e:
        return {"met": None, "accepted": False, "signed": True, "why": str(e)}
    return {"met": got["verdict"] == "PASS", "accepted": True, "signed": True, "signers": got["keys"], "verdict_evidence": got["evidence_hash"],
            "why": f"{len(got['keys'])} of the panel's referees signed {got['verdict']} (needs {panel[0]})"}


def check(c: dict, oracle: str, f: Fetcher | None = None, verdict: str | None = None, panel: tuple[int, list[str]] | None = None) -> dict:
    """Is this stage's milestone met right now? {met: True/False/None (pending), evidence, evidence_hash}. Reads the
    public source live (or the fixture the Fetcher holds); referee_pass/lab_qc read a verdict file."""
    from . import sources as S
    if oracle not in ORACLES:
        raise IdeaError(f"oracle: one of {', '.join(ORACLES)}")
    f = f or Fetcher()
    ids = c.get("ids", {})
    ev: dict = {"oracle": oracle, "claim": c["id"], "claim_hash": c["hash"]}
    try:
        if oracle == "preprint_posted":
            if ids.get("arxiv"):
                got = S.arxiv(f, ids["arxiv"])
                ev.update(met=True, why=f"arXiv lists {ids['arxiv']}", source="arxiv", mode=got["sources"][0]["mode"])
            elif ids.get("biorxiv") or ids.get("medrxiv"):
                server = "biorxiv" if ids.get("biorxiv") else "medrxiv"
                got = S.rxiv(f, ids[server], server)
                ev.update(met=True, why=f"{server} lists {ids[server]} (version {got.get('preprint_version')})", source=server,
                          mode=got["sources"][0]["mode"])
            elif ids.get("epmc"):
                ev.update(met=True, why=f"Europe PMC preprint {ids['epmc']}", source="europepmc", mode="record")
            else:
                ev.update(met=None, why="no preprint id on the record yet (pending)")
        elif oracle == "journal_published":
            jserver = "biorxiv" if ids.get("biorxiv") else "medrxiv" if ids.get("medrxiv") else None
            if jserver:
                got = S.rxiv_published(f, ids[jserver], jserver)
                ev.update(met=bool(got["published_doi"]), why=f"{jserver} pubs: {got['published_doi'] or 'not published yet'}",
                          published_doi=got["published_doi"], source=jserver, mode=got["mode"])
            elif ids.get("doi"):
                r = S.retraction(f, ids["doi"])
                ev.update(met=r["checked"] and not r["retracted"], why=f"Crossref resolves {ids['doi']}" + (" (RETRACTED)" if r["retracted"] else ""),
                          source="crossref", mode=r.get("mode"))
            else:
                ev.update(met=None, why="no DOI on the record yet (pending)")
        elif oracle in ("trial_registered", "results_posted"):
            if not ids.get("nct"):
                ev.update(met=False, why="the record names no ClinicalTrials.gov study")
            else:
                got = S.clinicaltrials(f, ids["nct"])
                t = got["trial"]
                if oracle == "trial_registered":
                    ev.update(met=t["status"] not in ("WITHDRAWN", None), why=f"{ids['nct']} status {t['status']}")
                else:
                    ev.update(met=bool(t["has_results"]), why=f"{ids['nct']} hasResults {t['has_results']}")
                ev.update(source="clinicaltrials", mode=got["sources"][0]["mode"], status=t["status"], has_results=t["has_results"])
        elif oracle == "not_retracted":
            if not ids.get("doi"):
                ev.update(met=None, why="no DOI to check (pending)")
            else:
                r = S.retraction(f, ids["doi"])
                ev.update(met=r["checked"] and not r["retracted"], why="Retraction Watch: " + ("RETRACTED" if r["retracted"] else "no retraction"),
                          notices=r["notices"], source="crossref", mode=r.get("mode"))
        else:
            kind = "referee" if oracle == "referee_pass" else "lab"
            if verdict and _is_signed_file(verdict):
                ev.update(_signed_verdict(verdict, c, oracle, panel), source=f"knos {kind} panel")
            else:          # an unsigned file is read and shown, but never accepted: no verdict can be signed or released on it
                ev.update(_file_verdict(verdict, c["id"], kind), source="knos referee" if kind == "referee" else "knos lab adapter")
                if verdict:
                    ev.update(accepted=False, signed=False,
                              why=ev["why"] + "; UNSIGNED: refused for release (needs m signatures of the committed panel)")
    except (FetchError, IdeaError) as e:
        ev.update(met=None, why=f"the source could not be read ({e}); try again", source=None)
    ev["read"] = now()
    ev["evidence_hash"] = _h({k: v for k, v in ev.items() if k not in ("read", "mode")})
    return ev


def _is_signed_file(path: str) -> bool:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(raw, list) or (isinstance(raw, dict) and "signatures" in raw)


# ---- 3. the pull commitment and pre-order plan --------------------------------------------------------------------
def _int(v, name: str, low: int, high: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not low <= v <= high:
        raise IdeaError(f"{name}: a whole number from {low:,} to {high:,}")
    return v


def plan(c: dict, *, units: int, price: int, stages: list[tuple[str, int]] | None = None, repo_id: int = DEFAULT_JUDGE_REPO,
         maker_github_id: int | None = None, stage_days: list[int] | None = None, pool_days: int = 90, demand_hash: str | None = None,
         decimals: int = 6, wf_repo: str = graduation.JUDGE_WF_REPO, wf_sha: str | None = None,
         cfg: fees_config.FeeConfig | None = None, stage_work_s: list[int] | None = None) -> dict:
    """What locking a pull commitment on this idea opens (nothing is sent): `units` x `price` (whole units of a
    `decimals` mint) split over the stages by basis points (summing to 10,000), one private knos_pay order per stage
    (milestone k), and the claim's pre-order pool (scope 0). Each stage must hold at least knos_pay's order minimum."""
    check_record(c)
    cfg = cfg or fees_config.load()
    stages = stages or default_stages(c)
    _int(units, "units", 1, 10_000_000)
    _int(price, "price", 1, 1_000_000_000)
    _int(repo_id, "repo_id", 1, 2 ** 63)
    if maker_github_id is not None:
        _int(maker_github_id, "maker_github_id", 1, 2 ** 63)
    if not 1 <= len(stages) <= 8 or sum(b for _, b in stages) != 10_000 or any(o not in ORACLES or b <= 0 for o, b in stages):
        raise IdeaError(f"stages: 1 to 8 (oracle, basis points) pairs, oracles from {', '.join(ORACLES)}, shares summing to 10,000")
    if len({o for o, _ in stages}) != len(stages):
        raise IdeaError("stages: each oracle once")
    one = 10 ** decimals
    total = units * price * one
    if total > pay.units(pay.MAX_AMOUNT, decimals):
        raise IdeaError("units x price is above knos_pay's maximum order")
    days = stage_days or [30 * (k + 1) for k in range(len(stages))]
    work = stage_work_s or [d * DAY for d in days]
    if len(work) != len(stages):
        raise IdeaError("one deadline per stage")
    amounts = release_schedule(total, [b / 100 for _, b in stages])     # whole base units, summing exactly to N x P
    low = pay.units(pay.ORDER_MIN_AMOUNT, decimals)
    for (o, _), a in zip(stages, amounts):
        if a < low:
            raise IdeaError(f"stage {o}: {a / one:g} units is under knos_pay's order minimum ({low / one:g}); raise units x price or its share")
    for w in work:
        _int(w, "stage deadline (s)", pay.MIN_WORK, pay.MAX_WORK)
    _int(pool_days * DAY, "pool deadline (s)", pay.MIN_WORK, pay.MAX_WORK)
    cid = c["id"]
    split = {"researcher": 10_000}
    commitment = {"v": TERMS_V, "kind": "pull-commitment", "claim": cid, "claim_hash": c["hash"], "field": c["field"],
                  "units": units, "price": price, "decimals": decimals, "total": total, "demand": demand_hash,
                  "stages": [{"milestone": k + 1, "oracle": o, "bps": b, "amount": a, "work_s": w}
                             for k, ((o, b), a, w) in enumerate(zip(stages, amounts, work))],
                  "release": "each stage paid to the researcher when its oracle is met and the judge signs; refunded after its deadline otherwise"}
    p = {"claim_id": cid, "claim_hash": c["hash"], "spec_hash": c["hash"], "repo_id": repo_id, "wf_repo": wf_repo,
         "wf_sha": wf_sha or pay.IDS["claim_sha"], "program": str(pay.PAY_ID), "mode": pay.MERGE,
         "options": graduation.options(repo_id).hex(), "payees": [] if maker_github_id is None else [(maker_github_id, 10_000, None)],
         "commitment": commitment, "commitment_hash": _h(commitment), "stages": [], "cluster": "devnet"}
    for st in commitment["stages"]:
        t = pay.terms_json({"v": TERMS_V, "kind": "pull-commitment-stage", "claim": cid, "spec_hash": c["hash"], "milestone": st["milestone"],
                            "oracle": st["oracle"], "units": units, "price": price, "bps": st["bps"], "commitment": p["commitment_hash"],
                            "split": split})
        part = f"stage{st['milestone']}"
        p[part] = {"scope": graduation.scope(cid, repo_id, st["milestone"]).hex(), "terms": t.decode(), "terms_hash": pay.terms_hash(t).hex(),
                   "amount": st["amount"], "payout_fee": pay.order_fee(st["amount"], decimals=decimals), "work_s": st["work_s"],
                   "oracle": st["oracle"], "milestone": st["milestone"], "graduation_fee": cfg.fee("graduation", st["amount"])}
        p["stages"].append(part)
    pt = graduation.terms("preorder", cid, c["hash"], 0, [("researcher", 10_000)])
    p["pool"] = {"scope": graduation.scope(cid, repo_id, graduation.POOL_ISSUE).hex(), "terms": pt.decode(),
                 "terms_hash": pay.terms_hash(pt).hex(), "work_s": pool_days * DAY, "min_buyers": 1, "min_locked": 0}
    p["warnings"] = [w for w in (retraction_warning(c),) if w]
    p["payee"] = "chosen at commit (knos idea commit --payee); none is assumed" if maker_github_id is None else f"GitHub id {maker_github_id}"
    p["buyer_pays"] = total + sum(p[s]["payout_fee"] for s in p["stages"])
    p["fees"] = {"payout_fee_each_stage": [p[s]["payout_fee"] for s in p["stages"]], "graduation_fee_status": cfg.doc["fees"]["graduation"]["status"],
                 "source": "config/fees.yaml"}
    return p


def fund_ix(p: dict, part: str, funder: Pubkey, funder_token: Pubkey, mint: Pubkey, amount: int | None = None, seq: int = 0,
            token_program: Pubkey = pay.TOKEN) -> Instruction:
    """FundOrderWallet of one stage of the pull commitment ("stage1", ...) or of a pre-order in the pool ("pool",
    `amount` given): `funder` signs; the amount plus the payout fee leave `funder_token`."""
    if part not in p["stages"] and part != "pool":
        raise IdeaError(f"part: one of {', '.join(p['stages'])} or pool")
    amt = int(p[part]["amount"] if part != "pool" else (amount or 0))
    if part == "pool":
        _int(amt, "amount", pay.units(pay.ORDER_MIN_AMOUNT), pay.units(pay.MAX_AMOUNT))
    return pay.fund_order_wallet_ix(funder, funder_token, mint, 0, 0, amt, p["wf_repo"], p["wf_sha"], bytes.fromhex(p[part]["terms_hash"]),
                                    mode=p["mode"], work_s=p[part]["work_s"], seq=seq, options=bytes.fromhex(p["options"]),
                                    scope=bytes.fromhex(p[part]["scope"]), token_program=token_program, program=Pubkey.from_string(p["program"]))


def address(p: dict, part: str, funder: Pubkey, seq: int = 0) -> Pubkey:
    return pay.order_pda(bytes.fromhex(p[part]["scope"]), funder, seq, Pubkey.from_string(p["program"]))


def release_audience(p: dict, part: str, order: Pubkey, evidence_hash: str, pr: int = 1, payees=None) -> dict:
    """What releases a stage today: the audience the judge repository's pinned prove.yml asks GitHub to sign, with the
    oracle's evidence hash in place of a head commit (40 hex: its first 40). Returned, never signed here."""
    ps = payees if payees is not None else [(i, b, None if a is None else Pubkey.from_string(a)) for i, b, a in p["payees"]]
    head = evidence_hash[:40]
    return {"route": "github-oidc (knos_pay today)", "audience": pay.order_pay_audience(order, head, bytes.fromhex(p[part]["terms_hash"]), p["mode"], pr, ps),
            "head_sha_is": "the first 40 hex of the oracle's evidence_hash", "evidence_hash": evidence_hash,
            "next_route": "an m-of-n signed Knos referee verdict over (order, evidence_hash, amount, recipient, expiry): knos_pay's issuer-agnostic release (next)"}


def refund_ix(relayer: Pubkey, order: Pubkey, o: pay.Order, program: Pubkey | None = None) -> Instruction:
    return pay.refund_order_ix(relayer, order, o, program=program or pay.PAY_ID)


def state(ledger, p: dict, mint: str) -> dict:
    """Every stage and the pool as the chain has them now, counting only this plan's own orders in `mint`."""
    nowt = ledger.now() if hasattr(ledger, "now") else None
    prog = Pubkey.from_string(p["program"])
    out = {"claim": p["claim_id"], "mint": mint, "parts": {}}
    for part in [*p["stages"], "pool"]:
        rows: list[dict[str, Any]] = []
        ignored: list[dict[str, str]] = []
        for a, o in graduation.orders(ledger, bytes.fromhex(p[part]["scope"]), prog):
            why = graduation.mismatch(p, part, o, mint)
            if why:
                ignored.append({"order": str(a), "why": why})
                continue
            rows.append({"order": str(a), "source": str(o.source), "amount": o.amount, "fee": o.fee, "state": o.state,
                         "past_deadline": None if nowt is None else nowt > o.pay_until})
        live = [r for r in rows if r["state"] == "open" and not r["past_deadline"]]
        out["parts"][part] = {"oracle": p[part].get("oracle", "product delivered (graduation)"), "orders": rows, "ignored": ignored,
                              "locked": sum(int(r["amount"]) for r in live), "buyers": len({r["source"] for r in live})}
    out["locked_total"] = sum(v["locked"] for v in out["parts"].values())
    return out


# ---- 4. stages judged by a referee panel: released on m-of-n signed verdicts (knos_pay 0.3.34) ----------------------
# A stage can be a PANEL order instead of a GitHub-judged one: the buyer pins m-of-n referee keys when locking it, and
# the stage is released when m referees sign the verdict "stage k met" over the oracle's evidence hash (PASS, paid to
# the payees), or refunded at once when m sign "stage k missed" (FAIL). knos.proof.issuers builds the instructions;
# these helpers tie them to a stage: the order's scope is the idea's topic and the stage's milestone, its terms are the
# stage's terms, and the evidence a referee signs is `check()`'s evidence_hash, so a verdict names exactly what was read.
STAGE_TOPIC = "knos-idea-stage:"
PASS, FAIL = "PASS", "FAIL"      # the two verdicts a referee signs for a stage


def _iss():
    from ..proof import issuers
    return issuers


def _panel(keys, *, funder=None, payees=(), unlisted_panel=None) -> str:
    """Knos's panel rule (knos.platform.referees): '' or the UNLISTED PANEL label; IdeaError for a panel it refuses."""
    from ..platform import referees
    try:
        return referees.panel_rule(keys, funder=funder, payees=payees, unlisted_panel=unlisted_panel)
    except referees.PanelError as why:
        raise IdeaError(f"panel: {why}") from None


def panel_topic(p: dict) -> int:
    """The topic id (a judged order's repo id) of an idea's pull commitment: one per claim and commitment."""
    return _iss().topic_id(STAGE_TOPIC + p["claim_id"] + ":" + p["commitment_hash"])


def fund_panel_ix(p: dict, part: str, funder: Pubkey, funder_token: Pubkey, mint: Pubkey, m: int, keys: list[bytes], seq: int = 0,
                  program: Pubkey = pay.PAY_ID, unlisted_panel: bool | None = None) -> Instruction:
    """FundOrderWallet of one stage as a PANEL order: m of the referee keys `keys` (32 bytes each) release it.
    The panel is held to Knos's referee registry (knos.platform.referees.panel_rule): the funder's own key is refused,
    and keys outside config/referees.yaml are refused with unlisted_panel=False (what --unlisted-panel turns off)."""
    if part not in p["stages"]:
        raise IdeaError(f"part: one of {', '.join(p['stages'])}")
    _panel(keys, funder=funder, unlisted_panel=unlisted_panel)
    st = p[part]
    return _iss().fund_order_judged_ix(funder, funder_token, mint, panel_topic(p), st["milestone"], st["amount"], st["terms"].encode(),
                                       panel=(m, keys), work_s=st["work_s"], seq=seq, program=program)


def panel_address(p: dict, part: str, funder: Pubkey, seq: int = 0, program: Pubkey = pay.PAY_ID) -> Pubkey:
    return pay.order_pda(pay.scope_of(panel_topic(p), p[part]["milestone"]), funder, seq, program)


def verdict_of(ev: dict) -> str | None:
    """The verdict an oracle reading supports: PASS when met, FAIL when not met, None while pending (no verdict)."""
    if ev.get("accepted") is False:       # an unsigned referee/lab file, or one the panel did not sign: no verdict
        return None
    return PASS if ev.get("met") is True else FAIL if ev.get("met") is False else None


def stage_digest(order: Pubkey, o: pay.Order, ev: dict, payees, program: Pubkey = pay.PAY_ID) -> bytes:
    """What each referee signs for this stage: the verdict digest over the oracle's evidence hash, with the payees for
    PASS or "FAIL" for a missed stage. Refused while the oracle is pending."""
    v = verdict_of(ev)
    if v is None:
        raise IdeaError(f"{ev.get('oracle')}: the milestone is pending; no verdict can be signed yet")
    return _iss().verdict_digest(order, o, bytes.fromhex(ev["evidence_hash"]), payees if v == PASS else FAIL, program)


def sign_stage(referee, order: Pubkey, o: pay.Order, ev: dict, payees, program: Pubkey = pay.PAY_ID) -> tuple[bytes, bytes]:
    """One referee's (public key, ed25519 signature) over the stage's verdict. The referee's key never leaves its
    holder: this runs where the key is."""
    d = stage_digest(order, o, ev, payees, program)
    return bytes(referee.pubkey()), bytes(referee.sign_message(d))


def stage_verdict_ixs(relayer: Pubkey, order: Pubkey, o: pay.Order, m: int, keys: list[bytes], ev: dict, payees,
                      signatures: list[tuple[bytes, bytes]], program: Pubkey = pay.PAY_ID, unlisted_panel: bool | None = None) -> list[Instruction]:
    """[ed25519 precompile, PayOrder with the PASS verdict] for a met stage, or [precompile, RefundOrder with the FAIL
    verdict] for a missed one. A cluster transaction holds one signature with a 3-key panel and one payee: send one
    per referee; the program tallies them and pays (or refunds) at the m-th."""
    iss = _iss()
    _panel(keys, funder=o.source, payees=payees if verdict_of(ev) == PASS else (), unlisted_panel=unlisted_panel)
    d = stage_digest(order, o, ev, payees, program)
    pre = iss.ed25519_ix(signatures, d)
    evidence = bytes.fromhex(ev["evidence_hash"])
    if verdict_of(ev) == PASS:
        return [pre, iss.pay_order_verdict_ix(relayer, order, o, m, keys, evidence, payees, program=program)]
    return [pre, iss.refund_order_verdict_ix(relayer, order, o, m, keys, evidence, program=program)]
