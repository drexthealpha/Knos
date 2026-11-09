"""Graduation: a claim whose verdict passed (works, wanted, makeable: knos.referee.verdict) opens a funding vault for
its next milestone and a pre-order pool, and pays everyone who contributed when the milestone is accepted.

Both are knos_pay work orders (knos.settle.v2.pay), funded by a wallet, so nothing new holds money:

    the milestone vault   one order per funder: `amount` for the contributors, the payout fee on top (held with it,
                           taken at release, returned on a refund). Paid by the pinned judge workflow's
                           GitHub-signed token to up to four payees, the contributor split (knos.splits); refunded to
                           the funder after the deadline when nobody delivered.
    the pre-order pool     one order per buyer, in the claim's pool scope: locked demand against the claim's spec. The
                           pool's bar (N distinct buyers, X locked) is read from the chain (`pool`), and its orders
                           are what knos.referee's DemandBook counts (`demand_orders`). Paid to the makers on
                           delivery by the same judge; refunded to each buyer after the deadline otherwise.

The orders are PRIVATE orders (pay.F_PRIVATE, salted): they store no repository and no issue, so a graduation never
shows up as a bounty on a GitHub issue that does not exist. The salt is sha256("knos-grad:" + claim id): derived from
the public claim id on purpose, so anyone can find a claim's vault and pool on chain (`pool`). The judge is the
research repository (judge_repo_id), whose prove.yml asks GitHub to sign the pay token.

No token here pays backers from revenue: a pre-order buys the product, and a funder of the milestone vault gets the
milestone delivered or the money back. A revenue-sharing token is a founder decision (securities law).

Pure builders and readers, no network: `ledger` is knos.chain.Ledger or the tests' LiteSVM stand-in. Every step
can be written to Knos Record (knos.record.append) when it is installed.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from solders.instruction import Instruction
from solders.pubkey import Pubkey

from .. import splits
from ..money import fees_config
from ..settle.v2 import pay

SALT_TAG = b"knos-grad:"
POOL_ISSUE = 0                         # the pool's scope; a milestone's vault is in the scope of its number (1, 2, ...)
DAY = 86_400
ESCROW_WORK = 30 * DAY                 # default: the milestone must be delivered within 30 days, else the funder is refunded
POOL_WORK = 90 * DAY                   # default: pre-orders wait 90 days for delivery
JUDGE_WF_REPO = "drexthealpha/Knos"    # the workflows whose signed run pays: the claim workflow pin of program_ids.json
TERMS_V = 1


class GraduationError(ValueError):
    pass


def salt(claim_id: str) -> bytes:
    if not isinstance(claim_id, str) or not 1 <= len(claim_id) <= 200 or not claim_id.isprintable():
        raise GraduationError("claim_id: printable text, 1 to 200 characters")
    return hashlib.sha256(SALT_TAG + claim_id.encode()).digest()


def scope(claim_id: str, repo_id: int, milestone: int = POOL_ISSUE) -> bytes:
    """The order scope of a claim's milestone vault (milestone >= 1) or of its pre-order pool (0)."""
    return pay.scope_of(repo_id, milestone, salt(claim_id))


def options(repo_id: int) -> bytes:
    return pay.opts(pay.F_PRIVATE, judge_repo_id=repo_id, salted=True)


def terms(kind: str, claim_id: str, spec_hash: str, milestone: int, shares: list[tuple[str, int]]) -> bytes:
    """The terms an order of the graduation is funded on (their sha256 is what the private order stores): which claim,
    which sealed spec, which milestone, and the split the judge must pay."""
    return pay.terms_json({"v": TERMS_V, "kind": kind, "claim": claim_id, "spec_hash": spec_hash, "milestone": milestone,
                           "split": {r: b for r, b in shares}})


# == a SIGNED verdict (0.3.34): what the MCP tool knos_graduate requires ==============================================
# The verdict object may carry `signed`: {"message": hex, "signatures": [[key, sig hex], ...], "m": int, "keys": [key, ...]}
# (keys as base58 or hex). The message is knos.platform.verdict.message(job, evidence, "PASS", 0, recipient, expiry,
# nonce) with job = graduation_job(claim_id) and evidence = graduation_evidence(spec_hash): m distinct keys of a panel
# drawn from Knos's referee registry (config/referees.yaml) signed that THIS claim's THIS spec passed. `unlisted_panel`:
# true in the verdict object to use keys outside the registry (the answer then says UNLISTED PANEL).


def graduation_job(claim_id: str) -> bytes:
    return hashlib.sha256(b"knos3:graduate:" + claim_id.encode()).digest()


