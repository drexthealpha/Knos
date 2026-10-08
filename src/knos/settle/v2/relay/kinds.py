"""The audiences the relay carries (`KINDS`), how a token is opened against its kind, and `precheck`: every question
the programs will ask, with reads alone."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, cast

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from ...relay import claims_of, header_of
from .. import oidc

from .pins import GENESIS, _Stop, _no
from .build import version
from .tokens import _Token, _jwks, other_keys, signed
from .reads import _data, _read
from .plans import _Ask, _Plan, _github_token
from .jobs import _plan_bind, _plan_fund, _plan_issuer_key, _plan_key, _plan_pay
from .workorders import _plan_cancel, _plan_order_fund, _plan_order_pay, _plan_org_bind, _plan_revert, _plan_take
from .metering import _plan_batch, _plan_eval, _plan_gate


def _handler(aud: str) -> "Kind | None":
    return next((kind for prefix, kind in KINDS.items() if aud.startswith(prefix)), None)


def kind_of(aud: str) -> str | None:
    """What the relay calls a token with this audience ("fund", "pay", "bind", "key", ...: see KINDS); None for an
    audience it does not carry."""
    found = _handler(aud)
    return found.name if found else None


def _open_other(jwt: str, me: Pubkey, c: dict, aud: str, kind: str | None, ledger) -> _Token:
    """A token whose issuer is not GitHub or GitLab: the keys the verifier holds for its `iss` are the key set, and
    the one that signed it is found by the same arithmetic as on chain. Nothing is fetched from the URL."""
    url = c.get("iss")
    if not isinstance(url, str) or not url.startswith("https://") or not 8 < len(url.encode()) <= oidc.MAX_ISS or ledger is None:
        raise _no(None, "this is not a token GitHub Actions or GitLab CI issued")
    held = [(addr, k, n) for addr, k, n in other_keys(ledger, url) if signed(jwt, n)]
    if not held:
        raise _no(kind, "this is not a token GitHub Actions or GitLab CI issued, and the verifier holds no key of its issuer that signed it: "
                        "an issuer's key is registered by the rotate workflow (rotate.yml with `issuer`), a private one by a wallet (knos-oidc RegisterPrivateKey)")
    addr, k, n = held[0]
    return _Token(jwt, c, aud, kind, k.issuer, n, oidc.token_id(jwt), addr, oidc.token_pda(me, oidc.token_id(jwt)), url, [(a, key) for a, key, _n in held])


def _open(jwt: str, me: Pubkey, jwks: dict | None, ledger=None) -> _Token:
    """The token, with the key its header names looked up among the issuer's published keys. Refuses one that none
    of them signed. For any other issuer (`ledger` given) the key is one the verifier holds for it: `_open_other`."""
    try:
        c, h = claims_of(jwt), header_of(jwt)
        aud = c["aud"] if isinstance(c["aud"], str) else c["aud"][0]
        issuer = next((i for i, url in oidc.ISSUERS.items() if c.get("iss") == url), None)
        kid = h.get("kid")
    except (KeyError, IndexError, ValueError, TypeError, AttributeError):
        raise _no(None, "this is not a token GitHub Actions or GitLab CI issued") from None
    kind = kind_of(aud)
    if not 0 < len(jwt.encode()) <= oidc.MAX_JWT:
        raise _no(kind, f"the token is {len(jwt.encode())} bytes; the verifier takes up to {oidc.MAX_JWT}")
    if issuer is None:
        return _open_other(jwt, me, c, aud, kind, ledger)
    keys_ = dict(oidc.jwks_keys(_jwks(issuer, jwks)))
    if kid not in keys_ and not (jwks and issuer in jwks):
        keys_ = dict(oidc.jwks_keys(_jwks(issuer, jwks, fresh=True)))      # the issuer may have added a key since we last looked
    n = keys_.get(kid)     # type: ignore[arg-type]  # a token with no kid finds no key
    if n is None:
        raise _no(kind, f"the issuer's key set has no key {str(kid)[:60]!r}")
    if not signed(jwt, n):
        raise _no(kind, "the signature is not the issuer's")
    tid = oidc.token_id(jwt)
    return _Token(jwt, c, aud, kind, issuer, n, tid, oidc.key_pda(issuer, n), oidc.token_pda(me, tid))


# -- one table: every audience this relay carries, and who plans it ----------------------------------------------------
@dataclass(frozen=True)
class Kind:
    """One kind of token. `name` is what its result and the worker's log call it, and the comment marker it is
    posted under (a pay token's marker is `proof`); `plan(ask)` answers with a _Plan, or raises the _Stop that says
    why nothing is sent, from reads alone; `since` is the escrow version that first takes it (`version`); `github`
    says whether what the escrow asks of every GitHub token applies before the audience is read."""
    name: str
    plan: Callable[[_Ask], _Plan]
    since: int = 0
    github: bool = True
    first: bool = False         # carried to the first deployment's relay as well (a key of GitHub's or GitLab's)
    private: bool = False       # also takes a token under a key a wallet registered itself, where its planner accepts that wallet


# A new kind is a planner and one line here.
KINDS: dict[str, Kind] = {
    "knos2:fund:": Kind("fund", lambda a: _plan_fund(a.ledger, a.me, a.t, a.terms, a.now, a.v)),
    "knos2:pay:": Kind("pay", lambda a: _plan_pay(a.ledger, a.me, a.t, a.now, a.v)),
    "knos2:bind:": Kind("bind", lambda a: _plan_bind(a.ledger, a.me, a.t, a.now, a.v)),
    "knos-oidc:key:": Kind("key", lambda a: _plan_key(a.ledger, a.me, a.t, a.jwks, a.now, a.v), github=False, first=True),
    "knos-oidc:ikey:": Kind("key", _plan_issuer_key, since=1, github=False),
    "knos3:fund:": Kind("fund", _plan_order_fund, since=1),
    "knos3:pay:": Kind("pay", _plan_order_pay, since=1, private=True),
    "knos3:auto:": Kind("pay", lambda a: _plan_order_pay(a, auto=True), since=1),
    "knos3:rule:": Kind("rule", lambda a: _plan_order_pay(a, rule=True), since=1),
    "knos3:take:": Kind("take", _plan_take, since=1),
    "knos3:cancel:": Kind("cancel", _plan_cancel, since=1),
    "knos3:revert:": Kind("revert", _plan_revert, since=1),
    "knos3:bind:": Kind("bind", _plan_org_bind, since=1),
    "knosm:eval:": Kind("eval", _plan_eval),        # knos_meter is a program of its own and never calls the escrow: it needs no 2.1 escrow
    "knosm:batch:": Kind("batch", _plan_batch),     # knos_meter 1.1: the buyer's count of a batch (RecordBatch)
    "knosm:claim:": Kind("claim", lambda a: _plan_batch(a, claim=True)),    # and the seller's own count of it (ClaimBatch)
    "gate:": Kind("gate", _plan_gate, github=False),       # upgrade_gate reads the verified token itself: it needs no 2.1 escrow, and asks its own claims
}


def _signer(ledger, me: Pubkey, t: _Token, plan: _Plan, now: int) -> None:
    """Reads the key that signed the token and the account this relayer verifies it in. The key must be one the
    verifier would use now; a genesis key the chain has not seen is registered on the way."""
    got = _read(ledger, [t.key, t.account])
    plan.have = _data(got, t.account)
    k = oidc.read_key(_data(got, t.key))
    if k is None and t.issuer == oidc.GITHUB and oidc.key_hash(t.n).hex() in GENESIS:
        plan.register = [oidc.register_key_ix(me, t.issuer, t.n), oidc.key_params_ix(me, t.issuer, t.n)]
        return
    if k is not None and k.state == 0:      # registered, its parameters never sent: anyone may send them
        plan.register, k.state = [oidc.key_params_ix(me, t.url or t.issuer, t.n, registrant=k.registrant)], 1
    usable, why = oidc.key_usable(k, now)
    if not usable:
        raise _no(t.kind, "the token cannot be verified: " + why)


def _plan(ledger, payer: Keypair, jwt: str, terms: bytes | str | None, jwks: dict | None, now: float | None) -> _Plan:
    """Everything `submit` will send for this token, or the _Stop that says why it sends nothing. Reads only."""
    me = payer.pubkey()
    t = _open(jwt.strip(), me, jwks, ledger)
    if t.kind is None:
        raise _no(None, f"not an audience of the second deployment: {t.aud[:60]!r}")
    now = int(now if now is not None else ledger.now())
    if int(t.c.get("exp", 0)) + oidc.LATE <= now:
        raise _no(t.kind, "token expired")
    handler, v = cast(Kind, _handler(t.aud)), version(ledger, payer)     # its kind is known: one handler
    if v < handler.since:
        raise _no(t.kind, "the escrow on this cluster is version 2.0, which takes no such token yet; it will once the announced upgrade to 2.1 is live")
    if handler.github:
        _github_token(t, now, handler.private)
    plan = handler.plan(_Ask(ledger, payer, me, t, now, v, terms.encode() if isinstance(terms, str) else terms, jwks))
    plan.v1 = v >= 1 and bool(getattr(ledger, "takes_v1", False))
    if plan.token:
        _signer(ledger, me, t, plan, now)
    return plan


def precheck(ledger, payer: Keypair, jwt: str, terms: bytes | None = None, jwks: dict | None = None, now: float | None = None) -> dict | None:
    """What `submit` would answer without sending anything: None to go ahead, the refusal, or (when the chain already
    shows what the token asks for) the result with "already": True. Reads only; no fee."""
    try:
        _plan(ledger, payer, jwt, terms, jwks, now)
    except _Stop as stop:
        return stop.result
    return None


def _handler_of(jwt: str) -> Kind | None:
    try:
        aud = claims_of(jwt.strip())["aud"]
        return _handler(aud if isinstance(aud, str) else aud[0])
    except Exception:  # noqa: BLE001 - not a token: `_open` says so
        return None
