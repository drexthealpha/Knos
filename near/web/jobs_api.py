"""The job endpoints of near/web/serve.py: post a job with a locked test and a bid, let two agents take it, have the
checker run the test and pay only the agent that passed, try the two guardrails, and quote paying the bid in USDC on
Base through NEAR Intents 1Click (dry: a quote only, nothing is spent). Every action is a testnet transaction signed on
this machine with the keys in ~/.near-credentials; the page never holds a key.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENTS = HERE.parent / "agents"
sys.path.insert(0, str(AGENTS))

from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402

import checker  # noqa: E402
import fail_agent  # noqa: E402
import pass_agent  # noqa: E402
from agent import run as run_agent  # noqa: E402
from common import CONFIG, JOB_DIR, JOB_TEST, call, ft_balance, sha256_file, view  # noqa: E402

JOBS = HERE / "jobs.local.json"
ONECLICK = "https://1click.chaindefuser.com/v0/quote"
USDC_BASE = "nep141:base-0x833589fcd6edb6e08f4c7c32d4f71b54bda02913.omft.near"
USDC_NEAR = "nep141:17208628f84f5d6ad33f0da3bbbeb27ffcb398eac501a31bd6ad2011e36133a1"


def _jobs() -> list[dict]:
    return json.loads(JOBS.read_text(encoding="utf-8")) if JOBS.exists() else []


def _save(row: dict) -> None:
    rows = [r for r in _jobs() if r["id"] != row["id"]]
    rows.insert(0, row)
    JOBS.write_text(json.dumps(rows[:30], indent=1), encoding="utf-8")


def post(body: dict) -> dict:
    """The payer opens a job: the bid and the locked test's sha256 go to the contract with a deadline."""
    bid = int(body.get("bid") or 0)
    minutes = int(body.get("minutes") or 10)
    if not (0 < bid <= 1_000_000 and 1 <= minutes <= 1440):
        return {"ok": False, "why": "the bid is 1 to 1,000,000 test units and the deadline 1 to 1,440 minutes"}
    jid = f"job-{time.strftime('%m%d%H%M%S', time.gmtime())}"
    test = body.get("test") or JOB_TEST
    if not re.fullmatch(r"test_\w+\.py", test) or not (JOB_DIR / test).is_file():
        return {"ok": False, "why": "no such locked test"}
    test_hash = sha256_file(JOB_DIR / test)
    msg = {"open_job": {"id": jid, "criteria_hash": test_hash, "deadline_ns": str((int(time.time()) + minutes * 60) * 1_000_000_000)}}
    r = call(CONFIG["payer"], CONFIG["token"], "ft_transfer_call", {"receiver_id": CONFIG["contract"], "amount": str(bid), "msg": json.dumps(msg)},
             "1 yoctoNEAR", "100 Tgas")
    row = {"id": jid, "bid": bid, "test_sha256": test_hash, "posted_at": int(time.time()), "txs": {"post": r["tx"]}, "ok": r["ok"]}
    if r["ok"]:
        _save(row)
    return {**r, "id": jid, "test_sha256": test_hash}


def run(body: dict) -> dict:
    """Both agents take the job and submit; the checker runs the locked test on each output and pays only a pass."""
    jid = body.get("id", "")
    row = next((x for x in _jobs() if x["id"] == jid), None)
    if not row:
        return {"ok": False, "why": "no such job on this page"}
    a, b = CONFIG["agents"]["a"], CONFIG["agents"]["b"]
    before = {a: ft_balance(a), b: ft_balance(b)}
    ra = run_agent("a", pass_agent.SOLUTION, jid)
    rb = run_agent("b", fail_agent.SOLUTION, jid)
    t0 = time.time()
    c = checker.check(jid)
    after = {a: ft_balance(a), b: ft_balance(b)}
    rel = next((x.get("release") for x in c["attempts"] if x.get("release")), None)
    row["txs"].update({"take_a": ra["take"]["tx"], "submit_a": ra["submit"]["tx"], "take_b": rb["take"]["tx"], "submit_b": rb["submit"]["tx"]})
    if rel:
        row["txs"]["release"] = rel["tx"]
    row["paid"] = {k: after[k] - before[k] for k in after}
    row["check_to_paid_s"] = round(time.time() - t0, 1)
    row["attempts"] = [{"agent": x["agent"], "passed": x["passed"], "reason": x.get("reason", "")} for x in c["attempts"]]
    _save(row)
    # what a copy of the page with no server shows (Pages): the last run, public data only
    (HERE / "latest.json").write_text(json.dumps({"job": row, "contract": CONFIG["contract"]}, indent=1) + "\n", encoding="utf-8")
    ok = bool(rel and rel["ok"]) and row["paid"][a] == row["bid"] and row["paid"][b] == 0
    return {"ok": ok, "id": jid, "job": row, "agents": [ra, rb], "check": c, "paid": row["paid"], "check_to_paid_s": row["check_to_paid_s"]}


