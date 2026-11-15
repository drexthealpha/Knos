"""A signed reproduction checked by anyone: `knos reproduce --verify` on the run's file, its artifact or its URL, offline
against GitHub's keys; the run's wall time from signed bytes; and scripts/reproductions.py, which lists verified
reproductions by repository owner and never Knos's own. No network: the key is the tests' own."""

from __future__ import annotations

import base64
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

from knos import reproduce as rp

from _settle import NOW, github_claims, sign_jwt, signing_key

ROOT = Path(__file__).resolve().parents[1]
OWN = json.loads((ROOT / "scripts" / "own_github_ids.json").read_text(encoding="utf-8"))
KEY = signing_key()
KEYS = {"k": KEY.n}
spec = importlib.util.spec_from_file_location("reproductions_script", ROOT / "scripts" / "reproductions.py")
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


def _clock():
    t = [0.0]

    def clock() -> float:
        t[0] += 1.5
        return t[0]
    return clock


def _report(started: int | None = NOW - 140, **checks) -> dict:
    fakes = {"payment": lambda: {"transaction": "sig"}, "programs": lambda: {"programs": {}}, "claim": lambda: {"verdict": "false"}}
    return rp.build({**fakes, **checks}, version="0.3.25", commit="", now=lambda: NOW - 20, clock=_clock(), started=started)


def _signed(report: dict, **claims) -> dict:
    return {"report": report, "token": sign_jwt(KEY, github_claims(aud=rp.AUDIENCE + rp.digest(report), event_name="workflow_dispatch", **claims))}


