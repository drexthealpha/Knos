"""G2 (a cell reading NaN, inf or -inf is a data cell, so a first row holding one is data, never a header; an unknown
column answers "I cannot find a column named <name>. Columns: <names>."), through the server's real run path (POST
/api/run and the connector's run) with the released program, and the server's own reading before it runs."""
from test_f1_unmeasurable import app, mcp_run, run  # noqa: F401 - the app fixture

from knos_wanted import telegram_bot, tool_run


def test_a_headerless_file_whose_first_row_holds_nan_is_read_as_data(app):  # noqa: F811
    table = "1,NaN\n2,1.8\n3,1.3"
    assert tool_run.columns(table) == (["column 1", "column 2"], 3)
    st, r = run(app, table, "column 2", "b-g2-nan-0001")
    assert st == 200, r
    assert r["result"] == "Failed at row 3: 1.3 is not above 1.4. 1 row passed. Row 1 has no number, so I did not check it."
    assert (r["verdict"], r["first_failing_row"], r["passed"], r["unchecked"]) == ("fail", 3, 1, [1]), r


def test_inf_and_minus_inf_in_any_case_are_data_cells():
    for first in ("INF,-inf", "-Infinity,nan", "+iNf,1"):
        assert tool_run.columns(first + "\n2,3")[0] == ["column 1", "column 2"], first
    assert tool_run.columns("cycle,NaN\n1,2")[0] == ["cycle", "NaN"]


def test_an_unknown_column_gives_the_programs_sentence_through_the_site_and_the_connector(app):  # noqa: F811
    table = "cycle,reading\n1,1.8"
    want = "I cannot find a column named voltage. Columns: cycle, reading. Choose one of them and check again."
    st, r = run(app, table, "voltage", "b-g2-col-0001")
    assert st == 400 and r == {"error": want}, r
    got = mcp_run(app, {"id": "limit-check", "table": table, "column": "voltage", "rule": "above", "limit": 1.4})
    assert got.get("isError") and got["content"][0]["text"] == want, got
    st, r = run(app, "1,NaN\n2,1.8", "reading", "b-g2-col-0002")
    assert st == 400 and r["error"] == "I cannot find a column named reading. Columns: column 1, column 2. Choose one of them and check again.", r


def test_the_bot_says_the_same_sentence_then_the_next_step():
    got = telegram_bot.answer("voltage above 1.4\ncycle,reading\n1,1.8", 1)
    first, nxt = got.split("\n", 1)
    assert first == "I cannot find a column named voltage. Columns: cycle, reading. Choose one of them and check again."
    assert nxt.startswith("Put one of them on the first line"), got
