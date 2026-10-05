"""Every way a token can wait minutes for the public relay, each under a fake GitHub and a clock the test moves:
a repository the worker has not seen, a handover with no run relaying, a first send that fails, GitHub's rate limits,
a workflow that queued. What the relay can do about each is asserted; what it cannot is measured and has its bound in
docs/RELAY.md ("Where a token waits"). Then the journal: a token is written down before it is sent, retried on fixed
times until it has an answer, and a relay killed between the send and the confirmation pays nobody twice (LiteSVM)."""
from __future__ import annotations

import json
import re
import urllib.error

import pytest

import test_worker as tw
from test_worker import HOME, PAYER, TERMS, Ledger, fund_aud, jwt

from knos.proof import ghrelay

T0 = 1_791_021_600.0        # a fixed time: nothing here reads this machine's clock
PAY = "knos2:pay:1:7:9:" + "a" * 40 + ":" + "0" * 64 + ":0:-"


class GitHub(tw.GitHub):
    """The worker tests' GitHub, which can also say "slow down" (403 with Retry-After, or with nothing remaining),
    and takes a PATCH of a comment (the relay's status line)."""

    def __init__(self):
        super().__init__()
        self.limit: dict[str, str] | None = None        # the headers of a rate limit: every request is answered 403 with them

    def open(self, req, timeout=None):
        if self.limit is not None:
            self.asked.append((req.get_method(), req.full_url[len(ghrelay.API):], 403))
            raise urllib.error.HTTPError(req.full_url, 403, "rate limited", self.limit, None)
        return super().open(req, timeout)

    def _route(self, method, path, data):
        m = re.fullmatch(r"repos/([^/]+/[^/]+)/issues/comments/(\d+)", path)
        if m and method == "PATCH":
            for c in self.comments.get(m.group(1), []):
                if c["id"] == int(m.group(2)):
                    c["body"] = data["body"]
                    return 200, {"id": c["id"]}
            return 404, None
        return super()._route(method, path, data)


