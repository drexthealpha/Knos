#!/usr/bin/env python3
"""agent_pr_board.py -- the Agent PR Index as a weekly leaderboard, from the published series alone (no network).

    python scripts/agent_pr_index.py board            # write the table into docs/INDEX.md, docs/index.json, docs/index.atom
    python scripts/agent_pr_index.py board --check    # write nothing; exit 1 when any of the three differs

One row an agent: of its merged pull requests that claimed passing tests and whose checks had finished, how many
had a failed check at the head commit, the rate, and its 95% Wilson interval. The board of a week adds up every
week the series holds up to and including it, because one week alone holds too few pull requests to rank anyone.
An agent with fewer than `min_claims_to_rank` such pull requests has no place and is shown with its counts.

A row can be disputed (.github/ISSUE_TEMPLATE/dispute-index-row.yml). docs/index_disputes.json lists the disputes:

    {"schema": "knos.agent-pr-index.disputes/1",
     "disputes": [{"agent": "<row>", "week": "<Monday>" or null, "issue": "https://github.com/<repo>/issues/<n>",
                   "opened": "<date>", "status": "open" | "resolved" | "rejected", "resolved": "<date>" or null,
                   "outcome": "<what was found, in words>" or null,
                   "changed": [{"field": "failed_at_merge", "from": 10, "to": 9}]}]}

Beside the feed it writes one record file an agent, docs/records/<agent>.json (knos.record_page, docs/RECORD.md): the
agent's row as the public part of its record, labelled as coming from public pull requests and not from Knos orders.

An open dispute marks its row, with the link, on the board of its week and of every later one. A resolved dispute
that changed a number is listed in the changelog. Nothing here reads a payment: a row cannot be bought.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from fractions import Fraction
from typing import Any
from urllib.parse import urlencode
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_pr_index  # noqa: E402

SCHEMA = "knos.agent-pr-index/1"
DISPUTES_SCHEMA = "knos.agent-pr-index.disputes/1"
REPO = "https://github.com/drexthealpha/Knos"
RAW = "https://raw.githubusercontent.com/drexthealpha/Knos/main/docs"
TEMPLATE = "dispute-index-row.yml"
TOO_FEW = agent_pr_index.TOO_FEW
STATUSES = ("open", "resolved", "rejected")
NO_PAY = "An agent vendor never pays for a row and cannot pay to change one."
# Which pull requests a row counts. The Index publishes two bases, and a share means nothing without its own:
# every merged claiming pull request here; the first claiming pull request per repository in docs/BENCH.md.
BASIS = ("Basis: every merged pull request that claimed passing tests, so a busy repository counts many times. "
         "[BENCH.md](BENCH.md) counts the first such pull request per repository instead; the two shares differ.")
BEGIN = "<!-- board:begin (written by scripts/agent_pr_index.py board; do not edit by hand) -->"
END = "<!-- board:end -->"

MEASURE = {
    "claimed_passing": "pull requests the search returned for the agent whose description, read line by line, says tests "
                       "or CI pass, in every week read up to and including `week`",
    "merged": "of those, the ones that were merged when read and whose checks had finished at the head commit: the "
              "sample size of the row",
    "failed_at_merge": "of the merged, the ones with at least one failed check at the head commit",
    "share, ci95": "failed_at_merge over merged, and the 95% Wilson score interval of that share (z = 1.96)",
    "rank": "among the agents with at least `min_claims_to_rank` in `merged`: 1 is the smallest share, equal shares share "
            "a place. null: too few to rank. A place orders what was said against what GitHub recorded, not the agents' code",
    "overlaps_above": "true when the row's interval reaches into the interval of the row placed before it: the two "
                      "places are not told apart by this sample",
    "disputed": "the open disputes of the row: each an issue anyone can read",
}

METHOD = [
    "**The agent.** Told by the GitHub App that opened the pull request, or by a line its tool writes in the description "
    "(`agents_told_by` in the file). A person who pastes that line is counted as the agent.",
    "**The search.** GitHub's issue search, for pull requests of that agent whose description holds one of six phrases: "
    "\"tests pass\", \"all tests pass\", \"tests passing\", \"CI passes\", \"CI is green\", \"CI passing\".",
    "**Claimed passing tests.** The description is read line by line (`CLAIM_RE` in `scripts/agent_pr_ci.py`). A line that "
    "says tests or CI pass is a claim; an unticked box, a wish (\"should pass\") or a negation is not.",
    "**The checks.** The check runs and commit statuses GitHub holds for the head commit, read once.",
    "**A failed check** is a check run that concluded `failure`, `timed_out` or `startup_failure`, or a commit status of "
    "`failure` or `error`. The agent's own session run is not a check.",
    "**A failed check is not always a failed test.** It may be a deploy preview, a label gate, a review bot or a scanner; "
    "it may be flaky; it may have been failing before the pull request.",
    "**A failed check is not always a false claim.** The description may be true of the tests its author ran. The row "
    "says only that GitHub recorded a failed check on the commit that was merged.",
    "**The row.** Of the merged pull requests that claimed passing tests and whose checks had finished: how many had a "
    "failed check, that count over the total, and the 95% Wilson interval of the share.",
    "**The place.** Only agents with at least {least} such pull requests have one: place 1 is the smallest share, equal "
    "shares share a place. The others are \"too few to rank\", shown with their counts. \"overlaps\" means the interval "
    "reaches into the one above: this sample does not tell those two places apart.",
    "**The week.** A board is named by a Monday and adds up every week read up to and including it. Each week's own "
    "counts, and how it was read, are in [`agent_weekly.json`](agent_weekly.json).",
]

LIMITS = [
    "The counts are Knos's own measurement. Nobody outside Knos has reviewed them: dispute a row below.",
    "The samples are unequal, so the size sits beside every rate. Read the interval, not the share.",
    "The weeks were not all read with the same design (`design` of each week in `agent_weekly.json`). Adding them up "
    "mixes those designs.",
    "The agents are used on different repositories with different checks, so the rows are not samples of the same work.",
    "Public repositories only, and only pull requests whose description holds a claim phrase.",
    "One reading of the checks, a day or more after the week ended. A check run again later is not seen.",
    "\"At merge\" is the head commit of a pull request that was merged when read, not the moment of the merge.",
]


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_disputes(path: str | None, agents: Any = ()) -> list[dict[str, Any]]:
    """The disputes of `path`, checked; none when the file is not there. A wrong entry stops the run, in words."""
    if not path or not os.path.exists(path):
        return []
    got = _load(path)
    if got.get("schema") != DISPUTES_SCHEMA:
        raise SystemExit(f"{path}: schema is {got.get('schema')!r}, not {DISPUTES_SCHEMA!r}")
    out = []
    for i, d in enumerate(got.get("disputes", [])):
        where = f"{path}: dispute {i + 1}"
        if agents and d.get("agent") not in agents:
            raise SystemExit(f"{where}: {d.get('agent')!r} is not a row. The rows are: {', '.join(agents)}")
        if not str(d.get("issue", "")).startswith(("https://github.com/", "https://gitlab.com/")):
            raise SystemExit(f"{where}: `issue` must be the link of a public issue")
        if d.get("status") not in STATUSES:
            raise SystemExit(f"{where}: `status` is {d.get('status')!r}; it is one of {', '.join(STATUSES)}")
        if d["status"] != "open" and not (d.get("outcome") and d.get("resolved")):
            raise SystemExit(f"{where}: a dispute that is {d['status']} says what was found (`outcome`) and when (`resolved`)")
        changed = d.get("changed") or []
        if any(set(c) != {"field", "from", "to"} for c in changed) or (changed and d["status"] != "resolved"):
            raise SystemExit(f"{where}: `changed` lists {{field, from, to}} and only a resolved dispute has it")
        out.append({"agent": d["agent"], "week": d.get("week"), "issue": d["issue"], "opened": d.get("opened"), "status": d["status"],
                    "resolved": d.get("resolved"), "outcome": d.get("outcome"), "changed": changed})
    return out


def weeks_of(series: dict[str, Any]) -> list[str]:
    """Every week any agent has a row for, newest first."""
    return sorted({w["week"] for a in series["agents"].values() for w in a["weeks"]}, reverse=True)


def dispute_url(agent: str, week: str) -> str:
    """A new "Dispute a row" issue with the agent and the week filled in."""
    return f"{REPO}/issues/new?" + urlencode({"template": TEMPLATE, "title": f"Dispute a row: {agent}, week of {week}", "agent": agent, "week": week})


def board(series: dict[str, Any], week: str | None = None, disputes: Any = ()) -> dict[str, Any]:
    """The leaderboard of `week` (the newest when None): every agent's row over the weeks up to and including it,
    placed agents first by place, then the others in the file's order. Reads nothing; the same series gives the same board."""
    week = week or series.get("latest_week") or weeks_of(series)[0]
    least, rows, reads = series.get("min_claims_to_rank", agent_pr_index.MIN_CLAIMS_TO_RANK), [], [series["read"]]
    for name, agent in series["agents"].items():
        mine = [w for w in agent["weeks"] if w["week"] <= week]
        judged = [w for w in mine if w["ci_finished"]]          # a week with no finished checks has no merge state to lack
        known = all(w["merged_despite_failed_check"] is not None for w in judged)
        k = sum(w["merged_despite_failed_check"]["k"] for w in judged) if known else None
        n = sum(w["merged_despite_failed_check"]["n"] for w in judged) if known else None
        reads += [w["read"] for w in mine]
        rows.append({"agent": name, "weeks": len(mine), "claimed_passing": sum(w["claimed_passing"] for w in mine), "merged": n, "failed_at_merge": k,
                     "share": round(k / n, 4) if n else None, "ci95": agent_pr_index.wilson(k, n) if n else None, "rank": None,
                     "status": "not read" if n is None else "ranked" if n >= least else TOO_FEW, "overlaps_above": False,
                     "disputed": [{"issue": d["issue"], "opened": d["opened"]} for d in disputes
                                  if d["agent"] == name and d["status"] == "open" and (d["week"] or "") <= week],
                     "dispute": dispute_url(name, week)})
    placed = sorted((r for r in rows if r["status"] == "ranked"), key=lambda r: Fraction(r["failed_at_merge"], r["merged"]))
    shares = [Fraction(r["failed_at_merge"], r["merged"]) for r in placed]
    for i, r in enumerate(placed):
        r["rank"] = shares.index(shares[i]) + 1
        r["overlaps_above"] = i > 0 and r["ci95"][0] <= placed[i - 1]["ci95"][1]
    return {"week": week, "read": max(reads[1:] or reads),
            "min_claims_to_rank": least, "rows": placed + [r for r in rows if r["status"] != "ranked"]}


