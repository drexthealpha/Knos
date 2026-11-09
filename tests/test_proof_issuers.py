"""Pay after proof from any source (knos_pay 0.3.34) in LiteSVM, on the 0.3.34 test build of knos_pay
(tests/fixtures/knos_pay_v2_0334_test.so) beside the committed test build of knos_oidc.

The Confidential Space and ORCID tokens here are signed by TEST issuer keys (generated per test, registered for the
issuers' real URLs through knos-oidc's attested path: the rotate workflow names the key, the guardian approves it,
a day passes). Google and ORCID sign the real ones; nothing here is a real Google or ORCID token. Synthetic data.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from _order import USDC, OrderChain, code
from _pay2 import GUARDIAN
from _settle import modulus, sign_jwt

from knos.proof import issuers as iss
from knos.settle.v2 import oidc, pay

E_ACCOUNTS, E_TERMS, E_STATE, E_TOKEN, E_CLAIMS, E_WORKFLOW, E_AUD, E_REPLAY = 80, 81, 83, 84, 85, 86, 87, 91
BUILD = "knos_pay_v2_0334_test.so"
IMAGE = hashlib.sha256(b"knos test judge image").digest()           # a container image digest the order pins (synthetic)
EVIDENCE = hashlib.sha256(b"synthetic dataset v1").digest()          # what the judge or the referees looked at (synthetic)
ORCID = "0000-0002-1825-0097"                                        # ORCID's own example iD (Josiah Carberry)
TERMS = pay.terms_json({"accept": "", "checks": [], "mode": "tests", "v": 2})

pytestmark = pytest.mark.skipif(not (Path(__file__).parent / "fixtures" / BUILD).is_file(), reason=f"tests/fixtures/{BUILD} is not built")


def chain() -> OrderChain:
    return OrderChain(pay_build=BUILD)


class IssuerKey:
    """A TEST key registered in knos-oidc for a real issuer URL, the attested way, or as a PRIVATE key of `private`."""
    def __init__(self, c: OrderChain, url: str, private: Keypair | None = None):
        self.c, self.url, self.k = c, url, rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.n, p = modulus(self.k), c.payer.pubkey()
        self.who = private.pubkey() if private else None
        self.key = oidc.key_pda(url, self.n, registrant=self.who)
        if private is not None:
            assert c.send([oidc.register_private_key_ix(self.who, url, self.n)], private), c.err
            assert c.send([oidc.key_params_ix(self.who, url, self.n, registrant=self.who)], private), c.err
            return
        tok = c.attest(url, self.n)
        assert c.send([oidc.register_issuer_key_ix(p, url, self.n, tok, c.key_of(tok))]) and c.send([oidc.key_params_ix(p, url, self.n)]), c.err
        assert c.send([oidc.approve_ix(GUARDIAN.pubkey(), url, self.n)], signers=[GUARDIAN]), c.err
        c.warp(oidc.KEY_DELAY)

    def token(self, claims: dict) -> Pubkey | None:
        c = self.c
        tid = c.write(sign_jwt(self.k, claims))
        for sq in oidc.step_plan(self.n.bit_length()):
            if not c.send([oidc.step_ix(c.payer.pubkey(), tid, self.key, sq)]):
                return None
        return oidc.token_pda(c.payer.pubkey(), tid)


def fund(c: OrderChain, topic: str, **kind) -> Pubkey:
    t = iss.topic_id(topic)
    ix = iss.fund_order_judged_ix(c.funder.pubkey(), c.funder_tok, c.usdc, t, 1, 20 * USDC, TERMS, **kind)
    assert c.send([ix], c.funder, tag="fund_order_judged"), c.err
    return ix.accounts[1].pubkey


def tokens(c: OrderChain, account: Pubkey) -> int:
    d = c.data(account)
    return int.from_bytes(d[64:72], "little") if d and len(d) >= 72 else 0


# == ATTESTED: a Confidential Space container pinned by its image digest ==============================================
def test_a_confidential_space_token_of_the_pinned_image_pays_the_order_and_nothing_else_does():
    c = chain()
    google = IssuerKey(c, iss.CS_ISSUER)
    order = fund(c, "cs-1", image_digest=IMAGE)
    o = c.order(order)
    assert iss.judge_of(c.data(order)) == (iss.ATTESTED, IMAGE) and o.wf_repo_hash == bytes(32) and o.mode == 1
    assert c.said("knos3:judge")[0] == f"knos3:judge order={order} kind=1 pin={IMAGE.hex()}"
    wallet = Keypair().pubkey()
    payees = [(ORCID, 10_000, wallet)]
    aud = iss.proof_audience(order, EVIDENCE, o.terms, payees)
    claims = lambda **over: {**iss.cs_claims(IMAGE, aud, c.now()), **over}  # noqa: E731
    pay_with = lambda tok: c.send([iss.pay_order_proof_ix(c.payer.pubkey(), tok, google.key, order, o, payees, used=pay.used_pda(c.data(tok)))])  # noqa: E731

    # another image, a debug image, a plain VM, a shielded VM, another order or other terms in the audience, an hour and a second
    other = claims()
    other["submods"] = {**other["submods"], "container": {**other["submods"]["container"], "image_digest": "sha256:" + "00" * 32}}
    experimental = claims()
    experimental["submods"] = {**experimental["submods"], "confidential_space": {"support_attributes": ["EXPERIMENTAL"]}}
    for bad, want in [(other, E_WORKFLOW), (claims(dbgstat="enabled"), E_CLAIMS), (claims(swname="GCE"), E_CLAIMS), (experimental, E_CLAIMS),
                      (claims(hwmodel="GCP_SHIELDED_VM"), E_CLAIMS), (claims(aud=iss.proof_audience(Keypair().pubkey(), EVIDENCE, o.terms, payees)), E_AUD),
                      (claims(aud=aud.replace(o.terms.hex(), "ab" * 32)), E_AUD), (claims(exp=c.now() + 3601), E_TOKEN)]:
        tok = google.token(bad)
        assert tok is not None, c.err
        assert not pay_with(tok) and code(c) == want, (want, c.err)
    # a GitHub token on this order: refused at the door (its family is not Confidential Space)
    gh = c.gh(aud)
    assert not c.send([pay.pay_order_ix(c.payer.pubkey(), gh, c.key, order, o, [(iss.orcid_id(ORCID), wallet)])]) and code(c) == E_TOKEN
    assert c.order(order).paid == 0

    good = google.token(claims())
    assert pay_with(good), c.err
    c.cu.setdefault("pay_order_attested", []).append(c.last_cu)
    assert c.order(order) is None and tokens(c, pay.ata(wallet, c.usdc)) == 20 * USDC
    assert c.said("knos3:settled")[0].endswith("judge=5") and c.said("knos3:proof")[0].endswith("image=sha256:" + IMAGE.hex())
    assert f"payee={iss.orcid_id(ORCID)}" in c.said("knos3:paid")[0]
    # REPLAY: the same token, on an order funded again at the same address, is refused by its marker
    assert fund(c, "cs-1", image_digest=IMAGE) == order
    assert not c.send([iss.pay_order_proof_ix(c.payer.pubkey(), good, google.key, order, c.order(order), payees, used=pay.used_pda(c.data(good)))])
    assert code(c) == E_REPLAY


def test_a_confidential_space_token_pays_no_forge_order_and_a_private_key_under_googles_url_is_not_google():
    c = chain()
    google = IssuerKey(c, iss.CS_ISSUER)
    impostor = IssuerKey(c, iss.CS_ISSUER, private=c.owner)       # a wallet registers "Google's" URL itself: still PRIVATE
    forge = c.fund_wallet()
    fo = c.order(forge)
    wallet = Keypair().pubkey()
    tok = google.token(iss.cs_claims(IMAGE, pay.order_pay_audience(forge, "a" * 40, fo.terms, fo.mode, 7, [(5, 10_000, wallet)]), c.now()))
    assert not c.send([pay.pay_order_ix(c.payer.pubkey(), tok, google.key, forge, fo, [(5, wallet)])]) and code(c) == E_TOKEN
    order = fund(c, "cs-2", image_digest=IMAGE)
    o = c.order(order)
    payees = [(5, 10_000, wallet)]
    fake = impostor.token(iss.cs_claims(IMAGE, iss.proof_audience(order, EVIDENCE, o.terms, payees), c.now()))
    assert fake is not None
    assert not c.send([iss.pay_order_proof_ix(c.payer.pubkey(), fake, impostor.key, order, o, payees, used=pay.used_pda(c.data(fake)))])
    assert code(c) == E_TOKEN


# == PANEL: m of n referee signatures over one verdict ================================================================
def vsend(c: OrderChain, ixs, **kw) -> bool:
    """A verdict as a relay sends it: PayOrder with data reads no token, so the harness must not add a token's marker."""
    return c.send(ixs, mark=False, **kw)


