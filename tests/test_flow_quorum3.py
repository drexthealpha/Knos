"""Two things a funding comment could not reach before, each from the comment to the program (knos_pay 2.1 in LiteSVM):

  1. `quorum 3 judge: owner/repo`: three independent readers. The comment names the judge repository, GitHub's API
     gives its id, the id goes into the order's options (the 48 bytes the fund token signs and the program reads:
     order.rs `judge_repo_id`, order_judge.rs judge c), and the order pays only after the buyer's run, a neutral run
     and the judge repository's run have each passed the same pull request. Two readers of one owner are one.
  2. An outcome that is not code (examples/outcomes/data-labelling): the comment `knos terms show data-labelling`
     gives funds an order on that example's black-box suite; the cheating file that passes the naive check is
     refused and not paid; the honest one is paid. The deliverable and the evaluation the meter would count are named.

The flow runs against tests/_flow.py's GitHub and relay; what it signed is then presented to the real program in
tests/_order.py's chain: the terms bytes hash to what the fund token names, and the options are the comment's.
Never run on devnet, and never by a customer: these are tests."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from solders.pubkey import Pubkey  # noqa: E402

from _flow import HUBOT, MONA, REPO_ID, GitHub, World, check, key  # noqa: E402
from _hub import user  # noqa: E402
from _order import MAINT, OWNER, REPO, USDC, OrderChain, code, issue  # noqa: E402
from _order import user as stranger  # noqa: E402
from test_flow import FAUCET, plain  # noqa: E402

from knos import commands, flow, judge, ledger, terms, terms_templates  # noqa: E402
from knos.settle.v2 import order_auto, pay  # noqa: E402

CLAIMS = 85                                           # lib.rs E_CLAIMS
ROOT = Path(__file__).resolve().parents[1]
ACME = user("acme", 9001, "Organization")             # owns the judge repository: neither the buyer nor the seller
JUDGE = {"id": 31_313_131, "full_name": "acme/judge", "owner": ACME, "default_branch": "main"}
COMMENT = "/knos fund 20 checks: test quorum 3 judge: acme/judge"


class Hub3(GitHub):
    """tests/_flow.py's GitHub, which also knows other repositories by name (`others`: full name -> GET /repos/<name>)."""
    others: dict = {}

    def __call__(self, path: str, data: dict | None = None, method: str | None = None):
        name = path[len("repos/"):] if path.startswith("repos/") else ""
        if data is None and name in self.others:
            self.asked.append(path)
            return self.others[name]
        return super().__call__(path, data, method)


def world(tmp_path, **others) -> World:
    w = World(tmp_path)
    w.version = 1
    w.hub.__class__ = Hub3
    w.hub.others = {"acme/judge": JUDGE, **others}
    w.hub.issue(7, "Slugify keeps punctuation.")
    w.hub.required = [{"context": "test", "integration_id": 15368}]
    return w


def said(w: World, n: int, who_: dict, body: str, most: int = 4000) -> str:
    assert flow.command(w.run(w.hub.commented(n, who_, body))) == 0
    return plain(w.hub.knos(n)[-1], most)


def paid_to(c: OrderChain, wallet: Pubkey) -> int:
    return c.balance(pay.ata(wallet, c.usdc))


def present(c: OrderChain, order: Pubkey, payees, **over) -> bool:
    return c.send([c.pay_ix(order, c.pay_token(order, payees, **over), payees)])


# ---- 1. a quorum of three ---------------------------------------------------------------------------------------------

def test_the_comment_reads_a_judge_repository_and_says_what_is_missing():
    got = commands.parse("/knos fund 200 checks: test quorum 3 judge: owner/repo", on_pull=False)
    assert isinstance(got, commands.Fund) and (got.units, got.checks, got.quorum, got.judge) == (200_000_000, ("test",), 3, "owner/repo")
    for text in ("/knos fund 20 quorum 3 judge acme/judge", "/knos fund 20 judge: https://github.com/acme/judge quorum 3"):
        assert commands.parse(text, on_pull=False).judge == "acme/judge", text
    bad = commands.parse("/knos fund 20 quorum 3 judge:", on_pull=False)
    assert isinstance(bad, commands.Error) and "`judge` needs a repository after it, like `judge: owner/repo`" in bad.reply
    assert "`judge` is written twice" in commands.parse("/knos fund 20 judge: a/b judge: c/d", on_pull=False).reply
    assert "`judge` is not something this command takes" in commands.parse("/knos offer @acme rate 5 budget 20 judge: a/b", on_pull=False).reply


