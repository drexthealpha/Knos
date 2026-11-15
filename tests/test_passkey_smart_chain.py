"""A passkey signs a buyer's pre-order and a maker's sale of a receivable, inside LiteSVM, with the bytes deployed on
devnet: LazorKit's smart wallet (tests/thirdparty/lazorkit_devnet_FLb7.so, dumped from FLb7fyAtkfA4TSa2uYcAT8QKHd2pkoMHgmqfnXFXo7ao)
beside the knos_pay test build of the 0.3.34 branch (knos_pay_v2_0334_test.so). Every assertion is a real P-256 ECDSA signature of a
software authenticator (tests/test_passkey_chain.py's `Passkey`), verified by LiteSVM's secp256r1 precompile; nobody
else's key moves the money. A relayer pays the fees and the rents. Synthetic test units."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from solders.instruction import AccountMeta, Instruction  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _order import USDC, OrderChain  # noqa: E402
from test_passkey_chain import RP_ID, Passkey  # noqa: E402

from knos import ideas  # noqa: E402
from knos.ideas import wanted as W  # noqa: E402
from knos.settle.v2 import passkey_fund as pf  # noqa: E402
from knos.settle.v2 import passkey_smart as ps  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
LAZOR_SO = Path(__file__).parent / "thirdparty" / "lazorkit_devnet_FLb7.so"   # not a Knos build: outside tests/fixtures, which CI rebuilds
LAZOR_SHA = "99a6911d77deaa35a9cf12d1e6cc5982d5e9e6cd466ad97be5fe88949053f430"   # the devnet executable, dumped 2026-10-17


class Holder:
    """One person's passkey and the LazorKit wallets it owns (one per purpose)."""
    def __init__(self, seed: int):
        self.p = Passkey(seed)
        self.cred = hashlib.sha256(b"credential %d" % seed).digest()      # sha256(credential id)

    def wallet(self, purpose: str = "main", extra: bytes = b"") -> Pubkey:
        return ps.wallet_pda(ps.user_seed(purpose, self.cred, extra))

    def vault(self, purpose: str = "main", extra: bytes = b"") -> Pubkey:
        return ps.vault_pda(self.wallet(purpose, extra))

    def authority(self, purpose: str = "main", extra: bytes = b"") -> Pubkey:
        return ps.authority_pda(self.wallet(purpose, extra), self.cred)[0]


