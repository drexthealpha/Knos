"""L42 and L17: a run cannot cross into another run or spend past its limit, and a person can delete their own result.
A result's own key goes only to the browser that ran it: another browser cannot download its table or delete it; an
oversized file is 413 and a slow run 408 (the limits in runner_conf); a crafted rule or column is data, never code; a
payment asking past the pack is refused. DELETE with the key removes the record, and a later GET is 404."""
from test_tool_run import SMALL, app, call, own, program  # noqa: F401  (fixtures)

from knos_wanted import tool_run


def delete(base, rid, key=None):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(base + f"/api/run/{rid}", method="DELETE", headers={"X-Knos-Key": key} if key else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def test_another_browser_cannot_read_or_delete_a_result(app):  # noqa: F811
    st, mine, _ = own(app, browser="b-one-000000001")
    st2, theirs, _ = own(app, browser="b-two-000000002", table="row,reading\n1,9\n2,8")
    assert st == st2 == 200 and mine["key"] != theirs["key"]
    assert call(app, f"/api/run/{mine['id']}.csv", headers={"X-Knos-Key": theirs["key"]})[0] == 403
    assert call(app, f"/api/run/{mine['id']}.json")[0] == 403
    assert delete(app, mine["id"], theirs["key"]) == 403 and delete(app, mine["id"]) == 403
    assert call(app, f"/api/run/{mine['id']}.json", headers={"X-Knos-Key": mine["key"]})[1]["table"] == SMALL


def test_delete_with_the_key_removes_the_result(app):  # noqa: F811
    st, r, _ = own(app, browser="b-del-000000001")
    assert delete(app, r["id"], r["key"]) == 200
    assert call(app, f"/r/{r['id']}/", raw=True)[0] == 404
    assert call(app, f"/api/run/{r['id']}.json", headers={"X-Knos-Key": r["key"]})[0] == 404
    assert delete(app, r["id"], r["key"]) == 404


def test_an_oversized_file_is_413_and_a_slow_run_408(app, monkeypatch):  # noqa: F811
    monkeypatch.setitem(tool_run.CONF, "max_rows", 3)
    assert own(app, table="row,reading\n" + "\n".join(f"{i},{i}" for i in range(1, 6)))[0] == 413
    monkeypatch.setitem(tool_run.CONF, "max_rows", 100000)
    monkeypatch.setattr(tool_run, "max_seconds", lambda: 1)
    real = tool_run.subprocess.run

    def slow(*a, **k):
        raise tool_run.subprocess.TimeoutExpired(a[0], k.get("timeout"))
    monkeypatch.setattr(tool_run.subprocess, "run", slow)
    try:
        assert own(app, browser="b-slow-00000001")[0] == 408
    finally:
        monkeypatch.setattr(tool_run.subprocess, "run", real)


def test_a_crafted_rule_or_column_is_data(app):  # noqa: F811
    for rule in ("above; import os", "__import__('os').system('x')", ["above"], {"x": 1}):
        st, r, _ = own(app, rule=rule)
        assert st == 400 and "above or below" in r["error"]
    st, r, _ = own(app, column="__import__('os').system('echo x')")
    assert st == 400 and "I cannot find a column named" in r["error"]
    st, r, _ = own(app, table='a,"b""); print(1) #"\n1,2', column='b"); print(1) #')
    assert st == 200 and r["verdict"] in ("pass", "fail", "unknown")             # read as a column name, run as data


def test_tab_and_semicolon_files_give_the_comma_files_verdict(app):  # noqa: F811
    comma = own(app, browser="b-sep-000000001")[1]
    tab = own(app, browser="b-sep-000000001", table=SMALL.replace(",", "\t"))[1]
    semi = own(app, browser="b-sep-000000001", table="row;reading\n1;5\n2;6\n3;7")[1]
    dec = own(app, browser="b-sep-000000002", table="row;reading\n1;5,0\n2;6,0\n3;3,5")[1]
    assert comma["result"] == tab["result"] == semi["result"]
    assert dec["verdict"] == "fail" and dec["first_failing_row"] == 3
