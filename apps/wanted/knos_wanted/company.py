"""The company side of the demand check: what Knos records and what Knos charges.

Record (knos.record, Sibyl WARM/COLD, anchored on Solana devnet):
  demand report  WARM  claim `demand:<report hash 40>` (its state: lean, mode, steps, pre-orders so far)
                 COLD  `experiment`: the report hash, the hash of the request-to-result trail, the tools called
  pre-order      COLD  `funding`: order address, devnet signature, amount, the fee lines below
                 WARM  the claim again with the pool's new state
  anchor         the Merkle root of every unanchored line in one devnet Memo transaction (knos.record.anchor), signed
                 by the app's devnet TEST wallet; after each pre-order, or `python -m knos_wanted anchor`.
The record is public, so a line holds hashes, statuses, tool names, addresses and amounts: never the maker's idea
text (only its sha256), never a buyer's tastes, never a Qloo result (Qloo data is never stored in public).

Fees: from config/fees.yaml through knos.money.fees_config, nothing typed here:
  funding     0 when the pre-order is locked (knos_pay holds the payout fee with the money)
  payout      the on-chain fee, taken by knos_pay at release to the maker (live)
  graduation  Knos's fee on a pre-order pool released after the product graduates (decided, collected off chain)
  demand_check   10 a month free; a deep demand check 500 USD by card once the company exists
  release        the 1% release fee; knos_pay charges the payout fee until a timelocked upgrade
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

DOMAIN = "demand"


def claim_id(report_hash: str) -> str:
    return "demand:" + report_hash[:40]


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _record():
    try:
        from knos import record
        return record
    except Exception:  # noqa: BLE001 - knos (or Sibyl) not installed: the flows run, the page says "not recorded"
        return None


def root() -> Path | None:
    rec = _record()
    if rec is None:
        return None
    v = os.environ.get("KNOS_WANTED_RECORD")
    return Path(v) if v else rec.default_root()


def _safe(fn, *a, **kw) -> dict:
    try:
        return fn(*a, **kw)
    except ImportError as why:
        return {"recorded": False, "why": f"Sibyl is not installed ({why.name or why})"}
    except Exception as why:  # noqa: BLE001 - a refused or failed record never hides the report; it says so
        return {"recorded": False, "why": f"{type(why).__name__}: {str(why)[:200]}"}


def record_report(rep: dict, store=None) -> dict:
    rec = _record()
    if rec is None:
        return {"recorded": False, "why": "the knos package is not installed"}

    def go():
        cid = claim_id(rep["hash"])
        steps = [{"tool": t["tool"], "status": t["status"]} for t in rep["trail"]]
        state = {"what": "Knos demand check report", "report_hash": rep["hash"], "idea_sha256": sha(rep["idea"]),
                 "mode": rep["mode"], "synthetic": rep["mode"] != "live", "lean": rep["lean"]["word"], "steps": steps,
                 "trail_sha256": sha(rep["trail"]), "framing": rep["framing"], "aggregate": rep["aggregate"],
                 "preorders": {"orders": 0, "units": 0}}
        r = root()
        warm = rec.claim(cid, state, domain=DOMAIN, root=r, store=store)
        cold = rec.append("experiment", {"report_hash": rep["hash"], "trail_sha256": state["trail_sha256"], "calls": sum(1 for s in steps if s["tool"]), "confirmations": sum(1 for s in steps if not s["tool"]),
                                         "tools": sorted({s["tool"] for s in steps if s["tool"]}), "mode": rep["mode"],
                                         "synthetic": state["synthetic"]}, claim=cid, domain=DOMAIN, root=r, store=store)
        return {"recorded": True, "claim": cid, "warm_seq": warm["seq"], "cold_seq": cold["seq"], "anchored": False}
    return _safe(go)


def record_preorder(report_hash: str, res: dict, quote: dict, synthetic_report: bool, store=None) -> dict:
    rec = _record()
    if rec is None:
        return {"recorded": False, "why": "the knos package is not installed"}

    def go():
        cid = claim_id(report_hash)
        r = root()
        cold = rec.append("funding", {"report_hash": report_hash, "order": res.get("order"), "signature": res.get("signature"),
                                      "buyer": res.get("buyer") or res.get("owner"), "buyer_kind": res.get("buyer_kind", "wallet"),
                                      "amount_units": res.get("amount_units"), "mint": res.get("mint"), "cluster": "devnet",
                                      "fees": quote, "synthetic_report": synthetic_report, "money": "devnet test units"},
                          claim=cid, domain=DOMAIN, root=r, store=store)
        prev = {}
        try:
            prev = rec.claim_state(cid, root=r, store=store) or {}
        except Exception:  # noqa: BLE001
            prev = {}
        pre = prev.get("preorders") or {"orders": 0, "units": 0}
        state = {k: v for k, v in prev.items() if not k.startswith("_")}
        state["preorders"] = {"orders": pre.get("orders", 0) + 1, "units": pre.get("units", 0) + (res.get("amount_units") or 0)}
        warm = rec.claim(cid, state or {"report_hash": report_hash, "preorders": state["preorders"]}, domain=DOMAIN, root=r, store=store)
        return {"recorded": True, "claim": cid, "cold_seq": cold["seq"], "warm_seq": warm["seq"], "anchored": False}
    return _safe(go)


def anchor(send=None, store=None) -> dict:
    """Anchor every unanchored line on devnet with the app's devnet TEST wallet (KNOS_WANTED_DEVNET_KEYPAIR)."""
    rec = _record()
    if rec is None:
        return {"anchored": False, "why": "the knos package is not installed"}

    def go():
        kp = None
        if send is None:
            from . import escrow
            kp = escrow.demo_key()
        line = rec.anchor(root(), keypair=kp, send=send, store=store)
        if line is None:
            return {"anchored": False, "why": "nothing pending"}
        p = line["payload"]
        return {"anchored": True, "tx": p["tx"], "first": p["first"], "last": p["last"], "root": p["root"], "signer": p["signer"],
                "explorer": f"https://explorer.solana.com/tx/{p['tx']}?cluster=devnet"}
    got = _safe(go)
    if "recorded" in got:
        got = {"anchored": False, "why": got["why"]}
    return got


