#!/usr/bin/env python3
"""backtest.py -- merged agent pull requests that said tests pass while a check had failed.

A Knos bounty pays a merged pull request only when every check its terms require passed at the head commit
(src/knos/terms.py). So, of the agent pull requests that said tests or CI pass and were merged anyway, how many had
a failed check at the head commit? A bounty that required that check would not have paid the merge; which checks a
bounty would have required is not in this data, since none of these pull requests had one. Same agents, claim
patterns and CI verdict as the Agent PR Index (agent_pr_ci.py, agent_pr_index.py), and the same two counts under the
same names.

    python scripts/backtest.py                                  # docs/backtest.json from docs/agent_pr_ci.json
    python scripts/backtest.py --index index.json               # and from a published index, where merges are known
    python scripts/backtest.py fetch --index index.json --pulls pulls.json    # read them from GitHub (needs gh)
    python scripts/backtest.py --index index.json --pulls pulls.json          # then: the whole index, with times
    python scripts/backtest.py --check                          # the method is frozen and docs/backtest.json is current

The recorded counts are read again by hand: docs/index_review.json says, for each merged pull request with a failed
check, what its page showed on a second reading and whether it stays counted (rules R1-R5 in docs/INDEX_METHOD.md).
`reviewed` in the output holds the counts after that reading; the recorded ones stay beside them. The method is
version 1: METHODS holds its sha256, and --check fails if docs/INDEX_METHOD.md changes without a new version.

What the data in the repository has: docs/agent_pr_ci.json (the 1 Oct 2026 sample) says for each pull request whether
it was merged when it was read, and when it was created; not when it was closed. index.json lists no merge state at
all. `fetch` reads both from GitHub (GET /repos/{repo}/pulls/{number}: merged, created_at, closed_at, merged_at) for
every pull request an index lists, through the same disk cache, and a run that is stopped continues where it was.
The output says, in `cannot_show`, what it could not work out from what it was given.
"""
import argparse
import datetime as dt
import hashlib
import re
import json
import os
import statistics
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_pr_ci  # noqa: E402
import agent_pr_index  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "docs", "agent_pr_ci.json")
OUT = os.path.join(ROOT, "docs", "backtest.json")
REVIEW = os.path.join(ROOT, "docs", "index_review.json")
NEGATIVES = os.path.join(ROOT, "docs", "index_reread_negatives.json")
METHOD = os.path.join(ROOT, "docs", "INDEX_METHOD.md")
# Each version of the method and the sha256 of docs/INDEX_METHOD.md at that version. A new version is a new line here.
METHODS = {1: "8502cc17977108607d404737696a62cb6e69fa9c535beedce1abd3a61fa5dbfb"}
# The expressions the method quotes, as the code holds them: --check finds each, verbatim, in the method file.
QUOTED = ("CLAIM_RE", "NONCLAIM_RE", "_BOILER_RE", "AGENT_RUN_RE", "TESTISH_RE", "ANCILLARY_RE")

DEFINITIONS = {
    "prs": "pull requests by the listed AI coding agents whose description says tests or CI pass, whose CI had "
           "finished at the head commit when it was read, and whose merge state is known",
    "merged": "of those, the ones that had been merged when they were read; the counts under it are over these",
    "any_check_failed": agent_pr_index.DEFINITIONS["any_check_failed"] + ". A Knos bounty whose terms require a check "
                        "that failed does not pay such a merge",
    "test_or_build_check_failed": agent_pr_index.DEFINITIONS["test_or_build_check_failed"],
    "cancelled_no_failure": "no failed check, but one that was cancelled, waits for a maintainer's approval or went "
                            "stale (the index's class `other`). A Knos bounty that requires such a check counts it "
                            "as failed; they are not in any_check_failed",
    "fate": "what had become of the pull requests when they were read, with a failed check and without one: merged, "
            "closed without a merge, or still open",
    "time_open": "hours from a pull request's creation to its merge or close, for those that were closed, with a "
                 "failed check and without one; those still open are counted, not timed",
    "share, ci95": "the count over its total, and the 95% Wilson interval of that share",
}


def _key(r):
    return f"{r['repo']}#{r['number']}".lower()


def _when(text):
    return dt.datetime.fromisoformat(str(text).replace("Z", "+00:00")) if text else None


