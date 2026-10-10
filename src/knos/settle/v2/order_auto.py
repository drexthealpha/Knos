"""Two options of a work order that knos_pay reads from its flags (programs-v2/knos_pay/src/order_judge.rs, judge e;
order_terms.rs, section 5), and what a relay needs to carry their tokens:

  AUTO      the funder chose, at funding, that the first pull request the black-box suite passes is paid without a
            merge. Its token's audience is knos3:auto:<order>:<head sha>:<terms hash hex>:1:<pr>:<payee>, from the
            order's own repository's pinned prove.yml. One payee: the pull request's author.
  QUORUM    2 or 3: PayOrder pays only when that many distinct judges (0 the order's own repository, 1 a neutral run,
            2 the judge repository) have passed the same artifact. Each one before the last leaves a marker
            ["q", order, kind]; the last one pays. PayOrder takes the three markers after all its other accounts.
            Distinct (2.2, `distinct`): judges whose runs were in repositories of one owner are one judge, and a
            neutral run counts only when its owner is not the order repository's owner and its actor did not start
            the run in the order's repository. Different forge accounts and owners: not different people.
            Off chain (`controllers`): a relay also refuses to carry the word that completes a quorum when two of
            the counted judges were started by one account, though their repositories have different owners. The
            program would count them as two; the refusal is the relay's, until a program upgrade makes it the rule.
"""
from __future__ import annotations

import hashlib
import os

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from . import pay

F_AUTO = 32
F_QUORUM = 0xC0
Q_LEN = 122          # 2.2: the marker also names its judge's run (owner, actor); 2.1 wrote 106 bytes, which count for nothing
Q_LEN_21 = 106       # that marker: the same fields up to the artifact, and no run
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


def read_q(data: bytes | None) -> tuple[int, Pubkey, Pubkey, int, bytes, int, int] | None:
    """A quorum marker: (kind, who paid its rent, its order, the stamp of the order it was made for (pay.Order.stamp),
    the artifact its judge passed, the `repository_owner_id` of the judge's run, its `actor_id`). None when the
    account is not one (a marker as 2.1 wrote it, 106 bytes, names no run and counts for nothing)."""
    if not data or len(data) != Q_LEN:
        return None
    return (data[1], Pubkey.from_bytes(data[2:34]), Pubkey.from_bytes(data[34:66]), int.from_bytes(data[66:74], "little", signed=True), bytes(data[74:106]),
            int.from_bytes(data[106:114], "little"), int.from_bytes(data[114:122], "little"))


def distinct(order_owner: int, who: list[tuple[int, int] | None]) -> int:
    """How many judges these are, exactly as the program counts (order_terms.rs `distinct`). `who`: for each kind
    (0 own repository, 1 neutral, 2 judge repository) the run that passed the artifact as (repository_owner_id,
    actor_id), or None. `order_owner`: the Balance's owner id of a Balance's order, 0 for a wallet's."""
    own, neutral, named = who
    third_party = neutral is not None and (order_owner != 0 or own is not None) and neutral[0] != order_owner and (
        own is None or (neutral[0] != own[0] and neutral[1] != own[1]))
    owners = [w[0] for w in (own, neutral if third_party else None, named) if w is not None]
    return len(set(owners))


def counted(order_owner: int, who: list[tuple[int, int] | None]) -> list[tuple[int, int]]:
    """The runs `distinct` counts, one for each owner, in kind order: the presenting kind's run where its owner is
    already counted is not added twice."""
    own, neutral, named = who
    third_party = neutral is not None and (order_owner != 0 or own is not None) and neutral[0] != order_owner and (
        own is None or (neutral[0] != own[0] and neutral[1] != own[1]))
    out: list[tuple[int, int]] = []
    for w in (own, neutral if third_party else None, named):
        if w is not None and all(w[0] != x[0] for x in out):
            out.append(w)
    return out


def controllers(order_owner: int, who: list[tuple[int, int] | None]) -> int:
    """How many different controllers the counted judges have: two runs share a controller when they share an owner
    or the account that started them (`actor_id`), directly or through a third run. Never more than `distinct`."""
    runs = counted(order_owner, who)
    groups: list[set[int]] = []
    for owner, actor in runs:
        mine = {owner, actor}
        for g in [g for g in groups if g & mine]:
            mine |= g
            groups.remove(g)
        groups.append(mine)
    return len(groups)


ONE_STARTER = ("two of the judges that passed this commit were started by one account, in repositories of different owners: "
               "one account is one judge, so the relay does not carry the word that would complete this quorum")

# Knos's own GitHub accounts: the "ids" of scripts/own_github_ids.json, which the records label "own" (a test holds the two equal)
OWN_IDS = frozenset({142920951})

OWN_ROUND = ("An own round: the funder and the account that started each judge's run are the relay operator's own, so "
             "the judges share one controller and are not independent evidence")


def own_ids() -> frozenset[int]:
    """The relay operator's own GitHub account ids: KNOS_OWN_IDS (comma-separated) when it is set, else Knos's own."""
    got = {int(x) for x in os.environ.get("KNOS_OWN_IDS", "").replace(" ", "").split(",") if x.isdigit()}
    return frozenset(got) or OWN_IDS


