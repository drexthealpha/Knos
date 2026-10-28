"""HTTP routes for projects (knos_wanted.valley), companies (knos_wanted.enterprise), evidence provenance
(knos_wanted.provenance) and the OpenAPI document. server.py hands every request here first; None = not ours.

Every route is listed once in ROUTES below (method, path, who may call it, what it takes); knos_wanted.openapi builds
/openapi.json from this table and server.ROUTES, so the document and the server cannot drift apart.
"""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.parse

from . import enterprise, proofs, provenance, valley

MAX_MEDIA_BODY = provenance.MAX_MEDIA

# (method, path, signed_in, summary, body or query fields)
ROUTES = [
    ("GET", "/api/templates", False, "Milestone templates and OpenRegulatory regulatory sets", {}),
    ("GET", "/api/projects", False, "Projects, newest first", {"take": "integer"}),
    ("GET", "/api/cross/stream", False, "A crossing's steps as Server-Sent Events while it runs", {"id": "string", "since": "integer"}),
    ("POST", "/api/draft", True, "Keep the brief you are writing for your passkey (every save is a version)", {"brief": "object", "title": "string"}),
    ("POST", "/api/draft/get", True, "Your latest draft and its timeline, on any device you sign in on", {}),
    ("POST", "/api/draft/forget", True, "Forget every draft kept for your passkey", {}),
    ("POST", "/api/presence", False, "Your pointer on a project page, and everyone else's there now (live cursors)",
     {"page": "string", "me": "string", "x": "number", "y": "number", "label": "string"}),
    ("GET", "/api/sns", False, "Who owns a .sol name on this cluster (Name Service), for a project that names one", {"name": "string"}),
    ("GET", "/api/price", False, "A Pyth price (EUR/USD, GBP/USD, SOL/USD, BTC/USD, ETH/USD), for a milestone in another currency", {"pair": "string"}),
    ("POST", "/api/evidence/evm", False, "Verify an EVM-signed attestation with Solana's Secp256k1 precompile (a devnet transaction)",
     {"eth_address": "string", "signature": "string", "message": "string"}),
    ("GET", "/api/track", False, "A wallet's track record: its Solana Attestation Service attestations of verified milestones",
     {"wallet": "string"}),
    ("GET", "/api/project/prompt", False, "What an agent working on a milestone is handed: the locked intent, effort and budget",
     {"project": "string", "milestone": "string"}),
    ("POST", "/api/ready/resolve", False, "Keep the reading a buyer tapped for a vague word (offered first next time)",
     {"word": "string", "reading": "string", "target": "string"}),
    ("POST", "/api/ready", False, "Ready to fund: is a brief clear enough to lock money on (free; nothing stored)", {"brief": "object"}),
    ("POST", "/api/project/brief", True, "The buyer edits a project's brief (until money locks)", {"project": "string", "brief": "object"}),
    ("POST", "/api/project/change", True, "After lock: the buyer proposes a change request (a new criteria hash)",
     {"project": "string", "brief": "object", "why": "string"}),
    ("POST", "/api/project/change/decide", True, "The maker accepts or rejects a change request", {"project": "string", "change": "string", "accept": "boolean"}),
    ("POST", "/api/project/cancel", True, "The buyer cancels: the maker keeps the kill fee agreed before lock", {"project": "string"}),
    ("POST", "/api/project/archive", False, "Take a project off the public list (still readable by id): its buyer, signed in, or the operator's X-Knos-Admin key",
     {"project": "string", "why": "string"}),
    ("POST", "/api/project/dispute", True, "Dispute a referee verdict inside its challenge window, with evidence",
     {"project": "string", "milestone": "string", "attempt": "string", "url": "string"}),
    ("GET", "/api/project", False, "One project with its milestones, orders, attempts and routing", {"id": "string"}),
    ("GET", "/api/project/route", False, "Where a milestone's work can be bought (labs, knos.game) and its quotes", {"project": "string", "milestone": "string"}),
    ("POST", "/api/project", True, "Open a project from a template (+ regulatory sets); deadline_s for a one-day sandbox",
     {"template": "string", "title": "string", "regulatory": "array", "report": "string", "team": "string", "deadline_s": "integer"}),
    ("POST", "/api/sandbox", True, "A one-day devnet sandbox project from a template", {"template": "string", "title": "string", "team": "string"}),
    ("POST", "/api/project/fund", False, "Fund one milestone (funder, grant or pool): the devnet transaction a wallet signs, or with passkey=true the step your passkey approves",
     {"project": "string", "milestone": "string", "units": "integer", "account": "string", "kind": "string", "grant": "object", "ref": "string", "pool": "string", "passkey": "boolean"}),
    ("POST", "/api/project/private", False, "A private order's encrypted amount and its ZK ElGamal proofs, verified on devnet",
     {"order": "string", "ciphertext": "base64", "pubkey_proof": "base64", "range_proof": "base64"}),
    ("POST", "/api/project/confirm", False, "Mark a funding locked once its order is on devnet", {"order": "string", "signature": "string"}),
    ("POST", "/api/project/pool", False, "Megafund: one funder spreads units over 2-8 milestones (one transaction each)",
     {"allocations": "array", "units": "integer", "account": "string", "ref": "string"}),
    ("POST", "/api/project/amc", False, "Advance-market commitment: an allowance collected only when the milestone verifies (passkey=true: your passkey approves it)",
     {"project": "string", "milestone": "string", "units": "integer", "account": "string", "passkey": "boolean"}),
    ("POST", "/api/project/amc/confirm", False, "Mark an AMC allowance approved once it is on devnet", {"amc": "string", "signature": "string"}),
    ("POST", "/api/project/claim", True, "A maker attempts a milestone and binds its payee wallet (passkey=true: paid to your passkey wallet)", {"project": "string", "milestone": "string", "wallet": "string", "passkey": "boolean"}),
    ("POST", "/api/project/post", True, "Post a result (the maker) or an independent check (someone else, another site)",
     {"project": "string", "milestone": "string", "attempt": "string", "url": "string", "role": "string"}),
    ("POST", "/api/project/operator", False, "The operator (X-Knos-Admin): open a project bound to a GitHub repository from a Ready brief, "
     "fund a milestone from the app's devnet test wallet, or claim it for CI",
     {"action": "string", "brief": "object", "title": "string", "repo": "string", "project": "string", "milestone": "string",
      "units": "integer", "wallet": "string"}),
    ("POST", "/api/project/ci", False, "Release a milestone whose check passed in CI: GitHub's record of the commit decides it",
     {"project": "string", "milestone": "string", "sha": "string"}),
    ("POST", "/api/project/solve", True, "A referee-checked milestone (knos-referee:<round>): claim it if needed, submit code to its round, released on a passing verdict "
     "(an agent key or its OAuth token is enough)", {"project": "string", "milestone": "string", "code": "string", "wallet": "string"}),
    ("GET", "/api/agent/keys", True, "Your agent keys: caps, counters and state (never a secret)", {}),
    ("POST", "/api/agent/keys", True, "Make a capped, revocable agent key (shown once): an OAuth 2.0 client for /oauth/token",
     {"label": "string", "max_claims": "integer", "max_spend_units": "integer", "days": "integer", "payout_wallet": "string"}),
    ("POST", "/api/agent/keys/revoke", True, "Revoke one of your agent keys: it and its access tokens stop at once", {"id": "string"}),
    ("POST", "/api/project/sweep", True, "Run the deadline sweeper now (it also runs every minute)", {}),
    ("POST", "/api/referral", True, "A referral link; the referrer's share is a knos_pay payee on release (passkey=true: paid to your passkey wallet)", {"target": "string", "wallet": "string", "passkey": "boolean"}),
    ("GET", "/r/{code}", False, "Follow a referral link", {}),
    ("GET", "/api/attest/key", False, "This server's ed25519 attestation key", {}),
    ("GET", "/api/attest", False, "in-toto Statement v1 in a DSSE envelope for an attempt's evidence",
     {"project": "string", "milestone": "string", "attempt": "string"}),
    ("POST", "/api/evidence/c2pa", True, "Sign a photo or video with a C2PA manifest naming the claim id (raw body; X-Claim-Id)", {}),
    ("POST", "/api/evidence/c2pa/verify", False, "Read a C2PA manifest from a photo or video (raw body)", {}),
    ("GET", "/api/sso/config", False, "Whether SAML single sign-on (SAML Jackson) is on", {}),
    ("GET", "/auth/sso", False, "Start SAML sign-in through SAML Jackson", {"tenant": "string"}),
    ("GET", "/auth/sso/callback", False, "SAML Jackson's OAuth callback", {"code": "string", "state": "string"}),
    ("POST", "/auth/sso/acs", False, "A test IdP's signed SAML answer (Knos as the service provider; HTTP-POST binding)",
     {"SAMLResponse": "string", "RelayState": "string"}),
    ("GET", "/auth/sso/metadata", False, "Knos's SAML service-provider metadata (entity id, ACS)", {}),
    ("POST", "/api/company/multisig", False, "The devnet transaction that creates a company's Squads multisig (its creator signs)",
     {"name": "string", "members": "array", "threshold": "integer", "creator": "string"}),
    ("POST", "/api/company/confirm", False, "Mark a company's multisig created once it is on devnet", {"company": "string", "signature": "string"}),
    ("GET", "/api/companies", False, "Companies and their multisigs", {}),
    ("GET", "/api/company/export", False, "A project's ledger as journal, Xero, QuickBooks or NetSuite CSV", {"project": "string", "format": "string"}),
    ("GET", "/api/proofs", False, "Recorded infrastructure proofs (kind + Helm, Keycloak SSO, Odoo/ERPNext/hledger imports, Sigstore), cosign-signed", {}),
    ("GET", "/api/proofs/signature", False, "The cosign (Sigstore bundle) signature of /api/proofs", {}),
    ("GET", "/api/proofs/cosign.pub", False, "The public key that signed /api/proofs", {}),
    ("GET", "/openapi.json", False, "This document", {}),
]


