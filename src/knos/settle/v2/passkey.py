"""Client for knos-passkey (programs-v2/knos_passkey): a wallet from a passkey. Pure address derivation, instruction
builders and the account reader; no network and no elliptic-curve code. The program is upgradeable only through a
multisig with a public 48-hour delay, until an outside review.

A passkey is a P-256 key a browser creates and keeps (WebAuthn). Its wallet is `wallet(key)`, the program's account
at ["pk", sha256(key)], with `key` the public key in its 33-byte compressed form (`compressed` takes the forms a
browser gives). That address can be paid like any other before it exists on chain: its money is in ordinary token
accounts it owns, `pay.ata(wallet, mint)` (knos.settle.v2.pay).

To withdraw, the passkey signs a WebAuthn assertion whose challenge is `challenge(wallet, mint, to, amount, nonce)`:
`to` is the destination TOKEN ACCOUNT (`pay.ata(owner, mint)` for a wallet address), `nonce` is `read_wallet(...).nonce + 1`.
One transaction then carries, in this order, with anyone paying the fee:

    open_ix(payer, key)                       only the first time: the wallet's account, nonce 0
    pay.create_ata_ix(payer, owner, mint)     only if the destination does not exist yet (the payer pays its rent)
    *withdraw_ixs(key, mint, to, amount, nonce, authenticator_data, client_data_json, signature)

`withdraw_ixs` is two instructions that must stay next to each other: Solana's secp256r1 precompile verifying the
assertion's signature (`secp256r1_ix`), then Withdraw, which reads what the precompile verified and checks that it
is this wallet's key over this withdrawal. Nothing else can move the money: see the header of the program's lib.rs.

A person with no SOL asks a relay to send it: `request(...)` is the text of the comment `knos-withdraw: <text>` on an
issue of their knos-claim repository, `read_request` reads it back, and knos.settle.v2.relay.withdraw checks it by
simulation and sends it at the relay's cost.
"""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

from . import load_ids
from knos.settle.v2.pay import SYSTEM, TOKEN, ata

IDS = load_ids()            # the pinned ids, or a staging deployment named by KNOS_PROGRAM_IDS
PASSKEY_ID = Pubkey.from_string(IDS["knos_passkey"])
SECP256R1_ID = Pubkey.from_string("Secp256r1SigVerify1111111111111111111111111")   # the precompile (SIMD-0075)
INSTRUCTIONS = Pubkey.from_string("Sysvar1nstructions1111111111111111111111111")    # the instructions sysvar
DOMAIN = b"knos-passkey"
WALLET_LEN = 48
N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551            # the order of P-256
_SPKI = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200")      # what precedes the point in a P-256 SubjectPublicKeyInfo
ERRORS = {110: "a wrong account in the instruction",
          111: "that is not a compressed P-256 public key (33 bytes starting with 02 or 03)",
          112: "that account is not a passkey wallet; open it first",
          113: "the instruction right before Withdraw must be the secp256r1 check of this passkey's signature, with everything in its own data",
          114: "the signature is another passkey's, not this wallet's",
          115: "the signed message is not this authenticator data followed by the hash of this client data",
          116: "the authenticator did not report that a person was present; sign again and confirm on the device",
          117: "the client data is not that of a passkey signature (type webauthn.get, with a challenge)",
          118: "the passkey signed for another withdrawal: the wallet, the mint, the destination, the amount or the nonce differs; sign again for this one",
          119: "the nonce is not the wallet's nonce plus one: this withdrawal was sent already, or another came first; read the wallet and sign again",
          120: "this mint cannot be withdrawn: it is not a mint of the token program passed, or it is a Token-2022 mint with an extension the program does not accept",
          121: "the signature's s is in the upper half; send n - s instead, as this client's builders do",
          122: "the source is not a token account of this mint owned by the wallet, or it is the destination"}


def _u64(v: int) -> bytes:
    return v.to_bytes(8, "little")


def compressed(key: bytes) -> bytes:
    """A P-256 public key as the program stores it: 33 bytes, 02 or 03 (y even or odd), then x. Takes that form, the
    65-byte uncompressed point (04, x, y) and the 91-byte SubjectPublicKeyInfo a browser's getPublicKey() returns."""
    key = bytes(key)
    if len(key) == 91 and key.startswith(_SPKI):
        key = key[len(_SPKI):]
    if len(key) == 65 and key[0] == 4:
        key = bytes([2 + (key[64] & 1)]) + key[1:33]
    if len(key) != 33 or key[0] not in (2, 3):
        raise ValueError("not a P-256 public key: give its 33-byte compressed form, its 65-byte point, or the 91 bytes of getPublicKey()")
    return key