class World(OrderChain):
    def __init__(self):
        super().__init__(pay_build="knos_pay_v2_0334_test.so")
        assert hashlib.sha256(LAZOR_SO.read_bytes()).hexdigest() == LAZOR_SHA
        self.svm.add_program_from_file(ps.LAZOR_ID, str(LAZOR_SO))
        self.relayer = self.fund(10)

    def open(self, h: Holder, purpose: str = "main", extra: bytes = b"") -> Pubkey:
        ix = ps.create_wallet_ix(self.relayer.pubkey(), ps.user_seed(purpose, h.cred, extra), h.cred, h.p.key, RP_ID)
        assert self.send([ix], self.relayer), self.err
        return h.vault(purpose, extra)

    def counter(self, authority: Pubkey) -> int:
        return ps.read_authority(self.data(authority)).counter

    tables: list

    def make_table(self, addresses: list[Pubkey]) -> None:
        """A lookup table of the relayer's, made with the lookup table program's own instructions."""
        sysvar = Pubkey.from_string("SysvarS1otHashes111111111111111111111111111")
        hashes = self.data(sysvar) or b""
        if not (len(hashes) >= 48 and int.from_bytes(hashes[:8], "little")):   # this LiteSVM keeps no SlotHashes: write recent slots in
            from solders.account import Account
            top = self.slot()
            raw = (64).to_bytes(8, "little") + b"".join((top - i).to_bytes(8, "little") + bytes(32) for i in range(64))
            self.svm.set_account(sysvar, Account(lamports=10 ** 9, data=raw + bytes(20_488 - len(raw)),
                                                 owner=Pubkey.from_string("Sysvar1111111111111111111111111111111111111"), executable=False))
            hashes = raw
        if not hasattr(self, "tables"):
            self.tables = []
        recent = int.from_bytes(hashes[8 + 40 * len(self.tables):16 + 40 * len(self.tables)], "little")
        alt, ixs = ps.create_table_ixs(self.relayer.pubkey(), self.relayer.pubkey(), recent, addresses)
        assert self.send(ixs, self.relayer), self.err
        c = self.svm.get_clock(); c.slot += 2; self.svm.set_clock(c)       # a table serves from the slot after its extension
        assert ps.read_table(self.data(alt)) == addresses
        self.tables.append((alt, addresses))

    def table(self, mint: Pubkey, *holders: "Holder") -> None:
        self.make_table(ps.table_addresses(pay.PAY_ID, mint))
        for h in holders:
            self.make_table(ps.wallet_table_addresses(h.wallet(), h.cred, mint))

    def send_v0(self, ixs, payer: Keypair | None = None) -> bool:
        """A v0 transaction through the lookup tables, with no compute budget instruction: what the relay sends."""
        from solders.transaction import VersionedTransaction
        payer = payer or self.relayer
        tx = VersionedTransaction(ps.message_v0(payer.pubkey(), ixs, getattr(self, "tables", []), self.svm.latest_blockhash()), [payer])
        self.size = len(bytes(tx))
        r = self.svm.send_transaction(tx)
        self.svm.expire_blockhash()
        ok = "Failed" not in type(r).__name__
        self.err = None if ok else str(r.err())
        self.logs = list((r if ok else r.meta()).logs())
        return ok

    def approve(self, prep: ps.Prepared, h: Holder, mangle=None) -> bool:
        """The passkey signs the prepared challenge (its count predicted), the relayer sends: the rents a transaction
        earlier, then the precompile and the wallet's instruction in a v0 transaction."""
        prep.sign_count = h.p.count + 1
        auth, cdj, sig = h.p.get(prep.challenge)
        if mangle:
            auth, cdj, sig = mangle(auth, cdj, sig)
        ixs = prep.finish(auth, cdj, sig)
        if prep.pre:
            assert self.send(prep.pre, self.relayer), self.err
            ixs = ixs[len(prep.pre):]
        return self.send_v0(ixs)

    def execute(self, h: Holder, inner, purpose: str = "main", extra: bytes = b"", **kw) -> ps.Prepared:
        a = h.authority(purpose, extra)
        return ps.execute(self.relayer.pubkey(), h.wallet(purpose, extra), a, inner, slot=self.slot(), counter=self.counter(a) + 1,
                          rp_id=RP_ID, key=h.p.key, **kw)


def transfer_ix(src: Pubkey, mint: Pubkey, dst: Pubkey, owner: Pubkey, amount: int) -> Instruction:
    return Instruction(pay.TOKEN, bytes([12]) + amount.to_bytes(8, "little") + bytes([6]),
                       [AccountMeta(src, False, True), AccountMeta(mint, False, False), AccountMeta(dst, False, True), AccountMeta(owner, True, False)])


def tokens(c: World, account: Pubkey) -> int:
    d = c.data(account)
    return int.from_bytes(d[64:72], "little") if d and len(d) >= 72 else 0


