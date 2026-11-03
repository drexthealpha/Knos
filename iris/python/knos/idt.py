"""Intent Disambiguation Tax (IDT): the reasoning a model spends working out what an unclear brief means.

Knos removes it before money locks (knos.ready) and hands every agent the brief in the form that needs the least
interpretation. Deterministic here; the model-side forms run through Claude Code in print mode (`claude -p`), the
only model Knos uses (the operator's own subscription; no API key, no local model).

  sketch(brief)            the explicit intent prefix every agent run receives first: goal, constraints, success
                           check, scope, as JSON fields, never prose (I1, I10)
  ambiguity(brief)         a 0-1 score from the Ready rules: missing fields and vague words (I3)
  interpretations(text)    2-3 readings of a vague milestone, side by side, for the buyer to tap one (I2)
  question(brief)          at most one clarifying question, only above QUESTION_AT (I4)
  route(brief)             fast path (template fill, low effort) for clear briefs, the rewrite flow for unclear ones;
                           difficulty -> Claude effort level and a token budget (I3, I8, R4, R8, R12, R18)
  agent_prompt(...)        what an agent is handed for a locked milestone: the sketch, the criteria hash with "intent
                           locked, do not re-derive", the effort prefix and budget, Chain-of-Draft steps, answer when
                           the check passes, confidence first (I6, I9, R3, R7/R9/R19 and R10 at prompt level, R22)
  shortest_ready(...)      N short drafts of a brief, keep the shortest that passes Ready (I11, R13)
  cothink(...)             a cheap outline (Haiku) that the main model executes (R5)
  inner_dialogue(...)      a short inner-dialogue loop for hard briefs that stops itself once Ready (R1)
  tiers(brief)             milestones scored easy / intermediate / final (R14)
  overthinking(run)        output tokens spent after the first answer point (M)
Not available on Claude (they need logits, activations, the KV cache or training): I12, R11, R15, R16, R20; their
closest prompt-level forms are listed in NOT_ON_CLAUDE.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

from . import ready

QUESTION_AT = 0.5
EFFORT = {"easy": "low", "normal": "medium", "hard": "high"}
BUDGET = {"easy": 400, "normal": 1500, "hard": 4000}            # output tokens a run should not need to exceed
NOT_ON_CLAUDE = {
    "I12": "intent-aware post-training: needs training Anthropic does not expose",
    "R7": "terminator token: needs decode control; prompt form: answer as soon as the check passes",
    "R9": "self-braking tuning: needs training; prompt form: no re-verification after the answer",
    "R10": "certainty-guided suppression: needs logits; prompt form: confidence first, no reflection when high",
    "R11": "manifold steering: needs activations Anthropic does not expose",
    "R15": "DynTS / attention pruning: needs the KV cache Anthropic does not expose",
    "R16": "contrastive decoding: needs logits Anthropic does not expose",
    "R19": "invalid-thinking suppression: needs training; prompt form as R9",
    "R20": "latent chain of thought: needs model internals Anthropic does not expose",
}
CHAIN_OF_DRAFT = "Think in minimal drafts: at most five words per step, symbols and numbers over sentences."
# Sketch-of-Thought (R2): three paradigms; the router picks one per brief from its words
SKETCH = {
    "conceptual_chaining": "Reason as a chain of key concepts joined by arrows (claim -> evidence -> measure); no full sentences.",
    "chunked_symbolism": "Reason in equations and code fragments: variables, values, one transformation per line.",
    "expert_lexicons": "Reason in the field's own shorthand and abbreviations (e.g. p95, CI, BOM, MARD), terse and exact.",
}
SKETCH_WORDS = {
    "chunked_symbolism": ("function", "code", "test", "latency", "ms", "api", "endpoint", "error rate", "algorithm", "score"),
    "expert_lexicons": ("prototype", "bench", "assay", "samples", "clinical", "sensor", "hardware", "lab", "regulatory", "iso"),
}
STOP_RULE = "Answer as soon as the success check passes. No re-verification and no alternatives after the answer."
CONFIDENCE_FIRST = "First line: your confidence (high/medium/low). High confidence: answer directly, no reflection pass."


def sketch(brief: dict) -> dict:
    """The compact intent every agent receives first (I1), as structured fields (I10)."""
    ms = [ready.normal(m, i) for i, m in enumerate((brief or {}).get("milestones") or [])]
    return {"goal": [m["name"] for m in ms],
            "success_check": [{"key": m["key"], "target": m["target"], "verifier": m["verifier"]} for m in ms],
            "constraints": {"deadline_s": [m["deadline_s"] for m in ms], "kill_fee_bps": (brief or {}).get("kill_fee_bps", 0),
                            "challenge_s": (brief or {}).get("challenge_s", ready.DEFAULT_CHALLENGE_S)},
            "scope": "only what each success check measures; nothing else is paid"}


def ambiguity(brief: dict) -> float:
    """0 = every field present and measurable, 1 = nothing usable. Deterministic: the Ready rules, weighted."""
    r = ready.check(brief or {})
    rows = r["milestones"] or [{"missing": ["milestones"], "vague": []}]
    per = [min(1.0, 0.2 * len(m["missing"]) + 0.15 * len(m["vague"])) for m in rows]
    return round(sum(per) / len(per), 3)


READINGS = {   # the usual meanings of a vague word, each with the measurable target it implies (I2, I5, I7)
    "faster": [("latency", "p95 latency under <number> ms on <named test>"), ("throughput", "<number> requests/s on <named test>"),
               ("build time", "CI build under <number> min")],
    "better": [("accuracy", "accuracy at or above <number>% on <named test>"), ("fewer errors", "error rate under <number>%"),
               ("user rating", "<number> of <number> testers rate it 4 or 5")],
    "robust": [("fewer crashes", "0 crashes in <number> runs of <named test>"), ("bad input", "100% of <named test> malformed inputs rejected"),
               ("uptime", "uptime at or above <number>% over <number> days")],
    "clean": [("lint", "0 lint errors on ci / lint"), ("smaller", "under <number> lines"), ("tested", "coverage at or above <number>%")],
    "improve": [("speed", "p95 under <number> ms"), ("quality", "<number>% of <named test> pass"), ("cost", "cost under <number> USD/month")],
    "modern": [("performance", "Lighthouse performance at or above <number>"), ("accessibility", "Lighthouse accessibility at or above <number>"),
               ("dependencies", "0 deprecated dependencies on ci / audit")],
    "progress": [("delivered", "<number> of <number> deliverables accepted"), ("tests", "<number> acceptance tests pass")],
    "scalable": [("load", "<number> concurrent users with p95 under <number> ms"), ("data", "<number> rows processed in under <number> s")],
}


def interpretations(text: str, patterns: dict | None = None) -> list[dict]:
    """2-3 readings of a vague milestone, each a target the buyer can tap; resolved patterns stored by the server
    (Sibyl REFERENCE tier) come first (I7)."""
    words = ready.vague_words(text or "")
    out: list[dict] = []
    for w in words:
        for label, target in ((patterns or {}).get(w) or []) + READINGS.get(w, []):
            if len(out) < 3 and all(o["target"] != target for o in out):
                out.append({"word": w, "reading": label, "target": target})
    if not out:
        out = [{"word": "", "reading": "a measured result", "target": "<number> <unit> on <named test or measurement>"}]
    return out


def question(brief: dict) -> str | None:
    """At most one clarifying question, and only when the brief is too ambiguous to rewrite by itself (I4)."""
    if ambiguity(brief) < QUESTION_AT:
        return None
    r = ready.check(brief or {})
    m = (r["milestones"] or [{}])[0]
    if m.get("vague"):
        return f"When you say '{m['vague'][0]}', which number should change, and to what?"
    if any(f.startswith("verifier") for f in m.get("missing", [])):
        return "Who or what decides it is done: a GitHub check, or a person (what, how, who, where)?"
    return "What number, with its unit, proves this milestone is done?"


def difficulty(brief: dict) -> str:
    """easy: Ready and machine-checked; hard: unclear or human-verified with several milestones; normal otherwise (R4)."""
    a = ambiguity(brief)
    ms = (brief or {}).get("milestones") or []
    human = any(((m.get("verifier") or {}).get("kind")) == "human" for m in ms if isinstance(m, dict))
    if a >= QUESTION_AT or (human and len(ms) > 2):
        return "hard"
    if a == 0 and not human and len(ms) <= 2:
        return "easy"
    return "normal"


def route(brief: dict) -> dict:
    """Dual-process routing (I8, R12): a clear brief goes the fast path at low effort; an unclear one to the rewrite
    flow. The effort level and budget are what an agent run is given (R4, R8, R18)."""
    d = difficulty(brief)
    r = ready.check(brief or {})
    return {"path": "fast" if r["ready"] and d == "easy" else "rewrite" if not r["ready"] else "full",
            "difficulty": d, "effort": EFFORT[d], "token_budget": BUDGET[d], "ambiguity": ambiguity(brief),
            "question": question(brief), "interpretations": None if r["ready"] else interpretations(
                " ".join(json.dumps(m) for m in (brief or {}).get("milestones") or []))}


def locked_hash(brief: dict) -> str:
    return ready.criteria_hash(brief)


def agent_prompt(brief: dict, milestone_key: str, criteria_hash: str | None = None, patterns: dict | None = None,
                 grounding: dict | None = None) -> dict:
    """What an agent working on one locked milestone receives (I1, I6, I9, R3, R8, R10, R18, R22)."""
    sk = sketch(brief)
    rt = route(brief)
    m = next((x for x in sk["success_check"] if x["key"] == milestone_key), sk["success_check"][0] if sk["success_check"] else {})
    h = criteria_hash or locked_hash(brief)
    lines = [f"[effort: {rt['effort']}; budget: {rt['token_budget']} output tokens]",
             f"Intent locked (criteria sha256:{h}). Do not re-derive or re-interpret the brief.",
             "Intent: " + json.dumps({"goal": sk["goal"], "success_check": m, "constraints": sk["constraints"], "scope": sk["scope"]},
                                     separators=(",", ":"), ensure_ascii=False),
             CHAIN_OF_DRAFT, SKETCH[sketch_paradigm(brief)], CONFIDENCE_FIRST, STOP_RULE,
             "Intermediate work as JSON, equations or code sketches, never prose."]
    lines += [f"Skill: {k}" for k in skills_for(brief, patterns)]
    if grounding:                    # Qloo's facts about who buys and where, so the work is aimed, not guessed
        lines.append("Grounding (Qloo): " + json.dumps(grounding, separators=(",", ":"), ensure_ascii=False))
    return {"milestone": milestone_key, "criteria_hash": h, "effort": rt["effort"], "token_budget": rt["token_budget"],
            "difficulty": rt["difficulty"], "paradigm": sketch_paradigm(brief), "prompt": "\n".join(lines), "intent": sk}


def sketch_paradigm(brief: dict) -> str:
    """The Sketch-of-Thought router (R2): chunked symbolism for code and numbers, expert lexicons for lab and hardware
    work, conceptual chaining for the rest (research, product claims)."""
    text = json.dumps(brief or {}).lower()
    score = {k: sum(w in text for w in ws) for k, ws in SKETCH_WORDS.items()}
    best = max(score, key=lambda k: score[k])
    return best if score[best] else "conceptual_chaining"


def skills_for(brief: dict, patterns: dict | None = None) -> list[str]:
    """Reasoning skills retrieved for a task (R6, R17): the stored resolutions of the vague words this kind of brief
    used before (the server's resolved patterns, also kept in its Sibyl record), one line each."""
    words = ready.vague_words(json.dumps(brief or {}))
    out = []
    for w, rows in (patterns or {}).items():
        if w in words or not words:
            out += [f"'{w}' here meant: {target}" for _reading, target in rows[:2]]
    return out[:4]


def tiers(brief: dict) -> list[dict]:
    """Milestones scored easy / intermediate / final by their place and verifier (RDoLT-style, R14)."""
    ms = [ready.normal(m, i) for i, m in enumerate((brief or {}).get("milestones") or [])]
    out = []
    for i, m in enumerate(ms):
        tier = "final" if i == len(ms) - 1 else "easy" if i == 0 else "intermediate"
        score = 1.0 - ready.check({"milestones": [m]})["milestones"][0]["missing"].__len__() * 0.25
        out.append({"key": m["key"], "tier": tier, "score": max(0.0, round(score, 2))})
    return out


# ---- the model side: Claude Code in print mode --------------------------------------------------------------------
Runner = Callable[[str, str, str], dict]     # (prompt, model, effort) -> {"text", "output_tokens", "session_id"}


def claude_runner(prompt: str, model: str = "sonnet", effort: str = "medium") -> dict:
    exe = "claude.cmd" if os.name == "nt" else "claude"
    p = subprocess.run([exe, "-p", "--output-format", "json", "--model", model, "--effort", effort, "--tools", ""],
                       input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=900)
    j = json.loads(p.stdout)
    return {"text": j.get("result") or "", "output_tokens": (j.get("usage") or {}).get("output_tokens", 0),
            "session_id": j.get("session_id"), "is_error": j.get("is_error")}


def _brief_of(text: str) -> dict | None:
    blocks = re.findall(r"```(?:json)?\s*\n(.*?)```", text or "", re.S)
    for b in reversed(blocks or [text or ""]):
        try:
            got = json.loads(b)
            if isinstance(got, dict):
                return got
        except ValueError:
            continue
    return None


def shortest_ready(ask: str, n: int = 3, run: Runner = claude_runner, model: str = "sonnet", effort: str = "low") -> dict:
    """N short drafts of a brief; keep the shortest that passes Ready (I11, R13)."""
    tries = []
    for _ in range(max(1, n)):
        r = run(f"{ask}\nBe brief. {CHAIN_OF_DRAFT} Output one ```json brief.", model, effort)
        b = _brief_of(r["text"])
        tries.append({"output_tokens": r["output_tokens"], "ready": bool(b and ready.check(b)["ready"]), "brief": b})
    ok = sorted((t for t in tries if t["ready"]), key=lambda t: (len(json.dumps(t["brief"])), t["output_tokens"]))
    return {"chosen": ok[0] if ok else None, "tries": tries, "kept": "shortest Ready draft" if ok else "none Ready"}


def cothink(ask: str, run: Runner = claude_runner, outline_model: str = "haiku", model: str = "sonnet", effort: str = "medium") -> dict:
    """A cheap outline (Haiku) first; the main model executes it instead of planning from scratch (R5)."""
    o = run(f"Outline in at most 6 terse lines how to do this, no solution:\n{ask}", outline_model, "low")
    x = run(f"{ask}\nFollow this outline; do not re-plan:\n{o['text']}\n{STOP_RULE}", model, effort)
    return {"outline_tokens": o["output_tokens"], "execute_tokens": x["output_tokens"], "text": x["text"]}


def inner_dialogue(ask: str, run: Runner = claude_runner, max_rounds: int = 3, model: str = "sonnet") -> dict:
    """Iteration of Thought for hard briefs: an inner-dialogue guide asks one pointed question per round and the loop
    stops itself as soon as the draft is Ready (R1)."""
    rounds, draft, guide = [], None, ""
    for i in range(max_rounds):
        r = run(f"{ask}\n{guide}\nOutput one ```json Knos brief. {CHAIN_OF_DRAFT}", model, "medium")
        draft = _brief_of(r["text"])
        rd = ready.check(draft or {})
        rounds.append({"round": i + 1, "output_tokens": r["output_tokens"], "ready": rd["ready"], "missing": rd["missing"][:5]})
        if rd["ready"]:
            break
        guide = "Inner guide: fix exactly these and nothing else: " + "; ".join(rd["missing"][:5])
    return {"brief": draft, "rounds": rounds, "stopped": "Ready" if rounds and rounds[-1]["ready"] else f"after {len(rounds)} rounds"}


def overthinking(text: str, output_tokens: int, check: Callable[[str], bool]) -> dict | None:
    """Share of output spent after the first point where the answer already passes its check (M). Measurable only
    when the reply's text up to some code block passes; None otherwise."""
    blocks = list(re.finditer(r"```(?:python|json|py)?\s*\n(.*?)```", text or "", re.S))
    for b in blocks:
        if check(b.group(1)):
            share = 1 - b.end() / max(1, len(text))
            return {"answer_at_char": b.end(), "after_answer_share": round(share, 3),
                    "after_answer_tokens_est": round(output_tokens * share)}
    return None


def benchmark_for(brief: dict) -> dict | None:
    """The measured benchmark's overall numbers (scripts/idt_bench.py): the output-token ratio vague to Ready and both
    pass rates, over every task. One task's row is never shown as a brief's own."""
    f = Path(__file__).with_name("idt_benchmark.json")
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rows = data["rows"]
    rate = lambda k: round(sum(1 for r in rows if r[k]) / len(rows), 2) if rows else None  # noqa: E731
    return {"overall_ratio": data["ratio_vague_to_ready"], "tasks": data["tasks"], "ready_pass_rate": rate("ready_passed"),
            "vague_pass_rate": rate("vague_passed"), "raw": data["raw"]}


def fingerprint(brief: dict) -> str:
    return hashlib.sha256(json.dumps(sketch(brief), sort_keys=True).encode()).hexdigest()[:16]


def register(app, help_lines: list | None = None) -> None:
    """`knos idt check BRIEF.json | draft "ASK"` on the main app. `help_lines`: cli._HELP."""
    import importlib
    typer = importlib.import_module("typer")       # named here and not imported: this module works without the command line

    sub = typer.Typer(add_completion=False, no_args_is_help=True, help="Intent Disambiguation Tax: route a brief, or draft one cheaply.")
    app.add_typer(sub, name="idt")
    if help_lines is not None:
        help_lines.append(("idt", None, "Route a brief (effort, budget, one question) or draft the shortest Ready one with Claude."))

    @sub.command("check")
    def check_(brief: Path = typer.Argument(..., help="A brief as JSON: {milestones: [...], kill_fee_bps, challenge_s}"),
               milestone: str = typer.Option("", "--prompt-for", help="also print the prompt an agent gets for this milestone key")) -> None:
        b = json.loads(brief.read_text(encoding="utf-8"))
        rc = ready.check(b)               # what is missing, milestone by milestone, as the hosted knos_ready says it
        out = {"ready": rc["ready"], "missing": rc["missing"], "milestones": rc["milestones"], "route": route(b), "sketch": sketch(b),
               "tiers": tiers(b), "benchmark": benchmark_for(b), "not_on_claude": NOT_ON_CLAUDE}
        if milestone:
            out["agent_prompt"] = agent_prompt(b, milestone)
        typer.echo(json.dumps(out, indent=1, ensure_ascii=False))
        if not rc["ready"]:
            raise typer.Exit(1)           # not ready: a script or CI can stop on it

    @sub.command("draft")
    def draft_(ask: str = typer.Argument(..., help="What the brief is for, in plain words (a paper, a product, a task)"),
               samples: int = typer.Option(3, "--samples", help="short drafts to make; the shortest Ready one is kept"),
               outline: bool = typer.Option(False, "--outline", help="CoThink: a Haiku outline first, the main model executes it"),
               loop: bool = typer.Option(False, "--loop", help="Iteration of Thought: up to 3 rounds that stop once Ready")) -> None:
        if loop:
            got = inner_dialogue(ask)
        elif outline:
            c = cothink(ask)
            got = {"brief": _brief_of(c["text"]), "outline_tokens": c["outline_tokens"], "execute_tokens": c["execute_tokens"]}
        else:
            got = shortest_ready(ask, samples)
        typer.echo(json.dumps(got, indent=1, ensure_ascii=False))
