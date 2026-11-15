"""One result shape for the three tests of the referee, and the one way the referee writes to Knos Record."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..cheats import Finding


@dataclass
class Check:
    name: str                       # works | wanted | makeable
    passed: bool
    reasons: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    cheats: list[Finding] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["cheats"] = [f.to_dict() for f in self.cheats]
        return d


def record_module():
    """knos.record when this install has it (Knos Record), else None: the referee then decides the same and
    says in its evidence that nothing was recorded."""
    try:
        from .. import record  # type: ignore[attr-defined]
    except ImportError:
        return None
    return record if hasattr(record, "append") else None


def write(kind: str, payload: dict, *, domain: str = "", root=None, claim=None) -> dict | None:
    rec = record_module()
    if rec is None:
        return None
    kw = {"domain": domain, "root": root}
    if claim is not None:
        kw["claim"] = claim
    return rec.append(kind, payload, **kw)
