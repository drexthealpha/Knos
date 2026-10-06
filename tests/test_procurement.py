"""Procurement as files in the buyer's repository: a rate card, a standing offer and a budget envelope
(src/knos/controls.py), and the approval policy with its chain (src/knos/approvals.py). Also the cases
web/procure.js must answer alike (tests/data/procure_cases.json; tests/web/procure.mjs runs them in node):

    python tests/test_procurement.py        write the cases file again, after a sentence changed
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("solders")

from knos import approvals, commands, controls  # noqa: E402

CASES = Path(__file__).parent / "data" / "procure_cases.json"
S = controls.sample()
CARD, ENV, OFFER, POLICY = S["rate_card"], S["envelope"], S["offers"][0], S["policy"]
REQ = dict(subject="offer:bug-fix-octocat", requester="ravi-acme", amount=1_200_000_000)
U = 1_000_000


def but(doc: dict, **change) -> dict:
    out = copy.deepcopy(doc)
    for k, v in change.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def ev(who: str, at: str = "2026-10-03T10:00:00Z", role: str = "approver", subject: str = REQ["subject"], amount: int = REQ["amount"]) -> dict:
    return approvals.event(subject=subject, amount=amount, requester="ravi-acme", approver=who, approver_id=1, role=role, at=at, authority="", policy_sha256="",
                           source={"kind": "forge comment", "forge": "github", "url": f"https://github.com/acme/widgets/issues/12#{who}-{at}", "comment_id": 1, "body_sha256": ""})


# ---- the three objects ----------------------------------------------------------------------------------------------------
def test_the_sample_is_sound_and_reads_back_from_its_own_file():
    assert controls.card_problems(CARD, controls.published_terms()) == []
    assert controls.offer_problems(OFFER, CARD) == []
    assert controls.envelope_problems(ENV) == []
    assert approvals.policy_problems(POLICY) == []
    for doc in (CARD, ENV, OFFER, POLICY):
        assert controls.read_yaml(controls.dump_yaml(doc)) == doc


def test_a_file_outside_the_part_of_yaml_read_is_refused_with_its_line():
    for text, said in (("a: {b: 1}", "Line 1: these files use plain keys"), ("a: 1\n\tb: 2", "Line 2: indent with spaces"), ("a: 1\na: 2", "Line 2: `a` is written twice."),
                       ("a:\n  b: 1\n c: 2", "Line 3: the indentation matches nothing above it."), ("", "The file is empty."), ('a: "open', "Line 1: the quoted text")):
        with pytest.raises(controls.Unread, match=said.replace("`", ".")):
            controls.read_yaml(text)
    assert controls.read_yaml('# a card\nname: x  # note\nlist: [a, "b, c", 3]\nrows:\n- k: 1\n  v: "#1"\n- 12.5\n') == {"name": "x", "list": ["a", "b, c", 3], "rows": [{"k": 1, "v": "#1"}, "12.5"]}


def test_a_rate_card_cites_published_terms_by_hash():
    known = controls.published_terms()
    wrong = but(CARD, outcomes=[{**CARD["outcomes"][0], "terms_hash": "0" * 64}])
    assert controls.card_problems(wrong, known) == ["Outcome `bug-fix`: `terms_hash` is not the published hash of `bugfix`."]
    assert controls.card_problems(but(CARD, outcomes=[{**CARD["outcomes"][0], "terms": "nothing"}]), known) == ["Outcome `bug-fix`: terms/ has no template `nothing`."]
    assert controls.card_problems(but(CARD, valid_to="2026-09-30", currency="USD"), known) == ["`currency` must be test USDC: this is devnet.", "`valid_from` is after `valid_to`."]
    assert controls.card_problems(but(CARD, outcomes=[{**CARD["outcomes"][0], "price": 2}, CARD["outcomes"][0]]), known) == [
        "Outcome `bug-fix`: devnet pays between 5.00 and 100,000.00 for one outcome.", "Outcome `bug-fix` is listed twice."]


def test_a_standing_offer_is_held_to_its_rate_card():
    assert controls.offer_problems(but(OFFER, outcome="rewrite"), CARD) == ["Rate card `maintenance-2026q4` has no outcome `rewrite`."]
    assert controls.offer_problems(but(OFFER, cap=40), CARD) == ["The cap of 40.00 is less than one `bug-fix` at 50.00."]
    assert controls.offer_problems(but(OFFER, ends="2027-01-31"), CARD) == ["The offer runs outside the rate card, which is valid 2026-10-01 to 2026-12-31."]
    assert controls.offer_problems(but(OFFER, suppliers="anyone"), CARD) == []
    assert controls.offer_problems(but(OFFER, suppliers=[], retries=0, reopened="maybe", period="year")) == [
        "`suppliers` is anyone, or a list of forge accounts, each once.", "`period` is week, month or quarter.",
        "`retries` is how many evaluations one deliverable may take: 1 to 20.", "`reopened` is same (not billed again) or new (a new deliverable)."]


def test_an_offer_becomes_the_comment_the_relay_already_reads():
    parts = controls.offer_parts(OFFER, CARD, "octocat", controls.template_parts("bugfix"))
    line = controls.offer_comment(parts)
    assert line == "/knos offer @octocat rate 50 budget 400 checks: unit, lint paths: src/**, tests/** days 30"
    got = commands.parse(line, on_pull=False)
    assert isinstance(got, commands.Offer) and (got.vendor, got.rate, got.budget, got.days) == ("octocat", 50 * U, 400 * U, 30)


def test_an_envelope_shows_before_and_after_and_refuses_by_the_amount_over():
    assert controls.envelope_state(ENV) == {"limit": 5000 * U, "committed": 1200 * U, "spent": 850 * U, "held": 150 * U, "left": 2800 * U}
    c = controls.commitment(but(OFFER, outcome="feature", suppliers=["hubot"]))
    assert c == {"suppliers": 1, "periods": 3, "cap": 400 * U, "fee": 10 * U, "value": 1200 * U, "leaves": 1230 * U}
    fine = controls.fit(ENV, c["leaves"])
    assert fine["ok"] and fine["before"]["left"] == 2800 * U and fine["after"]["committed"] == 2430 * U and fine["after"]["left"] == 1570 * U
    assert fine["sentence"] == "Fits: 1,230.00 is committed, and 1,570.00 stays in envelope `eng-2026q4`."
    over = controls.fit(ENV, controls.commitment(but(OFFER, cap=1000))["leaves"])
    assert not over["ok"] and over["over"] == 275 * U and over["after"] == over["before"]
    assert over["sentence"] == "Refused: this is 275.00 over envelope `eng-2026q4`. 2,800.00 of 5,000.00 is left."
    assert controls.envelope_problems(but(ENV, spent=4000)) == ["The envelope is over its limit by 350.00."]
    assert controls.envelope_problems(but(ENV, left=1)) == ["`left` says 1, and the limit less committed, spent and held is 2,800.00."]
    assert controls.commitment(but(OFFER, suppliers=["a", "b"], period="week", ends="2026-10-14"))["periods"] == 2


# ---- authority, and the chain ---------------------------------------------------------------------------------------------
def say(**k) -> str:
    return approvals.check(POLICY, **{"approver": "sam-acme", "requester": "ravi-acme", "amount": 1200 * U, "on": "2026-10-03", **k})["sentence"]


def test_an_approver_with_authority_is_named_with_it():
    got = approvals.check(POLICY, approver="mei-acme", requester="ravi-acme", amount=1200 * U, on="2026-10-03")
    assert got == {"ok": True, "role": "approver", "authority": "approver from 2026-01-01 to 2026-12-31, up to 25,000.00",
                   "sentence": "Fine: @mei-acme is approver from 2026-01-01 to 2026-12-31, up to 25,000.00."}
    assert say(approver="Sam-Acme").startswith("Fine:")         # a forge login is one account whatever its capitals


def test_an_approval_by_someone_not_in_the_role_is_refused():
    assert say(approver="octocat") == "Refused: @octocat does not hold the approver role in this policy."
    assert say(approver="dana-acme") == "Refused: @dana-acme does not hold the approver role in this policy."      # finance is not an approver
    assert say(approver="noor-acme", role="auditor") == "Refused: the auditor role approves nothing; an approver or finance does."


def test_a_self_approval_above_the_limit_is_refused():
    assert say(approver="mei-acme", requester="mei-acme") == "Refused: @mei-acme asked for this, and nobody approves their own request."
    some = but(POLICY, self_approval_limit=100)
    assert approvals.check(some, approver="mei-acme", requester="mei-acme", amount=1200 * U, on="2026-10-03")["sentence"] == \
        "Refused: @mei-acme asked for this, and nobody approves their own request above 100.00."
    assert approvals.check(some, approver="mei-acme", requester="mei-acme", amount=100 * U, on="2026-10-03")["ok"]


def test_an_expired_role_is_refused_and_so_is_one_not_begun():
    assert say(approver="lee-acme") == "Refused: @lee-acme's approver role ended 2026-06-30, before this approval of 2026-10-03."
    assert say(approver="lee-acme", on="2026-06-30").startswith("Fine:")
    assert say(on="2025-12-31") == "Refused: @sam-acme's approver role starts 2026-01-01, after this approval of 2025-12-31."


def test_an_amount_over_the_approvers_own_limit_is_refused():
    assert say(approver="mei-acme", amount=30_000 * U) == "Refused: 30,000.00 is over @mei-acme's own limit of 25,000.00."


def test_the_thresholds_one_two_and_finance():
    need = lambda n: approvals.tier_of(POLICY, n * U)  # noqa: E731
    assert (need(1000), need(1001), need(25_000), need(25_001)) == (
        {"approver": 1, "finance": 0, "up_to": 1000 * U}, {"approver": 2, "finance": 0, "up_to": 25_000 * U},
        {"approver": 2, "finance": 0, "up_to": 25_000 * U}, {"approver": 2, "finance": 1, "up_to": None})


def test_the_chain_says_what_waits_for_whom_and_counts_only_authority():
    one = approvals.chain(POLICY, **REQ, events=approvals.sample_events(), on="2026-10-06")
    assert not one["met"] and one["sentence"] == "Waits for 1 approver: 1,200.00 needs 2 approvers."
    assert one["waiting"] == [{"role": "approver", "count": 1, "who": ["sam-acme"]}]          # lee's role has ended; mei has signed
    assert [(c["approver"], c["authority"]) for c in one["counted"]] == [("mei-acme", "approver from 2026-01-01 to 2026-12-31, up to 25,000.00")]
    both = approvals.chain(POLICY, **REQ, events=[*approvals.sample_events(), ev("sam-acme")], on="2026-10-06")
    assert both["met"] and both["sentence"] == "Approved: 2 approvers signed, as 1,200.00 needs."
    bad = approvals.chain(POLICY, **REQ, events=[ev("mei-acme"), ev("mei-acme", "2026-10-04T10:00:00Z"), ev("lee-acme"), ev("octocat"), ev("sam-acme", subject="offer:other")], on="2026-10-06")
    assert not bad["met"] and len(bad["counted"]) == 1
    assert [r["sentence"] for r in bad["refused"]] == ["Refused: @mei-acme already approved this, and one person counts once.",
                                                      "Refused: @lee-acme's approver role ended 2026-06-30, before this approval of 2026-10-03.",
                                                      "Refused: @octocat does not hold the approver role in this policy."]
    big = dict(REQ, amount=30_000 * U)
    top = approvals.chain(POLICY, **big, events=[ev("sam-acme", amount=big["amount"])], on="2026-10-06")
    assert top["sentence"] == "Waits for 1 approver and finance: 30,000.00 needs 2 approvers and finance."
    assert top["waiting"] == [{"role": "approver", "count": 1, "who": []}, {"role": "finance", "count": 1, "who": ["dana-acme"]}]   # mei's own limit is 25,000
    changed = approvals.chain(POLICY, **REQ, events=[ev("sam-acme", amount=500 * U)], on="2026-10-06")
    assert changed["refused"][0]["sentence"] == "Refused: @sam-acme approved 500.00, and the request is now 1,200.00."
    stranger = approvals.chain(POLICY, **dict(REQ, requester="octocat"), events=[], on="2026-10-06")
    assert not stranger["met"] and stranger["refused"][0]["sentence"] == "Refused: @octocat does not hold the requester role on 2026-10-06."


def test_a_policy_that_cannot_be_met_is_not_sound():
    assert approvals.policy_problems(but(POLICY, thresholds=[{"up_to": 1000, "approvers": 1}, {"approvers": 2, "finance": 2}])) == [
        "Threshold 2 asks for 2 of `finance`, and the policy names fewer."]
    assert approvals.policy_problems(but(POLICY, thresholds=[{"up_to": 1000, "approvers": 1}, {"up_to": 500, "approvers": 1}, {"up_to": 9, "approvers": 0}])) == [
        "Threshold 2: `up_to` is an amount above the step before it.", "The last threshold has no `up_to`: it covers every amount above.",
        "Threshold 3: `approvers` is a whole number from 1 to 5."]
    assert approvals.policy_problems(but(POLICY, roles={"boss": [], "auditor": [{"account": "x", "limit": 5, "until": "soon"}]}))[:3] == [
        "`boss` is not a role: the roles are requester, approver, finance and auditor.", "Role `auditor`, @x: `until` is a date like 2026-10-01.",
        "Role `auditor`, @x: `limit` is an amount above zero, for an approver or finance only."]


# ---- the comment, read through the forge ------------------------------------------------------------------------------------
def comment(who: str, body: str = "/knos approve offer:bug-fix-octocat", at: str = "2026-10-03T10:00:00Z", **more) -> dict:
    return {"id": 2292, "html_url": "https://github.com/acme/widgets/issues/12#issuecomment-2292", "body": body, "created_at": at, "updated_at": at,
            "user": {"login": who, "id": 7002}, **more}


def test_an_event_takes_its_author_and_time_from_the_forge():
    made, said = approvals.from_comment(POLICY, comment("sam-acme", "Looks right.\n/knos approve offer:bug-fix-octocat\n"), **REQ, policy_text="p")
    assert said.startswith("Fine: @sam-acme") and made is not None
    assert (made["approver"], made["approver_id"], made["role"], made["at"], made["amount"]) == ("sam-acme", 7002, "approver", "2026-10-03T10:00:00Z", "1200")
    assert made["source"]["comment_id"] == 2292 and made["policy_sha256"] == approvals.sha256_hex("p") and made["id"].startswith("apr_")
    assert approvals.read_log(json.dumps(made) + "\nnot json\n") == [made]
    refused = lambda c, **k: approvals.from_comment(POLICY, c, **{**REQ, **k})  # noqa: E731
    assert refused(comment("octocat")) == (None, "Refused: @octocat does not hold the approver role in this policy.")
    assert refused(comment("sam-acme", "thanks")) == (None, "Refused: that comment has no `/knos approve` line.")
    assert refused(comment("sam-acme", "/knos approve offer:other")) == (None, "Refused: that comment approves `offer:other`, not `offer:bug-fix-octocat`.")
    assert refused(comment("sam-acme", updated_at="2026-10-04T00:00:00Z"))[1] == "Refused: that comment was edited after it was written. Ask for a new one."
    assert refused(comment("dana-acme"))[0]["role"] == "finance"                # an account that holds only finance signs as finance
    assert refused(comment("mei-acme", "/knos approve offer:bug-fix-octocat as finance"))[1] == "Refused: @mei-acme does not hold the finance role in this policy."


def test_the_gate_a_funding_workflow_can_ask():
    root = controls.PROCUREMENT
    files = {f"{root}/rate-cards/{CARD['name']}.yaml": controls.dump_yaml(CARD), f"{root}/envelopes/{ENV['name']}.yaml": controls.dump_yaml(ENV),
             f"{root}/offers/{OFFER['name']}.yaml": controls.dump_yaml(OFFER), f"{root}/policy.yaml": controls.dump_yaml(POLICY)}
    ask = lambda f, **k: approvals.gate(f, **{"vendor": "octocat", "rate": 50 * U, "budget": 400 * U, "on": "2026-10-06", **k})  # noqa: E731
    assert approvals.gate({}, vendor="octocat", rate=1, budget=1, on="2026-10-06") == (True, "")              # no procurement files: nothing more to hold it to
    assert ask(files) == (False, "Refused: offer `bug-fix-octocat` is not approved. Waits for 2 approvers: 1,200.00 needs 2 approvers.")
    one, _ = approvals.from_comment(POLICY, comment("mei-acme"), **REQ)
    two, _ = approvals.from_comment(POLICY, comment("sam-acme", at="2026-10-04T08:00:00Z"), **REQ)
    signed = {**files, f"{root}/approvals.jsonl": json.dumps(one) + "\n" + json.dumps(two) + "\n"}
    assert ask(signed) == (True, "Offer `bug-fix-octocat`, envelope `eng-2026q4`. Approved: 2 approvers signed, as 1,200.00 needs.")
    assert ask(signed, rate=60 * U)[1] == "Refused: no standing offer under .knos/procurement/offers/ names @octocat at this rate and cap today."
    assert ask(signed, on="2027-01-02")[0] is False and ask(signed, vendor="hubot")[0] is False
    forge = {2292: comment("mei-acme")}                                 # the forge has one of the two comments; the other was typed into the log
    assert ask(signed, fetch=forge.get) == (False, "Refused: offer `bug-fix-octocat` is not approved. Waits for 1 approver: 1,200.00 needs 2 approvers.")
    assert ask({**signed, f"{root}/policy.yaml": "roles: {}"})[1].startswith("Refused: .knos/procurement/policy.yaml: Line 1:")


def test_a_monthly_offer_is_also_lines_the_existing_policy_file_reads():
    from knos import policy
    lines = controls.policy_lines(OFFER, CARD, controls.template_parts("bugfix"))
    assert lines == "  - vendor: octocat\n    rate: 50\n    budget: 400\n    checks: [unit, lint]\n"
    got = policy.load("version: 1\nvendors: [octocat]\noffers:\n" + lines)
    assert [(o.vendor, int(o.rate), int(o.budget)) for o in got.offers] == [("octocat", 50, 400)]


# ---- the commands ------------------------------------------------------------------------------------------------------------
@pytest.fixture
def repo(tmp_path, monkeypatch, capsys):
    """The sample's files under .knos/procurement in a directory, and `knos(...)`: (exit code, what it printed)."""
    import typer

    from knos import cli
    root = tmp_path / ".knos" / "procurement"
    for sub, doc in (("rate-cards", CARD), ("envelopes", ENV), ("offers", OFFER)):
        (root / sub).mkdir(parents=True)
        (root / sub / f"{doc['name']}.yaml").write_text(controls.dump_yaml(doc), encoding="utf-8")
    (root / "policy.yaml").write_text(controls.dump_yaml(POLICY), encoding="utf-8")
    monkeypatch.setattr(cli, "_github", lambda path: {"repos/acme/widgets/issues/comments/2292": comment("sam-acme"),
                                                      "repos/acme/widgets/issues/comments/2293": comment("octocat")}[path])
    app = typer.Typer()
    controls.register(app)
    approvals.register(app)

    def knos(*args: str) -> tuple[int, str]:
        capsys.readouterr()
        try:
            got = app(args=[str(a) for a in args], standalone_mode=False)
            rc = got if isinstance(got, int) else 0
        except cli.Stop as why:
            rc = 1
            print(why.said, why.fix or "")
        except typer.Exit as e:
            rc = int(e.exit_code or 0)
        return rc, " ".join(capsys.readouterr().out.split())
    return root, knos


