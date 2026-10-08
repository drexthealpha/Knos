"""The public worker (knos.proof.ghrelay) against a fake GitHub: what it reads and how cheaply, where a token goes,
what travels with it, what it logs, and how a caller finds its verdict. One pass runs end to end on LiteSVM."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import urllib.error

import pytest
from _pay21 import each_build, pay21_build  # noqa: F401 - the fixtures `build` and `pay21`: a test that takes `build` runs on knos_pay 2.2 and on the live 2.1
from solders.keypair import Keypair

from knos.proof import ghrelay
from knos.settle import relay as relay1
from knos.settle.v2 import relay as relay2

HOME, ROTATE = ghrelay.HOME_REPO, ghrelay.ROTATE_REPO
TERMS = b'{"accept":"","checks":[{"app":15368,"name":"test"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":[],"reserve":7,"v":1}'
BALANCE = "7Np41oeYqPefeNQEHSv1UDhYrehxin3NStELsSKCT4K2"


def jwt(aud: str, **claims) -> str:
    """A token's shape with these claims (unsigned: the relays are faked wherever this is used)."""
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()  # noqa: E731
    return f"{enc({'alg': 'RS256', 'kid': 'k1'})}.{enc({'aud': aud, 'iat': 1000, **claims})}.c2ln"


def fund_aud(n: int) -> str:
    return f"knos2:fund:{n}:5000000:0:{hashlib.sha256(TERMS).hexdigest()}:1209600:{BALANCE}"


class Answer:
    def __init__(self, body, etag: str):
        self.body, self.headers = json.dumps(body).encode(), {"ETag": etag}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self.body


class GitHub:
    """api.github.com, faked where the worker opens it. Every answer has an ETag; a request that names the current
    one gets 304. `asked` is every request: (method, path, status)."""

    def __init__(self):
        self.comments: dict[str, list[dict]] = {}       # repository -> its issue comments, oldest first
        self.issues: dict[str, list[dict]] = {}
        self.search: list[str] = []                     # repositories the comment search finds
        self.repos: dict[str, list[dict]] = {}          # owner -> repositories
        self.asked: list[tuple[str, str, int]] = []
        self.down: set[str] = set()                     # paths GitHub answers 502 for
        self.runs: dict[str, dict] = {}                 # "owner/repo/<run id>" -> the workflow run, as the API gives it
        self.ids: dict[int, str] = {}                   # repository id -> its name
        self._id = 0

    def comment(self, repo: str, number: int, body: str, who: str = ghrelay.LOG_BOT, at: float | None = None) -> None:
        self._id += 1
        self.comments.setdefault(repo, []).append({"id": self._id, "body": body, "user": {"login": who},
                                                   "issue_url": f"https://api.github.com/repos/{repo}/issues/{number}",
                                                   "created_at": ghrelay._stamp(time.time() if at is None else at)})

    def open(self, req, timeout=None):
        path, method = req.full_url[len(ghrelay.API):], req.get_method()
        status, body = self._route(method, path, json.loads(req.data) if req.data else None)
        etag = '"' + hashlib.sha256(json.dumps(body).encode()).hexdigest()[:16] + '"'
        if method == "GET" and status == 200 and req.get_header("If-none-match") == etag:
            status = 304
        self.asked.append((method, path, status))
        if status != 200:
            raise urllib.error.HTTPError(req.full_url, status, "no", {}, None)
        return Answer(body, etag)

    def _route(self, method: str, path: str, data):
        where, _, query = path.partition("?")
        q = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        if where in self.down:
            return 502, None
        if where == "search/issues":
            return 200, {"items": [{"repository_url": f"https://api.github.com/repos/{r}"} for r in self.search]}
        m = re.fullmatch(r"users/([^/]+)/repos", where)
        if m:
            return 200, self.repos.get(m.group(1), [])
        m = re.fullmatch(r"repos/([^/]+/[^/]+)/issues/comments", where)
        if m:       # the repository's comments, newest first, a page at a time
            rows = list(reversed(self.comments.get(m.group(1), [])))
            size, page = int(q.get("per_page", 30)), int(q.get("page", 1))
            return 200, rows[(page - 1) * size:page * size]
        m = re.fullmatch(r"repos/([^/]+/[^/]+)/issues/(\d+)/comments", where)
        if m and method == "POST":
            self.comment(m.group(1), int(m.group(2)), data["body"])
            return 200, {"id": self._id}
        if m:
            rows = [c for c in self.comments.get(m.group(1), []) if c["issue_url"].endswith(f"/issues/{m.group(2)}") and c["created_at"] >= q.get("since", "")]
            size, page = int(q.get("per_page", 30)), int(q.get("page", 1))
            return 200, rows[(page - 1) * size:page * size]
        m = re.fullmatch(r"repos/([^/]+/[^/]+)/issues", where)
        if m and method == "POST":
            issue = {"number": len(self.issues.get(m.group(1), [])) + 1, "state": "open", "labels": data.get("labels", [])}
            self.issues.setdefault(m.group(1), []).append(issue)
            return 200, issue
        if m:
            return 200, [i for i in self.issues.get(m.group(1), []) if q.get("labels") in i["labels"] and i["state"] == "open"][:1]
        if re.fullmatch(r"repos/([^/]+/[^/]+)/labels", where):
            return 200, {}
        m = re.fullmatch(r"repositories/(\d+)", where)
        if m and int(m.group(1)) in self.ids:
            return 200, {"id": int(m.group(1)), "full_name": self.ids[int(m.group(1))]}
        m = re.fullmatch(r"repos/([^/]+/[^/]+)/actions/runs/(\d+)", where)
        if m and f"{m.group(1)}/{m.group(2)}" in self.runs:
            return 200, self.runs[f"{m.group(1)}/{m.group(2)}"]
        return 404, None

    def log(self) -> list[str]:
        """The worker's public log: the bodies of the comments on its log issue, in order."""
        return [c["body"] for c in self.comments.get(HOME, [])]

    def gets(self, since: int = 0) -> list[tuple[str, int]]:
        return [(path.split("?")[0], status) for method, path, status in self.asked[since:] if method == "GET"]


class Relays:
    """What the worker hands to a relay, kept: `relay_one` in its place, answering what the test says."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.answers: dict[str, dict] = {}              # token id -> the result (default: a fund that worked)

    def __call__(self, ledger, payer, kind, jwt, terms=None):
        self.calls.append((kind, jwt, terms))
        r = dict(self.answers.get(ghrelay.token_id(jwt), {"ok": True, "kind": ghrelay.RELAY_KIND.get(kind, kind), "sigs": ["s1", "s2"], "note": "done"}))
        return r


class Ledger:
    """A chain with nothing on it: the worker's rounds of what needs no token find nothing to send."""

    def now(self) -> int:
        return 1_790_000_000

    def program_accounts(self, program, size=None, memcmp=None):
        return []

    def account(self, address):
        return None


@pytest.fixture
def world(monkeypatch, tmp_path):
    """A fake GitHub behind the worker's reader, a state file of its own, and the relays faked."""
    gh, relays = GitHub(), Relays()
    monkeypatch.setattr(ghrelay, "_HUB", ghrelay.Hub(gh.open))
    monkeypatch.setattr(ghrelay, "_LOG", {})
    monkeypatch.setattr(ghrelay, "_state_path", lambda: tmp_path / "ghrelay.json")
    monkeypatch.setattr(ghrelay, "relay_one", relays)
    monkeypatch.delenv("KNOS_RELAY_REPOS", raising=False)
    gh.issues[HOME] = [{"number": 1, "state": "open", "labels": [ghrelay.LOG_LABEL]}]
    return gh, relays, tmp_path / "ghrelay.json"


PAYER = Keypair()


def passes(now: float, **kw) -> list[str]:
    return ghrelay.once(Ledger(), PAYER, now=now, **kw)


# -- reading GitHub: conditional requests for what is known, a search for what is not ----------------------------------------
def test_known_repositories_are_read_with_conditional_requests_and_new_ones_searched_for_every_30_seconds(world, monkeypatch):
    gh, relays, state = world
    t0 = time.time()
    first = jwt(fund_aud(7))
    gh.comment("octo/widgets", 7, ghrelay.token_comment("fund", first, TERMS))
    gh.search = ["octo/widgets"]
    assert len(passes(t0)) == 1 and [c[1] for c in relays.calls] == [first]
    # the search found the repository; its comments, the rotate repository's and the worker's own were read in full
    assert sorted(gh.gets()) == sorted([("search/issues", 200), (f"users/{HOME.split('/')[0]}/repos", 200), (f"repos/{HOME}/issues/comments", 200),
                                        (f"repos/{ROTATE}/issues/comments", 200), ("repos/octo/widgets/issues/comments", 200), (f"repos/{HOME}/issues", 200)])
    saved = json.loads(state.read_text())
    assert saved["repos"] == {"octo/widgets": t0} and saved["searched"] == t0 and saved["owners"] == ["octo"]
    # three seconds later nothing is new: no search, and a 304 for each repository, which GitHub does not count
    n = len(gh.asked)
    assert passes(t0 + 3) == [] and len(relays.calls) == 1
    assert sorted(gh.gets(n)) == sorted([(f"repos/{HOME}/issues/comments", 200), (f"repos/{ROTATE}/issues/comments", 304), ("repos/octo/widgets/issues/comments", 304)])
    n = len(gh.asked)        # (the worker's own repository had changed: its log gained a line)
    assert passes(t0 + 6) == [] and {status for _path, status in gh.gets(n)} == {304} and len(gh.gets(n)) == 3
    # a new comment there: that repository alone is read again, and only the new token is carried
    second = jwt(fund_aud(8), iat=1003)
    gh.comment("octo/widgets", 8, ghrelay.token_comment("fund", second, TERMS))
    n = len(gh.asked)
    assert len(passes(t0 + 9)) == 1 and [c[1] for c in relays.calls] == [first, second]
    assert ("repos/octo/widgets/issues/comments", 200) in gh.gets(n) and (f"repos/{ROTATE}/issues/comments", 304) in gh.gets(n)
    # half a minute after the last search the next one runs, and finds a repository nobody knew
    gh.comment("new/place", 1, ghrelay.token_comment("proof", jwt("knos2:pay:1:1:9:" + "a" * 40 + ":" + "0" * 64 + ":0:-")))
    gh.search.append("new/place")
    n = len(gh.asked)
    assert len(passes(t0 + 29)) == 0 and ("search/issues", 304) not in gh.gets(n) and ("search/issues", 200) not in gh.gets(n)
    assert len(passes(t0 + 30)) == 1 and ("search/issues", 200) in gh.gets(n) and relays.calls[-1][0] == "proof"
    assert set(json.loads(state.read_text())["repos"]) == {"octo/widgets", "new/place"}
    # a worker that starts afresh knows them from its state file before it has searched; what it has carried, it does not carry again
    monkeypatch.setattr(ghrelay, "_HUB", ghrelay.Hub(gh.open))
    n = len(gh.asked)
    assert passes(t0 + 40) == [] and len(relays.calls) == 3
    assert {path for path, _s in gh.gets(n)} == {f"repos/{r}/issues/comments" for r in ("octo/widgets", "new/place", HOME, ROTATE)}
    # two days after a repository's last token it is no longer read on every pass (the search finds it when it posts again)
    gh.search = []
    n = len(gh.asked)
    passes(t0 + 41 + ghrelay.KNOWN_FOR)
    assert not [p for p, _s in gh.gets(n) if "octo/widgets" in p] and json.loads(state.read_text())["repos"] == {}


