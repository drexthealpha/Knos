"""What 0.3.18 wires into the workflow commands (knos.flow): Knos Terms 3 enforced at funding, at settlement and in the
appeal; the `grace` option; the provisional decision in the status comment; the verdict gate before `knos attest`
reads a verdict; the log issues that say what they are; the quorum's reasons through the public worker's log line;
and what a payment's comment says of two judges with one owner on each build.

The fakes are tests/_flow.py's. With the new thing absent every comment is what it was: the files beside this one pin
that, and each test here says it once more for its own subject."""
from __future__ import annotations

import json

import pytest
from _flow import HUBOT, MONA, REPO, WF_REPO, World, check, claims
from knos import appeal, claim_guard, commands, decide, flow, ghwords, terms, terms3, verdict_gate
from knos.proof import ghrelay
from knos.settle.v2 import order_auto, pay
from knos.settle.v2 import relay as relay2
from test_flow import BOUGHT, BY_TESTS, CHECKS, plain
from test_flow_orders import ORDER, ordered, said, settled, world

PROVE = f"{WF_REPO}/.github/workflows/prove.yml"
OWN = {"name": "own", "issuer": terms3.GITHUB, "repository": REPO, "workflow": PROVE, "owner": "o"}


def document(**fields) -> dict:
    """The terms 3 document of o/r: 20.00 for one pull request that passes `test`, judged by the repository's own run."""
    doc = terms3.base(REPO, REPO)
    doc["checks"] = {**doc["checks"], "deciding": [{"name": "test", "app": 15368}]}
    doc["changes"] = {**doc["changes"], "paths": []}
    doc["price"] = {**doc["price"], "amount": "20.00"}
    doc["evaluators"] = {"quorum": 1, "list": [OWN]}
    for key, value in fields.items():
        doc[key] = {**doc[key], **value} if isinstance(doc.get(key), dict) else value
    return terms3.validate(doc, strict=False)


def with_terms(tmp_path, version: int = 1, **fields) -> tuple[World, dict]:
    w = world(tmp_path, version=version)
    doc = document(**fields)
    w.hub.contents[flow.TERMS3] = terms3.dumps(doc)
    w.signer.more = {"iss": terms3.GITHUB, "repository": REPO}
    return w, doc


# ---- 1. terms 3, enforced ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("version", (1, 2))
def test_fund_terms_funds_the_order_the_document_describes_and_its_terms_carry_the_documents_hash(tmp_path, version):
    w, doc = with_terms(tmp_path, version)
    assert isinstance(commands.parse("/knos fund terms"), commands.FundTerms) and commands.cite(doc) == commands.Fund(20_000_000, checks=("test",), cited=True)
    got = said(w, 7, HUBOT, "/knos fund terms", most=2000)
    assert got.startswith("Knos: 20.00 test USDC from the devnet faucet is in escrow for issue #7 as a work order") and f"{terms3.cite(doc)}." in got
    (address, o), = w.chain.orders(7)
    raw = flow._logged(w.run({}), address, bytes(o.terms), flow.ORDER_LOG)
    assert terms.parse(raw)["contract"] == terms3.digest(doc) and terms.canonical(terms.parse(raw)) == terms.canonical(terms3.order_terms(doc))
    # the same order written out by hand is the document's too
    w2, _doc = with_terms(tmp_path / "typed", version)
    assert terms3.cite(doc) in said(w2, 7, HUBOT, terms3.comment(doc), most=2000)


def test_an_order_that_says_anything_the_document_does_not_is_not_funded_and_each_difference_is_a_sentence(tmp_path):
    for n, (line, why) in enumerate((
            ("/knos fund 25 checks: test", "The order's amount is 25000000 millionths; the terms say 20000000."),
            ("/knos fund 20 checks: test days 30", "The order's deadline is 30 days; the terms say 14."),
            ("/knos fund 20 checks: test warranty 14 holdback 10", "The order's holdback is 10 percent; the terms say 0."),
            ("/knos fund 20 checks: test quorum 2", "The order's quorum is 2 judges; the terms say 1."),
            ("/knos fund 20 checks: test arbiter @erin", "The order's arbiter is erin; the terms name none."),
            ("/knos fund 20 checks: build", "The order's checks, paths or contract hash are not the ones this version of the terms gives."),
            ("/knos fund 20 checks: test paths: src/**", "The order's checks, paths or contract hash are not the ones this version of the terms gives."))):
        w, doc = with_terms(tmp_path / str(n))
        w.hub.checks[w.hub.head] = [check("test"), check("build")]
        got = said(w, 7, HUBOT, line, most=2000)
        assert got.startswith(f"Knos: nothing was funded. This repository's terms (`.knos/terms.json`: {doc['name']} version 1) and this order do not say "
                              "the same thing. ") and why in got and got.endswith("publish a new version of the terms first."), got
        assert w.chain.orders(7) == [] and w.signer.asked == []                                    # nothing was signed
    # `grace` against terms that say a late token is refused (on the build that has the option)
    w, _doc = with_terms(tmp_path / "grace", version=2)
    assert "the terms say a token presented late is refused." in said(w, 7, HUBOT, "/knos fund 20 checks: test grace", most=2000) and w.signer.asked == []


