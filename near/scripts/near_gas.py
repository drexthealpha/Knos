"""The gas the RS256 proof check burns on NEAR testnet, read from the receipts of real release transactions, against the
300 Tgas a transaction may use. Read-only: it signs nothing and needs no key.

    python near/scripts/near_gas.py [N] [receipts.json] [out.json]

It takes the last N (default 20) paid jobs of near/web/receipts.json (written by near/scripts/receipts.py), fetches
each release transaction whole from FastNear's public testnet index, and reads gas_burnt from the receipt the jobs
contract ran the release in (the one that parses the checker's token and checks its RS256 signature) and from the whole
transaction. It writes the max and the median of each, the hashes it read and the date to near/gas.json, and prints one
line.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from receipts import JOBS, transactions  # noqa: E402

NEAR = Path(__file__).resolve().parents[1]
LIMIT_TGAS = 300   # NEAR's gas limit for one transaction (docs.near.org, "Gas")


def tgas(gas: float) -> float:
    return round(gas / 1e12, 2)


def release_gas(t: dict) -> tuple[int, int] | None:
    """(gas of the jobs contract's release receipt, gas of the whole transaction) of one whole transaction, or None when
    it is not a successful release on the jobs contract."""
    rs = t.get("receipts") or []
    if any("Failure" in r["execution_outcome"]["outcome"]["status"] for r in rs):
        return None
    for r in rs:
        rc = r["receipt"]
        acts = (rc.get("receipt") or {}).get("Action", {}).get("actions", [])
        names = [a.get("FunctionCall", {}).get("method_name") for a in acts if isinstance(a, dict)]
        if rc.get("receiver_id") == JOBS and names and names[0] in ("release_job", "release_job_verified"):
            whole = t["execution_outcome"]["outcome"]["gas_burnt"] + sum(x["execution_outcome"]["outcome"]["gas_burnt"] for x in rs)
            return r["execution_outcome"]["outcome"]["gas_burnt"], whole
    return None


def summary(rows: list[dict]) -> dict:
    rec = [r["receipt_gas"] for r in rows]
    whole = [r["tx_gas"] for r in rows]
    return {"transactions": len(rows), "limit_tgas": LIMIT_TGAS,
            "release_receipt_tgas": {"max": tgas(max(rec)), "median": tgas(statistics.median(rec))},
            "transaction_tgas": {"max": tgas(max(whole)), "median": tgas(statistics.median(whole))},
            "share_of_limit_max": round(max(whole) / (LIMIT_TGAS * 1e12), 4)}


def main(n: str = "20", receipts: str = "", out: str = "") -> int:
    data = json.loads(Path(receipts or NEAR / "web" / "receipts.json").read_text(encoding="utf-8"))
    paid = [j for j in data["jobs"] if j.get("released_tx")][: int(n)]
    got = transactions([j["released_tx"].rsplit("/", 1)[-1] for j in paid])
    rows = []
    for j in paid:
        h = j["released_tx"].rsplit("/", 1)[-1]
        g = release_gas(got[h]) if h in got else None
        if g:
            rows.append({"job": j["job"], "tx": h, "receipt_gas": g[0], "tx_gas": g[1]})
    if not rows:
        print("no release transaction could be read")
        return 1
    s = {"read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "contract": JOBS, **summary(rows), "rows": rows}
    Path(out or NEAR / "gas.json").write_text(json.dumps(s, indent=1) + "\n", encoding="utf-8")
    print(f"RS256 release on {JOBS}, last {s['transactions']} paid jobs: the release receipt burns at most "
          f"{s['release_receipt_tgas']['max']} Tgas (median {s['release_receipt_tgas']['median']}), the whole transaction at most "
          f"{s['transaction_tgas']['max']} Tgas (median {s['transaction_tgas']['median']}) of the {LIMIT_TGAS} Tgas limit ({s['read_at']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