def referees(n: int) -> list[Keypair]:
    return [Keypair() for _ in range(n)]


def keys_of(panel: list[Keypair]) -> list[bytes]:
    return [bytes(k.pubkey()) for k in panel]


def verdict(c: OrderChain, order: Pubkey, panel: list[Keypair], m: int, signers: list[Keypair], payees, evidence: bytes = EVIDENCE,
            sign_for: Pubkey | None = None, o: pay.Order | None = None):
    """[precompile, PayOrder with data] (payees) or [precompile, RefundOrder with data] (payees == "FAIL")."""
    o = o or c.order(order)
    signed_o = c.order(sign_for) if sign_for else o
    digest = iss.verdict_digest(sign_for or order, signed_o, evidence, payees)
    pre = iss.ed25519_ix([(bytes(k.pubkey()), bytes(k.sign_message(digest))) for k in signers], digest)
    if payees == "FAIL":
        return [pre, iss.refund_order_verdict_ix(c.payer.pubkey(), order, o, m, keys_of(panel), evidence)]
    return [pre, iss.pay_order_verdict_ix(c.payer.pubkey(), order, o, m, keys_of(panel), evidence, payees)]


def test_two_of_three_referees_release_an_order_and_one_or_the_same_one_twice_does_not():
    c = chain()
    panel = referees(3)
    order = fund(c, "panel-1", panel=(2, keys_of(panel)))
    assert iss.judge_of(c.data(order)) == (iss.PANEL, iss.panel_pin(2, keys_of(panel)))
    wallet = Keypair().pubkey()
    payees = [(ORCID, 6_000, wallet), (77, 4_000, Keypair().pubkey())]
    # DUPLICATE SIGNER and BELOW THRESHOLD: one referee twice in one transaction counts once; recorded, nothing moves
    assert vsend(c, verdict(c, order, panel, 2, [panel[0], panel[0]], payees), tag="verdict_record_1_of_2"), c.err
    assert c.said("knos3:verdict")[0].endswith("have=1 of=2") and c.order(order).paid == 0 and tokens(c, pay.ov_pda(order)) == 20 * USDC + 60_000
    digest = iss.verdict_digest(order, c.order(order), EVIDENCE, payees)
    assert iss.read_vote(c.data(iss.vote_pda(order, digest)))["bits"] == 0b001
    # REPLAY of the same referee in another transaction: nothing new
    assert not vsend(c, verdict(c, order, panel, 2, [panel[0]], payees)) and code(c) == E_REPLAY
    # a key outside the panel: no signature over THIS digest by the panel
    assert not vsend(c, verdict(c, order, panel, 2, [Keypair()], payees)) and code(c) == E_CLAIMS
    # another evidence is another verdict: its own tally, 1 of 2, nothing paid
    assert vsend(c, verdict(c, order, panel, 2, [panel[1]], payees, evidence=bytes(32))), c.err
    assert c.order(order).paid == 0
    # another panel than the one pinned (m changed): refused
    assert not vsend(c, verdict(c, order, panel, 1, [panel[1]], payees)) and code(c) == E_CLAIMS
    # the second distinct referee: paid, 60/40
    assert vsend(c, verdict(c, order, panel, 2, [panel[2]], payees), tag="verdict_pay_2_of_2"), c.err
    assert c.order(order) is None and tokens(c, pay.ata(wallet, c.usdc)) == 12 * USDC
    assert c.said("knos3:settled")[0].endswith("judge=6")


