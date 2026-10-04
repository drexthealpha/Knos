"""A badge and a track record, both read from the chain and neither saying more than the receipt does.

    knos badge <owner/repo>        an SVG: "paid on proof", and how many payments the program made for pull requests
                                   to that repository, in which money, as of which day
    knos badge <owner/repo>#<pr>   an SVG: what that pull request was paid, in which money, on which day
    knos record <login or id>      knos_pay's reputation account for a payee (state.rs R_*), with its caveats

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


def svg(data: dict) -> str:
    """The badge, self-contained: no script, no link, no font file. web/badge.js `badgeSvg` writes the same bytes."""
    msg, tip = message(data), title(data)
    a, b = _width(LABEL), _width(msg)
    colour = "#57606a" if data.get("money") == TEST else "#1a7f37"       # test money is grey; green is kept for real money
    e = html.escape
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{a + b}" height="20" viewBox="0 0 {a + b} 20" role="img" '
            f'aria-label="{e(LABEL)}: {e(msg)}"><title>{e(tip)}</title>'
            f'<rect width="{a}" height="20" fill="#24292f"/><rect x="{a}" width="{b}" height="20" fill="{colour}"/>'
            f'<g fill="#fff" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">'
            f'<text x="{a / 2:g}" y="14" textLength="{a - 12}">{e(LABEL)}</text>'
            f'<text x="{a + b / 2:g}" y="14" textLength="{b - 12}">{e(msg)}</text></g></svg>\n')


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
    def badge_cmd(where: str = typer.Argument(..., help="owner/repo, or owner/repo#<pull request>"),
                  to_file: Path = typer.Option(None, "--out", help="where the SVG is written (default: knos-paid.svg, or knos-paid-<pr>.svg)"),
                  limit: int = typer.Option(1000, "--limit", help="how many of each escrow's newest transactions to read (at most 1000)")) -> None:
        """Write a "paid on proof" badge (an SVG) for a repository or one pull request, and print the Markdown that links it to the record."""
        from . import cli, records
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
    def record_cmd(who: str = typer.Argument(..., help="a GitHub login, or a GitHub user id"),
                   as_json: bool = typer.Option(False, "--json", help="the record as JSON (what web/badge.js renderRecord reads)")) -> None:
        """A payee's record as knos_pay keeps it on Solana: paid, distinct funders, first and last, with test money and self-paid shown apart."""
        from . import cli
        from .settle.v2 import pay
        uid = int(who) if who.isdigit() else int(cli._github(f"users/{who}")["id"])
        v = record_view(pay.read_rep(cli._ledger().account(pay.rep_pda(uid))), uid, "" if who.isdigit() else who,
                        os.environ.get("KNOS_CLUSTER", "devnet") != "mainnet")
        if as_json:
            typer.echo(json.dumps(v, indent=1))
            return
        for line in record_lines(v):
            cli.out.print(line, markup=False)
