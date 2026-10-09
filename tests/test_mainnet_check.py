"""knos mainnet-check, offline: every gate driven by injected fetchers. The gates are about the second deployment:
what is on chain is the verified build, only the pinned vault can upgrade it, that vault belongs to a multisig whose
time lock is 48 hours and that no single key can change, the guardian is the pinned one, GitHub's keys verify, the
program ids are used on no other cluster, and an outside review of those bytes is on record."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

from knos import mainnet_check as mc
from knos.settle.v2 import oidc, pay

NOW = 1_790_000_000
SQUADS = str(Pubkey.new_unique())
N1 = (1 << 2047) + 12345          # the two keys "GitHub publishes": one a genesis key, one attested and approved
N2 = (1 << 2047) + 67891


def squads_multisig(create_key: Pubkey, time_lock: int, *, config_authority: Pubkey | None = None, threshold: int = 2, members: int = 3,
                    rent_collector: Pubkey | None = None) -> bytes:
    """A Multisig account as the Squads v4 program lays it out (see the test of the real program's bytes below)."""
    out = mc.MULTISIG + bytes(create_key) + bytes(config_authority or Pubkey.default()) + threshold.to_bytes(2, "little")
    out += time_lock.to_bytes(4, "little") + (5).to_bytes(8, "little") + (1).to_bytes(8, "little")
    out += (b"\x01" + bytes(rent_collector)) if rent_collector else b"\x00"
    out += bytes([255]) + members.to_bytes(4, "little") + b"".join(bytes(Pubkey.new_unique()) + b"\x07" for _ in range(members))
    return out + (bytes(32) if rent_collector is None else b"")


def addresses(create_key: Pubkey) -> tuple[str, str]:
    ms = mc.multisig_address(create_key, Pubkey.from_string(SQUADS))
    return str(ms), str(mc.vault_address(ms, Pubkey.from_string(SQUADS)))


UPGRADE_KEY, GUARDIAN_KEY = Pubkey.new_unique(), Pubkey.new_unique()
IDS = {"knos_oidc": str(Pubkey.new_unique()), "knos_pay": str(Pubkey.new_unique()), "rotate_sha": "ab" * 20, "claim_sha": "cd" * 20,
       "squads_program": SQUADS}
IDS["upgrade_multisig"], IDS["upgrade_authority"] = addresses(UPGRADE_KEY)
IDS["knos_meter"], IDS["knos_passkey"] = str(Pubkey.new_unique()), str(Pubkey.new_unique())       # the programs 0.3.13 adds
IDS["guardian_multisig"], IDS["guardian"] = addresses(GUARDIAN_KEY)


def jwk(n: int, kid: str) -> dict:
    b = n.to_bytes(256, "big")
    return {"kty": "RSA", "alg": "RS256", "use": "sig", "kid": kid, "e": "AQAB",
            "n": base64.urlsafe_b64encode(b).rstrip(b"=").decode()}


def elf(name: str, *, rotate: str = IDS["rotate_sha"], claim: str = IDS["claim_sha"], guardian: str | None = None) -> bytes:
    body = b"\x7fELF" + name.encode() + b"code" * 40 + mc.SECURITY_TXT + b"name: knos" + bytes(Pubkey.from_string(guardian or IDS["guardian"]))
    body += rotate.encode() if name == "knos_oidc" else claim.encode()
    return body + b"\x00" * 64


def key_account(*, state: int = 1, flags: int = oidc.GENESIS | oidc.APPROVED, active_at: int = NOW - 86_400, expires_at: int = NOW + 29 * 86_400) -> bytes:
    head = bytes([state, oidc.GITHUB, 64, 255]) + bytes(4) + active_at.to_bytes(8, "little", signed=True) + expires_at.to_bytes(8, "little", signed=True)
    return head + bytes([flags]) + bytes(15) + bytes(8 * 64)


KEYS = {N1: key_account(), N2: key_account(flags=oidc.APPROVED)}
REVIEW = object()   # stands for "a review of exactly the bytes on chain"


def world(*, authority: str | None = IDS["upgrade_authority"], elfs=None, verified=None, upgrade=None, guardian=None, keys=None, commit=True,
          published=(N1, N2), checks=(True, "run 7: every job passed"), review=REVIEW, elsewhere=None, owner: str = SQUADS,
          refunded=(2, 31), new: str | None = IDS["upgrade_authority"]):
    """`new`: the upgrade authority of knos_meter and knos_passkey, deployed; None: neither is deployed yet."""
    elfs = elfs or {n: elf(n) for n in mc.PROGRAMS}
    accts = {}
    for name in mc.NEW_PROGRAMS if new else ():
        pd = mc.programdata_address(IDS[name])
        accts[IDS[name]] = (str(mc.LOADER), (2).to_bytes(4, "little") + bytes(pd), True)
        accts[str(pd)] = (str(mc.LOADER), (3).to_bytes(4, "little") + bytes(8) + b"\x01" + bytes(Pubkey.from_string(new)) + b"\x7fELF")
    for name in mc.PROGRAMS:
        pd = Pubkey.find_program_address([bytes(Pubkey.from_string(IDS[name]))], mc.LOADER)[0]
        head = (3).to_bytes(4, "little") + bytes(8) + (b"\x01" + bytes(Pubkey.from_string(authority)) if authority else b"\x00" + bytes(32))
        accts[str(pd)] = (str(mc.LOADER), head + elfs[name])
    accts[IDS["upgrade_multisig"]] = (owner, upgrade if upgrade is not None else squads_multisig(UPGRADE_KEY, 172_800))
    accts[IDS["guardian_multisig"]] = (owner, guardian if guardian is not None else squads_multisig(GUARDIAN_KEY, 0))
    for n, data in (KEYS if keys is None else keys).items():
        accts[str(oidc.key_pda(oidc.GITHUB, n, Pubkey.from_string(IDS["knos_oidc"])))] = (IDS["knos_oidc"], data)

    def get(url: str):
        if "api.github.com" in url:
            return {"sha": url.rsplit("/", 1)[1]} if commit else None
        return {"keys": [jwk(n, f"kid{i}-0000") for i, n in enumerate(published)]} if "githubusercontent" in url else {"keys": []}

    if review is REVIEW:
        review = ({"reviewer": "Example Review Ltd", "date": "2026-11-20", "report": "https://example.com/knos.pdf",
                   "programs": {n: mc.elf_hash(elfs[n]) for n in mc.PROGRAMS}}, "docs/review.json")
    v = verified if verified is not None else {n: {"executable_hash": mc.elf_hash(elfs[n]), "source": "test"} for n in mc.PROGRAMS}
    return mc.Fetch(account=accts.get, verified=v.get, program_checks=lambda: checks, get=get, review=lambda: review, now=lambda: NOW,
                    elsewhere=elsewhere or (lambda addr: {"testnet": False, "mainnet-beta": False}),
                    refunded=(lambda program: refunded) if refunded is not None else None, cluster=lambda: "devnet")


def results(fetch, env=None) -> dict[str, bool]:
    return {name: ok for name, ok, _ in mc.run(fetch, ids=IDS, env=env or {})}


def evidence(fetch) -> dict[str, tuple[bool, str]]:
    return {name: (ok, said) for name, ok, said in mc.run(fetch, ids=IDS, env={})}


KEYS_GATE = "every key GitHub publishes today verifies on chain"
REVIEW_GATE = "outside review recorded, of the bytes on chain"
VAULT_GATE = "knos_pay: upgradeable only through the pinned vault"
NEW_GATE = "knos_meter, knos_passkey: deployed, executable, upgradeable only through the pinned vault"


def test_the_programs_this_release_adds_are_not_deployed_yet_without_failing_and_held_to_the_vault_once_they_are(capsys):
    # before the release run deploys them: said, not checked, and no failure
    fetch = world(new=None)
    ok, said = evidence(fetch)[NEW_GATE]
    assert ok is None and said == "; ".join(f"{n} {IDS[n]}: not deployed yet (the release run deploys it)" for n in mc.NEW_PROGRAMS)
    assert [ok for ok in results(fetch).values()].count(None) == 1 and False not in results(fetch).values()
    # deployed into anyone else's hands: a failure, named
    other = str(Pubkey.new_unique())
    ok, said = evidence(world(new=other))[NEW_GATE]
    assert ok is False and f"upgrade authority {other}, not the upgrade vault {IDS['upgrade_authority']}" in said
    # the same in `knos status`: a line that passes while nothing is there, and fails for what is there in the wrong hands
    got = checks(status_world(new=None))["new programs"]
    assert got.ok and got.evidence.count("not deployed yet (the release run deploys it)") == 2 and got.todo == ""
    got = checks(status_world(new=other))["new programs"]
    assert not got.ok and "not the upgrade vault" in got.evidence and "scripts/deploy_v2.sh" in got.todo
    one = status_world()
    base = one.account
    one.account = lambda addr: (base(addr)[0], base(addr)[1], False) if addr == IDS["knos_meter"] else base(addr)
    got = checks(one)["new programs"]
    assert not got.ok and f"knos_meter {IDS['knos_meter']}: not executable" in got.evidence and "knos_passkey" in got.evidence


def test_all_gates_pass_and_exit_zero():
    got = evidence(world())
    assert all(ok for ok, _ in got.values()), got
    assert len(got) == 17 and "mainnet: locked (by design)" in got
    assert got[NEW_GATE][1] == "; ".join(f"{n} {IDS[n]}: deployed, executable, upgrade authority {IDS['upgrade_authority']}, the upgrade vault" for n in mc.NEW_PROGRAMS)
    assert got[KEYS_GATE][1] == "2 keys published; kid0-000: genesis, expires 2026-10-20; kid1-000: approved, expires 2026-10-20"
    assert got["upgrade multisig: time lock is 172800 s (48 hours), or the planned 691200 s (8 days)"][1] == f"{IDS['upgrade_multisig']}: time lock 172800 s, 2 of 3 members, config authority none"
    assert got[VAULT_GATE][1] == f"{IDS['knos_pay']}: upgrade authority {IDS['upgrade_authority']}, the pinned vault"


def test_each_gate_fails_on_its_own():
    one_key = str(Pubkey.new_unique())
    cases = {
        "knos_pay: on-chain bytes are this repository's verified build": world(verified={"knos_oidc": {"executable_hash": mc.elf_hash(elf("knos_oidc"))}, "knos_pay": {"executable_hash": "0" * 64}}),
        "upgrade multisig: time lock is 172800 s (48 hours), or the planned 691200 s (8 days)": world(upgrade=squads_multisig(UPGRADE_KEY, 86_400)),
        "upgrade multisig: no config authority": world(upgrade=squads_multisig(UPGRADE_KEY, 172_800, config_authority=Pubkey.from_string(one_key))),
        "guardian: the vault both programs name is the pinned multisig's, which has no config authority": world(guardian=squads_multisig(GUARDIAN_KEY, 0, config_authority=Pubkey.from_string(one_key))),
        "rotate and claim workflow pins are in the programs and on GitHub": world(commit=False),
        KEYS_GATE: world(keys={N1: KEYS[N1]}),
        "program ids are in use on no other cluster": world(elsewhere=lambda addr: {"testnet": False, "mainnet-beta": addr == IDS["knos_pay"]}),
        "program checks pass (Wycheproof, differential, property tests, fuzz, cargo-audit)": world(checks=(False, "fuzz: failure")),
        REVIEW_GATE: world(review=(None, "no docs/review.json: no outside review has been recorded")),
    }
    for gate, fetch in cases.items():
        got = results(fetch)
        assert got[gate] is False, gate
        assert [g for g, ok in got.items() if not ok] == [gate], (gate, got)


def test_only_the_pinned_vault_may_hold_the_upgrade_authority():
    """A single key as upgrade authority fails whoever holds it, Knos's fee vault included. No authority at all is the
    end state (after the review the programs are made immutable) and passes."""
    for holder in (str(Pubkey.new_unique()), "4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo", IDS["upgrade_multisig"]):
        ok, said = evidence(world(authority=holder))[VAULT_GATE]
        assert ok is False and said == f"{IDS['knos_pay']}: upgrade authority {holder}, not the pinned vault {IDS['upgrade_authority']}"
    assert evidence(world(authority=None))[VAULT_GATE] == (True, f"{IDS['knos_pay']}: no upgrade authority (made immutable)")


def test_the_multisig_gates_read_the_account_the_squads_program_owns_at_the_pinned_address():
    lock, auth, vault = "upgrade multisig: time lock is 172800 s (48 hours), or the planned 691200 s (8 days)", "upgrade multisig: no config authority", "upgrade multisig: the pinned vault is its vault"
    for time_lock in (0, 172_799, 172_801, 7_776_000):
        got = results(world(upgrade=squads_multisig(UPGRADE_KEY, time_lock)))
        assert (got[lock], got[auth], got[vault]) == (False, True, True), time_lock
    # a rent collector moves the members along; the time lock is where it was
    assert all(results(world(upgrade=squads_multisig(UPGRADE_KEY, 172_800, rent_collector=Pubkey.new_unique()))).values())
    # the planned time lock of 8 days (scripts/timelock_plan.py; docs/GOVERNANCE.md, section 2), once its configuration
    # transaction has executed, is what the design fixes too: no gate fails on it
    assert mc.PLANNED_TIME_LOCK == 691_200 and mc.TIME_LOCKS == (172_800, 691_200)
    assert all(results(world(upgrade=squads_multisig(UPGRADE_KEY, mc.PLANNED_TIME_LOCK))).values())
    # another program's account, an account that is not a multisig, a multisig of another create key at this address, nothing
    other_owner = evidence(world(owner=str(Pubkey.new_unique())))
    assert not other_owner[lock][0] and "not by the Squads program" in other_owner[lock][1]
    for wrong in (b"\x00" * 231, squads_multisig(Pubkey.new_unique(), 172_800), squads_multisig(UPGRADE_KEY, 172_800)[:99]):
        got = evidence(world(upgrade=wrong))
        assert not (got[lock][0] or got[auth][0] or got[vault][0]) and got[lock][1].endswith("not a Squads multisig account")
    fetch = world()
    account = fetch.account
    fetch.account = lambda addr: None if addr == IDS["upgrade_multisig"] else account(addr)
    assert evidence(fetch)[lock] == (False, f"{IDS['upgrade_multisig']}: no such account")


# The Multisig accounts the Squads v4 program itself wrote when scripts/governance.mjs created the two multisigs from
# the real create keys on a fork of mainnet-beta (the real program, 2 Oct 2026; three throwaway members): the one copy of
# them is in tests/fixtures/governance_v2.json, which scripts/governance_fixture.py writes and the Node tests read too.
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "governance_v2.json").read_text(encoding="utf-8"))
REAL = {name: account["data"] for name, account in FIXTURE["squads_accounts"].items()}


