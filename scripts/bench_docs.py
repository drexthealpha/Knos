"""Write the measured numbers in the docs from their sources, so that no doc states one by hand: docs/bench.json (the
Agent PR Index scan the docs quote, the programs' compute units, what was measured on devnet) and docs/backtest.json
(scripts/backtest.py).

    python scripts/bench_docs.py                     rewrite the marked blocks
    python scripts/bench_docs.py --check             exit 1 if a doc has drifted from the source, or names a slot this
                                                     script does not know (the test suite runs this)
    python scripts/bench_docs.py --from index.json   first take docs/bench.json's index numbers from a published
                                                     index.json, counted again from its own records (its Merkle root
                                                     must match)
    python scripts/bench_docs.py --stats stats.json  first take what was measured on devnet from the site's stats.json
                                                     (scripts/network_stats.py): the release runs this once
    python scripts/bench_docs.py --set NAME=NUMBER --source "where it was measured"
                                                     fill one slot that stats.json cannot (see SLOTS)
    python scripts/bench_docs.py --slots             list the slots that have no number yet; exit 1 if there is one

A block is `<!-- bench:NAME -->` ... `<!-- /bench:NAME -->` in README.md or docs/BENCH.md:

    headline      README: the index's two named figures, and the merged pull requests
    market        the index: a failed check of any kind, per agent
    market-tests  the same pull requests, counting only failed tests and builds
    backtest      the merged ones
    verify2 pay2  the second deployment's compute units (programs-v2): verifying a token, the escrow's instructions
    verify1 pay1  the first deployment's (programs)
    walk2 walk1   the escrows' last random walks
    devnet        the second deployment on devnet. A number nobody has measured yet reads "measured at release"
    devnet1       the first deployment's record on devnet

A slot is `[[stat: name]]` in a file under docs/submission/ or in one of SLOTTED (README.md, CHANGELOG.md and the
documents a judge opens): a number that only the release run can measure. SLOTS names every slot and says what it
counts. `--stats` fills the ones stats.json has, `--set` fills one of the others. Filling a slot does three things: the
number replaces the slot in the text, in every file that carries it; it is kept in docs/bench.json (`devnet.stats`, at
the same path as in stats.json, or `release.<name>` with its source); and a fact in docs/facts.json points at it, so
scripts/claims_check.py can hold the text to it. A slot with no number is left as it stands. A slot is filled once:
after that the text holds the number, and a later change is an edit of docs/bench.json and of the text.

Two slots are a time, not a number (WHEN): `--set upgrade_proposed="2026-10-05 14:00 UTC"` says when the upgrade of the
second deployment was approved by the multisig, and `upgrade_executable` is filled with it, 48 hours later, so the two
cannot disagree.

One fact, one value. FRAMES names the sentences in which a slot's fact is stated (in any public document and in the
site's text). `--check` fails when two of them give different values for one fact (a slot in one file and a number in
another is two values), when the slot in such a sentence is another fact's, or when the number is not the one
docs/bench.json keeps.
"""

from __future__ import annotations

import html
import json
import math
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "docs/BENCH.md"]
# The pitch-facing text (scripts/claims_check.py reads the same list): every number in it needs a fact.
PITCH = ["README.md", "web/index.html", "docs/submission/SUBMISSION.md", "docs/submission/pitch_script.md",
         "docs/submission/demo_script.md", "docs/submission/weekly_update.md"]
SUBMISSION = "docs/submission"       # every .md under it may carry [[stat: name]] slots
# The other files that may carry slots. Everything a judge opens states a release-measured fact through one, so that the
# release fills them all in one run and no document is left with an older number.
SLOTTED = ["README.md", "CHANGELOG.md", "docs/DISCLOSURE.md", "docs/WHY.md", "docs/COMPARE.md", "docs/MARKET.md",
           "docs/SECURITY.md", "docs/ASSURANCE.md", "docs/BENCH.md"]
