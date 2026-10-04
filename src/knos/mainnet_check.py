"""`knos mainnet-check`: what must hold before the second deployment (programs-v2) moves real money, each gate with the
evidence it was judged on.

    verified build      each program's on-chain bytes hash to this repository's verified build (solana-verify in
                        program.yml; or the files in KNOS_VERIFIED_DIR, for a build made on this machine)
    upgrade authority   each program's upgrade authority is the pinned vault; or none, once the outside review is
                        done and the program has been made immutable
    security.txt        each binary embeds a security.txt
    upgrade multisig    that vault is vault 0 of the pinned Squads v4 multisig; the multisig's time lock is 172800
                        seconds (an upgrade waits 48 hours in public after it is approved); it has no config
                        authority (no single key can change its members, its threshold or that delay)
    guardian            the GUARDIAN both programs name is vault 0 of the pinned guardian multisig, which has no
                        config authority either
    workflow pins       the commits of the rotate and claim workflows that the programs pin are in the on-chain
                        binaries and exist on GitHub
    GitHub's keys       every key GitHub publishes today has a key account that verifies now: registered, ready, a
                        genesis key or approved by the guardian, not revoked, not expired; with each one's expiry
    other clusters      the two program ids are in use on no other public cluster (an address is derived from the
                        program id, so a token for one cluster then names nothing on another)
    program checks      the last program.yml run on main passed: Wycheproof vectors, the differential test against
                        OpenSSL, the property tests, the fuzz walks, cargo-audit
    outside review      docs/review.json records one, and it is of the bytes on chain. There is none today: FAILS
    mainnet             locked, by design, until every gate above passes

The review is recorded as:

    {"reviewer": "who", "date": "2026-11-20", "report": "https://...", "commit": "<the commit reviewed>",
     "programs": {"knos_oidc": "<executable hash reviewed>", "knos_pay": "<executable hash reviewed>"}}

Exit 0 only if every gate passes. All I/O goes through `Fetch`, so tests inject fakes.

`knos status` (status() below) is the shorter question asked of a deployment that is meant to be running now, read from
chain, each line with what to do when it fails:

    program ids         the two pinned ids are deployed and executable
    upgrade authority   each program's upgrade authority is the upgrade vault (or none, once made immutable)
    upgrade multisig    its time lock is 172800 seconds and it has no config authority
    guardian            the GUARDIAN both programs name is vault 0 of the pinned guardian multisig
    GitHub's keys       every key GitHub publishes today is registered, usable now and more than 7 days from expiry
    new funding         not paused
    first deployment    both programs of the first deployment still have no upgrade authority
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple

from solders.pubkey import Pubkey

from . import chain
from .settle.v2 import oidc

LOADER = Pubkey.from_string("BPFLoaderUpgradeab1e11111111111111111111111")
SECURITY_TXT = b"=======BEGIN SECURITY.TXT V1======="
PROGRAMDATA_HEADER = 45  # u32 tag | u64 slot | u8 option | [32] authority
PINS_REPO = "drexthealpha/knos-oidc-rotate"
PROGRAMS = ("knos_oidc", "knos_pay")
TIME_LOCK = 172_800      # seconds between the vote that approves an upgrade and its execution
KEY_MARGIN = 7 * 86_400  # `knos status`: a key must outlive today by this much, so that the rotate workflow has a week to refresh it
MULTISIG = hashlib.sha256(b"account:Multisig").digest()[:8]   # Anchor's discriminator of a Squads v4 Multisig account
PUBLIC = {"devnet": "https://api.devnet.solana.com", "testnet": "https://api.testnet.solana.com",
          "mainnet-beta": "https://api.mainnet-beta.solana.com"}
GENESIS = {"EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG": "devnet", "4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY": "testnet",
           "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d": "mainnet-beta"}

# (owner, data) or (owner, data, executable) of an account, None when there is none. The program accounts a status check
# reads must carry the executable flag; every other check needs the first two.
Account = Callable[[str], "tuple[str, bytes] | tuple[str, bytes, bool] | None"]


@dataclass
class Fetch:
    """account(addr) -> (owner, data) or None; verified(name) -> {"executable_hash", "source"} or None;
    program_checks() -> (ok, detail); get(url) -> parsed JSON or None; review() -> (docs/review.json parsed or None,
    where it was looked for); now() -> the cluster's clock; elsewhere(addr) -> {other public cluster: whether an
    account exists there at addr, None when that cluster could not be read}."""

    account: Account
    verified: Callable[[str], dict | None]
    program_checks: Callable[[], tuple[bool, str]]
    get: Callable[[str], dict | list | None]
    review: Callable[[], tuple[dict | None, str]]
    now: Callable[[], int]
    elsewhere: Callable[[str], dict[str, bool | None]]
    cluster: Callable[[], str] | None = None


def elf_hash(elf: bytes) -> str:
    """solana-verify's program hash: sha256 of the ELF with the trailing zero padding stripped."""
    return hashlib.sha256(elf.rstrip(b"\x00")).hexdigest()


