"""Round 13, H4: the Telegram bot (knos_wanted.telegram_bot) against a stand-in Telegram server.

The stand-in is a local http.server in a thread that answers the two Bot API methods the bot uses (getUpdates,
sendMessage) at /bot<token>/<method>, so no message leaves this machine. The program is the released one when it exists,
else the stand-in under tests, as in test_tool_run.py."""
import hashlib
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from knos_wanted import telegram_bot, tool_run
from knos_wanted.runner_conf import CONF

STANDIN = Path(__file__).parent / "limit_standin.py"
TOKEN = "123456:stand-in-token-for-tests"
LINK = re.compile(r"https://knos\.onrender\.com/r/([A-Za-z0-9_-]{12})/")


@pytest.fixture(autouse=True)
def program(monkeypatch):
    """The released program when it is the one released for test_limit3.py, else the stand-in under tests."""
    if not (tool_run.ready() and str(tool_run.released().get("test") or "").endswith("/" + CONF["claim_test"])):
        rel = {**tool_run.released(), "sha256": hashlib.sha256(STANDIN.read_bytes()).hexdigest()}
        monkeypatch.setattr(tool_run, "program_path", lambda: STANDIN)
        monkeypatch.setattr(tool_run, "released", lambda: rel)      # ready() compares the program with released.json
    monkeypatch.setattr(tool_run, "_mem", {})


class StandIn:
    """A stand-in for api.telegram.org: queued updates out through getUpdates, sendMessage calls recorded."""

    def __init__(self):
        self.updates, self.sent, self.paths = [], [], []
        self.got = threading.Event()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                outer.paths.append(self.path)
                m = re.fullmatch(r"/bot([^/]+)/(\w+)", self.path)
                if not m or m.group(1) != TOKEN:
                    return self._send(401, {"ok": False, "description": "Unauthorized"})
                if m.group(2) == "getUpdates":
                    off = int(body.get("offset") or 0)
                    out = [u for u in outer.updates if u["update_id"] >= off]
                    if not out:
                        time.sleep(min(0.2, float(body.get("timeout") or 0)))
                    return self._send(200, {"ok": True, "result": out})
                if m.group(2) == "sendMessage":
                    outer.sent.append(body)
                    outer.got.set()
                    return self._send(200, {"ok": True, "result": {"message_id": len(outer.sent)}})
                return self._send(404, {"ok": False, "description": "Not Found"})

            def _send(self, code, doc):
                b = json.dumps(doc).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def say(self, text, chat=42):
        self.updates.append({"update_id": 1000 + len(self.updates),
                             "message": {"message_id": 1, "chat": {"id": chat, "type": "private"},
                                         "from": {"id": chat, "is_bot": False}, "text": text}})

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def tg():
    s = StandIn()
    yield s
    s.close()


@pytest.fixture
def bot(tg):
    return telegram_bot.Bot(telegram_bot.Telegram(TOKEN, tg.url), poll_s=0)


def ask(tg, bot, text, chat=42) -> str:
    tg.say(text, chat)
    n = len(tg.sent)
    bot.poll()
    assert len(tg.sent) == n + 1
    assert tg.sent[-1]["chat_id"] == chat
    return tg.sent[-1]["text"]


def test_no_token_no_start(capsys):
    before = {t.name for t in threading.enumerate()}
    assert telegram_bot.start(env={}) is None
    assert telegram_bot.start(env={"KNOS_TELEGRAM_TOKEN": "  "}) is None
    assert "knos-telegram" not in {t.name for t in threading.enumerate()} - before
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["knos telegram: off (KNOS_TELEGRAM_TOKEN is not set)"] * 2


def test_sample_answers_the_sentence_and_link(tg, bot):
    text = ask(tg, bot, "sample")
    sentence, link = text.split("\n")
    want = tool_run.run_program(tool_run.sample(), CONF["sample_column"], CONF["sample_rule"], CONF["sample_limit"])
    assert sentence == want["result"]
    m = LINK.fullmatch(link)
    assert m, link
    rec = tool_run.load_result(m.group(1))
    assert rec and rec["mode"] == "sample" and rec["result"] == sentence
    for word in ("Sample ", "/sample"):
        assert ask(tg, bot, word).split("\n")[0] == sentence


