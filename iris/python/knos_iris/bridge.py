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


def _repo(value: object) -> str:
    """A repository as "owner/name", lower case (GitHub's names ignore case): from a string or {"full_name": ...}."""
    if isinstance(value, dict):
        value = value.get("full_name")
    return value.strip().lower() if isinstance(value, str) else ""


def _loads(text: str) -> object:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def repo_mismatch(brief_id: str, brief_json: str, proof_json: str) -> str:
    """Why a proof is refused for naming another repository than the locked brief's, or "" when it is not.
    The brief's repository is its own "repository" field, else its id "github:<owner>/<repo>". The proof's is the
    body's "repository", else its payload's (a check run's webhook body carries repository.full_name). A brief or a
    proof that names none is not refused here: the referee still needs the exact check the brief names."""
    brief = _loads(brief_json)
    brief = brief if isinstance(brief, dict) else {}
    want = _repo(brief.get("repository")) or (brief_id[len("github:"):].strip().lower() if brief_id.startswith("github:") else "")
    proof = _loads(proof_json)
    proof = proof if isinstance(proof, dict) else {}
    payload = proof.get("payload")
    payload = _loads(payload) if isinstance(payload, str) else payload
    got = _repo(proof.get("repository")) or (_repo(payload.get("repository")) if isinstance(payload, dict) else "")
    if not want or not got or want == got:
        return ""
    return f"the proof comes from {got}, and the brief is locked for {want}"


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


MODEL = "snowflake/snowflake-arctic-embed-s"     # 33M parameters, 384 numbers, MTEB retrieval 51.98 (its model card)
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "   # the model card's prefix, for queries only
_model = None


def _arctic():
    """The open embedding model, loaded once from the image's own copy (KNOS_EMBED_DIR, filled at build); None when the
    package or the files are missing, or KNOS_EMBED=hash asks for the hashed embedding."""
    global _model
    if _model is None:
        import os
        if os.environ.get("KNOS_EMBED", "arctic") == "hash":
            _model = False
        else:
            try:
                from fastembed import TextEmbedding
                _model = TextEmbedding(MODEL, cache_dir=os.environ.get("KNOS_EMBED_DIR") or None)   # the image sets HF_HUB_OFFLINE=1
            except Exception:  # noqa: BLE001 - no package, no files: the hashed embedding answers
                _model = False
    return _model or None


def embed_model() -> str:
    """Which embedding answers: the open model's name, or "hashed" when it is not there."""
    return MODEL if _arctic() else "hashed"


def embed(text: str, query: bool = False) -> str:
    """A 384-number embedding of a criterion, or with query=True of a proof: the open model (L2-normalised) when it is
    there, else hashed counts of the text's content words."""
    m = _arctic()
    if m is not None:
        vec = [float(x) for x in next(iter(m.embed([(QUERY_PREFIX if query else "") + text])))]
        n = math.sqrt(sum(x * x for x in vec)) or 1.0
        return ",".join(f"{x / n:.6f}" for x in vec)
    return embed_hashed(text)


def embed_hashed(text: str) -> str:
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
