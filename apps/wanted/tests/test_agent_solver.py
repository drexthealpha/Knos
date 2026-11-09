"""an outside agent holding only a capped, revocable agent key claims a referee-judged milestone,
submits to the sealed referee and is paid, with no human step. Agent keys (shown once, stored hashed, counters on
disk), OAuth 2.0 client credentials, the Bearer rule on every write tool, the Agent Card, and the solver briefs.
No network: a fake ledger; the round is the packaged demo task, judged for real."""
import base64
import importlib
import json
import threading
import types
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from solders.keypair import Keypair

from knos_wanted import agentkeys, auth, server, tasks, valley
from knos_wanted.qloo_mcp import InProcess, Qloo

BRIEF = {"milestones": [{"key": "m1", "name": "Login under 300 ms", "target": "p95 under 300 ms on test_login",
                         "verifier": {"kind": "machine", "check": "ci / test_login"}, "deadline_days": 7}]}


@pytest.fixture
def app():
    state = server.State(Qloo(InProcess(), mode="mock", sleep=lambda s: None))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def call(base, path, body=None, token=None, form=None, headers=None):
    h = {"Content-Type": "application/x-www-form-urlencoded" if form is not None else "application/json", **(headers or {})}
    if token:
        h["Authorization"] = "Bearer " + token
    data = urllib.parse.urlencode(form).encode() if form is not None else None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"{}"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}"), dict(e.headers)


def mcp(base, name, args, token=None):
    st, got, h = call(base, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}, token)
    assert st == 200, got
    return got["result"], h


def human(base, label="owner"):
    return call(base, "/api/auth/guest", {"label": label})[1]["token"]


def new_key(base, tok, **kw):
    body = {"label": "solver bot", "max_claims": 2, "max_spend_units": 10, "days": 7, "payout_wallet": str(Keypair().pubkey()), **kw}
    st, got, _ = call(base, "/api/agent/keys", body, tok)
    assert st == 200, got
    return got


def test_a_key_is_shown_once_stored_hashed_and_its_counters_survive_a_restart(monkeypatch):
    from knos_wanted import chainstate
    queued = []
    monkeypatch.setattr(chainstate, "queue_save", lambda kind, key, obj: queued.append(kind))
    owner = auth.guest("owner")
    with pytest.raises(auth.AuthError):
        agentkeys.create(None, "bot", 1, 5, 1, str(Keypair().pubkey()))
    for bad in ({"max_claims": 51}, {"max_spend_units": 10_001}, {"days": 91}, {"payout_wallet": "nope"}, {"max_claims": True}):
        args = {"max_claims": 1, "max_spend_units": 5, "days": 1, "payout_wallet": str(Keypair().pubkey()), **bad}
        with pytest.raises(valley.Refused):
            agentkeys.create(owner, "bot", args["max_claims"], args["max_spend_units"], args["days"], args["payout_wallet"])
    got = agentkeys.create(owner, "bot", 2, 50, 3, str(Keypair().pubkey()))
    kid, secret = got["id"], got["key"][len("knos_ak_") + 17:]
    assert got["key"] == f"knos_ak_{kid}_{secret}" and len(base64.urlsafe_b64decode(secret + "=")) == 32
    raw = (valley._dir("agentkeys") / f"{kid}.json").read_text(encoding="utf-8")
    assert secret not in raw and json.loads(raw)["secret_sha256"] and "agentkeys" in queued and "agentkeys" in chainstate.KINDS
    assert all("key" not in k and "secret_sha256" not in k for k in agentkeys.keys(owner))
    agentkeys.take_claim(kid)
    agentkeys.spent(kid, 5)
    agentkeys.principal("Bearer " + got["key"])
    importlib.reload(agentkeys)                         # a restart: nothing kept in memory, all read back from disk
    rec = valley._load("agentkeys", kid)
    assert (rec["claims_used"], rec["units_spent"], rec["calls"]) == (1, 5, 1)
    assert agentkeys.principal("Bearer " + got["key"])["sub"] == "agentkey:" + kid
    agentkeys.take_claim(kid)
    with pytest.raises(valley.Refused, match="claim cap"):
        agentkeys.take_claim(kid)
    with pytest.raises(valley.Refused, match="spend cap"):
        agentkeys.can_spend(kid, 46)
    with pytest.raises(agentkeys.Dead, match="expired"):
        agentkeys.principal("Bearer " + got["key"], now=rec["expires_s"] + 1)
    with pytest.raises(auth.AuthError):
        agentkeys.keys(None)
    with pytest.raises(valley.Refused):
        agentkeys.revoke(auth.guest("someone else"), kid)
    agentkeys.revoke(owner, kid)
    with pytest.raises(agentkeys.Dead, match="revoked"):
        agentkeys.principal("Bearer " + got["key"])