def test_fund_terms_with_no_document_a_broken_one_or_no_work_orders_funds_nothing_and_says_which(tmp_path):
    w = world(tmp_path, version=1)
    got = said(w, 7, HUBOT, "/knos fund terms")
    assert got.startswith("Knos: nothing was funded. `/knos fund terms` funds the order this repository's terms describe, and it has none") and w.signer.asked == []
    broken = {**document(), "deadline": {"days": 14, "late": "accepted"}}
    w.hub.contents[flow.TERMS3] = json.dumps(broken)
    for line in ("/knos fund terms", "/knos fund 20"):
        got = said(w, 7, HUBOT, line)
        assert "says it is a Knos Terms 3 document, and it is not one an order can be funded on: `deadline.late` is refused" in got and w.signer.asked == []
    w.hub.contents[flow.TERMS3] = terms3.dumps(terms3.template("support-resolution"))            # a template that cannot be funded
    assert "These terms cannot fund an order: `support-resolution` describes work nothing can be paid for yet (not built: needs a signing system of record)." in said(w, 7, HUBOT, "/knos fund terms") and w.signer.asked == []
    w0, _doc = with_terms(tmp_path / "v0", version=0)                                             # the escrow holds no work orders: a job cannot carry these terms
    assert "describe a work order, and the escrow on this cluster does not hold work orders yet" in said(w0, 7, HUBOT, "/knos fund 20") and w0.signer.asked == []
    # a file that is not Knos Terms 3 keeps its meaning, and a repository with none funds as it always did
    w.hub.contents[flow.TERMS3] = json.dumps({"standard": "Knos Terms 1", "name": "old"})
    got = said(w, 7, HUBOT, "/knos fund 20")
    assert got.startswith("Knos: 20.00 test USDC from the devnet faucet is in escrow for issue #7 as a work order") and "Acceptance is governed" not in got


def funded_under(tmp_path, version: int = 1, **fields) -> tuple[World, dict]:
    """An order funded with `/knos fund terms` an hour ago, and pull request #12 open for it with `test` passed."""
    w, doc = with_terms(tmp_path, version, **fields)
    assert terms3.cite(doc) in said(w, 7, HUBOT, "/knos fund terms", most=2000)
    w.clock.sleep(3600)
    w.hub.checks[w.hub.pull(12, MONA, "Fixes #7")["head"]["sha"]] = [check("test")]
    w.chain.bind(MONA)
    return w, doc


@pytest.mark.parametrize("version", (1, 2))
def test_settle_signs_for_an_order_under_terms_3_only_as_an_evaluator_its_terms_name(tmp_path, version):
    w, _doc = funded_under(tmp_path / "own", version)
    assert settled(w).startswith("Knos: paid. @mona received 20.00 test USDC for issue #7, in full")
    # the terms name another workflow: GitHub signed this run, nothing is sent, and the comment says who may judge
    w, doc = funded_under(tmp_path / "other", version, evaluators={"list": [{**OWN, "workflow": f"{WF_REPO}/.github/workflows/attest.yml"}]})
    sent = len(w.relay.submitted)
    got = settled(w)
    assert "Knos Terms 3: o/r version 1) name who may judge it (`own`), and this run is none of them" in got and f"it ran `{PROVE}` in o/r" in got, got
    assert len(w.relay.submitted) == sent and w.chain.orders(7)[0][1].state == "open" and "received" not in got
    # the document moved on to a version 2: the order is still judged by the version it cites, found in the file's history
    w, doc = funded_under(tmp_path / "moved", version)
    w.hub.contents[flow.TERMS3] = terms3.dumps(document(version=2, deadline={"days": 30}))
    assert flow._terms3_cited(w.run({}), terms3.digest(doc)) is None                             # (this forge lists no history of the file)
    got = settled(w, code=1)
    assert "are not among the last versions of `.knos/terms.json`" in got and w.chain.orders(7)[0][1].state == "open"
    past = w.hub.__call__

    class History(type(w.hub)):
        def __call__(self, path, data=None, method=None):
            if path.startswith("repos/o/r/commits?path="):
                return [{"sha": "d" * 40}]
            if path == f"repos/o/r/contents/{flow.TERMS3}?ref={'d' * 40}":
                return self._content({}, None, None, "old-terms")
            return past(path, data, method)
    w.hub.__class__ = History
    w.hub.contents["old-terms"] = terms3.dumps(doc)
    assert flow._terms3_cited(w.run({}), terms3.digest(doc)) == doc
    run = w.run({"inputs": {"pull": "12"}})
    assert flow.settle(run) == 0 and plain(w.hub.knos(12)[-1], 1500).startswith("Knos: paid. @mona received 20.00")


