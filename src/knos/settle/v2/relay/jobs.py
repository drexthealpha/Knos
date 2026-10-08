"""Plans for the jobs of 2.0 (fund, pay, bind) and for the verifier's keys (GitHub's, and any RS256 issuer's)."""
from __future__ import annotations

import json
import re
import time
import urllib.request

from typing import Callable

from solders.instruction import Instruction
from solders.pubkey import Pubkey

from .... import chain, fees
from .. import oidc, pay

from .pins import ATTESTERS, CLAIM_REF, CLAIM_SHAS, JWKS_TTL, REFRESH_AFTER, ROTATE_REF, ROTATE_SHAS, ROTATE_SHAS2, _CU, _HEX40, _HEX64, _Stop, _no
from .tokens import _KEPT, _Token, _address, _ints, _jwks, _units, _when, _workflow
from .reads import _amount, _data, _last, _read, _said_in, held_for, jobs_for
from .plans import Group, _Ask, _Plan, _bounds, _decimals, _limits


def _fund_run(kind: str, c: dict, terms: bytes | None, named: str, private: bool = False) -> str:
    """What the escrow asks of the run behind any fund token (a job's or an order's), and of the terms that came with
    it. Returns the commit of the workflows that ran."""
    _wf_repo, wf_file, wf_sha = _workflow(c)
    if wf_file != "fund.yml":
        raise _no(kind, "a fund token must come from fund.yml")
    # a PRIVATE order's attestor has no comment to react to: its run is started by hand or by its schedule
    if c.get("event_name") not in ("issue_comment", "issues") + (("workflow_dispatch", "schedule") if private else ()):
        raise _no(kind, "a bounty is funded by a comment on an issue or by a new issue, and this run was started by something else")
    if str(c.get("run_attempt")) != "1":
        raise _no(kind, "this token is from a re-run, and only a run's first attempt can fund; comment again")
    if terms and (len(terms) > pay.MAX_TERMS or not all(0x20 <= b < 0x7f for b in terms) or pay.terms_hash(terms).hex() != named):
        raise _no(kind, "these are not the terms GitHub signed for: their hash is not the one the token carries")
    return wf_sha


