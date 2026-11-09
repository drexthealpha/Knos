"""Bounties mode of Knos Gate: an issue funded in vault is paid to the first pull request that passes the hidden tests
AND is merged by the maintainer; a claim that fails Gate is closed.

The money is not new code. A bounty is a knos_pay vault on Solana devnet (`knos fund-wallet OWNER/REPO#N AMOUNT`, or
`/knos fund` on the issue): a job of the repository's own prove.yml, or a work order. It is paid by the program when a
GitHub-signed run of the pinned workflow says the merged pull request met the terms (knos_oidc); Gate never signs a
payment and holds no key. What Gate adds:

    claims(pull)          the issues a pull request says it closes ("Fixes #12", "closes #12", "resolves: #12")
    must_close(...)       bounties mode: a claim that fails Gate is closed, whatever on_fail says (spam claims)
    winner(...)           the first merged claim whose Gate verdict at its merged head passed
    quote(amount, kind)   the fee and where it goes, from the ONE fee config (config/fees.yaml through
                          knos.money.fees_config, MONEY's API); with that package missing, the program's own compiled
                          numbers (knos.settle.v2.pay), and the quote says which it used
    treasury(mint, ...)   the fee's destination: a token account of FEE_OWNER, Knos's Squads vault (a program-derived
                          address of the Squads program), for that mint

Fiat on-ramps and off-ramps are a founder decision (docs/reference/REFEREE.md)."""
from __future__ import annotations

import re

CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)\b", re.I)


def claims(pull: dict) -> list[int]:
    text = f"{pull.get('title') or ''}\n{pull.get('body') or ''}"
    return sorted({int(n) for n in CLOSES.findall(text)})


def must_close(cfg: dict, pull: dict, verdict: dict) -> bool:
    return bool((cfg.get("bounties") or {}).get("enabled")) and bool(claims(pull)) and not verdict.get("passed")


def winner(issue: int, pulls: list[dict], verdicts: dict) -> dict | None:
    """pulls: GitHub's pull objects; verdicts: {pr number: Gate verdict}. A verdict counts only at the pull request's
    merged head commit."""
    merged = [p for p in pulls if p.get("merged_at") and issue in claims(p)]
    for p in sorted(merged, key=lambda p: p["merged_at"]):
        v = verdicts.get(p["number"])
        if v and v.get("passed") and v.get("head") == (p.get("head") or {}).get("sha"):
            return p
    return None


def quote(amount: int, kind: str = "job", decimals: int = 6) -> dict:
    """The fee of a bounty of `amount` (smallest units). kind "job" (a repository's own prove.yml pays it: the fee comes
    out of the amount) or "order" (a work order: the funder pays the fee on top)."""
    from ..settle.v2 import pay
    source = "config/fees.yaml (knos.money.fees_config, key bounty)"
    try:
        from ..money import fees_config  # type: ignore[attr-defined]
        got = fees_config.load().bounty(amount)
        fee = int(got["fee"])
    except (ImportError, AttributeError):
        fee, source = pay.order_fee(amount, pay.FEE_BPS, decimals), "knos_pay's compiled FEE_BPS and FEE_MIN (knos.money is not installed)"
    if kind == "job":
        fee = min(fee, amount)
        return {"amount": amount, "fee": fee, "payee_gets": amount - fee, "funder_pays": amount, "fee_to": "treasury",
                "treasury_owner": str(pay.FEE_OWNER), "source": source, "kind": kind}
    return {"amount": amount, "fee": fee, "payee_gets": amount, "funder_pays": amount + fee, "fee_to": "treasury",
            "treasury_owner": str(pay.FEE_OWNER), "source": source, "kind": kind}


def treasury(mint: str, escrow: str | None = None) -> dict:
    """Where a bounty's fee lands for `mint`: the fee account of FEE_OWNER (Knos's Squads vault PDA) that knos_pay
    writes for this vault account (`pay.fee_account_for`), and account 0 (the associated one)."""
    from solders.pubkey import Pubkey

    from ..settle.v2 import pay
    m = Pubkey.from_string(mint)
    first = pay.fee_accounts(m, pay.TOKEN, 1, None)[0]
    out = {"fee_owner": str(pay.FEE_OWNER), "squads_program": "SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf",
           "fee_account_0": str(first), "mint": mint}
    if escrow:
        out["fee_account"] = str(pay.fee_account_for(Pubkey.from_string(escrow), m))
    return out