UNMEASURED = "measured at release"
SLOT = re.compile(r"(?<!`)\[\[stat: ([a-z][a-z_]*)\]\]")      # not one quoted as code: that is the docs naming the syntax
# The rows of the `devnet` block: (what was measured, its path in stats.json).
DEVNET = [
    ("tasks funded", "by_deployment.second.funded"),
    ("tasks paid", "by_deployment.second.completed"),
    ("tasks funded with their own tokens by someone other than Knos, both deployments", "outside.funded"),
    ("of those, paid to someone other than the funder", "outside.completed"),
    ("funders among them", "outside.funders"),
    ("funders who funded again after one of their tasks was paid", "outside.repeat_funders"),
    ("payments timed from the merge, over the public relay's log", "latency.merge_to_paid.count"),
    ("seconds from the merge to the payment, median", "latency.merge_to_paid.median"),
    ("seconds from the merge to the payment, 90th percentile", "latency.merge_to_paid.p90"),
    ("seconds from the funding comment to the funded task, median", "latency.comment_to_funded.median"),
]
# Every slot: name -> (what the number counts, its path in stats.json). With no path, the release run measures the
# number itself and gives it with --set and --source.
SLOTS = {
    "tasks_paid_on_the_second_deployment": ("tasks paid on the second deployment, on devnet", "by_deployment.second.completed"),
    "outside_tasks_paid": ("tasks, on both deployments, that someone other than Knos funded with their own tokens and "
                           "that were paid to someone other than the funder", "outside.completed"),
    "outside_funders": ("the funders of those tasks", "outside.funders"),
    "funders_who_funded_again": ("of those funders, the ones who funded another task after one of theirs was paid",
                                 "outside.repeat_funders"),
    "seconds_from_merge_to_paid": ("seconds from the merge to the payment, the median over the public relay's log",
                                   "latency.merge_to_paid.median"),
    "payments_timed": ("the payments that median is over", "latency.merge_to_paid.count"),
    "payments_between_unrelated_accounts": (
        "payments on devnet, both deployments, whose payee is another GitHub account than the one that funded the task: "
        "the `knos:paid` and `knos2:paid` lines of the escrows' logs whose payee is not the task's funder", None),
    "outside_prs_merged_and_paid": ("of the pull requests #32, #33 and #34 by jaystay-bot, the ones that were merged and "
                                    "paid on devnet when the release ran", None),
    "tests_passing": ("tests that passed in the release's own run of the suite (`pytest -q` on the release commit)", None),
    "claim_parser_executions": ("inputs the fuzzer ran against the claim parser in the latest nightly run of program.yml: "
                                "`executions` and `source` in the fuzz.json of its `fuzz-claims` artifact", None),
    "upgrade_proposed": ("when the upgrade of knos_oidc and knos_pay to 2.1 was proposed to the upgrade multisig and approved "
                         "by its members on devnet (UTC, to the minute; the later of the two programs' approvals). `node "
                         "scripts/governance.mjs upgrade propose` stops after the approvals and prints when the proposal can "
                         "be executed, which is this time plus 48 hours; `knos status` reads the same from the chain", None),
    "upgrade_executable": ("48 hours after that approval: the first moment the Squads program lets the upgrade execute. "
                           "Filled with upgrade_proposed, never by itself", None),
    "days_of_shipping": ("days, from 1 Sep 2026 to the release, on which drexthealpha made a commit in the public "
                         "repository (the automatic commits of a workflow are left out): "
                         "`git log --author=drexthealpha --format=%ad --date=short | sort -u | wc -l`", None),
}
# The slots whose value is a time (UTC, to the minute), not a number.
WHEN = {"upgrade_proposed", "upgrade_executable"}
TIME = "%Y-%m-%d %H:%M UTC"
DELAY_HOURS = 48                      # the upgrade multisig's time lock (programs-v2/program_ids.json, upgrade_multisig)
_V = r"(\[\[stat: [a-z_]+\]\]|\d[\d,]*(?:\.\d+)?)"
_T = r"(\[\[stat: [a-z_]+\]\]|\d{4}-\d\d-\d\d \d\d:\d\d UTC)"
# The sentences in which a slot's fact is stated, each with one group: the value as written, a number or a slot.
FRAMES = {
    "seconds_from_merge_to_paid": [rf"merge to (?:paid|payment|the payment)\b[^.|]{{0,60}}?{_V} seconds",
                                   rf"{_V} seconds from (?:the )?merge to (?:paid|payment|the payment)"],
    "payments_timed": [rf"seconds\b[^.|]{{0,40}}? over {_V} payments"],
    "tests_passing": [rf"{_V} tests pass"],
    "claim_parser_executions": [rf"{_V} inputs against the claim parser"],
    "upgrade_proposed": [rf"proposed(?: and approved)?(?: by the multisig)? on {_T}"],
    "upgrade_executable": [rf"can execute from {_T}"],
}


def blocks(src: dict, bt: dict | None = None) -> dict[str, str]:
    ix = src["market"]["index"]
    out = {"market": market_index(ix), "market-tests": market_tests(ix)}
    if bt:
        out["backtest"] = backtest(bt, [label for label, _ in ix["agents"]])
        out["headline"] = headline(ix, bt)
    chain = src.get("chain")
    if chain:
        out.update({"verify2": verify(chain, "second"), "pay2": pay_second(chain), "verify1": verify(chain, "first"),
                    "pay1": pay_first(chain), "walk2": walk_second(chain["second"]["walks"]),
                    "walk1": walk_first(chain["first"]["walk"])})
    if "devnet" in src:
        out["devnet"] = devnet(src["devnet"])
        out["devnet1"] = devnet_first(src["devnet"]["first"])
    return out


