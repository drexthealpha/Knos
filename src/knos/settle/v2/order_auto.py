"""Two options of a work order that knos_pay reads from its flags (programs-v2/knos_pay/src/order_judge.rs, judge e;
order_terms.rs, section 5), and what a relay needs to carry their tokens:

  AUTO      the funder chose, at funding, that the first pull request the black-box suite passes is paid without a
            merge. Its token's audience is knos3:auto:<order>:<head sha>:<terms hash hex>:1:<pr>:<payee>, from the
            order's own repository's pinned prove.yml. One payee: the pull request's author.
  QUORUM    2 or 3: PayOrder pays only when that many distinct judges (0 the order's own repository, 1 a neutral run,
            2 the judge repository) have passed the same artifact. Each one before the last leaves a marker
            ["q", order, kind]; the last one pays. PayOrder takes the three markers after all its other accounts.
"""
from __future__ import annotations

import hashlib

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from . import pay

F_AUTO = 32
F_QUORUM = 0xC0
Q_LEN = 106
KINDS = {"own": 0, "auto": 0, "neutral": 1, "private": 2}    # relay._judge's names -> the kind a marker records


def quorum_flags(n: int) -> int:
    """The flag bits of a quorum of `n` judges: 0 (none), 2 or 3."""
    if n not in (0, 2, 3):
        raise ValueError("a quorum is 2 or 3 judges")
    return n << 6


def quorum_of(flags: int) -> int:
    """How many distinct judges an order with these flags needs before it pays: 0 (one token pays), 2 or 3."""
    return flags >> 6


def auto_audience(order: Pubkey, head_sha: str, terms: bytes, pr: int, payee_id: int, address: Pubkey | None = None) -> str:
    """What the pinned prove.yml asks GitHub to sign when the black-box suite passed on the head of an open pull
    request for an AUTO order: the pay audience under the word `auto`, mode 1, one payee (the author)."""
    return f"knos3:auto:{order}:{head_sha}:{terms.hex()}:1:{pr}:{pay.payees_text([(payee_id, 10_000, address)])}"


def artifact(audience: str) -> bytes:
    """What two judges must agree on: sha256 of the audience after its order's address (head, terms, mode, pull
    request, payees). A pay audience and an auto audience of the same pull request are the same artifact."""
    return hashlib.sha256(audience.split(":", 3)[3].encode()).digest()


def q_pda(order: Pubkey, kind: int, program: Pubkey = pay.PAY_ID) -> Pubkey:
    return Pubkey.find_program_address([b"q", bytes(order), bytes([kind])], program)[0]


def with_quorum(ix: Instruction, order: Pubkey, o: pay.Order, program: Pubkey = pay.PAY_ID) -> Instruction:
    """A PayOrder instruction with the three quorum markers last, when the order has a quorum; else `ix` as it is."""
    if not quorum_of(o.flags):
        return ix
    return Instruction(ix.program_id, bytes(ix.data), [*ix.accounts, *(AccountMeta(q_pda(order, k, program), False, True) for k in range(3))])


def read_q(data: bytes | None) -> tuple[int, Pubkey, Pubkey, int, bytes] | None:
    """A quorum marker: (kind, who paid its rent, its order, the `not_before` of the order it was made for, the
    artifact its judge passed). None when the account is not one."""
    if not data or len(data) != Q_LEN:
        return None
    return data[1], Pubkey.from_bytes(data[2:34]), Pubkey.from_bytes(data[34:66]), int.from_bytes(data[66:74], "little", signed=True), bytes(data[74:106])


def passed(markers: dict[int, bytes | None], o: pay.Order, audience: str, kind: int) -> int:
    """How many distinct judges have passed this audience's artifact for the order as it is funded now, counting the
    judge of `kind` who presents it. `markers`: {kind: the data of q_pda(order, kind)}."""
    art, have = artifact(audience), 1
    for k in range(3):
        q = read_q(markers.get(k))
        have += k != kind and q is not None and q[3] == o.not_before and q[4] == art
    return have
