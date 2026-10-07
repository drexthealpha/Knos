"""A quorum, the presentation grace and the upgrade between them, from the comment to the program through the relay
(knos.flow, knos.settle.v2.relay, the knos_pay builds in LiteSVM).

The public program ids run knos_pay 2.1 until the upgrade to 2.2 executes, so the relay meets both and decides by the
Version the cluster answers:

  - 2.2 counts judges by the owner of the repository each ran in. Two judges of one owner move nothing, and the
    comment on the pull request says why; two owners pay. Under 2.1 the same two tokens paid: what 0.3.17 did.
  - A judge's word recorded under 2.1 names no run. After the upgrade it counts for nothing: the relay says which
    judge has to sign again, and the order pays when he has.
  - Nothing is written for an order in the slot it was funded in (2.2): the relay keeps the token and carries it
    again, instead of calling it refused.
  - An order funded with the presentation grace takes a token issued by its deadline for two hours after it, and the
    refund sweep waits as long. 2.1 has no such option: the fund token is refused before any fee.

The funding comment goes through knos.flow against tests/_flow.py's GitHub; the options and the terms it signed are
then funded and judged on the real program by the real relay. Never run on devnet: these are tests."""
from __future__ import annotations

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from _flow import HUBOT, MONA, REPO_ID, World, check  # noqa: E402
from _order import OrderChain  # noqa: E402
from _pay21 import each_build, pay21_build  # noqa: E402, F401 - the fixtures `build` and `pay21`
from test_flow import BOUGHT, FAUCET, plain  # noqa: E402
from test_flow_quorum3 import JUDGE, said  # noqa: E402
from test_flow_quorum3 import world as quorum_world  # noqa: E402
from test_relay2 import JWKS, OWNER, REPO, USDC, Net, issue, order_fund_jwt, order_pay_jwt, user  # noqa: E402

from knos import flow  # noqa: E402
from knos.settle.v2 import order_auto, pay, relay  # noqa: E402

COMMENT = "/knos fund 20 checks: test quorum 2 judge: acme/judge neutral off"
OTHER = 9_000                                          # the account that owns the judge repository when it is nobody the order knows


def funded_by_the_comment(tmp_path, v: int) -> tuple[bytes, bytes]:
    """The funding comment through knos.flow: (the terms it logged, the 48 bytes of options its fund token signed)."""
    w = quorum_world(tmp_path / "fund")
    w.version = v
    said(w, 7, HUBOT, COMMENT)
    raw = w.chain.logs[str(pay.order_pda(pay.scope_of(REPO_ID, 7), FAUCET, 0))]
    options = bytes.fromhex(w.signer.asked[0].split(":")[9])
    assert options == pay.opts(order_auto.quorum_flags(2), reserve_days=7, judge_repo_id=JUDGE["id"])
    return raw, options


def on_chain(build) -> tuple[OrderChain, Net]:
    c = OrderChain(pay_build=build.build)
    return c, Net(c)


def carry(env, jwt: str, terms: bytes | None = None) -> dict:
    c, net = env
    return relay.submit(net, c.payer, jwt, terms, JWKS, now=c.now())


def order_of(env, raw: bytes, options: bytes, **kw) -> Pubkey:
    c, _net = env
    r = carry(env, order_fund_jwt(c, issue(), options=options, terms=raw, **kw), raw)
    assert r["ok"], r
    return Pubkey.from_string(r["order"])


def own(c, order: Pubkey, payees, raw: bytes, **over) -> str:
    """The order's own repository's run (its owner is the harness's OWNER)."""
    return order_pay_jwt(c, order, payees, terms=raw, **over)


def named(c, order: Pubkey, payees, raw: bytes, owner: int) -> str:
    """A run in the judge repository the comment named, which `owner` owns."""
    return order_pay_jwt(c, order, payees, terms=raw, file="attest.yml", event_name="push", repository_id=JUDGE["id"], repository_owner_id=owner)


def the_comment(tmp_path, v: int, r: dict) -> str:
    """What knos.flow writes on the merged pull request when the relay answers `r` for its pay token."""
    w = World(tmp_path / "said")
    w.version = v
    w.hub.issue(7, "Slugify keeps punctuation.")
    w.hub.required = [{"context": "test", "integration_id": 15368}]
    address = w.chain.order(7, 20_000_000, BOUGHT, flags=pay.F_FAUCET | order_auto.quorum_flags(2))
    w.clock.sleep(3600)
    w.hub.checks[w.hub.pull(12, MONA, "Fixes #7")["head"]["sha"]] = [check("test"), check("build")]
    w.chain.bind(MONA)
    w.relay.submit = lambda *a, **kw: {**r, "order": str(address)}
    assert flow.settle(w.run(w.hub.merge(12))) == 0
    return plain(w.hub.knos(12)[-1], 4000)


