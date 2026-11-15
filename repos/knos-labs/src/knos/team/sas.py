"""Solana Attestation Service and Lighthouse instructions, built with `solders`.

There is no Python SDK for SAS. Every layout here was read from the program source
(github.com/solana-foundation/solana-attestation-service, program/src) and is checked two ways: byte for byte in
tests/test_sas.py, and by live calls to the devnet-deployed program cloned into a local validator
(scripts/devchain.sh). Where the two ever disagree, the deployed program wins.

Instruction data is a one-byte discriminator, then the arguments: strings and byte arrays are u32 little-endian
length-prefixed, vectors are a u32 count then the items. Accounts are the program's own byte layout behind a
one-byte discriminator (Credential 0, Schema 1, Attestation 2).

Lighthouse (github.com/Jac0xb/lighthouse) makes a close compare-then-close: an `AssertAccountData` on the exact bytes
the closer expects, in the same transaction as `CloseAttestation`. If anyone changed or re-created the attestation in
between, the assertion fails and nothing is closed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

PROGRAM_ID = Pubkey.from_string("22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG")
LIGHTHOUSE_ID = Pubkey.from_string("L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95")
SYSTEM_PROGRAM = Pubkey.from_string("11111111111111111111111111111111")

# Instruction discriminators (program/src/entrypoint.rs)
IX_CREATE_CREDENTIAL = 0
IX_CREATE_SCHEMA = 1
IX_CHANGE_AUTHORIZED_SIGNERS = 3
IX_CREATE_ATTESTATION = 6
IX_CLOSE_ATTESTATION = 7

# Account discriminators (program/src/state/discriminator.rs)
CREDENTIAL = 0
SCHEMA = 1
ATTESTATION = 2

# Schema field types Knos uses (program/src/state/schema.rs, SchemaDataTypes, by their numbers there). There is no
# fixed-size byte type, so a 32-byte hash is a VecU8.
U8, U32, U64, I64, VEC_U8 = 0, 2, 3, 8, 13

# Lighthouse: the borsh variant index of AssertAccountData (programs/lighthouse/src/instruction.rs), log level Silent,
# DataValueAssertion::Bytes and EquatableOperator::Equal.
_LH_ASSERT_ACCOUNT_DATA = 2
_LH_SILENT = 0
_LH_BYTES = 11
_LH_EQUAL = 0


def _u32(n: int) -> bytes:
    return struct.pack("<I", n)


def _bytes(b: bytes) -> bytes:
    return _u32(len(b)) + b


def _pubkeys(keys: list[Pubkey]) -> bytes:
    return _u32(len(keys)) + b"".join(bytes(k) for k in keys)


def leb128(n: int) -> bytes:
    """Unsigned LEB128, as Lighthouse's CompactU64 and LEB128Vec lengths are written."""
    if n < 0:
        raise ValueError("leb128 is unsigned")
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


# ---- PDAs -------------------------------------------------------------------------------------------------------

def credential_pda(authority: Pubkey, name: str) -> Pubkey:
    return Pubkey.find_program_address([b"credential", bytes(authority), name.encode()], PROGRAM_ID)[0]


def schema_pda(credential: Pubkey, name: str, version: int = 1) -> Pubkey:
    return Pubkey.find_program_address([b"schema", bytes(credential), name.encode(), bytes([version])], PROGRAM_ID)[0]


def attestation_pda(credential: Pubkey, schema: Pubkey, nonce: Pubkey) -> Pubkey:
    return Pubkey.find_program_address([b"attestation", bytes(credential), bytes(schema), bytes(nonce)],
                                       PROGRAM_ID)[0]


def event_authority() -> Pubkey:
    return Pubkey.find_program_address([b"__event_authority"], PROGRAM_ID)[0]


# ---- instructions -----------------------------------------------------------------------------------------------

def _ix(accounts: list[tuple[Pubkey, bool, bool]], data: bytes, program: Pubkey = PROGRAM_ID) -> Instruction:
    return Instruction(program, data, [AccountMeta(k, is_signer=s, is_writable=w) for k, s, w in accounts])


def create_credential(payer: Pubkey, authority: Pubkey, name: str, signers: list[Pubkey]) -> Instruction:
    data = bytes([IX_CREATE_CREDENTIAL]) + _bytes(name.encode()) + _pubkeys(signers)
    return _ix([(payer, True, True), (credential_pda(authority, name), False, True), (authority, True, False),
                (SYSTEM_PROGRAM, False, False)], data)


def create_schema(payer: Pubkey, authority: Pubkey, credential: Pubkey, name: str, description: str,
                  layout: list[int], field_names: list[str]) -> Instruction:
    if len(layout) != len(field_names):
        raise ValueError("one field name per layout entry")
    data = (bytes([IX_CREATE_SCHEMA]) + _bytes(name.encode()) + _bytes(description.encode()) + _bytes(bytes(layout))
            + _u32(len(field_names)) + b"".join(_bytes(f.encode()) for f in field_names))
    return _ix([(payer, True, True), (authority, True, False), (credential, False, False),
                (schema_pda(credential, name), False, True), (SYSTEM_PROGRAM, False, False)], data)