def test_the_real_squads_programs_bytes_are_read_right_and_give_the_pinned_addresses():
    squads = Pubkey.from_string(oidc.IDS["squads_program"])
    members = None
    for name, time_lock, vault in (("upgrade", 172_800, "upgrade_authority"), ("guardian", 0, "guardian")):
        ms = mc.read_multisig(bytes.fromhex(REAL[name]))
        assert (ms.time_lock, ms.threshold, len(ms.members), ms.config_authority) == (time_lock, 2, 3, None)
        address = mc.multisig_address(ms.create_key, squads)
        assert str(address) == oidc.IDS[f"{name}_multisig"] and str(mc.vault_address(address, squads)) == oidc.IDS[vault]
        assert members in (None, ms.members)
        members = ms.members
    assert [str(m) for m in members] == ["8fjcaqHZ6RLPZfz9SmgA2QaUgmfLtEYnypKVWTK5VQKH", "9bhAo5aP3FMe4kcENkrKtCKcth189xK4A4uiB1QMZBC5",
                                         "DnfkiqUyTAKvBwFr8ZR7iV9FKL2QuG857NmfLf5Tb2iE"]
    # the layout the synthetic accounts above are built to is that one
    real = bytes.fromhex(REAL["upgrade"])
    assert len(squads_multisig(Pubkey.from_bytes(real[8:40]), 172_800)) == len(real) and real[:8] == mc.MULTISIG
    assert squads_multisig(Pubkey.from_bytes(real[8:40]), 172_800)[:78] == real[:78]


def test_a_key_must_be_registered_ready_trusted_active_unexpired_and_not_revoked():
    late = NOW + 3600
    cases = {
        "not registered": None,
        "registered, KeyParams not sent": key_account(state=0),
        "revoked": key_account(flags=oidc.GENESIS | oidc.APPROVED | oidc.REVOKED),
        "attested, not approved by the guardian": key_account(flags=0),
        "not active before 2026-09-21": key_account(flags=oidc.APPROVED, active_at=late),
        "genesis, expired 2026-09-21": key_account(expires_at=NOW),
    }
    for said, data in cases.items():
        keys = {N1: KEYS[N1], **({N2: data} if data is not None else {})}
        ok, got = evidence(world(keys=keys))[KEYS_GATE]
        assert ok is False and got == f"2 keys published; kid0-000: genesis, expires 2026-10-20; kid1-000: {said}", said
    # an account at the key's address that the verifier does not own is no key
    fetch = world()
    account = fetch.account
    fetch.account = lambda addr: (str(Pubkey.new_unique()), got[1]) if (got := account(addr)) and got[0] == IDS["knos_oidc"] else got
    assert evidence(fetch)[KEYS_GATE] == (False, "2 keys published; kid0-000: not registered; kid1-000: not registered")
    # GitHub's key set cannot be read, or is empty: the gate fails, it does not pass on nothing
    assert results(world(published=()))[KEYS_GATE] is False


