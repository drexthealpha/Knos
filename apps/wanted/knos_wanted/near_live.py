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
NEAR_SCRIPTS = ROOT / "near" / "scripts"   # near_counters.py: the full count, which the server reads itself when GitHub is late
BID = 1_000_000          # $1.00 of test money (the test token has 6 decimals)
SAMPLE = "hyperloglog"   # the sample claim (near/claims/claims.json), whose jobs are readied ahead
_lock = threading.Lock()
_runs: dict[str, dict] = {}
_day = {"day": "", "n": 0, "a": 0}   # n: the page's live proofs today; a: the agent call's, which page proofs never use up


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


def agent_cap() -> int:
    """The agent call's own live proofs a day, kept apart from the page's so a call always runs once page proofs are used."""
    try:
        return max(0, int(os.environ.get("KNOS_NEAR_AGENT_DAILY") or 10))
    except ValueError:
        return 10


def status() -> dict:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    used = _day["n"] if _day["day"] == today else 0
    used_a = _day["a"] if _day["day"] == today else 0
    on = os.environ.get("KNOS_NEAR_LIVE") == "on" and bool(os.environ.get("KNOS_NEAR_KEYS_FILE"))
    busy = any(r["state"] == "running" for r in _runs.values())
    job = _ready.get("job")   # read once: a click may take it meanwhile
    ready = bool(job)
    if on and (not ready or not _spare) and not _preparing.locked() and (used < daily_cap() or used_a < agent_cap()):   # keep two jobs ready
        threading.Thread(target=prepare, daemon=True).start()
    return {"live": on, "used_today": used, "cap_today": daily_cap(), "agent_used_today": used_a, "agent_cap_today": agent_cap(), "busy": busy, "ready": ready, "bid": BID, "network": "testnet",
            "account": os.environ.get("KNOS_NEAR_PAYER", ""), "money": "test tokens, not real money",
            **({"prepare_error": _ready["error"]} if not ready and _ready.get("error") else {}),
            **({"next": {k: job.get(k) for k in ("id", "attempts", "txs")}} if job else {})}   # the waiting job's two tries, before the click


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
            _day.update(day=today, n=0, a=0)
        _day["n"] += 1
        ready = _take_ready()
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
_spare: list = []         # a second ready job, so two buyers in a row are both served
_ready: dict = {}
_preparing = threading.Lock()


class ModelCodeFailed(RuntimeError):
    """Agent A's model-written code did not pass the locked test: the order says so and reuses the last verified proof."""


_written: dict = {}   # claim -> agent A's model-written code that last passed its locked test (the code a buyer downloads)
_asked: dict = {}     # claim -> when a job readied in the background last asked the model (at most once in 6 hours: no call in a loop)
ASK_EVERY = 6 * 3600


def _test_text(claim: str) -> str:
    return (ROOT / "near" / "agents" / "job" / CLAIMS[claim]["test"]).read_text(encoding="utf-8")


def _make_job(claim: str = SAMPLE, visitor: str = "") -> dict:
    """One job of a claim, start to just before payment: posted with the claim's locked test, taken and answered by both
    agents (each answer in the job's own folder), each answer run against the test; the passing one is named, nobody is
    paid yet; the claim's market opened. Agent A's code is written by the model on NEAR AI Cloud (one call, cached by
    its input); agent B stays the fixed shortcut that must fail."""
    from . import near_ai
    j = _jobs()
    posted_at = time.time()
    sa, sb = _solutions(claim)
    if not visitor and time.time() - _asked.get(claim, 0) < ASK_EVERY and claim not in _written:
        writer = {"model": None, "note": "the model was asked for this claim less than 6 hours ago and its code did not pass"}
    else:
        if not visitor:
            _asked[claim] = time.time()
        writer = near_ai.write_code(claim, CLAIMS[claim]["quote"], _test_text(claim), visitor)
    if writer.get("code"):
        sa = writer["code"]
    p = j.post({"bid": BID, "minutes": 240, "test": CLAIMS[claim]["test"]})
    if not p.get("ok"):
        raise RuntimeError(f"post: {p.get('said') or p.get('why') or p}"[:200])
    ra = j.run_agent("a", sa, p["id"])
    rb = j.run_agent("b", sb, p["id"])
    c = j.checker.check(p["id"], release=False)
    win = next((x for x in c["attempts"] if x.get("passed")), None)
    if not win and writer.get("code"):
        reason = next((x.get("reason", "") for x in c["attempts"] if x.get("agent") == ra.get("agent")), "")
        near_ai.forget_code(claim, CLAIMS[claim]["quote"], _test_text(claim))
        if writer.get("cut"):
            reason += f" (the answer stopped at the {near_ai.MAX_TOKENS}-token limit)"
        raise ModelCodeFailed(f"agent A's code, written by {writer['model']} (call {writer.get('id')}), failed the locked test: {reason}"[:240])
    if writer.get("code") and win and win.get("agent") == ra.get("agent"):
        _written[claim] = sa
    if not win:
        said = {"a": [ra.get(k, {}).get("said") for k in ("take", "submit")], "b": [rb.get(k, {}).get("said") for k in ("take", "submit")],
                "check": [x.get("reason") for x in c["attempts"]], "refused": c.get("refused")}
        raise RuntimeError(f"no output passed: {json.dumps(said)}"[:200])
    market = _open_market(p["id"], CLAIMS[claim]["question"])
    return {"id": p["id"], "claim": claim, "at": time.time(), "posted_at": posted_at, "criteria_hash": c["criteria_hash"], "payee": win["agent"],
            "market": market, "output_sha256": win["output_sha256"], "code_a": sa,
            "writer": {k: v for k, v in writer.items() if k != "code"},
            "attempts": [{"agent": x["agent"], "passed": x["passed"], "reason": x.get("reason", "")} for x in c["attempts"]],
            "txs": {"post": p.get("tx"), "take_a": ra["take"]["tx"], "submit_a": ra["submit"]["tx"],
                    "take_b": rb["take"]["tx"], "submit_b": rb["submit"]["tx"]}}


