"""The statement for accounts payable (src/knos/statement.py), its PDF (src/knos/pdf.py) and its exports.

One made-up supplier, two invoices. September's has every line state: an agreed line, a disputed one (a failed check),
one without enough evidence (no check ran), and the first line billed again. October's bills the deliverable September
agreed, through another pull request: a duplicate across two statements. GitHub is BOOK, by path; nothing asks the
network. tests/data/statement holds what the browser must give too (tests/web/statement.mjs);
`python tests/test_statement.py --write` writes it again."""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import typer

from knos import exports, ids, pdf, shadow, statement

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data" / "statement"


def sha1(n: int) -> str:
    return f"{n:040x}"


def pull(n: int, body: str, day: int) -> dict:
    return {"number": n, "body": body, "merged_at": f"2026-09-{day:02d}T10:00:00Z", "merge_commit_sha": sha1(1000 + n), "head": {"sha": sha1(n)},
            "base": {"ref": "main", "repo": {"full_name": "acme/app", "default_branch": "main"}}}


def checks(n: int, runs: list) -> dict:
    return {f"repos/acme/app/commits/{sha1(n)}/check-runs?per_page=100&page=1": {"total_count": len(runs), "check_runs": runs},
            f"repos/acme/app/commits/{sha1(n)}/status?per_page=100&page=1": {"state": "x", "total_count": 0, "statuses": []}}


def run(name: str, conclusion: str, n: int) -> dict:
    return {"name": name, "status": "completed", "conclusion": conclusion, "html_url": f"https://github.com/acme/app/actions/runs/{n}/job/{n}"}


BOOK: dict = {
    "repos/acme/app/pulls/1": pull(1, "Adds the parser. All tests pass.\n\nFixes #10", 3), **checks(1, [run("test", "success", 11)]),
    "repos/acme/app/pulls/2": pull(2, "CI is green.\n\nCloses #11", 5), **checks(2, [run("test", "failure", 21), run("lint", "success", 22)]),
    "repos/acme/app/pulls/3": pull(3, "Tests pass.", 8), **checks(3, []),
    "repos/acme/app/pulls/4": pull(4, "Tests pass.", 12), **checks(4, [run("test", "success", 41)]),
    "repos/acme/app/pulls/6": pull(6, "Tests pass. A second go.\n\nFixes #10", 28), **checks(6, [run("test", "success", 61)]),
    "repos/acme/app/pulls/7": pull(7, "Tests pass.", 29), **checks(7, [run("test", "success", 71)]),
}
SEPT = "pr,amount,supplier\nacme/app#1,100.00,Acme Agents\nacme/app#2,250.00,Acme Agents\nacme/app#3,80.00,Acme Agents\nacme/app#1,100.00,Acme Agents\nacme/app#4,60.00,Acme Agents\n"
OCT = "pr,amount,supplier\nacme/app#6,100.00,Acme Agents\nacme/app#7,45.50,Acme Agents\n"
META = {"invoice": "INV-2026-09", "supplier": "", "buyer": "Northwind", "currency": "USD", "date": "2026-09-30"}


def sept(embed: bool = True) -> dict:
    return statement.from_shadow({"invoice": SEPT, "answers": BOOK}, META, (), embed)


def october() -> dict:
    return statement.from_shadow({"invoice": OCT, "answers": BOOK}, {**META, "invoice": "INV-2026-10", "date": "2026-10-31"}, [statement.billed_before(sept())])


def status() -> dict:
    """September approved, its first line paid by bank, its last recorded as a devnet demonstration."""
    st = sept()
    s = statement.approve(st, None, "Dana Reyes", "finance controller", "2026-10-01")
    s = statement.pay(st, s, st["lines"][0]["invoice_line"], "bank", "BACS 77120", "2026-10-02")
    return statement.pay(st, s, st["lines"][4]["invoice_line"], "chain", "5Yd1testtransaction", "2026-10-03")


