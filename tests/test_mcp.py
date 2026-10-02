"""`knos mcp`: the server a coding agent talks to. Every test drives the real `serve` loop over in-memory streams,
with a chain and a GitHub made of dictionaries, so nothing here opens the network (conftest refuses it anyway).

The accounts are built byte for byte as knos-pay lays them out (see knos.settle.pay.read_job, read_due, read_rep).
"""

from __future__ import annotations

import io
import json

from solders.pubkey import Pubkey

from knos import mcp, version
from knos.settle import pay

NOW = 1_790_000_000
WIDGETS, GADGETS, GONE = 987_654_321, 555, 777      # repository ids
MONA = 1_234_567                                     # a GitHub user id


def _u64(v: int) -> bytes:
    return v.to_bytes(8, "little")


def job_bytes(repo_id: int, issue: int, amount: int, state: int = 1, mode: int = 0, deadline: int = NOW + 14 * 86_400,
              pay_after: int = 0, author_id: int = 0, funder: Pubkey | None = None) -> bytes:
    data = (bytes([state, mode, 1 if funder is None else 0]) + bytes(5) + _u64(repo_id) + _u64(issue) + _u64(amount)
            + _u64(deadline) + _u64(0) + _u64(pay_after) + _u64(author_id) + _u64(42) + _u64(0) + bytes(8)
            + bytes(funder or Pubkey.default()) + bytes(pay.faucet_mint()) + bytes(32) + pay.wf_repo_hash("drexthealpha/Knos")
            + b"c" * 40)
    assert len(data) == 256
    return data


def due_bytes(user_id: int, mint: Pubkey, amount: int) -> bytes:
    return _u64(amount) + _u64(user_id) + bytes(mint)


def rep_bytes(paid_jobs: int, total: int, repositories: int) -> bytes:
    return paid_jobs.to_bytes(4, "little") + bytes(4) + _u64(total) + repositories.to_bytes(4, "little") + bytes(12)


class Ledger:
    """The reads knos.mcp makes of a cluster, over a dictionary of accounts."""

    def __init__(self, accounts: dict | None = None, down: bool = False):
        self.accounts, self.down = dict(accounts or {}), down

    def _up(self) -> None:
        if self.down:
            raise OSError("connection refused\nTraceback (most recent call last): ...")

    def account(self, address):
        self._up()
        return self.accounts.get(address)

    def program_accounts(self, program, size: int, memcmp: dict[int, bytes] | None = None):
        self._up()
        assert program == pay.PAY_ID
        return [(a, d) for a, d in self.accounts.items()
                if len(d) == size and all(d[o:o + len(b)] == b for o, b in (memcmp or {}).items())]

    def now(self) -> int:
        self._up()
        return NOW


class GitHub:
    """api.github.com as a dictionary of paths; a path it does not have is the network failing."""

    def __init__(self, pages: dict | None = None):
        self.pages, self.asked = dict(pages or {}), []

    def __call__(self, path: str):
        self.asked.append(path)
        if path not in self.pages:
            raise OSError(f"no route to api.github.com for {path}")
        return self.pages[path]


def talk(messages: list, ledger=None, github=None) -> list:
    """Run the server over these lines (dicts are serialised; strings are sent as they are). Every line it wrote."""
    stdin = io.StringIO("".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in messages))
    stdout = io.StringIO()
    mcp.serve(stdin, stdout, ledger=ledger, github=github or GitHub())
    lines = stdout.getvalue().splitlines()
    assert stdout.getvalue() == "".join(line + "\n" for line in lines)     # whole lines, nothing else
    return [json.loads(line) for line in lines]                             # and every one of them is JSON


def call(name: str, arguments: dict | None = None, ledger=None, github=None) -> dict:
    """One tools/call, the 2026-07-28 way. Returns the result."""
    params = {"name": name, "arguments": arguments or {}, "_meta": {mcp.VERSION_KEY: mcp.PROTOCOL}}
    (reply,) = talk([{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}], ledger, github)
    assert reply["id"] == 1 and reply["result"]["resultType"] == "complete"
    return reply["result"]


