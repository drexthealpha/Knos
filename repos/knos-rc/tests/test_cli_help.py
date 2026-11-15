"""`knos` and `knos --help`: the four commands a person starts with, then the repository's workflows, then money.
And `knos check`, which is one command for two callers: a person naming a pull request, and a workflow's job."""
from __future__ import annotations

import pytest

from knos import cli, mcp


def _help(capsys, *args: str) -> tuple[int, str]:
    capsys.readouterr()
    rc = cli.main(list(args))
    return rc, capsys.readouterr().out


def test_no_argument_and_help_print_the_same_four_user_commands_first_then_the_two_groups(capsys):
    rc, bare = _help(capsys)
    assert rc == 0
    assert _help(capsys, "--help") == (0, bare)
    at = lambda text: bare.index(text)  # noqa: E731
    first, workflows, money = at("Commands"), at("For a repository's workflows"), at("For money")
    assert first < workflows < money
    user = bare[first:workflows]
    for name in ("check", "init", "claim", "status"):
        assert f"│ {name} " in user, name
    assert [user.index(f"│ {n} ") for n in ("check", "init", "claim", "status")] == sorted(user.index(f"│ {n} ") for n in ("check", "init", "claim", "status"))
    assert not any(f"│ {n} " in user for n in ("command", "settle", "review", "relay", "keys", "bounty", "balance", "mainnet-check"))
    # what a workflow runs is under its own heading, what moves money under its own
    for name in ("command", "settle", "review", "attest", "canary", "relay", "mcp", "proof"):
        assert f"│ {name} " in bare[workflows:money], name
    assert [bare.index(f"│ {n} ") for n in ("settle", "review", "attest", "canary", "relay")] == sorted(bare.index(f"│ {n} ") for n in ("settle", "review", "attest", "canary", "relay"))
    for name in ("bounty", "due", "fund-wallet", "balance", "keys", "mainnet-check"):
        assert f"│ {name} " in bare[money:], name
    assert "│ hook " not in bare            # the hook's entry point is nobody's command


def test_an_organisations_claim_and_the_meters_statement_are_in_the_help(capsys):
    """Two things a command does that its name does not say: `knos claim --org` and `knos statement --meter`."""
    rc, bare = _help(capsys, "--help")
    said = " ".join(bare.replace("│", " ").split())
    assert rc == 0 and "`claim --org`: an organisation's." in said and "`statement --meter`: evaluations billed." in said
    assert bare.index("--org") < bare.index("For a repository's workflows") < bare.index("For money") < bare.index("--meter")
    rc, text = _help(capsys, "claim", "--help")
    assert rc == 0 and "--org" in text and "organisation" in text
    rc, text = _help(capsys, "statement", "--help")
    assert rc == 0 and all(flag in text for flag in ("--meter", "--buyer", "--seller", "--month"))
    assert "knos claim --org <organisation> <address>" in cli.__doc__ and "knos statement --meter --buyer X --seller Y --month YYYY-MM" in cli.__doc__


def test_every_command_in_the_help_has_a_line_and_only_accept_is_still_to_come():
    from typer.main import get_command
    group = get_command(cli.app)
    shown = {name for name, _panel, _short in cli._HELP}
    present = {name for name, c in group.commands.items() if not c.hidden}
    assert present <= shown, sorted(present - shown)        # a new command without a place in the help fails here
    assert shown <= present


def test_status_documents_its_json(capsys):
    rc, said = _help(capsys, "status", "--help")
    assert rc == 0 and "--json" in said and "checks" in said and "pass" in said and "next" in said