def test_budget_offer_shows_the_envelope_before_and_after_and_refuses_over_the_limit(repo):
    root, knos = repo
    offer = root / "offers" / "bug-fix-octocat.yaml"
    rc, said = knos("budget", "offer", offer)
    assert rc == 0 and "before limit 5,000.00: committed 1,200.00, spent 850.00, held 150.00, left 2,800.00" in said
    assert "after limit 5,000.00: committed 2,430.00, spent 850.00, held 150.00, left 1,570.00" in said
    assert "/knos offer @octocat rate 50 budget 400 checks: unit, lint paths: src/**, tests/** days 30" in said
    offer.write_text(controls.dump_yaml(but(OFFER, cap=1000)), encoding="utf-8")
    rc, said = knos("budget", "offer", offer, "--write")
    assert rc == 1 and "Refused: this is 275.00 over envelope `eng-2026q4`. 2,800.00 of 5,000.00 is left." in said and "/knos offer" not in said
    assert controls.read_yaml((root / "envelopes" / "eng-2026q4.yaml").read_text(encoding="utf-8")) == ENV      # a refusal writes nothing
    offer.write_text(controls.dump_yaml(OFFER), encoding="utf-8")
    assert knos("budget", "offer", offer, "--write")[0] == 0
    assert knos("budget", "envelope", root / "envelopes" / "eng-2026q4.yaml")[1].endswith("committed 2,430.00, spent 850.00, held 150.00, left 1,570.00")
    rc, said = knos("budget", "card", root / "rate-cards" / "maintenance-2026q4.yaml")
    assert rc == 0 and "bug-fix 50.00 test USDC per accepted pull request; terms bugfix" in said
    offer.write_text("kind: standing-offer\n", encoding="utf-8")
    rc, said = knos("budget", "offer", offer)
    assert rc == 1 and "is not a sound standing offer:" in said and "`version` must be 1." in said


