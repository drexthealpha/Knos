"""Client for the second deployment of knos-oidc (programs-v2/knos_oidc): the Solana program that verifies an RS256
OIDC token from GitHub Actions, GitLab CI or any other RS256 issuer on chain. Pure instruction builders and account
readers; no network.

Writing, stepping and closing a token are the first deployment's instructions, byte for byte, sent to this program;
the same names are here. What is new is how a signing key lives:

    register_key_ix(payer, issuer, n, attest, attest_key)   # a key GitHub's signature names; it waits KEY_DELAY and the guardian
    refresh_ix(payer, issuer, n, attest, attest_key)        # the same attestation again: the key lives KEY_TTL from now
                                                            # attest_key: the key account that verified `attest`
                                                            # (read_token(attest's data).key); it must be usable now
    approve_ix(guardian, issuer, n)                  # the guardian lets an attested key be used
    revoke_ix(guardian, issuer, n)                   # the guardian ends a key, for ever
    ok, why = key_usable(read_key(account_data), now)   # what Step will say about this key, before a fee is spent

Any other RS256 issuer is named by its URL (its `iss`), a str where GitHub and GitLab are the numbers 0 and 1:

    register_issuer_key_ix(payer, url, n, attest, attest_key)   # the attester's run named this key of that issuer
    key_pda(url, n), key_params_ix(payer, url, n), refresh_ix(payer, url, n, ...), approve_ix, revoke_ix: the same, by URL
    token_issuer(token_account_data)                    # (sha256 of the issuer's URL, registrant or None) of such a token

A PRIVATE key is one a wallet registers itself, with no attestation, for an issuer no public runner can reach (a
company's GitHub Enterprise Server). Nobody vouches for it: a token it verified says what that wallet says.

    register_private_key_ix(registrant, url, n)         # usable at once, for KEY_TTL; sent again it renews the key
    key_pda(url, n, registrant=wallet), key_params_ix(..., registrant=wallet), revoke_ix(wallet, url, n, registrant=wallet)
    read_key(...).private, .registrant                  # and token_issuer(...)[1]: the wallet, in every token it verified
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from . import load_ids
from .. import oidc as _first
from ..oidc import (CHUNK, GITHUB, GITLAB, ISSUERS, JWKS, LATE, MAX_JWT, SYSTEM, T_JWT, Token, jwks_keys, key_hash, key_params,  # noqa: F401
                    modulus_bytes, read_token, step_plan, token_id)

IDS = load_ids()            # the pinned ids, or a staging deployment named by KNOS_PROGRAM_IDS
OIDC_ID = Pubkey.from_string(IDS["knos_oidc"])
GUARDIAN = Pubkey.from_string(IDS["guardian"])    # a multisig vault: it approves attested keys and revokes keys, nothing else

KEY_DELAY = 86_400          # a key admitted by an attestation verifies nothing for a day
KEY_TTL = 30 * 86_400       # a key expires this long after it was last attested
K_HDR = 40                  # the key account's header; n and r2 follow
KEY_TAIL = 64                 # after r2, for a key that is not GitHub's or GitLab's by number: sha256(issuer URL), registrant
APPROVED, REVOKED, GENESIS = 1, 2, 4
OTHER = 2                   # the issuer number of a key (and of a token it verified) of any other issuer: see its hash
PRIVATE = 3                 # the issuer number of a private key and of a token it verified: see its registrant
PRIVATE_FLAG = 8            # and its flag in the key account
MAX_ISS = 200               # the longest issuer URL
T_IHASH = 114               # in such a token account once VERIFIED: sha256(issuer URL), then the registrant (zero: none)


def token_pda(payer: Pubkey, tid: bytes, program: Pubkey = OIDC_ID) -> Pubkey:
    return _first.token_pda(payer, tid, program)


def issuer_hash(url: str) -> bytes:
    """What names an issuer on chain: sha256 of its URL, exactly as the issuer writes it in `iss`."""
    return hashlib.sha256(url.encode()).digest()


def key_pda(issuer: int | str, n: int, program: Pubkey = OIDC_ID, registrant: Pubkey | None = None) -> Pubkey:
    """The key account of GitHub (0) or GitLab (1), of any other issuer named by its URL, or (with `registrant`) the
    private key that wallet registered for that URL."""
    if registrant is not None:
        return Pubkey.find_program_address([b"pkey", bytes(registrant), issuer_hash(str(issuer)), key_hash(n)], program)[0]
    if isinstance(issuer, str):
        return Pubkey.find_program_address([b"ikey", issuer_hash(issuer), key_hash(n)], program)[0]
    return _first.key_pda(issuer, n, program)


def iss_pda(url: str, program: Pubkey = OIDC_ID) -> Pubkey:
    """The account that holds an issuer's URL, created with its first key."""
    return Pubkey.find_program_address([b"iss", issuer_hash(url)], program)[0]


