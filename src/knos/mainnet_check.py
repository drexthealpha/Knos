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

Exit 1 while any gate fails. A gate that cannot be checked from where the command runs (the verified build and the
program checks read program.yml's runs through `gh`; the review is a file of the repository) is shown as SKIP with
"not checked from here: needs a clone", and is not a failure: from a pip install most gates are checked and those
are not, and the summary line says how many. Run it in a clone of the repository for every gate. All I/O goes through
`Fetch`, so tests inject fakes.

`knos status` (status() below) is the shorter question asked of a deployment that is meant to be running now, read from
chain, each line with what to do when it fails:

    program ids         the two pinned ids are deployed and executable
    upgrade authority   each program's upgrade authority is the upgrade vault (or none, once made immutable)
    upgrade multisig    its time lock is 172800 seconds and it has no config authority
    upgrade proposal    no upgrade (or change) is pending on the upgrade multisig; one that is, with its index, the
                        buffer and when it can execute (the Squads accounts are read as scripts/governance.mjs
                        documents them: see `proposals`)
    guardian            the GUARDIAN both programs name is vault 0 of the pinned guardian multisig
    GitHub's keys       every key GitHub publishes today is registered, usable now and more than 7 days from expiry
    key refresh         the last Refresh of a key is under 7 days old (a key lives 30 days from its last one)
    new funding         not paused
    first deployment    both programs of the first deployment still have no upgrade authority
    refund              a refund has executed on the second deployment's knos_pay, in its newest transactions
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
REPO = "drexthealpha/Knos"      # whose program.yml runs `gh` reads, wherever the command is run
NOT_HERE = "not checked from here: needs a clone"
NEEDS_GH = NOT_HERE + " (and gh, logged in to GitHub)"
PROGRAMS = ("knos_oidc", "knos_pay")
NEW_PROGRAMS = ("knos_meter", "knos_passkey")       # new in 0.3.13: the release run deploys them, so until it has they are "not deployed yet"
TIME_LOCK = 172_800      # seconds between the vote that approves an upgrade and its execution
KEY_MARGIN = 7 * 86_400  # `knos status`: a key must outlive today by this much, so that the rotate workflow has a week to refresh it
MULTISIG = hashlib.sha256(b"account:Multisig").digest()[:8]   # Anchor's discriminator of a Squads v4 Multisig account
PROPOSAL = hashlib.sha256(b"account:Proposal").digest()[:8]
VAULT_TX = hashlib.sha256(b"account:VaultTransaction").digest()[:8]
CONFIG_TX = hashlib.sha256(b"account:ConfigTransaction").digest()[:8]
LOOK_BACK = 10           # the newest proposals of the upgrade multisig that `knos status` reads (as scripts/governance.mjs does)
REFUND_SCAN = 200        # the newest transactions of knos_pay that are read for a refund
REFRESH_MARGIN = 7 * 86_400
PUBLIC = {"devnet": "https://api.devnet.solana.com", "testnet": "https://api.testnet.solana.com",
          "mainnet-beta": "https://api.mainnet-beta.solana.com"}
GENESIS = {"EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG": "devnet", "4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY": "testnet",
           "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d": "mainnet-beta"}

# (owner, data) or (owner, data, executable) of an account, None when there is none. The program accounts a status check
# reads must carry the executable flag; every other check needs the first two.
Account = Callable[[str], "tuple[str, bytes] | tuple[str, bytes, bool] | None"]


@dataclass
class Fetch:
    """account(addr) -> (owner, data) or None; verified(name) -> {"executable_hash", "source"} or None, or {"unchecked":
    why} when it cannot be read from here; program_checks() -> (ok, detail), ok None when it cannot be read from here;
    get(url) -> parsed JSON, None when the host answered that there is nothing there, and raises Unreachable when it
    could not be asked; review() -> (docs/review.json parsed or None, where it was looked for: NOT_HERE when there is no
    clone to look in); now() -> the cluster's clock; elsewhere(addr) -> {other public cluster: whether an account
    exists there at addr, None when that cluster could not be read}."""

    account: Account
    verified: Callable[[str], dict | None]
    program_checks: Callable[[], tuple[bool, str]]
    get: Callable[[str], dict | list | None]
    review: Callable[[], tuple[dict | None, str]]
    now: Callable[[], int]
    elsewhere: Callable[[str], dict[str, bool | None]]
    refunded: "Callable[[str], tuple[int, int] | None] | None" = None    # (refunds found, transactions read) in a program's newest transactions; None: not readable
    cluster: Callable[[], str] | None = None    # the RPC's cluster, named from its genesis hash; None: "unknown"


class Unreachable(Exception):
    """A host could not be asked (no network, a rate limit, a server error): not an answer. Its text is the reason."""


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
    transaction_index: int = 0          # the index of the newest transaction (and proposal) the multisig has made
    stale_transaction_index: int = 0    # every transaction at or below this index is void


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
                    members=[Pubkey.from_bytes(data[at + 4 + 33 * k:at + 36 + 33 * k]) for k in range(count)],
                    transaction_index=int.from_bytes(data[78:86], "little"), stale_transaction_index=int.from_bytes(data[86:94], "little"))


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


