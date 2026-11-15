"""v0.3.34 fix phase: what the outside judges broke in the game, held shut.

1. Sealed-seed exfiltration (JUDGE-CLINICAL cheat 1): a candidate read the sealed file through a path built with
   chr() and regenerated the hidden labels. Now refused statically (AR-FILE), and masked at run time where the OS gives
   the candidate its own namespace.
2. Sybil pot capture (found in review): one actor joined as three players (two sharing a payee) with the same
   file and took all paid places. Now: one player per identity and per payee, identical files credit only the first
   submitter, anonymous players are never paid.
3. A CSV task works in the game (and a malformed one is refused with a clear message).
4. The time budget is CPU time with a wall-clock backstop.
"""
from __future__ import annotations

import json
import shutil

import pytest

from _game import TASK, FakeJudge, attempt

import knos.game as game
from knos.autoresearch import judge as arjudge
from knos.autoresearch import sandbox, synth
from knos.autoresearch import task as artask
from knos.game import pot
from knos.game.engine import Game, GameError, join_message, orcid_ok

SEALED = TASK / "referee" / "sealed.json"
# the judge's technique: the sealed path assembled from chr() codes, no telling string literal, str(e) not type(e).__name__
CHR_PATH = ("    p = ''.join(chr(c) for c in CODES)\n"
            "    try:\n        note = open(p).read()\n    except Exception as e:\n        note = str(e)\n")


def _chr_attempt(base: str, path: str) -> str:
    codes = [ord(ch) for ch in path]
    src = base.replace("CONFIG = {", f"CODES = {codes}\n\nCONFIG = {{", 1)
    return src.replace("def main():\n", "def main():\n" + CHR_PATH, 1)


def _game(tmp_path, **rules):
    return Game.create(tmp_path / "g", TASK, title="fix34", rules={"per_round": 5, **rules}, judge=FakeJudge(artask.load(TASK)))


# -- 1. sealed data --------------------------------------------------------------------------------------------------
def test_the_judges_chr_built_path_attempt_is_refused_before_any_code_runs(tmp_path):
    g = _game(tmp_path)
    src = _chr_attempt(g.baseline(), str(SEALED.resolve()))
    found = arjudge.static_findings({"train.py": src}, "train.py", g.baseline())
    assert {"AR-FILE"} <= {f.rule for f in found if f.severity == "refuse"}
    p = g.join("judge3")["player"]
    got = g.submit(p, {"train.py": src})
    assert got["decision"] == "refused" and got["shown"] is None and "runner_tampering" in got["cheats"]


@pytest.mark.parametrize("line", ["    f = open\n", "    s = bytes([47]).decode()\n", "    s = bytearray(b'/')\n",
                                  "    p = argparse.FileType('r')\n", "    t = json.loads('1').__class__\n", "    x = chr(47)\n",
                                  "    e = eval('1')\n", "    v = vars()\n"])
def test_every_way_to_reach_a_file_or_build_a_path_is_refused(line):
    base = (TASK / "train.py").read_text(encoding="utf-8")
    src = base.replace("def main():\n", "def main():\n" + line, 1)
    assert any(f.severity == "refuse" for f in arjudge.static_findings({"train.py": src}, "train.py", base)), line


def test_the_baseline_reads_data_only_through_knos_io():
    base = (TASK / "train.py").read_text(encoding="utf-8")
    assert "import knos_io" in base and not arjudge.static_findings({"train.py": base}, "train.py", None)


PROBE = ("import json\nimport knos_io\n"
         "def main():\n" + CHR_PATH +
         "    n = len(knos_io.rows('predict'))\n"
         "    with knos_io.output() as f:\n        json.dump({'predictions': [0] * n}, f)\n"
         "    print(json.dumps({'read_seed': 1 if 'seed' in note else 0}))\n"
         "main()\n")


