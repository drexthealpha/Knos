"""What a search engine and a link preview read of the site, held to the files and to a build of them.

    the first screen   web/index.html: a title of 60 characters at most, written for a person; a description of 155 at
                       most that begins with the one sentence (scripts/public_face.py); the author; the share tags say the
                       same; a SoftwareApplication in JSON-LD, with no rating and no review (none exists)
    the questions      web/faq.html, its FAQPage and README.md's "Questions" give the same questions and the same words;
                       each answer is two sentences of twelve words at most, at grade 8 or lower (tests/test_readme_plain.py)
    pages to index     web/faq.html and web/check/index.html: their own title, description and canonical address, one h1,
                       3 to 5 links inside the site, 2 or 3 to GitHub's or Solana's documentation, nothing loaded from
                       another host, and "Last updated" with the date scripts/build_site.sh stamps
    sitemap, llms.txt  every address of web/sitemap.xml is a page the build has, with the build's date; web/llms.txt
                       has the shape of https://llmstxt.org/ (an H1, a one-line summary, lists of links, "Optional" last)
                       and every link in it leads to a file
The pages in a browser (words, width, requests): tests/web/seo.mjs, run here on a build; skipped with no node or browser.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import _posix
import pytest
import test_readme_plain as plain

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
SITE = "https://drexthealpha.github.io/Knos/"
PAGES = {"faq.html": SITE + "faq.html", "check/index.html": SITE + "check/"}
TRUSTED = {"docs.github.com", "solana.com"}           # documentation a reader can trust, outside the project
WORD = re.compile(r"[A-Za-z0-9][\w'%.,/-]*")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BROWSERS = "/opt/pw-browsers"


class Page(HTMLParser):
    """The parts of a page this file reads: the head's tags, the JSON-LD blocks, the links, the loads, the h1s, the folds."""

    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.title, self.h1 = "", 0
        self.meta: dict[str, list[str]] = {}
        self.links: list[tuple[str, str]] = []
        self.hrefs: list[str] = []
        self.loads: list[str] = []
        self.ld: list[dict] = []
        self.folds: list[list[str]] = []
        self._in: list[str] = []
        self._buf = ""
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and ("name" in a or "property" in a):
            self.meta.setdefault(a.get("name") or a.get("property"), []).append(a.get("content", ""))
        if tag == "link":
            self.links.append((a.get("rel", ""), a.get("href", "")))
        if tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])
        if tag in ("script", "img", "source", "video", "audio", "iframe") and a.get("src"):
            self.loads.append(a["src"])
        # a preconnect to the site's own host downloads nothing (scripts/sync_brand.py PRECONNECT: the fonts' CORS connection)
        if tag == "link" and a.get("rel") not in ("canonical", "alternate") and not (a.get("rel") == "preconnect" and a.get("href") == "https://drexthealpha.github.io"):
            self.loads.append(a.get("href", ""))
        self.h1 += tag == "h1"
        if tag == "details":
            self.folds.append(["", ""])
        if tag in ("title", "summary", "p") or (tag == "script" and a.get("type") == "application/ld+json"):
            self._in.append("ld" if tag == "script" else tag)
            self._buf = ""

    def handle_data(self, data):
        if self._in:
            self._buf += data

    def handle_endtag(self, tag):
        want = "ld" if tag == "script" else tag
        if self._in and self._in[-1] == want:
            self._in.pop()
            text = re.sub(r"\s+", " ", self._buf).strip()
            if want == "title":
                self.title = text
            elif want == "ld":
                self.ld.append(json.loads(self._buf))
            elif want == "summary" and self.folds:
                self.folds[-1][0] = text
            elif want == "p" and self.folds and self.folds[-1][1] == "" and self.folds[-1][0]:
                self.folds[-1][1] = text


def page(rel: str, root: Path = WEB) -> Page:
    return Page((root / rel).read_text(encoding="utf-8"))


def sentence() -> str:
    return json.loads((ROOT / "docs" / "facts.json").read_text(encoding="utf-8"))["sentence"]