def _plan_fund(ledger, me: Pubkey, t: _Token, terms: bytes | None, now: int, v: int = 1) -> _Plan:
    kind, c, p = "fund", t.c, t.aud.split(":")
    try:
        if len(p) != 8 or p[4] not in ("0", "1") or not _HEX64.fullmatch(p[5]):
            raise ValueError(t.aud)
        issue, amount, mode, work, balance = int(p[2]), int(p[3]), int(p[4]), int(p[6]), _address(p[7])
        repo_id, owner_id, actor, iat = _ints(c, "repository_id", "repository_owner_id", "actor_id", "iat")
    except (KeyError, ValueError, TypeError):
        raise _no(kind, "malformed audience or claims") from None
    wf_sha = _fund_run(kind, c, terms, p[5])
    if not pay.MIN_WORK <= work <= pay.MAX_WORK:
        raise _no(kind, f"a bounty is open for a minute to {pay.MAX_WORK // 86_400} days; this token asks for {work} seconds")
    faucet = balance == pay.faucet_balance_pda(owner_id)
    if faucet:
        _bounds(kind, amount, 6)
    job, baltok = pay.job_pda(repo_id, issue, balance), pay.baltok_pda(balance)
    got = _read(ledger, [pay.pause_pda(), balance, baltok, job, pay.faucet_mint(), pay.rate_pda(repo_id), pay.balx_pda(balance)])
    b, j = pay.read_balance(_data(got, balance)), pay.read_job(_data(got, job))
    result = dict(kind=kind, job=str(job), repo_id=repo_id, issue=issue, amount=amount, mode=mode, balance=str(balance))

    def done(sigs: list[str], made: pay.Job | None = None) -> dict:
        made = made or pay.read_job(ledger.account(job))
        if made is None:
            return {"ok": False, "kind": kind, "why": "the funding did not reach the chain"}
        return {"ok": True, **result, "sigs": sigs, "amount": made.amount, "faucet": made.faucet, "deadline": made.deadline}
    if j is not None:       # a job keeps its token's time and commenter: this very token made it, carried by another relayer
        if (j.not_before, j.funder_id, j.terms.hex(), j.mode, j.wf_sha) == (iat, actor, p[5], mode, wf_sha):
            raise _Stop({**done(_last(ledger, job), j), "already": True})
        raise _no(kind, f"this issue already has a bounty from this balance (job {job})")
    if b is not None and iat <= b.last_iat:
        raise _no(kind, "this token was used already, and a fund token works once" if iat == b.last_iat else
                  "an older fund token than the last one this balance took; comment again")
    if not terms:
        raise _no(kind, "the bounty's terms did not come with its token (the `knos-terms:` line of the funding comment)")
    until = pay.read_pause(_data(got, pay.pause_pda()))
    if now < until:
        soon = until < int(c.get("exp", 0)) + oidc.LATE - 60        # the pause ends while this token still works
        raise _no(kind, f"new funding is paused until {_when(until)}; payments and refunds go on",
                  **({"retry": True, "wait": until - now} if soon else {}))
    groups: list[Group] = []
    if faucet:
        if _data(got, pay.faucet_mint()) is None:
            raise _no(kind, "this token spends the devnet faucet's test USDC, and this cluster has no faucet")
        if amount > pay.FAUCET_CAP:
            raise _no(kind, f"the faucet gives at most {_units(pay.FAUCET_CAP)} test USDC for one bounty; open a balance for more")
        if actor == 0:
            raise _no(kind, "this token names no commenter")
        if _amount(_data(got, baltok)) < amount:        # FaucetOpen mints the token's amount; a refund may have left it there already
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
        _bounds(kind, amount, _decimals(_data(_read(ledger, [b.mint]), b.mint)))
        if b.owner_id != owner_id:
            raise _no(kind, "that balance is for another GitHub owner's repositories")
        if actor == 0 or not (b.faucet or actor == b.owner_id or actor in b.spenders):
            raise _no(kind, "this commenter may not spend that balance: only its repository owner and the spenders its wallet listed can")
        if b.cap_per_job and amount > b.cap_per_job:
            raise _no(kind, f"that balance allows {_units(b.cap_per_job)} for one bounty; this token asks for {_units(amount)}")
        if _amount(_data(got, baltok)) < amount:
            raise _no(kind, f"the balance holds {_units(_amount(_data(got, baltok)))}, less than this bounty; add money to it or fund less")
        _limits(kind, pay.read_balx(_data(got, pay.balx_pda(balance))) if v >= 1 and b.has_x else None, amount, repo_id, wf_sha, now)
        mint = b.mint
        program = (got[baltok][0] if got.get(baltok) else None) or pay.TOKEN     # type: ignore[index]  # a Balance's token account belongs to its mint's token program
    groups.append(([pay.fund_balance_ix(me, t.account, t.key, balance, mint, repo_id, issue, terms, program, balx=bool(v >= 1 and b and b.has_x), used=t.jwt)], _CU["fund"]))
    return _Plan(t, groups, done)


def _payout(me: Pubkey, j: pay.Job, wallet: Pubkey, ix: Instruction, cu: int) -> Group:
    """A payment and the two token accounts it needs, made if they are not there (either token program)."""
    return ([pay.create_ata_ix(me, wallet, j.mint, j.token_program), pay.create_ata_ix(me, pay.FEE_OWNER, j.mint, j.token_program), ix],
            2 * _CU["ata"] + cu)


def _paid_before(ledger, repo_id: int, issue: int, payee: int, since: int) -> list[dict]:
    """What knos-pay itself logged when this payee was paid for this issue, among the last few payments on their
    record and no earlier than `since` (the signed token's own time): the token another relayer carried, after which the job
    is gone. An earlier bounty on the same issue, paid long before, is not this token's doing."""
    recent, logs = getattr(ledger, "recent", None), getattr(ledger, "logs", None)
    out = []
    try:
        for sig, when in (recent(pay.rep_pda(payee), 5) if recent and logs else []):
            if when is not None and when < since:
                continue
            for line in chain.said(logs(sig), pay.PAY_ID):     # type: ignore[misc]  # the loop runs only when `logs` is there
                m = re.fullmatch(rf"knos2:paid repo={repo_id} issue={issue} payee={payee} amount=(\d+) fee=(\d+) to=(\S+)", line)
                if m:
                    out.append({"job": "", "amount": int(m.group(1)) + int(m.group(2)), "fee": int(m.group(2)), "mint": "",
                                "to": m.group(3), "held_until": None, "sig": sig})
    except Exception:  # noqa: BLE001 - not finding it only means the plain refusal is given
        return []
    return out