def world() -> tuple[Ledger, GitHub]:
    """Three open bounties, one proven, one past its deadline; and what is waiting for mona."""
    wallet = Pubkey.from_string("4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo")
    ledger = Ledger({
        pay.job_pda(WIDGETS, 7): job_bytes(WIDGETS, 7, 20_000_000),
        pay.job_pda(WIDGETS, 7, wallet): job_bytes(WIDGETS, 7, 5_000_000, state=2, pay_after=NOW + 1800,
                                                   author_id=MONA, funder=wallet),
        pay.job_pda(GADGETS, 3): job_bytes(GADGETS, 3, 50_000_000, mode=1),
        pay.job_pda(GONE, 1): job_bytes(GONE, 1, 1_000_000),
        pay.job_pda(GADGETS, 9): job_bytes(GADGETS, 9, 90_000_000, deadline=NOW - 60),
        pay.due_pda(MONA, pay.faucet_mint()): due_bytes(MONA, pay.faucet_mint(), 19_500_000),
        pay.rep_pda(MONA): rep_bytes(3, 61_250_000, 2),
    })
    github = GitHub({
        f"repositories/{WIDGETS}": {"id": WIDGETS, "full_name": "octo/widgets"},
        f"repositories/{GADGETS}": {"id": GADGETS, "full_name": "acme/gadgets"},
        "repos/octo/widgets": {"id": WIDGETS, "full_name": "octo/widgets"},
        "repos/acme/gadgets/issues/3": {"number": 3, "title": "Retry the upload", "assignee": None, "assignees": [],
                                        "labels": [{"id": 1, "name": "bug", "color": "d73a4a"},
                                                   {"id": 2, "name": "good first issue", "color": "7057ff"}]},
        "repos/octo/widgets/issues/7": {"number": 7, "title": "Add a --json flag", "labels": [],
                                        "assignee": {"login": "mona"}, "assignees": [{"login": "mona"}]},
        "users/mona": {"id": MONA, "login": "mona"},
    })
    return ledger, github


# ---- the protocol ---------------------------------------------------------------------------------------------------


def test_a_session_client_shakes_hands_lists_the_tools_and_calls_one():
    ledger, github = world()
    hello, listed, called = talk([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": "three", "method": "tools/call", "params": {"name": "knos_due", "arguments": {"login": "mona"}}},
    ], ledger, github)
    assert hello == {"jsonrpc": "2.0", "id": 1, "result": {
        "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
        "serverInfo": {"name": "knos", "version": version()}, "instructions": mcp.INSTRUCTIONS}}
    assert "knos_bounties" in mcp.INSTRUCTIONS and "only when it is true" in mcp.INSTRUCTIONS
    tools = listed["result"]["tools"]
    assert [t["name"] for t in tools] == ["knos_bounties", "knos_bounty", "knos_check_pr", "knos_due"]
    assert listed["result"]["ttlMs"] == 300_000 and listed["result"]["cacheScope"] == "public"
    for t in tools:
        assert t["annotations"] == {"readOnlyHint": True, "openWorldHint": True} and t["title"] and t["description"]
        assert t["inputSchema"]["type"] == "object" and t["inputSchema"]["additionalProperties"] is False
    assert called["id"] == "three" and called["result"]["isError"] is False


