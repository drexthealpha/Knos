# ruff: noqa: F811  (the app fixture is test_tool_run's, imported by name)
"""Round 13 FIX-SERVER: the verdict on the tool and result pages (U6), "cannot tell" when no row held a number, the undo
of a test payment (U6 Rule 22), the speed a counted visitor's browser sends (U1 R13) and the tool as a form that works
with no script (U7 R21). The app is the one test_tool_run.py starts; the program is the released one."""
import re
import urllib.error
import urllib.parse
import urllib.request

import pytest

from knos_wanted import tool_page, tool_run

from test_tool_run import NoRedirect, app, call, own, program, sample_body  # noqa: F401  (fixtures and helpers)

ALL_SKIPPED = "cycle,v\n1,n/a\n2,n/a\n3,n/a"


def page(base, path):
    return call(base, path, raw=True)[1].decode()


def answer(html: str) -> str:
    return re.search(r'<div class="answer" data-answer data-verdict data-state="(\w+)">(.*?)</div>', html, re.S).group(0)


def test_a_file_with_no_number_in_the_column_is_cannot_tell_never_a_pass(app):
    st, r, _ = own(app, table=ALL_SKIPPED, column="v", limit=2, browser="b-fix-000001")
    assert st == 200 and r["verdict"] == "unknown", r
    assert r["result"] == "I cannot check: no row has a number." and r["unchecked"] == [1, 2, 3]
    html = page(app, "/r/" + r["link"].rstrip("/").rsplit("/", 1)[1] + "/")
    a = answer(html)
    assert 'data-state="unknown"' in a and "data-evidence" not in a
    reason = re.search(r'<p data-reason data-uncertain="true">(.*?)</p>', a).group(1)
    words = re.sub(r"<[^>]+>", " ", reason).split()
    assert 12 <= len(words) <= 35 and words[0] == "I", reason
    assert len(re.sub(r"<[^>]+>", " ", re.search(r"<p data-next-step>(.*?)</p>", a).group(1)).split()) >= 3


def test_pass_and_fail_carry_evidence_a_next_step_and_their_own_icon(app):
    icons = set()
    for table, limit, state in (("row,reading\n1,5\n2,6\n3,7", 4, "pass"), ("row,reading\n1,5\n2,3\n3,7", 4, "fail")):
        st, r, _ = own(app, table=table, limit=limit, browser="b-fix-000002")
        assert st == 200 and r["verdict"] == state, r
        a = answer(page(app, "/r/" + r["link"].rstrip("/").rsplit("/", 1)[1] + "/"))
        assert f'data-state="{state}"' in a and "%" not in a
        ev = re.search(r"<p data-evidence>(.*?)</p>", a).group(1)
        # the comparison is the evidence on the first screen; the test behind it is the answer's own link, under it
        assert "data-compare" in ev and f'href="{tool_page.TEST_URL}" data-verified' in a.split("<p data-evidence>", 1)[1]
        assert len(re.sub(r"<[^>]+>", " ", ev).split()) >= 5
        assert re.search(r"<p data-next-step>[^<]*(<bdi>)?\w", a)
        icons.add(re.search(r"<svg [^>]*>(.*?)</svg>", a).group(1))
        if state == "fail":
            assert "Row 2 of <bdi>reading</bdi> holds <bdi>3</bdi>, compared with <bdi>4</bdi>." in ev
    icons.add(tool_page._SHAPES["unknown"])
    assert len(icons) == 3                                  # three states, three shapes


@pytest.mark.parametrize("lang", tool_page.LANGS)
def test_every_language_writes_the_verdict(app, lang):
    st, r, _ = own(app, table=ALL_SKIPPED, column="v", limit=2, browser="b-fix-000003")
    html = page(app, "/r/" + r["link"].rstrip("/").rsplit("/", 1)[1] + f"/?lang={lang}")
    a = answer(html)
    assert tool_page.t(lang, "rs.cannot").split()[0] in a and tool_page.t(lang, "v.unknown") in html