def _s(v, n=200):
    return v.strip()[:n] if isinstance(v, str) else None


def handle_get(h, state, u, qs) -> bool:
    q = lambda k, d="": (qs.get(k) or [d])[0]   # noqa: E731
    p = u.path
    try:
        if p == "/api/templates":
            return h._send(200, valley.templates()) or True
        if p == "/api/projects":
            return h._send(200, valley.summaries_json(min(100, max(1, int(q("take", "10") or 10))))) or True
        if p == "/api/project":
            return h._send(200, valley.public_project(valley.project(q("id")))) or True
        if p == "/api/project/prompt":
            return h._send(200, valley.milestone_prompt(q("project"), q("milestone"))) or True
        if p == "/api/agent/keys":
            from . import agentkeys, auth
            try:
                return h._send(200, {"keys": agentkeys.keys(auth.who(h.headers.get("Authorization")))}) or True
            except auth.AuthError as why:
                return h._send(401, {"error": str(why)}) or True
        if p == "/api/cross/stream":
            from . import live
            live.stream(h, q("id"), int(q("since", "0") or 0))
            return True
        if p == "/api/sns":
            from . import chainx
            return h._send(200, chainx.sns_owner(q("name"))) or True
        if p == "/api/price":
            from . import chainx
            return h._send(200, chainx.price(q("pair", "EUR/USD"))) or True
        if p == "/api/track":
            from . import track
            return h._send(200, track.record(q("wallet"))) or True
        if p == "/api/project/route":
            pr = valley.project(q("project"))
            return h._send(200, valley.route(valley._milestone(pr, q("milestone")))) or True
        if p.startswith("/r/") and not re.fullmatch(r"/r/[0-9a-f]{16}(?:\.(?:pdf|csv|json))?", p):     # 16 hex: a demand result's page (server.py)
            code = p[3:]
            r = valley.load_referral(code)
            kind, _, val = r["target"].partition("=")
            to = f"/app/?ref={code}#" + (f"buy={val}" if kind == "b" else f"projects={val}")
            h.send_response(302)
            h.send_header("Location", to)
            h.send_header("Content-Length", "0")
            h.end_headers()
            return True
        if p == "/api/attest/key":
            return h._send(200, provenance.public_key()) or True
        if p == "/api/attest":
            return h._send(200, provenance.attest(q("project"), q("milestone"), q("attempt"))) or True
        if p in proofs.FILES:
            got = proofs.raw(p)
            return (h._send(200, got[0], got[1]) if got else h._send(404, {"error": "no recorded proofs in this build"})) or True
        if p == "/api/sso/config":
            return h._send(200, enterprise.sso_config()) or True
        if p == "/auth/sso":
            try:
                return h._redirect(enterprise.sso_start(q("tenant"), h._base(), next_page=q("next", "/"))) or True
            except enterprise.SSOError as why:
                return h._redirect("/app/#signin_error=" + urllib.parse.quote(str(why)[:120])) or True
        if p == "/auth/sso/metadata":
            from . import saml_sp
            return h._send(200, saml_sp.metadata(h._base()), "application/samlmetadata+xml") or True
        if p == "/auth/sso/callback":
            try:
                s = enterprise.sso_callback(q("code"), q("state"))
                return h._redirect(s.get("next", "/") + "#session=" + s["token"]) or True
            except enterprise.SSOError as why:
                return h._redirect("/app/#signin_error=" + urllib.parse.quote(str(why)[:120])) or True
        if p == "/api/companies":
            return h._send(200, {"companies": enterprise.companies()}) or True
        if p == "/api/company/export":
            body, ctype = enterprise.export(q("project"), q("format", "journal"))
            name = f"knos-{q('project')[:16]}-{q('format', 'journal')}.csv"
            return h._send(200, body.encode(), ctype, {"Content-Disposition": f'attachment; filename="{name}"'}) or True
        if p == "/openapi.json":
            from . import openapi
            return h._send(200, openapi.document(h._base())) or True
    except (valley.Refused, ValueError, KeyError) as why:
        return h._send(400 if not str(why).endswith("unknown id") else 404, {"error": str(why)[:300]}) or True
    except Exception as why:  # noqa: BLE001 - never a dropped connection: a generic line + a log line
        import sys
        print(f"knos projects GET error {p}: {type(why).__name__}: {str(why)[:300]}", file=sys.stderr, flush=True)
        return h._send(502, {"error": "the server could not answer this; try again"}) or True
    return False


