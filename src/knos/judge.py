"""The judge: the check on a pull request. It decides whether a pull request may be paid, and the pull request cannot
weaken what it is judged by.

Two verdicts:

    gate(...)    every pull request, running NO pull request code. The free check: the repository's own rules
                 (CONTRIBUTING.md, read from the base and kept in Sibyl), what this repository's history made required
                 (tampering caught before, also Sibyl), and the pull request's own words: a description saying "tests
                 pass" or "CI is green" is checked against GitHub's record of the commit. For a bounty's pull request
                 also what money moves on: the bounty's terms (knos.terms.accepted: every funded check passed at
                 that commit and nothing out of scope changed) and who is paid (knos.who). A description's words can
                 be found false; they never stand in for a check.
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
weakness either. For everything else there is the default mode, which pays on a maintainer's merge instead (and, for
a bounty funded on the first deployment, the review window in which its funder can veto a tests-mode payment).

So on the second deployment, which has no veto, a bounty is paid by its acceptance checks alone only when the bundle
is black-box by a mechanical test, `black_box`: an entry file blackbox / blackbox.sh / blackbox.py at its top that
names KNOS_RUN, no file that names KNOS_TREE, and no other runner set in .knos/proof.toml. knos.flow funds any other
bundle on the merge and says why, and refuses to sign a tests-mode proof for one.
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

from .terms import ours as _ours   # a check run that is Knos's own: never evidence about the pull request
from .terms import state_of, status_state, together
from .who import excluded, payee  # noqa: F401 - payee is this module's too: `knos proof payee` and callers use judge.payee

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


# The two things Knos ever rewrites or removes on GitHub, and nothing else, whoever calls `github`.
_WRITES = {"PATCH": r"repos/[^/]+/[^/]+/issues/comments/\d+",     # the text of a comment: Knos's own review comment
           "DELETE": r"repos/[^/]+/[^/]+/issues/\d+/assignees"}   # an issue's assignee: `/knos release`, a lapsed take


def github(path: str, data: dict | None = None, method: str | None = None, *, token: str | None = None):
    """GET api.github.com/<path>; with `data`, POST it there as JSON (GH_TOKEN or GITHUB_TOKEN is sent when set, and
    the API version these calls were written against; `token`, when given, is sent in their place: an attestor reads
    another repository with a token of its own). `method` PATCH edits a comment and DELETE takes an assignee
    off an issue, with `data` as the body: any other path is refused before anything is sent, and so is any other
    method. Raises OSError when GitHub says no or does not answer in JSON. An empty answer is None."""
    import urllib.request
    if method not in (None, "GET", "POST") and not re.fullmatch(_WRITES.get(method, r"(?!)"), path):
        raise ValueError(f"Knos does not send {method} to {path}")
    req = urllib.request.Request(f"https://api.github.com/{path}", data=None if data is None else json.dumps(data).encode(),
                                 method=method,
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "knos",
                                          "X-GitHub-Api-Version": "2022-11-28",
                                          **({} if data is None else {"Content-Type": "application/json"})})
    tok = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - api.github.com
        raw = resp.read()
    try:
        return json.loads(raw) if raw.strip() else None
    except ValueError:
        raise OSError(f"GitHub's answer for {path} was not JSON") from None


def assignment_check(issue: dict | None, pull: dict, paid: dict, events: list | None = None,
                     terms: dict | None = None, now: float | None = None) -> list[str]:
    """An issue someone is assigned to is theirs: a bounty on it is paid only for a pull request by an assignee (or by
    the agent an assignee ran). An unassigned issue is open to anyone, and so is one whose `/knos take` has lapsed
    (knos.who.reservation tells that from the issue's `events`, the bounty's `terms` and `now`). `payee` given the
    issue has already applied this; it is here for a payee that was worked out from the pull request alone."""
    why = excluded(issue, pull, paid, events, terms, now)
    return [f"assigned: {why}"] if why else []


def claim_report(body: str, check_runs: list[dict] | None, strict: bool = False, statuses: list[dict] | None = None) -> dict:
    """What the description claims against GitHub's record of its head commit, in full:

        said         what it claims ("tests pass", "CI is green"); empty when it claims neither
        state        none (no claim), true (a check passed and none failed), false (a check failed), unverified
        violations   what the gate refuses: a claim a failed check contradicts; and with `strict` (the merged commit)
                     also a claim that cannot be borne out: checks not finished, no check run at all, none that
                     passed, or GitHub unreadable
        unverified   the same sentences when not strict: reported, not held against the pull request
        facts        what is plainly so whatever was claimed, e.g. "checks failing: lint, test"
        checks       {name: passed | failed | skipped | pending}, the states knos.terms uses; None when unreadable

    `check_runs` is the commit's check runs (None: GitHub could not be read), `statuses` its commit statuses when the
    caller read them. Knos's own jobs are not evidence. A description that claims nothing is never a false claim,
    whatever failed: whether funded work is paid is decided by the bounty's terms, not by what was or was not said."""
    from .proof import claims
    kinds = claims.read(body or "").kinds & {"tests", "ci"}
    said = " and ".join(sorted({"tests": "tests pass", "ci": "CI is green"}[k] for k in kinds))
    out: dict = {"said": said, "state": "none", "violations": [], "unverified": [], "facts": [], "checks": None}

    def unproven(why: str, again: str = "") -> None:
        out["state"] = "unverified"
        out["violations" if strict else "unverified"].append(f"claim: {why}{again}" if strict else why)

    if check_runs is None:
        if kinds:
            unproven(f"the description says {said}, and GitHub's record of the head commit could not be read", "; run this job again")
        return out
    found: dict[str, list[str]] = {}
    for r in check_runs:
        if not _ours(r):
            found.setdefault(str(r.get("name", "?")), []).append(state_of(r))
    for s in statuses or []:
        found.setdefault(str(s.get("context", "?")), []).append(status_state(s))
    out["checks"] = {name: together(states) for name, states in sorted(found.items())}
    failed, running, passed = (sorted(n for n, s in out["checks"].items() if s == want) for want in ("failed", "pending", "passed"))
    if failed:
        out["facts"].append("checks failing: " + ", ".join(failed[:6]))
    if not kinds:
        return out
    if failed:
        out["state"] = "false"
        out["violations"].append(f"claim: the description says {said}, but these checks failed at the head commit: {', '.join(failed[:6])}")
    elif running:
        unproven(f"the description says {said}, and these checks have not finished at the head commit: {', '.join(running[:6])}",
                 "; run this job again when they have")
    elif not out["checks"]:
        unproven(f"the description claims {said}; GitHub has no check runs for this commit")
    elif not passed:
        unproven(f"the description claims {said}; no check passed at this commit (skipped: {', '.join(sorted(out['checks'])[:6])})")
    else:
        out["state"] = "true"
    return out