def read_iss(data: bytes | None) -> str | None:
    """The URL in an issuer account; None for anything else."""
    if not data or len(data) < 4 or data[0] != 3 or len(data) != 4 + data[3]:
        return None
    return bytes(data[4:]).decode()


def rotate_audience(issuer: int | str, n: int) -> str:
    """The audience the pinned rotate workflow asks GitHub to sign for a key it found in the issuer's key set."""
    if isinstance(issuer, str):
        return f"knos-oidc:ikey:{issuer_hash(issuer).hex()}:{key_hash(n).hex()}"
    return _first.rotate_audience(issuer, n)


def write_ixs(payer: Pubkey, tid: bytes, jwt: str | bytes, program: Pubkey = OIDC_ID) -> list[Instruction]:
    return _first.write_ixs(payer, tid, jwt, program)


def step_ix(payer: Pubkey, tid: bytes, key: Pubkey, squarings: int, program: Pubkey = OIDC_ID) -> Instruction:
    return _first.step_ix(payer, tid, key, squarings, program)


def close_ix(payer: Pubkey, tid: bytes, program: Pubkey = OIDC_ID) -> Instruction:
    return _first.close_ix(payer, tid, program)


def _with_attest_key(ix: Instruction, attest_key: Pubkey | None) -> Instruction:
    """The key account that verified the attestation goes right after it, read-only."""
    if attest_key is None:
        return ix
    return Instruction(ix.program_id, bytes(ix.data), [*ix.accounts, AccountMeta(attest_key, False, False)])


def register_key_ix(payer: Pubkey, issuer: int, n: int, attest: Pubkey | None = None, attest_key: Pubkey | None = None,
                    program: Pubkey = OIDC_ID) -> Instruction:
    """A genesis key (one of GitHub's four) needs no `attest`. Any other key needs a VERIFIED token account whose
    audience is rotate_audience(issuer, n), from the pinned rotate workflow run in the attester's repository, and
    `attest_key`: the key account that verified that token (read_token(its data).key), usable now. The program
    refuses an attested registration sent without it."""
    return _with_attest_key(_first.register_key_ix(payer, issuer, n, attest, program), attest_key if attest is not None else None)


def register_issuer_key_ix(payer: Pubkey, url: str, n: int, attest: Pubkey, attest_key: Pubkey, program: Pubkey = OIDC_ID) -> Instruction:
    """A key of any RS256 issuer, named by the issuer's URL. `attest`: a VERIFIED token account whose audience is
    rotate_audience(url, n), from the attester's run of the pinned rotate workflow; `attest_key`: the key account that
    verified it. The key waits KEY_DELAY and the guardian, like any attested key."""
    return Instruction(program, b"\x08" + _url_and_modulus(url, n),
                       [AccountMeta(payer, True, True), AccountMeta(key_pda(url, n, program), False, True), AccountMeta(iss_pda(url, program), False, True),
                        AccountMeta(SYSTEM, False, False), AccountMeta(attest, False, False), AccountMeta(attest_key, False, False)])


def _url_and_modulus(url: str, n: int) -> bytes:
    u = url.encode()
    if not (8 < len(u) <= MAX_ISS) or not url.startswith("https://"):
        raise ValueError(f"an issuer URL starts with https:// and has at most {MAX_ISS} bytes")
    return bytes([len(u)]) + u + modulus_bytes(n)


def register_private_key_ix(registrant: Pubkey, url: str, n: int, program: Pubkey = OIDC_ID) -> Instruction:
    """A private key: the wallet `registrant` says that `n` is a key of the issuer at `url`, and nobody checks it.
    Usable at once (after KeyParams) for KEY_TTL; sent again by the same wallet it renews the key. Every token it
    verifies carries the wallet's address, and a consumer accepts it only from a wallet it trusts for that purpose."""
    return Instruction(program, b"\x09" + _url_and_modulus(url, n),
                       [AccountMeta(registrant, True, True), AccountMeta(key_pda(url, n, program, registrant), False, True), AccountMeta(SYSTEM, False, False)])


