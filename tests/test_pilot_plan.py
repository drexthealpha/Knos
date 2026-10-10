"""scripts/pilot_plan.py and docs/PILOT.md's fair test: the draw that puts each task in a group, buyer by buyer, gives
the same bytes from the same list and seed and keeps the groups even; the size of the test follows the two-proportion
formula (checked on R's own `power.prop.test` examples); and the page states the sizes the script prints, the lead
number as backtest.json holds it, and that nothing has been run. Fixed inputs, no network, no clock."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pilot_plan as pp  # noqa: E402

PAGE = ROOT / "docs" / "PILOT.md"
REVIEWED = json.loads((ROOT / "docs" / "backtest.json").read_text(encoding="utf-8"))["reviewed"]["overall"]
LEAD = REVIEWED["test_or_build_check_failed"]
TASKS = [("acme", f"task-{n}") for n in range(1, 10)] + [("globex", f"slot {n}") for n in range(1, 7)]


def as_json(tasks=TASKS) -> bytes:
    return json.dumps({"tasks": [{"buyer": b, "task": t} for b, t in tasks]}).encode("utf-8")


def by_hand(tasks, seed: int, block: int) -> list[str]:
    """The rule as the docstring words it, written again apart from the script."""
    out = {}
    for buyer in dict.fromkeys(b for b, _ in tasks):
        mine = [t for b, t in tasks if b == buyer]
        for start in range(0, len(mine), block):
            ranked = sorted(mine[start:start + block], key=lambda t: hashlib.sha256(f"{seed}\n{buyer}\n{t}".encode()).hexdigest())
            half = len(ranked) // 2
            for i, t in enumerate(ranked):
                if i < 2 * half:
                    out[(buyer, t)] = "knos" if i < half else "usual"
                else:
                    last = hashlib.sha256(f"{seed}\n{buyer}\n{t}".encode()).hexdigest()[-1]
                    out[(buyer, t)] = "knos" if int(last, 16) % 2 == 0 else "usual"
    return [out[x] for x in tasks]


# ---- the draw -----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [0, 7, 20261010, 2**200 + 3])
def test_the_draw_is_the_written_rule_and_keeps_each_block_even(seed):
    groups = pp.assign(TASKS, seed)
    assert groups == by_hand(TASKS, seed, 4)
    for buyer in ("acme", "globex"):
        mine = [g for (b, _t), g in zip(TASKS, groups) if b == buyer]
        for start in range(0, len(mine) - len(mine) % 4, 4):
            assert sorted(mine[start:start + 4]) == ["knos", "knos", "usual", "usual"]
        assert abs(mine.count("knos") - mine.count("usual")) <= 1


def test_the_same_list_and_seed_give_the_same_bytes_and_another_seed_another_draw():
    one, two = pp.assignment(as_json(), "tasks.json", 7), pp.assignment(as_json(), "tasks.json", 7)
    assert one == two and one.endswith(b"\n") and b"\r" not in one
    doc = json.loads(one)
    assert doc["kind"] == "knos.pilot-assignment/1" and doc["seed"] == 7 and doc["block"] == 4
    assert doc["tasks_sha256"] == hashlib.sha256(as_json()).hexdigest()
    assert [(t["buyer"], t["task"]) for t in doc["tasks"]] == TASKS                       # file order, every task
    assert doc["counts"] == {b: {"knos": sum(1 for t in doc["tasks"] if t["buyer"] == b and t["group"] == "knos"),
                                 "usual": sum(1 for t in doc["tasks"] if t["buyer"] == b and t["group"] == "usual")} for b in ("acme", "globex")}
    assert any(pp.assign(TASKS, s) != pp.assign(TASKS, 7) for s in range(8, 12))


def test_a_csv_and_a_json_list_draw_the_same_groups():
    csv = ("buyer,task\n" + "".join(f"{b},{t}\n" for b, t in TASKS)).encode("utf-8")
    from_csv, from_json = json.loads(pp.assignment(csv, "tasks.csv", 11)), json.loads(pp.assignment(as_json(), "tasks.json", 11))
    assert from_csv["tasks"] == from_json["tasks"] and from_csv["tasks_sha256"] != from_json["tasks_sha256"]
    bare = json.dumps([{"buyer": b, "task": t} for b, t in TASKS]).encode("utf-8")
    assert json.loads(pp.assignment(bare, "tasks.json", 11))["tasks"] == from_json["tasks"]


@pytest.mark.parametrize("raw, name, said", [
    (b"[]", "t.json", "empty"),
    (b'[{"buyer": "a", "task": "1"}, {"buyer": "a", "task": "1"}]', "t.json", "listed twice"),
    (b'[{"buyer": "a"}]', "t.json", "no buyer or no task"),
    (b"buyer,job\na,1\n", "t.csv", "buyer,task"),
    (b"{", "t.json", "not JSON"),
])
def test_a_list_the_draw_cannot_use_is_refused_in_words(raw, name, said):
    with pytest.raises(pp.Unusable, match=said):
        pp.read_tasks(raw, name)


def test_an_odd_block_or_a_negative_seed_is_refused():
    for block, seed in ((3, 1), (0, 1), (4, -1)):
        with pytest.raises(pp.Unusable):
            pp.assign(TASKS, seed, block)


# ---- the size of the test -----------------------------------------------------------------------------------------------

def test_the_size_matches_the_examples_r_prints_for_power_prop_test():
    # stats/man/power.prop.test.Rd: p1 = .50, p2 = .75, power = .90 => n = 76.7; p1 = 0.90, p2 = 1.0, power = 0.8 => n = 73.37
    assert abs(pp.per_arm_exact(0.75, 0.25, 0.05, 0.9) - 76.7) < 0.05 and pp.per_arm(0.75, 0.25, 0.05, 0.9) == 77
    assert pp.per_arm_exact(0.5, -0.25, 0.05, 0.9) == pytest.approx(pp.per_arm_exact(0.75, 0.25, 0.05, 0.9))
    assert abs(pp.per_arm_exact(0.9999999, 0.0999999, 0.05, 0.8) - 73.37) < 0.01


@pytest.mark.parametrize("baseline, effect, alpha, power", [(0.037, 0, 0.05, 0.8), (0.037, 0.037, 0.05, 0.8), (0.037, 0.05, 0.05, 0.8),
                                                            (0, -0.01, 0.05, 0.8), (0.037, 0.03, 1.0, 0.8), (0.037, 0.03, 0.05, 0)])
def test_a_size_that_cannot_be_computed_is_refused(baseline, effect, alpha, power):
    with pytest.raises(pp.Unusable):
        pp.per_arm(baseline, effect, alpha, power)


def test_the_page_states_the_sizes_the_script_computes_from_the_lead_number():
    share, (low, high) = LEAD["share"], LEAD["ci95"]
    assert (REVIEWED["prs"], LEAD["prs"]) == (241, 9)
    rows = [[c.strip() for c in line.strip("|").split("|")] for line in PAGE.read_text(encoding="utf-8").splitlines()
            if line.startswith("| ") and "%" in line.split("|")[1] and re.match(r"\| [\d.]+% \(", line)]
    got = [(r[0].split()[0], r[1].split()[0], r[2], r[3]) for r in rows]
    want = [(share, 0.005), (low, 0.005), (high, 0.005), (share, share / 2)]
    assert got == [(f"{p:.1%}", f"{p - (p - k):.1%}", f"{pp.per_arm(p, p - k):,}", f"{2 * pp.per_arm(p, p - k):,}") for p, k in want]
    assert got[0][2:] == ("311", "622") and got[1][0] == "2.0%" and got[2][0] == "6.9%"
    flat = " ".join(PAGE.read_text(encoding="utf-8").split())
    assert f"`python scripts/pilot_plan.py power --baseline {share} --effect {round(share - 0.005, 4)}`" in flat
    assert "The plan is the first line: 311 tasks in each group, 622 in all." in flat
    assert "9 had a failed test, build, lint or type-check job at the head commit: 3.7% (95% interval 2.0% to 6.9%" in flat


# ---- the page -----------------------------------------------------------------------------------------------------------

def test_the_page_writes_the_test_down_before_it_starts_and_says_nothing_has_run():
    raw = PAGE.read_text(encoding="utf-8")
    flat = " ".join(raw.split())
    fair = raw.split("## A fair test, written down before it starts")[1].split("\n## ")[0]
    blocks = re.findall(r"```mermaid\n(.*?)```\n([^\n]*)\n", raw, re.S)
    assert len(blocks) == 1 and blocks[0][0].startswith("flowchart TB") and re.fullmatch(r"\*[^*]+\*", blocks[0][1])
    assert "style " not in blocks[0][0] and "classDef" not in blocks[0][0] and "%%{" not in blocks[0][0]
    assert "Nothing in this section has been run, and no buyer has seen it." in flat and "Nothing has been run yet." in flat
    for measure in ("Hours to approve", "Disputes", "Wrongful refusals", "Reverts within 30 and 90 days", "Cheats caught", "False refusals"):
        assert f"| {measure} |" in fair, measure
    # false refusals stand beside cheats caught: neighbouring rows of one table, in the same type
    rows = [line for line in fair.splitlines() if line.startswith("| ")]
    names = [r.split("|")[1].strip() for r in rows]
    assert names.index("False refusals") == names.index("Cheats caught") + 1
    assert "Cheats caught and false refusals are reported side by side, in the same table and the same type." in flat
    for said in ("**Success** needs all three", "**Failure:**", "never as success", "Nobody stops early on a good result.",
                 "A task stays in the group it was drawn for.", "The money is real in both groups.", "Mainnet (the real Solana network",
                 "It is not a random sample.", "It counts only merged work.", "The Pilot uses it for one thing: to size the test.",
                 "Nobody has agreed to do this yet.", "the analysis code is not written."):
        assert said in flat, said
    assert not re.search(r"\b(?:an|our|the) (?:outside|independent) analyst (?:has|is|will)\b", flat, re.I)


# ---- the command line ---------------------------------------------------------------------------------------------------

def test_the_command_line_writes_the_file_and_prints_its_sha256(tmp_path):
    tasks, out = tmp_path / "tasks.json", tmp_path / "assignment.json"
    tasks.write_bytes(as_json())
    run = subprocess.run([sys.executable, str(ROOT / "scripts" / "pilot_plan.py"), "assign", "--tasks", str(tasks), "--seed", "7",
                          "--out", str(out)], capture_output=True, text=True, encoding="utf-8", check=False)
    assert run.returncode == 0, run.stderr
    assert out.read_bytes() == pp.assignment(as_json(), "tasks.json", 7)
    assert f"sha256 {hashlib.sha256(out.read_bytes()).hexdigest()}  {out}" in run.stdout
    size = subprocess.run([sys.executable, str(ROOT / "scripts" / "pilot_plan.py"), "power", "--baseline", "0.0373", "--effect", "0.0323"],
                          capture_output=True, text=True, encoding="utf-8", check=False)
    assert size.returncode == 0 and size.stdout.splitlines()[0] == "Tasks needed in each group: 311 (622 in all)."
    bad = subprocess.run([sys.executable, str(ROOT / "scripts" / "pilot_plan.py"), "power", "--baseline", "0.0373", "--effect", "0"],
                         capture_output=True, text=True, encoding="utf-8", check=False)
    assert bad.returncode == 2 and "the effect must not be 0" in bad.stderr
