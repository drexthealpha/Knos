"""`knos observe` against the programs themselves (LiteSVM, the test builds): what an outsider can infer about a work
order from the bytes knos_pay and knos_oidc wrote, and nothing else.

One chain, three orders of one organisation's Balance: a public one (reserved, then paid to a supplier), a PRIVATE one
judged by an attestor repository (paid to the same supplier) and a public one paid to a second supplier. Every
transaction is recorded as a cluster's `getTransaction` would give it; knos.observe reads only that record.

tests/data/observe.json is such a record, kept so docs/PRIVACY.md's tables are written from it
(`python -m knos.observe --render-doc`). Record it again with `python tests/test_observe.py` from the repository's root."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

if __name__ == "__main__":
    sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / "src")]

from _order import AUTHOR, DAY, MAINT, OWNER, REPO, USDC, WF_SHA, OrderChain
from solders.keypair import Keypair

from knos import chain as kchain
from knos import flow, observe, records
from knos.settle.v2 import oidc, pay

# the public order: everything about it is meant to be readable
PUBLIC_ISSUE = 3_107
PUBLIC_TERMS = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "build-and-test"}], "mode": "merge", "paths": ["src/billing/**"], "v": 2})
# the private order: its repository, issue, pull request, branch, check and paths must be nowhere
TARGET, TARGET_ID, SECRET_ISSUE, SECRET_PULL, BRANCH = "octo/vault-core", 777_123_456, 48_611_907, 4_112_377, "fix-handle-leak"
SECRET_TERMS = pay.terms_json({"accept": "", "checks": [{"app": 15368, "name": "payroll-export"}], "mode": "merge", "paths": ["src/secret_module/**"], "v": 2})
ATTESTOR, ATTESTOR_ID = "octo/knos-settle", 31_313_131
SALT = hashlib.sha256(b"the salt of tests/test_observe.py").digest()
OTHER = 7_654_321                                      # a second supplier
WALLET_A, WALLET_B = (Keypair.from_seed(bytes([n]) * 32).pubkey() for n in (21, 22))
FIXTURE = Path(__file__).parent / "data" / "observe.json"
HASHED = ("repository: id", "issue", "pull request", "checks named in the terms", "allowed paths", "terms text")
HIDDEN = ("repository: name", "branch")
LEAKS = ("buyer organisation: GitHub id", "buyer organisation: name", "who gave the funding command", "where the money came from (a Balance or a wallet)",
         "supplier (payee): GitHub id", "supplier (payee): wallet", "amount", "fee", "mint (which money)", "funding time", "acceptance time", "review window",
         "workflow commit", "accepted commit", "judge (attestor) repository", "who started the run that judged it", "other orders of the same Balance or wallet",
         "order sizes with this supplier")


class Rec(OrderChain):
    """The order harness, keeping every transaction that succeeded in the shape `getTransaction` (encoding json) has."""

    def __init__(self, **kw):
        self.txs: list[dict] = []
        super().__init__(**kw)

    def send(self, ixs, payer=None, signers=(), tag=None, mark: bool = True) -> bool:
        ixs = [self.marked(ix) for ix in ixs] if mark else list(ixs)
        ok = super().send(ixs, payer, signers, tag, mark=False)
        if ok:
            keys = list(dict.fromkeys([str((payer or self.payer).pubkey()), *(str(a.pubkey) for ix in ixs for a in ix.accounts), *(str(ix.program_id) for ix in ixs)]))
            sig = kchain.b58(hashlib.sha512(b"observe" + len(self.txs).to_bytes(4, "little")).digest())
            self.txs.append({"blockTime": self.now(), "meta": {"err": None, "logMessages": list(self.logs)},
                             "transaction": {"signatures": [sig], "message": {"accountKeys": keys, "instructions": [
                                 {"programIdIndex": keys.index(str(ix.program_id)), "accounts": [keys.index(str(a.pubkey)) for a in ix.accounts],
                                  "data": kchain.b58(bytes(ix.data))} for ix in ixs]}}})
        return ok

    def programs_bytes(self) -> list[bytes]:
        """Every account the two programs own, as it stands."""
        return [bytes(acc.data) for program in (pay.PAY_ID, oidc.OIDC_ID) for _addr, acc in self.svm.get_program_accounts(program)]


class World:
    def __init__(self):
        c = self.c = Rec()
        self.accounts: dict[str, str] = {}
        self.seen: list[bytes] = []                       # the programs' accounts after each step: an order's is closed once paid
        # 1. a public order from the organisation's Balance, reserved by its supplier, paid an hour later
        self.public = c.fund_balance(PUBLIC_ISSUE, 20 * USDC, terms=PUBLIC_TERMS, options=pay.opts(reserve_days=3))
        self.keep(self.public)
        take = c.gh(pay.take_audience(self.public, AUTHOR, 2), repository_id=REPO, actor_id=AUTHOR)
        assert c.send([pay.reserve_ix(c.payer.pubkey(), take, c.key, self.public)]), c.err
        self.keep(self.public)
        c.warp(3600)
        assert c.pay(self.public, [(AUTHOR, 10_000, WALLET_A)]), c.err
        self.keep()
        # 2. a private order of the same Balance, funded and judged from the attestor repository, paid to the same supplier
        c.warp(DAY)
        scope, th = pay.scope_of(TARGET_ID, SECRET_ISSUE, SALT), pay.terms_hash(SECRET_TERMS)
        there = dict(repository_id=ATTESTOR_ID, repository=ATTESTOR, workflow_ref=f"{ATTESTOR}/.github/workflows/knos.yml@refs/heads/main",
                     sub=f"repo:{ATTESTOR}:ref:refs/heads/main")
        tok = c.fund_token(0, 40 * USDC, terms=pay.private_fund_terms(scope, th), options=pay.opts(pay.F_PRIVATE, judge_repo_id=ATTESTOR_ID, salted=True), **there)
        assert c.send([pay.fund_private_order_balance_ix(c.payer.pubkey(), tok, c.key, c.bal, c.usdc, OWNER, scope, th, c.data(tok))]), c.err
        self.private = pay.order_pda(scope, c.bal)
        self.keep(self.private)
        c.warp(7200)
        assert c.pay(self.private, [(AUTHOR, 10_000, WALLET_A)], pr=flow.hidden_pull(SALT, SECRET_PULL), **there), c.err
        self.keep()
        # 3. six days on, a public order paid to a second supplier
        c.warp(6 * DAY)
        self.third = c.fund_balance(PUBLIC_ISSUE + 1, 35 * USDC)
        c.warp(1800)
        assert c.pay(self.third, [(OTHER, 10_000, WALLET_B)], pr=9), c.err
        self.keep()

    def keep(self, order=None) -> None:
        self.seen += self.c.programs_bytes()
        if order is not None:
            self.accounts[str(order)] = self.c.data(order).hex()

    def source(self) -> observe.Recorded:
        return observe.Recorded(self.c.txs, self.accounts)

    def fixture(self) -> dict:
        """What docs/PRIVACY.md is written from: the transactions an order's history needs (the escrow's own, and the
        ones that wrote a token), the two orders' accounts while open, and which is which."""
        def needed(tx: dict) -> bool:
            keys = observe.keys_of(tx)
            return any(keys[ix["programIdIndex"]] == observe.PAY or (keys[ix["programIdIndex"]] == observe.OIDC and ix["data"].startswith("1") and len(ix["data"]) > 60)
                       for ix in tx["transaction"]["message"]["instructions"])
        return {"owner": OWNER, "public": str(self.public), "private": str(self.private), "accounts": self.accounts, "txs": [tx for tx in self.c.txs if needed(tx)]}


