"""outcome.yaml: read it, check it against schemas/outcome.schema.json and the rules a schema cannot say, hash it,
and derive what the escrow pins from it (one knos_pay order per tier, each with its own terms).

The hash. `spec_hash` is sha256 of the canonical JSON of the spec as read (keys sorted, no spaces, ASCII), so a
re-indented file or a new comment keeps its hash and any change of a value does not. Both parties sign that hash
(`knos.outcomes.sign`), each tier's terms carry it, and an order stores the sha256 of its terms: a spec edited after
funding gives other terms, so its tokens name another terms hash and knos_pay refuses them (error 87) whatever the
workflow says.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import yamlish

SCHEMA_PATH = Path(__file__).with_name("outcome.schema.json")     # the same bytes as schemas/outcome.schema.json (a test holds them equal)
ORDER_MIN_WHOLE = 5            # knos_pay ORDER_MIN_AMOUNT: 5.00 whole units
MAX_TERMS = 600                # knos_pay MAX_TERMS
DEFAULT_SHARE = 0.2


class SpecError(ValueError):
    """The spec does not hold: `problems` lists every rule it breaks, each in words."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---- a JSON Schema reader for the keywords outcome.schema.json uses ---------------------------------------------------
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool}


def _is(kind: str, v: Any) -> bool:
    if kind == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if kind == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TYPES[kind])


def check_schema(v: Any, s: dict, root: dict, at: str = "") -> list[str]:
    """Every way `v` breaks the schema `s` (a subset of draft 2020-12: type, const, enum, pattern, minLength,
    maxLength, minimum, maximum, exclusiveMinimum, exclusiveMaximum, required, properties, additionalProperties false,
    items, minItems, maxItems, $ref to #/$defs, allOf)."""
    where = at or "the spec"
    if "$ref" in s:
        name = s["$ref"].split("/")[-1]
        return check_schema(v, root["$defs"][name], root, at)
    out: list[str] = []
    for sub in s.get("allOf", []):
        out += check_schema(v, sub, root, at)
    if "const" in s and v != s["const"]:
        return out + [f"{where} must be {s['const']!r}"]
    if "enum" in s and v not in s["enum"]:
        return out + [f"{where} must be one of {', '.join(map(str, s['enum']))}"]
    kind = s.get("type")
    if kind and not _is(kind, v):
        return out + [f"{where} must be {'an' if kind[0] in 'aeiou' else 'a'} {kind}"]
    if isinstance(v, str):
        if "pattern" in s and not re.search(s["pattern"], v):
            out.append(f"{where} ({v!r}) is not in the form {s['pattern']}")
        if len(v) < s.get("minLength", 0) or len(v) > s.get("maxLength", 10 ** 9):
            out.append(f"{where} has the wrong length")
    if _is("number", v):
        if "minimum" in s and v < s["minimum"]:
            out.append(f"{where} must be at least {s['minimum']}")
        if "maximum" in s and v > s["maximum"]:
            out.append(f"{where} must be at most {s['maximum']}")
        if "exclusiveMinimum" in s and v <= s["exclusiveMinimum"]:
            out.append(f"{where} must be more than {s['exclusiveMinimum']}")
        if "exclusiveMaximum" in s and v >= s["exclusiveMaximum"]:
            out.append(f"{where} must be less than {s['exclusiveMaximum']}")
    if isinstance(v, dict):
        for k in s.get("required", []):
            if k not in v:
                out.append(f"{where} has no `{k}`")
        props = s.get("properties", {})
        for k, x in v.items():
            if k in props:
                out += check_schema(x, props[k], root, f"{at}.{k}" if at else k)
            elif s.get("additionalProperties") is False:
                out.append(f"{where} has `{k}`, which the schema does not know")
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0):
            out.append(f"{where} needs at least {s['minItems']} item(s)")
        if len(v) > s.get("maxItems", 10 ** 9):
            out.append(f"{where} takes at most {s['maxItems']} items")
        if "items" in s:
            for i, x in enumerate(v):
                out += check_schema(x, s["items"], root, f"{at}[{i}]")
    return out


def utc(text: str) -> int:
    """`2026-10-13T16:00:00Z` as unix seconds."""
    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())


