#!/usr/bin/env python3
"""agent_pr_ci.py -- re-runnable market statistic for Knos.

Question: of PRs authored by AI coding agents whose PR body claims tests/CI
pass, what share had CI FAILING at the PR's head SHA?

Read-only: only `gh api -X GET` calls. Every answer GitHub would give again is cached under
~/.cache/knos-agent-pr-ci/ so reruns are cheap (a server error or a rate limit is not an answer and
is asked again); each invocation stops after --max-seconds and can be re-run to resume.

Usage (from this directory):
    py agent_pr_ci.py collect   # search phase (Search API, 30 req/min)
    py agent_pr_ci.py checks    # per-PR head SHA + checks (core API); then report
    py agent_pr_ci.py report    # writes docs/agent_pr_ci.json from cache, prints summary
Options: --end YYYY-MM-DD (window end; frozen in cache/config.json on first
run), --days 90, --windows 9, --per-window 20, --max-seconds 270
Delete ~/.cache/knos-agent-pr-ci/ to take a fresh sample (e.g. with a new --end).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "knos-agent-pr-ci")
DATA = os.path.join(HERE, "..", "docs", "agent_pr_ci.json")
START = time.time()
ARGS = None
SEARCH_PAUSE = 6
_SEARCH_LOCK = __import__("threading").Lock()
_SEARCH_LAST = [0.0]


def _search_slot():
    """Space search calls SEARCH_PAUSE apart across threads (one shared 30/min budget)."""
    with _SEARCH_LOCK:
        wait = _SEARCH_LAST[0] + SEARCH_PAUSE - time.time()
        if wait > 0:
            time.sleep(wait)
        _SEARCH_LAST[0] = time.time()

# ---- agent definitions (search qualifiers) --------------------------------
AGENTS = [
    ("copilot",     "author:app/copilot-swe-agent"),
    ("devin",       "author:app/devin-ai-integration"),
    ("claude-bot",  "author:app/claude"),
    ("claude-code", "\"Generated with Claude Code\" in:body -author:app/claude"),
    ("codex",       "\"chatgpt.com/codex/tasks\" in:body"),
]
# How each agent is told apart, and what that misses. Each qualifier returned pull requests when the committed sample
# was read on 2026-10-01 (docs/agent_pr_ci.json: 179, 180, 180, 180 and 114 hits). The vendors' own pages say where the
# heuristic stops: Devin can be set to open pull requests as the user (docs.devin.ai/integrations/gh), Claude Code's
# line is a setting a user can turn off, and since 16 July 2026 GitHub's API also returns Copilot's pull requests
# under `author:<the person who asked>` (github.blog/changelog/2026-06-18-copilot-authored-pull-requests-now-
# included-in-author-searches), which does not change the app qualifier used here.
HEURISTICS = {
    "copilot": {"told_by": "the pull request's author is the GitHub App `copilot-swe-agent` (GitHub Copilot's cloud agent)",
                "misses": "Copilot used in an editor or a terminal, which opens pull requests under the person's own account"},
    "devin": {"told_by": "the author is the GitHub App `devin-ai-integration` (Devin's default: it opens pull requests as itself)",
              "misses": "an organisation that set Devin to open pull requests as the user"},
    "claude-bot": {"told_by": "the author is the GitHub App `claude` (Claude Code run from GitHub: the Action, or an @claude mention)",
                   "misses": "an installation that runs the Action under its own app or a person's token"},
    "claude-code": {"told_by": "the description holds the line \"Generated with Claude Code\" and the author is not the app `claude` "
                               "(Claude Code run on a person's machine, under their account)",
                    "misses": "anyone who turned the line off in settings; a person who pastes the line is counted"},
    "codex": {"told_by": "the description holds a `chatgpt.com/codex/tasks` link (the task link Codex's cloud agent writes)",
              "misses": "Codex run locally, which writes no link; a person who pastes a task link is counted"},
}
CLAIM_SEARCH = ('("tests pass" OR "all tests pass" OR "tests passing" OR '
                '"CI passes" OR "CI is green" OR "CI passing") in:body')

# ---- claim detection (applied locally to the body) -------------------------
_PASS = r"(?:pass(?:es|ed|ing)?|green)"
CLAIM_RE = re.compile(
    r"(?:\ball\s+(?:\w+\s+){0,2}tests?\s+(?:are\s+|now\s+)*" + _PASS +      # all tests pass
    r"|\btests?\s+(?:are\s+|now\s+|still\s+)*" + _PASS + r"\b" +             # tests pass(ing)
    r"|\btests?\b[^\n.]{0,40}?\band\s+passing\b" +                           # tests added and passing
    r"|\bCI\b(?:[\s:/,]+(?:is|are|now|run|runs|job|jobs|checks?|build|pipeline|workflows?|all|CD|#?\d+))*[\s:,]+"
    + _PASS + r"\b" +                                                        # CI passes / CI job passing
    r"|\b(?:all\s+(?:CI\s+)?checks?|(?:CI\s+)?checks)\s+(?:are\s+|have\s+)?" + _PASS + r"\b" +  # all checks pass
    r"|\bpass(?:es|ed|ing)?\s+all\s+(?:\w+\s+){0,2}(?:tests|checks|CI)\b" +  # passes all CI checks
    r"|`[^`\n]*test[^`\n]*`\s*(?:[-:—]\s*)?(?:all\s+)?" + _PASS + r"\b" +  # `npm test` passes
    r"|\b\d[\d,]*\s*(?:/\s*\d[\d,]*\s*)?(?:\w+\s+){0,2}passed\b" +          # 1312 passed / 15/15 tests passed
    r"|✅\s*[^\n]{0,40}?\btests?\b"
    r"|\btests?\b[^\n]{0,30}?✅)", re.I)
# a matched line is NOT counted as a claim if it is an unchecked box (a task-list item of any marker: -, *, +, 1.,
# 1), nested or quoted) or a conditional / instruction / negation / partial-failure statement. src/knos/proof/claims.py
# reads the same words (_BOX, _HEDGE, _BOILER) and web/front.js is a copy: tests/test_agent_pr_index.py holds the three
# together.
NONCLAIM_RE = re.compile(
    r"^[ \t]*(?:>[ \t]*)*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)+\[ \](?:[ \t]|$)|"
    r"\b(ensure|make sure|verify that|should|would|will|to confirm|until|"
    r"once|if|before|whether|need|needs|must|expect|expected|todo|not|"
    r"fail|fails|failing|failed|failure|failures|errors?|except|unless|pending|flaky|skip|"
    r"red|broken)\b|n't\b", re.I)
# boilerplate that would otherwise trip NONCLAIM_RE on a checked template box
_BOILER_RE = re.compile(r"\*\*Your PR cannot be merged unless tests pass\*\*|"
                        r"\bfail[- ](?:closed|safe|fast|open)\b|\b0 failed\b", re.I)


def strip_body(body):
    b = body or ""
    b = re.sub(r"<!--.*?-->", " ", b, flags=re.S)
    # Copilot embeds the user's original prompt -- that is not the agent's claim
    b = re.sub(r"<details>\s*<summary>[^<]*(original prompt|original issue)[^<]*</summary>.*?</details>",
               " ", b, flags=re.S | re.I)
    return b


def find_claim(body):
    for line in strip_body(body).splitlines():
        m = CLAIM_RE.search(line)
        if not m:
            continue
        if NONCLAIM_RE.search(_BOILER_RE.sub(" ", line)):
            continue
        return m.group(0).strip(), line.strip()[:200]
    return None, None


# ---- gh wrapper with disk cache and backoff ---------------------------------
class OutOfTime(Exception):
    pass


class OutOfBudget(OutOfTime):
    """A bounded run has sent the requests it may send, or GitHub refused one for a rate limit it will not wait out."""


# A bounded run (agent_pr_index.py sample): the most requests it may send, how many it has sent, and whether a
# refusal for a rate limit ends the run (True) or is waited out (False, the unbounded scans).
MAX_REQUESTS = None
ASKED = [0]
NO_WAIT = False
STOPPED = [None]        # why a bounded run stopped early, in words: its minutes, its requests, or GitHub's refusal


def _stop(why, exc):
    """Raise `exc`, keeping the first reason a bounded run was given for stopping (STOPPED)."""
    if STOPPED[0] is None:
        STOPPED[0] = why
    raise exc()


def _spend():
    """Count one request about to be sent; a bounded run that has none left stops here, before sending it."""
    if time_left() < 15:
        _stop("its minutes were spent", OutOfTime)
    if MAX_REQUESTS is not None and ASKED[0] >= MAX_REQUESTS:
        _stop("its requests were spent", OutOfBudget)
    ASKED[0] += 1


def time_left():
    return ARGS.max_seconds - (time.time() - START)


# An answer GitHub will give again for the same request: the pull request, the commit or the repository is gone or
# blocked. Any other failure (a server error, no network, a rate limit) says nothing about the request: it is not
# kept, so the next run asks again.
_GONE = re.compile(r"HTTP (404|410|422|451)\b")
_NO_ANSWER = re.compile(r"HTTP 5\d\d|error connecting|connection re(set|fused)|timeout|timed out|\bEOF\b|TLS handshake|"
                        r"not JSON", re.I)


def _gh(cmd):
    """One `gh` call: (exit code, stdout, stderr). The only place the network is touched; the tests replace it."""
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    return p.returncode, p.stdout or "", p.stderr or ""


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _cached(fn, max_age):
    """The kept answer in `fn`, or None: no file, a file cut short by a killed run, or one older than `max_age`."""
    try:
        with open(fn, encoding="utf-8") as f:
            got = json.load(f)
        if max_age is not None and (_now() - dt.datetime.fromisoformat(got["fetched"])).total_seconds() > max_age:
            return None
        return got["resp"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _core_reset():
    """Seconds until the hourly core budget is back, when it is used up; None when it is not (the refusal was a
    secondary limit) or GitHub does not say. Reading rate_limit does not count against the budget."""
    code, out, _ = _gh(["gh", "api", "-X", "GET", "rate_limit"])
    try:
        core = json.loads(out)["resources"]["core"]
        return max(1, core["reset"] - time.time()) + 5 if code == 0 and not core["remaining"] else None
    except (ValueError, KeyError, TypeError):
        return None


def gh_get(path, params=None, kind="core", max_age=None):
    """GET `path` through `gh api`, answered from the disk cache when it has the answer (and, with `max_age`, the
    answer is at most that many seconds old). {"ok": True, "json": ...} or {"ok": False, "error": ...}; a failure
    that says nothing about the request also carries "transient": True and is not kept."""
    key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    h = hashlib.sha1(key.encode()).hexdigest()
    fn = os.path.join(CACHE, kind, h[:2], h + ".json")
    hit = _cached(fn, max_age)
    if hit is not None:
        return hit
    if time_left() < 15:
        _stop("its minutes were spent", OutOfTime)
    cmd = ["gh", "api", "-X", "GET", path, "-H", "Accept: application/vnd.github+json"]
    for k, v in (params or {}).items():
        cmd += ["-f", f"{k}={v}"]
    resp = None
    for attempt in range(6):
        _spend()
        if kind == "search":
            _search_slot()  # 30 req/min search limit; complex OR queries trip secondary limits faster
        code, out, err = _gh(cmd)
        if code == 0:
            try:
                body = json.loads(out or "null")
            except ValueError:
                code, out, err = 1, "", "the answer was cut off (not JSON)"
        if code == 0:
            if kind == "search" and isinstance(body, dict) and body.get("incomplete_results") and attempt < 2 and not NO_WAIT:
                time.sleep(5)   # GitHub ran out of time on the query and returned what it had: ask twice more, then
                continue        # take the page as it is (scan_agent counts it as cut short)
            resp = {"ok": True, "json": body}
            break
        err = err + out[:500]
        if re.search(r"rate limit|HTTP 429|secondary", err, re.I):
            if NO_WAIT:                 # a bounded run never sleeps on a limit: it stops and writes what it has
                limit = "a secondary rate limit" if re.search("secondary", err, re.I) else "a rate limit"
                _stop(f"GitHub refused a {kind} request for {limit}", OutOfBudget)
            wait = min(90, 20 * (attempt + 1))
            if kind == "core" and not re.search("secondary", err, re.I):
                wait = _core_reset() or wait   # the hourly budget is spent: it comes back at a known time, wait for it
            if time_left() < wait + 15:
                raise OutOfTime()
            print(f"  rate-limited, sleeping {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
            continue
        if _NO_ANSWER.search(err) and attempt < 3:
            time.sleep(5)
            continue
        resp = {"ok": False, "error": err.strip()[:300]}
        if kind == "search" or not _GONE.search(err):
            resp["transient"] = True
        break
    if resp is None:
        raise OutOfTime()
    if not resp.get("transient"):
        os.makedirs(os.path.dirname(fn), exist_ok=True)
        tmp = f"{fn}.{os.getpid()}.{__import__('threading').get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"key": key, "fetched": _now().isoformat(), "resp": resp}, f)
        os.replace(tmp, fn)   # in one step: a run killed here leaves the old answer or none, never half of one
    return resp


def prune(days):
    """Forget the answers read more than `days` days ago; returns how many. With `days` longer than the scan's window
    they are all about pull requests that have left it, so the cache a scheduled run carries stays one window large."""
    cutoff, gone = time.time() - days * 86400, 0
    for kind in ("core", "search"):
        for folder, _, names in os.walk(os.path.join(CACHE, kind)):
            for name in names:
                fn = os.path.join(folder, name)
                try:
                    if os.path.getmtime(fn) < cutoff:
                        os.remove(fn)
                        gone += 1
                except OSError:
                    pass
    return gone


# ---- config (frozen window so reruns reproduce) ------------------------------
def load_config():
    fn = os.path.join(CACHE, "config.json")
    if os.path.exists(fn):
        with open(fn) as f:
            return json.load(f)
    cfg = {"end": ARGS.end or dt.date.today().isoformat(), "days": ARGS.days,
           "windows": ARGS.windows, "per_window": ARGS.per_window,
           "first_run_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
    os.makedirs(CACHE, exist_ok=True)
    with open(fn, "w") as f:
        json.dump(cfg, f, indent=1)
    return cfg


def windows(cfg):
    end = dt.date.fromisoformat(cfg["end"])
    start = end - dt.timedelta(days=cfg["days"] - 1)
    step = cfg["days"] / cfg["windows"]
    out = []
    for i in range(cfg["windows"]):
        a = start + dt.timedelta(days=round(i * step))
        b = start + dt.timedelta(days=round((i + 1) * step)) - dt.timedelta(days=1)
        out.append((a.isoformat(), b.isoformat()))
    return out


def queries(cfg):
    for agent, qual in AGENTS:
        for a, b in windows(cfg):
            yield agent, f"is:pr {qual} created:{a}..{b} {CLAIM_SEARCH}"


# ---- phases -------------------------------------------------------------------
def collect(cfg):
    cands, seen = [], set()
    for agent, q in queries(cfg):
        r = gh_get("search/issues", {"q": q, "per_page": cfg["per_window"],
                                      "sort": "created", "order": "desc"}, kind="search")
        if not r["ok"]:
            print("search error:", q, r["error"], file=sys.stderr)
            continue
        for it in r["json"]["items"]:
            repo = it["repository_url"].split("/repos/")[1]
            k = f"{repo}#{it['number']}".lower()
            if k in seen:
                continue
            seen.add(k)
            phrase, ctx = find_claim(it.get("body"))
            cands.append({"agent": agent, "repo": repo, "number": it["number"],
                          "author": it["user"]["login"], "created_at": it["created_at"],
                          "phrase": phrase, "claim_line": ctx, "query": q})
    return cands


# check runs that are the agent's own session/job, not project CI
AGENT_RUN_RE = re.compile(
    r"^(copilot|claude|claude[-_ ]?(code|review|code[-_ ]review|pr[-_ ]review)|codex|devin)$", re.I)
FAIL_CONCL = {"failure", "timed_out", "startup_failure"}
OK_CONCL = {"success", "neutral", "skipped"}


def classify(c, max_age=None):
    """What CI said at the pull request's head commit. `max_age`: read GitHub again where the kept answer is older
    than that many seconds (a verdict that was not final when it was read)."""
    # the combined status of refs/pull/N/head names the head SHA: one core call fewer than GET pulls/N
    st = gh_get(f"repos/{c['repo']}/commits/refs/pull/{c['number']}/head/status", max_age=max_age)
    if not st["ok"]:
        return {"class": "error", "detail": st["error"][:120], "transient": bool(st.get("transient"))}
    sha = st["json"]["sha"]
    out = {"sha": sha}
    runs, page = [], 1
    while True:
        r = gh_get(f"repos/{c['repo']}/commits/{sha}/check-runs", {"per_page": 100, "page": page}, max_age=max_age)
        if not r["ok"]:
            out.update({"class": "error", "detail": r["error"][:120], "transient": bool(r.get("transient"))})
            return out
        runs += r["json"]["check_runs"]
        if len(r["json"]["check_runs"]) < 100 or page >= 5:
            break
        page += 1
    statuses = st["json"]["statuses"]
    suites = []
    if not runs and not statuses:  # only then can a suite awaiting approval change the verdict
        su = gh_get(f"repos/{c['repo']}/commits/{sha}/check-suites", {"per_page": 100}, max_age=max_age)
        suites = su["json"]["check_suites"] if su["ok"] else []

    out.update(verdict(runs, statuses, suites))
    return out


def verdict(runs, statuses, suites=()):
    """The class of a head commit from its check runs ({name, status, conclusion}), its commit statuses ({context,
    state}) and its check suites ({conclusion}), however they were read (REST below, GraphQL in read_rollup)."""
    agent_runs = [x for x in runs if AGENT_RUN_RE.match(x["name"].strip())]
    ci_runs = [x for x in runs if not AGENT_RUN_RE.match(x["name"].strip())]
    concl = [x["conclusion"] for x in ci_runs if x["status"] == "completed"]
    pending = [x for x in ci_runs if x["status"] != "completed"]
    st_states = [s["state"] for s in statuses]
    failed_names = [x["name"] for x in ci_runs if x["conclusion"] in FAIL_CONCL] + \
                   [s["context"] for s in statuses if s["state"] in ("failure", "error")]
    awaiting = [s for s in suites if s.get("conclusion") == "action_required"]
    out = {"n_check_runs": len(ci_runs), "n_agent_runs_excluded": len(agent_runs),
           "n_statuses": len(statuses), "failed_checks": failed_names[:10],
           "awaiting_approval_suites": len(awaiting)}
    if failed_names:
        cls = "failed"
    elif not ci_runs and not statuses:
        cls = "blocked-awaiting-approval" if awaiting else "no-ci"
    elif pending or "pending" in st_states:
        cls = "pending"
    elif all(x in OK_CONCL for x in concl) and all(s == "success" for s in st_states):
        cls = "passed"
    else:
        cls = "other"  # e.g. cancelled / action_required / stale -- no hard failure
    out["class"] = cls
    out["other_conclusions"] = sorted({x for x in concl if x not in OK_CONCL})
    return out


# ---- the same reading in one GraphQL request for many pull requests --------------------------------------------------
# `statusCheckRollup` on a Commit holds the commit's check runs and commit statuses together (`contexts`: CheckRun |
# StatusContext; docs.github.com/en/graphql/reference/objects#statuscheckrollup), so the head commit's checks, its
# check suites and the pull request's merge state come in one request for ROLLUP_BATCH pull requests, where REST takes
# three to four requests for each one. Cost (docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-
# the-graphql-api): the connections a query asks for, counted as requests and divided by 100. A batch of 20 asks 60
# (commits, contexts and checkSuites for each) and costs 1 point of the 1,000 an hour the Actions token has; it
# names at most 20 x (1 + 100 + 30) = 2,620 nodes of the 500,000 a query may. It is a query: it changes nothing.
ROLLUP_BATCH = 20
_SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")
_ROLLUP = ("p%d: repository(owner: %s, name: %s) { pullRequest(number: %d) { merged commits(last: 1) { nodes { commit { oid "
           "statusCheckRollup { contexts(first: 100) { pageInfo { hasNextPage } nodes { __typename "
           "... on CheckRun { name status conclusion } ... on StatusContext { context state } } } } "
           "checkSuites(first: 30) { nodes { conclusion } } } } } } }")


def rollup_query(cands):
    parts = []
    for i, c in enumerate(cands):
        owner, _, name = c["repo"].partition("/")
        if _SAFE.match(owner) and _SAFE.match(name):
            parts.append(_ROLLUP % (i, json.dumps(owner), json.dumps(name), int(c["number"])))
    return "query { " + " ".join(parts) + " }"


def gh_graphql(query):
    """One GraphQL query through `gh api graphql` (never kept on disk: the caller's checkpoint keeps what it reads).
    {"ok": True, "data", "errors"} when GitHub answered, also when it answered null for some of it; otherwise
    {"ok": False, "error", "transient"}: transient when the failure says nothing about the query."""
    _spend()
    code, out, err = _gh(["gh", "api", "graphql", "-f", f"query={query}"])
    try:
        body = json.loads(out or "null")
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return {"ok": True, "data": body["data"], "errors": body.get("errors") or []}
    text = (err + out[:500]).strip() or "no answer"
    if re.search(r"rate limit|HTTP 429|secondary", text, re.I):
        raise OutOfBudget()
    return {"ok": False, "error": text[:300], "transient": code == 0 or bool(_NO_ANSWER.search(text))}


def read_rollup(cands):
    """The verdict and merge state of each of `cands` from one GraphQL request. A list as long as `cands`: a dict
    like classify's with `merged`, or None for one this request did not settle (GitHub timed out on it, or it has
    more than 100 checks: the caller reads that one over REST). A whole request GitHub refuses comes back as
    {"ok": False, ...} for the caller to decide (try again, or read over REST from now on)."""
    got = gh_graphql(rollup_query(cands))
    if not got["ok"]:
        return got
    gone = {str(e.get("path", [""])[0]) for e in got["errors"] if e.get("type") == "NOT_FOUND"}
    out = []
    for i, c in enumerate(cands):
        pr = (got["data"].get(f"p{i}") or {}).get("pullRequest")
        nodes = ((pr or {}).get("commits") or {}).get("nodes") or []
        if not pr or not nodes:
            out.append({"class": "error", "detail": "the pull request or its repository is gone", "transient": False}
                       if f"p{i}" in gone or (pr and not nodes) else None)
            continue
        commit = nodes[0]["commit"]
        contexts = (commit.get("statusCheckRollup") or {}).get("contexts") or {}
        if (contexts.get("pageInfo") or {}).get("hasNextPage"):
            out.append(None)
            continue
        low = lambda v: str(v or "").lower() or None  # noqa: E731
        runs = [{"name": x.get("name") or "", "status": low(x.get("status")), "conclusion": low(x.get("conclusion"))}
                for x in contexts.get("nodes") or [] if x and x.get("__typename") == "CheckRun"]
        statuses = [{"context": x.get("context") or "", "state": {"expected": "pending"}.get(low(x.get("state")), low(x.get("state")))}
                    for x in contexts.get("nodes") or [] if x and x.get("__typename") == "StatusContext"]
        suites = [{"conclusion": low(x.get("conclusion"))} for x in (commit.get("checkSuites") or {}).get("nodes") or [] if x]
        out.append({"sha": commit.get("oid"), **verdict(runs, statuses, suites), "merged": bool(pr.get("merged"))})
    return out


# A verdict that can still change: CI has not finished, has not started, or waits for a maintainer's approval. The
# answers behind it are kept on disk like any other, so a later run would repeat it for ever; instead it is read
# again once it is RECHECK_AFTER old, for as long as the pull request is RECHECK_DAYS young.
UNSETTLED = ("pending", "no-ci", "blocked-awaiting-approval")
RECHECK_AFTER = 5 * 3600
RECHECK_DAYS = 14


def _young(c, now=None):
    try:
        made = dt.datetime.fromisoformat(str(c.get("created_at", "")).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (now or _now()) - made < dt.timedelta(days=RECHECK_DAYS)


def run_checks(cands, workers=8):
    """Classify every claimed PR; 8 concurrent gh processes (core API only)."""
    from concurrent.futures import ThreadPoolExecutor
    todo = [c for c in cands if c["phrase"]]

    def one(c):
        try:
            got = classify(c)
            if got.get("class") in UNSETTLED and _young(c):
                got = classify(c, max_age=RECHECK_AFTER)
            c.update(got)
            return True
        except OutOfTime:
            return False

    with ThreadPoolExecutor(max_workers=workers) as ex:
        ok = list(ex.map(one, todo))
    if not all(ok):
        print(f"out of time: {sum(ok)}/{len(ok)} PRs classified; re-run to resume", file=sys.stderr)
        return False
    return True


# ---- scan: the >=2,000-PR market sample (search pages x date windows x agents) ---------------
def excluded_self(item):
    """True when the PR sits on a repo its author owns, or one owned by the human who triggered the agent (an
    assignee, when GitHub records one): an agent grading its owner's own repo is not a market observation."""
    owner = item["repository_url"].split("/repos/")[1].split("/")[0].lower()
    people = {item["user"]["login"].lower()} | {a["login"].lower() for a in item.get("assignees") or []}
    return owner in people


