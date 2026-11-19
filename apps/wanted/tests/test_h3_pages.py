"""Round 13, H3 a, b, e and f on the server's two pages (knos_wanted.tool_page): /t/<id>/ and /r/<result-id>/.

  a  the language from ?lang=, else Accept-Language, else English (U7 R17), with Vary: Accept-Language; Arabic sets
     dir="rtl" on the html tag (R1); every visible string comes from web/i18n/<lang>.json (R19), every file has every
     key, its placeholders and the plural forms of its language (R7, R33), and a machine translation says so, in the
     file and in the fold; the result sentence is the program's English through a fixed, tested template
  b  Listen sits in the result page's fold (the browser's own speech, no outside service)
  e  the result sentence is in the first response: it shows with scripts blocked
  f  the fold opens with the five labelled answers, in order, each at most 25 words in English, none of the four
     words the Plain Language Spec forbids in place of an answer; then "Show this on your site" and "Print"
"""
from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser

import pytest
import test_tool_run as B
from test_tool_run import call, file2, own, sample_body

from knos_wanted import tool_page, tool_run
from knos_wanted.runner_conf import CONF

app, program = B.app, B.program        # the fixtures of test_tool_run: a served app, and the released program or its stand-in

LANGS = tool_page.LANGS
CLDR = {"en": {"one", "other"}, "ar": {"zero", "one", "two", "few", "many", "other"}, "hi": {"one", "other"},
        "es": {"one", "many", "other"}, "fr": {"one", "many", "other"}, "pt": {"one", "many", "other"}, "zh-Hans": {"other"},
        "id": {"other"}, "sw": {"one", "other"}, "ru": {"one", "few", "many", "other"}}   # CLDR 49 plurals.json, as U7 R7 lists
MT = "machine translated, not reviewed by a native speaker"
FIVE = ["What you get", "What to do next", "What you pay", "Why believe this", "Who is responsible"]
NEVER = ("AI-powered", "verified", "backed", "ready")