def programdata_address(program: Pubkey | str) -> Pubkey:
    """Where the upgradeable loader keeps a program's bytes and its upgrade authority."""
    return Pubkey.find_program_address([bytes(Pubkey.from_string(program) if isinstance(program, str) else program)], LOADER)[0]


def program_data(account: Account, program: str) -> tuple[bool, str | None, bytes]:
    """(deployed, upgrade authority or None, the program's bytes)."""
    pd = account(str(programdata_address(program)))
    if not pd or pd[1][:4] != (3).to_bytes(4, "little"):
        return False, None, b""
    data = pd[1]
    authority = str(Pubkey.from_bytes(data[13:45])) if data[12] == 1 else None
    return True, authority, data[PROGRAMDATA_HEADER:]


@dataclass
class Multisig:
    create_key: Pubkey
    config_authority: Pubkey | None     # None: autonomous, only a vote of the members changes it
    threshold: int
    time_lock: int                      # seconds
    members: list[Pubkey]


def read_multisig(data: bytes | None) -> Multisig | None:
    """A Squads v4 Multisig account: 8 discriminator | create_key 32 | config_authority 32 (all zero: none) |
    threshold u16 | time_lock u32 | transaction_index u64 | stale_transaction_index u64 | rent_collector, one byte and
    32 more when it is set | bump u8 | members: a u32 count, then (key 32, permissions u8) each. None for anything else."""
    if not data or len(data) < 100 or data[:8] != MULTISIG or data[94] > 1:
        return None
    at = 94 + (33 if data[94] else 1) + 1
    count = int.from_bytes(data[at:at + 4], "little")
    if count > 65_535 or len(data) < at + 4 + 33 * count:
        return None
    authority = Pubkey.from_bytes(data[40:72])
    return Multisig(create_key=Pubkey.from_bytes(data[8:40]), config_authority=None if authority == Pubkey.default() else authority,
                    threshold=int.from_bytes(data[72:74], "little"), time_lock=int.from_bytes(data[74:78], "little"),
                    members=[Pubkey.from_bytes(data[at + 4 + 33 * k:at + 36 + 33 * k]) for k in range(count)])


def multisig_address(create_key: Pubkey, squads: Pubkey) -> Pubkey:
    return Pubkey.find_program_address([b"multisig", b"multisig", bytes(create_key)], squads)[0]


def vault_address(multisig: Pubkey, squads: Pubkey) -> Pubkey:
    """Vault 0 of a multisig: the address that signs what the multisig executes."""
    return Pubkey.find_program_address([b"multisig", bytes(multisig), b"vault", bytes([0])], squads)[0]


def multisig_at(account: Account, address: str, squads: str) -> tuple[Multisig | None, str]:
    """The Squads multisig at `address`, read from chain, and what was found there in words."""
    got = account(address)
    if not got:
        return None, f"{address}: no such account"
    if got[0] != squads:
        return None, f"{address}: owned by {got[0]}, not by the Squads program {squads}"
    ms = read_multisig(got[1])
    if ms is None or str(multisig_address(ms.create_key, Pubkey.from_string(squads))) != address:
        return None, f"{address}: not a Squads multisig account"
    return ms, (f"{address}: time lock {ms.time_lock} s, {ms.threshold} of {len(ms.members)} members, "
                f"config authority {ms.config_authority or 'none'}")


def _day(t: int) -> str:
    try:
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return f"time {t}"


def _key_evidence(key: oidc.Key | None, now: int) -> str:
    if key is None:
        return "not registered"
    if key.state != 1:
        return "registered, KeyParams not sent"
    if key.revoked:
        return "revoked"
    if not (key.genesis or key.approved):
        return "attested, not approved by the guardian"
    if now < key.active_at:
        return f"not active before {_day(key.active_at)}"
    return ("genesis" if key.genesis else "approved") + (f", expired {_day(key.expires_at)}" if now >= key.expires_at else f", expires {_day(key.expires_at)}")


