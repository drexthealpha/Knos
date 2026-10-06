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


def test_the_five_states_cover_every_payment_whose_line_has_its_times_and_the_others_are_listed_apart(tmp_path):
    """0.3.15's run: 3 of 39 lines had stage fields, and the table spoke for 3 payments without saying so. Now every
    ok line carries four times; the five-state table says its n, and a payment it cannot place is named under it."""
    doc, get, when = sample()
    old = ls.report(doc["comments"], doc["events"], get, when)
    assert all(s["n"] == 0 for s in old["states"].values())                 # the recorded lines are 0.3.15's: no times on them
    assert len(old["without_times"]) == old["whole"]["n"] == 9 and {x["why"] for x in old["without_times"]} == {"its line has no stage times (written before 0.3.16)"}
    # the same log as 0.3.16 writes it: six lines with their four times, one whose relay sent nothing, two as they were
    lines = ns.relay_lines(doc["comments"])
    tokens = [s["token"] for s in ns.measure("merge_to_paid", lines, doc["events"], get)["samples"]]
    assert len(tokens) == 9
    done = {s["token"]: s for s in ns.measure("merge_to_paid", lines, doc["events"], get)["samples"]}
    parts = ls.parts_of(doc["comments"])

    def with_times(body: str) -> str:
        out = []
        for line in body.splitlines():
            m = ns._RELAY.match(line.strip())
            i = tokens.index(m.group(4)) if m and m.group(4) in tokens else -1
            if 0 <= i < 7:
                t, p = float(done[m.group(4)]["at"]), parts[m.group(4)]         # confirmed at the paying block; the relay took `chain` seconds, 2 of them to confirm
                at = (t - p["chain"] - p["relay_wait"], t - p["chain"], t - 2, t)
                said = " ".join(f"{k}={'-' if i == 6 and k in ('sent_at', 'confirmed_at') else format(v, '.1f')}" for k, v in zip(ls.TIMES, at))
                line = line.replace(" note=", f" {said} note=", 1)
            out.append(line)
        return "\n".join(out)
    now = [{**c, "body": with_times(c["body"])} for c in doc["comments"]]
    paying = done[tokens[0]]["sigs"][-1]
    now.append({"created_at": "2026-10-04T00:00:00Z", "user": {"login": "github-actions[bot]"},      # a settle comment, as `knos settle` leaves it on the pull request
                "body": f"Knos: paid.\n\n<!-- knos-status -->\n<sub>…</sub>\n<!-- knos-states since=100.0 received=104.0 accepted=105.0 submitted=106.0 confirmed=110.0 finalized=123.4 tx={paying}\n-->"})
    r = ls.report(now, doc["events"], get, when)
    assert r["whole"] == old["whole"] and r["stages"] == old["stages"]      # the old table is as it was
    assert [r["states"][k]["n"] for k in ls.STATES] == [6, 6, 6, 6, 1] and r["states"]["finalized"] == {"n": 1, "p50": 13, "p95": 13, "max": 13}
    assert r["states"]["confirmed"] == {"n": 6, "p50": 2, "p95": 2, "max": 2}
    # the states of one payment add up to its wait (finalized comes after it was paid, and is not part of the wait)
    for token in tokens[:6]:
        f = ls.states(done[token], parts[token], ls.times_of(now)[token])
        assert f["received"] + f["accepted"] + f["submitted"] + f["confirmed"] == done[token]["seconds"], (token, f)
        assert f["submitted"] == parts[token]["relay_wait"] + parts[token]["chain"] - 2 and f["accepted"] == parts[token]["workflow"]
    # nothing is dropped: the three the table cannot place are named, each with why
    assert [(x["token"], x["why"]) for x in r["without_times"]] == [
        (tokens[6], "its relay sent nothing itself: another relayer carried it first"),
        (tokens[7], "its line has no stage times (written before 0.3.16)"), (tokens[8], "its line has no stage times (written before 0.3.16)")]
    assert len(r["without_times"]) + r["states"]["submitted"]["n"] == r["whole"]["n"]
    text = "\n".join(ls.render(r))
    assert "the five states, 6 of 9 payments (the ones whose log line carries queued_at, seen_at, sent_at and confirmed_at):" in text
    assert "confirmed         6      2      2      2   (the cluster confirming)" in text and "finalized         1     13     13     13" in text
    assert "not in that table, 3 payments:" in text and all(f"token {t} " in text for t in tokens[6:])
    # the line the relay writes is the line this script reads
    from knos.proof import ghrelay
    assert ls.TIMES == ghrelay.TIMES
    line = ghrelay.log_line("proof", "o/r", 9, "a.b.c", {"ok": True, "sigs": ["s"], "note": "paid sent_at=1 to W"}, 12, {"wait": 3, "chain": 9},
                            {"queued_at": 100.0, "seen_at": 103.0, "sent_at": 104.25, "confirmed_at": None})
    assert ls.times_of([{"body": line}]) == {ghrelay.token_id("a.b.c"): {"queued_at": 100.0, "seen_at": 103.0, "sent_at": 104.2, "confirmed_at": None}}


