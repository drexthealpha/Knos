"""What 0.3.17 wires into `knos attest`: an evaluation is also a ledger line with its verdict in words; a run that
refused, or could not decide, leaves a receipt that never authorises payment; the judge's reason is in the comment;
insufficient evidence is its own outcome; and an appeal ends on the neutral judge's verdict.

The fakes are tests/_flow.py's; the judge is the stand-in of tests/test_attest_rerun.py, here with the three fields
knos.judge.judge returns since this release (`verdict`, `notes`, `reason`)."""
from __future__ import annotations

import hashlib
import json

from _flow import HUBOT, MONA
from knos import appeal, flow, ghwords, ids, ledger, receipt, terms
from test_attest_rerun import Judge, rerun, signs, staged
from test_flow import BY_TESTS
from test_flow_orders import ORDER, Sellers, attested, world

SHA = "c" * 40


class Worded(Judge):
    """The judge as it answers now: the same verdict, with its word, its notes and its reason."""

    def __init__(self, word: str, reasons: list[str], notes: tuple = ()):
        super().__init__(passed=word == "accepted")
        self.word, self.reasons, self.notes = word, reasons, list(notes)

    def __call__(self, base, pr, cfg, changed=None, sandbox="auto") -> dict:
        got = super().__call__(base, pr, cfg, changed, sandbox=sandbox)
        return {**got, "verdict": self.word, "reasons": self.reasons, "notes": self.notes,
                "reason": "; ".join([*self.reasons, *self.notes]) or "every acceptance check passed"}


def test_an_evaluation_is_also_output_as_a_ledger_line_that_says_its_verdict_and_carries_its_ids(tmp_path):
    w = world(tmp_path)
    w.hub.pull(12, MONA, "Slugify, as the work order asks")
    head, work = w.hub.pulls[12]["head"]["sha"], bytes(range(32))
    w.hub.merge(12)
    w.relay.refusals.append({"ok": True, "kind": "eval", "sigs": ["sigE"], "accepted": True, "fee": 0})
    code, run, _text = attested(w, "eval", order=f"{work.hex()}.3.2500000", GITHUB_REPOSITORY_OWNER_ID=str(HUBOT["id"]), GITHUB_WORKFLOW_SHA=SHA, GITHUB_RUN_ID="77")
    assert code == 0
    e = ledger.parse(run.outputs["evaluation"])
    assert e.audience() == run.outputs["audience"]                    # the line and the signed audience are one evaluation
    assert (e.verdict, e.evaluator, e.run, e.accepted) == ("accepted", f"eval@{SHA}", "77", True)
    line = json.loads(run.outputs["evaluation"])
    assert line["dlv"] == ids.deliverable(work.hex(), 3) and line["evl"] == ids.evaluation(line["dlv"], head, flow.EVAL_POLICY.hex(), f"eval@{SHA}", "77")
    # closed unmerged: the line says rejected
    w.hub.pull(13, MONA, "Slugify, another way")
    w.hub.pulls[13]["state"] = "closed"
    w.relay.refusals.append({"ok": True, "kind": "eval", "sigs": ["sigR"], "accepted": False, "fee": 0})
    code, run, _text = attested(w, "eval", pull=13, order=f"{work.hex()}.3.2500000", GITHUB_REPOSITORY_OWNER_ID=str(HUBOT["id"]))
    e = ledger.parse(run.outputs["evaluation"])
    assert code == 0 and (e.verdict, e.accepted, e.value) == ("rejected", False, 0)


