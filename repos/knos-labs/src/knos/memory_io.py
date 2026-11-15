"""This repo's Sibyl memory as one portable file, and the continuity note a next session starts from.

    export_doc(client, repo)   every entity (proof_claim, proof_outcome, proof_rule, repo_rule, tamper, notes, ...)
                               as versioned JSON: sorted, with the sha256 of its entities
    import_doc(client, doc)    merge it back; idempotent (an identical entity is left alone)
    note(client, text)         the continuity note: what the next session on this repo should know first
    last_note(client)          the latest one, shown by `knos memory export` and at session start
"""

from __future__ import annotations

import hashlib
import json
import time

SCHEMA = "knos.memory/1"
CONTINUITY = "continuity"


def _body(row: dict):
    body = row.get("body")
    if isinstance(body, str):
        try:
            return json.loads(body)
        except ValueError:
            return {"text": body}
    return body


def _digest(entities: list[dict]) -> str:
    return hashlib.sha256(json.dumps(entities, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def entities(client) -> list[dict]:
    rows = [{"category": r["category"], "name": r["name"], "status": r.get("status"), "body": _body(r)}
            for r in client.list_entities(None, limit=10000)]
    return sorted(rows, key=lambda e: (e["category"], e["name"]))


def export_doc(client, repo: str = "") -> dict:
    ents = entities(client)
    last = last_note(client)
    return {"schema": SCHEMA, "repo": repo, "exported_at": time.time(),
            "continuity": last["text"] if last else None, "count": len(ents),
            "sha256": _digest(ents), "entities": ents}


def import_doc(client, doc: dict) -> tuple[int, int]:
    """Merge `doc` into the store. Returns (written, unchanged). Raises ValueError on a wrong schema or sha256."""
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"not a Knos memory export (schema {doc.get('schema')!r}, expected {SCHEMA!r})")
    ents = doc.get("entities") or []
    if _digest(ents) != doc.get("sha256"):
        raise ValueError("the export's sha256 does not match its entities: it was changed or truncated")
    have = {(e["category"], e["name"]): e for e in entities(client)}
    written = 0
    for e in ents:
        old = have.get((e["category"], e["name"]))
        if old and old["body"] == e["body"] and old["status"] == e["status"]:
            continue
        client.set_entity(e["category"], e["name"], e["body"], status=e.get("status"))
        written += 1
    return written, len(ents) - written


def note(client, text: str, at: float | None = None) -> dict:
    at = at or time.time()
    body = {"text": text.strip(), "at": at}
    client.set_entity(CONTINUITY, f"{at:017.6f}", body, status="active")
    return body


def last_note(client) -> dict | None:
    rows = [_body(r) for r in client.list_entities(CONTINUITY, limit=10000)]
    rows = [b for b in rows if isinstance(b, dict) and b.get("text")]
    return max(rows, key=lambda b: b.get("at", 0)) if rows else None
