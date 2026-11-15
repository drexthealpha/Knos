"""MOCK (synthetic, not real Qloo data): a local MCP stdio server with the SAME ten tool names and the same result
envelope as Qloo's canonical `qloo mcp` (@qloo/qloo-harness 0.1.26), answering with synthetic bodies.

The older MCP flow (demand.py, buyer.py) runs on this server when no Qloo credential is configured (`qloo_capabilities` reports
`adapter.ready: false`), and the tests use it as the fake MCP server. It is never real Qloo data:

- every envelope carries `"_mock": MOCK_LABEL`, every name ends in "(synthetic)", every id starts with "mock-";
- values come from a hash of the request, so the same input gives the same answer;
- names that are not ids come back as `needs_input` with candidates, as the real resolver does for an ambiguous
  name, so the "user confirms the match" step is exercised exactly as in live mode.

Shapes follow the harness's own result builders (dist/qloo-tools.js of @qloo/qloo-harness 0.1.26: output(),
needsInput(), compactEntity(), compactTag(), resolveEntities()) and its MCP tool schemas (`qloo mcp` tools/list,
read 14 Oct 2026). Run as a server:  python -m knos_wanted.mock_mcp
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from datetime import date, timedelta

from .geo import encode

MOCK_LABEL = "MOCK (synthetic, not real Qloo data)"
SERVER_NAME = "knos-qloo-mock"
SCHEMA_VERSION = "1.0-preview.1"
INSIGHTS_TYPES = ["artist", "book", "brand", "movie", "person", "place", "podcast", "tv_show", "videogame"]
SEARCH_TYPES = INSIGHTS_TYPES + ["locality", "actor", "album", "author", "director"]
CENTRES = {"london": (51.507, -0.128), "new york": (40.713, -74.006), "lagos": (6.524, 3.379), "paris": (48.857, 2.352),
           "berlin": (52.520, 13.405), "tokyo": (35.676, 139.650), "los angeles": (34.052, -118.244),
           "san francisco": (37.775, -122.419), "chicago": (41.878, -87.630), "toronto": (43.653, -79.383)}
AGE_KEYS = ["24_and_younger", "25_to_29", "30_to_34", "35_to_44", "45_to_54", "55_and_older"]

_list = {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "maxItems": 10}
_limit = {"type": "integer", "minimum": 1, "maximum": 20, "default": 10}
_itype = {"type": "string", "enum": INSIGHTS_TYPES}
_stype = {"type": "string", "enum": SEARCH_TYPES}
_text = {"type": "string", "minLength": 1}
_date = {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


# name -> (description, input schema): the same names, required fields and enums as `qloo mcp` (harness 0.1.26)
TOOLS: dict[str, tuple[str, dict]] = {
    "qloo_capabilities": ("Readiness of this server. MOCK: no Qloo call is ever made.",
                          {"type": "object", "properties": {"operation_ids": {"type": "array", "items": {"type": "string"}}},
                           "additionalProperties": False}),
    "qloo_recommend": ("Entities related to a combined taste profile (MOCK).",
                       _obj({"target_type": _itype, "signals": _list, "signal_tags": _list, "signal_tags_operator": {"type": "string"},
                             "signal_location": _text, "demographic": _text, "filter_location": _text, "include_tags": _list,
                             "include_tags_operator": {"type": "string"}, "exclude_tags": _list,
                             "exclude_tags_operator": {"type": "string"}, "explain": {"type": "boolean"}, "limit": _limit},
                            ["target_type"])),
    "qloo_rank": ("Rank one option set against one taste profile (MOCK).",
                  _obj({"options": _list, "option_type": _itype, "signals": _list, "signal_location": _text, "demographic": _text,
                        "include_tags": _list, "exclude_tags": _list}, ["options", "option_type"])),
    "qloo_describe": ("Resolve one named entity or id (MOCK).", _obj({"entity": _text, "type": _stype}, ["entity"])),
    "qloo_where_popular": ("Areas where one entity has strong affinity (MOCK).",
                           _obj({"entity": _text, "entity_type": _stype, "within": _text, "limit": _limit}, ["entity", "within"])),
    "qloo_compare_audiences": ("Compare two groups of entity signals (MOCK).",
                               _obj({"group_a": _list, "group_b": _list, "target_type": _itype, "limit": _limit}, ["group_a", "group_b"])),
    "qloo_entity_tags": ("Concepts that characterise entities (MOCK).",
                         _obj({"entities": _list, "entity_type": _stype, "limit": _limit}, ["entities"])),
    "qloo_audience_demographics": ("Aggregate demographics of one entity's audience (MOCK).",
                                   _obj({"entity": _text, "entity_type": _stype, "limit": _limit}, ["entity"])),
    "qloo_trends": ("Popularity time series for 1 to 5 entities (MOCK).",
                    _obj({"entities": {**_list, "maxItems": 5}, "entity_type": _itype, "start_date": _date, "end_date": _date,
                          "limit": _limit}, ["entities", "entity_type", "start_date", "end_date"])),
    "qloo_find_tags": ("Search the tag ontology by concept (MOCK).",
                       _obj({"query": _text, "semantic": {"type": "boolean"}, "limit": _limit}, ["query"])),
}
DOCS = {"recommend": ("/v2/insights", "insights-api-deep-dive"), "rank": ("/v2/insights", "insights-api-deep-dive"),
        "describe": ("/entities", "get-entities"), "where_popular": ("/v2/insights", "heatmaps-use-case"),
        "compare_audiences": ("/v2/analysis/compare", "analysis-compare"), "entity_tags": ("/v2/insights", "taste-analysis"),
        "audience_demographics": ("/v2/insights", "demographics-use-case"), "trends": ("/v2/trending", "get-trending"),
        "find_tags": ("/v2/tags", "get-tags")}


class InputError(ValueError):
    pass


def _rng(*parts) -> random.Random:
    key = json.dumps(parts, sort_keys=True, default=str)
    return random.Random(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big"))


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "x"


def is_id(value: str) -> bool:
    return isinstance(value, str) and value.startswith("mock-")


def _name_of(value: str) -> str:
    """The display name a mock id was made from: mock-<type>-<slug>-<n> -> "Slug N (synthetic)"."""
    if is_id(value):
        parts = value.split("-")
        return " ".join(parts[2:-1]).title() + f" {parts[-1].upper()} (synthetic)"
    return f"{value} (synthetic)"


def candidates(name: str, typ: str | None, n: int = 3) -> list[dict]:
    t = typ or "brand"
    r = _rng("cand", name, t)
    out = []
    for i, letter in enumerate("abc"[:n]):
        out.append({"id": f"mock-{t}-{_slug(name)}-{letter}", "name": f"{name.title()} {letter.upper()} (synthetic)",
                    "type": f"urn:entity:{t}", "rank": i + 1, "popularity": round(r.uniform(0.3, 0.99), 3),
                    "description": "Synthetic candidate made by Knos's MOCK server; not a real entity."})
    return out


def validate(tool: str, args: dict) -> None:
    """The checks the real server's schema makes before calling Qloo: required fields, enums, list sizes, limits."""
    if tool not in TOOLS:
        raise InputError(f"unknown tool {tool}")
    schema = TOOLS[tool][1]
    if not isinstance(args, dict):
        raise InputError("arguments must be an object")
    props = schema.get("properties", {})
    extra = set(args) - set(props)
    if extra and schema.get("additionalProperties") is False:
        raise InputError(f"unexpected field(s): {', '.join(sorted(extra))}")
    for k in schema.get("required", []):
        if k not in args:
            raise InputError(f"missing required field {k}")
    for k, v in args.items():
        s = props.get(k, {})
        if s.get("type") == "array":
            if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
                raise InputError(f"{k}: a list of non-empty strings")
            if not s.get("minItems", 0) <= len(v) <= s.get("maxItems", 10):
                raise InputError(f"{k}: {s.get('minItems', 0)} to {s.get('maxItems', 10)} items")
        elif s.get("type") == "integer":
            if isinstance(v, bool) or not isinstance(v, int) or not s.get("minimum", 1) <= v <= s.get("maximum", 20):
                raise InputError(f"{k}: an integer from {s.get('minimum', 1)} to {s.get('maximum', 20)}")
        elif s.get("type") == "string":
            if not isinstance(v, str) or not v:
                raise InputError(f"{k}: a non-empty string")
            if "enum" in s and v not in s["enum"]:
                raise InputError(f"{k}: one of {', '.join(s['enum'])}")
            if "pattern" in s and not re.match(s["pattern"], v):
                raise InputError(f"{k}: YYYY-MM-DD")


