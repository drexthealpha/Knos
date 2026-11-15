"""The purchase-order match and the cXML invoice of a statement (knos.exports: `match_of`, `write_statement` with
`match` and `ariba`), on September's statement of tests/test_statement.py and the status with a recorded goods-received
note that tests/data/statement keeps. tests/data/rails holds the two files; `python tests/test_exports_match.py --write`
writes them again. The cXML is read back as XML here; it was held to no document type definition and no network took it."""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import typer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_statement as T                                     # noqa: E402

from knos import audit, exports, statement                      # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data" / "rails"


def noted() -> dict:
    """September's status with the goods-received note of its last line recorded from the payment's receipt."""
    return json.loads((T.DATA / "sept.grn.status.json").read_text(encoding="utf-8"))


def golden() -> dict[str, str]:
    st = T.sept()
    return {"sept.match.csv": exports.write_statement("match", st, noted()), "sept.ariba.xml": exports.write_statement("ariba", st, noted(), {"supplier_id": "AN01000000001", "buyer_id": "AN02000000002"})}


@pytest.mark.parametrize("name", sorted(golden()))
def test_the_files_are_the_kept_ones(name):
    assert (DATA / name).read_text(encoding="utf-8") == golden()[name], f"{name} changed: if it was meant, python tests/test_exports_match.py --write"


def test_every_line_says_its_purchase_order_and_its_match():
    st = T.sept()
    table = list(csv.reader(io.StringIO(exports.write_statement("match", st, noted()))))
    assert table[0] == ["knos.finance-export", "version", "1", "match", exports.LABEL] and tuple(table[1]) == exports.MATCH and len(table) == 2 + len(st["lines"])
    rows = [dict(zip(exports.MATCH, r)) for r in table[2:]]
    last = statement.lines_now(st, noted())[4]
    assert last["po_reference"] and [r["po_number"] for r in rows] == ["", "", "", "", last["po_reference"]]
    assert [r["match"] for r in rows] == ["2-way", "none", "none", "none", "3-way"]
    assert rows[4]["match_legs"] == "purchase order + receipt of goods + invoice line" and rows[4]["match_why"] == "" and rows[4]["grn_reference"] == last["grn_reference"]
    assert rows[0]["match_legs"] == "receipt of goods + invoice line" and "no purchase order on record" in rows[0]["match_why"]
    assert rows[1]["match_why"].startswith("disputed: a check failed") and rows[3]["match_why"].startswith("duplicate: billed twice") and rows[3]["grn_reference"] == ""
    # a recorded note that does not match is "none", with the note's own words; with no status at all nothing is 3-way
    wrong = noted()
    grn = next(e for e in wrong["events"] if e["type"] == "grn")["grn"]
    grn.update({"match": False, "mismatches": ["the invoice line bills 60.00; the order's price is 50.00"]})
    assert exports.match_of(st, wrong)[4]["match"] == "none" and "the order's price is 50.00" in exports.match_of(st, wrong)[4]["match_why"]
    assert [m["match"] for m in exports.match_of(st)] == ["2-way", "none", "none", "none", "2-way"]
    # the three older files are what they were: the match is a file of its own
    assert exports.STATEMENT_FORMATS == ("quickbooks", "netsuite", "generic") and set(exports.STATEMENT_MORE) == {"match", "ariba"}
    with pytest.raises(audit.Refused, match="quickbooks, netsuite, generic, match, ariba"):
        exports.write_statement("xero", st)


