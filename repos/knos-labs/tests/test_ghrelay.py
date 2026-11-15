"""0.3.8 item C: the zero-secret GitHub relay (ghrelay), the caller workflow, the hook's PR receipt line."""

import base64
import hashlib
import json
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from knos.proof import ghrelay, hook

ROOT = Path(__file__).resolve().parents[1]
JOB = "ab" * 32
PAYOUT = "EwSxyJFNQkNN9qtss4Qd7DTvrNYb62vgvhdwqgfErXDz"


def jwt(aud: str, exp: float | None = None) -> str:
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'RS256', 'kid': 'k1'})}.{enc({'aud': aud, 'exp': exp or time.time() + 300})}.c2ln"


class Market:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def fund_with_token(self, ledger, payer, token):
        self.calls.append(("fund", token))
        if self.fail:
            raise LookupError(self.fail)
        return bytes.fromhex(JOB), "fsig"

    def prove_github(self, ledger, payer, job_id, token):
        self.calls.append(("prove", job_id.hex(), token))
        return "s1", "s2"


def test_parse_aud():
    assert ghrelay.parse_aud("knos:fund:7:5000000:" + "c" * 64 + ":1") == {
        "kind": "fund", "issue": 7, "units": 5_000_000, "checks": "c" * 64, "stake": True}
    p = ghrelay.parse_aud(f"knos:{JOB}:{'d' * 40}:{'c' * 64}:{PAYOUT}")
    assert p["kind"] == "proof" and p["job"] == JOB and p["payout"] == PAYOUT
    with pytest.raises(ValueError):
        ghrelay.parse_aud("knos:nothex")


def test_checks_hash_matches_fund_yml(tmp_path):
    d = tmp_path / ".knos" / "acceptance" / "1"
    (d / "sub").mkdir(parents=True)
    (d / "test_accept.py").write_bytes(b"def test_x():\n    assert 1\n")
    (d / "sub" / "data.txt").write_bytes(b"x")
    want = hashlib.sha256()
    for rel, data in sorted([("sub/data.txt", b"x"), ("test_accept.py", b"def test_x():\n    assert 1\n")]):
        want.update(f"{rel}\0{hashlib.sha256(data).hexdigest()}\n".encode())
    assert ghrelay.checks_hash(d) == want.hexdigest()
    src = (ROOT / ".github" / "workflows" / "fund.yml").read_text(encoding="utf-8")
    assert 'h.update(f"{f.relative_to(root).as_posix()}\\0{hashlib.sha256(f.read_bytes()).hexdigest()}\\n".encode())' \
        in src


def test_relay_fund_and_proof():
    m = Market()
    t = jwt("knos:fund:1:5000000:" + "c" * 64 + ":0")
    r = ghrelay.relay_one(None, None, "fund", t, market=m)
    assert r == {"ok": True, "job": JOB, "sigs": ["fsig"]}
    line = ghrelay.log_line("fund", "o/r", 1, t, r)
    assert line == f"knos-relay fund o/r#1 {ghrelay.token_id(t)} ok job={JOB} sig=fsig"
    assert t not in line
    p = jwt(f"knos:{JOB}:{'d' * 40}:{'c' * 64}:{PAYOUT}")
    r = ghrelay.relay_one(None, None, "proof", p, market=m, receipt=lambda *a: "https://x/receipt.html?a=A")
    assert r["sigs"] == ["s1", "s2"] and m.calls[-1] == ("prove", JOB, p)
    assert ghrelay.log_line("proof", "o/r", 2, p, r).endswith("receipt=https://x/receipt.html?a=A")


def test_relay_refusals():
    assert not ghrelay.relay_one(None, None, "proof", jwt("knos:fund:1:5:" + "c" * 64 + ":0"), market=Market())["ok"]
    assert ghrelay.relay_one(None, None, "fund", jwt("knos:fund:1:5:" + "c" * 64 + ":0", exp=1),
                             market=Market())["why"] == "token expired"
    r = ghrelay.relay_one(None, None, "fund", jwt("knos:fund:1:5:" + "c" * 64 + ":0"), market=Market("spent"))
    assert not r["ok"] and "spent" in ghrelay.log_line("fund", "o/r", 1, "a.b.c", r)


def test_found_and_discover():
    t = jwt("knos:fund:3:1:" + "c" * 64 + ":0")
    comments = [{"body": f"knos-fund: {t}\n\n<sub>x</sub>", "issue_url": "https://api.github.com/repos/o/r/issues/3",
                 "user": {"login": "github-actions[bot]"}}, {"body": "hello", "issue_url": "u/4", "user": {"login": "a"}}]
    assert ghrelay.found("o/r", "2026-10-02T00:00:00Z", getter=lambda p: comments) == \
        [("fund", 3, t, "github-actions[bot]")]

    def getter(path):
        if path.startswith("search/"):
            return {"items": [{"repository_url": "https://api.github.com/repos/a/b"}]}
        return [{"full_name": "drexthealpha/knos-e2e-1", "pushed_at": "2026-10-02T01:00:00Z"},
                {"full_name": "drexthealpha/Knos", "pushed_at": "2026-10-02T01:00:00Z"},
                {"full_name": "drexthealpha/old", "pushed_at": "2025-01-01T00:00:00Z"}]
    assert ghrelay.discover("2026-10-02T00:00:00Z", {}, getter=getter) == {"a/b", "drexthealpha/knos-e2e-1"}


