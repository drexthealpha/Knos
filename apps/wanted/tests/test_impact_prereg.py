"""The impact test's offline rules on synthetic numbers: sampling, the rankings, the bootstrap seed and both refusals."""
import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
_spec = importlib.util.spec_from_file_location("k6_impact_prereg", ROOT / "scripts" / "test_impact_prereg.py")
k6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(k6)


def test_sampling_deterministic_and_disjoint():
    full = [f"44{i:04d}" for i in range(200)]
    m1, r1 = k6.draw(full)
    m2, r2 = k6.draw(list(reversed(full)))
    assert (m1, r1) == (m2, r2)
    assert len(m1) == len(r1) == 75 and not set(m1) & set(r1)
    assert m1 == random.Random(4).sample(sorted(full), 75)
    short = full[:134]
    m, r = k6.draw(short)
    assert len(m) == len(r) == 67 and not set(m) & set(r) and set(m) | set(r) == set(short)


def test_eligible_drops_d1_and_other_sectors():
    codes = ["722511", "722514", "541940", "445310", "4453//", "311811", "812990"]
    assert k6.eligible(codes) == ["445310", "722514", "812990"]


TOP = [f"{i:05d}" for i in range(1, 16)]
POP = {m: 1_000_000 * (16 - i) for i, m in enumerate(TOP, 1)}     # 00001 largest


def test_lift_rank_on_known_numbers():
    means = {"00001": (0.9, 4), "00010": (0.6, 3), "00015": (0.5, 1)}
    lv = k6.lifts(TOP, POP, means)
    total = sum(POP.values())
    assert lv[0] == pytest.approx(0.9 / (POP["00001"] / total)) and lv[1] == 0.0
    # lift = affinity x total / pop: 00015 (pop 1M) 0.5/1, 00010 (6M) 0.6/6, 00001 (15M) 0.9/15; then by population
    assert k6.rank_lift15(TOP, POP, means) == ["00015", "00010", "00001", "00002", "00003"]
    assert k6.rank_lift15(TOP, POP, {}) == k6.rank_pop(TOP) == TOP[:5]


def test_placebo_shuffles_lifts_with_seed():
    means = {"00001": (0.9, 4), "00010": (0.6, 3), "00015": (0.5, 1)}
    a = k6.rank_placebo(TOP, POP, means, random.Random(4))
    b = k6.rank_placebo(TOP, POP, means, random.Random(4))
    assert a == b
    lv = k6.lifts(TOP, POP, means)
    random.Random(4).shuffle(lv)
    pos = sorted((i for i in range(15) if lv[i] > 0), key=lambda i: -lv[i])
    assert a[:len(pos)] == [TOP[i] for i in pos]
    assert k6.rank_placebo(TOP, POP, {}, random.Random(4)) == TOP[:5]


def test_pure_lift_keeps_metros_order_among_candidates():
    rows = [{"cbsa": "99999"}, {"cbsa": "00003"}, {"cbsa": "00007"}]
    assert k6.rank_pure([], {"00003", "00007"}, stats=lambda cells: rows) == ["00003", "00007"]


def test_metro_means_assigns_cells():
    cells = [{"lat": 1, "lon": 1, "affinity": 0.8}, {"lat": 1, "lon": 1, "affinity": 0.6}, {"lat": 9, "lon": 9, "affinity": 0.7},
             {"lat": 1, "lon": 1, "affinity": None}]
    where = lambda lat, lon: {"cbsa": "00001"} if lat == 1 else None  # noqa: E731
    assert k6.metro_means(cells, where) == {"00001": (pytest.approx(0.7), 2)}


def test_bootstrap_seed_and_score():
    pairs = {"c-a": [(0.6, 0.2), (0.4, 0.4), (0.8, 0.2), (0.2, 0.4)], "c-b": [(0.6, 0.6)] * 4}
    one, two = k6.bootstrap(pairs), k6.bootstrap(pairs)
    assert one == two and one["c-b"] == [0.0, 0.0]
    rng = random.Random(4)
    n = 4
    diffs = sorted(sum(pairs["c-a"][i][0] - pairs["c-a"][i][1] for i in [rng.randrange(n) for _ in range(n)]) / n for _ in range(2000))
    assert one["c-a"] == [round(diffs[50], 4), round(diffs[1949], 4)]
    codes = ["1", "2"]
    top10 = {"1": list("ABCDEFGHIJ"), "2": list("ABCDEFGHIJ")}
    arms = {"a": {"1": list("VWXYZ"), "2": list("AVWXY")}, "b": {"1": list("ABVWX"), "2": list("ABVWX")},
            "c": {"1": list("ABCDE"), "2": list("ABCDE")}, "d": {"1": list("AVWXY"), "2": list("AVWXY")}, "e": {"1": [], "2": []}}
    s = k6.score_sample(codes, top10, arms)
    assert s["mean_overlap"] == {"a": 0.1, "b": 0.4, "c": 1.0, "d": 0.2, "e": 0.0}
    assert s["difference"] == {"c-a": 0.9, "c-b": 0.6, "c-d": 0.8}
    assert k6.verdict(s, s)