def _share(k: int, n: int) -> str:
    """k of n as a percentage, rounded once from the counts. (A share docs/bench.json already rounded to four places
    can land a tenth off when it is rounded again: 0.2055 prints as 20.5% where the exact 20.552% is 20.6%.)"""
    return f"{100 * k / n:.1f}%"


def _interval(k: int, n: int, between: str = "–") -> str:
    """The 95% Wilson interval of k of n, rounded once from the counts."""
    z = 1.96
    p, d = k / n, 1 + z * z / n
    mid = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{100 * max(0.0, mid - half):.1f}%{between}{100 * min(1.0, mid + half):.1f}%"


def headline(ix: dict, bt: dict) -> str:
    """The README's numbers: the index's two counts under names that say which is which, and the merged pull requests
    of the sample that records merges."""
    r = ix["overall"]["first_pr_per_repo"]
    n, f, t = r["repos"], r["any_check_failed"]["repos"], r["test_or_build_check_failed"]["repos"]
    m = bt["sample"]["merged"]["overall"]
    mn, mk = m["prs"], m["any_check_failed"]["prs"]
    return "\n".join([
        f"**Agent PR Index, {ix['date']}.** In {n:,} repositories, the first pull request by an AI coding agent whose "
        f"description said tests or CI pass had:", "",
        f"- **a failed check of any kind** at its head commit in {f:,} ({_share(f, n)}; 95% interval "
        f"{_interval(f, n, ' to ')});",
        f"- **a failed test, build, lint or type-check job** in {t:,} ({_share(t, n)}; 95% interval "
        f"{_interval(t, n, ' to ')}). Names decide this one, so read it as the cautious figure.", "",
        f"Of the {mn:,} merged agent pull requests in the smaller sample that records merges, {mk:,} ({_share(mk, mn)}) "
        f"had a failed check while their description said tests pass. A failed check is GitHub's record, not a "
        f"judgment of why it failed."])


def market_index(ix: dict) -> str:
    """The Agent PR Index scan (scripts/agent_pr_index.py): one pull request per repository first (a busy repository
    counts once), then every pull request; shares with 95% Wilson intervals, per agent and overall. Every figure here
    is `any_check_failed`: a failed check of any kind."""
    o, r = ix["overall"], ix["overall"]["first_pr_per_repo"]
    n, f, of = r["repos"], r["any_check_failed"]["repos"], o["any_check_failed"]["prs"]
    lines = [f"**Agent PR Index, {ix['date']}:** in {n:,} repositories, the first pull request by an AI coding "
             f"agent whose description said tests or CI pass had **a failed check of any kind in {f:,} ({_share(f, n)})** "
             f"(95% Wilson interval {_interval(f, n)}). Counting every such pull request "
             f"instead of one per repository, it is {of:,} of {o['prs']:,} ({_share(of, o['prs'])}); "
             f"that figure leans on a few busy repositories, so the per-repository one is the one to quote. Pull requests "
             f"created {ix['window'][0]} – {ix['window'][1]} whose CI had finished at the head commit; "
             f"{ix['excluded_self_repo']:,} on repositories owned by the pull request's author or the person who "
             f"assigned the agent were left out. A failed check is GitHub's record, not a judgment of why it failed. "
             f"The list is published as `index.json` on the Pages site. A new scan is scheduled every 6 hours "
             f"(`.github/workflows/index.yml`) and replaces the published list only when it has finished, so the date "
             f"above says which scan these numbers are from.", "",
             "| agent | repositories | first claiming PR: any check failed | 95% interval | all claiming PRs | any check failed |",
             "|---|---|---|---|---|---|"]
    for label, a in ix["agents"]:
        if a["prs"]:
            b = a["first_pr_per_repo"]
            bn, bf, af = b["repos"], b["any_check_failed"]["repos"], a["any_check_failed"]["prs"]
            lines.append(f"| {label} | {bn:,} | {bf:,} ({_share(bf, bn)}) | {_interval(bf, bn)} | {a['prs']:,} | "
                         f"{af:,} ({_share(af, a['prs'])}) |")
    lines.append(f"| **all** | **{n:,}** | **{f:,} ({_share(f, n)})** | **{_interval(f, n)}** | {o['prs']:,} | "
                 f"{of:,} ({_share(of, o['prs'])}) |")
    return "\n".join(lines)


