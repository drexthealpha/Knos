"""The workflow-strip hole (src/knos/strip_check.py), from recorded GitHub answers: closed, partly or open, and never
closed for those who can edit the ruleset."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from knos import strip_check as K

ROOT = Path(__file__).resolve().parents[1]
FIX = json.loads((ROOT / "tests" / "data" / "strip" / "rules.json").read_text(encoding="utf-8"))


def _get(case: dict, fail: tuple = ()):
    def get(path: str):
        if any(path.startswith(f) for f in fail):
            raise OSError("GitHub said no")
        if path == "repos/acme/app":
            return {"default_branch": "main"}
        if path.startswith("repos/acme/app/rules/branches/main"):
            return case["rules"]
        if path.startswith("repos/acme/app/rulesets/"):
            return case.get("ruleset") or {"id": 1}
        if path == "repos/acme/app/branches/main":
            return case["branch"]
        raise AssertionError(path)
    return get


@pytest.mark.parametrize("name, state", [("closed", "closed"), ("partly", "partly"), ("classic", "partly"), ("open", "open")])
def test_each_recorded_answer(name, state):
    got = K.check("acme/app", _get(FIX[name]))
    assert got["state"] == state and got["branch"] == "main"


def test_closed_is_never_closed_for_those_who_can_edit_the_ruleset():
    got = K.check("acme/app", _get(FIX["closed"]))
    assert "Not closed for organization owners" in got["says"] and "1 bypass actor" in got["says"]
    assert got["evidence"][0]["pinned"] == "0123456789abcdef0123456789abcdef01234567"


def test_a_bypass_list_not_shown_is_said():
    case = {**FIX["closed"], "ruleset": {"id": 42}}
    assert "its bypass list was not read" in K.check("acme/app", _get(case))["says"]


def test_a_required_check_alone_is_partly():
    got = K.check("acme/app", _get(FIX["partly"]))
    assert got["evidence"] == [{"source": "ruleset 9", "context": "prove / prove"}]
    assert "an admin can remove the requirement" in got["says"]


def test_unreadable_is_not_open():
    assert K.check("acme/app", _get(FIX["open"], fail=("repos/acme/app/rules",)))["state"] == "unknown"


def test_the_command_exit_codes(monkeypatch):
    import typer
    from typer.testing import CliRunner

    from knos import judge
    app = typer.Typer()
    K.register(app, [])

    @app.command("other")
    def _other() -> None:
        pass
    for name, code in (("closed", 0), ("partly", 0), ("open", 1)):
        monkeypatch.setattr(judge, "github", _get(FIX[name]))
        got = CliRunner().invoke(app, ["protect", "--check-strip", "acme/app"])
        assert got.exit_code == code and got.output.startswith(f"acme/app main: {name.upper()}")
