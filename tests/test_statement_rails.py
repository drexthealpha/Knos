"""Paying an approved statement by bank (src/knos/rails.py, `knos statement pay --rail bank`, `knos statement status`).

The statement is September's of tests/test_statement.py: two agreed lines, one disputed, one without enough evidence,
one duplicate. tests/data/rails/vectors.json holds each case's statement, status, payer and the payment file both the
Python and web/rails.js must write, byte for byte (tests/web/rails.mjs); `python tests/test_statement_rails.py --write`
writes it again. Nothing asks a bank or the network. The file is held to the structure of the message definition by
knos.rails.check, which is hand-written: no official schema file is in the repository, and no bank has taken the file."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import typer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_statement as T                                     # noqa: E402

from knos import billing, ids, rails, statement                 # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data" / "rails"
NS = "{urn:iso:std:iso:20022:tech:xsd:pain.001.001.09}"
PAYEES = {"Acme Agents": {"name": "Acme Agents", "account": "GB82 WEST 1234 5698 7654 32", "bic": ""},
          "Zeta Ünion & Co <Ltd>": {"name": "Zeta Ünion & Co <Ltd>", "account": "021000021123456789", "bic": "chasus33"}}
PAYER = {"name": "Northwind Ltd", "account": "DE89 3704 0044 0532 0130 00", "bic": "DEUTDEFF", "on": "2026-10-02", "payees": PAYEES}
TWO = "pr,amount,supplier\nacme/app#1,100.00,Acme Agents\nacme/app#4,60.10,Zeta Ünion & Co <Ltd>\nacme/app#7,45.50,Acme Agents\nacme/app#2,250.00,Acme Agents\n"


def approved(st: dict) -> dict:
    return statement.approve(st, None, "Dana Reyes", "finance controller", "2026-10-01")


def two() -> dict:
    return statement.from_shadow({"invoice": TWO, "answers": T.BOOK}, {**T.META, "invoice": "INV-2026-09-B"})


def returned() -> tuple[dict, dict]:
    """September, instructed, and the bank sent the transfer back: the lines are payable again."""
    st = T.sept()
    s, _xml, found = rails.instruct(st, approved(st), PAYER)
    report = f"end_to_end_id,status,reference,date,reason\n{found[0]['end_to_end']},RJCT,,2026-10-03,AC04 closed account\n".encode()
    return st, rails.apply(st, s, rails.read_status(report), "2026-10-04")[0]


def vectors() -> list[dict]:
    out = []
    for name, st, status, payer in (("one supplier, two agreed lines", T.sept(), approved(T.sept()), PAYER),
                                    ("two suppliers, an account that is no IBAN, a name a bank would not take", two(), approved(two()),
                                     {**PAYER, "account": "12345678", "bic": "", "execute": "2026-10-06", "created": "2026-10-02T09:30:00+02:00"}),
                                    ("the second file after the bank returned the first", *returned(), {**PAYER, "on": "2026-10-05"})):
        xml, found, msg = rails.pain001(st, status, payer)
        out.append({"name": name, "statement": st, "status": status, "payer": payer, "xml": xml, "transfers": found, "message": msg})
    return out


def test_the_payment_files_are_the_kept_ones_byte_for_byte():
    kept = json.loads((DATA / "vectors.json").read_text(encoding="utf-8"))
    assert kept == json.loads(json.dumps(vectors())), "the payment file changed: if it was meant, python tests/test_statement_rails.py --write"
    assert [len(v["transfers"]) for v in kept] == [1, 2, 1]


def test_one_transfer_per_supplier_for_the_agreed_approved_lines_and_nothing_else():
    st = T.sept()
    with pytest.raises(rails.Refused, match="agreed, approved and still payable"):
        rails.pain001(st, None, PAYER)                                             # agreed, and nobody approved: nothing is instructed
    xml, found, msg = rails.pain001(st, approved(st), PAYER)
    assert rails.check(xml) == [] and len(found) == 1
    t = found[0]
    agreed = [ln["invoice_line"] for ln in st["lines"] if ln["state"] == "agreed"]
    assert t["lines"] == agreed and len(agreed) == 2 and t["amount"] == "160.00" and t["currency"] == "USD"      # 100.00 + 60.00; 250.00, 80.00 and the duplicate stay out
    assert ids.kind_of(t["end_to_end"]) == "settlement" and t["end_to_end"] == ids.settlement(f"{st['sha256']}:Acme Agents", "bank", ",".join(agreed))
    root = ET.fromstring(xml.encode())
    one = lambda tag: [e.text for e in root.iter(NS + tag)]                              # noqa: E731
    assert one("EndToEndId") == [t["end_to_end"]] and one("NbOfTxs") == ["1", "1"] and one("CtrlSum") == ["160.00", "160.00"] and one("MsgId") == [msg]
    assert len(msg) == 32 and one("PmtInfId") == [msg + "-1"] and one("IBAN") == ["DE89370400440532013000", "GB82WEST12345698765432"] and one("BICFI") == ["DEUTDEFF"]
    said = one("Ustrd")
    assert said[0] == f"KNOS {st['sha256']} INV INV-2026-09" and said[1].split() == agreed and all(len(u) <= 140 for u in said)
    assert next(root.iter(NS + "InstdAmt")).get("Ccy") == "USD" and one("Dt") == ["2026-10-02"] and one("CreDtTm") == ["2026-10-02T00:00:00Z"]
    for line in (ln["invoice_line"] for ln in st["lines"] if ln["state"] != "agreed"):
        assert line not in xml
    # two suppliers: two transfers, in the statement's order; a name is cut to what a bank's file takes; an account that is no IBAN
    st2 = two()
    xml2, found2, _ = rails.pain001(st2, approved(st2), {**PAYER, "account": "12345678", "bic": ""})
    assert [(f["supplier"], f["amount"], len(f["lines"])) for f in found2] == [("Acme Agents", "145.50", 2), ("Zeta Ünion & Co <Ltd>", "60.10", 1)]
    assert rails.check(xml2) == [] and "<Nm>Zeta .nion . Co .Ltd.</Nm>" in xml2 and "<CtrlSum>205.60</CtrlSum>" in xml2
    assert "<DbtrAcct><Id><Othr><Id>12345678</Id></Othr></Id></DbtrAcct>" in xml2 and "<DbtrAgt><FinInstnId><Othr><Id>NOTPROVIDED</Id></Othr></FinInstnId></DbtrAgt>" in xml2
    assert xml2.index("<CdtrAgt><FinInstnId><BICFI>CHASUS33</BICFI>") < xml2.index("<Cdtr><Nm>Zeta")       # the creditor's agent comes before the creditor
    assert len({f["end_to_end"] for f in found2}) == 2 and rails.pain001(st2, approved(st2), {**PAYER, "account": "12345678", "bic": ""})[0] == xml2


def test_what_cannot_be_instructed_is_refused_in_words():
    st, s = T.sept(), approved(T.sept())
    for payer, words in (({**PAYER, "account": "DE89370400440532013001"}, "check digits are wrong"), ({**PAYER, "name": ""}, "names who pays"),
                         ({**PAYER, "payees": {}}, "No bank account is given for Acme Agents"), ({**PAYER, "bic": "DEUT"}, "a BIC is 8 or 11"),
                         ({**PAYER, "on": "2 October"}, "names its day"), ({**PAYER, "account": "no account!"}, "is neither")):
        with pytest.raises(rails.Refused, match=words):
            rails.pain001(st, s, payer)
    test = statement.from_shadow({"invoice": T.SEPT, "answers": T.BOOK}, {**T.META, "currency": "test USDC"})
    with pytest.raises(rails.Refused, match="Test money is paid on devnet"):                # a bank never moves test money
        rails.pain001(test, approved(test), PAYER)
    plain = statement.from_shadow({"invoice": T.SEPT, "answers": T.BOOK}, {**T.META, "currency": ""})
    with pytest.raises(rails.Refused, match="this statement states no currency. Test money"):      # said, not a quoted placeholder (web/rails.js the same)
        rails.pain001(plain, approved(plain), PAYER)
    assert rails.iban_ok("GB82WEST12345698765432") and rails.iban_ok("FR1420041010050500013M02606") and not rails.iban_ok("GB83WEST12345698765432")
    assert rails.text("  Ünïcode & <tags>\n", 140) == ".n.code . .tags." and rails.text("x" * 200, 35) == "x" * 35


def test_the_checker_finds_what_is_not_the_messages_structure():
    st = T.sept()
    xml = rails.pain001(st, approved(st), PAYER)[0]
    assert rails.check(xml) == []
    for old, new, words in (("<NbOfTxs>1</NbOfTxs>\n      <CtrlSum>160.00</CtrlSum>\n      <InitgPty>", "<NbOfTxs>2</NbOfTxs>\n      <CtrlSum>160.00</CtrlSum>\n      <InitgPty>", "NbOfTxs says 2"),
                            ("<CtrlSum>160.00</CtrlSum>\n      <ReqdExctnDt>", "<CtrlSum>160.01</CtrlSum>\n      <ReqdExctnDt>", "CtrlSum says 160.01"),
                            ("pain.001.001.09", "pain.001.001.03", "not in the namespace"), ("      <PmtMtd>TRF</PmtMtd>\n", "", "PmtMtd: missing"),
                            ("<PmtMtd>TRF</PmtMtd>", "<PmtMtd>CHK</PmtMtd>", "not what the definition allows"), ('Ccy="USD"', 'Ccy="usd"', "three capital letters"),
                            ("GB82WEST", "GB83WEST", "check digits"), ("<ReqdExctnDt><Dt>2026-10-02</Dt></ReqdExctnDt>", "<ReqdExctnDt>2026-10-02</ReqdExctnDt>", "ReqdExctnDt/Dt: missing"),
                            ("<InitgPty>", "<Surprise/><InitgPty>", "not a child of GrpHdr"), ("</Document>", "", "not well-formed"),
                            ('<?xml version="1.0" encoding="UTF-8"?>', '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "b">]>', "document type")):
        assert old in xml and any(words in w for w in rails.check(xml.replace(old, new, 1))), words
    moved = xml.replace("      <PmtMtd>TRF</PmtMtd>\n", "").replace("      <ReqdExctnDt>", "      <PmtMtd>TRF</PmtMtd>\n      <ReqdExctnDt>")
    assert any("out of order" in w for w in rails.check(moved))                         # every element there, one in the wrong place
    twice = xml.replace("      <CdtTrfTxInf>", "      <CdtTrfTxInf>", 1)
    block = xml[xml.index("      <CdtTrfTxInf>"):xml.index("    </PmtInf>")]
    assert any("share an end-to-end id" in w for w in rails.check(twice.replace(block, block + block)))
    xmllint = shutil.which("xmllint")
    if xmllint:                                                 # well-formed by another program's reading too, when one is installed
        done = subprocess.run([xmllint, "--noout", "--nonet", "-"], input=xml, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
        assert done.returncode == 0, done.stderr


PAIN002 = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.10"><CstmrPmtStsRpt>
<GrpHdr><MsgId>BANK-1</MsgId><CreDtTm>2026-10-03T08:00:00Z</CreDtTm></GrpHdr>
<OrgnlGrpInfAndSts><OrgnlMsgId>{msg}</OrgnlMsgId><OrgnlMsgNmId>pain.001.001.09</OrgnlMsgNmId></OrgnlGrpInfAndSts>
<OrgnlPmtInfAndSts><OrgnlPmtInfId>{msg}-1</OrgnlPmtInfId>
<TxInfAndSts><OrgnlEndToEndId>{a}</OrgnlEndToEndId><TxSts>ACSC</TxSts><AccptncDtTm>2026-10-03T07:59:00Z</AccptncDtTm><AcctSvcrRef>BK-7781</AcctSvcrRef></TxInfAndSts>
<TxInfAndSts><OrgnlEndToEndId>{b}</OrgnlEndToEndId><TxSts>RJCT</TxSts><StsRsnInf><Rsn><Cd>AC04</Cd></Rsn><AddtlInf>Closed account</AddtlInf></StsRsnInf></TxInfAndSts>
<TxInfAndSts><OrgnlEndToEndId>stl_000000000000000000000000</OrgnlEndToEndId><TxSts>ACSC</TxSts></TxInfAndSts>
</OrgnlPmtInfAndSts></CstmrPmtStsRpt></Document>
"""


