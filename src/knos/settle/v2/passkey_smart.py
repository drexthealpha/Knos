"""A passkey that can sign ANY instruction for its owner: a LazorKit smart wallet on Solana (open source, MIT,
github.com/lazor-kit/program-v2), driven from Python with no SDK.

Why not knos_passkey here. knos_passkey (programs-v2/knos_passkey) lets a passkey sign exactly two things: a token
Withdraw, and one FundOrderWallet of the knos_pay it pins (5y7iWJ1V..., the public program). Knos's pre-orders run as
PANEL orders on the knos_pay panel test build (devnet FaMHCjzy...), and a maker who factors a receivable must sign
knos_pay's Assign or hand the wallet the receivable is paid to to a lender. knos_passkey can sign neither. A LazorKit
wallet can: its vault PDA signs any CPI the passkey approved (Execute), and its owner can be handed to another passkey
(TransferOwnership). Both are checked by Solana's secp256r1 precompile (SIMD-0075) over a WebAuthn assertion.

The deployed program this file speaks to: devnet FLb7fyAtkfA4TSa2uYcAT8QKHd2pkoMHgmqfnXFXo7ao, last deployed
2026-04-13 21:04 UTC (slot 455340549), which is lazor-kit/program-v2 at commit b61e94a (the commit made two minutes
before; its tree is the first with RevokeSession, whose code is in the deployed binary). Its executable is in
tests/thirdparty/lazorkit_devnet_FLb7.so (dumped from devnet) so the tests run these exact bytes.

HOW A LAZORKIT ASSERTION IS BUILT (program/src/auth/secp256r1/mod.rs at b61e94a):
  auth_payload  = slot u64 LE || counter u32 LE || sysvar_ix_index u8 || type_and_flags u8 || authenticatorData
  challenge     = sha256(discriminator u8 || auth_payload || signed_payload || slot u64 LE || payer || counter u32 LE || program id)
  clientDataJSON is NOT carried: the program rebuilds it as
                  {"type":"webauthn.get","challenge":"<b64url>","origin":"https://<rpId>","crossOrigin":false}
                  (type_and_flags 0x10; 0x01 crossOrigin true, 0x02 http://, 0x04 Chrome's "other_keys_can_be_added_here")
  the precompile instruction is the one right before, one signature, offsets 16/80/114, message
                  authenticatorData || sha256(clientDataJSON)
  counter       the authority's odometer plus one; slot within 150 slots (about a minute) of the chain's.
Because authenticatorData is inside the challenge, it must be known before the passkey signs: rpIdHash, the flags and
the authenticator's sign count. `predicted_auth_data` uses the flags the passkey showed at its last use (or at its
creation) and its next sign count; when an authenticator answers otherwise, `finish` raises Mismatch with what it
did answer and the caller prepares again with that (one more touch of the passkey). Synced passkeys (iCloud, Google)
keep the count at 0, so the second assertion always matches.

  Execute (4)          payer(s,w) wallet authority(w) vault, then every account the inner instructions name
                       signed_payload = the compact instructions || sha256(the keys they reference, in order)
  TransferOwnership (3) payer(s,w) wallet current(w) new(w) system rent, then the instructions sysvar
                       signed_payload = new type || new authority data || payer; the current owner's account is closed
  CreateWallet (0)     payer(s,w) wallet(w) vault authority(w) system rent: anyone, for any key (no signature)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, field

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from .passkey import b64url, compressed, raw_signature

LAZOR_ID = Pubkey.from_string(os.environ.get("KNOS_LAZORKIT_PROGRAM") or "FLb7fyAtkfA4TSa2uYcAT8QKHd2pkoMHgmqfnXFXo7ao")
LAZOR_COMMIT = "b61e94a"
SECP256R1 = Pubkey.from_string("Secp256r1SigVerify1111111111111111111111111")
INSTRUCTIONS = Pubkey.from_string("Sysvar1nstructions1111111111111111111111111")
RENT = Pubkey.from_string("SysvarRent111111111111111111111111111111111")
SYSTEM = Pubkey.from_string("11111111111111111111111111111111")

CREATE_WALLET, TRANSFER_OWNERSHIP, EXECUTE = 0, 3, 4
TYPE_GET, CROSS_ORIGIN, HTTP_ORIGIN, GOOGLE_EXTRA = 0x10, 0x01, 0x02, 0x04
UP, UV, BE, BS = 0x01, 0x04, 0x08, 0x10
MAX_SLOT_AGE = 150
HEADER = 48                        # an Authority account's header (state/authority.rs)
D_WALLET, D_AUTHORITY, D_SESSION, D_DEFERRED = 1, 2, 3, 4
WALLET_AT = {D_AUTHORITY: 16, D_SESSION: 8, D_DEFERRED: 72}     # where each account kind names its wallet
GOOGLE_TEXT = ',"other_keys_can_be_added_here":"do not compare clientDataJSON against a template. See https://goo.gl/yabPex"'
ERRORS = {3001: "the authority payload is malformed", 3002: "permission denied (no person present, or called by another program)",
          3003: "the secp256r1 instruction is missing or not the one right before", 3004: "another key, or another site (rpId)",
          3005: "what the passkey signed is not this transaction", 3006: "this assertion was used already (odometer)",
          3007: "the assertion is too old (more than 150 slots): sign again", 3011: "unknown authority type",
          3013: "a wallet cannot call LazorKit itself"}


class Mismatch(ValueError):
    """The authenticator answered with other authenticatorData (flags, count) or client data than predicted: prepare
    again with `flags`, `sign_count` and `type_flags` learned from this answer."""
    def __init__(self, why: str, flags: int, sign_count: int, type_flags: int):
        super().__init__(why)
        self.flags, self.sign_count, self.type_flags = flags, sign_count, type_flags


def _pda(seeds, program: Pubkey = LAZOR_ID) -> tuple[Pubkey, int]:
    return Pubkey.find_program_address(seeds, program)


def cred_hash(credential_id: bytes) -> bytes:
    """sha256 of the WebAuthn credential id (raw bytes): the authority's id seed."""
    return hashlib.sha256(bytes(credential_id)).digest()


