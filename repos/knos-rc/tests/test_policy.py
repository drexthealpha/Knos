"""`.knos/policy.yml`: every rule, what it refuses and says (the line), the digest, and the hand-written reader against pyyaml."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal as D

import pytest

from knos import policy

FULL = """\
# what Acme lets Knos do
version: 1
who_may_fund: [Alice, 1234567]      # a login (any case) or an id
cap_per_order: 100
monthly_budget: 1000.50
payees:
  - carol
  - dave
vendors: [acme-agents, "bolt-bots"]
checks: [test, lint]
offers:
  - vendor: acme-agents
    rate: 20
    budget: 400
    checks: [test]
  - vendor: bolt-bots
    rate: 5.5
warranty_days: 14
holdback_percent: 12.5
arbiter: Erin
private: true
"""


def test_a_full_policy_loads_with_the_line_of_every_rule():
    p = policy.load(FULL)
    assert p.who_may_fund == ("alice", "1234567") and p.cap_per_order == D(100) and p.monthly_budget == D("1000.50")
    assert p.payees == ("carol", "dave") and p.vendors == ("acme-agents", "bolt-bots") and p.checks == ("test", "lint")
    assert p.offers == (policy.Offer("acme-agents", D(20), D(400), ("test",)), policy.Offer("bolt-bots", D("5.5")))
    assert (p.warranty_days, p.holdback_bps, p.arbiter, p.private) == (14, 1250, "erin", True)
    assert [p.lines[k] for k in ("who_may_fund", "cap_per_order", "monthly_budget", "payees", "checks", "offers.1", "offers.1.rate", "arbiter")] == [3, 4, 5, 6, 10, 16, 17, 20]
    assert policy.load("").who_may_fund is None and policy.load("# nothing\n") == policy.Policy()      # no rules is a policy that adds none
    assert policy.load("---\ncap_per_order: 5\n").cap_per_order == D(5)


def test_json_is_read_as_json():
    j = policy.load('{\n "cap_per_order": 25,\n "checks": ["test"],\n "private": true\n}')
    assert (j.cap_per_order, j.checks, j.private, j.lines["cap_per_order"]) == (D(25), ("test",), True, 2)
    assert policy.digest(j) == policy.digest(policy.load("cap_per_order: 25\nchecks: [test]\nprivate: true\n"))


def test_a_labels_rule_is_refused_since_no_label_funds_an_issue():
    """Nothing in Knos funds an issue from its labels. A policy that says `bounty-50: 50` would load, be hashed into
    every order's terms, and fund nothing without a word; it is refused with its line instead, as a rule Knos does
    not keep."""
    for text in ("labels:\n  bounty-50: 50\n", "labels: [bounty-50, bounty-100]\ncap_per_order: 100\n", '{"labels": {"bounty-5": 5}}'):
        with pytest.raises(policy.Refused) as stop:
            policy.load(text)
        assert str(stop.value) == (".knos/policy.yml line 1: `labels` is not a rule: a label on an issue funds nothing. A person who may "
                                   "fund comments `/knos fund <amount>` on the issue."), text
    assert "labels" not in policy.RULES and not hasattr(policy.Policy(), "labels")


# ---- who may fund, how much, how much a month: and the line that says no -----------------------------------------------------

def test_allows_names_the_line_of_the_rule_that_refuses():
    p = policy.load(FULL)
    assert policy.allows(p, 1234567, 100, 0) == (True, "") and policy.allows(p, 9, 50, 0, login="ALICE") == (True, "")        # an id, or a login in any case
    ok, why = policy.allows(p, 42, 10, 0, login="mallory")
    assert not ok and why == ".knos/policy.yml line 3: only alice, 1234567 may fund; mallory (42) is not one of them."
    ok, why = policy.allows(p, 1234567, "100.01", 0)
    assert not ok and why == ".knos/policy.yml line 4: an order may take at most 100, and this one is 100.01."
    assert policy.allows(p, 1234567, 100, 900.5)[0]                                   # exactly the budget: it fits
    ok, why = policy.allows(p, 1234567, 100, D("900.51"))
    assert not ok and why == (".knos/policy.yml line 5: the monthly budget is 1000.5 and 900.51 is already spent this month, so 100 more would pass it (99.99 left).")
    # the first rule that says no is the one named: not a funder, even over the cap
    assert policy.allows(p, 42, 5000, 0)[1].startswith(".knos/policy.yml line 3:")
    # a rule not given adds nothing
    bare = policy.load("cap_per_order: 10\n")
    assert policy.allows(bare, 1, 10, 10**6) == (True, "") and not policy.allows(bare, 1, 11, 0)[0]
    assert policy.allows(policy.Policy(), "anyone", 10**9, 10**9) == (True, "")
    assert policy.allows(p, 1234567, 100, 0.0)[0]                                       # floats and ints are amounts too


def test_payees_vendors_and_standing_offers():
    p = policy.load(FULL)
    assert policy.payee_allowed(p, 5, "Carol") == (True, "") and policy.payee_allowed(p, 5, "x")[1] == ".knos/policy.yml line 6: only carol, dave may be paid; x is not one of them."
    assert policy.payee_allowed(policy.Policy(), 1) == (True, "")
    assert policy.offer_for(p, 7, "Acme-Agents").rate == D(20) and policy.offer_for(p, "bolt-bots").budget is None and policy.offer_for(p, "other") is None


def test_order_opts_are_the_defaults_a_funding_takes_and_a_vendors_offer_makes_it_standing():
    p = policy.load(FULL)
    assert policy.order_opts(p) == {"private": True, "arbiter": "erin", "warranty_days": 14, "holdback_bps": 1250, "checks": ["test", "lint"],
                                    "standing": False, "rate": None, "budget": None}
    offer = policy.order_opts(p, "acme-agents")
    assert (offer["standing"], offer["rate"], offer["budget"], offer["checks"]) == (True, D(20), D(400), ["test"])      # the offer's own checks
    other = policy.order_opts(p, "bolt-bots")
    assert (other["standing"], other["rate"], other["budget"], other["checks"]) == (True, D("5.5"), None, ["test", "lint"])  # else the policy's
    assert policy.order_opts(policy.Policy()) == {"private": False, "arbiter": None, "warranty_days": 0, "holdback_bps": 0, "checks": None,
                                                  "standing": False, "rate": None, "budget": None}
    assert policy.order_opts(p, "nobody")["standing"] is False


# ---- the digest --------------------------------------------------------------------------------------------------------------

def test_the_digest_is_the_sha256_of_canonical_json_and_ignores_what_does_not_change_the_meaning():
    p = policy.load(FULL)
    want = {"version": 1, "private": True, "who_may_fund": ["1234567", "alice"], "payees": ["carol", "dave"], "vendors": ["acme-agents", "bolt-bots"],
            "checks": ["lint", "test"], "cap_per_order": "100", "monthly_budget": "1000.5",
            "offers": [{"vendor": "acme-agents", "rate": "20", "budget": "400", "checks": ["test"]}, {"vendor": "bolt-bots", "rate": "5.5"}],
            "warranty_days": 14, "holdback_bps": 1250, "arbiter": "erin"}
    raw = json.dumps(want, sort_keys=True, separators=(",", ":")).encode()
    assert policy.canonical(p) == raw and policy.digest(p) == hashlib.sha256(raw).hexdigest() and len(policy.digest(p)) == 64
    shuffled = """
