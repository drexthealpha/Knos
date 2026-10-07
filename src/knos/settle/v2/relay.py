"""Carries one GitHub-signed token to the second deployment: has knos-oidc verify it, and sends the knos-pay
instruction its audience asks for. Anyone can run this and pay the fees; the money goes where the token and the chain
say, never where the relayer says. A workflow that has a relay key calls `submit` itself (knos.flow); Knos's public
worker calls it for every token a workflow posts instead (knos.proof.ghrelay).

    withdraw(ledger, payer, request)   a passkey wallet's withdrawal request (no token): see `withdraw`
    passkey_fund(ledger, payer, request, repo_id=None, issue=None)   the comment `/knos passkey-fund <base64url>` (no token):
                         a passkey wallet funds a work order and this relay pays the order's rent and the fee: see `passkey_fund`
    submit(ledger, payer, jwt, terms=None, jwks=None, now=None)
      knos2:fund:...     {"ok": True, "kind": "fund", "sigs", "job", "repo_id", "issue", "amount", "mode", "faucet", "balance", "deadline"}
      knos2:pay:...      {"ok": True, "kind": "pay", "sigs", "repo_id", "issue", "payee_id", "head",
                          "paid": [{"job", "amount", "fee", "mint", "to": wallet or None, "held_until": time or None}]}
      knos2:bind:...     {"ok": True, "kind": "bind", "sigs", "user_id", "wallet", "settled": [{"job", "amount", "fee", "mint"}]}
      knos3:fund:...     {"ok": True, "kind": "fund", "sigs", "order", "repo_id", "issue", "seq", "amount", "fee", "mode", "faucet", "balance", "deadline"}
                         a PRIVATE order adds "private": True: its "issue" is 0 and its "repo_id" is its judge repository's, where
                         the comment was; `terms` is then its scope and its terms hash (`private_terms`), not a terms JSON
      knos3:pay:...      {"ok": True, "kind": "pay", "sigs", "order", "repo_id", "issue", "mint", "head", "pr",
                          "paid": [{"payee_id", "amount", "to": wallet or None, "held_until": time or None}]}   (work orders, 2.1)
                         each row also has "id" (the same as "payee_id"); a standing order adds "left", one with a
                         holdback "held_back" and "warranty_until". Judges: the order's own repository, a neutral run
                         of attest.yml, the order's judge repository.
      knos3:auto:...     as knos3:pay, with "auto": True: an AUTO order's unmerged pull request, paid on its black-box suite alone
                         (an order with a quorum, before its last judge: "paid": [], "quorum": {"have", "of"})
      knos3:rule:...     {"ok": True, "kind": "rule", "sigs", "order", "repo_id", "issue", "mint", "paid": [as for knos3:pay]}   (the arbiter's ruling)
      knos3:take:...     {"ok": True, "kind": "take", "sigs", "order", "repo_id", "issue", "taker_id", "days", "reserved_until"}
      knos3:cancel:...   {"ok": True, "kind": "cancel", "sigs", "order", "repo_id", "issue", "cancel_at", "deadline"}
      knos3:revert:...   {"ok": True, "kind": "revert", "sigs", "order", "head", "repo_id", "issue", "mint", "amount"}   (what went back to the funder)
      knos3:bind:...     {"ok": True, "kind": "bind", "sigs", "user_id" (the organisation's id), "wallet", "org": True, "by", "settled": [...]}
      knosm:eval:...     {"ok": True, "kind": "eval", "sigs", "buyer_id", "seller_id", "order", "artifact", "milestone", "accepted", "rate", "fee", "month"}
                         (knos_meter Record: one billable evaluation, paid from the buyer's credits)
      knosm:batch:...    {"ok": True, "kind": "batch", "sigs", "buyer_id", "seller_id", "month", "seq", "count", "accepted", "value", "root", "fee", "chain"}
      knosm:claim:...    the same with "kind": "claim" (knos_meter RecordBatch, the buyer's count; ClaimBatch, the seller's own, no fee)
      gate:...           {"ok": True, "kind": "gate", "sigs", "program", "hash", "commit", "run_id", "record"}: upgrade_gate's record
                         that GitHub's runner built the executable with this hash for this program (program.yml's gate job)
      knos-oidc:ikey:... {"ok": True, "kind": "key", "sigs", "key", "added", "refreshed", "issuer"}: a key of any RS256 issuer,
                         named by its URL, which comes as `terms` (the `knos-issuer:` line of the token's comment)
      knos-oidc:key:...  {"ok": True, "kind": "key", "sigs", "key", "added": bool, "refreshed": bool, "first": {...}}
                         carried to both deployments. `key`, `added` (RegisterKey: the key now waits a day and the
                         guardian) and `refreshed` (Refresh: it lives 30 days from now) are the second verifier's;
                         `first` is what knos.settle.relay answered. When only the first deployment took the token,
                         "why" says what the second refused it for.
      refused            {"ok": False, "kind", "why"}; "retry": True when the same token may succeed later ("wait":
                         seconds, when that is known), and "transient": True when the cluster, not the token, was why;
                         with it "answered": True when the program itself refused in a way a twin run can cause
                         (67, 69, 84): tried a few passes, never for the token's whole life
      done before        the same result with "already": True and no fee spent, when the chain already shows what the
                         token asks for (another relayer carried it)

A token of an issuer that is not GitHub or GitLab (its `iss` is another URL) is verified under a key the verifier
holds for that URL (`other_keys`): a registered issuer's, or a PRIVATE one some wallet registered itself. The chain is
the key set: nothing is fetched from a URL a token names. `verify_only` carries any such token. The escrow takes one
in a single case: a pay token under a private key pays a PRIVATE order funded from the Balance that the key's own
registrant opened (never a ruling); everything else of the escrow's is GitHub's alone, and is refused here for nothing.

`terms` is the terms JSON whose hash a fund token's audience carries. `jwks` maps an issuer id (or, for any other
issuer, its URL) to its JWKS document (fetched from the issuer and kept ten minutes when not given). `now` is the chain's time (read from it when not given).

Before a fee is spent, `precheck` asks everything the two programs will ask, with reads alone: the claims, the
audience, the workflow, the key that signed, the job, the Balance, the faucet's rate, and GitHub's signature itself
(the same arithmetic as on chain, done here). Anyone can have GitHub sign any audience from a repository of their own
and post it where a relayer looks, so a relayer that paid first and asked later could be made to pay for nothing.

Round trips. On a 2.1 cluster (`version` answers 1) with a ledger that sends v1 transactions (4,096 bytes), a GitHub
token of the usual size (the harness's are 1,770 to 1,910 bytes) takes two transactions and two waits, whatever it
asks for:

    1  Write, Step(8)             the whole token, and the first half of the RSA verification
    2  Step(8), <escrow>, Close   the second half, what the audience asks for, and the token account closed again

A token longer than about 3,700 bytes has its head written first, in Writes side by side. Where v1 transactions cannot
be used (the deployed 2.0 escrow, a ledger without them, or a cluster that refused one: the relay then falls back by
itself and stays there) the same token takes four legacy transactions and three waits:

    1  Write | Write              the head of the token, side by side (one Write for a token up to 1,756 bytes)
    2  Write, Step(8)             the rest of it, and the first half of the RSA verification
    3  Step(8), <escrow>, Close   the second half, what the audience asks for, and the token account closed again

The first deployment's relay sends each chunk, each step, the escrow instruction and the close in a transaction of
its own and waits for each: seven and seven for the same token. The last Step and the escrow share a transaction when
both fit in its bytes and in 1,400,000 compute units; on the legacy path a fund with the longest terms (600 bytes)
does not, and takes two more. tests/test_relay2.py counts every path's transactions, waits and compute units, and
prints them with -s.

`ledger` needs send(ixs, payer) -> signature, account(address) -> bytes | None, program_accounts(program, size,
{offset: bytes}) -> [(address, data)] and now(); it is used better when it also has send_all, infos, recent, logs, simulate
(without it the cluster is taken for 2.0) and `takes_v1` with send(..., v1=True) (knos.chain.Ledger has them all).
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from ... import chain, fees, receipt
from .. import oidc as first_oidc
from .. import relay as first
from ..relay import claims_of, header_of
from . import gate, live, meter, oidc, order_auto, pay, passkey
from . import passkey_fund as pkfund

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
_CU = {"faucet": 140_000, "fund": 150_000, "ata": 30_000, "pay": 130_000, "settle": 90_000, "bind": 80_000, "close": 5_000,
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


def _handler(aud: str) -> "Kind | None":
    return next((kind for prefix, kind in KINDS.items() if aud.startswith(prefix)), None)


def kind_of(aud: str) -> str | None:
    """What the relay calls a token with this audience ("fund", "pay", "bind", "key", ...: see KINDS); None for an
    audience it does not carry."""
    found = _handler(aud)
    return found.name if found else None


def lane(jwt: str) -> str:
    """The lane a token travels in when several are carried at once (knos.settle.v2.relayq): two tokens of one lane
    may write the same account (a funder's Balance, an order, a job), so they are sent one after the other, in the
    order they came. It is the account that owns the repository the token was signed for (`repository_owner_id`),
    which is wider than any one of those accounts: tokens of different owners share none of them. A token that names
    no owner travels alone. Read from the token as it says it, unverified: a wrong lane costs speed, never money."""
    try:
        body = jwt.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        owner = claims.get("repository_owner_id") or claims.get("namespace_id") or claims.get("sub")
    except (IndexError, ValueError, AttributeError):
        owner = None
    return f"owner:{owner}" if owner else "alone:" + hashlib.sha256(jwt.encode()).hexdigest()[:16]


_VERSION: dict[tuple, int] = {}         # (cluster, program) -> what Version answered, for as long as this process lives
_VERSION_LINE = b"knos2:version"         # Version's log line (fund.rs: msg!("knos2:version {}", VERSION)): only a build that answers 12 holds it
_UPGRADEABLE = Pubkey.from_string("BPFLoaderUpgradeab1e11111111111111111111111")      # its program account names the ProgramData that holds the code


# The 0.3.14 fee's upper tier edge, 50,000 whole units, as the executable of 2.1 holds it: one 64-bit load (lddw, any
# register) of 50,000,000,000. The build with one fee rate (2.2) has no tiers, so no such load.
_TIERED = re.compile(rb"\x18[\x00-\x0f]\x00\x00" + (50_000_000_000 & 0xFFFFFFFF).to_bytes(4, "little") + rb"\x00{4}"
                     + re.escape((50_000_000_000 >> 32).to_bytes(4, "little")))


def _built(ledger) -> int | None:
    """Which knos-pay is deployed, read from its executable: no transaction, so no fee payer. 0 when the bytes do not
    hold Version's log line (2.0 refuses instruction 12 and has no such line); with the line, 1 when they hold the
    tiered fee of 0.3.14 (`_TIERED`: 2.1) and 2 when they do not (2.2, one rate: the number a log line prints is not
    in the bytes as text, the fee rule is in them as code). None when they could not be read. The program account
    holds the executable itself (loader v2, v4), or (the upgradeable loader) is the tag 2 and the address of the
    ProgramData account that holds it."""
    infos = getattr(ledger, "infos", None)
    if infos is None:
        return None
    try:
        got = infos([pay.PAY_ID])[0]
        if got is not None and got[0] == _UPGRADEABLE:
            data = got[1]
            got = infos([Pubkey.from_bytes(data[4:36])])[0] if len(data) >= 36 and data[:4] == (2).to_bytes(4, "little") else None
    except Exception:  # noqa: BLE001 - not read is no answer
        return None
    if got is None:
        return None
    code = bytes(got[1])
    return 0 if _VERSION_LINE not in code else 1 if _TIERED.search(code) else fees.NEW_VERSION


def forget(ledger=None) -> None:
    """Forgets what Version answered (for this ledger's cluster; with None, for every one), so that the next call asks
    again. A worker calls it when a pass begins: an upgrade that executed between two passes is met by the next one,
    and within a pass every token is planned against one answer."""
    if ledger is None:
        _VERSION.clear()
    else:
        _VERSION.pop((getattr(ledger, "url", None) or id(ledger), pay.PAY_ID), None)


def version(ledger, payer: Keypair | None = None) -> int:
    """Which knos-pay the cluster runs: 2 once 2.2 is live (its instruction 12 logs `knos2:version 2`: one fee rate,
    judges counted by owner, markers bound to an order's funding, the presentation grace), 1 for 2.1, 0 for the 2.0
    program, which refuses that instruction. Asked by simulation, so it costs nothing, and once per cluster until
    `forget` (a worker forgets when a pass begins). A ledger that cannot simulate, or a cluster that did not answer,
    counts as 0 for this call and is asked again on the next: everything 2.1 added is used only on an answer of 1 or
    more, and everything 2.2 changed only on 2 or more (the fee funded, the markers read, who counts as a judge), so
    whichever build is live is met with its own rules. `payer`: any funded key (default: the relay key).
    A simulation needs a fee payer that is on chain. A seller with no relay key (`knos settle --neutral`) or a
    repository with no secret has none, and the cluster refuses the simulation for that (AccountNotFound): then the
    deployed executable is read instead, which needs no payer at all (`_built`)."""
    where = (getattr(ledger, "url", None) or id(ledger), pay.PAY_ID)
    if where in _VERSION:
        return _VERSION[where]
    ask = getattr(ledger, "simulate", None)
    if ask is None:
        return 0
    try:
        logs = ask([pay.version_ix()], payer or chain.key())
    except Exception as why:  # noqa: BLE001 - a refusal by the program is the answer 0; anything else is no answer
        text = " ".join([str(why), *((getattr(why, "data", None) or {}).get("logs") or [])]) if isinstance(getattr(why, "data", None), dict) else str(why)
        if "InstructionError" in text or "invalid instruction data" in text or _code(text) is not None:
            _VERSION[where] = 0
        elif any(mark in text for mark in _BROKE):     # the fee payer is not on chain, or holds no SOL: nothing was asked
            built = _built(ledger)
            if built is not None:
                _VERSION[where] = built
                return built
        return 0
    found = next((int(m.group(1)) for m in (re.fullmatch(r"knos2:version (\d+)", line) for line in chain.said(logs, pay.PAY_ID)) if m), 0)
    _VERSION[where] = found
    return found


def _when(t: int) -> str:
    try:
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (OverflowError, OSError, ValueError):
        return f"time {t}"


def _units(n: int) -> str:
    return f"{n / 1_000_000:,.2f}"


# -- the token, read here before the chain reads it ---------------------------------------------------------------------
@dataclass
class _Token:
    jwt: str
    c: dict                 # its claims
    aud: str
    kind: str | None        # what its audience asks of the escrow; None for any other audience
    issuer: int
    n: int                  # the modulus of the key that signed it
    tid: bytes
    key: Pubkey             # the verifier's account of that key
    account: Pubkey         # where this relayer has it verified
    url: str | None = None  # the issuer's URL, when it is not GitHub or GitLab (`issuer` is then oidc.OTHER or oidc.PRIVATE)
    held: list = field(default_factory=list)    # then: (address, Key) of every key of that issuer on chain with this modulus

    @property
    def bits(self) -> int:
        return 8 * len(oidc.modulus_bytes(self.n))


_KEPT: dict[int, tuple[float, dict]] = {}


def _jwks(issuer: int, jwks: dict | None, fresh: bool = False) -> dict:
    """An issuer's JWKS document: the one given, else fetched from the issuer and kept ten minutes."""
    if jwks and issuer in jwks:
        return jwks[issuer]
    kept = _KEPT.get(issuer)
    if fresh or kept is None or time.monotonic() - kept[0] > JWKS_TTL:
        kept = _KEPT[issuer] = (time.monotonic(), first.fetch_jwks(issuer))
    return kept[1]


def signed(jwt: str, n: int) -> bool:
    """Whether the key with modulus `n` signed this token (RS256): what knos-oidc works out on chain in two
    transactions, worked out here for nothing, so that a forged token never costs a relayer a fee."""
    try:
        head, body, sig = jwt.split(".")
        raw = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
        k = len(oidc.modulus_bytes(n))
        if len(raw) != k or header_of(jwt).get("alg") != "RS256":
            return False
        digest = _DIGEST_INFO + hashlib.sha256(f"{head}.{body}".encode()).digest()
        return pow(int.from_bytes(raw, "big"), 65537, n).to_bytes(k, "big") == b"\x00\x01" + b"\xff" * (k - len(digest) - 3) + b"\x00" + digest
    except (ValueError, TypeError, AttributeError):
        return False


def other_keys(ledger, url: str) -> list[tuple[Pubkey, oidc.Key, int]]:
    """(address, Key, modulus) of every key the verifier holds for the issuer at `url`, where that is not GitHub or
    GitLab by number: the registered issuer's keys first (GitHub's signature named them and the guardian approved
    them), then the PRIVATE ones (a wallet registered each itself; nobody vouches for them), oldest first."""
    out = []
    for limbs in (64, 128):
        tail = oidc.K_HDR + 8 * limbs
        for addr, data in ledger.program_accounts(oidc.OIDC_ID, tail + oidc.KEY_TAIL, {2: bytes([limbs]), tail: oidc.issuer_hash(url)}):
            k = oidc.read_key(data)
            if k is not None and k.issuer >= oidc.OTHER and not k.revoked:
                out.append((addr, k, int.from_bytes(data[oidc.K_HDR:oidc.K_HDR + 4 * limbs], "little")))
    return sorted(out, key=lambda x: (x[1].private, x[1].active_at, str(x[0])))


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
    n = keys_.get(kid)
    if n is None:
        raise _no(kind, f"the issuer's key set has no key {str(kid)[:60]!r}")
    if not signed(jwt, n):
        raise _no(kind, "the signature is not the issuer's")
    tid = oidc.token_id(jwt)
    return _Token(jwt, c, aud, kind, issuer, n, tid, oidc.key_pda(issuer, n), oidc.token_pda(me, tid))


def _workflow(c: dict) -> tuple[bytes, str, str]:
    """(hash of the repository that holds the workflow, the workflow file's name, its commit) from a token's claims."""
    repo, _, rest = str(c.get("job_workflow_ref", "")).partition("/.github/workflows/")
    return pay.wf_repo_hash(repo), rest.split("@", 1)[0], str(c.get("job_workflow_sha", ""))


def _address(text: str) -> Pubkey:
    """An address written the one way Solana writes it (the programs compare the text). ValueError otherwise."""
    key = Pubkey.from_string(text)
    if str(key) != text:
        raise ValueError(text)
    return key


def _ints(c: dict, *names: str) -> list[int]:
    return [int(c[n]) for n in names]


# -- reading the chain --------------------------------------------------------------------------------------------------
def _read(ledger, addresses) -> dict[Pubkey, tuple[Pubkey | None, bytes] | None]:
    """{address: (owner, data)} for each account, None for one that does not exist: in one request when the ledger
    can do that (the owner is None when it cannot say)."""
    addresses = list(dict.fromkeys(addresses))
    many, owner = getattr(ledger, "infos", None), getattr(ledger, "owner", None)
    if many is not None:
        return dict(zip(addresses, many(addresses)))
    out = {}
    for a in addresses:
        data = ledger.account(a)
        out[a] = None if data is None else (owner(a) if owner else None, data)
    return out


def _data(got: dict, address: Pubkey) -> bytes | None:
    return got[address][1] if got.get(address) else None


def _amount(data: bytes | None) -> int:
    """What a token account holds (either token program)."""
    return int.from_bytes(data[64:72], "little") if data and len(data) >= 165 else 0


def jobs_for(ledger, repo_id: int, issue: int) -> list[tuple[Pubkey, pay.Job]]:
    """Every job on this issue that holds money: open, or held for its payee. An issue can have several: each Balance
    and each wallet funds its own."""
    found = ledger.program_accounts(pay.PAY_ID, pay.JOB_LEN, {8: repo_id.to_bytes(8, "little") + issue.to_bytes(8, "little")})
    jobs = [(addr, pay.read_job(data)) for addr, data in found]
    return sorted(((a, j) for a, j in jobs if j is not None and j.state in ("open", "held")), key=lambda x: str(x[0]))


def balances_for(ledger, owner_id: int) -> list[tuple[Pubkey, pay.Balance, int]]:
    """(address, Balance, what its token account holds now) for every Balance set aside for one GitHub owner's
    repositories: each wallet's, and on devnet the faucet's."""
    found = ledger.program_accounts(pay.PAY_ID, pay.BALANCE_LEN, {8: owner_id.to_bytes(8, "little")})
    bals = sorted(((a, b) for a, b in ((a, pay.read_balance(d)) for a, d in found) if b is not None), key=lambda x: str(x[0]))
    held = _read(ledger, [pay.baltok_pda(a) for a, _b in bals])
    return [(a, b, _amount(_data(held, pay.baltok_pda(a)))) for a, b in bals]


def held_for(ledger, user_id: int) -> list[tuple[Pubkey, pay.Job]]:
    """Every job that is held and waits for this GitHub user to bind a wallet."""
    found = ledger.program_accounts(pay.PAY_ID, pay.JOB_LEN, {0: bytes([3]), 56: user_id.to_bytes(8, "little")})
    jobs = [(addr, pay.read_job(data)) for addr, data in found]
    return sorted(((a, j) for a, j in jobs if j is not None and j.state == "held" and j.payee_id == user_id), key=lambda x: str(x[0]))


def keys(ledger) -> list[tuple[Pubkey, oidc.Key, int]]:
    """(address, Key, modulus) of every signing key the second verifier has: GitHub's first, each issuer's oldest first."""
    out = []
    for limbs in (64, 128):     # a token account can be as long as a key account, and its third byte is never a limb count
        for addr, data in ledger.program_accounts(oidc.OIDC_ID, oidc.K_HDR + 8 * limbs, {2: bytes([limbs])}):
            k = oidc.read_key(data)
            if k is not None:
                out.append((addr, k, int.from_bytes(data[oidc.K_HDR:oidc.K_HDR + 4 * limbs], "little")))
    return sorted(out, key=lambda x: (x[1].issuer, x[1].active_at, str(x[0])))


def _last(ledger, address: Pubkey) -> list[str]:
    """The transaction that last touched an account, for a result that sends none of its own. Best effort."""
    find = getattr(ledger, "last_signature", None)
    try:
        sig = find(address) if find else None
    except Exception:  # noqa: BLE001 - the verdict does not depend on finding the transaction
        sig = None
    return [sig] if sig else []


def _funded_by(ledger, order: Pubkey, used: Pubkey, most: int = 20) -> tuple[bool, list[str]]:
    """Whether the order now at `order` was funded by the fund token whose marker is `used`, and the transaction that
    funded it: the newest of the order's last few transactions in which knos-pay logged its funding, and whether that
    transaction also wrote the marker. An address is funded again once its order is paid or refunded, by another token
    of the same funder for the same issue and terms, so the order's own fields cannot tell the two tokens apart. When
    the cluster does not say: (True, the last transaction to touch the order), the answer before this was read."""
    recent, logs = getattr(ledger, "recent", None), getattr(ledger, "logs", None)
    if not (recent and logs):
        return True, _last(ledger, order)
    try:
        for sig, _when in recent(order, most):
            if any(line.startswith(f"knos3:funded order={order} ") for line in chain.said(logs(sig), pay.PAY_ID)):
                return sig in {s for s, _w in recent(used, most)}, [sig]
    except Exception:  # noqa: BLE001 - not known: as before
        pass
    return True, _last(ledger, order)


def _said_in(ledger, address: Pubkey, line: str, most: int = 10) -> list[str]:
    """The newest of the last few transactions that named `address` in which knos-pay itself logged exactly `line`.
    The last transaction to name an account is not the one that wrote it: a wallet's Bind is named, read-only, by
    every payment to its owner afterwards. When none is found the result names no transaction, never another one."""
    recent, logs = getattr(ledger, "recent", None), getattr(ledger, "logs", None)
    try:
        for sig, _when in (recent(address, most) if recent and logs else []):
            if line in chain.said(logs(sig), pay.PAY_ID):
                return [sig]
    except Exception:  # noqa: BLE001, S110 - the verdict does not depend on finding the transaction
        pass
    return []


def _batch_taken(ledger, where: Pubkey, kind: str, b, most: int = 20) -> dict | None:
    """Where knos_meter took exactly this batch (RecordBatch or ClaimBatch logs every number of the audience and its
    root), among the last few transactions that named its Ledger account `where`: {"sigs", "fee", "chain"} as that
    line says them, or None when none is found or the cluster does not say. A seq is taken once, so a line with this
    seq and this root is this audience's own batch: any token for it asks for what the chain already shows. One with
    another root is another batch, and is refused."""
    head = (f"knosm:{kind} buyer={b.buyer} seller={b.seller} month={b.month} seq={b.seq} count={b.count} accepted={b.accepted} "
            f"value={b.value} root={b.root.hex()} ")
    recent, logs = getattr(ledger, "recent", None), getattr(ledger, "logs", None)
    try:
        for sig, _when in (recent(where, most) if recent and logs else []):
            for line in chain.said(logs(sig), meter.METER_ID):
                if line.startswith(head):
                    fee, made = re.search(r" fee=(\d+)", line), re.search(r" chain=([0-9a-f]{64})", line)
                    return {"sigs": [sig], "fee": int(fee.group(1)) if fee else 0, **({"chain": made.group(1)} if made else {})}
    except Exception:  # noqa: BLE001, S110 - not known: the seq rule answers, as before
        pass
    return None


# -- what each audience asks of the escrow, decided with reads alone ----------------------------------------------------
Group = tuple[list[Instruction], int]       # instructions that go in one transaction together, and their compute units


@dataclass
class _Plan:
    t: _Token
    groups: list[Group]                     # the escrow's instructions, in order
    done: Callable[[list[str]], dict]       # the result, once they have all landed
    token: bool = True                      # whether they need the token verified (and its account closed behind them)
    alone: bool = False                     # whether the transactions after the one with the last Step depend on nothing but it
    lead: bool = False                      # whether the first group must land before the others whatever else is so (a Bind, then the payments it frees)
    closes: bool = False                    # whether a group already closes the token account
    have: bytes | None = None               # the token account as it stands
    v1: bool = False                        # whether its transactions go out as v1 ones (4,096 bytes): a 2.1 cluster, and a ledger that sends them
    register: list[Instruction] = field(default_factory=list)   # a signing key the chain needs first (a genesis key it has not seen)
    soon: str | None = None                 # what to say when the program answers 83 to a plan every read allowed: tried again on the next pass


def _github_token(t: _Token, now: int, private: bool = False) -> None:
    """What knos-pay asks of every token before it reads the audience (gh.rs): GitHub's, a GitHub-hosted runner, and
    times that GitHub's clock wrote. `private`: the kind also takes a token under a key some wallet registered itself,
    where its planner finds that wallet to be the one whose money it pays out (`_own_key`)."""
    if t.issuer != oidc.GITHUB and not (private and any(k.private for _a, k in t.held)):
        raise _no(t.kind, "the escrow takes GitHub's tokens only" + ("" if t.url is None else
                          ": a token of another issuer is verified for other programs to read (post it as `knos-verify:`), and a pay token under a "
                          "key a wallet registered itself pays a private order of that wallet's own balance"))
    if t.c.get("runner_environment") != "github-hosted":
        raise _no(t.kind, "not from a GitHub-hosted runner")
    try:
        iat, exp = _ints(t.c, "iat", "exp")
    except (KeyError, ValueError, TypeError):
        raise _no(t.kind, "malformed audience or claims") from None
    if iat > now + pay.TOKEN_AHEAD or exp - iat > pay.TOKEN_LIFE:
        raise _no(t.kind, "the token's times are not GitHub's: it is dated ahead of the chain's clock, or lives longer than an hour")


def _decimals(mint: bytes | None) -> int:
    """A mint's decimals (either token program); 6 when the mint could not be read."""
    return mint[44] if mint and len(mint) >= 82 else 6


def _bounds(kind: str, amount: int, decimals: int, least: int = pay.MIN_AMOUNT, what: str = "a bounty") -> None:
    """The escrow's limits are whole units of the mint, whatever its decimals."""
    low, high, one = pay.units(least, decimals), pay.units(pay.MAX_AMOUNT, decimals), 10 ** decimals
    if not low <= amount <= high:
        raise _no(kind, f"{what} is from {low / one:,.2f} to {high / one:,.2f}; this token asks for {amount / one:,.2f}")


def _limits(kind: str, x: pay.BalanceX | None, amount: int, repo_id: int, wf_sha: str, now: int) -> None:
    """What a Balance's side account asks of a funding (2.1): its repositories, its workflows commit, and what it may
    spend in a day and in all."""
    if x is None:
        return
    if x.repos and repo_id not in x.repos:
        raise _no(kind, "that balance lists the repositories that may spend it, and this one is not among them")
    if x.wf_sha and x.wf_sha != wf_sha:
        raise _no(kind, "that balance is spent only by the workflows at the commit its wallet pinned, and this run used another")
    today = x.day_spent if x.day == now // 86_400 else 0
    if (x.day_limit and today + amount > x.day_limit) or (x.total_limit and x.total_spent + amount > x.total_limit):
        raise _no(kind, f"{pay.ERRORS[100]}: {_units(today)} of {_units(x.day_limit)} spent today, {_units(x.total_spent)} of {_units(x.total_limit)} in all "
                        "(a limit of 0.00 is no limit)")


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
        program = (got[baltok][0] if got.get(baltok) else None) or pay.TOKEN     # a Balance's token account belongs to its mint's token program
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
            for line in chain.said(logs(sig), pay.PAY_ID):
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


# -- work orders (2.1): knos3:fund, knos3:pay -----------------------------------------------------------------------------
@dataclass
class _Ask:
    """One token, and what a handler plans it with."""
    ledger: object
    payer: Keypair
    me: Pubkey
    t: _Token
    now: int
    v: int                      # the escrow's version on this cluster
    terms: bytes | None = None
    jwks: dict | None = None


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
        program = (got[baltok][0] if got.get(baltok) else None) or pay.TOKEN
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
            for line in chain.said(logs(sig), pay.PAY_ID):
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
            more = {**({"again": [order_auto.NAMES[k] for k in again]} if again else {}), **({"uncounted": lone} if lone else {})}
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


def _said_since(ledger, address: Pubkey, pattern: str, since: int) -> tuple[re.Match, str] | None:
    """The newest line knos-pay itself logged, no earlier than `since`, in a transaction that named `address`, which
    matches `pattern` whole: (the match, the transaction). None when there is none, or the ledger cannot say."""
    recent, logs = getattr(ledger, "recent", None), getattr(ledger, "logs", None)
    try:
        for sig, when in (recent(address, 5) if recent and logs else []):
            if when is not None and when < since:
                continue
            for line in chain.said(logs(sig), pay.PAY_ID):
                if m := re.fullmatch(pattern, line):
                    return m, sig
    except Exception:  # noqa: BLE001, S110 - not finding it only means the plain refusal is given
        pass
    return None


def _plan_revert(a: _Ask) -> _Plan:
    """knos3:revert: inside the warranty a judge of the order says the accepted change was reverted (Revert):
    everything the order still holds, the holdback and the fee on it, goes back to where its money came from. The
    judge is a, b or c as for a payment (`_judge`: the order's own repository, a NEUTRAL attest.yml by hand, the judge
    repository). Never the arbiter: he rules on payments, and with this audience he is whoever else he is to the order."""
    kind, ledger, me, t, now = "revert", a.ledger, a.me, a.t, a.now
    order, o, p, iat = _order_token(a, kind, 4)
    if not _HEX40.fullmatch(p[3]):
        raise _no(kind, "malformed audience or claims")
    result = dict(kind=kind, order=str(order), head=p[3])
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
    return bool(bind) and len(bind) >= 56 and bind[2] == 1 and bytes(bind[3:8]) == bytes(bind[48:53])


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


# -- knos_meter: an evaluation counted, with no escrow --------------------------------------------------------------------
def credits_for(ledger, buyer_id: int) -> list[tuple[Pubkey, meter.Credits, int]]:
    """(address, Credits, what its token account holds) for every credits account prepaid for one buyer's evaluations."""
    found = ledger.program_accounts(meter.METER_ID, meter.CREDITS_LEN, {8: buyer_id.to_bytes(8, "little")})
    got = sorted(((a, c) for a, c in ((a, meter.read_credits(d)) for a, d in found) if c is not None), key=lambda x: str(x[0]))
    held = _read(ledger, [meter.crtok_pda(a) for a, _c in got])
    return [(a, c, _amount(_data(held, meter.crtok_pda(a)))) for a, c in got]


def _plan_eval(a: _Ask) -> _Plan:
    """knosm:eval: knos_meter records one evaluation (Record) against credits the buyer prepaid for the workflows
    that ran. An evaluation is billed once: a token for one the meter already has costs this relay nothing."""
    kind, ledger, me, t, now = "eval", a.ledger, a.me, a.t, a.now
    c = t.c
    try:
        e = meter.parse_audience(t.aud)
        if (len(e.order), len(e.policy)) != (32, 32) or not _HEX40.fullmatch(e.artifact) or not 0 <= e.milestone < 2 ** 32 or e.buyer_id == 0:
            raise ValueError(t.aud)
        owner, = _ints(c, "repository_owner_id")
    except (KeyError, ValueError, TypeError):
        raise _no(kind, "malformed audience or claims") from None
    wf_repo, wf_file, wf_sha = _workflow(c)
    if wf_file not in meter.WORKFLOWS:
        raise _no(kind, "an evaluation is recorded from attest.yml or prove.yml")
    if str(c.get("run_attempt")) != "1":
        raise _no(kind, "this token is from a re-run, and only a run's first attempt is counted; run the workflow again")
    if owner != e.buyer_id:
        raise _no(kind, "the run was not in a repository of the buyer its audience names")
    mark = meter.mark_pda(e.buyer_id, e.key)
    got = _read(ledger, [mark, meter.plan_pda(e.buyer_id), meter.METER_ID])
    result = dict(kind=kind, buyer_id=e.buyer_id, seller_id=e.seller_id, order=e.order.hex(), artifact=e.artifact, milestone=e.milestone)
    before = meter.read_mark(_data(got, mark))
    if before is not None:      # counted already (by this token or by another run): the first verdict stands, and a retry is free
        raise _Stop({"ok": True, **result, "sigs": _last(ledger, mark), "already": True, "accepted": before.accepted, "rate": before.rate, "fee": before.fee,
                     "month": before.month})
    if _data(got, meter.METER_ID) is None:      # what this needs is knos_meter (and the verifier it reads), never a version of the escrow
        raise _no(kind, f"knos_meter ({meter.METER_ID}) is not deployed on this cluster, so no evaluation can be counted here")
    pinned = [(addr, cr, held) for addr, cr, held in credits_for(ledger, e.buyer_id) if (cr.wf_repo_hash, cr.wf_sha) == (wf_repo, wf_sha)]
    if not pinned:
        raise _no(kind, "the buyer has no credits opened for these workflows at this commit; a wallet opens them (knos_meter OpenCredits), and "
                        "the first 10,000 evaluations of a month then cost nothing")
    plan_ = meter.read_plan(_data(got, meter.plan_pda(e.buyer_id)))
    paying = [(addr, cr, held) for addr, cr, held in pinned if held >= meter.quote(plan_, cr.decimals, now)]
    if not paying:
        raise _no(kind, "the buyer's credits hold less than the fee of this evaluation; a plain transfer to their token account adds to them")
    credits, cr, _held = max(paying, key=lambda x: x[2])
    fee = meter.quote(plan_, cr.decimals, now)
    home = pay.ata(meter.FEE_OWNER, cr.mint, cr.token_program)
    first = [pay.create_ata_ix(me, meter.FEE_OWNER, cr.mint, cr.token_program)] if fee and _data(_read(ledger, [home]), home) is None else []

    def done(sigs: list[str]) -> dict:
        made = meter.read_mark(ledger.account(mark))
        if made is None:
            return {"ok": False, "kind": kind, "why": "the evaluation did not reach the chain"}
        try:        # the one log of events, when this relay keeps one (KNOS_EVENTS): best effort, after the confirmation
            from ... import events
            if sigs and events.where():
                events.keep(events.where(), lambda: events.from_records([t.aud + " " + sigs[-1]], made.month))
        except Exception:  # noqa: BLE001, S110 - the evaluation is on chain whatever a log file says
            pass
        return {"ok": True, **result, "sigs": sigs, "accepted": made.accepted, "rate": made.rate, "fee": made.fee, "month": made.month}
    return _Plan(t, [([*first, meter.record_ix(me, t.account, t.key, credits, cr, t.aud, now)], _CU["ata"] * len(first) + _CU["record"])], done)


def _plan_batch(a: _Ask, claim: bool = False) -> _Plan:
    """knosm:batch: the buyer's count of many evaluations in one token (RecordBatch), under Record's rules and paid
    from the same credits. knosm:claim: the seller's own count (ClaimBatch), from any workflow in a repository the
    seller owns, with no credits and no fee. A batch token is taken once: its seq must be the Ledger's next. A token
    for a batch the chain already took (its seq, its numbers and its root in the Ledger's recent logs) is answered
    "already", with that transaction: another relayer carried it."""
    kind, ledger, me, t, now = "claim" if claim else "batch", a.ledger, a.me, a.t, a.now
    try:
        is_claim, b = meter.parse_batch_audience(t.aud)
        owner, = _ints(t.c, "repository_owner_id")
    except (KeyError, ValueError, TypeError):
        raise _no(kind, "malformed audience or claims") from None
    if is_claim != claim or not 1 <= b.count <= meter.MAX_BATCH or b.accepted > b.count or b.month not in (meter.yyyymm(now), meter.prev_month(meter.yyyymm(now))):
        raise _no(kind, meter.ERRORS[meter.E_BATCH])
    wf_repo, wf_file, wf_sha = _workflow(t.c)
    if not claim and wf_file not in meter.WORKFLOWS:
        raise _no(kind, "a batch is recorded from attest.yml or prove.yml")
    if not claim and str(t.c.get("run_attempt")) != "1":
        raise _no(kind, "this token is from a re-run, and only a run's first attempt is counted; run the workflow again")
    if owner != (b.seller if claim else b.buyer):
        raise _no(kind, "the run was not in a repository of the seller its audience names" if claim else "the run was not in a repository of the buyer its audience names")
    where = meter.ledger_pda(b.buyer, b.seller, b.month, claim)
    got = _read(ledger, [where, meter.plan_pda(b.buyer), meter.METER_ID])
    if _data(got, meter.METER_ID) is None:
        raise _no(kind, f"knos_meter ({meter.METER_ID}) is not deployed on this cluster, so no batch can be counted here")
    if old := live.needs(ledger, a.payer, "knos_meter", now):     # the batch mode is 1.1's: 1.0 runs until the upgrade executes
        raise _no(kind, old)
    before = meter.read_ledger(_data(got, where))
    result = dict(kind=kind, buyer_id=b.buyer, seller_id=b.seller, month=b.month, seq=b.seq, count=b.count, accepted=b.accepted, value=b.value, root=b.root.hex())
    if before is not None and before.next_seq > b.seq and (taken := _batch_taken(ledger, where, kind, b)):
        raise _Stop({"ok": True, **result, **taken, "already": True})     # this very batch is counted: another relayer carried it
    if (before.next_seq if before else 0) != b.seq:     # a seq another batch took, a batch out of order, or one that is missing: nothing is sent
        raise _no(kind, meter.ERRORS[meter.E_SEQ], next_seq=before.next_seq if before else 0)
    want = meter.chain_hash(before.chain if before else meter.ZERO, b.root, b.seq, b.count, b.accepted, b.value)

    def done(sigs: list[str]) -> dict:
        made = meter.read_ledger(ledger.account(where))
        if made is None or made.next_seq <= b.seq or (made.next_seq == b.seq + 1 and made.chain != want):
            return {"ok": False, "kind": kind, "why": "the batch did not reach the chain"}
        return {"ok": True, **result, "sigs": sigs, "fee": made.fees - (before.fees if before else 0), "chain": want.hex()}
    if claim:
        return _Plan(t, [([meter.claim_batch_ix(me, t.account, t.key, t.aud)], meter.CU_CLAIM)], done)
    pinned = [(addr, cr, held) for addr, cr, held in credits_for(ledger, b.buyer) if (cr.wf_repo_hash, cr.wf_sha) == (wf_repo, wf_sha)]
    if not pinned:
        raise _no(kind, "the buyer has no credits opened for these workflows at this commit; a wallet opens them (knos_meter OpenCredits), and "
                        "the first 10,000 evaluations of a month then cost nothing")
    plan_ = meter.read_plan(_data(got, meter.plan_pda(b.buyer)))
    paying = [(addr, cr, held) for addr, cr, held in pinned if held >= meter.batch_fee(plan_, b.count, cr.decimals, now)]
    if not paying:
        raise _no(kind, "the buyer's credits hold less than the fee of this batch, and a batch is taken whole or not at all; a plain transfer to "
                        "their token account adds to them, and the same token can be sent again while it is good")
    credits, cr, _held = max(paying, key=lambda x: x[2])
    home = pay.ata(meter.FEE_OWNER, cr.mint, cr.token_program)
    first = [pay.create_ata_ix(me, meter.FEE_OWNER, cr.mint, cr.token_program)] if meter.batch_fee(plan_, b.count, cr.decimals, now) and _data(_read(ledger, [home]), home) is None else []
    return _Plan(t, [([*first, meter.record_batch_ix(me, t.account, t.key, credits, cr, t.aud)], _CU["ata"] * len(first) + meter.CU_BATCH)], done)


# -- the upgrade gate: GitHub's word on which bytes its runner built ----------------------------------------------------
def _plan_gate(a: _Ask) -> _Plan:
    """gate:<program>:<executable hash>: examples/upgrade_gate records that GitHub's runner built these bytes for this
    program (its one instruction, Record). The token is program.yml's gate job's: Knos's repository, that file at the
    commit it built, main or a release tag, a GitHub-hosted runner. A record is written once, so a later run that
    built the same bytes costs this relay nothing."""
    kind, ledger, me, t = "gate", a.ledger, a.me, a.t
    c, p = t.c, t.aud.split(":")
    try:
        if len(p) != 3 or not _HEX64.fullmatch(p[2]):
            raise ValueError(t.aud)
        program, executable = _address(p[1]), bytes.fromhex(p[2])
        repo, = _ints(c, "repository_id")
    except (KeyError, ValueError, TypeError):
        raise _no(kind, "malformed audience or claims") from None
    ref, sha = str(c.get("ref", "")), str(c.get("sha", ""))
    if not (t.issuer == oidc.GITHUB and repo == gate.KNOS_REPO_ID and str(c.get("job_workflow_ref", "")).startswith(gate.WORKFLOW + "@")
            and c.get("runner_environment") == "github-hosted" and (ref == "refs/heads/main" or ref.startswith("refs/tags/v"))
            and _HEX40.fullmatch(sha) and c.get("job_workflow_sha") == sha):
        raise _no(kind, "a build is recorded only on a run of Knos's own program.yml on a GitHub-hosted runner, at a commit of main or of a "
                        "release tag, with the workflow file of that same commit")
    at = gate.record_pda(program, executable)
    got = _read(ledger, [at, gate.GATE_ID])
    result = dict(kind=kind, program=str(program), hash=p[2], record=str(at))

    def done(sigs: list[str], rec: gate.Record | None = None) -> dict:
        rec = rec or gate.read_record(ledger.account(at))
        if rec is None:
            return {"ok": False, "kind": kind, "why": "the record did not reach the chain"}
        return {"ok": True, **result, "sigs": sigs, "commit": rec.sha, "run_id": rec.run_id}
    before = gate.read_record(_data(got, at))
    if before is not None:      # recorded already, by this token or by an earlier run that built the same bytes: the first commit stays
        raise _Stop({**done(_last(ledger, at), before), "already": True})
    if _data(got, gate.GATE_ID) is None:
        raise _no(kind, f"the upgrade gate ({gate.GATE_ID}) is not deployed on this cluster, so no build can be recorded here")
    return _Plan(t, [([gate.record_ix(me, t.account, t.key, program, executable)], _CU["gate"])], done)


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
    handler, v = _handler(t.aud), version(ledger, payer)
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


def _out_of_compute(why: BaseException) -> bool:
    return any(mark in str(why) for mark in ("ProgramFailedToComplete", "Program failed to complete", "omputational budget exceeded",
                                             "exceeded CUs meter", "ComputationalBudgetExceeded"))


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
        txs[-1] = (txs[-1][0] + [close], txs[-1][1] + _CU["close"])
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
    said = pay.ERRORS.get(code) or _VERIFIER.get(code)
    words = ("the relayer's key has no SOL to pay the fees with" if any(mark in text for mark in _BROKE)
             else f"{said} (error {code})" if said else f"{type(why).__name__}: {text[:200]}")
    return {"ok": False, "kind": kind, "why": words, **({"retry": True, "transient": True} if transient(why) else {}), **({"answered": True} if answered(why) else {})}


def why_failed(why: BaseException) -> str:
    """What a failed transaction of the escrow's or the verifier's means, in the words of their clients (for a wallet's
    own commands: `knos balance`, `knos fund-wallet`)."""
    return _failed(None, why)["why"]


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


def _handler_of(jwt: str) -> Kind | None:
    try:
        aud = claims_of(jwt.strip())["aud"]
        return _handler(aud if isinstance(aud, str) else aud[0])
    except Exception:  # noqa: BLE001 - not a token: `_open` says so
        return None


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
        plan = _Plan(t, [], dict, v1=version(ledger, payer) >= 1 and bool(getattr(ledger, "takes_v1", False)))
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


# -- what needs no token: anyone's to send ------------------------------------------------------------------------------
def _each(ledger, payer: Keypair, txs: list[list[Instruction]]) -> list[str]:
    """Sends each transaction; one that fails (someone else was first, a destination that cannot be made) does not
    stop the others."""
    sigs = []
    for ixs in txs:
        try:
            sigs.append(ledger.send(ixs, payer))
        except Exception:  # noqa: BLE001, S112 - best effort: the next pass looks again
            continue
    return sigs


def refund_due(ledger, payer: Keypair, now: int) -> list[str]:
    """Sends back every job nobody can be paid from any more: open past its deadline, or held past its hold. To the
    Balance it came from, or to the funding wallet's token account (made if it is gone). Needs ledger.program_accounts."""
    me, txs = payer.pubkey(), []
    for state in (1, 3):
        for addr, data in ledger.program_accounts(pay.PAY_ID, pay.JOB_LEN, {0: bytes([state])}):
            j = pay.read_job(data)
            if j is not None and now > (j.deadline if j.state == "open" else j.hold_until):
                home = [] if j.from_balance else [pay.create_ata_ix(me, j.refund_to, j.mint, j.token_program)]
                txs.append([*home, pay.refund_ix(me, addr, j)])
    return _each(ledger, payer, txs)


def settle_held(ledger, payer: Keypair) -> list[str]:
    """Pays every held job whose payee has bound a wallet since it was held. Needs ledger.program_accounts."""
    me, now = payer.pubkey(), int(ledger.now())
    held = [(addr, j) for addr, j in ((a, pay.read_job(d)) for a, d in ledger.program_accounts(pay.PAY_ID, pay.JOB_LEN, {0: bytes([3])}))
            if j is not None and now <= j.hold_until]
    binds = _read(ledger, [pay.bind_pda(j.payee_id) for _a, j in held])
    txs = []
    for addr, j in held:
        bound = pay.read_bind(_data(binds, pay.bind_pda(j.payee_id)))
        if bound is not None:
            txs.append(_payout(me, j, bound.wallet, pay.settle_ix(me, addr, j, bound.wallet), 0)[0])
    return _each(ledger, payer, txs)


def orders(ledger, state: int) -> list[tuple[Pubkey, pay.Order]]:
    """Every work order in one state (1 open, 3 held, 4 warranty). Needs ledger.program_accounts."""
    found = ((a, pay.read_order(d)) for a, d in ledger.program_accounts(pay.PAY_ID, pay.ORDER_LEN, {0: bytes([2, state])}))
    return sorted(((a, o) for a, o in found if o is not None), key=lambda x: str(x[0]))


def open_repositories(ledger) -> set[int]:
    """The GitHub id of every repository with money waiting on a proof: an open job, or an open work order (a private
    order names no repository, so the one whose runs judge it stands in). A worker that reads those repositories'
    comments finds a pay token with no search at all. Reads only; needs ledger.program_accounts."""
    jobs = (pay.read_job(d) for _a, d in ledger.program_accounts(pay.PAY_ID, pay.JOB_LEN, {0: bytes([1])}))
    ids = {j.repo_id for j in jobs if j is not None} | {o.repo_id or o.judge_repo_id for _a, o in orders(ledger, 1)}
    return ids - {0}


def refund_orders_due(ledger, payer: Keypair, now: int) -> list[str]:
    """Sends back every work order nobody can be paid from any more: open past its deadline (`pay_until`: with the
    presentation grace, two hours later), or held past its hold.
    To the Balance it came from, or to the funding wallet's token account (made if it is gone). Nothing on a 2.0 escrow."""
    if version(ledger, payer) < 1:
        return []
    me, txs = payer.pubkey(), []
    # (an open order funded with the presentation grace is due GRACE after its deadline: until then a token issued by the deadline still pays it)
    due = [(addr, o) for state in (1, 3) for addr, o in orders(ledger, state) if now > (o.pay_until if o.state == "open" else o.hold_until)]
    # an order cancelled while it was reserved owes its taker a kill fee first: to his bound wallet's token account,
    # made here if it is not there; with no wallet bound the fee stays held for him in the order and the rest goes back
    binds = _read(ledger, [pay.bind_pda(o.reserved_by) for _a, o in due if pay.kill_fee(o)])
    for addr, o in due:
        home = [] if o.from_balance else [pay.create_ata_ix(me, o.refund_to, o.mint, o.token_program)]
        taker = pay.read_bind(_data(binds, pay.bind_pda(o.reserved_by))) if pay.kill_fee(o) else None
        if taker is not None and taker.wallet != pay.auth_pda():
            home.append(pay.create_ata_ix(me, taker.wallet, o.mint, o.token_program))
        txs.append([*home, pay.refund_order_ix(me, addr, o, kill_token=pay.ata(taker.wallet, o.mint, o.token_program) if taker is not None else None)])
    return _each(ledger, payer, txs)


def settle_orders_held(ledger, payer: Keypair) -> list[str]:
    """Pays every held work order whose payee has bound a wallet since it was held; the tip comes to this relayer's
    own token account, made the first time. Nothing on a 2.0 escrow."""
    if version(ledger, payer) < 1:
        return []
    me, now = payer.pubkey(), int(ledger.now())
    held = [(addr, o) for addr, o in orders(ledger, 3) if now <= o.hold_until]
    got = _read(ledger, [k for a, o in held for k in (pay.bind_pda(o.payee_id), pay.assign_pda(a, o.payee_id), pay.ata(me, o.mint, o.token_program),
                                                      pay.ata(pay.FEE_OWNER, o.mint, o.token_program))])
    txs = []
    for addr, o in held:
        wallet = _routed(got, addr, o, o.payee_id, None)        # the bound wallet, or the one the payee assigned this order's payment to
        if wallet is not None:
            txs.append([*_tip_accounts(me, o, got)[0], pay.settle_order_ix(me, addr, o, wallet)])
    return _each(ledger, payer, txs)


def release_orders_due(ledger, payer: Keypair, now: int) -> list[str]:
    """Sends what every order held back to the wallets recorded when it was paid, once its warranty is over and nobody
    reverted (Release). Anyone may; the tip comes to this relayer's own token account. Nothing on a 2.0 escrow."""
    if version(ledger, payer) < 1:
        return []
    me = payer.pubkey()
    due = [(addr, o) for addr, o in orders(ledger, 4) if now > o.hold_until]
    got = _read(ledger, [k for a, o in due for k in (pay.hb_pda(a), pay.ata(me, o.mint, o.token_program), pay.ata(pay.FEE_OWNER, o.mint, o.token_program))])
    txs = []
    for addr, o in due:
        hb = pay.read_holdback(_data(got, pay.hb_pda(addr)))
        if hb is not None:
            txs.append([*_tip_accounts(me, o, got)[0], pay.release_ix(me, addr, o, hb)])
    return _each(ledger, payer, txs)


def close_markers(ledger, payer: Keypair, now: int, per_tx: int = 8) -> list[str]:
    """Takes back the rent of the markers this relayer paid for, once they no longer matter (CloseMarker): the
    single-use marker of a token (`used`) after the time it stores, by which no instruction accepts that token any
    more; and a standing order's marker of a paid pull request (`done`) once its order is closed. Several to a
    transaction. Markers of both builds: 2.1 wrote a `done` of 65 bytes and a quorum marker of 106, 2.2 writes 73 and
    122, and either program closes what it can read by one rule. Nothing on a 2.0 escrow, which has neither."""
    if version(ledger, payer) < 1:
        return []
    me, ixs = payer.pubkey(), []
    for addr, data in ledger.program_accounts(pay.PAY_ID, pay.USED_LEN, {1: bytes(me)}):
        got = pay.read_marker(data)
        if got is not None and got[0] == me and now > got[1]:
            ixs.append(pay.close_marker_ix(addr, me))
    new = version(ledger, payer) >= fees.NEW_VERSION        # 2.1 knows only its own two lengths, and writes no other
    sizes = (pay.DONE_LEN_21, pay.DONE_LEN) if new else (pay.DONE_LEN_21,)
    marks = [(addr, data) for size in sizes for addr, data in ledger.program_accounts(pay.PAY_ID, size, {1: bytes(me)})]
    done = [(addr, got[1], data) for addr, data, got in ((a, d, pay.read_marker(d)) for a, d in marks) if got is not None and got[0] == me]
    there = _read(ledger, [order for _a, order, _d in done])
    for addr, order, data in done:      # its order is gone, or (2.2) the order there now is another funding: order_terms.rs close_marker
        o = pay.read_order(_data(there, order))
        if there.get(order) is None or (new and o is not None and (o.inc != 0 if len(data) == pay.DONE_LEN_21 else
                                                                  o.stamp != int.from_bytes(data[65:73], "little", signed=True))):
            ixs.append(pay.close_marker_ix(addr, me, order))
    # a quorum marker, once its order is not the open order it was made for (paid, refunded, or funded again later)
    said = [(addr, order_auto.read_any(data)) for size in ((order_auto.Q_LEN_21, order_auto.Q_LEN) if new else (order_auto.Q_LEN_21,))
            for addr, data in ledger.program_accounts(pay.PAY_ID, size, {2: bytes(me)})]
    now_at = _read(ledger, [q[2] for _a, q in said if q is not None])
    for addr, q in said:
        o = pay.read_order(_data(now_at, q[2])) if q is not None else None
        if q is not None and q[1] == me and (o is None or o.state != "open" or o.stamp != q[3]):
            ixs.append(pay.close_marker_ix(addr, me, q[2]))
    return _each(ledger, payer, [ixs[k:k + per_tx] for k in range(0, len(ixs), per_tx)])


def close_marks(ledger, payer: Keypair, now: int, per_tx: int = 8) -> list[str]:
    """Takes back the rent of the meter's marks this relayer paid for (knos_meter CloseMark), once the month they
    were counted in is over and no token of it can come again. Several to a transaction. knos_meter's own instruction:
    whatever version the escrow is (a cluster without the meter has no marks)."""
    me = payer.pubkey()
    ixs = [meter.close_mark_ix(me, mark) for mark in meter.closable(meter.marks_of(ledger, me), now)]
    return _each(ledger, payer, [ixs[k:k + per_tx] for k in range(0, len(ixs), per_tx)])


def withdraw(ledger, payer: Keypair, request: str | bytes) -> dict:
    """A passkey wallet's withdrawal (knos_passkey), sent and paid for by this relay, for a person who holds no SOL:
    Open when the wallet's account is not there yet, the secp256r1 check of the passkey's signature, Withdraw.
    `request` is what passkey.request wrote. {"ok": True, "kind": "withdraw", "sigs", "wallet", "mint", "to",
    "amount", "nonce"}, or {"ok": False, "kind": "withdraw", "why"}. The relay decides nothing: the passkey signed the
    mint, the destination, the amount and the nonce. Everything is asked first, by reads and then by simulating the
    very transaction, so a request the chain would refuse costs no fee; a ledger that cannot simulate sends none."""
    kind = "withdraw"
    try:
        q = passkey.read_request(request)
    except ValueError as why:
        return {"ok": False, "kind": kind, "why": str(why)}
    try:
        me, w = payer.pubkey(), q.wallet
        result = dict(kind=kind, wallet=str(w), mint=str(q.mint), to=str(q.to), amount=q.amount, nonce=q.nonce)
        got = _read(ledger, [w, q.mint, q.to, passkey.PASSKEY_ID])
        if _data(got, passkey.PASSKEY_ID) is None:     # knos_passkey never calls the escrow: what a withdrawal needs is that program, whatever the escrow's version
            raise _no(kind, f"knos_passkey ({passkey.PASSKEY_ID}) is not deployed on this cluster, so no passkey wallet can withdraw here")
        program = got[q.mint][0] if got.get(q.mint) else None
        if program not in (pay.TOKEN, pay.TOKEN_2022):
            raise _no(kind, "the mint this request names does not exist")
        source = pay.ata(w, q.mint, program)
        state = passkey.read_wallet(_data(got, w))
        if q.nonce != (state.nonce if state else 0) + 1:
            raise _no(kind, passkey.ERRORS[119])
        dest = _data(got, q.to)
        if dest is None or len(dest) < 165 or bytes(dest[:32]) != bytes(q.mint) or q.to == source:
            raise _no(kind, "the destination is not a token account of this mint; it is made first (by whoever is paid), then the request is signed for it")
        if q.amount == 0 or _amount(_data(_read(ledger, [source]), source)) < q.amount:
            raise _no(kind, "the wallet holds less of this mint than the request asks for")
        ixs = [*([passkey.open_ix(me, q.key)] if state is None else []),
               *passkey.withdraw_ixs(q.key, q.mint, q.to, q.amount, q.nonce, q.authenticator_data, q.client_data_json, q.signature, program)]
        ask = getattr(ledger, "simulate", None)
        if ask is None:
            raise _no(kind, "this relay's ledger cannot simulate, and a withdrawal is never sent unchecked")
        try:
            ask(ixs, payer)
        except Exception as why:  # noqa: BLE001 - the chain's refusal, in the passkey program's words
            if transient(why) and _code(str(why)) is None:
                raise
            code = _code(str(why))
            raise _no(kind, f"{passkey.ERRORS[code]} (error {code})" if code in passkey.ERRORS else
                      "the passkey's signature does not verify: it is another key's, or over other bytes than this request's" if code is not None and code < 8 else
                      f"the chain would refuse it: {str(why)[:200]}") from None       # (the secp256r1 check's own errors are 0 to 4)
        return {"ok": True, **result, "sigs": [ledger.send(ixs, payer)]}
    except _Stop as stop:
        return stop.result
    except Exception as why:  # noqa: BLE001 - the cluster did not answer, or dropped it: the same request may be sent again
        return _failed(kind, why)


def _rent(size: int) -> int:
    """The lamports that keep an account of `size` bytes: 3,480 a byte and year, two years, 128 bytes of overhead
    (the cluster's rent parameters, the same on every public cluster)."""
    return (128 + size) * 6960


def passkey_fund(ledger, payer: Keypair, request: str | bytes | dict, repo_id: int | None = None, issue: int | None = None) -> dict:
    """The comment `/knos passkey-fund <base64url>` (web/passkey_fund.js writes it; commands.PasskeyFund is its parse):
    a passkey wallet funds a work order, and this relay sends it, for a funder who holds no SOL and no wallet app. One
    transaction: Open when the wallet's account is not there yet, the rent of the order and of its token account (the
    wallet holds data and cannot pay rent), the secp256r1 check of the passkey's signature, Fund.
    `request`: the comment, its base64url text, or the intent's object. `repo_id`, `issue`: where the comment was
    posted; given them, an intent the passkey signed for another issue is refused (a private order names neither).
    {"ok": True, "kind": "passkey-fund", "sigs", "wallet", "order", "mint", "repo_id", "issue", "amount", "fee",
    "nonce", "deadline"}, or {"ok": False, "kind": "passkey-fund", "why"}: `passkey_fund_reply` is the comment for
    either. The relay decides nothing: the passkey signed the order's terms, amount, mint, nonce and last slot.
    Everything is asked first, by reads and then by simulating the very transaction, so a line the chain would refuse
    (an expired slot, a nonce used already, a signature over other bytes) costs no fee; a ledger that cannot simulate
    sends none. What this relay spends on a good one, besides the fee: the rent of two accounts, which knos_pay
    returns to the WALLET when the order closes, not to the relay."""
    kind = "passkey-fund"
    try:
        q = pkfund.read_intent(request.decode() if isinstance(request, bytes) else request)
    except (ValueError, UnicodeDecodeError) as why:
        return {"ok": False, "kind": kind, "why": str(why)}
    try:
        me, w, order = payer.pubkey(), q.wallet, q.order
        ov, d = pay.ov_pda(order), q.data
        n, repo, private = int.from_bytes(d[1:9], "little"), int.from_bytes(d[9:17], "little"), d[pkfund.SALTED] == 1
        result = dict(kind=kind, wallet=str(w), order=str(order), mint=str(q.mint), repo_id=repo, issue=n, amount=q.amount, nonce=q.nonce)
        if repo_id is not None and not private and (repo, n) != (int(repo_id), int(issue or 0)):
            raise _no(kind, f"the passkey signed for issue #{n} of the repository with id {repo}, and this comment is on another issue; "
                            "post the line on that issue, or sign again for this one", astray=True)
        got = _read(ledger, [w, q.mint, order, ov, passkey.PASSKEY_ID, pay.PAY_ID])
        for program, name in ((passkey.PASSKEY_ID, "knos_passkey"), (pay.PAY_ID, "knos_pay")):
            if _data(got, program) is None:
                raise _no(kind, f"{name} ({program}) is not deployed on this cluster, so no passkey wallet can fund an order here")
        if old := live.needs(ledger, payer, "knos_passkey", ledger.now() if hasattr(ledger, "now") else None):     # Fund is 1.1's
            raise _no(kind, old)
        if (got[q.mint][0] if got.get(q.mint) else None) != q.token_program:
            raise _no(kind, "the mint this line names does not exist, or is not a mint of the token program it names")
        state = passkey.read_wallet(_data(got, w))
        if q.nonce != (state.nonce if state else 0) + 1:
            raise _no(kind, "the nonce is not the wallet's nonce plus one: this funding was sent already, or the wallet signed something else "
                            "after it; sign again on the Buy page")
        if _data(got, order) is not None:
            raise _no(kind, "there is an order at that address already: this wallet funded this issue before; sign again on the Buy page, "
                            "which then signs for the next order of the issue")
        need = q.amount + fees.live(ledger, payer).order(q.amount, decimals=_decimals(_data(got, q.mint)))
        source = pay.ata(w, q.mint, q.token_program)
        if _amount(_data(_read(ledger, [source]), source)) < need:
            raise _no(kind, f"the wallet holds less of this mint than the order's amount and its fee ({need} of its smallest units); "
                            "put more in the wallet, then post the same line again while its slot lasts")
        ixs = [*([passkey.open_ix(me, q.key)] if state is None else []),
               *pkfund.rent_ixs(me, order, ov, _rent(pkfund.ORDER_LEN), _rent(165)), *q.ixs()]
        ask = getattr(ledger, "simulate", None)
        if ask is None:
            raise _no(kind, "this relay's ledger cannot simulate, and a passkey's funding is never sent unchecked")
        v1 = not _fits(me, ixs) and bool(getattr(ledger, "takes_v1", False))
        try:
            ask(ixs, payer, v1=True) if v1 else ask(ixs, payer)
        except Exception as why:  # noqa: BLE001 - the chain's refusal, in the words of the program that refused
            code = _code(str(why))
            if transient(why) and code is None:
                raise
            words = {**passkey.ERRORS, **pkfund.ERRORS, 118: "the passkey signed for another funding: the order's data, the mint, the last slot or the nonce "
                     "differs from what this line says; sign again on the Buy page"}
            raise _no(kind, f"{words[code]} (error {code})" if code in words else f"{pay.ERRORS[code]} (error {code})" if code in pay.ERRORS else
                      "the passkey's signature does not verify: it is another key's, or over other bytes than this line's" if code is not None and code < 8 else
                      f"the chain would refuse it: {str(why)[:200]}") from None       # (the secp256r1 check's own errors are 0 to 4)
        sig = _send(ledger, payer, ixs, v1)
        o = pay.read_order(_data(_read(ledger, [order]), order))
        return {"ok": True, **result, "sigs": [sig], "fee": o.fee if o else None, "deadline": o.deadline if o else None}
    except _Stop as stop:
        return stop.result
    except Exception as why:  # noqa: BLE001 - the cluster did not answer, or dropped it: the same line may be sent again
        return _failed(kind, why)


def passkey_fund_reply(r: dict) -> str:
    """The comment that answers a `/knos passkey-fund` line: what happened, and what to do next."""
    if r.get("ok"):
        test = r.get("mint") in (str(pay.USDC_DEVNET), str(pay.faucet_mint()))
        money = (lambda n: f"{_units(n)} test USDC") if test else (lambda n: f"{n} units of the test token {r.get('mint')}")
        where = f"issue #{r['issue']}" if r.get("issue") else "a private order"
        fee = f", and the wallet paid {money(r['fee'])} fee on top" if r.get("fee") is not None else ""
        return (f"Knos: funded from a passkey wallet. {money(r['amount'])} is in escrow for {where}{fee}. The order is `{r['order']}` on Solana devnet. "
                + (f"If it is not paid by {_when(r['deadline'])}, anyone can send it back to the wallet. " if r.get("deadline") else "")
                + "Nobody can change its terms now. The funder paid no SOL: the relay paid the transaction and the order's rent.")
    again = " The same line can be posted again in a few minutes." if r.get("retry") else ""
    return f"Knos: nothing was funded and nothing left the passkey wallet: {r.get('why', 'the line was refused')}.{again}"


def _exp(jwt: bytes) -> int | None:
    """The expiry an unverified token claims; None when the bytes are not (yet) a whole token."""
    try:
        return int(claims_of(jwt.decode("ascii"))["exp"])
    except Exception:  # noqa: BLE001 - half written
        return None


def sweep(ledger, payer: Keypair, now: int) -> list[str]:
    """Takes back the rent of this relayer's token accounts that nothing can use any more, on both verifiers: each
    one whose token is an hour past its expiry (a verify-only account is left for its consumer until then), verified
    or cut short; and one that never got its whole token, an hour after its last transaction. Needs
    ledger.program_accounts."""
    me, txs, seen = payer.pubkey(), [], getattr(ledger, "touched", None)
    for program in (oidc.OIDC_ID, first_oidc.OIDC_ID):
        for addr, data in ledger.program_accounts(program, None, {_T_PAYER: bytes(me)}):
            tok = oidc.read_token(data)
            if tok is None or tok.payer != me:
                continue
            exp = tok.exp if tok.verified else _exp(bytes(data[oidc.T_JWT:]))
            if exp is None and seen is not None:
                exp = seen(addr)
            if exp is not None and exp + oidc.LATE <= now:
                txs.append([oidc.close_ix(me, bytes(data[_T_ID:_T_ID + 32]), program)])
    return _each(ledger, payer, txs)


def register_missing(ledger, payer: Keypair, jwks: dict | None = None) -> list[str]:
    """What anyone can do for the verifier's keys with no token: register each of GitHub's genesis keys the chain has
    not seen, and send the parameters of a key that was registered without them."""
    me, txs = payer.pubkey(), []
    for _kid, n in oidc.jwks_keys(_jwks(oidc.GITHUB, jwks)):
        if oidc.key_hash(n).hex() in GENESIS and ledger.account(oidc.key_pda(oidc.GITHUB, n)) is None:
            txs.append([oidc.register_key_ix(me, oidc.GITHUB, n), oidc.key_params_ix(me, oidc.GITHUB, n)])
    for _addr, k, n in keys(ledger):
        if k.state == 0 and not k.revoked:
            txs.append([oidc.key_params_ix(me, k.issuer, n)])
    return _each(ledger, payer, txs)
