"""`knos gate ...`: the gate of Knos from the command line.

    knos gate init                    write a starting .knos/gate.yml
    knos gate validate [ROOT]         check .knos/gate.yml against its schema
    knos gate schema                  print the JSON Schema
    knos gate seal DIR                seal a hidden-test folder: its sha256 (for gate.yml) and the secret's value (to a file)
    knos gate run ...                 one pull request (what actions/gate runs)
    knos gate receipt verify FILE     check a receipt (JSON, or a receipt page) offline
    knos gate receipt keygen FILE     a new receipt-signing key (prints only its public key)
    knos gate receipt page FILE       a receipt as a page and a badge
    knos gate receipt self ...        a public-tests-only receipt for your own pull request, signed by your own key
    knos gate bounty quote AMOUNT     a bounty's fee and where it goes (the one fee config)
    knos gate bounty treasury MINT    the treasury's fee account for a mint
    knos gate require OWNER/REPO      a ruleset that makes the "Knos Gate" check required (--apply to create it)"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

STARTER = """version: 1
hidden_tests:
  source: secret
  secret: KNOS_GATE_HIDDEN
  sha256: "{sha}"
  into: tests/hidden
  command: python -m pytest -q tests/hidden
  timeout: 600
public_tests:
  command: python -m pytest -q tests
setup: python -m pip install --quiet pytest
scope:
  allow: []
  deny: []
