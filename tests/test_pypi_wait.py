"""scripts/pypi_wait.py and the worker's `claims` job: the job waits for PyPI to list the exact knos file
requirements/sign.txt pins before it installs, with growing pauses and an end. No network, no sleep."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("pypi_wait", ROOT / "scripts" / "pypi_wait.py")
PW = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PW)

H, VER = "c" * 64, "0.3.22"


def index(*files: tuple[str, str]) -> dict:
    return {"meta": {"api-version": "1.0"}, "name": "knos", "files": [{"filename": n, "hashes": {"sha256": h}} for n, h in files]}


def test_the_pin_is_read_from_the_real_requirements_file():
    text = (ROOT / "requirements" / "sign.txt").read_text(encoding="utf-8")
    if "\nknos==" not in text:     # a bumped tree before its release locks the wheel (scripts/bump_version.py unlock): no pin yet
        with pytest.raises(SystemExit, match="pins no knos"):
            PW.pinned(text, "knos")
        # the line the release run appends, as 0.3.21's was, read from the real file's own requirements around it
        text += "knos" "==0.3.21 --hash=sha256:c848187f1881c4d5986c8be8a8f89a1abe619bf1b0df689b411efd2aca54e82a\n"
    version, hashes = PW.pinned(text, "knos")
    assert f"knos=={version} --hash=sha256:{next(iter(hashes))}" in text and len(hashes) == 1
    assert PW.pinned("solders==0.29.0 \\\n    --hash=sha256:" + "a" * 64 + " \\\n    --hash=sha256:" + "b" * 64 + "\n", "solders") == ("0.29.0", {"a" * 64, "b" * 64})
    with pytest.raises(SystemExit, match="no --hash"):
        PW.pinned("knos==1.0\n", "knos")
    with pytest.raises(SystemExit, match="pins no knos"):
        PW.pinned("knos-settle==1.0 --hash=sha256:" + H + "\n", "knos")


def test_only_that_version_with_that_hash_counts():
    assert PW.listed(index(("knos-0.3.22-py3-none-any.whl", H)), "knos", "0.3.22", {H})
    assert PW.listed(index(("knos-0.3.22.tar.gz", H)), "knos", "0.3.22", {H})
    assert not PW.listed(index(("knos-0.3.22-py3-none-any.whl", "d" * 64)), "knos", "0.3.22", {H})        # another file
    assert not PW.listed(index(("knos-0.3.221-py3-none-any.whl", H), ("knos_settle-0.3.22-py3-none-any.whl", H)), "knos", "0.3.22", {H})
    assert not PW.listed({}, "knos", "0.3.22", {H})


def test_it_waits_with_growing_pauses_until_the_file_is_listed():
    answers = [OSError("503"), index(), ValueError("half a page"), index(("knos-0.3.22-py3-none-any.whl", H))]
    slept, said = [], []

    def get(_package):
        got = answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got
    assert PW.wait("knos", "0.3.22", {H}, 600, get=get, sleep=slept.append, say=said.append) is True
    assert slept == [5, 10, 20] and said[-1] == "PyPI lists knos 0.3.22 with the pinned hash (after 35 s)"


def test_it_gives_up_after_most_seconds_and_says_what_it_last_saw():
    slept, said = [], []
    assert PW.wait("knos", "0.3.22", {H}, 200, get=lambda _p: index(), sleep=slept.append, say=said.append) is False
    assert slept == [5, 10, 20, 40, 60, 60] and sum(slept) <= 200
    assert said[-1] == "PyPI did not list knos 0.3.22 with the pinned hash within 200 s; last seen: no file of knos 0.3.22 with the pinned hash"



def test_each_line_reaches_the_log_before_the_pause_it_announces(monkeypatch):
    """A job's output is a pipe, which keeps what Python prints until the process ends unless it is flushed: every
    line is out before the wait it announces (in staging on 8 Oct the twelve lines of a ten-minute wait came at once,
    in its last second)."""
    seen = []

    class Pipe:
        def write(self, text):
            seen.append(("write", text))
            return len(text)

        def flush(self):
            seen.append(("flush", None))
    monkeypatch.setattr(PW.sys, "stdout", Pipe())
    assert PW.wait("knos", "0.3.22", {H}, 20, get=lambda _p: index(), sleep=lambda s: seen.append(("sleep", s))) is False
    sleeps = [i for i, (what, _) in enumerate(seen) if what == "sleep"]
    assert [seen[i][1] for i in sleeps] == [5, 10] and seen[-1][0] == "flush"
    for i in sleeps:
        said = max(j for j in range(i) if seen[j][0] == "write" and seen[j][1].startswith("waiting"))
        assert any(seen[j][0] == "flush" for j in range(said, i))

def test_main_reads_the_file_and_exits_by_the_answer(tmp_path, monkeypatch):
    req = tmp_path / "sign.txt"
    req.write_text(f"knos=={VER} --hash=sha256:{H}\n", encoding="utf-8")
    monkeypatch.setattr(PW, "fetch", lambda _p: index(("knos-0.3.22-py3-none-any.whl", H)))
    assert PW.main([str(req)]) == 0
    monkeypatch.setattr(PW, "fetch", lambda _p: index())
    monkeypatch.setattr(PW.time, "sleep", lambda _s: None)
    assert PW.main([str(req), "--most", "1"]) == 1


def test_the_claims_job_waits_for_pypi_before_it_installs():
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / "worker.yml").read_text(encoding="utf-8"))["jobs"]
    runs = [str(s.get("run") or "") for s in jobs["claims"]["steps"]]
    wait = next(i for i, r in enumerate(runs) if "scripts/pypi_wait.py" in r)
    install = next(i for i, r in enumerate(runs) if "-r requirements/sign.txt" in r)
    assert wait < install and runs[wait] == "python3 -I scripts/pypi_wait.py requirements/sign.txt --package knos --most 600"
    assert 600 < jobs["claims"]["timeout-minutes"] * 60                              # the wait ends before the job's own limit
    assert "KEY" not in json.dumps(jobs["claims"]["steps"][wait])                     # no secret near it
    assert all("pypi_wait" not in json.dumps(job) for name, job in jobs.items() if name != "claims")


@pytest.mark.parametrize("path, job", [("worker.yml", "claims"), ("prove.yml", "settle"), ("attest.yml", "attest"), ("attest.yml", "refused")])
def test_the_install_is_tried_three_times_and_asks_the_index_again(path, job):
    steps = yaml.safe_load((ROOT / ".github" / "workflows" / path).read_text(encoding="utf-8"))["jobs"][job]["steps"]
    run = next(str(s["run"]) for s in steps if "--require-hashes" in str(s.get("run") or ""))
    assert 'for nap in 10 30 end; do' in run and 'refresh="--refresh"' in run and "uv pip install --no-config $refresh " in run
    assert '[ "$nap" != end ] || exit 1' in run                                     # the third failure ends the job



# ---- the `knos settle` job of prove.yml: the same wait, written into its install step (that job checks nothing out) ----
def _settle_install() -> str:
    steps = yaml.safe_load((ROOT / ".github" / "workflows" / "prove.yml").read_text(encoding="utf-8"))["jobs"]["settle"]["steps"]
    return next(str(s["run"]) for s in steps if "--require-hashes" in str(s.get("run") or ""))


def test_the_settle_job_writes_the_lock_waits_for_its_knos_file_then_installs_from_it():
    run = _settle_install().splitlines()
    write, wait, install = (next(i for i, ln in enumerate(run) if ln.startswith(x)) for x in ('cat > "$RUNNER_TEMP/knos.lock"', "python3 -I - ", "  uv pip install"))
    assert write < wait < install and run[write + 1:write + 3] == ["KNOS_LOCK", "LOCK"]
    assert run[wait] == """python3 -I - "$RUNNER_TEMP/knos.lock" 600 <<'WAIT'""" and run[install].endswith('--require-hashes --no-deps --no-build -r "$RUNNER_TEMP/knos.lock" && break')
    assert "${{" not in _settle_install() and "KEY" not in _settle_install()


@pytest.mark.parametrize("lock, answers, code, said", [
    (f"solders==0.29.0 --hash=sha256:{'a' * 64}\nknos=={VER} --hash=sha256:{H}\n", [index(), OSError("lag"), index((f"knos-{VER}-py3-none-any.whl", "d" * 64)),
     index((f"knos-{VER}-py3-none-any.whl", H))], 0, ["waiting 5 s", "waiting 10 s", "waiting 20 s", f"PyPI lists knos {VER} with the pinned hash (after 35 s)"]),
    (f"knos=={VER} --hash=sha256:{H}\n", [index(("knos-0.3.21-py3-none-any.whl", H))] * 20,
     f"PyPI did not list knos {VER} with the pinned hash within 600 s; last seen: no file of knos {VER} with the pinned hash", ["waiting 60 s"]),
    (f"solders==0.29.0 --hash=sha256:{'a' * 64}\n", [], 0, ["the lock pins no knos file: nothing to wait for"]),      # a rehearsal's lock
])
def test_the_settle_jobs_wait_runs_as_written(monkeypatch, capsys, tmp_path, lock, answers, code, said):
    import io
    import sys
    import textwrap
    import time
    import urllib.request
    text = textwrap.dedent(_settle_install().split("<<'WAIT'\n", 1)[1].split("\nWAIT\n", 1)[0])
    (tmp_path / "knos.lock").write_text(lock, encoding="utf-8")
    left, slept = list(answers), []

    def fake(req, timeout=0):
        assert req.full_url == "https://pypi.org/simple/knos/" and req.headers["Accept"] == PW.ACCEPT
        got = left.pop(0)
        if isinstance(got, Exception):
            raise got
        return io.BytesIO(json.dumps(got).encode("utf-8"))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    monkeypatch.setattr(time, "sleep", slept.append)
    monkeypatch.setattr(sys, "argv", ["-", str(tmp_path / "knos.lock"), "600"])
    try:
        exec(compile(text, "settle-wait", "exec"), {"__name__": "__main__"})      # noqa: S102 - the step's own text
        got = 0
    except SystemExit as stop:
        got = stop.code or 0
    out = capsys.readouterr().out
    assert got == code and all(x in out for x in said), (got, out)
    assert sum(slept) <= 600 and slept[:4] == [5, 10, 20, 40][:len(slept)]
