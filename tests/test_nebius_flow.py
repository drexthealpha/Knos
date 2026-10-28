"""The Knos x Nebius flow, end to end: a coding agent on Token Factory writes code AND tests, runs them for real and
fixes what fails; the Knos referee judges that code on sealed tests (and refuses a cheater whose own tests pass); the
payout is labelled LiteSVM; every step is metered; live mode sends real requests to Token Factory and Tavily."""
from __future__ import annotations
import pathlib as _pl

import pytest as _pt

if not (_pl.Path(__file__).resolve().parents[1] / "examples/nebius").is_dir():
    _pt.skip("examples/nebius/ left the public repository; this test runs where that folder is kept", allow_module_level=True)

import json
import os
from pathlib import Path


from knos.nebius import agent, flow, mock, onchain, payout, sources, tavily
from knos.nebius.tokenfactory import TokenFactory

ROOT = Path(__file__).resolve().parents[1]
TASK = ROOT / "examples" / "nebius" / "task"


def _workspace(tmp_path: Path) -> Path:
    import shutil
    ws = tmp_path / "ws"
    shutil.copytree(TASK / "base", ws)
    return ws


def test_reply_parsing_and_the_scope_the_task_opens():
    text = ("x\n```file path=duration.py\ndef f():\n    return 1\n```\n```python\n# file: tests/test_d.py\nassert 1\n```\n"
            "```file path=../evil.py\nx\n```")
    got = agent.parse_files(text)
    assert set(got) == {"duration.py", "tests/test_d.py", "../evil.py"} and got["duration.py"].endswith("return 1\n")
    assert agent.in_scope("duration.py") and agent.in_scope("tests/test_d.py")
    for bad in ("../evil.py", "/etc/passwd", "tests/conftest.py", "setup.py", ".knos/acceptance/1/test_issue.py"):
        assert not agent.in_scope(bad), bad


def test_the_agent_s_tests_run_with_no_key_in_their_environment(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "k1")
    monkeypatch.setenv("TAVILY_API_KEY", "k2")
    monkeypatch.setenv("GH_TOKEN", "k3")
    monkeypatch.setenv("SOME_SECRET", "k4")
    env = agent.clean_env()
    assert not {"NEBIUS_API_KEY", "TAVILY_API_KEY", "GH_TOKEN", "SOME_SECRET", "PYTHONPATH"} & set(env)


def test_the_agent_writes_runs_and_tests_until_its_own_tests_pass(tmp_path):
    ws = _workspace(tmp_path)
    tf = TokenFactory(api_key="", responder=mock.responder())
    run = agent.run(tf, (TASK / "TASK.md").read_text(encoding="utf-8"), ws, scope=flow.SCOPE, say=lambda *_: None)
    assert run.mode == "mock" and run.rounds == 2 and run.finished
    assert [t.passed for t in run.tests] == [False, True]          # real pytest runs: the first version fails its own test
    assert run.tests[0].exit_code == 1 and "5m1h" in run.tests[0].tail
    assert set(run.files) == {"duration.py", "tests/test_duration.py"} and "_DURATION" in (ws / "duration.py").read_text()
    assert run.to_dict()["label"] == sources.MOCK and all(c["mock"] for c in run.calls)


def test_the_agent_never_writes_outside_the_task(tmp_path):
    ws = _workspace(tmp_path)

    def reply(model, messages):
        return ("```file path=tests/conftest.py\nimport pytest\n```\n```file path=../outside.py\nx = 1\n```\n"
                "```file path=duration.py\ndef parse_duration(t):\n    return 0\n```")
    run = agent.run(TokenFactory(api_key="", responder=reply), "task", ws, scope=flow.SCOPE, rounds=1, say=lambda *_: None)
    assert sorted(run.refused_paths) == ["../outside.py", "tests/conftest.py"]
    assert not (ws / "tests" / "conftest.py").exists() and not (tmp_path / "outside.py").exists() and not run.finished


def test_live_mode_calls_token_factory_and_tavily_for_real():
    sent = []

    def tf_transport(method, url, headers, body, timeout):
        sent.append((url, headers["Authorization"], body["model"]))
        return {"choices": [{"message": {"content": "```file path=duration.py\ndef parse_duration(t):\n    return 0\n```"},
                             "finish_reason": "stop"}], "usage": {"prompt_tokens": 100, "completion_tokens": 20}}

    def tv_transport(method, url, headers, body, timeout):
        sent.append((url, headers["Authorization"], body["query"], body["include_usage"]))
        return {"results": [{"url": "https://example.org/x", "title": "t", "content": "nothing"}], "usage": {"credits": 1}}
    tf = TokenFactory(api_key="test-key", transport=tf_transport)
    tv = tavily.Tavily(api_key="test-key", transport=tv_transport)
    assert (tf.mode, tv.mode) == ("live", "live")
    r = tf.chat(sources.SUPER, [{"role": "user", "content": "x"}])
    assert not r.mock and sent[0] == (sources.BASE_URL + sources.CHAT_PATH, "Bearer test-key", sources.SUPER)
    prov = tavily.provenance(tv, '_DURATION = re.compile(r"^(?:(\\d+)d)?\\s*(?:(\\d+)h)?\\s*(?:(\\d+)m)?\\s*(?:(\\d+)s)?$")\n')
    assert prov["mock"] is False and prov["checked_lines"] == 1
    assert sent[1][0] == sources.TAVILY_SEARCH_URL and sent[1][1] == "Bearer test-key" and sent[1][3] is True
    assert tv.calls[0].credits == 1 and not tv.calls[0].mock


