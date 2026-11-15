"""Knos Receipt: signed with Ed25519, verified offline with the standard library alone; tampering, another key and
anything shaped like a secret are refused; the page renders, carries the receipt and verifies from the page."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from solders.keypair import Keypair

from knos.receipt2 import core, ed25519, page

ROOT = Path(__file__).resolve().parents[1]


def verdict(passed=True, mode="hidden"):
    return {"repo": "owner/demo", "pr": 9, "head": "c" * 40, "base": "b" * 40, "passed": passed,
            "rule": "" if passed else "gate.hidden_tests_failed", "mode": mode, "spec_hash": "a" * 64 if mode == "hidden" else "",
            "hidden": {"total": 3, "passed": 3, "failed": 0, "errors": 0, "skipped": 0} if mode == "hidden" else None,
            "public": {"total": 1, "passed": 1, "failed": 0, "errors": 0, "skipped": 0},
            "findings": [], "library": "knos.gate.cheatlib (local rules)"}


def envelope(kp=None, **kw):
    kp = kp or Keypair()
    runner = core.runner_from_env({"GITHUB_RUN_ID": "42", "GITHUB_REPOSITORY": "owner/demo", "RUNNER_ENVIRONMENT": "github-hosted"})
    body = core.build(verdict(**kw), issuer_name="test", issuer_key=str(kp.pubkey()), runner=runner,
                      rerun={"ran": True, "agrees": True}, rules_run=["gate.test_edited"], issued_at=1_760_000_000)
    return core.sign(body, kp), kp


def test_sign_and_verify():
    env, kp = envelope()
    got = core.verify(env)
    assert got["valid"] and got["digest"] == core.digest(env["receipt"]) and got["issuer"] is None
    assert env["receipt"]["links"]["install"].endswith("REFEREE.md#install")
    assert env["receipt"]["runner"]["run_url"] == "https://github.com/owner/demo/actions/runs/42"


@pytest.mark.parametrize("field, value", [("verdict", "passed2"), ("pull_request", 10), ("spec_hash", "b" * 64), ("head", "d" * 40)])
def test_any_change_breaks_the_signature(field, value):
    env, _ = envelope()
    env["receipt"][field] = value
    assert not core.verify(env)["valid"]


def test_another_key_is_refused():
    env, _ = envelope()
    other = Keypair()
    env["signature"]["sig"] = str(other.sign_message(core.canonical(env["receipt"])))
    assert not core.verify(env)["valid"]
    env2, _ = envelope()
    env2["signature"]["key"] = str(other.pubkey())
    assert "another issuer key" in core.verify(env2)["why"]


def test_the_pure_python_verifier_agrees_with_solders():
    for i in range(5):
        kp = Keypair()
        msg = os.urandom(i * 37)
        sig = bytes(kp.sign_message(msg))
        pub = bytes(kp.pubkey())
        assert ed25519.verify(pub, msg, sig)
        bad = bytearray(sig)
        bad[i] ^= 1
        assert not ed25519.verify(pub, msg, bytes(bad))
        assert not ed25519.verify(pub, msg + b"x", sig)
        assert ed25519.b58decode(str(kp.pubkey())) == pub and ed25519.b58encode(pub) == str(kp.pubkey())


def test_rfc8032_vector():
    # RFC 8032 section 7.1, TEST 2 (one-byte message 0x72)
    pub = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
    sig = bytes.fromhex("92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
                        "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")
    assert ed25519.verify(pub, b"\x72", sig) and not ed25519.verify(pub, b"\x73", sig)


def test_verify_needs_only_the_standard_library(tmp_path):
    env, _ = envelope()
    f = tmp_path / "r.json"
    f.write_text(json.dumps(env))
    code = ("import json,sys,importlib.util as u\n"
            f"sys.path.insert(0, {str(ROOT / 'src' / 'knos' / 'receipt2')!r})\n"
            "import ed25519, hashlib\n"
            "e=json.load(open(sys.argv[1]))\n"
            "b=json.dumps(e['receipt'],sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()\n"
            "print(ed25519.verify(ed25519.b58decode(e['signature']['key']), b, ed25519.b58decode(e['signature']['sig'])))\n"
            "print('solders' in sys.modules)\n")
    out = subprocess.run([sys.executable, "-I", "-c", code, str(f)], capture_output=True, text=True, check=True).stdout.split()
    assert out == ["True", "False"]


@pytest.mark.parametrize("secret", ["ghp_" + "a" * 36, "-----BEGIN RSA PRIVATE KEY-----", "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4eXoifQ.sig",
                                    json.dumps(list(range(64))), "someone@example.com"])
def test_a_receipt_never_carries_a_secret(secret):
    v = verdict()
    v["findings"] = [{"rule": "x", "category": "out_of_scope", "path": secret, "severity": "refuse"}]
    with pytest.raises(ValueError, match="secret"):
        core.build(v, issuer_name="t", issuer_key="k", runner={"kind": "local"})


def test_public_tests_only_is_said():
    env, _ = envelope(mode="public-tests-only")
    r = env["receipt"]
    assert r["mode"] == "public-tests-only" and "PUBLIC TESTS ONLY" in r["scope_note"] and r["tests"]["hidden"] is None
    assert "public tests only" in page.badge(env)


def test_page_renders_and_verifies_from_the_page():
    env, _ = envelope()
    html = page.render(env)
    assert "Knos Receipt" in html and "signature" in html.lower() and "valid" in html
    assert "Turn on the Knos check for your repo" in html and "<script src" not in html
    assert core.verify(page.from_page(html))["valid"]
    assert not core.secrets_in(html)


def test_page_escapes_what_it_shows():
    kp = Keypair()
    v = verdict(passed=False)
    v["findings"] = [{"rule": "gate.out_of_scope", "category": "out_of_scope", "path": "<script>alert(1)</script>", "severity": "refuse"}]
    body = core.build(v, issuer_name="t", issuer_key=str(kp.pubkey()), runner={"kind": "local"})
    html = page.render(core.sign(body, kp))
    assert "<script>alert(1)</script>" not in html.split('id="knos-receipt">')[0]


def test_the_listed_demo_issuer_is_not_a_founder_key():
    listed = core.known_issuers()
    assert len(listed) == 1 and "not a founder key" in listed[0]["note"].lower()
    ids = json.loads((ROOT / "src" / "knos" / "settle" / "v2" / "program_ids.json").read_text())
    assert listed[0]["key"] not in json.dumps(ids)


def test_rerun_agreement():
    a = {"total": 3, "passed": 3, "failed": 0, "errors": 0}
    assert core.rerun_agrees(a, dict(a))
    assert not core.rerun_agrees(a, {"total": 3, "passed": 2, "failed": 1, "errors": 0})


# ---- review fixes: major 10 (counts must agree), minor 40 (an unlisted key is said on the page) ----

def test_rerun_counts_must_match():
    a = {"total": 3, "passed": 3, "failed": 0, "errors": 0, "exit": 0}
    assert not core.rerun_agrees(a, {"total": 3, "passed": 2, "failed": 0, "errors": 0, "skipped": 1, "exit": 0})
    assert not core.rerun_agrees(a, {"total": 4, "passed": 4, "failed": 0, "errors": 0, "exit": 0})


def test_the_page_says_when_the_key_is_not_listed():
    env, _ = envelope()
    assert "a key Knos does not list" in page.render(env)