def test_a_judge_that_says_no_word_hands_on_the_verdict_0_3_16_wrote_and_one_that_does_adds_its_word_and_reason(tmp_path):
    w, _head, trees = staged(tmp_path)
    _code, out, _text = rerun(w, trees, Judge(passed=False))
    old = json.loads(out["verdict"])
    assert "verdict" not in old and "reason" not in old and flow._rerun_read(out["verdict"]) == old
    w, _head, trees = staged(tmp_path / "worded")
    code, out, text = rerun(w, trees, Worded("accepted", [], ["contributor tests in tests/test_new.py were run and not counted"]))
    v = json.loads(out["verdict"])
    assert code == 0 and (v["verdict"], v["passed"]) == ("accepted", True) and v["reason"] == "contributor tests in tests/test_new.py were run and not counted"
    assert flow._rerun_read(out["verdict"]) == v and "The judge's reason: contributor tests in tests/test_new.py were run and not counted." in text
    # read as untrusted text: a word that is not a run's, a word that contradicts `passed`, or one of the two fields alone
    for bad in ({**v, "verdict": "disputed"}, {**v, "verdict": "rejected"}, {k: x for k, x in v.items() if k != "reason"}, {**v, "reason": "x" * 301}):
        assert flow._rerun_read(json.dumps(bad)) == "the re-execution's verdict does not have the fields a verdict has"
    assert flow._rerun_read(json.dumps({**flow._rerun_verdict(None, {}), "verdict": "accepted", "reason": ""})).startswith("the re-execution's verdict does not")


def test_a_rejected_run_posts_the_judges_reason_in_the_tables_words_and_leaves_a_receipt_that_authorises_nothing(tmp_path):
    w, head, trees = staged(tmp_path)
    why = "pr: acceptance checks not passed: blackbox"
    code, out, _text = rerun(w, trees, Worded("rejected", [why]))
    v = json.loads(out["verdict"])
    assert code == 1 and (v["verdict"], v["reason"], v["reasons"]) == ("rejected", why, [why])
    sellers = Sellers(w)
    w.env.pop("KNOS_RELAY_KEY")
    code, run, text = signs(w, out["verdict"], sellers, GITHUB_WORKFLOW_SHA=SHA)
    assert code == 1 and w.signer.asked == [] and "token" not in run.outputs and len(w.chain.orders(7)) == 1
    r = json.loads(run.outputs["receipt"])
    assert receipt.check(r) is None and receipt.verdict_of(r) == "rejected" and not receipt.authorises_payment(r)
    assert r["transaction"] is None and r["amounts"]["paid"] == "0" and r["order"] == str(ORDER) and r["evaluator_observed"]["artifact"] == {"commit": head, "pull_request": 12}
    assert r["evidence_source"] == {"kind": "run_record", "reference": hashlib.sha256(out["verdict"].encode()).hexdigest(), "signed_by": None}
    assert r["policy"]["terms_hash"] == hashlib.sha256(terms.canonical(BY_TESTS)).hexdigest() and r["evaluator_observed"]["judge"] == {"kind": "neutral", "version": SHA}
    e = ledger.parse(run.outputs["evaluation"])
    assert (e.verdict, e.accepted, e.artifact, e.seller, e.dlv) == ("rejected", False, head, MONA["id"], r["ids"]["deliverable"])
    [said] = sellers.comments
    first, second, *_rest = said["body"].split("\n")
    assert first == flow.VERDICT + out["verdict"] and second == flow.RECEIPT + run.outputs["receipt"]
    assert f"The judge's reason: {why}. {ghwords.said(why)}" in said["body"] and ghwords.code_of_reason(why) == "judge.acceptance-failed"
    assert "Nothing was signed: the acceptance suite did not pass when it was run again here" in said["body"] and "nothing was signed" in text
    # a run that does not know its workflow's commit writes no receipt, says so, and refuses as before
    code, run, text = signs(w, out["verdict"], sellers)
    assert code == 1 and "receipt" not in run.outputs and "no receipt was written for this run" in text and len(sellers.comments) == 2
    assert not sellers.comments[1]["body"].split("\n")[1].startswith(flow.RECEIPT)


