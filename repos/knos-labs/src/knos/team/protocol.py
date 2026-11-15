"""The claim protocol: exactly one winner per overlapping unit, across machines, with no server.

A claim is a SAS attestation whose nonce is the salted unit hash, so two creates of one unit cannot both succeed.
Units that merely overlap (a file and its directory) have different nonces, so the winner is decided by order:

1. The creation slot of a claim is the slot of the latest successful transaction that ran SAS `CreateAttestation`
   on its address (found with getSignaturesForAddress; a PDA can be re-created after a close).
2. After its create confirms at slot S, a claimer reads every live claim with `commitment=confirmed` and
   `minContextSlot=S`. It wins only if no overlapping live claim by another holder has a lower (slot, address).
   Otherwise it closes its own claim and reports who it lost to.
3. A create that fails because the PDA exists with this holder's own hash counts as already held.
4. Renewals never re-create: a `knos.renew.v1` attestation extends the lease, and each renewal compare-closes the
   previous one. Renewals not signed by the claim's signer, or naming another holder, are ignored.
5. Every close is compare-then-close (Lighthouse), with the rent refunded to the claim's signer. Claims of other
   holders are swept only when they are 10+ minutes past their effective lease by chain time.
"""

from __future__ import annotations

import base64
import hashlib
import struct
import time
from dataclasses import dataclass

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from . import rpc, sas, schemas, units

LEASE_S = 60 * 60
SWEEP_GRACE_S = 10 * 60
@dataclass(frozen=True)
class Team:
    """What the protocol needs about a team: the public `.knos/team.json` plus this machine's copy of the salt."""
    url: str
    credential: Pubkey
    claim_schema: Pubkey
    renew_schema: Pubkey
    repo_id: bytes
    salt: bytes
    read_urls: tuple[str, ...] = ()

    @property
    def readers(self) -> tuple[str, ...]:
        return self.read_urls or (self.url,)


@dataclass(frozen=True)
class Holder:
    """One agent: a person's member key, the agent host, the machine and the session."""
    key: Keypair
    host: str
    machine: str
    session: str = ""

    def hash(self, salt: bytes) -> bytes:
        return units.holder_hash(salt, bytes(self.key.pubkey()), self.host, self.machine, self.session)


@dataclass
class LiveClaim:
    address: Pubkey
    signer: Pubkey
    data: schemas.ClaimData
    attestation: sas.Attestation
    lease_until: int  # effective: the later of the claim's own lease and its valid renewal
    renewal: tuple[Pubkey, sas.Attestation] | None = None

    def overlaps(self, unit_hash: bytes, ancestors: bytes) -> bool:
        return units.overlaps(self.data.unit_hash, self.data.ancestors, unit_hash, ancestors)


@dataclass
class Verdict:
    outcome: str  # won | held | lost | stale | offline
    address: Pubkey | None = None
    slot: int | None = None
    lost_to: LiveClaim | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome in ("won", "held")


# ---- reading the chain ------------------------------------------------------------------------------------------

def _attestations(url: str, credential: Pubkey, schema: Pubkey, min_context_slot: int | None = None,
                  timeout: float = 10.0) -> tuple[int, list[tuple[Pubkey, sas.Attestation]]]:
    cfg: dict = {"encoding": "base64", "commitment": "confirmed", "withContext": True,
                 "filters": [{"memcmp": {"offset": 0, "bytes": "3"}},  # base58 of the single byte 2: Attestation
                             {"memcmp": {"offset": 33, "bytes": str(credential)}},
                             {"memcmp": {"offset": 65, "bytes": str(schema)}}]}
    if min_context_slot is not None:
        cfg["minContextSlot"] = min_context_slot
    got = rpc.call(url, "getProgramAccounts", [str(sas.PROGRAM_ID), cfg], timeout)
    out = []
    for item in got["value"]:
        try:
            out.append((Pubkey.from_string(item["pubkey"]),
                        sas.parse_attestation(base64.b64decode(item["account"]["data"][0]))))
        except (ValueError, struct.error, KeyError, IndexError):
            continue
    return got["context"]["slot"], out


