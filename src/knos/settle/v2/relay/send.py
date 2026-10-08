"""Sending a plan: the token written, the RSA verification stepped, the escrow instruction, the close; `submit` and
`verify_only`."""
from __future__ import annotations

from typing import Callable

from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from .... import chain, receipt
from ... import relay as first
from .. import oidc

from .pins import ROOM, ROOM_V1, _CU, _LAST_STEP, _SPARE, _Stop, _code, _failed, _no, _out_of_compute
from .build import version
from .tokens import _Token, _jwks
from .plans import Group, _Plan
from .kinds import _handler_of, _open, _plan, _signer


# -- sending: few transactions, few waits -------------------------------------------------------------------------------
def _write_ix(me: Pubkey, tid: bytes, total: int, off: int, chunk: bytes) -> Instruction:
    """The verifier's Write (oidc.write_ixs cuts every 880 bytes; this relay cuts where its transactions have room)."""
    return Instruction(oidc.OIDC_ID, b"\x00" + tid + total.to_bytes(2, "little") + off.to_bytes(2, "little") + chunk,
                       [AccountMeta(me, True, True), AccountMeta(oidc.token_pda(me, tid), False, True), AccountMeta(oidc.SYSTEM, False, False)])


def _fits(me: Pubkey, ixs: list[Instruction], cu: int = 0, v1: bool = False) -> bool:
    return chain.tx_size(ixs, me, v1) <= (ROOM_V1 if v1 else ROOM) and cu <= chain.MAX_COMPUTE_UNITS - _SPARE


def _send(ledger, payer: Keypair, ixs: list[Instruction], v1: bool = False) -> str:
    """One transaction, waited for: a v1 one when the plan says so (a ledger that knows none is never asked for one)."""
    return ledger.send(ixs, payer, v1=True) if v1 else ledger.send(ixs, payer)


def _steps(bits: int, done: int) -> list[int]:
    """Squarings for each Step still to send, from `done` of 16: the verifier client's plan, picked up where the
    token account stands."""
    out, at = [], 0
    for sq in oidc.step_plan(bits):
        at += sq
        if at > done:
            out.append(at - max(done, at - sq))
    return out


def _verification(me: Pubkey, t: _Token, have: bytes | None, register: list[Instruction],
                  v1: bool = False) -> tuple[list[list[list[Instruction]]], Instruction | None, int]:
    """(rounds, last Step, its compute units): the transactions that bring the token to its last Step, in rounds
    whose transactions do not depend on each other, and the Step that finishes the verification, which the caller
    sends together with what needs the verified token. An account that already holds part of this token (a run that
    was cut short) is carried on from where it stands; a verified one needs nothing (no last Step). With `v1` a
    transaction holds 4,096 bytes: a token of the usual size is written whole beside its first Step."""
    raw, state = t.jwt.encode(), oidc.read_token(have)
    rounds: list[list[list[Instruction]]] = [[register]] if register else []
    if state is not None and state.verified:
        return rounds, None, 0
    written = have[oidc.T_JWT:] if have is not None and state is not None and len(have) == oidc.T_JWT + len(raw) else None
    done = state.done if state is not None and state.stage == 1 else 0
    if state is not None and (written is None or (state.stage == 1 and (written != raw or state.key != t.key or done >= 16))):
        rounds.append([[oidc.close_ix(me, t.tid)]])       # not this token as this relay writes it: start again
        written, done = None, 0
    steps = [oidc.step_ix(me, t.tid, t.key, sq) for sq in _steps(t.bits, done)]
    before = steps[:1] if len(steps) > 1 else []          # the last Step is the caller's; the one before it takes the token's tail along
    if done == 0:
        room = lambda *beside: 200 + (ROOM_V1 if v1 else ROOM) - chain.tx_size([_write_ix(me, t.tid, len(raw), 0, bytes(200)), *beside], me, v1)  # noqa: E731
        cut = len(raw) - min(len(raw), room(*before)) if before else len(raw)
        heads = [(off, raw[off:min(off + room(), cut)]) for off in range(0, cut, room())]
        lead = [[_write_ix(me, t.tid, len(raw), off, chunk)] for off, chunk in heads if written is None or written[off:off + len(chunk)] != chunk]
        if lead and register and len(rounds) == 1:
            rounds[0] += lead                              # the key's registration and the head of the token do not depend on each other
        elif lead:
            rounds.append(lead)
        if cut < len(raw) and (written is None or written[cut:] != raw[cut:]):
            before = [_write_ix(me, t.tid, len(raw), cut, raw[cut:]), *before]
    rounds += [[before]] if before else []
    rounds += [[[s]] for s in steps[1:-1]]
    fixed, per_byte = _LAST_STEP[t.bits]
    return rounds, steps[-1], fixed + per_byte * len(raw)


def _round(ledger, payer: Keypair, txs: list[list[Instruction]], v1: bool = False) -> list[str]:
    """Transactions that do not depend on each other: sent together and waited for once, when the ledger can."""
    many = getattr(ledger, "send_all", None)
    if many is not None and len(txs) > 1:
        return list(many(txs, payer, v1=True) if v1 else many(txs, payer))
    return [_send(ledger, payer, ixs, v1) for ixs in txs]


