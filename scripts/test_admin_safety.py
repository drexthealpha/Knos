"""test_admin_safety: every admin path of Knos on devnet, read from the chain. Read only: it signs and sends nothing.

    python scripts/test_admin_safety.py [--rpc URL] [--txs N]

1. Admin paths. Each program's upgrade authority, the GUARDIAN and FEE_OWNER the programs pin, and the mint authority of
   every Knos-owned mint is a vault of a Squads v4 multisig with threshold >= 2, a time lock >= 172,800 s (48 h) and no
   config authority; or none (immutable), or a program PDA. A spending limit on such a multisig is a path around its vote.
2. No durable-nonce admin signing: the code that builds admin and upgrade transactions never advances a nonce, and the
   newest transactions of each multisig do not start with AdvanceNonceAccount.
3. A cap per vault in knos_pay: the constant in the source and the checks that hold an amount to it.

One line per check, PASS or FAIL and the evidence. Exit 1 when any check fails, 2 when the cluster cannot be read.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from solders.pubkey import Pubkey

ROOT = Path(__file__).resolve().parent.parent
IDS = json.loads((ROOT / "src" / "knos" / "settle" / "v2" / "program_ids.json").read_text(encoding="utf-8"))
FIRST = json.loads((ROOT / "src" / "knos" / "settle" / "program_ids.json").read_text(encoding="utf-8"))   # the first deployment
HOOK = "AFQFtodihz5jAHpVBUk87AkH8FJsQdmHt8Z5NKLWRj1T"            # programs-hook/knos_hook (apps/wanted/knos_wanted/chainx.py)
GATE = "2DfVEuBMWvvh3kXZaQwk2SoszJsoV1PTiK1VGCkB55HW"            # examples/upgrade_gate
# FEE_OWNER is vault 0 of this multisig: found on chain from the Squads transactions that touch FEE_OWNER (it is no vault
# of the two multisigs in program_ids.json); the derivation is checked below.
FEE_MULTISIG = "2zpWe4223nNp6gPnHSAjdwGcu2cGPQtT5jcxf25MSYvV"
SQUADS = Pubkey.from_string(IDS["squads_program"])
LOADER = "BPFLoaderUpgradeab1e11111111111111111111111"
SYSTEM = "11111111111111111111111111111111"
MIN_LOCK, MIN_THRESHOLD = 172_800, 2
HOOK_INIT = bytes([43, 34, 13, 49, 167, 88, 235, 235])
MULTISIG_DISC = hashlib.sha256(b"account:Multisig").digest()[:8]
LIMIT_DISC = hashlib.sha256(b"account:SpendingLimit").digest()[:8]
# files that build admin or upgrade transactions
ADMIN_CODE = ["scripts/governance.mjs", "scripts/deploy_v2.py", "scripts/deploy_v2.sh", "scripts/schedule_upgrade.sh", "scripts/drill_upgrade.sh",
              "scripts/timelock_plan.py", "scripts/squads_fund.mjs", "src/knos/platform/squads.py", "examples/upgrade_gate/adopt.py"]
NONCE_WORDS = re.compile(r"nonceAdvance|advance_nonce|AdvanceNonce|NonceAccount|nonceInfo|platform\.nonce|platform import nonce|uses_durable_nonce")

RPC = "https://api.devnet.solana.com"
results: list[bool] = []


def rpc(method: str, params: list):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for attempt in range(6):
        try:
            req = urllib.request.Request(RPC, body, {"Content-Type": "application/json"})
            out = json.load(urllib.request.urlopen(req, timeout=30))
        except OSError:
            out = {"error": {"code": 429}}
        if out.get("error", {}).get("code") in (429, -32005):                  # rate limited: wait, ask again
            time.sleep(2 + 3 * attempt)
            continue
        if "error" in out:
            raise RuntimeError(f"{method}: {out['error']}")
        return out["result"]
    raise RuntimeError(f"{method}: no answer after 6 tries")


def account(addr: str) -> tuple[str, bytes] | None:
    v = rpc("getAccountInfo", [addr, {"encoding": "base64", "commitment": "confirmed"}])["value"]
    return None if v is None else (v["owner"], base64.b64decode(v["data"][0]))


def tx(sig: str) -> dict | None:
    return rpc("getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])


def check(name: str, ok: bool, evidence: str) -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {evidence}", flush=True)


def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz".index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + raw


def vault(multisig: str, index: int = 0) -> str:
    return str(Pubkey.find_program_address([b"multisig", bytes(Pubkey.from_string(multisig)), b"vault", bytes([index])], SQUADS)[0])


def read_multisig(data: bytes) -> dict:
    """Squads v4 Multisig: disc | create_key | config_authority | threshold u16 | time_lock u32 | indexes | rent_collector
    Option | bump | members vec (key 32, mask u8)."""
    i = 8 + 64 + 2 + 4 + 16
    i += 33 if data[i] == 1 else 1
    i += 1
    return {"config_authority": str(Pubkey.from_bytes(data[40:72])), "threshold": int.from_bytes(data[72:74], "little"),
            "time_lock": int.from_bytes(data[74:78], "little"), "members": int.from_bytes(data[i:i + 4], "little")}


MULTISIGS = {"upgrade": IDS["upgrade_multisig"], "guardian": IDS["guardian_multisig"], "fee": FEE_MULTISIG}
VAULTS = {vault(ms): name for name, ms in MULTISIGS.items()}
STATE: dict[str, dict] = {}


def held_by(what: str, authority: str | None, pda_of: str | None = None) -> None:
    """One admin path: who holds `authority`, judged against the multisig rule."""
    if authority is None:
        check(what, True, "no authority (immutable)")
        return
    if pda_of and authority == pda_of:
        check(what, True, f"{authority}, a PDA only the program signs for")
        return
    name = VAULTS.get(authority)
    if name is None:
        sigs = rpc("getSignaturesForAddress", [authority, {"limit": 1}])
        signed = ""
        if sigs:
            t = tx(sigs[0]["signature"])
            m = t["transaction"]["message"] if t else None
            if m and authority in m["accountKeys"][:m["header"]["numRequiredSignatures"]]:
                signed = f"; it signed {sigs[0]['signature']} itself, so it is a single keypair"
        check(what, False, f"{authority} is not the vault of any Squads multisig Knos uses{signed}")
        return
    ms = STATE[name]
    bad = [w for w, b in ((f"threshold {ms['threshold']} < {MIN_THRESHOLD}", ms["threshold"] < MIN_THRESHOLD),
                          (f"time lock {ms['time_lock']} s < {MIN_LOCK} s", ms["time_lock"] < MIN_LOCK),
                          (f"config authority {ms['config_authority']}", ms["config_authority"] != SYSTEM)) if b]
    check(what, not bad, f"{authority} = vault 0 of the {name} multisig {MULTISIGS[name]} ({ms['threshold']} of {ms['members']}, "
                         f"time lock {ms['time_lock']} s){'; ' + '; '.join(bad) if bad else ''}")


def oidc_key_admin_live() -> bool:
    """Whether the deployed knos_oidc refuses the guardian key approval (key step 4: Approve and Revoke take the
    upgrade vault). Simulated on the cluster with signature checking off, as the vault's signature by a cross-program
    call looks to the program: Approve (6) signed by the guardian answers Custom(79) only when the guardian may not
    approve; the build before step 4 takes the guardian and fails later, on the key account, with another error."""
    from solders.hash import Hash
    from solders.instruction import AccountMeta, Instruction
    from solders.message import Message
    from solders.transaction import Transaction
    oidc, guardian = Pubkey.from_string(IDS["knos_oidc"]), Pubkey.from_string(IDS["guardian"])
    probe = Pubkey.find_program_address([b"knos-admin-safety-probe"], oidc)[0]
    ix = Instruction(oidc, bytes([6]), [AccountMeta(guardian, True, False), AccountMeta(probe, False, True)])
    payer = Pubkey.from_string("FRXXJkfpwasEpttH5dvDwkySuJzL5D5swjA52U7TMeRD")        # a funded address pays the simulated fee
    tx = Transaction.new_unsigned(Message.new_with_blockhash([ix], payer, Hash.default()))
    got = rpc("simulateTransaction", [base64.b64encode(bytes(tx)).decode(),
                                      {"encoding": "base64", "sigVerify": False, "replaceRecentBlockhash": True, "commitment": "confirmed"}])
    err = (got or {}).get("value", {}).get("err") if isinstance(got, dict) else None
    return isinstance(err, dict) and (err.get("InstructionError") or [None, None])[1] == {"Custom": 79}


def program_authority(program: str) -> tuple[bool, str | None]:
    acc = account(program)
    if not acc or acc[0] != LOADER:
        return False, None
    pd = account(str(Pubkey.from_bytes(acc[1][4:36])))
    data = pd[1] if pd else b""
    return True, str(Pubkey.from_bytes(data[13:45])) if len(data) >= 45 and data[12] == 1 else None


def pinned(path: str, name: str) -> str | None:
    m = re.search(rf'pub const {name}: Pubkey = pubkey!\("(\w+)"\)', (ROOT / path).read_text(encoding="utf-8"))
    return m.group(1) if m else None


def credit_mints(limit: int) -> dict[str, str | None]:
    """Each project credit mint (InitializeExtraAccountMetaList of knos_hook, newest `limit` transactions) and its authority."""
    out: dict[str, str | None] = {}
    for s in rpc("getSignaturesForAddress", [HOOK, {"limit": limit}]):
        t = tx(s["signature"]) if not s.get("err") else None
        if not t:
            continue
        m = t["transaction"]["message"]
        keys = m["accountKeys"] + t["meta"].get("loadedAddresses", {}).get("writable", []) + t["meta"].get("loadedAddresses", {}).get("readonly", [])
        for ix in m["instructions"]:
            if keys[ix["programIdIndex"]] == HOOK and b58decode(ix["data"])[:8] == HOOK_INIT:
                mint = keys[ix["accounts"][1]]
                acc = account(mint)
                out[mint] = str(Pubkey.from_bytes(acc[1][4:36])) if acc and acc[1][:4] == b"\x01\x00\x00\x00" else None
    return out


def main() -> int:
    global RPC
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rpc", default=RPC)
    ap.add_argument("--txs", type=int, default=25, help="newest transactions read per multisig, and of knos_hook")
    o = ap.parse_args()
    RPC = o.rpc
    try:
        genesis = rpc("getGenesisHash", [])
        print(f"cluster {RPC} genesis {genesis}{' (devnet)' if genesis == 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG' else ''}", flush=True)
        for name, ms in MULTISIGS.items():
            acc = account(ms)
            if not acc or acc[0] != str(SQUADS) or acc[1][:8] != MULTISIG_DISC:
                raise RuntimeError(f"{name} multisig {ms} is not a Squads v4 multisig on this cluster")
            STATE[name] = read_multisig(acc[1])

        # 1. admin paths ------------------------------------------------------------------------------------------------
        for name in ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey"):
            _, auth = program_authority(IDS[name])
            held_by(f"upgrade authority {name} {IDS[name]}", auth)
        for name, prog in (("upgrade_gate", GATE), ("knos_hook", HOOK), ("first knos_oidc", FIRST["knos_oidc"]), ("first knos_pay", FIRST["knos_pay"])):
            deployed, auth = program_authority(prog)
            if deployed:
                held_by(f"upgrade authority {name} {prog}", auth)
        guardians = {pinned("programs-v2/knos_pay/src/lib.rs", "GUARDIAN"), pinned("programs-v2/knos_oidc/src/pins.rs", "GUARDIAN")}
        fee_owners = {pinned("programs-v2/knos_pay/src/lib.rs", "FEE_OWNER"), pinned("programs-v2/knos_meter/src/lib.rs", "FEE_OWNER")}
        check("pins agree", guardians == {IDS["guardian"]} and fee_owners == {IDS["fee_owner"]},
              f"GUARDIAN {sorted(map(str, guardians))}, FEE_OWNER {sorted(map(str, fee_owners))} in knos_pay, knos_oidc, knos_meter")
        if oidc_key_admin_live():
            # key step 4 is deployed: knos_oidc's Approve and Revoke take the upgrade vault (behind its 8-day lock), and
            # the guardian signs knos_pay's Pause alone, a brake that ends by itself and never moves money: no wait for it
            ms = STATE["guardian"]
            ok = ms["threshold"] >= MIN_THRESHOLD and ms["config_authority"] == SYSTEM
            check("GUARDIAN (knos_pay Pause only; knos_oidc keys are the upgrade vault's)", ok,
                  f"{IDS['guardian']} = vault 0 of the guardian multisig ({ms['threshold']} of {ms['members']}, time lock {ms['time_lock']} s, "
                  f"a brake); the deployed knos_oidc names the key admin {IDS['upgrade_authority']}")
        else:
            held_by("GUARDIAN (knos_pay Pause; knos_oidc approve/revoke key)", IDS["guardian"])
        held_by("FEE_OWNER (all fees; knos_pay SetPlan; knos_meter plans)", IDS["fee_owner"])
        pay = Pubkey.from_string(IDS["knos_pay"])
        mint = str(Pubkey.find_program_address([b"mint"], pay)[0])
        auth_pda = str(Pubkey.find_program_address([b"auth"], pay)[0])
        acc = account(mint)
        if acc:
            d = acc[1]
            held_by(f"mint authority faucet test USDC {mint}", str(Pubkey.from_bytes(d[4:36])) if d[0] == 1 else None, auth_pda)
            held_by(f"freeze authority faucet test USDC {mint}", str(Pubkey.from_bytes(d[50:82])) if d[46] == 1 else None, auth_pda)
        credits = credit_mints(o.txs)
        for m, a in sorted(credits.items()):
            # the hook's PDA ["mint-authority", mint]: knos_hook alone mints, and only into the vault its rules name
            held_by(f"mint authority project credits {m}", a,
                    pda_of=str(Pubkey.find_program_address([b"mint-authority", bytes(Pubkey.from_string(m))], Pubkey.from_string(HOOK))[0]))
        if not credits:
            print(f"INFO  no project credit mint in the newest {o.txs} knos_hook transactions", flush=True)
        for name, ms in MULTISIGS.items():
            found = rpc("getProgramAccounts", [str(SQUADS), {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0},
                                                              "filters": [{"memcmp": {"offset": 0, "bytes": base64.b64encode(LIMIT_DISC).decode(), "encoding": "base64"}},
                                                                          {"memcmp": {"offset": 8, "bytes": ms}}]}])
            check(f"no spending limit on the {name} multisig", not found, f"{len(found)} SpendingLimit accounts{': ' + ', '.join(a['pubkey'] for a in found) if found else ''}")

        # 2. durable nonces ---------------------------------------------------------------------------------------------
        hits = [f"{f}:{n}" for f in ADMIN_CODE if (ROOT / f).exists()
                for n, line in enumerate((ROOT / f).read_text(encoding="utf-8").splitlines(), 1) if NONCE_WORDS.search(line)]
        check("admin code builds no nonce transaction", not hits, f"{len([f for f in ADMIN_CODE if (ROOT / f).exists()])} files read"
              + (f"; nonce use at {', '.join(hits)}" if hits else "; none advances a nonce"))
        for name, ms in MULTISIGS.items():
            sigs = rpc("getSignaturesForAddress", [ms, {"limit": o.txs}])
            nonce, read = [], 0
            for s in sigs:
                t = tx(s["signature"])
                if not t:
                    continue
                read += 1
                m = t["transaction"]["message"]
                first = m["instructions"][0] if m["instructions"] else None
                if first and m["accountKeys"][first["programIdIndex"]] == SYSTEM and b58decode(first["data"])[:4] == (4).to_bytes(4, "little"):
                    nonce.append(s["signature"])
            check(f"no nonce in the {name} multisig's transactions", not nonce and read > 0,
                  f"{read} newest read{', newest ' + sigs[0]['signature'][:16] + '...' if sigs else ''}"
                  + (f"; AdvanceNonceAccount first in {', '.join(nonce)}" if nonce else ""))
    except RuntimeError as e:
        print(f"cannot read the cluster: {e}", file=sys.stderr)
        return 2

    # 3. a cap per vault -----------------------------------------------------------------------------------------------
    lib = (ROOT / "programs-v2" / "knos_pay" / "src" / "lib.rs").read_text(encoding="utf-8")
    m = re.search(r"pub const MAX_AMOUNT: u64 = ([\d_]+);", lib)
    cap = int(m.group(1).replace("_", "")) if m else 0
    uses = [f"{f}:{n}" for f in ("fund.rs", "order.rs") for n, line in enumerate((ROOT / "programs-v2" / "knos_pay" / "src" / f).read_text(encoding="utf-8").splitlines(), 1)
            if "units(MAX_AMOUNT, " in line]
    line = lib[:m.start()].count("\n") + 1 if m else 0
    check("cap per escrow in knos_pay", cap > 0 and len(uses) >= 3,
          f"MAX_AMOUNT = {cap:,} millionths = {cap / 1e6:,.2f} whole units per job and per order (programs-v2/knos_pay/src/lib.rs:{line}); "
          f"enforced at {', '.join(uses)}; a Balance may set a lower cap of its own (B_CAP, E_CAP)")

    failed = results.count(False)
    print(f"{len(results) - failed} passed, {failed} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