def read_live(team: Team, min_context_slot: int | None = None, url: str | None = None,
              timeout: float = 10.0) -> tuple[int, list[LiveClaim]]:
    """(context slot, every claim under the team's credential, each with its effective lease)."""
    url = url or team.readers[0]
    slot, claims = _attestations(url, team.credential, team.claim_schema, min_context_slot, timeout)
    _, renews = _attestations(url, team.credential, team.renew_schema, min_context_slot, timeout)
    by_claim: dict[bytes, list[tuple[Pubkey, sas.Attestation, schemas.RenewData]]] = {}
    for addr, att in renews:
        try:
            rd = schemas.RenewData.decode(att.data)
        except (ValueError, struct.error):
            continue
        by_claim.setdefault(rd.claim, []).append((addr, att, rd))
    out = []
    for addr, att in claims:
        try:
            cd = schemas.ClaimData.decode(att.data)
        except (ValueError, struct.error):
            continue
        live = LiveClaim(addr, att.signer, cd, att, cd.lease_until)
        for raddr, ratt, rd in by_claim.get(bytes(addr), []):
            if ratt.signer == att.signer and rd.holder == cd.holder and rd.lease_until > live.lease_until:
                live.lease_until, live.renewal = rd.lease_until, (raddr, ratt)
        out.append(live)
    return slot, out


def read_units(team: Team, unit: str, min_context_slot: int | None = None, url: str | None = None,
               timeout: float = 10.0) -> tuple[int, list[LiveClaim]]:
    """The live claims that can overlap a FILE unit: its own and its ancestor directories'. Their addresses are
    derivable, so this is one getMultipleAccounts, not a scan of the program. (A directory unit also overlaps claims
    below it, which only a scan finds: use read_live for those.) Renewals are looked up only for a claim whose own
    lease has passed, which is the only time one can matter."""
    url = url or team.readers[0]
    wanted = [unit, *units.ancestor_units(unit)]
    addrs = [sas.attestation_pda(team.credential, team.claim_schema,
                                 Pubkey.from_bytes(units.unit_hash(team.salt, team.repo_id, u))) for u in wanted]
    cfg: dict = {"encoding": "base64", "commitment": "confirmed"}
    if min_context_slot is not None:
        cfg["minContextSlot"] = min_context_slot
    got = rpc.call(url, "getMultipleAccounts", [[str(a) for a in addrs], cfg], timeout)
    out = []
    now = None
    for addr, item in zip(addrs, got["value"]):
        if not item:
            continue
        try:
            att = sas.parse_attestation(base64.b64decode(item["data"][0]))
            cd = schemas.ClaimData.decode(att.data)
        except (ValueError, struct.error, KeyError, IndexError):
            continue
        live = LiveClaim(addr, att.signer, cd, att, cd.lease_until)
        if now is None and cd.lease_until <= time.time() + 60:
            now = chain_time(url, timeout)
        if now is not None and cd.lease_until <= now:
            for raddr, ratt in renewals_of(team, addr, url):
                try:
                    rd = schemas.RenewData.decode(ratt.data)
                except (ValueError, struct.error):
                    continue
                if ratt.signer == att.signer and rd.holder == cd.holder and rd.lease_until > live.lease_until:
                    live.lease_until, live.renewal = rd.lease_until, (raddr, ratt)
        out.append(live)
    return got["context"]["slot"], out


def renewals_of(team: Team, claim: Pubkey, url: str | None = None) -> list[tuple[Pubkey, sas.Attestation]]:
    """Every live renewal naming `claim`, valid or not (a renewer compare-closes its previous one)."""
    _, renews = _attestations(url or team.readers[0], team.credential, team.renew_schema)
    out = []
    for addr, att in renews:
        try:
            if schemas.RenewData.decode(att.data).claim == bytes(claim):
                out.append((addr, att))
        except (ValueError, struct.error):
            continue
    return out


