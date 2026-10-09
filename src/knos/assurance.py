"""How much stands behind an accepted line: four assurance levels, and four words a statement keeps apart.

The levels, lowest first. A line reaches a level only when its own evidence shows it; nothing here is typed by anyone.

    workflow-reported        GitHub (or GitLab) signed a token for the workflow run, and that run reported the result.
                             The signature names which workflow ran where; the result is the run's word.
    re-executed              an evaluator outside the supplier's control ran the pinned suite again and says so by its
                             run's word (receipt levels `rerun` and `agreed`; `knos judge rerun`, the hermetic judge).
    independently-attested   a party other than the buyer and the supplier signed the result. No such party exists
                             today: no line reaches this level, and none may say it does.
    proved                   a proof of the property itself, checked on chain. Only one thing Knos records is proved in
                             this sense: the forge's signature of the workflow identity, which knos_oidc checks in the
                             transaction that pays. An acceptance result is never proved.

So a line's `level` is at most re-executed today, and `identity_proved` says separately whether the chain checked the
signature of the workflow that reported it. The receipt's own levels (knos.receipt.LEVELS: reported, rerun, agreed,
attested) are read, never rewritten: `FROM_RECEIPT` maps them here.

The four words (`words`):

    agreement        both sides reconstruct the same lines from the recorded events
    completeness     the record has no gap: what the sequence and acknowledgement checks cover, and what nothing checks
    correctness      the acceptance decision matches the terms: the level each line reached says how it was checked
    satisfaction     the buyer got what it wanted commercially: never claimed by Knos, by any level

`knos assurance FILE` prints the levels of a receipt, or of every line of a statement, and the four words."""
from __future__ import annotations

import json
import sys
from pathlib import Path

LEVELS = ("workflow-reported", "re-executed", "independently-attested", "proved")       # in rising order
REACHABLE = ("workflow-reported", "re-executed")        # the levels evidence recorded today can reach
SAYS = {"workflow-reported": "the forge signed which workflow ran; that run reported the result",
        "re-executed": "an evaluator outside the supplier's control ran the pinned inputs again",
        "independently-attested": "a party other than buyer and supplier signed the result: no such party exists today",
        "proved": "a proof of the property itself checked on chain: only the workflow signature is proved; acceptance results never are"}
FROM_RECEIPT = {"reported": "workflow-reported", "rerun": "re-executed", "agreed": "re-executed", "attested": "independently-attested"}
PROVED = "the workflow identity: knos_oidc checked the forge's signature of the token on chain"
NEVER = "The acceptance result is never proved: the chain checks who signed, not whether the tests were right."
NOT_EVALUATED = "not evaluated"
WORDS = ("agreement", "completeness", "correctness", "satisfaction")


def ladder(level: str | None) -> list[dict]:
    """Every level, in order, with whether `level` reaches it."""
    top = LEVELS.index(level) if level in LEVELS else -1
    return [{"level": x, "reached": n <= top, "says": SAYS[x]} for n, x in enumerate(LEVELS)]


def _check(level: str | None) -> str | None:
    if level is not None and level not in REACHABLE:
        raise ValueError(f"assurance level {level} is defined and nothing recorded today reaches it")
    return level


def of_receipt(r: dict, declared=()) -> dict:
    """The assurance of a valid acceptance receipt of any version: {level, receipt_level, identity_proved, proved,
    ladder, never}. `level` is None when no issuer signed the run (a version 4 or 5 receipt whose
    issuer_authenticated is null): it is then not even workflow-reported. `declared`: the control relationships the
    terms declare, as knos.receipt.assurance_of takes them (a version 5 receipt carries its own)."""
    from . import receipt as rc
    why = rc.check(r)
    if why:
        raise ValueError(f"not a valid acceptance receipt: {why}")
    groups = r["assurance"]["declared_related"] if r["version"] == 5 else declared
    was = rc.assurance_of(r, groups)["level"]
    auth = r.get("issuer_authenticated") if r["version"] >= 3 else None
    signed = r["version"] < 4 or auth is not None
    proved = bool(signed and isinstance(auth, dict) and (auth.get("verified") or {}).get("transaction"))
    level = _check(FROM_RECEIPT[was] if signed else None)
    return {"level": level, "receipt_level": was, "identity_proved": proved, "proved": [PROVED] if proved else [],
            "ladder": ladder(level), "never": NEVER}


