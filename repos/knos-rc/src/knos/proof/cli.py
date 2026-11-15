"""`knos proof ...`: the engine the Stop hook runs, by hand; and what the workflows run on GitHub: the judge, a
bounty's terms and their evidence, who is paid, and the judge's memory. Every read of GitHub goes through
knos.judge.github."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer


def register(app: typer.Typer, out, Stop, repo_of) -> None:
    proof = typer.Typer(add_completion=False, help="Compare what a change claims with what the repository and its checks show")
    app.add_typer(proof, name="proof")

    def _store(repo: Path):
        from . import history
        try:
            return history.SibylStore.for_repo(repo)
        except Exception:  # noqa: BLE001 - no store: still prove, just without memory
            return history.NullStore()

    @proof.command("check")
    def check(claim: str = typer.Argument(..., help="what the agent says is done"),
              in_: str = typer.Option(None, "--in", help="the repo (default: this one)")) -> None:
        """Run every check this claim needs (and what this repo's history requires). Exit 1 if any fails."""
        from . import engine
        repo = repo_of(in_)
        v = engine.evaluate(repo, claim, _store(repo))
        if not v.results:
            out.print("That claims nothing checkable.")
            return
        out.print(v.explain(), markup=False)
        out.print("[green]proven[/green]" if v.ok else "[red]not proven[/red]")
        if not v.ok:
            raise typer.Exit(1)

    @proof.command("run")
    def run(toml: Path = typer.Option(None, "--toml", help="default: .knos/proof.toml in the repo"),
            in_: str = typer.Option(None, "--in", help="the repo the checks run in (default: this one)")) -> None:
        """Run every [[check]] in .knos/proof.toml, whatever the claim. Exit 1 if any fails or none is defined."""
        from . import checks, engine
        repo = repo_of(in_)
        cfg = engine.load(toml) if toml else engine.config(repo)
        specs = [c for c in cfg.get("check", []) or [] if c.get("name") and c.get("run")]
        if not specs:
            raise Stop(cfg.get("_error") or "No [[check]] with a name and a run command: nothing to prove.")
        results = [checks.custom(repo, c["name"], c["run"]) for c in specs]
        for r in results:
            out.print(f"{'ok ' if r.ok else 'NO '} {r.name}: {r.detail}", markup=False, emoji=False)
        if not all(r.ok for r in results):
            out.print("[red]not proven[/red]")
            raise typer.Exit(1)
        out.print("[green]proven[/green]")

    @proof.command("checks-hash")
    def checks_hash(dir_: Path = typer.Option(..., "--dir", help="e.g. .knos/acceptance/<issue>")) -> None:
        """Print the sha256 that identifies an acceptance bundle (the value fixed on chain when the bounty is funded)."""
        from .. import judge
        try:
            out.print(judge.checks_hash(dir_), markup=False)
        except ValueError as why:
            raise Stop(str(why)) from None

    def _say(v: dict, evidence: Path | None) -> None:
        if evidence:
            evidence.write_text(json.dumps(v, indent=1, default=str), encoding="utf-8")
        ev = v["evidence"]
        for r in ev.get("required_by_history", []):
            out.print(f"REQUIRED by this repo's history: {r}", markup=False, emoji=False)
        for name, state in (ev.get("checks") or {}).items():
            out.print(f"{state:<10} {name}", markup=False, emoji=False)
        for note in [*ev.get("facts", []), *ev.get("unverified", []), *ev.get("notes", [])]:
            out.print(f"NOTE {note}", markup=False, emoji=False)
        who = ev.get("payee") or {}
        if who.get("id"):
            out.print(f"paid to @{who.get('login')} (GitHub user id {who['id']}): {who['why']}", markup=False, emoji=False)
        if who.get("hint"):
            out.print(f"NOTE {who['hint']}", markup=False, emoji=False)
        for r in v["reasons"]:
            out.print(f"NO  {r}", markup=False, emoji=False)
        if v["checks_hash"]:
            out.print(f"checks_hash {v['checks_hash']}", markup=False)
        if v.get("assurance"):          # how much this verdict can carry: in-process, black-box or hermetic (knos.judge.ASSURANCE)
            image = (ev.get("image") or {}).get("ref")
            out.print(f"assurance {v['assurance']}" + (f", in {image}" if image else "") + f": {v.get('assurance_means', '')}", markup=False, emoji=False)
        if not v["passed"]:
            out.print("[red]not proven[/red]")
            raise typer.Exit(1)
        out.print("[green]proven[/green]")

    def _terms(path: Path | None) -> dict | None:
        """The bounty's terms from a file that holds exactly their canonical bytes (a final newline is forgiven)."""
        from .. import terms
        if not path:
            return None
        try:
            return terms.parse(path.read_bytes().rstrip(b"\r\n"))
        except terms.Refused as why:
            raise Stop(f"{path}: {why}") from None

    def _lines(path: Path | None) -> list[str] | None:
        """The changed paths in a file as `git diff --name-only` wrote it."""
        from .. import terms
        return terms.listed(path.read_text(encoding="utf-8", errors="replace")) if path else None

    def _changed(path: Path | None, bought, repo_name: str, number) -> list[str] | None:
        """What the pull request changed, for a bounty's scope: the --changed file, else GitHub's own list of the
        pull request's files (a rename under both its names). None when neither can be had."""
        from .. import judge, terms
        files = _lines(path)
        if files is None and bought is not None and repo_name and number:
            files = terms.pull_files(repo_name, number, judge.github)
        return files

    def _inputs(store, diff, body_file, checks_file, repo_name, head, wait, bought=None, statuses_file=None):
        """(store, diff, description, check runs, commit statuses). The last two are read from GitHub when no file
        holds them; with a bounty's terms, until its checks have finished or `wait` seconds have passed."""
        import time

        from .. import judge, terms
        from . import history
        st = history.SibylStore.local(store) if store else history.NullStore()
        diff_text = diff.read_text(encoding="utf-8", errors="replace") if diff else None
        body = body_file.read_text(encoding="utf-8", errors="replace") if body_file else ""
        runs = statuses = None
        if checks_file:      # a list, or GitHub's own answer: one that holds fewer runs than it counts was cut short
            runs = terms.listing(json.loads(checks_file.read_text(encoding="utf-8")), "check_runs")
            statuses = terms.listing(json.loads(statuses_file.read_text(encoding="utf-8")), "statuses") if statuses_file else \
                ([] if bought else None)
        elif head and repo_name:
            end = time.monotonic() + wait       # one wait for both: what a claim needs, then what the terms need
            runs = judge.check_runs(repo_name, head, wait=wait, body=body)
            if bought is not None:
                _found, runs, statuses = terms.watch(bought, repo_name, head, judge.github, max(0.0, end - time.monotonic()))
        return st, diff_text, body, runs, statuses

    def _pull(event: Path | None, repo_name: str, number: int) -> dict | None:
        """The pull request: from the event GitHub hands the workflow (or a file holding the pull request itself),
        else read from GitHub by its number."""
        from .. import judge
        if event:
            got = json.loads(event.read_text(encoding="utf-8"))
            return got.get("pull_request") or (got if isinstance(got.get("head"), dict) and "user" in got else {})
        if number and repo_name:
            try:
                return judge.github(f"repos/{repo_name}/pulls/{number}")
            except OSError as why:
                raise Stop(f"GitHub did not answer for {repo_name}#{number}: {why}") from None
        return None

    def _who(event, repo_name: str, issue: str, issue_file, bought=None, number: int = 0, strict: bool = False, tip: bool = False):
        """(the pull request, what GitHub said, who is paid); the pull request is None when there is none. With
        --repo, GitHub is asked for what decides it: the issue and when it was assigned to whom, the comments on
        both, and who has write access. What GitHub does not answer is treated as not said: it never names anyone.
        `tip`: who a tip on the pull request goes to, which no issue enters."""
        import time

        from .. import closing, judge, who
        pull = _pull(event, repo_name, number)
        if pull is None:
            return None, {}, None
        facts: dict[str, Any] = {"issue": None, "events": None, "pull_comments": None, "issue_comments": None}
        permission = user = None
        message = ""
        issue, issue_file = ("", None) if tip else (issue, issue_file)
        if repo_name:
            facts = who.read(repo_name, pull.get("number"), issue, judge.github)  # type: ignore[arg-type]  # a pull request from a file may have no number: its comments are then not found
            permission, user = who.permission_of(repo_name, judge.github), who.user_of(judge.github)
            if (pull.get("user") or {}).get("type") == "Bot" and (pull.get("head") or {}).get("sha"):
                try:    # what its head commit says is a hint to show, nothing more
                    message = judge.github(f"repos/{repo_name}/commits/{pull['head']['sha']}")["commit"]["message"]
                except Exception:  # noqa: BLE001
                    message = ""
        if issue_file:
            facts["issue"] = json.loads(issue_file.read_text(encoding="utf-8"))
        closes: list[int] | None
        edited: float | bool | None
        strict, closes, edited = strict and bool(str(issue)), None, False      # no issue named: no bounty to be strict about
        if strict and repo_name and pull.get("number"):
            # GitHub's own list (without it, the description is read), and whether the description was edited after the merge
            closes, edited = closing.facts(repo_name, pull["number"], judge.github)
        facts["now"] = time.time()       # the one reading of the clock every later question about a reservation uses
        paid = judge.payee(pull, facts["issue"], facts["events"], facts["pull_comments"], facts["issue_comments"],
                           permission, bought, facts["now"], message, user, strict, closes, tip, edited)
        return pull, facts, paid

    common = dict(
        event=typer.Option(None, "--event", help="the pull_request event (GITHUB_EVENT_PATH), or a file holding the pull request: "
                                                 "who is paid, and the issue's assignment"),
        issue_file=typer.Option(None, "--issue-file", help="the issue as GitHub's API gives it (else fetched)"),
        diff=typer.Option(None, "--diff", help="the pull request's unified diff from the base"),
        evidence=typer.Option(None, "--evidence", help="write the evidence JSON here"),
        store=typer.Option(None, "--store", help="a directory the judge remembers in (Sibyl's local store: <dir>/sibyl.db)"),
        repo_name=typer.Option("", "--repo", help="owner/name"),
        agent=typer.Option("", "--agent", help="the pull request's author"),
        body_file=typer.Option(None, "--body-file", help="the pull request's description"),
        checks_file=typer.Option(None, "--checks-file", help="the head commit's check runs, as JSON (else fetched)"),
        head=typer.Option("", "--head", help="the head commit, to fetch its check runs from GitHub"),
        wait=typer.Option(0, "--wait", help="seconds to wait for the commit's other checks to finish"),
        terms_file=typer.Option(None, "--terms", help="the bounty's terms, as funded (their canonical JSON): the pull request "
                                                      "must meet them"),
        changed=typer.Option(None, "--changed", help="file listing the pull request's changed paths, one a line, a rename "
                                                     "under both its names (git diff --no-renames --name-only); with "
                                                     "--terms and none given, GitHub's list of the pull request's files"),
        statuses_file=typer.Option(None, "--statuses-file", help="the head commit's statuses, as JSON (else fetched)"),
        number=typer.Option(0, "--pull", help="the pull request's number, to read it from GitHub when there is no --event"),
    )

    @proof.command("gate")
    def gate(base: Path = typer.Option(..., "--base", help="the base branch checkout"),
             issue: str = typer.Option("", "--issue"),
             diff: Path = common["diff"], evidence: Path = common["evidence"], store: Path = common["store"],
             repo_name: str = common["repo_name"], agent: str = common["agent"], body_file: Path = common["body_file"],
             checks_file: Path = common["checks_file"], head: str = common["head"], wait: int = common["wait"],
             event: Path = common["event"], issue_file: Path = common["issue_file"],
             terms_file: Path = common["terms_file"], changed: Path = common["changed"],
             statuses_file: Path = common["statuses_file"], number: int = common["number"],
             funded: str = typer.Option("", "--funded", help="issue numbers that carry a bounty, comma-separated: a description "
                                                             "that mentions one without closing it is told so"),
             strict: bool = typer.Option(False, "--strict", help="at the merged commit: a claim that cannot be checked is refused")) -> None:
        """Check a pull request without running its code: the repository's rules, what its history requires, and whether
        "tests pass" in the description is true at the head commit. For a bounty's pull request it also checks
        the terms (with --terms: every funded check passed at that commit, nothing out of scope changed), who
        is paid, and the issue's assignment. Exit 1 unless it passes."""
        from .. import judge
        bought = _terms(terms_file)
        st, diff_text, body, runs, statuses = _inputs(store, diff, body_file, checks_file, repo_name, head, wait, bought, statuses_file)
        pull, facts, paid = _who(event, repo_name, issue, issue_file, bought, number, strict)
        _say(judge.gate(base, diff_text, st, repo_name or None, agent or None, body, runs, issue, pull,
                        facts.get("issue"), paid, strict, bought, statuses, _changed(changed, bought, repo_name, (pull or {}).get("number")),
                        [int(x) for x in funded.replace(",", " ").split() if x.isdigit()], facts.get("events"), facts.get("now")),
             evidence)

    @proof.command("payee")
    def payee(event: Path = common["event"], repo_name: str = common["repo_name"], number: int = common["number"],
              issue: str = typer.Option("", "--issue", help="the issue the pull request closes: its assignment decides too"),
              issue_file: Path = common["issue_file"], terms_file: Path = common["terms_file"],
              bound: str = typer.Option("", "--bound", help="the wallet bound to the payee's GitHub account, when you read one "
                                                            "from the chain"),
              strict: bool = typer.Option(False, "--strict", help="at the merged commit: the pull request must close --issue, and "
                                                                   "what GitHub did not answer pays nobody yet"),
              tip: bool = typer.Option(False, "--tip", help="who a `/knos tip` on this merged pull request goes to: decided on "
                                                            "the pull request alone, whatever was said about a bounty"),
              as_json: bool = typer.Option(False, "--json", help="print who is paid, why, and the payout address as JSON")) -> None:
        """Print the GitHub user id a pull request's bounty is paid to: its author, or for a pull request a bot
        opened, the person GitHub authenticates (the issue's assignee, a maintainer's `/knos pay @login`, or an
        assignee's `/knos mine`). Exit 1, saying why and what would fix it, when nobody is paid."""
        from .. import who
        _pull_, facts, paid = _who(event, repo_name, issue, issue_file, _terms(terms_file), number, strict, tip)
        if paid is None:
            raise Stop("not a pull request: pass --event, or --repo and --pull")
        if as_json:
            print(json.dumps({**paid, "address": who.payout_address(paid, facts["pull_comments"], bound or None)}))
        if not paid.get("id"):
            raise Stop(paid["why"] + ".", paid.get("fix") or "") if not as_json else typer.Exit(1)
        if not as_json:
            print(paid["id"])

    @proof.command("closes")
    def closes_cmd(event: Path = common["event"], repo_name: str = common["repo_name"], number: int = common["number"]) -> None:
        """Print the issues a pull request closes when it is merged, one number a line: GitHub's own list, and what
        its description closes with a keyword. A bounty is paid only for a pull request that closes its issue."""
        from .. import closing, judge
        pull = _pull(event, repo_name, number)
        if pull is None:
            raise Stop("not a pull request: pass --event, or --repo and --pull")
        listed = closing.read(repo_name, pull["number"], judge.github) if repo_name and pull.get("number") else None
        for n in closing.closed_by(pull, listed):
            print(n)

    @proof.command("comment")
    def comment_cmd(event: Path = typer.Option(..., "--event", help="the issue_comment or issues event (GITHUB_EVENT_PATH)"),
                    repo_name: str = common["repo_name"],
                    issue: str = typer.Option("", "--issue", help="for a comment on a pull request: the issue its bounty is on "
                                                                  "(else the one issue its description closes)"),
                    terms_file: Path = typer.Option(None, "--terms", help="that issue's bounty, as funded (its canonical JSON); "
                                                                          "none when it has no bounty")) -> None:
        """Answer one `/knos` comment (or a new issue's description). Prints one JSON object: the reply to post, the
        assignees to add and remove, and `then`, the step that still needs the blockchain (fund, tip, settle
        or status; empty when the reply is all). Prints nothing when there is no command."""
        import time

        from .. import closing, commands, judge, terms, who
        got = json.loads(event.read_text(encoding="utf-8"))
        on = got.get("issue") or {}
        said = got.get("comment") or on
        on_pull = "pull_request" in on
        command = commands.parse(said.get("body") or "", on_pull)
        name = getattr(command, "name", "")
        facts: dict[str, Any]
        pull, facts = None, {"issue": None, "events": None, "pull_comments": None, "issue_comments": None}
        permission = user = None
        if repo_name and on.get("number") and name not in ("", "fund", "status", "help"):
            permission, user = who.permission_of(repo_name, judge.github), who.user_of(judge.github)
            if not on_pull:     # take, release: the issue is in the event; who assigned whom, and when, is not
                facts.update(issue=on, events=terms.pages(f"repos/{repo_name}/issues/{on['number']}/events", judge.github))
            else:
                pull = _pull(None, repo_name, on["number"])
                if not isinstance(pull, dict):      # GitHub may answer with nothing at all (judge.github: an empty answer is None)
                    raise Stop(f"GitHub's answer for {repo_name}#{on['number']} was not a pull request.")
                if name not in ("tip", "settle"):
                    closes = closing.closing_issues(pull.get("body") or "", repo_name)
                    facts = who.read(repo_name, on["number"], issue or (closes[0] if len(closes) == 1 else ""), judge.github)
        o = who.answer(command, said.get("user") or {}, pull, facts["issue"], facts["events"], facts["pull_comments"],
                       facts["issue_comments"], permission, _terms(terms_file), time.time(), user)
        if o is not None:
            print(json.dumps({"command": name, "reply": o.reply, "assign": list(o.assign), "unassign": list(o.unassign), "then": o.then}))

    @proof.command("terms")
    def terms_cmd(repo_name: str = common["repo_name"],
                  command: str = typer.Option("", "--command", help="the fund command, e.g. \"/knos fund 20 checks: test\""),
                  body_file: Path = typer.Option(None, "--body-file", help="the comment (or the new issue's description) that holds the command"),
                  branch: str = typer.Option("", "--branch", help="the default branch (else asked of GitHub)"),
                  sha: str = typer.Option("", "--sha", help="the default branch's head commit (else asked of GitHub)"),
                  accept_dir: Path = typer.Option(None, "--accept-dir", help="the issue's acceptance bundle on the default branch "
                                                                             "(.knos/acceptance/<issue>): tests mode when it has files"),
                  issue: str = typer.Option("", "--issue", help="the issue being funded, for the reply"),
                  to: Path = typer.Option(None, "--out", help="write the canonical terms here, byte for byte"),
                  as_json: bool = typer.Option(False, "--json", help="print one JSON object: terms, hash, where the checks came "
                                                                     "from, the amount")) -> None:
        """Lock in a bounty's terms: read the fund command, ask GitHub what the repository requires (its required checks,
        else what ran on the default branch's head), and print the canonical terms and their hash. With --json
        it also prints the amount and the reply to post. A `/knos tip` gets the terms of a tip, which ask for
        nothing. Exit 1 with the reply to post when the command is neither, or the terms cannot be locked in."""
        from .. import commands, judge, terms
        text = body_file.read_text(encoding="utf-8", errors="replace") if body_file else command
        fund = commands.parse(text)
        if isinstance(fund, commands.Error):
            raise Stop(fund.reply)
        if not isinstance(fund, (commands.Fund, commands.Tip)):
            raise Stop(commands.reply("malformed", "fund", why="this needs a fund command"))
        tip = isinstance(fund, commands.Tip)
        accept = ""
        if not tip and accept_dir and accept_dir.is_dir() and any(p.is_file() for p in accept_dir.rglob("*")):
            accept = judge.checks_hash(accept_dir)
        required = runs = statuses = None
        if isinstance(fund, commands.Fund) and fund.checks != ():       # `checks: none` asks nothing of the repository
            if not repo_name:
                raise Stop("Name the repository whose checks the bounty buys: --repo owner/name.")
            try:
                branch = branch or judge.github(f"repos/{repo_name}")["default_branch"]
                sha = sha or judge.github(f"repos/{repo_name}/commits/{branch}")["sha"]
            except (OSError, KeyError, TypeError) as why:
                raise Stop(f"GitHub did not answer for {repo_name}: {why}") from None
            required = terms.required_checks(repo_name, branch, judge.github)
            runs, statuses = terms.head_checks(repo_name, sha, judge.github, events=True)
        try:
            built = terms.Built(terms.tip(), "tip", []) if tip else terms.build(fund, required, runs, statuses, accept)
            data = terms.canonical(built.terms)
        except terms.Refused as why:
            raise Stop(f"Knos: {why}") from None
        if to:
            to.write_bytes(data)
        if as_json:
            days = fund.days if isinstance(fund, commands.Fund) else terms.TIP_DAYS
            said = commands.reply("understood", fund, issue=issue, terms=built.terms, source=built.source, notes=built.notes)
            print(json.dumps({"command": fund.name, "terms": data.decode(), "hash": terms.terms_hash(data), "source": built.source,
                              "notes": built.notes, "units": fund.units, "days": days, "work": days * 86_400,
                              "mode": 1 if accept else 0, "reply": said}))
            return
        print(data.decode())
        print(terms.terms_hash(data))

    @proof.command("evidence")
    def evidence_cmd(terms_file: Path = typer.Option(..., "--terms", help="the bounty's terms, as funded (their canonical JSON)"),
                     repo_name: str = common["repo_name"],
                     sha: str = typer.Option("", "--sha", help="the commit: the pull request's head"),
                     number: int = typer.Option(0, "--pull", help="the pull request, to read its changed files from GitHub"),
                     changed: Path = common["changed"], checks_file: Path = common["checks_file"],
                     statuses_file: Path = common["statuses_file"], wait: int = common["wait"],
                     to: Path = typer.Option(None, "--out", help="write the verdict here as JSON")) -> None:
        """Check a bounty's terms against GitHub's record of one commit: each required check's state (passed, failed,
        skipped, pending, absent, unreadable) and the verdict. Exit 0 only when every check passed and no
        changed file is out of scope. A bounty funded with acceptance checks also needs those to pass: run
        `knos proof judge --terms`."""
        from .. import judge, terms
        bought = _terms(terms_file)
        if bought is None:
            raise Stop("Name the bounty's terms: --terms <file>.")
        if checks_file:
            runs = json.loads(checks_file.read_text(encoding="utf-8"))
            statuses = json.loads(statuses_file.read_text(encoding="utf-8")) if statuses_file else []
            found = terms.evidence(bought, runs, statuses)
        elif repo_name and sha:
            found, _runs, _statuses = terms.watch(bought, repo_name, sha, judge.github, wait)
        else:
            raise Stop("Nothing to read the checks from: pass --repo and --sha, or --checks-file.")
        if not changed and not (number and repo_name):
            raise Stop("Nothing says what the pull request changed: pass --changed, or --repo and --pull.")
        files = _changed(changed, bought, repo_name, number)
        ok, reasons = terms.accepted(bought, found, files)
        if to:
            to.write_text(json.dumps({"terms_hash": terms.terms_hash(bought), "mode": 1 if bought["mode"] == "tests" else 0,
                                      "accept": bought["accept"], "checks": found, "accepted": ok, "reasons": reasons},
                                     indent=1), encoding="utf-8")
        for name, state in found.items():
            out.print(f"{state:<10} {name}", markup=False, emoji=False)
        if bought["mode"] == "tests":
            out.print("this bounty also needs its acceptance checks to pass: knos proof judge --terms", markup=False)
        elif not bought["checks"]:
            out.print("no check is required: the merge alone is the acceptance", markup=False)
        for r in reasons:
            out.print(f"NO  {r}", markup=False, emoji=False)
        if not ok:
            out.print("[red]not accepted[/red]")
            raise typer.Exit(1)
        out.print("[green]accepted[/green]")

    memory = typer.Typer(add_completion=False, help="Keep the judge's memory between runs in the repository's knos-memory issue.")
    proof.add_typer(memory, name="memory")

    @memory.command("pull")
    def memory_pull(repo_name: str = typer.Option(..., "--repo", help="owner/name"),
                    store: Path = typer.Option(..., "--store", help="the directory of the judge's Sibyl store")) -> None:
        """Load what earlier runs learned, from the repository's knos-memory issue into the judge's Sibyl store."""
        from .. import judge
        from . import history
        from . import memory as lessons
        n = lessons.pull(repo_name, history.SibylStore.local(store), judge.github)
        if n is None:
            raise Stop(f"GitHub did not answer for {repo_name}'s knos-memory issue: this run remembers nothing.")
        out.print(f"Loaded {n} lesson(s) from {repo_name}'s knos-memory issue.", markup=False)

    @memory.command("push")
    def memory_push(repo_name: str = typer.Option(..., "--repo", help="owner/name"),
                    store: Path = typer.Option(..., "--store", help="the directory of the judge's Sibyl store"),
                    run_id: str = typer.Option("", "--run", help="this run's id, named in the comment")) -> None:
        """Post what this run learned to the repository's knos-memory issue (opened if there is none). Needs a token
        that may write issues: a run in the repository's own context."""
        from .. import judge
        from . import history
        from . import memory as lessons
        try:
            n = lessons.push(repo_name, history.SibylStore.local(store), judge.github, judge.github, run_id)
        except (OSError, KeyError, TypeError) as why:
            raise Stop(f"GitHub did not take the lessons: {why}") from None
        if n is None:
            raise Stop(f"GitHub did not answer for {repo_name}'s knos-memory issue: nothing was posted.")
        out.print(f"Posted {n} new lesson(s) to {repo_name}'s knos-memory issue." if n else "Nothing new to remember.", markup=False)

    @proof.command("judge")
    def judge_cmd(base: Path = typer.Option(..., "--base", help="the base branch checkout"),
                  pr: Path = typer.Option(..., "--pr", help="the pull request head source"),
                  issue: str = typer.Option(..., "--issue", help="the acceptance bundle: .knos/acceptance/<issue>/"),
                  changed: Path = typer.Option(None, "--changed", help="file listing the pull request's changed paths"),
                  setup: str = typer.Option("", "--setup", help="shell command that installs a tree's dependencies"),
                  sandbox: str = typer.Option("auto", "--sandbox", help="auto, require, off or hermetic"),
                  diff: Path = common["diff"], evidence: Path = common["evidence"], store: Path = common["store"],
                  repo_name: str = common["repo_name"], agent: str = common["agent"],
                  body_file: Path = common["body_file"], checks_file: Path = common["checks_file"],
                  head: str = common["head"], wait: int = common["wait"],
                  event: Path = common["event"], issue_file: Path = common["issue_file"],
                  terms_file: Path = common["terms_file"], statuses_file: Path = common["statuses_file"],
                  number: int = common["number"],
                  strict: bool = typer.Option(False, "--strict", help="at the merged commit: a claim that cannot be checked is refused")) -> None:
        """Tests mode: the gate, then the funder's acceptance checks in a sandbox (fail on the base, pass on the pull
        request). With --terms the pull request must meet them too, and the acceptance checks on the base must be
        the ones that were funded. Exit 1 unless it passes."""
        from .. import judge
        from . import engine
        cfg = dict(engine.config(base))
        cfg["issue"] = issue
        bought = _terms(terms_file)
        st, diff_text, body, runs, statuses = _inputs(store, diff, body_file, checks_file, repo_name, head, wait, bought, statuses_file)
        pull, facts, paid = _who(event, repo_name, issue, issue_file, bought, number, strict)
        _say(judge.judge_with_rules(base, pr, cfg, _lines(changed), diff_text, st, repo_name or None, agent or None, body,
                                    runs, setup or None, sandbox, pull, facts.get("issue"), paid, strict, bought, statuses,
                                    facts.get("events"), facts.get("now")), evidence)

    @proof.command("observe")
    def observe(sha: str = typer.Argument(...), check: str = typer.Argument(..., help="e.g. ci"),
                failed: bool = typer.Option(False, "--failed"), detail: str = typer.Option("", "--detail")) -> None:
        """Record later evidence about a commit (e.g. its CI failed after it was called done)."""
        from . import history
        repo = repo_of(None)
        history.observe(_store(repo), sha, check, not failed, detail)
        out.print(f"Recorded: {check} {'failed' if failed else 'passed'} at {sha[:8]}.")

    @proof.command("lint")
    def lint() -> None:
        """List the claims that this repository's evidence contradicts."""
        from . import history
        got = history.lint(_store(repo_of(None)))
        if not got:
            out.print("No claim here is contradicted by its evidence.")
        for x in got:
            out.print(f"  {x.sha[:8]}: claimed {', '.join(x.claimed) or 'done'}, but {x.failed} failed", markup=False)

    @proof.command("record")
    def record(words: str = typer.Argument("", help="find what Knos did about these words before, e.g. a check's or a file's name")) -> None:
        """What Knos remembers of claims of done in this repository: how many it refused, what failed last time, and the
        checks still owed. Read it before saying the work is done."""
        from . import history
        st = _store(repo_of(None))
        out.print(history.briefing(st) or "Knos has refused no claim of done in this repository (or its memory is not there).", markup=False)
        for line in history.recall(st, words) if words else []:
            out.print(f"  {line}", markup=False)

    @proof.command("learn")
    def learn() -> None:
        """Turn every past false "done" into a check this repo now requires."""
        from . import history
        rules = history.learn(_store(repo_of(None)))
        for r in rules:
            out.print(f"  a {r['when']} claim now requires {r['require']}  ({r.get('because', '')})", markup=False)
        if not rules:
            out.print("No false \"done\" claim in this repository's history yet.")
