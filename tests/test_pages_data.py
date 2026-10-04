"""The public record as static files (scripts/pages_data.py), counted from recorded inputs: the escrows' log lines as
network_stats reads them, a relay log, GitHub's answers as a dict. No network, no chain.

The scenario (`scenario()`): funder 501 (a Balance) funds five jobs in octo/widgets, funder 502 one in acme/gadgets,
and Knos's own account funds one. They end as: paid to alice (real), refunded after bob's merge (merged but unpaid),
paid in test USDC, paid to the funder's own account, paid to Knos's own account.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest
from solders.pubkey import Pubkey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import network_stats  # noqa: E402
import pages_data  # noqa: E402
from agent_pr_index import build as build_index  # noqa: E402

from knos.settle.v2 import pay as pay2  # noqa: E402

PAY2 = str(pay2.PAY_ID)
USDC = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
KNOS = 142920951
OWN = frozenset({KNOS})
T0 = 1_790_000_000
NOW = T0 + 10_000
BAL = str(Pubkey.from_bytes(bytes([7]) * 32))
TERMS = '{"accept":"","checks":[{"app":-1,"name":"test"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":[],"reserve":7,"v":1}'


def iso(t: int) -> str:
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tx(at: int, sig: str, *lines: str, keys=(USDC,)) -> dict:
    logs = [f"Program {PAY2} invoke [1]", *[f"Program log: {x}" for x in lines], f"Program {PAY2} success"]
    return {"signature": sig, "blockTime": at, "meta": {"err": None, "logMessages": logs}, "transaction": {"message": {"accountKeys": ["relayer", *keys, PAY2]}}}


def events(*txs: dict) -> list[dict]:
    out = []
    for t in txs:
        out += [{**ev, "tx": t["signature"]} for ev in network_stats.events_of(t)]
    return sorted(out, key=lambda e: e["at"])


def fund(at, sig, repo, issue, by, amount=5_000_000, faucet=0, source=BAL, terms=True):
    return tx(at, sig, f"knos2:funded repo={repo} issue={issue} amount={amount} mode=0 by={by} source={source} faucet={faucet}", *([f"knos2:terms {TERMS}"] if terms else []))


def paid(at, sig, repo, issue, payee, net=4_875_000, fee=125_000):
    return tx(at, sig, f"knos2:paid repo={repo} issue={issue} payee={payee} amount={net} fee={fee} to=W{payee}")


def scenario() -> list[dict]:
    return events(
        tx(T0, "bal501", "knos2:balance owner=501 authority=A501 mint=" + USDC),
        fund(T0 + 10, "f1", 10, 1, 501), paid(T0 + 1000, "pay1", 10, 1, 601),
        fund(T0 + 20, "f2", 10, 2, 501),
        tx(T0 + 5000, "ref2", "knos2:refunded repo=10 issue=2 amount=5000000"),
        fund(T0 + 30, "f3", 10, 3, 501, faucet=1), paid(T0 + 2000, "pay3", 10, 3, 601),
        fund(T0 + 40, "f4", 10, 4, 501), paid(T0 + 3000, "pay4", 10, 4, 501),
        fund(T0 + 50, "f5", 10, 5, KNOS, source=str(Pubkey.from_bytes(bytes([8]) * 32))), paid(T0 + 3500, "pay5", 10, 5, 601),
        tx(T0 + 60, "bal502", "knos2:balance owner=502 authority=A502 mint=" + USDC),
        fund(T0 + 70, "f6", 20, 1, 502, source=str(Pubkey.from_bytes(bytes([9]) * 32))), paid(T0 + 4000, "pay6", 20, 1, 603),
    )


NAMES = {"users": {501: "funder-one", 502: "funder-two", 601: "alice", 602: "bob", 603: "carol", KNOS: "knos-team"}, "repos": {10: "octo/widgets", 20: "acme/gadgets"}}
COMMENTS = [{"created_at": iso(T0 + 1010), "body": "knos-relay pay octo/widgets#11 0123456789abcdef ok sig=pay1 queue=3 workflow=40 wait=2 chain=4 note=paid t=8\n"
                                                    "knos-relay pay octo/widgets#13 fedcba9876543210 fail this merge cannot be paid\nknos-relay settle - - ok sig=x note=crank"},
            {"created_at": iso(T0 + 4010), "body": "knos-relay pay acme/gadgets#3 aaaaaaaaaaaaaaaa ok asked=%d sig=pay6 note=paid t=30" % (T0 + 3900)}]


def pull(author_id, login, merged, body, sha):
    return {"user": {"id": author_id, "login": login}, "merged_at": iso(merged), "closed_at": iso(merged), "head": {"sha": sha}, "body": body,
            "base": {"ref": "main", "repo": {"full_name": "octo/widgets", "default_branch": "main"}}}


def github():
    def ok(at):
        return {"check_runs": [{"name": "test", "status": "completed", "conclusion": "success", "completed_at": iso(at), "details_url": ""}]}
    data = {"repos/octo/widgets/pulls/11": pull(601, "alice", T0 + 990, "Fixes #1", "a" * 40), f"repos/octo/widgets/commits/{'a' * 40}/check-runs?per_page=100": ok(T0 + 900),
            "repos/octo/widgets/pulls/12": pull(602, "bob", T0 + 4000, "Fixes #2", "b" * 40), f"repos/octo/widgets/commits/{'b' * 40}/check-runs?per_page=100": ok(T0 + 3900),
            "repos/octo/widgets/pulls/13": pull(601, "alice", T0 + 4100, "Fixes #9", "c" * 40), f"repos/octo/widgets/commits/{'c' * 40}/check-runs?per_page=100": {"check_runs": []},
            "repos/octo/widgets/issues/2/timeline?per_page=100": [{"event": "labeled"}, {"event": "cross-referenced", "source": {"issue": {
                "number": 12, "pull_request": {}, "repository": {"full_name": "octo/widgets"}}}}]}

    def get(path):
        return data[path]
    return get


def build(evs=None, get=None, **kw):
    return pages_data.build(scenario() if evs is None else evs, COMMENTS, get, kw.pop("index", None), kw.pop("accounts", None), pages_data.Names(**NAMES), NOW, own=OWN, own_wallets=frozenset(), **kw)


def load(files, path):
    return json.loads(files[path])


# ---- every file says where it came from -----------------------------------------------------------------------------
def test_every_file_carries_its_source_and_when_it_was_generated():
    files = build(get=github())
    for path, text in files.items():
        if path.endswith(".json"):
            data = json.loads(text)
            assert data["generated"] == iso(NOW) and data["source"]["summary"], path
            assert data["source"]["chain"]["events"] == len(scenario())
    assert {"bounties.json", "bounties.rss", "u/alice.json", "u/alice.html", "r/octo/widgets.json", "r/octo/widgets.html", "badge/u/alice.json", "badge/r/octo/widgets.json",
            "rank/earners.json", "rank/earners.html", "rank/funders.json", "rank/funders.html", "rank/agents.json", "rank/agents.html", "latency.json",
            "operations.json", "OPERATIONS.md", "records.json"} <= set(files)


def test_a_build_with_nothing_measured_has_every_file_and_says_so(tmp_path):
    assert pages_data.main(["--out", str(tmp_path), "--empty"]) == 0
    got = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert {"bounties.json", "bounties.rss", "rank/earners.json", "rank/agents.html", "latency.json", "operations.json", "OPERATIONS.md", "records.json"} <= got
    assert json.loads((tmp_path / "bounties.json").read_text())["count"] == 0
    agents = json.loads((tmp_path / "rank/agents.json").read_text())
    assert agents["entries"] == [] and "not measured" in agents["note"]
    assert json.loads((tmp_path / "latency.json").read_text())["merge_to_paid"]["all_time"]["n"] == 0
    assert "No runs to show" in (tmp_path / "OPERATIONS.md").read_text()


# ---- bounties --------------------------------------------------------------------------------------------------------
def test_an_open_funded_task_is_listed_with_its_terms_in_words_and_as_json_and_its_funders_record():
    key = Pubkey.from_bytes(bytes([8]) * 32)
    evs = scenario() + events(fund(T0 + 80, "f7", 20, 2, 0, terms=True, source=str(key)), fund(T0 + 90, "f8", 20, 3, 502, faucet=1, source=BAL))
    acct = lambda deadline, faucet=False: type("Job", (), {"deadline": deadline, "mint": Pubkey.from_string(USDC), "faucet": faucet})()      # noqa: E731
    accounts = {str(pay2.job_pda(20, 2, key)): acct(NOW + 86_400), str(pay2.job_pda(20, 3, Pubkey.from_string(BAL))): acct(NOW - 5, True)}
    files = build(evs, github(), accounts=accounts)
    data = load(files, "bounties.json")
    assert data["count"] == 1 and data["expired_not_listed"] == 1
    b = data["bounties"][0]
    assert (b["repository"], b["issue"], b["amount"], b["mint_kind"], b["currency"], b["deployment"]) == ("acme/gadgets", 2, 5_000_000, "real", "USDC", "second")
    assert b["url"] == "https://github.com/acme/gadgets/issues/2" and b["deadline"] == iso(NOW + 86_400) and b["reserved_until"] is None
    assert b["terms"]["json"]["checks"] == [{"app": -1, "name": "test"}] and "test" in " ".join(b["terms"]["words"])
    assert b["funder"]["id"].startswith("wallet:") and b["funder"]["login"] is None and b["funder"]["record"] is None
    rss = files["bounties.rss"]
    assert rss.startswith("<?xml") and "<guid isPermaLink=\"false\">f7</guid>" in rss and "5.00 USDC for acme/gadgets#2" in rss


def test_without_the_programs_accounts_no_deadline_is_invented():
    evs = scenario() + events(fund(T0 + 80, "f7", 20, 2, 502))
    data = load(build(evs), "bounties.json")
    assert data["count"] == 1 and data["bounties"][0]["deadline"] is None and "not measured" in data["note"]
    assert data["bounties"][0]["funder"]["id"] == "gh:502" and data["bounties"][0]["funder"]["login"] == "funder-two"
    assert data["bounties"][0]["funder"]["record"] == "u/funder-two.json"


def test_third_party_text_is_escaped_in_the_feed_and_the_pages():
    evs = events(fund(T0, "fx", 20, 1, 502, terms=False))
    files = pages_data.build(evs, None, None, None, None, pages_data.Names(users={502: "x"}, repos={20: "a/b"}), NOW, own=OWN, own_wallets=frozenset())
    assert "<script" not in files["bounties.rss"]
    assert pages_data.esc('<img src=x onerror="1">') == "&lt;img src=x onerror=&quot;1&quot;&gt;"
    page = pages_data.page("<b>t</b>", "", {"source": {"summary": "<i>s</i>"}, "generated": "g"})
    assert "<b>t</b>" not in page and "<i>s</i>" not in page


# ---- accounts and repositories -------------------------------------------------------------------------------------
def test_an_earners_record_counts_each_kind_of_money_apart():
    files = build(get=github())
    a = load(files, "u/alice.json")
    assert a["login"] == "alice" and a["github_id"] == 601
    e = a["as_earner"]
    assert e["paid_merges"] == 3 and e["amounts"] == {"real": {"count": 1, "amount": 4_875_000}, "test": {"count": 1, "amount": 4_875_000},
                                                       "self": {"count": 0, "amount": 0}, "own": {"count": 1, "amount": 4_875_000}}
    assert e["distinct_funders"] == 1 and e["distinct_funders_real"] == 1          # Knos's own funding is not a funder
    assert e["refusals_at_merge"] == 1                                            # the relay log's `fail` on alice's pull request 13
    assert e["first"] == iso(T0 + 1000) and e["last"] == iso(T0 + 3500)
    assert a["badge"]["readme"].startswith("[![paid through Knos](https://img.shields.io/endpoint?url=https%3A%2F%2F")
    assert load(files, "u/carol.json")["as_earner"]["amounts"]["real"]["count"] == 1


def test_a_funders_record_has_funded_paid_refunded_and_the_merge_that_was_not_paid():
    f = load(build(get=github()), "u/funder-one.json")["as_funder"]
    assert [f["funded"][k]["count"] for k in ("real", "test", "self", "own")] == [2, 1, 1, 0]        # issues 1 and 2 (real), 3 (test), 4 (paid to the funder)
    assert f["paid"]["real"] == {"count": 1, "amount": 4_875_000} and f["paid"]["self"]["count"] == 1 and f["paid"]["test"]["count"] == 1
    assert f["refunded"]["real"] == {"count": 1, "amount": 5_000_000}
    assert f["reliability"] == {"n": 2, "k": 1, "share": 0.5, "ci95": [0.0945, 0.9055]}  # real jobs that ended: one paid, one refunded; the self-paid one is not counted
    assert f["merged_unpaid"] == [{"repository": "octo/widgets", "issue": 2, "amount": 5_000_000, "bucket": "real", "pull_request": 12, "author": "bob",
                                   "merged_at": iso(T0 + 4000), "refunded_at": iso(T0 + 5000)}]
    # median time from the checks passing to the merge, over the pull requests behind its jobs: only pull request 11 (90 s) and 12 (100 s)
    assert f["review"]["seconds"]["n"] == 2 and f["review"]["seconds"]["p50"] == 95


def test_a_refund_after_a_merge_is_found_on_the_authors_record_too_and_a_merge_after_the_refund_is_not_held_against_anyone():
    files = build(get=github())
    assert [x["pull_request"] for x in load(files, "u/alice.json")["merged_but_unpaid_to_me"]] == []
    # bob wrote the merged pull request: he has no job, so no file; the funder's record and the repository's carry it
    assert load(files, "r/octo/widgets.json")["as_funder"]["merged_unpaid"][0]["author"] == "bob"
    evs = [dict(e, at=T0 + 3000) if e["event"] == "refunded" else e for e in scenario()]            # refunded before bob's merge at T0 + 4000
    assert load(build(evs, github()), "u/funder-one.json")["as_funder"]["merged_unpaid"] == []


def test_what_needs_github_is_null_when_github_was_not_asked():
    files = build(get=None)
    a = load(files, "u/funder-one.json")
    assert a["as_funder"]["merged_unpaid"] is None and a["as_funder"]["review"]["note"] == "not measured: GitHub was not asked"
    assert a["as_funder"]["review"]["seconds"]["n"] == 0
    assert load(files, "u/alice.json")["as_earner"]["refusals_at_merge"] is None           # who wrote the pull requests is GitHub's to say
    assert load(files, "r/octo/widgets.json")["as_earner"]["refusals_at_merge"] == 1       # the repository's name is in the log line itself


def test_a_repositorys_record_is_the_same_per_repository():
    r = load(build(get=github()), "r/octo/widgets.json")
    assert r["repository"] == "octo/widgets" and r["github_id"] == 10
    assert r["as_earner"]["paid_merges"] == 4 and r["as_earner"]["payees"] == 1 and r["as_earner"]["amounts"]["self"]["count"] == 1
    assert r["badge"]["readme"].endswith("(https://drexthealpha.github.io/Knos/r/octo/widgets.html)")


def test_an_id_github_does_not_name_gets_no_file_and_is_counted():
    names = pages_data.Names(users={601: "alice"}, repos={10: "octo/widgets"})
    files = pages_data.build(scenario(), COMMENTS, None, None, None, names, NOW, own=OWN, own_wallets=frozenset())
    recs = load(files, "records.json")
    assert recs["accounts"] == ["alice"] and recs["repositories"] == ["octo/widgets"]
    assert recs["unnamed_accounts"] == 4 and recs["unnamed_repositories"] == 1


def test_names_come_from_github_and_only_in_a_form_that_is_safe_as_a_path():
    asked = []

    def get(path):
        asked.append(path)
        return {"user/1": {"login": "good-name"}, "user/2": {"login": "../etc"}, "user/3": {"login": "a/b"}, "repositories/9": {"full_name": "o/r"},
                "repositories/8": {"full_name": "o/.."}, "repositories/7": {"full_name": "o/x.git"}}[path]
    n = pages_data.Names()
    n.resolve(get, {1, 2, 3, 4}, {9, 8, 7})
    assert n.users == {1: "good-name"} and n.repos == {9: "o/r"}
    n.resolve(get, {1, 2}, {9})
    assert len(asked) == 7                                                                  # the ones refused are not asked about again
    assert not any(pages_data.safe_repo(x) for x in ("../x", "a/..", "a/b/c", "a/", "/b", "-a/b", "a/b c", "a/x.git"))
    assert pages_data.safe_repo("octo/widgets.js") and pages_data.safe_repo("o/.github")


def test_a_file_outside_the_output_folder_is_refused(tmp_path):
    with pytest.raises(ValueError):
        pages_data.write({"../x.json": "{}"}, tmp_path / "site")
    pages_data.write({"u/a.json": "{}"}, tmp_path / "site")
    assert (tmp_path / "site" / "u" / "a.json").read_text() == "{}"


# ---- badges ----------------------------------------------------------------------------------------------------------
def test_badges_are_in_the_shields_endpoint_format_and_count_real_money_only():
    files = build(get=github())
    repo = load(files, "badge/r/octo/widgets.json")
    assert repo["schemaVersion"] == 1 and repo["label"] == "pays on merge" and repo["message"] == "1 paid, median 10 s" and repo["color"] == "brightgreen"
    assert load(files, "badge/u/alice.json")["message"] == "1 paid" and load(files, "badge/u/alice.json")["label"] == "paid through Knos"
    assert load(files, "badge/u/carol.json")["message"] == "1 paid"
    assert load(files, "badge/u/funder-one.json")["message"] == "none yet"                    # a funder who was never paid
    assert load(files, "badge/u/knos-team.json")["message"] == "none yet"
    only_test = events(tx(T0, "b", "knos2:balance owner=501 authority=A mint=" + USDC), fund(T0 + 1, "f", 10, 1, 501, faucet=1), paid(T0 + 2, "p", 10, 1, 601))
    t = load(build(only_test), "badge/u/alice.json")
    assert t["message"] == "1 paid in test USDC" and t["color"] == "lightgrey"


# ---- ranks -----------------------------------------------------------------------------------------------------------
def test_earners_are_ranked_by_real_usdc_and_say_what_was_left_out():
    r = load(build(get=github()), "rank/earners.json")
    assert [(e["rank"], e["login"], e["paid_amount"], e["paid_merges"]) for e in r["entries"]] == [(1, "alice", 4_875_000, 1), (2, "carol", 4_875_000, 1)]
    assert r["left_out"] == {"test": 1, "self": 1, "own": 1}


def test_funders_are_ranked_with_their_reliability():
    r = load(build(get=github()), "rank/funders.json")
    first, second = r["entries"]
    assert (first["rank"], first["login"], first["paid_amount"], first["paid_jobs"], first["refunded_jobs"]) == (1, "funder-one", 4_875_000, 1, 1)
    assert first["reliability"]["share"] == 0.5 and first["merged_unpaid"] == 1
    assert (second["rank"], second["login"], second["reliability"]["share"], second["merged_unpaid"]) == (2, "funder-two", 1.0, 0)


def noise() -> list[dict]:
    """Everything that must not raise anyone's rank: test money to alice and carol, a funder paying their own account,
    Knos's own account funding and being paid, and a funder and a payee who only ever see such money."""
    return events(
        fund(T0 + 100, "n1", 10, 51, 502, faucet=1, source=str(Pubkey.from_bytes(bytes([9]) * 32))), paid(T0 + 6000, "np1", 10, 51, 603),       # test money to carol
        fund(T0 + 101, "n2", 20, 52, 502, source=str(Pubkey.from_bytes(bytes([9]) * 32))), paid(T0 + 6001, "np2", 20, 52, 502),                   # funder-two pays themselves
        fund(T0 + 102, "n3", 20, 53, KNOS, source=str(Pubkey.from_bytes(bytes([8]) * 32))), paid(T0 + 6002, "np3", 20, 53, 603),                  # Knos funds carol
        fund(T0 + 103, "n4", 20, 54, 502, source=str(Pubkey.from_bytes(bytes([9]) * 32))), paid(T0 + 6003, "np4", 20, 54, KNOS),                  # Knos is paid
        tx(T0 + 104, "nb", "knos2:balance owner=777 authority=A777 mint=" + USDC),
        fund(T0 + 105, "n5", 20, 55, 777, faucet=1), paid(T0 + 6004, "np5", 20, 55, 778),                                                         # only test money
        fund(T0 + 106, "n6", 20, 56, 777), paid(T0 + 6005, "np6", 20, 56, 777),                                                                    # only self-payment
    )


