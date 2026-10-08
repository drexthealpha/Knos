"""The enforcement matrix (knos.enforce): the table is whole, what it names exists in the source, the page and the JSON
are the table, and for the cells that claim something stops money, an attempt to get round it by another route.

The tests that send instructions run the committed program builds in LiteSVM and are skipped without it; every other
test here is the workflow's own code against the fakes of tests/_flow.py.
"""
from __future__ import annotations

import ast
import base64
import dataclasses
import json
import re
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from knos import approvals, controls, enforce, flow  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402

U = 1_000_000
PROC = controls.PROCUREMENT
MEI, DANA = {"login": "mei-acme", "id": 9001}, {"login": "dana-acme", "id": 9002}
POLICY = {"version": 1, "kind": "approval-policy", "currency": "test USDC", "self_approval_limit": 0,
          "roles": {"requester": [{"account": "hubot"}], "approver": [{"account": "mei-acme"}, {"account": "hubot"}], "finance": [{"account": "dana-acme"}]},
          "thresholds": [{"approvers": 1}]}
FILES = {f"{PROC}/policy.yaml": controls.dump_yaml(POLICY)}


class Files:
    """A repository with files under .knos/procurement/ on its default branch: GitHub's contents API for that folder
    (a listing for a folder, the file for a file), one comment by its id, and the hub behind it for everything else."""

    def __init__(self, hub, repo: str, files: dict[str, str]):
        self.hub, self.repo, self.files = hub, repo, files

    def __getattr__(self, name: str):
        return getattr(self.hub, name)

    def __call__(self, path: str, data: dict | None = None, method: str | None = None):
        at = f"repos/{self.repo}/contents/{PROC}"
        if path.startswith(f"repos/{self.repo}/issues/comments/") and data is None and method is None:
            return next((c for cs in self.hub.comments.values() for c in cs if str(c["id"]) == path.rsplit("/", 1)[1]), None)
        if not path.startswith(at):
            return self.hub(path, data, method) if method else self.hub(path, data)
        name = path[len(f"repos/{self.repo}/contents/"):].partition("?")[0]
        if name in self.files:
            return {"encoding": "base64", "content": base64.b64encode(self.files[name].encode()).decode()}
        under = sorted({f[len(name) + 1:].split("/")[0] for f in self.files if f.startswith(name + "/")})
        if not under:
            raise urllib.error.HTTPError(path, 404, "Not Found", None, None)       # type: ignore[arg-type]
        return [{"path": f"{name}/{x}", "type": "file" if f"{name}/{x}" in self.files else "dir"} for x in under]


def approved(hub, files: dict[str, str], n: int, subject: str, amount: int, requester: str = "hubot", by: dict = MEI) -> dict[str, str]:
    """`files` with one more approval in the log: `by` comments on `n`, and the event is taken from that comment."""
    c = hub.say(n, by, f"/knos approve {subject}")
    e, why = approvals.from_comment(POLICY, c, subject=subject, requester=requester, amount=amount, policy_text=files[f"{PROC}/policy.yaml"])
    assert e is not None, why
    return {**files, f"{PROC}/{approvals.LOG}": files.get(f"{PROC}/{approvals.LOG}", "") + json.dumps(e) + "\n"}


# ---- the table ----------------------------------------------------------------------------------------------------------
def cells():
    return [(r, x, c) for r, row in enforce.CELLS.items() for x, c in row.items()]


def test_the_table_is_whole_and_every_cell_is_one_class():
    assert enforce.problems() == []
    assert [r for r, _n, _h in enforce.ROUTES] == list(enforce.CELLS) and len(enforce.ROUTES) == 14 and len(enforce.RESTRICTIONS) == 9
    assert all(list(row) == [x for x, _n in enforce.RESTRICTIONS] for row in enforce.CELLS.values())
    n = enforce.counts()
    assert sum(n.values()) == 126 and all(n[c] for c in enforce.CLASSES), n
    assert all(c.test for _r, _x, c in cells() if c.cls != "outside")
    # the brief's own routes are all there
    assert {"wallet", "comment", "offer", "topup", "private", "balance", "netted", "advance", "passkey", "direct"} <= set(enforce.CELLS)
    # the enterprise route set: money in a Squads vault, its Balance, and an allowance
    assert {"vault", "vault_balance", "allowance"} <= set(enforce.CELLS)
    # and the page draws those three under the group's row, as the note "Enterprise-controlled funds" names them
    grouped = [r["name"] for r in enforce.as_json()["routes"] if r.get("group") == "enterprise"]
    assert grouped == ["Enterprise vault, by vote", "Enterprise vault's Balance", "A Squads allowance"]
    assert all(f"{name}" in next(n for n in enforce.NOTES if n.startswith("Enterprise-controlled funds.")) for name in grouped)


