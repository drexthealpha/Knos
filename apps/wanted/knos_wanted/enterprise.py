"""Knos for companies: SAML single sign-on through BoxyHQ SAML Jackson, money a company controls through its own Squads
multisig, and the company's ledger as files its accounting system imports.

SSO (SAML -> OIDC)   SAML Jackson (open source, github.com/boxyhq/jackson) runs as its own service (KNOS_SSO_URL, e.g. the
                     knos-sso Render service). The company's SAML IdP is a Jackson connection for one tenant; Knos talks
                     plain OAuth 2.0 + PKCE to Jackson ("tenanted" flow: client_id tenant=<t>&product=knos):
                       GET /auth/sso?tenant=<t>  ->  Jackson /api/oauth/authorize  ->  the IdP's sign-in  ->  Jackson ACS
                       ->  /auth/sso/callback?code=  ->  POST Jackson /api/oauth/token  ->  GET /api/oauth/userinfo
                       ->  a Knos session (kind "sso", the IdP's email + tenant)
                     The test IdP is mocksaml.com's public one (any @example.com user, any password): ensure_connection
                     registers its metadata for the tenant "knos-test" (Jackson's in-memory store forgets it on restart, so
                     the app re-registers on first use with KNOS_SSO_API_KEY).
Squads per company   POST /api/company/multisig builds Squads v4 multisig_create_v2 for the company's own member keys and
                     threshold; the company's creator wallet signs and pays (the server only signs the one-time create key,
                     which seeds the address and holds no power). Knos holds no key in it. The vault (index 0) is the
                     company's payee and treasury: spending from it needs the company's threshold, never Knos.
ERP export           GET /api/company/export?project=&format=xero|quickbooks|netsuite|journal: one line per released,
                     refunded or locked order. `journal` + hledger rules (export_hledger) were imported into hledger, an open
                     source accounting system, and its balances checked (evidence in the release record).
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import secrets
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import escrow

SQUADS = "SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf"
MOCKSAML_METADATA = "https://mocksaml.com/api/namespace/knos/saml/metadata"     # the knos namespace of mocksaml.com
PRODUCT = "knos"
_pending: dict[str, tuple[float, dict]] = {}
_plock = threading.Lock()
_ensured: dict[str, float] = {}


class SSOError(ValueError):
    pass


# ---- SSO through SAML Jackson ----------------------------------------------------------------------------------------
KEYCLOAK_TENANT = "knos-keycloak"
KEYCLOAK_REALM = "knos-test"


def test_idps() -> dict[str, dict]:
    """The TEST SAML IdPs the app registers in Jackson by itself, by tenant. mocksaml.com always; the self-hosted Keycloak
    test realm (deploy/sso/keycloak/knos-test-realm.json) when KNOS_SSO_KEYCLOAK_URL points at it."""
    out = {os.environ.get("KNOS_SSO_TEST_TENANT", "knos-test"): {
        "name": "mocksaml.com/namespace/knos (public test SAML IdP: any user@example.com, any password)", "metadata": MOCKSAML_METADATA}}
    kc = (os.environ.get("KNOS_SSO_KEYCLOAK_URL") or "").rstrip("/")
    if kc and _safe(kc):
        out[KEYCLOAK_TENANT] = {"name": f"Keycloak, self-hosted TEST realm {KEYCLOAK_REALM} (test users only)",
                                "metadata": f"{kc}/realms/{KEYCLOAK_REALM}/protocol/saml/descriptor", "wake": f"{kc}/realms/{KEYCLOAK_REALM}"}
    return out


def _safe(url: str) -> bool:
    u = urllib.parse.urlparse(url)
    return u.scheme == "https" or (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1"))


def sso_config() -> dict:
    url = (os.environ.get("KNOS_SSO_URL") or "").rstrip("/")
    idps = test_idps()
    first = next(iter(idps))
    return {"enabled": bool(url and os.environ.get("KNOS_SSO_CLIENT_SECRET")), "jackson": url or None,
            "test_tenant": first, "test_idp": idps[first]["name"],
            "test_tenants": [{"tenant": t, "idp": v["name"]} for t, v in idps.items()]}


def _http(method: str, url: str, data: dict | None = None, headers: dict | None = None, form: bool = False, opener=None) -> dict:
    body = None
    h = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            h["Content-Type"] = "application/json"
    op = opener or urllib.request.urlopen
    # Jackson runs on another free Render service: from this one it can answer 429 or 5xx for a while (rate limited,
    # or waking). Each is tried again after its Retry-After (or 2, 4, 8 s), at most 25 s in all; then a plain message.
    waited = 0.0
    for attempt in range(5):
        req = urllib.request.Request(url, data=body, method=method, headers=h)
        try:
            with op(req, timeout=60) as r:
                raw = r.read(512_000)
            return json.loads(raw or b"{}")
        except urllib.error.HTTPError as e:
            if e.code not in (429, 502, 503, 504) or waited >= RETRY_BUDGET_S:
                if e.code in (429, 502, 503, 504):
                    raise SSOError("single sign-on is busy right now; try again in a minute") from None
                raise SSOError(f"SAML Jackson answered HTTP {e.code} on {urllib.parse.urlparse(url).path}") from None
            pause = _retry_after(e.headers.get("Retry-After") if e.headers else None, 2.0 * 2 ** attempt)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise SSOError(f"SAML Jackson is not reachable ({type(e).__name__}); it may be waking up, try again in a minute") from None
        pause = min(pause, RETRY_BUDGET_S - waited)
        _sleep(pause)
        waited += pause
    raise SSOError("single sign-on is busy right now; try again in a minute")


RETRY_BUDGET_S = 25.0
_sleep = time.sleep          # tests replace it


def _retry_after(value, default: float) -> float:
    try:
        return max(0.5, min(float(value), 20.0))
    except (TypeError, ValueError):
        return default


def ensure_connection(tenant: str, base_url: str, opener=None) -> dict:
    """Register `tenant`'s TEST IdP (test_idps) in Jackson, once per process (Jackson's mem store resets)."""
    cfg = sso_config()
    idp = test_idps().get(tenant)
    if idp is None:
        return {"ensured": False, "why": "not a test tenant: its connection must already exist in Jackson"}
    key = os.environ.get("KNOS_SSO_API_KEY")
    if not key:
        return {"ensured": False, "why": "KNOS_SSO_API_KEY is not set: the connection must already exist in Jackson"}
    if time.time() - _ensured.get(tenant, 0) < 600:
        return {"ensured": True, "cached": True}
    if idp.get("wake"):     # a free-plan IdP sleeps: wake it before Jackson fetches its metadata
        try:
            (opener or urllib.request.urlopen)(urllib.request.Request(idp["wake"], method="GET"), timeout=120).close()
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SSOError("the test identity provider is not reachable; it may be waking up, try again in a minute") from None
    auth = {"Authorization": f"Api-Key {key}"}
    q = urllib.parse.urlencode({"tenant": tenant, "product": PRODUCT})
    got = _http("GET", f"{cfg['jackson']}/api/v1/sso?{q}", headers=auth, opener=opener)
    stale = [c for c in (got if isinstance(got, list) else []) if c.get("metadataUrl") and c["metadataUrl"] != idp["metadata"]]
    for c in stale:                                       # registered against another IdP address: replace it
        d = urllib.parse.urlencode({"clientID": c.get("clientID", ""), "clientSecret": c.get("clientSecret", "")})
        _http("DELETE", f"{cfg['jackson']}/api/v1/sso?{d}", headers=auth, opener=opener)
    if not (isinstance(got, list) and got) or stale:
        cb = base_url.rstrip("/") + "/auth/sso/callback"
        _http("POST", f"{cfg['jackson']}/api/v1/sso", headers=auth, form=True, opener=opener, data={
            "tenant": tenant, "product": PRODUCT, "name": f"{tenant} (test IdP: {idp['name']})", "metadataUrl": idp["metadata"],
            "defaultRedirectUrl": cb, "redirectUrl": json.dumps([cb])})
    _ensured[tenant] = time.time()
    return {"ensured": True}


NEXT = ("/", "/companies")          # where a sign-in may land (the app's own pages; anything else lands home)


def sso_start(tenant: str, base_url: str, opener=None, next_page: str = "/") -> str:
    cfg = sso_config()
    from . import saml_sp
    t = (tenant or cfg["test_tenant"]).strip().lower()
    if t in test_idps() and saml_sp.available():     # a TEST IdP: Knos is the service provider itself, no Jackson call
        try:
            return saml_sp.start(t, test_idps()[t]["metadata"], base_url, next_page if next_page in NEXT else "/", opener)
        except saml_sp.SAMLError as why:
            raise SSOError(str(why)) from None
    if not cfg["enabled"]:
        raise SSOError("SAML single sign-on is not configured on this server (KNOS_SSO_URL, KNOS_SSO_CLIENT_SECRET)")
    tenant = (tenant or cfg["test_tenant"]).strip().lower()
    if not tenant or len(tenant) > 64 or not all(c.isalnum() or c in "-_." for c in tenant):
        raise SSOError("tenant: the company's SSO tenant (letters, digits, - _ .)")
    if tenant in test_idps():
        ensure_connection(tenant, base_url, opener)
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(24)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    redirect = base_url.rstrip("/") + "/auth/sso/callback"
    with _plock:
        now = time.time()
        for k in [k for k, (t, _) in _pending.items() if now - t > 600]:
            _pending.pop(k)
        _pending[state] = (now, {"verifier": verifier, "tenant": tenant, "redirect": redirect, "next": next_page if next_page in NEXT else "/"})
    q = urllib.parse.urlencode({"response_type": "code", "client_id": f"tenant={tenant}&product={PRODUCT}", "redirect_uri": redirect,
                                "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})   # plain OAuth 2.0 + userinfo (no id_token: no JWT keys to manage)
    return f"{cfg['jackson']}/api/oauth/authorize?{q}"


def sso_callback(code: str, state: str, opener=None) -> dict:
    from . import auth
    with _plock:
        got = _pending.pop(state or "", None)
    if got is None or time.time() - got[0] > 600:
        raise SSOError("this sign-in expired or was not started here: start again")
    p = got[1]
    if not code:
        raise SSOError("the identity provider sent no code")
    cfg = sso_config()
    tok = _http("POST", f"{cfg['jackson']}/api/oauth/token", form=True, opener=opener, data={
        "grant_type": "authorization_code", "client_id": f"tenant={p['tenant']}&product={PRODUCT}",
        "client_secret": os.environ.get("KNOS_SSO_CLIENT_SECRET", ""), "redirect_uri": p["redirect"], "code": code,
        "code_verifier": p["verifier"]})
    if not tok.get("access_token"):
        raise SSOError("SAML Jackson gave no access token")
    me = _http("GET", f"{cfg['jackson']}/api/oauth/userinfo", headers={"Authorization": f"Bearer {tok['access_token']}"}, opener=opener)
    email = str(me.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise SSOError("the identity provider sent no email")
    req = me.get("requested") or {}
    if req.get("tenant") and req.get("tenant") != p["tenant"]:
        raise SSOError("the identity provider answered for another tenant")
    s = auth.issue(f"sso:{p['tenant']}:{hashlib.sha256(email.encode()).hexdigest()[:24]}", "sso", f"{email} ({p['tenant']})")
    s["tenant"] = p["tenant"]
    s["next"] = p.get("next") or "/"
    return s


def saml_finish(saml_response: str, relay: str, base_url: str, opener=None) -> dict:
    """A test IdP's signed answer at /auth/sso/acs (saml_sp.finish) -> a session, like sso_callback's."""
    from . import auth, saml_sp
    try:
        got = saml_sp.finish(saml_response, relay, base_url, opener)
    except saml_sp.SAMLError as why:
        raise SSOError(str(why)) from None
    s = auth.issue(f"sso:{got['tenant']}:{hashlib.sha256(got['email'].encode()).hexdigest()[:24]}", "sso", f"{got['email']} ({got['tenant']})")
    s["tenant"] = got["tenant"]
    s["next"] = got["next"] or "/"
    return s


# ---- Squads: a multisig per company ----------------------------------------------------------------------------------
def _pk(s):
    from solders.pubkey import Pubkey
    return Pubkey.from_string(str(s))


def squads_pdas(create_key) -> dict:
    from solders.pubkey import Pubkey
    prog = Pubkey.from_string(SQUADS)
    ms, _ = Pubkey.find_program_address([b"multisig", b"multisig", bytes(create_key)], prog)
    vault, _ = Pubkey.find_program_address([b"multisig", bytes(ms), b"vault", bytes([0])], prog)
    cfg, _ = Pubkey.find_program_address([b"multisig", b"program_config"], prog)
    return {"multisig": ms, "vault": vault, "program_config": cfg}


def create_v2_data(members: list[str], threshold: int, time_lock: int = 0, memo: str | None = None) -> bytes:
    """multisig_create_v2(args: MultisigCreateArgsV2) in Squads v4's Anchor encoding."""
    disc = hashlib.sha256(b"global:multisig_create_v2").digest()[:8]
    out = disc + b"\x00" + struct.pack("<H", threshold) + struct.pack("<I", len(members))
    for m in members:
        out += bytes(_pk(m)) + bytes([7])                # permissions mask: initiate | vote | execute
    out += struct.pack("<I", time_lock) + b"\x00"         # time lock; rent_collector: None
    if memo:
        mb = memo.encode()[:120]
        out += b"\x01" + struct.pack("<I", len(mb)) + mb
    else:
        out += b"\x00"
    return out