UNSIGNED_SOURCES = ("shadow",)      # a statement source whose evidence no forge signed (GitHub's answers, read; not signed)


def of_line(ln: dict, goods: dict | None = None, source: str = "") -> dict:
    """The assurance of one statement line (knos.statement.lines_now): from the receipt of goods recorded for it when
    there is one (`goods`, whose `assured` is `of_receipt` of its receipt), else from the line's `assurance` column:
    a receipt level, or "not evaluated". Without a receipt the chain's check of the signature is not shown, so
    identity_proved is False: the line says what its evidence shows, not more. `source`: the statement's; a shadow
    statement's lines (GitHub's answers, which GitHub does not sign) reach no level until a receipt is recorded."""
    kept = (goods or {}).get("assured")
    if isinstance(kept, dict) and "level" in kept:
        return {k: kept[k] for k in ("level", "receipt_level", "identity_proved", "proved", "ladder", "never")}
    was = ln.get("assurance") or (NOT_EVALUATED if not ln.get("evaluations") else "reported")
    level = _check(FROM_RECEIPT.get(was)) if was != NOT_EVALUATED and source not in UNSIGNED_SOURCES else None
    return {"level": level, "receipt_level": was, "identity_proved": False, "proved": [], "ladder": ladder(level), "never": NEVER}


def words(st: dict, lines: list[dict], gaps: list[dict] | None = None, acked: bool | None = None) -> dict:
    """The four words of a statement, kept apart: {word: {"state", "says"}}. `lines`: the statement's lines with
    `assured` (of_line). `gaps`: knos.events.gaps of the month, when the log was read for them; `acked`: whether
    both parties signed the month's last line (knos.period), when that was asked. Nothing is claimed that was not
    checked here: an unchecked property says "not checked" and what would check it."""
    n = len(lines)
    split = sum(1 for x in lines if x.get("state") == "disputed")
    source = st.get("source", "")
    agreement = ({"state": "agreed", "says": f"all {n} line(s) reconstructed the same on both sides"} if not split
                 else {"state": "differs", "says": f"{split} of {n} line(s) differ between the two sides; each says why"})
    if source != "events":
        complete = {"state": "not checked", "says": "this source carries no sequence numbers: a missing event cannot be seen here; "
                    "a log of events (knos events) checks sequence and acknowledgements"}
    elif gaps is None:
        complete = {"state": "not checked", "says": "the log's hash chain was checked; its sequence gaps were not read: `knos events gaps`"}
    else:
        open_ = [g for g in gaps if g.get("state") != "explained"]
        complete = ({"state": "gaps", "says": f"{len(open_)} sequence number(s) missing and not explained by a signed correction"} if open_
                    else {"state": "no gap found" if acked else "no gap found, not acknowledged",
                          "says": "every sequence number arrived or a signed correction explains it"
                          + ("; both parties signed the month's last line" if acked else "; no party's acknowledgement was checked")})
    met = [x for x in lines if x.get("state") == "agreed"]
    levels = [(x.get("assured") or of_line(x, source=source))["level"] for x in met]
    low = min((LEVELS.index(v) for v in levels if v is not None), default=None)
    unsigned = sum(1 for v in levels if v is None)
    correct = {"state": f"at least {LEVELS[low]}" if low is not None and not unsigned else "unchecked lines" if unsigned else "no accepted line",
               "says": (f"{len(met)} accepted line(s): the decision is the evaluator's against the terms hashed at funding; "
                        + (f"the weakest is {LEVELS[low]} ({SAYS[LEVELS[low]]})" if low is not None else "none reaches a level")
                        + (f"; {unsigned} with no signed evaluation" if unsigned else ""))}
    return {"agreement": agreement, "completeness": complete, "correctness": correct,
            "satisfaction": {"state": "not claimed", "says": "whether the buyer got what it wanted is the buyer's to say; no level claims it"}}