def key_params_ix(payer: Pubkey, issuer: int | str, n: int, program: Pubkey = OIDC_ID, registrant: Pubkey | None = None) -> Instruction:
    n0inv, r2 = key_params(n)
    return Instruction(program, b"\x04" + n0inv.to_bytes(4, "little") + r2,
                       [AccountMeta(payer, True, False), AccountMeta(key_pda(issuer, n, program, registrant), False, True)])


def refresh_ix(payer: Pubkey, issuer: int | str, n: int, attest: Pubkey, attest_key: Pubkey | None = None, program: Pubkey = OIDC_ID) -> Instruction:
    """The key's expiry becomes now + KEY_TTL if that is later. `attest` and `attest_key` as for register_key_ix (the
    program refuses a Refresh sent without `attest_key`). Anyone may send it."""
    return _with_attest_key(Instruction(program, b"\x05", [AccountMeta(payer, True, False), AccountMeta(key_pda(issuer, n, program), False, True),
                                                           AccountMeta(attest, False, False)]), attest_key)


def approve_ix(guardian: Pubkey, issuer: int | str, n: int, program: Pubkey = OIDC_ID) -> Instruction:
    return Instruction(program, b"\x06", [AccountMeta(guardian, True, False), AccountMeta(key_pda(issuer, n, program), False, True)])


def revoke_ix(guardian: Pubkey, issuer: int | str, n: int, program: Pubkey = OIDC_ID, registrant: Pubkey | None = None) -> Instruction:
    """For ever: no instruction undoes it, and the same modulus cannot be registered for that issuer again. The signer
    is the guardian, or for a private key (`registrant`) the wallet that registered it."""
    return Instruction(program, b"\x07", [AccountMeta(guardian, True, False), AccountMeta(key_pda(issuer, n, program, registrant), False, True)])


@dataclass
class Key:
    state: int          # 0 created, 1 ready (its Montgomery constants are on chain and checked)
    issuer: int
    bits: int           # 2048 or 4096
    active_at: int      # the key verifies nothing before this time
    expires_at: int     # nor from this time on
    approved: bool      # by the guardian (a genesis key is created approved)
    revoked: bool
    genesis: bool
    issuer_hash: bytes | None = None    # sha256 of the issuer's URL, for a key that is not GitHub's (0) or GitLab's (1)
    private: bool = False               # registered by a wallet with no attestation: nobody vouches for it
    registrant: Pubkey | None = None    # that wallet


def read_key(data: bytes | None) -> Key | None:
    """A key account's header; None for anything that is not a key account of this layout."""
    if not data or len(data) < K_HDR or data[2] not in (64, 128) or len(data) != K_HDR + 8 * data[2] + (KEY_TAIL if data[1] >= OTHER else 0):
        return None
    flags, tail = data[24], K_HDR + 8 * data[2]
    return Key(state=data[0], issuer=data[1], bits=32 * data[2], active_at=int.from_bytes(data[8:16], "little", signed=True),
               expires_at=int.from_bytes(data[16:24], "little", signed=True),
               approved=bool(flags & APPROVED), revoked=bool(flags & REVOKED), genesis=bool(flags & GENESIS),
               issuer_hash=bytes(data[tail:tail + 32]) if data[1] >= OTHER else None, private=bool(flags & PRIVATE_FLAG),
               registrant=Pubkey.from_bytes(bytes(data[tail + 32:tail + 64])) if flags & PRIVATE_FLAG and data[1] == PRIVATE else None)


def token_issuer(data: bytes | None) -> tuple[bytes, Pubkey | None] | None:
    """For a VERIFIED token account of an issuer that is not GitHub (0) or GitLab (1): sha256 of the issuer's URL, and
    the wallet that registered the key when it is a private one. None for any other account."""
    if not data or len(data) < T_JWT or data[0] != 2 or data[1] < OTHER:
        return None
    registrant = bytes(data[T_IHASH + 32:T_IHASH + 64])
    return bytes(data[T_IHASH:T_IHASH + 32]), (Pubkey.from_bytes(registrant) if any(registrant) else None)


def _when(t: int) -> str:
    try:
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (OverflowError, OSError, ValueError):
        return f"time {t}"