def test_a_repository_github_does_not_answer_for_is_asked_again_and_a_busy_one_is_read_to_the_horizon(world):
    gh, relays, _state = world
    t0 = time.time()
    gh.search = ["octo/widgets"]
    gh.comment("octo/widgets", 1, ghrelay.token_comment("fund", jwt(fund_aud(1), iat=900)), who="someone", at=t0 - 2 * ghrelay.HORIZON)
    for i in range(130):                                        # more comments in the last hour than one page holds
        gh.comment("octo/widgets", i + 1, "talk" if i != 3 else ghrelay.token_comment("fund", jwt(fund_aud(4)), TERMS), who="someone", at=t0 - 600 + i)
    gh.down.add("repos/octo/widgets/issues/comments")
    assert passes(t0) == [] and relays.calls == []
    gh.down.clear()
    assert len(passes(t0 + 31)) == 1 and len(relays.calls) == 1  # the second page held it; the token of two hours ago is past carrying
    assert [p for m, p, _s in gh.asked if "octo/widgets" in p and "page=2" in p]


def test_past_fifteen_known_repositories_the_newest_are_read_every_pass_and_the_others_in_turn(world):
    gh, relays, state = world
    t0 = time.time()
    known = {f"o/r{i:02}": t0 - 60 * i for i in range(30)}          # r00 had a token just now, r29 half an hour ago
    state.write_text(json.dumps({"repos": known, "searched": t0}))
    read = lambda n: {path.split("/issues/")[0][len("repos/"):] for path, _s in gh.gets(n)} - {HOME, ROTATE}  # noqa: E731
    seen: list[set] = []
    for i in range(3):
        n = len(gh.asked)
        assert passes(t0 + 3 * i) == []
        seen.append(read(n))
    newest = {f"o/r{i:02}" for i in range(15)}
    assert all(newest < got and len(got) == 20 for got in seen)      # fifteen every time, and five of the rest
    assert set().union(*seen) == set(known)                          # in three passes every one of them was read
    assert len(gh.gets()) == 3 * 22                                  # with the two always read: 22 requests a pass, however many are known


def test_repositories_with_money_waiting_on_chain_are_read_with_no_search(world):
    """A pay token is found by reading the repositories the chain says have an open job or order, each pass: GitHub's
    search (late, rate-limited, or down) is not needed for the proof of a funded issue."""
    from knos.settle.v2 import pay
    gh, relays, state = world

    class Funded(Ledger):
        asked = 0

        def program_accounts(self, program, size=None, memcmp=None):
            job = bytes([1]) + bytes(7) + (4242).to_bytes(8, "little") + bytes(pay.JOB_LEN - 16)
            done = bytes([3]) + bytes(7) + (99).to_bytes(8, "little") + bytes(pay.JOB_LEN - 16)             # held: no proof is awaited
            order = bytes([2, 1]) + bytes(6) + (5151).to_bytes(8, "little") + bytes(pay.ORDER_LEN - 16)
            private = bytearray(bytes([2, 1]) + bytes(pay.ORDER_LEN - 2))
            private[184:192] = (6161).to_bytes(8, "little")                                               # no repository on chain: its judge's stands in
            if program != pay.PAY_ID:
                return []
            self.asked += 1
            rows = [(Keypair().pubkey(), d) for d in (job, done, order, bytes(private))]
            return [(a, d) for a, d in rows if len(d) == size and all(d[o:o + len(b)] == b for o, b in (memcmp or {}).items())]
    ledger = Funded()
    assert relay2.open_repositories(ledger) == {4242, 5151, 6161}
    t0 = time.time()
    gh.ids = {4242: "quiet/jobs", 5151: "quiet/orders"}          # 6161 is private: GitHub names it to nobody
    gh.down.add("search/issues")                                # and the search is down
    proof = jwt("knos2:pay:4242:7:9:" + "a" * 40 + ":" + "0" * 64 + ":0:-")
    gh.comment("quiet/jobs", 12, ghrelay.token_comment("proof", proof))
    assert len(ghrelay.once(ledger, PAYER, now=t0, crank=False)) == 1 and [c[:2] for c in relays.calls] == [("proof", proof)]
    saved = json.loads(state.read_text())
    assert saved["chain"] == {"at": t0, "ids": [4242, 5151, 6161]} and saved["names"] == {"4242": "quiet/jobs", "5151": "quiet/orders"}
    # the next passes read those repositories again (a 304 each while nothing is new) without asking the chain or their names again
    asked, n = ledger.asked, len(gh.asked)
    assert ghrelay.once(ledger, PAYER, now=t0 + 3, crank=False) == [] and ledger.asked == asked
    got = gh.gets(n)
    assert ("repos/quiet/jobs/issues/comments", 304) in got and ("repos/quiet/orders/issues/comments", 304) in got and not [p for p, _s in got if p.startswith("repositories/")]
    # a minute on the chain is read again; a job that is gone is no longer watched (it stays known for two days, as any repository a token came from)
    gh.ids.pop(5151)
    ledger.program_accounts = lambda program, size=None, memcmp=None: []
    assert ghrelay.once(ledger, PAYER, now=t0 + 61, crank=False) == []
    saved = json.loads(state.read_text())
    assert saved["chain"]["ids"] == [] and saved["names"] == {} and set(saved["repos"]) == {"quiet/jobs"}


# -- what a comment carries ----------------------------------------------------------------------------------------------------
def test_a_fund_tokens_terms_travel_with_it(world):
    gh, relays, _state = world
    t0 = time.time()
    fund, proof = jwt(fund_aud(7)), jwt("knos2:pay:1:7:9:" + "a" * 40 + ":" + "0" * 64 + ":0:-", iat=1001)
    body = ghrelay.token_comment("fund", fund, TERMS)
    assert body.splitlines()[:2] == [f"knos-fund: {fund}", "knos-terms: " + TERMS.decode()] and ghrelay.MARK in body
    comments = [{"body": body.replace("\n", "\r\n"), "issue_url": "https://api.github.com/repos/o/r/issues/7", "user": {"login": "github-actions[bot]"},
                 "created_at": "2026-10-03T10:00:05Z"},
                {"body": f"knos-proof: {proof}\nknos-terms: {TERMS.decode()}", "issue_url": "u/9", "user": None}]
    got = ghrelay.tokens(comments)
    assert got == [("fund", 7, fund, "github-actions[bot]"), ("proof", 9, proof, "")]       # what `found` always gave: four things
    assert (got[0].terms, got[0].created, got[1].terms, got[1].created) == (TERMS, 1791021605.0, None, None)      # and what goes with them
    assert ghrelay.tokens(comments, "2026-10-03T10:00:06Z") == [("proof", 9, proof, "")]     # a comment older than the horizon is past
    for kind in ("fund", "proof", "bind", "key", "verify", "veto", "claim"):
        assert ghrelay.tokens([{"body": ghrelay.token_comment(kind, fund), "issue_url": "u/1", "user": {"login": "a"}}]) == [(kind, 1, fund, "a")]
    assert ghrelay.tokens([{"body": "knos-terms: {}\n\nno token here", "issue_url": "u/1", "user": {"login": "a"}}]) == []
    # through a pass: a workflow posts its tokens (with its own GitHub token), the relay is handed the terms with the
    # fund token and nothing with the proof
    gh.search = ["o/r"]
    posted: list[tuple] = []
    assert ghrelay.post_token("o/r", 7, "fund", fund, TERMS) == ghrelay.token_id(fund)
    assert ghrelay.post_token("o/r", 9, "proof", proof, github=lambda path, data: posted.append((path, data)) or gh.comment("o/r", 9, data["body"])) == ghrelay.token_id(proof)
    assert posted == [("repos/o/r/issues/9/comments", {"body": ghrelay.token_comment("proof", proof)})] and gh.comments["o/r"][0]["body"] == body
    assert len(passes(t0)) == 2 and relays.calls == [("fund", fund, TERMS), ("proof", proof, None)]


