"""The zero-secret GitHub relay (ghrelay), the caller workflow."""

import base64
import functools
import hashlib
import json
import re
import time
from pathlib import Path

import pytest

from knos.proof import ghrelay

ROOT = Path(__file__).resolve().parents[1]
JOB = "ab" * 32
PAYOUT = "EwSxyJFNQkNN9qtss4Qd7DTvrNYb62vgvhdwqgfErXDz"


def jwt(aud: str, exp: float | None = None) -> str:
    def enc(d: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    return f"{enc({'alg': 'RS256', 'kid': 'k1'})}.{enc({'aud': aud, 'exp': exp or time.time() + 300})}.c2ln"


def test_checks_hash_is_sorted_paths_each_with_its_content_hash(tmp_path):
    d = tmp_path / ".knos" / "acceptance" / "1"
    (d / "sub").mkdir(parents=True)
    (d / "test_accept.py").write_bytes(b"def test_x():\n    assert 1\n")
    (d / "sub" / "data.txt").write_bytes(b"x")
    want = hashlib.sha256()
    for rel, data in sorted([("sub/data.txt", b"x"), ("test_accept.py", b"def test_x():\n    assert 1\n")]):
        want.update(f"{rel}\0{hashlib.sha256(data).hexdigest()}\n".encode())
    assert ghrelay.checks_hash(d) == want.hexdigest()
    # 0.3.11's fund.yml computed the same hash in a script of its own, which had to be kept equal to this one by a
    # test. Now the workflow computes nothing: one command does, and this is the only place the hash is made.
    src = (ROOT / ".github" / "workflows" / "fund.yml").read_text(encoding="utf-8")
    assert "hashlib" not in src and "python3 -" not in src


def test_relay_one_reports_in_words_and_checks_the_marker():
    paid = {"ok": True, "kind": "pay", "sigs": ["s1", "s2", "s3", "s4"], "issue": 7, "author_id": 4242,
            "paid": [{"job": "J1", "amount": 5_000_000, "fee": 125_000, "mint": "M", "waits": 0}]}
    r = ghrelay.relay_one(None, None, "proof", "x.y.z", submit=lambda *a: dict(paid))
    assert r["ok"] and "4.88 is now waiting under GitHub user id 4242 for issue #7" in r["note"] and "#claim" in r["note"]
    line = ghrelay.log_line("proof", "o/r", 9, "x.y.z", r)
    assert line.startswith(f"knos-relay proof o/r#9 {ghrelay.token_id('x.y.z')} ok sig=s2,s3,s4 note=")
    waits = dict(paid, paid=[dict(paid["paid"][0], waits=3600)])
    note = ghrelay.relay_one(None, None, "proof", "x.y.z", submit=lambda *a: waits)["note"]
    assert "4.88 will be released in 1 h (a maintainer's /knos veto on the issue takes it back) to GitHub user id 4242" in note
    funded = {"ok": True, "kind": "fund", "sigs": ["f"], "job": "J", "issue": 3, "amount": 5_000_000, "mode": 0, "review": 3600}
    note = ghrelay.relay_one(None, None, "fund", "t", submit=lambda *a: dict(funded))["note"]
    assert "5.00 test USDC is in escrow for issue #3, paid when a maintainer merges" in note and "released 1 h after that" in note
    # a fund token posted under a proof marker is refused; a failure is passed through and logged as fail
    assert not ghrelay.relay_one(None, None, "proof", "t", submit=lambda *a: dict(funded))["ok"]
    bad = ghrelay.relay_one(None, None, "fund", "t", submit=lambda *a: {"ok": False, "why": "token expired"})
    assert ghrelay.log_line("fund", "o/r", 1, "t", bad).endswith("fail token expired")


def test_found_and_discover():
    t = jwt("knos:fund:3:1:0:" + "0" * 64 + ":1209600:0")
    comments = [{"body": f"knos-fund: {t}\n\n<sub>x</sub>", "issue_url": "https://api.github.com/repos/o/r/issues/3",
                 "user": {"login": "github-actions[bot]"}}, {"body": "hello", "issue_url": "u/4", "user": {"login": "a"}}]
    assert ghrelay.found("o/r", "2026-10-02T00:00:00Z", getter=lambda p: comments) == \
        [("fund", 3, t, "github-actions[bot]")]

    def getter(path):
        if path.startswith("search/"):
            return {"items": [{"repository_url": "https://api.github.com/repos/a/b"}]}
        return [{"full_name": "drexthealpha/knos-e2e-1", "pushed_at": "2026-10-02T01:00:00Z"},
                {"full_name": "drexthealpha/Knos", "pushed_at": "2026-10-02T01:00:00Z"},
                {"full_name": "drexthealpha/old", "pushed_at": "2025-01-01T00:00:00Z"}]
    assert ghrelay.discover("2026-10-02T00:00:00Z", {}, getter=getter) == {"a/b", "drexthealpha/knos-e2e-1", ghrelay.ROTATE_REPO,
                                                                            ghrelay.HOME_REPO}
    for kind in ("veto", "claim", "key", "proof"):
        assert ghrelay.TOKEN.findall(f"knos-{kind}: {t}") == [(kind, t)]


def test_caller_workflow_needs_no_secret_and_names_one_published_commit():
    wf = (ROOT / "examples" / "knos-workflow.yml").read_text(encoding="utf-8")
    # no secret is needed; the one a repository may set is handed on by name, never all of them
    assert set(re.findall(r"secrets\.(\w+)", wf)) == {"KNOS_RELAY_KEY"} and "inherit" not in wf and "No secret is needed" in wf
    # the workflows are pinned by one commit of drexthealpha/knos-workflows; until a release names it the template
    # carries a placeholder, and the release puts the commit into the examples and the site together
    pins = set(re.findall(r"drexthealpha/knos-workflows/\.github/workflows/(?:fund|prove)\.yml@(\S+)", wf))
    assert len(pins) == 1 and re.fullmatch(r"KNOS_WORKFLOWS_SHA|[0-9a-f]{40}", next(iter(pins)))
    code = "\n".join(ln for ln in wf.splitlines() if not ln.lstrip().startswith("#"))
    assert "pull_request_target" not in code and "issue_comment" in code and "push" in code
    assert "relay.yml" not in wf and "drexthealpha/Knos/.github/workflows" not in wf     # nothing of the first deployment's
    fund = (ROOT / ".github" / "workflows" / "fund.yml").read_text(encoding="utf-8")
    assert "id-token: write" in fund and 'knos command --event "$GITHUB_EVENT_PATH" --repo "$GITHUB_REPOSITORY"' in fund


def test_the_site_hands_out_the_examples_byte_for_byte():
    """web/front.js carries the two files a repository installs as templates. They are written from examples/ by
    scripts/front_workflow.py and by nothing else: after an example changes, run `python scripts/front_workflow.py`."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("front_workflow", ROOT / "scripts" / "front_workflow.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main(["--check"]) == 0, "web/front.js does not hand out examples/: run python scripts/front_workflow.py"
    js = (ROOT / "web" / "front.js").read_text(encoding="utf-8")
    check = re.search(r"export const CHECK_WORKFLOW = `(.*?)`;\n", js, re.DOTALL).group(1)
    code = "\n".join(ln for ln in check.splitlines() if not ln.lstrip().startswith("#"))      # its comments say it asks for none
    assert "knos-workflows/.github/workflows/check.yml@" in code and "id-token" not in code and "write" not in code
    net = (ROOT / ".github" / "workflows" / "network.yml").read_text(encoding="utf-8")
    assert 'bash scripts/build_site.sh _site "$GITHUB_SHA"' in net
    assert "settings/rules/new?target=branch&enforcement=active" in js


def test_judge_learns_a_contributing_violation_and_requires_it_next(tmp_path):
    from knos import judge as prove
    from knos.proof import history
    base = tmp_path / "base"
    (base / ".knos" / "acceptance" / "1").mkdir(parents=True)
    (base / ".knos" / "acceptance" / "1" / "test_accept.py").write_bytes(b"def test_a():\n    assert 1\n")
    (base / "CONTRIBUTING.md").write_bytes(b"# Rules\n\n- Do not leave print() debug statements in code.\n")
    diff = ("diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,3 @@\n def add(a, b):\n"
            "+    print(a, b)\n     return a + b\n")
    store = history.SibylStore.local(tmp_path / "store")
    v = prove.judge_with_rules(base, tmp_path / "pr", {"issue": "1"}, ["calc.py"], diff, store, "o/r", "bot")
    assert not v["passed"] and v["reasons"][0].startswith("repo rule: calc.py:2")
    assert v["evidence"]["required_by_history"] == [] and v["evidence"]["learned"] == ["tamper:rule:no_debug"]
    again = history.SibylStore.local(tmp_path / "store")   # a later run: the memory restored from the cache
    v2 = prove.judge_with_rules(base, tmp_path / "pr", {"issue": "1"}, ["calc.py"], diff, again, "o/r", "other")
    assert v2["evidence"]["required_by_history"] == ["tamper:rule:no_debug"]


def test_fund_yml_hands_the_event_to_one_command_and_parses_nothing_itself():
    """0.3.11's fund.yml read the comment and built the audience in an inline script, checked here against the client.
    A script in YAML can drift from the client and is hard to test. Now `knos command` reads GitHub's event file and
    does all of it (tests/test_commands.py and the command's own tests); who may fund is decided by the chain, from
    GitHub's signature of who commented, not by a label on the comment."""
    import yaml
    doc = yaml.safe_load((ROOT / ".github" / "workflows" / "fund.yml").read_text(encoding="utf-8"))
    [job] = doc["jobs"].values()
    scripts = [s["run"] for s in job["steps"] if "run" in s]
    assert scripts[-1] == 'knos command --event "$GITHUB_EVENT_PATH" --repo "$GITHUB_REPOSITORY"' and len(scripts) == 2
    text = json.dumps(job)
    assert "author_association" not in text and "comment.body" not in text and "issue.body" not in text
    assert not [s for s in job["steps"] if "artifact" in str(s.get("uses", ""))]       # the token is the command's to post or relay


# -- what 0.3.14 joined: the passkey's funding line, and the meter's batch and claim tokens under knos-eval: -----------

def test_a_passkey_funding_line_on_an_issue_is_sent_by_the_worker_and_answered(monkeypatch, tmp_path):
    """`/knos passkey-fund <base64url>` is no token and no workflow posts it: the funder pastes it. One pass of the
    worker finds it, sends it on LiteSVM (knos_pay and knos_passkey as built), answers on the issue and logs it."""
    pytest.importorskip("solders.litesvm")
    import test_passkey_relay as tp
    import test_worker as tw
    from _order import REPO, USDC, issue
    from knos.settle.v2 import passkey_fund as pf

    assert ghrelay.PASSKEY_FUND.pattern == pf.LINE.pattern          # the worker reads the line the client's reader takes

    class GitHub(tw.GitHub):
        def _route(self, method, path, data):                       # and the repository's id, which the chain knows it by
            ids = {"repos/octo/widgets": REPO, "repos/a/copies": REPO + 1}
            return (200, {"id": ids[path]}) if path in ids else (404, None) if path.startswith("repos/a/copies/issues/9") else super()._route(method, path, data)

    w, gh = tp.World(), GitHub()
    net, n, t0 = tp.Counted(w), issue(), time.time()
    monkeypatch.setattr(ghrelay, "_HUB", ghrelay.Hub(gh.open))
    monkeypatch.setattr(ghrelay, "_LOG", {})
    monkeypatch.setattr(ghrelay, "_state_path", lambda: tmp_path / "ghrelay.json")
    monkeypatch.setenv("KNOS_RELAY_REPOS", "octo/widgets,a/copies")
    gh.issues[tw.HOME] = [{"number": 1, "state": "open", "labels": [ghrelay.LOG_LABEL]}]
    line = tp.comment(w, n)
    text = line.split()[-1]
    gh.comment("a/copies", 9, line, who="mallory", at=t0 - 9)       # anyone can copy the line elsewhere, even first: it funds nothing there, and uses nothing up
    gh.comment("octo/widgets", n, f"Funding this from the Buy page.\n\n{line}\n", who="funder", at=t0 - 5)
    assert [(f[0], f[1], f[2]) for f in ghrelay.tokens(gh.comments["octo/widgets"])] == [("passkey-fund", n, text)]
    had = w.balance(w.source)
    lines = ghrelay.once(net, w.payer, now=t0, crank=False)
    order = pf.order_of(w.p.wallet, w.data_of(n))
    o = w.order(order)
    assert net.sent == 1 and (o.amount, o.repo_id, o.issue) == (20 * USDC, REPO, n) and had - w.balance(w.source) == 20 * USDC + o.fee
    ok = [ln for ln in lines if " ok " in ln]
    assert len(ok) == 1 and ok[0].startswith(f"knos-relay passkey-fund octo/widgets#{n} {ghrelay.token_id(text)} ok sig=")
    assert f"note=funded from a passkey wallet. {20 * USDC} units of the test token {w.usdc} is in escrow for issue #{n}" in ok[0]
    # the answer is on the issue (this relay's token may write there); the copy's comment could not be answered, and its log line names no id
    said = [c["body"] for c in gh.comments["octo/widgets"] if c["user"]["login"] == ghrelay.LOG_BOT]
    assert len(said) == 1 and said[0].startswith("Knos: funded from a passkey wallet. ") and f"`{order}`" in said[0]
    copy = [ln for ln in lines if "a/copies#9" in ln]
    assert len(copy) == 1 and copy[0].startswith(f"knos-relay passkey-fund a/copies#9 - fail this comment cannot carry its line ({ghrelay.token_id(text)[:8]}...): "
                                                 f"the passkey signed for issue #{n}")
    assert json.loads((tmp_path / "ghrelay.json").read_text())["verify"]["n"] == {"passkey-fund:octo/widgets": 1}
    # the next pass sends nothing. The same line pasted again, there or on another issue, sends nothing either: the
    # log already answers for that line (as for the loser of two overlapping runs), so nothing is added to it
    assert ghrelay.once(net, w.payer, now=t0 + 3, crank=False) == [] and net.sent == 1
    gh.comment("octo/widgets", n, line, who="funder", at=t0 + 4)
    gh.comment("octo/widgets", n + 1, line, who="funder", at=t0 + 4)
    assert ghrelay.once(net, w.payer, now=t0 + 6, crank=False) == [] and net.sent == 1 and w.nonce() == 1
    # 20 a day for one repository: the relay pays each fee and the order's rent
    saved = json.loads((tmp_path / "ghrelay.json").read_text())
    saved["verify"]["n"]["passkey-fund:octo/widgets"] = ghrelay.PASSKEY_FUND_PER_DAY
    (tmp_path / "ghrelay.json").write_text(json.dumps(saved))
    gh.comment("octo/widgets", n, tp.comment(w, n, seq=1), who="funder", at=t0 + 7)
    [capped] = ghrelay.once(net, w.payer, now=t0 + 9, crank=False)
    assert " fail 20 passkey fundings a day are sent for one repository" in capped and net.sent == 1 and w.nonce() == 1


def test_a_batch_and_a_sellers_claim_posted_as_knos_eval_reach_the_meters_batch_path(monkeypatch):
    """`knos attest --kind batch|claim` posts its token under the same marker as one evaluation. The worker hands it
    to the relay of the second deployment, which sends RecordBatch or ClaimBatch (knos_meter as built, on LiteSVM)."""
    pytest.importorskip("solders.litesvm")
    from _meter import BUYER, SELLER, Meter
    from test_relay2 import JWKS, Net, token
    from knos.settle.v2 import meter
    from knos.settle.v2 import relay as second

    c = Meter()
    net, month, root = Net(c), meter.yyyymm(c.now()), bytes([7]) * 32
    c.open(c.new_mint(), BUYER, 5_000_000)
    monkeypatch.setattr(second, "submit", functools.partial(second.submit, jwks=JWKS, now=c.now()))
    batch = meter.batch_audience(BUYER, SELLER, month, 0, 3, 2, 4_000_000, root)
    claim = meter.batch_audience(BUYER, SELLER, month, 0, 4, 3, 6_000_000, root, kind="claim")
    b = token(c, batch, file="attest.yml", repository_owner_id=BUYER, run_attempt=1)
    s = token(c, claim, file="attest.yml", repository_owner_id=SELLER, run_attempt=1)
    comment = {"body": ghrelay.token_comment("eval", b), "issue_url": "https://api.github.com/repos/o/r/issues/2", "user": {"login": ghrelay.LOG_BOT}}
    assert [tuple(f) for f in ghrelay.tokens([comment])] == [("eval", 2, b, ghrelay.LOG_BOT)]
    for jwt_, kind in ((b, "batch"), (s, "claim")):
        assert ghrelay.misposted("eval", jwt_) is None
        assert ghrelay.misposted("fund", jwt_) == f"posted as knos-fund, but its audience is a {kind} token's"
        assert ghrelay.misposted("verify", jwt_) == f"it is a Knos {kind} token, which is carried under its own marker"
    assert ghrelay.misposted("claim", s) == "posted as knos-claim, but its audience is a claim token's"     # (the meter's claim, not the first deployment's)
    # the first deployment's claim keeps its own marker: knos-eval: carries the meter's three and nothing else
    assert ghrelay.misposted("eval", jwt("knos:claim:1:" + "1" * 44)) == "posted as knos-eval, but its audience is a claim token's"
    assert ghrelay.misposted("eval", jwt("knos2:pay:1:1:9:" + "a" * 40 + ":" + "0" * 64 + ":0:-")) == "posted as knos-eval, but its audience is a pay token's"
    r = ghrelay.relay_one(net, c.payer, "eval", b)
    assert r["ok"] and (r["kind"], r["seq"], r["count"], r["accepted"], r["value"], r["fee"]) == ("batch", 0, 3, 2, 4_000_000, 0), r
    assert r["note"] == (f"Counted batch 0 of month {month} for buyer {BUYER} and seller {SELLER}: 3 evaluations, 2 accepted (the buyer's count, fee 0.00 from "
                         f"the buyer's credits). Merkle root {root.hex()}.")
    book = c.book()
    assert (book.next_seq, book.evaluations, book.accepted, book.value) == (1, 3, 2, 4_000_000)
    r = ghrelay.relay_one(net, c.payer, "eval", s)
    assert r["ok"] and r["kind"] == "claim" and "4 evaluations, 3 accepted (the seller's own count, at no fee)" in r["note"], r
    theirs = c.book(claim=True)
    assert (theirs.next_seq, theirs.evaluations, theirs.accepted) == (1, 4, 3)
    assert ghrelay.log_line("eval", "o/r", 2, s, r).startswith(f"knos-relay eval o/r#2 {ghrelay.token_id(s)} ok sig=")
    # the same batch token again: taken once, refused from a read
    again = ghrelay.relay_one(net, c.payer, "eval", token(c, batch, file="attest.yml", repository_owner_id=BUYER, run_attempt=1))
    assert not again["ok"] and again["kind"] == "batch" and again["why"] == meter.ERRORS[meter.E_SEQ]
    # a relay's result of another kind under the marker is still refused
    assert not ghrelay.relay_one(None, None, "eval", "t", submit=lambda *a: {"ok": True, "kind": "fund", "sigs": ["f"]})["ok"]


# -- what 0.3.15 added: the status line and its reader, and the page that says where a token waits -----------------------------

def _node() -> str:
    import shutil
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    return node


def test_the_status_views_data_is_worked_out_as_its_node_test_says():
    """web/status_data.js is pure functions; tests/web/status_data.mjs works every expected value by hand."""
    import subprocess
    run = subprocess.run([_node(), str(ROOT / "tests" / "web" / "status_data.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert run.returncode == 0 and run.stdout.strip().endswith("all passed"), run.stdout + run.stderr


def test_the_line_the_relay_writes_about_itself_is_the_line_the_status_view_reads():
    """One format, two programs: ghrelay.status_line writes it and web/status_data.js reads it. A field renamed in one
    and not the other shows here."""
    import subprocess
    now = 1_791_021_600.0
    state = {"round": {"at": now - 2, "took": 4.2, "tokens": 3},
             "journal": {"a": {"id": "1" * 16, "state": "waiting", "seen": now - 185, "last": now - 20, "tries": 4},
                         "b": {"id": "2" * 16, "state": "sending", "seen": now - 5, "last": now - 5, "tries": 1},
                         "c": {"id": "3" * 16, "state": "refused", "seen": now - 900, "last": now - 900, "tries": 1, "why": "no"},
                         "d": {"id": "4" * 16, "state": "confirmed", "seen": now - 90_000, "last": now - 90_000, "tries": 9},      # more than a day ago
                         "e": {"id": "5" * 16, "state": "waiting", "seen": now - 9000, "last": now - 9000, "tries": 2}}}            # its comment left the hour the relay reads
    line = ghrelay.status_line(state, now)
    assert line == f"knos-relay status - - ok at={ghrelay._stamp(now - 2)} round=4 tokens=3 waiting=2 oldest=185 retried=4 refused=1"
    comments = [{"user": {"login": ghrelay.LOG_BOT}, "created_at": ghrelay._stamp(now - 4000), "updated_at": ghrelay._stamp(now), "body": line},
                {"user": {"login": ghrelay.LOG_BOT}, "created_at": ghrelay._stamp(now - 30),
                 "body": ghrelay.log_line("proof", "o/r", 9, "x.y.z", {"ok": True, "sigs": ["s"], "note": "paid"}, 12, {"wait": 3, "chain": 9, "tries": 2})
                 + "\n" + ghrelay.log_line("fund", "o/r", 1, "a.b.c", {"ok": False, "why": "the balance does not hold that much"})}]
    script = ("import { summarise, LOG_BOT } from " + json.dumps((ROOT / "web" / "status_data.js").as_uri()) + ";"
              "const c = JSON.parse(process.argv[1]); console.log(JSON.stringify([LOG_BOT, summarise(c, null, Number(process.argv[2]))]));")
    run = subprocess.run([_node(), "--input-type=module", "-e", script, json.dumps(comments), str(int(now))], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert run.returncode == 0, run.stderr
    bot, got = json.loads(run.stdout)
    assert bot == ghrelay.LOG_BOT
    assert got["worker"] == {"ranRecently": True, "lastSeen": int(now), "ago": 0, "from": "status"}
    assert got["lastRound"] == {"at": int(now) - 2, "seconds": 4, "tokens": 3} and got["waiting"] == {"tokens": 2, "oldestSeconds": 185, "asOf": int(now) - 2}
    assert got["refused"] == {"count": 1, "reasons": [{"reason": "the balance does not hold that much", "count": 1, "last": int(now) - 30}]}
    assert got["retries"] == {"count": 4, "carried": 1} and got["answered"] == {"ok": 1, "failed": 1}


def test_the_page_about_the_relay_states_the_relays_own_constants():
    doc = (ROOT / "docs" / "RELAY.md").read_text(encoding="utf-8")
    assert f"up to {ghrelay.SEARCH_EVERY} s (`SEARCH_EVERY`)" in doc and f"{ghrelay.BACKOFF_MOST} s between two tries (`BACKOFF_MOST`)" in doc
    assert f"{ghrelay.CHAIN_NAMES} a pass" in doc and (ghrelay.LATE, ghrelay.HORIZON) == (3600, 70 * 60)
    from knos.settle.v2 import oidc
    assert ghrelay.LATE == oidc.LATE                                  # "an hour past its expiry" is the verifier's rule, not the relay's
    assert "knos-relay status - - ok at=<time> round=<s> tokens=<n> waiting=<n> oldest=<s> retried=<n> refused=<n>" in doc
    assert "knos-relay status - - ok at=<time> round=<s> tokens=<n> waiting=<n> oldest=<s> retried=<n> refused=<n>" in ghrelay.__doc__
    assert "none on devnet" in doc                                    # what is not done is said
    # and what is done says when and on what: the stages were measured on the live log, with the dates of its reads
    assert re.search(r"`scripts/latency_stages\.py` on the live log \(\d{1,2} \w+ 20\d\d, \d\d:\d\d to \d\d:\d\d UTC", doc)
    assert "has not yet been run against the live log" not in doc