def market_tests(ix: dict) -> str:
    """The same scan under the stricter count, `test_or_build_check_failed`: a failed check that is, by its name, a
    test, build, lint or type-check job. A failed deploy preview or label gate does not contradict "tests pass"."""
    o, r = ix["overall"], ix["overall"]["first_pr_per_repo"]
    n, f, t = r["repos"], r["any_check_failed"]["repos"], r["test_or_build_check_failed"]["repos"]
    ot = o["test_or_build_check_failed"]["prs"]
    lines = [f"**Counting only failed tests and builds:** a failed check is not always a failed test. In "
             f"**{t:,} of the {n:,} repositories ({_share(t, n)})** (95% Wilson interval {_interval(t, n)}) one of "
             f"the failed checks was, by its name, a test, build, lint or type-check job. In the other {f - t:,} of "
             f"the {f:,} no failed check had such a name: deploy previews, title and label gates, review bots, "
             f"coverage thresholds, security scanners, and jobs whose names do not say what they run (`check`, "
             f"`validate`). Over every pull request it is {ot:,} of {o['prs']:,} ({_share(ot, o['prs'])}). So \"said "
             f"tests pass while a check failed\" is {_share(f, n)} of repositories, and \"while a test or build "
             f"check failed\" is {_share(t, n)}; names decide the second, so read it as the cautious figure, not an "
             f"exact one.", "",
             "| agent | repositories | any check failed | a test or build check failed | 95% interval | all claiming PRs | a test or build check failed |",
             "|---|---|---|---|---|---|---|"]
    rows = [(label, a) for label, a in ix["agents"] if a["prs"]] + [("**all**", o)]
    for label, a in rows:
        b = a["first_pr_per_repo"]
        bn, bf, bt = b["repos"], b["any_check_failed"]["repos"], b["test_or_build_check_failed"]["repos"]
        at = a["test_or_build_check_failed"]["prs"]
        bold = "**" if a is o else ""
        lines.append(f"| {label} | {bold}{bn:,}{bold} | {bf:,} ({_share(bf, bn)}) | {bold}{bt:,} ({_share(bt, bn)}){bold} | "
                     f"{bold}{_interval(bt, bn)}{bold} | {a['prs']:,} | {at:,} ({_share(at, a['prs'])}) |")
    return "\n".join(lines)


def backtest(bt: dict, labels: list[str]) -> str:
    """docs/backtest.json in words: the merged pull requests of the 1 Oct 2026 sample, and what the data cannot show.
    A bounty pays on the checks its terms require, so a failed check refuses a payment only when it is one of them."""
    s = bt["sample"]
    m, fate = s["merged"]["overall"], s["fate"]
    n, k, t, c = m["prs"], m["any_check_failed"]["prs"], m["test_or_build_check_failed"]["prs"], m["cancelled_no_failure"]["prs"]
    bad, good = fate["any_check_failed"], fate["no_check_failed"]
    w = s["without_author_owned_repos"]["merged"]["overall"]
    lines = [f"Of the {s['with_finished_ci']:,} pull requests in the sample read on {s['read']} (created {s['created'][0]} – "
             f"{s['created'][1]}; `docs/agent_pr_ci.json`) whose description said tests or CI pass and whose CI had "
             f"finished, {n:,} had been merged. **{k:,} of those {n:,} ({_share(k, n)})** (95% Wilson interval "
             f"{_interval(k, n)}) had a failed check at the head commit. A Knos bounty whose terms required that "
             f"check would not have paid the merge. In {t:,} of them ({_share(t, n)} of the merged) a failed check "
             f"was a test or a build by its name. {c:,} more had no failed check but a cancelled one, which a bounty "
             f"that required it counts as failed. Without the repositories the pull request's author owns it is "
             f"{w['any_check_failed']['prs']:,} "
             f"of {w['prs']:,} ({_share(w['any_check_failed']['prs'], w['prs'])}). A pull request with a failed check "
             f"was merged less often than one without: {bad['merged']:,} of {bad['prs']:,} ({_share(bad['merged'], bad['prs'])}) "
             f"against {good['merged']:,} of {good['prs']:,} ({_share(good['merged'], good['prs'])}); "
             f"{bad['open']:,} and {good['open']:,} were still open when read.", "",
             "| agent | merged | any check failed | 95% interval | a test or build check failed |", "|---|---|---|---|---|"]
    for label, a in [*zip(labels, s["merged"]["agents"].values()), ("**all**", m)]:
        if a["prs"]:
            ak, at = a["any_check_failed"]["prs"], a["test_or_build_check_failed"]["prs"]
            lines.append(f"| {label} | {a['prs']:,} | {ak:,} ({_share(ak, a['prs'])}) | {_interval(ak, a['prs'])} | "
                         f"{at:,} ({_share(at, a['prs'])}) |")
    lines += ["", "What this cannot show:", ""] + [f"- {line}." for line in bt["cannot_show"]]
    return "\n".join(lines)