def _jwks(path: Path) -> Path:
    n = KEY.n.to_bytes((KEY.n.bit_length() + 7) // 8, "big")
    path.write_text(json.dumps({"keys": [{"kty": "RSA", "kid": "k", "e": "AQAB", "alg": "RS256", "use": "sig",
                                          "n": base64.urlsafe_b64encode(n).rstrip(b"=").decode()}]}), encoding="utf-8")
    return path


def _write(folder: Path, doc: dict, name: str = "octo-widgets-36905461215.json") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    return folder / name


# ---- the wall time, from signed bytes -----------------------------------------------------------------------------------

def test_the_wall_time_is_githubs_signing_time_less_the_first_steps_time_and_only_when_both_agree():
    report = _report()
    assert report["started"] == NOW - 140 and "started" not in _report(started=None)       # a report made by hand has none
    facts, wrong = rp.verified(_signed(report), KEYS, OWN, "octo-widgets-36905461215.json")
    assert wrong == [] and facts["wall_seconds"] == 140
    assert rp.verified(_signed(_report(started=None)), KEYS, OWN)[0]["wall_seconds"] is None
    assert rp.wall({"started": NOW + 5, "at": NOW}, {"iat": NOW}) is None              # began after it was signed
    assert rp.wall({"started": NOW - 200_000}, {"iat": NOW}) is None                    # longer than a day: not this run
    assert rp.wall({"started": True}, {"iat": NOW}) is None and rp.wall({"started": NOW - 9, "at": NOW + 600}, {"iat": NOW}) is None
    assert rp.started_from({"KNOS_REPRO_STARTED": "1790000000\n"}) == 1_790_000_000
    assert rp.started_from({"KNOS_REPRO_STARTED": "-3"}) is None and rp.started_from({}) is None and rp.started_from({"KNOS_REPRO_STARTED": "9" * 13}) is None


def test_the_workflow_starts_the_clock_in_its_first_step_under_the_name_the_command_reads():
    yaml = pytest.importorskip("yaml")
    for path in (ROOT / "examples" / "knos-reproduce.yml", ROOT / ".github" / "workflows" / "knos-reproduce.yml"):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        first = doc["jobs"]["run"]["steps"][0]
        assert first["run"] == 'echo "KNOS_REPRO_STARTED=$(date +%s)" >> "$GITHUB_ENV"'
        assert "KNOS_REPRO_STARTED" in Path(rp.__file__).read_text(encoding="utf-8")
        assert "KNOS_REPRO_STARTED" not in json.dumps(doc["jobs"]["sign"])           # the signing job is unchanged: it hashes bytes and asks


# ---- --verify -----------------------------------------------------------------------------------------------------------

def _app():
    typer = pytest.importorskip("typer")
    app = typer.Typer()
    app.command("other")(lambda: None)
    rp.register(app, [])
    return app


def _invoke(*args: str):
    from typer.testing import CliRunner
    return CliRunner().invoke(_app(), ["reproduce", *args])


def test_verify_accepts_the_file_the_artifacts_zip_its_folder_and_the_runs_url_and_says_where_the_keys_came_from(tmp_path, monkeypatch):
    keys = str(_jwks(tmp_path / "jwks.json"))
    doc = _signed(_report())
    made = _write(tmp_path / "knos-reproduction", doc)
    with zipfile.ZipFile(tmp_path / "knos-reproduction.zip", "w") as z:
        z.writestr(made.name, made.read_text(encoding="utf-8"))
    monkeypatch.chdir(tmp_path)
    url = "https://github.com/octo/widgets/actions/runs/36905461215"
    for target in (str(made), str(tmp_path / "knos-reproduction.zip"), str(tmp_path / "knos-reproduction"), url, url + "/attempts/1"):
        got = _invoke("--verify", target, "--keys", keys)
        assert got.exit_code == 0, (target, got.output)
        assert "a valid outside reproduction" in got.output and rp.digest(doc["report"]) in got.output
        assert "140 s from the workflow's first step to GitHub's signature" in got.output and "commit " + "a" * 40 in got.output
        assert f"GitHub's keys: {keys} (1)" in got.output and "supports: check, order_pay, upgrade_delay, upgrade_feed" in got.output
    # the URL of a run whose file is not here: what to download, and from where
    got = _invoke("--verify", "https://github.com/octo/widgets/actions/runs/1", "--keys", keys)
    assert got.exit_code == 2 and "gh run download 1 -R octo/widgets -n knos-reproduction" in got.output
    assert _invoke("--verify", str(tmp_path / "nothing.json"), "--keys", keys).exit_code == 2
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert _invoke("--verify", str(tmp_path / "bad.json"), "--keys", keys).exit_code == 2


def test_verify_refuses_an_edited_report_a_failed_check_another_key_and_calls_an_own_run_what_it_is(tmp_path):
    keys = str(_jwks(tmp_path / "jwks.json"))
    doc = _signed(_report())
    edited = _write(tmp_path / "edited", {"report": {**doc["report"], "knos": "9.9.9"}, "token": doc["token"]})
    got = _invoke("--verify", str(edited), "--keys", keys)
    assert got.exit_code == 1 and "not a reproduction" in got.output and "edited after it was signed" in got.output

    def boom():
        raise rp.Fail("devnet runs another build")
    failed = _write(tmp_path / "failed", _signed(_report(programs=boom)))
    got = _invoke("--verify", str(failed), "--keys", keys)
    assert got.exit_code == 1 and "`programs` failed in this run: that is a bug report" in got.output

    skipped = _write(tmp_path / "skipped", _signed(rp.build({"simulator": lambda: (_ for _ in ()).throw(rp.Skip("no checkout"))}, version="0.3.25", now=lambda: NOW)))
    assert "no check passed" in _invoke("--verify", str(skipped), "--keys", keys).output

    other = tmp_path / "other.json"
    other.write_text(json.dumps({"keys": [{"kty": "RSA", "kid": "k", "e": "AQAB", "n": "AQAB"}]}), encoding="utf-8")
    assert "signature is not GitHub's" in _invoke("--verify", str(_write(tmp_path / "ok", doc)), "--keys", str(other)).output

    own = _write(tmp_path / "own", _signed(_report(), repository="drexthealpha/knos-e2e", repository_owner="drexthealpha",
                                            repository_owner_id=str(OWN["ids"][0])), "drexthealpha-knos-e2e-36905461215.json")
    got = _invoke("--verify", str(own), "--keys", keys)
    assert got.exit_code == 1 and "the run is Knos's own: it is not a reproduction and counts for nothing" in got.output


def test_the_keys_come_from_the_file_given_else_the_checkouts_archive_else_github_and_the_output_says_which(tmp_path):
    keys, own, said = rp.keys_and_own(ROOT, _jwks(tmp_path / "jwks.json"), {})
    assert keys == KEYS and own == OWN and said[0].endswith("(1)")
    archived = rp.keys_of(json.loads((ROOT / "scripts" / "github_oidc_keys.json").read_text(encoding="utf-8")))
    keys, _own, said = rp.keys_and_own(ROOT, None, {})
    assert keys == archived and "as archived" in said[0] and "no network" in said[0]
    asked: list = []

    def unreachable():
        raise OSError("no route")
    keys, own, said = rp.keys_and_own(None, None, {}, fetch=lambda url: asked.append(url) or {"keys": []}, read=unreachable)
    assert asked == [rp.JWKS] and "read now from" in said[0] and own == {"ids": []} and "only the account drexthealpha" in said[1]


# ---- scripts/reproductions.py ---------------------------------------------------------------------------------------------

def test_reproductions_are_listed_by_repository_owner_and_knos_own_runs_and_bad_files_never_are(tmp_path):
    a = _write(tmp_path, _signed(_report()))
    b = _write(tmp_path, _signed(_report(started=None), run_id="36905461299"), "octo-widgets-36905461299.json")
    c = _write(tmp_path, _signed(_report(), repository="ada/lab", repository_owner="ada", repository_owner_id="77", run_id="5"), "ada-lab-5.json")
    own = _write(tmp_path, _signed(_report(), repository="drexthealpha/knos-e2e", repository_owner="drexthealpha", repository_owner_id=str(OWN["ids"][0])),
                 "drexthealpha-knos-e2e-36905461215.json")
    by_id = _write(tmp_path, _signed(_report(), repository="ada/side", repository_owner="ada", repository_owner_id="77", actor_id=str(OWN["ids"][0]), run_id="6"),
                   "ada-side-6.json")
    dup = _write(tmp_path / "again", _signed(_report()))
    got = script.survey([a, b, c, own, by_id, dup], KEYS, OWN)
    assert [o["owner"] for o in got["owners"]] == ["ada", "octo"] and got["runs"] == 3
    assert [r["wall_seconds"] for r in got["owners"][1]["runs"]] == [140, None]
    assert got["own"] == 2                       # an own repository's run, and a run an own account started elsewhere: neither listed
    assert [(r["file"], r["why"]) for r in got["refused"]] == [("octo-widgets-36905461215.json", ["the same run is listed twice"])]
    text = "\n".join(script.lines(got))
    assert "Outside reproductions: 3 run(s) by 2 repository owner(s). Knos's own runs, not counted: 2. Refused: 1." in text
    assert "| octo (424242) | octo/widgets | [36905461215](https://github.com/octo/widgets/actions/runs/36905461215) | 0.3.25 | payment, programs, claim | 140 s |" in text
    assert "drexthealpha" not in text.split("refused")[0]


def test_the_repository_holds_no_reproduction_today_and_the_script_says_zero(capsys):
    assert script.main([]) == 0
    assert capsys.readouterr().out.startswith("Outside reproductions: 0 run(s) by 0 repository owner(s). Knos's own runs, not counted: 0. Refused: 0.")
    assert script.main(["--json"]) == 0 and json.loads(capsys.readouterr().out) == {"owners": [], "runs": 0, "own": 0, "refused": []}
    assert script.main(["--nothing"]) == 2
