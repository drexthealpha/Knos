"""E1 (docs/reference/evidence_plan.md): every published number recomputed from the committed raw files, wins and
losses alike, and written to docs/reference/e1_results.json, which the front door's proof line and How we test Knos
read. --check recomputes and exits 1 on any difference with the file.

    python scripts/e1_publish.py [--check] [--preorders]      --preorders reads the pre-order counts from the live app
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "docs" / "reference"
OUT = REF / "e1_results.json"
APP = "https://knos.onrender.com"
BLOB = "https://github.com/drexthealpha/Knos/blob/{commit}/{path}"


def plan_commit() -> str:
    return subprocess.run(["git", "log", "--format=%H", "--diff-filter=A", "-1", "--", "docs/reference/evidence_plan.md"],
                          cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def idt() -> dict:
    s = json.loads((ROOT / "docs" / "idt" / "e1" / "summary.json").read_text(encoding="utf-8"))
    runs = json.loads((ROOT / "docs" / "idt" / "e1" / "runs.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import idt_bench
    again = idt_bench.summary(runs)
    assert again == s, "docs/idt/e1/summary.json is not what its runs give"
    c = s["control"]
    return {"tasks": s["tasks"], "vague_to_ready": c["ratio_vague_to_ready"], "vague_to_ready_95": c["interval_vague_to_ready"],
            "control_to_ready": c["ratio_control_to_ready"], "control_to_ready_95": c["interval_control_to_ready"],
            "pass_rate": c["pass_rate"], "ready_lost": [x["task"] for x in c["ready_lost"]],
            "claim_held": bool(c["interval_vague_to_ready"][0] > 1 and c["interval_control_to_ready"][0] > 1),
            "raw": ["docs/idt/e1/runs.json", "docs/idt/e1/summary.json"]}


def mutants() -> dict:
    d = json.loads((REF / "e1_mutants.json").read_text(encoding="utf-8"))
    rows = d["rows"]
    assert d["n"] == len(rows) and d["knos_caught"] == sum(r["knos_caught"] for r in rows) and d["ci_caught"] == sum(r["ci_caught"] for r in rows)
    return {"n": len(rows), "knos_caught": d["knos_caught"], "ci_caught": d["ci_caught"],
            "knos_misses": [f"{r['repo']}: {r['operator']}, {r['variant']}" for r in rows if not r["knos_caught"]],
            "ci_misses": [f"{r['repo']}: {r['operator']}, {r['variant']}" for r in rows if not r["ci_caught"]],
            "per_operator": d["per_operator"], "raw": ["docs/reference/e1_mutants.json"]}


def qloo() -> list[dict]:
    w = json.loads((REF / "where_truth.json").read_text(encoding="utf-8"))
    t = json.loads((REF / "taste_truth.json").read_text(encoding="utf-8"))
    lift = json.loads((REF / "qloo_lift_ranked.json").read_text(encoding="utf-8"))
    diff = json.loads((REF / "e1_qloo_diff.json").read_text(encoding="utf-8"))
    return [
        {"test": "the verdict against a free-data baseline", "made": diff["made"], "result": f"changed on {diff['summary']['verdict']} of {diff['summary']['rows']} ideas",
         "said": "Qloo changed the verdict", "raw": "docs/reference/e1_qloo_diff.json (from https://knos.onrender.com/api/qloo-diff)"},
        {"test": "where demand is (Census business counts)", "made": w["made"], "result": f"{w['mean_overlap']['knos_with_qloo']} with Qloo against {w['mean_overlap']['claude_alone']} for the model alone, "
         f"difference {w['difference']} (95% interval {w['bootstrap']['interval_95'][0]} to {w['bootstrap']['interval_95'][1]})", "said": "Qloo lost", "raw": "docs/reference/where_truth.json"},
        {"test": "taste (film fans)", "made": t["made"], "result": f"{t['mean_overlap']['knos_with_qloo']} against {t['mean_overlap']['claude_alone']}, difference {t['difference']} "
         f"(95% interval {t['bootstrap']['interval_95'][0]} to {t['bootstrap']['interval_95'][1]})", "said": "a tie", "raw": "docs/reference/taste_truth.json"},
        {"test": "a public dataset of crowdfunded product launches", "made": lift["made"], "result": f"rank correlation {lift['spearman']['open_signals_qloo']} with Qloo against "
         f"{lift['spearman']['open_signals']} without, difference {lift['difference']} (95% interval {lift['bootstrap']['interval_95'][0]} to {lift['bootstrap']['interval_95'][1]})",
         "said": "no lift", "raw": "docs/reference/qloo_lift_ranked.json"}]


def _get(path: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(APP + path, headers={"User-Agent": "knos-e1"}), timeout=120) as r:
        return json.loads(r.read())


def preorders() -> dict:
    """Every public project's orders, as the app holds them: held and released, split by who opened the project."""
    ids = [p["id"] for p in _get("/api/projects?take=100")["projects"]]
    held = released = 0
    mine = {"held": 0, "released": 0}
    labels: dict[str, int] = {}
    for pid in ids:
        p = _get(f"/api/project?id={pid}")
        label = str(p.get("owner_label") or "")
        for m in p.get("milestones") or []:
            for o in m.get("orders") or []:
                st = (o or {}).get("status")
                if st not in ("locked", "released"):
                    continue
                labels[label] = labels.get(label, 0) + 1
                held += st == "locked"
                released += st == "released"
                if not label or label.lower().startswith(("test", "knos", "guest", "founder", "e2e")):
                    mine["held" if st == "locked" else "released"] += 1
    return {"projects": len(ids), "held": held, "released": released, "founders": mine,
            "others": {"held": held - mine["held"], "released": released - mine["released"]}, "owner_labels": labels,
            "rule": "an order counts as the founder's when its project was opened by the founder or by one of Knos's own test runs (owner label empty, or starting test, knos, guest, founder or e2e)"}


def build(read_preorders: bool) -> dict:
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    c = plan_commit()
    return {"plan": "docs/reference/evidence_plan.md", "plan_commit": c, "plan_url": BLOB.format(commit=c, path="docs/reference/evidence_plan.md"),
            "idt": idt(), "proof_checking": mutants(), "qloo": qloo(),
            "preorders": preorders() if read_preorders else old.get("preorders"), "qloo_calls_spent": 0}


def main(argv: list[str]) -> int:
    doc = build("--preorders" in argv)
    if "--check" in argv:
        old = json.loads(OUT.read_text(encoding="utf-8"))
        same = {k: v for k, v in old.items() if k != "preorders"} == {k: v for k, v in doc.items() if k != "preorders"}
        print("e1_results.json is what the raw files give" if same else "e1_results.json differs from the raw files")
        return 0 if same else 1
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    i, m = doc["idt"], doc["proof_checking"]
    print(f"IDT {i['vague_to_ready']} {i['vague_to_ready_95']}, control {i['control_to_ready']} {i['control_to_ready_95']}, pass {i['pass_rate']}; "
          f"caught {m['knos_caught']} of {m['n']} (CI {m['ci_caught']}); preorders {doc['preorders']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
