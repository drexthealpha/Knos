"""docs/LAUNCH.md answers the twenty items of the pre-launch list, and scripts/launch_check.py holds it to what exists:
a named file or test that is missing, a key in the tree, an analytics script, an email sender or an AI provider's client
each fail it. docs/ROLLBACK.md covers every surface and cites its sources. Reads files only; the one subprocess is the
script on this repository, with no network."""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("launch_check", ROOT / "scripts" / "launch_check.py")
assert spec and spec.loader
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)

ITEMS = ["API key", "rotate", "rate limiting", "auth on every route", "data rules", "validate every input", "spending cap",
         "stack traces", "error tracking", "back up", "404", "Android", "3 seconds", "OG image", "privacy policy",
         "analytics", "password reset", "spam", "contact", "rollback"]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_this_repository_passes_and_every_item_of_the_list_has_its_row():
    rows, problems = lc.check(ROOT)
    assert problems == []
    assert [n for n, _i, _s in rows] == list(range(1, 21))
    for (n, item, _status), word in zip(rows, ITEMS):
        assert word.lower() in item.lower(), (n, item, word)
    # an item that does not apply says why, in the row
    page = read("docs/LAUNCH.md")
    for n, _item, status in rows:
        if status == "not applicable":
            line = next(x for x in page.splitlines() if x.startswith(f"| {n} |"))
            assert re.search(r"Knos (calls|sends) no|there is no", line), line


def test_the_script_says_the_counts_and_exits_0_and_launch_day_names_what_is_left():
    p = subprocess.run([sys.executable, str(ROOT / "scripts" / "launch_check.py")], capture_output=True, encoding="utf-8")
    assert p.returncode == 0 and p.stdout.startswith("launch list: ") and "every check held" in p.stdout
    rows, problems = lc.check(ROOT, launch_day=True)
    left = {n for n, _i, s in rows if s in ("partly", "not done")}
    assert left and {int(re.match(r"item (\d+):", x).group(1)) for x in problems} == left


def _launch(rows: dict[int, str]) -> str:
    head = "| # | item | status | evidence | not done |\n|---|---|---|---|---|\n"
    return head + "".join(f"| {n} | item {n} | done | {ev} | nothing |\n" for n, ev in sorted(rows.items()))


def test_a_missing_file_a_missing_test_a_missing_row_or_no_evidence_fails(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    rows = {n: "`tests/test_x.py::test_a`" for n in range(1, 21)}
    (tmp_path / "docs" / "LAUNCH.md").write_text(_launch(rows), encoding="utf-8")
    assert lc.table(tmp_path)[1] == []
    rows[5] = "`tests/test_x.py::test_gone`"
    rows[6] = "`tests/test_y.py`, and `python scripts/none.py --x`"
    rows[7] = "a sentence with no file"
    del rows[20]
    (tmp_path / "docs" / "LAUNCH.md").write_text(_launch(rows), encoding="utf-8")
    assert lc.table(tmp_path)[1] == ["item 5: tests/test_x.py: no test named test_gone", "item 6: tests/test_y.py: no such file",
                                     "item 6: scripts/none.py: no such file",
                                     "item 7: no evidence that can be checked (a file, a `file::test` or a command)",
                                     f"docs/LAUNCH.md: the rows are {list(range(1, 20))}, not 1 to 20 once each"]


def test_an_analytics_script_an_email_sender_or_a_providers_client_fails(tmp_path: Path):
    (tmp_path / "web").mkdir()
    (tmp_path / "src" / "knos").mkdir(parents=True)
    (tmp_path / "web" / "index.html").write_text('<script async src="https://example.org/x.js"></script>', encoding="utf-8")
    (tmp_path / "web" / "app.js").write_text('fetch("https://plausible.io/api/event")', encoding="utf-8")
    (tmp_path / "src" / "knos" / "notify.py").write_text("import smtplib\n", encoding="utf-8")
    (tmp_path / "src" / "knos" / "think.py").write_text("from openai import OpenAI\n", encoding="utf-8")
    assert lc.site_and_package(tmp_path) == ["web/app.js: names an analytics or tracking service", "web/index.html: loads a script from another host",
                                             "src/knos/notify.py: sends email", "src/knos/think.py: imports an AI provider's client"]


def test_the_rollback_covers_every_surface_with_commands_from_the_tree_and_cites_the_registries():
    page = read("docs/ROLLBACK.md")
    assert lc.documents(ROOT) == []
    for cmd in ("node scripts/governance.mjs guardian pause 604800", "node scripts/governance.mjs guardian pause 0",
                "bash scripts/deploy_v2.sh --propose --replace", "node scripts/governance.mjs upgrade execute",
                "npm deprecate knos-settle@", "python scripts/release.py publish", "python scripts/bump_version.py"):
        assert cmd in page, cmd
    for src in ("https://docs.pypi.org/project-management/yanking/", "https://docs.npmjs.com/cli/v11/commands/npm-deprecate",
                "https://docs.npmjs.com/policies/unpublish/"):
        assert f"({src})" in page
    # the facts it states are the tree's: the pause's limit, the relay's skip line, the 48-hour lock
    assert "PAUSE_MAX = 7 * 86_400" in read("scripts/governance.mjs") and "604800" in page and "at most 7 days" in page
    assert 'no KNOS_RELAY_KEY secret: skipped' in read(".github/workflows/worker.yml") and "KNOS_WORKER_KEY" in page
    assert '"time_lock": 172800' in read("web/upgrades.json") and "48\nhours on chain today" in page
    assert "immutable" not in page and "immutable" not in read("SECURITY.md")


def test_security_gives_a_private_path_and_a_public_one():
    text = read("SECURITY.md")
    assert "Report a vulnerability" in text and "private vulnerability reporting" in text and "open an issue" in text
    assert "docs/ROLLBACK.md" in text and "scripts/secret_scan.py --history" in text