def wallet(key: bytes, program: Pubkey = PASSKEY_ID) -> Pubkey:
    """The address of a passkey's wallet: ["pk", sha256(compressed public key)]."""
    return Pubkey.find_program_address([b"pk", hashlib.sha256(compressed(key)).digest()], program)[0]


def challenge(wallet: Pubkey, mint: Pubkey, to: Pubkey, amount: int, nonce: int) -> bytes:
    """The 32 bytes the passkey signs as its WebAuthn challenge to withdraw `amount` of `mint` to the token account
    `to`, as the wallet's withdrawal number `nonce`."""
    return hashlib.sha256(DOMAIN + bytes(wallet) + bytes(mint) + bytes(to) + _u64(amount) + _u64(nonce)).digest()


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def raw_signature(signature: bytes) -> bytes:
    """A P-256 signature as the precompile takes it: r then s, 32 bytes each, with s in the lower half of the order.
    Takes that form or the ASN.1 DER a browser returns (SEQUENCE of two INTEGERs). (r, n - s) verifies whenever
    (r, s) does, so lowering s changes nothing about who signed what."""
    sig = bytes(signature)
    if len(sig) != 64:
        try:
            if sig[0] != 0x30 or sig[1] != len(sig) - 2 or sig[2] != 2:
                raise ValueError
            r_end = 4 + sig[3]
            if sig[r_end] != 2 or r_end + 2 + sig[r_end + 1] != len(sig):
                raise ValueError
            r, s = int.from_bytes(sig[4:r_end], "big"), int.from_bytes(sig[r_end + 2:], "big")
            sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        except (IndexError, ValueError, OverflowError):
            raise ValueError("not a P-256 signature: give r and s (64 bytes) or the DER a browser returns") from None
    r, s = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")
    if not (0 < r < N and 0 < s < N):
        raise ValueError("not a P-256 signature: r or s is out of range")
    return sig[:32] + min(s, N - s).to_bytes(32, "big")


@dataclass(frozen=True)
class Request:
    """A withdrawal as its owner asks a relay to send it: everything `withdraw_ixs` takes, and nothing secret."""
    key: bytes
    mint: Pubkey
    to: Pubkey
    amount: int
    nonce: int
    authenticator_data: bytes
    client_data_json: bytes
    signature: bytes

    @property
    def wallet(self) -> Pubkey:
        return wallet(self.key)


REQUEST_PREFIX = "knos-withdraw:"       # the marker of the line a withdrawal request travels in


def request(key: bytes, mint: Pubkey, to: Pubkey, amount: int, nonce: int, authenticator_data: bytes, client_data_json: bytes, signature: bytes) -> str:
    """The text of a withdrawal request, for the comment `knos-withdraw: <text>` a relay reads: base64 (the standard
    alphabet, padded) of key (33 bytes, compressed), mint (32), to (32, the destination token account), amount and
    nonce (u64 LE each), then authenticatorData and clientDataJSON, each behind its length (u16 LE), then the
    signature (r and s, 64 bytes, s in the lower half). Anyone may read and send it: the passkey signed this one
    withdrawal and no other. The site writes the same bytes (sdk/settle/passkey.js, withdrawRequest), and one fixture
    holds both to it: `request` in sdk/settle/passkey.fixtures.json."""
    auth, cdj = bytes(authenticator_data), bytes(client_data_json)
    raw = (compressed(key) + bytes(mint) + bytes(to) + _u64(amount) + _u64(nonce) + len(auth).to_bytes(2, "little") + auth
           + len(cdj).to_bytes(2, "little") + cdj + raw_signature(signature))
    return base64.b64encode(raw).decode()


def request_line(*args, **kw) -> str:
    """The whole line, as the site shows it and a person posts it: `knos-withdraw: <request(...)>`."""
    return f"{REQUEST_PREFIX} {request(*args, **kw)}"