def chain_time(url: str, timeout: float = 5.0) -> int:
    """Unix time of the latest confirmed slot: sweeps go by this, never by the local clock."""
    slot = rpc.call(url, "getSlot", [{"commitment": "confirmed"}], timeout)
    for s in (slot, slot - 1, slot - 2):
        try:
            t = rpc.call(url, "getBlockTime", [s], timeout)
        except rpc.RpcError:
            continue
        if t is not None:
            return int(t)
    raise rpc.RpcError("no block time")


_slot_cache: dict[tuple[str, str], str] = {}


def _sas_action(url: str, signature: str, address: Pubkey, timeout: float) -> str | None:
    """'create' or 'close' if the transaction ran that SAS instruction on `address`, else None."""
    key = (str(address), signature)
    if key in _slot_cache:
        return _slot_cache[key]
    got = rpc.call(url, "getTransaction", [signature, {"encoding": "base64", "commitment": "confirmed",
                                                      "maxSupportedTransactionVersion": 0}], timeout)
    if not got or (got.get("meta") or {}).get("err"):
        return None
    tx = VersionedTransaction.from_bytes(base64.b64decode(got["transaction"][0]))
    msg = tx.message
    keys = list(msg.account_keys)
    loaded = (got.get("meta") or {}).get("loadedAddresses") or {}
    keys += [Pubkey.from_string(k) for k in loaded.get("writable", []) + loaded.get("readonly", [])]
    what = None
    for ix in msg.instructions:
        if keys[ix.program_id_index] != sas.PROGRAM_ID or not ix.data:
            continue
        accts = [keys[i] for i in bytes(ix.accounts)]
        if ix.data[0] == sas.IX_CREATE_ATTESTATION and len(accts) > 4 and accts[4] == address:
            what = "create"
        elif ix.data[0] == sas.IX_CLOSE_ATTESTATION and len(accts) > 3 and accts[3] == address:
            what = "close"
    if what:
        _slot_cache[key] = what
    return what


def creation_slot(url: str, address: Pubkey, min_context_slot: int | None = None, timeout: float = 10.0,
                  pages: int = 5) -> int | None:
    """The slot of the latest successful CreateAttestation of the live account at `address`; None if the history
    seen so far cannot say (the caller treats that as not proven earlier, and asks again)."""
    before = None
    for _ in range(pages):
        cfg: dict = {"limit": 100, "commitment": "confirmed"}
        if min_context_slot is not None:
            cfg["minContextSlot"] = min_context_slot
        if before:
            cfg["before"] = before
        sigs = rpc.call(url, "getSignaturesForAddress", [str(address), cfg], timeout) or []
        for s in sigs:
            if s.get("err"):
                continue
            what = _sas_action(url, s["signature"], address, timeout)
            if what == "create":
                return int(s["slot"])
            if what == "close":
                return None
        if len(sigs) < 100:
            return None
        before = sigs[-1]["signature"]
    return None


# ---- writing ------------------------------------------------------------------------------------------------------

def _with_min_context(fn, deadline: float):
    """Retry a read while the endpoint has not reached the asked slot yet (it lags), until `deadline`."""
    while True:
        try:
            return fn()
        except rpc.RpcError as e:
            lagging = "minimum context slot" in str(e).lower()
            if not lagging or time.monotonic() > deadline:
                raise
            time.sleep(0.2)


def decide(mine: Pubkey, my_slot: int, my_holder: bytes, unit_hash: bytes, ancestors: bytes,
           live: list[LiveClaim], slots: dict[str, int | None], now: int) -> LiveClaim | None:
    """The claim this one lost to, or None if it wins. Pure, so the property test can check it directly.

    A live claim by another holder that overlaps and is still within its lease beats this one if its (slot,
    address) is lower. A claim whose slot cannot be established yet is assumed earlier: losing is safe, a double
    winner is not."""
    best = None
    for c in live:
        if c.address == mine or c.data.holder == my_holder:
            continue
        if not c.overlaps(unit_hash, ancestors) or c.lease_until <= now:
            continue
        s = slots.get(str(c.address))
        earlier = s is None or (s, bytes(c.address)) < (my_slot, bytes(mine))
        if earlier and (best is None or (slots.get(str(best.address)) or 0) > (s or 0)):
            best = c
    return best