# ---- Squads proposals: what is waiting on the upgrade multisig ------------------------------------------------------------
# Squads v4 accounts, borsh behind an 8-byte Anchor discriminator (sha256("account:<Name>")[:8]); every Vec has a u32 count:
#   Proposal            multisig 32 | transaction_index u64 | status: a u8 tag (0 Draft, 1 Active, 2 Rejected, 3 Approved,
#                       4 Executing, 5 Executed, 6 Cancelled) then, for every tag but 4, the i64 time it was entered |
#                       bump u8 | approved: Vec<Pubkey> | rejected | cancelled
#   VaultTransaction    multisig 32 | creator 32 | index u64 | bump u8 | vault_index u8 | vault_bump u8 |
#                       ephemeral_signer_bumps: Vec<u8> | message: num_signers u8, num_writable_signers u8,
#                       num_writable_non_signers u8, account_keys: Vec<Pubkey>, instructions: Vec<(program_id_index u8,
#                       account_indexes: Vec<u8>, data: Vec<u8>)>, address_table_lookups
#   addresses           proposal  ["multisig", multisig, "transaction", index u64 LE, "proposal"]
#                       transaction  ["multisig", multisig, "transaction", index u64 LE]
# The upgradeable loader's Upgrade instruction is data 03 00 00 00 with accounts [programdata, program, buffer, spill,
# rent, clock, authority], as upgradeIx in scripts/governance.mjs builds it. An approved proposal can execute once its
# multisig's time lock has run from the time it was approved; an active one has not yet the approvals it needs.
STATUSES = ("Draft", "Active", "Rejected", "Approved", "Executing", "Executed", "Cancelled")


@dataclass
class Proposal:
    index: int
    status: str
    at: int                 # when it entered that status (0 for Executing, which holds none)
    approved: int           # how many members approved it


@dataclass
class Pending:
    """A proposal of the upgrade multisig that has not finished."""
    index: int
    status: str
    approved: int
    threshold: int
    kind: str               # "upgrade" (the loader's Upgrade), "config" (a change to the multisig itself) or "other"
    program: str | None     # an upgrade's program
    buffer: str | None      # and the buffer holding the bytes it would deploy
    executes_at: int | None  # when it can be executed: approval time + the time lock; None until it is approved


def proposal_address(multisig: Pubkey, index: int, squads: Pubkey) -> Pubkey:
    return Pubkey.find_program_address([b"multisig", bytes(multisig), b"transaction", index.to_bytes(8, "little"), b"proposal"], squads)[0]


def transaction_address(multisig: Pubkey, index: int, squads: Pubkey) -> Pubkey:
    return Pubkey.find_program_address([b"multisig", bytes(multisig), b"transaction", index.to_bytes(8, "little")], squads)[0]