def user_seed(purpose: str, credential_hash: bytes, extra: bytes = b"") -> bytes:
    """A wallet's seed: Knos's main wallet of a passkey ("main"), or one wallet per receivable ("receivable", claim id)."""
    return hashlib.sha256(b"knos:lazorkit:" + purpose.encode() + b":" + credential_hash + extra).digest()


def wallet_pda(seed: bytes, program: Pubkey = LAZOR_ID) -> Pubkey:
    return _pda([b"wallet", seed], program)[0]


def vault_pda(wallet: Pubkey, program: Pubkey = LAZOR_ID) -> Pubkey:
    return _pda([b"vault", bytes(wallet)], program)[0]


def authority_pda(wallet: Pubkey, credential_hash: bytes, program: Pubkey = LAZOR_ID) -> tuple[Pubkey, int]:
    return _pda([b"authority", bytes(wallet), credential_hash], program)


def auth_blob(credential_hash: bytes, key: bytes, rp_id: str) -> bytes:
    rp = rp_id.encode()
    if not 0 < len(rp) < 256:
        raise ValueError("rp_id: 1 to 255 bytes")
    return credential_hash + compressed(key) + bytes([len(rp)]) + rp


def create_wallet_ix(payer: Pubkey, seed: bytes, credential_hash: bytes, key: bytes, rp_id: str, program: Pubkey = LAZOR_ID) -> Instruction:
    """A LazorKit wallet whose one owner is this passkey (anyone may create it; no signature of the passkey)."""
    w = wallet_pda(seed, program)
    a, bump = authority_pda(w, credential_hash, program)
    data = bytes([CREATE_WALLET]) + seed + bytes([1, bump]) + bytes(6) + auth_blob(credential_hash, key, rp_id)
    return Instruction(program, data, [AccountMeta(payer, True, True), AccountMeta(w, False, True), AccountMeta(vault_pda(w, program), False, True),
                                       AccountMeta(a, False, True), AccountMeta(SYSTEM, False, False), AccountMeta(RENT, False, False)])