def test_pasted_table_with_first_line_answers_its_result(tg, bot):
    text = ask(tg, bot, "reading above 3\ncycle,reading\n1,5\n2,6\n3,2\n4,7", chat=-1001)
    lines = text.split("\n")
    assert lines[0] == "reading must stay above 3"
    assert lines[1] == "Failed at row 3: 2 is not above 3. 2 rows passed."   # the rows checked before the first failing row (the released program)
    rec = tool_run.load_result(LINK.fullmatch(lines[2]).group(1))
    assert rec["mode"] == "own" and rec["first_failing_row"] == 3
    assert lines[3] == f"Runs left today: {int(CONF['free_runs_a_day']) - 1}"


def test_pasted_table_without_first_line_uses_the_sample_rule_and_limit(tg, bot):
    text = ask(tg, bot, "cycle,capacity_ah\n1,1.6\n2,1.5\n3,1.45")
    assert text.split("\n")[:2] == ["capacity_ah must stay above 1.4", "Passed: all 3 rows stay above 1.4."]
    other = ask(tg, bot, "t,volts,amps\n1,9,0.5\n2,9,0.3")         # no sample column: the last column, as the site
    assert other.split("\n")[:2] == ["amps must stay above 1.4", "Failed at row 1: 0.5 is not above 1.4. 0 rows passed."]


@pytest.mark.parametrize("text", ["hello", "a,b\nx,y", "volts above 3\nt,amps\n1,2", "one line, only", ""])
def test_malformed_table_answers_a_first_person_error(tg, bot, text):
    got = ask(tg, bot, text)
    assert len(got.split()) >= 12, got
    assert got.startswith("I "), got
    assert re.search(r"Please|Put one|Send", got), got
    assert not LINK.search(got)


def test_a_file_gets_a_first_person_error(tg, bot):
    tg.updates.append({"update_id": 5, "message": {"chat": {"id": 7}, "from": {"is_bot": False}, "document": {"file_id": "x"}}})
    bot.poll()
    got = tg.sent[-1]["text"]
    assert len(got.split()) >= 12 and got.startswith("I ") and "Please" in got


def test_own_runs_share_the_site_allowance_per_chat(tg, bot, monkeypatch):
    monkeypatch.setitem(CONF, "free_runs_a_day", 2)
    table = "x,y\n1,5\n2,6"
    assert "Runs left today: 1" in ask(tg, bot, table, chat=1)
    assert "Runs left today: 0" in ask(tg, bot, table, chat=1)
    got = ask(tg, bot, table, chat=1)
    assert got.startswith("Today's 2 free runs") and len(got.split()) >= 12
    assert not LINK.search(got)
    assert "Runs left today: 1" in ask(tg, bot, table, chat=2)            # another chat, its own allowance
    assert LINK.search(ask(tg, bot, "sample", chat=1))                    # the sample stays free


def test_every_error_is_twelve_words_with_a_next_step():
    msgs = [telegram_bot.NOT_TEXT, telegram_bot.NOT_TABLE, telegram_bot.no_column("x", ["a", "b"]),
            telegram_bot.no_numbers("x"), telegram_bot.too_big(), telegram_bot.used_up()]
    msgs += [telegram_bot.refused(tool_run.Refusal(c, {"error": "x"})) for c in (402, 408, 413, 500, 503, 404)]
    msgs.append(telegram_bot.refused(tool_run.Refusal(503, tool_run.not_ready())))
    for m in msgs:
        assert len(m.split()) >= 12, m
        assert re.search(r"\b(I|me|my)\b", m), m
        assert re.search(r"Please|Send|Put one|try again", m), m
        assert "box" not in m and "Try it" not in m and "Check my data" not in m, m


def test_started_with_a_token_answers_through_the_loop_and_hides_the_token(tg, capsys):
    b = telegram_bot.start(env={"KNOS_TELEGRAM_TOKEN": TOKEN, "KNOS_TELEGRAM_API": tg.url}, poll_s=0)
    try:
        assert b is not None and b.thread.is_alive()
        tg.say("sample")
        assert tg.got.wait(30)
        assert LINK.search(tg.sent[0]["text"])
    finally:
        b.stop()
    assert not b.thread.is_alive()
    assert TOKEN not in repr(b.tg)
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err
    assert out.out.strip().splitlines() == ["knos telegram: on (long polling)"]


def test_a_wrong_token_is_reported_without_the_token(tg, capsys):
    b = telegram_bot.Bot(telegram_bot.Telegram("999:wrong", tg.url), poll_s=0)
    b.stopped.set()
    with pytest.raises(Exception) as e:
        b.poll()
    assert telegram_bot._why(e.value) == "HTTPError 401"
    assert "999:wrong" not in telegram_bot._why(e.value)