def _raw(h) -> bytes:
    n = int(h.headers.get("Content-Length") or 0)
    if n <= 0 or n > MAX_MEDIA_BODY:
        raise ValueError(f"send the photo or video as the request body (1 to {MAX_MEDIA_BODY:,} bytes)")
    return h.rfile.read(n)


POSTS = {r[1] for r in ROUTES if r[0] == "POST"}
LIVE_PATHS = ("/api/presence", "/api/draft", "/api/draft/get")
SIGNED = {r[1] for r in ROUTES if r[0] == "POST" and r[2]}
AGENT_PATHS = ("/api/project", "/api/project/claim", "/api/project/post", "/api/project/solve")   # knos_project_open, _claim, _post, knos_milestone_submit


def _admin(given) -> bool:
    """The operator's key (KNOS_ADMIN_KEY, a Render secret), compared in constant time; no key set means no admin."""
    import hmac
    want = os.environ.get("KNOS_ADMIN_KEY") or ""
    return len(want) >= 32 and isinstance(given, str) and hmac.compare_digest(given.encode(), want.encode())


def handle_post(h, state, path: str) -> bool:
    if path not in POSTS:
        return False
    from . import auth, preorder
    # presence (every 15 s) and draft autosave (on each change) have their own bucket: they never use up the person's
    # limit for the steps they take (a Ready check, a funding)
    if not state.allow(h._client(), "live" if path in LIVE_PATHS else "product"):
        return h._send(429, {"error": "too many requests from this address; try again in a few minutes"}) or True
    try:
        from . import agentkeys
        try:                                        # the routes the write tools call also take an agent key or its token
            user = agentkeys.principal(h.headers.get("Authorization")) if path in AGENT_PATHS else auth.who(h.headers.get("Authorization"))
        except auth.AuthError as why:
            return h._send(401, {"error": str(why)[:300]}) or True
        if path in SIGNED and user is None:
            return h._send(401, {"error": "sign in first (passkey, SSO, Google or a guest label)"
                                 + ("; an agent: Authorization: Bearer <agent key or its OAuth token> (/.well-known/oauth-protected-resource)"
                                    if path in AGENT_PATHS else "")}) or True
        if path.startswith("/api/agent/keys"):
            b = h._json()
            try:
                if path == "/api/agent/keys/revoke":
                    return h._send(200, agentkeys.revoke(user, str(b.get("id", "")))) or True
                return h._send(200, agentkeys.create(user, b.get("label"), b.get("max_claims"), b.get("max_spend_units"), b.get("days"),
                                                     str(b.get("payout_wallet", "")))) or True
            except auth.AuthError as why:
                return h._send(401, {"error": str(why)[:300]}) or True
        if path == "/api/evidence/c2pa":
            if not provenance.c2pa_available():
                return h._send(503, {"error": "C2PA signing is not installed on this server (c2pa-python)"}) or True
            mime = (h.headers.get("Content-Type") or "").split(";")[0].strip()
            return h._send(200, provenance.c2pa_sign(_raw(h), mime, str(h.headers.get("X-Claim-Id") or ""))) or True
        if path == "/api/evidence/c2pa/verify":
            if not provenance.c2pa_available():
                return h._send(503, {"error": "C2PA reading is not installed on this server (c2pa-python)"}) or True
            mime = (h.headers.get("Content-Type") or "").split(";")[0].strip()
            return h._send(200, provenance.c2pa_read(_raw(h), mime)) or True
        if path == "/auth/sso/acs":                    # a form post from the IdP, not JSON; lands on a page with the session
            n = int(h.headers.get("Content-Length") or 0)
            form = urllib.parse.parse_qs(h.rfile.read(n).decode("ascii", "replace") if 0 < n <= 600_000 else "")
            try:
                s = enterprise.saml_finish((form.get("SAMLResponse") or [""])[0], (form.get("RelayState") or [""])[0], h._base())
                return h._redirect(s.get("next", "/") + "#session=" + s["token"]) or True
            except enterprise.SSOError as why:
                return h._redirect("/app/#signin_error=" + urllib.parse.quote(str(why)[:120])) or True
        b = h._json()
        if path == "/api/project/archive":
            admin = _admin(h.headers.get("X-Knos-Admin"))
            if not admin and not user:
                return h._send(401, {"error": "sign in as the project's buyer, or send the operator's X-Knos-Admin key"}) or True
            return h._send(200, valley.unlist(str(b.get("project", "")), user, admin, str(b.get("why") or ""))) or True
        if path == "/api/project/operator":
            if not _admin(h.headers.get("X-Knos-Admin")):
                return h._send(403, {"error": "the operator's X-Knos-Admin key opens, funds and claims these projects"}) or True
            return h._send(200, _operator(b)) or True
        if path == "/api/project" and isinstance(b.get("report"), str):
            # the project's Grounding (Qloo) line reads its report from disk (valley.grounding); a crossing recalled from
            # memory was kept only in this server's memory, so it is written there now
            rep = state.report(b["report"])
            if rep is not None:
                state.keep_check(rep)
                from . import trace
                trace.keep(state, rep["hash"])             # its Grounding line links to this trace: kept on devnet too
        return h._send(200, _post(path, b, user or {}, h)) or True
    except preorder.Settled as why:
        return h._send(409, {"error": str(why)[:300]}) or True
    except preorder.NotVerified as why:
        return h._send(422, {"error": f"not verified: {why}"[:400], "verified": False}) or True
    except (valley.Refused, enterprise.SSOError, ValueError, TypeError, KeyError) as why:
        return h._send(400, {"error": str(why)[:300]}) or True
    except Exception as why:  # noqa: BLE001
        from .escrow import EscrowUnavailable
        if isinstance(why, EscrowUnavailable):
            return h._send(503, {"error": str(why)[:300]}) or True
        import hashlib
        import sys
        import time
        ref = hashlib.sha256(f"{time.time()}{id(why)}".encode()).hexdigest()[:10]
        print(f"knos projects error {ref} {path}: {type(why).__name__}: {str(why)[:300]}", file=sys.stderr, flush=True)
        return h._send(502, {"error": f"the server could not finish this step (reference {ref}); nothing was charged", "ref": ref}) or True