def test_check_names_a_pull_request_or_takes_a_workflows_event(capsys, monkeypatch, tmp_path):
    said = lambda *a: _help(capsys, *a)  # noqa: E731
    got = {"verdict": "false", "said": "The description says tests pass, but these checks failed at the head commit: test."}
    monkeypatch.setattr(mcp.Server, "_check_pr", lambda self, args: got if args == {"pr": "octo/widgets#7"} else (_ for _ in ()).throw(mcp.Failed("no such pull request")))
    assert said("check", "octo/widgets#7") == (1, got["said"] + "\n")       # exit 1 only for a false claim
    got = {"verdict": "true", "said": "The description says tests pass, and no finished check failed at the head commit."}
    assert said("check", "octo/widgets#7") == (0, got["said"] + "\n")
    assert said("check", "octo/widgets#8") == (1, "no such pull request\n")
    # neither a pull request nor a workflow's two options: told what to give
    rc, text = said("check")
    assert rc == 1 and text.splitlines()[0] == "Name a pull request: knos check owner/repo#7"
    rc, text = said("check", "octo/widgets#7", "--repo", "octo/widgets")
    assert rc == 1 and "not both" in text
    # the workflow's own call is unchanged: --event and --repo reach knos.flow
    from knos import flow
    event = tmp_path / "event.json"
    event.write_text("{}", encoding="utf-8")
    seen = []
    monkeypatch.setattr(flow, "check", lambda run: seen.append(run.repo) or 0)
    assert said("check", "--event", str(event), "--repo", "octo/widgets")[0] == 0 and seen == ["octo/widgets"]


@pytest.mark.parametrize("args", [["status", "--json", "--bogus"], ["nope"]])
def test_a_wrong_command_line_is_one_line_and_exit_2(capsys, args):
    rc, text = _help(capsys, *args)
    assert rc == 2 and text.splitlines()[-1] == "See:  knos --help"


def test_attest_and_canary_are_listed_and_their_own_options_are_read_without_typer(capsys, monkeypatch):
    """Both are a signing job's commands: knos.flow reads them with argparse, before typer or rich is imported."""
    from knos import flow
    for word, option in (("attest", "--repository"), ("canary", "--amount")):
        assert flow.takes([word, "--help"])
        rc, said = _help(capsys, word, "--help")
        assert rc == 0 and option in said and "usage: knos " + word in said
    seen = []
    monkeypatch.setattr(flow, "attest", lambda run, order, kind, pull, payees, plan="", judge="": seen.append((run.repo, order, kind, pull, payees)) or 0)   # --plan and --judge: empty unless given
    assert _help(capsys, "attest", "--repository", "octo/widgets", "--order", "O", "--kind", "pay", "--pull", "7")[0] == 0
    assert seen == [("octo/widgets", "O", "pay", 7, "")]
    # reached through the full command line all the same (a caller that built it first): handed on as it came
    from typer.main import get_command
    group = get_command(cli.app)
    assert {"attest", "canary"} <= set(group.commands)
    with pytest.raises(SystemExit) as stop:
        group.commands["attest"].main(["--repository", "octo/widgets", "--order", "P", "--kind", "take"], standalone_mode=True, prog_name="knos attest")
    assert stop.value.code == 0 and seen[-1] == ("octo/widgets", "P", "take", None, "")


def test_init_takes_a_host_and_says_which_hosts_there_are(capsys):
    """`knos init --host <name>` writes one coding agent's project files; a name nobody knows lists the ten, exit 1."""
    rc, said = _help(capsys, "init", "--help")
    assert rc == 0 and "--host" in said and "--global" in said
    rc, said = _help(capsys, "init", "--host", "no-such-host")
    assert rc == 1 and "cursor" in said and "roo" in said


def test_budget_observe_and_reproduce_are_commands_for_money(capsys):
    rc, said = _help(capsys, "--help")
    money = said[said.index("For money"):]
    assert rc == 0 and all(f" {word} " in money for word in ("budget", "observe", "reproduce"))
    for word, option in (("budget", "show"), ("observe", "--graph"), ("reproduce", "--only")):
        rc, text = _help(capsys, word, "--help")
        assert rc == 0 and option in text, word
