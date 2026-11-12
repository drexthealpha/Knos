"""The NEAR testnet balances that keep the live demo up, against their floors (near/balances.json), read from NEAR's
public RPC with no key. Exit 1 when one is under its floor or cannot be read.

    python3 scripts/near_balances.py           # a table, then the exit status
    python3 scripts/near_balances.py --json    # the same as JSON (what /api/near/balances serves)
"""
import base64
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RPCS = ("https://rpc.testnet.fastnear.com", "https://near-testnet.drpc.org", "https://rpc.testnet.near.org")
TOKEN = "knos-usdc-1102.testnet"


def _rpc(method: str, params) -> dict:
    last = None
    for url in RPCS:
        try:
            req = urllib.request.Request(url, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                         {"Content-Type": "application/json", "User-Agent": "knos-balances/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                out = json.loads(r.read())
            if "result" in out:
                return out["result"]
            last = out.get("error")
        except Exception as e:  # noqa: BLE001 - the next RPC
            last = str(e)
    raise RuntimeError(f"no RPC answered: {str(last)[:120]}")


def read(row: dict) -> float:
    a = row["account"]
    if row["kind"] == "near":
        return int(_rpc("query", {"request_type": "view_account", "finality": "final", "account_id": a})["amount"]) / 1e24
    if row["kind"] == "allowance":
        keys = _rpc("query", {"request_type": "view_access_key_list", "finality": "final", "account_id": a})["keys"]
        fc = [k["access_key"]["permission"]["FunctionCall"] for k in keys if k["access_key"]["permission"] != "FullAccess"]
        return max((int(f.get("allowance") or 0) for f in fc), default=0) / 1e24
    args = base64.b64encode(json.dumps({"account_id": a}).encode()).decode()
    res = _rpc("query", {"request_type": "call_function", "finality": "final", "account_id": TOKEN, "method_name": "ft_balance_of", "args_base64": args})
    return int(json.loads(bytes(res["result"]))) / 1e6


def check() -> list[dict]:
    rows = json.loads((ROOT / "near" / "balances.json").read_text(encoding="utf-8"))["accounts"]
    out = []
    for row in rows:
        try:
            v = read(row)
            out.append({**row, "value": round(v, 4), "ok": v >= row["floor"]})
        except Exception as e:  # noqa: BLE001 - unread counts as low
            out.append({**row, "value": None, "ok": False, "why": str(e)[:120]})
    return out


def main(argv: list[str]) -> int:
    rows = check()
    if "--json" in argv:
        print(json.dumps(rows, indent=1))
    else:
        unit = {"near": "NEAR", "allowance": "NEAR allowance", "usdc": "test USDC"}
        for r in rows:
            print(f"{'ok ' if r['ok'] else 'LOW'} {r['account']:40} {r['value'] if r['value'] is not None else 'unread':>12} {unit[r['kind']]:15} floor {r['floor']}  {r['what']}")
    low = [r for r in rows if not r["ok"]]
    if low:
        print(f"{len(low)} account(s) under their floor: top them up (testnet faucet) before the demo stops.", file=sys.stderr)
    return 1 if low else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
