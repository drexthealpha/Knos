"""L12: one press id (the idempotency key) and one payload record one pack; the same key with another payload is refused;
an unclear outcome is read back (check) before any retry and never records a payment; the pay box names the amount,
the currency, who receives it, when it moves, the undo rule and a control that closes it."""
import re

from test_tool_run import app, call, own, program  # noqa: F401  (fixtures)

from knos_wanted import tool_page, tool_run

B = {"browser": "b-pay-000000001", "test": True}


def used_up(app):  # noqa: F811
    for _ in range(tool_run.CONF["free_runs_a_day"]):
        assert own(app, browser=B["browser"])[0] == 200
    assert own(app, browser=B["browser"])[0] == 402


def test_two_posts_with_one_key_and_one_payload_record_one_pack(app):  # noqa: F811
    used_up(app)
    a = call(app, "/api/pay", {**B, "press": "press-000000001"})
    b = call(app, "/api/pay", {**B, "press": "press-000000001"})
    assert a[0] == b[0] == 200 and a[1] == b[1] and a[1]["runs_left"] == tool_run.CONF["pack_runs"]
    assert call(app, "/api/pay", {**B, "press": "press-000000001", "note": "other"})[0] == 409     # same key, other payload
    assert call(app, "/api/pay", {**B, "press": "press-000000001", "check": True})[1] == {"status": "recorded", "runs_left": a[1]["runs_left"]}


def test_a_check_before_a_retry_records_nothing(app):  # noqa: F811
    used_up(app)
    st, got, _ = call(app, "/api/pay", {**B, "press": "press-unanswered1", "check": True})
    assert st == 200 and got == {"status": "none"}
    assert own(app, browser=B["browser"])[0] == 402                                   # still no runs: nothing was recorded


def test_a_payment_asking_for_more_than_the_pack_is_refused(app):  # noqa: F811
    used_up(app)
    st, got, _ = call(app, "/api/pay", {**B, "press": "press-000000002", "amount": "$100"})
    assert st == 400 and "Nothing was charged" in got["error"]
    assert call(app, "/api/pay", {**B, "press": "press-000000003", "pack_runs": 2000})[0] == 400
    assert own(app, browser=B["browser"])[0] == 402


def test_the_pay_box_says_everything_and_an_unclear_answer_says_do_not_pay_again():
    js = tool_page.SCRIPT
    assert 'T("pay.terms"' in js and "dataset.cancel" in js and 'T("pay.unknown")' in js and "check: true" in js
    terms = tool_page.t("en", "pay.terms", price=1)
    assert "$1" in terms and "US dollars" in terms and "Knos" in terms and "as soon as you press Yes" in terms and "Undo" in terms
    assert tool_page.t("en", "pay.unknown").startswith("Do not pay again yet")
    assert re.search(r"if \(!code\) return unclear\(b, press\)", js)                # no answer: the record is read first