def claim(team: Team, holder: Holder, unit: str, kind: int = units.FILE, lease_s: int = LEASE_S,
          within: float = 5.0, payer: Keypair | None = None) -> Verdict:
    """Place a claim on `unit` and decide it. `within` bounds the whole call; an RPC failure or a timeout returns
    `offline` so the caller can fall back to local mode instead of blocking work."""
    deadline = time.monotonic() + within
    my_holder = holder.hash(team.salt)
    unit = units.unit(unit, directory=kind == units.DIR)
    uh = units.unit_hash(team.salt, team.repo_id, unit)
    anc = units.ancestors(team.salt, team.repo_id, unit)
    nonce = Pubkey.from_bytes(uh)
    addr = sas.attestation_pda(team.credential, team.claim_schema, nonce)
    left = lambda: max(0.5, deadline - time.monotonic())  # noqa: E731
    try:
        lease = chain_time(team.url, timeout=left()) + lease_s
        data = schemas.ClaimData(uh, anc, my_holder, lease, kind).encode()
        payer = payer or holder.key
        ix = sas.create_attestation(payer.pubkey(), holder.key.pubkey(), team.credential, team.claim_schema, nonce,
                                    data)
        outcome = "won"
        try:
            sig = rpc.send(team.url, [ix], payer, [holder.key], timeout=left(), confirm_within=left())
            my_slot = int(rpc.call(team.url, "getSignatureStatuses", [[sig]], left())["value"][0]["slot"])
        except rpc.RpcError:
            # Refused in preflight, or lost the race on chain (two creates of one address both pass preflight;
            # the second fails with AccountAlreadyInUse). Either way: whose is the address now?
            _, live = (read_units(team, unit, url=team.url, timeout=left()) if kind == units.FILE
                       else read_live(team, url=team.url, timeout=left()))
            c = next((x for x in live if x.address == addr), None)
            if c is None:
                raise
            if c.data.holder != my_holder:
                if c.lease_until <= chain_time(team.url, timeout=left()):
                    # its holder stopped renewing; a sweep closes it once the grace has passed
                    return Verdict("stale", addr, lost_to=c, reason="claim past its lease, not yet swept")
                return Verdict("lost", addr, lost_to=c, reason="unit already claimed")
            # Ours already (an earlier call may have timed out after it landed): still decide it against rivals.
            data, outcome = c.attestation.data, "held"
            found = None
            while True:  # the signature index can trail the account by a moment
                found = _with_min_context(lambda: creation_slot(team.url, addr, None, left()), deadline)
                if found is not None or time.monotonic() > deadline - 0.5:
                    break
                time.sleep(0.3)
            if found is None:
                return Verdict("offline", addr, reason="own claim's creation not visible yet")
            my_slot = found
        reader = team.readers[-1]
        if kind == units.FILE:
            _, live = _with_min_context(lambda: read_units(team, unit, my_slot, reader, left()), deadline)
        else:
            _, live = _with_min_context(lambda: read_live(team, my_slot, reader, left()), deadline)
        now = chain_time(team.url, timeout=left())
        rivals = [c for c in live if c.address != addr and c.data.holder != my_holder
                  and c.overlaps(uh, anc) and c.lease_until > now]
        slots: dict[str, int | None] = {}
        for c in rivals:
            slots[str(c.address)] = _with_min_context(
                lambda c=c: creation_slot(reader, c.address, my_slot, left()), deadline)
        if outcome == "held" and any(s is None for s in slots.values()):
            # never give up a claim this agent may already have won on an unproven rival: ask again later
            return Verdict("offline", addr, my_slot, reason="a rival's creation slot is not visible yet")
        loser_to = decide(addr, my_slot, my_holder, uh, anc, rivals, slots, now)
        if loser_to is None:
            return Verdict(outcome, addr, my_slot)
        mine = sas.Attestation(nonce, team.credential, team.claim_schema, data, holder.key.pubkey(), 0,
                               Pubkey.default())
        try:
            rpc.send(team.url, sas.compare_close(holder.key.pubkey(), holder.key.pubkey(), mine, addr), payer,
                     [holder.key])
        except (rpc.RpcError, OSError, TimeoutError):
            pass  # it lapses at its lease, and a later sweep closes it
        return Verdict("lost", addr, my_slot, lost_to=loser_to)
    except (OSError, TimeoutError, rpc.RpcError, KeyError, TypeError) as e:
        return Verdict("offline", addr, reason=str(e)[:200])