_WORLD: list[World] = []


def world() -> World:
    """Built once: nothing here changes it, and LiteSVM takes seconds to verify nine tokens."""
    if not _WORLD:
        _WORLD.append(World())
    return _WORLD[0]


def by_fact(facts: dict) -> dict[str, dict]:
    return {r["fact"]: r for r in facts["rows"]}


class Api:
    """GitHub's public API as a stranger sees it: the public repository and three accounts; anything else is a 404."""
    KNOWN = {f"repositories/{REPO}": {"full_name": "octo/widgets", "owner": {"id": OWNER, "login": "octo"}}, f"user/{OWNER}": {"login": "octo"},
             f"user/{AUTHOR}": {"login": "mona"}, f"user/{OTHER}": {"login": "hubot"}}

    def __init__(self):
        self.asked: list[str] = []

    def __call__(self, path: str) -> dict:
        import urllib.error
        self.asked.append(path)
        if path not in self.KNOWN:
            raise urllib.error.HTTPError(f"https://api.github.com/{path}", 404, "Not Found", None, None)
        return self.KNOWN[path]


def test_every_listed_fact_of_a_public_order_is_found_and_says_where():
    w, api = world(), Api()
    facts = observe.order_facts(w.source(), str(w.public), records.Names(api))
    got = by_fact(facts)
    assert not facts["private"] and facts["order"] == str(w.public) and facts["state"] == "paid"
    assert [r["fact"] for r in facts["rows"] if r["learns"] != observe.YES] == [], "a public order hides nothing"
    assert all(r["value"] and r["where"] for r in facts["rows"])
    start = 1_790_000_000
    want = {"buyer organisation: GitHub id": str(OWNER), "buyer organisation: name": "octo", "who gave the funding command": str(MAINT),
            "where the money came from (a Balance or a wallet)": str(w.c.bal), "repository: id": str(REPO), "repository: name": "octo/widgets",
            "issue": str(PUBLIC_ISSUE), "pull request": "7", "branch": "refs/heads/main", "supplier (payee): GitHub id": str(AUTHOR),
            "supplier (payee): name": "mona", "supplier (payee): wallet": str(WALLET_A), "amount": "20.000000", "fee": "0.060000 on top, paid by the funder",
            "mint (which money)": str(w.c.usdc), "checks named in the terms": "build-and-test", "allowed paths": "src/billing/**",
            "terms text": PUBLIC_TERMS.decode(), "workflow commit": WF_SHA, "accepted commit": "a" * 40,
            "other orders of the same Balance or wallet": "3 in all, 95.000000 funded", "order sizes with this supplier": "2 payments: 20.000000, 40.000000"}
    assert {k: got[k]["value"] for k in want} == want
    assert got["funding time"]["value"].startswith("2026-09-21 ") and got["acceptance time"]["value"].startswith("2026-09-21 ")
    assert start < w.c.txs[-1]["blockTime"] and got["review window"]["value"] == "1 h 00 min from funding to payment; open for work until 2026-10-05 14:13:21 UTC"
    assert got["whether a reservation named someone"]["value"].startswith(f"GitHub id {AUTHOR}, until 2026-09-23 ")
    assert got["judge (attestor) repository"]["value"] == f"octo/widgets (id {REPO})" and got["who started the run that judged it"]["value"] == "mona (id 1234567)"
    # each line says which log line, account field or claim it was read from
    assert got["amount"]["where"] == "`amount=` of the `knos3:funded` log line; bytes 64..72 of the order's account, while the order is open"
    assert "`repository` in the funding token GitHub signed (knos_oidc instruction data)" in got["repository: name"]["where"]
    assert got["supplier (payee): wallet"]["where"] == "`to=` of the `knos3:paid` log line"
    # the lookups are the public API's two id routes, and nothing else
    assert set(api.asked) == {f"repositories/{REPO}", f"user/{OWNER}", f"user/{AUTHOR}"}
    # one of its transactions finds it too; an address the programs never named finds nothing
    paying = next(observe.sig_of(tx) for tx in w.c.txs if any("knos3:paid" in line and str(w.public) in line for line in tx["meta"]["logMessages"]))
    assert observe.order_facts(w.source(), paying)["rows"] == observe.order_facts(w.source(), str(w.public))["rows"]
    for nothing in (str(Keypair.from_seed(bytes([99]) * 32).pubkey()), "not an address", observe.sig_of(w.c.txs[0])):
        try:
            observe.order_facts(w.source(), nothing)
        except LookupError as why:
            assert "No work order was found" in str(why)
        else:
            raise AssertionError(nothing)