def test_attest_signs_for_an_order_under_terms_3_only_from_a_repository_its_terms_let_judge(tmp_path):
    from test_flow_orders import attested
    anyone = {"name": "neutral", "issuer": terms3.GITHUB, "repository": "*", "workflow": PROVE, "owner": "*"}
    # the terms name the order's own repository only: a run anywhere else signs nothing that is sent
    w, _doc = funded_under(tmp_path / "own")
    w.hub.merge(12)
    w.signer.more = {"iss": terms3.GITHUB, "repository": "erin/judge"}
    code, _run, text = attested(w, "pay")
    assert code == 1 and "Nothing is sent: its terms (Knos Terms 3: o/r version 1) name who may judge it (`own`), and this run is none of them" in text
    assert w.relay.submitted[1:] == [] and w.chain.orders(7)[0][1].state == "open"
    # the terms let anyone's repository judge, except a party's: the pull request's author is one, a third account is not
    w, _doc = funded_under(tmp_path / "anyone", evaluators={"list": [OWN, anyone]})
    w.hub.merge(12)
    w.signer.more = {"iss": terms3.GITHUB, "repository": "mona/knos-attest"}
    code, _run, text = attested(w, "pay")
    assert code == 1 and "name who may judge it (`neutral`, `own`), and this run is none of them: it ran" in text and "in mona/knos-attest" in text
    w.signer.more = {"iss": terms3.GITHUB, "repository": "erin/judge"}
    code, _run, text = attested(w, "pay")
    assert code == 0 and "Solana took it" in text and w.chain.orders(7) == []


def test_an_order_with_no_terms_3_is_settled_as_before_and_asks_github_for_no_terms(tmp_path):
    w = ordered(tmp_path)
    w.chain.bind(MONA)
    assert settled(w).startswith("Knos: paid. @mona received 20.00") and not any(flow.TERMS3 in p for p in w.hub.asked)


def test_an_appeal_outside_the_window_the_terms_give_is_refused_with_the_sentence(tmp_path):
    w, doc = with_terms(tmp_path, checks={"deciding": [{"name": "test", "app": 15368}]})
    assert terms3.cite(doc) in said(w, 7, HUBOT, "/knos fund terms", most=2000)
    w.clock.sleep(3600)
    w.hub.checks[w.hub.pull(12, MONA, "Fixes #7")["head"]["sha"]] = [check("test", "failure")]
    w.chain.bind(MONA)
    assert "not paid" in settled(w)                                                               # rejected: remembered in the knos-memory issue, with its time
    rejected = w.clock()
    assert appeal.window_closed(doc, rejected, rejected + 7 * 86400) == "" and "give 7 days" in appeal.window_closed(doc, rejected, rejected + 7 * 86400 + 1)
    w.clock.sleep(8 * 86400)
    got = said(w, 12, MONA, "/knos appeal the check failed on a flaky runner")
    assert got.startswith("Knos: no appeal was opened. The terms this order was funded under (Knos Terms 3: o/r version 1) give 7 days after a rejection "
                          "to appeal it, and this pull request was rejected on 2026-09-21.") and "Nothing moved" in got, got
    # inside the window the appeal is opened as any other
    w2, doc = with_terms(tmp_path / "in")
    said(w2, 7, HUBOT, "/knos fund terms", most=2000)
    w2.clock.sleep(3600)
    w2.hub.checks[w2.hub.pull(12, MONA, "Fixes #7")["head"]["sha"]] = [check("test", "failure")]
    w2.chain.bind(MONA)
    settled(w2)
    w2.clock.sleep(86400)
    assert "no appeal was opened" not in said(w2, 12, MONA, "/knos appeal the check failed on a flaky runner", most=2500)


# ---- 2. grace ---------------------------------------------------------------------------------------------------------

