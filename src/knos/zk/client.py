"""The knos_zk program from Python: its instructions, its verdict account, and the rule a payout reads off it.

  verify_ix(program, proof, inputs)          instruction 0: the transaction fails unless the proof verifies
  record_ix(program, payer, proof, inputs)   instruction 1: verifies, then writes the verdict PDA
  verdict_address(program, inputs)           ["verdict", spec_hash, pred_hash, threshold (2 bytes)]
  parse_verdict(data) / payable(...)         what a payout checks before it pays
  send(url, payer, ixs)                      one devnet transaction; returns its signature and compute units

The layouts are the program's (programs-v2/knos_zk/src/lib.rs). Nothing here signs with any key but the one passed.
"""

from __future__ import annotations

from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from .bn254 import R
from .groth16 import Proof

SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")
VERDICT_SEED = b"verdict"
VERDICT_LEN = 138
NR_INPUTS = 3
ERRORS = {0: "bad instruction data", 1: "proof refused", 2: "wrong verdict address", 3: "verdict already recorded",
          4: "wrong system program"}

# The program id reserved for the devnet deployment (its keypair is in the build's own devnet wallet, not a Knos key).
# Deployed on devnet on 14 Oct 2026 (transaction 5Y7hVQqk...); its runs are read back in zk/fixtures/score64/devnet.json
# (zk/devnet_read.py). TOY verifying key.
DEVNET_PROGRAM_ID = "5M67Aqw1JHNSVrhFxCSzTmewdpysRKDtBKkTLrb192bk"


def inputs_bytes(inputs: list[int]) -> bytes:
    if len(inputs) != NR_INPUTS or any(not 0 <= x < R for x in inputs):
        raise ValueError(f"{NR_INPUTS} public inputs, each below the BN254 group order")
    return b"".join(x.to_bytes(32, "big") for x in inputs)


def body(proof: Proof, inputs: list[int]) -> bytes:
    """A_neg | B | C | inputs: 352 bytes"""
    return proof.a_negated() + proof.b + proof.c + inputs_bytes(inputs)


def verify_ix(program: Pubkey, proof: Proof, inputs: list[int]) -> Instruction:
    return Instruction(program, b"\x00" + body(proof, inputs), [])


def verdict_address(program: Pubkey, inputs: list[int]) -> tuple[Pubkey, int]:
    raw = inputs_bytes(inputs)
    return Pubkey.find_program_address([VERDICT_SEED, raw[:32], raw[32:64], raw[94:96]], program)


def record_ix(program: Pubkey, payer: Pubkey, proof: Proof, inputs: list[int]) -> Instruction:
    verdict, bump = verdict_address(program, inputs)
    return Instruction(
        program,
        bytes([1, bump]) + body(proof, inputs),
        [AccountMeta(payer, True, True), AccountMeta(verdict, False, True), AccountMeta(SYSTEM_PROGRAM, False, False)],
    )


@dataclass(frozen=True)
class Verdict:
    spec_hash: int
    pred_hash: int
    threshold: int
    slot: int
    recorder: Pubkey


def parse_verdict(data: bytes) -> Verdict:
    if len(data) != VERDICT_LEN or data[0] != 1:
        raise ValueError("not a knos_zk verdict account")
    i = lambda k: int.from_bytes(data[2 + 32 * k:2 + 32 * (k + 1)], "big")  # noqa: E731
    return Verdict(i(0), i(1), i(2), int.from_bytes(data[98:106], "little"), Pubkey.from_bytes(data[106:138]))


def payable(owner: Pubkey | str, data: bytes, program: Pubkey | str, *, spec_hash: int, bar: int,
            pred_hash: int | None = None) -> tuple[bool, list[str]]:
    """Whether a verdict account lets a payout go: owned by the program (only a verified proof creates one), for the
    sealed spec the bounty committed to, at a bar at least the bounty's, and for the submission named (if one is)."""
    why: list[str] = []
    if str(owner) != str(program):
        return False, ["the account is not the program's: no verified proof made it"]
    try:
        v = parse_verdict(data)
    except ValueError as e:
        return False, [str(e)]
    if v.spec_hash != spec_hash:
        why.append("the proof is about another sealed spec")
    if v.threshold < bar:
        why.append(f"the proven bar {v.threshold} is below the required {bar}")
    if pred_hash is not None and v.pred_hash != pred_hash:
        why.append("the proof is about another submission")
    return not why, why


def statement(labels, spec_salt: int, preds, pred_salt: int, threshold: int) -> dict:
    """What the holder of the sealed set states before proving (public inputs), and whether it is true. The labels and
    predictions never leave the caller; only the two hashes and the bar are public."""
    from . import mimc

    correct = sum(1 for a, b in zip(labels, preds) if a == b)
    return {
        "inputs": [mimc.spec_hash(labels, spec_salt), mimc.pred_hash(preds, pred_salt), int(threshold)],
        "provable": len(labels) == len(preds) and 0 <= threshold < 2**16 and correct >= threshold,
    }


def send(url: str, payer, ixs, *, units: int = 400_000, skip_preflight: bool = False) -> dict:
    """One transaction to `url` (devnet): a compute-unit limit, then `ixs`. Returns its signature, the compute units
    the cluster reports, its logs and its error (None when it succeeded). `skip_preflight` lets a transaction the
    program will refuse land on chain anyway, so the refusal itself has a public signature."""
    import base64
    import time

    from solders.compute_budget import set_compute_unit_limit
    from solders.hash import Hash

    from .. import chain
    from ..platform import finality

    level = finality.at(url)        # finalized on Alpenglow, else confirmed
    blockhash = Hash.from_string(chain.call(url, "getLatestBlockhash", [{"commitment": level}])["value"]["blockhash"])
    tx = chain.sign([set_compute_unit_limit(units), *ixs], payer, [], blockhash)
    sig = chain.call(url, "sendTransaction", [base64.b64encode(bytes(tx)).decode(),
                                              {"encoding": "base64", "preflightCommitment": level,
                                               "skipPreflight": skip_preflight}])
    try:
        chain.wait(url, sig)
    except chain.RpcError:
        pass  # failed on chain: the error is read from the transaction below
    got = None
    for _ in range(15):
        got = chain.Ledger(url, commitment=level)._transaction(sig)    # the one reader that asks for version 1
        if got:
            break
        time.sleep(1)
    meta = (got or {}).get("meta") or {}
    return {"signature": sig, "compute_units": meta.get("computeUnitsConsumed"), "logs": meta.get("logMessages", []),
            "slot": (got or {}).get("slot"), "err": meta.get("err")}
