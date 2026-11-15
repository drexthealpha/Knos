"""Paying an approved statement through a rail the buyer already has: a bank.

    knos statement pay <file> --rail bank --payer-name N --payer-account IBAN --payees payees.csv
    knos statement status <file> --from <the bank's status report>

`pain001` writes one ISO 20022 customer credit transfer initiation (pain.001.001.09) for the lines that are agreed,
approved and still payable, and for nothing else: one transfer per supplier. A disputed or duplicate line, a line
without enough evidence, a line nobody approved and a line that is already paid or already instructed is never in it.

    end-to-end id    the settlement id (knos.ids: stl_ and 24 hex characters), made from the statement's hash, the
                     supplier and the invoice lines the transfer pays. A bank carries it to the payee and back.
    remittance       first "KNOS <the statement's sha256> INV <invoice>", then the invoice line ids, four to a line.

`read_status` reads what the bank answers: a customer payment status report (pain.002, any version: it is read by
element name) or a CSV (`end_to_end_id,status,reference,date,reason`). `apply` marks each line of a settled transfer
paid outside Knos and each line of a rejected one payable again, with the bank's reason. Reading one report twice
changes nothing.

An answer that is not clear is never taken as a no. A timeout, "unknown", or a status code this module does not know
marks each line of the transfer UNKNOWN (a settlement record with state `held` and `unknown: true`, so the statement,
its CSV and the site all show the line held, with why): the money may have left. No payment file names such a line
until a later status file says paid (the line is paid) or returned (payable again, under a new end-to-end id). A
second instruction under an end-to-end id an earlier file used is refused, whatever the status file says
(`instruct`), and a payment reported for a line already paid under another id is said as paid twice.

`accepted_rows` is what the month's bill is made from: one row per agreed deliverable that was paid, whichever rail
paid it, so Acceptance is charged on it once; a deliverable the program released says `on_chain`, and its fee was
taken there.

What was checked, and what was not. `check` holds a file to the message definition's structure: the namespace, the
order and presence of every element this module writes, their lengths and patterns, and that the counts and the control
sum are the transfers'. It is written by hand from the published definition (docs/reference/RAILS.md names the pages read); the
official schema file is not in this repository and the file was not run through it. NO BANK HAS TAKEN A FILE THIS
MODULE WROTE. A bank's own rules (which characters, how many remittance lines, which agent identifiers) are narrower
than the definition and differ by bank.

Nothing here moves money. The file is an instruction the payer uploads to their own bank.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from xml.etree import ElementTree as ET

from . import ids

MESSAGE = "pain.001.001.09"
NS = "urn:iso:std:iso:20022:tech:xsd:" + MESSAGE
RAILS = ("bank", "usdc")
PAID = ("ACSC", "ACCC")                   # settled on the debtor's account; settled on the creditor's account
FAILED = ("RJCT", "CANC")                 # rejected; cancelled
PENDING = ("ACTC", "ACCP", "ACSP", "ACWC", "ACFC", "ACWP", "PDNG", "RCVD", "PART", "PATC")
UNCLEAR = ("unknown", "timeout", "timed out", "no answer", "error")    # the bank, or the link to it, gave no clear answer
WORDS = {"paid": "paid", "settled": "paid", "completed": "paid", "failed": "failed", "returned": "failed", "rejected": "failed",
         "cancelled": "failed", "pending": "pending", "sent": "pending", "accepted": "pending",
         **{w: "unknown" for w in UNCLEAR}, **{c.lower(): "paid" for c in PAID}, **{c.lower(): "failed" for c in FAILED}, **{c.lower(): "pending" for c in PENDING}}
STATUS_HEAD = ("end_to_end_id", "status", "reference", "date", "reason")
_OK = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/-?:().,'+ "
_IBAN = re.compile(r"[A-Z]{2}[0-9]{2}[A-Za-z0-9]{1,30}")
_BIC = re.compile(r"[A-Z0-9]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?")
_DAY = re.compile(r"\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")
_WHEN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?")


class Refused(ValueError):
    """An instruction that cannot be written, or a status report that cannot be read, in words."""


def text(value: str, most: int) -> str:
    """Text as a bank's file takes it: the Latin letters, digits and `/-?:().,'+` and the space; anything else is a
    full stop. Cut to `most` characters. (The narrow set every profile of the message accepts.)"""
    return "".join(c if c in _OK else "." for c in str(value).strip())[:most].strip()


def iban_ok(account: str) -> bool:
    """Whether an IBAN's two check digits are its own (ISO 13616: the number, rearranged, is 1 modulo 97)."""
    moved = account[4:] + account[:4]
    rest = 0
    for c in moved.upper():
        for d in str(int(c, 36)):
            rest = (rest * 10 + int(d)) % 97
    return rest == 1


def account(value: str, whose: str) -> tuple[str, str]:
    """("IBAN", the account) or ("Othr", the account): an account number as the file names it. Refused when it looks like
    an IBAN and its check digits are wrong, or when it is no account number at all."""
    got = re.sub(r"\s+", "", str(value or ""))
    if _IBAN.fullmatch(got) and len(got) >= 15:
        if not iban_ok(got):
            raise Refused(f"{whose}: {got} looks like an IBAN and its check digits are wrong. Nothing was written.")
        return "IBAN", got
    if not re.fullmatch(r"[A-Za-z0-9]{1,34}", got):
        raise Refused(f"{whose}: an account is an IBAN, or up to 34 letters and digits; {str(value)[:40]!r} is neither.")
    return "Othr", got


def bic(value: str, whose: str) -> str:
    got = re.sub(r"\s+", "", str(value or "")).upper()
    if got and not _BIC.fullmatch(got):
        raise Refused(f"{whose}: a BIC is 8 or 11 letters and digits; {str(value)[:20]!r} is not one.")
    return got


def instructed(status: dict | None) -> dict[str, dict]:
    """Invoice line -> the transfer that pays it, for every line an instruction file names and no bank returned since.
    A line whose last bank answer is not clear is held by its settlement record (`unknown`), returned or not."""
    out: dict[str, dict] = {}
    for e in (status or {}).get("events", []):
        if e["type"] == "instruction":
            for t in e["transfers"]:
                for line in t["lines"]:
                    out[line] = {**t, "message": e["message"]}
        elif e["type"] == "settlement" and e.get("returned"):
            out.pop(e["line"], None)
    return out


def unknown(status: dict | None) -> dict[str, dict]:
    """Invoice line -> its last settlement record, for every line whose last bank answer was not clear: no payment file
    names it until a status file says paid or returned."""
    last: dict[str, dict] = {}
    for e in (status or {}).get("events", []):
        if e["type"] == "settlement":
            last[e["line"]] = e
    return {line: e for line, e in last.items() if e.get("unknown")}


def transfers(st: dict, status: dict | None = None) -> list[dict]:
    """One transfer per supplier, in the statement's order, for the lines that are agreed, approved, still payable and
    in no instruction a bank still holds: [{"end_to_end", "supplier", "amount", "units", "currency", "lines"}]."""
    from . import statement as S
    cur, scale, sent = str(st["currency"]), st["scale"], instructed(status)
    rounds = sum(1 for e in (status or {}).get("events", []) if e["type"] == "instruction")
    by: dict[str, list[dict]] = {}
    for ln in S.lines_now(st, status):
        if ln["state"] == "agreed" and ln["payment"] == "payable" and ln["approved_by"] and ln["amount"] and ln["invoice_line"] not in sent:
            by.setdefault(ln["supplier"], []).append(ln)
    if by and not re.fullmatch(r"[A-Z]{3}", cur):
        raise Refused(f"A bank moves a currency with a three-letter code; {f'this statement is in {cur!r}' if cur else 'this statement states no currency'}. "
                      "Test money is paid on devnet (--rail usdc), never by bank.")
    out = []
    for supplier, mine in by.items():
        total = sum(S.units(ln["amount"], scale) for ln in mine)
        cents, rest = divmod(total, 10 ** (scale - 2)) if scale > 2 else (total * 10 ** (2 - scale), 0)
        if rest or total <= 0:
            raise Refused(f"The lines of {supplier} come to {S.amount_of(total, scale)} {cur}: a bank transfer is a positive amount in whole cents.")
        lines = [ln["invoice_line"] for ln in mine]
        out.append({"end_to_end": ids.settlement(f"{st['sha256']}:{supplier}", "bank", ",".join(lines) + (f"#{rounds}" if rounds else "")),
                    "supplier": supplier, "amount": f"{cents // 100}.{cents % 100:02d}", "units": cents, "currency": cur, "lines": lines})
    return out


def message_id(st: dict, found: list[dict]) -> str:
    """The file's own id: KNOS and 28 hex characters of the statement's hash and the transfers it holds."""
    return "KNOS" + hashlib.sha256((st["sha256"] + "|" + ",".join(t["end_to_end"] for t in found)).encode()).hexdigest()[:28].upper()


def _party(name: str, acct: tuple[str, str], agent: str, who: str, pad: str, required_agent: bool) -> list[str]:
    kind, number = acct
    inner = f"<IBAN>{number}</IBAN>" if kind == "IBAN" else f"<Othr><Id>{number}</Id></Othr>"
    out = [f"{pad}<{who}><Nm>{name}</Nm></{who}>", f"{pad}<{who}Acct><Id>{inner}</Id></{who}Acct>"]
    fin = f"<BICFI>{agent}</BICFI>" if agent else "<Othr><Id>NOTPROVIDED</Id></Othr>"
    said = f"{pad}<{who}Agt><FinInstnId>{fin}</FinInstnId></{who}Agt>"
    if who == "Dbtr":
        return [*out, said]                                   # the debtor's agent is mandatory, after the account
    return [*([said] if agent or required_agent else []), *out]      # the creditor's agent is optional, before the creditor


def pain001(st: dict, status: dict | None, payer: dict) -> tuple[str, list[dict], str]:
    """(the file's text, its transfers, its message id). `payer`: {"name", "account", "bic" (may be empty), "on" (the
    day the file is made), "execute" (the day the bank is asked to pay: `on` when left out), "created" (the file's
    time, `on` at midnight UTC when left out), "payees": {supplier: {"name", "account", "bic"}}}. The same statement,
    status and payer give the same bytes; web/rails.js gives them too (tests/data/rails)."""
    found = transfers(st, status)
    if not found:
        raise Refused("No line of this statement is agreed, approved and still payable: there is nothing to instruct. "
                      "`knos statement approve --agreed` approves the agreed lines; a line a bank file already names is not named again.")
    on = str(payer.get("on") or "")
    execute, created = str(payer.get("execute") or on), str(payer.get("created") or f"{on}T00:00:00Z")
    if not _DAY.fullmatch(on) or not _DAY.fullmatch(execute) or not _WHEN.fullmatch(created):
        raise Refused("A payment file names its day (YYYY-MM-DD), the day to pay and its own time (YYYY-MM-DDThh:mm:ssZ).")
    name = text(payer.get("name") or "", 140)
    if not name:
        raise Refused("A payment file names who pays: the payer's name.")
    mine, agent = account(payer.get("account") or "", "the payer's account"), bic(payer.get("bic") or "", "the payer's bank")
    payees = payer.get("payees") or {}
    missing = [t["supplier"] for t in found if not (payees.get(t["supplier"]) or {}).get("account")]
    if missing:
        raise Refused(f"No bank account is given for {', '.join(missing)}. The payees file has one row a supplier: supplier,name,account,bic.")
    msg, total = message_id(st, found), sum(t["units"] for t in found)
    summed = f"{total // 100}.{total % 100:02d}"
    out = ['<?xml version="1.0" encoding="UTF-8"?>', f'<Document xmlns="{NS}">', "  <CstmrCdtTrfInitn>", "    <GrpHdr>", f"      <MsgId>{msg}</MsgId>",
           f"      <CreDtTm>{created}</CreDtTm>", f"      <NbOfTxs>{len(found)}</NbOfTxs>", f"      <CtrlSum>{summed}</CtrlSum>",
           f"      <InitgPty><Nm>{name}</Nm></InitgPty>", "    </GrpHdr>", "    <PmtInf>", f"      <PmtInfId>{msg}-1</PmtInfId>", "      <PmtMtd>TRF</PmtMtd>",
           f"      <NbOfTxs>{len(found)}</NbOfTxs>", f"      <CtrlSum>{summed}</CtrlSum>", f"      <ReqdExctnDt><Dt>{execute}</Dt></ReqdExctnDt>",
           *_party(name, mine, agent, "Dbtr", "      ", True)]
    for t in found:
        p = payees[t["supplier"]]
        who = text(p.get("name") or t["supplier"], 140) or "NOTPROVIDED"
        said = [text(f"KNOS {st['sha256']} INV {st['invoice']}", 140), *(" ".join(t["lines"][n:n + 4]) for n in range(0, len(t["lines"]), 4))]
        out += ["      <CdtTrfTxInf>", f"        <PmtId><EndToEndId>{t['end_to_end']}</EndToEndId></PmtId>",
                f"        <Amt><InstdAmt Ccy=\"{t['currency']}\">{t['amount']}</InstdAmt></Amt>",
                *_party(who, account(p["account"], f"the account of {t['supplier']}"), bic(p.get("bic") or "", f"the bank of {t['supplier']}"), "Cdtr", "        ", False),
                "        <RmtInf>", *(f"          <Ustrd>{u}</Ustrd>" for u in said), "        </RmtInf>", "      </CdtTrfTxInf>"]
    out += ["    </PmtInf>", "  </CstmrCdtTrfInitn>", "</Document>"]
    return "\n".join(out) + "\n", found, msg


# ---- the structure the message definition asks for, checked by hand --------------------------------------------------

# element -> (its children in the definition's order, the ones that must be there). Only the elements this module can
# write are listed with their neighbours; an element that is not listed here is refused, so a file is never "valid" by
# leaving the table.
ORDER: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "Document": (("CstmrCdtTrfInitn",), ("CstmrCdtTrfInitn",)),
    "CstmrCdtTrfInitn": (("GrpHdr", "PmtInf"), ("GrpHdr", "PmtInf")),
    "GrpHdr": (("MsgId", "CreDtTm", "Authstn", "NbOfTxs", "CtrlSum", "InitgPty"), ("MsgId", "CreDtTm", "NbOfTxs", "InitgPty")),
    "PmtInf": (("PmtInfId", "PmtMtd", "BtchBookg", "NbOfTxs", "CtrlSum", "PmtTpInf", "ReqdExctnDt", "PoolgAdjstmntDt", "Dbtr", "DbtrAcct", "DbtrAgt",
                "DbtrAgtAcct", "InstrForDbtrAgt", "UltmtDbtr", "ChrgBr", "ChrgsAcct", "ChrgsAcctAgt", "CdtTrfTxInf"),
               ("PmtInfId", "PmtMtd", "ReqdExctnDt", "Dbtr", "DbtrAcct", "DbtrAgt", "CdtTrfTxInf")),
    "CdtTrfTxInf": (("PmtId", "PmtTpInf", "Amt", "XchgRateInf", "ChrgBr", "ChqInstr", "UltmtDbtr", "IntrmyAgt1", "CdtrAgt", "CdtrAgtAcct", "Cdtr", "CdtrAcct",
                     "UltmtCdtr", "Purp", "RgltryRptg", "Tax", "RmtInf"), ("PmtId", "Amt")),
    "PmtId": (("InstrId", "EndToEndId", "UETR"), ("EndToEndId",)),
    "Amt": (("InstdAmt",), ("InstdAmt",)),
    "ReqdExctnDt": (("Dt",), ("Dt",)),
    "InitgPty": (("Nm",), ()), "Dbtr": (("Nm",), ()), "Cdtr": (("Nm",), ()),
    "DbtrAcct": (("Id",), ("Id",)), "CdtrAcct": (("Id",), ("Id",)),
    "DbtrAgt": (("FinInstnId",), ("FinInstnId",)), "CdtrAgt": (("FinInstnId",), ("FinInstnId",)),
    "FinInstnId": (("BICFI", "Othr"), ()),
    "RmtInf": (("Ustrd",), ()),
}
MANY = {"PmtInf", "CdtTrfTxInf", "Ustrd"}
LEAF = {"MsgId": r".{1,35}", "PmtInfId": r".{1,35}", "EndToEndId": r".{1,35}", "CreDtTm": _WHEN.pattern, "NbOfTxs": r"[0-9]{1,15}",
        "CtrlSum": r"[0-9]{1,18}(\.[0-9]{1,17})?", "PmtMtd": r"TRF", "Dt": _DAY.pattern, "Nm": r".{1,140}", "IBAN": _IBAN.pattern, "BICFI": _BIC.pattern,
        "InstdAmt": r"[0-9]{1,13}(\.[0-9]{1,5})?", "Ustrd": r".{1,140}"}


def check(xml: str) -> list[str]:
    """Everything in a file that is not the message definition's structure, in words; empty when it holds. See the
    module's text for what this is and is not."""
    if "<!DOCTYPE" in xml or "<!ENTITY" in xml:
        return ["the file declares a document type: a payment file has none"]
    try:
        root = ET.fromstring(xml.encode("utf-8"))
    except ET.ParseError as why:
        return [f"the file is not well-formed XML: {why}"]
    wrong: list[str] = []
    name = lambda el: el.tag.split("}", 1)[-1]                                       # noqa: E731

    def walk(el, path: str) -> None:
        here = name(el)
        if not el.tag.startswith("{" + NS + "}"):
            wrong.append(f"{path}: not in the namespace {NS}")
        kids = [name(k) for k in el]
        if here in ("Id", "Othr"):                             # an account's or an agent's id: IBAN, or Othr with a plain Id
            if here == "Id" and not kids:
                if not re.fullmatch(r".{1,35}", el.text or ""):
                    wrong.append(f"{path}: an id is 1 to 35 characters")
                return
            allowed = ("IBAN", "Othr") if here == "Id" else ("Id",)
            if len(kids) != 1 or kids[0] not in allowed:
                wrong.append(f"{path}: holds exactly one of {', '.join(allowed)}")
        elif here in LEAF:
            if kids or not re.fullmatch(LEAF[here], el.text or "", re.S):
                wrong.append(f"{path}: {(el.text or '')[:40]!r} is not what the definition allows here")
            if here == "InstdAmt" and not re.fullmatch(r"[A-Z]{3}", el.get("Ccy") or ""):
                wrong.append(f"{path}: Ccy is three capital letters")
            if here == "IBAN" and not iban_ok(el.text or "XX00"):
                wrong.append(f"{path}: the IBAN's check digits are wrong")
            return
        elif here not in ORDER:
            wrong.append(f"{path}: an element this checker does not know")
            return
        else:
            order, needed = ORDER[here]
            at = -1
            for k in kids:
                if k not in order:
                    wrong.append(f"{path}/{k}: not a child of {here} that this checker knows")
                    continue
                if order.index(k) < at or (order.index(k) == at and k not in MANY):
                    wrong.append(f"{path}/{k}: out of order, or there twice")
                at = max(at, order.index(k))
            wrong.extend(f"{path}/{k}: missing" for k in needed if k not in kids)
            if here == "FinInstnId" and not kids:
                wrong.append(f"{path}: names no institution")
        for k in el:
            walk(k, f"{path}/{name(k)}")

    walk(root, name(root))
    if name(root) != "Document":
        wrong.append("the root element is Document")
    find = lambda what: [e for e in root.iter() if name(e) == what]                    # noqa: E731
    txs, e2e = find("CdtTrfTxInf"), [e.text for e in find("EndToEndId")]
    cents = lambda s: int(s.split(".")[0]) * 100 + int((s.split(".") + ["0"])[1].ljust(2, "0")[:2])     # noqa: E731
    try:
        total = sum(cents(e.text or "") for e in find("InstdAmt"))
        for el in (*find("GrpHdr"), *find("PmtInf")):
            n, c = (next((k.text for k in el if name(k) == w), None) for w in ("NbOfTxs", "CtrlSum"))
            if n is not None and int(n) != len(txs):
                wrong.append(f"{name(el)}/NbOfTxs says {n}; the file holds {len(txs)} transfers")
            if c is not None and cents(c) != total:
                wrong.append(f"{name(el)}/CtrlSum says {c}; the transfers come to {total // 100}.{total % 100:02d}")
    except (ValueError, TypeError):
        wrong.append("a count or an amount is not a number")
    if len(set(e2e)) != len(e2e):
        wrong.append("two transfers share an end-to-end id")
    if len({e.get("Ccy") for e in find("InstdAmt")}) > 1:
        wrong.append("the transfers are in more than one currency")
    return wrong


# ---- what the bank answers ------------------------------------------------------------------------------------------

def read_status(data: bytes) -> list[dict]:
    """A bank's answer as rows: [{"end_to_end" (empty: the whole file named by "message"), "message", "result": paid |
    failed | pending, "code", "reason", "reference", "on"}]. A customer payment status report (pain.002) is read by
    element name, whatever its version; a CSV by its header (STATUS_HEAD: the first two columns are needed)."""
    try:
        said = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Refused("The status file is not UTF-8 text.") from None
    if not said.lstrip().startswith("<"):
        rows = list(csv.DictReader(io.StringIO(said)))
        if not rows or not {"end_to_end_id", "status"} <= set(rows[0]):
            raise Refused(f"A status CSV has the columns {', '.join(STATUS_HEAD)}; the first two are needed.")
        out = []
        for n, r in enumerate(rows, 2):
            word = (r["status"] or "").strip().lower()
            if word not in WORDS:
                raise Refused(f"Status file line {n}: {r['status']!r} is not a status. Write paid, failed or pending, or the bank's own code (ACSC, RJCT).")
            out.append({"end_to_end": (r["end_to_end_id"] or "").strip(), "message": "", "result": WORDS[word], "code": (r["status"] or "").strip(),
                        "reason": (r.get("reason") or "").strip(), "reference": (r.get("reference") or "").strip(), "on": (r.get("date") or "").strip()[:10]})
        return out
    if "<!DOCTYPE" in said or "<!ENTITY" in said:
        raise Refused("The status file declares a document type: a bank's status report has none. It was not read.")
    try:
        root = ET.fromstring(said.encode("utf-8"))
    except ET.ParseError as why:
        raise Refused(f"The status file is not well-formed XML: {why}") from None
    name = lambda el: el.tag.split("}", 1)[-1]                                       # noqa: E731
    one = lambda el, what: next(((e.text or "").strip() for e in el.iter() if name(e) == what), "")      # noqa: E731
    if not any(name(e) == "CstmrPmtStsRpt" for e in root.iter()):
        raise Refused("The status file is not a customer payment status report (pain.002): it has no CstmrPmtStsRpt.")
    message = one(root, "OrgnlMsgId")

    def row(el, e2e: str, code: str) -> dict:
        why = next((e for e in el if name(e) == "StsRsnInf"), None)
        reason = " ".join(x for x in ((one(why, "Cd") or one(why, "Prtry")), one(why, "AddtlInf")) if x) if why is not None else ""
        return {"end_to_end": e2e, "message": message, "result": WORDS.get(code.lower(), "unknown"), "code": code or "none", "reason": reason,
                "reference": one(el, "AcctSvcrRef"), "on": one(el, "AccptncDtTm")[:10]}

    out = [row(tx, one(tx, "OrgnlEndToEndId"), one(tx, "TxSts")) for tx in root.iter() if name(tx) == "TxInfAndSts"]
    if not out:                                               # the bank answered for the whole file, or the whole batch
        for where, what in (("OrgnlPmtInfAndSts", "PmtInfSts"), ("OrgnlGrpInfAndSts", "GrpSts")):
            got = [(el, one(el, what)) for el in root.iter() if name(el) == where and one(el, what)]
            if got:
                return [row(el, "", code) for el, code in got]
        raise Refused("The status report names no transfer and no status for the file: there is nothing to record.")
    return out


def apply(st: dict, status: dict | None, rows: list[dict], on: str) -> tuple[dict, list[str]]:
    """(the status with what the bank said recorded, what was done in words). A settled transfer marks each of its
    lines paid outside Knos, with the end-to-end id as the settlement; a rejected one marks them payable again with the
    bank's reason, so the next instruction file names them; a pending one records nothing; an answer that is not clear
    holds them as unknown (see the module's text). A transfer no instruction of this statement names is said and
    skipped. What is already recorded is not recorded again."""
    from . import statement as S
    status = S._status(st, status)
    known: dict[str, dict] = {}
    for e in status["events"]:
        if e["type"] == "instruction":
            for t in e["transfers"]:
                known[t["end_to_end"]] = {**t, "message": e["message"]}
    if not known:
        raise Refused("No payment file was written for this statement, so no bank status belongs to it. `knos statement pay --rail bank` writes one.")
    events, said = list(status["events"]), []
    deliverable = {ln["invoice_line"]: ln["deliverable"] for ln in st["lines"]}
    for r in rows:
        mine = [known[r["end_to_end"]]] if r["end_to_end"] in known else [t for t in known.values() if not r["end_to_end"] and t["message"] == r["message"]]
        if not mine:
            said.append(f"{r['end_to_end'] or r['message'] or '(no id)'}: no payment file of this statement names it; skipped")
            continue
        for t in mine:
            if r["result"] == "pending":
                said.append(f"{t['end_to_end']}: still with the bank ({r['code']}); nothing recorded")
                continue
            day = S._day(r["on"] or on)
            why = " ".join(x for x in (r["code"], r["reason"]) if x) or "no status"
            done, twice = 0, []
            for line in t["lines"]:
                last = next((e for e in reversed(events) if e["type"] == "settlement" and e["line"] == line), None)
                event = {"type": "settlement", "line": line, "deliverable": deliverable[line], "settlement": t["end_to_end"], "method": "bank",
                         "reference": r["reference"] or t["end_to_end"], "on": day, "rail": MESSAGE}
                if r["result"] == "unknown":
                    if last is not None and last.get("unknown") and last["settlement"] == t["end_to_end"]:
                        continue
                    event.update({"reference": f"no clear answer ({why})", "state": "held", "unknown": why,
                                  "note": f"the bank's answer is not clear ({why}): the money may have left; no new payment file names this line "
                                          "until a status file says paid or returned"})
                else:
                    state = "paid_outside" if r["result"] == "paid" else "payable"
                    mine_last = next((e for e in reversed(events) if e["type"] == "settlement" and e["line"] == line and e["settlement"] == t["end_to_end"]), None)
                    if mine_last is not None and mine_last["state"] == state:
                        continue
                    if state == "paid_outside" and any(e["type"] == "settlement" and e["line"] == line and e["state"] == "paid_outside"
                                                       and e["settlement"] != t["end_to_end"] for e in events):
                        twice.append(line)
                    event["state"] = state
                    if state == "payable":
                        event.update({"returned": why, "note": f"the bank returned this payment: {why}"})
                events.append(event)
                done += 1
            n = f"{done} {'line' if done == 1 else 'lines'}"
            if r["result"] == "unknown":
                said.append(f"{t['end_to_end']}: the answer is not clear ({why}): {n} held as unknown; no new payment file names them until a status "
                            "file says paid or returned" if done else f"{t['end_to_end']}: already held as unknown; nothing changed")
                continue
            words = f"paid, {t['amount']} {t['currency']} to {t['supplier']}" if r["result"] == "paid" else f"returned by the bank ({r['code']} {r['reason']}".rstrip() + "): payable again"
            said.append(f"{t['end_to_end']}: {words}; {n} recorded" if done else f"{t['end_to_end']}: already recorded; nothing changed")
            if twice:
                said.append(f"{t['end_to_end']}: PAID TWICE: {', '.join(twice)} {'was' if len(twice) == 1 else 'were'} paid already under another end-to-end id; "
                            "ask the supplier to return one payment")
    return {**status, "events": events}, said


def instruct(st: dict, status: dict | None, payer: dict) -> tuple[dict, str, list[dict]]:
    """(the status with the instruction recorded, the file's text, its transfers). The record keeps the file's hash and
    which lines each transfer pays, so a status report finds its lines and no line is instructed twice."""
    from . import statement as S
    status = S._status(st, status)
    xml, found, msg = pain001(st, status, payer)
    used = {t["end_to_end"] for e in status["events"] if e["type"] == "instruction" for t in e["transfers"]}
    again = [t["end_to_end"] for t in found if t["end_to_end"] in used] + ([msg] if any(e["type"] == "instruction" and e["message"] == msg for e in status["events"]) else [])
    if again:                                                 # one settlement id, one instruction: never a second file for it
        raise Refused(f"An earlier payment file already used {', '.join(again)}. A second instruction under the same id could pay twice; nothing was written.")
    wrong = check(xml)
    if wrong:                                                 # never hand over a file the checker would not take
        raise Refused("The payment file does not hold to the message's structure: " + "; ".join(wrong[:3]))
    total = sum(t["units"] for t in found)
    event = {"type": "instruction", "rail": "bank", "format": MESSAGE, "message": msg, "on": S._day(str(payer["on"])), "execute": str(payer.get("execute") or payer["on"]),
             "sha256": hashlib.sha256(xml.encode("utf-8")).hexdigest(), "amount": f"{total // 100}.{total % 100:02d}", "currency": found[0]["currency"],
             "transfers": [{k: t[k] for k in ("end_to_end", "supplier", "amount", "currency", "lines")} for t in found]}
    return {**status, "events": [*status["events"], event]}, xml, found


def accepted_rows(st: dict, status: dict | None = None) -> list[dict]:
    """What a month's bill takes (knos.billing.invoice, `accepted`): one row per agreed deliverable that was paid,
    whichever rail paid it and however many records say so. `on_chain` is true when the program released it: the fee
    was taken there and is not charged again."""
    from . import statement as S
    events = S._status(st, status)["events"]
    out: dict[str, dict] = {}
    for ln in S.lines_now(st, status):
        if ln["state"] != "agreed" or ln["payment"] not in ("paid_outside", "devnet_demonstration") or not ln["amount"]:
            continue
        chain = any(e["type"] == "settlement" and e["line"] == ln["invoice_line"] and e["method"] == "chain" for e in events)
        row = out.setdefault(ln["deliverable"], {"deliverable": ln["deliverable"], "value": ln["amount"], "on_chain": False, "payee": ln["supplier"]})
        row["on_chain"] = row["on_chain"] or chain
    return list(out.values())


def read_payees(said: str) -> dict[str, dict]:
    """The payees file: `supplier,name,account,bic`, one row a supplier. The supplier is the statement's own word for it."""
    rows = list(csv.DictReader(io.StringIO(said)))
    if not rows or not {"supplier", "account"} <= set(rows[0]):
        raise Refused("The payees file has the columns supplier,name,account,bic; supplier and account are needed.")
    return {(r["supplier"] or "").strip(): {"name": (r.get("name") or "").strip(), "account": (r["account"] or "").strip(), "bic": (r.get("bic") or "").strip()}
            for r in rows if (r["supplier"] or "").strip()}
