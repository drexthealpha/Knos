"""Agent A as an AI model: an open coding model (through Ollama on this machine: no key, nothing paid) is given the job's
locked test and the paper's claim, writes solution.py, and the locked test judges it. On a failure the model is shown
the test's own last lines and tries again, up to TRIES times. Nothing here is edited by hand: the code that passes is the
model's, word for word, and every try is kept with its result.

    python3 near/scripts/ai_agent.py <out.json>     (needs `ollama serve` with MODEL pulled)
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

MODEL = "qwen2.5-coder:14b"
TRIES = 12
ROOT = pathlib.Path(__file__).resolve().parents[2]
TEST = ROOT / "near" / "agents" / "job" / "test_hll.py"

TASK = """You are a coding agent paid only if your code passes a locked test you cannot change.

The paper: Flajolet, Fusy, Gandouet and Meunier (2007), "HyperLogLog". Its claim: count the distinct items of a stream
with a typical error of about 2% in about 1.5 kilobytes of memory.

Write solution.py. It must define a class Counter with add(item) and count() (count returns a number). Use only the
Python standard library. This is the locked test that will judge it, exactly:

```python
{test}
```

Answer with one Python code block holding the whole of solution.py and nothing else."""


def ask(prompt: str) -> str:
    body = json.dumps({"model": MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0.2, "num_ctx": 8192}}).encode()
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=body, headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=1200))["response"]


def code_of(answer: str) -> str:
    m = re.findall(r"```(?:python)?\n(.*?)```", answer, re.S)
    return (max(m, key=len) if m else answer).strip() + "\n"


def judge(code: str) -> tuple[bool, str]:
    d = pathlib.Path(tempfile.mkdtemp())
    try:
        shutil.copy(TEST, d / "test_hll.py")
        (d / "solution.py").write_text(code, encoding="utf-8")
        r = subprocess.run([sys.executable, "test_hll.py"], cwd=d, capture_output=True, text=True, timeout=300)
        lines = (r.stdout + r.stderr).strip().splitlines()
        return r.returncode == 0, ("\n".join(lines[-8:]) if lines else f"no output, exit {r.returncode}")[:1200]   # the test's last lines, its traceback included
    except subprocess.TimeoutExpired:
        return False, "Failed: the test ran over 300 s."
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main(out: str) -> int:
    task = TASK.format(test=TEST.read_text(encoding="utf-8"))
    prompt, tries = task, []
    for n in range(1, TRIES + 1):
        t0 = time.time()
        code = code_of(ask(prompt))
        ok, said = judge(code)
        tries.append({"try": n, "passed": ok, "said": said, "seconds": round(time.time() - t0, 1), "code": code})
        print(f"try {n}: {said}", flush=True)
        if ok:
            break
        prompt = task + f"\n\nYour last solution.py was:\n```python\n{code}```\nThe locked test printed: {said}\nFix it. Answer with the whole new solution.py in one Python code block."
    won = next((t for t in tries if t["passed"]), None)
    pathlib.Path(out).write_text(json.dumps({"model": MODEL, "tries": tries, "passed": bool(won), "solution": won["code"] if won else None}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
