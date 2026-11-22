"""Round 13 (v0328 research ROUND13-ITEMS.md, R13 SPEC.md and SPEC2.md): the front door's first tool, "Check a test file
against a limit", and the pages around it, on a build of the site (scripts/build_site.sh).

  A  tests/web/tool.mjs in headless Chromium at 360 by 800 with no stored state, the hosted server answered by a stand-in
     that keeps SPEC2.md's interface: the first screen's words (13 or fewer, L02; none of the PLAIN-WORDS rule), "Check my data" and a
     sentence that starts "Failed at row " or "Passed: all ", "Use my data" with file 2 of A8 and "Failed at row 37"
  C  the same script runs own-data runs until the free runs end and checks the pay screen's strings against
     docs/data/pricing.json; here, every number on the pricing page and the pay screen equals that file
  D  every PASS and STOP line of docs/NUMBERS.md names a file of LAWS/DISTRIBUTION; the status page's counts equal
     docs/data/usage.json
  B6 README.md and web/llms.txt carry the same "Use Knos where you already are" section
  F1 the company sentence on /prove/ reads its count from docs/data/scorecard_summary.json

KNOS_LIVE_TOOL=1 also runs tests/web/tool.mjs --live: the published front door against the live server. No node, no
`playwright` package or no browser: the browser parts are skipped, with the reason."""

from __future__ import annotations

import ast
import html
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
DATA = ROOT / "docs" / "data"
BROWSERS = "/opt/pw-browsers"
LAWS = Path(os.environ.get("KNOS_PRIVATE_DIR", ROOT.parent / ("knos-v1" + "-private"))) / "v0328" / "research" / "LAWS" / "DISTRIBUTION"   # outside the repository
PLAIN = ["tx", "hash", "testnet", "devnet", "mainnet", "proof", "prove", "verify", "contract", "token", "wallet", "agent", "job",
         "oracle", "LMSR", "NEAR", "Solana", "MCP", "API", "JSON"]
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


@pytest.fixture(scope="module")
def site(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("tool") / "site"
    env = _posix.environ({**os.environ, "PYTHON": _posix.path(sys.executable), "PYTHONPATH": str(ROOT / "src")})
    env.pop("KNOS_SPA_AT_ROOT", None)
    built = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(out), "d" * 40],
                           env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert built.returncode == 0, built.stdout + built.stderr
    return out


class _Seen(HTMLParser):
    """The text a reader sees on a page: no script, style or textarea, nothing inside a closed <details> but its summary,
    the header's closed menu left out (its words are a press away)."""
    def __init__(self) -> None:
        super().__init__()
        self.skip, self.closed, self.in_summary, self.parts = 0, 0, 0, []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "textarea", "head"):
            self.skip += 1
        elif tag == "details":
            self.closed += 0 if "open" in dict(attrs) else 1
        elif tag == "summary":
            self.in_summary += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "textarea", "head"):
            self.skip -= 1
        elif tag == "details" and self.closed:
            self.closed -= 1
        elif tag == "summary":
            self.in_summary -= 1

    def handle_data(self, data):
        if not self.skip and (not self.closed or self.in_summary):
            self.parts.append(data)


def seen(html: str, inside: str = "main") -> str:
    m = re.search(rf"<{inside}\b.*?</{inside}>", html, re.S)
    p = _Seen()
    p.feed(m.group(0) if m else html)
    return " ".join("".join(p.parts).split())


def plain_hits(text: str) -> list[str]:
    return [w for w in PLAIN if re.search(rf"\b{w}s?\b", text, re.I)]


def node_run(args: list[str], timeout: int) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "tool.mjs"), *args], env=env, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    said = run.stdout.strip().splitlines()
    if run.returncode == 0 and said and said[-1].startswith("SKIP"):
        pytest.skip(said[-1][5:])
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    return run.stdout


def test_a_stranger_runs_the_sample_then_their_own_list_then_pays_with_test_money(site: Path) -> None:
    out = node_run([str(site)], 170)
    for line in ("the first screen is 13 words or fewer", "none of the PLAIN-WORDS rule's words", 'starts with "Failed at row " or "Passed: all "',
                 'file 2 of A8 reads "Failed at row 37"', "pay screen's headline is the pack", "one more run after the test payment", "all passed"):
        assert line in out, line


# defined only when asked for (KNOS_LIVE_TOOL=1): CI runs with --no-skips, and this test needs the live server
if os.environ.get("KNOS_LIVE_TOOL") == "1":
  def test_the_published_front_door_counts_the_sample_on_the_live_server() -> None:
      out = node_run(["--live"], 170)
      assert 'starts with "Failed at row " or "Passed: all "' in out and "all passed" in out


