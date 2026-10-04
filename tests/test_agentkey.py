"""The loop an agent runs by itself (knos_find_work, knos_take_work, knos_submit_work, knos_collect) and the key it
is paid at (knos.agentkey). The chain and GitHub are tests/test_mcp.py's dictionaries; what the agent posts goes to a
Hub that plays the repository's workflow and the relayer, and writes down who did what, so a test can say that no
person acted between finding the work and being paid.
"""

from __future__ import annotations

import io
import json
import os
import stat

import pytest
from solders.pubkey import Pubkey
from typer.testing import CliRunner

from _flow import bind_bytes, order_bytes
from test_mcp import HUBOT_ID, NOW, WIDGETS, GitHub, Ledger, rep2_bytes

from knos import agentkey, mcp, terms
from knos.settle.v2 import order_auto, pay

ADA = {"login": "agent-ada", "id": 77_001, "type": "User"}       # the agent's own GitHub account
ISSUE, AMOUNT = 31, 40_000_000
TERMS = {"accept": "ab" * 32, "checks": [], "deny": [".github/**", ".knos/**"], "mode": "tests", "paths": ["src/**"], "reserve": 3, "v": 1}
RAW = terms.canonical(TERMS)
SOURCE = pay.faucet_balance_pda(HUBOT_ID)
ORDER = pay.order_pda(pay.scope_of(WIDGETS, ISSUE), SOURCE, 0)


def _put(data: bytes, **at) -> bytes:
    d = bytearray(data)
    for offset, value in at.items():
        d[int(offset[1:]):int(offset[1:]) + 8] = int(value).to_bytes(8, "little")
    return bytes(d)


def order(auto: bool = True, **kw) -> bytes:
    """An open work order on octo/widgets#31, paid by its acceptance checks; `auto`: with no merge."""
    flags = pay.F_NEUTRAL | pay.F_FAUCET | (order_auto.F_AUTO if auto else 0)
    return order_bytes(WIDGETS, ISSUE, AMOUNT, SOURCE, pay.terms_hash(RAW), mode=1, flags=flags, deadline=NOW + 7 * 86_400, reserve_days=3,
                       owner_id=HUBOT_ID, funder_id=HUBOT_ID, **kw)


class Hub:
    """What answers the agent's posts: the repository's workflow (it reserves the order for a `/knos take`, and judges
    a pull request's head), and the relayer (it binds the wallet and sends what was held). `events` is everyone's acts,
    in order, as (who, what)."""

    def __init__(self, ledger: Ledger, github: GitHub):
        self.ledger, self.github, self.events, self.sent = ledger, github, [], []

    def post(self, method: str, path: str, body: dict) -> dict:
        self.sent.append({"method": method, "path": path, "body": body})
        if path.endswith("/comments"):
            self.events += [("agent", "comment " + body["body"]), ("workflow", "reserved")]
            self.ledger.second[ORDER] = _put(self.ledger.second[ORDER], o128=ADA["id"], o136=NOW + 3 * 86_400)
            return {"id": 9001}
        assert path == "repos/octo/widgets/pulls"
        self.events += [("agent", "pull request"), ("workflow", "black-box checks passed at the head: held for the author")]
        held = bytearray(_put(self.ledger.second[ORDER], o152=ADA["id"], o112=NOW + 180 * 86_400))
        held[1] = 3
        self.ledger.second[ORDER] = bytes(held)
        return {"number": 44}

    def bind(self, address: str, ledger) -> dict:
        assert ledger is self.ledger
        self.events += [("agent", "bind " + address), ("relayer", "bound and paid")]
        del self.ledger.second[ORDER]
        self.ledger.second[pay.bind_pda(ADA["id"])] = bind_bytes(ADA["id"], address)
        self.ledger.second[pay.rep_pda(ADA["id"])] = rep2_bytes(0, 0, 0, 1, 0, AMOUNT, NOW, NOW)
        return {"posted": {"repository": "agent-ada/knos-claim", "workflow": ".github/workflows/knos-claim.yml"}, "bound": True, "log": []}


