"""Knos Pro: the meter reads agents' logs correctly, the cap is enforced at the guard, and a Solana Pay purchase is
checked against the transaction itself. The RPC is never reached: its answers are fixtures."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from knos import guard
from knos.pro import budget, licence, meter, prices, solana

NOW = datetime.now(timezone.utc)


def _ts(minutes_ago: float = 1) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _claude_log(lines: list[dict]) -> Path:
    root = Path(os.environ["CLAUDE_CONFIG_DIR"]) / "projects" / "-home-me-repo"
    root.mkdir(parents=True, exist_ok=True)
    f = root / "s1.jsonl"
    with f.open("a", encoding="utf-8") as fh:
        for rec in lines:
            fh.write(json.dumps(rec) + "\n")
    return f


def _assistant(mid: str, rid: str, model: str = "claude-sonnet-4-6", inp=1000, out=500, cr=0) -> dict:
    return {"type": "assistant", "requestId": rid, "timestamp": _ts(), "cwd": "/home/me/repo",
            "message": {"id": mid, "model": model, "usage": {"input_tokens": inp, "output_tokens": out,
                                                             "cache_read_input_tokens": cr,
                                                             "cache_creation_input_tokens": 0}}}


def test_a_message_logged_once_per_block_is_counted_once() -> None:
    _claude_log([_assistant("m1", "r1"), _assistant("m1", "r1"), _assistant("m1", "r1"), _assistant("m2", "r2")])
    meter.update()
    got = meter.spent(NOW - timedelta(hours=1))
    per = (1000 * 3.0 + 500 * 15.0) / 1_000_000
    assert got["by"][0]["messages"] == 2
    assert abs(got["usd"] - 2 * per) < 1e-9


def test_reads_are_incremental_and_a_half_written_line_waits() -> None:
    f = _claude_log([_assistant("m1", "r1")])
    meter.update()
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_assistant("m2", "r2"))[:40])  # still being written
    meter.update()
    assert meter.spent(NOW - timedelta(hours=1))["by"][0]["messages"] == 1
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(_assistant("m2", "r2"))[40:] + "\n")
    meter.update()
    assert meter.spent(NOW - timedelta(hours=1))["by"][0]["messages"] == 2


def test_an_unknown_model_is_priced_high_and_marked_estimated() -> None:
    _claude_log([_assistant("m1", "r1", model="claude-future-9")])
    meter.update()
    got = meter.spent(NOW - timedelta(hours=1))
    assert got["estimated"] and got["usd"] >= (1000 * 10 + 500 * 50) / 1_000_000 - 1e-9


def test_codex_spend_is_the_increase_of_the_running_total() -> None:
    root = Path(os.environ["CODEX_HOME"]) / "sessions" / "2026" / "09" / "29"
    root.mkdir(parents=True)

    def tc(i, c, o):
        return {"timestamp": _ts(), "type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": i, "cached_input_tokens": c, "output_tokens": o}}}}

    rows = [{"timestamp": _ts(), "type": "turn_context", "payload": {"model": "gpt-5", "cwd": "/r"}},
            tc(1000, 0, 100), tc(1000, 0, 100), tc(3000, 1000, 300)]
    (root / "rollout-x.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    meter.update()
    got = meter.spent(NOW - timedelta(hours=1), host="codex")
    # uncached input 1000 + 1000, cached 1000, output 300 in total
    want = (2000 * 1.25 + 1000 * 0.13 + 300 * 10.0) / 1_000_000
    assert abs(got["usd"] - want) < 1e-9 and got["by"][0]["messages"] == 2


def test_prices_match_longest_prefix() -> None:
    assert prices.row("claude-sonnet-4-6-20260101")[0] == prices.LIST["claude-sonnet-4-6"]
    assert prices.row("gpt-5.4-mini")[0] == prices.LIST["gpt-5.4-mini"]


# ---- licence ------------------------------------------------------------------------


def test_trial_starts_once_and_lasts_fourteen_days() -> None:
    assert licence.status()["why"] == "none"
    st = licence.status(start_trial=True)
    assert st["active"] and st["why"] == "trial" and 13.9 < st["days_left"] <= 14
    started = json.loads(licence.trial_path().read_text())["started"]
    licence.status(start_trial=True)
    assert json.loads(licence.trial_path().read_text())["started"] == started


def test_an_expired_trial_is_not_active() -> None:
    old = (NOW - timedelta(days=15)).isoformat()
    licence.trial_path().write_text(json.dumps({"started": old}))
    assert licence.status(start_trial=True) == {"active": False, "why": "expired",
                                                "expires": (datetime.fromisoformat(old) + timedelta(days=14)).isoformat()}


def test_a_chain_paid_licence_counts_until_it_expires() -> None:
    body = licence.from_payment("pro-month", "SIG", "REF", "devnet", 10.0)
    licence.write(body)
    assert licence.status()["why"] == "licence"
    body["expires"] = (NOW - timedelta(days=1)).isoformat()
    licence.write(body)
    assert licence.status()["why"] == "none"


def test_a_signed_code_verifies_and_a_tampered_one_does_not() -> None:
    crypto = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    import base64

    key = crypto.Ed25519PrivateKey.generate()
    from cryptography.hazmat.primitives import serialization

    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    body = {"plan": "pro-year", "holder": "x", "expires": (NOW + timedelta(days=365)).isoformat()}
    body["sig"] = base64.urlsafe_b64encode(key.sign(licence.canonical(body))).decode().rstrip("=")
    assert licence.verify_signed(body, pub)
    assert not licence.verify_signed({**body, "plan": "team-seat"}, pub)
    code = base64.urlsafe_b64encode(json.dumps(body).encode()).decode()
    assert licence.decode_code(code) == body


# ---- Solana Pay -------------------------------------------------------------------------

REF = solana.b58encode(bytes(range(32)))


def test_base58_round_trips_and_references_are_addresses() -> None:
    raw = bytes([0, 0, 7] + list(range(29)))
    assert solana.b58decode(solana.b58encode(raw)) == raw
    assert solana.is_address(solana.MERCHANT) and solana.is_address(solana.new_reference())
    assert not solana.is_address("0OIl")


def test_the_link_is_a_solana_pay_transfer_request() -> None:
    url = solana.link("pro-month", 10, REF, "devnet", order="abc")
    u = urlparse(url)
    assert u.scheme == "solana" and u.path == solana.MERCHANT
    q = parse_qs(u.query)
    assert q["amount"] == ["10"] and q["spl-token"] == [solana.USDC["devnet"]]
    assert q["reference"] == [REF] and q["label"] == ["Knos"] and q["message"] == ["Knos Pro"]
    assert q["memo"] == ["knos:pro-month:abc"]
    assert "%20" in url and "+" not in url
    assert solana.link("pro-year", 100.5, REF)[:0] == "" and "amount=100.5" in solana.link("pro-year", 100.5, REF)


def _tx(delta_usdc: float, ref: str = REF, err=None, mint: str | None = None) -> dict:
    mint = mint or solana.USDC["devnet"]
    base = 5_000_000
    return {"meta": {"err": err,
                     "preTokenBalances": [{"owner": solana.MERCHANT, "mint": mint, "uiTokenAmount": {"amount": str(base)}}],
                     "postTokenBalances": [{"owner": solana.MERCHANT, "mint": mint,
                                            "uiTokenAmount": {"amount": str(base + int(delta_usdc * 1e6))}}],
                     "logMessages": ['Program log: Memo (len 19): "knos:pro-month:abc"']},
            "transaction": {"message": {"accountKeys": [{"pubkey": "payer"}, {"pubkey": ref}], "instructions": []}}}


def test_a_full_payment_with_the_reference_passes() -> None:
    ok, why, got = solana.check_payment(_tx(10), REF, 10, "devnet")
    assert ok and got == 10
    assert solana.memo_of(_tx(10)) == "knos:pro-month:abc"


@pytest.mark.parametrize("tx,reason", [
    (_tx(9.99), "was due"),
    (_tx(10, ref="someoneelse"), "reference"),
    (_tx(10, err={"InstructionError": [0, "x"]}), "failed"),
    (_tx(10, mint="So11111111111111111111111111111111111111112"), "was due"),
    (None, "not found"),
])
def test_anything_short_of_a_full_payment_fails(tx, reason) -> None:
    ok, why, _ = solana.check_payment(tx, REF, 10, "devnet")
    assert not ok and reason in why


def test_find_payment_reads_the_rpc(monkeypatch) -> None:
    calls = []

    def fake(network, method, params, timeout=20.0):
        calls.append(method)
        if method == "getSignaturesForAddress":
            assert params[0] == REF
            return [{"signature": "bad", "err": {"x": 1}}, {"signature": "short", "err": None},
                    {"signature": "good", "err": None}]
        return {"short": _tx(1), "good": _tx(10)}[params[0]]

    monkeypatch.setattr(solana, "rpc", fake)
    got = solana.find_payment(REF, 10, "devnet")
    assert got == {"signature": "good", "paid": 10.0, "memo": "knos:pro-month:abc"}
    assert calls.count("getTransaction") == 2  # the failed one is never fetched


def test_buy_writes_a_licence_when_the_payment_lands(repo, capsys, monkeypatch) -> None:
    from knos.cli import main

    monkeypatch.setattr(solana, "find_payment", lambda ref, amount, network, recipient=solana.MERCHANT:
                        {"signature": "5ig", "paid": amount, "memo": ""})
    assert main(["pro", "buy", "--network", "devnet"]) == 0
    said = capsys.readouterr().out
    assert "solana:" + solana.MERCHANT in said and "Paid." in said and "cluster=devnet" in said
    lic = licence.read()
    assert lic["via"] == "solana:5ig" and lic["network"] == "devnet" and licence.valid(lic)


def test_the_same_payment_cannot_activate_twice(repo, capsys, monkeypatch) -> None:
    from knos.cli import main

    monkeypatch.setattr(solana, "find_payment", lambda ref, amount, network, recipient=solana.MERCHANT:
                        {"signature": "5ig", "paid": amount, "memo": ""})
    assert main(["pro", "buy", "--network", "devnet"]) == 0
    licence.licence_path().unlink()
    assert main(["pro", "buy", "--network", "devnet"]) == 1
    assert "already activated" in capsys.readouterr().out
    assert licence.read() is None


def test_team_needs_three_seats_and_prices_by_seat(repo, capsys, monkeypatch) -> None:
    from knos.cli import main

    assert main(["pro", "buy", "--team", "2", "--no-wait"]) == 1
    assert main(["pro", "buy", "--team", "3", "--no-wait", "--network", "devnet"]) == 0
    assert "amount=96" in capsys.readouterr().out


# ---- the cap, at the guard ------------------------------------------------------------------


def test_a_reached_cap_refuses_edits_and_raising_it_lets_them_through(repo) -> None:
    licence.status(start_trial=True)
    _claude_log([_assistant("m1", "r1", model="claude-opus-5", inp=1_000_000, out=0)])  # $5
    budget.set_cap(4, "day")
    event = {"tool_input": {"file_path": str(repo / "src/auth.py")}, "cwd": str(repo), "session_id": "s"}
    v = guard.decide("claude", event)
    assert not v.allow and "spend cap" in v.reason and "knos budget raise" in v.reason
    budget.raise_cap(10)
    assert guard.decide("claude", event).allow


def test_no_cap_costs_nothing_and_an_unlicensed_cap_is_not_enforced(repo) -> None:
    event = {"tool_input": {"file_path": str(repo / "src/auth.py")}, "cwd": str(repo)}
    assert guard._over_budget() is None
    licence.trial_path().write_text(json.dumps({"started": (NOW - timedelta(days=30)).isoformat()}))
    _claude_log([_assistant("m1", "r1", model="claude-opus-5", inp=1_000_000, out=0)])
    budget.set_cap(1, "day")
    assert guard.decide("claude", event).allow


# ---- re-verification and scope ------------------------------------------------------------


def test_a_chain_licence_is_rechecked_daily_and_rides_a_grace_period_offline() -> None:
    body = licence.from_payment("pro-month", "SIG", "REF", "devnet", 10.0)
    body["verified_at"] = (NOW - timedelta(days=2)).isoformat()
    licence.write(body)
    assert licence.valid(licence.read())  # 2 days since the last check: within 1 + 7

    def offline(chain, network, tx):
        raise OSError("no network")

    licence.reverify(offline)
    assert licence.read()["verified_at"] == body["verified_at"]  # unchanged, still valid
    body["verified_at"] = (NOW - timedelta(days=9)).isoformat()
    licence.write(body)
    assert not licence.valid(licence.read())  # grace over: a Pro command online re-checks it
    licence.reverify(lambda chain, network, tx: True)
    assert licence.valid(licence.read())


def test_a_payment_that_no_longer_checks_out_ends_the_licence() -> None:
    body = licence.from_payment("pro-month", "SIG", "REF", "devnet", 10.0)
    body["verified_at"] = (NOW - timedelta(days=2)).isoformat()
    licence.write(body)
    licence.reverify(lambda chain, network, tx: False)
    assert not licence.valid(licence.read()) and "no longer" in licence.read()["revoked"]


def test_a_repo_scoped_cap_only_counts_and_refuses_that_repo(repo, tmp_path) -> None:
    licence.status(start_trial=True)
    rec = _assistant("m1", "r1", model="claude-opus-5", inp=1_000_000, out=0)
    rec["cwd"] = str(tmp_path / "other-repo")
    _claude_log([rec])  # $5, spent in another repo
    budget.set_cap(1, "day", repo=str(repo))
    assert budget.state()["spent"] == 0 and not budget.state()["over"]
    event = {"tool_input": {"file_path": str(repo / "src/auth.py")}, "cwd": str(repo)}
    assert guard.decide("claude", event).allow
    rec2 = _assistant("m2", "r2", model="claude-opus-5", inp=1_000_000, out=0)
    rec2["cwd"] = str(repo)
    _claude_log([rec2])
    budget.state()  # the guard re-reads the logs at most once a minute; read them now rather than wait
    v = guard.decide("claude", event)
    assert not v.allow and f"for {repo.name}" in v.reason
