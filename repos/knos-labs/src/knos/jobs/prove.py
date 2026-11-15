"""`knos prove --job JOB --jwt-file PATH`: pay a GitHub-posted job with the GitHub Actions OIDC token that proves it.

The token is minted by the `attest` job of .github/workflows/prove.yml (audience
`knos:<job>:<head sha>:<checks hash>:<payout>`, see parse_aud) after the `check` job judged the pull request
(judge, below). The escrow verifies the token's signature and claims on chain (market.prove_github); this module only
refuses early, with a clear reason, a token the chain would refuse anyway, so a wrong audience or an expired token
costs no transaction.
"""

from __future__ import annotations

import base64
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
import time
from pathlib import Path
from xml.etree import ElementTree

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

ISSUER = "https://token.actions.githubusercontent.com"


def claims(jwt: str) -> dict:
    """The token's payload, unverified (the chain verifies the signature)."""
    parts = jwt.strip().split(".")
    if len(parts) != 3:
        raise ValueError("not a JWT (expected header.payload.signature)")
    body = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        got = json.loads(base64.urlsafe_b64decode(body))
    except ValueError:
        raise ValueError("the JWT payload is not base64url JSON") from None
    if not isinstance(got, dict):
        raise ValueError("the JWT payload is not a JSON object")
    return got


def precheck(c: dict, job_id: bytes, now: float | None = None) -> None:
    """Raise ValueError naming the first claim the on-chain check would refuse."""
    now = time.time() if now is None else now
    aud = c.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if len(auds) != 1:
        raise ValueError(f"audience is {aud!r}: expected one knos:<job>:<head>:<checks>:<payout> audience")
    try:
        got = parse_aud(auds[0])
    except ValueError as why:
        raise ValueError(f"audience: {why}") from None
    if got["job"] != job_id.hex():
        raise ValueError(f"audience is for job {got['job']}, not {job_id.hex()}: this token was minted for another job")
    if c.get("iss") != ISSUER:
        raise ValueError(f"issuer is {c.get('iss')!r}, not GitHub Actions ({ISSUER})")
    exp = c.get("exp")
    if not isinstance(exp, (int, float)) or exp <= now:
        raise ValueError("the token has expired: mint a new one (they last minutes)")
    wsha = str(c.get("job_workflow_sha", ""))
    if len(wsha) != 40 or any(ch not in "0123456789abcdef" for ch in wsha):
        raise ValueError(f"job_workflow_sha is {wsha!r}: the token must come from a pinned prove.yml commit "
                         "(the escrow accepts only commits registered on chain)")


def prove(ledger, payer, job_id: bytes, jwt: str) -> tuple[str, str]:
    """Pre-check, then hand the token to the escrow. Returns the two verify transaction signatures."""
    precheck(claims(jwt), job_id)
    from . import market
    fn = getattr(market, "prove_github", None)
    if fn is None:
        raise RuntimeError("this knos has no on-chain GitHub verification yet (market.prove_github)")
    return fn(ledger, payer, job_id, jwt)


# ---- the 5-part audience -------------------------------------------------------------------------------------------
#
#     knos:<job id, 64 hex>:<PR head sha, 40 hex>:<acceptance checks hash, 64 hex>:<payout, base58 Solana pubkey>
#
# The escrow fixed the checks hash at funding; the token binds the commit that passed them and who gets paid.

_HEX = re.compile(r"[0-9a-f]+")
_B58 = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")


def build_aud(job: str, head: str, checks: str, payout: str) -> str:
    """The audience prove.yml's attest job mints. Raises ValueError on a malformed part."""
    aud = f"knos:{job}:{head}:{checks}:{payout}"
    parse_aud(aud)
    return aud


