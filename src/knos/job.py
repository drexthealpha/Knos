"""One Knos job from Python or the command line, in its order: Qloo checks demand (`knos demand`), the test is locked
(`ready`), IRIS's rules referee checks the proof (`iris_check`), and NEAR pays the agent that passed (`near_job`).

    from knos import job
    job.ready(brief)                       # Ready or the missing fields, and the criteria hash that locks it
    job.iris_check(brief, "checkrun", proof)  # met or not met per milestone, as the IRIS referee decides
    job.near_job()                         # one live testnet job on the hosted runner: two agents, the passing one paid

`knos ready <brief.json>`, `knos iris-check <brief.json> <kind> <proof.json>` and `knos near-job` print the same.
The NEAR job runs on https://knos.onrender.com (KNOS_WANTED_URL) from its own capped testnet account; test tokens only.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

BASE = os.environ.get("KNOS_WANTED_URL", "https://knos.onrender.com").rstrip("/")
TX = "https://testnet.nearblocks.io/txns/"


def ready(brief: dict) -> dict:
    """Whether a brief can lock money (knos.ready.check): Ready with its criteria hash, or what is missing."""
    from . import ready as _ready
    return _ready.check(brief)


def iris_check(brief: dict, kind: str, proof) -> dict:
    """The rules referee IRIS runs (knos.referee_rules) on one proof: a check run, a FHIR Observation or an HL7 ORU."""
    from . import ready as _ready
    from . import referee_rules
    if kind == "checkrun" and isinstance(proof, dict) and "check_run" not in proof and ({"name", "conclusion"} & set(proof)):
        proof = {"check_run": proof}
    payload = proof if isinstance(proof, str) else json.dumps(proof)
    return json.loads(referee_rules.decide(json.dumps(brief), kind, payload, _ready.criteria_hash(brief)))


def _get(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(BASE + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json", "User-Agent": "knos-sdk"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def near_job(wait: bool = True, every: float = 3.0, limit: float = 600.0, say=None) -> dict:
    """Start one live job on the hosted runner and, with `wait`, follow it to the payment. A cap answers with a replay."""
    s = _get("/api/near/live", {})
    if s.get("replay") or not wait:
        return s
    t0, step = time.time(), ""
    while time.time() - t0 < limit:
        time.sleep(every)
        r = _get(f"/api/near/live/{s['run']}")
        if say and r.get("step") != step:
            step = r.get("step", "")
            say(f"{round(r.get('seconds_so_far', 0))} s: {step}")
        if r.get("state") != "running":
            return r
    return {"state": "running", "run": s["run"], "why": f"still running after {limit:.0f} s"}


def register(app, help_lines: list | None = None) -> None:
    """`knos ready`, `knos iris-check` and `knos near-job` on the main app."""
    import importlib
    typer = importlib.import_module("typer")

    if help_lines is not None:
        help_lines.append(("ready", None, "Lock the test: Ready or what a brief is missing, and its criteria hash."))
        help_lines.append(("iris-check", None, "Check a proof as IRIS does: met or not met per milestone."))
        help_lines.append(("near-job", None, "One live NEAR testnet job: two agents try, only the passing one is paid."))

    def _load(path: str):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        try:
            return json.loads(text)
        except ValueError:
            return text                              # an HL7 ORU message is text

    @app.command("ready", help="Whether a brief (a JSON file) can lock money: Ready with its criteria hash, or what is missing.")
    def ready_(brief: str = typer.Argument(..., help="the brief, a JSON file with milestones")) -> None:
        r = ready(_load(brief))
        typer.echo(("Ready: " + str(r.get("criteria_hash"))) if r.get("ready") else "Not ready: " + "; ".join(r.get("missing") or []))

    @app.command("iris-check", help="Check one proof against a brief with the rules referee IRIS runs. Kinds: checkrun, observation, oru.")
    def iris_check_(brief: str = typer.Argument(..., help="the brief, a JSON file"),
                    kind: str = typer.Argument(..., help="checkrun, observation or oru"),
                    proof: str = typer.Argument(..., help="the proof file (JSON, or the ORU message as text)")) -> None:
        r = iris_check(_load(brief), kind, _load(proof))
        typer.echo(f"{r.get('decision')}: " + "; ".join(f"{m.get('key')} {'met' if m.get('met') else 'not met'} ({m.get('reason', '')})"
                                                     for m in r.get("milestones") or []))

    @app.command("near-job", help="Run one live NEAR testnet job on the hosted runner and follow it to the payment (test tokens).")
    def near_job_(as_json: bool = typer.Option(False, "--json", help="the whole answer")) -> None:
        r = near_job(say=typer.echo)
        if as_json:
            typer.echo(json.dumps(r, indent=1))
            return
        if r.get("replay"):
            typer.echo(f"Replay: {r.get('why')}.")
            r = {"job": (r.get("last") or {}).get("job"), "state": "replay"}
        job = r.get("job") or {}
        paid = r.get("paid") or job.get("paid") or {}
        typer.echo(f"{r.get('state')}: " + ", ".join(f"{k} paid {v}" for k, v in paid.items()))
        for k, h in (job.get("txs") or {}).items():
            typer.echo(f"  {k}: {TX}{h}")
