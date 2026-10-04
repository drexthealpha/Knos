"""The public record of Knos as static files: JSON for aggregators and agent platforms, and a page for each one.

    python scripts/pages_data.py --out _site --events _events.json --index _site/index.json [--docs docs/OPERATIONS.md]
    python scripts/pages_data.py --out _site --empty        # the same files with nothing measured (a local build)

It counts from what scripts/network_stats.py counts from (the escrows' own log lines of both deployments, the relay
log, GitHub when it answers) and from the Agent PR Index's published index.json. Nothing here is self-reported, and a
number that could not be measured is null with a note, never a guess. Written under the output folder:

    bounties.json, bounties.rss      every open funded task, for aggregators and agent platforms: bounties (jobs) and
                                     open work orders, an order with its terms, what it holds back and for how long (its
                                     warranty), who it is reserved for and until when, and whether it is a standing offer
    u/<login>.json, .html            one account's record, as earner and as funder
    r/<owner>/<repo>.json, .html     the same, per repository
    badge/u/<login>.json, badge/r/<owner>/<repo>.json     shields.io endpoint files
    rank/earners, rank/funders, rank/agents (.json and .html)
    statements/<login>.json          every payment to an account and every payment it funded, one row each, for the site's statements
    latency.json                     merge to paid and comment to funded, last 30 days and all time
    operations.json                  the canary's runs, its incidents, the time to a first answer to outsiders
    records.json                     which accounts and repositories have a file, and how many could not be named
    docs/OPERATIONS.md (--docs)      operations.json in words; with no data it says so

Every file carries `source` (what it was counted from) and `generated` (when). Every file can be recomputed by running
this script on the same inputs.

A work order (knos_pay 2.1, the escrow's `knos3:` lines) is counted as one job for its funder and its repository. What it
paid is counted for each payee by that payee's own share (a split pays several, and a holdback released after its
warranty adds to its payee's), and a statement has one row per payment.

What a payment is counted as, per job (scripts/network_stats.py's kind_of, and the mint):

    own     Knos's own account or wallet is on either end (scripts/own_github_ids.json). Never counted for anyone.
    self    paid, and the funder is the payee. Never counted for anyone.
    test    the devnet faucet's test USDC, or any mint that is not Circle's USDC.
    real    Circle's USDC (devnet 4zMMC9sr..., mainnet EPjFWdd5...) from someone who is not the payee and not Knos.

A rank (earners, funders) is built from `real` jobs only, so test money, self-payment and Knos's own accounts cannot
raise it; what was left out is counted beside the table.

The chain's logs carry GitHub ids, not names. Names come from GitHub (`user/<id>`, `repositories/<id>`); an id GitHub
does not name gets no file, and `records.json` says how many.
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import math
import os
import re
import statistics
import sys
import time
import urllib.parse
from pathlib import Path
from xml.sax.saxutils import escape as xml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import agent_pr_index  # noqa: E402 - the standard library only

SITE = "https://drexthealpha.github.io/Knos"
HOME_REPO = "drexthealpha/Knos"
CANARY = "canary.yml"        # the workflow whose runs are the canary's (every 30 minutes)
USDC = frozenset({"4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU",     # Circle's, devnet
                  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"})    # Circle's, mainnet
KINDS = ("real", "test", "self", "own")
DAY = 86_400
_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_REPO = re.compile(r"[A-Za-z0-9._-]{1,100}")
_FAIL = re.compile(r"^knos-relay (\w+) (\S+?)#(\d+) (\S+) fail (.*)$")
_OK = re.compile(r"^knos-relay (\w+) (\S+?)#(\d+) ([0-9a-f]{16}) ok (.*)$")
_PARTS = ("queue", "workflow", "wait", "chain")      # the relay's optional per-stage seconds on an `ok` line
AGENT_NAMES = {"copilot": "GitHub Copilot coding agent", "devin": "Devin", "claude-bot": "Claude GitHub app",
               "claude-code": "Claude Code", "codex": "OpenAI Codex"}


def _ns():
    """scripts/network_stats.py, imported when something is counted (it needs solders; an empty build does not)."""
    import network_stats
    return network_stats


def own_ids() -> tuple[frozenset, frozenset]:
    data = json.loads((ROOT / "scripts" / "own_github_ids.json").read_text(encoding="utf-8"))
    return frozenset(data["ids"]), frozenset(data.get("wallets", []))


def _unix(stamp) -> int | None:
    """GitHub's timestamp (2026-10-02T12:00:00Z), or seconds already, as unix seconds."""
    if isinstance(stamp, (int, float)) or str(stamp).isdigit():
        return int(stamp)
    try:
        return int(datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def iso(ts) -> str | None:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None


def spread(seconds) -> dict:
    """{n, p50, p95, p99, slowest} in seconds, by nearest rank; null when there is nothing to measure."""
    took = sorted(int(s) for s in seconds if s is not None and s >= 0)
    if not took:
        return {"n": 0, "p50": None, "p95": None, "p99": None, "slowest": None}
    pick = lambda q: took[max(0, math.ceil(q * len(took)) - 1)]  # noqa: E731
    return {"n": len(took), "p50": int(statistics.median(took)), "p95": pick(0.95), "p99": pick(0.99), "slowest": took[-1]}


def rate(k: int, n: int) -> dict:
    """k of n as a share with its 95% Wilson interval (the Agent PR Index's); null share when n is 0."""
    return {"n": n, "k": k, "share": round(k / n, 4) if n else None, "ci95": agent_pr_index.wilson(k, n)}


# ---- names -----------------------------------------------------------------------------------------------------------
class Names:
    """GitHub ids to logins and repository names. Only what GitHub said, only in a form safe as a file name."""

    def __init__(self, users: dict | None = None, repos: dict | None = None):
        self.users = {int(k): v for k, v in (users or {}).items() if _LOGIN.fullmatch(str(v))}
        self.repos = {int(k): v for k, v in (repos or {}).items() if safe_repo(v)}
        self.tried: set = set()

    def login(self, i) -> str | None:
        return self.users.get(int(i)) if i else None

    def repo(self, i) -> str | None:
        return self.repos.get(int(i)) if i else None

    def repo_id(self, name: str) -> int | None:
        return next((i for i, n in self.repos.items() if n.lower() == name.lower()), None)

    def resolve(self, get, users, repos, cap: int = 400) -> None:
        """Ask GitHub about the ids not known yet, at most `cap` of them; one that is refused is left unnamed."""
        todo = [("user", i) for i in sorted(users) if i and i not in self.users] + [("repo", i) for i in sorted(repos) if i and i not in self.repos]
        for what, i in [t for t in todo if t not in self.tried][:cap]:
            self.tried.add((what, i))
            try:
                if what == "user":
                    got = str(get(f"user/{i}")["login"])
                    if _LOGIN.fullmatch(got):
                        self.users[i] = got
                else:
                    got = str(get(f"repositories/{i}")["full_name"])
                    if safe_repo(got):
                        self.repos[i] = got
            except Exception:  # noqa: BLE001 - GitHub did not name it: it has no file
                continue


def safe_repo(name) -> bool:
    owner, _, repo = str(name).partition("/")
    return bool(_LOGIN.fullmatch(owner) and _REPO.fullmatch(repo) and repo not in (".", "..") and not repo.endswith(".git"))


# ---- jobs, with what pages need beyond network_stats ----------------------------------------------------------------
def mint_kind(job: dict, keys) -> str:
    """real when the funding transaction names Circle's USDC mint among its accounts; test for the faucet and for any
    other mint, and when the transaction is not known: real is never assumed."""
    if job.get("faucet"):
        return "test"
    return "real" if USDC & set(keys or ()) else "test"


def bucket_of(job: dict) -> str:
    if job["kind"] in ("own", "self"):
        return job["kind"]
    return "test" if job["kind"] == "test" or job["mint_kind"] == "test" else "real"


def jobs_of(events: list[dict], own: frozenset, own_wallets: frozenset) -> list[dict]:
    """network_stats's jobs and work orders, each with `kind`, `mint_kind` and `bucket` (real, test, self or own). A
    work order that has paid and is closed, or holds only its warranty's part back, reads as `paid` here (its own
    state stays in `order_state`); a standing order that has paid and is still on offer stays `open`."""
    if not events:
        return []
    ns = _ns()
    jobs, _ = ns.work_of(events)
    keys = {ev["tx"]: ev["keys"] for ev in events if ev["event"] in ("funded", "order_funded") and ev.get("tx")}
    for j in jobs:
        j["kind"] = ns.kind_of(j, own, own_wallets)
        j["mint_kind"] = mint_kind(j, keys.get(j["tx"]))
        j["bucket"] = bucket_of(j)
        if "payments" in j:
            j["order_state"] = j["state"]
            j["state"] = "paid" if j["state"] == "warranty" else j["state"]
    return jobs


def earnings(jobs: list[dict]) -> list[dict]:
    """What each payee was paid, one entry per payee per job: a paid job itself; a work order's payments folded per
    payee (a split pays several; a holdback's release adds to its payee's; a kill fee is not pay for work and is left
    out), each a copy of the order with that payee's `payee`, `to`, `net`, `fee`, and the time, transaction and pull
    request of its first payment."""
    out = []
    for j in jobs:
        if "payments" not in j:
            out += [j] if j["state"] == "paid" else []
            continue
        per: dict[int, dict] = {}
        for pay_ in j["payments"]:
            if pay_["kind"] == "kill":
                continue
            e = per.setdefault(pay_["payee"], {**j, "state": "paid", "payee": pay_["payee"], "to": pay_["to"], "net": 0, "fee": 0, "paid_at": pay_["at"],
                                               "paid_tx": pay_["tx"], "pr": pay_["pr"] or None})
            e["net"] += pay_["amount"]
            e["fee"] += pay_["fee"]
        out += per.values()
    return out


def by_kind(jobs: list[dict], field: str) -> dict:
    return {k: {"count": sum(1 for j in jobs if j["bucket"] == k), "amount": sum(j.get(field) or 0 for j in jobs if j["bucket"] == k)} for k in KINDS}


def funder_stats(jobs: list[dict]) -> dict:
    """What a funder did with the jobs given: how many were funded, paid, refunded and are open, and how reliably their
    jobs ended in payment: paid of (paid + refunded), with the interval. Reliability is counted per kind of money and
    only over `real` and `test` jobs: a payment to the funder's own account or to Knos's own never adds to it."""
    paid, refunded = [j for j in jobs if j["state"] == "paid"], [j for j in jobs if j["state"] == "refunded"]
    ends = lambda kind: rate(sum(1 for j in paid if j["bucket"] == kind), sum(1 for j in paid + refunded if j["bucket"] == kind))  # noqa: E731
    return {"funded": by_kind(jobs, "amount"), "paid": by_kind(paid, "net"), "refunded": by_kind(refunded, "amount"),
            "open": sum(1 for j in jobs if j["state"] in ("open", "held", "proven")), "reliability": ends("real"), "reliability_test": ends("test")}


# ---- GitHub's side of a job: the pull request behind it -------------------------------------------------------------
def passed_at(runs: list[dict]) -> int | None:
    """When the last of a commit's checks finished, if every one that is not Knos's own succeeded (or was neutral or
    skipped); None when one failed or was still running, or there were none."""
    from knos import terms
    mine = [r for r in runs if not terms.ours(r, "")]
    if not mine or any(r.get("status") != "completed" or r.get("conclusion") not in ("success", "neutral", "skipped") for r in mine):
        return None
    times = [_unix(r.get("completed_at")) for r in mine]
    return max(t for t in times if t is not None) if any(t is not None for t in times) else None


def pr_facts(get, repo: str, number: int, cache: dict) -> dict | None:
    """One pull request as GitHub records it: its author, when it was merged or closed, when its checks passed, and
    the issues it closes. None when GitHub does not answer."""
    from knos import closing
    key = (repo.lower(), number)
    if key not in cache:
        try:
            pull = get(f"repos/{repo}/pulls/{number}")
            try:
                runs = (get(f"repos/{repo}/commits/{pull['head']['sha']}/check-runs?per_page=100") or {}).get("check_runs") or []
            except Exception:  # noqa: BLE001 - checks unread: no time from checks to the verdict, the rest still stands
                runs = None
            user = pull.get("user") or {}
            cache[key] = {"repo": repo, "number": number, "author_id": user.get("id"), "author": user.get("login"),
                          "merged_at": _unix(pull.get("merged_at")), "closed_at": _unix(pull.get("closed_at")),
                          "passed_at": passed_at(runs) if runs is not None else None, "closes": closing.closed_by(pull)}
        except Exception:  # noqa: BLE001
            cache[key] = None
    return cache[key]


def review_seconds(pr: dict) -> int | None:
    """From the pull request's checks passing to its merge or, when it was not merged, its closing. None when either
    time is unknown, or the merge came before the checks passed."""
    end = pr.get("merged_at") or pr.get("closed_at")
    return end - pr["passed_at"] if end and pr.get("passed_at") and end >= pr["passed_at"] else None


def pulls_of_jobs(jobs: list[dict], lines: list[dict], get, names: Names, cache: dict, most: int = 300) -> None:
    """Sets job["prs"] (the pull requests behind a job, as pr_facts) and job["merged_unpaid"] (a pull request that
    closes the job's issue was merged, no later than the refund, and the money was refunded instead). A paid job's
    pull request is the one the relay log names for the paying transaction; a refunded job's are the pull requests
    that GitHub's timeline of the issue shows as referencing it. Needs `get`; without it nothing is set (None)."""
    by_sig = {s: (r["repo"], r["number"]) for r in lines if r["kind"] in ("pay", "proof") for s in r["sigs"]}
    for j in jobs:
        j["prs"], j["merged_unpaid"] = None, None
    if get is None:
        return
    for j in sorted([j for j in jobs if j["state"] in ("paid", "refunded")], key=lambda j: j.get("paid_at") or j.get("refunded_at") or 0)[-most:]:
        j["prs"], j["merged_unpaid"] = [], False
        name = names.repo(j["repo"])
        if j["state"] == "paid" and by_sig.get(j.get("paid_tx")):
            repo, n = by_sig[j["paid_tx"]]
            pr = pr_facts(get, repo, n, cache)
            j["prs"] = [pr] if pr else []
        elif j["state"] == "refunded" and name:
            try:
                timeline = get(f"repos/{name}/issues/{j['issue']}/timeline?per_page=100")
            except Exception:  # noqa: BLE001
                j["merged_unpaid"] = None
                continue
            for ev in timeline:
                src = ((ev or {}).get("source") or {}).get("issue") or {}
                if ev.get("event") == "cross-referenced" and "pull_request" in src:
                    pr = pr_facts(get, (src.get("repository") or {}).get("full_name") or name, int(src["number"]), cache)
                    if pr and pr["repo"].lower() == name.lower() and j["issue"] in pr["closes"] and pr["merged_at"] and pr["merged_at"] <= j["refunded_at"]:
                        j["prs"].append(pr)
            j["merged_unpaid"] = bool(j["prs"])


def merged_unpaid(jobs: list[dict], names: Names) -> list[dict]:
    return [{"repository": names.repo(j["repo"]), "issue": j["issue"], "amount": j["amount"], "bucket": j["bucket"], "pull_request": pr["number"],
             "author": pr["author"], "merged_at": iso(pr["merged_at"]), "refunded_at": iso(j["refunded_at"])}
            for j in jobs if j.get("merged_unpaid") for pr in j["prs"]]


# ---- the relay log, with what network_stats does not keep ------------------------------------------------------------
def relay_extras(comments: list[dict]) -> tuple[dict, list[dict]]:
    """({token id: {queue, workflow, wait, chain: seconds}} for the `ok` lines that carry any of the four, the `fail`
    lines of the log as {kind, repo, number, token, why, posted}). Lines of the crank (no repository) are left out."""
    extras, fails = {}, []
    for c in comments or []:
        posted = _unix(c.get("created_at"))
        for line in (c.get("body") or "").splitlines():
            m = _OK.match(line.strip())
            if m:
                head = re.split(r"(?:^| )note=", m.group(5), maxsplit=1)[0]
                got = {k: float(v) for k, v in re.findall(r"(?:^| )(%s)=(\d+(?:\.\d+)?)(?= |$)" % "|".join(_PARTS), head)}
                if got:
                    extras[m.group(4)] = got
                continue
            m = _FAIL.match(line.strip())
            if m:
                fails.append({"kind": m.group(1), "repo": m.group(2), "number": int(m.group(3)), "token": m.group(4), "why": m.group(5), "posted": posted})
    return extras, fails


def refusals(fails: list[dict], get, names: Names, cache: dict, most: int = 300) -> list[dict]:
    """The relay's refusals at a merge: lines of kind pay or proof that ended `fail`, each with the repository's id
    (when the name is known) and the pull request author (when GitHub says), the newest `most`."""
    out = []
    for f in [f for f in fails if f["kind"] in ("pay", "proof")][-most:]:
        pr = pr_facts(get, f["repo"], f["number"], cache) if get else None
        out.append({**f, "repo_id": names.repo_id(f["repo"]), "author_id": (pr or {}).get("author_id"), "at": f["posted"]})
    return out


# ---- records: one account, one repository ---------------------------------------------------------------------------
def _bounds(paid: list[dict]) -> dict:
    return {"first": iso(min((j["paid_at"] for j in paid), default=0)), "last": iso(max((j["paid_at"] for j in paid), default=0))}


def earner_part(paid: list[dict], refused: list[dict] | None) -> dict:
    """paid merges, amounts by kind, distinct funders (of money that was not self-paid or Knos's own), refusals at
    merge, first and last."""
    outside = [j for j in paid if j["bucket"] in ("real", "test")]
    return {"paid_merges": len(paid), "amounts": by_kind(paid, "net"), "distinct_funders": len({j["funder"] for j in outside}),
            "distinct_funders_real": len({j["funder"] for j in outside if j["bucket"] == "real"}),
            "refusals_at_merge": len(refused) if refused is not None else None, **_bounds(paid)}


def review_part(jobs: list[dict]) -> dict:
    """Median time from a pull request passing its checks to the merge or rejection, over the jobs' pull requests."""
    took = [review_seconds(pr) for j in jobs for pr in (j.get("prs") or [])]
    return {"seconds": spread(took), "note": None if any(j.get("prs") is not None for j in jobs) else "not measured: GitHub was not asked"}


def refused_of(refused: list[dict] | None, key: str, value) -> list[dict] | None:
    """The refusals that belong to one account (`author_id`) or repository (`repo_id`); None when they cannot be told:
    the relay log was not read, or GitHub was not asked who wrote the pull requests."""
    if refused is None or (key == "author_id" and refused and not any(r["author_id"] for r in refused)):
        return None
    return [r for r in refused if r[key] == value]


def account_record(i: int, login: str, jobs: list[dict], refused: list[dict] | None, names: Names, measured: bool) -> dict:
    """`measured`: GitHub was asked about the pull requests behind the jobs (else those parts are null)."""
    paid = [j for j in earnings(jobs) if j["payee"] == i]
    funded = [j for j in jobs if j["funder"] == f"gh:{i}"]
    mine = [j for j in jobs if j.get("merged_unpaid") and any(pr["author_id"] == i for pr in j["prs"])]
    return {"login": login, "github_id": i, "as_earner": earner_part(paid, refused_of(refused, "author_id", i)),
            "as_funder": {**funder_stats(funded), "review": review_part(funded), "merged_unpaid": merged_unpaid(funded, names) if measured else None},
            "merged_but_unpaid_to_me": merged_unpaid(mine, names) if measured else None}


def repo_record(i: int, name: str, jobs: list[dict], refused: list[dict] | None, names: Names, measured: bool) -> dict:
    paid = [j for j in jobs if j["state"] == "paid"]
    return {"repository": name, "github_id": i,
            "as_earner": {**earner_part(paid, refused_of(refused, "repo_id", i)), "payees": len({j["payee"] for j in earnings(jobs) if j["bucket"] in ("real", "test")})},
            "as_funder": {**funder_stats(jobs), "review": review_part(jobs), "merged_unpaid": merged_unpaid(jobs, names) if measured else None}}


# ---- statements: the payments of an account, one row each ------------------------------------------------------------
STATEMENT_COLUMNS = ("date", "time", "deployment", "repository_id", "repository", "issue", "pull_request", "payee_id", "payee", "amount", "fee", "total", "currency",
                     "amount_units", "fee_units", "total_units", "funder_id", "funder", "kind", "transaction")


def units_text(units: int) -> str:
    """19500000 as "19.500000": integer arithmetic, so a column adds up to the unit."""
    return f"{units // 1_000_000}.{units % 1_000_000:06d}"


def payment_rows(jobs: list[dict], names: Names) -> list[dict]:
    """One row per payment, oldest first: the columns of `knos receipts` that this build knows, plus `kind` (real, test, self or own: what the
    payment is counted as) and `month`. `amount` is what reached the payee, `fee` what the escrow kept, `total` the two together, in the mint's
    six decimals; the `*_units` are the same as integers. `funder` is the funder's login (None when GitHub did not name it) or its wallet."""
    rows = []
    # a work order: one row per payee per payment (its fee is its funder's, on the first row of each paying transaction)
    each = [j if "payments" not in j else {**j, "state": "paid", "payee": p["payee"], "net": p["amount"], "fee": p["fee"], "paid_at": p["at"], "paid_tx": p["tx"],
                                           "pr": p["pr"] or None} for j in jobs for p in (j["payments"] if "payments" in j else [None]) if p is None or p["kind"] != "kill"]
    for j in each:
        if j["state"] != "paid" or not j.get("paid_at"):
            continue
        net, fee = j.get("net") or 0, j.get("fee") or 0
        fid = int(j["funder"][3:]) if j["funder"].startswith("gh:") and j["funder"][3:].isdigit() else None
        stamp = iso(j["paid_at"])
        rows.append({"month": stamp[:7], "date": stamp[:10], "time": stamp, "deployment": j["v"], "repository_id": j["repo"], "repository": names.repo(j["repo"]), "issue": j["issue"],
                     "pull_request": j.get("pr"), "payee_id": j["payee"], "payee": names.login(j["payee"]), "amount": units_text(net), "fee": units_text(fee), "total": units_text(net + fee),
                     "currency": "USDC" if j["mint_kind"] == "real" else "test USDC", "amount_units": net, "fee_units": fee, "total_units": net + fee, "funder_id": fid,
                     "funder": names.login(fid) if fid else j["funder"], "kind": j["bucket"], "transaction": j.get("paid_tx")})
    return sorted(rows, key=lambda r: (r["time"], r["transaction"] or ""))


def statement_file(i: int, login: str, rows: list[dict]) -> dict:
    """The rows an account was paid (`as_seller`) and the rows it funded (`as_owner`): the site picks a month and adds them up in the browser."""
    return {"login": login, "github_id": i, "columns": list(STATEMENT_COLUMNS), "decimals": 6,
            "as_seller": [r for r in rows if r["payee_id"] == i], "as_owner": [r for r in rows if r["funder_id"] == i],
            "note": "Every payment the escrows' log lines show, as paid: amounts in six decimals. A payment newer than `generated` is not in it. `kind` says what a payment is counted as (real, test, self, own); kinds are never added together."}


# ---- badges ----------------------------------------------------------------------------------------------------------
def badge(label: str, message: str, color: str, meta: dict) -> dict:
    return {"schemaVersion": 1, "label": label, "message": message, "color": color, "cacheSeconds": 1800, **meta}


def _usd(units: int) -> str:
    return f"{units / 1_000_000:,.2f}"


def paid_badge(rec: dict, meta: dict, median: int | None = None, repo: bool = False) -> dict:
    """"pays on merge: 12 paid, median 21 s" for a repository, "paid through Knos: 7" for an account. Only payments in
    real USDC are counted; with only test USDC the message says so, with nothing it says "none yet"."""
    amounts = rec["as_earner"]["amounts"]
    real, test = amounts["real"]["count"], amounts["test"]["count"]
    label = "pays on merge" if repo else "paid through Knos"
    if real:
        return badge(label, f"{real} paid" + (f", median {median} s" if repo and median is not None else ""), "brightgreen", meta)
    if test:
        return badge(label, f"{test} paid in test USDC", "lightgrey", meta)
    return badge(label, "none yet", "lightgrey", meta)


def readme_line(kind: str, path: str, label: str) -> str:
    """The Markdown to paste in a README: the badge, linking to the record."""
    endpoint = urllib.parse.quote(f"{SITE}/badge/{kind}/{path}.json", safe="")
    return f"[![{label}](https://img.shields.io/endpoint?url={endpoint})]({SITE}/{kind}/{path}.html)"


# ---- ranks -----------------------------------------------------------------------------------------------------------
def rank_earners(jobs: list[dict], names: Names) -> dict:
    """Payees by real USDC received. Test money, self-payment and Knos's own accounts are not in it; they are
    counted in `left_out`."""
    paid = [j for j in earnings(jobs) if j["payee"]]
    real = {}
    for j in paid:
        if j["bucket"] == "real":
            real.setdefault(j["payee"], []).append(j)
    rows = sorted(({"github_id": i, "login": names.login(i), "paid_amount": sum(j["net"] for j in js), "paid_merges": len(js),
                    "distinct_funders": len({j["funder"] for j in js}), "first": _bounds(js)["first"], "last": _bounds(js)["last"]} for i, js in real.items()),
                  key=lambda r: (-r["paid_amount"], -r["paid_merges"], r["first"] or "", r["github_id"]))
    return {"entries": [{"rank": n, **r} for n, r in enumerate(rows, 1)],
            "left_out": {k: sum(1 for j in paid if j["bucket"] == k) for k in ("test", "self", "own")}}


def rank_funders(jobs: list[dict], names: Names) -> dict:
    """Funders by real USDC that reached a payee, with how reliably their jobs ended in payment. Only real-money jobs
    count, so test money, self-payment and Knos's own accounts do not raise a rank."""
    real = {}
    for j in jobs:
        if j["bucket"] == "real":
            real.setdefault(j["funder"], []).append(j)
    rows = []
    for f, js in real.items():
        s = funder_stats(js)
        gh = int(f[3:]) if f.startswith("gh:") and f[3:].isdigit() else None
        rows.append({"funder": f, "github_id": gh, "login": names.login(gh) if gh else None, "paid_amount": s["paid"]["real"]["amount"], "paid_jobs": s["paid"]["real"]["count"],
                     "refunded_jobs": s["refunded"]["real"]["count"], "open_jobs": s["open"], "reliability": s["reliability"],
                     "merged_unpaid": sum(1 for j in js if j.get("merged_unpaid")) if any(j.get("merged_unpaid") is not None for j in js) else None})
    rows = sorted((r for r in rows if r["paid_jobs"] or r["refunded_jobs"]), key=lambda r: (-r["paid_amount"], -r["paid_jobs"], r["funder"]))
    left = [j for j in jobs if j["state"] == "paid"]
    return {"entries": [{"rank": n, **r} for n, r in enumerate(rows, 1)],
            "left_out": {k: sum(1 for j in left if j["bucket"] == k) for k in ("test", "self", "own")}}


def rank_agents(index: dict | None) -> dict:
    """The Agent PR Index's false-claim rate by agent: of the repositories where the agent's first pull request said
    tests or CI pass, in how many a check had failed at the head commit. Lowest first. Null without an index."""
    if not index:
        return {"month": None, "window": None, "entries": [], "note": "not measured: this build has no Agent PR Index (index.json)"}
    rows = []
    for name, t in (index.get("agents") or {}).items():
        first = t["first_pr_per_repo"]
        rows.append({"agent": name, "name": AGENT_NAMES.get(name, name), "repositories": first["repos"], "false_claim_rate": first["any_check_failed"]["share"],
                     "ci95": first["any_check_failed"]["ci95"], "test_or_build_rate": first["test_or_build_check_failed"]["share"],
                     "test_or_build_ci95": first["test_or_build_check_failed"]["ci95"], "pull_requests": t["prs"],
                     "pull_requests_any_check_failed": t["any_check_failed"]["prs"]})
    rows.sort(key=lambda r: (r["false_claim_rate"] is None, r["false_claim_rate"] or 0, r["agent"]))
    return {"month": str(index["date"])[:7], "date": index["date"], "window": index["window"], "root": index["root"],
            "definition": (index.get("definitions") or {}).get("any_check_failed"),
            "entries": [{"rank": n, **r} for n, r in enumerate(rows, 1)]}


# ---- latency ---------------------------------------------------------------------------------------------------------
def latency_samples(lines: list[dict], events: list[dict], get, extras: dict, most: int = 500) -> dict:
    """{merge_to_paid, comment_to_funded: [{at, seconds, t, parts}]} over the newest `most` lines of each kind of the
    relay log: `at` is the block time of the transaction that paid or funded, `seconds` runs from the merge or the
    funding comment (as network_stats.latency reads them), `t` is the relay's own seconds (comment to last
    transaction) and `parts` the optional stages the line carries."""
    ns = _ns() if lines else None
    landed = {}
    for ev in events:       # a job's lines and a work order's alike
        if ev["event"] in ("funded", "paid", "order_funded", "order_paid") and ev.get("tx"):
            landed.setdefault((ev["tx"], "fund" if ev["event"].endswith("funded") else "pay"), ev["at"])
    out = {}
    for name, kinds, what in (("comment_to_funded", ("fund",), "fund"), ("merge_to_paid", ("proof", "pay"), "pay")):
        got = []
        for line in [r for r in lines if r["kind"] in kinds][-most:]:
            done = next((landed[(s, what)] for s in line["sigs"] if (s, what) in landed), None)
            start = ns.asked_at(line, done, get) if done is not None and (get is not None or line["asked"] is not None) else None
            if start is not None and done >= start:
                got.append({"at": done, "seconds": done - start, "t": line.get("t"), "parts": extras.get(line["token"], {}), "sigs": line["sigs"]})
        out[name] = got
    return out


def latency_block(samples: list[dict]) -> dict:
    """The spread of a list of samples, by day, and the split of the wait the relay log allows: `github_side` (the
    merge or comment to the token's comment, which is the queue and the workflow together) and `relay_side` (the
    token's comment to the last transaction: the relay's wait and the chain together) are measured whenever the line
    ends in ` t=`; `queue`, `workflow`, `relay_wait` and `chain` only from lines that carry those stages."""
    days = {}
    for s in samples:
        days.setdefault(iso(s["at"])[:10], []).append(s["seconds"])
    split = {"github_side": spread([s["seconds"] - s["t"] for s in samples if s["t"] is not None and s["seconds"] >= s["t"]]),
             "relay_side": spread([s["t"] for s in samples if s["t"] is not None])}
    for part, key in (("queue", "queue"), ("workflow", "workflow"), ("relay_wait", "wait"), ("chain", "chain")):
        split[part] = spread([s["parts"][key] for s in samples if key in s["parts"]])
    return {**spread([s["seconds"] for s in samples]), "by_day": {d: {k: v for k, v in spread(x).items() if k in ("n", "p50", "p95", "slowest")} for d, x in sorted(days.items())},
            "split": split}


def latency_json(samples: dict, now: float, meta: dict, note: str | None) -> dict:
    out = {**meta, "note": note, "definitions": {
        "merge_to_paid": "from the merge (GitHub's merged_at) to the block time of the transaction that paid, over the lines of the public relay log",
        "comment_to_funded": "from the funding comment (GitHub's created_at) to the block time of the funding transaction",
        "split": "github_side + relay_side = the whole wait. queue (the comment or merge to the workflow run's start), workflow (the run's start to "
                 "the token's comment), relay_wait (that comment to the relay picking it up) and chain (pickup to the last confirmation) are read "
                 "from the relay log lines that carry queue=, workflow=, wait= and chain= (seconds). The relay writes each only when it could "
                 "measure it, so their n can be lower than the whole wait's, and lines written before it did carry none"}}
    for name, got in samples.items():
        out[name] = {"last_30_days": latency_block([s for s in got if s["at"] >= now - 30 * DAY]), "all_time": latency_block(got)}
    return out


# ---- operations ------------------------------------------------------------------------------------------------------
def canary_runs(get, repo: str = HOME_REPO, workflow: str = CANARY, pages: int = 20) -> list[dict] | None:
    """The canary workflow's runs, newest first; None when GitHub does not list them (no token, or no such workflow)."""
    out = []
    try:
        for page in range(1, pages + 1):
            got = (get(f"repos/{repo}/actions/workflows/{workflow}/runs?per_page=100&page={page}") or {}).get("workflow_runs") or []
            out += got
            if len(got) < 100:
                break
    except Exception:  # noqa: BLE001
        return None
    return out


def canary_block(runs: list[dict] | None, now: float) -> dict:
    if not runs:
        return {"runs": 0, "note": "No canary run has been read: GitHub was not asked, or the canary workflow has not run." if runs is None else "The canary workflow has not run yet."}
    finished = [r for r in runs if r.get("status") == "completed" and r.get("conclusion") in ("success", "failure", "timed_out", "startup_failure")]
    bad = [r for r in finished if r["conclusion"] != "success"]

    def window(rs):
        return {"runs": len(rs), "failed": sum(1 for r in rs if r["conclusion"] != "success"), "success_rate": rate(sum(1 for r in rs if r["conclusion"] == "success"), len(rs))}
    recent = [r for r in finished if (_unix(r.get("created_at")) or 0) >= now - 30 * DAY]
    return {"runs": len(runs), "first_run": iso(min(filter(None, (_unix(r.get("created_at")) for r in runs)), default=0)),
            "last_30_days": window(recent), "all_runs_read": window(finished),
            "incidents": [{"at": r.get("created_at"), "conclusion": r["conclusion"], "run": r.get("html_url")} for r in sorted(bad, key=lambda r: r.get("created_at") or "", reverse=True)[:50]],
            "note": None}


def response_block(get, own: frozenset, repo: str = HOME_REPO, pages: int = 2) -> dict:
    """The time from an outside issue or pull request being opened to the first comment of someone on the team (one of
    Knos's own accounts, or an owner, member or collaborator of the repository) who is not its author. Outside: not
    Knos's own account, not a bot."""
    if get is None:
        return {"n": 0, "note": "not measured: GitHub was not asked"}
    try:
        items = []
        for page in range(1, pages + 1):
            items += get(f"repos/{repo}/issues?state=all&sort=created&direction=desc&per_page=100&page={page}")
        outside = [i for i in items if (i.get("user") or {}).get("id") not in own and (i.get("user") or {}).get("type") != "Bot"]
        took, waiting = [], []
        for it in outside:
            opened = _unix(it.get("created_at"))
            team = [c for c in get(f"repos/{repo}/issues/{it['number']}/comments?per_page=100")
                    if (c.get("user") or {}).get("id") != (it.get("user") or {}).get("id") and (c.get("user") or {}).get("type") != "Bot"
                    and ((c.get("user") or {}).get("id") in own or c.get("author_association") in ("OWNER", "MEMBER", "COLLABORATOR"))]
            first = min((_unix(c.get("created_at")) for c in team), default=None)
            (took if first is not None else waiting).append(first - opened if first is not None else opened)
    except Exception as e:  # noqa: BLE001
        return {"n": 0, "note": f"not measured: GitHub did not answer ({type(e).__name__})"}
    return {**{k: v for k, v in spread(took).items() if k in ("n", "p50", "p95", "slowest")}, "waiting": len(waiting), "of": len(outside), "note": None if outside else "no outside issue or pull request yet"}


def operations_json(get, now: float, own: frozenset, meta: dict, workflow: str = CANARY) -> dict:
    runs = canary_runs(get, workflow=workflow) if get else None
    return {**meta, "canary": {**canary_block(runs, now), "workflow": workflow, "repository": HOME_REPO}, "response": response_block(get, own),
            "definitions": {"success_rate": "successful runs of the canary over its finished runs (failure, timed out and startup failure are failures; cancelled runs are not counted), with the 95% Wilson interval",
                            "incident": "a finished canary run that did not succeed, with its run's link",
                            "response": "from an outside issue or pull request being opened to the first comment of a team member who is not its author, over the newest 200 of the repository"}}


def _pct(r: dict) -> str:
    return "n/a" if not r or r["share"] is None else f"{r['share'] * 100:.1f}% ({r['k']} of {r['n']}; 95% interval {r['ci95'][0] * 100:.1f}%-{r['ci95'][1] * 100:.1f}%)"


def _dur(s) -> str:
    return "n/a" if s is None else (f"{s} s" if s < 120 else f"{s / 60:.1f} min" if s < 7200 else f"{s / 3600:.1f} h")


def _sentence(note: str | None) -> str:
    note = (note or "").strip()
    return note[:1].upper() + note[1:] + ("" if not note or note.endswith(".") else ".")


def render_operations_md(ops: dict) -> str:
    """docs/OPERATIONS.md from operations.json. Only what the json holds: with no data it says so and shows nothing."""
    c, r = ops.get("canary") or {}, ops.get("response") or {}
    lines = ["# Operations", "",
             "Whether Knos is working, from the public record. This page is written by `scripts/pages_data.py` from `operations.json`, "
             "which is published beside it on the site (`" + SITE + "/operations.json`); nothing here is typed by hand.", ""]
    lines += [f"Generated {ops['generated']}." if ops.get("generated") else "No measurement has been made yet: this is the page as it is committed, and the live page on the site replaces it.", ""]
    lines += ["## The canary", "",
              f"The canary is the scheduled workflow `{c.get('workflow') or CANARY}` of `{c.get('repository') or HOME_REPO}`, meant to run every 30 minutes. These are its runs as GitHub lists them.", ""]
    if not c.get("runs"):
        lines += [f"No runs to show. {_sentence(c.get('note')) or 'Nothing has been measured yet.'}", ""]
    else:
        lines += [f"- Runs read: {c['runs']}, the first on {c['first_run']}.",
                  f"- Success rate, last 30 days: {_pct(c['last_30_days']['success_rate'])} over {c['last_30_days']['runs']} finished runs.",
                  f"- Success rate, every run read: {_pct(c['all_runs_read']['success_rate'])}.", ""]
        lines += ["## Incidents", ""]
        lines += [f"- {i['at']}: {i['conclusion']} ([run]({i['run']}))" for i in c["incidents"]] or ["None: every finished canary run succeeded."]
        lines += [""]
    lines += ["## Answers to outside issues and pull requests", ""]
    if not r.get("of"):
        lines += [f"No outside issue or pull request to show. {_sentence(r.get('note'))}".strip(), ""]
    else:
        lines += [f"- Median time to a first answer from the team: {_dur(r['p50'])} (95th percentile {_dur(r['p95'])}, slowest {_dur(r['slowest'])}), over {r['n']} answered.",
                  f"- Still waiting for an answer: {r['waiting']} of {r['of']}.", ""]
    lines += ["## How these are counted", ""] + [f"- **{k}**: {v}" for k, v in (ops.get("definitions") or {}).items()] + [""]
    return "\n".join(lines)


# ---- bounties --------------------------------------------------------------------------------------------------------
def terms_of(job: dict) -> dict:
    """The terms of a job in words and as JSON; both null for a job whose terms the log does not carry (the first
    deployment keeps them in the repository's own files) or that this version cannot read."""
    raw = job.get("terms")
    if not raw:
        return {"words": None, "json": None}
    try:
        from knos import terms
        return {"words": terms.describe(terms.parse(raw), "funder"), "json": json.loads(raw)}
    except Exception:  # noqa: BLE001 - not the terms format of this version: published as it was logged
        try:
            return {"words": None, "json": json.loads(raw)}
        except ValueError:
            return {"words": None, "json": None}


def open_bounties(jobs: list[dict], accounts: dict | None, names: Names, now: float) -> tuple[list[dict], int]:
    """(every open funded task, how many open jobs are past their deadline and so left out). `accounts` maps a job's
    or a work order's address to its account as the program holds it (the deadline, the mint, a reservation, what an
    order promises); one whose account is gone is not open. A work order has `order` (see `order_part`); a job has
    None there. A private order names no repository and is not listed."""
    out, expired = [], 0
    for j in jobs:
        if j["state"] != "open" or j.get("private"):
            continue
        acct = (accounts or {}).get(j.get("address")) if accounts is not None else None
        if accounts is not None and (acct is None or ("payments" in j and acct.state != "open")):
            continue
        deadline = getattr(acct, "deadline", None) or (j.get("deadline") if "payments" in j else None) or None
        if deadline and deadline < now:
            expired += 1
            continue
        mint = str(acct.mint) if acct is not None and getattr(acct, "mint", None) else None
        kind = "test" if j["mint_kind"] == "test" or getattr(acct, "faucet", False) or (mint is not None and mint not in USDC) else "real"
        name = names.repo(j["repo"])
        order = order_part(j, acct, now) if "payments" in j else None
        reserved = order["reserved_until"] if order else iso(getattr(acct, "reserved_until", None) or None)
        out.append({"repository": name, "repository_id": j["repo"], "issue": j["issue"], "url": f"https://github.com/{name}/issues/{j['issue']}" if name else None,
                    "deployment": "first" if j["v"] == 1 else "second", "amount": order["on_offer"] if order else j["amount"], "decimals": 6,
                    "currency": "USDC" if kind == "real" else "test USDC",
                    "mint_kind": kind, "mint": mint, "terms": terms_of(j), "funded_at": iso(j["at"]), "funded_tx": j["tx"],
                    "deadline": iso(deadline), "reserved_until": reserved, "order": order, "own": j["kind"] == "own", "_funder": j["funder"]})
    return sorted(out, key=lambda b: (b["funded_at"] or "", b["funded_tx"] or ""), reverse=True), expired


def order_part(j: dict, acct, now: float) -> dict:
    """What an open work order promises beyond its amount and terms, from its account when it was read (else from the
    log, which knows less: null where it does not say):

        address, seq            the order's account, and its funder's number for it on this issue
        on_offer                what its payees can still receive (a standing order: what is left of it)
        fee                     what its funder put in on top (the payees receive the amount whole)
        standing, rate          a standing offer pays `rate` for each accepted pull request while enough is left
        holdback_bps, warranty_days   that share of a payment is held back for that long, and goes back on a revert
        reserved_by, reserved_until   the GitHub id it is reserved for now, and until when (null: free to take)
        reserve_days, kill_bps  how long one may reserve it, and the taker's share if it is cancelled meanwhile
        cancelled_at            the funder gave notice then: it pays what is accepted until `deadline`
        neutral                 the seller may have it paid from a repository of his own (`knos settle --neutral`)
        arbiter_id              the GitHub id whose ruling ends a dispute (null: none was named)"""
    get = lambda name, default=None: getattr(acct, name, default) if acct is not None else default  # noqa: E731
    until = get("reserved_until", j.get("reserved_until")) or None
    taken = bool(until and until >= now)
    cancelled = get("cancel_at", j.get("cancelled_at")) or None
    return {"address": j["order"], "seq": j["seq"], "on_offer": (acct.amount - acct.paid) if acct is not None else j["amount"] - j["net"],
            "fee": get("fee", j["fee_escrowed"]), "standing": j["standing"], "rate": get("rate") or None,
            "holdback_bps": get("holdback_bps"), "warranty_days": get("warranty_s") // DAY if acct is not None else None,
            "reserved_by": (get("reserved_by", j.get("reserved_by")) or None) if taken else None, "reserved_until": iso(until) if taken else None,
            "reserve_days": get("reserve_days"), "kill_bps": get("kill_bps"), "cancelled_at": iso(cancelled), "neutral": j["neutral"],
            "arbiter_id": get("arbiter_id") or None}


def with_funders(bounties: list[dict], jobs: list[dict], names: Names) -> list[dict]:
    """Each bounty with its funder's record: what that funder has funded, paid and refunded in the same kind of money."""
    for b in bounties:
        f = b.pop("_funder")
        mine = [j for j in jobs if j["funder"] == f and j["mint_kind"] == b["mint_kind"]]
        s = funder_stats(mine)
        gh = int(f[3:]) if f.startswith("gh:") and f[3:].isdigit() else None
        login = names.login(gh) if gh else None
        b["funder"] = {"id": f, "login": login, "funded": sum(v["count"] for v in s["funded"].values()), "paid": sum(v["count"] for v in s["paid"].values()),
                       "refunded": sum(v["count"] for v in s["refunded"].values()),
                       "reliability": s["reliability"] if b["mint_kind"] == "real" else s["reliability_test"], "record": f"u/{login}.json" if login else None}
    return bounties


def bounties_rss(bounties: list[dict], meta: dict) -> str:
    items = []
    for b in bounties:
        where = f"{b['repository']}#{b['issue']}" if b["repository"] else f"repository {b['repository_id']} issue #{b['issue']}"
        words = " ".join(b["terms"]["words"] or []) or "The terms are in the repository's own files."
        when = datetime.datetime.fromtimestamp(_unix(b["funded_at"]), datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000") if b["funded_at"] else ""
        o = b.get("order")
        if o:       # what a work order promises, in a sentence each
            words += (f" A standing offer: {o['rate'] / 1_000_000:,.2f} for each accepted pull request." if o["standing"] and o["rate"] else "") \
                + (f" {o['holdback_bps'] / 100:g}% is held back for a warranty of {o['warranty_days']} days." if o["holdback_bps"] else "") \
                + (f" Reserved until {o['reserved_until']}." if o["reserved_until"] else "")
        items.append("<item><title>" + xml(f"{b['amount'] / 1_000_000:,.2f} {b['currency']} for {where}") + "</title>"
                     + (f"<link>{xml(b['url'])}</link>" if b["url"] else f"<link>{SITE}/bounties.json</link>")
                     + f"<guid isPermaLink=\"false\">{xml(str(b['funded_tx']))}</guid>" + (f"<pubDate>{when}</pubDate>" if when else "")
                     + "<description>" + xml(f"{words} Funder: {b['funder']['login'] or b['funder']['id']}. Deadline: {b['deadline'] or 'not read'}.") + "</description></item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>Knos: open funded tasks</title>'
            f"<link>{SITE}/bounties.json</link><description>Every open funded task on Knos. Source: {xml(meta['source']['summary'])}</description>"
            f"<lastBuildDate>{datetime.datetime.fromtimestamp(meta['_now'], datetime.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000')}</lastBuildDate>"
            + "".join(items) + "</channel></rss>\n")


# ---- html ------------------------------------------------------------------------------------------------------------
CSS = ("body{font:16px/1.55 system-ui,sans-serif;margin:0;background:#fbfbf9;color:#16181d}main{max-width:860px;margin:0 auto;padding:24px 16px 48px}"
       "table{border-collapse:collapse;width:100%;margin:12px 0}th,td{text-align:left;padding:6px 10px;border-bottom:1px solid #e3e4e8}"
       "code,pre{background:#eef;padding:2px 5px;border-radius:4px;overflow-wrap:anywhere}a{color:#3b46c4}.muted{color:#5b616e;font-size:14px}"
       "@media(prefers-color-scheme:dark){body{background:#0f1115;color:#eceef2}th,td{border-color:#2a2f3a}code,pre{background:#1b1f2a}a{color:#8f98ff}.muted{color:#a2a8b5}}")


def esc(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def table(head: list[str], rows: list[list]) -> str:
    if not rows:
        return "<p class=muted>Nothing to show yet.</p>"
    return "<table><thead><tr>" + "".join(f"<th>{esc(h)}</th>" for h in head) + "</tr></thead><tbody>" + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table>"


def page(title: str, body: str, meta: dict, json_path: str | None = None) -> str:
    src = f"Source: {esc(meta['source']['summary'])}. Generated {esc(meta['generated'])}." + (f" The same numbers as <a href=\"{esc(SITE)}/{esc(json_path)}\">{esc(json_path)}</a>." if json_path else "")
    return (f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content=\"width=device-width,initial-scale=1\"><title>{esc(title)}</title>"
            f"<style>{CSS}</style><main><p class=muted><a href=\"{SITE}/\">Knos</a>: pays for software work on signed acceptance</p><h1>{esc(title)}</h1>{body}<p class=muted>{src}</p></main></html>\n")


def kinds_rows(amounts: dict) -> list[list]:
    words = {"real": "real USDC", "test": "test USDC", "self": "paid to the funder's own account", "own": "Knos's own accounts"}
    return [[esc(words[k]), esc(v["count"]), esc(_usd(v["amount"]))] for k, v in amounts.items()]


def unpaid_html(items: list[dict] | None) -> str:
    if items is None:
        return "<p class=muted>Not measured: GitHub was not asked or did not answer.</p>"
    return table(["repository", "issue", "pull request", "merged", "refunded"], [[esc(i["repository"]), esc(i["issue"]), esc(i["pull_request"]), esc(i["merged_at"]), esc(i["refunded_at"])] for i in items]) \
        if items else "<p>None: no pull request that closed a funded issue was merged and then refunded.</p>"


def record_page(rec: dict, kind: str, path: str, meta: dict) -> str:
    e, f = rec["as_earner"], rec["as_funder"]
    title = rec.get("login") or rec["repository"]
    label = "paid through Knos" if kind == "u" else "pays on merge"
    paste = readme_line(kind, path, label)
    rel = f["reliability"]
    body = (f"<h2>Paid merges</h2><p>{esc(e['paid_merges'])} paid; first {esc(e['first'] or 'none yet')}, last {esc(e['last'] or 'none yet')}. "
            f"{esc(e['distinct_funders'])} distinct funders ({esc(e['distinct_funders_real'])} with real USDC). Refusals at merge: {esc('not measured' if e['refusals_at_merge'] is None else e['refusals_at_merge'])}.</p>"
            + table(["kind of money", "payments", "USDC received"], kinds_rows(e["amounts"]))
            + "<h2>As funder</h2>" + table(["kind of money", "funded", "USDC funded"], kinds_rows(f["funded"]))
            + table(["kind of money", "paid", "USDC paid"], kinds_rows(f["paid"])) + table(["kind of money", "refunded", "USDC refunded"], kinds_rows(f["refunded"]))
            + f"<p>Open now: {esc(f['open'])}. Of the real-USDC jobs that ended, {esc(_pct(rel))} ended in payment. "
              f"Median time from a pull request passing its checks to the merge or rejection: {esc(_dur(f['review']['seconds']['p50']) if f['review']['seconds']['n'] else (f['review']['note'] or 'not measured'))}"
              f" over {esc(f['review']['seconds']['n'])} pull requests.</p>"
            + "<h2>Merged but unpaid</h2><p class=muted>A pull request that closes a funded issue was merged, and the bounty was refunded instead. This says both happened, not whose fault it was.</p>" + unpaid_html(f["merged_unpaid"])
            + f"<h2>README</h2><pre>{esc(paste)}</pre>")
    return page(title, body, meta, f"{kind}/{path}.json")


def rank_page(title: str, head: list[str], rows: list[list], note: str, meta: dict, json_path: str) -> str:
    return page(title, f"<p>{esc(note)}</p>" + table(head, rows), meta, json_path)


# ---- everything ------------------------------------------------------------------------------------------------------
def build(events: list[dict], comments: list[dict] | None, get, index: dict | None, accounts: dict | None, names: Names, now: float,
          own: frozenset | None = None, own_wallets: frozenset | None = None, canary: str = CANARY, source: dict | None = None) -> dict[str, str]:
    """{path under the output folder: text} for every file this module writes. `events` are network_stats's, `comments`
    the relay log's comments (None: not read), `get` reads GitHub (None: not asked), `index` is the Agent PR Index,
    `accounts` maps job addresses to accounts (None: not read)."""
    if own is None or own_wallets is None:
        own, own_wallets = own_ids()
    jobs = jobs_of(events, own, own_wallets)
    ns = _ns() if (events or comments) else None
    lines = ns.relay_lines(comments or []) if ns else []
    extras, fails = relay_extras(comments or []) if ns else ({}, [])
    if get is not None:
        names.resolve(get, {j[k] for j in jobs for k in ("payee", "owner", "by") if j.get(k)} | {i for j in jobs for i in j.get("payees", ()) if i},
                      {j["repo"] for j in jobs})
    cache: dict = {}
    pulls_of_jobs(jobs, lines, get, names, cache)
    refused = refusals(fails, get, names, cache) if comments is not None else None
    samples = latency_samples(lines, events, get, extras)       # asks GitHub for each line's start: once
    gen = iso(now)
    meta = {"generated": gen, "source": dict(source or {}), "_now": now}
    meta["source"].setdefault("chain", {"events": len(events), "programs": [str(_ns().pay.PAY_ID), str(_ns().pay2.PAY_ID)] if events else []})
    meta["source"].setdefault("relay_log", {"lines": len(lines), "failed_lines": len(fails), "repository": ns.RELAY_LOG_REPO if ns else None})
    meta["source"].setdefault("github", get is not None)
    meta["source"].setdefault("agent_pr_index", {"date": index["date"], "root": index["root"]} if index else None)
    meta["source"].setdefault("recompute", "python scripts/network_stats.py --events-out e.json; python scripts/pages_data.py --events e.json --index index.json")
    meta["source"].setdefault("summary", f"{len(events)} log lines of the escrows' history on devnet, {len(lines)} lines of the relay log, "
                              + ("GitHub" if get else "no GitHub reads") + (f", the Agent PR Index of {index['date']} (root {index['root'][:12]})" if index else ", no Agent PR Index"))
    stamp = lambda d: {"source": meta["source"], "generated": gen, **d}  # noqa: E731
    files: dict[str, str] = {}
    dump = lambda path, data: files.__setitem__(path, json.dumps(data, indent=1, sort_keys=False, ensure_ascii=False) + "\n")  # noqa: E731

    # bounties
    bounties, expired = open_bounties(jobs, accounts, names, now)
    bounties = with_funders(bounties, jobs, names)
    dump("bounties.json", stamp({"count": len(bounties), "expired_not_listed": expired, "bounties": bounties,
                                  "note": None if accounts is not None else "not measured against the programs' accounts: deadlines are null"}))
    files["bounties.rss"] = bounties_rss(bounties, meta)

    # accounts and repositories
    measured = get is not None
    account_ids = sorted({i for j in jobs for i in (j.get("payees") or [j["payee"]]) if i} | {int(j["funder"][3:]) for j in jobs if j["funder"].startswith("gh:") and j["funder"][3:].isdigit() and int(j["funder"][3:])})
    payments = payment_rows(jobs, names)
    unnamed_accounts, index_users, index_repos = 0, [], []
    badge_meta = {"source": meta["source"], "generated": gen}
    for i in account_ids:
        login = names.login(i)
        if not login:
            unnamed_accounts += 1
            continue
        rec = account_record(i, login, jobs, refused, names, measured)
        dump(f"u/{login}.json", stamp({**rec, "badge": {"endpoint": f"{SITE}/badge/u/{login}.json", "readme": readme_line("u", login, "paid through Knos")}}))
        files[f"u/{login}.html"] = record_page(rec, "u", login, meta)
        dump(f"badge/u/{login}.json", paid_badge(rec, badge_meta))
        dump(f"statements/{login}.json", stamp(statement_file(i, login, payments)))
        index_users.append(login)
    unnamed_repos = 0
    for i in sorted({j["repo"] for j in jobs if j["repo"]}):
        name = names.repo(i)
        if not name:
            unnamed_repos += 1
            continue
        mine = [j for j in jobs if j["repo"] == i]
        rec = repo_record(i, name, mine, refused, names, measured)
        dump(f"r/{name}.json", stamp({**rec, "badge": {"endpoint": f"{SITE}/badge/r/{name}.json", "readme": readme_line("r", name, "pays on merge")}}))
        files[f"r/{name}.html"] = record_page(rec, "r", name, meta)
        sigs = {j["paid_tx"] for j in mine if j["state"] == "paid" and j.get("paid_tx")}
        median = spread([s["seconds"] for s in samples["merge_to_paid"] if sigs & set(s["sigs"])])["p50"]
        dump(f"badge/r/{name}.json", paid_badge(rec, badge_meta, median, repo=True))
        index_repos.append(name)
    dump("records.json", stamp({"accounts": index_users, "repositories": index_repos, "unnamed_accounts": unnamed_accounts, "unnamed_repositories": unnamed_repos,
                                 "note": "an id GitHub did not name gets no file"}))

    # ranks
    earners, funders, agents = rank_earners(jobs, names), rank_funders(jobs, names), rank_agents(index)
    dump("rank/earners.json", stamp(earners))
    dump("rank/funders.json", stamp(funders))
    dump("rank/agents.json", stamp(agents))
    who = lambda login, gid: f'<a href="{SITE}/u/{esc(login)}.html">{esc(login)}</a>' if login else esc(f"id {gid}")  # noqa: E731
    note = "Real USDC only. Test money, a payment to the funder's own account and Knos's own accounts are not counted: " + ", ".join(f"{v} {k}" for k, v in earners["left_out"].items()) + " payments left out."
    files["rank/earners.html"] = rank_page("Earners", ["rank", "account", "USDC received", "paid merges", "distinct funders", "first", "last"],
                                           [[esc(r["rank"]), who(r["login"], r["github_id"]), esc(_usd(r["paid_amount"])), esc(r["paid_merges"]), esc(r["distinct_funders"]), esc(r["first"]), esc(r["last"])] for r in earners["entries"]],
                                           note, meta, "rank/earners.json")
    files["rank/funders.html"] = rank_page("Funders", ["rank", "funder", "USDC paid out", "paid", "refunded", "open", "reliability (paid of paid + refunded)", "merged but unpaid"],
                                           [[esc(r["rank"]), who(r["login"], r["github_id"]) if r["github_id"] else esc(r["funder"]), esc(_usd(r["paid_amount"])), esc(r["paid_jobs"]), esc(r["refunded_jobs"]), esc(r["open_jobs"]),
                                             esc(_pct(r["reliability"])), esc("not measured" if r["merged_unpaid"] is None else r["merged_unpaid"])] for r in funders["entries"]],
                                           note.replace("not counted", "not counted in a rank"), meta, "rank/funders.json")
    files["rank/agents.html"] = rank_page(f"Agents by false-claim rate{', ' + agents['month'] if agents['month'] else ''}", ["rank", "agent", "repositories", "a check had failed", "95% interval", "a test or build check failed", "95% interval"],
                                          [[esc(r["rank"]), esc(r["name"]), esc(r["repositories"]), esc("n/a" if r["false_claim_rate"] is None else f"{r['false_claim_rate'] * 100:.1f}%"),
                                            esc("n/a" if not r["ci95"] else f"{r['ci95'][0] * 100:.1f}%-{r['ci95'][1] * 100:.1f}%"),
                                            esc("n/a" if r["test_or_build_rate"] is None else f"{r['test_or_build_rate'] * 100:.1f}%"),
                                            esc("n/a" if not r["test_or_build_ci95"] else f"{r['test_or_build_ci95'][0] * 100:.1f}%-{r['test_or_build_ci95'][1] * 100:.1f}%")] for r in agents["entries"]],
                                          agents.get("note") or ("Of the repositories where the agent's first pull request said tests or CI pass, the share where a check had failed at the head commit "
                                                                 f"(Agent PR Index of {agents['date']}, pull requests created {agents['window'][0]} to {agents['window'][1]}). A failed check is GitHub's record, not a judgment of why."),
                                          meta, "rank/agents.json")

    # latency and operations
    note = None if get else "not measured: GitHub was not asked, so a line of the relay log that does not carry its own start time is not measured"
    dump("latency.json", latency_json(samples, now, {"source": meta["source"], "generated": gen}, note))
    ops = operations_json(get, now, own, {"source": meta["source"], "generated": gen}, canary)
    dump("operations.json", ops)
    files["OPERATIONS.md"] = render_operations_md(ops if (events or comments or get) else {**ops, "generated": None})      # a build that read nothing says so
    return files


def empty(now: float) -> dict[str, str]:
    """Every file with nothing measured: what a build with no chain and no GitHub writes."""
    return build([], None, None, None, None, Names(), now, own=frozenset(), own_wallets=frozenset(),
                 source={"summary": "nothing: this build read neither the chain nor GitHub"})


def write(files: dict[str, str], out: Path) -> None:
    root = out.resolve()
    for rel, text in files.items():
        dest = (root / rel).resolve()
        if root not in dest.parents:
            raise ValueError(f"{rel} is outside the output folder")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_site")
    ap.add_argument("--events", help="the log events scripts/network_stats.py --events-out wrote; without it the chain is read here")
    ap.add_argument("--index", help="the Agent PR Index (index.json), already checked")
    ap.add_argument("--docs", help="also write OPERATIONS.md here (docs/OPERATIONS.md)")
    ap.add_argument("--limit", type=int, default=1000, help="the newest transactions of each program to read when --events is not given")
    ap.add_argument("--canary", default=CANARY, help="the file of the canary workflow in the home repository")
    ap.add_argument("--no-github", action="store_true")
    ap.add_argument("--empty", action="store_true", help="write every file with nothing measured")
    a = ap.parse_args(argv)
    now = time.time()
    if a.empty:
        files = empty(now)
    else:
        ns = _ns()
        from knos import chain
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or None
        get = None if a.no_github else (lambda path: ns.github(path, token))
        url = os.environ.get("KNOS_RPC") or chain.CLUSTERS["devnet"]
        if a.events and Path(a.events).exists():
            events = json.loads(Path(a.events).read_text(encoding="utf-8"))
        else:
            events = []
            for program in (ns.pay.PAY_ID, ns.pay2.PAY_ID, ns.meter.METER_ID):
                events += ns.history(url, program, a.limit)[0]
            events.sort(key=lambda ev: ev["at"])
        index = None
        if a.index and Path(a.index).exists():
            try:
                index = agent_pr_index.check(a.index)
            except SystemExit as e:      # the list was edited after the count: shown as absent, never used
                print(f"pages_data: {e}", file=sys.stderr)
        accounts = None
        try:
            ledger = chain.Ledger(url)
            accounts = {str(k): ns.pay2.read_job(d) for k, d in ledger.program_accounts(ns.pay2.PAY_ID, ns.pay2.JOB_LEN)}
            accounts.update({str(k): ns.pay2.read_order(d) for k, d in ledger.program_accounts(ns.pay2.PAY_ID, ns.pay2.ORDER_LEN)})
            accounts.update({str(k): ns.pay.read_job(d) for k, d in ledger.program_accounts(ns.pay.PAY_ID, 256)})
            accounts = {k: v for k, v in accounts.items() if v}
        except Exception as e:  # noqa: BLE001 - deadlines are then null, and the file says so
            print(f"pages_data: the programs' accounts were not read ({type(e).__name__})", file=sys.stderr)
        comments = None
        if get:
            try:
                comments = ns.relay_log(get)
            except Exception as e:  # noqa: BLE001
                print(f"pages_data: the relay log was not read ({type(e).__name__})", file=sys.stderr)
        files = build(events, comments, get, index, accounts, Names(), now, canary=a.canary)
    write(files, Path(a.out))
    if a.docs:
        Path(a.docs).write_text(files["OPERATIONS.md"], encoding="utf-8")
    print(f"pages_data: {len(files)} files under {a.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
