"""Post a task as a buyer: one command from a written spec and a folder of hidden tests to an issue, a seal and the
exact funding command (`knos task post`, an older flow kept for the tasks already funded).

What a buyer needs before work starts, in order, and which existing piece does each:

    1. the spec           a Markdown file; it becomes the issue's description (public: the worker reads only this)
    2. the hidden tests   a folder kept OUTSIDE every repository; `knos accept init` makes a black-box one from a
                          reference program. Its hash is sealed, its content is never posted
    3. the seal           knos.referee.seal: the bundle's hash and the hash of the judging code that will judge it,
                          posted on the issue as a comment, so anyone can later check the tests that judged were these
    4. the money          `knos fund-wallet OWNER/REPO#N AMOUNT ...` (this command prints it; it never moves money
                          itself), with the fee the program takes at payout said before anyone funds
    5. the referee        `knos referee works --seal ... --hidden ...` once work is delivered

Nothing is sent without `send=True` (`--send`): then `gh` opens the issue (unless one is named) and posts the seal
comment, as the buyer's own GitHub account. The plan is returned either way, so a buyer sees every step first.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

FUND_LINE = re.compile(r"^\s*/knos\s+fund\b", re.I | re.M)


class Refused(ValueError):
    """Why a task cannot be posted as given, in one sentence that says what to do."""


def _title(spec: str) -> str:
    for line in spec.splitlines():
        if line.strip().startswith("#"):
            return line.strip().lstrip("#").strip()[:200]
    raise Refused("the spec has no heading: its first `# ...` line becomes the issue's title")


def _inside_git(path: Path) -> Path | None:
    for p in [path, *path.parents]:
        if (p / ".git").exists():
            return p
    return None


def check_bundle(bundle: Path) -> list[str]:
    """Warnings about the hidden bundle (empty when it is fine). Raises Refused when it cannot be sealed."""
    from . import judge
    if not bundle.is_dir():
        raise Refused(f"{bundle} is not a folder of hidden tests (make one with `knos accept init`, or write blackbox.py)")
    files = {p.relative_to(bundle).as_posix(): p.read_bytes() for p in bundle.rglob("*") if p.is_file()}
    if not files:
        raise Refused(f"{bundle} is empty: there is nothing to seal")
    notes = []
    repo = _inside_git(bundle.resolve())
    if repo is not None:
        notes.append(f"the hidden tests are inside the git repository {repo}: keep them outside every repository a worker "
                     "can read, or they are not hidden")
    why = judge.black_box(files, {})
    if why:
        notes.append(f"not black-box: its checks {why}. A worker's code can then fake the verdict from inside the test "
                     "process; `knos accept init` makes a black-box bundle")
    read = from_base_reads(files)
    if read:
        notes.append(f"the tests read {', '.join(read)}, which the judge takes from the BASE, never from the delivered "
                     "work: a check of what the worker puts there always sees the base's copy. Check it outside the "
                     "sealed tests, or on another file")
    return notes


# What knos.judge's overlay always takes from the base (judge.restored, runner python/command/blackbox): a sealed test
# that reads one of these sees the base's copy, whatever the work delivered. Found by V34DOG while buying, before 0.4.0.
FROM_BASE = ("pyproject.toml", "setup.cfg", "pytest.ini", "tox.ini", "conftest.py")


def from_base_reads(files: dict) -> list[str]:
    """The files of FROM_BASE a bundle's text names (`files`: relative name -> bytes)."""
    text = b"\n".join(files.values()).decode("utf-8", "replace")
    return [n for n in FROM_BASE if re.search(r"(?<![\w.-])" + re.escape(n) + r"(?![\w.-])", text)]


def trees(commit: str, patch, *, repo=".", into) -> tuple[Path, Path]:
    """The two trees a delivered patch is judged on: `base` = the repository at `commit` (git archive, no .git), `pr` =
    a copy of it with the patch applied (git apply, binary patches too). Raises Refused when the patch does not apply."""
    into = Path(into)
    base, pr = into / "base", into / "pr"
    for d in (base, pr):
        if d.exists():
            raise Refused(f"{d} already exists: give an empty folder")
    base.mkdir(parents=True)
    arc = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", commit], capture_output=True, timeout=600)
    if arc.returncode != 0:
        raise Refused(f"git archive {commit} failed in {repo}: {arc.stderr.decode('utf-8', 'replace').strip()[:300]}")
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(arc.stdout)) as tar:
        tar.extractall(base, filter="data") if hasattr(tarfile, "data_filter") else tar.extractall(base)
    shutil.copytree(base, pr, symlinks=True)
    got = subprocess.run(["git", "apply", "--whitespace=nowarn", str(Path(patch).resolve())], cwd=pr, capture_output=True,
                         timeout=600)
    if got.returncode != 0:
        raise Refused(f"the patch does not apply to {commit}: {got.stderr.decode('utf-8', 'replace').strip()[:300]}")
    return base, pr


ALREADY = "already pass on the base"      # knos.judge's words when the hidden tests do not fail on the base


