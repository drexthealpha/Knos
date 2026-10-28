"""I4 test_iris_devnet: one live devnet run of each release path with IRIS in it: a GitHub-check milestone paid through
the relay, a lab milestone (FHIR Observation) voted through the referee release, a refund after a 1-day deadline; each
transaction confirmed with its log line and the receipt showing the Visual Trace session.

    python iris/tests/test_iris_devnet.py <result file> [<signature> ...]

It looks each given signature up on devnet (getTransaction, its log lines) and says what is missing for the others.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

OUT = Path(sys.argv[1])
SIGS = sys.argv[2:]
RPC = "https://api.devnet.solana.com"


def tx(sig: str) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0,
                                                                                            "commitment": "confirmed"}]}).encode()
    with urllib.request.urlopen(urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json"}), timeout=60) as r:
        return json.loads(r.read()).get("result") or {}


lines, fails = [], 0
paths = ["a GitHub-check milestone paid through the relay", "a lab milestone voted through the referee release", "a refund after a 1-day deadline"]
for i, name in enumerate(paths):
    sig = SIGS[i] if i < len(SIGS) else ""
    if not sig:
        fails += 1
        why = {0: "needs a funded issue's merged pull request and its GitHub-signed token; IRIS relays it, it never signs one",
               1: "needs IRIS's decision as one FROST share of the referee panel (2 of 3); that signing step is not built in iris/ yet",
               2: "needs an order whose 1-day deadline has passed; one funded today can be refunded tomorrow"}[i]
        lines.append(f"FAIL {name}: not run: {why}")
        continue
    t = tx(sig)
    logs = (t.get("meta") or {}).get("logMessages") or []
    ok = bool(t) and (t.get("meta") or {}).get("err") is None and logs
    fails += not ok
    lines.append(f"{'ok  ' if ok else 'FAIL'} {name}: {sig[:20]}... slot {t.get('slot')}, {len(logs)} log lines")
lines.append(f"FAIL test_iris_devnet: {fails} of 3 paths without a confirmed devnet run" if fails else "PASS test_iris_devnet: 3 of 3 paths confirmed on devnet")
print("\n".join(lines))
with OUT.open("a", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
sys.exit(1 if fails else 0)