def test_every_test_a_cell_names_exists():
    seen: dict[str, set[str]] = {}
    for route, x, c in cells():
        if not c.test:
            continue
        file, _, name = c.test.partition("::")
        if file not in seen:
            assert (ROOT / file).is_file(), (route, x, file)
            seen[file] = {n.name for n in ast.walk(ast.parse((ROOT / file).read_text(encoding="utf-8"))) if isinstance(n, ast.FunctionDef)}
        assert name in seen[file], (route, x, c.test)


def test_a_program_cell_names_instructions_the_program_dispatches_and_errors_it_has():
    lib = (ROOT / "programs-v2/knos_pay/src/lib.rs").read_text(encoding="utf-8")
    tags = {int(n): fn for n, fn in re.findall(r"^\s+(\d+) => \w+::(\w+)\(", lib, re.M)}
    assert len(tags) >= 28
    snake = lambda name: re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()  # noqa: E731
    texts = [c.by for _r, _x, c in cells()] + [how for _i, _n, how in enforce.ROUTES]
    named = [(name, int(n)) for t in texts for name, n in re.findall(r"\b([A-Z][A-Za-z]+) \((\d+)\)", t)]
    assert len(named) > 40
    for name, n in named:
        assert tags.get(n) == snake(name), (name, n, tags.get(n))
    for t in texts:
        for found in re.findall(r"errors? (\d+)(?: (?:and|to) (\d+))?", t):
            assert all(int(e) in pay.ERRORS for e in found if e), t
    for route, x, c in cells():
        if c.cls == "program":
            assert re.search(r"knos_pay|knos_passkey|Squads v4", c.by) and (re.search(r"\(\d+\)", c.by) or re.search("knos_passkey|Squads v4", c.by)), (route, x)
        else:       # nothing but a `program` cell opens by naming a program
            assert not c.by.startswith(("knos_pay", "knos_passkey", "Squads v4")), (route, x)
    # every Squads v4 instruction a cell names is one tests/_squads.py sends to the deployed Squads build
    harness = (ROOT / "tests/_squads.py").read_text(encoding="utf-8")
    squads = {name for t in texts for name in re.findall(r"Squads v4 (?:\w+ )?([A-Z][a-z]+(?:[A-Z][a-z]+)+)", t)} | \
             {name for t in texts if "Squads v4" in t for name in re.findall(r"\b(ProposalApprove|VaultTransaction\w+|SpendingLimitUse)\b", t)}
    assert {"VaultTransactionExecute", "ProposalApprove", "SpendingLimitUse", "VaultTransactionCreate"} <= squads, squads
    for name in squads:
        assert f'"global", "{snake(name)}"' in harness, name


def test_a_workflow_cell_names_a_job_of_a_workflow_and_every_function_named_anywhere_exists():
    for route, x, c in cells():
        if c.cls == "workflow":
            found = re.findall(r"\b(\w+\.yml) job `(\w+)`", c.by)
            assert found and "`flow." in c.by, (route, x)
            for file, job in found:
                assert re.search(rf"^  {job}:$", (ROOT / ".github/workflows" / file).read_text(encoding="utf-8"), re.M), (file, job)
        for mod, name in re.findall(r"`(flow|approvals)\.(\w+)`", c.by):
            assert callable(getattr({"flow": flow, "approvals": approvals}[mod], name)), (route, x, name)
    # the pinned funding workflow is the one the repository's own workflow file calls, and it runs `knos command`
    assert re.search(r"uses: [\w-]+/knos-workflows/\.github/workflows/fund\.yml@[0-9a-f]{40}", (ROOT / ".github/workflows/knos.yml").read_text(encoding="utf-8"))
    assert "knos command --event" in (ROOT / ".github/workflows/fund.yml").read_text(encoding="utf-8")