def golden() -> dict[str, bytes]:
    st, s = sept(), status()
    out = {"sept.json": statement.canonical(st), "sept.status.json": statement.canonical(s), "sept.plain.csv": statement.as_csv(st).encode(),
           "sept.csv": statement.as_csv(st, s).encode(), "sept.pdf": statement.as_pdf(st, s), "october.json": statement.canonical(october()),
           "october.csv": statement.as_csv(october()).encode()}
    for fmt in exports.STATEMENT_FORMATS:
        out[f"sept.{fmt}.csv"] = exports.write_statement(fmt, st, s, {"account": "6100 Contract engineering"}).encode()
    # the goods-received note: of three lines with no receipt at hand, and of the last line recorded from its payment's receipt
    sys.path.insert(0, str(ROOT / "tests"))
    import _assurance
    for n in (0, 1, 3):
        out[f"sept.grn.{n + 1}.json"] = statement.canonical(statement.grn(st, s, st["lines"][n]["invoice_line"]))
    last = st["lines"][4]["invoice_line"]
    noted = statement.grn_record(st, s, last, "2026-10-04", _assurance.five("agreed", invoice_line=last, times=2), "PO-2026-0932")
    out.update({"sept.grn.status.json": statement.canonical(noted), "sept.grn.5.json": statement.canonical(statement.grn(st, noted, last)),
                "sept.grn.csv": statement.as_csv(st, noted).encode(), "sept.grn.generic.csv": exports.write_statement("generic", st, noted).encode()})
    return out


def sample() -> dict[str, bytes]:
    """The site's sample (web/statement_sample.json and its status): September with its evidence named, not carried."""
    st = sept(embed=False)
    s = statement.approve(st, None, "Dana Reyes", "finance controller", "2026-10-01")
    s = statement.pay(st, s, st["lines"][0]["invoice_line"], "bank", "BACS 77120", "2026-10-02")
    return {"statement_sample.json": statement.canonical(st), "statement_sample.status.json": statement.canonical(s)}


@pytest.mark.parametrize("name", sorted(sample()))
def test_the_sites_sample_is_the_statement_the_python_makes(name):
    assert (ROOT / "web" / name).read_bytes() == sample()[name], f"web/{name} changed: python tests/test_statement.py --write"


@pytest.mark.parametrize("name", sorted(golden()))
def test_every_file_is_the_kept_file_byte_for_byte(name):
    assert (DATA / name).read_bytes() == golden()[name], f"{name} changed: if it was meant, python tests/test_statement.py --write"


# ---- the lines ------------------------------------------------------------------------------------------------------

def test_one_invoice_has_all_four_states_each_with_its_ids_its_amount_and_why_in_words():
    st = sept()
    assert [ln["state"] for ln in st["lines"]] == ["agreed", "disputed", "insufficient_evidence", "duplicate", "agreed"]
    assert set(ln["state"] for ln in st["lines"]) == set(ids.LINE_STATES)
    assert st["totals"] == {"billed": {"lines": 5, "amount": "590.00"}, "agreed": {"lines": 2, "amount": "160.00"}, "disputed": {"lines": 1, "amount": "250.00"},
                            "duplicate": {"lines": 1, "amount": "100.00"}, "insufficient_evidence": {"lines": 1, "amount": "80.00"}}
    one, two, three, four, _five = st["lines"]
    for ln in st["lines"]:
        assert ids.kind_of(ln["deliverable"]) == "deliverable" and ids.kind_of(ln["invoice_line"]) == "invoice_line" and ln["settlement"] is None
        assert all(ids.kind_of(e) == "evaluation" for e in ln["evaluations"]) and (ln["why"] == "") == (ln["state"] == "agreed")
        assert re.fullmatch(r"[0-9a-f]{64}", ln["evidence_sha256"]) and ln["payment"] == ("payable" if ln["state"] == "agreed" else "held")
    assert one["deliverable"] == ids.deliverable("github:acme/app", "issue 10") and one["invoice_line"] == ids.invoice_line("Acme Agents", "INV-2026-09", 1)
    assert len(one["evaluations"]) == 1 and one["evidence"] == "https://github.com/acme/app/pull/1"
    assert two["why"] == "a check failed when this change was merged: test" and two["evidence"] == "https://github.com/acme/app/actions/runs/21/job/21"
    assert three["why"] == "the checks give no verdict: no check ran" and three["evaluations"] != []
    assert four["why"] == "billed twice on this invoice: same pull request as line 1" and four["duplicate_of"] == "line 1"
    assert four["deliverable"] == one["deliverable"] and four["invoice_line"] != one["invoice_line"] and four["evaluations"] == []
    assert len({ln["invoice_line"] for ln in st["lines"]}) == 5 and len({ln["deliverable"] for ln in st["lines"]}) == 4