def test_the_cxml_invoice_holds_the_agreed_lines_grouped_by_order():
    st = T.sept()
    text = exports.write_statement("ariba", st, noted(), {"supplier_id": "AN01000000001", "buyer_id": "AN02000000002"})
    assert text.splitlines()[1] == '<!DOCTYPE cXML SYSTEM "http://xml.cXML.org/schemas/cXML/1.2.020/InvoiceDetail.dtd">'
    root = ET.fromstring(text.split("\n", 2)[2].encode())           # the body after the declaration and the document type line
    assert root.tag == "cXML" and [e.text for e in root.iter("Identity")] == ["AN01000000001", "AN02000000002", "AN01000000001"]
    head = root.find("Request/InvoiceDetailRequest/InvoiceDetailRequestHeader")
    assert (head.get("invoiceID"), head.get("purpose"), head.get("operation"), head.get("invoiceDate")) == ("INV-2026-09", "standard", "new", "2026-09-30T00:00:00+00:00")
    assert [c.tag for c in head][:2] == ["InvoiceDetailHeaderIndicator", "InvoiceDetailLineIndicator"] and head.find("Extrinsic").text == st["sha256"]
    orders = root.findall("Request/InvoiceDetailRequest/InvoiceDetailOrder")
    assert len(orders) == 2                                           # one with no order on record, one under its purchase order
    po = statement.lines_now(st, noted())[4]["po_reference"]
    assert orders[0].find("InvoiceDetailOrderInfo/MasterAgreementReference/DocumentReference").get("payloadID") == ""
    assert orders[1].find("InvoiceDetailOrderInfo/OrderReference").get("orderID") == po
    items = root.findall(".//InvoiceDetailItem")
    assert [i.get("invoiceLineNumber") for i in items] == ["1", "5"]   # the agreed lines; a disputed or duplicate line is never invoiced
    assert [c.tag for c in items[0]][:4] == ["UnitOfMeasure", "UnitPrice", "InvoiceDetailItemReference", "SubtotalAmount"]
    extr = {e.get("name"): e.text for e in items[1].findall("Extrinsic")}
    assert extr["knosMatch"] == "3-way" and extr["knosInvoiceLine"] == st["lines"][4]["invoice_line"] and extr["knosGoodsReceivedNote"].startswith("grn_")
    summary = root.find("Request/InvoiceDetailRequest/InvoiceDetailSummary")
    assert [c.tag for c in summary] == ["SubtotalAmount", "Tax", "NetAmount"] and summary.find("NetAmount/Money").text == "160.00" and summary.find("NetAmount/Money").get("currency") == "USD"
    assert "SharedSecret" not in text                                # a secret is never written into a file
    odd = {**st, "invoice": 'A&B "<1>"'}
    odd["sha256"] = statement.digest(odd)
    assert 'invoiceID="A&amp;B &quot;&lt;1&gt;&quot;"' in exports.cxml(odd) and ET.fromstring(exports.cxml(odd).split("\n", 2)[2].encode()) is not None
    # what is said of each new file: which parts were seen in a published sample, and that nothing imported it
    assert exports.UNVERIFIED in exports.STATEMENT_MORE["ariba"]["unverified"] and "read 2026-10-07" in exports.STATEMENT_MORE["ariba"]["confirmed"]
    assert exports.label("ariba") == exports.label("match") == exports.LABEL and "NOT the page's" in exports.FORMATS["coupa"]["unverified"]


def test_the_command_writes_both(tmp_path):
    from typer.testing import CliRunner
    app = typer.Typer()
    statement.register(app)
    st = T.sept()
    file = tmp_path / "ap-statement.json"
    file.write_bytes(statement.canonical(st))
    (tmp_path / "ap-statement.status.json").write_bytes(statement.canonical(noted()))
    cli = CliRunner(mix_stderr=False) if "mix_stderr" in CliRunner.__init__.__code__.co_varnames else CliRunner()
    for fmt, want in golden().items():
        kind = fmt.split(".")[1]
        out = tmp_path / fmt
        got = cli.invoke(app, ["statement", "export", str(file), "--format", kind, "--out", str(out), "--supplier-id", "AN01000000001", "--buyer-id", "AN02000000002"])
        assert got.exit_code == 0, got.output
        assert out.read_text(encoding="utf-8") == want


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        sys.exit("python tests/test_exports_match.py --write    writes tests/data/rails/sept.match.csv and sept.ariba.xml again")
    DATA.mkdir(parents=True, exist_ok=True)
    for name, text in golden().items():
        (DATA / name).write_text(text, encoding="utf-8", newline="")
        print(f"wrote {name}")
