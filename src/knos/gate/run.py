"""One Gate run on one pull request: `knos gate run` (what actions/gate runs) and `run(...)` (what tests call).

    1. the config from the BASE tree (.knos/gate.yml); none there: nothing to judge
    2. outside_only and an inside author: a passing check that says it did not judge
    3. the cheat checks on the diff (knos.gate.cheatlib); a refused cheat: no test runs (the code is not trusted)
    4. the sealed hidden tests: the bundle from the secret (or a fetched private-repo folder), held to its seal,
       placed at hidden_tests.into in the pull request's tree, run in the sandbox, run again when it passed
       (the re-run must agree), then removed
    5. the public tests, when configured
    6. the verdict, the receipt (signed when a key is given), the comment; every text Gate would post is checked
       against the hidden files' lines first, and a text that would leak one is replaced by a refusal to post
    7. with `post`: the one comment (edited in place), the labels, closing (on_fail: close)
    8. Knos Record: one "verification" entry and one "cheat" entry per finding (knos.record, when installed)

Output folder: verdict.json, comment.md, and with a receipt receipt.json, receipt.html, badge.svg."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from . import cheatlib, config, report, sealed
from . import verdict as V


def _hidden_bundle(h: dict, hidden_env: str | None, hidden_file: Path | None, hidden_dir: Path | None) -> bytes:
    if hidden_dir is not None:
        return sealed.pack(hidden_dir)
    if hidden_file is not None:
        return Path(hidden_file).read_bytes()
    name = hidden_env or h.get("secret") or "KNOS_GATE_HIDDEN"
    value = os.environ.get(name, "")
    if not value.strip():
        raise sealed.Refused(f"the hidden tests are not available to this run (secret {name} is empty: a fork's "
                             "`pull_request` run gets no secret; Gate's knos-gate.yml runs on `workflow_run`)")
    return sealed.decode(value)


def _record(v: dict) -> None:
    try:
        from .. import record  # type: ignore[attr-defined]
    except ImportError:
        return
    if not hasattr(record, "append"):
        return
    try:
        record.append("verification", {"spec_hash": v["spec_hash"], "passed": v["passed"], "rule": v["rule"],
                                       "mode": v["mode"], "repo": v["repo"], "pr": v["pr"], "head": v["head"]}, domain="code")
        for f in v["findings"]:
            if f.get("severity") == "refuse":
                record.append("cheat", {"spec_hash": v["spec_hash"], "cheat": f["category"], "rule": f["rule"],
                                        "repo": v["repo"], "pr": v["pr"]}, domain="code")
    except Exception:  # noqa: BLE001 - the record is a log of the run, never a reason the run fails
        pass


def run(*, base: Path, pr_dir: Path, diff: str, repo: str, pr: int, head: str, base_sha: str = "",
        author_association: str = "NONE", out: Path, hidden_env: str | None = None, hidden_file: Path | None = None,
        hidden_dir: Path | None = None, sandbox: str = "auto", keypair=None, issuer_name: str = "knos-gate",
        env: dict | None = None, rerun: bool = True, cheat_lib=None, pull: dict | None = None) -> dict:
    env = dict(os.environ if env is None else env)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    run_url = ""
    if env.get("GITHUB_RUN_ID"):
        run_url = f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/{env.get('GITHUB_REPOSITORY', repo)}/actions/runs/{env['GITHUB_RUN_ID']}"
    cfg = config.load(base)
    if cfg["outside_only"] and not V.outside(author_association):
        v = V.skipped(repo, pr, head, base_sha, f"the author is a {author_association.lower()} of this repository")
        return _finish(v, cfg, out, None, set(), keypair, issuer_name, env, None, pull, diff)
    findings = cheatlib.scan(diff, cfg, base, lib=cheat_lib)
    lib_name = cheatlib.library() if cheat_lib is None else "knos.cheats"
    hidden = public = rerun_said = None
    error, hidden_lines = "", set()
    tmp = out / "work"
    tmp.mkdir(exist_ok=True)
    if not cheatlib.refused(findings):
        h = cfg["hidden_tests"]
        if h:
            placed: list[Path] = []
            try:
                bundle = _hidden_bundle(h, hidden_env, hidden_file, hidden_dir)
                target = Path(pr_dir) / h["into"]
                if target.exists():
                    raise sealed.Refused(f"the pull request's tree already has {h['into']}, where the hidden tests go")
                placed = [target / n for n in sealed.unpack(bundle, target, h["sha256"])]
                hidden_lines = sealed.hidden_lines(placed)
                hidden = sealed.run(h["command"], pr_dir, tmp / "hidden.xml", tmp / "hidden.log", timeout=h["timeout"], sandbox=sandbox)
                if rerun and sealed.passed(hidden):
                    second = sealed.run(h["command"], pr_dir, tmp / "hidden2.xml", tmp / "hidden2.log", timeout=h["timeout"],
                                        sandbox=sandbox, extra_env={"PYTHONHASHSEED": "1"})
                    from ..receipt2.core import rerun_agrees
                    agrees = rerun_agrees(hidden, second)
                    rerun_said = {"ran": True, "agrees": agrees}
                    if not agrees:
                        findings.append({"rule": "gate.rerun_mismatch", "category": "rerun_mismatch", "path": "",
                                         "detail": "a second run of the hidden tests did not agree with the first", "severity": "refuse"})
            except sealed.Refused as why:
                error = str(why)
            finally:
                if (Path(pr_dir) / h["into"]).exists() and placed:
                    shutil.rmtree(Path(pr_dir) / h["into"], ignore_errors=True)
                for f in tmp.glob("hidden*"):
                    f.unlink()          # the suite's output and report name the hidden tests: they never leave the runner
        if cfg["public_tests"]:
            public = sealed.run(cfg["public_tests"]["command"], pr_dir, tmp / "public.xml", tmp / "public.log",
                                timeout=cfg["public_tests"]["timeout"], sandbox=sandbox)
    v = V.decide(cfg, findings, hidden, public, repo=repo, pr=pr, head=head, base=base_sha, run_url=run_url,
                 library=lib_name, error=error)
    return _finish(v, cfg, out, rerun_said, hidden_lines, keypair, issuer_name, env, cheat_lib, pull, diff)


def _finish(v, cfg, out: Path, rerun_said, hidden_lines, keypair, issuer_name, env, cheat_lib, pull, diff: str = "") -> dict:
    from ..receipt2 import core as rc
    from ..receipt2 import page
    envelope = None
    if cfg.get("receipt") and not v.get("skipped"):
        key = str(keypair.pubkey()) if keypair is not None else ""
        body = rc.build(v, issuer_name=issuer_name, issuer_key=key, runner=rc.runner_from_env(env), rerun=rerun_said,
                        rules_run=cheatlib.rules_run(cheat_lib))
        if keypair is not None:
            envelope = rc.sign(body, keypair)
            (out / "receipt.json").write_text(json.dumps(envelope, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            (out / "receipt.html").write_text(page.render(envelope), encoding="utf-8")
            (out / "badge.svg").write_text(page.badge(envelope), encoding="utf-8")
        else:
            (out / "receipt.unsigned.json").write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    text = report.comment(v, envelope)
    leaked = sealed.leaks(text + json.dumps(v), hidden_lines)
    if leaked:
        v = {**v, "passed": False, "rule": "gate.leak_guard", "reasons": ["Gate stopped itself from posting text that quoted a hidden test"],
             "findings": []}
        text = report.comment(v, None)
        envelope = None
    v["actions"] = V.actions(v, cfg)
    if pull is not None:
        from . import bounty
        v["claims"] = bounty.claims(pull)
        if bounty.must_close(cfg, pull, v):
            v["actions"]["close"] = True           # bounties mode: a claim that fails Gate is closed
            text += "\n\nThis pull request claims a bounty and failed Knos Gate, so it was closed. Fix it and open a new one."
    (out / "verdict.json").write_text(json.dumps(v, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "comment.md").write_text(text, encoding="utf-8")
    (out / "summary.md").write_text(report.summary(v), encoding="utf-8")
    log = None
    if not v.get("skipped"):
        from . import sarif as S         # code scanning (SARIF) and check annotations: the same refused findings, nothing more
        from .. import version
        log, notes = S.sarif(v, diff, version()), S.annotations(v, diff)
        if sealed.leaks(json.dumps(log) + json.dumps(notes), hidden_lines):
            log, notes = S.sarif({**v, "findings": []}, "", version()), []
        (out / "knos-gate.sarif").write_text(json.dumps(log, indent=1) + "\n", encoding="utf-8")
        (out / "annotations.json").write_text(json.dumps(notes, indent=1) + "\n", encoding="utf-8")
        _record(v)
    return {"verdict": v, "comment": text, "receipt": envelope, "sarif": log}


def post(result: dict, repo: str, pr: int, *, me: str | None = "github-actions[bot]", client=None,
         code_scanning: bool = False) -> dict | None:
    """The comment and the labels; with `code_scanning`, the SARIF log too (POST code-scanning/sarifs for the head
    commit, ref refs/pull/<pr>/head; the token needs `security-events: write`). Returns GitHub's answer to the upload."""
    from .github import Client
    c = client or Client(repo)
    c.upsert_comment(pr, result["comment"], me=me)
    c.apply(pr, result["verdict"]["actions"])
    if code_scanning and result.get("sarif") is not None and not result["verdict"].get("skipped"):
        return c.upload_sarif(result["verdict"]["head"], f"refs/pull/{pr}/head", result["sarif"])
    return None