def key_usable(key: Key | None, now: int) -> tuple[bool, str]:
    """Whether Step accepts this key at `now` (the chain's clock), and if not, why and what to do. The same checks,
    in the same order, as the program's."""
    if key is None:
        return False, "this signing key is not on chain yet. Send RegisterKey with an attestation from the rotate workflow."
    if key.state != 1:
        return False, "this signing key is registered but not ready. Send KeyParams for it (anyone can)."
    if key.revoked:
        return False, "the guardian revoked this signing key. It cannot be used again."
    if not (key.genesis or key.approved or key.private):
        wait = f" Its {KEY_DELAY // 3600}-hour wait ends {_when(key.active_at)}." if now < key.active_at else ""
        return False, f"this signing key is new and the guardian has not approved it yet.{wait} Try again after the approval."
    if now < key.active_at:
        return False, f"this signing key is new: it can be used from {_when(key.active_at)}. Try again then."
    if now >= key.expires_at:
        return False, (f"this signing key expired {_when(key.expires_at)}: nothing attested it for {KEY_TTL // 86_400} days. "
                       "Run the rotate workflow and send Refresh with its token.")
    return True, ""


# ---- ES256: a token signed with ECDSA on P-256, verified in ONE transaction (programs-v2/knos_oidc/src/es256.rs) -------
#
#    register_private_es256_key_ix(wallet, url, key)        # tag 11: a wallet says `key` is a P-256 key of the issuer at `url`
#    verify_es256_ixs(payer, key_account, jwt, key)         # the secp256r1 precompile, then tag 15: both in one transaction
#    es256_token_id(jwt), token_pda(payer, that)            # where the VERIFIED token is, with the layout of an RS256 one
#    read_ec_key(account_data), ec_key_usable(...)          # a P-256 key account
#
# The program does no curve arithmetic: Solana's secp256r1 precompile verifies the signature as the instruction right
# before VerifyEs256, and the program reads from it what was verified. So the whole signing input rides in the
# transaction, and it can be at most MAX_ES256_INPUT bytes. The precompile takes only the lower s: `es256_parts`
# replaces s by n - s where an issuer wrote the upper one, which needs no secret and changes nothing that is signed.
# A key GitHub's rotate workflow attests (tags 10, 12, 13) has no client here: no pinned commit of that workflow asks for
# its audience yet. `tests/test_es256_client.py` runs these against the built program in the simulator.
SECP256R1_ID = Pubkey.from_string("Secp256r1SigVerify1111111111111111111111111")     # SIMD-0075
SYSVAR_INSTRUCTIONS = Pubkey.from_string("Sysvar1nstructions1111111111111111111111111")
EC_KEY_LEN = 33             # a P-256 public key, SEC1 compressed: 0x02 or 0x03, then x
EC_SIG_LEN = 64             # r then s, 32 bytes each, as JWS writes an ES256 signature
EC_MARK = 0xEC              # the third byte of a P-256 key account, where an RSA key holds its limb count
EC_ACCOUNT = K_HDR + EC_KEY_LEN + KEY_TAIL      # 137
MAX_ES256_INPUT = 780       # the longest signing input a legacy transaction carries beside the two instructions (docs/ES256.md)
P256_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
_P256_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_P256_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_SELF = 0xFFFF              # an instruction index of the precompile: "these bytes are in my own data"



def _unb64(text: str | bytes) -> bytes:
    import base64
    raw = text.encode() if isinstance(text, str) else bytes(text)
    return base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))