def graduation_evidence(spec_hash: str) -> bytes:
    return hashlib.sha256(b"knos3:spec:" + spec_hash.encode()).digest()


def graduation_message(claim_id: str, spec_hash: str, expiry: int, nonce: int = 0, recipient: bytes = bytes(32)) -> bytes:
    """What each referee signs to say a claim graduates (knos.platform.verdict layout)."""
    from ..platform import verdict as V
    return V.message(graduation_job(claim_id), graduation_evidence(spec_hash), "PASS", 0, recipient, expiry, nonce)


def _key32(k) -> bytes:
    if isinstance(k, str) and len(k) == 64:
        return bytes.fromhex(k)
    return bytes(Pubkey.from_string(str(k)))


def signed_verdict(verdict: Any, claim_id: str, *, funder: str | None = None, now: int | None = None) -> str:
    """'' when `verdict` carries m valid signatures of a registry panel over this claim's and spec's PASS, the UNLISTED
    PANEL label when it does with unlisted_panel=true; GraduationError otherwise (an unsigned "passed" is refused)."""
    import time
    from ..platform import referees, verdict as V
    if not isinstance(verdict, dict) or verdict.get("passed") is not True:
        raise GraduationError("only a verdict that passed (works, wanted and makeable) graduates")
    sv = verdict.get("signed")
    if not isinstance(sv, dict):
        raise GraduationError("the verdict is not signed: knos_graduate needs m of n signatures of Knos's referee panel "
                              "(config/referees.yaml) over graduation_message(claim_id, spec_hash, ...)")
    try:
        msg = bytes.fromhex(str(sv["message"]))
        sigs = [(_key32(k), bytes.fromhex(str(s))) for k, s in sv["signatures"]]
        keys = [_key32(k) for k in sv["keys"]]
        m = int(sv["m"])
        f = V.parse(msg)
    except (KeyError, TypeError, ValueError) as why:
        raise GraduationError(f"the signed verdict is malformed: {why}") from None
    spec_hash = verdict.get("spec_hash")
    if not isinstance(spec_hash, str) or f["job"] != graduation_job(claim_id) or f["evidence_hash"] != graduation_evidence(spec_hash):
        raise GraduationError("the signed verdict is for another claim or another spec")
    if f["verdict"] != "PASS":
        raise GraduationError("the signed verdict is FAIL")
    if not 1 <= m <= len(keys):
        raise GraduationError("m: from 1 to the number of panel keys")
    unlisted = verdict.get("unlisted_panel") is True
    try:
        label = referees.panel_rule(keys, funder=funder, unlisted_panel=True if unlisted else False)
    except referees.PanelError as why:
        raise GraduationError(f"panel: {why}") from None
    ok, reason = V.check(msg, sigs, keys, m, now=int(time.time()) if now is None else now, used=set(), record=False,
                         unlisted_panel=True)
    if not ok:
        raise GraduationError(f"the signed verdict does not hold: {reason}")
    return label


