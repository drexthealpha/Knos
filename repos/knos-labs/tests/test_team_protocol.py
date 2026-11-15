"""The claim protocol, live on a local validator with the devnet-deployed SAS and Lighthouse; plus the pure parts
(units, hashing, the verdict rule) with no chain at all."""

from __future__ import annotations

import functools
import secrets
import time

import pytest

from knos.team import protocol, registry, rpc, sas, schemas, units
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from _devchain import URL, devchain, new_team

# the guard waits 5 s; tests allow more because the validator shares a small machine with the suite
claim = functools.partial(protocol.claim, within=30)


# ---- units and hashing: no chain ----------------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("Src/A.py", "src/a.py"),
    ("src\\billing\\tax.py", "src/billing/tax.py"),
    ("./src//billing/tax.py", "src/billing/tax.py"),
    ("file:src/a.py", "src/a.py"),
    ("café.py", "café.py"),  # NFD and NFC spell one unit
])
def test_one_unit_on_every_os(a, b):
    assert units.unit(a) == units.unit(b)
    salt, rid = b"s" * 32, b"r" * 32
    assert units.unit_hash(salt, rid, units.unit(a)) == units.unit_hash(salt, rid, units.unit(b))


def test_directories_and_schemes():
    assert units.unit("src/billing/**") == "src/billing/"
    assert units.unit("src/billing", directory=True) == "src/billing/"
    assert units.unit("task:Invoice-4411") == "task:invoice-4411"
    assert units.ancestors(b"s", b"r", "task:x") == b""
    assert len(units.ancestors(b"s", b"r", "a/b/c.py")) == 16  # a/ and a/b/
    assert len(units.ancestors(b"s", b"r", "a/b/")) == 8


def test_overlap_rule():
    salt, rid = secrets.token_bytes(32), secrets.token_bytes(32)

    def h(u):
        return units.unit_hash(salt, rid, u), units.ancestors(salt, rid, u)

    f, d, other, sib = h("src/billing/tax.py"), h("src/billing/"), h("src/other.py"), h("src/billing2/")
    assert units.overlaps(*f, *d) and units.overlaps(*d, *f)
    assert not units.overlaps(*f, *other)
    assert not units.overlaps(*d, *sib)
    assert units.overlaps(*h("src/"), *f)


def test_different_salts_hide_units():
    rid = b"r" * 32
    assert units.unit_hash(b"a" * 32, rid, "src/a.py") != units.unit_hash(b"b" * 32, rid, "src/a.py")


def test_holder_hash_separates_agents_and_carries_the_host():
    salt, signer = secrets.token_bytes(32), secrets.token_bytes(32)
    a = units.holder_hash(salt, signer, "claude-code", "m1")
    b = units.holder_hash(salt, signer, "codex", "m1")
    c = units.holder_hash(salt, signer, "claude-code", "m2")
    assert len({a, b, c}) == 3
    assert units.holder_host(salt, a) == "claude-code" and units.holder_host(salt, b) == "codex"


def test_decide_is_order_by_slot_then_address():
    salt, rid = b"s" * 32, b"r" * 32
    uh, anc = units.unit_hash(salt, rid, "a/b.py"), units.ancestors(salt, rid, "a/b.py")
    dh, danc = units.unit_hash(salt, rid, "a/"), units.ancestors(salt, rid, "a/")
    mine = Pubkey.from_bytes(b"\x05" * 32)

    def live(addr_byte, holder, h=dh, a=danc, lease=10 ** 10):
        cd = schemas.ClaimData(h, a, holder, lease, 1)
        att = sas.Attestation(Pubkey.default(), Pubkey.default(), Pubkey.default(), cd.encode(), Pubkey.default(), 0,
                              Pubkey.default())
        return protocol.LiveClaim(Pubkey.from_bytes(bytes([addr_byte]) * 32), Pubkey.default(), cd, att, lease)

    earlier, later = live(9, b"x" * 32), live(1, b"y" * 32)
    slots = {str(earlier.address): 10, str(later.address): 12}
    assert protocol.decide(mine, 11, b"m" * 32, uh, anc, [earlier, later], slots, 0) is earlier
    assert protocol.decide(mine, 9, b"m" * 32, uh, anc, [earlier, later], slots, 0) is None
    # same slot: the lower address wins
    assert protocol.decide(mine, 10, b"m" * 32, uh, anc, [earlier], slots, 0) is None  # 05.. < 09..
    lower = live(1, b"z" * 32)
    assert protocol.decide(mine, 10, b"m" * 32, uh, anc, [lower], {str(lower.address): 10}, 0) is lower
    # unknown slot: assumed earlier (lose rather than risk two winners)
    assert protocol.decide(mine, 10, b"m" * 32, uh, anc, [later], {}, 0) is later
    # expired, own, and non-overlapping claims never beat it
    assert protocol.decide(mine, 99, b"m" * 32, uh, anc, [live(2, b"q" * 32, lease=5)], {}, 6) is None
    assert protocol.decide(mine, 99, b"m" * 32, uh, anc, [live(2, b"m" * 32)], {}, 0) is None
    far = units.unit_hash(salt, rid, "z.py")
    assert protocol.decide(mine, 99, b"m" * 32, uh, anc, [live(2, b"q" * 32, h=far, a=b"")], {}, 0) is None


