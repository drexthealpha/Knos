"""scripts/outcome_support.py: support resolutions counted under agreed terms. The tickets are the example's made-up
ones. Shown: each rule of the definition decides the ticket it is for; a ticket whose window is open has no verdict
and is not counted; a record exported twice is one deliverable; the meter's batch says the count, and the supplier's
invoice set against it bills each accepted resolution once; a token shaped like GitHub's and signed by a TEST key is
held to exactly that count. No help desk and no GitHub signed anything here."""
from __future__ import annotations

import base64
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts")]

import outcome_support as sup  # noqa: E402
from _settle import SeedKey, github_claims, modulus, sign_jwt  # noqa: E402

from knos import ledger as L  # noqa: E402
from knos import statement  # noqa: E402

EX = sup.EXAMPLE
KEY, KID, NOW = SeedKey(2048, seed="knos outcome support test key"), "support-test-kid", 1_791_100_000


@pytest.fixture()
def tickets() -> dict:
    return json.loads((EX / "tickets.json").read_text(encoding="utf-8"))


@pytest.fixture()
def terms() -> dict:
    return json.loads((EX / "terms.json").read_text(encoding="utf-8"))


def test_each_rule_of_the_definition_decides_the_ticket_it_is_for(tickets, terms):
    verdicts, evals = sup.evaluate(tickets, terms)
    got = {v["ticket"]: (v["verdict"], v["why"]) for v in verdicts}
    assert {k: v[0] for k, v in got.items()} == {
        "T-1001": "accepted", "T-1002": "accepted", "T-1003": "rejected", "T-1004": "rejected", "T-1005": None, "T-1006": "rejected",
        "T-1007": "accepted", "T-1008": "rejected", "T-1009": "rejected", "T-1010": "accepted"}
    assert "came back inside the window" in got["T-1003"][1] and "came back inside the window" in got["T-1006"][1]
    assert "person took it over" in got["T-1004"][1] and "person took it over" in got["T-1008"][1]
    assert "never marked it solved" in got["T-1009"][1] and "not judged yet" in got["T-1005"][1]
    assert {v["ticket"]: v["basis"] for v in verdicts if v["verdict"] == "accepted"} == {"T-1001": "confirmed", "T-1002": "silent", "T-1007": "silent",
                                                                                         "T-1010": "confirmed"}
    # the record exported twice is one ticket, and a ticket with no verdict is no evaluation
    assert len(tickets["tickets"]) == 11 and len(verdicts) == 10 and len(evals) == 9 and len({e.dlv for e in evals}) == 9
    assert sup.summary(verdicts, terms) == {"tickets": 10, "accepted": 4, "rejected": 5, "not_judged_yet": 1, "value": 4 * 990_000,
                                            "policy": sup.policy_of(terms)}
    assert "MADE-UP DATA" in tickets["about"]


def test_the_terms_are_the_policy_and_changing_them_changes_the_count(tickets, terms):
    strict = {**terms, "confirmation": "required"}
    assert sup.policy_of(strict) != sup.policy_of(terms)
    assert sup.summary(sup.evaluate(tickets, strict)[0], strict)["accepted"] == 2          # silence no longer counts
    short = {**terms, "window_hours": 24}
    got = {v["ticket"]: v["verdict"] for v in sup.evaluate(tickets, short)[0]}
    assert got["T-1005"] == "accepted" and got["T-1006"] == "accepted" and got["T-1003"] == "rejected"     # 30 h and 50 h are past a day; 20 h is not
    for bad in ({**terms, "window_hours": 0}, {**terms, "confirmation": "maybe"}, {**terms, "extra": 1}, {**terms, "kind": "other"}, {**terms, "rate": -1}):
        with pytest.raises(sup.Refused):
            sup.read_terms(bad)


def test_the_window_closing_is_what_makes_a_verdict_and_a_late_reopening_takes_nothing_back(tickets, terms):
    later = {**tickets, "exported_at": tickets["exported_at"] + 72 * 3600}
    assert {v["ticket"]: v["verdict"] for v in sup.evaluate(later, terms)[0]}["T-1005"] == "accepted"
    [t7] = [t for t in tickets["tickets"] if t["id"] == "T-1007"]
    solved = next(e["at"] for e in t7["events"] if e["type"] == "solved")
    reopened = next(e["at"] for e in t7["events"] if e["type"] == "reopened")
    assert L.reopened(solved, reopened, 72 * 3600) == L.CLOSED and sup.judge(t7, terms, tickets["exported_at"])["verdict"] == "accepted"


def test_a_ticket_file_that_says_two_things_or_is_out_of_order_is_refused(tickets, terms):
    two = copy.deepcopy(tickets)
    two["tickets"][-1]["events"].append({"at": two["exported_at"], "type": "reopened"})        # T-1002 again, now different
    with pytest.raises(sup.Refused, match="twice with different contents"):
        sup.evaluate(two, terms)
    back = copy.deepcopy(tickets)
    back["tickets"][0]["events"][0]["at"] += 10 ** 6
    with pytest.raises(sup.Refused, match="in order"):
        sup.evaluate(back, terms)
    odd = copy.deepcopy(tickets)
    odd["tickets"][0]["events"][0]["type"] = "resolved_by_magic"
    with pytest.raises(sup.Refused):
        sup.evaluate(odd, terms)


