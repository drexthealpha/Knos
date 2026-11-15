"""Why a fund or pay attempt did not complete, and what the reply says next (knos.ghwords.RELAY).

Every reason the public relay log has given (stats.json, latency.attempts, 9 Oct 2026) is here: the asker's own
reasons get one plain sentence on what to do, Knos's reasons are counted as failures, and the two real bugs behind
two of the reasons (an import of a module that no longer exists, a token-size limit of 2,048 bytes) stay fixed.
"""

from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

import pytest
from solders.keypair import Keypair

from knos import flow, ghwords
from knos.settle.v2 import oidc
from knos.settle.v2.relay import kinds
from knos.settle.v2.relay.pins import _Stop

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import network_stats as ns  # noqa: E402

# (the relay's reason as it says it now, or said it in the log; whose it is)
SEEN = [
    ("an older fund token than the repository's last one; comment again", "knos"),
    ("this issue already has the repository's bounty", "user"),
    ("this issue already has a bounty from this balance (job 9xQ)", "user"),
    ("the escrow on this cluster is version 2.0, which takes no such token yet; it will once the announced upgrade to 2.1 is live", "knos"),
    ("AttributeError: module 'knos.jobs.market' has no attribute 'fund_with_token'", "knos"),
    ("ProgramVersionError: devnet runs knos-escrow older than 0.3.9", "knos"),
    ("ValueError: token too long", "knos"),
    ("the token is 9000 bytes; the verifier takes up to 8192", "knos"),
    ("no bounty on this issue", "user"),
    ("no bounty is in escrow for this issue (never funded, or already paid or refunded)", "user"),
    ("not an audience of the second deployment: 'knos:pay:1:2:3'", "user"),
    ("RpcError: Transaction simulation failed: Error processing Instruction 2", "knos"),
    ("for an order with a quorum a neutral run counts only as a third party's: not one in the order's own repository, and not one started by its funder", "user"),
    ("no open job on this issue accepted the token", "knos"),       # a bounty is there, and refused this token
]


@pytest.mark.parametrize("why,whose", SEEN)
def test_every_reason_the_log_gave_has_an_owner_and_one_plain_next_step(why, whose):
    got, then = ghwords.relay_reason(why)
    assert got == whose
    assert then.endswith(".") and then.count(". ") == 0 and len(then.split()) <= 16, then       # one sentence, short
    assert ghwords.user_error(why) is (whose == "user")


def test_a_reason_nobody_wrote_down_is_knos_s_and_says_to_try_again():
    assert ghwords.relay_reason("TimeoutError: the cluster did not answer") == ("knos", ghwords.RELAY_AGAIN)
    assert ghwords.relay_reason(None) == ("knos", ghwords.RELAY_AGAIN)


def test_the_reply_ends_with_the_reason_s_own_step_or_the_command_s_own_retry():
    again = "Post `/knos fund 5` again to try again."
    assert flow._then("this issue already has the repository's bounty", again).startswith("This issue has its bounty already")
    assert flow._then("RpcError: blockhash not found", again) == again
    assert flow._then("an older fund token than the repository's last one", again).startswith("Another funding")
    assert flow._theirs({"ok": False, "why": "no bounty on this issue"})
    assert not flow._theirs({"ok": False, "why": "RpcError: blockhash not found"})
    assert not flow._theirs({"ok": False, "timeout": True, "why": "no relayer carried it within 10 minutes"})
    assert not flow._theirs({"ok": True, "why": ""})


def _line(kind, issue, ok, rest, tid):
    return f"knos-relay {kind} o/r#{issue} {tid} {'ok' if ok else 'fail'} {rest}"


def test_the_stats_count_the_asker_s_own_errors_apart_from_failures():
    lines = [
        _line("fund", 1, False, "this issue already has the repository's bounty", "a1"),       # the asker's: never done
        _line("fund", 2, False, "an older fund token than the repository's last one; comment again", "a2"),
        _line("fund", 2, True, "sig=s note=job t=3", "a3"),                                        # done after a failure
        _line("fund", 3, False, "AttributeError: module 'knos.jobs.market' has no attribute 'x'", "a4"),   # Knos's: never done
        _line("fund", 4, True, "sig=s note=job t=2", "a5"),
        _line("fund", 5, False, "no bounty on this issue", "a6"),
        _line("fund", 5, False, "RpcError: Transaction simulation failed", "a7"),                  # one of them Knos's: a failure
    ]
    a = ns.attempts([{"created_at": "2026-10-04T00:00:00Z", "body": "\n".join(lines)}], ns.ATTEMPTS["fund"])
    assert (a["asked"], a["completed"], a["never"], a["user_errors"], a["failures"]) == (5, 2, 3, 1, 2)
    assert a["completion"] == 0.4 and a["completion_possible"] == 0.5
    assert a["user_reasons"] == {"this issue already has the repository's": 1, "no bounty on this issue": 1}
    assert ns.attempts([])["completion_possible"] is None and ns.attempts([])["user_errors"] == 0


def test_no_module_names_the_jobs_market_that_was_removed():
    """`AttributeError: module 'knos.jobs.market'` came from a relay of 2 Oct (0.3.9); 0.3.10 removed the module."""
    assert not (ROOT / "src" / "knos" / "jobs").exists()
    for p in [*(ROOT / "src" / "knos").rglob("*.py"), *(ROOT / "scripts").glob("*.py")]:
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"\bknos\.jobs\b|\bjobs\.market\b|from \.+jobs import market\b", text), p


def _token(size: int) -> str:
    """An unsigned GitHub-shaped token of `size` bytes (the padding is a long claim, as a long ref or path gives)."""
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    head = enc({"alg": "RS256", "kid": "nobody", "typ": "JWT"})
    body = {"iss": oidc.ISSUERS[oidc.GITHUB], "aud": "knos3:take:x", "pad": ""}
    base = len(head) + len(enc(body)) + 2 + 342
    body["pad"] = "p" * max(0, (size - base) * 3 // 4)
    while len(f"{head}.{enc(body)}.") + 342 < size:
        body["pad"] += "p"
    return f"{head}.{enc(body)}." + "A" * (size - len(f"{head}.{enc(body)}."))


def test_a_token_over_the_old_2048_byte_limit_is_taken_and_one_over_the_verifier_s_gets_a_plain_answer():
    """`ValueError: token too long` was the 0.3.9 relay's limit of 2,048 bytes. The verifier now takes 8,192
    (knos_oidc MAX_JWT); a longer token is answered with its size, never an exception."""
    me, jwks = Keypair.from_seed(bytes(32)).pubkey(), {oidc.GITHUB: {"keys": []}}
    for size in (2049, 4096, oidc.MAX_JWT):
        jwt = _token(size)
        assert len(jwt) == size
        with pytest.raises(_Stop) as e:
            kinds._open(jwt, me, jwks)
        assert "key set has no key" in e.value.result["why"]          # past the size check: refused only for its key
    with pytest.raises(_Stop) as e:
        kinds._open(_token(oidc.MAX_JWT + 1), me, jwks)
    why = e.value.result["why"]
    assert why == f"the token is {oidc.MAX_JWT + 1} bytes; the verifier takes up to {oidc.MAX_JWT}"
    assert ghwords.relay_reason(why)[0] == "knos"