def envelope(op: str, status: str, summary: str, *, results=None, query: dict | None = None, cid: str = "mock-1", **extra) -> dict:
    path, doc = DOCS.get(op, ("/", "index"))
    env = {"schema_version": SCHEMA_VERSION, "operation": op, "status": status, "summary": summary,
           "results": results if results is not None else [], "result_count": len(results) if isinstance(results, list) else 0,
           "execution": {"transport": "mcp", "transport_name": "Knos MOCK MCP (synthetic)", "correlation_id": cid, "duration_ms": 0},
           "provenance": {"source": MOCK_LABEL, "endpoint": path, "documentation": f"https://docs.qloo.com/reference/{doc}",
                          "requests": [{"method": "GET", "path": path, "query": query or {}}]},
           "_mock": MOCK_LABEL, **extra}
    return env


def _needs(op: str, names: list[tuple[str, str, str | None]], cid: str) -> dict:
    issues = [{"input": n, "kind": "ambiguous", "input_kind": "entity", "field": field, **({"scope": t} if t else {}),
               "candidates": candidates(n, t)} for n, field, t in names]
    env = envelope(op, "needs_input", "Choose the intended Qloo entity.", cid=cid, resolution={"issues": issues})
    env.pop("provenance")
    return env


def _entity(eid: str, r: random.Random, typ: str) -> dict:
    return {"entity_id": eid, "name": _name_of(eid), "type": f"urn:entity:{typ}", "popularity": round(r.uniform(0.2, 0.99), 3),
            "affinity": round(r.uniform(0.05, 0.98), 3)}


