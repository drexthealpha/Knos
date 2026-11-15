"""Verified reproductions, by the account that owns the repository they ran in.

    python scripts/reproductions.py [--json] [--live] [FILE_OR_FOLDER ...]

Reads every file of reproductions/ (and any file, artifact .zip or folder given after it), verifies each as
`knos reproduce --verify` does (GitHub's signature against scripts/github_oidc_keys.json, offline; `--live` also reads
the keys GitHub publishes now), and lists the valid ones grouped by repository owner. A run of Knos's own (an account
of scripts/own_github_ids.json, or a repository of drexthealpha) is never listed: it is counted under `own`, apart.
A file that does not verify, or in which a check failed or none passed, is listed under `refused`, with why.

The count it prints is the outside reproductions count: owners, runs, and the wall time of each run (from the
workflow's first step to GitHub's signature, both signed; empty for a report made by Knos 0.3.24 or older). Standard library
only: it runs on a bare Python, as the check of a pull request does.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = "scripts/github_oidc_keys.json"
OWN = "scripts/own_github_ids.json"


def _reproduce():
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from knos import reproduce
    return reproduce


def _files(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        out += sorted(p.glob("*.json")) if p.is_dir() else [p]
    return out


def survey(paths: list[Path], keys: dict[str, int], own: dict) -> dict:
    """{"owners": [{owner, owner_id, runs: [...]}], "own": n, "refused": [{file, why}]} for these files."""
    rp = _reproduce()
    owners: dict[str, dict] = {}
    mine, refused, seen = 0, [], set()
    for path in paths:
        try:
            doc, name = rp.opened(path)
        except (OSError, ValueError) as unread:
            refused.append({"file": path.name, "why": [f"not a reproduction's file ({unread})"]})
            continue
        facts, wrong = rp.verified(doc, keys, own, name)
        if any("the run is Knos's own" in w for w in wrong) and not rp.verified(doc, keys, own, name, ours=True)[1]:
            mine += 1
            continue
        why = rp.judged(facts, wrong)
        run = (facts.get("repository"), facts.get("run_id"), facts.get("run_attempt"))
        if not why and run in seen:
            why = ["the same run is listed twice"]
        if why:
            refused.append({"file": name, "why": why})
            continue
        seen.add(run)
        row = owners.setdefault(str(facts["repository_owner_id"]), {"owner": facts["repository_owner"], "owner_id": int(facts["repository_owner_id"]), "runs": []})
        row["runs"].append({k: facts[k] for k in ("repository", "run", "sha", "actor", "knos", "passed", "capabilities", "wall_seconds", "report_sha256")} | {"file": name})
    listed = sorted(owners.values(), key=lambda o: (o["owner"].lower(), o["owner_id"]))
    return {"owners": listed, "runs": sum(len(o["runs"]) for o in listed), "own": mine, "refused": refused}


def lines(got: dict) -> list[str]:
    out = [f"Outside reproductions: {got['runs']} run(s) by {len(got['owners'])} repository owner(s). Knos's own runs, not counted: {got['own']}. Refused: {len(got['refused'])}."]
    if got["owners"]:
        out += ["", "| owner | repository | run | knos | passed | wall time |", "|---|---|---|---|---|---|"]
        for o in got["owners"]:
            for r in o["runs"]:
                took = f"{r['wall_seconds']} s" if r["wall_seconds"] is not None else "not recorded"
                out.append(f"| {o['owner']} ({o['owner_id']}) | {r['repository']} | [{r['run'].rsplit('/', 1)[-1]}]({r['run']}) | {r['knos']} | {', '.join(r['passed'])} | {took} |")
    for r in got["refused"]:
        out.append(f"refused {r['file']}: " + "; ".join(r["why"]))
    return out


def main(argv: list[str]) -> int:
    rp = _reproduce()
    if any(a.startswith("-") and a not in ("--json", "--live") for a in argv):
        print(__doc__)
        return 2
    keys = rp.keys_of(json.loads((ROOT / KEYS).read_text(encoding="utf-8")))
    if "--live" in argv:
        try:
            keys.update(rp.keys_of(rp._fetch_json(rp.JWKS)))
        except (*rp.UNASKED, ValueError) as unread:
            print(f"GitHub's keys could not be read ({unread}); the archived keys were used.", file=sys.stderr)
    given = [Path(a) for a in argv if not a.startswith("-")]
    got = survey(_files([ROOT / rp.REPRODUCTIONS, *given]), keys, json.loads((ROOT / OWN).read_text(encoding="utf-8")))
    print(json.dumps(got, indent=1, sort_keys=True) if "--json" in argv else "\n".join(lines(got)))
    return 1 if got["refused"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
