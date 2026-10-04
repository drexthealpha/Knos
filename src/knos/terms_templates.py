"""Terms from a template: five ready `/knos` comments, each with the exact terms it funds and one sentence that says them.

    knos terms list            the five, one sentence each
    knos terms show <name>     the comment to post, the sentence, the terms JSON knos-pay hashes, and its sha256

    bugfix             named checks must pass; only src/ and tests/ may change
    feature-blackbox   paid when the black-box acceptance suite (.knos/acceptance/<issue>/) passes
    milestone          a share of the payment held back for a warranty period
    standing-rate      one vendor, a rate per accepted pull request, up to a budget
    private-attested   a private repository's order, funded and paid by the organisation's attestor repository

A template is one comment. Everything else here is derived from it by the code that reads a real comment
(knos.commands.parse) and fixes a real bounty's terms (knos.terms.build), so a template cannot say one thing and
fund another: examples/terms/<name>.json is `export(name)`, and the tests hold the two equal.

The terms of a real bounty also carry facts of the repository it is funded in, which no template can know: the id
of the GitHub App that produces each check, the hash of the acceptance bundle, the hash of the repository's policy,
the vendor's account id. Each template says under `assumes` which sample facts its JSON was made with. The comment is
what you copy; the reply to it shows your repository's own terms and their hash. No template asks for more than
100: on devnet the program's faucet gives at most 100 test USDC per comment, so each works with no Balance.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import commands, policy, terms

ACTIONS = 15368                 # the GitHub App id of GitHub Actions: the source of a check that a workflow job produces
SAMPLE_ACCEPT = "5d" * 32       # stands for knos.judge.checks_hash(.knos/acceptance/<issue>/): the bundle is the repository's own
SAMPLE_VENDOR = 583231          # the account id of github.com/octocat, who stands for the vendor
SAMPLE_POLICY = "version: 1\nprivate: true\nattestor: acme/knos-settle\ntargets: [acme/vault-core]\n"


@dataclass(frozen=True)
class Template:
    name: str
    comment: str                # the one line to post
    where: str                  # where it is posted
    accept: str = ""            # tests mode: the acceptance bundle's hash
    vendor: int = 0             # a standing offer: the vendor's account id
    policy: str = ""            # the text of .knos/policy.yml, when the order is funded under one
    assumes: dict = field(default_factory=dict)


_ACTIONS = f"each named check is a GitHub Actions job (GitHub App {ACTIONS}) that ran on the default branch's latest commit"
TEMPLATES = {t.name: t for t in (
    Template("bugfix", "/knos fund 50 checks: unit, lint paths: src/**, tests/**", "an issue", assumes={"checks": _ACTIONS}),
    Template("feature-blackbox", "/knos fund 80 checks: unit", "an issue that has .knos/acceptance/<issue>/ on the default branch",
             accept=SAMPLE_ACCEPT, assumes={"checks": _ACTIONS, "accept": "a sample hash: yours is the hash of your own acceptance bundle"}),
    Template("milestone", "/knos fund 100 checks: unit holdback 20 warranty 30 days 30", "an issue", assumes={"checks": _ACTIONS}),
    Template("standing-rate", "/knos offer @octocat rate 10 budget 100 checks: unit days 90", "an issue", vendor=SAMPLE_VENDOR,
             assumes={"checks": _ACTIONS, "vendor": f"@octocat (account id {SAMPLE_VENDOR}) stands for your vendor"}),
    Template("private-attested", "/knos fund 50 checks: unit paths: src/**", "an issue of a private repository the attestor's policy lists",
             policy=SAMPLE_POLICY, assumes={"checks": _ACTIONS, "policy": "the attestor repository's .knos/policy.yml is: " + SAMPLE_POLICY.strip().replace("\n", "; ")}),
)}


def get(name: str) -> Template:
    if name not in TEMPLATES:
        raise KeyError(f"there is no template named {name}: the templates are {', '.join(TEMPLATES)}")
    return TEMPLATES[name]


def command(t: Template):
    """The template's comment, read as a comment on an issue is read."""
    got = commands.parse(t.comment, on_pull=False)
    if not isinstance(got, (commands.Fund, commands.Offer)):
        raise ValueError(f"the template {t.name} does not fund anything: {t.comment}")
    return got


