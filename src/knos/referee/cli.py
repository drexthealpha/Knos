"""`knos referee seal | works | wanted | makeable | maintainer` and `knos cheats list | red-team`: one line in knos.cli."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PANEL = "For a repository's workflows"


def register(app: Any, help_lines: list | None = None) -> None:
    import importlib
    typer = importlib.import_module("typer")
    if help_lines is not None:
        help_lines.append(("referee", PANEL, "The referee: sealed tests, a locked judge and the cheat rules (Works), demand (Wanted), cost (Makeable)."))
        help_lines.append(("cheats", PANEL, "The cheat library: every rule, and the known cheats each refuses (`cheats red-team`)."))
    ref = typer.Typer(no_args_is_help=True, help="The Knos referee: Works, Wanted, Makeable. A verdict passes only when all three do.")
    app.add_typer(ref, name="referee", rich_help_panel=PANEL)
    lib = typer.Typer(no_args_is_help=True, help="The cheat library: named, tested rules.")
    app.add_typer(lib, name="cheats", rich_help_panel=PANEL)

    def emit(data: dict, out: Path | None) -> None:
        text = json.dumps(data, indent=1, sort_keys=True, default=str)
        if out:
            out.write_text(text + "\n", encoding="utf-8")
        typer.echo(text)

    @ref.command("seal")
    def seal_cmd(bundle: Path = typer.Argument(..., help="the hidden acceptance bundle (kept outside the repository)"),
                 issue: str = typer.Option(..., "--issue"),
                 scope: list[str] = typer.Option([], "--scope", help="a path glob the work may touch (repeat)"),
                 out: Path = typer.Option(None, "--out")) -> None:
        """Seal a task before work starts: the bundle's hash and the hash of the judging code that will judge it."""
        from . import seal, seal_hash
        s = seal(bundle, issue=issue, scope=scope)
        emit({**s, "seal_hash": seal_hash(s)}, out)

    @ref.command("works")
    def works_cmd(base: Path = typer.Option(..., "--base"), pr: Path = typer.Option(..., "--pr"),
                  sealed: Path = typer.Option(..., "--seal", help="the seal's JSON (knos referee seal --out)"),
                  hidden: Path = typer.Option(None, "--hidden", help="the hidden bundle, when the base does not hold it"),
                  sandbox: str = typer.Option("auto", "--sandbox"), out: Path = typer.Option(None, "--out")) -> None:
        """Judge one pull request against a seal. Exit 0 when it works, 1 when not."""
        from . import works
        s = json.loads(sealed.read_text(encoding="utf-8"))
        s.pop("seal_hash", None)
        c = works(base, pr, s, hidden_dir=hidden, sandbox=sandbox)
        emit(c.to_dict(), out)
        raise typer.Exit(0 if c.passed else 1)

    @ref.command("wanted")
    def wanted_cmd(spec_hash: str = typer.Argument(...), min_buyers: int = typer.Option(..., "--min-buyers"),
                   min_locked: int = typer.Option(..., "--min-locked", help="in the currency's smallest unit"),
                   book: Path = typer.Option(None, "--book", help="the demand book (default KNOS_HOME/referee/demand.json)")) -> None:
        """Is the result wanted: N distinct buyers with X held until the proof passes against this spec."""
        from . import DemandBook
        c = DemandBook(book).wanted(spec_hash, min_buyers=min_buyers, min_locked=min_locked)
        emit(c.to_dict(), None)
        raise typer.Exit(0 if c.passed else 1)

    @ref.command("makeable")
    def makeable_cmd(quotes: Path = typer.Argument(..., help="a JSON list of quotes {kind, supplier, unit_cost, quantity, currency, source, valid_until}"),
                     price: float = typer.Option(..., "--price", help="the locked price"),
                     margin: float = typer.Option(0.0, "--margin"), fees: float = typer.Option(0.0, "--fees")) -> None:
        """Can it be made at a profit: the quotes' cost against the locked price."""
        from . import makeable
        c = makeable(json.loads(quotes.read_text(encoding="utf-8")), locked_price=price, min_margin=margin, fees=fees)
        emit(c.to_dict(), None)
        raise typer.Exit(0 if c.passed else 1)

    @ref.command("maintainer")
    def maintainer_cmd(base: Path = typer.Option(..., "--base"), diff: Path = typer.Option(..., "--diff"),
                       mode: str = typer.Option("label", "--mode", help="off, comment, label or close"),
                       scope: list[str] = typer.Option([], "--scope", help="a path glob the issue allows (repeat)"),
                       checks: str = typer.Option("", "--checks", help="passed or failed: the Knos check's result on this pull request (claims and repository rules), when the caller ran it"),
                       out: Path = typer.Option(None, "--out")) -> None:
        """The free maintainer mode: what to label (and, in close mode, whether to close). Runs none of the PR's code.
        Exit 0 always when it decided; the decision is in the JSON."""
        from . import maintainer
        got = maintainer(base, diff.read_text(encoding="utf-8", errors="replace"), scope=scope, mode=mode,
                         checks_passed={"passed": True, "failed": False}.get(checks))
        emit(got, out)

    @lib.command("list")
    def list_cmd(category: str = typer.Option(None, "--category")) -> None:
        """Every rule: id, category, severity, title; and how many known cases each refuses."""
        from .. import cheats
        for r in cheats.rules(category):
            n = sum(1 for c in cheats.CASES if r.id in c.expect)
            typer.echo(f"{r.id:32} {r.category:24} {r.severity:7} {n:3} case(s)  {r.title}")

    @lib.command("red-team")
    def red_team_cmd() -> None:
        """Every known cheat case through the library (needs a source checkout). Exit 1 when one is missed."""
        from .. import cheats
        got = cheats.red_team()
        typer.echo(json.dumps(got))
        raise typer.Exit(0 if not got["missed"] else 1)
