"""The Hermes plugin (knos.hermes_plugin): register(ctx) adds knos_verify, knos_receipt, knos_bounty_claim and
knos_outcome_check through ctx.register_tool exactly as Hermes's PluginContext takes them (hermes_cli/plugins.py
@8f817911: name, toolset, schema, handler, ...; a handler is handler(args, **kwargs) -> JSON text, never raising),
and the pip entry point and the directory plugin both reach it."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from knos import hermes_plugin as P

ROOT = Path(__file__).resolve().parents[1]
FOUR = ["knos_verify", "knos_receipt", "knos_bounty_claim", "knos_outcome_check"]


class Ctx:
    """The part of Hermes's PluginContext a tool plugin calls."""

    def __init__(self):
        self.tools: dict = {}

    def register_tool(self, name, toolset, schema, handler, check_fn=None, requires_env=None, is_async=False,
                      description="", emoji="", override=False):
        assert name not in self.tools and not override
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, "description": description}


def test_register_adds_the_four_tools_with_openai_style_schemas():
    ctx = Ctx()
    P.register(ctx)
    assert list(ctx.tools)[:4] == FOUR
    for name in FOUR:
        t = ctx.tools[name]
        assert t["toolset"] == "knos" and t["schema"]["name"] == name and t["schema"]["parameters"]["type"] == "object"
        assert set(t["schema"]["parameters"]["required"]) <= set(t["schema"]["parameters"]["properties"]) and t["description"]


def test_handlers_return_json_text_and_never_raise(tmp_path):
    ctx = Ctx()
    P.register(ctx)
    for name in FOUR:
        out = ctx.tools[name]["handler"]({}, task_id="t1", session_id="s1")
        assert isinstance(out, str) and "error" in json.loads(out)
    out = json.loads(ctx.tools["knos_receipt"]["handler"]({"file": str(tmp_path / "missing.json")}))
    assert out["valid"] is False


def test_outcome_check_names_each_drift_and_passes_an_unchanged_outcome(tmp_path):
    funded = {"spec_hash": "a" * 64, "window": {"start": 1, "end": 2}, "salt": "s", "control_share": 0.5,
              "measurement_commit": "c" * 40, "data_hashes": {"data/x.csv": "d" * 64}}
    now = {**funded, "salt": "other", "control_share": 0.6, "data_hashes": {"data/x.csv": "e" * 64}}
    (tmp_path / "f.json").write_text(json.dumps(funded), encoding="utf-8")
    (tmp_path / "n.json").write_text(json.dumps(now), encoding="utf-8")
    (tmp_path / "same.json").write_text(json.dumps(funded), encoding="utf-8")
    got = P.outcome_check({"funded": str(tmp_path / "f.json"), "now": str(tmp_path / "n.json")})
    assert got["drifted"] is True
    if got["engine"] == "local":
        assert {f["rule"] for f in got["findings"]} == {"salt_changed", "control_drift", "data_tampering"}
    assert P.outcome_check({"funded": str(tmp_path / "f.json"), "now": str(tmp_path / "same.json")})["drifted"] is False


def test_bounty_claim_asks_the_mcp_server_and_sends_nothing():
    seen = []

    class Server:
        def _call(self, params):
            seen.append(params)
            return {"structuredContent": {"tool": params["name"]}, "content": [{"type": "text", "text": "{}"}]}
    got = P.bounty_claim({"issue": "octo/widgets#7"}, server=Server())
    assert [p["name"] for p in seen] == ["knos_bounty", "knos_take"] and got["sends"] == "nothing"
    assert any("Fixes #7" in s for s in got["steps"]) and any("knos_verify" in s for s in got["steps"])


def test_the_entry_point_reaches_register():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = text.split('[project.entry-points."hermes_agent.plugins"]', 1)[1]
    assert re.search(r'^knos = "knos\.hermes_plugin:register"$', block, re.M)


@pytest.mark.parametrize("name", FOUR)
def test_no_tool_description_claims_more_than_it_does(name):
    d = P.SCHEMAS[name]["description"].lower()
    assert "mainnet" not in d and "audit" not in d
    if name in ("knos_bounty_claim", "knos_outcome_check", "knos_receipt"):
        assert "sends nothing" in d or "reads only" in d or "check a knos" in d


def test_knos_verify_through_the_plugin_makes_a_receipt_that_names_hermes(tmp_path):
    import subprocess
    r = tmp_path / "repo"
    r.mkdir()
    (r / "a.py").write_text("A = 1\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"],
                 ["add", "-A"], ["commit", "-qm", "base"], ["checkout", "-qb", "w"]):
        subprocess.run(["git", *args], cwd=str(r), check=True, capture_output=True)
    (r / "a.py").write_text("A = 2\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "w"], cwd=str(r), check=True, capture_output=True)
    ctx = Ctx()
    P.register(ctx)
    got = json.loads(ctx.tools["knos_verify"]["handler"]({"path": str(r), "base": "main", "tests": "git --version", "runs": 1}, task_id="t"))
    assert got["verdict"] == "pass" and "Hermes Agent" in got["pr_markdown"] and got["receipt"]["ai_disclosure"].count("Hermes Agent") == 1
    assert json.loads(ctx.tools["knos_receipt"]["handler"]({"file": got["receipt_file"]}))["valid"] is True
