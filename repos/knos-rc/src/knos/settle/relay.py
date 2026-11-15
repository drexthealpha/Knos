"""Carries one GitHub-signed token to the chain: verifies it with knos-oidc, then sends the knos-pay instruction its
audience asks for. Anyone can run this and pay the gas; the money goes where the token says, never where the relayer
says. The always-on worker calls `submit` for every token a repository's workflow publishes.

    submit(ledger, payer, jwt)   ->  {"ok": True, "kind": "pay", "sigs": [...], ...}  or  {"ok": False, "why": "..."}

`ledger` needs send(ixs, payer) -> signature, account(address) -> bytes | None, and (to find wallet-funded jobs and
what is due) program_accounts(program, size, {offset: bytes}) -> [(address, data)]. `jwks` maps an issuer id to its
JWKS document (fetched from the issuer when not given).
"""
from __future__ import annotations

import base64
import json
import time
import urllib.request

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from . import oidc, pay

KINDS = {"fund": "knos:fund:", "pay": "knos:pay:", "veto": "knos:veto:", "claim": "knos:claim:", "key": "knos-oidc:key:"}


def claims_of(jwt: str) -> dict:
    body = jwt.strip().split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def header_of(jwt: str) -> dict:
    head = jwt.strip().split(".")[0]
    return json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)))


def kind_of(aud: str) -> str | None:
    return next((k for k, prefix in KINDS.items() if aud.startswith(prefix)), None)


def fetch_jwks(issuer: int) -> dict:
    with urllib.request.urlopen(oidc.JWKS[issuer], timeout=20) as r:  # noqa: S310 - a fixed https URL
        return json.load(r)


def _issuer_of(claims: dict) -> int:
    for i, url in oidc.ISSUERS.items():
        if claims.get("iss") == url:
            return i
    raise ValueError(f"unknown issuer {claims.get('iss')!r}")


def ensure_key(ledger, payer: Keypair, issuer: int, n: int, attest: Pubkey | None = None) -> list[str]:
    """Registers the key if the chain does not have it yet (a genesis key needs nothing; any other needs `attest`)."""
    sigs = []
    data = ledger.account(oidc.key_pda(issuer, n))
    if data is None:
        sigs.append(ledger.send([oidc.register_key_ix(payer.pubkey(), issuer, n, attest)], payer))
        data = b"\0"
    if data[0] != 1:
        sigs.append(ledger.send([oidc.key_params_ix(payer.pubkey(), issuer, n)], payer))
    return sigs


def verify(ledger, payer: Keypair, jwt: str, jwks: dict | None = None) -> tuple[Pubkey, list[str]]:
    """The token, VERIFIED in its account on chain. Returns (account, signatures). Reuses an account that already
    holds this token; registers the signing key first when it is a genesis key the chain has not seen."""
    jwt = jwt.strip()
    c, h = claims_of(jwt), header_of(jwt)
    issuer = _issuer_of(c)
    keys = oidc.jwks_keys((jwks or {}).get(issuer) or fetch_jwks(issuer))
    by_kid = dict(keys)
    if h.get("kid") not in by_kid:
        raise LookupError(f"the issuer's key set has no key {h.get('kid')!r}")
    n = by_kid[h["kid"]]
    sigs = ensure_key(ledger, payer, issuer, n)
    tid = oidc.token_id(jwt)
    acct = oidc.token_pda(payer.pubkey(), tid)
    have = oidc.read_token(ledger.account(acct))
    if have is not None and have.verified:
        return acct, sigs
    if have is not None:
        sigs.append(ledger.send([oidc.close_ix(payer.pubkey(), tid)], payer))
    for ix in oidc.write_ixs(payer.pubkey(), tid, jwt):
        sigs.append(ledger.send([ix], payer))
    for sq in oidc.step_plan(n.bit_length()):
        sigs.append(ledger.send([oidc.step_ix(payer.pubkey(), tid, oidc.key_pda(issuer, n), sq)], payer))
    return acct, sigs


def jobs_for(ledger, repo_id: int, issue: int) -> list[tuple[Pubkey, pay.Job]]:
    """Every live job on this issue: the repository's own, and any a wallet added."""
    out = {}
    own = pay.job_pda(repo_id, issue)
    j = pay.read_job(ledger.account(own))
    if j:
        out[own] = j
    finder = getattr(ledger, "program_accounts", None)
    if finder is not None:
        for addr, data in finder(pay.PAY_ID, 256, {8: repo_id.to_bytes(8, "little") + issue.to_bytes(8, "little")}):
            j = pay.read_job(data)
            if j:
                out[addr] = j
    return list(out.items())


