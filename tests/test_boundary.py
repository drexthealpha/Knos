"""The protected enterprise spending boundary (knos.boundary): the Squads v4 settings a procurement policy becomes, and
Squads itself refusing what the plan says it refuses; approvals bound to one commitment; budgets reserved before work
by two writers at once.

The Squads tests run Squads Labs' deployed program in LiteSVM beside the test build of knos_pay. The program is not
in the repository: `python scripts/squads_program.py fetch` reads it from devnet and checks it against a pinned
sha256; without it those tests are skipped.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from knos import approvals, boundary, controls  # noqa: E402

U = 1_000_000
PROC = controls.PROCUREMENT
KEYS = {  # fixed addresses (no key is needed to plan)
    "ravi-acme": "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin",
    "mei-acme": "4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsp7D4xWLs4gDB4T",
    "dana-acme": "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj",
    "lee-acme": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
}
AUTHORITY = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
POLICY = {"version": 1, "kind": "approval-policy", "currency": "test USDC", "self_approval_limit": 0,
          "roles": {"requester": [{"account": "ravi-acme"}], "approver": [{"account": "mei-acme"}, {"account": "lee-acme"}],
                    "finance": [{"account": "dana-acme"}], "auditor": [{"account": "audit-acme"}]},
          "thresholds": [{"up_to": "1000", "approvers": 1}, {"approvers": 1, "finance": 1}]}
def rows(keys: dict) -> list[dict]:
    return [{"account": a, "key": k} for a, k in keys.items()]


BOUNDARY = {"version": 1, "kind": "spending-boundary", "keys": rows(KEYS), "config_authority": AUTHORITY, "time_lock_hours": 24,
            "balance": {"owner_id": 424242, "cap_per_order": "10000", "per_day": "20000", "total": "100000", "spenders": [555000],
                        "workflows_commit": "c" * 40}}


# ---- the plan ----------------------------------------------------------------------------------------------------------
def test_the_plan_gives_requesters_no_vote_a_threshold_a_time_lock_and_a_separate_config_authority():
    p = boundary.plan(POLICY, BOUNDARY)
    s = p["squads"]["create"]
    assert p["squads"]["program"] == boundary.SQUADS and s["config_authority"] == AUTHORITY and s["time_lock"] == 86_400
    assert s["threshold"] == 2                                   # the policy's highest step: one approver and finance
    masks = {m["accounts"][0]: m["mask"] for m in s["members"]}
    assert masks == {"ravi-acme": boundary.INITIATE, "mei-acme": boundary.VOTE | boundary.EXECUTE, "lee-acme": boundary.VOTE | boundary.EXECUTE,
                     "dana-acme": boundary.VOTE | boundary.EXECUTE}
    assert "audit-acme" not in json.dumps(s)                     # an auditor reads; no key in the vault
    assert p["balance"] == {"authority": "the vault", "owner_id": 424242, "cap": 10_000 * U, "spenders": [555000], "day_limit": 20_000 * U,
                            "total_limit": 100_000 * U, "repos": [], "workflows_commit": "c" * 40}
    assert p["squads"]["spending_limits"] == []
    assert any("Tiers by amount" in a for a in p["advisory"]) and any("Finance as a separate signature" in a for a in p["advisory"])
    assert any("only the config authority" in h for h in p["hard"])
    text = "\n".join(boundary.plan_lines(p))
    assert "threshold 2, time lock 86400 s" in text and "@ravi-acme): initiate" in text


def test_the_plan_refuses_what_squads_could_not_hold():
    def refused(policy=POLICY, b=BOUNDARY) -> str:
        with pytest.raises(boundary.Refused) as e:
            boundary.plan(policy, b)
        return str(e.value)
    both = {**POLICY, "roles": {**POLICY["roles"], "requester": [{"account": "ravi-acme"}, {"account": "mei-acme"}]}}
    assert "both requests and approves" in refused(both)
    assert "config authority is also a member's key" in refused(b={**BOUNDARY, "config_authority": KEYS["mei-acme"]})
    assert "gives no Solana key" in refused(b={**BOUNDARY, "keys": rows({k: v for k, v in KEYS.items() if k != "dana-acme"})})
    assert "share one key" in refused(b={**BOUNDARY, "keys": rows({**KEYS, "lee-acme": KEYS["mei-acme"]})})
    assert "time_lock_hours" in refused(b={**BOUNDARY, "time_lock_hours": 2161})
    assert "at most 4 GitHub ids" in refused(b={**BOUNDARY, "balance": {**BOUNDARY["balance"], "spenders": [1, 2, 3, 4, 5]}})
    assert "not sound" in refused(policy={**POLICY, "thresholds": []})


def test_an_allowance_is_planned_only_when_asked_and_says_it_spends_without_a_vote():
    allowance = {"name": "hosting", "destination": AUTHORITY, "mint": KEYS["lee-acme"], "amount": "500", "period": "month", "members": ["dana-acme"]}
    p = boundary.plan(POLICY, {**BOUNDARY, "allowances": [allowance]})
    [sl] = p["squads"]["spending_limits"]
    assert (sl["amount"], sl["period_index"], sl["members"], sl["destinations"]) == (500 * U, 3, [KEYS["dana-acme"]], [AUTHORITY])
    assert "WITHOUT a vote" in sl["note"] and any("Allowances" in a for a in p["advisory"])
    with pytest.raises(boundary.Refused):
        boundary.plan(POLICY, {**BOUNDARY, "allowances": [{**allowance, "period": "year"}]})


def test_knos_boundary_plan_prints_the_plan(tmp_path):
    typer = pytest.importorskip("typer")
    from typer.testing import CliRunner
    (tmp_path / "policy.yaml").write_text(controls.dump_yaml(POLICY), encoding="utf-8")
    (tmp_path / "boundary.yaml").write_text(controls.dump_yaml(BOUNDARY), encoding="utf-8")
    app, lines = typer.Typer(), []
    boundary.register(app, lines)

    @app.command("other")
    def other() -> None:
        pass
    got = CliRunner().invoke(app, ["boundary", "plan", str(tmp_path / "policy.yaml"), "--json"])
    assert got.exit_code == 0, got.output
    assert json.loads(got.stdout) == boundary.plan(POLICY, BOUNDARY) and lines[0][0] == "boundary"
    (tmp_path / "boundary.yaml").write_text(controls.dump_yaml({**BOUNDARY, "config_authority": KEYS["ravi-acme"]}), encoding="utf-8")
    got = CliRunner().invoke(app, ["boundary", "plan", str(tmp_path / "policy.yaml")])
    assert got.exit_code == 1 and "Refused" in got.output


# ---- approvals bound to one commitment ----------------------------------------------------------------------------------
POLICY_TEXT = controls.dump_yaml(POLICY)
ORDER = {"repo_id": 987654321, "issue": 77, "seq": 0, "funder": KEYS["lee-acme"], "terms_sha256": "ab" * 32, "amount": 1200 * U, "beneficiary": "octocat"}


def bound_files(order: dict = ORDER, expires: str = "2026-11-01", approvers=("mei-acme", "dana-acme"), policy_text: str = POLICY_TEXT) -> tuple[dict, dict]:
    c = boundary.commitment(**{k: order[k] for k in ("repo_id", "issue", "seq", "funder", "terms_sha256", "amount", "beneficiary")},
                            policy_sha256=approvals.sha256_hex(policy_text), expires=expires)
    log = ""
    for n, who in enumerate(approvers, 1):
        role = "finance" if who == "dana-acme" else "approver"
        e = approvals.event(subject=c["subject"], amount=c["amount"], requester="ravi-acme", approver=who, approver_id=9000 + n, role=role,
                            at="2026-10-08T10:00:0%dZ" % n, authority=role, source={"url": f"https://github.com/acme/w/issues/77#c{n}", "comment_id": n},
                            policy_sha256=c["policy_sha256"])
        log += json.dumps(e) + "\n"
    return {f"{PROC}/policy.yaml": POLICY_TEXT, f"{PROC}/requests/issue-77.json": json.dumps(c), f"{PROC}/{approvals.LOG}": log}, c


def test_an_approval_funds_the_one_commitment_it_names():
    files, c = bound_files()
    ok, sentence = boundary.gate_bound(files, order=ORDER, requester="ravi-acme", on="2026-10-09")
    assert ok and sentence.startswith("Approved"), sentence
    assert approvals.read_comment(approvals.comment_line(c["subject"])) == (c["subject"], None)      # what an approver posts is a subject the log reads
    assert boundary.payee_allowed(files, order=ORDER, payee="octocat")[0]


def test_an_approval_is_refused_for_another_order_after_expiry_under_a_changed_policy_or_for_another_payee():
    files, _c = bound_files()
    def why(order=ORDER, f=files, on="2026-10-09") -> str:
        ok, sentence = boundary.gate_bound(f, order=order, requester="ravi-acme", on=on)
        assert not ok
        return sentence
    assert "for another order (the issue differs)" in why({**ORDER, "issue": 78})
    assert "for another order (the order's sequence differs)" in why({**ORDER, "seq": 1})       # the same issue funded twice
    assert "for another order (the funder differs)" in why({**ORDER, "funder": KEYS["mei-acme"]})
    assert "for another order (the terms differs)" in why({**ORDER, "terms_sha256": "cd" * 32})
    assert "expired on 2026-11-01" in why(on="2026-11-02")
    changed = POLICY_TEXT.replace("self_approval_limit: 0", "self_approval_limit: 10")
    assert "policy changed after this approval" in why(f={**files, f"{PROC}/policy.yaml": changed})
    assert "to @octocat, not to @mallory" in why({**ORDER, "beneficiary": "mallory"})
    assert "is for 1,200.00" in why({**ORDER, "amount": 1300 * U}) or "is for 1200.00" in why({**ORDER, "amount": 1300 * U})
    assert not boundary.payee_allowed(files, order=ORDER, payee="mallory")[0]
    # one approval short of the policy: refused with the chain's own sentence
    short, _c = bound_files(approvers=("mei-acme",))
    assert "Waits for finance" in why(f=short)
    # a request edited after its digest was taken
    doc = json.loads(files[f"{PROC}/requests/issue-77.json"])
    edited = {**files, f"{PROC}/requests/issue-77.json": json.dumps({**doc, "beneficiary": "mallory"})}
    assert "changed after its digest" in why({**ORDER, "beneficiary": "mallory"}, f=edited)
    # no policy: nothing more is asked, as approvals.gate_order
    assert boundary.gate_bound({}, order=ORDER, requester="ravi-acme", on="2026-10-09") == (True, "")


# ---- budgets reserved before work ----------------------------------------------------------------------------------------
def test_a_reservation_holds_the_budget_and_gives_it_back(tmp_path):
    r = boundary.Reservations(tmp_path / "budget.db")
    r.set_budget("eng-2026q4", 1000 * U)
    assert r.reserve("eng-2026q4", "issue:77", 600 * U)[0]
    assert r.reserve("eng-2026q4", "issue:77", 600 * U) == (True, "`issue:77` already holds 600.00 of `eng-2026q4`.")  # the same hold
    ok, sentence = r.reserve("eng-2026q4", "issue:78", 500 * U)
    assert not ok and "has 400.00 left" in sentence
    assert r.release("issue:77")[0] and r.reserve("eng-2026q4", "issue:78", 500 * U)[0]
    assert r.spend("issue:78")[0] and not r.release("issue:78")[0]          # a spent hold stays spent
    assert r.status("eng-2026q4")["left"] == 500 * U
    assert not r.reserve("nope", "x", 1)[0]


WRITER = """
import sys
from knos import boundary
r = boundary.Reservations(sys.argv[1])
sys.stdout.write("go\\n"); sys.stdout.flush()
sys.stdin.readline()
ok, sentence = r.reserve("eng", sys.argv[2], 600 * 1_000_000)
print("ok" if ok else "refused", sentence)
"""


def test_two_writers_cannot_both_take_the_last_of_a_budget(tmp_path):
    """Two processes, each with its own connection, ask at the same moment for 600 of 1,000: one gets it."""
    db = tmp_path / "budget.db"
    boundary.Reservations(db).set_budget("eng", 1000 * U)
    env = {"PYTHONPATH": str(ROOT / "src")}
    import os
    env = {**os.environ, **env}
    procs = [subprocess.Popen([sys.executable, "-c", WRITER, str(db), f"issue:{n}"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                              encoding="utf-8", env=env) for n in (1, 2)]
    for p in procs:
        assert p.stdout is not None and p.stdout.readline().strip() == "go"
    for p in procs:                                     # both are ready before either is told to go
        assert p.stdin is not None
        p.stdin.write("\n")
        p.stdin.flush()
    said = sorted(p.communicate(timeout=60)[0].split(" ", 1)[0] for p in procs)
    assert said == ["ok", "refused"], said
    assert boundary.Reservations(db).status("eng")["taken"] == 600 * U


# ---- Squads itself -----------------------------------------------------------------------------------------------------------
def _squads():
    pytest.importorskip("solders.litesvm")
    import _squads
    if not _squads.available():
        pytest.skip("needs the Squads v4 program: python scripts/squads_program.py fetch")
    return _squads


def _vault_chain(time_lock: int = 0):
    sq = _squads()
    from solders.keypair import Keypair
    from _order import USDC
    c = sq.SquadsChain()
    req, a1, a2, cfg = Keypair(), Keypair(), Keypair(), Keypair()
    for k in (req, a1, a2, cfg):
        c.svm.airdrop(k.pubkey(), 10 ** 9)
    # the plan's own members, threshold and time lock, with these keys
    keys = {"ravi-acme": str(req.pubkey()), "mei-acme": str(a1.pubkey()), "dana-acme": str(a2.pubkey()), "lee-acme": str(Keypair().pubkey())}
    p = boundary.plan(POLICY, {**BOUNDARY, "keys": rows(keys), "config_authority": str(cfg.pubkey()), "time_lock_hours": time_lock // 3600})
    by_key = {str(k.pubkey()): k for k in (req, a1, a2)}
    s = p["squads"]["create"]
    members = [(by_key[m["key"]], m["mask"]) for m in s["members"] if m["key"] in by_key]
    ms = c.create(members, s["threshold"], cfg.pubkey(), s["time_lock"])
    vault = sq.vault_pda(ms)
    c.svm.airdrop(vault, 10 ** 9)
    vt = c.token_account(vault, c.usdc)
    c.mint_to(c.usdc, vt, 150 * USDC)
    return sq, c, ms, vault, vt, req, a1, a2, cfg


def _fund_ix(c, vault, vt, amount):
    from _order import REPO, TERMS, issue
    from _pay2 import WF_REPO, WF_SHA
    from knos.settle.v2 import pay
    return pay.fund_order_wallet_ix(vault, vt, c.usdc, REPO, issue(), amount, WF_REPO, WF_SHA, TERMS)


def test_squads_refuses_a_funding_from_the_vault_without_the_threshold():
    from _order import USDC
    from solders.keypair import Keypair
    sq, c, ms, vault, vt, req, a1, a2, _cfg = _vault_chain(time_lock=3600)
    ix = _fund_ix(c, vault, vt, 100 * USDC)
    assert c.propose(ms, Keypair(), [ix]) is None and c.said_error() == "NotAMember"
    i = c.propose(ms, req, [ix])
    assert i is not None, c.err
    assert not c.approve(ms, i, req) and c.said_error() == "Unauthorized"        # a requester's key cannot vote
    assert c.approve(ms, i, a1), c.err
    assert not c.execute(ms, i, a1) and c.said_error() == "InvalidProposalStatus"  # one vote of two: nothing moves
    assert c.order(ix.accounts[1].pubkey) is None
    assert c.approve(ms, i, a2), c.err
    assert not c.execute(ms, i, req) and c.said_error() == "Unauthorized"          # a requester cannot execute
    assert not c.execute(ms, i, a1) and c.said_error() == "TimeLockNotReleased"    # the time lock runs from the last vote
    c.warp(3600)
    assert c.execute(ms, i, a1), c.err
    o = c.order(ix.accounts[1].pubkey)
    assert o is not None and o.source == vault == o.refund_to and o.amount == 100 * USDC        # the vault funded it; a refund goes back to it


def test_the_vault_cannot_fund_past_what_it_holds():
    """Money moves into the order when the funding executes: two approved fundings cannot both take the last of it."""
    from _order import USDC
    from knos.settle.v2 import pay
    sq, c, ms, vault, vt, req, a1, a2, _cfg = _vault_chain()
    first, second = _fund_ix(c, vault, vt, 100 * USDC), _fund_ix(c, vault, vt, 50 * USDC)
    ids = [c.propose(ms, req, [ix]) for ix in (first, second)]
    for i in ids:
        assert i is not None and c.approve(ms, i, a1) and c.approve(ms, i, a2), c.err
    assert c.execute(ms, ids[0], a1), c.err
    left = c.balance(vt)
    assert left == 150 * USDC - 100 * USDC - pay.order_fee(100 * USDC) < 50 * USDC     # less than the second needs
    assert not c.execute(ms, ids[1], a1) and "insufficient funds" in " ".join(c.logs).lower()
    assert c.balance(vt) == left and c.order(second.accounts[1].pubkey) is None


def test_squads_refuses_an_allowance_over_its_limit_to_another_destination_or_by_another_key():
    from _order import USDC
    from solders.keypair import Keypair
    sq, c, ms, vault, vt, req, a1, a2, cfg = _vault_chain()
    dest, other = Keypair().pubkey(), Keypair().pubkey()
    c.token_account(dest, c.usdc)
    c.token_account(other, c.usdc)
    sl = c.add_spending_limit(ms, cfg, c.usdc, 100 * USDC, sq.MONTH, [a2.pubkey()], [dest])
    assert sl is not None, c.err
    from knos.settle.v2 import pay
    assert c.use_spending_limit(ms, sl, a2, c.usdc, dest, 60 * USDC), c.err                     # no vote: an allowance
    assert not c.use_spending_limit(ms, sl, a2, c.usdc, dest, 41 * USDC) and c.said_error() == "SpendingLimitExceeded"
    assert not c.use_spending_limit(ms, sl, a2, c.usdc, other, 1 * USDC) and c.said_error() == "InvalidDestination"
    assert not c.use_spending_limit(ms, sl, a1, c.usdc, dest, 1 * USDC) and c.said_error() == "Unauthorized"
    assert c.balance(pay.ata(dest, c.usdc)) == 60 * USDC
    c.warp(30 * 86_400 + 1)                                                                     # a month (30 days) later the amount is back
    assert c.use_spending_limit(ms, sl, a2, c.usdc, dest, 40 * USDC), c.err


def test_only_the_config_authority_changes_the_vault_policy():
    sq, c, ms, vault, vt, req, a1, a2, cfg = _vault_chain()
    assert not c.change_threshold(ms, a1, 1) and c.said_error() == "Unauthorized"               # an approver cannot lower it
    assert not c.change_threshold(ms, req, 1) and c.said_error() == "Unauthorized"
    assert not c.config_change_threshold(ms, a1, 1) and c.said_error() == "NotSupportedForControlled"   # nor propose it to the others
    assert c.add_spending_limit(ms, a1, c.usdc, 1, sq.DAY, [a1.pubkey()], []) is None and c.said_error() == "Unauthorized"
    assert c.threshold(ms) == 2
    assert c.change_threshold(ms, cfg, 1), c.err
    assert c.threshold(ms) == 1


def test_a_balance_the_vault_opened_is_changed_only_by_the_vault():
    """The vault opens a knos_pay Balance: a comment's funding meets its cap (error 93), a member's own key cannot
    change it (error 98), and the vault's vote can."""
    from _order import OWNER, USDC, issue
    from _order import code as code_of
    from knos.settle.v2 import pay
    sq, c, ms, vault, vt, req, a1, a2, _cfg = _vault_chain()
    i = c.propose(ms, req, [pay.open_balance_ix(vault, OWNER, c.usdc, cap=50 * USDC, spenders=[555000])])
    assert i is not None and c.approve(ms, i, a1) and c.approve(ms, i, a2) and c.execute(ms, i, a1), c.err
    bal = pay.balance_pda(OWNER, vault, c.usdc)
    c.mint_to(c.usdc, pay.baltok_pda(bal), 100 * USDC)
    n = issue()
    tok = c.fund_token(n, 60 * USDC, terms=pay.terms_hash(c_terms()), balance=bal)
    assert not c.send([c.fund_balance_ix(tok, n, bal, c_terms())]) and code_of(c) == 93               # over the cap
    assert not c.send([pay.set_balance_ix(a1.pubkey(), bal, cap=0)], a1) and code_of(c) in (98, 80)   # an approver's own key is not the vault
    j = c.propose(ms, req, [pay.set_balance_ix(vault, bal, cap=70 * USDC, spenders=[555000])])
    assert j is not None and c.approve(ms, j, a1) and c.approve(ms, j, a2) and c.execute(ms, j, a1), c.err
    n = issue()
    tok = c.fund_token(n, 60 * USDC, terms=pay.terms_hash(c_terms()), balance=bal)
    assert c.send([c.fund_balance_ix(tok, n, bal, c_terms())]), c.err
    # the Balance holds what was moved into it and no more: 50 of the 39.82 left is refused, whatever the cap allows
    n = issue()
    tok = c.fund_token(n, 50 * USDC, terms=pay.terms_hash(c_terms()), balance=bal)
    left = c.balance(pay.baltok_pda(bal))
    assert left == 100 * USDC - 60 * USDC - pay.order_fee(60 * USDC) < 50 * USDC
    assert not c.send([c.fund_balance_ix(tok, n, bal, c_terms())]) and c.balance(pay.baltok_pda(bal)) == left


def c_terms() -> bytes:
    from _order import TERMS
    return TERMS
