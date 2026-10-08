"""What the relay holds fixed: the workflow pins it accepts, the compute units it plans by, what knos-oidc's error
numbers mean, and how a refusal or a failed send is read (`transient`, `answered`, `why_failed`)."""
from __future__ import annotations

import re
from typing import Any

from .... import chain
from .. import oidc, pay


# GitHub's four keys of 2 Oct 2026, the root knos-oidc starts from (programs-v2/knos_oidc/src/pins.rs, GENESIS):
# RegisterKey takes these with no attestation, so a relayer that meets one the chain has not seen registers it.
GENESIS = frozenset({"29dfb1c0b82f6c6f770f45a7a78b73a30dfe33980f4a82a6fb4280ccf7417e1a",
                     "dc2cea85e2a48ec836bbde7177dff1de2a77fe17faef2276ff0d9460d7a73565",
                     "e0bfde8963254fb2f7871c4d80d968fc25e272687fd72ad90d89b3e51ea240af",
                     "478592fecdfacedd7b679f9f428586b22785ec752b6bea6cc1b793ae134975fb"})


ROTATE_REF = "drexthealpha/knos-oidc-rotate/.github/workflows/rotate.yml@"


CLAIM_REF = "drexthealpha/knos-oidc-rotate/.github/workflows/claim.yml@"


# The pins the programs hold (program_ids.json). A test build accepts test pins beside them; the tests add those here.
ROTATE_SHAS = frozenset({oidc.IDS["rotate_sha"]})


CLAIM_SHAS = frozenset({pay.IDS["claim_sha"]})


# The later commit of both workflows, which only the 2.1 programs take beside the pins above: rotate.yml with an `issuer`
# input (a key of any RS256 issuer, named by its URL), claim.yml with `kind: org` (an organisation's wallet).
ROTATE_SHAS2 = frozenset({oidc.IDS["rotate_sha2"]})


ORG_CLAIM_SHAS = frozenset({pay.IDS["claim_sha_org"]})


ATTESTERS = frozenset((oidc.IDS["attest_owner_id"], repo) for repo in oidc.IDS["attest_repo_ids"])


REFRESH_AFTER = 86_400      # a key is refreshed when that moves its expiry by a day or more: once a day, not per token


JWKS_TTL = 600


ROOM = chain.MAX_TX_BYTES - 4   # what this relay lets a transaction weigh (a ledger that signs another way may add 2 bytes)


ROOM_V1 = chain.MAX_V1_BYTES - 4    # and a v1 transaction, which a 2.1 cluster takes


# Compute units, measured in LiteSVM (tests/test_relay2.py prints them) and rounded up. The last Step also hashes and
# decodes the token, so it costs more the longer the token is: (for any token, for each of its bytes), by key size.
_LAST_STEP = {2048: (760_000, 75), 4096: (820_000, 75)}


# Every instruction that takes a token also makes the token's marker: 40,000 more than it cost without one.
_CU: dict[str, Any] = {"faucet": 140_000, "fund": 150_000, "ata": 30_000, "pay": 130_000, "settle": 90_000, "bind": 80_000, "close": 5_000,
       "register": 45_000, "refresh": 35_000, "params": {2048: 150_000, 4096: 550_000},
       "record": 90_000,
       "fund_order": 150_000, "pay_order": 150_000, "payee": 60_000,       # an order's payment: once, and for each payee (its token account made on the way)
       "terms": 40_000,                                                    # and what a standing order's marker or a holdback's record adds to it
       "quorum": 40_000,                                                   # and what an order's quorum adds: three marker addresses, one marker written
       "reserve": 100_000, "cancel": 100_000, "revert": 160_000, "release": 90_000, "bind_org": 100_000, "issuer_key": 90_000,
       "gate": 60_000}


_SPARE = 50_000             # compute units left unplanned in a transaction


_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")     # PKCS#1 v1.5: "a SHA-256 digest follows"


_HEX64, _HEX40 = re.compile(r"[0-9a-f]{64}"), re.compile(r"[0-9a-f]{40}")


_U64 = re.compile(r"0|[1-9][0-9]{0,17}")