def test_the_page_and_the_json_are_the_table(capsys):
    assert enforce.main(["--check"]) == 0, "run: python -m knos.enforce --write"
    assert enforce.main(["--json"]) == 0
    doc = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert [r["id"] for r in doc["routes"]] == list(enforce.CELLS) and [x["id"] for x in doc["restrictions"]] == [x for x, _n in enforce.RESTRICTIONS]
    assert set(doc["cells"]["comment"]["approvers"]) == {"class", "by", "test"} and doc["cells"]["comment"]["approvers"]["class"] == "workflow"
    assert all(doc["cells"][r["id"]][x["id"]]["class"] in enforce.CLASSES for r in doc["routes"] for x in doc["restrictions"])
    page = (ROOT / enforce.DOC).read_text(encoding="utf-8")
    assert page.count("\n## ") == 2 + len(enforce.ROUTES) and "| [Funding by comment](#comment) | program | program | program | workflow | advisory |" in page
    assert enforce.main(["--nothing"]) == 2 and enforce.main([]) == 0 and "Funding by comment" in capsys.readouterr().out


def test_the_controls_page_says_what_the_source_does_about_the_gate():
    text = (ROOT / "docs/CONTROLS.md").read_text(encoding="utf-8")
    for false in ("nothing calls it today", "does not ask it yet", "not asked by the funding workflow yet", "a workflow would ask"):
        assert false not in text, false
    assert "ENFORCEMENT.md" in text and "approvals.gate_order" in text and "flow._gated" in text
    source = (ROOT / "src/knos/flow.py").read_text(encoding="utf-8")
    assert source.count("_gated(run, rp, cmd, commenter") == 3 and "approvals.gate(" in source and "approvals.gate_order(" in source


def test_knos_controls_matrix_prints_the_table():
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner
    app, lines = typer.Typer(), []
    enforce.register(app, lines)

    @app.command("other")
    def other() -> None:        # a second command, so the group keeps its name
        pass
    got = CliRunner().invoke(app, ["controls", "matrix", "--json"])
    assert got.exit_code == 0 and json.loads(got.stdout) == enforce.as_json() and lines[0][0] == "controls"
    assert "A top-up" in CliRunner().invoke(app, ["controls", "matrix"]).stdout


# ---- the workflow's gate, tried from every route a comment has --------------------------------------------------------------
def comment(w, n: int, who_: dict, body: str, files: dict[str, str] | None, code: int = 0) -> str:
    from test_flow_orders import plain
    run = w.run(w.hub.commented(n, who_, body))
    if files is not None:
        run._github = Files(w.hub, "o/r", files)
    assert flow.command(run) == code
    return plain(w.hub.knos(n)[-1], 1700)


def test_a_plain_fund_cannot_go_round_the_approval_a_standing_offer_needs(tmp_path):
    from _flow import HUBOT, MONA
    from test_flow_orders import world
    w = world(tmp_path)
    w.hub.can["mona"] = "write"
    # the offer is refused by the buyer's files; so the same budget is asked for as a plain order
    assert "Refused: no standing offer under .knos/procurement/offers/ names @mona at this rate and cap today." in comment(
        w, 7, HUBOT, "/knos offer @mona rate 12 budget 30 checks: test", FILES)
    refused = comment(w, 7, HUBOT, "/knos fund 30 checks: test", FILES)
    assert refused.startswith("Knos: nothing was funded. Refused: `issue:7` is not approved. Waits for 1 approver: 30.00 needs 1 approver.")
    assert "An approver comments `/knos approve issue:7`" in refused and "--subject issue:7 --requester hubot --amount 30" in refused
    # someone who can write and is no requester; the requester's own approval; an approval typed into the log
    assert "Refused: @mona does not hold the requester role on " in comment(w, 7, MONA, "/knos fund 30 checks: test", FILES)
    own = approvals.event(subject="issue:7", amount=30 * U, requester="hubot", approver="hubot", approver_id=1, role="approver", at="2026-01-01T00:00:00Z",
                          authority="", source={"comment_id": 0}, policy_sha256="")
    typed = {**own, "approver": "mei-acme", "source": {"comment_id": 987_654}}
    for log in (own, typed):
        assert "`issue:7` is not approved" in comment(w, 7, HUBOT, "/knos fund 30 checks: test", {**FILES, f"{PROC}/{approvals.LOG}": json.dumps(log) + "\n"})
    assert w.chain.orders(7) == [] and w.signer.asked == []                 # nothing was signed on any of these
    # an approver with authority comments: exactly that amount is funded, and another amount is not
    signed = approved(w.hub, FILES, 7, "issue:7", 30 * U)
    assert "Waits for 1 approver: 31.00 needs 1 approver." in comment(w, 7, HUBOT, "/knos fund 31 checks: test", signed) and w.chain.orders(7) == []
    assert comment(w, 7, HUBOT, "/knos fund 30 checks: test", signed).startswith("Knos: 30.00") and len(w.chain.orders(7)) == 1
    # a repository with no procurement file is asked nothing more
    assert comment(w, 7, MONA, "/knos fund 20 checks: test", None).startswith("Knos: 20.00") and len(w.chain.orders(7)) == 2