class Seen(HTMLParser):
    """Visible text: no head, script, style or textarea; every attribute a person can see or hear (placeholder,
    aria-label, title)."""
    def __init__(self):
        super().__init__()
        self.skip, self.text = 0, []

    def handle_starttag(self, tag, attrs):
        if tag in ("head", "script", "style", "textarea"):
            self.skip += 1
        for k, v in attrs:
            if k in ("placeholder", "aria-label", "title") and v and not self.skip:
                self.text.append(v)

    def handle_endtag(self, tag):
        if tag in ("head", "script", "style", "textarea"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.text.append(data.strip())


def seen(page: str) -> list[str]:
    p = Seen()
    p.feed(page)
    return p.text


def words(s: str) -> int:
    return len(re.sub(r"<[^>]+>", " ", s).split())


def result_id(app, lang="en") -> str:
    st, r, _ = call(app, "/api/run", sample_body(test=True))
    assert st == 200, r
    return r["link"].rstrip("/").rsplit("/", 1)[1]


# ---- the files ---------------------------------------------------------------------------------------------------------
def test_every_language_file_has_every_key_its_placeholders_and_its_plural_forms():
    en = tool_page.table("en")["strings"]
    for lang in LANGS:
        d = tool_page.table(lang)
        assert d["_meta"]["lang"] == lang and d["_meta"]["dir"] == ("rtl" if lang == "ar" else "ltr")
        s = d["strings"]
        assert set(s) == set(en), (lang, set(en) ^ set(s))
        for k, v in s.items():
            src = en[k] if isinstance(en[k], str) else en[k]["other"]
            forms = list(v.values()) if isinstance(v, dict) else [v]
            assert all(f.strip() for f in forms), (lang, k)
            if isinstance(v, dict):
                assert set(v) == CLDR[lang], (lang, k, sorted(v))
            for f in forms:
                assert sorted(re.findall(r"\{(\w+)\}", f)) == sorted(re.findall(r"\{(\w+)\}", src)), (lang, k, f)
                assert f.count("<a ") == src.count("<a "), (lang, k)
            if lang != "en" and v == en[k]:
                assert k in d["_meta"]["same"], (lang, k)        # the same as English only where it is the right word there
        if lang != "en":
            assert d["_meta"]["status"] == MT and d["_meta"]["reviewed_by"] == "", lang


def test_the_english_file_holds_the_words_the_tool_and_its_tests_name():
    s = tool_page.table("en")["strings"]
    assert s["tool.title"] == tool_run.TITLE and s["tool.line"] == tool_run.LINE and s["res.shown_by"] == tool_run.SHOWN_BY
    assert s["tool.sample_made_up" if CONF["sample_made_up"] else "tool.sample_nasa"] == CONF["sample_label"]
    assert [s[k] for k in ("q.get", "q.next", "q.pay", "q.why", "q.who")] == FIVE


def test_the_plural_rules_are_cldrs():
    want = {("ar", 0): "zero", ("ar", 1): "one", ("ar", 2): "two", ("ar", 3): "few", ("ar", 10): "few", ("ar", 11): "many",
            ("ar", 99): "many", ("ar", 100): "other", ("ar", 103): "few", ("ru", 1): "one", ("ru", 2): "few", ("ru", 5): "many",
            ("ru", 11): "many", ("ru", 21): "one", ("ru", 22): "few", ("ru", 112): "many", ("fr", 0): "one", ("fr", 1): "one",
            ("fr", 2): "other", ("fr", 1000000): "many", ("es", 0): "other", ("es", 1): "one", ("es", 1000000): "many",
            ("pt", 0): "one", ("hi", 0): "one", ("hi", 1): "one", ("hi", 2): "other", ("en", 0): "other", ("en", 1): "one",
            ("sw", 1): "one", ("zh-Hans", 1): "other", ("id", 1): "other"}
    for (lang, n), cat in want.items():
        assert tool_page.plural(lang, n) == cat, (lang, n)


def test_counts_and_money_are_written_in_each_languages_own_way():
    assert [tool_page.nf(c, 100000) for c in ("en", "hi", "es", "fr", "ru")] == ["100,000", "1,00,000", "100.000", "100 000", "100 000"]
    assert tool_page.nf("es", 1234) == "1234" and tool_page.nf("hi", 1234567) == "12,34,567"
    assert tool_page.money("en", 1) == "$1" and tool_page.money("fr", 330) == "330 $"


# ---- the language of a page --------------------------------------------------------------------------------------------
def test_the_language_comes_from_the_link_then_the_browser_then_english():
    assert tool_page.pick(None, "ar-EG,ar;q=0.9,en;q=0.8") == "ar"
    assert tool_page.pick("fr", "ar-EG") == "fr"
    assert tool_page.pick(None, "xx") == "en" and tool_page.pick(None, "") == "en"
    assert tool_page.pick(None, "zh-CN") == "zh-Hans" and tool_page.pick(None, "pt-BR") == "pt"
    assert tool_page.pick(None, "en;q=0.4, sw;q=0.9") == "sw"


@pytest.mark.parametrize("lang", LANGS)
def test_a_tool_page_in_each_language(app, lang):
    st, raw, h = call(app, "/t/limit-check/", headers={"Accept-Language": f"{lang},en;q=0.1"}, raw=True)
    page = raw.decode()
    assert st == 200 and "Accept-Language" in (h.get("Vary") or "") and h.get("Content-Language") == lang
    assert f'<html lang="{lang}" dir="{"rtl" if lang == "ar" else "ltr"}">' in page
    m = tool_page.meta(lang)
    assert 'data-language-switcher' in page and f'<span lang="{lang}">{m["name"]}</span>' in page
    for c in LANGS:                                                      # every language, written in itself
        assert f'lang="{c}" hreflang="{c}"' in page and tool_page.meta(c)["name"] in page
    if lang != "en":
        en = tool_page.table("en")["strings"]
        allowed = set(tool_page.meta(lang)["same"])
        shown = seen(page)
        left = [x for x in shown if any(x == v for k, v in en.items() if isinstance(v, str) and k not in allowed and len(v) > 3)]
        assert left == [], (lang, left)                                  # no English string left on the screen (U7 R19)
        assert html.escape(tool_page.t(lang, "fold.mt")) in page         # the fold says it is a machine translation
    for field in ("list", "col", "limit"):                                   # text a person puts in keeps its own direction (U7 R2)
        assert re.search(rf'<(input|textarea|select) id="{field}"[^>]*dir="auto"', page), field


def test_the_link_names_a_language_and_wins_over_the_browser(app):
    st, raw, _ = call(app, "/t/limit-check/?lang=ru", headers={"Accept-Language": "ar"}, raw=True)
    assert '<html lang="ru" dir="ltr">' in raw.decode()
    st, raw, _ = call(app, "/t/limit-check/", headers={"Accept-Language": "xx-YY"}, raw=True)
    assert '<html lang="en" dir="ltr">' in raw.decode()


# ---- the fold: five answers, then the rest ----------------------------------------------------------------------------
def five_of(page: str) -> list[tuple[str, str]]:
    dl = re.search(r'<dl class="five">(.*?)</dl>', page, re.S).group(1)
    return re.findall(r"<dt>(.*?)</dt><dd>(.*?)</dd>", dl, re.S)


@pytest.mark.parametrize("path", ["tool", "result"])
def test_the_fold_opens_with_the_five_answers(app, path):
    url = "/t/limit-check/" if path == "tool" else f"/r/{result_id(app)}/"
    page = call(app, url, raw=True)[1].decode()
    fold = page[page.index("<summary>How it works</summary>"):]
    assert fold.index('<dl class="five">') < fold.index("<ol>")             # the five lines first, the rest of the fold after them
    got = five_of(page)
    assert [q for q, _ in got] == FIVE
    for q, a in got:
        text = re.sub(r"<[^>]+>", "", a)
        assert 0 < words(text) <= 25, (q, text)
        for w in NEVER:
            assert not re.search(rf"\b{w}\b", text, re.I), (q, w)
    pay = re.sub(r"<[^>]+>", "", got[2][1])
    assert f"{CONF['free_runs_a_day']} free runs a day" in pay and CONF["pack_price"] in pay and f"for {CONF['pack_runs']} more" in pay
    assert "test" in re.sub(r"<[^>]+>", "", got[3][1]) and "github.com/drexthealpha/Knos/issues" in got[4][1]
    for lang in LANGS:                                                     # the same five, in every language, in order
        p = call(app, url + f"?lang={lang}", raw=True)[1].decode()
        assert [q for q, _ in five_of(p)] == [tool_page.t(lang, k) for k in ("q.get", "q.next", "q.pay", "q.why", "q.who")]


def test_the_result_page_has_listen_the_line_for_another_site_and_print(app):
    rid = result_id(app)
    page = call(app, f"/r/{rid}/", raw=True)[1].decode()
    fold = page[page.index("<summary>How it works</summary>"):page.index("</details>", page.index("<summary>How it works</summary>"))]
    assert '<button type="button" id="listen" hidden>Listen</button>' in fold          # shown by the script where speech exists
    assert '<a href="#k-embed">Show this on your site</a>' in fold
    line = re.search(r'id="k-embed-line" readonly dir="auto" value="([^"]+)"', fold).group(1)
    assert re.fullmatch(rf'&lt;iframe src=&quot;http://127\.0\.0\.1:\d+/r/{rid}/mark&quot;[^&]*.*&gt;&lt;/iframe&gt;', line), line
    assert re.search(rf'<a href="http://127\.0\.0\.1:\d+/r/{rid}/print">Print</a>', fold)
    assert "speechSynthesis" in page and "SpeechSynthesisUtterance" in page and "u.lang = KI.speech()" in page
    tool_page_html = call(app, "/t/limit-check/", raw=True)[1].decode()
    assert 'id="listen"' not in tool_page_html and "/mark" not in tool_page_html     # a tool page has no result to show


# ---- the result sentence, in every language, with no script ----------------------------------------------------------
SENTENCES = ["Failed at row 37: 2.41 is not above 2.5. 98 rows passed.",
             "Failed at row 1: 3 is not below 2. 0 rows passed.",
             "Passed: all 100 rows stay above 1.4.",
             "Passed: all 1 row stays above 1.4. Row 2 has no number, so I did not check it.",
             "Passed: all 97 rows stay above 1.4. Rows 2, 5 and 7 have no number, so I did not check them.",
             "Failed at row 50: 1.4 is not above 1.4. 47 rows passed. Rows 3 and 9 have no number, so I did not check them.",
             "Failed at row 10: 1.2 is not above 1.4. 1 row passed. Rows 2, 3, 4, 5, 6 and 3 more have no number, so I did not check them.",
             "I cannot check: no row has a number."]


def test_the_template_reads_every_sentence_the_program_writes():
    for s in SENTENCES:
        m = tool_page.RS.match(s)
        assert m, s
        # English is the program's sentence as written ("I cannot check" is already in the first person, UX/U6.md Rule 7)
        assert tool_page.sentence("en", s, as_html=False) == s
        for lang in LANGS:
            out = tool_page.sentence(lang, s, as_html=False)
            assert out and (lang == "en" or out != s)
            for n in re.findall(r"\d+(?:\.\d+)?", s):
                assert n in out, (lang, n, out)                          # every number of the program's sentence is kept
            html_ = tool_page.sentence(lang, s)
            if lang != "en" and not s.startswith("I cannot check"):   # "I cannot check" quotes no value from the file
                assert "<bdi>" in html_                                    # values from the file keep their own direction (U7 R2)
    assert tool_page.sentence("ar", "something else") == "something else"   # a sentence the template does not know: as written


def test_a_result_page_shows_the_sentence_with_no_script_in_each_language(app):
    st, r, _ = call(app, "/api/run", sample_body(test=True))
    rid = r["link"].rstrip("/").rsplit("/", 1)[1]
    for lang in LANGS:
        page = call(app, f"/r/{rid}/?lang={lang}", raw=True)[1].decode()
        nos = re.sub(r"<script.*?</script>", "", page, flags=re.S)            # what a browser with scripts blocked has
        big = re.search(r'<p class="big" id="about">(.*?)</p>', nos, re.S).group(1)
        assert re.sub(r"<[^>]+>", "", big) == tool_page.sentence(lang, r["result"], as_html=False), lang
        if lang != "en":
            assert json.dumps(r["result"])[1:-1].split(":")[0] in page        # the program's own words stay in the fold


def test_a_page_in_arabic_keeps_the_own_file_and_the_chart_left_to_right(app):
    text, column, limit = file2()
    st, r, _ = own(app, text, column=column, limit=limit)
    rid = r["link"].rstrip("/").rsplit("/", 1)[1]
    page = call(app, f"/r/{rid}/?lang=ar", raw=True)[1].decode()
    assert '<html lang="ar" dir="rtl">' in page and '<textarea id="list" dir="auto"' in page
    assert 'dir: "ltr", "data-no-mirror": ""' in page                         # the chart is drawn left to right (U7 R4)
    assert "<bdi>" in re.search(r'<p class="big" id="about">(.*?)</p>', page, re.S).group(1)


def test_the_page_css_sets_no_direction_and_no_left_or_right():
    css = tool_page.CSS
    for bad in ("margin-left", "margin-right", "padding-left", "padding-right", "text-align:left", "text-align:right",
                "float:left", "float:right"):
        assert bad not in css.replace(" ", ""), bad                            # U7 R1: logical properties only
    assert not re.search(r"(?<![-\w])(left|right|direction)\s*:", css)          # nor the base direction in CSS


def test_the_server_image_carries_the_language_files():
    """The Render image is built from apps/wanted/Dockerfile: the pages read web/i18n/<lang>.json from /app, so the image
    must copy that folder (the lead's file: one COPY line)."""
    docker = (tool_page.ROOT / "apps" / "wanted" / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^COPY\b.*\bweb/i18n\b", docker, re.M), "apps/wanted/Dockerfile does not copy web/i18n"
