"""The referee's decision in replay mode is Knos's one rules referee (knos.referee_rules), the same code the hosted
server runs for a lab proof: it reads only structured fields, never the proof's free text, so text inside a proof
cannot steer it. In live mode the AI Hub agent decides and this contract is what its reply must match
(Knos.Iris.AI.Verdict). A recorded live answer in fixtures/replay wins over it."""
from __future__ import annotations

from knos.referee_rules import MODEL, decide, oru_to_observation

__all__ = ["MODEL", "decide", "oru_to_observation"]