def test_a_run_that_could_not_decide_is_its_own_outcome_nothing_paid_nothing_against_the_supplier_and_it_is_run_again(tmp_path):
    w, head, trees = staged(tmp_path)
    why = "pr: the acceptance checks ran out of time"
    code, out, text = rerun(w, trees, Worded("insufficient_evidence", [why]))
    v = json.loads(out["verdict"])
    assert code == 1 and (v["verdict"], v["passed"]) == ("insufficient_evidence", False) and "the run could not decide" in text and "did not pass" not in text
    assert "It will be run again: nothing is paid, nothing is recorded against the supplier and no evaluation is charged." in text
    sellers = Sellers(w)
    w.env.pop("KNOS_RELAY_KEY")
    before = json.dumps(w.hub.comments, sort_keys=True, default=str)
    code, run, text = signs(w, out["verdict"], sellers, GITHUB_WORKFLOW_SHA=SHA)
    assert code == 1 and w.signer.asked == [] and "token" not in run.outputs and len(w.chain.orders(7)) == 1          # no payment
    assert "This run could not decide (insufficient evidence) whether pull request #12 takes" in text and "run the workflow again" in text
    assert "does not take" not in text and "did not pass" not in text                                                # and no rejection
    assert json.dumps(w.hub.comments, sort_keys=True, default=str) == before                 # nothing is written in the order's repository, its memory included
    r = json.loads(run.outputs["receipt"])
    assert receipt.check(r) is None and receipt.verdict_of(r) == "insufficient_evidence" and not receipt.authorises_payment(r)
    e = ledger.parse(run.outputs["evaluation"])
    assert (e.verdict, e.accepted, e.value) == ("insufficient_evidence", False, 0)           # the ledger line says so, and bills nothing
    [said] = sellers.comments
    assert f"Nothing was signed: this run could not decide (insufficient evidence): {why}. It will be run again" in said["body"]
    assert f"The judge's reason: {why}." in said["body"]
    # a judge that could not run at all, and a base whose checks are not the funded ones: the same outcome, never a rejection
    def broken(*_a, **_k):
        raise RuntimeError("no sandbox on this machine")
    w, _head, trees = staged(tmp_path / "broken")
    _code, out, _text = rerun(w, trees, broken)
    assert json.loads(out["verdict"])["verdict"] == "insufficient_evidence"
    # and with no verdict handed on at all there is nothing certain either: the receipt says insufficient evidence
    code, run, _text = signs(w, None, GITHUB_WORKFLOW_SHA=SHA)
    assert code == 1 and receipt.verdict_of(json.loads(run.outputs["receipt"])) == "insufficient_evidence"


def _appealed(w, head: str, monkeypatch) -> tuple[flow._Kept, dict]:
    """Memory of o/r holding an open appeal of pull request #12's rejection, as `/knos appeal` opens it."""
    store, thash = flow._Kept(), hashlib.sha256(terms.canonical(terms.parse(terms.canonical(BY_TESTS)))).hexdigest()
    record, _reply = appeal.from_comment("the checks pass on my machine", repo="o/r", pull=w.hub.pulls[12], commenter="mona", now=w.clock(), verdict="rejected",
                                         store=store, scope=thash, key=7, artifact=head, evaluator="knos", run=head, terms_hash=thash, mode="tests")
    assert record is not None and appeal.recalled(store, "o/r", record["evaluation"])["state"] == "open"
    monkeypatch.setattr(flow, "_memory", lambda run: store)
    return store, record


