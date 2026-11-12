"""Prove a paper's claim on NEAR testnet from a terminal: the one call an agent makes (POST /api/near/claim/flow on the
hosted server), printed as lines a person can read. Standard library only.

    python3 near/scripts/knos_prove.py <paper link or DOI> [test USDC, 1 to 100]

Prints the claim, the verdict, the spending cap's refusal, each payment with its NEAR explorer link and the verified
code's address; exits 0 when the claim was proved and paid, 1 otherwise."""
import json
import sys
import urllib.request

HOSTED = "https://knos.onrender.com"


def prove(url: str, amount: int = 10) -> dict:
    req = urllib.request.Request(HOSTED + "/api/near/claim/flow", data=json.dumps({"url": url, "amount": amount}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "knos-prove"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def lines(r: dict) -> list[str]:
    if not r.get("ok"):
        return [f"not proved: {r.get('why') or r.get('why_not_settled') or 'no answer'}"]
    if "look" in r:
        q = (r["look"].get("quote") or {})
        return ["Knos cannot prove this paper yet.", f"Today a person checks it: {q.get('checker')}. Price: {q.get('price')}. Time: {q.get('time')}."]
    v = r.get("verdict") or {}
    out = [f"claim: {r.get('claim')}", f"verdict: {'holds' if v.get('holds') else 'fails' if v.get('holds') is False else 'none'}"
           + (f" (the paper: {v.get('paper')}; measured: {v.get('measured')})" if v.get("paper") else "")]
    if r.get("reused"):
        out.append(f"reused: {r.get('why_not_settled')}")
    cap = r.get("cap") or {}
    if cap.get("refused"):
        out.append(f"spending cap: agent B asked {cap.get('tried_units')} units over its cap of {cap.get('cap_units')}, refused on NEAR: {cap.get('url')}")
    rc = r.get("receipt") or {}
    if r.get("paid"):
        out += [f"paid: {rc.get('buyer_usd')} test USDC behind the claim",
                f"  agent A's share {rc.get('agent_usd')}: {rc.get('agent_pay_url')}",
                f"  Knos's fee {rc.get('knos_usd')}: {rc.get('fee_url')}",
                f"  the job's pay to agent A: {rc.get('job_pay_url')}"]
    out.append(f"recorded on NEAR: {'yes' if r.get('settled') else 'no'}")
    if r.get("code"):
        out.append(f"verified code: {r['code']}")
    return out


def main(argv: list[str]) -> int:
    if not argv or len(argv) > 2:
        print(__doc__)
        return 2
    r = prove(argv[0], int(argv[1]) if len(argv) == 2 else 10)
    print("\n".join(lines(r)))
    return 0 if r.get("ok") and r.get("paid") and r.get("settled") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