def test_a_fund_comment_names_the_third_reader_and_the_program_takes_exactly_what_it_signed(tmp_path):
    w = world(tmp_path)
    got = said(w, 7, HUBOT, COMMENT)
    order = pay.order_pda(pay.scope_of(REPO_ID, 7), FAUCET, 0)
    raw = w.chain.logs[str(order)]
    options = pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(3), reserve_days=7, judge_repo_id=JUDGE["id"])
    # the name was resolved through GitHub's API, and its id is in the options the fund token signs; the terms hash is the terms'
    assert "repos/acme/judge" in w.hub.asked
    assert w.signer.asked == [pay.order_fund_audience(7, 20_000_000, pay.MERGE, pay.terms_hash(raw), FAUCET, 14 * 86_400, 0, options)]
    (_a, o), = w.chain.orders(7)
    assert o.judge_repo_id == JUDGE["id"] and order_auto.quorum_of(o.flags) == 3 and o.flags & pay.F_NEUTRAL
    assert "judge" not in terms.parse(raw)                 # the judge is an option of the order, where the program reads it
    # the terms sentence says who the three readers are
    sentence, = terms.describe_options(False, 3, True, "acme/judge")
    assert sentence in got
    assert sentence.startswith("It is paid only after three independent readers have each passed the same pull request at the same commit, "
                               "all of these: 1. this repository's own run; 2. a neutral run that someone other than its funder starts by hand")
    assert "3. a run in acme/judge, the judge repository named at funding" in sentence and "two repositories of one owner are one reader" in sentence

    # the program: the same terms bytes and the same 48 bytes, funded by a comment's token from a Balance
    c = OrderChain()
    n = issue()
    on_chain = c.fund_balance(n, 20 * USDC, terms=raw, options=options)
    made = c.order(on_chain)
    assert made.terms.hex() == pay.terms_hash(raw).hex() == w.signer.asked[0].split(":")[5]       # comment -> terms -> the program's hash
    assert made.judge_repo_id == JUDGE["id"] and order_auto.quorum_of(made.flags) == 3
    assert w.signer.asked[0].split(":")[9] == options.hex()
    author, wallet = stranger(), key("quorum3 wallet 1")
    payees = [(author, 10_000, wallet)]
    # a: the buyer repository's run. b: a neutral run the seller starts in a repository of their own. Two of three: nothing is paid
    assert present(c, on_chain, payees), c.err
    assert c.said("knos3:quorum") == [f"knos3:quorum order={on_chain} judge=0 have=1 of=3"] and paid_to(c, wallet) == 0
    assert present(c, on_chain, payees, **c.neutral(author)), c.err
    assert c.said("knos3:quorum") == [f"knos3:quorum order={on_chain} judge=1 have=2 of=3"] and paid_to(c, wallet) == 0
    assert present(c, on_chain, payees, **c.neutral(author)), c.err      # the same reader again counts once
    assert paid_to(c, wallet) == 0 and c.order(on_chain).state == "open"
    # a run in a repository that is not the one named is no judge of this order
    assert not present(c, on_chain, payees, repository_id=JUDGE["id"] + 1, file="attest.yml", event_name="push") and code(c) == CLAIMS
    # c: the judge repository the comment named. Now all three have passed the same pull request: paid
    # (its owner is a third account: neither the buyer nor the seller. A judge repository of the buyer's would be no third reader)
    assert present(c, on_chain, payees, repository_id=JUDGE["id"], repository_owner_id=9_000, file="attest.yml", event_name="push"), c.err
    assert paid_to(c, wallet) == 20 * USDC and c.order(on_chain) is None and c.said("knos3:settled")[0].endswith("judge=2")