def test_funding_one_task_shows_the_envelope_before_and_after_and_refuses_over_the_limit(repo):
    root, knos = repo
    env = root / "envelopes" / "eng-2026q4.yaml"
    rc, said = knos("budget", "envelope", env, "--fund", "500")
    assert rc == 0 and "one task of 500.00, fee 12.50 on top." in said
    assert "before limit 5,000.00: committed 1,200.00, spent 850.00, held 150.00, left 2,800.00" in said
    assert "after limit 5,000.00: committed 1,712.50, spent 850.00, held 150.00, left 2,287.50" in said and "Fits: 512.50 is committed" in said
    rc, said = knos("budget", "envelope", env, "--fund", "3000")
    assert rc == 1 and "Refused: this is 245.00 over envelope `eng-2026q4`. 2,800.00 of 5,000.00 is left." in said
    assert controls.read_yaml(env.read_text(encoding="utf-8")) == ENV


def test_approve_records_only_an_approval_with_authority(repo):
    root, knos = repo
    offer, log = root / "offers" / "bug-fix-octocat.yaml", root / "approvals.jsonl"
    rc, said = knos("approve", "status", "--offer", offer, "--on", "2026-10-06")
    assert rc == 1 and "Waits for 2 approvers: 1,200.00 needs 2 approvers." in said and "@mei-acme, @sam-acme" in said
    rc, said = knos("approve", "record", "--repo", "acme/widgets", "--comment", 2293, "--offer", offer)
    assert rc == 1 and "Refused: @octocat does not hold the approver role in this policy. Nothing was recorded." in said and not log.exists()
    rc, said = knos("approve", "record", "--repo", "acme/widgets", "--comment", 2292, "--offer", offer)
    assert rc == 0 and "Fine: @sam-acme is approver from 2026-01-01 to 2026-12-31." in said and "Waits for 1 approver" in said
    assert [e["approver"] for e in approvals.read_log(log.read_text(encoding="utf-8"))] == ["sam-acme"]
    assert "Already recorded" in knos("approve", "record", "--repo", "acme/widgets", "--comment", 2292, "--offer", offer)[1]
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1
    rc, said = knos("approve", "check", "--approver", "lee-acme", "--offer", offer, "--on", "2026-10-03")
    assert rc == 1 and said == "Refused: @lee-acme's approver role ended 2026-06-30, before this approval of 2026-10-03."
    rc, said = knos("approve", "check", "--approver", "dana-acme", "--as", "finance", "--subject", "dlv_x", "--requester", "ravi-acme", "--amount", "30000",
                    "--policy", root / "policy.yaml", "--on", "2026-10-03")
    assert rc == 0 and said == "Fine: @dana-acme is finance from 2026-01-01 to 2026-12-31."


