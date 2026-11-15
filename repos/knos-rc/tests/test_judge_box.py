"""The host sandbox's limits (knos.judge.Box): a submission's command cannot fork-bomb the judge's machine, write outside
its own folder, write a file past the size limit or burn CPU past the CPU limit, and nothing it starts outlives its run.

The command line is checked as a list everywhere; the runs need the sandbox (Linux, setpriv, unshare, prlimit, root or
passwordless sudo) and are skipped where there is none. tests.yml's Linux shards and hermetic.yml have it."""

from __future__ import annotations

import os
import secrets
import sys
import tempfile
from pathlib import Path

import pytest

from knos import judge

needs_box = pytest.mark.skipif(not judge.sandbox_available(), reason="needs the sandbox (Linux, setpriv, unshare, prlimit, root or sudo)")
posix = pytest.mark.skipif(os.name == "nt", reason="the sandbox is a Linux one")


def _box(limits: judge.HostLimits = judge.HOST_LIMITS, sandboxed: bool = True) -> judge.Box:
    box = judge.Box(Path(tempfile.mkdtemp(prefix="knos-judge-")).resolve(), sandboxed, limits=limits)
    box.work.mkdir()
    box.open_up()
    return box


def _alive(token: str) -> int:
    """Processes on this machine whose command line holds `token`, once the kernel has finished tearing down the run's
    PID namespace (it kills them all; this waits at most five seconds for the last to go)."""
    import time
    for _ in range(50):
        n = 0
        for pid in os.listdir("/proc"):
            try:
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    n += token.encode() in f.read()
            except OSError:
                pass
        if not n:
            return 0
        time.sleep(0.1)
    return n


@posix
def test_the_sandboxed_command_line_is_limits_then_another_user_inside_namespaces(monkeypatch, tmp_path):
    # A Box makes its folders when it is made: the root is the test's own folder, never one at the top of the machine,
    # which only root may create (a runner is not root: run 37750601693, "Permission denied: '/t'").
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    root = tmp_path / "box"
    box = judge.Box(root, True, limits=judge.HostLimits(nproc=64, cpu=30, data=1 << 30, fsize=1 << 20))
    argv, env = box.wrap(["python3", "x.py"], net=False, seconds=90)
    assert env is None
    assert argv[:4] == ["timeout", "-s", "KILL", "90"]
    assert argv[4:11] == ["unshare", "--mount", "--pid", "--fork", "--kill-child", "--net", "--"]
    assert argv[11:13] == ["sh", "-c"] and argv[13] == judge._ISOLATE and argv[14:16] == ["sh", str(root)]
    at = argv.index("prlimit")
    assert argv[at:at + 6] == ["prlimit", "--nproc=64", "--cpu=30", f"--data={1 << 30}", f"--fsize={1 << 20}", "--"]
    assert argv[at + 6:at + 10] == ["setpriv", "--reuid=65534", "--regid=65534", "--clear-groups"]
    assert argv[-2:] == ["python3", "x.py"]
    online, _ = box.wrap(["true"], net=True)
    assert "--net" not in online and online[0] == "unshare"       # the dependency install: network, same walls
    for line in ("mount --bind", "remount,bind,ro", "tmpfs /dev/shm", "exit 125"):
        assert line in judge._ISOLATE
    box.sandboxed = False
    plain, env = box.wrap(["true"])
    assert plain == ["true"] and env is not None and not any(k.startswith("GITHUB_") for k in env)


