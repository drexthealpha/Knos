"""The script of the knos-verify action: one pull request, read from GitHub, and a verdict as JSON.

    python verify.py --pr owner/repo#7 [--checks "test,lint"] [--commit head|merge] [--out FILE]

Two questions, both answered from GitHub's own record and neither by running the pull request's code:

  1. the free Knos check: when the description says "tests pass" or "CI is green", did a finished check fail at the
     head commit? (`knos check owner/repo#7`, the same function)
  2. with --checks: did each named check really pass at the commit? (the head commit, or with --commit merge the
     merge commit of a merged pull request). "passed" means completed with conclusion success; failed, skipped,
     still running and absent are each said as what they are.

It reads public data with the job's read-only token, holds no secret and no wallet, and writes to no chain. The
verdict goes to stdout, to --out, to the job summary (GITHUB_STEP_SUMMARY) and to the step's outputs (GITHUB_OUTPUT:
`passed`, `verdict`, the path of the JSON). Exit 1 when it did not pass, unless --no-fail.

A check's name is whatever a workflow file says, so names GitHub returned are only ever inside `untrusted`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCHEMA = "knos.verify/1"
STATES = ("passed", "failed", "skipped", "pending", "absent", "unreadable")


def verdict(pr: str, checks: list[str], commit: str = "head", get=None) -> dict:
    """The verdict for `pr` (owner/repo#n or its URL). `get(path)` answers api.github.com/<path> (tests give one)."""
    from knos import mcp, version
    from knos import terms as tm
    server = mcp.Server(github=get)
    claim = server._check_pr({"pr": pr})                      # raises mcp.Failed, in words, when GitHub cannot be read
    repo, number = claim["pr"].rsplit("#", 1)
    out = {"schema": SCHEMA, "knos": version(), "pr": claim["pr"], "head": claim["head"], "commit": claim["head"], "at": "head",
           "claim": {"verdict": claim["verdict"], "said": claim["said"], "claims": claim["claims"]},
           "checks": {}, "reasons": [], "untrusted": {"failed_checks": claim["untrusted"]["failed_checks"]}}
    if claim["verdict"] == "false":
        out["reasons"].append(claim["said"])
    if commit == "merge":
        got = server._ask(f"repos/{repo}/pulls/{number}")
        sha = str(got.get("merge_commit_sha") or "")
        if not got.get("merged") or len(sha) != 40:
            out["reasons"].append("the pull request is not merged, so it has no merge commit to read checks at")
            checks = []
        else:
            out["commit"], out["at"] = sha, "merge"
    if checks:
        want = {"checks": [{"name": n, "app": tm.ANY} for n in checks], "paths": [], "deny": []}
        runs, statuses = tm.head_checks(repo, out["commit"], server._get)
        out["checks"] = tm.evidence(want, runs, statuses, run_id=os.environ.get("GITHUB_RUN_ID", ""))
        out["reasons"] += tm.accepted(want, out["checks"], [])[1]
    out["passed"] = not out["reasons"]
    return out


def summary(v: dict) -> str:
    """The job summary: Knos's own sentences and the names the caller asked for; nothing a repository wrote."""
    lines = [f"### Knos verify: {'passed' if v['passed'] else 'not passed'}", "",
             f"Pull request `{v['pr']}`, {v['at']} commit `{v['commit'][:12]}`.", "", f"- Claim check: {v['claim']['said']}"]
    lines += [f"- Named check {i + 1}: {state}" for i, state in enumerate(v["checks"].values())]
    lines += ["", "Read from GitHub's record of the commit. No code of the pull request was run, no secret was used and "
                  "nothing was written to a chain.", ""]
    return "\n".join(lines)


def _names(text: str) -> list[str]:
    return list(dict.fromkeys(n.strip() for n in text.replace("\n", ",").split(",") if n.strip()))


def main(argv: list[str] | None = None, get=None) -> int:
    ap = argparse.ArgumentParser(prog="knos-verify", description=__doc__.split("\n\n")[0])
    ap.add_argument("--pr", required=True, help="owner/repo#number, or the pull request's github.com URL")
    ap.add_argument("--checks", default="", help="names of checks that must have passed, comma or newline separated")
    ap.add_argument("--commit", choices=("head", "merge"), default="head")
    ap.add_argument("--out", default="", help="also write the verdict JSON to this file")
    ap.add_argument("--fail", dest="no_fail", action="store_false", help="exit 1 when the verdict is not passed (the default)")
    ap.add_argument("--no-fail", dest="no_fail", action="store_true", help="exit 0 whatever the verdict (the caller reads the output)")
    ap.set_defaults(no_fail=False)
    a = ap.parse_args(argv)
    from knos import mcp
    try:
        v = verdict(a.pr, _names(a.checks), a.commit, get)
    except mcp.Failed as why:
        print(f"Knos verify could not read the pull request: {why} Nothing was decided; run it again.", file=sys.stderr)
        return 2
    text = json.dumps(v, sort_keys=True, separators=(",", ":"))
    print(text)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(summary(v))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"passed={'true' if v['passed'] else 'false'}\nverdict={text}\njson={a.out}\n")
    return 0 if v["passed"] or a.no_fail else 1


if __name__ == "__main__":
    sys.exit(main())
