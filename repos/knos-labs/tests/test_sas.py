"""SAS and Lighthouse builders: byte for byte against the program source, then live against the devnet-deployed
programs cloned into a local validator (scripts/devchain.sh start). The live half skips when no validator is up."""

from __future__ import annotations

import os
import struct

import pytest

from knos.team import rpc, sas
from solders.keypair import Keypair
from solders.pubkey import Pubkey

K = [Pubkey.from_bytes(bytes([i]) * 32) for i in range(1, 8)]


def test_program_ids_and_event_authority():
    assert str(sas.PROGRAM_ID) == "22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG"
    assert str(sas.LIGHTHOUSE_ID) == "L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95"
    # The "__event_authority" PDA as the SAS IDL publishes it.
    assert str(sas.event_authority()) == "DzSpKpST2TSyrxokMXchFz3G2yn5WEGoxzpGEUDjCX4g"


def test_create_credential_bytes():
    ix = sas.create_credential(K[0], K[1], "knos-00ff", [K[2], K[3]])
    assert ix.data == (b"\x00" + b"\x09\x00\x00\x00" + b"knos-00ff" + b"\x02\x00\x00\x00"
                       + bytes([3]) * 32 + bytes([4]) * 32)
    pda = Pubkey.find_program_address([b"credential", bytes(K[1]), b"knos-00ff"], sas.PROGRAM_ID)[0]
    metas = [(m.pubkey, m.is_signer, m.is_writable) for m in ix.accounts]
    assert metas == [(K[0], True, True), (pda, False, True), (K[1], True, False), (sas.SYSTEM_PROGRAM, False, False)]


def test_create_schema_bytes():
    ix = sas.create_schema(K[0], K[1], K[2], "knos.claim.v1", "d", [sas.VEC_U8, sas.I64], ["h", "lease"])
    assert ix.data == (b"\x01" + b"\x0d\x00\x00\x00knos.claim.v1" + b"\x01\x00\x00\x00d" + b"\x02\x00\x00\x00\x0d\x08"
                       + b"\x02\x00\x00\x00" + b"\x01\x00\x00\x00h" + b"\x05\x00\x00\x00lease")
    pda = Pubkey.find_program_address([b"schema", bytes(K[2]), b"knos.claim.v1", b"\x01"], sas.PROGRAM_ID)[0]
    assert [m.pubkey for m in ix.accounts] == [K[0], K[1], K[2], pda, sas.SYSTEM_PROGRAM]
    assert [m.is_signer for m in ix.accounts] == [True, True, False, False, False]
    assert [m.is_writable for m in ix.accounts] == [True, False, False, True, False]
    with pytest.raises(ValueError):
        sas.create_schema(K[0], K[1], K[2], "s", "", [sas.U8], [])


def test_create_attestation_bytes():
    ix = sas.create_attestation(K[0], K[1], K[2], K[3], K[4], b"\xaa\xbb", expiry=-2)
    assert ix.data.hex() == "06" + "05" * 32 + "02000000" + "aabb" + "feffffffffffffff"
    pda = Pubkey.find_program_address([b"attestation", bytes(K[2]), bytes(K[3]), bytes(K[4])], sas.PROGRAM_ID)[0]
    assert [(m.pubkey, m.is_signer, m.is_writable) for m in ix.accounts] == [
        (K[0], True, True), (K[1], True, False), (K[2], False, False), (K[3], False, False), (pda, False, True),
        (sas.SYSTEM_PROGRAM, False, False)]


def test_close_attestation_accounts():
    ix = sas.close_attestation(K[0], K[1], K[2], K[3])
    assert ix.data == b"\x07"
    assert [(m.pubkey, m.is_signer, m.is_writable) for m in ix.accounts] == [
        (K[0], False, True), (K[1], True, False), (K[2], False, False), (K[3], False, True),
        (sas.event_authority(), False, False), (sas.SYSTEM_PROGRAM, False, False), (sas.PROGRAM_ID, False, False)]


def test_change_authorized_signers_bytes():
    ix = sas.change_authorized_signers(K[0], K[1], K[2], [K[3]])
    assert ix.data == b"\x03\x01\x00\x00\x00" + bytes([4]) * 32
    assert [m.is_writable for m in ix.accounts] == [True, False, True, False]