def test_a_program_id_seen_on_another_cluster_or_a_cluster_that_cannot_be_read_fails():
    gate = "program ids are in use on no other cluster"
    ok, said = evidence(world())[gate]
    assert ok and said == "; ".join(f"{IDS[n]}: not on testnet, not on mainnet-beta" for n in mc.PROGRAMS)
    ok, said = evidence(world(elsewhere=lambda addr: {"testnet": None, "mainnet-beta": True}))[gate]
    assert not ok and "unreadable on testnet, IN USE on mainnet-beta" in said
    assert results(world(elsewhere=lambda addr: {"testnet": None, "mainnet-beta": False}))[gate] is False
    assert evidence(world(elsewhere=lambda addr: {}))[gate] == (False, "; ".join(f"{IDS[n]}: no other cluster was asked" for n in mc.PROGRAMS))


def test_the_review_must_be_of_the_bytes_on_chain_and_say_who_and_where():
    hashes = {n: mc.elf_hash(elf(n)) for n in mc.PROGRAMS}
    good = {"reviewer": "Example Review Ltd", "date": "2026-11-20", "report": "https://example.com/knos.pdf", "programs": hashes}
    assert evidence(world(review=(good, "docs/review.json")))[REVIEW_GATE] == (True, "docs/review.json: by Example Review Ltd, 2026-11-20, https://example.com/knos.pdf")
    for bad in ({**good, "programs": {**hashes, "knos_pay": "0" * 64}}, {**good, "programs": {"knos_oidc": hashes["knos_oidc"]}}, {**good, "programs": None},
                {**good, "reviewer": ""}, {**good, "report": "a report exists"}, {}):
        assert evidence(world(review=(bad, "docs/review.json")))[REVIEW_GATE][0] is False, bad
    ok, said = evidence(world(review=(None, "no docs/review.json: no outside review has been recorded")))[REVIEW_GATE]
    assert not ok and said == "no docs/review.json: no outside review has been recorded"
    # a review of an earlier build does not cover what is deployed now
    newer = {n: elf(n) + b"patched" for n in mc.PROGRAMS}
    ok, said = evidence(world(elfs=newer, review=(good, "docs/review.json")))[REVIEW_GATE]
    assert not ok and said.endswith("the hashes it records are not the on-chain programs'")


def test_the_pins_and_the_guardian_must_be_in_the_on_chain_binaries():
    pins, guardian = "rotate and claim workflow pins are in the programs and on GitHub", "guardian: the vault both programs name is the pinned multisig's, which has no config authority"
    for elfs in ({"knos_oidc": elf("knos_oidc", rotate="ef" * 20), "knos_pay": elf("knos_pay")}, {"knos_oidc": elf("knos_oidc"), "knos_pay": elf("knos_pay", claim="ef" * 20)}):
        assert results(world(elfs=elfs, verified={}))[pins] is False
    other = str(Pubkey.new_unique())
    ok, said = evidence(world(elfs={"knos_oidc": elf("knos_oidc"), "knos_pay": elf("knos_pay", guardian=other)}))[guardian]
    assert not ok and said.endswith("named in the on-chain binary of: knos_oidc")


def test_a_compiled_program_names_the_guardian_as_four_immediates_which_a_search_for_32_bytes_in_a_row_would_miss():
    """Measured on the real builds: none holds the pinned guardian as 32 bytes in a row; all load it with four lddw
    instructions. (A fake binary with the 32 bytes in a row, which is what these tests used before, passed a check that
    would have failed on every real deployment.)"""
    fixtures = Path(__file__).parent / "fixtures"
    guardian = Pubkey.from_string(oidc.IDS["guardian"])
    for build in ("knos_oidc_v2_real.so", "knos_oidc_v2_test.so", "knos_pay_v2_nodevnet.so", "knos_pay_v2_test.so"):
        built = (fixtures / build).read_bytes()
        assert bytes(guardian) not in built, build
        assert mc.names_key(built, guardian), build
        assert not mc.names_key(built, Pubkey.from_string(oidc.IDS["upgrade_authority"])), build      # the loader knows the vault, the programs do not
    assert mc.names_key((fixtures / "knos_pay_v2_nodevnet.so").read_bytes(), Pubkey.from_string(oidc.IDS["fee_owner"]))      # knos-pay pays it
    for build in ("knos_oidc_test.so", "knos_pay_nodevnet.so"):      # the first deployment's builds name another guardian
        assert not mc.names_key((fixtures / build).read_bytes(), guardian), build
    raw = bytes(guardian)
    in_a_row = b"\x7fELF" + bytes(50) + raw + bytes(50)
    lddw = b"".join(b"\x18\x01\x00\x00" + raw[i:i + 4] + bytes(4) + raw[i + 4:i + 8] for i in range(0, 32, 8))
    assert mc.names_key(in_a_row, guardian) and mc.names_key(b"\x7fELF" + lddw, guardian)
    assert not mc.names_key(b"\x7fELF" + lddw[:-16], guardian) and not mc.names_key(b"\x7fELF" + bytes(100), guardian)
    other = Pubkey.new_unique()
    assert not mc.names_key(in_a_row, other) and not mc.names_key(b"\x7fELF" + lddw, other)


def test_the_guardian_check_passes_for_the_real_pinned_multisig_and_the_real_compiled_builds():
    """Every input real: the pinned ids, the multisig account the Squads program wrote for the guardian, and the compiled
    builds (the verified build of the same sources differs only in how it is built)."""
    fixtures, ids = Path(__file__).parent / "fixtures", oidc.IDS
    real = {"knos_oidc": (fixtures / "knos_oidc_v2_real.so").read_bytes(), "knos_pay": (fixtures / "knos_pay_v2_nodevnet.so").read_bytes()}

    def account(address):
        return (ids["squads_program"], bytes.fromhex(REAL["guardian"])) if address == ids["guardian_multisig"] else None
    ok, said = mc._guardian(account, ids, real)
    assert ok and said.endswith("named in the on-chain binary of: knos_oidc, knos_pay") and f"vault 0 is {ids['guardian']}" in said, said
    first = {"knos_oidc": (fixtures / "knos_oidc_test.so").read_bytes(), "knos_pay": (fixtures / "knos_pay_nodevnet.so").read_bytes()}
    ok, said = mc._guardian(account, ids, first)
    assert not ok and said.endswith("named in the on-chain binary of: neither program")


def test_unlocking_mainnet_fails_its_gate_and_main_reports(monkeypatch):
    assert results(world(), env={"KNOS_ALLOW_MAINNET": "1"})["mainnet: UNLOCKED (KNOS_ALLOW_MAINNET=1)"] is False
    monkeypatch.setattr(mc.oidc, "IDS", IDS)
    lines: list[str] = []
    assert mc.main(lines.append, fetch=world(review=(None, "no docs/review.json: no outside review has been recorded"))) == 1
    assert lines[-1] == "16/17 gates pass; mainnet stays locked"
    assert "FAIL  outside review recorded, of the bytes on chain  (no docs/review.json: no outside review has been recorded)" in lines
    out: list[str] = []
    assert mc.main(out.append, fetch=world(), as_json=True) == 0
    assert json.loads(out[0])["passed"] == 17


def test_nothing_deployed_fails_plainly():
    f = mc.Fetch(account=lambda a: None, verified=lambda n: None, program_checks=lambda: (False, "none"), get=lambda u: None,
                 review=lambda: (None, "no docs/review.json"), now=lambda: NOW, elsewhere=lambda a: {"testnet": False, "mainnet-beta": False})
    got = {n: (ok, d) for n, ok, d in mc.run(f, ids=IDS, env={})}
    assert got["knos_oidc: upgradeable only through the pinned vault"] == (False, f"{IDS['knos_oidc']}: not deployed")
    assert got["upgrade multisig: time lock is 172800 s (48 hours), or the planned 691200 s (8 days)"] == (False, f"{IDS['upgrade_multisig']}: no such account")
    assert got[KEYS_GATE] == (False, f"{oidc.JWKS[oidc.GITHUB]} unreadable")
    assert sorted(n for n, (ok, _) in got.items() if ok) == ["mainnet: locked (by design)", "program ids are in use on no other cluster"]


