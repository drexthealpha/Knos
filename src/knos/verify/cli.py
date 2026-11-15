"""`knos verify`, on the main command line (registered by knos.cli's module table)."""

from __future__ import annotations

import json
from pathlib import Path

EXIT = {"pass": 0, "fail": 1, "refused": 3}


def register(app, help_lines: list | None = None) -> None:
    import importlib
    typer = importlib.import_module("typer")
    if help_lines is not None:
        help_lines.append(("verify", "For suppliers", "Before you open a pull request: the repository's AI policy, cheat checks, its tests twice, and a signed receipt."))

    @app.command("verify", rich_help_panel="For suppliers")
    def verify_(tree: Path = typer.Option(Path("."), "--tree", help="your checkout, with the change committed (default: here)"),
                base: str = typer.Option("", "--base", help="the branch the change is measured against (default: origin/HEAD, main or master)"),
                tests: str = typer.Option("", "--tests", help="the test command, when the repository's is not found by itself"),
                runs: int = typer.Option(2, "--runs", min=1, max=3, help="how many times the tests run; the re-runs must agree"),
                agent: str = typer.Option("", "--agent", help="the agent's name for the AI-use line (Claude Code, Hermes, OpenClaw, ...)"),
                no_ai: bool = typer.Option(False, "--no-ai", help="the change was made without AI: the AI-use line says so"),
                human_confirmed: bool = typer.Option(False, "--human-confirmed", help="a person confirms the repository's condition for AI-made work is met (conditional policies only; never for banned)"),
                out_file: Path = typer.Option(None, "--out", help="write the receipt here (default: .git/knos/receipt.json)"),
                as_json: bool = typer.Option(False, "--json", help="print the receipt as JSON"),
                check: Path = typer.Option(None, "--check", help="instead, check a receipt file: shape, digest and signature"),
                key: bool = typer.Option(False, "--key", help="instead, print the public key this machine signs receipts with"),
                timeout: int = typer.Option(900, "--timeout", help="seconds each test run may take")) -> None:
        """Run Knos on your committed change before you open a pull request. Reads the repository's AI policy at the
        base (a repository that bans AI-made pull requests is refused, exit 3), runs the cheat checks on the diff,
        runs the repository's own tests twice in a throwaway clone, and writes a signed receipt. Prints the lines to
        paste into the pull request's description. Exit 0 pass, 1 fail, 3 refused."""
        from .. import cli
        from . import Cannot, receipt, tools, verify
        if key:
            cli.out.print(receipt.signer(), markup=False)
            return
        if check is not None:
            got = tools.knos_receipt({"file": str(check)})
            cli.out.print(json.dumps(got, indent=1) if as_json else
                          ("valid" if got["valid"] else "NOT valid: " + "; ".join(got["problems"])) +
                          (f" | verdict {got.get('verdict')} | {got.get('attestation')}" if got["valid"] else ""), markup=False)
            raise typer.Exit(0 if got["valid"] else 1)
        try:
            r = verify(tree, base=base, tests=tests, runs=runs, agent=agent, ai_used=not no_ai, human_confirmed=human_confirmed, timeout=timeout)
        except Cannot as why:
            raise cli.Stop(str(why)) from None
        target = out_file or tools._default_out(tree)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(r, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        if as_json:
            cli.out.print(json.dumps(r, indent=1, sort_keys=True), markup=False)
        else:
            cli.out.print(receipt.markdown(r), markup=False)
            for why in r["reasons"]:
                cli.out.print(f"  - {why}", markup=False)
            if r["ai_policy"]["untrusted"]["lines"]:
                cli.out.print(f"  the policy's words ({r['ai_policy']['file']}), as data: " + " | ".join(r["ai_policy"]["untrusted"]["lines"][:2]), markup=False)
            cli.out.print(f"receipt: {target}", markup=False)
        raise typer.Exit(EXIT[r["verdict"]])
