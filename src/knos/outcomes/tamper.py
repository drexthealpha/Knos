"""The cheat checks of a measurement: what was fixed at funding (the lock) against what the run sees now.

Each finding names a category that the cheat library and Knos Record use (knos.cheats; NOTES "REFEREE API"):

    spec_hash_changed       the spec's hash is not the one the lock (and the orders' terms) carry
    window_changed          the measurement window moved
    salt_changed            the control salt changed
    control_drift           the control share in the spec changed; or the observed share left its tolerance; or the
                            data's own arm field disagrees with the hash split (items moved between groups)
    measurement_code_drift  the measuring code is not the code the lock names (knos.outcomes' own hash)
    data_tampering          rows dated before the window differ from those seen at funding; or an item id is twice

When the cheat library (knos.cheats, agent REFEREE) is installed, its `scan_outcome` runs too and its findings are
added, so every rule it names applies to every measurement; this module's checks still run, so a measurement never
depends on that package being present.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Finding:
    rule: str
    category: str
    detail: str
    path: str = ""
    severity: str = "refuse"

    def to_dict(self) -> dict:
        return asdict(self)


def code_hash() -> str:
    """sha256 over this package's Python files (name and bytes, sorted): the measuring code's identity.

    What it is and is not. Computed by the code it names, so on its own it only catches an honest mistake (another
    version installed). The reusable workflow therefore computes the same hash with sha256sum, outside Python, before
    any of this package runs, and stops when it differs from the lock. The pin that binds is the vault's: an order
    pays only a token from prove.yml at the commit it pinned, and that commit names the measuring workflow and the
    measuring code. It covers knos/outcomes/*.py only, not the Python interpreter or the standard library."""
    h = hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob("*.py")):
        h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def check(funded: dict, now: dict, *, observed_share: float | None = None, tolerance: float = 0.02, duplicate_ids=(),
          arm_mismatches: int = 0) -> list[Finding]:
    """`funded` and `now` in the shape knos.cheats.scan_outcome takes: spec_hash, window {start, end}, salt,
    control_share, measurement_commit, data_hashes {name: sha256}."""
    out: list[Finding] = []
    if funded.get("spec_hash") != now.get("spec_hash"):
        out.append(Finding("outcome.spec_hash", "spec_hash_changed", f"the spec hashes to {now.get('spec_hash')}; it was {funded.get('spec_hash')} at funding"))
    if dict(funded.get("window") or {}) != dict(now.get("window") or {}):
        out.append(Finding("outcome.window", "window_changed", f"the window is {now.get('window')}; it was {funded.get('window')} at funding"))
    if funded.get("salt") != now.get("salt"):
        out.append(Finding("outcome.salt", "salt_changed", "the control salt is not the one committed at funding"))
    if funded.get("control_share") != now.get("control_share"):
        out.append(Finding("outcome.share", "control_drift", f"the control share is {now.get('control_share')}; it was {funded.get('control_share')} at funding"))
    if not funded.get("measurement_commit"):
        out.append(Finding("outcome.code", "measurement_code_drift", "the lock names no measuring code: a lock without one is refused"))
    elif funded.get("measurement_commit") != now.get("measurement_commit"):
        out.append(Finding("outcome.code", "measurement_code_drift", "the measuring code is not the code named at funding"))
    for name, digest in (funded.get("data_hashes") or {}).items():
        if (now.get("data_hashes") or {}).get(name) != digest:
            out.append(Finding("outcome.history", "data_tampering", f"{name}: the rows dated before the window changed after funding", path=name))
    if duplicate_ids:
        ids = list(duplicate_ids)
        out.append(Finding("outcome.duplicates", "data_tampering", f"{len(ids)} item id(s) appear twice, e.g. {ids[0]}"))
    share = now.get("control_share")
    if observed_share is not None and share is not None and abs(observed_share - share) > tolerance:
        out.append(Finding("outcome.drift", "control_drift", f"the observed control share is {observed_share:.4f}; the spec says {share} (tolerance {tolerance:.4f})"))
    if arm_mismatches:
        out.append(Finding("outcome.arm", "control_drift", f"{arm_mismatches} item(s) were handled in the other group than the hash put them in"))
    return out


def library(funded: dict, now: dict, tolerance: float) -> list[Finding]:
    """The cheat library's own outcome rules, when it is installed; [] when it is not."""
    try:
        from knos import cheats  # type: ignore[attr-defined]
        scan = cheats.scan_outcome
    except (ImportError, AttributeError):
        return []
    out = []
    for f in scan(funded, now, control_tolerance=tolerance):
        out.append(Finding(getattr(f, "rule", "library"), getattr(f, "category", "unknown"), getattr(f, "detail", ""), getattr(f, "path", ""),
                           getattr(f, "severity", "refuse")))
    return out


def merge(mine: list[Finding], theirs: list[Finding]) -> list[Finding]:
    """Both lists, one finding per (category, path) (this module's wording kept)."""
    seen = {(f.category, f.path) for f in mine}
    return mine + [f for f in theirs if (f.category, f.path) not in seen]


def refused(findings: list[Finding]) -> bool:
    return any(f.severity == "refuse" for f in findings)
