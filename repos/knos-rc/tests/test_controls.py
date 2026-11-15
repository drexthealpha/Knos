"""`knos budget` (src/knos/controls.py) on LiteSVM: the limits a Balance's wallet sets with `budget set` are the ones
the PROGRAM then enforces, and `budget check` names beforehand the rule the program refuses on. Also: the dry run that
sends nothing, who has authority, the "authorised by" of an audit row, and the cases web/controls_data.js must answer
alike (tests/data/controls_cases.json; tests/web/controls.mjs runs them in node)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

import typer  # noqa: E402
from _order import AUTHOR, DAY, MAINT, OWNER, REPO, USDC, OrderChain, code, issue  # noqa: E402
from _pay2 import WF_SHA, ChainLedger  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

from knos import cli, controls, fees  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402
from knos.settle.v2 import relay as relay2  # noqa: E402

OTHER, ELSEWHERE, SECOND = 123_123_123, 321_321_321, 777_000       # a repository of the owner's not on the list; a stranger's; a second spender
CASES = Path(__file__).parent / "data" / "controls_cases.json"
GITHUB = {"users/acme": {"id": OWNER}, "users/maint": {"id": MAINT}, "users/stranger": {"id": AUTHOR}, "users/second": {"id": SECOND},
          "repos/acme/app": {"id": REPO, "owner": {"id": OWNER}}, "repos/acme/other": {"id": OTHER, "owner": {"id": OWNER}},
          "repos/else/where": {"id": ELSEWHERE, "owner": {"id": AUTHOR}},
          f"repositories/{REPO}": {"full_name": "acme/app"}, f"repositories/{OTHER}": {"full_name": "acme/other"},
          f"user/{OWNER}": {"login": "acme"}, f"user/{MAINT}": {"login": "maint"}, f"user/{SECOND}": {"login": "second"}}


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    """A chain with the owner's Balance (100,000 test USDC, MAINT a spender) behind the command line, GitHub faked, the
    owner wallet's keypair file, and `knos(...)`: run `knos budget ...`, return (exit code, what it printed)."""
    c = OrderChain()
    monkeypatch.setattr(cli, "_ledger", lambda: ChainLedger(c))
    monkeypatch.setattr(cli, "_github", lambda path: GITHUB[path])
    monkeypatch.setattr(cli, "_fetch", lambda path: GITHUB[path])
    monkeypatch.delenv("KNOS_WALLET_KEY", raising=False)
    keyfile = tmp_path / "owner.json"
    keyfile.write_text(json.dumps(list(bytes(c.owner))), encoding="utf-8")
    app = typer.Typer(add_completion=False)
    app.callback()(lambda: None)
    controls.register(app)

    def knos(*args) -> tuple[int, str]:
        capsys.readouterr()
        try:
            rc = app(args=["budget", *map(str, args)], standalone_mode=False, prog_name="knos")
            rc = int(rc) if isinstance(rc, int) else 0
        except cli.Stop as why:
            print(why.said, why.fix)
            rc = 1
        except typer.Exit as e:
            rc = int(e.exit_code or 0)
        return rc, capsys.readouterr().out
    return c, knos, keyfile


def fund(c: OrderChain, amount: int, actor: int = MAINT, repo: int = REPO, owner: int = OWNER) -> int | None:
    """A comment by `actor` in `repo` funds an order of `amount` whole units from the owner's Balance, as GitHub would
    sign it. None: the program took it; else the program's error number."""
    n = issue()
    tok = c.fund_token(n, amount * USDC, actor=actor, repository_id=repo, repository_owner_id=owner)
    return None if c.send([c.fund_balance_ix(tok, n, repo=repo)]) else code(c)


def predicted(knos, amount: int, by: str = "maint", repo: str = "acme/app") -> tuple[str, int, dict]:
    rc, said = knos("check", "--owner", "acme", "--repo", repo, "--amount", amount, "--by", by, "--json")
    d = json.loads(said)
    assert rc == (0 if d["ok"] else 1)
    return d["rule"], d["code"], d