# ---- the programs' compute units (docs/bench.json, "chain") ------------------------------------------------------------

def _steps(steps: list[int]) -> str:
    """Two steps are named; six are given as their lowest and highest."""
    return " and ".join(f"{s:,}" for s in steps) if len(steps) <= 2 else f"{min(steps):,} to {max(steps):,}"


def verify(chain: dict, which: str) -> str:
    """One deployment's verifier: the compute units of each transaction that verifies a token, by key size and token
    length. Every figure is for a token account whose address the program finds at its first try: the lowest of the
    runs measured, since a run's figure moves with the address."""
    d = chain[which]
    lines = ["| token | key | transactions | compute units of each |", "|---|---|---|---|"]
    for row in d["verify"]:
        lines.append(f"| {row['bytes']:,} bytes{', ' + row['what'] if row.get('what') else ''} | RSA-{row['bits']} | "
                     f"{len(row['steps'])} | {_steps(row['steps'])} |")
    if d.get("read"):
        lines.append(f"| another program reads a verified token (`examples/oidc_gate`) | | part of its own | {d['read']:,} |")
    worst = max(max(row["steps"]) for row in d["verify"])
    lines += ["", f"The limit is {chain['limit']:,} compute units per transaction; the costliest step here leaves "
                  f"{chain['limit'] - worst:,}. Each figure is for a token account whose address the program finds at "
                  f"its first try, and is the lowest of {d['runs']} runs of the tests. Every further try costs "
                  f"{chain['per_try']:,} more in each step: about half of all tokens need none, a quarter need one. "
                  f"Measured on {d['measured']} with {d['build']}."]
    keys = d.get("keys")
    if keys:
        lines += ["", f"The key instructions are small next to a verification: Refresh {keys['refresh']:,}, Approve "
                      f"{keys['approve']:,}, Revoke {keys['revoke']:,}."]
    return "\n".join(lines)


def pay_second(chain: dict) -> str:
    """The second deployment's escrow: Pay over many payments (its cost moves with the addresses it derives), and the
    highest seen of every other instruction."""
    p, d = chain["second"]["pay"], chain["second"]
    lines = ["| instruction | lowest | median | highest |", "|---|---|---|---|"]
    lines += [f"| {c['what']} | {c['min']:,} | {c['median']:,} | {c['max']:,} |" for c in p["cases"]]
    to_wallet = [c for c in p["cases"] if c.get("pays")]
    lines += ["", f"Compute units of knos-pay, the token program's share included, over {p['payments']:,} payments of "
                  f"each kind: the test file run {p['runs']} times, each run on a fresh chain with {p['payments'] // p['runs']} "
                  f"payments of each kind ({d['measured']}). A payment to a wallet took {min(c['min'] for c in to_wallet):,} to "
                  f"{max(c['max'] for c in to_wallet):,}. The spread is not noise: Pay derives the addresses it pays "
                  f"through (the payee's binding and record, the funder's marker, the vault and its authority), and "
                  f"each costs {chain['per_try']:,} for every try after the first.", "",
              f"The other instructions, highest seen in those {p['runs']} runs: "
              + "; ".join(f"{name} {cu:,}" for name, cu in d["other"]) + "."]
    return "\n".join(lines)


def pay_first(chain: dict) -> str:
    p = chain["first"]["pay"]
    return "\n".join(["| instruction | lowest | highest |", "|---|---|---|",
                      f"| Pay (check the token's claims against the job, credit the author, take the fee, close the job) | "
                      f"{p['pay'][0]:,} | {p['pay'][1]:,} |",
                      f"| Claim | {p['claim'][0]:,} | {p['claim'][1]:,} |", "",
                      f"Compute units, over {p['runs']} runs of one payment and one claim each ({chain['first']['measured']})."])


def _money(units: float) -> str:
    """An amount of the walk's test tokens, as exact as the test printed it (a token has 6 decimals)."""
    return f"{units:,.6f}".rstrip("0").rstrip(".")


def walk_second(walks: dict) -> str:
    """The second escrow's last random walks: what the test printed for each seed (docs/bench.json, chain.second.walks)."""
    runs = walks["runs"]
    steps = sum(r["steps"] for r in runs)
    total = {k: sum(r[k] for r in runs) for k in ("funded", "paid", "fees", "refunded")}
    seeds = ", ".join(str(r["seed"]) for r in runs[:-1]) + f" and {runs[-1]['seed']}" if len(runs) > 1 else str(runs[0]["seed"])
    return (f"Last runs ({walks['measured']}): {len(runs)} walks of {runs[0]['steps']:,} steps, seeds {seeds}, "
            f"{steps:,} steps in all: 0 violations. Funded {_money(total['funded'])}, paid {_money(total['paid'])}, fees "
            f"{_money(total['fees'])}, refunded {_money(total['refunded'])}: every token that entered left by one of the three.")


