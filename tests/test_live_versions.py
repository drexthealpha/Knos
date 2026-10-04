"""knos_meter and knos_passkey 1.0 keep running until the proposals that upgrade them execute, so the 0.3.14 relay asks
each which build it is before it sends what only 1.1 has (knos.settle.v2.live): a batch for the meter, a passkey
wallet's Fund. On LiteSVM with the builds of this tree (1.1) nothing changes. Against a 1.0 program the answer is a
plain sentence with the date the upgrade executes, read from the upgrade multisig on the same cluster, and nothing is
sent.

The 1.0 program here is the 1.1 build behind a ledger that answers the version question as 1.0 does: "invalid
instruction data", in LiteSVM's words and in a cluster's. Those words were measured against the two programs as
0.3.13 deployed them (the builds at commit 567fd12, loaded into LiteSVM): knos_meter 1.0 refuses instruction 7, and
knos_passkey 1.0 instruction 2, with InvalidInstructionData; knos_passkey 1.1 answers the same probe with its error 110.
"""
from __future__ import annotations

import pytest

pytest.importorskip("solders.litesvm")

from solders.pubkey import Pubkey  # noqa: E402

from _meter import BUYER, SELLER, Meter  # noqa: E402
from _order import REPO, issue  # noqa: E402
from test_passkey_fund import World  # noqa: E402
from test_passkey_relay import Counted, comment  # noqa: E402
from test_relay2 import JWKS, Net, token  # noqa: E402
from test_site_recorded import vault_transaction_account  # noqa: E402
from test_upgrade_feed import IDS, world  # noqa: E402

from knos import chain  # noqa: E402
from knos.settle.v2 import live, meter, passkey, relay  # noqa: E402

LITESVM = "transaction failed: TransactionErrorInstructionError((1, Fieldless(InvalidInstructionData)))"
CLUSTER = "transaction failed: {'InstructionError': [0, 'InvalidInstructionData']}"
APPROVED = 1_791_300_000                      # when the proposals of this build were approved
BUFFER = IDS["fee_owner"]                     # any address: the proposal's buffer is not read here


def proposals(*rows) -> dict:
    """The upgrade multisig's accounts with these proposals: (index, status, program name)."""
    return world([(index, status, APPROVED, 2 if status == "Approved" else 1, vault_transaction_account(IDS[name], BUFFER)) for index, status, name in rows], {})


def old(base, program: Pubkey, words: str, accounts: dict):
    """`base` (a ledger class of the harness) for a cluster where `program` is still 1.0 and the upgrade multisig holds
    `accounts`: the version question is refused in `words`, everything else is the chain's own."""
    class Old(base):
        probes = 0

        def simulate(self, ixs, payer, signers=None, *a, **k):
            ixs = list(ixs)
            if len(ixs) == 1 and ixs[0].program_id == program and not ixs[0].accounts:
                Old.probes += 1
                raise chain.RpcError(words, {"err": {"InstructionError": [0, "InvalidInstructionData"]}, "logs": [f"Program {program} failed: invalid instruction data"]})
            return super().simulate(ixs, payer, signers, *a, **k)

        def infos(self, addresses):
            got = super().infos(addresses)
            return [(Pubkey.from_string(accounts[str(a)][0]), accounts[str(a)][1]) if str(a) in accounts else g for a, g in zip(addresses, got)]
    return Old


@pytest.fixture(autouse=True)
def asked_again():
    live._NEW.clear()
    yield
    live._NEW.clear()


def test_the_builds_of_this_tree_answer_as_1_1_and_are_asked_once():
    c = Meter()
    net = Net(c)
    assert live.runs(net, c.payer, "knos_meter") is True and live.needs(net, c.payer, "knos_meter") is None
    assert meter.VERSION == live.WANT["knos_meter"] == "1.1"
    w = World()
    led = Counted(w)
    assert live.runs(led, w.payer, "knos_passkey") is True and live.needs(led, w.payer, "knos_passkey") is None
    # once a program answered as the newer build it is not asked again: an upgrade is never undone
    led.simulate = None
    assert live.runs(led, w.payer, "knos_passkey") is True
    # a ledger that cannot simulate, or a cluster that did not answer, is no answer: nothing is refused on a guess
    live._NEW.clear()
    assert live.runs(led, w.payer, "knos_passkey") is None and live.needs(led, w.payer, "knos_passkey") is None

    def down(*a, **k):
        raise chain.RpcError("the cluster did not answer", None)
    led.simulate = down
    assert live.runs(led, w.payer, "knos_passkey") is None and live.runs(led, w.payer, "knos_meter") is None