def test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first(world):
    c, knos, keyfile = world
    assert predicted(knos, 5_000)[0] == "ok"                 # before any limit: the owner's spender may fund anything the Balance holds
    rc, said = knos("set", "--owner", "acme", "--cap", 50, "--per-day", 60, "--total", 500, "--repo", "acme/app", "--pin-workflows",
                    "--workflows-commit", WF_SHA, "--keypair", keyfile)
    assert rc == 0 and "Set." in said and "cap per order        none  ->  50.00" in said and "allowed repositories any repository of the owner  ->  acme/app" in said, said
    b, x = pay.read_balance(c.data(c.bal)), pay.read_balx(c.data(pay.balx_pda(c.bal)))
    assert (b.cap_per_job, b.spenders, b.has_x) == (50 * USDC, (MAINT,), True)
    assert (x.day_limit, x.total_limit, x.repos, x.wf_sha) == (60 * USDC, 500 * USDC, (REPO,), WF_SHA)

    # each refusal: `budget check` says the rule, then the PROGRAM refuses the same funding with that rule's error
    for want, kw, cmd in (("spender", dict(actor=AUTHOR), dict(by="stranger")),
                          ("repository", dict(repo=OTHER), dict(repo="acme/other")),
                          ("owner", dict(repo=ELSEWHERE, owner=AUTHOR), dict(repo="else/where")),
                          ("cap", {}, {})):
        amount = 51 if want == "cap" else 20
        rule, err, _d = predicted(knos, amount, **cmd)
        assert rule == want and err == controls.RULES[want]
        assert fund(c, amount, **kw) == err, (want, c.err)
    assert pay.read_balx(c.data(pay.balx_pda(c.bal))).total_spent == 0        # a refusal counts nothing

    # within every limit: predicted fine, and the program takes it; the limits count the amount and the fee
    rule, _err, d = predicted(knos, 20)
    # the fee is the one of the build under test (knos.fees.live asks the program): the numbers below follow it
    live = fees.live(ChainLedger(c))
    with_fee, m = (lambda whole: whole * USDC + live.order(whole * USDC)), controls.money
    f20 = live.order(20 * USDC)
    assert (rule, d["fee"], d["effectivePct"], d["total"]) == ("ok", f20, controls.percent(f20, 20 * USDC), with_fee(20))
    assert fund(c, 20) is None, c.err
    x = pay.read_balx(c.data(pay.balx_pda(c.bal)))
    assert (x.day_spent, x.total_spent) == (with_fee(20), with_fee(20))

    # over today's limit: 40 is under the cap, and with its fee and what today already counts it is over 60
    rule, err, d = predicted(knos, 40)
    assert (rule, err) == ("day", 100) and f"{m(60 * USDC - with_fee(20))} is left until midnight UTC" in d["sentence"]
    assert fund(c, 40) == 100
    assert predicted(knos, 38)[0] == "ok" and fund(c, 38) is None             # 38 and its fee still fit under 60
    c.warp(DAY)                                                               # the next UTC day: today's count starts again
    assert predicted(knos, 40)[0] == "ok" and fund(c, 40) is None, c.err

    # the total limit, lowered under what is spent: the counters stay, and the program refuses with the same error
    assert knos("set", "--owner", "acme", "--total", 110, "--per-day", 0, "--keypair", keyfile)[0] == 0
    rule, err, d = predicted(knos, 20)
    assert (rule, err) == ("total", 100) and f"{m(with_fee(20) + with_fee(38) + with_fee(40))} spent so far" in d["sentence"]
    assert fund(c, 20) == 100
    assert predicted(knos, 9)[0] == "ok" and fund(c, 9) is None               # 9 and its fee fit under 110


