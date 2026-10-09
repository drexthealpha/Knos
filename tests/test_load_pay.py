"""`scripts/load_pay.py`: end-to-end PayOrder capacity with N relays, each with a fee payer of its own. The simulator
proves the whole path (write, verify, PayOrder) and counts; it gives no rate. On a cluster every payment attempted is
counted, and a failure or a payment that never completed is never dropped from the denominator."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("knos_load_pay", ROOT / "scripts" / "load_pay.py")
load_pay = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = load_pay
_spec.loader.exec_module(load_pay)

from solders.keypair import Keypair  # noqa: E402

from knos.settle.v2 import relayq  # noqa: E402


def test_the_simulator_pays_every_order_once_each_by_the_relay_of_its_part_with_that_relays_key_alone():
    pytest.importorskip("solders.litesvm")
    got = load_pay.simulate(3, 6)
    assert got["ok"] and all(got["checks"].values()), got["checks"]
    assert (got["attempted"], got["paid"], got["refused"], got["never_completed"]) == (6, 6, 0, 0)
    assert sum(r["attempted"] for r in got["per_relay"]) == 6 and len(set(got["fee_payers"])) == 3
    assert got["rate"] is None and got["seconds"] is None and "times nothing" in got["why_no_rate"]       # no rate from a simulator
    assert got["transactions_per_payment"]["p50"] >= 2 and got["cu_per_payment"]["n"] == 6


def test_on_a_cluster_every_attempt_is_counted_with_its_failures_and_percentiles_apart():
    """A stand-in relay: one token refused, one that never answers. Paid 2 of 4, and the rate says of what."""
    from knos.settle.v2 import relay
    tokens = [{"kind": "pay", "jwt": f"t{i}"} for i in range(4)]
    lanes = {f"t{i}": str(i) for i in range(4)}
    clock = iter(float(x) for x in range(100))
    seen: dict[str, str] = {}

    def send(ledger, key, kind, jwt):
        seen[jwt] = str(key.pubkey())
        if jwt == "t1":
            return {"ok": False, "why": "the program refused it"}
        if jwt == "t2":
            raise TimeoutError("no answer")
        return {"ok": True}
    wallet = Keypair.from_seed(bytes(32))
    real = relay.lane
    relay.lane = lambda jwt: lanes[jwt]
    try:
        got = load_pay.on_cluster(None, wallet, 2, tokens, clock=lambda: next(clock), relay_one=send, lend=lambda k: True, sweep=lambda k: None)
    finally:
        relay.lane = real
    assert (got["attempted"], got["paid"], got["refused"], got["never_completed"]) == (4, 2, 1, 1) and got["ok"] is False
    assert got["first_refusals"] == ["the program refused it"]
    assert set(got["payment_s"]) == {"n", "p50", "p95", "p99", "max"} and got["payment_s"]["n"] == 2
    assert got["paid_per_s"] is not None and got["seconds"] > 0
    keys = got["fee_payers"]
    assert all(seen[t["jwt"]] == keys[relayq.part_of(lanes[t["jwt"]], 2)] for t in tokens)      # each token by the relay of its part
    # a relay that was not lent its SOL: nothing is sent, and the run says why
    got = load_pay.on_cluster(None, wallet, 2, tokens, relay_one=send, lend=lambda k: False, sweep=lambda k: None)
    assert got["ok"] is False and got["attempted"] == 0 and "not lent" in got["stopped"]


def test_the_command_asks_for_what_it_needs():
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts" / "load_pay.py"), *a], capture_output=True, text=True, encoding="utf-8")  # noqa: E731
    assert run("--relays", "2").returncode == 2 and "--tokens" in run("--relays", "2").stderr
    assert run("--relays", "2", "--simulate").returncode == 2
    assert run("--relays", "0", "--simulate", "--orders", "1").returncode == 2


def test_a_token_another_relay_carried_first_is_counted_and_never_as_paid():
    """`already`: the chain showed the payment done before this relay sent anything. It is in the denominator, and it
    is not a payment of the run: counting it as paid would time a read, not a PayOrder."""
    from knos.settle.v2 import relay
    tokens = [{"kind": "pay", "jwt": f"t{i}"} for i in range(3)]
    real = relay.lane
    relay.lane = lambda jwt: jwt
    try:
        got = load_pay.on_cluster(None, Keypair.from_seed(bytes(32)), 2, tokens, relay_one=lambda led, k, kind, jwt: {"ok": True, "already": jwt == "t0"},
                                  lend=lambda k: True, sweep=lambda k: None)
    finally:
        relay.lane = real
    assert (got["attempted"], got["paid"], got["already"], got["refused"], got["never_completed"]) == (3, 2, 1, 0, 0) and got["ok"] is False
    assert got["payment_s"]["n"] == 2


def test_measure_pay_write_keeps_the_cluster_run_and_the_page_prints_it_with_its_denominator(tmp_path, monkeypatch):
    """`python scripts/load.py measure --pay --relays 4 --tokens FILE --wallet KEY --write`, the command docs/LOAD.md
    names: the run of scripts/load_pay.py is appended to docs/load.json and rendered under its own heading."""
    sys.path[:0] = [p for p in (str(ROOT / "scripts"), str(ROOT / "tests")) if p not in sys.path]
    import load
    import load_pay as lp
    monkeypatch.setattr(load, "JSON", tmp_path / "load.json")
    monkeypatch.setattr(load, "DOC", tmp_path / "LOAD.md")
    (tmp_path / "load.json").write_text(json.dumps({"runs": []}), encoding="utf-8")
    from knos.settle.v2 import pay
    record = {"kind": "pay", "cluster": "devnet", "date": "2026-10-09", "relays": 4, "orders": 5, "wallet": "W",
              "programs": {"knos_pay": str(pay.PAY_ID), "knos_oidc": str(pay.OIDC_ID), "ids": "the ids this installation names"},
              "fee_payers": ["A", "B", "C", "D"], "attempted": 5, "paid": 4, "refused": 1, "never_completed": 0, "already": 0,
              "per_relay": [], "first_refusals": ["error 91"], "seconds": 12.5, "paid_per_s": 0.32,
              "payment_s": {"n": 4, "p50": 2.1, "p95": 3.0, "p99": 3.0, "max": 3.0}, "ok": False}
    monkeypatch.setattr(lp, "on_cluster", lambda *a, **k: record)
    toks, key = tmp_path / "pay.json", tmp_path / "key.json"
    toks.write_text(json.dumps([{"kind": "pay", "jwt": "x"}]), encoding="utf-8")
    key.write_text(json.dumps(list(bytes(Keypair.from_seed(bytes(32))))), encoding="utf-8")
    assert load.main(["measure", "--pay", "--relays", "4", "--tokens", str(toks), "--wallet", str(key), "--write"]) == 1     # not every payment paid
    kept = json.loads((tmp_path / "load.json").read_text(encoding="utf-8"))["measured"]
    assert kept == [record]
    page = (tmp_path / "LOAD.md").read_text(encoding="utf-8")
    assert ("#### Measured on devnet, public program ids, 2026-10-09: end-to-end PayOrder: token verification, then the payment; "
            "4 relays, 5 payments attempted (did not complete cleanly)") in page
    assert "| 5 | 4 of 5 | 0 | 1 | 0 | 12.5 | 0.32 | 2.1 | 3.0 | none: fewer than 100 payments | 3.0 |" in page
    assert "Not measured: end-to-end PayOrder capacity" not in page and "The first refusals: error 91." in page
    import rate_claims
    assert rate_claims.check(page) == []
    with pytest.raises(SystemExit):
        load.main(["measure", "--pay", "--relays", "2", "--orders", "2", "--simulate", "--write"])      # a simulated run is never written


def test_the_simulator_spreads_one_owners_orders_over_the_relays_and_each_fee_reaches_its_orders_account():
    """0.3.22: a pay token's lane is its order, and each order's fee goes to one of K token accounts of FEE_OWNER."""
    pytest.importorskip("solders.litesvm")
    got = load_pay.simulate(4, 16, fee_accounts=4)
    assert got["ok"] and all(got["checks"].values()), got["checks"]
    assert (got["owners"], got["lanes"], got["fee_accounts"], got["paid"]) == (1, "order", 4, 16)
    assert sum(1 for r in got["per_relay"] if r["attempted"]) > 1 and got["fee_accounts_used"] > 1


def test_on_a_cluster_k_fee_accounts_are_named_to_the_relays_for_the_run_and_the_record_says_so(monkeypatch):
    import base64
    monkeypatch.delenv("KNOS_FEE_SHARDS", raising=False)
    wallet = Keypair.from_seed(bytes(32))
    seen = []

    def send(ledger, key, kind, jwt):
        import os
        seen.append((os.environ.get("KNOS_FEE_SHARDS"), os.environ.get("KNOS_FEE_BASE")))
        return {"ok": True}
    body = base64.urlsafe_b64encode(json.dumps({"aud": "x", "repository_owner_id": "77"}).encode()).decode().rstrip("=")
    tokens = [{"kind": "pay", "jwt": f"h.{body}.s"} for _ in range(3)]
    got = load_pay.on_cluster(None, wallet, 2, tokens, relay_one=send, lend=lambda k: True, sweep=lambda k: None, fee_accounts=4)
    assert set(seen) == {("4", str(wallet.pubkey()))} and (got["fee_accounts"], got["lanes"], got["owners"]) == (4, "order", 1)
    import os
    assert "KNOS_FEE_SHARDS" not in os.environ                      # put back as it was


def test_the_one_relay_run_and_the_four_relay_run_of_8_october_stand_side_by_side_as_measured():
    doc = json.loads((ROOT / "docs" / "load.json").read_text(encoding="utf-8"))
    run = [m for m in doc["measured"] if m.get("kind") == "pay" and m.get("date") == "2026-10-08"]
    assert [(m["relays"], m["paid"], m["attempted"], m["paid_per_s"], m["seconds"], m["fee_accounts"]) for m in run] == [
        (1, 40, 40, 0.097, 412.74, 1), (4, 40, 40, 0.189, 211.27, 4)]
    four = run[1]
    assert [r["paid"] for r in four["per_relay"]] == [16, 8, 5, 11] and four["per_fee_account"] == [14, 9, 9, 8]
    assert (four["payment_s"]["p50"], four["payment_s"]["p95"], four["payment_s"]["max"], four["lanes"]) == (11.45, 22.61, 34.9, "order")
    page = (ROOT / "docs" / "LOAD.md").read_text(encoding="utf-8")
    assert "2026-10-08: end-to-end PayOrder: token verification, then the payment; 1 relay, 40 payments attempted" in page
    assert "2026-10-08: end-to-end PayOrder: token verification, then the payment; 4 relays, 40 payments attempted" in page
    assert "ONE relay carried all of them" in page and "Not measured: payments by order over several relays" not in page
    assert "against 40 of 40 payments, 0.097 a second, through one relay and one fee account (2026-10-08): 1.95 times the rate" in page


# == contention scenarios ==============================================================================================
def test_one_seed_lays_the_same_orders_over_the_same_relays_so_hot_funder_has_every_relay_write_the_fee_account():
    """The Balance's owner and the orders' issues come from the seed: two runs of one seed spread the orders alike.
    Drawn anew each run, 1 run in 32 of 2 relays and 6 orders put every order in one part, and hot-funder's one fee
    account was then written by one relay, not by all (tests.yml run 37925673025, Python 3.10)."""
    pytest.importorskip("solders.litesvm")
    a, b = (load_pay.simulate(2, 6, fee_accounts=2, scenario="hot-funder") for _ in range(2))
    assert a["per_relay"] == b["per_relay"] and all(r["attempted"] for r in a["per_relay"]), (a["per_relay"], b["per_relay"])
    assert a["checks"]["one_fee_account_written_by_every_relay"] and a["written_by_every_relay"] >= 1


@pytest.mark.parametrize("scenario", sorted(load_pay.SCENARIOS))
def test_each_contention_scenario_runs_in_the_simulator_with_its_own_checks_and_no_rate(scenario):
    """hot-funder: one fee account written by every relay; rpc-faults: refusals and lost answers injected, a resend
    after a lost answer refused by the program, nobody paid twice; priority-fee: the lamports a priced PayOrder costs
    over an unpriced one are exactly ceil(price x limit / 1,000,000); burst: every token open before the first payment."""
    pytest.importorskip("solders.litesvm")
    got = load_pay.simulate(2, 6, fee_accounts=2, scenario=scenario)
    assert got["ok"] and all(got["checks"].values()), got["checks"]
    assert (got["attempted"], got["paid"], got["scenario"], got["rate"]) == (6, 6, scenario, None)
    if scenario == "rpc-faults":
        f = got["faults_injected"]
        assert f["refused"] and f["lost"] and f["resent_and_refused"] and got["retries"] > 0
    if scenario == "priority-fee":
        assert got["priority_lamports_expected"] == 14_000
        assert got["lamports_per_payorder"]["with_price"][0] - got["lamports_per_payorder"]["without"][0] == 14_000
    if scenario == "hot-funder":
        assert got["fee_accounts"] == 1 and got["fee_accounts_used"] == 1
    if scenario == "burst":
        assert got["tokens_open_at_once"] == 6


class _Inner:
    """A ledger that takes every send and remembers its instructions."""
    def __init__(self):
        self.sent = []

    def send(self, ixs, payer, signers=None, v1=False):
        self.sent.append(list(ixs))
        return f"s{len(self.sent)}"


def _lanes(monkeypatch, n: int):
    from knos.settle.v2 import relay
    monkeypatch.setattr(relay, "lane", lambda jwt: jwt)
    return [{"kind": "pay", "jwt": f"t{i}"} for i in range(n)]


def test_rpc_faults_on_a_cluster_retry_and_count_a_lost_answer_as_paid_only_when_this_run_sent_it(monkeypatch):
    tokens = _lanes(monkeypatch, 12)
    inner, done = _Inner(), set()

    def send(ledger, key, kind, jwt):         # a relay: one send, which the chain keeps; once it has it, it answers "already"
        if jwt in done:
            return {"ok": True, "already": True}
        inner.now = jwt
        ledger.send([], key)
        return {"ok": True}
    real = inner.send
    inner.send = lambda ixs, payer, signers=None, v1=False: (done.add(inner.now), real(ixs, payer, signers, v1))[1]
    got = load_pay.on_cluster(None, Keypair.from_seed(bytes(32)), 1, tokens, ledger=inner, relay_one=send, lend=lambda k: True,
                              sweep=lambda k: None, scenario="rpc-faults")
    f = got["faults_injected"]
    assert f["refused"] + f["lost"] > 0 and got["retries"] >= f["refused"] + f["lost"] - got["never_completed"]
    assert got["already"] == 0 and got["paid"] + got["never_completed"] == 12 and len(done) == len(inner.sent)
    assert got["scenario"] == "rpc-faults" and "measures" in got


def test_priority_fee_on_a_cluster_puts_the_price_beside_the_limit_on_every_legacy_transaction_with_room(monkeypatch):
    from solders.compute_budget import ID as BUDGET

    from knos import chain
    tokens = _lanes(monkeypatch, 3)
    inner = _Inner()
    got = load_pay.on_cluster(None, Keypair.from_seed(bytes(32)), 1, tokens, ledger=inner, lend=lambda k: True, sweep=lambda k: None,
                              relay_one=lambda led, key, kind, jwt: (led.send([chain.set_compute_unit_limit(1)], key), {"ok": True})[1],
                              scenario="priority-fee", cu_price=7)
    assert got["paid"] == 3 and got["priority"] == {"priced": 3, "no_room": 0} and got["cu_price_micro_lamports"] == 7
    for ixs in inner.sent:      # the relay's own limit kept, the price added, nothing else
        assert [ix.program_id for ix in ixs] == [BUDGET, BUDGET] and bytes(ixs[0].data)[:1] == b"\x03" and int.from_bytes(bytes(ixs[0].data)[1:9], "little") == 7


def test_burst_on_a_cluster_sends_a_relays_payments_at_once_and_hot_funder_needs_one_funder(monkeypatch):
    import threading
    tokens = _lanes(monkeypatch, 3)
    together = threading.Barrier(3, timeout=30)

    def send(ledger, key, kind, jwt):         # passes only if all three are in flight at the same time
        together.wait()
        return {"ok": True}
    got = load_pay.on_cluster(None, Keypair.from_seed(bytes(32)), 1, tokens, relay_one=send, lend=lambda k: True, sweep=lambda k: None,
                              scenario="burst")
    assert (got["paid"], got["never_completed"], got["ok"]) == (3, 0, True)
    monkeypatch.setattr(load_pay, "_owner", lambda jwt: jwt)        # three tokens, three owners
    got = load_pay.on_cluster(None, Keypair.from_seed(bytes(32)), 1, tokens, relay_one=lambda *a: {"ok": True}, lend=lambda k: True,
                              sweep=lambda k: None, scenario="hot-funder")
    assert got["ok"] is False and "one funder" in got["stopped"] and got["fee_accounts"] == 1


def test_the_page_says_what_each_scenario_measures_and_which_have_run():
    page = (ROOT / "docs" / "LOAD.md").read_text(encoding="utf-8")
    for name, words in load_pay.SCENARIOS.items():
        row = next(line for line in page.splitlines() if line.startswith(f"| {name} | "))
        assert words in row and "local simulator" in row and "every check holds" in row
        assert row.endswith("| not run yet |") or "public program ids" in row
    assert "0.189" in page and "16, 8, 5 and 11" in page and "14, 9, 9 and 8" in page and "37833126115" in page


# == 0.3.24: v1 transactions priced; burst backs off ===================================================================
class _Cluster:
    """A cluster's ledger as far as `Shaped` signs v1 transactions itself: a blockhash, a submission, nothing else."""
    url, commitment = "fake://", "confirmed"

    def __init__(self):
        self.sent, self.legacy = [], []

    def _blockhash(self):
        from solders.hash import Hash
        return Hash.new_unique()

    def _submit(self, tx):
        self.sent.append(tx)
        return str(tx.signatures[0])

    def send(self, ixs, payer, signers=None, v1=False):
        assert not v1, "a v1 transaction under priority-fee is signed by Shaped, with its price in the message"
        self.legacy.append(list(ixs))
        return f"s{len(self.legacy)}"