def names_key(elf: bytes, key: Pubkey) -> bool:
    """Whether a program binary has this 32-byte key built in. A compiler for Solana loads such a constant with four 64-bit
    immediates (`lddw`: the low half of each 8 bytes sits 4 bytes into an instruction and the high half 4 bytes into its
    second 8-byte slot, so the halves are 8 bytes apart) rather than keeping it as 32 bytes in a row; a key kept as data
    would be in a row. Both are looked for. Measured: tests/fixtures/knos_oidc_v2_real.so and knos_pay_v2_nodevnet.so hold
    the pinned guardian in the first form only."""
    raw = bytes(key)
    if raw in elf:
        return True
    return all(re.search(re.escape(raw[i:i + 4]) + b"\x00\x00\x00\x00" + re.escape(raw[i + 4:i + 8]), elf) for i in range(0, 32, 8))


def _guardian(account: Account, ids: dict, elfs: dict[str, bytes]) -> tuple[bool, str]:
    """Whether the GUARDIAN is vault 0 of the pinned guardian multisig (which no single key can change) and is the one both
    on-chain binaries name; and the evidence in words. `elfs`: each program's bytes on chain."""
    squads, guardian = Pubkey.from_string(ids["squads_program"]), Pubkey.from_string(ids["guardian"])
    gs, found = multisig_at(account, ids["guardian_multisig"], ids["squads_program"])
    its_vault = gs is not None and vault_address(Pubkey.from_string(ids["guardian_multisig"]), squads) == guardian
    named = [name for name in PROGRAMS if names_key(elfs[name], guardian)]
    return (its_vault and gs.config_authority is None and len(named) == len(PROGRAMS),
            found + ("" if gs is None else f"; vault 0 is {'' if its_vault else 'not '}{guardian}")
            + f"; named in the on-chain binary of: {', '.join(named) or 'neither program'}")


def _github_keys(fetch: Fetch, ids: dict) -> list[tuple[str, int, oidc.Key | None]]:
    """(kid, modulus, the key account's header or None when it is not on chain) for every key GitHub publishes now; none at
    all when GitHub's key list cannot be read."""
    doc = fetch.get(oidc.JWKS[oidc.GITHUB])
    out = []
    for kid, n in (oidc.jwks_keys(doc) if isinstance(doc, dict) else []):
        got = fetch.account(str(oidc.key_pda(oidc.GITHUB, n, Pubkey.from_string(ids["knos_oidc"]))))
        out.append((kid, n, oidc.read_key(got[1]) if got and got[0] == ids["knos_oidc"] else None))
    return out