def scan_windows(end, days, width):
    """Newest-first [a, b] date windows of at most `width` days covering exactly the `days` days ending at `end`.

    The windows are cut at fixed calendar boundaries (every `width` days, counted from day 1), not counted back from
    `end`. So when `end` moves on by a day, every window but the newest and the oldest is the same query as the day
    before: its search pages and the verdicts behind them are already on disk, and a scheduled run has only the new
    day's pull requests to read. Counted back from `end`, every window moved every day and every run started again."""
    last = dt.date.fromisoformat(end)
    first = last - dt.timedelta(days=days - 1)
    out, b = [], last
    while b >= first:
        a = max(first, dt.date.fromordinal(b.toordinal() - b.toordinal() % width))
        out.append((a.isoformat(), b.isoformat()))
        b = a - dt.timedelta(days=1)
    return out


# window width (days) per agent so one query stays under GitHub's 1,000-result cap at recent volumes
SCAN_WIDTH = {"copilot": 5, "devin": 1, "claude-bot": 5, "claude-code": 1, "codex": 10}


NO_CLAIM = []   # [agent, created_at] of every search hit whose description, read closely, claims nothing (list.append is atomic)


SPLIT_FLOOR = 3600   # seconds: a span is not cut finer than an hour; one still over the cap is read to it and counted


