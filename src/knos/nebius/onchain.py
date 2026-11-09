"""The devnet legs of the Knos x Nebius flow, each timed from send to FINALIZED ("paid and final in N ms").

    Devnet.load(dir)                 the team's wallet (buyer), the agent's wallet (worker) and the team's test mint, from
                                     key files in `dir` (team.json, agent.json, mint.json); a key is never printed
    devnet.`fund_escrow`(...)          knos_pay FundWallet: the team's bounty into vault, terms fixed (seal hash inside)
    devnet.pay_check(...)            x402 v2 `exact`: the agent pays one raw check (0.02) to Knos's treasury through the
                                     public x402.org facilitator (no key; the facilitator pays the network fee)
    final_ms(url, sig, t0)           polls getSignatureStatuses until finalized: (confirmed ms, finalized ms) after t0
    alpenglow(url)                   getAgGenesisCert: a certificate = Alpenglow; null or "Method not found" = TowerBFT

Devnet only; the test mint is the team's own (synthetic test units). The payout leg needs a GitHub Actions OIDC token
from a signed run of a pinned prove.yml (knos.settle.v2.pay), so it is not here: knos.nebius.payout replays the same
job in LiteSVM and says so.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .. import chain
from ..settle.v2 import pay

if TYPE_CHECKING:
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey

RPC_ENV = "KNOS_RPC"


def rpc_url() -> str:
    return os.environ.get(RPC_ENV) or chain.CLUSTERS["devnet"]


def final_ms(url: str, sig: str, t0: float, within: float = 90.0) -> dict:
    """Milliseconds from t0 (perf_counter before the send) to the first status read at confirmed and at finalized."""
    out: dict = {"confirmed_ms": None, "finalized_ms": None, "err": None}
    end = t0 + within
    while time.perf_counter() < end:
        st = chain.call(url, "getSignatureStatuses", [[sig], {"searchTransactionHistory": False}])["value"][0]
        if st:
            out["err"] = st.get("err")
            ms = int((time.perf_counter() - t0) * 1000)
            if st.get("confirmationStatus") in ("confirmed", "finalized") and out["confirmed_ms"] is None:
                out["confirmed_ms"] = ms
            if st.get("confirmationStatus") == "finalized":
                out["finalized_ms"] = ms
                return out
        time.sleep(0.15)
    return out


def alpenglow(url: str) -> dict:
    try:
        got = chain.call(url, "getAgGenesisCert", [])
    except Exception as why:  # noqa: BLE001 - "Method not found" (-32601) on an RPC that predates it: TowerBFT
        return {"consensus": "towerbft", "why": str(why)[:120]}
    return {"consensus": "alpenglow" if got else "towerbft", "why": "getAgGenesisCert returned " + ("a certificate" if got else "null")}


def _kp(path: Path):
    from solders.keypair import Keypair
    return Keypair.from_bytes(bytes(json.loads(path.read_text(encoding="utf-8"))))


@dataclass
class Devnet:
    team: Keypair           # the buyer
    agent: Keypair          # the worker
    mint: Pubkey            # the team's test mint
    decimals: int = 6
    url: str = ""

    @classmethod
    def load(cls, wallets: Path, url: str | None = None) -> "Devnet":
        w = Path(wallets)
        mint = _kp(w / "mint.json").pubkey() if (w / "mint.json").is_file() else None
        if mint is None:
            from solders.pubkey import Pubkey
            mint = Pubkey.from_string((w / "mint.txt").read_text().strip())
        return cls(_kp(w / "team.json"), _kp(w / "agent.json"), mint, 6, url or rpc_url())

    def _send_timed(self, ixs, payer, signers=None) -> dict:
        from solders.hash import Hash
        bh = Hash.from_string(chain.call(self.url, "getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])
        tx = chain.sign(list(ixs), payer, signers, bh)
        import base64
        raw = base64.b64encode(bytes(tx)).decode()
        t0 = time.perf_counter()
        sig = chain.call(self.url, "sendTransaction", [raw, {"encoding": "base64", "preflightCommitment": "confirmed"}])
        return {"sig": sig, **final_ms(self.url, sig, t0)}

    def fund_escrow(self, *, repo_id: int, issue: int, amount: int, wf_repo: str, wf_sha: str, terms: bytes,
                    work_s: int = 86_400) -> dict:
        """The team's bounty into knos_pay vault, plus (idempotent) the treasury's token account of the mint, which the
        x402 check pays into."""
        me = self.team.pubkey()
        ixs = [pay.create_ata_ix(me, pay.FEE_OWNER, self.mint),
               pay.fund_wallet_ix(me, pay.ata(me, self.mint), self.mint, repo_id, issue, amount, wf_repo, wf_sha, terms, pay.MERGE, work_s)]
        got = self._send_timed(ixs, self.team)
        return {**got, "job": str(pay.job_pda(repo_id, issue, me)), "program": str(pay.PAY_ID), "amount_units": amount,
                "mint": str(self.mint), "network": "devnet"}

    def pay_check(self, amount: int, memo: str) -> dict:
        """One raw agent check over x402 exact: the agent signs, the facilitator verifies, pays the fee and lands it."""
        from solders.hash import Hash

        from ..money import x402_exact as X
        f = X.Facilitator()
        fp = f.fee_payer()
        if not fp:
            return {"paid": False, "why": "the facilitator lists no exact fee payer for solana devnet", "network": "devnet"}
        req = X.requirement(amount, str(self.mint), str(pay.FEE_OWNER), fp, memo=memo)
        bh = Hash.from_string(chain.call(self.url, "getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])
        p = X.payment(req, self.agent, bh, decimals=self.decimals,
                      resource={"url": "https://drexthealpha.github.io/Knos/checks", "description": "one Knos referee check", "mimeType": "application/json"})
        t0 = time.perf_counter()
        try:
            s = f.verify_and_settle(p, req, confirm=X.confirm_on(self.url))
        except X.Refused as why:
            return {"paid": False, "why": str(why), "network": "devnet", "facilitator": f.url}
        sig = s.get("transaction")
        timing = final_ms(self.url, sig, t0) if sig else {}
        return {"paid": True, "sig": sig, **timing, "amount_units": amount, "mint": str(self.mint), "pay_to": str(pay.FEE_OWNER),
                "facilitator": f.url, "network": "devnet", "confirmed_by": s.get("confirmedBy", "facilitator")}
