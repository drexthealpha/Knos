"""The NEAR page's live counters, read from NEAR testnet's public record (NearBlocks), every page of it, slowly enough
for its free tier. A paid first proof is one fee that reached Knos's fee account from the buyer's test account; the
dollars are those fees plus agent A's shares from that account; lost is what the buyer's test account's own record says
left it for Knos's fee account or agent A and the receivers' records do not show arriving.

    python3 near/scripts/near_counters.py <out.json>

The page (near/web/index.html) shows this file's numbers at once and adds whatever is newer than `as_of_ns` from the
newest page of each record, so the counters stay live with three requests from a visitor's browser."""
import base64
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api-testnet.nearblocks.io/v3/accounts/"
TOKEN = "knos-usdc-1102.testnet"
LIVE, FEE, AGENT = "live.knos-swarm-1105.testnet", "knos-payer-1102.testnet", "agent-a.knos-swarm-1105.testnet"
AGENT2 = "agent-a2.knos-swarm-1105.testnet"
MARKET = "market.knos-swarm-1105.testnet"   # since Round 7 the amount behind a claim goes through the claim market, which records it
RPC = "https://rpc.testnet.near.org"
CLAIMS = Path(__file__).resolve().parents[1] / "claims" / "claims.json"


def view(contract: str, method: str, args: dict):
    """A read-only call on NEAR testnet (standard library only)."""
    body = {"jsonrpc": "2.0", "id": "k", "method": "query", "params": {"request_type": "call_function", "finality": "final",
            "account_id": contract, "method_name": method, "args_base64": base64.b64encode(json.dumps(args).encode()).decode()}}
    req = urllib.request.Request(RPC, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "User-Agent": "knos-near-counters"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read())["result"]
    return json.loads(bytes(res["result"]))


def backs() -> list[tuple[str, int, int]]:
    """Every time test USDC was put behind a claim through the claim market: (claim, unix seconds, units), from its record."""
    out = []
    for c in json.loads(CLAIMS.read_text(encoding="utf-8"))["claims"]:
        i = 0
        while True:
            try:
                got = view(MARKET, "get_backs", {"claim": c["name"], "from_index": i, "limit": 500})
            except Exception:  # noqa: BLE001 - a contract with no record yet
                return []
            out += [(c["name"], int(at), int(a)) for at, a in got]
            if len(got) < 500:
                break
            i += 500
    return out


def rows(account: str) -> list[dict]:
    """Every token transfer of `account` in the test token, all pages, newest first."""
    out, nxt = [], ""
    for _ in range(200):
        url = API + account + "/ft-txns?limit=100" + ("&next=" + urllib.parse.quote(nxt) if nxt else "")
        body = None
        for tries in range(8):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "knos-near-counters"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code != 429 or tries == 7:
                    raise
                time.sleep(10 * (tries + 1))         # the free tier's limit: wait, ask again
        out += [x for x in (body or {}).get("data") or [] if x.get("contract_account_id") == TOKEN]
        nxt = ((body or {}).get("meta") or {}).get("next_page") or ""
        if not nxt:
            return out
        time.sleep(3)
    raise RuntimeError(f"{account}: more than 200 pages")


def read() -> dict:
    """The full count, read now (the hosted server calls this too when GitHub's copy is late)."""
    fee, agent = rows(FEE), rows(AGENT) + rows(AGENT2)   # agent A signs as agent-a2 since 12 Nov (Round 8)
    live = rows(LIVE)
    paid = [x for x in fee if x.get("involved_account_id") in (LIVE, MARKET) and int(x.get("delta_amount") or 0) > 0]
    shares = [x for x in agent if x.get("involved_account_id") in (LIVE, MARKET) and int(x.get("delta_amount") or 0) > 0]
    arrived = sum(int(x["delta_amount"]) for x in paid + shares)
    newest = max([int(x.get("block_timestamp") or 0) for x in fee + agent + live] or [0])
    # lost: a transfer that left the buyer's account for Knos's fee account or agent A and has no arrival with the same
    # transaction in the receivers' records. The three records are read moments apart, so a transfer younger than 10
    # minutes may not show its arrival yet; it is not counted as lost until it is older.
    came = {x.get("transaction_hash") for x in paid + shares}
    settled_by = newest - 600 * 10**9
    lost = -sum(int(x["delta_amount"]) for x in live if x.get("involved_account_id") in (FEE, AGENT, AGENT2) and int(x.get("delta_amount") or 0) < 0
                and x.get("transaction_hash") not in came and int(x.get("block_timestamp") or 0) < settled_by)
    # through the claim market: each fee that arrived from it is matched to the time it recorded the amount behind a claim
    # (the fee is that amount less agent A's 1 part in 49, within a minute); a recorded amount older than 10 minutes with
    # no fee arrived counts as lost
    claim_of, used = {}, set()
    for claim, at, units in backs():
        want = {units - units // 49, units // 10}   # Knos's fee: 48 parts in 49 before 12 Nov, 1 part in 10 since (Round 8, T16)
        hit = next((x for x in paid if x.get("involved_account_id") == MARKET and x.get("transaction_hash") not in used
                    and int(x["delta_amount"]) in want and abs(int(int(x.get("block_timestamp") or 0) / 1e9) - at) <= 60), None)
        if hit:
            used.add(hit["transaction_hash"])
            claim_of[hit["transaction_hash"]] = (claim, units)
        elif at < settled_by / 1e9:
            lost += units
    out = {"proofs": len(paid), "usd": round(arrived / 1e6, 6), "lost_usd": round(lost / 1e6, 6), "as_of_ns": str(newest),
           "read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rows": {"fee": len(fee), "agent": len(agent), "live": len(live)},
           "record": "https://testnet.nearblocks.io/address/" + LIVE + "?tab=tokentxns"}
    # every paid proof's receipt, newest first: Knos's fee transfer (its transaction, the fee in test USDC, its time) and
    # the claim it paid for: the claim market's record names it; the fees sent straight from the buyer's test account
    # before that record existed were all for the one claim their memos name, HyperLogLog
    out["receipts"] = [[x.get("transaction_hash"), round(int(x["delta_amount"]) / 1e6, 6), int(int(x.get("block_timestamp") or 0) / 1e9),
                        claim_of.get(x.get("transaction_hash"), ("hyperloglog" if x.get("involved_account_id") == LIVE else "", 0))[0]] for x in paid]
    # per claim: before the record, HyperLogLog's fees and agent shares as they arrived; through the market, each amount
    # as the market recorded it behind its claim
    old = sum(int(x["delta_amount"]) for x in paid + shares if x.get("involved_account_id") == LIVE)
    by = {"hyperloglog": {"proofs": sum(1 for x in paid if x.get("involved_account_id") == LIVE), "usd": round(old / 1e6, 6)}}
    for name, units in claim_of.values():
        b = by.setdefault(name, {"proofs": 0, "usd": 0.0})
        b["proofs"] += 1
        b["usd"] = round(b["usd"] + units / 1e6, 6)
    out["by_claim"] = by
    return out


def main(path: str) -> int:
    out = read()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