def test_a_plain_order_is_held_to_no_rate_card_and_no_envelope(tmp_path):
    from _flow import HUBOT
    from test_flow_orders import world
    s, w = controls.sample(), world(tmp_path)
    spent = {**s["envelope"], "limit": 100, "committed": 60, "spent": 40, "held": 0}            # an envelope with nothing left
    assert controls.fit(spent, 30 * U)["ok"] is False                                          # `knos budget envelope --fund 30` says no
    files = {**FILES, f"{PROC}/envelopes/{spent['name']}.yaml": controls.dump_yaml(spent),
             f"{PROC}/rate-cards/{s['rate_card']['name']}.yaml": controls.dump_yaml(s["rate_card"])}
    signed = approved(w.hub, files, 7, "issue:7", 30 * U)
    # advisory: the workflow reads neither for a plain order, and 30.00 is no price of the rate card
    assert comment(w, 7, HUBOT, "/knos fund 30 checks: test", signed).startswith("Knos: 30.00") and len(w.chain.orders(7)) == 1


def test_an_offer_over_its_envelope_still_funds_once_it_is_approved():
    s, root = controls.sample(), PROC
    offer, card = s["offers"][0], s["rate_card"]
    envelope = {**s["envelope"], "limit": 100, "committed": 60, "spent": 40, "held": 0}
    files = {f"{root}/rate-cards/{card['name']}.yaml": controls.dump_yaml(card), f"{root}/envelopes/{envelope['name']}.yaml": controls.dump_yaml(envelope),
             f"{root}/offers/{offer['name']}.yaml": controls.dump_yaml(offer), f"{root}/policy.yaml": controls.dump_yaml(s["policy"])}
    req = dict(subject=f"offer:{offer['name']}", requester=offer["requested_by"], amount=controls.commitment(offer)["value"])
    log = ""
    for n, who_ in enumerate(("mei-acme", "sam-acme")):
        e, why = approvals.from_comment(s["policy"], {"id": 70 + n, "body": f"/knos approve offer:{offer['name']}", "user": {"login": who_, "id": 9000 + n},
                                                      "created_at": "2026-10-03T10:00:00Z", "updated_at": "2026-10-03T10:00:00Z", "html_url": ""}, **req)
        assert e is not None, why
        log += json.dumps(e) + "\n"
    row = controls.outcome_of(card, offer["outcome"])
    ask = dict(vendor=offer["suppliers"][0], rate=controls.units_of(row["price"]), budget=controls.units_of(offer["cap"]), on="2026-10-06")
    assert controls.fit(envelope, controls.commitment(offer)["leaves"])["ok"] is False          # the command refuses it
    ok, said = approvals.gate({**files, f"{root}/{approvals.LOG}": log}, **ask)
    assert ok and said.startswith(f"Offer `{offer['name']}`, envelope `{envelope['name']}`."), said     # the gate does not: advisory
    assert approvals.gate(files, **ask)[0] is False                                              # the approvals it does ask