arbiter: ERIN
private: true
holdback_percent: 12.50
warranty_days: 14
offers:
- {vendor: bolt-bots, rate: 5.50}
- vendor: acme-agents      # same offer, other order
  checks: [test]
  budget: 400.0
  rate: 20.0
checks: [lint, test]
vendors: ["bolt-bots", acme-agents]
payees: [dave, carol]
monthly_budget: 1000.5
cap_per_order: 100.00
who_may_fund: [1234567, alice]
"""
    assert policy.digest(policy.load(shuffled)) == policy.digest(p)
    # any rule that changes the meaning changes the digest
    for old, new in (("cap_per_order: 100", "cap_per_order: 101"), ("private: true", "private: false"), ("[test, lint]", "[test]"), ("holdback_percent: 12.5", "holdback_percent: 12"),
                     ("arbiter: Erin", "arbiter: frank"), ("rate: 20", "rate: 21")):
        assert policy.digest(policy.load(FULL.replace(old, new))) != policy.digest(p), old
    assert policy.digest(policy.Policy()) == hashlib.sha256(b'{"private":false,"version":1}').hexdigest()


# ---- malformed files ---------------------------------------------------------------------------------------------------------

BAD = [
    ("cap_per_order: lots\n", "line 1: cap_per_order must be a number, not `lots`."),
    ("cap_per_order: 0\n", "line 1: cap_per_order must be more than 0, not 0."),
    ("cap_per_order: -5\n", "line 1: cap_per_order must be more than 0"),
    ("cap_per_order: true\n", "line 1: cap_per_order must be a number"),
    ("cap_per_order: 10\ncap_per_order: 20\n", "line 2: `cap_per_order` appears twice."),
    ("cap_per_order: 100\nmonthly_budget: 50\n", "line 2: the monthly budget 50 is under the cap per order 100 (line 1)"),
    ("monthly_budjet: 5\n", "line 1: `monthly_budjet` is not a rule; did you mean `monthly_budget`?"),
    ("zzz: 5\n", "line 1: `zzz` is not a rule. The rules are: version,"),
    ("version: 2\n", "line 1: version 2 is not one this Knos reads"),
    ("who_may_fund: []\n", "line 1: who_may_fund must be a list with at least one name, like [alice, bob]; an empty list would mean nobody."),
    ("who_may_fund: alice\n", "line 1: who_may_fund must be a list"),
    ("who_may_fund: [alice, bad name]\n", "line 1: `bad name` in who_may_fund is not a GitHub login or id."),
    ("who_may_fund: [alice, ALICE]\n", "line 1: who_may_fund names alice twice."),
    ("payees: [-x]\n", "line 1: `-x` in payees is not a GitHub login or id."),
    ("checks:\n  - test\n  - ''\n", "`` in checks is not a name"),
    ("cap_per_order: 5\nlabels:\n  bounty-5: 5\n", "line 2: `labels` is not a rule: a label on an issue funds nothing."),
    ("offers: []\n", "line 1: offers is a list; each item has a vendor and a rate."),
    ("offers:\n  - rate: 5\n", "line 2: an offer needs a vendor."),
    ("offers:\n  - vendor: acme\n", "line 2: an offer needs a rate."),
    ("offers:\n  - vendor: acme\n    rate: 5\n    budjet: 9\n", "line 4: an offer has no `budjet`; did you mean `budget`?"),
    ("offers:\n  - vendor: acme\n    rate: 50\n    budget: 10\n", "line 4: the budget 10 is under the rate 50"),
    ("offers:\n  - vendor: acme\n    rate: 5\n  - vendor: Acme\n    rate: 6\n", "line 4: there are two offers for acme."),
    ("vendors: [bolt]\noffers:\n  - vendor: acme\n    rate: 5\n", "line 3: the offer is for acme, but vendors (line 1) does not list them."),
    ("offers:\n  - just text\n", "line 2: an offer is `vendor: ...`"),
    ("warranty_days: 91\n", "line 1: warranty_days must be from 0 to 90, not 91."),
    ("warranty_days: 1.5\n", "line 1: warranty_days must be a whole number"),
    ("holdback_percent: 51\nwarranty_days: 5\n", "line 1: holdback_percent must be from 0 to 50, not 51."),
    ("holdback_percent: 10\n", "line 1: a holdback is released after the warranty, so it needs warranty_days (line missing)."),
    ("holdback_percent: 10\nwarranty_days: 0\n", "line 1: a holdback is released after the warranty, so it needs warranty_days (line 2)."),
    ("holdback_percent: 1.234\nwarranty_days: 5\n", "line 1: holdback_percent has at most two decimals"),
    ("arbiter: not a login\n", "line 1: `not a login` is not a GitHub login or id."),
    ("private: yes please\n", "line 1: private is true or false"),
    ("private: 1\n", "line 1: private is true or false, not `1`."),
    # the file itself
    ("cap_per_order 5\n", "line 1: expected `name: value`, found `cap_per_order 5`."),
    ("- a\n- b\n", "line 1: a policy is `name: value` lines, not a list."),
    ("cap_per_order: 5\n\tprivate: true\n", "line 2: indent with spaces, not tabs."),
    ("cap_per_order: 5\n  private: true\n", "line 2: this line is indented more than the one before it"),
    ("checks:\n    - a\n  - b\n", "line 3: this line is indented differently from the lines before it."),
    ("cap_per_order: 5\n---\nprivate: true\n", "line 2: several documents"),
    ("anchor: &a 5\n", "line 1: `&` (an anchor, alias, tag or multi-line string) is not supported"),
    ("labels: |\n  x\n", "line 1: `|` (an anchor, alias, tag or multi-line string) is not supported"),
    ("cap_per_order: 007\n", "line 1: write 7, not 007"),
    ("checks: [a, b\n", "line 1: `[` is never closed on the line"),
    ("checks:\n- - a\n", "line 2: a list inside a list on one line is not supported"),
    ("checks: [a, b] extra\n", "line 1: unexpected `extra` after the list or mapping."),
    ("checks: 'a\n", "line 1: a quote is opened and never closed."),
    ('checks: ["a\\qb"]\n', "has an escape this reader does not know"),
    ("checks: a: b\n", "line 1: `a: b` has a colon in plain text; put it in quotes."),
    ("labels: {a 5}\n", "line 1: expected `name: value` inside `{ }`."),
    ("labels: {a: 1, a: 2}\n", "line 1: `a` appears twice."),
    ('{"cap_per_order": }', "line 1: not valid JSON"),
    ("[1, 2]", "line 1: a policy is a mapping of rules, not a list."),
    (None, ".knos/policy.yml is not text."),
]


@pytest.mark.parametrize("text, why", BAD)
def test_a_malformed_policy_is_refused_with_its_line(text, why):
    with pytest.raises(policy.Refused) as err:
        policy.load(text)
    assert str(err.value).startswith(".knos/policy.yml") and why in str(err.value), str(err.value)


def test_a_refusal_never_becomes_a_permissive_policy():
    # the caller must stop funding on Refused: the only way to a Policy is a file that holds; there is no "best effort" reading
    for text, _ in BAD[:-1]:
        with pytest.raises(policy.Refused):
            policy.load(text)


# ---- the reader against pyyaml (a development dependency only) ---------------------------------------------------------------

yaml = pytest.importorskip("yaml")
DOCUMENTS = [
    FULL,
    "a: 1\nb: [x, 'y z', \"q\\n\"]\nc:\n  d: true\n  e: ~\n  f: null\n",
    "list:\n- 1\n- two\n- 3.5\n- {k: v, n: [1, 2]}\n",
    "list:\n  - a: 1\n    b: 2\n  - a: 3\n    b:\n      - x\n      - y\n",
    "k: 'it''s'  # comment with 'quotes' and # hash\nj: \"say \\\"hi\\\" # not a comment\"\n",
    "url: http://example.com/a#b\nnum: -12\nflt: 1.5e3\nbig: 12345678901234567890\ntilde: '~'\ntrue_text: 'true'\n",
    "empty:\nnext: 1\n",
    "nested:\n  a:\n    b:\n      c: [1, [2, 3], {x: y}]\n  z: 9\n",
    "key with spaces: value with spaces\n'quoted key': 1\n\"also: quoted\": 2\n",
    "x: [ ]\ny: { }\nz: [1,2 , 3]\n",
    "# only comments\n\n# and blank lines\na: 1\n\n\nb: 2\n",
    '{"a": [1, 2, {"b": null}], "c": "d"}',
]


def _normal(value):
    """pyyaml's types, as this reader has them: ints and floats compare by value."""
    if isinstance(value, dict):
        return {str(k): _normal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normal(v) for v in value]
    return value