def _state(r):
    """merged | closed_unmerged | open, or None when the row does not say."""
    if r.get("merged") is None and not r.get("merged_at"):
        return None
    if r.get("merged") or r.get("merged_at"):
        return "merged"
    state = r.get("state") or r.get("pr_state")
    return "open" if state == "open" else "closed_unmerged" if state == "closed" or r.get("closed_at") else None


def _failed(r):
    return agent_pr_index.FAILED["any_check_failed"](r)


def time_open(rows):
    """Hours from creation to merge or close, with a failed check and without; None when no row says when it closed."""
    def hours(r):
        made, done = _when(r.get("created_at")), _when(r.get("merged_at") or r.get("closed_at"))
        return (done - made).total_seconds() / 3600 if made and done else None

    if not any(hours(r) is not None for r in rows):
        return None
    out = {}
    for name, mine in (("any_check_failed", [r for r in rows if _failed(r)]), ("no_check_failed", [r for r in rows if not _failed(r)])):
        took = sorted(h for h in map(hours, mine) if h is not None)
        cut = statistics.quantiles(took, n=4, method="inclusive") if len(took) > 1 else took * 3
        out[name] = {"prs": len(mine), "closed": len(took), "still_open": sum(1 for r in mine if _state(r) == "open"),
                     "median_hours": round(cut[1], 1) if took else None,
                     "quartile_hours": [round(cut[0], 1), round(cut[2], 1)] if took else None}
    return out


def backtest(rows):
    """rows: classified pull requests with a claim. Those with finished CI and a known merge state are counted."""
    known = [r for r in rows if r.get("class") in agent_pr_index.COMPLETED and _state(r)]
    merged = [r for r in known if _state(r) == "merged"]

    def over(mine):
        k = sum(1 for r in mine if r["class"] == "other")
        return {**agent_pr_index.counts(mine, "prs"),
                "cancelled_no_failure": {"prs": k, "share": round(k / len(mine), 4) if mine else None,
                                         "ci95": agent_pr_index.wilson(k, len(mine))}}

    fate = {}
    for name, mine in (("any_check_failed", [r for r in known if _failed(r)]), ("no_check_failed", [r for r in known if not _failed(r)])):
        fate[name] = {"prs": len(mine), **{s: sum(1 for r in mine if _state(r) == s) for s in ("merged", "closed_unmerged", "open")}}
        fate[name]["merged_share"] = round(fate[name]["merged"] / len(mine), 4) if mine else None
        fate[name]["merged_ci95"] = agent_pr_index.wilson(fate[name]["merged"], len(mine))
    return {"prs": len(known),
            "merged": {"overall": over(merged),
                       "agents": {name: over([r for r in merged if r["agent"] == name]) for name, _ in agent_pr_ci.AGENTS}},
            "fate": fate, "time_open": time_open(known)}


def _author_owned(r):
    return r["repo"].split("/")[0].lower() == str(r.get("author") or "").lower()


def from_sample(sample):
    """The 1 Oct 2026 sample (docs/agent_pr_ci.json): every pull request has `merged` and `pr_state`."""
    rows = sample["prs"]
    created = sorted(r["created_at"][:10] for r in rows)
    done = [r for r in rows if r.get("class") in agent_pr_index.COMPLETED]
    return {"source": "docs/agent_pr_ci.json", "read": sample["generated_utc"][:10], "created": [created[0], created[-1]],
            "claimed_prs": len(rows), "with_finished_ci": len(done), **backtest(rows),
            # the index leaves out repositories the author (or the person who assigned the agent) owns; this sample
            # did not. Who assigned an agent is not in it, so only the author's own repositories can be taken out.
            "without_author_owned_repos": backtest([r for r in rows if not _author_owned(r)])}


def from_index(index, pulls=None, sample=None):
    """A published index. Its records carry no merge state: it comes from `pulls` (backtest.py fetch) or, failing
    that, from the sample for the pull requests that are in both."""
    states = pulls if pulls is not None else {_key(r): {"merged": r["merged"], "state": r["pr_state"], "created_at": r["created_at"]}
                                              for r in (sample or {}).get("prs", [])}
    rows = [{**r, **states[_key(r)]} for r in index["prs"] if _key(r) in states and "error" not in states[_key(r)]]
    return {"source": "index.json", "date": index["date"], "window": index["window"], "root": index["root"],
            "listed_prs": index["n_prs"], "merge_state_known": len(rows),
            "merge_state_from": "GitHub (backtest.py fetch)" if pulls is not None else "docs/agent_pr_ci.json, for the pull requests in both",
            **backtest(rows)}


