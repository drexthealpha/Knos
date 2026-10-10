"""The statement of one invoice as each accounting system's bill-import file (knos.erp: `knos statement export --to
xero|quickbooks|netsuite|csv`), on September's statement of tests/test_statement.py with its last line refused by the
buyer (so owed to the supplier) and its first paid by bank. tests/data/erp keeps the files; `python tests/test_erp.py
--write` writes them again, and tests/web/erp.mjs makes the same bytes with the site's web/erp.js."""
from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_statement as T                                     # noqa: E402

from knos import erp, exports, ids, statement                   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data" / "erp"
TODAY = "2026-10-05"
OPTIONS = {"account": "6100", "tax_code": "NONE"}

# The columns each system's own documentation names as required (TARGETS[...]["source"] / ["seen"], read 2026-10-09)
REQUIRED = {
    "xero": {"ContactName", "InvoiceNumber", "InvoiceDate", "DueDate", "Description", "Quantity", "UnitAmount", "AccountCode", "TaxType"},
    "quickbooks": {"Bill no.", "Supplier", "Bill Date", "Due Date", "Account", "Line Amount", "Line Tax Code"},
    "netsuite": {"External ID", "Vendor", "Expenses : Account", "Expenses : Amount"},
    "csv": set(erp.PLAIN),
}
DOCUMENTED = {
    "xero": ["ContactName", "InvoiceNumber", "Reference", "InvoiceDate", "DueDate", "Description", "Quantity", "UnitAmount", "AccountCode", "TaxType",
             "InventoryItemCode", "Discount", "Currency"],
    "quickbooks": ["Bill no.", "Supplier", "Bill Date", "Due Date", "Account", "Line Description", "Line Amount", "Line Tax Code", "Memo"],
    "netsuite": ["External ID", "Vendor", "Date", "Reference No.", "Memo", "Expenses : Account", "Expenses : Amount", "Expenses : Memo"],
    "csv": list(erp.PLAIN),
}


def refused() -> dict:
    """September: line 5 refused by the buyer though its policy is met, the rest approved, line 1 paid by bank."""
    st = T.sept()
    last, first = st["lines"][4]["invoice_line"], st["lines"][0]["invoice_line"]
    s = statement.refuse(st, None, last, "Sam Ortiz", "engineering manager", "2026-10-01", "not what we asked for")
    s = statement.approve(st, s, "Dana Reyes", "finance controller", "2026-10-02")
    return statement.pay(st, s, first, "bank", "BACS 77120", "2026-10-03")


def golden() -> dict[str, str]:
    st, s = T.sept(), refused()
    out = {"sept.refused.status.json": statement.canonical(s).decode("utf-8"), "inputs.json": json.dumps({"today": TODAY, "options": OPTIONS}, sort_keys=True) + "\n"}
    for to in erp.TARGETS:
        payable, held = erp.write(to, st, s, OPTIONS, TODAY)
        out[f"sept.{to}.csv"], out[f"sept.{to}.held.csv"] = payable, held
    return out