def claim_check(body: str, check_runs: list[dict] | None, strict: bool = False) -> list[str]:
    """The free check's verdict on the description's claims: what `claim_report` refuses. A claim of passing tests or
    green CI is refused when a finished check failed. Before a merge, a claim that cannot be checked yet (checks
    unfinished, none at all, GitHub unreadable) is not held against the pull request. `strict` (the merged commit):
    it is refused too, until it can be checked."""
    return claim_report(body, check_runs, strict)["violations"]


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
         issue_data: dict | None = None, paid: dict | None = None, strict: bool = False, terms: dict | None = None,
         statuses: list[dict] | None = None, changed: list | None = None, funded=(), events: list | None = None,
         now: float | None = None) -> dict:
    """The verdict that needs no pull request code. {"passed", "checks_hash" (""), "reasons", "evidence"}. A rule
    violation is learned: that check is then required for every later pull request to this repo or by this agent.
    With `pull` (the pull request) and `paid` (payee(...)), a bounty's pull request must also pay someone, and
    respect the issue's assignment (`issue_data`; with the issue's `events` and `now`, a `/knos take` that has
    lapsed holds nothing, exactly as payee decided it).

    With `terms` (the bounty's, knos.terms.parse) the pull request must also meet them at this commit: every funded
    check `passed` in `check_runs` and `statuses` (knos.terms.head_checks), and no file in `changed` out of scope.
    `funded` (issue numbers with a bounty) adds a note when the description mentions one without closing it.

    `passed` is the check's verdict: everything above. What a payment is decided on is narrower and is in the
    evidence: "accepted" (the terms alone; None without terms) and "payable" (the terms are met and someone is
    paid; None unless both were given). A description's words and the repository's rules are in neither."""
    from .proof import history
    base = Path(base_dir)
    required, contributing, violations = _rule_violations(base, diff_text, store, repo, agent)
    for kind in sorted({x.rule["kind"] for x in violations}):
        first = next(x for x in violations if x.rule["kind"] == kind)
        history.learn_tamper(store, repo, agent, f"rule:{kind}", str(first))
    reasons = [f"repo rule: {x}" for x in violations]
    report = claim_report(body, check_runs, strict, statuses)
    false_claims = report["violations"]
    if report["state"] == "false":     # a claim that could not be checked is not a lie
        history.learn_tamper(store, repo, agent, "false-claim", false_claims[0])
    reasons += false_claims
    bought: dict = {}
    if terms is not None:
        from . import terms as bounty
        found = bounty.evidence(terms, check_runs, statuses)
        ok, why = bounty.accepted(terms, found, changed)
        reasons += [f"terms: {w}" for w in why]
        bought = {"terms_hash": bounty.terms_hash(terms), "checks": found, "accepted": ok}
    if pull is not None and paid is not None:
        who = [f"{paid.get('kind', 'payee')}: {paid['why']}" + (f". {paid['fix']}" if paid.get("fix") else "")] \
            if not paid.get("id") else assignment_check(issue_data, pull, paid, events, terms, now)
        reasons += who
        if bought:
            bought["payable"] = bought["accepted"] and not who
    from . import closing
    note = closing.mention_note(closing.mentions_without_closing(body, funded, repo)) if funded else ""
    ev = {"issue": str(issue), "mode": "merge", **({"payee": paid} if paid is not None else {}), "repo_rules": [str(x) for x in violations],
          "rules_known": len(contributing), "claims": false_claims, "unverified": report["unverified"], "facts": report["facts"],
          "notes": [note] if note else [], "accepted": None, "payable": None, **bought,
          "checks_seen": None if check_runs is None else len(check_runs), "required_by_history": required,
          "learned": sorted(history.tamper_checks_required(store, repo, agent))}
    return {"passed": not reasons, "checks_hash": "", "reasons": reasons, "evidence": ev}


