"""scripts/exercise_rounds/: the four rounds 0.3.20 brings to scripts/exercise_public.py, each loaded from its file and
run on the simulator: a reserve consumed by a netted period, the GitLab round, the private path, a hosted judge.
Nothing here is evidence of the public program ids: the tokens are the test key's and the forge is a stand-in."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def ex():
    spec = importlib.util.spec_from_file_location("knos_exercise_round_files", ROOT / "scripts" / "exercise_public.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    said: list[str] = []
    mod.register_places()
    assert mod.load_rounds(say=said.append) == ["gitlab", "judge", "net-reserve", "private"] and said == []
    return mod


def test_every_place_kept_for_a_round_is_filled_and_gitlab_is_the_files_round(ex):
    assert set(ex.EXT) == {"gitlab", "judge", "net-reserve", "private"} and "gitlab" not in ex.ROUNDS
    assert all(x.simulate is not None and "a place kept for the round" not in x.doc for x in ex.EXT.values())
    assert ex.EXT["net-reserve"].caps == ("netting_reserve",) and ex.EXT["gitlab"].caps == ("verify_gitlab", "gitlab_pay")
    assert ex.EXT["judge"].needs[-1] == "neutral" and ex.EXT["private"].caps == () and ex.EXT["judge"].caps == ("host_a_judge",)
    plan = ex.exercisable()
    assert plan.get("gitlab_pay") == "gitlab" and plan.get("netting_reserve") == "net-reserve" and plan.get("host_a_judge") == "judge"


def _one(ex, name: str, neutral: str | None = None) -> tuple[dict, list[str]]:
    w, said = ex.Simulated(), []
    w.neutral = neutral
    try:
        ev = ex.new_evidence(w, ex.simulated_programs())
        codes = ex.run_registered(w, ev, said.append, None, name)
        assert codes == {name: 0}, said
        again = ex.run_registered(w, ev, said.append, None, name)                 # what ended 0 is not sent again
        assert again == {name: 0} and f"[{name}] done before: nothing is sent again" in said
    finally:
        w.close()
    return ev, said


def test_the_reserve_round_runs_from_its_file(ex):
    ev, _said = _one(ex, "net-reserve")
    st = ev["rounds"]["net-reserve"]
    assert ev["exercises"]["netting_reserve"]["status"] == "exercised" and len(st["paid"]) == 4 and st["drawn"]["drawn"] == 8_000_000
    assert [t["refused"] for t in st["transactions"] if t.get("refused")] == [83] and "refund" in st


def test_the_gitlab_round_runs_from_its_file_on_a_stand_in_forge(ex):
    ev, _said = _one(ex, "gitlab")
    assert ev["exercises"]["gitlab_pay"]["status"] == ev["exercises"]["verify_gitlab"]["status"] == "exercised" and "paid" in ev["rounds"]["gitlab"]
    assert ev["mode"] == "simulated"                                              # a stand-in forge: nothing of gitlab.com


def test_the_private_path_is_one_step_that_touches_no_program_and_waits_for_an_outside_run_at_the_public_ids(ex):
    ev, said = _one(ex, "private")
    path = ev["rounds"]["private"]["path"]
    assert path["simulated"] is True and path["verdict"] == "accepted" and len(path["record_sha256"]) == 64 and ev["exercises"] == {}
    assert "record.json" in path["files"] and "token.jwt" in path["files"] and "transactions" not in ev["rounds"]["private"]

    class Public:                                                                 # the public run: the same path, then nothing until someone outside has run it
        mode, neutral = "public", None

        def __init__(self, noted=None):
            self.noted = noted

        def now(self) -> int:
            return 1_793_000_000

        def outside(self, name: str):
            return self.noted
    ev2 = {"programs": {}, "rounds": {}, "exercises": {}}
    assert ex.run_registered(Public(), ev2, said.append, None, "private") == {"private": 3}
    assert ev2["rounds"]["private"]["result"] == "needs run: a private repository's own run" and ev2["rounds"]["private"]["path"]["record_sha256"] == path["record_sha256"]
    assert ex.run_registered(Public({"record": "ab" * 32, "by": "someone"}), ev2, said.append, None, "private") == {"private": 0}
    assert ev2["rounds"]["private"]["outside"] == {"record": "ab" * 32, "by": "someone"}


def test_a_hosted_judge_of_another_owner_is_the_second_of_two_and_the_order_pays(ex):
    ev, _said = _one(ex, "judge", neutral="host/knos-judge")
    st, done = ev["rounds"]["judge"], ev["exercises"]["host_a_judge"]
    assert done["status"] == "exercised" and done["signature"] == st["paid"]["signature"] and st["host"]["owner"] != st["one"]["owner"]
    assert st["host"]["independent_of_seller"] is True and st["host"]["level"] == "reported"      # it read GitHub's record: no suite ran, and the level says so
    w, said = ex.Simulated(), []
    try:
        ev2 = ex.new_evidence(w, ex.simulated_programs())
        assert ex.run_registered(w, ev2, said.append, None, "judge") == {"judge": 3}               # no host named: nothing is sent
        assert ev2["rounds"]["judge"]["result"].startswith("skipped: no `--neutral OWNER/REPO` was given") and "transactions" not in ev2["rounds"]["judge"]
    finally:
        w.close()
