"""The receipts of every test job on the NEAR jobs contract, for a bookkeeper: one row per job with its funding, proof,
payout and refund, each with its testnet transaction, read now from NEAR testnet's public record. Read-only: it signs
nothing and needs no key.

    python near/scripts/receipts.py [out_dir]        (default near/web: receipts.json and receipts.csv)

Where each column comes from: FastNear's public transaction index for testnet lists every transaction that touched the
jobs contract and returns each one whole, with its receipts and their outcomes. A funding is a successful
ft_transfer_call to the contract whose msg is `open_job`; a payout is a successful release_job (or
release_job_verified), a refund a successful refund_job, each naming the job; Knos's part is the ft_transfer the
contract sends with the memo "knos fee, job <id>". The job's state, payee and proof id are the contract's `get_job`
(read from a NEAR RPC); the totals are its `get_totals`, which count the jobs opened since its 14 Nov 2026 upgrade; the
owners' pause switch is `get_switches` and each agent's hold line is `get_agent_rules`.

Optional: KNOS_RECEIPTS_CACHE names a file that keeps the transactions already fetched (a final transaction never
changes), so a run stopped by a busy free tier starts where it was.
"""
from __future__ import annotations

import base64
import csv
import http.client
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

JOBS = "jobs.knos-swarm-1105.testnet"
INDEX = "https://tx.test.fastnear.com/v0/"
RPCS = ["https://rpc.testnet.fastnear.com", "https://near-testnet.drpc.org", "https://rpc.testnet.near.org"]
TX = "https://testnet.nearblocks.io/txns/"
COLUMNS = ["job", "state", "token", "amount", "payer", "paid_to", "funded", "funded_tx", "proof", "released", "released_tx",
           "fee", "refunded", "refunded_tx"]
UA = {"User-Agent": "knos-receipts", "Content-Type": "application/json"}
NET = (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException)


def post(url: str, payload: dict, tries: int = 8) -> dict:
    body = json.dumps(payload).encode()
    for n in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, body, UA), timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:   # a free tier answers 429 when asked too fast: wait, ask again
            if e.code not in (429, 500, 502, 503, 504) or n == tries - 1:
                raise
            time.sleep(5 * (n + 1))
        except NET:
            if n == tries - 1:
                raise
            time.sleep(5 * (n + 1))
    raise RuntimeError(url)


def rpc(method: str, params, rpcs: list[str] | None = None) -> dict:
    last = None
    for url in rpcs or RPCS:
        try:
            out = post(url, {"jsonrpc": "2.0", "id": "k", "method": method, "params": params}, tries=3)
        except NET as e:
            last = e
            continue
        if "error" in out:
            last = RuntimeError(json.dumps(out["error"])[:300])
            continue
        return out["result"]
    raise RuntimeError(f"no RPC answered {method}: {last}")


def view(method: str, args: dict, account: str = JOBS, rpcs: list[str] | None = None):
    r = rpc("query", {"request_type": "call_function", "finality": "final", "account_id": account, "method_name": method,
                      "args_base64": base64.b64encode(json.dumps(args).encode()).decode()}, rpcs)
    return json.loads(bytes(r["result"]).decode() or "null")


def account_txs(account: str = JOBS) -> list[str]:
    """Every transaction hash that touched `account`, newest first, all pages."""
    out, token = [], None
    for _ in range(1000):
        page = post(INDEX + "account", {"account_id": account, **({"resume_token": token} if token else {})})
        out += [t["transaction_hash"] for t in page.get("account_txs") or []]
        token = page.get("resume_token")
        if not token or not page.get("account_txs"):
            return list(dict.fromkeys(out))
        time.sleep(1)
    raise RuntimeError("more than 1000 pages")


_SEEN: dict = {}


def transactions(hashes: list[str], batch: int = 20) -> dict:
    """Each transaction whole (transaction, execution_outcome, receipts), by hash, fetched `batch` at a time."""
    todo = [h for h in hashes if h not in _SEEN]
    for i in range(0, len(todo), batch):
        got = post(INDEX + "transactions", {"tx_hashes": todo[i:i + batch]})
        for t in got.get("transactions") or []:
            if t:
                _SEEN[t["transaction"]["hash"]] = t
        if (i // batch) % 25 == 24:
            print(f"{len(_SEEN)} transactions fetched", file=sys.stderr, flush=True)
            _save()
        time.sleep(0.5)
    return {h: _SEEN[h] for h in hashes if h in _SEEN}


def _save() -> None:
    if os.environ.get("KNOS_RECEIPTS_CACHE"):
        Path(os.environ["KNOS_RECEIPTS_CACHE"]).write_text(json.dumps(_SEEN), encoding="utf-8")


def calls(t: dict) -> list[tuple[str, str, str, dict, dict]]:
    """(receiver, predecessor, method, args, outcome) of every function call receipt of one transaction."""
    out = []
    for r in t.get("receipts") or []:
        rc = r["receipt"]
        for a in (rc.get("receipt") or {}).get("Action", {}).get("actions", []):
            fc = a.get("FunctionCall") if isinstance(a, dict) else None
            if fc:
                try:
                    args = json.loads(base64.b64decode(fc["args"]))
                except ValueError:
                    args = {}
                out.append((rc["receiver_id"], rc["predecessor_id"], fc["method_name"], args if isinstance(args, dict) else {},
                            r["execution_outcome"]["outcome"]))
    return out


def ok(t: dict) -> bool:
    """Every receipt of the transaction succeeded."""
    return not any("Failure" in r["execution_outcome"]["outcome"]["status"] for r in t.get("receipts") or [])


def when(t: dict) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(t["execution_outcome"]["block_timestamp"]) / 1e9))


