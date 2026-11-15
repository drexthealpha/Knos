"""The claim protocol's property test: exactly one winner, and the winner is never blocked.

Each round, five holders (five member keys, as on five machines) race for units drawn from an overlapping pool:
files, their directories, and a nested directory, under a fresh prefix. The units are only strings hashed with the
team salt, so they exist on no disk but the claimer's (none here at all). Decisions are read through a second RPC
endpoint that lags the node by 2-5 slots. Some rounds also send dust to a claim address first, and some have a
holder "crash" right after its create: the claim is on chain, undecided and never closed.

After every round:
  - no two winning claims overlap (zero double winners);
  - every winner is allowed to edit its unit by the guard's own rule (zero holder blocks), even while a later
    overlapping claim is pending or its claimer has crashed;
  - every other holder that overlaps a winner is refused.

Rounds: KNOSTEST_PROPERTY_N (default 10 in the normal suite; the ship runs 1,000 locally, PRs 10 and the nightly 200).
"""

from __future__ import annotations

import json
import os
import random
import secrets
import threading
from pathlib import Path

import pytest

from _devchain import URL, devchain, funded
from _lagproxy import LagProxy
from knos.team import live, protocol, registry, rpc, sas, schemas, units
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer

pytestmark = pytest.mark.slow  # nightly; `pytest -m slow` (needs the local validator)

ROUNDS = int(os.environ.get("KNOSTEST_PROPERTY_N", "10"))


def _claim_address(team, unit: str):
    """Where the protocol puts a unit's claim (protocol.claim's address), to dust it before anyone claims."""
    from solders.pubkey import Pubkey
    from knos.team import sas
    nonce = Pubkey.from_bytes(units.unit_hash(team.salt, team.repo_id, units.unit(unit)))
    return sas.attestation_pda(team.credential, team.claim_schema, nonce)


def _pool(prefix: str) -> list[tuple[str, int]]:
    return [(f"{prefix}/a/x.py", units.FILE), (f"{prefix}/a/y.py", units.FILE), (f"{prefix}/a/", units.DIR),
            (f"{prefix}/a/b/z.py", units.FILE), (f"{prefix}/a/b/", units.DIR), (f"{prefix}/c.py", units.FILE)]


def _retry(fn, tries: int = 6):
    """Harness calls only (setup, checks, clean-up): a slow shared validator must not end a 1,000-round run. The
    protocol under test gets no retries beyond its own."""
    import time
    for i in range(tries):
        try:
            return fn()
        except (OSError, TimeoutError, rpc.RpcError):
            if i == tries - 1:
                raise
            time.sleep(1 + i)


def _row(c: protocol.LiveClaim) -> tuple:
    return (str(c.address), c.data.unit_hash, c.data.ancestors, c.data.holder, str(c.signer), c.lease_until)


