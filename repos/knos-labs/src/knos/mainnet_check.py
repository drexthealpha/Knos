"""`knos mainnet-check`: the gates the escrow must pass before it may go to mainnet, each checked on chain.

    upgrade authority   the program's upgrade authority is a Squads v4 vault whose multisig has a time lock > 0
    escrow admin        the escrow config2 admin is that vault
    fee account         the escrow fee token account is owned by that vault
    verified build      the solana-verify (docker) executable hash equals the on-chain program hash
    security.txt        the on-chain binary embeds a security.txt
    IDL                 an on-chain IDL account exists (Program Metadata canonical "idl", or Anchor's)
    cargo-audit         the last cargo-audit run (program.yml on main, via gh) passed, or a recorded result file
    outside signer      at least one multisig member is not a known Knos key (all 3 are Knos keys today: FAILS)
    24 h time lock      the multisig time lock is >= 86,400 s (300 s today: FAILS)
    mainnet             locked unless KNOS_ALLOW_MAINNET=1 (locked is the PASS, by design)

Exit 0 only if every gate passes. All I/O goes through `Fetch`, so tests inject fakes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass
from typing import Callable

from solders.pubkey import Pubkey

PROGRAM = "GwmbMFvyHHwHug5em9dv26oXz2zTgXKGsNdrBxPayRPq"
SQUADS = Pubkey.from_string("SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf")
LOADER = Pubkey.from_string("BPFLoaderUpgradeab1e11111111111111111111111")
TOKEN = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
METADATA = Pubkey.from_string("ProgM6JCCvbYkfKqJYHePx4xxSUSqJp7rh8Lyv7nk7S")
# The devnet Squads multisig (scripts/squads_devnet.json); override with KNOS_SQUADS_MULTISIG.
DEVNET_MULTISIG = os.environ.get("KNOS_SQUADS_MULTISIG", "2zpWe4223nNp6gPnHSAjdwGcu2cGPQtT5jcxf25MSYvV")
SECURITY_TXT = b"=======BEGIN SECURITY.TXT V1======="
# Every key Knos itself holds; a multisig made only of these is not independent.
KNOS_KEYS = frozenset({
    "3AwCofxMiRBChGA4BWdEqGKxgREErrrRYf3fqjhP7HzM",
    "EwSxyJFNQkNN9qtss4Qd7DTvrNYb62vgvhdwqgfErXDz",
    "9TGQPftNmrt8T6ETUZJ5CeQf27z3pFR8En3FkKrA2PbT",
})
MIN_TIMELOCK = 86_400
PROGRAMDATA_HEADER = 45  # u32 tag | u64 slot | u8 option | [32] authority


@dataclass
class Fetch:
    """account(addr) -> (owner, data) or None; verify(program) -> OtterSec status dict or None;
    audit() -> (ok, detail)."""

    account: Callable[[str], tuple[str, bytes] | None]
    verify: Callable[[str], dict | None]
    audit: Callable[[], tuple[bool, str]]


def vault_pda(multisig: Pubkey, index: int = 0) -> Pubkey:
    return Pubkey.find_program_address([b"multisig", bytes(multisig), b"vault", bytes([index])], SQUADS)[0]


def multisig_timelock(data: bytes) -> tuple[int, int]:
    """Squads v4 Multisig: disc(8) create_key(32) config_authority(32) threshold(u16) time_lock(u32) ..."""
    return int.from_bytes(data[72:74], "little"), int.from_bytes(data[74:78], "little")


def multisig_members(data: bytes) -> list[str]:
    """... time_lock(u32) transaction_index(u64) stale_transaction_index(u64) rent_collector(Option<Pubkey>) bump(u8)
    members(Vec<{key[32], permissions u8}>)."""
    try:
        off = 94
        off += 33 if data[off] == 1 else 1
        off += 1
        n = int.from_bytes(data[off:off + 4], "little")
        off += 4
        return [str(Pubkey.from_bytes(data[off + 33 * i:off + 33 * i + 32])) for i in range(n)]
    except (IndexError, ValueError):
        return []


def elf_hash(elf: bytes) -> str:
    """solana-verify's program hash: sha256 of the ELF with the trailing zero padding stripped."""
    return hashlib.sha256(elf.rstrip(b"\x00")).hexdigest()