def test_oauth_client_credentials_and_the_published_metadata(app):
    tok = human(app)
    assert call(app, "/api/agent/keys", {"label": "x", "max_claims": 1, "max_spend_units": 1, "days": 1, "payout_wallet": "x"})[0] == 401
    k = new_key(app, tok)
    st, listed, _ = call(app, "/api/agent/keys", token=tok)
    assert st == 200 and [x["id"] for x in listed["keys"]] == [k["id"]] and "key" not in listed["keys"][0]
    secret = k["key"].split("_", 3)[3]
    st, got, _ = call(app, "/oauth/token", form={"grant_type": "client_credentials", "client_id": k["id"], "client_secret": secret})
    assert st == 200 and got["token_type"] == "Bearer" and got["expires_in"] == 3600 and got["scope"] == "knos.solve", got
    basic = base64.b64encode(f"{k['id']}:{secret}".encode()).decode()
    st, got2, _ = call(app, "/oauth/token", form={"grant_type": "client_credentials"}, headers={"Authorization": "Basic " + basic})
    assert st == 200 and got2["access_token"].startswith("knos_at_")
    st, bad, h = call(app, "/oauth/token", form={"grant_type": "client_credentials"},
                      headers={"Authorization": "Basic " + base64.b64encode(f"{k['id']}:wrong".encode()).decode()})
    assert st == 401 and bad["error"] == "invalid_client" and h["WWW-Authenticate"].startswith("Basic")
    assert call(app, "/oauth/token", form={"grant_type": "password", "client_id": k["id"], "client_secret": secret})[1]["error"] == "unsupported_grant_type"
    assert call(app, "/oauth/token", form={"grant_type": "client_credentials", "client_id": k["id"], "client_secret": secret,
                                           "scope": "admin"})[1]["error"] == "invalid_scope"
    st, asm, _ = call(app, "/.well-known/oauth-authorization-server")
    assert st == 200 and asm["token_endpoint"].endswith("/oauth/token") and asm["grant_types_supported"] == ["client_credentials"]
    assert {"client_secret_basic", "client_secret_post"} == set(asm["token_endpoint_auth_methods_supported"])
    st, prm, _ = call(app, "/.well-known/oauth-protected-resource")
    assert prm["resource"] == app + "/mcp" and prm["authorization_servers"] == [asm["issuer"]] == [app]   # live: https://knos.onrender.com
    assert call(app, "/.well-known/oauth-protected-resource/mcp")[1] == prm
    st, card, h = call(app, "/.well-known/agent-card.json")
    assert st == 200 and h["Access-Control-Allow-Origin"] == "*"
    for f in ("name", "description", "supportedInterfaces", "version", "capabilities", "defaultInputModes", "defaultOutputModes", "skills"):
        assert card[f], f
    assert card["supportedInterfaces"][0]["url"] == app + "/mcp" and card["supportedInterfaces"][0]["protocolBinding"] == "MCP"
    assert card["securitySchemes"]["agent_key"]["oauth2SecurityScheme"]["flows"]["clientCredentials"]["tokenUrl"].endswith("/oauth/token")
    assert [s["id"] for s in card["skills"]] == ["find-work", "claim-milestone", "submit-to-referee", "check-brief"]
    assert all(s["tags"] and s["description"] for s in card["skills"])