def terms_of(t: Template) -> dict:
    """The terms that comment funds in a repository where the sample facts hold: built as flow builds a real bounty's."""
    cmd = command(t)
    runs = [{"name": n, "app": {"id": ACTIONS}, "status": "completed", "conclusion": "success"} for n in cmd.checks or ()]
    more = {**({"policy": policy.digest(policy.load(t.policy))} if t.policy else {}), **({"vendor": t.vendor} if t.vendor else {})}
    return terms.parse(terms.canonical({**terms.build(cmd, [], runs, [], t.accept).terms, **more}))


def _money(units: int) -> str:
    return f"{commands.amount(units)} {commands.MONEY}"


def _dirs(globs) -> str:
    """Globs as a person says them: `src/**` is src/."""
    return " and ".join(g[:-2] if g.endswith("/**") else g for g in globs)


def sentence(t: Template) -> str:
    """The template in one sentence, written from the parsed comment and the terms, never by hand."""
    cmd, tm = command(t), terms_of(t)
    names = ", ".join(f"`{c['name']}`" for c in tm["checks"])
    only = f"only touches {_dirs(tm['paths'])}" if tm["paths"] else ""
    if tm["mode"] == "tests":
        on = "on a pull request that also passes the issue's black-box acceptance suite" + (f" and {only}" if only else "")
    else:
        on = "on a merge" + (f" that {only}" if only else "")
    if names:
        when = f"when check{'s' if len(tm['checks']) != 1 else ''} {names} pass{'es' if len(tm['checks']) == 1 else ''} {on}"
    else:
        when = "when a maintainer merges a pull request that closes the issue" + (f" and {only}" if only else "") if tm["mode"] == "merge" else on
    if isinstance(cmd, commands.Offer):
        head = f"Pays @{cmd.vendor} {_money(cmd.rate)} for each pull request of theirs, up to {_money(cmd.budget)} in all, {when}"
    else:
        head = f"Pays {_money(cmd.units)} {when}"
    held = (f"; {cmd.holdback}% of it waits {cmd.warranty} days and goes back if the change is reverted"
            if getattr(cmd, "holdback", None) and getattr(cmd, "warranty", None) else "")
    private = "; funded and paid by the organisation's attestor repository, so nothing public names the private one" if t.policy else ""
    return f"{head}{held}{private}; refund after {cmd.days} days"


def export(name: str) -> dict:
    """What examples/terms/<name>.json holds. `terms_json` is the exact bytes knos-pay hashes; `terms_hash` their sha256."""
    t = get(name)
    raw = terms.canonical(terms_of(t))
    return {"name": t.name, "sentence": sentence(t), "comment": t.comment, "where": t.where, "terms": json.loads(raw),
            "terms_json": raw.decode("ascii"), "terms_hash": terms.terms_hash(raw), "assumes": t.assumes}


def dumps(name: str) -> str:
    return json.dumps(export(name), indent=2, ensure_ascii=True) + "\n"


def register(app) -> None:
    """`knos terms list` and `knos terms show <name>`."""
    import typer

    sub = typer.Typer(no_args_is_help=True, help="Terms from a template: the comment to post and exactly what it funds.")

    @sub.command("list")
    def _list() -> None:
        """The templates, one sentence each."""
        for name in TEMPLATES:
            typer.echo(f"{name}\n    {sentence(TEMPLATES[name])}")
        typer.echo("\nknos terms show <name> gives the comment to post and the terms it funds.")

    @sub.command("show")
    def _show(name: str = typer.Argument(..., help=", ".join(TEMPLATES)),
              as_json: bool = typer.Option(False, "--json", help="the template as examples/terms/<name>.json holds it")) -> None:
        """One template: the comment, the sentence, the terms JSON knos-pay hashes, and its sha256."""
        try:
            got = export(name)
        except KeyError as why:
            typer.echo(str(why.args[0]))
            raise typer.Exit(1) from None
        if as_json:
            typer.echo(dumps(name), nl=False)
            return
        typer.echo(f"{got['sentence']}.\n\nPost this as a comment on {got['where']}:\n\n    {got['comment']}\n\n"
                   f"The terms it funds (the bytes the program hashes):\n\n    {got['terms_json']}\n\n    sha256 {got['terms_hash']}\n\n"
                   "These bytes were made with sample facts:")
        for what in got["assumes"].values():
            typer.echo(f"  - {what}")
        typer.echo("In your repository the reply to the comment shows your own terms and their hash. Money is test USDC on Solana devnet.")

    app.add_typer(sub, name="terms")
