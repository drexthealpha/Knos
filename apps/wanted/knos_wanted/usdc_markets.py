"""Round 9 U8: each claim's two markets in Circle's NEAR testnet USDC, on usdc-market.knos-swarm-1105.testnet (beside
the first claim market, which is never touched). The truth market sits on a standing job of the claim: posted with the
claim's locked test and a 24-hour deadline, open to trade while it stands, then proved in its last 4 hours (both agents
answer, the locked test runs, the passing one is paid) and settled from the job's own state. The demand market asks
whether 10 test USDC are put behind proving the claim within 7 days. Knos seeds each with b ln 2 = 1.386295 test USDC
(b = 2 USDC), sized to what Circle's faucet gives (20 USDC every 2 hours). Visitors trade and back from their own
wallets in the browser (web/usdc-market.js); nothing here touches a visitor's funds. Testnet only."""
from __future__ import annotations

import json
import sys
import threading
import time

from . import near_live as nl

CFG = json.loads((nl.ROOT / "near" / "claims" / "usdc_market.json").read_text(encoding="utf-8"))
UMARKET, USDC = CFG["market"], CFG["token"]
SEED = round(CFG["seed_usdc"] * 1e6)    # 1386295: b ln 2 for b = 2 USDC
DAY, PROVE_IN = 1440, 4 * 3600
_lock = threading.Lock()
log: list = []   # what the last ticks did, newest last (also in the server log)


def _say(what: str, r: dict | None = None) -> None:
    log.append({"at": int(time.time()), "what": what, **({"ok": r.get("ok"), "tx": r.get("tx")} if r else {})})
    del log[:-60]
    print("usdc_markets:", what, (r or {}).get("tx", ""), file=sys.stderr, flush=True)


def _send(contract: str, method: str, args: dict, deposit: str = "0 NEAR") -> dict:
    import common
    with nl._lock:
        common._PREFETCHED.pop(nl.LIVE, None)
        r = common.call(nl.LIVE, contract, method, args, deposit=deposit, gas="150 Tgas")
        common._PREFETCHED.pop(nl.LIVE, None)
    return r


def _seed(mid: str, question: str) -> dict:
    return _send(USDC, "ft_transfer_call", {"receiver_id": UMARKET, "amount": str(SEED),
                                            "msg": json.dumps({"seed": {"id": mid, "question": question[:200]}})}, "1 yoctoNEAR")


def _prove(job_id: str, claim: str) -> bool:
    """Both agents answer the standing job, the locked test runs on each answer, and the passing one is paid."""
    j = nl._jobs()
    sa, sb = nl._solutions(claim)
    j.run_agent("a", sa, job_id)
    j.run_agent("b", sb, job_id)
    c = j.checker.check(job_id, release=True)
    return any(a.get("passed") and (a.get("release") or {}).get("ok") for a in c["attempts"])


def tick() -> None:
    """Open what is missing, prove what is near its deadline, settle what is paid. One at a time; each step on chain."""
    if not _lock.acquire(blocking=False):
        return
    try:
        nl._jobs()
        from common import view
        if not nl.status()["live"]:
            return
        have = int(view(USDC, "ft_balance_of", {"account_id": nl.LIVE}) or 0)
        ids = [str(i) for i in (view(UMARKET, "get_markets", {}) or [])]
        by_test = {c["test"]: n for n, c in nl.CLAIMS.items()}
        by_hash = {h: by_test.get(f, "") for h, f in nl._jobs().checker.tests().items()}
        open_truth: dict = {}
        for mid in (i for i in ids if i.startswith("job:")):
            m = (view(UMARKET, "get_market", {"id": mid}) or {}).get("market") or {}
            job = view(nl._jobs().CONFIG["contract"], "get_job", {"id": mid[4:]}) or {}
            claim = by_hash.get(job.get("criteria_hash", ""))
            if not claim or m.get("outcome") is not None:
                continue
            if job.get("state") in ("Paid", "Released", "Refunded"):
                _say(f"{mid} settled from its job", _send(UMARKET, "resolve", {"id": mid}))
                continue
            open_truth[claim] = mid
            left = int(job.get("deadline_ns", 0)) / 1e9 - time.time()
            if job.get("state") == "Open" and left < PROVE_IN:
                ok = _prove(mid[4:], claim)
                _say(f"{mid} proved: {'passed, paid' if ok else 'no answer passed'}")
                if ok:
                    time.sleep(5)
                    _say(f"{mid} settled from its job", _send(UMARKET, "resolve", {"id": mid}))
        for claim, c in nl.CLAIMS.items():
            if claim not in open_truth and have >= SEED:
                p = nl._jobs().post({"bid": nl.BID, "minutes": DAY, "test": c["test"]})
                if not p.get("ok"):
                    _say(f"{claim}: job not posted: {str(p.get('said') or p.get('why'))[:120]}")
                    continue
                r = _seed("job:" + p["id"], c["question"])
                _say(f"job:{p['id']} opened for {claim}", r)
                have -= SEED if r.get("ok") else 0
            dem = [i for i in ids if i.startswith(f"demand:{claim}:")]
            if not dem and have >= SEED:
                q = f"Will at least {CFG['demand_usdc']} test USDC be put behind proving this claim within 7 days? {c['plain']}"
                r = _seed(f"demand:{claim}:{int(time.time())}", q)
                _say(f"demand market opened for {claim}", r)
                have -= SEED if r.get("ok") else 0
    except Exception as e:  # noqa: BLE001 - the next tick tries again; the log says what stopped
        _say(f"stopped: {type(e).__name__}: {str(e)[:160]}")
    finally:
        _lock.release()


def start() -> None:
    threading.Thread(target=tick, daemon=True).start()
