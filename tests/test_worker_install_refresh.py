"""The worker's install step asks PyPI's index again with --refresh on every retry (as the claims job does). In the 0.3.24
release run the `event` job asked five times without it and uv kept its first answer, "no version of knos==0.3.25",
until a person re-ran the job. The relay chain's install and the event job's are one step, letter for letter."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _install(job: str) -> str:
    steps = yaml.safe_load((ROOT / ".github" / "workflows" / "worker.yml").read_text(encoding="utf-8"))["jobs"][job]["steps"]
    [step] = [s for s in steps if "requirements/sign.txt" in str(s.get("run", "")) and "uv pip install" in str(s.get("run", ""))]
    return str(step["run"])


def test_the_event_jobs_install_is_the_chains_and_both_refresh_on_a_retry():
    event, chain = _install("event"), _install("relay")
    assert event == chain
    assert 'refresh=""' in event and "uv pip install --no-config $refresh " in event and 'refresh="--refresh"' in event
    assert event.index('refresh="--refresh"') > event.index("uv pip install") and event.count("uv pip install ") == 1


@pytest.mark.parametrize("job", ["event", "relay"])
def test_the_first_try_asks_plainly_and_every_retry_with_refresh(job, tmp_path):
    if os.name == "nt":
        pytest.skip("runs the step with stand-ins for uv and sleep on a POSIX shell")
    import _posix
    bash = _posix.bash()
    fake = tmp_path / "bin"
    fake.mkdir()
    # uv: `venv` does nothing; `pip install` writes its arguments, and fails with the index's lag until --refresh has been
    # asked twice (the index then lists the release)
    (fake / "uv").write_text('#!/bin/sh\n[ "$1" = venv ] && exit 0\necho "$*" >> "$LOG/tries"\n'
                             'n=$(grep -c -- "--refresh" "$LOG/tries")\n[ "$n" -ge 2 ] && exit 0\n'
                             'echo "  x No solution found when resolving dependencies: Because there is no version of $PIN and you require $PIN, we can conclude" >&2\nexit 1\n',
                             encoding="utf-8")
    (fake / "sleep").write_text('#!/bin/sh\necho "$1" >> "$LOG/naps"\n', encoding="utf-8")
    for tool in ("uv", "sleep"):
        (fake / tool).chmod(0o755)
    pin = "knos" + "==9.8.7"                                           # in two parts: this file is read for version pins too
    work = tmp_path / "run"
    (work / "requirements").mkdir(parents=True)
    (work / "requirements" / "sign.txt").write_text(f"{pin} --hash=sha256:" + "a" * 64 + "\n", encoding="utf-8")
    env = _posix.environ({**os.environ, "RUNNER_TEMP": _posix.path(work), "GITHUB_PATH": _posix.path(work / "path"), "LOG": _posix.path(work), "PIN": pin},
                         first=[fake])
    done = subprocess.run([bash, "--noprofile", "--norc", "-e", "-c", _install(job)], env=env, cwd=str(work), capture_output=True, text=True,
                          encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    tries = (work / "tries").read_text(encoding="utf-8").splitlines()
    assert len(tries) == 3 and "--refresh" not in tries[0] and all("--refresh" in t for t in tries[1:])
    assert (work / "naps").read_text(encoding="utf-8").split() == ["15", "30"] and (work / "path").exists()
    assert done.stdout.count("PyPI's index does not list knos 9.8.7 yet: asking again (--refresh) in") == 2