def test_one_signature_per_transaction_fits_a_cluster_and_m_in_one_pays_at_once():
    c = chain()
    panel = referees(3)
    wallet = Keypair().pubkey()
    payees = [(ORCID, 10_000, wallet)]
    order = fund(c, "panel-2", panel=(2, keys_of(panel)))
    # one referee per transaction: under the 1,232 bytes a v0 transaction may have, with a 3-key panel and one payee
    assert vsend(c, verdict(c, order, panel, 2, [panel[0]], payees)) and c.size <= 1232, (c.err, c.size)
    assert vsend(c, verdict(c, order, panel, 2, [panel[2]], payees)) and c.size <= 1232, (c.err, c.size)
    assert tokens(c, pay.ata(wallet, c.usdc)) == 20 * USDC
    # m in one transaction pays at once; LiteSVM does not hold a transaction to 1,232 bytes, a cluster does: two
    # signatures with one payee are over it, so they go one per transaction (or in a v1 transaction)
    other = fund(c, "panel-3", panel=(2, keys_of(panel)))
    assert vsend(c, verdict(c, other, panel, 2, [panel[0], panel[1]], payees), tag="verdict_pay_2_in_one_tx"), c.err
    assert c.size > 1232 and c.order(other) is None


def test_a_fail_verdict_refunds_the_funder_and_a_verdict_pays_only_its_own_order_and_funding():
    c = chain()
    panel = referees(2)
    a, b = fund(c, "panel-a", panel=(2, keys_of(panel))), fund(c, "panel-b", panel=(2, keys_of(panel)))
    payees = [(77, 10_000, Keypair().pubkey())]
    # WRONG ORDER: signed for a, shown for b
    assert not vsend(c, verdict(c, b, panel, 2, [panel[0]], payees, sign_for=a)) and code(c) == E_CLAIMS
    # FAIL: one referee is recorded; the second refunds b to the funder now, before its deadline
    before = tokens(c, c.funder_tok)
    assert vsend(c, verdict(c, b, panel, 2, [panel[0]], "FAIL"), tag="verdict_fail_record"), c.err
    assert c.order(b) is not None and c.said("knos3:verdict")[0].startswith(f"knos3:verdict order={b} verdict=FAIL")
    assert vsend(c, verdict(c, b, panel, 2, [panel[1]], "FAIL"), tag="verdict_fail_refund"), c.err
    assert c.order(b) is None and tokens(c, c.funder_tok) == before + 20 * USDC + 60_000
    # a PASS tally and a FAIL tally are different verdicts: one referee's PASS and another's FAIL pay nothing
    assert vsend(c, verdict(c, a, panel, 2, [panel[0]], payees)), c.err
    assert vsend(c, verdict(c, a, panel, 2, [panel[1]], "FAIL")), c.err
    assert c.order(a).paid == 0 and c.order(a).state == "open"
    # REPLAY across fundings: a is refunded at its deadline and funded again at the same address; the old signatures
    # name the old funding's stamp
    old = c.order(a)
    kept = verdict(c, a, panel, 2, [panel[0], panel[1]], payees, o=old)
    c.warp(14 * 86_400 + 1)
    assert not vsend(c, verdict(c, a, panel, 2, [panel[1]], payees)) and code(c) == E_STATE       # past the deadline
    assert c.send([pay.refund_order_ix(c.payer.pubkey(), a, old)]), c.err
    assert fund(c, "panel-a", panel=(2, keys_of(panel))) == a and c.order(a).stamp != old.stamp
    assert not vsend(c, [kept[0], iss.pay_order_verdict_ix(c.payer.pubkey(), a, c.order(a), 2, keys_of(panel), EVIDENCE, payees)]) and code(c) == E_CLAIMS
    # a PANEL order takes no token through PayOrder, and a forge order no verdict
    assert not c.send([pay.pay_order_ix(c.payer.pubkey(), c.gh("x"), c.key, a, c.order(a), [(77, payees[0][2])])]) and code(c) == E_CLAIMS
    forge = c.fund_wallet()
    assert not vsend(c, verdict(c, forge, panel, 2, [panel[0]], payees)) and code(c) == E_CLAIMS