def events(t: dict) -> list[tuple[str, str, dict]]:
    """(kind, job id, detail) of one transaction: funded, released, refunded or fee; nothing when it failed."""
    if not ok(t):
        return []
    out = []
    tx = t["transaction"]
    for receiver, pred, method, args, _o in calls(t):
        if method == "ft_transfer_call" and args.get("receiver_id") == JOBS and pred == tx["signer_id"]:
            try:
                msg = json.loads(args.get("msg") or "{}")
            except ValueError:
                msg = {}
            o = msg.get("open_job") if isinstance(msg, dict) else None
            if isinstance(o, dict) and o.get("id"):
                out.append(("funded", o["id"], {"amount": str(args.get("amount") or ""), "token": receiver, "payer": tx["signer_id"]}))
        elif receiver == JOBS and method in ("release_job", "release_job_verified") and args.get("id"):
            out.append(("released", args["id"], {}))
        elif receiver == JOBS and method == "refund_job" and args.get("id"):
            out.append(("refunded", args["id"], {}))
        elif method == "ft_transfer" and pred == JOBS and str(args.get("memo") or "").startswith("knos fee, job "):
            out.append(("fee", str(args["memo"]).removeprefix("knos fee, job "), {"amount": str(args.get("amount") or "")}))
    return out


def build(txs: list[dict], job_of) -> list[dict]:
    """One record per job from whole transactions (job_of(id) -> get_job); a job the contract does not know is left out."""
    jobs: dict[str, dict] = {}
    for t in sorted(txs, key=lambda x: int(x["execution_outcome"]["block_timestamp"])):
        for kind, jid, detail in events(t):
            j = jobs.setdefault(jid, {c: "" for c in COLUMNS} | {"job": jid})
            h = TX + t["transaction"]["hash"]
            if kind == "funded":
                j.update(funded=when(t), funded_tx=h, **detail)
            elif kind == "fee":
                j["fee"] = detail["amount"]
            else:
                j.update({kind: when(t), f"{kind}_tx": h})
    out = []
    for jid, j in jobs.items():
        g = job_of(jid)
        if not g:
            continue
        j.update(state=str(g.get("state") or ""), paid_to=str(g.get("paid_to") or ""), proof=str(g.get("proof_jti") or ""))
        j["amount"] = j["amount"] or str(g.get("amount") or "")
        out.append(j)
    return sorted(out, key=lambda j: j["funded"] or j["released"] or j["refunded"], reverse=True)


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\r\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def sums(rows: list[dict], since: str = "") -> dict:
    """Per token, the units locked, paid, refunded and still open of the jobs funded at or after `since` (UTC ISO)."""
    out: dict[str, dict] = {}
    for j in rows:
        if not j["funded"] or j["funded"] < since or not j["amount"]:
            continue
        t = out.setdefault(j["token"], {"locked": 0, "paid": 0, "refunded": 0, "open": 0})
        n = int(j["amount"])
        t["locked"] += n
        t[{"Paid": "paid", "Refunded": "refunded"}.get(j["state"], "open")] += n
    return out


def main(out_dir: str = "") -> int:
    out = Path(out_dir) if out_dir else Path(__file__).resolve().parents[1] / "web"
    cache = os.environ.get("KNOS_RECEIPTS_CACHE")
    if cache and Path(cache).exists():
        _SEEN.update(json.loads(Path(cache).read_text(encoding="utf-8")))
    hashes = account_txs()
    print(f"{len(hashes)} transactions listed", file=sys.stderr, flush=True)
    try:
        txs = list(transactions(hashes).values())
    finally:
        _save()
    ids = sorted({jid for t in txs for _k, jid, _d in events(t)})
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(6) as pool:   # one get_job per job, six at once, every other one asking the second RPC first
        state = dict(zip(ids, pool.map(lambda i: view("get_job", {"id": ids[i]}, rpcs=RPCS if i % 2 else [RPCS[1], RPCS[0], *RPCS[2:]]), range(len(ids)))))
    print(f"{len(ids)} jobs read", file=sys.stderr, flush=True)
    jobs = build(txs, state.get)
    totals = view("get_totals", {})
    switches = view("get_switches", {}) or {}
    agents = json.loads((Path(__file__).resolve().parents[1] / "agents" / "swarm.json").read_text(encoding="utf-8"))["agents"]
    # each agent's hold line: a spend over it waits for the approver (get_agent_rules; 0 means no hold line set)
    holds = {a: view("get_agent_rules", {"agent": a}) or {} for a in agents.values()}
    data = {"contract": JOBS, "read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "transactions_read": len(txs),
            "transactions_listed": len(hashes), "totals": totals, "paused": bool(switches.get("paused")), "approver": switches.get("approver"),
            "hold_line": {a: {"hold_over": str(r.get("hold_over") or "0"), "daily_cap": str(r.get("daily_cap") or "0")} for a, r in holds.items()},
            "counted_since": "", "jobs": jobs}
    # the contract counts only the jobs opened since its 14 Nov 2026 upgrade: the first funding time from which the
    # rows add up to its totals is that cut, and the page and the test compare the two
    want = {t: {k: int(v[k]) for k in ("locked", "paid", "refunded", "open")} for t, v in (totals or {}).items() if int(v["locked"])}
    for since in sorted({j["funded"] for j in jobs if j["funded"] >= "2026-11-14"}):
        if sums(jobs, since) == want:
            data["counted_since"] = since
            break
    (out / "receipts.json").write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")   # compact: phones download it
    (out / "receipts.csv").write_text(to_csv(jobs), encoding="utf-8", newline="")
    print(json.dumps({"jobs": len(jobs), "transactions": len(txs), "listed": len(hashes), "counted_since": data["counted_since"], "totals": want}))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:2]))