def test_every_number_on_the_pricing_page_and_the_pay_screen_is_pricing_json(site: Path) -> None:
    doc = json.loads((DATA / "pricing.json").read_text(encoding="utf-8"))
    n = {k: v["value"] for k, v in doc["numbers"].items()}
    for v in doc["numbers"].values():
        assert v["unit"] and (v["source"] == "not from a law: a starting value to be tested" or re.search(r"LAWS|\.md", v["source"])), v
    page = (site / "pricing" / "index.html").read_text(encoding="utf-8")
    text = seen(page, "body")
    shown = {float(x.replace(",", "")) for x in NUMBER.findall(seen(page.replace("<details", "<details open")))}
    # L33: the one paid tier's target lines (docs/data/pricing.json "plans", each with its law line) are numbers of the file too
    plan = {float(x) for part in ("covers", "paying_share") for k, x in doc["plans"][part].items() if k in ("low", "high")}
    assert shown == {float(v) for v in n.values()} | plan, (shown, n, plan)          # every number on the page, the fold too
    for k, v in n.items():
        assert f'<span data-n="{k}">{v:,}</span>' in page, k
    assert f"{n['free_runs_per_day']} free a day" in text and f"{n['pack_runs']} more runs for ${n['pack_price']} in test money" in text
    assert "Today this is test money. Nothing is charged." in text and plain_hits(text) == [], plain_hits(text)
    assert not re.search(r"\b(token|credit|points?)s?\b", text, re.I)                # dollars only (UX-SOTA B5)
    door = (site / "index.html").read_text(encoding="utf-8")
    head = re.search(r'<h2 id="pay-h">(.*?)</h2>', door).group(1)
    assert re.sub(r"<[^>]+>", "", head) == f"{n['pack_runs']} more runs for ${n['pack_price']} in test money"
    fold = re.sub(r"<[^>]+>", "", re.search(r'<details class="how" id="how">(.*?)</details>', door, re.S).group(1))
    assert f"{n['free_runs_per_day']} free a day, then {n['pack_runs']} more runs for ${n['pack_price']} in test money" in fold
    for word in ("pay on proof", "escrow", "marketplace"):                             # C5
        assert word not in (text + door).lower(), word


def test_every_pass_and_stop_line_of_numbers_md_names_a_distribution_law_file() -> None:
    names = {p.name for p in LAWS.glob("*.md")} if LAWS.is_dir() else set(json.loads((DATA / "distribution_files.json").read_text(encoding="utf-8"))["files"])
    page = (ROOT / "docs" / "NUMBERS.md").read_text(encoding="utf-8")
    lines = re.findall(r"(?m)^- (PASS|STOP): (.+)$", page)
    assert [k for k, _ in lines] == ["PASS", "STOP"] * 3, lines                     # exactly three measures, each a PASS and a STOP
    for kind, line in lines:
        named = re.findall(r"\b([A-Z][A-Z0-9-]*\d*\.md)\b", line)
        assert named and all(n in names for n in named), (kind, line, named)
        if "not given in the law" not in line:
            assert re.search(r'"[^"]+"', line), line                                 # the rule, quoted
    heads = re.findall(r"(?m)^### (.+)$", page.split("## Three measures", 1)[1].split("\n## ", 1)[0])
    assert heads == ["Day-7 return", "Active days", "Paying share"], heads


