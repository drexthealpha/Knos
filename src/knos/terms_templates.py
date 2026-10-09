"""Terms from a template: five ready `/knos` comments, each with the exact terms it funds and one sentence that says them.

    knos terms list            the five, one sentence each
    knos terms show <name>     the comment to post, the sentence, the terms JSON knos-pay hashes, and its sha256
    knos terms diff <a> <b>    what changed between two versions of an acceptance policy, in plain words

    bugfix             named checks must pass; only src/ and tests/ may change
    feature-blackbox   paid when the black-box acceptance suite (.knos/acceptance/<issue>/) passes
    milestone          a share of the payment held back for a warranty period
    standing-rate      one vendor, a rate when the agreed checks pass at merge, up to a budget
    private-attested   a private repository's order, funded and paid by the organisation's attestor repository

Three more are outcomes that are not code (examples/outcomes/): the same comment and the same terms, where the
acceptance suite scores a file. Their `accept` is the hash of the example's own bundle, so the terms are real ones:

    data-labelling          a labelled dataset, scored on gold items that were never shown
    data-transformation     a transformation, run on seeded tables and reconciled to the cent (150: more than the
                            devnet faucet gives, so it needs a Balance)
    reproducible-research   an analysis, run again, then run on moved input

A template is one comment. Everything else here is derived from it by the code that reads a real comment
(knos.commands.parse) and fixes a real bounty's terms (knos.terms.build), so a template cannot say one thing and
fund another: examples/terms/<name>.json is `export(name)`, and the tests hold the two equal.

The terms of a real bounty also carry facts of the repository it is funded in, which no template can know: the id
of the GitHub App that produces each check, the hash of the acceptance bundle, the hash of the repository's policy,
the vendor's account id. Each template says under `assumes` which sample facts its JSON was made with. The comment is
what you copy; the reply to it shows your repository's own terms and their hash. No template asks for more than
100: on devnet the program's faucet gives at most 100 test USDC per comment, so each works with no Balance.

An ACCEPTANCE POLICY is the terms an order was funded on, and its version is their sha256: the hash the order keeps,
every pay token carries, and the meter records as `policy`. Nobody edits a version; a change is a new version with a
new hash, used by the next order. `diff` says what differs between two versions (docs/ASSURANCE.md, "Acceptance
policies").
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
    says: str = ""              # the sentence, when the suite's own rules say more than the terms can (an outcome)
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

_BUNDLE = "the hash of examples/outcomes/{}/base/.knos/acceptance/1/ as it is in this repository: yours is the hash of your own suite"
_WHERE = "an issue of a repository that has this example's black-box suite as .knos/acceptance/<issue>/ on the default branch"
OUTCOMES = {t.name: t for t in (       # the comment that funds each example of examples/outcomes, and the terms it funds there
    Template("data-labelling", "/knos fund 40 checks: none", _WHERE, accept="8445799b6b70bde0dcf4a73465d9a34b0e180a9c88daa305acf4926c5d62acc5",
             assumes={"accept": _BUNDLE.format("data-labelling")},
             says="Pays 40 test USDC when labels.csv labels every item of data/items.csv, at least 90% of the 120 held-out gold items "
                  "carry the gold label, no class has recall below 80% on them, and the 40 visible examples do not score more than "
                  "10 points above them; refund after 14 days"),
    Template("data-transformation", "/knos fund 150 checks: none", _WHERE, accept="9d4381ba658fc5bfc89ee6a3dc067061a9c7731b65dd1be4c3850433fa45e251",
             assumes={"accept": _BUNDLE.format("data-transformation"),
                      "balance": "150 is more than the devnet faucet gives per comment (100): the repository's owner has a Balance that holds it"},
             says="Pays 150 test USDC when transform.sql turns each of 40 seeded, unseen pairs of tables into a ledger with one row "
                  "per customer, every distinct charge counted once, and gross, refunds and net equal to the input's totals to "
                  "the cent; refund after 14 days"),
    Template("reproducible-research", "/knos fund 90 checks: none", _WHERE, accept="a370157d7afb2d43aba0e6285942c190a820fceec69061630273f0099a9ab71e",
             assumes={"accept": _BUNDLE.format("reproducible-research")},
             says="Pays 90 test USDC when analysis.py, run again with seed 20261005 on the trial's rows, prints the estimate "
                  "claimed in RESULT.json within 0.000001 minutes, and the estimate moves with the treatment arm when the arm "
                  "is moved; refund after 14 days"),
)}
ALL = {**TEMPLATES, **OUTCOMES}


def get(name: str) -> Template:
    if name not in ALL:
        raise KeyError(f"there is no template named {name}: the templates are {', '.join(ALL)}")
    return TEMPLATES[name] if name in TEMPLATES else ALL[name]     # the table itself: a template published again is read as it is now


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
    if t.says:
        return t.says
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


# ---- two versions of an acceptance policy, compared --------------------------------------------------------------

def version(tm: dict) -> str:
    """The version of an acceptance policy: the sha256 of its canonical terms, as the order and the meter hold it."""
    return terms.terms_hash(terms.canonical(tm))


def load(what: str) -> dict:
    """The terms `what` names: a template, or a file that holds terms (the canonical JSON alone, or a document with
    them under "terms", as `knos terms show <name> --json` and examples/outcomes/<name>/terms.json write it).
    Raises ValueError with words for the person who typed it."""
    from pathlib import Path
    if what in ALL:
        return terms_of(ALL[what])
    path = Path(what)
    if not path.is_file():
        raise ValueError(f"{what} is neither a template ({', '.join(ALL)}) nor a file that holds terms")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return terms.parse(terms.canonical(doc["terms"] if isinstance(doc, dict) and isinstance(doc.get("terms"), dict) else doc))
    except (ValueError, OSError) as why:
        raise ValueError(f"{what} does not hold terms: {why}") from None


def _check(c: dict) -> str:
    return f"`{c['name']}`" + {terms.STATUS: " as a commit status", terms.ANY: " from any source"}.get(c["app"], f" from GitHub App {c['app']}")


def _days(n: int) -> str:
    return f"{n} day{'s' if n != 1 else ''}" if n else "not at all"


def diff(a: dict, b: dict) -> list[str]:
    """What an order funded on version `b` asks that one funded on version `a` did not, and the other way round: one
    plain sentence for each difference, in the order a buyer would read the terms. Empty when the two are one version."""
    a, b = terms.parse(terms.canonical(a)), terms.parse(terms.canonical(b))
    out = []
    by = {"merge": "a maintainer's merge", "tests": "the acceptance suite passing"}
    if a["mode"] != b["mode"]:
        out.append(f"What decides payment changed: it was {by[a['mode']]}; it is now {by[b['mode']]}.")
    if a["accept"] != b["accept"] and a["accept"] and b["accept"]:
        out.append(f"The acceptance suite changed: its files are not the same (hash {a['accept'][:12]} before, {b['accept'][:12]} now). "
                   "Work accepted by one suite is not thereby accepted by the other.")
    if a.get("image") != b.get("image"):
        where = [f"in the image `{x}`" if x else "on the runner, with no pinned image" for x in (a.get("image"), b.get("image"))]
        out.append(f"Where the suite runs the work changed: before, {where[0]}; now, {where[1]}.")
    was, now = [_check(c) for c in a["checks"]], [_check(c) for c in b["checks"]]
    out += [f"A check must now pass that did not have to: {name}." for name in now if name not in was]
    out += [f"A check no longer has to pass: {name}." for name in was if name not in now]
    for key, more, less in (("paths", "The work may now also change files matching", "The work may no longer change files matching"),
                            ("deny", "The work may no longer touch", "The work may now touch")):
        if key == "deny" or (a[key] and b[key]):       # an empty `paths` is no limit: said once, below
            out += [f"{more} `{g}`." for g in b[key] if g not in a[key]]
            out += [f"{less} `{g}`." for g in a[key] if g not in b[key]]
    if bool(a["paths"]) != bool(b["paths"]):
        listed = ", ".join(f"`{g}`" for g in a["paths"] or b["paths"])
        out.append(f"Before, any file could change; now only files matching {listed}." if b["paths"] else
                   f"Before, only files matching {listed} could change; now any file can.")
    if a["reserve"] != b["reserve"]:
        out.append(f"How long the issue can be reserved changed: {_days(a['reserve'])} before, {_days(b['reserve'])} now.")
    if a.get("policy") != b.get("policy"):
        out.append("The repository's rules for funding (.knos/policy.yml) " + ("changed between the two" if a.get("policy") and b.get("policy") else
                   "are named by one version and not by the other") + ": who may fund, the caps, the defaults.")
    if a.get("vendor") != b.get("vendor"):
        out.append(f"The one account it pays changed: account id {a.get('vendor') or 'none'} before, {b.get('vendor') or 'none'} now.")
    return out


def diff_text(a: str, b: str) -> str:
    """What `knos terms diff <a> <b>` prints."""
    ta, tb = load(a), load(b)
    va, vb = version(ta), version(tb)
    if va == vb:
        return f"Nothing changed: both are version {va} of the acceptance policy.\n"
    lines = diff(ta, tb)
    return (f"Acceptance policy, version {va[:12]} ({a}) to version {vb[:12]} ({b}):\n\n" + "".join(f"  - {x}\n" for x in lines)
            + f"\n{len(lines)} difference{'s' if len(lines) != 1 else ''}. An order keeps the version it was funded on: its hash is in the order, "
            "and a payment under any other version is refused. The later version applies only to orders funded on it.\n")


def _three(what: str) -> dict | None:
    """The Knos Terms 3 document `what` names: a file that holds one, or a published one as `name` or `name@version`.
    None when it is neither (it is then read as the older format)."""
    from pathlib import Path

    from . import terms3, terms_registry as registry
    path = Path(what)
    if path.is_file():
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return terms3.validate(doc) if terms3.is_terms3(doc) else None
    name, _, version = what.partition("@")
    if name in terms3.TEMPLATES and (not version or version.isdigit()):
        try:
            return registry.read3(name, int(version) if version else None)
        except registry.Absent:
            return terms3.template(name)
        except KeyError as why:
            raise ValueError(str(why.args[0])) from None
    return None


def register(app) -> None:
    """`knos terms list`, `show <name>`, `diff <a> <b>`, `propose <owner/repo>`, and from the registry of published
    terms `cite` and `verify`. A Knos Terms 3 file (knos.terms3) is verified field by field and diffed by meaning."""
    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    sub = typer.Typer(no_args_is_help=True, help="Terms from a template: the comment to post and exactly what it funds.")

    @sub.command("list")
    def _list() -> None:
        """The templates, one sentence each."""
        for name in ALL:
            typer.echo(f"{name}\n    {sentence(ALL[name])}")
        typer.echo("\nknos terms show <name> gives the comment to post and the terms it funds.")

    @sub.command("show")
    def _show(name: str = typer.Argument(..., help=", ".join(ALL)),
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

    @sub.command("diff")
    def _diff(a: str = typer.Argument(..., help="the earlier version: a template's name, or a file that holds terms"),
              b: str = typer.Argument(..., help="the later version, named the same way")) -> None:
        """What changed between two versions of an acceptance policy, one plain sentence for each difference."""
        try:
            three = [_three(x) for x in (a, b)]
            first, second = three
            if first is not None and second is not None:
                from . import terms3
                typer.echo(terms3.diff_text(first, second, a, b), nl=False)
                return
            if any(three):
                raise ValueError("One of the two is Knos Terms 3 and the other is not: two versions of one format are compared, not two formats.")
            typer.echo(diff_text(a, b), nl=False)
        except ValueError as why:
            typer.echo(str(why))
            raise typer.Exit(1) from None

    @sub.command("cite")
    def _cite(name: str = typer.Argument(..., help="a published template: " + ", ".join(TEMPLATES)),
              version: int = typer.Argument(None, help="which published version; the newest when left out")) -> None:
        """The sentence a contract carries to name a published template by hash, and the address of the published file."""
        from . import terms_registry as registry
        try:
            line, url = registry.cite(name, version)
        except (registry.Absent, registry.Changed) as why:
            typer.echo(str(why))
            raise typer.Exit(1) from None
        except KeyError as why:
            typer.echo(str(why.args[0]))
            raise typer.Exit(1) from None
        typer.echo(f"{line}\n{url}")

    @sub.command("verify")
    def _verify(what: str = typer.Argument(..., help="a sha256 in hex, or a file that holds terms JSON")) -> None:
        """Which published template and version these terms are, or that they are not a published template."""
        from pathlib import Path

        from . import terms_registry as registry
        from . import terms3
        path = Path(what)
        try:
            doc = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        except (OSError, ValueError):
            doc = None
        if doc is not None and terms3.is_terms3(doc):
            try:
                digest, found = registry.verify3(doc)
            except (terms3.Refused, registry.Changed) as why:        # a missing field is said by name
                typer.echo(str(why))
                raise typer.Exit(1) from None
            typer.echo(registry.said3(doc, digest, found))
            return
        try:
            found = registry.verify(what if registry.is_hash(what) or not path.is_file() else path.read_text(encoding="utf-8"))
        except (registry.Absent, registry.Changed) as why:
            typer.echo(str(why))
            raise typer.Exit(1) from None
        except (OSError, ValueError) as why:
            typer.echo(f"{what} could not be read: {why}")
            raise typer.Exit(1) from None
        typer.echo(registry.said(found))
        if not found:
            raise typer.Exit(1)

    @sub.command("propose")
    def _propose(repo: str = typer.Argument(..., help="a public repository, as owner/name"),
                 out: str = typer.Option("", "--out", help="write the proposed terms 3 file here (the buyer edits and commits it)"),
                 template: str = typer.Option("bug-fix", "--template", help="where the defaults come from: bug-fix, migration"),
                 as_json: bool = typer.Option(False, "--json", help="the whole proposal as JSON: the terms, and where each line came from")) -> None:
        """Propose terms for a repository from its own record: the checks that passed on every recent merge decide,
        its test directories are protected, and every line says where it came from. Nothing is funded or posted."""
        import time
        from pathlib import Path

        from . import propose_terms, terms3
        try:
            got = propose_terms.propose(repo, propose_terms.reader(), time.time(), template)
        except (propose_terms.Refused, terms3.Refused, KeyError) as why:
            typer.echo(str(why.args[0]))
            raise typer.Exit(1) from None
        except OSError as why:
            typer.echo(f"GitHub did not answer for {repo}: {why}")
            raise typer.Exit(1) from None
        if out:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_text(terms3.dumps(got["terms"]), encoding="utf-8", newline="")
        typer.echo(json.dumps(got, indent=2) if as_json else propose_terms.text(got), nl=as_json)

    app.add_typer(sub, name="terms")