def test_without_a_key_budget_set_prints_before_and_after_and_sends_nothing(world, monkeypatch):
    c, knos, keyfile = world
    before = (c.data(c.bal), c.data(pay.balx_pda(c.bal)))
    rc, said = knos("set", "--owner", "acme", "--per-day", "250.5", "--spender", "maint", "--spender", "second")
    assert rc == 0 and "Nothing was sent." in said and f"Wallet {c.owner.pubkey()} must sign 2 instruction(s)" in said
    assert "daily limit          none  ->  250.50" in said and "maint (id 555000)  ->  maint (id 555000), second (id 777000)" in said
    assert "total limit          none  (unchanged)" in said and "SetBalanceX" in said
    assert before == (c.data(c.bal), c.data(pay.balx_pda(c.bal))) and before[1] is None
    # --dry-run with the key still sends nothing; --json gives the instructions a multisig would propose
    rc, said = knos("set", "--owner", "acme", "--cap", 10, "--keypair", keyfile, "--dry-run", "--json")
    plan = json.loads(said)
    assert rc == 0 and plan["authority"] == str(c.owner.pubkey()) and (plan["before"]["cap"], plan["after"]["cap"]) == (0, 10 * USDC)
    [ix] = plan["instructions"]
    assert ix["program"] == str(pay.PAY_ID) and bytes.fromhex(ix["data_hex"]) == bytes(pay.set_balance_ix(c.owner.pubkey(), c.bal, 10 * USDC, [MAINT]).data)
    assert ix["accounts"][0] == {"address": str(c.owner.pubkey()), "signer": True, "writable": False}
    assert pay.read_balance(c.data(c.bal)).cap_per_job == 0
    # a cluster that still runs 2.0 has no side account: said before anything is sent
    with monkeypatch.context() as old:
        old.setattr(relay2, "version", lambda ledger, payer=None: 0)
        rc, said = knos("set", "--owner", "acme", "--per-day", 30, "--cap", 10, "--keypair", keyfile)
        assert rc == 1 and "not knos_pay 2.1 yet" in said and "Nothing was sent" in said and before == (c.data(c.bal), c.data(pay.balx_pda(c.bal)))
    # what cannot hold is refused in words, and so is another wallet's key
    assert knos("set", "--owner", "acme")[0] == 1
    rc, said = knos("set", "--owner", "acme", "--per-day", 100, "--total", 50)
    assert rc == 1 and "daily limit is more than the total limit" in said
    stranger = keyfile.with_name("stranger.json")
    stranger.write_text(json.dumps(list(bytes(c.funder))), encoding="utf-8")
    rc, said = knos("set", "--owner", "acme", "--cap", 10, "--keypair", stranger)
    assert rc == 1 and "No such Balance" in said
    rc, said = knos("set", "--owner", "acme", "--cap", 10, "--keypair", stranger, "--balance", c.bal)
    assert rc == 1 and "Only that wallet changes it" in said and pay.read_balance(c.data(c.bal)).cap_per_job == 0


def test_only_the_wallet_that_opened_the_balance_can_send_what_budget_set_builds(world):
    c, _knos, _keyfile = world
    [b] = controls.budgets(ChainLedger(c), OWNER)
    ixs, _before, _after = controls.changes(b, cap=10 * USDC, per_day=30 * USDC)
    assert [ix.data[0] for ix in ixs] == [1, 13]
    for ix in ixs:      # the same bytes with another signer in the authority's place: the program refuses (98)
        forged = type(ix)(ix.program_id, bytes(ix.data), [type(a)(c.funder.pubkey(), a.is_signer, a.is_writable) if a.pubkey == c.owner.pubkey() else a
                                                         for a in ix.accounts])
        assert not c.send([forged], c.funder) and code(c) == 98
    assert c.send(ixs, c.owner), c.err
    assert controls.settings(controls.budgets(ChainLedger(c), OWNER)[0]) == {"cap": 10 * USDC, "spenders": (MAINT,), "per_day": 30 * USDC, "total": 0,
                                                                              "repos": (), "workflows": ""}
    assert controls.changes(controls.budgets(ChainLedger(c), OWNER)[0], cap=10 * USDC)[0] == []      # nothing to sign when nothing changes


def test_budget_show_and_who_say_what_the_chain_has(world):
    c, knos, keyfile = world
    live, m = fees.live(ChainLedger(c)), controls.money     # the rule of the build under test: the lines below follow it
    assert c.set_plan(OWNER, live.plan_min, c.now() + 30 * DAY), c.err
    assert knos("set", "--owner", "acme", "--cap", 50, "--per-day", 60, "--total", 500, "--repo", "acme/app", "--repo", "acme/other",
                "--workflows-commit", WF_SHA, "--keypair", keyfile)[0] == 0
    assert fund(c, 20) is None, c.err                       # at the Plan's lowest rate: the least fee
    spent = 20 * USDC + live.order(20 * USDC, live.plan_min)
    assert spent == 20 * USDC + pay.units(live.floor)
    rc, said = knos("show", "--owner", "acme")
    assert rc == 0, said
    for line in (f"Balance {c.bal}: holds {m(100_000 * USDC - spent)} of mint {c.usdc}, for the repositories of GitHub id {OWNER} (acme).",
                 "cap per order        50.00", f"daily limit          60.00; {m(spent)} spent today (UTC), {m(60 * USDC - spent)} left",
                 f"total limit          500.00; {m(spent)} spent, {m(500 * USDC - spent)} left", f"allowed repositories acme/app (id {REPO}), acme/other (id {OTHER})",
                 f"workflows commit     {WF_SHA}", f"spenders             maint (id {MAINT}), besides the owner", f"fee                  a Plan: {live.rate(live.plan_min)} until ", f"the {live.release} fee, which knos_pay {live.build} charges", fees.KEEPS):
        assert line in said, (line, said)
    rc, said = knos("show", "--owner", "acme", "--no-names")
    assert rc == 0 and f"allowed repositories id {REPO}, id {OTHER}" in said
    rc, said = knos("who", "--owner", "acme")
    assert rc == 0 and f"the owner: acme (id {OWNER})" in said and f"a spender: maint (id {MAINT})" in said
    assert f"wallet {c.owner.pubkey()}, which opened the Balance. Nobody else" in said
    rc, said = knos("who", "--owner", "stranger")
    assert rc == 1 and "No Balance is set aside" in said