def own_round(funder_id: int, runs: list[tuple[int, int]], own: frozenset[int]) -> bool:
    """True when the order's funder and the account that started each counted run (`counted`) are all the operator's
    own: the one-starter refusal is for outside orders, and an own round runs, labelled own (`OWN_ROUND`)."""
    return bool(own) and bool(runs) and funder_id in own and all(actor in own for _owner, actor in runs)


def passed(markers: dict[int, bytes | None], o: pay.Order, audience: str, kind: int, run: tuple[int, int] | None = None) -> int:
    """How many distinct judges have passed this audience's artifact for the order as it is funded now, counting the
    judge of `kind` who presents it. `markers`: {kind: the data of q_pda(order, kind)}. `run`: the presenting
    token's (repository_owner_id, actor_id); the count is the program's only with it. Without it the presenter is
    taken for an owner nobody else is, which is the most the program can count."""
    art = artifact(audience)
    who: list[tuple[int, int] | None] = [None, None, None]
    for k in range(3):
        q = read_q(markers.get(k))
        if k != kind and q is not None and q[3] == o.stamp and q[4] == art:
            who[k] = (q[5], q[6])
    if run is None:
        return distinct(o.owner_id, who) + 1
    who[kind] = run
    return distinct(o.owner_id, who)


# -- both builds ----------------------------------------------------------------------------------------------------------
# The public program runs 2.1 until the upgrade to 2.2 executes, so whoever carries a token reads the markers as the
# build that is LIVE reads them: `passed21` on 2.1, `passed` (with the presenting run) on 2.2.
NAMES = {0: "the order's own repository", 1: "the neutral run", 2: "the judge repository"}


def read_any(data: bytes | None) -> tuple[int, Pubkey, Pubkey, int, bytes] | None:
    """A quorum marker of either build, as far as both write it: (kind, who paid its rent, its order, the stamp of
    the order it was made for, the artifact its judge passed). None when the account is not one."""
    if not data or len(data) not in (Q_LEN, Q_LEN_21):
        return None
    return data[1], Pubkey.from_bytes(data[2:34]), Pubkey.from_bytes(data[34:66]), int.from_bytes(data[66:74], "little", signed=True), bytes(data[74:106])


def _counts21(data: bytes | None, o: pay.Order, art: bytes) -> bool:
    q = read_any(data) if data and len(data) == Q_LEN_21 else None
    return q is not None and q[3] == o.not_before and q[4] == art


def passed21(markers: dict[int, bytes | None], o: pay.Order, audience: str, kind: int) -> int:
    """`passed` as knos_pay 2.1 counts: every other kind whose marker (106 bytes) is of this order's funding time and
    this artifact is one more judge, whoever ran it."""
    art = artifact(audience)
    return 1 + sum(k != kind and _counts21(markers.get(k), o, art) for k in range(3))


def stale(markers: dict[int, bytes | None], o: pay.Order, audience: str, kind: int) -> list[int]:
    """The kinds, other than the presenting one, whose judge passed this artifact for this order under 2.1 and left a
    marker 2.2 counts for nothing (it names no run): each has to sign again for his word to count."""
    art = artifact(audience)
    return [k for k in range(3) if k != kind and o.inc == 0 and _counts21(markers.get(k), o, art)]


def spoke(markers: dict[int, bytes | None], o: pay.Order, audience: str, kind: int, run: tuple[int, int]) -> list[tuple[int, int] | None]:
    """For each kind, the run (repository_owner_id, actor_id) that has passed this artifact for the order as it is
    funded now, the presenting one included: what `distinct` counts on 2.2."""
    art = artifact(audience)
    who: list[tuple[int, int] | None] = [None, None, None]
    for k in range(3):
        q = read_q(markers.get(k))
        if k != kind and q is not None and q[3] == o.stamp and q[4] == art:
            who[k] = (q[5], q[6])
    who[kind] = run
    return who


def uncounted(order_owner: int, who: list[tuple[int, int] | None]) -> list[str]:
    """Why judges who have spoken are fewer than those who spoke, in plain words: one sentence for each run that
    `distinct` does not count as a judge of its own. Empty when every run counts."""
    own, neutral, named = who
    out, third = [], False
    if neutral is not None:
        if order_owner == 0 and own is None:
            out.append("the neutral run is not counted until the order's own repository has passed this commit, because until then nothing shows "
                       "that it is a third party's")
        elif neutral[0] == order_owner or (own is not None and neutral[0] == own[0]):
            out.append("the neutral run was in a repository of the account that owns the order's repository, and runs in repositories of one "
                       "owner are one judge")
        elif own is not None and neutral[1] == own[1]:
            out.append("the neutral run was started by the account that started the run in the order's own repository, so it is not a third party's")
        else:
            third = True
    if named is not None and any(e is not None and e[0] == named[0] for e in (own, neutral if third else None)):
        out.append("the judge repository has the same owner as another judge that passed this commit, and runs in repositories of one owner are "
                   "one judge")
    return out
