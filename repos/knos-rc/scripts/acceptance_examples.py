"""The acceptance examples (examples/acceptance/<task>/): a buyer's task that is not code, as a black-box bundle.

    python scripts/acceptance_examples.py [--task clean-csv] [--repeat 5] [--only honest|cheats|near_misses]

Each task folder holds TASK.md (what the buyer wrote), base/ (the buyer's repository at the base commit: a starting
point that fails, the visible examples, and `.knos/acceptance/1/`, the bundle), solution/ (an honest submission),
cheats/<name>/ (each a submission that tries to be paid without doing the work) and near_misses/<name>/ (honest
attempts that miss one rule). A submission is a folder of files laid over base/ to make the pull request's tree.

Every submission goes through `knos proof judge --base <base> --pr <tree> --issue 1`, the command prove.yml runs.
Text in a submission may carry @BASE@ (the judge's base checkout), @MARK@ (a path a cheat may try to write) and @PORT@
(a local service that does the task, for the cheat that tries to hand the work to one).
"""

from __future__ import annotations

import argparse
import contextlib
import http.server
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "acceptance"
sys.path.insert(0, str(ROOT / "src"))

from knos import judge  # noqa: E402
from knos.cli import main as knos  # noqa: E402

NEEDS_SANDBOX = ("writes_outside", "outsource_network")   # what they try is stopped by the sandbox and by nothing else


def tasks() -> list[str]:
    return sorted(p.name for p in EXAMPLES.iterdir() if (p / "base").is_dir())


def submissions(task: str) -> dict[str, list[tuple[str, Path]]]:
    """{"honest": [...], "cheats": [...], "near_misses": [...]}: (name, folder) of each."""
    root = EXAMPLES / task
    kinds = {"honest": [("solution", root / "solution")]}
    for kind in ("cheats", "near_misses"):
        kinds[kind] = sorted((p.name, p) for p in (root / kind).iterdir() if p.is_dir()) if (root / kind).is_dir() else []
    return kinds


def lay(task: str, folder: Path | None, pr: Path, fill: dict | None = None) -> Path:
    """base/ copied to `pr`, with the submission's files laid over it ({token: text} replaced in what it adds)."""
    shutil.copytree(EXAMPLES / task / "base", pr)
    for src in sorted(folder.rglob("*") if folder else []):
        if src.is_file():
            to = pr / src.relative_to(folder)
            to.parent.mkdir(parents=True, exist_ok=True)
            data = src.read_bytes()
            for token, text in (fill or {}).items():
                data = data.replace(token.encode(), str(text).encode())
            to.write_bytes(data)
    return pr


@contextlib.contextmanager
def service(task: str):
    """A local service that does the task (the honest solution behind HTTP), for the cheat that hands the work to one.
    Yields its port. The judge's sandbox has no network, so nothing reaches it from there."""
    solution = EXAMPLES / task / "solution"
    entry = next(p.name for p in (EXAMPLES / task / "base").glob("*.py"))

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            got = subprocess.run([sys.executable, entry], input=body, capture_output=True, cwd=solution, timeout=60)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(got.stdout)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def judged(task: str, name: str, folder: Path | None, repeat: int = 1) -> dict:
    """What `knos proof judge` says about one submission: {"accepted", "reasons", "sandbox", "wrote", "bundle_intact"}.
    `repeat` judgments are made (each with a new draw of the bundle's generated inputs); accepted is True only if all
    were, and `accepts` counts them."""
    accepts, last = 0, {}
    for _ in range(repeat):
        with tempfile.TemporaryDirectory(prefix="knos-accept-") as t, service(task) as port:
            tmp = Path(t)
            (tmp / "guard").mkdir()                                    # a directory only this user may write
            mark = tmp / "guard" / "marker"
            base = tmp / "base"
            shutil.copytree(EXAMPLES / task / "base", base)
            bundle = base / ".knos" / "acceptance" / "1"
            before = judge.checks_hash(bundle)
            pr = lay(task, folder, tmp / "tree", {"@BASE@": base, "@MARK@": mark, "@PORT@": port})
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                rc = knos(["proof", "judge", "--base", str(base), "--pr", str(pr), "--issue", "1",
                           "--evidence", str(tmp / "ev.json")])
            ev = json.loads((tmp / "ev.json").read_text(encoding="utf-8")) if (tmp / "ev.json").is_file() else {}
            accepts += rc == 0
            last = {"accepted": False, "reasons": [ln[4:].strip() for ln in out.getvalue().splitlines() if ln.startswith("NO ")],
                    "sandbox": bool((ev.get("evidence") or {}).get("sandbox")), "wrote": mark.exists(),
                    "bundle_intact": judge.checks_hash(bundle) == before, "output": out.getvalue()}
    last["accepts"], last["accepted"] = accepts, accepts == repeat
    return last


def run(task: str, only: str | None = None, repeat: int = 1) -> dict[str, list[dict]]:
    got: dict[str, list[dict]] = {}
    for kind, subs in submissions(task).items():
        if only in (None, kind):
            got[kind] = [{"name": name, **judged(task, name, folder, repeat)} for name, folder in subs
                         if name not in NEEDS_SANDBOX or judge.sandbox_available()]
    return got


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", choices=tasks(), action="append")
    ap.add_argument("--only", choices=["honest", "cheats", "near_misses"])
    ap.add_argument("--repeat", type=int, default=1, help="judge each submission this many times (new draws each time)")
    a = ap.parse_args(argv)
    bad = 0
    for task in a.task or tasks():
        print(f"## {task}")
        for kind, rows in run(task, a.only, a.repeat).items():
            for r in rows:
                want = kind == "honest"
                ok = r["accepted"] == want
                bad += not ok
                print(f"{'ok ' if ok else 'BAD'} {kind:11} {r['name']:24} {'accepted' if r['accepted'] else 'refused'} "
                      f"({r['accepts']}/{a.repeat} accepted)  {'; '.join(r['reasons'])[:90]}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
