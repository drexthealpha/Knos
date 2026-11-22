"""The files agents and AI search read on knos.onrender.com: llms.txt, robots.txt, the sitemap, the AI catalog, the MCP
Server Card, the HTML 404, the /start redirect and IndexNow.

Every route function is pure and returns (status, body, content type, headers): body is bytes, or a dict the server
sends as JSON. The server wires each one to its path (knos_wanted.server).

    GET /llms.txt                      llms_txt(base)              https://llmstxt.org/
    GET /robots.txt                    robots_txt(base)
    GET /sitemap.xml                   sitemap_xml(base)           https://www.sitemaps.org/protocol.html
    GET /.well-known/ai-catalog.json   ai_catalog(base)            SEP-2127 discovery (AI Catalog)
    GET /mcp/server-card               server_card(base, ...)      SEP-2127 Server Card
    GET /start, /start/                start_redirect()
    GET /<key>.txt                     key_file(key)               IndexNow key file
    any unknown path, Accept text/html not_found_html(path)
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as _xml_escape

BASE = "https://knos.onrender.com"
PAGES = "https://drexthealpha.github.io/Knos"
START = PAGES + "/"          # /start: the old Start page left the site, so straight to the front door
REPO = "https://github.com/drexthealpha/Knos"
ONE_LINE = "The goal: Knos carries research across the valley of death."
DIR = Path(__file__).resolve().parent / "agentfiles"
KEY_FILE = Path(__file__).resolve().parents[3] / "web" / "indexnow.txt"   # the repo's web/indexnow.txt (public by design)
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
INDEXNOW_MAX = 10_000
# no $schema in the card: the server-card schema's published URL answered 404 (15 Nov 2026), so the card names none
SERVER_CARD_NAME = "io.github.drexthealpha/knos"        # the schema's "namespace/name" form; "knos" alone fails its pattern
FALLBACK_PROTOCOL = "2025-11-25"                         # what GET /mcp advertises (knos_wanted.agent.PROTOCOL)
BOTS = ("OAI-SearchBot", "Claude-SearchBot", "Claude-User", "ChatGPT-User", "Googlebot", "*")
PRIVATE = ("/api/", "/auth/", "/oauth/")
DISCOVERY_HEADERS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET",
                     "Access-Control-Allow-Headers": "Content-Type, If-None-Match", "Cache-Control": "public, max-age=3600"}
_KEY = re.compile(r"[A-Za-z0-9-]{8,128}")


def _base(base: str | None) -> str:
    return (base or BASE).rstrip("/")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# 1. llms.txt ---------------------------------------------------------------------------------------------------------

def llms_txt(base: str = BASE):
    text = (DIR / "llms.txt").read_text(encoding="utf-8").replace("{base}", _base(base))
    return 200, text.encode("utf-8"), "text/markdown; charset=utf-8", {"Cache-Control": "public, max-age=3600"}


# 2. robots.txt -------------------------------------------------------------------------------------------------------

def robots_txt(base: str = BASE):
    lines = []
    for bot in BOTS:
        lines += [f"User-agent: {bot}", "Allow: /"] + [f"Disallow: {p}" for p in PRIVATE] + [""]
    lines.append(f"Sitemap: {_base(base)}/sitemap.xml")
    return 200, ("\n".join(lines) + "\n").encode("utf-8"), "text/plain; charset=utf-8", {"Cache-Control": "public, max-age=3600"}


# 3. sitemap.xml ------------------------------------------------------------------------------------------------------

def sitemap_xml(base: str = BASE, lastmod: str | None = None):
    """The public pages; a lastmod is a W3C date (YYYY-MM-DD or full ISO time)."""
    b, day = _base(base), (lastmod or _today())
    urls = [(b + "/app/", day), (PAGES + "/proof/", day)]
    rows = "".join(f"  <url><loc>{_xml_escape(loc)}</loc><lastmod>{_xml_escape(mod)}</lastmod></url>\n" for loc, mod in urls)
    body = ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{rows}</urlset>\n")
    return 200, body.encode("utf-8"), "application/xml; charset=utf-8", {"Cache-Control": "public, max-age=3600"}


# 4. AI catalog -------------------------------------------------------------------------------------------------------

def ai_catalog(base: str = BASE):
    b = _base(base)
    host = b.split("://", 1)[-1]
    doc = {"specVersion": "1.0",
           "host": {"displayName": "Knos", "identifier": b, "documentationUrl": REPO + "#readme"},
           "entries": [
               {"identifier": f"urn:air:{host}:mcp:knos", "type": "application/mcp-server-card+json", "url": b + "/mcp/server-card",
                "displayName": "Knos MCP server"},
               {"identifier": f"urn:air:{host}:openapi:knos", "type": "application/vnd.oai.openapi+json", "url": b + "/openapi.json",
                "displayName": "Knos HTTP API"},
               {"identifier": f"urn:air:{host}:llms:knos", "type": "text/markdown", "url": b + "/llms.txt",
                "displayName": "llms.txt"}]}
    return 200, doc, "application/ai-catalog+json", dict(DISCOVERY_HEADERS)


# 5. MCP Server Card --------------------------------------------------------------------------------------------------

def supported_protocol_versions(fallback: str = FALLBACK_PROTOCOL) -> list[str]:
    """The installed `mcp` SDK's latest revision first, then every other version it supports, newest first. Without
    the SDK: the one version this server's own /mcp advertises."""
    try:
        from mcp.types import LATEST_PROTOCOL_VERSION  # type: ignore[import-not-found]
        try:
            from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS  # type: ignore[import-not-found]
        except ImportError:
            SUPPORTED_PROTOCOL_VERSIONS = [LATEST_PROTOCOL_VERSION]
        rest = sorted({str(v) for v in SUPPORTED_PROTOCOL_VERSIONS} - {str(LATEST_PROTOCOL_VERSION)}, reverse=True)
        return [str(LATEST_PROTOCOL_VERSION)] + rest
    except ImportError:
        return [fallback]