def test_a_copy_of_a_token_posted_another_way_neither_uses_it_up_nor_speaks_for_it(world):
    """A token is public once it is posted, and anyone can post it again: under another marker, with other terms or
    none, in a repository of their own. Whatever is read first, the token is carried once, from the comment that
    posts it rightly, and the only log line that names it is its own verdict."""
    gh, relays, _state = world
    t0 = time.time()
    fund, proof = jwt(fund_aud(7)), jwt("knos2:pay:1:7:9:" + "a" * 40 + ":" + "0" * 64 + ":0:-", iat=1001)
    gh.search = ["a/copies", "octo/widgets"]                    # the copies are in a repository that is read first
    gh.comment("a/copies", 1, ghrelay.token_comment("fund", fund, b'{"v":2}'))
    gh.comment("a/copies", 1, f"knos-fund: {fund}")
    gh.comment("a/copies", 1, ghrelay.token_comment("proof", fund))
    gh.comment("a/copies", 1, ghrelay.token_comment("verify", fund))
    gh.comment("a/copies", 1, ghrelay.token_comment("bind", proof))
    gh.comment("octo/widgets", 7, ghrelay.token_comment("fund", fund, TERMS))
    gh.comment("octo/widgets", 9, ghrelay.token_comment("proof", proof))
    gh.comment("b/echo", 3, ghrelay.token_comment("fund", fund, TERMS))      # and one copy is exact: the same token, posted the same way
    gh.search.append("b/echo")
    lines = passes(t0)
    assert relays.calls == [("fund", fund, TERMS), ("proof", proof, None)]
    named = [ln for ln in lines if f" {ghrelay.token_id(fund)} " in ln or f" {ghrelay.token_id(proof)} " in ln]
    # (the exact copy was read before the original: the token did what it says all the same, and its one verdict is the same)
    assert [ln.split()[1:5] for ln in named] == [["fund", "b/echo#3", ghrelay.token_id(fund), "ok"], ["proof", "octo/widgets#9", ghrelay.token_id(proof), "ok"]]
    passed = sorted(ln.split(" - fail ")[1] for ln in lines if " - fail " in ln)
    short = ghrelay.token_id(fund)[:8]
    assert passed == sorted([f"this comment cannot carry its token ({short}...): its `knos-terms:` line is missing, or is not the terms the token names"] * 2 + [
        f"this comment cannot carry its token ({short}...): posted as knos-proof, but its audience is a fund token's",
        f"this comment cannot carry its token ({short}...): it is a Knos fund token, which is carried under its own marker",
        f"this comment cannot carry its token ({ghrelay.token_id(proof)[:8]}...): posted as knos-bind, but its audience is a pay token's"]) and len(lines) == 7
    assert ghrelay.wait_for(ghrelay.token_id(fund), HOME, 1, every=0) == named[0]       # whoever waits for the token reads its own verdict
    assert passes(t0 + 3) == []                                  # and each comment was dealt with once
    # the first deployment's tokens need no terms line, and a token of nobody's audience may be verified alone
    assert ghrelay.misposted("fund", jwt("knos:fund:3:1:0:" + "0" * 64 + ":1209600:0")) is None and ghrelay.misposted("verify", jwt("sts.amazonaws.com")) is None
    assert ghrelay.misposted("fund", jwt("sts.amazonaws.com")) is None       # (the relay itself says what that is)


# -- where a token goes -------------------------------------------------------------------------------------------------------
def test_a_token_goes_to_the_deployment_its_audience_names(monkeypatch):
    went: list[tuple] = []
    answer = lambda kind: {"ok": True, "kind": kind, "sigs": ["s"], "key": "K", "added": True, "vetoed": ["J"],  # noqa: E731
                           "claimed": [], "address": "A", "account": "T", "payer": "P", "exp": 0, "refreshed": False, "user_id": 5, "wallet": "W", "settled": [],
                           "job": "J", "issue": 7, "amount": 5_000_000, "mode": 0, "faucet": True, "balance": BALANCE, "deadline": 0}
    monkeypatch.setattr(relay1, "submit", lambda ledger, payer, jwt: went.append(("first", jwt)) or answer(relay1.kind_of(ghrelay.audience(jwt))))
    monkeypatch.setattr(relay2, "submit", lambda ledger, payer, jwt, terms=None: went.append(("second", jwt, terms)) or
                        ({"ok": False, "kind": None, "why": "not an audience of the second deployment"} if relay2.kind_of(ghrelay.audience(jwt)) is None
                         else answer(relay2.kind_of(ghrelay.audience(jwt)))))
    monkeypatch.setattr(relay2, "verify_only", lambda ledger, payer, jwt: went.append(("verify", jwt)) or answer("verify"))
    one = lambda kind, token, terms=None: ghrelay.relay_one("ledger", "payer", kind, token, terms=terms)  # noqa: E731
    new, old, key = jwt("knos2:bind:" + BALANCE), jwt("knos:veto:5:7"), jwt("knos-oidc:key:0:" + "ab" * 32)
    assert one("bind", new)["ok"] and went == [("second", new, None)]
    assert one("veto", old)["ok"] and went[-1] == ("first", old)
    assert one("claim", jwt("knos:claim:" + BALANCE))["ok"] and went[-1][0] == "first"
    assert one("key", key)["note"].startswith("Key K registered with the second verifier") and went[-1] == ("second", key, None)      # which hands it to the first too
    assert one("verify", jwt("sts.amazonaws.com"))["note"].startswith("Verified. Account T") and went[-1][0] == "verify"
    assert one("fund", jwt(fund_aud(7)), TERMS)["ok"] and went[-1][2] == TERMS      # a fund token's terms go with it
    # a comment that cannot carry its token is refused before anything is sent: a marker the audience does not fit, a
    # fund token without the terms it names, a Knos token under the verify marker
    n = len(went)
    assert one("proof", new) == {"ok": False, "kind": None, "why": "posted as knos-proof, but its audience is a bind token's"}
    assert one("bind", jwt("knos:claim:" + BALANCE))["why"] == "posted as knos-bind, but its audience is a claim token's"
    assert one("fund", key)["why"] == "posted as knos-fund, but its audience is a key token's"
    assert one("fund", jwt(fund_aud(7)))["why"] == one("fund", jwt(fund_aud(7)), b"{}")["why"] == "its `knos-terms:` line is missing, or is not the terms the token names"
    assert one("verify", new)["why"] == "it is a Knos bind token, which is carried under its own marker" and len(went) == n
    # an audience that is nobody's, and something that is no token: the second relay says so
    assert one("fund", jwt("sts.amazonaws.com")) == {"ok": False, "kind": None, "why": "not an audience of the second deployment"}
    assert not one("fund", "eyJ.x.y")["ok"] and went[-1] == ("second", "eyJ.x.y", None)


def test_what_the_second_deployments_results_say_in_words():
    fund = {"ok": True, "kind": "fund", "sigs": ["a"], "job": "J", "repo_id": 5, "issue": 3, "amount": 5_000_000, "mode": 0, "faucet": True,
            "balance": "B", "deadline": 1_791_209_600}
    assert ghrelay.note(fund) == ("5.00 test USDC is in escrow for issue #3, paid when the pull request that closes this issue is merged and meets "
                                  "the bounty's terms. Unpaid by 2026-10-05 14:13 UTC, it goes back to its funder. Job J.")
    assert ghrelay.note({**fund, "faucet": False, "mode": 1}).startswith("5.00 from balance B is in escrow for issue #3, paid when the issue's acceptance checks pass")
    entry = {"job": "J", "amount": 5_000_000, "fee": 125_000, "mint": "M", "to": "W", "held_until": None}
    paid = {"ok": True, "kind": "pay", "sigs": ["a"], "repo_id": 5, "issue": 3, "payee_id": 42, "head": "a" * 40, "paid": [entry, entry]}
    assert ghrelay.note(paid) == "9.75 was paid to W for issue #3 (GitHub user id 42)."
    from knos.settle.v2 import pay                              # the faucet's mint and Circle's devnet mint are test USDC, and called that
    assert ghrelay.note({**paid, "paid": [{**entry, "mint": str(pay.faucet_mint())}, {**entry, "mint": str(pay.USDC_DEVNET)}]}).startswith("9.75 test USDC was paid to W")
    held = ghrelay.note({**paid, "paid": [{**entry, "to": None, "held_until": 1_805_552_000}]})
    assert held.startswith("4.88 is held for GitHub user id 42 for issue #3 until 2027-03-20 14:13 UTC. It is sent once they name a wallet: `knos claim <their Solana address>`")
    bound = {"ok": True, "kind": "bind", "sigs": ["a"], "user_id": 42, "wallet": "W", "settled": []}
    assert ghrelay.note(bound) == "GitHub user id 42 is now paid at W."
    assert ghrelay.note({**bound, "settled": [{"job": "J", "amount": 5_000_000, "fee": 125_000, "mint": "M"}]}).endswith(" 1 held payment, 4.88 in all, went there.")
    key = {"ok": True, "kind": "key", "sigs": [], "key": "K", "added": False, "refreshed": True, "first": {"ok": True, "added": False}}
    assert ghrelay.note(key) == "Key K refreshed: the second verifier keeps it 30 days from now."
    assert ghrelay.note({**key, "refreshed": False}) == "Key K already known to the second verifier."
    assert ghrelay.note({**key, "refreshed": False, "why": "no", "first": {"ok": True, "added": True}}) == "Key K not taken by the second verifier (no). The first deployment added it."
    assert ghrelay.note({"ok": True, "kind": "key", "sigs": [], "key": "K", "added": True}) == "Key K added."      # the first deployment's own result, as ever