def test_the_meter_counts_the_accepted_resolutions_and_the_statement_bills_each_once(tickets, terms, tmp_path):
    b = sup.the_batch(tickets, terms, "2026-10")
    assert (b.count, b.accepted, b.value) == (9, 4, 3_960_000)
    assert sup.audience(b) == f"knosm:claim:{sup.BUYER}:{sup.SELLER}:202610:0:9:4:3960000:{b.root.hex()}"
    stored = L.load(L.dump([b]))
    assert L.verify(stored) == [] and L.parse_batch_audience(sup.audience(b))[0] is True
    st, log = sup.make_statement(tickets, terms, (EX / "invoice.csv").read_text(encoding="utf-8"), "2026-10")
    assert [ln["state"] for ln in st["lines"]] == ["agreed", "agreed", "disputed", "insufficient_evidence", "agreed", "agreed", "duplicate", "disputed"]
    assert st["totals"]["agreed"] == {"lines": 4, "amount": "3.96"} and st["totals"]["billed"] == {"lines": 8, "amount": "7.92"}
    assert st["accepted_deliverables"] == 4 and statement.verify(st) == (True, "same")
    assert [ln["payment"] for ln in st["lines"]].count("payable") == 4
    # the command writes the same statement, the log it was made from, and the ledger file
    said: list[str] = []
    assert sup.main(["statement", "--out", str(tmp_path)], said.append) == 0 and sup.main(["batch", "--out", str(tmp_path)], said.append) == 0
    assert json.loads((tmp_path / "ap-statement.json").read_text(encoding="utf-8"))["sha256"] == st["sha256"]
    assert (tmp_path / "events.jsonl").read_text(encoding="utf-8") == log.text() and (tmp_path / "ledger.seller.jsonl").read_text(encoding="utf-8") == L.dump([b])
    assert any(line.startswith("audience knosm:claim:") for line in said)


def _jwks() -> dict:
    n = modulus(KEY)
    return {"keys": [{"kty": "RSA", "alg": "RS256", "use": "sig", "kid": KID, "e": "AQAB",
                      "n": base64.urlsafe_b64encode(n.to_bytes((n.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()}]}


def _token(aud: str, **over) -> str:
    c = github_claims(aud=aud, iss=sup.GITHUB, iat=NOW, nbf=NOW - 5, exp=NOW + 300, repository_owner_id="777",
                      job_workflow_ref=f"octo/widgets/{sup.WORKFLOW}@refs/heads/main")
    c.update(over)
    return sign_jwt(KEY, c, {"alg": "RS256", "kid": KID})


def test_the_receipt_holds_a_github_shaped_token_to_exactly_this_count(tickets, terms):
    b = sup.the_batch(tickets, terms, "2026-10", 0, sup.BUYER, 777)             # the seller is the repository's owner
    r = sup.receipt(_token(sup.audience(b)), _jwks(), tickets, terms, "2026-10", NOW)
    assert (r["count"], r["accepted"], r["value"], r["seller"], r["on_chain"]) == (9, 4, 3_960_000, 777, None)
    assert r["limitations"] == list(sup.LIMITATIONS) and "made-up" in r["limitations"][0] and r["root"] == b.root.hex()
    changed = copy.deepcopy(tickets)
    changed["tickets"][2]["events"] = changed["tickets"][2]["events"][:2]       # T-1003 with its reopening taken out
    with pytest.raises(sup.Refused, match="audience is not this count"):
        sup.receipt(_token(sup.audience(b)), _jwks(), changed, terms, "2026-10", NOW)
    with pytest.raises(sup.Refused, match="audience is not this count"):
        sup.receipt(_token(sup.audience(b)), _jwks(), tickets, {**terms, "window_hours": 24}, "2026-10", NOW)
    with pytest.raises(sup.Refused, match="not of a run of"):
        sup.receipt(_token(sup.audience(b), job_workflow_ref="octo/widgets/.github/workflows/other.yml@refs/heads/main"), _jwks(), tickets, terms, "2026-10", NOW)
    with pytest.raises(sup.Refused, match="not one GitHub signed"):
        sup.receipt(_token(sup.audience(b), iss="https://example.com"), _jwks(), tickets, terms, "2026-10", NOW)
    forged = _token(sup.audience(b))[:-6] + "AAAAAA"
    with pytest.raises(sup.Refused, match="not one GitHub signed"):
        sup.receipt(forged, _jwks(), tickets, terms, "2026-10", NOW)


def test_the_workflow_signs_in_a_job_that_runs_nothing_from_the_repository_and_the_page_says_what_runs():
    import yaml
    doc = yaml.safe_load((ROOT / sup.WORKFLOW).read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    assert doc["permissions"] == {} and set(jobs) == {"count", "sign", "receipt"}
    assert jobs["count"]["permissions"] == {"contents": "read"} == jobs["receipt"]["permissions"] and jobs["sign"]["permissions"] == {"id-token": "write"}
    sign = jobs["sign"]["steps"]
    assert not any("checkout" in str(s.get("uses", "")) or "pip install" in str(s.get("run", "")) for s in sign)
    assert "knosm:claim:*" in sign[0]["run"] and "scripts/outcome_support.py receipt" in jobs["receipt"]["steps"][-2]["run"]
    page = (ROOT / "docs" / "OUTCOMES.md").read_text(encoding="utf-8")
    for words in ("## Support resolutions", "https://www.intercom.com/help/en/articles/8205718-fin-ai-agent-resolutions",
                  "https://support.zendesk.com/hc/en-us/articles/5352026794010", "made-up", "| Customer operations |", "| Back-office processing |",
                  "| Agent services |", "| Data operations |", "| Software delivery |"):
        assert words in page, words
    readme = (EX / "README.md").read_text(encoding="utf-8")
    assert "made up" in readme and "4 accepted, 5 rejected, 1 not judged yet" in readme
