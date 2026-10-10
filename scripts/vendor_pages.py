#!/usr/bin/env python3
"""vendor_pages.py -- one page for each agent vendor the Agent PR Index rates: its numbers, its reply, its disputes and
what it can do to earn the supplier badge. From the published files alone; no network, no clock.

    python scripts/agent_pr_index.py vendors           # write docs/VENDORS.md and docs/vendors.json
    python scripts/agent_pr_index.py vendors --check   # write nothing; exit 1 when either differs

What a vendor gets, for each row:

    numbers    the row of the newest week (failed checks at merge, of merged, the share and its 95% Wilson interval,
               the place) and each week's own counts, so the sample is never hidden behind a rate
    reply      a right of reply: one click opens the "Reply for a vendor" form; a reply is listed in
               docs/index_replies.json and printed beside the row word for word, as the vendor wrote it
    disputes   one click opens the "Dispute a row" form with the agent and the week filled in; every dispute of the
               row, open or closed, with what was found (docs/index_disputes.json)
    badge      the two steps that turn the vendor's record from grey to green (docs/RECORD.md): the free check on its
               own pull requests, and accepted work under a funded order, which writes a signed delivery record

    docs/index_replies.json:
    {"schema": "knos.agent-pr-index.replies/1",
     "replies": [{"agent": "<row>", "issue": "https://github.com/<repo>/issues/<n>", "posted": "<date>", "text": "<the reply>"}]}

The index is not a rating of defect-free work, of the code, or of the vendor: the page says so first.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_pr_board  # noqa: E402

SCHEMA = "knos.vendors/1"
REPLIES_SCHEMA = "knos.agent-pr-index.replies/1"
REPO = agent_pr_board.REPO
SITE = "https://drexthealpha.github.io/Knos"
REPLY_TEMPLATE = "vendor-reply.yml"
MAX_REPLY = 1200
INSTALL = "uses: drexthealpha/Knos/.github/workflows/supplier.yml@v0.3.25"
NOT = [
    "It is not a rating of defect-free work: a merged pull request with no failed check can still be wrong.",
    "It is not a rating of the code or of the vendor: it counts what GitHub recorded against what a description said.",
    "A failed check is not always a failed test or a false claim (INDEX.md, method, points 6 and 7).",
]
BADGE_STEPS = [
    {"step": "Run the free check on your own pull requests",
     "how": f"One line in your repository's workflow: `{INSTALL}` (docs/RECORD.md, section 3)",
     "gives": "a check receipt for each pull request; the badge stays grey"},
    {"step": "Deliver accepted work under a funded order",
     "how": "A buyer funds an order; the work passes the terms fixed at funding and is paid on a token the forge signed",
     "gives": "an acceptance receipt for each delivery (docs/RECEIPT.md); the badge turns green, with its sample"},
]


def reply_url(agent: str) -> str:
    """A new "Reply for a vendor" issue with the agent filled in."""
    return f"{REPO}/issues/new?" + urlencode({"template": REPLY_TEMPLATE, "title": f"Reply for {agent}", "agent": agent})


def slug(agent: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in agent.lower()).strip("-")


def load_replies(path: str | None, agents: Any = ()) -> list[dict[str, Any]]:
    """The replies of `path`, checked; none when the file is not there. A wrong entry stops the run, in words."""
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        got = json.load(f)
    if got.get("schema") != REPLIES_SCHEMA:
        raise SystemExit(f"{path}: schema is {got.get('schema')!r}, not {REPLIES_SCHEMA!r}")
    out = []
    for i, r in enumerate(got.get("replies", [])):
        where = f"{path}: reply {i + 1}"
        if agents and r.get("agent") not in agents:
            raise SystemExit(f"{where}: {r.get('agent')!r} is not a row")
        if not str(r.get("issue", "")).startswith("https://github.com/"):
            raise SystemExit(f"{where}: `issue` must be the link of the public issue the reply was posted in")
        text = str(r.get("text") or "").strip()
        if not text or len(text) > MAX_REPLY:
            raise SystemExit(f"{where}: `text` is the reply word for word, 1 to {MAX_REPLY} characters")
        out.append({"agent": r["agent"], "issue": r["issue"], "posted": r.get("posted"), "text": text})
    return out


def weekly_counts(series: dict[str, Any], agent: str) -> list[dict[str, Any]]:
    """Each week's own counts for one agent, newest first: the sample of every week, apart."""
    out = []
    for w in sorted(series["agents"][agent]["weeks"], key=lambda w: w["week"], reverse=True):
        m = w.get("merged_despite_failed_check") if w.get("ci_finished") else None
        out.append({"week": w["week"], "claimed_passing": w.get("claimed_passing", 0),
                    "failed_at_merge": m["k"] if m else None, "merged": m["n"] if m else None})
    return out


