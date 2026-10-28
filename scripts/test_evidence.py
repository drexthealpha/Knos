"""test_evidence (E1), live: each plan commit precedes its result commit; every published number equals what
scripts/e1_publish.py recomputes from the committed raw files; the control and the misses are on How we test Knos;
0 Qloo calls spent.

    python scripts/test_evidence.py [result file]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://drexthealpha.github.io/Knos/"


def first_commit(path: str) -> tuple[str, int]:
    out = subprocess.run(["git", "log", "--format=%H %ct", "--diff-filter=A", "--", path], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return (out[-2], int(out[-1])) if out else ("", 0)


def get(url: str) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "knos-e1"}), timeout=120) as r:
        return r.read().decode("utf-8", "replace")


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv else None
    lines, fails = [], []

    def ok(c, what):
        lines.append(f"{'ok  ' if c else 'FAIL'} {what}")
        if not c:
            fails.append(what)

    plan, pt = first_commit("docs/reference/evidence_plan.md")
    for raw in ("docs/idt/e1/runs.json", "docs/reference/e1_mutants.json", "docs/reference/e1_results.json"):
        c, t = first_commit(raw)
        ok(plan and c and t >= pt and c != plan, f"plan {plan[:7]} precedes {raw} ({c[:7]})")
    ran = json.loads((ROOT / "docs/idt/e1/runs.json").read_text(encoding="utf-8"))
    first_run = min(r["at"] for r in ran if r.get("at"))
    plan_at = subprocess.run(["git", "log", "-1", "--format=%cI", plan], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    ok(bool(first_run), f"the first IDT run is dated {first_run}; the plan was committed {plan_at}")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "e1_publish.py"), "--check"], capture_output=True, text=True, encoding="utf-8")
    ok(r.returncode == 0, f"e1_publish.py --check: {r.stdout.strip()}")
    d = json.loads((ROOT / "docs/reference/e1_results.json").read_text(encoding="utf-8"))
    page = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", get(SITE + "how-we-test.html")))
    i, m = d["idt"], d["proof_checking"]
    ok("padded" in page and str(i["control_to_ready"]) in page and str(i["control_to_ready_95"][0]) in page, f"the control is on the page: {i['control_to_ready']} [{i['control_to_ready_95'][0]}, {i['control_to_ready_95'][1]}]")
    ok("Knos missed:" in page and f"caught {m['knos_caught']} of {m['n']}" in page and ", ".join(i["ready_lost"]) in page,
       f"the misses are on the page: Knos missed {len(m['knos_misses'])}, CI caught {m['ci_caught']} of {m['n']}; the Ready brief lost on {', '.join(i['ready_lost'])}")
    front = get(SITE)
    ok(f"Knos {m['knos_caught']} of {m['n']}" in front and d["plan_url"] in front, "the front door's proof line carries the numbers, linked to the plan's commit")
    ok(d["qloo_calls_spent"] == 0, "0 Qloo calls spent")
    lines.append(f"FAIL test_evidence: {len(fails)} check(s) failed" if fails else
                 f"PASS test_evidence: IDT {i['vague_to_ready']}x [{i['vague_to_ready_95'][0]}, {i['vague_to_ready_95'][1]}], padded control {i['control_to_ready']}x "
                 f"[{i['control_to_ready_95'][0]}, {i['control_to_ready_95'][1]}] (the claim {'held' if i['claim_held'] else 'did not hold'}), pass {i['pass_rate']}; "
                 f"altered pull requests caught {m['knos_caught']} of {m['n']} (CI {m['ci_caught']}); pre-orders {d['preorders']['held']} held, {d['preorders']['released']} released, "
                 f"{d['preorders']['others']['held'] + d['preorders']['others']['released']} others'; each plan before its result; 0 Qloo calls")
    print("\n".join(lines))
    if out:
        with out.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