def secrets() -> dict[str, list[bytes]]:
    """Every form the private repository's facts could take in bytes: text, and a number as the programs store one."""
    number = lambda n: [str(n).encode(), n.to_bytes(8, "little")]  # noqa: E731
    return {"the repository's name": [TARGET.encode(), b"vault-core"], "the repository's id": number(TARGET_ID), "the issue": number(SECRET_ISSUE),
            "the pull request": number(SECRET_PULL), "the branch": [BRANCH.encode()], "the check's name": [b"payroll-export"],
            "a path": [b"secret_module", b"src/secret"], "the terms": [SECRET_TERMS], "the salt": [SALT, SALT.hex().encode()]}


def found(blobs: list[bytes]) -> list[str]:
    return [name for name, forms in secrets().items() if any(form in blob for form in forms for blob in blobs)]


def test_a_private_order_hides_its_repository_issue_branch_checks_and_paths_and_still_shows_who_was_paid_how_much_and_when():
    w, api = world(), Api()
    facts = observe.order_facts(w.source(), str(w.private), records.Names(api))
    got = by_fact(facts)
    assert facts["private"] and facts["state"] == "paid"
    assert {f: got[f]["learns"] for f in HASHED} == dict.fromkeys(HASHED, observe.HASH) and {f: got[f]["learns"] for f in HIDDEN} == dict.fromkeys(HIDDEN, observe.NO)
    assert got["repository: id"]["value"] == pay.scope_of(TARGET_ID, SECRET_ISSUE, SALT).hex() == got["issue"]["value"]
    assert got["checks named in the terms"]["value"] == pay.terms_hash(SECRET_TERMS).hex() and got["pull request"]["value"] == str(flow.hidden_pull(SALT, SECRET_PULL))
    # what it still shows, said honestly: the money, both parties, the wallet, the times, the attestor, the link to the Balance's other orders
    assert {f: got[f]["learns"] for f in LEAKS} == dict.fromkeys(LEAKS, observe.YES) and set(LEAKS) <= set(facts["still_public"])
    want = {"buyer organisation: GitHub id": str(OWNER), "buyer organisation: name": "octo", "supplier (payee): GitHub id": str(AUTHOR), "supplier (payee): name": "mona",
            "supplier (payee): wallet": str(WALLET_A), "amount": "40.000000", "fee": "0.120000 on top, paid by the funder", "mint (which money)": str(w.c.usdc),
            "judge (attestor) repository": f"{ATTESTOR} (id {ATTESTOR_ID})", "other orders of the same Balance or wallet": "3 in all, 95.000000 funded",
            "order sizes with this supplier": "2 payments: 20.000000, 40.000000", "where the money came from (a Balance or a wallet)": str(w.c.bal)}
    assert {k: got[k]["value"] for k in want} == want
    assert got["funding time"]["value"].startswith("2026-09-22 ") and got["review window"]["value"].startswith("2 h 00 min from funding to payment")
    assert "`repository` in the pay token" in got["judge (attestor) repository"]["where"] and "bytes 184..192" in got["judge (attestor) repository"]["where"]
    assert not any(path.startswith("repositories/") for path in api.asked)          # there is no repository id to look up
    said = "\n".join(observe.table_text(facts))
    assert "A private order hides its repository, issue and terms. It still shows: " in said and "not a guarantee" in said
    # NOT derivable: every byte the programs wrote or were sent. Their accounts after each step, every log line and all
    # instruction data of every transaction (the tokens GitHub signed are in it), and what the observer made of them
    logs = "\n".join(line for tx in w.c.txs for line in tx["meta"]["logMessages"]).encode()
    sent = [observe._unb58(ix["data"]) for tx in w.c.txs for ix in tx["transaction"]["message"]["instructions"]]
    # a token travels as base64 in that data: each one is put together again and read as GitHub signed it
    src = w.source()
    written = {key for tx in w.c.txs if observe._ixs(tx, observe.OIDC) for key in observe.keys_of(tx)}
    tokens = [claims for claims in (observe.token_claims(src, key) for key in sorted(written)) if claims]
    signed = json.dumps(tokens).encode()
    kinds = [str(t.get("aud", "")).split(":")[1] for t in tokens if str(t.get("aud", "")).startswith("knos3:")]
    assert (kinds.count("fund"), kinds.count("pay"), kinds.count("take")) == (3, 3, 1)
    told = json.dumps([facts, observe.graph(observe.events_in(w.c.txs), OWNER), w.fixture()]).encode()
    assert len(w.seen) > 40 and len(sent) > 40 and b"knos3:funded" in logs and any(ATTESTOR.encode() in blob for blob in w.seen)      # the tokens are among them
    assert set(found([SECRET_TERMS + str(TARGET_ID).encode() + SALT])) == {"the repository's id", "the check's name", "a path", "the terms", "the salt"}   # the scan finds what is there
    for where, blobs in (("the programs' accounts", w.seen), ("the log", [logs]), ("instruction data", sent), ("the tokens GitHub signed", [signed]),
                         ("what the observer printed", [told])):
        assert found(blobs) == [], where
    # while the amount, the payee and the attestor are in those same bytes, in the clear
    account = bytes.fromhex(w.accounts[str(w.private)])
    assert (40 * USDC).to_bytes(8, "little") in account and ATTESTOR_ID.to_bytes(8, "little") in account and OWNER.to_bytes(8, "little") in account
    assert f"payee={AUTHOR} amount=40000000 to={WALLET_A}".encode() in logs and ATTESTOR.encode() in signed and str(ATTESTOR_ID).encode() in signed