def _plan_pay(ledger, me: Pubkey, t: _Token, now: int, v: int = 1) -> _Plan:
    kind, c, p = "pay", t.c, t.aud.split(":")
    try:
        if len(p) != 9 or not _HEX40.fullmatch(p[5]) or not _HEX64.fullmatch(p[6]) or p[7] not in ("0", "1"):
            raise ValueError(t.aud)
        repo_id, issue, payee, mode = int(p[2]), int(p[3]), int(p[4]), int(p[7])
        ran_in, iat = _ints(c, "repository_id", "iat")
        if payee == 0 or (p[8] != "-" and not _address(p[8])):
            raise ValueError(t.aud)
    except (KeyError, ValueError, TypeError):
        raise _no(kind, "malformed audience or claims") from None
    wf_repo, wf_file, wf_sha = _workflow(c)
    if wf_file != "prove.yml" or ran_in != repo_id:
        raise _no(kind, "not from the workflow or the repository the audience names")
    result = dict(kind=kind, repo_id=repo_id, issue=issue, payee_id=payee, head=p[5])
    jobs = jobs_for(ledger, repo_id, issue)
    opened = [(a, j) for a, j in jobs if j.state == "open"]
    pinned = [(a, j) for a, j in jobs if (j.wf_repo_hash, j.wf_sha) == (wf_repo, wf_sha)]
    agreed = [(a, j) for a, j in pinned if (j.terms.hex(), j.mode) == (p[6], mode)]
    mine = [(a, j) for a, j in agreed if j.state == "open" and now <= j.deadline and iat >= j.not_before]
    used = pay.used_pda(t.jwt)
    spent = v >= 1 and _data(_read(ledger, [used]), used) is not None       # the token's marker is there: it has paid, or held, its one job
    if v >= 1:              # 2.1: a pay token pays exactly one job, the largest here. (2.0 pays every one, and knows no marker)
        mine = [] if spent else sorted(mine, key=lambda x: (-x[1].amount, str(x[0])))[:1]
    if not mine:
        held = [(a, j) for a, j in agreed if j.state == "held" and j.payee_id == payee]
        if held:        # another relayer carried this token: the jobs wait for the payee to bind a wallet
            entries = [{"job": str(a), "amount": j.amount, "fee": fees.rule(v).job(j.amount), "mint": str(j.mint), "to": None, "held_until": j.hold_until} for a, j in held]
            raise _Stop({"ok": True, **result, "sigs": _last(ledger, held[0][0]), "already": True, "paid": entries})
        before = _paid_before(ledger, repo_id, issue, payee, iat - pay.TOKEN_AHEAD)
        if before:      # and here the payee had a wallet: the job was paid and is gone
            raise _Stop({"ok": True, **result, "sigs": list(dict.fromkeys(e.pop("sig") for e in before)), "already": True, "paid": before})
        raise _no(kind, "this token has paid its one bounty already; another bounty on the issue is paid by a new run of the workflow" if spent and opened else
                  "no bounty is in escrow for this issue (never funded, or already paid or refunded)" if not jobs else
                  "the bounty on this issue is already held for another GitHub user" if not opened else
                  "no open bounty on this issue pins this workflow at this commit" if not any(j.state == "open" for _a, j in pinned) else
                  "the open bounty on this issue has other terms than the ones this token was made for" if not any(j.state == "open" for _a, j in agreed) else
                  "the bounty's deadline has passed: it goes back to its funder" if all(now > j.deadline for _a, j in agreed if j.state == "open") else
                  "this token is older than the bounty: it was made before the funding")
    bound = pay.read_bind(_data(_read(ledger, [pay.bind_pda(payee)]), pay.bind_pda(payee)))
    wallet = pay.destination(bound, t.aud)
    if wallet == pay.auth_pda():
        raise _no(kind, "the address this token names is the escrow's own account")
    groups: list[Group] = []
    for addr, j in mine:
        ix = pay.pay_ix(me, t.account, t.key, addr, j, payee, wallet, used=used)
        if v < 1:
            ix = Instruction(ix.program_id, bytes(ix.data), list(ix.accounts)[:-1])
        groups.append(([ix], _CU["pay"]) if wallet is None else _payout(me, j, wallet, ix, _CU["pay"]))

    def done(sigs: list[str]) -> dict:
        after, paid = _read(ledger, [a for a, _j in mine]), []
        for addr, j in mine:
            left = pay.read_job(_data(after, addr))         # gone: paid. Held: no wallet was known. Still open: this token did not pay it
            if left is None or left.state == "held":
                paid.append({"job": str(addr), "amount": j.amount, "fee": fees.rule(v).job(j.amount), "mint": str(j.mint),
                             "to": str(wallet) if left is None and wallet is not None else None, "held_until": left.hold_until if left else None})
        return {"ok": True, **result, "sigs": sigs, "paid": paid} if paid else {"ok": False, "kind": kind, "why": "no open job on this issue accepted the token"}
    return _Plan(t, groups, done, alone=True)


