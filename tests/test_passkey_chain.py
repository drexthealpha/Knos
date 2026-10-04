"""knos-passkey (programs-v2/knos_passkey) inside LiteSVM: a wallet whose only authority is a WebAuthn passkey.

WHAT RUNS HERE. The program is the real build (tests/fixtures/knos_passkey_v2_real.so; it has no test feature).
The secp256r1 precompile is LiteSVM's own, the same native code a validator runs: every withdrawal below carries a
real P-256 signature that the precompile verifies, and `test_the_precompile_itself_runs_here` shows it refusing a
wrong one. The authenticator is a stand-in (`Passkey`: a P-256 key from `cryptography` that signs what a browser's
authenticator signs, authenticatorData || sha256(clientDataJSON), and returns the DER a browser returns). No browser
and no cluster take part.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from solders.compute_budget import set_compute_unit_limit
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.litesvm import LiteSVM
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.system_program import CreateAccountParams, TransferParams, create_account, transfer
from solders.transaction import VersionedTransaction

from knos.settle.v2 import passkey as pk
from knos.settle.v2 import passkey_fund as pf
from knos.settle.v2 import pay
from knos.settle.v2.pay import TOKEN, TOKEN_2022, ata, create_ata_ix

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "tests" / "fixtures" / "knos_passkey_v2_real.so"
SRC = {p.name: p.read_text(encoding="utf-8") for p in (ROOT / "programs-v2" / "knos_passkey" / "src").glob("*.rs")}
ORIGIN, RP_ID = "https://knos.dev", "knos.dev"
UP, UV = 0x01, 0x04                 # authenticatorData flags: a person was present; the person was verified


class Passkey:
    """What a platform authenticator does with one passkey, for a page at ORIGIN."""
    def __init__(self, seed: int):
        self.sk = ec.derive_private_key(seed, ec.SECP256R1())
        pub = self.sk.public_key()
        self.spki = pub.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)   # getPublicKey()
        self.point = pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.key = pub.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.CompressedPoint)
        self.wallet = pk.wallet(self.key)
        self.count = 0

    def sign(self, message: bytes, high_s: bool | None = None) -> bytes:
        """DER, as a browser returns it. high_s: True or False forces which of the two valid s values is returned."""
        r, s = utils.decode_dss_signature(self.sk.sign(message, ec.ECDSA(hashes.SHA256())))
        if high_s is not None and (s > pk.N // 2) != high_s:
            s = pk.N - s
        return utils.encode_dss_signature(r, s)

    def get(self, challenge: bytes, flags: int = UP | UV, client_data: bytes | None = None, high_s: bool | None = None) -> tuple[bytes, bytes, bytes]:
        """navigator.credentials.get: (authenticatorData, clientDataJSON, signature)."""
        self.count += 1
        auth = hashlib.sha256(RP_ID.encode()).digest() + bytes([flags]) + self.count.to_bytes(4, "big")
        cdj = client_data if client_data is not None else client_data_json(challenge)
        return auth, cdj, self.sign(auth + hashlib.sha256(cdj).digest(), high_s)


def client_data_json(challenge: bytes, type_: str = "webauthn.get") -> bytes:
    """The clientDataJSON a browser writes (WebAuthn's serialisation: type, challenge, origin, crossOrigin)."""
    return json.dumps({"type": type_, "challenge": pk.b64url(challenge), "origin": ORIGIN, "crossOrigin": False}, separators=(",", ":")).encode()


class Chain:
    def __init__(self):
        assert BUILD.is_file(), "tests/fixtures/knos_passkey_v2_real.so is missing: bash scripts/build_programs_v2.sh passkey"
        self.svm = LiteSVM()
        self.svm.add_program_from_file(pk.PASSKEY_ID, str(BUILD))
        self.payer = self.fund()            # the relay: pays every fee and every rent, holds no token, signs nothing else
        self.err: str | None = None
        self.logs: list[str] = []

    def fund(self, sol: int = 10) -> Keypair:
        k = Keypair(); self.svm.airdrop(k.pubkey(), sol * 10 ** 9); return k

    def send(self, ixs, signers=(), budget: bool = True, payer: Keypair | None = None) -> bool:
        """One transaction, paid by the relay. budget: a compute budget instruction goes first (index 0)."""
        ixs, payer = [set_compute_unit_limit(400_000), *ixs] if budget else list(ixs), payer or self.payer
        tx = VersionedTransaction(MessageV0.try_compile(payer.pubkey(), ixs, [], self.svm.latest_blockhash()), [payer, *signers])
        self.size = len(bytes(tx))
        r = self.svm.send_transaction(tx)
        self.svm.expire_blockhash()
        ok = "Failed" not in type(r).__name__
        meta = r if ok else r.meta()
        self.err = None if ok else str(r.err())
        self.logs = list(meta.logs())
        used = [int(m.group(1)) for m in (re.match(rf"Program {pk.PASSKEY_ID} consumed (\d+) of", line) for line in self.logs) if m]
        self.cu = used[-1] if used else 0
        return ok

    def refused(self, ixs, **kw) -> tuple[int, int] | str:
        """(index of the instruction that failed, its custom error code) of a transaction that must not go through."""
        assert not self.send(ixs, **kw), "the transaction went through"
        m = re.search(r"\((\d+), Tagged\(InstructionErrorCustom\((\d+)\)\)", self.err)
        return (int(m.group(1)), int(m.group(2))) if m else self.err

    def said(self, prefix: str) -> list[str]:
        return [line.split("Program log: ", 1)[1] for line in self.logs if line.startswith("Program log: " + prefix)]

    def data(self, address: Pubkey) -> bytes | None:
        a = self.svm.get_account(address)
        return bytes(a.data) if a is not None and a.lamports > 0 else None

    def lamports(self, address: Pubkey) -> int:
        return self.svm.get_balance(address) or 0

    def mint(self, program: Pubkey = TOKEN, extensions: list[tuple[int, bytes]] = (), at: Keypair | None = None) -> Pubkey:
        """A 6-decimal mint whose mint authority is the relay. extensions: (value length, initialising instruction data)."""
        m, me = at or Keypair(), self.payer.pubkey()
        space = 166 + sum(4 + n for n, _ in extensions) if extensions else 82
        ixs = [create_account(CreateAccountParams(from_pubkey=me, to_pubkey=m.pubkey(), lamports=self.svm.minimum_balance_for_rent_exemption(space),
                                                  space=space, owner=program)),
               *(Instruction(program, data, [AccountMeta(m.pubkey(), False, True)]) for _, data in extensions),
               Instruction(program, bytes([20, 6]) + bytes(me) + b"\x00", [AccountMeta(m.pubkey(), False, True)])]
        assert self.send(ixs, signers=[m]), self.err
        return m.pubkey()

    def pay(self, owner: Pubkey, mint: Pubkey, amount: int, program: Pubkey = TOKEN) -> Pubkey:
        """What paying an address is: its associated token account, created by the one who pays, and tokens into it."""
        t = ata(owner, mint, program)
        ixs = [create_ata_ix(self.payer.pubkey(), owner, mint, program),
               Instruction(program, b"\x07" + amount.to_bytes(8, "little"), [AccountMeta(mint, False, True), AccountMeta(t, False, True),
                                                                              AccountMeta(self.payer.pubkey(), True, False)])]
        assert self.send(ixs), self.err
        return t

    def balance(self, token_account: Pubkey) -> int:
        d = self.data(token_account)
        return int.from_bytes(d[64:72], "little") if d and len(d) >= 165 else 0

    def nonce(self, p: Passkey) -> int:
        w = pk.read_wallet(self.data(p.wallet))
        return w.nonce if w else 0


class World:
    """A chain, a mint, a passkey whose wallet was paid 100.00 and opened, and somewhere to withdraw to."""
    def __init__(self, program: Pubkey = TOKEN, extensions=()):
        self.c = Chain()
        self.program = program
        self.mint = self.c.mint(program, extensions)
        self.p = Passkey(7)
        self.source = self.c.pay(self.p.wallet, self.mint, 100_000_000, program)
        assert self.c.send([pk.open_ix(self.c.payer.pubkey(), self.p.key)]), self.c.err
        self.owner = Keypair().pubkey()                                   # the person's other wallet, or an exchange's address
        self.to = ata(self.owner, self.mint, program)
        assert self.c.send([create_ata_ix(self.c.payer.pubkey(), self.owner, self.mint, program)]), self.c.err

    def ixs(self, amount: int = 5_000_000, nonce: int | None = None, *, signer: Passkey | None = None, signed: dict | None = None,
            assertion: tuple[bytes, bytes, bytes] | None = None, **get) -> list[Instruction]:
        """[precompile, Withdraw] for `amount` to self.to. signed: what the passkey signs instead (wallet, mint, to,
        amount, nonce), when it differs from what the instruction says. assertion: use this one, already made."""
        nonce = self.c.nonce(self.p) + 1 if nonce is None else nonce
        what = dict(wallet=self.p.wallet, mint=self.mint, to=self.to, amount=amount, nonce=nonce) | (signed or {})
        auth, cdj, sig = assertion or (signer or self.p).get(pk.challenge(**what), **get)
        return pk.withdraw_ixs(self.p.key, self.mint, self.to, amount, nonce, auth, cdj, sig, self.program)

    def state(self) -> tuple[int, int, int]:
        return self.c.balance(self.source), self.c.balance(self.to), self.c.nonce(self.p)


@pytest.fixture()
def w() -> World:
    return World()


E = {name: int(code) for name, code in re.findall(r"pub const (E_\w+): u32 = (\d+);", SRC["lib.rs"])}


# -- the precompile ---------------------------------------------------------------------------------------------------
def test_the_precompile_itself_runs_here():
    """LiteSVM executes Secp256r1SigVerify: a good signature passes, and a signature over another message, a high s
    and a signature of another key are each refused by the precompile's own instruction (its error 2)."""
    c, a, b = Chain(), Passkey(1), Passkey(2)
    assert c.svm.get_account(pk.SECP256R1_ID).executable
    message = b"what an authenticator signs"
    assert c.send([pk.secp256r1_ix(a.key, a.sign(message), message)], budget=False), c.err
    raw = pk.raw_signature(a.sign(message))
    high = raw[:32] + (pk.N - int.from_bytes(raw[32:], "big")).to_bytes(32, "big")
    unchecked = lambda key, sig, msg: Instruction(pk.SECP256R1_ID, bytes(pk.secp256r1_ix(key, raw, msg).data)[:16] + key + sig + msg, [])  # noqa: E731
    assert c.send([unchecked(a.key, raw, message)], budget=False), c.err
    assert c.refused([unchecked(a.key, raw, message + b"!")], budget=False) == (0, 2)
    assert c.refused([unchecked(a.key, high, message)], budget=False) == (0, 2)
    assert c.refused([unchecked(b.key, raw, message)], budget=False) == (0, 2)


# -- a withdrawal -----------------------------------------------------------------------------------------------------
def test_a_wallet_is_paid_before_it_exists_and_one_transaction_opens_it_and_withdraws():
    c, p = Chain(), Passkey(3)
    mint = c.mint()
    source = c.pay(p.wallet, mint, 100_000_000)             # the address is only derived so far: no account is there
    assert c.data(p.wallet) is None and c.balance(source) == 100_000_000
    owner = Keypair().pubkey()
    to = ata(owner, mint)
    auth, cdj, sig = p.get(pk.challenge(p.wallet, mint, to, 25_000_000, 1))
    relay_before, source_rent = c.lamports(c.payer.pubkey()), c.lamports(source)
    ixs = [pk.open_ix(c.payer.pubkey(), p.spki), create_ata_ix(c.payer.pubkey(), owner, mint),
           *pk.withdraw_ixs(p.point, mint, to, 25_000_000, 1, auth, cdj, sig)]
    assert c.send(ixs), c.err
    assert c.size <= 1232, c.size                           # one legacy transaction
    assert (c.balance(source), c.balance(to)) == (75_000_000, 25_000_000)
    assert pk.read_wallet(c.data(p.wallet)) == pk.Wallet(key=p.key, nonce=1)
    assert c.said("knosp:") == [f"knosp:opened wallet={p.wallet}", f"knosp:withdrawn wallet={p.wallet} mint={mint} to={to} amount=25000000 nonce=1"]
    # the relay paid for everything that was created; the wallet holds its rent and nothing of its token account moved
    rent = c.svm.minimum_balance_for_rent_exemption
    assert c.lamports(p.wallet) == rent(pk.WALLET_LEN) and c.lamports(source) == source_rent
    assert relay_before - c.lamports(c.payer.pubkey()) >= rent(pk.WALLET_LEN) + rent(165)
    assert c.cu < 40_000, c.cu


def test_withdrawals_follow_one_another_and_none_can_be_sent_twice(w: World):
    first = w.ixs(5_000_000)
    assert w.c.send(first), w.c.err
    assert w.state() == (95_000_000, 5_000_000, 1)
    assert w.c.refused(first) == (2, E["E_NONCE"])                       # the same assertion again
    second = w.ixs(1_000_000)
    assert w.c.send(second), w.c.err
    assert w.state() == (94_000_000, 6_000_000, 2)
    for old in (first, second):
        assert w.c.refused(old) == (2, E["E_NONCE"])
    assert w.state() == (94_000_000, 6_000_000, 2)


def test_a_wrong_nonce_is_refused(w: World):
    assert w.c.send(w.ixs()), w.c.err                                    # the wallet's nonce is 1
    for nonce in (0, 1, 3, 2 ** 64 - 1):                                 # signed and sent with a nonce that is not 2
        assert w.c.refused(w.ixs(nonce=nonce)) == (2, E["E_NONCE"]), nonce
    # signed for nonce 3 and sent as 2, and the reverse: the instruction's nonce is the one checked first
    assert w.c.refused(w.ixs(nonce=2, signed={"nonce": 3})) == (2, E["E_CHALLENGE"])
    assert w.c.refused(w.ixs(nonce=3, signed={"nonce": 2})) == (2, E["E_NONCE"])
    assert w.state() == (95_000_000, 5_000_000, 1)
    assert w.c.send(w.ixs(nonce=2)), w.c.err


def test_another_passkeys_signature_is_refused(w: World):
    other = Passkey(8)
    assert w.c.send([pk.open_ix(w.c.payer.pubkey(), other.key)]), w.c.err
    # the other passkey signs exactly this withdrawal; the precompile verifies it (it is a good signature of that key)
    auth, cdj, sig = other.get(pk.challenge(w.p.wallet, w.mint, w.to, 5_000_000, 1))
    message = auth + hashlib.sha256(cdj).digest()
    withdraw = pk.withdraw_ix(w.p.key, w.mint, w.to, 5_000_000, 1, cdj)
    assert w.c.refused([pk.secp256r1_ix(other.key, sig, message), withdraw]) == (2, E["E_SIGNER"])
    # the same signature under this wallet's key does not verify at all: the precompile stops the transaction
    assert w.c.refused([pk.secp256r1_ix(w.p.key, sig, message), withdraw]) == (1, 2)
    # the other passkey's own withdrawal, pointed at this wallet's money
    auth, cdj, sig = other.get(pk.challenge(other.wallet, w.mint, w.to, 5_000_000, 1))
    mixed = Instruction(pk.PASSKEY_ID, bytes(withdraw.data)[:17] + cdj,
                        [AccountMeta(other.wallet, False, True), *withdraw.accounts[1:]])   # its wallet, this wallet's token account
    assert w.c.refused([pk.secp256r1_ix(other.key, sig, auth + hashlib.sha256(cdj).digest()), mixed]) == (2, E["E_FROM"])
    assert w.state() == (100_000_000, 0, 0)


def test_a_changed_amount_destination_or_mint_is_refused(w: World):
    c = w.c
    assertion = w.p.get(pk.challenge(w.p.wallet, w.mint, w.to, 5_000_000, 1))
    auth, cdj, sig = assertion
    thief = c.pay(Keypair().pubkey(), w.mint, 0)                          # a token account of the same mint, someone else's
    other_mint = c.mint()
    c.pay(w.p.wallet, other_mint, 100_000_000)
    for name, ixs in {
        "amount": pk.withdraw_ixs(w.p.key, w.mint, w.to, 50_000_000, 1, auth, cdj, sig),
        "destination": pk.withdraw_ixs(w.p.key, w.mint, thief, 5_000_000, 1, auth, cdj, sig),
        "mint": pk.withdraw_ixs(w.p.key, other_mint, c.pay(w.owner, other_mint, 0), 5_000_000, 1, auth, cdj, sig),
    }.items():
        assert c.refused(ixs) == (2, E["E_CHALLENGE"]), name
    # a relay cannot repair the client data either: the signature is over its hash
    forged = client_data_json(pk.challenge(w.p.wallet, w.mint, thief, 5_000_000, 1))
    message = auth + hashlib.sha256(cdj).digest()
    assert c.refused([pk.secp256r1_ix(w.p.key, sig, message), pk.withdraw_ix(w.p.key, w.mint, thief, 5_000_000, 1, forged)]) == (2, E["E_MESSAGE"])
    assert w.state() == (100_000_000, 0, 0) and c.balance(thief) == 0
    assert c.send(w.ixs(assertion=assertion)), c.err                     # untouched, the same assertion pays what it says
    assert w.state() == (95_000_000, 5_000_000, 1)


def test_a_missing_or_misplaced_precompile_instruction_is_refused(w: World):
    c = w.c
    verify, withdraw = w.ixs()
    spacer = transfer(TransferParams(from_pubkey=c.payer.pubkey(), to_pubkey=c.payer.pubkey(), lamports=1))
    assert c.refused([withdraw], budget=False) == (0, E["E_PRECOMPILE"])             # no instruction before it
    assert c.refused([withdraw]) == (1, E["E_PRECOMPILE"])                           # another program's instruction before it
    assert c.refused([withdraw, verify]) == (1, E["E_PRECOMPILE"])                   # after it
    assert c.refused([verify, spacer, withdraw]) == (3, E["E_PRECOMPILE"])           # not right before it
    auth, cdj, _ = w.p.get(pk.challenge(w.p.wallet, w.mint, w.to, 5_000_000, 2))     # the next withdrawal, signed, but with no check of its own
    assert c.refused([verify, withdraw, pk.withdraw_ix(w.p.key, w.mint, w.to, 5_000_000, 2, cdj)]) == (3, E["E_PRECOMPILE"])
    assert w.state() == (100_000_000, 0, 0)
    # the instructions account must be the sysvar, not an account someone filled
    fake = Instruction(pk.PASSKEY_ID, withdraw.data, [*withdraw.accounts[:5], AccountMeta(c.payer.pubkey(), False, False)])
    assert c.refused([verify, fake]) == (2, E["E_ACCOUNTS"])
    assert c.send([verify, withdraw]), c.err


def _precompile(records: list[tuple], body: bytes) -> Instruction:
    """A precompile instruction written by hand: one record of seven u16 per signature, then `body`."""
    return Instruction(pk.SECP256R1_ID, bytes([len(records), 0]) + b"".join(v.to_bytes(2, "little") for r in records for v in r) + body, [])


def test_a_precompile_instruction_that_checks_bytes_elsewhere_is_refused(w: World):
    """The precompile can take the key, the signature and the message each from another instruction. So an
    instruction can verify one thing while its own data shows another where a careless reader would look. Each
    decoy below is accepted by the runtime (what it points at is a good signature) and refused by Withdraw."""
    c, thief, ME = w.c, Passkey(9), 0xFFFF
    withdraw = lambda amount, cdj: pk.withdraw_ix(w.p.key, w.mint, w.to, amount, 1, cdj)  # noqa: E731
    # a thief signs this wallet's withdrawal with his own key; instruction 1 is his honest check: key at 16, signature at 49
    auth, cdj, sig = thief.get(pk.challenge(w.p.wallet, w.mint, w.to, 5_000_000, 1))
    message = auth + hashlib.sha256(cdj).digest()
    honest = pk.secp256r1_ix(thief.key, sig, message)
    raw, n = pk.raw_signature(sig), len(message)
    decoys = {"the key is read from instruction 1": _precompile([(49, ME, 16, 1, 113, n, ME)], w.p.key + raw + message),
              "the signature is read from instruction 1": _precompile([(49, 1, 16, ME, 113, n, ME)], thief.key + bytes(64) + message),
              "both are": _precompile([(49, 1, 16, 1, 113, n, ME)], w.p.key + bytes(64) + message)}
    for name, decoy in decoys.items():
        assert c.send([honest, decoy]), (name, c.err)
        assert c.refused([honest, decoy, withdraw(5_000_000, cdj)]) == (3, E["E_PRECOMPILE"]), name
    # the wallet's own passkey signed a withdrawal of 0.000001; the decoy verifies that message (in instruction 1) and
    # shows, in its own data, a message for 50.00 that nobody signed
    small = w.p.get(pk.challenge(w.p.wallet, w.mint, w.to, 1, 1))
    signed = small[0] + hashlib.sha256(small[1]).digest()
    big = client_data_json(pk.challenge(w.p.wallet, w.mint, w.to, 50_000_000, 1))
    shown = small[0] + hashlib.sha256(big).digest()
    honest = pk.secp256r1_ix(w.p.key, small[2], signed)
    decoy = _precompile([(49, ME, 16, ME, 113, len(signed), 1)], w.p.key + pk.raw_signature(small[2]) + shown)
    assert c.send([honest, decoy]), c.err
    assert c.refused([honest, decoy, withdraw(50_000_000, big)]) == (3, E["E_PRECOMPILE"])
    # an instruction that verifies two signatures, both this passkey's and both good: only exactly one is read
    auth, cdj, sig = w.p.get(pk.challenge(w.p.wallet, w.mint, w.to, 5_000_000, 1))
    message = auth + hashlib.sha256(cdj).digest()
    record = (30 + 33, ME, 30, ME, 30 + 33 + 64, len(message), ME)
    two = _precompile([record, record], w.p.key + pk.raw_signature(sig) + message)
    assert c.send([two]), c.err
    assert c.refused([two, withdraw(5_000_000, cdj)]) == (2, E["E_PRECOMPILE"])
    assert w.state() == (100_000_000, 0, 0)
    assert c.send([pk.secp256r1_ix(w.p.key, sig, message), withdraw(5_000_000, cdj)]), c.err


def test_a_high_s_signature_is_refused_and_the_client_lowers_it(w: World):
    c = w.c
    auth, cdj, der = w.p.get(pk.challenge(w.p.wallet, w.mint, w.to, 5_000_000, 1), high_s=True)
    r, s = utils.decode_dss_signature(der)
    assert s > pk.N // 2
    message = auth + hashlib.sha256(cdj).digest()
    low = pk.secp256r1_ix(w.p.key, der, message)
    assert int.from_bytes(bytes(low.data)[16 + 33 + 32:16 + 33 + 64], "big") == pk.N - s
    high = Instruction(pk.SECP256R1_ID, bytes(low.data)[:16 + 33] + r.to_bytes(32, "big") + s.to_bytes(32, "big") + message, [])
    withdraw = pk.withdraw_ix(w.p.key, w.mint, w.to, 5_000_000, 1, cdj)
    # the precompile's own instruction refuses it, so Withdraw never runs (its own check, E_HIGH_S, is tested in webauthn.rs)
    assert c.refused([high, withdraw]) == (1, 2)
    assert w.state() == (100_000_000, 0, 0)
    assert c.send([low, withdraw]), c.err                                # the same assertion with s lowered, as raw_signature does
    assert w.state() == (95_000_000, 5_000_000, 1)


def test_what_webauthn_requires_of_the_assertion(w: World):
    c = w.c
    ch = pk.challenge(w.p.wallet, w.mint, w.to, 5_000_000, 1)
    assert c.refused(w.ixs(flags=UV)) == (2, E["E_PRESENT"])             # verified, but nobody reported present
    assert c.refused(w.ixs(flags=0)) == (2, E["E_PRESENT"])
    assert c.refused(w.ixs(client_data=client_data_json(ch, "webauthn.create"))) == (2, E["E_CLIENT_DATA"])   # a registration, not a signature
    assert c.refused(w.ixs(client_data=b'{"challenge":"' + pk.b64url(ch).encode() + b'"}')) == (2, E["E_CLIENT_DATA"])
    assert c.refused(w.ixs(client_data=json.dumps({"type": "webauthn.get", "challenge": pk.b64url(ch) + "A"}).encode())) == (2, E["E_CHALLENGE"])
    assert c.refused(w.ixs(client_data=json.dumps({"type": "webauthn.get", "challenge": ch.hex()}).encode())) == (2, E["E_CHALLENGE"])
    # a signed message too short to be authenticator data and a hash
    short = hashlib.sha256(client_data_json(ch)).digest()
    assert c.refused([pk.secp256r1_ix(w.p.key, w.p.sign(short), short), pk.withdraw_ix(w.p.key, w.mint, w.to, 5_000_000, 1, client_data_json(ch))]) \
        == (2, E["E_MESSAGE"])
    assert w.state() == (100_000_000, 0, 0)
    # present without verification is enough; the members of the client data may come in any order, with others beside them
    other = json.dumps({"origin": ORIGIN, "crossOrigin": False, "challenge": pk.b64url(ch), "topOrigin": {"a": ["}", 1]}, "type": "webauthn.get"}, indent=1).encode()
    assert c.send(w.ixs(flags=UP, client_data=other)), c.err
    assert w.state() == (95_000_000, 5_000_000, 1)


# -- the money --------------------------------------------------------------------------------------------------------
def test_only_the_wallets_own_token_account_of_the_mint_is_spent(w: World):
    c = w.c
    rich = c.pay(Keypair().pubkey(), w.mint, 500_000_000)                 # someone else's money
    other_mint = c.mint()
    of_other_mint = c.pay(w.p.wallet, other_mint, 100_000_000)
    auth, cdj, sig = w.p.get(pk.challenge(w.p.wallet, w.mint, w.to, 5_000_000, 1))
    for source in (rich, of_other_mint, w.to, w.mint):
        ixs = pk.withdraw_ixs(w.p.key, w.mint, w.to, 5_000_000, 1, auth, cdj, sig, from_token=source)
        assert c.refused(ixs) == (2, E["E_FROM"]), source
    assert c.refused(pk.withdraw_ixs(w.p.key, w.mint, w.to, 5_000_000, 1, auth, cdj, sig, token_program=TOKEN_2022)) == (2, E["E_MINT"])
    # more than the wallet holds: the token program refuses, and the nonce is not spent
    assert c.refused(w.ixs(amount=100_000_001))[0] == 2
    assert w.state() == (100_000_000, 0, 0) and c.balance(rich) == 500_000_000
    assert c.send(w.ixs(amount=100_000_000)), c.err                      # all of it
    assert w.state() == (0, 100_000_000, 1)


def test_token_2022_mints_only_with_extensions_on_the_list():
    me, none = bytes([9]) * 32, bytes(32)
    plain = World(TOKEN_2022)
    assert plain.c.send(plain.ixs()), plain.c.err
    assert plain.state() == (95_000_000, 5_000_000, 1)
    pointer = World(TOKEN_2022, [(64, bytes([39, 0]) + me + none)])     # MetadataPointer: on the list
    assert pointer.c.send(pointer.ixs()), pointer.c.err
    refused = {"a permanent delegate": [(32, bytes([35]) + me)],
               "a transfer hook that only names an authority": [(64, bytes([36, 0]) + me + none)],
               "a transfer fee of nothing": [(108, bytes([26, 0, 0, 0]) + (0).to_bytes(2, "little") + (0).to_bytes(8, "little"))],
               "after one that is on the list": [(64, bytes([39, 0]) + me + none), (32, bytes([35]) + me)]}
    for name, extensions in refused.items():
        x = World(TOKEN_2022, extensions)
        assert x.c.refused(x.ixs()) == (2, E["E_MINT"]), name
        assert x.state() == (100_000_000, 0, 0)


# -- Open -------------------------------------------------------------------------------------------------------------
def test_open_creates_the_wallet_once_for_any_key_and_only_at_its_own_address():
    c, p = Chain(), Passkey(4)
    payer = c.payer.pubkey()
    assert pk.wallet(p.spki) == pk.wallet(p.point) == pk.wallet(p.key) == p.wallet and pk.compressed(p.spki) == p.key
    sent = c.svm.minimum_balance_for_rent_exemption(0)                   # lamports sent to the address before it exists
    assert c.send([transfer(TransferParams(from_pubkey=payer, to_pubkey=p.wallet, lamports=sent))]), c.err
    assert c.send([pk.open_ix(payer, p.key)]), c.err
    d = c.data(p.wallet)
    assert len(d) == pk.WALLET_LEN and d[0] == 1 and d[2:35] == p.key and d[35:] == bytes(13)
    assert Pubkey.create_program_address([b"pk", hashlib.sha256(p.key).digest(), bytes([d[1]])], pk.PASSKEY_ID) == p.wallet
    assert c.svm.get_account(p.wallet).owner == pk.PASSKEY_ID and c.lamports(p.wallet) == c.svm.minimum_balance_for_rent_exemption(pk.WALLET_LEN)
    assert c.send([pk.open_ix(payer, p.key)]) and c.data(p.wallet) == d and c.said("knosp:") == []     # again: nothing changes
    # another key's address, a key that is not a compressed point, a payer that did not sign
    q = Passkey(5)
    at = lambda key, wallet, who=payer: Instruction(pk.PASSKEY_ID, b"\x00" + key, [AccountMeta(who, who == payer, True), AccountMeta(wallet, False, True),  # noqa: E731
                                                                                   AccountMeta(pk.SYSTEM, False, False)])
    assert c.refused([at(q.key, p.wallet)]) == (1, E["E_ACCOUNTS"])
    assert c.refused([at(q.key, q.wallet, Keypair().pubkey())]) == (1, E["E_ACCOUNTS"])
    assert c.refused([at(b"\x04" + q.key[1:], q.wallet)]) == (1, E["E_KEY"])
    assert c.refused([at(q.key[:32], q.wallet)]) == (1, E["E_KEY"]) and c.refused([at(q.point, q.wallet)]) == (1, E["E_KEY"])
    assert c.data(q.wallet) is None
    # a withdrawal from a wallet that was never opened
    mint = c.mint()
    c.pay(q.wallet, mint, 1_000_000)
    to = c.pay(Keypair().pubkey(), mint, 0)
    assert c.refused(pk.withdraw_ixs(q.key, mint, to, 1, 1, *q.get(pk.challenge(q.wallet, mint, to, 1, 1)))) == (2, E["E_WALLET"])


# -- the client and the IDL against the source ------------------------------------------------------------------------
def test_the_client_reads_keys_and_signatures_as_a_browser_gives_them():
    p = Passkey(6)
    assert len(p.spki) == 91 and len(p.point) == 65 and pk.compressed(p.point) == pk.compressed(p.key) == p.key
    for bad in (b"", p.key[:32], b"\x05" + p.key[1:], p.spki[:-1], b"\x00" * 65):
        with pytest.raises(ValueError):
            pk.compressed(bad)
    der = p.sign(b"m", high_s=True)
    r, s = utils.decode_dss_signature(der)
    raw = pk.raw_signature(der)
    assert raw == r.to_bytes(32, "big") + (pk.N - s).to_bytes(32, "big") and pk.raw_signature(raw) == raw
    assert pk.raw_signature(r.to_bytes(32, "big") + s.to_bytes(32, "big")) == raw
    for bad in (b"", der[:-1], der + b"\x00", b"\x31" + der[1:], bytes(64), b"\xff" * 64):
        with pytest.raises(ValueError):
            pk.raw_signature(bad)
    half = bytes(int(x, 16) for x in re.search(r"HALF_N: \[u8; 32\] = \[(.*?)\];", SRC["webauthn.rs"], re.S).group(1).replace(",", " ").split())
    assert int.from_bytes(half, "big") == pk.N // 2
    assert pk.challenge(Pubkey(bytes([1]) * 32), Pubkey(bytes([2]) * 32), Pubkey(bytes([3]) * 32), 5_000_000, 1) == hashlib.sha256(
        b"knos-passkey" + bytes([1]) * 32 + bytes([2]) * 32 + bytes([3]) * 32 + (5_000_000).to_bytes(8, "little") + (1).to_bytes(8, "little")).digest()
    assert set(pk.ERRORS) | set(pf.ERRORS) == set(E.values()) and re.search(r'DOMAIN: &\[u8\] = b"knos-passkey"', SRC["lib.rs"])
    assert re.search(r'SECP256R1_ID: Pubkey = pubkey!\("(\w+)"\)', SRC["lib.rs"]).group(1) == str(pk.SECP256R1_ID)


def test_the_idl_says_what_the_source_and_the_client_do():
    idl = json.loads((ROOT / "idl" / "knos_passkey.json").read_text(encoding="utf-8"))
    ids = json.loads((ROOT / "programs-v2" / "program_ids.json").read_text())
    assert set(idl) == {"version", "name", "docs", "instructions", "accounts", "errors", "metadata"}
    assert idl["metadata"] == {"origin": "shank", "address": ids["knos_passkey"]} == {"origin": "shank", "address": str(pk.PASSKEY_ID)}
    assert json.loads((ROOT / "src" / "knos" / "settle" / "v2" / "program_ids.json").read_text()) == ids
    # every instruction of the source, with its tag; every account of each builder, with its flags, in order
    tags = {name: int(tag) for tag, name in re.findall(r"//!   (\d+) (\w+) +\S", SRC["lib.rs"])}
    assert tags == {"Open": 0, "Withdraw": 1, "Fund": 2}
    assert {i["name"]: i["discriminant"]["value"] for i in idl["instructions"]} == tags
    assert sorted(int(t) for t in re.findall(r"^        (\d+) => \w+\(program_id", SRC["lib.rs"], re.M)) == sorted(tags.values())
    p, payer, mint, to = Passkey(6), Pubkey(bytes([1]) * 32), Pubkey(bytes([2]) * 32), Pubkey(bytes([3]) * 32)
    cdj = client_data_json(bytes(32))
    inner = bytes([pf.FUND_ORDER_WALLET]) + bytes(pf.FUND_MIN - 1) + b"{}"      # a FundOrderWallet's data: its tag, 157 bytes, the terms
    built = {"Open": (pk.open_ix(payer, p.key), {"key": p.key}),
             "Withdraw": (pk.withdraw_ix(p.key, mint, to, 7, 9, cdj), {"amount": 7, "nonce": 9, "clientDataJson": cdj}),
             "Fund": (pf.fund_ix(p.key, mint, inner, 77, 9, cdj), {"expirySlot": 77, "nonce": 9, "clientLen": len(cdj), "clientDataJson": cdj, "fundOrderWallet": inner})}
    size = lambda t: {"u8": 1, "u16": 2, "u64": 8}.get(t) if isinstance(t, str) else size(t["array"][0]) * t["array"][1]  # noqa: E731
    for i in idl["instructions"]:
        ix, args = built[i["name"]]
        assert set(i) == {"name", "docs", "accounts", "args", "discriminant"} and i["discriminant"]["type"] == "u8"
        assert [(a["isSigner"], a["isMut"]) for a in i["accounts"]] == [(a.is_signer, a.is_writable) for a in ix.accounts], i["name"]
        data, at = bytes(ix.data), 1
        assert data[0] == i["discriminant"]["value"]
        for a in i["args"]:
            # `bytes` runs to the end of the data, except Fund's clientDataJson, which the clientLen before it measures
            n = size(a["type"]) if a["type"] != "bytes" else args["clientLen"] if "clientLen" in args and a["name"] == "clientDataJson" else len(data) - at
            want = args[a["name"]]
            assert data[at:at + n] == (want.to_bytes(n, "little") if isinstance(want, int) else want), a["name"]
            at += n
        assert at == len(data)
    names = {"wallet": p.wallet, "from": ata(p.wallet, mint), "mint": mint, "to": to, "tokenProgram": TOKEN, "instructions": pk.INSTRUCTIONS}
    withdraw = next(i for i in idl["instructions"] if i["name"] == "Withdraw")
    assert [names[a["name"]] for a in withdraw["accounts"]] == [a.pubkey for a in built["Withdraw"][0].accounts]
    order = pf.order_of(p.wallet, inner)
    names |= {"order": order, "ov": pay.ov_pda(order), "payAuth": pay.auth_pda(), "systemProgram": pay.SYSTEM, "pause": pay.pause_pda(), "knosPay": pay.PAY_ID}
    fund = next(i for i in idl["instructions"] if i["name"] == "Fund")
    assert [names[a["name"]] for a in fund["accounts"]] == [a.pubkey for a in built["Fund"][0].accounts]
    # the wallet account's layout against the source's offsets and the client's reader
    (wallet,) = idl["accounts"]
    offsets, at = {}, 0
    for f in wallet["type"]["fields"]:
        offsets[f["name"]] = at
        at += size(f["type"])
    consts = {n: int(v) for n, v in re.findall(r"pub const (W_\w+|WALLET_LEN): usize = (\d+);", SRC["lib.rs"])}
    assert at == consts["WALLET_LEN"] == pk.WALLET_LEN
    assert (offsets["version"], offsets["bump"], offsets["key"], offsets["nonce"]) == (consts["W_VERSION"], consts["W_BUMP"], consts["W_KEY"], consts["W_NONCE"])
    raw = bytearray(at); raw[0] = 1; raw[offsets["key"]:offsets["key"] + 33] = p.key; raw[offsets["nonce"]:] = (41).to_bytes(8, "little")
    assert pk.read_wallet(bytes(raw)) == pk.Wallet(key=p.key, nonce=41)
    # every error code of the source, and no other
    assert {e["code"]: e["name"] for e in idl["errors"]} == {code: "".join(part.title() for part in name[2:].split("_")) for name, code in E.items()}
    assert set(pk.ERRORS) | set(pf.ERRORS) == set(E.values()) and set(pf.ERRORS) == {E["E_EXPIRED"], E["E_FUND"]}
    assert idl["version"] == re.search(r'^version = "([\d.]+)"', (ROOT / "programs-v2" / "knos_passkey" / "Cargo.toml").read_text(), re.M).group(1)


# -- the JavaScript client ----------------------------------------------------------------------------------------------
FIXTURES = ROOT / "sdk" / "settle" / "passkey.fixtures.json"


def _new_inputs() -> dict:
    """Inputs for a new fixture file: one passkey, one assertion with a HIGH s (so both clients must lower it), and
    the registration it came from as a browser reports it."""
    p = Passkey(0x4B6E6F73)
    seeds = {name: bytes([n]) * 32 for name, n in (("payer_seed", 21), ("mint_seed", 22), ("owner_seed", 23))}
    mint, owner = Keypair.from_seed(seeds["mint_seed"]).pubkey(), Keypair.from_seed(seeds["owner_seed"]).pubkey()
    auth, cdj, der = p.get(pk.challenge(p.wallet, mint, ata(owner, mint), 25_000_000, 1), high_s=True)
    # the registration: authenticator data with the attested credential (COSE key), and the attestation object around it
    cred = bytes(range(16))
    cose = bytes.fromhex("a5010203262001215820") + p.point[1:33] + bytes.fromhex("225820") + p.point[33:]
    reg = hashlib.sha256(RP_ID.encode()).digest() + bytes([0x45]) + bytes(4) + bytes(16) + len(cred).to_bytes(2, "big") + cred + cose
    att = bytes.fromhex("a363666d74646e6f6e656761747453746d74a068617574684461746158") + bytes([len(reg)]) + reg
    return {**{k: v.hex() for k, v in seeds.items()}, "spki": p.spki.hex(), "point": p.point.hex(), "amount": 25_000_000, "nonce": 1,
            "authenticator_data": auth.hex(), "client_data_json": cdj.decode(), "signature_der": der.hex(),
            "registration_authenticator_data": reg.hex(), "attestation_object": att.hex(), "credential_id": cred.hex(), "rp_id": RP_ID}


def test_the_bytes_the_javascript_client_is_held_to_are_the_python_clients_and_they_withdraw_on_chain():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "passkey_fixtures.py"), "--check"], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr or r.stdout
    given = json.loads(FIXTURES.read_text(encoding="utf-8"))
    i = given["inputs"]
    pub = serialization.load_der_public_key(bytes.fromhex(i["spki"]))
    auth, cdj, der = bytes.fromhex(i["authenticator_data"]), i["client_data_json"].encode(), bytes.fromhex(i["signature_der"])
    pub.verify(der, auth + hashlib.sha256(cdj).digest(), ec.ECDSA(hashes.SHA256()))      # a real assertion of that key
    assert utils.decode_dss_signature(der)[1] > pk.N // 2 and int(given["raw_signature"][64:], 16) <= pk.N // 2
    # the four instructions, exactly as the file has them (and as passkey.js builds them), in one transaction
    c = Chain()
    payer = Keypair.from_seed(bytes.fromhex(i["payer_seed"]))
    c.svm.airdrop(payer.pubkey(), 10 ** 9)
    mint = c.mint(at=Keypair.from_seed(bytes.fromhex(i["mint_seed"])))
    assert str(mint) == given["mint"]
    source = c.pay(Pubkey.from_string(given["wallet"]), mint, 100_000_000)
    ixs = [Instruction(Pubkey.from_string(x["program"]), bytes.fromhex(x["data"]),
                       [AccountMeta(Pubkey.from_string(a["pubkey"]), a["signer"], a["writable"]) for a in x["accounts"]])
           for x in (given["ixs"][name] for name in ("open", "create_ata", "secp256r1", "withdraw"))]
    assert c.send(ixs, payer=payer), c.err
    assert str(source) == given["from"] and (c.balance(source), c.balance(Pubkey.from_string(given["to"]))) == (75_000_000, 25_000_000)


