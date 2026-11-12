"""`knos prove [paper link] [test USDC]`: one real proof of a paper's claim on NEAR testnet, from the terminal.

It makes the one call the hosted service answers (POST https://knos.onrender.com/api/near/claim/flow) and prints the
claim, the sha256 of the test NEAR locked before any agent started, the verdict, and the receipt's NEAR transactions.
With no link it proves the sample, HyperLogLog (2007). Test money only; nothing is installed or signed here."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

HOSTED = "https://knos.onrender.com/api/near/claim/flow"
SAMPLE = "https://doi.org/10.46298/dmtcs.3545"


def main(args: list[str]) -> int:
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    url = args[0] if args else SAMPLE
    amount = float(args[1]) if len(args) > 1 else 3
    print(f"Proving the claim of {url} on NEAR testnet with {amount:g} test USDC (about 25 s)...", flush=True)
    req = urllib.request.Request(HOSTED, json.dumps({"url": url, "amount": amount}).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "knos-cli"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError) as e:
        print(f"Not proved: the service did not answer ({e}). Where to fix it: try again in a minute; https://drexthealpha.github.io/Knos/status/ says if it is up.")
        return 1
    v = d.get("verdict") or {}
    look = d.get("look") or {}
    if not d.get("ok") or (not v and look):
        print(f"Not proved: {d.get('why') or d.get('next') or d.get('why_not_settled') or 'no answer'}. Where to fix it: paste a paper Knos has a claim for, listed at https://drexthealpha.github.io/Knos/claims/")
        return 1
    print(f"Claim: {d.get('claim')}")
    print(f"Locked test sha256: {d.get('test_sha256') or 'not returned'}")
    print(f"Verdict: {'holds' if v.get('holds') else 'does not hold'}" + (" (the last verified proof, reused)" if d.get("reused") else "") + f", job {d.get('job')}")
    if v.get("agent_a"):
        print(f"Agent A: {v['agent_a']}")
    if v.get("ai_reviewer"):
        print(f"Reviewer: {v['ai_reviewer']}")
    rc = d.get("receipt") or {}
    if rc:
        print(f"Receipt: {rc.get('buyer_usd')} test USDC behind the proof, {rc.get('agent_usd')} to the agent, {rc.get('knos_usd')} to Knos")
        for k in ("fee_url", "agent_pay_url", "job_pay_url"):
            if rc.get(k):
                print(f"  NEAR: {rc[k]}")
    elif d.get("why_not_settled"):
        print(f"Not paid: {d['why_not_settled']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
