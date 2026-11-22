"""The model on a check's answer, only with a key the founder set on this server (ANTHROPIC_API_KEY, from the API credit
of the founder's plan): "Model alone" on a person's own input and "Ask about this result". Without the key the state is "off": the
chips keep their recorded model-alone answers and a new idea says the model needs a key. The key is never read into an
answer, a log line or a status field: /api/status says only "on" or "off".

Caps, checked before any call: 1 model call per check (its hash) and 200 per UTC day; past either, refused in one plain
sentence. `provider` is a stand-in for tests (a function prompt -> text); the default sends one Messages API request.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

MODEL = os.environ.get("KNOS_MODEL") or "claude-sonnet-5-5"
PER_CHECK, PER_DAY = 1, 200
NEEDS_KEY = "Model alone needs a model key"
_lock = threading.Lock()
_day: dict = {"day": None, "n": 0}
_per: dict[str, int] = {}


class Refused(ValueError):
    """A model call the caps or the missing key refuse, in one plain sentence."""


def state() -> str:
    return "on" if os.environ.get("ANTHROPIC_API_KEY") else "off"


def take(check_hash: str) -> None:
    """One model call for this check, or Refused."""
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with _lock:
        if _day["day"] != today:
            _day.update(day=today, n=0)
            _per.clear()
        if _day["n"] >= PER_DAY:
            raise Refused(f"The model's {PER_DAY} calls for today are used; it answers again after 00:00 UTC.")
        if _per.get(check_hash, 0) >= PER_CHECK:
            raise Refused(f"This result already had its {PER_CHECK} model call.")
        _day["n"] += 1
        _per[check_hash] = _per.get(check_hash, 0) + 1


def _anthropic(prompt: str) -> str:
    from knos import anthropic_http
    try:
        return anthropic_http.messages(prompt, MODEL)
    except anthropic_http.NoKey:
        raise Refused(NEEDS_KEY) from None
    except Exception as why:  # noqa: BLE001 - said in one sentence, never the request or the key
        raise Refused(f"The model did not answer ({type(why).__name__}).") from None


def ask(prompt: str, check_hash: str, provider=None) -> str:
    if provider is None and state() != "on":
        raise Refused(NEEDS_KEY)
    take(check_hash)
    return (provider or _anthropic)(prompt)


def follow_up(rep: dict, question: str, provider=None) -> dict:
    """One question about a result, answered from the card's own data and sources only, citing them as [source N]."""
    q = " ".join(str(question or "").split())[:400]
    if not q:
        raise Refused("Ask one question about this result.")
    rows = (rep.get("open_demand") or {}).get("rows") or []
    sources = [f"[source {i}] {r.get('name')}: {r.get('value')} {r.get('unit')}" + (f" ({r['link']})" if r.get("link") else "")
               for i, r in enumerate(rows[:20], 1)]
    card = {k: rep.get(k) for k in ("idea", "place", "decision")}
    prompt = ("Answer one question about this demand check using only the data below. Cite every fact as [source N] with the "
              "source it came from; say plainly when the data does not answer it.\n\nCARD: " + json.dumps(card, default=str)[:6000]
              + "\n\nSOURCES:\n" + "\n".join(sources) + f"\n\nQUESTION: {q}")
    text = ask(prompt, str(rep.get("hash") or ""), provider)
    cites = sorted({int(n) for n in re.findall(r"\[source (\d+)\]", text)})
    return {"answer": text.strip(), "cites": cites, "model": "stub" if provider else MODEL}