def test_the_withdrawal_request_is_one_format_for_the_site_and_the_relay():
    """`request` and `request_line` of the fixture are what the site's line builder is held to (sdk/settle/passkey.test.mjs:
    withdrawRequest, withdrawLine) and what the relay reads: the same bytes, written by either side."""
    from knos.proof import ghrelay
    given = json.loads(FIXTURES.read_text(encoding="utf-8"))
    i = given["inputs"]
    key, mint, to = bytes.fromhex(given["key"]), Pubkey.from_string(given["mint"]), Pubkey.from_string(given["to"])
    auth, cdj, der = bytes.fromhex(i["authenticator_data"]), i["client_data_json"].encode(), bytes.fromhex(i["signature_der"])
    assert pk.request(bytes.fromhex(i["spki"]), mint, to, i["amount"], i["nonce"], auth, cdj, der) == given["request"]
    assert pk.request_line(key, mint, to, i["amount"], i["nonce"], auth, cdj, der) == given["request_line"] == f"knos-withdraw: {given['request']}"
    want = pk.Request(key, mint, to, i["amount"], i["nonce"], auth, cdj, bytes.fromhex(given["raw_signature"]))
    for text in (given["request"], given["request_line"], given["request"].replace("+", "-").replace("/", "_").rstrip("="), given["request_line"].encode()):
        assert pk.read_request(text) == want
    assert [str(ix.program_id) for ix in pk.withdraw_ixs(want.key, want.mint, want.to, want.amount, want.nonce, want.authenticator_data, want.client_data_json,
                                                          want.signature)] == [given["ixs"]["secp256r1"]["program"], given["ixs"]["withdraw"]["program"]]
    # the public worker finds exactly that text in the comment the site's link opens, and hands it to the relay
    comment = {"body": f"{given['request_line']}\n", "issue_url": "https://api.github.com/repos/alice/knos-claim/issues/1", "user": {"login": "alice"}}
    assert [(f[0], f[2]) for f in ghrelay.tokens([comment])] == [("withdraw", given["request"])]
    # and the site's one line builder is the SDK's (web/claim.js adds nothing of its own to the bytes)
    claim = (ROOT / "web" / "claim.js").read_text(encoding="utf-8")
    assert "const comment = passkey.withdrawLine({ key: me.key, mint: MINT, to, amount, nonce, assertion });" in claim
    assert not re.search(r"WITHDRAW_PREFIX|parseWithdrawComment|BigUint64", claim) and re.findall(r"^export .*", claim, re.M) == ["export function initClaim(ctx) {"]
    assert 'export const WITHDRAW_PREFIX = "knos-withdraw:";' in (ROOT / "sdk" / "settle" / "passkey.js").read_text(encoding="utf-8") and pk.REQUEST_PREFIX == "knos-withdraw:"


def test_the_javascript_client_passes_its_own_checks():
    node = shutil.which("node")
    if not node:
        pytest.skip("needs node")
    r = subprocess.run([node, str(ROOT / "sdk" / "settle" / "passkey.test.mjs")], capture_output=True, text=True, timeout=120, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert re.search(r"sdk/settle/passkey: \d+ checks", r.stdout), r.stdout
    assert 'await import("./passkey.test.mjs");' in (ROOT / "sdk" / "settle" / "test.mjs").read_text(encoding="utf-8")   # what CI runs
    assert 'cp sdk/settle/passkey.js "$out/passkey.js"' in (ROOT / "scripts" / "build_site.sh").read_text(encoding="utf-8")


if __name__ == "__main__":
    # --new: a new passkey and a new signed assertion for sdk/settle/passkey.fixtures.json (scripts/passkey_fixtures.py builds the rest)
    assert "--new" in sys.argv, "python tests/test_passkey_chain.py --new"
    sys.path.insert(0, str(ROOT / "scripts"))
    import passkey_fixtures
    passkey_fixtures.write(_new_inputs())
    print(f"wrote {FIXTURES}")
