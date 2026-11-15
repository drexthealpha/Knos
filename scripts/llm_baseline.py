"""Kept for its record: a tool of the earlier demand-check work, not of Knos's locked-test flow.
test_llm_baseline, the first arm: Claude alone (no tools, no data) answers each idea of the comparison
with the same four fields Knos answers (verdict, audience, cities, price tier). Run on the founder's PC with the Claude
Code CLI on its subscription (`claude -p --output-format json`): no server key. Each answer is kept with the model's
own words, then scripts/qloo_vs_open_signals.py --claude <file> publishes the three arms side by side.

    python scripts/llm_baseline.py <out.json>
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qloo_vs_open_signals import IDEAS  # noqa: E402

AGES = ["24_and_younger", "25_to_29", "30_to_34", "35_to_44", "45_to_54", "55_and_older"]
PROMPT = """Judge the demand for one product idea from what you already know (no searching, no tools).
Idea: {idea}
Market: United States.
Answer with JSON only, no other text:
{{"verdict": "OPEN" if enough people want it now to open pre-orders, else "REFUSE",
 "age": the age group most likely to buy, one of {ages},
 "gender": "male" or "female", whichever leans more,
 "cities": the 3 US cities to launch in first,
 "tier": one of "budget", "mid", "premium", "luxury",
 "why": one short sentence}}"""


def ask(idea: str) -> dict:
    claude = (shutil.which("claude.cmd") if sys.platform == "win32" else None) or shutil.which("claude")   # npm's Windows shim is .cmd
    # no project files, no memory of Knos; Windows may still hold the CLI's files when the directory is removed
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as empty:
        # the prompt goes in on stdin: Windows runs the CLI through a .cmd shim, which cuts an argument at its first newline
        r = subprocess.run([claude, "-p", "--output-format", "json", "--max-turns", "1",
                            "--disallowed-tools", "WebSearch", "WebFetch", "Bash", "Read", "Write", "Edit", "Glob", "Grep", "Agent"],
                           input=PROMPT.format(idea=idea, ages=AGES), cwd=empty, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
    env = json.loads(r.stdout)
    text = env.get("result") or ""
    m = re.search(r"\{.*\}", text, re.S)
    got = json.loads(m.group(0)) if m else {}
    age, gender = got.get("age") if got.get("age") in AGES else "", got.get("gender") if got.get("gender") in ("male", "female") else ""
    return {"verdict": got.get("verdict") if got.get("verdict") in ("OPEN", "REFUSE") else None,
            "audience": ", ".join(x for x in (str(age).replace("_", " "), gender) if x),
            "cities": [str(c) for c in (got.get("cities") or [])][:3], "tier": got.get("tier") if got.get("tier") in ("budget", "mid", "premium", "luxury") else "",
            "why": str(got.get("why") or "")[:240], "model": next(iter((env.get("modelUsage") or {}).keys()), env.get("model") or ""),
            "raw": text[:1200]}


def main(argv: list[str]) -> int:
    out = Path(argv[0])
    done = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    for field, idea in IDEAS:
        if idea in done and done[idea].get("verdict"):
            continue
        t = time.time()
        try:
            done[idea] = {**ask(idea), "field": field, "seconds": round(time.time() - t, 1)}
        except (ValueError, subprocess.SubprocessError, OSError, RecursionError) as why:   # RecursionError: Windows' rmtree
            done[idea] = {"error": f"{type(why).__name__}: {str(why)[:160]}", "field": field}
        a = done[idea]
        print(f"{field:9} {idea[:44]:44} Claude: {a.get('verdict')}, {a.get('audience') or '-'}, {'/'.join(a.get('cities') or []) or '-'}, "
              f"{a.get('tier') or '-'} {a.get('error') or ''}", flush=True)
        out.write_text(json.dumps(done, indent=1), encoding="utf-8")
    ok = sum(1 for i in IDEAS if done.get(i[1], {}).get("verdict"))
    print(f"Claude alone answered {ok} of {len(IDEAS)}")
    return 0 if ok == len(IDEAS) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
