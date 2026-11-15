"""Decide a claim: the checks it needs, run by Knos, plus the checks the repo's history made required.

    claim kind -> check        tests -> tests, ci -> ci, pypi -> pypi, urls -> urls, deleted -> deleted,
                               author -> author, release -> author (+ whatever history requires: usually ci)
    .knos/proof.toml           tests / install / author, and [[check]] name, run, when (a regex on the claim).
                               A `run` whose first word is `python` or `python3` runs with the interpreter Knos is
                               running under, on every platform (checks.with_python): never PATH's, which on Windows
                               is the Microsoft Store alias.
    history.required(...)      checks earlier false "done"s in this repo made required (knos.proof.history)
    repo-rules, rule:<id>      the PR (base to working tree, and its commits) against CONTRIBUTING.md and the rules past
                               rejections taught (history.lint_pr). Run FIRST: a violation fails the verdict citing
                               the line, and nothing else runs, so nothing is attested or minted for it.

Results are cached per check and per state of the tree, so a second stop on unchanged work does not re-run the suite.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import checks, claims, history

KIND_CHECKS = {"tests": "tests", "ci": "ci", "pypi": "pypi", "urls": "urls", "deleted": "deleted", "author": "author",
               "release": "author", "done": "tests"}


def config(repo: Path) -> dict:
    return load(Path(repo) / ".knos" / "proof.toml")


def load(p: Path) -> dict:
    p = Path(p)
    if not p.exists():
        return {}
    try:
        import tomllib
    except ImportError:  # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]
    try:
        return tomllib.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a broken config is reported by the verdict, not a crash
        return {"_error": "unreadable .knos/proof.toml"}


@dataclass
class Verdict:
    ok: bool
    claim: claims.Claim
    results: list[checks.Result] = field(default_factory=list)
    required_by_history: set[str] = field(default_factory=set)

    @property
    def digest(self) -> str:
        return hashlib.sha256("".join(sorted(r.digest() for r in self.results)).encode()).hexdigest()

    def explain(self) -> str:
        lines = [f"{'ok ' if r.ok else 'NO '} {r.name}: {r.detail}" for r in self.results]
        if self.required_by_history:
            lines.append("required by this repo's history (Knos learned it from an earlier false done): "
                         + ", ".join(sorted(self.required_by_history)))
        return "\n".join(lines)


def _tree_state(repo: Path) -> str:
    def git(*a):
        try:
            return subprocess.run(["git", *a], cwd=str(repo), capture_output=True, text=True, timeout=20).stdout
        except (OSError, subprocess.TimeoutExpired):
            return ""
    return hashlib.sha256((git("rev-parse", "HEAD") + git("status", "--porcelain") + git("diff")).encode()).hexdigest()


def _cache_path() -> Path:
    from .. import paths
    return paths.home() / "proof-cache.json"


def needed(claim: claims.Claim, cfg: dict, store, repo: Path | None = None,
           agent: str | None = None) -> tuple[list[str], set[str]]:
    names = {KIND_CHECKS[k] for k in claim.kinds if k in KIND_CHECKS}
    if "tests" in names and "tests" not in claim.kinds and repo is not None and not checks.test_command(repo, cfg.get("tests")):
        names.discard("tests")   # a bare "done" in a repository with no test command Knos can find: nothing to run
    if repo is not None and any(r.get("origin") == "contributing" for r in history.repo_rules(store, repo)):
        names.add("repo-rules")
    learned = history.required(store, claim.kinds | ({"release"} if "pypi" in claim.kinds else set()))
    learned |= history.tamper_checks_required(store, repo, agent)   # tampering caught on this repo or by this agent
    for c in cfg.get("check", []) or []:
        if c.get("name") and (not c.get("when") or re.search(c["when"], claim.text, re.I)):
            names.add(f"custom:{c['name']}")
    return sorted(names | learned), learned - names


def _git(repo: Path, *a) -> tuple[int, str]:
    try:
        got = subprocess.run(["git", *a], cwd=str(repo), capture_output=True, text=True, timeout=30,
                             encoding="utf-8", errors="replace")
        return got.returncode, got.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def pr(repo: Path, cfg: dict) -> tuple[str, list[dict]]:
    """The PR as Knos sees it: the diff from the base (proof.toml `base`, else the merge-base with origin/HEAD,
    origin/main, main or master) to the working tree, and the commits since the base. On the base itself: the
    uncommitted changes."""
    head = _git(repo, "rev-parse", "HEAD")[1].strip()
    base = ""
    for ref in [cfg.get("base"), "origin/HEAD", "origin/main", "main", "master"]:
        if not ref:
            continue
        code, got = _git(repo, "merge-base", "HEAD", ref)
        if code == 0 and got.strip() and got.strip() != head:
            base = got.strip()
            break
    if not base:
        return _git(repo, "diff", "HEAD")[1], []
    log = _git(repo, "log", "--format=%H%x00%B%x01", f"{base}..HEAD")[1]
    commits = [{"sha": c.split("\0", 1)[0].strip(), "message": c.split("\0", 1)[1].strip()}
               for c in log.split("\x01") if "\0" in c]
    return _git(repo, "diff", base)[1], commits


def repo_rules_check(repo: Path, cfg: dict, store, only: set[str], name: str = "repo-rules") -> checks.Result:
    """The PR against the repo's rules (`only`: their ids), each violation citing the rule's line and the PR's."""
    diff, commits = pr(repo, cfg)
    got = history.lint_pr(store, repo, diff, commits, only)
    if not got:
        return checks.Result(name, True, "the PR keeps every repo rule", {"violations": []})
    more = f" (+{len(got) - 6} more)" if len(got) > 6 else ""
    return checks.Result(name, False, "; ".join(map(str, got[:6])) + more, {"violations": [str(v) for v in got]})


