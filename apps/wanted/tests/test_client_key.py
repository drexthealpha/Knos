"""The address a rate limit counts behind a proxy (KNOS_WANTED_TRUST_PROXY = the number of trusted proxies that
append to X-Forwarded-For; Render: 1). A client can send its own X-Forwarded-For: those leading entries never
change the key."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from knos_wanted import server


def test_the_entry_the_proxy_appended_is_the_key_and_forged_leading_entries_change_nothing(monkeypatch):
    monkeypatch.setenv("KNOS_WANTED_TRUST_PROXY", "1")
    assert server.client_key("203.0.113.7", "10.0.0.1") == "203.0.113.7"                       # Render appended it
    assert server.client_key("1.2.3.4, 203.0.113.7", "10.0.0.1") == "203.0.113.7"              # forged lead, same key
    assert server.client_key("9.9.9.9, 8.8.8.8, 203.0.113.7", "10.0.0.1") == "203.0.113.7"
    assert server.client_key("", "10.0.0.1") == "10.0.0.1"
    monkeypatch.setenv("KNOS_WANTED_TRUST_PROXY", "2")                                         # CDN + Render
    assert server.client_key("1.2.3.4, 203.0.113.7, 198.51.100.2", "10.0.0.1") == "203.0.113.7"
    # Cloudflare in front: its CF-Connecting-IP is the key, whichever edge address the proxy appended this time
    assert {server.client_key(f"203.0.113.7, 172.70.0.{i}", "10.0.0.1", "203.0.113.7") for i in range(5)} == {"203.0.113.7"}
    for off in ("", "0", "yes"):
        monkeypatch.setenv("KNOS_WANTED_TRUST_PROXY", off)
        assert server.trusted_hops() == 0 and server.client_key("1.2.3.4, 203.0.113.7", "10.0.0.1") == "10.0.0.1"
        assert server.client_key("", "10.0.0.1", "203.0.113.7") == "10.0.0.1"          # no trusted proxy: the header is ignored


def test_a_client_cannot_step_around_the_faucet_limit_with_a_forged_header(monkeypatch, tmp_path):
    monkeypatch.setenv("KNOS_WANTED_TRUST_PROXY", "1")
    state = server.State()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    seen = []
    try:
        cap = server.LIMITS["faucet"][0]
        for i in range(cap + 2):
            req = urllib.request.Request(f"http://127.0.0.1:{httpd.server_address[1]}/api/wallet/faucet", data=b"{}", method="POST",
                                         headers={"Content-Type": "application/json", "X-Forwarded-For": f"10.9.9.{i}, 203.0.113.7"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    seen.append(r.status)
            except urllib.error.HTTPError as e:
                seen.append(e.code)
                json.loads(e.read() or b"{}")
    finally:
        httpd.shutdown()
    assert seen[cap:] == [429, 429], seen          # the forged first entries are ignored: one key, one limit
