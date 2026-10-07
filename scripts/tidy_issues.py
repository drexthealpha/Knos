#!/usr/bin/env python3
"""Every open issue and pull request of the owner's repositories, and what to do with each.

    python scripts/tidy_issues.py                      # a table, and the exact text of each comment; changes nothing
    python scripts/tidy_issues.py --rpc <devnet url>   # also reads from the chain whether a rehearsal's order still holds money
    python scripts/tidy_issues.py --rpc <url> --apply  # posts the comments and closes what the table says (through `gh`)
    python scripts/tidy_issues.py --json               # the same rows as data

The repositories: drexthealpha/Knos, knos-e2e*, knos-playground, knos-task, knos-attest, knos-workflows. Each open
item is one of:

    machine     an issue a workflow writes its log in (the relay log, "knos tokens", the judge's memory): it must stay
                open, because the workflow finds it by being open. Nothing is posted.
    rehearsal   the owner's own finished rehearsal (a title "C12: ...", "C-b: ...", "Track ...", or the words rehearsal, drill,
                canary, smoke, e2e, staging, test task). Closed with one line. With --rpc, one whose order still holds
                money is left open and said so; without --rpc nothing is closed by --apply, since that was not read.
    claim       an outside issue or pull request that claims a payment (knos.claim_guard reads it) and has no answer:
                the guard's own answer, the label `no-order`. Never closed.
    outside     any other outside contribution whose last word is not this repository's: one line of thanks that says
                who reads it and that it is unpaid. Never closed. An outside item already answered needs nothing.
    own         the owner's other open work: left alone.
    bot         an item another service's bot opened (dependabot and the like): left alone. Such a bot's comment is not
                this repository's word either: an outside item it spoke on last is still answered.

No comment quotes a word of the item it answers. Reading uses `gh api`; nothing is written without --apply.
"""
from __future__ import annotations

import argparse
import calendar
import fnmatch
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from knos import claim_guard  # noqa: E402

OWNER = "drexthealpha"
REPOS = ("Knos", "knos-e2e*", "knos-playground", "knos-task", "knos-attest", "knos-workflows")
MARK = "<!-- knos-tidy 1 -->"
REHEARSAL_DONE = "This was a devnet rehearsal, and it is finished. Closing it; nothing is owed on it."
THANKS = (MARK + "\nThank you for this. A maintainer reads it and answers here. Contributions are welcome and unpaid unless the issue "
          "shows a funded order, and this one shows none.")
_REHEARSAL = re.compile(r"^\s*(?:C(?:\d*[a-z]?|-[a-z]\d*)\s*:|Track\b)|\b(?:rehears\w*|drill|canary|smoke|e2e|staging|test task)\b", re.I)


def gh(args: list[str]) -> str:
    got = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)
    if got.returncode != 0:
        raise OSError(f"gh {' '.join(args[:3])}: {got.stderr.strip()[:200]}")
    return got.stdout