def _plan_bind(ledger, me: Pubkey, t: _Token, now: int, v: int = fees.NEW_VERSION) -> _Plan:
    kind, c, p = "bind", t.c, t.aud.split(":")
    try:
        if len(p) != 3:
            raise ValueError(t.aud)
        wallet = _address(p[2])
        user, owner, iat = _ints(c, "actor_id", "repository_owner_id", "iat")
    except (KeyError, ValueError, TypeError):
        raise _no(kind, "malformed audience or claims") from None
    how = "`knos claim <address>` does it: it runs Knos's claim workflow in your own repository named knos-claim"
    if not str(c.get("job_workflow_ref", "")).startswith(CLAIM_REF) or c.get("job_workflow_sha") not in CLAIM_SHAS:
        raise _no(kind, f"a wallet is bound only by Knos's claim workflow at its pinned commit; {how}")
    if user == 0 or user != owner or not str(c.get("repository", "")).endswith("/knos-claim"):
        raise _no(kind, f"the claim must run in a repository named knos-claim that the claiming account owns; {how}")
    # by hand only: the form of "Run workflow" cannot be filled in by a link, so only a run its owner started counts
    if c.get("event_name") != "workflow_dispatch" or str(c.get("run_attempt")) != "1":
        raise _no(kind, "the claim must be started by hand by the account's owner (Run workflow, with the address typed in), and not be a re-run; "
                        "`knos claim <address>` does that")
    bound = pay.read_bind(_data(_read(ledger, [pay.bind_pda(user)]), pay.bind_pda(user)))
    held = [(a, j) for a, j in held_for(ledger, user) if now <= j.hold_until]
    result = dict(kind=kind, user_id=user, wallet=str(wallet))
    settles = [_payout(me, j, wallet, pay.settle_ix(me, addr, j, wallet), _CU["settle"]) for addr, j in held]

    def done(sigs: list[str], already: bool = False) -> dict:
        after = _read(ledger, [a for a, _j in held]) if held else {}
        settled = [{"job": str(a), "amount": j.amount, "fee": fees.rule(v).job(j.amount), "mint": str(j.mint)} for a, j in held if _data(after, a) is None]
        return {"ok": True, **result, "sigs": sigs, **({"already": True} if already else {}), "settled": settled}
    if bound is not None and iat <= bound.iat:
        if (bound.iat, bound.wallet) != (iat, wallet):
            raise _no(kind, "a newer claim has bound a wallet since this one; run the claim again to change it")
        if not settles:         # another relayer carried it, and nothing is left to pay
            raise _Stop(done(_said_in(ledger, pay.bind_pda(user), f"knos2:bound user={user} wallet={wallet}"), True))
        return _Plan(t, settles, lambda sigs: done(sigs, True), token=False, alone=True)       # a Settle needs no token
    bind = ([pay.bind_ix(me, t.account, t.key, user, used=t.jwt), oidc.close_ix(me, t.tid)], _CU["bind"] + _CU["close"])
    return _Plan(t, [bind, *settles], done, alone=True, lead=True, closes=True)


