"""The slop audit, end to end:

    PYTHONPATH=src python -m research.slop_audit rows   --data ~/knos/data/aidev/v4 --v3 ~/knos/data/aidev/v3 --work ~/knos/data/aidev/work
    PYTHONPATH=src python -m research.slop_audit ci     --work ~/knos/data/aidev/work      (read-only GitHub; resumable)
    PYTHONPATH=src python -m research.slop_audit report --work ~/knos/data/aidev/work [--out research/slop_audit/out]
    PYTHONPATH=src python -m research.slop_audit fixture   (the committed tiny fixture through the same report; without
                                                            --out it writes to a new temporary folder, never over out/)

`rows` reads the dataset (needs duckdb + pyarrow); `ci` asks GitHub for the head-commit checks of the pull requests
whose description claims tests pass or CI is green; `report` writes slop_audit.json and slop_audit.csv. The report
needs neither the dataset nor the network once rows.jsonl and the CI cache exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import aidev, audit

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
FIXTURE = HERE / "fixtures" / "tiny.json"
METHOD_VERSION = 1


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def claimants(rows: list[dict]) -> list[dict]:
    return [{"id": r["id"], "repo": r["repo"], "number": r["number"]} for r in rows if audit.claims_any(r)]


def join_ci(rows: list[dict], ci_dir: Path) -> list[dict]:
    """Each claimant's CI class from the cache (None where it was not read). The per-pull-request files are gathered
    once into ci_classes.json beside the cache (one small file reads far faster than thousands on a busy disk)."""
    gathered = ci_dir.with_name("ci_classes.json")
    if gathered.exists():
        classes = {int(k): v for k, v in json.loads(gathered.read_text()).items()}
    else:
        classes = {}
        for f in ci_dir.glob("*.json"):
            classes[int(f.stem)] = json.loads(f.read_text())["class"]
        gathered.write_text(json.dumps(classes))
    out = []
    for r in rows:
        r = dict(r)
        r["ci"] = classes.get(r["id"]) if audit.claims_any(r) else None
        out.append(r)
    return out


def report(rows: list[dict], meta: dict, out: Path, links: list[list[int]] | None = None) -> dict:
    t = audit.table(rows, links)
    t["meta"] = meta
    out.mkdir(parents=True, exist_ok=True)
    (out / "slop_audit.json").write_text(audit.dumps(t), encoding="utf-8")
    (out / "slop_audit.csv").write_text(audit.to_csv(t), encoding="utf-8")
    return t


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m research.slop_audit")
    ap.add_argument("cmd", choices=["rows", "ci", "report", "fixture"])
    ap.add_argument("--data", type=Path, help="folder holding the AIDev v4 parquet tables")
    ap.add_argument("--v3", type=Path, help="folder holding AIDev v3 related_issue.parquet (issue links)")
    ap.add_argument("--work", type=Path, help="folder for rows.jsonl and the CI cache (outside the repository)")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--max-seconds", type=float, default=3300)
    ap.add_argument("--ci-read-on", default="", help="the UTC date the CI record was read (written into the report)")
    a = ap.parse_args(argv)
    if a.cmd != "fixture" and a.work is None:
        ap.error("--work is required for rows, ci and report")
    if a.cmd == "rows" and a.data is None:
        ap.error("--data is required for rows")

    if a.cmd == "fixture":
        if a.out == OUT:                 # the committed audit output in out/ is never overwritten by the fixture
            import tempfile
            a.out = Path(tempfile.mkdtemp(prefix="slop-fixture-"))
        fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
        from . import rules
        rows = []
        for pr in fx["prs"]:
            files = [rules.file_signals(f["filename"], f["status"], f.get("patch")) for f in pr["files"]]
            rows.append({"id": pr["id"], "agent": pr["agent"], "merged": pr["merged"], "repo": pr["repo"],
                         "number": pr["number"], "claims": rules.read_claims(pr["body"]), "has_files": bool(files),
                         "diff": rules.pr_signals(files) if files else None,
                         "ci": pr.get("ci") if audit.claims_any({"claims": rules.read_claims(pr["body"])}) else None})
        t = report(rows, {"dataset": "fixture (synthetic)", "method_version": METHOD_VERSION}, a.out, fx["issue_links"])
        print(json.dumps(t["all"]["fails_a_measured_knos_check"]))
        return 0

    rows_file = a.work / "rows.jsonl"
    if a.cmd == "rows":
        rows = aidev.build_rows(a.data, cache=rows_file)
        meta = {"files": {p.name: _sha256(p) for p in sorted(a.data.glob("*.parquet")) if p.name in aidev.TABLES}}
        if a.v3:
            (a.work / "issue_links.json").write_text(json.dumps(aidev.issue_links(a.v3)))
            meta["issue_links_from"] = {"dataset_version": "v3", "dataset_revision": aidev.V3_REVISION,
                                        "related_issue.parquet": _sha256(a.v3 / "related_issue.parquet")}
        (a.work / "rows_meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True))
        print(f"rows: {len(rows)} pull requests, {sum(r['has_files'] for r in rows)} with a file list, "
              f"{len(claimants(rows))} claim tests pass or CI is green")
        return 0
    rows = aidev.build_rows(a.data, cache=rows_file)
    if a.cmd == "ci":
        from . import ci
        got = ci.read(claimants(rows), a.work / "ci", max_seconds=a.max_seconds)
        print(f"ci: {len(got)} of {len(claimants(rows))} claimants read")
        return 0
    rows = join_ci(rows, a.work / "ci")
    meta = {"dataset": "hao-li/AIDev (AIDev-pop: repositories with more than 100 stars)", "dataset_version": "v4",
            "dataset_revision": aidev.REVISION, "dataset_cutoff": "Nov 2025 (dataset card); PRs created 2024-12-24 to 2025-10-24",
            "dataset_license": "CC BY 4.0 (source repositories keep their own licences)",
            "paper": "arXiv:2507.15003", "method_version": METHOD_VERSION, "ci_read_on": a.ci_read_on,
            **json.loads((a.work / "rows_meta.json").read_text())}
    links_file = a.work / "issue_links.json"
    t = report(rows, meta, a.out, json.loads(links_file.read_text()) if links_file.exists() else None)
    s = t["all"]
    print(json.dumps({k: s[k] for k in ("prs", "prs_with_file_list", "claims_tests_pass_or_ci_green", "false_claim_of_settled",
                                        "any_cheat_rule", "fails_a_measured_knos_check")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