def test_caller_workflow_has_no_secret_and_front_matches():
    wf = (ROOT / "examples" / "knos-workflow.yml").read_text(encoding="utf-8")
    assert "secrets." not in wf and "secrets:" not in wf
    # fund.yml and prove.yml at the one sha the escrow registered (job_workflow_sha); relay.yml mints nothing
    reg = set(re.findall(r"drexthealpha/Knos/\.github/workflows/(?:fund|prove)\.yml@([0-9a-f]+)", wf))
    rel = set(re.findall(r"drexthealpha/Knos/\.github/workflows/relay\.yml@([0-9a-f]+)", wf))
    assert len(reg) == 1 and len(rel) == 1 and all(len(s) == 40 for s in reg | rel)
    assert "kind: refused" in wf
    assert "pull_request_target" in wf and "issue_comment" in wf
    js = (ROOT / "web" / "front.js").read_text(encoding="utf-8")
    assert f'KNOS_SHA = "{next(iter(reg))}"' in js and f'KNOS_RELAY_SHA = "{next(iter(rel))}"' in js
    wf_js = re.search(r"export const WORKFLOW = `(.*?)`;\n", js, re.DOTALL).group(1)
    wf_js = wf_js.replace("${KNOS_SHA}", next(iter(reg))).replace("${KNOS_RELAY_SHA}", next(iter(rel)))
    assert wf_js.replace("\\${{", "${{").replace("\\\\", "\\") == wf
    assert "settings/rules/new?target=branch&enforcement=active" in js
    fund = (ROOT / ".github" / "workflows" / "fund.yml").read_text(encoding="utf-8")
    assert '"OWNER","MEMBER","COLLABORATOR"' in fund and "id-token: write" in fund and "name: knos-fund" in fund


def test_hook_adds_receipt_line_to_open_pr(tmp_path, monkeypatch):
    from knos.proof import checks
    monkeypatch.setattr(checks, "head", lambda repo: "f" * 40)
    res = checks.Result("tests", True, "3 passed")
    v = SimpleNamespace(results=[res])
    calls = []

    def gh(repo, *args, inp=None):
        calls.append((args, inp))
        if args[:2] == ("pr", "view"):
            return json.dumps({"number": 5, "body": "Fixes #1", "state": "OPEN"})
        return "ok"
    line = hook.pr_receipt(tmp_path, v, "all tests pass", gh=gh, publish=lambda: "ATT")
    assert line.startswith("knos-receipt: https://drexthealpha.github.io/Knos/receipt.html?a=ATT")
    args, inp = calls[-1]
    assert args[:3] == ("pr", "edit", "5") and inp.startswith("Fixes #1\n\nknos-receipt:")

    def gh2(repo, *args, inp=None):
        if args[:2] == ("pr", "view"):
            return json.dumps({"number": 5, "body": inp_body, "state": "OPEN"})
        raise AssertionError("edited twice")
    inp_body = inp
    assert hook.pr_receipt(tmp_path, v, "all tests pass", gh=gh2, publish=lambda: "ATT") is None
    assert hook.pr_receipt(tmp_path, v, "x", gh=lambda *a, **k: None) is None


def test_hook_links_the_paid_receipt(tmp_path, monkeypatch):
    from knos.proof import checks
    monkeypatch.setattr(checks, "head", lambda repo: "f" * 40)
    v = SimpleNamespace(results=[checks.Result("tests", True, "3 passed")])
    url = "https://drexthealpha.github.io/Knos/receipt.html?a=Paid111"
    edits = []

    def gh(repo, *args, inp=None):
        if args[:2] == ("pr", "view"):
            return json.dumps({"number": 2, "body": "Fixes #1", "state": "OPEN", "comments": [
                {"author": {"login": "github-actions"}, "body": f"Knos: paid. Job x.\nReceipt: {url}"}]})
        edits.append(inp)
        return "ok"
    line = hook.pr_receipt(tmp_path, v, "all tests pass", gh=gh, publish=lambda: "NEVER")
    assert url in line and url in edits[0]


def test_judge_learns_a_contributing_violation_and_requires_it_next(tmp_path):
    from knos.jobs import prove
    from knos.proof import history
    base = tmp_path / "base"
    (base / ".knos" / "acceptance" / "1").mkdir(parents=True)
    (base / ".knos" / "acceptance" / "1" / "test_accept.py").write_bytes(b"def test_a():\n    assert 1\n")
    (base / "CONTRIBUTING.md").write_bytes(b"# Rules\n\n- Do not leave print() debug statements in code.\n")
    diff = ("diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,3 @@\n def add(a, b):\n"
            "+    print(a, b)\n     return a + b\n")
    store = history.SibylStore.local(tmp_path / "store")
    v = prove.judge_with_rules(base, tmp_path / "pr", {"issue": "1"}, ["calc.py"], diff, store, "o/r", "bot")
    assert not v["passed"] and v["reasons"][0].startswith("repo rule: calc.py:2")
    assert v["evidence"]["required_by_history"] == [] and v["evidence"]["learned"] == ["tamper:rule:no_debug"]
    again = history.SibylStore.local(tmp_path / "store")   # a later run: the memory restored from the cache
    v2 = prove.judge_with_rules(base, tmp_path / "pr", {"issue": "1"}, ["calc.py"], diff, again, "o/r", "other")
    assert v2["evidence"]["required_by_history"] == ["tamper:rule:no_debug"]