def test_the_status_page_shows_every_count_of_usage_json(site: Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import site_usage
    finally:
        sys.path.pop(0)
    u = json.loads((DATA / "usage.json").read_text(encoding="utf-8"))
    assert site_usage.check(u) == []
    page = (site / "status" / "index.html").read_text(encoding="utf-8")
    for key, label in site_usage.COUNTS:
        m = re.search(rf'<tr><th>{re.escape(label)}</th><td class="n" data-count="{key}">([\d,]+)</td></tr>', page.replace("&#x27;", "'"))
        if key == "tools_opened":                                                   # L36: no raw open count
            assert not m and 'data-count="tools_opened"' not in page, key
            continue
        assert m and int(m.group(1).replace(",", "")) == u["totals"][key], key
    # L36: the first line is the people who reached a first result in the last 7 days ("not known yet" until measured)
    first = (u.get("lead") or {}).get("first_result_7d")
    m = re.search(r'<table id="use"><tbody><tr><th>People who got a first result, last 7 days</th><td class="n" data-lead="first_result_7d">([^<]+)</td>', page)
    assert m and m.group(1) == ("not known yet" if first is None else f"{first:,g}"), m
    for key, label in site_usage.MEASURES:
        m = re.search(rf'data-measure="{key}">([^<]+)</td>', page)
        want = "not enough browsers yet" if u["measures"][key] is None else f"{u['measures'][key]:,}"
        assert m and m.group(1) == want, key
    text = seen(page, "body")
    assert plain_hits(text) == [], plain_hits(text)
    assert (site / "data" / "usage.json").read_bytes() == (DATA / "usage.json").read_bytes()


def test_readme_and_llms_txt_carry_one_section_that_adds_the_connector() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import site_product
    finally:
        sys.path.pop(0)
    section = site_product.where_you_are()
    for rel in ("README.md", "web/llms.txt"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert section in text and text.count("## Use Knos where you already are") == 1, rel
    assert site_product.sample().split("\n")[0] == "cycle,capacity_ah"
    assert "claude mcp add --transport http knos https://knos.onrender.com/mcp" in section
    assert f"`{site_product.sample_result()}`" in section and site_product.sample_result().startswith("Failed at row ")
    assert "count-distinct" not in section and "different items" not in section            # the list counter is no tool


def test_the_company_count_on_a_public_page_is_the_scorecard_summary(site: Path) -> None:
    summary = json.loads((DATA / "scorecard_summary.json").read_text(encoding="utf-8"))
    prove = (site / "prove" / "index.html").read_text(encoding="utf-8")
    assert f"{summary['rows']:,} companies are on a first list. No outside company has bought from Knos." in prove
    pages = [p for p in site.rglob("*.html") if "near/vendor" not in p.as_posix()]
    for p in pages:
        t = p.read_text(encoding="utf-8", errors="replace")
        assert "38 of 12,010" not in t and not re.search(r"census", t, re.I), p   # F1
    for m in re.finditer(r"([\d,]+) companies", "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in pages)):
        assert int(m.group(1).replace(",", "")) == summary["rows"], m.group(0)


def test_the_front_door_is_one_box_whose_example_is_the_tools_sample(site: Path) -> None:
    """L01 (IQ PLAN.md): one box, "Ask anything about research"; a pasted table runs the limit check, and the tool's
    sample is the box's one example (kept in a template, checked when the box is empty)."""
    door = (site / "index.html").read_text(encoding="utf-8")
    assert door.count("<h1") == 1 and "<h1><label for=\"list\" id=\"k-name\">Ask anything about research</label></h1>" in door
    assert 'id="ask-box"' not in door and 'id="paper"' not in door                    # one box: the question box is the tool's box
    assert door.index('id="tool"') < door.index('id="ask-out"') < door.index('id="k-live"')
    assert '<p class="kgoal">' not in door and "The goal: " not in door                # L02: no mission line, the menu too
    assert '<h2 id="t-title">Check a test file against a limit</h2>' in door
    who = re.search(r'<p class="who" id="who">([^<]+)</p>', door).group(1)
    assert who == "For anyone who tests batteries, motors, parts or machines."
    sample = (ROOT / "near" / "agents" / "job" / "data" / "limit" / "sample.csv").read_text(encoding="utf-8").replace("\r\n", "\n").strip("\n")
    box = re.search(r'<textarea id="list"[^>]*>(.*?)</textarea>', door, re.S).group(1)
    assert box == ""                                                                  # the box starts empty
    kept = re.search(r'<template id="k-sample" data-sample>(.*?)</template>', door, re.S).group(1)
    assert html.unescape(kept) == sample                                              # the job's sample, written in at build time
    conf = ast.literal_eval(re.search(r"CONF = (\{.*\})", (ROOT / "apps" / "wanted" / "knos_wanted" / "runner_conf.py").read_text(encoding="utf-8"), re.S).group(1))
    assert f'<label for="list" id="list-label" hidden>{conf["sample_label"]}</label>' in door   # the same label as the server's tool page
    # F1B: the rule line says the sample's column in plain words; the file's name for it is the form's and the fold's
    assert '<span id="colname">charge held</span>' in door and '<input type="hidden" name="column" value="capacity_ah" dir="auto">' in door
    assert re.search(r'<details class="how".*The sample\'s column <bdi>capacity_ah</bdi> holds', door, re.S)
    assert 'value="1.4"' in door
    for gone in ("count-distinct", "different items", "Exact count"):                    # the list counter is shown to nobody here
        assert gone not in door, gone
