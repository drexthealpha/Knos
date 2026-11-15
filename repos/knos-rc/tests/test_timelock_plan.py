"""scripts/timelock_plan.py: the configuration transaction that sets the upgrade multisig's time lock above an order's
notice, planned from the real devnet multisig account (tests/fixtures/governance_v2.json) with proposals built in the
Squads layouts src/knos/mainnet_check.py reads (the builders of tests/test_site_recorded.py). It refuses while a proposal
is open, and `knos exit --before-upgrade` says what the time lock covers. Nothing is sent; no network."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from solders.pubkey import Pubkey

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import timelock_plan as tp  # noqa: E402
from test_site_recorded import BUFFER_PAY, GOVERNANCE, IDS, NOW, SQUADS, proposal_account, vault_transaction_account  # noqa: E402

from knos import exit as kexit  # noqa: E402
from knos import mainnet_check as mc  # noqa: E402
from knos.settle.v2 import pay  # noqa: E402

REAL = bytes.fromhex(GOVERNANCE["squads_accounts"]["upgrade"]["data"])


def world(statuses: dict[int, str], *, time_lock: int | None = None, authority: bytes | None = None) -> dict:
    """The devnet upgrade multisig with proposals 1..n of knos_pay upgrades, each in its status."""
    data = REAL[:78] + max(statuses or {0: ""}).to_bytes(8, "little") + REAL[86:]
    if time_lock is not None:
        data = data[:74] + time_lock.to_bytes(4, "little") + data[78:]
    if authority is not None:
        data = data[:40] + authority + data[72:]
    ms_key, squads = Pubkey.from_string(IDS["upgrade_multisig"]), Pubkey.from_string(SQUADS)
    out = {IDS["upgrade_multisig"]: (SQUADS, data)}
    for i, status in statuses.items():
        out[str(mc.proposal_address(ms_key, i, squads))] = (SQUADS, proposal_account(i, status, NOW - 3600, 2 if status in ("Approved", "Executed") else 1))
        out[str(mc.transaction_address(ms_key, i, squads))] = (SQUADS, vault_transaction_account(IDS["knos_pay"], BUFFER_PAY))
    return out


def test_the_minimum_is_the_notice_and_the_grace_and_the_plan_is_above_it():
    assert tp.MINIMUM == 7 * 86_400 + 2 * 3600 + 2 == kexit.COVERS
    assert tp.MINIMUM < tp.PLANNED <= tp.MAX_TIME_LOCK == 7_776_000


def test_after_proposals_7_and_8_executed_it_prints_the_config_transaction():
    acc = world({7: "Executed", 8: "Executed"})
    got = tp.plan(lambda a: acc.get(a), IDS, NOW)
    assert got["state"] == "plan" and got["time_lock_now"] == 172_800 and got["transaction_index"] == 9
    data = bytes.fromhex(got["instruction"]["data"])
    assert data[:8] == hashlib.sha256(b"global:config_transaction_create").digest()[:8]
    # one action, variant 3 (SetTimeLock), 691,200 s, no memo
    assert data[8:] == (1).to_bytes(4, "little") + b"\x03" + (691_200).to_bytes(4, "little") + b"\x00"
    names = [(a["name"], a["signer"], a["writable"]) for a in got["instruction"]["accounts"]]
    assert names == [("multisig", False, True), ("transaction", False, True), ("creator", True, False), ("rent_payer", True, True), ("system_program", False, False)]
    tx = got["instruction"]["accounts"][1]["address"]
    assert tx == str(mc.transaction_address(Pubkey.from_string(IDS["upgrade_multisig"]), 9, Pubkey.from_string(SQUADS)))
    assert "config_transaction_execute, from 2 days 0 h after the last approval" in got["steps"][3]
    assert "refunded 21 days" not in got["steps"][4] and "0 days 21 h 59 min before it can run" in got["steps"][4]


def test_it_refuses_while_a_proposal_is_open_or_approved_and_not_executed():
    for status in ("Draft", "Active", "Approved"):
        acc = world({7: "Executed", 8: status})
        try:
            tp.plan(lambda a: acc.get(a), IDS, NOW)
        except tp.Refused as why:
            assert f"proposal 8 (upgrade of {IDS['knos_pay']}, {status.lower()}" in str(why) and "stale" in str(why)
        else:
            raise AssertionError(f"planned past a proposal that is {status}")


def test_it_refuses_what_squads_would_refuse_and_says_when_it_is_already_in_force():
    acc = world({7: "Executed"})
    for seconds in (tp.MINIMUM - 1, tp.MAX_TIME_LOCK + 1):
        try:
            tp.plan(lambda a: acc.get(a), IDS, NOW, seconds)
        except tp.Refused as why:
            assert "outside" in str(why)
        else:
            raise AssertionError(seconds)
    owned = world({7: "Executed"}, authority=bytes([9]) * 32)
    try:
        tp.plan(lambda a: owned.get(a), IDS, NOW)
    except tp.Refused as why:
        assert "config authority" in str(why)
    else:
        raise AssertionError("planned for a multisig with a config authority")
    done = world({9: "Executed"}, time_lock=tp.PLANNED)
    got = tp.plan(lambda a: done.get(a), IDS, NOW)
    assert got["state"] == "in force" and got["steps"] == [] and "Nothing to send" in got["words"][0]


def test_the_script_runs_from_a_state_file(tmp_path):
    state = tmp_path / "state.json"
    for statuses, code in (({7: "Executed", 8: "Executed"}, 0), ({8: "Approved"}, 1)):
        acc = world(statuses)
        state.write_text(json.dumps({"now": NOW, "accounts": {a: {"owner": o, "data": d.hex()} for a, (o, d) in acc.items()}}), encoding="utf-8")
        run = subprocess.run([sys.executable, str(ROOT / "scripts" / "timelock_plan.py"), "--state", str(state), "--json"],
                             capture_output=True, text=True, encoding="utf-8", check=False)
        assert run.returncode == code, run.stderr
        if code == 0:
            assert json.loads(run.stdout)["time_lock_planned"] == 691_200
        else:
            assert "Refused: proposals are still open" in run.stderr


def test_knos_exit_says_what_the_time_lock_covers():
    today, planned = world({8: "Executed"}), world({9: "Executed"}, time_lock=tp.PLANNED)
    assert kexit.time_lock(lambda a: today.get(a), IDS) == 172_800
    assert kexit.time_lock(lambda a: planned.get(a), IDS) == tp.PLANNED
    assert kexit.time_lock(lambda a: None, IDS) is None
    short, covered = kexit.lock_words(172_800), kexit.lock_words(tp.PLANNED)
    assert "shorter than 7 days of notice" in short and "122 h 0 min short" in short
    assert "every open order can be cancelled and refunded before any upgrade approved from now on" in covered and "Held orders" in covered
    assert kexit.lock_words(kexit.COVERS - 1).startswith("The upgrade multisig's time lock is 170 h") and "shorter" in kexit.lock_words(kexit.COVERS - 1)
    assert kexit.words([], NOW, None, tp.PLANNED, True)[-1] == covered
    assert kexit.as_json([], NOW, None, 172_800)["open_orders_covered"] is False


def test_an_order_cancelled_at_the_approval_is_refunded_before_an_upgrade_under_the_planned_lock():
    """The exit plan's own arithmetic: an open order with a far deadline, funded with the grace, cancelled when the
    upgrade is approved, is out before approval + the planned lock and not before approval + 48 hours."""
    approved = 1_000_000
    o = pay.Order(state="open", mode=0, from_balance=False, flags=0, decimals=6, reserve_days=0, repo_id=1, issue=1, scope=bytes(32), seq=0,
                  holdback_bps=0, kill_bps=0, amount=5_000_000, fee=50_000, rate=0, paid=0, deadline=approved + 30 * 86_400, not_before=0,
                  hold_until=0, warranty_s=0, reserved_by=0, reserved_until=0, cancel_at=0, payee_id=0, funder_id=0, owner_id=0, arbiter_id=0,
                  judge_repo_id=0, source=Pubkey.default(), refund_to=Pubkey.default(), rent_to=Pubkey.default(), mint=Pubkey.default(),
                  terms=bytes(32), wf_repo_hash=bytes(32), wf_sha="c" * 40, fee_bps=30, grace=True)
    _state, _mint, ix, out_at, _who, _why = kexit.order_way(o, 0, approved)
    assert ix == "Cancel, then RefundOrder"
    for lock, before in ((172_800, False), (kexit.COVERS - 1, False), (kexit.COVERS, True), (tp.PLANNED, True)):
        assert (out_at < approved + lock) is before, lock