def test_lighthouse_assert_bytes():
    ix = sas.assert_account_bytes(K[0], 1, b"\x01\x02")
    # AssertAccountData(2), LogLevel::Silent(0), offset LEB128(1), DataValueAssertion::Bytes(11), len LEB128(2),
    # bytes, EquatableOperator::Equal(0)
    assert ix.data == bytes([2, 0, 1, 11, 2, 1, 2, 0])
    assert ix.program_id == sas.LIGHTHOUSE_ID
    assert [(m.pubkey, m.is_signer, m.is_writable) for m in ix.accounts] == [(K[0], False, False)]
    assert sas.leb128(0) == b"\x00" and sas.leb128(127) == b"\x7f" and sas.leb128(300) == b"\xac\x02"


def test_account_round_trip():
    a = sas.Attestation(K[0], K[1], K[2], b"xyz", K[3], 7, Pubkey.default())
    raw = a.to_bytes()
    assert raw[0] == 2 and raw[33:65] == bytes(K[1]) and raw[65:97] == bytes(K[2])
    assert sas.parse_attestation(raw) == a
    cred = b"\x00" + bytes(K[0]) + struct.pack("<I", 4) + b"team" + struct.pack("<I", 2) + bytes(K[1]) + bytes(K[2])
    assert cred[37:41] == b"team"  # the name starts at byte offset 37
    assert sas.parse_credential(cred) == sas.Credential(K[0], "team", [K[1], K[2]])
    with pytest.raises(ValueError):
        sas.parse_attestation(cred)


# ---- live, against the devnet-deployed programs on a local validator --------------------------------------------

URL = os.environ.get("KNOS_DEVCHAIN_URL", "http://127.0.0.1:8899")


def _up() -> bool:
    try:
        return rpc.call(URL, "getHealth", [], timeout=2) == "ok"
    except Exception:
        return False


def devchain(fn):
    return pytest.mark.chain(pytest.mark.skipif(not _up(), reason="no local validator: scripts/devchain.sh start")(fn))

CLAIM_LAYOUT = [sas.VEC_U8, sas.VEC_U8, sas.VEC_U8, sas.I64, sas.U8]
CLAIM_FIELDS = ["unit_hash", "ancestors", "holder_hash", "lease_until", "kind"]


def _claim_data(unit: bytes, holder: bytes, lease: int) -> bytes:
    vec = lambda b: struct.pack("<I", len(b)) + b  # noqa: E731
    return vec(unit) + vec(b"") + vec(holder) + struct.pack("<q", lease) + b"\x00"


@pytest.fixture(scope="module")
def team():
    owner, s1, s2 = Keypair(), Keypair(), Keypair()
    for k in (owner, s1, s2):
        rpc.airdrop(URL, k.pubkey(), 2_000_000_000)
    name = "knos-" + os.urandom(8).hex()
    rpc.send(URL, [sas.create_credential(owner.pubkey(), owner.pubkey(), name, [s1.pubkey(), s2.pubkey()])], owner)
    cred = sas.credential_pda(owner.pubkey(), name)
    rpc.send(URL, [sas.create_schema(owner.pubkey(), owner.pubkey(), cred, "knos.claim.v1", "a Knos claim",
                                     CLAIM_LAYOUT, CLAIM_FIELDS)], owner)
    return owner, s1, s2, cred, sas.schema_pda(cred, "knos.claim.v1")


@devchain
def test_live_credential_and_schema(team):
    owner, s1, s2, cred, schema = team
    _, raw = rpc.account_data(URL, cred)
    got = sas.parse_credential(raw)
    assert got.authority == owner.pubkey() and got.signers == [s1.pubkey(), s2.pubkey()]
    assert got.name.startswith("knos-")
    _, raw = rpc.account_data(URL, schema)
    assert raw[0] == sas.SCHEMA and raw[1:33] == bytes(cred)


