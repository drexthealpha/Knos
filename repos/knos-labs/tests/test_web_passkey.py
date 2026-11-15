"""The web app's Tempo passkey wallet: built on viem's WebAuthn accounts, aimed at the deployed Moderato escrow, and
reachable from the Hire form. (The live flow was run in a browser on Moderato on 1 Oct 2026: faucet, approve, post.)"""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def test_passkey_wallet_uses_viem_webauthn_on_moderato():
    js = (WEB / "tempo.js").read_text(encoding="utf-8")
    assert "WebAuthnP256.createCredential" in js and "Account.fromWebAuthnP256" in js and "tempoModerato" in js
    assert "tempo_fundAddress" in js
    from knos.jobs import tempo
    assert '"0x888d39bB186cC718481E98080Bdb5fd8Df27Ab49"' in js and tempo.PATH_USD.lower() in js.lower()


def test_the_hire_form_offers_the_passkey():
    assert 'id="post-passkey"' in (WEB / "index.html").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'import("./tempo.js")' in app and "passkeyAccount" in app