def test_the_six_stages_are_one_table_and_a_stage_nobody_recorded_says_so_never_a_figure():
    doc, get, when = sample()
    r = ls.report(doc["comments"], doc["events"], get, when)
    assert [row["stage"] for row in r["six"]] == ["workflow scheduling", "evaluation", "relay pickup", "submission", "confirmation", "finality"]
    by = {row["stage"]: row for row in r["six"]}
    assert (by["workflow scheduling"]["n"], by["workflow scheduling"]["p50"], by["workflow scheduling"]["p95"]) == (9, 4, 1182)
    assert (by["relay pickup"]["n"], by["relay pickup"]["p50"], by["relay pickup"]["p95"]) == (9, 3, 41)
    assert by["finality"] == {"stage": "finality", "n": 0, "p50": None, "p95": None, "what": "the last confirmation to the cluster finalizing it"}
    table = ls.table(r["six"], r["whole"])
    assert table[0] == "| stage | from, to | n | p50 | p95 |"
    assert table[2] == "| merge to paid, the whole wait | GitHub's `merged_at` to the block that paid | 9 | 68 s | 1210 s |"
    assert table[5] == "| relay pickup | the token's comment to a relay taking it up | 9 | 3 s | 41 s |"
    assert table[-1] == "| finality | the last confirmation to the cluster finalizing it | not recorded | not recorded | not recorded |"
    # without block times submission and confirmation were not recorded either, and say so: `chain` is not split to fill them
    bare = ls.table(ls.report(doc["comments"], doc["events"], get)["six"])
    assert [ln.count("not recorded") for ln in bare[2:]] == [0, 0, 0, 3, 3, 3]
    # with nothing timed at all, every cell says so
    assert all(ln.count("not recorded") == 3 for ln in ls.table(ls.report(doc["comments"], doc["events"])["six"])[2:])
    # the page's table is this function's, on the figures docs/bench.json keeps, and its finality row is not a guess
    page = (ROOT / "docs" / "LOAD.md").read_text(encoding="utf-8")
    kept = json.loads((ROOT / "docs" / "load.json").read_text(encoding="utf-8"))["relay"]["stages"]
    bench = json.loads((ROOT / "docs" / "bench.json").read_text(encoding="utf-8"))["release"]
    assert all(line in page for line in ls.table(kept["six"], kept["whole"]))
    assert "| finality | the last confirmation to the cluster finalizing it | not recorded | not recorded | not recorded |" in page
    for row, key in zip(kept["six"], ("runner_queue", "workflow", "relay_wait", "first_send", "confirm")):
        assert (row["n"], row["p50"], row["p95"]) == tuple(bench[f"stage_{key}_{stat}"]["value"] for stat in ("payments", "median", "ninety_fifth")), row
    whole = (kept["whole"]["n"], kept["whole"]["p50"], kept["whole"]["p95"])
    assert whole == tuple(bench[f"stage_whole_{stat}"]["value"] for stat in ("payments", "median", "ninety_fifth")) == (41, 25, 58)


def test_the_command_prints_the_six_stages_alone_as_markdown(tmp_path):
    doc, _get, _when = sample()
    log, events = tmp_path / "log.json", tmp_path / "events.json"
    log.write_text(json.dumps({"comments": doc["comments"]}), encoding="utf-8")
    events.write_text(json.dumps(doc["events"]), encoding="utf-8")
    said: list[str] = []
    assert ls.main(["--log", str(log), "--events", str(events), "--offline", "--md"], said.append) == 0
    assert len(said) == 9 and said[0].startswith("| stage |") and all(ln.startswith("| ") for ln in said)
    assert said[2] == "| merge to paid, the whole wait | GitHub's `merged_at` to the block that paid | not recorded | not recorded | not recorded |"     # offline: no merge time, so nothing was timed