def test_a_tip_is_held_to_the_approval_policy_too(tmp_path):
    from _flow import HUBOT, MONA
    from test_flow import bounty
    w = bounty(tmp_path)
    w.chain.bind(MONA)
    w.hub.merge(12)
    asked = len(w.signer.asked)

    def tip(files) -> str:
        run = w.run(w.hub.commented(12, HUBOT, "/knos tip 5"))
        run._github = Files(w.hub, "o/r", files)
        assert flow.command(run) == 0
        return w.hub.knos(12)[-1]
    refused = tip(FILES)
    assert refused.startswith("Knos: no tip was sent. Refused: `tip:12` is not approved. Waits for 1 approver: 5.00 needs 1 approver.")
    assert len(w.signer.asked) == asked                                      # GitHub was asked to sign nothing
    # an approval of the issue's order is not one of the tip
    assert "`tip:12` is not approved" in tip(approved(w.hub, FILES, 12, "issue:12", 5 * U)) and len(w.signer.asked) == asked
    # approved, it is funded whatever an envelope says: no envelope is read
    empty = {**controls.sample()["envelope"], "limit": 1, "committed": 1, "spent": 0, "held": 0}
    signed = approved(w.hub, {**FILES, f"{PROC}/envelopes/{empty['name']}.yaml": controls.dump_yaml(empty)}, 12, "tip:12", 5 * U)
    assert "Knos: a tip of 5.00" in tip(signed) and len(w.signer.asked) == asked + 1


def test_a_private_order_is_held_to_the_approval_policy_of_its_own_repository(tmp_path):
    import test_flow_private as private
    from _flow import HUBOT
    w, pub = private.world(tmp_path)
    w.hub.say(private.ISSUE, HUBOT, private.FUND)
    w.clock.sleep(60)
    amount = next(c for c in [flow.commands.parse(private.FUND, False)]).units

    def attestor(files) -> str:
        run = private.run(w, pub, private.by_hand(issue=private.ISSUE))
        run._reader = lambda repo: Files(w.hub, private.TARGET, files)
        flow.command(run)
        return w.hub.comments[private.ISSUE][-1]["body"]
    refused = attestor(FILES)
    assert f"Knos: nothing was funded. Refused: `issue:{private.ISSUE}` is not approved. Waits for 1 approver" in refused and w.chain.orders() == []
    assert w.signer.asked == []
    # the comment is answered once: a new one, after the approval, is funded at any amount the rate card does not know
    signed = approved(w.hub, FILES, private.ISSUE, f"issue:{private.ISSUE}", amount)
    w.hub.say(private.ISSUE, HUBOT, private.FUND)
    w.clock.sleep(60)
    attestor(signed)
    assert len(w.chain.orders()) == 1 and len(w.signer.asked) == 1


def test_a_neutral_run_refuses_a_payee_the_policy_file_does_not_list(tmp_path):
    from _flow import MONA
    from test_flow_orders import attested, ordered, settled
    w = ordered(tmp_path)
    w.chain.bind(MONA)
    w.hub.contents[".knos/policy.yml"] = "version: 1\npayees: [eve]\n"
    # the repository's own settle job holds the list
    assert "only eve may be paid; mona is not one of them" in settled(w) and w.signer.asked == [] and len(w.chain.orders()) == 1
    # the other route to a payment, a neutral run in the seller's own repository: it reads the buyer's file too and signs nothing
    code, _run, text = attested(w, "pay")
    assert code == 1 and "nothing was signed" in text and "only eve may be paid; mona is not one of them" in text
    assert w.signer.asked == [] and len(w.chain.orders()) == 1
    # without the list the same run pays: the list is what stopped it
    del w.hub.contents[".knos/policy.yml"]
    code, _run, text = attested(w, "pay")
    assert code == 0 and "it pays @mona, and Solana took it" in text and w.chain.orders() == []


