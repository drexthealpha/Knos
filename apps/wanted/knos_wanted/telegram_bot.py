"""The Knos tool inside Telegram (Round 13, H4): the same check as POST /api/run, answered in a chat.

It starts only when KNOS_TELEGRAM_TOKEN is set (server.serve calls start()); with no token nothing starts and one line
is printed. It talks to the Telegram Bot HTTP API with the standard library only: long polling with getUpdates, answers
with sendMessage. KNOS_TELEGRAM_API changes the API's address, so tests point it at a stand-in.

What it answers:
    "sample"          the sample's result sentence and its result link (a sample run: free, as on the site)
    a pasted table    that table's result sentence, its link and the runs left today
                      first line, if wanted: "<column> above <limit>" or "<column> below <limit>", e.g. "capacity_ah above 1.4";
                      with no such line: the sample's rule and limit, on the sample's column when the table has it, else
                      on the table's last column (the site's default column)
Each run goes through tool_run.run: the same tool, the same released program, the same limits. A run on a pasted table
is an own run with the site's allowance, keyed by the chat: the chat id stands in for the address, so the allowance is
held in this process's memory under a keyed hash (tool_run.address_key), never written and never in the measures.
The token is never printed: errors print only their kind and HTTP code."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request

from . import tool_page, tool_run
from .runner_conf import CONF

TOKEN_ENV = "KNOS_TELEGRAM_TOKEN"
API_ENV = "KNOS_TELEGRAM_API"
API = "https://api.telegram.org"
HEAD = re.compile(r"^\s*(?P<column>[^,]+?)\s+(?P<rule>above|below)\s+(?P<limit>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*$", re.I)
SITE = f"{tool_run.PUBLIC}/t/{tool_run.TOOL_ID}/"

HELLO = ("Send the word sample to see a check of a made-up battery test, or paste a table, one row per line with commas "
         f"between values. To choose the check, make the first line like this: {CONF['sample_column']} above "
         f"{tool_page.shown_limit(CONF['sample_limit'])}")
FORMAT = (f"To choose the check, make the first line like this: {CONF['sample_column']} above "
          f"{tool_page.shown_limit(CONF['sample_limit'])}")
NOT_TEXT = ("I can only read a table pasted as text in the message, not a file or a picture. Please paste the rows as "
            "text, or send the word sample.")
NOT_TABLE = ("I could not read a table in your message. Please paste a header and at least one row, one row per line "
             "with commas between values, or send the word sample.")


def no_column(column: str, names: list[str]) -> str:
    return (f"{tool_run.no_column(column, names)}\nPut one of them on the first line, like this: {names[-1][:40]} above "
            f"{tool_page.shown_limit(CONF['sample_limit'])}")


def no_numbers(column: str) -> str:
    return (f"I found no numbers in the column \"{column[:40]}\", so I have nothing to check. Please paste a table whose "
            f"column holds numbers, or name another column. {FORMAT}")


def too_big() -> str:
    return (f"Your table is too big for me to check: the limit is {int(CONF['max_rows']):,} rows. Please send a shorter "
            "table and I will check it.")


def used_up() -> str:
    return (f"Today's {CONF['free_runs_a_day']} free runs on your own tables in this chat are used, so I did not check "
            f"this one. Send it again tomorrow, or check it on the Knos site: {SITE}")


def refused(r: tool_run.Refusal) -> str:
    """A refusal of tool_run.run, said for a chat (the site's words speak of a box and a button)."""
    if r.code == 402:
        return used_up()
    if r.code == 413:
        return too_big()
    if r.code == 408:
        return (f"This took too long, so I stopped it after {tool_run.max_seconds()} seconds. Please send a shorter "
                "table and I will check it again.")
    if r.code == 503 and r.body == tool_run.not_ready():
        return r.body["error"]
    if r.code == 503:
        return "I am checking other tables right now and could not start yours. Please send it again in a moment."
    return ("Something went wrong and I have no result for this table, and the run was not counted. Please send it "
            "again, or send the word sample.")


def parse(text: str) -> tuple[str, str, str, float] | str:
    """(table, column, rule, limit) from a pasted message, or the message to answer when it is no table."""
    lines = [x for x in str(text).replace("\r\n", "\n").split("\n") if x.strip()]
    m = HEAD.match(lines[0]) if lines else None
    if m:
        lines = lines[1:]
        column, rule, limit = m["column"].strip(), m["rule"].lower(), float(m["limit"])
    else:
        column, rule, limit = None, CONF["sample_rule"], float(CONF["sample_limit"])
    if len(lines) < 2:
        return NOT_TABLE
    table = "\n".join(x.strip() for x in lines)
    names, n = tool_run.columns(table)
    if not names or n == 0:
        return NOT_TABLE
    if n > int(CONF["max_rows"]):
        return too_big()
    if column is None:
        column = CONF["sample_column"] if CONF["sample_column"] in names else names[-1]
    elif column not in names:
        return no_column(column, names)
    i = names.index(column)
    rows = [r for r in csv.reader(io.StringIO(table)) if any(c.strip() for c in r)]
    data = rows[1:] if rows and tool_run.header_row(rows[0]) else rows
    if not any(i < len(r) and tool_run._num(r[i]) is not None for r in data):
        return no_numbers(column)
    return table, column, rule, limit


def answer(text: str, chat_id) -> str:
    """The bot's reply to one text message from one chat."""
    said = str(text or "").strip()
    word = said.lower().lstrip("/").split("@")[0]
    if word in ("start", "help"):
        return HELLO
    address = f"telegram:{chat_id}"
    try:
        if word == "sample":
            got = tool_run.run({"id": tool_run.TOOL_ID, "table": tool_run.sample(), "column": CONF["sample_column"],
                                "rule": CONF["sample_rule"], "limit": CONF["sample_limit"]}, address)
            return f"{got['result']}\n{got['link']}"
        p = parse(said)
        if isinstance(p, str):
            return p
        table, column, rule, limit = p
        got = tool_run.run({"id": tool_run.TOOL_ID, "table": table, "column": column, "rule": rule, "limit": limit}, address)
    except tool_run.Refusal as r:
        return refused(r)
    out = f"{column} must stay {rule} {tool_page.shown_limit(limit)}\n{got['result']}\n{got['link']}"
    return out + (f"\nRuns left today: {got['runs_left']}" if got.get("runs_left") is not None else "")


class Telegram:
    """The Bot HTTP API: POST <api>/bot<token>/<method> with a JSON body; the answer's "result"."""

    def __init__(self, token: str, api: str = API):
        self._url = f"{api.rstrip('/')}/bot{token}/"

    def __repr__(self) -> str:
        return "Telegram(<token hidden>)"

    def call(self, method: str, params: dict, timeout: float = 20) -> object:
        req = urllib.request.Request(self._url + method, data=json.dumps(params).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:     # noqa: S310 (the API's own https address, or a test's)
            got = json.loads(r.read() or b"{}")
        if not got.get("ok"):
            raise RuntimeError(f"Telegram said not ok to {method}: {str(got.get('description'))[:120]}")
        return got.get("result")


def _why(e: Exception) -> str:
    """An error's kind and code, never its address (the address holds the token)."""
    code = getattr(e, "code", None)
    return f"{type(e).__name__}{f' {code}' if code else ''}"


class Bot:
    def __init__(self, tg: Telegram, poll_s: int = 30):
        self.tg, self.poll_s, self.offset = tg, poll_s, 0
        self.stopped = threading.Event()
        self.thread: threading.Thread | None = None

    def handle(self, update: dict) -> None:
        msg = update.get("message") or {}
        chat = (msg.get("chat") or {}).get("id")
        if chat is None or (msg.get("from") or {}).get("is_bot"):
            return
        text = msg.get("text")
        reply = answer(text, chat) if isinstance(text, str) else NOT_TEXT
        self.tg.call("sendMessage", {"chat_id": chat, "text": reply[:4000], "disable_web_page_preview": True})

    def poll(self) -> int:
        """One getUpdates; each update answered in order. The number of updates read."""
        got = self.tg.call("getUpdates", {"offset": self.offset, "timeout": self.poll_s, "allowed_updates": ["message"]},
                           timeout=self.poll_s + 10)
        updates = got if isinstance(got, list) else []
        for u in updates:
            self.offset = max(self.offset, int(u.get("update_id", 0)) + 1)
            try:
                self.handle(u)
            except Exception as e:  # noqa: BLE001
                print(f"knos telegram: an answer was not sent: {_why(e)}", file=sys.stderr, flush=True)
        return len(updates)

    def loop(self) -> None:
        wait = 1.0
        while not self.stopped.is_set():
            try:
                self.poll()
                wait = 1.0
            except Exception as e:  # noqa: BLE001
                print(f"knos telegram: polling failed, trying again in {wait:.0f} s: {_why(e)}", file=sys.stderr, flush=True)
                self.stopped.wait(wait)
                wait = min(60.0, wait * 2)

    def stop(self, join_s: float = 5) -> None:
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(join_s)


def start(env=None, poll_s: int = 30) -> Bot | None:
    """The bot in a thread of its own when KNOS_TELEGRAM_TOKEN is set; else None and one line."""
    env = os.environ if env is None else env
    token = str(env.get(TOKEN_ENV) or "").strip()
    if not token:
        print("knos telegram: off (KNOS_TELEGRAM_TOKEN is not set)", flush=True)
        return None
    bot = Bot(Telegram(token, str(env.get(API_ENV) or API)), poll_s)
    bot.thread = threading.Thread(target=bot.loop, daemon=True, name="knos-telegram")
    bot.thread.start()
    print("knos telegram: on (long polling)", flush=True)
    return bot