def world(auto: bool = True, **kw) -> tuple[Ledger, GitHub, Hub]:
    ledger = Ledger(second={ORDER: order(auto, **kw)}, logs={ORDER: RAW})
    github = GitHub({
        "user": dict(ADA), "repos/octo/widgets": {"id": WIDGETS, "full_name": "octo/widgets", "default_branch": "main"},
        f"repositories/{WIDGETS}": {"id": WIDGETS, "full_name": "octo/widgets"},
        f"repos/octo/widgets/issues/{ISSUE}": {"number": ISSUE, "title": "Slugify keeps punctuation", "state": "open", "assignees": [],
                                               "labels": [{"name": "python"}]},
    })
    return ledger, github, Hub(ledger, github)


PASS = lambda issue, branch, args, bought: {"passed": True, "failed": [], "ran": [f"knos proof judge --issue {issue}"]}  # noqa: E731
FAIL = lambda issue, branch, args, bought: {"passed": False, "failed": ["case 4: expected `a-b`, got `a b`"], "ran": ["knos proof judge"]}  # noqa: E731
SUBMIT = {"issue": f"octo/widgets#{ISSUE}", "path": ".", "branch": "fix-31", "title": "Slugify drops punctuation"}


def call(name: str, arguments: dict, ledger, github, hub: Hub, run=PASS, scopes=None) -> dict:
    params = {"name": name, "arguments": arguments, "_meta": {mcp.VERSION_KEY: mcp.PROTOCOL}}
    stdin, stdout = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}) + "\n"), io.StringIO()
    mcp.serve(stdin, stdout, ledger=ledger, github=github, post=hub.post, run=run, bind=hub.bind, scopes=scopes or (lambda tok: None))
    return json.loads(stdout.getvalue())["result"]


def ok(*a, **kw) -> dict:
    got = call(*a, **kw)
    assert got["isError"] is False, got["content"]
    return got["structuredContent"]


def refused(*a, **kw) -> str:
    got = call(*a, **kw)
    assert got["isError"] is True
    return got["content"][0]["text"]


@pytest.fixture
def acting(monkeypatch):
    """The operator turned the acting tools on, the agent has its key, and its token is a fine-grained one."""
    monkeypatch.setenv("KNOS_AGENT_ACT", "1")
    monkeypatch.setenv("KNOS_AGENT_TOKEN", "github_pat_" + "x" * 30)
    return agentkey.init()["address"]


# ---- the loop ------------------------------------------------------------------------------------------------------------

def test_an_agent_finds_takes_submits_and_is_paid_on_an_auto_order_with_no_person_in_between(acting):
    ledger, github, hub = world()
    key_text = (agentkey.folder() / "key.json").read_text()
    results = []

    found = ok("knos_find_work", {"label": "Python", "mode": "auto", "min_usdc": 10}, ledger, github, hub)
    results.append(found)
    (work,) = found["work"]
    assert (work["repo"], work["issue"], work["mode"], work["auto"], work["kind"]) == ("octo/widgets", ISSUE, "auto", True, "work order")
    assert work["you_receive_usdc"] == "40.00" and work["money"] == "test USDC" and work["reserved"] is None and work["reserve_days"] == 3
    assert work["deadline"] == mcp._iso(NOW + 7 * 86_400) and "with no merge" in work["paid_when"]
    assert work["acceptance"]["command"] == f"knos proof judge --base <a checkout of the default branch> --pr <your tree> --issue {ISSUE}"
    # the funder's words (terms sentence, checks, paths) and the repository's (title, labels) are data, inside `untrusted`
    assert work["untrusted"]["paths"] == ["src/**"] and work["untrusted"]["checks"] == [] and work["untrusted"]["labels"] == ["python"]
    assert any("acceptance checks" in s for s in work["untrusted"]["terms"]) and hub.sent == []

    took = ok("knos_take_work", {"issue": work["repo"] + f"#{ISSUE}"}, ledger, github, hub)
    results.append(took)
    assert took["sent"] is True and took["as"] == "agent-ada" and took["token"] == "fine-grained" and took["reserve_days"] == 3
    assert took["posted"] == {"method": "POST", "path": f"repos/octo/widgets/issues/{ISSUE}/comments", "body": {"body": "/knos take"}} == hub.sent[-1]
    assert pay.read_order(ledger.second[ORDER]).reserved_by == ADA["id"]
    assert ok("knos_find_work", {}, ledger, github, hub)["work"] == []                 # reserved: nobody else is offered it
    again = ok("knos_take_work", {"issue": f"octo/widgets#{ISSUE}"}, ledger, github, hub)
    assert again["sent"] is False and again["posted"] is None and len(hub.sent) == 1       # already the agent's: nothing posted twice

    sub = ok("knos_submit_work", SUBMIT, ledger, github, hub)
    results.append(sub)
    assert sub["submitted"] is True and sub["pr"] == "octo/widgets#44" and sub["auto"] is True and sub["local"]["passed"] is True
    assert sub["posted"] == hub.sent[-1] == {"method": "POST", "path": "repos/octo/widgets/pulls", "body": {
        "title": "Slugify drops punctuation", "head": "agent-ada:fix-31", "base": "main", "body": f"Fixes #{ISSUE}\n", "maintainer_can_modify": True}}
    from knos import closing
    assert closing.closing_issues(sub["posted"]["body"]["body"], "octo/widgets") == [ISSUE]     # the line the workflow matches it by

    paid = ok("knos_collect", {}, ledger, github, hub)
    results.append(paid)
    assert paid["bind"]["sent"] is True and paid["bind"]["posted"]["repository"] == "agent-ada/knos-claim"
    assert paid["wallet"] == acting == paid["agent_address"] and paid["wallet_is_agent_key"] is True and paid["held"] == []
    assert paid["paid"]["test_payments"] == 1 and paid["paid"]["test_total_usdc"] == "40.00"

    # everything that happened, in order: the agent, the repository's workflow and the relayer. No person.
    assert [who for who, _ in hub.events] == ["agent", "workflow", "agent", "workflow", "agent", "relayer"]
    assert [what.split()[0] for who, what in hub.events if who == "agent"] == ["comment", "pull", "bind"]
    # and no result holds the key: not the file's text, not a number of it
    said = json.dumps(results)
    assert key_text not in said and key_text[1:40] not in said and "key.json" not in said