def test_an_undo_takes_the_test_payment_back_once_while_its_runs_are_unused(app):
    body = {"browser": "b-undo-00001", "press": "press-undo-1", "test": True}
    st, paid, _ = call(app, "/api/pay", body)
    assert st == 200 and paid["runs_left"] == 25
    st, back, _ = call(app, "/api/pay", {**body, "undo": True})
    assert st == 200 and back == {"runs_left": 5, "undone": True}, back
    assert call(app, "/api/pay", {**body, "undo": True})[1] == back            # a second undo: the same answer
    st, r, _ = call(app, "/api/pay", {**body, "browser": "b-undo-00002", "undo": True})
    assert st == 404 and r["error"].startswith("I have no test payment"), r  # another browser cannot undo it
    body2 = {"browser": "b-undo-00003", "press": "press-undo-2", "test": True}
    assert call(app, "/api/pay", body2)[0] == 200
    for _ in range(6):                                                    # 5 free runs, then one of the paid ones
        assert own(app, browser="b-undo-00003")[0] == 200
    st, r, _ = call(app, "/api/pay", {**body2, "undo": True})
    assert st == 409 and r["error"].startswith("I could not undo") and len(r["error"].split()) >= 12, r


def test_speed_is_kept_only_from_a_counted_browser(app):
    st, r, _ = call(app, "/api/vitals", {"screen": "tool", "lcp": 900, "inp": 40, "cls": 0.01})
    assert st == 400 and r["error"].startswith("I keep speed measures only"), r
    st, r, _ = call(app, "/api/vitals", {"screen": "tool", "lcp": 900, "inp": 40, "cls": 0.01, "browser": "b-vitals-0001"})
    assert st == 200 and r == {"kept": True}
    u = call(app, "/api/usage")[1]
    day = max(u["vitals"])
    assert u["vitals"][day]["tool"]["n"] >= 1 and u["vitals"][day]["tool"]["lcp_p75"] == 900.0


def form(base, path, fields: dict):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=60) as r:
            return r.status, r.headers, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode()


def test_the_tool_works_as_a_form_with_no_script(app):
    html = page(app, "/t/limit-check/")
    assert re.search(r'<form id="tool" method="post" action="http://127\.0\.0\.1:\d+/t/limit-check/run">', html)
    assert '<button id="go" class="primary" type="submit" data-primary>' in html
    st, h, _ = form(app, "/t/limit-check/run", {"table": tool_run.sample(), "column": "capacity_ah", "rule": "above", "limit": "1,4", "test": "1"})
    assert st == 303 and re.fullmatch(r"/r/[A-Za-z0-9_-]{12}/\?test=1", h["Location"]), h["Location"]
    assert "Failed at row " in page(app, h["Location"])
    st, _, body = form(app, "/t/limit-check/run", {"table": "when,volts\n1,3", "column": "capacity_ah", "rule": "above", "limit": "2"})
    assert st == 400 and "I cannot find a column named capacity_ah. Columns: when, volts." in body
    assert ">when,volts\n1,3</textarea>" in body and 'role="alert"' in body          # the person's table is kept
    # G5: the box is offered empty, the sample's first rows shown in it as an example; sent empty and untouched, Check my
    # data checks that example (the hidden field "sample"); a box sent empty without it is an empty file
    assert '<input type="hidden" dir="auto" name="sample" value="1">' in html
    st, h, _ = form(app, "/t/limit-check/run", {"table": "", "sample": "1", "column": "capacity_ah", "rule": "above", "limit": "1.4", "test": "1"})
    assert st == 303 and "Failed at row " in page(app, h["Location"])
    st, _, body = form(app, "/t/limit-check/run", {"table": "", "column": "capacity_ah", "rule": "above", "limit": "1.4"})
    assert st == 400 and "Your file is empty" in body and "then press Check my data." in body
    # the sample link with no script: the tool page with the sample in the box, labelled as the sample
    html = page(app, "/t/limit-check/?sample=1")
    assert re.search(r'<textarea id="list"[^>]*>cycle,capacity_ah\n1,1\.86\n', html) and ">Sample: made-up battery test</label>" in html
    assert 'name="sample"' not in html and "placeholder=" not in html


def test_sample_body_still_runs(app):
    assert call(app, "/api/run", sample_body(test=True))[1]["verdict"] in tool_page.STATES


