"""Terms proposed from a repository's own record (src/knos/propose_terms.py), on an invented repository in the shape of GitHub's answers: no network.

tests/data/propose_terms.json holds what GitHub's REST API answers for one repository and the proposal made from it;
web/propose_terms.js is held to the same `expected` by tests/web/terms.mjs.
"""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from knos import propose_terms as pt, terms, terms3, terms_templates

FIXTURE = json.loads((Path(__file__).resolve().parent / "data" / "propose_terms.json").read_text(encoding="utf-8"))
REPO, NOW = FIXTURE["repo"], pt.seconds(FIXTURE["now"])


def _reader(api=None):
    api, asked = FIXTURE["api"] if api is None else api, []

    def get(path):
        asked.append(path)
        return api.get(path)
    return get, asked


def test_the_proposal_is_the_recorded_one_and_a_valid_terms_3_file():
    get, asked = _reader()
    got = pt.propose(REPO, get, NOW)
    assert got == FIXTURE["expected"]
    assert terms3.validate(got["terms"]) == got["terms"] and terms3.digest(got["terms"]) == got["hash"]
    assert len(asked) <= 17 and all(p.startswith(f"repos/{REPO}") for p in asked)
    assert terms3.order_terms(got["terms"])["contract"] == got["hash"]


def test_the_checks_that_passed_on_every_recent_merge_decide_and_the_others_are_said():
    got = pt.propose(REPO, _reader()[0], NOW)
    assert [c["name"] for c in got["terms"]["checks"]["deciding"]] == ["license/cla", "unit"]
    src = got["from"]["checks"]
    assert "`unit` passed on every one of the last 10 merged pull requests (#130 to #140)." in src
    assert "Left out: `lint` did not pass on #138." in src            # one failed attempt on one merge is enough
    assert "Left out: `build (ubuntu-latest)` ran on 9 of 10 merges." in src and "Left out: `docs` did not pass on #136." in src
    assert not any("knos / check" in s for s in src)                   # Knos's own job is never evidence
    assert got["merges"] == 10 and got["last_merge"] == "2026-09-28T10:00:00Z"   # the unmerged closed pull request is not a merge
    assert got["comment"] == "/knos fund 50 checks: license/cla, unit paths: src/** days 14"


def test_test_directories_become_protected_paths_and_codeowners_name_who_changes_the_policy():
    got = pt.propose(REPO, _reader()[0], NOW)
    assert got["terms"]["changes"] == {**got["terms"]["changes"], "paths": ["src/**"], "protected": [".github/**", ".knos/**", "e2e/**", "tests/**"], "may_add": []}
    assert got["terms"]["policy"]["may_change"] == ["@acme/platform", "@alice"]
    assert got["from"]["policy"] == ["`.github/CODEOWNERS` names @acme/platform, @alice for every file."]
    assert terms3.order_terms(got["terms"])["deny"] == [".github/**", ".knos/**", "e2e/**", "tests/**"]


def test_every_proposed_field_says_where_it_came_from_and_the_rest_is_the_template_default():
    got = pt.propose(REPO, _reader()[0], NOW)
    assert set(got["from"]) == set(terms3.NAMES) and all(lines and all(s.endswith(".") for s in lines) for lines in got["from"].values())
    default = terms3.template("bug-fix")
    for field in ("deliverable", "window", "price", "deadline", "dispute"):
        assert {k: v for k, v in got["terms"][field].items()} == default[field]
        assert got["from"][field][0].startswith("Template default")
    text = pt.text(got)
    assert text.count("      from: ") == sum(len(v) for v in got["from"].values()) and "Last merge: 2026-09-28" in text
    assert "Nothing was funded, posted or opened." in text


def test_no_merge_in_thirty_days_no_proposal_and_the_date_is_said():
    with pytest.raises(pt.Refused, match=r"acme/widgets last merged a pull request on 2026-09-28, 31 days ago\. Nothing is proposed"):
        pt.propose(REPO, _reader()[0], pt.seconds("2026-10-29T12:00:00Z"))
    assert pt.propose(REPO, _reader()[0], pt.seconds("2026-10-28T09:00:00Z"))["merges"] == 10      # day 30 is still inside
    api = copy.deepcopy(FIXTURE["api"])
    key = next(k for k in api if "/pulls?" in k)
    api[key] = [{**p, "merged_at": None} for p in api[key]]
    with pytest.raises(pt.Refused, match="has no merged pull request"):
        pt.propose(REPO, _reader(api)[0], NOW)


