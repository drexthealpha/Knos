"""A bounty's terms: what a funder buys is fixed at funding, written one way only, and judged on GitHub's record of a
commit. A description's words are not in any of it."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from _hub import Hub, run, status
from knos import commands, terms
from knos.cli import main

SPEC = (b'{"accept":"","checks":[{"app":15368,"name":"test"}],"deny":[".github/**",".knos/**"],"mode":"merge",'
        b'"paths":[],"reserve":7,"v":1}')
BASE = json.loads(SPEC)


def fund(rest: str = "") -> commands.Fund:
    got = commands.parse(f"/knos fund 20 {rest}")
    assert isinstance(got, commands.Fund), got
    return got


def refused(call, *args, **kw) -> str:
    with pytest.raises(terms.Refused) as why:
        call(*args, **kw)
    return str(why.value)


# ---- the canonical form ----------------------------------------------------------------------------------------------

def test_equal_terms_are_the_same_bytes_and_the_hash_is_their_sha256():
    assert terms.canonical(BASE) == SPEC and len(SPEC) <= terms.MAX_BYTES == 600
    assert terms.terms_hash(BASE) == terms.terms_hash(SPEC) == terms.terms_hash(bytearray(SPEC)) == hashlib.sha256(SPEC).hexdigest()
    # a list in another order, or with a repeat, is the same terms: canonical puts it in order
    shuffled = {**BASE, "deny": [".knos/**", ".github/**", ".knos/**"],
                "checks": [{"name": "test", "app": 15368}, {"app": 0, "name": "ci"}, {"app": 15368, "name": "build"}, {"app": 0, "name": "ci"}]}
    assert json.loads(terms.canonical(shuffled))["checks"] == [{"app": 15368, "name": "build"}, {"app": 0, "name": "ci"}, {"app": 15368, "name": "test"}]
    assert json.loads(terms.canonical(shuffled))["deny"] == [".github/**", ".knos/**"]
    # ASCII: anything else is written \uXXXX, and read back as it was
    odd = {**BASE, "checks": [{"app": 15368, "name": "tést ✓ 🧪"}]}
    data = terms.canonical(odd)
    assert data.isascii() and b"t\\u00e9st \\u2713 \\ud83e\\uddea" in data and terms.parse(data) == odd
    # one name required from two sources is two entries
    both = {**BASE, "checks": [{"app": 15368, "name": "test"}, {"app": 0, "name": "test"}, {"app": -1, "name": "lint"}]}
    assert terms.parse(terms.canonical(both))["checks"] == [{"app": -1, "name": "lint"}, {"app": 0, "name": "test"}, {"app": 15368, "name": "test"}]
    tests_mode = {**BASE, "mode": "tests", "accept": "ab" * 32}
    assert terms.parse(terms.canonical(tests_mode)) == tests_mode
    assert "600" in refused(terms.canonical, {**BASE, "paths": [f"src/{'x' * 190}{i}/**" for i in range(4)]})


def test_parse_reads_only_the_canonical_bytes():
    assert terms.parse(SPEC) == terms.parse(SPEC.decode()) == BASE

    def swap(old: bytes, new: bytes) -> bytes:
        assert old in SPEC
        return SPEC.replace(old, new, 1)

    not_canonical = [
        SPEC + b"\n", b" " + SPEC, swap(b",", b", "), swap(b":", b": "),                      # a space anywhere
        swap(b'"accept":"","checks":[{"app":15368,"name":"test"}]', b'"checks":[{"app":15368,"name":"test"}],"accept":""'),   # key order
        swap(b'{"app":15368,"name":"test"}', b'{"name":"test","app":15368}'),                # key order inside a check
        swap(b'[".github/**",".knos/**"]', b'[".knos/**",".github/**"]'),                    # a list out of order
        swap(b'[".github/**",".knos/**"]', b'[".github/**",".github/**",".knos/**"]'),       # a repeat
        swap(b'{"app":15368,"name":"test"}', b'{"app":15368,"name":"test"},{"app":15368,"name":"test"}'),
        swap(b'"v":1}', b'"v":1,"v":1}'),                                                     # a key twice
        swap(b'"name":"test"', b'"name":"t\\u0065st"'),                                       # an escape Python would not write
        swap(b'"app":15368', b'"app":015368'), swap(b'"reserve":7', b'"reserve":7.0'), swap(b'"reserve":7', b'"reserve":7e0'),
    ]
    for data in not_canonical:
        refused(terms.parse, data)
    wrong = [
        b"", b"[]", b"null", b'"terms"', b"{", b"\xff\xfe", "é".encode(),
        swap(b'"v":1', b'"v":2'), swap(b'"v":1', b'"v":true'), swap(b'"v":1', b'"v":"1"'),
        swap(b'"reserve":7', b'"reserve":-1'), swap(b'"reserve":7', b'"reserve":91'), swap(b'"reserve":7', b'"reserve":"7"'),
        swap(b'"reserve":7', b'"reserve":true'), swap(b'"reserve":7', b'"reserve":null'),
        swap(b'"mode":"merge"', b'"mode":"both"'), swap(b'"accept":""', b'"accept":"abcd"'), swap(b'"accept":""', b'"accept":null'),
        swap(b'"mode":"merge"', b'"mode":"tests"'),                                           # tests mode needs the hash
        swap(b'"accept":""', b'"accept":"' + b"AB" * 32 + b'"').replace(b"merge", b"tests"),    # in lowercase hex
        swap(b'"v":1}', b'"v":1,"x":1}'), swap(b',"v":1}', b"}"),                             # a key too many, a key too few
        swap(b'"checks":[{"app":15368,"name":"test"}]', b'"checks":{}'), swap(b'"paths":[]', b'"paths":"src"'),
        swap(b'"deny":[".github/**",".knos/**"]', b'"deny":null'),
        swap(b'{"app":15368,"name":"test"}', b'{"app":15368,"name":"test","x":1}'), swap(b'{"app":15368,"name":"test"}', b'"test"'),
        swap(b'"app":15368', b'"app":-2'), swap(b'"app":15368', b'"app":true'), swap(b'"app":15368', b'"app":"15368"'),
        swap(b'"app":15368', b'"app":2147483648'),
        swap(b'"name":"test"', b'"name":""'), swap(b'"name":"test"', b'"name":7'), swap(b'"name":"test"', b'"name":"a\\nb"'),
        swap(b'"name":"test"', b'"name":"' + b"x" * 201 + b'"'),
        swap(b'".knos/**"', b'"/abs"'), swap(b'".knos/**"', b'"!not"'), swap(b'".knos/**"', b'"a/../b"'),
        swap(b'".knos/**"', b'"a\\\\b"'), swap(b'".knos/**"', b'" a"'), swap(b'".knos/**"', b'7'),
    ]
    for data in wrong:
        refused(terms.parse, data)
    big = terms._dump({**BASE, "paths": ["p" * 150 + str(i) for i in range(4)]})
    assert len(big) > 600 and "600" in refused(terms.parse, big)                # over the limit, however well written
    assert "v is 1" in refused(terms.canonical, {**BASE, "v": 2}) and "fields" in refused(terms.canonical, "terms")


def test_no_bytes_but_the_canonical_ones_are_ever_read(tmp_path):
    """Whatever is done to the bytes, `parse` either refuses them or they are exactly what `canonical` writes: two
    different byte strings never mean the same terms, so a hash names one set of terms and one only."""
    import random
    rng = random.Random(600)
    names = ["test", "build (ubuntu-latest, 3.12)", "ci/x", "é", 'q"uote', "back\\slash", "a b", "lint"]
    globs = ["src/**", "docs/*.md", "**/*.py", "a b/c", ".github/**", ".knos/**", "x/"]
    seen = set()
    for _ in range(300):
        tests_mode = rng.random() < 0.3
        t = {"accept": "".join(rng.choice("0123456789abcdef") for _ in range(64)) if tests_mode else "",
             "checks": [{"app": rng.choice([-1, 0, 15368, 2**31 - 1]), "name": rng.choice(names)} for _ in range(rng.randint(0, 4))],
             "deny": rng.sample(globs, rng.randint(0, 3)), "mode": "tests" if tests_mode else "merge",
             "paths": rng.sample(globs, rng.randint(0, 3)), "reserve": rng.randint(0, 90), "v": 1}
        data = terms.canonical(t)
        again = terms.parse(data)
        assert terms.canonical(again) == data and terms.terms_hash(again) == terms.terms_hash(data) == hashlib.sha256(data).hexdigest()
        assert json.loads(data) == again and len(data) <= 600
        seen.add(data)
        for _ in range(12):                                                                # damage the bytes a little
            cut = rng.randrange(len(data))
            other = rng.choice([data[:cut] + data[cut + 1:], data[:cut] + bytes([rng.choice(b' ,:"[]{}0179aeZ\\\n')]) + data[cut:],
                                data[:cut] + bytes([rng.randrange(256)]) + data[cut + 1:], data[:cut] + data[cut:cut + 9] + data[cut:]])
            try:
                read = terms.parse(other)
            except terms.Refused:
                continue
            assert terms.canonical(read) == other                                          # still valid terms: then these are their bytes
    assert len(seen) > 250


def test_the_chain_client_hashes_the_bytes_canonical_wrote():
    """knos-pay checks sha256 of the JSON the funding instruction carries against the audience's hash. The client
    that builds that instruction and these terms must mean the same bytes and the same hash."""
    pay = pytest.importorskip("knos.settle.v2.pay")
    odd = {**BASE, "paths": ["docs/**", "src/\u00e9/*.py"], "checks": [{"app": -1, "name": "t\u00ebst (ubuntu, 3.12)"}, {"app": 0, "name": "ci/x"}]}
    for t in (BASE, {**BASE, "checks": []}, odd, {**BASE, "accept": "ab" * 32, "mode": "tests"}):
        data = terms.canonical(t)
        got = pay.terms_hash(data)
        assert (got.hex() if isinstance(got, (bytes, bytearray)) else got) == terms.terms_hash(t) == hashlib.sha256(data).hexdigest()
        if hasattr(pay, "terms_json"):
            assert pay.terms_json(terms.parse(data)) == data
    assert getattr(pay, "MAX_TERMS", terms.MAX_BYTES) == terms.MAX_BYTES


# ---- globs -----------------------------------------------------------------------------------------------------------

def test_globs_are_githubs_a_star_stays_in_one_directory_and_two_cross_them():
    yes = [("README.md", "*.md"), ("docs/a.md", "**.md"), ("docs/a.md", "**/*.md"), ("a.md", "**/*.md"),
           ("docs/a/b.md", "docs/**"), ("docs/a", "docs/*"), ("x/docs/a", "**/docs/**"), ("docs/a", "**/docs/**"),
           ("src/x.py", "src/"), ("src/a/b/x.py", "src/"), ("src/test_x.py", "src/**/test_*.py"),
           ("src/a/b/test_x.py", "src/**/test_*.py"), ("a.py", "?.py"), (".github/workflows/ci.yml", ".github/**"),
           ("a+b (1).txt", "a+b (1).txt"), ("ab/c", "a**/c"), ("line\nbreak", "line**")]
    no = [("docs/a.md", "*.md"), ("docs/a/b", "docs/*"), ("ab.py", "?.py"), ("a/b.py", "?.py"), ("/.py", "?.py"),
          (".GitHub/workflows/ci.yml", ".github/**"), (".github", ".github/**"), ("xdocs/a", "docs/**"), ("src", "src/"),
          ("a.pyc", "*.py"), ("xa+b (1).txt", "a+b (1).txt")]
    for path, glob in yes:
        assert terms.matches(path, glob), (path, glob)
    for path, glob in no:
        assert not terms.matches(path, glob), (path, glob)
    assert terms.valid_glob("src/**") == "src/**" and "glob" in refused(terms.valid_glob, "../x")


# ---- the terms a fund command buys -----------------------------------------------------------------------------------

def test_the_checks_are_the_funders_names_each_with_the_app_that_produces_it():
    runs = [run("test"), run("build", app=777), run("both"), run("prove / check"), run("unpinned", app=None)]
    statuses = [status("ci/jenkins"), status("both")]
    required = [{"name": "ruled", "app": 4242}, {"name": "jenkins-rule", "app": 99}, {"name": "open", "app": None}]
    built = terms.build(fund("checks: test, build, ci/jenkins, both, ruled, nowhere, unpinned"), required, runs, statuses)
    assert built.source == "funder" and built.terms["mode"] == "merge" and built.terms["accept"] == ""
    assert built.terms["checks"] == [
        {"app": 0, "name": "both"}, {"app": 15368, "name": "both"},     # a check run and a status of one name: both must pass
        {"app": 777, "name": "build"},                                    # the app that produced it on the default branch
        {"app": 0, "name": "ci/jenkins"},                                 # a commit status
        {"app": -1, "name": "nowhere"},                                   # seen nowhere, pinned by nothing: any source
        {"app": 4242, "name": "ruled"},                                   # not seen, but a branch rule names its source
        {"app": 15368, "name": "test"},
        {"app": -1, "name": "unpinned"}]                                  # it ran, and GitHub names no app for it
    assert len(built.notes) == 1 and "`nowhere`" in built.notes[0] and "any source" in built.notes[0]   # said out loud
    assert built.terms["deny"] == [".github/**", ".knos/**"] and built.terms["paths"] == [] and built.terms["reserve"] == 7
    # a rule's app wins over the app seen, and a rule cannot be held against what shows only as a commit status
    assert terms.build(fund("checks: test"), [{"name": "test", "app": 5}], runs, statuses).terms["checks"] == [{"app": 5, "name": "test"}]
    assert terms.build(fund("checks: ci/jenkins"), [{"name": "ci/jenkins", "app": 5}], runs, statuses).terms["checks"] == [{"app": 0, "name": "ci/jenkins"}]
    # paths, reserve and the acceptance bundle come through; tests mode is the bundle's hash
    more = terms.build(fund("checks: test paths: src/**, docs/*.md reserve 3"), [], runs, [], accept="cd" * 32)
    assert more.terms == {"accept": "cd" * 32, "checks": [{"app": 15368, "name": "test"}], "deny": [".github/**", ".knos/**"],
                          "mode": "tests", "paths": ["docs/*.md", "src/**"], "reserve": 3, "v": 1}
    assert terms.build(fund("checks: test"), [], runs, [], deny=("vendor/**",)).terms["deny"] == ["vendor/**"]
    # Knos's own job says nothing about the code, so nobody can buy it
    assert "Knos's own job" in refused(terms.build, fund("checks: test, prove / check"), [], runs, statuses)


def test_no_checks_is_allowed_only_when_said_out_loud():
    none = terms.build(fund("checks: none"))                    # asks nothing of the repository: GitHub is not read
    assert none.terms["checks"] == [] and none.source == "funder"
    assert terms.describe(none.terms, none.source)[0] == "You asked for no checks; your merge alone is the acceptance."
    bare = terms.build(fund(), [], [run("prove / check"), run("skipped", "skipped")], [])
    assert bare.terms["checks"] == [] and bare.source == "none"
    assert terms.describe(bare.terms, bare.source)[0] == "This repository has no checks; your merge alone is the acceptance."
    assert terms.canonical(bare.terms) == SPEC.replace(b'{"app":15368,"name":"test"}', b"")


def test_without_names_the_branchs_required_checks_are_the_terms():
    required = [{"name": "test", "app": 15368}, {"name": "any", "app": None}, {"name": "seen", "app": None},
                {"name": "legacy", "app": None}, {"name": "twice", "app": 1}, {"name": "twice", "app": 2}]
    runs = [run("seen", app=31), run("other"), run("test", app=999)]
    built = terms.build(fund(), required, runs, [status("legacy")])
    assert built.source == "rules"
    assert built.terms["checks"] == [{"app": -1, "name": "any"}, {"app": 0, "name": "legacy"}, {"app": 31, "name": "seen"},
                                     {"app": 15368, "name": "test"}, {"app": 1, "name": "twice"}, {"app": 2, "name": "twice"}]
    assert "other" not in json.dumps(built.terms)                # what merely ran is not required when the branch has rules
    assert [n for n in built.notes if "`any`" in n]


def test_without_names_or_rules_the_checks_that_ran_on_the_default_branch_are_the_terms(monkeypatch):
    runs = [run("test"), run("build", "failure"), run("lint", app=777), run("cancelled", "cancelled"),
            run("deploy", "skipped"), run("docs", "neutral"),                               # never ran: cannot be required to pass
            run("prove / check"), run("knos / fund", status="in_progress"),                  # Knos's own
            run("nightly", event="schedule"), run("on-comment", event="issue_comment", status="in_progress"),
            run("pages", event="dynamic"), run("ci", event="push"), run("pr", event="pull_request"),
            run("this-run", details_url="https://github.com/o/r/actions/runs/77/job/1", status="in_progress")]
    statuses = [status("ci/external", "failure"), status("knos / relay")]
    monkeypatch.setenv("GITHUB_RUN_ID", "77")
    built = terms.build(fund(), [], runs, statuses)
    assert built.source == "head" and built.notes == []
    # check runs only: a service names its commit status one way on a branch and another on a pull request
    assert [c["name"] for c in built.terms["checks"]] == ["build", "cancelled", "ci", "lint", "pr", "test"]
    assert {c["name"]: c["app"] for c in built.terms["checks"]}["lint"] == 777
    assert terms.describe(built.terms, built.source)[0].endswith("(the checks that ran on the default branch's latest commit).")
    assert "`ci/external` (a commit status)" in terms.describe(terms.build(fund("checks: ci/external"), [], runs, statuses).terms)[0]
    # terms are for ever, so they are not fixed while the repository's checks are still running
    for unfinished in ([run("test"), run("e2e", None, status="in_progress")], [run("test"), run("q", None, status="queued", event="push")]):
        assert "still running" in refused(terms.build, fund(), [], unfinished, [])
    assert terms.build(fund(), [], [run("test")], [status("ci/slow", "pending")]).terms["checks"] == [{"app": 15368, "name": "test"}]


def test_terms_are_not_guessed_when_github_cannot_be_read_or_they_do_not_fit():
    runs, statuses = [run("test")], []
    for required, r, s in ((None, runs, statuses), ([], None, statuses), ([], runs, None),
                           ([], {"total_count": 150, "check_runs": runs}, statuses),          # GitHub's own answer, cut short
                           ([], runs, {"total_count": 2, "statuses": []}), ([], {"check_runs": "no"}, statuses)):
        for command in (fund(), fund("checks: test")):
            assert "GitHub did not answer" in refused(terms.build, command, required, r, s)
    whole = terms.build(fund(), [], {"total_count": 1, "check_runs": runs}, {"total_count": 0, "statuses": []})
    assert whole.terms["checks"] == [{"app": 15368, "name": "test"}]
    many = ", ".join(f"integration-tests-shard-{i:02d} (ubuntu-latest)" for i in range(12))
    said = refused(terms.build, fund(f"checks: {many}"), [], [], [])
    assert said.startswith("Those 12 checks do not fit") and "Name fewer checks" in said
    said = refused(terms.build, fund(), [], [run(f"integration-tests-shard-{i:02d} (ubuntu-latest)") for i in range(12)], [])
    assert said.startswith("This repository's 12 checks do not fit") and "`checks: a, b`" in said
    fits = terms.build(fund(), [], [run(f"t{i}") for i in range(15)], [])
    assert len(fits.terms["checks"]) == 15 and len(terms.canonical(fits.terms)) <= 600
    long_paths = SimpleNamespace(checks=("test",), paths=["p" * 150 + str(i) for i in range(4)], reserve=7)
    assert refused(terms.build, long_paths, [], [run("test")], []).startswith("Those paths do not fit")


def test_the_terms_are_told_in_plain_sentences():
    said = terms.describe({**BASE, "paths": ["src/**"], "reserve": 1}, "funder")
    assert said == ["It is paid when a maintainer merges a pull request that closes this issue, if these checks passed at that "
                    "pull request's last commit: `test` (the checks you named).",
                    "The pull request may not change `.github/**` or `.knos/**`, and may only change files matching `src/**`.",
                    "`/knos take` reserves the issue for 1 day."]
    assert "(this branch's required checks)" in terms.describe(BASE, "rules")[0] and terms.describe(BASE)[0].endswith("`test`.")
    any_source = terms.describe({**BASE, "checks": [{"app": -1, "name": "lint"}], "deny": [], "paths": ["a/**", "b/**"], "reserve": 0})
    assert "`lint` (any source)" in any_source[0]
    assert any_source[1:] == ["The pull request may only change files matching `a/**` or `b/**`.",
                              "Nobody can reserve it: the first accepted pull request is paid."]
    assert len(terms.describe({**BASE, "deny": []})) == 2                    # nothing denied, nothing to say about scope
    tests_mode = {**BASE, "mode": "tests", "accept": "ab" * 32}
    assert "acceptance checks" in terms.describe(tests_mode)[0] and "`test`" in terms.describe(tests_mode)[0]
    assert terms.describe({**tests_mode, "checks": []})[0] == "It is paid when its acceptance checks (.knos/acceptance/ for this issue) pass on a pull request."


def test_a_check_that_runs_on_pushes_only_is_not_made_a_condition_of_a_pull_request():
    """A deploy or a release runs on the default branch and never on a pull request. Taken as a condition, it would
    be `absent` on every pull request and the bounty could never be paid."""
    def at_head(*runs_, started, **workflows):
        answers = {"repos/o/r/commits/abc/check-runs": {"total_count": len(runs_), "check_runs": list(runs_)},
                   "repos/o/r/commits/abc/status": {"total_count": 0, "statuses": []},
                   "repos/o/r/actions/runs?head_sha=abc&per_page=100&page=1": {"total_count": len(started), "workflow_runs": started},
                   **{f"repos/o/r/actions/workflows/{k[1:]}/runs": v for k, v in workflows.items()}}
        hub = Hub(answers)
        return terms.head_checks("o/r", "abc", hub, events=True)[0], hub

    def by(suite, event, workflow=None):
        return {"check_suite_id": suite, "event": event, **({"workflow_id": workflow} if workflow else {})}
    ran, never = {"total_count": 40, "workflow_runs": [{}]}, {"total_count": 0, "workflow_runs": []}
    runs = [run("test", check_suite={"id": 1}), run("deploy", check_suite={"id": 2}), run("lint", check_suite={"id": 3}),
            run("vercel", app=8329, check_suite={"id": 4}), run("fast-forwarded", check_suite={"id": 5}), run("labeler", check_suite={"id": 6}),
            run("release", "skipped", check_suite={"id": 2})]
    started = [by(1, "push", 11), by(2, "push", 22), by(3, "push", 11), by(5, "pull_request", 55), by(6, "pull_request_target", 66)]
    got, hub = at_head(*runs, started=started, w11=ran, w22=never)
    assert {r["name"]: r.get("on_pulls", "unmarked") for r in got} == {
        "test": True, "deploy": False, "lint": True, "vercel": "unmarked", "fast-forwarded": True, "labeler": "unmarked", "release": False}
    assert hub.asked.count("repos/o/r/actions/workflows/11/runs?event=pull_request&per_page=1") == 1           # asked once per workflow
    assert not [p for p in hub.asked if "workflows/55" in p or "workflows/66" in p]                           # the event already says
    built = terms.build(fund(), [], got, [])
    assert [c["name"] for c in built.terms["checks"]] == ["fast-forwarded", "lint", "test", "vercel"]          # not deploy; not another pull request's job
    assert built.notes == ["Left out, because its workflow has never run on a pull request: `deploy`. To require one anyway, name it: "
                           "`checks: a, b`."] and built.source == "head"
    assert "Left out, because its workflow has never run on a pull request: `deploy`." in commands.reply(
        "understood", fund(), issue=7, terms=built.terms, source=built.source, notes=built.notes)             # the funder is told
    named = terms.build(fund("checks: deploy, test"), [], got, [])
    assert [c["name"] for c in named.terms["checks"]] == ["deploy", "test"] and named.notes == []              # named by the funder: required
    two, _ = at_head(run("deploy", check_suite={"id": 2}), run("publish", check_suite={"id": 2}), run("test", check_suite={"id": 1}),
                     started=started, w11=ran, w22=never)
    assert terms.build(fund(), [], two, []).notes[0].startswith("Left out, because their workflows have never run on a pull request: `deploy`, `publish`.")
    # a push-only job that is still running does not hold the funding up; one that would be required does
    busy, _ = at_head(run("test", check_suite={"id": 1}), run("deploy", None, status="in_progress", check_suite={"id": 2}),
                      started=started, w11=ran, w22=never)
    assert [c["name"] for c in terms.build(fund(), [], busy, []).terms["checks"]] == ["test"]
    busy, _ = at_head(run("test", None, status="in_progress", check_suite={"id": 1}), run("deploy", check_suite={"id": 2}),
                      started=started, w11=ran, w22=never)
    assert "Checks are still running on the default branch's latest commit (test)" in refused(terms.build, fund(), [], busy, [])
    # no check here is known to run on pull requests (nobody opened one yet): nothing is left out, and the risk is said
    new, _ = at_head(run("test", check_suite={"id": 1}), run("build", check_suite={"id": 1}), run("vercel", app=8329, check_suite={"id": 4}),
                     started=started, w11=never)
    fresh = terms.build(fund(), [], new, [])
    assert [c["name"] for c in fresh.terms["checks"]] == ["build", "test", "vercel"]
    assert fresh.notes == ["`build`, `test` have never run on a pull request. A check that runs on pushes only can never pass on one, "
                           "and this bounty could then not be paid."]
    one, _ = at_head(run("test", check_suite={"id": 1}), started=started, w11=never)
    assert terms.build(fund(), [], one, []).notes[0].startswith("`test` has never run on a pull request.")
    # GitHub did not say (no answer, an odd answer, no workflow named): the check is kept and nothing is claimed
    for answer in (None, {"total_count": "many"}, {"workflow_runs": []}, "no"):
        unknown, hub = at_head(run("test", check_suite={"id": 1}), run("deploy", check_suite={"id": 2}), started=started,
                               **({"w11": answer} if answer is not None else {}), w22=never)
        assert unknown[0]["on_pulls"] is None, answer
        kept = terms.build(fund(), [], unknown, [])
        assert [c["name"] for c in kept.terms["checks"]] == ["deploy", "test"] and kept.notes[0].startswith("`deploy` has never run"), answer
    anonymous, hub = at_head(run("test", check_suite={"id": 1}), started=[by(1, "push")])
    assert anonymous[0]["on_pulls"] is None and terms.build(fund(), [], anonymous, []).notes == []


# ---- evidence --------------------------------------------------------------------------------------------------------

def need(*checks) -> dict:
    return {**BASE, "checks": [{"app": app, "name": name} for name, app in checks]}


def test_a_required_check_is_in_exactly_one_of_six_states():
    t = need(("test", 15368))
    for conclusion, state in (("success", "passed"), ("failure", "failed"), ("timed_out", "failed"), ("cancelled", "failed"),
                              ("action_required", "failed"), ("startup_failure", "failed"), ("stale", "failed"),
                              (None, "failed"), ("a-new-conclusion", "failed"),            # finished, and not success
                              ("skipped", "skipped"), ("neutral", "skipped")):
        assert terms.evidence(t, [run("test", conclusion)], []) == {"test": state}, conclusion
        assert terms.state_of(run("test", conclusion)) == state
    for st in ("queued", "in_progress", "waiting", "requested", "pending", None):
        assert terms.evidence(t, [run("test", None, status=st)], []) == {"test": "pending"}, st
    assert terms.evidence(t, [], []) == {"test": "absent"} == terms.evidence(t, [run("tests"), run("Test")], [])
    assert terms.evidence(t, None, []) == {"test": "unreadable"}                   # GitHub could not be read
    assert terms.evidence(t, {"total_count": 101, "check_runs": [run("test")] * 100}, []) == {"test": "unreadable"}   # cut short
    assert terms.evidence(t, {"total_count": 1, "check_runs": [run("test")]}, None) == {"test": "passed"}      # no status is needed
    assert set(terms.STATES) == {"passed", "failed", "skipped", "pending", "absent", "unreadable"}
    assert terms.evidence(need(), [run("test", "failure")], []) == {}             # nothing is required: nothing to show


def test_only_the_app_the_terms_name_can_produce_the_check():
    t = need(("test", 15368))
    assert terms.evidence(t, [run("test", app=999)], [status("test")]) == {"test": "absent"}     # another app's, and a status, are not it
    assert terms.evidence(t, [run("test", app=None)], []) == {"test": "absent"}
    assert terms.evidence(t, [run("test", app=999), run("test", "failure")], []) == {"test": "failed"}
    # 0: a commit status with that context; the newest status of a context is the one that counts
    s = need(("ci/x", 0))
    assert terms.evidence(s, [run("ci/x")], []) == {"ci/x": "absent"}
    assert terms.evidence(s, [run("ci/x")], None) == {"ci/x": "unreadable"} == terms.evidence(s, None, {"total_count": 3, "statuses": []})
    for state, want in (("success", "passed"), ("failure", "failed"), ("error", "failed"), ("pending", "pending"), ("?", "failed")):
        assert terms.evidence(s, None, [status("ci/x", state)]) == {"ci/x": want}
        assert terms.status_state(status("ci/x", state)) == want
    old, new = status("ci/x", "failure", updated_at="2026-10-01T10:00:00Z", id=1), status("ci/x", "success", updated_at="2026-10-01T11:00:00Z", id=2)
    assert terms.evidence(s, [], [old, new]) == terms.evidence(s, [], [new, old]) == {"ci/x": "passed"}
    assert terms.evidence(s, [], [status("ci/x", "success", created_at="2026-10-01T10:00:00Z"), status("ci/x", "error", created_at="2026-10-01T12:00:00Z")]) == {"ci/x": "failed"}
    # -1: any source, as a branch rule that names none allows: a check run of any app, or a commit status
    a = need(("lint", -1))
    assert terms.evidence(a, [run("lint", app=999)], []) == {"lint": "passed"} == terms.evidence(a, [], [status("lint")])
    assert terms.evidence(a, [run("lint")], [status("lint", "failure")]) == {"lint": "failed"}
    assert terms.evidence(a, [run("lint")], None) == {"lint": "unreadable"} == terms.evidence(a, None, [status("lint")])
    assert terms.evidence(a, [], []) == {"lint": "absent"}


def test_several_runs_of_one_check_count_as_one_and_a_failure_decides():
    t = need(("test", 15368))
    ok, bad, wait, skip = run("test"), run("test", "failure"), run("test", None, status="in_progress"), run("test", "skipped")
    for runs, want in (([ok, bad], "failed"), ([bad, wait], "failed"), ([ok, wait], "pending"), ([skip, wait], "pending"),
                       ([ok, skip], "passed"), ([skip, skip], "skipped"), ([ok, ok], "passed"), ([ok, bad, wait, skip], "failed")):
        assert terms.evidence(t, runs, []) == {"test": want}, want
        assert terms.evidence(t, list(reversed(runs)), []) == {"test": want}
    assert terms.together([]) == "absent" and terms.together(["skipped", "passed"]) == "passed"
    # the same name required from two sources: both must pass, and the worse state is the one shown
    both = need(("test", 15368), ("test", 0))
    assert terms.evidence(both, [ok], [status("test")]) == {"test": "passed"}
    assert terms.evidence(both, [ok], []) == {"test": "absent"} == terms.evidence(both, [], [status("test")])
    assert terms.evidence(both, [ok], [status("test", "pending")]) == {"test": "pending"}
    assert terms.evidence(both, [bad], None) == {"test": "unreadable"}
    assert terms.evidence(both, [skip], [status("test")]) == {"test": "skipped"}


def test_knos_own_jobs_are_never_evidence(monkeypatch):
    for name in ("prove / check", "prove / merged", "prove-relay / relay", "prove-refused / refused", "fund / mint",
                 "fund-relay / relay", "check / claims", "knos / check", "knos"):
        assert terms.ours({"name": name}) and terms.evidence(need((name, 15368)), [run(name)], []) == {name: "absent"}, name
        assert terms.evidence(need((name, 0)), [], [status(name)]) == {name: "absent"}
    for name in ("test", "improve / check", "claims", "refund / x", "my knos"):
        assert not terms.ours({"name": name}), name
    here = run("test", details_url="https://github.com/o/r/actions/runs/123/job/9")
    t = need(("test", 15368))
    assert terms.evidence(t, [here], []) == {"test": "passed"}
    assert terms.evidence(t, [here], [], run_id="123") == {"test": "absent"} and terms.ours(here, 123) and not terms.ours(here, "12")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")                 # this run's own jobs, whatever they are called
    assert terms.evidence(t, [here], []) == {"test": "absent"} and terms.evidence(t, [here], [], run_id="") == {"test": "passed"}
    assert not terms.ours({"name": None}) and not terms.ours({})


# ---- scope, and the verdict ------------------------------------------------------------------------------------------

def test_scope_is_what_the_pull_request_may_not_change_and_all_it_may():
    assert terms.scope(BASE, ["src/a.py", "README.md"]) == [] == terms.scope(BASE, [])
    assert terms.scope(BASE, ["src/a.py", ".github/workflows/ci.yml", ".knos/proof.toml"]) == [
        "changes `.github/workflows/ci.yml`, which this bounty does not allow (`.github/**`)",
        "changes `.knos/proof.toml`, which this bounty does not allow (`.knos/**`)"]
    only = {**BASE, "paths": ["src/**", "docs/*.md"]}
    assert terms.scope(only, ["src/a/b.py", "docs/x.md"]) == []
    assert terms.scope(only, ["docs/deep/x.md", "setup.py", "src/ok.py"]) == [
        "changes `docs/deep/x.md`, outside what this bounty covers (`src/**`, `docs/*.md`)",
        "changes `setup.py`, outside what this bounty covers (`src/**`, `docs/*.md`)"]
    # GitHub's own file objects: a workflow moved out of .github was changed there, whatever it is called now
    moved = [{"filename": "old/ci.yml", "previous_filename": ".github/workflows/ci.yml", "status": "renamed"}, {"filename": "a.py"}]
    assert terms.scope(BASE, moved) == ["changes `.github/workflows/ci.yml`, which this bounty does not allow (`.github/**`)"]
    assert terms.scope(BASE, None) == ["the pull request's changed files could not be read from GitHub; try again"]
    many = terms.scope(BASE, [f".github/{i:02d}.yml" for i in range(14)])
    assert len(many) == 11 and many[-1] == "and 4 more files out of scope"
    odd = terms.scope(BASE, [".github/a`b\nc\x7f" + "x" * 200])[0]           # a file's name cannot write the reply
    assert "`" not in odd.split("`")[1] and "\n" not in odd and "a?b?c?" in odd and len(odd) < 200


def test_a_list_of_changed_paths_is_read_as_git_writes_it(tmp_path):
    """`git diff --name-only` puts a name with unusual characters in quotes with C escapes. Read as it stands, such
    a name matches no glob: a workflow file with an accent in its name would be outside `.github/**`."""
    text = (' lead.txt\n"back\\\\slash.txt"\ndocs/core.py\r\n"docs/\\303\\251.md"\nplain name.txt\n"quo\\"te.txt"\n'
            '"tab\\tname.txt"\n\n   \n"bell\\a\\b\\v\\f\\r\\n.txt"\n')
    assert terms.listed(text) == [" lead.txt", "back\\slash.txt", "docs/core.py", "docs/\u00e9.md", "plain name.txt", 'quo"te.txt',
                                  "tab\tname.txt", "bell\x07\x08\x0b\x0c\r\n.txt"]
    hidden = terms.listed('".github/workflows/\\303\\251vil.yml"\nsrc/a.py\n')
    assert terms.scope(BASE, hidden) == ["changes `.github/workflows/\u00e9vil.yml`, which this bounty does not allow (`.github/**`)"]
    assert terms.scope({**BASE, "paths": ["docs/**"]}, terms.listed('"docs/\\303\\251.md"\n')) == []
    # what is not git's quoting stands as it is; a name that is not text is still one name, and never raises
    for odd in ('"', '"a', 'a"', '"a\\q"', '"a\\"', '"a\\8"', '"a\\400"', '"a\\12"'):
        assert terms.listed(odd) == [odd], odd
    assert terms.listed('"\\377\\376/x"\n\ud800y') == ["\ufffd\ufffd/x", "\ud800y"] and terms.listed('""') == [""]
    assert terms.scope({**BASE, "paths": ["docs/**"]}, ["\ud800y", ""]) == ["changes `?y`, outside what this bounty covers (`docs/**`)"]
    assert terms.listed("") == [] == terms.listed(None)
    # against git itself, where there is one: every name comes back as the file is called, a rename under both names
    import shutil
    import subprocess
    if not shutil.which("git"):
        pytest.skip("no git here")

    def git(*args: str, stdin: str = "") -> str:     # bytes both ways: git writes names in UTF-8, as the workflow's file is read
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@x", "-c", "commit.gpgsign=false", *args], cwd=tmp_path,
                              check=True, capture_output=True, input=stdin.encode("utf-8")).stdout.decode("utf-8")
    git("init", "-q", ".")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "core.py").write_text("a = 1\n" * 20, encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    names = ["docs/\u00e9.md", "tab\tname.txt", 'quo"te.txt', "back\\slash.txt", " lead.txt", "plain name.txt", "docs/core.py"]
    (tmp_path / "docs").mkdir()
    git("mv", "src/core.py", "docs/core.py")
    # The new files go into the commit through git's index, not this file system: a commit made anywhere can name a file
    # tab<TAB>name.txt or quo"te.txt, and Windows cannot hold one (nor, by default, will git there take the name).
    blob = git("hash-object", "-w", "--stdin", stdin="x\n").strip()
    git("-c", "core.protectNTFS=false", "update-index", "-z", "--index-info", stdin="".join(f"100644 {blob}\t{n}\0" for n in names[:-1]))
    git("update-ref", "HEAD", git("commit-tree", git("write-tree").strip(), "-p", "HEAD", "-m", "pr").strip())
    for quoting in ("true", "false"):
        out = git("-c", f"core.quotePath={quoting}", "diff", "--name-only", "--no-renames", "HEAD~1", "HEAD")
        assert sorted(terms.listed(out)) == sorted([*names, "src/core.py"]), quoting
    only_docs = {**BASE, "paths": ["docs/**"]}
    assert "changes `src/core.py`, outside what this bounty covers (`docs/**`)" in terms.scope(only_docs, terms.listed(out))


def test_only_every_check_passed_and_nothing_out_of_scope_is_acceptance():
    t = need(("build", 15368), ("test", 15368))
    assert terms.accepted(t, {"build": "passed", "test": "passed"}, ["src/a.py"]) == (True, [])
    for state, said in (("failed", "required check `test` failed at this commit"),
                        ("pending", "required check `test` has not finished at this commit"),
                        ("skipped", "required check `test` was skipped at this commit, which does not count as passing"),
                        ("absent", "required check `test` did not run on this commit"),
                        ("unreadable", "required check `test` could not be read from GitHub; try again"),
                        ("green", "required check `test` could not be read from GitHub; try again")):     # not a state: not a pass
        assert terms.accepted(t, {"build": "passed", "test": state}, []) == (False, [said]), state
    assert terms.accepted(t, {"build": "passed"}, [])[1] == ["required check `test` could not be read from GitHub; try again"]
    ok, why = terms.accepted(t, {"build": "failed", "test": "passed", "extra": "failed"}, [".github/x.yml"])
    assert not ok and why == ["required check `build` failed at this commit",
                              "changes `.github/x.yml`, which this bounty does not allow (`.github/**`)"]
    assert terms.accepted(t, {"build": "passed", "test": "passed"}, None)[0] is False       # the files could not be read
    # no check required: the merge is the acceptance, and the scope still holds
    assert terms.accepted(need(), {}, ["a.py"]) == (True, []) and not terms.accepted(need(), {}, [".knos/x"])[0]
    twice = need(("test", 15368), ("test", 0))
    assert terms.accepted(twice, {"test": "absent"}, [])[1] == ["required check `test` did not run on this commit"]


def test_a_description_cannot_change_what_is_required():
    """The evidence is GitHub's record and the terms; no function here takes the pull request's words."""
    import inspect
    for f in (terms.evidence, terms.scope, terms.accepted):
        assert not {"body", "description", "text", "claim"} & set(inspect.signature(f).parameters), f.__name__


# ---- reading GitHub --------------------------------------------------------------------------------------------------

def test_a_paged_listing_is_read_whole_or_not_at_all():
    full = [{"n": i} for i in range(100)]
    hub = Hub({"x?per_page=100&page=1": full, "x?per_page=100&page=2": full[:5]})
    assert len(terms.pages("x", hub)) == 105 and hub.asked == ["x?per_page=100&page=1", "x?per_page=100&page=2"]
    assert terms.pages("y?a=1", Hub({"y?a=1&per_page=100&page=1": []})) == []
    counted = Hub({"z?per_page=100&page=1": {"total_count": 100, "items": full}})
    assert len(terms.pages("z", counted, "items")) == 100 and len(counted.asked) == 1          # the count says that was all
    assert terms.pages("gone", Hub()) is None                                                   # GitHub said no
    assert terms.pages("x", Hub({"x": {"message": "rate limited"}})) is None                    # not a listing
    assert terms.pages("x", Hub({"x": {"items": None}}), "items") is None
    assert terms.pages("x", Hub({"x": full}), cap=3) is None                                    # still full at the cap: cut short
    assert terms.pages("x", Hub({"x": {"total_count": 1000, "items": full}}), "items", cap=2) is None


def test_required_checks_are_the_union_of_rulesets_and_branch_protection():
    rules = [{"type": "pull_request", "parameters": {}},
             {"type": "required_status_checks", "parameters": {"required_status_checks": [
                 {"context": "test", "integration_id": 15368}, {"context": "lint"}, {"context": "prove / check", "integration_id": 15368}]}},
             {"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "docs", "integration_id": 31}]}},
             "noise"]
    branch = {"name": "main", "protected": True, "protection": {"enabled": True, "required_status_checks": {
        "enforcement_level": "non_admins", "contexts": ["build", "legacy", "lint"],
        "checks": [{"context": "build", "app_id": 15368}, {"context": "legacy", "app_id": None}, {"context": "lint", "app_id": -1},
                   {"context": "docs", "app_id": 32}, {"context": "", "app_id": 1}, {"context": "flag", "app_id": True}]}}}
    hub = Hub({"repos/o/r/rules/branches/main": rules, "repos/o/r/branches/main": branch})
    assert terms.required_checks("o/r", "main", hub) == [
        {"name": "build", "app": 15368}, {"name": "docs", "app": 31}, {"name": "docs", "app": 32}, {"name": "flag", "app": None},
        {"name": "legacy", "app": None}, {"name": "lint", "app": None}, {"name": "test", "app": 15368}]     # never Knos's own
    assert hub.asked == ["repos/o/r/rules/branches/main?per_page=100&page=1", "repos/o/r/branches/main"]
    off = {"protection": {"required_status_checks": {"enforcement_level": "off", "contexts": ["build"], "checks": []}}}
    assert terms.required_checks("o/r", "main", Hub({"repos/o/r/rules/branches/main": [], "repos/o/r/branches/main": off})) == []
    for bare in ({}, {"protected": False}, {"protection": None}, {"protection": {"required_status_checks": None}}, []):
        assert terms.required_checks("o/r", "main", Hub({"repos/o/r/rules/branches/main": [], "repos/o/r/branches/main": bare})) == []
    slashed = Hub({"repos/o/r/rules/branches/release%2F1.x": [], "repos/o/r/branches/release%2F1.x": {}})
    assert terms.required_checks("o/r", "release/1.x", slashed) == []
    # not being able to read is not the same as requiring nothing
    assert terms.required_checks("o/r", "main", Hub({"repos/o/r/branches/main": branch})) is None
    assert terms.required_checks("o/r", "main", Hub({"repos/o/r/rules/branches/main": rules})) is None


def test_head_checks_reads_every_check_run_and_the_newest_status_of_each_context():
    first = [run(f"job{i}") for i in range(100)]
    hub = Hub({"repos/o/r/commits/abc/check-runs?per_page=100&page=1": {"total_count": 101, "check_runs": first},
               "repos/o/r/commits/abc/check-runs?per_page=100&page=2": {"total_count": 101, "check_runs": [run("late", "failure")]},
               "repos/o/r/commits/abc/status": {"state": "success", "total_count": 1, "statuses": [status("ci/x")]}})
    runs, statuses = terms.head_checks("o/r", "abc", hub)
    assert len(runs) == 101 and runs[-1]["name"] == "late" and statuses == [status("ci/x")]
    assert not [p for p in hub.asked if "actions/runs" in p]
    assert terms.evidence({**BASE, "checks": [{"app": 15368, "name": "late"}]}, runs, statuses) == {"late": "failed"}
    assert terms.head_checks("o/r", "abc", Hub()) == (None, None)
    only_runs = Hub({"repos/o/r/commits/abc/check-runs": {"total_count": 0, "check_runs": []}})
    assert terms.head_checks("o/r", "abc", only_runs) == ([], None)
    endless = Hub({"repos/o/r/commits/abc/check-runs": {"total_count": 5000, "check_runs": first},
                   "repos/o/r/commits/abc/status": {"total_count": 0, "statuses": []}})
    assert terms.head_checks("o/r", "abc", endless) == (None, [])                           # cut short is unreadable


def test_head_checks_can_mark_each_run_with_the_event_that_started_it():
    runs = [run("test", check_suite={"id": 1}), run("nightly", check_suite={"id": 2}), run("other-app", app=9, check_suite={"id": 3}),
            run("bare", check_suite=None)]
    answers = {"repos/o/r/commits/abc/check-runs": {"total_count": 4, "check_runs": runs},
               "repos/o/r/commits/abc/status": {"total_count": 0, "statuses": []},
               "repos/o/r/actions/runs?head_sha=abc&per_page=100&page=1": {"total_count": 3, "workflow_runs": [
                   {"check_suite_id": 1, "event": "push"}, {"check_suite_id": 2, "event": "schedule"}, {"check_suite_id": 7, "event": None}, "x"]}}
    got, _ = terms.head_checks("o/r", "abc", Hub(answers), events=True)
    assert [(r["name"], r.get("event")) for r in got] == [("test", "push"), ("nightly", "schedule"), ("other-app", None), ("bare", None)]
    assert [c["name"] for c in terms.build(fund(), [], got, []).terms["checks"]] == ["bare", "other-app", "test"]
    del answers["repos/o/r/actions/runs?head_sha=abc&per_page=100&page=1"]                   # that read fails: the runs come back unmarked
    unmarked, _ = terms.head_checks("o/r", "abc", Hub({**answers, "repos/o/r/commits/abc/check-runs": {
        "total_count": 1, "check_runs": [run("test", check_suite={"id": 1})]}}), events=True)
    assert unmarked == [run("test", check_suite={"id": 1})]
    assert terms.head_checks("o/r", "abc", Hub({"repos/o/r/commits/abc/status": {"statuses": []}}), events=True) == (None, [])


def test_pull_files_lists_a_rename_under_both_names():
    files = [{"filename": "b.py", "previous_filename": "a.py", "status": "renamed"}, {"filename": "c.py", "status": "added"}, "x"]
    assert terms.pull_files("o/r", 12, Hub({"repos/o/r/pulls/12/files": files})) == ["a.py", "b.py", "c.py"]
    assert terms.pull_files("o/r", 12, Hub()) is None
    page = [{"filename": f"f{i}"} for i in range(100)]
    assert terms.pull_files("o/r", 12, Hub({"repos/o/r/pulls/12/files": page})) is None        # GitHub stops listing at 3000 files


def test_watch_waits_for_a_required_check_and_no_longer():
    t = need(("test", 15368))
    answers = [[run("test", None, status="in_progress")], None, [run("test")]]
    naps, calls = [], []

    def get(path):
        if "check-runs" in path:
            calls.append(path)
            got = answers[min(len(calls), len(answers)) - 1]
            if got is None:
                raise OSError("502")
            return {"total_count": len(got), "check_runs": got}
        return {"total_count": 0, "statuses": []}
    clock = iter(range(0, 1000, 15))
    found, runs, statuses = terms.watch(t, "o/r", "abc", get, wait=600, sleep=naps.append, clock=lambda: next(clock))
    assert found == {"test": "passed"} and runs == [run("test")] and statuses == [] and naps == [15, 15] and len(calls) == 3
    calls.clear()
    found, runs, _ = terms.watch(t, "o/r", "abc", get, wait=0, sleep=naps.append)            # no waiting asked for
    assert found == {"test": "pending"} and len(calls) == 1 and naps == [15, 15]
    calls.clear()
    slow = iter([0, 100, 700])
    assert terms.watch(need(("never", 15368)), "o/r", "abc", get, wait=600, sleep=naps.append, clock=lambda: next(slow))[0] == {"never": "absent"}
    assert len(calls) == 1                                                                     # absent is an answer: no waiting for it


# ---- knos proof terms, knos proof evidence ---------------------------------------------------------------------------

def cli(capsys, *args: str) -> tuple[int, str]:
    rc = main(list(args))
    got = capsys.readouterr()
    return rc, got.out + got.err


@pytest.fixture()
def github(monkeypatch):
    hub = Hub({"repos/o/r": {"default_branch": "main"}, "repos/o/r/commits/main": {"sha": "abc"},
               "repos/o/r/rules/branches/main": [], "repos/o/r/branches/main": {},
               "repos/o/r/commits/abc/check-runs": {"total_count": 3, "check_runs": [
                   run("test", check_suite={"id": 1}), run("nightly", check_suite={"id": 2}), run("knos / fund", status="in_progress")]},
               "repos/o/r/commits/abc/status": {"total_count": 0, "statuses": []},
               "repos/o/r/actions/runs": {"total_count": 2, "workflow_runs": [{"check_suite_id": 1, "event": "push"},
                                                                               {"check_suite_id": 2, "event": "schedule"}]}})
    monkeypatch.setattr("knos.judge.github", hub)
    return hub


def test_knos_proof_terms_prints_the_canonical_terms_and_their_hash(github, tmp_path, capsys):
    rc, out = cli(capsys, "proof", "terms", "--repo", "o/r", "--command", "/knos fund 20", "--out", str(tmp_path / "terms.json"))
    assert rc == 0 and out.splitlines() == [SPEC.decode(), hashlib.sha256(SPEC).hexdigest()]
    assert (tmp_path / "terms.json").read_bytes() == SPEC                                    # byte for byte: what is funded
    github.asked.clear()
    rc, out = cli(capsys, "proof", "terms", "--repo", "o/r", "--branch", "main", "--sha", "abc", "--json", "--issue", "7",
                  "--command", "/knos bounty 12.5 checks: test paths: src/** days 30 reserve 3")
    got = json.loads(out)
    assert rc == 0 and terms.parse(got["terms"])["paths"] == ["src/**"] and got["hash"] == terms.terms_hash(got["terms"].encode())
    assert {k: got[k] for k in ("source", "units", "days", "work", "mode", "notes")} == \
        {"source": "funder", "units": 12_500_000, "days": 30, "work": 30 * 86_400, "mode": 0, "notes": []}
    assert got["reply"].startswith("Knos: 12.5 test USDC for issue #7. It is paid when a maintainer merges")     # ready to post
    assert "reserves the issue for 3 days. If it is not paid within 30 days" in got["reply"]
    assert "repos/o/r" not in github.asked and "repos/o/r/commits/main" not in github.asked    # given, so not asked
    # the command in a comment's body; tests mode when the issue has an acceptance bundle on the default branch
    bundle = tmp_path / ".knos" / "acceptance" / "7"
    bundle.mkdir(parents=True)
    (bundle / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (tmp_path / "comment.md").write_text("Let's pay for this.\n\n/knos fund 5 checks: none\n", encoding="utf-8")
    github.asked.clear()
    rc, out = cli(capsys, "proof", "terms", "--body-file", str(tmp_path / "comment.md"), "--accept-dir", str(bundle), "--json")
    from knos import judge
    got = json.loads(out)
    assert rc == 0 and got["mode"] == 1 and terms.parse(got["terms"])["accept"] == judge.checks_hash(bundle)
    assert github.asked == []                                                                # `checks: none` asks GitHub nothing
    rc, out = cli(capsys, "proof", "terms", "--command", "/knos fund 5 checks: none", "--accept-dir", str(tmp_path / "nothing"), "--json")
    assert rc == 0 and json.loads(out)["mode"] == 0 and json.loads(out)["command"] == "fund"
    # a tip: its terms ask for nothing, whatever the repository requires and whatever bundle the issue has
    rc, out = cli(capsys, "proof", "terms", "--repo", "o/r", "--command", "/knos tip 2.5", "--accept-dir", str(bundle), "--json",
                  "--out", str(tmp_path / "tip.json"))
    got = json.loads(out)
    assert rc == 0 and github.asked == [] and got == {
        "command": "tip", "terms": '{"accept":"","checks":[],"deny":[],"mode":"merge","paths":[],"reserve":0,"v":1}',
        "hash": terms.terms_hash(terms.tip()), "source": "tip", "notes": [], "units": 2_500_000, "days": 1, "work": 86_400, "mode": 0,
        "reply": "Knos: a tip of 2.5 test USDC for this merged pull request. Next: it is paid on Solana, and Knos confirms here."}
    assert terms.parse((tmp_path / "tip.json").read_bytes()) == terms.tip()
    assert terms.accepted(terms.tip(), terms.evidence(terms.tip(), [], []), [".github/workflows/ci.yml", "a.py"]) == (True, [])


def test_knos_proof_terms_refuses_in_the_words_to_post(github, capsys):
    rc, out = cli(capsys, "proof", "terms", "--repo", "o/r", "--command", "/knos fund lots")
    assert rc == 1 and out.startswith("Knos: that was not understood") and "`/knos fund <amount>" in out
    rc, out = cli(capsys, "proof", "terms", "--repo", "o/r", "--command", "/knos take")
    assert rc == 1 and "this needs a fund command" in out
    rc, out = cli(capsys, "proof", "terms", "--repo", "o/r", "--command", "nothing here")
    assert rc == 1 and "this needs a fund command" in out
    rc, out = cli(capsys, "proof", "terms", "--command", "/knos fund 20")
    assert rc == 1 and "--repo owner/name" in out
    rc, out = cli(capsys, "proof", "terms", "--repo", "o/gone", "--command", "/knos fund 20")
    assert rc == 1 and out.startswith("GitHub did not answer for o/gone")
    del github.answers["repos/o/r/branches/main"]
    rc, out = cli(capsys, "proof", "terms", "--repo", "o/r", "--command", "/knos fund 20")
    assert rc == 1 and out.startswith("Knos: GitHub did not answer for this repository's checks")
    rc, out = cli(capsys, "proof", "terms", "--repo", "o/r", "--command", "/knos fund 20 checks: knos / fund")
    assert rc == 1


def test_knos_proof_evidence_prints_each_checks_state_and_the_verdict(github, tmp_path, capsys):
    t = tmp_path / "terms.json"
    t.write_bytes(terms.canonical(need(("nightly", 15368), ("test", 15368))) + b"\n")           # a final newline is forgiven
    changed = tmp_path / "changed.txt"
    changed.write_text("src/a.py\n\nREADME.md\n", encoding="utf-8")
    rc, out = cli(capsys, "proof", "evidence", "--terms", str(t), "--repo", "o/r", "--sha", "abc", "--changed", str(changed),
                  "--out", str(tmp_path / "verdict.json"))
    assert rc == 0 and out.splitlines() == ["passed     nightly", "passed     test", "accepted"]
    assert json.loads((tmp_path / "verdict.json").read_text()) == {
        "terms_hash": terms.terms_hash(need(("nightly", 15368), ("test", 15368))), "mode": 0, "accept": "",
        "checks": {"nightly": "passed", "test": "passed"}, "accepted": True, "reasons": []}       # what the pay audience is made of
    # the changed files from GitHub; a workflow file is out of scope
    github.answers["repos/o/r/pulls/12/files"] = [{"filename": "src/a.py"}, {"filename": ".github/workflows/ci.yml"}]
    rc, out = cli(capsys, "proof", "evidence", "--terms", str(t), "--repo", "o/r", "--sha", "abc", "--pull", "12")
    assert rc == 1 and "NO  changes `.github/workflows/ci.yml`" in out and out.splitlines()[-1] == "not accepted"
    rc, out = cli(capsys, "proof", "evidence", "--terms", str(t), "--repo", "o/r", "--sha", "abc", "--pull", "13")
    assert rc == 1 and "changed files could not be read" in out
    # from files: a failed check, a missing one
    (tmp_path / "runs.json").write_text(json.dumps({"total_count": 1, "check_runs": [run("test", "failure")]}), encoding="utf-8")
    rc, out = cli(capsys, "proof", "evidence", "--terms", str(t), "--checks-file", str(tmp_path / "runs.json"), "--changed", str(changed))
    assert rc == 1 and out.splitlines() == ["absent     nightly", "failed     test", "NO  required check `nightly` did not run on this commit",
                                            "NO  required check `test` failed at this commit", "not accepted"]
    s = need(("ci/x", 0))
    t.write_bytes(terms.canonical(s))
    (tmp_path / "statuses.json").write_text(json.dumps([status("ci/x")]), encoding="utf-8")
    rc, out = cli(capsys, "proof", "evidence", "--terms", str(t), "--checks-file", str(tmp_path / "runs.json"),
                  "--statuses-file", str(tmp_path / "statuses.json"), "--changed", str(changed))
    assert rc == 0 and "passed     ci/x" in out
    t.write_bytes(terms.canonical(need()))
    rc, out = cli(capsys, "proof", "evidence", "--terms", str(t), "--repo", "o/r", "--sha", "abc", "--changed", str(changed))
    assert rc == 0 and "no check is required: the merge alone is the acceptance" in out
    # a bounty funded with acceptance checks: this verdict is half of what it needs, and it says so
    t.write_bytes(terms.canonical({**need(), "accept": "ab" * 32, "mode": "tests"}))
    rc, out = cli(capsys, "proof", "evidence", "--terms", str(t), "--repo", "o/r", "--sha", "abc", "--changed", str(changed),
                  "--out", str(tmp_path / "verdict.json"))
    assert rc == 0 and out.splitlines() == ["this bounty also needs its acceptance checks to pass: knos proof judge --terms", "accepted"]
    got = json.loads((tmp_path / "verdict.json").read_text())
    assert got["mode"] == 1 and got["accept"] == "ab" * 32 and got["accepted"] is True
    t.write_bytes(terms.canonical(need()))
    # what it cannot judge it says, and does not accept
    rc, out = cli(capsys, "proof", "evidence", "--terms", str(t), "--changed", str(changed))
    assert rc == 1 and "pass --repo and --sha, or --checks-file" in out
    rc, out = cli(capsys, "proof", "evidence", "--terms", str(t), "--repo", "o/r", "--sha", "abc")
    assert rc == 1 and "pass --changed, or --repo and --pull" in out
    t.write_bytes(terms.canonical(need()).replace(b",", b", "))
    rc, out = cli(capsys, "proof", "evidence", "--terms", str(t), "--repo", "o/r", "--sha", "abc", "--changed", str(changed))
    assert rc == 1 and "not in canonical form" in out


# ---- image: the hermetic judge's container, fixed at funding ----------------------------------------------------------

IMAGE = "docker.io/library/python@sha256:" + "a" * 64
TESTS = {**BASE, "mode": "tests", "accept": "b" * 64}


def test_an_image_is_part_of_the_terms_and_of_their_hash():
    with_image = {**TESTS, "image": IMAGE}
    data = terms.canonical(with_image)
    assert terms.parse(data) == with_image and json.loads(data)["image"] == IMAGE
    assert terms.terms_hash(with_image) == hashlib.sha256(data).hexdigest() != terms.terms_hash(TESTS)
    other = {**TESTS, "image": "docker.io/library/python@sha256:" + "c" * 64}
    assert terms.terms_hash(other) != terms.terms_hash(with_image)            # another image is other terms
    assert b"image" not in terms.canonical(TESTS) and terms.canonical(BASE) == terms.canonical({**BASE})   # terms without one keep their bytes
    built = terms.build(fund(), [], [], [], accept="b" * 64, image=IMAGE)
    assert built.terms["image"] == IMAGE and built.terms["mode"] == "tests"
    assert "image" not in terms.build(fund(), [], [], [], accept="", image=IMAGE).terms    # a merge has no judge to pin


@pytest.mark.parametrize("image", ["python:3.12", "docker.io/library/python:3.12-alpine", "ghcr.io/owner/judge:latest", "python"])
def test_a_tag_without_a_digest_is_refused_at_funding_with_what_to_write(image):
    for said in (refused(terms.canonical, {**TESTS, "image": image}), refused(terms.build, fund(), [], [], [], "b" * 64, image=image)):
        assert "a tag can be pointed at another image after funding" in said
        assert "Pin it by digest: write <registry>/<name>@sha256:<64 hex>" in said


def test_an_image_that_is_not_one_and_an_image_in_merge_mode_are_refused():
    for bad in ("python@sha256:" + "a" * 64, IMAGE[:-1], IMAGE.upper(), IMAGE + " --privileged", "", 7, None, [IMAGE]):
        assert "image" in refused(terms.canonical, {**TESTS, "image": bad}), bad
    assert "image goes with tests mode" in refused(terms.canonical, {**BASE, "image": IMAGE})
    assert "not in canonical form" in refused(terms.parse, terms.canonical({**TESTS, "image": IMAGE}).replace(b'"image"', b' "image"'))


def test_the_terms_say_which_assurance_they_buy():
    assert terms.assurance(BASE) == "" and terms.assurance(TESTS) == ""                     # merge mode; and not known from the terms alone
    assert (terms.assurance(TESTS, False), terms.assurance(TESTS, True), terms.assurance({**TESTS, "image": IMAGE})) == \
        ("in-process", "black-box", "hermetic")
    assert not any(line.startswith("Judge:") for line in terms.describe(BASE))
    tests = terms.describe(TESTS, black_box=False)[-1]
    box = terms.describe(TESTS, black_box=True)[-1]
    hermetic = terms.describe({**TESTS, "image": IMAGE})[-1]
    assert tests.startswith("Judge: in-process. ") and "7 of 63" in tests
    assert box.startswith("Judge: black-box. ") and "0 of 63" in box and "not a proof for every attack" in box
    assert hermetic.startswith(f"Judge: hermetic, in `{IMAGE}`. ") and "0 of 63" in hermetic and "not a proof for every attack" in hermetic
