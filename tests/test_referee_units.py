"""The rules referee compares a lab value with its target only in the target's own unit (sweep 22, CODE.md 2.15): a
glucose of 5.5 mmol/L never passes a "< 100 mg/dL" target, and the same unit written another way still compares."""
import json

from knos import ready, referee_rules

BRIEF = {"milestones": [{"key": "m1", "name": "glucose", "target": "glucose under 100 mg/dL in 12 samples",
                         "verifier": {"kind": "lab", "what": "LOINC 2345-7 glucose"}}]}


def _decide(value, unit):
    obs = {"resourceType": "Observation", "id": "o1", "code": {"coding": [{"system": "http://loinc.org", "code": "2345-7"}]},
           "valueQuantity": {"value": value, "unit": unit}}
    return json.loads(referee_rules.decide(json.dumps(BRIEF), "observation", json.dumps(obs), ready.criteria_hash(BRIEF)))


def test_a_value_in_another_unit_is_never_compared():
    got = _decide(5.5, "mmol/L")
    assert got["decision"] != "met" and "not compared" in json.dumps(got)


def test_the_same_unit_written_another_way_compares():
    assert _decide(95, "mg / dl")["decision"] == "met"
    assert _decide(130, "mg/dL")["decision"] != "met"