def _passkey(path: str, b: dict, user: dict, h) -> dict:
    """The same steps signed by the person's own passkey wallet (no browser wallet, no new account): each returns the
    step the passkey approves (static/passkey_wallet.js), relayed by POST /api/sign."""
    from . import escrow, wallets
    led, rp = escrow.ledger(), h._rp()
    pid, key = str(b.get("project", "")), str(b.get("milestone", ""))
    if path == "/api/project/fund":
        return wallets.prepare_project_fund(led, user, pid, key, b.get("units", 5), rp, str(b.get("kind") or "funder"),
                                            b.get("grant") if isinstance(b.get("grant"), dict) else None, _s(b.get("ref"), 20), _s(b.get("pool"), 64),
                                            private=b.get("private") is True)
    if path == "/api/project/amc":
        return wallets.prepare_amc(led, user, pid, key, b.get("units", 5), rp)
    if path == "/api/company/multisig":
        members = b.get("members") or []
        if isinstance(members, str):
            members = [m.strip() for m in re.split(r"[,\s]+", members) if m.strip()]
        return wallets.prepare_company(led, user, str(b.get("name", "")), members, b.get("threshold", 1), rp)
    vault = str(wallets.ensure(led, wallets.holder(user), rp)["vault"])        # where a maker or referrer is paid: its passkey wallet
    if path == "/api/project/claim":
        return {**valley.claim(pid, key, user, vault), "paid_to": "your passkey wallet"}
    return {**valley.make_referral(user, vault, str(b.get("target", ""))), "paid_to": "your passkey wallet"}


