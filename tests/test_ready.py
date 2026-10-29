"""Ready to fund (knos.ready): a vague brief is refused with its missing fields, its rewrite passes, the hash is fixed."""
from knos import ready

VAGUE = {"milestones": [{"key": "speed", "name": "Make the checkout faster", "target": "better performance"}]}
CLEAR = {"milestones": [{"key": "speed", "name": "Checkout p95 latency", "target": "p95 under 300 ms on test_checkout_latency",
                         "verifier": {"kind": "machine", "check": "ci / test_checkout_latency"}, "deadline_days": 14}],
         "kill_fee_bps": 1000, "challenge_s": 72 * 3600}
LAB = {"milestones": [{"key": "assay", "name": "Glucose assay on sweat samples", "target": "12 samples within 5% of the blood reference",
                       "verifier": {"kind": "human", "what": "glucose in each sample", "how": "the published assay protocol",
                                    "who": "an independent lab", "where": "a public https page with the run log"}, "deadline_s": 3600}]}


def test_vague_brief_names_every_missing_field_and_word():
    r = ready.check(VAGUE)
    assert r["label"] == "Not ready" and r["criteria_hash"] is None
    for want in ("speed.target: a number with its unit, or a named test", "speed.verifier", "speed.deadline: 60 seconds to 90 days"):
        assert want in r["missing"]
    assert set(r["milestones"][0]["vague"]) == {"better", "faster"}
    t = r["milestones"][0]["rewrite"]
    assert "<number and unit>" in t["name"] and t["verifier"]["check"] == "<GitHub check or test name>"


def test_clear_and_lab_briefs_are_ready_and_hash_is_stable():
    for b in (CLEAR, LAB):
        r = ready.check(b)
        assert r["ready"], r["missing"]
        assert r["criteria_hash"] == ready.criteria_hash(b) and len(r["criteria_hash"]) == 64
    changed = {**CLEAR, "kill_fee_bps": 2000}
    assert ready.criteria_hash(changed) != ready.criteria_hash(CLEAR)


def test_human_verifier_needs_what_how_who_where():
    b = {"milestones": [{**LAB["milestones"][0], "verifier": {"kind": "human", "what": "glucose", "how": "", "who": "x"}}]}
    m = ready.check(b)["missing"]
    assert "assay.verifier.how" in m and "assay.verifier.who" in m and "assay.verifier.where" in m


def test_terms_are_bounded():
    assert "kill_fee_bps: 0 to 5000 (what the maker keeps if the buyer cancels)" in ready.check({**CLEAR, "kill_fee_bps": 9000})["missing"]
    assert any(x.startswith("challenge_s") for x in ready.check({**CLEAR, "challenge_s": 5})["missing"])


def test_knos_pay_client_refuses_a_not_ready_brief():
    import pytest

    from knos.ideas import commit as C
    with pytest.raises(C.IdeaError, match="Not ready"):
        C.commit({}, units=1, price=1, payee={}, funder=None, funder_token=None, mint=None, led=None, criteria=VAGUE)


def test_a_brief_that_is_not_an_object_is_refused_in_one_plain_sentence():
    import pytest
    for bad in ([], "x", None, 3):
        with pytest.raises(ValueError, match=ready.NOT_A_BRIEF):
            ready.criteria_hash(bad)
        assert ready.check(bad)["ready"] is False                   # the check answers Not ready, naming its fields
