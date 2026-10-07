"""The fee in one place (src/knos/fees.py), and that what a person is shown follows the build that is LIVE: the 0.3.14
fee while the cluster's knos_pay answers Version below 2 (or the upgrade feed has no executed proposal of knos_pay after
the 2.1 one), the 0.3.18 fee after. Both states are driven here with a ledger that answers as each build does."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("solders")

from knos import controls, fees  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402
from knos.settle.v2 import relay as relay2  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
USDC = 10 ** 6


class Answers:
    """A ledger whose knos_pay answers Version as build `said` does: a number is `knos2:version N`; None is the 2.0
    program, which refuses the instruction."""

    def __init__(self, said: int | None, url: str):
        self.said, self.url, self.asked = said, url, 0

    def simulate(self, ixs, payer, signers=None) -> list[str]:
        self.asked += 1
        assert [bytes(ix.data) for ix in ixs] == [b"\x0c"] and ixs[0].program_id == pay.PAY_ID      # Version, and nothing else
        if self.said is None:
            raise RuntimeError("InstructionError(0, InvalidInstructionData): invalid instruction data")
        return [f"Program {pay.PAY_ID} invoke [1]", f"Program log: knos2:version {self.said}", f"Program {pay.PAY_ID} success"]


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(relay2, "_VERSION", {})          # what a cluster answered is kept for the process: not across tests


def test_the_018_fee_is_one_rate_with_a_floor_and_is_pay_pys_own_numbers():
    new = fees.NEW
    assert (new.bps, new.floor, new.plan_min, new.tiers) == (pay.FEE_BPS, pay.FEE_MIN, 10, ()) == (30, 50_000, 10, ())
    # the price book's examples: 5.00 -> 0.05; 100.00 -> 0.30; 1,000.00 -> 3.00; 5,000.00 -> 15.00; 100,000.00 -> 300.00
    assert [new.order(a * USDC) for a in (5, 100, 1_000, 5_000, 100_000)] == [50_000, 300_000, 3_000_000, 15_000_000, 300_000_000]
    assert all(new.order(a) == max(50_000, a * 30 // 10_000) == pay.fee_of(a) for a in (5_000_000, 16_666_666, 16_666_667, 20_000_000, 999_999_999, 10 ** 11))
    assert [new.job(a) for a in (0, 1, 50_000, USDC, 20 * USDC)] == [0, 1, 50_000, 50_000, 60_000] and new.job(20 * USDC) == pay.fee_of(20 * USDC)
    assert new.order(5_000 * USDC, 10) == 5 * USDC and new.order(20 * USDC, 10) == 50_000          # a Plan lowers the one rate; the floor stays
    assert new.order(123_456_789, decimals=9) == max(123_456_789 * 30 // 10_000, 50_000_000)        # the floor is in whole units of the mint
    assert new.rate() == "0.30% of the amount, at least 0.05" and new.rate(10) == "0.10% of the amount, at least 0.05"


def test_the_014_fee_is_kept_exactly_as_the_public_program_charges_it():
    old = fees.OLD
    assert [old.order(a * USDC) for a in (5, 16, 100, 1_000, 5_000, 50_000, 100_000)] == [400_000, 400_000, 2_500_000, 25_000_000, 65_000_000, 515_000_000, 765_000_000]
    assert old.order(10 ** 12) == 5_265_000_000 and old.order(1_001 * USDC) == 25_010_000 and old.order(50_001 * USDC) == 515_005_000
    assert (old.order(100 * USDC, 50), old.order(5_000 * USDC, 50), old.order(50_000 * USDC, 50)) == (500_000, 45_000_000, 495_000_000)    # a Plan: the first tier only
    assert [old.job(a) for a in (0, 1, USDC, 20 * USDC)] == [0, 1, 50_000, 500_000]
    assert old.rate() == "2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40"


def test_a_plan_is_held_to_the_range_of_the_rule_in_force():
    plan = lambda bps, expires=10: pay.Plan(bps, 7, expires)      # noqa: E731
    assert [fees.NEW.plan_bps(plan(b), 5) for b in (5, 10, 20, 30, 100)] == [10, 10, 20, 30, 30]
    assert [fees.OLD.plan_bps(plan(b), 5) for b in (5, 50, 100, 250, 900)] == [50, 50, 100, 250, 250]
    assert fees.NEW.plan_bps(plan(10), 10) == 30 and fees.NEW.plan_bps(None, 0) == 30 and fees.OLD.plan_bps(plan(100), 10) == 250


@pytest.mark.parametrize("said, release", [(None, "0.3.14"), (0, "0.3.14"), (1, "0.3.14"), (2, "0.3.18"), (3, "0.3.18")])
def test_the_rule_follows_what_the_program_answers(said, release):
    ledger = Answers(said, f"test://pay-{said}")
    assert fees.live(ledger).release == release and fees.version(ledger) == (said or 0)
    assert fees.live(ledger).release == release and ledger.asked == 1          # asked once for each cluster and process


def test_budget_check_and_show_say_the_fee_of_the_live_build_on_both_sides_of_the_upgrade():
    """The same Balance and the same order, read from a cluster that runs knos_pay 2.1 and from one that runs 2.2."""
    balance = pay.Balance(False, 424242, pay.PAY_ID, pay.USDC_DEVNET, 0, 0, (), 0, False)
    said = {}
    for version in (1, 2):
        b = controls.Budget(pay.PAY_ID, balance, None, None, 1_000 * USDC, 6, 1_790_000_000, fees.live(Answers(version, f"test://budget-{version}")))
        d = controls.check(b, 987654321, 100 * USDC, 424242)
        said[version] = (d.fee, d.total, d.effective_pct, d.bps, [line.strip() for line in controls.show_lines(b) if "fee" in line])
    assert said[1][:4] == (2_500_000, 102_500_000, "2.50", 250) and said[2][:4] == (300_000, 100_300_000, "0.30", 30)
    assert said[1][4] == ["fee                  standard: 2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40 (no Plan)",
                          f"the 0.3.14 fee, which knos_pay 2.1 charges; from knos_pay 2.2: 0.30% of the amount, at least 0.05. {fees.KEEPS}",
                          "The limits count what leaves the Balance (amount and fee); the cap counts the amount."]
    assert said[2][4] == ["fee                  standard: 0.30% of the amount, at least 0.05 (no Plan)", f"the 0.3.18 fee, which knos_pay 2.2 charges. {fees.KEEPS}",
                          "The limits count what leaves the Balance (amount and fee); the cap counts the amount."]


def test_the_mcp_server_quotes_the_fee_of_the_live_build():
    from knos import mcp
    for version, fee in ((1, 500_000), (2, 60_000)):
        server = mcp.Server(ledger=Answers(version, f"test://mcp-{version}"), github=lambda path: {})
        assert server._fee(20 * USDC) == fee and server._fee(20 * USDC) == fee


def test_the_upgrade_feed_says_which_fee_for_whoever_asks_no_chain():
    entry = lambda index, program, status: {"index": index, "program": program, "status": status}      # noqa: E731
    feed = lambda *entries: {"entries": list(entries)}                                                    # noqa: E731
    assert fees.feed_version(feed(entry(4, "knos_pay", "pending"), entry(2, "knos_pay", "replaced"))) == 1
    assert fees.feed_version(feed(entry(4, "knos_pay", "executed"), entry(6, "knos_passkey", "executed"))) == 1        # 2.1 ran: still the 0.3.14 fee
    assert fees.feed_version(feed(entry(8, "knos_pay", "pending"), entry(4, "knos_pay", "executed"))) == 1               # 2.2 proposed, not run
    assert fees.feed_version(feed(entry(8, "knos_pay", "cancelled"), entry(4, "knos_pay", "executed"))) == 1
    assert fees.feed_version(feed(entry(7, "knos_oidc", "executed"), entry(4, "knos_pay", "executed"))) == 1             # another program's upgrade
    assert fees.feed_version(feed(entry(8, "knos_pay", "executed"), entry(4, "knos_pay", "executed"))) == 2
    assert fees.feed_version({}) is None and fees.feed_version(None) is None and fees.feed_version({"entries": "x"}) is None
    # the committed feed of this tree: no proposal of knos_pay after the 2.1 one has executed, so the site's fallback is the 0.3.14 fee
    committed = json.loads((ROOT / "web" / "upgrades.json").read_text(encoding="utf-8"))
    ran = [e["index"] for e in committed["entries"] if e["program"] == "knos_pay" and e["status"] == "executed" and e["index"] > fees.OLD_PAY_PROPOSALS]
    assert fees.feed_version(committed) == (2 if ran else 1)
    # and the SDK's fixtures hold the JavaScript to the same answers (sdk/settle/test.mjs)
    fx = json.loads((ROOT / "sdk" / "settle" / "fixtures.json").read_text(encoding="utf-8"))
    assert set(_find(fx, "fee version of a feed").values()) == {1, 2, None}


def _find(doc, key):
    if isinstance(doc, dict):
        if key in doc:
            return doc[key]
        for v in doc.values():
            got = _find(v, key)
            if got is not None:
                return got
    return None


def test_the_fee_in_words_is_true_on_both_sides_and_says_what_an_older_order_keeps():
    both, before, after = fees.words(None), fees.words(1), fees.words(2)
    assert all(w.endswith(fees.KEEPS) for w in (both, before, after, fees.words(0)))
    assert "once knos_pay 2.2 is live" in both and "until that upgrade executes the public program charges the 0.3.14 fee" in both and "`knos status`" in both
    assert before.startswith("Fee today: 2.5% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40 test USDC") and "From knos_pay 2.2: 0.30% of the amount, at least 0.05." in before
    assert after == f"Fee: 0.30% of the amount, at least 0.05 test USDC, paid by the funder on top (knos_pay 2.2 is live). {fees.KEEPS}"
    assert "2.5%" not in after and "0.40" not in after


def test_the_site_and_the_python_say_the_fee_in_the_same_words():
    """web/price.js feeWords and feeRate are tested against these same sentences in tests/web/price.mjs."""
    price = (ROOT / "tests" / "web" / "price.mjs").read_text(encoding="utf-8")
    for version in (None, 1, 2):
        assert json.dumps(fees.words(version))[1:-1] in price, version
    assert fees.KEEPS in (ROOT / "web" / "price.js").read_text(encoding="utf-8")


def test_every_document_that_states_the_fee_says_both_sides_and_what_an_older_order_keeps():
    keeps = "funded before the upgrade keep the rate fixed at their funding"
    for rel in ("docs/SECURITY.md", "docs/INSTALL.md", "docs/X402.md", "docs/COMPARE.md", "docs/CONSOLE.md", "docs/CONTROLS.md", "sdk/settle/README.md"):
        text = " ".join((ROOT / rel).read_text(encoding="utf-8").split())
        assert keeps in text, rel
        assert "0.30%" in text and "0.05" in text, rel                                  # the 0.3.18 fee
        assert ("2.5% of the first 1,000" in text or "0.3.14 fee" in text) and "0.40" in text, rel     # and the one the public program charges until 2.2 is live
        assert "knos_pay 2.2" in text, rel
    # the submission's form field has a length limit: the same facts in fewer words
    short = " ".join((ROOT / "docs" / "submission" / "SUBMISSION.md").read_text(encoding="utf-8").split())
    assert "0.30%, minimum 0.05, from knos_pay 2.2 (before that upgrade: the 0.3.14 fee, minimum 0.40; earlier orders keep their rate)" in short