def test_an_appeal_ends_on_the_neutral_judges_verdict_accepted_or_rejected_with_the_reason_and_the_comment_says_so(tmp_path, monkeypatch):
    # upheld: the neutral judge ran the suite itself and it did not pass
    w, head, trees = staged(tmp_path)
    store, record = _appealed(w, head, monkeypatch)
    _code, out, _text = rerun(w, trees, Worded("rejected", ["pr: acceptance checks not passed: blackbox"]))
    sellers = Sellers(w)
    w.env.pop("KNOS_RELAY_KEY")
    code, run, _text = signs(w, out["verdict"], sellers, GITHUB_WORKFLOW_SHA=SHA)
    row = appeal.recalled(store, "o/r", record["evaluation"])
    assert code == 1 and row["state"] == "rejected" and "they did not pass: Your change does not pass the acceptance checks." in row["why"]
    ended = "Knos: appeal ended. #12 stays **rejected**."
    assert ended in sellers.comments[-1]["body"] and "Reason it ended: The neutral judge ran the funded acceptance checks again" in sellers.comments[-1]["body"]
    assert any(ended in c["body"] for c in w.hub.comments[12])                              # the pull request is told
    # a second run of an appeal that has ended changes nothing and says nothing of it
    code, run, _text = signs(w, out["verdict"], sellers, GITHUB_WORKFLOW_SHA=SHA)
    assert "appeal ended" not in sellers.comments[-1]["body"] and sum(ended in c["body"] for c in w.hub.comments[12]) == 1
    # overturned: it passed there
    w, head, trees = staged(tmp_path / "passes")
    store, record = _appealed(w, head, monkeypatch)
    code, out, _text = rerun(w, trees, Worded("accepted", []))
    assert code == 0
    code, run, _text = signs(w, out["verdict"])
    row = appeal.recalled(store, "o/r", record["evaluation"])
    assert code == 0 and len(w.signer.asked) == 1 and row["state"] == "accepted" and row["why"].endswith("and they passed.")
    assert any("Knos: appeal ended. #12 is **accepted**: the rejection is overturned." in c["body"] for c in w.hub.comments[12])
    # a run that could not decide ends nothing: the appeal stays open and is asked for again
    w, head, trees = staged(tmp_path / "undecided")
    store, record = _appealed(w, head, monkeypatch)

    def broken(*_a, **_k):
        raise RuntimeError("no sandbox on this machine")
    _code, out, _text = rerun(w, trees, broken)
    code, run, _text = signs(w, out["verdict"], GITHUB_WORKFLOW_SHA=SHA)
    assert code == 1 and appeal.recalled(store, "o/r", record["evaluation"])["state"] == "open"
    # with no appeal in memory nothing is said and nothing is written
    w, head, trees = staged(tmp_path / "none")
    monkeypatch.setattr(flow, "_memory", lambda run: flow._Kept())
    _code, out, _text = rerun(w, trees, Worded("accepted", []))
    code, run, _text = signs(w, out["verdict"])
    assert code == 0 and not any("appeal" in c["body"] for c in w.hub.comments.get(12, []))


# ---- the procurement gate of a standing offer ------------------------------------------------------------------------

class Procured:
    """o/r with files under .knos/procurement/ on its default branch: GitHub's contents API for that folder (a listing
    for a folder, the file for a file), and the World's hub for everything else."""

    def __init__(self, w, files: dict[str, str], down: bool = False):
        self.w, self.files, self.down = w, files, down

    def __call__(self, path: str, data: dict | None = None, method: str | None = None):
        import base64
        import urllib.error
        at = "repos/o/r/contents/.knos/procurement"
        if path.startswith("repos/o/r/issues/comments/") and data is None and method is None:       # one comment, by its id
            return next((c for cs in self.w.hub.comments.values() for c in cs if str(c["id"]) == path.rsplit("/", 1)[1]), None)
        if not path.startswith(at):
            return self.w.hub(path, data, method) if method else self.w.hub(path, data)
        name, _, query = path[len("repos/o/r/contents/"):].partition("?")
        assert query == "ref=main"
        if name in self.files:
            if self.down:
                raise OSError("502 Bad Gateway")
            return {"encoding": "base64", "content": base64.b64encode(self.files[name].encode()).decode()}
        under = sorted({f[len(name) + 1:].split("/")[0] for f in self.files if f.startswith(name + "/")})
        if not under:
            raise urllib.error.HTTPError(path, 404, "Not Found", None, None)
        return [{"path": f"{name}/{x}", "type": "file" if f"{name}/{x}" in self.files else "dir"} for x in under]


