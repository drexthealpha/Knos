"""What the IRIS tests need from iris/.env (or the environment): the password of _SYSTEM, and the two signing secrets.
Values are read, never printed."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"


def value(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    if ENV.is_file():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name:
                return v.strip()
    return ""


def auth(password: str | None = None) -> str:
    pw = value("IRIS_PASSWORD") if password is None else password
    return "Basic " + base64.b64encode(f"_SYSTEM:{pw}".encode()).decode()


def sign(body: bytes, secret: str | None = None) -> str:
    """GitHub's X-Hub-Signature-256 for this exact body."""
    key = (value("KNOS_WEBHOOK_SECRET") if secret is None else secret).encode()
    return "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()


def signed_verdict(verdict: dict, secret: str | None = None) -> dict:
    """The verdict with its "signature": HMAC-SHA256 of the verdict without that key, keys sorted, no spaces."""
    key = (value("KNOS_VERDICT_SECRET") if secret is None else secret).encode()
    body = json.dumps({k: v for k, v in verdict.items() if k != "signature"}, sort_keys=True, separators=(",", ":"))
    return {**verdict, "signature": "sha256=" + hmac.new(key, body.encode(), hashlib.sha256).hexdigest()}


def headers(data: bytes | None = None, kind: str = "") -> dict:
    """Authorization, JSON, and for a check run the body's signature."""
    h = {"Authorization": auth(), "Content-Type": "application/json"}
    if data is not None and kind == "checkrun":
        h["X-Hub-Signature-256"] = sign(data)
    return h
