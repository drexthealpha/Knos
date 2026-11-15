#!/usr/bin/env python3
"""agent_pr_index.py -- the Agent PR Index: of PRs by AI coding agents whose body claims tests/CI pass, what did CI
actually say at the head SHA? Same agents, claim regexes and CI verdict as agent_pr_ci.py.

Two steps, so the Pages build never scans:

    python scripts/agent_pr_index.py scan --rows rows.json     # >=2,000 PRs (slow; .github/workflows/index.yml, 6 h)
    python scripts/agent_pr_index.py build --rows rows.json --out index.json   # offline + devnet proofs
    python scripts/agent_pr_index.py attest --out _site/index.json   # Pages build: re-check root, attest on SAS

index.yml uploads index.json as the asset of a GitHub Release tagged index-<date> (a release, not a data commit);
network.yml downloads the newest one into the Pages site and attests its root with env KNOS_ATTEST_KEY.

The scan searches each agent over date windows (GitHub caps a query at 1,000 results), drops PRs on repos owned by
the PR's author or the human who assigned the agent (self repos are not a market observation; the count is kept),
and classifies CI at each head SHA. The build writes:

    {"date", "window", "n_prs", "excluded_self_repo", "overall": {...}, "agents": {name: {claimed_green,
     actually_failed, share, ci95: [lo, hi], proven}}, "proven": {worker: distinct funders}, "prs": [...], "root",
     "attestation"?, "signature"?, "attest_error"?}

`ci95` is the 95% Wilson interval of `share`. `proven` counts, per worker, the distinct funders (buyer wallets) that
paid it through a verified proof (the escrow's verify_release, read from devnet): ten payments from one funder
count once. `root` is the sha256 Merkle root over the per-PR records; with env KNOS_ATTEST_KEY it is attested on
Solana devnet SAS, so anyone can check the published list is the one that was counted.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_pr_ci  # noqa: E402
from knos.proof.receipt import merkle_root  # noqa: E402

DEVNET = "https://api.devnet.solana.com"
PR_KEYS = ("agent", "repo", "number", "sha", "class", "failed_checks", "phrase")
COMPLETED = ("failed", "passed", "other")
VERIFY_RELEASE = 11  # escrow instruction tag (knos.jobs.sol.verify_release): paid on a verified proof
WORKER_TOKEN, BUYER = 4, 8  # its account positions (knos.jobs.sol._payout)


def record(c):
    return {k: c.get(k) for k in PR_KEYS}


def leaf(rec):
    return hashlib.sha256(json.dumps(rec, sort_keys=True, ensure_ascii=False).encode()).digest()


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes in n trials; None when n == 0."""
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, mid - half), 4), round(min(1.0, mid + half), 4)]


def tally(mine):
    green = sum(1 for r in mine if r["class"] in COMPLETED)
    failed = sum(1 for r in mine if r["class"] == "failed")
    return {"claimed_green": green, "actually_failed": failed,
            "share": round(failed / green, 4) if green else None, "ci95": wilson(failed, green)}


def distinct_funders(payments):
    """payments: [{"worker", "funder", "verified"}]. Reputation counts each funder once: {worker: n distinct}."""
    out = {}
    for p in payments:
        if p.get("verified") and p.get("worker") and p.get("funder"):
            out.setdefault(p["worker"], set()).add(p["funder"])
    return {w: len(f) for w, f in sorted(out.items())}


def payments_from_tx(tx, program):
    """The verify_release payouts in one confirmed devnet transaction (json encoding): worker token account and the
    buyer who funded the job. A failed transaction pays nothing."""
    if not tx or (tx.get("meta") or {}).get("err") is not None:
        return []
    from network_stats import _b58_first_byte
    msg = tx["transaction"]["message"]
    keys = msg["accountKeys"] + [k for side in ("writable", "readonly")
                                 for k in ((tx.get("meta") or {}).get("loadedAddresses") or {}).get(side, [])]
    out = []
    for ix in msg["instructions"]:
        if keys[ix["programIdIndex"]] != program or _b58_first_byte(ix["data"]) != VERIFY_RELEASE:
            continue
        acc = ix["accounts"]
        if len(acc) > BUYER:
            out.append({"worker": keys[acc[WORKER_TOKEN]], "funder": keys[acc[BUYER]], "verified": True})
    return out


def chain_payments(url=os.environ.get("KNOS_DEVNET_RPC", DEVNET), limit=1000):
    """Every verify_release in the escrow program's recent devnet history (settled jobs are closed accounts, so
    their payouts live only in transaction history). Returns (payments, n transactions left unread)."""
    from knos.jobs import sol
    from knos.team import rpc
    from concurrent.futures import ThreadPoolExecutor
    pid = sol.program_id()
    sigs = [s["signature"] for s in rpc.signatures_for(url, pid, limit=limit, timeout=30.0) if s.get("err") is None]

    def read(sig):
        try:
            return rpc.transaction(url, sig, timeout=30.0)  # rpc.call backs off on the endpoint's 429s
        except Exception:  # still throttled: counted as unread, never guessed
            return False

    with ThreadPoolExecutor(max_workers=2) as ex:
        txs = list(ex.map(read, sigs))
    return [p for tx in txs if tx for p in payments_from_tx(tx, str(pid))], sum(1 for tx in txs if tx is False)


