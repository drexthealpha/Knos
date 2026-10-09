"""No page of the site scrolls sideways at 320, 360, 390, 768 or 1280 px: tests/web/overflow.mjs, run on a build of web/.
The budget of the first screen and of what moves: tests/web/motion.mjs, and the words of the shell counted from the file.

The measuring is in the node script (headless Chromium through the `playwright` package, as tests/web/site.mjs). This
file builds the site as the Pages build does and runs it. No node, no package or no browser: skipped, with the reason."""

from __future__ import annotations

import json
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


ONE = "The neutral meter for AI agent work: neither side keeps the count."
WORD = re.compile(r"[A-Za-z0-9][\w'’%.,/-]*")


OUTCOME = "Both sides close invoices on evidence both verify."       # the customer outcome, under the sentence


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


def test_the_budget_of_words_weight_and_motion_holds(tmp_path: Path) -> None:
    """tests/web/motion.mjs: 40 words on the first screen, the weight of the stylesheet and of what moves, nothing
    running for a reader who asked for no movement, the focus drawn, the contrast of the text, no sideways scroll."""
    _run(tmp_path, "motion.mjs", "motion: every check held")


def test_the_first_screen_says_forty_words_at_most() -> None:
    """Read from the file, with no browser: the bar as a first visitor sees it (its own links, More, Menu), the sentence,
    the figure's line and the one control (the front door: a box, its button, a sample). The demo's mount is empty in
    the file; its words are its module's."""
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    bar = page[page.index('<header class="bar">'):page.index("</header>")]
    bar = re.sub(r'<div class="more-list".*?</div>', "", bar, flags=re.S)                 # what More holds is one press away
    # the first screen ends where "How it works" begins (since 0.3.22 it stands under the hero, before the demo's mount)
    hero = page[page.index('<div class="hero'):min(page.index('<section id="demo"'), page.index('<h2 id="how-it-works">'))]
    assert f'<h1 id="check">{ONE}</h1>' in hero
    assert len(re.findall(r"<a\b", bar[bar.index("<nav"):bar.index('<div class="more"')])) == 6      # six links in the bar: Check, Demo, Console, Leaderboard, Pricing, Docs
    fact = re.search(r'<p class="hero-fact"[^>]*>(.*?)</p>', hero, re.S)
    assert fact and len(_words(fact[1])) <= 12 and re.sub(r"<[^>]+>", "", fact[1]) == "241 merged agent “tests pass” pull requests: 9 failed tests or builds."
    merged = json.loads((ROOT / "docs" / "backtest.json").read_text(encoding="utf-8"))["reviewed"]["overall"]
    assert (merged["prs"], merged["test_or_build_check_failed"]["prs"]) == (241, 9)
    door = hero[hero.index('<form id="front-door"'):hero.index("</form>")]
    assert re.findall(r'data-fd="(\w+)"', door) == ["run", "sample"] and '<textarea id="fd-in"' in door and 'id="mark3d"' in hero
    # two buttons: the one primary action, and the sample beside it (quiet)
    assert [re.sub(r"<[^>]+>", "", b).strip() for b in re.findall(r"<button\b[^>]*>.*?</button>", hero)] == ["Check", "Try a sample"]
    assert 'class="k-btn" data-fd="run"' in hero and 'class="k-btn quiet" data-fd="sample"' in hero
    assert 'id="hero-board"' in hero and hero.index('id="hero-board"') > hero.index("</form>")      # the leaderboard strip, directly under the box
    assert '<section id="demo" class="mount" aria-label="Demo" hidden></section>' in page.split('id="view-check"')[1].split("</section>")[0] + "</section>"
    # the 40 words are counted as tests/web/front_door.mjs counts them in a browser: prose (headings, sentences, links),
    # the bar with them. A control (a button) and a figure (.k-num) are the thing itself, not a statement about it. Since
    # 0.3.19 the customer outcome is one of the lines, inside the same 40.
    assert f'<p class="hero-outcome" id="hero-outcome">{OUTCOME}</p>' in hero and hero.index(f">{ONE}</h1>") < hero.index(OUTCOME) < hero.index('id="hero-fact"')

    def prose(html: str) -> list[str]:
        html = re.sub(r"<button\b[^>]*>.*?</button>", " ", html, flags=re.S)
        return _words(re.sub(r'<(\w+)\b[^>]*class="[^"]*\bk-num\b[^"]*"[^>]*>.*?</\1>', " ", html, flags=re.S))
    words = prose(bar) + prose(hero)
    assert 20 <= len(words) <= 40, (len(words), words)
    assert len(_words(bar) + _words(hero)) <= 48                              # and with every control's label and figure: no more than these


def test_the_figure_on_the_first_screen_is_the_measured_one() -> None:
    """The second number, under the first screen (#second-fact). 17.8% is the Agent PR Index's count of repositories (docs/BENCH.md): the first pull request by an agent whose
    description said tests or CI pass had a failed check in 147 of 826. The line says no more than that."""
    bench = (ROOT / "docs" / "BENCH.md").read_text(encoding="utf-8")
    found = re.search(r"in (\d[\d,]*) repositories, the first pull request by an AI coding agent whose description said tests or CI pass had \*\*a failed check of any kind in (\d+) \((\d+\.\d)%\)", bench)
    assert found, "docs/BENCH.md no longer states the figure in this form"
    total, failed, share = int(found[1].replace(",", "")), int(found[2]), found[3]
    assert f"{100 * failed / total:.1f}" == share
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    line = re.sub(r"<[^>]+>", "", re.search(r'<p class="fine" id="second-fact"[^>]*>(.*?)</p>', page, re.S)[1])
    assert line == f"{share}% of agents' first “tests pass” pull requests had a failed check."
    assert 'href="https://github.com/drexthealpha/Knos/blob/main/docs/BENCH.md">' + share + "%</a>" in page


def test_a_statement_of_the_shell_is_twelve_words_at_most() -> None:
    """Every heading, label, button and sentence the shell (web/index.html) shows without a press. What is longer is
    folded under a <details>; a table's cell is data, a block of code is the thing itself, and neither is counted."""
    page = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    body = re.sub(r"<(noscript|details|script|pre|table)\b.*?</\1>", "", page[page.index("<body"):], flags=re.S)
    long = []
    for tag in ("h1", "h2", "h3", "h4", "label", "button", "p", "li", "dd", "dt", "figcaption", "span"):
        for found in re.finditer(rf"<{tag}\b[^>]*>(.*?)</{tag}>", body, re.S):
            if tag == "li" and re.search(r"<(p|h3|form|ol|button)\b", found[1]):
                continue                                                              # a step that holds its own parts, counted as those
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", found[1])).strip()
            long += [(tag, s) for s in re.split(r"(?<=[.?!:])\s+", text) if len(_words(s)) > 12]
    assert not long, long
    summaries = [re.sub(r"<[^>]+>", "", m) for m in re.findall(r"<summary\b[^>]*>(.*?)</summary>", page, re.S)]
    assert len(summaries) > 20 and all(len(_words(m)) <= 12 for m in summaries)
    for head in re.findall(r"<h[1-4]\b[^>]*>(.*?)</h[1-4]>", page, re.S):
        assert len(_words(head)) <= 12, head
