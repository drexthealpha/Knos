"""The issuer keys knos-oidc starts with: sha256 of each RS256 modulus GitHub Actions and GitLab publish.

    python scripts/oidc_pins.py            print the hashes of the keys published right now
    python scripts/oidc_pins.py --check    exit 1 if a published key is neither a GENESIS constant in pins.rs nor
                                           (with --rpc) registered on chain

GENESIS is fixed in the binary. A key an issuer adds later enters only by GitHub's own signature, through the pinned
rotate workflow (drexthealpha/knos-oidc-rotate); --check tells you when that workflow has work to do.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from knos.settle import oidc  # noqa: E402

PINS = ROOT / "programs" / "knos_oidc" / "src" / "pins.rs"


def genesis(text: str | None = None) -> set[tuple[int, str]]:
    """(issuer, hash hex) for every GENESIS constant in pins.rs (the test constants are not counted)."""
    text = PINS.read_text(encoding="utf-8") if text is None else text
    body = text[text.index("pub const GENESIS"):]
    body = body[:body.index("];")]
    return {(int(i), h) for i, h in re.findall(r'\((\d),\s*h\("([0-9a-f]{64})"\)\)', body)}


def published(get=None) -> list[tuple[int, str, str]]:
    """(issuer, kid, hash hex) for every key the issuers publish now."""
    def fetch(url: str) -> dict:
        with urllib.request.urlopen(url, timeout=20) as r:  # noqa: S310 - the issuers' fixed https URLs
            return json.load(r)
    out = []
    for issuer, url in oidc.JWKS.items():
        for kid, n in oidc.jwks_keys((get or fetch)(url)):
            out.append((issuer, kid, oidc.key_hash(n).hex()))
    return out


def main(argv=None, get=None, account=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--rpc", help="also accept a key registered on this cluster")
    a = ap.parse_args(argv)
    have = genesis()
    if a.rpc and account is None:
        from knos import chain
        account = chain.Ledger(a.rpc).account
    missing = 0
    for issuer, kid, h in published(get):
        where = "genesis" if (issuer, h) in have else "not in pins.rs"
        if where != "genesis" and account is not None:
            from solders.pubkey import Pubkey
            pda = Pubkey.find_program_address([b"key", bytes([issuer]), bytes.fromhex(h)], oidc.OIDC_ID)[0]
            where = "registered on chain" if account(pda) is not None else "NOT ACCEPTED: run the rotate workflow"
        missing += where.startswith(("not", "NOT"))
        print(f"{oidc.ISSUERS[issuer]}  {kid}  {h}  {where}")
    return 1 if a.check and missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