def test_two_readers_of_one_owner_are_one_and_the_order_is_not_paid(tmp_path):
    c = OrderChain()
    options = pay.opts(pay.F_NEUTRAL | order_auto.quorum_flags(3), reserve_days=7, judge_repo_id=JUDGE["id"])
    order = c.fund_balance(issue(), 20 * USDC, options=options)
    author, wallet = stranger(), key("quorum3 wallet 2")
    payees = [(author, 10_000, wallet)]
    assert present(c, order, payees), c.err                                                       # a: the buyer's run
    assert present(c, order, payees, repository_id=JUDGE["id"], file="attest.yml", event_name="push"), c.err     # c: the judge repository
    # the judge repository belongs to the owner of the order's repository: two repositories of one owner are one reader
    assert c.said("knos3:quorum") == [f"knos3:quorum order={order} judge=2 have=1 of=3"]
    # the "neutral" run is the buyer's again: started by the Balance's owner, by the funder, or in the order's own repository
    for over in (c.neutral(OWNER), c.neutral(MAINT), c.neutral(author, REPO)):
        assert not present(c, order, payees, **over) and code(c) == CLAIMS, over
    assert paid_to(c, wallet) == 0 and c.order(order).state == "open" and c.quorum(order)[1] is None
    # someone else's run is a second owner's, not a third: the judge repository is still the buyer's
    assert present(c, order, payees, **c.neutral(author)), c.err
    assert c.said("knos3:quorum") == [f"knos3:quorum order={order} judge=1 have=2 of=3"] and paid_to(c, wallet) == 0
    # a third owner's run in the judge repository is the third reader
    assert present(c, order, payees, repository_id=JUDGE["id"], repository_owner_id=9_000, file="attest.yml", event_name="push"), c.err
    assert paid_to(c, wallet) == 20 * USDC

    # the chain does not know who owns a repository, so a judge repository of one of the sides is refused at funding, in words
    mine, funders, takers = ({"id": n, "full_name": f"x/j{n}", "owner": who_, "default_branch": "main"} for n, who_ in ((1, HUBOT), (2, MONA), (3, ACME)))
    w = world(tmp_path, **{"hubot/judge": mine, "mona/judge": funders, "o/r": {"id": REPO_ID, "full_name": "o/r", "owner": HUBOT, "default_branch": "main"}})
    w.hub.can["mona"] = "write"
    again = "Name a repository that someone else owns, then post the comment again."
    assert said(w, 7, HUBOT, "/knos fund 20 quorum 3 judge: hubot/judge") == (
        "Knos: nothing was funded. `judge: hubot/judge` belongs to @hubot, and so does a side of this order (this repository's owner). Two "
        f"accounts of one owner are one judge, not two. {again}")
    assert ("`judge: mona/judge` belongs to @mona, and so does a side of this order (you, the funder). Two accounts of one owner are one judge, "
            "not two.") in said(w, 7, MONA, "/knos fund 20 quorum 3 judge: mona/judge")
    assert said(w, 7, HUBOT, "/knos fund 20 quorum 3 judge: o/r") == (
        f"Knos: nothing was funded. `judge: o/r` is this repository, and its own run is already one of the readers: it would count once. {again}")
    w.hub.issues[7]["assignees"] = [ACME]                   # whoever holds the issue is who would be paid
    assert "belongs to @acme, and so does a side of this order (@acme, who holds this issue and would be paid)" in said(w, 7, HUBOT, COMMENT)
    w.hub.issues[7]["assignees"] = []
    # no judge named, a name GitHub does not know, a judge with no quorum, and a quorum the readers cannot reach
    assert ("`quorum 3` asks for three different judges, and this order can have 2: this repository's own run, and a neutral run anyone can "
            "start. No judge repository is named for the third: add `judge: owner/repo`, a repository that neither you nor this repository's "
            "owner owns, or comment it with `quorum 2`, then post the comment again.") in said(w, 7, HUBOT, "/knos fund 20 quorum 3")
    assert "GitHub gave no repository named nobody/here that this run can read (the judge)" in said(w, 7, HUBOT, "/knos fund 20 quorum 3 judge: nobody/here")
    assert ("`judge:` names a reader of a quorum, and this comment asks for no quorum: on its own, that repository's run could have the order "
            "paid. Add `quorum 2` or `quorum 3`, or leave out `judge:`") in said(w, 7, HUBOT, "/knos fund 20 judge: acme/judge")
    assert ("`quorum 3` asks for three different judges, and this order can have 2: this repository's own run (you said `neutral off`), and the "
            "judge repository acme/judge. Leave out `neutral off`, then") in said(w, 7, HUBOT, COMMENT + " neutral off")
    assert w.signer.asked == [] and w.chain.orders() == []
    # two of the three, with no neutral run: the buyer's run and the judge repository's
    got = said(w, 7, HUBOT, "/knos fund 20 quorum 2 neutral off judge: acme/judge")
    assert terms.describe_options(False, 2, False, "acme/judge")[0] in got and "all of these: 1. this repository's own run; 2. a run in acme/judge" in got
    assert w.signer.asked[0].endswith(pay.opts(order_auto.quorum_flags(2), reserve_days=7, judge_repo_id=JUDGE["id"]).hex())
    # a chain without work orders says so, and a judge is never silently dropped
    w.version = 0
    assert "`auto`, `quorum` and `judge` are options of a work order" in said(w, 7, HUBOT, COMMENT)


