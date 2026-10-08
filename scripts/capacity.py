"""Capacity of the whole workflow: what one order costs outside the chain, and which limit a customer meets first.

    python scripts/capacity.py --write            # count again, write docs/load.json's `workflow` section and docs/LOAD.md
    python scripts/capacity.py -R 10 -N 1000      # one customer: 10 repositories, 1,000 accepted deliverables a day

scripts/load.py measures the chain side. A chain number is not the system's capacity: an order is also two workflow
jobs, the requests each makes of GitHub with a token GitHub rations, the comments it posts, a token GitHub signs, a
relay that carries it, and a statement someone reads back. This script:

  count()     runs the three words of src/knos/flow.py (`command`, `settle`, `attest`) against the tests' fake of
              api.github.com (tests/_flow.py) and counts, per word and per way the token travels, the requests read,
              the requests written, the comments made and the tokens GitHub signed. Counted from the code, not from
              GitHub: exact for the paths the fake serves, on the simplest order (one issue, one pull request, one payee).
  constants() everything else the model uses, each with where it comes from: GitHub's and Solana's published limits
              (LIMITS, each with its link in SOURCES), the relay's own constants (src/knos/proof/ghrelay.py), the chain
              rates scripts/load.py measured, and the recorded merge-to-paid samples (docs/bench.json).
  bounds()    for a customer with R repositories and N accepted deliverables a day: every limit, the N at which it
              binds, and what lifts it without a program change. The first row is the limit that binds first.

Nothing here opens the network. Arrivals are taken as even over the day unless `--peak` says how much busier the
busiest hour is than the mean one; that is an input, not a measurement.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests"), str(ROOT / "scripts")]

JSON, BENCH = ROOT / "docs" / "load.json", ROOT / "docs" / "bench.json"
DAY = 86_400
READ = "2026-10-05"                 # the day the published limits below were read
SIZES = ((1, 10), (10, 1_000), (100, 100_000))     # (repositories, accepted deliverables a day): the three customers of the page
OWN, PUBLIC = "own", "public"       # who carries the token: the job itself, with the repository's fee key; Knos's public worker
SERIAL_PASS = "the public relay's pass, at the serial rate recorded"       # the row of `bounds` for what one relayer carries in a day

# Published limits, as read on READ. A limit GitHub or Solana changes is changed here, with its link, and nowhere else.
LIMITS = {
    "github_token_requests_per_hour": 1_000,        # GITHUB_TOKEN, per repository
    "github_token_requests_per_hour_enterprise": 15_000,
    "rest_requests_per_hour_user": 5_000,
    "rest_requests_per_hour_unauthenticated": 60,
    "content_per_minute": 80,                       # secondary limit: content-generating requests (a comment is one)
    "content_per_hour": 500,
    "points_per_minute": 900,                       # secondary limit: a GET is 1 point, a POST/PATCH/DELETE 5
    "search_per_minute": 30,
    "concurrent_jobs": {"Free": 20, "Pro": 40, "Team": 60, "Enterprise": 500},
    "runs_queued_per_10s": 500,                     # per repository
    "rpc_requests_per_10s": 100,                    # Solana's public endpoints, per IP
    "rpc_one_method_per_10s": 40,
    "account_cu_per_block": 12_000_000,
    "slot_s": 0.4,
}
SOURCES = {
    "GitHub: rate limits for the REST API (60 an hour unauthenticated, 5,000 authenticated, 1,000 per repository for GITHUB_TOKEN, 15,000 on "
    "Enterprise Cloud; secondary limits: 900 points a minute, 80 content-generating requests a minute and 500 an hour, \"subject to change "
    "without notice\")": "https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api",
    "GitHub: best practices for the REST API (a 304 to a conditional request sent with an Authorization header does not count against the "
    "primary limit; wait a second between writes)": "https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api",
    "GitHub: Actions limits (concurrent jobs on standard hosted runners: Free 20, Pro 40, Team 60, Enterprise 500; 500 workflow runs queued "
    "per 10 seconds per repository)": "https://docs.github.com/en/actions/reference/limits",
    "GitHub: Actions billing (standard hosted runners are free in public repositories; included minutes a month: Free 2,000, Pro 3,000, "
    "Team 3,000, Enterprise Cloud 50,000)": "https://docs.github.com/en/billing/concepts/product-billing/github-actions",
    "GitHub: search endpoints (30 requests a minute when authenticated)": "https://docs.github.com/en/rest/search/search",
    "GitHub: OpenID Connect reference (the page that describes the token request; it states no rate limit, and none was measured here)":
        "https://docs.github.com/en/actions/reference/security/oidc",
    "Solana: public RPC endpoints (100 requests per 10 seconds per IP, 40 for one method; \"not intended for production applications\")":
        "https://solana.com/docs/references/clusters",
    "Solana: 100M CU blocks (SIMD-0286), which also states the 12M per-account limit": "https://solana.com/upgrades/100m-cu-blocks",
}


# == counting what the workflow asks of GitHub =========================================================================
def _tally(w, before: tuple, word: str) -> dict:
    """What one run of a word asked since `before`: (reads, writes, tokens signed, waits for the public worker)."""
    reads, wrote = w.hub.asked[before[0]:], w.hub.wrote[before[1]:]
    comments = sum(1 for p in wrote if p.endswith("/comments"))
    return {"word": word, "reads": len(reads), "writes": len(wrote), "comments": comments, "tokens_signed": len(w.signer.asked) - before[2],
            "waits": len(w.worker.waited) - before[3], "jobs": 1}


def _mark(w) -> tuple:
    return len(w.hub.asked), len(w.hub.wrote), len(w.signer.asked), len(w.worker.waited)


def count() -> dict:
    """{way: {word: tally}} for the simplest order: `/knos fund 20` on an issue, one pull request that closes it, merged,
    one payee with a bound wallet. `attest_pay` is the seller's own run for the same payment; `attest_eval` is one
    evaluation counted at the meter. Both ways the token travels (OWN: KNOS_RELAY_KEY is set; PUBLIC: it is not)."""
    from _flow import HUBOT, MONA, World, check
    from knos import flow
    out: dict = {}
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):     # a run prints what it commented
        for way in (OWN, PUBLIC):
            def world(name: str):
                w = World(Path(tmp) / f"{way}-{name}", relay_key=way == OWN)
                w.version = 1
                w.hub.issue(7, "Slugify keeps punctuation.")
                w.hub.required = [{"context": "test", "integration_id": 15368}]
                return w

            def attest(w, kind: str, order: str, **env) -> dict:
                w.tmp.mkdir(parents=True, exist_ok=True)
                run = w.run({}, **{"GITHUB_ACTOR_ID": str(MONA["id"]), "GITHUB_ACTOR": "mona", "GITHUB_REPOSITORY_ID": "999",
                                   "GITHUB_STEP_SUMMARY": str(w.tmp / "summary.md"), **env})
                w.signer.actor = MONA["id"]
                at = _mark(w)
                code = flow.attest(run, order, kind, 12)
                assert code == 0, (way, kind, (w.tmp / "summary.md").read_text(encoding="utf-8"))
                return _tally(w, at, f"attest ({kind})")
            got = {}
            w = world("order")
            at = _mark(w)
            assert flow.command(w.run(w.hub.commented(7, HUBOT, "/knos fund 20"))) == 0 and len(w.chain.orders(7)) == 1
            got["command"] = _tally(w, at, "command (`/knos fund`)")
            w.clock.sleep(3600)
            w.hub.checks[w.hub.pull(12, MONA, "Fixes #7")["head"]["sha"]] = [check("test"), check("build")]
            w.chain.bind(MONA)
            event = w.hub.merge(12)
            at = _mark(w)
            assert flow.settle(w.run(event)) == 0 and w.chain.orders() == []
            got["settle"] = _tally(w, at, "settle (on the merge)")
            if way == OWN:                  # the seller's and the meter's runs post in a repository of their own when no key is set: counted with the key
                w = world("attest")
                w.chain.order(7, 20_000_000, {"accept": "", "checks": [{"app": 15368, "name": "test"}], "deny": [".github/**", ".knos/**"],
                                              "mode": "merge", "paths": [], "reserve": 7, "v": 1})
                w.clock.sleep(3600)
                w.hub.checks[w.hub.pull(12, MONA, "Fixes #7")["head"]["sha"]] = [check("test")]
                w.chain.bind(MONA)
                w.hub.merge(12)
                (address, _o), = w.chain.orders(7)
                got["attest_pay"] = attest(w, "pay", str(address))
                w = world("eval")
                w.hub.pull(12, MONA, "Slugify, as the work order asks")
                w.hub.merge(12)
                w.relay.refusals.append({"ok": True, "kind": "eval", "sigs": ["sigE"], "accepted": True, "fee": 0})
                got["attest_eval"] = attest(w, "eval", f"{bytes(range(32)).hex()}.3.2500000", GITHUB_REPOSITORY_OWNER_ID=str(HUBOT["id"]))
            out[way] = got
    return out


# == the constants the model is fed ====================================================================================
def polls(seconds: float, every: float = 3.0) -> int:
    """Requests `ghrelay.wait_for` makes while a job waits `seconds` for the public worker's log line: one to find the
    log issue, then one read of the log now and every `every` seconds. The job reads with its own GITHUB_TOKEN and
    without If-None-Match (knos.judge.github), so every one counts against the repository's hourly limit."""
    return 2 + int(seconds // every)


def constants(counted: dict | None = None, load: dict | None = None, bench: dict | None = None) -> dict:
    """The `workflow` section of docs/load.json, before the model's answers: `counted` (count()), `relay` and `meter`
    (constants of the code), `chain` (docs/load.json's local run), `latency` (docs/bench.json's recorded samples)."""
    from knos import flow
    from knos.proof import ghrelay
    from knos.settle.v2 import meter, relayq
    load = json.loads(JSON.read_text(encoding="utf-8")) if load is None else load
    bench = json.loads(BENCH.read_text(encoding="utf-8")) if bench is None else bench
    loc, lat = load["local"], bench["devnet"]["stats"]["latency"]
    st, d = loc["stages"], loc["derived"]
    m2p = lat["merge_to_paid"]
    tx = sum(st[s]["tx_per_order"]["p50"] for s in ("verify", "fund", "pay"))
    return {
        "read": READ,
        "limits": LIMITS,
        "sources": SOURCES,
        "counted": counted if counted is not None else count(),
        "relay": {
            "wait_every_s": 3.0, "wait_at_most_s": flow.RELAY_WAIT,
            "polls_at_median": polls(m2p["median"]), "polls_at_p95": polls(m2p["p95"]), "polls_at_timeout": polls(flow.RELAY_WAIT),
            "repositories_read_per_pass_at_most": 2 + ghrelay.EVERY_PASS + ghrelay.IN_TURN + ghrelay.CHAIN_REPOS,
            "search_every_s": ghrelay.SEARCH_EVERY, "pass_every_s": 3.0,
            "counted_reads_per_token": 1,       # the repository's comment page changed, so its conditional read is answered in full
            "log_comments_per_token": 1,        # `once` posts a carried token's line at once: someone is waiting for it
            "tokens_at_a_time": relayq.WORKERS,     # `once` queues a pass's tokens and carries this many at once, an owner's in order
        },
        "meter": {"statement_reads_at_most": 100_000, "rows_per_history_request": 100, "evaluations_per_batch_at_most": meter.MAX_BATCH},
        "chain": {
            "fixtures": loc["fixtures"],
            "transactions_per_order": tx, "tokens_per_order": st["verify"]["tokens_per_order"],
            "bytes_per_order": sum(st[s]["bytes_per_order"]["p50"] for s in ("verify", "fund", "pay")),
            "cu_per_order": d["cu_per_order"],
            "one_relayer_orders_per_second": d["one_relayer_orders_per_second"],
            "one_balance_orders_per_second": d["one_balance_orders_per_second"],
            "fee_account_orders_per_second": d["fee_account_orders_per_second"],
        },
        "latency": {"merge_to_paid_s": {k: m2p[k] for k in ("count", "median", "p95")}, "window": m2p["window"],
                    "comment_to_funded_median_s": lat.get("comment_to_funded", {}).get("median"),
                    "stage_split": "not apart in these samples; scripts/latency_stages.py splits"
                                   " the payments whose relay log line carries the stage fields: docs/RELAY.md, \"Where a token waits\""},
    }


# == the per-order budget ==============================================================================================
def budget(c: dict, way: str) -> dict:
    """What one deliverable (funded by a comment, paid on its merge) costs: the two words' counts, the public worker's
    polling when it carries the tokens (at the median and the p95 of the recorded merge-to-paid), and the chain's."""
    words = [c["counted"][way][w] for w in ("command", "settle")]
    s = {k: sum(w[k] for w in words) for k in ("reads", "writes", "comments", "tokens_signed", "waits", "jobs")}
    wait = {"median": s["waits"] * c["relay"]["polls_at_median"], "p95": s["waits"] * c["relay"]["polls_at_p95"],
            "timeout": s["waits"] * c["relay"]["polls_at_timeout"]}
    return {**s, "poll_requests": wait, "token_requests": {k: s["reads"] + s["writes"] + v for k, v in wait.items()},
            "relay_log_comments": s["waits"] * c["relay"]["log_comments_per_token"],
            "transactions": c["chain"]["transactions_per_order"], "bytes": c["chain"]["bytes_per_order"], "cu": c["chain"]["cu_per_order"]}


def statement_requests(evaluations: int, per_transaction: int = 1, rows: int = 100) -> int:
    """RPC requests `knos statement --meter` makes for a month: the month account's history a hundred rows a request,
    one getTransaction for each transaction in it, and the month account itself (knos.settle.v2.meter.statement,
    knos.chain.Ledger.history)."""
    txs = math.ceil(evaluations / per_transaction)
    return txs // rows + 1 + txs + 1


# == the model =========================================================================================================
def bounds(c: dict, repos: int, per_day: int, way: str = OWN, plan: str = "Free", peak: float = 1.0, relayers: int = 1) -> list[dict]:
    """Every limit a customer with `repos` repositories and `per_day` accepted deliverables a day meets, soonest first.
    `at` is the deliverables a day at which the limit binds; `load` is per_day / at (1.0 and over: it binds). The work
    is taken as spread evenly over the repositories, and over the day except that the busiest hour is `peak` times the
    mean. `scope` says whose limit it is: the customer's own, or one every customer of the public worker shares."""
    b, L, ch, lat = budget(c, way), c["limits"], c["chain"], c["latency"]["merge_to_paid_s"]
    hours = 24 / peak
    rows = [
        {"limit": "comments made in one repository", "scope": "each repository",
         "at": repos * L["content_per_hour"] * hours / b["comments"],
         "from": f"{b['comments']} comments a deliverable (counted); {L['content_per_hour']} content-generating requests an hour (GitHub)",
         "lift": "more repositories" + ("; or the job's own relay, which posts no token comment" if way == PUBLIC else "")},
        {"limit": "GITHUB_TOKEN requests an hour", "scope": "each repository",
         "at": repos * L["github_token_requests_per_hour"] * hours / b["token_requests"]["p95"],
         "from": f"{b['token_requests']['p95']} requests a deliverable ({b['reads']} reads and {b['writes']} writes counted"
                 + (f", {b['poll_requests']['p95']} polls of the relay log at the p95 wait" if b["waits"] else "")
                 + f"); {L['github_token_requests_per_hour']:,} an hour for a repository (GitHub)",
         "lift": ("the job's own relay (no polling); " if way == PUBLIC else "") + "more repositories; GitHub Enterprise Cloud (15,000 an hour)"},
        {"limit": f"concurrent jobs ({plan} plan)", "scope": "the customer's account",
         "at": L["concurrent_jobs"][plan] * DAY / peak / (b["jobs"] * lat["p95"]),
         "from": f"{b['jobs']} jobs a deliverable (counted), each taken as busy for the p95 of merge-to-paid, {lat['p95']} s (recorded, "
                 f"{lat['count']} samples; a job's own time on the runner was not measured apart); {L['concurrent_jobs'][plan]} jobs at once (GitHub)",
         "lift": "a larger plan (Pro 40, Team 60, Enterprise 500); self-hosted runners, which this limit does not count"},
        {"limit": "the Balance, one writable account", "scope": "each Balance",
         "at": ch["one_balance_orders_per_second"] * DAY / peak,
         "from": f"{ch['one_balance_orders_per_second']} fundings a second for one Balance (derived by scripts/load.py from measured compute "
                 "units and 12M units an account a block)",
         "lift": "one Balance per team in place of one per organisation: a Balance's address is the owner's id, the wallet that opened it "
                 "and the mint, and a funding comment spends the Balance that lists its commenter, so each team's wallet opens its own "
                 "(`knos balance open`) and lists its own people. The hot account is split by configuration; every Balance keeps its own "
                 "cap, and no order can take more than its Balance holds"},
        {"limit": "the fee account of the mint", "scope": "every customer, every relayer",
         "at": ch["fee_account_orders_per_second"] * DAY / peak,
         "from": f"{ch['fee_account_orders_per_second']} payments a second in one mint (derived by scripts/load.py)",
         "lift": "K fee accounts, no program change: PayOrder, SettleOrder and Release take ANY token account of the mint that "
                 "FEE_OWNER owns (order_pay.rs `is_owned(fee_tok, token, mint, FEE_OWNER)`), so `knos relay fee-accounts --k K` makes "
                 "K-1 more and each order's payments use one of K, chosen by the order (KNOS_FEE_SHARDS, KNOS_FEE_BASE); shown in the "
                 "simulator on the 2.1 and 2.2 builds, not yet measured on a cluster"},
    ]
    if way == PUBLIC:
        tokens = ch["tokens_per_order"]
        rows += [
            {"limit": "the public relay's log comments", "scope": "every customer of the public worker",
             "at": L["content_per_hour"] * hours / (tokens * c["relay"]["log_comments_per_token"]),
             "from": f"{tokens} tokens a deliverable, one log comment each (src/knos/proof/ghrelay.py posts a carried token's line at once); "
                     f"{L['content_per_hour']} content-generating requests an hour (GitHub)",
             "lift": "the job's own relay with the repository's fee key (KNOS_RELAY_KEY): nothing is logged by the public worker; or "
                     "several workers, each logging in a repository of its own (KNOS_RELAY_LOG_REPO)"},
            # The sweep carries up to `tokens_at_a_time` tokens at once since 0.3.17. The only time recorded on devnet
            # is of the sweep before that, so this row stays the serial arithmetic and says so: it is not multiplied
            # by a number of workers nobody has timed on a cluster.
            {"limit": SERIAL_PASS, "scope": "every customer of the public worker",
             "at": relayers * DAY / peak / (tokens * lat["median"]),
             "from": f"{tokens} tokens a deliverable, counted as carried one after another; a token taken as the median of merge-to-paid, "
                     f"{lat['median']} s (recorded on devnet when the sweep carried one token at a time; it includes the runner's start, so "
                     "the relay's own share is smaller and one relayer carries at least this many). The sweep now carries up to "
                     f"{c['relay']['tokens_at_a_time']} tokens at once, the tokens of one owner in order (section 6): what that adds is "
                     "not measured on devnet yet, so it is not counted here",
             "lift": "the job's own relay; or several relayers (anyone can run one: the chain takes each token once, whoever carries it)"},
        ]
    else:
        rows.append({"limit": "the fee key's own account", "scope": "each fee key",
                     "at": relayers * ch["one_relayer_orders_per_second"] * DAY / peak,
                     "from": f"{ch['one_relayer_orders_per_second']} orders a second for one key that pays the fees (derived by scripts/load.py)",
                     "lift": "a fee key per repository or per team (KNOS_RELAY_KEY is a repository secret)"})
    if "attest_eval" in c["counted"].get(OWN, {}):
        cap = c["meter"]["statement_reads_at_most"]
        rows.append({"limit": "the meter's statement, recomputed from the logs", "scope": "each buyer and seller, each month", "retrieval": True,
                     "at": cap / 30,
                     "from": f"`knos statement --meter` reads at most {cap:,} transactions of a month's account, one RPC request each "
                             f"(src/knos/settle/v2/meter.py); a 30-day month, one evaluation a deliverable, one transaction an evaluation. "
                             "Not a limit on the work: past it the month's account is still the count, and the recomputation from logs is cut short",
                     "lift": f"batching the meter: one RecordBatch token carries up to {c['meter']['evaluations_per_batch_at_most']:,} "
                             "evaluations under one Merkle root, so a month is a few transactions whatever its volume"})
    for r in rows:
        r["at"] = int(r["at"])
        r["load"] = round(per_day / r["at"], 4) if r["at"] else math.inf
        r["binds"] = per_day >= r["at"]
    return sorted(rows, key=lambda r: (r["at"], r["limit"]))


def answer(c: dict, repos: int, per_day: int, **kw) -> dict:
    """The model's answer for one customer: the limit on throughput that binds first, at what N, and whether this N is
    past it. A limit on reading the record back (`retrieval`) is listed among `binding` and never named `first`: past
    it the work is still done and counted, and what stops is one way of checking the count."""
    rows = bounds(c, repos, per_day, **kw)
    first = next(r for r in rows if not r.get("retrieval"))
    return {"repositories": repos, "per_day": per_day, "way": kw.get("way", OWN), "first": first["limit"], "at": first["at"],
            "fits": not first["binds"], "binding": [r["limit"] for r in rows if r["binds"]], "bounds": rows}


def workflow(c: dict | None = None) -> dict:
    """docs/load.json's `workflow` section: the constants, the per-order budget both ways, and the three customers."""
    c = constants() if c is None else c
    return {**c, "budget": {way: budget(c, way) for way in (OWN, PUBLIC)},
            "statement_requests": {str(n): {"one_by_one": statement_requests(n * 30),
                                            "batched_daily": statement_requests(n * 30, max(1, n))} for _r, n in SIZES},
            "customers": [answer(c, r, n, way=way) for r, n in SIZES for way in (OWN, PUBLIC)]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Which limit a customer meets first, from counted and published constants.")
    ap.add_argument("-R", "--repos", type=int, help="the customer's repositories")
    ap.add_argument("-N", "--per-day", type=int, help="accepted deliverables a day")
    ap.add_argument("--way", choices=(OWN, PUBLIC), default=OWN, help="who carries the tokens: the job's own relay, or Knos's public worker")
    ap.add_argument("--plan", choices=tuple(LIMITS["concurrent_jobs"]), default="Free", help="the GitHub plan (concurrent jobs)")
    ap.add_argument("--peak", type=float, default=1.0, help="how many times the mean hour the busiest hour is (1: even over the day)")
    ap.add_argument("--relayers", type=int, default=1)
    ap.add_argument("--write", action="store_true", help="count again and write docs/load.json's workflow section and docs/LOAD.md")
    a = ap.parse_args(argv)
    if a.write:
        import load
        doc = load.load()
        doc["workflow"] = workflow()
        load.write(doc)
        return 0
    if not (a.repos and a.per_day):
        ap.error("say -R and -N (a customer's repositories and accepted deliverables a day), or --write")
    doc = json.loads(JSON.read_text(encoding="utf-8"))
    c = doc.get("workflow") or constants()
    got = answer(c, a.repos, a.per_day, way=a.way, plan=a.plan, peak=a.peak, relayers=a.relayers)
    print(json.dumps(got, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
