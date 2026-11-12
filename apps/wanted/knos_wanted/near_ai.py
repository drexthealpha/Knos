"""Private AI on NEAR AI Cloud for each order: agent A writes its code with one model call, and the reviewer checks the
code that passed the locked test with a second. At most two model calls an order. The reviewer can only make a verdict
stricter (it may reject a pass; it can never turn a fail into a pass).

The model is deepseek-ai/DeepSeek-V4.1-Flash-1017, served from NEAR AI's attested TEEs; its attestation is verified as
NEAR AI's docs describe (near_attest.verify_model) before a page says "private", and each answer's signature is checked
against the verified signer (near_attest.check_signature). The fallback is moonshotai/kimi-k2.6; an answer from it says
whether its attestation verified. max_tokens 800, the JSON field "approve" first, answers cached by the sha256 of their
input.

The key is NEAR_AI_API_KEY (Render's environment; never printed, logged or returned). Its credit is $10 that cannot be
topped up: 10 calls an hour per visitor, 200 a day in all, and at $8 spent no more calls: the fixed program and the
locked test alone decide, and the answer says so. Spend is counted from each answer's token counts at the listed prices,
in a ledger that a scheduled CI job copies to the gh-pages branch (near-ai-ledger.json); a restarted server starts from
that copy, so a deploy cannot reset it. No call runs in CI or tests: without the key (or with KNOS_NEAR_AI_OFF set) the
model steps are off and say so."""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

BASE = os.environ.get("NEAR_AI_BASE", "https://cloud-api.near.ai/v1").rstrip("/")
MODELS = ("deepseek-ai/DeepSeek-V4.1-Flash-1017", "moonshotai/kimi-k2.6")
PRICE = {"deepseek-ai/DeepSeek-V4.1-Flash-1017": (0.30e-6, 1.20e-6), "moonshotai/kimi-k2.6": (0.81e-6, 3.85e-6)}   # USD per input, output token (GET /v1/models, 12 Nov 2026)
MAX_TOKENS = 800
CREDIT_USD = 10.0
STOP_AT_USD = 8.0
PER_VISITOR_HOUR = 10
PER_DAY = 200
LEDGER = Path(os.environ.get("KNOS_NEAR_AI_LEDGER") or (Path(os.environ.get("TMPDIR") or "/tmp") / "knos-near-ai.json"))
SAVED = os.environ.get("KNOS_NEAR_AI_SAVED", "https://raw.githubusercontent.com/drexthealpha/Knos/gh-pages/near-ai-ledger.json")

_lock = threading.Lock()
_visits: dict[str, deque] = {}
_state = {"spent_usd": 0.0, "calls": 0, "day": "", "today": 0, "cache": {}, "seeded": None}


def _key() -> str:
    return "" if os.environ.get("KNOS_NEAR_AI_OFF") else os.environ.get("NEAR_AI_API_KEY", "")


