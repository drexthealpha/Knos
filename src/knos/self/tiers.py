"""The three tiers of tests, run by the referee from main on a candidate's tree (and on its parent's, to compare).

    public   the target's public tests (in the candidate's own tree, which agents read)
    sealed   the hidden bundle (sha256 in targets.yml, kept outside the repository): its metric script measures the
             parent and the candidate, its tests judge the candidate; both run twice and must agree. What leaves this
             module for an agent is pass/fail; the counts and the metric go to the public log; no test's text, name
             or output ever does (the logs are deleted with the temporary folder).
    audit    a second hidden bundle, never used to decide a merge: `knos self audit` runs it on accepted versions when
             asked, to catch work that fits the sealed tests and nothing else.

Every run of candidate code (and of the parent's, to compare) goes through the loop's jail: a clean environment with
no token and no secret, a new network namespace (no network) and a new mount namespace in which the loop's state
(the trusted referee checkout, the archive, the record, the runs, the other bundles), the wallet folders and the
other tree are covered by empty, unreadable mounts and the repository's .git is read-only; then it runs as
KNOS_SELF_SANDBOX_USER (a separate account, when the founder makes one) or as the operator. It needs `sudo -n
unshare`; without it the loop refuses to judge (fail closed) unless `--sandbox none` is asked for explicitly.
What the jail does not stop: candidate code runs in the same process as the hidden tests it is judged by, so it can
read them while they run (Gate's limit too); as the operator's own user it can read what is not masked.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ..gate import sealed as _sealed

JUDGING = ("judge.py", "referee", "cheats")


def tree_judge_hash(tree) -> str:
    """knos.referee.judge_hash() of the checkout `tree` (its src/knos), computed by reading files only: the same
    value an install running from that tree reports, without importing any of it."""
    knos = Path(tree) / "src" / "knos"
    files: list[tuple[str, Path]] = []
    for name in JUDGING:
        p = knos / name
        if p.is_file():
            files.append((name, p))
        elif p.is_dir():
            files += [(q.relative_to(knos).as_posix(), q) for q in p.rglob("*.py") if "__pycache__" not in q.parts]
    if not files:
        raise ValueError(f"no judging code under {knos}")
    lines = "".join(n + "\0" + hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() + "\n" for n, p in sorted(files))
    return hashlib.sha256(lines.encode()).hexdigest()


def bundle_sha(bundle: bytes) -> str:
    return _sealed.seal(bundle)


def pack(folder) -> bytes:
    return _sealed.pack(folder)


def unpack(bundle_file, sha256: str, into) -> list[str]:
    """The hidden bundle into `into`, refused (gate.sealed.Refused) unless its sha256 is the one targets.yml holds."""
    return _sealed.unpack(Path(bundle_file).read_bytes(), into, sha256)


def tree_loop_hash(tree) -> str:
    """sha256 over everything that judges or runs the loop in `tree`: the judging code plus Gate's runner and the
    loop itself (knos/gate, knos/self). A referee change that touches only the runner or the loop still changes it."""
    knos = Path(tree) / "src" / "knos"
    files = [(q.relative_to(knos).as_posix(), q) for name in LOOP_CODE for q in
             ([knos / name] if (knos / name).is_file() else sorted((knos / name).rglob("*.py")) if (knos / name).is_dir() else [])
             if "__pycache__" not in q.parts]
    if not files:
        raise ValueError(f"no loop code under {knos}")
    lines = "".join(n + "\0" + hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() + "\n" for n, p in sorted(files))
    return hashlib.sha256(lines.encode()).hexdigest()


LOOP_CODE = JUDGING + ("gate", "self")

# ---- the jail -----------------------------------------------------------------------------------------------------
# set by the judge from the loop's request: paths no candidate run may read (`mask`), paths it may read and never
# write (`ro`), and the trees of one judgment (each run masks the trees it is not running)
JAIL: dict = {"mask": [], "ro": [], "trees": []}
_PROBE: dict = {}


class NoSandbox(RuntimeError):
    pass


def configure(mask=(), ro=(), trees=()) -> None:
    JAIL.update(mask=[str(p) for p in mask], ro=[str(p) for p in ro], trees=[str(p) for p in trees])


def default_mask() -> list[str]:
    """Key and wallet folders no candidate run may read: the Solana CLI's, plus every folder in KNOS_SELF_MASK (':'-separated;
    the operator lists the payout wallet's and any other key folder of the machine there)."""
    home = Path.home()
    out = [home / ".config" / "solana"]
    out += [Path(p) for p in os.environ.get("KNOS_SELF_MASK", "").split(":") if p]
    return [str(p) for p in out]