PASSKEY_PATHS = ("/api/project/fund", "/api/project/amc", "/api/project/claim", "/api/referral", "/api/company/multisig")


def _operator(b: dict) -> dict:
    act, pid, key = str(b.get("action", "")), str(b.get("project", "")), str(b.get("milestone", ""))
    if act == "open":
        return valley.operator_open(b.get("brief") if isinstance(b.get("brief"), dict) else {}, str(b.get("title", "")), str(b.get("repo", "")))
    if act == "fund":
        return valley.operator_fund(pid, key, b.get("units", 5))
    if act == "claim":
        return valley.operator_claim(pid, key, str(b.get("wallet", "")))
    if act == "solver_open":                    # the three solver briefs (knos_wanted.solver_briefs), or the ids named
        which = b.get("which") if isinstance(b.get("which"), list) else None
        return {"projects": valley.open_solver_briefs(which, _s(b.get("round"), 80))}
    if act == "solver_fund":                    # the referee-judged milestone, from the app's devnet test wallet
        return valley.operator_fund_solver(pid, b.get("units", 5))
    raise ValueError("action: open, fund, claim, solver_open or solver_fund")


def _post(path: str, b: dict, user: dict, h) -> dict:
    if b.get("passkey") is True and path in PASSKEY_PATHS:
        if not user:
            raise ValueError("sign in with your passkey first")
        return _passkey(path, b, user, h)
    if path == "/api/project/pool" and b.get("passkey") is True:
        from . import valley as v
        return {"pool": v._id("pool", str(user.get("sub"))), "rule": "fund each milestone with POST /api/project/fund {passkey, kind: pool, pool}"}
    if path in ("/api/draft", "/api/draft/get", "/api/draft/forget"):
        from . import live
        if path == "/api/draft":
            return live.draft_save(user, b.get("brief") if isinstance(b.get("brief"), dict) else {}, str(b.get("title") or ""))
        return live.draft_get(user) if path == "/api/draft/get" else live.draft_forget(user)
    if path == "/api/presence":
        from . import live
        return live.presence(str(b.get("page", "")), str(b.get("me", "")), b.get("x", 0), b.get("y", 0), str(b.get("label") or "someone"))
    if path == "/api/evidence/evm":
        from . import chainx
        return chainx.evm_verify(str(b.get("eth_address", "")), str(b.get("signature", "")), str(b.get("message", ""))[:1000])
    if path == "/api/ready/resolve":
        return valley.resolve(b.get("word"), b.get("reading"), b.get("target"), user)
    if path == "/api/ready":
        return valley.check_brief(b.get("brief") if isinstance(b.get("brief"), dict) else b)
    if path == "/api/project":
        return valley.create_project(user, str(b.get("template", "")), str(b.get("title", "")), b.get("regulatory") or [],
                                     _s(b.get("report"), 64), _s(b.get("team"), 80), b.get("deadline_s"),
                                     b.get("brief") if isinstance(b.get("brief"), dict) else None)
    if path == "/api/project/brief":
        return valley.edit_brief(str(b.get("project", "")), user, b.get("brief") if isinstance(b.get("brief"), dict) else {})
    if path == "/api/project/change":
        return valley.change_request(str(b.get("project", "")), user, b.get("brief") if isinstance(b.get("brief"), dict) else {}, _s(b.get("why"), 300) or "")
    if path == "/api/project/change/decide":
        return valley.decide_change(str(b.get("project", "")), user, str(b.get("change", "")), b.get("accept") is True)
    if path == "/api/project/cancel":
        return valley.cancel(str(b.get("project", "")), user, base=h._base())
    if path == "/api/project/dispute":
        return valley.dispute(str(b.get("project", "")), str(b.get("milestone", "")), str(b.get("attempt", "")), user, str(b.get("url", "")))
    if path == "/api/sandbox":
        return valley.create_project(user, str(b.get("template") or "internal_tool"), str(b.get("title") or "One-day sandbox project"), [],
                                     None, _s(b.get("team"), 80) or "sandbox team", int(os.environ.get("KNOS_SANDBOX_DEADLINE_S", "86400")))
    if path == "/api/project/fund":
        return valley.fund_tx(str(b.get("project", "")), str(b.get("milestone", "")), b.get("units", 5), str(b.get("account", "")),
                              str(b.get("kind") or "funder"), b.get("grant") if isinstance(b.get("grant"), dict) else None, _s(b.get("ref"), 20),
                              private=b.get("private") is True)
    if path == "/api/project/confirm":
        return valley.confirm(str(b.get("order", "")), _s(b.get("signature"), 100))
    if path == "/api/project/private":
        return valley.private_pledge(str(b.get("order", "")), b)
    if path == "/api/project/pool":
        return valley.pool_txs(b.get("allocations") or [], b.get("units", 0), str(b.get("account", "")), _s(b.get("ref"), 20))
    if path == "/api/project/amc":
        return valley.amc_tx(str(b.get("project", "")), str(b.get("milestone", "")), b.get("units", 5), str(b.get("account", "")))
    if path == "/api/project/amc/confirm":
        return valley.amc_confirm(str(b.get("amc", "")), _s(b.get("signature"), 100))
    if path == "/api/project/claim":
        return valley.claim(str(b.get("project", "")), str(b.get("milestone", "")), user, str(b.get("wallet", "")))
    if path == "/api/project/post":
        return valley.post(str(b.get("project", "")), str(b.get("milestone", "")), str(b.get("attempt", "")), user,
                           str(b.get("url", "")), str(b.get("role", "")))
    if path == "/api/project/ci":
        return valley.ci_release(str(b.get("project", "")), str(b.get("milestone", "")), str(b.get("sha", "")), base=h._base())
    if path == "/api/project/solve":
        return valley.solve(str(b.get("project", "")), str(b.get("milestone", "")), str(b.get("code", "")), user, str(b.get("wallet", "")),
                            base=h._base())
    if path == "/api/project/sweep":
        return valley.sweep()
    if path == "/api/referral":
        return valley.make_referral(user, str(b.get("wallet", "")), str(b.get("target", "")))
    if path == "/api/company/multisig":
        members = b.get("members") or []
        if isinstance(members, str):
            members = [m.strip() for m in re.split(r"[,\s]+", members) if m.strip()]
        return enterprise.company_multisig_tx(str(b.get("name", "")), members, b.get("threshold", 1), str(b.get("creator", "")))
    if path == "/api/company/confirm":
        return enterprise.company_confirm(str(b.get("company", "")), _s(b.get("signature"), 100))
    raise ValueError("not found")


