"""Client for knos-oidc (programs/knos_oidc): the Solana program that verifies an RS256 OIDC token from GitHub
Actions or GitLab CI on chain. Pure instruction builders and account readers; no network.

    ixs = write_ixs(payer, tid, jwt)                 # the token into its account (several chunks)
    for sq in step_plan(bits): step_ix(payer, tid, key, sq)   # 2048-bit: [8, 8]; 4096-bit: [2, 3, 3, 3, 4, 1]
    read_token(account_data).payload                 # the verified claims, once the last step has run
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

SYSTEM = Pubkey.from_string("11111111111111111111111111111111")
IDS = json.loads(resources.files(__package__).joinpath("program_ids.json").read_text())
OIDC_ID = Pubkey.from_string(IDS["knos_oidc"])

GITHUB, GITLAB = 0, 1
ISSUERS = {GITHUB: "https://token.actions.githubusercontent.com", GITLAB: "https://gitlab.com"}
JWKS = {GITHUB: "https://token.actions.githubusercontent.com/.well-known/jwks", GITLAB: "https://gitlab.com/oauth/discovery/keys"}
MAX_JWT = 8192
LATE = 3600         # a token is accepted up to an hour past its exp (each instruction has its own replay guard)
T_JWT = 626
CHUNK = 880          # token bytes per Write instruction (one per transaction)


def token_id(jwt: str | bytes) -> bytes:
    return hashlib.sha256(jwt if isinstance(jwt, bytes) else jwt.encode()).digest()


def token_pda(payer: Pubkey, tid: bytes, program: Pubkey = OIDC_ID) -> Pubkey:
    return Pubkey.find_program_address([b"tok", bytes(payer), tid], program)[0]


def modulus_bytes(n: int) -> bytes:
    k = (n.bit_length() + 7) // 8
    if k not in (256, 512):
        raise ValueError("only 2048- and 4096-bit RSA keys are supported")
    return n.to_bytes(k, "big")


def key_hash(n: int) -> bytes:
    return hashlib.sha256(modulus_bytes(n)).digest()


def key_pda(issuer: int, n: int, program: Pubkey = OIDC_ID) -> Pubkey:
    return Pubkey.find_program_address([b"key", bytes([issuer]), key_hash(n)], program)[0]


def key_params(n: int) -> tuple[int, bytes]:
    """(n0inv, r2): -n^-1 mod 2^32 and R^2 mod n (R = 2^bits), which KeyParams takes and checks on chain."""
    k = len(modulus_bytes(n))
    n0inv = (-pow(n, -1, 1 << 32)) % (1 << 32)
    return n0inv, pow(2, 16 * k, n).to_bytes(k, "big")


def step_plan(bits: int) -> list[int]:
    """Squarings per Step transaction, 16 in all, so that every transaction stays under the 1,400,000 compute units
    a transaction can have, for a token of any size up to MAX_JWT. Measured in tests/test_oidc_chain.py.

    2048-bit: [8, 8]. 4096-bit: [2, 3, 3, 3, 4, 1]. The first call also puts the signature in Montgomery form, so it
    has room for two squarings; a middle call for four. The call that finishes also hashes the token, decodes its
    payload and reads its claims, work that grows with the token, so it gets one squaring. This function used to
    return [2, 3, 3, 3, 3, 2]: with two squarings the last call ran out of compute units once a GitLab token passed
    about 5,000 bytes (a few hundred bytes earlier or later for claims of another shape).
    """
    return [8, 8] if bits == 2048 else [2, 3, 3, 3, 4, 1]


def write_ixs(payer: Pubkey, tid: bytes, jwt: str | bytes, program: Pubkey = OIDC_ID) -> list[Instruction]:
    raw = jwt if isinstance(jwt, bytes) else jwt.encode()
    if not 0 < len(raw) <= MAX_JWT:
        raise ValueError(f"token is {len(raw)} bytes; the verifier takes up to {MAX_JWT}")
    acc = [AccountMeta(payer, True, True), AccountMeta(token_pda(payer, tid, program), False, True), AccountMeta(SYSTEM, False, False)]
    out = []
    for off in range(0, len(raw), CHUNK):
        chunk = raw[off:off + CHUNK]
        out.append(Instruction(program, b"\x00" + tid + len(raw).to_bytes(2, "little") + off.to_bytes(2, "little") + chunk, acc))
    return out


def step_ix(payer: Pubkey, tid: bytes, key: Pubkey, squarings: int, program: Pubkey = OIDC_ID) -> Instruction:
    return Instruction(program, b"\x01" + tid + bytes([squarings]),
                       [AccountMeta(payer, True, False), AccountMeta(token_pda(payer, tid, program), False, True), AccountMeta(key, False, False)])


def close_ix(payer: Pubkey, tid: bytes, program: Pubkey = OIDC_ID) -> Instruction:
    return Instruction(program, b"\x02" + tid, [AccountMeta(payer, True, True), AccountMeta(token_pda(payer, tid, program), False, True)])


def register_key_ix(payer: Pubkey, issuer: int, n: int, attest: Pubkey | None = None, program: Pubkey = OIDC_ID) -> Instruction:
    acc = [AccountMeta(payer, True, True), AccountMeta(key_pda(issuer, n, program), False, True), AccountMeta(SYSTEM, False, False)]
    if attest is not None:
        acc.append(AccountMeta(attest, False, False))
    return Instruction(program, b"\x03" + bytes([issuer]) + modulus_bytes(n), acc)


def key_params_ix(payer: Pubkey, issuer: int, n: int, program: Pubkey = OIDC_ID) -> Instruction:
    n0inv, r2 = key_params(n)
    return Instruction(program, b"\x04" + n0inv.to_bytes(4, "little") + r2,
                       [AccountMeta(payer, True, False), AccountMeta(key_pda(issuer, n, program), False, True)])


def rotate_audience(issuer: int, n: int) -> str:
    """The audience the pinned rotate workflow asks GitHub to sign for a key it found in the issuer's JWKS."""
    return f"knos-oidc:key:{issuer}:{key_hash(n).hex()}"


@dataclass
class Token:
    stage: int          # 0 writing, 1 stepping, 2 verified
    issuer: int
    done: int           # squarings done, of 16
    exp: int
    key: Pubkey
    payer: Pubkey
    payload: bytes      # the decoded claims (JSON), only when verified

    @property
    def verified(self) -> bool:
        return self.stage == 2

    def claims(self) -> dict:
        return json.loads(self.payload)


def read_token(data: bytes | None) -> Token | None:
    if not data or len(data) < T_JWT:
        return None
    off, ln = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
    return Token(stage=data[0], issuer=data[1], done=data[2], exp=int.from_bytes(data[10:18], "little", signed=True),
                 key=Pubkey.from_bytes(data[18:50]), payer=Pubkey.from_bytes(data[50:82]),
                 payload=bytes(data[off:off + ln]) if data[0] == 2 else b"")


def jwks_keys(jwks: dict) -> list[tuple[str, int]]:
    """(kid, modulus) for each RS256 key with exponent 65537 in a JWKS document."""
    import base64
    out = []
    for k in jwks.get("keys", []):
        if k.get("kty") == "RSA" and k.get("e") == "AQAB" and k.get("alg", "RS256") == "RS256":
            out.append((k.get("kid", ""), int.from_bytes(base64.urlsafe_b64decode(k["n"] + "=" * (-len(k["n"]) % 4)), "big")))
    return out
