"""L39: a visit is put in the variant or the holdout by its daily random id alone (no stored id), and both groups'
first-result rates are counted for /status."""
import secrets

from knos_wanted import visits


def test_groups_come_from_the_daily_id_and_both_rates_are_counted(monkeypatch):
    monkeypatch.setattr(visits, "_days", {})
    monkeypatch.setattr(visits, "_seeded", [True])
    ids = [secrets.token_hex(8) for _ in range(200)]
    assert all(visits.group_of(v) == visits.group_of(v) for v in ids)                 # the same id, the same group
    assert {visits.group_of(v) for v in ids} == {"variant", "holdout"}
    for v in ids:
        assert visits.record({"v": v, "e": "view", "p": "/"})
    got_result = ids[:50]
    for v in got_result:
        assert visits.record({"v": v, "e": "result", "p": "/"})
    h = visits.summary()["holdout"]
    for g in ("variant", "holdout"):
        n = sum(1 for v in ids if visits.group_of(v) == g)
        r = sum(1 for v in got_result if visits.group_of(v) == g)
        assert h[g] == {"visits": n, "first_result": r, "rate": round(r / n, 4)}