def cannot_show(out):
    """What this run could not work out, from what it was given. Each line says what is missing."""
    lines = []
    index = out.get("index")
    if out["sample"]["time_open"] is None and not (index and index["time_open"]):
        lines.append("How long pull requests stayed open: docs/agent_pr_ci.json records when each was created and "
                     "whether it was open, closed or merged when it was read, not when it was closed or merged, and "
                     "index.json records neither. `backtest.py fetch` reads those times from GitHub")
    if index and index["merge_state_known"] < index["listed_prs"]:
        lines.append(f"The merges of the whole index: index.json lists no merge state. It is known for "
                     f"{index['merge_state_known']:,} of its {index['listed_prs']:,} pull requests "
                     f"({index['merge_state_from']})")
    if not index:
        lines.append("Anything about the published index: this run was not given one (--index index.json)")
    lines += ["Whether the check was failing at the moment of the merge: CI was read at the head commit on the day "
              "of the scan. A check re-run later shows its last result, and a check can fail after a merge",
              "Why a check failed, or whether the maintainer saw it: a failed check is GitHub's record, not a "
              "judgment. any_check_failed counts deploy previews and label gates; test_or_build_check_failed "
              "is decided from check names",
              "Agent pull requests in general: these are pull requests whose description claims tests or CI pass, the "
              "newest per agent and date window that GitHub's search returned, not a random sample",
              "What a bounty would have changed: none of these pull requests had one, so which checks its terms would "
              "have required is not known. This counts merges with a failed check, not payments refused"]
    return lines


def fetch(index, max_seconds, get=None):
    """Merge state and times of every pull request the index lists, from GitHub: {"repo#number": {...}}. Answers are
    kept on disk (agent_pr_ci's cache); a pull request still open is asked again after a day."""
    agent_pr_ci.ARGS = SimpleNamespace(max_seconds=max_seconds)
    get = get or agent_pr_ci.gh_get
    out, left = {}, 0
    for r in index["prs"]:
        try:
            got = get(f"repos/{r['repo']}/pulls/{r['number']}")
            if got["ok"] and got["json"].get("state") == "open":
                got = get(f"repos/{r['repo']}/pulls/{r['number']}", max_age=86400)
        except agent_pr_ci.OutOfTime:
            left += 1
            continue
        if not got["ok"]:
            if not got.get("transient"):
                out[_key(r)] = {"error": got["error"][:120]}      # deleted, or its repository is gone
            else:
                left += 1
            continue
        pr = got["json"]
        out[_key(r)] = {"merged": bool(pr.get("merged_at")), "state": pr.get("state"), "created_at": pr.get("created_at"),
                        "closed_at": pr.get("closed_at"), "merged_at": pr.get("merged_at")}
    return out, left


def method(path=METHOD):
    """{"version", "file", "sha256"} of the method file, and the problems --check reports (empty when it holds)."""
    with open(path, "rb") as f:
        raw = f.read()
    cut = raw.find(DRAFT)
    raw = raw if cut < 0 else raw[:cut]                 # the frozen version 1 text ends where the draft begins
    text, digest = raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()
    m = re.search(r"(?m)^Version: (\d+)$", text)
    version = int(m.group(1)) if m else None
    problems = []
    if version not in METHODS:
        problems.append(f"docs/INDEX_METHOD.md names version {version}, which METHODS in scripts/backtest.py does not list")
    elif METHODS[version] != digest:
        problems.append(f"docs/INDEX_METHOD.md changed (sha256 {digest[:12]}) but still says version {version}, frozen at "
                        f"{METHODS[version][:12]}: a change of method is a new version")
    problems += [f"docs/INDEX_METHOD.md does not quote {name} as scripts/agent_pr_ci.py holds it"
                 for name in QUOTED if getattr(agent_pr_ci, name).pattern not in text]
    return {"version": version, "file": "docs/INDEX_METHOD.md", "sha256": digest}, problems


