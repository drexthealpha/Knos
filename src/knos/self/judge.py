"""The referee of the self loop, as it runs from MAIN: `python -m knos.self.judge REQUEST.json VERDICT.json`, started by
the loop with main's checkout first on the path. Everything that decides is main's: targets.yml, CODEOWNERS, the cheat
library, the sealed bundles' hashes, this file. The candidate is only read (its diff, its files) until the cheat rules
pass, and then only run as the thing under test, in Gate's sandboxed runner, never imported here.

In order, the first refusal decides (no candidate code runs before step 5):

    1. the referee is main's     the running judging code's hash (knos.referee.judge_hash) is main's tree's; the
                                 candidate's own judging code is hashed too and, when it differs, the candidate is a
                                 referee change: refused here (it goes through `knos self referee` and the founder)
    2. lineage                   the candidate commit descends from the parent the loop chose
    3. trust split               no core path (targets.yml core + CODEOWNERS), nothing outside the product
    4. cheat rules               knos.cheats.scan_diff with the target's scope and the core, plus the loop's own rules
                                 (test count, asserts, logging, detector markers)
    5. public tier               the target's public tests pass on the candidate
    6. sealed tier               the hidden bundle: the metric on parent and candidate, the hidden tests, each re-run;
                                 the agent's own number, if it gave one, must be what the referee measured
    7. merge rule                the target improves by at least min_gain
    8. shadow                    the target's neighbouring tests, parent beside candidate: a disagreement is held
    9. plausible gain            a gain above implausible_gain_rel is held

Decision: accept (the loop then applies the daily cap and moves it to canary) | held (founder review) | refused.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from .. import cheats as _cheats
from . import config, rules, tiers


def _git(repo, *args) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=300)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {done.stderr.decode('utf-8', 'replace').strip()[-300:]}")
    return done.stdout.decode("utf-8", "replace")


def _f(f) -> dict:
    return f.to_dict() if hasattr(f, "to_dict") else dict(f)


def judge(req: dict, *, main_root=None, cfg: dict | None = None) -> dict:
    """`main_root`: main's checkout (default: the tree this code runs from). `cfg`: targets as loaded from main
    (default: main_root/targets.yml; tests give their own)."""
    from ..referee import judge_hash
    main_root = Path(main_root) if main_root is not None else config.repo_root()
    cfg = cfg if cfg is not None else config.load(main_root)
    t = config.target(cfg, req["target"])
    v: dict = {"target": t["id"], "referee": "main", "reasons": [], "findings": [], "tiers": {}}
    running = judge_hash()
    v["judge_hash"] = tiers.tree_judge_hash(main_root)
    v["running_judge_hash"] = running
    if running != v["judge_hash"]:
        return _done(v, "refused", ["the running referee is not main's (its judging code does not hash to main's tree)"])
    # the hashes the loop pinned when it was set up (archive v0): a referee checkout edited since then is not main's
    if req.get("expected_judge_hash") and req["expected_judge_hash"] != v["judge_hash"]:
        return _done(v, "refused", ["the referee checkout's judging code is not the one pinned at `knos self init`"])
    v["loop_hash"] = tiers.tree_loop_hash(main_root)
    if req.get("expected_loop_hash") and req["expected_loop_hash"] != v["loop_hash"]:
        return _done(v, "refused", ["the referee checkout's runner or loop code is not the one pinned at `knos self init`"])
    parent_dir, cand_dir, repo = Path(req["parent_dir"]), Path(req["candidate_dir"]), Path(req.get("repo") or req["candidate_dir"])
    for d, c in ((parent_dir, req["parent_commit"]), (cand_dir, req["candidate_commit"])):
        head = _git(d, "rev-parse", "HEAD").strip()
        if head != c:
            return _done(v, "refused", [f"the tree at hand is {head[:12]}, not the commit named {c[:12]}"])
    if subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", req["parent_commit"], req["candidate_commit"]],
                      capture_output=True).returncode != 0:
        return _done(v, "refused", ["the candidate is not built on the parent the loop chose"])
    # paths as git lists them (NUL-separated, never quoted), and the diff with non-ASCII names unquoted: a path the
    # diff reader cannot see is refused, so a quoted name can never slip past the rules
    listed = sorted(x for x in _git(repo, "-c", "core.quotePath=false", "diff", "--no-renames", "--name-only", "-z",
                                    req["parent_commit"], req["candidate_commit"]).split("\0") if x)
    diff = _git(repo, "-c", "core.quotePath=false", "diff", "--no-renames", "--binary", "--no-color", "--no-ext-diff",
                req["parent_commit"], req["candidate_commit"])
    v["diff_hash"] = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    if req.get("run_dir"):
        Path(req["run_dir"]).mkdir(parents=True, exist_ok=True)
        (Path(req["run_dir"]) / "candidate.diff").write_text(diff, encoding="utf-8")
    v["candidate_judge_hash"] = tiers.tree_judge_hash(cand_dir)
    paths = sorted({f.path for f in _cheats.parse_diff(diff)})
    v["changed"] = listed
    findings = []
    for unseen in sorted(set(listed) - set(paths)):
        findings.append(_cheats.Finding("self.unparsed_path", "out_of_scope", unseen[:200],
                                        "a changed path the diff reader cannot read (quoted or unusual name): refused"))
    paths = sorted(set(paths) | set(listed))
    if v["candidate_judge_hash"] != v["judge_hash"]:
        findings.append(_cheats.Finding("self.referee_in_agent_pr", "judge_drift", "",
                                        "the candidate changes the judging code: a referee change goes through the founder "
                                        "(knos self referee), never through the loop; main's referee judged this"))
    findings += config.agent_findings(paths, cfg, t.get("scope") or ())
    findings += _cheats.scan_diff(diff, base_dir=parent_dir, scope=tuple(t.get("scope") or ()), core=tuple(config.core_globs(cfg)))
    static, counts = rules.static_findings(diff, parent_dir, cand_dir)
    findings += static
    v["counts"] = counts
    v["findings"] = _dedupe([_f(f) for f in findings])
    v["proposed_rules"] = rules.proposed_rules(findings)
    if _cheats.refused(findings):
        return _done(v, "refused", [f"{f['rule']} ({f['category']}){': ' + f['path'] if f['path'] else ''}: {f['detail']}"
                                    for f in v["findings"] if f["severity"] == "refuse"][:12])
    sandbox = req.get("sandbox", "auto")
    jail = req.get("jail") or {}
    tiers.configure(mask=list(jail.get("mask") or []) + tiers.default_mask(), ro=jail.get("ro") or [],
                    trees=[parent_dir, cand_dir])
    if sandbox != "none" and not tiers.jail_available():
        return _done(v, "refused", ["no sandbox on this machine (sudo -n unshare --net --mount): no candidate code runs "
                                    "with the operator's reach; the loop fails closed"])
    pub = tiers.public_tier(t["public_tests"], cand_dir, sandbox=sandbox)
    v["tiers"]["public"] = pub
    if not pub["passed"]:
        return _done(v, "refused", ["public tests fail on the candidate"])
    sealed = tiers.sealed_tier(req["bundles"]["sealed"], t["sealed"]["sha256"], t["sealed"], parent_dir, cand_dir,
                               sandbox=sandbox, reruns=int(req.get("reruns", 1)), tolerance_abs=float(t.get("tolerance_abs", 0)))
    v["tiers"]["sealed"] = sealed
    v["metric_parent"] = (sealed.get("metric_parent") or {}).get("metric")
    v["metric_candidate"] = (sealed.get("metric_candidate") or {}).get("metric")
    claim = rules.claim_findings(req.get("claimed_metric"), v["metric_candidate"], float(t.get("tolerance_abs", 0)))
    if claim:
        v["findings"] += [_f(f) for f in claim]
        return _done(v, "refused", [claim[0].detail + " (the referee re-runs everything; an agent's report is never used)"])
    if not sealed.get("passed"):
        why = [sealed["error"]] if sealed.get("error") else []
        if sealed.get("rerun_agrees") is False:
            why.append("the sealed tier's re-run did not agree with its first run")
            v["findings"].append({"rule": "self.rerun_mismatch", "category": "rerun_mismatch", "path": "", "detail": "; ".join(sealed.get("rerun_reasons") or []), "severity": "refuse"})
        return _done(v, "refused", why or ["sealed tests: failed"])
    g = rules.gain(v["metric_parent"], v["metric_candidate"], t["direction"])
    v["gain"] = g
    if g is None or g < float(t.get("min_gain", 0)) or (g <= 0 and float(t.get("min_gain", 0)) <= 0):
        return _done(v, "refused", [f"the target did not improve: {v['metric_parent']} -> {v['metric_candidate']} "
                                    f"({t['direction']} is better; at least {t.get('min_gain', 0)} needed)"])
    if t.get("shadow_tests"):
        sh = tiers.shadow_tier(t["shadow_tests"], parent_dir, cand_dir, sandbox=sandbox)
        v["tiers"]["shadow"] = sh
        if not sh["passed"]:
            return _done(v, "held", [f"shadow: passes on the parent and fails on the candidate: {', '.join(sh['disagreements'])}"])
    if rules.implausible(v["metric_parent"], g, t.get("implausible_gain_rel")):
        v["findings"].append({"rule": "self.implausible_gain", "category": "rerun_mismatch", "path": "",
                              "detail": f"gain {g} of {v['metric_parent']}", "severity": "flag"})
        return _done(v, "held", [f"implausibly large gain ({g} of {v['metric_parent']}, above {t.get('implausible_gain_rel')}): "
                                 "held for the founder"])
    return _done(v, "accept", [])


def _dedupe(fs: list[dict]) -> list[dict]:
    seen, out = set(), []
    for f in fs:
        key = (f["category"], f["path"], f["rule"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def _done(v: dict, decision: str, reasons: list[str]) -> dict:
    v["decision"] = decision
    v["reasons"] = list(v.get("reasons") or []) + list(reasons)
    return v


def agent_view(v: dict) -> dict:
    """What the agent that wrote the candidate is told: the decision, its reasons, the public tier's counts, and
    pass/fail ONLY for the sealed tier (no counts, no names, no log)."""
    tiers_ = v.get("tiers") or {}
    out = {"decision": v.get("decision"), "reasons": v.get("reasons", []),
           "cheats": sorted({f["category"] for f in v.get("findings") or [] if f.get("severity") == "refuse"})}
    if "public" in tiers_:
        out["public"] = {"passed": tiers_["public"]["passed"], "tests": tiers_["public"].get("tests")}
    if "sealed" in tiers_:
        out["sealed"] = {"passed": bool(tiers_["sealed"].get("passed"))}
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: python -m knos.self.judge REQUEST.json VERDICT.json", file=sys.stderr)
        return 2
    req = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    try:
        v = judge(req)
    except Exception as why:  # noqa: BLE001 - the loop records a referee failure as a refusal, said
        v = {"decision": "refused", "reasons": [f"the referee failed: {type(why).__name__}: {str(why)[:300]}"], "findings": [], "tiers": {}}
    Path(argv[1]).write_text(json.dumps(v, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