@devchain
def test_live_claim_is_a_mutex_and_compare_close_refunds_the_signer(team):
    owner, s1, s2, cred, schema = team
    nonce = Pubkey.from_bytes(os.urandom(32))
    data = _claim_data(bytes(nonce), b"h" * 32, 1_900_000_000)
    rpc.send(URL, [sas.create_attestation(s1.pubkey(), s1.pubkey(), cred, schema, nonce, data)], s1)
    addr = sas.attestation_pda(cred, schema, nonce)
    slot, raw = rpc.account_data(URL, addr)
    att = sas.parse_attestation(raw)
    assert att == sas.Attestation(nonce, cred, schema, data, s1.pubkey(), 0, Pubkey.default())
    assert att.to_bytes() == raw  # our layout is the deployed program's layout, byte for byte

    # A second create of the same PDA fails, whoever tries it: the on-chain mutex.
    with pytest.raises(rpc.RpcError):
        rpc.send(URL, [sas.create_attestation(s2.pubkey(), s2.pubkey(), cred, schema, nonce, data)], s2)

    # A compare-close with the wrong expectation fails and closes nothing.
    wrong = sas.Attestation(nonce, cred, schema, _claim_data(bytes(nonce), b"x" * 32, 1_900_000_000), s1.pubkey(), 0,
                            Pubkey.default())
    with pytest.raises(rpc.RpcError):
        rpc.send(URL, sas.compare_close(s1.pubkey(), s2.pubkey(), wrong, addr), s2)
    assert rpc.account_data(URL, addr)[1] is not None

    # Any authorized signer may close; the rent goes to the attestation's signer, who does not sign.
    before = rpc.balance(URL, s1.pubkey())
    rent = rpc.call(URL, "getBalance", [str(addr), {"commitment": "confirmed"}])["value"]
    rpc.send(URL, sas.compare_close(s1.pubkey(), s2.pubkey(), att, addr), s2)
    assert rpc.account_data(URL, addr)[1] is None
    assert rpc.balance(URL, s1.pubkey()) == before + rent

    # After a close the PDA can be created again.
    rpc.send(URL, [sas.create_attestation(s2.pubkey(), s2.pubkey(), cred, schema, nonce, data)], s2)
    assert sas.parse_attestation(rpc.account_data(URL, addr)[1]).signer == s2.pubkey()


@devchain
def test_live_dust_on_the_pda_does_not_block_the_claim(team):
    owner, s1, s2, cred, schema = team
    nonce = Pubkey.from_bytes(os.urandom(32))
    addr = sas.attestation_pda(cred, schema, nonce)
    from solders.system_program import TransferParams, transfer
    rpc.send(URL, [transfer(TransferParams(from_pubkey=owner.pubkey(), to_pubkey=addr, lamports=1_000_000))], owner)
    rpc.send(URL, [sas.create_attestation(s1.pubkey(), s1.pubkey(), cred, schema, nonce,
                                          _claim_data(bytes(nonce), b"h" * 32, 0))], s1)
    assert sas.parse_attestation(rpc.account_data(URL, addr)[1]).signer == s1.pubkey()


@devchain
def test_live_only_authorized_signers_and_the_authority_can_act(team):
    owner, s1, s2, cred, schema = team
    outsider = Keypair()
    rpc.airdrop(URL, outsider.pubkey(), 1_000_000_000)
    nonce = Pubkey.from_bytes(os.urandom(32))
    data = _claim_data(bytes(nonce), b"o" * 32, 0)
    with pytest.raises(rpc.RpcError):
        rpc.send(URL, [sas.create_attestation(outsider.pubkey(), outsider.pubkey(), cred, schema, nonce, data)],
                 outsider)
    with pytest.raises(rpc.RpcError):  # only the credential's authority may change the signers
        rpc.send(URL, [sas.change_authorized_signers(s1.pubkey(), s1.pubkey(), cred, [s1.pubkey()])], s1)
    rpc.send(URL, [sas.change_authorized_signers(owner.pubkey(), owner.pubkey(), cred,
                                                 [s1.pubkey(), s2.pubkey(), outsider.pubkey()])], owner)
    rpc.send(URL, [sas.create_attestation(outsider.pubkey(), outsider.pubkey(), cred, schema, nonce, data)], outsider)
    rpc.send(URL, [sas.change_authorized_signers(owner.pubkey(), owner.pubkey(), cred,
                                                 [s1.pubkey(), s2.pubkey()])], owner)
    with pytest.raises(rpc.RpcError):  # removed: can no longer close
        rpc.send(URL, [sas.close_attestation(outsider.pubkey(), outsider.pubkey(), cred,
                                             sas.attestation_pda(cred, schema, nonce))], outsider)
