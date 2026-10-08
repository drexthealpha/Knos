"""Plans for work orders (2.1): fund, pay (with judges, quorum and holdback), take, cancel, revert, and an
organisation's wallet."""
from __future__ import annotations

import hashlib
import re
from typing import Any

from solders.instruction import Instruction
from solders.pubkey import Pubkey

from .... import chain, fees
from .. import oidc, order_auto, pay

from .pins import CLAIM_REF, CLAIM_SHAS, ORG_CLAIM_SHAS, _CU, _HEX40, _HEX64, _Stop, _U64, _no
from .tokens import _Token, _address, _ints, _units, _when, _workflow
from .reads import _amount, _data, _funded_by, _last, _read, _said_in, _said_since, held_for
from .plans import Group, _Ask, _Plan, _bounds, _decimals, _limits
from .jobs import _fund_run, _payout


def _options(kind: str, raw: bytes, amount: int, actor: int = 0, owner: int = 0, mode: int = 1, v: int = fees.NEW_VERSION) -> tuple[bool, int]:
    """The 48 bytes a funder fixes beside the amount (opts_of in order.rs, and the arbiter rule of order_judge::funded):
    refused here as the program of version `v` would. Returns (whether the order is PRIVATE, its judge repository's
    id). Byte 33 is the presentation grace, which 2.2 reads and 2.1 refuses as it refuses any byte after the 33rd."""
    flags, holdback, warranty, kill, rate, arbiter, judge, salted = (raw[0], int.from_bytes(raw[1:3], "little"), int.from_bytes(raw[3:5], "little"),
                                                                    int.from_bytes(raw[5:7], "little"), int.from_bytes(raw[8:16], "little"),
                                                                    int.from_bytes(raw[16:24], "little"), int.from_bytes(raw[24:32], "little"), raw[32])
    private, standing = bool(flags & pay.F_PRIVATE), bool(flags & pay.F_STANDING)
    auto, quorum = bool(flags & order_auto.F_AUTO), order_auto.quorum_of(flags)
    judges = 1 + bool(flags & pay.F_NEUTRAL) + bool(judge)
    if (auto or quorum) and (private or standing):
        raise _no(kind, "`auto` and `quorum` are for a public order that pays one pull request: not a private order, not a standing offer")
    if auto and mode != pay.TESTS:
        raise _no(kind, "`auto` pays a pull request without a merge, so only on a black-box acceptance suite: this issue has none "
                        "(.knos/acceptance/<issue>/ with a `blackbox.sh`), and without one only a merge pays")
    if raw[33] == 1 and not any(raw[34:]) and v < fees.NEW_VERSION:
        raise _no(kind, "this order asks for the presentation grace (a token issued by the deadline is still taken for two hours after it), which "
                        "the escrow on this cluster does not have yet: it comes with the announced upgrade to knos_pay 2.2. Fund without it until then")
    if quorum and not 2 <= quorum <= judges:
        raise _no(kind, f"`quorum {quorum}` needs that many judges this order can have, and it has {judges}: its own repository, a neutral "
                        "run unless `neutral off`, and a judge repository if it names one")
    ok = (flags & ~(pay.F_PRIVATE | pay.F_NEUTRAL | pay.F_STANDING | order_auto.F_AUTO | order_auto.F_QUORUM) == 0 and salted <= 1 and raw[33] <= (v >= fees.NEW_VERSION) and not any(raw[34:]) and holdback <= pay.MAX_HOLDBACK_BPS
          and warranty <= pay.MAX_WARRANTY_DAYS and kill <= pay.MAX_KILL_BPS and (holdback == 0 or warranty > 0)
          and (1 <= rate <= amount if standing else rate == 0) and private == bool(salted) and (not private or judge != 0))
    if not ok:
        raise _no(kind, "the order's options are outside what is allowed: a holdback up to 50% and only with a warranty, a warranty up to "
                        f"{pay.MAX_WARRANTY_DAYS} days, a kill fee up to 20%, a rate only for a standing order and no more than its amount, "
                        "and a private order names its scope and a judge repository")
    if arbiter and arbiter in (actor, owner):
        raise _no(kind, "the arbiter decides between the funder and the payees: he cannot be the commenter who funds the order, nor the owner whose balance pays")
    return private, judge


def private_terms(beside: bytes | str | None) -> bytes | None:
    """What travels with the fund token of a PRIVATE order, where a public one's terms JSON travels: the order's scope
    and its terms hash, 64 bytes, or the 128 hex characters a comment's `knos-terms:` line writes them as. Neither
    says which repository or which issue. None for anything else."""
    raw = beside.encode() if isinstance(beside, str) else bytes(beside or b"")
    if len(raw) == 128 and re.fullmatch(rb"[0-9a-f]{128}", raw):
        raw = bytes.fromhex(raw.decode())
    return raw if len(raw) == 64 else None


def carries_terms(aud: str, terms: bytes | str | None) -> bool:
    """Whether `terms` is what a fund token with this audience was signed for: the terms JSON whose hash the audience
    carries, or (the options say PRIVATE) the scope and terms hash whose hash it carries."""
    p = aud.split(":")
    if len(p) < 6 or terms is None:
        return False
    private = len(p) == 10 and re.fullmatch(r"[0-9a-f]{%d}" % (2 * pay.OPTS_LEN), p[9]) and bytes.fromhex(p[9])[0] & pay.F_PRIVATE
    raw = private_terms(terms) if private else (terms.encode() if isinstance(terms, str) else bytes(terms))
    return raw is not None and hashlib.sha256(raw).hexdigest() == p[5]


