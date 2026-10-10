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
    python scripts/bench_docs.py --site _site        hold the documents to a built site's stats.json and latency.json:
                                                     exit 1 when they disagree on any number both state
    python scripts/bench_docs.py --set NAME=NUMBER --source "where it was measured"
                                                     fill one slot that stats.json cannot (see SLOTS)
    python scripts/bench_docs.py --stages stages.json --source "where it was measured"
                                                     fill the stage and attempt slots (STAGE_SLOTS) from
                                                     `scripts/latency_stages.py --json` on the live relay log
    python scripts/bench_docs.py --repo             first fill the slots this repository answers itself (REPO_SLOTS: the
                                                     files of reproductions/, and the constants a person keeps under
                                                     "by_hand" in docs/facts.json)
    python scripts/bench_docs.py --slots            list the slots that have no number yet; exit 1 if there is one

A block is `<!-- bench:NAME -->` ... `<!-- /bench:NAME -->` in README.md or docs/BENCH.md:

    headline      the index's two named figures, and the merged pull requests
    today         README: how many capabilities are at each stage, and which ones reached the public program ids (all
                  read from docs/capabilities.json, so the table cannot disagree with it), and the outside-use numbers of
                  NUMBERS.md, zeros included, from the same sources
    outside-use   docs/submission/NUMBERS.md: nine numbers about use by anyone who is not Knos, each from where it is kept
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

No slot is a time. When an upgrade was proposed and from when it can execute exist only after the push that the
proposal's build record needs, so no committed document states them: the documents point at the site's upgrades.json
(web/upgrades.json is the committed copy) and at `knos status`, and scripts/doc_claims.py refuses a document that names
such a time. The release's one commit is therefore complete before the push.

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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "docs/BENCH.md", "docs/submission/NUMBERS.md"]
# The pitch-facing text (scripts/claims_check.py reads the same list): every number in it needs a fact.
PITCH = ["README.md", "web/index.html", "docs/submission/SUBMISSION.md", "docs/submission/pitch_script.md",
         "docs/submission/demo_script.md", "docs/submission/weekly_update.md", "docs/submission/pitch_script_120.md"]
SUBMISSION = "docs/submission"       # every .md under it may carry [[stat: name]] slots
# The other files that may carry slots. Everything a judge opens states a release-measured fact through one, so that the
# release fills them all in one run and no document is left with an older number.
SLOTTED = ["README.md", "CHANGELOG.md", "docs/DISCLOSURE.md", "docs/WHY.md", "docs/COMPARE.md", "docs/MARKET.md",
           "docs/SECURITY.md", "docs/ASSURANCE.md", "docs/BENCH.md", "docs/RELAY.md"]
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
    ("repositories that are not Knos's in which an outside funder funded a task (scripts/outsiders.py)", "outsiders.repositories"),
    ("accounts and wallets that are not Knos's, paid by a task somebody else funded (scripts/outsiders.py)", "outsiders.payees"),
    ("payments timed from the merge, over the public relay's log (n)", "latency.merge_to_paid.count"),
    ("seconds from the merge to the payment, median (p50)", "latency.merge_to_paid.median"),
    ("seconds from the merge to the payment, 95th percentile (p95)", "latency.merge_to_paid.p95"),
    ("the day of the oldest of those payments (UTC)", "latency.merge_to_paid.window.from"),
    ("the day of the newest", "latency.merge_to_paid.window.to"),
    ("of those payments, made by the first deployment's escrow", "latency.merge_to_paid.deployment.first"),
    ("of those payments, made by the second deployment's escrow", "latency.merge_to_paid.deployment.second"),
    ("seconds from the funding comment to the funded task, median", "latency.comment_to_funded.median"),
]
# Kept beside the rows, and printed under the table: what the merge-to-paid number is, in the words of the one function
# that measures it (scripts/network_stats.py, measure()).
DEFINITION = "latency.merge_to_paid.definition"
# The numbers stats.json and latency.json both state, as (path in stats.json's latency.<wait>, path in latency.json's
# <wait>): one build writes both, from one function, so they are equal or the build is broken.
SITE_PAIRS = [(k, f"measure.{k}") for k in ("n", "p50", "p95", "slowest", "count", "median", "p90")] + [("n", "all_time.n"), ("p50", "all_time.p50"), ("p95", "all_time.p95")]
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
    "days_of_shipping": ("days, from 1 Sep 2026 to the release, on which drexthealpha made a commit in the public "
                         "repository (the automatic commits of a workflow are left out): "
                         "`git log --author=drexthealpha --format=%ad --date=short | sort -u | wc -l`", None),
}
# The stages of a payment and the attempts, as scripts/latency_stages.py --json reports them on the live relay log: each
# a slot with no path in stats.json, filled by `--stages FILE --source "..."` (or one at a time with --set).
STAGE_WORDS = {
    "runner_queue": "the merge to the start of the workflow run (runner queue)",
    "workflow": "the start of the workflow run to the token's comment (workflow)",
    "relay_wait": "the token's comment to the relay picking it up (relay wait)",
    "first_send": "the relay's pickup to the block of the token's first transaction (first send)",
    "confirm": "that block to the block of the transaction that paid (confirm)",
    "queued": "the run waiting for a runner, as GitHub records it (inside the runner queue)",
    "chain": "the relay's pickup to its last confirmation (first send and confirm together)",
}
STAGE_STATS = {"payments": ("n", "payments in which this stage is measured"), "median": ("p50", "the median seconds"),
               "ninety_fifth": ("p95", "the 95th percentile, by nearest rank, in seconds"), "slowest": ("max", "the longest, in seconds")}