def run(fetch: Fetch, ids: dict | None = None, env: dict | None = None) -> list[tuple[str, bool, str]]:
    env = os.environ if env is None else env
    ids = ids or oidc.IDS
    squads, vault = ids["squads_program"], ids["upgrade_authority"]
    res: list[tuple[str, bool, str]] = []
    elfs, hashes = {}, {}
    for name in PROGRAMS:
        deployed, authority, elf = program_data(fetch.account, ids[name])
        elfs[name], hashes[name] = elf, elf_hash(elf) if elf else None
        st = fetch.verified(name) or {}
        want = st.get("executable_hash")
        res.append((f"{name}: on-chain bytes are this repository's verified build", bool(elf) and want == hashes[name],
                    f"on-chain {hashes[name]}, verified build {want or 'none'}" + (f" ({st['source']})" if st.get("source") else "")))
        res.append((f"{name}: upgradeable only through the pinned vault", deployed and authority in (vault, None),
                    f"{ids[name]}: " + ("not deployed" if not deployed else "no upgrade authority (made immutable)" if authority is None else
                                        f"upgrade authority {authority}" + (", the pinned vault" if authority == vault else f", not the pinned vault {vault}"))))
        res.append((f"{name}: security.txt in the on-chain binary", SECURITY_TXT in elf,
                    "present" if SECURITY_TXT in elf else "not found"))

    ms, found = multisig_at(fetch.account, ids["upgrade_multisig"], squads)
    its_vault = ms is not None and str(vault_address(Pubkey.from_string(ids["upgrade_multisig"]), Pubkey.from_string(squads))) == vault
    res.append(("upgrade multisig: the pinned vault is its vault", its_vault,
                found if ms is None else f"vault 0 of {ids['upgrade_multisig']} is " + (vault if its_vault else f"not {vault}")))
    res.append((f"upgrade multisig: time lock is {TIME_LOCK} s (48 hours)", ms is not None and ms.time_lock == TIME_LOCK, found))
    res.append(("upgrade multisig: no config authority", ms is not None and ms.config_authority is None, found))

    res.append(("guardian: the vault both programs name is the pinned multisig's, which has no config authority", *_guardian(fetch.account, ids, elfs)))

    pins = {"rotate_sha": "knos_oidc", "claim_sha": "knos_pay"}     # the pin, and the program whose binary carries it
    bad = []
    for key, name in pins.items():
        pin = str(ids.get(key, ""))
        commit = fetch.get(f"https://api.github.com/repos/{PINS_REPO}/commits/{pin}") if len(pin) == 40 else None
        if len(pin) != 40 or pin.encode() not in elfs[name]:
            bad.append(f"{key} {pin or 'unset'} is not in the on-chain binary of {name}")
        elif not (isinstance(commit, dict) and commit.get("sha") == pin):
            bad.append(f"{key} {pin} is not a commit of {PINS_REPO}")
    res.append(("rotate and claim workflow pins are in the programs and on GitHub", not bad,
                "; ".join(bad) or f"{PINS_REPO}@{ids['rotate_sha']} (rotate) and @{ids['claim_sha']} (claim): in the binaries, and the commits exist"))

    keys, now = _github_keys(fetch, ids), fetch.now()
    usable = sum(oidc.key_usable(key, now)[0] for _kid, _n, key in keys)
    res.append(("every key GitHub publishes today verifies on chain", bool(keys) and usable == len(keys),
                f"{len(keys)} keys published; " + "; ".join(f"{kid[:8]}: {_key_evidence(key, now)}" for kid, _n, key in keys)
                if keys else f"{oidc.JWKS[oidc.GITHUB]} unreadable"))

    seen = {name: fetch.elsewhere(ids[name]) for name in PROGRAMS}
    res.append(("program ids are in use on no other cluster", all(v and all(there is False for there in v.values()) for v in seen.values()),
                "; ".join(f"{ids[name]}: " + (", ".join(f"{'unreadable' if there is None else 'IN USE' if there else 'not'} on {cluster}"
                                                           for cluster, there in v.items()) or "no other cluster was asked")
                          for name, v in seen.items())))

    ok, detail = fetch.program_checks()
    res.append(("program checks pass (Wycheproof, differential, property tests, fuzz, cargo-audit)", ok, detail))

    review, where = fetch.review()
    covered = isinstance(review, dict) and isinstance(review.get("programs"), dict) and all(
        hashes[name] and review["programs"].get(name) == hashes[name] for name in PROGRAMS)
    named_ok = isinstance(review, dict) and bool(review.get("reviewer")) and str(review.get("report", "")).startswith("https://")
    res.append(("outside review recorded, of the bytes on chain", covered and named_ok,
                where if review is None else f"{where}: " + (f"by {review.get('reviewer')}, {review.get('date')}, {review.get('report')}" if named_ok else "it needs a reviewer and a report at an https address")
                + ("" if covered else "; the hashes it records are not the on-chain programs'")))
    locked = env.get("KNOS_ALLOW_MAINNET") != "1"
    res.append(("mainnet: locked (by design)" if locked else "mainnet: UNLOCKED (KNOS_ALLOW_MAINNET=1)", locked,
                "the released binaries are devnet builds" if locked else "unset KNOS_ALLOW_MAINNET until the gates above pass"))
    return res


# ---- knos status ------------------------------------------------------------------------------------------------------

class Check(NamedTuple):
    name: str
    ok: bool
    evidence: str      # what was read from chain, in words
    todo: str          # what to do when it fails; empty when it passes


def _at(t: int) -> str:
    try:
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (OverflowError, OSError, ValueError):
        return f"time {t}"


def _program(account: Account, address: str) -> tuple[bool, str]:
    """Whether `address` is a deployed, executable program of the upgradeable loader whose bytes are at the address the
    loader derives from it, and what was found there in words."""
    got = account(address)
    if not got:
        return False, "no such account"
    if got[0] != str(LOADER):
        return False, f"owned by {got[0]}, not by the upgradeable loader"
    if got[1][:4] != (2).to_bytes(4, "little") or got[1][4:36] != bytes(programdata_address(address)):
        return False, "not a program account of the upgradeable loader"
    if len(got) > 2 and not got[2]:
        return False, "not executable"
    return True, "deployed, executable"