def test_the_graph_of_three_orders_names_both_counterparties_what_each_was_paid_and_how_often():
    w = world()
    events = observe.events_in(w.c.txs)
    g = observe.graph(events, OWNER, records.Names(Api()))
    assert (g["owner"], g["name"], g["orders"], g["private_orders"], g["funded"], g["sources"], g["paid_by"]) == (OWNER, "octo", 3, 1, "95.000000", [str(w.c.bal)], [])
    first, second = g["pays"]
    assert (first["id"], first["name"], first["wallets"], first["orders"], first["paid"], first["sizes"], first["payments"], first["payments_of_private_orders"]) == \
        (AUTHOR, "mona", [str(WALLET_A)], 2, "60.000000", ["20.000000", "40.000000"], 2, 1)
    assert (second["id"], second["name"], second["wallets"], second["orders"], second["paid"], second["median_days_between"]) == (OTHER, "hubot", [str(WALLET_B)], 1, "35.000000", None)
    assert 1.0 < first["median_days_between"] < 1.2 and first["first"].startswith("2026-09-21") and first["last"].startswith("2026-09-22")
    # the same history read from the supplier's side names its customer
    [buyer] = observe.graph(events, AUTHOR)["paid_by"]
    assert (buyer["id"], buyer["paid"], buyer["orders"]) == (f"gh:{OWNER}", "60.000000", 2) and observe.graph(events, AUTHOR)["pays"] == []
    assert json.loads(json.dumps(g)) == g
    said = "\n".join(observe.graph_text(g))
    assert f"It pays {AUTHOR} (mona): 60.000000 in 2 payments on 2 orders (20.000000, 40.000000)" in said and f"It pays {OTHER} (hubot): 35.000000" in said
    assert observe.graph_text(observe.graph(events, 5))[1] == "The escrow's history that was read shows no payment from or to this id."