def _pages(run, path: str, cap: int = 10) -> list:
    rows: list = []
    for page in range(1, cap + 1):
        batch = json.loads(run(["api", f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}"]) or "[]")
        rows += batch if isinstance(batch, list) else []
        if not isinstance(batch, list) or len(batch) < 100:
            break
    return rows


def repositories(run, owner: str = OWNER, patterns=REPOS) -> list[dict]:
    """The owner's repositories whose names match, as GitHub lists them: [{"full_name", "id"}], by name."""
    rows = _pages(run, f"users/{owner}/repos?type=owner")
    return sorted(({"full_name": str(r["full_name"]), "id": int(r["id"])} for r in rows if isinstance(r, dict)
                   and any(fnmatch.fnmatchcase(str(r.get("name") or "").lower(), p.lower()) for p in patterns)), key=lambda r: r["full_name"].lower())


def _ours(who, association) -> bool:
    return claim_guard._ours(who, association)


def _age(stamp: str, now: float) -> int:
    try:
        return max(0, int((now - calendar.timegm(time.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S"))) // 86_400))
    except ValueError:
        return 0


def classify(item: dict, listed: dict[int, dict], now: float, funded: bool | None = None, comments: list | None = None) -> dict:
    """One row: {"number", "pull", "age", "category", "action", "comment", "close", "label", "note"}. `listed` are the
    repository's open items by number; `funded`: whether the chain holds money on this number (None: not read);
    `comments`: the item's comments, for an outside item (None: not read, and then nothing is proposed for it)."""
    number, pull = int(item["number"]), "pull_request" in item
    row = {"number": number, "pull": pull, "age": _age(item.get("created_at", ""), now), "comment": "", "close": False, "label": "", "note": ""}
    ours = _ours(item.get("user"), item.get("author_association"))
    title, body = str(item.get("title") or ""), str(item.get("body") or "")
    if claim_guard.machine(item):
        return {**row, "category": "machine", "action": "leave open", "note": "a workflow's log: it is found by being open"}
    if ours and _REHEARSAL.search(title):
        if funded:
            return {**row, "category": "rehearsal", "action": "leave open", "note": "its order still holds money on chain"}
        return {**row, "category": "rehearsal", "action": "close", "comment": REHEARSAL_DONE, "close": True,
                "note": "" if funded is False else "the chain was not read (--rpc): --apply leaves it"}
    if ours:
        return {**row, "category": "own", "action": "leave"}
    if claim_guard.bot(item.get("user")):
        return {**row, "category": "bot", "action": "leave", "note": "another service's bot: nothing is said to it"}
    if comments is None:
        return {**row, "category": "outside", "action": "read again", "note": "its comments could not be read"}
    claim = claim_guard.claims(title) or claim_guard.claims(body)
    if claim_guard.answered(comments) or any(str(c.get("body") or "").startswith(MARK) and _ours(c.get("user"), c.get("author_association")) for c in comments):
        return {**row, "category": "claim" if claim else "outside", "action": "nothing", "note": "answered already"}
    if claim:
        if funded:
            return {**row, "category": "claim", "action": "nothing", "note": "it holds a funded order: the payment workflows answer"}
        about = [n for n in claim_guard.named(f"{title}\n{body}") if n in listed and n != number][:claim_guard.MAX_ISSUES]
        logs = [n for n in about if claim_guard.machine(listed[n])]
        return {**row, "category": "claim", "action": "answer, label no-order", "label": claim_guard.LABEL,
                "comment": claim_guard.answer(pull, logs, [n for n in about if n not in logs])}
    last = comments[-1] if comments else None
    if last is not None and _ours(last.get("user"), last.get("author_association")):
        return {**row, "category": "outside", "action": "nothing", "note": "this repository spoke last"}
    return {**row, "category": "outside", "action": "answer", "comment": THANKS}


def survey(run, now: float, chain=None, owner: str = OWNER) -> list[dict]:
    """Every open item of every repository, classified. `chain(repo_id, number)` -> bool | None."""
    out = []
    for rp in repositories(run, owner):
        items = [i for i in _pages(run, f"repos/{rp['full_name']}/issues?state=open") if isinstance(i, dict) and "number" in i]
        listed = {int(i["number"]): i for i in items}
        for item in sorted(items, key=lambda i: int(i["number"])):
            ours = _ours(item.get("user"), item.get("author_association"))
            comments = None
            if not ours and not claim_guard.machine(item):
                try:
                    comments = _pages(run, f"repos/{rp['full_name']}/issues/{int(item['number'])}/comments")
                except (OSError, ValueError):
                    comments = None
            funded = chain(rp["id"], int(item["number"])) if chain is not None and not claim_guard.machine(item) else None
            out.append({"repo": rp["full_name"], **classify(item, listed, now, funded, comments)})
    return out


def apply(run, rows: list[dict], chain_read: bool) -> list[str]:
    """Do what the rows say, through `gh`: the comment, the label, the closing. A rehearsal is closed only when the
    chain said its order holds nothing. Returns one line per thing done or left."""
    done = []
    for r in rows:
        where = f"{r['repo']}#{r['number']}"
        if not r["comment"]:
            continue
        if r["close"] and (not chain_read or r["note"]):
            done.append(f"{where}: left (the chain was not read: give --rpc)")
            continue
        run(["api", "-X", "POST", f"repos/{r['repo']}/issues/{r['number']}/comments", "-f", f"body={r['comment']}"])
        if r["label"]:
            try:
                run(["api", "-X", "POST", f"repos/{r['repo']}/labels", "-f", f"name={r['label']}", "-f", "color=ededed"])
            except OSError:
                pass        # the label is there already
            run(["api", "-X", "POST", f"repos/{r['repo']}/issues/{r['number']}/labels", "-f", f"labels[]={r['label']}"])
        if r["close"]:
            run(["api", "-X", "PATCH", f"repos/{r['repo']}/issues/{r['number']}", "-f", "state=closed", "-f", "state_reason=completed"])
        done.append(f"{where}: {'commented and closed' if r['close'] else 'answered'}")
    return done


def table(rows: list[dict]) -> str:
    head = ["item", "kind", "age", "category", "action", "note"]
    cells = [[f"{r['repo']}#{r['number']}", "pull" if r["pull"] else "issue", f"{r['age']} d", r["category"], r["action"], r["note"]] for r in rows]
    wide = [max(len(str(x)) for x in col) for col in zip(head, *cells)]
    lines = ["  ".join(str(x).ljust(w) for x, w in zip(row, wide)).rstrip() for row in [head, *cells]]
    counts: dict[str, int] = {}
    for r in rows:
        counts[f"{r['category']}: {r['action']}"] = counts.get(f"{r['category']}: {r['action']}", 0) + 1
    lines += ["", *(f"{n:4d}  {k}" for k, n in sorted(counts.items()))]
    texts = dict.fromkeys(r["comment"] for r in rows if r["comment"])
    for n, text in enumerate(texts, 1):
        where = ", ".join(f"{r['repo']}#{r['number']}" for r in rows if r["comment"] == text)
        lines += ["", f"comment {n} (on {where}):", *("    " + ln for ln in text.splitlines())]
    return "\n".join(lines) + "\n"


def _chain(rpc: str):
    """`chain(repo_id, number)`: whether the chain holds money there (knos.claim_guard.funded, flow.py's own reading);
    None when it did not answer."""
    from knos import chain, flow
    run = flow.Run("", {}, ledger=chain.Ledger(rpc))

    def ask(repo_id: int, number: int) -> bool | None:
        try:
            return claim_guard.funded(run, repo_id, number)
        except Exception:  # noqa: BLE001 - not known
            return None
    return ask


def main(argv: list[str] | None = None, run=gh, now: float | None = None, chain=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--rpc", default="", help="a Solana devnet RPC: reads whether an item's order still holds money")
    p.add_argument("--apply", action="store_true", help="post the comments and close what the table says, through gh")
    p.add_argument("--json", action="store_true")
    p.add_argument("--owner", default=OWNER)
    args = p.parse_args(argv)
    chain = chain or (_chain(args.rpc) if args.rpc else None)
    rows = survey(run, time.time() if now is None else now, chain, args.owner)
    sys.stdout.write(json.dumps(rows, indent=1) + "\n" if args.json else table(rows))
    if args.apply:
        for line in apply(run, rows, chain is not None):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