def guard(body: dict) -> dict:
    """Agent B's two guardrails, each refused on chain: a payment over its cap, a release with no passing proof."""
    b = CONFIG["agents"]["b"]
    out = {"ok": True, "tries": []}
    have = view(CONFIG["contract"], "get_budget", {"agent": b})
    if not have:
        g = call(CONFIG["payer"], CONFIG["token"], "ft_transfer_call",
                 {"receiver_id": CONFIG["contract"], "amount": "2", "msg": json.dumps({"budget": {"agent": b, "cap": "1"}})}, "1 yoctoNEAR", "100 Tgas")
        out["budget"] = g
    over = call(b, CONFIG["contract"], "spend", {"to": CONFIG["shop"], "amount": "2"}, gas="10 Tgas")   # an agent key: little gas, its allowance lasts
    out["tries"].append({"what": "helper B pays 2 test units on a cap of 1", **over})
    # the bid of an open job (a fresh one of 1 test unit when none is open), so the refusal is the proof check's
    jid = body.get("id") or next((x["id"] for x in _jobs() if (view(CONFIG["contract"], "get_job", {"id": x["id"]}) or {}).get("state") == "Open"), "")
    if not jid:
        fresh = post({"bid": 1, "minutes": 15})
        out["open_job"] = fresh
        jid = fresh.get("id", "")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)   # agent B's own key: not a checker key
    head = checker.b64u(json.dumps({"alg": "RS256", "kid": CONFIG["checker_kid"], "typ": "JWT"}).encode())
    job = view(CONFIG["contract"], "get_job", {"id": jid}) or {}
    claims = {"iss": checker.ISS, "aud": CONFIG["contract"], "exp": int(time.time()) + 600, "jti": str(uuid.uuid4()), "job": jid, "payee": b,
              "output_sha256": next((x["output_sha256"] for x in job.get("attempts", []) if x["agent"] == b), "0" * 64),
              "criteria_hash": job.get("criteria_hash", "0" * 64)}
    p = checker.b64u(json.dumps(claims).encode())
    forged = f"{head}.{p}." + checker.b64u(key.sign(f"{head}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256()))
    rel = call(CONFIG["relayer"], CONFIG["contract"], "release_job", {"id": jid, "token": forged}, gas="120 Tgas")
    out["tries"].append({"what": f"helper B takes the money of job {jid} with no passing work (a token it signed itself)", **rel})
    out["ok"] = all(not t["ok"] for t in out["tries"])
    return out


def quote(body: dict) -> dict:
    """A 1Click quote for paying the bid in USDC from Base to the payer on NEAR: dry, so no deposit address, no swap."""
    units = int(body.get("usdc_units") or 1_000_000)
    req = {"dry": True, "swapType": "EXACT_INPUT", "slippageTolerance": 100, "originAsset": USDC_BASE, "depositType": "ORIGIN_CHAIN",
           "destinationAsset": USDC_NEAR, "amount": str(units), "refundTo": body.get("refund_to") or "0x0000000000000000000000000000000000000001",
           "refundType": "ORIGIN_CHAIN", "recipient": body.get("recipient") or "0" * 64, "recipientType": "DESTINATION_CHAIN",
           "deadline": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 3600)), "quoteWaitingTimeMs": 0}
    try:
        with urllib.request.urlopen(urllib.request.Request(ONECLICK, json.dumps(req).encode(), {"Content-Type": "application/json", "User-Agent": "knos-near-checkout/1.0"}), timeout=30) as r:
            q = json.loads(r.read())
        return {"ok": True, "request": req, "quote": q.get("quote", {}), "correlationId": q.get("correlationId")}
    except urllib.error.HTTPError as e:
        return {"ok": False, "request": req, "why": f"1Click answered {e.code}: {e.read()[:200].decode(errors='replace')}"}


def status() -> dict:
    rows = []
    for r in _jobs()[:3]:
        j = view(CONFIG["contract"], "get_job", {"id": r["id"]}) or {}
        rows.append({**r, "state": j.get("state"), "paid_to": j.get("paid_to"), "takers": j.get("takers", [])})
    return {"contract": CONFIG["contract"], "agents": CONFIG["agents"], "jobs": rows}


ROUTES = {"/api/job/post": post, "/api/job/run": run, "/api/job/guard": guard, "/api/job/quote": quote, "/api/job/pay": post}
__all__ = ["ROUTES", "status", "base64"]
