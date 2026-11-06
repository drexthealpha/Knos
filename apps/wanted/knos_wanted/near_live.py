"""One live NEAR testnet job for any visitor of /near/: the hosted app posts a job from its own capped account
(live.knos-swarm-1105.testnet, test tokens only), both agents take it and submit with their function-call keys, and the
checker's own key (kid checker-live, set by 2 owners, removable by them) releases the bid to the agent that passed.

Caps: KNOS_NEAR_LIVE=on or nothing runs (the kill switch); one run at a time; KNOS_NEAR_LIVE_DAILY runs a UTC day
(default 20); a bid of 1000 test units; the account's token balance. Past a cap the page shows the last run, labelled
a replay. Keys: KNOS_NEAR_KEYS_FILE and KNOS_CHECKER_PEM_FILE, secret files on the host; none is ever sent or printed.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(os.environ.get("KNOS_NEAR_ROOT") or Path(__file__).resolve().parents[3])   # /app in the image
NEAR_WEB = ROOT / "near" / "web"
BID = 1_000_000          # $1.00 of test money (the test token has 6 decimals)
_lock = threading.Lock()
_runs: dict[str, dict] = {}
_day = {"day": "", "n": 0}


def _jobs():
    if str(NEAR_WEB) not in sys.path:
        sys.path.insert(0, str(NEAR_WEB))
    import jobs_api   # near/web/jobs_api.py: the same code the maintainer's machine runs
    return jobs_api


def latest() -> dict:
    try:
        return json.loads((NEAR_WEB / "latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def daily_cap() -> int:
    try:
        return max(0, int(os.environ.get("KNOS_NEAR_LIVE_DAILY") or 20))
    except ValueError:
        return 20


def status() -> dict:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    used = _day["n"] if _day["day"] == today else 0
    on = os.environ.get("KNOS_NEAR_LIVE") == "on" and bool(os.environ.get("KNOS_NEAR_KEYS_FILE"))
    busy = any(r["state"] == "running" for r in _runs.values())
    ready = bool(_ready.get("job"))
    if on and not ready and not _preparing.locked() and used < daily_cap():   # keep one job ready for the next click
        threading.Thread(target=prepare, daemon=True).start()
    return {"live": on, "used_today": used, "cap_today": daily_cap(), "busy": busy, "ready": ready, "bid": BID, "network": "testnet",
            "account": os.environ.get("KNOS_NEAR_PAYER", ""), "money": "test tokens, not real money",
            **({"prepare_error": _ready["error"]} if not ready and _ready.get("error") else {})}


def start() -> dict:
    """A run id to poll, or a replay of the last run with the reason no live run starts."""
    s = status()
    why = ("live runs are switched off" if not s["live"] else "a run is in progress; this one is a replay" if s["busy"]
           else f"today's {s['cap_today']} live runs are used; this one is a replay" if s["used_today"] >= s["cap_today"] else "")
    if not why and not _ready.get("job"):   # a ready job is funded already: no balance to ask for
        try:
            j = _jobs()
            if j.ft_balance(j.CONFIG["payer"]) < BID:
                why = "the live account's test tokens are spent; this one is a replay"
        except Exception as e:  # noqa: BLE001 - testnet unreachable: say so and replay
            why = f"testnet did not answer ({str(e)[:80]}); this one is a replay"
    if why:
        return {"replay": True, "why": why, "last": latest(), **s}
    with _lock:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if _day["day"] != today:
            _day.update(day=today, n=0)
        _day["n"] += 1
        ready = _ready.pop("job", None) if _ready.get("job") and time.time() - _ready["job"]["at"] < READY_FOR else None
    if ready:   # a job both agents have already tried: the visitor's click sends only the payment
        t0 = time.time()
        out = _release(ready)
        threading.Thread(target=prepare, daemon=True).start()
        # kept as a finished run too, so a client that polls GET /api/near/live/{run} (knos near-job 0.4.1, the MCP
        # tool) reads the same answer at once
        with _lock:
            rid = uuid.uuid4().hex[:12]
            _runs[rid] = {**out, "job_id": ready["id"], "started": t0}
        return {"replay": False, "run": rid, **out, **status()}
    with _lock:
        rid = uuid.uuid4().hex[:12]
        _runs[rid] = {"state": "running", "step": "posting the job", "started": time.time()}
    threading.Thread(target=_run, args=(rid,), daemon=True).start()
    return {"replay": False, "run": rid, **status()}


def _run(rid: str) -> None:
    r = _runs[rid]
    try:
        j = _jobs()
        p = j.post({"bid": BID, "minutes": 10})
        r.update(step="agents take the job and submit; the checker runs the locked test", job_id=p.get("id"), post=p.get("url"))
        if not p.get("ok"):
            raise RuntimeError(p.get("said") or p.get("why") or "the job was not posted")
        out = j.run({"id": p["id"]})
        r.update(state="done" if out.get("ok") else "failed", step="paid" if out.get("ok") else "stopped", job=out.get("job"),
                 paid=out.get("paid"), check_to_paid_s=out.get("check_to_paid_s"), seconds=round(time.time() - r["started"], 1))
    except Exception as e:  # noqa: BLE001 - the page shows why the run stopped
        r.update(state="failed", step="stopped", why=str(e)[:300], seconds=round(time.time() - r["started"], 1))
    for k in [k for k, v in _runs.items() if time.time() - v["started"] > 3600]:
        _runs.pop(k, None)


READY_FOR = 3 * 3600      # a ready job is posted with a 4 h deadline and offered for 3 h of it
_ready: dict = {}
_preparing = threading.Lock()


def prepare() -> None:
    """Post a job and have both agents take it and submit, and run the locked test on each output, but pay nobody yet:
    the job then waits, ready, for a visitor's click (start). One at a time."""
    if not _preparing.acquire(blocking=False):
        return
    try:
        if _ready.get("job") or not status()["live"]:
            return
        j = _jobs()
        posted_at = time.time()
        p = j.post({"bid": BID, "minutes": 240})
        if not p.get("ok"):
            raise RuntimeError(f"post: {p.get('said') or p.get('why') or p}"[:200])
        ra = j.run_agent("a", j.pass_agent.SOLUTION, p["id"])
        rb = j.run_agent("b", j.fail_agent.SOLUTION, p["id"])
        c = j.checker.check(p["id"], release=False)
        win = next((x for x in c["attempts"] if x.get("passed")), None)
        if not win:
            said = {"a": [ra.get(k, {}).get("said") for k in ("take", "submit")], "b": [rb.get(k, {}).get("said") for k in ("take", "submit")],
                    "check": [x.get("reason") for x in c["attempts"]]}
            raise RuntimeError(f"no output passed: {json.dumps(said)}"[:200])
        _ready.pop("error", None)
        _ready["job"] = {"id": p["id"], "at": time.time(), "posted_at": posted_at, "criteria_hash": c["criteria_hash"], "payee": win["agent"],
                         "output_sha256": win["output_sha256"],
                         "attempts": [{"agent": x["agent"], "passed": x["passed"], "reason": x.get("reason", "")} for x in c["attempts"]],
                         "txs": {"post": p.get("tx"), "take_a": ra["take"]["tx"], "submit_a": ra["submit"]["tx"],
                                 "take_b": rb["take"]["tx"], "submit_b": rb["submit"]["tx"]}}
        if os.environ.get("KNOS_NEAR_KEYS_FILE"):
            import common   # near/agents/common.py, on the path once jobs_api is loaded
            common.prefetch(j.CONFIG["relayer"])   # the click then only signs and sends the payment
    except Exception as e:  # noqa: BLE001 - no ready job: the next click runs the whole job instead
        _ready["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        print("near_live prepare:", _ready["error"], file=sys.stderr, flush=True)
    finally:
        _preparing.release()


def _release(ready: dict) -> dict:
    j, t0 = _jobs(), time.time()
    try:
        r = j.checker.release_one(ready["id"], ready["payee"], ready["output_sha256"], ready["criteria_hash"])
    except RuntimeError as e:   # a nonce fetched earlier went stale: fetch afresh and send once more
        if "nonce" not in str(e).lower():
            raise
        r = j.checker.release_one(ready["id"], ready["payee"], ready["output_sha256"], ready["criteria_hash"])
    agents = [x["agent"] for x in ready["attempts"]]
    paid = {a: (BID if a == ready["payee"] and r.get("ok") else 0) for a in agents}
    job = {"id": ready["id"], "bid": BID, "txs": {**ready["txs"], **({"release": r["tx"]} if r.get("ok") else {})},
           "paid": paid, "check_to_paid_s": round(time.time() - t0, 1), "attempts": ready["attempts"], "ok": bool(r.get("ok")),
           "posted_at": ready.get("posted_at", ready["at"]), "paid_at": time.time() if r.get("ok") else None}
    return {"state": "done" if r.get("ok") else "failed", "step": "paid" if r.get("ok") else "stopped", "job": job, "paid": paid,
            "seconds": round(time.time() - t0, 1), "why": "" if r.get("ok") else r.get("said", ""), "release_url": r.get("url")}


def get(rid: str) -> dict | None:
    r = _runs.get(rid)
    return None if r is None else {k: v for k, v in r.items() if k != "started"} | {"seconds_so_far": round(time.time() - r["started"], 1)}


# The three live totals under the page's first screen (UX rule H7), each read from the public record of the jobs
# contract on NEAR testnet (NearBlocks v3): the money paid to helpers whose work passed, the jobs paid, and the tries
# (each helper's submit). Kept 2 minutes; on any error the last good answer, or none, is given.
JOBS = "jobs.knos-swarm-1105.testnet"
NB = "https://api-testnet.nearblocks.io/v3/accounts/" + JOBS
RECORD = "https://testnet.nearblocks.io/address/" + JOBS
_totals: dict = {}


def _walk(path: str, pages: int = 40):
    nxt = ""
    for _ in range(pages):
        req = urllib.request.Request(NB + path + "?limit=100" + (f"&next={nxt}" if nxt else ""), headers={"User-Agent": "knos-near-totals"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read())
        yield from body.get("data") or []
        nxt = (body.get("meta") or {}).get("next_page") or ""
        if not nxt:
            return


_refreshing = threading.Lock()


def totals() -> dict:
    """The last answer at once; a stale or missing one is read again in the background (the walk takes about 16 s)."""
    if not (_totals.get("at") and time.time() - _totals["at"] < 120) and not _refreshing.locked():
        threading.Thread(target=_refresh, daemon=True).start()
    return _totals.get("out") or {"pending": True, "record": RECORD}


def _refresh() -> None:
    if not _refreshing.acquire(blocking=False):
        return
    try:
        _totals_read()
    finally:
        _refreshing.release()


def _totals_read() -> dict:
    try:
        rows = [t for t in _walk("/ft-txns")
                if t.get("contract_account_id") == "knos-usdc-1102.testnet" and int(t.get("delta_amount") or 0) < 0
                and str(t.get("involved_account_id", "")).startswith(("agent-a.", "agent-b."))]
        paid = [int(t["delta_amount"]) for t in rows]
        # one dot of the star map per paid job: its time and its transaction, nothing else
        dots = [{"t": int(int(t["block_timestamp"]) // 1_000_000_000), "tx": t.get("transaction_hash", "")} for t in rows]
        tries = sum(1 for t in _walk("/txns") if (t.get("outcomes") or {}).get("status")
                    and any(a.get("method") == "submit" for a in t.get("actions") or []))
        out = {"paid_usd": f"{sum(-x for x in paid) / 1_000_000:.3f}", "jobs_paid": len(paid), "tries": tries,
               "record": RECORD, "record_money": RECORD + "?tab=tokentxns", "token": "test USDC, 6 decimals",
               "read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "dots": dots,
               "explorer": "https://testnet.nearblocks.io/txns/"}
        _totals.update(at=time.time(), out=out)
        return out
    except Exception as e:  # noqa: BLE001 - the record did not answer: say so, keep the last good answer
        return _totals.get("out") or {"error": f"the public record did not answer ({str(e)[:80]})", "record": RECORD}


_guarding = threading.Lock()


def guard() -> dict:
    """The two guardrails on NEAR testnet, live for a visitor: helper B tries to pay 2 test units on a cap of 1, then to
    take a job's money with a token it signed itself instead of a passing check. Both are refused by the contract; the
    answer is each try's words, the contract's refusal and its transaction. One at a time; counted in the day's cap."""
    s = status()
    if not s["live"]:
        return {"ok": False, "why": "live runs are switched off"}
    if s["used_today"] >= s["cap_today"]:
        return {"ok": False, "why": f"today's {s['cap_today']} live runs are used"}
    if not _guarding.acquire(blocking=False):
        return {"ok": False, "why": "a guardrail try is running; try again in a minute"}
    try:
        with _lock:
            today = time.strftime("%Y-%m-%d", time.gmtime())
            if _day["day"] != today:
                _day.update(day=today, n=0)
            _day["n"] += 1
        t0 = time.time()
        out = _jobs().guard({})
        out["seconds"] = round(time.time() - t0, 1)
        return out
    except Exception as e:  # noqa: BLE001 - the page says why
        return {"ok": False, "why": f"testnet did not answer ({str(e)[:120]})"}
    finally:
        _guarding.release()

