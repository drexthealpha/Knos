"""The files a finance system imports (knos.exports), and the fixtures the site's functions are held to.

One statement (the mix of tests/_finance.py: an organisation's work orders and bounties in one month), one refs file,
and the file of every format kept in tests/data/finance: a change to a format is a change to a golden file, on
purpose. `python tests/test_exports.py --write` writes them again. tests/web/finance.mjs gives the same statement to
web/finance_data.js and compares the bytes.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import _finance as fin
from knos import audit, exports

ROOT = Path(__file__).resolve().parents[1]


def statement(events=None) -> tuple[dict, list[dict], str]:
    scope, rows, _sums, head, _n = audit.parse(audit.export(fin.mix() if events is None else events, fin.ACME, "csv", **fin.SEPT))
    return scope, rows, head


def golden() -> dict[str, str]:
    """Every file of tests/data/finance that is made from the mix: {name: text}."""
    scope, rows, head = statement()
    refs = audit.read_refs(fin.REFS)
    dump = lambda doc: json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"       # noqa: E731
    out = {"statement_mix.csv": audit.export(fin.mix(), fin.ACME, "csv", **fin.SEPT), "statement_mix.json": audit.export(fin.mix(), fin.ACME, "json", **fin.SEPT),
           "statement_bounties.csv": audit.export(fin.bounties(), fin.ACME, "csv", **fin.SEPT), "refs.csv": fin.REFS, "extras.json": dump(fin.extras()),
           "options.json": dump(fin.OPTIONS), "records_mix.json": dump(audit.records_of(rows, refs, fin.extras()["receipts"])),
           "records_mix_chain_only.json": dump(audit.records_of(rows))}
    for fmt in exports.FORMATS:
        out[f"{fmt}.csv"] = exports.write(fmt, scope, rows, head, refs, fin.OPTIONS)
    return out


@pytest.mark.parametrize("name", sorted(golden()))
def test_every_file_is_the_golden_file_byte_for_byte(name):
    assert (fin.DATA / name).read_bytes() == golden()[name].encode("utf-8"), f"{name} changed: if it was meant, python tests/test_exports.py --write"


def table(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_one_line_per_accepted_deliverable_and_supplier_and_nothing_for_what_was_not_accepted():
    scope, rows, head = statement()
    found = exports.bills(scope, rows, head, audit.read_refs(fin.REFS))
    accepted = [r for r in audit.records_of(rows) if r["acceptance"]["accepted"]]
    assert len(accepted) == 8 and len(found) == 9                                   # the arbiter's split is one deliverable and two suppliers
    assert [b["deliverable"] for b in found].count("OrdD:FD:0") == 2 and len({b["bill_no"] for b in found}) == 9
    assert not {"OrdE:FE:0", "OrdF:FF:0", "OrdB:FB:-"} & {b["deliverable"] for b in found}       # expired, open, the rest that went back
    assert sum(b["amount_units"] for b in found) == sum(r["commercial"]["amount_units"] for r in accepted) == 398_500_000
    assert all(len(b["bill_no"]) == 16 and b["bill_no"].startswith("KNOS-") and b["statement_head"] == head for b in found)
    a = found[0]
    assert (a["deliverable"], a["supplier"], a["date"], a["amount"], a["invoice_ref"], a["status"]) == \
        ("OrdA:FA:0", "gh:8001", "2026-09-03", "100.00", "PO-4411 line 2", "paid on devnet (test money)")
    assert a["memo"] == (f"TEST MONEY (devnet test USDC): not a payable | paid on devnet (test money) | Knos statement sha256:{head} | "
                         "receipt https://explorer.solana.com/tx/PA?cluster=devnet | deliverable OrdA:FA:0 | ref PO-4411 line 2")
    outside = next(b for b in found if b["deliverable"] == "OrdB:FB:12")
    assert outside["status"] == "paid outside Knos" and not outside["memo"].startswith("TEST MONEY")
    held = next(b for b in found if b["status"] == "payable")                        # accepted, held for a wallet: owed, so it is a line
    assert (held["supplier"], held["amount"], held["record"], held["receipt"]) == ("gh:8006", "10.00", "bounty", "https://explorer.solana.com/tx/JH3?cluster=devnet")
    reverted = next(b for b in found if b["status"] == "reverted")
    assert (reverted["amount"], reverted["correction"]) == ("160.00", "credit 40000000")


def test_each_product_gets_its_own_column_names_and_formats():
    scope, rows, head = statement()
    refs = audit.read_refs(fin.REFS)
    files = {fmt: table(exports.write(fmt, scope, rows, head, refs, fin.OPTIONS)) for fmt in exports.FORMATS}
    ns = files["netsuite"]
    assert tuple(ns[0]) == exports.NETSUITE and ns[0][:4] == ["External ID", "Vendor", "Date", "Reference No."] and len(ns) == 10
    assert ns[1][:5] == [ns[1][0], "gh:8001", "9/3/2026", ns[1][0], "USD"] and ns[1][6:8] == ["6100 Contract engineering", "100.00"]
    assert f"Knos statement sha256:{head}" in ns[1][5] and "receipt https://explorer.solana.com/tx/PA?cluster=devnet" in ns[1][5]
    qb = files["quickbooks"]
    assert qb[0][:5] == ["Bill no.", "Supplier", "Bill Date", "Due Date", "Account"] and qb[1][2] == qb[1][3] == "3/9/2026" and qb[1][6] == "100.00"
    assert head in qb[1][8] and len(qb) == 10
    coupa = files["coupa"]
    assert coupa[0][0] == "Invoice" and coupa[1][0] == "Invoice Line" and coupa[0][1] == coupa[1][1] == "Invoice Number"
    assert [r[0] for r in coupa[2:]] == ["Invoice", "Invoice Line"] * 9 and all(len(r) == len(coupa[0 if r[0] == "Invoice" else 1]) for r in coupa)
    assert coupa[2][5] == "2026-09-03" and coupa[2][21] == "1000" and head in coupa[2][15] and coupa[3][6] == "100.00" and coupa[3][9] == "PO-4411 line 2"
    sap = files["sap"]
    assert sap[0][:5] == ["Invoice ID", "Company Code", "Transaction", "Invoicing Party", "Reference"] and sap[1][1] == "1000" and sap[1][5] == "20260903"
    assert all(len(r[4]) <= 16 and len(r[8]) <= 25 and len(r[12]) <= 50 and len(r[16]) <= 18 for r in sap[1:]) and sap[1][12] == f"Knos {head[:16]} tx PA"
    # another date format, and the defaults when no option is given
    assert table(exports.write("netsuite", scope, rows, head, None, {"date_format": "DD/MM/YYYY"}))[1][2] == "03/09/2026"
    assert table(exports.write("netsuite", scope, rows, head))[1][6] == exports.DEFAULTS["account"]
    assert (exports.decimal(19_500_000), exports.decimal(404_999), exports.decimal(7), exports.decimal(100 * fin.U)) == ("19.50", "0.404999", "0.000007", "100.00")
    assert (exports.day("2026-09-03", "M/D/YYYY"), exports.day("2026-12-25", "DD.MM.YYYY"), exports.day("2026-09-03", "YYYYMMDD")) == ("9/3/2026", "25.12.2026", "20260903")
    with pytest.raises(audit.Refused):
        exports.write("xero", scope, rows, head)
    # what could not be confirmed from the product's own page is said, per format, where the command prints it
    assert all(f["source"] and f["confirmed"] for f in exports.FORMATS.values())
    assert exports.UNVERIFIED in exports.FORMATS["sap"]["unverified"] and exports.UNVERIFIED in exports.FORMATS["coupa"]["unverified"]
    assert exports.FORMATS["generic"]["unverified"] == ""


def test_the_generic_file_gives_the_statement_back_and_the_same_hash():
    scope, rows, head = statement()
    refs = audit.read_refs(fin.REFS)
    text = exports.write("generic", scope, rows, head, refs, fin.OPTIONS)
    assert text.splitlines()[0] == "knos.finance-export,version,1,generic"
    back = exports.statement_of(text)
    assert back == audit.export(fin.mix(), fin.ACME, "csv", **fin.SEPT) and audit.verify(back) == [] and audit.parse(back)[3] == head
    # and round again: the statement it carries makes the same generic file
    scope2, rows2, _sums, head2, _n = audit.parse(back)
    assert exports.write("generic", scope2, rows2, head2, refs, fin.OPTIONS) == text
    lines = [dict(zip(exports.GENERIC, c)) for c in table(text)[2:] if c[0] not in ("statement", "total", "head")]       # the deliverable lines
    assert len(lines) == 9 and lines[0]["deliverable"] == "OrdA:FA:0" and all(r["statement_head"] == head for r in lines)
    # a line edited in the carried statement is found; a file cut short is refused
    assert any("does not follow" in s for s in audit.verify(exports.statement_of(text.replace('""paid_units"":""100000000""', '""paid_units"":""100000001""', 1))))
    for wrong in ("", "a,b\n", text.split("\nstatement,", 1)[0] + "\n", text.replace("version,1,generic", "version,9,generic", 1)):
        with pytest.raises(audit.Refused):
            exports.statement_of(wrong)
    # the same statement and refs give the same bytes; the refs are the party's own and change no hash
    assert exports.write("generic", scope, rows, head, refs, fin.OPTIONS) == text
    assert audit.parse(exports.statement_of(exports.write("generic", scope, rows, head)))[3] == head
    # an owner with nothing: every format is its header and no line
    empty = audit.parse(audit.export(fin.mix(), 4242, "csv", **fin.SEPT))
    assert [len(table(exports.write(f, empty[0], empty[1], empty[3]))) for f in exports.FORMATS] == [1, 1, 2, 1, 3]


def test_a_statement_of_version_1_exports_too():
    scope, rows, _sums, head, _n = audit.parse((fin.DATA / "audit_v1.csv").read_text(encoding="utf-8"))
    found = exports.bills(scope, rows, head)
    # version 1 does not say each payee's share: a deliverable with one supplier is a line, a split is not
    assert [b["deliverable"] for b in found] == ["OrdA:FA:0", "OrdB:FB:11", "OrdB:FB:12", "OrdC:FC:0"]
    assert audit.parse(exports.statement_of(exports.write("generic", scope, rows, head)))[3] == head


def test_the_sites_functions_make_the_same_bytes():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([node, str(ROOT / "tests" / "web" / "finance.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
    assert "FAIL" not in done.stdout and done.stdout.count("ok  ") >= 20


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        sys.exit("python tests/test_exports.py --write    writes tests/data/finance again from tests/_finance.py")
    fin.DATA.mkdir(parents=True, exist_ok=True)
    for name, text in golden().items():
        (fin.DATA / name).write_text(text, encoding="utf-8", newline="")
        print(f"wrote {name}")