def test_a_repository_that_cannot_be_read_or_named_is_refused_in_plain_words():
    with pytest.raises(pt.Refused, match="octo/private was not found. Only a public repository can be read without signing in."):
        pt.propose("octo/private", _reader()[0], NOW)
    for bad in ("widgets", "a b/c", "", "acme/widgets/extra"):
        with pytest.raises(pt.Refused, match="Name the repository as owner/name"):
            pt.propose(bad, _reader()[0], NOW)
    assert pt.propose("https://github.com/acme/widgets/", _reader()[0], NOW)["repo"] == "acme/widgets"


def test_a_bare_repository_gets_the_defaults_and_says_so():
    api = {k: v for k, v in FIXTURE["api"].items() if "/contents/" not in k and "check-runs" not in k}
    api[f"repos/{REPO}/contents/?ref=main"] = [{"name": "lib", "type": "dir"}]
    got = pt.propose(REPO, _reader(api)[0], NOW)
    t = got["terms"]
    assert t["checks"]["deciding"] == [] and t["changes"]["paths"] == [] and t["changes"]["protected"] == list(terms.DENY)
    assert t["policy"]["may_change"] == ["@acme"] and got["from"]["policy"] == ["acme/widgets has no CODEOWNERS file, so the owner, @acme, is proposed."]
    assert got["from"]["checks"][0].startswith("The check runs of the recent merges could not be read")
    assert "No workflow file was found in .github/workflows." in got["from"]["checks"]
    assert got["from"]["changes"][0] == "No test directory was found at the top of acme/widgets; nothing beyond the default is protected."
    assert terms3.validate(t) == t


def test_checks_that_do_not_fit_an_orders_terms_are_left_out_and_said():
    api = copy.deepcopy(FIXTURE["api"])
    extra = [{"name": f"matrix / a rather long job name number {i:02d}", "status": "completed", "conclusion": "success", "app": {"id": 15368}} for i in range(12)]
    for key in api:
        if "check-runs" in key:
            api[key]["check_runs"] += extra
    got = pt.propose(REPO, _reader(api)[0], NOW)
    kept = got["terms"]["checks"]["deciding"]
    assert 2 <= len(kept) < 14 and len(terms.canonical(terms3.order_terms(got["terms"]))) <= terms.MAX_BYTES
    assert sum("an order's terms have no room for it (600 bytes)" in s for s in got["from"]["checks"]) == 14 - len(kept)


def test_codeowners_owners_of_everything_are_the_last_star_line():
    assert pt.owners("* @a\n/src @b\n* @c @org/team # all\n") == ["@c", "@org/team"]
    assert pt.owners("/src @b\n*.md @docs\n") == [] and pt.owners("* not-an-owner someone@example.com\n") == []
    api = copy.deepcopy(FIXTURE["api"])
    api[f"repos/{REPO}/contents/.github/CODEOWNERS?ref=main"]["content"] = base64.b64encode(b"/src @bob\n").decode()
    assert pt.propose(REPO, _reader(api)[0], NOW)["from"]["policy"] == ["`.github/CODEOWNERS` names nobody for every file, so the owner, @acme, is proposed."]


def test_knos_terms_propose_prints_the_draft_and_writes_the_file(tmp_path, monkeypatch):
    app = typer.Typer()
    terms_templates.register(app)
    monkeypatch.setattr(pt, "reader", lambda: _reader()[0])
    monkeypatch.setattr("time.time", lambda: float(NOW))
    out = tmp_path / ".knos" / "terms.json"
    got = CliRunner().invoke(app, ["terms", "propose", REPO, "--out", str(out)])
    assert got.exit_code == 0 and got.output.startswith("Proposed terms for acme/widgets (Knos Terms 3). Last merge: 2026-09-28; 10 recent merges read.")
    assert json.loads(out.read_text(encoding="utf-8")) == FIXTURE["expected"]["terms"]
    assert CliRunner().invoke(app, ["terms", "verify", str(out)]).exit_code == 0
    as_json = CliRunner().invoke(app, ["terms", "propose", REPO, "--json"])
    assert json.loads(as_json.output) == FIXTURE["expected"]
    monkeypatch.setattr(pt, "reader", lambda: (lambda path: None))
    gone = CliRunner().invoke(app, ["terms", "propose", "octo/none"])
    assert gone.exit_code == 1 and gone.output.strip() == "octo/none was not found. Only a public repository can be read without signing in."