def _offer(w, files: dict[str, str] | None, body: str = "/knos offer @mona rate 12 budget 30 checks: test", down: bool = False) -> str:
    from test_flow_orders import plain
    run = w.run(w.hub.commented(7, HUBOT, body))
    if files is not None:
        run._github = Procured(w, files, down)
    flow.command(run)
    return plain(w.hub.knos(7)[-1], 1500)


def test_a_standing_offer_funds_only_when_the_buyers_procurement_files_approve_it_and_with_none_nothing_changes(tmp_path):
    import time

    from knos import approvals, controls
    s, root = controls.sample(), controls.PROCUREMENT
    w = world(tmp_path)
    w.hub.issue(7, "Slugify titles", HUBOT)
    today = time.strftime("%Y-%m-%d", time.gmtime(w.clock()))
    year = today[:4]
    card = {**s["rate_card"], "valid_from": f"{year}-01-01", "valid_to": f"{year}-12-31",
            "outcomes": [{**o, "price": 12} if o["name"] == "bug-fix" else o for o in s["rate_card"]["outcomes"]]}
    envelope = {**s["envelope"], "period_from": f"{year}-01-01", "period_to": f"{year}-12-31", "as_of": today}
    offer = {**s["offers"][0], "suppliers": ["mona"], "cap": 30, "starts": f"{year}-01-01", "ends": f"{year}-12-31"}
    policy = {**s["policy"], "roles": {role: [{**h, "from": f"{year}-01-01", "until": f"{year}-12-31"} for h in held] for role, held in s["policy"]["roles"].items()}}
    files = {f"{root}/rate-cards/{card['name']}.yaml": controls.dump_yaml(card), f"{root}/envelopes/{envelope['name']}.yaml": controls.dump_yaml(envelope),
             f"{root}/offers/{offer['name']}.yaml": controls.dump_yaml(offer), f"{root}/policy.yaml": controls.dump_yaml(policy)}
    # no file under .knos/procurement/: the offer is funded exactly as it was
    plainly = _offer(w, None)
    assert plainly.startswith("Knos: a standing offer for @mona is in escrow on issue #7: 30.00") and len(w.chain.orders(7)) == 1
    assert not any(".knos/procurement/" in p for p in w.hub.asked)                    # one question, answered no, and nothing more is read
    # the files are there and nobody approved the offer: nothing is funded, and the reply says what waits
    refused = _offer(w, files)
    assert refused.startswith("Knos: nothing was funded. Refused: offer `bug-fix-octocat` is not approved. Waits for 1 approver: 360.00 needs 1 approver.") and len(w.chain.orders(7)) == 1
    assert "The files under `.knos/procurement/` on the default branch decide this" in refused
    # another rate than the rate card's, and files GitHub lists and does not give: nothing is funded either
    assert "Refused: no standing offer under .knos/procurement/offers/ names @mona at this rate and cap today." in _offer(
        w, files, "/knos offer @mona rate 13 budget 30 checks: test")
    assert "has procurement files, and they could not be read from GitHub (502 Bad Gateway)" in _offer(w, files, down=True) and len(w.chain.orders(7)) == 1
    # an approver with authority comments, the log records it, and the forge still has the comment: it is funded
    req = dict(subject=f"offer:{offer['name']}", requester=offer["requested_by"], amount=controls.commitment(offer)["value"])
    c = w.hub.say(7, {"login": "mei-acme", "id": 9001}, f"/knos approve offer:{offer['name']}")
    e, why = approvals.from_comment(policy, c, policy_text=files[f"{root}/policy.yaml"], **req)
    assert e is not None, why
    signed = {**files, f"{root}/{approvals.LOG}": json.dumps(e) + "\n"}
    assert _offer(w, signed).startswith("Knos: a standing offer for @mona is in escrow on issue #7: 30.00") and len(w.chain.orders(7)) == 2
    # an approval typed into the log that the forge does not have is not counted
    forged = {**signed, f"{root}/{approvals.LOG}": json.dumps({**e, "source": {**e["source"], "comment_id": 999_999}}) + "\n"}
    assert "is not approved. Waits for 1 approver" in _offer(w, forged) and len(w.chain.orders(7)) == 2