def quote(units: int) -> dict:
    """The fee lines of one pre-order of `units` test units (6 decimals), read from config/fees.yaml."""
    try:
        from knos.money import fees_config
    except Exception:  # noqa: BLE001
        return {"available": False, "why": "the knos package is not installed"}
    cfg = fees_config.load()
    amount = int(units) * 1_000_000
    f = cfg.doc["fees"]
    return {"available": True, "source": "config/fees.yaml", "amount_units": units,
            "at_lock": {"line": "funding", "units": cfg.fee("funding", amount) / 1e6, "status": f["funding"]["status"]},
            "at_release": {"line": "payout", "units": cfg.fee("payout", amount) / 1e6, "status": f["payout"]["status"],
                           "payer": f["payout"].get("payer")},
            "on_graduation": {"line": "graduation", "units": cfg.fee("graduation", amount) / 1e6, "status": f["graduation"]["status"],
                              "collected": f["graduation"].get("collected")},
            "demand_report": {"line": "demand_check", "units": 0, "status": f["demand_check"]["status"],
                              "free_a_month": f["demand_check"]["free_a_month"], "today": f["demand_check"]["today"]}}


# ---- the decision check in the Record: Sibyl is the agent's working memory; money rules live on chain ------------
class NotInRecord(ValueError):  # Sibyl is the agent's working memory; it never gates money
    """Sibyl (the agent's memory) holds no such record."""


