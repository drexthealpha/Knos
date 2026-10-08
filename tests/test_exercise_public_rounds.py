"""scripts/exercise_public.py: the rounds other modules bring are registered by name, each with what it needs and a
path on the simulator. A prerequisite that is not met, or one the script does not know, ends THAT round with 3; a
round that fails ends it with 1; no round stops another."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("knos_exercise_public_rounds", ROOT / "scripts" / "exercise_public.py")
ex = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ex
_spec.loader.exec_module(ex)


class W:
    """A world with nothing in it: the registry asks it four things."""
    def __init__(self, mode: str = "simulated", neutral: str | None = None, notes: dict | None = None):
        self.mode, self.neutral, self.notes = mode, neutral, notes or {}

    def outside(self, name: str):
        return self.notes.get(name)

    def now(self) -> int:
        return 1_760_000_000


@pytest.fixture()
def clean():
    kept, rounds = dict(ex.EXT), dict(ex.ROUNDS)
    ex.EXT.clear()
    yield
    ex.EXT.clear()
    ex.EXT.update(kept)
    ex.ROUNDS.clear()
    ex.ROUNDS.update(rounds)


def ev(**programs) -> dict:
    return {"programs": {n: {"is": s} for n, s in programs.items()}, "rounds": {}, "exercises": {}}


def test_each_round_ends_with_its_own_code_and_a_3_or_a_1_stops_no_other(clean):
    ran: list[str] = []

    def good(book, st):
        """Does its thing."""
        ran.append("good")
        st["seen"] = book.w.mode

    def bad(book, st):
        raise ex.Failed("the count was off by one")

    def waits(book, st):
        raise ex.Need("prove.yml", "merge the pull request")
    ex.register("unknown-need", good, needs=("a-thing-nobody-knows",), simulate=good)
    ex.register("unmet", good, needs=("knos_pay", "pay-2.2"), simulate=good)
    ex.register("no-sim", good, caps=("cap_x",))
    ex.register("fails", bad, simulate=bad, caps=("cap_y",))
    ex.register("waits", waits, simulate=waits)
    ex.register("fine", good, needs=("knos_oidc", "neutral", "note:fine"), simulate=good, caps=("cap_z",))
    said: list[str] = []
    e = ev(knos_pay="new", knos_oidc="next")
    codes = ex.run_registered(W(neutral="other/repo", notes={"fine": {"k": "v"}}), e, said.append)
    assert codes == {"unknown-need": 3, "unmet": 3, "no-sim": 3, "fails": 1, "waits": 3, "fine": 0} and ran == ["good"]
    r = e["rounds"]
    assert "`a-thing-nobody-knows` is a prerequisite this script does not know" in r["unknown-need"]["result"]
    assert r["unmet"]["result"] == "skipped: proposals 7 and 8 have not executed at the public ids (`status --want 2.2` does not exit 0)"
    assert r["no-sim"]["result"] == "skipped: it has no path on the simulator" and r["fails"]["result"] == "failed: the count was off by one"
    assert r["waits"]["result"] == "needs run: prove.yml" and r["fine"] == {"round": "fine", "seen": "simulated", "result": "ok", "exit": 0}
    assert "  fine: exit 0: ok" in said and "[fine] Does its thing." in said
    # a capability of a round that did not end 0 says why; one that ended 0 is the round's own to mark
    assert e["exercises"] == {"cap_x": {"status": r["no-sim"]["result"], "round": "no-sim"}, "cap_y": {"status": "failed: the count was off by one", "round": "fails"}}
    # the command's code: 1 when a round failed, else what the steps gave; a 3 changes nothing
    assert ex.registered_summary(codes, 0, said.append) == 1 and ex.registered_summary({"a": 3, "b": 0}, 0, said.append) == 0
    assert ex.registered_summary({"a": 3}, 3, said.append) == 3 and said[-1] == "registered rounds: a exit 3"
    # again: what ended 0 is not sent again, and the phase picks
    again = ex.run_registered(W(neutral="other/repo", notes={"fine": {"k": "v"}}), e, said.append, only="fine")
    assert again == {"fine": 0} and ran == ["good"] and "[fine] done before: nothing is sent again" in said
    ex.register("early", good, simulate=good, phase="before")
    assert set(ex.run_registered(W(), ev(), said.append, phase="before")) == {"early"}


def test_what_each_prerequisite_asks():
    e = ev(knos_pay="old", knos_meter="next")
    assert ex.prerequisite("knos_meter", W(), e) is None and "knos_pay does not run its upgraded build" in ex.prerequisite("knos_pay", W(), e)
    assert ex.prerequisite("pay-2.2", W(), {**e, "want_2_2": True}) is None and ex.prerequisite("neutral", W(neutral="a/b"), e) is None
    assert "--neutral OWNER/REPO" in ex.prerequisite("neutral", W(), e) and "note gitlab --keys DIR" in ex.prerequisite("note:gitlab", W(), e)
    assert ex.prerequisite("public", W("public"), e) is None and ex.prerequisite("public", W(), e) == "it runs at the public ids only"
    with pytest.raises(KeyError):
        ex.prerequisite("mainnet", W(), e)


def test_a_file_brings_a_round_and_a_file_that_is_no_round_is_said_and_left_out(clean, tmp_path):
    (tmp_path / "net_reserve.py").write_text(
        'ROUND = {"name": "net-reserve", "needs": ("knos_pay",), "caps": ("net_reserve",)}\n\n\n'
        'def run(book, st):\n    """A period that consumes a reserve."""\n    raise xp.Cannot("no reserve is funded at the public ids")\n\n\n'
        'def simulate(book, st):\n    st["consumed"] = 5\n', encoding="utf-8")
    (tmp_path / "gitlab.py").write_text('ROUND = {"name": "gitlab", "phase": "any"}\n\n\ndef run(book, st):\n    """GitLab, from a file."""\n', encoding="utf-8")
    (tmp_path / "broken.py").write_text("ROUND = {}\n", encoding="utf-8")
    (tmp_path / "_helper.py").write_text("raise SystemExit(9)\n", encoding="utf-8")
    ex.register_places()
    assert set(ex.EXT) == {"net-reserve", "private", "judge"} and "gitlab" in ex.ROUNDS
    said: list[str] = []
    assert ex.load_rounds(tmp_path, said.append) == ["gitlab", "net-reserve"]
    assert len(said) == 1 and said[0].startswith("[broken.py] not a round: ")
    assert "gitlab" not in ex.ROUNDS and ex.EXT["gitlab"].doc == "GitLab, from a file." and ex.EXT["net-reserve"].needs == ("knos_pay",)
    assert ex.exercisable.__doc__ and ex.EXT["net-reserve"].caps == ("net_reserve",)
    e = ev(knos_pay="new", knos_oidc="new")
    codes = ex.run_registered(W(), e, said.append, phase="after")
    assert codes == {"net-reserve": 0, "private": 3, "judge": 3, "gitlab": 3} and e["rounds"]["net-reserve"]["consumed"] == 5
    assert "no round `private` is in this tree yet" in e["rounds"]["private"]["result"] and e["rounds"]["judge"]["result"].startswith("skipped: no `--neutral")
    public = ev(knos_pay="new")
    assert ex.run_registered(W("public"), public, said.append, only="net-reserve") == {"net-reserve": 3}
    assert public["rounds"]["net-reserve"]["result"] == "cannot: no reserve is funded at the public ids"
    assert ex.load_rounds(tmp_path / "nowhere", said.append) == []


def test_the_command_lists_the_registered_rounds_and_one_alone_gives_its_own_code(tmp_path):
    said: list[str] = []
    assert ex.main(["list"], said.append) == 0
    text = "\n".join(said)
    for name in ("net-reserve", "private", "judge"):
        assert f"round {name} (phase after; needs " in text
    out = tmp_path / "ev.json"
    assert ex.main(["run", "--simulate", "--only", "judge", "--out", str(out)], said.append) == 3
    assert "  judge: exit 3: skipped: no `--neutral OWNER/REPO` was given: a repository of another owner" in said
    assert ex._json(out)["rounds"]["judge"]["exit"] == 3