def reviewed(sample, review):
    """The recorded counts after the second reading: a merged pull request the review excludes leaves the numerators;
    the denominator stays (the pull requests with no failed check were not read again)."""
    rows = [r for r in sample["prs"] if r.get("class") in agent_pr_index.COMPLETED and _state(r) == "merged"]
    read = {p["pr"].lower(): p for p in review["prs"]}
    failed = {_key(r) for r in rows if _failed(r)}
    if failed != set(read):
        raise SystemExit(f"docs/index_review.json reads {len(read)} pull requests; the sample has {len(failed)} merged with a "
                         f"failed check: {sorted(failed ^ set(read))[:5]}")
    kept = {k for k, p in read.items() if p["decision"] == "counted"}
    plain = {k for k in kept if not p_template(read[k])}

    def over(mine):
        n = len(mine)

        def one(keys, strict):
            k = sum(1 for r in mine if _key(r) in keys and (not strict or agent_pr_index.FAILED["test_or_build_check_failed"](r)))
            return {"prs": k, "share": round(k / n, 4) if n else None, "ci95": agent_pr_index.wilson(k, n)}
        return {"prs": n, "test_or_build_check_failed": one(kept, True), "any_check_failed": one(kept, False),
                "without_template_boxes": {"test_or_build_check_failed": one(plain, True), "any_check_failed": one(plain, False)}}

    excluded: dict = {}
    for p in review["prs"]:
        for rule in p["rules"] if p["decision"] == "excluded" else ():
            excluded[rule] = excluded.get(rule, 0) + 1
    return {"source": "docs/index_review.json", "read": review["read"], "method_version": review["method_version"],
            "reread": len(read), "kept": len(kept), "excluded": len(read) - len(kept), "excluded_by_rule": dict(sorted(excluded.items())),
            "overall": over(rows), "agents": {name: over([r for r in rows if r["agent"] == name]) for name, _ in agent_pr_ci.AGENTS}}


def p_template(p):
    return bool(p["read"].get("template_box"))


# ---- version 2 (draft): the funnel, intervals clustered by repository, the re-read of the negatives ------------------
# Version 1 stays frozen: method() hashes docs/INDEX_METHOD.md only up to DRAFT, where the version 2 draft begins.
DRAFT = b"\n## Version 2 (draft"
SEED = 20261010           # one seed for the cluster bootstrap and the re-read sample, written down before either ran
RESAMPLES = 2000


def _merged_rows(sample):
    return sorted((r for r in sample["prs"] if r.get("class") in agent_pr_index.COMPLETED and _state(r) == "merged"), key=_key)


def _strict_kept(sample, review):
    """The merged rows, and the keys of those in the reviewed strict count (the lead) and the reviewed any count."""
    rows = _merged_rows(sample)
    kept = {p["pr"].lower() for p in review["prs"] if p["decision"] == "counted"}
    strict = {_key(r) for r in rows if _key(r) in kept and agent_pr_index.FAILED["test_or_build_check_failed"](r)}
    return rows, strict, {_key(r) for r in rows if _key(r) in kept}


def funnel(sample, review):
    """Every step from the search to the lead number, each with its count and its share of the step before."""
    rows, strict, kept = _strict_kept(sample, review)
    done = [r for r in sample["prs"] if r.get("class") in agent_pr_index.COMPLETED]
    failed = [r for r in rows if _failed(r)]
    steps = [("searched", sample.get("n_search_hits"), "search hits GitHub returned for the five agents and the claim words"),
             ("claimed", len(sample["prs"]), "a line of the description says tests or CI pass (the claim)"),
             ("finished_ci", len(done), "CI had finished at the head commit when read"),
             ("merged", len(rows), "merged when read: the denominator"),
             ("any_check_failed", len(failed), "merged with a failed check of any kind (recorded scan)"),
             ("reread_kept", len(kept), "still counted after the second reading of those (rules R1-R5)"),
             ("strict", len(strict), "of those, a test, build, lint or type check failed: the lead number")]
    out, before = [], None
    for name, n, says in steps:
        if n is None:
            continue                                    # a sample that does not record its search hits
        out.append({"step": name, "prs": n, "of_previous": round(n / before, 4) if before else None, "means": says})
        before = n
    return out


def _repo(r):
    return r["repo"].lower()