@pytest.mark.skipif(not sandbox.namespace_available(), reason="no unprivileged user namespaces on this machine")
def test_the_sealed_file_is_masked_at_run_time_even_from_code_the_rules_missed(tmp_path):
    """sandbox.run directly (the static rules bypassed): with the mask the file reads as nothing; without it the same
    probe reads it (the control, so the probe is known to work)."""
    secret = tmp_path / "referee"
    secret.mkdir()
    (secret / "sealed.json").write_text('{"seed": "demo-sealed-test"}\n', encoding="utf-8")
    rows = synth.rows("t", 20)
    src = PROBE.replace("CODES", repr([ord(c) for c in str(secret / "sealed.json")]))
    control = sandbox.run(src, "train.py", {"train": rows, "val": rows}, rows, seed=1, budget_s=10)
    assert control.ok and control.reported == {"read_seed": 1}
    masked = sandbox.run(src, "train.py", {"train": rows, "val": rows}, rows, seed=1, budget_s=10, mask=[str(secret)])
    assert masked.ok and masked.reported == {"read_seed": 0} and masked.isolation == "namespace"


@pytest.mark.skipif(not sandbox.namespace_available(), reason="no unprivileged user namespaces on this machine")
def test_a_games_referee_masks_the_tasks_sealed_folder_and_the_game_folder(tmp_path):
    g = Game.create(tmp_path / "real", TASK, title="masks", rules={"rounds": 1, "per_round": 1})
    assert str(SEALED.resolve()) in g.judge.mask and str((tmp_path / "real").resolve()) in g.judge.mask


def test_without_a_jail_a_machine_that_requires_one_runs_nothing(monkeypatch):
    monkeypatch.setitem(sandbox._PROBE, "ok", False)
    monkeypatch.setenv(sandbox.REQUIRE_ENV, "1")
    rows = synth.rows("t", 5)
    r = sandbox.run("print(1)\n", "train.py", {"train": rows, "val": rows}, rows, seed=1, budget_s=5)
    assert not r.ok and "no namespace jail" in r.error


# -- 2. sybils -------------------------------------------------------------------------------------------------------
W1, W2 = "So11111111111111111111111111111111111111112", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"


def test_one_player_per_identity_and_per_payee(tmp_path):
    g = _game(tmp_path)
    g.join("p1", github_id=11, payee=W1)
    with pytest.raises(GameError, match="identity already plays"):
        g.join("p2", github_id=11)
    with pytest.raises(GameError, match="payee address already belongs"):
        g.join("p3", kind="agent", github_id=12, payee=W1)
    with pytest.raises(GameError, match="one identity per player"):
        g.join("p4", github_id=13, orcid="0000-0002-1825-0097")
    assert orcid_ok("0000-0002-1825-0097") and orcid_ok("0000-0001-5109-3700") and not orcid_ok("0000-0002-1825-0098")
    g.join("p5", orcid="0000-0002-1825-0097", payee=W2)
    with pytest.raises(GameError):
        g.join("p6", orcid="0000-0002-1825-0098")
    with pytest.raises(GameError, match="identity already plays"):
        g.join("p7", orcid="0000-0002-1825-0097")


def test_a_signed_key_is_an_identity(tmp_path):
    from solders.keypair import Keypair
    g = _game(tmp_path)
    k = Keypair()
    sig = str(k.sign_message(join_message(g.s["id"], "keyed")))
    g.join("keyed", kind="agent", pubkey=str(k.pubkey()), signature=sig)
    with pytest.raises(GameError, match="signature"):
        g.join("other", pubkey=str(k.pubkey()), signature=sig)          # signed another name
    other = str(k.sign_message(join_message(g.s["id"], "again")))
    with pytest.raises(GameError, match="identity already plays"):
        g.join("again", pubkey=str(k.pubkey()), signature=other)


def test_a_game_can_require_an_identity(tmp_path):
    g = _game(tmp_path, identity_required=True)
    with pytest.raises(GameError, match="needs an identity"):
        g.join("anon")
    g.join("named", github_id=21)


def test_the_judges_sybil_one_file_three_names_is_paid_once(tmp_path):
    """Sybil pot capture, found in review: three players, the same file; one honest player with another file."""
    g = _game(tmp_path)
    same = attempt(g.baseline(), 0.9, 0.9, "sybil")
    s1 = g.join("s1", github_id=31, payee=W1)["player"]
    s2 = g.join("s2", github_id=32, payee=W2)["player"]
    s3 = g.join("s3", kind="agent", github_id=33)["player"]
    honest = g.join("honest", github_id=34)["player"]
    for p in (s1, s2, s3):
        g.submit(p, {"train.py": same})
    g.submit(honest, {"train.py": attempt(g.baseline(), 0.8, 0.8, "own work")})
    f = g.finish()
    by = {v["name"]: v for v in f["verdicts"]}
    assert by["s1"]["passed"] and not by["s2"]["passed"] and not by["s3"]["passed"]
    assert "first submitter" in by["s2"]["reasons"][0]
    paid = {p["player"] for p in pot.split(f)["parts"]}
    assert paid == {s1, honest}


