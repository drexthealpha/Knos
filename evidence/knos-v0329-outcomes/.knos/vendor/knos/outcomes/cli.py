"""`knos outcome ...`: pay for a measured result.

    knos outcome draft "GOAL" --sample data.csv [--out outcome.yaml] [--synthetic] [--llm --llm-key-env NAME]
    knos outcome validate outcome.yaml          every rule the spec breaks, or its hash
    knos outcome hash outcome.yaml              the hash both parties sign and each tier's terms carry
    knos outcome tiers outcome.yaml             one order per tier: address, terms hash, amount, fee; the total escrowed
    knos outcome lock outcome.yaml [--history data.csv] [--out outcome.lock.json]   what is fixed at funding
    knos outcome assign outcome.yaml --data data.csv    who is in the control group (recompute it yourself)
    knos outcome measure outcome.yaml --lock outcome.lock.json [--repo .|--data FILE] [--out result.json] [--record]
    knos outcome sign outcome.yaml --role buyer|seller --keypair wallet.json
    knos outcome verify-signatures outcome.yaml [--file outcome.signatures.json]
    knos outcome comment outcome.yaml           the issue comment: the signed hash, both signatures, the orders
    knos outcome audiences result.json          the pay audience of every tier that passed, one per line
    knos outcome sample outcome.yaml [--n 10000] SYNTHETIC tickets in the window, to try it
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def register(app: Any, help_lines: list | None = None) -> None:
    import importlib
    typer = importlib.import_module("typer")
    if help_lines is not None:
        help_lines.append(("outcome", "For money", "Pay for a measured result: draft the spec, sign it, fund one order per tier, measure."))
    sub = typer.Typer(help="Pay for a result measured from data (lift over a randomized control group), in tiers under a hard cap. Devnet only.",
                      no_args_is_help=True)
    app.add_typer(sub, name="outcome", rich_help_panel="For money")

    def _load(path: Path) -> dict:
        from .spec import SpecError, load
        try:
            return load(path)
        except SpecError as why:
            for p in why.problems:
                typer.echo(f"- {p}", err=True)
            raise typer.Exit(2) from None

    @sub.command("draft")
    def draft_(goal: str = typer.Argument(..., help="the result you want, in plain English"),
               sample: Path = typer.Option(..., "--sample", help="a sample of your data: CSV, JSON or JSONL"),
               out: Path = typer.Option(Path("outcome.yaml"), "--out"),
               data_path: str = typer.Option(None, "--data-path", help="where the data will live in your repository (default: the sample's name)"),
               synthetic: bool = typer.Option(False, "--synthetic", help="the data are made up: label everything synthetic"),
               llm: bool = typer.Option(False, "--llm", help="let Claude draft it, with your own key"),
               llm_key_env: str = typer.Option(None, "--llm-key-env", help="the environment variable holding your Anthropic key")) -> None:
        """Turn a goal and a data sample into a draft outcome.yaml (templates; an LLM only with --llm and your key)."""
        from .draft import draft
        try:
            text, _spec, how = draft(goal, sample, data_path=data_path, synthetic=synthetic, llm=llm, key_env=llm_key_env)
        except ValueError as why:
            typer.echo(str(why), err=True)
            raise typer.Exit(2) from None
        out.write_text(text, encoding="utf-8")
        typer.echo(f"wrote {out} ({how}). Read it, fill every EDIT, then: knos outcome validate {out}")

    @sub.command("validate")
    def validate_(spec: Path = typer.Argument(...)) -> None:
        """Every rule the spec breaks; its hash when it holds."""
        from .spec import spec_hash
        s = _load(spec)
        typer.echo(f"holds. spec hash {spec_hash(s)}" + ("  (SYNTHETIC data)" if s["synthetic"] else ""))

    @sub.command("hash")
    def hash_(spec: Path = typer.Argument(...)) -> None:
        """The spec's hash: sha256 of its canonical JSON."""
        from .spec import spec_hash
        typer.echo(spec_hash(_load(spec)))

    @sub.command("tiers")
    def tiers_(spec: Path = typer.Argument(...), as_json: bool = typer.Option(False, "--json")) -> None:
        """One knos_pay order per tier, and what the buyer escrows in all."""
        from . import escrow
        s = _load(spec)
        rows, total = escrow.orders(s), escrow.escrowed(s)
        if as_json:
            typer.echo(json.dumps({"orders": rows, "escrowed": total}, indent=2))
            return
        for o in rows:
            typer.echo(f"{o['name']:<12} seq {o['seq']:<5} {o['amount'] / 1e6:>10.2f} + fee {o['fee'] / 1e6:.2f}  order {o['address']}  terms {o['terms_hash'][:16]}")
        typer.echo(f"cap {total['cap'] / 1e6:.2f}; escrowed with fees {total['total'] / 1e6:.2f}")

    @sub.command("lock")
    def lock_(spec: Path = typer.Argument(...), history: Path = typer.Option(None, "--history", help="the data as they stand at funding"),
              out: Path = typer.Option(Path("outcome.lock.json"), "--out"), no_orders: bool = typer.Option(False, "--no-orders")) -> None:
        """Write what is fixed at funding: spec hash, window, salt, share, the measuring code's hash, the history's hash, the orders."""
        from .data import parse
        from .measure import lock_for
        s = _load(spec)
        rows = parse(history.read_bytes(), s["data"]["format"], s["data"].get("items_key")) if history else []
        orders = []
        if not no_orders:
            from . import escrow
            orders = escrow.orders(s)
        doc = lock_for(s, rows, orders)
        out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        typer.echo(f"wrote {out}: spec {doc['spec_hash'][:16]}, code {doc['measurement_commit'][:16]}, {len(orders)} order(s)")

    @sub.command("assign")
    def assign_(spec: Path = typer.Argument(...), data_file: Path = typer.Option(..., "--data"), out: Path = typer.Option(None, "--out")) -> None:
        """Recompute the control group from the public salt: the arm of every item in the window."""
        from . import assign, data
        s = _load(spec)
        rows = data.in_window(s, data.parse(data_file.read_bytes(), s["data"]["format"], s["data"].get("items_key")))
        arms = assign.split([r[s["data"]["id_field"]] for r in rows], s["control"]["salt"], float(s["control"].get("share", 0.2)))
        n_c = sum(1 for a in arms.values() if a == "control")
        if out:
            out.write_text(json.dumps(arms, indent=0, sort_keys=True) + "\n", encoding="utf-8")
        typer.echo(f"{len(arms)} items in the window: {n_c} control ({n_c / max(1, len(arms)):.4f}), {len(arms) - n_c} treated")

    @sub.command("measure")
    def measure_(spec: Path = typer.Argument(...), lock: Path = typer.Option(..., "--lock"), repo: Path = typer.Option(None, "--repo"),
                 data_file: Path = typer.Option(None, "--data"), out: Path = typer.Option(None, "--out"), now: int = typer.Option(None, "--now"),
                 record: bool = typer.Option(False, "--record", help="append the Knos Record entries")) -> None:
        """Measure the window: treated vs control, lift, bootstrap bound, tiers, cheat checks. Exit 0 only when the bar was reached."""
        from . import measure, recordio
        rc = measure.main_measure(spec, lock, repo, out, now, data_file)
        if record and out:
            recordio.measurement(json.loads(out.read_text(encoding="utf-8")))
        raise typer.Exit(rc)

    @sub.command("sign")
    def sign_(spec: Path = typer.Argument(...), role: str = typer.Option(..., "--role"), keypair: Path = typer.Option(..., "--keypair"),
              file: Path = typer.Option(Path("outcome.signatures.json"), "--file")) -> None:
        """Sign the spec's hash with your wallet (the buyer: escrow.funder; the seller: parties.seller.address)."""
        from .. import chain
        from . import sign
        s = _load(spec)
        try:
            entry = sign.sign(s, role, chain.wallet(keypair))
        except ValueError as why:
            typer.echo(str(why), err=True)
            raise typer.Exit(2) from None
        sign.add(file, s, entry)
        typer.echo(f"{role} signed {entry['signature'][:24]}... into {file}")

    @sub.command("verify-signatures")
    def verify_(spec: Path = typer.Argument(...), file: Path = typer.Option(Path("outcome.signatures.json"), "--file")) -> None:
        """Both parties signed this spec's hash with the wallets it names."""
        from . import sign
        s = _load(spec)
        bad = sign.verify(s, json.loads(file.read_text(encoding="utf-8")))
        for b in bad:
            typer.echo(f"- {b}")
        if bad:
            raise typer.Exit(1)
        typer.echo("both parties signed this spec")

    @sub.command("comment")
    def comment_(spec: Path = typer.Argument(...), file: Path = typer.Option(Path("outcome.signatures.json"), "--file")) -> None:
        """The comment for the orders' issue: the signed hash, the signatures, the orders. Posts nothing."""
        from . import escrow, sign
        s = _load(spec)
        sigs = json.loads(file.read_text(encoding="utf-8")) if file.is_file() else {"signatures": []}
        typer.echo(sign.comment(s, sigs, escrow.orders(s)))

    @sub.command("sample")
    def sample_(spec: Path = typer.Argument(...), n: int = typer.Option(10_000, "--n"), seed: int = typer.Option(12, "--seed"),
                out: Path = typer.Option(Path("tickets.csv"), "--out")) -> None:
        """SYNTHETIC support tickets inside the spec's window, to try a measurement with no data of your own."""
        from . import synth
        s = _load(spec)
        out.write_text(synth.to_csv(synth.tickets(s, n, seed=seed)), encoding="utf-8")
        typer.echo(f"wrote {n} SYNTHETIC tickets to {out} (made up; every row says synthetic=1)")

    @sub.command("audiences")
    def audiences_(result: Path = typer.Argument(...)) -> None:
        """The pay audience of each tier that passed, one per line (what the workflow's signing job asks GitHub to sign)."""
        doc = json.loads(result.read_text(encoding="utf-8"))
        for t in doc.get("tiers", []):
            if t.get("passed") and t.get("audience"):
                typer.echo(t["audience"])