@dataclass(frozen=True)
class Authority:
    kind: int          # 0 Ed25519, 1 Secp256r1
    role: int          # 0 Owner, 1 Admin, 2 Spender
    counter: int
    wallet: Pubkey
    credential_hash: bytes
    key: bytes
    rp_id: str


def read_authority(data: bytes | None) -> Authority | None:
    if not data or len(data) < HEADER + 66 or data[0] != D_AUTHORITY or data[1] != 1:
        return None
    n = data[HEADER + 65]
    return Authority(data[1], data[2], int.from_bytes(data[8:12], "little"), Pubkey.from_bytes(data[16:48]),
                     bytes(data[HEADER:HEADER + 32]), bytes(data[HEADER + 32:HEADER + 65]), data[HEADER + 66:HEADER + 66 + n].decode())


def predicted_auth_data(rp_id: str, flags: int = UP | UV, sign_count: int = 0) -> bytes:
    """authenticatorData as the passkey will return it: sha256(rpId) || flags || sign count (big-endian). Extension
    data (ED) and attested credential data (AT) never appear in an assertion Knos asks for."""
    return hashlib.sha256(rp_id.encode()).digest() + bytes([flags & 0x3F]) + int(sign_count).to_bytes(4, "big")


def next_count(last: int) -> int:
    """The sign count an authenticator returns next: 0 stays 0 (synced passkeys), else one more."""
    return 0 if not last else last + 1


def client_data_json(type_flags: int, rp_id: str, challenge: bytes) -> bytes:
    """The clientDataJSON the program rebuilds (webauthn.rs reconstruct_client_data_json)."""
    t = "webauthn.get" if type_flags & 0xF0 == TYPE_GET else "webauthn.create"
    s = (f'{{"type":"{t}","challenge":"{b64url(challenge)}","origin":"{"http" if type_flags & HTTP_ORIGIN else "https"}://{rp_id}",'
         f'"crossOrigin":{"true" if type_flags & CROSS_ORIGIN else "false"}' + (GOOGLE_TEXT if type_flags & GOOGLE_EXTRA else "") + "}")
    return s.encode()


def type_flags_of(client_data: bytes) -> int | None:
    """The type_and_flags under which the program rebuilds exactly these bytes, or None (another layout: a browser that
    adds other keys, an origin with a port)."""
    try:
        d = json.loads(client_data)
        origin = d["origin"]
    except (ValueError, KeyError, TypeError):
        return None
    f = TYPE_GET if d.get("type") == "webauthn.get" else 0
    f |= CROSS_ORIGIN if d.get("crossOrigin") else 0
    f |= HTTP_ORIGIN if str(origin).startswith("http://") else 0
    f |= GOOGLE_EXTRA if "other_keys_can_be_added_here" in d else 0
    rp = str(origin).split("://", 1)[-1]
    try:
        ch = base64.urlsafe_b64decode(d["challenge"] + "=" * (-len(d["challenge"]) % 4))
    except (ValueError, TypeError, KeyError):
        return None
    return f if client_data_json(f, rp, ch) == bytes(client_data) else None


def secp256r1_ix(key: bytes, signature: bytes, message: bytes) -> Instruction:
    """The precompile instruction in the layout LazorKit reads (introspection.rs): one signature, its data in this
    instruction (index 0xFFFF), signature at 16, the 33-byte key at 80, one byte of padding, the message at 114."""
    head = bytes([1, 0]) + b"".join(v.to_bytes(2, "little") for v in (16, 0xFFFF, 80, 0xFFFF, 114, len(message), 0xFFFF))
    return Instruction(SECP256R1, head + raw_signature(signature) + compressed(key) + b"\x00" + bytes(message), [])