def test_a_result_page_opened_from_its_link_shows_the_table_it_checked_in_the_box(app):
    # R13 G2 step 6: a result address opened fresh shows the same input and result, so the box holds the table it checked
    # (labelled as that table); U6 Rule 2 (UX/U6.md line 33): the box is emptied for the next table by the person's own
    # run on the page (its script); the checked table then stays shown, read-only, under the result (G5): that copy is
    # hidden while the box itself holds the table
    st, r, _ = own(app, table="row,reading\n1,5\n2,3\n3,7", limit=4, browser="b-fix-000009")
    assert st == 200, r
    html = page(app, "/r/" + r["link"].rstrip("/").rsplit("/", 1)[1] + "/")
    assert re.search(r'<textarea id="list"[^>]*>row,reading\n1,5\n2,3\n3,7</textarea>', html)
    assert '<label id="lab" for="list">Table checked</label>' in html
    assert "if (ran && box.value.trim())" in html                  # only the person's own run empties the box
    assert re.search(r'<figure id="k-input" aria-labelledby="k-input-h" hidden><figcaption id="k-input-h">Table checked</figcaption>'
                     r'<pre data-user-content dir="auto" tabindex="0" aria-labelledby="k-input-h">row,reading\n1,5\n2,3\n3,7</pre></figure>', html)
    assert "if (was && box.value.trim() !== String(was).trim()) checked(was); else unchecked();" in html
    assert '<h1><label for="list" id="k-name">' in html          # the box's label is the screen's largest text (U1 R5)


def test_with_save_data_the_pages_come_without_their_script_and_say_so_in_vary(app):
    # U7 R25 (UX/U7.md line 279): the lighter page is the form the server runs, as with scripts off
    st, r, _ = call(app, "/api/run", sample_body(mode="sample", test=True))
    assert st == 200, r
    for path in ("/t/limit-check/", "/r/" + r["link"].rstrip("/").rsplit("/", 1)[1] + "/"):
        full = call(app, path, raw=True)
        lite = call(app, path, headers={"Save-Data": "on"}, raw=True)
        assert full[0] == lite[0] == 200 and "Save-Data" in full[2]["Vary"] and "Save-Data" in lite[2]["Vary"]
        assert "<script>" in full[1].decode() and 'id="k-tool"' not in lite[1].decode() and "serviceWorker" not in lite[1].decode()
        assert len(lite[1]) <= 0.7 * len(full[1]) and '<form id="tool" method="post"' in lite[1].decode()
        assert lite[2].get("X-Knos-Offline") is None


def test_the_free_runs_are_counted_per_browser_not_per_address(app):
    # R13 WALK 1: pricing says "5 free a day, in each browser"; two browsers on one address (two people on one network)
    # that did not say yes to being counted each have their own five, by the runs id their page keeps for that alone
    free = int(tool_run.CONF["free_runs_a_day"])
    for runs in ("r-fixw1-browser-a", "r-fixw1-browser-b"):
        st, r, _ = own(app, browser="", runs=runs)
        assert st == 200 and r["free_left"] == free - 1, r
    st, r, _ = own(app, browser="", runs="r-fixw1-browser-a")
    assert st == 200 and r["free_left"] == free - 2, r
    assert tool_run._key("", "1.2.3.4", "r-fixw1-browser-a").startswith("run:")
    assert tool_run._key("", "1.2.3.4", None).startswith("addr:")         # a caller with no id at all: the address


@pytest.mark.parametrize("path", ["/r/nosuchresult123/", "/r/nosuchresult123", "/r/abcdefabcdef", "/r/x/", "/r/aaaaaaaaaaaa/"])
def test_every_unknown_result_address_is_the_plain_not_found_page(app, path):
    st, body, h = call(app, path, raw=True)
    html = body.decode()
    assert st == 404 and h["Content-Type"].startswith("text/html") and "<h1>I cannot find this page</h1>" in html, html[:200]
    assert '<a class="go" href="/t/limit-check/" data-primary>' in html and "referral" not in html


def test_the_printed_page_and_the_mark_write_at_least_16_px_and_their_link_is_48_px_high(app):
    st, r, _ = call(app, "/api/run", sample_body(mode="sample", test=True))
    rid = r["link"].rstrip("/").rsplit("/", 1)[1]
    for part in ("print", "mark"):
        html = page(app, f"/r/{rid}/{part}")
        sizes = [int(x) for x in re.findall(r"font(?:-size)?:(\d+)px", html)]
        assert sizes and min(sizes) >= 16, (part, sizes)
        assert "min-height:48px" in html