def _funded_bundle(base: Path, issue: str, terms: dict) -> str:
    """Why the acceptance checks on the base are not what these terms bought; empty when they are."""
    if terms["mode"] != "tests":
        return "this bounty is paid on the merge: it was not funded with acceptance checks"
    try:
        have = checks_hash(base / ".knos" / "acceptance" / issue) if re.fullmatch(r"[A-Za-z0-9._-]+", issue) else ""
    except ValueError:
        have = ""
    return "" if have == terms["accept"] else (f"the acceptance checks in .knos/acceptance/{issue} on the base are not the "
                                               "ones this bounty was funded with")


def judge_with_rules(base_dir, pr_dir, cfg: dict, changed: list[str] | None, diff_text: str | None, store,
                     repo: str | None = None, agent: str | None = None, body: str = "",
                     check_runs: list[dict] | None = None, setup: str | None = None, sandbox: str = "auto",
                     pull: dict | None = None, issue_data: dict | None = None, paid: dict | None = None,
                     strict: bool = False, terms: dict | None = None, statuses: list[dict] | None = None,
                     events: list | None = None, now: float | None = None) -> dict:
    """gate() first; only a pull request that clears it has its code run by judge(). A protected-path refusal is
    learned the same way a rule violation is.

    With `terms` (a bounty funded in tests mode) the gate holds the pull request to them, and the acceptance checks
    on the base must be the ones that were funded (the terms' `accept`). What a payment is decided on is in the
    evidence, as for gate(): "accepted" (the funded checks passed at this commit, nothing out of scope changed, and
    the funded acceptance checks pass) and "payable" (accepted, and someone is paid). So that a description's words
    and the repository's rules enter neither, the acceptance checks are run whenever the rest of the terms is met,
    also when the gate refused the pull request for another reason; `passed` still needs both."""
    from .proof import history
    base = Path(base_dir)
    issue = str(cfg.get("issue", ""))
    scope = changed_files(base, Path(pr_dir)) if terms is not None and changed is None else changed
    g = gate(base, diff_text, store, repo, agent, body, check_runs, issue, pull, issue_data, paid, strict, terms,
             statuses, scope, (), events, now)
    ev = g["evidence"]
    someone = ev["payable"] if ev["accepted"] else None        # with the terms met, `payable` says whether someone is paid
    if terms is not None:
        why = _funded_bundle(base, issue, terms)
        if why:
            g["reasons"].append(f"terms: {why}")
            g["passed"], ev["accepted"] = False, False
        if not ev["accepted"] and ev["payable"] is not None:
            ev["payable"] = False
    if not (g["passed"] if terms is None else ev["accepted"]):
        try:
            g["checks_hash"] = checks_hash(base / ".knos" / "acceptance" / issue)
        except ValueError:
            pass
        ev["mode"] = "tests"
        return g
    v = judge(base_dir, pr_dir, cfg, changed, setup=setup, sandbox=sandbox)
    bad = [r for r in v["reasons"] if r.startswith("touches protected path")]
    if bad:
        history.learn_tamper(store, repo, agent, "protected-path", bad[0])
    v["evidence"]["mode"] = "tests"
    if paid is not None:
        v["evidence"]["payee"] = paid
    if ev["rules_known"]:
        v["evidence"]["repo_rules"] = ev["repo_rules"]
    for key in ("unverified", "facts", "notes"):
        v["evidence"][key] = ev[key]
    if terms is not None:
        met = v["passed"]
        v["evidence"].update(terms_hash=ev["terms_hash"], checks=ev["checks"], claims=ev["claims"], accepted=met,
                             payable=None if someone is None else bool(someone and met))
        v["reasons"] = g["reasons"] + v["reasons"]
        v["passed"] = not v["reasons"]
    v["evidence"]["required_by_history"] = ev["required_by_history"]
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