protect: []
on_fail: comment
label: knos-gate-failed
pass_label: ""
outside_only: true
receipt: true
"""


def register(app, help_lines: list | None = None) -> None:
    import importlib
    typer = importlib.import_module("typer")
    if help_lines is not None:
        help_lines.append(("gate", "For a repository's workflows", "The gate of Knos: sealed hidden tests and cheat checks on outside pull requests, reported in one check with a signed receipt."))
    gate = typer.Typer(add_completion=False, help="The gate of Knos: a maintainer's check on outside pull requests (docs/reference/REFEREE.md)")
    app.add_typer(gate, name="gate")
    receipt = typer.Typer(add_completion=False, help="Knos Receipt: signed, offline-verifiable, counts only")
    gate.add_typer(receipt, name="receipt")
    bounty = typer.Typer(add_completion=False, help="Bounties mode: fee quotes and the treasury")
    gate.add_typer(bounty, name="bounty")

    @gate.command("init")
    def init_(root: Path = typer.Argument(Path("."), help="the repository"), force: bool = typer.Option(False, "--force")) -> None:
        """Write a starting .knos/gate.yml (seal your hidden tests with `knos gate seal` and put the sha256 in it)."""
        p = root / ".knos" / "gate.yml"
        if p.exists() and not force:
            typer.echo(f"{p} exists (use --force to replace it)")
            raise typer.Exit(1)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(STARTER.format(sha="0" * 64), encoding="utf-8")
        typer.echo(f"wrote {p}: seal your hidden tests (knos gate seal DIR) and replace hidden_tests.sha256")

    @gate.command("validate")
    def validate_(root: Path = typer.Argument(Path("."), help="the repository")) -> None:
        """Check .knos/gate.yml. Exit 1 with every problem listed."""
        from . import config
        try:
            cfg = config.load(root)
        except config.ConfigError as why:
            typer.echo(f"not valid:\n{why}")
            raise typer.Exit(1) from None
        typer.echo(json.dumps(cfg, indent=1, sort_keys=True))

    @gate.command("schema")
    def schema_() -> None:
        """Print the JSON Schema of .knos/gate.yml."""
        from . import config
        typer.echo(json.dumps(config.SCHEMA, indent=2))

    @gate.command("seal")
    def seal_(folder: Path = typer.Argument(..., help="the hidden tests"),
              secret_out: Path = typer.Option(None, "--secret-out", help="write the secret's value (base64) here")) -> None:
        """Seal a folder of hidden tests: print the sha256 for hidden_tests.sha256. The secret's value is written to a
        file, never printed (store it with `gh secret set KNOS_GATE_HIDDEN < FILE`)."""
        from . import sealed
        bundle = sealed.pack(folder)
        typer.echo(f"sha256 {sealed.seal(bundle)}")
        typer.echo(f"files  {len(__import__('tarfile').open(fileobj=__import__('io').BytesIO(bundle), mode='r:gz').getnames())}")
        typer.echo(f"bytes  {len(bundle)}" + ("" if len(bundle) <= sealed.MAX_BUNDLE else
                                                f" (over a secret's {sealed.MAX_BUNDLE}: use source: repo)"))
        if secret_out:
            fd = os.open(secret_out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(sealed.encode(bundle))
            typer.echo(f"secret value written to {secret_out}")

    @gate.command("run")
    def run_(base: Path = typer.Option(..., "--base", help="the base commit's tree (the config is read here)"),
             pr_dir: Path = typer.Option(..., "--pr", help="the pull request's tree (its tests run here)"),
             diff: Path = typer.Option(..., "--diff", help="git diff base...head"),
             repo: str = typer.Option(..., "--repo"), number: int = typer.Option(..., "--number"),
             head: str = typer.Option(..., "--head"), base_sha: str = typer.Option("", "--base-sha"),
             association: str = typer.Option("NONE", "--association", help="the pull request's author_association"),
             pull_json: Path = typer.Option(None, "--pull-json", help="GitHub's pull request object (for bounty claims)"),
             out_dir: Path = typer.Option(..., "--out"), hidden_dir: Path = typer.Option(None, "--hidden-dir"),
             hidden_file: Path = typer.Option(None, "--hidden-file"), hidden_env: str = typer.Option(None, "--hidden-env"),
             sandbox: str = typer.Option("auto", "--sandbox", help="nonet,user (what actions/gate requires), nonet, auto or none"),
             key_env: str = typer.Option("KNOS_RECEIPT_KEY", "--key-env", help="env var holding the receipt key (JSON array)"),
             key_file: Path = typer.Option(None, "--key-file"), issuer: str = typer.Option("knos-gate", "--issuer"),
             post: bool = typer.Option(False, "--post", help="post the comment and labels with GH_TOKEN"),
             me: str = typer.Option("github-actions[bot]", "--me", help="the login Gate's comment is posted as"),
             code_scanning: bool = typer.Option(False, "--code-scanning", help="with --post: upload the findings as SARIF to GitHub code scanning (needs security-events: write)"),
             annotate: bool = typer.Option(False, "--annotate", help="print the findings as ::error workflow commands (Action mode: annotations on the check)")) -> None:
        """Judge one pull request. Exit 0 passed, 1 refused, 2 Gate could not run."""
        from . import config, run
        kp = None
        raw = os.environ.get(key_env or "", "").strip()
        if key_file:
            raw = key_file.read_text(encoding="utf-8").strip()
        if raw:
            from solders.keypair import Keypair
            kp = Keypair.from_bytes(bytes(json.loads(raw)))
        pull = json.loads(pull_json.read_text(encoding="utf-8")) if pull_json else None
        try:
            got = run.run(base=base, pr_dir=pr_dir, diff=diff.read_text(encoding="utf-8", errors="replace"), repo=repo, pr=number,
                          head=head, base_sha=base_sha, author_association=association, out=out_dir, hidden_env=hidden_env,
                          hidden_file=hidden_file, hidden_dir=hidden_dir, sandbox=sandbox, keypair=kp, issuer_name=issuer, pull=pull)
        except config.ConfigError as why:
            typer.echo(f"Knos Gate cannot run: {why}")
            raise typer.Exit(2) from None
        v = got["verdict"]
        typer.echo(Path(out_dir, "summary.md").read_text(encoding="utf-8"))
        if annotate and Path(out_dir, "annotations.json").exists():
            from . import sarif
            sys.stdout.write(sarif.workflow_commands(json.loads(Path(out_dir, "annotations.json").read_text(encoding="utf-8"))))
        if post:
            up = run.post(got, repo, number, me=me, code_scanning=code_scanning)
            if up:
                typer.echo(f"code scanning: upload {up.get('id', '?')} accepted")
        raise typer.Exit(0 if v["passed"] else 1)

    @receipt.command("verify")
    def verify_(file: Path = typer.Argument(..., help="receipt.json or a receipt page (.html)")) -> None:
        """Check a receipt's signature offline (standard library Ed25519). Exit 1 when it does not hold."""
        from ..receipt2 import core, page
        text = file.read_text(encoding="utf-8")
        env = page.from_page(text) if text.lstrip().startswith("<") else json.loads(text)
        got = core.verify(env)
        r = env.get("receipt", {})
        typer.echo(f"{'VALID' if got['valid'] else 'INVALID'}: {got['why']}")
        typer.echo(f"digest {got['digest']}")
        if got["valid"]:
            typer.echo(f"{r['repository']}#{r['pull_request']} at {r['head'][:12]}: {r['verdict']}"
                       + (f" ({r['rule']})" if r.get("rule") else "") + f"; {r['scope_note']}")
            typer.echo(f"issuer {r['issuer']['name']} {r['issuer']['key']}" + (" (listed)" if got["issuer"] else " (not listed)"))
        if not got["valid"]:
            raise typer.Exit(1)

    @receipt.command("keygen")
    def keygen_(file: Path = typer.Argument(..., help="where the new key goes (never commit it)")) -> None:
        """A new Ed25519 key for signing receipts. Prints only the public key."""
        from ..receipt2 import core
        typer.echo(core.keygen(file))

    @receipt.command("page")
    def page_(file: Path = typer.Argument(...), out_dir: Path = typer.Option(Path("."), "--out")) -> None:
        """Write receipt.html and badge.svg for a signed receipt."""
        from ..receipt2 import page
        env = json.loads(file.read_text(encoding="utf-8"))
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "receipt.html").write_text(page.render(env), encoding="utf-8")
        (out_dir / "badge.svg").write_text(page.badge(env), encoding="utf-8")
        typer.echo(f"wrote {out_dir / 'receipt.html'} and {out_dir / 'badge.svg'}")

    @receipt.command("self")
    def self_(base: Path = typer.Option(..., "--base", help="the base commit's tree"), pr_dir: Path = typer.Option(..., "--pr"),
              diff: Path = typer.Option(..., "--diff"), repo: str = typer.Option(..., "--repo"), number: int = typer.Option(..., "--number"),
              head: str = typer.Option(..., "--head"), command: str = typer.Option(..., "--command", help="the repository's own public test command"),
              key_file: Path = typer.Option(..., "--key-file"), out_dir: Path = typer.Option(Path("knos-receipt"), "--out")) -> None:
        """A receipt for your own pull request against a repository WITHOUT Gate: its own public tests and the cheat
        checks, signed by your own key. The receipt says "public tests only" and that you issued it."""
        from ..receipt2 import core, page
        from . import cheatlib, config, sealed
        from . import verdict as V
        cfg = config.validate({"version": 1, "public_tests": {"command": command}})
        text = diff.read_text(encoding="utf-8", errors="replace")
        findings = cheatlib.scan(text, cfg, base)
        public = None
        if not cheatlib.refused(findings):
            work = out_dir / "work"
            work.mkdir(parents=True, exist_ok=True)
            public = sealed.run(command, pr_dir, work / "public.xml", work / "public.log", sandbox="none")
        v = V.decide(cfg, findings, None, public, repo=repo, pr=number, head=head, base="", library=cheatlib.library())
        kp = core.keypair_from_file(key_file)
        body = core.build(v, issuer_name="self-issued by the pull request's author", issuer_key=str(kp.pubkey()),
                          runner=core.runner_from_env(dict(os.environ)), rules_run=cheatlib.rules_run())
        env = core.sign(body, kp)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "receipt.json").write_text(json.dumps(env, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        (out_dir / "receipt.html").write_text(page.render(env), encoding="utf-8")
        (out_dir / "badge.svg").write_text(page.badge(env), encoding="utf-8")
        typer.echo(f"{v['passed'] and 'passed' or 'refused'} (public tests only); receipt in {out_dir}")
        raise typer.Exit(0 if v["passed"] else 1)

    @gate.command("require")
    def require_(repo: str = typer.Argument(..., help="owner/name"),
                 app_id: int = typer.Option(None, "--app-id", help="only the Knos Gate App's check counts (its App id)"),
                 apply: bool = typer.Option(False, "--apply", help="create or update the ruleset with GH_TOKEN (needs repository administration)")) -> None:
        """Make the "Knos Gate" check required to merge into the default branch (a repository ruleset). Without
        --apply it prints the ruleset and changes nothing."""
        from .github import Client
        try:
            got = Client(repo).require(app_id, apply=apply)
        except OSError as why:
            typer.echo(f"GitHub refused the ruleset: {why}. It needs a token with administration on {repo}.")
            raise typer.Exit(2) from None
        typer.echo(json.dumps(got["ruleset"], indent=1))
        if got["sent"] is not None:
            typer.echo(f"ruleset {got['sent'].get('id', '?')} is active on {repo}: Knos Gate must pass before a merge.")
        else:
            typer.echo("Nothing was changed (add --apply).")

    @bounty.command("quote")
    def quote_(amount: str = typer.Argument(..., help="in test USDC on devnet, like 20 or 12.5"),
               kind: str = typer.Option("job", "--kind", help="job (the fee comes out of it) or order (on top)")) -> None:
        """A bounty's fee and where it goes, read from the one fee config."""
        from decimal import Decimal

        from . import bounty as B
        units = int(Decimal(amount) * 1_000_000)
        typer.echo(json.dumps(B.quote(units, kind), indent=1))

    @bounty.command("treasury")
    def treasury_(mint: str = typer.Argument(...), account: str = typer.Option(None, "--account", help="a job or order account"),
                  old_name: str = typer.Option(None, "--escrow", hidden=True)) -> None:
        """The token account a bounty's fee lands in, for a mint: Knos's Squads vault's."""
        from . import bounty as B
        typer.echo(json.dumps(B.treasury(mint, account or old_name), indent=1))


def main(argv: list[str] | None = None) -> int:      # python -m knos.gate.cli (the Action calls it this way)
    import typer
    app = typer.Typer(add_completion=False)
    register(app)
    try:
        rc = app(args=["gate", *(sys.argv[1:] if argv is None else argv)], standalone_mode=False, prog_name="knos")
        return int(rc) if isinstance(rc, int) else 0
    except SystemExit as e:
        return int(e.code or 0)
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "exit_code", None)
        if code is not None:
            return int(code)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