def parse_aud(aud: str) -> dict:
    """Split a 5-part audience into job, head, checks, payout. Raises ValueError naming the bad part."""
    parts = str(aud).split(":")
    if len(parts) != 5 or parts[0] != "knos":
        raise ValueError(f"{aud!r} is not knos:<job>:<head sha>:<checks hash>:<payout>")
    _, job, head, checks, payout = parts
    for name, v, n in (("job", job, 64), ("head sha", head, 40), ("checks hash", checks, 64)):
        if len(v) != n or not _HEX.fullmatch(v):
            raise ValueError(f"{name} {v!r} is not {n} lowercase hex characters")
    if not _B58.fullmatch(payout):
        raise ValueError(f"payout {payout!r} is not a base58 Solana address")
    return {"job": job, "head": head, "checks": checks, "payout": payout}


def checks_hash(folder: Path) -> str:
    """sha256 over the acceptance bundle: sorted relative paths, each "path\\0sha256(content)\\n"."""
    folder = Path(folder)
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else []
    if not files:
        raise ValueError(f"no acceptance tests in {folder}")
    lines = "".join(f"{f}\0{hashlib.sha256((folder / f).read_bytes()).hexdigest()}\n" for f in files)
    return hashlib.sha256(lines.encode()).hexdigest()


# ---- the repo's own rules and learned tampering, before the judge (Sibyl memory, kept in the caller's cache) --------

def judge_with_rules(base_dir, pr_dir, cfg: dict, changed: list[str] | None, diff_text: str | None, store,
                     repo: str | None = None, agent: str | None = None) -> dict:
    """judge(), gated by the base's CONTRIBUTING rules (knos.proof.history.parse_contributing) on the PR's diff, run
    first: a violation refuses the PR before any test runs or any token is minted, and is learned
    (history.learn_tamper): `tamper:rule:<kind>` is then required for every later PR to this repo or by this agent,
    and the evidence names it (`required_by_history`). A protected-path refusal is learned the same way."""
    from ..proof import history
    base = Path(base_dir)
    required = sorted(history.tamper_checks_required(store, repo, agent))
    contributing = [r for r in history.repo_rules(store, base) if r.get("origin") == "contributing"]
    violations = history.lint_pr(store, base, diff_text, (), {r["id"] for r in contributing}) \
        if diff_text is not None and contributing else []
    if not violations and diff_text is not None:   # what history made required, in CONTRIBUTING or not
        violations = history.lint_learned(required, diff_text)
    if violations:
        try:
            h = checks_hash(base / ".knos" / "acceptance" / str(cfg.get("issue", "")))
        except ValueError:
            h = ""
        for kind in sorted({x.rule["kind"] for x in violations}):
            first = next(x for x in violations if x.rule["kind"] == kind)
            history.learn_tamper(store, repo, agent, f"rule:{kind}", str(first))
        v = {"passed": False, "checks_hash": h, "reasons": [f"repo rule: {x}" for x in violations],
             "evidence": {"issue": str(cfg.get("issue", "")), "repo_rules": [str(x) for x in violations]}}
    else:
        v = judge(base_dir, pr_dir, cfg, changed)
        bad = [r for r in v["reasons"] if r.startswith("touches protected path")]
        if bad:
            history.learn_tamper(store, repo, agent, "protected-path", bad[0])
        if contributing:
            v["evidence"]["repo_rules"] = []
    v["evidence"]["required_by_history"] = required
    v["evidence"]["learned"] = sorted(history.tamper_checks_required(store, repo, agent))
    return v


# ---- judge: the check job's verdict --------------------------------------------------------------------------------
#
# judge(base, pr, cfg) decides whether the pull request at `pr` delivers issue cfg["issue"] against the base checkout
# at `base`, with the pull request unable to weaken what it is judged by:
#   protected     the PR may not touch .knos/**, .github/**, the test dirs, conftest.py, pytest.ini, tox.ini, nor the
#                 pytest sections of pyproject.toml / setup.cfg (proof.toml `protected = [...]` replaces the list).
#   overlay       the run happens on the PR's source with the base's test dirs, .github/, .knos/, every conftest.py,
#                 pytest.ini, tox.ini, setup.cfg and pyproject.toml copied over it, and PYTEST_* env cleared.
#   sentinel      a random-named passing test and a random-named failing canary are written into the overlaid tests
#                 dir; the report (written outside the tree, at a random path) must show the sentinel passed and the
#                 canary failed, or the runner was faked, short-circuited or patched to pass everything.
#   fail-to-pass  every acceptance test (.knos/acceptance/<issue>/, from the base) passes on the PR and at least one
#                 fails on the base; every other test that passed on the base still passes (pass-to-pass); and the PR
#                 collects at least as many tests as the base.
# Out of scope: an implementation that special-cases the acceptance inputs (a stub returning the expected constants)
# passes, as it would pass any test it was shown; and code under test runs in pytest's own process, so a PR that
# finds the sentinel names and rewrites the report at exit is not stopped by this job alone.