def dues_for(ledger, user_id: int) -> list[tuple[Pubkey, int]]:
    """(mint, amount) for everything waiting under a GitHub user id."""
    mints = {pay.faucet_mint(), pay.USDC_DEVNET}
    finder = getattr(ledger, "program_accounts", None)
    if finder is not None:
        for _addr, data in finder(pay.PAY_ID, 48, {8: user_id.to_bytes(8, "little")}):
            mints.add(Pubkey.from_bytes(data[16:48]))
    out = []
    for m in mints:
        amount = pay.read_due(ledger.account(pay.due_pda(user_id, m)))
        if amount or ledger.account(pay.due_pda(user_id, m)):
            out.append((m, amount))
    return out


def _workflow(c: dict) -> tuple[bytes, str, str]:
    """(hash of the repository that holds the workflow, the workflow file's name, its commit) from a token's claims."""
    ref = str(c.get("job_workflow_ref", ""))
    repo, _, rest = ref.partition("/.github/workflows/")
    return pay.wf_repo_hash(repo), rest.split("@", 1)[0], str(c.get("job_workflow_sha", ""))


def precheck(ledger, c: dict, kind: str, aud: str, now: float) -> dict | None:
    """What the chain would refuse, found with reads alone, before any fee is spent. Anyone can get GitHub to sign a
    token with any audience from a workflow of their own, so a relayer that verified first and asked later could be
    made to pay fees for nothing. Returns None to go ahead, the refusal ({"ok": False, "why", ["retry"]}), or, when
    another relayer has already carried this very token, the result with no transaction ({"ok": True, "already"})."""
    no = lambda why, **kw: {"ok": False, "kind": kind, "why": why, **kw}  # noqa: E731
    # the chain already shows what this token asks for: another relayer was first. Done, and nothing to send
    def already(at, **kw):
        last = getattr(ledger, "last_signature", None)
        try:
            sig = last(at) if last else None
        except Exception:  # noqa: BLE001 - the verdict does not depend on finding the transaction
            sig = None
        return {"ok": True, "kind": kind, "sigs": [sig] if sig else [], "already": True, **kw}
    p = aud.split(":")
    wf_repo, wf_file, wf_sha = _workflow(c)
    if kind != "key" and c.get("runner_environment") != "github-hosted":
        return no("not from a GitHub-hosted runner")
    try:
        if kind == "fund":
            repo_id, issue, amount = int(c["repository_id"]), int(p[2]), int(p[3])
            if wf_file != "fund.yml":
                return no("a fund token must come from fund.yml")
            if not (amount == 0 or pay.MIN_AMOUNT <= amount <= pay.FAUCET_CAP):
                return no(f"a devnet bounty is {pay.MIN_AMOUNT // 10**6} to {pay.FAUCET_CAP // 10**6} test USDC")
            rate = ledger.account(pay.rate_pda(repo_id))
            last_iat = int.from_bytes(rate[8:16], "little", signed=True) if rate and len(rate) == 16 else None
            have = pay.read_job(ledger.account(pay.job_pda(repo_id, issue)))
            if have is not None:
                if last_iat == int(c.get("iat", 0)) and have.amount == amount and have.wf_sha == wf_sha:
                    return already(pay.job_pda(repo_id, issue), job=str(pay.job_pda(repo_id, issue)), repo_id=repo_id, issue=issue, amount=amount,
                                   mode=have.mode, review=int(p[7]))     # another relayer carried this very token
                return no("this issue already has the repository's bounty")
            if last_iat is not None:
                last = int.from_bytes(rate[0:8], "little", signed=True)
                if int(c.get("iat", 0)) <= last_iat:
                    return no("an older fund token than the repository's last one")
                if now < last + 60:
                    return no("one funding per repository per minute", retry=True)
        elif kind in ("pay", "veto"):
            repo_id, issue = int(p[2]), int(p[3])
            if wf_file != ("prove.yml" if kind == "pay" else "fund.yml") or int(c["repository_id"]) != repo_id:
                return no("not from the workflow or the repository the audience names")
            jobs = jobs_for(ledger, repo_id, issue)
            want = "open" if kind == "pay" else "proven"
            if kind == "pay":
                held = [(a, j) for a, j in jobs if j.state == "proven" and j.author_id == int(p[4]) and j.wf_sha == wf_sha]
                if held and not any(j.state == "open" for _a, j in jobs):
                    return already(held[0][0], paid=[{"job": str(a), "amount": j.amount, "fee": pay.fee_of(j.amount), "mint": str(j.mint),
                                          "waits": j.review} for a, j in held],
                                   repo_id=repo_id, issue=issue, author_id=int(p[4]), head=p[5])
            if not any(j.state == want and j.wf_repo_hash == wf_repo and j.wf_sha == wf_sha for _a, j in jobs):
                return no(f"no {want} bounty on this issue pins this workflow at this commit" if jobs else
                          "no bounty is in escrow for this issue (never funded, or already paid or refunded)")
        elif kind == "claim":
            if c.get("event_name") != "workflow_dispatch" or not c.get("actor_id") or c.get("actor_id") != c.get("repository_owner_id"):
                return no("a claim must be run by hand (workflow_dispatch) by the owner of the repository it runs in")
            if not any(amount for _m, amount in dues_for(ledger, int(c["actor_id"]))):
                return no("nothing is due to this GitHub account")
    except (KeyError, ValueError, IndexError):
        return no("malformed audience or claims")
    return None