def idl_addresses(program: Pubkey) -> list[Pubkey]:
    seed = b"idl".ljust(16, b"\x00")
    canonical = Pubkey.find_program_address([bytes(program), seed], METADATA)[0]
    base = Pubkey.find_program_address([], program)[0]
    anchor = Pubkey.create_with_seed(base, "anchor:idl", program)
    return [canonical, anchor]


def run(fetch: Fetch, program: str = PROGRAM, multisig: str = DEVNET_MULTISIG,
        env: dict | None = None) -> list[tuple[str, bool, str]]:
    env = os.environ if env is None else env
    pid = Pubkey.from_string(program)
    res: list[tuple[str, bool, str]] = []
    pd_addr = Pubkey.find_program_address([bytes(pid)], LOADER)[0]
    pd = fetch.account(str(pd_addr))
    authority = None
    elf = b""
    if pd and pd[1][:4] == (3).to_bytes(4, "little"):
        data = pd[1]
        authority = Pubkey.from_bytes(data[13:45]) if data[12] == 1 else None
        elf = data[PROGRAMDATA_HEADER:]

    # 1. upgrade authority = Squads vault with a time lock
    vault = None
    members: list[str] = []
    lock = 0
    if not multisig:
        res.append(("upgrade authority is a Squads v4 vault (time lock > 0)", False,
                    f"authority {authority}; no multisig given (KNOS_SQUADS_MULTISIG)"))
    else:
        ms = fetch.account(multisig)
        vault = vault_pda(Pubkey.from_string(multisig))
        if not ms or ms[0] != str(SQUADS):
            res.append(("upgrade authority is a Squads v4 vault (time lock > 0)", False, f"{multisig} is not a Squads v4 account"))
        else:
            threshold, lock = multisig_timelock(ms[1])
            members = multisig_members(ms[1])
            ok = authority == vault and lock > 0
            res.append(("upgrade authority is a Squads v4 vault (time lock > 0)", ok,
                        f"authority {authority}, vault {vault}, threshold {threshold}, time lock {lock}s"))

    # 1b. independence: an outside signer, and a 24 h time lock
    outside = [m for m in members if m not in KNOS_KEYS]
    res.append(("an outside signer is a member", bool(outside),
                f"outside members: {', '.join(outside)}" if outside else
                f"all {len(members)} members are Knos keys; the multisig is not yet independent"))
    res.append(("time lock >= 86,400 s", lock >= MIN_TIMELOCK, f"time lock {lock}s"))

    # 2./3. escrow admin and fee account
    cfg = fetch.account(str(Pubkey.find_program_address([b"config2"], pid)[0]))
    if not cfg:
        res.append(("escrow admin is the vault", False, "no config2 account"))
        res.append(("fee account owned by the vault", False, "no config2 account"))
    else:
        admin = Pubkey.from_bytes(cfg[1][0:32])
        fee = Pubkey.from_bytes(cfg[1][64:96])
        res.append(("escrow admin is the vault", vault is not None and admin == vault, f"admin {admin}"))
        tok = fetch.account(str(fee))
        owner = Pubkey.from_bytes(tok[1][32:64]) if tok and tok[0] == str(TOKEN) and len(tok[1]) >= 64 else None
        res.append(("fee account owned by the vault", vault is not None and owner == vault,
                    f"fee token {fee}, owner {owner}"))

    # 4. verified build
    onchain = elf_hash(elf) if elf else None
    st = fetch.verify(program) or {}
    want = st.get("executable_hash") or st.get("hash")
    ok = bool(onchain) and bool(want) and want == onchain and st.get("is_verified", True) is not False
    src = f" ({st['source']})" if st.get("source") else ""
    res.append(("solana-verify hash == on-chain hash", ok, f"on-chain {onchain}, verified build {want or 'none'}{src}"))

    # 5. security.txt
    res.append(("security.txt in the on-chain binary", SECURITY_TXT in elf,
                "present" if SECURITY_TXT in elf else "not found in the dumped program bytes"))

    # 6. IDL
    found = [str(a) for a in idl_addresses(pid) if fetch.account(str(a))]
    res.append(("IDL account on chain", bool(found), ", ".join(found) or "none at the metadata or anchor address"))

    # 7. cargo-audit
    ok, detail = fetch.audit()
    res.append(("cargo-audit clean", ok, detail))

    # 8. mainnet locked
    locked = env.get("KNOS_ALLOW_MAINNET") != "1"
    res.append(("mainnet: locked (by design)" if locked else "mainnet: UNLOCKED (KNOS_ALLOW_MAINNET=1)", locked,
                "KNOS_ALLOW_MAINNET unset" if locked else "unset KNOS_ALLOW_MAINNET until the gates above pass"))
    return res


