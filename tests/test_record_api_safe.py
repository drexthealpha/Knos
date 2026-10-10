"""The record API as a stranger meets it (src/knos/record_api.py, src/knos/selfhost.py): a rate limit per client, every
route's auth stated and enforced, every input checked (400 with one line), no stack trace in any answer, and one
deployment's records and counts never handed to another. A stdlib HTTP client against a server on an ephemeral port;
no network beyond 127.0.0.1, no clock but the test's own."""
from __future__ import annotations

import http.client
import json
import shutil
import threading
from pathlib import Path

import pytest

from knos import cli, record_api, selfhost

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "docs" / "records"
ORDER = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"      # any base58 address: these tests never reach a chain
SIG = "5" * 88
SECRET = "rpc.example/?api-key=DO-NOT-SHOW"


class Chain:
    """A chain that never answers, with words an operator would not want a caller to read."""
    def infos(self, _keys):
        raise RuntimeError(f"connection refused by https://{SECRET}\n  File \"relay.py\", line 9")

    def account(self, _key):
        raise RuntimeError(f"connection refused by https://{SECRET}")

    def now(self):
        raise RuntimeError(f"no clock from https://{SECRET}")


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def server(records: Path = RECORDS, **kw) -> record_api.Server:
    return record_api.Server({"lookups": record_api.PACK, "url": "https://records.example"}, Chain(), records, **kw)


def payment(**payload) -> str:
    body = {"x402Version": record_api.X402_VERSION, "accepted": {}, "payload": {"order": ORDER, "n": 0, "signature": SIG, **payload}}
    return record_api.encode(body)


class Running:
    """The server on 127.0.0.1, port 0, answering in a thread until the block ends."""
    def __init__(self, srv: record_api.Server):
        self.httpd = record_api.serve(srv, port=0)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(10)

    def ask(self, path: str, method: str = "GET", headers: dict | None = None, body: bytes | None = None):
        c = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=10)
        try:
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            raw = r.read().decode("utf-8")
            return r.status, {k.lower(): v for k, v in r.getheaders()}, raw
        finally:
            c.close()


# -- item 3: rate limiting ----------------------------------------------------------------------------------------------
def test_a_token_bucket_per_client_refills_at_its_rate():
    clock = Clock()
    lim = record_api.Limiter(rate=1, burst=3, clock=clock)
    assert [lim.take("a") for _ in range(3)] == [0.0, 0.0, 0.0]
    assert lim.take("a") == pytest.approx(1.0) and lim.take("b") == 0.0           # one client's flood is not another's
    clock.t += 0.5
    assert lim.take("a") == pytest.approx(0.5)
    clock.t += 0.5
    assert lim.take("a") == 0.0
    clock.t += 1000
    assert [lim.take("a") for _ in range(4)][-1] > 0                              # a long rest refills to the burst, no more
    with pytest.raises(ValueError):
        record_api.Limiter(rate=0)
    small = record_api.Limiter(rate=1, burst=1, clock=clock, most=2)
    for who in ("x", "y", "z", "w"):
        small.take(who)
    assert len(small._buckets) <= 2                                               # a flood of addresses cannot grow memory


def test_past_the_limit_a_client_gets_429_with_retry_after_and_others_are_served():
    srv = server(limiter=record_api.Limiter(rate=0.5, burst=2, clock=Clock()))
    with Running(srv) as s:
        assert [s.ask("/records/codex.json")[0] for _ in range(2)] == [200, 200]
        status, headers, raw = s.ask("/records/codex.json")
    assert status == 429 and headers["retry-after"] == "2" and json.loads(raw)["error"].startswith("too many requests")
    assert srv.handle("/records/codex.json", {}, client="10.0.0.2")[0] == 200
    assert srv.handle("/records/codex.json", {})[0] == 200                         # a call in this process is not limited
    assert record_api.RATE > 0 and record_api.BURST >= 1


# -- item 4: auth on every route ------------------------------------------------------------------------------------------
def test_every_route_is_stated_and_answers_as_stated_and_nothing_else_is_served():
    pytest.importorskip("solders")
    srv = server()
    assert [(r[0], r[1]) for r in record_api.ROUTES] == [("/records/<slug>.json", "public"), ("/lookup/<slug>", "paid"),
                                                         ("/orders/<order>", "public"), ("/health", "public")]
    assert srv.handle("/records/codex.json", {})[0] == 200
    assert srv.handle(f"/orders/{ORDER}", {})[2]["used"] == 0
    assert srv.handle("/health", {})[0] == 503                                   # public, and honest that the chain does not answer
    srv.offer = record_api.offer(ORDER, 1, ORDER, 1, 1, "o/wf", "a" * 40, "terms")
    status, headers, body = srv.handle("/lookup/codex", {})
    assert status == 402 and "PAYMENT-REQUIRED" in headers and "record" not in body   # paid: nothing of the answer without payment
    for path in ("/", "/admin", "/records/", "/records/codex.svg", "/lookup", "/orders"):
        status, _h, body = srv.handle(path, {})
        assert status == 404 and body["routes"] == [r[0] for r in record_api.ROUTES], path
    with Running(srv) as s:
        for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
            status, headers, raw = s.ask("/records/codex.json", method)
            assert status == 405 and headers["allow"] == "GET" and "\n" not in raw, method
        status, headers, raw = s.ask("/records/codex.json", "HEAD")
        assert status == 405 and raw == ""
        status, headers, _raw = s.ask("/records/codex.json")
        assert headers["server"].startswith("knos-record") and "python" not in headers["server"].lower()
        assert headers["x-content-type-options"] == "nosniff"