def clustered(rows, hits, seed=SEED, resamples=RESAMPLES):
    """A share whose pull requests come in groups by repository. Beside the Wilson interval (which treats every pull
    request as independent): the design effect from the between-repository variance of a ratio estimate, the Wilson
    interval on the effective sample size n / design effect (never above n), and a percentile interval from
    resampling whole repositories with a fixed seed."""
    import random
    n, k = len(rows), sum(1 for r in rows if _key(r) in hits)
    if not n:
        return None
    groups: dict = {}
    for r in rows:
        m, y = groups.get(_repo(r), (0, 0))
        groups[_repo(r)] = (m + 1, y + (_key(r) in hits))
    g, p = len(groups), k / n
    var_c = g / (g - 1) * sum((y - p * m) ** 2 for m, y in groups.values()) / (n * n) if g > 1 else 0.0
    var_i = p * (1 - p) / n
    deff = max(1.0, var_c / var_i) if var_i else 1.0
    n_eff = n / deff
    rng, sizes = random.Random(seed), list(groups.values())
    shares = []
    for _ in range(resamples):
        pick = rng.choices(sizes, k=g)
        shares.append(sum(y for _, y in pick) / sum(m for m, _ in pick))
    shares.sort()
    hit_repos = [repo for repo, (_, y) in groups.items() if y]
    return {"prs": k, "of": n, "repositories": g, "repositories_with_one": len(hit_repos),
            "most_from_one_repository": max((y for _, y in groups.values()), default=0),
            "wilson_ci95": agent_pr_index.wilson(k, n),
            "design_effect": round(deff, 3), "effective_n": round(n_eff, 1),
            "clustered_wilson_ci95": agent_pr_index.wilson(p * n_eff, n_eff),
            "cluster_bootstrap_ci95": [round(shares[int(0.025 * resamples)], 4), round(shares[int(0.975 * resamples) - 1], 4)],
            "bootstrap": {"seed": seed, "resamples": resamples}}


def reread_draw(sample, review, seed=SEED, negatives=20, controls=5):
    """The sample for the blind re-read: `negatives` of the merged pull requests outside the strict count, and
    `controls` from inside it, shuffled together. The same seed always gives the same list."""
    import random
    rows, strict, _ = _strict_kept(sample, review)
    rng = random.Random(seed)
    neg = rng.sample([r for r in rows if _key(r) not in strict], negatives)
    ctl = rng.sample([r for r in rows if _key(r) in strict], controls)
    mix = neg + ctl
    rng.shuffle(mix)
    return [{"pr": f"{r['repo']}#{r['number']}", "role": "negative" if r in neg else "control"} for r in mix]


def reread(sample, review, record):
    """The re-read of the negatives, summed. Refused when the list is not the seeded draw."""
    want = reread_draw(sample, review, record["seed"], record["negatives"], record["controls"])
    got = [{"pr": p["pr"], "role": p["role"]} for p in record["prs"]]
    if sorted(map(str, got)) != sorted(map(str, want)):
        raise SystemExit("docs/index_reread_negatives.json is not the sample its seed draws: the re-read must use the seeded draw")
    out = {"read": record["read"], "seed": record["seed"]}
    for role in ("negative", "control"):
        mine = [p for p in record["prs"] if p["role"] == role]
        out[role + "s"] = {"prs": len(mine), **{o: sum(1 for p in mine if p["outcome"] == o) for o in record["outcomes"]}}
    neg = out["negatives"]
    readable = neg["consistent"] + neg["flipped"]
    out["flipped_share_ci95"] = agent_pr_index.wilson(neg["flipped"], readable)
    out["says"] = (f"{neg['flipped']} of {neg['prs']} negatives flipped; {neg['consistent']} read as before, "
                   f"{neg['inconclusive']} could not be decided without logging in, and {neg['unreadable']} pages did not show the merge "
                   f"or the checks")
    return out


def version2(sample, review, record=None):
    """The version 2 draft: none of it changes a version 1 count."""
    rows, strict, kept = _strict_kept(sample, review)
    recorded = {_key(r) for r in rows if _failed(r)}
    recorded_strict = {_key(r) for r in rows if agent_pr_index.FAILED["test_or_build_check_failed"](r)}
    return {"status": "draft: version 1 stays the method of record; nothing here changes its counts",
            "funnel": funnel(sample, review),
            "clustered": {"reviewed_strict": clustered(rows, strict), "reviewed_any": clustered(rows, kept),
                          "recorded_strict": clustered(rows, recorded_strict), "recorded_any": clustered(rows, recorded)},
            "reread_negatives": {"protocol": "docs/INDEX_METHOD.md, version 2 draft, 'Reading the negatives again'",
                                 "population": len(rows) - len(strict),
                                 "run": reread(sample, review, record) if record else None},
            "comparison_group": {"status": "planned, not run",
                                 "plan": "docs/INDEX_METHOD.md, version 2 draft, 'A comparison group of pull requests by people'"}}


