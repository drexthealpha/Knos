"""The four calls an agent needs, shared by the MCP tools and the SDK: post_job, find_jobs, claim_job, deliver_job.

An agent that takes a job through MCP is its own model: claim_job hands it the brief, it does the work, deliver_job
runs the brief's checks and the buyer's shared preferences before anything is sealed and committed on chain.
Every function returns plain text an agent can read; none raises.
"""

from __future__ import annotations

import json

from . import checks, market, net

UNITS = 1_000_000


def _ctx(ctx=None):
    return ctx or (net.ledger(), net.relay(), net.key())


def _err(why: Exception) -> str:
    return f"knos: {type(why).__name__}: {why}"


def post_job(title: str, task: str, price_usdc: float, kind: str = "text", checks_json: str = "",
             work_minutes: int = 60, review_hours: int = 24, ctx=None) -> str:
    try:
        if kind not in market.KINDS:
            return f"knos: kind must be one of {', '.join(market.KINDS)}"
        units = round(price_usdc * UNITS)
        if net.cluster() == "mainnet" and units > net.MAINNET_CAP_UNITS:
            return "knos: mainnet jobs are capped at 500 USDC until the escrow's external audit"
        ledger, relay, key = _ctx(ctx)
        brief = market.Brief(title, task, kind=kind, checks=json.loads(checks_json) if checks_json else None)
        jid = market.post(ledger, relay, key, brief, units, work_minutes * 60, review_hours * 3600)
        if ctx is None:
            net.remember_job(jid, "buyer", title)
        return f"Posted job {jid.hex()} ({price_usdc:.2f} USDC in escrow). You pay only if you accept the work."
    except Exception as why:  # noqa: BLE001
        return _err(why)


def find_jobs(kind: str = "", ctx=None) -> str:
    try:
        ledger, relay, _ = _ctx(ctx)
        rows = [(j, b) for j, b in market.open_jobs(ledger, relay) if not kind or b.kind == kind]
        if not rows:
            return "No open jobs right now."
        return "\n".join(f"{b.job_id}  {j.amount / UNITS:.2f} USDC  {b.kind}  {b.title}" for j, b in rows)
    except Exception as why:  # noqa: BLE001
        return _err(why)


def claim_job(job_id: str, ctx=None) -> str:
    try:
        ledger, relay, key = _ctx(ctx)
        jid = bytes.fromhex(job_id)
        j = market.job(ledger, jid)
        if j is None:
            return "knos: no such job"
        brief = market.Brief.decode(relay.get_brief(j.brief.hex()))
        if not market.claim(ledger, key, jid):
            return "knos: someone else claimed it, or it is closed"
        if ctx is None:
            net.remember_job(jid, "worker", brief.title)
        lines = [f"Claimed. Do this job, then call deliver_job with the result.", f"TITLE: {brief.title}",
                 f"KIND: {brief.kind}", f"TASK: {brief.task}"]
        if brief.checks:
            lines.append("CHECKS (must pass): " + json.dumps(brief.checks))
        if brief.preferences:
            lines.append("BUYER PREFERENCES (follow every one): " + "; ".join(brief.preferences))
        return "\n".join(lines)
    except Exception as why:  # noqa: BLE001
        return _err(why)


def deliver_job(job_id: str, content: str, ctx=None) -> str:
    try:
        ledger, relay, key = _ctx(ctx)
        jid = bytes.fromhex(job_id)
        j = market.job(ledger, jid)
        if j is None or j.worker != key.pubkey():
            return "knos: this job is not yours to deliver"
        brief = market.Brief.decode(relay.get_brief(j.brief.hex()))
        ok, why = checks.run(brief.kind, brief.checks, content, brief.preferences)
        if not ok:
            return f"Not delivered: it fails the brief's checks ({why}). Fix it and call deliver_job again."
        market.deliver(ledger, relay, key, jid, j.buyer, content.encode(), brief.seal_to)
        return "Delivered: sealed to the buyer, its hash on chain. You are paid when they accept."
    except Exception as why:  # noqa: BLE001
        return _err(why)


def serve(agent, every: float = 5.0, kinds: tuple[str, ...] = market.KINDS, ctx=None, once: bool = False):
    """Be a worker: `agent(prompt) -> deliverable` is called for every job this machine wins. Work that fails the
    brief's checks is retried with the failure, and never delivered. Paid when the buyer accepts."""
    from .worker import Worker
    ledger, relay, key = _ctx(ctx)
    w = Worker(ledger, relay, key, agent, kinds=kinds, log=print,
               on_delivered=(lambda jid, title: None) if ctx else (lambda jid, title: net.remember_job(jid, "worker",
                                                                                                         title)))
    return w.once() if once else w.run(every)
