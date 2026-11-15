"""$KNOS_RUN on Windows: what a black-box check runs the pull request's code through. It must run the command the check
names, with the arguments the check gave, in the tree, as `exec "$@"` does on Linux, and end everything it started at the
check's time limit. Each test runs the runner the judge makes, the way a check runs it."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from knos import judge

pytestmark = pytest.mark.skipif(os.name != "nt", reason="$KNOS_RUN on Windows")
WHOAMI = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "whoami.exe"


@pytest.fixture(params=["launcher", "cmd"])
def make(request, tmp_path, monkeypatch):
    """The runner as the judge makes it: knos-run.exe, and knos-run.cmd for a Python that ships no venv launcher."""
    if request.param == "cmd":
        monkeypatch.setattr(judge, "_venv_launcher", lambda: None, raising=False)

    def made(work: Path | None = None) -> Path:
        work = work or tmp_path / "tree"
        work.mkdir(exist_ok=True)
        (tmp_path / "knos-run").mkdir(exist_ok=True)
        return judge._windows_runner(tmp_path / "knos-run", work)
    made.mode = request.param
    return made


def _alive(pid: int) -> bool:
    k = ctypes.windll.kernel32
    handle = k.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    try:
        return bool(k.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259     # STILL_ACTIVE
    finally:
        k.CloseHandle(handle)


def test_python3_is_the_judges_interpreter_even_when_the_store_stub_is_first_on_path(make, tmp_path):
    runner = make()
    stub = tmp_path / "WindowsApps"           # what App Execution Aliases put on PATH: a python3.exe that runs nothing
    stub.mkdir()
    shutil.copyfile(WHOAMI, stub / "python3.exe")
    shutil.copyfile(WHOAMI, stub / "python.exe")
    env = dict(os.environ, PATH=str(stub) + os.pathsep + os.environ.get("PATH", ""))
    for name in ("python3", "python"):
        got = subprocess.run([str(runner), name, "-c", "import sys; print(sys.version_info[:2])"], capture_output=True,
                             env=env, timeout=60)
        assert got.returncode == 0 and got.stdout.decode().strip() == str(sys.version_info[:2]), (name, got)


def test_the_arguments_reach_the_command_as_the_check_gave_them(make):
    runner = make()
    if make.mode == "cmd":
        pytest.skip("cmd.exe reads a .cmd's arguments itself: only the launcher passes them through unchanged")
    assert runner.suffix == ".exe"
    args = ["a&b", "x|y", "<in>", "o>ut", "^c", "%PATH%", "!x!", 'q"uote', "sp ace", "", "é"]
    got = subprocess.run([str(runner), sys.executable, "-c", "import json, sys; print(json.dumps(sys.argv[1:]))", *args],
                         capture_output=True, timeout=60)
    assert got.returncode == 0 and json.loads(got.stdout) == args, got


def test_the_command_runs_in_the_tree_with_its_stdin_and_exit_status(make, tmp_path):
    runner = make()
    (tmp_path / "tree" / "solve.py").write_text("import os, sys\nprint(os.getcwd(), sys.stdin.read().upper())\n"
                                                "sys.exit(3)\n", encoding="utf-8")
    got = subprocess.run([str(runner), "python3", "solve.py"], input=b"abc", capture_output=True, timeout=60)
    assert got.returncode == 3 and got.stdout.decode().split() == [str(tmp_path / "tree"), "ABC"], got
    missing = subprocess.run([str(runner), "knos-no-such-command"], capture_output=True, timeout=60)
    assert missing.returncode == 127 and b"not found" in missing.stderr


def test_a_bare_name_is_found_on_path_never_in_the_tree(make, tmp_path):
    runner = make()
    tools = tmp_path / "bin"
    tools.mkdir()
    shutil.copyfile(WHOAMI.with_name("hostname.exe"), tools / "knostool.exe")     # the tool on PATH
    shutil.copyfile(WHOAMI, tmp_path / "tree" / "knostool.exe")                   # the pull request's own, by that name
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ.get("PATH", ""))
    env.pop("NoDefaultCurrentDirectoryInExePath", None)     # unset, as it is by default: Windows then looks in the cwd first
    real = subprocess.run([str(tools / "knostool.exe")], capture_output=True, timeout=60).stdout
    got = subprocess.run([str(runner), "knostool"], capture_output=True, env=env, timeout=60)
    assert got.returncode == 0 and got.stdout.split() == real.split(), got


def test_the_whole_tree_ends_at_the_checks_time_limit(make, tmp_path):
    runner = make()
    pid = tmp_path / "grandchild.pid"
    code = ("import subprocess, sys, time; "     # one line: a .cmd's arguments end at a line break
            "kid = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], stdout=sys.stdout, stderr=sys.stderr); "
            f"open({str(pid)!r}, 'w').write(str(kid.pid)); "
            "time.sleep(60)")
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run([str(runner), sys.executable, "-c", code], capture_output=True, timeout=3)
    assert time.monotonic() - start < 20      # the grandchild holds the pipe: it must end with the rest, not after 60 s
    deadline = time.monotonic() + 10
    while _alive(int(pid.read_text())) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not _alive(int(pid.read_text())), "a process the command started outlived the check"


def test_an_interpreter_path_outside_ascii_still_runs(make, tmp_path, monkeypatch):
    import _winapi
    home = Path(getattr(sys, "_base_executable", "") or sys.executable).parent
    link = tmp_path / "Pythoné"                # the folder of a per-user install for a user named José
    _winapi.CreateJunction(str(home), str(link))
    try:
        monkeypatch.setattr(sys, "_base_executable", str(link / Path(sys._base_executable).name))
        runner = make()
        got = subprocess.run([str(runner), "python3", "-c", "print(6 * 7)"], capture_output=True, timeout=60)
        assert got.returncode == 0 and got.stdout.strip() == b"42", got
    finally:
        os.rmdir(link)                          # the junction only, never the interpreter it points at