def _key_todo(key: oidc.Key | None, digest: str, now: int) -> str:
    """What to do about a published key that is not usable now, or ends within KEY_MARGIN, in words."""
    if key is not None and key.state == 1 and not key.revoked and not (key.genesis or key.approved):
        return f"the guardian approves it: node scripts/governance.mjs guardian approve github {digest}"
    ok, why = oidc.key_usable(key, now)
    if not ok:
        return why
    return f"it ends {_day(key.expires_at)}: run the rotate workflow and send Refresh with its token"


def status(fetch: Fetch, ids: dict | None = None, first: dict | None = None) -> list[Check]:
    """The eight things `knos status` says about the second deployment, read from chain (and GitHub's key list), each with
    what to do when it fails. `ids`: the second deployment's pinned ids (programs-v2/program_ids.json); `first`: the
    first deployment's (knos.settle program_ids.json)."""
    from .settle import oidc as first_oidc
    from .settle.v2 import pay

    ids, first = ids or oidc.IDS, first or first_oidc.IDS
    squads, vault, now = ids["squads_program"], ids["upgrade_authority"], fetch.now()
    res: list[Check] = []

    found = {name: _program(fetch.account, ids[name]) for name in PROGRAMS}
    res.append(Check("program ids: the pinned ones, deployed and executable", all(ok for ok, _ in found.values()),
                     "; ".join(f"{name} {ids[name]}: {why}" for name, (_, why) in found.items()),
                     "run scripts/deploy_v2.sh: it deploys what is missing and does nothing else"))

    data = {name: program_data(fetch.account, ids[name]) for name in PROGRAMS}
    immutable = all(deployed and authority is None for deployed, authority, _ in data.values())
    res.append(Check("upgrade authority: only the upgrade vault, or none once made immutable",
                     all(deployed and authority in (vault, None) for deployed, authority, _ in data.values()),
                     "; ".join(f"{name}: " + ("not deployed" if not deployed else "no upgrade authority (made immutable)" if authority is None else
                                              f"upgrade authority {authority}, " + ("the upgrade vault" if authority == vault else f"not the upgrade vault {vault}"))
                               for name, (deployed, authority, _) in data.items()),
                     f"hand each program to the upgrade vault: scripts/deploy_v2.sh does it when the fee payer's key file is the current authority; "
                     f"or solana program set-upgrade-authority <program id> --new-upgrade-authority {vault} "
                     "--skip-new-upgrade-authority-signer-check --upgrade-authority <the current authority's key file>"))

    ms, said = multisig_at(fetch.account, ids["upgrade_multisig"], squads)
    its_vault = ms is not None and str(vault_address(Pubkey.from_string(ids["upgrade_multisig"]), Pubkey.from_string(squads))) == vault
    moot = " (not needed now: both programs are immutable)" if immutable else ""
    fixed = ("a multisig's delay and its authority are fixed when it is made. Make a new upgrade multisig with node scripts/governance.mjs create, "
             "pin its addresses in programs-v2/program_ids.json and hand the programs to it; until then upgrades are not held to a public wait")
    res.append(Check(f"upgrade delay: an upgrade waits {TIME_LOCK // 3600} hours in public", immutable or (its_vault and ms.time_lock == TIME_LOCK),
                     said + ("" if ms is None else f"; vault 0 is {'' if its_vault else 'not '}{vault}") + moot, fixed))
    res.append(Check("upgrade multisig: no single key can change it", immutable or (ms is not None and ms.config_authority is None),
                     said + moot, fixed))

    ok, why = _guardian(fetch.account, ids, {name: elf for name, (_, _, elf) in data.items()})
    res.append(Check("guardian: the vault both programs name is the pinned multisig's", ok, why,
                     "the guardian is built into each program: upgrade both with a build that names the pinned guardian "
                     "(node scripts/governance.mjs upgrade propose <program> <buffer>), or, if its multisig is wrong, make it again with "
                     "node scripts/governance.mjs create and pin it"))

    keys, bad, todo, said = _github_keys(fetch, ids), [], [], []
    for kid, n, key in keys:
        digest = oidc.key_hash(n).hex()
        if oidc.key_usable(key, now)[0] and key.expires_at - now > KEY_MARGIN:
            said.append(f"{kid[:8]}: {_key_evidence(key, now)}")
        else:
            bad.append(kid)
            said.append(f"{kid[:8]} (key hash {digest}): {_key_evidence(key, now)}")
            todo.append(f"{kid[:8]}: {_key_todo(key, digest, now)}.")
    res.append(Check(f"GitHub's keys: every one registered, usable, and more than {KEY_MARGIN // 86_400} days from expiry", bool(keys) and not bad,
                     f"{len(keys)} keys published; " + "; ".join(said) if keys else f"{oidc.JWKS[oidc.GITHUB]} could not be read",
                     " ".join(todo) if keys else "run it again in a few minutes: GitHub's list of keys could not be read"))

    got = fetch.account(str(pay.pause_pda(Pubkey.from_string(ids["knos_pay"]))))
    until = pay.read_pause(got[1] if got else None)
    res.append(Check("new funding: not paused", not until > now,
                     f"paused until {_at(until)}" if until > now else "not paused" + (f" (the last pause ended {_at(until)})" if until else ""),
                     "the guardian lifts the pause: node scripts/governance.mjs guardian pause 0"))

    one = [(name, *program_data(fetch.account, first[name])[:2]) for name in PROGRAMS]
    res.append(Check("first deployment: still immutable", all(deployed and authority is None for _n, deployed, authority in one),
                     "; ".join(f"{name} {first[name]}: " + ("not deployed on this cluster" if not deployed else "no upgrade authority (immutable)" if authority is None
                                                           else f"upgradeable by {authority}") for name, deployed, authority in one),
                     "the first deployment is on devnet and must have no upgrade authority: point KNOS_RPC at devnet; if a program shows an upgrade "
                     "authority there, remove it for good with solana program set-upgrade-authority <program id> --final"))
    return [c if not c.ok else c._replace(todo="") for c in res]       # a line that passes has nothing to do