# -- the verify-only limit -----------------------------------------------------------------------------------------------------
def test_an_orders_tokens_travel_under_their_own_markers_and_an_issuers_url_beside_its_key_token(world):
    """What flow and attest post for a work order (take, cancel, revert, rule), an organisation's claim, and the rotate
    workflow's token for a key of any issuer, whose comment starts with the issuer's URL."""
    gh, relays, _state = world
    t0, order, url = time.time(), BALANCE, "https://gitlab.example.com"
    posted = [("take", jwt(f"knos3:take:{order}:42:7"), None), ("cancel", jwt(f"knos3:cancel:{order}", iat=1001), None),
              ("revert", jwt(f"knos3:revert:{order}:{'a' * 40}", iat=1002), None), ("rule", jwt(f"knos3:rule:{order}:42.10000.-", iat=1003), None),
              ("bind", jwt(f"knos3:bind:{BALANCE}", iat=1004), None),
              ("key", jwt(f"knos-oidc:ikey:{hashlib.sha256(url.encode()).hexdigest()}:{'ab' * 32}", iat=1005), url.encode())]
    gh.search = ["octo/widgets"]
    for n, (marker, token, beside) in enumerate(posted, 1):
        gh.comment("octo/widgets", n, ghrelay.token_comment(marker, token, beside))
    assert ghrelay.token_comment("key", "eyJ.a.b", url).startswith(f"knos-issuer: {url}\nknos-key: eyJ.a.b\n")
    lines = passes(t0)
    assert relays.calls == posted and [ln.split()[1] for ln in lines] == [m for m, _t, _b in posted] and all(" ok " in ln for ln in lines), lines
    # a copy under another marker, or with another issuer's URL beside it (or none), says nothing about the token
    wrong = {("take", posted[1][1], None): "posted as knos-take, but its audience is a cancel token's",
             ("proof", posted[3][1], None): "posted as knos-proof, but its audience is a rule token's",
             ("key", posted[5][1], None): "its `knos-issuer:` line is missing, or is not the issuer the token names",
             ("key", posted[5][1], b"https://evil.example.com"): "its `knos-issuer:` line is missing, or is not the issuer the token names"}
    assert {k: ghrelay.misposted(*k) for k in wrong} == wrong and all(ghrelay.misposted(*x) is None for x in posted)
    # a work order's fund token names its terms as a job's does: the `knos-terms:` line must be those terms
    fund3 = jwt(f"knos3:fund:7:5000000:0:{hashlib.sha256(TERMS).hexdigest()}:1209600:{BALANCE}:0:{'00' * 48}")
    assert ghrelay.misposted("fund", fund3, TERMS) is None
    assert ghrelay.misposted("fund", fund3) == ghrelay.misposted("fund", fund3, b"{}") == "its `knos-terms:` line is missing, or is not the terms the token names"


def test_what_a_work_orders_results_say_in_words():
    base = {"ok": True, "sigs": ["a"], "order": "O", "repo_id": 5, "issue": 3}
    paid = [{"id": 42, "payee_id": 42, "amount": 8_000_000, "to": "W", "held_until": None}]
    assert ghrelay.note({**base, "kind": "pay", "mint": "M", "head": "a" * 40, "pr": 9, "paid": paid, "held_back": 2_000_000, "warranty_until": 1_791_209_600}) == (
        "8.00 was paid to W (GitHub user id 42) for order O. 2.00 more is held back until 2026-10-05 14:13 UTC, the end of the order's warranty: "
        "it follows then, unless the change is reverted first.")
    assert ghrelay.note({**base, "kind": "pay", "mint": "M", "head": "a" * 40, "pr": 9, "paid": paid, "left": 5_000_000}).endswith(" The standing order stays open with 5.00 left.")
    assert ghrelay.note({**base, "kind": "rule", "mint": "M", "paid": paid}) == "The arbiter ruled. 8.00 was paid to W (GitHub user id 42) for order O."
    assert ghrelay.note({**base, "kind": "take", "taker_id": 42, "days": 7, "reserved_until": 1_791_209_600}) == (
        "Order O (issue #3) is reserved for GitHub user id 42 until 2026-10-05 14:13 UTC.")
    assert ghrelay.note({**base, "kind": "cancel", "cancel_at": 1_790_604_800, "deadline": 1_791_209_600}).startswith(
        "Order O (issue #3) is cancelled with notice: a pull request that meets its terms before 2026-10-05 14:13 UTC is still paid;")
    assert ghrelay.note({**base, "kind": "revert", "head": "abcdef0" + "1" * 33, "mint": "M", "amount": 10_250_000}) == (
        "10.25 that order O held went back to its funder: the change it paid for was reverted inside its warranty (commit abcdef0).")
    assert ghrelay.note({"ok": True, "kind": "bind", "sigs": ["a"], "user_id": 77, "wallet": "W", "org": True, "by": 42, "settled": []}) == (
        "GitHub organisation id 77 is now paid at W (its member with id 42 ran the claim).")
    assert ghrelay.note({"ok": True, "kind": "key", "sigs": ["a"], "key": "K", "added": True, "refreshed": False, "issuer": "https://gitlab.example.com"}) == (
        "Key K of the issuer https://gitlab.example.com registered with the verifier: it verifies after a day's wait, once the guardian has approved it.")


def test_verify_only_is_limited_to_20_a_day_for_one_repository(world):
    gh, relays, state = world
    t0 = 1_791_021_600.0                                        # 2026-10-03 10:00 UTC
    gh.search = ["octo/widgets"]
    mine = [jwt("sts.amazonaws.com", repository_id="111", iat=1000 + i) for i in range(23)]
    other = jwt("sts.amazonaws.com", repository_id="222")
    gitlab = jwt("https://vault.example.com", project_id="20")
    for token in (*mine[:22], other, gitlab):
        gh.comment("octo/widgets", 1, ghrelay.token_comment("verify", token), at=t0 - 5)
    relays.answers[ghrelay.token_id(mine[0])] = {"ok": False, "kind": "verify", "why": "the signature is not the issuer's"}      # costs nothing: not counted
    relays.answers[ghrelay.token_id(mine[1])] = {"ok": True, "kind": "verify", "sigs": [], "already": True, "note": "done"}      # nor is one already there
    lines = passes(t0)
    ok, no = [ln for ln in lines if " ok " in ln], [ln for ln in lines if " fail " in ln]
    # (the one the chain already had is not logged at once: its line waits ALREADY_WAIT for the run that sent it to speak)
    assert len(lines) == 23 and len(ok) == 22 and len(no) == 1 and "the signature is not the issuer's" in no[0]
    assert json.loads(state.read_text())["verify"] == {"day": "2026-10-03", "n": {"111": 20, "222": 1, "gitlab:20": 1}}
    # the twenty-first of that repository is refused without being carried; another repository's is not
    gh.comment("octo/widgets", 1, ghrelay.token_comment("verify", mine[22]), at=t0)
    gh.comment("octo/widgets", 1, ghrelay.token_comment("verify", jwt("x", repository_id="222", iat=5)), at=t0)
    n = len(relays.calls)
    lines = passes(t0 + 3)
    assert len(relays.calls) == n + 1 and len(lines) == 2 and " ok " in lines[0]
    assert lines[1].split(" fail ")[1] == ("20 tokens a day are verified for one repository, and this one has had them; post it again after midnight UTC, "
                                           "or relay it yourself (anyone can)")
    # the next day it is carried again
    late = jwt("sts.amazonaws.com", repository_id="111", iat=99_000)
    gh.comment("octo/widgets", 1, ghrelay.token_comment("verify", late), at=t0 + 86_400)
    held, carried = passes(t0 + 86_400)                         # (with it, the line that waited: nobody else's line answered for that token)
    assert "(another relayer carried it first) t=" in held and " sent_at=- confirmed_at=- " in held and f" {ghrelay.token_id(late)} ok " in carried and relays.calls[-1][1] == late
    assert json.loads(state.read_text())["verify"] == {"day": "2026-10-04", "n": {"111": 1}}


