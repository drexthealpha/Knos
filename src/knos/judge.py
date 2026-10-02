"""The judge: prove.yml's `check` job. It decides whether a pull request may be paid, and the pull request cannot
weaken what it is judged by.

Two verdicts:

    gate(...)    every bounty pull request, before merge, running NO pull request code: the repository's own rules
                 (CONTRIBUTING.md, parsed once and kept in Sibyl), what this repository's history made required
                 (tampering caught before, also Sibyl), and the pull request's own words: a description saying "tests
                 pass" or "CI is green" is checked against the commit's finished checks on GitHub.
    judge(...)   tests mode (.knos/acceptance/<issue>/ exists on the base): the funder's acceptance checks, run in a
                 sandbox, must fail on the base and pass on the pull request.

What judge() enforces:

    protected     the pull request may not touch .knos/**, .github/**, the test directories or the files that decide
                  how tests run (proof.toml `protected = [...]` replaces the list).
    overlay       the run happens on the pull request's source with the base's tests and test configuration copied
                  over it.
    sandbox       every command that runs pull request code (its dependency install, its tests) runs as another user
                  (uid 65534), with an empty environment, and the tests run with no network. So that code cannot
                  write the judge's files, its memory, the job's outputs, or call out. `--sandbox require` (what
                  prove.yml passes) refuses to judge without it.
    sentinel      a random-named passing test and a random-named failing canary are added; the report must show the
                  sentinel passed and the canary failed, or the runner was faked or patched to pass everything.
    fail-to-pass  every acceptance check passes on the pull request and at least one fails on the base; every other
                  test that passed on the base still passes; the pull request collects no fewer tests than the base.

Languages (picked from the acceptance bundle's files, or `runner = "..."` in .knos/proof.toml):

    python   pytest, JUnit report                      acceptance: .knos/acceptance/<issue>/test_*.py
    node     `node --test`, JUnit report               acceptance: *.test.js / .mjs / .cjs / .ts
    go       `go test -json`                           acceptance: *_test.go (one package)
    rust     `cargo test`                              acceptance: *.rs, built as integration tests
    command  any language or framework                 acceptance: a `check` script (or `[judge] run = "..."`);
                                                       exit 0 means done. No sentinel in this mode.
    blackbox any language, and forgery-proof           acceptance: a `blackbox` script that runs as the judge and
                                                       reaches the pull request's code only through "$KNOS_RUN ..."

What is and is not stopped (docs/SECURITY.md says the same): in the first five runners the code under test shares a
process with the test runner, so a pull request written to forge the runner's report from inside is not stopped by
the report alone. The blackbox runner closes that: the check never loads the pull request's code, so nothing that
code does can change the verdict except producing the right output. An implementation that special-cases fixed
example inputs passes any check made of fixed examples; a blackbox check with generated inputs does not have that
weakness either. For everything else there is the review window, in which the funder can veto a tests-mode payment,
and the default mode, which pays on a maintainer's merge instead.
"""

from __future__ import annotations

import configparser
import fnmatch
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

SANDBOX_UID = 65534
_SKIP = {".git", "__pycache__", ".pytest_cache", "node_modules", "target"}
_LEAK = ("GITHUB_", "ACTIONS_", "RUNNER_", "PYTEST_", "INPUT_", "KNOS_", "GH_")


def checks_hash(folder: Path) -> str:
    """sha256 over the acceptance bundle: sorted relative paths, each "path\\0sha256(content)\\n". knos-pay fixes it
    when the bounty is funded; fund.yml computes the same."""
    folder = Path(folder)
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else []
    if not files:
        raise ValueError(f"no acceptance checks in {folder}")
    lines = "".join(f"{f}\0{hashlib.sha256((folder / f).read_bytes()).hexdigest()}\n" for f in files)
    return hashlib.sha256(lines.encode()).hexdigest()


# ---- the gate: rules, history and the pull request's own claims. Runs no pull request code. ------------------------

def _rule_violations(base: Path, diff_text: str | None, store, repo, agent):
    from .proof import history
    required = sorted(history.tamper_checks_required(store, repo, agent))
    contributing = [r for r in history.repo_rules(store, base) if r.get("origin") == "contributing"]
    violations = history.lint_pr(store, base, diff_text, (), {r["id"] for r in contributing}) \
        if diff_text is not None and contributing else []
    if not violations and diff_text is not None:   # what history made required, in CONTRIBUTING or not
        violations = history.lint_learned(required, diff_text)
    return required, contributing, violations


_KNOS_JOBS = re.compile(r"^(?:prove|fund)(?:-relay|-refused)? / |^knos| / claims$")


def _ours(run: dict) -> bool:
    """A check run that is Knos's own (this workflow run's jobs, and the Knos jobs of earlier runs on the same commit:
    the check, the proof, the relay and its verdict): never evidence about the pull request."""
    mine = os.environ.get("GITHUB_RUN_ID", "")
    return bool(mine and f"/runs/{mine}/" in str(run.get("details_url", ""))) or bool(_KNOS_JOBS.search(str(run.get("name", ""))))


def github(path: str):
    """GET api.github.com/<path> (GH_TOKEN or GITHUB_TOKEN is sent when set). Raises OSError when GitHub says no."""
    import urllib.request
    req = urllib.request.Request(f"https://api.github.com/{path}",
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "knos"})
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - api.github.com
        return json.loads(resp.read())


# How the agents that open pull requests under a bot account name the person who ran them. Each is a whole line of
# the description: Devin ends it with "Requested by: @login"; Jules with "PR created automatically by Jules for task
# N started by @login"; anyone can write "Knos-Pay-To: @login".
_LOGIN = r"@([A-Za-z0-9][A-Za-z0-9-]{0,38})"
_PAY_TO = (re.compile(r"knos-pay-to:[ \t]{0,8}" + _LOGIN + r"\.?", re.I),
           re.compile(r"requested by:?[ \t]{0,8}" + _LOGIN + r"\.?", re.I),
           re.compile(r"pr created automatically by jules\b[^@]{0,120}\bstarted by[ \t]{0,8}" + _LOGIN + r"\.?", re.I))
# Copilot and Cursor credit that person in the commit: a GitHub no-reply address carries the numeric user id.
_CO_AUTHOR = re.compile(r"co-authored-by:[^<]{0,120}<(\d{1,12})\+[A-Za-z0-9-]{1,39}@users\.noreply\.github\.com>", re.I)


def _named(body: str) -> set[str]:
    """The logins a description's own lines name as the person to pay. Quoted lines and fenced code are not the
    description's own words (an agent may have copied them from an issue), so they are skipped."""
    out, fenced = set(), False
    for line in (body or "").splitlines()[-400:]:
        line = line.strip()
        if line.startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced or line.startswith(">") or len(line) > 300:
            continue
        for pat in _PAY_TO:
            m = pat.fullmatch(line)
            if m:
                out.add(m.group(1).lower())
    return out


