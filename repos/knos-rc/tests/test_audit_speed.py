"""How fast `knos audit export` reads the chain (knos.audit.owner_history): only the owner's Balances, its wallets and the
orders and bounties funded from them, never the escrow's newest 1,000 transactions.

A simulated cluster answers the JSON-RPC calls from the log lines of tests/test_audit.py's month (and _finance.py's
bounties), written back as transactions; it counts the calls. The checks: the file is the same bytes as the one made
from the whole history, and on a history the size of the witnessed run's (a few transactions of the owner among 1,000
of others) it takes a handful of calls, not a thousand. No network, no clock."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from solders.pubkey import Pubkey

import _finance as fin
import test_audit as base
from knos import audit, chain, cli
from knos.settle.v2 import pay as pay2

PAY = str(pay2.PAY_ID)
SEPT = base.SEPT
SKIP = ("event", "v", "at", "signer", "keys", "tx", "json")


class Cluster:
    """getProgramAccounts, getSignaturesForAddress and getTransaction over a list of log lines."""

    def __init__(self, events: list[dict]):
        self.calls: list[str] = []
        self.txs: dict[str, dict] = {}
        self.balances: list[tuple[str, int]] = []
        src: dict[tuple, str] = {}
        for n, ev in enumerate(sorted(events, key=lambda e: e["at"])):
            t = self.txs.setdefault(ev["tx"], {"at": ev["at"], "slot": n, "keys": ["relayer"], "logs": []})
            order = ev["event"].startswith("order_")
            name = ("knos3:" + ev["event"][6:]) if order else ("knos2:" + ev["event"])
            t["logs"].append(f"Program log: {name} " + (ev["json"] if "json" in ev else " ".join(f"{k}={v}" for k, v in ev.items() if k not in SKIP)))
            adds = [ev[k] for k in ("order", "source") if k in ev]
            if ev["event"] == "balance":
                b = str(pay2.balance_pda(int(ev["owner"]), Pubkey.from_string(ev["authority"]), Pubkey.from_string(ev["mint"])))
                self.balances.append((b, int(ev["owner"])))
                adds.append(b)
            if not order and "repo" in ev and "issue" in ev:
                if "source" in ev:
                    src[(ev["repo"], ev["issue"])] = ev["source"]
                if (ev["repo"], ev["issue"]) in src:
                    adds.append(str(pay2.job_pda(int(ev["repo"]), int(ev["issue"]), Pubkey.from_string(src[(ev["repo"], ev["issue"])]))))
            t["keys"] += [a for a in adds if a not in t["keys"]]

    def call(self, url, method, params, timeout=10.0):
        self.calls.append(method)
        if method == "getProgramAccounts":
            assert params[0] == PAY and params[1]["filters"][0] == {"dataSize": pay2.BALANCE_LEN}
            want = params[1]["filters"][1]["memcmp"]["bytes"]
            return [{"pubkey": b, "account": {}} for b, owner in self.balances if chain.b58(owner.to_bytes(8, "little")) == want]
        if method == "getSignaturesForAddress":
            mine = [(sig, t) for sig, t in self.txs.items() if params[0] == PAY or params[0] in t["keys"]]
            mine.sort(key=lambda x: -x[1]["slot"])
            return [{"signature": s, "err": None, "blockTime": t["at"], "slot": t["slot"]} for s, t in mine[:params[1]["limit"]]]
        if method == "getTransaction":
            t = self.txs[params[0]]
            return {"blockTime": t["at"], "meta": {"err": None, "logMessages": [f"Program {PAY} invoke [1]", *t["logs"], f"Program {PAY} success"]},
                    "transaction": {"message": {"accountKeys": t["keys"]}}}
        raise AssertionError(method)


@pytest.fixture()
def cluster(monkeypatch):
    def make(events):
        c = Cluster(events)
        monkeypatch.setattr(chain, "call", c.call)
        return c
    return make


def test_the_owners_own_part_gives_the_same_file_as_the_whole_history(cluster):
    for events, wallets in ((base.month(), [base.WALLET]), (base.month(), []), (fin.mix(), [base.WALLET]), (base.later(), [])):
        c = cluster(events)
        got = audit.owner_history("http://rpc", base.ACME, wallets, last=SEPT["last"])
        assert got is not None and got.unread == 0 and got.cut == ()
        assert audit.export(got.events, base.ACME, wallets=wallets, **SEPT) == audit.export(events, base.ACME, wallets=wallets, **SEPT)
        assert "getTransaction" in c.calls
    whole = audit.escrow_history("http://rpc", 1000, SEPT["last"])
    assert audit.export(whole.events, base.ACME, **SEPT) == audit.export(base.later(), base.ACME, **SEPT)


def test_another_owners_transactions_are_not_read_and_nothing_after_the_last_day_is(cluster):
    cluster(base.later())
    got = audit.owner_history("http://rpc", base.ACME, last=SEPT["last"])
    read = {ev["tx"] for ev in got.events}
    assert "PG" not in read and "FG" not in read and "B2" not in read       # OTHER's order and Balance
    assert "PF" not in read and "FI" not in read                           # after 30 September
    assert {"FA", "PA", "RB", "VC", "B1"} <= read


def test_a_history_the_size_of_the_witnessed_run_takes_a_handful_of_calls_not_a_thousand(cluster):
    """The witnessed run: one Balance, one order funded and paid, among 1,000 transactions of the escrow by others."""
    others = [ev for n in range(500) for ev in base.funded(f"Other{n}", base.T0 + n, f"OF{n}", base.U, source=base.BAL2, by=6002)[:1]]
    others += [ev for n in range(500) for ev in base.paid(f"Other{n}", base.T0 + 600 + n, f"OP{n}", [(8001, base.U)], base.U, base.U, 0)]
    mine = [base.line("balance", base.T0 - 10, "B1", owner=base.ACME, authority=base.WALLET, mint=base.MINT),
            base.line("balance", base.T0 - 10, "B2", owner=base.OTHER, authority=base.WALLET2, mint=base.MINT),
            *base.funded("OrdW", base.T0 + 2000, "FW", 5 * base.U), *base.paid("OrdW", base.T0 + 2300, "PW", [(8001, 5 * base.U)], 5 * base.U, 5 * base.U, 0)]
    c = cluster(others + mine)
    got = audit.owner_history("http://rpc", base.ACME, last="2026-09-01")
    assert audit.export(got.events, base.ACME, first="2026-09-01", last="2026-09-01") == audit.export(others + mine, base.ACME, first="2026-09-01", last="2026-09-01")
    assert len(c.calls) <= 8, c.calls                         # 1 listing, 2 histories, 3 transactions
    c.calls.clear()
    audit.escrow_history("http://rpc", 1000, "2026-09-01")
    assert len(c.calls) >= 1000                               # what 0.3.22 read (three times: both escrows and the meter)
    # at the public endpoint's 40 calls of one method per 10 s, that is over 4 minutes against about a second


def test_an_endpoint_that_will_not_list_balances_falls_back_to_the_escrow(cluster, monkeypatch):
    c = cluster(base.month())

    def no_listing(url, method, params, timeout=10.0):
        if method == "getProgramAccounts":
            raise chain.RpcError("Method not allowed", None)
        return c.call(url, method, params, timeout)
    monkeypatch.setattr(chain, "call", no_listing)
    assert audit.owner_history("http://rpc", base.ACME) is None
    monkeypatch.setattr(cli, "_ledger", lambda: SimpleNamespace(url="http://rpc"))
    got = audit.history_for(base.ACME, (), 1000, SEPT["last"])
    assert audit.export(got.events, base.ACME, **SEPT) == audit.export(base.month(), base.ACME, **SEPT)


def test_the_command_reads_the_owners_part(cluster, monkeypatch, capsys, tmp_path):
    cluster(base.month())
    monkeypatch.setattr(cli, "_ledger", lambda: SimpleNamespace(url="http://rpc"))
    out = tmp_path / "a.json"
    assert cli.main(["audit", "export", "--owner", str(base.ACME), "--from", SEPT["first"], "--to", SEPT["last"], "--format", "json", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == audit.export(base.month(), base.ACME, "json", **SEPT)
    assert json.loads(out.read_text(encoding="utf-8"))["scope"]["partial"] == 0