def shape(fixture: dict) -> list:
    """The tables without what differs from one recording to the next (addresses the harness draws at random)."""
    src = observe.Recorded(fixture["txs"], fixture["accounts"])
    tables = [[(r["fact"], r["learns"], r["where"]) for r in observe.order_facts(src, fixture[which])["rows"]] for which in ("public", "private")]
    g = observe.graph(observe.events_in(fixture["txs"]), fixture["owner"])
    return [*tables, [(c["id"], c["orders"], c["paid"], c["sizes"], c["first"], c["last"], c["median_days_between"]) for c in g["pays"]]]


def test_the_tables_in_the_privacy_document_are_the_commands_and_the_record_they_come_from_is_what_the_programs_write():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    doc = observe.DOC.read_text(encoding="utf-8")
    assert observe.render_doc(doc, fixture) == doc, "docs/PRIVACY.md is stale: run python -m knos.observe --render-doc"
    assert observe.main(["--render-doc", "--check"]) == 0 and observe.main([]) == 2
    for name, block in observe.doc_blocks(fixture).items():
        assert block in doc and block.count("\n") > 2, name
    # the kept record says what a run of the programs says today: the same facts, verdicts and sources, the same graph
    assert shape(fixture) == shape(world().fixture())
    assert found([json.dumps(fixture).encode(), doc.encode()]) == []
    # the trimmed record loses nothing the tables need
    w = world()
    for order in (w.public, w.private):
        assert observe.order_facts(observe.Recorded(**{k: w.fixture()[k] for k in ("txs", "accounts")}), str(order)) == observe.order_facts(w.source(), str(order))


# an issue's bounty on the public program ids, as devnet logged it (knos-e2e issue 211, funded from the faucet's Balance
# by comment and paid on merge): a job's knos2 lines, which carry no `order`
FAUCET_BALANCE, BOUNTY_ESCROW, BOUNTY_REPO, BOUNTY_OWNER = ("EuuemHS1W5j6BRrtJadXZ59AxXphWa3pEdKTyHzd8HyU", "79ELTFsEMBz1xZL4jUL5HHKUd71My8QrNPaaJvJkiraF",
                                                            1_401_439_243, 142_920_951)