def jail_available() -> bool:
    if "ok" not in _PROBE:
        try:
            _PROBE["ok"] = bool(shutil.which("sudo") and shutil.which("unshare")) and subprocess.run(
                ["sudo", "-n", "unshare", "--net", "--mount", "true"], capture_output=True, timeout=30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _PROBE["ok"] = False
    return _PROBE["ok"]


def _prefix(env: dict, sandbox: str, tree) -> tuple[list[str], str]:
    if sandbox == "none":
        return [], "none"
    if not jail_available():
        raise NoSandbox("this machine cannot make the loop's jail (sudo -n unshare --net --mount): candidate code "
                        "would run with the operator's reach; refused (use --sandbox none only where that is acceptable)")
    import getpass
    user = os.environ.get("KNOS_SELF_SANDBOX_USER") or getpass.getuser()
    q = shlex.quote
    masks = list(JAIL["mask"]) + [t for t in JAIL["trees"] if Path(t).resolve() != Path(tree).resolve()]
    steps = []
    for m in masks:
        steps.append(f"if [ -d {q(m)} ]; then mount -t tmpfs -o size=64k,mode=000 knos-self-mask {q(m)}; "
                     f"elif [ -f {q(m)} ]; then mount --bind /dev/null {q(m)}; fi")
    for r in JAIL["ro"]:
        steps.append(f"if [ -e {q(r)} ]; then mount --bind {q(r)} {q(r)} && mount -o remount,bind,ro {q(r)}; fi")
    assigns = " ".join(q(f"{k}={v}") for k, v in sorted(env.items()))
    script = "set -e; " + "; ".join(steps + [f'exec sudo -n -u {q(user)} -- env -i {assigns} "$@"'])
    kind = "nonet,mount" + (",user" if os.environ.get("KNOS_SELF_SANDBOX_USER") else ",operator")
    return ["sudo", "-n", "unshare", "--net", "--mount", "--", "sh", "-c", script, "knos-self-jail"], kind


def _run(argv: list[str], cwd, env: dict, sandbox: str, tree, timeout: int, out_file=None):
    """argv in the jail. Returns (exit code, stdout text, sandbox kind, seconds)."""
    base = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL") if k in os.environ}
    base.update(env)
    prefix, kind = _prefix(base, sandbox, tree)
    t0 = time.monotonic()
    try:
        done = subprocess.run(prefix + argv, cwd=str(cwd), env=base, capture_output=True,
                              text=True, timeout=timeout)
        code, text = done.returncode, done.stdout
    except subprocess.TimeoutExpired:
        code, text = -9, ""
    return code, text, kind, round(time.monotonic() - t0, 2)


def _env(tree) -> dict:
    home = Path(tempfile.gettempdir()) / "knos-self-home"
    return {"PYTHONPATH": str(Path(tree) / "src"), "KNOS_SELF_TREE": str(tree), "PYTHONDONTWRITEBYTECODE": "1",
            "KNOS_HOME": str(home), "HOME": str(home), "CI": "true"}


def _junit(path: Path) -> dict:
    """Counts from a JUnit report, read without following a link the run may have planted."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return _sealed.counts(None)
    with os.fdopen(fd, "rb") as f:
        data = f.read(20_000_001)
    tmp = Path(tempfile.mkdtemp(prefix="knos-self-junit-"))
    try:
        (tmp / "j.xml").write_bytes(data)
        return _sealed.counts(tmp / "j.xml")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def pytest(tests, tree, work, *, rootdir=None, timeout: int = 900, sandbox: str = "auto", seed: str | None = None) -> dict:
    """pytest on `tests` in the jail, the tree's src first on the path, cwd = the tree. Returns the counts (total,
    passed, failed, errors, skipped) plus exit, sandbox, seconds and `passed_all` (counts all pass AND exit 0)."""
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    if os.environ.get("KNOS_SELF_SANDBOX_USER") and sandbox != "none":
        os.chmod(work, 0o1777)           # a separate account writes its report here, and nothing else of ours
    junit = work / "junit.xml"
    argv = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", f"--junitxml={junit}", *map(str, tests)]
    if rootdir is not None:
        ini = Path(rootdir) / "pytest.ini"
        if not ini.exists():
            ini.write_text("[pytest]\n", encoding="utf-8")
        argv += ["--rootdir", str(rootdir), "-c", str(ini)]
    extra = _env(tree)
    Path(extra["HOME"]).mkdir(parents=True, exist_ok=True)
    if seed is not None:
        extra["PYTHONHASHSEED"] = seed
    code, _text, kind, secs = _run(argv, tree, extra, sandbox, tree, timeout)
    got = _junit(junit)
    got.update({"exit": code, "sandbox": kind, "seconds": secs, "timed_out": code == -9})
    got["passed_all"] = _sealed.passed(got) and code == 0
    return got


def metric(script, tree, *, timeout: int = 300, sandbox: str = "auto") -> dict:
    """The sealed metric script on one tree, in the jail: `python SCRIPT TREE` prints one JSON line {"metric": number}.
    The script is the founder's (sealed by hash); it measures the tree in a child process of its own."""
    env = _env(tree)
    env.pop("PYTHONPATH", None)          # the metric script itself imports nothing of the tree
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    code, text, kind, secs = _run([sys.executable, str(script), str(tree)], Path(script).parent, env, sandbox, tree, timeout)
    if code == -9:
        return {"ok": False, "metric": None, "error": "timed out", "seconds": secs, "sandbox": kind}
    out = {"ok": False, "metric": None, "seconds": secs, "exit": code, "sandbox": kind}
    for line in reversed(text.strip().splitlines()):
        try:
            got = json.loads(line)
        except ValueError:
            continue
        if isinstance(got, dict) and isinstance(got.get("metric"), (int, float)) and not isinstance(got.get("metric"), bool):
            out.update({"ok": code == 0 and bool(got.get("ok", True)), "metric": got["metric"],
                        "detail": {k: v for k, v in got.items() if k in ("modules", "baseline", "unit")}})
            break
    if out["metric"] is None:
        out["error"] = "the metric script printed no metric"
    return out