def record_check(rep: dict, store=None) -> dict:
    """WARM claim `demand:<hash>`: the decision (verdict, target, reserve), counts, no idea text; COLD `experiment`."""
    rec = _record()
    if rec is None:
        return {"recorded": False, "why": "the knos package is not installed"}

    def go():
        cid, r = claim_id(rep["hash"]), root()
        d = rep.get("decision") or {}
        state = {"what": "Knos demand check decision", "report_hash": rep["hash"], "idea_sha256": sha(rep.get("idea")),
                 "verdict": d.get("verdict"), "target_units": d.get("target_units"), "reserve_units": d.get("reserve_units"),
                 "live": str(rep.get("label", "")).startswith("LIVE"), "research": (rep.get("research") or {}).get("hash"),
                 "preorders": {"orders": 0, "units": 0, "list": []}, "released": []}
        warm = rec.claim(cid, state, domain=DOMAIN, root=r, store=store)
        cold = rec.append("experiment", {"report_hash": rep["hash"], "calls": len(rep.get("calls") or []),
                                         "endpoints": sorted({c["call"] for c in rep.get("calls") or []}), "verdict": d.get("verdict")},
                          claim=cid, domain=DOMAIN, root=r, store=store)
        return {"recorded": True, "claim": cid, "warm_seq": warm["seq"], "cold_seq": cold["seq"]}
    return _safe(go)


def record_queued(idea: str, reset: str, store=None) -> dict:
    """COLD `queued_check`: a picked reading Qloo could not answer, waiting for Qloo's reset (the idea's sha256, no text)."""
    rec = _record()
    if rec is None:
        return {"recorded": False, "why": "the knos package is not installed"}

    def go():
        cold = rec.append("queued_check", {"idea_sha256": sha(idea), "until": reset, "why": "Qloo's monthly limit"},
                          claim=claim_id(sha(idea)), domain=DOMAIN, root=root(), store=store)
        return {"recorded": True, "queued": True, "cold_seq": cold["seq"]}
    return _safe(go)


def record_state(report_hash: str, store=None) -> dict:
    """The decision as the agent remembers it (Sibyl, WARM). Raises NotInRecord when Sibyl is absent or holds none."""
    rec = _record()
    if rec is None:
        raise NotInRecord("the agent's memory (the Knos Record in Sibyl) is not available on this server")
    try:
        got = rec.claim_state(claim_id(report_hash), root=root(), store=store) or {}
    except ImportError:
        raise NotInRecord("Sibyl is not installed on this server: the agent has no memory here") from None
    if got.get("report_hash") != report_hash:
        raise NotInRecord("the agent's memory (Sibyl) holds no record of this report")
    return got


def record_lock(report_hash: str, order: str, units: int, signature: str | None, store=None) -> dict:
    rec = _record()

    def go():
        cid, r = claim_id(report_hash), root()
        prev = record_state(report_hash, store)
        cold = rec.append("funding", {"report_hash": report_hash, "order": order, "signature": signature, "amount_units": units,
                                      "cluster": "devnet", "money": "devnet test units"}, claim=cid, domain=DOMAIN, root=r, store=store)
        state = {k: v for k, v in prev.items() if not k.startswith("_")}
        pre = state.get("preorders") or {"orders": 0, "units": 0, "list": []}
        state["preorders"] = {"orders": pre.get("orders", 0) + 1, "units": pre.get("units", 0) + units, "list": [*pre.get("list", []), order]}
        warm = rec.claim(cid, state, domain=DOMAIN, root=r, store=store)
        return {"recorded": True, "claim": cid, "cold_seq": cold["seq"], "warm_seq": warm["seq"]}
    return _safe(go) if rec is not None else {"recorded": False, "why": "the knos package is not installed"}


def record_release(report_hash: str, order: str, signatures: list, evidence_sha256: str, store=None) -> dict:
    rec = _record()

    def go():
        cid, r = claim_id(report_hash), root()
        prev = record_state(report_hash, store)
        cold = rec.append("payout", {"report_hash": report_hash, "what": "pre-order released to the maker on proof", "order": order, "signatures": signatures, "evidence_sha256": evidence_sha256,
                                      "cluster": "devnet"}, claim=cid, domain=DOMAIN, root=r, store=store)
        state = {k: v for k, v in prev.items() if not k.startswith("_")}
        state["released"] = [*state.get("released", []), order]
        warm = rec.claim(cid, state, domain=DOMAIN, root=r, store=store)
        return {"recorded": True, "claim": cid, "cold_seq": cold["seq"], "warm_seq": warm["seq"]}
    return _safe(go) if rec is not None else {"recorded": False, "why": "the knos package is not installed"}