# -- item 6: every input checked on the server ---------------------------------------------------------------------------
BAD = [
    ("/records/" + "a" * 300 + ".json", {}, "over 200 characters"),
    ("/records/codex.json?x=1", {}, "no query string"),
    ("/records/%2e%2e%2fsecret.json", {}, "characters no route has"),
    ("/records/Codex.json", {}, "lower-case letters"),
    ("/records/../codex.json", {}, "lower-case letters"),
    ("/lookup/a--b", {}, "single dashes"),
    ("/lookup/" + "a" * 65, {}, "64 at most"),
    ("/orders/not-an-order", {}, "Solana address"),
    ("/lookup/codex", {"Attested-Payer": "me"}, "Attested-Payer"),
    ("/lookup/codex", {"PAYMENT-SIGNATURE": "not base64"}, "not base64 JSON"),
    ("/lookup/codex", {"PAYMENT-SIGNATURE": "x" * 5000}, "over 4096"),
    ("/lookup/codex", {"PAYMENT-SIGNATURE": record_api.encode([1, 2])}, "payload {order, n, signature}"),
    ("/lookup/codex", {"PAYMENT-SIGNATURE": record_api.encode({"payload": {}})}, "x402Version"),
    ("/lookup/codex", {"PAYMENT-SIGNATURE": payment(order="0OIl")}, "payload.order"),
    ("/lookup/codex", {"PAYMENT-SIGNATURE": payment(n=-1)}, "payload.n"),
    ("/lookup/codex", {"PAYMENT-SIGNATURE": payment(n=True)}, "payload.n"),
    ("/lookup/codex", {"PAYMENT-SIGNATURE": payment(n="0")}, "payload.n"),
    ("/lookup/codex", {"PAYMENT-SIGNATURE": payment(signature="short")}, "payload.signature"),
    ("/lookup/codex", {"PAYMENT-SIGNATURE": payment(transaction="<script>")}, "payload.transaction"),
    ("/lookup/codex", {"Record-Grant": "g" * 5000}, "Record-Grant"),
]


@pytest.mark.parametrize("path,headers,said", BAD, ids=[f"bad{i}" for i in range(len(BAD))])
def test_a_bad_input_is_400_with_one_line_saying_why(path, headers, said):
    status, _h, body = server().handle(path, headers)
    assert status == 400 and said in body["error"] and "\n" not in body["error"] and list(body) == ["error"]


def test_a_grant_of_the_wrong_shape_is_refused_before_it_is_used():
    from knos import record_answer as R
    good = {"schema": R.GRANT, "supplier": "codex", "reader": ORDER, "fields": ["disputes"], "issued": 1, "not_after": 2, "key": ORDER, "signature": SIG}
    assert R.grant_shape(good) is None
    for change, said in (({"issued": "1"}, "issued"), ({"not_after": True}, "not_after"), ({"fields": "disputes"}, "fields"),
                         ({"fields": [{"a": 1}]}, "fields"), ({"fields": []}, "fields"), ({"reader": 7}, "reader"), ({"extra": 1}, "fields no grant has"),
                         ({"supplier": "x" * 200}, "supplier")):
        assert said in R.grant_shape({**good, **change})
        assert R.check_grant({**good, **change}, "codex", ORDER, ORDER, 1)[0] == []     # never an exception, never a field


def test_a_request_with_a_body_is_refused_on_the_socket():
    with Running(server()) as s:
        status, _h, raw = s.ask("/records/codex.json", body=b'{"a": 1}', headers={"Content-Type": "application/json"})
    assert status == 400 and json.loads(raw) == {"error": "a request to this API carries no body"}


# -- item 8: errors never leak a stack trace -----------------------------------------------------------------------------
def test_an_unforeseen_error_is_a_500_with_one_line_and_the_trace_only_on_the_operators_terminal(capsys):
    with Running(server(debug=False)) as s:
        status, _h, raw = s.ask("/lookup/codex", headers={"PAYMENT-SIGNATURE": payment()})
        h_status, _h2, h_raw = s.ask("/health")
    assert status == 500 and json.loads(raw) == {"error": "the server could not answer this request (its operator can run it with --debug to see why)"}
    assert h_status == 503 and json.loads(h_raw)["chain"] == {"ok": False, "why": "the chain did not answer"}
    for text in (raw, h_raw, capsys.readouterr().err):
        assert "DO-NOT-SHOW" not in text and "Traceback" not in text and "File " not in text
    with Running(server(debug=True)) as s:
        status, _h, raw = s.ask("/lookup/codex", headers={"PAYMENT-SIGNATURE": payment()})
        h_raw = s.ask("/health")[2]
    err = capsys.readouterr().err
    assert status == 500 and "DO-NOT-SHOW" not in raw + h_raw                  # the caller never sees it, debug or not
    assert "Traceback" in err and "RuntimeError" in err                         # the operator does, when asked