BLACKBOX_ENTRY = ("blackbox", "blackbox.sh", "blackbox.py")


def black_box(files: dict, cfg: dict | None = None) -> str:
    """Why an acceptance bundle is not black-box, in words that finish "its checks ..."; "" when it is.

    This is the mechanical test that decides whether a bounty may be paid by its acceptance checks alone, with no
    merge. docs/TAMPER.md measures why it matters: checks that import the submission into the judge's process were
    fooled by pull requests that patch the test runner from inside or answer the fixed examples; black-box checks
    (the submission runs as a separate process and only what it prints is compared) were fooled by none. knos.flow
    asks this when a bounty is funded (a bundle that fails it is funded on the merge) and again before the proof of
    such a bounty is signed.

    `files`: the bundle, {path inside .knos/acceptance/<issue>/: content}. `cfg`: the same commit's
    .knos/proof.toml, parsed ({} or None when there is none). A bundle is black-box when all three hold:

      1. .knos/proof.toml does not send it to another runner: no `runner` (or `[judge] runner`) other than
         "blackbox", and with none named no `[judge] run` command. Those are what `runner_of` reads first.
      2. Its top level holds an entry file named blackbox, blackbox.sh or blackbox.py. The blackbox runner copies
         the bundle out of the tree and runs that file as the judge, so no test runner shares a process with the
         pull request's code.
      3. The entry names KNOS_RUN, and no file of the bundle names KNOS_TREE. "$KNOS_RUN <command>" runs a command
         in the pull request's tree inside the sandbox: the one way a check gets an answer from that code without
         loading it. KNOS_TREE is the tree's path: a check that opens the tree itself can import the submission
         into its own process, which is the weakness the runner exists to close.

    The test reads names and text; it does not prove what a check computes. It keeps a funder from paying on a
    bundle that is fooled by construction, and the funder still writes the check: generated inputs, compared with a
    reference of its own, are what an implementation cannot special-case."""
    cfg = cfg if isinstance(cfg, dict) else {}
    section = cfg.get("judge") if isinstance(cfg.get("judge"), dict) else {}
    if cfg.get("_error"):
        return "cannot be checked: `.knos/proof.toml` is not valid TOML"
    named = cfg.get("runner") or section.get("runner")
    if named and named != "blackbox":
        return f"share a process with the pull request's code (runner `{_word(named)}`)"
    if not named and section.get("run"):
        return "are a `[judge] run` command, run inside the pull request's tree"
    entry = next((n for n in BLACKBOX_ENTRY if n in files), None)
    if entry is None:
        return "load the pull request's code into the process that judges it"
    text = lambda raw: raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)  # noqa: E731
    if "KNOS_RUN" not in text(files[entry]):
        return "never run the pull request's code through `$KNOS_RUN`"
    if any("KNOS_TREE" in text(raw) for raw in files.values()):
        return "open the pull request's tree themselves (`KNOS_TREE`)"
    return ""