# -- what 2.1 added: work orders, the meter, passkey withdrawals -------------------------------------------------------------------
def test_a_withdrawal_request_is_read_only_in_a_knos_claim_repository_and_an_evaluation_under_its_own_marker(world):
    gh, relays, state = world
    t0 = 1_791_021_600.0                                        # 2026-10-03 10:00 UTC
    request = base64.b64encode(bytes(range(256)) * 2).decode()  # the shape of passkey.request's text (the relay is faked here)
    ev = jwt("knosm:eval:1:2:" + "a1" * 32 + ":" + "b" * 40 + ":" + "b2" * 32 + ":0:1:5")
    order_fund = jwt(f"knos3:fund:7:20000000:0:{hashlib.sha256(TERMS).hexdigest()}:1209600:{BALANCE}:0:{'00' * 48}", iat=1001)
    gh.search = ["alice/knos-claim", "octo/widgets", "a/copies"]
    gh.comment("alice/knos-claim", 1, f"knos-withdraw: {request}\n\n{ghrelay.MARK}", who="alice", at=t0 - 5)
    gh.comment("a/copies", 3, f"knos-withdraw: {request}", who="mallory", at=t0 - 5)      # anyone can copy a request anywhere, even where it is read first:
                                                                                         # it is read in a knos-claim repository only, and the copy uses nothing up
    gh.comment("octo/widgets", 4, ghrelay.token_comment("eval", ev), at=t0 - 5)
    gh.comment("octo/widgets", 5, ghrelay.token_comment("fund", order_fund, TERMS), at=t0 - 5)
    gh.comment("octo/widgets", 6, ghrelay.token_comment("fund", order_fund, b'{"v":2}'), at=t0 - 5)      # an order's fund token needs its terms too
    relays.answers[ghrelay.token_id(request)] = {"ok": True, "kind": "withdraw", "sigs": ["w1"], "note": "sent"}
    relays.answers[ghrelay.token_id(ev)] = {"ok": True, "kind": "eval", "sigs": ["e1"], "note": "counted"}
    lines = passes(t0)
    assert relays.calls == [("withdraw", request, None), ("eval", ev, None), ("fund", order_fund, TERMS)]
    short = ghrelay.token_id(request)[:8]
    assert sorted(re.sub(r" wait=\d+ chain=\d+| \w+_at=[\d.]+", "", ln.rsplit(" t=", 1)[0]) for ln in lines) == sorted([
        f"knos-relay withdraw alice/knos-claim#1 {ghrelay.token_id(request)} ok sig=w1 note=sent",
        f"knos-relay withdraw a/copies#3 - fail this comment cannot carry its token ({short}...): a withdrawal request is read only on an issue of a repository named knos-claim",
        f"knos-relay eval octo/widgets#4 {ghrelay.token_id(ev)} ok sig=e1 note=counted",
        f"knos-relay fund octo/widgets#5 {ghrelay.token_id(order_fund)} ok sig=s1,s2 note=done",
        f"knos-relay fund octo/widgets#6 - fail this comment cannot carry its token ({ghrelay.token_id(order_fund)[:8]}...): its `knos-terms:` line is missing, "
        "or is not the terms the token names"])
    assert json.loads(state.read_text())["verify"]["n"] == {"withdraw:alice/knos-claim": 1}      # the relay pays each fee: 20 a day for one repository
    saved = json.loads(state.read_text())
    saved["verify"]["n"]["withdraw:alice/knos-claim"] = ghrelay.WITHDRAW_PER_DAY
    state.write_text(json.dumps(saved))
    another = base64.b64encode(bytes(range(255, -1, -1)) * 2).decode()
    gh.comment("alice/knos-claim", 1, f"knos-withdraw: {another}", who="alice", at=t0)
    [line] = passes(t0 + 3)
    assert "fail 20 withdrawals a day are sent for one repository" in line and len(relays.calls) == 3
    # what their results say in words
    order = {"ok": True, "kind": "fund", "sigs": ["a"], "order": "O", "repo_id": 5, "issue": 3, "seq": 0, "amount": 20_000_000, "fee": 500_000, "mode": 0,
             "faucet": False, "balance": "B", "deadline": 1_791_209_600}
    assert ghrelay.note(order) == ("20.00 from balance B is in escrow as a work order for issue #3 (its funder paid a fee of 0.50 on top), paid when a pull request "
                                   "for this issue is merged and meets the order's terms. Unpaid by 2026-10-05 14:13 UTC, it goes back to its funder. Order O.")
    paid = {"ok": True, "kind": "pay", "sigs": ["a"], "order": "O", "head": "a" * 40, "pr": 7,
            "paid": [{"payee_id": 42, "amount": 12_000_000, "to": "W", "held_until": None}, {"payee_id": 43, "amount": 8_000_000, "to": "X", "held_until": None}]}
    assert ghrelay.note(paid) == "12.00 was paid to W (GitHub user id 42), 8.00 was paid to X (GitHub user id 43) for order O."
    held = ghrelay.note({**paid, "paid": [{"payee_id": 42, "amount": 20_000_000, "to": None, "held_until": 1_805_552_000}]})
    assert held.startswith("20.00 of order O is held for GitHub user id 42 until 2027-03-20 14:13 UTC. It is sent once they name a wallet")
    counted = {"ok": True, "kind": "eval", "sigs": ["a"], "buyer_id": 1, "seller_id": 2, "order": "a1" * 32, "artifact": "b" * 40, "milestone": 0, "accepted": False,
               "rate": 5, "fee": 50_000, "month": 202610}
    assert ghrelay.note(counted) == f"Counted: buyer 1, seller 2, artifact {'b' * 40}, milestone 0, rejected. Fee 0.05 from the buyer's credits; month 202610."
    assert ghrelay.note({"ok": True, "kind": "withdraw", "sigs": ["a"], "wallet": "P", "mint": "M", "to": "T", "amount": 5, "nonce": 3}) == \
        "5 of mint M (its smallest units) went from passkey wallet P to T, as its withdrawal number 3."


# -- the public log ------------------------------------------------------------------------------------------------------------
def test_a_log_line_keeps_its_format_and_says_how_long_the_token_took(world, monkeypatch):
    gh, relays, state = world
    t0 = time.time()
    gh.search = ["octo/widgets"]
    good, bad, known = jwt(fund_aud(7)), jwt(fund_aud(8), iat=1001), jwt("knos-oidc:key:0:" + "ab" * 32, iat=1002)
    relays.answers[ghrelay.token_id(good)] = {"ok": True, "kind": "fund", "sigs": ["s1", "s2", "s3", "s4"], "note": "5.00 test USDC is in escrow for issue #7."}
    relays.answers[ghrelay.token_id(bad)] = {"ok": False, "kind": "fund", "why": "this commenter may not\nspend that balance"}
    relays.answers[ghrelay.token_id(known)] = {"ok": True, "kind": "key", "sigs": [], "key": "K", "added": False, "refreshed": False}
    gh.comment("octo/widgets", 7, ghrelay.token_comment("fund", good, TERMS), at=t0 - 5)
    gh.comment("octo/widgets", 8, ghrelay.token_comment("fund", bad, TERMS), at=t0 - 5)
    gh.comment("octo/widgets", 9, ghrelay.token_comment("key", known), at=t0 - 5)
    lines = passes(t0)
    m = re.fullmatch(rf"knos-relay fund octo/widgets#7 {ghrelay.token_id(good)} ok sig=s2,s3,s4 wait=(\d+) chain=0 queued_at=[\d.]+ seen_at=[\d.]+ sent_at=[\d.]+ confirmed_at=[\d.]+ note=5.00 test USDC is in escrow for issue #7. t=(\d+)", lines[0])
    assert m and 5 <= int(m.group(1)) <= int(m.group(2)) <= 7, lines     # from the comment's creation to the last transaction; the stages come before the note
    assert lines[1:] == [f"knos-relay fund octo/widgets#8 {ghrelay.token_id(bad)} fail this commenter may not spend that balance"]      # one line; no time on a refusal;
    assert gh.log() == [lines[0], lines[1]]                      # and nothing for a key the chain already had. What worked was logged at once
    assert ghrelay.log_line("proof", "o/r", 9, good, {"ok": True, "sigs": [], "note": "N", "already": True}, 12).endswith(" ok sig=none note=N (another relayer carried it first) t=12")
    assert ghrelay.log_line("proof", "o/r", 9, good, {"ok": True, "sigs": ["s"], "note": "paid queue=9 to W"}, 12, {"chain": 4, "queue": 3, "wait": 8, "workflow": 21}).endswith(
        " ok sig=s queue=3 workflow=21 wait=8 chain=4 note=paid queue=9 to W t=12")
    # a verdict GitHub would not take is not lost: the next pass posts it
    later = jwt(fund_aud(10), iat=1005)
    gh.comment("octo/widgets", 10, ghrelay.token_comment("fund", later, TERMS))
    gh.down.add(f"repos/{HOME}/issues/1/comments")
    lines = passes(t0 + 3)
    assert len(lines) == 1 and len(gh.log()) == 2 and json.loads(state.read_text())["unposted"] == lines
    gh.down.clear()
    assert passes(t0 + 6) == [] and gh.log()[2] == lines[0] and "unposted" not in json.loads(state.read_text())
    # a relay with no log issue yet makes one, labelled, on its first line
    gh.issues[HOME] = []
    monkeypatch.setattr(ghrelay, "_LOG", {})
    ghrelay.post_log(["knos-relay settle - - ok sig=s note=n"])
    assert gh.issues[HOME] == [{"number": 1, "state": "open", "labels": [ghrelay.LOG_LABEL]}] and gh.log()[-1] == "knos-relay settle - - ok sig=s note=n"
    # more lines than one comment holds go in as many comments as it takes, none of them cut
    many = [f"knos-relay fund o/r#{i} - fail " + "x" * 950 for i in range(130)]
    n = len(gh.log())
    ghrelay.post_log(many)
    assert len(gh.log()) == n + 3 and "\n".join(gh.log()[n:]).splitlines() == many and all(len(body) <= 60_000 for body in gh.log()[n:])