@pytest.mark.parametrize("text", DOCUMENTS)
def test_the_reader_agrees_with_pyyaml_on_what_it_accepts(text):
    got, _lines = policy._parse(text)
    assert got == _normal(yaml.safe_load(text))
    assert [type(x) for x in json.loads(json.dumps(got)).values()] == [type(x) for x in _normal(yaml.safe_load(text)).values()]


@pytest.mark.parametrize("text", [d for d, _ in BAD[:-1] if d and "\t" not in d and "&" not in d and "|" not in d and "007" not in d])
def test_what_it_refuses_is_never_something_pyyaml_reads_as_a_different_policy(text):
    """Where both read a file, they read the same; where this reader refuses, it may be a file pyyaml would take."""
    try:
        got, _ = policy._parse(text)
    except policy.Refused:
        return
    try:
        other = yaml.safe_load(text)
    except yaml.YAMLError:
        return
    assert got == _normal(other)


def test_nothing_but_a_policy_or_a_refusal_comes_out_of_any_text():
    """2,000 files made of the reader's own tokens, in any order: a Policy, or Refused; never another exception."""
    import random
    rng = random.Random(13)
    pieces = ["cap_per_order", "who_may_fund", "labels", "offers", "vendor", "rate", ":", ": ", "- ", "-", "  ", "    ", "\t", "[", "]", "{", "}", ",", "'", '"', "#", " # c",
              "5", "-5", "1.5", "007", "true", "null", "~", "alice", "a b", "&x", "*y", "|", ">", "---", "\n", "\n", "\n", "\\", "﻿", "é", "9" * 30]
    for _ in range(2000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 40)))
        try:
            got = policy.load(text)
        except policy.Refused as why:
            assert str(why).startswith(".knos/policy.yml")
        else:
            assert isinstance(got, policy.Policy) and len(policy.digest(got)) == 64


