"""Knos's demand check as one service: a static page + a small JSON API, Python standard library only. Qloo is
reached ONLY from this server: its REST API (knos_wanted.qloo_rest, the primary path: POST /api/check) and, for the
older confirm-each-match flow, `qloo mcp` (knos_wanted.qloo_mcp). The browser never sees a key or calls Qloo.

    python -m knos_wanted serve            (HOST, default 127.0.0.1; PORT, default 8080)

POST /api/check {idea, place?, leader?}            the report and the code-made decision (no sign-in needed)
POST /api/wallet {}                                your passkey's wallet (made the first time); POST /api/wallet/faucet: test units
POST /api/maker/claim {report}                     the maker's passkey claims the milestone: pre-orders pay wallets it owns
POST /api/preorder {report, units}                 the challenge your passkey signs to lock test units for the maker
POST /api/sign {intent, authenticatorData, clientDataJSON, signature}   relay a passkey's answer (pre-order, factoring)
GET  /api/receivables; POST /api/lend/quote {commitment, advance_bps}; /api/factor {commitment, quote} (the maker sells);
POST /api/lend/advance {commitment}; /api/lend/collect {commitment}      factoring, every step signed by a passkey
POST /api/milestone {commitment, evidence_url}     verify the evidence; 2 of 3 referees sign PASS; release (signed in)
POST /api/refund {commitment}                      past the deadline: back to the buyer (signed in)
Rate limits per client address keep a public demo from draining the Qloo quota and the devnet test wallet.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import sys
import threading
import time
from collections import OrderedDict, defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import urllib.parse
from urllib.parse import parse_qs, urlparse

from . import outside
from . import agent, auth, blink, buyer, catalog, check, company, demand, escrow, front, planner, preorder, privacy, product_routes, referee, research, tasks, valley, wallets, x402
from .qloo_mcp import AGGREGATE, Lazy, Qloo, QlooUnavailable
from .qloo_rest import Client

STATIC = Path(__file__).parent / "static"
ROOT_ICONS = {"/favicon.ico": "favicon.ico", "/apple-touch-icon.png": "brand/apple-touch-icon.png",
              "/apple-touch-icon-precomposed.png": "brand/apple-touch-icon.png"}


def trusted_hops() -> int:
    """KNOS_WANTED_TRUST_PROXY: how many proxies in front of this server append to X-Forwarded-For (Render: 1).
    "0", unset or not a number: none, and the header is ignored."""
    v = (os.environ.get("KNOS_WANTED_TRUST_PROXY") or "").strip()
    return int(v) if v.isdigit() and 0 < int(v) <= 8 else 0


def client_key(xff: str, peer: str, cf: str = "") -> str:
    """The address a rate limit counts. Behind a trusted proxy, Cloudflare's CF-Connecting-IP when it is there (Render
    is fronted by Cloudflare, which sets it and overwrites any a client sends; the X-Forwarded-For entry a proxy
    appended was an edge address that changes request to request, so 40 calls in a row were never limited). Else each
    trusted proxy APPENDS the address it saw, so the entry the nearest trusted proxy wrote is the n-th from the END;
    anything before it was written by the client and can be forged."""
    hops = trusted_hops()
    if hops and cf.strip():
        return cf.strip()[:64]
    parts = [x.strip() for x in (xff or "").split(",") if x.strip()]
    if hops and parts:
        return parts[-hops if len(parts) >= hops else 0][:64]
    return str(peer)[:64]
MAX_BODY = 16_384
SESSION_S = 30 * 60
LIMITS = {"maker": (20, 600), "search": (40, 600), "buyer": (20, 600), "publish": (10, 600), "demo": (4, 600),
          "faucet": (2, 3600), "tx": (20, 600), "check": (30, 600), "taste": (30, 600), "mcp": (300, 600), "lock": (6, 600), "auth": (30, 600),
          "milestone": (30, 600), "milestone_one": (10, 3600), "referee": (120, 600), "product": (60, 600),
          "live": (120, 600)}   # (calls, seconds) per client; "live": presence and draft autosave, apart from "product"
GLOBAL_DEMO = (60, 3600)
FRONT_ORIGINS = ("https://drexthealpha.github.io",)               # the front door, allowed to read the demand check
PUBLIC_BASE = "https://knos.onrender.com"                       # this app's public address, in the files agents read
MCP_CHECK_TOOLS = ("knos_demand_check", "knos_cross", "knos_research_card")   # MCP tools that ask Qloo: the check limit
DEMAND_CORS = ("/api/qloo/status", "/api/check", "/api/demand/fields", "/api/cross", "/api/report", "/api/vectors", "/api/proof", "/api/ready/card", "/api/money", "/api/qloo-diff", "/api/agent/payout/latest", "/api/usage", "/api/counter", "/api/receipts", "/api/calls", "/api/match", "/api/record/head", "/api/forecasts", "/api/status", "/healthz")                                           # demo pre-orders, all clients
ROUTES = {"/api/trace/keep": "product", "/api/ask": "check", "/api/feedback": "product", "/api/qloo-diff": "product", "/api/open-signals": "check", "/api/ready/card": "product", "/api/company/need": "product", "/api/maker/start": "maker", "/api/maker/search": "search", "/api/maker/confirm": "maker", "/api/maker/publish": "publish",
          "/api/buyer/start": "buyer", "/api/buyer/confirm": "buyer", "/api/preorder/demo": "demo", "/api/preorder/faucet": "faucet",
          "/api/preorder/tx": "tx", "/api/preorder/submit": "tx",
          "/api/check": "check", "/api/test/record": "check", "/api/research": "check", "/api/cross": "check", "/api/factor": "lock",
          "/api/fund": "lock", "/api/task/submit": "check", "/api/anchor": "lock",
          "/api/auth/email": "auth", "/api/auth/email/verify": "auth", "/api/preorder": "lock", "/api/milestone": "milestone", "/api/refund": "lock",
          "/api/auth/challenge": "auth", "/api/auth/passkey/register": "auth", "/api/auth/passkey/login": "auth",
          "/api/auth/google": "auth", "/api/auth/guest": "auth",
          "/api/wallet": "tx", "/api/wallet/faucet": "faucet", "/api/sign": "tx", "/api/maker/claim": "lock", "/api/lend/quote": "lock",
          "/api/lend/advance": "lock", "/api/lend/collect": "lock", "/oauth/token": "auth"}
SIGNED_IN = ("/api/preorder", "/api/milestone", "/api/refund", "/api/factor", "/api/fund", "/api/task/submit", "/api/anchor",
             "/api/preorder/demo", "/api/preorder/faucet", "/api/preorder/tx", "/api/preorder/submit",
             "/api/wallet", "/api/wallet/faucet", "/api/sign", "/api/maker/claim", "/api/lend/quote", "/api/lend/advance", "/api/lend/collect")   # no anonymous money or faucet calls
# every GET route below (do_GET), for the OpenAPI document (knos_wanted.openapi); the product routes list their own
PAGES = {"/fields": "fields.html", "/money": "money.html", "/companies": "companies.html", "/trace": "trace.html", "/trace.html": "trace.html", "/with-without": "with_without.html", "/with-without.html": "with_without.html",
         "/qloo-safe-use": "qloo_safe_use.html", "/qloo-safe-use.html": "qloo_safe_use.html", "/invite": "invite.html", "/invite.html": "invite.html"}
GET_ROUTES = {"/actions.json": "Solana Actions rules", "/llms.txt": "This app for language models (llmstxt.org)", "/robots.txt": "Crawler rules: search and assistant bots allowed, /api/ left out", "/sitemap.xml": "The public pages and traces, with lastmod", "/.well-known/ai-catalog.json": "The AI catalog: the MCP Server Card, the OpenAPI document and llms.txt", "/mcp/server-card": "The MCP Server Card (SEP-2127): the /mcp remote and its protocol versions", "/trace.md": "A demand report trace as Markdown (?hash=)", "/trace": "A demand report trace page (?hash=), its verdict in the HTML", "/start": "301 to the Start page on the front door", "/start/": "301 to the Start page on the front door", "/api/refuse": "What Knos will not fund: the refuse list the Ready check applies", "/api/fields": "Fields: 7 bottlenecks by 7 technologies, 49 cells, each live or next",
              "/api/money": "The money page: what is held, released and charged, and the price list",
              "/api/vectors": "The seven product-value vectors, measured: cost, speed, friction, trust, capability, access, status",
              "/api/proof": "The latest real verdict this server reached (shown first on both front doors)",
              "/api/forecasts": "The forecast ledger's rows, Knos's picks with them (docs/reference/forecast_plan_v2.md)",
              "/api/ready/card": "A Ready card, read back from its devnet attestation (?hash= the criteria hash)",
              "/api/solvers": "Proven solvers first: wallets by verified milestones, each read back from devnet",
              "/fields": "Fields", "/money": "The money", "/with-without": "With and without Qloo: the 20 ideas, the table in the page", "/companies": "Companies", "/api/trace": "A demand report's Qloo calls, redacted: endpoint, params, ids, excerpt, limit",
              "/api/outside": "The outside counter: crossings and pre-order commitments by people outside Knos, summed from the store",
              "/api/outside/rows": "Every row the outside counter sums (kind, time, crossing id or order address, via)",
              "/api/qloo-diff": "The \"With and without Qloo\" table: 20 ideas, each checked with Qloo and with the key unset", "/sw.js": "The app's service worker (offline shell, background sync)",
              "/manifest.webmanifest": "The app's web app manifest (installable, home-screen shortcuts)", "/api/actions/preorder": "Solana Action (Blink): pre-order metadata",
              "/api/pay/fund": "Solana Pay transaction request: the label and icon a wallet shows before funding a milestone",
              "/api/cross": "Poll a live crossing", "/verify": "How we verify", "/api/crossings": "Crossings, newest first",
              "/api/front": "Research products open for backing now (the front door's list; ?slug= one product)",
              "/api/demand/fields": "The Qloo demand families F1-F8: every option's name, Qloo parameter, kind, help and example",
              "/api/tasks": "Open contributor rounds (knos.game)", "/api/memory/search": "Search the agent's memory (Sibyl)",
              "/api/x402/report": "A demand report, paid per read over x402", "/api/commitments": "Pre-orders and funders' held money",
              "/mcp": "MCP discovery page (POST JSON-RPC here)", "/mcp/store": "The app-store MCP profile: read-only tools, no sign-in, a daily call cap (POST JSON-RPC here)", "/auth/orcid": "Sign in with ORCID", "/auth/orcid/callback": "ORCID callback",
              "/": "301 to the front door, https://drexthealpha.github.io/Knos/", "/app": "301 to /app/",
              "/quality": "301 to the front door's quality page", "/quality/": "301 to the front door's quality page", "/app/": "The app", "/status/qloo": "Qloo as this server met it today: calls, cache hits, last success, last 429", "/api/qloo/status": "The same as JSON, with the line the front door shows while Qloo limits requests", "/api/record/head": "The Knos record's newest line in Sibyl: its sequence number, time and kind", "/api/calls": "The last 200 Qloo requests this server made or recorded: time, endpoint, parameters, status, ms, cached; never a body", "/api/match": "The products Qloo matched to a recorded idea (?idea=), for the step that asks whether this is what you mean", "/paid": "301 to /app/?all=1: the app with the passkey wallet, pre-orders, pools, company sign-in and accounting files", "/api/status": "Server status", "/api/ops/memory": "The operator's: this process's memory now and at its peak", "/api/agent/payout/latest": "The newest payout to an agent, read from devnet", "/api/usage": "Demand checks run, Ready briefs made, and the knos_pay program's devnet transactions", "/api/counter": "Live checks today and this week, checks by others, devnet pre-orders held and released, feedback answers", "/api/taste/movie": "The films a film's fans also love, from Qloo (?title=&year=): names and years only", "/api/products": "Listed products", "/api/quote": "Fee quote",
              "/api/pool": "A report's pre-order pool", "/healthz": "Health check", "/api/report": "A demand report",
              "/api/receipts": "A result's receipts (?id=, the first 16 hex of its hash): each Qloo call with its time and hash, the target's rule, the model's answer, the brief's criteria hash, the Sibyl record line, devnet transactions",
              "/api/commitment": "One commitment", "/api/auth/config": "Sign-in providers", "/api/fees": "Fees (config/fees.yaml)",
              "/api/receivables": "Receivables a lender can finance (passkey wallets: advance rate, fee, due date)",
              "/api/referee/group": "The FROST referee group (public)", "/api/referee/pending": "Open referee signing sessions",
              "/api/referee/session": "One referee signing session", "/api/prize/evidence": "A demo prize's public evidence (the round's verdict)",
              "/api/project/evidence": "A project attempt's public review (both pages and the claim ids)",
              "/.well-known/agent-card.json": "The A2A 1.0 Agent Card: the MCP endpoint, the OAuth 2.0 client-credentials flow, the skills",
              "/.well-known/oauth-authorization-server": "OAuth 2.0 authorization server metadata (RFC 8414): client credentials only",
              "/.well-known/oauth-protected-resource": "OAuth 2.0 protected resource metadata (RFC 9728): the MCP endpoint",
              "/.well-known/oauth-protected-resource/mcp": "The same metadata at the resource's own path (RFC 9728 section 3.1)"}
SUMMARIES = {"/api/check": "Demand check on Qloo", "/api/company/need": "Companies: one sentence to a Ready brief, a private demand check and an opened milestone", "/api/ready/card": "Attest a Ready brief on devnet: the shareable card", "/api/open-signals": "Demand from open signals only (no Qloo, keyless)", "/api/research": "Research card from a paper id", "/api/cross": "Start a crossing",
             "/api/preorder": "Pre-order on proof", "/api/milestone": "Post milestone evidence; 2 of 3 referees release",
             "/api/refund": "Refund past the deadline", "/api/fund": "Fund a milestone", "/api/factor": "Receivable financing offer",
             "/api/anchor": "Anchor the record root on devnet", "/api/task/submit": "Submit to a contributor round",
             "/oauth/token": "OAuth 2.0 token (RFC 6749 4.4, client credentials): an agent key's id and secret -> a one-hour Bearer token"}



DATA_SLOT = '<script type="application/json" id="k-data">null</script>'
_INLINE: dict = {}


def inline_css(page: str) -> str:
    """A page's two stylesheets written into it: each was a render-blocking request to this server (100 to 250 ms
    of server time on the free instance before the first paint). Their relative addresses are made absolute."""
    if "css" not in _INLINE:
        tokens = (STATIC / "brand" / "tokens.css").read_text(encoding="utf-8")
        tokens = tokens.replace('url("../fonts/', 'url("/static/fonts/').replace('url("mark.svg")', 'url("/static/brand/mark.svg")') \
            .replace('url("wordmark.svg")', 'url("/static/brand/wordmark.svg")')
        def tight(css: str) -> str:                   # no comments, one space per run of whitespace: the same rules
            return re.sub(r"\s+", " ", re.sub(r"/\*.*?\*/", "", css, flags=re.S)).strip()
        _INLINE["css"] = {'<link rel="stylesheet" href="/static/brand/tokens.css">': f"<style>{tight(tokens)}</style>",
                          '<link rel="stylesheet" href="/static/style.css">': f"<style>{tight((STATIC / 'style.css').read_text(encoding='utf-8'))}</style>"}
    for link, style in _INLINE["css"].items():
        page = page.replace(link, style, 1)
    return page


def money_doc() -> dict:
    """The money page's price list (money_data.MONEY) and the live payout fee with its floor, from config/fees.yaml."""
    from .money_data import MONEY
    f = preorder.fee_line()
    doc = {k: v for k, v in MONEY.items() if k != "pools"}
    fee = {"rate_bps": f.get("rate_bps") or 0, "floor": f.get("floor"), "status": f.get("status"), "source": "config/fees.yaml"}
    return {**doc, "fee": fee, "totals": _money_totals(fee)}


