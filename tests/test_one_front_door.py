"""One front door: the Pages root, as the build writes it, is the demand check alone (1 h1, the box, the chips, the
card's place, the four steps, the three clicks); the rest of the site is app.html and the check of a pull request is
check/. The app's home holds none of the money or company tools, which are its Paid on proof page (/paid). Every
description of the package is a sentence of docs/facts.json."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
MISSION = "See who wants your product, and where, before you build it"
MOVED = ("passkey", "SAML", "SSO", "Squads", "Xero", "QuickBooks", "devnet SOL")


def raw(html: str) -> str:
    return re.sub(r"<script\b.*?</script>", " ", html, flags=re.S | re.I)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    import _posix
    out = tmp_path_factory.mktemp("site")
    env = _posix.environ(dict(os.environ))
    env["KNOS_SPA_AT_ROOT"] = "0"                          # the build Pages publishes
    r = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(out), "ab" * 20],
                       capture_output=True, text=True, env=env, check=False)
    assert r.returncode == 0, r.stderr[-2000:]
    return out


def test_the_root_is_the_demand_check_alone(built):
    page = raw((built / "index.html").read_text(encoding="utf-8"))
    h1 = re.findall(r"<h1\b[^>]*>(.*?)</h1>", page, re.S)
    assert [re.sub(r"<[^>]+>", "", h).strip() for h in h1] == [MISSION]
    assert 'id="k-q"' in page and len(re.findall(r'class="k-chip"', page)) == 6 and "data-more-chips" in page and 'id="k-card"' in page
    steps = re.search(r'<ol class="k-step-list">(.*?)</ol>', page, re.S).group(1)
    assert len(re.findall(r"<li\b", steps)) == 4 and "How do I see it work?" in page
    for gone in ('id="view-check"', 'id="front-door"', "Check an AI agent's pull request", 'id="view-records"', 'id="view-fund"', 'id="hero-fact"'):
        assert gone not in page, gone
    assert 'href="./check/#sample" id="steps-check"' in page                     # Paid on proof's link goes to the check's own page


def test_one_app_app_html_sends_old_links_on_and_the_check_is_its_own_page(built):
    app = (built / "app.html").read_text(encoding="utf-8")       # one app: knos.onrender.com/app/; no second copy is published
    assert 'url=https://knos.onrender.com/app/' in app and 'location.replace("https://knos.onrender.com/app/" + location.hash)' in app
    assert 'id="view-check"' not in app and (built / "check" / "index.html").is_file() and not (built / "app-moved.html").exists()
    head = (built / "index.html").read_text(encoding="utf-8").split("</head>")[0]
    assert 'location.replace("check/"' in head and 'location.replace("app.html" + h)' in head and 'addEventListener("hashchange", go)' in head


def test_the_apps_home_holds_no_money_or_company_tools_and_paid_holds_them():
    sys.path[:0] = [str(ROOT / "apps" / "wanted"), str(ROOT / "src")]
    from knos_wanted import server
    page = (ROOT / "apps" / "wanted" / "knos_wanted" / "static" / "index.html").read_text(encoding="utf-8")
    home = raw(server.home_page(page))
    assert {w: len(re.findall(rf"\b{re.escape(w)}\b", home, re.I)) for w in MOVED} == {w: 0 for w in MOVED}
    full = raw(page)
    assert all(re.search(rf"\b{re.escape(w)}\b", full, re.I) for w in MOVED)               # /paid serves them whole
    ids = set(re.findall(r'\bid="([^"]+)"', "".join(re.findall(r"<!-- paid:start -->.*?<!-- paid:end -->", page, re.S))))
    assert ids and all(f'id="{i}"' in home for i in ids)                                   # every id the scripts bind to


def test_every_description_is_a_sentence_of_facts_json():
    facts = json.loads((ROOT / "docs" / "facts.json").read_text(encoding="utf-8"))
    said = {facts["sentence"], facts["registry_sentence"]}
    pyproject = re.search(r'(?m)^description = "(.*)"$', (ROOT / "pyproject.toml").read_text(encoding="utf-8")).group(1)
    npm = json.loads((ROOT / "sdk" / "settle" / "package.json").read_text(encoding="utf-8"))["description"]
    server = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))["description"]
    lead = re.search(r"\*\*(.+?)\*\*", (ROOT / "README.md").read_text(encoding="utf-8").split("</h1>", 1)[1]).group(1)
    assert {pyproject, npm, server, lead} <= said, {pyproject, npm, server, lead} - said
    tens = (ROOT / "README.md").read_text(encoding="utf-8").split("## Try it in ten seconds", 1)[1].split("\n## ", 1)[0]
    assert tens.strip().startswith("Open [the demand check](https://drexthealpha.github.io/Knos/)")
