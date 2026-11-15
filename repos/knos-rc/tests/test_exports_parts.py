"""The five parts beside every export (knos.exports `parts_file`, `parts_check`): every row of every format, from the
statement of an organisation's month (tests/_finance.py) and from the statement of one invoice (tests/test_statement.py)."""
from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _finance as fin                                          # noqa: E402
import test_exports as X                                        # noqa: E402
import test_exports_match as M                                  # noqa: E402
import test_statement as T                                      # noqa: E402

from knos import audit, exports, receipt                        # noqa: E402


def _rows(text: str) -> list[dict]:
    got = list(csv.reader(io.StringIO(text)))
    return [dict(zip(exports.PARTS, r)) for r in got[2:]]


@pytest.mark.parametrize("fmt", sorted(exports.FORMATS))
def test_every_bill_of_every_finance_format_has_its_five_parts(fmt):
    scope, rows, head = X.statement()
    refs = audit.read_refs(fin.REFS)
    text = exports.write(fmt, scope, rows, head, refs, fin.OPTIONS)
    parts = exports.parts_file(exports.parts_rows(scope, rows, head, refs), exports.sha_of(text))
    assert exports.parts_check(text, parts) == []
    got = _rows(parts)
    assert len(got) == len(exports.bills(scope, rows, head, refs)) == 9
    assert all(r[k] for r in got for k in receipt.FIVE)
    assert all(r["assurance"] == exports.NO_RECEIPT and r["receipt_sha256"] == "" for r in got)       # no receipt read: the floor, said as such


def test_with_its_receipt_a_bill_carries_the_receipts_own_parts_and_never_anothers():
    import copy
    import json
    scope, rows, head = X.statement()
    bill = next(b for b in exports.bills(scope, rows, head) if b["transaction"])
    r5 = copy.deepcopy(json.loads((X.ROOT / "docs" / "receipt" / "vectors.v5.json").read_text(encoding="utf-8"))["valid_v5"][0]["receipt"])
    assert receipt.check(r5) is None
    other = exports.parts_rows(scope, rows, head, receipts={bill["transaction"]: r5})          # a valid receipt of another payment
    assert all(r["receipt_sha256"] is None for r in other)
    own = {**bill, "transaction": r5["transaction"]["signature"]}                             # the bill this receipt's payment is
    assert exports._bill_parts(own, r5) == receipt.five_cells(r5) and receipt.five_missing(receipt.five_cells(r5)) == []
    assert all(r["receipt_sha256"] is None for r in exports.parts_rows(scope, rows, head, receipts=fin.extras()["receipts"]))      # not a receipt that checks


def test_a_parts_file_that_leaves_a_row_or_a_part_out_is_refused():
    scope, rows, head = X.statement()
    text = exports.write("netsuite", scope, rows, head)
    found = exports.parts_rows(scope, rows, head)
    short = exports.parts_file(found[1:], exports.sha_of(text))
    assert exports.parts_check(text, short) == [f"{found[0]['bill_no']} has no row in the parts file."]
    assert exports.parts_check(text + "x", exports.parts_file(found, exports.sha_of(text)))[0].startswith("The parts file names another export")
    with pytest.raises(audit.Refused, match="five parts"):
        exports.parts_file([{**found[0], "assurance": " "}], "0" * 64)


@pytest.mark.parametrize("fmt", [*exports.STATEMENT_FORMATS, *exports.STATEMENT_MORE])
def test_every_line_of_every_statement_export_has_its_five_parts(fmt):
    st, status = T.sept(), M.noted()
    text = exports.write_statement(fmt, st, status)
    got = _rows(exports.parts_file(exports.statement_parts_rows(st, status), exports.sha_of(text)))
    assert len(got) == len(st["lines"]) and all(r[k] for r in got for k in receipt.FIVE)
    last = got[-1]                                                  # the line whose goods-received note was recorded from the payment's receipt
    assert last["receipt_sha256"] and last["assurance"].startswith(("Rerun", "WEAK", "Agreed", "Reported"))
    if fmt in ("quickbooks", "netsuite"):
        assert exports.parts_check(text, exports.parts_file(exports.statement_parts_rows(st, status), exports.sha_of(text))) == []


def test_the_statement_export_command_writes_the_parts_file_beside(tmp_path):
    import json

    from typer.testing import CliRunner

    from knos import cli
    st = T.sept()
    (tmp_path / "ap-statement.json").write_text(json.dumps(st), encoding="utf-8")
    run = CliRunner()
    got = run.invoke(cli.app, ["statement", "export", str(tmp_path / "ap-statement.json"), "--format", "quickbooks", "--out", str(tmp_path / "bills.csv")])
    assert got.exit_code == 0, got.output
    text, parts = (tmp_path / "bills.csv").read_text(encoding="utf-8"), (tmp_path / "bills.csv.parts.csv").read_text(encoding="utf-8")
    assert exports.parts_check(text, parts) == []
    out = run.invoke(cli.app, ["statement", "export", str(tmp_path / "ap-statement.json"), "--format", "generic"])
    assert out.exit_code == 0 and (tmp_path / "ap-statement.generic.parts.csv").is_file()
