"""One OpenAPI 3.1 document for this server, served at /openapi.json beside the hosted MCP endpoint (/mcp).

Built from the route tables the server dispatches on (server.ROUTES + server.GET_ROUTES + product_routes.ROUTES), so a
route cannot exist without being documented. validate() checks the structure this server relies on; the release
evidence also runs the document through openapi-spec-validator.
"""
from __future__ import annotations

from . import product_routes

TYPES = {"string": {"type": "string"}, "integer": {"type": "integer"}, "array": {"type": "array", "items": {}}, "object": {"type": "object"}, "boolean": {"type": "boolean"}}

# Examples are real on this server: the recorded solar festival card, the crossing released on devnet and its attempt.
H, P = "14d68eb782caff051897a9799ed592e7a6875bce6559c1c19fa67b0be41899c0", "7b4ed16b8c2903dc"
MS = {"project": P, "milestone": "preorders"}
# a GET route's query: name -> example (a required name is in REQUIRED); a value {"from": ...} is read from another call
FROM_CROSS = {"from": {"method": "POST", "path": "/api/cross", "body": {"ref": "10.1038/nature16521"}, "pick": "id"}}
PARAMS = {"/api/report": {"hash": H}, "/api/trace": {"hash": H}, "/api/receipts": {"id": H[:16]}, "/api/pool": {"hash": H},
          "/api/quote": {"hash": H, "units": 5}, "/api/x402/report": {"hash": H}, "/api/project": {"id": P}, "/api/project/prompt": MS,
          "/api/project/route": MS, "/api/commitments": {"take": 5}, "/api/crossings": {"take": 5}, "/api/receivables": {"take": 5},
          "/api/company/export": {"project": P, "format": "xero"}, "/api/actions/preorder": {"report": H}, "/api/price": {"pair": "EUR/USD"},
          "/api/ready/card": {"hash": "0" * 64}, "/api/memory/search": {"q": "kombucha"}, "/api/taste/movie": {"title": "Inception", "year": 2010},
          "/api/attest": {**MS, "attempt": "46088348e3"}, "/api/track": {"wallet": "EZi57B4aT661Nwf9oZyPN5ronZMMgtgGUfe68aGff4Gf"},
          "/api/sns": {"name": "knos.sol"}, "/api/projects": {"take": 10}, "/api/cross": {"id": FROM_CROSS, "since": 0},
          "/api/cross/stream": {"id": FROM_CROSS},
          "/api/commitment": {"id": {"from": {"method": "GET", "path": "/api/commitments", "pick": "commitments.0.commitment"}}},
          "/api/referee/session": {"id": {"from": {"method": "GET", "path": "/api/referee/pending", "pick": "sessions.0.id"}}},
          "/api/project/evidence": {"id": {"from": {"method": "GET", "path": "/api/project?id=" + P, "pick": "milestones.0.attempts.0.evidence"}}},
          "/api/prize/evidence": {"id": {"from": {"method": "GET", "path": "/api/tasks", "pick": "rounds.0.prize.id"}}},
          "/api/front": {"slug": {"from": {"method": "GET", "path": "/api/front", "pick": "products.0.slug"}}}}
REQUIRED = {"/api/report": {"hash"}, "/api/trace": {"hash"}, "/api/receipts": {"id"}, "/api/pool": {"hash"}, "/api/quote": {"hash"},
            "/api/x402/report": {"hash"}, "/api/project": {"id"}, "/api/project/prompt": {"project", "milestone"},
            "/api/project/route": {"project", "milestone"}, "/api/company/export": {"project"}, "/api/actions/preorder": {"report"},
            "/api/ready/card": {"hash"}, "/api/memory/search": {"q"}, "/api/taste/movie": {"title", "year"}, "/api/attest": {"project", "milestone", "attempt"},
            "/api/track": {"wallet"}, "/api/sns": {"name"}, "/api/cross": {"id"}, "/api/cross/stream": {"id"}, "/api/commitment": {"id"},
            "/api/referee/session": {"id"}, "/api/project/evidence": {"id"}, "/api/prize/evidence": {"id"}}
BRIEF = {"title": "A check", "milestones": [{"name": "Tests pass", "target": "pytest exits 0 on the repository", "verifier": {"kind": "machine", "check": "pytest"}, "deadline_days": 3}]}
# a POST route that changes nothing: its body and example
BODIES = {"/api/research": ({"ref": "string", "product": "string"}, {"ref": "10.1038/nature14539"}),
          "/api/open-signals": ({"idea": "string", "place": "string"}, {"idea": "a cold brew coffee shop", "place": "Austin"}),
          "/api/ready": ({"brief": "object"}, {"brief": BRIEF})}
