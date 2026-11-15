"""The checks Knos runs itself. Each returns a Result with the evidence it saw; none trusts the agent.

    tests     the repo's test command in a fresh virtual environment (uv when present, else venv + pip)
    ci        `gh run list` for HEAD: every workflow run for that commit completed, every job succeeded
    pypi      the package's version (pyproject) is live on pypi.org
    urls      each URL answers 200
    deleted   each path is gone from disk and from git
    author    HEAD's author is the one .knos/proof.toml names, and no AI attribution trailers
    custom    any [[check]] in .knos/proof.toml: a command that must exit 0
"""

from __future__ import annotations

import hashlib
import json
import os
import re
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


def _run(cmd, cwd: Path, timeout: float = 280, env: dict | None = None) -> tuple[int, str]:
    try:
        got = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                             shell=isinstance(cmd, str), env=env)
        return got.returncode, (got.stdout + got.stderr)[-2000:]
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except OSError as why:
        return 127, str(why)


def head(repo: Path) -> str:
    return _run(["git", "rev-parse", "HEAD"], repo, 10)[1].strip()


# ---- tests in a fresh venv ---------------------------------------------------------------------------------------

def tests(repo: Path, command: str | None = None, install: str | None = None) -> Result:
    """The tests, as a newcomer would run them: a fresh virtual environment, the project installed, the command run."""
    command = command or ("pytest -q" if (repo / "pyproject.toml").exists() or (repo / "setup.py").exists() else "")
    if not command:
        return Result("tests", False, "no test command: set tests = \"...\" in .knos/proof.toml")
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
        spec = install or (".[dev]" if "dev" in (repo / "pyproject.toml").read_text(encoding="utf-8", errors="ignore")
                           else ".")
        pip = [uv, "pip", "install", "-q", "--python", str(py), "-e", spec] if uv else [str(py), "-m", "pip", "install",
                                                                                      "-q", "-e", spec]
        code, out = _run(pip, repo, 280)
        if code:
            return Result("tests", False, f"the project does not install in a fresh venv: {out[-300:]}",
                          {"install": spec, "exit": code})
        env = {**os.environ, "VIRTUAL_ENV": str(venv), "PATH": str(py.parent) + os.pathsep + os.environ.get("PATH", "")}
        code, out = _run(command, repo, 280, env)
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
    code, out = _run(command, repo, 280)
    return Result(f"custom:{name}", code == 0, f"`{command}` exited {code}: {out.strip()[-160:]}",
                  {"command": command, "exit": code})