def _land(ledger, payer: Keypair, last: Instruction | None, last_cu: int, groups: list[Group], close: Instruction | None, alone: bool,
          lead: bool = False, v1: bool = False) -> tuple[list[str], bool]:
    """Sends the last Step, the escrow's groups and the Close in as few transactions and waits as they fit in: the
    Step shares its transaction with the groups that fit beside it, and the Close rides in the last one. Groups left
    over go in further transactions, side by side when `alone` says they depend on nothing but the first (with no
    Step to send, on nothing at all, unless `lead` says the first group comes first). Returns (signatures, whether
    the token account was closed)."""
    me = payer.pubkey()
    txs: list[Group] = []
    cur, cu = ([last], last_cu) if last is not None else ([], 0)
    for ixs, need in groups:
        if cur and not _fits(me, cur + ixs, cu + need, v1):
            txs.append((cur, cu))
            cur, cu = [], 0
        cur, cu = cur + ixs, cu + need
    if cur:
        txs.append((cur, cu))
    first_n = 1 if last is not None or lead or not alone else 0     # the transaction with the Step (or the Bind) lands before any other
    together = alone and len(txs) - first_n > 1             # the rest land in any order, so the Close waits for them all
    closed = close is not None and bool(txs) and not together and _fits(me, txs[-1][0] + [close], txs[-1][1] + _CU["close"], v1)
    if closed:
        txs[-1] = (txs[-1][0] + [close], txs[-1][1] + _CU["close"])     # type: ignore[list-item]  # `closed` holds only with a close
    sigs: list[str] = []
    for ixs, _cu in txs[:first_n]:
        try:
            sigs.append(_send(ledger, payer, ixs, v1))
        except Exception as why:
            if last is None or len(ixs) == 1 or not _out_of_compute(why):
                raise
            sigs.append(_send(ledger, payer, [last], v1))   # the Step took more than was measured: it goes alone, the rest after it
            more, shut = _land(ledger, payer, None, 0, groups, close, alone, lead, v1)
            return sigs + more, shut
    rest = [ixs for ixs, _cu in txs[first_n:]]
    sigs += _round(ledger, payer, rest, v1) if together else [_send(ledger, payer, ixs, v1) for ixs in rest]
    if close is not None and not closed:
        sigs.append(_send(ledger, payer, [close], v1))
    return sigs, close is not None


def _someone_else(ledger, sigs: list[str], me: Pubkey) -> bool:
    """Whether the newest of `sigs` (transactions the chain shows did a token's work, which this relay did not see
    confirmed) was paid for by another key than `me`: another relayer carried the token, and this relay's own lost
    transaction did not land. False when the ledger cannot tell (the answer before 0.3.19: the work counts as this
    relay's own). Seen live in staging on 7 Oct 2026: two relayers sent one fund token in the same second; the loser
    logged the winner's transaction as its own."""
    find = getattr(ledger, "payer_of", None)
    if not sigs or find is None:
        return False
    try:
        who = find(sigs[-1])
    except Exception:  # noqa: BLE001 - the cluster did not say: the answer stays as it was before this was asked
        return False
    return who is not None and str(who) != str(me)


def _carry(ledger, payer: Keypair, plan: _Plan, again: Callable[[], _Plan]) -> dict:
    """Sends what the plan holds and answers with what the chain then shows. `again` plans the same token anew: after
    a failure it tells whether the chain shows the token's work all the same (a transaction reported lost had landed)."""
    me, t, sigs = payer.pubkey(), plan.t, []
    closed = not plan.token
    try:
        last, last_cu = None, 0
        if plan.token:
            rounds, last, last_cu = _verification(me, t, plan.have, plan.register, plan.v1)
            for txs in rounds:
                sigs += _round(ledger, payer, txs, plan.v1)
        landed, shut = _land(ledger, payer, last, last_cu, plan.groups, oidc.close_ix(me, t.tid) if plan.token and not plan.closes else None, plan.alone,
                             plan.lead, plan.v1)
        sigs += landed
        closed = closed or shut or plan.closes
        return plan.done(sigs)
    except Exception as why:  # noqa: BLE001 - one bad token never stops the relay loop
        closed = not plan.token
        if plan.v1 and chain.v1_refused(why):       # this cluster takes no v1 transaction: the same token, the old way, from where it stands
            ledger.takes_v1 = False
            closed = True                           # (the retry closes what it opens)
            return _carry(ledger, payer, again(), again)
        still = False       # whether every read still allows what the program just refused
        try:
            again()
            still = True
        except _Stop as stop:
            if stop.result.get("ok"):
                if _someone_else(ledger, [s for s in stop.result.get("sigs", []) if s not in sigs], me):
                    # another relayer's transaction did the token's work while this one was carrying it: "already", and
                    # what this relay sent on the way (its verification) is named apart, so the log credits the winner
                    return {**stop.result, "already": True, "spent": sigs}
                return {k: v for k, v in {**stop.result, "sigs": list(dict.fromkeys([*sigs, *stop.result.get("sigs", [])]))}.items() if k != "already"}
        except Exception:  # noqa: BLE001, S110 - the cluster is not answering: the failure stands, and is tried again
            pass
        if still and plan.soon and _code(str(why)) == 83:
            # the one refusal no read foresees: the slot of the order's funding. It clears with the next block; should
            # it not, the passes are counted and the token is given up like any refusal that does not clear
            return {"ok": False, "kind": t.kind, "why": plan.soon, "retry": True, "transient": True, "answered": True, "wait": 1}
        return _failed(t.kind, why)
    finally:
        if not closed:      # the token account has done its work, or failed to: take the rent back either way
            try:
                if ledger.account(t.account) is not None:
                    ledger.send([oidc.close_ix(me, t.tid)], payer)
            except Exception:  # noqa: BLE001, S110 - `sweep` closes it later
                pass