def test_grace_is_an_option_of_fund_that_the_token_signs_on_2_2_and_a_plain_refusal_on_the_builds_before_it(tmp_path):
    cmd = commands.parse("/knos fund 20 grace")
    assert isinstance(cmd, commands.Fund) and cmd.grace is True and commands.parse("/knos fund 20").grace is False
    assert commands.parse("/knos fund 20 grace grace").reply.startswith("Knos: that was not understood: `grace` is written twice")
    assert commands.parse("/knos offer @mona rate 5 budget 20 grace").reply.startswith("Knos: that was not understood: `grace` is not something this command takes")
    w = world(tmp_path / "new", version=2)
    got = said(w, 7, HUBOT, "/knos fund 20 grace", most=2000)
    options = bytes.fromhex(w.signer.asked[-1].split(":")[-1])
    assert options[33] == 1 and options == pay.opts(pay.F_NEUTRAL, reserve_days=7, grace=True) and len(w.chain.orders(7)) == 1
    assert "still pays for 2 hours after it (`grace`). If it is not paid by then, the money and the fee go back to where they came from." in got
    w = world(tmp_path / "plain", version=2)                                                      # without the word the options are what they were
    assert "grace" not in said(w, 7, HUBOT, "/knos fund 20", most=2000) and bytes.fromhex(w.signer.asked[-1].split(":")[-1])[33] == 0
    for version, words in ((1, "the escrow that is live on this cluster does not know that option yet (it comes with knos_pay 2.2). Leave out `grace`"),
                           (0, "`grace` is an option of a work order, and the escrow on this cluster does not hold work orders yet")):
        w = world(tmp_path / f"v{version}", version=version)
        got = said(w, 7, HUBOT, "/knos fund 20 grace")
        assert got.startswith("Knos: nothing was funded. ") and words in got and w.signer.asked == [] and w.chain.orders(7) == [] and w.chain.jobs(7) == []


def test_a_receipts_declared_accounts_are_the_ones_of_the_terms_the_order_cites_or_none(tmp_path):
    """`flow._declared`: what `knos attest` hands knos.receipt.build5. The accounts the order's own Knos Terms 3 document
    declares to be one party; nothing for an order that cites no document, a version that is not found, or a forge
    that does not answer: nothing is declared on a guess."""
    w, doc = with_terms(tmp_path, evaluators={"quorum": 1, "list": [OWN], "related": [[8002, 7001], [9003, 7001]]})
    assert terms3.declared(doc) == [[7001, 8002, 9003]]
    run = w.run({})
    assert flow._declared(run, {"contract": terms3.digest(doc)}) == [[7001, 8002, 9003]]
    assert flow._declared(run, {}) == [] and flow._declared(run, None) == [] and flow._declared(run, {"contract": "ab" * 32}) == []
    plain_w, plain_doc = with_terms(tmp_path / "plain")
    assert flow._declared(plain_w.run({}), {"contract": terms3.digest(plain_doc)}) == []        # terms that declare nobody
    down = w.run({})
    down.github = lambda path, data=None, method=None: (_ for _ in ()).throw(OSError("502"))
    assert flow._declared(down, {"contract": terms3.digest(doc)}) == []


# ---- 3. the provisional decision --------------------------------------------------------------------------------------

def _settling(w: World) -> str:
    """The words of the status comment's "accepted, settling" edit of the next settlement of pull request #12."""
    before = len(w.hub.posted)
    assert flow.settle(w.run(w.hub.merge(12))) == 0
    return next((d["body"].split("\n\n" + flow.STATUS)[0] for _p, d in w.hub.posted[before:] if str(d.get("body", "")).startswith("Knos: accepted, settling.")), "")