ATTEMPT_WORDS = {"asked": "pull requests whose payment the public relay log has a line for",
                 "completed": "of those, the ones with a line that says ok",
                 "lines": "log lines with a token's id, one per token a relay answered for",
                 "failed": "of those lines, the ones that say fail",
                 "retried": "ok lines that took more than one try",
                 "after_failure": "payments completed only after a failed line",
                 "never": "payments asked for that no line says ok"}
STAGE_SLOTS = {f"stage_{stage}_{stat}": (f"{what}: {words}, over the public relay's log (scripts/latency_stages.py)", ("stages", stage, key))
               for stage, words in STAGE_WORDS.items() for stat, (key, what) in STAGE_STATS.items()}
STAGE_SLOTS |= {f"stage_whole_{stat}": (f"{what}: the merge to the payment, the whole wait, as scripts/latency_stages.py "
                                        "timed it over the public relay's log", ("whole", key)) for stat, (key, what) in STAGE_STATS.items()}
STAGE_SLOTS |= {f"pay_attempts_{name}": (f"{words} (scripts/latency_stages.py, network_stats.attempts)", ("attempts", name))
                for name, words in ATTEMPT_WORDS.items()}
SLOTS |= {name: (what, None) for name, (what, _where) in STAGE_SLOTS.items()}
# Use by anyone who is not Knos (docs/submission/NUMBERS.md). Two are counted by the site's build (stats.json,
# `outsiders`: scripts/outsiders.py). The others are read from this repository: the report files of reproductions/, and
# the counts only a person can supply, which are constants under BY_HAND in docs/facts.json that a person changes when
# the other party agrees to be counted. The table of NUMBERS.md is written from them (the block `outside-use`), and
# `--repo` (like every fill) fills a slot that names one in any other document; nothing else may set them.
SLOTS |= {
    "outside_repositories": ("repositories that are not Knos's in which an outside funder funded a task", "outsiders.repositories"),
    "outside_payees": ("accounts and wallets that are not Knos's and were paid by a task somebody else funded", "outsiders.payees"),
}
BY_HAND = "by_hand"
REPO_SLOTS = {
    "reproductions_signed": ("report files in reproductions/ from a run GitHub signed in someone else's repository", "reproductions/*.json"),
    "buyer_interviews_held": ("interviews held with someone who approves a supplier's invoice", f"docs/facts.json, {BY_HAND}"),
    "letters_of_intent": ("letters of intent signed by another party", f"docs/facts.json, {BY_HAND}"),
    "outside_programs_reading_the_verifier": ("programs that are not Knos's and are known to read a token knos-oidc verified",
                                              f"docs/facts.json, {BY_HAND}"),
    "shadow_counts_published": ("neutral counts published beside a supplier's own invoice count", f"docs/facts.json, {BY_HAND}"),
}
SLOTS |= {name: (what, None) for name, (what, _where) in REPO_SLOTS.items()}


