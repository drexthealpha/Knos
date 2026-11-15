"""Records anyone can verify: counters plus a Merkle root on chain, signed by the agent's member key."""

from __future__ import annotations

import hashlib
import secrets


from _devchain import URL, devchain, new_team
from knos.team import records, rpc


def test_merkle_root_and_proofs():
    leaves = [hashlib.sha256(bytes([i])).digest() for i in range(7)]
    root = records.merkle_root(leaves)
    assert root == records.merkle_root(list(reversed(leaves)))  # order of the log does not matter
    for x in leaves:
        assert records.verify_proof(x, records.proof(leaves, x), root)
    assert not records.verify_proof(hashlib.sha256(b"not in it").digest(), records.proof(leaves, leaves[0]), root)
    assert records.merkle_root([]) == b"\0" * 32


def test_build_counts_only_this_holder_and_period():
    salt, me, other = b"s" * 32, b"m" * 32, b"o" * 32
    start = records.period_start(1_800_000_000)
    ev = [{"ts": start + 1, "kind": "claim", "holder": me.hex(), "claim": "A"},
          {"ts": start + 2, "kind": "release", "holder": me.hex(), "claim": "A"},
          {"ts": start + 3, "kind": "claim", "holder": me.hex(), "claim": "B"},
          {"ts": start + 4, "kind": "lapsed", "holder": me.hex(), "claim": "B"},
          {"ts": start + 5, "kind": "blocked", "holder": me.hex()},
          {"ts": start + 6, "kind": "claim", "holder": other.hex()},
          {"ts": start + records.DAY + 1, "kind": "claim", "holder": me.hex()}]
    p = records.build(salt, me, start, ev, [{"id": "j1", "body": "decided sqlite"}])
    assert (p.taken, p.finished, p.abandoned, p.collisions) == (2, 1, 1, 1)
    assert len(p.leaves) == 6
    # no plaintext: leaves are salted hashes
    assert all(b"sqlite" not in x for x in p.leaves)


@devchain
def test_a_record_is_written_once_and_verifies_against_the_log():
    team, _, (a,) = new_team(1)
    holder = secrets.token_bytes(32)
    start = records.period_start() - records.DAY
    ev = [{"ts": start + 10, "kind": "claim", "holder": holder.hex(), "claim": "X"},
          {"ts": start + 20, "kind": "release", "holder": holder.hex(), "claim": "X"}]
    p = records.build(team.salt, holder, start, ev, [])
    assert records.write(URL, team.credential, a, p)
    assert records.write(URL, team.credential, a, p) is None  # once per period
    got = records.verify(URL, team.credential, p)
    assert got["on_chain"] and got["counters_match"] and got["root_matches"] and got["signer"] == str(a.pubkey())
    tampered = records.build(team.salt, holder, start, ev[:1], [])
    got = records.verify(URL, team.credential, tampered)
    assert not got["counters_match"] and not got["root_matches"]
    raw = rpc.account_data(URL, records.record_address(team.credential, holder, start))[1]
    assert b"release" not in raw and b"claim" not in raw


@devchain
def test_a_journal_entry_is_proven_against_the_record_on_chain(knos_home, repo):
    from datetime import datetime, timezone

    from knos.memory import Fact, Memory
    from knos.team import live
    team, _, (a,) = new_team(1)
    tf = __import__("knos.team.config", fromlist=["TeamFile"]).TeamFile(
        "localnet", team.credential, "knos-t", a.pubkey(), {"claim": team.claim_schema, "renew": team.renew_schema},
        team.repo_id, URL)
    rt = live.Runtime(repo, tf, a, team.salt, "m1")
    holder = rt.holder("claude", "sess1").hash(team.salt)
    with Memory(repo) as mem:
        mem.record(Fact(text="decided to shard by tenant", source="note", where="claude/sess1 said so",
                        when=datetime.now(timezone.utc).isoformat()))
        mem.record(Fact(text="something codex said", source="note", where="codex/x said so",
                        when=datetime.now(timezone.utc).isoformat()))
    start = records.period_start()
    j = live.journal_for(rt, holder, start)
    assert [x["text"] for x in j] == ["decided to shard by tenant"]  # only this agent host's entries
    p = live.period_of(rt, holder, start, j)
    assert records.write(URL, team.credential, a, p)
    _, rec = records.read(URL, team.credential, holder, start)
    target = records.leaf(team.salt, {"journal": j[0]})
    assert records.verify_proof(target, records.proof(p.leaves, target), rec.merkle_root)