def test_knos_record_serve_stops_with_one_line_unless_debug(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("KNOS_DEBUG", raising=False)
    assert record_api.main([str(tmp_path / "no-offer.json"), "--port", "0"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("knos record serve stopped: ") and err.count("\n") == 1 and "Traceback" not in err
    with pytest.raises(OSError):
        record_api.main([str(tmp_path / "no-offer.json"), "--port", "0", "--debug"])
    with pytest.raises(SystemExit):
        record_api.main([str(tmp_path / "no-offer.json"), "--rate", "0"])


def test_the_cli_says_one_line_and_shows_the_trace_only_with_debug(monkeypatch, capsys):
    def boom(**_kw):
        raise RuntimeError("deep inside\n  File \"x.py\", line 1")
    monkeypatch.setattr(cli, "load", lambda command=None: None)
    monkeypatch.setattr(cli, "_app", boom)
    monkeypatch.delenv("KNOS_DEBUG", raising=False)
    assert cli.main(["anything"]) == 1
    got = capsys.readouterr()
    assert got.out.strip().startswith("knos stopped: RuntimeError: deep inside") and "--debug" in got.out
    assert "Traceback" not in got.out + got.err and len(got.out.strip().splitlines()) == 1
    assert cli.main(["--debug", "anything"]) == 1
    assert "Traceback" in capsys.readouterr().err
    monkeypatch.setenv("KNOS_DEBUG", "1")
    assert cli.main(["anything"]) == 1
    assert "Traceback" in capsys.readouterr().err


# -- item 5: one deployment's data never reaches another ----------------------------------------------------------------
def test_two_tenants_sharing_a_memory_folder_see_only_their_own_records_and_counts(tmp_path):
    pytest.importorskip("sibyl_memory_client")
    offer = tmp_path / "offer.json"
    offer.write_text(json.dumps({"lookups": record_api.PACK}), encoding="utf-8")
    folders = {}
    for tenant, slug in (("buyer-a", "codex"), ("buyer-b", "copilot")):
        folders[tenant] = tmp_path / tenant
        folders[tenant].mkdir()
        shutil.copy(RECORDS / f"{slug}.json", folders[tenant] / f"{slug}.json")
    a = record_api.build_server(offer, folders["buyer-a"], tmp_path / "memory", ledger=Chain(), tenant="buyer-a")
    b = record_api.build_server(offer, folders["buyer-b"], tmp_path / "memory", ledger=Chain(), tenant="buyer-b")
    assert a.handle("/records/codex.json", {})[0] == 200 and b.handle("/records/codex.json", {})[0] == 404
    assert b.handle("/records/copilot.json", {})[0] == 200 and a.handle("/records/copilot.json", {})[0] == 404
    (folders["buyer-b"] / "codex.json").symlink_to(folders["buyer-a"] / "codex.json")      # a link into the other's folder
    assert b.handle("/records/codex.json", {})[0] == 404 and b.record("codex") is None
    a._spend(ORDER, 0)
    a._spend(ORDER, 1)
    assert a.handle(f"/orders/{ORDER}", {})[2]["used"] == 2 and b.handle(f"/orders/{ORDER}", {})[2]["used"] == 0
    again = record_api.build_server(offer, folders["buyer-a"], tmp_path / "memory", ledger=Chain(), tenant="buyer-a")
    assert again.used(ORDER) == 2                                                   # and a restart keeps its own
    assert record_api.tenant_id(None) == "knos-record-api" and record_api.tenant_id("buyer-a") == "knos-record-api:buyer-a"
    with pytest.raises(ValueError):
        record_api.tenant_id("../buyer-b")


GOOD = """
[chain]
cluster = "devnet"
rpc = "https://api.devnet.solana.com"

[record]
offer = "offer.json"
tenant = "buyer-a"
rate = 5
burst = 50
"""


def test_the_self_host_config_names_the_tenant_and_the_limit_and_refuses_bad_ones(tmp_path):
    c = selfhost.check(GOOD, tmp_path)
    assert c.errors == []
    args = selfhost.argv_of(c, "record", tmp_path, state=tmp_path / "state")
    assert args[args.index("--tenant") + 1] == "buyer-a" and args[args.index("--rate") + 1] == "5" and args[args.index("--burst") + 1] == "50"
    assert "--memory" in args
    for change, said in (('tenant = "Buyer A"', "record.tenant"), ("rate = 0", "record.rate"), ("burst = true", "record.burst"),
                         ('rate = "5"', "record.rate")):
        key = change.split(" =")[0]
        text = "\n".join(line for line in GOOD.splitlines() if not line.startswith(key + " ")) + "\n" + change + "\n"
        assert any(said in e for e in selfhost.check(text, tmp_path).errors), change
