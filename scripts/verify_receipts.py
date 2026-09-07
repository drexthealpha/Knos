"""Resolve every transaction hash this repository shows against the chain.

The documents point a judge at eleven onchain receipts. A receipt that does
not resolve is worse than no receipt, because it reads as evidence, so this
asks the chain directly rather than trusting the page.

Each hash is checked against the chain it is *labelled* with. That distinction
is the whole point: the first version of this script asked mainnet for all
eleven and reported three missing, which read exactly like fabrication. Those
three are the `Access.sol` transactions, correctly documented as Base Sepolia
and correctly absent from mainnet. A checker that queries the wrong chain
manufactures the failure it claims to have found.

    python scripts/verify_receipts.py

Exits non-zero if anything does not resolve. Needs a network; nothing else in
knos does.
"""

from __future__ import annotations

import json
import sys
import urllib.request

CHAINS = {
    "mainnet": {
        "id": "0x2105",
        "rpcs": ["https://base-rpc.publicnode.com",
                 "https://base.llamarpc.com",
                 "https://mainnet.base.org"],
    },
    "sepolia": {
        "id": "0x14a34",
        "rpcs": ["https://base-sepolia-rpc.publicnode.com",
                 "https://sepolia.base.org"],
    },
}

# What the documents claim, and where they claim it.
RECEIPTS = [
    ("mainnet", "x402 news $0.001",
     "0x80d984d2e88332888a595f5476722bca9efbe7850fce4090b02f49154d958c76"),
    ("mainnet", "x402 brief $0.01",
     "0xce109c28781fec2ea12b8e115d59b1bfea219434379a30d472cf72b4abd9a85e"),
    ("mainnet", "x402 news $0.001",
     "0xa8e7135e6c41e6eb8ed5d15b5dbf5aafc5a8f748e9d16e08aa1ae6d9c0466103"),
    ("mainnet", "x402 brief $0.01",
     "0x3a45e0066fbf764731f98dab3f023ee2a690dc8923f08ae7f9cb4332e049a88b"),
    ("mainnet", "ACP 75659 escrow",
     "0x756b867b2b1165bfe674025a82d21cd765378a40ab226274bd555abf0065bd64"),
    ("mainnet", "ACP 75659 paid",
     "0x95a84c44802d09e38ef920524f947dff0eb5a2fe972054fca97bfd989cbcea59"),
    ("mainnet", "ACP earlier job",
     "0x2ce6af5c1c223a5b1395cbae719a96d7f1ded74fd90f909375142f9e4a14d9ca"),
    ("mainnet", "ACP earlier job",
     "0x20983f7ba5afc2cc96da402e1509e8f267c15e4068048f6397bee4bb13537d04"),
    ("sepolia", "Access.sol deploy",
     "0xdcc25ff7460a09a080ec32016b39121b6a34b741f03411bcfdc2ee2a93b31d21"),
    ("sepolia", "Access.sol grant",
     "0x84e11e21315b51e9e6b6453d226a44bcabf5a80f4c0085ba6f5b56ed169a92b6"),
    ("sepolia", "Access.sol revoke",
     "0xb3ea6920c0a7bf7fa9dde64e6f0c2275e149f976bf20c909098a2431417adfb4"),
]

CONTRACT = "0x955fa320D60D9172CF048141ed7eEE442da66E52"
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"


def call(chain: str, method: str, params: list) -> object:
    body = json.dumps({"jsonrpc": "2.0", "id": 1,
                       "method": method, "params": params}).encode()
    last: Exception | None = None
    for rpc in CHAINS[chain]["rpcs"]:
        req = urllib.request.Request(
            rpc, data=body,
            headers={"Content-Type": "application/json", "User-Agent": "curl/8.4.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r).get("result")
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"every {chain} RPC refused: {last}")


def main() -> int:
    bad = 0

    for chain, want in ((c, CHAINS[c]["id"]) for c in CHAINS):
        got = call(chain, "eth_chainId", [])
        mark = "ok " if got == want else "BAD"
        print(f"  {mark} {chain:8} chain id {got} (expected {want})")
        if got != want:
            bad += 1
    print()

    for chain, what, h in RECEIPTS:
        try:
            rec = call(chain, "eth_getTransactionReceipt", [h])
        except Exception as e:  # noqa: BLE001
            print(f"  ??  {chain:8} {what:18} rpc error: {e}")
            bad += 1
            continue

        if not rec:
            print(f"  BAD {chain:8} {what:18} {h} does not resolve")
            bad += 1
            continue

        ok = rec.get("status") == "0x1"
        # A purchase that never touched USDC is not a purchase.
        moved = any(str(lg.get("address", "")).lower() == USDC
                    for lg in rec.get("logs") or [])
        note = "  usdc" if moved else ""
        print(f"  {'ok ' if ok else 'BAD'} {chain:8} {what:18}"
              f" block {int(rec['blockNumber'], 16)}{note}")
        if not ok:
            bad += 1

    code = call("sepolia", "eth_getCode", [CONTRACT, "latest"])
    live = bool(code) and code != "0x"
    print()
    print(f"  {'ok ' if live else 'BAD'} sepolia  Access.sol         "
          f"{(len(code) // 2 - 1) if live else 0} bytes deployed at {CONTRACT}")
    if not live:
        bad += 1

    print()
    print(f"{len(RECEIPTS) - bad} of {len(RECEIPTS)} receipts resolve on the chain "
          "each is documented against.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
