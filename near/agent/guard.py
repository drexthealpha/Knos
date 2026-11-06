"""Before an agent pays, it asks the guard about the receiver: allow, warn or block, with every reason read from chain.

    from guard import check; check("someone.testnet")

Reads: does the account exist (an unchecked receiver is blocked); is it on the shared blocklist (blocklist.json, each
entry with its evidence); is it a contract; how old is it (the first block it exists in, by search over archival
blocks); did its code change in about the last day; has this agent paid it before (history.json). Verdicts: block
for a blocklisted or missing account, warn for a contract, a new account or changed code, allow otherwise.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

RPC = "https://archival-rpc.testnet.fastnear.com"
HERE = Path(__file__).resolve().parent
EMPTY_CODE = "11111111111111111111111111111111"
DAY_BLOCKS = 144_000  # about a day at 0.6 s a block
NEW_ACCOUNT_S = 7 * 86_400


def rpc(method: str, params: dict) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for _ in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(RPC, body, {"Content-Type": "application/json"}), timeout=60) as r:
                return json.loads(r.read())
        except OSError:
            time.sleep(2)
    raise RuntimeError(f"{method} failed")


def account_at(acct: str, height: int | None = None) -> dict | None:
    q = {"request_type": "view_account", "account_id": acct, **({"block_id": height} if height else {"finality": "final"})}
    out = rpc("query", q)
    return out.get("result")


def first_block(acct: str, now: int) -> int:
    """The lowest block height at which the account exists"""
    lo, hi = max(1, now - 60 * DAY_BLOCKS), now
    try:
        if account_at(acct, lo):
            return lo  # older than the search window
    except RuntimeError:
        pass       # the archival node did not answer for that block: search on, as for every other height
    while hi - lo > 1:
        mid = (lo + hi) // 2
        try:
            exists = account_at(acct, mid) is not None
        except RuntimeError:
            exists = False
        lo, hi = (lo, mid) if exists else (mid, hi)
    return hi


def block_time(height: int) -> float:
    return int(rpc("block", {"block_id": height})["result"]["header"]["timestamp"]) / 1e9


def check(acct: str, payer_history: Path = HERE / "history.json") -> dict:
    reasons, verdict = [], "allow"
    block = json.loads((HERE / "blocklist.json").read_text(encoding="utf-8"))
    hit = next((b for b in block if b["account"] == acct), None)
    if hit:
        return {"account": acct, "verdict": "block", "reasons": [f"on the shared blocklist: {hit['why']} (evidence {hit['evidence']})"]}
    now_acct = account_at(acct)
    if not now_acct:
        return {"account": acct, "verdict": "block", "reasons": ["no such account: an unchecked receiver is not paid"]}
    head = rpc("block", {"finality": "final"})["result"]["header"]
    now = head["height"]
    if now_acct["code_hash"] != EMPTY_CODE:
        verdict = "warn"
        reasons.append(f"a contract (code {now_acct['code_hash'][:8]})")
        before = account_at(acct, now - DAY_BLOCKS)
        if before and before["code_hash"] != now_acct["code_hash"]:
            reasons.append("its code changed in about the last day")
    first = first_block(acct, now)
    age = int(head["timestamp"]) / 1e9 - block_time(first)
    if age < NEW_ACCOUNT_S:
        verdict = "warn"
        reasons.append(f"created {age / 3600:.1f} h ago (block {first})")
    else:
        reasons.append(f"older than {age / 86_400:.0f} days")
    paid = json.loads(payer_history.read_text(encoding="utf-8")) if payer_history.exists() else []
    reasons.append(f"paid before by this agent: {paid.count(acct)} time(s)")
    return {"account": acct, "verdict": verdict, "reasons": reasons}