def test_an_anonymous_player_is_ranked_but_never_paid(tmp_path):
    g = _game(tmp_path)
    anon = g.join("anon")["player"]
    named = g.join("named", github_id=41)["player"]
    g.submit(anon, {"train.py": attempt(g.baseline(), 0.95, 0.95, "a")})
    g.submit(named, {"train.py": attempt(g.baseline(), 0.8, 0.8, "n")})
    f = g.finish()
    assert f["winner"] == anon
    assert [p["player"] for p in pot.split(f)["parts"]] == [named]


def test_split_pool_credits_an_identical_artifact_only_to_its_first_submitter():
    atts = [{"player": "a", "kind": "human", "verified": True, "score": 0.5, "artifact_hash": "h1"},
            {"player": "b", "kind": "agent", "verified": True, "score": 0.5, "artifact_hash": "h1"},
            {"player": "c", "kind": "agent", "verified": True, "score": 0.5, "artifact_hash": "h2"}]
    assert game.split_pool(10, atts) == {"a": 5, "c": 5}


# -- 3. a CSV task ---------------------------------------------------------------------------------------------------
def _csv_task(tmp_path, sealed_doc=None):
    root = tmp_path / "csvtask"
    shutil.copytree(TASK, root)
    (root / "public").mkdir()
    synth.write(root / "public" / "train.csv", synth.rows("csv-train", 200))
    synth.write(root / "public" / "val.csv", synth.rows("csv-val", 100))
    synth.write(root / "referee" / "hidden_dev.csv", synth.rows("csv-dev", 150))
    synth.write(root / "referee" / "hidden_final.csv", synth.rows("csv-final", 200))
    raw = json.dumps(sealed_doc or {"dev": "hidden_dev.csv", "final": "hidden_final.csv"}).encode()
    (root / "referee" / "sealed.json").write_bytes(raw)
    spec = json.loads((root / "task.json").read_text(encoding="utf-8"))
    spec["data"] = {"kind": "csv", "train": "public/train.csv", "val": "public/val.csv"}
    spec["sealed"]["sha256"] = artask.sha256_bytes(raw)
    spec["time_budget_s"] = 10
    (root / "task.json").write_text(json.dumps(spec), encoding="utf-8")
    return root


def test_a_csv_task_plays_with_the_real_referee(tmp_path):
    """SYNTHETIC rows written as CSV files: the csv backend, not the seed one."""
    root = _csv_task(tmp_path)
    g = Game.create(tmp_path / "g", root, title="csv task", rules={"rounds": 1, "per_round": 1})
    p = g.join("ada", github_id=51)["player"]
    from knos.autoresearch import proposers
    src = proposers.write_config(g.baseline(), dict(proposers.read_config(g.baseline()), features="square"))
    got = g.submit(p, {"train.py": src})
    assert got["decision"] == "scored", got
    assert g.public_data("train").splitlines()[0].startswith("x0,")


def test_a_csv_task_without_its_hidden_files_is_refused_in_words(tmp_path):
    root = _csv_task(tmp_path, sealed_doc={"seed": "x"})
    with pytest.raises(artask.TaskError, match="names the hidden files: dev, final missing"):
        artask.load(root)


# -- 4. CPU time ------------------------------------------------------------------------------------------------------
def test_the_budget_is_cpu_time(tmp_path):
    rows = synth.rows("t", 5)
    spin = "import knos_io\nwhile True:\n    pass\n"
    r = sandbox.run(spin, "train.py", {"train": rows, "val": rows}, rows, seed=1, budget_s=1)
    assert not r.ok and r.timed_out and "time budget" in r.error
    assert sandbox.backstop(20) == 60 and sandbox.backstop(1) == 16
