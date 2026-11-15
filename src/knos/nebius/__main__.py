"""python -m knos.nebius flow --out DIR [--wallets DIR] [--team NAME] [--rounds N]
                                      (ONE task end to end: post -> agent codes on Nemotron -> referee -> paid -> invoiced)
   python -m knos.nebius status
   python -m knos.nebius demo [--out DIR] [--iterations N] [--root REPO]
   python -m knos.nebius rerun TASK_DIR --file-b64 B64      (what a Nebius Serverless Job runs: one candidate, sealed set)
   python -m knos.nebius job-command TASK_DIR FILE [--ref BRANCH]   (prints the `nebius ai job create` line, runs nothing)
   python -m knos.nebius job TASK_DIR FILE [--ref BRANCH]           (creates the job; needs KNOS_NEBIUS_JOBS=1 + CLI)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path

from . import rerun, sources

REPO_URL = "https://github.com/drexthealpha/Knos"


def _job_args(task_dir: str, file: str, ref: str) -> str:
    b64 = base64.b64encode(Path(file).read_bytes()).decode()
    return ("-c " + shlex.quote(f"git clone -q --depth 1 -b {shlex.quote(ref)} {REPO_URL} /k && cd /k && "
                                f"pip install -q -e . && python -m knos.nebius rerun {shlex.quote(task_dir)} --file-b64 {b64}"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m knos.nebius")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="which mode each provider is in (no key is ever printed)")
    fl = sub.add_parser("flow", help="one task end to end: post, code on Nemotron, referee, paid, metered (flow.json + flow.html in --out)")
    fl.add_argument("--out", default="")
    fl.add_argument("--root", default=".", help="a folder that has examples/nebius/task (kept outside the public repository)")
    fl.add_argument("--wallets", default="", help="a folder with team.json, agent.json, mint.json (devnet keys; never printed): funds the held money and pays the check on devnet")
    fl.add_argument("--team", default="knos-internal-dogfooding")
    fl.add_argument("--rounds", type=int, default=4)
    fl.add_argument("--no-cheater", action="store_true", help="leave out the scripted (synthetic) cheater")
    fl.add_argument("--usage", default="", help="append to this usage record (a team's record across runs) instead of DIR/usage.jsonl")
    d = sub.add_parser("demo", help="the golden path; panel.json + panel.html in --out")
    d.add_argument("--out", default="")
    d.add_argument("--iterations", type=int, default=4)
    d.add_argument("--root", default=".", help="the Knos checkout (targets.yml, examples/autoresearch)")
    r = sub.add_parser("rerun", help="judge one candidate file on the task's sealed final set (both seeds)")
    r.add_argument("task")
    r.add_argument("--file-b64", required=True)
    for name in ("job-command", "job"):
        j = sub.add_parser(name)
        j.add_argument("task")
        j.add_argument("file")
        j.add_argument("--ref", default="main")
        j.add_argument("--name", default="knos-rerun")
        j.add_argument("--image", default="python:3.12-slim")
    a = ap.parse_args(argv)

    if a.cmd == "status":
        print(json.dumps({"token_factory": "live" if os.environ.get(sources.KEY_ENV) else f"mock ({sources.KEY_ENV} not set)",
                          "tavily": "live" if os.environ.get(sources.TAVILY_KEY_ENV) else f"mock ({sources.TAVILY_KEY_ENV} not set)",
                          "reruns": rerun.backend(), "coder": sources.SUPER, "explainer": sources.ULTRA}, indent=2))
        return 0
    if a.cmd == "flow":
        from .flow import run_flow
        out = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="knos-flow-"))
        done = run_flow(Path(a.root), out, wallets=Path(a.wallets) if a.wallets else None, team=a.team, rounds=a.rounds,
                        cheater=not a.no_cheater, usage=Path(a.usage) if a.usage else None)
        print(f"flow: {out / 'flow.html'}")
        return 0 if any(s.get("step") == "referee" and s.get("passed") for s in done["steps"]) else 1
    if a.cmd == "demo":
        from .demo import run_demo
        out = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="knos-nebius-"))
        run_demo(Path(a.root), out, iterations=a.iterations)
        print(f"panel: {out / 'panel.html'}")
        return 0
    if a.cmd == "rerun":
        from ..autoresearch import judge, task
        t = task.load(a.task)
        src = base64.b64decode(a.file_b64).decode()
        v = judge.LocalJudge(t).judge({t.editable: src}, None, stage="final")
        print(json.dumps({"passed": v.passed, "scores": v.scores, "reasons": v.reasons, "judge_hash": judge.judge_hash()}))
        return 0 if v.passed else 1
    args = _job_args(a.task, a.file, a.ref)
    if a.cmd == "job-command":
        print(shlex.join(rerun.job_create(a.name, a.image, "bash", args)))
        return 0
    if rerun.backend()["backend"] != "nebius-serverless-job":
        print("knos nebius: " + rerun.backend()["reason"], file=sys.stderr)
        return 2
    print(json.dumps(rerun.run_job(a.name, a.image, "bash", args), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