# ---- the cases the site must answer alike --------------------------------------------------------------------------------------
def build_cases() -> list[dict]:
    known, parts = controls.published_terms(), controls.template_parts("bugfix")
    texts = [controls.dump_yaml(d) for d in (CARD, ENV, OFFER, POLICY)] + ['# c\nname: x  # note\nlist: [a, "b, c", 3]\nrows:\n- k: 1\n  v: "#1"\n- 12.5\nnone:\nyes: true\n',
                                                                         "a: {b: 1}", "a: 1\n\tb: 2", "a: 1\na: 2", "a:\n  b: 1\n c: 2", "", 'a: "open', "a: [1, 2", "- a\n- b: 1\n  c: [x]\n"]

    def yaml(text: str):
        try:
            return controls.read_yaml(text)
        except controls.Unread as why:
            return {"unread": str(why)}
    out = [{"fn": "readYaml", "args": [t], "out": yaml(t)} for t in texts]
    out += [{"fn": "dumpYaml", "args": [d], "out": controls.dump_yaml(d)} for d in (CARD, ENV, OFFER, POLICY, {"a": "true", "b": "1 2", "c": "x: y", "d": [], "e": None, "f": False})]
    out += [{"fn": "unitsOf", "args": [v], "out": controls.units_of(v)} for v in (50, "12.5", "0.000001", "1.0000001", -1, True, "x", None, "5,000")]
    out += [{"fn": "dayOf", "args": [v], "out": controls.day_of(v)} for v in ("2026-10-01", "1970-01-01", "2026-02-30", "2026-1-1", 20261001, None)]
    cards = [CARD, but(CARD, outcomes=[{**CARD["outcomes"][0], "terms_hash": "0" * 64}]), but(CARD, outcomes=[{**CARD["outcomes"][0], "terms": "nothing", "extra": 1}]),
             but(CARD, valid_to="2026-09-30", currency="USD", version=2, name="Q4", surprise=1), but(CARD, outcomes=[{**CARD["outcomes"][0], "price": 2, "unit": ""}, CARD["outcomes"][0], {"name": "X"}]),
             but(CARD, outcomes=[]), [], "card"]
    out += [{"fn": "cardProblems", "args": [c, known], "out": controls.card_problems(c, known)} for c in cards]
    offers = [OFFER, but(OFFER, outcome="rewrite"), but(OFFER, cap=40), but(OFFER, ends="2027-01-31"), but(OFFER, suppliers="anyone"), but(OFFER, rate_card="other"),
              but(OFFER, suppliers=["a", "A"], retries=True, reopened=None, period="year", cap="200000", requested_by="-x", envelope=None, starts="soon"), None]
    out += [{"fn": "offerProblems", "args": [o, CARD], "out": controls.offer_problems(o, CARD)} for o in offers]
    envs = [ENV, but(ENV, spent=4000), but(ENV, left=1), but(ENV, left="2800"), but(ENV, owner="", cost_centre=None, limit=0, held="x", as_of="then", period_from="2027-01-01")]
    out += [{"fn": "envelopeProblems", "args": [e], "out": controls.envelope_problems(e)} for e in envs]
    out += [{"fn": "envelopeState", "args": [ENV], "out": controls.envelope_state(ENV)}]
    sized = [OFFER, but(OFFER, suppliers="anyone", period="week"), but(OFFER, suppliers=["a", "b"], period="quarter", cap=30000), but(OFFER, cap=1000), but(OFFER, ends="2026-10-01")]
    out += [{"fn": "commitment", "args": [o], "out": controls.commitment(o)} for o in sized]
    out += [{"fn": "fit", "args": [ENV, n], "out": controls.fit(ENV, n)} for n in (1230 * U, 2800 * U, 2800 * U + 1, 3075 * U)]
    out += [{"fn": "offerComment", "args": [OFFER, CARD, "octocat", parts], "out": controls.offer_comment(controls.offer_parts(OFFER, CARD, "octocat", parts))},
            {"fn": "offerComment", "args": [but(OFFER, period="week", cap="12.5"), CARD, "hubot", {**parts, "paths": []}],
             "out": controls.offer_comment(controls.offer_parts(but(OFFER, period="week", cap="12.5"), CARD, "hubot", {**parts, "paths": []}))}]
    policies = [POLICY, but(POLICY, thresholds=[{"up_to": 1000, "approvers": 1}, {"approvers": 2, "finance": 2}]),
                but(POLICY, thresholds=[{"up_to": 1000, "approvers": 1}, {"up_to": 500, "approvers": 1, "who": 1}, {"up_to": 9, "approvers": 0}]),
                but(POLICY, roles={"boss": [], "auditor": [{"account": "x", "limit": 5, "until": "soon"}], "finance": "dana", "approver": [{"account": "a", "from": "2026-02-01", "until": "2026-01-01", "x": 1}, {}]}),
                but(POLICY, roles=None, thresholds=[], self_approval_limit="lots", kind="policy")]
    out += [{"fn": "policyProblems", "args": [p], "out": approvals.policy_problems(p)} for p in policies]
    some = but(POLICY, self_approval_limit=100)
    asks = [(POLICY, dict(approver="mei-acme")), (POLICY, dict(approver="Sam-Acme")), (POLICY, dict(approver="octocat")), (POLICY, dict(approver="dana-acme")),
            (POLICY, dict(approver="dana-acme", role="finance")), (POLICY, dict(approver="noor-acme", role="auditor")), (POLICY, dict(approver="mei-acme", requester="mei-acme")),
            (some, dict(approver="mei-acme", requester="mei-acme")), (some, dict(approver="mei-acme", requester="mei-acme", amount=100 * U)), (POLICY, dict(approver="lee-acme")),
            (POLICY, dict(approver="lee-acme", on="2026-06-30")), (POLICY, dict(on="2025-12-31")), (POLICY, dict(approver="mei-acme", amount=30_000 * U))]
    for policy, k in asks:
        a = {"approver": "sam-acme", "requester": "ravi-acme", "amount": 1200 * U, "on": "2026-10-03", "role": "approver", **k}
        out.append({"fn": "check", "args": [policy, a], "out": approvals.check(policy, **a)})
    big = 30_000 * U
    chains = [(REQ, approvals.sample_events()), (REQ, [*approvals.sample_events(), ev("sam-acme")]), (REQ, []),
              (REQ, [ev("mei-acme"), ev("mei-acme", "2026-10-04T10:00:00Z"), ev("lee-acme"), ev("octocat"), ev("sam-acme", subject="offer:other")]),
              (dict(REQ, amount=big), [ev("sam-acme", amount=big)]), (dict(REQ, amount=big), [ev("sam-acme", amount=big), ev("dana-acme", role="finance", amount=big), ev("dana-acme", amount=big)]),
              (REQ, [ev("sam-acme", amount=500 * U)]), (dict(REQ, requester="octocat"), []), (dict(REQ, amount=900 * U), [ev("sam-acme", amount=900 * U)])]
    for req, events in chains:
        a = {**req, "events": events, "on": "2026-10-06"}
        out.append({"fn": "chain", "args": [POLICY, a], "out": approvals.chain(POLICY, **a)})
    out += [{"fn": "readComment", "args": [b], "out": (lambda r: None if r is None else list(r))(approvals.read_comment(b))}
            for b in ("/knos approve offer:bug-fix-octocat", "ok\r\n/knos approve dlv_0123 as finance\r\n", "/knos approve", "please /knos approve x", "/knos approve a b")]
    return [{"name": f"{c['fn']} {n}", **c} for n, c in enumerate(out, 1)]


def dumped() -> str:
    return json.dumps({"note": "Written by tests/test_procurement.py from src/knos/controls.py and src/knos/approvals.py. Do not edit by hand.",
                       "cases": build_cases()}, indent=1, ensure_ascii=True) + "\n"


def test_the_cases_the_site_runs_are_the_pythons_answers():
    assert CASES.read_text(encoding="utf-8") == dumped(), "tests/data/procure_cases.json is stale: python tests/test_procurement.py"


if __name__ == "__main__":
    CASES.write_text(dumped(), encoding="utf-8", newline="")
    print(f"wrote {CASES}", file=sys.stderr)