def test_the_log_line_says_where_the_time_went_and_the_site_reads_it(world, monkeypatch):
    """queue, workflow, wait and chain, in seconds, where each can be measured: the run GitHub records for the token
    (its creation is the comment or the merge that started it), the token's comment, and the relay's own clock."""
    gh, relays, _state = world
    t0 = 1_791_021_600.0
    clock = [t0]
    monkeypatch.setattr(ghrelay.time, "time", lambda: clock[0])
    gh.search = ["octo/widgets"]
    proof = jwt("knos2:pay:1:7:9:" + "a" * 40 + ":" + "0" * 64 + ":0:-", repository="octo/widgets", run_id="5550001", run_attempt="1")
    bare = jwt("knos2:pay:1:8:9:" + "a" * 40 + ":" + "0" * 64 + ":0:-", iat=1001, repository="octo/private", run_id="5550002")      # GitHub will not say when it ran
    gh.runs["octo/widgets/5550001"] = {"created_at": ghrelay._stamp(t0 - 40), "run_started_at": ghrelay._stamp(t0 - 37), "run_attempt": 1}
    gh.comment("octo/widgets", 12, ghrelay.token_comment("proof", proof), at=t0 - 9)      # the merge was 40 s ago, the run began 3 s later and posted its token 28 s after that
    gh.comment("octo/widgets", 13, ghrelay.token_comment("proof", bare), at=t0 - 9)

    def carried(ledger, payer, kind, token, terms=None):
        clock[0] += 4                                           # two transactions and their confirmations
        return {"ok": True, "kind": "pay", "sigs": ["s1", "s2"], "note": "4.88 test USDC was paid to W for issue #7 (GitHub user id 9)."}
    monkeypatch.setattr(ghrelay, "relay_one", carried)
    lines = passes(t0)
    assert lines == [f"knos-relay proof octo/widgets#12 {ghrelay.token_id(proof)} ok sig=s1,s2 queue=3 workflow=28 wait=9 chain=4 "
                     f"queued_at={t0 - 9:.1f} seen_at={t0:.1f} sent_at={t0:.1f} confirmed_at={t0 + 4:.1f} "
                     "note=4.88 test USDC was paid to W for issue #7 (GitHub user id 9). t=13",
                     f"knos-relay proof octo/widgets#13 {ghrelay.token_id(bare)} ok sig=s1,s2 wait=13 chain=4 "
                     f"queued_at={t0 - 9:.1f} seen_at={t0 + 4:.1f} sent_at={t0 + 4:.1f} confirmed_at={t0 + 8:.1f} "
                     "note=4.88 test USDC was paid to W for issue #7 (GitHub user id 9). t=17"]
    assert ghrelay.stages("not a token", None, 5.0, 7.4) == {"chain": 2} and ghrelay.stages(proof, t0 - 50, t0, t0 + 1) == {"queue": 3, "wait": 50, "chain": 1}
    # the readers of the line: the site's latency split, the caller's verdict, the claim's
    import importlib.util
    import sys
    from pathlib import Path
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("pages_data_under_test", scripts / "pages_data.py")
    pages = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = pages
    spec.loader.exec_module(pages)
    extras, fails = pages.relay_extras([{"body": "\n".join(lines), "created_at": ghrelay._stamp(t0)}])
    assert extras == {ghrelay.token_id(proof): {"queue": 3.0, "workflow": 28.0, "wait": 9.0, "chain": 4.0}, ghrelay.token_id(bare): {"wait": 13.0, "chain": 4.0}} and fails == []
    assert re.search(r"\bnote=(.*?)(?:\s+t=[0-9.]+)?\s*$", lines[0]).group(1) == "4.88 test USDC was paid to W for issue #7 (GitHub user id 9)."      # knos.flow's reading
    assert re.search(r"\bsig=(\S+)", lines[0]).group(1) == "s1,s2"


def test_a_token_that_must_wait_is_tried_again_when_its_time_comes_not_on_every_pass(world, monkeypatch):
    gh, relays, state = world
    t0 = time.time()
    gh.search = ["a/one", "b/two"]
    early, late, dropped = jwt(fund_aud(1), iat=1000), jwt(fund_aud(2), iat=2000), jwt(fund_aud(3), iat=3000)
    gh.comment("b/two", 1, ghrelay.token_comment("fund", early, TERMS))
    gh.comment("a/one", 2, ghrelay.token_comment("fund", late, TERMS))
    gh.comment("a/one", 3, ghrelay.token_comment("fund", dropped, TERMS))
    relays.answers[ghrelay.token_id(late)] = {"ok": False, "kind": "fund", "why": "the faucet serves a repository once a minute", "retry": True, "wait": 50}
    relays.answers[ghrelay.token_id(dropped)] = {"ok": False, "kind": "fund", "why": "TimeoutError: not confirmed", "retry": True, "transient": True}
    assert len(passes(t0)) == 1 and [c[1] for c in relays.calls] == [early, late, dropped]      # in the order GitHub issued them, across repositories
    # the relay said how long the faucet's token must wait: it is not asked about again before that. A failure of the
    # cluster's is tried on the next passes, then given more room each time
    asked = lambda token: sum(1 for c in relays.calls if c[1] == token)  # noqa: E731
    for i in range(1, 17):
        passes(t0 + 3 * i)
    assert asked(late) == 1 and asked(dropped) == 5 and list(json.loads(state.read_text())["tries"].values()) == [5]      # at 0, 3, 6, 18 and 39 s
    del relays.answers[ghrelay.token_id(late)]
    assert passes(t0 + 49) == [] and len(passes(t0 + 50)) == 1 and asked(late) == 2
    # a failure that never clears is given up on after twelve tries, which now takes minutes, and said out loud
    t, lines = t0 + 50, []
    while not lines and t < t0 + 900:
        t += 3
        lines = passes(t)
    assert asked(dropped) == 12 and 360 < t - t0 < 480 and lines[0].endswith("(gave up after 12 passes; run the workflow again for a fresh token)")
    assert json.loads(state.read_text())["hold"] == {} and json.loads(state.read_text())["tries"] == {}


def test_wait_for_finds_the_workers_line_for_a_token(world):
    gh, _relays, _state = world
    tid = ghrelay.token_id(jwt(fund_aud(7)))
    line = f"knos-relay fund octo/widgets#7 {tid} ok sig=s1,s2 note=5.00 test USDC is in escrow for issue #7. t=6"
    gh.comment(HOME, 1, f"knos-relay fund a/b#1 {'0' * 16} ok sig=x note=y t=1\nknos-relay proof a/b#2 {'1' * 16} fail no")
    gh.comment(HOME, 1, line.replace(" ok ", " fail "), who="mallory")       # anyone can comment on a public issue: not the worker's, not counted
    assert ghrelay.wait_for(tid, HOME, 0.05, every=0.01) is None
    assert {status for _m, path, status in gh.asked if "issues/1/comments" in path} == {200, 304}       # asked again and again, for nothing
    # the worker reports while the caller waits: the line comes back as it was written
    polls = []

    def get(path):
        polls.append(path)
        if len(polls) == 5:
            gh.comment(HOME, 1, f"knos-relay key x/y#3 {'2' * 16} ok sig=k note=z\n{line}")
        return ghrelay._api(path)
    assert ghrelay.wait_for(tid, HOME, 5, every=0, get=get) == line
    assert len(polls) == 5 and all(p.startswith(f"repos/{HOME}/issues/1/comments?since=") for p in polls)      # the log issue is looked up once, not on every poll
    # a log with more than a page of lines since the caller began waiting is read to its end
    gh.comments[HOME] = []
    for i in range(101):
        gh.comment(HOME, 1, f"knos-relay fund a/b#1 {i:016x} ok sig=x note=y t=1" if i < 100 else line)
    assert ghrelay.wait_for(tid, HOME, 1, every=0) == line
    # a repository with no relay log, and GitHub not answering: None when the time is up
    assert ghrelay.wait_for(tid, "no/log", 0.02, every=0.01) is None
    gh.down.add(f"repos/{HOME}/issues/1/comments")
    assert ghrelay.wait_for(tid, HOME, 0.02, every=0.01) is None


def test_serve_loops_passes_and_sends_what_needs_no_token_once_a_minute(monkeypatch):
    clock, ran = [0.0], []

    def once(ledger, payer, crank=True):
        ran.append((clock[0], crank))
        clock[0] += 1.0 if len(ran) != 3 else 7.0               # a pass takes a second; the third one, with a token to carry, seven
        if len(ran) == 2:
            raise OSError("GitHub is down")                     # one bad pass does not stop the worker
        return ["line"]
    monkeypatch.setattr(ghrelay, "once", once)
    assert ghrelay.serve(70, every=3.0, ledger="ledger", payer="payer", clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s)) == len(ran) - 1
    starts = [t for t, _c in ran]
    assert starts[:5] == [0.0, 3.0, 6.0, 13.0, 16.0] and all(t < 70 for t in starts)      # every three seconds, or as soon as the last pass ended
    assert [t for t, crank in ran if crank] == [0.0, 61.0]


