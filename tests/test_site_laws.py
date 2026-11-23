"""The site's part of the laws of IQ PLAN.md (22 Nov 2026), on one build of the site (scripts/build_site.sh):

  L01, L02, L05, L11, L20, L22, L28  tests/web/one_box.mjs in headless Chromium (skipped with no node or browser)
  L02  the front door's title, description and link preview are the one sentence (web/i18n/en.json "goal"); no mission
       line and no other contest anywhere on the built site
  L05  no font size in px in web/app.css, web/brand/tokens.css or any built page
  L14, L33  the price window and the one paid tier: a missing value is "not known yet" (or "not set yet"), never 0
  L16  every menu link of the built site is a page; each paper says "Reproduced" or "Not reproduced yet" from
       docs/data/reproduced.json, with a link to its authors' public page
  L20  privacy.html keeps its words outside the fold within 250
  L28  the star count is the one the GitHub API gave at build time, and none when it did not answer
  L31  every claim page names each backer's role and flags one who can affect the outcome; no price under a demand heading
  L32  web/money.js: a missing input is "not known", refundable money is held, not revenue, an internal transfer once
  L36, L38  the status page leads with the people who got a result; each question's counts and the changes list
  L47  no "Kardashev" anywhere in web/
  L48  scripts/site_weekly_log.py writes one dated entry per ISO week from git log; the status page shows the newest
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import _posix
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import site_pages  # noqa: E402
import site_product  # noqa: E402

SAID = json.loads((ROOT / "web" / "i18n" / "en.json").read_text(encoding="utf-8"))["strings"]["goal"]["text"]


@pytest.fixture(scope="module")
def site(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("laws") / "site"
    env = _posix.environ({**os.environ, "PYTHON": _posix.path(sys.executable), "PYTHONPATH": str(ROOT / "src"),
                          "KNOS_GITHUB_REPO_JSON": str(out.parent / "no-answer.json")})   # the API did not answer
    env.pop("KNOS_SPA_AT_ROOT", None)
    built = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(out), "e" * 40],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=600)
    assert built.returncode == 0, built.stdout + built.stderr
    return out


def pages(site: Path) -> list[Path]:
    return [p for p in site.rglob("*.html") if "near/vendor" not in p.as_posix()]


def test_one_box_and_the_front_doors_laws_in_a_browser(site: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "one_box.mjs"), str(site)], capture_output=True, text=True, encoding="utf-8", timeout=300)
    said = run.stdout.strip().splitlines()
    if run.returncode == 0 and said and said[-1].startswith("SKIP"):
        pytest.skip(said[-1][5:])
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert "all passed" in run.stdout


def test_one_sentence_on_every_surface_and_no_mission_or_contest_line(site: Path) -> None:
    assert len(SAID) < 125 and re.match(r"^Knos is an? .+ that helps .+", SAID), SAID
    door = (site / "index.html").read_text(encoding="utf-8")
    assert re.search(r"<title>(.*?)</title>", door).group(1) == SAID
    for attr in ('name="description"', 'property="og:description"'):
        assert re.search(rf'<meta {attr} content="([^"]*)"', door).group(1) == SAID, attr
    assert site_product.GOAL == SAID
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in site.rglob("*") if p.is_file() and p.suffix in (".html", ".json", ".js", ".txt"))
    for gone in ("billions of people", "days, not years", "From NEAR HACKATHON", "From Colosseum"):
        assert gone not in text, gone


def test_no_font_size_in_px_in_the_style_files_or_any_built_page(site: Path) -> None:
    for rel in ("web/app.css", "web/brand/tokens.css"):
        assert site_pages.PX_FONT.findall((ROOT / rel).read_text(encoding="utf-8")) == [], rel
    hits = {p.relative_to(site).as_posix(): site_pages.PX_FONT.findall(p.read_text(encoding="utf-8", errors="replace"))[:2] for p in pages(site)}
    assert {k: v for k, v in hits.items() if v} == {}
    assert site_pages.rem_fonts("p { font: 600 18px/24px x; font-size: 12px; margin: 4px }") == "p { font: 600 1.125rem/1.5rem x; font-size: 0.75rem; margin: 4px }"


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.menu, self.inside = [], 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "details" and "kmenu" in (a.get("class") or ""):
            self.inside += 1
        elif tag == "a" and self.inside and a.get("href"):
            self.menu.append(a["href"])

    def handle_endtag(self, tag):
        if tag == "details" and self.inside:
            self.inside -= 1


def test_every_menu_link_is_a_page_and_each_paper_says_whether_it_was_reproduced(site: Path) -> None:
    for page in (site / "index.html", site / "claims" / "index.html", site / "papers" / "index.html"):
        p = _Links()
        p.feed(page.read_text(encoding="utf-8"))
        assert p.menu, page
        for href in p.menu:
            target = (page.parent / href).resolve()
            target = target / "index.html" if href.endswith("/") or target.is_dir() else target
            assert target.is_file(), (page, href)
            assert 'http-equiv="refresh"' not in target.read_text(encoding="utf-8")[:600], (page, href)   # a page, not a redirect
    menu = _Links()
    menu.feed((site / "index.html").read_text(encoding="utf-8"))
    assert "papers/" in menu.menu                                                        # the Papers link opens papers/
    rep = json.loads((ROOT / "docs" / "data" / "reproduced.json").read_text(encoding="utf-8"))["claims"]
    papers = (site / "papers" / "index.html").read_text(encoding="utf-8")
    for c in site_product.claims():
        row = re.search(rf'<tr data-paper="{re.escape(c["name"])}">(.*?)</tr>', papers, re.S)
        assert row, c["name"]
        want = "Reproduced" if rep.get(c["name"], {}).get("reproduced") else "Not reproduced yet"
        assert f">{want}</td>" in row.group(1), c["name"]
        link = site_product.paper_link(c)
        assert link and f'<a href="{link}" data-authors>Ask the authors</a>' in row.group(1), c["name"]


def test_the_privacy_page_keeps_its_words_outside_the_fold_within_250(site: Path) -> None:
    page = (site / "privacy.html").read_text(encoding="utf-8")
    main = re.search(r"<main>(.*?)</main>", page, re.S).group(1)
    outside = re.sub(r"<details.*?</details>", " ", main, flags=re.S)
    words = re.findall(r"[A-Za-z0-9][\w'’.-]*", re.sub(r"<[^>]+>", " ", outside))
    assert len(words) <= 250, len(words)
    assert "<details" in main                                                            # the events are one press away


def test_the_star_count_is_the_apis_or_none(tmp_path: Path, monkeypatch) -> None:
    door = '<span id="k-stars" hidden></span>'
    monkeypatch.setenv("KNOS_GITHUB_REPO_JSON", str(tmp_path / "missing.json"))
    assert site_pages.stars() is None and site_pages.with_stars(door) == door             # omitted, never 0
    (tmp_path / "repo.json").write_text(json.dumps({"stargazers_count": 1234}), encoding="utf-8")
    monkeypatch.setenv("KNOS_GITHUB_REPO_JSON", str(tmp_path / "repo.json"))
    assert site_pages.stars() == 1234
    shown = site_pages.with_stars(door)
    assert 'data-stars="1234"' in shown and "1,234 stars" in shown
    (tmp_path / "zero.json").write_text(json.dumps({"stargazers_count": "many"}), encoding="utf-8")
    monkeypatch.setenv("KNOS_GITHUB_REPO_JSON", str(tmp_path / "zero.json"))
    assert site_pages.stars() is None


def test_the_built_front_door_names_the_licence_and_the_fork_page(site: Path) -> None:
    door = (site / "index.html").read_text(encoding="utf-8")
    assert "MIT licensed" in door and 'href="https://github.com/drexthealpha/Knos/fork"' in door
    assert '<span id="k-stars" hidden></span>' in door                                    # this build's API gave no answer


def test_the_price_window_and_the_paid_tier_never_show_a_missing_value_as_zero(site: Path) -> None:
    d = site_product.pricing()
    assert site_product.price_window(d) == {"low": None, "high": None, "fits": None} if d["window"]["cost_per_run"]["value"] is None else True
    page = (site / "pricing" / "index.html").read_text(encoding="utf-8")
    cost = re.search(r'<table id="cost">(.*?)</table>', page, re.S).group(1)
    for k in ("cost_per_run", "margin", "person_cost", "risk", "switching"):
        assert k in d["window"], k
    if d["window"]["cost_per_run"]["value"] is None:
        assert "<td>not known yet</td>" in cost and "<td>0</td>" not in cost
    assert ("not measured" in cost) == (d["window"]["person_cost"].get("url") is None)   # a person's cost carries its source, or says so
    plans = re.search(r'<table id="plans">(.*?)</table>', page, re.S).group(1)
    assert "Monthly plan, the default" in plans and "Yearly plan" in plans and "By region" in plans
    # the model: blank in, unknown out; filled in, a window and the free users one payer covers
    full = json.loads(json.dumps(d))
    for k, v in (("cost_per_run", 0.002), ("margin", 0.5), ("person_cost", 10.0), ("risk", 1.0), ("switching", 2.0)):
        full["window"][k]["value"] = v
    assert site_product.price_window(full) == {"low": 0.004, "high": 7.0, "fits": True}
    full["plans"]["monthly"]["price"] = 4.0
    got = site_product.covers(full)
    assert got is not None and abs(got - 4.0 / (0.002 * d["numbers"]["free_runs_per_day"]["value"] * 30)) < 1e-9
    real = site_product.covers(d)
    lo, hi = d["plans"]["covers"]["low"], d["plans"]["covers"]["high"]
    assert real is None or lo <= real <= hi, real                                         # D10.md:60, once measured


def test_every_claim_page_names_each_backers_role_and_flags_a_conflict(site: Path) -> None:
    for c in site_product.claims():
        page = (site / "claim" / c["name"] / "index.html").read_text(encoding="utf-8")
        assert "<th>Role</th>" in page and "<th>Can affect the outcome?</th>" in page, c["name"]
        assert 'textContent: "Backer"' in page and "Yes: Knos owns and checks this claim" in page and "Yes: submits the work for this claim" in page
        # no price under a demand heading: the demand row reads the test money behind the claim, never a market price
        demand = re.search(r"<tr><th>100 test dollars behind it within 7 days\?</th><td>(.*?)</td></tr>", page, re.S).group(1)
        assert not re.search(r"price|cents|¢", demand, re.I), demand
    assert "yes_cents" not in site_product.LIVE_JS.split("function demandText", 1)[1].split("}\n", 1)[0]


def test_money_lines_keep_unknown_held_and_internal_apart() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    probe = ("const m = require(process.argv[1]);"
             "const rows = m.moneyRows({ open: '2500000', paid: '7000000', refunded: null });"
             "const once = m.transfersOnce([{ tx: 'a', from: 'buyer.testnet', amount: '1000000' }, { tx: 'a', from: 'buyer.testnet', amount: '1000000' },"
             " { tx: 'b', from: 'live.knos.testnet', amount: '3000000' }], ['live.knos.testnet']);"
             "console.log(JSON.stringify({ rows: rows.map(([l, v]) => [l, m.cell(v)]), once }));")
    out = subprocess.run([node, "-e", probe, str(ROOT / "web" / "money.js")], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["rows"] == [["Held in open jobs, refundable", "2.50"], ["Paid out for passed work", "7.00"], ["Refunded", "not known"], ["Knos's revenue", "not known"]]
    assert got["once"] == {"revenue": 1, "internal": 3}                                   # the repeated transaction once; Knos's own apart


def test_the_status_page_leads_with_results_and_shows_the_answers_and_the_week(site: Path) -> None:
    page = (site / "status" / "index.html").read_text(encoding="utf-8")
    first = re.search(r'<table id="use"><tbody><tr><th>([^<]+)</th>', page).group(1)
    assert first == "First results, 7 days"                                             # short: the first screen holds 40 words (UX/U3.md:57)
    assert 'data-count="tools_opened"' not in page                                       # no raw open count
    for k, *_ in __import__("site_usage").LEAD:
        assert f'data-lead-full="{k}"' in page, k
    for k, _q in site_product.QUESTIONS:
        assert f'data-survey="{k}"' in page, k
    assert "Changed because of the answers" in page
    weekly = json.loads((ROOT / "docs" / "data" / "weekly.json").read_text(encoding="utf-8"))["weeks"]
    if weekly:
        assert f"Week {weekly[0]['week']}, {weekly[0]['from']} to {weekly[0]['to']}" in page


def test_the_weekly_log_is_one_dated_entry_per_iso_week() -> None:
    import site_weekly_log
    rows = [("2026-11-16", "a"), ("2026-11-22", "b"), ("2026-11-23", "c"), ("2026-01-01", "d")]
    got = site_weekly_log.weeks(rows)
    assert [w["week"] for w in got] == ["2026-W48", "2026-W47", "2026-W01"]
    assert got[1] == {"week": "2026-W47", "from": "2026-11-16", "to": "2026-11-22", "changes": 2,
                      "history": "https://github.com/drexthealpha/Knos/commits/main?since=2026-11-16&until=2026-11-22"}
    assert site_weekly_log.weeks(site_weekly_log.commits())                              # the repository's own history


def test_no_kardashev_anywhere_in_web() -> None:
    hits = [p.relative_to(ROOT).as_posix() for p in (ROOT / "web").rglob("*") if p.is_file() and p.suffix in (".html", ".js", ".json", ".css", ".txt")
            and "kardashev" in p.read_text(encoding="utf-8", errors="replace").lower()]
    assert hits == []