def calibrate(bundle, base, reference, *, issue: str = "0", sandbox: str = "auto") -> dict:
    """Test the hidden tests before sealing them in public: judged with the cheat rules off, the unchanged `base` must
    FAIL and `reference` (the buyer's own solution, never delivered) must PASS. Either way round is a defect of the
    tests, not of any worker's work: fix the bundle and calibrate again, then post."""
    from . import referee
    bundle = Path(bundle)
    notes = check_bundle(bundle)
    sealed = referee.seal(bundle, issue=str(issue))
    got: dict[str, dict] = {}
    # The judge is fail-to-pass: judging the base against itself never passes, but its reasons say whether the hidden
    # tests already pass on the base ("already pass on the base"), which is what a buyer needs to know.
    c = referee.works(Path(base), Path(base), sealed, hidden_dir=bundle, sandbox=sandbox, scan=False)
    got["base"] = {"passed": any(ALREADY in r for r in c.reasons), "reasons": c.reasons[:3]}
    c = referee.works(Path(base), Path(reference), sealed, hidden_dir=bundle, sandbox=sandbox, scan=False)
    got["reference"] = {"passed": c.passed, "reasons": c.reasons[:3]}
    said = []
    if got["base"]["passed"]:
        said.append("the unchanged base PASSES the hidden tests: they would pay for no work (fail-to-pass is required)")
    if not got["reference"]["passed"] and not got["base"]["passed"]:
        said.append("your reference solution FAILS the hidden tests: they would refuse honest work. "
                    + "; ".join(got["reference"]["reasons"])[:400])
    return {"ok": not said, "bundle": str(bundle), "spec_hash": sealed["spec_hash"], "warnings": notes, **got,
            "said": said or ["calibrated: the base fails and your reference passes; seal and post it"]}


def fee_lines(amount_units: int, decimals: int = 6) -> list[str]:
    """What the fee is, before anyone funds: the program's fee at payout, and the decided whole bounty fee."""
    from . import fees
    r = fees.rule(None)
    fee = r.job(amount_units, decimals)
    out = [f"At payout the program takes {fees.pct(r.job_bps)} of the amount, at least {fees._money(r.job_floor)}: "
           f"{_units(fee, decimals)} here, so the worker receives {_units(amount_units - fee, decimals)}."]
    try:
        from .money import fees_config
        p = fees_config.load().platform("bounty_platform", amount_units)
        if p.get("offchain"):
            out.append(f"Knos's bounty fee is {fees.pct(int(p['rate_bps']))} ({p['status']}, config/fees.yaml): the program's fee "
                       f"is part of it; the rest, {_units(p['offchain'], decimals)}, is invoiced off chain, not taken by the program.")
    except Exception:  # noqa: BLE001 - a missing or older fee config leaves only the program's fee, which is what is charged
        pass
    return out


def _units(n: int, decimals: int) -> str:
    whole, frac = divmod(int(n), 10 ** decimals)
    return f"{whole}." + str(frac).rjust(decimals, "0")[:2]


def plan(spec_path, bundle, repo: str, amount: str, *, issue: int | None = None, days: int = 14, mint: str | None = None,
         keypair: str | None = None, checks: str = "none", reruns: int = 1, tolerance: dict | None = None,
         out_dir=None, decimals: int = 6) -> dict:
    """Every step of posting the task, nothing sent. `issue`: an issue that already holds the spec (else one is opened)."""
    from . import referee
    spec_path, bundle = Path(spec_path), Path(bundle)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
        raise Refused(f"{repo!r} is not OWNER/NAME")
    m = re.fullmatch(r"([0-9]{1,12})(?:\.([0-9]+))?", amount or "")
    if not m or len(m.group(2) or "") > decimals:
        raise Refused(f"an amount is digits, like 20 or 12.5; {amount!r} is not one")
    units = int(m.group(1)) * 10 ** decimals + int((m.group(2) or "").ljust(decimals, "0") or 0)
    spec = spec_path.read_text(encoding="utf-8")
    title = _title(spec)
    if FUND_LINE.search(spec):
        raise Refused("the spec has a `/knos fund` line: in a repository that runs the Knos workflow, opening the issue "
                      "would fund it from the faucet. Take the line out; this command funds from your own wallet")
    notes = check_bundle(bundle)
    n = issue if issue else None
    sealed = referee.seal(bundle, issue=str(n if n else 0), reruns=reruns, tolerance=tolerance)
    out_dir = Path(out_dir) if out_dir else bundle.parent
    fund = ["knos", "fund-wallet", f"{repo}#{n if n else '<issue>'}", amount, "--checks", checks, "--days", str(days),
            *(["--mint", mint] if mint else []), *(["--keypair", str(keypair)] if keypair else [])]
    return {"repo": repo, "title": title, "issue": n, "spec": str(spec_path), "bundle": str(bundle), "amount_units": units,
            "days": days, "warnings": notes, "seal": sealed, "seal_hash": referee.seal_hash(sealed),
            "seal_file": str(out_dir / f"seal-{n if n else '<issue>'}.json"), "fund_command": fund,
            "fees": fee_lines(units, decimals),
            "judge_command": ["knos", "referee", "works", "--base", "<base tree>", "--pr", "<delivered tree>", "--seal",
                              str(out_dir / f"seal-{n if n else '<issue>'}.json"), "--hidden", str(bundle)],
            "judge_patch_command": ["knos", "task", "judge", "--seal", str(out_dir / f"seal-{n if n else '<issue>'}.json"),
                                    "--hidden", str(bundle), "--commit", "<base commit>", "--patch", "<delivered patch>"]}