def test_a_deliverable_an_earlier_statement_agreed_is_a_duplicate_on_the_next():
    first, second = sept(), october()
    again, new = second["lines"]
    assert again["deliverable"] == first["lines"][0]["deliverable"] and again["reference"] == "acme/app#6"        # another pull request, the same issue
    assert (again["state"], again["payment"], again["duplicate_of"]) == ("duplicate", "held", f"statement {first['sha256'][:12]} line 1")
    assert again["why"] == "already billed: invoice INV-2026-09 line 1 agreed this deliverable on 2026-09-30"
    assert new["state"] == "agreed" and second["totals"]["duplicate"] == {"lines": 1, "amount": "100.00"} and second["totals"]["agreed"]["amount"] == "45.50"
    assert second["prior"] == [{"sha256": first["sha256"], "invoice": "INV-2026-09", "date": "2026-09-30",
                                "deliverables": {ln["deliverable"]: {"line": ln["line"], "invoice_line": ln["invoice_line"]} for ln in first["lines"] if ln["state"] == "agreed"}}]
    assert statement.from_shadow({"invoice": OCT, "answers": BOOK}, META)["lines"][0]["state"] == "agreed"        # without the earlier statement nobody can know
    assert statement.verify(second) == (True, "same")                                                         # the earlier statement's part is inside this one
    with pytest.raises(statement.Refused, match="changed after it was made"):
        statement.billed_before({**first, "invoice": "INV-other"})


# ---- three forms that say the same ----------------------------------------------------------------------------------

def squeeze(text: str) -> str:
    return re.sub(r"\s+", "", text)


@pytest.mark.parametrize("with_status", [False, True])
def test_the_json_the_csv_and_the_pdf_say_the_same(with_status):
    st, s = sept(), status() if with_status else None
    c = statement.cells(st, s)
    table = list(csv.reader(io.StringIO(statement.as_csv(st, s))))
    assert table[0] == ["knos-statement", "1", st["sha256"]] and st["sha256"] == statement.digest(st)
    at = table.index(list(statement.HEAD))
    assert table[1:at] == c["top"] and table[at + 1:at + 1 + len(st["lines"])] == c["rows"]
    for ln, row in zip(statement.lines_now(st, s), c["rows"]):         # every cell of the CSV is the JSON's value, as text
        got = dict(zip(statement.HEAD, row))
        assert got == {"line": str(ln["line"]), "reference": ln["reference"], "supplier": ln["supplier"], "state": ids.LINE_WORDS[ln["state"]], "amount": ln["amount"],
                       "why": ln["why"], "deliverable": ln["deliverable"], "evaluations": " ".join(ln["evaluations"]), "invoice_line": ln["invoice_line"],
                       "settlement": ln["settlement"] or "", "payment": statement.PAY_WORDS[ln["payment"]], "evidence": ln["evidence"],
                       "evidence_sha256": ln["evidence_sha256"], "duplicate_of": ln["duplicate_of"],
                       "assurance": ln["assurance"], "po_reference": ln["po_reference"], "grn_reference": ln["grn_reference"]}
    drawn = squeeze("".join(pdf.texts(statement.as_pdf(st, s))))
    for cell in (x for part in ("top", "rows", "totals", "answers", "events") for row in c[part] for x in row):
        assert squeeze(cell) in drawn, f"the PDF does not say {cell!r}"
    assert squeeze(st["sha256"]) in drawn and squeeze(st["note"]) in drawn
    assert statement.as_pdf(st, s) == statement.as_pdf(json.loads(statement.canonical(st)), s) and statement.as_csv(st, s) == statement.as_csv(sept(), s)


# ---- the PDF is a PDF -----------------------------------------------------------------------------------------------

def objects(data: bytes) -> dict[int, bytes]:
    """A reader for the test: the cross-reference table found from the file's end, each offset checked to start the
    object it is listed for, and each object's body. Fails on anything out of place."""
    assert data.startswith(b"%PDF-1.4\n") and data.endswith(b"%%EOF\n")
    start = int(re.search(rb"startxref\n(\d+)\n%%EOF\n$", data).group(1))
    assert data[start:start + 5] == b"xref\n"
    first, count = map(int, data[start + 5:data.index(b"\n", start + 5)].split())
    table = data[data.index(b"\n", start + 5) + 1:]
    assert first == 0 and table[:20] == b"0000000000 65535 f \n"
    out = {}
    for n in range(1, count):
        entry = table[20 * n:20 * n + 20]
        assert re.fullmatch(rb"\d{10} 00000 n \n", entry), entry
        at = int(entry[:10])
        head = f"{n} 0 obj\n".encode()
        assert data[at:at + len(head)] == head, f"object {n} is not at the offset the table gives"
        out[n] = data[at + len(head):data.index(b"\nendobj\n", at)]
    trailer = table[20 * count:]
    assert trailer.startswith(b"trailer\n") and f"/Size {count} ".encode() in trailer and b"/Root 1 0 R" in trailer
    return out


