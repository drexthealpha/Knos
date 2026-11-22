"""A project opened from a brief with a launch block keeps it, and its criteria hash is the brief's own
(knos.ready.criteria_hash): the city and the pre-order target cannot change without the hash changing."""
from knos import ready
from knos_wanted import valley

T = {"city": "Boulder, CO", "cbsa": "14500", "affinity": 0.9986, "cells": 3, "population": 326831, "target": 10,
     "refund_rule": "If fewer than 10 pre-orders come from Boulder, CO by the first milestone deadline, every pre-order is refunded."}


def brief(t: dict) -> dict:
    return {"title": "Pre-orders for a synthetic jacket",
            "milestones": [{"key": "preorders", "name": f"Pre-orders from {t['city']}", "target": f"{t['target']} pre-order customers from {t['city']}",
                            "verifier": {"kind": "machine", "check": "test_preorders_from_city"}, "deadline_days": 30}],
            "kill_fee_bps": 0, "challenge_s": 86_400, "launch": dict(t)}


def test_the_launch_terms_are_kept_and_hashed_with_the_milestones():
    b = brief(T)
    out = valley.create_project({"sub": "u1", "label": "test"}, "custom", b["title"], brief=b)
    p = valley.project(out["id"])
    assert p["launch"]["city"] == "Boulder, CO" and p["launch"]["target"] == 10 and out["launch"] == p["launch"]
    assert valley.readiness(p)["criteria_hash"] == ready.criteria_hash(b)
    assert ready.criteria_hash(brief({**T, "target": 11})) != ready.criteria_hash(b)