def test_finality_is_timed_to_finalized_and_alpenglow_is_detected(monkeypatch):
    seen = iter([None, {"confirmationStatus": "processed"}, {"confirmationStatus": "confirmed"}, {"confirmationStatus": "finalized", "err": None}])
    monkeypatch.setattr(onchain.chain, "call", lambda url, method, params, timeout=10.0: {"value": [next(seen)]})
    monkeypatch.setattr(onchain.time, "sleep", lambda s: None)
    import time as _t
    got = onchain.final_ms("u", "sig", _t.perf_counter())
    assert got["finalized_ms"] is not None and got["confirmed_ms"] is not None and got["confirmed_ms"] <= got["finalized_ms"]
    monkeypatch.setattr(onchain.chain, "call", lambda url, method, params, timeout=10.0: {"slot": 1, "cert": "x"})
    assert onchain.alpenglow("u")["consensus"] == "alpenglow"
    monkeypatch.setattr(onchain.chain, "call", lambda url, method, params, timeout=10.0: None)
    assert onchain.alpenglow("u")["consensus"] == "towerbft"

    def missing(url, method, params, timeout=10.0):
        raise ValueError("-32601 Method not found")
    monkeypatch.setattr(onchain.chain, "call", missing)
    assert onchain.alpenglow("u")["consensus"] == "towerbft" and "32601" in onchain.alpenglow("u")["why"]


def test_one_flow_end_to_end_without_a_chain(tmp_path):
    out = tmp_path / "run"
    d = flow.run_flow(ROOT, out, tf=TokenFactory(api_key="", responder=mock.responder()),
                      tv=tavily.Tavily(api_key="", responder=mock.tavily_responder), say=lambda *_: None)
    steps = {s["step"]: s for s in d["steps"]}
    assert list(steps) == ["post", "code", "check_fee", "provenance", "referee", "referee_cheater", "paid", "metered"]
    assert len(steps["post"]["seal_hash"]) == 64 and steps["post"]["escrow"]["funded"] is False
    assert steps["code"]["own_tests_pass"] and steps["referee"]["passed"] and steps["referee"]["reruns_agree"]
    assert steps["referee"]["changed"] == ["duration.py", "tests/test_duration.py"]
    ch = steps["referee_cheater"]
    assert ch["synthetic"] and ch["own_tests_passed"] and not ch["passed"] and "test_edited" in ch["cheats"]
    assert ch["explanation"]["verdict"] == "refused" and ch["explanation"]["advisory"]
    if payout.available(ROOT) is None:
        assert steps["paid"]["paid"] and steps["paid"]["label"] == payout.LABEL and steps["paid"]["to_payee_units"] > 0
    t = d["dashboard"]["totals"]
    assert (t["verifications"], t["verified"], t["refused"], t["failing_merges_blocked"]) == (2, 1, 1, 1)
    assert d["dashboard"]["invoice"]["due_usd"] == "0.00"          # the team's first verification is free
    assert d["modes"]["token_factory"] == "mock" and "track" not in d
    assert (out / "flow.html").is_file() and "LiteSVM" in (out / "flow.html").read_text(encoding="utf-8")
    assert len((out / "usage.jsonl").read_text().splitlines()) == (3 if steps["paid"]["paid"] else 2)
    # the hidden tests were never in the agent's tree
    assert not (out / "pr" / ".knos" / "acceptance").exists() and json.loads((out / "seal.json").read_text())["spec_hash"]


def test_the_committed_run_is_labelled_and_names_its_devnet_transactions():
    run = ROOT / "examples" / "nebius" / "flow-run"
    d = json.loads((run / "flow.json").read_text(encoding="utf-8"))
    steps = {s["step"]: s for s in d["steps"]}
    assert d["modes"]["payout"] == "LiteSVM (testkeys build), not devnet" and d["modes"]["chain"] == "devnet"
    assert steps["post"]["escrow"]["network"] == "devnet" and len(steps["post"]["escrow"]["sig"]) > 80
    assert steps["post"]["cluster"]["consensus"] in ("alpenglow", "towerbft")
    assert steps["check_fee"]["paid"] and steps["check_fee"]["facilitator"].startswith("https://x402.org")
    assert steps["paid"]["label"].startswith("LiteSVM")
    if d["modes"]["token_factory"] == "mock":
        assert sources.MOCK in " ".join(d["labels"])
    raw = (run / "usage.jsonl").read_text(encoding="utf-8")
    assert "internal dogfooding" in raw and "BEGIN" not in raw
    for name in (sources.KEY_ENV, sources.TAVILY_KEY_ENV):
        key = os.environ.get(name)
        assert not key or key not in raw + (run / "flow.json").read_text(encoding="utf-8")
