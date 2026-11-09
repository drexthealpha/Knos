"""No page of the site scrolls sideways at 320, 360, 390, 768 or 1280 px: tests/web/overflow.mjs, run on a build of web/.
The budget of the first screen and of what moves: tests/web/motion.mjs, and the words of the shell counted from the file.

The measuring is in the node script (headless Chromium through the `playwright` package, as tests/web/site.mjs). This
file builds the site as the Pages build does and runs it. No node, no package or no browser: skipped, with the reason."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import _posix
import pytest

ROOT = Path(__file__).resolve().parents[1]
BROWSERS = "/opt/pw-browsers"          # where this project's machines keep Chromium; anywhere else playwright's default holds


ONE = "Knos carries research across the valley of death."
WORD = re.compile(r"[A-Za-z0-9][\w'’%.,/-]*")


# the Paid on proof step's one sentence on signed checks, kept word for word as written: the one statement over 12 words
SIGNING = "GitHub signs which checks ran, and a Solana program checks that signature itself before it pays."
OUTCOME = "Check an AI agent's pull request before it is paid."       # the check of agent work, one use of Knos: the h1
WHO = "One use of Knos: pay for code only when its checks pass."   # who it is for, under the h1
SHORT = "See who wants it, then test each step."      # Knos in a few words, under it (the one sentence is folded under "What is here")


def _words(html: str) -> list[str]:
    return WORD.findall(re.sub(r"<[^>]+>", " ", html))


def _run(tmp_path: Path, script: str, says: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    site = tmp_path / "site"
    env = _posix.environ({**os.environ, "PYTHON": _posix.path(sys.executable), "PYTHONPATH": str(ROOT / "src")})
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    built = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(site), "c" * 40],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert built.returncode == 0, built.stdout + built.stderr
    run = subprocess.run([node, str(ROOT / "tests" / "web" / script), str(site)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=600)
    said = run.stdout.strip().splitlines()
    if run.returncode == 0 and said and said[-1].startswith("SKIP"):
        # a script may hold what needs no browser (motion.mjs's weights) before it looks for one: those still count
        assert all(line.startswith("ok") for line in said[:-1]) and "FAIL" not in run.stderr, run.stdout + run.stderr
        pytest.skip(said[-1][5:])
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert says in run.stdout


def test_no_page_scrolls_sideways(tmp_path: Path) -> None:
    _run(tmp_path, "overflow.mjs", "none scrolls sideways")


def test_the_figure_on_the_first_screen_is_the_measured_one() -> None:
    """The second number, under the first screen (#second-fact). 17.8% is the Agent PR Index's count of repositories (docs/reference/BENCH.md): the first pull request by an agent whose
    description said tests or CI pass had a failed check in 147 of 826. The line says no more than that."""
    bench = (ROOT / "docs" / "reference" / "BENCH.md").read_text(encoding="utf-8")
    found = re.search(r"in (\d[\d,]*) repositories, the first pull request by an AI coding agent whose description said tests or CI pass had \*\*a failed check of any kind in (\d+) \((\d+\.\d)%\)", bench)
    assert found, "docs/reference/BENCH.md no longer states the figure in this form"
    total, failed, share = int(found[1].replace(",", "")), int(found[2]), found[3]
    assert f"{100 * failed / total:.1f}" == share
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    line = re.sub(r"<[^>]+>", "", re.search(r'<p class="fine" id="second-fact"[^>]*>(.*?)</p>', page, re.S)[1])
    assert line == f"{share}% of agents' first “tests pass” pull requests had a failed check: {failed} of {total}."
    assert 'href="https://github.com/drexthealpha/Knos/blob/main/docs/reference/BENCH.md">' + share + "%</a>" in page


def test_a_statement_of_the_shell_is_twelve_words_at_most() -> None:
    """Every heading, label, button and sentence the shell (web/index.html) shows without a press. What is longer is
    folded under a <details>; a table's cell is data, a block of code is the thing itself, and neither is counted."""
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    body = re.sub(r"<(noscript|details|script|pre|table)\b.*?</\1>", "", page[page.index("<body"):], flags=re.S)
    body = re.sub(r'<p class="k-vision"[^>]*>.*?</p>', "", body, flags=re.S)        # the two vision lines are the founder's fixed text
    long = []
    for tag in ("h1", "h2", "h3", "h4", "label", "button", "p", "li", "dd", "dt", "figcaption", "span"):
        for found in re.finditer(rf"<{tag}\b[^>]*>(.*?)</{tag}>", body, re.S):
            if tag == "li" and re.search(r"<(p|h3|form|ol|button)\b", found[1]):
                continue                                                              # a step that holds its own parts, counted as those
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", found[1])).strip()
            long += [(tag, s) for s in re.split(r"(?<=[.?!:])\s+", text) if len(_words(s)) > 12 and s != SIGNING]
    assert not long, long
    summaries = [re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<summary\b[^>]*>(.*?)</summary>", page, re.S)]
    assert len(summaries) > 20 and all(len(_words(m)) <= 12 for m in summaries)
    for head in re.findall(r"<h[1-4]\b[^>]*>(.*?)</h[1-4]>", page, re.S):
        assert len(_words(head)) <= 12, head
