"""Terms proposed from a repository's own record: `knos terms propose <owner/repo>`.

A buyer should not have to write acceptance terms from nothing. This reads what a public repository already shows
and proposes a filled Knos Terms 3 file (knos.terms3) the buyer edits and commits as `.knos/terms.json`:

    the checks that passed on every one of its last 10 merged pull requests   become the deciding checks
    its test directories                                                      become protected paths
    the owners its CODEOWNERS file names for everything                       may publish a new version
    everything else                                                           is the template's default

Every proposed field carries the lines that say where it came from (`from`), so nothing in a proposal is unexplained.
A proposal is a draft: nothing is funded, posted or opened anywhere by making one.

Nothing is proposed for a repository that merged no pull request in the last 30 days: its record is too old to say
which checks decide today. The date of the last merge is in every proposal and in every refusal.

`propose(repo, get, now)` reads through `get(path)`, which answers GitHub's REST API for a path (parsed JSON, or None
for a 404), so the tests run it on a recorded fixture with no network. It asks at most 17 questions: fewer than the
60 an hour GitHub allows a reader who has not signed in. web/propose_terms.js is the same reading in a browser, and
tests/data/propose_terms.json holds both to one answer.
"""
from __future__ import annotations

import base64
import calendar
import re
import time

from . import terms, terms3

MERGES = 10                     # how many recent merges are read
FRESH_DAYS = 30                 # a repository with no merge in this many days gets no proposal
TEST_DIRS = ("__tests__", "e2e", "spec", "specs", "test", "testing", "tests")
CODEOWNERS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
FILE = ".knos/terms.json"
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")
_OWNER = re.compile(r"@[A-Za-z0-9][A-Za-z0-9-]{0,38}(?:/[A-Za-z0-9._-]{1,60})?")
_NAMED = re.compile(r"[a-z0-9][a-z0-9._-]{0,39}/[a-z0-9][a-z0-9._-]{0,39}", re.I)


class Refused(ValueError):
    """No proposal can be made, and the message says why in words for the person who asked."""


def seconds(iso: str) -> int:
    """An ISO 8601 UTC time (`2026-10-01T12:00:00Z`) as seconds since 1970."""
    return calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))


def owners(text: str) -> list[str]:
    """Who a CODEOWNERS file names for everything: the owners of its last `*` line; with no such line, nobody."""
    found: list[str] = []
    for line in text.splitlines():
        parts = line.split("#")[0].split()
        if parts and parts[0] == "*":
            found = [p for p in parts[1:] if _OWNER.fullmatch(p)]
    return sorted(set(found))


def passing(merges: list[dict]) -> tuple[list[dict], list[str]]:
    """(the checks that passed on every merge that could be read, as {name, app}; the names that did not, each with
    why). `merges`: [{"number", "runs": the check runs of its last commit, or None when they could not be read}]."""
    read = [m for m in merges if m["runs"] is not None]
    seen: dict[tuple[str, int], dict[int, list[str]]] = {}
    for m in read:
        for run in m["runs"]:
            if not isinstance(run, dict) or not isinstance(run.get("name"), str) or terms.ours(run, ""):
                continue
            app = (run.get("app") or {}).get("id")
            key = (run["name"], app if isinstance(app, int) and not isinstance(app, bool) and app > 0 else terms.ANY)
            seen.setdefault(key, {}).setdefault(m["number"], []).append(terms.state_of(run))
    keep, dropped = [], []
    for (name, app), by in sorted(seen.items()):
        bad = [n for n in sorted(by) if terms.together(by[n]) != "passed"]
        if len(by) == len(read) and not bad:
            keep.append({"name": name, "app": app})
        elif bad:
            dropped.append(f"`{name}` did not pass on #{bad[0]}" + (f" and {len(bad) - 1} more" if len(bad) > 1 else ""))
        else:
            dropped.append(f"`{name}` ran on {len(by)} of {len(read)} merges")
    return keep, dropped


