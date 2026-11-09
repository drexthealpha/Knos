"""The lab vault: two pots per lab order, released by the two verdicts.

    lab pot       the lab's price + the Knos lab order fee (config/fees.yaml `fees.lab_order`, decided 14 Oct 2026: 3%)
                  LAB PASS  -> the price to the lab, the fee to the Knos treasury (even if the science failed)
                  LAB FAIL  -> everything back to the funder (no fee is taken on a refund)
    outcome pot   the researcher's reward
                  OUTCOME PASS -> the reward to the researcher (and the claim may graduate: knos.graduation)
                  OUTCOME FAIL or VOID -> the reward back to the funder

`settlement(lab, outcome)` is the pure decision: which transfers the two verdicts allow. It never looks at who
asked; only at the verdicts.

On devnet today the pots are SPL token accounts whose owner is an SPL Token MULTISIG of the referee keys (m of n):
no single key, the funder's included, can move them; a release is a token transfer that m referees co-sign, in one
transaction with a Memo carrying the signed verdict's digest, so the chain binds each release to its verdict. What
it does NOT do on chain: read the verdict's fields or refund by itself after a deadline (the referees sign the
refund). knos_pay's verdict release path (an m-of-n referee verdict checked by the ed25519 precompile, with expiry and
replay protection on chain) is the production path; when it is deployed the same verdict messages
(knos.labs.verdicts.message) release a knos_pay order instead. The fee then follows knos_pay (0.30% on chain, the rest
of the 3% invoiced: `cfg.platform("lab_order", amount)`).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..money import fees_config
from .verdicts import FAIL, PASS, VOID, Verdict

TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
MEMO = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
MULTISIG_LEN = 355
ACCOUNT_LEN = 165
MINT_LEN = 82


class EscrowError(ValueError):
    pass


@dataclass
class Plan:
    order: str                   # the Knos lab order id (also in every verdict)
    field: str
    price: int                   # the lab's price, base units of a 6-decimal mint
    fee: int                     # the Knos lab order fee on the price
    reward: int                  # the researcher's reward
    fee_rate_bps: int
    fee_status: str
    fee_bearer: str = "funder, on top of the price"

    @property
    def lab_pot(self) -> int:
        return self.price + self.fee

    def to_dict(self) -> dict:
        return {"order": self.order, "field": self.field, "price": self.price, "fee": self.fee, "reward": self.reward,
                "lab_pot": self.lab_pot, "outcome_pot": self.reward, "fee_rate_bps": self.fee_rate_bps,
                "fee_status": self.fee_status, "fee_bearer": self.fee_bearer, "fee_line": "config/fees.yaml fees.lab_order"}


def plan(order: str, field: str, price: int, reward: int, cfg: fees_config.FeeConfig | None = None) -> Plan:
    cfg = cfg or fees_config.load()
    for name, v in (("price", price), ("reward", reward)):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise EscrowError(f"{name}: base units, a whole number from 0")
    if price == 0:
        raise EscrowError("a lab order has a price")
    line = cfg.doc["fees"]["lab_order"]
    return Plan(order, field, price, cfg.fee("lab_order", price), reward, line["rate_bps"], line["status"])


def settlement(p: Plan, lab: Verdict, outcome: Verdict | None) -> list[dict]:
    """The transfers the verdicts allow: [{"pot", "to" (lab | treasury | researcher | funder), "amount", "why"}]."""
    if lab.kind != "lab" or lab.verdict not in (PASS, FAIL):
        raise EscrowError("the first verdict is a LAB verdict, PASS or FAIL")
    out = []
    if lab.passed:
        out.append({"pot": "lab", "to": "lab", "amount": p.price, "why": "LAB PASS: protocol executed and QC passed"})
        if p.fee:
            out.append({"pot": "lab", "to": "treasury", "amount": p.fee, "why": f"the Knos lab order fee ({p.fee_rate_bps} bps, {p.fee_status})"})
    else:
        out.append({"pot": "lab", "to": "funder", "amount": p.lab_pot, "why": "LAB FAIL: refund, no fee"})
    if p.reward:
        if outcome is None:
            raise EscrowError("the outcome pot needs the OUTCOME verdict (or VOID)")
        if outcome.kind != "outcome" or outcome.verdict not in (PASS, FAIL, VOID):
            raise EscrowError("the second verdict is an OUTCOME verdict")
        if outcome.evidence_hash != lab.evidence_hash:
            raise EscrowError("the two verdicts were given on different evidence")
        if outcome.passed and not lab.passed:
            raise EscrowError("an OUTCOME PASS needs a LAB PASS")
        if outcome.passed:
            out.append({"pot": "outcome", "to": "researcher", "amount": p.reward, "why": "OUTCOME PASS: the claim held"})
        else:
            out.append({"pot": "outcome", "to": "funder", "amount": p.reward,
                        "why": f"OUTCOME {outcome.verdict}: the claim did not hold; the researcher is not paid"})
    return out


# ---- SPL Token instructions (multisig-owned pots) -------------------------------------------------------------------

def _pk(x):
    from solders.pubkey import Pubkey
    return x if isinstance(x, Pubkey) else Pubkey.from_string(str(x))


def init_multisig_ix(multisig, signers: list, m: int):
    """InitializeMultisig2 (SPL Token instruction 19): m of the listed signers (1 to 11)."""
    from solders.instruction import AccountMeta, Instruction
    if not 1 <= m <= len(signers) <= 11:
        raise EscrowError("a multisig is m of n, 1 <= m <= n <= 11")
    return Instruction(_pk(TOKEN), bytes([19, m]), [AccountMeta(_pk(multisig), False, True)] +
                       [AccountMeta(_pk(s), False, False) for s in signers])


def init_account_ix(account, mint, owner):
    """InitializeAccount3 (SPL Token instruction 18): a token account of `mint` owned by `owner` (the multisig)."""
    from solders.instruction import AccountMeta, Instruction
    return Instruction(_pk(TOKEN), bytes([18]) + bytes(_pk(owner)), [AccountMeta(_pk(account), False, True), AccountMeta(_pk(mint), False, False)])


def transfer_checked_ix(source, mint, dest, owner, amount: int, decimals: int, cosigners: list | None = None):
    """TransferChecked (12). With `cosigners`, `owner` is a multisig and the cosigners sign (m of them)."""
    from solders.instruction import AccountMeta, Instruction
    metas = [AccountMeta(_pk(source), False, True), AccountMeta(_pk(mint), False, False), AccountMeta(_pk(dest), False, True),
             AccountMeta(_pk(owner), not cosigners, False)]
    metas += [AccountMeta(_pk(s), True, False) for s in (cosigners or [])]
    return Instruction(_pk(TOKEN), bytes([12]) + int(amount).to_bytes(8, "little") + bytes([decimals]), metas)


def close_account_ix(account, dest, owner, cosigners: list | None = None):
    """CloseAccount (9): an emptied pot's rent back to `dest`; a multisig owner needs its cosigners."""
    from solders.instruction import AccountMeta, Instruction
    metas = [AccountMeta(_pk(account), False, True), AccountMeta(_pk(dest), False, True), AccountMeta(_pk(owner), not cosigners, False)]
    metas += [AccountMeta(_pk(s), True, False) for s in (cosigners or [])]
    return Instruction(_pk(TOKEN), bytes([9]), metas)


def memo_ix(text: str):
    from solders.instruction import Instruction
    return Instruction(_pk(MEMO), text.encode("utf-8"), [])


def read_token_amount(data: bytes | None) -> int | None:
    """The amount of an SPL token account (bytes 64..72), None when there is no account."""
    if data is None or len(data) < 72:
        return None
    return int.from_bytes(bytes(data)[64:72], "little")


def read_multisig(data: bytes | None) -> dict | None:
    """{m, n, initialized, signers} of an SPL Token multisig account."""
    if data is None or len(data) < MULTISIG_LEN:
        return None
    from solders.pubkey import Pubkey
    raw = bytes(data)
    m, n, init = raw[0], raw[1], raw[2] == 1
    return {"m": m, "n": n, "initialized": init, "signers": [str(Pubkey.from_bytes(raw[3 + 32 * i: 35 + 32 * i])) for i in range(n)]}
