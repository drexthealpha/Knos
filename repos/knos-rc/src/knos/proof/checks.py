"""The checks Knos runs itself. Each returns a Result with the evidence it saw; none trusts the agent.

    tests     the repo's test command in a fresh virtual environment (uv when present, else venv + pip)
    ci        `gh run list` for HEAD: every workflow run for that commit completed, every job succeeded
    pypi      the package's version (pyproject) is live on pypi.org
    urls      each URL answers 200
    deleted   each path is gone from disk and from git
    author    HEAD's author is the one .knos/proof.toml names, and no AI attribution trailers
    custom    any [[check]] in .knos/proof.toml: a command that must exit 0

A command (a [[check]]'s `run`, or `tests`) goes to the shell as written, with one exception: when its first word is
`python` or `python3`, that word is replaced by the full path of the interpreter Knos itself is running under (for
`tests` in a Python project: the fresh virtual environment's). The bare name means whatever PATH finds first: on
Windows that is the Microsoft Store alias, which runs nothing and exits 9009, and elsewhere it can be a system Python
without the project's packages. So `run = "python scripts/check.py"` means the same on every machine. Only the first
word is replaced; write the interpreter's path yourself to choose another one.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

AI_TRAILERS = re.compile(r"(co-authored-by:.*(claude|anthropic|openai|codex|copilot|devin|gpt|noreply@anthropic)|"
                         r"generated with \[?claude|🤖 generated)", re.I)


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    evidence: dict = field(default_factory=dict)

    def digest(self) -> str:
        return hashlib.sha256(json.dumps([self.name, self.ok, self.evidence], sort_keys=True,
                                         default=str).encode()).hexdigest()


_PYTHON_FIRST = re.compile(r"\s*python3?(?=\s|$)")   # the first word, exactly: not python3.12, pythonw or python-config


def with_python(command: str, exe: str | None = None) -> str:
    """`command` with a first word of `python` or `python3` replaced by an interpreter's full path, quoted for the
    shell that will run it: the interpreter Knos is running under, or `exe` (a fresh venv's). Any other command comes
    back unchanged, and so does every later word: a `python` after `&&` or in a pipe is the repository's own business."""
    exe = exe or sys.executable
    m = _PYTHON_FIRST.match(command)
    if not m or not exe:
        return command
    # cmd.exe keeps everything between double quotes (a Windows path cannot contain one); sh needs shlex's quoting
    return (f'"{exe}"' if os.name == "nt" else shlex.quote(exe)) + command[m.end():]


def _run(cmd, cwd: Path, timeout: float = 280, env: dict | None = None) -> tuple[int, str]:
    try:
        # errors="replace": a command's output in another encoding (a Windows code page, a binary dump) is still a
        # result to report, never a crash of the check that ran it
        got = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, errors="replace", timeout=timeout,
                             shell=isinstance(cmd, str), env=env)
        return got.returncode, (got.stdout + got.stderr)[-2000:]
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except OSError as why:
        return 127, str(why)


def head(repo: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], repo, 10)[1].strip()


# ---- tests in a fresh venv ---------------------------------------------------------------------------------------

def test_command(repo: Path, command: str | None = None) -> str:
    """The command that runs this repository's tests: proof.toml's `tests`, else what its language's own files say."""
    repo = Path(repo)
    if command:
        return command
    if (repo / "pyproject.toml").exists() or (repo / "setup.py").exists():
        return "pytest -q"
    try:
        if (json.loads((repo / "package.json").read_text(encoding="utf-8")).get("scripts") or {}).get("test"):
            return "npm test"
    except (OSError, ValueError):
        pass
    if (repo / "Cargo.toml").exists():
        return "cargo test"
    if (repo / "go.mod").exists():
        return "go test ./..."
    return ""


def tests(repo: Path, command: str | None = None, install: str | None = None) -> Result:
    """The tests, as a newcomer would run them. Python: a fresh virtual environment, the project installed, the
    command run. JavaScript, Rust and Go: the language's own test command, in the repository."""
    python = (repo / "pyproject.toml").exists() or (repo / "setup.py").exists()
    command = test_command(repo, command)
    if not command:
        return Result("tests", False, "no test command: set tests = \"...\" in .knos/proof.toml")
    if not python:
        code, out = _run(with_python(command), repo, 280)
        tail = out.strip().splitlines()[-1] if out.strip() else ""
        return Result("tests", code == 0, f"`{command}`: {tail}", {"command": command, "exit": code, "head": head(repo)})
    venv = Path(tempfile.mkdtemp(prefix="knos-proof-venv-"))
    try:
        uv = shutil.which("uv")
        py = venv / ("Scripts" if os.name == "nt" else "bin") / "python"
        if uv:
            code, out = _run([uv, "venv", "-q", str(venv)], repo, 120)
        else:
            code, out = _run([sys.executable, "-m", "venv", str(venv)], repo, 120)
        if code:
            return Result("tests", False, f"could not create a fresh venv: {out[-200:]}")
        toml = repo / "pyproject.toml"
        spec = install or (".[dev]" if toml.exists() and "dev" in toml.read_text(encoding="utf-8", errors="ignore")
                           else ".")
        pip = [uv, "pip", "install", "-q", "--python", str(py), "-e", spec] if uv else [str(py), "-m", "pip", "install",
                                                                                      "-q", "-e", spec]
        code, out = _run(pip, repo, 280)
        if code:
            return Result("tests", False, f"the project does not install in a fresh venv: {out[-300:]}",
                          {"install": spec, "exit": code})
        env = {**os.environ, "VIRTUAL_ENV": str(venv), "PATH": str(py.parent) + os.pathsep + os.environ.get("PATH", "")}
        code, out = _run(with_python(command, str(py)), repo, 280, env)   # `python -m pytest`: the fresh venv's python
        tail = out.strip().splitlines()[-1] if out.strip() else ""
        return Result("tests", code == 0, f"`{command}` in a fresh venv: {tail}", {"command": command, "exit": code,
                                                                                    "head": head(repo)})
    finally:
        shutil.rmtree(venv, ignore_errors=True)