_totals_cache: dict = {"at": 0.0, "v": None}


def _money_totals(fee: dict) -> dict | None:
    """What is held, released and charged, summed over every public order (GET /api/projects is 800 KB: the page no
    longer downloads it to add three numbers). A private order's amount is not public: skipped. The sum runs in the
    background, at most once a minute, and the page shows the last one: over 577 projects a cold sum took 20 s, and
    under a champion run's load past 120 s, so /money timed out (run 40092771755)."""
    if time.time() - _totals_cache["at"] >= 60 and not _totals_cache.get("busy"):
        _totals_cache["busy"] = True
        threading.Thread(target=_sum_totals, args=(fee,), daemon=True, name="knos-money-totals").start()
    return _totals_cache["v"]


def _sum_totals(fee: dict) -> None:
    try:
        bps, floor = int(fee.get("rate_bps") or 0), float(fee.get("floor") or 0.05)
        held = released = charged = 0.0
        held_n = released_n = 0
        for p in valley.projects(100):
            for ms in p.get("milestones") or []:
                for o in ms.get("orders") or []:
                    held_n += o.get("status") == "locked"
                    released_n += o.get("status") == "released"
                    if o.get("units") is None:
                        continue
                    v = float(o["units"]) * float(o.get("unit_price") or 1)
                    if o.get("status") == "locked":
                        held += v
                    elif o.get("status") == "released":
                        released += v
                        charged += max(v * bps / 1e4, floor)
        out = {"held": round(held, 2), "released": round(released, 2), "charged": round(charged, 2), "unit": "test units",
               "held_n": held_n, "released_n": released_n, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _totals_cache.update(at=time.time(), v=out)
    except Exception:  # noqa: BLE001 - the price list still answers; the page says the totals are not readable now
        _totals_cache.update(at=time.time())
    finally:
        _totals_cache["busy"] = False


def memory_now(st) -> dict:
    """VmRSS and VmHWM (the peak since start) from /proc/self/status, in MB, the threads, the demand checks running and
    the reports held: what a load test reads before and after (Linux only; elsewhere the two sizes are None)."""
    mb = {}
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition(":")
            if k in ("VmRSS", "VmHWM"):
                mb[k] = round(int(v.split()[0]) / 1024, 1)
    except OSError:
        pass
    procs = []                                       # every process in the container (Render counts them all): name, MB
    for d in Path("/proc").glob("[0-9]*"):
        try:
            f = dict(line.split(":", 1) for line in (d / "status").read_text(encoding="utf-8").splitlines() if ":" in line)
            if "VmRSS" in f:
                cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
                procs.append({"pid": int(d.name), "name": f.get("Name", "").strip(), "rss_mb": round(int(f["VmRSS"].split()[0]) / 1024, 1),
                              "command": " ".join(w.rsplit("/", 1)[-1] for w in cmd.split()[:4])})   # program names, no paths
        except (OSError, ValueError):
            continue
    return {"rss_mb": mb.get("VmRSS"), "peak_mb": mb.get("VmHWM"), "threads": threading.active_count(),
            "checks_running": check.running[0], "checks_at_once": check.CHECKS_AT_ONCE, "reports_in_memory": len(st.reports),
            "processes": sorted(procs, key=lambda x: -x["rss_mb"])[:8], "all_processes_mb": round(sum(x["rss_mb"] for x in procs), 1)}


_payout_cache: dict = {"at": 0.0, "v": None}
# The app's home holds the demand check and the research products. The money and the company tools (passkey sign-in,
# pre-orders, pools, single sign-on, a company's multisig, accounting files) are the Paid on proof page, /paid: on the
# home each such block (<!-- paid:start --> to <!-- paid:end --> in static/index.html) leaves only an empty, hidden
# element per id, so the page's scripts still find what they bind to, and an address of a moved view goes to /paid.
PAID_BLOCK = re.compile(r"<!-- paid:start -->.*?<!-- paid:end -->", re.S)
MOVED_VIEWS = ("signin", "buy", "teams")
_VOID = {"input", "img", "br", "hr", "meta", "link"}
# the list of what can be pre-ordered stays on the home (#buy); one product's pre-order (#buy=<hash>) is on /paid
TO_PAID = ('<script>(() => { const go = () => { const h = location.hash.slice(1), v = h.split("=")[0]; '
           f'if ({list(MOVED_VIEWS)!r}.includes(v) && !(v === "buy" && !h.includes("="))) location.replace("/app/?all=1" + location.hash); }}; go(); '
           'addEventListener("hashchange", go); })();</script>')


def named(state, q: str) -> list[dict]:
    """The crossings this server ran and the checks it keeps (the recorded ones included) whose idea holds q, newest first."""
    from . import recorded
    want = " ".join(q.lower().split())
    seen, rows = set(), []
    for c in agent.crossings(state):
        idea = str(c.get("idea") or "")
        if want and want in idea.lower() and idea.lower() not in seen:
            seen.add(idea.lower())
            rows.append({"tier": "crossing", "name": idea, "key": c.get("report"), "snippet": f"verdict {c.get('verdict') or 'none yet'}, {c.get('status')}"})
    with recorded._lock:
        kept = sorted([*recorded._last.values(), *recorded._answered.values()], key=lambda r: str(r.get("made") or ""), reverse=True)
    for r in kept:
        idea = str(r.get("idea") or "")
        if want and want in idea.lower() and idea.lower() not in seen:
            seen.add(idea.lower())
            rows.append({"tier": "check", "name": idea, "key": r.get("hash"),
                         "snippet": f"verdict {(r.get('decision') or {}).get('verdict')}, Qloo answered {str(r.get('made') or '')[:10]}"})
    return rows[:20]


def home_page(page: str) -> str:
    """static/index.html as the home serves it: each paid block as hidden, empty stand-ins of its ids."""
    def stubs(m: re.Match) -> str:
        tags = re.findall(r'<([a-z][a-z0-9]*)\b[^>]*\bid="([^"]+)"', m.group(0))
        inner = "".join(f'<{t} id="{i}" hidden>' if t in _VOID else f'<{t} id="{i}" hidden></{t}>' for t, i in tags)
        return f'<div hidden data-moved="/app/?all=1">{inner}</div>'
    return PAID_BLOCK.sub(stubs, page).replace("</head>", TO_PAID + "\n</head>", 1)


REFEREE = "Released by the referee's verdict"
GITHUB = "Released by GitHub's signed check, verified on Solana"
OIDC_V2 = "FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W"


def released_by(tx: dict | None) -> str | None:
    """What released a payout, read from its own transaction: the referee's signed verdict (knos_pay's `knos3:verdict`
    log) or GitHub's signed check (knos-oidc verifying the token in the same transaction). None when neither."""
    meta = (tx or {}).get("meta") or {}
    logs = meta.get("logMessages") or []
    if any("knos3:verdict" in line for line in logs):
        return REFEREE
    if any(line.startswith(f"Program {OIDC_V2} invoke") for line in logs):
        return GITHUB
    return None


def latest_agent_payout() -> dict:
    """The newest milestone released to an attempt an agent key made, read back from devnet: the release
    transaction's confirmation and the test units the attempt's wallet received in it (its token balances before
    and after). Five minutes in a cache; {"found": false} when there is none or the chain does not answer."""
    v = _payout_cache["v"]
    if v is not None and time.time() - _payout_cache["at"] < (300 if v.get("found") else 30):
        return v
    best = None
    for p in valley._all("projects"):
        for m in p.get("milestones") or []:
            agents = {a.get("id"): a for a in m.get("attempts") or [] if a.get("agent_key")}
            for h in m.get("history") or []:
                what = str(h.get("what") or "")
                if not what.startswith("released to attempt "):
                    continue
                att = agents.get(what.rsplit(" ", 1)[-1])
                sigs = [s for o in h.get("orders") or [] for s in o.get("signatures") or []]
                if att and sigs and (best is None or h.get("at", "") > best[0]):
                    best = (h.get("at", ""), sigs[0], att.get("wallet"), p.get("title") or p.get("id"), (att.get("result") or {}).get("url"))
    out: dict = {"found": False}
    kept = valley._safe_load("pages", "latest-agent-payout")      # the last one read back confirmed: a redeploy keeps it
    if kept and (best is None or kept.get("at", "") > best[0]):
        best = (kept.get("at", ""), kept.get("signature"), kept.get("wallet"), kept.get("project"), kept.get("result"))
    if best:
        at, sig, wallet, title, result = best
        try:
            from knos import chain
            tx = chain.call(escrow.ledger().url, "getTransaction", [sig, {"encoding": "jsonParsed", "commitment": "confirmed",
                                                                         "maxSupportedTransactionVersion": 0}])
            meta = (tx or {}).get("meta") or {}
            def held(rows):
                return sum(float((b.get("uiTokenAmount") or {}).get("uiAmount") or 0) for b in rows or [] if b.get("owner") == wallet)
            units = held(meta.get("postTokenBalances")) - held(meta.get("preTokenBalances"))
            out = {"found": bool(tx) and meta.get("err") is None and units > 0, "signature": sig, "units": round(units, 6), "at": at, "project": title,
                   "slot": (tx or {}).get("slot"), "explorer": escrow.explorer(sig), "released": released_by(tx),
                   "result": result}             # the address of the work it paid for (a pull request, for an agent)
            if out["found"] and (not kept or kept.get("signature") != sig):
                valley._save("pages", "latest-agent-payout", {"at": at, "signature": sig, "wallet": wallet, "project": title, "result": result})
        except Exception as why:  # noqa: BLE001 - the chain did not answer: said, not guessed
            out = {"found": False, "why": f"{type(why).__name__}: {str(why)[:120]}"}
    _payout_cache.update(at=time.time(), v=out)
    return out


REPORTS_IN_MEMORY = 100


class State:
    def __init__(self, q: Qloo | None = None, rest: Client | None = None):
        self.q = q or Lazy()          # `qloo mcp` (120 MB) starts at the MCP flow's first use
        self.rest = rest or Client()
        self.cards: dict[str, dict] = {}
        self.last_anchor: dict | None = None
        self.reports: OrderedDict[str, dict] = OrderedDict()
        self.sessions: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self.hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self.lock = threading.Lock()
        self.qlock = threading.Lock()        # one Qloo conversation at a time over the one bridge

    def pair(self, key: tuple) -> None:
        """A verdict card was answered: the full card for the same idea, from the same address, within 5 minutes, is free."""
        with self.lock:
            self.__dict__.setdefault("pairs", {})[key] = time.monotonic()

    def paired(self, key: tuple) -> bool:
        with self.lock:
            t = self.__dict__.setdefault("pairs", {}).pop(key, None)
        return t is not None and time.monotonic() - t < 300

    HITS_IDLE_S = 3_600          # a client key with no call for an hour is dropped (every window here is an hour or less)
    HITS_KEYS = 10_000           # and at most this many keys are held, the longest idle going first

    def allow(self, client: str, kind: str) -> bool:
        n, window = LIMITS[kind]
        now = time.monotonic()
        with self.lock:
            self._sweep(now)
            checks = [((client, kind), n, window)] + ([(("*", "demo"), *GLOBAL_DEMO)] if kind == "demo" else [])
            for key, cap, win in checks:
                d = self.hits.get(key)
                while d and now - d[0] > win:
                    d.popleft()
                if d is not None and not d:
                    del self.hits[key]
                    d = None
                if d is not None and len(d) >= cap:
                    return False
            for key, _, _ in checks:
                self.hits[key].append(now)
            return True

    def _sweep(self, now: float) -> None:
        """Bounded memory: keys idle for HITS_IDLE_S go, then the longest idle beyond HITS_KEYS (a key per address and
        kind, and addresses are the caller's to choose). Called under self.lock, at most once a second."""
        if now - self.__dict__.get("_swept", -1e9) < 1 and len(self.hits) <= self.HITS_KEYS:
            return
        self._swept = now
        for key in [k for k, d in self.hits.items() if not d or now - d[-1] > self.HITS_IDLE_S]:
            del self.hits[key]
        if len(self.hits) > self.HITS_KEYS:
            for key, _ in sorted(self.hits.items(), key=lambda kv: kv[1][-1])[:len(self.hits) - self.HITS_KEYS]:
                del self.hits[key]

    def keep(self, r: dict) -> None:
        with self.lock:
            self.reports[r["hash"]] = r
            # the newest in memory, the rest read back from disk (report()): 500 full reports took about a fifth of the
            # free instance's 512 MB and it was killed for memory under a day of checks (24 Oct 2026)
            while len(self.reports) > REPORTS_IN_MEMORY:
                self.reports.popitem(last=False)

    def report(self, h) -> dict | None:
        with self.lock:
            got = self.reports.get(h) if isinstance(h, str) else None
        if got is None and isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h):
            f = escrow._state_dir() / "reports" / f"{h}.report"       # a decision report kept across restarts
            if f.exists():
                got = json.loads(f.read_text(encoding="utf-8"))
        if got is None and isinstance(h, str):
            from . import recorded                   # a sample chip's recorded card, by its hash (the trace of a fresh server)
            got = recorded.by_hash(h)
        return got

    def keep_check(self, r: dict) -> None:
        self.keep(r)
        if r.get("stale"):                                # a sample's last real card, shown while Qloo is down: memory only
            return
        d = escrow._state_dir() / "reports"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{r['hash']}.report").write_text(json.dumps(r, default=str), encoding="utf-8")

    def known(self, h) -> bool:
        return self.report(h) is not None or (isinstance(h, str) and catalog.get(h) is not None)

    def session(self, s: dict | None = None, sid: str | None = None, flow: str | None = None) -> dict:
        now = time.monotonic()
        with self.lock:
            for k in [k for k, (t, _) in self.sessions.items() if now - t > SESSION_S]:
                self.sessions.pop(k)
            if s is not None:
                self.sessions[s["id"]] = (now, s)
                while len(self.sessions) > 500:
                    self.sessions.popitem(last=False)
                return s
            got = self.sessions.get(sid or "")
        if got is None or (flow and got[1].get("flow") != flow):
            raise ValueError("unknown or expired session: start again")
        return got[1]