def test_the_accepted_edit_carries_the_provisional_decision_and_a_failure_of_decide_never_blocks_the_payment(tmp_path, monkeypatch, capsys):
    usual = "The payment to @mona is on its way to Solana; this comment is edited when it lands."
    w = ordered(tmp_path / "none")
    w.chain.bind(MONA)
    assert _settling(w).endswith(usual)                                                           # a relay with no `precheck` to ask: the comment is what it was
    asked: list = []
    monkeypatch.setattr(relay2, "precheck", lambda ledger, payer, jwt, terms=None, jwks=None, now=None: asked.append((ledger, jwt)))
    w = ordered(tmp_path / "decided")
    w.chain.bind(MONA)
    w.relay.precheck = relay2.precheck
    got = _settling(w)
    (ledger, jwt), = asked
    doc = decide.provisional(decide.token(jwt, terms.canonical(BOUGHT), ledger=w.chain), at=int(w.clock()) - 30, jwt=jwt, terms=terms.canonical(BOUGHT))
    line = decide.comment_line(doc)
    assert ledger is w.chain and claims(jwt)["aud"].startswith(f"knos3:pay:{ORDER}:") and got.endswith(f"{usual} {line}"), got
    assert line.startswith("Provisional: accepted (everything the chain will ask of this token holds now). Not paid yet") and decide.check(doc) is None
    assert "paid." not in got.replace("Not paid yet", "") and plain(w.hub.knos(12)[-1], 1500).startswith("Knos: paid. @mona received 20.00")
    # a refusal the relay's reads would give is said as provisional too, and the token still goes to the chain, which decides
    monkeypatch.setattr(relay2, "precheck", lambda *a, **k: {"ok": False, "kind": "pay", "why": "the order is not open"})
    w = ordered(tmp_path / "refused")
    w.chain.bind(MONA)
    w.relay.precheck = relay2.precheck
    assert "Provisional: rejected (the order is not open). Not paid yet" in _settling(w) and w.chain.orders(7) == []
    # decide itself fails: logged, nothing in the comment, and the payment is made
    monkeypatch.setattr(decide, "token", lambda *a, **k: 1 / 0)
    w = ordered(tmp_path / "broken")
    w.chain.bind(MONA)
    w.relay.precheck = relay2.precheck
    capsys.readouterr()
    assert _settling(w).endswith(usual) and plain(w.hub.knos(12)[-1], 1500).startswith("Knos: paid. @mona received 20.00")
    assert "the provisional decision could not be made (ZeroDivisionError" in capsys.readouterr().err


def test_where_the_offline_half_decides_its_line_is_posted_first_and_one_chain_request_replaces_it(tmp_path, monkeypatch, capsys):
    """0.3.19: `decide.offline` (no network) gives the line that is posted at once; `decide.chain_check` (one request)
    then gives the line that replaces it. The relay's whole precheck is not asked. A chain that does not answer, or a
    check that fails, changes nothing and stops nothing."""
    usual = "The payment to @mona is on its way to Solana; this comment is edited when it lands."
    monkeypatch.setattr(relay2, "precheck", lambda *a, **k: pytest.fail("the relay's whole precheck was asked"))
    offline = {"decision": "accepted", "why": decide.OFFLINE, "kind": "pay", "chain_read": False, "already": False, "rules": decide.RULES_OFFLINE}
    monkeypatch.setattr(decide, "offline", lambda jwt, terms=None, **k: dict(offline))
    asked: list = []

    def settling(name: str, chain_check) -> tuple[World, list[str]]:
        monkeypatch.setattr(decide, "chain_check", chain_check)
        w = ordered(tmp_path / name)
        w.chain.bind(MONA)
        w.relay.precheck = relay2.precheck
        before = len(w.hub.posted)
        assert flow.settle(w.run(w.hub.merge(12))) == 0
        return w, [d["body"].split("\n\n" + flow.STATUS)[0] for _p, d in w.hub.posted[before:] if str(d.get("body", "")).startswith("Knos: accepted, settling.")]

    def answered(jwt, *, ledger, order=None, timeout=decide.CHAIN_TIMEOUT):
        asked.append((ledger, order))
        return {"read": True, "round_trips": 1, "why": "", "now": int(claims(jwt)["iat"]), "token_used": False, "paused_until": 0, "order": None}
    w, (first, second) = settling("answered", answered)
    assert asked == [(w.chain, None)]                                    # one request, of this run's own chain
    assert first.endswith(f"{usual} Provisional: accepted ({decide.OFFLINE}). Not paid yet: the chain settles next. Provisional receipt " + first[-17:])
    assert second.startswith(first.split(" Provisional: ")[0]) and "Provisional: accepted (decided from the signed evidence; the chain shows the token is unused" in second
    assert first[-17:] != second[-17:] and "paid." not in second.replace("Not paid yet", "")           # a second provisional receipt, and never "paid"
    assert plain(w.hub.knos(12)[-1], 1500).startswith("Knos: paid. @mona received 20.00")
    # the chain shows the token used already: said, still provisional, and the chain decides
    w, (first, second) = settling("used", lambda jwt, **k: {**answered(jwt, **k), "token_used": True})
    assert "the chain shows this token used already" in second and "Provisional: accepted" in second
    # the chain did not answer in time: the offline line stays, once
    w, lines = settling("silent", lambda jwt, **k: {"read": False, "round_trips": 1, "why": "the chain did not answer (TimeoutError: no answer in 2 s)", "now": None,
                                                    "token_used": None, "paused_until": None, "order": None})
    assert len(lines) == 1 and f"Provisional: accepted ({decide.OFFLINE})" in lines[0]
    assert plain(w.hub.knos(12)[-1], 1500).startswith("Knos: paid. @mona received 20.00")
    # the check itself fails: logged, the offline line stays, the payment is made
    capsys.readouterr()
    w, lines = settling("broken", lambda jwt, **k: 1 / 0)
    assert len(lines) == 1 and "chain state not yet read" in lines[0] and plain(w.hub.knos(12)[-1], 1500).startswith("Knos: paid. @mona received 20.00")
    assert "the chain check of the provisional decision could not be made (ZeroDivisionError" in capsys.readouterr().err
    # an offline rejection is said at once too, and nothing overrules it
    monkeypatch.setattr(decide, "offline", lambda jwt, terms=None, **k: {**offline, "decision": "rejected", "why": "the signature is not the issuer's"})
    w, lines = settling("rejected", answered)
    assert len(lines) == 2 and all("Provisional: rejected (the signature is not the issuer's)" in line for line in lines)