def _truth(tmp_path, n):
    t = {"candidates": [{"cbsa": m, "pop": POP[m]} for m in TOP], "top15": TOP,
         "codes": [{"naics": f"44{i:04d}", "sample": "main", "title": "Beer, Wine, and Liquor Stores"} for i in range(n)]}
    p = tmp_path / "truth.json"
    p.write_text(json.dumps(t), encoding="utf-8")
    return p


def test_budget_refusal_before_any_call(tmp_path):
    sent = []
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "calls.json").write_text(json.dumps({"calls": 900}), encoding="utf-8")
    with pytest.raises(k6.Refused, match="passes 1000"):
        k6.knos_arm(str(_truth(tmp_path, 51)), str(tmp_path / "out.json"), str(cache), send=lambda p, q: sent.append(p), plan_sha="x")
    assert sent == []
    with pytest.raises(k6.Refused, match="passes 1000"):
        k6.knos_arm(str(_truth(tmp_path, 501)), str(tmp_path / "out.json"), str(tmp_path / "c2"), send=lambda p, q: sent.append(p), plan_sha="x")
    assert sent == []


def test_client_counts_caches_and_stops(tmp_path):
    sent = []

    def send(path, params):
        sent.append(path)
        return 200, {"results": {"tags": [{"id": "urn:tag:x", "name": "Liquor Store"}]}}
    c = k6.Counted(str(tmp_path / "c"), send, stop_at=2)
    assert c.get("/v2/tags", {"q": 1}, k6._tags_of)[1] == [{"id": "urn:tag:x", "name": "Liquor Store"}]
    c.get("/v2/tags", {"q": 1}, k6._tags_of)
    assert c.calls == 1 and len(sent) == 1
    c.get("/v2/tags", {"q": 2}, k6._tags_of)
    with pytest.raises(k6.Stop):
        c.get("/v2/tags", {"q": 3}, k6._tags_of)
    assert len(sent) == 2 and k6.Counted(str(tmp_path / "c"), send).calls == 2
    with pytest.raises(k6.Stop, match="429"):
        k6.Counted(str(tmp_path / "d"), lambda p, q: (429, None)).get("/v2/tags", {}, k6._tags_of)
    with pytest.raises(k6.Refused):
        k6.Counted(str(ROOT / ".cache-k6"), send)


def test_knos_arm_end_to_end_synthetic(tmp_path):
    def send(path, params):
        if path == "/v2/tags":
            return 200, {"results": {"tags": [{"id": "urn:tag:wine", "name": "Wine"}, {"id": "urn:tag:jazz", "name": "Jazz"}]}}
        assert params["signal.interests.tags"] == "urn:tag:wine" and params["filter.type"] == "urn:heatmap"
        return 200, {"results": {"heatmap": [{"location": {"latitude": 40.7, "longitude": -74.0}, "query": {"affinity": 0.9}},
                                             {"location": {"latitude": 40.7, "longitude": -74.0}, "query": {"affinity": 0.7}}]}}
    out = tmp_path / "knos.json"
    assert k6.knos_arm(str(_truth(tmp_path, 2)), str(out), str(tmp_path / "cache"), send=send, plan_sha="x") == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["qloo_calls"] == 2 and doc["rows"][0]["tags_kept"] == 1 and doc["rows"][0]["cells"] == 2
    assert "results" not in out.read_text(encoding="utf-8")


def _git_stub(tracked, clean):
    def git(args, cwd):
        return 0 if (tracked if args[0] == "ls-files" else clean) else 1
    return git


def test_plan_must_be_committed(tmp_path):
    plan = tmp_path / "docs" / "plan.md"
    plan.parent.mkdir()
    plan.write_text("rules", encoding="utf-8")
    with pytest.raises(k6.Refused, match="not committed"):
        k6.require_plan(plan, tmp_path, _git_stub(False, True))
    with pytest.raises(k6.Refused, match="differs"):
        k6.require_plan(plan, tmp_path, _git_stub(True, False))
    import hashlib
    assert k6.require_plan(plan, tmp_path, _git_stub(True, True)) == hashlib.sha256(b"rules").hexdigest()
    with pytest.raises(k6.Refused, match="does not exist"):
        k6.require_plan(tmp_path / "docs" / "none.md", tmp_path, _git_stub(True, True))