def text(doc: dict, status: dict | None = None) -> list[str]:
    """`knos assurance FILE` in lines: a receipt's level, or each line of a statement and the four words."""
    from . import receipt as rc
    if isinstance(doc, dict) and doc.get("type") == rc.TYPE:
        a = of_receipt(doc)
        out = [f"Assurance: {a['level'] or 'none: no issuer signed the run'} (receipt level {a['receipt_level']})."]
        out += [f"  [{'x' if s['reached'] else ' '}] {s['level']}: {s['says']}" for s in a["ladder"]]
        out.append(f"Proved on chain: {a['proved'][0]}." if a["proved"] else "Proved on chain: nothing this receipt records.")
        return [*out, a["never"]]
    if not (isinstance(doc, dict) and isinstance(doc.get("lines"), list) and "source" in doc):
        raise ValueError("not an acceptance receipt or a statement")
    from . import statement as S
    lines = [{**x, "assured": x.get("assured") or of_line(x, source=doc["source"])} for x in S.lines_now(doc, status)]
    out = [f"Statement {doc.get('invoice', '')}: {len(lines)} line(s)."]
    for x in lines:
        a = x["assured"]
        out.append(f"  line {x['line']}: {a['level'] or ('not signed' if a['receipt_level'] != NOT_EVALUATED else NOT_EVALUATED)}" + (" (workflow identity proved on chain)" if a["identity_proved"] else ""))
    out.append("Kept apart:")
    out += [f"  {w}: {v['state']}. {v['says'].capitalize()}." for w, v in words(doc, lines).items()]
    return [*out, NEVER]


def register(app, help_lines: list | None = None) -> None:
    """`knos assurance FILE`, on the main app. `help_lines`: cli._HELP, which gets the command's line."""
    import importlib
    typer = importlib.import_module("typer")       # named here and not imported: this module is standard library only at import
    if help_lines is not None:
        help_lines.append(("assurance", "For money", "How much stands behind a receipt or each statement line: workflow-reported, re-executed, attested, proved."))

    @app.command("assurance")
    def assurance_(file: Path = typer.Argument(..., help="an acceptance receipt, or a statement of `knos statement make`"),
                   status: Path = typer.Option(None, "--status", help="the statement's status file, for recorded goods-received notes"),
                   as_json: bool = typer.Option(False, "--json", help="print JSON")) -> None:
        """Print the assurance level of a receipt, or of every line of a statement, and keep agreement, completeness, correctness and commercial satisfaction apart. Only levels the evidence reaches are shown as reached."""
        try:
            doc = json.loads(file.read_text(encoding="utf-8"))
            st = json.loads(status.read_text(encoding="utf-8")) if status else None
            if as_json:
                from . import receipt as rc
                if doc.get("type") == rc.TYPE:
                    typer.echo(json.dumps(of_receipt(doc), indent=1, sort_keys=True))
                    return
                from . import statement as S
                lines = [{**x, "assured": of_line(x, source=doc["source"])} for x in S.lines_now(doc, st)]
                typer.echo(json.dumps({"lines": [{"line": x["line"], **x["assured"]} for x in lines], "words": words(doc, lines)}, indent=1, sort_keys=True))
                return
            typer.echo("\n".join(text(doc, st)))
        except (OSError, ValueError, KeyError, TypeError) as err:
            typer.echo(f"Cannot read {file}: {err}", err=True)
            raise typer.Exit(2) from None


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m knos.assurance FILE", file=sys.stderr)
        return 2
    print("\n".join(text(json.loads(Path(args[0]).read_text(encoding="utf-8")))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