def test_the_banks_answer_marks_lines_paid_or_payable_again_and_reading_it_twice_changes_nothing():
    st = two()
    s, xml, found = rails.instruct(st, approved(st), PAYER)
    event = s["events"][-1]
    assert event["type"] == "instruction" and event["sha256"] == hashlib.sha256(xml.encode()).hexdigest() and event["amount"] == "205.60"
    with pytest.raises(rails.Refused, match="nothing to instruct"):                    # a line a file already names is never named again
        rails.pain001(st, s, PAYER)
    assert [r["payment"] for r in statement.lines_now(st, s)][:3] == ["payable"] * 3    # instructed is not paid
    report = PAIN002.format(msg=event["message"], a=found[0]["end_to_end"], b=found[1]["end_to_end"]).encode()
    rows = rails.read_status(report)
    assert [(r["result"], r["code"], r["reason"], r["reference"], r["on"]) for r in rows] == [("paid", "ACSC", "", "BK-7781", "2026-10-03"),
                                                                                           ("failed", "RJCT", "AC04 Closed account", "", ""), ("paid", "ACSC", "", "", "")]
    after, said = rails.apply(st, s, rows, "2026-10-04")
    now = {r["supplier"] + str(r["line"]): r for r in statement.lines_now(st, after)}
    assert (now["Acme Agents1"]["payment"], now["Acme Agents3"]["payment"], now["Zeta Ünion & Co <Ltd>2"]["payment"]) == ("paid_outside", "paid_outside", "payable")
    assert now["Acme Agents1"]["settlement"] == found[0]["end_to_end"] == now["Acme Agents3"]["settlement"]      # the id on the bank's own statement
    assert now["Zeta Ünion & Co <Ltd>2"]["why"] == "the bank returned this payment: RJCT AC04 Closed account"
    assert "paid, 145.50 USD to Acme Agents; 2 lines recorded" in said[0] and "returned by the bank (RJCT AC04 Closed account): payable again" in said[1]
    assert "no payment file of this statement names it; skipped" in said[2]
    again, said2 = rails.apply(st, after, rows, "2026-10-09")
    assert again == after and all("already recorded" in w or "skipped" in w for w in said2)
    # the returned line goes into the next file, under another end-to-end id; the paid ones never again
    xml2, found2, _ = rails.pain001(st, after, {**PAYER, "on": "2026-10-05"})
    assert [(f["supplier"], f["amount"]) for f in found2] == [("Zeta Ünion & Co <Ltd>", "60.10")] and found2[0]["end_to_end"] != found[1]["end_to_end"] and rails.check(xml2) == []
    # the CSV and the PDF say the file, the payment and the return
    text = statement.as_csv(st, after)
    assert f"payment file,2026-10-02,{event['message']},\"2 transfers by bank (pain.001.001.09), 205.60 USD, to pay on 2026-10-02\",sha256 {event['sha256']}" in text
    assert "paid outside Knos by bank, reference BK-7781" in text and "returned by the bank (RJCT AC04 Closed account): payable again" in text
    assert statement.as_pdf(st, after).startswith(b"%PDF")
    # a CSV answer; a status for the whole file; a pending one; what is no answer
    csv_rows = rails.read_status(f"end_to_end_id,status,reference,date,reason\n{found[0]['end_to_end']},paid,REF9,2026-10-03,\n{found[1]['end_to_end']},pending,,,\n".encode())
    by_csv, said3 = rails.apply(st, s, csv_rows, "2026-10-04")
    assert [e["reference"] for e in by_csv["events"] if e["type"] == "settlement"] == ["REF9", "REF9"] and "still with the bank (pending); nothing recorded" in said3[1]
    whole = ("<Document><CstmrPmtStsRpt><OrgnlGrpInfAndSts><OrgnlMsgId>" + event["message"] + "</OrgnlMsgId><GrpSts>RJCT</GrpSts><StsRsnInf><Rsn><Cd>FF01</Cd></Rsn></StsRsnInf>"
             "</OrgnlGrpInfAndSts></CstmrPmtStsRpt></Document>").encode()
    all_back = rails.apply(st, s, rails.read_status(whole), "2026-10-04")[0]
    assert [e["state"] for e in all_back["events"] if e["type"] == "settlement"] == ["payable"] * 3 and all_back["events"][-1]["returned"] == "RJCT FF01"
    for wrong, words in ((b"<Document/>", "no CstmrPmtStsRpt"), (b"a,b\n1,2\n", "has the columns"), (b"end_to_end_id,status\nx,maybe\n", "is not a status"),
                         (b"<!DOCTYPE x [<!ENTITY a 'b'>]><x/>", "document type"), (b"<x", "not well-formed"), (b"\xff\xfe", "not UTF-8")):
        with pytest.raises(rails.Refused, match=words):
            rails.read_status(wrong)
    with pytest.raises(rails.Refused, match="No payment file was written"):
        rails.apply(st, approved(st), rows, "2026-10-04")