def table(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def first(text: str) -> dict[str, str]:
    got = table(text)
    return dict(zip(got[0], got[1]))


@pytest.mark.parametrize("name", sorted(golden()))
def test_the_files_are_the_kept_ones(name):
    assert (DATA / name).read_text(encoding="utf-8") == golden()[name], f"{name} changed: if it was meant, python tests/test_erp.py --write"


@pytest.mark.parametrize("to", sorted(erp.TARGETS))
def test_each_file_has_the_documented_header_and_its_required_columns_filled(to):
    payable, _held = erp.write(to, T.sept(), refused(), OPTIONS, TODAY)
    got = table(payable)
    assert got[0] == DOCUMENTED[to] and list(erp.TARGETS[to]["columns"]) == DOCUMENTED[to]
    assert len(got) == 2, "one bill: line 1. Line 5 is owed (refused), 2 disputed, 3 without enough evidence, 4 a duplicate"
    row = dict(zip(got[0], got[1]))
    assert all(row[c] for c in REQUIRED[to]), {c: row[c] for c in REQUIRED[to] if not row[c]}
    assert erp.TARGETS[to]["source"] and erp.TARGETS[to]["confirmed"]
    assert to == "csv" or erp.TARGETS[to]["source"].startswith("https://")


@pytest.mark.parametrize("to", ["xero", "quickbooks", "netsuite"])
def test_the_memo_carries_the_four_steps_and_the_assurance(to):
    payable, _ = erp.write(to, T.sept(), refused(), OPTIONS, TODAY)
    row = first(payable)
    memo = row[{"xero": "Description", "quickbooks": "Memo", "netsuite": "Memo"}[to]]
    for s in ids.STEPS:
        assert f"{ids.STEP_WORDS[s]}: " in memo
    assert "assurance reported" in memo and "settled: yes, paid outside Knos by bank, reference BACS 77120" in memo
    assert "payment authorised: yes, by Dana Reyes (finance controller) on 2026-10-02" in memo


def test_disputed_and_owed_lines_go_to_the_held_sheet_never_the_payable():
    st, s = T.sept(), refused()
    for to in erp.TARGETS:
        payable, held = erp.write(to, st, s, OPTIONS, TODAY)
        rows = {r["line"]: r for r in csv.DictReader(io.StringIO(held))}
        assert sorted(rows) == ["2", "3", "4", "5"]
        assert rows["5"]["held_because"].startswith(ids.OWED_WORDS) and rows["2"]["held_because"].startswith("disputed")
        assert rows["5"]["accepted"].startswith("no, refused by Sam Ortiz")
        for line in rows.values():
            assert line["invoice_line"] not in payable
        assert st["lines"][0]["invoice_line"] in payable or exports.bill_number(st["lines"][0]["deliverable"], st["lines"][0]["supplier"]) in payable


@pytest.mark.parametrize("fmt", ["quickbooks", "netsuite", "ariba"])
def test_the_older_format_files_never_bill_an_owed_or_disputed_line(fmt):
    """`knos statement export --format quickbooks|netsuite|ariba` too: a line the buyer refused (owed to the supplier)
    or a disputed one is never a bill; the agreed, approved lines are."""
    st, s = T.sept(), refused()
    text = exports.write_statement(fmt, st, s, {"account": "6100", "supplier_id": "AN01", "buyer_id": "AN02"})
    no = lambda ln: exports.bill_number(ln["deliverable"], ln["supplier"])       # noqa: E731
    owed, disputed, first = st["lines"][4], st["lines"][1], st["lines"][0]
    assert no(first) in text or first["invoice_line"] in text
    for ln in (owed, disputed):
        assert no(ln) not in text and ln["invoice_line"] not in text


def test_a_line_nobody_authorised_in_time_is_owed_and_held():
    st = T.sept()
    early = erp.write("csv", st, None, None, "2026-10-05")
    late = erp.write("csv", st, None, None, "2026-11-30")         # 61 days after the statement's day, nobody authorised
    assert len(table(early[0])) == 3 and len(table(late[0])) == 1
    assert sum(r["held_because"].startswith(ids.OWED_WORDS) for r in csv.DictReader(io.StringIO(late[1]))) == 2


def test_options_and_dates():
    st = T.sept()
    row = first(erp.write("xero", st, None, {"date_format": "MM/DD/YYYY", "account": "400", "tax_code": "Tax Exempt"}, TODAY)[0])
    assert (row["InvoiceDate"], row["AccountCode"], row["TaxType"], row["Quantity"], row["UnitAmount"]) == ("09/30/2026", "400", "Tax Exempt", "1", "100.00")
    assert first(erp.write("xero", st, None, None, TODAY)[0])["AccountCode"] == "", "Xero takes a code of your own chart: none is made up"
    assert first(erp.write("quickbooks", st, None, None, TODAY)[0])["Account"] == exports.DEFAULTS["account"]
    with pytest.raises(erp.Refused, match="--to is xero, quickbooks, netsuite, csv"):
        erp.write("sage", st)


def test_export_file_writes_both_beside_the_statement(tmp_path):
    st = T.sept()
    file = tmp_path / "ap-statement.json"
    file.write_bytes(statement.canonical(st))
    (tmp_path / "ap-statement.status.json").write_bytes(statement.canonical(refused()))
    said = erp.export_file(file, "quickbooks", None, OPTIONS, TODAY)
    assert (tmp_path / "ap-statement.quickbooks.csv").read_text(encoding="utf-8") == golden()["sept.quickbooks.csv"]
    assert (tmp_path / "ap-statement.quickbooks.held.csv").read_text(encoding="utf-8") == golden()["sept.quickbooks.held.csv"]
    assert said[0].endswith(f"1 bill for QuickBooks Online: import bills ({exports.LABEL}).") and "4 held lines" in said[1] and said[2].startswith("Unverified:")
    out = tmp_path / "bills.xero.csv"
    erp.export_file(file, "xero", out, OPTIONS, TODAY)
    assert erp.held_path(out) == tmp_path / "bills.xero.held.csv" and erp.held_path(out).is_file()
    (tmp_path / "ap-statement.json").write_bytes(statement.canonical({**st, "invoice": "edited"}))
    with pytest.raises(erp.Refused, match="changed after it was made"):
        erp.export_file(file, "csv", None, None, TODAY)


def test_the_sites_functions_make_the_same_bytes():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([node, str(ROOT / "tests" / "web" / "erp.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
    assert "FAIL" not in done.stdout and done.stdout.count("ok  ") == 2 * len(erp.TARGETS) + 1


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        sys.exit("python tests/test_erp.py --write    writes tests/data/erp again")
    DATA.mkdir(parents=True, exist_ok=True)
    for name, text in golden().items():
        (DATA / name).write_text(text, encoding="utf-8", newline="")
        print(f"wrote {name}")