_CONFIRM = ("CONFIRM FIRST: this opens or changes work that devnet TEST money depends on. Ask the human you work for before "
            "calling, and say what it does. Needs Authorization: Bearer (an agent key's OAuth token, or a session).")
_obj = lambda props, req=(): {"type": "object", "properties": props, "required": list(req), "additionalProperties": False}  # noqa: E731
_S, _I = {"type": "string"}, {"type": "integer"}
MCP_TOOLS = [
    {"name": "knos_templates", "title": "Milestone templates",
     "description": "AI model eval, hardware prototype, internal tool, paper to pilot, vendor deliverable; and the ISO 13485 / EU MDR "
                    "regulatory milestones from OpenRegulatory's open templates (with attribution and licence).",
     "inputSchema": _obj({})},
    {"name": "knos_projects", "title": "Projects and their milestones",
     "description": "The newest projects (take, default 10) as summaries: each milestone's state and held units. With id: one project "
                    "in full, with its milestones (tranches), held orders, AMC commitments, attempts and where the work can be bought.",
     "inputSchema": _obj({"id": _S, "take": {"type": "integer", "minimum": 1, "maximum": 100}})},
    {"name": "knos_project_open", "title": "Open a project from a template", "description": "Opens a project; each milestone is its own "
     "tranche, released only on a result plus an independent check. " + _CONFIRM,
     "inputSchema": _obj({"template": _S, "title": _S, "regulatory": {"type": "array", "items": _S}, "session": _S}, ("template", "title"))},
    {"name": "knos_project_claim", "title": "Attempt a milestone", "description": "Takes a milestone as a maker (parallel attempts allowed) "
     "and binds the wallet it pays (an agent key: its payout wallet, leave wallet out). A missed deadline refunds the funders and "
     "reopens it to others. " + _CONFIRM,
     "inputSchema": _obj({"project": _S, "milestone": _S, "wallet": _S, "session": _S}, ("project", "milestone"))},
    {"name": "knos_project_post", "title": "Post a result or an independent check", "description": "role=result (the maker) or check (someone "
     "else, another site): a public https page containing the milestone's claim id. Both in: the referee panel releases (the FROST group: 2 of 3 independent hosts re-check and sign). " + _CONFIRM,
     "inputSchema": _obj({"project": _S, "milestone": _S, "attempt": _S, "url": _S, "role": _S, "session": _S},
                         ("project", "milestone", "attempt", "url", "role"))},
    {"name": "knos_milestone_submit", "title": "Submit to a referee-checked milestone",
     "description": "For a milestone whose verifier is knos-referee:<round>: claims it for you if you have no attempt yet (an agent key: "
     "paid at its payout wallet, one claim of its cap), sends your whole train.py to that round's sealed referee, and when the "
     "verdict meets the target the held money is released to you with no human step. knos_tasks links the round's README. With kind observation or oru and a brief, it checks a lab's "
     "proof inside the same rules referee IRIS runs, and returns the decision only. " + _CONFIRM,
     "inputSchema": _obj({"project": _S, "milestone": _S, "code": {"type": "string", "description": "the whole train.py"},
                          "wallet": _S, "session": _S,
                          "kind": {"type": "string", "enum": ["observation", "oru"], "description": "a lab's proof instead of code: a FHIR Observation or an HL7 ORU message, checked by the rules referee IRIS runs too (the decision only; nothing moves)"},
                          "proof": {"description": "the Observation (an object) or the ORU message (a string)"},
                          "brief": {"type": "object", "description": "the locked brief the lab proof answers"}}, ())},
    {"name": "knos_openapi", "title": "This server's OpenAPI document", "description": "The same API as REST: /openapi.json.",
     "inputSchema": _obj({})},
    {"name": "knos_ready", "title": "Ready to fund", "description": "Free check of a brief before any money locks: each milestone needs a "
     "measurable target (number and unit, or a named test), a verifier (a GitHub check name, or what/how/who/where) and a deadline; vague "
     "words are flagged. Returns Ready, or Not ready with the missing fields and a rewrite template. Sends nothing.",
     "inputSchema": _obj({"brief": {"type": "object"}}, ("brief",))},
    {"name": "knos_usage", "title": "What was asked of Knos", "description": "In plain words: which Knos tools were called over MCP "
     "and how many times since this server started. Reads only, except `record`: the operator (its X-Knos-Admin key) "
     "records a measured token use, which stays private.",
     "inputSchema": _obj({"record": {"type": "object", "description": "a goal's measured token use (scripts/goal_usage.py); the operator only"}})},
    {"name": "knos_milestone_prompt", "title": "The brief an agent works from", "description": "For a milestone you work on: the locked "
     "intent (goal, success check, constraints, scope) with its criteria hash, the effort level and output-token budget, and how to "
     "answer (minimal drafts, confidence first, stop when the check passes). Use it as your first instruction; do not re-derive the brief.",
     "inputSchema": _obj({"project": _S, "milestone": _S}, ("project", "milestone"))},
]