def acceptance(rows: list[dict]) -> str:
    return next(ln["amount"] for ln in billing.invoice({"plan": "none", "accepted": rows})["lines"] if ln["line"] == "acceptance")


def test_acceptance_is_charged_once_whichever_rail_pays():
    st = T.sept()
    first, last = (ln["invoice_line"] for ln in st["lines"] if ln["state"] == "agreed")
    s, _xml, found = rails.instruct(st, approved(st), PAYER)
    assert rails.accepted_rows(st, s) == [] and acceptance([]) == "0.00"               # instructed is not paid: nothing is charged yet
    paid = [{"end_to_end": found[0]["end_to_end"], "message": "", "result": "paid", "code": "ACSC", "reason": "", "reference": "BK-1", "on": "2026-10-03"}]
    bank, _ = rails.apply(st, s, paid, "2026-10-03")
    rows = rails.accepted_rows(st, bank)
    assert [(r["value"], r["on_chain"]) for r in rows] == [("100.00", False), ("60.00", False)] and acceptance(rows) == "0.48"       # 0.30% of 160.00
    assert rails.accepted_rows(st, rails.apply(st, bank, paid, "2026-10-08")[0]) == rows                                            # the bank's answer read twice
    # the same lines paid on the other rail: the same two deliverables, each once; the program took its fee, so none is charged off chain
    chain = statement.pay(st, statement.pay(st, approved(st), first, "chain", "TxOne", "2026-10-03"), last, "chain", "TxTwo", "2026-10-03")
    rows2 = rails.accepted_rows(st, chain)
    assert [r["deliverable"] for r in rows2] == [r["deliverable"] for r in rows] and all(r["on_chain"] for r in rows2) and acceptance(rows2) == "0.00"
    # one line by bank and, by mistake, on chain too: still one row for its deliverable, and no second fee off chain
    both = statement.pay(st, bank, first, "chain", "TxOne", "2026-10-04")
    rows3 = rails.accepted_rows(st, both)
    assert len(rows3) == 2 and [r["on_chain"] for r in rows3] == [True, False] and acceptance(rows3) == "0.18"                      # 0.30% of 60.00 only
    # a transfer the bank sent back is not paid, so not charged
    assert rails.accepted_rows(*returned()) == []


