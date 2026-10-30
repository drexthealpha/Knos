"""The `knos mcp` tool knos_demand_check, listed when KNOS_MCP_TOOLS=demand (a comma-separated list, e.g. "ideas,demand").

Any agent gets the same code-made decision as Knos's web app without holding a Qloo key: the tool POSTs the idea to the
hosted demand check (KNOS_WANTED_URL, its /api/check), where Qloo's API is called server side and the decision (OPEN
pre-orders with a target and a reserve, REFUSE with reasons, or "cannot decide: no Qloo evidence") is made by code.
Read-only: nothing is locked or signed by this tool.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, NoReturn

from . import qloo_families

OPT_IN_ENV, OPT_IN_WORD = "KNOS_MCP_TOOLS", "demand"
DEFAULT_URL = "https://knos.onrender.com"
TIMEOUT_S = 120

MCP_TOOLS: list[dict[str, Any]] = [{
    "name": "knos_demand_check",
    "title": "Is this product wanted? (Qloo demand check)",
    "description": ("Check a product idea against Qloo's taste data through Knos's hosted demand check: the closest existing "
                    "products and the market leader, the idea's taste tags, who (age, gender), where (places), audience "
                    "segments, rising or falling, and overlap vs the leader. Returns a decision made by code: OPEN pre-orders "
                    "(target units and reserve) or REFUSE with reasons; without Qloo evidence it says 'cannot decide'. "
                    "Every number names the Qloo call that produced it. Directional demand evidence, not a sales forecast."),
    "properties": {"idea": {"type": "string", "description": "the product idea in plain words, or a paper's DOI (3 to 500 characters)"},
                   "picked": {"type": "boolean", "description": "true when idea is the exact reading picked from the readings a first call returned"},
                   "place": {"type": "string", "description": "where to look for demand (a city or country); default United States"},
                   "leader": {"type": "string", "description": "the market leader to compare against; default Qloo's top match"},
                   **{k: qloo_families.schema(k) for k in qloo_families.FIELDS}},
    "required": ["idea"],
}]


def base_url() -> str:
    return (os.environ.get("KNOS_WANTED_URL") or DEFAULT_URL).rstrip("/")


def _fail(text: str) -> NoReturn:
    from .mcp import Failed
    raise Failed(text)


def demand_check(args: dict) -> dict:
    idea = args.get("idea")
    if not isinstance(idea, str) or not 3 <= len(idea.strip()) <= 500:
        _fail("idea: the product idea in 3 to 500 characters")
    try:
        opts = qloo_families.options({k: args[k] for k in qloo_families.FIELDS if k in args})
    except ValueError as why:
        _fail(str(why))
    body = {"idea": idea.strip(), **{k: args[k] for k in ("place", "leader") if isinstance(args.get(k), str) and args[k].strip()}, **opts,
            **({"picked": True} if args.get("picked") is True else {})}
    url = base_url()
    if not url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
        _fail("KNOS_WANTED_URL must be an https URL (or a local server)")
    req = urllib.request.Request(url + "/api/check", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "knos-mcp"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            rep = json.loads(r.read(2_000_000))
    except urllib.error.HTTPError as e:
        try:
            said = json.loads(e.read(4000) or b"{}").get("error", "")
        except ValueError:
            said = ""
        _fail(f"the demand check at {url} answered HTTP {e.code}{': ' + said if said else ''}")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        _fail(f"the demand check at {url} could not be reached ({type(e).__name__}); set KNOS_WANTED_URL to the hosted app")
    if rep.get("kind") == "which_one":           # which one do you mean? the readings first, as on the front door
        return {**rep, "next": "call knos_demand_check again with idea set to the text of the reading you mean and picked: true"}
    d = rep.get("decision") or {}
    return {"decision": d.get("verdict"), "qloo_calls": rep.get("qloo_calls"),
            **{k: rep[k] for k in ("queued", "stand_in", "read_as", "result_line", "brief", "ready") if rep.get(k)}, "reasons": d.get("reasons"), "target_units": d.get("target_units"),
            "reserve_units": d.get("reserve_units"), "formula": d.get("formula"), "report_hash": rep.get("hash"),
            "label": rep.get("label"), "leader": (rep.get("leader") or {}).get("name"),
            "who": rep.get("who"), "where": rep.get("where"), "audiences": rep.get("audiences"), "trend": rep.get("trend"),
            "versus": rep.get("versus"), "calls": rep.get("calls"), "rules": rep.get("rules"),
            "report_url": f"{url}/#report={rep.get('hash')}", "framing": rep.get("framing")}


HANDLERS = {"knos_demand_check": demand_check}
