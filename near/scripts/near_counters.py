"""The NEAR page's live counters, read from NEAR testnet's public record (NearBlocks), every page of it, slowly enough
for its free tier. A paid first proof is one fee that reached Knos's fee account from the buyer's test account; the
dollars are those fees plus agent A's shares from that account; lost is what the buyer's test account's own record says
left it for Knos's fee account or agent A and the receivers' records do not show arriving.

    python3 near/scripts/near_counters.py <out.json>

The page (near/web/index.html) shows this file's numbers at once and adds whatever is newer than `as_of_ns` from the
newest page of each record, so the counters stay live with three requests from a visitor's browser."""
import json
import sys
import time
import urllib.parse
import urllib.request

API = "https://api-testnet.nearblocks.io/v3/accounts/"
TOKEN = "knos-usdc-1102.testnet"
LIVE, FEE, AGENT = "live.knos-swarm-1105.testnet", "knos-payer-1102.testnet", "agent-a.knos-swarm-1105.testnet"


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


def main(path: str) -> int:
    fee, agent = rows(FEE), rows(AGENT)
    live = rows(LIVE)
    paid = [x for x in fee if x.get("involved_account_id") == LIVE and int(x.get("delta_amount") or 0) > 0]
    shares = [x for x in agent if x.get("involved_account_id") == LIVE and int(x.get("delta_amount") or 0) > 0]
    arrived = sum(int(x["delta_amount"]) for x in paid + shares)
    left = -sum(int(x["delta_amount"]) for x in live if x.get("involved_account_id") in (FEE, AGENT) and int(x.get("delta_amount") or 0) < 0)
    newest = max([int(x.get("block_timestamp") or 0) for x in fee + agent + live] or [0])
    out = {"proofs": len(paid), "usd": round(arrived / 1e6, 6), "lost_usd": round(max(0, left - arrived) / 1e6, 6), "as_of_ns": str(newest),
           "read_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rows": {"fee": len(fee), "agent": len(agent), "live": len(live)},
           "record": "https://testnet.nearblocks.io/address/" + LIVE + "?tab=tokentxns"}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f)
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
