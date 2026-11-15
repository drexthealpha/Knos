"""Referee changes need the founder. A change to the judge, the cheat library or the runner never comes in as an agent's
pull request (those paths are core: refused). It comes as the founder's own pull request, and before it may judge:

    1. red-team gate   the fixed red-team set (knos.cheats.CASES, built by MAIN's code from tests/bench_tamper) is run
                       through main's scanner and through the candidate's, each in its own process from its own tree.
                       The candidate must refuse at least as many cases as main AND every case main refuses
                       (`at_least_current`). A weaker referee is blocked here, whoever signed it.
    2. shadow          the candidate referee re-scores past jobs of the loop (their diffs, from the run folder) beside
                       main's referee; every disagreement is listed. Fewer than shadow_jobs_min jobs: it waits.
    3. founder         an ed25519 signature over "knos-self:referee:<candidate loop_hash>" by a key in
                       targets.yml loop.referee_change.approval_keys. No key listed: the change waits for the founder.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .tiers import tree_judge_hash, tree_loop_hash

_SCAN = r"""
import json, sys
from pathlib import Path
tree = Path(sys.argv[1]).resolve()
import knos.cheats as C
assert Path(C.__file__).resolve().is_relative_to(tree), "the scanner did not load from the tree under test"
req = json.loads(Path(sys.argv[2]).read_text())
out = {}
for job in req.get("pairs", []):
    try:
        out[job["id"]] = bool(C.refused(C.scan(job["base"], job["pr"])))
    except Exception as why:
        out[job["id"]] = "error: " + str(why)[:200]
diffs = {}
for job in req.get("diffs", []):
    try:
        f = C.scan_diff(Path(job["diff"]).read_text(encoding="utf-8", errors="replace"), core=tuple(job.get("core") or ()), scope=tuple(job.get("scope") or ()))
        diffs[job["id"]] = {"refused": bool(C.refused(f)), "rules": sorted({x.rule for x in f if x.severity == "refuse"})}
    except Exception as why:
        diffs[job["id"]] = {"refused": None, "error": str(why)[:200]}