@pytest.fixture
def world(monkeypatch, tmp_path):
    """A fake GitHub behind a reader whose clock is the test's, the relays faked, notes of its own."""
    gh, relays, clock = GitHub(), tw.Relays(), [T0]
    monkeypatch.setattr(ghrelay, "_HUB", ghrelay.Hub(gh.open, clock=lambda: clock[0]))
    monkeypatch.setattr(ghrelay, "_LOG", {})
    monkeypatch.setattr(ghrelay, "_state_path", lambda: tmp_path / "ghrelay.json")
    monkeypatch.setattr(ghrelay, "relay_one", relays)
    monkeypatch.delenv("KNOS_RELAY_REPOS", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    monkeypatch.setenv("KNOS_RELAY_STATUS", "1")
    gh.issues[HOME] = [{"number": 1, "state": "open", "labels": [ghrelay.LOG_LABEL]}]
    return gh, relays, tmp_path / "ghrelay.json", clock


def run(clock: list, until: float, every: float = 3.0, ledger=None, stop=lambda lines: False) -> list[tuple[float, list[str]]]:
    """Passes every `every` seconds of the test's clock until `until` (or `stop(lines)`): [(seconds since T0, the lines)] of the passes that logged."""
    out = []
    while clock[0] <= until:
        lines = ghrelay.once(ledger or Ledger(), PAYER, now=clock[0], crank=False)
        if lines:
            out.append((clock[0] - T0, lines))
        if stop(lines):
            break
        clock[0] += every
    return out


def token(aud: str, **claims) -> str:
    """A token issued at T0 that the chain would take until an hour past its expiry."""
    return jwt(aud, **{"iat": int(T0), "exp": int(T0) + 300, **claims})


def notes(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# -- 1. a repository the worker has not seen ---------------------------------------------------------------------------------
def test_a_token_in_a_repository_the_worker_does_not_know_waits_for_githubs_search_and_no_longer(world, monkeypatch):
    """A funding comment in a repository with no open job, no token in two days and no place in KNOS_RELAY_REPOS is
    found only by GitHub's comment search. The relay asks every SEARCH_EVERY seconds; how late the search's index is,
    is GitHub's. The bound is that lag plus SEARCH_EVERY, and the test shows nothing else is added."""
    gh, relays, _state, clock = world
    fund = token(fund_aud(1))
    gh.comment("new/repo", 1, ghrelay.token_comment("fund", fund, TERMS), at=T0)
    clock[0] = T0 + 2
    assert run(clock, T0 + 92) == [] and relays.calls == []         # 90 s of passes: the index has not caught up, and nothing else knows the repository
    gh.search = ["new/repo"]                                        # GitHub's index has the comment, 93 s after it was posted
    [(at, [line])] = run(clock, T0 + 200, stop=bool)
    assert 93 <= at <= 93 + ghrelay.SEARCH_EVERY and f" {ghrelay.token_id(fund)} ok " in line
    assert int(re.search(r" wait=(\d+) ", line).group(1)) == at     # the whole wait is in the line's `wait=`, for anyone who measures
    # known from then on: the next token there is read on the next pass, with no search
    gh.search, again = [], token(fund_aud(2), iat=int(T0) + 150)
    gh.comment("new/repo", 2, ghrelay.token_comment("fund", again, TERMS), at=clock[0] + 1)
    before = clock[0]
    [(at, _lines)] = run(clock, clock[0] + 30, stop=bool)
    assert at - (before - T0) <= 3
    # and a repository named in KNOS_RELAY_REPOS never waits for the search
    monkeypatch.setenv("KNOS_RELAY_REPOS", "named/repo")
    named = token(fund_aud(3), iat=int(T0) + 160)
    gh.comment("named/repo", 3, ghrelay.token_comment("fund", named, TERMS), at=clock[0] + 1)
    before = clock[0]
    [(at, _lines)] = run(clock, clock[0] + 30, stop=bool)
    assert at - (before - T0) <= 3


def test_a_relay_that_starts_with_no_notes_names_every_open_repository_within_a_few_passes(world):
    """The chain names a repository by its id. With 45 open jobs and empty notes the relay used to learn 20 names a
    minute, so a proof in the 45th waited two minutes; now it asks for 20 a pass, each once after a read of the chain."""
    from knos.settle.v2 import pay
    gh, relays, state, clock = world
    ids = list(range(5000, 5045))
    gh.ids = {i: f"open/r{i}" for i in ids}

    class Open(Ledger):
        def program_accounts(self, program, size=None, memcmp=None):
            rows = [bytes([1]) + bytes(7) + i.to_bytes(8, "little") + bytes(pay.JOB_LEN - 16) for i in ids] if program == pay.PAY_ID else []
            return [(tw.Keypair().pubkey(), d) for d in rows if len(d) == size and all(d[o:o + len(b)] == b for o, b in (memcmp or {}).items())]
    proof = token("knos2:pay:5044:7:9:" + "a" * 40 + ":" + "0" * 64 + ":0:-")
    gh.comment("open/r5044", 12, ghrelay.token_comment("proof", proof), at=T0)
    gh.down.add("search/issues")
    [(at, [line])] = run(clock, T0 + 120, ledger=Open(), stop=bool)
    assert at == 6 and f" {ghrelay.token_id(proof)} ok " in line        # the third pass: 20, 40, 45 names
    asked = [p for p, _s in gh.gets() if p.startswith("repositories/")]
    assert len(asked) == 45 == len(set(asked)) and notes(state)["unnamed"] == []


# -- 2. a token posted while no run relays ---------------------------------------------------------------------------------
def test_a_token_posted_in_a_gap_between_two_runs_is_carried_once_by_the_first_pass_of_the_next(world, monkeypatch):
    """worker.yml overlaps two runs by 30 s. A next run that waits longer than that for a runner, or a chain of runs
    that stopped until the 5-minute timer, leaves a gap: the relay adds nothing to it. The first pass of the next run
    carries what was posted meanwhile, and does not carry again what the run before answered in its last seconds."""
    gh, relays, state, clock = world
    done, gap = token(fund_aud(7)), token(fund_aud(8), iat=int(T0) + 40)
    monkeypatch.setenv("GITHUB_RUN_ID", "41")
    gh.search = ["octo/widgets"]
    run(clock, T0)                                                  # run 41's notes are saved here; it relays 30 s more
    gh.comment("octo/widgets", 7, ghrelay.token_comment("fund", done, TERMS), at=T0 + 10)
    gh.comment(HOME, 1, f"knos-relay fund octo/widgets#7 {ghrelay.token_id(done)} ok sig=s1 note=done t=4", at=T0 + 14)     # carried in those 30 s, not in the notes
    gh.comment("octo/widgets", 8, ghrelay.token_comment("fund", gap, TERMS), at=T0 + 40)                                    # nobody relays: run 42 is waiting for a runner
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    clock[0] = T0 + 340                                             # the timer started the chain again, five minutes on
    [(at, [line])] = run(clock, T0 + 400, stop=bool)
    assert at == 340 and [c[1] for c in relays.calls] == [gap] and f" {ghrelay.token_id(gap)} ok " in line and " wait=300 " in line
    assert sum(ghrelay.token_id(done) in body for body in gh.log()) == 1


# -- 3. a first send that fails ---------------------------------------------------------------------------------------------
def test_a_send_that_fails_for_the_clusters_reasons_is_tried_again_on_fixed_times_and_never_given_up_while_the_token_is_good(world):
    gh, relays, state, clock = world
    proof = token(PAY)
    gh.search = ["octo/widgets"]
    gh.comment("octo/widgets", 12, ghrelay.token_comment("proof", proof), at=T0)
    relays.answers[ghrelay.token_id(proof)] = {"ok": False, "kind": "pay", "why": "TimeoutError: not confirmed within 60s", "retry": True, "transient": True}
    tried = []
    while clock[0] <= T0 + 1800:                                    # half an hour of an endpoint that confirms nothing
        n = len(relays.calls)
        assert ghrelay.once(Ledger(), PAYER, now=clock[0], crank=False) == []      # never a verdict: the failure says nothing about the token
        if len(relays.calls) > n:
            tried.append(int(clock[0] - T0))
        clock[0] += 3
    # the next pass twice, then 10, 20, ... 60 s apart (to the next pass after), then every 60 s: the same times on every run of this test
    assert tried[:10] == [0, 3, 6, 18, 39, 69, 111, 162, 222, 282] and [ghrelay.backoff(n) for n in (1, 2, 3, 4, 8, 9, 50)] == [0, 0, 10, 20, 60, 60, 60]
    assert all(b - a <= ghrelay.BACKOFF_MOST + 3 for a, b in zip(tried, tried[1:])) and len(tried) > ghrelay.MAX_TRIES + 10
    entry = notes(state)["journal"]
    assert [(e["id"], e["state"], e["tries"]) for e in entry.values()] == [(ghrelay.token_id(proof), "waiting", len(tried))]
    # the endpoint answers: carried on the next try, and the line says how many it took
    del relays.answers[ghrelay.token_id(proof)]
    [(at, [line])] = run(clock, clock[0] + 70, stop=bool)
    assert f" {ghrelay.token_id(proof)} ok sig=s1,s2 " in line and f" tries={len(tried) + 1} queued_at=" in line and at - tried[-1] <= 63
    saved = notes(state)
    assert [e["state"] for e in saved["journal"].values()] == ["confirmed"] and saved["tries"] == {} and saved["hold"] == {}
    assert run(clock, clock[0] + 30) == []                          # once


def test_a_token_past_its_hour_ends_with_the_reason_and_a_refusal_is_final_at_once(world):
    gh, relays, state, clock = world
    old, refused = token(PAY, iat=int(T0) - 4000, exp=int(T0) - 3700), token(fund_aud(9))
    gh.search = ["octo/widgets"]
    gh.comment("octo/widgets", 12, ghrelay.token_comment("proof", old), at=T0 - 3000)        # still in the comments the relay reads (70 minutes)
    gh.comment("octo/widgets", 9, ghrelay.token_comment("fund", refused, TERMS), at=T0)
    relays.answers[ghrelay.token_id(old)] = {"ok": False, "kind": "pay", "why": "OSError: the endpoint did not answer", "retry": True, "transient": True}
    relays.answers[ghrelay.token_id(refused)] = {"ok": False, "kind": "fund", "why": "this commenter may not spend that balance"}
    logged = run(clock, T0 + 900)
    lines = [ln for _at, got in logged for ln in got]
    # the refusal: logged on the first pass with its reason, sent once, never again
    assert logged[0] == (0, [f"knos-relay fund octo/widgets#9 {ghrelay.token_id(refused)} fail this commenter may not spend that balance"])
    assert sum(c[1] == refused for c in relays.calls) == 1
    # the expired one: the chain would not take it any more, so MAX_TRIES passes and then its reason, in words
    assert sum(c[1] == old for c in relays.calls) == ghrelay.MAX_TRIES and lines[-1].endswith(
        f"fail OSError: the endpoint did not answer (tried {ghrelay.MAX_TRIES} times until the token expired; run the workflow again for a fresh token)")
    journal = {e["id"]: e for e in notes(state)["journal"].values()}
    assert (journal[ghrelay.token_id(refused)]["state"], journal[ghrelay.token_id(refused)]["why"]) == ("refused", "this commenter may not spend that balance")
    assert journal[ghrelay.token_id(old)]["state"] == "expired" and ghrelay.expires(old) == T0 - 100 and ghrelay.expires("no token") is None


def test_what_the_relay_counts_as_the_clusters_failure_and_what_as_a_verdict():
    from knos import chain
    from knos.settle.v2 import relay
    for why in (OSError("connection reset"), TimeoutError("sig not confirmed within 60s"), chain.RpcError("Transaction simulation failed: Blockhash not found"),
                chain.RpcError("Node is behind by 150 slots"), chain.RpcError("Node is unhealthy"), chain.RpcError("Internal error"),
                chain.RpcError("block height exceeded")):
        assert relay.transient(why) and relay._failed("pay", why).get("retry") is True, why
    from knos.settle.v2 import pay
    verdict = relay._failed("fund", chain.RpcError("transaction failed: {'InstructionError': [1, {'Custom': 94}]}"))
    assert "retry" not in verdict and verdict["why"] == f"{pay.ERRORS[94]} (error 94)"       # the program's own answer: final


# -- 4. GitHub's rate limits -------------------------------------------------------------------------------------------------
def test_when_github_says_slow_down_nothing_is_asked_until_the_time_it_named_and_no_verdict_is_lost(world):
    gh, relays, state, clock = world
    proof, during = token(PAY), token(fund_aud(4), iat=int(T0) + 30)
    gh.search = ["octo/widgets"]
    gh.comment("octo/widgets", 12, ghrelay.token_comment("proof", proof), at=T0)
    assert len(run(clock, T0)) == 1
    clock[0] = T0 + 3
    gh.limit = {"Retry-After": "120"}                               # GitHub's secondary limit: stay away for two minutes
    gh.comment("octo/widgets", 4, ghrelay.token_comment("fund", during, TERMS), at=T0 + 30)
    n = len(gh.asked)
    assert run(clock, T0 + 6) == []
    first = len(gh.asked) - n
    assert first > 0 and ghrelay._HUB.rest == T0 + 3 + 120
    gh.limit = None                                                 # (GitHub would answer again; the relay keeps its word all the same)
    n = len(gh.asked)
    assert run(clock, T0 + 120) == [] and len(gh.asked) == n       # 38 passes, not one request
    [(at, [line])] = run(clock, T0 + 200, stop=bool)
    assert at == 123 and f" {ghrelay.token_id(during)} ok " in line     # the first pass after the time GitHub named
    # the hourly limit: nothing remains until the reset GitHub names; and a 403 that names no limit rests nothing
    hub = ghrelay.Hub(gh.open, clock=lambda: clock[0])
    gh.limit = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(int(clock[0]) + 900)}
    with pytest.raises(RuntimeError, match="GitHub answered 403"):
        hub.get("repos/octo/widgets")
    assert hub.rest == clock[0] + 900
    with pytest.raises(RuntimeError, match="GitHub asked for 900 more seconds without requests"):
        hub.send("repos/x/y/issues/1/comments", {"body": "b"})
    plain = ghrelay.Hub(gh.open, clock=lambda: clock[0])
    gh.limit = {}
    with pytest.raises(RuntimeError):
        plain.get("repos/octo/private")
    assert plain.rest == 0


def test_a_verdict_github_would_not_take_during_a_limit_is_posted_when_the_limit_ends(world):
    gh, relays, state, clock = world
    proof = token(PAY)
    gh.search = ["octo/widgets"]
    gh.comment("octo/widgets", 12, ghrelay.token_comment("proof", proof), at=T0)
    real = relays.__call__

    def carried(*a, **kw):          # the limit starts while the token is on its way to Solana
        gh.limit = {"Retry-After": "60"}
        return real(*a, **kw)
    ghrelay.relay_one = carried     # (the fixture's monkeypatch puts the module back)
    [(at, [line])] = run(clock, T0)
    assert gh.log() == [] and notes(state)["unposted"] == [line]    # carried, and its line kept
    gh.limit = None
    run(clock, T0 + 70)
    assert gh.log() == [line] and "unposted" not in notes(state) and len(relays.calls) == 1


# -- 5. a workflow that queued ------------------------------------------------------------------------------------------------
def test_a_workflow_that_waited_for_a_runner_shows_as_queue_seconds_and_the_relays_own_wait_stays_small(world):
    """The relay cannot shorten what happens before the token's comment. It measures it: the line of a payment whose
    workflow waited 20 minutes for a runner says so, and its own part is a pass."""
    gh, relays, _state, clock = world
    proof = token(PAY, repository="octo/widgets", run_id="5550001", run_attempt="1")
    gh.search = ["octo/widgets"]
    gh.runs["octo/widgets/5550001"] = {"created_at": ghrelay._stamp(T0 - 1230), "run_started_at": ghrelay._stamp(T0 - 22), "run_attempt": 1}
    gh.comment("octo/widgets", 12, ghrelay.token_comment("proof", proof), at=T0 - 2)
    [(_at, [line])] = run(clock, T0)
    assert " queue=1208 workflow=20 wait=2 chain=0 " in line and line.endswith(" t=2")


# -- the journal: written before the send, and a kill between send and confirmation --------------------------------------------
def test_a_token_is_in_the_notes_before_it_is_sent_and_a_killed_pass_loses_nothing(world):
    gh, relays, state, clock = world
    first, second = token(fund_aud(1)), token(fund_aud(2), iat=int(T0) + 1)
    gh.search = ["octo/widgets"]
    gh.comment("octo/widgets", 1, ghrelay.token_comment("fund", first, TERMS), at=T0)
    gh.comment("octo/widgets", 2, ghrelay.token_comment("fund", second, TERMS), at=T0)
    seen_at_send = []

    def killed(ledger, payer, kind, token_, terms=None):
        saved = notes(state)
        seen_at_send.append(([e["state"] for e in saved["journal"].values() if e["id"] == ghrelay.token_id(token_)], len(saved["seen"])))
        if token_ == second:
            raise KeyboardInterrupt("the runner was stopped")       # not an error the pass catches: the process ends here
        return relays(ledger, payer, kind, token_, terms)
    ghrelay.relay_one = killed
    with pytest.raises(KeyboardInterrupt):
        ghrelay.once(Ledger(), PAYER, now=T0, crank=False)
    assert seen_at_send == [(["sending"], 0), (["sending"], 1)]     # each was written down before its send; the first one's answer too
    saved = notes(state)
    assert sorted(e["state"] for e in saved["journal"].values()) == ["confirmed", "sending"] and len(saved["seen"]) == 1
    assert not list(state.parent.glob("*.tmp"))                     # the notes are moved into place whole
    # the next pass (the same run, or the one after): the first is not sent again, the second is
    ghrelay.relay_one = relays
    clock[0] = T0 + 3
    [(_at, [line])] = run(clock, T0 + 3)
    assert [c[1] for c in relays.calls] == [first, second] and f" {ghrelay.token_id(second)} ok " in line and " tries=2 " in line
    assert sorted(e["state"] for e in notes(state)["journal"].values()) == ["confirmed", "confirmed"]


def test_a_relay_killed_after_the_chain_took_the_token_sends_it_again_and_nobody_is_paid_twice(monkeypatch, tmp_path):
    """On LiteSVM, knos_pay and knos_oidc as built: the paying transaction lands, the process ends before it noted or
    logged anything, and the next pass sends the same token again. The chain's single-use marker answers "done":
    the payee holds the payment once, the fee account its fee once, and the log has one line."""
    pytest.importorskip("solders.litesvm")
    from _pay2 import Chain
    from solders.keypair import Keypair
    from test_relay2 import JWKS, TERMS as terms, Net, faucet_jwt, pay_jwt, user

    from knos.settle import relay as relay1
    from knos.settle.v2 import pay
    from knos.settle.v2 import relay as relay2
    c = Chain()
    net, gh = Net(c), GitHub()
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    gh.issues[HOME] = [{"number": 1, "state": "open", "labels": [ghrelay.LOG_LABEL]}]
    monkeypatch.setattr(ghrelay, "_HUB", ghrelay.Hub(gh.open, clock=c.now))
    monkeypatch.setattr(ghrelay, "_LOG", {})
    monkeypatch.setattr(ghrelay, "_state_path", lambda: tmp_path / "ghrelay.json")
    monkeypatch.setattr(relay1, "fetch_jwks", lambda issuer: JWKS[issuer])
    monkeypatch.setattr(relay2, "_KEPT", {})
    monkeypatch.setenv("KNOS_RELAY_REPOS", "octo/widgets")
    monkeypatch.setenv("KNOS_NO_SAS", "1")
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    org, repo, payee, wallet = user(), user(), user(), Keypair().pubkey()
    gh.comment("octo/widgets", 7, ghrelay.token_comment("fund", faucet_jwt(c, 7, org, repo), terms), at=c.now())
    assert len(ghrelay.once(net, c.payer, now=c.now(), crank=False)) == 1
    c.warp(60)
    proof = pay_jwt(c, repo, 7, payee, wallet)
    gh.comment("octo/widgets", 12, ghrelay.token_comment("proof", proof), at=c.now())
    real = ghrelay.relay_one

    def killed(*a, **kw):
        real(*a, **kw)
        raise KeyboardInterrupt("the runner was stopped")
    monkeypatch.setattr(ghrelay, "relay_one", killed)
    with pytest.raises(KeyboardInterrupt):
        ghrelay.once(net, c.payer, now=c.now(), crank=False)
    got, fee = pay.ata(wallet, pay.faucet_mint()), pay.ata(pay.FEE_OWNER, pay.faucet_mint())
    assert c.balance(got) == 4_875_000 and c.balance(fee) == 125_000 and len(gh.log()) == 1      # paid; only the funding has its line
    saved = notes(tmp_path / "ghrelay.json")
    assert [e["state"] for e in saved["journal"].values() if e["id"] == ghrelay.token_id(proof)] == ["sending"]
    monkeypatch.setattr(ghrelay, "relay_one", real)
    c.warp(3)
    sent = net.txs
    # the chain shows it done. This relay had sent it (its notes say so), so nobody else will log it: the line is
    # written at once, not kept back as the line of a token another run carried is (ALREADY_WAIT)
    [line] = ghrelay.once(net, c.payer, now=c.now(), crank=False)
    assert f" {ghrelay.token_id(proof)} ok " in line and " tries=2 " in line and line.count("(another relayer carried it first)") == 1
    assert " sent_at=- confirmed_at=- " in line                     # it sent nothing this time, and says no time it did not measure
    assert c.balance(got) == 4_875_000 and c.balance(fee) == 125_000                             # the second send moved nothing
    assert relay2.submit(net, c.payer, proof, None, JWKS, now=c.now()).get("already") is True    # and a third is answered the same, from reads
    assert net.txs - sent <= 1 and ghrelay.once(net, c.payer, now=c.now() + 3, crank=False) == [] and len(gh.log()) == 2


# -- the status line ------------------------------------------------------------------------------------------------------------
def test_the_status_line_is_one_comment_rewritten_and_says_what_waits(world):
    gh, relays, state, clock = world
    ok, waits, refused = token(PAY), token(fund_aud(2), iat=int(T0) + 1), token(fund_aud(3), iat=int(T0) + 2)
    gh.search = ["octo/widgets"]
    for n, (kind, t) in enumerate((("proof", ok), ("fund", waits), ("fund", refused)), 1):
        gh.comment("octo/widgets", n, ghrelay.token_comment(kind, t, TERMS if kind == "fund" else None), at=T0)
    relays.answers[ghrelay.token_id(waits)] = {"ok": False, "kind": "fund", "why": "TimeoutError: not confirmed", "retry": True, "transient": True}
    relays.answers[ghrelay.token_id(refused)] = {"ok": False, "kind": "fund", "why": "the balance does not hold that much"}
    assert ghrelay.publish_status(T0) is None                       # before the first pass there is nothing to say
    run(clock, T0 + 60)
    line = ghrelay.publish_status(T0 + 60)
    assert re.fullmatch(rf"knos-relay status - - ok at={ghrelay._stamp(T0 + 60)} round=\d+ tokens=0 waiting=1 oldest=60 retried=4 refused=1", line), line
    said = gh.log()[-1].split("\n")
    assert said[0] == line and len(gh.log()) == 3                   # the paid token's line, the refusal's, and the status
    # under the counts, each round the relay took up, newest first: where, the first of its id, its state and its seconds
    ids = [ghrelay.token_id(t)[:8] for t in (waits, ok, refused)]
    assert said[1:] == [f"knos-relay round octo/widgets#2 {ids[0]} ok order=- state=waiting seconds=60 kind=fund",
                        f"knos-relay round octo/widgets#1 {ids[1]} ok order=- state=confirmed seconds=0 kind=proof",
                        f"knos-relay round octo/widgets#3 {ids[2]} ok order=- state=refused seconds=0 kind=fund"]
    comment = notes(state)["status_comment"]
    run(clock, T0 + 120)
    again = ghrelay.publish_status(T0 + 120)
    assert " waiting=1 oldest=120 " in again and gh.log()[-1].split("\n")[0] == again and len(gh.log()) == 3 and notes(state)["status_comment"] == comment
    assert f" {ids[0]} ok order=- state=waiting seconds=120 " in gh.log()[-1]
    assert ("PATCH", f"repos/{HOME}/issues/comments/{comment}", 200) in gh.asked
    # a line that names no token id never answers a job that waits for its token
    assert ghrelay.wait_for(ghrelay.token_id(waits), HOME, 0.02, every=0.01) is None
    # the comment was deleted: a new one is posted; GitHub down: None, and nothing is raised
    gh.comments[HOME] = [c for c in gh.comments[HOME] if c["id"] != comment]
    assert ghrelay.publish_status(T0 + 180) and notes(state)["status_comment"] != comment
    gh.limit = {"Retry-After": "30"}
    assert ghrelay.publish_status(T0 + 240) is None


def test_only_the_log_repositorys_own_worker_writes_a_status_line(world, monkeypatch):
    gh, _relays, _state, clock = world
    run(clock, T0)
    worker = {"GITHUB_REPOSITORY": HOME, "GITHUB_WORKFLOW_REF": f"{HOME}/.github/workflows/worker.yml@refs/heads/main"}
    assert ghrelay.publishes_status(worker) and ghrelay.publishes_status({"KNOS_RELAY_STATUS": "1"})
    assert not ghrelay.publishes_status({}) and not ghrelay.publishes_status({**worker, "KNOS_RELAY_STATUS": "0"})
    assert not ghrelay.publishes_status({**worker, "GITHUB_WORKFLOW_REF": f"{HOME}/.github/workflows/tests.yml@refs/heads/main"})      # the same repository's tests
    assert not ghrelay.publishes_status({"GITHUB_REPOSITORY": "someone/fork", "GITHUB_WORKFLOW_REF": "someone/fork/.github/workflows/worker.yml@refs/heads/main"})
    monkeypatch.delenv("KNOS_RELAY_STATUS")
    monkeypatch.delenv("GITHUB_WORKFLOW_REF", raising=False)
    n = len(gh.asked)
    assert ghrelay.publish_status(T0) is None and len(gh.asked) == n and gh.log() == []      # a relay of one's own: nothing is asked of GitHub


def test_serve_publishes_the_status_once_a_minute_and_the_worker_command_does_too(monkeypatch):
    from knos import flow
    said = []
    monkeypatch.setattr(ghrelay, "once", lambda ledger, payer, crank=True: [])
    monkeypatch.setattr(ghrelay, "publish_status", lambda now=None: said.append("status"))      # (which itself writes only for the log's own worker)
    monkeypatch.setenv("GH_TOKEN", "t")
    clock, sleep = tw._clock()
    ghrelay.serve(125, every=3.0, ledger="ledger", payer="payer", clock=clock, sleep=sleep)
    assert len(said) == 3                                           # at 0, 60 and 120 s
    said.clear()
    clock, sleep = tw._clock()
    assert flow.relay(serve=125, ghrelay=ghrelay, ledger="ledger", payer="payer", clock=clock, sleep=sleep, env={"GH_TOKEN": "t"}) == 0
    assert len(said) == 3