def _plan_order_fund(a: _Ask) -> _Plan:
    """knos3:fund: a comment funds a work order from a Balance (FundOrderBalance), the faucet opened on the way. The
    funder pays the fee on top of the amount, so the Balance must hold both."""
    kind, ledger, me, t, now, terms = "fund", a.ledger, a.me, a.t, a.now, a.terms
    c, p = t.c, t.aud.split(":")
    try:
        if len(p) != 10 or p[4] not in ("0", "1") or not _HEX64.fullmatch(p[5]) or not re.fullmatch(r"[0-9a-f]{%d}" % (2 * pay.OPTS_LEN), p[9]):
            raise ValueError(t.aud)
        issue, amount, mode, work, balance, seq = int(p[2]), int(p[3]), int(p[4]), int(p[6]), _address(p[7]), int(p[8])
        repo_id, owner_id, actor, iat = _ints(c, "repository_id", "repository_owner_id", "actor_id", "iat")
        if not 0 <= seq < 2 ** 32:
            raise ValueError(t.aud)
    except (KeyError, ValueError, TypeError):
        raise _no(kind, "malformed audience or claims") from None
    private, judge_repo = _options(kind, bytes.fromhex(p[9]), amount, actor, owner_id, mode, a.v)
    wf_sha = _fund_run(kind, c, None if private else terms, p[5], private=private)
    hidden = private_terms(terms) if private else None      # a private order: its scope, then its terms hash (order_judge::funded)
    if private:
        if issue != 0:
            raise _no(kind, "malformed audience or claims")
        if not terms:           # the order's address is made of its scope, which only the comment says
            raise _no(kind, "the order's scope and terms hash did not come with its token (the `knos-terms:` line of the funding comment: 128 hex characters)")
        if hidden is None or hashlib.sha256(hidden).hexdigest() != p[5]:
            raise _no(kind, "these are not the scope and the terms hash GitHub signed for: their hash is not the one the token carries")
        if repo_id != judge_repo:
            raise _no(kind, "a private order is funded by a comment in the repository it names as its judge, and this run was in another")
    if not pay.MIN_WORK <= work <= pay.MAX_WORK:
        raise _no(kind, f"an order is open for a minute to {pay.MAX_WORK // 86_400} days; this token asks for {work} seconds")
    faucet = balance == pay.faucet_balance_pda(owner_id)
    scope, named = (hidden[:32], hidden[32:].hex()) if hidden else (pay.scope_of(repo_id, issue), p[5])
    order, baltok, used = pay.order_pda(scope, balance, seq), pay.baltok_pda(balance), pay.used_pda(t.jwt)
    got = _read(ledger, [pay.pause_pda(), balance, baltok, order, pay.faucet_mint(), pay.rate_pda(repo_id), pay.balx_pda(balance), pay.plan_pda(owner_id), used])
    b, o = pay.read_balance(_data(got, balance)), pay.read_order(_data(got, order))
    result = dict(kind=kind, order=str(order), repo_id=repo_id, issue=issue, seq=seq, amount=amount, mode=mode, balance=str(balance),
                  **({"private": True} if private else {}))

    def done(sigs: list[str], made: pay.Order | None = None) -> dict:
        made = made or pay.read_order(ledger.account(order))
        if made is None:
            return {"ok": False, "kind": kind, "why": "the funding did not reach the chain"}
        return {"ok": True, **result, "sigs": sigs, "amount": made.amount, "fee": made.fee, "faucet": made.faucet, "deadline": made.deadline}
    if o is not None:       # the token's marker is there and the order is as the token says: this very token made it, carried by another relayer
        if (pay.spent(_data(got, used)), o.funder_id, o.terms.hex(), o.mode, o.wf_sha) == (True, actor, named, mode, wf_sha):
            mine, sigs = _funded_by(ledger, order, used)
            if mine:
                raise _Stop({**done(sigs, o), "already": True})
        if pay.spent(_data(got, used)):     # its order was paid or refunded, and another token funded this address again
            raise _no(kind, f"this token was used already: it funded an earlier order at this address ({order}), since paid or refunded, "
                            "and a fund token works once; the order there now was funded by another token")
        raise _no(kind, f"this issue already has order number {seq} from this balance (order {order}); fund again with another number")
    if pay.spent(_data(got, used)):
        raise _no(kind, "this token was used already, and a fund token works once")
    if not terms:
        raise _no(kind, "the order's terms did not come with its token (the `knos-terms:` line of the funding comment)")
    until = pay.read_pause(_data(got, pay.pause_pda()))
    if now < until:
        soon = until < int(c.get("exp", 0)) + oidc.LATE - 60
        raise _no(kind, f"new funding is paused until {_when(until)}; payments and refunds go on", **({"retry": True, "wait": until - now} if soon else {}))
    rule = fees.rule(a.v)       # the fee the program that is live will take on top: 2.1's tiers, or 2.2's one rate
    bps = rule.plan_bps(pay.read_plan(_data(got, pay.plan_pda(owner_id))), now)
    groups: list[Group] = []
    if faucet:
        _bounds(kind, amount, 6, pay.ORDER_MIN_AMOUNT, "an order")
        total = amount + rule.order(amount, bps)
        if _data(got, pay.faucet_mint()) is None:
            raise _no(kind, "this token spends the devnet faucet's test USDC, and this cluster has no faucet")
        if amount > pay.FAUCET_CAP:
            raise _no(kind, f"the faucet gives at most {_units(pay.FAUCET_CAP)} test USDC for one order; open a balance for more")
        if actor == 0:
            raise _no(kind, "this token names no commenter")
        if _amount(_data(got, baltok)) < total:     # FaucetOpen mints the amount and the fee on it
            last, last_iat = pay.read_rate(_data(got, pay.rate_pda(repo_id)))
            if last and iat <= last_iat:
                raise _no(kind, "an older fund token than the repository's last one; comment again")
            if now < last + pay.FUND_PERIOD:
                raise _no(kind, "the faucet serves a repository once a minute", retry=True, wait=last + pay.FUND_PERIOD - now)
            groups.append(([pay.faucet_open_ix(me, t.account, t.key, owner_id, repo_id, used=t.jwt)], _CU["faucet"]))
        mint, program = pay.faucet_mint(), pay.TOKEN
    else:
        if b is None:
            raise _no(kind, f"the balance this token names ({balance}) does not exist")
        decimals = _decimals(_data(_read(ledger, [b.mint]), b.mint))
        _bounds(kind, amount, decimals, pay.ORDER_MIN_AMOUNT, "an order")
        if b.owner_id != owner_id:
            raise _no(kind, "that balance is for another GitHub owner's repositories")
        if actor == 0 or not (b.faucet or actor == b.owner_id or actor in b.spenders):
            raise _no(kind, "this commenter may not spend that balance: only its repository owner and the spenders its wallet listed can")
        if b.cap_per_job and amount > b.cap_per_job:
            raise _no(kind, f"that balance allows {_units(b.cap_per_job)} for one order; this token asks for {_units(amount)}")
        total, one = amount + rule.order(amount, bps, decimals), 10 ** decimals
        if _amount(_data(got, baltok)) < total:
            raise _no(kind, f"the balance holds {_amount(_data(got, baltok)) / one:,.2f}, less than this order and its fee ({total / one:,.2f}); "
                            "add money to it or fund less")
        _limits(kind, pay.read_balx(_data(got, pay.balx_pda(balance))) if b.has_x else None, total, repo_id, wf_sha, now)
        mint = b.mint
        program = (got[baltok][0] if got.get(baltok) else None) or pay.TOKEN     # type: ignore[index]  # got.get(baltok) holds it
    fund = (pay.fund_private_order_balance_ix(me, t.account, t.key, balance, mint, owner_id, scope, hidden[32:], used, seq, program) if hidden else
            pay.fund_order_balance_ix(me, t.account, t.key, balance, mint, owner_id, repo_id, issue, terms, used, seq, program))
    groups.append(([fund], _CU["fund_order"]))
    return _Plan(t, groups, done)