# -- one pass, end to end, on LiteSVM --------------------------------------------------------------------------------------------
def test_a_pass_carries_a_fund_token_and_its_proof_to_the_second_deployment(monkeypatch, tmp_path, build):
    pytest.importorskip("solders.litesvm")
    from _pay2 import Chain
    from test_relay2 import JWKS, TERMS as terms, Net, faucet_jwt, pay_jwt, user

    from knos.settle.v2 import pay
    c = Chain(pay_build=build.build)
    net = Net(c)
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    gh = GitHub()
    gh.issues[HOME] = [{"number": 1, "state": "open", "labels": [ghrelay.LOG_LABEL]}]
    gh.search = ["octo/widgets"]
    monkeypatch.setattr(ghrelay, "_HUB", ghrelay.Hub(gh.open))
    monkeypatch.setattr(ghrelay, "_LOG", {})
    monkeypatch.setattr(ghrelay, "_state_path", lambda: tmp_path / "ghrelay.json")
    monkeypatch.setattr(relay1, "fetch_jwks", lambda issuer: JWKS[issuer])      # GitHub's key set, as the relays would fetch it
    monkeypatch.setattr(relay2, "_KEPT", {})
    org, repo, payee, wallet = user(), user(), user(), Keypair().pubkey()
    fund = faucet_jwt(c, 7, org, repo)
    gh.comment("octo/widgets", 7, ghrelay.token_comment("fund", fund, terms), at=time.time() - 4)
    [line] = ghrelay.once(net, c.payer)
    job = pay.job_pda(repo, 7, pay.faucet_balance_pda(org))
    assert re.fullmatch(rf"knos-relay fund octo/widgets#7 {ghrelay.token_id(fund)} ok sig=\S+ wait=\d+ chain=\d+ queued_at=[\d.]+ seen_at=[\d.]+ sent_at=[\d.]+ confirmed_at=[\d.]+ note=5.00 test USDC is in escrow for issue #7, paid when .* Job {job}\. t=\d+", line), line
    assert pay.read_job(c.data(job)).terms == pay.terms_hash(terms) and net.terms_of(job) == terms
    # a fund token in a comment without its terms line (a copy somebody made, or a broken workflow) funds nothing; the
    # log says why without naming the token, and the token is still carried from the comment that posts it whole
    c.warp(60)
    bare = faucet_jwt(c, 8, org, repo)
    gh.comment("octo/widgets", 8, f"knos-fund: {bare}\n\n{ghrelay.MARK}")
    [line] = ghrelay.once(net, c.payer)
    assert line == (f"knos-relay fund octo/widgets#8 - fail this comment cannot carry its token ({ghrelay.token_id(bare)[:8]}...): its `knos-terms:` line is missing, "
                    "or is not the terms the token names")
    assert ghrelay.wait_for(ghrelay.token_id(bare), HOME, 0.02, every=0.01) is None
    gh.comment("octo/widgets", 8, ghrelay.token_comment("fund", bare, terms))
    [line] = ghrelay.once(net, c.payer)
    assert f" {ghrelay.token_id(bare)} ok sig=" in line and pay.read_job(c.data(pay.job_pda(repo, 8, pay.faucet_balance_pda(org)))).state == "open"
    # the proof pays; the caller, waiting on the worker's log, reads the same line
    proof = pay_jwt(c, repo, 7, payee, wallet)
    gh.comment("octo/widgets", 12, ghrelay.token_comment("proof", proof))
    c.warp(60)
    [line] = ghrelay.once(net, c.payer)
    # the job of 5.00 less the fee the live build takes out of it: 0.125 under 2.1, 0.05 under 2.2
    assert f"note={build.pick('4.88', '4.95')} test USDC was paid to {wallet} for issue #7 (GitHub user id {payee}). t=" in line
    assert c.balance(pay.ata(wallet, pay.faucet_mint())) == build.pick(4_875_000, 4_950_000)
    assert ghrelay.wait_for(ghrelay.token_id(proof), HOME, 1, every=0) == line
    assert ghrelay.once(net, c.payer) == []                     # each token once
    # what needs no token: a bounty nobody proved goes back when its time is up, and the log says so
    c.warp(60)
    late = faucet_jwt(c, 9, org, repo, work=60)
    gh.comment("octo/widgets", 9, ghrelay.token_comment("fund", late, terms))
    assert len(ghrelay.once(net, c.payer)) == 1
    c.warp(61)
    [line] = ghrelay.once(net, c.payer)
    assert re.fullmatch(r"knos-relay refund - - ok sig=\S+ note=a bounty nobody could be paid from any more went back to its funder", line)
    assert c.data(pay.job_pda(repo, 9, pay.faucet_balance_pda(org))) is None and gh.log()[-1] == line


# -- two runs of the worker relay together for a few seconds (worker.yml starts the next before this one stops) ---------------
def test_a_run_that_takes_over_neither_carries_nor_logs_again_what_the_log_answers(world, monkeypatch):
    gh, relays, state = world
    t0 = time.time()
    done, new = jwt(fund_aud(7)), jwt(fund_aud(8))
    gh.comment("octo/widgets", 7, ghrelay.token_comment("fund", done, TERMS), at=t0 - 200)
    gh.comment("octo/widgets", 8, ghrelay.token_comment("fund", new, TERMS), at=t0 - 5)
    # the run before this one carried the first token and logged it; the notes this run starts from are a run old
    gh.comment(HOME, 1, f"knos-relay fund octo/widgets#7 {ghrelay.token_id(done)} ok sig=s1 note=done t=4", at=t0 - 190)
    state.write_text(json.dumps({"run": "41", "repos": {"octo/widgets": t0 - 400}}))
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    lines = passes(t0)
    assert [c[1] for c in relays.calls] == [new] and len(lines) == 1 and ghrelay.token_id(new) in lines[0]
    assert json.loads(state.read_text())["run"] == "42" and len(gh.log()) == 2
    # from then on the notes are this run's own: the log is not read for them again
    n = len(gh.asked)
    assert passes(t0 + 3) == [] and f"repos/{HOME}/issues/1/comments" not in [path for path, _status in gh.gets(n)]


def test_a_token_the_chain_shows_done_is_logged_once_whichever_run_carried_it(world, monkeypatch):
    gh, relays, state = world
    t0 = time.time()
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    ours, theirs = jwt(fund_aud(7)), jwt(fund_aud(8))
    gh.search = ["octo/widgets"]
    for n, token in ((7, ours), (8, theirs)):
        gh.comment("octo/widgets", n, ghrelay.token_comment("fund", token, TERMS), at=t0 - 5)
        relays.answers[ghrelay.token_id(token)] = {"ok": True, "kind": "fund", "sigs": ["s1"], "note": "done", "already": True}
    # the run that relayed beside this one carried the first and logged it; someone else's relayer carried the second
    gh.comment(HOME, 1, f"knos-relay fund octo/widgets#7 {ghrelay.token_id(ours)} ok sig=s1 note=done t=3", at=t0 - 2)
    # (nothing is said of the second at once: had a run of this relay carried it, its own line would be on its way)
    assert passes(t0) == [] and len(relays.calls) == 2 and passes(t0 + 3) == []
    [line] = passes(t0 + ghrelay.ALREADY_WAIT)
    assert ghrelay.token_id(theirs) in line and "(another relayer carried it first)" in line and len(relays.calls) == 2
    assert " sent_at=- confirmed_at=- " in line                  # this relay sent nothing: it claims no time for it
    assert [ln for ln in gh.log() if ghrelay.token_id(ours) in ln] == [gh.log()[0]] and passes(t0 + 60) == []


# -- two runs overlap: what the loser of a race sees, and which log line answers for which comment ------------------------------
def test_the_run_that_loses_a_passkey_withdrawal_to_the_other_run_logs_no_failure_for_it(world, monkeypatch):
    """A passkey withdrawal has no `already`: once one run sent it, the wallet's nonce has moved on and the other run is
    refused. That refusal is not the request's verdict: the log has the one that sent it."""
    gh, relays, _state = world
    t0 = 1_791_021_600.0
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    sent, refused = (base64.b64encode(bytes(range(256)) * n).decode() for n in (2, 3))
    gh.search = ["alice/knos-claim"]
    gh.comment("alice/knos-claim", 1, f"knos-withdraw: {sent}", who="alice", at=t0 - 5)
    gh.comment("alice/knos-claim", 2, f"knos-withdraw: {refused}", who="alice", at=t0 - 5)
    for request in (sent, refused):
        relays.answers[ghrelay.token_id(request)] = {"ok": False, "kind": "withdraw", "why": "the wallet's nonce is not the request's"}
    # the run relaying beside this one sent the first a moment ago and logged it
    gh.comment(HOME, 1, f"knos-relay withdraw alice/knos-claim#1 {ghrelay.token_id(sent)} ok sig=w1 note=sent t=2", at=t0 - 1)
    lines = passes(t0)
    assert len(relays.calls) == 2
    assert [ln.split()[1:5] for ln in lines] == [["withdraw", "alice/knos-claim#2", ghrelay.token_id(refused), "fail"]]     # a refusal of its own is logged
    assert [ln for ln in gh.log() if ghrelay.token_id(sent) in ln] == [gh.log()[0]]


def test_a_copys_log_line_under_another_marker_does_not_answer_for_the_comment_that_posts_the_token_rightly(world, monkeypatch):
    """A run that takes over skips what the log answers. A copy of a token under another marker is logged with the
    token's id (a token of nobody's audience is refused only by the relay), and must not answer for the right one."""
    gh, relays, state = world
    t0 = time.time()
    token = jwt("sts.amazonaws.com")
    gh.comment("octo/widgets", 3, ghrelay.token_comment("verify", token), at=t0 - 5)
    gh.comment(HOME, 1, f"knos-relay fund mallory/r#1 {ghrelay.token_id(token)} fail not a Knos audience", at=t0 - 3)
    state.write_text(json.dumps({"run": "41", "repos": {"octo/widgets": t0 - 30}}))
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    lines = passes(t0)
    assert relays.calls == [("verify", token, None)] and [ln.split()[1:5] for ln in lines] == [["verify", "octo/widgets#3", ghrelay.token_id(token), "ok"]]
    assert ghrelay.answer("verify", token) != ghrelay.answer("fund", token)


# -- `knos relay`, read by knos.flow: the worker's command, and a job that relays its own token -------------------------------
class Passes:
    """knos.proof.ghrelay where flow.relay uses it for passes: `once` does what the test says, pass by pass."""
    CRANK_EVERY = ghrelay.CRANK_EVERY

    def __init__(self, *outcomes):
        self.outcomes, self.ran = list(outcomes), []

    def once(self, ledger, payer, crank=True):
        self.ran.append(crank)
        got = self.outcomes[min(len(self.ran), len(self.outcomes)) - 1] if self.outcomes else None
        if isinstance(got, BaseException):
            raise got
        return []


def _clock(step: float = 1.0):
    """A clock a pass moves on by `step` seconds each time it is read, and a sleep that moves it."""
    t = [0.0]

    def clock() -> float:
        t[0] += step
        return t[0]
    return clock, lambda s: t.__setitem__(0, t[0] + s)