def readme_questions() -> list[tuple[str, str]]:
    """README.md's "Questions": (question, answer) with the links' targets taken out."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    part = text.split("\n## Questions\n", 1)[1].split("\n## ", 1)[0]
    pairs = re.findall(r"(?m)^### (.+)\n\n(.+)$", part)
    return [(q, re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", a)) for q, a in pairs]


def faq_ld() -> list[tuple[str, str]]:
    (ld,) = [d for d in page("faq.html").ld if d.get("@type") == "FAQPage"]
    return [(q["name"], q["acceptedAnswer"]["text"]) for q in ld["mainEntity"]]


# ---- the first screen ---------------------------------------------------------------------------------------------------

def test_the_first_screen_is_named_for_a_person_and_described_by_the_sentence():
    p = page("index.html")
    said = sentence()
    assert len(p.title) <= 60 and p.title.startswith("Knos. "), p.title
    (description,) = p.meta["description"]
    assert len(description) <= 155 and description.startswith(said + " ") and len(description) > len(said) + 20, description
    assert p.meta["author"] == ["drexthealpha"]
    assert p.meta["og:title"] == p.meta["twitter:title"] == [p.title]
    assert p.meta["og:description"] == p.meta["twitter:description"] == [description]
    assert [h for r, h in p.links if r == "canonical"] == [SITE] == p.meta["og:url"]
    assert p.meta["og:image"] == [SITE + "brand/card.png"] and p.meta["og:image:type"] == ["image/png"]
    # the title is the line the first screen already says under the sentence, not a new claim
    assert p.title.removeprefix("Knos. ") in (WEB / "index.html").read_text(encoding="utf-8").split("</head>", 1)[1]


def test_the_first_screen_says_what_it_is_in_json_ld_and_claims_no_rating():
    (app,) = page("index.html").ld
    assert app["@context"] == "https://schema.org" and app["@type"] == "SoftwareApplication"
    assert app["name"] == "Knos" and app["description"] == sentence() and app["url"] == SITE
    assert app["applicationCategory"] == "DeveloperApplication" and app["operatingSystem"]
    assert "offers" not in app          # no price: checking is free, but paying, the meter and Control are not
    assert app["license"] == "https://opensource.org/licenses/MIT" and (ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT")
    for rel in ("index.html", *PAGES):
        text = json.dumps(page(rel).ld)
        assert not re.search(r"aggregateRating|\"review|ratingValue", text), rel          # no rating or review exists


# ---- the questions ------------------------------------------------------------------------------------------------------

def test_the_questions_say_the_same_words_on_the_page_in_its_json_ld_and_in_the_readme():
    shown = [(q, a) for q, a in page("faq.html").folds]
    assert 6 <= len(shown) <= 8
    assert shown == faq_ld() == readme_questions()
    for q, a in shown:
        said = [s for s in re.split(r"(?<=[.!?])\s+", a) if s]
        assert len(said) <= 2 and all(len(WORD.findall(s)) <= 12 for s in said), (q, a)
        assert not re.search(r"\b(wallets?|hash(es|ed)?|pin(s|ned)?|token accounts?)\b", a, re.I), a     # the site's record words
    level, _per = plain.grade(" ".join(a for _q, a in shown))
    assert level <= 8, f"the answers read at grade {level:.1f}"


def test_the_answers_agree_with_the_tree():
    answers = dict(faq_ld())
    from knos.settle.v2 import pay
    assert "0.30%, at least 0.05 test USDC" in answers["What does Knos cost?"]
    assert pay.FEE_BPS == 30 and pay.order_fee(100_000_000) == 300_000 and pay.order_fee(5_000_000) == 50_000 == pay.fee_of(5_000_000)
    assert "demand check" in (ROOT / "docs" / "PRICING.md").read_text(encoding="utf-8")
    assert answers["What is Knos?"] == "Knos takes research from a paper to a product people want. It pays each step only on verified proof."
    assert "valley of death" in sentence() and "paid only on proof" in sentence()             # the one sentence, as two short answers
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "The money waits in a program on [Solana](docs/WORDS.md#solana), not with Knos." in readme
    assert "Today one person can still change that program, after a public wait" in readme
    assert "test USDC" in answers["Does Knos use real money?"] and "devnet" in answers["Does Knos use real money?"]
    assert "LIMIT_S = 10" in (WEB / "check.js").read_text(encoding="utf-8")                  # "within ten seconds"


# ---- the pages a search engine indexes ----------------------------------------------------------------------------------

@pytest.mark.parametrize("rel", sorted(PAGES))
def test_each_page_to_index_has_its_own_address_heading_links_and_date(rel):
    p, text = page(rel), (WEB / rel).read_text(encoding="utf-8")
    assert len(p.title) <= 60 and p.title.startswith("Knos. ") and p.title != page("index.html").title, p.title
    (description,) = p.meta["description"]
    assert 50 <= len(description) <= 155, description
    assert [h for r, h in p.links if r == "canonical"] == [PAGES[rel]] == p.meta["og:url"]
    assert p.h1 == 1 and p.meta["author"] == ["drexthealpha"] and "robots" not in p.meta          # nothing keeps a crawler out
    # the page's own links: the bar (web/brand/bar.html) is the same on every page of Knos, and the home link apart
    own = page(rel).hrefs if "<!-- k-bar -->" not in text else Page(re.sub(r"<!-- k-bar -->.*?<!-- /k-bar -->", "", text, flags=re.S)).hrefs
    inside = {urljoin(PAGES[rel], h) for h in own if urljoin(PAGES[rel], h).startswith(SITE)} - {SITE}
    assert 3 <= len(inside) <= 5, sorted(inside)
    for url in inside:                                                                      # each leads to a file of the site
        assert (WEB / built_file(urlparse(url)._replace(fragment="").geturl())).is_file(), url
    trusted = {h for h in p.hrefs if urlparse(h).hostname in TRUSTED}
    assert 2 <= len(trusted) <= 3, trusted
    assert [u for u in p.loads if re.match(r"(https?:)?//", u)] == []                         # nothing is loaded from another host
    assert re.search(r'<p class="fine" id="updated">Last updated <time datetime="KNOS_BUILD_DATE">KNOS_BUILD_DATE</time></p>', text)


def test_the_check_page_is_the_apps_own_check():
    text = (WEB / "check" / "index.html").read_text(encoding="utf-8")
    assert 'import { renderCheck } from "../check.js";' in text and '<div id="check-one"></div>' in text
    refs = re.findall(r'(?:href|src)="(?!https://|#)([^"]+)"', text)                       # one folder down: every file from "../"
    assert refs and all(ref.startswith("../") for ref in refs), refs
    for ref in refs:
        assert (WEB / built_file(urljoin(SITE + "check/", ref.split("#")[0]))).is_file(), ref


# ---- sitemap and llms.txt -----------------------------------------------------------------------------------------------

NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def sitemap(root: Path = WEB) -> list[tuple[str, str]]:
    tree = ET.parse(root / "sitemap.xml")
    return [(u.findtext("s:loc", "", NS), u.findtext("s:lastmod", "", NS)) for u in tree.getroot().findall("s:url", NS)]


def built_file(url: str) -> str:
    assert url.startswith(SITE), url                       # a sitemap at /Knos/ may list only addresses under /Knos/
    path = url.removeprefix(SITE)
    return path + "index.html" if path == "" or path.endswith("/") else path


def test_the_sitemap_lists_every_public_page_and_names_each_ones_source_for_its_date():
    urls = sitemap()
    assert [u for u, _d in urls][:4] == [SITE, SITE + "check/", SITE + "faq.html", SITE + "privacy.html"] and len(urls) >= 18
    for want in ("proof/", "forecasts/", "status/", "calls/", "try/", "how-we-test.html", "pricing.html", "docs/"):
        assert SITE + want in [u for u, _d in urls], want
    assert sum(u.startswith(SITE + "results/") for u, _d in urls) == 6
    for url, d in urls:
        src = d.removeprefix("git:")
        assert d.startswith("git:web/") and (ROOT / src).is_file(), (url, d)          # scripts/sitemap_dates.py dates it from git
        built = "home.html" if url == SITE else built_file(url)
        assert (WEB / built).is_file() and [h for r, h in page(built).links if r == "canonical"] == [url], url


def test_the_front_door_says_what_it_is_and_what_it_costs_in_json_ld():
    (doc,) = [d for d in page("home.html").ld if "@graph" in d]
    app = next(x for x in doc["@graph"] if x["@type"] == "SoftwareApplication")
    org = next(x for x in doc["@graph"] if x["@type"] == "Organization")
    assert app["name"] == "Knos" and app["description"] == sentence() and app["url"] == SITE and app["publisher"] == {"@id": org["@id"]}
    assert org["sameAs"] == ["https://github.com/drexthealpha/Knos"]
    offer = app["offers"]
    pricing = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", (WEB / "pricing.html").read_text(encoding="utf-8")))
    assert offer["@type"] == "Offer" and offer["price"] == "0" and offer["description"] in pricing and offer["url"] == SITE + "pricing.html"


def test_llms_txt_has_the_proposals_shape_and_every_link_leads_somewhere():
    text = (WEB / "llms.txt").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "# Knos" and lines[1] == "" and lines[2] == f"> {sentence()}"              # the one line opens it
    heads = re.findall(r"(?m)^## (.+)$", text)
    assert heads[-1] == "Optional" and len(heads) >= 2 and not re.search(r"(?m)^#{3,} ", text)
    items = re.findall(r"(?m)^- \[([^\]]+)\]\(([^)]+)\)(?:: .+)?$", text)
    assert len(items) == len(re.findall(r"(?m)^- ", text)) >= 6
    raw = "https://raw.githubusercontent.com/drexthealpha/Knos/main/"
    for _name, url in items:
        if url.startswith(SITE):
            assert (WEB / built_file(url)).is_file(), url
        elif url.startswith(raw):
            assert (ROOT / url.removeprefix(raw)).is_file(), url
        else:
            assert url in ("https://github.com/drexthealpha/Knos", "https://pypi.org/project/knos/", "https://knos.onrender.com/mcp", "https://knos.onrender.com/app/") or url.startswith("https://github.com/drexthealpha/Knos/tree/main/"), url


# ---- a build ------------------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    site = tmp_path_factory.mktemp("seo") / "site"
    env = _posix.environ({**os.environ, "PYTHON": _posix.path(sys.executable), "PYTHONPATH": str(ROOT / "src")})
    run = subprocess.run([_posix.bash(), _posix.path(ROOT / "scripts" / "build_site.sh"), _posix.path(site), "c" * 40],
                         env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    return site


def test_the_build_stamps_one_date_on_every_page_and_dates_the_sitemap_from_git(built: Path):
    assert all(DATE.match(d) for _u, d in sitemap(built))                     # each page's own last commit (scripts/sitemap_dates.py)
    stamp = re.search(r'Last updated <time datetime="(\d{4}-\d{2}-\d{2})">', (built / "faq.html").read_text(encoding="utf-8")).group(1)
    head = subprocess.run(["git", "log", "-1", "--format=%cs"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    if head.returncode == 0 and DATE.match(head.stdout.strip()):
        assert stamp == head.stdout.strip()                 # a commit this clone does not have ("c" * 40) gives HEAD's date
    for rel in PAGES:
        text = (built / rel).read_text(encoding="utf-8")
        assert "KNOS_BUILD_DATE" not in text and f'Last updated <time datetime="{stamp}">{stamp}</time>' in text
    for url, _d in sitemap(built):
        assert (built / built_file(url)).is_file(), url
    assert (built / "llms.txt").read_bytes() == (WEB / "llms.txt").read_bytes()
    assert html.unescape(page("faq.html", built).title) == page("faq.html").title


def test_the_pages_hold_the_sites_rules_in_a_browser(built: Path):
    """tests/web/seo.mjs: the word budget, no sideways scroll at five widths in both schemes, no outside request, and the
    check page's own check answering from GitHub's recorded answers."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    env = _posix.environ({**os.environ})
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path(BROWSERS).is_dir():
        env["PLAYWRIGHT_BROWSERS_PATH"] = BROWSERS
    run = subprocess.run([node, str(ROOT / "tests" / "web" / "seo.mjs"), str(built)], env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
    said = run.stdout.strip().splitlines()
    if run.returncode == 0 and said and said[-1].startswith("SKIP"):
        pytest.skip(said[-1][5:])
    assert run.returncode == 0, "\n".join(line for line in (run.stdout + run.stderr).splitlines() if not line.startswith("ok"))
    assert "seo: every page holds" in run.stdout
