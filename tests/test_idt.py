"""knos.idt: the intent sketch, ambiguity, readings, one question, routing, the agent prompt and the model-side loops."""
from knos import idt, ready

VAGUE = {"milestones": [{"key": "speed", "name": "Make the checkout faster", "target": "better performance"}]}
CLEAR = {"milestones": [{"key": "p95", "name": "Checkout p95 latency", "target": "p95 under 300 ms on test_checkout_latency",
                         "verifier": {"kind": "machine", "check": "ci / test_checkout_latency"}, "deadline_days": 14}],
         "kill_fee_bps": 1000, "challenge_s": 86400}


def test_sketch_is_structured_and_ambiguity_orders_briefs():
    s = idt.sketch(CLEAR)
    assert s["goal"] == ["Checkout p95 latency"] and s["success_check"][0]["verifier"]["check"] == "ci / test_checkout_latency"
    assert idt.ambiguity(CLEAR) == 0 < idt.ambiguity(VAGUE) <= 1


def test_vague_brief_gets_readings_one_question_and_the_rewrite_route():
    r = idt.route(VAGUE)
    assert r["path"] == "rewrite" and r["difficulty"] == "hard" and r["effort"] == "high"
    assert 2 <= len(r["interpretations"]) <= 3 and {x["word"] for x in r["interpretations"]} <= {"faster", "better"}
    assert r["question"] and r["question"].count("?") == 1


def test_clear_brief_takes_the_fast_path_at_low_effort_with_no_question():
    r = idt.route(CLEAR)
    assert (r["path"], r["difficulty"], r["effort"], r["question"]) == ("fast", "easy", "low", None)


def test_agent_prompt_carries_the_locked_intent_and_the_stop_rule():
    p = idt.agent_prompt(CLEAR, "p95", "ab" * 32)
    assert "Intent locked (criteria sha256:" + "ab" * 32 in p["prompt"] and "Do not re-derive" in p["prompt"]
    assert idt.STOP_RULE in p["prompt"] and idt.CHAIN_OF_DRAFT in p["prompt"] and p["effort"] == "low"


def test_resolved_patterns_come_first():
    got = idt.interpretations("make it faster", {"faster": [("page load", "LCP under <number> s")]})
    assert got[0]["target"] == "LCP under <number> s"


def test_shortest_ready_draft_is_kept_and_inner_dialogue_stops_when_ready():
    import json
    good = "```json\n" + json.dumps(CLEAR) + "\n```"
    longer = "```json\n" + json.dumps({**CLEAR, "note": "x" * 50}) + "\n```"
    replies = iter([{"text": longer, "output_tokens": 90}, {"text": "no", "output_tokens": 10}, {"text": good, "output_tokens": 40}])
    got = idt.shortest_ready("ask", 3, run=lambda p, m, e: next(replies))
    assert got["chosen"]["output_tokens"] == 40 and sum(t["ready"] for t in got["tries"]) == 2
    rounds = iter([{"text": "```json\n{}\n```", "output_tokens": 30}, {"text": good, "output_tokens": 20}])
    d = idt.inner_dialogue("ask", run=lambda p, m, e: next(rounds), max_rounds=3)
    assert d["stopped"] == "Ready" and len(d["rounds"]) == 2


def test_overthinking_counts_what_comes_after_the_answer():
    text = "```python\nx = 1\n```\n" + "Let me double check. " * 20
    got = idt.overthinking(text, 200, lambda code: "x = 1" in code)
    assert got and got["after_answer_share"] > 0.5


def test_tiers_and_not_on_claude():
    assert [t["tier"] for t in idt.tiers({"milestones": CLEAR["milestones"] * 3})] == ["easy", "intermediate", "final"]
    assert set(idt.NOT_ON_CLAUDE) >= {"I12", "R11", "R15", "R16", "R20"} and ready.check(CLEAR)["ready"]


def test_the_packaged_benchmark_is_the_measured_one():
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert subprocess.run([sys.executable, str(root / "scripts" / "idt_page.py"), "--check"], capture_output=True).returncode == 0


def test_rewrite_says_what_it_assumed_and_how_sure_and_the_prompt_picks_a_sketch_paradigm_and_skills():
    r = ready.check(VAGUE)["milestones"][0]["rewrite"]
    assert r["assumed"]["word"] in {"faster", "better"} and r["confidence"] == "low"
    assert idt.sketch_paradigm(CLEAR) == "chunked_symbolism"
    assert idt.sketch_paradigm({"milestones": [{"name": "Glucose assay on 12 sweat samples"}]}) == "expert_lexicons"
    assert idt.sketch_paradigm({"milestones": [{"name": "Reproduce the paper's claim"}]}) == "conceptual_chaining"
    p = idt.agent_prompt(VAGUE, "speed", "ab" * 32, {"faster": [["latency", "p95 under 300 ms"]]})
    assert "Skill: 'faster' here meant: p95 under 300 ms" in p["prompt"] and p["paradigm"] in idt.SKETCH