def test_a_private_policy_names_its_attestor_and_the_repositories_it_attests_for():
    """`private: true` with `attestor: owner/name` and `targets: [owner/name, ...]`: one repository funds and pays the
    private orders of the others. Either rule without `private: true`, targets without an attestor, and a name that is
    not a repository's are refused with the line; a policy that uses neither keeps the hash it had."""
    p = policy.load("private: true\nattestor: Acme/knos-settle\ntargets:\n  - acme/app\n  - Acme/API\n")
    assert (p.private, p.attestor, p.targets) == (True, "acme/knos-settle", ("acme/app", "acme/api"))
    assert json.loads(policy.canonical(p)) == {"version": 1, "private": True, "attestor": "acme/knos-settle", "targets": ["acme/api", "acme/app"]}
    assert policy.digest(p) != policy.digest(policy.load("private: true\nattestor: acme/knos-settle\ntargets: [acme/app]\n"))
    assert policy.digest(policy.load("private: true\n")) == hashlib.sha256(b'{"private":true,"version":1}').hexdigest()
    # only the named repository attests, and only for a listed one; the reason never repeats the target's name
    assert policy.attests(p, "ACME/knos-settle") == (True, "") and policy.attests(p, "acme/knos-settle", "acme/api") == (True, "")
    assert policy.attests(p, "acme/app") == (False, ".knos/policy.yml line 2: the attestor is acme/knos-settle, and this run is in acme/app. A private order is "
                                                   "funded and paid only from the attestor repository.")
    assert policy.attests(p, "acme/knos-settle", "acme/hidden") == (False, ".knos/policy.yml line 3: targets does not list that repository, so this attestor does nothing for it.")
    for none in (None, policy.Policy(), policy.load("private: true\n")):
        ok, why = policy.attests(none, "acme/x")
        assert not ok and why.startswith(".knos/policy.yml of acme/x names no attestor: private orders need `private: true`, `attestor: acme/x`")
    for text, why in (("attestor: acme/knos-settle\n", "line 1: attestor is for private orders, so it needs `private: true` (line missing)."),
                      ("private: false\ntargets: [acme/app]\n", "line 2: targets is for private orders, so it needs `private: true` (line 1)."),
                      ("private: true\ntargets: [acme/app]\n", "line 2: targets are the repositories an attestor reads, so it needs `attestor: owner/name`"),
                      ("private: true\nattestor: acme/a\ntargets: [acme/a]\n", "line 3: acme/a is the attestor itself; targets are the other repositories it reads."),
                      ("private: true\nattestor: knos-settle\n", "line 2: `knos-settle` in attestor is not a repository; write it as owner/name."),
                      ("private: true\nattestor: acme/a\ntargets: acme/app\n", "line 3: targets must be a list of repositories, like [acme/app, acme/api]."),
                      ("private: true\nattestor: acme/a\ntargets: [acme/app, ACME/app]\n", "line 3: targets names acme/app twice."),
                      ("private: true\nattestor: [acme/a, acme/b]\n", "line 2: attestor is one repository, as owner/name.")):
        with pytest.raises(policy.Refused) as stop:
            policy.load(text)
        assert f"{policy.PATH} {why}" in str(stop.value), (text, str(stop.value))