def run_check(name: str, repo: Path, claim: claims.Claim, cfg: dict, runners: dict | None = None,
              store=None) -> checks.Result:
    runners = runners or {}
    if name in runners:
        return runners[name](repo, claim, cfg)
    store = store if store is not None else history.NullStore()
    if name == "repo-rules":
        return repo_rules_check(repo, cfg, store, {r["id"] for r in history.repo_rules(store, repo)
                                                   if r.get("origin") == "contributing"})
    if name.startswith("rule:"):
        return repo_rules_check(repo, cfg, store, {name[5:]}, name)
    if name == "tests":
        return checks.tests(repo, cfg.get("tests"), cfg.get("install"))
    if name == "ci":
        return checks.ci(repo)
    if name == "pypi":
        return checks.pypi(repo, claim.version if claim.version and "pypi" in claim.kinds else None)
    if name == "urls":
        return checks.urls(claim.urls)
    if name == "deleted":
        return checks.deleted(repo, claim.deleted)
    if name == "author":
        return checks.author(repo, cfg.get("author"))
    if name.startswith("custom:"):
        spec: dict = next((c for c in cfg.get("check", []) if f"custom:{c.get('name')}" == name), {})
        return checks.custom(repo, spec.get("name", name), spec.get("run", "false"))
    if name.startswith("tamper:"):   # fail closed: only the prove judge (passed in as a runner) can clear it
        return checks.Result(name, False, f"required since {name[7:]} was caught here; run by the judge (knos.judge)")
    return checks.Result(name, False, "unknown check")


def evaluate(repo: Path, text: str, store=None, runners: dict | None = None, use_cache: bool = True,
             agent: str | None = None) -> Verdict:
    repo = Path(repo)
    store = store if store is not None else history.NullStore()
    claim = claims.read(text)
    if not claim.says_done:
        return Verdict(True, claim)
    cfg = config(repo)
    names, learned = needed(claim, cfg, store, repo, agent)
    gate = [n for n in names if n == "repo-rules" or n.startswith("rule:")]
    names = gate + [n for n in names if n not in gate]   # the repo's rules first: nothing runs past a violation
    state = _tree_state(repo)
    cache = {}
    if use_cache:
        try:
            cache = json.loads(_cache_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
    results = []
    for n in names:
        key = f"{repo}|{state}|{n}|{','.join(claim.urls) if n == 'urls' else ''}|{','.join(claim.deleted)}"
        hit = cache.get(key) if n in ("tests",) else None   # only the slow, tree-determined check is cached
        if hit:
            results.append(checks.Result(**hit))
            continue
        r = run_check(n, repo, claim, cfg, runners, store)
        results.append(r)
        if gate and n == gate[-1] and not all(x.ok for x in results):
            break   # the PR breaks a repo rule: the verdict fails here, before any other check or attestation
        if n == "tests" and use_cache:
            cache[key] = r.__dict__
    if use_cache and cache:
        try:
            _cache_path().write_text(json.dumps(cache), encoding="utf-8")
        except OSError:
            pass
    v = Verdict(all(r.ok for r in results), claim, results, learned)
    try:
        history.record(store, checks.head(repo), text, sorted(claim.kinds),
                       [{"name": r.name, "ok": r.ok, "detail": r.detail} for r in results], v.ok)
    except Exception:  # noqa: BLE001 - the verdict stands even if the store is full
        pass
    return v