def build(rows, date, window, excluded=0, payments=()):
    """rows: classified candidates with a claim; only those whose CI had finished at the head SHA are counted and
    listed. Deterministic for the same rows (order-independent)."""
    prs = sorted((record(r) for r in rows if r.get("class") in COMPLETED), key=lambda r: (r["repo"].lower(), r["number"]))
    proven = distinct_funders(payments)
    agents = {}
    for name, _ in agent_pr_ci.AGENTS:
        agents[name] = tally([r for r in prs if r["agent"] == name])
        agents[name]["proven"] = proven.get(name, 0)
    root = merkle_root([leaf(r) for r in prs])
    return {"date": date, "window": list(window), "n_prs": len(prs), "excluded_self_repo": excluded,
            "overall": tally(prs), "agents": agents, "proven": proven, "prs": prs, "root": root.hex()}


def attest(index, key_json):
    from solders.keypair import Keypair

    from knos.proof import receipt
    key = Keypair.from_bytes(bytes(json.loads(key_json)))
    sig, att = receipt.publish(DEVNET, key, bytes.fromhex(index["root"]), "", f"agent-pr-index {index['date']}")
    index.update({"attestation": str(att), "signature": str(sig), "attester": str(key.pubkey())})


def attest_file(path, key_json):
    """Re-derive the root from the published per-PR records (a tampered list does not attest), then attest it."""
    with open(path, encoding="utf-8") as f:
        index = json.load(f)
    if merkle_root([leaf(r) for r in index["prs"]]).hex() != index["root"]:
        raise SystemExit(f"{path}: root does not match its prs; not attested")
    for k in ("attestation", "signature", "attester", "attest_error"):
        index.pop(k, None)
    try:
        attest(index, key_json)
    except Exception as e:  # the site still ships; the missing attestation is visible in the JSON
        index["attest_error"] = str(e)[:300]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    return index


def scan(end, days, per_agent, max_seconds):
    agent_pr_ci.ARGS = SimpleNamespace(max_seconds=max_seconds)
    agent_pr_ci.SEARCH_PAUSE = 2.1  # concurrent agents share one 30/min search pacing; gh_get backs off on 403/429
    try:
        kept, n = agent_pr_ci.scan_collect(end, days, per_agent)
    except agent_pr_ci.OutOfTime:
        kept, n = [], {"hits": 0, "excluded": 0, "no_claim": 0}
    agent_pr_ci.run_checks(kept)
    start = (dt.date.fromisoformat(end) - dt.timedelta(days=days - 1)).isoformat()
    return {"window": [start, end], "counts": n,
            "rows": [c for c in kept if c.get("class") not in (None, "error")]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["scan", "build", "attest"])
    ap.add_argument("--rows", default="rows.json")
    ap.add_argument("--out", default="_site/index.json")
    ap.add_argument("--end", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--per-agent", type=int, default=480)
    ap.add_argument("--max-seconds", type=int, default=3 * 3600)
    a = ap.parse_args()
    if a.step == "scan":
        got = scan(a.end, a.days, a.per_agent, a.max_seconds)
        with open(a.rows, "w", encoding="utf-8") as f:
            json.dump(got, f, ensure_ascii=False)
        print(f"scanned {len(got['rows'])} PRs, counts {got['counts']}", file=sys.stderr)
        return 0
    if a.step == "attest":
        if not os.environ.get("KNOS_ATTEST_KEY"):
            print("KNOS_ATTEST_KEY unset; index.json ships unattested", file=sys.stderr)
            return 0
        index = attest_file(a.out, os.environ["KNOS_ATTEST_KEY"])
        print(f"agent PR index root {index['root']}: attestation {index.get('attestation') or index.get('attest_error')}",
              file=sys.stderr)
        return 0
    with open(a.rows, encoding="utf-8") as f:
        got = json.load(f)
    try:
        payments, unread = chain_payments()
        chain_error = f"{unread} escrow transactions unread (RPC throttled)" if unread else None
    except Exception as e:  # the index still ships; proven counts are then zero and the error is in the JSON
        payments, chain_error = [], str(e)[:300]
    index = build(got["rows"], dt.date.today().isoformat(), got["window"], got["counts"]["excluded"], payments)
    if chain_error:
        index["proven_error"] = chain_error
    if os.environ.get("KNOS_ATTEST_KEY"):
        try:
            attest(index, os.environ["KNOS_ATTEST_KEY"])
        except Exception as e:  # the site still ships; the missing attestation is visible in the JSON
            index["attest_error"] = str(e)[:300]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    print(f"agent PR index: {index['n_prs']} PRs, {index['excluded_self_repo']} self-repo PRs excluded, "
          f"root {index['root']}, attestation {index.get('attestation') or index.get('attest_error') or 'none'}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
