"""outcome.yaml: the reader, the schema, the rules a schema cannot say, the hash, and each tier's terms."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from knos.outcomes import spec as S
from knos.outcomes import synth, yamlish

ROOT = Path(__file__).resolve().parents[1]


def good() -> dict:
    return synth.example_spec()


def test_the_schema_in_the_package_is_the_published_one_byte_for_byte():
    assert (ROOT / "schemas" / "outcome.schema.json").read_bytes() == S.SCHEMA_PATH.read_bytes()
    doc = json.loads(S.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert doc["properties"]["control"]["properties"]["share"]["default"] == 0.2      # the task's default control share
    assert set(doc["required"]) == set(good())


def test_the_example_spec_holds_and_jsonschema_agrees_when_it_is_installed():
    assert S.problems(good()) == []
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(good(), S.schema())


def test_the_reader_and_the_writer_round_trip_and_pyyaml_reads_the_same_values():
    s = good()
    text = yamlish.dumps(s, {"title": "a comment"})
    assert yamlish.loads(text) == s
    assert "\n# a comment\ntitle: " in text
    yaml = pytest.importorskip("yaml")
    assert yaml.safe_load(text) == s          # dates and digits stay quoted, so a YAML 1.1 reader agrees


@pytest.mark.parametrize("text,value", [
    ("a: 1\nb: [x, 'y z', 2.5]\n", {"a": 1, "b": ["x", "y z", 2.5]}),
    ("a:\n  - k: 1\n    j: two\n  - k: 3\n", {"a": [{"k": 1, "j": "two"}, {"k": 3}]}),
    ("a: 'it''s' # c\nb: \"q\\\"\"\nc: ~\nd: true\n", {"a": "it's", "b": 'q"', "c": None, "d": True}),
    ('{"a": 1}', {"a": 1}),
])
def test_the_reader_takes_its_subset(text, value):
    assert yamlish.loads(text) == value


@pytest.mark.parametrize("text", ["a: &x 1\n", "a: {b: 1}\n", "a: 1\na: 2\n", "a: |\n  x\n", "a:\n\t- 1\n", "a: b: c\n"])
def test_the_reader_refuses_what_it_does_not_take(text):
    with pytest.raises(yamlish.YamlError):
        yamlish.loads(text)


def test_the_hash_ignores_layout_and_comments_and_follows_every_value():
    s = good()
    h = S.spec_hash(s)
    assert len(h) == 64
    assert S.spec_hash(yamlish.loads("# hi\n" + yamlish.dumps(s))) == h
    assert S.spec_hash(json.loads(json.dumps(s, indent=4))) == h
    t = copy.deepcopy(s)
    t["tiers"][0]["min_lift"] = 0.04
    assert S.spec_hash(t) != h


def _broken(path: str, value):
    s = good()
    *head, last = path.split(".")
    at = s
    for k in head:
        at = at[int(k)] if isinstance(at, list) else at[k]
    if value is KeyError:
        del at[last]
    else:
        at[last] = value
    return s


@pytest.mark.parametrize("path,value,words", [
    ("version", 2, "version"),
    ("metric.formula", "__import__('os')", "formula"),
    ("metric.formula", "open('x')", "formula"),
    ("metric.direction", "sideways", "direction"),
    ("data.source", "ftp", "data.source"),
    ("data.token_secret", "lower-case", "token_secret"),
    ("data.synthetic", False, "synthetic"),
    ("window.end", "2026-08-01T00:00:00Z", "window.end"),
    ("window.start", "1 Sept", "window.start"),
    ("control.share", 0.7, "control.share"),
    ("control.salt", "short", "control.salt"),
    ("success.confidence", 1.0, "confidence"),
    ("price.cap", 31.0, "cap"),
    ("tiers.1.min_lift", 0.04, "rise"),
    ("tiers.0.amount", 4.0, "amount"),
    ("tiers.1.name", "lift-5", "own name"),
    ("escrow.cluster", "mainnet-beta", "escrow.cluster"),
    ("escrow.funder", "not-an-address", "escrow.funder"),
    ("escrow.work_seconds", 10, "work_seconds"),
    ("parties.seller.address", KeyError, "address"),
    ("dispute_window_days", 365, "dispute_window_days"),
])
def test_each_rule_refuses_its_known_bad_spec(path, value, words):
    found = S.problems(_broken(path, value))
    assert found and any(words in p for p in found), found
    with pytest.raises(S.SpecError):
        S.validate(_broken(path, value))


def test_an_unknown_key_is_refused():
    s = good()
    s["metric"]["extra"] = 1
    assert any("does not know" in p for p in S.problems(s))


def test_an_http_source_needs_a_url_and_names_its_secret_never_holds_it():
    s = good()
    s["data"] = {**s["data"], "source": "http", "path": None, "token_secret": "SUPPORT_API_TOKEN"}
    del s["data"]["path"]
    assert any("data.url" in p for p in S.problems(s))
    s["data"]["url"] = "https://help.example/api/tickets"
    assert S.problems(s) == []


def test_each_tier_has_its_own_terms_carrying_the_spec_hash_under_the_programs_600_bytes():
    from knos.settle.v2 import pay
    s = good()
    h = S.spec_hash(s)
    seen = set()
    for k in range(len(s["tiers"])):
        raw = S.terms_bytes(s, k)
        assert len(raw) <= S.MAX_TERMS
        assert raw == pay.terms_json(S.terms(s, k))             # the vault's own canonical form
        assert json.loads(raw)["spec"] == h and json.loads(raw)["synthetic"] is True
        assert S.terms_hash(s, k) == pay.terms_hash(raw)
        seen.add(raw)
    assert len(seen) == 3