@dataclass
class Prepared:
    """One LazorKit instruction waiting for its passkey assertion. `challenge` is what navigator.credentials.get signs."""
    discriminator: int
    program: Pubkey
    payer: Pubkey
    accounts: list[AccountMeta]
    data_payload: bytes            # the instruction data between the discriminator and the auth payload
    signed_payload: bytes          # what the challenge hashes in its third place
    slot: int
    counter: int
    sysvar_index: int
    rp_id: str
    key: bytes
    flags: int = UP | UV
    sign_count: int = 0
    type_flags: int = TYPE_GET
    pre: list = field(default_factory=list)        # instructions the relayer sends first in the same transaction

    @property
    def auth_data(self) -> bytes:
        return predicted_auth_data(self.rp_id, self.flags, self.sign_count)

    @property
    def auth_payload(self) -> bytes:
        return (self.slot.to_bytes(8, "little") + self.counter.to_bytes(4, "little") + bytes([self.sysvar_index, self.type_flags])
                + self.auth_data)

    @property
    def challenge(self) -> bytes:
        return hashlib.sha256(bytes([self.discriminator]) + self.auth_payload + self.signed_payload + self.slot.to_bytes(8, "little")
                              + bytes(self.payer) + self.counter.to_bytes(4, "little") + bytes(self.program)).digest()

    def parts(self) -> dict:
        """What a browser needs to recompute the challenge itself before it lets the passkey sign it."""
        return {"discriminator": self.discriminator, "auth_payload": self.auth_payload.hex(), "signed_payload": self.signed_payload.hex(),
                "slot": self.slot, "payer": str(self.payer), "counter": self.counter, "program": str(self.program),
                "accounts": [str(a.pubkey) for a in self.accounts], "challenge": self.challenge.hex()}

    def finish(self, authenticator_data: bytes, client_data: bytes, signature: bytes) -> list[Instruction]:
        """[secp256r1 precompile, the LazorKit instruction] for this assertion; Mismatch when the authenticator answered
        otherwise than predicted (prepare again with what it answered)."""
        authenticator_data, client_data = bytes(authenticator_data), bytes(client_data)
        tf = type_flags_of(client_data)
        flags = authenticator_data[32] if len(authenticator_data) >= 37 else self.flags
        count = int.from_bytes(authenticator_data[33:37], "big") if len(authenticator_data) >= 37 else self.sign_count
        if authenticator_data != self.auth_data or tf != self.type_flags:
            if len(authenticator_data) != 37 or tf is None:
                raise ValueError("this passkey's answer cannot be checked by the wallet program (extension data, or a page origin "
                                 "with a port): sign on the site's own https origin")
            raise Mismatch("the passkey answered with other flags or count than predicted: sign once more", flags, next_count(count), tf)
        if client_data != client_data_json(self.type_flags, self.rp_id, self.challenge):
            raise ValueError("the passkey signed another challenge than this transaction's")
        msg = authenticator_data + hashlib.sha256(client_data).digest()
        ix = Instruction(self.program, bytes([self.discriminator]) + self.data_payload + self.auth_payload, self.accounts)
        return [*self.pre, secp256r1_ix(self.key, signature, msg), ix]


def _compact(accounts: list[AccountMeta], inner: list[Instruction]) -> tuple[bytes, bytes]:
    at = {a.pubkey: i for i, a in enumerate(accounts)}
    out, keys = [bytes([len(inner)])], []
    for ix in inner:
        idx = [at[a.pubkey] for a in ix.accounts]
        if len(idx) > 255 or len(ix.data) > 0xFFFF:
            raise ValueError("an inner instruction is too large for LazorKit's compact form")
        out.append(bytes([at[ix.program_id], len(idx), *idx]) + len(ix.data).to_bytes(2, "little") + bytes(ix.data))
        keys += [bytes(ix.program_id)] + [bytes(a.pubkey) for a in ix.accounts]
    return b"".join(out), hashlib.sha256(b"".join(keys)).digest()