READ_POSTS = {"/api/research", "/api/open-signals", "/api/ready", "/api/check"}
HTML = {"/app/", "/paid", "/fields", "/money", "/with-without", "/companies", "/verify", "/status/qloo", "/qloo-safe-use", "/trace.html", "/r/{code}"}
CONTENT = {"/sw.js": "application/javascript", "/manifest.webmanifest": "application/manifest+json", "/api/proofs/cosign.pub": "text/plain",
           "/api/proofs/signature": "application/json", "/api/cross/stream": "text/event-stream", "/api/company/export": "text/csv"}
MOVED = {"/": "https://drexthealpha.github.io/Knos/", "/app": "/app/", "/quality": "https://drexthealpha.github.io/Knos/quality/",
         "/quality/": "https://drexthealpha.github.io/Knos/quality/"}
NOT_READ_ONLY = {"/auth/orcid", "/auth/orcid/callback", "/auth/sso", "/auth/sso/callback", "/r/{code}", "/api/agent/keys", "/mcp/store"}


def _answer(method: str, path: str) -> dict:
    """The 200 (or 301) a route answers, with its real content type."""
    if method == "GET" and path in MOVED:
        return {"301": {"description": f"moved: {MOVED[path]}", "headers": {"Location": {"schema": {"type": "string"}, "example": MOVED[path]}}}}
    if method == "GET" and path in HTML:
        return {"200": {"description": "an HTML page", "content": {"text/html": {"schema": {"type": "string"}}}}}
    if method == "GET" and path in CONTENT:
        return {"200": {"description": "OK", "content": {CONTENT[path]: {"schema": {"type": "string"}}}}}
    return {"200": {"description": "OK", "content": {"application/json": {"schema": {"type": "object"}}}}}


def _routes():
    from . import server
    seen = {(m, p) for m, p, *_ in product_routes.ROUTES}
    rows = list(product_routes.ROUTES)
    for p in server.ROUTES:
        if ("POST", p) not in seen:
            rows.append(("POST", p, p in server.SIGNED_IN, server.SUMMARIES.get(p, f"POST {p}"), {}))
    for p, summary in server.GET_ROUTES.items():
        if ("GET", p) not in seen:
            rows.append(("GET", p, False, summary, {}))
    rows.append(("POST", "/api/pay/fund", False, "Solana Pay transaction request: {account} -> the milestone's funding transaction to sign",
                 {"project": "string", "milestone": "string", "units": "integer", "account": "string"}))
    rows.append(("POST", "/mcp", False, "Hosted MCP (Streamable HTTP, JSON-RPC 2.0): Knos's tools for agents", {}))
    return rows