def test_collect_reports_what_is_held_and_binds_nothing_when_actions_are_off(monkeypatch):
    ledger, github, hub = world()
    held = bytearray(_put(ledger.second[ORDER], o152=ADA["id"], o112=NOW + 180 * 86_400))
    held[1] = 3
    ledger.second[ORDER] = bytes(held)
    agentkey.init()
    out = ok("knos_collect", {}, ledger, github, hub)
    assert out["wallet"] is None and [(h["issue"], h["net_units"], h["kind"]) for h in out["held"]] == [(ISSUE, AMOUNT, "work order")]
    assert out["bind"]["sent"] is False and "KNOS_AGENT_ACT=1" in out["bind"]["why"] and hub.events == []
    github.pages["users/agent-ada"] = dict(ADA)
    other = ok("knos_collect", {"login": "agent-ada"}, ledger, github, hub)          # a named login is only read
    assert other["bind"] == {"sent": False, "why": "a login was named: this only read its state"} and other["agent_address"] is None


# ---- the refusals: each sends nothing --------------------------------------------------------------------------------------

def test_nothing_is_posted_unless_the_operator_turned_the_acting_tools_on(monkeypatch):
    ledger, github, hub = world()
    monkeypatch.setenv("KNOS_AGENT_TOKEN", "github_pat_" + "x" * 30)
    for name, args in (("knos_take_work", {"issue": f"octo/widgets#{ISSUE}"}), ("knos_submit_work", SUBMIT)):
        said = refused(name, args, ledger, github, hub)
        assert said.startswith(f"{name} is off, and nothing was sent") and "KNOS_AGENT_ACT=1" in said and "knos agent init --allow-actions" in said
    assert hub.sent == [] and ok("knos_find_work", {}, ledger, github, hub)["work"]       # finding work needs no switch and no key
    agentkey.init(allow_actions=True)                                                     # the other way to turn them on
    assert ok("knos_take_work", {"issue": f"octo/widgets#{ISSUE}"}, ledger, github, hub)["sent"] is True


