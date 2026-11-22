"""A result's three downloads, from its /r/<id> page: the brief as a one-page PDF (the print layout's fields: the idea,
the verdict, each open signal and the page's address), the open signals as CSV (source, value, unit, whether it counts,
link) and the Ready brief as JSON (none: the open signals name no launch city, so no brief locks money on them)."""
from __future__ import annotations

import csv
import io
import json
import textwrap

from . import result_page


def csv_text(rep: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["source", "value", "unit", "counts", "link"])
    for r in (rep.get("open_demand") or {}).get("rows") or []:
        if isinstance(r, dict):
            w.writerow([r.get("name"), r.get("value"), r.get("unit"), "yes" if r.get("counts") else "no", r.get("link") or ""])
    return out.getvalue()


def brief_doc(rep: dict) -> dict:
    return {"ready": False, "brief": None, "idea": rep.get("idea"), "report": rep.get("hash"),
            "why": "The open signals name no launch city, so there is no Ready brief to lock money on."}


def _ascii(s: str) -> str:
    return str(s).encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf(rep: dict, url: str) -> bytes:
    """One A4 page of text in Helvetica: the fields the /r/ page prints."""
    fb = rep.get("open_demand") or {}
    word = fb.get("head") or result_page.WORD.get(str((rep.get("decision") or {}).get("verdict") or ""), result_page.WORD["CANNOT_DECIDE"])
    rows = [(16, f"Knos. {rep.get('idea') or 'this idea'}"), (12, word)]
    rows += [(11, f"{r.get('name')}: {r.get('value')} {r.get('unit')}") for r in fb.get("rows") or [] if isinstance(r, dict)]
    rows += [(9, " ".join(x for x in (fb.get("line"), fb.get("rule")) if x)), (9, url), (9, "Devnet, test money.")]
    y, ops = 800, []
    for size, text in rows:
        for part in textwrap.wrap(text, 90, break_long_words=False, break_on_hyphens=False) or [""]:
            ops.append(f"BT /F1 {size} Tf 50 {y} Td ({_ascii(part)}) Tj ET")
            y -= size + 8
    stream = "\n".join(ops).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def json_text(rep: dict) -> str:
    return json.dumps(brief_doc(rep), indent=1, ensure_ascii=False)


# ---- a limit check's result, its inputs and its evidence (L06): /api/run/<id>.csv and /api/run/<id>.json -------------------
def row_status(r: dict) -> dict[int, str]:
    """Each data row's status by the program's own answer: "failed" in a failing run of rows, "no number" when the
    program could not read a number in it (its "unchecked"), else "passed"."""
    out = {int(x): "no number" for x in r.get("unchecked") or [] if isinstance(x, int)}
    for pair in r.get("failing") or []:
        if isinstance(pair, list) and len(pair) == 2:
            for n in range(int(pair[0]), int(pair[1]) + 1):
                out.setdefault(n, "failed")
    return out


def tool_csv(r: dict) -> str:
    """The checked table as it was sent, each data row with its row number and status, then the verdict, the locked
    test's sha256 and the tool's version on every row, so the file stands alone in any spreadsheet."""
    rows = [x for x in csv.reader(io.StringIO(r.get("input") or "")) if any(c.strip() for c in x)]
    from . import tool_run
    head = rows[0] if rows and tool_run.header_row(rows[0]) else [f"column {i + 1}" for i in range(max((len(x) for x in rows), default=0))]
    data = rows[1:] if rows and tool_run.header_row(rows[0]) else rows
    st = row_status(r)
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["knos_row", "knos_status", *head, "knos_verdict", "knos_column", "knos_rule", "knos_limit", "knos_test_sha256", "knos_tool_version", "knos_checked_at"])
    for i, x in enumerate(data, 1):
        w.writerow([i, st.get(i, "passed"), *x, r.get("verdict"), r.get("column"), r.get("rule"), r.get("limit"),
                    r.get("test_sha256"), r.get("tool_version"), r.get("created_at")])
    return out.getvalue()


def tool_json(r: dict) -> dict:
    """The result and its inputs as one document; sent back to POST /api/run as it is, it checks the same table again
    ("id" is the tool's id, as /api/run reads it; the result's own id is "result_id")."""
    return {"id": r.get("tool") or "limit-check", "result_id": r.get("id"), "table": r.get("input") or "", "column": r.get("column"),
            "rule": r.get("rule"), "limit": r.get("limit"), "verdict": r.get("verdict"), "result": r.get("result"),
            "first_failing_row": r.get("first_failing_row"), "failing": r.get("failing"), "passed": r.get("passed"),
            "unchecked": r.get("unchecked"), "input_cut": bool(r.get("cut")), "test_sha256": r.get("test_sha256"),
            "tool_version": r.get("tool_version"), "created_at": r.get("created_at"), "link": r.get("link")}