def problems(spec: Any) -> list[str]:
    """Every rule `spec` breaks; [] when it holds."""
    if not isinstance(spec, dict):
        return ["an outcome spec is a mapping (key: value lines)"]
    s = schema()
    out = check_schema(spec, s, s)
    if out:
        return out
    from . import metric
    try:
        metric.compile_formula(spec["metric"]["formula"])
    except metric.FormulaError as why:
        out.append(f"metric.formula: {why}")
    d = spec["data"]
    if d["source"] == "file" and not d.get("path"):
        out.append("data.path is needed when data.source is file")
    if d["source"] == "http" and not d.get("url"):
        out.append("data.url is needed when data.source is http")
    if d["source"] == "http" and d.get("ref"):
        out.append("data.ref is for a file in the repository, not an endpoint")
    if bool(d.get("arm_field")) != bool(d.get("treated_value")):
        out.append("data.arm_field and data.treated_value come together")
    if bool(spec["synthetic"]) != bool(d["synthetic"]):
        out.append("synthetic and data.synthetic must agree: made-up data are labelled synthetic everywhere")
    if utc(spec["window"]["end"]) <= utc(spec["window"]["start"]):
        out.append("window.end must be after window.start")
    tiers = spec["tiers"]
    names = [t["name"] for t in tiers]
    if len(set(names)) != len(names):
        out.append("each tier needs its own name")
    lifts = [t["min_lift"] for t in tiers]
    if any(b <= a for a, b in zip(lifts, lifts[1:])):
        out.append("tiers must rise: each tier's min_lift above the one before")
    if lifts and lifts[0] < spec["success"]["min_lift"]:
        out.append("the first tier's min_lift is below success.min_lift")
    total = round(sum(micro(t["amount"]) for t in tiers))
    if total != micro(spec["price"]["cap"]):
        out.append(f"the tiers add up to {total / 1e6:g} and the cap is {spec['price']['cap']:g}: the cap is the total escrowed, so they must be equal")
    if any(abs(t["amount"] * 1_000_000 - round(t["amount"] * 1_000_000)) > 1e-6 for t in tiers):
        out.append("tier amounts have at most 6 decimals")
    if spec["escrow"]["cluster"] not in ("devnet", "localnet"):
        out.append("escrow.cluster: devnet or localnet only")
    for t in tiers:
        if len(terms_bytes(spec, tiers.index(t), _hash=("0" * 64))) > MAX_TERMS:
            out.append(f"tier {t['name']}: its terms are longer than {MAX_TERMS} bytes")
    return out


def validate(spec: Any) -> dict:
    """`spec` when it holds; SpecError listing every problem otherwise."""
    found = problems(spec)
    if found:
        raise SpecError(found)
    return spec


def load(path: str | Path) -> dict:
    """Read and check an outcome.yaml (or .json)."""
    return validate(yamlish.loads(Path(path).read_text(encoding="utf-8")))


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def spec_hash(spec: dict) -> str:
    """sha256 (hex) of the spec's canonical JSON."""
    return hashlib.sha256(canonical(spec)).hexdigest()


def micro(whole: float) -> int:
    """Whole units (5.25) as millionths (5_250_000)."""
    return int(round(whole * 1_000_000))


def control_share(spec: dict) -> float:
    return float(spec["control"].get("share", DEFAULT_SHARE))


def _num(x: float) -> str:
    return format(x, ".6g")


def terms(spec: dict, k: int, _hash: str | None = None) -> dict:
    """The terms of tier k's order: what knos_pay hashes and stores. The spec's hash, the tier and its bar."""
    t = spec["tiers"][k]
    return {"v": 1, "kind": "outcome", "spec": _hash or spec_hash(spec), "tier": k, "name": t["name"], "min_lift": _num(t["min_lift"]),
            "confidence": _num(spec["success"]["confidence"]), "lift": spec["metric"]["lift"], "synthetic": bool(spec["synthetic"])}


def terms_bytes(spec: dict, k: int, _hash: str | None = None) -> bytes:
    """Canonical JSON of tier k's terms, exactly as knos.settle.v2.pay.terms_json writes them."""
    return json.dumps(terms(spec, k, _hash), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def terms_hash(spec: dict, k: int) -> bytes:
    return hashlib.sha256(terms_bytes(spec, k)).digest()


def lock(spec: dict, measurement_commit: str = "") -> dict:
    """What is fixed at funding, in the shape the cheat checks compare (knos.cheats.scan_outcome takes it)."""
    return {"spec_hash": spec_hash(spec), "window": dict(spec["window"]), "salt": spec["control"]["salt"],
            "control_share": control_share(spec), "measurement_commit": measurement_commit, "data_hashes": {}}