def test_a_classic_token_with_repo_scope_is_refused_unless_the_operator_allowed_it(monkeypatch, acting):
    ledger, github, hub = world()
    monkeypatch.setenv("KNOS_AGENT_TOKEN", "ghp_" + "y" * 36)
    args = {"issue": f"octo/widgets#{ISSUE}"}
    said = refused("knos_take_work", args, ledger, github, hub, scopes=lambda tok: ["repo", "workflow"])
    assert "classic token with the `repo` scope" in said and "--allow-broad-token" in said and hub.sent == []
    unknown = refused("knos_take_work", args, ledger, github, hub, scopes=lambda tok: None)
    assert "did not say which scopes" in unknown and hub.sent == []                       # not known is not narrow
    assert "ghp_" not in said + unknown                                                    # the token is never said back
    narrow = ok("knos_take_work", args, ledger, github, hub, scopes=lambda tok: ["public_repo"])
    assert narrow["sent"] is True and narrow["token"] == "classic: public_repo"
    ledger, github, hub = world()
    agentkey.init(allow_actions=True, allow_broad=True)
    assert ok("knos_take_work", args, ledger, github, hub, scopes=lambda tok: ["repo"])["token"] == "classic, allowed by the operator"


def test_a_failed_local_acceptance_is_not_submitted_and_says_which_check_failed(acting):
    ledger, github, hub = world()
    out = ok("knos_submit_work", SUBMIT, ledger, github, hub, run=FAIL)
    assert (out["sent"], out["submitted"], out["posted"], out["local"]["passed"]) == (False, False, None, False)
    assert out["untrusted"]["failed"] == ["case 4: expected `a-b`, got `a b`"] and out["said"].startswith("Nothing was submitted: the local acceptance failed")
    assert "case 4" not in out["said"] and hub.sent == []          # what a bundle printed is data, inside `untrusted`


def test_an_order_reserved_by_someone_else_is_neither_taken_nor_submitted_to(acting):
    ledger, github, hub = world()
    ledger.second[ORDER] = _put(ledger.second[ORDER], o128=5150, o136=NOW + 86_400)
    for name, args in (("knos_take_work", {"issue": f"octo/widgets#{ISSUE}"}), ("knos_submit_work", SUBMIT)):
        said = refused(name, args, ledger, github, hub)
        assert f"is reserved for GitHub user id 5150 until {mcp._iso(NOW + 86_400)}" in said and said.startswith(f"{name} sent nothing")
    found = ok("knos_find_work", {}, ledger, github, hub)
    assert found["work"] == [] and found["skipped"] == {"reserved": 1, "assigned": 0}
    # a reservation that lapsed holds nobody out; an issue a maintainer assigned to another account does
    ledger.second[ORDER] = _put(ledger.second[ORDER], o136=NOW - 1)
    assert len(ok("knos_find_work", {}, ledger, github, hub)["work"]) == 1
    github.pages[f"repos/octo/widgets/issues/{ISSUE}"]["assignees"] = [{"login": "mona", "id": 1_234_567}]
    assert "is assigned to another account (GitHub user id 1234567)" in refused("knos_take_work", {"issue": f"octo/widgets#{ISSUE}"}, ledger, github, hub)
    assert ok("knos_find_work", {}, ledger, github, hub)["skipped"] == {"reserved": 0, "assigned": 1} and hub.sent == []


def test_take_is_for_a_user_account_or_an_agents_own_on_an_auto_order_and_an_order_without_reservations_says_to_submit(acting):
    # an agent's own account (GitHub type Bot) takes an order funded `auto`: it is who such an order is for
    ledger, github, hub = world()
    github.pages["user"] = {"login": "ada-app[bot]", "id": 9, "type": "Bot"}
    took = ok("knos_take_work", {"issue": f"octo/widgets#{ISSUE}"}, ledger, github, hub)
    assert took["sent"] is True and took["posted"]["body"] == {"body": "/knos take"} and took["as"] == "ada-app[bot]"
    # an order without `auto` still asks for a person's account, and so does every type that is neither
    ledger, github, hub = world(auto=False)
    github.pages["user"] = {"login": "ada-app[bot]", "id": 9, "type": "Bot"}
    said = refused("knos_take_work", {"issue": f"octo/widgets#{ISSUE}"}, ledger, github, hub)
    assert "for a Bot account only on an order funded `auto`; ada-app[bot] is of type Bot, and the order on octo/widgets#" in said and hub.sent == []
    ledger, github, hub = world()
    github.pages["user"] = {"login": "acme", "id": 9, "type": "Organization"}
    assert "acme is of type Organization" in refused("knos_take_work", {"issue": f"octo/widgets#{ISSUE}"}, ledger, github, hub) and hub.sent == []
    ledger, github, hub = world()
    data = bytearray(ledger.second[ORDER])
    data[7] = 0
    ledger.second[ORDER] = bytes(data)
    assert "takes no reservations" in refused("knos_take_work", {"issue": f"octo/widgets#{ISSUE}"}, ledger, github, hub) and hub.sent == []