# ---- the real fetchers ----------------------------------------------------------------------------------------------

def _rpc(url: str) -> Account:
    def account(addr: str) -> tuple[str, bytes] | None:
        v = chain.call(url, "getAccountInfo", [addr, {"encoding": "base64", "commitment": "confirmed"}], timeout=30)["value"]
        return (v["owner"], base64.b64decode(v["data"][0]), bool(v.get("executable"))) if v else None
    return account


def _get(url: str):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "knos", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - fixed https URLs
            return json.load(r)
    except Exception:  # noqa: BLE001
        return None


def _last_run() -> tuple[int, list[dict]]:
    runs = json.loads(subprocess.run(
        ["gh", "run", "list", "--workflow", "program.yml", "--branch", "main", "--limit", "1", "--json", "databaseId"],
        capture_output=True, text=True, timeout=30, check=True).stdout)
    rid = runs[0]["databaseId"]
    jobs = json.loads(subprocess.run(["gh", "run", "view", str(rid), "--json", "jobs"], capture_output=True, text=True,
                                     timeout=30, check=True).stdout)["jobs"]
    return rid, jobs


def _verified(env: dict) -> Callable[[str], dict | None]:
    """The verified build of a program: `<name>.so` in KNOS_VERIFIED_DIR when that is set (a `solana-verify build` made
    on this machine); else the `<name>-v2-verified.so` artifact (the same build, in docker) of the last successful
    program.yml run on main. Hashed the way solana-verify does. (OtterSec's status API covers mainnet only.)"""
    import tempfile

    def verified(name: str) -> dict | None:
        local = env.get("KNOS_VERIFIED_DIR")
        try:
            if local:
                return {"executable_hash": elf_hash((Path(local) / f"{name}.so").read_bytes()), "source": f"{local}/{name}.so"}
            runs = json.loads(subprocess.run(
                ["gh", "run", "list", "--workflow", "program.yml", "--branch", "main", "--status", "success", "--limit", "1",
                 "--json", "databaseId"], capture_output=True, text=True, timeout=30, check=True).stdout)
            rid = runs[0]["databaseId"]
            with tempfile.TemporaryDirectory(dir=".") as d:  # relative, so a Windows gh.exe under WSL works too
                d = os.path.relpath(d)
                subprocess.run(["gh", "run", "download", str(rid), "-n", f"{name}-v2-verified.so", "-D", d],
                               capture_output=True, timeout=120, check=True)
                elf = open(os.path.join(d, f"{name}.so"), "rb").read()
            return {"executable_hash": elf_hash(elf), "source": f"program.yml run {rid} verified-build artifact"}
        except Exception:  # noqa: BLE001
            return None
    return verified