def test_two_judges_of_one_owner_move_nothing_and_the_comment_says_why_and_two_owners_pay(tmp_path, build):
    raw, options = funded_by_the_comment(tmp_path, build.v)
    env = c, net = on_chain(build)
    assert relay.version(net, c.payer) == build.pick(1, 2)
    wallet = Keypair().pubkey()
    payees = [(user(), 10_000, wallet)]
    got = lambda: c.balance(pay.ata(wallet, c.usdc)) if c.data(pay.ata(wallet, c.usdc)) is not None else 0  # noqa: E731

    # -- one owner: the order's own repository, and a judge repository that the same account owns
    order = order_of(env, raw, options)
    r = carry(env, own(c, order, payees, raw))
    assert r["ok"] and r["paid"] == [] and r["quorum"] == {"have": 1, "of": 2} and got() == 0, r
    r = carry(env, named(c, order, payees, raw, OWNER))
    if not build.new:       # 2.1 counted markers, whoever ran them: the same two tokens paid, as they did under 0.3.17
        assert r["ok"] and "quorum" not in r and got() == 20 * USDC and c.order(order) is None, r
    else:
        why = "the judge repository has the same owner as another judge that passed this commit, and runs in repositories of one owner are one judge"
        assert r["ok"] and r["paid"] == [] and r["quorum"] == {"have": 1, "of": 2, "uncounted": [why]}, r
        o = c.order(order)
        assert got() == 0 and (o.state, o.paid, c.held(order)) == ("open", 0, 20 * USDC + 60_000)        # nothing moved: the amount and its fee wait
        # the same reader again changes nothing, by anyone's relay
        again = carry(env, named(c, order, payees, raw, OWNER))
        assert again["ok"] and again["quorum"]["have"] == 1 and got() == 0 and c.order(order).state == "open", again
        text = the_comment(tmp_path, build.v, r)
        assert text.startswith("Knos: not paid yet. ") and "1 of the 2 different judges its funder asked for have passed this commit" in text, text
        assert f"It counts 1 because {why}." in text and "received" not in text
        assert "someone who is not its funder and owns no repository that judged it runs `knos settle --neutral" in text

    # -- two owners: the judge repository belongs to an account that is neither side's. The second word pays, in full
    order = order_of(env, raw, options)
    before = got()
    r = carry(env, own(c, order, payees, raw))
    assert r["ok"] and r["quorum"] == {"have": 1, "of": 2} and got() == before, r
    assert "It counts" not in the_comment(tmp_path / "first", build.v, r)
    r = carry(env, named(c, order, payees, raw, OTHER))
    assert r["ok"] and "quorum" not in r and [p["amount"] for p in r["paid"]] == [20 * USDC], r
    assert got() - before == 20 * USDC and c.order(order) is None


def test_a_judges_word_recorded_before_the_upgrade_counts_for_nothing_and_the_relay_says_who_signs_again(tmp_path, pay21):
    raw, options = funded_by_the_comment(tmp_path, 1)
    c = OrderChain(pay_build=pay21)                                     # the build that is live
    env = c, net = c, Net(c)
    relay.forget()
    try:
        wallet = Keypair().pubkey()
        payees = [(user(), 10_000, wallet)]
        order = order_of(env, raw, options)
        r = carry(env, own(c, order, payees, raw))
        marker = order_auto.q_pda(order, 0)
        assert relay.version(net, c.payer) == 1 and r["ok"] and r["quorum"] == {"have": 1, "of": 2} and len(c.data(marker)) == order_auto.Q_LEN_21, r
        # the upgrade executes: the same address runs 2.2. A relay learns it when its next pass begins
        c.svm.add_program_from_file(pay.PAY_ID, str(Path_of("knos_pay_v2_test.so")))
        relay.forget(net)
        assert relay.version(net, c.payer) == 2 and c.order(order).inc == 0     # the order was funded under 2.1: no incarnation
        # the second judge, of another owner. Under 2.1 this token would have paid; now the first word names no run
        r = carry(env, named(c, order, payees, raw, OTHER))
        assert r["ok"] and r["paid"] == [] and r["quorum"] == {"have": 1, "of": 2, "again": ["the order's own repository"]}, r
        assert c.order(order).state == "open" and c.data(pay.ata(wallet, c.usdc)) is None and len(c.data(marker)) == order_auto.Q_LEN_21
        text = the_comment(tmp_path, 2, r)
        assert ("The order's own repository passed this commit before the escrow's upgrade to knos_pay 2.2, and a word recorded before it names "
                "no run, so it counts for nothing now: that judge signs again (run its workflow once more) and is counted then.") in text, text
        assert text.startswith("Knos: not paid yet. ") and "1 of the 2 different judges" in text
        # it signs again: a new run, a new token. Now two owners have passed the same commit, and the order pays
        r = carry(env, own(c, order, payees, raw))
        assert r["ok"] and "quorum" not in r and c.balance(pay.ata(wallet, c.usdc)) == 20 * USDC and c.order(order) is None, r
        # the two markers are the relay's to close, whichever build wrote them: the 2.1 one was never rewritten
        lengths = sorted(len(c.data(order_auto.q_pda(order, k)) or b"") for k in range(3))
        assert lengths == [0, order_auto.Q_LEN_21, order_auto.Q_LEN]
        assert len(relay.close_markers(net, c.payer, c.now())) == 1 and all(c.data(order_auto.q_pda(order, k)) is None for k in range(3))
    finally:
        relay.forget()