def build(sample, review, index=None, pulls=None, kept=None, negatives=None):
    """`kept`: the `index` part of an earlier output, carried over when this run was given no index (index.json and its
    pulls are not in the repository, so a run without them keeps what the run with them wrote). `negatives`: the
    record of the blind re-read (docs/index_reread_negatives.json), for the version 2 draft."""
    out = {"about": "Of merged pull requests by AI coding agents whose description said tests or CI pass, how many had a "
                    "failed check at the head commit. A Knos bounty whose terms required that check would not have "
                    "paid the merge. Written by scripts/backtest.py.",
           "definitions": {**DEFINITIONS, "reviewed": "the same counts after a second reading of each merged pull request "
                           "with a failed check (docs/index_review.json, rules in docs/INDEX_METHOD.md); the denominator "
                           "stays, since the others were not read again"},
           "method": method()[0], "sample": from_sample(sample)}
    out["reviewed"] = reviewed(sample, review)
    if index:
        out["index"] = from_index(index, pulls, sample)
    elif kept:
        out["index"] = kept
    out["cannot_show"] = cannot_show(out)
    out["version2_draft"] = version2(sample, review, negatives)
    return out


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("step", nargs="?", default="build", choices=["build", "fetch"])
    ap.add_argument("--sample", default=SAMPLE)
    ap.add_argument("--index", help="a published index.json (its Merkle root is checked)")
    ap.add_argument("--pulls", help="merge state of the index's pull requests, written by `fetch`")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--max-seconds", type=int, default=3000)
    ap.add_argument("--review", default=REVIEW)
    ap.add_argument("--negatives", help="the blind re-read of the negatives (default: docs/index_reread_negatives.json, "
                                        "with the sample in the repository)")
    ap.add_argument("--check", action="store_true", help="fail if the method changed without a new version, or the output is stale")
    a = ap.parse_args(argv)
    negatives = _load(a.negatives) if a.negatives else _load(NEGATIVES) if a.sample == SAMPLE and os.path.exists(NEGATIVES) else None
    if a.check:
        _, problems = method()
        if not problems and not a.index:
            was = _load(a.out)
            if was != json.loads(json.dumps(build(_load(a.sample), _load(a.review), kept=was.get("index"), negatives=negatives))):
                problems.append(f"{os.path.relpath(a.out, ROOT)} is not what scripts/backtest.py writes: run it")
        for line in problems:
            print("backtest --check: " + line, file=sys.stderr)
        return 1 if problems else 0
    index = agent_pr_index.check(a.index) if a.index else None
    if a.step == "fetch":
        if not index or not a.pulls:
            ap.error("fetch needs --index index.json and --pulls pulls.json")
        pulls, left = fetch(index, a.max_seconds)
        with open(a.pulls, "w", encoding="utf-8") as f:
            json.dump(pulls, f, ensure_ascii=False)
        print(f"read {len(pulls):,} of {index['n_prs']:,} pull requests"
              + (f"; {left:,} not answered yet: run this again to continue" if left else ""), file=sys.stderr)
        return 1 if left else 0
    sample = _load(a.sample)
    pulls = _load(a.pulls) if index and a.pulls and os.path.exists(a.pulls) else None
    was = _load(a.out) if os.path.exists(a.out) else {}
    out = build(sample, _load(a.review), index, pulls, kept=was.get("index"), negatives=negatives)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
        f.write("\n")
    m = out["sample"]["merged"]["overall"]
    print(f"backtest: {m['prs']} merged pull requests in the sample, {m['any_check_failed']['prs']} with a failed check "
          f"({m['test_or_build_check_failed']['prs']} a test, build, lint or type check); after the second reading "
          f"{out['reviewed']['overall']['any_check_failed']['prs']} and {out['reviewed']['overall']['test_or_build_check_failed']['prs']}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
