"""NEAR AI Cloud attestation, verified as NEAR AI's docs describe (docs.near.ai/cloud/verification, "Quote, Nonce, and
Signer Bindings" and "NEAR Model Attestations"), before any page says "private".

For a model: a fresh 32-byte nonce, GET /v1/attestation/report?model=...&provider=near&signing_algo=ecdsa (free, no
key), then for the gateway's evidence and every model candidate: the Intel TDX quote verified with dcap-qvl against
Intel's collateral, TDX debug mode off, the quote's report data binding the signing address and the nonce, the echoed
nonce, MRCONFIGID equal to 01 || sha256(app_compose) || 15 zero bytes, and the RTMR3 event log replayed to the quote's
RTMR3. A reply is then checked by its signature (GET /v1/signature/{id}): its text names the sha256 of the exact
request and response bytes, and the address recovered from the signature is a verified candidate's signing address.

GPU evidence (NVIDIA NRAS) is not checked here, and the page says so."""
from __future__ import annotations

import hashlib
import json
import secrets
import struct
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://cloud-api.near.ai/v1"
ACCEPTED_TCB = {"UpToDate"}
_cache: dict = {}


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _signing_identity(report: dict) -> bytes:
    algorithm = report["signing_algo"]
    identity = bytes.fromhex(report["signing_address"].removeprefix("0x"))
    if {"ecdsa": 20, "ed25519": 32}.get(algorithm) != len(identity):
        raise ValueError("unsupported signing identity")
    return identity


def replay_rtmr3(event_log) -> bytes:
    rtmr3 = bytes(48)
    for event in _json(event_log):
        if event.get("imr") != 3:
            continue
        digest = hashlib.sha384(struct.pack("<I", event["event_type"]) + b":" + event["event"].encode("utf-8") + b":"
                                + bytes.fromhex(event.get("event_payload") or "")).digest()
        if event.get("digest") and bytes.fromhex(event["digest"]) != digest:
            raise ValueError(f"digest mismatch for event {event['event']}")
        rtmr3 = hashlib.sha384(rtmr3 + digest).digest()
    return rtmr3


async def check_report(report: dict, nonce_hex: str) -> str:
    """The docs' check of one NEAR-operated report; returns the quote's TCB status or raises with what failed."""
    import dcap_qvl
    verified = await dcap_qvl.get_collateral_and_verify(bytes.fromhex(report["intel_quote"]))
    if verified.status not in ACCEPTED_TCB:
        raise ValueError(f"TCB status {verified.status} not accepted: {verified.advisory_ids}")
    quote = json.loads(verified.to_json())["report"]["TD10"]
    if bytes.fromhex(quote["td_attributes"])[0] & 1:
        raise ValueError("TDX debug mode is enabled")
    identity = _signing_identity(report)
    fingerprint = report.get("tls_cert_fingerprint")
    bound = hashlib.sha256(identity + bytes.fromhex(fingerprint)).digest() if fingerprint else identity.ljust(32, b"\0")
    if bytes.fromhex(quote["report_data"]) != bound + bytes.fromhex(nonce_hex):
        raise ValueError("report data does not bind the signer and nonce")
    if report["request_nonce"].lower() != nonce_hex.lower():
        raise ValueError("echoed nonce does not match")
    app_compose = _json(report["info"]["tcb_info"])["app_compose"]
    if bytes.fromhex(quote["mr_config_id"]) != b"\x01" + hashlib.sha256(app_compose.encode("utf-8")).digest() + bytes(15):
        raise ValueError("MRCONFIGID does not match app_compose")
    if replay_rtmr3(report["event_log"]) != bytes.fromhex(quote["rt_mr3"]):
        raise ValueError("event log does not match RTMR3")
    return verified.status


