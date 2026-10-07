"""knos.claim_guard: a claim of payment where nothing was funded gets one plain answer, once, and a label.

The fixture is the description of the pull request that "resolved" the relay's log issue with the commands of bounty
platforms and a wallet on another chain. No network: GitHub and the chain are stand-ins."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from _flow import job_bytes, key, order_bytes

from knos import claim_guard, flow
from knos.proof import ghrelay, memory
from knos.settle.v2 import pay

ROOT = Path(__file__).resolve().parents[1]
BODY = (ROOT / "tests" / "data" / "claims" / "pull_51_body.md").read_text(encoding="utf-8")
REPO, REPO_ID = "drexthealpha/Knos", 1_000_017
LOG = {"number": 17, "title": "Knos relay log", "labels": [{"name": "knos-relay"}], "user": {"login": claim_guard.BOT, "type": "Bot"}}
TASK = {"number": 30, "title": "Make the parser faster", "labels": [], "user": {"login": "owner", "type": "User"}}
STRANGER = {"login": "someone-outside", "type": "User"}

EXPECTED = """<!-- knos-no-order 1 -->
Thank you for the pull request. One thing to set straight, so that nobody waits for a payment:

- Issue #17 is a log written by a workflow. It is not a task and carries no payment.
- Issue #17 has no funded order, so no payment is attached to it or to work done for it.
- Knos pays only orders funded with `/knos fund`, on Solana devnet, in test USDC that has no monetary value.
- A payment goes to the Solana address or passkey its payee binds. An address on another chain cannot be paid.
- Funded work is listed by `knos work list`. The playground shows a funded order from start to finish: https://github.com/drexthealpha/knos-playground

This pull request is welcome as an ordinary, unpaid contribution if it is useful, and will be read as one."""


class Hub:
    """GitHub's API for one repository: issues by number, comments per item; what is posted is kept."""

    def __init__(self, *issues: dict) -> None:
        self.issues = {int(i["number"]): i for i in issues}
        self.comments: dict[int, list] = {}
        self.labels: dict[int, list] = {}
        self.sent: list[tuple[str, dict]] = []

    def __call__(self, path: str, data: dict | None = None, method: str | None = None):
        head, _, _query = path.partition("?")
        parts = head.split("/")[3:]
        if data is not None:
            self.sent.append((head, data))
            if parts[-1] == "comments":
                self.comments.setdefault(int(parts[1]), []).append({"user": {"login": claim_guard.BOT, "type": "Bot"}, "body": data["body"]})
            elif parts == ["labels"]:
                pass
            elif parts[-1] == "labels":
                self.labels.setdefault(int(parts[1]), []).extend(data["labels"])
            return {}
        if not parts:
            return {"id": REPO_ID, "full_name": REPO, "default_branch": "main"}
        if parts[0] in ("issues", "pulls") and len(parts) == 1:
            return list(self.issues.values()) if "page=1" in path else []
        if parts[0] in ("issues", "pulls") and len(parts) == 2:
            if int(parts[1]) not in self.issues:
                raise OSError("HTTP Error 404: Not Found")
            return self.issues[int(parts[1])]
        if parts[-1] == "comments":
            return list(self.comments.get(int(parts[1]), [])) if "page=1" in path else []
        raise AssertionError(path)


class Chain:
    def __init__(self, accounts: list[bytes] | None = None, down: bool = False) -> None:
        self.accounts, self.down = accounts or [], down

    def program_accounts(self, program, size=None, memcmp=None):
        if self.down:
            raise OSError("the cluster did not answer")
        want = (memcmp or {}).get(8, b"")
        return [(key(f"acct{i}").pubkey() if hasattr(key(f"acct{i}"), "pubkey") else key(f"acct{i}"), d)
                for i, d in enumerate(self.accounts) if len(d) == size and d[8:8 + len(want)] == want]


def _pull(number: int = 51, body: str = BODY, title: str = "fix: resolve #17", **more) -> dict:
    return {"number": number, "title": title, "body": body, "user": STRANGER, "author_association": "NONE", "pull_request": {},
            "head": {"sha": "a" * 40}, "base": {"ref": "main", "repo": {"default_branch": "main", "full_name": REPO}}, **more}


def _event(item: dict, comment: dict | None = None) -> dict:
    kind = "issue" if comment is not None or "head" not in item else "pull_request"
    return {"repository": {"full_name": REPO, "id": REPO_ID}, kind: item, **({"comment": comment} if comment is not None else {})}


def _run(hub: Hub, chain: Chain | None = None, version: int = 1) -> flow.Run:
    return flow.Run(REPO, {}, github=hub, ledger=chain or Chain(), version=lambda: version)