# ---- 2. a labelled dataset, funded by a comment and paid by its black-box suite ---------------------------------------

LAB = ROOT / "examples" / "outcomes" / "data-labelling"
SUITE, NAIVE = 1, 2


def verdict(tmp: Path, folder: str, suite: int) -> bool:
    """`knos proof judge`, the command the pinned workflow runs, on the example's base with a submission laid over it."""
    import contextlib
    import io
    import shutil

    from knos.cli import main as knos
    base, pr = tmp / "base", tmp / "pr"
    shutil.copytree(LAB / "base", base)
    shutil.copytree(LAB / "base", pr)
    shutil.copytree(LAB / folder, pr, dirs_exist_ok=True)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return knos(["proof", "judge", "--base", str(base), "--pr", str(pr), "--issue", str(suite)]) == 0


@pytest.mark.skipif(os.name == "nt", reason="the suite runs `$KNOS_RUN python3 ...`: the judge's machine is Linux or macOS")
def test_a_labelled_dataset_is_funded_by_a_comment_and_only_the_honest_file_is_paid(tmp_path):
    template = terms_templates.get("data-labelling")
    doc = json.loads((LAB / "terms.json").read_text(encoding="utf-8"))
    assert template.comment == doc["comment"] == "/knos fund 40 checks: none"
    bundle = LAB / "base" / ".knos" / "acceptance" / str(SUITE)
    # the buyer's repository carries the example's black-box suite for issue 1, and the comment funds an order on it
    w = World(tmp_path / "flow")
    w.version = 1
    w.hub.issue(SUITE, "Label 400 support messages.")
    w.hub.bundles[SUITE] = {p.name: p.read_bytes() for p in sorted(bundle.iterdir()) if p.is_file()}
    w.hub.contents[".knos/proof.toml"] = (LAB / "base" / ".knos" / "proof.toml").read_text(encoding="utf-8")
    got = said(w, SUITE, HUBOT, template.comment)
    order = pay.order_pda(pay.scope_of(REPO_ID, SUITE), FAUCET, 0)
    raw = w.chain.logs[str(order)]
    assert raw.decode() == doc["terms_json"] == terms_templates.export("data-labelling")["terms_json"]
    assert terms.parse(raw)["accept"] == judge.checks_hash(bundle) and pay.terms_hash(raw).hex() == doc["terms_hash"]
    assert w.signer.asked == [pay.order_fund_audience(SUITE, 40_000_000, pay.TESTS, pay.terms_hash(raw), FAUCET, 14 * 86_400, 0,
                                                      pay.opts(pay.F_NEUTRAL, reserve_days=7))]
    assert "is in escrow for issue #1 as a work order" in got and "Judge: black-box." in got
    w.chain.bind(MONA)
    w.clock.sleep(3600)

    # the same terms and options in the program, funded by a comment's token
    c = OrderChain()
    n = issue()
    on_chain = c.fund_balance(n, 40 * USDC, terms=raw, mode=pay.TESTS, options=pay.opts(pay.F_NEUTRAL, reserve_days=7))
    assert c.order(on_chain).terms.hex() == doc["terms_hash"] and c.order(on_chain).mode == pay.TESTS
    wallet = key("quorum3 wallet 3")

    # the cheating file: it copies the 40 visible answers. The naive check accepts it; the suite the order is funded on does not
    cheat = w.hub.pull(12, MONA, "Fixes #1")["head"]["sha"]
    w.hub.files[12] = [{"filename": "labels.csv", "patch": "@@ -0,0 +1 @@\n+id,label"}]
    w.hub.checks[cheat] = [check("test")]
    assert verdict(tmp_path / "cheat-naive", "cheats/special_cases_visible", NAIVE)
    assert not verdict(tmp_path / "cheat-suite", "cheats/special_cases_visible", SUITE)
    # so the job that signs never runs for it: nothing was signed, nothing was paid, here or in the program
    assert len(w.signer.asked) == 1 and w.chain.orders(SUITE)[0][1].state == "open"
    assert paid_to(c, wallet) == 0 and c.held(on_chain) == 40 * USDC + pay.order_fee(40 * USDC)

    # the honest file: the suite passes it, the job after the judge signs for that commit, and the order pays
    honest = w.hub.pull(13, MONA, "Fixes #1")["head"]["sha"]
    w.hub.files[13] = [{"filename": "labels.csv", "patch": "@@ -0,0 +1 @@\n+id,label"}, {"filename": "label.py", "patch": "@@ -0,0 +1 @@\n+import csv"}]
    w.hub.checks[honest] = [check("test")]
    assert verdict(tmp_path / "honest-suite", "solution", SUITE)
    assert flow.settle(w.run(w.hub.ran(13)), tests=True, pull=13, head=honest, issue=SUITE) == 0
    assert w.signer.asked[1] == pay.order_pay_audience(order, honest, pay.terms_hash(raw), pay.TESTS, 13, [(MONA["id"], 10_000, None)])
    assert plain(w.hub.knos(13)[-1], 1500).startswith("Knos: paid. @mona received 40.00 test USDC for issue #1, in full") and w.chain.orders() == []
    # the program takes a token with those fields (the commit, the terms hash, mode 1, the pull request, one payee) and pays in full
    payees = [(MONA["id"], 10_000, wallet)]
    assert present(c, on_chain, payees, head_sha=honest, pr=13), c.err
    assert paid_to(c, wallet) == 40 * USDC and c.order(on_chain) is None
    # a token for the cheating commit would have named another artifact; with the order closed there is nothing left to take
    assert not c.send([pay.pay_order_ix(c.payer.pubkey(), c.pay_token(on_chain, payees, o=made_for(raw), head_sha=cheat, pr=12), c.key, on_chain,
                                        made_for(raw), c.wallets(payees))])
    assert paid_to(c, wallet) == 40 * USDC

    # what the meter would count: one deliverable (the order and its milestone), two evaluations under one policy (the terms' hash)
    rate, policy_ = 40_000_000, pay.terms_hash(raw).hex()
    refused, accepted = (ledger.Evaluation(HUBOT["id"], MONA["id"], bytes(order).hex(), artifact, policy_, 0, ok, rate)
                         for artifact, ok in ((cheat, False), (honest, True)))
    deliverable = ledger.deliverable_id(bytes(order), 0).hex()
    assert refused.deliverable == accepted.deliverable == deliverable and len(deliverable) == 64
    assert refused.id != accepted.id and accepted.id == ledger.eval_id(bytes(order), honest, bytes.fromhex(policy_), 0)
    assert (accepted.value, refused.value) == (rate, 0)
    assert accepted.audience() == f"knosm:eval:{HUBOT['id']}:{MONA['id']}:{bytes(order).hex()}:{honest}:{policy_}:0:1:{rate}"
    assert refused.audience().endswith(f":{cheat}:{policy_}:0:0:{rate}")
    line = json.loads(accepted.line())
    assert (line["deliverable"], line["policy"], line["artifact"], line["accepted"], line["rate"]) == (deliverable, doc["terms_hash"], honest, 1, rate)
    assert ledger.parse(accepted.line()) == accepted and not ledger.parse(refused.line()).accepted


