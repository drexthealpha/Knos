"""What a funder buys: the terms of one bounty, fixed when it is funded.

The funding instruction carries these bytes. knos-pay keeps their sha256 in the job, logs the JSON, and pays only on a
token that carries the same hash, so what is written here is public and cannot change afterwards.

    {"accept":"","checks":[{"app":15368,"name":"test"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":[],"reserve":7,"v":1}

The canonical form (the only one `parse` reads): one JSON object with exactly these keys, sorted; separators "," and
":"; ASCII, everything else written \\uXXXX as Python's json writes it; every list sorted by code point with no repeat;
at most 600 bytes.

    checks    what must have concluded `success` at the merged pull request's head commit, each with the GitHub App
              that must have produced it: its id; 0 for a commit status with that context; -1 for any source (a
              branch rule that names no source allows exactly that)
    paths     when not empty, every changed file must match one of these globs
    deny      no changed file may match one of these (so a pull request cannot edit the checks that judge it)
    accept    tests mode: the hash of .knos/acceptance/<issue>/ (knos.judge.checks_hash); empty in merge mode
    image     optional, tests mode only: the container image the black-box check runs the submission in, pinned by
              digest: <registry>/<name>@sha256:<64 hex>. A tag is refused: a tag can be moved after funding
    reserve   days a `/knos take` reservation lasts (0: the issue cannot be reserved)

Globs are GitHub's own, as in a workflow's `paths:` filter: `*` stays inside one directory, `**` crosses them, `?` is
one character, and a pattern ending in `/` means everything under that directory.

What decides a payment is `accepted`: every required check `passed` at that commit and no changed file out of scope.
The words of a pull request's description never change what is required. The readers of GitHub are at the bottom,
each with an injected `get(path)` (knos.judge.github): they are the only functions here that are not pure.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import time
import urllib.parse
from typing import NamedTuple

MAX_BYTES = 600                    # knos-pay's MAX_TERMS
DENY = (".github/**", ".knos/**")
RESERVE, MAX_RESERVE = 7, 90
STATUS, ANY = 0, -1                # a check's `app`: a commit status; any source
STATES = ("passed", "failed", "skipped", "pending", "absent", "unreadable")
_KEYS = frozenset(("accept", "checks", "deny", "mode", "paths", "reserve", "v"))
_ORDER_KEYS = frozenset(("image", "policy", "vendor"))     # terms may also say these; without them a job's bytes stay as they were
# <registry>/<name>@sha256:<64 hex>: a registry host (a dot, a port, or localhost), a lower-case path, and a digest. No tag.
_IMAGE = re.compile(r"(?=[^/]*[.:]|localhost/)[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[0-9]{1,5})?(?:/[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*)+@sha256:[0-9a-f]{64}")


class Refused(ValueError):
    """Terms that cannot be made or read. The message is for the funder: what happened and what to type instead."""


# ---- Knos's own jobs are never evidence about a pull request ---------------------------------------------------------

_KNOS_JOBS = re.compile(r"^(?:prove|fund)(?:-relay|-refused)? / |^knos| / claims$")


def ours(run: dict, run_id: str | None = None) -> bool:
    """A check run that is Knos's own (this workflow run's jobs, and the Knos jobs of other runs on the same commit:
    the check, the proof, the relay and its verdict). `run_id` is this run's id (default: GITHUB_RUN_ID)."""
    mine = os.environ.get("GITHUB_RUN_ID", "") if run_id is None else str(run_id)
    return bool(mine and f"/runs/{mine}/" in str(run.get("details_url", ""))) or _knos_name(run.get("name"))


def _knos_name(name) -> bool:
    return bool(_KNOS_JOBS.search(str(name or "")))


# ---- the canonical form ----------------------------------------------------------------------------------------------