def test_find_work_filters_by_repository_label_amount_and_mode():
    ledger, github, hub = world(auto=False)
    find = lambda **a: ok("knos_find_work", a, ledger, github, hub)["work"]  # noqa: E731
    assert [w["mode"] for w in find()] == ["tests"] and find(mode="auto") == [] and len(find(mode="tests", repo="octo/widgets")) == 1
    assert find(label="rust") == [] and find(min_usdc=41) == [] and len(find(min_usdc=40, label="python")) == 1
    assert "mode is merge, tests or auto" in refused("knos_find_work", {"mode": "fast"}, ledger, github, hub)


# ---- the key ---------------------------------------------------------------------------------------------------------------

def test_the_key_is_made_once_readable_only_by_its_owner_and_never_printed():
    from knos.cli import app
    run = CliRunner()
    made = run.invoke(app, ["agent", "init"])
    key = agentkey.folder() / "key.json"
    secret = json.loads(key.read_text())
    assert made.exit_code == 0 and len(secret) == 64
    if os.name != "nt":          # Windows keeps who can read a file in its ACL, not in these bits
        assert stat.S_IMODE(key.stat().st_mode) == 0o600
    address = agentkey.address()
    assert address == str(Pubkey.from_bytes(bytes(secret[32:]))) and address in made.output and "off" in made.output
    again = run.invoke(app, ["agent", "init", "--allow-actions"])
    assert "was not replaced" in again.output and json.loads(key.read_text()) == secret and agentkey.actions() is True
    shown = run.invoke(app, ["agent", "show"])
    assert address in shown.output and "public_repo" in shown.output and "Issues: Read and write" in shown.output
    for said in (made.output, again.output, shown.output):
        assert str(secret)[1:30] not in said and key.read_text() not in said
    turned = run.invoke(app, ["agent", "rotate"])
    new = agentkey.address()
    assert turned.exit_code == 0 and new != address and new in turned.output
    assert json.loads((agentkey.folder() / f"key.{address}.json").read_text()) == secret          # the old key is kept, not destroyed
    assert agentkey.actions() is True                                                              # and the switches carry over
    if os.name != "nt":
        assert stat.S_IMODE(key.stat().st_mode) == 0o600


def test_the_address_is_read_without_opening_the_key_file(monkeypatch):
    address = agentkey.init()["address"]
    (agentkey.folder() / "key.json").unlink()                      # gone: anything that opened it would fail
    assert agentkey.address() == address and agentkey.show()["address"] == address and agentkey.show()["key_mode"] is None


def test_the_local_check_holds_the_changed_files_to_the_orders_paths_and_needs_a_base_to_judge(tmp_path):
    import subprocess
    git = lambda *a: subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@x", *a], check=True, capture_output=True)  # noqa: E731
    git("init", "-q", "-b", "main")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("a = 1\n")
    git("add", "-A")
    git("commit", "-qm", "base")
    git("checkout", "-qb", "fix-31")
    (tmp_path / "README.md").write_text("out of scope\n")
    git("add", "-A")
    git("commit", "-qm", "change")
    merge = {**TERMS, "mode": "merge", "accept": ""}
    out = mcp._local_check(ISSUE, "main", {"path": str(tmp_path)}, [merge])
    assert out["passed"] is False and out["ran"] == ["allowed paths"] and any("README.md" in why for why in out["failed"])
    with pytest.raises(mcp.Failed, match="needs `base`"):
        mcp._local_check(ISSUE, "main", {"path": str(tmp_path)}, [TERMS])
    with pytest.raises(mcp.Failed, match="path is not a folder"):
        mcp._local_check(ISSUE, "main", {"path": str(tmp_path / "nowhere")}, [merge])
