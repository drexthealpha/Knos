"""scripts/second_operator.py: the second operator's drill as one command. Tested against canned answers: nobody but
the founder has run the real one, and docs/OPERATOR.md and docs/DRILLS.md say so."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("second_operator", ROOT / "scripts" / "second_operator.py")
so = importlib.util.module_from_spec(spec)
spec.loader.exec_module(so)
KEY = json.dumps(list(range(1, 33)) + [0] * 32)          # not a real keypair: `address` is given by the test


def world(**over):
    """A runner with a passing drill's answers; `over` replaces the answer for a command's first words."""
    asked = []

    def run(cmd, env):
        asked.append((cmd, env))
        for words, answer in over.items():
            if " ".join(cmd).find(words) >= 0:
                return answer
        return so.simulated("you/Knos")[0](cmd, env)
    return run, asked


def go(run, **kw):
    said = []
    got = so.drill("you/Knos", KEY, run=run, balance=kw.pop("balance", lambda a, r: 2_000_000_000), address=lambda k: "Mine111", say=said.append,
                   wait=lambda _s: None, knos=["knos"], **kw)
    return got, said


def test_the_five_steps_run_in_order_with_the_operators_own_key_and_fork():
    run, asked = world()
    got, said = go(run)
    assert got == {"fee_payer": "Mine111", "fork": "you/Knos", "run": 1}
    assert [line.split()[0] for line in said[:5]] == ["1", "2", "3", "4", "5"] and all(" ok: " in line and "expected" in line for line in said[:5])
    cmds = [c for c, _e in asked]
    assert cmds[:5] == [["knos", "status"], ["knos", "relay"], ["gh", "secret", "list", "-R", "you/Knos"], ["gh", "workflow", "run", "worker.yml", "-R", "you/Knos"],
                        ["gh", "run", "list", "-R", "you/Knos", "--workflow", "worker.yml", "--limit", "5", "--json", "databaseId,status,displayTitle,event"]]
    assert asked[1][1]["KNOS_RELAY_KEY"] == KEY                                   # the relay ran with the operator's key, as the file's contents
    assert "-f" not in cmds[3]                                                    # `after` left empty: that is what starts a chain (worker.yml)
    assert "fee payer must be Mine111" in said[5] and "docs/DRILLS.md" in said[6]
    worker = (ROOT / ".github" / "workflows" / "worker.yml").read_text(encoding="utf-8")
    assert "leave it empty to start the chain" in worker and "KNOS_RELAY_KEY" in worker


@pytest.mark.parametrize("over, kw, why", [
    ({"knos status": (1, "a signing key expires in 3 days")}, {}, "1 status: `knos status` exited 1"),
    ({}, {"balance": lambda a, r: 1_000}, "2 fee payer: Mine111 holds 0.000 SOL, expected at least 0.05"),
    ({"knos relay": (1, "boom")}, {}, "3 relay: one pass of `knos relay` with your key exited 1"),
    ({"gh secret": (0, "OTHER_SECRET\t2026")}, {}, "4 the fork: you/Knos has no secret KNOS_RELAY_KEY"),
    ({"gh workflow run": (1, "HTTP 403")}, {}, "5 the chain: GitHub did not start worker.yml"),
    ({"gh run list": (0, "[]")}, {}, "GitHub lists no run of it after 30 seconds"),
])
def test_it_stops_at_the_first_step_that_does_not_hold_and_says_what_was_expected(over, kw, why):
    run, asked = world(**over)
    with pytest.raises(so.Failed) as e:
        go(run, **kw)
    assert why in str(e.value)
    if why.startswith("1 "):
        assert len(asked) == 1 and "expires in 3 days" in str(e.value)            # nothing after a failed step runs, and the step's own words are shown


def test_the_founders_repository_is_not_a_fork_of_ones_own_and_a_simulation_is_not_a_drill():
    with pytest.raises(so.Failed, match="the founder's"):
        so.drill("DrextheAlpha/knos", KEY, run=world()[0])
    with pytest.raises(so.Failed, match="not a Solana keypair file"):
        so._address("not json")
    done = subprocess.run([sys.executable, str(ROOT / "scripts" / "second_operator.py"), "--fork", "you/Knos", "--simulate"], capture_output=True, text=True,
                          encoding="utf-8", check=False, timeout=60)
    assert done.returncode == 0 and done.stdout.startswith("SIMULATED: canned answers") and "This is not a drill" in done.stdout and "5 the chain  ok" in done.stdout
    assert so.main(["--fork", "you/Knos"]) == 1


def test_the_page_gives_the_command_its_expected_output_and_says_nobody_has_run_it():
    page = (ROOT / "docs" / "OPERATOR.md").read_text(encoding="utf-8")
    assert "python scripts/second_operator.py --fork YOU/Knos --key relay.json" in page and "Not yet run by a second person" in page
    for line in ("1 status     ok", "2 fee payer  ok", "3 relay      ok", "4 the fork   ok", "5 the chain  ok"):
        assert line in page
    assert "gh workflow run worker.yml -R YOU/Knos" in page and "gh secret set KNOS_RELAY_KEY -R YOU/Knos < relay.json" in page
    assert "host_a_judge" in page