def test_the_pdf_parses_has_every_page_and_is_the_same_bytes_every_time():
    st, s = sept(), status()
    data = statement.as_pdf(st, s)
    assert data == statement.as_pdf(sept(), status()) and data.isascii()
    obj = objects(data)
    kids = [int(k) for k in re.findall(rb"(\d+) 0 R", re.search(rb"/Kids \[(.*?)\]", obj[2]).group(1))]
    assert b"/Type /Catalog" in obj[1] and int(re.search(rb"/Count (\d+)", obj[2]).group(1)) == len(kids) >= 2
    for n, kid in enumerate(kids, 1):
        assert b"/Type /Page " in obj[kid] and b"/MediaBox [0 0 842 595]" in obj[kid]
        body = obj[int(re.search(rb"/Contents (\d+) 0 R", obj[kid]).group(1))]
        length = int(re.search(rb"/Length (\d+)", body).group(1))
        stream = body[body.index(b"stream\n") + 7:]
        assert stream[length:] == b"endstream" and f"page {n} of {len(kids)}".encode() in stream
    assert b"/BaseFont /Helvetica " in obj[3] and b"/CreationDate (D:20260930000000Z)" in obj[5]        # the statement's own day, not today's
    many = pdf.Doc("Many rows", created="2026-01-02", size=pdf.A4)
    many.table(["n", "words"], [[str(i), "a line that is long enough to wrap (twice) \\ in a narrow column é €"] for i in range(120)], [1, 3])
    pages = objects(many.render())
    assert int(re.search(rb"/Count (\d+)", pages[2]).group(1)) == 3 and pdf.texts(many.render()).count("words") == 3      # the head again on every page
    assert "é €" in "".join(pdf.texts(many.render())) and pdf.wrap("abcdefghij", 7, 12) != ["abcdefghij"] and pdf.latin("日本") == b"??"
    with pytest.raises(ValueError):
        pdf.Doc("x", created="today")


def test_the_statement_pdf_does_not_open_with_an_empty_ruled_row():
    """The table under the title has no head: it used to draw one all the same, an empty ruled row before "invoice".
    Now the first thing under the subtitle is one rule and then the first row. A table with a head is drawn as before,
    and the PDF says the same words."""
    ops = statement.as_pdf(sept(), status()).decode("ascii").split("stream\n")[1].splitlines()
    first = next(i for i, op in enumerate(ops) if op.endswith(f"({statement.cells(sept(), status())['top'][0][0]}) Tj ET"))
    between = ops[2:first]
    assert "Nothing here moves money" in ops[1] and len(between) == 1 and between[0].endswith(" l S"), between
    part = between[0].split()
    x1, y1, x2, y2 = (float(part[i]) for i in (2, 3, 5, 6))
    assert y1 == y2 and (x1, x2) == (36.0, 842.0 - 36.0)                # the rule above the first row, as wide as the page's room
    bare, headed, blank = (pdf.Doc("t", created="2026-01-02") for _ in range(3))
    bare.table(["", " "], [["a", "b"], ["c", "d"]], [1, 5])
    headed.table(["k", "v"], [["a", "b"], ["c", "d"]], [1, 5])
    blank.table(["k", "v"], [["a", "b"]], [1, 5])
    assert pdf.texts(bare.render())[:-1] == ["a", "b", "c", "d"] and pdf.texts(headed.render())[:-1] == ["k", "v", "a", "b", "c", "d"]
    assert bare.y > headed.y and sum(op.endswith(" l S") for op in bare.pages[0]) == sum(op.endswith(" l S") for op in blank.pages[0])
    long = pdf.Doc("t", created="2026-01-02", size=pdf.A4)
    long.table(["", ""], [[str(i), "x"] for i in range(120)], [1, 3])
    assert len(long.pages) > 1 and all(page[0].endswith(" l S") and page[0].split()[3] == page[0].split()[6] for page in long.pages)   # each page opens with the rule
    assert pdf.texts(long.render()).count("x") == 120
    before = ["Statement for invoice INV-2026-09", "Each line of the invoice set against the evidence. Nothing here moves money.", "invoice"]
    assert pdf.texts(statement.as_pdf(sept(), status()))[:3] == before