def _program_checks() -> tuple[bool, str]:
    try:
        rid, jobs = _last_run()
    except Exception as why:  # noqa: BLE001
        return False, f"gh could not read the last program.yml run ({type(why).__name__})"
    bad = [f"{j['name']}: {j.get('conclusion')}" for j in jobs if j.get("conclusion") not in ("success", "skipped")]
    return not bad, f"program.yml run {rid}: " + ("every job passed" if not bad else "; ".join(bad))


def _review() -> tuple[dict | None, str]:
    for root in (Path.cwd(), Path(__file__).resolve().parents[2]):
        p = root / "docs" / "review.json"
        if p.is_file():
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                return None, f"{p} is not JSON"
            return (doc, str(p)) if isinstance(doc, dict) else (None, f"{p} is not a JSON object")
    return None, "no docs/review.json: no outside review has been recorded"


def _elsewhere(url: str) -> Callable[[str], dict[str, bool | None]]:
    """Asks every public cluster but the one `url` is (told by its genesis hash) whether an account exists at an address."""
    here: list[str | None] = []

    def elsewhere(address: str) -> dict[str, bool | None]:
        if not here:
            try:
                here.append(GENESIS.get(chain.call(url, "getGenesisHash", [])))
            except Exception:  # noqa: BLE001
                here.append(None)
        out: dict[str, bool | None] = {}
        for name, other in PUBLIC.items():
            if name != here[0]:
                try:
                    out[name] = _rpc(other)(address) is not None
                except Exception:  # noqa: BLE001 - a cluster that cannot be read is reported, never taken as empty
                    out[name] = None
        return out
    return elsewhere


def _cluster(url: str) -> str:
    """Name the RPC's cluster from Solana's genesis hash, without exposing the endpoint URL."""
    try:
        return GENESIS.get(chain.call(url, "getGenesisHash", []), "unknown")
    except Exception:  # noqa: BLE001 - status still reports its checks when the cluster cannot be identified
        return "unknown"


def live(env: dict | None = None) -> Fetch:
    env = os.environ if env is None else env
    url = env.get("KNOS_RPC") or env.get("KNOS_SOLANA_RPC") or PUBLIC["devnet"]
    return Fetch(account=_rpc(url), verified=_verified(env), program_checks=_program_checks, get=_get, review=_review,
                 now=chain.Ledger(url).now, elsewhere=_elsewhere(url), cluster=lambda: _cluster(url))


def main(say: Callable[[str], None] = print, fetch: Fetch | None = None, as_json: bool = False) -> int:
    got = run(fetch or live())
    passed = sum(ok for _, ok, _ in got)
    if as_json:
        say(json.dumps({"gates": [{"gate": n, "pass": ok, "evidence": d} for n, ok, d in got], "passed": passed,
                        "of": len(got)}, indent=1))
        return 0 if passed == len(got) else 1
    for name, ok, detail in got:
        say(f"{'PASS' if ok else 'FAIL'}  {name}  ({detail})")
    say(f"{passed}/{len(got)} gates pass" + ("" if passed == len(got) else "; mainnet stays locked"))
    return 0 if passed == len(got) else 1


def status_main(say: Callable[[str], None] = print, fetch: Fetch | None = None, as_json: bool = False) -> int:
    """`knos status`: exit 0 only when every check passes."""
    source = fetch or live()
    got = status(source)
    passed = sum(c.ok for c in got)
    if as_json:
        say(json.dumps({"cluster": source.cluster() if source.cluster else "unknown",
                        "checks": [{"check": c.name, "pass": c.ok, "evidence": c.evidence, "next": c.todo if not c.ok else ""} for c in got],
                        "overall": passed == len(got), "passed": passed, "of": len(got)}, indent=1))
        return 0 if passed == len(got) else 1
    for c in got:
        say(f"{'PASS' if c.ok else 'FAIL'}  {c.name}  ({c.evidence})")
        if not c.ok:
            say(f"      Next: {c.todo}")
    say(f"{passed} of {len(got)} checks pass" + ("" if passed == len(got) else f"; {len(got) - passed} to fix"))
    return 0 if passed == len(got) else 1