def _text(value, what: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 200 or any(ch < " " or ch == "\x7f" for ch in value):
        raise Refused(f"{what} must be 1 to 200 characters on one line: {str(value)[:60]!r}")
    return value


def valid_glob(value) -> str:
    """`value` when it is a glob the terms can hold; raises Refused otherwise."""
    g = _text(value, "a glob")
    if g != g.strip() or g.startswith(("/", "!")) or "\\" in g or ".." in g.split("/"):
        raise Refused(f"a glob is a path from the repository's root, like src/** or docs/*.md: {g[:60]!r}")
    return g


def valid_image(value) -> str:
    """`value` when it names one container image for ever: <registry>/<name>@sha256:<64 hex>. Raises Refused, with what
    to write instead, for a tag (it can be moved to other bytes after funding) and for anything else."""
    text = value if isinstance(value, str) else ""
    if len(text) <= 255 and _IMAGE.fullmatch(text):
        return text
    shown = str(value)[:80]
    if text and "@sha256:" not in text:
        raise Refused(f"image {shown!r} is a name or a tag, and a tag can be pointed at another image after funding. Pin it by "
                      "digest: write <registry>/<name>@sha256:<64 hex>, for example docker.io/library/python@sha256:... "
                      "(`docker buildx imagetools inspect <name>:<tag>` prints the digest).")
    raise Refused(f"image {shown!r} is not <registry>/<name>@sha256:<64 hex>: write the registry in full "
                  "(docker.io/library/python, not python), lower case, with no tag before the @, and all 64 hex "
                  "characters of the digest.")


def _int(value, low: int, high: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise Refused(f"{what} must be a whole number from {low} to {high}")
    return value


def _clean(terms) -> dict:
    """The terms with every field checked and every list in its canonical order. Raises Refused."""
    if not isinstance(terms, dict) or set(terms) - _ORDER_KEYS != _KEYS:
        raise Refused("a bounty's terms have exactly these fields: " + ", ".join(sorted(_KEYS)))
    more = {}
    if "policy" in terms:       # sha256 of the repository's .knos/policy.yml as it was at funding (knos.policy.digest)
        if not isinstance(terms["policy"], str) or not re.fullmatch(r"[0-9a-f]{64}", terms["policy"]):
            raise Refused("policy is the hash of the repository's policy file (64 hex characters)")
        more["policy"] = terms["policy"]
    if "vendor" in terms:       # a standing offer: the GitHub id of the one account it pays
        more["vendor"] = _int(terms["vendor"], 1, 2**63 - 1, "vendor")
    if "image" in terms:        # the hermetic judge's image (knos.judge): fixed at funding like every other field
        more["image"] = valid_image(terms["image"])
        if terms.get("mode") != "tests":
            raise Refused("image goes with tests mode: it is what the acceptance checks run the pull request's code in. "
                          "A bounty paid on a merge has no judge to pin.")
    if terms["v"] != 1 or type(terms["v"]) is not int:
        raise Refused("v is 1: the only version of the terms there is")
    if terms["mode"] not in ("merge", "tests"):
        raise Refused("mode is merge or tests")
    accept = terms["accept"]
    if not isinstance(accept, str) or not re.fullmatch(r"[0-9a-f]{64}" if terms["mode"] == "tests" else "", accept):
        raise Refused("accept is the acceptance bundle's hash (64 hex characters) in tests mode, and empty in merge mode")
    checks = set()
    if not isinstance(terms["checks"], list):
        raise Refused("checks is a list")
    for c in terms["checks"]:
        if not isinstance(c, dict) or set(c) != {"app", "name"}:
            raise Refused('each check is {"app": <GitHub App id, 0 for a commit status, -1 for any source>, "name": <its name>}')
        checks.add((_text(c["name"], "a check's name"), _int(c["app"], ANY, 2**31 - 1, "a check's app")))
    lists = {}
    for key in ("deny", "paths"):
        if not isinstance(terms[key], list):
            raise Refused(f"{key} is a list of globs")
        lists[key] = sorted({valid_glob(g) for g in terms[key]})
    return {"accept": accept, "checks": [{"app": app, "name": name} for name, app in sorted(checks)],
            "deny": lists["deny"], "mode": terms["mode"], "paths": lists["paths"],
            "reserve": _int(terms["reserve"], 0, MAX_RESERVE, "reserve"), "v": 1, **more}


def _dump(terms: dict) -> bytes:
    return json.dumps(terms, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def canonical(terms: dict) -> bytes:
    """The bytes that are funded, hashed and logged. Lists are put in order, so equal terms give equal bytes.
    Raises Refused when a field is not what the format allows or the result is over 600 bytes."""
    data = _dump(_clean(terms))
    if len(data) > MAX_BYTES:
        raise Refused(f"these terms take {len(data)} bytes; a bounty's terms hold at most {MAX_BYTES}")
    return data


def terms_hash(terms) -> str:
    """sha256 of the canonical bytes, in hex: what the fund and pay audiences carry. Takes the terms or their bytes."""
    return hashlib.sha256(bytes(terms) if isinstance(terms, (bytes, bytearray)) else canonical(terms)).hexdigest()


def parse(data) -> dict:
    """The terms in `data`, which must be exactly their canonical bytes: anything else (another key order, a space,
    an unsorted list, a repeated key, a number written another way, more than 600 bytes) is refused."""
    raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    if len(raw) > MAX_BYTES:
        raise Refused(f"these terms take {len(raw)} bytes; a bounty's terms hold at most {MAX_BYTES}")
    try:
        got = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise Refused("these terms are not ASCII JSON") from None
    clean = _clean(got)
    if _dump(clean) != raw:
        raise Refused("these terms are not in canonical form (sorted keys, no spaces, sorted lists)")
    return clean


# ---- globs -----------------------------------------------------------------------------------------------------------

@functools.lru_cache(maxsize=512)
def _glob(pattern: str) -> re.Pattern:
    pat = pattern + "**" if pattern.endswith("/") else pattern
    out, i = [], 0
    while i < len(pat):
        if pat.startswith("**/", i) and (i == 0 or pat[i - 1] == "/"):
            out.append("(?:.*/)?")       # zero or more directories
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile("".join(out), re.DOTALL)


def matches(path: str, glob: str) -> bool:
    """Whether a file's path (from the repository's root, `/` between directories) matches a terms glob."""
    return _glob(glob).fullmatch(path) is not None


_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


def _git_path(line: str) -> str:
    """One path as git prints it. A name with a quote, a backslash, a control character or (by default) a byte
    outside ASCII comes in double quotes with C escapes; left like that it would match no glob."""
    if len(line) < 2 or line[0] != '"' or line[-1] != '"':
        return line
    out, body, i = bytearray(), line[1:-1], 0
    while i < len(body):
        if body[i] != "\\":
            out += body[i].encode("utf-8", "replace")
            i += 1
        elif body[i + 1:i + 2] in _ESCAPES:
            out.append(_ESCAPES[body[i + 1]])
            i += 2
        elif re.fullmatch(r"[0-3][0-7]{2}", body[i + 1:i + 4]):
            out.append(int(body[i + 1:i + 4], 8))
            i += 4
        else:
            return line      # not git's quoting: the name as it stands
    return out.decode("utf-8", "replace")


def listed(text: str) -> list[str]:
    """The paths in a list as `git diff --name-only` prints it, one a line, each as the file is really named.
    Make the list with `--no-renames`: by default git names a renamed file only where it went, and `scope` must
    see where it came from too."""
    return [_git_path(line.rstrip("\r")) for line in (text or "").split("\n") if line.strip()]


# ---- the terms of one bounty, from the fund command and what the repository has --------------------------------------

class Built(NamedTuple):
    terms: dict
    source: str      # where the checks came from: funder (they wrote them), rules, head, or none (there are none)
    notes: list      # what was assumed, in words for the funder


_CODE_EVENTS = ("push", "pull_request", "merge_group")      # what puts a workflow's checks on the commit it tests
_AGAIN = "Send the command again."


def listing(got, key: str) -> list | None:
    """A listing as it was given: None (GitHub could not be read), a list, or GitHub's own answer
    {"total_count": n, key: [...]}, which is None too when it holds fewer rows than it counts (cut short)."""
    if got is None:
        return None
    if isinstance(got, dict):
        rows = got.get(key)
        total = got.get("total_count")
        if not isinstance(rows, list) or (isinstance(total, int) and total > len(rows)):
            return None
        return rows
    return list(got)


def _app(run: dict) -> int:
    app = (run.get("app") or {}).get("id")
    return app if isinstance(app, int) and not isinstance(app, bool) and app > 0 else ANY


def state_of(run: dict) -> str:
    """One check run: passed, failed, skipped or pending. A finished run that did not conclude success, skipped or
    neutral has failed (failure, timed_out, cancelled, action_required, startup_failure, stale, or nothing at all)."""
    if run.get("status") != "completed":
        return "pending"
    concluded = run.get("conclusion")
    return "passed" if concluded == "success" else "skipped" if concluded in ("skipped", "neutral") else "failed"


def status_state(status: dict) -> str:
    """One commit status: passed, pending or failed (failure, error)."""
    return {"success": "passed", "pending": "pending"}.get(str(status.get("state")), "failed")


_RANK = {"failed": 0, "pending": 1, "passed": 2, "skipped": 3}


def together(states: list[str]) -> str:
    """Several runs of one check on one commit, as one state: a failure decides, then an unfinished run, then a
    success; all skipped is skipped; none at all is absent."""
    return min(states, key=_RANK.__getitem__) if states else "absent"


def _sources(name: str, pinned: set, runs: list, statuses: list, notes: list) -> list[tuple[str, int]]:
    """The (name, app) entries one required check becomes. As a check run: from the app a branch rule pins, else the
    app that produced it on the default branch's head commit. As a commit status, when that is how it shows there
    (a rule's pin cannot be held against a status: GitHub does not say which app wrote one). Seen nowhere and
    pinned by nothing: any source, said out loud."""
    seen = {_app(r) for r in runs if r.get("name") == name}
    status = any(s.get("context") == name for s in statuses)
    out = {(name, a) for a in ((pinned or seen) if seen or not status else ())} | ({(name, STATUS)} if status else set())
    if not out:
        notes.append(f"`{name}` did not run on the default branch's latest commit and no branch rule names its "
                     "source, so a check or a commit status of that name from any source will count.")
        out.add((name, ANY))
    return sorted(out)


def build(fund, required=None, check_runs=None, statuses=None, accept: str = "", deny=DENY, image: str = "") -> Built:
    """The terms a fund command buys, decided once, here.

    `fund` is the parsed command (knos.commands.Fund: `checks` is None when the funder named none, an empty tuple
    for `checks: none`; `paths`; `reserve`). The repository's facts, each None when GitHub could not be read:
    `required` (required_checks), and the default branch head's `check_runs` and `statuses` (head_checks).

    The checks are the names the funder wrote; else the default branch's required status checks; else every check
    run that ran to an end on the default branch's head commit (never Knos's own, never one a comment, a schedule
    or a button started, never a skipped one, and not one whose workflow is known to run on pushes only). No check
    at all is allowed, and `describe` says so out loud.
    `accept` is the acceptance bundle's hash in tests mode, and `image` the digest-pinned image its black-box check
    runs the submission in ("" for none; ignored in merge mode). Raises Refused, with the words to send the funder."""
    named = getattr(fund, "checks", None)
    notes: list[str] = []
    if named is not None and not named:
        pairs, source = [], "funder"
    else:
        runs, stats = listing(check_runs, "check_runs"), listing(statuses, "statuses")
        if required is None or runs is None or stats is None:
            raise Refused("GitHub did not answer for this repository's checks, so the bounty's terms could not be "
                          f"fixed. {_AGAIN}")
        runs = [r for r in runs if not ours(r)]
        stats = [s for s in stats if not _knos_name(s.get("context"))]
        pins: dict[str, set] = {}
        for r in required:
            pins.setdefault(str(r.get("name")), set()).update({r["app"]} if isinstance(r.get("app"), int) else ())
        if named:
            mine = [n for n in named if _knos_name(n)]
            if mine:
                raise Refused(f"`{mine[0]}` is Knos's own job, and a bounty cannot require it. Name your repository's "
                              "checks, or leave `checks:` out.")
            pairs, source = [p for n in named for p in _sources(n, pins.get(n, set()), runs, stats, notes)], "funder"
        elif pins:
            pairs, source = [p for n in sorted(pins) for p in _sources(n, pins[n], runs, stats, notes)], "rules"
        else:
            pairs = _ran(runs, notes)
            source = "head" if pairs else "none"
    paths = [str(p) for p in getattr(fund, "paths", None) or ()]
    terms = {"accept": accept or "", "checks": [{"app": app, "name": name} for name, app in pairs], "deny": list(deny),
             "mode": "tests" if accept else "merge", "paths": paths, "reserve": getattr(fund, "reserve", RESERVE), "v": 1}
    if image and accept:
        terms["image"] = image
    clean = _clean(terms)
    size = len(_dump(clean))
    if size > MAX_BYTES:
        n = len(clean["checks"])
        if len(_dump({**clean, "checks": []})) > MAX_BYTES:
            raise Refused(f"Those paths do not fit: a bounty's terms hold {MAX_BYTES} bytes and these take {size}. "
                          "Use fewer or shorter globs.")
        if source == "funder":
            raise Refused(f"Those {n} checks do not fit: a bounty's terms hold {MAX_BYTES} bytes and these take {size}. "
                          "Name fewer checks, the ones that must pass.")
        raise Refused(f"This repository's {n} checks do not fit in a bounty's terms ({MAX_BYTES} bytes; they take {size}). "
                      "Name the ones that must pass: `checks: a, b`.")
    return Built(clean, source, notes)


TIP_DAYS = 1       # how long a tip that could not be paid waits before it goes back


def tip() -> dict:
    """The terms of a `/knos tip`: a small bounty on a merged pull request, funded and paid at once. They ask for
    nothing: the one who tips has seen the work, and it is their money."""
    return {"accept": "", "checks": [], "deny": [], "mode": "merge", "paths": [], "reserve": 0, "v": 1}


def _ran(runs: list, notes: list) -> list[tuple[str, int]]:
    """Every check run that ran to an end on the default branch's head commit, as far as it would run on a pull
    request too. A run that head_checks marked with the event that started it counts only when that event puts
    checks on the commit under test (a push or a pull request): a job started by a comment, a schedule, a button
    or another pull request's event attaches to the same commit and would never show on a pull request's head.
    A run marked as never seen on a pull request (a deploy or a release, which runs on pushes only) is left out
    and named, once another check is known to run there; a bounty that required it could never be paid.
    Commit statuses are not taken from there: services name them differently on a branch and on a pull request."""
    runs = [r for r in runs if (r.get("event") is None or r["event"] in _CODE_EVENTS) and r.get("name") and state_of(r) != "skipped"]
    never = sorted({str(r["name"]) for r in runs if r.get("on_pulls") is False})
    names = ", ".join(f"`{n}`" for n in never[:6])
    if never and any(r.get("on_pulls") for r in runs):
        runs = [r for r in runs if r.get("on_pulls") is not False]
        notes.append(f"Left out, because {'its workflow has' if len(never) == 1 else 'their workflows have'} never run on a "
                     f"pull request: {names}. To require one anyway, name it: `checks: a, b`.")
    elif never:
        notes.append(f"{names} {'has' if len(never) == 1 else 'have'} never run on a pull request. A check that runs on pushes "
                     "only can never pass on one, and this bounty could then not be paid.")
    waiting = sorted({str(r["name"]) for r in runs if state_of(r) == "pending"})
    if waiting:
        raise Refused("Checks are still running on the default branch's latest commit (" + ", ".join(waiting[:6])
                      + "). A bounty's checks are fixed from the ones that ran there, so send the command again when "
                        "they have finished, or name them yourself: `checks: a, b` (or `checks: none`).")
    return sorted({(str(r["name"]), _app(r)) for r in runs})


def _named(checks: list) -> str:
    kind = {STATUS: " (a commit status)", ANY: " (any source)"}
    return ", ".join(f"`{c['name']}`{kind.get(c['app'], '')}" for c in checks)


ASSURANCE = {      # what each way of judging was measured to stop: docs/TAMPER.md has the numbers, docs/ASSURANCE.md the table
    "in-process": "The checks load the pull request's code into the process that judges it: 7 of 63 cheating pull "
                  "requests in Knos's tamper suite passed this mode (docs/TAMPER.md).",
    "black-box": "The pull request's code runs as a separate process on the judge's machine and only its output is "
                 "compared: 0 of 63 cheating pull requests in that suite passed. That is a count for that suite, not a "
                 "proof for every attack.",
    "hermetic": "The pull request's code runs black-box inside a container image pinned by digest, with no network, a "
                "read-only root, no host files but its own tree, and memory, CPU, process and time limits: 0 of 63 in "
                "that suite passed black-box, and anyone can run the same judge again on the same image. That is a "
                "count for that suite, not a proof for every attack.",
}


def assurance(terms: dict, black_box: bool | None = None) -> str:
    """"in-process", "black-box" or "hermetic" for tests-mode terms; "" in merge mode (a person's merge is the
    acceptance) and when `black_box` is None with no image (the terms alone do not say how the bundle is written)."""
    if terms.get("mode") != "tests":
        return ""
    if terms.get("image"):
        return "hermetic"
    return "" if black_box is None else "black-box" if black_box else "in-process"


def describe(terms: dict, source: str = "", black_box: bool | None = None) -> list[str]:
    """The terms in plain sentences, for the reply to the funder: what must be true for the bounty to be paid.
    `black_box`: whether the acceptance bundle is (knos.judge.black_box), when the caller knows; with it, or with an
    image in the terms, the last sentence names the assurance of the judge."""
    out = []
    where = {"funder": "the checks you named", "rules": "this branch's required checks",
             "head": "the checks that ran on the default branch's latest commit"}.get(source, "")
    how = ("when its acceptance checks (.knos/acceptance/ for this issue) pass on a pull request" if terms["mode"] == "tests"
           else "when a maintainer merges a pull request that closes this issue")
    if terms["checks"]:
        out.append(f"It is paid {how}, if these checks passed at that pull request's last commit: "
                   f"{_named(terms['checks'])}" + (f" ({where})." if where else "."))
    elif terms["mode"] == "tests":
        out.append(f"It is paid {how}.")
    elif source == "funder":
        out.append("You asked for no checks; your merge alone is the acceptance.")
    else:
        out.append("This repository has no checks; your merge alone is the acceptance.")
    may = "The pull request may not change " + " or ".join(f"`{g}`" for g in terms["deny"]) if terms["deny"] else ""
    only = "may only change files matching " + " or ".join(f"`{g}`" for g in terms["paths"]) if terms["paths"] else ""
    if may or only:
        out.append((f"{may}, and {only}" if may and only else may or f"The pull request {only}") + ".")
    out.append(f"`/knos take` reserves the issue for {terms['reserve']} day{'s' if terms['reserve'] != 1 else ''}."
               if terms["reserve"] else "Nobody can reserve it: the first accepted pull request is paid.")
    level = assurance(terms, black_box)
    if level:
        out.append(f"Judge: {level}" + (f", in `{terms['image']}`" if level == "hermetic" else "") + f". {ASSURANCE[level]}")
    return out


AUTO = ("It pays the first pull request that passes the black-box suite, without waiting for a merge: nobody assigns, reviews or "
        "merges first. You chose this when you funded; it cannot be turned off afterwards, only cancelled with notice.")
JUDGES = {2: "two", 3: "three"}


def readers(neutral: bool = True, judge: str = "") -> list[str]:
    """Who can pass a pull request for an order, each in a few words: the buyer repository's own run, a neutral run
    (unless the funder said `neutral off`), and the judge repository named at funding (`judge`, owner/name)."""
    return ["this repository's own run",
            *(["a neutral run that someone other than its funder starts by hand in a repository of their own (for an order paid by its "
               "acceptance suite, that run executes the suite again itself)"] if neutral else []),
            *([f"a run in {judge}, the judge repository named at funding, which belongs to neither the funder nor this repository's owner"]
              if judge else [])]


def describe_options(auto: bool = False, quorum: int = 0, neutral: bool = True, judge: str = "") -> list[str]:
    """The sentences for the reply to the funder about the options of a work order that are not in the terms JSON
    (they are in the order's options, which the fund token also signs): `auto`, `quorum 2|3` and `judge: owner/repo`.
    The quorum's sentence says who the readers are."""
    out = [AUTO] if auto else []
    if quorum:
        who = readers(neutral, judge)
        names = "; ".join(f"{i}. {w}" for i, w in enumerate(who, 1))
        count = "all of these" if quorum == len(who) else f"any {JUDGES[quorum]} of these"
        out.append(f"It is paid only after {JUDGES[quorum]} independent readers have each passed the same pull request at the same commit, "
                   f"{count}: {names}. One reader counts once, however often it passes; two repositories of one owner are one reader.")
    return out


# ---- evidence: GitHub's record of one commit against the terms -------------------------------------------------------

_WORST = ("unreadable", "failed", "pending", "absent", "skipped", "passed")


def _one(check: dict, runs: list | None, statuses: list | None) -> str:
    name, app = check["name"], check["app"]
    if (runs is None and app != STATUS) or (statuses is None and app in (STATUS, ANY)):
        return "unreadable"
    found = [] if app == STATUS else [state_of(r) for r in runs if r.get("name") == name and app in (ANY, _app(r))]
    if app in (STATUS, ANY):
        mine = [s for s in statuses if s.get("context") == name]
        if mine:    # a context's newest status is the one that counts
            found.append(status_state(max(mine, key=lambda s: (str(s.get("updated_at") or s.get("created_at") or ""),
                                                                 s.get("id") or 0))))
    return together(found)


def evidence(terms: dict, check_runs, statuses, run_id: str | None = None) -> dict:
    """{check name: state} for every check the terms require, from one commit's check runs and commit statuses
    (lists as GitHub gives them, or GitHub's own answers with their `total_count`).

        passed      completed, conclusion success, from the app the terms name
        failed      completed with failure, timed_out, cancelled, action_required, startup_failure or stale
        skipped     completed with skipped or neutral
        pending     not completed
        absent      no such check on this commit (one of that name from another app is not it)
        unreadable  the listing is None (GitHub could not be read) or was cut short

    Knos's own jobs are never evidence. A name the terms require from two sources shows the worse of the two."""
    runs, stats = listing(check_runs, "check_runs"), listing(statuses, "statuses")
    if runs is not None:
        runs = [r for r in runs if not ours(r, run_id)]
    if stats is not None:
        stats = [s for s in stats if not _knos_name(s.get("context"))]
    out: dict[str, str] = {}
    for check in terms["checks"]:
        state = _one(check, runs, stats)
        before = out.get(check["name"])
        out[check["name"]] = state if before is None else min(before, state, key=_WORST.index)
    return out


def _show(path) -> str:
    """A path, safe to say back: one line, no backtick, nothing a terminal or a JSON file cannot hold."""
    return "".join(ch if " " <= ch != "`" and ch != "\x7f" and not "\ud800" <= ch <= "\udfff" else "?" for ch in str(path))[:120]


def scope(terms: dict, changed_files) -> list[str]:
    """What the pull request changed that the terms do not allow: a file a `deny` glob matches, or, when `paths` is
    not empty, a file none of them matches. `changed_files` is the list of changed paths, or GitHub's own file
    objects (a rename counts under both its names); None means it could not be read, which is a violation too."""
    if changed_files is None:
        return ["the pull request's changed files could not be read from GitHub; try again"]
    names = set()
    for f in changed_files:
        names.update(str(n) for n in ((f.get("filename"), f.get("previous_filename")) if isinstance(f, dict) else (f,)) if n)
    out = []
    for path in sorted(names):
        denied = next((g for g in terms["deny"] if matches(path, g)), None)
        if denied:
            out.append(f"changes `{_show(path)}`, which this bounty does not allow (`{denied}`)")
        elif terms["paths"] and not any(matches(path, g) for g in terms["paths"]):
            out.append(f"changes `{_show(path)}`, outside what this bounty covers ("
                       + ", ".join(f"`{g}`" for g in terms["paths"]) + ")")
    return out[:10] + ([f"and {len(out) - 10} more files out of scope"] if len(out) > 10 else [])


_WHY = {"failed": "failed at this commit", "pending": "has not finished at this commit",
        "skipped": "was skipped at this commit, which does not count as passing",
        "absent": "did not run on this commit", "unreadable": "could not be read from GitHub; try again"}


def accepted(terms: dict, evidence: dict, changed_files) -> tuple[bool, list[str]]:
    """Whether the terms are met, and every reason they are not: each required check must be `passed` in `evidence`
    (a name missing from it counts as unreadable), and `scope(terms, changed_files)` must be empty. With no check
    required, the scope alone decides."""
    reasons = []
    for name in dict.fromkeys(c["name"] for c in terms["checks"]):
        state = evidence.get(name, "unreadable")
        if state != "passed":
            reasons.append(f"required check `{name}` {_WHY.get(state, _WHY['unreadable'])}")
    reasons += scope(terms, changed_files)
    return not reasons, reasons


# ---- reading GitHub: `get(path)` is knos.judge.github (a path under api.github.com; raises when GitHub says no) -------

def pages(path: str, get, key: str | None = None, cap: int = 10) -> list | None:
    """Every row of a paged listing, 100 a page. None when GitHub could not be read, or when `cap` full pages were
    not the end of it (cut short)."""
    rows: list = []
    sep = "&" if "?" in path else "?"
    try:
        for page in range(1, cap + 1):
            got = get(f"{path}{sep}per_page=100&page={page}")
            batch = got.get(key) if key and isinstance(got, dict) else got
            if not isinstance(batch, list):
                return None
            rows += batch
            if len(batch) < 100:
                return rows
            total = got.get("total_count") if isinstance(got, dict) else None
            if isinstance(total, int) and len(rows) >= total:
                return rows
    except Exception:  # noqa: BLE001 - GitHub said no, or did not answer
        return None
    return None


def required_checks(repo: str, branch: str, get) -> list[dict] | None:
    """The status checks a branch requires: [{"name", "app"}], app None when the rule names no source. The union of
    its rulesets (GET /repos/{repo}/rules/branches/{branch}) and its classic protection
    (GET /repos/{repo}/branches/{branch}, `protection.required_status_checks`). Never Knos's own check. None when
    GitHub could not be read: that is not the same as requiring nothing."""
    b = urllib.parse.quote(str(branch), safe="")
    rules = pages(f"repos/{repo}/rules/branches/{b}", get)
    if rules is None:
        return None
    try:
        info = get(f"repos/{repo}/branches/{b}")
    except Exception:  # noqa: BLE001
        return None
    found: dict[str, set] = {}

    def add(name, app) -> None:
        if isinstance(name, str) and name and not _knos_name(name):
            found.setdefault(name, set()).update({app} if isinstance(app, int) and not isinstance(app, bool) and app > 0 else ())

    for rule in rules:
        if isinstance(rule, dict) and rule.get("type") == "required_status_checks":
            for c in (rule.get("parameters") or {}).get("required_status_checks") or []:
                add(c.get("context"), c.get("integration_id"))
    classic = ((info.get("protection") or {}) if isinstance(info, dict) else {}).get("required_status_checks") or {}
    if classic.get("enforcement_level") != "off":
        for c in classic.get("checks") or []:
            add(c.get("context"), c.get("app_id"))
        for name in classic.get("contexts") or []:
            add(name, None)
    return [{"name": name, "app": app} for name in sorted(found) for app in (sorted(found[name]) or [None])]


def head_checks(repo: str, sha: str, get, events: bool = False) -> tuple[list | None, list | None]:
    """(check runs, commit statuses) at one commit: every page of GET /repos/{repo}/commits/{sha}/check-runs, and
    the newest status of each context from GET /repos/{repo}/commits/{sha}/status. Each is None when GitHub could
    not be read or the listing was cut short.

    `events` (what `build` wants at the default branch's head): each check run of a GitHub Actions job also gets
    "event", the event that started its workflow run (GET /repos/{repo}/actions/runs?head_sha=...), and, when a
    push started it, "on_pulls": whether that workflow has ever run for a pull request
    (GET /repos/{repo}/actions/workflows/{id}/runs?event=pull_request; None when GitHub did not say). When the
    workflow runs cannot be read the check runs come back unmarked."""
    runs = pages(f"repos/{repo}/commits/{sha}/check-runs", get, "check_runs")
    statuses = pages(f"repos/{repo}/commits/{sha}/status", get, "statuses")
    if events and runs:
        started = pages(f"repos/{repo}/actions/runs?head_sha={sha}", get, "workflow_runs") or []
        by_suite = {w.get("check_suite_id"): w for w in started if isinstance(w, dict) and w.get("event")}
        seen: dict = {}
        for r in runs:
            w = by_suite.get((r.get("check_suite") or {}).get("id"))
            if w:
                r["event"] = w["event"]
                if w["event"] in _CODE_EVENTS:
                    r["on_pulls"] = w["event"] == "pull_request" or _on_pulls(repo, w.get("workflow_id"), get, seen)
    return runs, statuses


def _on_pulls(repo: str, workflow, get, seen: dict) -> bool | None:
    """Whether a workflow has ever run for a pull request, asked once per workflow. None: GitHub did not say."""
    if workflow not in seen:
        try:
            seen[workflow] = int(get(f"repos/{repo}/actions/workflows/{int(workflow)}/runs?event=pull_request&per_page=1")["total_count"]) > 0
        except Exception:  # noqa: BLE001 - GitHub said no, or did not answer: not known
            seen[workflow] = None
    return seen[workflow]


def pull_files(repo: str, number: int, get) -> list[str] | None:
    """Every path a pull request changes (a rename under both names), from GET /repos/{repo}/pulls/{n}/files. None
    when GitHub could not be read, or at the 3000 files where GitHub stops listing."""
    files = pages(f"repos/{repo}/pulls/{number}/files", get, cap=30)
    if files is None:
        return None
    return sorted({str(n) for f in files if isinstance(f, dict) for n in (f.get("filename"), f.get("previous_filename")) if n})


def watch(terms: dict, repo: str, sha: str, get, wait: float = 0, sleep=None, clock=None) -> tuple[dict, list | None, list | None]:
    """(evidence, check runs, statuses) at a commit, read again every 15 seconds for up to `wait` seconds while a
    required check has not finished or GitHub cannot be read."""
    sleep, clock = sleep or time.sleep, clock or time.monotonic
    end = clock() + wait
    while True:
        runs, statuses = head_checks(repo, sha, get)
        found = evidence(terms, runs, statuses)
        if not {"pending", "unreadable"} & set(found.values()) or clock() >= end:
            return found, runs, statuses
        sleep(15)