@needs_box
def test_a_fork_bomb_meets_the_process_limit_and_nothing_it_started_outlives_the_run():
    token = "knosbomb" + secrets.token_hex(6)
    bomb = ("import os, sys, time\nn = 0\nwhile True:\n    try:\n        pid = os.fork()\n    except OSError:\n        break\n"
            "    if pid == 0:\n        time.sleep(600)\n        os._exit(0)\n    n += 1\nprint('forked', n, flush=True)\n")
    box = _box(judge.HostLimits(nproc=48))
    try:
        (box.work / "bomb.py").write_text(bomb, encoding="utf-8")
        code, out = box.run([sys.executable, "bomb.py", token], timeout=60)
        assert code == 0 and "forked" in out, out[-500:]
        assert int(out.split("forked")[1].split()[0]) < 48            # stopped by the limit, not by the machine
        assert _alive(token) == 0                                      # the sleeping children died with the run
        code, out = box.run(["sh", "-c", f": {token}; b(){{ b | b & }}; b; sleep 1; echo held"], timeout=60)
        assert "held" in out and _alive(token) == 0, out[-300:]        # the classic one, too
    finally:
        box.clean()


@needs_box
def test_a_write_outside_the_box_is_refused_and_inside_it_works(tmp_path):
    drop = tmp_path / "drop"
    drop.mkdir()
    drop.chmod(0o1777)                                                 # a folder any user may write, as /tmp is
    name = secrets.token_hex(6)
    probe = ("import os, sys\nfor d in sys.argv[1:]:\n    try:\n        open(os.path.join(d, 'f'), 'w').write('x')\n"
             "        print('wrote', d)\n    except OSError as why:\n        print('no', d, why.errno)\n")
    box = _box()
    try:
        (box.work / "probe.py").write_text(probe, encoding="utf-8")
        shm = f"/dev/shm/knos-{name}"
        code, out = box.run([sys.executable, "probe.py", str(drop), "/tmp", "/var/tmp", str(box.work), str(box.root / "tmp"),
                             str(box.home)], timeout=60)
        assert code == 0, out
        for d in (str(drop), "/tmp", "/var/tmp"):
            assert f"no {d} " in out, out
        for d in (str(box.work), str(box.root / "tmp"), str(box.home)):
            assert f"wrote {d}" in out, out
        assert not (drop / "f").exists()
        code, out = box.run(["sh", "-c", f"mkdir {shm} && echo private"], timeout=60)
        assert "private" in out and not Path(shm).exists()             # /dev/shm is a tmpfs of the run's own
    finally:
        box.clean()


@needs_box
def test_a_file_past_the_size_limit_and_cpu_past_the_cpu_limit_are_stopped():
    box = _box(judge.HostLimits(fsize=1 << 20, cpu=1))
    try:
        # the marker is printed in two parts: Python 3.13's traceback quotes the source line, which must not count as the output
        code, out = box.run([sys.executable, "-c", "open('big', 'wb').write(b'x' * (2 << 20)); print('wrote', 'it all')"], timeout=60)
        assert code != 0 and "wrote it all" not in out
        assert (box.work / "big").stat().st_size <= 1 << 20
        code, out = box.run([sys.executable, "-c", "while True: pass"], timeout=60)
        assert code != 0 and code != 124                               # killed by the CPU limit, well before the time limit
    finally:
        box.clean()


@needs_box
def test_the_time_limit_kills_the_whole_tree():
    token = "knoslate" + secrets.token_hex(6)
    box = _box()
    try:
        late = f"{sys.executable} -c 'import time; time.sleep(600)' {token}"
        code, out = box.run(["sh", "-c", f"{late} & {late} & wait"], timeout=2)
        assert code == 124 and _alive(token) == 0
    finally:
        box.clean()


@pytest.mark.skipif(os.name != "posix", reason="setrlimit is POSIX")
def test_without_a_sandbox_the_command_still_gets_the_cpu_and_file_size_limits():
    box = _box(judge.HostLimits(fsize=1 << 20), sandboxed=False)
    try:
        code, out = box.run([sys.executable, "-c", "import resource; print(resource.getrlimit(resource.RLIMIT_FSIZE)[0])"], timeout=60)
        assert code == 0 and out.split()[0] == str(1 << 20)
    finally:
        box.clean()


def test_what_each_platform_enforces_is_said():
    doc = (Path(__file__).resolve().parents[1] / "docs" / "reference" / "ATTESTOR.md").read_text(encoding="utf-8")
    for words in ("RLIMIT_NPROC", "macOS", "Windows", "read-only"):
        assert words in doc