def test_the_commands_write_the_file_read_the_answer_and_keep_the_old_path(tmp_path):
    from typer.testing import CliRunner
    app = typer.Typer()
    statement.register(app)
    cli = CliRunner()
    told = lambda got: got.output + str(got.exception or "")                           # noqa: E731  (a refusal is the command line's Stop)
    st = T.sept()
    file = tmp_path / "ap-statement.json"
    file.write_bytes(statement.canonical(st))
    (tmp_path / "payees.csv").write_text("supplier,name,account,bic\nAcme Agents,Acme Agents,GB82 WEST 1234 5698 7654 32,\n", encoding="utf-8")
    bank = ["statement", "pay", str(file), "--rail", "bank", "--payer-name", "Northwind Ltd", "--payer-account", "DE89370400440532013000", "--payer-bic", "DEUTDEFF",
            "--payees", str(tmp_path / "payees.csv"), "--on", "2026-10-02"]
    got = cli.invoke(app, bank)
    assert got.exit_code != 0 and "agreed, approved and still payable" in told(got) and not (tmp_path / "ap-statement.pain001.xml").exists()
    assert cli.invoke(app, ["statement", "approve", str(file), "--agreed", "--by", "Dana Reyes", "--role", "finance controller", "--on", "2026-10-01"]).exit_code == 0
    got = cli.invoke(app, bank)
    assert got.exit_code == 0, got.output
    xml = (tmp_path / "ap-statement.pain001.xml").read_text(encoding="utf-8")
    assert xml == rails.pain001(st, approved(st), PAYER)[0] and "No money moved" in got.output and "1 transfer (pain.001.001.09)" in got.output
    assert cli.invoke(app, bank).exit_code != 0                                            # not twice
    e2e = rails.transfers(st, approved(st))[0]["end_to_end"]
    (tmp_path / "bank.csv").write_text(f"end_to_end_id,status,reference,date,reason\n{e2e},ACSC,BK-1,2026-10-03,\n", encoding="utf-8")
    got = cli.invoke(app, ["statement", "status", str(file), "--from", str(tmp_path / "bank.csv"), "--on", "2026-10-04"])
    assert got.exit_code == 0 and "paid, 160.00 USD to Acme Agents; 2 lines recorded" in got.output and "Owed:" in got.output and "0 lines, 0.00 USD payable" in got.output
    status = json.loads((tmp_path / "ap-statement.status.json").read_text(encoding="utf-8"))
    assert [e["type"] for e in status["events"]] == ["approval", "instruction", "settlement", "settlement"]
    assert (tmp_path / "ap-statement.csv").read_bytes() == statement.as_csv(st, status).encode() and file.read_bytes() == statement.canonical(st)
    assert "already recorded" in cli.invoke(app, ["statement", "status", str(file), "--from", str(tmp_path / "bank.csv")]).output
    assert cli.invoke(app, ["statement", "verify", str(file)]).exit_code == 0
    # the existing paths: a line recorded with the payer's own reference; --rail usdc is the devnet record
    other = tmp_path / "b" / "ap-statement.json"
    other.parent.mkdir()
    other.write_bytes(statement.canonical(st))
    line = st["lines"][0]["invoice_line"]
    got = cli.invoke(app, ["statement", "pay", str(other), "--line", line, "--method", "bank", "--ref", "BACS 77120", "--on", "2026-10-02"])
    assert got.exit_code == 0 and "paid outside Knos (bank, reference BACS 77120" in got.output
    got = cli.invoke(app, ["statement", "pay", str(other), "--line", st["lines"][4]["invoice_line"], "--rail", "usdc", "--ref", "5Yd1testtransaction", "--on", "2026-10-03"])
    assert got.exit_code == 0 and "devnet demonstration (chain, reference 5Yd1testtransaction" in got.output
    assert json.loads((other.parent / "ap-statement.status.json").read_text(encoding="utf-8")) == {**T.status(), "events": T.status()["events"][1:]}
    for args, words in ((["--rail", "wire"], "--rail is bank or usdc"), (["--method", "bank"], "--line and --ref")):
        got = cli.invoke(app, ["statement", "pay", str(other), *args])
        assert got.exit_code != 0 and words in told(got)


