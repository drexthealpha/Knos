"""Test harness for the jobs market: the escrow in the Solana runtime (knos.jobs.localsvm.Escrow) behind the same
interface as a real cluster (knos.jobs.ledger.Ledger), plus clock control. Tests only; the product talks to devnet."""

from __future__ import annotations

from dataclasses import dataclass, field

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from knos.jobs import localsvm, sol


class Escrow(localsvm.Escrow):
    def warp(self, seconds: int) -> None:
        c = self.svm.get_clock()
        c.unix_timestamp = c.unix_timestamp + seconds
        self.svm.set_clock(c)


@dataclass
class LocalLedger:
    """The escrow inside LiteSVM (knos.jobs.localsvm.Escrow), behind the same interface."""
    env: object
    program: Pubkey = field(init=False)
    network: str = "localnet"

    def __post_init__(self):
        self.program = self.env.pid

    def send(self, ixs, payer: Keypair, signers: list[Keypair] | None = None) -> str:
        everyone = {bytes(k.pubkey()): k for k in [payer, *(signers or [])]}
        if not self.env.send(list(ixs), payer, list(everyone.values())):
            raise RuntimeError("transaction failed")
        return "local"

    def account(self, address: Pubkey) -> bytes | None:
        acc = self.env.svm.get_account(address)
        return bytes(acc.data) if acc is not None else None

    def jobs(self, state: str | None = None) -> list[sol.Job]:
        from knos.jobs import market
        out = []
        for jid in getattr(self.env, "known_jobs", []):
            got = self.env.job(jid) or market._SETTLED.get(sol.job_pda(self.program, jid))   # settled: closed
            if got and (state is None or got.state == state):
                out.append(got)
        return out

    def blockhash(self):
        return self.env.svm.latest_blockhash()

    def now(self) -> int:
        return int(self.env.svm.get_clock().unix_timestamp)

    def config(self) -> dict:
        return sol.parse_config(self.account(sol.config_pda(self.program)))
