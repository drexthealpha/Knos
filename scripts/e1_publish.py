"""E1 (docs/reference/evidence_plan.md): every published number recomputed from the committed raw files, wins and
losses alike, and written to docs/reference/e1_results.json. --check recomputes and exits 1 on any difference with the file.

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
            "idt": idt(), "proof_checking": mutants(),
            "preorders": preorders() if read_preorders else old.get("preorders")}


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