def _payees(aud: str) -> list[tuple[int, int, Pubkey | None]]:
    """The payees of an order's pay audience as the program reads them: 1 to 4, each id once and not 0, each share
    at least one basis point, 10000 in all. ValueError otherwise."""
    out = [(i, bps, _address(str(w)) if w is not None else None) for i, bps, w in pay.payees_of(aud)]
    if not 1 <= len(out) <= pay.MAX_PAYEES or len({i for i, _b, _w in out}) != len(out) or any(i == 0 or bps < 1 for i, bps, _w in out) \
            or sum(bps for _i, bps, _w in out) != 10_000:
        raise ValueError(aud)
    return out


def _shares(due: int, payees) -> list[int]:
    """What each payee receives of `due`: its share rounded down, the last one taking what rounding left."""
    out = [due * bps // 10_000 for _i, bps, _w in payees[:-1]]
    return [*out, due - sum(out)]


def _order_paid(ledger, order: Pubkey, pr: int, since: int) -> list[dict]:
    """What knos-pay itself logged when this order was paid for this pull request, no earlier than `since`: the token
    another relayer carried, after which the order is gone."""
    recent, logs = getattr(ledger, "recent", None), getattr(ledger, "logs", None)
    out = []
    try:
        for sig, when in (recent(order, 5) if recent and logs else []):
            if when is not None and when < since:
                continue
            for line in chain.said(logs(sig), pay.PAY_ID):     # type: ignore[misc]  # the loop runs only when `logs` is there
                m = re.fullmatch(rf"knos3:paid order={order} pr={pr} payee=(\d+) amount=(\d+) to=(\S+)", line)
                if m:
                    out.append({"id": int(m.group(1)), "payee_id": int(m.group(1)), "amount": int(m.group(2)), "to": m.group(3), "held_until": None, "sig": sig})
    except Exception:  # noqa: BLE001 - not finding it only means the plain refusal is given
        return []
    return out


def _tip_accounts(me: Pubkey, o: pay.Order, got: dict) -> tuple[list[Instruction], int]:
    """An order's payment sends the relayer its tip and FEE_OWNER the rest of the fee: their token accounts of the
    order's mint must exist, so each is made the first time it is needed. (`got`: a read that asked for both.)"""
    tp = o.token_program
    ixs = [pay.create_ata_ix(me, owner, o.mint, tp) for owner in (me, pay.FEE_OWNER) if _data(got, pay.ata(owner, o.mint, tp)) is None]
    return ixs, _CU["ata"] * len(ixs)


def _number(v) -> int | None:
    """A claim, or a part of an audience, as the programs read a number (claims::parse_u64): digits alone, no sign, no
    leading zero, at most 18 of them; a claim may be a JSON number or a string. None for anything else."""
    text = str(v) if isinstance(v, int) and not isinstance(v, bool) else v
    return int(text) if isinstance(text, str) and _U64.fullmatch(text) else None


_ASKS = {"take": "reserve an order", "cancel": "cancel an order", "revert": "end an order's warranty"}


def _run(kind: str, o: pay.Order, t: _Token) -> tuple[str, int, int, bool]:
    """What `judge` and `command` (order_judge.rs) both ask of a token about an order before anything else: the pinned
    workflows at the order's commit, and a run's first attempt. Returns (the workflow file that ran, the id of the
    repository it ran in, the id of the account that started it, whether that account started it by hand in a
    repository it owns)."""
    c = t.c
    wf_repo, wf_file, wf_sha = _workflow(c)
    if (o.wf_repo_hash, o.wf_sha) != (wf_repo, wf_sha):
        raise _no(kind, "the order pins another workflow repository or commit than the one this token's run used")
    if str(c.get("run_attempt")) != "1":
        raise _no(kind, f"this token is from a re-run, and only a run's first attempt can {_ASKS.get(kind, 'pay an order')}; run the workflow again")
    ran_in, owner, actor = (_number(c.get(name)) for name in ("repository_id", "repository_owner_id", "actor_id"))
    if ran_in is None or owner is None or actor is None:
        raise _no(kind, "malformed audience or claims")
    return wf_file, ran_in, actor, c.get("event_name") == "workflow_dispatch" and actor != 0 and actor == owner


def _judge(kind: str, o: pay.Order, t: _Token, rule: bool = False, auto: bool = False) -> str:
    """Which judge of this order signed this token, as order_judge.rs decides it from the claims alone: "own" (a: the
    order's own repository, its prove.yml), "neutral" (b: attest.yml started by hand by the owner of the repository it
    ran in, for an order funded NEUTRAL and not PRIVATE), "private" (c: the order's judge repository, its prove.yml or
    attest.yml), or "arbiter" (d: `rule`, the audience of a ruling). Refuses a token no judge of the order signed."""
    wf_file, ran_in, actor, by_hand = _run(kind, o, t)
    if rule:
        named = o.arbiter_id != 0 and o.arbiter_id not in (o.funder_id, o.owner_id)
        if wf_file == "attest.yml" and named and by_hand and actor == o.arbiter_id:
            return "arbiter"
        raise _no(kind, "a ruling is the arbiter's alone: the pinned attest.yml, started by hand by the arbiter the order named at funding, "
                        "in a repository he owns" + ("" if named else "; this order named none"))
    own = o.repo_id != 0 and ran_in == o.repo_id
    if auto:        # judge e: an AUTO order's own prove.yml, and nobody else's run
        if o.flags & order_auto.F_AUTO and own and wf_file == "prove.yml":
            return "auto"
        raise _no(kind, "a pull request is paid without a merge only by an order funded with `auto`, and only on the pinned prove.yml run in "
                        "the order's own repository" + ("" if o.flags & order_auto.F_AUTO else "; this order was funded without it, and waits for its judge"))
    if own and wf_file == "prove.yml":
        return "own"
    if o.judge_repo_id != 0 and ran_in == o.judge_repo_id and wf_file in ("prove.yml", "attest.yml"):
        return "private"
    if o.flags & pay.F_NEUTRAL and not o.flags & pay.F_PRIVATE and by_hand and wf_file == "attest.yml":
        return "neutral"
    raise _no(kind, "not from a judge this order takes: the pinned prove.yml run in the order's own repository"
              + (", the pinned attest.yml started by hand by the owner of the repository it runs in" if o.flags & pay.F_NEUTRAL and not o.flags & pay.F_PRIVATE else "")
              + (", or a run in the order's judge repository" if o.judge_repo_id else ""))


def _command(kind: str, o: pay.Order, t: _Token) -> tuple[str, int]:
    """Whose run signed a COMMAND about this order (Reserve, Cancel), as order_judge::command decides it, and the id of
    the account that started it: "own" (the order's own repository, its fund.yml answering a comment or its prove.yml)
    or "neutral" (attest.yml started by hand by the owner of the repository it ran in, for an order funded NEUTRAL and
    not PRIVATE). Nothing else: the order's judge repository and its arbiter judge work, they sign no command."""
    wf_file, ran_in, actor, by_hand = _run(kind, o, t)
    if o.repo_id != 0 and ran_in == o.repo_id and wf_file in ("fund.yml", "prove.yml"):
        return "own", actor
    neutral = bool(o.flags & pay.F_NEUTRAL) and not o.flags & pay.F_PRIVATE
    if neutral and by_hand and wf_file == "attest.yml":
        return "neutral", actor
    raise _no(kind, "not a command this order takes: the pinned fund.yml or prove.yml run in the order's own repository"
              + (", or the pinned attest.yml started by hand by the owner of the repository it runs in" if neutral else "")
              + "; the order's judge repository and its arbiter sign none")


def _own_key(kind: str, o: pay.Order, t: _Token) -> Pubkey:
    """The one token of the escrow's that GitHub did not sign (order_judge::token): a pay token under a PRIVATE key
    pays a PRIVATE order funded from the Balance that the key's registrant opened. It is then the word of the wallet
    whose money it pays out, and of nobody else's. Returns that key's account; refuses every other pairing."""
    mine = [addr for addr, k in t.held if k.private and k.registrant is not None and o.from_balance and o.flags & pay.F_PRIVATE
            and pay.balance_pda(o.owner_id, k.registrant, o.mint) == o.source]
    if not mine:
        raise _no(kind, "this token is not GitHub's, and no key that signed it was registered by the wallet that opened this order's balance: a key a "
                        "wallet registered itself pays only a private order funded from that wallet's own balance")
    return mine[0]


def _routed(got: dict, order: Pubkey, o: pay.Order, payee: int, named: Pubkey | None) -> Pubkey | None:
    """Where PayOrder pays one payee: nowhere yet (None) when the token names no address and no wallet is bound; else
    the wallet this payee assigned the order's payment to (Assign), else the address, else the bound wallet. (`got`:
    a read that asked for the payee's Bind and assignment.)"""
    dest = pay.order_destination(pay.read_bind(_data(got, pay.bind_pda(payee))), named)
    return dest if dest is None else pay.read_assign(_data(got, pay.assign_pda(order, payee)), o) or dest


def _plan_order_pay(a: _Ask, rule: bool = False, auto: bool = False) -> _Plan:
    """knos3:pay: a judge's token pays an order to its 1 to 4 payees (PayOrder), or holds it for a single payee with
    no wallet. knos3:rule (`rule`): the arbiter's ruling pays the payees it names, with no pull request. A standing
    order pays its rate and stays open; an order with a holdback pays the rest and keeps the holdback through its
    warranty. The tip goes to this relayer's own token account. knos3:auto (`auto`): the black-box suite passed on an
    open pull request of an order funded `auto`: its one author is paid with no merge. An order with a quorum pays on
    its last judge's token; each one before that leaves its marker and pays nothing yet."""
    kind, ledger, me, t, now = "rule" if rule else "pay", a.ledger, a.me, a.t, a.now
    c, p = t.c, t.aud.split(":")
    try:
        if len(p) != (4 if rule else 8) or not (rule or (_HEX40.fullmatch(p[3]) and _HEX64.fullmatch(p[4]) and p[5] in ("0", "1"))):
            raise ValueError(t.aud)
        order, pr, payees = _address(p[2]), 0 if rule else int(p[6]), _payees(t.aud)
        iat, = _ints(c, "iat")
    except (KeyError, ValueError, TypeError):
        raise _no(kind, "malformed audience or claims") from None
    o = pay.read_order(ledger.account(order))
    result = dict(kind=kind, order=str(order), **({} if rule else dict(head=p[3], pr=pr)), **(dict(auto=True) if auto else {}))

    def before() -> list[dict]:     # what the escrow logged when another relayer carried this very token
        return _order_paid(ledger, order, pr, iat - pay.TOKEN_AHEAD)

    def already(rows: list[dict]) -> _Stop:
        return _Stop({"ok": True, **result, "sigs": list(dict.fromkeys(e.pop("sig") for e in rows)), "already": True, "paid": rows})
    if o is None:
        if rows := before():        # the order was paid and is gone
            raise already(rows)
        raise _no(kind, "no such order is in escrow (never funded, or already paid or refunded)")
    result.update(repo_id=o.repo_id, issue=o.issue, mint=str(o.mint))
    judge = _judge(kind, o, t, rule, auto)
    if auto and (len(payees) != 1 or p[5] != "1"):
        raise _no(kind, "malformed audience or claims")
    if auto and o.reserved_by and now <= o.reserved_until and payees[0][0] != o.reserved_by:
        raise _no(kind, "the order is reserved, and until the reservation ends only its taker's pull request is paid")
    if t.issuer != oidc.GITHUB:
        t.key, t.issuer = _own_key(kind, o, t), oidc.PRIVATE
    if rule and any(i == o.arbiter_id for i, _b, _w in payees):
        raise _no(kind, "a ruling cannot pay the arbiter himself")
    if not rule and (o.terms.hex(), o.mode) != (p[4], int(p[5])):
        raise _no(kind, "the order has other terms than the ones this token was made for")
    if o.state == "held":
        if [i for i, _b, _w in payees] == [o.payee_id]:     # another relayer carried it: the order waits for its payee to bind a wallet
            entry = {"id": o.payee_id, "payee_id": o.payee_id, "amount": o.amount - o.paid, "to": None, "held_until": o.hold_until}
            raise _Stop({"ok": True, **result, "sigs": _last(ledger, order), "already": True, "paid": [entry]})
        raise _no(kind, "the order is already held for another GitHub user")
    standing, left = bool(o.flags & pay.F_STANDING), o.amount - o.paid
    tp = o.token_program
    got = _read(ledger, [*(k for i, _b, _w in payees for k in (pay.bind_pda(i), pay.assign_pda(order, i))), pay.ata(me, o.mint, tp),
                         pay.ata(pay.FEE_OWNER, o.mint, tp), pay.done_pda(order, pr)])
    if o.state != "open" or (standing and _data(got, pay.done_pda(order, pr)) is not None):
        if rows := before():        # paid by this token already: what it holds back waits for its warranty, or (standing) it stays open for the next
            raise already(rows)
        raise _no(kind, f"this standing order has paid pull request #{pr} already, and pays each one once" if o.state == "open" else
                  "the order is not open: it was paid, and what it holds back waits for its warranty")
    if not o.in_time(iat, now):     # the deadline, or (an order funded with the presentation grace) a token issued by it, shown within GRACE
        raise _no(kind, "the order's deadline has passed, and this token was issued after it: the grace this order was funded with is for a token "
                        "issued by the deadline; the order goes back to its funder" if o.grace and now <= o.pay_until else
                  "the order's deadline has passed: it goes back to its funder")
    if iat < o.not_before:
        raise _no(kind, "this token is older than the order: it was made before the funding")
    if standing and o.holdback_bps:
        raise _no(kind, pay.ERRORS[103])
    due = (o.rate if left >= o.rate else 0) if standing else left - left * o.holdback_bps // 10_000    # due_now in order_terms.rs
    if due == 0:
        raise _no(kind, "less than one payment is left in this standing order; the rest goes back to its funder")
    wallets = [(i, _routed(got, order, o, i, w)) for i, _b, w in payees]
    if any(w == pay.auth_pda() for _i, w in wallets):
        raise _no(kind, "an address this token names is the escrow's own account")
    held = any(w is None for _i, w in wallets)
    if held and (standing or o.holdback_bps):
        raise _no(kind, "a standing order, and one with a holdback, is never held: every payee needs an address in the token or a bound wallet; "
                        "they bind one with `knos claim <address>`, then run the workflow again")
    if held and len(payees) != 1:
        raise _no(kind, "one of the payees has no address in the token and no bound wallet, and a split is paid whole or not at all; "
                        "they bind one with `knos claim <address>`, then run the workflow again")
    # an order with a quorum: how many distinct judges have passed this artifact, this one included (order_terms.rs, quorum)
    need = 0 if rule else order_auto.quorum_of(o.flags)
    if need and judge == "neutral" and (_run(kind, o, t)[1] == o.repo_id or (o.from_balance and _run(kind, o, t)[2] in (o.funder_id, o.owner_id))):
        raise _no(kind, "for an order with a quorum a neutral run counts only as a third party's: not one in the order's own repository, "
                        "and not one started by its funder")
    marks = _read(ledger, [order_auto.q_pda(order, k) for k in range(3)]) if need else {}
    said, mine = {k: _data(marks, order_auto.q_pda(order, k)) for k in range(3)}, order_auto.KINDS.get(judge, 0)      # (the arbiter is no kind: his ruling needs no quorum)
    again: list[int] = []
    lone: list[str] = []
    if not need:
        have = 0
    elif a.v >= fees.NEW_VERSION:       # 2.2 counts owners: this token's run beside the runs the other markers name
        ran = (_number(c.get("repository_owner_id")) or 0, _run(kind, o, t)[2])
        have = order_auto.passed(said, o, t.aud, mine, run=ran)
        again = order_auto.stale(said, o, t.aud, mine)      # a judge who passed under 2.1: his marker names no run and counts for nothing now
        lone = order_auto.uncounted(o.owner_id, order_auto.spoke(said, o, t.aud, mine, ran)) if have < need else []
    else:                               # 2.1 counts markers
        have = order_auto.passed21(said, o, t.aud, mine)
    waits = have < need
    fresh = a.v >= fees.NEW_VERSION and o.inc != 0 and (need or standing)   # 2.2 writes and counts no marker in the slot of the funding (83)
    first, cu = ([], 0) if held or waits else _tip_accounts(me, o, got)
    ix = order_auto.with_quorum(pay.pay_order_ix(me, t.account, t.key, order, o, wallets, pr=pr, used=t.jwt), order, o)

    def done(sigs: list[str]) -> dict:
        after = pay.read_order(ledger.account(order))
        if waits:       # this judge's word is recorded; the order pays when enough distinct judges have passed the same artifact
            q = order_auto.read_any(ledger.account(order_auto.q_pda(order, mine)))
            if q is None or q[4] != order_auto.artifact(t.aud):
                return {"ok": False, "kind": kind, "why": "the order did not accept the token"}
            more: dict[str, Any] = {**({"again": [order_auto.NAMES[k] for k in again]} if again else {}), **({"uncounted": lone} if lone else {})}
            return {"ok": True, **result, "sigs": sigs, "paid": [], "quorum": {"have": have, "of": need, **more}}
        if after is not None and after.state == "held":
            row = {"id": payees[0][0], "payee_id": payees[0][0], "amount": due, "to": None, "held_until": after.hold_until}
            return {"ok": True, **result, "sigs": sigs, "paid": [row]}
        took = ledger.account(pay.done_pda(order, pr)) is not None if standing else after is None or after.state == "warranty" or after.paid != o.paid
        if not took:
            return {"ok": False, "kind": kind, "why": "the order did not accept the token"}
        paid = [{"id": i, "payee_id": i, "amount": share, "to": str(w), "held_until": None} for (i, w), share in zip(wallets, _shares(due, payees))]
        more = ({"left": after.amount if after is not None else 0} if standing else
                {"held_back": left - due, "warranty_until": after.hold_until} if after is not None and after.state == "warranty" else {})
        return {"ok": True, **result, "sigs": sigs, "paid": paid, **more}
    extra = (_CU["terms"] if standing or o.holdback_bps else 0) + (_CU["quorum"] if need else 0)
    soon = ("the order was funded in this very block, and its first payment or judge's word is taken from the next one on; "
            "the same token is carried again on the next pass") if fresh else None
    return _Plan(t, [([*first, ix], cu + _CU["pay_order"] + _CU["payee"] * len(payees) + extra)], done, alone=True, soon=soon)


# -- what an order can promise (2.1, order_terms.rs): knos3:take, cancel, revert; and an organisation's wallet ------------
def _order_token(a: _Ask, kind: str, parts: int) -> tuple[Pubkey, pay.Order | None, list[str], int]:
    """(the order's address, the order or None, the audience's parts, the token's issue time) of a token whose
    audience is knos3:<kind>:<order address>:..."""
    p = a.t.aud.split(":")
    try:
        if len(p) != parts:
            raise ValueError(a.t.aud)
        order, (iat,) = _address(p[2]), _ints(a.t.c, "iat")
    except (KeyError, ValueError, TypeError):
        raise _no(kind, "malformed audience or claims") from None
    return order, pay.read_order(a.ledger.account(order)), p, iat


def _plan_take(a: _Ask) -> _Plan:
    """knos3:take: a person takes an open order for himself, for how many days he says (Reserve). The token is a
    command's (`_command`): the order's own repository answered his comment (the pinned fund.yml) or his pull request
    (prove.yml), or, for a NEUTRAL order, he started the pinned attest.yml by hand in a repository of his own; and the
    taker it names is the account that started the run. One taker at a time, and none once the order was cancelled."""
    kind, ledger, me, t, now = "take", a.ledger, a.me, a.t, a.now
    order, o, p, iat = _order_token(a, kind, 5)
    taker, days = _number(p[3]), _number(p[4])
    if not taker or days is None:
        raise _no(kind, "malformed audience or claims")
    if o is None:
        raise _no(kind, "no such order is in escrow (never funded, or already paid or refunded)")
    result = dict(kind=kind, order=str(order), repo_id=o.repo_id, issue=o.issue, taker_id=taker, days=days)
    _which, actor = _command(kind, o, t)
    if actor != taker:
        raise _no(kind, f"a person reserves an order for himself: this token names GitHub user id {taker} as the taker, and its run was started by "
                        f"GitHub user id {actor}")
    if o.reserved_by == taker and now <= o.reserved_until and iat <= o.reserved_until - days * 86_400 <= int(t.c.get("exp", 0)) + oidc.LATE:
        raise _Stop({"ok": True, **result, "sigs": _last(ledger, order), "already": True, "reserved_until": o.reserved_until})     # this token's doing
    if o.state != "open" or now > o.deadline:
        raise _no(kind, "the order is not open any more: it was paid, held for its payee, or its deadline has passed")
    if o.cancel_at:
        raise _no(kind, "the order was cancelled, and a cancelled order takes no new reservation")
    if o.reserved_by and now <= o.reserved_until:
        raise _no(kind, f"the order is reserved for GitHub user id {o.reserved_by} until {_when(o.reserved_until)}")
    if iat < o.not_before:
        raise _no(kind, "this token is older than the order: it was made before the funding")
    if not 1 <= days <= o.reserve_days:
        raise _no(kind, f"this order is reserved for 1 to {o.reserve_days} days, and the token asks for {days}" if o.reserve_days else
                  "this order takes no reservations: it was funded with none")

    def done(sigs: list[str]) -> dict:
        after = pay.read_order(ledger.account(order))
        if after is None or after.reserved_by != taker:
            return {"ok": False, "kind": kind, "why": "the order did not accept the token"}
        return {"ok": True, **result, "sigs": sigs, "reserved_until": after.reserved_until}
    return _Plan(t, [([pay.reserve_ix(me, t.account, t.key, order, used=t.jwt)], _CU["reserve"])], done)


def _plan_cancel(a: _Ask) -> _Plan:
    """knos3:cancel: the commenter who funded a Balance's order, or the Balance's owner, gives notice from the order's
    own repository, by its pinned fund.yml (a comment) or prove.yml (Cancel): the deadline becomes at most seven days
    away, and what is accepted until then is paid. A NEUTRAL run cancels nothing, whoever starts it."""
    kind, ledger, me, t, now = "cancel", a.ledger, a.me, a.t, a.now
    order, o, _p, iat = _order_token(a, kind, 3)
    if o is None:
        raise _no(kind, "no such order is in escrow (never funded, or already paid or refunded)")
    result = dict(kind=kind, order=str(order), repo_id=o.repo_id, issue=o.issue)
    if not o.from_balance:
        raise _no(kind, "this order was funded from a wallet, and only that wallet's own signature cancels it (knos_pay Cancel); no token does")
    which, actor = _command(kind, o, t)
    if which != "own":
        raise _no(kind, "a neutral run cancels nothing, since anyone can start one: a cancellation is signed in the order's own repository, by its "
                        "pinned fund.yml or prove.yml")
    if actor not in (o.funder_id, o.owner_id):
        raise _no(kind, "only the commenter who funded the order, or the owner of the balance it came from, cancels it")
    if o.cancel_at:
        if o.cancel_at >= iat - pay.TOKEN_AHEAD:        # cancelled since this token was signed: its own doing, or the same request's
            raise _Stop({"ok": True, **result, "sigs": _last(ledger, order), "already": True, "cancel_at": o.cancel_at, "deadline": o.deadline})
        raise _no(kind, f"the order was cancelled already, on {_when(o.cancel_at)}")
    if o.state != "open" or now > o.deadline:
        raise _no(kind, "the order is not open any more: it was paid, held for its payee, or its deadline has passed")
    if iat < o.not_before:
        raise _no(kind, "this token is older than the order: it was made before the funding")

    def done(sigs: list[str]) -> dict:
        after = pay.read_order(ledger.account(order))
        if after is None or not after.cancel_at:
            return {"ok": False, "kind": kind, "why": "the order did not accept the token"}
        return {"ok": True, **result, "sigs": sigs, "cancel_at": after.cancel_at, "deadline": after.deadline}
    return _Plan(t, [([pay.cancel_ix(me, order, t.account, t.key, used=t.jwt)], _CU["cancel"])], done)


def _plan_revert(a: _Ask) -> _Plan:
    """knos3:revert: inside the warranty a judge of the order says the accepted change was reverted (Revert):
    everything the order still holds, the holdback and the fee on it, goes back to where its money came from. The
    judge is a, b or c as for a payment (`_judge`: the order's own repository, a NEUTRAL attest.yml by hand, the judge
    repository). Never the arbiter: he rules on payments, and with this audience he is whoever else he is to the order."""
    kind, ledger, me, t, now = "revert", a.ledger, a.me, a.t, a.now
    order, o, p, iat = _order_token(a, kind, 4)
    if not _HEX40.fullmatch(p[3]):
        raise _no(kind, "malformed audience or claims")
    result: dict[str, Any] = dict(kind=kind, order=str(order), head=p[3])
    if o is None:
        was = _said_since(ledger, order, rf"knos3:reverted order={order} amount=(\d+) head={p[3]}", iat - pay.TOKEN_AHEAD)
        if was:         # another relayer carried this token: the holdback went back and the order is gone
            raise _Stop({"ok": True, **result, "sigs": [was[1]], "already": True, "amount": int(was[0].group(1))})
        raise _no(kind, "no such order is in escrow (never funded, or already paid or refunded)")
    result.update(repo_id=o.repo_id, issue=o.issue, mint=str(o.mint))
    _judge(kind, o, t)          # a, b or c, or refused: only the audience of a ruling makes anyone the arbiter
    if o.state != "warranty":
        raise _no(kind, "the order holds nothing back: a revert counts only inside the warranty of an order that was paid with a holdback")
    if now > o.hold_until:
        raise _no(kind, f"the warranty ended {_when(o.hold_until)}: what was held back goes to the payees")
    if iat < o.hold_until - o.warranty_s:
        raise _no(kind, "this token is older than the payment whose warranty it would end")
    ov = pay.ov_pda(order)
    home = o.refund_to if o.from_balance else pay.ata(o.refund_to, o.mint, o.token_program)
    got = _read(ledger, [pay.hb_pda(order), ov, home])
    hb = pay.read_holdback(_data(got, pay.hb_pda(order)))
    if hb is None:
        raise _no(kind, "the order's record of what it holds back is not on chain")
    amount = _amount(_data(got, ov))
    first = [] if o.from_balance or _data(got, home) is not None else [pay.create_ata_ix(me, o.refund_to, o.mint, o.token_program)]

    def done(sigs: list[str]) -> dict:
        if ledger.account(order) is not None:
            return {"ok": False, "kind": kind, "why": "the order did not accept the token"}
        return {"ok": True, **result, "sigs": sigs, "amount": amount}
    return _Plan(t, [([*first, pay.revert_ix(me, t.account, t.key, order, o, hb, used=t.jwt)], _CU["ata"] * len(first) + _CU["revert"])], done)


def _org_made(bind: bytes | None) -> bool:
    """Whether BindOrg wrote this Bind as it stands (order_judge.rs, org_made): its mark is there, and is of the
    `iat` the account holds. What a person bound himself is never this."""
    return bool(bind) and len(bind) >= 56 and bind[2] == 1 and bytes(bind[3:8]) == bytes(bind[48:53])     # type: ignore[arg-type, index]  # bool(bind) holds it


def _plan_org_bind(a: _Ask) -> _Plan:
    """knos3:bind: a member starts the pinned claim workflow by hand in an ORGANISATION's repository named knos-claim
    (BindOrg): the organisation is paid at the address, and what is held for it follows."""
    kind, ledger, me, t, now = "bind", a.ledger, a.me, a.t, a.now
    c, p = t.c, t.aud.split(":")
    try:
        if len(p) != 3:
            raise ValueError(t.aud)
        wallet = _address(p[2])
        actor, org, iat = _ints(c, "actor_id", "repository_owner_id", "iat")
    except (KeyError, ValueError, TypeError):
        raise _no(kind, "malformed audience or claims") from None
    how = "`knos claim --org <organisation> <address>` does it: it runs Knos's claim workflow in the organisation's repository named knos-claim"
    if not str(c.get("job_workflow_ref", "")).startswith(CLAIM_REF) or c.get("job_workflow_sha") not in CLAIM_SHAS | ORG_CLAIM_SHAS:
        raise _no(kind, f"an organisation's wallet is bound only by Knos's claim workflow at its pinned commit; {how}")
    if org == 0 or actor == 0 or org == actor or not str(c.get("repository", "")).endswith("/knos-claim"):
        raise _no(kind, "an organisation's claim runs in the organisation's repository named knos-claim, started by a member (a person binds "
                        f"with `knos claim <address>` in a repository of his own); {how}")
    if c.get("event_name") != "workflow_dispatch" or str(c.get("run_attempt")) != "1":
        raise _no(kind, "the claim must be started by hand by a member of the organisation (Run workflow, with the address typed in), and not "
                        "be a re-run; `knos claim --org <organisation> <address>` does that")
    raw = _data(_read(ledger, [pay.bind_pda(org)]), pay.bind_pda(org))
    bound = pay.read_bind(raw)
    held = [(addr, j) for addr, j in held_for(ledger, org) if now <= j.hold_until]
    result = dict(kind=kind, user_id=org, wallet=str(wallet), org=True, by=actor)
    settles = [_payout(me, j, wallet, pay.settle_ix(me, addr, j, wallet), _CU["settle"]) for addr, j in held]

    def done(sigs: list[str], already: bool = False) -> dict:
        after = _read(ledger, [addr for addr, _j in held]) if held else {}
        settled = [{"job": str(addr), "amount": j.amount, "fee": fees.rule(a.v).job(j.amount), "mint": str(j.mint)} for addr, j in held if _data(after, addr) is None]
        return {"ok": True, **result, "sigs": sigs, **({"already": True} if already else {}), "settled": settled}
    if bound is not None:
        if not _org_made(raw):
            raise _no(kind, "this GitHub id bound its wallet itself (a person's claim), and only its own claim changes that")
        if iat <= bound.iat:
            if (bound.iat, bound.wallet) != (iat, wallet):
                raise _no(kind, "a newer claim has bound a wallet since this one; run the claim again to change it")
            if not settles:
                raise _Stop(done(_said_in(ledger, pay.bind_pda(org), f"knos3:bound org={org} wallet={wallet} by={actor}"), True))
            return _Plan(t, settles, lambda sigs: done(sigs, True), token=False, alone=True)
    bind = ([pay.bind_org_ix(me, t.account, t.key, org, used=t.jwt), oidc.close_ix(me, t.tid)], _CU["bind_org"] + _CU["close"])
    return _Plan(t, [bind, *settles], done, alone=True, lead=True, closes=True)