def test_priority_fee_prices_every_transaction_legacy_and_v1_alike(monkeypatch):
    """The 9 Oct run sent its v1 transactions with no price. Now every transaction built under priority-fee carries
    one: a legacy one SetComputeUnitPrice beside its limit, a v1 one the same lamports in its message configuration
    (ceil(price x limit / 1,000,000)), signed and valid."""
    from solders.compute_budget import ID as BUDGET
    from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
    from solders.instruction import Instruction
    from solders.pubkey import Pubkey

    from knos import chain
    monkeypatch.setattr(chain, "wait", lambda *a, **k: {})
    monkeypatch.setattr(chain, "wait_all", lambda *a, **k: [])
    tokens = _lanes(monkeypatch, 3)
    inner = _Cluster()
    memo = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")

    def relay_one(led, key, kind, jwt):
        work = Instruction(memo, jwt.encode(), [])
        led.send([set_compute_unit_limit(600_000), work], key, v1=True)          # a v1 transaction with its own limit
        led.send_all([[work], [Instruction(memo, b"x" + jwt.encode(), [])]], key, v1=True)      # two at once
        led.send([work], key)                                                           # and a legacy one
        return {"ok": True}
    got = load_pay.on_cluster(None, Keypair.from_seed(bytes(32)), 1, tokens, ledger=inner, relay_one=relay_one, lend=lambda k: True,
                              sweep=lambda k: None, scenario="priority-fee", cu_price=10_000)
    assert got["paid"] == 3 and got["priority"] == {"priced": 12, "no_room": 0}
    assert len(inner.sent) == 9 and len(inner.legacy) == 3
    for tx in inner.sent:
        assert tx.verify_with_results() == [True] * len(tx.signatures)
        cfg = tx.message.config
        assert cfg.priority_fee == load_pay.priority_lamports(10_000, cfg.compute_unit_limit) > 0
        assert not any(tx.message.account_keys[ix.program_id_index] == BUDGET for ix in tx.message.instructions) or chain.V1_BUDGET_IX
    assert sorted({tx.message.config.compute_unit_limit for tx in inner.sent}) == [600_000, chain.MAX_COMPUTE_UNITS]
    assert {tx.message.config.priority_fee for tx in inner.sent} == {6_000, 14_000}
    for ixs in inner.legacy:
        prices = [ix for ix in ixs if ix.program_id == BUDGET and bytes(ix.data)[:1] == b"\x03"]
        assert len(prices) == 1 and int.from_bytes(bytes(prices[0].data)[1:9], "little") == 10_000
    # with the tests' simulator setting (V1_BUDGET_IX) the instructions go in beside the configuration too
    monkeypatch.setattr(chain, "V1_BUDGET_IX", True)
    m = load_pay.message_v1_priced([set_compute_unit_price(5)], Keypair.from_seed(bytes(32)).pubkey())
    assert m.config.priority_fee == 7 and len(m.instructions) == 2