def test_every_write_tool_needs_a_bearer_credential_and_a_revoked_key_is_refused(app):
    tok = human(app)
    open_ = {"template": "custom", "title": "Agent's tool", "brief": BRIEF}
    no, h = mcp(app, "knos_project_open", {"template": "internal_tool", "title": "No credential"})
    assert no["isError"] and "oauth-protected-resource" in no["content"][0]["text"] and "knos_sign_in" in no["content"][0]["text"]
    assert 'resource_metadata="https://knos.onrender.com/.well-known/oauth-protected-resource"' in h["WWW-Authenticate"]
    assert mcp(app, "knos_templates", {})[0].get("isError") is None                  # reading needs nothing
    assert mcp(app, "knos_project_open", {"template": "internal_tool", "title": "A person's", "session": tok})[0].get("isError") is None
    assert mcp(app, "knos_project_open", {"template": "internal_tool", "title": "A person's header"}, tok)[0].get("isError") is None
    k = new_key(app, tok)
    secret = k["key"].split("_", 3)[3]
    at = call(app, "/oauth/token", form={"grant_type": "client_credentials", "client_id": k["id"], "client_secret": secret})[1]["access_token"]
    got, _ = mcp(app, "knos_project_open", {"template": "internal_tool", "title": "By the agent alone"}, at)
    assert got.get("isError") is None and got["structuredContent"]["owner_label"].startswith("solver bot (agent key")
    got, _ = mcp(app, "knos_project_open", {"template": "internal_tool", "title": "By the key itself"}, k["key"])
    assert got.get("isError") is None
    st, p, _ = call(app, "/api/project", open_, at)                                     # the REST route the tool calls: the same rule
    assert st == 200, p
    assert call(app, "/api/project", open_)[0] == 401
    assert call(app, "/api/agent/keys", {"label": "x", "max_claims": 1, "max_spend_units": 1, "days": 1,
                                         "payout_wallet": str(Keypair().pubkey())}, at)[0] == 401      # an agent makes no keys
    assert call(app, "/api/agent/keys/revoke", {"id": k["id"]}, tok)[1]["state"] == "revoked"
    for cred in (at, k["key"]):
        got, _ = mcp(app, "knos_project_open", {"template": "internal_tool", "title": "After revoke"}, cred)
        assert got["isError"] and "revoked" in got["content"][0]["text"]
    st, e, _ = call(app, "/api/project/claim", {"project": p["id"], "milestone": "m1"}, at)
    assert st == 401 and "revoked" in e["error"]
    assert call(app, "/oauth/token", form={"grant_type": "client_credentials", "client_id": k["id"], "client_secret": secret})[0] == 401


@pytest.fixture
def money(monkeypatch):
    from knos import chain
    from knos.ideas import commit as C

    from knos_wanted import escrow, preorder
    from test_valley import Led
    refs, relayer, mint, led = [Keypair() for _ in range(3)], Keypair(), Keypair().pubkey(), Led()
    monkeypatch.setattr(preorder, "_need", lambda: None)
    monkeypatch.setattr(preorder, "referees", lambda: refs)
    monkeypatch.setattr(preorder, "relayer", lambda: relayer)
    monkeypatch.setattr(escrow, "demo_key", lambda: relayer)
    monkeypatch.setattr(escrow, "mint", lambda led=None, create=True: mint)
    monkeypatch.setattr(valley, "_ledger", lambda x=None: x or led)

    def rpc(url, m, params, timeout=20):
        if m == "sendTransaction":                       # the funding lands: every order is on chain
            led.accounts.update({o["order"]: b"order" for o in valley._all("orders")})
            return "3" * 88
        if m == "getGenesisHash":                        # vault caches this answer per process: never poison it for other tests
            return escrow.DEVNET_GENESIS
        return {"value": {"blockhash": "11111111111111111111111111111111"}}
    monkeypatch.setattr(chain, "call", rpc)
    payees = []
    monkeypatch.setattr(C, "sign", lambda doc, stage, r, led, passed, review: payees.append(C.payees_of(doc["payee"])) or {"sig": 1})
    monkeypatch.setattr(C, "release", lambda doc, st, recs, rel, led: {"status": "released", "sent": [{"signature": "s1"}, {"signature": "s2"}]})
    monkeypatch.setenv("KNOS_GAME_DIR", "")              # the demo round this test seeds is forgotten after it
    return types.SimpleNamespace(led=led, payees=payees)


def winning(train: str) -> str:
    """The change the round's README names (features 'square', standardize True), on the baseline."""
    out = train.replace("'features': 'linear'", "'features': 'square'").replace("'standardize': False", "'standardize': True")
    assert out != train
    return out