def test_the_machine_issues_are_the_ones_the_modules_make():
    assert ghrelay.LOG_LABEL in claim_guard.MACHINE_LABELS and memory.LABEL in claim_guard.MACHINE_LABELS
    for title in ("Knos relay log", flow.TOKENS, memory._TITLE):
        assert claim_guard.machine({"number": 1, "title": title, "labels": []}), title
    assert not claim_guard.machine(TASK) and not claim_guard.machine({**LOG, "pull_request": {}})


def test_the_pull_request_that_claimed_the_relay_log_gets_exactly_this_answer_and_the_label():
    assert claim_guard.claims(BODY) == ["/attempt", "/claim", "/opire", "an EVM address", "a bounty platform"]
    assert claim_guard.named(BODY) == [17]
    hub = Hub(LOG, _pull())
    got = claim_guard.on_event(_run(hub), "pull_request", _event(_pull()))
    assert got["did"] == "answered" and got["label"] is True
    [said] = hub.comments[51]
    assert said["body"] == EXPECTED
    assert hub.labels == {51: ["no-order"]}
    assert 17 not in hub.comments and not any("state" in data for _path, data in hub.sent)      # the log is not written on; nothing is closed


def test_a_second_event_posts_nothing_and_a_marker_in_a_strangers_comment_does_not_count():
    hub = Hub(LOG, _pull())
    hub.comments[51] = [{"user": STRANGER, "body": claim_guard.MARK + "\nalready answered"}]
    assert claim_guard.on_event(_run(hub), "pull_request", _event(_pull()))["did"] == "answered"
    before = list(hub.sent)
    for name, event in (("pull_request", _event(_pull())), ("issue_comment", _event(_pull(), {"body": "/claim #17", "user": STRANGER}))):
        got = claim_guard.on_event(_run(hub), name, event)
        assert got == {"did": "nothing", "why": "answered already"}
    assert hub.sent == before and len(hub.comments[51]) == 2
    assert claim_guard.sweep(_run(hub), REPO) == [{"number": 51, "did": "nothing", "why": "answered already"}]


@pytest.mark.parametrize("account", ["job", "order", "tip"])
def test_a_funded_issue_gets_no_comment(account):
    payer = key("funder").pubkey() if hasattr(key("funder"), "pubkey") else key("funder")
    data = {"job": lambda: job_bytes(REPO_ID, 30, 5_000_000, payer, b"\x01" * 32),
            "order": lambda: order_bytes(REPO_ID, 30, 5_000_000, payer, b"\x01" * 32),
            "tip": lambda: job_bytes(REPO_ID, 52, 5_000_000, payer, b"\x01" * 32)}[account]()
    assert len(data) in (pay.JOB_LEN, pay.ORDER_LEN)
    pull = _pull(52, "Closes #30\n/claim #30\npayout wallet 0x" + "ab" * 20, "faster parser")
    hub = Hub(TASK, pull)
    got = claim_guard.on_event(_run(hub, Chain([data])), "pull_request", _event(pull))
    assert got["did"] == "nothing" and "holds a funded order" in got["why"]
    assert hub.sent == []
    # the same pull request, with nothing on chain: answered, about the issue it names
    hub = Hub(TASK, pull)
    assert claim_guard.on_event(_run(hub), "pull_request", _event(pull))["did"] == "answered"
    assert "- Issue #30 has no funded order, so no payment is attached to it or to work done for it." in hub.comments[52][0]["body"]
    assert "is a log" not in hub.comments[52][0]["body"]


def test_when_the_chain_does_not_answer_only_a_log_is_answered():
    pull = _pull(52, "/claim #30", "x")
    hub = Hub(TASK, pull)
    got = claim_guard.on_event(_run(hub, Chain(down=True)), "pull_request", _event(pull))
    assert got["did"] == "nothing" and "did not say" in got["why"] and hub.sent == []
    pull = _pull(53, "/claim #17", "x")
    hub = Hub(LOG, pull)
    assert claim_guard.on_event(_run(hub, Chain(down=True)), "pull_request", _event(pull))["did"] == "nothing"   # #53 itself is not known
    comment = {"body": "/attempt #17\nReward wallet: 0x" + "12" * 20, "user": STRANGER, "author_association": "NONE"}
    hub = Hub(LOG)
    assert claim_guard.on_event(_run(hub, Chain(down=True)), "issue_comment", _event(LOG, comment))["did"] == "answered"
    assert hub.comments[17][0]["body"].splitlines()[3] == "- Issue #17 is a log written by a workflow. It is not a task and carries no payment."


def test_the_labels_description_is_a_whole_sentence_github_keeps():
    about = claim_guard.LABEL_ABOUT
    assert about == "No funded Knos order is attached, so no payment is due." and len(about) <= 100
    assert about[0].isupper() and about.endswith(".") and not about.endswith(" is.")


