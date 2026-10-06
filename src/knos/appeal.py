"""An appeal: the supplier says a verdict is wrong, and the neutral judge runs it again.

    /knos appeal <reason>          a comment by the pull request's author, on the pull request
    knos appeal "<reason>" ...     the same on the command line

What an appeal is, as a state machine (`open_`, `asked`, `resolve`):

    rejected or insufficient evidence
        --open_-->  disputed, state `open`     who, when and why are recorded; the money does not move
        --asked-->  disputed, state `rerun`    the neutral judge was started (attest.yml: its first job, `rerun`, fetches
                                               the two commits and runs the funded suite itself, under another account)
        --resolve-> accepted                   the suite passed there: the rejection is overturned
                    rejected                   it did not pass there: the rejection stands, with the reasons in plain words
                    disputed, state `open`     the neutral judge could not run (its machine, an image, GitHub): that is
                                               nobody's failure, so nothing is decided and it is asked for again

An order that is paid on a merge has no suite to run again: the neutral judge reads the repository's check results and
does not run them. Its appeal is resolved by the arbiter the order named (`ruling`), and the record says so.

The verdict words are knos.ids.VERDICTS; an appeal is about one evaluation and carries that evaluation's id and its
deliverable's id (knos.ids). It has no id of another kind: one evaluation has one appeal.

Three things hold for every appeal, and the record says each: the money stays where the order's terms put it until
the appeal ends (`money`); an appeal costs the supplier nothing, whatever its outcome (`cost`), and its re-execution
is never billed to them; and an accepted verdict cannot be appealed by the supplier, because nothing was refused.

What is remembered (who appealed what, and how it ended) is kept through knos.proof.history (`remember`), in the
memory engine and nowhere else. The record itself is a document the supplier keeps: `knos appeal --out FILE`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import ghwords, ids

KIND, VERSION = "knos-appeal", 1
STATES = ("open", "rerun", "accepted", "rejected")
APPEALABLE = ("rejected", "insufficient_evidence")
MAX_REASON = 200
COST = {"supplier": 0, "note": "An appeal costs the supplier nothing, whatever its outcome. Its re-execution is not billed to them."}
# the reasons of a re-execution that say the judge could not run, not that the work failed
_INFRASTRUCTURE = frozenset({"rerun.cannot-run", "judge.image", "judge.no-sandbox", "judge.sandbox-python", "terms.files-unread",
                             "terms.check-unreadable", "who.unread"})


class Refused(ValueError):
    """The appeal cannot be opened or moved. `code` is its row in knos.ghwords.REFUSALS."""

    def __init__(self, code: str, detail: str = ""):
        happened, do = ghwords.refusal(code)
        super().__init__(f"{happened} {do}" + (f" ({detail})" if detail else ""))
        self.code = code


def _iso(at: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(at)))


def _plain(text, most: int = MAX_REASON) -> str:
    """Words from a comment, safe to say back: one line, no backtick, no `/knos` at its start."""
    said = " ".join("".join(ch if " " <= ch != "`" and ch != "\x7f" else " " for ch in str(text or "")).split())[:most].strip()
    while said.lower().startswith("/knos"):
        said = said[5:].lstrip()
    return said


def money(order_state: str = "open", mode: str = "tests") -> str:
    """Where the money is while the appeal is open, in one sentence, from the state of the order it is about."""
    if order_state == "paid":
        return "The order was paid already; the appeal is about the record, and moves nothing."
    if order_state == "refunded":
        return "The order's deadline passed and the money went back to its funder; a new order would pay an overturned verdict."
    if order_state == "none":
        return "No money is held for this work: the appeal is about the count only."
    return ("The money stays in escrow, as the order's terms put it: an appeal moves nothing, and nobody can take it "
            "out before the order's deadline.")


def next_step(mode: str = "tests", repo: str = "", pull: int = 0, arbiter: str = "") -> str:
    """The next step of an open appeal, in one sentence: who runs or rules, and how it is asked for."""
    where = f"https://github.com/{repo}/pull/{pull}" if repo and pull else "<the pull request's URL>"
    if mode == "tests":
        return (f"The neutral judge runs the funded acceptance checks again, itself: `knos settle --neutral {where}`, or start "
                "knos-attest.yml by hand with this repository, pull request and order, kind `pay`. Its verdict ends the appeal.")
    who = f"@{arbiter}, the arbiter the order names," if arbiter else "The arbiter the order names (it names none: the funder and the supplier agree on one)"
    return (f"This order is paid on a merge, so there is no suite to run again. {who} rules: knos-attest.yml, kind `rule`. "
            "That ruling ends the appeal.")


def open_(*, repo: str, pull: int, supplier: str, by: str, reason: str, at: float, verdict: str = "rejected",
          scope: str = "", key: str | int = "", artifact: str = "", evaluator: str = "", run: str | int = "",
          deliverable: str = "", evaluation: str = "", terms_hash: str = "", mode: str = "tests", order_state: str = "open",
          arbiter: str = "", existing: dict | None = None) -> dict:
    """Open an appeal and return its record: the verdict becomes `disputed`. Raises Refused (with the refusal's code) when
    `by` is not the supplier, the reason is empty, the verdict is `accepted`, or `existing` (the appeal already known for
    this evaluation) is still open or has ended.

    `supplier`: the pull request's author. `by`: who commented. `verdict`: the one being contested, any word
    knos.ids.verdict reads. The ids: give `deliverable` and `evaluation`, or what they are made of (`scope`: the order
    or the standing offer's terms hash; `key`: the milestone or issue; `artifact`: the judged commit; `evaluator`;
    `run`); the policy of the evaluation is the terms hash."""
    said = _plain(reason)
    if not said:
        raise Refused("appeal.no-reason")
    if str(by).strip().lower() != str(supplier).strip().lower() or not str(supplier).strip():
        raise Refused("appeal.not-supplier")
    was = ids.verdict(verdict)
    if existing and existing.get("state") in ("open", "rerun"):
        raise Refused("appeal.open")
    if existing and existing.get("state") in ("accepted", "rejected"):
        raise Refused("appeal.closed")
    if was == "disputed":
        raise Refused("appeal.open")
    if was not in APPEALABLE:
        raise Refused("appeal.nothing")
    deliverable = deliverable or ids.deliverable(scope or terms_hash or repo, key if key != "" else pull)
    evaluation = evaluation or ids.evaluation(deliverable, artifact, terms_hash, evaluator, run)
    if ids.kind_of(deliverable) != "deliverable" or ids.kind_of(evaluation) != "evaluation":
        raise ValueError("an appeal names a deliverable id and an evaluation id (knos.ids)")
    at = float(at)
    return {"kind": KIND, "v": VERSION, "id": evaluation, "deliverable": deliverable, "evaluation": evaluation,
            "repo": str(repo), "pull": int(pull), "terms_hash": str(terms_hash), "mode": mode, "arbiter": str(arbiter),
            "supplier": str(supplier), "by": str(by), "at": int(at), "at_iso": _iso(at), "reason": said,
            "was": was, "verdict": "disputed", "state": "open", "outcome": None, "why": "",
            "money": money(order_state, mode), "cost": dict(COST), "next": next_step(mode, repo, pull, arbiter),
            "history": [{"at": int(at), "by": str(by), "event": "opened", "note": said}]}


def _moved(appeal: dict, at: float, by: str, event: str, note: str, **changes) -> dict:
    if not isinstance(appeal, dict) or appeal.get("kind") != KIND or appeal.get("v") != VERSION or appeal.get("state") not in STATES:
        raise ValueError("that is not an appeal's record (knos appeal --out writes one)")
    if appeal["state"] in ("accepted", "rejected"):
        raise Refused("appeal.closed")
    return {**appeal, **changes, "history": [*appeal["history"], {"at": int(at), "by": str(by), "event": event, "note": _plain(note, 400)}]}


def asked(appeal: dict, at: float, run_url: str = "", by: str = "knos") -> dict:
    """The neutral judge was started for this appeal: state `rerun`, still disputed. `run_url`: the run's page."""
    return _moved(appeal, at, by, "re-execution asked", run_url or "the neutral judge was started", state="rerun")


def resolve(appeal: dict, at: float, rerun: dict | None = None, ruling: dict | None = None) -> dict:
    """End an appeal on the neutral judge's verdict (`rerun`: what its run wrote as verdict.json and posted as
    `knos-verdict:`) or, for an order paid on a merge, on the arbiter's ruling ({"by", "accepted", "why"}).

    It ends `accepted` or `rejected`, with the reason. A re-execution that could not run decides nothing: the appeal
    stays disputed and open, and is asked for again. A verdict about another pull request is refused (`rerun.other`)."""
    if (rerun is None) == (ruling is None):
        raise ValueError("an appeal ends on a re-execution's verdict or on a ruling: give one of the two")
    if ruling is not None:
        who, why = _plain(ruling.get("by"), 64), _plain(ruling.get("why"), 400)
        if not who or not isinstance(ruling.get("accepted"), bool):
            raise ValueError('a ruling is {"by": <the arbiter>, "accepted": true or false, "why": <one sentence>}')
        if appeal.get("arbiter") and who.lstrip("@").lower() != str(appeal["arbiter"]).lower():
            raise Refused("command.not_allowed", f"the order names @{appeal['arbiter']} as its arbiter")
        end = "accepted" if ruling["accepted"] else "rejected"
        why = why or f"@{who.lstrip('@')} ruled it {end}"
        return _moved(appeal, at, who, f"ruled {end}", why, state=end, verdict=end, outcome=end, why=why,
                      next="The appeal has ended." + (" The order can be paid: `knos settle`." if end == "accepted" else ""))
    if not isinstance(rerun, dict) or rerun.get("v") != 1 or not isinstance(rerun.get("reexecuted"), bool):
        raise ValueError("that is not a neutral judge's verdict (the `knos-verdict:` line of its comment, or its run's verdict.json)")
    if not rerun["reexecuted"]:
        return _moved(appeal, at, "neutral judge", "nothing re-executed", "this order is paid on a merge: the judge read the "
                      "repository's check results and ran nothing", state="open",
                      next=next_step("merge", appeal["repo"], appeal["pull"], appeal.get("arbiter", "")))
    if int(rerun.get("pull") or 0) != appeal["pull"] or str(rerun.get("repository") or "").lower() != appeal["repo"].lower():
        raise Refused("rerun.other")
    reasons = [str(r) for r in rerun.get("reasons") or []]
    if rerun.get("passed") is True and not reasons:
        why = "The neutral judge ran the funded acceptance checks again, itself, and they passed."
        return _moved(appeal, at, "neutral judge", "overturned", why, state="accepted", verdict="accepted", outcome="accepted", why=why,
                      next="The appeal has ended: the rejection is overturned. The order can be paid: `knos settle`.")
    told = [ghwords.explain(r) for r in reasons] or [ghwords.explain("the acceptance suite did not pass when it was run again here")]
    if all(t["code"] in _INFRASTRUCTURE for t in told):
        return _moved(appeal, at, "neutral judge", "could not run", told[0]["happened"], state="open",
                      next="The neutral judge could not run, which decides nothing. " + next_step(appeal["mode"], appeal["repo"], appeal["pull"], appeal.get("arbiter", "")))
    why = "The neutral judge ran the funded acceptance checks again, itself, and they did not pass: " + " ".join(
        f"{t['happened']} {t['do']} ({t['code']})" for t in told[:3])
    return _moved(appeal, at, "neutral judge", "upheld", why, state="rejected", verdict="rejected", outcome="rejected", why=why[:400],
                  next="The appeal has ended: the rejection stands. A new pull request is judged again, at no cost.")


def reply(appeal: dict) -> str:
    """The comment Knos answers `/knos appeal` with, and the lines the command line prints. Never starts with `/knos`."""
    word = ids.VERDICT_WORDS[appeal["verdict"]]
    head = {"open": f"Knos: appeal recorded. The verdict on #{appeal['pull']} is now **{word}**.",
            "rerun": f"Knos: the neutral judge is running #{appeal['pull']} again. The verdict stays **{word}** until it ends.",
            "accepted": f"Knos: appeal ended. #{appeal['pull']} is **accepted**: the rejection is overturned.",
            "rejected": f"Knos: appeal ended. #{appeal['pull']} stays **rejected**."}[appeal["state"]]
    lines = [head, "",
             f"- Who: @{appeal['by']}, {appeal['at_iso']}. Why: {appeal['reason']}",
             f"- Contested: {ids.VERDICT_WORDS[appeal['was']]} (evaluation `{appeal['evaluation']}`, deliverable `{appeal['deliverable']}`)"]
    if appeal["why"]:
        lines.append(f"- Reason it ended: {appeal['why']}")
    lines += [f"- Money: {appeal['money']}", f"- Cost to the supplier: nothing. {COST['note']}", f"- Next: {appeal['next']}"]
    return "\n".join(lines)


def refused_reply(why: Refused) -> str:
    """The comment for an appeal that could not be opened: what happened, what to do, and the code."""
    happened, do = ghwords.refusal(why.code)
    return f"Knos: no appeal was opened. {happened} {do} (`{why.code}`)"


def remember(store, appeal: dict) -> dict:
    """Keep where the appeal stands in the memory engine (knos.proof.history.appeal_outcome), and on the supplier's record."""
    from .proof import history
    last = appeal["history"][-1]["at"]
    return history.appeal_outcome(store, appeal["repo"], appeal["id"], appeal["state"], appeal["supplier"], appeal["pull"],
                                  appeal["reason"], appeal["why"], appeal["terms_hash"], at=last)


def recalled(store, repo: str, evaluation: str) -> dict | None:
    """What memory holds of the appeal of this evaluation: {"state", ...} (knos.proof.history.appeals), or None."""
    from .proof import history
    return next((b for b in history.appeals(store, repo) if b["id"] == evaluation), None)


def resume(row: dict, repo: str, deliverable: str = "", mode: str = "tests", arbiter: str = "", order_state: str = "open") -> dict:
    """An appeal's record rebuilt from what memory holds of it (`recalled`), for a later run that has no file: the
    workflow's re-execution job ends the appeal with `resolve(resume(...), now, rerun=verdict)`. `repo` as owner/name."""
    at = float(row["at"])
    deliverable = deliverable if ids.kind_of(deliverable) == "deliverable" else ids.deliverable(row.get("terms") or repo, row["pull"])
    return {"kind": KIND, "v": VERSION, "id": row["id"], "deliverable": deliverable, "evaluation": row["id"], "repo": str(repo),
            "pull": int(row["pull"]), "terms_hash": str(row.get("terms") or ""), "mode": mode, "arbiter": str(arbiter),
            "supplier": row["supplier"], "by": row["supplier"], "at": int(at), "at_iso": _iso(at), "reason": row["reason"],
            "was": "rejected", "verdict": "disputed" if row["state"] in ("open", "rerun") else row["state"], "state": row["state"],
            "outcome": row["state"] if row["state"] in ("accepted", "rejected") else None, "why": row.get("why", ""),
            "money": money(order_state, mode), "cost": dict(COST), "next": next_step(mode, repo, int(row["pull"]), arbiter),
            "history": [{"at": int(at), "by": row["supplier"], "event": "opened", "note": row["reason"]}]}


def from_comment(rest: str, *, repo: str, pull: dict, commenter: str, now: float, verdict: str, store=None, **order) -> tuple[dict | None, str]:
    """`/knos appeal <rest>` as knos.flow handles it: (the record or None, the reply to post). `pull`: GitHub's pull
    request object (its author is the supplier). `verdict`: the verdict it has now. `order`: what `open_` takes of the
    order (scope, key, artifact, evaluator, run, terms_hash, mode, order_state, arbiter). With a `store` the appeal is
    remembered, and one that memory already holds for this evaluation is not opened twice."""
    author = str((pull.get("user") or {}).get("login") or "")
    try:
        draft = open_(repo=repo, pull=int(pull.get("number") or 0), supplier=author, by=commenter, reason=rest, at=now, verdict=verdict, **order)
        if store is not None:
            open_(repo=repo, pull=draft["pull"], supplier=author, by=commenter, reason=rest, at=now, verdict=verdict,
                  existing=recalled(store, repo, draft["evaluation"]), **order)
            remember(store, draft)
    except Refused as why:
        return None, refused_reply(why)
    return draft, reply(draft)


# ---- the command line ------------------------------------------------------------------------------------------------

def register(app, help_lines: list | None = None) -> None:
    """`knos appeal`, on the main app. `help_lines`: cli._HELP, which gets the command's line."""
    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    if help_lines is not None:
        help_lines.append(("appeal", "For suppliers", "Contest a rejection: the verdict becomes disputed and the neutral judge runs it again. Costs nothing."))

    @app.command("appeal", rich_help_panel="For suppliers")
    def appeal_(reason: str = typer.Argument("", help="why the verdict is wrong, in one sentence"),
                repo: str = typer.Option("", "--repo", help="the repository, as owner/name"),
                pull: int = typer.Option(0, "--pull", help="the pull request's number"),
                by: str = typer.Option("", "--by", help="your GitHub login (the pull request's author)"),
                verdict: str = typer.Option("rejected", "--verdict", help="the verdict you contest: rejected, or insufficient evidence"),
                terms_file: Path = typer.Option(None, "--terms", help="the order's terms file (its hash names the terms the appeal is under)"),
                order: str = typer.Option("", "--order", help="the order's address, when the work has one"),
                issue: str = typer.Option("", "--issue", help="the issue or milestone the work is for"),
                head: str = typer.Option("", "--head", help="the commit that was judged"),
                mode: str = typer.Option("tests", "--mode", help="tests (paid on acceptance checks) or merge"),
                arbiter: str = typer.Option("", "--arbiter", help="merge mode: the arbiter the order names"),
                resolve_file: Path = typer.Option(None, "--resolve", help="an appeal's record: end it on --rerun or --ruling"),
                rerun_file: Path = typer.Option(None, "--rerun", help="with --resolve: the neutral judge's verdict.json"),
                ruling: str = typer.Option("", "--ruling", help="with --resolve, merge mode: accepted or rejected, by --arbiter"),
                record_of: str = typer.Option("", "--record", help="print one supplier's record in --repo from memory, and stop"),
                out: Path = typer.Option(None, "--out", help="write the appeal's record here (your own copy)"),
                tree: Path = typer.Option(Path("."), "--tree", help="your checkout: its memory is the one used"),
                as_json: bool = typer.Option(False, "--json", help="print the record as JSON")) -> None:
        """Contest a verdict. The verdict becomes `disputed`; who, when and why are recorded; the money stays where the
        terms put it; the neutral judge's own run ends it as accepted or rejected. An appeal never costs the supplier
        anything. `--resolve FILE --rerun VERDICT` ends one; `--record LOGIN` prints a supplier's record."""
        from . import cli, preflight
        from .proof import history
        store, memory = preflight.memory(tree)
        now = time.time()
        if record_of:
            got = {**history.supplier_record(store, repo or tree.resolve().name, record_of), "memory": memory}
            typer.echo(json.dumps(got, indent=1) if as_json else
                       f"{got['supplier']} in {got['repo']}: {got['accepted']} accepted, {got['rejected']} rejected, {got['appealed']} appealed, "
                       f"{got['overturned']} overturned. {memory['said']}")
            return
        try:
            if resolve_file is not None:
                record = json.loads(resolve_file.read_text(encoding="utf-8"))
                if rerun_file is not None:
                    record = resolve(record, now, rerun=json.loads(rerun_file.read_text(encoding="utf-8")))
                elif ruling:
                    record = resolve(record, now, ruling={"by": arbiter, "accepted": ids.verdict(ruling) == "accepted", "why": reason})
                else:
                    raise cli.Stop("--resolve needs the neutral judge's verdict (--rerun FILE) or, for an order paid on a merge, --ruling.",
                                   record.get("next", ""))
            else:
                if not repo or not pull or not by:
                    raise cli.Stop("An appeal names the pull request and who appeals.", "Give --repo owner/name --pull N --by <your login>.")
                thash = ""
                if terms_file is not None:
                    thash = preflight.read_terms(terms_file.read_text(encoding="utf-8"))["hash"]
                order_of = dict(scope=order or thash, key=issue or pull, artifact=head, evaluator="knos", run=head or pull, terms_hash=thash,
                                mode=mode, arbiter=arbiter, order_state="open" if order else "none")
                draft = open_(repo=repo, pull=pull, supplier=by, by=by, reason=reason, at=now, verdict=verdict, **order_of)
                record = open_(repo=repo, pull=pull, supplier=by, by=by, reason=reason, at=now, verdict=verdict,
                               existing=recalled(store, repo, draft["evaluation"]), **order_of)
        except Refused as why:
            happened, do = ghwords.refusal(why.code)
            raise cli.Stop(f"No appeal was opened. {happened}", f"{do} ({why.code})") from None
        except (OSError, ValueError) as why:
            raise cli.Stop(f"No appeal was opened: {ghwords.first_line(why)}.", "Give the files `knos appeal --out` and the neutral judge wrote.") from None
        remember(store, record)
        record = {**record, "memory": memory}
        if out is not None:
            out.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        typer.echo(json.dumps(record, indent=1, sort_keys=True) if as_json else
                   reply(record) + f"\n- Memory: {memory['said']}" + (f"\n- Your copy: {out}" if out is not None else ""))