def _word(value) -> str:
    return re.sub(r"[`\r\n]", "'", str(value))[:40]


def proof_config(text: str | None) -> dict:
    """A .knos/proof.toml's text, parsed as knos.proof.engine.load parses the file: {} for none, {"_error": ...} for
    one that is not TOML."""
    if not text:
        return {}
    try:
        got = tomllib.loads(text)
    except Exception:  # noqa: BLE001 - said by whoever asked, not raised
        return {"_error": "unreadable .knos/proof.toml"}
    return got if isinstance(got, dict) else {}


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
    if any(n in BLACKBOX_ENTRY for n in names):
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


_RUBY_LINE = re.compile(r"^(\S+#\S+) = [\d.]+ s = ([.FESB])\r?$", re.M)   # ruby on Windows ends each line with \r\n


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


# $KNOS_RUN on Windows, which runs no "#!/bin/sh" file. It is a program, knos-run.exe: the venv launcher that ships with
# Python, beside a pyvenv.cfg naming the judge's interpreter and a .pth file that runs this relay before Python reads
# its arguments. So the command's arguments reach the relay as the check gave them: a .cmd would hand them to cmd.exe,
# which splits them at & and |, redirects at < and >, and expands %VAR%. The relay runs the command in the tree (WORK,
# written in by the judge) inside a job object, so the whole tree it starts ends with it: a check that stops
# "$KNOS_RUN ..." at its time limit ends knos-run.exe, and with it the relay, whose job then ends every process the
# command started (one left running would hold the check's pipe open past the limit, and outlive the judge).
# When there is no launcher, or it does not start the relay, knos-run.cmd runs the same relay (LAUNCHED = False).
_WINDOWS_RUN = '''import ctypes
import os
import subprocess
import sys
import threading
from ctypes import wintypes

kernel = ctypes.WinDLL("kernel32")
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
kernel.CreateJobObjectW.restype = wintypes.HANDLE
kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
kernel.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
kernel.GetCurrentProcess.restype = wintypes.HANDLE


class _Limits(ctypes.Structure):        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
                ("IoInfo", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _end(code):
    for f in (sys.stdout, sys.stderr):
        try:
            f.flush()
        except (AttributeError, OSError, ValueError):
            pass
    os._exit(code)


def _resolve(name):
    """The program a bare command name runs: found on PATH only, as `exec` finds it on Linux, never in the tree (Windows
    looks in the current directory first, so a git.exe the pull request commits would run in place of Git). python3 is
    the judge's own interpreter: Windows ships no python3.exe, and the python3 on PATH is often the Microsoft Store's
    stub, which runs nothing. So is python when the only one on PATH is that stub."""
    if os.path.dirname(name) or os.path.splitdrive(name)[0]:
        return name
    low = name.lower()
    stem = low[:-4] if low.endswith(".exe") else low
    python = getattr(sys, "_base_executable", "") or sys.executable
    if stem == "python3":
        return python
    exts = [e for e in os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]
    names = [name] if os.path.splitext(low)[1] in [e.lower() for e in exts] else [name + e for e in exts]
    for d in os.environ.get("PATH", "").split(os.pathsep):
        d = d.strip().strip('"')
        if not d or not os.path.isabs(d):
            continue                     # a relative entry ("." among them) names the tree
        for n in names:
            path = os.path.join(d, n)
            if os.path.isfile(path):
                if stem == "python" and os.path.basename(os.path.normpath(d)).lower() == "windowsapps":
                    return python
                return path
    return python if stem == "python" else None


def main(argv):
    if argv == ["knos-run:probe"]:
        print("knos-run:ready")
        _end(0)
    parent = kernel.OpenProcess(0x00100000, False, os.getppid())    # SYNCHRONIZE: to wait for $KNOS_RUN to end
    if not parent:
        _end(126)                        # $KNOS_RUN has already been ended
    try:
        os.chdir(WORK)
    except OSError:
        _end(126)
    if not argv:
        _end(0)
    found = _resolve(argv[0])
    if not found:
        print(f"knos-run: {argv[0]}: command not found", file=sys.stderr)
        _end(127)
    job = kernel.CreateJobObjectW(None, None)
    limits = _Limits(LimitFlags=0x2000)  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: the job's last handle ends the tree
    if not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)) \\
            or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        print("knos-run: the command could not be put in a job object", file=sys.stderr)
        _end(126)
    os.environ.pop("__PYVENV_LAUNCHER__", None)     # the launcher's, for this relay only: not the command's Python
    std = []
    for fd in (0, 1, 2):
        try:
            os.fstat(fd)
            std.append(fd)
        except OSError:
            std.append(subprocess.DEVNULL)
    try:
        child = subprocess.Popen([found, *argv[1:]], stdin=std[0], stdout=std[1], stderr=std[2])
    except OSError as why:
        print(f"knos-run: {why}", file=sys.stderr)
        _end(127)

    def watch():
        kernel.WaitForSingleObject(parent, 0xFFFFFFFF)
        kernel.TerminateJobObject(job, 1)    # $KNOS_RUN was ended (the check's time limit): so is all it started
    threading.Thread(target=watch, daemon=True).start()
    _end(child.wait())


try:
    main(sys.orig_argv[1:] if LAUNCHED else sys.argv[1:])
except BaseException as why:            # in a .pth file an error would let Python go on to run argv[1] as a script
    print(f"knos-run: {why!r}", file=sys.stderr)
    _end(126)
'''


