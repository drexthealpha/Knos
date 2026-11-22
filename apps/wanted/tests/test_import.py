"""L26: a spreadsheet (.xlsx) and a tab file of the sample give the same verdict as the comma file, in one step."""
import base64
import io
import zipfile

from test_tool_run import app, call, program, sample_body  # noqa: F401  (fixtures)

from knos_wanted import tool_run


def xlsx_of(table: str) -> bytes:
    """A minimal workbook of the table: numbers as numbers, words as shared strings."""
    rows = [r.split(",") for r in table.strip().split("\n")]
    words = sorted({c for r in rows for c in r if not tool_run.is_data(c)})
    cell = lambda i, j, c: (f'<c r="{chr(65 + j)}{i + 1}"><v>{c}</v></c>' if tool_run.is_data(c)        # noqa: E731
                            else f'<c r="{chr(65 + j)}{i + 1}" t="s"><v>{words.index(c)}</v></c>')
    sheet = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             + "".join(f'<row r="{i + 1}">' + "".join(cell(i, j, c) for j, c in enumerate(r)) + "</row>" for i, r in enumerate(rows))
             + "</sheetData></worksheet>")
    sst = ('<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           + "".join(f"<si><t>{w}</t></si>" for w in words) + "</sst>")
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", sst)
    return b.getvalue()


def test_xlsx_and_tab_copies_of_the_sample_give_the_same_verdict(app):  # noqa: F811
    comma = call(app, "/api/run", sample_body(test=True))[1]
    st, conv, _ = call(app, "/api/convert", {"xlsx": base64.b64encode(xlsx_of(tool_run.sample())).decode()})
    assert st == 200 and tool_run.lines_of(conv["table"]) == tool_run.lines_of(tool_run.sample())
    from_xlsx = call(app, "/api/run", sample_body(table=conv["table"], test=True))[1]
    tab = call(app, "/api/run", sample_body(table=tool_run.sample().replace(",", "\t"), test=True))[1]
    assert comma["result"] == from_xlsx["result"] == tab["result"] and comma["verdict"] == tab["verdict"]


def test_a_broken_workbook_is_a_plain_refusal(app):  # noqa: F811
    st, r, _ = call(app, "/api/convert", {"xlsx": base64.b64encode(b"not a zip").decode()})
    assert st == 400 and "comma separated" in r["error"]