def test_the_relays_exit_status_says_whether_it_relayed(capsys, monkeypatch):
    """worker.yml takes the relay's status as the step's. One bad pass never stops the worker (GitHub was down); a
    relay that could not make one pass, or that lacks a module, is status 1 with one line that says why."""
    from knos import flow
    clock, sleep = _clock()
    kw = dict(ledger="ledger", payer="payer", clock=clock, sleep=sleep, env={"GH_TOKEN": "t"})
    good = Passes(None, OSError("GitHub is down"), None)
    assert flow.relay(serve=30, ghrelay=good, **kw) == 0 and len(good.ran) > 3 and good.ran[0] is True and not any(good.ran[1:])
    assert "relay pass: OSError: GitHub is down" in capsys.readouterr().err
    down = Passes(OSError("GitHub is down"))
    said = flow.relay(serve=30, ghrelay=down, **kw)
    assert isinstance(said, str) and "not one pass finished in 30 seconds" in said and "OSError: GitHub is down" in said and len(down.ran) > 3
    # what 0.3.13's worker met: a module the install does not have. The first pass ends the relay; nothing is retried
    broken = Passes(ModuleNotFoundError("No module named 'typer'"))
    said = flow.relay(serve=250, ghrelay=broken, **kw)
    assert len(broken.ran) == 1 and said == ("knos relay cannot run in this install: ModuleNotFoundError: No module named 'typer'. Nothing was relayed.")
    assert flow.relay(ghrelay=Passes(None), **kw) == 0                                          # one pass, with no option
    assert "the pass did not finish: OSError: GitHub is down" in flow.relay(ghrelay=down, **kw)
    # through the command line: the line is printed and the status is 1
    assert flow.takes(["relay", "--serve", "250"]) and flow.main(["relay", "--token-file", "/nowhere/token"]) == 1
    assert "No such file" in capsys.readouterr().out
    # a key that is no key: said in a line, before any pass
    for name in ("KNOS_RELAY_KEY", "KNOS_MEMBER_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KNOS_FEE_KEY", "not a key")              # the name a repository's own workflow may give its fee key
    ran = len(good.ran)
    assert "knos relay cannot start" in flow.relay(serve=30, ghrelay=good) and len(good.ran) == ran


def test_a_job_relays_its_own_token_from_a_file_with_knos_relay(build, monkeypatch, tmp_path, capsys):
    """A run that holds a token and a fee key relays it itself: `knos relay --token-file F`, the same command path as
    the worker's, with no comment to post and no worker to wait for. The file is the token, or the comment that would
    have carried it (its `knos-terms:` line travels with a fund token). On LiteSVM, through the real relays."""
    pytest.importorskip("solders.litesvm")
    from _pay2 import Chain
    from test_relay2 import JWKS, TERMS as terms, Net, faucet_jwt, pay_jwt, user

    from knos import flow
    from knos.settle.v2 import pay
    c = Chain(pay_build=build.build)
    net = Net(c)
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    monkeypatch.setattr(relay1, "fetch_jwks", lambda issuer: JWKS[issuer])
    monkeypatch.setattr(relay2, "_KEPT", {})
    asked = []
    monkeypatch.setattr(ghrelay, "_HUB", ghrelay.Hub(lambda req, timeout=None: asked.append(req.full_url) or (_ for _ in ()).throw(OSError("no GitHub here"))))
    org, repo, payee, wallet = user(), user(), user(), Keypair().pubkey()
    kw = dict(ghrelay=ghrelay, ledger=net, payer=c.payer, env={})

    def result() -> dict:
        return json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    # the fund token, as the comment that carries it; then alone, with its terms in a file of their own
    fund = faucet_jwt(c, 7, org, repo)
    (tmp_path / "fund").write_text(ghrelay.token_comment("fund", fund, terms), encoding="utf-8")
    assert flow.relay(str(tmp_path / "fund"), **kw) == 0
    r, job = result(), pay.job_pda(repo, 7, pay.faucet_balance_pda(org))
    assert r["ok"] and r["sigs"] and "5.00 test USDC is in escrow for issue #7" in r["note"] and pay.read_job(c.data(job)).state == "open"
    c.warp(60)
    (tmp_path / "bare").write_text(faucet_jwt(c, 8, org, repo) + "\n", encoding="utf-8")
    (tmp_path / "terms").write_bytes(terms + b"\n")
    assert flow.relay(str(tmp_path / "bare"), **kw) == 1 and not result()["ok"]                 # a fund token without its terms funds nothing
    assert flow.relay(str(tmp_path / "bare"), str(tmp_path / "terms"), **kw) == 0 and result()["ok"]
    # the pay token of the merging run: paid at once, with no comment read and no pass over GitHub
    proof = pay_jwt(c, repo, 7, payee, wallet)
    (tmp_path / "pay").write_text(proof, encoding="utf-8")
    c.warp(60)
    assert flow.relay(str(tmp_path / "pay"), **kw) == 0
    r = result()
    assert r["ok"] and f"{build.pick('4.88', '4.95')} test USDC was paid to {wallet} for issue #7" in r["note"] and c.balance(pay.ata(wallet, pay.faucet_mint())) == build.pick(4_875_000, 4_950_000)
    # the same token a second time (the public worker finding a copy, or the step run again) pays nobody twice
    flow.relay(str(tmp_path / "pay"), **kw)
    again = result()
    print(again)
    assert (again.get("already") or not again["ok"]) and c.balance(pay.ata(wallet, pay.faucet_mint())) == build.pick(4_875_000, 4_950_000)
    assert asked == []                                                                          # GitHub was never asked: no poll, no comment fetch
    # the fee key under the name a repository's own workflow may give it: it is the relay's key, when there is no other
    env = {"KNOS_FEE_KEY": json.dumps(list(bytes(c.payer)))}
    flow.relay(str(tmp_path / "pay"), ghrelay=ghrelay, ledger=net, payer=c.payer, env=env)
    assert env["KNOS_RELAY_KEY"] == env["KNOS_FEE_KEY"]
    env = {"KNOS_FEE_KEY": "[1]", "KNOS_RELAY_KEY": "[2]"}
    flow.relay(str(tmp_path / "pay"), ghrelay=ghrelay, ledger=net, payer=c.payer, env=env)
    assert env["KNOS_RELAY_KEY"] == "[2]"


# -- worker.yml: a relay that fails is seen, and starts nothing ----------------------------------------------------------------
def _workflows() -> dict:
    import yaml
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    files = sorted([*(root / ".github" / "workflows").glob("*.yml"), *(root / "examples").glob("*.yml")])
    return {f.name if f.parent.name == "workflows" else f"examples/{f.name}": yaml.safe_load(f.read_text(encoding="utf-8")) for f in files}


RELAYS = re.compile(r"\bknos(?:\.flow)?\s+relay\b")


def test_no_workflow_hides_a_relay_that_failed():
    """0.3.13's worker ran `python -m knos relay --serve 250 || true`: the relay failed at its first import in every
    run, and every run was green. No workflow follows a relay command with anything that swallows its status."""
    docs = _workflows()
    seen = []
    for name, doc in docs.items():
        for job_name, job in (doc.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                script = re.sub(r"\\\n\s*", " ", str(step.get("run") or ""))             # a command over two lines is one command
                for line in script.splitlines():
                    if RELAYS.search(line):
                        seen.append(name)
                        assert "||" not in line.split("relay", 1)[1] and not line.rstrip().endswith(("&", ";true", "; true")), (name, job_name, line)
                        assert not step.get("continue-on-error") and not job.get("continue-on-error"), (name, job_name)
    assert seen.count("worker.yml") == 3                         # the smoke step and the two that relay
    assert "|| true" not in json.dumps(docs["worker.yml"])


def test_the_worker_checks_the_relay_starts_before_it_relays_and_only_a_relay_that_succeeded_starts_the_next_run():
    steps = _workflows()["worker.yml"]["jobs"]["relay"]["steps"]
    runs = [str(s.get("run") or "") for s in steps]
    install = next(i for i, r in enumerate(runs) if "requirements/sign.txt" in r)
    assert "--require-hashes" in runs[install] and runs[install].count(" -r ") == 1       # the lean install: that list and nothing else
    # the smoke step: right after the install, with what was installed, before the key is in any step's environment
    smoke = steps[install + 1]
    assert smoke["run"].strip() == "python -m knos relay --help" and smoke["if"] == "steps.chain.outputs.go == 'true'"
    assert set(smoke["env"]) == {"PYTHONPATH"} and "secrets." not in json.dumps(steps[:install + 2])
    relays = [i for i, r in enumerate(runs) if "knos relay --serve" in r]
    starts = [i for i, r in enumerate(runs) if "python -m knos.proof.chain start" in r]
    assert install + 1 < relays[0] < starts[0] == relays[1] < starts[1] == len(steps) - 1
    first = steps[relays[0]]
    assert first["id"] == "relay" and "gh workflow run" not in first["run"]
    lines = [ln.strip() for ln in first["run"].splitlines()]
    at = lines.index("python -m knos relay --serve 250")
    assert lines[-1] == 'echo "relayed=true" >> "$GITHUB_OUTPUT"' and at < len(lines) - 1      # said only after the relay ended well
    assert "exit 1" in lines[at + 1] and "-ge 200" in lines[at + 1]                             # and had relayed its time: no quick loop
    # every step between the relay and the end runs only while nothing failed (no status function: GitHub adds success())
    for s in steps[relays[0] + 1:-1]:
        assert s["if"] == "steps.chain.outputs.go == 'true'" and "always()" not in s["if"] and "failure()" not in s["if"]
    # the last step runs whatever happened in the handover step, and starts a run only after a relay step that succeeded
    last = steps[-1]["if"]
    assert last.startswith("always() && ") and "steps.relay.outcome == 'success'" in last and "steps.relay.outputs.relayed == 'true'" in last
    assert "||" not in last
    # in the handover step the relay runs after the start, as its own command: its status is the step's
    handover = [ln.strip() for ln in re.sub(r"\\\n\s*", " ", steps[relays[1]]["run"]).splitlines()]
    assert handover[-1] == "python -m knos relay --serve 30" and handover[-2].startswith("python -m knos.proof.chain start ")