DEFAULT_TEST_DIRS = ("tests", "test")
CONFIG_FILES = ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml")
_SKIP = {".git", "__pycache__", ".pytest_cache"}


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


def protected_patterns(cfg: dict) -> list[str]:
    if isinstance(cfg.get("protected"), list):
        return [str(x) for x in cfg["protected"]]
    dirs = cfg.get("test_dirs", DEFAULT_TEST_DIRS)
    return [".knos/**", ".github/**", *(f"{d.strip('/')}/**" for d in dirs),
            "conftest.py", "**/conftest.py", "pytest.ini", "tox.ini"]


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


def overlay(base: Path, pr: Path, work: Path, test_dirs) -> None:
    """Copy the PR tree to `work`, then replace everything that decides how tests run with the base's copy."""
    shutil.copytree(pr, work, ignore=shutil.ignore_patterns(*_SKIP))
    for d in [*test_dirs, ".github", ".knos"]:
        shutil.rmtree(work / d, ignore_errors=True)
        if (base / d).is_dir():
            shutil.copytree(base / d, work / d, ignore=shutil.ignore_patterns(*_SKIP))
    for c in list(work.rglob("conftest.py")):
        c.unlink()
    for c in base.rglob("conftest.py"):
        rel = c.relative_to(base)
        if not _SKIP.intersection(rel.parts):
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(c, work / rel)
    for name in CONFIG_FILES:
        (work / name).unlink(missing_ok=True)
        if (base / name).is_file():
            shutil.copyfile(base / name, work / name)


def sentinel(work: Path, test_dirs) -> tuple[str, str]:
    """Write a random-named passing sentinel and failing canary into the first tests dir; returns their names."""
    tok = secrets.token_hex(8)
    d = next((work / t for t in test_dirs if (work / t).is_dir()), work / list(test_dirs)[0])
    d.mkdir(parents=True, exist_ok=True)
    (d / f"test_knos_sentinel_{tok}.py").write_text(
        f"def test_sentinel_{tok}():\n    assert True\n\n\ndef test_canary_{tok}():\n    assert False\n", "utf-8")
    return f"test_sentinel_{tok}", f"test_canary_{tok}"


def run_tests(work: Path, targets: list[str], timeout: float = 600) -> dict | None:
    """Run pytest in `work`; {classname::name: passed|failed|skipped} from a report at a random path outside it."""
    tmp = Path(tempfile.mkdtemp(prefix="knos-report-"))
    rep = tmp / f"{secrets.token_hex(8)}.xml"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"   # no installed plugin decides the outcome (and startup is fast)
    try:
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={rep}",
                        f"--rootdir={work}", *targets], cwd=work, env=env, capture_output=True, timeout=timeout)
        root = ElementTree.parse(rep).getroot()
    except (subprocess.TimeoutExpired, OSError, ElementTree.ParseError):
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = {}
    for tc in root.iter("testcase"):
        tags = {c.tag for c in tc}
        state = "failed" if tags & {"failure", "error"} else "skipped" if "skipped" in tags else "passed"
        out[f"{tc.get('classname', '')}::{tc.get('name', '')}"] = state
    return out


def _side(work: Path, issue: str, test_dirs, timeout: float):
    sent, canary = sentinel(work, test_dirs)
    targets = [f".knos/acceptance/{issue}", *(t for t in test_dirs if (work / t).is_dir())]
    return run_tests(work, targets, timeout), sent, canary


