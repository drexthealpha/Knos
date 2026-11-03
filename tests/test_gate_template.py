"""The Knos Gate template adopters copy never needs pull_request_target (GitHub blocks it by default from 2 Dec 2026).

knos-gate-pr.yml runs the pull request's code on pull_request with no secret; knos-gate.yml starts on workflow_run,
holds the hidden tests and never checks out the pull request.
"""
import pathlib

import yaml

GATE = pathlib.Path(__file__).resolve().parents[1] / "actions" / "gate"
PR_FLOW, RUN_FLOW = GATE / "knos-gate-pr.yml", GATE / "knos-gate.yml"


def on(doc):
    return doc.get("on", doc.get(True))     # PyYAML reads the key `on` as True


def test_no_gate_file_names_pull_request_target():
    hits = [f"{p.name}:{n}" for p in sorted(GATE.glob("*.yml")) for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if "pull_request_target" in line]
    assert hits == []


def test_the_pull_request_half_has_no_secret_and_a_read_only_token():
    text = PR_FLOW.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert list(on(doc)) == ["pull_request"]
    assert doc["permissions"] == {"contents": "read"}
    assert "secrets." not in text and "id-token" not in text
    for job in doc["jobs"].values():
        assert "permissions" not in job
        for step in job["steps"]:
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False


def test_the_secret_half_starts_on_workflow_run_and_never_checks_out_the_pull_request():
    doc = yaml.safe_load(RUN_FLOW.read_text(encoding="utf-8"))
    trigger = on(doc)
    assert list(trigger) == ["workflow_run"]
    assert trigger["workflow_run"]["workflows"] == [yaml.safe_load(PR_FLOW.read_text(encoding="utf-8"))["name"]]
    assert doc["permissions"] == {}
    job = doc["jobs"]["gate"]
    assert job["name"] == "Knos Gate" and job["if"] == "github.event.workflow_run.event == 'pull_request'"
    uses = [str(s.get("uses", "")) for s in job["steps"]]
    assert not any(u.startswith("actions/checkout") for u in uses)
    gate = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("drexthealpha/Knos/actions/gate@"))
    assert gate["with"]["head"] == "${{ github.event.workflow_run.head_sha }}"
    assert gate["with"]["hidden-tests"] == "${{ secrets.KNOS_GATE_HIDDEN }}"
    # the untrusted run fields reach a shell only through env, never pasted into the script
    for step in job["steps"]:
        assert "${{" not in step.get("run", "")