def comment(p: dict) -> str:
    s = p["seal"]
    return ("Sealed before work starts (`knos referee seal`). The hidden tests are kept by the buyer, outside every "
            "repository; only their hash is public.\n\n"
            f"- spec_hash (hidden tests): `{s['spec_hash']}`\n- judge_hash (the judging code that will judge): "
            f"`{s['judge_hash']}`\n- seal_hash: `{p['seal_hash']}`\n\n"
            f"Funding: `{' '.join(p['fund_command'])}`\n\n" + "\n".join(p["fees"]) + "\n")


def _gh(*args: str) -> str:
    exe = shutil.which("gh")
    if not exe:
        raise Refused("`gh` (GitHub's command line) is not installed: install it and run `gh auth login`, or post by hand")
    got = subprocess.run([exe, *args], capture_output=True, text=True, timeout=120)
    if got.returncode != 0:
        raise Refused(f"gh {args[0]} {args[1]} failed: {(got.stderr or got.stdout).strip()[:300]}")
    return got.stdout.strip()


def send(p: dict, gh: Callable[..., str] = _gh) -> dict:
    """Open the issue (unless the plan names one), seal against its number, write the seal file, post the comment.
    Money is not moved: the plan's fund_command does that, run by the buyer."""
    from . import referee
    p = dict(p)
    if not p["issue"]:
        url = gh("issue", "create", "-R", p["repo"], "--title", p["title"], "--body-file", p["spec"])
        m = re.search(r"/issues/(\d+)", url)
        if not m:
            raise Refused(f"gh did not say which issue it opened: {url[:200]}")
        p["issue"] = int(m.group(1))
        p["issue_url"] = url
    n = p["issue"]
    sealed = referee.seal(p["bundle"], issue=str(n), reruns=p["seal"]["reruns"], tolerance=p["seal"]["tolerance"])
    p.update(seal=sealed, seal_hash=referee.seal_hash(sealed))
    p["seal_file"] = p["seal_file"].replace("<issue>", str(n))
    p["fund_command"] = [x.replace("<issue>", str(n)) for x in p["fund_command"]]
    p["judge_command"] = [x.replace("<issue>", str(n)) for x in p["judge_command"]]
    if p.get("judge_patch_command"):
        p["judge_patch_command"] = [x.replace("<issue>", str(n)) for x in p["judge_patch_command"]]
    Path(p["seal_file"]).write_text(json.dumps({**sealed, "seal_hash": p["seal_hash"]}, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    p["comment_url"] = gh("issue", "comment", str(n), "-R", p["repo"], "--body", comment(p))
    p["sent"] = True
    return p


def lines(p: dict) -> list[str]:
    out = [f"Task: {p['title']}", f"Repository: {p['repo']}" + (f", issue #{p['issue']}" if p["issue"] else ", a new issue"),
           f"Hidden tests: {p['bundle']} (sealed: spec_hash {p['seal']['spec_hash'][:16]}..., judge_hash {p['seal']['judge_hash'][:16]}...)"]
    out += [f"Warning: {w}" for w in p["warnings"]]
    out += ["", "Steps:"]
    if not p.get("sent"):
        out.append(f"  1. gh issue create -R {p['repo']} --title \"{p['title']}\" --body-file {p['spec']}"
                   if not p["issue"] else f"  1. the spec is on issue #{p['issue']}")
        out.append(f"  2. seal against the issue's number and post the seal as a comment (written to {p['seal_file']})")
    else:
        out.append(f"  1. issue {p.get('issue_url') or '#' + str(p['issue'])}: done")
        out.append(f"  2. seal {p['seal_file']} and comment {p.get('comment_url', '')}: done")
    out.append("  3. fund it from your wallet (this command never moves money): " + " ".join(p["fund_command"]))
    out += [f"     {x}" for x in p["fees"]]
    out.append("  4. when work is delivered, judge it: " + " ".join(p["judge_command"]))
    if p.get("judge_patch_command"):
        out.append("     work delivered as a patch: " + " ".join(p["judge_patch_command"]))
    if not p.get("sent"):
        out.append("  Before --send, test your hidden tests: knos task calibrate --tests " + p["bundle"]
                   + " --base <base tree> --reference <your own solution>")
        out += ["", "Nothing was sent. With --send, gh opens the issue and posts the seal as your account."]
    return out