_USAGE: dict[str, int] = {}
READ_ONLY = ("knos_templates", "knos_projects", "knos_openapi", "knos_ready", "knos_milestone_prompt", "knos_usage")


def mcp_call(name: str, args: dict, signed) -> dict:
    """Every tool call is counted (knos_usage says it in plain words). A read-only tool that hits a passing network
    error is asked once more before the error is returned (self-healing); a tool that moves money never is."""
    _USAGE[name] = _USAGE.get(name, 0) + 1
    try:
        return _mcp_call(name, args, signed)
    except (ConnectionError, TimeoutError, OSError):
        if name not in READ_ONLY:
            raise
        import time
        time.sleep(1.0)
        return _mcp_call(name, args, signed)


def usage(record: dict | None = None) -> dict:
    rows = sorted(_USAGE.items(), key=lambda kv: -kv[1])
    said = "; ".join(f"{n.replace('knos_', '').replace('_', ' ')}: {c} time{'s' if c != 1 else ''}" for n, c in rows) or "nothing yet"
    if record is not None:                       # a goal's token use, measured from its transcript; the operator records it
        from . import outside
        if not _admin(getattr(outside.CTX, "headers", None) and outside.CTX.headers.get("X-Knos-Admin")):
            raise ValueError("record: the operator's X-Knos-Admin key records a goal's token use")
        keep = {k: record.get(k) for k in ("v", "goal", "measured_with", "output_tokens", "input_tokens", "cache_read_input_tokens",
                                           "cache_creation_input_tokens", "messages", "since", "until")}
        if not isinstance(keep["goal"], str) or not all(isinstance(keep[k], int) and keep[k] >= 0 for k in ("output_tokens", "input_tokens", "messages")):
            raise ValueError("record: goal, and output_tokens, input_tokens, messages as whole numbers")
        valley._save("pages", "goal_usage", {"goals": {**_goals(), keep["goal"]: keep}})
    return {"since": "this server started", "calls": dict(rows), "in_words": f"Asked of Knos over MCP: {said}."}