def server_card(base: str = BASE, version: str = "0.0.0", protocol_versions: list[str] | None = None):
    b = _base(base)
    card = {"name": SERVER_CARD_NAME, "title": "Knos", "version": str(version),
            "description": "Knos: see who would buy a research product first, from free public signals; devnet test money.",
            "websiteUrl": b + "/app/", "repository": {"url": REPO, "source": "github"},
            "icons": [{"src": b + "/static/icon.svg", "mimeType": "image/svg+xml", "sizes": ["any"]}],
            "remotes": [{"type": "streamable-http", "url": b + "/mcp", "supportedProtocolVersions": list(protocol_versions or supported_protocol_versions())}]}
    return 200, card, "application/mcp-server-card+json", dict(DISCOVERY_HEADERS)


# 6. HTML 404 and 7. /start -------------------------------------------------------------------------------------------

def not_found_html(path: str = ""):
    """For an unknown path whose request's Accept header contains text/html. The path is never echoed."""
    return 404, (DIR / "404.html").read_bytes(), "text/html; charset=utf-8", {}


def start_redirect():
    return 301, b"", "text/plain", {"Location": START}


# 8. IndexNow ---------------------------------------------------------------------------------------------------------

def read_key(path: Path = KEY_FILE) -> str | None:
    """The public IndexNow key from web/indexnow.txt (one line of hex), or None when the file is absent or malformed."""
    try:
        k = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return k if _KEY.fullmatch(k) else None


def key_file(key: str):
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        return 404, {"error": "not found"}, "application/json", {}
    return 200, key.encode("ascii"), "text/plain; charset=utf-8", {"Cache-Control": "public, max-age=86400"}


def indexnow(urls, key: str, key_location: str, host: str) -> dict:
    """The JSON body for POST https://api.indexnow.org/indexnow: only URLs on `host`, without duplicates, at most 10,000."""
    seen, keep = set(), []
    for u in urls or ():
        if isinstance(u, str) and u.split("://", 1)[-1].split("/", 1)[0] == host and u not in seen:
            seen.add(u)
            keep.append(u)
        if len(keep) == INDEXNOW_MAX:
            break
    return {"host": host, "key": key, "keyLocation": key_location, "urlList": keep}


def indexnow_send(body: dict, endpoint: str = INDEXNOW_ENDPOINT, opener=urllib.request.urlopen) -> int:
    """POST the body; the HTTP status (200 or 202 is success), or 0 when nothing answered. Never raises."""
    try:
        if not body.get("urlList"):
            return 0
        req = urllib.request.Request(endpoint, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        with opener(req, timeout=15) as r:
            return int(getattr(r, "status", 0) or r.getcode())
    except urllib.error.HTTPError as why:
        return int(why.code)
    except Exception:  # noqa: BLE001
        return 0


def _ld_script(doc) -> str:
    return '<script type="application/ld+json">' + json.dumps(doc, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + "</script>"


# 10. /app/ JSON-LD ---------------------------------------------------------------------------------------------------

def app_jsonld(base: str = BASE) -> dict:
    b = _base(base)
    return {"@context": "https://schema.org", "@graph": [
        {"@type": "SoftwareApplication", "name": "Knos", "url": b + "/app/", "description": ONE_LINE,
         "applicationCategory": "BusinessApplication", "operatingSystem": "Web",
         "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"}, "sameAs": [REPO]},
        {"@type": "WebSite", "name": "Knos", "url": b + "/app/",
         "potentialAction": {"@type": "SearchAction", "target": {"@type": "EntryPoint", "urlTemplate": b + "/app/?q={search_term_string}"},
                             "query-input": "required name=search_term_string"}}]}


def app_jsonld_script(base: str = BASE) -> str:
    return _ld_script(app_jsonld(base))