BOUNTY_TXS = (("v9QEbniaNfaQYsKHaj2HtXF9E4edxR5XsWNBmARv1x2Po9EMYv3k8wsBPzptVxJL1hGMJwNpyYk1mX1TYjR9kdJ", 1_791_150_973,
               [f"knos2:funded repo={BOUNTY_REPO} issue=211 amount=5000000 mode=0 by={BOUNTY_OWNER} source={FAUCET_BALANCE} faucet=1",
                'knos2:terms {"accept":"","checks":[{"app":15368,"name":"test"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":[],"reserve":7,"v":1}']),
              ("5bRp3jUS1z9zpeXkTJ2HCEzuepzaLEGxDGsSPmJNrCY9kYes6dC57pfD3ox8Y8tEbHPn2dcAkrKJ8FdmUVfg82zw", 1_791_151_032,
               [f"knos2:paid repo={BOUNTY_REPO} issue=211 payee={BOUNTY_OWNER} amount=4875000 fee=125000 to=9a6RmArU8cfKGqWRfXU2i8xGXsvVFiNs97ZMVuYyozcW"]))


def _bounty_txs() -> list[dict]:
    program = str(pay.PAY_ID)
    return [{"blockTime": at, "transaction": {"signatures": [sig], "message": {"accountKeys": [str(Keypair.from_seed(bytes([9]) * 32).pubkey()), BOUNTY_ESCROW, program]}},
             "meta": {"err": None, "logMessages": [f"Program {program} invoke [1]", *(f"Program log: {line}" for line in lines), f"Program {program} success"]}}
            for sig, at, lines in BOUNTY_TXS]


def test_an_issues_bounty_is_in_the_graph_and_its_address_is_named_a_bounty_never_nothing():
    """The first real run (0.3.15) on the public program ids: every payment there is an issue's bounty, and `knos observe`
    said of a funded and paid one that the programs logged nothing about it, and of its funder that nothing was paid."""
    txs = _bounty_txs()
    g = observe.graph(observe.events_in(txs), BOUNTY_OWNER)
    assert (g["orders"], g["bounties"], g["funded"], g["sources"]) == (0, 1, "5.000000", [FAUCET_BALANCE])
    [paid] = g["pays"]
    assert (paid["id"], paid["paid"], paid["orders"], paid["wallets"]) == (BOUNTY_OWNER, "4.875000", 1, ["9a6RmArU8cfKGqWRfXU2i8xGXsvVFiNs97ZMVuYyozcW"])
    said = observe.graph_text(g)
    assert said[0] == f"GitHub id {BOUNTY_OWNER}: 0 work orders and 1 bounty on an issue funded from its Balances (0 private), 5.000000 in all."
    assert all("shows no payment" not in line for line in said)
    src = observe.Recorded(txs)
    for target in (BOUNTY_ESCROW, BOUNTY_TXS[1][0]):
        with pytest.raises(LookupError, match=rf"{target} is an issue's bounty \(repository id {BOUNTY_REPO}, issue 211\), not a work order") as why:
            observe.order_facts(src, target)
        assert "logged nothing" not in str(why.value)
    # nothing at all is still nothing
    with pytest.raises(LookupError, match="No work order was found"):
        observe.order_facts(observe.Recorded([]), BOUNTY_ESCROW)


def test_the_command_prints_the_table_and_the_graph_as_text_and_as_json(monkeypatch):
    import typer
    from typer.testing import CliRunner
    w = world()
    app, lines = typer.Typer(), []
    app.command("other")(lambda: None)
    observe.register(app, lines)
    assert [(name, panel) for name, panel, _line in lines] == [("observe", "For money")]
    monkeypatch.setattr(observe, "Rpc", lambda url: w.source())
    monkeypatch.setattr(records, "history", lambda url, program, limit: (observe.events_in(w.c.txs), 0, False))
    run = lambda *args: CliRunner().invoke(app, ["observe", *args, "--rpc", "http://localhost:1", "--offline"])  # noqa: E731
    got = run(str(w.private))
    assert got.exit_code == 0, got.output
    assert f"Work order {w.private} (private, paid)" in got.output and "only a hash" in got.output and "not looked up (--offline)" in got.output
    assert json.loads(run(str(w.public), "--json").output)["rows"] == observe.order_facts(w.source(), str(w.public))["rows"]
    g = json.loads(run("--graph", str(OWNER), "--json").output)
    assert [c["id"] for c in g["pays"]] == [AUTHOR, OTHER] and (g["unread"], g["history_cut"]) == (0, False)
    assert f"It pays {AUTHOR}: 60.000000 in 2 payments" in run("--graph", str(OWNER)).output


if __name__ == "__main__":
    FIXTURE.write_text(json.dumps(World().fixture(), indent=0, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {FIXTURE}. Now: python -m knos.observe --render-doc")
