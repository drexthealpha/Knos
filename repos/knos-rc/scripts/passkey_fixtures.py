"""Write sdk/settle/passkey.fixtures.json: what the Python client of knos-passkey (the authority,
src/knos/settle/v2/passkey.py) derives and builds from one passkey and one signed withdrawal, so the browser helper
(sdk/settle/passkey.js) can be checked against it byte for byte, offline. tests/test_passkey_chain.py sends exactly
these instructions to the program.  Run: python scripts/passkey_fixtures.py     `--check` exits 1 if the file is stale.

The file's `inputs` are kept as they are: the passkey's public key as a browser reports it, a WebAuthn assertion
that key really signed (with a high s, so a client must lower it), and the registration it came from. New inputs
need a P-256 private key: python tests/test_passkey_chain.py --new
"""
import json
import sys
from pathlib import Path

from solders.instruction import Instruction
from solders.keypair import Keypair

from knos.settle.v2 import passkey
from knos.settle.v2.pay import ata, create_ata_ix

OUT = Path(__file__).resolve().parents[1] / "sdk" / "settle" / "passkey.fixtures.json"


def plain(ix: Instruction) -> dict:
    return {"program": str(ix.program_id), "data": bytes(ix.data).hex(),
            "accounts": [{"pubkey": str(a.pubkey), "signer": a.is_signer, "writable": a.is_writable} for a in ix.accounts]}


def build(i: dict) -> dict:
    """The fixture for these inputs. The payer, the mint and the destination's owner are keys of seeds, so a test can sign as them."""
    payer, mint, owner = (Keypair.from_seed(bytes.fromhex(i[k])).pubkey() for k in ("payer_seed", "mint_seed", "owner_seed"))
    key = passkey.compressed(bytes.fromhex(i["spki"]))
    wallet, to = passkey.wallet(key), ata(owner, mint)
    auth, cdj, der = bytes.fromhex(i["authenticator_data"]), i["client_data_json"].encode(), bytes.fromhex(i["signature_der"])
    challenge = passkey.challenge(wallet, mint, to, i["amount"], i["nonce"])
    verify, withdraw = passkey.withdraw_ixs(key, mint, to, i["amount"], i["nonce"], auth, cdj, der)
    account = bytes([1, 255]) + key + bytes(5) + (41).to_bytes(8, "little")       # a wallet account after 41 withdrawals
    read = passkey.read_wallet(account)
    return {"inputs": i, "program": str(passkey.PASSKEY_ID), "payer": str(payer), "mint": str(mint), "owner": str(owner), "key": key.hex(),
            "wallet": str(wallet), "from": str(ata(wallet, mint)), "to": str(to),
            "challenge": challenge.hex(), "challenge_b64url": passkey.b64url(challenge), "raw_signature": passkey.raw_signature(der).hex(),
            # the withdrawal request as a relay reads it, and the one line the site shows for it: both sides are held to these
            "request": passkey.request(key, mint, to, i["amount"], i["nonce"], auth, cdj, der),
            "request_line": passkey.request_line(key, mint, to, i["amount"], i["nonce"], auth, cdj, der),
            "account": {"data": account.hex(), "key": read.key.hex(), "nonce": read.nonce},
            "errors": {str(code): words for code, words in passkey.ERRORS.items()},
            "ixs": {"open": plain(passkey.open_ix(payer, key)), "create_ata": plain(create_ata_ix(payer, owner, mint)),
                    "secp256r1": plain(verify), "withdraw": plain(withdraw)}}


def write(inputs: dict) -> None:
    OUT.write_text(json.dumps(build(inputs), indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    have = json.loads(OUT.read_text(encoding="utf-8"))
    if "--check" in sys.argv:
        sys.exit(0 if have == build(have["inputs"]) else "sdk/settle/passkey.fixtures.json is stale: run python scripts/passkey_fixtures.py")
    write(have["inputs"])