def company_multisig_tx(name: str, members: list[str], threshold: int, creator: str, led=None) -> dict:
    """The transaction the company's creator wallet signs: a Squads v4 multisig of the company's members."""
    from solders.hash import Hash
    from solders.keypair import Keypair
    from solders.message import Message
    from solders.transaction import Transaction

    from knos import chain
    led = led or escrow.ledger()
    create_key = Keypair()
    ix, rec, _ = multisig_ix(name, members, threshold, _pk(creator), create_key.pubkey(), led)
    bh = Hash.from_string(chain.call(led.url, "getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])
    tx = Transaction.new_unsigned(Message.new_with_blockhash([ix], _pk(creator), bh))
    tx.partial_sign([create_key], bh)
    _save_company(rec)
    return {"transaction": base64.b64encode(bytes(tx)).decode(), "company": rec["id"], "multisig": rec["multisig"], "vault": rec["vault"],
            "message": f"Creates {rec['name']}'s Squads multisig ({rec['threshold']} of {len(rec['members'])}) on devnet. Your wallet signs and pays; Knos holds no key in it."}


def multisig_ix(name: str, members: list[str], threshold: int, creator, create_key, led):
    """Squads v4 multisig_create_v2 for a company: (the instruction, the company's record, the creation fee in lamports).
    `create_key` seeds the multisig's address and signs with `creator` (a passkey wallet's vault may be both)."""
    from solders.instruction import AccountMeta, Instruction
    from solders.pubkey import Pubkey
    name = (name or "").strip()[:80]
    if len(name) < 2:
        raise ValueError("name: the company's name")
    if not isinstance(members, list) or not 1 <= len(members) <= 10 or len(set(members)) != len(members):
        raise ValueError("members: 1 to 10 distinct member wallet addresses")
    for m in members:
        _pk(m)
    if isinstance(threshold, bool) or not isinstance(threshold, int) or not 1 <= threshold <= len(members):
        raise ValueError("threshold: 1 to the number of members")
    if str(creator) not in members:
        raise ValueError("creator: one of the members signs and pays for the multisig")
    pdas = squads_pdas(create_key)
    cfg = led.account(pdas["program_config"])
    if cfg is None or len(cfg) < 80:
        raise ValueError("Squads v4's program config is not on this cluster")
    treasury = Pubkey.from_bytes(cfg[48:80])
    fee = int.from_bytes(cfg[40:48], "little")
    ix = Instruction(Pubkey.from_string(SQUADS), create_v2_data(members, threshold, memo=f"Knos company: {name}"), [
        AccountMeta(pdas["program_config"], False, False), AccountMeta(treasury, False, True), AccountMeta(pdas["multisig"], False, True),
        AccountMeta(create_key, True, False), AccountMeta(creator, True, True),
        AccountMeta(Pubkey.from_string("11111111111111111111111111111111"), False, False)])
    cid = hashlib.sha256(bytes(pdas["multisig"])).hexdigest()[:16]
    rec = {"id": cid, "name": name, "members": members, "threshold": threshold, "multisig": str(pdas["multisig"]),
           "vault": str(pdas["vault"]), "creator": str(creator), "status": "pending", "made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    return ix, rec, fee


def _cdir():
    d = escrow._state_dir() / "valley" / "companies"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_company(rec: dict) -> None:
    (_cdir() / f"{rec['id']}.json").write_text(json.dumps(rec, indent=1), encoding="utf-8")


def company(cid: str) -> dict:
    if not isinstance(cid, str) or not cid.isalnum() or len(cid) != 16:
        raise ValueError("company: unknown id")
    f = _cdir() / f"{cid}.json"
    if not f.exists():
        raise ValueError("company: unknown id")
    return json.loads(f.read_text(encoding="utf-8"))


def company_confirm(cid: str, signature: str | None = None, led=None) -> dict:
    rec = company(cid)
    if rec["status"] == "pending":
        led = led or escrow.ledger()
        acc = led.account(_pk(rec["multisig"]))
        if acc is None:
            raise ValueError("the multisig is not on devnet yet: send the signed transaction first")
        rec["status"] = "created"
        rec["signature"] = signature if signature and len(signature) < 100 else None
        rec["account_bytes"] = len(acc)
        _save_company(rec)
    return {**rec, "explorer": escrow.explorer(rec["multisig"], "address"),
            "squads_app": f"https://devnet.squads.so/squads/{rec['multisig']}/home"}


def companies() -> list[dict]:
    out = []
    for f in sorted(_cdir().glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)[:50]:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


# ---- ERP export ------------------------------------------------------------------------------------------------------
FORMATS = ("journal", "xero", "quickbooks", "netsuite")


def ledger_lines(pid: str) -> list[dict]:
    """One line per order on the project: locked (a commitment held in vault), released (paid to the maker), refunded."""
    from . import valley
    p = valley.project(pid)
    rows = []
    for m in p["milestones"]:
        for oid in m["fundings"]:
            o = valley._safe_order(oid)
            if not o or o["status"] == "pending":
                continue
            sig = o["signatures"].get("referee_2_pass") or o["signatures"].get("referee_1_pass") or o["signatures"].get("refund") or o["signatures"].get("lock")
            rows.append({"date": (o.get("made") or "")[:10], "project": p["title"], "milestone": m["name"], "order": o["order"],
                         "status": o["status"], "amount": f"{o['units'] * o['unit_price']:.2f}", "kind": o["kind"],
                         "counterparty": (o.get("paid_to") or {}).get("maker") or o["funder"], "reference": "KNOS-" + o["order"][:11],
                         "signature": sig or ""})
    return rows


ACCOUNTS = {"locked": ("Assets:Knos money held", "Liabilities:Milestone commitments"),
            "released": ("Expenses:Milestones paid", "Assets:Knos money held"),
            "refunded": ("Assets:Refunds receivable", "Assets:Knos money held"),
            "closed": ("Expenses:Milestones paid", "Assets:Knos money held")}


def export(pid: str, fmt: str) -> tuple[str, str]:
    if fmt not in FORMATS:
        raise ValueError(f"format: one of {', '.join(FORMATS)}")
    rows = ledger_lines(pid)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    memo = lambda r: f"TEST MONEY devnet; {r['milestone']}; {r['status']}; tx {r['signature'][:20]}"   # noqa: E731
    if fmt == "journal":
        w.writerow(["date", "description", "account", "amount", "reference", "status"])
        for r in rows:
            dr, cr = ACCOUNTS.get(r["status"], ACCOUNTS["locked"])
            desc = f"{r['project']}: {r['milestone']} ({r['status']}, {r['kind']})"
            w.writerow([r["date"], desc, dr, r["amount"], r["reference"], r["status"]])
            w.writerow([r["date"], desc, cr, "-" + r["amount"], r["reference"], r["status"]])
    elif fmt == "xero":          # Xero's bill import template columns (*: required)
        w.writerow(["*ContactName", "*InvoiceNumber", "*InvoiceDate", "*DueDate", "Description", "*Quantity", "*UnitAmount", "*AccountCode", "*TaxType", "Currency"])
        for r in rows:
            if r["status"] == "released":
                w.writerow([r["counterparty"], r["reference"], r["date"], r["date"], memo(r), "1", r["amount"], "400", "Tax Exempt", "USD"])
    elif fmt == "quickbooks":    # QuickBooks Online journal entry import
        w.writerow(["JournalNo", "JournalDate", "AccountName", "Debits", "Credits", "Description", "Name"])
        for r in rows:
            dr, cr = ACCOUNTS.get(r["status"], ACCOUNTS["locked"])
            w.writerow([r["reference"], r["date"], dr, r["amount"], "", memo(r), r["counterparty"]])
            w.writerow([r["reference"], r["date"], cr, "", r["amount"], memo(r), r["counterparty"]])
    else:                        # NetSuite CSV journal import
        w.writerow(["External ID", "Date", "Account", "Debit", "Credit", "Memo", "Name"])
        for r in rows:
            dr, cr = ACCOUNTS.get(r["status"], ACCOUNTS["locked"])
            w.writerow([r["reference"], r["date"], dr, r["amount"], "", memo(r), r["counterparty"]])
            w.writerow([r["reference"], r["date"], cr, "", r["amount"], memo(r), r["counterparty"]])
    return buf.getvalue(), "text/csv; charset=utf-8"


HLEDGER_RULES = """# hledger CSV rules for Knos's journal export (knos_wanted.enterprise.export(..., "journal"))
skip 1
fields date, description, account1, amount, code, status_
currency USD
account2 equity:knos import balancing
"""