# ---- CI: every job for HEAD ------------------------------------------------------------------------------------

def _json(out: str, start: str):
    """The first JSON value in a command's output: gh can print notices before or after it."""
    i = out.find(start)
    return json.JSONDecoder().raw_decode(out[i:])[0] if i >= 0 else None


def ci(repo: Path, sha: str | None = None, runner=None) -> Result:
    """Every GitHub Actions run for this commit completed and every job in it succeeded (`gh run list` + `gh run view`)."""
    sha = sha or head(repo)
    run = runner or (lambda args: _run(["gh", *args], repo, 60))
    code, out = run(["run", "list", "--commit", sha, "--json", "databaseId,status,conclusion,workflowName"])
    if code:
        return Result("ci", False, f"gh could not list runs for {sha[:8]}: {out[-200:]}", {"sha": sha})
    try:
        runs = _json(out, "[") or []
    except ValueError:
        runs = []
    if not runs:
        return Result("ci", False, f"no CI run for {sha[:8]} yet: push it, then wait for CI", {"sha": sha})
    bad, pending = [], []
    for r in runs:
        if r.get("status") != "completed":
            pending.append(r.get("workflowName"))
            continue
        code, view = run(["run", "view", str(r["databaseId"]), "--json", "jobs"])
        jobs = (_json(view, "{") or {}).get("jobs", []) if code == 0 else []
        for j in jobs:
            if j.get("conclusion") not in ("success", "skipped", "neutral"):
                bad.append(f"{r.get('workflowName')}/{j.get('name')}: {j.get('conclusion')}")
        if not jobs and r.get("conclusion") != "success":
            bad.append(f"{r.get('workflowName')}: {r.get('conclusion')}")
    ev = {"sha": sha, "runs": len(runs), "failed": bad, "pending": pending}
    if pending:
        return Result("ci", False, f"CI still running for {sha[:8]}: {', '.join(pending)}", ev)
    if bad:
        return Result("ci", False, f"CI failed for {sha[:8]}: {'; '.join(bad[:4])}", ev)
    return Result("ci", True, f"every CI job passed for {sha[:8]} ({len(runs)} run(s))", ev)


# ---- PyPI ------------------------------------------------------------------------------------------------------

def _project(repo: Path) -> tuple[str | None, str | None]:
    p = repo / "pyproject.toml"
    if not p.exists():
        return None, None
    text = p.read_text(encoding="utf-8", errors="ignore")
    name = re.search(r'^name\s*=\s*"([^"]+)"', text, re.M)
    ver = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return (name.group(1) if name else None), (ver.group(1) if ver else None)


def _get(url: str, timeout: float = 20) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "knos-proof"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - URLs the agent itself named
            return r.status, r.read(200_000)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (OSError, ValueError) as why:
        return 0, str(why).encode()


def pypi(repo: Path, version: str | None = None, getter=_get) -> Result:
    name, ver = _project(repo)
    version = version or ver
    if not name or not version:
        return Result("pypi", False, "no package name/version in pyproject.toml")
    code, _ = getter(f"https://pypi.org/pypi/{name}/{version}/json")
    return Result("pypi", code == 200, f"{name} {version} {'is' if code == 200 else 'is NOT'} live on PyPI (HTTP {code})",
                  {"package": name, "version": version, "http": code})


def urls(found: list[str], getter=_get) -> Result:
    seen = {u: getter(u)[0] for u in found}
    bad = [f"{u} -> {c}" for u, c in seen.items() if c != 200]
    return Result("urls", not bad, "every URL answers 200" if not bad else "not live: " + "; ".join(bad[:4]),
                  {"urls": seen})


def deleted(repo: Path, paths: list[str]) -> Result:
    still = []
    for p in paths:
        tracked = _run(["git", "ls-files", "--error-unmatch", p], repo, 10)[0] == 0
        if (repo / p).exists() or tracked:
            still.append(p)
    return Result("deleted", not still, "every deleted path is gone" if not still else "still there: " + ", ".join(still),
                  {"paths": paths, "still": still})


def author(repo: Path, expected: str | None) -> Result:
    code, out = _run(["git", "log", "-1", "--format=%an <%ae>%n%B"], repo, 10)
    if code:
        return Result("author", False, "not a git repository")
    who, _, body = out.partition("\n")
    trailers = AI_TRAILERS.findall(body)
    ok_who = expected is None or who.strip() == expected.strip()
    ok = ok_who and not trailers
    why = []
    if not ok_who:
        why.append(f"author is {who.strip()}, not {expected}")
    if trailers:
        why.append("AI attribution in the commit message")
    return Result("author", ok, "; ".join(why) or f"HEAD by {who.strip()}, no AI trailers",
                  {"author": who.strip(), "expected": expected, "ai_trailers": bool(trailers)})


def custom(repo: Path, name: str, command: str) -> Result:
    """A [[check]]: its `run` command must exit 0. The evidence keeps the command as the repository wrote it (the same
    on every machine); what ran is that with a leading `python` made this interpreter (with_python)."""
    code, out = _run(with_python(command), repo, 280)
    return Result(f"custom:{name}", code == 0, f"`{command}` exited {code}: {out.strip()[-160:]}",
                  {"command": command, "exit": code})