def payee(pull: dict, head_message: str = "", get=None) -> dict:
    """Who a pull request's bounty is paid to: {"id", "login", "why"}, or {"id": None, "why"} when nobody can be named.

    A person's pull request pays that person, whatever its description says. An agent that opens pull requests under
    a bot account (Copilot, Devin, Jules, Cursor) has no account to be paid into, so the money goes to the person who
    ran it, found the way that agent itself names them: the pull request's assignee; else a line of its description;
    else the co-author of its head commit. A description that names two different people, or a name GitHub does not
    confirm as a person, pays nobody: better no payment than one to whoever got a line into the text.
    `pull` is the pull request as the event or the API gives it; `get(path)` reads api.github.com."""
    get = get or github
    user = pull.get("user") or {}
    if user.get("type") != "Bot":
        return {"id": user.get("id"), "login": user.get("login"), "why": "the pull request's author"}
    bot = user.get("login")
    nobody = lambda why: {"id": None, "login": None, "why": why}  # noqa: E731
    fix = "assign the pull request to the person who ran it, or keep one line `Knos-Pay-To: @login` in its description"
    for a in pull.get("assignees") or []:
        if a.get("type", "User") == "User" and a.get("id"):
            return {"id": a["id"], "login": a.get("login"), "why": f"assignee of {bot}'s pull request"}

    def person(path: str) -> dict | None:
        try:
            who = get(path)
        except Exception:  # noqa: BLE001 - GitHub did not answer: nobody is confirmed
            return None
        return who if isinstance(who, dict) and who.get("type") == "User" and who.get("id") else None

    named = _named(pull.get("body") or "")
    if len(named) > 1:
        return nobody(f"{bot}'s description names more than one person to pay ({', '.join('@' + n for n in sorted(named))}): {fix}")
    if named:
        login = next(iter(named))
        who = person(f"users/{login}")
        if not who:
            return nobody(f"{bot}'s description names @{login}, which GitHub did not confirm as a person: {fix}")
        return {"id": who["id"], "login": who.get("login"), "why": f"named in the description of {bot}'s pull request"}
    ids = {int(m.group(1)) for line in (head_message or "").splitlines()[-200:] if len(line) <= 300
           for m in [_CO_AUTHOR.fullmatch(line.strip())] if m}
    if len(ids) == 1:
        uid = next(iter(ids))
        who = person(f"user/{uid}")
        if who and who["id"] == uid:
            return {"id": uid, "login": who.get("login"), "why": f"co-author of {bot}'s head commit"}
    return nobody(f"{bot} is a bot and nothing names the one person who ran it: {fix}")


def assignment_check(issue: dict | None, pull: dict, paid: dict) -> list[str]:
    """An issue someone is assigned to is theirs: a bounty on it is paid only for a pull request by an assignee (or by
    the agent an assignee ran). An unassigned issue is open to anyone. `issue` is the issue as the API gives it."""
    assigned = [a for a in (issue or {}).get("assignees") or [] if a.get("id")]
    if not assigned:
        return []
    ids = {a["id"] for a in assigned}
    if (pull.get("user") or {}).get("id") in ids or paid.get("id") in ids:
        return []
    names = ", ".join("@" + str(a.get("login")) for a in assigned[:4])
    return [f"assigned: issue #{issue.get('number')} is assigned to {names}; only an assignee's pull request is paid for it"]


def claim_check(body: str, check_runs: list[dict] | None, strict: bool = False) -> list[str]:
    """What the pull request's description claims against GitHub's record of its head commit. `check_runs` is the
    commit's check runs (GET /repos/{repo}/commits/{sha}/check-runs). A claim of passing tests or green CI is refused
    when a finished check failed. Before a merge, unfinished or unreadable checks are not held against it. `strict`
    (the merged commit, where money moves): a claim that cannot be checked is refused too, until it can be."""
    from .proof import claims
    kinds = claims.read(body or "").kinds & {"tests", "ci"}
    if not kinds:
        return []
    said = " and ".join(sorted({"tests": "tests pass", "ci": "CI is green"}[k] for k in kinds))
    if check_runs is None:
        return [f"claim: the description says {said}, and GitHub's record of the head commit could not be read; "
                "run this job again"] if strict else []
    others = [r for r in check_runs if not _ours(r)]
    bad = sorted({r.get("name", "?") for r in others
                  if r.get("status") == "completed" and r.get("conclusion") in ("failure", "timed_out", "cancelled",
                                                                                   "startup_failure", "action_required")})
    if bad:
        return [f"claim: the description says {said}, but these checks failed at the head commit: {', '.join(bad[:6])}"]
    running = sorted({r.get("name", "?") for r in others if r.get("status") != "completed"})
    if strict and running:
        return [f"claim: the description says {said}, and these checks have not finished at the head commit: "
                f"{', '.join(running[:6])}; run this job again when they have"]
    return []