def _venv_launcher() -> Path | None:
    """The launcher Python's venv copies into a virtual environment on Windows: it runs the interpreter its pyvenv.cfg
    names with its own command line, unchanged, and ends that interpreter when it is ended (a job object of its own)."""
    import venv
    nt = Path(venv.__file__).resolve().parent / "scripts" / "nt"
    return next((nt / n for n in ("venvlauncher.exe", "python.exe") if (nt / n).is_file()), None)


def _cmd_line(python: str) -> bytes:
    """knos-run.cmd's one line, in the code page cmd.exe reads a batch file in (the console's, else the OEM one): written
    as UTF-8, a path such as C:\\Users\\José\\... is misread and the interpreter is not found. A path that code page
    cannot spell is given by its short (8.3) name."""
    import ctypes
    k = ctypes.windll.kernel32
    cp = k.GetConsoleOutputCP() or k.GetOEMCP()
    enc = "utf-8" if cp == 65001 else f"cp{cp}"
    try:
        "".encode(enc)
    except LookupError:
        enc = "mbcs"
    paths = [python]
    buf = ctypes.create_unicode_buffer(32768)
    if k.GetShortPathNameW(python, buf, len(buf)):
        paths.append(buf.value)
    for path in paths:
        line = f'@"{path.replace("%", "%%")}" -I -S "%~dp0knos-run.py" %*\r\n'
        try:
            return line.encode(enc)
        except UnicodeEncodeError:
            continue
    return line.encode(enc, "replace")