def renew(team: Team, holder: Holder, address: Pubkey, lease_s: int = LEASE_S, timeout: float = 10.0,
          payer: Keypair | None = None) -> int:
    """Extend a claim this holder owns; returns the new lease end. One transaction creates the new renewal and
    compare-closes the previous one, so at most one renewal per claim stays live."""
    payer = payer or holder.key
    _, raw = rpc.account_data(team.url, address, timeout=timeout)
    if raw is None:
        raise LookupError("claim not found")
    att = sas.parse_attestation(raw)
    if att.signer != holder.key.pubkey() or schemas.ClaimData.decode(att.data).holder != holder.hash(team.salt):
        raise PermissionError("not this agent's claim")
    new_lease = chain_time(team.url, timeout) + lease_s
    nonce = Pubkey.from_bytes(hashlib.sha256(bytes(address) + struct.pack("<q", new_lease)).digest())
    data = schemas.RenewData(bytes(address), holder.hash(team.salt), new_lease).encode()
    ixs = [sas.create_attestation(payer.pubkey(), holder.key.pubkey(), team.credential, team.renew_schema, nonce,
                                  data)]
    for raddr, ratt in renewals_of(team, address):
        if ratt.signer == holder.key.pubkey():
            ixs += sas.compare_close(ratt.signer, holder.key.pubkey(), ratt, raddr)
    rpc.send(team.url, ixs, payer, [holder.key], timeout=timeout)
    return new_lease


def release(team: Team, holder: Holder, address: Pubkey, timeout: float = 10.0, payer: Keypair | None = None) -> bool:
    """Compare-close this holder's claim and its renewals; rent goes back to the signer. False if already gone."""
    payer = payer or holder.key
    _, raw = rpc.account_data(team.url, address, timeout=timeout)
    if raw is None:
        return False
    att = sas.parse_attestation(raw)
    if schemas.ClaimData.decode(att.data).holder != holder.hash(team.salt):
        raise PermissionError("not this agent's claim")
    ixs = sas.compare_close(att.signer, holder.key.pubkey(), att, address)
    for raddr, ratt in renewals_of(team, address):
        ixs += sas.compare_close(ratt.signer, holder.key.pubkey(), ratt, raddr)
    rpc.send(team.url, ixs, payer, [holder.key], timeout=timeout)
    return True


def sweep(team: Team, closer: Keypair, timeout: float = 10.0, limit: int = 8,
          grace: int = SWEEP_GRACE_S) -> list[Pubkey]:
    """Close other holders' claims that are 10+ minutes past their effective lease by chain time. Each close
    asserts the exact bytes read (including the renewal, if one was seen), so a claim renewed in between survives."""
    now = chain_time(team.url, timeout)
    _, live = read_live(team, url=team.url, timeout=timeout)
    closed = []
    for c in live:
        if len(closed) >= limit or c.lease_until + grace > now:
            continue
        ixs = sas.compare_close(c.signer, closer.pubkey(), c.attestation, c.address)
        if c.renewal:
            ixs += sas.compare_close(c.renewal[1].signer, closer.pubkey(), c.renewal[1], c.renewal[0])
        try:
            rpc.send(team.url, ixs, closer, timeout=timeout)
            closed.append(c.address)
        except (rpc.RpcError, OSError, TimeoutError):
            continue
    return closed