def test_codecs_round_trip():
    cd = schemas.ClaimData(b"u" * 32, b"a" * 16, b"h" * 32, 123, 1)
    assert schemas.ClaimData.decode(cd.encode()) == cd
    rd = schemas.RenewData(b"c" * 32, b"h" * 32, -5)
    assert schemas.RenewData.decode(rd.encode()) == rd
    rec = schemas.RecordData(b"h" * 32, 1, 2, 3, 4, 5, 6, b"m" * 32)
    assert schemas.RecordData.decode(rec.encode()) == rec
    with pytest.raises(ValueError):
        schemas.ClaimData.decode(cd.encode() + b"x")


# ---- live ---------------------------------------------------------------------------------------------------------

def _holder(key, host="claude-code", machine="m1"):
    return protocol.Holder(key, host, machine)


@devchain
def test_schemas_on_chain_match_the_layout_byte_for_byte():
    team, owner, _ = new_team(1)
    for spec in schemas.ALL:
        _, raw = rpc.account_data(URL, sas.schema_pda(team.credential, spec[0]))
        assert raw == schemas.schema_account_bytes(team.credential, spec)


@devchain
def test_claim_hold_lose_release():
    team, _, (a, b) = new_team(2)
    alice, bob = _holder(a), _holder(b, "codex", "m2")
    v = claim(team, alice, "src/billing/tax.py")
    assert v.outcome == "won", v.reason
    assert claim(team, alice, "src/billing/tax.py").outcome == "held"
    lost = claim(team, bob, "Src/Billing/TAX.py")
    assert lost.outcome == "lost" and lost.lost_to.signer == a.pubkey()
    # the directory overlaps the file: bob creates, reads, sees alice earlier, closes his own
    d = claim(team, bob, "src/billing/", kind=units.DIR)
    assert d.outcome == "lost" and d.lost_to.address == v.address
    assert rpc.account_data(URL, d.address)[1] is None  # bob's losing claim was closed
    # no plaintext on chain: the unit is only a salted hash
    raw = rpc.account_data(URL, v.address)[1]
    assert b"billing" not in raw and b"tax" not in raw
    assert protocol.release(team, alice, v.address)
    assert claim(team, bob, "src/billing/tax.py").outcome == "won"


@devchain
def test_two_agents_of_one_person_are_different_holders():
    team, _, (a,) = new_team(1)
    assert claim(team, _holder(a, "claude-code"), "x.py").outcome == "won"
    assert claim(team, _holder(a, "codex"), "x.py").outcome == "lost"


@devchain
def test_renewal_extends_and_replaces_the_previous_one():
    team, _, (a,) = new_team(1)
    h = _holder(a)
    v = claim(team, h, "r.py", lease_s=60)
    first = protocol.renew(team, h, v.address, lease_s=600)
    time.sleep(1.2)
    second = protocol.renew(team, h, v.address, lease_s=1200)
    assert second > first
    assert len(protocol.renewals_of(team, v.address)) == 1
    _, live = protocol.read_live(team)
    assert next(c for c in live if c.address == v.address).lease_until == second
    assert protocol.release(team, h, v.address)
    assert protocol.renewals_of(team, v.address) == []