def document(base: str = "https://knos.onrender.com") -> dict:
    paths: dict = {}
    for method, path, signed, summary, fields in _routes():
        op = {"summary": summary, "operationId": (method.lower() + path.replace("/", "_").replace("{", "").replace("}", "")).strip("_") + ("_page" if len(path) > 1 and path.endswith("/") else ""),
              "responses": {**_answer(method, path), "400": {"description": "refused, with the reason in `error`"},
                            "404": {"description": "no such object, with the reason in `error`"}, "429": {"description": "rate limited"}}}
        if (method == "GET" and path not in NOT_READ_ONLY and not signed and not path.startswith("/auth/")) or (method == "POST" and path in READ_POSTS):
            op["x-read-only"] = True
        if method == "GET" and path == "/api/x402/report":
            op["responses"]["402"] = {"description": "payment required: the x402 price, in the PAYMENT-REQUIRED header"}
        if method == "GET" and path == "/api/taste/movie":
            op["responses"]["503"] = {"description": "Qloo did not answer, with the reason in `error`"}
        if signed:
            op["security"] = [{"session": []}]
            op["responses"]["401"] = {"description": "sign in first"}
        params = [{"name": n, "in": "path", "required": True, "schema": {"type": "string"}} for n in _path_params(path)]
        if method == "GET":
            ex = PARAMS.get(path, {})
            names = list(dict.fromkeys([*fields, *ex]))
            for k in names:
                prm = {"name": k, "in": "query", "required": k in REQUIRED.get(path, set()), "schema": TYPES.get(fields.get(k, "integer" if isinstance(ex.get(k), int) else "string"), {"type": "string"})}
                if isinstance(ex.get(k), dict) and "from" in ex[k]:
                    prm["x-example-from"] = ex[k]["from"]
                elif k in ex:
                    prm["example"] = ex[k]
                params.append(prm)
        elif fields or path in BODIES:
            props, example = BODIES.get(path, (fields, None))
            op["requestBody"] = {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "properties": {k: TYPES.get(t, {"type": "string"}) for k, t in props.items()}}, **({"example": example} if example else {})}}}
        if method == "POST" and path in DEMAND_BODIES:      # the demand check: every Qloo family field, typed, with an example
            op["requestBody"] = {"required": True, "content": {"application/json": {"schema": demand_body(path),
                                 "examples": {"who-and-where": {"summary": "Who and where",
                                              "value": {"idea": "trail running shoes for ultramarathons", "age": "24_and_younger", "near": "Austin", "radius": 5000}},
                                              "price-and-brand": {"summary": "Price tier and who serves it",
                                              "value": {"idea": "a cold brew coffee shop", "near": "Seattle", "price_level": "1", "references_brand": "Starbucks"}}}}}}
        if params:
            op["parameters"] = params
        paths.setdefault(path, {})[method.lower()] = op
    return {"openapi": "3.1.0",
            "info": {"title": "Knos", "version": _version(),
                     "description": "Knos carries research across the valley of death: see who wants it and where, then get paid only on proof. Demand checks on Qloo, Ready briefs, milestone "
                                    "money held on Solana until the proof passes; devnet, test money, no customers yet. Agents: the same tools over MCP at /mcp."},
            "servers": [{"url": base}],
            "components": {"securitySchemes": {"session": {"type": "http", "scheme": "bearer",
                                                           "description": "the session token a sign-in returns (passkey, SSO, Google, ORCID, email, guest)"}}},
            "paths": dict(sorted(paths.items()))}


DEMAND_BODIES = {"/api/check": "idea", "/api/cross": "ref or idea"}


def demand_body(path: str) -> dict:
    """The body of a demand check: the idea (or paper), the market, and every family field of knos.qloo_families."""
    from knos import qloo_families as Q
    props = {"idea": {"type": "string", "description": "the product idea, 3 to 500 characters", "examples": ["a cold brew coffee shop"]},
             "place": {"type": "string", "description": "the launch market (city or country)", "examples": ["Austin"]},
             "leader": {"type": "string", "description": "the market leader to compare against", "examples": ["Starbucks"]}}
    if path == "/api/cross":
        props = {"ref": {"type": "string", "description": "a paper id (DOI, arXiv, PubMed, OpenAlex, patent)", "examples": ["10.1038/nature16521"]},
                 **props, "product": {"type": "string", "description": "the product phrase"}}
    props.update({k: Q.schema(k) for k in Q.FIELDS})
    return {"type": "object", "properties": props, **({"required": ["idea"]} if path == "/api/check" else {}), "additionalProperties": False}


def _path_params(path: str) -> list[str]:
    import re
    return re.findall(r"{([a-z_]+)}", path)


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("knos")
    except Exception:  # noqa: BLE001
        return "0.4.0"


def validate(doc: dict) -> list[str]:
    errs = []
    if doc.get("openapi") != "3.1.0" or not doc.get("info", {}).get("title") or not doc.get("info", {}).get("version"):
        errs.append("openapi/info")
    ids = set()
    for path, ops in doc.get("paths", {}).items():
        if not path.startswith("/"):
            errs.append(f"{path}: must start with /")
        for m, op in ops.items():
            if m not in ("get", "post", "put", "delete", "patch", "options"):
                errs.append(f"{path} {m}: method")
            if op["operationId"] in ids:
                errs.append(f"{path} {m}: duplicate operationId")
            ids.add(op["operationId"])
            if not op.get("responses"):
                errs.append(f"{path} {m}: responses")
            for prm in op.get("parameters", []):
                if prm["in"] == "path" and "{" + prm["name"] + "}" not in path:
                    errs.append(f"{path}: path parameter {prm['name']}")
            for s in op.get("security", []):
                for k in s:
                    if k not in doc["components"]["securitySchemes"]:
                        errs.append(f"{path}: security {k}")
    return errs