def check_runs(repo: str, sha: str, wait: float = 0, body: str = "", get=None, sleep=None) -> list[dict] | None:
    """The head commit's check runs from GitHub (public for a public repository; GH_TOKEN or GITHUB_TOKEN is sent
    when set). When the description makes a claim, waits up to `wait` seconds for the other checks to finish, so a
    claim made before CI ran is still checked. None when GitHub could not be read: then nothing is held against it."""
    import time
    from .proof import claims

    def fetch(url: str):
        return github(url.split("api.github.com/", 1)[1])

    get, sleep = get or fetch, sleep or time.sleep
    claims_something = bool(claims.read(body or "").kinds & {"tests", "ci"})
    end = time.monotonic() + (wait if claims_something else 0)
    while True:
        runs = []
        try:
            for page in range(1, 11):       # a commit can have more than 100 check runs
                got = get(f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs?per_page=100&page={page}")
                batch = got.get("check_runs", []) if isinstance(got, dict) else []
                runs += batch
                if len(batch) < 100:
                    break
        except Exception:  # noqa: BLE001 - an unreadable API is not the pull request's fault
            return None
        others = [r for r in runs if not _ours(r)]
        if all(r.get("status") == "completed" for r in others) or time.monotonic() >= end:
            return runs
        sleep(15)


def gate(base_dir, diff_text: str | None, store, repo: str | None = None, agent: str | None = None,
         body: str = "", check_runs: list[dict] | None = None, issue: str = "", pull: dict | None = None,
         issue_data: dict | None = None, paid: dict | None = None, strict: bool = False) -> dict:
    """The verdict that needs no pull request code. {"passed", "checks_hash" (""), "reasons", "evidence"}. A rule
    violation is learned: that check is then required for every later pull request to this repo or by this agent.
    With `pull` (the pull request) and `paid` (payee(pull)), a bounty's pull request must also name someone to pay,
    and respect the issue's assignment (`issue_data`)."""
    from .proof import history
    base = Path(base_dir)
    required, contributing, violations = _rule_violations(base, diff_text, store, repo, agent)
    for kind in sorted({x.rule["kind"] for x in violations}):
        first = next(x for x in violations if x.rule["kind"] == kind)
        history.learn_tamper(store, repo, agent, f"rule:{kind}", str(first))
    reasons = [f"repo rule: {x}" for x in violations]
    false_claims = claim_check(body, check_runs, strict)
    if false_claims and "failed at the head commit" in false_claims[0]:    # a claim that could not be checked is not a lie
        history.learn_tamper(store, repo, agent, "false-claim", false_claims[0])
    reasons += false_claims
    who = []
    if pull is not None and paid is not None:
        if not paid.get("id"):
            who.append(f"payee: {paid['why']}")
        who += assignment_check(issue_data, pull, paid)
    reasons += who
    ev = {"issue": str(issue), "mode": "merge", **({"payee": paid} if paid is not None else {}), "repo_rules": [str(x) for x in violations],
          "rules_known": len(contributing), "claims": false_claims,
          "checks_seen": None if check_runs is None else len(check_runs), "required_by_history": required,
          "learned": sorted(history.tamper_checks_required(store, repo, agent))}
    return {"passed": not reasons, "checks_hash": "", "reasons": reasons, "evidence": ev}


def judge_with_rules(base_dir, pr_dir, cfg: dict, changed: list[str] | None, diff_text: str | None, store,
                     repo: str | None = None, agent: str | None = None, body: str = "",
                     check_runs: list[dict] | None = None, setup: str | None = None, sandbox: str = "auto",
                     pull: dict | None = None, issue_data: dict | None = None, paid: dict | None = None) -> dict:
    """gate() first; only a pull request that clears it has its code run by judge(). A protected-path refusal is
    learned the same way a rule violation is."""
    from .proof import history
    base = Path(base_dir)
    g = gate(base, diff_text, store, repo, agent, body, check_runs, str(cfg.get("issue", "")), pull, issue_data, paid)
    if not g["passed"]:
        try:
            g["checks_hash"] = checks_hash(base / ".knos" / "acceptance" / str(cfg.get("issue", "")))
        except ValueError:
            pass
        g["evidence"]["mode"] = "tests"
        return g
    v = judge(base_dir, pr_dir, cfg, changed, setup=setup, sandbox=sandbox)
    bad = [r for r in v["reasons"] if r.startswith("touches protected path")]
    if bad:
        history.learn_tamper(store, repo, agent, "protected-path", bad[0])
    v["evidence"]["mode"] = "tests"
    if paid is not None:
        v["evidence"]["payee"] = paid
    if g["evidence"]["rules_known"]:
        v["evidence"]["repo_rules"] = []
    v["evidence"]["required_by_history"] = g["evidence"]["required_by_history"]
    v["evidence"]["learned"] = sorted(history.tamper_checks_required(store, repo, agent))
    return v


# ---- what a pull request may not touch, and the overlay ------------------------------------------------------------

RUNNERS = ("python", "node", "go", "rust", "ruby", "command", "blackbox")
TEST_DIRS = {"python": ("tests", "test"), "node": ("test", "tests", "__tests__"), "go": (), "rust": ("tests",),
             "ruby": ("test", "spec"), "command": ("tests", "test"), "blackbox": ("tests", "test")}
CONFIG_FILES = ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml")
_NODE_TEST = re.compile(r"(\.|-|_)(test|spec)\.[cm]?[jt]s$|(^|/)test-[^/]*\.[cm]?[jt]s$|(^|/)test\.[cm]?[jt]s$")
_NODE_SRC = re.compile(r"\.[cm]?[jt]s$")
_RUBY_TEST = re.compile(r"(^|/)test_[^/]*\.rb$|_test\.rb$")


def _files(root: Path) -> dict[str, str]:
    out = {}
    for p in Path(root).rglob("*"):
        rel = p.relative_to(root)
        if p.is_file() and not _SKIP.intersection(rel.parts):
            out[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def changed_files(base: Path, pr: Path) -> list[str]:
    a, b = _files(base), _files(pr)
    return sorted(f for f in set(a) | set(b) if a.get(f) != b.get(f))


def runner_of(base: Path, cfg: dict) -> str:
    """The language the acceptance bundle is written in."""
    named = cfg.get("runner") or (cfg.get("judge") or {}).get("runner")
    if named:
        if named not in RUNNERS:
            raise ValueError(f"runner {named!r} is not one of {', '.join(RUNNERS)}")
        return named
    if (cfg.get("judge") or {}).get("run"):
        return "command"
    bundle = Path(base) / ".knos" / "acceptance" / str(cfg.get("issue", ""))
    names = [p.name for p in bundle.rglob("*") if p.is_file()] if bundle.is_dir() else []
    if any(n in ("blackbox", "blackbox.sh", "blackbox.py") for n in names):
        return "blackbox"
    if any(n in ("check", "check.sh") for n in names):
        return "command"
    for ext, runner in ((".py", "python"), ("_test.go", "go"), (".rs", "rust")):
        if any(n.endswith(ext) for n in names):
            return runner
    if any(_NODE_SRC.search(n) for n in names):
        return "node"
    if (Path(base) / "Gemfile").is_file() or any(Path(base).glob("*.gemspec")):
        return "ruby"
    return "python"


def protected_patterns(cfg: dict, runner: str = "python") -> list[str]:
    if isinstance(cfg.get("protected"), list):
        return [str(x) for x in cfg["protected"]]
    dirs = cfg.get("test_dirs", TEST_DIRS[runner])
    pats = [".knos/**", ".github/**", *(f"{d.strip('/')}/**" for d in dirs)]
    if runner in ("python", "command", "blackbox"):
        pats += ["conftest.py", "**/conftest.py", "pytest.ini", "tox.ini"]
    if runner == "node":
        pats += ["**/*.test.*", "**/*.spec.*", ".npmrc"]
    if runner == "go":
        pats += ["**/*_test.go"]
    if runner == "rust":
        pats += [".cargo/**"]
    if runner == "ruby":
        pats += ["Rakefile", ".rspec", "test/test_helper.rb", "spec/spec_helper.rb"]
    return pats


def is_protected(path: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if pat.endswith("/**") and (path + "/").startswith(pat[:-2]):
            return True
        if fnmatch.fnmatchcase(path, pat) or (pat.startswith("**/") and fnmatch.fnmatchcase(path, pat[3:])):
            return True
    return False


def _pytest_section(root: Path, name: str):
    p = Path(root) / name
    if not p.is_file():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    if name == "pyproject.toml":
        try:
            return tomllib.loads(text).get("tool", {}).get("pytest")
        except ValueError:
            return "unreadable"
    cp = configparser.ConfigParser(interpolation=None)
    try:
        cp.read_string(text)
    except configparser.Error:
        return "unreadable"
    return {k: dict(cp[k]) for k in cp.sections() if k in ("tool:pytest", "pytest")}


def _copy_matching(base: Path, work: Path, match) -> None:
    """Make `work`'s files that `match` exactly the base's: the pull request's are removed, the base's copied in."""
    for p in list(work.rglob("*")):
        rel = p.relative_to(work)
        if p.is_file() and not _SKIP.intersection(rel.parts) and match(rel.as_posix()):
            p.unlink()
    for p in base.rglob("*"):
        rel = p.relative_to(base)
        if p.is_file() and not _SKIP.intersection(rel.parts) and match(rel.as_posix()):
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, work / rel)


def overlay(base: Path, pr: Path, work: Path, test_dirs, runner: str = "python") -> None:
    """Copy the pull request's tree to `work`, then replace everything that decides how tests run with the base's."""
    shutil.copytree(pr, work, ignore=shutil.ignore_patterns(*_SKIP), symlinks=True)
    for d in [*test_dirs, ".github", ".knos", *((".cargo",) if runner == "rust" else ())]:
        shutil.rmtree(work / d, ignore_errors=True)
        if (base / d).is_dir():
            shutil.copytree(base / d, work / d, ignore=shutil.ignore_patterns(*_SKIP), symlinks=True)
    if runner in ("python", "command", "blackbox"):
        _copy_matching(base, work, lambda rel: rel.rsplit("/", 1)[-1] == "conftest.py")
        for name in CONFIG_FILES:
            (work / name).unlink(missing_ok=True)
            if (base / name).is_file():
                shutil.copyfile(base / name, work / name)
    elif runner == "node":
        _copy_matching(base, work, lambda rel: bool(re.search(r"\.(test|spec)\.[^/]+$", rel)) or rel == ".npmrc")
    elif runner == "go":
        _copy_matching(base, work, lambda rel: rel.endswith("_test.go"))
    elif runner == "ruby":
        _copy_matching(base, work, lambda rel: rel in ("Rakefile", ".rspec"))


# ---- the sandbox: where pull request code runs ---------------------------------------------------------------------

def sandbox_available() -> bool:
    if not sys.platform.startswith("linux") or not shutil.which("setpriv") or not shutil.which("unshare"):
        return False
    if os.geteuid() == 0:
        return True
    try:
        return subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _reachable(path: Path) -> None:
    """Let the sandbox user traverse (not list) the directories above a tool this user owns, e.g. ~/.cargo/bin or a
    virtualenv's interpreter: both the path as given and what it links to."""
    path = Path(os.path.abspath(path))
    for d in {*path.parents, *path.resolve().parents}:
        try:
            st = d.stat()
            if st.st_uid == os.geteuid() and not st.st_mode & 0o001:
                d.chmod(st.st_mode | 0o001)
        except OSError:
            pass


def _sandbox_cannot_run(exe: str) -> str | None:
    """Why the sandbox user cannot start `exe` (None when it can). An interpreter under a directory other users may
    not enter would otherwise show up only as a test run that wrote no report."""
    _reachable(Path(exe))
    argv = ([] if os.geteuid() == 0 else ["sudo", "-n"]) + ["setpriv", f"--reuid={SANDBOX_UID}", f"--regid={SANDBOX_UID}",
                                                            "--clear-groups", "--", exe, "-c", "pass"]
    try:
        got = subprocess.run(argv, capture_output=True, timeout=30, cwd="/")
    except (OSError, subprocess.SubprocessError) as why:
        return str(why)
    return None if got.returncode == 0 else (got.stderr.decode("utf-8", "replace").strip()[-200:] or f"exit {got.returncode}")


@dataclass
class Box:
    """One side's run (the base, or the pull request): its tree, a home and an output directory, and how commands
    run in it."""
    root: Path
    sandboxed: bool
    work: Path = field(init=False)
    home: Path = field(init=False)
    out: Path = field(init=False)
    env: dict = field(default_factory=dict)
    python: str | None = None       # a venv's interpreter, when the tree's dependencies were installed into one

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.work, self.home, self.out = self.root / "work", self.root / "home", self.root / "out"
        for d in (self.home, self.out, self.root / "tmp"):
            d.mkdir(parents=True, exist_ok=True)

    def open_up(self) -> None:
        """Give the sandbox user the tree (and nothing else of ours)."""
        if not self.sandboxed:
            return
        os.chmod(self.root, 0o755)
        for d in (self.work, self.home, self.out, self.root / "tmp"):
            for p in [d, *d.rglob("*")]:
                try:
                    if not p.is_symlink():
                        p.chmod(p.stat().st_mode | (0o777 if p.is_dir() else 0o666))
                except OSError:
                    pass

    def _env(self, extra: dict | None) -> dict:
        if self.sandboxed:
            env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "LANG": "C.UTF-8"}
        else:
            env = {k: v for k, v in os.environ.items() if not k.startswith(_LEAK)}
        if self.sandboxed or os.name != "nt":
            env.update({"HOME": str(self.home), "TMPDIR": str(self.root / "tmp")})
        env.update(self.env)
        env.update(extra or {})
        return env

    def wrap(self, argv: list, net: bool = False, env: dict | None = None) -> tuple[list, dict | None]:
        """The argv (and environment) that runs `argv` in the sandbox: another user, an empty environment, no network
        unless `net`. Without a sandbox on this machine: the same argv, with CI's variables removed."""
        full = self._env(env)
        if not self.sandboxed:
            return list(argv), full
        drop = ["setpriv", f"--reuid={SANDBOX_UID}", f"--regid={SANDBOX_UID}", "--clear-groups", "--",
                "env", "-i", *[f"{k}={v}" for k, v in full.items()], *argv]
        if not net:
            drop = ["unshare", "-n", "--", "sh", "-c", 'ip link set lo up 2>/dev/null; exec "$@"', "sh", *drop]
        return ([] if os.geteuid() == 0 else ["sudo", "-n"]) + drop, None

    def run(self, cmd, net: bool = False, env: dict | None = None, timeout: float = 600,
            cwd: Path | None = None) -> tuple[int, str]:
        """Run `cmd` (argv, or a shell string) in the tree. Returns (exit code, combined output); 124 on a timeout."""
        argv = ["sh", "-c", cmd] if isinstance(cmd, str) and os.name != "nt" else cmd
        shell = isinstance(argv, str)
        full = self._env(env)
        if not shell:
            argv, full = self.wrap(argv, net, env)
        try:
            got = subprocess.run(argv, cwd=str(cwd or self.work), env=full, capture_output=True, timeout=timeout,
                                 shell=shell, stdin=subprocess.DEVNULL)   # a test that reads stdin must not wait on ours
        except subprocess.TimeoutExpired:
            return 124, "timed out"
        except OSError as why:
            return 127, str(why)
        return got.returncode, (got.stdout + got.stderr).decode("utf-8", "replace")

    def clean(self) -> None:
        if self.sandboxed:   # files the sandbox user made are not ours to delete
            subprocess.run(([] if os.geteuid() == 0 else ["sudo", "-n"]) + ["rm", "-rf", str(self.root)],
                           capture_output=True, timeout=120)
        shutil.rmtree(self.root, ignore_errors=True)


# ---- the runners ---------------------------------------------------------------------------------------------------

@dataclass
class Run:
    results: dict | None            # test id -> passed | failed | skipped; None when no report came out
    accept: set = field(default_factory=set)   # the ids that are the acceptance checks
    sentinel: str | None = None     # ids the report must show passed / failed (None: this runner has no sentinel)
    canary: str | None = None
    log: str = ""


def _junit(path: Path) -> dict | None:
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return None
    out = {}
    for tc in root.iter("testcase"):
        tags = {c.tag for c in tc}
        state = "failed" if tags & {"failure", "error"} else "skipped" if "skipped" in tags else "passed"
        where = tc.get("file") or tc.get("classname", "")
        out[f"{where}::{tc.get('name', '')}"] = state
    return out


def sentinel(work: Path, test_dirs) -> tuple[str, str]:
    """Write a random-named passing sentinel and failing canary into the first tests dir; returns their names."""
    tok = secrets.token_hex(8)
    dirs = list(test_dirs) or ["tests"]
    d = next((work / t for t in dirs if (work / t).is_dir()), work / dirs[0])
    d.mkdir(parents=True, exist_ok=True)
    (d / f"test_knos_sentinel_{tok}.py").write_text(
        f"def test_sentinel_{tok}():\n    assert True\n\n\ndef test_canary_{tok}():\n    assert False\n", "utf-8")
    return f"test_sentinel_{tok}", f"test_canary_{tok}"


def _by_name(results: dict | None, name: str) -> str | None:
    return next((k for k in results or {} if k.split("::")[-1] == name), None)


def run_tests(work: Path, targets: list[str], timeout: float = 600, box: Box | None = None,
              python: str | None = None) -> dict | None:
    """Run pytest in `work`; {file-or-class::name: passed|failed|skipped} from a report written outside the tree."""
    own = box is None
    box = box or Box(Path(tempfile.mkdtemp(prefix="knos-run-")).resolve(), False)
    if own:
        box.work = Path(work).resolve()
    rep = box.out / f"{secrets.token_hex(8)}.xml"
    try:
        box.run([python or sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--continue-on-collection-errors",
                 f"--junitxml={rep}",
                 f"--rootdir={box.work}", *targets], timeout=timeout,
                env={"PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
        return _junit(rep)
    finally:
        if own:
            box.clean()


def _python(box: Box, issue: str, test_dirs, timeout: float, cfg: dict) -> Run:
    sent, canary = sentinel(box.work, test_dirs)
    box.open_up()
    targets = [f".knos/acceptance/{issue}", *(t for t in test_dirs if (box.work / t).is_dir())]
    got = run_tests(box.work, targets, timeout, box, box.python)
    prefix = f".knos.acceptance.{issue}."
    accept = {k for k in got or {} if prefix in k}     # (a module that failed to import is named in `name`)
    return Run(got, accept, _by_name(got, sent), _by_name(got, canary))


def _node_files(box: Box, issue: str, test_dirs) -> tuple[list[str], list[str]]:
    accept, rest = [], []
    for p in sorted(box.work.rglob("*")):
        rel = p.relative_to(box.work)
        if not p.is_file() or _SKIP.intersection(rel.parts) or not _NODE_SRC.search(p.name):
            continue
        s = rel.as_posix()
        if rel.parts[:3] == (".knos", "acceptance", issue):
            accept.append(s)
        elif _NODE_TEST.search(s) or (rel.parts[0] in test_dirs and not p.name.startswith(("_", "."))):
            rest.append(s)
    return accept, rest


def _node(box: Box, issue: str, test_dirs, timeout: float, cfg: dict) -> Run:
    """Two runs, because node's JUnit report does not say which file a test came from: the acceptance bundle (with
    the sentinel), then the repository's own tests."""
    tok = secrets.token_hex(8)
    bundle = box.work / ".knos" / "acceptance" / issue
    (bundle / f"knos_sentinel_{tok}.test.cjs").write_text(
        "const test = require('node:test');\n"
        f"test('sentinel_{tok}', () => {{}});\n"
        f"test('canary_{tok}', () => {{ throw new Error('canary'); }});\n", "utf-8")
    box.open_up()
    accept, rest = _node_files(box, issue, test_dirs)
    got: dict = {}
    log = ""
    for label, files in (("acceptance", accept), ("tests", rest)):
        if not files:
            continue
        rep = box.out / f"{secrets.token_hex(8)}.xml"
        _, out = box.run(["node", "--test", "--test-reporter=junit", f"--test-reporter-destination={rep}", *files],
                         timeout=timeout)
        log += out
        part = _junit(rep)
        if part is None:
            return Run(None, log=log[-2000:])
        for k, v in part.items():
            name = k.split("::", 1)[-1]
            if name.replace("\\", "/") in files:     # node reports a file that registered no test as one passed test
                name, v = f"{name} (no test ran)", "failed"
            got[f"{label}::{name}"] = v
    sent, canary = f"acceptance::sentinel_{tok}", f"acceptance::canary_{tok}"
    return Run(got, {k for k in got if k.startswith("acceptance::") and k not in (sent, canary)},
               sent if sent in got else None, canary if canary in got else None, log[-2000:])


def _go(box: Box, issue: str, test_dirs, timeout: float, cfg: dict) -> Run:
    tok = secrets.token_hex(8)
    spot = box.work / ".knos" / "acceptance" / issue / f"knos_sentinel_{tok}"   # its own package: it builds and runs
    spot.mkdir(parents=True)                                                    # even when the acceptance does not
    (spot / "sentinel_test.go").write_text(
        f'package sentinel\n\nimport "testing"\n\nfunc TestSentinel{tok}(t *testing.T) {{}}\n\n'
        f'func TestCanary{tok}(t *testing.T) {{ t.Fatal("canary") }}\n', "utf-8")
    box.open_up()
    _, out = box.run(["go", "test", "-json", "-count=1", "-vet=off", "./...", f"./.knos/acceptance/{issue}/..."],
                     timeout=timeout, env={"GOFLAGS": "-mod=mod", "GOPROXY": "off", "GOTOOLCHAIN": "local",
                                           "GOPATH": str(box.home / "go"),
                                           "GOCACHE": str(box.home / ".cache" / "go-build")})
    got: dict = {}
    failed_pkgs, seen = set(), False
    for line in out.splitlines():
        m = re.match(r"FAIL\s+(\S+) \[(build|setup) failed\]", line)
        if m:
            failed_pkgs.add(m.group(1))
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        seen = True
        if ev.get("Test") and ev.get("Action") in ("pass", "fail", "skip"):
            got[f"{ev.get('Package', '')}::{ev['Test']}"] = {"pass": "passed", "fail": "failed", "skip": "skipped"}[ev["Action"]]
        elif ev.get("Action") == "fail" and ev.get("Package") and not ev.get("Test"):
            failed_pkgs.add(ev["Package"])
    if not seen and not failed_pkgs:
        return Run(None, log=out[-2000:])
    for pkg in failed_pkgs:     # a package that did not build, or failed outside any test, counts as one failed check
        if not any(k.startswith(pkg + "::") for k in got):
            got[f"{pkg}::(build)"] = "failed"
    mark = f"/.knos/acceptance/{issue}::"
    accept = {k for k in got if mark in k}
    return Run(got, accept, _by_name(got, f"TestSentinel{tok}"), _by_name(got, f"TestCanary{tok}"), out[-2000:])


def _cargo_results(out: str) -> dict:
    got: dict = {}
    current = ""
    for line in out.splitlines():
        m = re.match(r"\s*Running (?:unittests )?(\S+)", line)
        if m:
            current = Path(m.group(1)).stem
            continue
        if re.match(r"\s*Doc-tests ", line):
            current = "doc"
            continue
        m = re.match(r"test (.+?) \.\.\. (ok|FAILED|ignored)", line)
        if m:
            got[f"{current}::{m.group(1)}"] = {"ok": "passed", "FAILED": "failed", "ignored": "skipped"}[m.group(2)]
    return got


def _rustup_home() -> Path:
    """Where rustup keeps its toolchains. Not from $HOME, which the judge's caller may have pointed elsewhere (and the
    sandbox user has its own): $RUSTUP_HOME, else next to the cargo on PATH (~/.cargo/bin/cargo -> ~/.rustup), else
    the account's own home directory."""
    if os.environ.get("RUSTUP_HOME"):
        return Path(os.environ["RUSTUP_HOME"])
    cands = []
    cargo = shutil.which("cargo")
    if cargo:
        cands.append(Path(cargo).resolve().parent.parent.parent / ".rustup")
    if os.environ.get("CARGO_HOME"):
        cands.append(Path(os.environ["CARGO_HOME"]).parent / ".rustup")
    try:
        import pwd
        cands.append(Path(pwd.getpwuid(os.getuid()).pw_dir) / ".rustup")
    except (ImportError, KeyError, AttributeError):
        pass
    cands.append(Path.home() / ".rustup")
    for c in cands:
        if (c / "toolchains").is_dir():
            return c
    return cands[-1]


def _rust_toolchain() -> str | None:
    """The default toolchain of that rustup home, pinned for the run: the sandbox has no rustup settings of its own."""
    home = _rustup_home()
    try:
        m = re.search(r'^default_toolchain\s*=\s*"([^"]+)"', (home / "settings.toml").read_text("utf-8"), re.M)
    except OSError:
        m = None
    if m:
        return m.group(1)
    try:
        names = sorted(p.name for p in (home / "toolchains").iterdir() if p.is_dir())
    except OSError:
        return None
    return next((n for n in names if n.startswith("stable")), names[0] if names else None)


def _rust(box: Box, issue: str, test_dirs, timeout: float, cfg: dict) -> Run:
    tok = secrets.token_hex(8)
    tests = box.work / "tests"
    tests.mkdir(exist_ok=True)
    stems = []
    for f in sorted((box.work / ".knos" / "acceptance" / issue).glob("*.rs")):
        stem = f"knos_acceptance_{re.sub(r'[^A-Za-z0-9_]', '_', issue)}_{f.stem}"
        shutil.copyfile(f, tests / f"{stem}.rs")
        stems.append(stem)
    (tests / f"knos_sentinel_{tok}.rs").write_text(
        f"#[test]\nfn sentinel_{tok}() {{}}\n\n#[test]\nfn canary_{tok}() {{ panic!(\"canary\"); }}\n", "utf-8")
    box.open_up()
    env = {"CARGO_HOME": str(box.home / ".cargo"), "CARGO_NET_OFFLINE": "true", "CARGO_TERM_COLOR": "never",
           "RUSTUP_HOME": str(_rustup_home())}
    toolchain = os.environ.get("RUSTUP_TOOLCHAIN") or _rust_toolchain()
    if toolchain:
        env["RUSTUP_TOOLCHAIN"] = toolchain
    _, out = box.run("cargo test --no-fail-fast 2>&1", timeout=timeout, env=env)
    got = _cargo_results(out)
    if not got:     # nothing ran: if it is the acceptance that does not build (the usual case on the base, where the
        for stem in stems:                                        # feature does not exist yet), run the rest without it
            (tests / f"{stem}.rs").unlink()
        _, again = box.run("cargo test --no-fail-fast 2>&1", timeout=timeout, env=env)
        got = _cargo_results(again)
        if not got:
            return Run(None, log=out[-2000:])
        got.update({f"{stem}::(build)": "failed" for stem in stems})
        out += again
    accept = {k for k in got if k.split("::")[0] in stems}
    return Run(got, accept, _by_name(got, f"sentinel_{tok}"), _by_name(got, f"canary_{tok}"), out[-2000:])


_RUBY_LINE = re.compile(r"^(\S+#\S+) = [\d.]+ s = ([.FESB])$", re.M)


def _ruby(box: Box, issue: str, test_dirs, timeout: float, cfg: dict) -> Run:
    """minitest, one file per process so every result knows its file: the acceptance bundle, then the repository's own
    tests. Every process also defines a sentinel and a canary (inline, so no file holds their names), so code that
    makes every test pass is seen where it runs.
    A file that registered no test counts as one failed check."""
    tok = secrets.token_hex(8)
    box.open_up()
    files = {"acceptance": [], "tests": []}
    for p in sorted(box.work.rglob("*.rb")):
        rel = p.relative_to(box.work)
        s = rel.as_posix()
        if _SKIP.intersection(rel.parts) or p.name == "test_helper.rb" or not _RUBY_TEST.search(s):
            continue
        if rel.parts[:3] == (".knos", "acceptance", issue):
            files["acceptance"].append(s)
        elif rel.parts[0] in test_dirs:
            files["tests"].append(s)
    got: dict = {}
    log = ""
    sent, canary = f"KnosProbe{tok}#test_sentinel", f"KnosProbe{tok}#test_canary"
    probes: dict = {sent: [], canary: []}      # what the sentinel and the canary did in every process
    for names in files.values():
        for f in names:
            load = (f'require "minitest/autorun"; class KnosProbe{tok} < Minitest::Test; def test_sentinel; assert true; end; '
                    'def test_canary; assert false, "canary"; end; end; require "./#{ARGV.shift}"')   # no file holds the token
            _, out = box.run(["ruby", "-Ilib", "-Itest", "-e", load, f, "--verbose"], timeout=timeout)
            log += out
            found = [(t, m) for t, m in _RUBY_LINE.findall(out) if t not in probes]
            for t, m in _RUBY_LINE.findall(out):
                if t in probes:
                    probes[t].append(m)
            for test, mark in found:
                got[f"{f}::{test}"] = {".": "passed", "S": "skipped"}.get(mark, "failed")
            if not found:     # it did not load, or registered nothing: one failed check, as node reports it
                got[f"{f}::(no test ran)"] = "failed"
    # one sentinel and one canary for the whole run: the sentinel passed everywhere, the canary failed everywhere
    sid, cid = f"knos_sentinel::{sent}", f"knos_sentinel::{canary}"
    got[sid] = "passed" if probes[sent] and set(probes[sent]) == {"."} else "failed"
    got[cid] = "failed" if probes[canary] and set(probes[canary]) <= {"F", "E"} else "passed"
    prefix = f".knos/acceptance/{issue}/"
    return Run(got, {k for k in got if k.startswith(prefix) and k not in (sid, cid)}, sid, cid, log[-2000:])


def _command(box: Box, issue: str, test_dirs, timeout: float, cfg: dict) -> Run:
    """Any language: the acceptance check is a command; exit 0 means done. The repository's own test command
    (`tests = "..."` in proof.toml), when set, is the pass-to-pass check."""
    bundle = f".knos/acceptance/{issue}"
    run = (cfg.get("judge") or {}).get("run")
    if not run:
        name = "check" if (box.work / bundle / "check").is_file() else "check.sh"
        run = f"sh {bundle}/{name}"
    box.open_up()
    env = {"KNOS_ACCEPTANCE": bundle, "KNOS_ISSUE": issue}
    code, log = box.run(run, timeout=timeout, env=env)
    got = {"acceptance::check": "passed" if code == 0 else "failed"}
    if cfg.get("tests"):
        code, more = box.run(str(cfg["tests"]), timeout=timeout, env=env)
        got["tests::suite"] = "passed" if code == 0 else "failed"
        log += more
    return Run(got, {"acceptance::check"}, log=log[-2000:])


def _blackbox(box: Box, issue: str, test_dirs, timeout: float, cfg: dict) -> Run:
    """The check that cannot be forged from inside: it runs as the judge, outside the tree, and never loads the pull
    request's code. It reaches that code only through "$KNOS_RUN <command>", which runs the command in the tree,
    inside the sandbox. The check file is the base's (the pull request cannot touch .knos/), so it is trusted the way
    the repository's own CI is. Exit 0 means done."""
    import shlex
    bundle = box.work / ".knos" / "acceptance" / issue
    private = box.root / "check"
    shutil.copytree(bundle, private)
    os.chmod(private, 0o700)
    box.open_up()
    argv, env = box.wrap(["sh", "-c", 'exec "$@"', "sh"], net=False)
    runner = private / "knos-run"
    runner.write_text("#!/bin/sh\n" + f"cd {shlex.quote(str(box.work))} || exit 126\n"
                      + "exec " + " ".join(shlex.quote(a) for a in argv) + ' "$@"\n', "utf-8")
    runner.chmod(0o700)
    name = next(n for n in ("blackbox", "blackbox.sh", "blackbox.py") if (private / n).is_file())
    cmd = [sys.executable, name] if name.endswith(".py") else ["sh", name]
    mine = {k: v for k, v in os.environ.items() if not k.startswith(_LEAK)}
    mine.update({"KNOS_RUN": str(runner), "KNOS_TREE": str(box.work), "KNOS_ISSUE": issue})
    try:
        got = subprocess.run(cmd, cwd=str(private), env=mine, capture_output=True, timeout=timeout)
        code, log = got.returncode, (got.stdout + got.stderr).decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        code, log = 124, "timed out"
    res = {"acceptance::blackbox": "passed" if code == 0 else "failed"}
    if cfg.get("tests"):
        code, more = box.run(str(cfg["tests"]), timeout=timeout)
        res["tests::suite"] = "passed" if code == 0 else "failed"
        log += more
    return Run(res, {"acceptance::blackbox"}, log=log[-2000:])


_RUN = {"blackbox": _blackbox, "python": _python, "node": _node, "go": _go, "rust": _rust, "ruby": _ruby, "command": _command}


def _side(box: Box, runner: str, issue: str, test_dirs, timeout: float, cfg: dict, setup: str | None) -> Run:
    """Install the tree's dependencies (network allowed), then run its tests (no network)."""
    if runner == "rust":
        _reachable(Path(shutil.which("cargo") or "cargo"))
        _reachable(_rustup_home() / "x")
    if runner == "python" and setup:
        # The tree's dependencies go into a venv of its own (the sandbox user cannot write the judge's Python). It
        # sees the judge's pytest through the system site-packages; `pip` in it is the judge's pip, aimed at the venv.
        venv = box.root / "venv"
        made = subprocess.run([sys.executable, "-m", "venv", "--without-pip", "--system-site-packages", str(venv)],
                              capture_output=True, timeout=180)
        if made.returncode == 0:
            bindir = venv / ("Scripts" if os.name == "nt" else "bin")
            py = bindir / ("python.exe" if os.name == "nt" else "python")
            if os.name != "nt":
                for name in ("pip", "pip3"):
                    (bindir / name).write_text(f'#!/bin/sh\nexec "{py}" -m pip "$@"\n', "utf-8")
                    (bindir / name).chmod(0o755)
            if sys.prefix != sys.base_prefix:
                # the judge itself lives in a virtualenv (pipx, uv tool): "system" site-packages is then the bare
                # interpreter's, without pytest. A .pth file puts the judge's own packages after the tree's.
                import site
                import sysconfig
                own = [d for d in site.getsitepackages() if Path(d).is_dir()]
                lib = Path(sysconfig.get_path("purelib", vars={"base": str(venv), "platbase": str(venv)}))
                if lib.is_dir():
                    (lib / "knos_judge.pth").write_text("\n".join(own) + "\n", "utf-8")
            box.python = str(py)
            box.env.update({"VIRTUAL_ENV": str(venv), "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")})
            if box.sandboxed:
                for p in [venv, *venv.rglob("*")]:
                    if not p.is_symlink():
                        p.chmod(p.stat().st_mode | (0o777 if p.is_dir() else 0o666))
    if setup:
        box.open_up()
        env = {"CARGO_HOME": str(box.home / ".cargo"), "GOPATH": str(box.home / "go"),
               "GOCACHE": str(box.home / ".cache" / "go-build"), "GOFLAGS": "-mod=mod",
               "RUSTUP_HOME": str(_rustup_home())}
        code, log = box.run(setup, net=True, timeout=timeout, env=env)
        if code:
            return Run(None, log=f"setup failed (exit {code}): {log[-1500:]}")
    return _RUN[runner](box, issue, test_dirs, timeout, cfg)


def judge(base_dir, pr_dir, cfg: dict, changed: list[str] | None = None, cache: dict | None = None,
          setup: str | None = None, sandbox: str = "auto") -> dict:
    """The verdict on a pull request in tests mode: {"passed", "checks_hash", "reasons", "evidence"}.

    cfg: the base's .knos/proof.toml plus "issue". `changed`: the pull request's changed paths (default: the tree
    diff). `cache` (a dict) reuses the base side's run across pull requests against the same base tree, as the
    benchmark does. `setup`: a shell command that installs a tree's dependencies. `sandbox`: auto (use it when this
    machine can), require (refuse to judge without it), off."""
    base, pr = Path(base_dir), Path(pr_dir)
    issue = str(cfg.get("issue", "")).strip()
    timeout = float(cfg.get("timeout", 600))
    ev: dict = {"issue": issue}

    def verdict(h: str, reasons: list[str]) -> dict:
        return {"passed": not reasons, "checks_hash": h, "reasons": reasons, "evidence": ev}

    if not re.fullmatch(r"[A-Za-z0-9._-]+", issue):
        return verdict("", [f"bad issue id {issue!r}"])
    try:
        h = checks_hash(base / ".knos" / "acceptance" / issue)
        runner = runner_of(base, cfg)
    except ValueError as why:
        return verdict("", [str(why)])
    ev["runner"] = runner
    test_dirs = list(cfg.get("test_dirs", TEST_DIRS[runner]))
    changed = changed_files(base, pr) if changed is None else sorted(changed)
    ev["changed"] = changed
    pats = protected_patterns(cfg, runner)
    bad = [f for f in changed if is_protected(f, pats)]
    if runner in ("python", "command", "blackbox"):
        bad += [f"{n} (pytest section)" for n in ("pyproject.toml", "setup.cfg")
                if n in changed and _pytest_section(base, n) != _pytest_section(pr, n)]
    if bad:
        return verdict(h, [f"touches protected path {f}" for f in bad])
    boxed = sandbox != "off" and sandbox_available()
    if boxed and runner in ("python", "command", "blackbox"):
        why = _sandbox_cannot_run(sys.executable)
        if why and sandbox == "require":
            return verdict(h, [f"the sandbox user cannot run this Python ({sys.executable}): {why}. Install knos where "
                               "other users can reach it; refusing to run pull request code without the sandbox"])
        boxed = not why
    if sandbox == "require" and not boxed:
        return verdict(h, ["no sandbox on this machine (needs Linux, setpriv, unshare and root or passwordless sudo); "
                           "refusing to run pull request code without it"])
    ev["sandbox"] = {"user": SANDBOX_UID, "network": "setup only" if setup else "none"} if boxed else None
    reasons: list[str] = []
    key = (json.dumps(_files(base), sort_keys=True), issue, tuple(test_dirs), runner, setup or "")
    boxes = []
    try:
        if cache is None or key not in cache:
            bb = Box(Path(tempfile.mkdtemp(prefix="knos-judge-")).resolve(), boxed)
            boxes.append(bb)
            overlay(base, base, bb.work, test_dirs, runner)
            got = _side(bb, runner, issue, test_dirs, timeout, cfg, setup)
            if cache is not None:
                cache[key] = got
        pb = Box(Path(tempfile.mkdtemp(prefix="knos-judge-")).resolve(), boxed)
        boxes.append(pb)
        overlay(base, pr, pb.work, test_dirs, runner)
        sides = {"base": got if cache is None else cache[key],
                 "pr": _side(pb, runner, issue, test_dirs, timeout, cfg, setup)}
    finally:
        for b in boxes:
            b.clean()
    res = {}
    for side, run in sides.items():
        if run.results is None:
            reasons.append(f"{side}: the test run wrote no report (killed, exited early or timed out)"
                           + (f": {run.log.strip()[-300:]}" if run.log.strip() else ""))
            continue
        if runner not in ("command", "blackbox"):
            if run.sentinel is None or run.results.get(run.sentinel) != "passed":
                reasons.append(f"{side}: the sentinel test was not collected and passed (the runner was faked)")
            if run.canary is None or run.results.get(run.canary) != "failed":
                reasons.append(f"{side}: the canary test did not fail (something makes every test pass)")
        mine = {k: v for k, v in run.results.items() if k not in (run.sentinel, run.canary)}
        accept = {k: v for k, v in mine.items() if k in run.accept}
        res[side] = (mine, accept)
        ev[side] = {"collected": len(mine), "passed": sum(v == "passed" for v in mine.values()), "acceptance": accept}
    if len(res) == 2:
        (bm, ba), (pm, pa) = res["base"], res["pr"]
        gone = [k for k in ba if k not in pa and not k.startswith("::") and "(" not in k]
        if not pa:
            reasons.append("pr: no acceptance check ran")
        if gone and pa:
            reasons.append("pr: acceptance checks that ran on the base did not run: " + ", ".join(gone))
        if any(v != "passed" for v in pa.values()):
            reasons.append("pr: acceptance checks not passed: " + ", ".join(k for k, v in pa.items() if v != "passed"))
        if ba and all(v == "passed" for v in ba.values()):
            reasons.append("base: the acceptance checks already pass on the base (not fail-to-pass)")
        if len(pm) < len(bm):
            reasons.append(f"pr collected {len(pm)} tests, fewer than the base's {len(bm)}")
        broke = [k for k, v in bm.items() if v == "passed" and k not in ba and pm.get(k) != "passed"]
        if broke:
            reasons.append("pass-to-pass broken: " + ", ".join(broke))
    return verdict(h, reasons)
