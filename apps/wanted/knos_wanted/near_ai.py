"""The AI reviewer on NEAR AI Cloud: one model call at most per order, after the locked test passed, and it can only
make the verdict stricter (it may reject a pass; it can never turn a fail into a pass).

The key is NEAR_AI_API_KEY (Render's environment; never printed, logged or returned). Its credit is $10 that cannot be
topped up, so: model anthropic/claude-haiku-5-5 (fallback google/gemini-2.5-flash-lite), max_tokens 400, answers cached
by the sha256 of their input, 10 calls an hour per visitor and 200 a day in all, and at $8 spent no more calls: the fixed
rule (the locked test alone) decides and the answer says so. Spend is counted from the token counts of each response at
the listed prices; when NEAR AI Cloud answers its balance for the key, that figure is used instead. No call runs in CI or
tests: without the key (or with KNOS_NEAR_AI_OFF set) the reviewer is off and says so."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

BASE = os.environ.get("NEAR_AI_BASE", "https://cloud-api.near.ai/v1").rstrip("/")
MODELS = ("anthropic/claude-haiku-5-5", "google/gemini-2.5-flash-lite")
PRICE = {"anthropic/claude-haiku-5-5": (0.10e-6, 0.50e-6), "google/gemini-2.5-flash-lite": (0.10e-6, 0.40e-6)}   # USD per input, output token (GET /v1/models, 12 Nov 2026)
MAX_TOKENS = 400
CREDIT_USD = 10.0
STOP_AT_USD = 8.0
PER_VISITOR_HOUR = 10
PER_DAY = 200
LEDGER = Path(os.environ.get("KNOS_NEAR_AI_LEDGER") or (Path(os.environ.get("TMPDIR") or "/tmp") / "knos-near-ai.json"))

_lock = threading.Lock()
_visits: dict[str, deque] = {}
_state = {"spent_usd": 0.0, "calls": 0, "day": "", "today": 0, "cache": {}, "balance_usd": None, "balance_at": 0.0, "attestation": None}


def _key() -> str:
    return "" if os.environ.get("KNOS_NEAR_AI_OFF") else os.environ.get("NEAR_AI_API_KEY", "")


def _load() -> None:
    try:
        _state.update(json.loads(LEDGER.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def _save() -> None:
    try:
        LEDGER.write_text(json.dumps({k: _state[k] for k in ("spent_usd", "calls", "day", "today", "cache")}), encoding="utf-8")
    except OSError:
        pass


_load()


def _get(path: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + _key(), "User-Agent": "knos-reviewer/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _balance() -> float | None:
    """The key's remaining credit as NEAR AI Cloud reports it (free GETs), read at most every 10 minutes; None when the
    key may not read it."""
    if time.time() - _state["balance_at"] < 600:
        return _state["balance_usd"]
    _state["balance_at"] = time.time()
    try:
        me = _get("/users/me")
        orgs = me.get("organizations") or me.get("orgs") or []
        org = (orgs[0].get("id") if orgs and isinstance(orgs[0], dict) else None) or me.get("organization_id") or me.get("org_id")
        if not org:
            return None
        b = _get(f"/organizations/{org}/usage/balance")
        for k in ("balance_usd", "balance", "remaining_usd", "remaining", "credits_usd"):
            if isinstance(b.get(k), (int, float, str)):
                v = float(b[k])
                _state["balance_usd"] = v / 1e6 if v > 1000 else v   # some answers are in micro-dollars
                return _state["balance_usd"]
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError):
        return None
    return None


def spent() -> tuple[float, str]:
    """Dollars spent so far and where the figure comes from."""
    b = _balance() if _key() else None
    if b is not None and 0 <= b <= CREDIT_USD:
        return max(round(CREDIT_USD - b, 6), _state["spent_usd"]), "NEAR AI Cloud's balance for the key"
    return round(_state["spent_usd"], 6), "the token counts of each answer at the listed prices"


def attestation(model: str = MODELS[0]) -> dict:
    """NEAR AI Cloud's attestation report for the model (a free GET), read once: its sha256 and what it holds, or why
    there is none."""
    if _state["attestation"] is not None:
        return _state["attestation"]
    if not _key():
        return {"ok": False, "why": "no NEAR AI key"}
    try:
        raw = json.dumps(_get(f"/attestation/report?model={urllib.request.quote(model, safe='')}", timeout=30), sort_keys=True)
        rep = json.loads(raw)
        _state["attestation"] = {"ok": True, "model": model, "sha256": hashlib.sha256(raw.encode()).hexdigest(), "at": int(time.time()),
                                 "holds": sorted(rep.keys())[:12] if isinstance(rep, dict) else [],
                                 "url": f"{BASE}/attestation/report?model={model}"}
    except urllib.error.HTTPError as e:
        _state["attestation"] = {"ok": False, "model": model, "why": f"NEAR AI Cloud answered {e.code} for this model's attestation report"}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "model": model, "why": f"not read: {type(e).__name__}"}
    return _state["attestation"]


def status() -> dict:
    s, src = spent()
    return {"on": bool(_key()), "model": MODELS[0], "fallback": MODELS[1], "max_tokens": MAX_TOKENS, "spent_usd": s, "spent_from": src,
            "stop_at_usd": STOP_AT_USD, "credit_usd": CREDIT_USD, "calls": _state["calls"], "calls_today": _state["today"] if _state["day"] == _today() else 0,
            "per_day": PER_DAY, "per_visitor_hour": PER_VISITOR_HOUR, "cached_answers": len(_state["cache"])}


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


SYSTEM = ("You review code that has already passed a locked test written before the code. You may only reject it. "
          "Reject if the code games the test instead of doing what the claim says: it reads or inspects the test, hard-codes "
          "expected answers, special-cases the test's inputs, or does not use the method the claim names. Otherwise approve. "
          'Do not think aloud. Answer with JSON only, approve first: {"approve": true or false, "reason": "at most 25 words"}.')


def review(claim: str, quote: str, test: str, code: str, visitor: str = "") -> dict:
    """The reviewer's answer for code that passed its locked test. `approve` is False to reject, True to let the pass
    stand, None when no model answered (the fixed rule decides, and `note` says why)."""
    base = {"model": MODELS[0], "approve": None, "cached": False}
    if not _key():
        return {**base, "note": "no NEAR AI key: the locked test alone decided"}
    inp = json.dumps({"claim": claim, "quote": quote, "test": test[:8000], "code": code[:8000]}, sort_keys=True)
    h = hashlib.sha256(inp.encode()).hexdigest()
    with _lock:
        hit = _state["cache"].get(h)
        if hit:
            return {**hit, "cached": True, "input_sha256": h}
        s, src = spent()
        if s >= STOP_AT_USD:
            return {**base, "note": f"the AI budget is used (${s:.2f} of ${CREDIT_USD:.0f} by {src}): the fixed rule decided, the locked test alone"}
        if _state["day"] != _today():
            _state.update(day=_today(), today=0)
        if _state["today"] >= PER_DAY:
            return {**base, "note": f"today's {PER_DAY} AI reviews are used: the fixed rule decided, the locked test alone"}
        q = _visits.setdefault(visitor or "-", deque())
        while q and time.time() - q[0] > 3600:
            q.popleft()
        if len(q) >= PER_VISITOR_HOUR:
            return {**base, "note": f"{PER_VISITOR_HOUR} AI reviews an hour per visitor are used: the fixed rule decided, the locked test alone"}
        q.append(time.time())
        _state["today"] += 1
        _state["calls"] += 1
    body_user = f"Claim: {quote}\n\nLocked test ({claim}):\n{test[:8000]}\n\nCode that passed it:\n{code[:8000]}"
    t0 = time.time()
    last = ""
    for model in MODELS:   # the fallback only when the first model gives no answer; one answer per order either way
        req = urllib.request.Request(BASE + "/chat/completions", method="POST",
                                     headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json", "User-Agent": "knos-reviewer/1.0"},
                                     data=json.dumps({"model": model, "max_tokens": MAX_TOKENS, "temperature": 0,
                                                      "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": body_user}]}).encode())
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                out = json.loads(r.read())
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
        if isinstance(text, list):   # some answers come as parts
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        try:
            j = json.loads(text[text.index("{"): text.rindex("}") + 1])
            approve = j.get("approve") if isinstance(j.get("approve"), bool) else None
            reason = str(j.get("reason") or "")[:200]
        except ValueError:   # cut short or wrapped: the approve field and the reason as far as they came
            import re
            a = re.search(r'"approve"\s*:\s*(true|false)', text)
            approve = (a.group(1) == "true") if a else None
            m = re.search(r'"reason"\s*:\s*"([^"]*)', text)
            reason = (m.group(1) if m else "")[:200] or "the answer was not the JSON asked for"
        ans = {"model": model, "approve": approve, "reason": reason, "tokens_in": tin, "tokens_out": tout, "cost_usd": cost,
               "seconds": round(time.time() - t0, 1), "at": int(time.time()), "id": out.get("id"),
               "finish": choice.get("finish_reason"), "chars": len(text)}
        if approve is None:
            ans["note"] = "the model's answer could not be read: the fixed rule decided, the locked test alone"
        with _lock:
            if approve is not None:
                _state["cache"][h] = ans
            _save()
        return {**ans, "cached": False, "input_sha256": h}
    with _lock:
        _save()
    return {**base, "note": f"no model answered ({last}): the fixed rule decided, the locked test alone"}