def test_a_rank_never_rises_from_test_money_self_payment_or_knos_own_accounts():
    base, polluted = build(), build(sorted(scenario() + noise(), key=lambda e: e["at"]))
    for name in ("earners", "funders"):
        a, b = load(base, f"rank/{name}.json"), load(polluted, f"rank/{name}.json")
        assert a["entries"] == b["entries"], name           # not one entry changed: not an amount, a count, a reliability or a position
        assert b["left_out"] != a["left_out"]               # what was left out is counted, not hidden
    ids = {e["github_id"] for e in load(polluted, "rank/earners.json")["entries"]}
    assert ids == {601, 603} and 778 not in ids and 777 not in ids and KNOS not in ids
    assert {e["funder"] for e in load(polluted, "rank/funders.json")["entries"]} == {"gh:501", "gh:502"}
    # Knos's own account is never ranked even when its money was real USDC and the payee is an outsider
    assert all(e["github_id"] != KNOS for e in load(polluted, "rank/funders.json")["entries"])
    # and the records say what each kind was
    assert load(polluted, "u/carol.json")["as_earner"]["amounts"]["test"]["count"] == 1 and load(polluted, "u/carol.json")["as_earner"]["amounts"]["own"]["count"] == 1


def test_a_mint_that_is_not_circles_is_test_money_and_real_is_never_assumed():
    other = events(fund(T0 + 1, "o1", 10, 1, 501), paid(T0 + 2, "o2", 10, 1, 601))
    other[0]["keys"] = ["relayer", PAY2]                                                       # the funding transaction names no USDC mint
    jobs = pages_data.jobs_of(other, OWN, frozenset())
    assert jobs[0]["mint_kind"] == "test" and jobs[0]["bucket"] == "test"
    assert pages_data.mint_kind({"faucet": False}, None) == "test"
    assert pages_data.mint_kind({"faucet": False}, ["x", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"]) == "real"
    assert pages_data.mint_kind({"faucet": True}, [USDC]) == "test"


def test_agents_are_ranked_by_the_indexs_false_claim_rate_with_intervals_and_the_month():
    def row(agent, repo, n, failed):
        return {"agent": agent, "repo": repo, "number": n, "sha": "s", "class": "failed" if failed else "passed", "failed_checks": ["test"] if failed else [], "phrase": "tests pass"}
    rows = [row("copilot", f"o/r{i}", 1, i < 3) for i in range(10)] + [row("devin", f"o/d{i}", 1, i < 1) for i in range(10)] + [row("codex", "o/x", 1, False)]
    index = build_index(rows, "2026-10-02", ["2026-06-04", "2026-10-01"], 5)
    r = load(build(index=index), "rank/agents.json")
    assert r["month"] == "2026-10" and r["window"] == ["2026-06-04", "2026-10-01"] and r["root"] == index["root"]
    got = [(e["rank"], e["agent"], e["repositories"], e["false_claim_rate"]) for e in r["entries"] if e["repositories"]]
    assert got == [(1, "codex", 1, 0.0), (2, "devin", 10, 0.1), (3, "copilot", 10, 0.3)]
    copilot = next(e for e in r["entries"] if e["agent"] == "copilot")
    assert copilot["ci95"] == [0.1078, 0.6032] and copilot["name"] == "GitHub Copilot coding agent"
    html = build(index=index)["rank/agents.html"]
    assert "2026-10" in html and "GitHub Copilot coding agent" in html and "30.0%" in html


# ---- latency ---------------------------------------------------------------------------------------------------------
def test_latency_is_the_spread_by_day_in_two_windows_with_the_split_the_log_allows():
    get = github()
    files = build(get=get)
    lat = load(files, "latency.json")
    m = lat["merge_to_paid"]["all_time"]
    # pay1: merged T0+990, paid T0+1000 = 10 s (relay t=8); pay6: asked T0+3900, paid T0+4000 = 100 s (t=30)
    assert (m["n"], m["p50"], m["p95"], m["p99"], m["slowest"]) == (2, 55, 100, 100, 100)
    assert m["by_day"] == {iso(T0)[:10]: {"n": 2, "p50": 55, "p95": 100, "slowest": 100}}
    assert m["split"]["relay_side"]["p50"] == 19 and m["split"]["github_side"]["n"] == 2 and m["split"]["github_side"]["p50"] == 36      # 2 s and 70 s
    assert m["split"]["queue"] == {"n": 1, "p50": 3, "p95": 3, "p99": 3, "slowest": 3} and m["split"]["chain"]["p50"] == 4
    assert m["split"]["workflow"]["p50"] == 40 and m["split"]["relay_wait"]["p50"] == 2
    assert lat["merge_to_paid"]["last_30_days"]["n"] == 2
    assert lat["comment_to_funded"]["all_time"]["n"] == 0


def test_the_last_thirty_days_leave_out_what_is_older():
    day = 86_400
    samples = [{"at": NOW - 40 * day, "seconds": 100, "t": None, "parts": {}, "sigs": []}, {"at": NOW - 2 * day, "seconds": 20, "t": None, "parts": {}, "sigs": []},
               {"at": NOW - 1 * day, "seconds": 40, "t": None, "parts": {}, "sigs": []}]
    out = pages_data.latency_json({"merge_to_paid": samples}, NOW, {"source": {}, "generated": "g"}, None)["merge_to_paid"]
    assert out["all_time"]["n"] == 3 and out["last_30_days"]["n"] == 2 and out["last_30_days"]["p50"] == 30 and out["all_time"]["slowest"] == 100
    assert len(out["all_time"]["by_day"]) == 3
    assert pages_data.spread([]) == {"n": 0, "p50": None, "p95": None, "p99": None, "slowest": None}
    assert pages_data.spread(range(1, 101))["p95"] == 95 and pages_data.spread(range(1, 101))["p99"] == 99


# ---- operations ------------------------------------------------------------------------------------------------------
def runs():
    mk = lambda n, conclusion, t: {"id": n, "status": "completed", "conclusion": conclusion, "created_at": iso(t), "html_url": f"https://github.com/drexthealpha/Knos/actions/runs/{n}"}  # noqa: E731
    return [mk(1, "success", NOW - 3600), mk(2, "failure", NOW - 7200), mk(3, "success", NOW - 10_800), mk(4, "cancelled", NOW - 14_400), mk(5, "success", NOW - 40 * 86_400),
            {"id": 6, "status": "in_progress", "conclusion": None, "created_at": iso(NOW - 60), "html_url": "x"}]


def test_operations_say_the_canarys_success_rate_and_each_incident_with_its_run():
    ops = pages_data.operations_json(lambda path: {"workflow_runs": runs()} if "/actions/workflows/canary.yml/runs" in path else [], NOW, OWN, {"source": {}, "generated": "g"})
    c = ops["canary"]
    assert c["runs"] == 6 and c["last_30_days"]["runs"] == 3 and c["last_30_days"]["failed"] == 1 and c["last_30_days"]["success_rate"]["k"] == 2
    assert c["all_runs_read"]["runs"] == 4 and c["all_runs_read"]["success_rate"]["share"] == 0.75        # the cancelled and the running one are not counted
    assert c["incidents"] == [{"at": iso(NOW - 7200), "conclusion": "failure", "run": "https://github.com/drexthealpha/Knos/actions/runs/2"}]
    md = pages_data.render_operations_md(ops)
    assert "actions/runs/2" in md and "75.0%" in md


def test_the_time_to_a_first_answer_counts_outside_issues_only_and_those_still_waiting():
    def item(n, uid, at, bot=False):
        return {"number": n, "created_at": iso(at), "user": {"id": uid, "type": "Bot" if bot else "User"}}
    items = [item(1, 900, T0), item(2, 901, T0 + 10), item(3, KNOS, T0 + 20), item(4, 77, T0 + 30, bot=True), item(5, 902, T0 + 40)]
    comments = {1: [{"created_at": iso(T0 + 100), "user": {"id": KNOS, "type": "User"}, "author_association": "OWNER"}],
                2: [{"created_at": iso(T0 + 50), "user": {"id": 901, "type": "User"}, "author_association": "NONE"},          # the author answering themselves
                    {"created_at": iso(T0 + 60), "user": {"id": 5, "type": "Bot"}, "author_association": "NONE"}],               # a bot
                5: [{"created_at": iso(T0 + 400), "user": {"id": 12, "type": "User"}, "author_association": "MEMBER"}]}

    def get(path):
        if "/issues?" in path:
            return items if path.endswith("page=1") else []
        return comments.get(int(path.split("/issues/")[1].split("/")[0]), [])
    r = pages_data.response_block(get, OWN)
    assert (r["n"], r["of"], r["waiting"], r["p50"], r["slowest"]) == (2, 3, 1, 230, 360)
    assert pages_data.response_block(None, OWN)["note"] == "not measured: GitHub was not asked"


def test_with_no_data_the_operations_document_says_so_and_shows_nothing_invented():
    md = pages_data.render_operations_md(pages_data.operations_json(None, 0, OWN, {"source": {"summary": ""}, "generated": None}))
    assert "No measurement has been made yet" in md and "No runs to show." in md and "No outside issue or pull request to show." in md
    assert not any(ch.isdigit() for ch in md.split("## How these are counted")[0].replace("30 minutes", "").replace("0.3", ""))
    committed = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    assert committed == md, "docs/OPERATIONS.md is the document for no data: run python scripts/pages_data.py --docs docs/OPERATIONS.md --empty --out <dir> with nothing measured"


def test_the_site_build_and_the_pages_workflow_write_these_files():
    net = (ROOT / ".github" / "workflows" / "network.yml").read_text(encoding="utf-8")
    assert net.index("scripts/network_stats.py --out") < net.index("scripts/pages_data.py --out _site --events _events.json --index _site/index.json")
    assert "--events-out _events.json" in net and '"scripts/pages_data.py"' in net
    assert "scripts/pages_data.py" in (ROOT / "scripts" / "build_site.sh").read_text(encoding="utf-8")


# ---- statements ------------------------------------------------------------------------------------------------------
def test_a_statement_file_lists_every_payment_to_an_account_and_every_payment_it_funded_and_adds_up_with_the_record():
    files = build(get=github())
    alice, f1 = load(files, "statements/alice.json"), load(files, "statements/funder-one.json")
    assert alice["login"] == "alice" and alice["github_id"] == 601 and alice["columns"][0] == "date" and alice["as_owner"] == []
    # alice was paid three times (real, test, and by Knos's own account): the same count and amounts as her record, by kind
    rec = load(files, "u/alice.json")["as_earner"]
    for kind in ("real", "test", "self", "own"):
        mine = [r for r in alice["as_seller"] if r["kind"] == kind]
        assert (len(mine), sum(r["amount_units"] for r in mine)) == (rec["amounts"][kind]["count"], rec["amounts"][kind]["amount"]), kind
    first = alice["as_seller"][0]
    assert first == {"month": "2026-09", "date": "2026-09-21", "time": "2026-09-21T14:30:00Z", "deployment": 2, "repository_id": 10, "repository": "octo/widgets", "issue": 1, "pull_request": None,
                     "payee_id": 601, "payee": "alice", "amount": "4.875000", "fee": "0.125000", "total": "5.000000", "currency": "USDC", "amount_units": 4_875_000, "fee_units": 125_000,
                     "total_units": 5_000_000, "funder_id": 501, "funder": "funder-one", "kind": "real", "transaction": "pay1"}
    # the funder's rows are the payments of its jobs: to alice twice and to itself once, and what funder-one funded and was refunded is not a payment
    assert [(r["issue"], r["payee"], r["kind"]) for r in f1["as_owner"]] == [(1, "alice", "real"), (3, "alice", "test"), (4, "funder-one", "self")] and f1["as_seller"][0]["payee"] == "funder-one"
    assert all(r["total_units"] == r["amount_units"] + r["fee_units"] and r["total"] == units_text(r["total_units"]) for r in alice["as_seller"] + f1["as_owner"])
    funded = load(files, "u/funder-one.json")["as_funder"]["paid"]
    assert {k: (sum(1 for r in f1["as_owner"] if r["kind"] == k), sum(r["amount_units"] for r in f1["as_owner"] if r["kind"] == k)) for k in funded} == {k: (v["count"], v["amount"]) for k, v in funded.items()}
    # every account with a record has one, and nobody else
    assert {p[len("statements/"):-5] for p in files if p.startswith("statements/")} == set(load(files, "records.json")["accounts"])


def units_text(n: int) -> str:
    return pages_data.units_text(n)


# ---- what the site's browser tests are served ------------------------------------------------------------------------
RECORDED = ROOT / "tests" / "web" / "recorded" / "pages_data.json"
RECORDED_NOTE = ("The JSON files pages_data.build writes for the scenario of tests/test_pages_data.py (build(get=github(), index=agent_index())), "
                 "as the static site would publish them: tests/web/site.mjs serves them as the same-origin files the Records, Ranks and Statements views read. "
                 "Written by `python tests/test_pages_data.py`; test_the_recorded_files_are_what_pages_data_writes fails when they are not what the code writes now.")


def agent_index() -> dict:
    def row(agent, repo, n, failed):
        return {"agent": agent, "repo": repo, "number": n, "sha": "s", "class": "failed" if failed else "passed", "failed_checks": ["test"] if failed else [], "phrase": "tests pass"}
    rows = [row("copilot", f"o/r{i}", 1, i < 3) for i in range(10)] + [row("devin", f"o/d{i}", 1, i < 1) for i in range(10)] + [row("codex", "o/x", 1, False)]
    return build_index(rows, "2026-10-02", ["2026-06-04", "2026-10-01"], 5)


def recorded_files() -> dict:
    files = build(get=github(), index=agent_index())
    keep = ("records.json", "u/", "r/", "badge/", "rank/", "statements/")
    return {"note": RECORDED_NOTE, "files": {path: json.loads(text) for path, text in sorted(files.items()) if path.endswith(".json") and path.startswith(keep)}}


def test_the_recorded_files_are_what_pages_data_writes():
    assert json.loads(RECORDED.read_text(encoding="utf-8")) == json.loads(json.dumps(recorded_files())), "regenerate: python tests/test_pages_data.py"


if __name__ == "__main__":
    RECORDED.write_text(json.dumps(recorded_files(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", RECORDED)


# ---- work orders (knos_pay 2.1): the escrow's knos3 lines ------------------------------------------------------------
def order(n: int) -> str:
    return str(Pubkey.from_bytes(bytes([40 + n]) * 32))


def order_funded(at, sig, n, issue, amount, by=501, flags=4, repo=10, source=BAL, deadline=NOW + 14 * 86_400):
    """The two lines FundOrderBalance prints (tests/test_records.py reads the same from the program itself)."""
    fee = pay2.order_fee(amount)
    return tx(at, sig, f"knos3:funded order={order(n)} repo={repo} issue={issue} seq=0 amount={amount} fee={fee} mode=0 by={by} source={source} flags={flags} deadline={deadline}",
              f"knos3:terms {TERMS}")


def order_paid(at, sig, n, pr, shares, of, paid_, fee=900_000, tip=100_000, warranty=None):
    lines = [f"knos3:paid order={order(n)} pr={pr} payee={who_} amount={amount} to=W{who_}" for who_, amount in shares]
    lines.append(f"knos3:settled order={order(n)} paid={paid_} of={of} fee={fee} tip={tip} judge=0")
    return tx(at, sig, *lines, *([f"knos3:warranty order={order(n)} held={warranty[0]} until={warranty[1]}"] if warranty else []))


def orders_scenario() -> list[dict]:
    """Funder 501's Balance funds three work orders in octo/widgets: one open and reserved for bob; one split between
    alice and bob, paid with a fifth held back; a standing offer that has paid alice once and is still on offer."""
    return events(
        tx(T0, "bal501", "knos2:balance owner=501 authority=A501 mint=" + USDC),
        order_funded(T0 + 10, "o1", 1, 31, 40_000_000),
        tx(T0 + 100, "take1", f"knos3:reserved order={order(1)} taker=602 until={NOW + 5 * 86_400}"),
        order_funded(T0 + 20, "o2", 2, 32, 50_000_000),
        order_paid(T0 + 1000, "opay2", 2, 12, [(601, 28_000_000), (602, 12_000_000)], 50_000_000, 40_000_000, warranty=(10_000_000, NOW + 86_400)),
        order_funded(T0 + 30, "o3", 3, 33, 25_000_000, flags=4 | 8),
        order_paid(T0 + 2000, "opay3", 3, 13, [(601, 10_000_000)], 25_000_000, 10_000_000, fee=150_000),
    )


def order_accounts() -> dict:
    from _flow import order_bytes
    usdc, bal, th = Pubkey.from_string(USDC), Pubkey.from_string(BAL), pay2.terms_hash(TERMS.encode())
    mk = lambda issue, amount, **kw: pay2.read_order(order_bytes(10, issue, amount, bal, th, deadline=NOW + 14 * 86_400, mint=usdc, **kw))  # noqa: E731
    reserved = bytearray(order_bytes(10, 31, 40_000_000, bal, th, deadline=NOW + 14 * 86_400, mint=usdc, flags=4, reserve_days=7, kill_bps=1000, arbiter=77))
    reserved[128:136], reserved[136:144] = (602).to_bytes(8, "little"), (NOW + 5 * 86_400).to_bytes(8, "little")
    return {order(1): pay2.read_order(bytes(reserved)),
            order(2): mk(32, 50_000_000, flags=4, state=4, paid=40_000_000, holdback_bps=2000, warranty_days=1),
            order(3): mk(33, 15_000_000, flags=4 | 8, rate=10_000_000, fee=225_000)}


def test_open_work_orders_are_listed_with_what_they_promise_and_a_split_is_counted_for_each_payee():
    sys.path.insert(0, str(ROOT / "tests"))
    comments = [{"created_at": iso(T0 + 1010), "body": f"knos-relay proof octo/widgets#12 0123456789abcdef ok asked={T0 + 940} sig=opay2 queue=2 workflow=30 wait=3 chain=5 "
                                                    "note=paid t=8\n", "user": {"login": "github-actions[bot]"}}]
    files = pages_data.build(orders_scenario(), comments, None, None, order_accounts(), pages_data.Names(**NAMES), NOW, own=OWN, own_wallets=frozenset())
    data = load(files, "bounties.json")
    # the order in its warranty is paid, not open; the reserved one and the standing offer are on offer
    assert data["count"] == 2 and [b["issue"] for b in data["bounties"]] == [33, 31]
    standing, taken = data["bounties"]
    assert (taken["amount"], taken["currency"], taken["deadline"], taken["reserved_until"], taken["terms"]["json"]["reserve"]) == (
        40_000_000, "USDC", iso(NOW + 14 * 86_400), iso(NOW + 5 * 86_400), 7)
    assert taken["order"] == {"address": order(1), "seq": 0, "on_offer": 40_000_000, "fee": 1_000_000, "standing": False, "rate": None, "holdback_bps": 0,
                              "warranty_days": 0, "reserved_by": 602, "reserved_until": iso(NOW + 5 * 86_400), "reserve_days": 7, "kill_bps": 1000,
                              "cancelled_at": None, "neutral": True, "arbiter_id": 77}
    assert (standing["amount"], standing["order"]["standing"], standing["order"]["rate"], standing["order"]["on_offer"], standing["reserved_until"]) == (
        15_000_000, True, 10_000_000, 15_000_000, None)
    assert taken["funder"]["login"] == "funder-one" and taken["funder"]["funded"] == 3 and taken["funder"]["paid"] == 1
    assert "Reserved until" in files["bounties.rss"] and "A standing offer: 10.00 for each accepted pull request." in files["bounties.rss"]
    # each payee's own share: alice 28 of the split and 10 of the standing offer, bob 12
    alice, bob = load(files, "u/alice.json"), load(files, "u/bob.json")
    assert alice["as_earner"]["paid_merges"] == 2 and alice["as_earner"]["amounts"]["real"] == {"count": 2, "amount": 38_000_000}
    assert bob["as_earner"]["amounts"]["real"] == {"count": 1, "amount": 12_000_000}
    rows = load(files, "statements/alice.json")["as_seller"]
    assert [(r["issue"], r["pull_request"], r["amount_units"], r["fee_units"], r["kind"]) for r in rows] == [(32, 12, 28_000_000, 1_000_000, "real"),
                                                                                                          (33, 13, 10_000_000, 250_000, "real")]
    assert [(r["payee"], r["amount_units"], r["fee_units"]) for r in load(files, "statements/funder-one.json")["as_owner"]] == [
        ("alice", 28_000_000, 1_000_000), ("bob", 12_000_000, 0), ("alice", 10_000_000, 250_000)]
    assert [(e["login"], e["paid_amount"]) for e in load(files, "rank/earners.json")["entries"]] == [("alice", 38_000_000), ("bob", 12_000_000)]
    funder = load(files, "u/funder-one.json")["as_funder"]
    assert funder["funded"]["real"] == {"count": 3, "amount": 115_000_000} and funder["paid"]["real"]["count"] == 1 and funder["open"] == 2
    repo = load(files, "r/octo/widgets.json")
    assert repo["as_earner"]["payees"] == 2 and repo["as_earner"]["paid_merges"] == 1
    # the latency of an order's payment is measured like a job's, with the stages its relay line carries
    lat = load(files, "latency.json")
    assert lat["merge_to_paid"]["all_time"]["n"] == 1 and lat["merge_to_paid"]["all_time"]["split"]["queue"]["n"] == 1
    assert lat["merge_to_paid"]["all_time"]["split"]["chain"]["p50"] == 5 and "only when it could measure it" in lat["definitions"]["split"]
    # with no accounts read, what the log says is listed and nothing is invented
    blind = load(pages_data.build(orders_scenario(), None, None, None, None, pages_data.Names(**NAMES), NOW, own=OWN, own_wallets=frozenset()), "bounties.json")
    o = next(b for b in blind["bounties"] if b["issue"] == 31)["order"]
    assert (o["reserved_by"], o["reserved_until"], o["holdback_bps"], o["warranty_days"], o["on_offer"]) == (602, iso(NOW + 5 * 86_400), None, None, 40_000_000)
    assert next(b for b in blind["bounties"] if b["issue"] == 33)["order"]["on_offer"] == 15_000_000