def read_proposal(data: bytes | None) -> Proposal | None:
    """A Squads v4 Proposal account; None for anything else."""
    if not data or len(data) < 8 + 32 + 8 + 1 or data[:8] != PROPOSAL:
        return None
    tag = data[48]
    if tag >= len(STATUSES):
        return None
    at = 49
    when = 0
    if tag != 4:
        if len(data) < at + 8:
            return None
        when, at = int.from_bytes(data[at:at + 8], "little", signed=True), at + 8
    at += 1                                                    # bump
    if len(data) < at + 4:
        return None
    count = int.from_bytes(data[at:at + 4], "little")
    if count > 65_535 or len(data) < at + 4 + 32 * count:
        return None
    return Proposal(index=int.from_bytes(data[40:48], "little"), status=STATUSES[tag], at=when, approved=count)


def read_transaction(data: bytes | None) -> tuple[str, str | None, str | None]:
    """(kind, program, buffer) of what a Squads transaction account would run: "upgrade" with the program and the buffer when
    it carries the upgradeable loader's Upgrade, "config" for a change to the multisig itself, "other" for the rest
    (or for an account of a layout this does not know)."""
    if data and data[:8] == CONFIG_TX:
        return "config", None, None
    if not data or data[:8] != VAULT_TX:
        return "other", None, None
    try:
        at = 8 + 32 + 32 + 8 + 3
        at += 4 + int.from_bytes(data[at:at + 4], "little")                     # ephemeral signer bumps
        at += 3                                                                  # the three signer counts
        nkeys = int.from_bytes(data[at:at + 4], "little")
        keys = [str(Pubkey.from_bytes(data[at + 4 + 32 * k:at + 36 + 32 * k])) for k in range(nkeys)]
        at += 4 + 32 * nkeys
        count = int.from_bytes(data[at:at + 4], "little")
        at += 4
        for _ in range(count):
            program = data[at]
            n = int.from_bytes(data[at + 1:at + 5], "little")
            accounts = list(data[at + 5:at + 5 + n])
            at += 5 + n
            size = int.from_bytes(data[at:at + 4], "little")
            body = data[at + 4:at + 4 + size]
            at += 4 + size
            if keys[program] == str(LOADER) and body[:4] == (3).to_bytes(4, "little") and len(accounts) >= 3:
                return "upgrade", keys[accounts[1]], keys[accounts[2]]
    except (IndexError, ValueError):
        pass
    return "other", None, None


def pending_proposals(account: Account, multisig: str, ms: Multisig, squads: str, look_back: int = LOOK_BACK) -> list[Pending]:
    """The unfinished proposals (Draft, Active, Approved) among the newest `look_back` of a multisig, newest first. Those at or
    below its stale index are void and not read; a proposal that is not on chain was never made."""
    out = []
    squads_key, ms_key = Pubkey.from_string(squads), Pubkey.from_string(multisig)
    for index in range(ms.transaction_index, max(ms.stale_transaction_index, ms.transaction_index - look_back), -1):
        got = account(str(proposal_address(ms_key, index, squads_key)))
        p = read_proposal(got[1]) if got and got[0] == squads else None
        if p is None or p.status not in ("Draft", "Active", "Approved"):
            continue
        tx = account(str(transaction_address(ms_key, index, squads_key)))
        kind, program, buffer = read_transaction(tx[1] if tx and tx[0] == squads else None)
        out.append(Pending(index=index, status=p.status, approved=p.approved, threshold=ms.threshold, kind=kind, program=program,
                           buffer=buffer, executes_at=p.at + ms.time_lock if p.status == "Approved" else None))
    return out


