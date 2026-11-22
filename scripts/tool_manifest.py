"""Anyone can add a check to Knos: a small manifest beside its locked test (IQ PLAN.md L49; DISTRIBUTION/D4.md:210).

    python scripts/tool_manifest.py              # every tools/<id>/manifest.json: listed, or refused with the reason
    python scripts/tool_manifest.py tools/x      # one manifest

A manifest is tools/<id>/manifest.json:

    {"id": "limit-check", "title": "...", "line": "...", "inputs": ["table", ...],
     "program": "<path of the program>", "test": "<path of its locked test>",
     "data": ["<a file or folder the test reads>", ...], "sample": "<path>", "timeout_s": 60}

Paths are relative to the repository. A check is listed only when its locked test passes: the test, the program (as
solution.py) and the data are copied into an empty folder, laid out as they sit beside the test, and the test runs there
with `python -E -s -B`, as the checker runs a locked test (near/agents/checker.py). A manifest whose test is missing or
fails is refused, with the reason. /api/tools lists what `listed()` returns (the app's part, apps/wanted).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ID = re.compile(r"[a-z0-9][a-z0-9-]{1,40}")
NEED = ("id", "title", "line", "inputs", "program", "test")


def _inside(root: Path, rel: object) -> Path | None:
    if not isinstance(rel, str) or not rel or rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
        return None
    p = (root / rel).resolve()
    return p if p.is_relative_to(root.resolve()) else None


def check(folder: Path, root: Path = ROOT) -> tuple[dict | None, str]:
    """(the manifest, "") when its locked test passes, else (None, the reason it is refused)."""
    try:
        m = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"no readable manifest.json: {e}"
    if not isinstance(m, dict):
        return None, "manifest.json is not an object"
    missing = [k for k in NEED if not m.get(k)]
    if missing:
        return None, "the manifest lacks " + ", ".join(missing)
    if not ID.fullmatch(str(m["id"])) or m["id"] != folder.name:
        return None, f"the id must be the folder's name in lower case letters, digits and dashes ({folder.name})"
    test, program = _inside(root, m["test"]), _inside(root, m["program"])
    if not test or not test.is_file():
        return None, f"its locked test {m['test']} is missing"
    if not program or not program.is_file():
        return None, f"its program {m['program']} is missing"
    data = []
    for rel in m.get("data") or []:
        p = _inside(root, rel)
        if not p or not p.exists():
            return None, f"the data {rel} is missing"
        data.append(p)
    timeout = int(m.get("timeout_s") or 60)
    with tempfile.TemporaryDirectory(prefix="knos-tool-") as tmp:
        box = Path(tmp)
        shutil.copy2(test, box / test.name)
        shutil.copy2(program, box / "solution.py")
        for p in data:
            try:
                rel = p.relative_to(test.parent)
            except ValueError:
                return None, f"the data {p.relative_to(root).as_posix()} does not sit beside its test"
            dest = box / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            (shutil.copytree if p.is_dir() else shutil.copy2)(p, dest)
        try:
            r = subprocess.run([sys.executable, "-E", "-s", "-B", test.name], cwd=box, capture_output=True, text=True,
                               timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, f"its locked test ran past {timeout} s"
    last = (r.stdout.strip().splitlines() or [""])[-1][:300]
    if r.returncode != 0:
        return None, f"its locked test failed: {last or r.stderr.strip()[-300:]}"
    return m, ""


def listed(root: Path = ROOT) -> tuple[list[dict], dict[str, str]]:
    """The checks /api/tools may list ({id, title, line, inputs}) and the refused ones with their reasons."""
    ok, refused = [], {}
    for folder in sorted((root / "tools").glob("*/")):
        if not (folder / "manifest.json").exists():
            continue
        m, why = check(folder, root)
        if m:
            ok.append({k: m[k] for k in ("id", "title", "line", "inputs")})
        else:
            refused[folder.name] = why
    return ok, refused


def main(argv: list[str]) -> int:
    if argv:
        m, why = check((ROOT / argv[0]).resolve())
        print(f"listed: {m['id']}" if m else f"refused: {why}")
        return 0 if m else 1
    ok, refused = listed()
    for t in ok:
        print(f"listed: {t['id']}")
    for k, why in refused.items():
        print(f"refused: {k}: {why}")
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