def _span(a, b):
    """(first second, last second) of the days a..b, UTC."""
    lo = dt.datetime.fromisoformat(a).replace(tzinfo=dt.timezone.utc)
    return lo, dt.datetime.fromisoformat(b).replace(tzinfo=dt.timezone.utc) + dt.timedelta(days=1, seconds=-1)


def created(lo, hi):
    """The `created:` qualifier of a span: whole days as dates (the query a run of any earlier version asked, so its
    answer is on disk), a part of a day to the second."""
    whole = lo.time() == dt.time(0) and hi.time() == dt.time(23, 59, 59)
    f = (lambda t: t.date().isoformat()) if whole else (lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ"))
    return f"created:{f(lo)}..{f(hi)}"


def halves(lo, hi):
    """The span cut in two, newest half first; None when it is already at most SPLIT_FLOOR long."""
    size = int((hi - lo).total_seconds()) + 1
    if size <= SPLIT_FLOOR:
        return None
    mid = lo + dt.timedelta(seconds=size // 2)
    return [(mid, hi), (lo, mid - dt.timedelta(seconds=1))]


def scan_agent(agent, qual, end, days, per_agent, width=None):
    """One agent's windows, newest first, up to 10 pages of 100 each, until `per_agent` claimed, non-self-repo PRs are
    kept. GitHub answers a query with at most 1,000 results: a window whose first page says it holds more is cut in
    two (down to an hour) and each half is asked by itself, so a busy day is read whole. Returns (kept, counts,
    finished): `finished` is False when a query was refused or the time ran out, so what was kept is the newest part
    of the sample and not all of it. counts["capped"]: hour-long spans that still held more than 1,000."""
    kept, seen, n = [], set(), {"hits": 0, "excluded": 0, "no_claim": 0, "cut_short": 0, "capped": 0}
    todo = [_span(a, b) for a, b in scan_windows(end, days, width or SCAN_WIDTH.get(agent, 3))][::-1]   # a stack: newest on top
    while todo:
        lo, hi = todo.pop()
        q = f"is:pr {qual} {created(lo, hi)} {CLAIM_SEARCH}"
        for page in range(1, 11):
            if len(kept) >= per_agent:
                return kept, n, True
            try:
                r = gh_get("search/issues", {"q": q, "per_page": 100, "page": page,
                                              "sort": "created", "order": "desc"}, kind="search")
            except OutOfTime:
                print(f"out of time searching {agent}: {created(lo, hi)} page {page}", file=sys.stderr)
                return kept, n, False
            if not r["ok"]:
                print("search error:", q, r["error"], file=sys.stderr)
                return kept, n, False
            items = r["json"]["items"]
            if page == 1 and (r["json"].get("total_count") or 0) > 1000:
                cut = halves(lo, hi)
                if cut:
                    todo += cut[::-1]      # the newest half is read next; this page's hits come again in it
                    break
                n["capped"] += 1           # an hour with more than 1,000: its newest 1,000 are read, and the count says so
            n["cut_short"] += bool(r["json"].get("incomplete_results"))   # a page GitHub ran out of time on
            for it in items:
                repo = it["repository_url"].split("/repos/")[1]
                k = f"{repo}#{it['number']}".lower()
                if k in seen or len(kept) >= per_agent:
                    continue
                seen.add(k)
                n["hits"] += 1
                if excluded_self(it):
                    n["excluded"] += 1
                    continue
                phrase, ctx = find_claim(it.get("body"))
                if not phrase:
                    n["no_claim"] += 1
                    NO_CLAIM.append([agent, it["created_at"]])   # when it was opened: the weekly series counts it as sampled
                    continue
                kept.append({"agent": agent, "repo": repo, "number": it["number"],
                             "author": it["user"]["login"], "created_at": it["created_at"],
                             "phrase": phrase, "claim_line": ctx})
            if len(items) < 100:
                break
    return kept, n, True


def scan_collect(end, days, per_agent, width=None):
    """All agents concurrently (the search limit is shared; gh_get backs off on it). A PR found under two agents'
    queries counts once, for the first agent listed. Returns (kept, counts, unfinished): the agents whose search did
    not finish. What the others found is kept either way."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=len(AGENTS)) as ex:
        res = list(ex.map(lambda aq: scan_agent(aq[0], aq[1], end, days, per_agent.get(aq[0], 0)
                                                    if isinstance(per_agent, dict) else per_agent, width), AGENTS))
    kept, seen, n = [], set(), {"hits": 0, "excluded": 0, "no_claim": 0, "cut_short": 0, "capped": 0}
    for rows, cnt, _ in res:
        for k in n:
            n[k] += cnt[k]
        for r in rows:
            key = f"{r['repo']}#{r['number']}".lower()
            if key not in seen:
                seen.add(key)
                kept.append(r)
    return kept, n, [name for (name, _), (_, _, finished) in zip(AGENTS, res) if not finished]

CLASSES = ["failed", "passed", "other", "pending", "no-ci", "blocked-awaiting-approval", "error"]


# Sensitivity variant: a failure counts as a "test/build" failure only if at
# least one failed check's name looks like test/build/lint CI and not like a
# deploy preview, policy/label/metadata gate, review bot or security scanner.
TESTISH_RE = re.compile(r"test|build|compil|\bci\b|unit|integration|e2e|pytest|jest|vitest|lint|"
                        r"clippy|rustfmt|fmt|typecheck|tsc|linux|windows|macos|ubuntu|cargo|"
                        r"gradle|maven|mvn|smoke|julia|python|node|run:|benchmark|analy[sz]e", re.I)
ANCILLARY_RE = re.compile(r"vercel|netlify|cloudflare|workers builds|deploy|publish|label|\bcla\b|"
                          r"metadata|commitlint|contributor|review|lighthouse|snyk|codecov|sonar|"
                          r"security|audit|title|changelog|governance|evidence|non-empty|gate|"
                          r"lifecycle|compliance|aegis|ci-success", re.I)


def is_testish_failure(r):
    return any(TESTISH_RE.search(n) and not ANCILLARY_RE.search(n) for n in (r.get("failed_checks") or []))


def summarize(rows):
    cnt = {k: sum(1 for r in rows if r.get("class") == k) for k in CLASSES}
    cnt["failed_testish"] = sum(1 for r in rows if r.get("class") == "failed" and is_testish_failure(r))
    cnt["unchecked"] = sum(1 for r in rows if "class" not in r)
    with_ci = cnt["failed"] + cnt["passed"] + cnt["other"]  # completed CI verdicts
    cnt["N"] = len(rows)
    cnt["with_completed_ci"] = with_ci
    cnt["share_failed_among_completed_ci"] = round(cnt["failed"] / with_ci, 4) if with_ci else None
    cnt["share_failed_among_all"] = round(cnt["failed"] / len(rows), 4) if rows else None
    cnt["share_testish_failed_among_completed_ci"] = (round(cnt["failed_testish"] / with_ci, 4)
                                                      if with_ci else None)
    return cnt


def one_per_repo(rows):
    """Earliest-created claimed PR per repo (robustness to repo concentration)."""
    best = {}
    for r in sorted(rows, key=lambda r: r["created_at"]):
        best.setdefault(r["repo"].lower(), r)
    return list(best.values())


def report(cfg, cands):
    q = [c for c in cands if c["phrase"]]
    summary = {"all": summarize(q)}
    for a, _ in AGENTS:
        summary[a] = summarize([c for c in q if c["agent"] == a])
    rates = [summary[a]["share_failed_among_completed_ci"] for a, _ in AGENTS
             if summary[a]["share_failed_among_completed_ci"] is not None]
    summary["agent_balanced_mean_share_failed"] = round(sum(rates) / len(rates), 4) if rates else None
    summary["one_pr_per_repo"] = summarize(one_per_repo(q))
    summary["n_distinct_repos"] = len({c["repo"].lower() for c in q})
    out = {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "config": cfg,
           "search_windows": windows(cfg), "agents": AGENTS, "claim_search": CLAIM_SEARCH,
           "claim_regex": CLAIM_RE.pattern, "nonclaim_regex": NONCLAIM_RE.pattern,
           "n_search_hits": len(cands), "n_with_claim": len(q), "summary": summary,
           "prs": [{k: c.get(k) for k in ("agent", "repo", "number", "author", "created_at",
                                          "pr_state", "merged", "sha", "phrase", "claim_line",
                                          "class", "failed_checks", "other_conclusions",
                                          "n_check_runs", "n_statuses", "n_agent_runs_excluded",
                                          "awaiting_approval_suites", "detail")} for c in q],
           "rejected_no_claim": [{"agent": c["agent"], "repo": c["repo"], "number": c["number"]}
                                 for c in cands if not c["phrase"]]}
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print(json.dumps(summary, indent=1))


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["collect", "checks", "report"])
    ap.add_argument("--end")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--windows", type=int, default=9)
    ap.add_argument("--per-window", type=int, default=20)
    ap.add_argument("--max-seconds", type=int, default=270)
    ARGS = ap.parse_args()
    cfg = load_config()
    try:
        cands = collect(cfg)
    except OutOfTime:
        print("out of time during search; re-run to resume", file=sys.stderr)
        return 2
    print(f"search hits: {len(cands)}, with claim: {sum(1 for c in cands if c['phrase'])}",
          file=sys.stderr)
    if ARGS.phase == "collect":
        return 0
    if ARGS.phase == "checks":
        if not run_checks(cands):
            return 2
    else:  # report: classify from cache only
        ARGS.max_seconds = 0
        run_checks(cands)
    report(cfg, cands)
    return 0


if __name__ == "__main__":
    sys.exit(main())