def _windows_runner(home: Path, work: Path) -> Path:
    """$KNOS_RUN on Windows, made in `home` (a folder of its own): knos-run.exe when the launcher starts the relay, else
    knos-run.cmd, which runs the relay with the interpreter itself (not a virtual environment's launcher, which would
    stand between the .cmd and the relay and outlive the .cmd)."""
    python = Path(getattr(sys, "_base_executable", "") or sys.executable)
    home.mkdir(parents=True, exist_ok=True)
    launcher = _venv_launcher()
    if launcher:
        site = home / "Lib" / "site-packages"
        site.mkdir(parents=True, exist_ok=True)
        (site / "knos_run.py").write_text(f"WORK = {str(work)!r}\nLAUNCHED = True\n" + _WINDOWS_RUN, "utf-8")
        (site / "knos_run.pth").write_text("import knos_run\n", "utf-8")
        (home / "pyvenv.cfg").write_text(f"home = {python.parent}\ninclude-system-site-packages = false\n", "utf-8")
        (home / "Scripts").mkdir(exist_ok=True)
        runner = home / "Scripts" / "knos-run.exe"
        shutil.copyfile(launcher, runner)
        try:
            probe = subprocess.run([str(runner), "knos-run:probe"], capture_output=True, timeout=60,
                                   stdin=subprocess.DEVNULL)
            if probe.returncode == 0 and probe.stdout.strip() == b"knos-run:ready":
                return runner
        except (OSError, subprocess.TimeoutExpired):
            pass
    (home / "knos-run.py").write_text(f"WORK = {str(work)!r}\nLAUNCHED = False\n" + _WINDOWS_RUN, "utf-8")
    runner = home / "knos-run.cmd"
    runner.write_bytes(_cmd_line(str(python)))
    return runner


def _blackbox(box: Box, issue: str, test_dirs, timeout: float, cfg: dict) -> Run:
    """The check that cannot be forged from inside: it runs as the judge, outside the tree, and never loads the pull
    request's code. It reaches that code only through "$KNOS_RUN <command>", which runs the command in the tree,
    inside the sandbox. The check file is the base's (the pull request cannot touch .knos/), so it is trusted the way
    the repository's own CI is. The bundle is copied out of the tree and taken out of it: what the check holds (a
    held-out set, a reference) is not readable by the code it judges. Exit 0 means done."""
    import shlex
    bundle = box.work / ".knos" / "acceptance" / issue
    private = box.root / "check"
    shutil.copytree(bundle, private)
    os.chmod(private, 0o700)
    # The bundle may hold the answers (a held-out set, a reference). The copy above is the judge's; the one in the tree
    # would be readable by the code that is being judged, so no bundle of the repository stays there.
    shutil.rmtree(box.work / ".knos" / "acceptance", ignore_errors=True)
    box.open_up()
    if os.name == "nt":
        runner = _windows_runner(box.root / "knos-run", box.work)
    else:
        argv, env = box.wrap(["sh", "-c", 'exec "$@"', "sh"], net=False)
        runner = private / "knos-run"
        runner.write_text("#!/bin/sh\n" + f"cd {shlex.quote(str(box.work))} || exit 126\n"
                          + "exec " + " ".join(shlex.quote(a) for a in argv) + ' "$@"\n', "utf-8")
    runner.chmod(0o700)
    name = next(n for n in BLACKBOX_ENTRY if (private / n).is_file())
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
