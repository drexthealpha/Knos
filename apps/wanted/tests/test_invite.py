"""L25: an invite opened by a new browser that runs one check on its own file adds the extra free runs to both browsers;
"Copy this check" carries column, rule and limit; another browser's opening of a shared result is counted on that result
for its maker; a challenge is recorded inside Knos with its status (L13)."""
from test_tool_run import app, call, own, program, sample_body  # noqa: F401  (fixtures)

from knos_wanted import tool_page, tool_run, valley

N = tool_run.CONF["invite_runs"]
FREE = tool_run.CONF["free_runs_a_day"]


def test_an_invite_gives_both_browsers_extra_free_runs_once(app):  # noqa: F811
    st, inv, _ = call(app, "/api/invite", {"browser": "b-host-00000001", "test": True})
    assert st == 200 and inv["runs_each"] == N
    st, r, _ = own(app, browser="b-new-000000001", invite=inv["invite"])
    assert st == 200 and r["free_left"] == FREE - 1 + N
    again = own(app, browser="b-new-000000001", invite=inv["invite"])[1]
    assert again["free_left"] == FREE - 2 + N                                       # once per new browser
    host = own(app, browser="b-host-00000001", invite=inv["invite"])[1]
    assert host["free_left"] == FREE - 1 + N                                       # the host got N, and no more for its own code


def test_copy_this_check_carries_column_rule_and_limit():
    js = tool_page.SCRIPT
    assert 'T("inv.copy")' in js and 'u.searchParams.set("rule", r.rule)' in js and 'u.searchParams.set("limit", String(r.limit))' in js
    assert 'u.searchParams.set("column", r.column)' in js and 'q.get("rule")' in js and 'q.get("column")' in js


def test_an_opening_by_another_browser_is_counted_for_the_maker(app):  # noqa: F811
    st, r, _ = own(app, browser="b-maker-0000001")
    assert call(app, "/api/opened", {"id": r["id"]})[1] == {"counted": True}
    assert call(app, "/api/opened", {"id": r["id"], "test": True})[1] == {"counted": False}
    assert valley._safe_load(tool_run.RESULTS, r["id"])["opens"] == 1
    page = call(app, f"/r/{r['id']}/", raw=True)[1].decode("utf-8")
    assert '"opens": 1' in page and 'T("res.opens"' in tool_page.SCRIPT


def test_a_challenge_is_recorded_with_its_status(app):  # noqa: F811
    st, r, _ = call(app, "/api/run", sample_body(test=True))
    st, ch, _ = call(app, "/api/challenge", {"id": r["id"], "why": "row 120 is above the limit in my copy"})
    assert st == 200 and ch["status"] == "open" and ch["result"] == r["id"]
    st, got, _ = call(app, f"/api/challenge/{ch['challenge']}")
    assert st == 200 and got["status"] == "open" and got["result"] == r["id"] and "why" not in got
    assert call(app, "/api/challenge", {"id": r["id"], "why": ""})[0] == 400
    assert call(app, "/api/challenge", {"id": "nosuchresult", "why": "wrong"})[0] == 404