# ---- 4. the verdict gate ----------------------------------------------------------------------------------------------

def test_a_rerun_verdict_goes_through_the_gate_first_and_what_two_readers_would_read_differently_is_refused():
    v = flow._rerun_verdict(None, {"GITHUB_REPOSITORY": "mona/knos-attest"})
    text = json.dumps(v, sort_keys=True, separators=(",", ":"))
    verdict_gate.shape(text)
    assert flow._rerun_read(text) == v
    twice = text[:-1] + ',"reexecuted":false}'                                                    # the same key twice: json.loads keeps the last, another reader the first
    assert json.loads(twice) == v and flow._rerun_read(twice) == ("the re-execution's verdict is not text every reader reads the same way: the verdict is not "
                                                                  "one JSON object with each key once")
    assert flow._rerun_read(text[:-1] + ',"sentence":"café"}').startswith("the re-execution's verdict is not text every reader reads the same way")
    # what the reader refused before, it refuses in the words it had
    assert flow._rerun_read("x" * 9000) == "the re-execution's verdict is larger than a verdict is" and flow._rerun_read("not json") == "the re-execution's verdict is not JSON"


def test_settle_tests_reads_the_bundle_at_the_base_commit_the_judges_verdict_names_and_refuses_another_runs_verdict(tmp_path):
    from test_flow import judged
    base, sha = "b" * 40, "c" * 40

    def verdict(w, head, **more) -> str:
        return json.dumps({"v": 2, "kind": "judge", "passed": True, "repository_id": 555, "run": 77, "attempt": 1, "workflow_sha": sha, "pull": 12, "issue": 7,
                           "head": head, "base": base, "accept": BY_TESTS["accept"], "changed": "0" * 64, "changed_count": 1, "runner": "blackbox", "image": "",
                           **more}, sort_keys=True, separators=(",", ":"))

    env = {"GITHUB_REPOSITORY_ID": "555", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_WORKFLOW_SHA": sha, "GITHUB_SHA": base}
    w, head = judged(tmp_path / "held")
    run = w.run({}, VERDICT=verdict(w, head), **env)
    assert flow.settle(run, tests=True, pull=12, head=head, issue=7) == 0 and run.judged_at == base
    assert f"repos/o/r/contents/.knos/acceptance?ref={base}" in w.hub.asked and plain(w.hub.knos(12)[-1], 1500).startswith("Knos: paid.")
    # a verdict of another base commit, or one that did not pass: nothing is signed
    for n, (more, why) in enumerate((({"base": "e" * 40}, "The verdict is of another base commit than this job signs for."),
                                     ({"passed": False}, "The acceptance checks did not pass."), ({"extra": 1}, "The verdict does not have exactly the fields a verdict has."))):
        w, head = judged(tmp_path / str(n))
        run = w.run({}, VERDICT=verdict(w, head, **more), **env)
        assert flow.settle(run, tests=True, pull=12, head=head, issue=7) == 1 and w.signer.asked == [] and w.hub.knos(12) == []
    # with no verdict handed to the step it reads what it read before: the run's own commit
    w, head = judged(tmp_path / "none")
    run = w.run({}, **env)
    assert flow.settle(run, tests=True, pull=12, head=head, issue=7) == 0 and run.judged_at == "" and CHECKS


# ---- 5. the claim guard asks flow ---------------------------------------------------------------------------------------

def test_funded_is_flows_own_reading_and_the_claim_guard_asks_it(tmp_path, monkeypatch):
    w = ordered(tmp_path)
    run = w.run({})
    assert flow.funded(run, 555, 7) is True and flow.funded(run, 555, 8) is False and claim_guard.funded(run, 555, 7) is True
    monkeypatch.setattr(flow, "funded", lambda run, repo_id, issue: (repo_id, issue) == (555, 8))
    assert claim_guard.funded(run, 555, 7) is False and claim_guard.funded(run, 555, 8) is True
    w.chain.down = True
    monkeypatch.undo()
    with pytest.raises(Exception):      # noqa: B017, PT011 - the chain did not answer: not knowing is not "there is none"
        flow.funded(w.run({}), 555, 7)


# ---- 6. a log issue says what it is -----------------------------------------------------------------------------------

class Forge:
    """A repository's issues as `_tokens_issue` touches them: list the open ones, open one, edit one's body."""

    def __init__(self, issues: list[dict] | None = None):
        self.issues, self.wrote = list(issues or []), []

    def __call__(self, path: str, data: dict | None = None, method: str | None = None):
        if data is None:
            assert path == "repos/mona/knos-attest/issues?state=open&per_page=100"
            return [dict(i) for i in self.issues]
        self.wrote.append((method or "POST", path, data))
        if method == "PATCH":
            next(i for i in self.issues if path == f"repos/mona/knos-attest/issues/{i['number']}").update(data)
            return {}
        self.issues.append({"number": len(self.issues) + 1, **data})
        return {"number": len(self.issues)}


def test_the_tokens_issue_says_it_is_a_log_and_an_older_one_is_edited_once_to_say_so():
    said_ = "This is a log written by a workflow. It is not a task and carries no payment. "
    assert ghwords.MACHINE == said_ and flow.TOKENS_BODY.startswith(said_ + "Knos posts here the tokens GitHub signed")
    assert claim_guard.LOG_LINE in ghwords.MACHINE                                                # the claim guard's answer and the issue's body say the same thing
    new = Forge()
    assert flow._tokens_issue(new, "mona/knos-attest") == 1 and new.issues[0]["body"] == flow.TOKENS_BODY
    assert flow._tokens_issue(new, "mona/knos-attest") == 1 and len(new.wrote) == 1               # made with the sentence: never edited
    old = Forge([{"number": 3, "title": "knos tokens", "pull_request": {}, "body": "x"}, {"number": 9, "title": flow.TOKENS, "body": "Knos posts here the tokens."}])
    assert flow._tokens_issue(old, "mona/knos-attest") == 9
    assert old.wrote == [("PATCH", "repos/mona/knos-attest/issues/9", {"body": said_ + "Knos posts here the tokens."})]
    assert flow._tokens_issue(old, "mona/knos-attest") == 9 and len(old.wrote) == 1 and old.issues[0]["body"] == "x"      # once; and never another issue
    # a forge that takes no edit (a token with no `issues: write`, a reader of two arguments): the number is still found
    assert flow._tokens_issue(lambda path, data=None: [{"number": 9, "title": flow.TOKENS, "body": ""}], "mona/knos-attest") == 9
    assert ghwords.machine_body(said_ + "x") is None and ghwords.machine_body(None) == said_


# ---- 7. and 8. a quorum through the public worker's line, and two judges with one owner --------------------------------

SAME = "the judge repository has the same owner as another judge that passed this commit, and runs in repositories of one owner are one judge"


def test_the_workers_line_words_an_orders_quorum_so_that_its_reasons_reach_the_comment(tmp_path):
    q = {"have": 1, "of": 2, "uncounted": [SAME], "again": ["the order's own repository"]}
    r = {"ok": True, "kind": "pay", "order": str(ORDER), "sigs": ["sigQ"], "paid": [], "quorum": q}
    note = ghrelay.note(r)
    assert note == ghwords.quorum_note(ORDER, q) and note.startswith(f"1 of 2 judges have passed this commit for order {ORDER}: nothing is paid until 2 have. Not counted: ")
    assert ghwords.quorum_read(note) == q and ghwords.quorum_read(note + " (another relayer carried it first)") == q
    assert ghwords.quorum_read(ghwords.quorum_note(ORDER, {"have": 2, "of": 3})) == {"have": 2, "of": 3} and ghwords.quorum_read("relayed by the worker") is None
    paid = {"ok": True, "kind": "pay", "order": str(ORDER), "sigs": ["s"], "paid": [{"amount": 20_000_000, "to": "W", "payee_id": 4242}]}
    assert ghrelay.note(paid) == f"20.00 was paid to W (GitHub user id 4242) for order {ORDER}." and ghwords.quorum_read(ghrelay.note(paid)) is None     # a payment's words are what they were
    # the flow, with no relay key: the worker's line is the only thing that comes back, and the comment says nothing moved and why
    w = ordered(tmp_path, flags=pay.F_NEUTRAL | pay.F_FAUCET | order_auto.quorum_flags(2))
    w.version = 2
    w.env.pop("KNOS_RELAY_KEY")
    w.chain.bind(MONA)

    def wait_for(tid, log_repo, timeout, every=3.0, get=None):
        n, marker, jwt, _terms = next(x for x in w.worker.posted() if w.worker.token_id(x[2]) == tid)
        return ghrelay.log_line(marker, REPO, n, jwt, {**r, "note": ghrelay.note(r)}, 39).replace(ghrelay.token_id(jwt), tid)
    w.worker.wait_for = wait_for
    got = settled(w)
    assert got.startswith("Knos: not paid yet. ") and "1 of the 2 different judges its funder asked for have passed this commit, so nothing is paid until 2 have." in got
    assert f"It counts 1 because {SAME[:150]}" in got and "The order's own repository passed this commit before the escrow's upgrade to knos_pay 2.2" in got
    assert "received" not in got and w.chain.orders(7)[0][1].state == "open"
    line = wait_for(w.worker.token_id(w.worker.posted()[-1][2]), "", 0)
    assert flow._verdict(line, "pay", w.worker.token_id(w.worker.posted()[-1][2]))["quorum"] == q


def test_two_judges_of_one_owner_paid_on_2_1_say_so_in_ghwords_words_and_on_2_2_nothing_moves_and_the_comment_says_why(tmp_path, monkeypatch):
    from knos import receipt
    from test_receipt import VECTORS
    shared = receipt.build4(VECTORS["valid_v3"][2]["receipt"])
    assert shared["evaluator_observed"]["same_controller"] is True and len(shared["evaluator_observed"]["evaluators"]) == 2
    words = "two judges, one owner: counted as two by the build that is live; the next build counts one"
    assert ghwords.one_owner(2) == words and ghwords.one_owner(3).startswith("three judges, one owner: counted as three")
    monkeypatch.setattr(flow, "_quorum_receipt", lambda run, sig: shared)
    # 2.1 is live: it counts markers, so the second judge's token paid. The comment says what the next build will count
    w = ordered(tmp_path / "v1", flags=pay.F_NEUTRAL | pay.F_FAUCET | order_auto.quorum_flags(2))
    w.version = 1
    w.chain.bind(MONA)
    w.relay.refusals.append({"ok": True, "kind": "pay", "sigs": ["sigQ"], "seconds": 30})
    got = settled(w)
    assert got.startswith("Knos: paid. @mona received 20.00") and "Its quorum: two evaluations, one controller: not independent." in got
    assert f"{words[0].upper()}{words[1:]}." in got, got
    # 2.2 is live: the relay's answer is a judge recorded and one not counted. Nothing moved, and the comment says why
    w = ordered(tmp_path / "v2", flags=pay.F_NEUTRAL | pay.F_FAUCET | order_auto.quorum_flags(2))
    w.version = 2
    w.chain.bind(MONA)
    w.relay.refusals.append({"ok": True, "kind": "pay", "sigs": ["sigQ"], "seconds": 30, "paid": [], "quorum": {"have": 1, "of": 2, "uncounted": [SAME]}})
    got = settled(w)
    assert got.startswith("Knos: not paid yet. ") and "so nothing is paid until 2 have." in got and f"It counts 1 because {SAME}." in got, got
    assert "received" not in got and "one owner: counted as" not in got and "owns no repository that judged it" in got
    # a payment on 2.2 never says the 2.1 sentence, and an independent quorum on 2.1 does not either
    w = ordered(tmp_path / "v2paid", flags=pay.F_NEUTRAL | pay.F_FAUCET | order_auto.quorum_flags(2))
    w.version = 2
    w.chain.bind(MONA)
    w.relay.refusals.append({"ok": True, "kind": "pay", "sigs": ["sigQ"], "seconds": 30})
    assert "counted as two" not in settled(w)
    monkeypatch.setattr(flow, "_quorum_receipt", lambda run, sig: None)
    w = ordered(tmp_path / "v1apart", flags=pay.F_NEUTRAL | pay.F_FAUCET | order_auto.quorum_flags(2))
    w.version = 1
    w.chain.bind(MONA)
    w.relay.refusals.append({"ok": True, "kind": "pay", "sigs": ["sigQ"], "seconds": 30})
    assert "one owner" not in settled(w)