print(json.dumps({"pairs": out, "diffs": diffs, "rules": len(C.RULES)}))
"""


def _run_scanner(tree, request: dict, *, timeout: int = 1800) -> dict:
    """The cheat library of `tree` (its src/knos/cheats) on the given case pairs / diffs, in a fresh process."""
    with tempfile.TemporaryDirectory(prefix="knos-self-scan-") as t:
        req = Path(t) / "req.json"
        req.write_text(json.dumps(request), encoding="utf-8")
        env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "HOME") if k in os.environ}
        env.update({"PYTHONPATH": str(Path(tree) / "src"), "PYTHONDONTWRITEBYTECODE": "1"})
        done = subprocess.run([sys.executable, "-c", _SCAN, str(tree), str(req)], cwd=t, env=env, capture_output=True,
                              text=True, timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError(f"the scanner of {tree} failed: {done.stderr.strip()[-400:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def build_cases(into, cases=None) -> list[dict]:
    """The fixed red-team set, laid out by THIS (main's) code: [{id, base, pr}]."""
    from .. import cheats
    out = []
    for c in (cases if cases is not None else cheats.CASES):
        base, pr = Path(into) / c.id / "base", Path(into) / c.id / "pr"
        cheats.build_case(c, base, pr)
        out.append({"id": c.id, "base": str(base), "pr": str(pr)})
    return out


def red_team_gate(main_tree, candidate_tree, *, cases=None) -> dict:
    """{"current", "candidate": {caught,total,missed}, "newly_missed", "passed"}: the candidate referee must catch every
    case main's catches (so also at least as many)."""
    with tempfile.TemporaryDirectory(prefix="knos-self-redteam-") as t:
        pairs = build_cases(t, cases)
        cur = _run_scanner(main_tree, {"pairs": pairs})["pairs"]
        try:
            new = _run_scanner(candidate_tree, {"pairs": pairs})["pairs"]
        except RuntimeError as why:            # a referee that cannot even run catches nothing
            new = {p["id"]: f"error: {str(why)[-200:]}" for p in pairs}

    def summary(got: dict) -> dict:
        missed = sorted(k for k, v in got.items() if v is not True)
        return {"caught": len(got) - len(missed), "total": len(got), "missed": missed}
    a, b = summary(cur), summary(new)
    newly = sorted(set(b["missed"]) - set(a["missed"]))
    return {"current": a, "candidate": b, "newly_missed": newly, "passed": b["caught"] >= a["caught"] and not newly}


def shadow(main_tree, candidate_tree, jobs: list[dict]) -> dict:
    """jobs: [{id, diff (a file), core, scope}] of past loop runs. Both referees score each; disagreements listed."""
    if not jobs:
        return {"jobs": 0, "disagreements": []}
    a = _run_scanner(main_tree, {"diffs": jobs})["diffs"]
    b = _run_scanner(candidate_tree, {"diffs": jobs})["diffs"]
    dis = [{"job": j["id"], "main": a.get(j["id"]), "candidate": b.get(j["id"])} for j in jobs
           if (a.get(j["id"]) or {}).get("refused") != (b.get(j["id"]) or {}).get("refused")]
    return {"jobs": len(jobs), "disagreements": dis}


def approval_message(candidate_hash: str) -> bytes:
    return f"knos-self:referee:{candidate_hash}".encode()


def founder_approved(candidate_hash: str, approval: dict | None, keys) -> tuple[bool, str]:
    """approval: {"key": base58 public key, "signature": base58 64-byte signature}. Verified with Knos's own
    stdlib Ed25519 (knos.receipt2.ed25519). The loop never holds a founder key; the founder signs by hand."""
    if not keys:
        return False, "no founder approval key in targets.yml: every referee change waits for the founder"
    if not approval:
        return False, "no founder signature over the candidate referee's loop hash (knos-self:referee:<candidate_loop_hash>)"
    from ..receipt2 import ed25519
    if approval.get("key") not in keys:
        return False, "the approving key is not one targets.yml lists"
    try:
        ok = ed25519.verify(ed25519.b58decode(approval["key"]), approval_message(candidate_hash),
                            ed25519.b58decode(approval["signature"]))
    except Exception:  # noqa: BLE001 - a malformed signature is no signature
        ok = False
    return (True, "signed by the founder") if ok else (False, "the founder signature does not verify")


def referee_change(main_tree, candidate_tree, cfg: dict, *, jobs=(), approval=None, cases=None) -> dict:
    """The whole gate for one candidate referee: blocked | waiting (shadow or founder) | approved."""
    rc = (cfg.get("loop") or {}).get("referee_change") or {}
    out: dict = {"main_judge_hash": tree_judge_hash(main_tree), "candidate_judge_hash": tree_judge_hash(candidate_tree),
                 "main_loop_hash": tree_loop_hash(main_tree), "candidate_loop_hash": tree_loop_hash(candidate_tree)}
    # the judge, the cheat library, Gate's runner and the loop itself: a change to any of them is a referee change
    if out["main_loop_hash"] == out["candidate_loop_hash"]:
        return {**out, "decision": "no_change", "reasons": ["the candidate's judging, runner and loop code is main's"]}
    rt = red_team_gate(main_tree, candidate_tree, cases=cases)
    out["red_team"] = rt
    if not rt["passed"]:
        why = f"red-team regression: main catches {rt['current']['caught']}/{rt['current']['total']}, the candidate {rt['candidate']['caught']}/{rt['candidate']['total']}"
        if rt["newly_missed"]:
            why += f"; newly missed: {', '.join(rt['newly_missed'][:8])}"
        return {**out, "decision": "blocked", "reasons": [why]}
    sh = shadow(main_tree, candidate_tree, list(jobs))
    out["shadow"] = sh
    if sh["jobs"] < int(rc.get("shadow_jobs_min", 3)):
        return {**out, "decision": "waiting", "reasons": [f"shadow: {sh['jobs']} past jobs scored, {rc.get('shadow_jobs_min', 3)} needed"]}
    ok, why = founder_approved(out["candidate_loop_hash"], approval, rc.get("approval_keys") or [])
    if not ok:
        return {**out, "decision": "waiting", "reasons": [why] + ([f"shadow disagreements: {len(sh['disagreements'])}"] if sh["disagreements"] else [])}
    return {**out, "decision": "approved", "reasons": [why]}
