"""Register GitHub Actions' OIDC signing keys with the Knos escrow (RegisterKey, tag 15; admin only).

Fetches https://token.actions.githubusercontent.com/.well-known/jwks, and for each RSA-2048 key (RS256, e=65537)
not yet registered sends RegisterKey with its kid, modulus n, R^2 mod n and n0inv (the program checks both). Run
against devnet only after the 0.3.7 program is deployed from main.

    KNOS_ADMIN_KEY=/path/to/admin.json  python scripts/register_github_keys.py [--url https://api.devnet.solana.com]

The admin key file is a Solana CLI keypair (JSON array). It is read, never printed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.request

from solders.keypair import Keypair

from knos.jobs import sol
from knos.jobs.ledger import Ledger

JWKS = "https://token.actions.githubusercontent.com/.well-known/jwks"

ap = argparse.ArgumentParser()
ap.add_argument("--url", default=os.environ.get("KNOS_SOLANA_RPC", "https://api.devnet.solana.com"))
ap.add_argument("--program", default=sol.DEVNET_PROGRAM)
ap.add_argument("--dry-run", action="store_true")
args = ap.parse_args()

path = os.environ.get("KNOS_ADMIN_KEY")
if not path:
    sys.exit("set KNOS_ADMIN_KEY to the escrow admin's keypair file")
with open(path, encoding="utf-8") as f:
    admin = Keypair.from_bytes(bytes(json.load(f)))

ledger = Ledger(args.url, sol.program_id(args.program))
if ledger.config()["admin"] != admin.pubkey():
    sys.exit("that key is not the escrow's admin")

with urllib.request.urlopen(urllib.request.Request(JWKS, headers={"User-Agent": "knos"}), timeout=30) as r:
    keys = json.load(r)["keys"]

for k in keys:
    kid = k.get("kid", "")
    if k.get("kty") != "RSA" or k.get("e") != "AQAB":
        print(f"skip {kid}: not RSA e=65537")
        continue
    n = int.from_bytes(base64.urlsafe_b64decode(k["n"] + "=" * (-len(k["n"]) % 4)), "big")
    if n.bit_length() != 2048:
        print(f"skip {kid}: not 2048-bit")
        continue
    addr = sol.gh_key_pda(ledger.program, kid)
    if ledger.account(addr):
        print(f"{kid}: already registered at {addr}")
        continue
    if args.dry_run:
        print(f"{kid}: would register at {addr}")
        continue
    sig = ledger.send([sol.register_key(ledger.program, admin.pubkey(), kid, n)], admin)
    print(f"{kid}: registered at {addr} ({sig})")