def test_an_unknown_session_version_is_answered_with_the_newest_one_and_ping_is_empty():
    hello, pong = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}},
                        {"jsonrpc": "2.0", "id": 2, "method": "ping"}])
    assert hello["result"]["protocolVersion"] == "2025-11-25" and pong == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_a_stateless_client_discovers_lists_and_calls_with_no_handshake():
    ledger, github = world()
    meta = {"_meta": {mcp.VERSION_KEY: "2026-07-28"}}
    found, listed, called = talk([
        {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": meta},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": meta},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "knos_due", "arguments": {"login": "mona"}, **meta}},
    ], ledger, github)
    assert found["result"] == {"resultType": "complete", "supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}},
                               "instructions": mcp.INSTRUCTIONS,
                               "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "knos", "version": version()}}}
    assert listed["result"]["resultType"] == "complete" and len(listed["result"]["tools"]) == 4
    result = called["result"]
    assert result["resultType"] == "complete" and result["isError"] is False
    assert result["content"] == [{"type": "text", "text": json.dumps(result["structuredContent"], indent=1)}]


def test_a_protocol_version_the_server_does_not_speak_is_refused_by_name():
    (reply,) = talk([{"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {"_meta": {mcp.VERSION_KEY: "2027-01-01"}}}])
    assert reply == {"jsonrpc": "2.0", "id": 9, "error": {"code": -32022, "message": "Unsupported protocol version",
                                                         "data": {"supported": ["2026-07-28"], "requested": "2027-01-01"}}}


def test_a_notification_is_never_answered():
    assert talk([{"jsonrpc": "2.0", "method": "notifications/initialized"},
                 {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1, "reason": "x"}},
                 {"jsonrpc": "2.0", "method": "tools/list"},                 # even one that names a real method
                 {"jsonrpc": "2.0", "method": "no/such/thing"},
                 {"jsonrpc": "2.0", "id": 4, "result": {}},                  # a reply to nothing this server asked
                 ""]) == []


def test_a_line_that_is_not_json_gets_a_parse_error_and_the_server_keeps_going():
    bad, wrong, pong = talk(["{not json", "[]", {"jsonrpc": "2.0", "id": 2, "method": "ping"}])
    assert bad == {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
    assert wrong["error"]["code"] == -32600 and wrong["id"] is None
    assert pong["result"] == {}


def test_unknown_methods_tools_and_shapes_are_json_rpc_errors():
    replies = talk([{"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "knos_pay_me"}},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"arguments": {}}},
                    {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": ["knos_due"]}])
    assert [r["error"]["code"] for r in replies] == [-32601, -32602, -32602, -32602]
    assert [r["id"] for r in replies] == [1, 2, 3, 4] and "knos_pay_me" in replies[1]["error"]["message"]


def test_a_batch_from_an_older_client_is_answered_as_a_batch():
    (replies,) = talk([json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                   {"jsonrpc": "2.0", "method": "notifications/initialized"},
                                   {"jsonrpc": "2.0", "id": 2, "method": "ping"}])])
    assert [r["id"] for r in replies] == [1, 2]


def test_starting_the_server_asks_nothing_of_the_chain_or_github(monkeypatch):
    """No ledger is given, so one would be made on first use: it never is, and GitHub is never asked."""
    from knos import chain
    monkeypatch.setattr(chain, "ledger", lambda: (_ for _ in ()).throw(AssertionError("the chain was touched")))
    github = GitHub()
    replies = talk([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 3, "method": "server/discover"}], None, github)
    assert len(replies) == 3 and all("result" in r for r in replies) and github.asked == []


# ---- the tools ------------------------------------------------------------------------------------------------------


def test_knos_bounties_lists_open_work_largest_first_with_what_the_author_gets():
    ledger, github = world()
    got = call("knos_bounties", {}, ledger, github)["structuredContent"]
    assert [(b["repo"], b["issue"], b["amount_usdc"], b["net_usdc"]) for b in got["bounties"]] == [
        ("acme/gadgets", 3, "50.00", "48.75"), ("octo/widgets", 7, "20.00", "19.50"), (None, 1, "1.00", "0.95")]
    first, _second, unnamed = got["bounties"]              # the proven job and the one past its deadline are not work
    assert first == {"repo": "acme/gadgets", "issue": 3, "url": "https://github.com/acme/gadgets/issues/3",
                     "amount_usdc": "50.00", "net_usdc": "48.75",
                     "paid_when": "the funder's acceptance checks pass on a pull request",
                     "refunded_after": "2026-10-05T14:13:20Z", "job": str(pay.job_pda(GADGETS, 3)),
                     "title": "Retry the upload", "labels": ["bug", "good first issue"], "assigned": False}
    assert got["bounties"][1]["paid_when"] == "a maintainer merges the pull request that closes the issue"
    assert unnamed["repo"] is None and unnamed["url"] is None and unnamed["repo_id"] == GONE   # GitHub did not answer
    assert (unnamed["title"], unnamed["labels"], unnamed["assigned"]) == (None, None, None)
    assert got["open"] == 3 and got["cluster"] == "devnet" and got["note"] == "test USDC, no real value"
    for said in ("Fixes #<issue>", "No wallet or address is needed", "GitHub account", "knos claim <address>",
                 "https://drexthealpha.github.io/Knos/#claim"):
        assert said in got["how"]


def test_knos_bounties_can_be_held_to_one_repository_and_a_number():
    ledger, github = world()
    one = call("knos_bounties", {"repo": "octo/widgets"}, ledger, github)["structuredContent"]
    assert [(b["repo"], b["issue"]) for b in one["bounties"]] == [("octo/widgets", 7)] and one["open"] == 1
    top = call("knos_bounties", {"limit": 1}, ledger, github)["structuredContent"]
    assert [b["issue"] for b in top["bounties"]] == [3] and top["open"] == 3


def test_knos_bounties_says_what_each_issue_is_about():
    ledger, github = world()
    got = call("knos_bounties", {}, ledger, github)["structuredContent"]
    gadgets, widgets, gone = got["bounties"]
    assert (gadgets["title"], gadgets["labels"], gadgets["assigned"]) == ("Retry the upload", ["bug", "good first issue"], False)
    assert (widgets["title"], widgets["labels"], widgets["assigned"]) == ("Add a --json flag", [], True)   # none is not null
    assert (gone["title"], gone["labels"], gone["assigned"]) == (None, None, None)


def test_knos_bounties_asks_github_once_per_named_bounty_and_never_for_an_unnamed_one():
    ledger, github = world()
    call("knos_bounties", {}, ledger, github)
    assert sorted(p for p in github.asked if "/issues/" in p) == ["repos/acme/gadgets/issues/3", "repos/octo/widgets/issues/7"]
    assert f"repositories/{GONE}" in github.asked                       # it was asked who the repository is, and no more


def test_a_failed_issue_lookup_leaves_its_fields_null_and_the_bounty_listed():
    ledger, github = world()
    del github.pages["repos/acme/gadgets/issues/3"]                     # this one lookup fails; the other does not
    got = call("knos_bounties", {}, ledger, github)
    assert got["isError"] is False
    gadgets, widgets, _gone = got["structuredContent"]["bounties"]
    assert (gadgets["title"], gadgets["labels"], gadgets["assigned"]) == (None, None, None)
    assert (gadgets["repo"], gadgets["issue"], gadgets["amount_usdc"]) == ("acme/gadgets", 3, "50.00")   # nothing else lost
    assert widgets["title"] == "Add a --json flag"
    for odd in ({"title": "no labels key"}, {"title": None, "labels": [], "assignees": []},
                {"title": "t", "labels": [{"name": None}], "assignees": []}):   # answers that are not an issue
        github.pages["repos/acme/gadgets/issues/3"] = odd
        row = call("knos_bounties", {}, ledger, github)["structuredContent"]["bounties"][0]
        assert (row["title"], row["labels"], row["assigned"]) == (None, None, None)       # never the text "None"


def test_github_refusing_the_issue_lookups_does_not_fail_the_list():
    import urllib.error
    ledger, github = world()

    def get(path: str):
        if "/issues/" in path:
            raise urllib.error.HTTPError(f"https://api.github.com/{path}", 403, "rate limit", None, None)
        return github(path)

    got = call("knos_bounties", {}, ledger, get)
    assert got["isError"] is False
    rows = got["structuredContent"]["bounties"]
    assert [b["repo"] for b in rows] == ["acme/gadgets", "octo/widgets", None]
    assert all((b["title"], b["labels"], b["assigned"]) == (None, None, None) for b in rows)


def test_an_issue_with_an_assignee_in_either_field_is_assigned():
    ledger, github = world()
    github.pages["repos/acme/gadgets/issues/3"] = {"title": "t", "labels": [], "assignee": {"login": "mona"}}
    assert call("knos_bounties", {}, ledger, github)["structuredContent"]["bounties"][0]["assigned"] is True
    github.pages["repos/acme/gadgets/issues/3"] = {"title": "t", "labels": [], "assignees": [{"login": "mona"}]}
    assert call("knos_bounties", {}, ledger, github)["structuredContent"]["bounties"][0]["assigned"] is True


def test_knos_bounty_shows_every_job_on_an_issue_and_its_state():
    ledger, github = world()
    got = call("knos_bounty", {"issue": "octo/widgets#7"}, ledger, github)["structuredContent"]
    opened, proven = got["bounties"]
    assert (opened["state"], opened["mode"], opened["amount_usdc"], opened["refunded_after"]) == (
        "open", "merge", "20.00", "2026-10-05T14:13:20Z") and "author_id" not in opened
    assert (proven["state"], proven["author_id"], proven["released_in_s"], proven["amount_usdc"]) == ("proven", MONA, 1800, "5.00")
    assert got["issue"] == "octo/widgets#7" and got["said"] == "2 bounties in escrow for octo/widgets#7."
    none = call("knos_bounty", {"issue": "octo/widgets#8"}, ledger, github)
    assert none["isError"] is False and none["structuredContent"]["bounties"] == []
    assert none["structuredContent"]["said"].startswith("no bounty in escrow for octo/widgets#8")


def _pull(body: str, runs: list[dict], sha: str = "a" * 40) -> GitHub:
    return GitHub({"repos/octo/widgets/pulls/12": {"number": 12, "body": body, "head": {"sha": sha}},
                   f"repos/octo/widgets/commits/{sha}/check-runs?per_page=100&page=1": {"check_runs": runs}})


def _run(name: str, conclusion: str | None) -> dict:
    return {"name": name, "status": "completed" if conclusion else "in_progress", "conclusion": conclusion}


def test_knos_check_pr_holds_the_description_to_githubs_record():
    says = "Fixes #7. All tests pass and CI is green."
    got = call("knos_check_pr", {"pr": "octo/widgets#12"}, None, _pull(says, [_run("unit", "failure"), _run("lint", "success"),
                                                                          _run("e2e", "timed_out")]))["structuredContent"]
    assert got == {"pr": "octo/widgets#12", "head": "a" * 40, "claims": ["CI is green", "tests pass"], "verdict": "false",
                   "failed_checks": ["e2e", "unit"],
                   "said": "The description says CI is green and tests pass, but these checks failed at the head commit: e2e, unit."}

    def verdict(body: str, runs: list[dict], pr: str = "octo/widgets#12") -> tuple:
        out = call("knos_check_pr", {"pr": pr}, None, _pull(body, runs))["structuredContent"]
        return out["verdict"], out["claims"], out["failed_checks"]

    assert verdict("Fixes #7. Tests pass.", [_run("unit", "success")]) == ("true", ["tests pass"], [])
    assert verdict("Fixes #7. Tests pass.", [_run("unit", "success")], "https://github.com/octo/widgets/pull/12/files")[0] == "true"
    assert verdict("Fixes #7. Tests pass.", [_run("unit", "success"), _run("e2e", None)])[0] == "checks still running"
    assert verdict("Fixes #7. Tests pass.", [_run("unit", "failure"), _run("e2e", None)])[0] == "false"   # a failure is final
    assert verdict("Fixes #7. Refactors the parser.", [_run("unit", "failure")]) == ("no claim", [], [])
    assert verdict("Fixes #7. Tests pass.", []) == ("no checks", ["tests pass"], [])   # nothing recorded is not "true"
    assert verdict("Fixes #7. Tests pass.", [_run("knos / gate", "failure")])[0] == "no checks"   # Knos's own check is not evidence


def test_knos_check_pr_says_so_when_the_checks_cannot_be_read():
    github = GitHub({"repos/octo/widgets/pulls/12": {"number": 12, "body": "Tests pass.", "head": {"sha": "b" * 40}}})
    got = call("knos_check_pr", {"pr": "octo/widgets#12"}, None, github)
    assert got["isError"] is True and "could not be checked" in got["content"][0]["text"]


def test_knos_due_shows_what_waits_what_was_paid_and_how_to_claim():
    ledger, github = world()
    got = call("knos_due", {"login": "@mona"}, ledger, github)["structuredContent"]
    assert got["login"] == "mona" and got["user_id"] == MONA
    assert got["waiting"] == [{"mint": str(pay.faucet_mint()), "amount_usdc": "19.50"}] and got["waiting_usdc"] == "19.50"
    assert got["paid"] == {"pull_requests": 3, "repositories": 2, "total_usdc": "61.25"}
    assert "knos claim <address>" in got["how"] and "https://drexthealpha.github.io/Knos/#claim" in got["how"]
    github.pages["users/nobody"] = {"id": 5, "login": "nobody"}
    empty = call("knos_due", {"login": "nobody"}, ledger, github)["structuredContent"]
    assert empty["waiting"] == [] and empty["paid"]["pull_requests"] == 0 and empty["said"] == "Nothing is waiting for nobody."


def _sentence(result: dict) -> str:
    """A failed tool's whole answer: isError, one text block, one line, no traceback, no structured content."""
    assert result["isError"] is True and "structuredContent" not in result and len(result["content"]) == 1
    text = result["content"][0]["text"]
    assert result["content"][0]["type"] == "text" and "\n" not in text and "Traceback" not in text and text.endswith(".")
    return text


def test_a_tool_that_cannot_answer_says_so_in_one_sentence():
    ledger, github = world()
    assert _sentence(call("knos_due", {"login": "mona"}, Ledger(down=True), github)).startswith("Solana devnet did not answer")
    assert _sentence(call("knos_bounties", {}, Ledger(down=True), github)).startswith("Solana devnet did not answer")
    assert _sentence(call("knos_due", {"login": "stranger"}, ledger, github)).startswith("GitHub did not answer for users/stranger")
    assert _sentence(call("knos_bounty", {"issue": "octo/nothing#1"}, ledger, github)).startswith("GitHub did not answer")
    assert _sentence(call("knos_check_pr", {"pr": "octo/widgets#99"}, ledger, github)).startswith("GitHub did not answer")


def test_githubs_own_refusals_are_told_apart():
    import urllib.error

    def refusing(code: int):
        def get(path: str):
            raise urllib.error.HTTPError(f"https://api.github.com/{path}", code, "no", None, None)
        return get

    ledger, _github = world()
    assert _sentence(call("knos_due", {"login": "mona"}, ledger, refusing(404))) == "GitHub has nothing at users/mona."
    assert "set GH_TOKEN" in _sentence(call("knos_due", {"login": "mona"}, ledger, refusing(403)))
    got = call("knos_bounties", {}, ledger, refusing(403))              # the list is still worth having without names
    assert got["isError"] is False and [b["repo"] for b in got["structuredContent"]["bounties"]] == [None, None, None]


def test_a_bad_argument_is_a_sentence_and_nothing_is_asked():
    ledger, github = world()
    for name, arguments, word in (("knos_bounty", {}, "needs issue"),
                                  ("knos_bounty", {"issue": "widgets 7"}, "owner/repo#number"),
                                  ("knos_bounty", {"issue": 7}, "must be text"),
                                  ("knos_bounties", {"limit": 51}, "from 1 to 50"),
                                  ("knos_bounties", {"limit": True}, "from 1 to 50"),
                                  ("knos_bounties", {"repo": "../../users/mona"}, "owner/name"),
                                  ("knos_bounties", {"wallet": "x"}, "no argument named wallet"),
                                  ("knos_check_pr", {"pr": "https://example.com/octo/widgets/pull/1"}, "github.com URL"),
                                  ("knos_due", {"login": "mona/../../repos"}, "GitHub login")):
        assert word in _sentence(call(name, arguments, ledger, github)), (name, arguments)
    assert github.asked == []
    (reply,) = talk([{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "knos_due", "arguments": ["mona"]}}])
    assert "as an object" in _sentence(reply["result"])


def test_a_fault_inside_a_tool_is_a_sentence_too(capsys):
    ledger, github = world()
    github.pages["users/odd"] = {"id": "not a number"}      # an answer no one planned for
    assert _sentence(call("knos_due", {"login": "odd"}, ledger, github)) == "knos_due could not answer (ValueError)."
    logged = capsys.readouterr()
    assert logged.out == "" and logged.err.startswith("knos mcp: knos_due: ValueError")   # the cause goes to stderr


def test_the_command_writes_nothing_but_json_lines_to_stdout(monkeypatch, capsys):
    from knos.cli import main
    monkeypatch.setattr("sys.stdin", io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}) + "\n"
        + "oops\n" + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"))
    assert main(["mcp"]) == 0                               # stdin ended: a clean exit
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line).get("id") for line in lines] == [1, None, 2]


def test_a_name_from_a_model_cannot_reach_another_path_of_githubs_api_and_a_hostile_line_does_not_end_the_server():
    from knos import mcp
    for bad in ("../user#1", "o/..#1", "o/.#1", "-x/y#1", "o/" + "x" * 101 + "#1", "o/r/../../user#1"):
        assert not mcp._ISSUE.fullmatch(bad), bad
    assert mcp._ISSUE.fullmatch("octo/widgets#7") and mcp._ISSUE.fullmatch("a/b.c#2") and mcp._ISSUE.fullmatch("o/.github#3")
    out = io.StringIO()
    mcp.serve(io.StringIO("[" * 100_000 + "\n" + '{"jsonrpc":"2.0","id":1,"method":"ping"}\n'), out)
    first, second = (json.loads(x) for x in out.getvalue().splitlines())
    assert first["error"]["code"] == -32700 and second == {"jsonrpc": "2.0", "id": 1, "result": {}}