@pytest.mark.parametrize("words", [LITESVM, CLUSTER])
def test_a_batch_against_knos_meter_1_0_is_refused_in_plain_words_with_the_date_and_nothing_is_sent(words):
    c = Meter()
    accounts = proposals((3, "Approved", "knos_oidc"), (4, "Approved", "knos_pay"), (5, "Approved", "knos_meter"), (6, "Approved", "knos_passkey"))
    net = old(Net, meter.METER_ID, words, accounts)(c)
    mint = c.new_mint()
    c.open(mint, BUYER, 500_000_000)
    month, root = meter.yyyymm(c.now()), bytes([7]) * 32
    for kind, owner in (("batch", BUYER), ("claim", SELLER)):
        aud = meter.batch_audience(BUYER, SELLER, month, 0, 10, 8, 16_000_000, root, kind)
        r = relay.submit(net, c.payer, token(c, aud, file="attest.yml", repository_owner_id=owner, run_attempt=1), None, JWKS, now=c.now())
        assert not r["ok"] and r["kind"] == kind and net.txs == 0, r
        when = live._when(APPROVED + 172_800)
        assert r["why"].startswith(f"this needs knos_meter 1.1, which executes on {when} or shortly after (proposal 5 of the upgrade multisig"), r["why"]
        assert "The cluster runs knos_meter 1.0 until then" in r["why"] and "Nothing was sent and nothing was charged" in r["why"]
        assert "invalid instruction" not in r["why"].lower() and "InstructionError" not in r["why"]         # not the program's raw refusal
    assert c.book() is None and c.book(claim=True) is None                # no Ledger account was written
    # the time lock is over and nobody executed yet: said so, not promised for a date that has passed
    late = live.needs(net, c.payer, "knos_meter", APPROVED + 172_800 + 60)
    assert late.startswith(f"this needs knos_meter 1.1, which could be executed since {when} and has not been yet (proposal 5")


def test_a_passkey_funding_against_knos_passkey_1_0_is_refused_in_plain_words_and_the_reply_says_when():
    w = World()
    n = issue()
    line = comment(w, n)
    accounts = proposals((5, "Approved", "knos_meter"), (6, "Approved", "knos_passkey"))
    net = old(Counted, passkey.PASSKEY_ID, CLUSTER, accounts)(w)
    before = (w.balance(w.source), w.lamports(w.payer.pubkey()), w.nonce())
    r = relay.passkey_fund(net, w.payer, line, REPO, n)
    assert not r["ok"] and r["kind"] == "passkey-fund" and getattr(net, "sent", 0) == 0, r
    assert r["why"].startswith(f"this needs knos_passkey 1.1, which executes on {live._when(APPROVED + 172_800)} or shortly after (proposal 6 of the upgrade multisig"), r["why"]
    assert "The cluster runs knos_passkey 1.0 until then" in r["why"] and "the chain would refuse it" not in r["why"]
    assert (w.balance(w.source), w.lamports(w.payer.pubkey()), w.nonce()) == before
    # the same line, once 1.1 runs (the harness's own build): funded
    done = relay.passkey_fund(Counted(w), w.payer, line, REPO, n)
    assert done["ok"] and w.nonce() == 1, done


def test_the_sentence_without_a_date_when_the_upgrade_is_not_approved_or_not_proposed():
    w = World()
    for accounts, words in ((proposals((6, "Active", "knos_passkey")), "which is proposed (proposal 6 of the upgrade multisig) and executes 48 hours after the members approve it"),
                            (proposals((2, "Cancelled", "knos_passkey"), (4, "Approved", "knos_pay")), "which is not on this cluster yet: no approved upgrade of it was found"),
                            ({}, "which is not on this cluster yet")):
        net = old(Counted, passkey.PASSKEY_ID, LITESVM, accounts)(w)
        said = live.needs(net, w.payer, "knos_passkey")
        assert said.startswith("this needs knos_passkey 1.1, " + words), said
    # of two approved proposals for one program the newer one is named (the older would be the one --replace withdraws)
    both = proposals((2, "Approved", "knos_passkey"), (6, "Approved", "knos_passkey"))
    assert live.executes(old(Counted, passkey.PASSKEY_ID, LITESVM, both)(w), "knos_passkey") == (APPROVED + 172_800, 6, True)


def test_what_both_builds_have_is_built_as_0_3_13_built_it():
    """The other half of "works with the old and the new one": the instructions 1.0 has are sent to either unchanged.
    Their tags are the ones 1.0's processor matches (0 to 4 for the meter, 0 and 1 for the passkey wallet)."""
    key = Pubkey.from_string(IDS["fee_owner"])
    assert meter.close_mark_ix(key, key).data == b"\x04" and meter.version_ix().data == b"\x07"
    assert passkey.open_ix(key, bytes([2]) + bytes(32)).data[:1] == b"\x00"