@pytest.mark.parametrize("tool", ["qpdf", "pdftotext"])
def test_another_program_reads_the_pdf_when_one_is_installed(tool):
    program = shutil.which(tool)
    if not program:
        pytest.skip(f"{tool} is not installed")
    # The reader runs in a short folder of its own, which is also its home, with a small environment: the pdftotext of Git
    # for Windows on GitHub's runners (xpdf 4.06) stops with an access violation (0xC0000005) when its input's path, its
    # home folder and its environment are long together, as a pytest-xdist worker's temporary folders and CI's PATH of
    # 2,817 characters make them; any of them short and it reads the same file (measured on windows-latest, runs
    # 37500539479, 37500847855 and 37503981086 of drexthealpha/knos-rc). The bytes read are the same; what the reader is asked is too.
    with tempfile.TemporaryDirectory(prefix="st") as folder:
        path = Path(folder) / "statement.pdf"
        path.write_bytes(statement.as_pdf(sept(), status()))
        system = [os.path.join(os.environ.get("SYSTEMROOT", "C:\\Windows"), "System32")] if os.name == "nt" else []
        env = {"PATH": os.pathsep.join([os.path.dirname(program), *system]), "HOME": folder, "USERPROFILE": folder,
               **{k: os.environ[k] for k in ("SYSTEMROOT", "LANG", "LC_ALL") if k in os.environ}}
        got = subprocess.run([program, "--check", path.name] if tool == "qpdf" else [program, "-layout", path.name, "-"], capture_output=True, text=True,
                             encoding="utf-8", timeout=60, cwd=folder, env=env)
    assert got.returncode == 0, got.stderr
    if tool == "pdftotext":
        assert "Statement for invoice INV-2026-09" in got.stdout and "insufficient evidence" in got.stdout and sept()["lines"][0]["invoice_line"] in got.stdout


# ---- approval and payment status ------------------------------------------------------------------------------------

def test_approving_the_agreed_lines_leaves_the_exceptions_open_and_names_who():
    st = sept()
    s = statement.approve(st, None, "Dana Reyes", "finance controller", "2026-10-01")
    agreed = [ln["invoice_line"] for ln in st["lines"] if ln["state"] == "agreed"]
    assert s["events"] == [{"type": "approval", "scope": "agreed", "by": "Dana Reyes", "role": "finance controller", "on": "2026-10-01", "lines": agreed, "amount": "160.00"}]
    assert s["statement"] == st["sha256"] and statement.digest(st) == st["sha256"]                    # the statement is not touched
    now = statement.lines_now(st, s)
    assert [bool(r["approved_by"]) for r in now] == [True, False, False, False, True]
    said = dict(statement.answers(st, s))
    assert said == {"Authorised": "not known here: a shadow run reads the invoice and GitHub, not the order",
                    "Billed": "5 lines, 590.00 USD on invoice INV-2026-09 from Acme Agents", "Delivered": "4 of 5 lines name work that was evaluated",
                    "Passed": "2 lines, 160.00 USD agreed", "Already billed": "1 line, 100.00 USD: line 4 (line 1)",
                    "Approved": "2 agreed lines, 160.00 USD by Dana Reyes (finance controller) on 2026-10-01, role as stated",
                    "Disputed": "1 line, 250.00 USD, open", "Insufficient evidence": "1 line, 80.00 USD, open", "Credited": "0 lines, 0.00 USD refunded",
                    "Paid": "0 lines, 0.00 USD", "Owed": "2 lines, 160.00 USD payable"}
    assert dict(statement.answers(st))["Approved"] == "nobody yet"
    with pytest.raises(statement.Refused, match="no agreed line left"):
        statement.approve(st, s, "Dana Reyes", "finance controller", "2026-10-02")
    with pytest.raises(statement.Refused, match="another statement"):
        statement.approve(october(), s, "Dana Reyes", "finance controller", "2026-10-02")


def test_a_payment_made_outside_is_a_settlement_record_with_its_own_id_and_moves_nothing():
    st, s = sept(), status()
    one, two, five = st["lines"][0], st["lines"][1], st["lines"][4]
    paid = [e for e in s["events"] if e["type"] == "settlement"]
    assert paid[0] == {"type": "settlement", "line": one["invoice_line"], "deliverable": one["deliverable"], "method": "bank", "reference": "BACS 77120", "on": "2026-10-02",
                       "state": "paid_outside", "settlement": ids.settlement(one["deliverable"], "bank", "BACS 77120")}
    assert ids.kind_of(paid[0]["settlement"]) == "settlement" and paid[1]["state"] == "devnet_demonstration"
    now = statement.lines_now(st, s)
    assert [(r["payment"], bool(r["settlement"])) for r in now] == [("paid_outside", True), ("held", False), ("held", False), ("held", False), ("devnet_demonstration", True)]
    said = dict(statement.answers(st, s))
    assert said["Paid"] == "2 lines, 160.00 USD (devnet demonstration, paid outside Knos)" and said["Owed"] == "0 lines, 0.00 USD payable"
    with pytest.raises(statement.Refused, match="already recorded"):
        statement.pay(st, s, one["invoice_line"], "bank", "BACS 77120", "2026-10-09")
    with pytest.raises(statement.Refused, match="No line of this statement"):
        statement.pay(st, s, five["deliverable"], "bank", "x", "2026-10-09")
    with pytest.raises(statement.Refused, match="YYYY-MM-DD"):
        statement.pay(st, s, five["invoice_line"], "bank", "x", "9 October")
    back = statement.pay(st, s, one["invoice_line"], "bank", "BACS 77999", "2026-10-20", "refunded")           # every state can be written down, the last one stands
    assert statement.lines_now(st, back)[0]["payment"] == "refunded" and dict(statement.answers(st, back))["Credited"] == "1 line, 100.00 USD refunded"
    wrong = statement.pay(st, None, two["invoice_line"], "bank", "BACS 1", "2026-10-02")                       # paid before anyone looked: it is said, not hidden
    assert dict(statement.answers(st, wrong))["Credited"].endswith("1 line, 250.00 USD paid though not agreed, to be credited or settled")
    assert {statement.pay(st, None, one["invoice_line"], "other", "r", "2026-10-02", w)["events"][0]["state"] for w in statement.PAY_WORDS.values()} == set(statement.PAY_STATES)