def changelog(disputes: Any) -> list[dict[str, Any]]:
    """The resolved disputes that changed a number, newest first."""
    return sorted(({k: d[k] for k in ("resolved", "agent", "week", "issue", "outcome", "changed")} for d in disputes
                   if d["status"] == "resolved" and d["changed"]), key=lambda d: d["resolved"], reverse=True)


def feed(series: dict[str, Any], disputes: Any = ()) -> dict[str, Any]:
    """docs/index.json: every week's board, the method, the limits, the disputes and the changelog."""
    least = series.get("min_claims_to_rank", agent_pr_index.MIN_CLAIMS_TO_RANK)
    canon = json.dumps(series, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return {"schema": SCHEMA, "name": series.get("name", agent_pr_index.NAME), "latest_week": weeks_of(series)[0], "read": series["read"],
            "basis": {"counts": "every_merged_claiming_pr", "says": BASIS.replace("[BENCH.md](BENCH.md)", "docs/BENCH.md"),
                      "other": "docs/BENCH.md and docs/bench.json `first_pr_per_repo`: the first claiming pull request per repository"},
            "min_claims_to_rank": least, "rule": NO_PAY, "measure": MEASURE, "method": [m.format(least=least) for m in METHOD], "limits": LIMITS,
            "agents_told_by": series.get("agents_told_by", {}), "claim_search": series.get("claim_search"),
            "source": {"file": "docs/agent_weekly.json", "sha256_of_canonical_json": hashlib.sha256(canon).hexdigest(),
                       "reproduce": "python scripts/agent_pr_index.py board --check"},
            "links": {"page": f"{REPO}/blob/main/docs/INDEX.md", "json": f"{RAW}/index.json", "atom": f"{RAW}/index.atom",
                      "dispute": f"{REPO}/issues/new?template={TEMPLATE}"},
            "weeks": [board(series, w, disputes) for w in weeks_of(series)], "disputes": list(disputes), "changelog": changelog(disputes)}


def _pct(x: float) -> str:
    return f"{x:.1%}"


def _line(r: dict[str, Any]) -> str:
    """One row in words, for a feed reader."""
    if not r["merged"]:
        return f"{r['agent']}: {r['claimed_passing']} claimed passing tests; no merged one with finished checks ({r['status']})"
    place = f"place {r['rank']}" + (", overlaps the place above" if r["overlaps_above"] else "") if r["rank"] else r["status"]
    return (f"{r['agent']}: {r['failed_at_merge']} of {r['merged']} merged had a failed check ({_pct(r['share'])}; 95% interval "
            f"{_pct(r['ci95'][0])} to {_pct(r['ci95'][1])}); {r['claimed_passing']} claimed passing tests; {place}"
            + ("; disputed" if r["disputed"] else ""))


def atom(doc: dict[str, Any]) -> str:
    """docs/index.atom: one entry a week, newest first. Every date is the day GitHub was read, so the same series
    gives the same bytes."""
    stamp = lambda day: f"{day}T00:00:00Z"  # noqa: E731
    out = ['<?xml version="1.0" encoding="utf-8"?>', '<feed xmlns="http://www.w3.org/2005/Atom">',
           f"  <title>{escape(doc['name'])}</title>",
           "  <subtitle>Of every merged agent pull request that claimed passing tests (not one per repository), how many had a failed check. By agent, by week, with sample sizes and 95% intervals.</subtitle>",
           f"  <id>{doc['links']['atom']}</id>", f'  <link rel="self" href="{doc["links"]["atom"]}"/>',
           f'  <link rel="alternate" href="{doc["links"]["page"]}"/>', f"  <updated>{stamp(doc['read'])}</updated>",
           "  <author><name>Knos</name></author>"]
    for w in doc["weeks"]:
        text = "\n".join([*(_line(r) for r in w["rows"]), "A failed check is not always a failed test, and not always a false claim.",
                          f"Method, limits and how to dispute a row: {doc['links']['page']}"])
        out += ["  <entry>", f"    <title>{escape(doc['name'])}, week of {w['week']}</title>",
                f"    <id>{doc['links']['json']}#{w['week']}</id>", f'    <link rel="alternate" href="{doc["links"]["page"]}"/>',
                f'    <link rel="related" type="application/json" href="{doc["links"]["json"]}"/>',
                f"    <updated>{stamp(w['read'])}</updated>", f'    <summary type="text">{escape(text)}</summary>', "  </entry>"]
    return "\n".join(out + ["</feed>"]) + "\n"


def table(doc: dict[str, Any], week: str | None = None) -> str:
    """What docs/INDEX.md holds between its board markers: the table, the method in ten lines, the limits, the week,
    how to work it again, the disputes and the changelog."""
    w = next(x for x in doc["weeks"] if x["week"] == (week or doc["latest_week"]))
    cell = lambda r: "not read" if r["merged"] is None else "0 of 0" if not r["merged"] else f"{r['failed_at_merge']} of {r['merged']}"  # noqa: E731
    lines = [f"**{doc['name']}, week of {w['week']}.** Read {w['read']}. Every week read up to this one, added up. "
             f"{BASIS} "
             f"An agent with fewer than {w['min_claims_to_rank']} merged pull requests in its row is \"{TOO_FEW}\".", "",
             "| Place | Agent | Claimed passing tests | Failed check at merge, of every merged one | Rate | 95% interval | Row |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in w["rows"]:
        place = TOO_FEW if r["status"] == TOO_FEW else r["status"] if r["rank"] is None else f"{r['rank']}{' (overlaps)' if r['overlaps_above'] else ''}"
        marks = "".join(f" [† disputed]({d['issue']})" for d in r["disputed"])
        lines.append(f"| {place} | {r['agent']}{marks} | {r['claimed_passing']} | {cell(r)} | {'' if not r['merged'] else _pct(r['share'])} | "
                     f"{'' if not r['merged'] else _pct(r['ci95'][0]) + ' to ' + _pct(r['ci95'][1])} | [dispute]({r['dispute']}) |")
    lines += ["", NO_PAY, "", "**Method, in ten lines.**", "", *(f"{i}. {m}" for i, m in enumerate(doc["method"], 1)), "",
              "**Limits.**", "", *(f"- {x}" for x in doc["limits"]), "",
              "**Work it again.** One command, no network, from the files of this repository. It counts the table again from "
              "[`agent_weekly.json`](agent_weekly.json) and fails when this page, [`index.json`](index.json) or "
              "[`index.atom`](index.atom) says anything else:", "", f"    {doc['source']['reproduce']}", "",
              "Every pull request behind the weeks read on 2026-10-01 is listed in [`agent_pr_ci.json`](agent_pr_ci.json) by "
              "repository and number, so each can be opened on GitHub and looked at.", "",
              "**Disputes.** Anyone can [dispute a row](" + doc["links"]["dispute"] + "): name the agent, the pull requests "
              "counted wrongly, and the evidence. An open dispute marks its row with † and its link."]
    opened = [d for d in doc["disputes"] if d["status"] == "open"]
    closed = [d for d in doc["disputes"] if d["status"] != "open"]
    lines += [""] + ([f"- open: {d['agent']}{'' if not d['week'] else ', week of ' + d['week']}, opened {d['opened']}: {d['issue']}" for d in opened]
                     + [f"- {d['status']} {d['resolved']}: {d['agent']}: {d['outcome']} ({d['issue']})" for d in closed] or ["No row has been disputed yet."])
    lines += ["", "**Changelog.** Every resolved dispute that changed a number."]
    lines += [""] + ([f"- {c['resolved']}: {c['agent']}{'' if not c['week'] else ', week of ' + c['week']}: "
                      + "; ".join(f"`{x['field']}` {x['from']} to {x['to']}" for x in c["changed"]) + f". {c['outcome']} ({c['issue']})"
                      for c in doc["changelog"]] or ["No number has changed after a dispute yet."])
    return "\n".join(lines)


def render(text: str, block: str, path: str = "the document") -> str:
    if BEGIN not in text or END not in text:
        raise SystemExit(f"{path}: the markers are not there:\n{BEGIN}\n{END}")
    head, rest = text.split(BEGIN, 1)
    return f"{head}{BEGIN}\n{block}\n{END}{rest.split(END, 1)[1]}"


def main(series_path: str, disputes_path: str | None, doc_path: str, feed_path: str, atom_path: str, check: bool = False) -> int:
    series = _load(series_path)
    doc = feed(series, load_disputes(disputes_path, list(series["agents"])))
    with open(doc_path, encoding="utf-8") as f:
        page = f.read()
    want = {doc_path: render(page, table(doc), doc_path), feed_path: json.dumps(doc, ensure_ascii=False, indent=1) + "\n", atom_path: atom(doc)}
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
    from knos import record_page       # standard library only: every agent's row as the public part of its record
    records = os.path.join(os.path.dirname(os.path.abspath(feed_path)), "records")
    want.update({os.path.join(records, name): text for name, text in record_page.index_records(doc).items()})
    stale = []
    for path, text in want.items():
        try:
            with open(path, encoding="utf-8") as f:
                same = f.read() == text
        except OSError:
            same = False
        if not same:
            stale.append(path)
            if not check:
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
    top = doc["weeks"][0]
    print(f"{doc['name']}, week of {top['week']}: {sum(r['rank'] is not None for r in top['rows'])} of {len(top['rows'])} agents placed, "
          f"{sum(d['status'] == 'open' for d in doc['disputes'])} open disputes; "
          + (("differs: " if check else "wrote ") + ", ".join(stale) if stale else "nothing to write"), file=sys.stderr)
    if check and stale:
        print("They are not what the series gives. Write them again: python scripts/agent_pr_index.py board", file=sys.stderr)
    return 1 if check and stale else 0