def execute(payer: Pubkey, wallet: Pubkey, authority: Pubkey, inner: list[Instruction], *, slot: int, counter: int, rp_id: str,
            key: bytes, flags: int = UP | UV, sign_count: int = 0, type_flags: int = TYPE_GET, pre=None,
            program: Pubkey = LAZOR_ID) -> Prepared:
    """Execute: the wallet's vault signs `inner` (CPIs), approved by the passkey. `counter` is the authority's odometer
    plus one (read_authority(...).counter + 1); `slot` a recent slot of the chain."""
    vault = vault_pda(wallet, program)
    metas: dict[Pubkey, list[bool]] = {payer: [True, True], wallet: [False, False], authority: [False, True], vault: [False, True]}
    for ix in inner:
        if ix.program_id == program:
            raise ValueError("a LazorKit wallet cannot call LazorKit itself")
        metas.setdefault(ix.program_id, [False, False])
        for a in ix.accounts:
            m = metas.setdefault(a.pubkey, [False, False])
            m[1] = m[1] or a.is_writable
            if a.is_signer and a.pubkey not in (vault, payer):
                raise ValueError(f"{a.pubkey} would have to sign: only the vault (and the relayer paying) sign inside Execute")
    metas.setdefault(INSTRUCTIONS, [False, False])
    accounts = [AccountMeta(k, s, w) for k, (s, w) in metas.items()]
    compact, h = _compact(accounts, inner)
    return Prepared(EXECUTE, program, payer, accounts, compact, compact + h, slot, counter, list(metas).index(INSTRUCTIONS),
                    rp_id, compressed(key), flags, sign_count, type_flags, list(pre or []))


def transfer_ownership(payer: Pubkey, wallet: Pubkey, current: Pubkey, new_credential_hash: bytes, new_key: bytes, new_rp_id: str, *,
                       slot: int, counter: int, rp_id: str, key: bytes, flags: int = UP | UV, sign_count: int = 0,
                       type_flags: int = TYPE_GET, pre=None, program: Pubkey = LAZOR_ID) -> Prepared:
    """TransferOwnership: the wallet's owner becomes another passkey and the current owner's authority is closed."""
    new = authority_pda(wallet, new_credential_hash, program)[0]
    payload = bytes([1]) + auth_blob(new_credential_hash, new_key, new_rp_id)
    accounts = [AccountMeta(payer, True, True), AccountMeta(wallet, False, False), AccountMeta(current, False, True), AccountMeta(new, False, True),
                AccountMeta(SYSTEM, False, False), AccountMeta(RENT, False, False), AccountMeta(INSTRUCTIONS, False, False)]
    return Prepared(TRANSFER_OWNERSHIP, program, payer, accounts, payload, payload + bytes(payer), slot, counter, 6, rp_id, compressed(key),
                    flags, sign_count, type_flags, list(pre or []))


# ---- size: an address lookup table -------------------------------------------------------------------------------
# A passkey-approved panel pre-order is one transaction of about 1,470 bytes with every key written out (the panel
# order's terms alone are 510 bytes of knos_pay data, and the precompile carries the signature, the key and the
# message): above Solana's 1,232. A v0 transaction that loads the accounts every pre-order names from one lookup
# table (the relayer's, made once) and sends the rents of the order a transaction earlier is under it.
ALT_PROGRAM = Pubkey.from_string("AddressLookupTab1e1111111111111111111111111")


def table_addresses(pay_program: Pubkey, mint: Pubkey, extra=()) -> list[Pubkey]:
    """What every passkey pre-order of one mint names besides its own wallet and order: knos_pay and its accounts,
    the token and system programs, the sysvars. (Programs a transaction calls at its top level cannot be loaded.)"""
    from . import pay
    auth = Pubkey.find_program_address([b"auth"], pay_program)[0]
    pause = Pubkey.find_program_address([b"pause"], pay_program)[0]
    out = [pay_program, auth, pause, mint, pay.TOKEN, SYSTEM, INSTRUCTIONS, RENT, pay.ATA_PROGRAM, *extra]
    return list(dict.fromkeys(out))


