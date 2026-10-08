"""The GitLab round as one command (scripts/gitlab_round.py): on the simulator, with a stand-in for gitlab.com whose
tokens the test key signs, a wallet funds an order for a GitLab project, a pipeline that a pipeline started signs
the pay audience, knos_oidc verifies the token and knos_pay pays the merge request's author. Without credentials the
command says what is missing and exits 3. A token the escrow would refuse is refused before any fee."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts")]

import exercise_public as ep  # noqa: E402
import gitlab_round as gr  # noqa: E402


@pytest.fixture(scope="module")
def world():
    w = ep.Simulated()
    try:
        yield w, gr.simulated_forge(w)
    finally:
        w.close()


def _round(w, forge, said):
    ev = ep.new_evidence(w, ep.simulated_programs())
    st = ev["rounds"].setdefault("gitlab", {"round": "gitlab"})
    return ev, st, ep.Book(ev, w, said.append)


def test_the_round_pays_a_merge_request_author_on_a_token_the_stand_in_signed_and_sends_nothing_twice(world):
    w, forge = world
    said: list[str] = []
    ev, st, book = _round(w, forge, said)
    gr.round_gitlab(book, st, ep, forge=forge)
    assert ev["exercises"]["verify_gitlab"]["status"] == ev["exercises"]["gitlab_pay"]["status"] == "exercised"
    assert ev["exercises"]["verify_gitlab"]["program"] == "knos_oidc" and ev["exercises"]["gitlab_pay"]["program"] == "knos_pay"
    assert [t["program"] for t in st["transactions"]] == ["knos_pay", "knos_oidc", "knos_pay"]
    assert st["paid"]["amount"] == ep.AMOUNT and st["paid"]["payee"] == gr.GL_ID + forge.USER
    # the pin is the example's own file on the protected branch, and the order named its commit
    assert forge.file(gr.BRANCH, gr.CI_FILE) == gr.PINNED.read_text(encoding="utf-8") and gr.BRANCH in forge.protected
    assert st["order"]["pin"] == forge.shas[gr.BRANCH] and forge.file("main", gr.CI_FILE) == gr.TRIGGER
    sent = len(st["transactions"])
    gr.round_gitlab(book, st, ep, forge=forge)
    assert len(st["transactions"]) == sent


def test_a_token_signed_for_a_pipeline_run_by_hand_is_refused_before_any_fee(world):
    w, forge = world
    ev, st, book = _round(w, forge, [])
    forge.source = "web"
    try:
        with pytest.raises(ep.Failed, match="`pipeline_source` is 'web'; the escrow takes only 'pipeline'.*No fee was spent"):
            gr.round_gitlab(book, st, ep, forge=forge)
    finally:
        forge.source = "pipeline"
    assert [t["program"] for t in st["transactions"]] == ["knos_pay"] and "token" not in st and "paid" not in st     # the funding alone
    gr.round_gitlab(book, st, ep, forge=forge)          # the same order, a new pipeline: paid
    assert "paid" in st and len([t for t in st["transactions"] if "funds an order" in t["what"]]) == 1


def test_without_credentials_the_command_says_exactly_what_is_missing_and_exits_3(monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("KNOS_GITLAB_PROJECT", raising=False)
    said: list[str] = []
    assert gr.main(["run"], said.append) == 3
    text = "\n".join(said)
    assert "GITLAB_TOKEN is not set" in text and "KNOS_GITLAB_PROJECT is not set" in text and "--rpc and --keys are not given" in text
    assert gr.main(["check"], said.append) == 3
    assert gr.missing({"GITLAB_TOKEN": "x"}, {"project": "g/p"}) == [] and gr.missing({}, {"project": "g/p"}) == [gr.MISSING["GITLAB_TOKEN"]]

    class NoKeys:               # the round inside exercise_public: a public world with nothing set asks for a run, and fails nothing
        mode = "public"
        def outside(self, name):
            return None
    with pytest.raises(ep.Need, match="needs run: the GitLab round") as need:
        gr.round_gitlab(ep.Book({"rounds": {}, "exercises": {}}, NoKeys(), said.append), {"round": "gitlab"}, ep, env={})
    assert "GITLAB_TOKEN is not set" in need.value.how


def test_the_pinned_jobs_checks_are_the_ones_the_carrier_repeats():
    wallet = "EwSxyJFNQkNN9qtss4Qd7DTvrNYb62vgvhdwqgfErXDz"
    project = {"id": 20, "path": "g/p", "namespace_id": 72, "default_branch": "main"}
    mr = {"state": "merged", "target_branch": "main", "sha": "a" * 40, "author_id": 77, "description": f"text\n\nKnos-Pay-To: {wallet}"}
    default = {"sha": "b" * 40, "protected": True, "default": True}
    aud = f"knos3:pay:{wallet}:{'a' * 40}:{'00' * 32}:0:5:{gr.GL_ID + 77}.10000.{wallet}"
    assert gr.judge(aud, project, mr, default)[0] == gr.GL_ID + 77
    for change, why in (({"state": "opened"}, "not merged"), ({"target_branch": "dev"}, "default branch"), ({"sha": "c" * 40}, "head"),
                        ({"author_id": 78}, "author"), ({"description": f"Knos-Pay-To: {wallet} and more"}, "description")):
        with pytest.raises(gr.Refused, match=why):
            gr.judge(aud, project, {**mr, **change}, default)
    with pytest.raises(gr.Refused, match="not protected"):
        gr.judge(aud, project, mr, {**default, "protected": False})
    with pytest.raises(gr.Refused, match="whole amount"):
        gr.judge(aud.replace(".10000.", ".5000."), project, mr, default)
    # each of those is a line of the example's paying job, and the trigger job is YAML GitLab can load
    import yaml
    job = "\n".join(yaml.safe_load(gr.PINNED.read_text(encoding="utf-8"))["knos-pay"]["script"])
    for line in ('test "$SHARE" = 10000', "= merged", ".target_branch mr.json", '.sha mr.json)" = "$HEAD"', ".author.id mr.json", "Knos-Pay-To: $ADDRESS",
                 "repository/branches/", '= "true true"'):
        assert line in job, line
    assert "protected_branches" not in job          # that endpoint needs a token the job does not have
    trigger = yaml.safe_load(gr.TRIGGER)["knos-pay"]
    assert trigger["trigger"] == {"project": "$CI_PROJECT_PATH", "branch": gr.BRANCH} and trigger["variables"] == {"KNOS_AUD": "$KNOS_AUD"}


def test_the_claims_are_held_to_the_escrows_rules_one_by_one():
    project = {"id": 20, "path": "g/p", "namespace_id": 72}
    good = {"iss": "https://gitlab.com", "iat": 1000, "exp": 1300, "runner_environment": "gitlab-hosted", "ref_type": "branch", "ref_protected": "true",
            "pipeline_source": "pipeline", "ref_path": "refs/heads/knos", "project_path": "g/p", "ci_config_ref_uri": "gitlab.com/g/p//.gitlab-ci.yml@refs/heads/knos",
            "ci_config_sha": "e" * 40, "project_id": "20", "namespace_id": "72", "aud": "knos3:pay:x"}
    gr.spend_checks(good, project, "e" * 40, "knos3:pay:x", 1100)
    for claim, value in (("runner_environment", "self-hosted"), ("ref_protected", "false"), ("pipeline_source", "api"), ("ci_config_sha", "f" * 40),
                         ("ci_config_ref_uri", None), ("project_id", "21"), ("aud", "knos3:pay:y"), ("iss", "https://gitlab.example.com")):
        with pytest.raises(gr.Refused, match=f"`{claim}`"):
            gr.spend_checks({**good, claim: value}, project, "e" * 40, "knos3:pay:x", 1100)
    with pytest.raises(gr.Refused, match="lives over an hour"):
        gr.spend_checks({**good, "exp": 1000 + 3601}, project, "e" * 40, "knos3:pay:x", 1100)
    with pytest.raises(gr.Refused, match="expired"):
        gr.spend_checks(good, project, "e" * 40, "knos3:pay:x", 1300 + 3600)


def test_gitlabs_api_is_asked_at_the_documented_paths_with_the_token_in_a_header():
    asked: list[tuple[str, str, dict | None]] = []
    answers = {
        ("GET", "/projects/g%2Fp"): {"id": 20, "path_with_namespace": "g/p", "namespace": {"id": 72}, "default_branch": "main", "visibility": "public",
                                     "shared_runners_enabled": True},
        ("GET", "/user"): {"id": 4242, "username": "u"},
        ("GET", "/projects/g%2Fp/repository/branches/knos"): {"commit": {"id": "e" * 40}, "protected": True, "default": False},
        ("POST", "/projects/g%2Fp/pipeline"): {"id": 9},
        ("GET", "/projects/g%2Fp/pipelines/9/bridges"): [{"name": "knos-pay", "downstream_pipeline": {"id": 10}}],
        ("GET", "/projects/g%2Fp/pipelines/10/jobs"): [{"name": "knos-pay", "id": 11, "status": "success"}],
    }

    def http(method, url, body, headers):
        assert headers == {"PRIVATE-TOKEN": "secret"} and url.startswith(gr.API)
        path = url.removeprefix(gr.API)
        asked.append((method, path, body))
        if path == "/projects/g%2Fp/jobs/11/artifacts/knos-token.jwt":
            return 200, b"a.b.c\n"
        if (method, path) in answers:
            return 200, json.dumps(answers[(method, path)]).encode()
        return 404, b"{}"
    g = gr.GitLab("g/p", "secret", http)
    assert g.project() == {"id": 20, "path": "g/p", "namespace_id": 72, "default_branch": "main", "visibility": "public", "runners": True}
    assert g.user()["id"] == 4242 and g.branch("knos") == {"sha": "e" * 40, "protected": True, "default": False} and g.branch("none") is None
    assert g.start("main", "knos3:pay:x") == 9
    assert asked[-1] == ("POST", "/projects/g%2Fp/pipeline", {"ref": "main", "variables": [{"key": "KNOS_AUD", "value": "knos3:pay:x"}]})
    assert g.token(9) == {"state": "success", "jwt": "a.b.c", "job": 11}
    answers[("GET", "/projects/g%2Fp/pipelines/10/jobs")] = [{"name": "knos-pay", "id": 11, "status": "failed", "web_url": "u"}]
    assert g.token(9)["state"] == "failed"
    del answers[("GET", "/projects/g%2Fp/pipelines/9/bridges")]
    assert g.token(9)["state"] == "running"