def read_request(text: str | bytes) -> Request:
    """What `request` wrote (standard or URL-safe base64), alone or behind its `knos-withdraw:` marker. ValueError
    for anything else."""
    try:
        t = (text.decode() if isinstance(text, bytes) else text).strip()
        t = t[len(REQUEST_PREFIX):].strip() if t.startswith(REQUEST_PREFIX) else t
        t = t.replace("-", "+").replace("_", "/")
        raw = base64.b64decode(t + "=" * (-len(t) % 4), validate=True)
        key, mint, to = compressed(raw[:33]), Pubkey.from_bytes(raw[33:65]), Pubkey.from_bytes(raw[65:97])
        amount, nonce, at = int.from_bytes(raw[97:105], "little"), int.from_bytes(raw[105:113], "little"), 113
        parts = []
        for _ in range(2):
            size = int.from_bytes(raw[at:at + 2], "little")
            parts.append(raw[at + 2:at + 2 + size])
            at += 2 + size
            if len(parts[-1]) != size:
                raise ValueError
        if len(raw) - at != 64 or len(raw[:113]) != 113:
            raise ValueError
        return Request(key, mint, to, amount, nonce, parts[0], parts[1], raw_signature(raw[at:]))
    except (ValueError, IndexError, TypeError, UnicodeDecodeError):
        raise ValueError("not a withdrawal request: base64 of key, mint, to, amount, nonce, authenticatorData, clientDataJSON, signature") from None


@dataclass(frozen=True)
class Wallet:
    key: bytes      # the passkey's compressed public key
    nonce: int      # the nonce of the last withdrawal; the next one carries nonce + 1


def read_wallet(data: bytes | None) -> Wallet | None:
    """A wallet account's data; None when the wallet is not open yet (its next nonce is then 1, after open_ix)."""
    if data is None or len(data) != WALLET_LEN or data[0] != 1:
        return None
    return Wallet(key=bytes(data[2:35]), nonce=int.from_bytes(data[40:48], "little"))


# -- instructions -----------------------------------------------------------------------------------------------------
def open_ix(payer: Pubkey, key: bytes, program: Pubkey = PASSKEY_ID) -> Instruction:
    """Open: creates the wallet's account (anyone pays its rent). A wallet that is open already is left as it is."""
    key = compressed(key)
    return Instruction(program, b"\x00" + key, [AccountMeta(payer, True, True), AccountMeta(wallet(key, program), False, True),
                                                AccountMeta(SYSTEM, False, False)])


def secp256r1_ix(key: bytes, signature: bytes, message: bytes) -> Instruction:
    """The precompile instruction that verifies one P-256 signature over `message`, everything in its own data:
    count 1, padding, seven u16 LE (signature offset, signature instruction, key offset, key instruction, message
    offset, message length, message instruction; an instruction of 0xFFFF is this one), then key, signature, message."""
    key, sig = compressed(key), raw_signature(signature)
    offsets = (16 + 33, 0xFFFF, 16, 0xFFFF, 16 + 33 + 64, len(message), 0xFFFF)
    return Instruction(SECP256R1_ID, bytes([1, 0]) + b"".join(v.to_bytes(2, "little") for v in offsets) + key + sig + bytes(message), [])


def withdraw_ix(key: bytes, mint: Pubkey, to: Pubkey, amount: int, nonce: int, client_data_json: bytes, token_program: Pubkey = TOKEN,
                from_token: Pubkey | None = None, program: Pubkey = PASSKEY_ID) -> Instruction:
    """Withdraw alone; it is refused unless the instruction right before it is `secp256r1_ix` for the same assertion.
    `from_token`: the wallet's token account to spend (default: its associated one)."""
    w = wallet(key, program)
    source = from_token or ata(w, mint, token_program)
    return Instruction(program, b"\x01" + _u64(amount) + _u64(nonce) + bytes(client_data_json),
                       [AccountMeta(w, False, True), AccountMeta(source, False, True), AccountMeta(mint, False, False), AccountMeta(to, False, True),
                        AccountMeta(token_program, False, False), AccountMeta(INSTRUCTIONS, False, False)])


def withdraw_ixs(key: bytes, mint: Pubkey, to: Pubkey, amount: int, nonce: int, authenticator_data: bytes, client_data_json: bytes,
                 signature: bytes, token_program: Pubkey = TOKEN, from_token: Pubkey | None = None, program: Pubkey = PASSKEY_ID) -> list[Instruction]:
    """The two instructions of a withdrawal, from a WebAuthn assertion (response.authenticatorData,
    response.clientDataJSON, response.signature): the precompile over authenticatorData || sha256(clientDataJSON),
    then Withdraw. Keep them adjacent and in this order."""
    message = bytes(authenticator_data) + hashlib.sha256(bytes(client_data_json)).digest()
    return [secp256r1_ix(key, signature, message),
            withdraw_ix(key, mint, to, amount, nonce, client_data_json, token_program, from_token, program)]