# ---- the real fetchers ------------------------------------------------------------------------


def _rpc(url: str) -> Callable[[str], tuple[str, bytes] | None]:
    def account(addr: str) -> tuple[str, bytes] | None:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
                           "params": [addr, {"encoding": "base64", "commitment": "confirmed"}]}).encode()
        req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            v = json.load(r)["result"]["value"]
        return (v["owner"], base64.b64decode(v["data"][0])) if v else None
    return account


def _osec(program: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"https://verify.osec.io/status/{program}", timeout=20) as r:
            return json.load(r)
    except Exception:
        return None


def _ci_verified(program: str) -> dict | None:
    """OtterSec's status API only covers mainnet. On devnet the verified build is the `knos_escrow-verified.so`
    artifact (solana-verify docker build) of the last successful program.yml run on main; hash it the same way."""
    import tempfile
    try:
        runs = json.loads(subprocess.run(
            ["gh", "run", "list", "--workflow", "program.yml", "--branch", "main", "--status", "success", "--limit", "1",
             "--json", "databaseId"], capture_output=True, text=True, timeout=30, check=True).stdout)
        rid = runs[0]["databaseId"]
        with tempfile.TemporaryDirectory(dir=".") as d:  # relative, so a Windows gh.exe under WSL works too
            d = os.path.relpath(d)
            subprocess.run(["gh", "run", "download", str(rid), "-n", "knos_escrow-verified.so", "-D", d],
                           capture_output=True, timeout=120, check=True)
            elf = open(os.path.join(d, "knos_escrow.so"), "rb").read()
        return {"executable_hash": elf_hash(elf), "source": f"program.yml run {rid} verified-build artifact"}
    except Exception:
        return None


def _verified(program: str) -> dict | None:
    st = _osec(program)
    if st and (st.get("executable_hash") or st.get("hash")):
        return st
    return _ci_verified(program)


def _audit(env: dict) -> tuple[bool, str]:
    rec = env.get("KNOS_CARGO_AUDIT_RESULT")
    if rec and os.path.exists(rec):
        got = json.loads(open(rec, encoding="utf-8").read())
        vulns = got.get("vulnerabilities", {}).get("count", got.get("count", 1))
        return vulns == 0, f"{rec}: {vulns} vulnerabilities"
    try:
        runs = json.loads(subprocess.run(
            ["gh", "run", "list", "--workflow", "program.yml", "--branch", "main", "--limit", "1",
             "--json", "databaseId"], capture_output=True, text=True, timeout=30, check=True).stdout)
        rid = runs[0]["databaseId"]
        jobs = json.loads(subprocess.run(["gh", "run", "view", str(rid), "--json", "jobs"], capture_output=True,
                                         text=True, timeout=30, check=True).stdout)["jobs"]
    except Exception as why:
        return False, f"no recorded result and gh failed ({type(why).__name__}); set KNOS_CARGO_AUDIT_RESULT"
    job = next((j for j in jobs if j["name"] == "cargo-audit"), None)
    if not job:
        return False, f"run {rid} has no cargo-audit job"
    return job.get("conclusion") == "success", f"program.yml run {rid}: cargo-audit {job.get('conclusion')}"


def live(env: dict | None = None) -> Fetch:
    env = os.environ if env is None else env
    url = env.get("KNOS_SOLANA_RPC", "https://api.devnet.solana.com")
    return Fetch(account=_rpc(url), verify=_verified, audit=lambda: _audit(env))


def main(say: Callable[[str], None] = print, fetch: Fetch | None = None, multisig: str | None = None) -> int:
    got = run(fetch or live(), multisig=multisig if multisig is not None else DEVNET_MULTISIG)
    for name, ok, detail in got:
        say(f"{'PASS' if ok else 'FAIL'}  {name}  ({detail})")
    passed = sum(ok for _, ok, _ in got)
    say(f"{passed}/{len(got)} gates pass" + ("" if passed == len(got) else "; mainnet stays locked"))
    return 0 if passed == len(got) else 1