def create_table_ixs(authority: Pubkey, payer: Pubkey, recent_slot: int, addresses: list[Pubkey]) -> tuple[Pubkey, list[Instruction]]:
    """CreateLookupTable (0) and ExtendLookupTable (2) of the lookup table program (bincode: a u32 tag). `recent_slot`
    must be one of the chain's recent slots (SlotHashes)."""
    table, bump = Pubkey.find_program_address([bytes(authority), int(recent_slot).to_bytes(8, "little")], ALT_PROGRAM)
    create = Instruction(ALT_PROGRAM, (0).to_bytes(4, "little") + int(recent_slot).to_bytes(8, "little") + bytes([bump]),
                         [AccountMeta(table, False, True), AccountMeta(authority, True, False), AccountMeta(payer, True, True), AccountMeta(SYSTEM, False, False)])
    extend = Instruction(ALT_PROGRAM, (2).to_bytes(4, "little") + len(addresses).to_bytes(8, "little") + b"".join(bytes(a) for a in addresses),
                         [AccountMeta(table, False, True), AccountMeta(authority, True, False), AccountMeta(payer, True, True), AccountMeta(SYSTEM, False, False)])
    return table, [create, extend]


def read_table(data: bytes | None) -> list[Pubkey]:
    """The addresses of a lookup table account (56 bytes of metadata, then 32 per address)."""
    if not data or len(data) < 56:
        return []
    return [Pubkey.from_bytes(data[i:i + 32]) for i in range(56, len(data) - 31, 32)]


def wallet_table_addresses(wallet: Pubkey, credential_hash: bytes, mint: Pubkey, program: Pubkey = LAZOR_ID) -> list[Pubkey]:
    """A passkey wallet's own table (made by the relayer when the wallet is made): its wallet, authority, vault and
    the vault's token account. With the shared table, a 3-referee panel pre-order is 1,121 bytes instead of 1,211."""
    from . import pay
    v = vault_pda(wallet, program)
    return [wallet, authority_pda(wallet, credential_hash, program)[0], v, pay.ata(v, mint)]


def message_v0(payer: Pubkey, ixs: list[Instruction], tables: list[tuple[Pubkey, list[Pubkey]]], blockhash):
    """A v0 message loading what it can from `tables` [(table address, its addresses)]."""
    from solders.address_lookup_table_account import AddressLookupTableAccount
    from solders.message import MessageV0
    return MessageV0.try_compile(payer, ixs, [AddressLookupTableAccount(k, list(a)) for k, a in tables if k is not None and a], blockhash)


def control_filters(wallet: Pubkey) -> list[tuple[int, int]]:
    """getProgramAccounts memcmp filters, (discriminator, wallet offset), for every LazorKit account that can act for
    `wallet`: authorities, sessions and deferred executions."""
    return [(d, at) for d, at in WALLET_AT.items()]


def sole_owner(found: list[tuple[Pubkey, bytes]], wallet: Pubkey, credential_hash: bytes, now_slot: int) -> tuple[bool, str]:
    """Whether the accounts that name `wallet` (from control_filters) leave exactly one power over it: the owner
    authority of `credential_hash`. A session or a deferred execution still live, or any other authority, is refused."""
    owners = []
    for addr, data in found:
        if not data:
            continue
        d = data[0]
        if d == D_AUTHORITY:
            a = read_authority(data)
            if a is None or a.wallet != wallet:
                if data[16:48] == bytes(wallet):
                    return False, f"authority {addr} of an unknown kind acts for this wallet"
                continue
            owners.append(a)
        elif d == D_SESSION and data[8:40] == bytes(wallet):
            if int.from_bytes(data[72:80], "little") >= now_slot:
                return False, f"a live session {addr} can still spend from this wallet"
        elif d == D_DEFERRED and data[72:104] == bytes(wallet):
            if int.from_bytes(data[168:176], "little") >= now_slot:
                return False, f"a deferred execution {addr} authorized by an earlier owner can still run"
    if len(owners) != 1:
        return False, f"{len(owners)} authorities act for this wallet"
    if owners[0].credential_hash != credential_hash or owners[0].role != 0:
        return False, "the wallet's one authority is another passkey"
    return True, "one owner: this passkey"