@devchain
def test_forged_renewal_is_ignored():
    team, _, (a, b) = new_team(2)
    v = claim(team, _holder(a), "f.py", lease_s=60)
    # bob writes a renewal for alice's claim: wrong signer, so it does not extend the lease
    data = schemas.RenewData(bytes(v.address), _holder(a).hash(team.salt), 10 ** 10).encode()
    nonce = Pubkey.from_bytes(secrets.token_bytes(32))
    rpc.send(URL, [sas.create_attestation(b.pubkey(), b.pubkey(), team.credential, team.renew_schema, nonce, data)], b)
    _, live = protocol.read_live(team)
    assert next(c for c in live if c.address == v.address).lease_until < 10 ** 10


@devchain
def test_sweep_closes_only_expired_claims_and_refunds_the_signer():
    team, owner, (a, b) = new_team(2)
    old = claim(team, _holder(a), "old.py", lease_s=1)
    fresh = claim(team, _holder(a), "fresh.py", lease_s=3600)
    time.sleep(2.5)
    before = rpc.balance(URL, a.pubkey())
    closed = protocol.sweep(team, b, grace=0)
    assert old.address in closed and fresh.address not in closed
    assert rpc.balance(URL, a.pubkey()) > before  # rent back to the claim's signer, not the sweeper
    assert rpc.account_data(URL, fresh.address)[1] is not None


@devchain
def test_stale_claim_is_reported_stale_not_lost():
    team, _, (a, b) = new_team(2)
    claim(team, _holder(a), "s.py", lease_s=1)
    time.sleep(2.5)
    assert claim(team, _holder(b, "codex"), "s.py").outcome == "stale"


@devchain
def test_rpc_down_is_offline_not_an_error():
    team, _, (a,) = new_team(1)
    dead = protocol.Team("http://127.0.0.1:9", team.credential, team.claim_schema, team.renew_schema, team.repo_id,
                         team.salt)
    v = protocol.claim(dead, _holder(a), "o.py", within=1.0)
    assert v.outcome == "offline"


@devchain
def test_member_salt_and_name_are_sealed():
    team, owner, (a, b) = new_team(2)
    salt = secrets.token_bytes(32)
    registry.add_member_attestation(URL, owner, team.credential, a.pubkey(), "alice", salt)
    assert registry.my_salt(URL, team.credential, a) == salt
    assert registry.members(URL, team.credential, salt)[str(a.pubkey())]["name"] == "alice"
    raw = rpc.account_data(URL, sas.attestation_pda(team.credential, sas.schema_pda(team.credential,
                                                                                    "knos.member.v1"), a.pubkey()))[1]
    assert b"alice" not in raw and salt not in raw
    with pytest.raises(Exception):
        registry.open_salt(schemas.MemberData.decode(sas.parse_attestation(raw).data).salt_box, b)


def test_free_plan_covers_three_member_keys(monkeypatch, tmp_path):
    from knos.team import config, service
    owner = Keypair()
    tf = config.TeamFile("devnet", Pubkey.from_bytes(b"\1" * 32), "knos-x", owner.pubkey(),
                         {"member": Pubkey.from_bytes(b"\2" * 32)}, b"\0" * 32)
    three = [owner.pubkey(), *[Keypair().pubkey() for _ in range(3)]]
    monkeypatch.setattr(registry, "signers", lambda url, cred: three)
    monkeypatch.setattr(service, "team_seats", lambda: 0)
    monkeypatch.setattr(service, "public_repo", lambda repo, timeout=5.0: False)
    code = service.join_code(Keypair().pubkey(), "dana")
    with pytest.raises(service.TeamError, match="Team plan"):
        service.add(tf, owner, code, repo=tmp_path)
    monkeypatch.setattr(service, "public_repo", lambda repo, timeout=5.0: True)
    monkeypatch.setattr(service, "_fund", lambda *a: None)
    monkeypatch.setattr(registry, "set_signers", lambda *a: "sig")
    monkeypatch.setattr(service.rpc, "account_data", lambda *a, **k: (0, b"x"))
    monkeypatch.setattr(config, "salt", lambda *a, **k: b"s" * 32)
    assert service.add(tf, owner, code, repo=tmp_path)["steps"] == ["added"]  # a public open-source repo is free
