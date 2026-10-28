"""The calls the IRIS classes make into Knos, each one function returning JSON text (Embedded Python hands strings both ways)."""
from __future__ import annotations

import hashlib
import json
import math
import re

from knos import ready, verdict_gate


def check(brief_json: str) -> str:
    """knos.ready.check: Ready, or Not ready with the exact missing fields."""
    return json.dumps(ready.check(json.loads(brief_json)))


def criteria_hash(brief_json: str) -> str:
    return ready.criteria_hash(json.loads(brief_json))


def require(brief_json: str) -> str:
    """knos.ready.require: the brief's check when Ready; NotReady (raised) when not."""
    return json.dumps(ready.require(json.loads(brief_json)))


def read_verdict(text: str) -> str:
    """knos.verdict_gate.strict: one JSON object, or Refused."""
    return json.dumps(verdict_gate.strict(text))


def proof_hash(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---- the vector search's embedding -------------------------------------------------------------------------------
DIM = 384
WORD = re.compile(r"[a-z0-9]+")
# words every milestone line carries (the brief's own labels) and common function words: they say nothing of the milestone
STOP = set("a an the of in on at to for and or is be by with from under over least most target verifier ci test page result score".split())


def words(text: str) -> list[str]:
    out = []
    for w in WORD.findall(text.lower().replace("_", " ")):
        if w in STOP or len(w) < 2:
            continue
        out.append(w[:-1] if len(w) > 4 and w.endswith("s") else w)
    return out


def embed(text: str) -> str:
    """A 384-number embedding: hashed counts of the text's content words, signed and L2-normalised. Deterministic and
    offline, so a run anywhere needs no model download; the same function embeds criteria and queries."""
    v = [0.0] * DIM
    for g in words(text):
        h = hashlib.sha256(g.encode()).digest()
        i = int.from_bytes(h[:4], "big") % DIM
        v[i] += 1.0 if h[4] & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return ",".join(f"{x / n:.6f}" for x in v)


def criterion_text(brief_json: str) -> str:
    """One line per milestone, "key|text": what the vector table holds for the brief."""
    b = json.loads(brief_json)
    out = []
    for m in b.get("milestones") or []:
        ver = m.get("verifier") or {}
        out.append(f"{m.get('key')}|{m.get('name')}. target: {m.get('target')}. verifier: {ver.get('check') or ver.get('what') or ''}")
    return "\n".join(out)