_TWIN = ("custom program error: 0x43", "custom program error: 0x45", "custom program error: 0x54", "'Custom': 67", "'Custom': 69", "'Custom': 84")


def answered(why: BaseException) -> bool:
    """The program itself refused, with a number a twin run can cause (67, 69, 84). That clears within a pass or two
    when a twin was why; when it does not clear it is the program's answer, so a relay counts these tries and stops
    (`knos.proof.ghrelay.MAX_TRIES`), whatever life the token has left."""
    return not isinstance(why, (OSError, TimeoutError)) and any(mark in str(why) for mark in _TWIN)


def transient(why: BaseException) -> bool:
    """A failure that says nothing about the token: the cluster did not answer or dropped the transaction, or another
    run with this same relayer key was moving the same token account (knos-oidc refuses with 67 or 69, and knos-pay
    with 84 when the account was closed under it). The same token may succeed on the next pass."""
    if isinstance(why, (OSError, TimeoutError)):
        return True
    text = str(why)
    return any(mark in text for mark in ("custom program error: 0x43", "custom program error: 0x45", "custom program error: 0x54",
                                         "'Custom': 67", "'Custom': 69", "'Custom': 84", "Blockhash not found",
                                         "block height exceeded", "Too Many Requests", "Node is behind"))


def submit(ledger, payer: Keypair, jwt: str, jwks: dict | None = None, now: float | None = None) -> dict:
    """Verify the token and do what its audience says. Never raises for a bad token: returns {"ok": False, "why"}
    ("retry": True when the same token may succeed later). The token's account is always closed behind it, so the
    relayer's rent comes back whatever happened."""
    jwt = jwt.strip()
    me = payer.pubkey()
    opened = False
    try:
        c = claims_of(jwt)
        aud = c["aud"] if isinstance(c["aud"], str) else c["aud"][0]
        kind = kind_of(aud)
        if kind is None:
            return {"ok": False, "why": f"not a Knos audience: {aud[:60]!r}"}
        now = now if now is not None else time.time()
        if c.get("exp", 0) + oidc.LATE <= now:
            return {"ok": False, "kind": kind, "why": "token expired"}
        p = aud.split(":")
        refused = precheck(ledger, c, kind, aud, now)
        if refused:
            return refused
        if kind == "key":       # nothing to do when the chain already has the key: no transaction at all
            issuer, want = int(p[2]), p[3]
            found = next((n for _kid, n in oidc.jwks_keys((jwks or {}).get(issuer) or fetch_jwks(issuer)) if oidc.key_hash(n).hex() == want), None)
            if found is None:
                return {"ok": False, "kind": kind, "why": "the issuer's key set has no key with that hash"}
            n: int = found
            have = ledger.account(oidc.key_pda(issuer, n))
            if have is not None and have[0] == 1:
                return {"ok": True, "kind": kind, "sigs": [], "key": str(oidc.key_pda(issuer, n)), "added": False}
        opened = True
        tok, sigs = verify(ledger, payer, jwt, jwks)
        out: dict = {"ok": True, "kind": kind, "sigs": sigs}
        if kind == "fund":
            repo_id, issue = int(c["repository_id"]), int(p[2])
            out["sigs"].append(ledger.send([pay.fund_with_token_ix(me, tok, repo_id, issue)], payer))
            out.update(job=str(pay.job_pda(repo_id, issue)), repo_id=repo_id, issue=issue, amount=int(p[3]), mode=int(p[4]), review=int(p[7]))
        elif kind == "pay":
            repo_id, issue, author = int(p[2]), int(p[3]), int(p[4])
            mode = int(p[7])
            paid = []
            for addr, j in jobs_for(ledger, repo_id, issue):
                if j.state != "open" or j.mode != mode:
                    continue
                try:
                    sig = ledger.send([pay.create_ata_ix(me, pay.FEE_OWNER, j.mint), pay.pay_ix(me, tok, addr, author, j.mint, j.funder)], payer)
                except Exception as why:  # noqa: BLE001 - a job pinning another workflow refuses; the others still pay
                    if transient(why):
                        raise
                    out.setdefault("refused", []).append(f"{addr}: {str(why)[:120]}")
                    continue
                paid.append({"job": str(addr), "amount": j.amount, "fee": pay.fee_of(j.amount), "mint": str(j.mint), "waits": j.review})
                out["sigs"].append(sig)
            if not paid:
                return {"ok": False, "kind": kind, "why": "no open job on this issue accepted the proof", **({"refused": out["refused"]} if "refused" in out else {})}
            out.update(paid=paid, repo_id=repo_id, issue=issue, author_id=author, head=p[5])
        elif kind == "veto":
            repo_id, issue = int(p[2]), int(p[3])
            vetoed = []
            for addr, j in jobs_for(ledger, repo_id, issue):
                if j.state == "proven":
                    out["sigs"].append(ledger.send([pay.veto_ix(me, addr, tok)], payer))
                    vetoed.append(str(addr))
            if not vetoed:
                return {"ok": False, "kind": kind, "why": "no proven job on this issue to veto"}
            out.update(vetoed=vetoed)
        elif kind == "claim":
            user, address = int(c["actor_id"]), Pubkey.from_string(p[2])
            got = []
            for mint, amount in dues_for(ledger, user):
                out["sigs"].append(ledger.send([pay.create_ata_ix(me, address, mint), pay.claim_ix(me, tok, user, mint, address)], payer))
                got.append({"mint": str(mint), "amount": amount})
            if not got:
                return {"ok": False, "kind": kind, "why": "nothing is due to this GitHub account"}
            out.update(claimed=got, user_id=user, address=str(address))
        elif kind == "key":
            new = ensure_key(ledger, payer, issuer, n, tok)
            out["sigs"] += new
            out.update(key=str(oidc.key_pda(issuer, n)), added=bool(new))
        return out
    except Exception as why:  # noqa: BLE001 - one bad token never stops the relay loop
        return {"ok": False, "why": f"{type(why).__name__}: {str(why)[:200]}",
                **({"retry": True, "transient": True} if transient(why) else {}), **({"answered": True} if answered(why) else {})}
    finally:
        if opened:      # the token account has done its work, or failed to: take the rent back either way
            try:
                if ledger.account(oidc.token_pda(me, oidc.token_id(jwt))) is not None:
                    ledger.send([oidc.close_ix(me, oidc.token_id(jwt))], payer)
            except Exception:  # noqa: BLE001, S110 - the next pass closes it
                pass


def settle_due(ledger, payer: Keypair, now: int) -> list[str]:
    """Pays every proven job whose review window has passed (tests mode). Needs ledger.program_accounts."""
    sigs = []
    for addr, data in ledger.program_accounts(pay.PAY_ID, 256, {0: bytes([2])}):
        j = pay.read_job(data)
        if j and j.pay_after <= now:
            me = payer.pubkey()
            sigs.append(ledger.send([pay.create_ata_ix(me, pay.FEE_OWNER, j.mint), pay.settle_ix(me, addr, j.author_id, j.mint, j.funder)], payer))
    return sigs


def refund_due(ledger, payer: Keypair, now: int) -> list[str]:
    """Refunds every open job past its deadline. Needs ledger.program_accounts."""
    sigs = []
    for addr, data in ledger.program_accounts(pay.PAY_ID, 256, {0: bytes([1])}):
        j = pay.read_job(data)
        if j and j.deadline < now:
            me = payer.pubkey()
            dest = pay.due_pda(j.funder_id, j.mint) if j.token_funded else pay.ata(j.funder, j.mint)
            sigs.append(ledger.send([pay.refund_ix(me, addr, j.mint, dest, j.funder)], payer))
    return sigs