def verify_model(model: str, max_age: int = 3600) -> dict:
    """The model's attestation, fetched with a fresh nonce and verified (held an hour): ok, the verified signing
    addresses, the report's URL and sha256, and what was and was not checked."""
    hit = _cache.get(model)
    if hit and time.time() - hit["at"] < max_age:
        return hit
    import asyncio
    nonce = secrets.token_hex(32)
    q = {"model": model, "provider": "near", "signing_algo": "ecdsa", "nonce": nonce}
    url = f"{BASE}/attestation/report?" + urllib.parse.urlencode(q)
    out = {"model": model, "at": time.time(), "url": f"{BASE}/attestation/report?model={urllib.parse.quote(model, safe='')}",
           "checked": "Intel TDX quote (dcap-qvl), report data binding signer and nonce, MRCONFIGID, RTMR3 event log",
           "not_checked": "NVIDIA GPU evidence"}
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json", "x-no-aliasing": "true", "User-Agent": "knos-attest/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
        body = json.loads(raw)
        out["sha256"] = hashlib.sha256(raw).hexdigest()
        cands = body.get("model_attestations") or []
        if not cands:
            raise ValueError("no NEAR model evidence returned")

        async def run():
            g = await check_report(body["gateway_attestation"], nonce)
            ms = [(c["signing_address"].lower(), await check_report(c, nonce)) for c in cands]
            return g, ms
        g, ms = asyncio.run(run())
        out.update(ok=True, gateway=g, signers=sorted({a for a, _ in ms}), candidates=len(ms),
                   gateway_signer=str(body["gateway_attestation"].get("signing_address", "")).lower())
    except Exception as e:  # noqa: BLE001 - the page says what failed, and "private" is not claimed
        out.update(ok=False, why=f"{type(e).__name__}: {str(e)[:200]}")
    _cache[model] = out
    return out


def check_signature(chat_id: str, model: str, request_body: bytes, response_body: bytes, key: str, att: dict) -> dict:
    """The reply's signature, as NEAR AI's docs describe ("Response Signatures"): GET /v1/signature/{id} (a 404 is
    asked again for a few seconds), the EIP-191 signer recovered from its text equal to its signing_address, and the
    text equal to the exact bytes' hashes: "<model>:<request sha256>:<response sha256>" with a signer among the
    verified model reports for a model-signed reply (provider_tee, the only kind that binds the reply to the model's
    TEE), "<request sha256>:<response sha256>" with the verified gateway's signer for a gateway-signed one."""
    try:
        q = urllib.parse.urlencode({"signing_algo": "ecdsa"})
        req = urllib.request.Request(f"{BASE}/signature/{urllib.parse.quote(chat_id, safe='')}?{q}",
                                     headers={"Authorization": "Bearer " + key, "Accept": "application/json", "User-Agent": "knos-attest/1.0"})
        sig = None
        for n in range(4):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    sig = json.loads(r.read())
                if sig.get("text"):
                    break
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
            time.sleep(1.5 * (n + 1))
        if not sig or not sig.get("text"):
            return {"ok": False, "why": "no signature was available for this reply"}
        hashes = f"{hashlib.sha256(request_body).hexdigest()}:{hashlib.sha256(response_body).hexdigest()}"
        kind = sig.get("signature_kind")
        from eth_account import Account
        from eth_account.messages import encode_defunct
        who = Account.recover_message(encode_defunct(text=sig["text"]), signature=sig["signature"]).lower()
        if who != str(sig.get("signing_address", "")).lower():
            return {"ok": False, "kind": kind, "why": "the signature does not match its signing address"}
        if kind == "provider_tee":
            if sig["text"] != f"{model}:{hashes}" or who not in (att.get("signers") or []):
                return {"ok": False, "kind": kind, "why": "the model-signed text or signer does not match the verified model report"}
            return {"ok": True, "kind": kind, "signer": who, "model_bound": True}
        if kind == "gateway":
            if sig["text"] != hashes or who != att.get("gateway_signer"):
                return {"ok": False, "kind": kind, "why": "the gateway-signed text or signer does not match the verified gateway"}
            return {"ok": True, "kind": kind, "signer": who, "model_bound": False}
        return {"ok": False, "kind": kind, "why": "the signature's kind is not one the docs define"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "why": f"{type(e).__name__}: {str(e)[:160]}"}