def test_a_token_from_a_changed_workflow_is_stopped_only_by_the_balances_own_pin():
    from solders.pubkey import Pubkey
    b = pay.Balance(faucet=False, owner_id=1, authority=Pubkey.default(), mint=Pubkey.default(), cap_per_job=0, last_iat=0, spenders=(2,), spent=0, has_x=True)
    x = pay.BalanceX(day_limit=0, total_limit=0, repos=(), wf_sha="", day=0, day_spent=0, total_spent=0)
    ask = dict(repo_id=5, amount=20 * U, by_id=2, now=0, repo_owner_id=1, wf_sha="b" * 40)
    # no pin: the program takes a fund.yml of any commit, so a run that skipped the files funds within the Balance's limits
    assert controls.decide(b, x, **ask).ok
    pinned = controls.decide(b, dataclasses.replace(x, wf_sha="a" * 40), **ask)
    assert (pinned.ok, pinned.rule, pinned.code) == (False, "workflows", 86)
    # and the limits hold whoever carries the token: the cap, the day
    assert controls.decide(dataclasses.replace(b, cap_per_job=10 * U), x, **ask).code == 93
    assert controls.decide(b, dataclasses.replace(x, day_limit=10 * U), **ask).code == 100
    assert controls.decide(b, x, **{**ask, "by_id": 3}).code == 92


# ---- the program, asked directly -----------------------------------------------------------------------------------------
def test_a_top_up_goes_past_the_balances_cap_and_limits_and_only_its_wallet_signs_it():
    pytest.importorskip("solders.litesvm")
    from _order import MAINT, USDC, OrderChain, code, issue, swap
    c = OrderChain()
    assert c.send([pay.set_balance_ix(c.owner.pubkey(), c.bal, cap=15 * USDC, spenders=[MAINT])], c.owner), c.err
    assert c.send([pay.set_balance_x_ix(c.owner.pubkey(), c.bal, day_limit=12 * USDC)], c.owner), c.err
    n = issue()
    assert not c.send([c.fund_balance_ix(c.fund_token(n, 20 * USDC), n)]) and code(c) == 93      # a comment cannot fund 20: the cap is 15
    n = issue()
    assert not c.send([c.fund_balance_ix(c.fund_token(n, 13 * USDC), n)]) and code(c) == 100     # nor 13: 12 a day
    order = c.fund_balance(amount=10 * USDC)
    before, x = c.order(order), pay.read_balx(c.data(pay.balx_pda(c.bal)))
    ix = pay.top_up_ix(c.owner.pubkey(), order, before, 10 * USDC)
    stranger, _tok = c.wallet(c.usdc, 100 * USDC)
    assert not c.send([swap(ix, 0, stranger.pubkey())], stranger) and code(c) == 98              # nobody but the Balance's wallet
    assert c.send([ix], c.owner), c.err                                                           # which takes the order to 20: past the cap and the day
    after = c.order(order)
    assert after.amount == 20 * USDC > 15 * USDC and pay.read_balx(c.data(pay.balx_pda(c.bal))) == x      # and the limits counted nothing
    assert (bytes(after.terms), after.deadline, after.mode) == (bytes(before.terms), before.deadline, before.mode)


def test_a_wallet_is_held_to_the_programs_bounds_and_to_no_file():
    pytest.importorskip("solders.litesvm")
    from _order import USDC, OrderChain, code, issue, user
    from solders.keypair import Keypair
    c = OrderChain()
    n = issue()
    assert not c.send([c.fund_wallet_ix(n, amount=4 * USDC)], c.funder) and code(c) == 81       # under 5.00
    assert not c.send([c.fund_wallet_ix(n, amount=100_001 * USDC)], c.funder) and code(c) == 81
    stranger, _tok = c.wallet(c.usdc, 0)
    assert not c.send([c.fund_wallet_ix(n, funder=stranger)], stranger)                          # another wallet cannot spend this one's money
    # with its own signature and nothing else (no Balance, no GitHub account, no file) it funds
    order = c.fund_wallet(n, amount=50 * USDC)
    o = c.order(order)
    assert o.amount == 50 * USDC and not o.from_balance
    # the terms are fixed: a token for other terms pays nothing, one for these terms does
    payee, wallet = user(), Keypair().pubkey()
    assert not c.pay(order, [(payee, 10_000, wallet)], terms=bytes(32)) and code(c) == 87
    assert c.pay(order, [(payee, 10_000, wallet)]), c.err