_T_PAYER, _T_ID = 50, 82    # where a token account keeps the key that pays for it, and the token's id


# what knos-oidc means by its error numbers (knos-pay's 80-99, and the key's 76-78, are worded in pay.ERRORS)
_VERIFIER = {64: "the token is longer than the verifier takes", 65: "the signature is not as long as its key",
             67: "a wrong account for the verifier, or another run moved this token's account",
             68: "the signing key is not ready on chain", 69: "another run moved this token's account",
             70: "the signature is not the issuer's", 71: "the token is not signed with RS256", 72: "the token's issuer is not the key's",
             73: "the chain does not trust this signing key and no attestation names it",
             74: "the attestation is not the rotate workflow's, run by its schedule or by hand in the attester's repository",
             75: "the attestation has expired"}


class _Stop(Exception):
    """submit's answer, raised where it became known: a refusal, or work the chain already shows."""
    def __init__(self, result: dict):
        super().__init__(result.get("why", "already done"))
        self.result = result


def _no(kind: str | None, why: str, **more) -> _Stop:
    return _Stop({"ok": False, "kind": kind, "why": why, **more})


def _out_of_compute(why: BaseException) -> bool:
    return any(mark in str(why) for mark in ("ProgramFailedToComplete", "Program failed to complete", "omputational budget exceeded",
                                             "exceeded CUs meter", "ComputationalBudgetExceeded"))


def _code(text: str) -> int | None:
    """The program's error number, in whatever words a ledger reported it."""
    m = re.search(r"custom program error: 0x([0-9a-fA-F]+)", text)
    if m:
        return int(m.group(1), 16)
    m = re.search(r"'Custom': (\d+)|Custom\((\d+)\)", text)
    return int(m.group(1) or m.group(2)) if m else None


_BROKE = ("found no record of a prior credit", "insufficient lamports", "InsufficientFundsForFee", "AccountNotFound")


def transient(why: BaseException) -> bool:
    """A failure that says nothing about the token: the cluster did not answer or dropped the transaction, the fee
    payer is out of SOL, or another run with this same relayer key was moving the same token account (knos-oidc
    refuses with 67 or 69, knos-pay with 84 when the account was closed under it; what would make 84 a verdict on the
    token was asked before anything was sent). The same token may succeed on the next pass."""
    if isinstance(why, (OSError, TimeoutError)):
        return True
    text = str(why)
    return _code(text) in (67, 69, 84) or any(mark in text for mark in ("Blockhash not found", "block height exceeded", "Too Many Requests",
                                                                        "Node is behind", "Node is unhealthy", "Internal error", *_BROKE))


def answered(why: BaseException) -> bool:
    """The program itself refused, with a number a twin run can cause (67, 69, 84). That clears within a pass or two
    when a twin was why; when it does not clear it is the program's answer, so a relay counts these tries and stops
    (`knos.proof.ghrelay.MAX_TRIES`), whatever life the token has left."""
    return not isinstance(why, (OSError, TimeoutError)) and _code(str(why)) in (67, 69, 84)


def _failed(kind: str | None, why: BaseException) -> dict:
    """A failure as a result, in words: the program's own meaning for its error number when it gave one."""
    text = str(why)
    code = _code(text)
    if code == 90:      # the faucet's minute went to another token between the read and the transaction
        return {"ok": False, "kind": kind, "why": "the faucet serves a repository once a minute", "retry": True, "wait": pay.FUND_PERIOD}
    said = (pay.ERRORS.get(code) or _VERIFIER.get(code)) if code is not None else None
    words = ("the relayer's key has no SOL to pay the fees with" if any(mark in text for mark in _BROKE)
             else f"{said} (error {code})" if said else f"{type(why).__name__}: {text[:200]}")
    return {"ok": False, "kind": kind, "why": words, **({"retry": True, "transient": True} if transient(why) else {}), **({"answered": True} if answered(why) else {})}


def why_failed(why: BaseException) -> str:
    """What a failed transaction of the escrow's or the verifier's means, in the words of their clients (for a wallet's
    own commands: `knos balance`, `knos fund-wallet`)."""
    return _failed(None, why)["why"]