def test_a_passkey_wallet_moves_tokens_only_on_its_own_fresh_assertion():
    c = World()
    buyer = Holder(31)
    vault = c.open(buyer)
    a = ps.read_authority(c.data(buyer.authority()))
    assert a.key == buyer.p.key and a.rp_id == RP_ID and a.counter == 0 and a.role == 0
    src = c.token_account(vault, c.usdc)
    c.mint_to(c.usdc, src, 50 * USDC)                       # the faucet: test units to the passkey's vault
    dst = c.token_account(Keypair().pubkey(), c.usdc)
    prep = c.execute(buyer, [transfer_ix(src, c.usdc, dst, vault, 7 * USDC)])
    assert c.approve(prep, buyer), c.err
    assert tokens(c, dst) == 7 * USDC and c.counter(buyer.authority()) == 1
    # the same assertion again: the odometer refuses it
    prep.sign_count = buyer.p.count + 1
    again = prep.finish(*buyer.p.get(prep.challenge))
    assert not c.send(again, c.relayer) and "3006" in str(c.err)
    # another passkey's signature over this wallet's challenge: refused
    other = Holder(32)
    prep = c.execute(buyer, [transfer_ix(src, c.usdc, dst, vault, 1 * USDC)])
    prep.sign_count = other.p.count + 1
    auth, cdj, sig = other.p.get(prep.challenge)
    ixs = prep.finish(auth, cdj, sig)
    ixs[-2] = ps.secp256r1_ix(other.p.key, sig, auth + hashlib.sha256(cdj).digest())
    assert not c.send(ixs, c.relayer)
    # a changed amount after signing: refused (the challenge covers the instructions)
    prep = c.execute(buyer, [transfer_ix(src, c.usdc, dst, vault, 1 * USDC)])
    prep.sign_count = buyer.p.count + 1
    signed = buyer.p.get(prep.challenge)
    tampered = c.execute(buyer, [transfer_ix(src, c.usdc, dst, vault, 40 * USDC)])
    tampered.sign_count, tampered.slot = prep.sign_count, prep.slot
    with pytest.raises(ValueError):
        tampered.finish(*signed)
    assert tokens(c, dst) == 7 * USDC


def test_a_mismatched_prediction_asks_for_one_more_touch():
    c = World()
    h = Holder(33)
    vault = c.open(h)
    src = c.token_account(vault, c.usdc)
    c.mint_to(c.usdc, src, 5 * USDC)
    prep = c.execute(h, [transfer_ix(src, c.usdc, c.token_account(Keypair().pubkey(), c.usdc), vault, USDC)])
    prep.sign_count = 0                                       # predicted a synced passkey; this one counts
    with pytest.raises(ps.Mismatch) as m:
        prep.finish(*h.p.get(prep.challenge))
    assert m.value.sign_count == h.p.count + 1 and m.value.flags == ps.UP | ps.UV


def _plan(units: int = 6):
    claim = ideas.claim("Pre-order for: a test product (Knos demand report)", field_name="Business, Management and Accounting", kind="person")
    return W.plan(claim, units=units, price=1, stages=[("referee_pass", 10_000)], stage_work_s=[30 * 86_400])


def _preorder(c: World, buyer: Holder, p, panel, mint):
    """The buyer's passkey signs FundOrderWallet (a PANEL order) as its vault; the relayer sends the rents first."""
    vault, tok = buyer.vault(), pay.ata(buyer.vault(), mint)
    fund = W.fund_panel_ix(p, "stage1", vault, tok, mint, 2, [bytes(k.pubkey()) for k in panel], unlisted_panel=True)
    order = W.panel_address(p, "stage1", vault)
    rent = pf.rent_ixs(c.relayer.pubkey(), order, pay.ov_pda(order), c.svm.minimum_balance_for_rent_exemption(pf.ORDER_LEN),
                       c.svm.minimum_balance_for_rent_exemption(165))
    prep = c.execute(buyer, [fund], pre=rent)
    return prep, order