def sealed_tier(bundle_file, sha256: str, spec: dict, parent_dir, candidate_dir, *, sandbox: str = "auto",
                reruns: int = 1, tolerance_abs: float = 0.0) -> dict:
    """The sealed tier: metric on parent and candidate (the candidate twice), hidden tests on the candidate (twice).
    Refused bundle -> {"passed": False, "error": ...}."""
    from ..referee import rerun_agrees
    tmp = Path(tempfile.mkdtemp(prefix="knos-self-sealed-"))
    try:
        bundle = tmp / "bundle"
        try:
            unpack(bundle_file, sha256, bundle)
        except (_sealed.Refused, OSError) as why:
            return {"passed": False, "error": f"sealed bundle: {why}"}
        out: dict = {"bundle_sha256": sha256}
        script = bundle / spec.get("metric", "metric.py")
        if script.is_file():
            out["metric_parent"] = metric(script, parent_dir, sandbox=sandbox)
            first = metric(script, candidate_dir, sandbox=sandbox)
            runs = [first] + [metric(script, candidate_dir, sandbox=sandbox) for _ in range(max(0, reruns))]
            out["metric_candidate"] = first
            out["metric_reruns"] = [r.get("metric") for r in runs]
        tests = bundle / spec.get("tests", "test_sealed.py")
        first_t = pytest([tests], candidate_dir, tmp / "t1", rootdir=bundle, sandbox=sandbox)
        again = [pytest([tests], candidate_dir, tmp / f"t{i + 2}", rootdir=bundle, sandbox=sandbox, seed=str(i + 1))
                 for i in range(max(0, reruns))]
        out["tests"] = _slim(first_t)
        agree = True
        differ: list[str] = []
        for a in again:
            ok, w = rerun_agrees({"passed": first_t["passed_all"]}, {"passed": a["passed_all"]})
            agree, differ = agree and ok, differ + w
        if "metric_candidate" in out:
            vals = out["metric_reruns"]
            for v in vals[1:]:
                ok, w = rerun_agrees({"passed": True, "metric": vals[0]}, {"passed": True, "metric": v},
                                     {"abs": tolerance_abs, "rel": 0.0})
                agree, differ = agree and ok, differ + w
        out["rerun_agrees"] = agree
        out["rerun_reasons"] = differ
        metric_ok = "metric_candidate" not in out or (out["metric_candidate"]["ok"] and out["metric_parent"]["ok"])
        out["passed"] = bool(first_t["passed_all"] and agree and metric_ok)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def audit_tier(bundle_file, sha256: str, spec: dict, tree, *, sandbox: str = "auto") -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="knos-self-audit-"))
    try:
        bundle = tmp / "bundle"
        try:
            unpack(bundle_file, sha256, bundle)
        except (_sealed.Refused, OSError) as why:
            return {"passed": False, "error": f"audit bundle: {why}"}
        got = pytest([bundle / spec.get("tests", "test_audit.py")], tree, tmp / "a", rootdir=bundle, sandbox=sandbox)
        return {"passed": got["passed_all"], "tests": _slim(got), "bundle_sha256": sha256}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def public_tier(tests, tree, *, sandbox: str = "auto") -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="knos-self-public-"))
    try:
        got = pytest([Path(tree) / t for t in tests], tree, tmp / "p", sandbox=sandbox)
        return {"passed": got["passed_all"], "tests": _slim(got), "files": list(tests)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def shadow_tier(tests, parent_dir, candidate_dir, *, sandbox: str = "auto") -> dict:
    """The shadow stage for a product change: the target's neighbouring tests, file by file, on the parent and on the
    candidate side by side. A file that passes on the parent and fails on the candidate is a disagreement."""
    rows, disagree = [], []
    for t in tests:
        if not (Path(candidate_dir) / t).is_file() or not (Path(parent_dir) / t).is_file():
            continue
        p = public_tier([t], parent_dir, sandbox=sandbox)
        c = public_tier([t], candidate_dir, sandbox=sandbox)
        rows.append({"file": t, "parent": p["passed"], "candidate": c["passed"], "tests": c["tests"].get("total")})
        if p["passed"] and not c["passed"]:
            disagree.append(t)
    return {"passed": not disagree, "files": rows, "disagreements": disagree}


def _slim(c: dict) -> dict:
    return {k: c[k] for k in ("total", "passed", "failed", "errors", "skipped", "sandbox", "seconds", "timed_out") if k in c}
