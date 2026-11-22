"""L48: a dated weekly update log, docs/data/weekly.json, written from the repository's own history (git log on main):
one entry per ISO week, its dates, how many changes were merged and the link to them. The status page shows the
newest entry. Nothing is written by hand.

    python scripts/site_weekly_log.py              # write docs/data/weekly.json from git log
    python scripts/site_weekly_log.py --weeks 12   # only the last 12 weeks (default 26)
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data" / "weekly.json"
# the change lines themselves stay in git: a commit line may name a tool by its maker, and public text names Knos only
REPO = "https://github.com/drexthealpha/Knos"


def commits(repo: Path = ROOT) -> list[tuple[str, str]]:
    """(date YYYY-MM-DD, first line) of each commit on the checked-out branch, newest first."""
    out = subprocess.run(["git", "log", "--no-merges", "--format=%cs%x09%s"], cwd=repo, capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return [tuple(line.split("\t", 1)) for line in out.splitlines() if "\t" in line]   # type: ignore[misc]


def weeks(rows: list[tuple[str, str]], most: int = 26) -> list[dict]:
    """One entry per ISO week that has a change, newest first: the week's id (2026-W47), its Monday and Sunday, the count
    of changes and the link to that week's history."""
    by: dict[tuple[int, int], list[tuple[str, str]]] = {}
    for day, line in rows:
        y, w, _ = dt.date.fromisoformat(day).isocalendar()
        by.setdefault((y, w), []).append((day, line))
    out = []
    for (y, w) in sorted(by, reverse=True)[:most]:
        monday = dt.date.fromisocalendar(y, w, 1)
        items = by[(y, w)]
        out.append({"week": f"{y}-W{w:02d}", "from": monday.isoformat(), "to": (monday + dt.timedelta(days=6)).isoformat(),
                    "changes": len(items), "history": f"{REPO}/commits/main?since={monday.isoformat()}&until={(monday + dt.timedelta(days=6)).isoformat()}"})
    return out


def main(argv: list[str]) -> int:
    most = int(argv[argv.index("--weeks") + 1]) if "--weeks" in argv else 26
    data = {"_": "Written by scripts/site_weekly_log.py from git log: one entry per ISO week, newest first.", "weeks": weeks(commits(), most)}
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"weekly log: {len(data['weeks'])} weeks, newest {data['weeks'][0]['week'] if data['weeks'] else 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
