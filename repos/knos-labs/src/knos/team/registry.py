"""A team on chain: one SAS credential named `knos-<16 random hex>` whose authority is the owner key, the four Knos
schemas under it, and one `knos.member.v1` attestation per member (nonce = the member's public key).

The member attestation holds the display name and the team salt, both sealed so that only members can read them:
the salt in a PyNaCl sealed box to the member's own key, the name in a secret box keyed from the salt.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from . import rpc, sas, schemas

# SAS rewrites the whole signer list in one transaction, which caps a team at 30 member keys (measured on the local
# validator: 31 exceeds the 1232-byte transaction limit). Recorded in docs/BENCH.md.
MAX_SIGNERS = 30
CLAIM_RENT_SOL = 0.003  # measured: 2,797,920 lamports for a claim two folders deep (docs/BENCH.md)
FEE_BUFFER_SOL = 0.005
LAMPORTS = 1_000_000_000


def new_name() -> str:
    return "knos-" + secrets.token_hex(8)


def float_lamports(max_live_claims: int = 20) -> int:
    """The SOL float a member key needs: a refundable deposit per live claim plus a fee buffer."""
    return int((max_live_claims * CLAIM_RENT_SOL + FEE_BUFFER_SOL) * LAMPORTS)


@dataclass(frozen=True)
class OnChain:
    name: str
    credential: Pubkey
    schemas: dict[str, Pubkey]


def schema_addresses(credential: Pubkey) -> dict[str, Pubkey]:
    return {spec[0].split(".")[1]: sas.schema_pda(credential, spec[0]) for spec in schemas.ALL}


def create(url: str, owner: Keypair, signers: list[Pubkey], name: str | None = None) -> OnChain:
    """The credential, then the four schemas, all paid and signed by the owner key."""
    name = name or new_name()
    credential = sas.credential_pda(owner.pubkey(), name)
    rpc.send(url, [sas.create_credential(owner.pubkey(), owner.pubkey(), name, signers)], owner)
    ixs = [sas.create_schema(owner.pubkey(), owner.pubkey(), credential, n, d, layout, fields)
           for n, d, layout, fields in schemas.ALL]
    for i in range(0, len(ixs), 2):  # two per transaction keeps each under the 1232-byte limit
        rpc.send(url, ixs[i:i + 2], owner)
    return OnChain(name, credential, schema_addresses(credential))


def signers(url: str, credential: Pubkey) -> list[Pubkey]:
    _, raw = rpc.account_data(url, credential)
    if raw is None:
        raise LookupError("team credential not found on this cluster")
    return sas.parse_credential(raw).signers


def set_signers(url: str, owner: Keypair, credential: Pubkey, keys: list[Pubkey]) -> str:
    if len(keys) > MAX_SIGNERS:
        raise ValueError(f"a team holds at most {MAX_SIGNERS} member keys")
    return rpc.send(url, [sas.change_authorized_signers(owner.pubkey(), owner.pubkey(), credential, keys)], owner)


# ---- sealing the salt and the display name ------------------------------------------------------------------------

def _curve_pk(ed_pub: bytes) -> bytes:
    from nacl.bindings import crypto_sign_ed25519_pk_to_curve25519
    return crypto_sign_ed25519_pk_to_curve25519(ed_pub)


def _curve_sk(key: Keypair) -> bytes:
    from nacl.bindings import crypto_sign_ed25519_sk_to_curve25519
    return crypto_sign_ed25519_sk_to_curve25519(bytes(key))


def seal_salt(salt: bytes, member: Pubkey) -> bytes:
    from nacl.public import PublicKey, SealedBox
    return SealedBox(PublicKey(_curve_pk(bytes(member)))).encrypt(salt)


def open_salt(box: bytes, key: Keypair) -> bytes:
    from nacl.public import PrivateKey, SealedBox
    return SealedBox(PrivateKey(_curve_sk(key))).decrypt(box)


def _name_key(salt: bytes) -> bytes:
    return hashlib.sha256(salt + b"knos.name").digest()


def seal_name(salt: bytes, name: str) -> bytes:
    from nacl.secret import SecretBox
    return bytes(SecretBox(_name_key(salt)).encrypt(name.encode("utf-8")))


def open_name(salt: bytes, box: bytes) -> str:
    from nacl.secret import SecretBox
    return SecretBox(_name_key(salt)).decrypt(box).decode("utf-8", "replace")


def add_member_attestation(url: str, owner: Keypair, credential: Pubkey, member: Pubkey, display: str,
                           salt: bytes) -> str:
    """Written by the owner, who must itself be a signer of the credential."""
    schema = sas.schema_pda(credential, schemas.MEMBER[0])
    data = schemas.MemberData(seal_name(salt, display), seal_salt(salt, member)).encode()
    return rpc.send(url, [sas.create_attestation(owner.pubkey(), owner.pubkey(), credential, schema, member, data)],
                    owner)


def members(url: str, credential: Pubkey, salt: bytes | None = None) -> dict[str, dict]:
    """member public key -> {"name": display name if the salt is known, "address": attestation address}."""
    from .protocol import _attestations
    schema = sas.schema_pda(credential, schemas.MEMBER[0])
    _, found = _attestations(url, credential, schema)
    out = {}
    for addr, att in found:
        try:
            md = schemas.MemberData.decode(att.data)
            name = open_name(salt, md.name_box) if salt else ""
        except Exception:  # noqa: BLE001 - a malformed or foreign member record is skipped, not fatal
            continue
        out[str(att.nonce)] = {"name": name, "address": str(addr), "signer": str(att.signer)}
    return out


def names(url: str, credential: Pubkey, salt: bytes, timeout: float = 5.0) -> dict[str, str]:
    """member public key -> display name, by address (the credential's signers, then their member records in one
    getMultipleAccounts): no scan of the program."""
    import base64
    keys = signers(url, credential)
    schema = sas.schema_pda(credential, schemas.MEMBER[0])
    addrs = [str(sas.attestation_pda(credential, schema, k)) for k in keys]
    got = rpc.call(url, "getMultipleAccounts", [addrs, {"encoding": "base64", "commitment": "confirmed"}], timeout)
    out = {}
    for k, item in zip(keys, got["value"]):
        if not item:
            continue
        try:
            md = schemas.MemberData.decode(sas.parse_attestation(base64.b64decode(item["data"][0])).data)
            out[str(k)] = open_name(salt, md.name_box)
        except Exception:  # noqa: BLE001 - a record this salt cannot open is skipped
            continue
    return out


def my_salt(url: str, credential: Pubkey, key: Keypair) -> bytes | None:
    """This member's copy of the team salt, from its own member attestation."""
    schema = sas.schema_pda(credential, schemas.MEMBER[0])
    _, raw = rpc.account_data(url, sas.attestation_pda(credential, schema, key.pubkey()))
    if raw is None:
        return None
    return open_salt(schemas.MemberData.decode(sas.parse_attestation(raw).data).salt_box, key)
