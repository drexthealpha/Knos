"""A badge and a track record, both read from the chain and neither saying more than the receipt does.

    knos badge <owner/repo>        an SVG: "paid on proof", and how many payments the program made for pull requests
                                   to that repository, in which money, as of which day
    knos badge <owner/repo>#<pr>   an SVG: what that pull request was paid, in which money, on which day
    knos record <login or id>      knos_pay's reputation account for a payee (state.rs R_*), with its caveats
    knos record build <supplier>   a supplier's public record file, docs/records/<slug>.json (knos.record_page, docs/RECORD.md)
    knos record receipt <file>     an acceptance receipt as one PDF page and JSON, to send with an invoice
    knos badge record <slug>       an SVG from a supplier's record file, in the same drawing as the two above

`knos badge` writes the SVG to a file and prints the Markdown that shows it and links it to the repository's record on
the site (r/<owner>/<repo>.html, the page that lists every payment with its transaction). The SVG is one file with no
script, no link and no font of its own: text is drawn in whatever sans-serif the reader has, at a fixed width.

A badge states its scope and its date. A count is "as of" a day, because the next payment changes it; a payment has
the day it was made. On devnet all money is test USDC and the badge says so. "Paid" means the funder's named checks
passed at the merge and the program paid: it is an event, not a score of the work.

The comment Knos posts after a settlement that paid ends with one badge line (`said`, called by knos.flow.settle). A comment cannot carry a
file, so that picture is drawn by shields.io from the words in its own address; nothing is fetched from Knos.

web/badge.js draws the same badge (`badgeSvg`, byte for byte: tests/test_badge.py) and the same record for the site.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.parse
from decimal import Decimal
from pathlib import Path

SITE = "https://drexthealpha.github.io/Knos"
LABEL = "paid on proof"
TEST = "test USDC"

CAVEATS = (
    "Paid is an event: a funder's named checks passed at a merge and the program paid. It is not a score of the work.",
    "Distinct funders counts different funders. Ten payments from one funder add one.",
    "Payments in the faucet's test money and payments an account funded itself are shown apart and are not in the headline.",
)
DEVNET = "Solana devnet: every amount here is test USDC, not money."
# The Knos mark at the left of a badge: the small copy of web/brand/src/knos-mark.svg, set 12 units high. One line, and
# scripts/brand.py writes it (web/brand/mark.js holds the same for web/badge.js; tests/test_brand.py compares them).
MARK: dict = {"d": "M372 1661c-2-12 15-28 20-39 20-45 47-89 72-131 41-71 78-145 117-220 29-55 62-109 91-164 17-31 67-140 89-157 17-14 64-32 86-43 76-36 213-112 253-188 28-54 48-112 38-175-4-23-13-44-18-66-2-10-13-18-12-29 7-16 50-57 64-71 72-74 139-129 250-113 61 9 86 42 136 57 41 12 81 22 120 39 16 7 39 29 50 33 8 3 43 39 36 46-7 1-57-24-70-27-42-13-85-14-129-14-9 0-63-1-61 7 1 2 48 2 51 2 46 0 99 0 143 15 6 2 37 9 38 15-5 7-54 6-64 7-35 2-106 0-136 12-9 3-18 14-26 20-72 66-73 142-99 229-21 70-58 136-106 192-64 73-142 125-226 166-29 14-157 57-171 71-11 12-16 57-21 74-15 62-32 124-46 187-3 16-11 69-20 78-11 8-81 31-94 31 10-57 27-113 41-169 2-9 14-52 10-54-4 3-20 56-23 65-10 29-63 188-76 200-9 6-119 50-122 48-1-2 26-65 30-73 33-65 60-144 90-213 3-9 30-76 34-78 2-1 1-3 0-4-4-1-16 26-17 30-9 5-47 89-54 104-20 44-49 86-68 129-11 26-50 112-66 130-9 11-84 27-102 33-5 2-29 12-32 8zM1020 1127c4-6 50-19 60-23 34-15 85-35 114-58 11-9 27-21 40-26 8-2 62 78 72 91 75 98 147 198 219 298 20 28 48 55 63 86 2 5 18 19 15 24-100 2-200 1-300 1-37-46-69-95-104-142-39-51-79-102-114-155-8-12-67-89-65-96zM811 761c-12-2-99 44-121 47-22 3-85-43-103-58-7-6-47-41-47-48 2-3 35-6 41-7 43-9 87-14 131-21 15-3 30-5 45-7 1 0 4 0 3-2-90-1-180-1-270-1-20 0-117-94-133-114-4-6-28-36-27-41 12-6 68 4 85 6l227 20c16 1 69 14 81 7-1-2-26-5-30-6-33-4-65-12-98-19-67-14-134-28-201-41-22-4-87-12-103-20-22-12-28-39-45-54-10-9-63-103-58-110 3-2 85 19 95 22 88 25 180 32 267 59 21 6 93 27 111 27 1 0 3 0 4-1 0-1-3-2-4-3-33-15-71-21-105-33-66-23-133-44-200-63-50-15-98-36-149-48-12-3-35-9-45-16-15-12-46-73-50-92-2-7-22-45-14-48 14 0 35 11 49 16 68 21 136 41 204 63 145 47 294 86 439 134 88 29 185 43 252 113 39 41 62 94 62 150 1 142-117 228-232 284-25 13-99 60-121 60 0-25 36-90 46-116 3-6 19-34 14-39zM676 402c-1-3-7-3-9-1 1 3 8 4 9 1zM1417 336c-5 7-6 17-5 25 15 41 73-13 31-29-8-3-20-1-26 4z", "transform": "translate(4.31 3.27) scale(0.00764)", "width": 13}  # written by scripts/brand.py


def _day(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(t))


def _s(n: int) -> str:
    return "" if n == 1 else "s"


def _amount(units: int) -> str:
    """Millionths as money is written, with two decimals or as many as it takes (as knos.flow writes a comment)."""
    whole, part = divmod(int(units), 1_000_000)
    return f"{whole}.{f'{part:06d}'.rstrip('0').ljust(2, '0')}"


# ---- the badge -------------------------------------------------------------------------------------------------------

def message(data: dict) -> str:
    """What the right half says: the scope and the date, and nothing the receipt does not say."""
    if data.get("pr"):
        return f"#{data['pr']}: {data['amount']} {data['money']}, {data['date']}"
    n = int(data["count"])
    other = int(data.get("other") or 0)
    return (f"{n} payment{_s(n)} in {data['money']}" + (f", {other} in another token" if other else "")
            + f", as of {data['as_of']}")


def title(data: dict) -> str:
    """The accessible title: the same facts as a sentence, and what they do not mean."""
    if data.get("pr"):
        return (f"Paid on proof: pull request #{data['pr']} of {data['repo']} was paid {data['amount']} {data['money']} on "
                f"{data['date']} (UTC), after the checks its funder named passed at the merge. This is a payment, not a score of the work.")
    n = int(data["count"])
    return (f"Paid on proof: {n} payment{_s(n)} in {data['money']} for pull requests to {data['repo']}, as of {data['as_of']} "
            "(UTC). Each was made after the checks its funder named passed at the merge. This is a count of payments, not a score of the work.")


def _width(text: str) -> int:
    """A fixed width for the text, so the badge is the same size in any font (textLength makes the text fit it)."""
    return round(len(text) * 6.4) + 12


def _draw(label: str, msg: str, tip: str, colour: str) -> str:
    m = MARK["width"] + 7                                                # the mark, 5 from the edge and 2 before the words
    a, b = _width(label) + m, _width(msg)
    e = html.escape
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{a + b}" height="20" viewBox="0 0 {a + b} 20" role="img" '
            f'aria-label="{e(label)}: {e(msg)}"><title>{e(tip)}</title>'
            f'<rect width="{a}" height="20" fill="#24292f"/><rect x="{a}" width="{b}" height="20" fill="{colour}"/>'
            f'<g fill="#fff" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">'
            f'<path fill-rule="evenodd" transform="{MARK["transform"]}" d="{MARK["d"]}"/>'
            f'<text x="{(a + m) / 2:g}" y="14" textLength="{a - m - 12}">{e(label)}</text>'
            f'<text x="{a + b / 2:g}" y="14" textLength="{b - 12}">{e(msg)}</text></g></svg>\n')


def svg(data: dict) -> str:
    """The badge, self-contained: no script, no link, no font file. web/badge.js `badgeSvg` writes the same bytes."""
    colour = "#57606a" if data.get("money") == TEST else "#1a7f37"       # test money is grey; green is kept for real money
    return _draw(LABEL, message(data), title(data), colour)


# ---- the "Knos-verified" badge ---------------------------------------------------------------------------------------
# Issued from one acceptance receipt that checks, and from nothing else. There is no other way to get one.

VERIFIED_LABEL = "Knos-verified"
NOT_FOR_SALE = "This badge is issued only from a receipt that checks. It cannot be bought, and the party it is about never pays for it."


def verified(receipt, digest: str | None = None, disputed: bool = False) -> dict:
    """Whether one deliverable gets the badge, and the evidence it links to. `receipt`: an acceptance receipt
    (docs/RECEIPT.md). `digest`: the digest the receipt was published under, when the caller has one; a receipt that
    does not hash to it gets no badge. `disputed`: somebody contested the verdict and nobody resolved it yet.

    Returns {issued, verdict, words, why, digest, repository_id, pull_request, commit, evidence, note}. `issued` is
    True only for a receipt that passes every rule of `knos.receipt.check` and whose verdict is accepted. `verdict`
    is one of knos.ids.VERDICTS: a receipt that does not check is insufficient evidence, never a rejection."""
    from . import ids
    from . import receipt as rc
    out: dict = {"issued": False, "verdict": "insufficient_evidence", "why": "", "digest": None, "repository_id": None, "pull_request": None,
                 "commit": None, "evidence": [], "note": NOT_FOR_SALE}
    why = rc.check(receipt)
    if why is None and receipt.get("version", 1) < 2:
        why = "a version 1 receipt names no verdict: upgrade it (knos.receipt.upgrade) and check again"
    if why is None and digest is not None and rc.digest(receipt) != digest.lower():
        why = "the receipt does not hash to the digest it was published under"
    if why is None:
        seen = receipt["evaluator_observed"]
        out["verdict"] = "disputed" if disputed else ids.verdict(seen["verdict"])
        out.update(digest=rc.digest(receipt), repository_id=(receipt.get("repository") or {}).get("id"),
                   pull_request=seen["artifact"].get("pull_request"), commit=seen["artifact"].get("commit"))
        on = {"devnet": "?cluster=devnet", "testnet": "?cluster=testnet", "mainnet": "", "mainnet-beta": ""}.get(str(receipt.get("cluster")))
        tx = ((receipt.get("issuer_authenticated") or {}).get("verified") or {}).get("transaction")
        if on is not None and tx:           # a local or unknown cluster has no public page: the digest is the evidence
            out["evidence"].append({"what": "the transaction in which the signature was verified", "url": f"https://explorer.solana.com/tx/{tx}{on}"})
            out["evidence"].append({"what": "the order's account", "url": f"https://explorer.solana.com/address/{receipt['order']}{on}"})
        why = "somebody contested this verdict and nobody has resolved it" if disputed else ""
    out["issued"] = out["verdict"] in ids.BILLABLE and not why
    out["words"], out["why"] = ids.VERDICT_WORDS[out["verdict"]], why or ""
    return out


def verified_message(v: dict) -> str:
    what = f"#{v['pull_request']}" if v.get("pull_request") else str(v.get("commit") or "")[:12]
    return f"{what}: {v['words']}, receipt {str(v['digest'])[:12]}"


def verified_svg(v: dict) -> str:
    """The badge for a result `verified` issued. ValueError for anything else: there is no badge for a verdict that
    is not accepted. web/badge.js `verifiedSvg` writes the same bytes."""
    if v.get("issued") is not True or v.get("verdict") != "accepted" or not v.get("digest"):
        raise ValueError(f"no badge: {v.get('why') or v.get('words') or 'no receipt that checks'}")
    tip = (f"Knos-verified: the acceptance receipt {v['digest']} checks and its verdict is accepted. It says the agreed checks passed, "
           f"not that the work is good. {NOT_FOR_SALE}")
    return _draw(VERIFIED_LABEL, verified_message(v), tip, "#1a7f37")


def verified_markdown(v: dict, image: str) -> str:
    """The line to paste: the badge, linked to the first piece of evidence (or to the receipt's specification)."""
    to = v["evidence"][0]["url"] if v.get("evidence") else "https://github.com/drexthealpha/Knos/blob/main/docs/RECEIPT.md"
    return f"[![{VERIFIED_LABEL}: {verified_message(v)}]({image})]({to})"


def receipt_url(repo: str) -> str:
    """The repository's record on the site: every payment for it, each with its transaction."""
    return f"{SITE}/r/{urllib.parse.quote(repo)}.html"


def markdown(data: dict, image: str) -> str:
    """The line to paste: the picture at `image` (a path in the repository, or a URL), linked to the record."""
    return f"[![{LABEL}: {message(data)}]({image})]({receipt_url(data['repo'])})"


def _shield(text: str) -> str:
    return urllib.parse.quote(text.replace("-", "--").replace("_", "__").replace(" ", "_"), safe="")


def comment_line(data: dict) -> str:
    """The badge line of a comment: a picture shields.io draws from the words in the address, linked to the record."""
    return markdown(data, f"https://img.shields.io/badge/{_shield(LABEL)}-{_shield(message(data))}-{'57606a' if data.get('money') == TEST else '1a7f37'}")


_PAID = re.compile(r"\b(?:received|paid) (\d[\d,]*\.\d+) test USDC\b")
_LEAD = re.compile(r"^(?:Knos: )?[Pp]aid\. ")


def said(repo: str, number: int, text: str, now: float) -> str:
    """The comment after a settlement, with one badge line at its end when it says a payment reached a wallet; any
    other comment as it was. A comment has one paragraph per bounty: the badge adds up the ones that begin "paid.",
    in the comment's own figures, so it cannot say more than the comment above it."""
    paid = [got[1] for part in text.split("\n\n") if _LEAD.match(part) and (got := _PAID.search(part))]
    if not paid or not number:
        return text
    units = sum(int(Decimal(p.replace(",", "")) * 1_000_000) for p in paid)
    return text + "\n\n" + comment_line({"repo": repo, "pr": int(number), "amount": _amount(units), "money": TEST, "date": _day(now)})


def from_rows(repo: str, pr: int | None, rows: list[dict], now: float) -> dict | None:
    """A badge's data from the receipts of one repository (knos.records.payments rows). None: nothing was paid there."""
    if pr:
        mine = [r for r in rows if str(r.get("pull_request") or "") == str(pr) and r["currency"] == TEST]
        if not mine:
            return None
        return {"repo": repo, "pr": pr, "amount": _amount(sum(r["amount_units"] for r in mine)),
                "money": TEST, "date": max(r["date"] for r in mine)}
    return {"repo": repo, "pr": None, "count": sum(1 for r in rows if r["currency"] == TEST), "money": TEST,
            "other": sum(1 for r in rows if r["currency"] != TEST), "as_of": _day(now)}


# ---- the record ------------------------------------------------------------------------------------------------------

def record_view(rep, github_id: int, login: str = "", devnet: bool = True) -> dict:
    """knos_pay's reputation account as the page and the command show it. `rep`: knos.settle.v2.pay.Record. The
    headline holds only payments from someone else in money that is not the faucet's; the other two counts stay apart."""
    usd = _amount
    return {"github_id": github_id, "login": login, "cluster": "devnet" if devnet else "mainnet",
            "money": TEST if devnet else "USDC",
            "headline": {"paid": rep.paid, "distinct_funders": rep.funders, "total": usd(rep.total),
                         "first": _day(rep.first) if rep.paid and rep.first else None,
                         "last": _day(rep.last) if rep.paid and rep.last else None},
            "apart": {"test_paid": rep.test_paid, "test_total": usd(rep.test_total), "self_paid": rep.self_paid},
            "caveats": [*CAVEATS, *([DEVNET] if devnet else [])]}


def record_lines(v: dict) -> list[str]:
    h, a, who = v["headline"], v["apart"], v["login"] or f"GitHub id {v['github_id']}"
    lines = [f"{who} (GitHub id {v['github_id']}): the record knos_pay keeps on Solana {v['cluster']} (the second deployment)."]
    if h["paid"]:
        lines.append(f"Paid {h['paid']} time{_s(h['paid'])} by {h['distinct_funders']} distinct funder{_s(h['distinct_funders'])}: "
                     f"{h['total']} {v['money']} in all, first {h['first']}, last {h['last']}.")
    else:
        lines.append("No payment from someone else is recorded. Nothing recorded is not the same as nothing done.")
    lines.append(f"Shown apart, not in the count above: {a['test_paid']} payment{_s(a['test_paid'])} in the faucet's test money "
                 f"({a['test_total']} {TEST}); {a['self_paid']} payment{_s(a['self_paid'])} this account funded itself "
                 "(the program keeps their number, not their amount).")
    return lines + [f"  - {c}" for c in v["caveats"]]


# ---- the two commands ------------------------------------------------------------------------------------------------

def register(app) -> None:
    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    @app.command("badge")
    def badge_cmd(where: str = typer.Argument(..., help="owner/repo, or owner/repo#<pull request>; or `record <slug>` for a supplier's record"),
                  what: str = typer.Argument("", help="with `record`: the supplier's slug, or the path of its record file"),
                  records_dir: Path = typer.Option(Path("docs/records"), "--records", help="with `record`: the folder the record files are in"),
                  to_file: Path = typer.Option(None, "--out", help="where the SVG is written (default: knos-paid.svg, or knos-paid-<pr>.svg)"),
                  limit: int = typer.Option(1000, "--limit", help="how many of each escrow's newest transactions to read (at most 1000)")) -> None:
        """Write a "paid on proof" badge (an SVG) for a repository or one pull request, and print the Markdown that links it to the record."""
        from . import cli, records
        if where == "record":
            record_page = importlib.import_module("knos.record_page")     # named, not imported: it reads the memory engine, which a job that signs does not install
            path = Path(what) if what.endswith(".json") else records_dir / f"{what}.json"
            if not what or not path.is_file():
                raise cli.Stop(f"There is no record file at {path}.", "Write it first: knos record build <supplier>")
            doc = json.loads(path.read_text(encoding="utf-8"))
            why = record_page.check(doc)
            if why:
                raise cli.Stop(f"{path} is not a record to draw a badge from: {why}.", "Write it again: knos record build <supplier>")
            image = to_file or Path(f"knos-record-{doc['supplier']}.svg")
            image.write_text(record_page.badge_svg(doc), encoding="utf-8", newline="\n")
            b = record_page.badge_data(doc)
            cli.err.print(f"Wrote {image}: {b['label']}: {b['message']}. Commit it, then paste this line:", markup=False)
            typer.echo(record_page.badge_markdown(doc, image.as_posix()))
            return
        repo, _, n = where.partition("#")
        if repo.count("/") != 1 or (n and not n.isdigit()):
            raise cli.Stop("Name the repository as owner/repo, or one pull request as owner/repo#12.")
        repo_id = int(cli._github(f"repos/{repo}")["id"])
        rows = [r for r in records.payments(cli._history(limit).events) if r["repository_id"] == repo_id]
        data = from_rows(repo, int(n) if n else None, rows, time.time())
        if data is None:
            raise cli.Stop(f"No payment for pull request #{n} of {repo} is in the history read from Solana devnet, so there is no badge to write.",
                           f"See what was paid there: {receipt_url(repo)}")
        path = to_file or Path(f"knos-paid-{n}.svg" if n else "knos-paid.svg")
        path.write_text(svg(data), encoding="utf-8", newline="\n")
        cli.err.print(f"Wrote {path}: {LABEL}: {message(data)}. Commit it, then paste this line:", markup=False)
        typer.echo(markdown(data, path.as_posix()))

    @app.command("record")
    def record_cmd(who: str = typer.Argument(..., help="a GitHub login, or a GitHub user id; or `build <supplier>`, or `receipt <acceptance receipt file>`"),
                   what: str = typer.Argument("", help="with `build`: the supplier's name; with `receipt`: the acceptance receipt's file"),
                   out: Path = typer.Option(None, "--out", help="build: the folder to write (default docs/records); receipt: the files' path without the ending"),
                   index: Path = typer.Option(Path("docs/index.json"), "--index", help="build: the Agent PR Index feed, for an agent it measures"),
                   events_log: Path = typer.Option(None, "--events", help="build: the events log to count work settled through Knos from (default: KNOS_EVENTS)"),
                   supplier_id: list[str] = typer.Option([], "--id", help="build: a name the supplier has in the events log (repeat it; default: the supplier's name)"),
                   memory: Path = typer.Option(None, "--memory", help="build: the folder of the Sibyl store to recall the supplier from"),
                   repo: list[str] = typer.Option([], "--repo", help="build: a repository to recall the supplier in, owner/repo (repeat it)"),
                   as_of: str = typer.Option(None, "--as-of", help="build: the day to write in the file, YYYY-MM-DD"),
                   invoice: str = typer.Option("", "--invoice", help="receipt: the number of the invoice it goes with"),
                   as_json: bool = typer.Option(False, "--json", help="the record as JSON (what web/badge.js renderRecord reads)")) -> None:
        """A payee's record as knos_pay keeps it on Solana: paid, distinct funders, first and last, with test money and self-paid shown apart."""
        from . import cli
        if what and who in ("build", "receipt"):
            from . import events
            record_page = importlib.import_module("knos.record_page")     # named, not imported (as above)
            try:
                if who == "build":
                    path, doc = record_page.run_build(what, out or Path("docs/records"), index, events.where(events_log), supplier_id, memory, repo, as_of)
                    for line in record_page.lines(doc):
                        cli.out.print(line, markup=False)
                    cli.err.print(f"Wrote {path}. Its page: {doc['links']['page']}. Its badge: knos badge record {doc['supplier']}", markup=False)
                else:
                    pdf_path, json_path, doc = record_page.run_receipt(Path(what), out, invoice)
                    cli.out.print(f"Wrote {pdf_path} and {json_path}: {doc['accepted']['words']}, receipt {doc['receipt_sha256']}.", markup=False)
                    cli.out.print(f"Whoever receives it checks the receipt file with no network: {doc['verify']['command']}", markup=False)
            except (OSError, ValueError) as why:
                raise cli.Stop(f"Nothing was written: {why}", "The record's inputs and the receipt's are described in docs/RECORD.md.") from None
            return
        from .settle.v2 import pay
        uid = int(who) if who.isdigit() else int(cli._github(f"users/{who}")["id"])
        v = record_view(pay.read_rep(cli._ledger().account(pay.rep_pda(uid))), uid, "" if who.isdigit() else who,
                        os.environ.get("KNOS_CLUSTER", "devnet") != "mainnet")
        if as_json:
            typer.echo(json.dumps(v, indent=1))
            return
        for line in record_lines(v):
            cli.out.print(line, markup=False)
