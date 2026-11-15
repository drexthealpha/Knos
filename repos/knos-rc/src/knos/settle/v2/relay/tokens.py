"""A token as the relay reads it before any fee is spent: its claims, the key that signed it (`signed`, `other_keys`),
the workflow that asked for it, and the lane it travels in (`lane`)."""
from __future__ import annotations

import base64
import hashlib
import json
import time

from dataclasses import dataclass, field
from datetime import datetime, timezone

from solders.pubkey import Pubkey

from ... import relay as first
from ...relay import claims_of, header_of
from .. import oidc, pay

from .pins import JWKS_TTL, _DIGEST_INFO


# the audiences that name one order and write no Balance's state: their lane is the order, so one owner's orders
# spread over relays while one order's tokens (take, cancel, pay, revert, ...) still leave in the order they came
ORDER_LANES = ("knos3:pay:", "knos3:auto:", "knos3:rule:", "knos3:take:", "knos3:cancel:", "knos3:revert:")


def lane(jwt: str) -> str:
    """The lane a token travels in when several are carried at once (knos.settle.v2.relayq): two tokens of one lane
    may write the same account, so they are sent one after the other, in the order they came.
    A token that pays, rules on, reserves, cancels or reverts a work order (ORDER_LANES) writes that order, its
    payees' records, a fee account or (a revert) the token account its money goes back to, never a Balance's own
    account, which fundings write in the order GitHub issued them: its lane is the ORDER (`order:<address>`), so one
    owner's many orders go to many relays at once while one order's tokens still leave one at a time. Any other
    token (a funding from a Balance, a job of the first generation) writes accounts its owner's other tokens write
    too: its lane is the account that owns the repository it was signed for (`repository_owner_id`). A token that names neither travels alone. Read from the token as it says it,
    unverified: a wrong lane costs speed, never money (the chain takes a token once)."""
    try:
        body = jwt.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        aud = claims.get("aud")
        aud = aud[0] if isinstance(aud, list) and aud else aud
        if isinstance(aud, str) and aud.startswith(ORDER_LANES):
            order = aud.split(":")[2]
            if 32 <= len(order) <= 44:
                return f"order:{order}"
        owner = claims.get("repository_owner_id") or claims.get("namespace_id") or claims.get("sub")
    except (IndexError, ValueError, AttributeError):
        owner = None
    return f"owner:{owner}" if owner else "alone:" + hashlib.sha256(jwt.encode()).hexdigest()[:16]


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


_KEPT: dict[int | str, tuple[float, dict]] = {}


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


def _exp(jwt: bytes) -> int | None:
    """The expiry an unverified token claims; None when the bytes are not (yet) a whole token."""
    try:
        return int(claims_of(jwt.decode("ascii"))["exp"])
    except Exception:  # noqa: BLE001 - half written
        return None