def test_the_sites_function_writes_the_same_bytes_and_its_view_holds():
    """tests/web/rails.mjs: the vectors in node, then the view in headless Chromium (that part skips itself, in words,
    where there is no playwright package or no browser)."""
    import os
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    env = dict(os.environ)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env and Path("/opt/pw-browsers").is_dir():       # where this project's machines keep Chromium
        env["PLAYWRIGHT_BROWSERS_PATH"] = "/opt/pw-browsers"
    done = subprocess.run([node, str(ROOT / "tests" / "web" / "rails.mjs")], env=env, capture_output=True, text=True, encoding="utf-8", timeout=170, check=False)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]
    assert "FAIL" not in done.stdout and "all passed" in done.stdout and done.stdout.count("ok  ") >= 20


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        sys.exit("python tests/test_statement_rails.py --write    writes tests/data/rails/vectors.json again")
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "vectors.json").write_text(json.dumps(vectors(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="")
    print("wrote vectors.json")


def test_the_site_words_a_payment_file_and_a_returned_payment_as_the_python_does(tmp_path):
    """web/finance_data.js `statementCells` against statement.cells, on a status that holds an instruction and a return."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    st, s = returned()
    kinds = [row[0] for row in statement.cells(st, s)["events"]]
    assert "payment file" in kinds and any("returned by the bank" in row[3] for row in statement.cells(st, s)["events"])
    (tmp_path / "in.json").write_text(json.dumps({"st": st, "status": s}), encoding="utf-8")
    script = ("import { readFileSync } from 'node:fs'; import { pathToFileURL } from 'node:url';"
              "const m = await import(pathToFileURL(process.argv[2]).href), d = JSON.parse(readFileSync(process.argv[3], 'utf8'));"
              "process.stdout.write(JSON.stringify({ events: (await m.statementCells(d.st, d.status)).events, csv: await m.statementCsv(d.st, d.status) }));")
    (tmp_path / "cells.mjs").write_text(script, encoding="utf-8")
    done = subprocess.run([node, str(tmp_path / "cells.mjs"), str(ROOT / "web" / "finance_data.js"), str(tmp_path / "in.json")],
                          capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    assert got["events"] == statement.cells(st, s)["events"] and got["csv"] == statement.as_csv(st, s)
