"""H1: only the maker who claimed a milestone posts its evidence. A guest session (free from /api/auth/guest or the MCP
tool knos_sign_in) that does not own the commitment gets 403 from /api/milestone and from knos_evidence, and nothing is
fetched, signed or released; the owner still reaches the release. test_the_old_exploit is the attack as it was run:
on the code before this fix it reached the release."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from knos_wanted import agent, auth, escrow, preorder, server
from knos_wanted.qloo_mcp import InProcess, Qloo
from knos_wanted.qloo_rest import Client

ORDER = "So11111111111111111111111111111111111111112"
OWNER = "passkey:" + "a" * 16


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """One locked commitment whose milestone the passkey OWNER claimed, a server, and a record of every release asked for."""
    monkeypatch.setattr(escrow, "_state_dir", lambda: tmp_path)
    preorder._save({"order": ORDER, "report": "0" * 64, "status": "locked", "claim_id": "knos-idea:" + "0" * 32, "units": 40,
                    "receivable": {"maker_sub": OWNER, "wallet": "W", "vault": "V"}})
    released = []
    monkeypatch.setattr(preorder, "milestone", lambda report, order, url, *a, **k: released.append((order, url)) or {"commitment": order, "release": "released"})
    state = server.State(Qloo(InProcess(), mode="mock", sleep=lambda s: None), Client(key="", base="https://example.test", folder=tmp_path))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", state, released
    httpd.shutdown()


def post(base: str, path: str, body: dict, token: str | None) -> tuple[int, dict]:
    h = {"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})}
    req = urllib.request.Request(base + path, json.dumps(body).encode(), h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def evidence_tool(state, session: str) -> dict:
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "knos_evidence", "arguments": {"commitment": ORDER, "evidence_url": "https://x.example/p", "session": session}}}
    return agent.mcp(state, msg)["result"]


def test_the_old_exploit(setup):
    """A fresh guest posts evidence on a commitment it does not own. Before the fix this reached the release."""
    base, state, released = setup
    guest = post(base, "/api/auth/guest", {"label": "anyone"}, None)[1]["token"]
    code, body = post(base, "/api/milestone", {"commitment": ORDER, "evidence_url": "https://x.example/p"}, guest)
    assert code == 403, (code, body)
    assert released == []


def test_guest_gets_403_from_the_api_and_the_mcp_tool(setup):
    base, state, released = setup
    guest_api = post(base, "/api/auth/guest", {"label": "x"}, None)[1]["token"]
    code, body = post(base, "/api/milestone", {"commitment": ORDER, "evidence_url": "https://x.example/p"}, guest_api)
    assert code == 403 and "owns" in body["error"]
    signed_in = agent.mcp(state, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "knos_sign_in", "arguments": {"label": "bot"}}})
    guest_mcp = signed_in["result"]["structuredContent"]["token"]
    got = evidence_tool(state, guest_mcp)
    assert got["isError"] is True and got["structuredContent"]["status"] == 403
    assert released == []                       # nothing fetched, signed or sent for either


def test_the_owner_still_can(setup):
    base, state, released = setup
    owner = auth.issue(OWNER, "passkey", "Maker")["token"]
    code, body = post(base, "/api/milestone", {"commitment": ORDER, "evidence_url": "https://x.example/p"}, owner)
    assert code == 200 and body["release"] == "released"
    got = evidence_tool(state, owner)
    assert not got.get("isError") and got["structuredContent"]["release"] == "released"
    assert released == [(ORDER, "https://x.example/p")] * 2


def test_a_commitment_that_names_no_owner_is_refused_to_everyone(setup, tmp_path):
    base, state, released = setup
    other = "So11111111111111111111111111111111111111113"
    preorder._save({"order": other, "report": "0" * 64, "status": "locked", "claim_id": "knos-idea:" + "1" * 32, "units": 5})
    owner = auth.issue(OWNER, "passkey", "Maker")["token"]
    code, _ = post(base, "/api/milestone", {"commitment": other, "evidence_url": "https://x.example/p"}, owner)
    assert code == 403 and released == []