def _attests(t: _Token, v: int) -> tuple[bool, bool]:
    """Whether a token is an attestation the verifier takes for a key (`attested` in knos_oidc): (from the attester:
    registers and refreshes, anyone's: refreshes only). The pinned rotate workflow on a GitHub-hosted runner, at the
    first pin or (2.1) the later one; run by its schedule or by hand in an attester's repository, or (2.1, anyone's)
    started by hand in a repository of the person who started it."""
    c = t.c
    try:
        owner, repo = _ints(c, "repository_owner_id", "repository_id")
    except (KeyError, ValueError, TypeError):
        return False, False
    pinned = (t.issuer == oidc.GITHUB and str(c.get("job_workflow_ref", "")).startswith(ROTATE_REF) and c.get("runner_environment") == "github-hosted"
              and c.get("job_workflow_sha") in (ROTATE_SHAS | ROTATE_SHAS2 if v >= 1 else ROTATE_SHAS))
    names = pinned and (owner, repo) in ATTESTERS and c.get("event_name") in ("schedule", "workflow_dispatch")
    anyone = pinned and v >= 1 and c.get("event_name") == "workflow_dispatch" and str(c.get("actor_id")) == str(owner)
    return names, anyone


def _plan_key(ledger, me: Pubkey, t: _Token, jwks: dict | None, now: int, v: int = 1) -> _Plan:
    """A key token on the second verifier: RegisterKey for a key it does not have, Refresh for one it has."""
    kind, p = "key", t.aud.split(":")
    try:
        issuer, want = int(p[2]), p[3]
        if len(p) != 4 or issuer not in oidc.ISSUERS:
            raise ValueError(t.aud)
    except (ValueError, IndexError):
        raise _no(kind, "malformed audience or claims") from None
    n = next((n for _kid, n in oidc.jwks_keys(_jwks(issuer, jwks)) if oidc.key_hash(n).hex() == want), None)
    if n is None:
        raise _no(kind, "the issuer's key set has no key with that hash")
    key = oidc.key_pda(issuer, n)
    k = oidc.read_key(ledger.account(key))
    if k is not None and k.revoked:
        raise _no(kind, "the guardian revoked this key; it cannot be used again")
    names, anyone = _attests(t, v)

    def done(added: bool = False, refreshed: bool = False) -> Callable[[list[str]], dict]:
        return lambda sigs: {"ok": True, "kind": kind, "sigs": sigs, "key": str(key), "added": added, "refreshed": refreshed}
    params: Group = ([oidc.key_params_ix(me, issuer, n)], _CU["params"][8 * len(oidc.modulus_bytes(n))])
    if k is None:
        if not names:
            raise _no(kind, "the second verifier takes a new key only from the rotate workflow at its pinned commit, run by its "
                            "schedule or by hand in the attester's own repository")
        register = ([oidc.register_key_ix(me, issuer, n, t.account, t.key if v >= 1 else None), oidc.close_ix(me, t.tid)], _CU["register"] + _CU["close"])
        return _Plan(t, [register, params], done(added=True), closes=True)
    if k.state != 1:            # registered, its parameters never sent: anyone may send them, and no token is needed
        return _Plan(t, [params], done(), token=False)
    if not (names or anyone) or now + oidc.KEY_TTL - k.expires_at < REFRESH_AFTER:
        raise _Stop(done()([]))  # the verifier has it, and a day of life gained is not worth a transaction
    refresh = ([oidc.refresh_ix(me, issuer, n, t.account, t.key if v >= 1 else None), oidc.close_ix(me, t.tid)], _CU["refresh"] + _CU["close"])
    return _Plan(t, [refresh], done(refreshed=True), closes=True)