def _pending_words(p: Pending, now: int) -> str:
    what = (f"an upgrade of program {p.program} from buffer {p.buffer}" if p.kind == "upgrade" else
            "a change to the upgrade multisig itself (its members, threshold or delay)" if p.kind == "config" else "a transaction of the upgrade vault")
    if p.status == "Approved":
        left = max(0, p.executes_at - now)
        when = (f"it can be executed from {_at(p.executes_at)} (in {left // 3600} h {left % 3600 // 60} min)" if left else
                f"its delay is over ({_at(p.executes_at)}): anyone in the multisig can execute it now")
        return f"proposal {p.index}: {what}; approved by {p.approved} of {p.threshold} members needed; {when}"
    if p.status == "Active":
        return (f"proposal {p.index}: {what}; {p.approved} of {p.threshold} approvals so far; it can be executed {TIME_LOCK // 3600} hours after the "
                "last approval is given")
    return f"proposal {p.index}: {what}; drafted, not yet put to the members' vote"


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
    try:
        doc = fetch.get(oidc.JWKS[oidc.GITHUB])
    except Unreachable:
        doc = None
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
        res.append((f"{name}: on-chain bytes are this repository's verified build", None if st.get("unchecked") else bool(elf) and want == hashes[name],
                    st["unchecked"] if st.get("unchecked") else f"on-chain {hashes[name]}, verified build {want or 'none'}" + (f" ({st['source']})" if st.get("source") else "")))
        res.append((f"{name}: upgradeable only through the pinned vault", deployed and authority in (vault, None),
                    f"{ids[name]}: " + ("not deployed" if not deployed else "no upgrade authority (made immutable)" if authority is None else
                                        f"upgrade authority {authority}" + (", the pinned vault" if authority == vault else f", not the pinned vault {vault}"))))
        res.append((f"{name}: security.txt in the on-chain binary", SECURITY_TXT in elf,
                    "present" if SECURITY_TXT in elf else "not found"))

    # knos_meter and knos_passkey are new in this release: not deployed yet is not checked (and not a failure); deployed, they are held to the vault
    new = {name: _new_program(fetch.account, ids[name], vault) for name in NEW_PROGRAMS if ids.get(name)}
    res.append(("knos_meter, knos_passkey: deployed, executable, upgradeable only through the pinned vault",
                False if any(ok is False for ok, _ in new.values()) else None if any(ok is None for ok, _ in new.values()) or not new else True,
                "; ".join(f"{name} {ids[name]}: {why}" for name, (_, why) in new.items()) or "none is pinned"))

    ms, found = multisig_at(fetch.account, ids["upgrade_multisig"], squads)
    its_vault = ms is not None and str(vault_address(Pubkey.from_string(ids["upgrade_multisig"]), Pubkey.from_string(squads))) == vault
    res.append(("upgrade multisig: the pinned vault is its vault", its_vault,
                found if ms is None else f"vault 0 of {ids['upgrade_multisig']} is " + (vault if its_vault else f"not {vault}")))
    res.append((f"upgrade multisig: time lock is {TIME_LOCK} s (48 hours)", ms is not None and ms.time_lock == TIME_LOCK, found))
    res.append(("upgrade multisig: no config authority", ms is not None and ms.config_authority is None, found))

    res.append(("guardian: the vault both programs name is the pinned multisig's, which has no config authority", *_guardian(fetch.account, ids, elfs)))

    pins = {"rotate_sha": "knos_oidc", "claim_sha": "knos_pay"}     # the pin, and the program whose binary carries it
    bad, unreached = [], []
    for key, name in pins.items():
        pin = str(ids.get(key, ""))
        if len(pin) != 40 or pin.encode() not in elfs[name]:
            bad.append(f"{key} {pin or 'unset'} is not in the on-chain binary of {name}")
            continue
        try:
            commit = fetch.get(f"https://api.github.com/repos/{PINS_REPO}/commits/{pin}")
        except Unreachable as why:
            unreached.append(str(why))
            continue
        if not (isinstance(commit, dict) and commit.get("sha") == pin):
            bad.append(f"{key} {pin} is not a commit of {PINS_REPO}")
    pin_name = "rotate and claim workflow pins are in the programs and on GitHub"
    if bad:
        res.append((pin_name, False, "; ".join(bad)))
    elif unreached:       # GitHub was not asked successfully: that says nothing about the pins
        res.append((pin_name, None, f"could not reach GitHub ({unreached[0]}), so the commits of {PINS_REPO} were not checked; the pins are in the binaries"))
    else:
        res.append((pin_name, True, f"{PINS_REPO}@{ids['rotate_sha']} (rotate) and @{ids['claim_sha']} (claim): in the binaries, and the commits exist"))

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
    res.append(("outside review recorded, of the bytes on chain", None if where == NOT_HERE else covered and named_ok,
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


def _new_program(account: Account, address: str, vault: str) -> tuple[bool | None, str]:
    """A program this release adds (knos_meter, knos_passkey): (None, "not deployed yet") while nothing is at its
    address, which is how it stands until the release run deploys it; else whether it is deployed, executable and
    upgradeable only through the upgrade vault (or by nobody), and what was found in words."""
    if not account(address):
        return None, "not deployed yet (the release run deploys it)"
    ok, why = _program(account, address)
    if not ok:
        return False, why
    deployed, authority, _elf = program_data(account, address)
    if not deployed:
        return False, "its ProgramData account is not on this cluster"
    return authority in (vault, None), why + ", " + ("no upgrade authority (made immutable)" if authority is None else
                                                     f"upgrade authority {authority}, " + ("the upgrade vault" if authority == vault else f"not the upgrade vault {vault}"))


def _key_todo(key: oidc.Key | None, digest: str, now: int) -> str:
    """What to do about a published key that is not usable now, or ends within KEY_MARGIN, in words."""
    if key is not None and key.state == 1 and not key.revoked and not (key.genesis or key.approved):
        return f"the guardian approves it: node scripts/governance.mjs guardian approve github {digest}"
    ok, why = oidc.key_usable(key, now)
    if not ok:
        return why
    return f"it ends {_day(key.expires_at)}: run the rotate workflow and send Refresh with its token"


def status(fetch: Fetch, ids: dict | None = None, first: dict | None = None) -> list[Check]:
    """The twelve things `knos status` says about the second deployment, read from chain (and GitHub's key list), each with
    what to do when it fails. `ids`: the second deployment's pinned ids (programs-v2/program_ids.json); `first`: the
    first deployment's (knos.settle program_ids.json)."""
    from .settle import oidc as first_oidc
    from .settle.v2 import gate, pay

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

    # the programs this release adds: nothing at their addresses until the release run deploys them, which is not a fault
    new = {name: _new_program(fetch.account, ids[name], vault) for name in NEW_PROGRAMS if ids.get(name)}
    res.append(Check("new programs: knos_meter and knos_passkey are deployed and executable, upgradeable only through the upgrade vault; or not deployed yet",
                     all(ok is not False for ok, _ in new.values()),
                     "; ".join(f"{name} {ids[name]}: {why}" for name, (_, why) in new.items()) or "none is pinned",
                     "what is at a pinned address must be the program, in the upgrade vault's hands: run scripts/deploy_v2.sh (it deploys what is missing "
                     f"and hands it over), or solana program set-upgrade-authority <program id> --new-upgrade-authority {vault} "
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

    if immutable:
        res.append(Check("upgrade proposal: nothing pending on the upgrade multisig", True, "both programs are immutable: nothing can be proposed", ""))
    elif ms is None:
        res.append(Check("upgrade proposal: nothing pending on the upgrade multisig", False, f"{said}; so its proposals could not be read",
                         "fix the upgrade multisig first (the lines above); until then a pending upgrade cannot be seen"))
    else:
        waiting = pending_proposals(fetch.account, ids["upgrade_multisig"], ms, squads)
        head = waiting[0] if waiting else None
        res.append(Check("upgrade proposal: nothing pending on the upgrade multisig", not waiting,
                         # an upgrade's buffer is held against upgrade_gate's record: whether a GitHub run built exactly those bytes
                         "; ".join(_pending_words(p, now) + (gate.words(fetch.account, p.program, p.buffer) if p.kind == "upgrade" else "") for p in waiting) or
                         f"no proposal is pending on {ids['upgrade_multisig']} ({ms.transaction_index} made so far; the newest {LOOK_BACK} were read)",
                         "" if head is None else
                         (f"before it runs, compare the buffer with the verified build: solana program dump {head.buffer} buffer.so, and its hash "
                          "(sha256 without trailing zeros) with the executable hash of this repository's verified build. " if head.buffer else "") +
                         f"If it is not expected, members vote to cancel it: node scripts/governance.mjs cancel upgrade {head.index}. "
                         "This line passes again once it has executed or been cancelled."))

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

    # A Refresh moves a key's expiry to now + the key's life if that is later, so the newest Refresh is the newest expiry less the life.
    refreshed = max((key.expires_at - oidc.KEY_TTL for _kid, _n, key in keys if key is not None and key.state == 1 and not key.revoked), default=None)
    age = None if refreshed is None else now - refreshed
    res.append(Check(f"key refresh: the last one is under {REFRESH_MARGIN // 86_400} days old", age is not None and age < REFRESH_MARGIN,
                     "no key of GitHub's is on chain to read a refresh from" if age is None else
                     f"the last key refresh was {_at(refreshed)}, {max(0, age) // 86_400} day{'' if max(0, age) // 86_400 == 1 else 's'} {max(0, age) % 86_400 // 3600} h ago",
                     "run the rotate workflow and send Refresh with its token; anyone can (the workflow run by hand in a repository you own counts), "
                     "so do not wait for the scheduled run"))

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
    seen = fetch.refunded(ids["knos_pay"]) if fetch.refunded else None
    refund_todo = ("a refund has to be seen on the deployed bytes: fund a small bounty with a 1-day deadline (knos fund-wallet owner/repo#N 5 --days 1 "
                   "--mint <mint>), leave it unpaid, and the relay refunds it after the deadline (anyone can send the refund)")
    res.append(Check("refund: one has executed on the second deployment", bool(seen and seen[0]),
                     f"knos_pay {ids['knos_pay']}: the history could not be read here" if seen is None else
                     f"knos_pay {ids['knos_pay']}: " + (f"{seen[0]} refund{'s' if seen[0] != 1 else ''} in its newest {seen[1]} transactions" if seen[0]
                                                         else f"no refund in its newest {seen[1]} transactions"),
                     refund_todo))
    return [c if not c.ok else c._replace(todo="") for c in res]       # a line that passes has nothing to do


# ---- the real fetchers ----------------------------------------------------------------------------------------------

def _rpc(url: str) -> Account:
    def account(addr: str) -> tuple[str, bytes] | None:
        v = chain.call(url, "getAccountInfo", [addr, {"encoding": "base64", "commitment": "confirmed"}], timeout=30)["value"]
        return (v["owner"], base64.b64decode(v["data"][0]), bool(v.get("executable"))) if v else None
    return account


def _get(url: str):
    """Parsed JSON; None when the host says there is nothing there (404); Unreachable for anything else that went wrong, with
    the rate-limit hint for a 403 or 429. GH_TOKEN, when set, goes to GitHub's API only to lift its rate limit."""
    from . import ghwords
    headers = {"User-Agent": "knos", "Accept": "application/json"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:  # noqa: S310 - fixed https URLs
            return json.load(r)
    except Exception as why:  # noqa: BLE001
        code = ghwords.code_of(why)
        if code == 404:
            return None
        raise Unreachable(f"HTTP {code}; {ghwords.RATE}" if code in (403, 429) else ghwords.first_line(why)) from None


class NeedsClone(Exception):
    """A gate that is read from a clone of the repository or through `gh`, and neither is here."""


def _clone() -> Path | None:
    """The clone of this repository the command runs in (or from), found by programs-v2/program_ids.json; None from a pip install."""
    here = Path.cwd().resolve()
    for d in (here, *here.parents, Path(__file__).resolve().parents[2]):
        if (d / "programs-v2" / "program_ids.json").is_file():
            return d
    return None


def _gh(*args: str) -> str:
    """`gh` for the repository's own runs (named with -R, so it needs no clone); NeedsClone when gh is missing, not logged in, or fails."""
    try:
        got = subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True, timeout=120)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        raise NeedsClone(NEEDS_GH) from None
    if got.returncode != 0:
        raise NeedsClone(NEEDS_GH)
    return got.stdout


def _last_run(*more: str) -> tuple[int, list[dict]]:
    """(the id of the last program.yml run on main, its jobs). LookupError when there is none."""
    runs = json.loads(_gh("run", "list", "--workflow", "program.yml", "--branch", "main", "--limit", "1", "--json", "databaseId", *more))
    if not runs:
        raise LookupError("no program.yml run on main")
    rid = runs[0]["databaseId"]
    return rid, json.loads(_gh("run", "view", str(rid), "--json", "jobs"))["jobs"]


def _verified(env: dict) -> Callable[[str], dict | None]:
    """The verified build of a program: `<name>.so` in KNOS_VERIFIED_DIR when that is set (a `solana-verify build` made
    on this machine); else the `<name>-v2-verified.so` artifact (the same build, in docker) of the last successful
    program.yml run on main, read with `gh` (without it: {"unchecked": ...}, not a failure). Hashed the way solana-verify
    does. (OtterSec's status API covers mainnet only.)"""
    import tempfile

    def verified(name: str) -> dict | None:
        local = env.get("KNOS_VERIFIED_DIR")
        try:
            if local:
                return {"executable_hash": elf_hash((Path(local) / f"{name}.so").read_bytes()), "source": f"{local}/{name}.so"}
            runs = json.loads(_gh("run", "list", "--workflow", "program.yml", "--branch", "main", "--status", "success", "--limit", "1", "--json", "databaseId"))
            rid = runs[0]["databaseId"]
            with tempfile.TemporaryDirectory(dir=".") as d:  # relative, so a Windows gh.exe under WSL works too
                d = os.path.relpath(d)
                _gh("run", "download", str(rid), "-n", f"{name}-v2-verified.so", "-D", d)
                elf = open(os.path.join(d, f"{name}.so"), "rb").read()
            return {"executable_hash": elf_hash(elf), "source": f"program.yml run {rid} verified-build artifact"}
        except NeedsClone as why:
            return {"unchecked": str(why)}
        except Exception:  # noqa: BLE001
            return None
    return verified


def _program_checks() -> tuple[bool | None, str]:
    try:
        rid, jobs = _last_run()
    except NeedsClone as why:
        return None, str(why)
    except Exception as why:  # noqa: BLE001
        return False, f"gh could not read the last program.yml run ({type(why).__name__}: {why})"
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
    if _clone() is None:
        return None, NOT_HERE
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


def _refunded(url: str) -> Callable[[str], tuple[int, int] | None]:
    """Refunds that executed, counted in the newest REFUND_SCAN transactions of a program (stopping at the first batch that holds one)."""
    def refunded(program: str) -> tuple[int, int] | None:
        from . import records
        try:
            return records.count_events(url, program, "refunded", REFUND_SCAN)
        except Exception:  # noqa: BLE001 - the cluster did not answer: not read, never "none"
            return None
    return refunded


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
                 now=chain.Ledger(url).now, elsewhere=_elsewhere(url), refunded=_refunded(url), cluster=lambda: _cluster(url))


def main(say: Callable[[str], None] = print, fetch: Fetch | None = None, as_json: bool = False) -> int:
    """`knos mainnet-check`: exit 1 while any gate fails. A gate that could not be checked from here is not one."""
    got = run(fetch or live())
    passed, failed, skipped = (sum(ok is want for _, ok, _ in got) for want in (True, False, None))
    if as_json:
        say(json.dumps({"gates": [{"gate": n, "pass": ok, "evidence": d} for n, ok, d in got], "passed": passed, "of": len(got),
                        "failed": failed, "not_checked": skipped}, indent=1))
        return 1 if failed else 0
    for name, ok, detail in got:
        say(f"{'SKIP' if ok is None else 'PASS' if ok else 'FAIL'}  {name}  ({detail})")
    say(f"{passed}/{len(got)} gates pass"
        + (f"; {skipped} not checked from here, which is not a failure (run it in a clone of the repository to check them)" if skipped else "")
        + ("; mainnet stays locked" if failed else ""))
    return 1 if failed else 0


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