def ec_key(x: int | bytes | str, y: int | bytes | str | None = None) -> bytes:
    """A P-256 public key as the key account and the precompile hold it: SEC1 compressed. `x`, `y`: the point, as
    numbers, 32 bytes each, or the base64url text of a JWK's `x` and `y` (kty EC, crv P-256). With `x` alone: 33 bytes
    already compressed, checked. ValueError for what is not a point of the curve."""
    def number(v) -> int:
        if isinstance(v, int) and not isinstance(v, bool):
            return v
        raw = _unb64(v) if isinstance(v, str) else bytes(v)
        if len(raw) != 32:
            raise ValueError("a P-256 coordinate is 32 bytes")
        return int.from_bytes(raw, "big")
    if y is None:
        key = bytes.fromhex(x) if isinstance(x, str) else bytes(x)       # type: ignore[arg-type]
        if len(key) != EC_KEY_LEN or key[0] not in (2, 3):
            raise ValueError("a compressed P-256 key is 33 bytes that start with 02 or 03")
        px = int.from_bytes(key[1:], "big")
        side = (px * px * px - 3 * px + _P256_B) % _P256_P
        if px >= _P256_P or pow(pow(side, (_P256_P + 1) // 4, _P256_P), 2, _P256_P) != side:
            raise ValueError("not a point of P-256")
        return key
    px, py = number(x), number(y)
    if not (0 <= px < _P256_P and 0 <= py < _P256_P) or (py * py - (px * px * px - 3 * px + _P256_B)) % _P256_P != 0:
        raise ValueError("not a point of P-256")
    return bytes([2 + (py & 1)]) + px.to_bytes(32, "big")


def ec_key_hash(key: bytes) -> bytes:
    return hashlib.sha256(ec_key(key)).digest()


def ec_key_pda(url: str, key: bytes, program: Pubkey = OIDC_ID, registrant: Pubkey | None = None) -> Pubkey:
    """The account of a P-256 key of the issuer at `url`: the one a wallet registered itself (`registrant`), or the
    one an attestation admitted."""
    if registrant is not None:
        return Pubkey.find_program_address([b"epkey", bytes(registrant), issuer_hash(url), ec_key_hash(key)], program)[0]
    return Pubkey.find_program_address([b"eckey", issuer_hash(url), ec_key_hash(key)], program)[0]


def _url_and_ec_key(url: str, key: bytes) -> bytes:
    raw = url.encode()
    if not (8 < len(raw) <= MAX_ISS and url.startswith("https://") and all(0x21 <= c < 0x7F and c not in (0x22, 0x5C) for c in raw)):
        raise ValueError("an issuer's URL starts with https://, is printable ASCII with no quote and no backslash, and is at most 200 bytes")
    return bytes([len(raw)]) + raw + ec_key(key)


def register_private_es256_key_ix(registrant: Pubkey, url: str, key: bytes, program: Pubkey = OIDC_ID) -> Instruction:
    """A private P-256 key (tag 11): the wallet `registrant` says that `key` is a key of the issuer at `url`, and nobody
    checks it. Usable at once, for KEY_TTL; sent again by the same wallet it renews the key. Every token it verifies
    carries the wallet's address, and a consumer accepts it only from a wallet it trusts for that purpose."""
    return Instruction(program, b"\x0b" + _url_and_ec_key(url, key),
                       [AccountMeta(registrant, True, True), AccountMeta(ec_key_pda(url, key, program, registrant), False, True), AccountMeta(SYSTEM, False, False)])


def revoke_es256_ix(signer: Pubkey, url: str, key: bytes, program: Pubkey = OIDC_ID, registrant: Pubkey | None = None) -> Instruction:
    """Ends a P-256 key for ever (tag 14). `signer`: the guardian, or for a private key (`registrant`) that wallet."""
    return Instruction(program, b"\x0e", [AccountMeta(signer, True, False), AccountMeta(ec_key_pda(url, key, program, registrant), False, True)])


def es256_parts(jwt: str | bytes) -> tuple[bytes, bytes]:
    """(the signing input, the signature with the lower s) of a compact ES256 token: what the precompile is given. The
    signing input is `base64url(header).base64url(payload)`, untouched. ValueError for what is not such a token."""
    text = (jwt.decode() if isinstance(jwt, bytes) else jwt).strip()
    parts = text.split(".")
    if len(parts) != 3 or not all(parts):
        raise ValueError("a compact token is three parts with two dots")
    try:
        signature = _unb64(parts[2])
    except ValueError:
        signature = b""
    if len(signature) != EC_SIG_LEN:
        raise ValueError("an ES256 signature is 64 bytes: r then s (RFC 7518, section 3.4)")
    r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    if not (0 < r < P256_N and 0 < s < P256_N):
        raise ValueError("r and s of an ES256 signature are above zero and below the curve's order")
    message = f"{parts[0]}.{parts[1]}".encode()
    if len(message) > MAX_ES256_INPUT:
        raise ValueError(f"the signing input is {len(message)} bytes; one transaction carries at most {MAX_ES256_INPUT}")
    return message, signature[:32] + min(s, P256_N - s).to_bytes(32, "big")


def es256_token_id(jwt: str | bytes) -> bytes:
    """What names the token account VerifyEs256 writes: sha256 of the signing input (`token_pda(payer, this)`)."""
    return hashlib.sha256(es256_parts(jwt)[0]).digest()


def secp256r1_ix(key: bytes, signature: bytes, message: bytes) -> Instruction:
    """The secp256r1 precompile's instruction for one signature, every part in its own data: count, padding, seven
    u16 LE (signature offset, instruction, key offset, instruction, message offset, length, instruction), then the
    key, the signature and the message. It has no accounts."""
    if len(signature) != EC_SIG_LEN:
        raise ValueError("the signature is 64 bytes")
    head = bytes([1, 0])
    for v in (16 + EC_KEY_LEN, _SELF, 16, _SELF, 16 + EC_KEY_LEN + EC_SIG_LEN, len(message), _SELF):
        head += v.to_bytes(2, "little")
    return Instruction(SECP256R1_ID, head + ec_key(key) + bytes(signature) + bytes(message), [])


def verify_es256_ixs(payer: Pubkey, key_account: Pubkey, jwt: str | bytes, key: bytes, program: Pubkey = OIDC_ID) -> list[Instruction]:
    """The two instructions that verify an ES256 token, to be sent one right after the other in ONE transaction: the
    precompile over the token's signing input, then VerifyEs256 (tag 15, no data), which creates the token account
    `token_pda(payer, es256_token_id(jwt))` VERIFIED. `key_account`: `ec_key_pda(...)`; `key`: the 33 bytes it holds.
    The payer pays the account's rent. Nothing but a compute-budget instruction may stand before the first."""
    message, signature = es256_parts(jwt)
    token = token_pda(payer, hashlib.sha256(message).digest(), program)
    return [secp256r1_ix(key, signature, message),
            Instruction(program, b"\x0f", [AccountMeta(payer, True, True), AccountMeta(token, False, True), AccountMeta(key_account, False, False),
                                           AccountMeta(SYSTEM, False, False), AccountMeta(SYSVAR_INSTRUCTIONS, False, False)])]


@dataclass
class EcKey:
    issuer: int             # OTHER (an attested key) or PRIVATE
    key: bytes              # the 33 bytes, SEC1 compressed
    active_at: int
    expires_at: int
    approved: bool
    revoked: bool
    private: bool
    issuer_hash: bytes      # sha256 of the issuer's URL
    registrant: Pubkey | None = None    # the wallet that registered a private key


def read_ec_key(data: bytes | None) -> EcKey | None:
    """A P-256 key account; None for anything else (an RSA key account holds 64 or 128 where this holds EC_MARK)."""
    if not data or len(data) != EC_ACCOUNT or data[0] != 1 or data[2] != EC_MARK:
        return None
    flags, tail = data[24], K_HDR + EC_KEY_LEN
    return EcKey(issuer=data[1], key=bytes(data[K_HDR:tail]), active_at=int.from_bytes(data[8:16], "little", signed=True),
                 expires_at=int.from_bytes(data[16:24], "little", signed=True), approved=bool(flags & APPROVED), revoked=bool(flags & REVOKED),
                 private=bool(flags & PRIVATE_FLAG), issuer_hash=bytes(data[tail:tail + 32]),
                 registrant=Pubkey.from_bytes(bytes(data[tail + 32:tail + 64])) if flags & PRIVATE_FLAG and data[1] == PRIVATE else None)


def ec_key_usable(key: EcKey | None, now: int) -> tuple[bool, str]:
    """Whether VerifyEs256 accepts this key at `now` (the chain's clock), and if not, why. The rule is Step's for an
    RSA key: not revoked; approved by the guardian unless it is a private key; inside its time."""
    if key is None:
        return False, "this P-256 key is not on chain. Register it first (a private key: RegisterPrivateEs256Key, by the wallet that vouches for it)."
    if key.revoked:
        return False, "this P-256 key was revoked. It cannot be used again."
    if not (key.approved or key.private):
        return False, "this P-256 key is new and the guardian has not approved it yet. Try again after the approval."
    if now < key.active_at:
        return False, f"this P-256 key is new: it can be used from {_when(key.active_at)}. Try again then."
    if now >= key.expires_at:
        return False, f"this P-256 key expired {_when(key.expires_at)}. A private key is renewed by its wallet sending the registration again."
    return True, ""
