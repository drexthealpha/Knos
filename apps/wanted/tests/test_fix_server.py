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
    assert st == 200 and r["verdict"] == "unknown" and r["result"] == tool_page.UNKNOWN, r
    assert r["result"].startswith("I cannot ") and len(r["result"].split()) <= 9
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
    assert tool_page.t(lang, "rs.unknown").split()[0] in a and tool_page.t(lang, "v.unknown") in html


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
    assert st == 400 and "I could not find a column called capacity_ah in your file." in body
    assert ">when,volts\n1,3</textarea>" in body and 'role="alert"' in body          # the person's table is kept


def test_sample_body_still_runs(app):
    assert call(app, "/api/run", sample_body(test=True))[1]["verdict"] in tool_page.STATES


def test_a_result_page_offers_the_box_empty_and_shows_the_table_it_checked(app):
    # U6 Rule 2 (UX/U6.md line 33): after a verdict the box is empty for the next table; the checked table is kept in the
    # page's fold, and the page's script puts it back in the box when the person comes back (section 12)
    st, r, _ = own(app, table="row,reading\n1,5\n2,3\n3,7", limit=4, browser="b-fix-000009")
    assert st == 200, r
    html = page(app, "/r/" + r["link"].rstrip("/").rsplit("/", 1)[1] + "/")
    assert re.search(r'<textarea id="list"[^>]*></textarea>', html)
    assert re.search(r'<div id="k-input"><p class="muted">[^<]+</p><pre data-user-content dir="auto">row,reading\n1,5\n2,3\n3,7</pre>', html)
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