def test_the_solver_briefs_are_ready_and_only_the_referee_one_releases_by_itself():
    rows = valley.solver_briefs("knos-demo-20261023000000")
    from knos import ready
    assert [b["id"] for b in rows] == ["lean_formal_conjecture", "modded_nanogpt_record", "autoresearch_round"]
    assert all(ready.check(b["brief"])["ready"] for b in rows)
    auto = [b["id"] for b in rows if valley.referee_round(b["brief"]["milestones"][0])]
    assert auto == ["autoresearch_round"] and valley.min_margin(rows[2]["brief"]["milestones"][0]) == 0.005
    assert "only one of the three" in rows[2]["note"] and all("No autonomous release" in b["note"] for b in rows[:2])


def test_an_agent_with_only_its_key_claims_submits_and_is_paid_with_no_human_step(app, money):
    """The operator opens and funds brief (c); then ONLY the key: a token, a losing submission (refused, nothing paid), a
    winning one: the referee's verdict releases the vault to the key's payout wallet, counted on its caps."""
    projects = valley.open_solver_briefs(["autoresearch_round"])
    pid = projects[0]["id"]
    rnd = tasks.round_state()
    m = projects[0]["milestones"][0]
    assert m["verifier"]["check"] == f"knos-referee:{rnd['id']}" and projects[0]["ready"]["ready"]
    assert valley.operator_fund_solver(pid, 5)["status"] == "locked"
    owner = human(app)
    wallet = str(Keypair().pubkey())
    k = new_key(app, owner, payout_wallet=wallet, max_claims=1, max_spend_units=5)
    secret = k["key"].split("_", 3)[3]
    at = call(app, "/oauth/token", form={"grant_type": "client_credentials", "client_id": k["id"], "client_secret": secret})[1]["access_token"]
    st, lst, _ = call(app, "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, at)
    assert "knos_milestone_submit" in {t["name"] for t in lst["result"]["tools"]}
    base = (tasks.TASK_DIR / "train.py").read_text(encoding="utf-8")
    no, _ = mcp(app, "knos_milestone_submit", {"project": pid, "milestone": m["key"], "code": base + "\n# same model\n"}, at)
    assert no["isError"] and "lift" in no["content"][0]["text"] and not money.payees
    got, _ = mcp(app, "knos_milestone_submit", {"project": pid, "milestone": m["key"], "code": winning(base)}, at)
    out = got.get("structuredContent")
    assert got.get("isError") is None, got
    assert out["milestone"] == "released" and out["released"][0]["status"] == "released" and out["claimed"] is False
    v = out["referee"]
    assert v["pass"] and v["decision"] == "scored" and v["lift"] >= 0.005 and v["round"] == rnd["id"]
    assert str(money.payees[0][0][2]) == wallet                                       # paid at the key's payout wallet only
    rec = valley._load("agentkeys", k["id"])
    assert (rec["claims_used"], rec["units_spent"], rec["calls"]) == (1, 5, 2)
    page = json.loads(valley.project_evidence(valley._evidence_id(pid, m["key"], out["attempt"])))
    assert page["kind"] == "knos-referee-verified-milestone" and page["claims"] and page["verdict"]["pass"]
    att = valley.project(pid)["milestones"][0]["attempts"][0]
    assert att["agent_key"] == k["id"] and att["status"] == "paid" and att["referee_tries"][0]["pass"] is False


def test_an_agent_keys_caps_refuse_a_claim_and_a_payout(app, money):
    p = valley.open_solver_briefs(["autoresearch_round"], round_id="knos-demo-20261023000000")[0]
    key = p["milestones"][0]["key"]
    valley.operator_fund_solver(p["id"], 6)
    owner = auth.guest("owner")
    poor = agentkeys.as_user(valley._load("agentkeys", agentkeys.create(owner, "poor bot", 3, 5, 1, str(Keypair().pubkey()))["id"]))
    with pytest.raises(valley.Refused, match="spend cap"):
        valley.claim(p["id"], key, poor, "")
    assert valley._load("agentkeys", poor["agent_key"])["claims_used"] == 0          # a refused claim is given back
    one = agentkeys.as_user(valley._load("agentkeys", agentkeys.create(owner, "one-claim bot", 1, 100, 1, str(Keypair().pubkey()))["id"]))
    with pytest.raises(valley.Refused, match="payout wallet"):
        valley.claim(p["id"], key, one, str(Keypair().pubkey()))
    valley.claim(p["id"], key, one, "")
    q = valley.open_solver_briefs(["autoresearch_round"], round_id="knos-demo-20261023000000")[0]
    with pytest.raises(valley.Refused, match="claim cap"):
        valley.claim(q["id"], key, one, "")
