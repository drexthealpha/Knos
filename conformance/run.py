"""Run the conformance kit against an implementation.

    python conformance/run.py --impl "<command>" [--format terms] [--require-all] [--json]

The command is started once. Every case of the kit goes to its standard input as one line of JSON,

    {"id": "terms/4", "op": "terms.hash", "input": {...}}

and it answers each on its standard output with one line of JSON, in any order:

    {"id": "terms/4", "output": ...}        the answer
    {"id": "terms/4", "refused": true}      the input is not valid in this format
    {"id": "terms/4", "unsupported": true}  this implementation does not do this operation

An answer passes when it equals what the vector expects: the same JSON value, or a refusal where one is expected.
Exit 0: no case failed (with --require-all: and none was unsupported). Exit 1 otherwise. The vectors are checked
against the hashes in manifest.json first, so a run is always against the kit version the manifest names.

Standard library only: an implementer needs Python 3.10 and nothing of Knos's.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "manifest.json"


class Changed(Exception):
    """A vector file is not the one the manifest names."""


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def content_hash(data: dict, groups: list[str] | None = None) -> str:
    """sha256 of the vectors as canonical JSON (keys sorted, no white space, UTF-8): the same whatever the file's line
    ends or indentation. `groups`: only these top-level keys (the receipt file may gain groups for a later version;
    the groups of the versions named here may not change)."""
    kept = {g: data[g] for g in groups} if groups else data
    return hashlib.sha256(json.dumps(kept, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _file(entry: dict) -> dict:
    data = json.loads((HERE / entry["file"]).resolve().read_text(encoding="utf-8"))
    if content_hash(data, entry.get("groups")) != entry["sha256"]:
        raise Changed(f"{entry['file']} does not hold the vectors kit version {manifest()['kit']} names (their sha256 differs): the "
                      "vectors of a published version never change")
    return data


def _set(receipt: dict, changes: dict) -> dict:
    """An invalid receipt: the valid one it was made from, with the fields at these dotted paths replaced."""
    r = copy.deepcopy(receipt)
    for path, value in changes.items():
        steps, node = path.split("."), r
        for step in steps[:-1]:
            node = node[int(step)] if isinstance(node, list) else node[step]
        last = steps[-1]
        node[int(last) if isinstance(node, list) else last] = value
    return r


def receipt_cases(vectors: dict, groups: list[str] | None = None) -> list[dict]:
    """The cases of a receipt vector file (docs/receipt/vectors.json, vectors.v4.json): every valid receipt is accepted
    and has the digest named; every invalid one is refused. `groups`: the file's groups the manifest names; a group
    `invalid<x>` is made from the receipts of `valid<x>`."""
    groups = groups or ["valid", "invalid", "valid_v2", "invalid_v2", "valid_v3", "invalid_v3"]
    out = []
    for group in (g for g in groups if g.startswith("valid")):
        for i, v in enumerate(vectors[group]):
            out.append({"id": f"receipt/{group}/{i}/digest", "op": "receipt.digest", "name": v["name"], "input": {"receipt": v["receipt"]},
                        "expect": {"output": v["sha256"]}})
            out.append({"id": f"receipt/{group}/{i}/check", "op": "receipt.check", "name": v["name"], "input": {"receipt": v["receipt"]},
                        "expect": {"output": True}})
            if "authorises_payment" in v:       # version 4: a valid receipt is not always one that authorises payment
                out.append({"id": f"receipt/{group}/{i}/verdict", "op": "receipt.verdict", "name": v["name"], "input": {"receipt": v["receipt"]},
                            "expect": {"output": {"verdict": v["verdict"], "authorises_payment": v["authorises_payment"]}}})
    for group in (g for g in groups if g.startswith("invalid")):
        of = "valid" + group[len("invalid"):]
        for i, v in enumerate(vectors[group]):
            out.append({"id": f"receipt/{group}/{i}/check", "op": "receipt.check", "name": v["name"],
                        "input": {"receipt": _set(vectors[of][v["of"]]["receipt"], v["set"])}, "expect": {"refused": True, "why": v["why"]}})
    return out


def cases(only: list[str] | None = None) -> list[dict]:
    """Every case of the kit, each with the format it belongs to."""
    out = []
    for entry in manifest()["formats"]:
        if only and entry["format"] not in only:
            continue
        data = _file(entry)
        for c in receipt_cases(data, entry.get("groups")) if entry["format"].startswith("receipt") else data["cases"]:
            out.append({**c, "format": entry["format"]})
    return out


def ask(command: list[str], todo: list[dict], timeout: float = 300) -> tuple[dict[str, dict], str]:
    """({case id: the implementation's answer}, what it wrote to standard error)."""
    lines = "".join(json.dumps({"id": c["id"], "op": c["op"], "input": c["input"]}) + "\n" for c in todo)
    done = subprocess.run(command, input=lines.encode("utf-8"), capture_output=True, timeout=timeout)
    answers: dict[str, dict] = {}
    for line in done.stdout.decode("utf-8", "replace").splitlines():
        try:
            got = json.loads(line)
        except ValueError:
            continue
        if isinstance(got, dict) and isinstance(got.get("id"), str):
            answers[got["id"]] = got
    return answers, done.stderr.decode("utf-8", "replace")


def verdict(case: dict, answer: dict | None) -> str:
    """"pass", "unsupported", or why it failed."""
    if answer is None:
        return "no answer"
    if answer.get("unsupported") is True:
        return "unsupported"
    want = case["expect"]
    if want.get("refused"):
        return "pass" if answer.get("refused") is True else f"accepted what must be refused ({want.get('why', 'not valid')})"
    if answer.get("refused") is True:
        return "refused what is valid"
    if "output" not in answer:
        return "no output"
    return "pass" if answer["output"] == want["output"] else f"answered {json.dumps(answer['output'])[:120]}, expected {json.dumps(want['output'])[:120]}"


def run(command: list[str], only: list[str] | None = None) -> dict:
    """{"kit", "formats": {format: {"cases", "passed", "unsupported", "failed": [{"id", "op", "name", "why"}]}},
    "unsupported_ops": [...], "stderr"}."""
    todo = cases(only)
    answers, err = ask(command, todo)
    out: dict = {"kit": manifest()["kit"], "formats": {}, "unsupported_ops": [], "stderr": err[-2000:]}
    for c in todo:
        f = out["formats"].setdefault(c["format"], {"cases": 0, "passed": 0, "unsupported": 0, "failed": []})
        f["cases"] += 1
        v = verdict(c, answers.get(c["id"]))
        if v == "pass":
            f["passed"] += 1
        elif v == "unsupported":
            f["unsupported"] += 1
            if c["op"] not in out["unsupported_ops"]:
                out["unsupported_ops"].append(c["op"])
        else:
            f["failed"].append({"id": c["id"], "op": c["op"], "name": c["name"], "why": v})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--impl", required=True, help="the command that runs the implementation, as one string")
    ap.add_argument("--format", action="append", help="only this format (repeatable): " + ", ".join(e["format"] for e in manifest()["formats"]))
    ap.add_argument("--require-all", action="store_true", help="an unsupported case fails the run")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    a = ap.parse_args(argv)
    try:
        got = run(shlex.split(a.impl), a.format)
    except Changed as why:
        print(f"stopped: {why}", file=sys.stderr)
        return 2
    failed = sum(len(f["failed"]) for f in got["formats"].values())
    skipped = sum(f["unsupported"] for f in got["formats"].values())
    if a.json:
        print(json.dumps(got, indent=1))
    else:
        print(f"Knos conformance kit, version {got['kit']}")
        for name, f in got["formats"].items():
            print(f"{name:10} {f['passed']} of {f['cases']} passed" + (f", {f['unsupported']} not implemented" if f["unsupported"] else "")
                  + (f", {len(f['failed'])} FAILED" if f["failed"] else ""))
            for x in f["failed"]:
                print(f"  FAILED {x['id']} ({x['op']}: {x['name']}): {x['why']}")
        if got["unsupported_ops"]:
            print("not implemented: " + ", ".join(sorted(got["unsupported_ops"])))
        if failed and got["stderr"].strip():
            print("the implementation's standard error ended with:\n" + got["stderr"].strip()[-600:])
    return 1 if failed or (a.require_all and skipped) else 0


if __name__ == "__main__":
    raise SystemExit(main())