# ---- made again, years later ----------------------------------------------------------------------------------------

def test_verify_makes_the_statement_again_from_its_evidence_and_names_the_first_line_that_differs(monkeypatch):
    import socket

    def no_network(*a, **k):
        raise AssertionError("verify asked the network")
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    st = sept()
    assert statement.verify(json.loads(statement.canonical(st))) == (True, "same")
    assert set(st["evidence"]["items"]) == {"invoice", *(p for p in BOOK if "/pulls/6" not in p and f"/{sha1(6)}/" not in p and "/pulls/7" not in p and f"/{sha1(7)}/" not in p)}
    edited = json.loads(statement.canonical(st))
    edited["lines"][1]["state"], edited["lines"][1]["why"] = "agreed", ""
    assert statement.verify(edited)[1].startswith("differs: the statement is not the one its own sha256 names")
    edited["sha256"] = statement.digest(edited)                                                 # whoever edits it can fix the hash; the evidence still says no
    assert statement.verify(edited) == (False, "differs: line 2: state is 'agreed' in the statement and 'disputed' from the evidence")
    swapped = json.loads(statement.canonical(st))
    swapped["evidence"]["embedded"]["answers"]["repos/acme/app/pulls/2"]["merged_at"] = None
    swapped["sha256"] = statement.digest(swapped)
    assert statement.verify(swapped) == (False, "differs: the evidence is not the evidence the statement names (its sha256 is another)")
    # evidence kept beside the statement: named by hash, given back as a file
    lean = sept(embed=False)
    kept = statement.canonical(st["evidence"]["embedded"])
    assert lean["evidence"]["embedded"] is None and lean["evidence"]["sha256"] == st["evidence"]["sha256"] and lean["lines"] == st["lines"] and lean["sha256"] != st["sha256"]
    assert statement.verify(lean, kept) == (True, "same")
    assert statement.verify(lean, kept.replace(b'"conclusion":"failure"', b'"conclusion":"success"'))[1] == "differs: the evidence is not the evidence the statement names (its sha256 is another)"
    with pytest.raises(statement.Refused, match="--bundle"):
        statement.verify(lean)


