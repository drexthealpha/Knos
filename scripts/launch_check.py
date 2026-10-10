"""The launch list, checked offline: docs/LAUNCH.md's twenty rows hold, and what they name exists.

    python scripts/launch_check.py                  exit 1 when anything below fails, one line each
    python scripts/launch_check.py --history        also scan every blob ever committed for keys (about a minute)
    python scripts/launch_check.py --launch-day     also fail while a row is "partly" or "not done"

What it checks, and nothing needs the network:

    the table      docs/LAUNCH.md has the rows 1 to 20, once each, in order, each with a status word (done, partly, not
                   done, not applicable) and at least one piece of evidence it can check
    the evidence   every file named in backticks in the evidence column exists, and every `file::test` names a test
                   that file defines; the same for docs/ROLLBACK.md and SECURITY.md, whose links lead to files
    keys           scripts/secret_scan.py over the tree's files (with --history, over every blob): no hit to rotate
    the site       no file under web/ loads a script from another host or names an analytics service (items 9, 16)
    the package    src/knos sends no email (item 18) and imports no AI provider's client (item 7)
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUSES = ("done", "partly", "not done", "not applicable")
ROW = re.compile(r"^\| (\d+) \| ([^|]+) \| (" + "|".join(STATUSES) + r") \| (.+) \| ([^|]+) \|$")
ROOT_FILES = {"LICENSE", ".gitignore", "SECURITY.md", "README.md", "CONTRIBUTING.md", "pyproject.toml"}
PATH = re.compile(r"^\.?[\w.-]+(?:/[\w.-]+)*/?$")
SURFACES = ("PyPI", "npm", "tag", "Pages", "relay", "guardian pause", "time lock")
# what an analytics or error-tracking script is served from; the site serves its own files only
TRACKERS = re.compile(r"googletagmanager|google-analytics|plausible\.io|posthog|cdn\.segment|mixpanel|sentry-cdn|"
                      r"browser\.sentry|hotjar|clarity\.ms|umami\.is|usefathom|cloudflareinsights|matomo", re.I)
REMOTE_SCRIPT = re.compile(r"<script[^>]*\bsrc=[\"'](?:https?:)?//", re.I)
MAILER = re.compile(r"^\s*(?:import smtplib|from smtplib import|from email\.mime)", re.M)
PROVIDERS = re.compile(r"^\s*(?:import|from)\s+(?:anthropic|openai|mistralai|cohere|google\.generativeai|google\.genai)\b", re.M)


def _words(cell: str) -> list[str]:
    return [w.rstrip(",;:.)") for span in re.findall(r"`([^`]+)`", cell) for w in span.split()]


def evidence(root: Path, cell: str) -> tuple[int, list[str]]:
    """(how many pieces were checked, what is missing) for the backticked words of one cell."""
    checked, missing = 0, []
    for w in _words(cell):
        path, _, test = w.partition("::")
        if path.startswith(("http", "-", "<")) or not PATH.match(path) or ("/" not in path and path not in ROOT_FILES):
            continue
        checked += 1
        f = root / path
        if not f.exists():
            missing.append(f"{path}: no such file")
        elif test and not re.search(rf"^(?:async )?def {re.escape(test)}\(", f.read_text(encoding="utf-8"), re.M):
            missing.append(f"{path}: no test named {test}")
    return checked, missing


def table(root: Path) -> tuple[list[tuple[int, str, str]], list[str]]:
    """The rows (number, item, status) and the problems of docs/LAUNCH.md."""
    doc = root / "docs" / "LAUNCH.md"
    if not doc.is_file():
        return [], ["docs/LAUNCH.md is missing"]
    rows, problems = [], []
    for line in doc.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if not m:
            continue
        n, item, status, ev, _left = int(m.group(1)), m.group(2).strip(), m.group(3), m.group(4), m.group(5)
        rows.append((n, item, status))
        checked, missing = evidence(root, ev)
        problems += [f"item {n}: {x}" for x in missing]
        if not checked:
            problems.append(f"item {n}: no evidence that can be checked (a file, a `file::test` or a command)")
    if [r[0] for r in rows] != list(range(1, 21)):
        problems.append(f"docs/LAUNCH.md: the rows are {[r[0] for r in rows]}, not 1 to 20 once each")
    return rows, problems


def documents(root: Path) -> list[str]:
    problems = []
    for rel in ("docs/ROLLBACK.md", "SECURITY.md"):
        f = root / rel
        if not f.is_file():
            problems.append(f"{rel} is missing")
            continue
        text = f.read_text(encoding="utf-8")
        problems += [f"{rel}: {x}" for x in evidence(root, text)[1]]
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
            if not target.startswith("https://") and not (f.parent / target).exists():
                problems.append(f"{rel}: the link {target} leads nowhere")
    rollback = (root / "docs" / "ROLLBACK.md")
    if rollback.is_file():
        text = rollback.read_text(encoding="utf-8")
        problems += [f"docs/ROLLBACK.md: says nothing of {s}" for s in SURFACES if s not in text]
    security = root / "SECURITY.md"
    if security.is_file() and "Report a vulnerability" not in security.read_text(encoding="utf-8"):
        problems.append("SECURITY.md: no private way to report a vulnerability")
    return problems


def site_and_package(root: Path) -> list[str]:
    problems = []
    for f in sorted((root / "web").rglob("*")):
        if f.suffix in (".html", ".js", ".css") and f.is_file():
            text = f.read_text(encoding="utf-8", errors="replace")
            rel = f.relative_to(root).as_posix()
            if REMOTE_SCRIPT.search(text):
                problems.append(f"{rel}: loads a script from another host")
            if TRACKERS.search(text):
                problems.append(f"{rel}: names an analytics or tracking service")
    for f in sorted((root / "src" / "knos").rglob("*.py")):
        text = f.read_text(encoding="utf-8")
        rel = f.relative_to(root).as_posix()
        if MAILER.search(text):
            problems.append(f"{rel}: sends email")
        if PROVIDERS.search(text):
            problems.append(f"{rel}: imports an AI provider's client")
    return problems


def _scanner():
    spec = importlib.util.spec_from_file_location("secret_scan", ROOT / "scripts" / "secret_scan.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def keys(root: Path, history: bool) -> list[str]:
    s = _scanner()
    try:
        out = s.scan(s.history_blobs(root) if history else s.tree_blobs(root), s.operational(root))
    except (OSError, s.subprocess.CalledProcessError) as e:
        return [f"keys: git could not read {root} ({type(e).__name__})"]
    return [f"keys: {h['verdict']}: {h['kind']} in {h['path']}" for h in out["hits"] if h["verdict"] in ("operational", "look")]


def check(root: Path = ROOT, history: bool = False, launch_day: bool = False) -> tuple[list[tuple[int, str, str]], list[str]]:
    rows, problems = table(root)
    problems += documents(root) + site_and_package(root) + keys(root, history)
    if launch_day:
        problems += [f"item {n}: {status}: {item}" for n, item, status in rows if status in ("partly", "not done")]
    return rows, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--history", action="store_true", help="scan every blob ever committed, not only the tree")
    ap.add_argument("--launch-day", action="store_true", help="fail while any row is partly or not done")
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    rows, problems = check(Path(a.root), a.history, a.launch_day)
    count = {s: sum(1 for r in rows if r[2] == s) for s in STATUSES}
    print("launch list: " + ", ".join(f"{n} {s}" for s, n in count.items()))
    for p in problems:
        print(f"  {p}")
    print("every check held" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