def _names(v, n: int = 3) -> list[str]:
    if isinstance(v, str):
        v = re.split(r"[,;\n]", v)
    return [s.strip()[:60] for s in (v or []) if isinstance(s, str) and s.strip()][:n]


def _text(v, n: int = 60) -> str | None:
    return v.strip()[:n] if isinstance(v, str) and v.strip() else None


def make_handler(state: State):
    class H(BaseHTTPRequestHandler):
        server_version = "knos-demand-check/0.3.33"

        def log_message(self, fmt, *args):  # no request logging: ideas and tastes are the visitor's; keys are never in URLs
            pass

        def _client(self) -> str:
            return client_key(self.headers.get("X-Forwarded-For", ""), self.client_address[0], self.headers.get("CF-Connecting-IP", ""))

        def _send(self, code: int, body, ctype: str = "application/json", headers: dict | None = None) -> None:
            data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
            self.send_response(code)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            # the front door (GitHub Pages) runs the same demand check from the browser: these answers, to that origin only,
            # never with credentials (no sign-in is needed to check demand)
            if urlparse(self.path).path in DEMAND_CORS and self.headers.get("Origin") in FRONT_ORIGINS and "Access-Control-Allow-Origin" not in (headers or {}):
                self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
                self.send_header("Vary", "Origin")
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            if not any(k.lower() == "cache-control" for k in (headers or {})):
                self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

        def _json(self) -> dict:
            if getattr(self, "_body", None) is not None:      # read once: the check's rate limit reads it first
                return self._body
            n = int(self.headers.get("Content-Length") or 0)
            if n > (4 * MAX_BODY if urlparse(self.path).path == "/api/qloo-diff" else MAX_BODY):   # the operator's table: 3 arms x 20 rows
                raise ValueError("request too large")
            got = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(got, dict):
                raise ValueError("send a JSON object")
            self._body = got
            return got

        def _base(self) -> str:
            host = self.headers.get("Host") or "localhost"
            proto = "https" if trusted_hops() or not host.startswith(("127.", "localhost")) else "http"
            return f"{proto}://{host}"

        def _redirect(self, to: str) -> None:
            self.send_response(302)
            self.send_header("Location", to)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_OPTIONS(self):
            return self._send(204, b"", "text/plain", blink.CORS)

        def do_GET(self):
            u = urlparse(self.path)
            outside.begin(self.headers)
            qs = parse_qs(u.query)
            if product_routes.handle_get(self, state, u, qs):
                return None
            if u.path == "/actions.json":
                return self._send(200, blink.RULES, headers=blink.CORS)
            if u.path == "/api/actions/preorder":
                rep = state.report((qs.get("report") or [""])[0])
                if rep is None:
                    return self._send(404, {"message": "unknown report"}, headers=blink.CORS)
                return self._send(200, blink.action(rep, self._base()), headers=blink.CORS)
            if u.path == blink.PAY_PATH:
                return self._send(200, blink.pay_get(self._base()), headers=blink.CORS)
            if u.path == "/api/cross":
                got = agent.poll((qs.get("id") or [""])[0], int((qs.get("since") or ["0"])[0] or 0))
                return self._send(200 if got else 404, got or {"error": "unknown crossing"})
            if u.path in ("/verify", "/verify.html"):
                return self._send(200, inline_css((STATIC / "verify.html").read_text(encoding="utf-8")).encode("utf-8"), "text/html; charset=utf-8")
            if u.path in ("/fields", "/money"):              # drawn from data in the page itself: nothing moves after the first paint
                from .fields_data import FIELDS
                from . import vectors
                data = json.dumps(FIELDS if u.path == "/fields" else money_doc(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
                page = (STATIC / PAGES[u.path]).read_text(encoding="utf-8").replace(DATA_SLOT, f'<script type="application/json" id="k-data">{data}</script>', 1)
                return self._send(200, inline_css(vectors.filled(page)).encode("utf-8"), "text/html; charset=utf-8")
            if u.path in PAGES:                              # the trace, "With and without Qloo", Qloo safe use, the invite
                from . import vectors
                page = (STATIC / PAGES[u.path]).read_text(encoding="utf-8")
                if u.path in ("/with-without", "/with-without.html"):     # its table in the page: drawn with no request first
                    try:
                        data = json.dumps(valley._load("pages", "qloo_diff"), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
                        page = page.replace(DATA_SLOT, f'<script type="application/json" id="k-data">{data}</script>', 1)
                    except valley.Refused:
                        pass                                 # not published yet: the page asks and says so
                if u.path in ("/trace", "/trace.html") and (qs.get("hash") or [""])[0]:   # the verdict in the HTML, for readers with no script
                    from . import agent_files as _af, trace as _trace
                    t = _trace.load(state, (qs.get("hash") or [""])[0])
                    if t:
                        ssr = _af.trace_html_head(t, base=PUBLIC_BASE)
                        page = page.replace("</head>", ssr["head"] + "</head>", 1).replace("<main", ssr["section"] + "<main", 1) \
                            if "<main" in page else page.replace("</head>", ssr["head"] + "</head>", 1).replace("</body>", ssr["section"] + "</body>", 1)
                return self._send(200, inline_css(vectors.filled(page)).encode("utf-8"), "text/html; charset=utf-8")
            if u.path == "/api/trace":                       # a report's Qloo calls, redacted (knos_wanted.trace)
                from . import trace as _trace
                t = _trace.load(state, (qs.get("hash") or [""])[0])
                return self._send(200 if t else 404, t or {"error": "unknown report: no trace kept for it"})
            if u.path == "/api/outside":                     # the outside counter, from the store (knos_wanted.outside)
                return self._send(200, outside.totals())
            if u.path == "/api/outside/rows":
                return self._send(200, {"rows": outside.rows(), "rule": outside.RULE})
            if u.path == "/api/refuse":                      # the published refuse list (knos.refuse), applied by every Ready check
                from knos import refuse
                return self._send(200, refuse.public())
            if u.path == "/api/fields":                      # the fields page: 7 bottlenecks by 7 technologies
                from .fields_data import FIELDS
                return self._send(200, FIELDS)
            if u.path == "/api/money":                       # the money page: the pools, and the share Knos needs at the live fee
                return self._send(200, money_doc())
            if u.path == "/api/solvers":                     # proven solvers first: verified milestones, read back from devnet
                from . import companies
                return self._send(200, companies.solvers())
            if u.path == "/api/vectors":                     # the seven product-value vectors, measured
                from . import vectors
                return self._send(200, vectors.vectors())
            if u.path == "/api/proof":                       # the latest real verdict, drawn first on both front doors
                from . import vectors
                return self._send(200, vectors.proof())
            if u.path == "/api/ready":                       # the Ready check is a POST: GET says how
                return self._send(200, {"what": "Ready to fund: is a brief clear enough to lock money on", "free": True, "stored": "nothing",
                                        "how": "POST /api/ready with a JSON body {\"brief\": {...}} (or the brief itself)",
                                        "answers": "ready (true or false), what is unclear, the criteria hash, and the intent sketch",
                                        "also": "the knos_ready tool on https://knos.onrender.com/mcp"})
            if u.path == "/api/ready/card":
                from . import track
                h = (qs.get("hash") or [""])[0]
                if not re.fullmatch(r"[0-9a-f]{64}", h):
                    return self._send(400, {"error": "hash: the brief's criteria hash (64 hex)"})
                return self._send(200, track.ready_card_get(h))
            if re.fullmatch(r"/ready/[0-9a-f]{64}", u.path):
                return self._send(200, (STATIC / "ready.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/qloo-diff":                   # the table behind "With and without Qloo"
                try:
                    return self._send(200, valley._load("pages", "qloo_diff"))
                except valley.Refused:
                    return self._send(404, {"error": "the table has not been published yet"})
            if u.path == "/api/demand/fields":               # one table for every interface's controls (knos.qloo_families)
                from . import families as _fam
                return self._send(200, _fam.fields())
            if u.path == "/api/front":                       # the front door's list (web/home.js asks it from github.io)
                slug = (qs.get("slug") or [""])[0]
                if slug:
                    got = front.resolve(state, slug)
                    return self._send(200 if got else 404, got or {"error": "unknown product"}, headers=front.CORS)
                return self._send(200, front.board(state), headers=front.CORS)
            if u.path == "/api/crossings":
                take = min(100, max(1, int((qs.get("take") or ["30"])[0] or 30)))
                offset = max(0, int((qs.get("offset") or ["0"])[0] or 0))
                rows = agent.crossings(state, offset + take)[offset:]
                return self._send(200, {"crossings": rows, "take": take, "offset": offset})
            if u.path == "/api/tasks":
                return self._send(200, tasks.listing())
            if u.path == "/api/memory/search":
                q = (qs.get("q") or [""])[0][:200]
                if not q.strip():
                    return self._send(400, {"error": "q: what to search the record for"})
                try:
                    from knos.record import search as rsearch
                    got = rsearch.search(q, root=company.root())
                    rows = [{k: r.get(k) for k in ("tier", "key", "category", "name", "doc_key", "snippet", "score")} for r in got.get("rows", [])[:20]]
                    said = got.get("said")
                    if not rows:                     # nothing in the record: the crossings and checks that name it, by their words
                        rows = named(state, q)
                        said = f"{len(rows)} crossing{'s' if len(rows) != 1 else ''} and checks name \"{q}\"." if rows else f"Nothing in the record or the crossings names \"{q}\"."
                    return self._send(200, {"query": q, "said": said, "verdict": got.get("verdict"), "rows": rows})
                except Exception as why:  # noqa: BLE001
                    return self._send(503, {"error": f"the record cannot be searched here ({type(why).__name__})"})
            if u.path == "/api/x402/report":
                h = (qs.get("hash") or [""])[0]
                rep_ = state.report(h)
                if rep_ is None:
                    return self._send(404, {"error": "unknown report"})
                if not x402.ready():
                    return self._send(503, {"error": "the paid route needs the devnet test wallet configured"})
                pay_h = self.headers.get("PAYMENT-SIGNATURE")
                try:
                    if not pay_h:
                        ch = x402.challenge(h, self._base())
                        return self._send(402, ch, headers={"PAYMENT-REQUIRED": x402.header(ch)})
                    settled = x402.settle(pay_h)
                except ValueError as why:
                    ch = {**x402.challenge(h, self._base()), "error": str(why)[:200]}
                    return self._send(402, ch, headers={"PAYMENT-REQUIRED": x402.header(ch)})
                return self._send(200, {**rep_, "paid": settled}, headers={"PAYMENT-RESPONSE": x402.header(settled)})
            if u.path == "/api/receivables":
                return self._send(200, {"receivables": wallets.receivables(), "money": wallets.MONEY,
                                        "model": "PayFi receivable financing: advance rate, fee, due date, repaid by the release"})
            if u.path == "/api/commitments":
                take = min(100, max(1, int((qs.get("take") or ["50"])[0] or 50)))
                offset = max(0, int((qs.get("offset") or ["0"])[0] or 0))
                return self._send(200, {"commitments": preorder.all_public(offset + take)[offset:], "take": take, "offset": offset})
            if u.path in ("/.well-known/agent-card.json", "/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource",
                          "/.well-known/oauth-protected-resource/mcp"):     # RFC 9728 also places it under the resource's path
                from . import agentkeys
                base = tasks.public_base(self._base())
                doc = agentkeys.card(base) if u.path.endswith("agent-card.json") else agentkeys.server_metadata(base) \
                    if u.path.endswith("authorization-server") else agentkeys.resource_metadata(base)
                return self._send(200, doc, headers={"Access-Control-Allow-Origin": "*"})
            if u.path in ("/mcp", "/mcp/store"):
                if "text/html" in (self.headers.get("Accept") or ""):
                    return self._send(200, agent.DISCOVERY.encode(), "text/html; charset=utf-8")
                url = tasks.public_base(self._base()) + u.path
                return self._send(200, {"name": "knos", "transport": "streamable-http", "protocolVersion": agent.PROTOCOL, "url": url,
                                        "tools_list": {"method": "POST", "url": url, "body": {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}},
                                        "install": f"claude mcp add --transport http knos {url}"})
            if u.path == "/auth/orcid":
                try:
                    return self._redirect(auth.orcid_authorize(self._base() + "/auth/orcid/callback"))
                except auth.AuthError as why:
                    return self._send(404, {"error": str(why)})
            if u.path == "/auth/orcid/callback":
                try:
                    s_ = auth.orcid_callback((qs.get("code") or [""])[0], (qs.get("state") or [""])[0], self._base() + "/auth/orcid/callback")
                    return self._redirect("/app/#session=" + s_["token"])
                except auth.AuthError as why:
                    return self._redirect("/app/#signin_error=" + urllib.parse.quote(str(why)[:120]))
            if u.path == "/":                                 # one front door: the Pages site
                return self._send(301, b"", "text/plain; charset=utf-8", {"Location": "https://drexthealpha.github.io/Knos/"})
            if u.path == "/app":
                return self._send(301, b"", "text/plain; charset=utf-8", {"Location": "/app/"})
            if u.path == "/index.html":                      # one app, one address: /app/
                return self._send(301, b"", "text/plain", headers={"Location": "/app/"})
            if u.path == "/paid":                            # the same app, its money and company tools shown: one address
                return self._send(301, b"", "text/plain", headers={"Location": "/app/?all=1"})
            if u.path in ("/app/", "/app/index.html"):
                from . import vectors
                page = (STATIC / "index.html").read_text(encoding="utf-8")
                page = page if (qs.get("all") or [""])[0] == "1" else home_page(page)
                # the newest projects in the page itself: /app/#projects shows its list at the first paint
                page = page.replace('<ul id="projList" class="plist"></ul>', f'<ul id="projList" class="plist">{valley.list_html(10)}</ul>', 1)
                pr = vectors.proof().get("proof")
                if pr:                                        # the proof shown first, in the page itself (at the first paint)
                    data = json.dumps(pr, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
                    page = page.replace('<script type="application/json" id="k-proof">null</script>',
                                        f'<script type="application/json" id="k-proof">{data}</script>', 1)
                from . import agent_files as _af               # SoftwareApplication + WebSite with its ?q= search action
                page = page.replace("</head>", _af.app_jsonld_script(PUBLIC_BASE) + "</head>", 1)
                return self._send(200, inline_css(vectors.filled(page)).encode("utf-8"), "text/html; charset=utf-8")
            if re.fullmatch(r"/receipts/[0-9a-f]{16}", u.path) or u.path == "/api/receipts":   # each number's source, row by row
                from . import receipts, result_page
                rid = u.path[10:] if u.path.startswith("/receipts/") else (qs.get("id") or [""])[0][:16]
                rep = result_page.find(state, rid) if re.fullmatch(r"[0-9a-f]{16}", rid) else None
                if u.path == "/api/receipts":
                    return self._send(200, receipts.doc(rep)) if rep else self._send(404, {"error": "no result has this id"})
                return self._send(200 if rep else 404, receipts.page(rep, rid).encode("utf-8"), "text/html; charset=utf-8")
            if re.fullmatch(r"/r/[0-9a-f]{16}\.(pdf|csv|json)", u.path):      # the result's downloads: brief PDF, calls CSV, Ready brief JSON
                from . import exports, result_page
                rid, ext = u.path[3:19], u.path[20:]
                rep = result_page.find(state, rid)
                if rep is None:
                    return self._send(404, {"error": "no result has this address"})
                name = f"knos-{rid}" + {"pdf": "-brief.pdf", "csv": "-calls.csv", "json": "-ready-brief.json"}[ext]
                body, ctype = {"pdf": lambda: (exports.pdf(rep, self._base() + "/r/" + rid), "application/pdf"),
                               "csv": lambda: (exports.csv_text(rep).encode("utf-8"), "text/csv; charset=utf-8"),
                               "json": lambda: (exports.json_text(rep).encode("utf-8"), "application/json")}[ext]()
                return self._send(200, body, ctype, headers={"Content-Disposition": f'attachment; filename="{name}"'})
            if re.fullmatch(r"/r/[0-9a-f]{16}", u.path):     # a demand result's permanent page, from the reports kept here
                from . import result_page
                rid = u.path[3:]
                rep = result_page.find(state, rid)
                return self._send(200 if rep else 404, result_page.page(rep, self._base() + u.path, rid).encode("utf-8"), "text/html; charset=utf-8")
            if u.path == "/api/forecasts":                 # the forecast ledger's rows, Knos's picks with them (forecast_plan_v2.md)
                from . import recorded
                with recorded._lock:
                    fc = dict(recorded._forecasts)
                return self._send(200 if fc else 404, fc or {"error": "no forecast rows on this server"}, headers={"Cache-Control": "no-store"})
            if u.path == "/status/qloo":                    # Qloo as this server met it today, from its own traffic: no call made
                from . import qloo_status
                return self._send(200, inline_css(qloo_status.page()).encode("utf-8"), "text/html; charset=utf-8")
            if u.path == "/api/record/head":                # the Knos record's newest line (Sibyl): its sequence number and time
                try:
                    from knos.record import journal
                    h = journal.head(company.root()) or (journal.remembered(journal.sibyl(company.root())) or [{}])[-1]
                    return self._send(200, {"seq": h.get("seq"), "at": h.get("ts"), "kind": h.get("kind")}, headers={"Cache-Control": "no-store"})
                except Exception as why:  # noqa: BLE001 - a record that cannot be read is said, never guessed
                    return self._send(503, {"seq": None, "why": f"the Knos record could not be read here ({type(why).__name__})"})
            if u.path == "/api/calls":                      # the last 200 Qloo requests: no body, no key (the front door's /calls/)
                from . import qloo_rest
                return self._send(200, {"calls": qloo_rest.recent(), "most": qloo_rest.RECENT.maxlen,
                                        "about": "time, endpoint, parameters, status, ms and cached; never a response body"}, headers={"Cache-Control": "no-store"})
            if u.path == "/api/match":                      # "Is this what you mean?": the products Qloo matched to a recorded idea
                from . import recorded
                idea = (qs.get("idea") or [""])[0][:200]
                names = recorded.matched(idea)
                return self._send(200, {"idea": idea, "matches": names[:4], "from": "recorded" if names else "none"})
            if u.path == "/api/qloo/status":                # the same for the front door's line above the chips
                from . import qloo_status
                return self._send(200, qloo_status.doc(), headers={"Cache-Control": "no-store"})
            if u.path in ("/sw.js", "/manifest.webmanifest"):        # the PWA: its worker's scope is the whole app
                ctype = "text/javascript; charset=utf-8" if u.path == "/sw.js" else "application/manifest+json"
                return self._send(200, (STATIC / u.path[1:]).read_bytes(), ctype, {"Cache-Control": "no-cache"})
            if u.path in ROOT_ICONS:                                    # where browsers look without a link: the crow
                f = STATIC / ROOT_ICONS[u.path]
                return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "image/x-icon", {"Cache-Control": "max-age=86400"})
            if u.path.startswith("/static/"):
                f = (STATIC / u.path[len("/static/"):]).resolve()
                if STATIC.resolve() in f.parents and f.is_file():
                    return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
                return self._send(404, {"error": "not found"})
            if u.path == "/api/status":
                return self._send(200, self.status())
            if u.path == "/api/taste/movie":                 # the films a film's fans also love (Knos's Qloo client; names and years only)
                from . import taste
                if not product_routes._admin(self.headers.get("X-Knos-Admin")) and not state.allow(self._client(), "taste"):
                    return self._send(429, {"error": "too many requests from this address; try again in a few minutes"})
                y = (qs.get("year") or [""])[0]
                from .qloo_rest import QlooError
                try:
                    return self._send(200, taste.also_love_movie(state.rest, (qs.get("title") or [""])[0], int(y) if y.isdigit() else None))
                except QlooError as why:                       # Qloo did not answer: 503 with the reason, in one sentence
                    from . import qloo_status
                    said = qloo_status.limit_line() if "429" in str(why) else None
                    return self._send(503, {"error": said or f"Qloo did not answer this time: {str(why)[:160]}"})
            if u.path == "/api/usage":                       # the public counter: checks and briefs from the store, payouts from devnet
                from . import usage
                return self._send(200, usage.counts())
            if u.path == "/api/counter":                     # live checks today and this week, others' checks, pre-orders, feedback
                from . import usage
                return self._send(200, usage.counter(_money_totals({"rate_bps": 0}) or {}), headers={"Cache-Control": "no-store"})
            if u.path == "/api/agent/payout/latest":         # the newest payout to an agent, as the chain has it
                return self._send(200, latest_agent_payout())
            if u.path == "/api/ops/memory":                  # the operator's: this process's memory now and at its peak
                if not product_routes._admin(self.headers.get("X-Knos-Admin")):
                    return self._send(403, {"error": "the operator's X-Knos-Admin key reads this"})
                return self._send(200, memory_now(state))
            if u.path == "/api/products":
                return self._send(200, {"products": catalog.products(), "aggregate": AGGREGATE})
            if u.path == "/api/quote":
                try:
                    units = int((qs.get("units") or ["5"])[0])
                    escrow._amount(units) if escrow.available() else None
                    return self._send(200, company.quote(units))
                except (ValueError, TypeError) as why:
                    return self._send(400, {"error": str(why)})
            if u.path == "/api/pool":
                h = (qs.get("hash") or [""])[0]
                try:
                    return self._send(200, escrow.pool(h))
                except escrow.EscrowUnavailable as why:
                    return self._send(503, {"error": str(why)})
                except Exception as why:  # noqa: BLE001
                    return self._send(400, {"error": f"{type(why).__name__}: {why}"[:300]})
            if u.path == "/healthz":
                return self._send(200, {"ok": True})
            agent_file = self._agent_file(u, qs)
            if agent_file:
                return self._send(*agent_file)
            if u.path in ("/quality", "/quality/"):          # the quality page is the front door's, measured at each build
                return self._send(301, b"", "text/plain", headers={"Location": "https://drexthealpha.github.io/Knos/quality/"})
            if u.path.startswith("/api/card/"):             # an Open card's downloads: pre-order text, outreach draft, refund date
                from . import story
                rep = state.report((qs.get("hash") or [""])[0])
                got = story.download(rep, u.path[len("/api/card/"):]) if rep else None
                if not got:
                    return self._send(404, {"error": "no such download: an Open card's preorder, outreach or refund.ics"})
                body, ctype, name = got
                return self._send(200, body.encode("utf-8"), ctype, {"Content-Disposition": f'attachment; filename="{name}"'})
            if u.path == "/api/report":
                rep = state.report((qs.get("hash") or [""])[0])
                if rep is None:
                    return self._send(404, {"error": "unknown report"})
                from . import recorded                       # read back later: "recorded <its day>", never LIVE
                rep = recorded.stored(rep)
                return self._send(200, {**rep, "preorders": preorder.of_report(rep["hash"]),
                                        "reserve": preorder.reserve_status(rep) if rep.get("kind") == check.KIND else None})
            if u.path == "/api/commitment":
                try:
                    rec = preorder.load((qs.get("id") or [""])[0])
                    try:
                        rec = blink.refresh(rec)
                    except Exception:  # noqa: BLE001 - the chain is unreachable: show what the server holds
                        pass
                    return self._send(200, preorder.public(rec))
                except ValueError as why:
                    return self._send(404, {"error": str(why)})
            if u.path == "/api/auth/config":
                return self._send(200, auth.config())
            if u.path == "/api/fees":
                return self._send(200, preorder.fee_line())
            if u.path.startswith("/api/referee/"):            # the FROST referee hosts (knos_wanted.referee)
                return self._send(*referee.get(u.path, qs))
            if u.path == "/api/project/evidence":             # a project attempt's public review (both pages, claim ids)
                page = valley.project_evidence((qs.get("id") or [""])[0])
                return self._send(200, page, "application/json") if page else self._send(404, {"error": "unknown evidence"})
            if u.path == "/api/prize/evidence":               # a round's public evidence: its verdict
                page = tasks.prize_evidence((qs.get("id") or [""])[0])
                return self._send(200, page, "application/json") if page else self._send(404, {"error": "unknown prize"})
            if "text/html" in (self.headers.get("Accept") or ""):   # a person's browser: a page with the way back
                from . import agent_files as _af
                return self._send(*_af.not_found_html())
            return self._send(404, {"error": "not found"})

        def _agent_file(self, u, qs) -> tuple | None:
            """The files agents and search engines read (knos_wanted.agent_files): llms.txt, robots.txt, the sitemap, the
            AI catalog and the MCP Server Card, the trace's Markdown twin, the IndexNow key, and /start's 301 to Pages."""
            from . import agent_files as af
            if u.path in ("/start", "/start/"):
                return af.start_redirect()
            if u.path == "/llms.txt":
                return af.llms_txt(base=PUBLIC_BASE)
            if u.path == "/robots.txt":
                return af.robots_txt(base=PUBLIC_BASE)
            if u.path == "/sitemap.xml":
                from . import trace as _trace
                try:
                    kept = sorted(p.stem for p in _trace._dir().glob("*.json"))[-2000:]
                except OSError:
                    kept = []
                return af.sitemap_xml(base=PUBLIC_BASE, trace_hashes=kept)
            if u.path == "/.well-known/ai-catalog.json":
                return af.ai_catalog(base=PUBLIC_BASE)
            if u.path == "/mcp/server-card":
                from . import __version__
                return af.server_card(base=PUBLIC_BASE, version=__version__, protocol_versions=list(agent.PROTOCOLS))
            if u.path == "/trace.md":
                from . import trace as _trace
                t = _trace.load(state, (qs.get("hash") or [""])[0])
                return af.trace_markdown(t, base=PUBLIC_BASE) if t else (404, {"error": "unknown report: no trace kept for it"}, "application/json", {})
            if u.path.endswith(".txt") and len(u.path) > 5:
                key = af.read_key()
                if key and u.path[1:-4] == key:
                    return af.key_file(key)
            return None

        def status(self) -> dict:
            from . import model as _model                # "on" or "off": whether the founder set a model key, never the key
            pf = preorder.preflight_status()
            rest = state.rest.status()
            mcp = state.q.status()
            from . import qloo_status
            q = qloo_status.doc()
            if rest["rest"] and q["limited"]:     # the key is set but Qloo limits it: said, never "live"
                top = {"mode": "limited", "label": q["line"] or "Qloo is limiting requests right now.", "reason": "Qloo's own limit headers and its last answers",
                       "mcp_flow": {k: mcp.get(k) for k in ("mode", "label", "reason")}}
            elif rest["rest"]:        # the decision path is Qloo's REST API: when it is live, the server is live
                top = {"mode": "live", "label": check.LIVE_LABEL, "reason": "Qloo REST API key configured on this server",
                       "mcp_flow": {k: mcp.get(k) for k in ("mode", "label", "reason")}}
            else:
                top = {"no_key_behaviour": "every check answers CANNOT_DECIDE (" + check.NO_EVIDENCE + "); pre-orders never open"}
            from . import qloo_harness
            hz = qloo_harness.harness()
            rest = {**rest, "harness_first": {"surface": qloo_harness.SURFACE, "on": hz.enabled(), "answered": hz.answered,
                                              "rule": "a call goes through the harness when every parameter maps onto a harness tool; else REST"}}
            from . import status_deps
            return {**mcp, **top, "model": _model.state(), "qloo_rest": rest, "preorders": pf, "record_anchor": state.last_anchor, "deps": status_deps.deps(),
                    "x402": {"ready": x402.ready(), "route": "/api/x402/report?hash=<report>", "price": f"{x402.PRICE_UNITS} test unit per read"},
                    "fees": preorder.fee_line(), "auth": auth.config(),
                    "framing": demand.FRAMING, "escrow": escrow.available(),
                    "demo_wallet": bool(os.environ.get("KNOS_WANTED_DEVNET_KEYPAIR")), "cluster": "devnet",
                    "relayer": preorder.relayer_funds(),
                    "record": company.root() is not None, "targets": ["brand", "place", "artist", "movie", "book", "podcast", "tv_show"]}

        def do_POST(self):
            u = urlparse(self.path)
            outside.begin(self.headers)                   # the outside counter reads who is asking (knos_wanted.outside)
            if u.path in ("/mcp", "/mcp/store"):
                return self._mcp("store" if u.path == "/mcp/store" else "full")
            if u.path == "/oauth/token":
                return self._oauth_token()
            if u.path in ("/api/actions/preorder", blink.PAY_PATH):
                return self._action(u)
            if u.path in ("/api/referee/commit", "/api/referee/share", "/api/referee/attest"):   # a referee host's FROST round (signed by its transport key)
                if not state.allow(self._client(), "referee"):
                    return self._send(429, {"error": "too many referee posts from this address"})
                try:
                    return self._send(*referee.post(u.path, self._json()))
                except ValueError as why:
                    return self._send(400, {"error": str(why)[:200]})
            if product_routes.handle_post(self, state, u.path):
                return None
            kind = ROUTES.get(u.path)
            if kind is None:
                return self._send(404, {"error": "not found"})
            # a verdict card and the full card that follows it for the same idea are one check against the limit
            pair, free = None, False
            if u.path == "/api/check":
                try:
                    pb = self._json()
                except ValueError as why:
                    return self._send(400, {"error": str(why)[:200]})
                pair = (self._client(), " ".join(str(pb.get("idea") or "").split()).lower()[:200])
                free = pb.get("stage") != "verdict" and state.paired(pair)
            self._free_check = free                         # the full card after its verdict: one live check, not two
            # the operator's own measured runs (scripts/qloo_vs_open_signals.py) carry its key and skip the per-address limits
            if not product_routes._admin(self.headers.get("X-Knos-Admin")) and not free and not state.allow(self._client(), kind):
                return self._send(429, {"error": "too many requests from this address; try again in a few minutes"})
            try:
                body = self._json()
                if u.path == "/api/task/submit":               # knos_task_submit's route: an agent key or its token too
                    from . import agentkeys
                    self.user = agentkeys.principal(self.headers.get("Authorization"))
                else:
                    self.user = auth.who(self.headers.get("Authorization"))
                if u.path in SIGNED_IN and self.user is None:
                    return self._send(401, {"error": "sign in first (passkey, Google or a guest label)"})
                if u.path == "/api/milestone" and not state.allow("commitment:" + str(body.get("commitment", ""))[:64], "milestone_one"):
                    return self._send(429, {"error": "this commitment had 10 evidence posts in the last hour; try again later"})
                if u.path.startswith("/api/auth/") or u.path in ("/api/check", "/api/test/record", "/api/research", "/api/cross", "/api/trace/keep", "/api/qloo-diff", "/api/open-signals", "/api/ready/card", "/api/company/need") + SIGNED_IN:
                    return self._send(200, self.route_v2(u.path, body))
                return self._send(200, self.route(u.path, body))
            except (auth.AuthError, wallets.NeedPasskey) as why:
                return self._send(401, {"error": str(why)[:300], "needs": "passkey" if isinstance(why, wallets.NeedPasskey) else None})
            except preorder.Settled as why:
                return self._send(409, {"error": str(why)[:300], "refused_by": "the order on devnet (read from the chain)"})
            except preorder.NotVerified as why:
                return self._send(422, {"error": f"milestone not verified: {why}"[:400], "verified": False})
            except escrow.EscrowUnavailable as why:
                return self._send(503, {"error": str(why)})
            except QlooUnavailable as why:
                return self._send(503, {"error": f"Qloo MCP: {why}"})
            except (privacy.PersonalData, demand.FlowError, planner.PlanError) as why:
                return self._send(400, {"error": str(why)[:400]})
            except (ValueError, TypeError, KeyError) as why:
                return self._send(400, {"error": str(why)[:300]})
            except Exception as why:  # noqa: BLE001 - never a raw Python error to the user: a generic line + a log line
                ref = hashlib.sha256(f"{time.time()}{id(why)}".encode()).hexdigest()[:10]
                print(f"knos-demand-check error {ref} {u.path}: {type(why).__name__}: {str(why)[:300]}", file=sys.stderr, flush=True)
                return self._send(502, {"error": f"the server could not finish this step (reference {ref}); nothing was charged", "ref": ref})

        def _origin(self) -> tuple[str, str]:
            host = (self.headers.get("Host") or "").split(":")[0]
            rp_id = os.environ.get("KNOS_WANTED_RP_ID") or host
            origin = self.headers.get("Origin") or ""
            o = urlparse(origin)
            if o.hostname != rp_id or (o.scheme != "https" and rp_id not in ("localhost", "127.0.0.1")):
                raise auth.AuthError("passkeys work only on this site's own https origin (or localhost)")
            return origin, rp_id

        def _mcp(self, profile: str = "full"):
            try:
                msg = self._json()
            except ValueError as why:
                return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(why)[:200]}})
            # a tool that asks Qloo or runs a check counts as a check; every other MCP message (initialize, tools/list,
            # reading a round, claiming, submitting) has its own, larger allowance: an agent's one task is dozens of them
            name = str(((msg.get("params") or {}) if isinstance(msg.get("params"), dict) else {}).get("name") or "")
            spends = msg.get("method") == "tools/call" and (name in MCP_CHECK_TOOLS or name.startswith("qloo_"))
            if not state.allow(self._client(), "check" if spends else "mcp"):
                return self._send(429, {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32000, "message": "rate limited"}})
            from . import qloo_rest
            qloo_rest.set_visitor(qloo_rest.visitor_hash(self._client()))   # an MCP demand check counts against the same visitor
            try:
                out = agent.mcp(state, msg, profile)
            finally:
                qloo_rest.set_visitor(None)
            if out is None:
                return self._send(202, b"", "text/plain")
            hdr = {"Mcp-Session-Id": "knos"} if msg.get("method") == "initialize" else {}
            need = ((out.get("result") or {}).get("structuredContent") or {}) if isinstance(out.get("result"), dict) else {}
            if need.get("needs") == "authorization":          # a write tool without a credential: where to get one (RFC 9728 5.1)
                hdr["WWW-Authenticate"] = f'Bearer resource_metadata="{need["resource_metadata"]}", scope="knos.solve"'
            return self._send(200, out, headers=hdr or None)

        def _oauth_token(self):
            """POST /oauth/token: client credentials, as a form body (RFC 6749 4.4) or JSON, the client by HTTP Basic or in the body."""
            from . import agentkeys
            if not state.allow(self._client(), "auth"):
                return self._send(429, {"error": "slow_down", "error_description": "too many token requests from this address"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._send(400, {"error": "invalid_request", "error_description": "request too large"})
            raw = self.rfile.read(n) if n > 0 else b""
            try:
                form = json.loads(raw or b"{}") if (self.headers.get("Content-Type") or "").startswith("application/json") else \
                    {k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}
            except (ValueError, UnicodeDecodeError):
                return self._send(400, {"error": "invalid_request", "error_description": "a form body: grant_type=client_credentials"})
            code, body, headers = agentkeys.token(form if isinstance(form, dict) else {}, self.headers.get("Authorization"))
            return self._send(code, body, headers=headers or None)

        def _action(self, u):
            qs = parse_qs(u.query)
            if not state.allow(self._client(), "lock"):
                return self._send(429, {"message": "too many pre-orders from this address; try again later"}, headers=blink.CORS)
            try:
                body = self._json()
                if u.path == blink.PAY_PATH:                    # Solana Pay: fund a milestone from any wallet
                    one = lambda k: (qs.get(k) or [""])[0]  # noqa: E731
                    return self._send(200, blink.pay_post(one("project"), one("milestone"), int(one("units") or 5), str(body.get("account", ""))),
                                      headers=blink.CORS)
                rep = state.report((qs.get("report") or [""])[0])
                if rep is None:
                    raise ValueError("unknown report")
                units = int((qs.get("units") or ["5"])[0])
                return self._send(200, blink.preorder_tx(rep, str(body.get("account", "")), units), headers=blink.CORS)
            except (ValueError, TypeError, escrow.EscrowUnavailable) as why:
                return self._send(400, {"message": str(why)[:300]}, headers=blink.CORS)
            except Exception as why:  # noqa: BLE001
                print(f"knos-demand-check action error: {type(why).__name__}: {str(why)[:300]}", file=sys.stderr, flush=True)
                return self._send(500, {"message": "the server could not build this transaction"}, headers=blink.CORS)

        def route_v2(self, path: str, body: dict) -> dict:
            """Knos's demand check on Qloo's REST API, pre-orders paid on proof, and sign-in."""
            if path == "/api/cross":
                ref, idea = _text(body.get("ref"), 200), _text(body.get("idea"), 500)
                privacy.check({"idea": idea, "place": body.get("place")})
                from knos import qloo_families
                opts = {k: body[k] for k in qloo_families.FIELDS if k in body}
                privacy.check({k: v for k, v in opts.items() if isinstance(v, str)})
                job = agent.start(state, ref=ref, idea=idea, place=_text(body.get("place")), product=_text(body.get("product"), 200),
                                  options=opts)
                outside.note("crossing", job["id"], "crossing")
                return {"id": job["id"], "status": job["status"]}
            if path == "/api/auth/email":
                return auth.email_link(str(body.get("email") or ""), self._base())
            if path == "/api/auth/email/verify":
                return auth.email_verify(str(body.get("token") or ""))
            user = self.user or {}
            if path in ("/api/factor", "/api/wallet", "/api/wallet/faucet", "/api/maker/claim", "/api/lend/quote", "/api/lend/advance",
                        "/api/lend/collect", "/api/sign"):
                return self.money(path, body, user)
            if path == "/api/fund":
                rep = state.report(body.get("report") or body.get("hash"))
                if rep is None or rep.get("kind") != check.KIND:
                    raise ValueError("unknown report: run the crossing first")
                return wallets.prepare_preorder(escrow.ledger(), user, rep, body.get("units", 5), self._rp(), funder=True)
            if path == "/api/anchor":
                got = company.anchor()
                if got.get("anchored"):
                    state.last_anchor = {"tx": got["tx"], "explorer": got["explorer"], "root": got["root"]}
                return got
            if path == "/api/task/submit" and user.get("kind") == "agent":   # its prize: the key's payout wallet, within its cap
                return agent._task_submit(body, user)
            if path == "/api/task/submit":
                return tasks.submit(str(body.get("round", "")), str(body.get("name", "")), str(body.get("code", "")),
                                    f"{user.get('kind')}: {user.get('label')}", sub=str(user.get("sub") or ""),
                                    wallet=_text(body.get("wallet"), 44), base=self._base())
            if path == "/api/feedback":                   # "Was this useful?": the result's hash, yes or no, a note; a salted visitor hash
                from . import qloo_rest, usage
                return usage.feedback(str(body.get("hash") or ""), body.get("useful") is True, str(body.get("note") or ""),
                                      qloo_rest.visitor_hash(self._client()))
            if path == "/api/ask":                        # one question about a result: the model, under its caps, only with a key
                from . import model as _model
                rep = state.report(str(body.get("hash") or ""))
                if rep is None:
                    raise ValueError("unknown result: send the result's hash")
                try:
                    return _model.follow_up(rep, str(body.get("question") or ""))
                except _model.Refused as why:
                    return {"refused": str(why), "model": _model.state()}
            if path == "/api/check":
                idea = body.get("idea")
                if not isinstance(idea, str) or not idea.strip():
                    raise ValueError("describe the idea")
                from knos import readings as _readings      # a paper's DOI is digits by its nature: it names a paper, never a person
                doi = _readings.doi_of(idea)
                privacy.check({"idea": "" if doi and doi == idea.strip() else idea, "place": body.get("place"), "leader": body.get("leader")})
                ex = body.get("exclude") or []
                if not isinstance(ex, list) or len(ex) > 20 or not all(isinstance(x, str) and len(x) < 80 for x in ex):
                    raise ValueError("exclude: a list of up to 20 Qloo entity ids the maker unticked")
                from knos import qloo_families
                opts = {k: body[k] for k in qloo_families.FIELDS if k in body and k != "exclude"}   # the families' fields, by name
                if ex:
                    opts["exclude"] = ",".join(ex)
                privacy.check({k: v for k, v in opts.items() if isinstance(v, str) and k != "exclude"})   # exclude: Qloo ids, checked above
                without = body.get("without_qloo") is True        # the same check with the key unset (the comparison)
                picked = body.get("picked") is True              # the reader picked this exact reading (which.py)
                if not picked and not without and not ex:
                    from . import which                         # which one do you mean? before any Qloo call
                    w = which.step(idea)
                    if w:
                        return w
                t0 = time.perf_counter()
                stage = "verdict" if body.get("stage") == "verdict" else None
                if stage:
                    state.pair((self._client(), " ".join(idea.split()).lower()[:200]))
                from . import qloo_rest                     # 10 live checks per visitor an hour (a salted hash, never the address)
                capped = None if without or getattr(self, "_free_check", False) else qloo_rest.visitor_take(qloo_rest.visitor_hash(self._client()))
                rep = check.demand_check(idea, _text(body.get("place")), _text(body.get("leader"), 80),
                                         client=Client(key="") if without else state.rest, exclude=ex, options=opts, stage=stage,
                                         only_cache=capped)
                if without:
                    rep["without_qloo"] = True
                else:
                    from . import recorded                   # Qloo not answering: said, or the sample's last real card
                    rep = recorded.honest(idea, rep, picked=picked)
                    if stage or not getattr(self, "_free_check", False):     # the verdict and its full card: one check
                        from . import usage
                        usage.bump_live(int((rep.get("qloo_calls") or {}).get("live") or 0))
                rep["fees"] = preorder.fee_line()
                card = state.cards.get(str(body.get("research") or ""))
                if card:
                    rep["research"] = {**card, "why_never_crossed": research.why_never_crossed(card, rep)}
                rep["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)
                if isinstance(rep.get("qloo_calls"), dict):
                    rep["qloo_calls"] = {**rep["qloo_calls"], "ms": rep["elapsed_ms"]}
                from . import story                          # the decision first: sentence, tiles, used words, reruns
                rep["story"] = story.build(rep)
                if not rep.get("queued"):
                    rep["record"] = {"recorded": False, "why": "a last real card, already recorded"} if rep.get("stale") else company.record_check(rep)
                state.keep_check(rep)
                if not rep.get("stale") and not rep.get("queued"):
                    from . import vectors
                    vectors.note("check", rep["elapsed_ms"], rep, state)   # speed and cost, measured; a real verdict is the proof shown first
                return rep
            if path == "/api/test/record" and os.environ.get("KNOS_TEST_MODE") == "1":   # test mode only: a stub last card
                from . import recorded
                with recorded._lock:
                    recorded._last[recorded.key(str(body.get("key") or ""))] = dict(body.get("card") or {})
                return {"kept": True}
            if path == "/api/company/need":                # companies mode: one sentence -> Ready brief, private check, opened milestone
                if not self.user:
                    raise auth.AuthError("sign in first: company SSO (one press), or any Knos session")
                from . import companies
                return companies.need(_text(body.get("need"), 300) or "", self.user, body.get("open") is True, state)
            if path == "/api/ready/card":                  # a Ready brief, attested on devnet once: the shareable card
                from . import track
                brief = body.get("brief") if isinstance(body.get("brief"), dict) else body
                return track.ready_card(brief)
            if path == "/api/open-signals":                 # the no-Qloo baseline: keyless public sources, each named
                from . import open_signals
                idea = _text(body.get("idea"), 500) or ""
                privacy.check({"idea": idea})
                if len(idea.split()) < 2:
                    raise ValueError("idea: a few words saying what the product is")
                cc = (_text(body.get("country"), 2) or "US").upper()
                return open_signals.baseline(idea, cc if cc.isalpha() else "US")
            if path == "/api/trace/keep":                   # keep a report's trace on devnet: something links to it
                from . import trace as _trace
                return _trace.keep(state, str(body.get("hash") or ""))
            if path == "/api/qloo-diff":                     # the operator publishes the "With and without Qloo" table
                if not product_routes._admin(self.headers.get("X-Knos-Admin")):
                    raise auth.AuthError("the operator's X-Knos-Admin key publishes this table")
                rows = body.get("rows")
                if not isinstance(rows, list) or not 1 <= len(rows) <= 60:
                    raise ValueError("rows: 1 to 60")
                doc = {"v": 2 if body.get("baseline") else 1, "made": body.get("made"), "summary": body.get("summary"), "rows": rows,
                       "rule": body.get("rule"), "baseline": body.get("baseline"), "rules": body.get("rules")}
                valley._save("pages", "qloo_diff", doc)
                return {"published": len(rows), "page": "/with-without"}
            if path == "/api/research":
                card = research.research_card(str(body.get("ref") or ""), product=_text(body.get("product"), 200))
                with state.lock:
                    state.cards[card["hash"]] = card
                    while len(state.cards) > 300:
                        state.cards.pop(next(iter(state.cards)))
                return card
            if path == "/api/auth/challenge":
                return {"challenge": auth.challenge(), "rp_id": os.environ.get("KNOS_WANTED_RP_ID") or (self.headers.get("Host") or "").split(":")[0]}
            if path == "/api/auth/passkey/register":
                origin, _ = self._origin()
                return auth.register(body, origin, str(body.get("label") or ""))
            if path == "/api/auth/passkey/login":
                origin, rp_id = self._origin()
                return auth.login(body, origin, rp_id)
            if path == "/api/auth/google":
                return auth.google(body.get("credential"))
            if path == "/api/auth/guest":
                return auth.guest(str(body.get("label") or ""))
            if path == "/api/preorder":
                rep = state.report(body.get("report") or body.get("hash"))
                if rep is None or rep.get("kind") != check.KIND:
                    raise ValueError("unknown report: run the demand check first")
                return wallets.prepare_preorder(escrow.ledger(), user, rep, body.get("units", 5), self._rp())
            rec = preorder.load(str(body.get("commitment", "")))
            rec = blink.refresh(rec)
            if path == "/api/milestone":
                return preorder.milestone(state.report(rec["report"]) or {}, rec["order"], str(body.get("evidence_url", "")))
            return preorder.refund(rec["order"])

        def _rp(self) -> str:
            return os.environ.get("KNOS_WANTED_RP_ID") or (self.headers.get("Host") or "").split(":")[0]

        def money(self, path: str, body: dict, user: dict) -> dict:
            """Every step that moves money is signed by the person's own passkey (knos_wanted.wallets)."""
            led = escrow.ledger()
            if path == "/api/sign":
                return wallets.sign(led, user, body)
            h = wallets.holder(user)
            if path == "/api/wallet":
                return wallets.public(led, h, self._rp())
            if path == "/api/wallet/faucet":
                return wallets.faucet(led, h, self._rp())
            if path == "/api/maker/claim":
                rep = state.report(body.get("report") or body.get("hash"))
                if rep is None or rep.get("kind") != check.KIND:
                    raise ValueError("unknown report: run the demand check first")
                return wallets.claim_maker(led, user, rep, self._rp())
            c = str(body.get("commitment", ""))
            if path == "/api/factor":
                return wallets.prepare_accept(led, user, c, str(body.get("quote", "")))
            if path == "/api/lend/quote":
                return wallets.quote(led, user, c, body.get("advance_bps", 9000), self._rp())
            if path == "/api/lend/advance":
                return wallets.prepare_advance(led, user, c, self._rp())
            return wallets.prepare_collect(led, user, c, self._rp())

        def route(self, path: str, body: dict) -> dict:
            if path == "/api/maker/start":
                idea = body.get("idea")
                if not isinstance(idea, str) or not idea.strip():
                    raise ValueError("describe the idea")
                with state.qlock:
                    s = demand.start(state.q, idea, _names(body.get("rivals")), _text(body.get("place")), _names(body.get("variants")) or None)
                return state.session(s)
            if path == "/api/maker/search":
                s = state.session(sid=body.get("session"), flow="maker")
                name = _text(body.get("name"))
                if not name:
                    raise ValueError("type a name to look up")
                with state.qlock:
                    return {"question": demand.search(state.q, s, str(body.get("key", "")), name), "trail": s["trail"]}
            if path == "/api/maker/confirm":
                s = state.session(sid=body.get("session"), flow="maker")
                if not isinstance(body.get("choices"), dict):
                    raise ValueError("choices: an object")
                with state.qlock:
                    rep = demand.confirm(state.q, s, body["choices"])
                rep["record"] = company.record_report(rep)
                state.keep(rep)
                return rep
            if path == "/api/maker/publish":
                rep = state.report(body.get("hash"))
                if rep is None:
                    raise ValueError("unknown report: build the report first")
                return {"product": catalog.publish(rep, str(body.get("title", ""))), "quote": company.quote(5)}
            if path == "/api/buyer/start":
                with state.qlock:
                    return state.session(buyer.start(state.q, body.get("likes"), body.get("vibes"), body.get("targets")))
            if path == "/api/buyer/confirm":
                s = state.session(sid=body.get("session"), flow="buyer")
                if not isinstance(body.get("choices"), dict):
                    raise ValueError("choices: an object")
                with state.qlock:
                    return buyer.confirm(state.q, s, body["choices"])
            h = body.get("hash")
            if path == "/api/preorder/faucet":
                return escrow.faucet(str(body.get("owner", "")))
            if not state.known(h):
                raise ValueError("unknown report: build the report or pick a listed product first")
            units = body.get("units", 5)
            if path == "/api/preorder/tx":
                return escrow.wallet_tx(h, str(body.get("owner", "")), units)
            if path == "/api/preorder/demo":
                raise ValueError("removed: no server key buys for anyone; a pre-order is signed by your own passkey (POST /api/preorder) "
                                 "or your own wallet (POST /api/preorder/tx)")
            res = escrow.submit(str(body.get("transaction", "")), str(body.get("owner", "")))
            res.update(owner=str(body.get("owner", "")), amount_units=units, order=body.get("order"), buyer_kind="wallet")
            rep = state.report(h) or catalog.get(h) or {}
            q = company.quote(units)
            res["fees"] = q
            res["record"] = company.record_preorder(h, res, q, synthetic_report=rep.get("mode") != "live")
            if res["record"].get("recorded") and os.environ.get("KNOS_WANTED_DEVNET_KEYPAIR") and os.environ.get("KNOS_WANTED_ANCHOR", "1") == "1":
                res["anchor"] = company.anchor()
            return res

    return H


def _restore_projects(budget_s: float = 60.0) -> None:
    """A redeploy starts on an empty disk: read the projects back from their devnet records (knos_wanted.chainstate),
    within `budget_s`; a failure is said in the log and the app starts anyway."""
    from . import chainstate
    if not chainstate.on() or any(valley._dir("projects").glob("*.json")):
        return
    box: dict = {}

    def run():
        try:
            from . import trace as _trace

            from . import privacy

            def put(kind, key, obj):
                obj, n = privacy.scrub(obj)              # no email address comes back from devnet into the store
                box["scrubbed"] = box.get("scrubbed", 0) + n
                if n and kind != "traces":
                    valley._save(kind, key, obj)         # and the devnet copy is rewritten without it
                    return
                if kind == "projects":
                    valley._save(kind, key, obj, chain=False)
                elif kind == "traces":
                    _trace.restore_save(kind, key, obj)
                else:
                    valley._save(kind, key, obj, chain=False)
            box["n"] = chainstate.restore(put)
            box["scrubbed"] = box.get("scrubbed", 0) + privacy.scrub_disk(escrow._state_dir())
            money_doc()                                  # the money page's totals are summed once now, in the background
        except Exception as why:  # noqa: BLE001
            box["error"] = f"{type(why).__name__}: {str(why)[:200]}"
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(budget_s)
    print(f"knos chainstate: restored {box.get('n', 0)} project(s) from devnet; {box.get('scrubbed', 0)} email address(es) replaced"
          + (f"; {box['error']}" if "error" in box else "")
          + ("" if not t.is_alive() else f"; still reading after {budget_s:.0f} s"), flush=True)


def serve(host: str | None = None, port: int | None = None) -> None:
    os.environ.setdefault("SIBYL_MEMORY_TELEMETRY", "0")     # Sibyl's heartbeat is off on this server (its documented opt-out)
    host = host or os.environ.get("HOST", "127.0.0.1")
    port = port or int(os.environ.get("PORT", "8080"))
    state = State()
    _restore_projects()                    # before serving: the projects kept on devnet, when this disk has none
    threading.Thread(target=lambda: preorder.preflight_status(force=True), daemon=True).start()   # the money path, simulated
    threading.Thread(target=tasks.available, daemon=True).start()        # seeds the demo round when no round is open
    valley.start_sweeper()                 # missed milestone deadlines: refund + reopen, every KNOS_VALLEY_SWEEP_S seconds
    threading.Thread(target=valley.warm_summaries, daemon=True, name="projects-summary").start()   # /app/#projects reads a file
    from . import qloo_harness
    threading.Thread(target=qloo_harness.harness().warm, daemon=True, name="qloo-harness-warm").start()
    # no sample idea is run at boot: each chip's recorded card is its last real answer, read from the private secret
    # file (recorded.load), else the first real answer a reader's own press gets (recorded.keep); a restart asks Qloo nothing
    from . import recorded
    print(f"knos recorded: {recorded.load()} of {len(recorded.CHIPS)} sample chips have a recorded card", flush=True)
    # the seeded research products cross on the first request for the board (front.board), never at boot
    httpd = ThreadingHTTPServer((host, port), make_handler(state))
    rest_ok, rest_why = state.rest.ready()
    print(f"Knos demand check on http://{host}:{port}  Qloo REST: {'on' if rest_ok else 'off (' + rest_why + ')'}  "
          f"Qloo MCP: {state.q.status().get('mode')}  pre-orders on proof: preflight running (see /api/status)", flush=True)
    try:
        httpd.serve_forever()
    finally:
        state.q.close()