def test_what_a_judged_order_cannot_be_funded_with():
    c = chain()
    keys = keys_of(referees(3))
    ix = iss.fund_order_judged_ix(c.funder.pubkey(), c.funder_tok, c.usdc, iss.topic_id("bad"), 1, 20 * USDC, TERMS, panel=(2, keys))

    def with_byte(at: int, value: int) -> Instruction:
        d = bytearray(bytes(ix.data)); d[at] = value
        return Instruction(ix.program_id, bytes(d), list(ix.accounts))
    opts_at = 1 + 37
    # a forge option on a judged order (NEUTRAL, a holdback), mode 0, an unknown judge, the byte before the judge
    for at, value in [(opts_at, pay.F_NEUTRAL), (opts_at + 1, 100), (1 + 24, 0), (opts_at + 35, 3), (opts_at + 34, 1)]:
        assert not c.send([with_byte(at, value)], c.funder) and code(c) == E_TERMS, (at, value, c.err)
    with pytest.raises(ValueError):
        iss.panel_bytes(4, keys)
    with pytest.raises(ValueError):
        iss.panel_bytes(1, [keys[0], keys[0]])
    assert c.send([ix], c.funder), c.err


# == ORCID: a researcher's iD paid at a wallet ========================================================================
def test_an_orcid_sign_in_to_knos_binds_the_id_and_a_verdict_pays_it_there():
    c = chain()
    orcid = IssuerKey(c, iss.ORCID_ISSUER)
    wallet = Keypair()
    tok = orcid.token(iss.orcid_claims(ORCID, iss.TEST_ORCID_CLIENT, wallet.pubkey(), c.now()))
    assert tok is not None, c.err
    bind = lambda t: iss.bind_orcid_ix(c.payer.pubkey(), t, orcid.key, ORCID, pay.used_pda(c.data(t)))  # noqa: E731
    # another site's ORCID client chose its own nonce: binds nothing
    other = orcid.token(iss.orcid_claims(ORCID, "APP-SOMEONEELSE00001", Keypair().pubkey(), c.now()))
    assert not c.send([bind(other)]) and code(c) == E_AUD
    assert c.send([bind(tok)], tag="bind_orcid"), c.err
    assert pay.read_bind(c.data(pay.bind_pda(iss.orcid_id(ORCID)))).wallet == wallet.pubkey()
    assert c.said("knos3:bound")[0] == f"knos3:bound orcid={iss.orcid_id(ORCID) - iss.OR_BASE} wallet={wallet.pubkey()}"
    used = c.data(pay.used_pda(c.data(tok)))
    assert int.from_bytes(used[33:41], "little", signed=True) >= c.now() + iss.ORCID_LIFE      # kept while the token can be fresh
    # the same sign-in again: refused
    assert not c.send([bind(tok)]) and code(c) == E_REPLAY
    # a verdict names the iD with "-": paid at the bound wallet
    panel = referees(1)
    order = fund(c, "orcid-panel", panel=(1, keys_of(panel)))
    payees = [(ORCID, 10_000, None)]
    o = c.order(order)
    digest = iss.verdict_digest(order, o, EVIDENCE, payees)
    pre = iss.ed25519_ix([(bytes(panel[0].pubkey()), bytes(panel[0].sign_message(digest)))], digest)
    assert vsend(c, [pre, iss.pay_order_verdict_ix(c.payer.pubkey(), order, o, 1, keys_of(panel), EVIDENCE, payees, wallets=[wallet.pubkey()])],
                  tag="verdict_pay_orcid_bound"), c.err
    assert tokens(c, pay.ata(wallet.pubkey(), c.usdc)) == 20 * USDC