def test_authority_of_says_who_authorised_an_orders_money():
    bal = pay.Balance(False, OWNER, Pubkey.default(), Pubkey.default(), 0, 0, (MAINT,), 0)
    order = {"from_balance": True, "by": MAINT, "owner": OWNER, "source": "Bal", "faucet": False}
    assert controls.authority_of(order, bal) == {"funder_id": MAINT, "role": "spender", "listed_now": True, "authorised_by": f"gh:{MAINT} (spender)"}
    assert controls.authority_of(order) ["listed_now"] is None
    assert controls.authority_of(order, {"spenders": []})["listed_now"] is False        # a spender then, taken off the list since
    assert controls.authority_of({**order, "by": OWNER}, bal)["authorised_by"] == f"gh:{OWNER} (owner)"
    assert controls.authority_of({**order, "by": AUTHOR, "faucet": True})["role"] == "faucet"
    assert controls.authority_of({"from_balance": False, "by": 0, "owner": 0, "source": "Wal1et"}) == {
        "funder_id": 0, "role": "wallet", "listed_now": None, "authorised_by": "wallet:Wal1et"}


# ---- the cases both the Python and web/controls_data.js answer --------------------------------------------------------
def _cases() -> list[dict]:
    now = 1_790_000_000
    bal = {"faucet": False, "hasX": True, "ownerId": 424242, "capPerJob": 5_000_000_000, "spenders": [555000, 777000]}
    x = {"dayLimit": 6_000_000_000, "totalLimit": 60_000_000_000, "repos": [987654321, 5], "wfSha": "c" * 40, "day": now // 86_400,
         "daySpent": 1_000_000_000, "totalSpent": 55_000_000_000}
    base = {"balance": bal, "balx": x, "plan": None, "repoId": 987654321, "amount": 100_000_000, "byId": 555000, "now": now, "holds": None,
            "repoOwnerId": None, "wfSha": None}
    free = {**bal, "hasX": False, "capPerJob": 0}
    vary = {
        "fine: a spender, 100": {},
        "fine: the owner, the minimum fee on 5": {"byId": 424242, "amount": 5_000_000},
        "fine: a Plan at 0.20%": {"plan": {"feeBps": 20, "ownerId": 424242, "expires": now + 1}},
        "fine: a Plan that ended is the standard rate": {"plan": {"feeBps": 20, "ownerId": 424242, "expires": now}},
        "fine: a Plan under the lowest rate is held to it": {"plan": {"feeBps": 5, "ownerId": 424242, "expires": now + 9}},
        "fine: exactly the daily limit": {"amount": 4_985_044_866},
        "fine: yesterday's count is not today's": {"balx": {**x, "day": now // 86_400 - 1, "daySpent": 5_900_000_000}, "amount": 4_900_000_000},
        "fine: no side account, 50,000": {"balance": free, "balx": None, "amount": 50_000_000_000},
        "fine: the side account is ignored until the Balance says it has one": {"balance": free, "amount": 50_000_000_000},
        "fine: the faucet's, any commenter": {"balance": {**free, "faucet": True}, "balx": None, "byId": 31337},
        "fine: the pinned commit": {"wfSha": "c" * 40},
        "owner: a stranger's repository": {"repoOwnerId": 31337},
        "spender: not listed": {"byId": 31337},
        "spender: nobody": {"byId": 0},
        "spender: before the cap": {"byId": 31337, "amount": 9_000_000_000},
        "cap: one unit over": {"amount": 5_000_000_001},
        "cap: before the repository": {"amount": 5_000_000_001, "repoId": 6},
        "repository: not listed": {"repoId": 6},
        "workflows: another commit": {"wfSha": "d" * 40},
        "day: one unit over": {"amount": 4_985_044_867},
        "day: before the total": {"amount": 4_990_000_000, "balx": {**x, "totalSpent": 59_000_000_000}},
        "total: over": {"balx": {**x, "daySpent": 0, "totalSpent": 59_950_000_000}},
        "funds: the Balance holds less than amount and fee": {"holds": 100_299_999},
        "fine: the Balance holds exactly amount and fee": {"holds": 100_300_000},
        "amount: under 5": {"amount": 4_999_999, "balx": None, "balance": free},
        "amount: over 100,000": {"amount": 100_000_000_001, "balx": None, "balance": free},
    }
    return [{"name": name, "in": {**base, **over}} for name, over in vary.items()]


def _answer(q: dict) -> dict:
    b, x, p = q["balance"], q["balx"], q["plan"]
    balance = pay.Balance(b["faucet"], b["ownerId"], Pubkey.default(), Pubkey.default(), b["capPerJob"], 0, tuple(b["spenders"]), 0, b["hasX"])
    balx = x and pay.BalanceX(x["dayLimit"], x["totalLimit"], tuple(x["repos"]), x["wfSha"], x["day"], x["daySpent"], x["totalSpent"])
    plan = p and pay.Plan(p["feeBps"], p["ownerId"], p["expires"])
    return controls.decide(balance, balx, q["repoId"], q["amount"], q["byId"], q["now"], plan=plan, holds=q["holds"], repo_owner_id=q["repoOwnerId"],
                           wf_sha=q["wfSha"]).as_json()


def _file() -> str:
    table = [{"amount": r["amount"], "fee": r["fee"], "total": r["total"], "effectivePct": r["effective_pct"]} for r in controls.fee_table()]
    return json.dumps({"cases": [{**c, "out": _answer(c["in"])} for c in _cases()], "feeTable": table}, indent=1, sort_keys=True) + "\n"


def test_the_cases_file_is_what_the_python_answers_and_each_rule_is_in_it():
    assert CASES.read_text(encoding="utf-8") == _file(), "the cases changed: write the file again (python tests/test_controls.py) and read the difference"
    got = json.loads(_file())
    assert {c["out"]["rule"] for c in got["cases"]} == set(controls.RULES)
    assert all(c["name"].split(":")[0] == ("fine" if c["out"]["ok"] else c["out"]["rule"]) for c in got["cases"])
    # the price book's table, to the cent, under the 0.3.18 fee (0.30%, at least 0.05) ...
    assert [(controls.money(r["amount"]), controls.money(r["fee"]), r["effectivePct"]) for r in got["feeTable"]] == [
        ("5.00", "0.05", "1.00"), ("20.00", "0.06", "0.30"), ("1,000.00", "3.00", "0.30"), ("5,000.00", "15.00", "0.30"), ("50,000.00", "150.00", "0.30")]
    # ... and under the 0.3.14 fee, which the public program charges until knos_pay 2.2 is live
    assert [(controls.money(r["amount"]), controls.money(r["fee"]), r["effective_pct"]) for r in controls.fee_table(rule=fees.OLD)] == [
        ("5.00", "0.40", "8.00"), ("20.00", "0.50", "2.50"), ("1,000.00", "25.00", "2.50"), ("5,000.00", "65.00", "1.30"), ("50,000.00", "515.00", "1.03")]
    # the same decision under the 0.3.14 fee: 4,935.643565 and its fee of 64.356435 were exactly the 5,000 left of a day
    q = next(c["in"] for c in got["cases"] if c["name"] == "fine: a spender, 100")
    b, x = q["balance"], q["balx"]
    balance = pay.Balance(b["faucet"], b["ownerId"], Pubkey.default(), Pubkey.default(), b["capPerJob"], 0, tuple(b["spenders"]), 0, b["hasX"])
    balx = pay.BalanceX(x["dayLimit"], x["totalLimit"], tuple(x["repos"]), x["wfSha"], x["day"], x["daySpent"], x["totalSpent"])
    was = [controls.decide(balance, balx, q["repoId"], a, q["byId"], q["now"], rule=fees.OLD) for a in (4_935_643_565, 4_935_643_566, 100_000_000)]
    assert [(d.rule, d.fee, d.bps) for d in was] == [("ok", 64_356_435, 250), ("day", 64_356_435, 250), ("ok", 2_500_000, 250)]
    assert controls.money(1) == "0.000001" and controls.money(1_234_567_890_120) == "1,234,567.89012" and controls.percent(1, 0) == "0.00"


def test_the_site_answers_the_same_cases_the_same():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    r = subprocess.run([node, str(Path(__file__).parent / "web" / "controls.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    assert r.returncode == 0 and "all passed" in r.stdout, r.stdout + r.stderr


if __name__ == "__main__":      # python tests/test_controls.py: write the cases file again, after a rule or a sentence changed
    CASES.write_text(_file(), encoding="utf-8", newline="\n")
