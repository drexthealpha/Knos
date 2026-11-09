"""Every program the app or the site uses, with who can upgrade it, read from devnet: README.md's second table of
programs (between <!-- authorities:start --> and <!-- authorities:end -->) and docs/program_authorities.json.

    python scripts/program_authorities.py           read devnet, write the JSON and the README table
    python scripts/program_authorities.py --check   exit 1 when the README or the JSON differs from devnet today

An upgradeable program's authority is the one in its ProgramData account (none: nobody can change it). A program
owned by another loader cannot be upgraded at all.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from knos import chain  # noqa: E402

OUT = ROOT / "docs" / "program_authorities.json"
README = ROOT / "README.md"
START, END = "<!-- authorities:start -->", "<!-- authorities:end -->"
UPGRADEABLE = "BPFLoaderUpgradeab1e11111111111111111111111"
SECOND = json.loads((ROOT / "src" / "knos" / "settle" / "v2" / "program_ids.json").read_text(encoding="utf-8"))
FIRST = json.loads((ROOT / "src" / "knos" / "settle" / "program_ids.json").read_text(encoding="utf-8"))
VAULT = SECOND["upgrade_authority"]          # the Squads vault: an upgrade waits out its 8-day time lock

# (address, what it is to Knos, where it is used)
PROGRAMS = [
    ("FaMHCjzyUexFncZrmNyFQNz3gBdsLbhTLke7QBFykJY4", "knos-pay 0.3.34: the app's live program (0.3.34)", "every pre-order, milestone payout and agent payout of the app"),
    (SECOND["knos_oidc"], "knos-oidc 2.2: the verifier of GitHub's signed checks", "pay on merge, the site's signature line"),
    (SECOND["knos_pay"], "knos-pay 2.2: the payment program", "pay on merge, the site's work orders"),
    (SECOND["knos_meter"], "knos-meter: the count", "the meter on the site"),
    (SECOND["knos_passkey"], "knos-passkey: a wallet from a passkey", "passkey wallets in the app"),
    ("AFQFtodihz5jAHpVBUk87AkH8FJsQdmHt8Z5NKLWRj1T", "knos-hook: the transfer hook", "the app's Token-2022 project credits"),
    (FIRST["knos_oidc"], "knos-oidc, first deployment", "the site's history of the first deployment"),
    (FIRST["knos_pay"], "knos-pay, first deployment", "the site's history of the first deployment"),
    ("recr1L3PCGKLbckBqMNcJhuuyU1zgo8nBhfLVsJNwr5", "SPL Record (Solana)", "the app's chain-state records"),
    ("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr", "SPL Memo (Solana)", "the app's fee estimate and its notes on chain"),
    ("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb", "Token-2022 (Solana)", "the app's project credits"),
    ("SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf", "Squads multisig", "the upgrade and guardia vaults"),
]


def _info(address: str) -> dict | None:
    got = chain.call(chain.DEVNET_URL, "getAccountInfo", [address, {"encoding": "base64"}])
    return (got or {}).get("value")


def authority(address: str) -> dict:
    """{"loader", "authority"}: authority None when nobody can upgrade it (no authority, or not an upgradeable loader)."""
    acct = _info(address)
    if acct is None:
        return {"loader": None, "authority": None, "missing": True}
    if acct["owner"] != UPGRADEABLE:
        return {"loader": acct["owner"], "authority": None}
    data = base64.b64decode(acct["data"][0])
    programdata = chain.b58(data[4:36])
    pd = base64.b64decode(_info(programdata)["data"][0])
    has = pd[12] == 1                                   # ProgramData: u32 tag, u64 slot, Option<Pubkey> authority
    return {"loader": UPGRADEABLE, "programdata": programdata, "authority": chain.b58(pd[13:45]) if has else None}


def read() -> dict:
    rows = []
    for address, name, where in PROGRAMS:
        rows.append({"address": address, "name": name, "used_for": where, **authority(address)})
    return {"read_at": time.strftime("%Y-%m-%d", time.gmtime()), "rpc": chain.DEVNET_URL, "vault": VAULT, "programs": rows}


def who(row: dict) -> str:
    if row.get("missing"):
        return "not found on devnet"
    if row["loader"] != UPGRADEABLE:
        return "none: not an upgradeable program"
    if row["authority"] is None:
        return "none: nobody can change it"
    if row["authority"] == VAULT:
        return f"`{VAULT}`, the Squads vault (an upgrade waits out its 8-day time lock)"
    return f"`{row['authority']}`, one key"


def table(doc: dict) -> str:
    lines = [f"Every program the app or this site uses, and who can upgrade it, read from devnet on {doc['read_at']} "
             "([`scripts/program_authorities.py`](https://github.com/drexthealpha/Knos/blob/main/scripts/program_authorities.py)):", "",
             "| program | address | used for | upgrade authority |", "|---|---|---|---|"]
    lines += [f"| {r['name']} | `{r['address']}` | {r['used_for']} | {who(r)} |" for r in doc["programs"]]
    return "\n".join(lines)


def _readme(text: str, doc: dict) -> str:
    a, b = text.index(START) + len(START), text.index(END)
    return text[:a] + "\n" + table(doc) + "\n" + text[b:]


def main(argv: list[str]) -> int:
    doc = read()
    text = README.read_text(encoding="utf-8")
    if "--check" in argv:
        kept = json.loads(OUT.read_text(encoding="utf-8"))
        same = [{k: v for k, v in r.items()} for r in kept["programs"]] == doc["programs"]
        shown = _readme(text, {**doc, "read_at": kept["read_at"]}) == text
        for k, r in zip(kept["programs"], doc["programs"]):
            if k != r:
                print(f"differs from devnet: {r['name']} {r['address']}: kept {who(k)}, chain {who(r)}")
        print(f"{len(doc['programs'])} programs; JSON matches devnet: {same}; README matches the JSON: {shown}")
        return 0 if same and shown else 1
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    README.write_text(_readme(text, doc), encoding="utf-8", newline="\n")
    print(table(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