def _load() -> None:
    try:
        _state.update(json.loads(LEDGER.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def _seed() -> None:
    """The ledger the scheduled CI job saved on the gh-pages branch: the larger spend and every cached answer, so a
    deploy starts where the last server ended. Only with the key (never in tests)."""
    if _state["seeded"] is not None or not _key():
        return
    _state["seeded"] = False
    try:
        with urllib.request.urlopen(urllib.request.Request(SAVED, headers={"User-Agent": "knos-ledger/1.0"}), timeout=10) as r:
            saved = json.loads(r.read())
        with _lock:
            _state["spent_usd"] = max(_state["spent_usd"], float(saved.get("spent_usd") or 0))
            _state["calls"] = max(_state["calls"], int(saved.get("calls") or 0))
            if saved.get("day") == _today() and int(saved.get("today") or 0) > (_state["today"] if _state["day"] == _today() else 0):
                _state.update(day=saved["day"], today=int(saved["today"]))
            for h, a in (saved.get("cache") or {}).items():
                _state["cache"].setdefault(h, a)
        _state["seeded"] = True
    except (urllib.error.URLError, OSError, ValueError, TypeError):
        pass


def _save() -> None:
    try:
        LEDGER.write_text(json.dumps(ledger()), encoding="utf-8")
    except OSError:
        pass


_load()


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def ledger() -> dict:
    """What the scheduled CI job saves: the spend, the call counts and the cached answers (no key, nothing private)."""
    return {k: _state[k] for k in ("spent_usd", "calls", "day", "today", "cache")}


def spent() -> tuple[float, str]:
    _seed()
    return round(_state["spent_usd"], 6), "the token counts of each answer at the listed prices, kept across deploys on the gh-pages branch"


def attestation(model: str = MODELS[0]) -> dict:
    from . import near_attest
    if not _key():
        return {"ok": False, "model": model, "why": "no NEAR AI key"}
    a = near_attest.verify_model(model)
    return {k: a.get(k) for k in ("ok", "model", "url", "sha256", "gateway", "signers", "candidates", "checked", "not_checked", "why")}


def status() -> dict:
    s, src = spent()
    return {"on": bool(_key()), "model": MODELS[0], "fallback": MODELS[1], "max_tokens": MAX_TOKENS, "calls_per_order": 2,
            "spent_usd": s, "spent_from": src, "stop_at_usd": STOP_AT_USD, "credit_usd": CREDIT_USD, "calls": _state["calls"],
            "calls_today": _state["today"] if _state["day"] == _today() else 0, "per_day": PER_DAY,
            "per_visitor_hour": PER_VISITOR_HOUR, "cached_answers": len(_state["cache"])}


def _call(kind: str, inp: dict, system: str, user: str, visitor: str) -> dict:
    """One model call (or its cached answer): the limits, the spend, the fallback model, the call id, the model's
    attestation and the answer's signature. `text` is the model's answer; `note` says why there is none."""
    base = {"kind": kind, "model": MODELS[0], "text": None, "cached": False}
    if not _key():
        return {**base, "note": "no NEAR AI key"}
    _seed()
    h = hashlib.sha256(json.dumps({"kind": kind, **inp}, sort_keys=True).encode()).hexdigest()
    with _lock:
        hit = _state["cache"].get(h)
        if hit:
            return {**hit, "cached": True, "input_sha256": h}
        s, _ = round(_state["spent_usd"], 6), ""
        if s >= STOP_AT_USD:
            return {**base, "note": f"the AI budget is used (${s:.2f} of ${CREDIT_USD:.0f}): the fixed program and the locked test alone decided"}
        if _state["day"] != _today():
            _state.update(day=_today(), today=0)
        if _state["today"] >= PER_DAY:
            return {**base, "note": f"today's {PER_DAY} model calls are used: the fixed program and the locked test alone decided"}
        q = _visits.setdefault(visitor or "-", deque())
        while q and time.time() - q[0] > 3600:
            q.popleft()
        if len(q) >= PER_VISITOR_HOUR:
            return {**base, "note": f"{PER_VISITOR_HOUR} model calls an hour per visitor are used: the fixed program and the locked test alone decided"}
        q.append(time.time())
        _state["today"] += 1
        _state["calls"] += 1
    from . import near_attest
    t0, last = time.time(), ""
    for model in MODELS:   # the fallback only when the first model gives no answer; one answer either way
        att = near_attest.verify_model(model)   # preflight: the attestation verified before the completion is sent
        # thinking off: the reasoning of DeepSeek V4.1 Flash otherwise uses all 800 tokens before any answer (12 Nov)
        body = json.dumps({"model": model, "max_tokens": MAX_TOKENS, "temperature": 0, "chat_template_kwargs": {"thinking": False},
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
        req = urllib.request.Request(BASE + "/chat/completions", method="POST", data=body,
                                     headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json", "User-Agent": "knos-agent/1.0",
                                              "x-no-aliasing": "true", "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            out = json.loads(raw)
        except urllib.error.HTTPError as e:
            last = f"{model} answered {e.code}"
            continue
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = f"{model} did not answer ({type(e).__name__})"
            continue
        u = out.get("usage") or {}
        tin, tout = int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
        pin, pout = PRICE[model]
        cost = round(tin * pin + tout * pout, 6)
        with _lock:
            _state["spent_usd"] = round(_state["spent_usd"] + cost, 6)
        choice = (out.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        if isinstance(text, list):
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        sig = near_attest.check_signature(str(out.get("id") or ""), model, body, raw, _key(), att) if att.get("ok") else \
            {"ok": False, "why": "the model's attestation did not verify"}
        ans = {"kind": kind, "model": model, "text": text, "id": out.get("id"), "tokens_in": tin, "tokens_out": tout, "cost_usd": cost,
               "finish": choice.get("finish_reason"), "seconds": round(time.time() - t0, 1), "at": int(time.time()),
               "private": bool(att.get("ok") and sig.get("ok") and sig.get("model_bound")), "attestation": {"ok": att.get("ok"), "url": att.get("url"), "sha256": att.get("sha256"),
                                                                                 "why": att.get("why"), "not_checked": att.get("not_checked")},
               "signature": sig}
        with _lock:
            if text:
                _state["cache"][h] = ans
            _save()
        return {**ans, "cached": False, "input_sha256": h}
    with _lock:
        _save()
    return {**base, "note": f"no model answered ({last}): the fixed program and the locked test alone decided"}


REVIEW = ("You review code that has already passed a locked test written before the code. You may only reject it. "
          "Reject if the code games the test instead of doing what the claim says: it reads or inspects the test, hard-codes "
          "expected answers, special-cases the test's inputs, or does not use the method the claim names. Otherwise approve. "
          'Do not think aloud. Answer with JSON only, approve first: {"approve": true or false, "reason": "at most 25 words"}.')
WRITE = ("You are agent A. Write the Python module solution.py that the locked test below imports, implementing the "
         "paper's method the claim names, so that the test passes. Do not read, open or inspect the test file, and do not "
         "special-case its inputs. Do not think aloud. Answer with the code only, in one ```python block.")


def review(claim: str, quote: str, test: str, code: str, visitor: str = "") -> dict:
    """The reviewer's answer for code that passed its locked test: `approve` False rejects, True lets the pass stand,
    None when no model answered (the locked test alone decides, and `note` says why)."""
    a = _call("review", {"claim": claim, "quote": quote, "test": test[:8000], "code": code[:8000]}, REVIEW,
              f"Claim: {quote}\n\nLocked test ({claim}):\n{test[:8000]}\n\nCode that passed it:\n{code[:8000]}", visitor)
    text = a.get("text") or ""
    approve, reason = None, ""
    try:
        j = json.loads(text[text.index("{"): text.rindex("}") + 1])
        approve = j.get("approve") if isinstance(j.get("approve"), bool) else None
        reason = str(j.get("reason") or "")[:200]
    except ValueError:   # cut short or wrapped: the approve field and the reason as far as they came
        m = re.search(r'"approve"\s*:\s*(true|false)', text)
        approve = (m.group(1) == "true") if m else None
        r = re.search(r'"reason"\s*:\s*"([^"]*)', text)
        reason = (r.group(1) if r else "")[:200]
    out = {k: v for k, v in a.items() if k != "text"}
    out.update(approve=approve, reason=reason or ("" if approve is not None else "the answer was not the JSON asked for"))
    if approve is None and not out.get("note"):
        out["note"] = "the model's answer could not be read: the locked test alone decided"
    return out


def write_code(claim: str, quote: str, test: str, visitor: str = "") -> dict:
    """Agent A's code for a claim, written by the model: `code` is the module, or None with `note` saying why (the
    fixed program is then used and the order says so)."""
    a = _call("write", {"claim": claim, "quote": quote, "test": test[:8000]}, WRITE,
              f"Claim: {quote}\n\nThe locked test ({claim}), which imports solution:\n{test[:8000]}", visitor)
    text = a.get("text") or ""
    m = re.search(r"```(?:python)?\n(.*?)```", text, re.S) or re.search(r"```(?:python)?\n(.*)", text, re.S)
    code = (m.group(1) if m else "").strip()
    out = {k: v for k, v in a.items() if k != "text"}
    out["code"] = code + "\n" if code else None
    if not code and not out.get("note"):
        out["note"] = "the model's answer held no code" + (" (it stopped at max_tokens)" if a.get("finish") == "length" else "")
    return out