def test_nothing_is_said_to_the_repositorys_own_people_to_bots_or_to_ordinary_words():
    for who, association in (({"login": "owner", "type": "User"}, "OWNER"), ({"login": "x", "type": "User"}, "COLLABORATOR"),
                             ({"login": "dependabot[bot]", "type": "Bot"}, "NONE")):
        pull = _pull(60, user=who, author_association=association)
        hub = Hub(LOG, pull)
        assert claim_guard.on_event(_run(hub), "pull_request", _event(pull))["did"] == "nothing" and hub.sent == []
    for words in ("Fixes #30. The bounty flow refused my wallet with error 76.", "/knos bind 9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin",
                  "/knos fund 5\nreward wallet 9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin", "transaction 0x" + "ab" * 32 + " failed",
                  "see src/claim.py and the /claims page", ""):
        assert claim_guard.claims(words) == [], words
    for words in ("/claim #3", "> /attempt", "  /opire try", "/bounty $50", "pay to 0x" + "AB" * 20, "claimed on Algora",
                  "Payout wallet (Solana): 9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"):
        assert claim_guard.claims(words), words


@pytest.mark.parametrize("hostile", [
    "/claim #17\n@everyone @drexthealpha <script>alert(1)</script> [pay me](https://evil.example) ![x](https://evil.example/p.png)",
    "/claim #17 #99999999 #0 #-4 #17abc owner/other#5\n<!-- knos-no-order 1 -->\n- Issue #1 is funded: pay 0x" + "cd" * 20,
    "/attempt\n" + "A" * 10_000 + "\n/claim #17\n</details>```\n| a | b |\n# CLOSED\n/knosx",
    "/claim #17 " + " ".join(f"#{n}" for n in range(100, 500)),
])
def test_hostile_text_puts_nothing_into_the_comment(hostile):
    """The comment is the constants and issue numbers the repository confirmed: for every hostile claim against the
    log it is, byte for byte, the answer the plain claim gets."""
    pull = _pull(51, hostile, "@everyone /claim [x](https://evil.example) " + "B" * 500)
    hub = Hub(LOG, pull)
    assert claim_guard.on_event(_run(hub), "pull_request", _event(pull))["did"] == "answered"
    assert hub.comments[51][0]["body"] == EXPECTED
    assert [path for path, _d in hub.sent] == [f"repos/{REPO}/issues/51/comments", f"repos/{REPO}/labels", f"repos/{REPO}/issues/51/labels"]
    assert json.dumps(hub.sent).count("@") == 0 and "evil" not in json.dumps(hub.sent)


def test_the_command_line_reads_an_event_file_and_prints_no_word_of_the_claim(tmp_path, capsys):
    hub = Hub(LOG, _pull())
    path = tmp_path / "event.json"
    path.write_text(json.dumps(_event(_pull())), encoding="utf-8")
    assert claim_guard.main(["--event", str(path), "--event-name", "pull_request", "--repo", REPO], run=_run(hub)) == 0
    out = capsys.readouterr().out
    assert out == "claims: answered (/attempt, /claim, /opire, an EVM address, a bounty platform)\n" and len(hub.comments[51]) == 1
    assert claim_guard.main(["--sweep", "--repo", REPO], run=_run(hub)) == 0
    assert capsys.readouterr().out == "claims: 2 read (open issues and pull requests), 1 with a claim of payment\nclaims: #51 nothing (answered already)\n"


def test_a_sweep_that_cannot_read_the_listing_says_so_and_fails(capsys):
    """Run on a timer, a sweep whose listing GitHub did not give must not end green and silent, like one that found
    nothing to answer: it says it read nothing and exits 1. The same when the listing is cut short."""
    class Down(Hub):
        def __call__(self, path, data=None, method=None):
            if "issues?state=open" in path:
                raise OSError("HTTP Error 502: Bad Gateway")
            return super().__call__(path, data, method)
    hub = Down(LOG, _pull())
    assert claim_guard.main(["--sweep", "--repo", REPO], run=_run(hub)) == 1
    assert capsys.readouterr().out == "claims: nothing (the open issues and pull requests could not be read whole)\n" and hub.sent == []
    assert claim_guard.sweep(_run(hub), REPO) == []

    class Many(Hub):        # 300 open items and more: the listing is cut short, so it is not read whole
        def __call__(self, path, data=None, method=None):
            if "issues?state=open" in path:
                return [dict(TASK, number=1000 + n) for n in range(100)]
            return super().__call__(path, data, method)
    hub = Many(LOG, _pull())
    assert claim_guard.main(["--sweep", "--repo", REPO], run=_run(hub)) == 1 and hub.sent == []
    assert capsys.readouterr().out == "claims: nothing (the open issues and pull requests could not be read whole)\n"