def repo_numbers(root: Path = ROOT) -> dict:
    """{slot name: (number, where it was read)} for every slot of REPO_SLOTS this tree can answer."""
    out: dict = {}
    folder, facts = root / "reproductions", root / "docs" / "facts.json"
    if folder.is_dir():
        out["reproductions_signed"] = (len(list(folder.glob("*.json"))), "the count of reproductions/*.json in this repository")
    by_hand = json.loads(facts.read_text(encoding="utf-8")).get(BY_HAND, {}) if facts.is_file() else {}
    for name in REPO_SLOTS:
        if _number(by_hand.get(name)):
            out[name] = (by_hand[name], f"docs/facts.json, {BY_HAND}.{name}: a constant a person changes")
    return out


def stage_numbers(report: dict, source: str) -> dict:
    """{slot name: (number, source)} for every stage slot `report` (latency_stages.py --json) has a number for."""
    out = {}
    for name, (_what, where) in STAGE_SLOTS.items():
        value = _dig(report, ".".join(where))
        if _number(value):
            out[name] = (value, source)
    return out
_V = r"(\[\[stat: [a-z_]+\]\]|\d[\d,]*(?:\.\d+)?)"
# The sentences in which a slot's fact is stated, each with one group: the value as written, a number or a slot.
FRAMES = {
    "seconds_from_merge_to_paid": [rf"merge to (?:paid|payment|the payment)\b[^.|]{{0,60}}?{_V} seconds",
                                   rf"{_V} seconds from (?:the )?merge to (?:paid|payment|the payment)"],
    "payments_timed": [rf"seconds\b[^.|]{{0,40}}? over {_V} payments"],
    "tasks_paid_on_the_second_deployment": [rf"{_V} tasks (?:had been |were |are )?paid on the second deployment"],
    "payments_between_unrelated_accounts": [rf"{_V} payments have gone to another GitHub account",
                                            rf"{_V} (?:payments )?to an outside contributor"],
    "tests_passing": [rf"{_V} tests pass"],
    "claim_parser_executions": [rf"{_V} inputs against the claim parser"],
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


def outside_rows(src: dict, repo: dict) -> list[tuple[str, object, str]]:
    """(what, value, where it is read) for the nine numbers about use by anyone who is not Knos. `repo` is
    repo_numbers(): what this repository answers itself. A value nothing has measured is None."""
    stats, release = (src.get("devnet") or {}).get("stats") or {}, src.get("release") or {}
    between = release.get("payments_between_unrelated_accounts") or {}
    repositories, payees = _dig(stats, "outsiders.repositories"), _dig(stats, "outsiders.payees")
    where_r = where_p = "`docs/bench.json`, `devnet.stats.outsiders` (scripts/outsiders.py, in the site's build)"
    if repositories is None and _dig(stats, "outside.funded") == 0:        # no outside task was funded, so in no outside repository
        repositories, where_r = 0, "`docs/bench.json`, `devnet.stats.outside.funded` is 0: no outside task, so no outside repository"
    if payees is None and between.get("source"):                           # the accounts the measured payments name
        payees = len(set(re.findall(r"to another GitHub account \((\d+)\)", between["source"])))
        where_p = "`docs/bench.json`, `release.payments_between_unrelated_accounts.source`: the accounts it names, on tasks Knos funded itself"
    by_hand = "`docs/facts.json`, `by_hand`: a person changes it; [DISCLOSURE.md](../DISCLOSURE.md) says the same"
    rows = [
        ("Outside funders: accounts other than Knos's that funded a task with their own tokens", _dig(stats, "outside.funders"),
         "`docs/bench.json`, `devnet.stats.outside.funders`"),
        ("Outside repositories: repositories not owned by Knos in which a task was funded", repositories, where_r),
        ("Outside payees: GitHub accounts other than the funder's that were paid", payees, where_p),
        ("Payments between unrelated accounts: payments whose payee is another GitHub account than the funder", between.get("value"),
         "`docs/bench.json`, `release.payments_between_unrelated_accounts`, read from the escrows' logs"),
        ("Buyer interviews held", (repo.get("buyer_interviews_held") or [None])[0], by_hand + "; [INTERVIEWS.md](INTERVIEWS.md) is the kit, unused"),
        ("Letters of intent", (repo.get("letters_of_intent") or [None])[0], by_hand),
        ("Reproductions signed by GitHub: files in `reproductions/` from a run in someone else's repository",
         (repo.get("reproductions_signed") or [None])[0], "the report files of [`reproductions/`](../../reproductions/README.md)"),
        ("Outside programs reading the verifier", (repo.get("outside_programs_reading_the_verifier") or [None])[0],
         by_hand + "; the examples in [COMPOSE.md](../COMPOSE.md) are Knos's own"),
        ("Shadow counts published: a neutral count printed beside a supplier's own invoice count, with every mismatch",
         (repo.get("shadow_counts_published") or [None])[0], by_hand + "; [PILOT.md](../PILOT.md), \"How it starts: shadow mode\""),
    ]
    return rows


def outside_use(src: dict, repo: dict) -> str:
    """docs/submission/NUMBERS.md's table: nine numbers about use by anyone who is not Knos, each from where it is kept.
    `repo` is repo_numbers(): what this repository answers itself. A number nothing has measured is said so, never 0."""
    lines = ["| # | number | value | where it is read |", "|---|---|---|---|"]
    lines += [f"| {i} | {what} | {_said(value) if _number(value) else 'not measured'} | {where} |"
              for i, (what, value, where) in enumerate(outside_rows(src, repo), 1)]
    return "\n".join(lines)


# README.md's one table, "What is real today": the stage rows (stage_rows), the nine
# numbers of NUMBERS.md and the rows no number decides (TODAY_LAST), so the front page prints every zero that page prints and can print no other value.
NUMBERS_DOC = "[docs/submission/NUMBERS.md](docs/submission/NUMBERS.md)"
CAPS_DOC = "[docs/CAPABILITIES.md](docs/CAPABILITIES.md)"
# The plain name of each capability the stage rows print; a capability with none is printed by its id. The stage of each
# is read from docs/capabilities.json every time, so the front page cannot say a capability is lower or higher than that.
PLAIN = {
    "verify_github": "GitHub token verification", "verify_gitlab": "GitLab token verification", "key_guardian": "the key guardian",
    "fund_by_comment": "funding by one comment", "fund_from_wallet": "funding from a wallet", "pay_on_merge": "pay on merge",
    "hold_and_bind": "holding pay for a payee with no wallet", "refund": "refund at the deadline", "pause": "pause",
    "work_orders": "work orders", "order_pay": "an order paying up to four payees", "tests_mode": "orders judged by hidden tests",
    "order_auto_accept": "auto-accepted orders", "top_up": "top-ups", "single_use_tokens": "single-use tokens",
    "meter_single": "one counted evaluation", "meter_batch": "a counted batch of evaluations", "meter_seller_claim": "the seller's own count",
    "passkey_payee_wallet": "a payee's passkey wallet", "passkey_funder": "a passkey funder", "passkey_fund_relay": "the passkey relay",
    "buyer_page": "the site's Buy page", "x402_knos_order": "an x402 order", "upgrade_gate": "the upgrade gate",
    "outcome_not_code": "an outcome that is not code", "holdback_release": "a holdback released after its warranty",
    "oidc_strict_json": "strict JSON in the verifier", "es256_tokens": "ES256 tokens in one transaction", "presentation_grace": "the presentation grace",
}
STAGE_ROWS = (   # (stage, the row's name, what the row adds after the names, the label docs/CAPABILITIES.md gives the stage)
    ("reproduced", "Reproduced by someone else", "", "reproduced by someone else"),
    ("exercised", "Exercised at the public devnet program ids", "", "exercised on devnet"),
    ("deployed", "Deployed at the public devnet program ids, no transaction recorded", "", "deployed on devnet"),
    ("tested", "Tested here only", ", each with the test its row names", "tested locally"),
    ("implemented", "Written, not tested", "", "implemented"),
)


def capabilities(root: Path = ROOT) -> list[dict]:
    """docs/capabilities.json's rows; a tree that has no manifest of its own (a test's copy) reads this repository's."""
    path = root / "docs" / "capabilities.json"
    if not path.is_file():
        path = ROOT / "docs" / "capabilities.json"
    return json.loads(path.read_text(encoding="utf-8")).get("capabilities", []) if path.is_file() else []


def stage_rows(caps: list[dict]) -> list[tuple[str, str, str]]:
    """The rows of README's table that say how far each capability has got, one row a stage, every one from
    docs/capabilities.json: the count of the stage, then the names of what reached the public ids."""
    rows = []
    for stage, name, tail, label in STAGE_ROWS:
        ids = [c["id"] for c in caps if c.get("stage") == stage]
        said = f"{len(ids)} of {len(caps)}"
        if ids and stage in ("reproduced", "exercised", "deployed"):
            said += ": " + ", ".join(PLAIN.get(i, f"`{i}`") for i in ids)
        rows.append((name, said + (tail if ids else ""), f"{CAPS_DOC}, the rows \"{label}\""))
    return rows


TODAY_NOTES = {3: ", on tasks Knos funded itself", 4: ", on tasks Knos funded itself"}     # by row of NUMBERS.md
TODAY_LAST = [
    ("Paying customers", "0", "[docs/DISCLOSURE.md](docs/DISCLOSURE.md)"),
    ("Revenue", "0; test USDC is not money", "[docs/MARKET.md](docs/MARKET.md)"),
    ("Outside security review", "none", "[docs/ASSURANCE.md](docs/ASSURANCE.md)"),
    ("Key holders", "one person holds every key; an upgrade waits 48 hours in public", "[docs/GOVERNANCE.md](docs/GOVERNANCE.md)"),
    ("Network and money", "Solana devnet, test USDC; mainnet is not touched", "[docs/SECURITY.md](docs/SECURITY.md)"),
]


def release_row(root: Path = ROOT) -> tuple[str, str, str]:
    """The table's first row: which release this copy is, from pyproject.toml and the top entry of CHANGELOG.md, so a
    reader served an older copy (a cache, a registry, a fork) can tell. The two must name the same release. A tree
    that lacks either file (a test's copy of a few documents) reads it from this repository."""
    read = lambda rel: ((root / rel) if (root / rel).is_file() else ROOT / rel).read_text(encoding="utf-8")  # noqa: E731
    py = re.search(r'(?m)^version = "([\d.]+)"', read("pyproject.toml"))
    top = re.search(r"(?m)^## (\d+\.\d+\.\d+) \(([^)]*)\)", read("CHANGELOG.md"))
    if not py or not top or py.group(1) != top.group(1):
        raise SystemExit(f"pyproject.toml says {py and py.group(1)} and CHANGELOG.md's top entry says {top and top.group(1)}: "
                         "write the entry first")
    return ("This copy", f"Release {top.group(1)}, {top.group(2)}. A copy naming an older release, or another product, is out of date",
            "[CHANGELOG.md](CHANGELOG.md); the newest: [PyPI](https://pypi.org/project/knos/)")


def today(src: dict, repo: dict, caps: list[dict] | None = None, root: Path = ROOT) -> str:
    """README.md's table (the block `today`): which release this is (release_row), how far each capability has got
    (stage_rows, from docs/capabilities.json), and what nobody outside has used, the last from the same sources as
    outside_use()."""
    rows = [release_row(root), *stage_rows(capabilities() if caps is None else caps),
            *((what.split(":")[0], (_said(value) if _number(value) else "not measured") + TODAY_NOTES.get(i, ""), NUMBERS_DOC + f", row {i}")
              for i, (what, value, _where) in enumerate(outside_rows(src, repo), 1)),
            *TODAY_LAST]
    return "\n".join(["| What | Today | Read from |", "|---|---|---|", *(f"| {a} | {b} | {c} |" for a, b, c in rows)])


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
             "| agent | repositories | first claiming PR per repository: any check failed | 95% interval | every claiming PR | every claiming PR: any check failed |",
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
             "| agent | repositories | first claiming PR per repository: any check failed | first claiming PR per repository: a test or build check failed | 95% interval | every claiming PR | every claiming PR: a test or build check failed |",
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
    if _dig(stats, DEFINITION):
        lines += ["", f"Merge to paid is defined as: {_dig(stats, DEFINITION)}. One function measures it (`measure` in "
                      "`scripts/network_stats.py`); this table, `docs/facts.json`, the site's Numbers page (`stats.json`) and "
                      "`latency.json` all state that function's output."]
    if stats.get("note"):
        lines += ["", stats["note"]]
    lines += ["", (f"Read from the site's `stats.json` of {read} (`python scripts/bench_docs.py --stats stats.json`)." if read else
                   f"No row has a number yet: {d['second']} The release fills the table from the site's `stats.json` "
                   "(`python scripts/bench_docs.py --stats stats.json`).")]
    return "\n".join(lines)


def _first_ids() -> dict:
    """The first deployment's public program ids, as programs/program_ids.json records them."""
    return json.loads((ROOT / "programs" / "program_ids.json").read_text(encoding="utf-8"))


def devnet_first(f: dict) -> str:
    """The first deployment's record on devnet, as read from the chain (docs/bench.json, devnet.first)."""
    return (f"Read from the escrow's own logs on devnet on {f['read']}: {f['transactions']} transactions in all, the last "
            f"at {f['last']}. {f['funded']:,} bounties funded, {f['paid']:,} paid, {f['vetoed']:,} vetoed, {f['claimed']:,} "
            f"claims, {f['refunded']:,} refunded, {f['open']:,} still open. Every one of the {f['paid']:,} payments was Knos's "
            f"own account paying itself to prove the path; {f['outside_paid']:,} went to anyone else. The median from the "
            f"funding transaction to the paying one was {f['median_seconds_fund_to_paid']:,} seconds over those {f['paid']:,} payments "
            f"(the first deployment's public program ids, knos_pay `{_first_ids()['knos_pay']}` and knos_oidc `{_first_ids()['knos_oidc']}`, "
            f"programs/program_ids.json; read {f['read']}). "
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
        for name, stated in _stated(root, doc):
            files = out.setdefault(name, {}).setdefault(stated, [])
            if doc not in files:
                files.append(doc)
    return out


_STATED: dict[tuple[str, str], list[tuple[str, str]]] = {}     # (document, sha256 of its bytes) -> what it states: a pure function of its text


def _stated(root: Path, doc: str) -> list[tuple[str, str]]:
    """(slot name, value as written) for every frame of FRAMES a document states, in order. Kept by the document's
    bytes, so a tree read twice (scripts/doc_claims.py, and its tests, read it many times) is matched once."""
    import hashlib
    key = (doc, hashlib.sha256((root / doc).read_bytes()).hexdigest())
    if key not in _STATED:
        text = _prose(root, doc)
        _STATED[key] = [(name, m.group(1)) for name, frames in FRAMES.items() for frame in frames for m in re.finditer(frame, text)]
    return _STATED[key]


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
    for name, (value, where) in sorted(repo_numbers(root).items()):       # a number of the repository that moved since it was filled
        kept = _dig(src, f"release.{name}.value")
        if kept is not None and kept != value:
            out.append(f"{name} is {_said(kept)} in docs/bench.json and {_said(value)} in {where}: change the documents that say it, then run --repo")
    return out


def site_disagreements(stats: dict, latency: dict | None = None, root: Path = ROOT) -> list[str]:
    """Every number the documents share with the site's data, where the two differ, one line each. `stats` is the
    site's stats.json and `latency` its latency.json (both of one build). Three comparisons: docs/bench.json's
    `devnet.stats` (which docs/BENCH.md's table and docs/facts.json state) against stats.json, path by path, when
    bench.json was filled from that very stats.json (`updated` is the same); every fact of docs/facts.json that points
    into `devnet.stats` against bench.json; and stats.json against latency.json. The release runs it after `--stats`
    (`python scripts/bench_docs.py --site _site`), and the Pages build can."""
    src = json.loads((root / "docs" / "bench.json").read_text(encoding="utf-8"))
    kept, out = (src.get("devnet") or {}).get("stats") or {}, []
    if kept.get("updated") == stats.get("updated"):
        for what, path in DEVNET:
            if _dig(kept, path) != _dig(stats, path):
                out.append(f"{what}: {_said(_dig(kept, path))} in docs/bench.json, {_said(_dig(stats, path))} in the site's stats.json")
    else:
        out.append(f"docs/bench.json was filled from the stats.json of {kept.get('updated')}, the site's is of {stats.get('updated')}: run --stats on it first")
    for f in json.loads((root / "docs" / "facts.json").read_text(encoding="utf-8"))["facts"]:
        path = str(f.get("path", ""))
        if f.get("json") == "docs/bench.json" and path.startswith("devnet.stats.") and f.get("equals") != _dig(src, path):
            out.append(f"docs/facts.json says {f.get('equals')} for {path}, docs/bench.json {_dig(src, path)}")
    for wait in ("merge_to_paid", "comment_to_funded"):
        for a, b in SITE_PAIRS if latency is not None else []:
            if _dig(stats, f"latency.{wait}.{a}") != _dig(latency, f"{wait}.{b}"):
                out.append(f"{wait}: stats.json's {a} is {_dig(stats, f'latency.{wait}.{a}')}, latency.json's {b} is {_dig(latency, f'{wait}.{b}')}")
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
        for _what, path in [*DEVNET, ("", DEFINITION)]:
            _keep(kept, path, _dig(stats, path))
        src.setdefault("devnet", {})["stats"] = kept
    for name in given or {}:
        if name in REPO_SLOTS:
            raise SystemExit(f"--set {name}: this one is read from the repository ({REPO_SLOTS[name][1]}); change it there")
    given = {**repo_numbers(root), **(given or {})}
    for name, (value, source) in given.items():
        if name not in SLOTS or SLOTS[name][1] is not None or not _number(value):
            raise SystemExit(f"--set {name}: " + ("not a slot this script knows" if name not in SLOTS else
                                                  "stats.json fills this one (--stats)" if SLOTS[name][1] else "not a number"))
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
        fact = {"say": [_said(value)], "what": why, "json": "docs/bench.json", "path": where, "equals": value}
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
    src = json.loads((root / "docs" / "bench.json").read_text(encoding="utf-8"))
    gen = blocks(src, json.loads((root / "docs" / "backtest.json").read_text(encoding="utf-8")))
    gen["outside-use"] = outside_use(src, repo_numbers(root))
    gen["today"] = today(src, repo_numbers(root), capabilities(root), root)
    drift = []
    for d in DOCS:
        p = root / d
        if not p.is_file():
            continue
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
        if not source or not re.fullmatch(r"\d+(?:\.\d+)?", value):
            raise SystemExit('usage: python scripts/bench_docs.py --set NAME=NUMBER --source "where it was measured"')
        given = {name: (float(value) if "." in value else int(value), source)}
    if "--stages" in sys.argv:      # scripts/latency_stages.py --json on the live log: every stage slot it has a number for
        source = _arg("--source")
        if not source:
            raise SystemExit('usage: python scripts/bench_docs.py --stages stages.json --source "where and when it was measured"')
        given = {**(given or {}), **stage_numbers(json.loads(Path(_arg("--stages") or "").read_text(encoding="utf-8")), source)}
    if "--stats" in sys.argv or "--repo" in sys.argv or given:      # --repo: only the numbers this repository holds (REPO_SLOTS)
        fill(_arg("--stats"), given)
    if "--site" in sys.argv:      # a built site's folder: its stats.json and latency.json against the documents
        site = Path(_arg("--site"))
        lat = site / "latency.json"
        wrong = site_disagreements(json.loads((site / "stats.json").read_text(encoding="utf-8")), json.loads(lat.read_text(encoding="utf-8")) if lat.exists() else None)
        for line in wrong:
            print("the documents and the site: " + line)
        if wrong:
            raise SystemExit(1)
    if "--slots" in sys.argv:
        left = slots()
        for doc, name in left:
            print(f"{doc}: [[stat: {name}]]  {SLOTS.get(name, ('NOT A KNOWN SLOT',))[0]}")
        print(f"{len(left)} slot{'' if len(left) == 1 else 's'} with no number yet")
        raise SystemExit(1 if left else 0)
    raise SystemExit(main("--check" in sys.argv))