def _goals() -> dict:
    try:
        return valley._load("pages", "goal_usage").get("goals") or {}
    except valley.Refused:
        return {}


def _mcp_call(name: str, args: dict, signed) -> dict:
    if name == "knos_usage":
        return usage(args.get("record") if isinstance(args.get("record"), dict) else None)
    if name == "knos_templates":
        return valley.templates()
    if name == "knos_projects":
        if args.get("id"):
            return valley.public_project(valley.project(str(args["id"])))
        return json.loads(valley.summaries_json(min(100, max(1, int(args.get("take") or 10)))))
    if name == "knos_openapi":
        from . import openapi
        return openapi.document()
    if name == "knos_ready":
        return valley.check_brief(args.get("brief") if isinstance(args.get("brief"), dict) else {})
    if name == "knos_milestone_prompt":
        return valley.milestone_prompt(str(args.get("project", "")), str(args.get("milestone", "")))
    who = signed(args)
    try:
        if name == "knos_project_open":
            return valley.create_project(who, str(args.get("template", "")), str(args.get("title", "")), args.get("regulatory") or [])
        if name == "knos_project_claim":
            return valley.claim(str(args.get("project", "")), str(args.get("milestone", "")), who, str(args.get("wallet", "")))
        if name == "knos_project_post":
            return valley.post(str(args.get("project", "")), str(args.get("milestone", "")), str(args.get("attempt", "")), who,
                               str(args.get("url", "")), str(args.get("role", "")))
        if name == "knos_milestone_submit":
            return valley.solve(str(args.get("project", "")), str(args.get("milestone", "")), str(args.get("code", "")), who,
                                str(args.get("wallet", "")))
    except valley.Refused as why:
        raise ValueError(str(why)) from None
    raise ValueError(f"unknown tool {name}")


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


__all__ = ["ROUTES", "handle_get", "handle_post", "json"]