@devchain
def test_exactly_one_winner_and_the_winner_is_never_blocked():
    owner = funded(5)
    keys = [funded(3) for _ in range(5)]
    made = registry.create(URL, owner, [owner.pubkey(), *[k.pubkey() for k in keys]])
    proxy = LagProxy(URL, (2, 5), seed=7)
    team = protocol.Team(URL, made.credential, made.schemas["claim"], made.schemas["renew"],
                         secrets.token_bytes(32), secrets.token_bytes(32), (proxy.url,))
    holders = [protocol.Holder(k, host, f"machine-{i}", f"s{i}")
               for i, (k, host) in enumerate(zip(keys, ["claude-code", "codex", "cursor", "opencode", "sdk"]))]
    rng = random.Random(int(os.environ.get("KNOSTEST_PROPERTY_SEED", "11")))
    stats = {"rounds": 0, "claims": 0, "winners": 0, "lost": 0, "offline": 0, "stale": 0, "crashed": 0, "dust": 0,
             "double_winners": 0, "holder_blocks": 0, "unrefused_overlaps": 0}
    try:
        for r in range(ROUNDS):
            pool = _pool(f"r{r}-{secrets.token_hex(3)}")
            picks = [rng.choice(pool) for _ in holders]
            crasher = rng.randrange(len(holders)) if rng.random() < 0.3 else None
            if rng.random() < 0.3:  # dust on one claim address before anyone claims
                u, k = rng.choice(pool)
                pda = _claim_address(team, units.unit(u, directory=k == units.DIR))
                _retry(lambda: rpc.send(URL, [transfer(TransferParams(from_pubkey=owner.pubkey(), to_pubkey=pda,
                                                                      lamports=1_000_000))], owner))
                stats["dust"] += 1
            results: dict[int, protocol.Verdict] = {}

            def run(i: int) -> None:
                h, (u, k) = holders[i], picks[i]
                if i == crasher:  # create, then "crash": never decide, never close
                    unit = units.unit(u, directory=k == units.DIR)
                    uh, anc = units.unit_hash(team.salt, team.repo_id, unit), units.ancestors(team.salt,
                                                                                              team.repo_id, unit)
                    data = schemas.ClaimData(uh, anc, h.hash(team.salt), protocol.chain_time(URL) + 3600, k).encode()
                    try:
                        rpc.send(URL, [sas.create_attestation(h.key.pubkey(), h.key.pubkey(), team.credential,
                                                              team.claim_schema, Pubkey.from_bytes(uh), data)], h.key)
                    except (rpc.RpcError, OSError, TimeoutError):
                        pass
                    results[i] = protocol.Verdict("crashed")
                    return
                results[i] = protocol.claim(team, h, u, kind=k, within=60)

            threads = [threading.Thread(target=run, args=(i,)) for i in range(len(holders))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            winners = [i for i, v in results.items() if v.outcome in ("won", "held")]
            for i, v in results.items():
                stats["claims"] += 1
                key = {"won": "winners", "held": "winners", "lost": "lost", "offline": "offline", "stale": "stale",
                       "crashed": "crashed"}[v.outcome]
                stats[key] += 1
                if v.outcome == "offline":
                    stats.setdefault("offline_reasons", []).append(v.reason[:120])

            def hashes(i):
                u, k = picks[i]
                unit = units.unit(u, directory=k == units.DIR)
                return units.unit_hash(team.salt, team.repo_id, unit), units.ancestors(team.salt, team.repo_id, unit)

            for x in winners:
                for y in winners:
                    if x < y and holders[x].hash(team.salt) != holders[y].hash(team.salt) and \
                            units.overlaps(*hashes(x), *hashes(y)):
                        stats["double_winners"] += 1

            _, now_live = _retry(lambda: protocol.read_live(team, url=URL))
            now = _retry(lambda: protocol.chain_time(URL))
            rows = [_row(c) for c in now_live]
            for i in winners:
                verdicts = {str(results[i].address): "won"}
                what, _ = live.edit_rule(rows, holders[i].hash(team.salt), *hashes(i), now, verdicts)
                if what != "allow":
                    stats["holder_blocks"] += 1
            for i in range(len(holders)):
                if i in winners:
                    continue
                if any(units.overlaps(*hashes(i), *hashes(w)) and holders[i].hash(team.salt) != holders[w].hash(
                        team.salt) for w in winners):
                    what, _ = live.edit_rule(rows, holders[i].hash(team.salt), *hashes(i), now, {})
                    if what != "refuse":
                        stats["unrefused_overlaps"] += 1

            # give the rent back: winners release, crashed claims are closed by the owner's member key
            for i in winners:
                try:
                    protocol.release(team, holders[i], results[i].address)
                except Exception:
                    pass
            for c in now_live:
                if c.data.holder in {h.hash(team.salt) for h in holders} and any(
                        c.address == results[i].address for i in winners):
                    continue
                try:
                    rpc.send(URL, sas.compare_close(c.signer, owner.pubkey(), c.attestation, c.address), owner)
                except Exception:
                    pass
            stats["rounds"] += 1
            for k in keys:
                if _retry(lambda: rpc.balance(URL, k.pubkey())) < 500_000_000:
                    _retry(lambda: rpc.airdrop(URL, k.pubkey(), 2_000_000_000))
    finally:
        proxy.close()
        stats["lagged_reads_served_stale"] = proxy.stale_served
        stats["min_context_refusals"] = proxy.min_context_refused
        out = os.environ.get("KNOSTEST_PROPERTY_OUT")
        if out:
            Path(out).write_text(json.dumps(stats, indent=1), encoding="utf-8")
    assert stats["double_winners"] == 0, stats
    assert stats["holder_blocks"] == 0, stats
    assert stats["unrefused_overlaps"] == 0, stats
    assert stats["winners"] > 0, stats