def test_a_closed_month_becomes_a_statement_and_github_signatures_are_checked_with_no_network(monkeypatch):
    import socket

    import test_ledger_periods as P
    from knos import ledger as L
    key = P.Key("knos meter close test key")
    record, texts, tokens, jwks = P._month((key, {"keys": [key.jwk("k1")]}))
    blob = L.month_bundle(record, texts, tokens, jwks)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked the network")))
    st = statement.from_month(blob, {"currency": "USD"})
    assert st["source"] == "month" and st["date"] == "2026-10-31" and st["evidence"]["signed"] == ["buyer", "seller"] and st["evidence"]["sha256"] == statement.sha(blob)
    assert (st["supplier"], st["buyer"], st["invoice"], st["scale"]) == (f"gh:{P.SELLER}", f"gh:{P.BUYER}", "meter 202610", 6)
    assert [ln["state"] for ln in st["lines"]] == ["agreed"] * 8 and st["totals"]["agreed"] == {"lines": 8, "amount": "16.00"}
    first = st["lines"][0]
    assert first["amount"] == "2.00" and first["evidence_sha256"] == st["evidence"]["items"]["ledger.seller.jsonl"] and len(first["evaluations"]) == 1
    assert statement.verify(st) == (True, "same") and base64.b64decode(st["evidence"]["embedded"]) == blob
    assert statement.make(blob, {"currency": "USD"}) == st and len(objects(statement.as_pdf(st))) >= 7
    # only the supplier's ledger: nothing can be agreed
    alone = statement.from_month(L.month_bundle(record, {"seller": texts["seller"]}, {"seller": tokens["seller"]}, jwks), {})
    assert {ln["state"] for ln in alone["lines"]} == {"insufficient_evidence"} and alone["evidence"]["signed"] == ["seller"]
    # a month in dispute: the line the buyer judged differently, the one it never had and the one it entered twice are disputed, in words
    e, buyer, seller = P._two_sides()
    open_month = L.close(buyer, seller, P.MONTH)
    argued = statement.from_month(L.month_bundle(open_month, {"buyer": L.dump(s.batch() for s in buyer), "seller": L.dump(s.batch() for s in seller)}, {}, jwks), {})
    why = {ln["why"] for ln in argued["lines"] if ln["state"] == "disputed"}
    assert why == {"the two ledgers give this evaluation different verdicts", "the buyer's ledger has no record of this evaluation",
                   "the buyer's ledger holds this evaluation twice and no correction settles it"} and argued["evidence"]["signed"] == []
    assert argued["totals"]["disputed"]["lines"] == 3 and argued["totals"]["agreed"]["lines"] == 5
    with pytest.raises(statement.Refused, match="does not hold"):
        statement.from_month(blob.replace(b"accepted", b"accepteD", 1), {})


# ---- the exports ----------------------------------------------------------------------------------------------------

def test_the_exports_carry_the_state_and_the_ids_and_only_agreed_lines_become_bills():
    st, s = sept(), status()
    files = {fmt: list(csv.reader(io.StringIO(exports.write_statement(fmt, st, s, {"account": "6100 Contract engineering"})))) for fmt in exports.STATEMENT_FORMATS}
    qb, ns, generic = files["quickbooks"], files["netsuite"], files["generic"]
    assert tuple(qb[0]) == exports.QUICKBOOKS and {"Bill no.", "Supplier", "Bill Date", "Due Date", "Account", "Line Amount", "Line Tax Code"} <= set(qb[0])
    assert tuple(ns[0]) == exports.NETSUITE and ns[0][:4] == ["External ID", "Vendor", "Date", "Reference No."] and "Expenses : Amount" in ns[0]
    assert len(qb) == len(ns) == 3 and [r[6] for r in qb[1:]] == ["100.00", "60.00"] and [r[6] for r in ns[1:]] == ["100.00", "60.00"]
    one = st["lines"][0]
    assert qb[1][:5] == [exports.bill_number(one["deliverable"], "Acme Agents"), "Acme Agents", "30/9/2026", "30/9/2026", "6100 Contract engineering"]
    assert ns[1][:4] == [qb[1][0], "Acme Agents", "9/30/2026", qb[1][0]] and ns[1][0] == ns[1][3]
    memo = qb[1][8]
    assert memo == ns[1][4] and memo.startswith(f"agreed, paid outside Knos | Knos statement sha256:{st['sha256']} | deliverable {one['deliverable']} | invoice line {one['invoice_line']}")
    assert f"evaluation {one['evaluations'][0]}" in memo and f"settlement {ids.settlement(one['deliverable'], 'bank', 'BACS 77120')}" in memo
    assert generic[0] == ["knos.finance-export", "version", "1", "statement", "file export, not an integration"] and tuple(generic[1]) == exports.STATEMENT_GENERIC
    assert [r[2] for r in generic[2:]] == ["agreed", "disputed", "insufficient evidence", "duplicate", "agreed"] and len({r[12] for r in generic[2:]}) == 5
    assert exports.IMPORTED == {} and all(exports.label(f) == exports.LABEL == "file export, not an integration" for f in exports.FORMATS)
    with pytest.raises(Exception, match="--format is quickbooks, netsuite, generic"):
        exports.write_statement("sap", st)


# ---- the commands ---------------------------------------------------------------------------------------------------