# ---- a quorum whose evaluators share a controller ---------------------------------------------------------------------

def test_a_quorum_of_one_controller_is_said_in_the_paid_comment_and_on_the_statement_line(tmp_path, monkeypatch):
    from knos import statement
    from knos.settle.v2 import order_auto, pay
    from test_flow_orders import ordered, settled
    from test_receipt import VECTORS
    from test_statement import sept
    shared, alone = (receipt.build4(VECTORS["valid_v3"][n]["receipt"]) for n in (2, 1))
    assert shared["evaluator_observed"]["same_controller"] is True and receipt.check(shared) is None           # the receipt's own field, as the chain's rules compute it
    said = "two evaluations, one controller: not independent"
    assert statement.not_independent(shared) == said and statement.not_independent(alone) == "" and statement.not_independent(None) == ""
    # the comment of a quorum order's payment says it, from the payment's receipt; an independent quorum, or no receipt, adds nothing
    asked: list[str] = []
    for held, want in ((shared, True), (alone, False), (None, False)):
        w = ordered(tmp_path / str(len(asked)), flags=pay.F_NEUTRAL | pay.F_FAUCET | order_auto.quorum_flags(2))
        w.chain.bind(MONA)
        monkeypatch.setattr(flow, "_quorum_receipt", lambda run, sig, held=held: asked.append(sig) or held)
        w.relay.refusals.append({"ok": True, "kind": "pay", "sigs": ["sigQ"], "seconds": 30})      # the relay's answer once the last judge of the quorum spoke
        got = settled(w)
        assert got.startswith("Knos: paid. @mona received 20.00") and (f"Its quorum: {said}." in got) is want, got
    assert len(asked) == 3
    w = ordered(tmp_path / "plain")                                                                  # an order with no quorum asks for no receipt
    w.chain.bind(MONA)
    assert "Its quorum" not in settled(w) and len(asked) == 3
    assert flow._quorum_receipt(w.run({}), "sig") is None                                           # no cluster address to ask: nothing, and no error
    # the statement line of a payment recorded with that receipt says it too; without one the record is what it was
    st = sept()
    line, sig = st["lines"][0], shared["transaction"]["signature"]
    plain = statement.pay(st, None, line["invoice_line"], "chain", sig, "2026-10-03")
    noted = statement.pay(st, None, line["invoice_line"], "chain", sig, "2026-10-03", receipt=shared)
    assert "note" not in plain["events"][0] and noted["events"][0] == {**plain["events"][0], "note": said}
    assert statement.lines_now(st, plain)[0]["why"] == line["why"] and statement.lines_now(st, noted)[0]["why"] == (f"{line['why']}; {said}" if line["why"] else said)
    assert any(said in row[5] for row in statement.cells(st, noted)["rows"]) and said in statement.as_csv(st, noted)
    for bad, how in ((shared, "bank"), ({**shared, "version": 9}, "chain")):
        try:
            statement.pay(st, None, line["invoice_line"], how, sig, "2026-10-03", receipt=bad)
        except statement.Refused as why:
            assert "--receipt is not a valid acceptance receipt of this payment" in str(why)
        else:
            raise AssertionError("refused")
    assert "note" not in statement.pay(st, None, line["invoice_line"], "chain", alone["transaction"]["signature"], "2026-10-03", receipt=alone)["events"][0]