def walk_first(walk: dict) -> str:
    """The first escrow's last random walk, as the test printed it (docs/bench.json, chain.first.walk)."""
    return (f"Last {walk['steps']:,}-step run: 0 violations. Seed {walk['seed']}, {walk['measured']}: funded "
            f"{walk['funded']}, claimed {walk['claimed']}, fees {walk['fees']}, refunded {walk['refunded']}; the rest was "
            f"still in the vault, in open jobs and in money not yet claimed, when the walk ended.")


# ---- what was measured on devnet (docs/bench.json, "devnet") -----------------------------------------------------------

def _dig(obj, path: str):
    for part in path.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return None
        obj = obj[part]
    return obj


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _said(value) -> str:
    """A measured number as the docs print it, a time as it was given; anything else (nothing measured yet) as
    `UNMEASURED`."""
    if isinstance(value, str) and value:
        return value
    if not _number(value):
        return UNMEASURED
    return f"{value:,}" if isinstance(value, int) else f"{value:,.1f}"


def devnet(d: dict) -> str:
    """The second deployment on devnet, from the numbers `--stats` took from stats.json. A row with no number yet
    says so: nothing here is estimated."""
    stats = d.get("stats") or {}
    read = stats.get("updated")
    lines = ["| the second deployment on devnet | measured |", "|---|---|"]
    lines += [f"| {what} | {_said(_dig(stats, path))} |" for what, path in DEVNET]
    lines += ["", (f"Read from the site's `stats.json` of {read} (`python scripts/bench_docs.py --stats stats.json`)." if read else
                   f"No row has a number yet: {d['second']} The release fills the table from the site's `stats.json` "
                   "(`python scripts/bench_docs.py --stats stats.json`).")]
    return "\n".join(lines)


def devnet_first(f: dict) -> str:
    """The first deployment's record on devnet, as read from the chain (docs/bench.json, devnet.first)."""
    return (f"Read from the escrow's own logs on devnet on {f['read']}: {f['transactions']} transactions in all, the last "
            f"at {f['last']}. {f['funded']:,} bounties funded, {f['paid']:,} paid, {f['vetoed']:,} vetoed, {f['claimed']:,} "
            f"claims, {f['refunded']:,} refunded, {f['open']:,} still open. Every one of the {f['paid']:,} payments was Knos's "
            f"own account paying itself to prove the path; {f['outside_paid']:,} went to anyone else. The median from the "
            f"funding transaction to the paying one was {f['median_seconds_fund_to_paid']:,} seconds. "
            f"{f['open_for_outside']:,} of the open bounties are the ones another account's pull requests answer "
            f"({f['outside_prs']}); they had not been merged when this was read.")


def apply(text: str, gen: dict[str, str]) -> str:
    def repl(m):
        name = m.group(1)
        return f"<!-- bench:{name} -->\n{gen[name]}\n<!-- /bench:{name} -->" if name in gen else m.group(0)
    return re.sub(r"<!-- bench:([\w-]+) -->.*?<!-- /bench:\1 -->", repl, text, flags=re.S)