def test_a_buyers_passkey_locks_a_panel_preorder_that_releases_to_the_makers_receivable_wallet_and_refunds_to_the_buyer():
    c = World()
    buyer, maker = Holder(41), Holder(42)
    vault = c.open(buyer)
    tok = c.token_account(vault, c.usdc)
    c.mint_to(c.usdc, tok, 50 * USDC)
    claim_bytes = b"claim-1"
    receivable = c.open(maker, "receivable", claim_bytes)     # the maker's wallet for this one receivable
    c.table(c.usdc, buyer)
    p = _plan()
    panel = [Keypair() for _ in range(3)]
    prep, order = _preorder(c, buyer, p, panel, c.usdc)
    assert c.approve(prep, buyer), c.err
    o = c.order(order)
    assert o is not None and o.amount == p["stage1"]["amount"] and tokens(c, tok) == 50 * USDC - o.amount - o.fee
    assert c.size <= 1182, c.size             # Solana's 1,232 less Knos's 50-byte margin
    # release: 2 of 3 referees sign PASS naming the receivable wallet; the program pays it
    _release(c, order, panel, [(_wallet_payee(receivable), 10_000, receivable)])
    assert tokens(c, pay.ata(receivable, c.usdc)) == p["stage1"]["amount"]


def _wallet_payee(addr: Pubkey) -> int:
    from knos.ideas import commit as C
    return C.wallet_payee_id(str(addr))


def _release(c: World, order: Pubkey, panel, payees, wallets=None) -> None:
    from knos.proof import issuers as iss
    ev = {"met": True, "evidence_hash": "ab" * 32, "oracle": "referee_pass"}
    keys = [bytes(x.pubkey()) for x in panel]
    for w in (c.relayer.pubkey(), pay.FEE_OWNER):            # the tip's and the fee's token accounts, as commit._settle makes them
        c.token_account(w, c.usdc)
    for k in panel[:2]:
        o = c.order(order)
        d = W.stage_digest(order, o, ev, payees)
        ixs = [iss.ed25519_ix([W.sign_stage(k, order, o, ev, payees)], d),
               iss.pay_order_verdict_ix(c.relayer.pubkey(), order, o, 2, keys, bytes.fromhex(ev["evidence_hash"]), payees, wallets=wallets)]
        assert c.send(ixs, c.relayer, mark=False), c.err
    assert c.order(order) is None


def _locked(c: World, buyer: Holder, payee_vault: Pubkey):
    c.table(c.usdc, buyer)
    tok = c.token_account(buyer.vault(), c.usdc)
    c.mint_to(c.usdc, tok, 50 * USDC)
    p, panel = _plan(), [Keypair() for _ in range(3)]
    prep, order = _preorder(c, buyer, p, panel, c.usdc)
    assert c.approve(prep, buyer), c.err
    return p, panel, order, tok


def test_past_its_deadline_the_preorder_goes_back_to_the_buyers_passkey_wallet():
    c = World()
    buyer, maker = Holder(43), Holder(44)
    c.open(buyer)
    receivable = c.open(maker, "receivable", b"claim-2")
    p, panel, order, tok = _locked(c, buyer, receivable)
    o = c.order(order)
    before = tokens(c, tok)
    c.warp(31 * 86_400)
    assert c.send([pay.refund_order_ix(c.relayer.pubkey(), order, o)], c.relayer), c.err
    assert tokens(c, tok) == before + o.amount + o.fee