def prepare() -> None:
    """Post a HyperLogLog job and have both agents take it and submit, and run the locked test on each output, but pay
    nobody yet: the job then waits, ready, for a visitor's click (start). One at a time."""
    if not _preparing.acquire(blocking=False):
        return
    try:
        if (_ready.get("job") and _spare) or not status()["live"]:
            return
        try:
            fresh = _make_job(SAMPLE)
        except ModelCodeFailed as e:   # the model was asked (now gated for 6 hours): ready the job with agent A's fixed program at once
            print("near_live prepare:", f"ModelCodeFailed: {str(e)[:200]}", file=sys.stderr, flush=True)
            fresh = _make_job(SAMPLE)
        _ready.pop("error", None)
        if _ready.get("job"):
            _spare.append(fresh)
        else:
            _ready["job"] = fresh
        threading.Thread(target=_refresh_last, daemon=True).start()   # the last settled proof, ready for the next visitor
        if os.environ.get("KNOS_NEAR_KEYS_FILE"):
            import common   # near/agents/common.py, on the path once jobs_api is loaded
            common.prefetch(_jobs().CONFIG["relayer"])   # the click then only signs and sends the payment
    except Exception as e:  # noqa: BLE001 - no ready job: the next click runs the whole job instead
        _ready["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        print("near_live prepare:", _ready["error"], file=sys.stderr, flush=True)
    finally:
        _preparing.release()


def _release(ready: dict) -> dict:
    j, t0 = _jobs(), time.time()
    try:
        r = j.checker.release_one(ready["id"], ready["payee"], ready["output_sha256"], ready["criteria_hash"])
    except Exception as e:  # noqa: BLE001 - a nonce fetched earlier went stale (another instance, during a deploy, sent with
        # it; testnet answers InvalidNonce or a bare INVALID_TRANSACTION): fetch afresh and send once more
        if "nonce" not in str(e).lower() and "INVALID_TRANSACTION" not in str(e):
            raise
        r = j.checker.release_one(ready["id"], ready["payee"], ready["output_sha256"], ready["criteria_hash"])
    agents = [x["agent"] for x in ready["attempts"]]
    paid = {a: (BID if a == ready["payee"] and r.get("ok") else 0) for a in agents}
    job = {"id": ready["id"], "bid": BID, "txs": {**ready["txs"], **({"release": r["tx"]} if r.get("ok") else {})},
           "paid": paid, "check_to_paid_s": round(time.time() - t0, 1), "attempts": ready["attempts"], "ok": bool(r.get("ok")),
           "posted_at": ready.get("posted_at", ready["at"]), "paid_at": time.time() if r.get("ok") else None}
    return {"state": "done" if r.get("ok") else "failed", "step": "paid" if r.get("ok") else "stopped", "job": job, "paid": paid,
            "seconds": round(time.time() - t0, 1), "why": "" if r.get("ok") else r.get("said", ""), "release_url": r.get("url")}


def _take_ready() -> dict | None:
    """The ready job (call under _lock), with the spare one moved up in its place; a stale job is dropped."""
    job = _ready.pop("job", None)
    if job and time.time() - job["at"] >= READY_FOR:
        job = None
    if _spare:
        _ready["job"] = _spare.pop(0)
    if job is None and _ready.get("job") and time.time() - _ready["job"]["at"] < READY_FOR:
        job = _ready.pop("job")
        if _spare:
            _ready["job"] = _spare.pop(0)
    return job


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
        for tries in range(4):                         # NearBlocks' free tier answers 429 when asked too fast: wait, ask again
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    body = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or tries == 3:
                    raise
                time.sleep(4 * (tries + 1))
        yield from body.get("data") or []
        nxt = (body.get("meta") or {}).get("next_page") or ""
        if not nxt:
            return


_refreshing = threading.Lock()


def totals() -> dict:
    """The last answer at once; a stale or missing one is read again in the background (the walk takes about 16 s)."""
    if (not (_totals.get("at") and time.time() - _totals["at"] < 120) and not _refreshing.locked()
            and not (_totals.get("error") and time.time() - _totals.get("tried", 0) < 300)):   # refused (429): wait 5 minutes
        threading.Thread(target=_refresh, daemon=True).start()
    if not _totals.get("out"):                         # before the first read: the last snapshot the build shipped, its time on it
        try:
            _totals["out"] = {**json.loads((NEAR_WEB / "totals.json").read_text(encoding="utf-8")), "snapshot": True}
        except (OSError, ValueError):
            pass
    return _totals.get("out") or {"pending": True, "record": RECORD, **({"why": _totals["error"]} if _totals.get("error") else {})}


def _refresh() -> None:
    if not _refreshing.acquire(blocking=False):
        return
    try:
        before = _totals.get("at")
        _totals["tried"] = time.time()
        _totals_read()
        if _totals.get("at") != before:               # a new answer came: no error to say
            _totals.pop("error", None)
    except Exception as e:  # noqa: BLE001 - the last good totals stay; the answer says why the new read failed
        _totals["error"] = f"{type(e).__name__}: {str(e)[:160]}"
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
        _totals["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        return _totals.get("out") or {"error": f"the public record did not answer ({str(e)[:80]})", "record": RECORD}


_guarding = threading.Lock()
_guard_last: dict = {}


def guard_last(why: str) -> dict:
    """The last live guardrail try, marked a replay with why no new one ran; without one, why alone."""
    if not _guard_last.get("tries"):
        return {"ok": False, "why": why}
    return {**_guard_last, "replay": True, "why": why, "age_s": round(time.time() - _guard_last["at"])}


def guard() -> dict:
    """The two guardrails on NEAR testnet, live for a visitor: helper B tries to pay 2 test units on a cap of 1, then to
    take a job's money with a token it signed itself instead of a passing check. Both are refused by the contract; the
    answer is each try's words, the contract's refusal and its transaction. One at a time; counted in the day's cap."""
    s = status()
    if not s["live"]:
        return {"ok": False, "why": "live runs are switched off"}
    if s["used_today"] >= s["cap_today"]:
        return guard_last(f"today's {s['cap_today']} live runs are used")
    if not _guarding.acquire(blocking=False):
        return guard_last("a guardrail try is running now")
    try:
        with _lock:
            today = time.strftime("%Y-%m-%d", time.gmtime())
            if _day["day"] != today:
                _day.update(day=today, n=0, a=0)
            _day["n"] += 1
        t0 = time.time()
        try:
            out = _jobs().guard({})
        except Exception as e:  # noqa: BLE001 - one retry with fresh nonces when a key was used meanwhile
            if "INVALID_TRANSACTION" not in str(e) and "nonce" not in str(e).lower():
                raise
            import common
            common._PREFETCHED.clear()
            time.sleep(2)
            out = _jobs().guard({})
        out["seconds"] = round(time.time() - t0, 1)
        if out.get("tries"):
            _guard_last.clear()
            _guard_last.update(out, at=time.time())
        return out
    except Exception as e:  # noqa: BLE001 - the page says why
        return {"ok": False, "why": f"testnet did not answer ({str(e)[:120]})"}
    finally:
        _guarding.release()


MARKET = "market.knos-swarm-1105.testnet"
TOKEN = "knos-usdc-1102.testnet"
LIVE = "live.knos-swarm-1105.testnet"
SHARE_BUY = 1_000_000        # one buy from the page: $1.00 of test money
_buying = threading.Lock()


def market() -> dict:
    """The claim markets, read from testnet now: the open one (its price in cents) and the settled one's record."""
    rec = json.loads((NEAR_WEB / "market.json").read_text(encoding="utf-8"))
    _jobs()
    from common import view
    out = {"contract": MARKET, "record": rec["settled"], "rule": rec["rule"]}
    for key, mid in (("open", rec["open"]), ("settled", rec["settled"]["id"])):
        v = view(MARKET, "get_market", {"id": mid}) or {}
        m = v.get("market") or {}
        out[key] = {"id": mid, "question": m.get("question"), "yes_c": round(int(v.get("yes_price") or 0) / 10_000),
                    "no_c": round(int(v.get("no_price") or 0) / 10_000), "trades": m.get("trades"), "outcome": m.get("outcome"),
                    "pool_usd": round(int(m.get("pool") or 0) / 1e6, 2)}
    return out


def buy(side: str, market_id: str = "") -> dict:
    """One $1.00 buy of Yes or No on an open claim market (a claim's truth or demand market, else the open claim), sent
    from the app's capped test account; the answer is the shares bought, the new price and the transaction."""
    if side not in ("yes", "no"):
        return {"ok": False, "why": "side: yes or no"}
    if market_id and not (market_id.startswith(("job:job-", "demand:")) and len(market_id) <= 64):
        return {"ok": False, "why": "no such market"}
    s = status()
    if not s["live"]:
        return {"ok": False, "why": "live runs are switched off"}
    if not _buying.acquire(timeout=30):   # buys go one at a time on NEAR: a second waits its turn
        return {"ok": False, "why": "other buys held the line for 30 s; press again"}
    try:
        mid = market_id or json.loads((NEAR_WEB / "market.json").read_text(encoding="utf-8"))["open"]
        _jobs()
        import common
        from common import call, view
        m0 = (view(MARKET, "get_market", {"id": mid}) or {}).get("market")
        if not m0:
            return {"ok": False, "why": "no such market"}
        if m0.get("outcome") is not None:
            return {"ok": False, "why": "this market is settled: its result is final"}
        before = view(MARKET, "get_holding", {"id": mid, "account": LIVE}) or {}
        was = int((view(MARKET, "get_market", {"id": mid}) or {}).get(side + "_price") or 0)
        args = {"receiver_id": MARKET, "amount": str(SHARE_BUY), "msg": json.dumps({"buy": {"id": mid, "side": side}})}
        with _lock:                                       # the next job's prefetched nonce is for the job: a buy asks afresh
            common._PREFETCHED.pop(LIVE, None)
            try:
                r = call(LIVE, TOKEN, "ft_transfer_call", args, deposit="1 yoctoNEAR", gas="100 Tgas")
            except Exception as e:  # noqa: BLE001 - one retry on a stale nonce, anything else is said on the page
                if "INVALID_TRANSACTION" not in str(e) and "InvalidNonce" not in str(e):
                    raise
                time.sleep(2)
                r = call(LIVE, TOKEN, "ft_transfer_call", args, deposit="1 yoctoNEAR", gas="100 Tgas")
            common._PREFETCHED.pop(LIVE, None)            # a nonce fetched while the buy was on its way is spent
        after = view(MARKET, "get_holding", {"id": mid, "account": LIVE}) or {}
        v = view(MARKET, "get_market", {"id": mid}) or {}
        got = int(after.get(side) or 0) - int(before.get(side) or 0)
        return {"ok": r["ok"] and got > 0, "side": side, "paid_usd": SHARE_BUY / 1e6, "shares": round(got / 1e6, 2),
                "yes_c": round(int(v.get("yes_price") or 0) / 10_000), "no_c": round(int(v.get("no_price") or 0) / 10_000),
                "was_c": round(was / 10_000, 1), "now_c": round(int(v.get(side + "_price") or 0) / 10_000, 1),
                "tx": r["tx"], "url": r["url"], **({} if r["ok"] else {"why": r["said"]})}
    except Exception as e:  # noqa: BLE001 - the page says why, in plain words
        busy = "429" in str(e) or "Too Many" in str(e)
        return {"ok": False, "why": "NEAR testnet's public servers are busy right now: try again in a minute" if busy else f"testnet did not answer ({str(e)[:120]})"}
    finally:
        _buying.release()


def product_buy() -> dict:
    """Buy the job's product: $1.00 of test money from the app's capped test account to the helper whose work passed
    (agent A), with no wallet; the answer is the transaction. One at a time, within the day's cap."""
    s = status()
    if not s["live"]:
        return {"ok": False, "why": "live runs are switched off"}
    if not _buying.acquire(timeout=30):   # buys go one at a time on NEAR: a second waits its turn
        return {"ok": False, "why": "other buys held the line for 30 s; press again"}
    try:
        _jobs()
        import common
        from common import CONFIG, call
        maker = CONFIG["agents"]["a"]
        args = {"receiver_id": maker, "amount": str(SHARE_BUY), "memo": "bought: the visitor counter from the HyperLogLog job"}
        with _lock:
            common._PREFETCHED.pop(LIVE, None)
            try:
                r = call(LIVE, TOKEN, "ft_transfer", args, deposit="1 yoctoNEAR", gas="30 Tgas", wait="EXECUTED_OPTIMISTIC")
            except Exception as e:  # noqa: BLE001 - one retry on a stale nonce, anything else is said on the page
                if "INVALID_TRANSACTION" not in str(e) and "InvalidNonce" not in str(e):
                    raise
                time.sleep(2)
                r = call(LIVE, TOKEN, "ft_transfer", args, deposit="1 yoctoNEAR", gas="30 Tgas", wait="EXECUTED_OPTIMISTIC")
            common._PREFETCHED.pop(LIVE, None)
        return {"ok": r["ok"], "paid_usd": SHARE_BUY / 1e6, "to": maker, "tx": r["tx"], "url": r["url"], **({} if r["ok"] else {"why": r["said"]})}
    except Exception as e:  # noqa: BLE001 - the page says why
        return {"ok": False, "why": f"testnet did not answer ({str(e)[:120]})"}
    finally:
        _buying.release()


SEED = 69_314_719            # b * ln 2 for b = 100 test tokens: Knos's most a market can lose


def claim_quote() -> dict:
    """What funding a job's test costs from Base: a dry 1Click quote (no deposit address, nothing moves). Without a
    partner key 1Click keeps 0.2%; the quote's own amounts show it."""
    q = _jobs().quote({"usdc_units": BID})
    if not q.get("ok"):
        return {"ok": False, "why": q.get("why") or "1Click did not answer"}
    qq = q.get("quote") or {}
    a_in, a_out = int(qq.get("amountIn") or BID), int(qq.get("amountOut") or 0)
    return {"ok": True, "send_usdc": round(a_in / 1e6, 6), "arrives_usdc": round(a_out / 1e6, 6), "fee_usdc": round((a_in - a_out) / 1e6, 6),
            "fee_pct": round((a_in - a_out) * 100 / a_in, 2) if a_in else None, "from": "USDC on Base", "to": "USDC on NEAR",
            "dry": True, "correlation": q.get("correlationId")}


def claim_run() -> dict:
    """One claim, start to end, on testnet: a market on the job both helpers already tried, the visitor's $1 on Yes,
    the payment to the helper whose work passed, the market settled from the job's state, the visitor's shares paid."""
    s = status()
    if not s["live"]:
        return {"ok": False, "why": "live runs are switched off"}
    if s["used_today"] >= s["cap_today"]:
        return {"ok": False, "why": f"today's {s['cap_today']} live runs are used"}
    with _lock:
        ready = _take_ready()
        if ready:
            today = time.strftime("%Y-%m-%d", time.gmtime())
            if _day["day"] != today:
                _day.update(day=today, n=0, a=0)
            _day["n"] += 1
    if not ready:
        threading.Thread(target=prepare, daemon=True).start()
        return {"ok": False, "why": "the next job is being readied; try again in a minute"}
    t0, steps = time.time(), []
    try:
        _jobs()
        import common
        from common import call, view
        mid = "job:" + ready["id"]

        def send(what: str, contract: str, method: str, args: dict, deposit: str = "0 NEAR") -> dict:
            with _lock:
                common._PREFETCHED.pop(LIVE, None)
                r = call(LIVE, contract, method, args, deposit=deposit, gas="100 Tgas")
            steps.append({"step": what, "ok": r["ok"], "tx": r["tx"], "url": r["url"], **({} if r["ok"] else {"why": r["said"]})})
            if not r["ok"]:
                raise RuntimeError(f"{what}: {r['said']}")
            return r

        if not ready.get("market"):
            send("market opened", TOKEN, "ft_transfer_call", {"receiver_id": MARKET, "amount": str(SEED), "msg": json.dumps(
                {"seed": {"id": mid, "question": "Will a helper's work pass this job's test?"}})}, "1 yoctoNEAR")
        send("you bought Yes for $1.00", TOKEN, "ft_transfer_call", {"receiver_id": MARKET, "amount": str(SHARE_BUY),
             "msg": json.dumps({"buy": {"id": mid, "side": "yes"}})}, "1 yoctoNEAR")
        held = view(MARKET, "get_holding", {"id": mid, "account": LIVE}) or {}
        for k, label in (("take_a", "Helper A took the job"), ("submit_a", "Helper A sent its work"),
                         ("take_b", "Helper B took the job"), ("submit_b", "Helper B sent its work")):
            tx = (ready.get("txs") or {}).get(k)
            if tx:
                steps.append({"step": label, "ok": True, "tx": tx, "url": common.EXPLORER + tx})
        paid = _release(ready)
        rel = (paid.get("job") or {}).get("txs", {}).get("release")
        steps.append({"step": "Helper A's work passed: paid $1.00" if paid["state"] == "done" else "the payment stopped",
                      "ok": paid["state"] == "done", "tx": rel, "url": paid.get("release_url")})
        if paid["state"] != "done":
            raise RuntimeError(paid.get("why") or "the payment stopped")
        send("market settled Yes, by the job's test", MARKET, "resolve", {"id": mid})
        send("your Yes shares paid", MARKET, "redeem", {"id": mid})
        threading.Thread(target=prepare, daemon=True).start()
        return {"ok": True, "market": mid, "shares": round(int(held.get("yes") or 0) / 1e6, 2), "steps": steps,
                "seconds": round(time.time() - t0, 1)}
    except Exception as e:  # noqa: BLE001 - the page shows the step that stopped and why
        threading.Thread(target=prepare, daemon=True).start()
        return {"ok": False, "why": str(e)[:200], "steps": steps, "seconds": round(time.time() - t0, 1)}



# The research buyer's flow on /near/: paste a paper link, see its claim, how likely the claim holds (the price of its
# market on NEAR testnet) and one offer; order it, and the readied job proves or refutes the claim within seconds.
CLAIM_Q = "Does HyperLogLog count 30,000 visitors within 10% using at most 1.5 kilobytes?"   # the locked test that settles it
# the claims Knos can prove (near/claims/claims.json): each from a real paper, each with its locked test and its two
# agents' code; HyperLogLog's jobs are readied ahead, any other claim's job runs when it is ordered
CLAIMS = {c["name"]: c for c in json.loads((ROOT / "near" / "claims" / "claims.json").read_text(encoding="utf-8"))["claims"]}


def final_verdict(test_passed: bool, reviewer: bool | None = None) -> bool:
    """The verdict: the locked test decides, and an AI reviewer, when one is set, can only make it stricter. A pass it
    rejects becomes a fail; a fail it approves stays a fail. None set today: the reviewer's answer is None."""
    return test_passed and reviewer is not False


def _known(c: dict) -> dict:
    return {"name": c["name"], "plain": c["plain"], "paper": c["paper"], "authors": f"{c['authors']}, {c['year']}", "doi": "https://doi.org/" + c["doi"],
            "quote": c["quote"], "paper_number": c["paper_number"], "locked": c["locked"], "code_name": c["code_name"],
            "check": f"https://github.com/drexthealpha/Knos/blob/main/near/agents/job/{c['test']}", "not_checked": c["not_checked"]}


KNOWN = {c["doi"].lower(): _known(c) for c in CLAIMS.values()} | {"arxiv:" + c["arxiv"]: _known(c) for c in CLAIMS.values() if c.get("arxiv")}


def _solutions(claim: str) -> tuple[str, str]:
    """The two agents' code for a claim: agent A's follows the paper, agent B's is the usual shortcut."""
    if claim == SAMPLE:
        j = _jobs()
        return j.pass_agent.SOLUTION, j.fail_agent.SOLUTION
    d = ROOT / "near" / "agents" / "solutions"
    stem = CLAIMS[claim]["test"][len("test_"):-len(".py")]
    return (d / f"{stem}_a.py").read_text(encoding="utf-8"), (d / f"{stem}_b.py").read_text(encoding="utf-8")
# What fits a paper Knos has no check for yet: the cheapest checker a buyer can order, its price and time as published
# (research note D5, read 10 Nov 2026). Each entry: words that pick it, then what is shown.
CHECKERS = [
    (("protein", "binder", "enzyme", "antibod", "peptide", "binding"),
     {"checker": "a cloud lab that tests designed proteins (Adaptyv Bio)", "price": "from $149 per protein, two replicates included",
      "time": "about 3 weeks", "source": "https://aiwiki.ai/wiki/adaptyv_bio/raw"}),
    (("theorem", "proof", "conjecture", "lemma", "math."),
     {"checker": "an open-source Lean proof agent (NEAR AI)", "price": "about $0.17 per problem ($111 for all 672 PutnamBench problems)",
      "time": "not published", "source": "https://www.kucoin.com/news/flash/near-ai-s-lean-agent-solves-all-672-putnambench-problems-for-111"}),
    (("simulat", "fluid", "finite element", "aerodynam", "stress", "heat transfer"),
     {"checker": "a browser engineering simulator (SimScale Community plan)", "price": "free, 2,000 core-hours",
      "time": "not published", "source": "https://www.simscale.com/pricing/"}),
]
RERUN = {"checker": "a person re-running the paper's code and data", "price": "$330 to $763 per paper (2023 estimate)",
         "time": "not published", "source": "https://labordynamicsinstitute.github.io/crress-book/sessions/6/perignon"}


def _open_market(job_id: str, question: str = CLAIM_Q) -> dict | None:
    """The claim's market for a readied job: seeded by Knos's test account; its price says how likely the claim holds."""
    try:
        _jobs()
        import common
        from common import call
        mid = "job:" + job_id
        args = {"receiver_id": MARKET, "amount": str(SEED), "msg": json.dumps({"seed": {"id": mid, "question": question[:200]}})}
        with _lock:
            common._PREFETCHED.pop(LIVE, None)
            r = call(LIVE, TOKEN, "ft_transfer_call", args, deposit="1 yoctoNEAR", gas="100 Tgas")
            common._PREFETCHED.pop(LIVE, None)
        return {"id": mid, "seed_tx": r["tx"]} if r["ok"] else None
    except Exception as e:  # noqa: BLE001 - no market: the page says so, the job still proves
        print("near_live market:", str(e)[:200], file=sys.stderr, flush=True)
        return None


def _paper_meta(url: str) -> dict:
    """Title and subjects of a paper from its DOI (Crossref) or arXiv id (arXiv's API); empty when neither answers."""
    import re
    import urllib.parse
    doi = re.search(r"(10\.\d{4,9}/[^\s?#]+)", url)
    arx = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", url)
    try:
        if doi:
            req = urllib.request.Request("https://api.crossref.org/works/" + urllib.parse.quote(doi.group(1).rstrip(".")),
                                         headers={"User-Agent": "knos-near-claims"})
            with urllib.request.urlopen(req, timeout=6) as r:
                m = json.loads(r.read())["message"]
            return {"title": " ".join((m.get("title") or [""])[0].split()), "subjects": " ".join(m.get("subject") or [])}
        if arx:
            with urllib.request.urlopen("https://export.arxiv.org/api/query?id_list=" + arx.group(1), timeout=6) as r:
                x = r.read().decode("utf-8", "replace")
            t = re.search(r"<entry>.*?<title>(.*?)</title>", x, re.S)
            cats = " ".join(re.findall(r'term="([^"]+)"', x))
            return {"title": " ".join(t.group(1).split()) if t else "", "subjects": cats}
    except Exception:  # noqa: BLE001 - no metadata: the quote falls back to a re-run of code and data
        return {}
    return {}


_last: dict = {}


def last_proof() -> dict | None:
    """The newest settled market for the sample claim, read from the market contract (kept 5 minutes): its outcome,
    when its job was paid, and its id. None when no market for this claim has settled yet."""
    if _last.get("at") and time.time() - _last["at"] < 300:
        return _last.get("out")
    try:
        _jobs()
        from common import view
        ids = [i for i in (view(MARKET, "get_markets", {}) or []) if str(i).startswith("job:job-")]
        out = None
        for mid in reversed(ids[-12:]):
            m = (view(MARKET, "get_market", {"id": mid}) or {}).get("market") or {}
            if m.get("question") == CLAIM_Q and m.get("outcome") is not None:
                out = {"id": mid, "holds": bool(m["outcome"]), "job": mid[4:],
                       "record": "https://testnet.nearblocks.io/address/" + MARKET}
                break
        _last.update(at=time.time(), out=out)
        return out
    except Exception:  # noqa: BLE001 - no last proof shown: the offer still stands
        return _last.get("out")


_lasting = threading.Lock()


_bal: dict = {}


def _low_balance() -> str:
    """Why no order can be paid now, when the buyer test account holds less than the largest order and a market's seed
    (read at most once a minute); empty when it can."""
    try:
        if not _bal.get("at") or time.time() - _bal["at"] > 60:
            _jobs()
            import common
            _bal.update(at=time.time(), units=common.ft_balance(LIVE))
        need = AMOUNT_MAX * 1_000_000 + SEED
        if _bal["units"] < need:
            return (f"Knos's buyer test account holds {_bal['units'] / 1e6:,.2f} test USDC, under the {need / 1e6:,.2f} an order "
                    "and its market need; it is being topped up. Try again later.")
    except Exception:  # noqa: BLE001 - unread: the payment itself answers
        return ""
    return ""


def _refresh_last() -> None:
    if not _lasting.acquire(blocking=False):
        return
    try:
        _last.pop("at", None)
        last_proof()
    finally:
        _lasting.release()


def claim_look(url: str) -> dict:
    """What a pasted paper link gets: for a paper Knos has a check for, its claim word for word, the price of its market
    and the offer; for any other paper, which checker fits, with its published price and time."""
    import re
    url = (url or "").strip()[:500]
    if not re.match(r"(?i)(https?://\S+|doi:\s*10\.\S+|10\.\d{4,9}/\S+)$", url):
        return {"ok": False, "why": "that is not a paper link: paste a DOI such as https://doi.org/10.46298/dmtcs.3545, or the paper's web address"}
    m = re.search(r"(10\.\d{4,9}/[^\s?#]+)", url)
    a = re.search(r"(?i)(?:arxiv\.org/(?:abs|pdf)/|10\.48550/arxiv\.|arxiv:)(\d{4}\.\d{4,5})", url)
    known = (KNOWN.get(m.group(1).lower().rstrip(".")) if m else None) or (KNOWN.get("arxiv:" + a.group(1)) if a else None)
    if not known:
        meta = _paper_meta(url)
        words = (meta.get("title", "") + " " + meta.get("subjects", "")).lower()
        fit = next((c for keys, c in CHECKERS if any(k in words for k in keys)), RERUN)
        return {"ok": True, "known": False, "title": meta.get("title", ""), "quote": fit}
    if not (_last.get("at") and time.time() - _last["at"] < 300) and not _lasting.locked():
        threading.Thread(target=_refresh_last, daemon=True).start()   # read in the background: the click never waits for it
    out = {"ok": True, "known": True, **known, "amount_default": AMOUNT_DEFAULT, "amount_max": AMOUNT_MAX, "last": _last.get("out"), "reusable": bool(_proofs.get("last"))}
    s = status()
    if s["used_today"] >= s["cap_today"]:
        left = 86400 - int(time.time()) % 86400
        return {**out, "ready": False, "why": f"Today's {s['cap_today']} live proofs on NEAR testnet are used. The next can start at 00:00 UTC, or sooner after a new release, "
                f"in {left // 3600} h {left % 3600 // 60} min."}
    low = _low_balance()
    if low:
        return {**out, "ready": False, "why": low}
    if known["name"] != SAMPLE:   # its job runs when ordered: both agents and the locked test while the buyer watches
        mine = [p for k, p in _proofs.items() if k != "last" and p.get("claim") == known["name"]]
        last = max(mine, key=lambda p: p.get("at", 0)) if mine else None
        paid = ((_board.get("out") or {}).get("claims") or {}).get(known["name"], {}).get("last_proof")   # read from NEAR
        lp = {"holds": bool(last["verdict"].get("holds")), "job": last["job"], "record": last.get("release_url")} if last else (
            {"holds": True, "job": paid, "record": "https://testnet.nearblocks.io/address/" + MARKET} if paid else None)
        return {**out, "last": lp, "reusable": False, "ready": True, "runs_on_order": True}
    job = _ready.get("job")
    mk = (job or {}).get("market")
    if not job and _ready.get("error"):
        threading.Thread(target=prepare, daemon=True).start()
        return {**out, "ready": False, "why": "The next proof could not be readied on NEAR testnet just now; try again in a few minutes."}
    if not job:
        threading.Thread(target=prepare, daemon=True).start()
        return {**out, "ready": True, "readying": True}   # an order waits for the job being readied
    out.update(ready=True, job_id=job["id"])
    if mk:
        out["market"] = {"id": mk["id"], "seed_tx": mk.get("seed_tx")}
    return out


_bal: dict = {}


def balances() -> dict:
    """The accounts that keep the demo up against their floors (scripts/near_balances.py), read at most every 10 minutes."""
    if _bal.get("at") and time.time() - _bal["at"] < 600:
        return _bal["out"]
    import importlib.util
    spec = importlib.util.spec_from_file_location("near_balances", ROOT / "scripts" / "near_balances.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    rows = m.check()
    out = {"ok": all(x["ok"] for x in rows), "rows": rows, "read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _bal.update(at=time.time(), out=out)
    return out


def writer_line(w: dict | None) -> str:
    """The verdict's one line about who wrote agent A's code."""
    if not w:
        return "a fixed program"
    if not w.get("model") or w.get("note"):   # no code from the model: the fixed program's code ran, and the line says why
        return f"a fixed program ({w.get('note') or 'no model answer'}" + (f", call {w['id']}" if w.get("id") else "") + ")"
    private = "private, attestation and signature verified" if w.get("private") else "not verified private"
    return f"{w['model']} on NEAR AI Cloud, call {w.get('id')} ({private})" + (" (a cached answer for the same claim and test)" if w.get("cached") else "")


def ai_line(ai: dict | None) -> str:
    """The verdict's one line about the AI reviewer: what it answered, or why the locked test alone decided."""
    if not ai or ai.get("approve") is None:
        return (ai or {}).get("note") or "none set: the locked test alone decided"
    when = time.strftime("%d %b %H:%M UTC", time.gmtime(ai.get("at") or time.time()))
    said = "approved the pass" if ai["approve"] else "rejected the pass"
    return f"{ai['model']} on NEAR AI Cloud {said}: {(ai.get('reason') or 'no reason given').rstrip('.')}" + (f" (the cached answer of {when} for the same code and test)" if ai.get("cached") else "")


def claim_prove(agent: bool = False, claim: str = SAMPLE, visitor: str = "") -> dict:
    """The ordered proof: the readied job's locked test, both agents' reruns, the payment to the one that passed, the
    verdict beside the paper's own number, and the claim's market settled by the job."""
    import re
    s = status()
    if not s["live"]:
        return {"ok": False, "why": "live runs are switched off"}
    if agent and s["agent_used_today"] >= s["agent_cap_today"]:
        return {"ok": False, "why": f"today's {s['agent_cap_today']} live runs for the agent call are used"}
    if not agent and s["used_today"] >= s["cap_today"]:
        return {"ok": False, "why": f"today's {s['cap_today']} live runs are used"}
    claim = claim if claim in CLAIMS else SAMPLE
    ready = None
    if claim != SAMPLE:   # no readied pool: the job runs now, while the buyer watches
        with _lock:
            today = time.strftime("%Y-%m-%d", time.gmtime())
            if _day["day"] != today:
                _day.update(day=today, n=0, a=0)
            _day["a" if agent else "n"] += 1
        waited = time.time()
        try:
            ready = _make_job(claim, visitor)
        except ModelCodeFailed as e:   # said plainly; the order then shows the last verified proof, marked reused
            return {"ok": False, "model_failed": True, "why": str(e), "seconds": round(time.time() - waited, 1)}
        except Exception as e:  # noqa: BLE001 - the page says which step stopped
            return {"ok": False, "why": f"the job on NEAR testnet stopped: {str(e)[:160]}", "seconds": round(time.time() - waited, 1)}
    else:
        with _lock:
            ready = _take_ready()
            if ready:
                today = time.strftime("%Y-%m-%d", time.gmtime())
                if _day["day"] != today:
                    _day.update(day=today, n=0, a=0)
                _day["a" if agent else "n"] += 1
        waited = time.time()
    while not ready and time.time() - waited < (20 if agent else 90):   # the next job is being readied: wait for it (an agent gets the last proof after 20 s)
        threading.Thread(target=prepare, daemon=True).start()
        time.sleep(3)
        with _lock:
            ready = _take_ready()
            if ready:
                _day["a" if agent else "n"] += 1
    if not ready:
        if str(_ready.get("error", "")).startswith("ModelCodeFailed"):   # the model's code failed the test while the job was readied
            return {"ok": False, "model_failed": True, "why": str(_ready["error"]).split(": ", 1)[1]}
        return {"ok": False, "why": f"the next proof is still being readied after {20 if agent else 90} s; try again in a minute"}
    t0 = time.time()
    ai = None
    if any(a["passed"] for a in ready["attempts"]):   # one model call at most per order, after the test passed and before anyone is paid
        from . import near_ai
        try:
            ai = near_ai.review(claim, CLAIMS[claim]["quote"], _test_text(claim), ready.get("code_a") or _solutions(claim)[0], visitor)
        except Exception as e:  # noqa: BLE001 - a reviewer that breaks leaves the fixed rule
            ai = {"approve": None, "note": f"the AI reviewer stopped ({type(e).__name__}): the locked test alone decided"}
        if ai.get("approve") is False:   # stricter only: a pass it rejects is a fail, and the agent is not paid
            return {"ok": False, "claim": claim, "ai": ai, "why": f"the AI reviewer on NEAR AI Cloud rejected the code that passed the test: {ai.get('reason')}. Nothing was paid",
                    "verdict": {"holds": False, "ai_reviewer": ai_line(ai)}, "seconds": round(time.time() - t0, 1)}
    try:
        paid = _release(ready)
        win = next((a for a in ready["attempts"] if a["passed"]), {})
        got = re.search(r"within ([\d.]+%), in ([\d,]+ bytes)", win.get("reason", "")) if claim == SAMPLE else None
        k = _known(CLAIMS[claim])
        out = {"ok": paid["state"] == "done", "job": paid.get("job"), "attempts": ready["attempts"], "release_url": paid.get("release_url"),
               "criteria_hash": ready["criteria_hash"], "check": k["check"], "claim": claim,
               "verdict": {"paper": k["paper_number"],
                           "measured": f"{got.group(1)} error on 30,000 visitors, {got.group(2)} of memory" if got else win.get("reason", "").removeprefix("Passed: "),
                           "holds": final_verdict(bool(win), (ai or {}).get("approve")), "checked": k["locked"], "not_checked": CLAIMS[claim]["not_checked"],
                           "ai_reviewer": ai_line(ai), "agent_a": writer_line(ready.get("writer"))}, "ai": ai, "writer": ready.get("writer")}
        out["ran_before_s"] = round(waited - ready["at"])   # > 0: the agents ran before the order; < 0: while the buyer waited
        out["market"] = ready.get("market") or _open_market(ready["id"], CLAIMS[claim]["question"])   # opened now if readying could not; settled next, by POST /api/near/claim/settle, once the job is paid
        if out["ok"]:
            rec = {"job": ready["id"], "claim": claim, "attempts": ready["attempts"], "verdict": out["verdict"], "txs": (paid.get("job") or {}).get("txs", {}),
                               "release_url": paid.get("release_url"), "seconds": round(time.time() - t0, 1), "at": time.time()}
            _proofs[ready["id"]] = rec
            if claim == SAMPLE:   # the agent call's reuse, once its day's runs are used, is the sample's last proof
                _proofs["last"] = rec
        if not out["ok"]:
            out["why"] = str(paid.get("why") or f"the job's payment on NEAR testnet stopped at '{paid.get('state')}'")[:200]
        out["seconds"] = round(time.time() - t0, 1)
        out["job_id"] = ready["id"]
        return out
    except Exception as e:  # noqa: BLE001 - the page says which step stopped
        threading.Thread(target=prepare, daemon=True).start()
        return {"ok": False, "why": f"testnet did not answer ({str(e)[:120]})", "seconds": round(time.time() - t0, 1)}


def claim_settle(mid: str) -> dict:
    """Settles a claim's market from its paid job: anyone may ask; the answer is the chain's."""
    if not str(mid).startswith("job:job-"):
        return {"ok": False, "why": "no such market"}
    try:
        _jobs()
        import common
        from common import call, view
        with _lock:
            common._PREFETCHED.pop(LIVE, None)
            try:
                r = call(LIVE, MARKET, "resolve", {"id": mid}, gas="100 Tgas", wait="EXECUTED_OPTIMISTIC")
            except Exception as e:  # noqa: BLE001 - one retry on a stale nonce
                if "INVALID_TRANSACTION" not in str(e) and "nonce" not in str(e).lower():
                    raise
                time.sleep(2)
                common._PREFETCHED.pop(LIVE, None)
                r = call(LIVE, MARKET, "resolve", {"id": mid}, gas="100 Tgas", wait="EXECUTED_OPTIMISTIC")
            common._PREFETCHED.pop(LIVE, None)
        said = str(r.get("said") or "")   # the contract's own answer: "<id> settled Yes by its locked check (Paid)"
        outcome = True if "settled Yes" in said else False if "settled No" in said else None
        for _ in range(4):
            if outcome is not None or not r["ok"]:
                break
            time.sleep(1.5)   # a final read lags the optimistic one by a block or two
            outcome = ((view(MARKET, "get_market", {"id": mid}) or {}).get("market") or {}).get("outcome")
        if r["ok"] and outcome is not None:   # the newest proof is this one
            _last.update(at=time.time(), out={"id": mid, "holds": bool(outcome), "job": mid[4:], "record": "https://testnet.nearblocks.io/address/" + MARKET})
        return {"ok": r["ok"], "settled": outcome, "tx": r["tx"], "url": r["url"], **({} if r["ok"] else {"why": r["said"]})}
    except Exception as e:  # noqa: BLE001 - the page says why
        return {"ok": False, "why": f"testnet did not answer ({str(e)[:120]})"}
    finally:   # the next job is readied only now, so its transactions never race this one
        threading.Thread(target=prepare, daemon=True).start()


def claim_code(claim: str = SAMPLE) -> tuple[bytes, str, str]:
    """A claim's verified code: the version that passed its locked test, its sha256 (the one submitted on NEAR testnet)
    and its file name."""
    import hashlib
    claim = claim if claim in CLAIMS else SAMPLE
    body = (_written.get(claim) or _solutions(claim)[0]).encode("utf-8")   # agent A's model-written code once it has passed
    return body, hashlib.sha256(body).hexdigest(), CLAIMS[claim]["code_name"]


# Round 3: the price, the receipt, the spending cap, the cost of each step, reuse, the counters and one call for agents
AMOUNT_DEFAULT = 10                    # test USDC a buyer puts behind a claim unless they type another amount
AMOUNT_MAX = 100
FEE_OF = 10                            # the split, the market contract's rule: Knos keeps 1 part in 10 (rounded down), the agent the rest


def _units(amount) -> int:
    """The buyer's amount in test USDC units (6 decimals), from 1 to AMOUNT_MAX test USDC."""
    try:
        a = float(amount if amount not in (None, "") else AMOUNT_DEFAULT)
    except (TypeError, ValueError):
        a = AMOUNT_DEFAULT
    return int(round(max(1.0, min(float(AMOUNT_MAX), a)) * 1_000_000))
TREASURY = "knos-payer-1102.testnet"   # Knos's own test account, where the fee is kept
RPC = "https://rpc.testnet.near.org"
_proofs: dict = {}
_price: dict = {}


def _rpc(method: str, params) -> dict:
    import common   # the same RPCs in turn as every other read, so one busy RPC does not stop it
    try:
        return common.rpc(method, params) or {}
    except RuntimeError:
        return {}


def _gas(tx: str, sender: str) -> float | None:
    """The NEAR a transaction burned in fees, from its own outcome on testnet."""
    try:
        r = _rpc("tx", [tx, sender])
        return sum(int(o["outcome"]["tokens_burnt"]) for o in [r["transaction_outcome"], *r["receipts_outcome"]]) / 1e24
    except Exception:  # noqa: BLE001 - the step shows no cost rather than a guessed one
        return None


def near_usd() -> float | None:
    """NEAR's price in US dollars now, kept 10 minutes: CoinGecko, else CoinPaprika (no key needed for either). The source
    used is kept beside it, so the log names it."""
    if _price.get("at") and time.time() - _price["at"] < 600:
        return _price.get("usd")
    _price["at"] = time.time()
    for src, url, pick in (("https://www.coingecko.com/en/coins/near", "https://api.coingecko.com/api/v3/simple/price?ids=near&vs_currencies=usd", lambda d: d["near"]["usd"]),
                           ("https://coinpaprika.com/coin/near-near-protocol/", "https://api.coinpaprika.com/v1/tickers/near-near-protocol", lambda d: d["quotes"]["USD"]["price"])):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "knos-near"}), timeout=10) as r:
                _price.update(usd=round(float(pick(json.loads(r.read()))), 4), source=src)
            return _price["usd"]
        except Exception:  # noqa: BLE001 - the next source, else NEAR only
            continue
    return _price.get("usd")


def action_log(steps: list[tuple[str, str | None, str]]) -> dict:
    """Each step of a proof with what it cost: the fee its transaction burned, in NEAR and in dollars at today's price."""
    from concurrent.futures import ThreadPoolExecutor
    usd = near_usd()
    with ThreadPoolExecutor(max_workers=8) as ex:
        fees = list(ex.map(lambda st: _gas(st[1], st[2]) if st[1] else None, steps))
    rows = [{"step": what, "tx": tx, "url": ("https://testnet.nearblocks.io/txns/" + tx) if tx else None,
             "near": round(f, 6) if f is not None else None, "usd": round(f * usd, 5) if (f is not None and usd) else None}
            for (what, tx, _), f in zip(steps, fees)]
    total = sum(r["usd"] for r in rows if r["usd"] is not None)
    total_near = sum(r["near"] for r in rows if r["near"] is not None)
    return {"rows": rows, "near_usd": usd, "total_usd": round(total, 5) if usd else None, "total_near": round(total_near, 6), "price_source": _price.get("source")}


def claim_cap() -> dict:
    """The spending cap, live: agent B tries to spend 2 test units on a cap of 1, and the jobs contract refuses it."""
    _jobs()
    import common
    from common import CONFIG, call
    b = CONFIG["agents"]["b"]
    why = ""
    for n in range(4):   # agent B's key also signs the next ready job, so a clashing nonce is fetched again and retried
        with _cap_lock:
            common._PREFETCHED.pop(b, None)
            try:
                r = call(b, CONFIG["contract"], "spend", {"to": CONFIG["shop"], "amount": "2"}, gas="10 Tgas", wait="EXECUTED_OPTIMISTIC")
                common._PREFETCHED.pop(b, None)
                return {"ok": not r["ok"], "refused": not r["ok"], "said": r["said"], "tx": r["tx"], "url": r["url"], "agent": b, "cap_units": 1, "tried_units": 2}
            except Exception as e:  # noqa: BLE001 - retried, then the page says the network was busy
                why = str(e)[:120]
        time.sleep(2 + 2 * n)
    return {"ok": False, "why": "the test network was busy for 4 tries", "detail": why}


_cap_lock = threading.Lock()


def _transfer(to: str, units: int, memo: str) -> dict:
    """One test USDC transfer from the buyer test account Knos holds (no wallet needed), with one retry on a stale nonce."""
    import common
    from common import call
    args = {"receiver_id": to, "amount": str(units), "memo": memo}
    with _lock:
        common._PREFETCHED.pop(LIVE, None)
        try:
            r = call(LIVE, TOKEN, "ft_transfer", args, deposit="1 yoctoNEAR", gas="30 Tgas", wait="EXECUTED_OPTIMISTIC")
        except Exception as e:  # noqa: BLE001 - one retry on a stale nonce
            if "INVALID_TRANSACTION" not in str(e) and "nonce" not in str(e).lower():
                return {"ok": False, "why": f"testnet did not answer ({str(e)[:120]})"}
            time.sleep(2)
            common._PREFETCHED.pop(LIVE, None)
            r = call(LIVE, TOKEN, "ft_transfer", args, deposit="1 yoctoNEAR", gas="30 Tgas", wait="EXECUTED_OPTIMISTIC")
        common._PREFETCHED.pop(LIVE, None)
    return {"ok": r["ok"], "tx": r["tx"], "url": r["url"], "usd": units / 1e6, **({} if r["ok"] else {"why": r["said"]})}


_backs_on: dict = {}


def _backs() -> bool:
    """Whether the deployed claim market records what is put behind a claim (its get_backs view answers)."""
    if "on" not in _backs_on or time.time() - _backs_on.get("at", 0) > 600:
        try:
            from common import view
            view(MARKET, "get_backs", {"claim": SAMPLE, "from_index": 0, "limit": 1})
            _backs_on.update(on=True, at=time.time())
        except Exception:  # noqa: BLE001 - an older contract: the two direct transfers
            _backs_on.update(on=False, at=time.time())
    return _backs_on["on"]


def _back(claim: str, units: int, to: list) -> dict:
    """Put `units` behind a claim through the claim market (msg back): recorded there, passed on to `to` in full."""
    import common
    from common import call
    args = {"receiver_id": MARKET, "amount": str(units), "msg": json.dumps({"back": {"claim": claim, "to": to}})}
    with _lock:
        common._PREFETCHED.pop(LIVE, None)
        try:
            r = call(LIVE, TOKEN, "ft_transfer_call", args, deposit="1 yoctoNEAR", gas="100 Tgas", wait="EXECUTED_OPTIMISTIC")
        except Exception as e:  # noqa: BLE001 - one retry on a stale nonce
            if "INVALID_TRANSACTION" not in str(e) and "nonce" not in str(e).lower():
                return {"ok": False, "why": f"testnet did not answer ({str(e)[:120]})"}
            time.sleep(2)
            common._PREFETCHED.pop(LIVE, None)
            r = call(LIVE, TOKEN, "ft_transfer_call", args, deposit="1 yoctoNEAR", gas="100 Tgas", wait="EXECUTED_OPTIMISTIC")
        common._PREFETCHED.pop(LIVE, None)
    return {"ok": r["ok"], "tx": r["tx"], "url": r["url"], **({} if r["ok"] else {"why": r["said"]})}


def claim_pay(amount=None, claim: str = SAMPLE) -> dict:
    """The test USDC the buyer put behind the claim, paid for its first proof: 90% to agent A, whose work passed, and 10%
    to Knos. Sent to the claim market, which records it on chain behind the claim (the demand market settles from that
    record), refuses any other split, and passes both parts on in the same transaction."""
    _jobs()
    import common
    from common import CONFIG
    claim = claim if claim in CLAIMS else SAMPLE
    units = _units(amount)
    share = units - units // FEE_OF
    t_pay = time.time()
    try:
        held = common.ft_balance(LIVE)
    except Exception:  # noqa: BLE001 - unread: the transfers themselves answer
        held = units
    if held < units:
        return {"ok": False, "why": f"the buyer test account holds {held / 1e6:.2f} test USDC, under {units / 1e6:.2f}, so nothing was sent", "usd": units / 1e6}
    if _backs():
        b = _back(claim, units, [[CONFIG["agents"]["a"], str(share)], [TREASURY, str(units - share)]])
        agent = {**b, "usd": share / 1e6}
        fee = {**b, "usd": (units - share) / 1e6}
    else:
        agent = _transfer(CONFIG["agents"]["a"], share, f"knos proof: agent A's share of the amount behind the {claim} claim")
        fee = _transfer(TREASURY, units - share, f"knos proof: Knos's fee from the amount behind the {claim} claim") if agent["ok"] else {"ok": False, "why": "not sent: the agent's share failed"}
    ok = agent["ok"] and fee["ok"]
    if ok:
        _paid_log.append((time.time(), units / 1e6, fee.get("tx"), claim))
    return {"ok": ok, "usd": units / 1e6, "agent": agent, "fee": fee, "tx": fee.get("tx"), "url": fee.get("url"), "from": LIVE,
            "seconds": round(time.time() - t_pay, 1), "fee_account": "https://testnet.nearblocks.io/address/" + TREASURY + "?tab=tokentxns",
            **({} if ok else {"why": agent.get("why") if not agent["ok"] else fee.get("why")})}


def claim_receipt(cap: dict | None, pay: dict, settle: dict | None, job: str = "") -> dict:
    """The receipt after the result: the amount behind the claim, agent A's share and Knos's fee, and what each step cost."""
    last = (_proofs.get(job) if job else None) or _proofs.get("last") or {}   # this order's own proof
    txs = last.get("txs") or {}
    from common import CONFIG
    a, b = CONFIG["agents"]["a"], CONFIG["agents"]["b"]
    steps = [("The job and its locked test posted", txs.get("post"), CONFIG["payer"]), ("Agent A took the job", txs.get("take_a"), a),
             ("Agent A sent its version", txs.get("submit_a"), a), ("Agent B took the job", txs.get("take_b"), b),
             ("Agent B sent its version", txs.get("submit_b"), b)]
    if cap and cap.get("tx"):
        steps.append(("Agent B's over-budget step, refused", cap["tx"], b))
    steps.append(("The job paid agent A for passing", txs.get("release"), CONFIG["relayer"]))
    at, ft = (pay.get("agent") or {}).get("tx"), (pay.get("fee") or {}).get("tx")
    if at and at == ft:   # through the claim market: one transaction splits it
        steps.append(("Your amount, split between agent A and Knos (one transaction)", at, LIVE))
    else:
        if at:
            steps.append(("Agent A's share of your amount", at, LIVE))
        if ft:
            steps.append(("Knos's fee from your amount", ft, LIVE))
    if settle and settle.get("tx"):
        steps.append(("The claim's record on NEAR updated", settle["tx"], LIVE))
    ok = bool(pay.get("ok"))   # a failed payment's transaction is never shown as a receipt
    return {"buyer_usd": pay.get("usd") if ok else 0, "agent_usd": (pay.get("agent") or {}).get("usd") if ok else 0, "knos_usd": (pay.get("fee") or {}).get("usd") if ok else 0,
            "agent_pay_url": (pay.get("agent") or {}).get("url") if ok else None, "fee_url": (pay.get("fee") or {}).get("url") if ok else None,
            "job_pay_url": last.get("release_url"), "log": action_log(steps)}


def claim_reuse(job: str = "") -> dict:
    """A second proof of the same order: the verified result of its first proof (its job) is reused, so no agent reruns it."""
    last = _proofs.get(job) if job else None   # this order's own first proof, never another buyer's
    if not last:
        return {"ok": False, "why": "this order has no paid first proof to reuse yet" if job else "name the order's job: order the first proof"}
    return {"ok": True, "free": True, "reused": last["job"], "verdict": last["verdict"], "first_url": last.get("release_url"),
            "saved": {"agent_usd": BID / 1e6, "first_answer_seconds": last["seconds"]}}   # the first proof's run to its answer, measured on the server


_snap: dict = {}
_snapping = threading.Lock()
_top: dict = {}             # the highest counts this server has answered, so a page never sees them go back
_paid_log: list = []      # this server's own paid first proofs since it started: (unix time, test USDC moved, fee tx)


def _late(out: dict | None) -> bool:
    """A count read over 15 minutes ago, or none."""
    try:
        import calendar
        return not out or time.time() - calendar.timegm(time.strptime(out["read_at"], "%Y-%m-%dT%H:%M:%SZ")) > 900
    except (KeyError, ValueError):
        return True


def _direct() -> None:
    """Read the full count here, from the same public record and with the same code GitHub Actions runs, when GitHub's
    copy is late or cannot be fetched from this server's address."""
    try:
        if str(NEAR_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(NEAR_SCRIPTS))
        import near_counters
        out = near_counters.read()
        if _late(_snap.get("out")) or out["read_at"] > (_snap.get("out") or {}).get("read_at", ""):
            _snap.update(at=time.time(), out=out)
    except Exception as e:  # noqa: BLE001 - the copy held stays in use
        print("near_live counters (direct):", str(e)[:160], file=sys.stderr, flush=True)


def _snapshot(direct: bool = False) -> dict | None:
    """The full count of NEAR testnet's public record, read every 10 minutes by GitHub Actions (near/scripts/
    near_counters.py, published as the "near-counters" check run); kept here 5 minutes. When that copy is late or GitHub
    refuses this server, and the caller can wait, the server reads the record itself."""
    if _snap.get("at") and time.time() - _snap["at"] < 300 and not (direct and _late(_snap.get("out"))):
        return _snap.get("out")
    gh = "https://api.github.com/repos/drexthealpha/Knos/"
    try:
        def get(u: str) -> dict:
            req = urllib.request.Request(gh + u, headers={"User-Agent": "knos-near-counters", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        run = (get("actions/workflows/near-counters.yml/runs?status=success&per_page=1").get("workflow_runs") or [])[0]
        crs = [x for x in get(f"commits/{run['head_sha']}/check-runs?check_name=near-counters&per_page=100").get("check_runs") or [] if x["name"] == "near-counters"]
        cr = max(crs, key=lambda x: x.get("completed_at") or "")   # every read is published on the same commit: the newest one
        _snap.update(at=time.time(), out=json.loads(cr["output"]["summary"]))
    except Exception as e:  # noqa: BLE001 - the last snapshot read stays in use
        print("near_live counters:", str(e)[:160], file=sys.stderr, flush=True)
        _snap["at"] = time.time() - (0 if "rate limit" in str(e) else 240)   # ask again in a minute; in 5 when GitHub's hourly limit is used
    if direct and _late(_snap.get("out")):
        _direct()
    return _snap.get("out")


def _resnap() -> None:
    if _snapping.acquire(blocking=False):
        try:
            _snapshot(direct=True)
        finally:
            _snapping.release()


if os.environ.get("KNOS_NEAR_LIVE") == "on":   # the hosted server holds a copy from its start: the first visitor waits on nothing
    threading.Thread(target=_resnap, daemon=True).start()


def counters() -> dict:
    """Live counters: the full count of the public record (the snapshot above), plus every first proof this server has
    paid since that count was read, each a transfer NEAR confirmed (its log). Lost is the record's own figure."""
    base = _snap.get("out")
    if not (_snap.get("at") and time.time() - _snap["at"] < 300) and not _snapping.locked():
        threading.Thread(target=_resnap, daemon=True).start()   # read again in the background; answer from the copy held
    if not base:
        base = _snapshot()
    if not base:   # the record could not be read here: the page reads it and adds this server's confirmed payments
        return {"pending": True, "paid": [[round(x[0], 3), x[1]] for x in _paid_log]}
    since = int(base.get("as_of_ns") or 0) / 1e9
    new = [x for x in _paid_log if x[0] > since]
    proofs, usd = base["proofs"] + len(new), round(base["usd"] + sum(x[1] for x in new), 6)
    if proofs < _top.get("proofs", 0) or (proofs == _top.get("proofs") and usd < _top.get("usd", 0)):
        proofs, usd = _top["proofs"], _top["usd"]   # a fresh read can lag what this server already counted: never go back
    _top.update(proofs=proofs, usd=usd)
    return {"proofs": proofs, "usd": usd, "lost_usd": base["lost_usd"],
            "read_at": base.get("read_at"), "since_read": len(new), "record": base.get("record"),
            "paid": [[round(x[0], 3), x[1]] for x in _paid_log],
            "by_claim": _by_claim(base.get("by_claim") or {SAMPLE: {"proofs": base["proofs"], "usd": base["usd"]}}, new),
            "receipts": [[x[2], None, int(x[0]), x[3]] for x in reversed(new)] + (base.get("receipts") or [])}


def _by_claim(read: dict, new: list) -> dict:
    """Each claim's paid proofs and test USDC behind it: the full read, plus this server's payments since."""
    out = {k: dict(v) for k, v in read.items()}
    for x in new:
        b = out.setdefault(x[3], {"proofs": 0, "usd": 0.0})
        b["proofs"] += 1
        b["usd"] = round(b["usd"] + x[1], 6)
    return out


# The claims board: each claim's two markets on NEAR testnet, read from the claim market contract. The truth market
# ("job:<id>", the claim's newest job) shows its price while the locked test has not run and only its result after; the
# demand market ("demand:<claim>:<opened>") asks whether 100 test USDC are put behind proving the claim within 7 days,
# and settles from the contract's own record of what was put behind it. A claim with no open demand market gets one,
# seeded by Knos's test account. Each market says its trader count, so a thin market says it is thin.
WEEK = 7 * 24 * 3600
_board: dict = {}
_job_claim: dict = {}   # "job:<id>" -> (its claim, its last state read)
_boarding = threading.Lock()


_settled: dict = {}   # a settled market never changes: read once, kept for good


def _market_view(mid: str) -> dict | None:
    from common import view
    if mid in _settled:
        return _settled[mid]
    try:
        v = view(MARKET, "get_market", {"id": mid}) or {}
    except Exception:  # noqa: BLE001 - not read this time (a busy public RPC): the board keeps going
        return None
    m = v.get("market")
    if not m:
        return None
    try:
        traders = int(view(MARKET, "get_traders", {"id": mid}) or 0)
    except Exception:  # noqa: BLE001 - an older contract counts no traders
        traders = None
    out = {"id": mid, "question": m.get("question"), "trades": m.get("trades", 0), "traders": traders, "outcome": m.get("outcome")}
    if m.get("outcome") is not None:
        _settled[mid] = out
    if m.get("outcome") is None:   # the price only before the result
        out["yes_cents"] = round(int(v.get("yes_price") or 0) / 10_000, 1)
    return out


def _seed_demand(claim: str) -> str | None:
    """Open the claim's demand market for the next 7 days, seeded by Knos's test account (b ln 2 test USDC)."""
    import common
    from common import call
    mid = f"demand:{claim}:{int(time.time())}"
    q = f"Will at least 100 test USDC be put behind proving this claim within 7 days? {CLAIMS[claim]['plain']}"[:200]
    args = {"receiver_id": MARKET, "amount": str(SEED), "msg": json.dumps({"seed": {"id": mid, "question": q}})}
    with _lock:
        common._PREFETCHED.pop(LIVE, None)
        r = call(LIVE, TOKEN, "ft_transfer_call", args, deposit="1 yoctoNEAR", gas="100 Tgas")
        common._PREFETCHED.pop(LIVE, None)
    return mid if r["ok"] else None


def _read_board() -> None:
    if not _boarding.acquire(blocking=False):
        return
    try:
        _jobs()
        from common import view
        ids = [str(i) for i in (view(MARKET, "get_markets", {}) or [])]
        now = int(time.time())
        hashes = {CLAIMS[c]["test"]: c for c in CLAIMS}
        tests = _jobs().checker.tests()   # sha256 -> test file
        from concurrent.futures import ThreadPoolExecutor
        # each claim's newest job: the ones this server made first, then the newest 16 jobs on chain, read side by side
        mine = {}
        for p in [*[v for k, v in _proofs.items() if k != "last"], *([_ready["job"]] if _ready.get("job") else [])]:
            c = p.get("claim", SAMPLE)
            jid = p.get("job") or p.get("id")
            if jid and (c not in mine or jid > mine[c]):
                mine[c] = jid
        # every job market's claim, read once (a job's locked test never changes), its state read again while it can change
        jobs = sorted((i for i in ids if i.startswith("job:job-")), reverse=True)   # the job id holds its UTC time: newest first
        todo = [m for m in jobs if m not in _job_claim or _job_claim[m][1] != "Paid"][:40]   # 40 a read: the public RPC limits bursts

        def job_of(mid: str):
            try:
                return mid, view(_jobs().CONFIG["contract"], "get_job", {"id": mid[4:]}) or {}
            except Exception:  # noqa: BLE001 - read again at the next refresh
                return mid, None
        with ThreadPoolExecutor(3) as ex:
            for mid, j in ex.map(job_of, todo):
                if j is not None:
                    _job_claim[mid] = (hashes.get(tests.get(j.get("criteria_hash", ""), ""), ""), j.get("state", ""))
        paid = {}   # each claim's newest paid job: its last proof, held
        for mid in jobs:
            c, state = _job_claim.get(mid, ("", ""))
            if c and (c not in mine or mid[4:] > mine[c]):
                mine[c] = mid[4:]
            if c and state == "Paid" and (c not in paid or mid[4:] > paid[c]):
                paid[c] = mid[4:]
        for p in [v for k, v in _proofs.items() if k != "last"]:
            c = p.get("claim", SAMPLE)
            if c not in paid or p["job"] > paid[c]:
                paid[c] = p["job"]
        with ThreadPoolExecutor(8) as ex:
            views = dict(zip(mine, ex.map(lambda jid: _market_view("job:" + jid), mine.values())))
        truth = {c: v for c, v in views.items() if v}
        backs_on = _backs()
        board = {}
        for c in CLAIMS:
            dem = sorted((i for i in ids if i.startswith(f"demand:{c}:")), key=lambda i: int(i.rsplit(":", 1)[1]))
            d = _market_view(dem[-1]) if dem else None
            # a new demand market only when the chain lists none for the claim, or its newest was read as settled: a market
            # that could not be read this time is never taken for a missing one (each seed costs 69.31 test USDC)
            if backs_on and status()["live"] and (not dem or (d is not None and d.get("outcome") is not None)):
                try:
                    mid = _seed_demand(c)
                    d = _market_view(mid) if mid else d
                except Exception as e:  # noqa: BLE001 - shown as not open yet
                    print("near_live demand market:", str(e)[:160], file=sys.stderr, flush=True)
            if d:
                opened = int(d["id"].rsplit(":", 1)[1])
                try:
                    got = view(MARKET, "get_outside", {"claim": c, "from": opened, "until": opened + WEEK}) or {}   # outside backers only
                except Exception:  # noqa: BLE001 - not read this time
                    got = {}
                d.update(opened=opened, closes=opened + WEEK, behind_usd=int(got.get("total") or 0) / 1e6, backs=got.get("count", 0), bar_usd=100)
                # the bar met, or the week over: anyone may settle it, and the board does, from the contract's own record
                if d.get("outcome") is None and (d["behind_usd"] >= 100 or now > opened + WEEK) and status()["live"]:
                    try:
                        import common
                        from common import call
                        with _lock:
                            common._PREFETCHED.pop(LIVE, None)
                            r = call(LIVE, MARKET, "resolve", {"id": d["id"]}, gas="100 Tgas")
                            common._PREFETCHED.pop(LIVE, None)
                        if r.get("ok"):
                            d = _market_view(d["id"]) or d
                            d.update(opened=opened, closes=opened + WEEK, behind_usd=int(got.get("total") or 0) / 1e6, backs=got.get("count", 0), bar_usd=100, settle_tx=r.get("url"))
                    except Exception as e:  # noqa: BLE001 - settled at a later refresh
                        print("near_live demand settle:", str(e)[:160], file=sys.stderr, flush=True)
            try:
                all_ = (view(MARKET, "get_backed", {"claim": c, "from": 0, "until": now}) or {}) if backs_on else {}
            except Exception:  # noqa: BLE001 - not read this time
                all_ = {}
            board[c] = {"truth": truth.get(c), "last_proof": paid.get(c), "demand": d, "behind_usd": int(all_.get("total") or 0) / 1e6, "proofs": all_.get("count", 0)}
        _board.update(at=time.time(), out={"claims": board, "read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "contract": MARKET})
    except Exception as e:  # noqa: BLE001 - the board held stays in use
        print("near_live board:", str(e)[:200], file=sys.stderr, flush=True)
    finally:
        _boarding.release()


if os.environ.get("KNOS_NEAR_LIVE") == "on":   # the board is read from the server's start: the first visitor waits on nothing
    threading.Thread(target=_read_board, daemon=True).start()


def claims_board() -> dict:
    """Every claim with its two markets and the test USDC behind it, read from NEAR testnet (kept a minute). The sample
    claim's paid proofs before the claim market kept its record are added from the counters' full read."""
    if not (_board.get("at") and time.time() - _board["at"] < 60):
        threading.Thread(target=_read_board, daemon=True).start()
    out = json.loads(json.dumps(_board.get("out") or {"claims": {}}))
    base = _snap.get("out") or {}
    if out["claims"].get(SAMPLE) is not None and base.get("proofs") is not None:
        s = out["claims"][SAMPLE]
        s["before_record"] = {"proofs": base["proofs"], "usd": base["usd"]}
    for c, k in CLAIMS.items():
        out["claims"].setdefault(c, {})
        out["claims"][c].update(plain=k["plain"], paper=k["paper"], authors=f"{k['authors']}, {k['year']}", doi=k["doi"])
    return out


def claim_flow(url: str, amount=None, visitor: str = "") -> dict:
    """The whole flow in one call, for an agent: look up the paper, prove its claim, pay, settle, and the receipt."""
    look = claim_look(url)
    if not look.get("known"):
        return {"ok": True, "look": look, "next": "no check for this paper yet: the quote says which checker fits"}
    proof = claim_prove(agent=True, claim=look.get("name", SAMPLE), visitor=visitor)   # its own daily runs: page proofs never use them up
    if not proof.get("ok"):
        why = str(proof.get("why") or (f"the next proof could not be readied: {_ready['error']}" if _ready.get("error") else "the proof stopped before its answer"))
        last = _proofs.get("last")
        if not last:   # after a restart: the claim's last paid proof as NEAR records it
            paid = ((_board.get("out") or {}).get("claims") or {}).get(look.get("name", SAMPLE), {}).get("last_proof")
            if paid:
                last = {"job": paid, "verdict": {"holds": True, "ai_reviewer": "not run again: a reused proof, read from NEAR"},
                        "release_url": "https://testnet.nearblocks.io/address/" + MARKET}
        if last and (("live runs" in why and "are used" in why) or "still being readied" in why or proof.get("model_failed")):   # no live run now: the last verified proof, reused and marked so, no money moved
            return {"ok": True, "reused": True, "job": last["job"], "claim": look.get("quote"), "verdict": last["verdict"],
                    "code": "https://knos.onrender.com/api/near/claim/code", "first_proof": last.get("release_url"), "cap": None,
                    "paid": False, "settled": False, "receipt": None,
                    "why_not_settled": f"{why}: this is the last verified proof ({last['job']}), reused; no new run and no money moved"}
        return {"ok": False, "claim": look.get("quote"), "verdict": None, "code": None, "cap": None, "paid": False, "settled": False,
                "why_not_settled": why, "receipt": None, "why": why}
    cap = claim_cap()
    pay = claim_pay(amount, proof.get("claim", SAMPLE))
    settle = claim_settle((proof.get("market") or {}).get("id", "")) if proof.get("market") else None
    done = bool(cap.get("ok") and pay.get("ok") and settle and settle.get("ok") and settle.get("settled") is not None)
    why = "" if done else ("spending cap step: " + str(cap.get("why") or "not refused on record")) if not cap.get("ok") else \
        ("payment: " + str(pay.get("why") or "refused")) if not pay.get("ok") else ("record: " + str((settle or {}).get("why") or "no record for this job"))
    return {"ok": True, "job": str(proof.get("job_id") or ""), "claim": look.get("quote"), "claim_name": proof.get("claim"), "verdict": proof.get("verdict"),
            "test_sha256": proof.get("criteria_hash"),
            "ai": {k: (proof.get("ai") or {}).get(k) for k in ("model", "id", "approve", "cached", "tokens_in", "tokens_out", "cost_usd", "finish", "private", "attestation", "signature", "note")},
            "writer": {k: (proof.get("writer") or {}).get(k) for k in ("model", "id", "cached", "tokens_in", "tokens_out", "cost_usd", "finish", "private", "attestation", "signature", "note")},
            "code": "https://knos.onrender.com/api/near/claim/code?claim=" + str(proof.get("claim") or SAMPLE),
            "cap": cap, "paid": bool(pay.get("ok")), "settled": done, **({} if done else {"why_not_settled": why}), "receipt": claim_receipt(cap, pay, settle, str(proof.get("job_id") or ""))}


def claim_finish(cap: dict | None, market: str = "", amount=None, job: str = "") -> dict:
    """After the answer of a first proof: the amount behind the claim paid, the claim's record updated, the receipt."""
    t0 = time.time()
    pay = claim_pay(amount, (_proofs.get(job) or {}).get("claim", SAMPLE))
    settle = claim_settle(market) if market else None
    return {"ok": pay.get("ok", False), "pay": pay, "settle": settle, "receipt": {**claim_receipt(cap, pay, settle, job), "job": job}, "seconds": round(time.time() - t0, 1)}


def claim_try(n: int) -> dict:
    """The verified code at work: the version that passed the locked test counts n different visitors (each seen twice,
    as in the test), and says how close its count is and how many bytes it keeps."""
    import pickle
    n = max(1_000, min(int(n), 100_000))
    import types
    mod = sys.modules.get("solution")
    if mod is None or not hasattr(mod, "Counter"):   # the module the locked test imports, so its saved size is the test's
        mod = types.ModuleType("solution")
        exec(compile(_jobs().pass_agent.SOLUTION, "visitor_counter.py", "exec"), mod.__dict__)   # noqa: S102 - Knos's own verified code
        sys.modules["solution"] = mod
    t0, c = time.time(), mod.Counter()
    tag = f"{time.time_ns()}"
    for _ in range(2):
        for i in range(n):
            c.add(f"visitor-{tag}-{i}")
    got = c.count()
    return {"ok": True, "visitors": n, "counted": round(got), "off_pct": round(abs(got - n) / n * 100, 1),
            "bytes": len(pickle.dumps(c)), "seconds": round(time.time() - t0, 1)}


_plain: dict = {}


def plain_page() -> dict:
    """The small model's page about the paper (product-page.yml), from its public check run; held 10 minutes."""
    if _plain.get("at") and time.time() - _plain["at"] < 600 and _plain.get("out"):
        return _plain["out"]
    if time.time() - _plain.get("failed", 0) < 600:   # GitHub refused this server: ask again in 10 minutes, not on every visit
        return _plain.get("out") or {"ok": False, "why": "the plain-words page could not be read just now"}
    gh = "https://api.github.com/repos/drexthealpha/Knos/"
    try:
        def get(u: str) -> dict:
            req = urllib.request.Request(gh + u, headers={"User-Agent": "knos-near-plain", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        for run in get("actions/workflows/product-page.yml/runs?status=success&per_page=5").get("workflow_runs") or []:
            cr = next((x for x in get(f"commits/{run['head_sha']}/check-runs?check_name=product-page").get("check_runs") or [] if x["name"] == "product-page"), None)
            if cr:
                _plain.update(at=time.time(), out={**json.loads(cr["output"]["summary"]), "url": cr["html_url"]})
                return _plain["out"]
    except Exception as e:  # noqa: BLE001 - the page says it could not be read
        print("near_live plain page:", str(e)[:160], file=sys.stderr, flush=True)
        _plain["failed"] = time.time()
    return _plain.get("out") or {"ok": False, "why": "the plain-words page could not be read just now"}


_tests: dict = {}


def tests_status() -> dict:
    """The full test suite's latest finished run on main (GitHub Actions, tests.yml), held 5 minutes: passed or not, its link."""
    if _tests.get("at") and time.time() - _tests["at"] < 300 and _tests.get("out"):
        return _tests["out"]
    if time.time() - _tests.get("failed", 0) < 600:   # GitHub refused this server: ask again in 10 minutes, not on every visit
        return _tests.get("out") or {"why": "the test record could not be read just now"}
    try:
        req = urllib.request.Request("https://api.github.com/repos/drexthealpha/Knos/actions/workflows/tests.yml/runs?branch=main&status=completed&per_page=10",
                                     headers={"User-Agent": "knos-near-tests", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            runs = [x for x in json.loads(r.read()).get("workflow_runs") or [] if x.get("conclusion") in ("success", "failure")]
        run = runs[0]
        _tests.update(at=time.time(), out={"passed": run["conclusion"] == "success", "url": run["html_url"], "sha": run["head_sha"][:8], "at": run["updated_at"]})
    except Exception as e:  # noqa: BLE001 - the page says it could not be read
        print("near_live tests:", str(e)[:160], file=sys.stderr, flush=True)
        _tests["failed"] = time.time()
    return _tests.get("out") or {"why": "the test record could not be read just now"}