class _Endpoint:
    """A public endpoint under a burst, as 9 Oct met it: it takes 13 sends in each 10 seconds and turns the rest away,
    half with HTTP 429, half with "Blockhash not found". Time is each payment's own (`pause` adds to it), so the run
    takes no wall-clock time. `lose`: that many of the first sends that land have their answer lost (a 429 on the
    confirmation): the payment is on chain, the relay does not know it. The order's single-use marker refuses a second
    PayOrder for a paid order."""

    def __init__(self, lose: int = 0):
        import threading
        self.lock, self.mine = threading.Lock(), threading.local()
        self.at: dict[str, float] = {}
        self.taken: dict[int, int] = {}
        self.payouts: dict[str, int] = {}
        self.hashes: dict[str, list[int]] = {}
        self.fetched, self.lose, self.turned_away = 0, lose, {"429": 0, "blockhash": 0}

    def pause(self, seconds: float) -> None:
        self.mine.owed = getattr(self.mine, "owed", 0.0) + seconds

    def relay_one(self, ledger, key, kind, jwt):
        import urllib.error
        with self.lock:
            self.at[jwt] = self.at.get(jwt, 0.0) + getattr(self.mine, "owed", 0.0)
            self.mine.owed = 0.0
            self.fetched += 1
            self.hashes.setdefault(jwt, []).append(self.fetched)        # each send signed over a blockhash fetched for it
            window = int(self.at[jwt] // 10)
            if self.taken.get(window, 0) >= 13:
                n = sum(self.turned_away.values())
                if n % 2 == 0:
                    self.turned_away["429"] += 1
                    raise urllib.error.HTTPError("fake://", 429, "Too Many Requests", None, None)  # type: ignore[arg-type]
                self.turned_away["blockhash"] += 1
                return {"ok": False, "why": "Transaction simulation failed: Blockhash not found"}
            self.taken[window] = self.taken.get(window, 0) + 1
            if jwt in self.payouts:
                return {"ok": False, "why": "Allocate: account Address { used marker } already in use"}
            self.payouts[jwt] = 1
            if self.lose:
                self.lose -= 1
                raise urllib.error.HTTPError("fake://", 429, "Too Many Requests", None, None)  # type: ignore[arg-type]
        return {"ok": True}


def _burst(monkeypatch, lose: int = 0) -> tuple[dict, _Endpoint]:
    tokens = _lanes(monkeypatch, 40)
    net = _Endpoint(lose)
    got = load_pay.on_cluster(None, Keypair.from_seed(bytes(32)), 4, tokens, relay_one=net.relay_one, lend=lambda k: True,
                              sweep=lambda k: None, scenario="burst", pause=net.pause)
    return got, net


def test_burst_before_the_backoff_pays_13_of_40_as_9_october_did(monkeypatch):
    monkeypatch.setattr(load_pay, "BURST_ATTEMPTS", 1)
    got, net = _burst(monkeypatch)
    assert (got["attempted"], got["paid"], got["failures"], got["retries"]) == (40, 13, 27, 0) and got["ok"] is False
    assert net.turned_away == {"429": 14, "blockhash": 13}


def test_burst_backs_off_refreshes_the_blockhash_and_pays_40_of_40_once_each(monkeypatch):
    for _ in range(5):          # the relays race for the endpoint's 13 places a window: the outcome may not depend on who wins
        got, net = _burst(monkeypatch, lose=2)
        assert (got["attempted"], got["paid"], got["failures"], got["ok"]) == (40, 40, 0, True), got["first_refusals"]
        assert got["duplicates_refused"] == 2 and set(net.payouts.values()) == {1} and len(net.payouts) == 40     # no payee paid twice
        assert got["retries"] > 0 and max(net.at.values()) <= 63.0                                               # waits bounded
        assert all(len(h) == len(set(h)) for h in net.hashes.values())                                           # a fresh blockhash a send
        assert got["backoff"]["sends_at_most"] == load_pay.BURST_ATTEMPTS


def test_backoff_is_bounded_jittered_and_seeded():
    import random
    waits = [load_pay.backoff_s(a, random.Random("21:t0")) for a in range(1, 12)]
    assert waits == [load_pay.backoff_s(a, random.Random("21:t0")) for a in range(1, 12)]
    assert all(min(16.0, 2 ** (a - 1)) / 2 <= w <= min(16.0, 2 ** (a - 1)) for a, w in zip(range(1, 12), waits))
    assert load_pay.transient("HTTPError: HTTP Error 429: Too Many Requests") and load_pay.transient("Blockhash not found")
    assert not load_pay.transient("custom program error: 0x1771")