def test_a_maker_sells_the_receivable_to_a_lender_and_the_release_pays_the_lender():
    """Factoring with what the deployed programs allow for a payee named by a wallet: the receivable is paid to a
    LazorKit wallet made for it alone; the maker's passkey hands that wallet's ownership to the lender's passkey
    (TransferOwnership), the lender's passkey pays the advance, and the release lands in the wallet the lender now
    owns. knos_pay's Assign is not used: it needs a Bind for the payee, and a wallet-only payee has none (E_PAYEE 88)."""
    c = World()
    buyer, maker, lender = Holder(45), Holder(46), Holder(47)
    c.open(buyer)
    rw = ps.user_seed("receivable", maker.cred, b"claim-3")
    receivable = c.open(maker, "receivable", b"claim-3")
    maker_main, lender_main = c.open(maker), c.open(lender)
    lender_tok = c.token_account(lender_main, c.usdc)
    c.mint_to(c.usdc, lender_tok, 20 * USDC)
    p, panel, order, _ = _locked(c, buyer, receivable)
    face = p["stage1"]["amount"]
    # what a lender checks first: the receivable wallet has one power over it, the maker's passkey
    found = [(Pubkey.default(), c.data(maker.authority("receivable", b"claim-3")))]
    assert ps.sole_owner(found, ps.wallet_pda(rw), maker.cred, c.slot())[0]
    # 1. the maker's passkey hands the receivable wallet to the lender's passkey
    w = ps.wallet_pda(rw)
    cur = maker.authority("receivable", b"claim-3")
    prep = ps.transfer_ownership(c.relayer.pubkey(), w, cur, lender.cred, lender.p.key, RP_ID, slot=c.slot(), counter=c.counter(cur) + 1,
                                 rp_id=RP_ID, key=maker.p.key)
    assert c.approve(prep, maker), c.err
    assert c.data(cur) is None                                   # the maker's authority is closed
    new = ps.authority_pda(w, lender.cred)[0]
    assert ps.sole_owner([(new, c.data(new))], w, lender.cred, c.slot())[0]
    # 2. the lender's passkey pays the advance (90% of face) to the maker's own wallet
    advance = face * 9 // 10
    maker_tok = c.token_account(maker_main, c.usdc)
    prep = c.execute(lender, [transfer_ix(lender_tok, c.usdc, maker_tok, lender_main, advance)])
    assert c.approve(prep, lender), c.err
    assert tokens(c, maker_tok) == advance
    # the maker's passkey can no longer move anything out of the receivable wallet
    c.token_account(receivable, c.usdc)
    stale = ps.execute(c.relayer.pubkey(), w, cur, [transfer_ix(pay.ata(receivable, c.usdc), c.usdc, maker_tok, receivable, 1)],
                       slot=c.slot(), counter=3, rp_id=RP_ID, key=maker.p.key)
    assert not c.approve(stale, maker)                           # its authority account is gone: LazorKit refuses
    # 3. the release pays the receivable wallet, which the lender's passkey now controls; the lender sweeps it
    _release(c, order, panel, [(_wallet_payee(receivable), 10_000, receivable)])
    rtok = pay.ata(receivable, c.usdc)
    assert tokens(c, rtok) == face
    a = ps.authority_pda(w, lender.cred)[0]
    prep = ps.execute(c.relayer.pubkey(), w, a, [transfer_ix(rtok, c.usdc, lender_tok, receivable, face)], slot=c.slot(),
                      counter=c.counter(a) + 1, rp_id=RP_ID, key=lender.p.key)
    assert c.approve(prep, lender), c.err
    assert tokens(c, lender_tok) == 20 * USDC - advance + face


def test_assign_works_once_the_payee_is_bound_and_its_bound_wallet_is_a_passkey_wallet():
    """knos_pay's own factoring instruction, for a payee the program can bind (a GitHub id, by the pinned claim
    workflow; here the test build's test key signs the claim token). The maker's bound wallet is the vault of a
    LazorKit wallet; its passkey signs Assign through Execute; the release pays the lender's wallet."""
    c = World()
    buyer, maker, lender = Holder(48), Holder(49), Holder(50)
    c.open(buyer)
    maker_vault, lender_vault = c.open(maker), c.open(lender)
    gid = 4_242_4242
    assert c.bind(gid, maker_vault), c.err
    p, panel, order, _ = _locked(c, buyer, maker_vault)
    asg = pay.assign_pda(order, gid)
    rent = pf.rent_ixs(c.relayer.pubkey(), asg, asg, c.svm.minimum_balance_for_rent_exemption(88), 0)[:1]
    prep = c.execute(maker, [pay.assign_ix(maker_vault, order, gid, lender_vault)], pre=rent)
    assert c.approve(prep, maker), c.err
    assert any("knos3:assigned" in x for x in c.logs)
    _release(c, order, panel, [(gid, 10_000, maker_vault)], wallets=[lender_vault])
    assert tokens(c, pay.ata(lender_vault, c.usdc)) == p["stage1"]["amount"]