def _first(ledger, payer: Keypair, jwt: str, jwks: dict | None, now: float | None) -> dict:
    """A key token on the first deployment, as ever (knos.settle.relay), with the key sets this module already has."""
    docs = dict(jwks or {})
    for issuer in oidc.ISSUERS:
        try:
            docs.setdefault(issuer, _jwks(issuer, jwks))
        except Exception:  # noqa: BLE001, S110 - the first deployment's relay fetches what it needs
            pass
    return first.submit(ledger, payer, jwt, docs, now)


def submit(ledger, payer: Keypair, jwt: str, terms: bytes | None = None, jwks: dict | None = None, now: float | None = None) -> dict:
    """Verify the token and do what its audience says, on the second deployment (a key token: on both). Never raises
    for a bad token: returns {"ok": False, "kind", "why"}, with "retry": True when the same token may succeed later.
    The token's account is closed behind it, so the relayer's rent comes back whatever happened. A key token is ok
    when either deployment took it or had nothing to do; a later run of the rotate workflow brings the key again."""
    handler = _handler_of(jwt)
    kind = handler.name if handler else None
    before = _first(ledger, payer, jwt, jwks, now) if handler is not None and handler.first else None
    try:
        plan = lambda: _plan(ledger, payer, jwt, terms, jwks, now)  # noqa: E731
        result = _carry(ledger, payer, plan(), plan)
    except _Stop as stop:
        result = stop.result
    except Exception as why:  # noqa: BLE001 - the cluster or the issuer did not answer: nothing was sent
        result = _failed(kind, why)
    if before is None:
        receipt.settled(ledger, result)       # a confirmed payment's receipt as an attestation: after it, fail soft, KNOS_NO_SAS=1 opts out
        return result
    if result["ok"]:
        return {**result, "sigs": [*before.get("sigs", []), *result["sigs"]], "first": before}
    if before.get("ok"):        # the first deployment took it; the second said why it did not
        return {"ok": True, "kind": "key", "sigs": list(before.get("sigs", [])), "key": str(before.get("key", "")), "added": False,
                "refreshed": False, "why": result["why"], "first": before}
    return result


def verify_only(ledger, payer: Keypair, jwt: str, jwks: dict | None = None, now: float | None = None) -> dict:
    """Verifies a token of any audience into its account and leaves it there, for someone else's program to read
    (GitHub's, GitLab's, or one of any issuer the verifier holds a key for: a registered issuer's key before a private one):
    {"ok": True, "kind": "verify", "sigs", "account", "payer", "exp"}. The account is the verifier's
    ["tok", payer, sha256(token)]: a consumer checks that knos-oidc owns it and reads the claims (docs/OIDC.md). It
    stays until an hour past the token's expiry, when `sweep` takes its rent back. The same reads as `submit` come
    first: a token no published key signed, or whose key the chain would refuse, costs nothing."""
    kind = "verify"
    try:
        me = payer.pubkey()
        t = _open(jwt.strip(), me, jwks, ledger)
        t.kind = kind
        now = int(now if now is not None else ledger.now())
        exp = int(t.c.get("exp", 0))
        if exp + oidc.LATE <= now:
            raise _no(kind, "token expired")
        plan = _Plan(t, [], dict, v1=version(ledger, payer) >= 1 and bool(getattr(ledger, "takes_v1", False)))     # type: ignore[arg-type]  # nothing is paid
        _signer(ledger, me, t, plan, now)
        result = dict(ok=True, kind=kind, account=str(t.account), payer=str(me), exp=exp)
        rounds, last, _cu = _verification(me, t, plan.have, plan.register, plan.v1)
        if last is None:
            return {**result, "sigs": [], "already": True}
        sigs: list[str] = []
        try:
            for txs in [*rounds, [[last]]]:
                sigs += _round(ledger, payer, txs, plan.v1)
        except Exception as why:  # noqa: BLE001
            if not (plan.v1 and chain.v1_refused(why)):
                raise
            ledger.takes_v1 = False                 # this cluster takes no v1 transaction: the old way, from where the account stands
            return verify_only(ledger, payer, jwt, jwks, now)
        return {**result, "sigs": sigs}
    except _Stop as stop:
        return {**stop.result, "kind": kind}
    except Exception as why:  # noqa: BLE001
        return _failed(kind, why)