def _issuer_keys(url: str, jwks: dict | None) -> dict:
    """The key set of any OpenID issuer, found the way everyone finds it: `<url>/.well-known/openid-configuration`
    names where it is published. The one given for this URL when `jwks` has it; else fetched and kept ten minutes.
    The document must be this issuer's own, and its key set must be served over https."""
    if jwks and url in jwks:
        return jwks[url]
    kept = _KEPT.get(url)
    if kept is None or time.monotonic() - kept[0] > JWKS_TTL:
        conf = _fetch(url.rstrip("/") + "/.well-known/openid-configuration")
        where = str(conf.get("jwks_uri") or "") if isinstance(conf, dict) else ""
        if not isinstance(conf, dict) or conf.get("issuer") != url or not where.startswith("https://"):
            raise ValueError("the issuer's openid-configuration is not this issuer's, or names no https key set")
        kept = _KEPT[url] = (time.monotonic(), _fetch(where))
    return kept[1]


def _fetch(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "knos", "Accept": "application/json"}), timeout=20) as r:  # noqa: S310 - https, checked by the caller
        return json.loads(r.read(1 << 20))


def _plan_issuer_key(a: _Ask) -> _Plan:
    """knos-oidc:ikey: a key of ANY RS256 issuer, named by the issuer's URL (2.1): RegisterIssuerKey for a key the
    verifier does not have, Refresh for one it has. The URL travels with the token (the `knos-issuer:` line of its
    comment; `terms` here), and its sha256 is in the audience GitHub signed. The issuer is asked for its key set only
    once the token is the pinned rotate workflow's: nobody's comment makes this relay fetch a URL of their choosing."""
    kind, ledger, me, t, now = "key", a.ledger, a.me, a.t, a.now
    p = t.aud.split(":")
    if len(p) != 4 or not _HEX64.fullmatch(p[2]) or not _HEX64.fullmatch(p[3]):
        raise _no(kind, "malformed audience or claims")
    url = (a.terms or b"").decode("ascii", "replace").strip()
    if not url:
        raise _no(kind, "the issuer's URL did not come with its token (the `knos-issuer:` line of the comment)")
    if not url.startswith("https://") or not 8 < len(url.encode()) <= oidc.MAX_ISS or oidc.issuer_hash(url).hex() != p[2]:
        raise _no(kind, "the `knos-issuer:` line is not the issuer this token names")
    names, anyone = _attests(t, a.v)
    if not (names or anyone):
        raise _no(kind, "an issuer's key is taken only from the rotate workflow at its pinned commit, run by its schedule or by hand in the "
                        "attester's own repository")
    try:
        n = next((n for _kid, n in oidc.jwks_keys(_issuer_keys(url, a.jwks)) if oidc.key_hash(n).hex() == p[3]), None)
    except _Stop:
        raise
    except Exception as why:  # noqa: BLE001 - the issuer did not answer, or answered something else: asked again on a later pass
        raise _no(kind, f"the issuer's key set could not be read at {url} ({type(why).__name__})", retry=True, transient=True) from None
    if n is None:
        raise _no(kind, "the issuer's key set has no key with that hash")
    key = oidc.key_pda(url, n)
    k = oidc.read_key(ledger.account(key))
    if k is not None and k.revoked:
        raise _no(kind, "the guardian revoked this key; it cannot be used again")

    def done(added: bool = False, refreshed: bool = False) -> Callable[[list[str]], dict]:
        return lambda sigs: {"ok": True, "kind": kind, "sigs": sigs, "key": str(key), "added": added, "refreshed": refreshed, "issuer": url}
    params: Group = ([oidc.key_params_ix(me, url, n)], _CU["params"][8 * len(oidc.modulus_bytes(n))])
    if k is None:
        if not names:
            raise _no(kind, "a new key is registered only on the attester's own run of the rotate workflow; anyone's run refreshes a key the "
                            "verifier already has")
        register = ([oidc.register_issuer_key_ix(me, url, n, t.account, t.key), oidc.close_ix(me, t.tid)], _CU["issuer_key"] + _CU["close"])
        return _Plan(t, [register, params], done(added=True), closes=True)
    if k.state != 1:
        return _Plan(t, [params], done(), token=False)
    if now + oidc.KEY_TTL - k.expires_at < REFRESH_AFTER:
        raise _Stop(done()([]))
    refresh = ([oidc.refresh_ix(me, url, n, t.account, t.key), oidc.close_ix(me, t.tid)], _CU["refresh"] + _CU["close"])
    return _Plan(t, [refresh], done(refreshed=True), closes=True)