def test_the_gates_are_about_the_second_deployments_pinned_addresses():
    """Run with no ids, the check reads programs-v2's: its two programs, its two multisigs and their vaults."""
    asked: list[str] = []
    f = mc.Fetch(account=lambda a: asked.append(a), verified=lambda n: None, program_checks=lambda: (False, "none"), get=lambda u: None,
                 review=lambda: (None, "none"), now=lambda: NOW, elsewhere=lambda a: {})
    mc.run(f, env={})
    programdata = [str(Pubkey.find_program_address([bytes(Pubkey.from_string(oidc.IDS[n]))], mc.LOADER)[0]) for n in mc.PROGRAMS]
    assert asked == [*programdata, *(oidc.IDS[n] for n in mc.NEW_PROGRAMS), oidc.IDS["upgrade_multisig"], oidc.IDS["guardian_multisig"]]
    assert (oidc.IDS["knos_oidc"], oidc.IDS["knos_pay"]) == ("FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W", "5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k")


# ---- the real fetchers, as far as they go without a network ---------------------------------------------------------

def test_the_review_file_is_read_from_the_repository_and_a_broken_one_is_no_review(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    here_only = mc._review()
    assert here_only[0] is None      # this repository records no review yet: the gate fails until one exists
    assert here_only[1] == "no docs/review.json: no outside review has been recorded"
    (tmp_path / "docs").mkdir()
    for text in ("not json", "[1, 2]"):
        (tmp_path / "docs" / "review.json").write_text(text, encoding="utf-8")
        doc, where = mc._review()
        assert doc is None and where.startswith(str(tmp_path / "docs" / "review.json")) and "JSON" in where
    (tmp_path / "docs" / "review.json").write_text('{"reviewer": "x"}', encoding="utf-8")
    assert mc._review() == ({"reviewer": "x"}, str(tmp_path / "docs" / "review.json"))


@pytest.mark.parametrize(("genesis", "expected"), [
    ("EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG", "devnet"),
    ("4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY", "testnet"),
    ("5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d", "mainnet-beta"),
    ("unrecognized genesis", "unknown"),
])
def test_rpc_cluster_is_named_from_its_genesis_hash_without_disclosing_the_rpc_url(monkeypatch, genesis, expected):
    endpoint = "https://rpc.example/secret-token"
    asked = []

    def call(url, method, params):
        asked.append((url, method, params))
        return genesis

    monkeypatch.setattr(mc.chain, "call", call)
    assert mc._cluster(endpoint) == expected
    assert asked == [(endpoint, "getGenesisHash", [])]


def test_a_verified_build_on_this_machine_is_hashed_as_solana_verify_does(tmp_path):
    (tmp_path / "knos_pay.so").write_bytes(b"\x7fELFprogram" + bytes(4096))
    got = mc._verified({"KNOS_VERIFIED_DIR": str(tmp_path)})
    assert got("knos_pay") == {"executable_hash": mc.elf_hash(b"\x7fELFprogram"), "source": f"{tmp_path}/knos_pay.so"}
    assert got("knos_oidc") is None                                   # no such file: no verified build, the gate fails


@pytest.mark.parametrize("here, others", [("EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG", ["testnet", "mainnet-beta"]),
                                          ("5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d", ["devnet", "testnet"]),
                                          ("a local validator's genesis", ["devnet", "testnet", "mainnet-beta"])])
def test_every_public_cluster_but_the_one_checked_is_asked(monkeypatch, here, others):
    asked: list[str] = []

    def call(url, method, params, timeout=10.0):
        if method == "getGenesisHash":
            return here
        asked.append(url)
        if "testnet" in url:
            raise OSError("unreachable")
        return {"value": {"owner": "x", "data": ["", "base64"]} if "mainnet" in url else None}
    monkeypatch.setattr(mc.chain, "call", call)
    got = mc._elsewhere("https://rpc.example")("SomeProgram1111111111111111111111111111111")
    assert list(got) == others and asked == [mc.PUBLIC[name] for name in others]
    assert got == {name: {"devnet": False, "testnet": None, "mainnet-beta": True}[name] for name in others}


# ---- the live claim "48" (scripts/claims_check.py, LIVE["upgrade_delay"]) --------------------------------------------

def _claims_check():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("claims_check", Path(__file__).resolve().parents[1] / "scripts" / "claims_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_48_hours_hold_only_when_the_time_locked_multisigs_vault_is_the_upgrade_authority(monkeypatch):
    """The sentence the pitch says is true on chain only when the multisig's time lock is 172800 seconds, no single key
    can change it, and its vault (not a deploy key) is what can upgrade both programs."""
    cc, ids = _claims_check(), oidc.IDS

    def chain_with(multisig: bytes | None, authority: str | None, owner: str = ids["squads_program"]):
        accts = {ids["upgrade_multisig"]: (owner, multisig)} if multisig is not None else {}
        for name in mc.PROGRAMS:
            pd = Pubkey.find_program_address([bytes(Pubkey.from_string(ids[name]))], mc.LOADER)[0]
            accts[str(pd)] = (str(mc.LOADER), (3).to_bytes(4, "little") + bytes(8) + (b"\x01" + bytes(Pubkey.from_string(authority)) if authority else bytes(33)) + b"\x7fELF")

        def rpc(method, params):
            assert method == "getAccountInfo"
            got = accts.get(params[0])
            return {"value": {"owner": got[0], "data": [base64.b64encode(got[1]).decode(), "base64"]} if got else None}
        monkeypatch.setattr(cc, "_rpc", rpc)
        return cc.LIVE["upgrade_delay"]()

    real, vault = bytes.fromhex(REAL["upgrade"]), ids["upgrade_authority"]
    ok, said = chain_with(real, vault)
    assert ok and said == (f"upgrade multisig {ids['upgrade_multisig']}: time lock 172800 s, 2 of 3 members, config authority none; "
                           f"knos_oidc: upgrade authority {vault}, its vault; knos_pay: upgrade authority {vault}, its vault")
    deployer = str(Pubkey.new_unique())
    ok, said = chain_with(real, deployer)                            # deployed, the hand-over not done yet
    assert not ok and said.endswith(f"knos_pay: upgrade authority {deployer}, NOT its vault")
    assert chain_with(real, None)[0] is False                        # no authority: there is no upgrade to wait 48 hours for
    no_lock = real[:74] + (0).to_bytes(4, "little") + real[78:]
    one_key = real[:40] + bytes(Pubkey.new_unique()) + real[72:]
    for multisig in (no_lock, one_key, bytes.fromhex(REAL["guardian"]), None):
        assert chain_with(multisig, vault)[0] is False
    assert chain_with(real, vault, owner=str(Pubkey.new_unique()))[0] is False
    # every fact in docs/facts.json that is checked live has its check
    facts = json.loads((cc.ROOT / "docs" / "facts.json").read_text(encoding="utf-8"))["facts"]
    assert {f["live"] for f in facts if "live" in f} <= set(cc.LIVE)


# ---- knos status ------------------------------------------------------------------------------------------------------

FIRST = {"knos_oidc": str(Pubkey.new_unique()), "knos_pay": str(Pubkey.new_unique())}   # the first deployment's programs


def proposal_account(index: int, status: str, at: int = 0, approved: int = 2) -> bytes:
    """A Squads v4 Proposal of the upgrade multisig, as the program lays it out."""
    tag = mc.STATUSES.index(status)
    out = mc.PROPOSAL + bytes(Pubkey.from_string(IDS["upgrade_multisig"])) + index.to_bytes(8, "little") + bytes([tag])
    out += at.to_bytes(8, "little", signed=True) if status != "Executing" else b""
    out += bytes([254]) + approved.to_bytes(4, "little") + b"".join(bytes(Pubkey.new_unique()) for _ in range(approved))
    return out + bytes(8)                                           # rejected and cancelled: none


PROG, BUF = str(Pubkey.new_unique()), str(Pubkey.new_unique())


def vault_transaction_account(program: str = PROG, buffer: str = BUF, *, loader: bool = True, extra_first: bool = False) -> bytes:
    """A Squads v4 VaultTransaction that carries the upgradeable loader's Upgrade (what `upgrade propose` creates)."""
    vault = Pubkey.from_string(IDS["upgrade_authority"])
    keys = [mc.programdata_address(program), Pubkey.from_string(program), Pubkey.from_string(buffer), Pubkey.new_unique(), Pubkey.new_unique(), Pubkey.new_unique(), vault,
            mc.LOADER if loader else Pubkey.new_unique()]
    out = mc.VAULT_TX + bytes(32) + bytes(vault) + (6).to_bytes(8, "little") + bytes([255, 0, 254]) + (1).to_bytes(4, "little") + b"\x07"      # one ephemeral signer bump
    out += bytes([1, 1, 6]) + len(keys).to_bytes(4, "little") + b"".join(bytes(k) for k in keys)
    noop = (b"\x00\x00\x00\x00", [])                                                            # an instruction before the upgrade's
    instructions = ([(0, noop[1], noop[0])] if extra_first else []) + [(7, list(range(7)), (3).to_bytes(4, "little"))]
    out += len(instructions).to_bytes(4, "little")
    for program_index, accounts, data in instructions:
        out += bytes([program_index]) + len(accounts).to_bytes(4, "little") + bytes(accounts) + len(data).to_bytes(4, "little") + data
    return out + (0).to_bytes(4, "little")                                                       # no address table lookups


def status_world(*, programs: bool = True, executable: bool = True, paused_until: int = 0, first_authority: str | None = None, first_deployed: bool = True,
                 flags: bool = True, pay_authority: str | None = "same", proposals: dict | None = None, **kw):
    """world() plus what `knos status` reads besides: the two program accounts, the pause account, the first deployment.
    `pay_authority`: another upgrade authority (or None: none) for knos_pay alone."""
    fetch = world(**kw)
    base, extra = fetch.account, {}
    if pay_authority != "same":
        pd = str(mc.programdata_address(IDS["knos_pay"]))
        head = (3).to_bytes(4, "little") + bytes(8) + (b"\x01" + bytes(Pubkey.from_string(pay_authority)) if pay_authority else b"\x00" + bytes(32))
        extra[pd] = (str(mc.LOADER), head + base(pd)[1][mc.PROGRAMDATA_HEADER:])
    for name in mc.PROGRAMS:
        if programs:
            program = (str(mc.LOADER), (2).to_bytes(4, "little") + bytes(mc.programdata_address(IDS[name])))
            extra[IDS[name]] = (*program, executable) if flags else program
        if first_deployed:
            head = (3).to_bytes(4, "little") + bytes(8) + (b"\x01" + bytes(Pubkey.from_string(first_authority)) if first_authority else b"\x00" + bytes(32))
            extra[str(mc.programdata_address(FIRST[name]))] = (str(mc.LOADER), head + b"\x7fELF")
    squads, multisig = Pubkey.from_string(SQUADS), Pubkey.from_string(IDS["upgrade_multisig"])
    for index, got in (proposals or {}).items():       # {index: the proposal's bytes} or {index: (its bytes, the transaction's bytes or None)}
        data, tx = got if isinstance(got, tuple) else (got, vault_transaction_account())
        extra[str(mc.proposal_address(multisig, index, squads))] = (SQUADS, data)
        if tx is not None:
            extra[str(mc.transaction_address(multisig, index, squads))] = (SQUADS, tx)
    if paused_until:
        extra[str(pay.pause_pda(Pubkey.from_string(IDS["knos_pay"])))] = (IDS["knos_pay"], paused_until.to_bytes(8, "little", signed=True))
    fetch.account = lambda addr: extra.get(addr) or base(addr)
    return fetch


def checks(fetch) -> dict[str, mc.Check]:
    """Each check of `knos status` by its topic (the words before the colon)."""
    return {c.name.split(":")[0]: c for c in mc.status(fetch, ids=IDS, first=FIRST)}


TOPICS = ["program ids", "upgrade authority", "new programs", "upgrade delay", "upgrade multisig", "upgrade proposal", "guardian", "GitHub's keys", "key refresh",
          "new funding", "first deployment", "refund"]


def failing(fetch) -> list[str]:
    return [topic for topic, c in checks(fetch).items() if not c.ok]


def test_status_has_twelve_checks_and_all_pass_for_a_deployment_that_is_running_as_designed():
    got = checks(status_world())
    assert list(got) == TOPICS and all(c.ok and c.todo == "" for c in got.values()), got
    assert got["program ids"].evidence == f"knos_oidc {IDS['knos_oidc']}: deployed, executable; knos_pay {IDS['knos_pay']}: deployed, executable"
    assert got["upgrade authority"].evidence.count("the upgrade vault") == 2
    assert got["new programs"].evidence == "; ".join(f"{n} {IDS[n]}: deployed, executable, upgrade authority {IDS['upgrade_authority']}, the upgrade vault"
                                                    for n in mc.NEW_PROGRAMS)
    assert got["upgrade delay"].evidence == (f"{IDS['upgrade_multisig']}: time lock 172800 s, 2 of 3 members, config authority none; vault 0 is {IDS['upgrade_authority']}")
    assert got["GitHub's keys"].evidence == "2 keys published; kid0-000: genesis, expires 2026-10-20; kid1-000: approved, expires 2026-10-20"
    assert got["new funding"].evidence == "not paused"
    assert got["first deployment"].evidence == "; ".join(f"{n} {FIRST[n]}: no upgrade authority (immutable)" for n in mc.PROGRAMS)
    assert got["upgrade proposal"].evidence == f"no proposal is pending on {IDS['upgrade_multisig']} (5 made so far; the newest 10 were read)"
    assert got["key refresh"].evidence == "the last key refresh was 2026-09-20 14:13 UTC, 1 day 0 h ago"
    assert got["refund"].evidence == f"knos_pay {IDS['knos_pay']}: 2 refunds in its newest 31 transactions"


def test_each_status_check_fails_on_its_own_and_says_what_to_do():
    other = Pubkey.new_unique()
    cases = {
        "program ids": (status_world(programs=False), "scripts/deploy_v2.sh"),
        "upgrade authority": (status_world(authority=str(other)), "set-upgrade-authority"),
        "new programs": (status_world(new=str(other)), "set-upgrade-authority"),
        "upgrade delay": (status_world(upgrade=squads_multisig(UPGRADE_KEY, 86_400)), "node scripts/governance.mjs create"),
        "upgrade multisig": (status_world(upgrade=squads_multisig(UPGRADE_KEY, 172_800, config_authority=other)), "node scripts/governance.mjs create"),
        "upgrade proposal": (status_world(proposals={5: proposal_account(5, "Approved", NOW - 3600)}), "governance.mjs cancel upgrade 5"),
        "guardian": (status_world(guardian=squads_multisig(GUARDIAN_KEY, 0, config_authority=other)), "pin it"),
        "GitHub's keys": (status_world(keys={N1: KEYS[N1]}), "the rotate workflow"),
        "key refresh": (status_world(keys={N1: key_account(expires_at=NOW + 20 * 86_400), N2: key_account(flags=oidc.APPROVED, expires_at=NOW + 12 * 86_400)}), "Refresh"),
        "new funding": (status_world(paused_until=NOW + 3600), "guardian pause 0"),
        "first deployment": (status_world(first_authority=str(other)), "--final"),
        "refund": (status_world(refunded=(0, 40)), "--days 1"),
    }
    assert list(cases) == TOPICS
    for topic, (fetch, hint) in cases.items():
        assert failing(fetch) == [topic], topic
        todo = checks(fetch)[topic].todo
        assert hint in todo, (topic, todo)


def test_a_program_that_is_not_there_or_not_executable_or_not_the_loaders_fails_with_what_was_found():
    one = checks(status_world(executable=False))["program ids"]
    assert not one.ok and one.evidence == "; ".join(f"{n} {IDS[n]}: not executable" for n in mc.PROGRAMS)
    # a fetcher that cannot say whether a program is executable (a two-field account) is not failed for that: the loader's
    # program account is executable by construction
    assert checks(status_world(flags=False))["program ids"].ok
    fetch = status_world()
    account = fetch.account
    wrong = {IDS["knos_oidc"]: (str(Pubkey.new_unique()), b"\x02\x00\x00\x00" + bytes(32), True),                 # not the loader's
             IDS["knos_pay"]: (str(mc.LOADER), (2).to_bytes(4, "little") + bytes(Pubkey.new_unique()), True)}      # its bytes are elsewhere
    fetch.account = lambda addr: wrong.get(addr) or account(addr)
    got = checks(fetch)["program ids"]
    assert not got.ok and "not by the upgradeable loader" in got.evidence and "not a program account of the upgradeable loader" in got.evidence
    nothing = mc.Fetch(account=lambda a: None, verified=lambda n: None, program_checks=lambda: (False, ""), get=lambda u: None,
                       review=lambda: (None, ""), now=lambda: NOW, elsewhere=lambda a: {})
    got = checks(nothing)
    # nothing is paused where nothing is deployed, and the programs this release adds are not deployed yet, which is no fault
    assert [t for t, c in got.items() if c.ok] == ["new programs", "new funding"] and got["program ids"].evidence.count("no such account") == 2
    assert got["GitHub's keys"].evidence == f"{oidc.JWKS[oidc.GITHUB]} could not be read"
    assert got["first deployment"].evidence.count("not deployed on this cluster") == 2


def test_the_upgrade_authority_is_the_vault_or_nothing_and_a_program_made_immutable_needs_no_multisig():
    got = checks(status_world(authority=str(Pubkey.new_unique()), first_authority=None))["upgrade authority"]
    assert not got.ok and f"not the upgrade vault {IDS['upgrade_authority']}" in got.evidence
    # the end state after the outside review: no upgrade authority. The upgrade multisig is then not needed, and not checked
    done = checks(status_world(authority=None, upgrade=squads_multisig(UPGRADE_KEY, 0, config_authority=Pubkey.new_unique())))
    assert all(c.ok for c in done.values()), done
    assert done["upgrade authority"].evidence.count("no upgrade authority (made immutable)") == 2
    assert done["upgrade delay"].evidence.endswith("(not needed now: both programs are immutable)")
    # one program still upgradeable by the vault: the multisig counts again
    mixed = checks(status_world(authority=None, pay_authority=IDS["upgrade_authority"], upgrade=squads_multisig(UPGRADE_KEY, 0, config_authority=Pubkey.new_unique())))
    assert [t for t, c in mixed.items() if not c.ok] == ["upgrade delay", "upgrade multisig"] and mixed["upgrade authority"].ok
    assert mixed["upgrade authority"].evidence == f"knos_oidc: no upgrade authority (made immutable); knos_pay: upgrade authority {IDS['upgrade_authority']}, the upgrade vault"


def test_the_time_lock_and_the_config_authority_are_two_lines_and_a_wrong_multisig_fails_both_it_cannot_be_trusted_for():
    got = checks(status_world(upgrade=squads_multisig(UPGRADE_KEY, 172_801)))
    assert (got["upgrade delay"].ok, got["upgrade multisig"].ok) == (False, True)
    got = checks(status_world(upgrade=b"\x00" * 231))
    assert (got["upgrade delay"].ok, got["upgrade multisig"].ok) == (False, False) and got["upgrade delay"].evidence.endswith("not a Squads multisig account")
    got = checks(status_world(owner=str(Pubkey.new_unique())))
    assert not (got["upgrade delay"].ok or got["upgrade multisig"].ok or got["guardian"].ok)


def test_every_github_key_is_judged_and_a_failing_one_is_named_by_its_hash():
    digest = {n: oidc.key_hash(n).hex() for n in (N1, N2)}
    cases = {
        "not registered": (None, "the rotate workflow", "kid1-000: not registered"),
        "attested, not approved by the guardian": (key_account(flags=0), f"node scripts/governance.mjs guardian approve github {digest[N2]}", ""),
        "registered, KeyParams not sent": (key_account(state=0), "KeyParams", ""),
        "revoked": (key_account(flags=oidc.APPROVED | oidc.REVOKED), "revoked", ""),
        "genesis, expired 2026-09-21": (key_account(expires_at=NOW), "Refresh", ""),
    }
    for said, (data, hint, _) in cases.items():
        fetch = status_world(keys={N1: KEYS[N1], **({N2: data} if data is not None else {})})
        got = checks(fetch)["GitHub's keys"]
        assert not got.ok and f"kid1-000 (key hash {digest[N2]}): {said}" in got.evidence and "kid0-000: genesis, expires 2026-10-20" in got.evidence, said
        assert hint in got.todo and got.todo.startswith("kid1-000:"), (said, got.todo)
        assert failing(fetch) == ["GitHub's keys"]
    # a usable key that ends within a week is a failing one: the rotate workflow has to refresh it while there is time
    for expires, ok in ((NOW + 7 * 86_400 + 1, True), (NOW + 7 * 86_400, False), (NOW + 3 * 86_400, False), (NOW + 29 * 86_400, True)):
        got = checks(status_world(keys={N1: KEYS[N1], N2: key_account(flags=oidc.APPROVED, expires_at=expires)}))["GitHub's keys"]
        assert got.ok is ok, expires
        if not ok:
            assert f"kid1-000 (key hash {digest[N2]}): approved, expires" in got.evidence and "send Refresh with its token" in got.todo
    # GitHub's key list cannot be read, or lists nothing: the check does not pass on nothing
    for published in ((), ):
        got = checks(status_world(published=published))["GitHub's keys"]
        assert not got.ok and got.todo.startswith("run it again in a few minutes")


def test_new_funding_is_paused_only_until_the_time_the_pause_account_says():
    got = checks(status_world(paused_until=NOW + 600))["new funding"]
    assert not got.ok and got.evidence == "paused until 2026-09-21 14:23 UTC" and got.todo == "the guardian lifts the pause: node scripts/governance.mjs guardian pause 0"
    ended = checks(status_world(paused_until=NOW - 600))["new funding"]
    assert ended.ok and ended.evidence == "not paused (the last pause ended 2026-09-21 14:03 UTC)"
    assert checks(status_world(paused_until=NOW))["new funding"].ok            # lifted: a pause lasts until, not including, that second


def test_the_first_deployment_must_be_deployed_here_and_have_no_upgrade_authority():
    holder = str(Pubkey.new_unique())
    got = checks(status_world(first_authority=holder))["first deployment"]
    assert not got.ok and got.evidence == "; ".join(f"{n} {FIRST[n]}: upgradeable by {holder}" for n in mc.PROGRAMS)
    got = checks(status_world(first_deployed=False))["first deployment"]
    assert not got.ok and "not deployed on this cluster" in got.evidence and "KNOS_RPC" in got.todo


def test_status_reads_the_second_deployments_pinned_ids_and_the_first_deployments_by_default(monkeypatch):
    from knos.settle import oidc as first
    asked: list[str] = []
    f = mc.Fetch(account=lambda a: asked.append(a), verified=lambda n: None, program_checks=lambda: (False, "none"), get=lambda u: None,
                 review=lambda: (None, "none"), now=lambda: NOW, elsewhere=lambda a: {})
    mc.status(f)
    programdata = lambda ids: [str(mc.programdata_address(ids[n])) for n in mc.PROGRAMS]     # noqa: E731
    assert asked == [*(oidc.IDS[n] for n in mc.PROGRAMS), *programdata(oidc.IDS), *(oidc.IDS[n] for n in mc.NEW_PROGRAMS), oidc.IDS["upgrade_multisig"], oidc.IDS["guardian_multisig"],
                     str(pay.pause_pda()), *programdata(first.IDS)]
    assert first.IDS["knos_oidc"] != oidc.IDS["knos_oidc"] and first.IDS["knos_pay"] != oidc.IDS["knos_pay"]


def test_status_command_prints_every_line_with_what_to_do_and_exits_by_the_result(monkeypatch, capsys):
    from knos import cli
    monkeypatch.setattr(mc.oidc, "IDS", IDS)
    monkeypatch.setattr("knos.settle.oidc.IDS", FIRST)
    fetch = status_world()
    monkeypatch.setattr(mc, "live", lambda env=None: fetch)
    assert cli.main(["status"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split("  ")[1].split(":")[0] for line in lines[:-1]] == TOPICS and all(line.startswith("PASS  ") for line in lines[:-1])
    assert lines[-1] == "12 of 12 checks pass"
    text_checks = [(line.split("  ")[1].split("  (")[0], line.startswith("PASS  ")) for line in lines[:-1]]
    assert cli.main(["status", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["cluster"] == "devnet" and doc["overall"] is True
    assert (doc["passed"], doc["of"]) == (12, 12)
    assert len(doc["checks"]) == 12 and all({"check", "pass", "evidence", "next"} <= set(c) for c in doc["checks"])
    assert [(check["check"], check["pass"]) for check in doc["checks"]] == text_checks
    assert all(c["next"] == "" for c in doc["checks"] if c["pass"])
    fetch = status_world(paused_until=NOW + 600, keys={N1: KEYS[N1]})
    monkeypatch.setattr(mc, "live", lambda env=None: fetch)
    assert cli.main(["status"]) == 1
    text = capsys.readouterr().out
    assert "FAIL  new funding: not paused  (paused until" in text and "      Next: the guardian lifts the pause: node scripts/governance.mjs guardian pause 0" in text
    assert "FAIL  GitHub's keys: " in text and text.splitlines()[-1] == "10 of 12 checks pass; 2 to fix"
    text_checks = [(line.split("  ")[1].split("  (")[0], line.startswith("PASS  ")) for line in text.splitlines()[:-1] if line.startswith(("PASS  ", "FAIL  "))]
    assert cli.main(["status", "--json"]) == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["cluster"] == "devnet" and doc["overall"] is False
    assert (doc["passed"], doc["of"]) == (10, 12) and [c["check"].split(":")[0] for c in doc["checks"] if not c["pass"]] == ["GitHub's keys", "new funding"]
    assert [(check["check"], check["pass"]) for check in doc["checks"]] == text_checks
    assert all(c["next"] == "" for c in doc["checks"] if c["pass"]) and all(c["next"] for c in doc["checks"] if not c["pass"])


# ---- from a pip install: what cannot be checked is said, and is not a failure --------------------------------------------

def _from_pip(**kw):
    """world() with the three gates that need a clone, or gh, unread."""
    skip = {n: {"unchecked": mc.NEEDS_GH} for n in mc.PROGRAMS}
    fetch = world(verified=skip, checks=(None, mc.NEEDS_GH), review=(None, mc.NOT_HERE), **kw)
    return fetch


def test_gates_that_need_a_clone_or_gh_say_so_and_are_not_failures(monkeypatch):
    monkeypatch.setattr(mc.oidc, "IDS", IDS)
    got = {name: (ok, said) for name, ok, said in mc.run(_from_pip(), ids=IDS, env={})}
    skipped = {name for name, (ok, _) in got.items() if ok is None}
    assert skipped == {f"{n}: on-chain bytes are this repository's verified build" for n in mc.PROGRAMS} | {
        "program checks pass (Wycheproof, differential, property tests, fuzz, cargo-audit)", "outside review recorded, of the bytes on chain"}
    assert got["outside review recorded, of the bytes on chain"] == (None, "not checked from here: needs a clone")
    assert all(said.startswith("not checked from here: needs a clone") for name, (ok, said) in got.items() if ok is None)
    assert [name for name, (ok, _) in got.items() if ok is False] == []
    lines: list[str] = []
    assert mc.main(lines.append, fetch=_from_pip()) == 0                    # nothing that could be checked failed
    assert lines[-1] == "13/17 gates pass; 4 not checked from here, which is not a failure (run it in a clone of the repository to check them)"
    assert [line.split("  ")[0] for line in lines[:-1]].count("SKIP") == 4 and "FAIL" not in {line.split("  ")[0] for line in lines[:-1]}
    # a failure among the gates that were checked still ends it
    lines.clear()
    assert mc.main(lines.append, fetch=_from_pip(authority=str(Pubkey.new_unique()))) == 1
    assert lines[-1].endswith("; mainnet stays locked") and "not checked from here" in lines[-1]
    out: list[str] = []
    assert mc.main(out.append, fetch=_from_pip(), as_json=True) == 0
    doc = json.loads(out[0])
    assert (doc["passed"], doc["of"], doc["failed"], doc["not_checked"]) == (13, 17, 0, 4) and [g["pass"] for g in doc["gates"]].count(None) == 4


def test_a_github_that_cannot_be_reached_is_not_a_pin_that_is_not_a_commit():
    def down(url: str):
        raise mc.Unreachable("HTTP 403; set GH_TOKEN to lift its rate limit")
    fetch = world()
    fetch.get = down
    name = "rotate and claim workflow pins are in the programs and on GitHub"
    ok, said = {n: (ok, d) for n, ok, d in mc.run(fetch, ids=IDS, env={})}[name]
    assert ok is None and said.startswith("could not reach GitHub (HTTP 403; set GH_TOKEN to lift its rate limit)") and "is not a commit of" not in said
    # GitHub answering that there is no such commit is the statement about the pin
    ok, said = {n: (ok, d) for n, ok, d in mc.run(world(commit=False), ids=IDS, env={})}[name]
    assert ok is False and "is not a commit of drexthealpha/knos-oidc-rotate" in said
    # a pin that is not in the binary is a failure whether or not GitHub answers
    bad = world(elfs={n: elf(n, rotate="ee" * 20) for n in mc.PROGRAMS})
    bad.get = down
    ok, said = {n: (ok, d) for n, ok, d in mc.run(bad, ids=IDS, env={})}[name]
    assert ok is False and "is not in the on-chain binary of knos_oidc" in said and "could not reach" not in said


def test_the_real_fetchers_tell_a_missing_commit_from_an_unreachable_github(monkeypatch):
    import io
    import urllib.error

    def raising(code):
        def urlopen(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(b""))
        return urlopen
    monkeypatch.setattr(mc.urllib.request, "urlopen", raising(404))
    assert mc._get("https://api.github.com/repos/o/r/commits/abc") is None
    monkeypatch.setattr(mc.urllib.request, "urlopen", raising(403))
    with pytest.raises(mc.Unreachable, match="HTTP 403; set GH_TOKEN to lift its rate limit"):
        mc._get("https://api.github.com/repos/o/r/commits/abc")
    monkeypatch.setattr(mc.urllib.request, "urlopen", raising(500))
    with pytest.raises(mc.Unreachable, match="HTTP Error 500"):
        mc._get("https://api.github.com/repos/o/r/commits/abc")


def test_without_gh_the_real_gates_are_skipped_not_failed(monkeypatch, tmp_path):
    def no_gh(*args):
        raise mc.NeedsClone(mc.NEEDS_GH)
    monkeypatch.setattr(mc, "_gh", no_gh)
    assert mc._program_checks() == (None, mc.NEEDS_GH)
    assert mc._verified({})("knos_pay") == {"unchecked": mc.NEEDS_GH}
    # a build made on this machine needs no gh
    (tmp_path / "knos_pay.so").write_bytes(b"\x7fELFpay\x00\x00")
    assert mc._verified({"KNOS_VERIFIED_DIR": str(tmp_path)})("knos_pay")["executable_hash"] == mc.elf_hash(b"\x7fELFpay")
    # gh is asked about the repository by name, so a clone is not needed for it
    asked = []
    monkeypatch.undo()                  # the real _gh, with subprocess faked
    monkeypatch.setattr(mc.subprocess, "run", lambda argv, **kw: asked.append(argv) or type("P", (), {"returncode": 0, "stdout": "[]"})())
    mc._gh("run", "list")
    assert asked == [["gh", "run", "list", "-R", mc.REPO]]
    # no clone: the review file is not there to be read, and that is said, not judged
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mc, "_clone", lambda: None)
    monkeypatch.setattr(mc, "__file__", str(tmp_path / "src" / "knos" / "mainnet_check.py"))
    assert mc._review() == (None, mc.NOT_HERE)
    monkeypatch.setattr(mc, "_clone", lambda: tmp_path)
    assert mc._review() == (None, "no docs/review.json: no outside review has been recorded")


# ---- knos status: a pending upgrade, the last refresh, a refund ---------------------------------------------------------------

def _upgrade(status: str, at: int = NOW - 3600, approved: int = 2, **tx):
    return checks(status_world(proposals={5: (proposal_account(5, status, at, approved), vault_transaction_account(**tx))}))["upgrade proposal"]


def test_a_pending_upgrade_is_named_with_its_index_its_buffer_and_when_it_can_execute():
    got = _upgrade("Approved", at=NOW - 3600)
    left = 172_800 - 3600
    unread = "; its buffer could not be read, so whether GitHub built it is not known"         # (no buffer account in this world: the gate says so)
    assert not got.ok and got.evidence == (f"proposal 5: an upgrade of program {PROG} from buffer {BUF}; approved by 2 of 2 members needed; "
                                           f"it can be executed from {mc._at(NOW - 3600 + 172_800)} (in {left // 3600} h {left % 3600 // 60} min)" + unread)
    assert got.todo.startswith(f"before it runs, compare the buffer with the verified build: solana program dump {BUF} buffer.so")
    assert "node scripts/governance.mjs cancel upgrade 5" in got.todo and "passes again once it has executed or been cancelled" in got.todo
    # once the delay is over, it says so
    got = _upgrade("Approved", at=NOW - 3 * 86_400)
    assert not got.ok and "its delay is over" in got.evidence and "execute it now" in got.evidence
    # a proposal still being voted on, and one only drafted
    got = _upgrade("Active", approved=1)
    assert not got.ok and got.evidence == f"proposal 5: an upgrade of program {PROG} from buffer {BUF}; 1 of 2 approvals so far; it can be executed 48 hours after the last approval is given" + unread
    got = _upgrade("Draft")
    assert not got.ok and got.evidence.endswith("drafted, not yet put to the members' vote" + unread)
    # the upgrade is found whatever comes before it in the transaction
    assert PROG in _upgrade("Approved", extra_first=True).evidence


def test_a_pending_upgrades_buffer_is_held_against_the_record_of_the_run_that_built_it():
    """upgrade_gate (examples/upgrade_gate) keeps, per program and executable hash, the GitHub run that built those
    bytes. `knos status` reads the buffer of a pending upgrade and says whether such a record exists."""
    from knos.settle.v2 import gate
    built = b"\x7fELF" + bytes(range(200)) + bytes(64)                       # the program in the buffer, with the padding a deploy leaves
    buffer = (str(mc.LOADER), (1).to_bytes(4, "little") + b"\x01" + bytes(32) + built)
    h = gate.executable_hash(built)
    at = gate.record_pda(Pubkey.from_string(PROG), h)
    record = bytearray(gate.RECORD_LEN)
    record[0], record[8:16], record[32:64], record[64:96], record[96:136] = 1, (4242).to_bytes(8, "little"), bytes(Pubkey.from_string(PROG)), h, b"c" * 40

    def said(extra: dict) -> str:
        fetch = status_world(proposals={5: (proposal_account(5, "Approved", NOW - 3600), vault_transaction_account())})
        base = fetch.account
        fetch.account = lambda addr: extra.get(addr) or base(addr)
        return checks(fetch)["upgrade proposal"].evidence
    got = said({BUF: buffer})
    assert got.endswith(f"; the buffer's build {h.hex()} is NOT recorded by upgrade_gate ({at} does not exist): no GitHub run vouches for these bytes. "
                        "Do not approve it until program.yml has recorded this hash, or the members have rebuilt it themselves")
    got = said({BUF: buffer, str(at): (str(gate.GATE_ID), bytes(record))})
    assert got.endswith(f"; the buffer's build {h.hex()} is recorded by upgrade_gate: GitHub's runner built it from commit {'c' * 40} (run 4242, record {at})")
    # a record at that address that another program owns is no record
    assert "is NOT recorded by upgrade_gate" in said({BUF: buffer, str(at): (str(Pubkey.new_unique()), bytes(record))})
    # a change to the multisig itself has no buffer: nothing is said of one
    fetch = status_world(proposals={5: (proposal_account(5, "Approved", NOW - 3600), None)})
    assert "buffer" not in checks(fetch)["upgrade proposal"].evidence


def test_proposals_that_finished_or_are_not_upgrades_or_are_not_readable_are_not_mistaken_for_one():
    for status in ("Executed", "Cancelled", "Rejected", "Executing"):
        assert _upgrade(status).ok, status
    # a change to the multisig itself is pending too, and is called that
    cfg = mc.CONFIG_TX + bytes(100)
    got = checks(status_world(proposals={5: (proposal_account(5, "Active", NOW), cfg)}))["upgrade proposal"]
    assert not got.ok and "a change to the upgrade multisig itself (its members, threshold or delay)" in got.evidence
    other = checks(status_world(proposals={5: (proposal_account(5, "Approved", NOW), vault_transaction_account(loader=False))}))["upgrade proposal"]
    assert not other.ok and "a transaction of the upgrade vault" in other.evidence and "solana program dump" not in other.todo
    # no transaction account (closed) still shows the proposal
    assert not checks(status_world(proposals={5: (proposal_account(5, "Approved", NOW), None)}))["upgrade proposal"].ok
    # a proposal at or below the stale index is void and is not read; the older ones are looked at only as far as LOOK_BACK
    assert checks(status_world(proposals={1: proposal_account(1, "Approved", NOW)}))["upgrade proposal"].ok
    assert checks(status_world(proposals={4: proposal_account(4, "Active", NOW)}))["upgrade proposal"].ok is False
    # an account of another program, or one of another layout, is nobody's proposal
    fetch = status_world(proposals={5: proposal_account(5, "Approved", NOW)})
    account = fetch.account
    fetch.account = lambda addr: (str(Pubkey.new_unique()), account(addr)[1]) if account(addr) and account(addr)[0] == SQUADS and len(account(addr)[1]) < 200 else account(addr)
    assert {c.name.split(":")[0]: c for c in mc.status(fetch, ids=IDS, first=FIRST)}["upgrade proposal"].ok
    for junk in (b"", mc.PROPOSAL, mc.PROPOSAL + bytes(40) + bytes([9]), proposal_account(5, "Approved", NOW)[:-12]):
        assert mc.read_proposal(junk) is None
    assert mc.read_transaction(vault_transaction_account()[:80]) == ("other", None, None) and mc.read_transaction(None) == ("other", None, None)
    assert mc.read_proposal(proposal_account(5, "Executing")).status == "Executing"
    assert mc.read_multisig(squads_multisig(UPGRADE_KEY, 172_800)).transaction_index == 5 and mc.read_multisig(squads_multisig(UPGRADE_KEY, 0)).stale_transaction_index == 1


def test_nothing_can_be_proposed_once_immutable_and_nothing_is_read_when_the_multisig_is_not():
    done = checks(status_world(authority=None, proposals={5: proposal_account(5, "Approved", NOW)}))["upgrade proposal"]
    assert done.ok and done.evidence == "both programs are immutable: nothing can be proposed"
    got = checks(status_world(upgrade=b"\x00" * 231))["upgrade proposal"]
    assert not got.ok and got.evidence.endswith("so its proposals could not be read") and "fix the upgrade multisig first" in got.todo


def test_the_last_key_refresh_is_the_newest_one_among_keys_that_can_be_used():
    day = 86_400
    fresh = key_account(expires_at=NOW + 25 * day)                       # refreshed 5 days ago
    got = checks(status_world(keys={N1: fresh}))["key refresh"]
    assert got.ok and got.evidence == f"the last key refresh was {mc._at(NOW - 5 * day)}, 5 days 0 h ago"
    stale = key_account(expires_at=NOW + 22 * day)                        # 8 days ago
    got = checks(status_world(keys={N1: stale}))["key refresh"]
    assert not got.ok and "8 days 0 h ago" in got.evidence and "send Refresh with its token" in got.todo and "run by hand" in got.todo
    # the newest of the keys counts; a revoked key, or one not ready, does not
    assert checks(status_world(keys={N1: stale, N2: fresh}))["key refresh"].ok
    assert not checks(status_world(keys={N1: stale, N2: key_account(expires_at=NOW + 29 * day, flags=oidc.APPROVED | oidc.REVOKED)}))["key refresh"].ok
    assert not checks(status_world(keys={N1: stale, N2: key_account(expires_at=NOW + 29 * day, state=0)}))["key refresh"].ok
    # exactly 7 days is not under 7
    assert not checks(status_world(keys={N1: key_account(expires_at=NOW + 23 * day)}))["key refresh"].ok and checks(status_world(keys={N1: key_account(expires_at=NOW + 23 * day + 1)}))["key refresh"].ok
    none = checks(status_world(published=()))["key refresh"]
    assert not none.ok and none.evidence == "no key of GitHub's is on chain to read a refresh from"


def test_a_refund_must_have_executed_on_the_deployed_program_and_not_being_able_to_read_is_not_none():
    assert checks(status_world())["refund"].ok
    one = checks(status_world(refunded=(1, 1)))["refund"]
    assert one.ok and one.evidence.endswith("1 refund in its newest 1 transactions")
    none = checks(status_world(refunded=(0, 200)))["refund"]
    assert not none.ok and none.evidence == f"knos_pay {IDS['knos_pay']}: no refund in its newest 200 transactions" and "--days 1" in none.todo
    unread = checks(status_world(refunded=None))["refund"]
    assert not unread.ok and unread.evidence.endswith("the history could not be read here")
    # asked about the second deployment's knos_pay, nothing else
    asked = []
    fetch = status_world()
    fetch.refunded = lambda program: asked.append(program) or (1, 3)
    mc.status(fetch, ids=IDS, first=FIRST)
    assert asked == [IDS["knos_pay"]]


def test_the_refund_reader_counts_what_the_program_itself_logged_in_its_newest_transactions(monkeypatch):
    from knos import chain, records
    program = str(Pubkey.new_unique())
    other = str(Pubkey.new_unique())

    def tx(*lines: str) -> dict:
        return {"blockTime": 1, "meta": {"err": None, "logMessages": list(lines)}, "transaction": {"message": {"accountKeys": ["payer"]}}}
    refund = "Program log: knos2:refunded repo=1 issue=2 amount=3"
    txs = {"s1": tx(f"Program {program} invoke [1]", f"Program {program} success"),
           "s2": tx(f"Program {other} invoke [1]", refund, f"Program {other} success"),       # another program printing the same words
           "s3": tx(f"Program {program} invoke [1]", refund, f"Program {program} success"),
           "s4": tx(f"Program {program} invoke [1]", refund, f"Program {program} success")}
    sigs = [{"signature": s, "err": None} for s in ("s1", "s2", "s3", "s4")] + [{"signature": "bad", "err": {"x": 1}}]
    asked = []

    def call(url, method, params, timeout=30):
        asked.append(method)
        if method == "getSignaturesForAddress":
            return sigs
        if params[0] == "s4":
            raise OSError("throttled")
        return txs[params[0]]
    monkeypatch.setattr(chain, "call", call)
    # one batch holds the first refund (s2 is not the program's; s3 is; s4 could not be read): found 1, read 3
    assert records.count_events("http://rpc", program, "refunded", 200) == (1, 3)
    assert asked.count("getTransaction") == 4 and "bad" not in str(asked)
    assert records.count_events("http://rpc", program, "paid", 200) == (0, 3)
    # nothing readable at all is an error, never "none"
    monkeypatch.setattr(chain, "call", lambda url, method, params, timeout=30: sigs if method == "getSignaturesForAddress" else (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(chain.Refused):
        records.count_events("http://rpc", program, "refunded", 200)
    assert mc._refunded("http://rpc")(program) is None
    # a program with no transactions yet: none found of none read
    monkeypatch.setattr(chain, "call", lambda url, method, params, timeout=30: [])
    assert records.count_events("http://rpc", program, "refunded", 200) == (0, 0)