def propose(repo: str, get, now: float, template: str = "bug-fix") -> dict:
    """The proposal for `repo` (owner/name): {"repo", "terms": a valid terms 3 document, "hash", "from": {field: [where
    each line came from]}, "last_merge", "merges", "comment", "file"}. Raises Refused: not a public repository, or no
    merge in the last 30 days."""
    repo = str(repo).strip().removeprefix("https://github.com/").strip("/")
    if not _REPO.fullmatch(repo):
        raise Refused("Name the repository as owner/name, like octocat/hello-world.")
    info = get(f"repos/{repo}")
    if not isinstance(info, dict) or not info.get("full_name"):
        raise Refused(f"{repo} was not found. Only a public repository can be read without signing in.")
    repo, branch = info["full_name"], info.get("default_branch") or "main"
    if not _NAMED.fullmatch(repo):
        raise Refused(f"{repo} has a name too long for a terms file to carry.")
    owner = repo.split("/")[0]
    pulls = get(f"repos/{repo}/pulls?state=closed&base={branch}&sort=updated&direction=desc&per_page=100")
    merged = sorted((p for p in pulls or [] if isinstance(p, dict) and p.get("merged_at")), key=lambda p: p["merged_at"], reverse=True)[:MERGES]
    if not merged:
        raise Refused(f"{repo} has no merged pull request among its last 100 closed ones, so nothing says which checks decide there. Nothing is proposed.")
    last = merged[0]["merged_at"]
    age = int((now - seconds(last)) // 86400)
    if age > FRESH_DAYS:
        raise Refused(f"{repo} last merged a pull request on {last[:10]}, {age} days ago. Nothing is proposed for a repository "
                      f"with no merge in the last {FRESH_DAYS} days: its record is too old to say which checks decide today.")
    merges = []
    for p in merged:
        got = get(f"repos/{repo}/commits/{(p.get('head') or {}).get('sha')}/check-runs?per_page=100")
        merges.append({"number": p["number"], "runs": got.get("check_runs") if isinstance(got, dict) and isinstance(got.get("check_runs"), list) else None})
    read = [m for m in merges if m["runs"] is not None]
    deciding, dropped = passing(merges)
    root = get(f"repos/{repo}/contents/?ref={branch}")
    dirs = sorted(e["name"] for e in root or [] if isinstance(e, dict) and e.get("type") == "dir" and isinstance(e.get("name"), str))
    tests = [d for d in dirs if d.lower() in TEST_DIRS]
    flows = get(f"repos/{repo}/contents/.github/workflows?ref={branch}")
    flows = sorted(e["name"] for e in flows or [] if isinstance(e, dict) and str(e.get("name", "")).endswith((".yml", ".yaml")))
    who, owners_file = [], ""
    for path in CODEOWNERS:
        got = get(f"repos/{repo}/contents/{path}?ref={branch}")
        if isinstance(got, dict) and isinstance(got.get("content"), str):
            try:
                who, owners_file = owners(base64.b64decode(got["content"]).decode("utf-8", "replace")), path
            except ValueError:
                who = []
            break

    doc = terms3.base(repo, name=repo.lower())
    default = terms3.template(template)
    for field in ("deliverable", "window", "price", "deadline"):
        doc[field] = {k: v for k, v in default[field].items() if k != "says"}
    src: dict[str, list[str]] = {f: [f"Template default (`{template}`)."] for f in terms3.NAMES}
    src["deliverable"] = [f"Template default (`{template}`): one deliverable for each issue of {repo}."]
    src["evidence"] = ["Template default: GitHub signs for a run of the pinned Knos workflows, and nothing else counts."]
    protected = [f"{d}/**" for d in tests]
    doc["checks"] = {"mode": "merge", "deciding": deciding, "accept": "",
                     "authority": (f"the {len(flows)} workflow file{'' if len(flows) == 1 else 's'} in .github/workflows of {repo}" if flows
                                   else f"the checks GitHub records for {repo}") + " at the commit the order is funded on"}
    src["checks"] = ([f"`{c['name']}` passed on every one of the last {len(read)} merged pull requests (#{read[-1]['number']} to #{read[0]['number']})."
                      for c in deciding] if read else [])
    if not deciding:
        src["checks"].append(f"No check passed on every one of the last {len(read)} merged pull requests, so a maintainer's merge decides alone. Name a check you trust."
                             if read else "The check runs of the recent merges could not be read, so no check is named. Name one you trust.")
    src["checks"] += [f"Left out: {d}." for d in dropped[:8]] + ([f"Left out: {len(dropped) - 8} more."] if len(dropped) > 8 else [])
    src["checks"].append(f"Workflows read: {', '.join(flows)}." if flows else "No workflow file was found in .github/workflows.")
    paths = [g for g in default["changes"]["paths"] if g.endswith("/**") and g[:-3] in dirs and g not in protected]
    doc["changes"] = {"paths": paths, "protected": sorted({*terms.DENY, *protected}), "may_add": []}
    src["changes"] = [f"`{d}/` is a test directory of {repo}: protected, so the work cannot pass by changing its own tests. Remove the line to let a contributor add tests."
                      for d in tests] or [f"No test directory was found at the top of {repo}; nothing beyond the default is protected."]
    src["changes"].append("`.github/**` and `.knos/**` are protected in every order: they hold the checks and the terms.")
    src["changes"].append(f"Template default, kept where {repo} has the directory: {', '.join(paths)}." if paths else
                          "Any other file may change: the template's directories are not all in this repository.")
    doc["policy"] = {"may_change": who or ["@" + owner], "how": "new-version"}
    src["policy"] = [f"`{owners_file}` names {', '.join(who)} for every file." if who else
                     (f"`{owners_file}` names nobody for every file, so the owner, @{owner}, is proposed." if owners_file else
                      f"{repo} has no CODEOWNERS file, so the owner, @{owner}, is proposed.")]
    src["dispute"] = ["Template default: no arbiter is named. Name one neither side controls, or a rejection can only be undone by agreement."]
    src["evaluators"] = [f"Template default: the order's own repository, {repo}, judges. Add a second owner and `quorum 2` if the supplier does not trust it."]

    while True:         # an order's terms hold 600 bytes: the checks that do not fit are left out, and said
        try:
            terms3.order_terms(terms3.validate(doc, strict=False))
            break
        except terms3.Refused:
            if not doc["checks"]["deciding"]:
                raise
            gone = doc["checks"]["deciding"].pop()
            src["checks"] = [s for s in src["checks"] if not s.startswith(f"`{gone['name']}` passed")] + [
                f"Left out: `{gone['name']}` passed every time, and an order's terms have no room for it (600 bytes)."]
    out = terms3.validate(doc, strict=False)
    return {"repo": repo, "terms": out, "hash": terms3.digest(out), "from": src, "last_merge": last, "merges": len(merged),
            "comment": terms3.comment(out), "file": FILE}


def text(p: dict) -> str:
    """A proposal as the command line prints it: each of the ten answers, and under it where it came from."""
    lines = [f"Proposed terms for {p['repo']} ({terms3.STANDARD}). Last merge: {p['last_merge'][:10]}; {p['merges']} recent merges read.", ""]
    for q in terms3.questions(p["terms"]):
        lines += [q["question"], f"    {q['answer']}", *(f"      from: {s}" for s in p["from"][q["field"]]), ""]
    lines += [f"This is a draft. Edit it, save it as {p['file']} in the repository, and commit it: `knos terms propose {p['repo']} --out {p['file']}`.",
              "`knos terms verify <file>` checks your edit. The comment that funds an order on it:", "", f"    {p['comment']}", "",
              "Nothing was funded, posted or opened. Money is test USDC on Solana devnet."]
    return "\n".join(lines) + "\n"


def reader():
    """`get` for the command line: GitHub's public REST API, read and never written. A 404 is None. GH_TOKEN or
    GITHUB_TOKEN is sent when set, which lifts the limit of 60 answers an hour; nothing needs it."""
    import json
    import os
    import urllib.error
    import urllib.request

    def get(path: str):
        req = urllib.request.Request(f"https://api.github.com/{path}", headers={
            "Accept": "application/vnd.github+json", "User-Agent": "knos", "X-GitHub-Api-Version": "2022-11-28"})
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - api.github.com
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as why:
            if why.code == 404:
                return None
            if why.code in (403, 429):
                raise Refused("GitHub refused to answer: a reader who has not signed in gets 60 answers an hour. Try again later, or set GITHUB_TOKEN.") from None
            raise
        except ValueError:
            raise OSError(f"GitHub's answer for {path} was not JSON") from None
    return get
