import json
import re
import urllib.error
import xml.etree.ElementTree as ET

from knos_wanted import agent_files as af

BASE = "https://knos.onrender.com"
H = "ab" * 32
SM = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _copy_ok(text: str):
    low = text.lower()
    assert "—" not in text
    for w in ("escrow", "hackathon", "contest", "judge", "devpost", "colosseum", "prize", "demo", "marketplace",
              "kickstarter", "upwork", "algora"):
        assert w not in low, w


def test_llms_txt():
    code, body, ctype, _ = af.llms_txt(BASE)
    text = body.decode()
    assert code == 200 and ctype.startswith("text/markdown")
    assert text.startswith("# Knos\n") and "\n> " + af.ONE_LINE + "\n" in text
    assert "## Optional" in text and "{base}" not in text
    for path in ("/app/", "/mcp)", "/mcp/server-card", "/openapi.json"):
        assert BASE + path in text, path
    assert re.search(r"^- \[[^\]]+\]\(https://[^)]+\): \S", text, re.M)
    _copy_ok(text)


def test_robots_txt():
    code, body, ctype, _ = af.robots_txt(BASE)
    text = body.decode()
    assert code == 200 and ctype.startswith("text/plain")
    for bot in ("OAI-SearchBot", "Claude-SearchBot", "Claude-User", "ChatGPT-User", "Googlebot", "*"):
        assert f"User-agent: {bot}\nAllow: /\nDisallow: /api/" in text, bot
    assert f"Sitemap: {BASE}/sitemap.xml" in text


def test_sitemap_xml():
    code, body, ctype, _ = af.sitemap_xml(BASE, lastmod="2026-10-29")
    assert code == 200 and "xml" in ctype
    assert b"&amp;" not in body
    root = ET.fromstring(body)
    locs = [u.find(SM + "loc").text for u in root.findall(SM + "url")]
    mods = [u.find(SM + "lastmod").text for u in root.findall(SM + "url")]
    assert locs == [BASE + "/app/", "https://drexthealpha.github.io/Knos/proof/"]
    assert mods == ["2026-10-29", "2026-10-29"]


def test_sitemap_escapes_ampersand():
    _, body, _, _ = af.sitemap_xml("https://x.test/a&b")
    assert b"a&amp;b" in body
    ET.fromstring(body)


def test_ai_catalog():
    code, doc, ctype, headers = af.ai_catalog(BASE)
    doc = json.loads(json.dumps(doc))
    assert code == 200 and ctype == "application/ai-catalog+json"
    assert doc["specVersion"] == "1.0"
    assert doc["host"] == {"displayName": "Knos", "identifier": BASE, "documentationUrl": doc["host"]["documentationUrl"]}
    urls = {e["url"]: e["type"] for e in doc["entries"]}
    assert urls[BASE + "/mcp/server-card"] == "application/mcp-server-card+json"
    assert BASE + "/openapi.json" in urls and BASE + "/llms.txt" in urls
    assert headers["Access-Control-Allow-Origin"] == "*" and "max-age=3600" in headers["Cache-Control"]


def test_server_card():
    versions = af.supported_protocol_versions()
    assert versions and all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) for v in versions)
    code, card, ctype, headers = af.server_card(BASE, "0.4.1", versions)
    card = json.loads(json.dumps(card))
    assert code == 200 and ctype == "application/mcp-server-card+json"
    assert "$schema" not in card                  # its published schema URL answered 404
    assert re.fullmatch(r"[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+", card["name"]) and card["name"].endswith("/knos")
    assert 1 <= len(card["description"]) <= 100 and card["version"] == "0.4.1"
    assert card["repository"] == {"url": "https://github.com/drexthealpha/Knos", "source": "github"}
    assert card["remotes"] == [{"type": "streamable-http", "url": BASE + "/mcp", "supportedProtocolVersions": versions}]
    assert "tools" not in card and card["icons"][0]["src"].startswith("https://")
    assert headers["Access-Control-Allow-Origin"] == "*" and "max-age=3600" in headers["Cache-Control"]
    _copy_ok(card["description"])


def test_not_found_html():
    code, body, ctype, _ = af.not_found_html("/start/<script>")
    text = body.decode()
    assert code == 404 and ctype.startswith("text/html")
    assert "<h1>There is no page here</h1>" in text and "font-size:56px" in text
    assert 'href="https://knos.onrender.com/app/"' in text and 'href="https://drexthealpha.github.io/Knos/"' in text
    assert "prefers-color-scheme:dark" in text and "<script" not in text.lower() and "<link" not in text


def test_start_redirect():
    assert af.start_redirect() == (301, b"", "text/plain", {"Location": "https://drexthealpha.github.io/Knos/"})


def test_indexnow_body_and_key():
    key = af.read_key()
    assert key and re.fullmatch(r"[A-Za-z0-9-]{8,128}", key)
    code, body, ctype, _ = af.key_file(key)
    assert code == 200 and body.decode() == key and ctype.startswith("text/plain")
    assert af.key_file("../etc")[0] == 404
    urls = [f"{BASE}/trace.html?hash={i}" for i in range(10_005)] + ["https://other.test/x", f"{BASE}/app/"]
    b = af.indexnow(urls, key, f"{BASE}/{key}.txt", "knos.onrender.com")
    assert set(b) == {"host", "key", "keyLocation", "urlList"}
    assert b["host"] == "knos.onrender.com" and b["keyLocation"] == f"{BASE}/{key}.txt"
    assert len(b["urlList"]) == 10_000 and all(u.startswith(BASE + "/") for u in b["urlList"])
    json.dumps(b)


def test_indexnow_send_never_raises():
    seen = {}

    class R:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def ok(req, timeout):
        seen["timeout"], seen["data"], seen["method"] = timeout, json.loads(req.data), req.get_method()
        return R()

    def boom(req, timeout):
        raise OSError("no network")

    def refused(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 422, "bad", {}, None)

    body = af.indexnow([BASE + "/app/"], "k" * 32, BASE + "/" + "k" * 32 + ".txt", "knos.onrender.com")
    assert af.indexnow_send(body, opener=ok) == 202
    assert seen == {"timeout": 15, "data": body, "method": "POST"}
    assert af.indexnow_send(body, opener=boom) == 0
    assert af.indexnow_send(body, opener=refused) == 422
    assert af.indexnow_send({}, opener=ok) == 0


def test_app_jsonld():
    doc = json.loads(json.dumps(af.app_jsonld(BASE)))
    app, site = doc["@graph"]
    assert app["@type"] == "SoftwareApplication" and app["name"] == "Knos"
    assert app["applicationCategory"] == "BusinessApplication" and app["operatingSystem"] == "Web"
    assert app["offers"]["price"] == "0" and app["url"] == BASE + "/app/" and "https://github.com/drexthealpha/Knos" in app["sameAs"]
    assert site["@type"] == "WebSite"
    assert site["potentialAction"]["target"]["urlTemplate"] == BASE + "/app/?q={search_term_string}"
    assert af.app_jsonld_script(BASE).startswith('<script type="application/ld+json">')