def made_for(raw: bytes):
    """An order as the closed one was, for building a token and an instruction after it is gone."""
    c = OrderChain()
    return c.order(c.fund_balance(issue(), 40 * USDC, terms=raw, mode=pay.TESTS, options=pay.opts(pay.F_NEUTRAL, reserve_days=7)))


@pytest.mark.parametrize("name", sorted(terms_templates.OUTCOMES))
def test_each_outcome_has_a_template_whose_terms_are_the_examples_own(name):
    from typer.testing import CliRunner

    from knos.cli import app
    root = ROOT / "examples" / "outcomes" / name
    doc, held = json.loads((root / "terms.json").read_text(encoding="utf-8")), terms_templates.export(name)
    assert held["terms"]["accept"] == judge.checks_hash(root / "base" / ".knos" / "acceptance" / "1")
    assert (held["comment"], held["sentence"], held["terms_json"], held["terms_hash"]) == (doc["comment"], doc["sentence"], doc["terms_json"], doc["terms_hash"])
    cmd = commands.parse(held["comment"], on_pull=False)
    assert isinstance(cmd, commands.Fund) and cmd.checks == () and held["terms"]["mode"] == "tests"
    shown = CliRunner().invoke(app, ["terms", "show", name])
    assert shown.exit_code == 0 and all(held[k] in shown.output for k in ("comment", "terms_json", "terms_hash", "sentence"))
    assert name not in terms_templates.TEMPLATES and name in CliRunner().invoke(app, ["terms", "list"]).output
    text = (ROOT / "docs" / "OUTCOMES.md").read_text(encoding="utf-8")
    assert f"`knos terms show {name}`" in text and held["comment"] in text
    assert "never on devnet" in text and "never by a customer" in text