def _interp(ids: list[str]) -> list[dict]:
    return [{"input": i, "entityId": i, "name": _name_of(i), "match": "identifier"} for i in ids]


def call(tool: str, args: dict, cid: str = "mock-1", today: date | None = None) -> dict:
    """One tools/call: the structured envelope. Unresolved names -> needs_input, as the real resolver answers."""
    op = tool.removeprefix("qloo_")
    if tool == "qloo_capabilities":
        return {"manifest_schema_version": "1.1", "contract_version": "1.0.0", "result_schema_version": SCHEMA_VERSION,
                "contract_checksum": "mock", "adapter": {"id": SERVER_NAME, "compatibility": "mock", "ready": True,
                                                         "supported_operation_ids": [t.removeprefix("qloo_") for t in TOOLS if t != "qloo_capabilities"],
                                                         "fallback": "none"}, "_mock": MOCK_LABEL}
    try:
        validate(tool, args)
    except InputError as why:
        return envelope(op, "error", str(why), cid=cid, error={"code": "QLOO_INPUT", "layer": "input", "retryable": False,
                                                                "recovery": "Correct the input and call again."})
    r = _rng(tool, args)
    lim = args.get("limit", 10)
    if tool == "qloo_find_tags":
        q = args["query"]
        res = [{"id": f"urn:tag:mock:{_slug(q)}-{i}", "name": f"{q} {['', 'culture', 'style'][i]} (synthetic)".replace("  ", " "),
                "type": "urn:tag:keyword:mock", "popularity": round(r.uniform(0.2, 0.95), 3)} for i in range(min(lim, 3))]
        return envelope(op, "ok", f"{len(res)} synthetic tag(s) for '{q}'.", results=res, cid=cid,
                        interpretation={"query": q, "semantic": args.get("semantic", True)},
                        query={"filter.query": q, "feature.semantic_search": True, "take": lim})
    if tool == "qloo_describe":
        e = args["entity"]
        if not is_id(e):
            return _needs(op, [(e, "entity", args.get("type"))], cid)
        res = [{**_entity(e, r, e.split("-")[1]), "properties": {"short_description": "Synthetic entity (MOCK)."}}]
        return envelope(op, "ok", "Resolved 1 synthetic entity.", results=res, cid=cid, interpretation={"entity": _interp([e])[0]},
                        query={"entity_ids": [e]})
    if tool in ("qloo_audience_demographics", "qloo_where_popular"):
        e = args["entity"]
        if not is_id(e):
            return _needs(op, [(e, "entity", args.get("entity_type"))], cid)
        if tool == "qloo_audience_demographics":
            ages = {k: round(r.uniform(-0.45, 0.45), 3) for k in AGE_KEYS}
            g = round(r.uniform(-0.3, 0.3), 3)
            res = [{"entity_id": e, "query": {"age": ages, "gender": {"female": g, "male": round(-g, 3)}}}]
            return envelope(op, "ok", "Synthetic aggregate demographics.", results=res, cid=cid,
                            interpretation={"entity": _interp([e])[0]},
                            query={"filter.type": "urn:demographics", "signal.interests.entities": e, "take": lim})
        lat, lon = CENTRES.get(args["within"].strip().lower(), (40.0 + r.uniform(-10, 10), r.uniform(-20, 20)))
        cells = []
        for _ in range(lim):
            la, lo = lat + r.uniform(-0.12, 0.12), lon + r.uniform(-0.18, 0.18)
            cells.append({"location": {"latitude": round(la, 4), "longitude": round(lo, 4), "geohash": encode(la, lo, 6)},
                          "query": {"affinity": round(r.uniform(0.05, 0.99), 3), "popularity": round(r.uniform(0.1, 0.99), 3)}})
        cells.sort(key=lambda c: -c["query"]["affinity"])
        for i, c in enumerate(cells):
            c["query"]["affinity_rank"] = i + 1
        return envelope(op, "ok", f"{len(cells)} synthetic heatmap cells.", results=cells, cid=cid,
                        interpretation={"entity": _interp([e])[0], "within": args["within"]},
                        query={"filter.type": "urn:heatmap", "signal.interests.entities": e, "filter.location.query": args["within"], "take": lim})
    if tool in ("qloo_entity_tags", "qloo_trends"):
        es = args["entities"]
        bad = [x for x in es if not is_id(x)]
        if bad:
            return _needs(op, [(x, "entities", args.get("entity_type")) for x in bad], cid)
        if tool == "qloo_entity_tags":
            res = [{"id": f"urn:tag:mock:trait-{i}", "name": f"Trait {i + 1} (synthetic)", "type": "urn:tag:keyword:mock",
                    "popularity": round(r.uniform(0.1, 0.9), 3), "affinity": round(r.uniform(0.1, 0.99), 3)} for i in range(min(lim, 6))]
            res.sort(key=lambda t: -t["affinity"])
            return envelope(op, "ok", f"{len(res)} synthetic tags.", results=res, cid=cid, interpretation={"entities": _interp(es)},
                            query={"filter.type": "urn:tag", "signal.interests.entities": es, "take": lim})
        start, end = date.fromisoformat(args["start_date"]), date.fromisoformat(args["end_date"])
        if start > end:
            return envelope(op, "error", "start_date after end_date.", cid=cid,
                            error={"code": "QLOO_INPUT", "layer": "input", "retryable": False, "recovery": "Fix the dates."})
        series = []
        for e in es:
            rr = _rng("trend", e, args["start_date"], args["end_date"])
            p, drift, pts = rr.uniform(40, 80), rr.uniform(-0.6, 0.6), []
            n = min(lim, 12)
            step = max(1, (end - start).days // max(1, n - 1))
            for i in range(n):
                p = max(1.0, min(99.9, p + drift + rr.uniform(-0.8, 0.8)))
                pts.append({"date": (start + timedelta(days=i * step)).isoformat(), "population_percentile": round(p, 2)})
            series.append({"entity": _interp([e])[0], "points": pts})
        env = envelope(op, "ok", f"{len(series)} synthetic series.", results=None, cid=cid,
                       interpretation={"entity_type": args["entity_type"], "start_date": args["start_date"], "end_date": args["end_date"]},
                       query={"filter.type": args["entity_type"], "filter.start_date": args["start_date"], "filter.end_date": args["end_date"]})
        env.pop("results")
        env.update(series=series, result_count=len(series))
        return env
    if tool == "qloo_compare_audiences":
        bad = [(x, f, args.get("target_type")) for f in ("group_a", "group_b") for x in args[f] if not is_id(x)]
        if bad:
            return _needs(op, bad, cid)
        typ = args.get("target_type", "brand")
        res = [_entity(f"mock-{typ}-shared-taste-{i}", r, typ) for i in range(min(lim, 6))]
        return envelope(op, "ok", f"{len(res)} synthetic entities from the comparison.", results=res, cid=cid,
                        interpretation={"group_a": _interp(args["group_a"]), "group_b": _interp(args["group_b"]), "target_type": typ},
                        query={"a.signal.interests.entities": args["group_a"], "b.signal.interests.entities": args["group_b"], "take": lim})
    if tool in ("qloo_recommend", "qloo_rank"):
        sig = args.get("signals", [])
        if args.get("demographic") and not args.get("signal_location"):
            return envelope(op, "needs_input", "Demographic Qloo signals require signal_location so the audience geography is explicit.",
                            cid=cid, resolution={"issues": []})
        if tool == "qloo_rank" and not (sig or args.get("signal_location") or args.get("demographic")):
            return envelope(op, "needs_input", "Ranking requires an entity, location, or demographic signal.", cid=cid,
                            resolution={"issues": []})
        if tool == "qloo_recommend" and not (sig or args.get("signal_tags") or args.get("signal_location") or args.get("demographic")):
            return envelope(op, "needs_input", "Provide at least one entity, tag, location, or demographic taste signal.", cid=cid,
                            resolution={"issues": []})
        names = [(x, "signals", None) for x in sig if not is_id(x)]
        if tool == "qloo_rank":
            names += [(x, "options", args["option_type"]) for x in args["options"] if not is_id(x)]
        if names:
            return _needs(op, names, cid)
        if tool == "qloo_rank":
            typ = args["option_type"]
            res = [_entity(o, _rng("rank", o, sig, args.get("signal_location"), args.get("demographic")), typ) for o in args["options"]]
            res.sort(key=lambda x: -x["affinity"])
            return envelope(op, "ok", f"Ranked {len(res)} synthetic option(s).", results=res, cid=cid,
                            interpretation={"option_type": typ, "options": _interp(args["options"]), "signals": _interp(sig),
                                            "signal_location": args.get("signal_location"), "demographic": args.get("demographic")},
                            query={"filter.type": typ, "filter.results.entities": args["options"], "take": len(args["options"])})
        typ = args["target_type"]
        res = []
        for i in range(min(lim, 5)):
            e = _entity(f"mock-{typ}-{_slug('liked by fans ' + typ)}-{i}", r, typ)
            if args.get("explain", True):
                e["explainability"] = [{"entity_id": s, "score": round(r.uniform(0.1, 1.0), 3)} for s in sig[:3]]
            res.append(e)
        res.sort(key=lambda x: -x["affinity"])
        return envelope(op, "ok", f"{len(res)} synthetic recommendation(s).", results=res, cid=cid,
                        interpretation={"target_type": typ, "signals": _interp(sig), "signal_tags": args.get("signal_tags", [])},
                        query={"filter.type": typ, "signal.interests.entities": sig, "take": lim, "feature.explainability": True})
    return envelope(op, "error", f"unknown tool {tool}", cid=cid,
                    error={"code": "QLOO_INPUT", "layer": "input", "retryable": False, "recovery": "Use a listed tool."})


# ---- the stdio server (newline-delimited JSON-RPC 2.0, as MCP's stdio transport) -----------------------------------
def handle(msg: dict, state: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:      # a notification (notifications/initialized, cancelled): no answer
        return None
    if method == "initialize":
        ver = (msg.get("params") or {}).get("protocolVersion", "2025-06-18")
        return {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": ver, "capabilities": {"tools": {"listChanged": False}},
                                                        "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
                                                        "instructions": MOCK_LABEL}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (d, s) in TOOLS.items()]}}
    if method == "tools/call":
        p = msg.get("params") or {}
        state["n"] = state.get("n", 0) + 1
        fail = state.get("fail", {}).get(p.get("name"))
        if fail:
            fail["left"] -= 1
            if fail["left"] >= 0:
                env = envelope(str(p.get("name", "")).removeprefix("qloo_"), "error", "MOCK transient failure.", cid=f"mcp-{state['n']}",
                               error={"code": fail["code"], "layer": "qloo", "retryable": fail["retryable"], "recovery": "Retry later."})
                return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(env)}],
                                                                "structuredContent": env, "isError": True}}
        env = call(str(p.get("name", "")), p.get("arguments") or {}, cid=f"mcp-{state['n']}")
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": json.dumps(env)}],
                                                        "structuredContent": env, "isError": env.get("status") == "error"}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def fail_plan(text: str | None) -> dict:
    """KNOS_WANTED_MOCK_FAIL="qloo_rank:QLOO_RATE_LIMIT:retryable:2,..." -> the first N calls of a tool fail (tests)."""
    out = {}
    for part in (text or "").split(","):
        bits = part.strip().split(":")
        if len(bits) == 4:
            out[bits[0]] = {"code": bits[1], "retryable": bits[2] == "retryable", "left": int(bits[3])}
    return out


def serve(stdin=None, stdout=None) -> None:
    import os
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    state = {"fail": fail_plan(os.environ.get("KNOS_WANTED_MOCK_FAIL"))}
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        out = handle(msg, state) if isinstance(msg, dict) else None
        if out is not None:
            stdout.write(json.dumps(out) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
