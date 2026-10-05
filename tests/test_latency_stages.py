"""scripts/latency_stages.py on a recorded sample of the relay log (tests/web/recorded/relay_log_stages.json: the
log's exact format, constructed), and network_stats.attempts: where each payment's seconds went, and what the count
of attempts says about the ones that failed or were cut short."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "web" / "recorded" / "relay_log_stages.json"


def _load(name: str):
    sys.path.insert(0, str(ROOT / "scripts")) if str(ROOT / "scripts") not in sys.path else None
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = sys.modules[name] = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ls = _load("latency_stages")
ns = ls.ns


def sample() -> tuple[dict, callable, callable]:
    doc = json.loads(SAMPLE.read_text(encoding="utf-8"))

    def get(path: str):                 # GitHub, for the one thing asked of it: when the pull request was merged
        repo, n = path[len("repos/"):].split("/pulls/")
        return {"merged_at": doc["merged_at"][f"{repo}#{n}"]}
    return doc, get, doc["block_times"].get


def test_each_payment_is_split_into_its_stages_and_every_stage_says_its_own_n():
    doc, get, when = sample()
    r = ls.report(doc["comments"], doc["events"], get, when)
    assert r["whole"] == {"n": 9, "p50": 68, "p95": 1210, "max": 1210, "lines": 9, "not_timed": 0, "window": {"from": "2026-10-04", "to": "2026-10-04"}}
    assert set(r["stages"]) == {*ls.STAGES, *ls.ALSO} and all(s["n"] == 9 for s in r["stages"].values())
    # the stages of one payment add up to its wait, to the second
    for row in r["slowest"]:
        assert row["runner_queue"] + row["workflow"] + row["relay_wait"] + row["first_send"] + row["confirm"] == row["seconds"]
        assert row["first_send"] + row["confirm"] == row["chain"] and row["queued"] <= row["runner_queue"]
    # each slow payment is slow in one stage, and the table says which
    top = {row["seconds"]: row for row in r["slowest"]}
    assert (top[1210]["runner_queue"], top[1210]["queued"], top[1210]["relay_wait"]) == (1182, 2, 3)        # the run was asked for 20 minutes late: not a runner, not the relay
    assert (top[240]["runner_queue"], top[240]["relay_wait"]) == (213, 3)                                   # paid by a second run's token, after the first was refused
    assert (top[126]["queued"], top[126]["relay_wait"]) == (95, 3)                                          # a runner queue
    assert (top[92]["relay_wait"], top[92]["first_send"], top[92]["confirm"]) == (2, 66, 6)                 # sends the endpoint dropped
    assert top[68]["relay_wait"] == 41                                                                      # a gap between two runs of the worker
    assert r["stages"]["relay_wait"] == {"n": 9, "p50": 3, "p95": 41, "max": 41} and r["stages"]["confirm"]["max"] == 8
    assert r["stages"]["runner_queue"]["p50"] == 4 and r["stages"]["runner_queue"]["max"] == 1182
    # without block times the last two stages are left out and `chain` stands for both; without GitHub nothing is timed, and that is said
    bare = ls.report(doc["comments"], doc["events"], get)
    assert bare["stages"]["first_send"] == {"n": 0, "p50": None, "p95": None, "max": None} and bare["stages"]["chain"]["n"] == 9
    blind = ls.report(doc["comments"], doc["events"])
    assert blind["whole"]["n"] == 0 and blind["whole"]["not_timed"] == 9 and blind["attempts"] == r["attempts"]


def test_the_attempts_count_the_failed_and_the_retried_beside_the_ones_that_worked():
    doc, _get, _when = sample()
    a = ns.attempts(doc["comments"])
    assert a == {"asked": 10, "completed": 9, "completion": 0.9, "lines": 11, "failed": 2, "retried": 1, "tries": 16, "misposted": 1,
                 "after_failure": 1, "never": 1,
                 "reasons": {"no open bounty for this issue:": 1, "the terms the token names are": 1}}
    assert ns.attempts(doc["comments"], ns.ATTEMPTS["fund"])["asked"] == 1 and ns.attempts([])["completion"] is None
    # a line anyone else wrote into the note of an ok line is not a field: `tries=` is read before `note=`
    odd = [{"created_at": "2026-10-04T00:00:00Z", "body": "knos-relay proof o/r#1 " + "ab" * 8 + " ok sig=s wait=1 chain=2 note=paid tries=9 to W t=3"}]
    assert ns.attempts(odd)["retried"] == 0 and ls.parts_of(odd)["ab" * 8] == {"relay_wait": 1, "chain": 2}


def test_the_command_prints_the_table_and_the_completion_line(tmp_path):
    doc, _get, _when = sample()
    log, events = tmp_path / "log.json", tmp_path / "events.json"
    lines = [{**c, "body": c["body"].replace(" ok sig=", f" ok asked={ns._unix(doc['merged_at'].get(c['body'].split()[2], '')) or 0} sig=")} if c["body"].startswith("knos-relay proof")
             and " ok " in c["body"] else c for c in doc["comments"]]         # each line carries its own start: nothing is asked of GitHub
    log.write_text(json.dumps({"comments": lines}), encoding="utf-8")
    events.write_text(json.dumps(doc["events"]), encoding="utf-8")
    said: list[str] = []
    assert ls.main(["--log", str(log), "--events", str(events), "--offline"], said.append) == 0
    text = "\n".join(said)
    assert said[0] == "merge to paid, 9 payments (2026-10-04 to 2026-10-04): p50 68 s, p95 1210 s, max 1210 s; 0 of 9 log lines could not be timed"
    assert "runner_queue      9      4   1182   1182" in text and "relay_wait        9      3     41     41" in text and "first_send        0      -      -      -" in text
    assert "successful completion across all attempts, including interrupted ones: 9 of 10 payments (90.0%)" in text
    assert "11 log lines with a token; 2 failed; 1 took more than one try (16 tries in all); 1 completed only after a failed line; 1 never completed; 1 comments could not carry their token" in text
    assert ls.main(["--offline"], said.append) == 1 and ls.main(["--log", str(log), "--offline"], said.append) == 1 and "give --events FILE" in said[-1]
    said.clear()
    assert ls.main(["--log", str(log), "--events", str(events), "--offline", "--json"], said.append) == 0 and json.loads(said[0])["attempts"]["asked"] == 10