def build(series: dict[str, Any], disputes: Any = (), replies: Any = ()) -> dict[str, Any]:
    """docs/vendors.json: one entry an agent, in the board's order."""
    top = agent_pr_board.board(series, None, disputes)
    vendors = []
    for r in top["rows"]:
        name = r["agent"]
        mine = [d for d in disputes if d["agent"] == name]
        vendors.append({
            "agent": name, "slug": slug(name), "page": f"{SITE}/#vendor={slug(name)}", "record": f"{SITE}/#record={slug(name)}",
            "row": {k: r[k] for k in ("weeks", "claimed_passing", "merged", "failed_at_merge", "share", "ci95", "rank", "status", "overlaps_above")},
            "weekly": weekly_counts(series, name),
            "reply": reply_url(name), "replies": [x for x in replies if x["agent"] == name],
            "dispute": r["dispute"],
            "disputes": {"open": [d for d in mine if d["status"] == "open"], "closed": [d for d in mine if d["status"] != "open"]},
        })
    return {"schema": SCHEMA, "name": series.get("name", agent_pr_board.agent_pr_index.NAME), "week": top["week"], "read": top["read"],
            "min_claims_to_rank": top["min_claims_to_rank"], "not": NOT, "badge": BADGE_STEPS, "rule": agent_pr_board.NO_PAY,
            "vendors": vendors}


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _row_line(row: dict[str, Any]) -> str:
    if row["merged"] is None:
        return "not read"
    if not row["merged"]:
        return "0 of 0 merged"
    place = f"place {row['rank']}" + (" (overlaps the one above)" if row["overlaps_above"] else "") if row["rank"] else row["status"]
    return (f"{row['failed_at_merge']:,} of {row['merged']:,} merged had a failed check: {_pct(row['share'])}, 95% interval "
            f"{_pct(row['ci95'][0])} to {_pct(row['ci95'][1])}; {row['claimed_passing']:,} claimed passing tests; {place}; "
            f"{row['weeks']} weeks added up")


def markdown(doc: dict[str, Any]) -> str:
    """docs/VENDORS.md."""
    lines = ["# Vendors in the Agent PR Index", "",
             "<!-- written by scripts/agent_pr_index.py vendors; do not edit by hand -->", "",
             f"One section for each agent the [Agent PR Index](INDEX.md) counts, week of {doc['week']} (read {doc['read']}): its "
             "numbers with their sample, its reply, its disputes, and how it earns the supplier badge. The site shows the "
             f"same as a page per vendor ([{SITE}/#vendor=copilot]({SITE}/#vendor=copilot)); the data is "
             "[`vendors.json`](vendors.json).", "", "**What the index is not.**", ""]
    lines += [f"- {n}" for n in doc["not"]]
    lines += ["", f"**The rule.** {doc['rule']} A reply or a dispute costs nothing and changes no number by itself; a "
              "dispute that finds a miscount changes the row, and the change is listed in the changelog of "
              "[INDEX.md](INDEX.md).", "",
              "**Earn the supplier badge.** The badge is the vendor's own record ([RECORD.md](RECORD.md)), apart from its "
              "index row.", ""]
    lines += [f"{i}. **{s['step']}.** {s['how']}. Gives {s['gives']}." for i, s in enumerate(doc["badge"], 1)]
    for v in doc["vendors"]:
        lines += ["", f"## {v['agent']}", "", f"**Row.** {_row_line(v['row'])}.", "",
                  "| Week | Claimed passing | Failed check at merge, of merged |", "| --- | --- | --- |"]
        lines += [f"| {w['week']} | {w['claimed_passing']:,} | "
                  + ("not finished" if w["merged"] is None else f"{w['failed_at_merge']:,} of {w['merged']:,}") + " |" for w in v["weekly"]]
        lines += ["", f"**Reply.** [Reply for {v['agent']}]({v['reply']}): printed here word for word.", ""]
        lines += [f"> {x['text']}  \n> ({x['posted']}, [{x['issue'].rsplit('/', 1)[-1]}]({x['issue']}))" for x in v["replies"]] or ["No reply yet."]
        lines += ["", f"**Disputes.** [Dispute this row]({v['dispute']}). Open: {len(v['disputes']['open'])}; closed: "
                  f"{len(v['disputes']['closed'])}."]
        lines += [f"- open since {d['opened']}: {d['issue']}" for d in v["disputes"]["open"]]
        lines += [f"- {d['status']} {d['resolved']}: {d['outcome']} ({d['issue']})" for d in v["disputes"]["closed"]]
        lines += ["", f"**Record.** [{v['agent']}'s supplier record]({v['record']}): grey until work is accepted under a funded order."]
    return "\n".join(lines) + "\n"


def main(series_path: str, disputes_path: str | None, replies_path: str | None, doc_path: str, data_path: str, check: bool = False) -> int:
    with open(series_path, encoding="utf-8") as f:
        series = json.load(f)
    agents = list(series["agents"])
    doc = build(series, agent_pr_board.load_disputes(disputes_path, agents), load_replies(replies_path, agents))
    want = {doc_path: markdown(doc), data_path: json.dumps(doc, ensure_ascii=False, indent=1) + "\n"}
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
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
    print(f"vendors, week of {doc['week']}: {len(doc['vendors'])} pages; "
          + (("differs: " if check else "wrote ") + ", ".join(stale) if stale else "nothing to write"), file=sys.stderr)
    if check and stale:
        print("Write them again: python scripts/agent_pr_index.py vendors", file=sys.stderr)
    return 1 if check and stale else 0