def change_authorized_signers(payer: Pubkey, authority: Pubkey, credential: Pubkey,
                              signers: list[Pubkey]) -> Instruction:
    """Rewrites the whole signer list; the credential account is resized, the payer covers any extra rent."""
    data = bytes([IX_CHANGE_AUTHORIZED_SIGNERS]) + _pubkeys(signers)
    return _ix([(payer, True, True), (authority, True, False), (credential, False, True),
                (SYSTEM_PROGRAM, False, False)], data)


def create_attestation(payer: Pubkey, signer: Pubkey, credential: Pubkey, schema: Pubkey, nonce: Pubkey,
                       data: bytes, expiry: int = 0) -> Instruction:
    """Fails if the attestation PDA already exists, which is what makes a claim a mutex. `expiry` 0 = never."""
    body = bytes([IX_CREATE_ATTESTATION]) + bytes(nonce) + _bytes(data) + struct.pack("<q", expiry)
    return _ix([(payer, True, True), (signer, True, False), (credential, False, False), (schema, False, False),
                (attestation_pda(credential, schema, nonce), False, True), (SYSTEM_PROGRAM, False, False)], body)


def close_attestation(refund_to: Pubkey, signer: Pubkey, credential: Pubkey, attestation: Pubkey) -> Instruction:
    """Any authorized signer of the credential may close any of its attestations. The rent goes to `refund_to`,
    which does not have to sign (program/src/processor/close_attestation.rs)."""
    data = bytes([IX_CLOSE_ATTESTATION])
    return _ix([(refund_to, False, True), (signer, True, False), (credential, False, False),
                (attestation, False, True), (event_authority(), False, False), (SYSTEM_PROGRAM, False, False),
                (PROGRAM_ID, False, False)], data)


def assert_account_bytes(target: Pubkey, offset: int, expected: bytes) -> Instruction:
    """Lighthouse AssertAccountData: `target.data[offset:offset+len(expected)] == expected`, or the transaction fails."""
    data = (bytes([_LH_ASSERT_ACCOUNT_DATA, _LH_SILENT]) + leb128(offset)
            + bytes([_LH_BYTES]) + leb128(len(expected)) + expected + bytes([_LH_EQUAL]))
    return _ix([(target, False, False)], data, program=LIGHTHOUSE_ID)


# ---- accounts ---------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Credential:
    authority: Pubkey
    name: str
    signers: list[Pubkey]


@dataclass(frozen=True)
class Attestation:
    nonce: Pubkey
    credential: Pubkey
    schema: Pubkey
    data: bytes
    signer: Pubkey
    expiry: int
    token_account: Pubkey

    def to_bytes(self) -> bytes:
        """The account exactly as the program writes it (state/attestation.rs, to_bytes)."""
        return (bytes([ATTESTATION]) + bytes(self.nonce) + bytes(self.credential) + bytes(self.schema)
                + _bytes(self.data) + bytes(self.signer) + struct.pack("<q", self.expiry) + bytes(self.token_account))


def _pk(raw: bytes, at: int) -> Pubkey:
    return Pubkey.from_bytes(raw[at:at + 32])


def parse_credential(raw: bytes) -> Credential:
    if not raw or raw[0] != CREDENTIAL:
        raise ValueError("not a SAS credential")
    at = 33
    (n,) = struct.unpack_from("<I", raw, at)
    name = raw[at + 4:at + 4 + n].decode()
    at += 4 + n
    (count,) = struct.unpack_from("<I", raw, at)
    at += 4
    return Credential(_pk(raw, 1), name, [_pk(raw, at + 32 * i) for i in range(count)])


def parse_attestation(raw: bytes) -> Attestation:
    if not raw or raw[0] != ATTESTATION:
        raise ValueError("not a SAS attestation")
    at = 97
    (n,) = struct.unpack_from("<I", raw, at)
    data = bytes(raw[at + 4:at + 4 + n])
    at += 4 + n
    (expiry,) = struct.unpack_from("<q", raw, at + 32)
    return Attestation(_pk(raw, 1), _pk(raw, 33), _pk(raw, 65), data, _pk(raw, at), expiry, _pk(raw, at + 40))


def compare_close(refund_to: Pubkey, closer: Pubkey, expected: Attestation, address: Pubkey) -> list[Instruction]:
    """Close `address` only if it still holds exactly `expected`: the Lighthouse assertion covers every byte after
    the discriminator (nonce, credential, schema, data, signer, expiry, token account)."""
    return [assert_account_bytes(address, 1, expected.to_bytes()[1:]),
            close_attestation(refund_to, closer, expected.credential, address)]