def take(index_path: str, root: Path = ROOT) -> None:
    """docs/bench.json's numbers from a published index.json: counted again from the records it lists (its root must
    match them), without the list itself. The agents keep the names docs/bench.json already gives them."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import agent_pr_index
    index = agent_pr_index.restate(agent_pr_index.check(index_path))
    bench = root / "docs" / "bench.json"
    src = json.loads(bench.read_text(encoding="utf-8"))
    labels = [label for label, _ in src["market"]["index"]["agents"]]
    assert len(labels) == len(index["agents"]), "docs/bench.json names another set of agents than the index"
    src["market"]["index"] = {**{k: index[k] for k in ("date", "window", "n_prs", "excluded_self_repo", "overall")},
                              "agents": [[label, counts] for label, counts in zip(labels, index["agents"].values())],
                              "root": index["root"]}
    bench.write_text(json.dumps(src, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


# ---- the slots of docs/submission ---------------------------------------------------------------------------------------

def _keep(into: dict, path: str, value) -> None:
    parts = path.split(".")
    for part in parts[:-1]:
        into = into.setdefault(part, {})
    into[parts[-1]] = value


def slot_files(root: Path = ROOT) -> list[str]:
    """Every file that may carry a slot and exists: docs/submission/*.md, then SLOTTED."""
    return [f"{SUBMISSION}/{doc.name}" for doc in sorted((root / SUBMISSION).glob("*.md"))] + [d for d in SLOTTED if (root / d).is_file()]


def slots(root: Path = ROOT) -> list[tuple[str, str]]:
    """(file, slot name) for every slot still open, in the order they are read."""
    return [(doc, name) for doc in slot_files(root) for name in SLOT.findall((root / doc).read_text(encoding="utf-8"))]


def _prose(root: Path, doc: str) -> str:
    """A document as its sentences: generated blocks and code left out (a slot quoted as code names the syntax), the
    changelog's newest release only (older ones are history), a page's tags removed, and one space between words."""
    text = (root / doc).read_text(encoding="utf-8")
    if doc == "CHANGELOG.md":
        text = "## ".join(text.split("\n## ")[:2])
    for pat in (r"<!-- bench:(\w[\w-]*) -->.*?<!-- /bench:\1 -->", r"```.*?```", r"`[^`\n]*`", r"<script.*?</script>"):
        text = re.sub(pat, " ", text, flags=re.S)
    if doc.endswith(".html"):
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return " ".join(text.replace("**", "").split())


def public_text(root: Path = ROOT) -> list[str]:
    """Every public document and the site's text: where one fact must have one value."""
    docs = ["README.md", "CHANGELOG.md", *sorted(f"docs/{p.name}" for p in (root / "docs").glob("*.md")),
            *sorted(f"{SUBMISSION}/{p.name}" for p in (root / SUBMISSION).glob("*.md")), "web/index.html"]
    return [d for d in docs if (root / d).is_file()]


def said(root: Path = ROOT) -> dict[str, dict[str, list[str]]]:
    """{slot name: {value as written: [files that state it]}} over FRAMES, in every public document and the site."""
    out: dict[str, dict[str, list[str]]] = {}
    for doc in public_text(root):
        text = _prose(root, doc)
        for name, frames in FRAMES.items():
            for frame in frames:
                for m in re.finditer(frame, text):
                    files = out.setdefault(name, {}).setdefault(m.group(1), [])
                    if doc not in files:
                        files.append(doc)
    return out


def _kept(src: dict, name: str):
    """The value docs/bench.json keeps for a slot, or None when nothing was measured."""
    path = SLOTS[name][1]
    return _dig(src.get("devnet", {}).get("stats") or {}, path) if path else _dig(src, f"release.{name}.value")


def disagreements(root: Path = ROOT) -> list[str]:
    """What breaks "one fact, one value", one line each."""
    src = json.loads((root / "docs" / "bench.json").read_text(encoding="utf-8"))
    out = []
    for name, values in sorted(said(root).items()):
        where = "; ".join(f"{value} in {', '.join(files)}" for value, files in values.items())
        if len(values) > 1:
            out.append(f"{name} has {len(values)} values: {where}")
            continue
        value = next(iter(values))
        if value.startswith("[["):
            if value != f"[[stat: {name}]]":
                out.append(f"{name} is stated with another fact's slot: {where}")
        elif _said(_kept(src, name)) != value:
            out.append(f"{name} is {_said(_kept(src, name))} in docs/bench.json and {where}")
    return out


def fill(stats_path: str | None = None, given: dict | None = None, root: Path = ROOT) -> list[str]:
    """What the release does with its measurements. `stats_path`: the site's stats.json; the numbers the `devnet` block
    uses are kept in docs/bench.json, and every slot whose number it has is filled. `given`: {slot name: (number, where
    it was measured)} for slots stats.json cannot fill. Each filled slot gets a fact in docs/facts.json. Returns the
    names of the slots that are still open."""
    bench, facts_file = root / "docs" / "bench.json", root / "docs" / "facts.json"
    src, facts = json.loads(bench.read_text(encoding="utf-8")), json.loads(facts_file.read_text(encoding="utf-8"))
    stats = json.loads(Path(stats_path).read_text(encoding="utf-8")) if stats_path else None
    if stats is not None:
        kept: dict = {"updated": stats.get("updated")}
        for _what, path in DEVNET:
            _keep(kept, path, _dig(stats, path))
        src.setdefault("devnet", {})["stats"] = kept
    given = dict(given or {})
    if "upgrade_executable" in given:
        raise SystemExit("--set upgrade_executable: it is filled with upgrade_proposed, 48 hours later")
    if "upgrade_proposed" in given:
        when, source = given["upgrade_proposed"]
        try:
            later = (datetime.strptime(str(when), TIME) + timedelta(hours=DELAY_HOURS)).strftime(TIME)
        except ValueError:
            raise SystemExit('--set upgrade_proposed: a time like "2026-10-05 14:00 UTC"') from None
        given["upgrade_executable"] = (later, f"{DELAY_HOURS} hours after upgrade_proposed ({source})")
    for name, (value, source) in given.items():
        good = isinstance(value, str) if name in WHEN else _number(value)
        if name not in SLOTS or SLOTS[name][1] is not None or not good:
            raise SystemExit(f"--set {name}: " + ("not a slot this script knows" if name not in SLOTS else
                                                  "stats.json fills this one (--stats)" if SLOTS[name][1] else
                                                  "not a time" if name in WHEN else "not a number"))
        src.setdefault("release", {})[name] = {"value": value, "source": source}

    where_said: dict[str, set[str]] = {}       # a fact's path -> the documents its slot was filled in
    here = [""]

    def number(m: re.Match) -> str:
        name = m.group(1)
        what, path = SLOTS.get(name, ("", None))
        if path is not None and stats is not None and _number(_dig(stats, path)):
            value, where, why = _dig(stats, path), f"devnet.stats.{path}", f"{what} (the site's stats.json of {stats.get('updated')})"
            _keep(src["devnet"]["stats"], path, value)
        elif path is None and name in given:
            value, where, why = given[name][0], f"release.{name}.value", f"{what}. Measured: {given[name][1]}"
        else:
            return m.group(0)
        fact = {"say": [] if name in WHEN else [_said(value)], "what": why, "json": "docs/bench.json", "path": where, "equals": value}
        if name in WHEN:
            fact["text"] = value                       # a time is held to its text, not to a number (claims_check.py)
        facts["facts"] = [f for f in facts["facts"] if f.get("path") != where] + [fact]
        where_said.setdefault(where, set()).add(here[0])
        return _said(value)

    for rel in slot_files(root):
        here[0] = rel
        doc = root / rel
        text = doc.read_text(encoding="utf-8")
        new = SLOT.sub(number, text)
        if new != text:
            doc.write_text(new, encoding="utf-8")
    # A number said only in documents that are not pitch-facing (docs/ASSURANCE.md, ...) is a "doc" fact: claims_check.py
    # then holds those documents to it, instead of looking for it in the pitch-facing text, which does not say it.
    for f in facts["facts"]:
        docs = where_said.get(f.get("path"), set())
        if docs and f["say"] and not docs & set(PITCH):
            f["doc"] = sorted(docs) if len(docs) > 1 else next(iter(docs))
    bench.write_text(json.dumps(src, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    facts_file.write_text(json.dumps(facts, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return sorted({name for _doc, name in slots(root)})


def main(check: bool = False, root: Path = ROOT) -> int:
    gen = blocks(json.loads((root / "docs" / "bench.json").read_text(encoding="utf-8")),
                 json.loads((root / "docs" / "backtest.json").read_text(encoding="utf-8")))
    drift = []
    for d in DOCS:
        p = root / d
        old = p.read_text(encoding="utf-8")
        new = apply(old, gen)
        if new != old:
            drift.append(d)
            if not check:
                p.write_text(new, encoding="utf-8")
    unknown = sorted({f"{doc}: [[stat: {name}]]" for doc, name in slots(root) if name not in SLOTS})
    if unknown:
        print("slots this script does not know (add them to SLOTS in scripts/bench_docs.py): " + "; ".join(unknown))
    if check and drift:
        print("benchmark numbers drifted from docs/bench.json in: " + ", ".join(drift))
    two = disagreements(root)
    for line in two:
        print("one fact, one value: " + line)
    return 1 if unknown or two or (check and drift) else 0


def _arg(flag: str) -> str | None:
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else None


if __name__ == "__main__":
    if "--from" in sys.argv:
        take(_arg("--from"))
    given = None
    if "--set" in sys.argv:
        name, _, value = (_arg("--set") or "").partition("=")
        source = _arg("--source")
        if not source or not (name in WHEN or re.fullmatch(r"\d+(?:\.\d+)?", value)):
            raise SystemExit('usage: python scripts/bench_docs.py --set NAME=NUMBER --source "where it was measured"')
        given = {name: (value if name in WHEN else float(value) if "." in value else int(value), source)}
    if "--stats" in sys.argv or given:
        fill(_arg("--stats"), given)
    if "--slots" in sys.argv:
        left = slots()
        for doc, name in left:
            print(f"{doc}: [[stat: {name}]]  {SLOTS.get(name, ('NOT A KNOWN SLOT',))[0]}")
        print(f"{len(left)} slot{'' if len(left) == 1 else 's'} with no number yet")
        raise SystemExit(1 if left else 0)
    raise SystemExit(main("--check" in sys.argv))