def judge(base_dir, pr_dir, cfg: dict, changed: list[str] | None = None, cache: dict | None = None) -> dict:
    """The check job's verdict on a pull request: {"passed", "checks_hash", "reasons", "evidence"}.

    cfg: the base's .knos/proof.toml plus "issue"; `changed` is the PR's changed paths (default: the tree diff);
    `cache` (a dict) reuses the base side's run across PRs against the same base tree, as the benchmark does."""
    base, pr = Path(base_dir), Path(pr_dir)
    issue = str(cfg.get("issue", "")).strip()
    test_dirs = list(cfg.get("test_dirs", DEFAULT_TEST_DIRS))
    timeout = float(cfg.get("timeout", 600))
    ev: dict = {"issue": issue}

    def verdict(h: str, reasons: list[str]) -> dict:
        return {"passed": not reasons, "checks_hash": h, "reasons": reasons, "evidence": ev}

    if not re.fullmatch(r"[A-Za-z0-9._-]+", issue):
        return verdict("", [f"bad issue id {issue!r}"])
    try:
        h = checks_hash(base / ".knos" / "acceptance" / issue)
    except ValueError as why:
        return verdict("", [str(why)])
    changed = changed_files(base, pr) if changed is None else sorted(changed)
    ev["changed"] = changed
    pats = protected_patterns(cfg)
    bad = [f for f in changed if is_protected(f, pats)]
    bad += [f"{n} (pytest section)" for n in ("pyproject.toml", "setup.cfg")
            if n in changed and _pytest_section(base, n) != _pytest_section(pr, n)]
    if bad:
        return verdict(h, [f"touches protected path {f}" for f in bad])
    reasons: list[str] = []
    key = (json.dumps(_files(base), sort_keys=True), issue, tuple(test_dirs))
    with tempfile.TemporaryDirectory(prefix="knos-judge-") as tmp:
        wb, wp = Path(tmp) / "base", Path(tmp) / "pr"
        if cache is None or key not in cache:
            overlay(base, base, wb, test_dirs)
            got = _side(wb, issue, test_dirs, timeout)
            if cache is not None:
                cache[key] = got
        overlay(base, pr, wp, test_dirs)
        sides = {"base": got if cache is None else cache[key], "pr": _side(wp, issue, test_dirs, timeout)}
    prefix = f".knos.acceptance.{issue}."
    res = {}
    for side, (got, sent, canary) in sides.items():
        if got is None:
            reasons.append(f"{side}: pytest wrote no report (killed, exited early or timed out)")
            continue
        names = {k.split("::")[-1]: v for k, v in got.items()}
        if names.get(sent) != "passed":
            reasons.append(f"{side}: the sentinel test was not collected and passed (the runner was faked)")
        if names.get(canary) != "failed":
            reasons.append(f"{side}: the canary test did not fail (something makes every test pass)")
        mine = {k: v for k, v in got.items() if sent not in k and canary not in k}
        accept = {k: v for k, v in mine.items() if k.startswith(prefix)}
        res[side] = (mine, accept)
        ev[side] = {"collected": len(mine), "passed": sum(v == "passed" for v in mine.values()), "acceptance": accept}
    if len(res) == 2:
        (bm, ba), (pm, pa) = res["base"], res["pr"]
        if not pa:
            reasons.append("pr: no acceptance test ran")
        elif any(v != "passed" for v in pa.values()):
            reasons.append("pr: acceptance tests not passed: " + ", ".join(k for k, v in pa.items() if v != "passed"))
        if ba and all(v == "passed" for v in ba.values()):
            reasons.append("base: the acceptance tests already pass on the base (not fail-to-pass)")
        if len(pm) < len(bm):
            reasons.append(f"pr collected {len(pm)} tests, fewer than the base's {len(bm)}")
        broke = [k for k, v in bm.items() if v == "passed" and k not in ba and pm.get(k) != "passed"]
        if broke:
            reasons.append("pass-to-pass broken: " + ", ".join(broke))
    return verdict(h, reasons)