def _int(v: Any, name: str, low: int, high: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not low <= v <= high:
        raise GraduationError(f"{name}: a whole number from {low:,} to {high:,}")
    return v


def plan(verdict: dict, *, claim_id: str, repo_id: int, amount: int, contributors: list[dict], milestone: int = 1,
         work_s: int = ESCROW_WORK, pool_work_s: int = POOL_WORK, min_buyers: int = 1, min_locked: int = 0,
         wf_repo: str = JUDGE_WF_REPO, wf_sha: str | None = None, cfg: fees_config.FeeConfig | None = None) -> dict:
    """What graduating this claim opens: refused unless the verdict passed all three checks. `amount`: what the
    milestone vault holds for the contributors (base units of a 6-decimal mint). Nothing is sent."""
    cfg = cfg or fees_config.load()
    if not isinstance(verdict, dict) or verdict.get("passed") is not True:
        raise GraduationError("only a verdict that passed (works, wanted and makeable) graduates")
    spec_hash = verdict.get("spec_hash")
    if not isinstance(spec_hash, str) or not spec_hash:
        raise GraduationError("the verdict names no spec_hash")
    _int(repo_id, "repo_id", 1, 2 ** 63)
    _int(milestone, "milestone", 1, 2 ** 32)
    _int(amount, "amount", pay.units(pay.ORDER_MIN_AMOUNT), pay.units(pay.MAX_AMOUNT))
    _int(work_s, "work_s", pay.MIN_WORK, pay.MAX_WORK)
    _int(pool_work_s, "pool_work_s", pay.MIN_WORK, pay.MAX_WORK)
    try:
        ps = splits.payees(contributors, cfg)
        split = splits.amounts(amount, contributors, cfg)
    except splits.SplitError as why:
        raise GraduationError(str(why)) from None
    shares = [(role, bps) for (role, _gid, _a), (_i, bps, _w) in zip(split, ps)]
    wf_sha = wf_sha or pay.IDS["claim_sha"]
    e_terms = terms("milestone", claim_id, spec_hash, milestone, shares)
    p_terms = terms("preorder", claim_id, spec_hash, 0, shares)
    fee = cfg.fee("payout", amount)
    return {
        "claim_id": claim_id, "repo_id": repo_id, "spec_hash": spec_hash, "milestone": milestone, "wf_repo": wf_repo, "wf_sha": wf_sha,
        "program": str(pay.PAY_ID), "mode": pay.MERGE, "options": options(repo_id).hex(),
        "escrow": {"scope": scope(claim_id, repo_id, milestone).hex(), "terms": e_terms.decode(), "terms_hash": pay.terms_hash(e_terms).hex(),
                   "amount": amount, "payout_fee": fee, "funder_pays": amount + fee, "work_s": work_s,
                   "graduation_fee": cfg.fee("graduation", amount), "graduation_fee_status": cfg.doc["fees"]["graduation"]["status"]},
        "pool": {"scope": scope(claim_id, repo_id, POOL_ISSUE).hex(), "terms": p_terms.decode(), "terms_hash": pay.terms_hash(p_terms).hex(),
                 "work_s": pool_work_s, "min_buyers": min_buyers, "min_locked": min_locked},
        "payees": [(i, b, None if a is None else str(a)) for i, b, a in ps],
        "split": [{"role": r, "github_id": g, "amount": a} for r, g, a in split],
        "split_status": cfg.doc["splits"]["status"],
    }


def _fund(p: dict, part: str, wallet: Pubkey, token: Pubkey, mint: Pubkey, amount: int, seq: int, token_program: Pubkey, work_s: int) -> Instruction:
    return pay.fund_order_wallet_ix(wallet, token, mint, 0, 0, amount, p["wf_repo"], p["wf_sha"], bytes.fromhex(p[part]["terms_hash"]),
                                    mode=p["mode"], work_s=work_s, seq=seq, options=bytes.fromhex(p["options"]),
                                    scope=bytes.fromhex(p[part]["scope"]), token_program=token_program, program=Pubkey.from_string(p["program"]))


def escrow_ix(p: dict, funder: Pubkey, funder_token: Pubkey, mint: Pubkey, seq: int = 0, token_program: Pubkey = pay.TOKEN) -> Instruction:
    """FundOrderWallet of the milestone vault: `funder` signs; the amount and the payout fee leave `funder_token`."""
    return _fund(p, "escrow", funder, funder_token, mint, p["escrow"]["amount"], seq, token_program, p["escrow"]["work_s"])


def preorder_ix(p: dict, buyer: Pubkey, buyer_token: Pubkey, mint: Pubkey, amount: int, seq: int = 0, token_program: Pubkey = pay.TOKEN) -> Instruction:
    """FundOrderWallet of one pre-order in the claim's pool: `buyer` signs; `amount` plus the payout fee leave `buyer_token`."""
    _int(amount, "amount", pay.units(pay.ORDER_MIN_AMOUNT), pay.units(pay.MAX_AMOUNT))
    return _fund(p, "pool", buyer, buyer_token, mint, amount, seq, token_program, p["pool"]["work_s"])


def address(p: dict, part: str, source: Pubkey, seq: int = 0) -> Pubkey:
    """The order a wallet funds in the vault (`"escrow"`) or the pool ("pool")."""
    return pay.order_pda(bytes.fromhex(p[part]["scope"]), source, seq, Pubkey.from_string(p["program"]))


def refund_ix(relayer: Pubkey, order: Pubkey, o: pay.Order, program: Pubkey | None = None) -> Instruction:
    """RefundOrder: anyone may send it once the order is past its deadline; everything goes back to the funder."""
    return pay.refund_order_ix(relayer, order, o, program=program or pay.PAY_ID)


def pay_audience(p: dict, part: str, order: Pubkey, head_sha: str, pr: int, payees: list | None = None) -> str:
    """What the judge's prove.yml (in the research repository) asks GitHub to sign to pay `order` (of the vault or
    the pool) to the contributor split."""
    ps = payees if payees is not None else [(i, b, None if a is None else Pubkey.from_string(a)) for i, b, a in p["payees"]]
    return pay.order_pay_audience(order, head_sha, bytes.fromhex(p[part]["terms_hash"]), p["mode"], pr, ps)


def orders(ledger, scope_bytes: bytes, program: Pubkey | None = None) -> list[tuple[Pubkey, pay.Order]]:
    """Every knos_pay order in a scope, read from the chain (one getProgramAccounts filtered by size and scope)."""
    got = ledger.program_accounts(program or pay.PAY_ID, size=pay.ORDER_LEN, memcmp={24: scope_bytes})
    out = []
    for addr, data in got:
        o = pay.read_order(bytes(data))
        if o is not None and o.scope == scope_bytes:
            out.append((addr, o))
    return sorted(out, key=lambda x: str(x[0]))


def mismatch(p: dict, part: str, o: pay.Order, mint: str) -> str | None:
    """Why an order found in the plan's scope is not one of its orders, or None. The scope alone proves nothing:
    anyone can fund a private order in a public scope, with any mint (a worthless one included), any terms, any judge
    and any workflow pin. So an order counts only when it is the plan's: its terms hash, mode, judge repository,
    pinned workflows, private flag, no holdback and not standing, and the mint the caller accepts."""
    if o.terms.hex() != p[part]["terms_hash"] or o.mode != p["mode"]:
        return "other terms"
    if not o.flags & pay.F_PRIVATE or o.flags & pay.F_STANDING or o.holdback_bps or o.judge_repo_id != p["repo_id"]:
        return "another kind of order or another judge"
    if o.wf_repo_hash != pay.wf_repo_hash(p["wf_repo"]) or o.wf_sha != p["wf_sha"]:
        return "other pinned workflows"
    if str(o.mint) != mint:
        return f"mint {o.mint}, not {mint}"
    return None


def _summary(p: dict, part: str, found: list[tuple[Pubkey, pay.Order]], now: int | None, mint: str) -> dict:
    rows, ignored = [], []
    for a, o in found:
        why = mismatch(p, part, o, mint)
        if why is not None:
            ignored.append({"order": str(a), "why": why})
            continue
        rows.append({"order": str(a), "source": str(o.source), "amount": o.amount, "fee": o.fee, "state": o.state, "deadline": o.deadline,
                     "mint": str(o.mint), "past_deadline": None if now is None else now > o.pay_until})
    live = [r for r in rows if r["state"] == "open" and not r["past_deadline"]]
    return {"mint": mint, "orders": rows, "ignored": ignored, "buyers": len({r["source"] for r in live}),
            "locked": sum(r["amount"] for r in live), "fees_held": sum(r["fee"] for r in live)}


def pool(ledger, p: dict, mint: str) -> dict:
    """The claim's pre-order pool as the chain has it now, counting only the plan's own orders in `mint` (the mint the
    makers accept: demand in another mint, or on other terms, is listed under `ignored` and never counted): the
    distinct buyers and the amount locked in open orders still inside their time, and whether the bar is met."""
    now = ledger.now() if hasattr(ledger, "now") else None
    s = _summary(p, "pool", orders(ledger, bytes.fromhex(p["pool"]["scope"]), Pubkey.from_string(p["program"])), now, str(mint))
    s["bar"] = {"min_buyers": p["pool"]["min_buyers"], "min_locked": p["pool"]["min_locked"],
                "met": s["buyers"] >= p["pool"]["min_buyers"] and s["locked"] >= p["pool"]["min_locked"]}
    return s


def escrow(ledger, p: dict, mint: str) -> dict:
    """The milestone vault's orders in `mint`, counted as `pool` counts them."""
    now = ledger.now() if hasattr(ledger, "now") else None
    return _summary(p, "escrow", orders(ledger, bytes.fromhex(p["escrow"]["scope"]), Pubkey.from_string(p["program"])), now, str(mint))


def demand_orders(p: dict, pool_state: dict, currency: str = "USDC") -> list[dict]:
    """The pool's open orders in the shape knos.referee's DemandBook and referee.wanted count: one per order, its
    buyer, amount (base units) and vault reference (the order's address), status "locked"."""
    return [{"spec_hash": p["spec_hash"], "buyer": r["source"], "amount": r["amount"], "escrow_ref": r["order"], "status": "locked",
             "currency": currency} for r in pool_state["orders"] if r["state"] == "open" and not r["past_deadline"]]


def record(kind: str, p: dict, payload: dict, root=None) -> dict | None:
    """One Knos Record entry (graduation, funding, split, payout, refund) for this claim, when knos.record is
    installed; None when it is not. Only public fields: amounts, addresses, signatures, hashes."""
    try:
        from .. import record as rec  # type: ignore[attr-defined]
    except ImportError:
        return None
    body = {"spec_hash": p["spec_hash"], "cluster": "devnet", **payload}
    return rec.append(kind, json.loads(json.dumps(body, default=str)), claim=p["claim_id"], root=root)