def test_a_github_bind_is_what_it_was():
    """Bind (8) with a GitHub claim token still binds a GitHub id, through the same instruction ORCID now uses."""
    from _pay2 import TEST_CLAIM_SHA
    c = chain()
    wallet = Keypair().pubkey()
    tok = c.gh(pay.bind_audience(wallet), file="claim.yml", wf_repo="drexthealpha/knos-oidc-rotate", wf_sha=TEST_CLAIM_SHA,
               event_name="workflow_dispatch", repository="mona/knos-claim", actor_id="1234567", repository_owner_id="1234567")
    assert c.send([pay.bind_ix(c.payer.pubkey(), tok, c.key, 1234567, used=pay.used_pda(c.data(tok)))]), c.err
    assert pay.read_bind(c.data(pay.bind_pda(1234567))).wallet == wallet and c.said("knos2:bound")


def test_the_client_numbers_orcid_ids_as_the_program_does():
    assert iss.orcid_id("0000-0002-1825-0097") == 10 ** 18 + 21_825_009 and iss.orcid_id("0000-0002-1694-233X") == 10 ** 18 + 21_694_233
    assert iss.orcid_of(iss.orcid_id("0000-0002-1694-233X")) == "0000-0002-1694-233X" and iss.orcid_of(77) is None
    for bad in ["0000-0002-1825-0098", "0000000218250097", "0000-0002-1825-009"]:
        with pytest.raises(ValueError):
            iss.orcid_id(bad)
    assert iss.bind_nonce("W") == "knos3:bind:W" and 0 < iss.topic_id("x") < 10 ** 18
    assert len(iss.proof_audience(Pubkey.default(), bytes(32), bytes(32), [(ORCID, 2500, Keypair().pubkey())] * 4).encode()) <= 512
