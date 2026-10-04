"""The zero-secret GitHub relay (ghrelay), the caller workflow."""

import base64
import hashlib
import json
import re
import time
from pathlib import Path


from knos.proof import ghrelay

ROOT = Path(__file__).resolve().parents[1]
JOB = "ab" * 32
PAYOUT = "EwSxyJFNQkNN9qtss4Qd7DTvrNYb62vgvhdwqgfErXDz"


def jwt(aud: str, exp: float | None = None) -> str:
    def enc(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    return f"{enc({'alg': 'RS256', 'kid': 'k1'})}.{enc({'aud': aud, 'exp': exp or time.time() + 300})}.c2ln"


def test_checks_hash_is_sorted_paths_each_with_its_content_hash(tmp_path):
    d = tmp_path / ".knos" / "acceptance" / "1"
    (d / "sub").mkdir(parents=True)
    (d / "test_accept.py").write_bytes(b"def test_x():\n    assert 1\n")
    (d / "sub" / "data.txt").write_bytes(b"x")
    want = hashlib.sha256()
    for rel, data in sorted([("sub/data.txt", b"x"), ("test_accept.py", b"def test_x():\n    assert 1\n")]):
        want.update(f"{rel}\0{hashlib.sha256(data).hexdigest()}\n".encode())
    assert ghrelay.checks_hash(d) == want.hexdigest()
    # 0.3.11's fund.yml computed the same hash in a script of its own, which had to be kept equal to this one by a
    # test. Now the workflow computes nothing: one command does, and this is the only place the hash is made.
    src = (ROOT / ".github" / "workflows" / "fund.yml").read_text(encoding="utf-8")
    assert "hashlib" not in src and "python3 -" not in src


def test_relay_one_reports_in_words_and_checks_the_marker():
    paid = {"ok": True, "kind": "pay", "sigs": ["s1", "s2", "s3", "s4"], "issue": 7, "author_id": 4242,
            "paid": [{"job": "J1", "amount": 5_000_000, "fee": 125_000, "mint": "M", "waits": 0}]}
    r = ghrelay.relay_one(None, None, "proof", "x.y.z", submit=lambda *a: dict(paid))
    assert r["ok"] and "4.88 is now waiting under GitHub user id 4242 for issue #7" in r["note"] and "#claim" in r["note"]
    line = ghrelay.log_line("proof", "o/r", 9, "x.y.z", r)
    assert line.startswith(f"knos-relay proof o/r#9 {ghrelay.token_id('x.y.z')} ok sig=s2,s3,s4 note=")
    waits = dict(paid, paid=[dict(paid["paid"][0], waits=3600)])
    note = ghrelay.relay_one(None, None, "proof", "x.y.z", submit=lambda *a: waits)["note"]
    assert "4.88 will be released in 1 h (a maintainer's /knos veto on the issue takes it back) to GitHub user id 4242" in note
    funded = {"ok": True, "kind": "fund", "sigs": ["f"], "job": "J", "issue": 3, "amount": 5_000_000, "mode": 0, "review": 3600}
    note = ghrelay.relay_one(None, None, "fund", "t", submit=lambda *a: dict(funded))["note"]
    assert "5.00 test USDC is in escrow for issue #3, paid when a maintainer merges" in note and "released 1 h after that" in note
    # a fund token posted under a proof marker is refused; a failure is passed through and logged as fail
    assert not ghrelay.relay_one(None, None, "proof", "t", submit=lambda *a: dict(funded))["ok"]
    bad = ghrelay.relay_one(None, None, "fund", "t", submit=lambda *a: {"ok": False, "why": "token expired"})
    assert ghrelay.log_line("fund", "o/r", 1, "t", bad).endswith("fail token expired")


def test_found_and_discover():
    t = jwt("knos:fund:3:1:0:" + "0" * 64 + ":1209600:0")
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
    assert ghrelay.discover("2026-10-02T00:00:00Z", {}, getter=getter) == {"a/b", "drexthealpha/knos-e2e-1", ghrelay.ROTATE_REPO,
                                                                            ghrelay.HOME_REPO}
    for kind in ("veto", "claim", "key", "proof"):
        assert ghrelay.TOKEN.findall(f"knos-{kind}: {t}") == [(kind, t)]


def test_caller_workflow_needs_no_secret_and_names_one_published_commit():
    wf = (ROOT / "examples" / "knos-workflow.yml").read_text(encoding="utf-8")
    # no secret is needed; the one a repository may set is handed on by name, never all of them
    assert set(re.findall(r"secrets\.(\w+)", wf)) == {"KNOS_RELAY_KEY"} and "inherit" not in wf and "No secret is needed" in wf
    # the workflows are pinned by one commit of drexthealpha/knos-workflows; until a release names it the template
    # carries a placeholder, and the release puts the commit into the examples and the site together
    pins = set(re.findall(r"drexthealpha/knos-workflows/\.github/workflows/(?:fund|prove)\.yml@(\S+)", wf))
    assert len(pins) == 1 and re.fullmatch(r"KNOS_WORKFLOWS_SHA|[0-9a-f]{40}", next(iter(pins)))
    code = "\n".join(ln for ln in wf.splitlines() if not ln.lstrip().startswith("#"))
    assert "pull_request_target" not in code and "issue_comment" in code and "push" in code
    assert "relay.yml" not in wf and "drexthealpha/Knos/.github/workflows" not in wf     # nothing of the first deployment's
    fund = (ROOT / ".github" / "workflows" / "fund.yml").read_text(encoding="utf-8")
    assert "id-token: write" in fund and 'knos command --event "$GITHUB_EVENT_PATH" --repo "$GITHUB_REPOSITORY"' in fund


def test_the_site_hands_out_the_examples_byte_for_byte():
    """web/front.js carries the two files a repository installs as templates. They are written from examples/ by
    scripts/front_workflow.py and by nothing else: after an example changes, run `python scripts/front_workflow.py`."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("front_workflow", ROOT / "scripts" / "front_workflow.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--check"]) == 0, "web/front.js does not hand out examples/: run python scripts/front_workflow.py"
    js = (ROOT / "web" / "front.js").read_text(encoding="utf-8")
    check = re.search(r"export const CHECK_WORKFLOW = `(.*?)`;\n", js, re.DOTALL).group(1)
    code = "\n".join(ln for ln in check.splitlines() if not ln.lstrip().startswith("#"))      # its comments say it asks for none
    assert "knos-workflows/.github/workflows/check.yml@" in code and "id-token" not in code and "write" not in code
    net = (ROOT / ".github" / "workflows" / "network.yml").read_text(encoding="utf-8")
    assert 'bash scripts/build_site.sh _site "$GITHUB_SHA"' in net
    assert "settings/rules/new?target=branch&enforcement=active" in js


def test_judge_learns_a_contributing_violation_and_requires_it_next(tmp_path):
    from knos import judge as prove
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


def test_fund_yml_hands_the_event_to_one_command_and_parses_nothing_itself():
    """0.3.11's fund.yml read the comment and built the audience in an inline script, checked here against the client.
    A script in YAML can drift from the client and is hard to test. Now `knos command` reads GitHub's event file and
    does all of it (tests/test_commands.py and the command's own tests); who may fund is decided by the chain, from
    GitHub's signature of who commented, not by a label on the comment."""
    import yaml
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "fund.yml").read_text(encoding="utf-8"))
    [job] = doc["jobs"].values()
    scripts = [s["run"] for s in job["steps"] if "run" in s]
    assert scripts[-1] == 'knos command --event "$GITHUB_EVENT_PATH" --repo "$GITHUB_REPOSITORY"' and len(scripts) == 2
    text = json.dumps(job)
    assert "author_association" not in text and "comment.body" not in text and "issue.body" not in text
    assert not [s for s in job["steps"] if "artifact" in str(s.get("uses", ""))]       # the token is the command's to post or relay