def Path_of(name: str):
    from _settle import FIX
    return FIX / name


def test_a_word_in_the_slot_of_the_funding_is_carried_again_and_not_called_refused(tmp_path, build):
    if not build.new:
        pytest.skip("knos_pay 2.1 has no incarnation: it writes a marker in any slot")
    raw, options = funded_by_the_comment(tmp_path, build.v)
    env = c, net = on_chain(build)
    wallet = Keypair().pubkey()
    payees = [(user(), 10_000, wallet)]
    order = order_of(env, raw, options)
    first = own(c, order, payees, raw)
    funded_in = c.order(order).inc - 1
    slots = c.svm._svm                  # tests/_pay2.py's _Slots, under the lock tests/test_relay2.py's Net put around it

    def hold() -> None:                 # the chain's slot stands still: every transaction lands in the slot of the funding
        clock = slots._inner.get_clock()
        clock.slot = funded_in
        slots._inner.set_clock(clock)
    slots._next = hold
    try:
        r = carry(env, first)
    finally:
        del slots._next
    assert r == {"ok": False, "kind": "pay", "retry": True, "transient": True, "answered": True, "wait": 1,
                 "why": "the order was funded in this very block, and its first payment or judge's word is taken from the next one on; "
                        "the same token is carried again on the next pass"}, r
    assert c.data(order_auto.q_pda(order, 0)) is None and c.data(pay.used_pda(first)) is None        # nothing was written: the token is whole
    r = carry(env, first)               # the next pass, a block later
    assert r["ok"] and r["quorum"] == {"have": 1, "of": 2}, r
    # every other 83 stays a refusal: an order past its deadline is known from a read and costs nothing
    c.warp(15 * 86_400)
    late = carry(env, named(c, order, payees, raw, OTHER))
    assert not late["ok"] and "retry" not in late and "the order's deadline has passed" in late["why"], late


def test_an_order_with_the_grace_takes_a_token_issued_by_its_deadline_and_is_not_refunded_before(build):
    env = c, net = on_chain(build)
    graced = pay.opts(grace=True)
    if not build.new:       # 2.1 refuses the byte (the program: E_TERMS); the relay says so before any fee
        txs = net.txs
        r = carry(env, order_fund_jwt(c, issue(), options=graced, work=600), relay2_terms())
        assert not r["ok"] and "which the escrow on this cluster does not have yet: it comes with the announced upgrade to knos_pay 2.2" in r["why"], r
        assert net.txs == txs
        return
    terms = relay2_terms()
    fund = lambda options: Pubkey.from_string(carry(env, order_fund_jwt(c, issue(), options=options, work=600), terms)["order"])  # noqa: E731
    order, plain_order, unproven = fund(graced), fund(None), fund(graced)
    o = c.order(order)
    assert (o.grace, o.pay_until - o.deadline) == (True, pay.GRACE) == (True, 7_200) and not c.order(plain_order).grace
    wallet, cranker = Keypair().pubkey(), c.fund()
    payees = [(user(), 10_000, wallet)]
    c.warp(o.deadline - c.now() - 1)
    in_time = order_pay_jwt(c, order, payees)                   # GitHub issued it a second before the deadline
    c.warp(c.order(unproven).deadline - c.now() + 100)          # and it is shown after every one of the three deadlines
    late = order_pay_jwt(c, order, payees, pr=8)                # this one was issued after the deadline
    # the sweep sends back the order with no grace, and leaves both graced ones alone: a refund now would be refused (83)
    sent = relay.refund_orders_due(net, cranker, c.now())
    assert len(sent) == 1 and c.order(plain_order) is None and c.order(order) is not None and c.order(unproven) is not None
    txs = net.txs
    r = carry(env, late)
    assert not r["ok"] and net.txs == txs and r["why"].startswith("the order's deadline has passed, and this token was issued after it"), r
    r = carry(env, in_time)                                     # late, and in time: carried and paid in full
    assert r["ok"] and [p["amount"] for p in r["paid"]] == [20 * USDC] and c.balance(pay.ata(wallet, c.usdc)) == 20 * USDC and c.order(order) is None, r
    # the order nobody proved goes back when its grace is over, and not a second before
    end = c.order(unproven).pay_until
    c.warp(end - c.now())
    assert relay.refund_orders_due(net, cranker, c.now()) == [] and c.order(unproven) is not None
    c.warp(1)
    bal = c.balance(pay.baltok_pda(c.bal))
    assert len(relay.refund_orders_due(net, cranker, c.now())) == 1 and c.order(unproven) is None
    assert c.balance(pay.baltok_pda(c.bal)) - bal == 20 * USDC + 60_000        # the amount and the fee its funder paid on top


def relay2_terms() -> bytes:
    from test_relay2 import TERMS
    return TERMS


def test_the_fakes_and_the_harness_agree_on_who_owns_the_orders_repository():
    """The one-owner case above rests on it: the harness's own run is signed for the owner the Balance is of."""
    from _pay2 import github_claims
    assert int(github_claims()["repository_owner_id"]) == OWNER and int(github_claims()["repository_id"]) == REPO