def test_the_commands_from_a_shadow_run_to_a_verified_statement(tmp_path):
    from typer.testing import CliRunner
    app = typer.Typer()
    shadow.register(app)
    statement.register(app)
    cli = CliRunner()

    def ok(*args: str) -> str:
        got = cli.invoke(app, [str(a) for a in args])
        assert got.exit_code == 0, got.output
        return got.output

    (tmp_path / "invoice.csv").write_text(SEPT, encoding="utf-8")
    (tmp_path / "book.json").write_text(json.dumps(BOOK), encoding="utf-8")
    out = tmp_path / "sept"
    assert "knos statement make" in ok("shadow", tmp_path / "invoice.csv", "--recorded", tmp_path / "book.json", "--out", out)
    said = ok("statement", "make", out / "evidence.json", "--invoice", "INV-2026-09", "--buyer", "Northwind", "--currency", "USD", "--date", "2026-09-30")
    file = out / "ap-statement.json"
    assert file.read_bytes() == statement.canonical(sept()) and f"sha256 {sept()['sha256']}" in said and "insufficient evidence" in said
    assert (out / "ap-statement.csv").read_bytes() == statement.as_csv(sept()).encode() and (out / "ap-statement.pdf").read_bytes() == statement.as_pdf(sept())
    assert json.loads((out / "statement.json").read_text(encoding="utf-8"))["kind"] == "knos-shadow-statement"        # the shadow run's own file is still there
    assert ok("statement", "verify", file).splitlines() == ["same", "ap-statement.csv: same", "ap-statement.pdf: same"]
    assert cli.invoke(app, ["statement", "approve", str(file), "--by", "Dana Reyes", "--role", "finance controller"]).exit_code != 0       # what is approved must be said
    said = ok("statement", "approve", file, "--agreed", "--by", "Dana Reyes", "--role", "finance controller", "--on", "2026-10-01")
    assert "Approved:" in said and "by Dana Reyes (finance controller) on 2026-10-01" in said and "Disputed:" in said
    line = sept()["lines"][0]["invoice_line"]
    said = ok("statement", "pay", file, "--line", line, "--method", "bank", "--ref", "BACS 77120", "--on", "2026-10-02")
    assert f"recorded {ids.settlement(sept()['lines'][0]['deliverable'], 'bank', 'BACS 77120')}" in said and "No money moved." in said
    ok("statement", "pay", file, "--line", sept()["lines"][4]["invoice_line"], "--method", "chain", "--ref", "5Yd1testtransaction", "--on", "2026-10-03")
    assert (out / "ap-statement.status.json").read_bytes() == statement.canonical(status()) and file.read_bytes() == statement.canonical(sept())
    assert (out / "ap-statement.csv").read_bytes() == statement.as_csv(sept(), status()).encode()
    assert "Owed:" in ok("statement", "show", file) and "same" in ok("statement", "verify", file)
    assert ok("statement", "export", file, "--format", "quickbooks", "--account", "6100 Contract engineering").endswith(golden()["sept.quickbooks.csv"].decode())
    # the next invoice, with the earlier statement: the deliverable billed again is named
    (tmp_path / "oct.csv").write_text(OCT, encoding="utf-8")
    ok("shadow", tmp_path / "oct.csv", "--recorded", tmp_path / "book.json", "--out", tmp_path / "oct")
    said = ok("statement", "make", tmp_path / "oct" / "evidence.json", "--prior", file, "--invoice", "INV-2026-10", "--buyer", "Northwind", "--currency", "USD",
              "--date", "2026-10-31", "--reference")
    made = json.loads((tmp_path / "oct" / "ap-statement.json").read_text(encoding="utf-8"))
    assert made["lines"] == october()["lines"] and made["evidence"]["embedded"] is None and "--bundle" in said
    assert cli.invoke(app, ["statement", "verify", str(tmp_path / "oct" / "ap-statement.json")]).exit_code != 0                 # the evidence is in a file: it must be given
    assert ok("statement", "verify", tmp_path / "oct" / "ap-statement.json", "--bundle", tmp_path / "oct" / "ap-statement.evidence.json").startswith("same")
    # a changed line is found by its number, and the command fails
    doc = json.loads(file.read_text(encoding="utf-8"))
    doc["lines"][2]["amount"] = "8.00"
    doc["sha256"] = statement.digest(doc)
    (tmp_path / "edited.json").write_text(json.dumps(doc), encoding="utf-8")
    got = cli.invoke(app, ["statement", "verify", str(tmp_path / "edited.json")])
    assert got.exit_code == 1 and got.output.strip() == "differs: line 3: amount is '8.00' in the statement and '80.00' from the evidence"


def test_the_page_gives_the_same_csv_and_exports_as_the_python():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    got = subprocess.run([node, str(ROOT / "tests" / "web" / "statement.mjs")], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert got.returncode == 0, got.stdout + got.stderr


if __name__ == "__main__" and "--write" in sys.argv:
    DATA.mkdir(parents=True, exist_ok=True)
    for name, data in golden().items():
        (DATA / name).write_bytes(data)
        print("wrote", name)
    for name, data in sample().items():
        (ROOT / "web" / name).write_bytes(data)
        print("wrote web/" + name)
