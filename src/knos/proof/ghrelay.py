"""The zero-secret GitHub relay: Knos's public worker (worker.yml) carries the tokens that repositories' own workflows
minted to Solana, and pays the fees. Anyone else can run it too (`knos relay`); a relayer decides nothing. Each relayer
uses a key of its own (a token's account on chain belongs to the key that carried it, so two relayers never touch each
other's; two runs sharing one key do, and the loser of that race tries again on its next pass).

Transport (caller -> worker). A repository that installed Knos and keeps no relay key of its own has NO Knos secret, so
it cannot call the Knos repository or its API with auth. Its workflow posts the GitHub Actions OIDC token it minted as
a comment with its own GITHUB_TOKEN (`post_token` writes that comment, `found` reads it):

    knos-fund: <jwt>      on the issue, after a maintainer's `/knos fund <amount>`; and with it, on a line of its own,
    knos-terms: <json>    the bounty's terms (the token carries only their hash); for a PRIVATE work order, funded by a
                          comment in its judge repository, 128 hex characters instead: its scope and its terms hash
    knos-proof: <jwt>     on the pull request, once it is merged and has met the bounty's terms
    knos-bind: <jwt>      on an issue in the claimer's own repository named knos-claim (the pinned claim workflow)
    knos-key: <jwt>       on an issue in drexthealpha/knos-oidc-rotate or drexthealpha/Knos (a key an issuer publishes,
                          named by GitHub's signature); for an issuer that is not GitHub or GitLab the comment starts
    knos-issuer: <url>    with the issuer's URL on a line of its own (the token carries only its hash)
    knos-take: <jwt>      on the issue, after `/knos take`: the work order is reserved for the taker
    knos-cancel: <jwt>    on the issue, after `/knos cancel`: the work order's funder gives notice
    knos-revert: <jwt>    the accepted change was reverted inside the order's warranty: the holdback goes back
    knos-rule: <jwt>      the ruling of the arbiter a work order named
    knos-verify: <jwt>    any GitHub Actions or GitLab CI token, or one of an issuer the verifier holds a key for (a
                          registered issuer's, or a private key): verified into an account another program can read,
                          and nothing more; 20 a day for one repository
    knos-eval: <jwt>      an evaluation for knos_meter to count (`knosm:eval:`), from the buyer's repository; and under
                          the same marker a batch of them (`knosm:batch:`) and the seller's own count (`knosm:claim:`)
    knos-gate: <jwt>      on the "knos tokens" issue of drexthealpha/Knos, by program.yml's gate job: GitHub's word that
                          its runner built one program's executable (`gate:<program>:<hash>`), for examples/upgrade_gate
    knos-withdraw: <b64>  not a token: a passkey wallet's signed withdrawal (knos.settle.v2.passkey.request), on an
                          issue of its owner's repository named knos-claim. The relay sends it and pays its fee; the
                          money goes where the passkey signed, 20 a day for one repository
    /knos passkey-fund <base64url>   not a token and not posted by a workflow: the line the site's Buy page shows after a
                          passkey signed a funding (knos.settle.v2.passkey_fund), pasted on the issue it funds. The
                          relay sends it and pays its fee and the order's rent, 20 a day for one repository, and
                          answers on the issue where its GitHub token may write (always in its log)
    knos-veto: <jwt>      the first deployment's, as before: a bounty funded there finishes there
    knos-claim: <jwt>

The marker only says where to look. What a token does is fixed by its audience, and so is where it goes: `knos:` to the
first deployment's relay (knos.settle.relay), `knos2:`, `knos3:` (work orders), `knosm:` (the meter) and `gate:` to the second's
(knos.settle.v2.relay, whose table KINDS names every audience it carries), and a key token (`knos-oidc:key:`) to both.

Posting the token in public is acceptable ONLY because it is not a bearer credential here: its audience names one
action, the escrow accepts it for at most an hour and guards each action against replay, and it is valid only from the
workflow commit the bounty pinned. Whoever relays it first only pays the fees; the money goes where the token says.

Discovery (worker finds the comments). Public reads, no install. The repositories the worker knows (those it found a
token in during the last two days, kept in KNOS_HOME; the ones in KNOS_RELAY_REPOS; the rotate repository; its own) are
read on every pass with conditional requests: GitHub answers 304 while nothing is new, which costs nothing against the
rate limit, so a pass every few seconds is cheap. (Past fifteen known repositories, the ones with the newest tokens are
read on every pass and the others a few a pass, in turn.) New repositories are found at most every 30 seconds: one
issue search for the word every token comment carries (`knosrelay`), and the recently pushed repositories of owners
served before. And without any search: once a minute the chain is read for every repository that has an open job or
work order (`watched`), and those are read on every pass, so the proof of a funded issue is found even when GitHub's
search is late or down. With no GH_TOKEN GitHub allows 60 requests an hour, which is one pass now and then, not a worker.

Result (worker -> caller). The worker cannot write to other repositories. It appends one line per relayed token to the
open issue labelled `knos-relay` in its own repository (its own GITHUB_TOKEN can do that):

    knos-relay <kind> <owner/repo>#<n> <token id> ok sig=<s1>[,<s2>...] [queue=<s>] [workflow=<s>] [wait=<s>] [chain=<s>] queued_at=<t> seen_at=<t> sent_at=<t> confirmed_at=<t> note=<what happened, in words> t=<seconds>
    knos-relay <kind> <owner/repo>#<n> <token id> fail <reason>

The four `_at` fields are on EVERY ok line, whoever relayed (this worker, a job that relays its own token, `knos
relay --token-file`: all three write the line with `log_line` and `times`). They are Unix seconds on the relay's
clock: `queued_at` the token was posted for a relay (its comment's creation; handed over, for a relay that reads no
comment), `seen_at` this relay picked it up, `sent_at` it handed its first transaction to the cluster, `confirmed_at`
its last transaction confirmed. A token the chain already showed done (`already`) was sent by someone else: its line
says `sent_at=-` and `confirmed_at=-`, never a time this relay did not measure. scripts/latency_stages.py turns
them into the five states of a payment (received, accepted, submitted, confirmed, finalized: docs/RELAY.md).

`t` is the time from the comment's creation to the token's last transaction. The four before the note say where the
time went, in seconds, each only when it could be measured (`stages`): `queue`, from the comment or the merge that
started the workflow run to the run's start; `workflow`, from there to the token's comment; `wait`, from that comment
to this relay picking it up; `chain`, from there to the last confirmation. (`wait` + `chain` is `t`.) The caller waits for the line that names
its token id (`wait_for`) and comments the verdict with its own token. A line with that id is a verdict on the token
itself, the same whoever posted it. A comment that holds a token it cannot carry (someone's copy under another marker,
or with other terms) is logged with `-` for the id, so it answers nobody who waits for the token.

What a token can wait for, and the bound of each, is in docs/RELAY.md ("Where a token waits"). Three rules hold here:

    journaled before sent   a token the relay has seen is written to its notes (`journal`, in KNOS_HOME/ghrelay.json:
                            the queue of knos.settle.v2.relayq, which carries up to 4 tokens of different owners at
                            once) before its first transaction. A relay killed between the send and the confirmation finds
                            the token again on its next pass and sends it again: the chain takes a token once, so the
                            second send moves nothing (tests/test_relay_failures.py runs it on LiteSVM).
    retried until an answer a failure that says nothing about the token (the cluster or GitHub did not answer) is
                            tried again on the next pass, then after 10, 20, ... 60 seconds, and from then every 60
                            seconds while the chain would still take the token (an hour past its `exp`). There is no
                            random part: the same failures give the same times. A token with no readable `exp` gets
                            MAX_TRIES passes. So does one the program itself refused with a number a twin run can
                            cause (67, 69, 84; "answered" in the relay's result): if it does not clear, it is a refusal.
    a refusal is final      what the program or the relay's own reads refuse is logged with the reason and never sent
                            again.

Once a minute the log repository's own worker (`publishes_status`) rewrites one comment of the log, the status line
(`status_line`, `publish_status`):

    knos-relay status - - ok at=<time> round=<s> tokens=<n> waiting=<n> oldest=<s> retried=<n> refused=<n>

`round` is how long the last pass took and `tokens` what it carried; `waiting` the tokens seen and not yet answered,
`oldest` the age of the first of them; `retried` and `refused` count the last 24 hours. web/status_data.js reads it.
Under it, in the same comment, the last ROUNDS (ten) tokens the relay took up, newest first, one line each (`rounds`):

    knos-relay round <owner/repo>#<n> <first 8 of the token id> ok order=<address or -> state=<state> seconds=<s> kind=<kind>

`state` is the journal's, as the notes spell it (sending, waiting, confirmed, refused, expired: the queue's leased,
queued, done and dead, knos.settle.v2.relayq) and `seconds` the time from the token's
comment to its answer (to now, for one still waiting). The line holds eight characters of the id, so it never answers
a job that waits for the token (`wait_for` asks for all sixteen), and the comment stays under 2,600 characters.

One more rule, for two runs that relay together at a handover: LOG NOTHING THE LOG ALREADY HAS. A token the chain
showed done before this relay sent anything (`already`, on this relay's first try of it) is not logged at once: the
run that sent it is about to write its line. The line is held (`held`, in the notes) and the log is read again on the following passes; it is
dropped when the log answers for the token, and posted after ALREADY_WAIT seconds when it does not (a stranger
carried it, and nobody else will say so).
"""

from __future__ import annotations

import base64
import calendar
import copy
import hashlib
import json
import math
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .. import ghwords

TOKEN = re.compile(r"knos-(proof|fund|bind|veto|claim|key|verify|eval|take|cancel|revert|rule|gate):\s*(eyJ[\w-]+\.[\w-]+\.[\w-]+)")
WITHDRAW = re.compile(r"knos-withdraw:\s*([A-Za-z0-9+/_-]{200,4000}={0,2})")    # a passkey wallet's withdrawal request: no token, see knos.settle.v2.passkey.request
# a passkey's funding, as the Buy page writes it (the pattern of knos.settle.v2.passkey_fund.LINE, kept equal by a test)
PASSKEY_FUND = re.compile(r"/knos passkey-fund\s+([A-Za-z0-9_-]{300,6000})")
CLAIM_REPO = "/knos-claim"       # a withdrawal request is read only in a repository of this name (its owner's own, as for a claim)
# a fund token's terms, in the same comment: the terms JSON, or (a private order) its scope and terms hash as 128 hex characters
TERMS = re.compile(r"^knos-terms:[ \t]*(\{.*\}|[0-9a-f]{128})[ \t\r]*$", re.M)
ISSUER = re.compile(r"^knos-issuer:[ \t]*(https://[!-~]{1,192})[ \t\r]*$", re.M)     # the URL of the issuer whose key a key token names, in the same comment
MARK = "knosrelay"   # one word every token comment carries, so one search finds them all
ROTATE_REPO = "drexthealpha/knos-oidc-rotate"
RELAY_KIND = {"proof": "pay"}   # the comment marker says proof; the relays call that audience pay
# knos_meter's three audiences are all posted as knos-eval: (knos attest --kind eval|batch|claim): one evaluation, the
# buyer's count of a batch, the seller's own count of it
METER_KINDS = ("eval", "batch", "claim")
LOG_LABEL = "knos-relay"
LOG_BOT = "github-actions[bot]"  # who writes the log: the log repository's own workflow. Nobody else's line counts.
# The repository the relay keeps its public log in, and whose own issues it always scans: the one whose worker.yml runs
# it (worker.yml passes its own name), Knos's by default.
HOME_REPO = os.environ.get("KNOS_RELAY_LOG_REPO") or "drexthealpha/Knos"
MAX_TRIES = 12          # failed passes a token gets when the failure may clear (the cluster dropped it, a twin run) and its expiry cannot be read
LATE = 3600             # the chain takes a token until this long after its `exp` (knos.settle.v2.oidc.LATE); until then a failure that may clear is tried again
BACKOFF_MOST = 60       # the longest a token is left alone between two tries, in seconds
REST_MOST = 3600        # the longest the relay stays away from GitHub because GitHub asked it to (its hourly limit resets within the hour)
HORIZON = 70 * 60       # how far back a pass looks: a token is accepted for an hour
SEARCH_EVERY = 30       # seconds between two searches for repositories the worker does not know yet
ALREADY_WAIT = 15       # seconds a line about a token someone else carried waits for that someone's own line in the log
ROUNDS = 10             # tokens the status comment lists under its counts, newest first
CRANK_EVERY = 60        # seconds between two rounds of what needs no token (refunds, held payments), in `serve`
CHAIN_EVERY = 60        # seconds between two reads of the chain for the repositories that have money waiting on a proof
CHAIN_REPOS = 100       # of those, at most this many are read on every pass (a pass with nothing new is a 304 each)
CHAIN_NAMES = 20        # repository ids whose names GitHub is asked for in one read of the chain
KNOWN_FOR = 2 * 86_400  # a repository is known this long after its last token
EVERY_PASS = 15         # known repositories read on every pass: the ones whose tokens are newest
IN_TURN = 5             # of the other known ones, this many a pass, in turn (GitHub allows 900 requests a minute)
VERIFY_PER_DAY = 20     # verify-only tokens carried for one repository in a day (each locks rent for an hour)
PASSKEY_FUND_PER_DAY = 20   # passkey fundings sent for one repository in a day (the relay pays each fee and the rent of the order's two accounts)
WITHDRAW_PER_DAY = 20   # passkey withdrawals sent for one knos-claim repository in a day (the relay pays each fee, and a new wallet's rent)
API = "https://api.github.com/"


def claims(jwt: str) -> dict:
    body = jwt.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def token_id(jwt: str) -> str:
    """What the relay log names a token by (never the token itself)."""
    return hashlib.sha256(jwt.strip().encode()).hexdigest()[:16]


def checks_hash(root: Path) -> str:
    """sha256 over the acceptance directory: for each file, sorted by its posix path relative to `root`,
    "<path>\\0<sha256 hex of the bytes>\\n"."""
    h = hashlib.sha256()
    for f in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix()):
        h.update(f"{f.relative_to(root).as_posix()}\0{hashlib.sha256(f.read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()


def _stamp(t: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _unix(stamp) -> float | None:
    try:
        return float(calendar.timegm(time.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ")))
    except ValueError:
        return None


# ---- GitHub (GH_TOKEN is the worker's own GITHUB_TOKEN, used only for rate limits and its own log) -----------------

class Hub:
    """GitHub's REST API as the worker reads it. Every GET is conditional: an answer is kept with its ETag and asked
    for again with If-None-Match, and GitHub's 304 ("what you have is current") costs nothing against the rate limit.
    So reading a repository that has nothing new is one cheap request, however often it is done."""

    def __init__(self, urlopen=None, clock=time.time):
        self.kept: dict[str, tuple[str, object]] = {}   # path -> (its ETag, the answer)
        self.fresh = self.same = 0                      # answers that were new, and 304s
        self.rest = 0.0                                 # GitHub asked not to be asked again before this time (a rate limit)
        self._open, self._clock = urlopen or urllib.request.urlopen, clock

    def _limited(self, e: urllib.error.HTTPError) -> None:
        """A 403 or 429 that is a rate limit says how long to stay away: `Retry-After` seconds, or until
        `X-RateLimit-Reset` when nothing remains, or (a 429 that names neither) a minute. Asking again before then
        makes GitHub's secondary limit last longer, so until then nothing is asked at all (`_resting`). A 403 that
        names no limit is one path's own refusal and rests nothing."""
        if e.code not in (403, 429):
            return
        head: Any = e.headers or {}
        after, reset = str(head.get("Retry-After") or ""), str(head.get("X-RateLimit-Reset") or "")
        wait = (int(after) if after.isdigit() else int(reset) - self._clock() if str(head.get("X-RateLimit-Remaining")) == "0" and reset.isdigit()
                else 60 if e.code == 429 else 0)
        if wait > 0:
            self.rest = max(self.rest, self._clock() + min(wait, REST_MOST))

    def _resting(self, what: str) -> None:
        left = self.rest - self._clock()
        if left > 0:
            raise RuntimeError(f"GitHub asked for {left:.0f} more seconds without requests (its rate limit): {what} was not asked")

    def _request(self, path: str, data: dict | None = None, method: str | None = None, etag: str | None = None):
        head = {"Accept": "application/vnd.github+json", "User-Agent": "knos"}
        tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if tok:
            head["Authorization"] = f"Bearer {tok}"
        if etag:
            head["If-None-Match"] = etag
        if data is not None:
            head["Content-Type"] = "application/json"
        return urllib.request.Request(API + path, data=None if data is None else json.dumps(data).encode(), headers=head, method=method)

    def get(self, path: str):
        kept = self.kept.get(path)
        self._resting(path)
        try:
            with self._open(self._request(path, etag=kept[0] if kept else None), timeout=10) as resp:
                got, etag = json.loads(resp.read() or b"null"), resp.headers.get("ETag")
        except urllib.error.HTTPError as e:
            if e.code == 304 and kept:
                self.same += 1
                return kept[1]
            self._limited(e)
            raise RuntimeError(f"GitHub answered {e.code} for {path}") from None
        except (OSError, ValueError) as why:
            raise RuntimeError(f"GitHub did not answer for {path}: {why}") from None
        self.fresh += 1
        if etag:
            self.kept[path] = (etag, got)
        return got

    def send(self, path: str, data: dict, method: str = "POST"):
        self._resting(f"{method} {path}")
        try:
            with self._open(self._request(path, data, method), timeout=30) as resp:
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as e:
            self._limited(e)
            raise RuntimeError(f"GitHub answered {e.code} for {method} {path}") from None
        except (OSError, ValueError) as why:
            raise RuntimeError(f"GitHub did not answer for {method} {path}: {why}") from None


_HUB = Hub()


def _api(path: str) -> list | dict:
    return _HUB.get(path)


def discover(since: str, state: dict, getter=_api) -> set[str]:
    """Repositories that may hold a token: the search, the owners served before, and the ones always read."""
    repos = {r.strip() for r in os.environ.get("KNOS_RELAY_REPOS", "").split(",") if "/" in r}
    repos.add(ROTATE_REPO)
    try:
        res = getter(f"search/issues?q=%22{MARK}%22+in:comments+updated:%3E={since[:10]}&sort=updated&order=desc&per_page=50")
        for it in res.get("items", []):
            repos.add("/".join(it["repository_url"].split("/")[-2:]))
    except Exception:  # noqa: BLE001, S110 - search is one source of several
        pass
    for owner in set(state.get("owners", [])) | {HOME_REPO.split("/")[0]}:
        try:
            for r in getter(f"users/{owner}/repos?sort=pushed&per_page=30"):
                if r.get("pushed_at", "") >= since[:10]:
                    repos.add(r["full_name"])
        except Exception:  # noqa: BLE001, S110
            pass
    repos.add(HOME_REPO)     # Knos funds its own issues the same way, and calls the rotate workflow from here
    return repos


def watched(ledger, state: dict, now: float, getter=_api) -> set[str]:
    """The repositories that have money waiting on a proof, by name, from the chain alone: every repository id with
    an open job or work order (knos.settle.v2.relay.open_repositories), read at most every CHAIN_EVERY seconds. The
    chain knows a repository by its id; GitHub's `repositories/<id>` gives its name, asked once and kept in `state`.
    A chain or a GitHub that does not answer leaves what was known."""
    kept = state.setdefault("chain", {"at": 0, "ids": []})
    names = state.setdefault("names", {})
    if now - kept.get("at", 0) >= CHAIN_EVERY:
        try:
            from ..settle.v2 import relay as second
            kept.update(at=now, ids=sorted(second.open_repositories(ledger)))
        except Exception as why:  # noqa: BLE001 - the cluster did not answer: the last answer stands, and it is asked again next pass
            print(f"watched: {type(why).__name__}: {why}", file=sys.stderr)
        state["unnamed"] = [i for i in kept["ids"] if str(i) not in names]
        for gone in set(names) - {str(i) for i in kept["ids"]}:
            del names[gone]
    # CHAIN_NAMES names a pass, each id once after a read of the chain: a relay that starts with no notes and many open
    # repositories has them all within a few passes (it used to ask for twenty a minute)
    ask, state["unnamed"] = list(state.get("unnamed", []))[:CHAIN_NAMES], list(state.get("unnamed", []))[CHAIN_NAMES:]
    for rid in ask:
        try:
            names[str(rid)] = str(getter(f"repositories/{rid}")["full_name"])
        except Exception:  # noqa: BLE001, S110 - a private or deleted repository, or GitHub did not answer: asked again at the next read
            pass
    return {names[str(i)] for i in kept["ids"][:CHAIN_REPOS] if str(i) in names and "/" in names[str(i)]}


class Found(tuple):
    """One token a comment carries: (marker kind, issue or pull request number, jwt, comment author). It also knows
    `terms`, what travels with the token on a line of the same comment (a fund token's terms JSON, from `knos-terms:`;
    a key token's issuer URL, from `knos-issuer:`), and `created`, when the comment was posted (unix time; None when
    GitHub did not say)."""
    terms: bytes | None
    created: float | None

    def __new__(cls, kind: str, number: int, jwt: str, who: str, terms: bytes | None = None, created: float | None = None):
        self = super().__new__(cls, (kind, number, jwt, who))
        self.terms, self.created = terms, created
        return self


def tokens(comments: list, since: str = "") -> list[Found]:
    """Every token in GitHub's issue comments that were posted at or after `since`."""
    out = []
    for c in comments:
        if str(c.get("created_at") or since) < since:       # GitHub's times are ISO 8601 in UTC: they sort as text
            continue
        body = c.get("body") or ""
        beside = {"fund": TERMS.search(body), "key": ISSUER.search(body)}
        for kind, jwt in [*TOKEN.findall(body), *(("withdraw", asked) for asked in WITHDRAW.findall(body)),
                          *(("passkey-fund", line) for line in PASSKEY_FUND.findall(body))]:
            out.append(Found(kind, int(c["issue_url"].rsplit("/", 1)[1]), jwt, (c.get("user") or {}).get("login", ""),
                             hit.group(1).encode() if (hit := beside.get(kind)) else None, _unix(c.get("created_at"))))
    return out


def found(repo: str, since: str, getter=_api) -> list[Found]:
    """Every token in `repo`'s comments since `since`. The request is the same on every pass (the newest hundred
    comments), so a pass with nothing new is a 304; an older page is read only when a whole page is newer than `since`."""
    out: list[Found] = []
    for page in range(1, 6):
        got = getter(f"repos/{repo}/issues/comments?sort=created&direction=desc&per_page=100" + (f"&page={page}" if page > 1 else ""))
        out += tokens(got, since)
        if len(got) < 100 or str(got[-1].get("created_at") or "") < since:
            break
    return out


def token_comment(kind: str, jwt: str, terms: bytes | str | None = None) -> str:
    """The comment a workflow posts for a relayer to find: the marker and the token, what travels with it on a line of
    its own (a fund token's terms; under the `key` marker, the issuer's URL, first), and the word the search finds.
    `found` reads exactly this."""
    beside = terms.decode() if isinstance(terms, bytes) else terms
    lines = ([f"knos-issuer: {beside}"] if beside and kind == "key" else []) + [f"knos-{kind}: {jwt}"] + ([f"knos-terms: {beside}"] if beside and kind != "key" else [])
    return "\n".join(lines) + f"\n\n<sub>{MARK}: a GitHub-signed token. Anyone can carry it to Solana, and it can only do what it says.</sub>"


def post_token(repo: str, number: int, kind: str, jwt: str, terms: bytes | str | None = None, github=None) -> str:
    """Posts a token for a relayer to find: `token_comment` on issue or pull request `number` of `repo`, with the
    caller's own GitHub token (`github(path, data)` posts to GitHub's API; default: this module's). Returns the id
    the relay log will name the token by, which is what `wait_for` takes."""
    (github or _HUB.send)(f"repos/{repo}/issues/{number}/comments", {"body": token_comment(kind, jwt, terms)})
    return token_id(jwt)


# ---- the relay -----------------------------------------------------------------------------------------------------

def audience(jwt: str) -> str:
    """A token's audience, as it says it (unverified); "" for what is not a token."""
    try:
        aud = claims(jwt)["aud"]
        return aud if isinstance(aud, str) else str(aud[0])
    except Exception:  # noqa: BLE001 - not a token: the relay says so
        return ""


def carry(ledger, payer, jwt: str, terms: bytes | None = None) -> dict:
    """One token to the deployment its audience names: `knos:` to the first relay, everything else to the second
    (which hands a key token of GitHub's or GitLab's to the first as well). `terms`: a fund token's terms JSON, or
    the issuer URL of a key token that names its issuer by URL. The relay's result."""
    from ..settle import relay as first
    from ..settle.v2 import relay as second
    return first.submit(ledger, payer, jwt) if audience(jwt).startswith("knos:") else second.submit(ledger, payer, jwt, terms)


def fits(kind: str, named: str | None, aud: str | None = None) -> bool:
    """Whether a comment's marker `kind` may carry what the relays call `named`: its own name (proof: pay), and under
    `eval` any of the meter's three. `aud`, when known, keeps the meter's `claim` apart from the first deployment's
    (`knos:claim:`), which has a marker of its own."""
    if aud is not None and (aud.startswith("knosm:") or (kind == "eval" and named != "eval")):
        return kind == "eval" and named in METER_KINDS and aud.startswith("knosm:")
    return named == RELAY_KIND.get(kind, kind) or (kind == "eval" and named in METER_KINDS)


def misposted(kind: str, jwt: str, terms: bytes | None = None) -> str | None:
    """Why a comment cannot carry the token it holds, or None: its marker does not fit the token's audience, or (a
    fund token of the second deployment) its `knos-terms:` line is not the terms the audience names. Anyone can copy
    a token into a comment of their own, so such a comment says nothing about the token: it is passed over, and the
    token is still carried from the comment that posts it rightly."""
    from ..settle import relay as first
    from ..settle.v2 import relay as second
    aud = audience(jwt)
    named = (first if aud.startswith("knos:") else second).kind_of(aud)
    if kind == "verify":
        return f"it is a Knos {named} token, which is carried under its own marker" if named else None
    if named is not None and not fits(kind, named, aud):
        return f"posted as knos-{kind}, but its audience is a {named} token's"
    if named == "fund" and aud.startswith(("knos2:", "knos3:")) and not second.carries_terms(aud, terms):
        return "its `knos-terms:` line is missing, or is not the terms the token names"
    if aud.startswith("knos-oidc:ikey:") and (terms is None or hashlib.sha256(terms).hexdigest() != (aud.split(":") + [""] * 3)[2]):
        return "its `knos-issuer:` line is missing, or is not the issuer the token names"
    return None


def relay_one(ledger, payer, kind: str, jwt: str, submit=None, terms: bytes | None = None, where: tuple[int, int] | None = None) -> dict:
    """Send one token a comment carried under the marker `kind` to the chain (`carry`); under the `verify` marker it
    is only verified. A comment that cannot carry its token (`misposted`) is refused before anything is sent. Returns
    the relay's result, plus "note": what happened in words. `submit(ledger, payer, jwt)`: a relay to use instead.
    `where`: for a passkey's funding line (`kind` passkey-fund, `jwt` the line's base64url text), the repository id and
    the issue its comment is on."""
    if submit is not None:
        r = submit(ledger, payer, jwt)
    elif kind == "withdraw":
        from ..settle.v2 import relay as second
        r = second.withdraw(ledger, payer, jwt)
    elif kind == "passkey-fund":
        from ..settle.v2 import relay as second
        r = second.passkey_fund(ledger, payer, jwt, *(where or (None, None)))
    else:
        wrong = misposted(kind, jwt, terms)
        if wrong:
            return {"ok": False, "kind": None, "why": wrong}
        if kind == "verify":
            from ..settle.v2 import relay as second
            r = second.verify_only(ledger, payer, jwt)
        else:
            r = carry(ledger, payer, jwt, terms)
    if r.get("ok") and not fits(kind, r.get("kind")):
        return {"ok": False, "why": f"marker {kind} but audience {r.get('kind')}"}
    if r.get("ok"):
        r["note"] = note(r)
    return r


def _usdc(units: int) -> str:
    return f"{units / 1_000_000:.2f}"


def _day(t: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))


def _note2(r: dict) -> str | None:
    """What a result of the second deployment's relay means, in words; None for a result that is not one of its."""
    k = r["kind"]
    if k == "fund" and "order" in r:
        what = ("a pull request for this issue is merged and meets the order's terms" if r["mode"] == 0
                else "the issue's acceptance checks pass on a pull request that meets the order's terms")
        money = "test USDC" if r["faucet"] else f"from balance {r['balance']}"
        if r.get("private"):        # nothing of the repository, the issue or the terms is on chain, and nothing of them is said here
            return (f"{_usdc(r['amount'])} {money} is in escrow as a private work order (its funder paid a fee of {_usdc(r['fee'])} on top), paid when a run "
                    f"in its judge repository (id {r['repo_id']}) attests that its terms were met. Unpaid by {_day(r['deadline'])}, it goes back to its funder. "
                    f"Order {r['order']}.")
        return (f"{_usdc(r['amount'])} {money} is in escrow as a work order for issue #{r['issue']} (its funder paid a fee of {_usdc(r['fee'])} on top), "
                f"paid when {what}. Unpaid by {_day(r['deadline'])}, it goes back to its funder. Order {r['order']}.")
    if k == "pay" and "order" in r and r.get("quorum") and not r.get("paid"):       # recorded, not paid: the reasons travel in the line
        return ghwords.quorum_note(r["order"], r["quorum"])
    if k in ("pay", "rule") and "order" in r:
        sent, held = [p for p in r["paid"] if p["to"]], [p for p in r["paid"] if not p["to"]]
        out = [f"{_usdc(p['amount'])} was paid to {p['to']} (GitHub user id {p['payee_id']})" for p in sent]
        words = (", ".join(out) + f" for order {r['order']}.") if out else ""
        if held:
            words += (f"{_usdc(held[0]['amount'])} of order {r['order']} is held for GitHub user id {held[0]['payee_id']} until {_day(held[0]['held_until'])}. "
                      "It is sent once they name a wallet: `knos claim <their Solana address>`, or "
                      "https://drexthealpha.github.io/Knos/#claim. After that date it goes back to its funder.")
        if r.get("held_back"):
            words += (f" {_usdc(r['held_back'])} more is held back until {_day(r['warranty_until'])}, the end of the order's warranty: it follows then, "
                      "unless the change is reverted first.")
        if "left" in r:
            words += f" The standing order stays open with {_usdc(r['left'])} left." if r["left"] else " That was the last of the standing order."
        return ("The arbiter ruled. " if k == "rule" else "") + words
    if k == "take" and "order" in r:
        return f"Order {r['order']} (issue #{r['issue']}) is reserved for GitHub user id {r['taker_id']} until {_day(r['reserved_until'])}."
    if k == "cancel" and "order" in r:
        return (f"Order {r['order']} (issue #{r['issue']}) is cancelled with notice: a pull request that meets its terms before {_day(r['deadline'])} is "
                "still paid; after that the money and the fee go back to where they came from.")
    if k == "revert" and "order" in r:
        return (f"{_usdc(r['amount'])} that order {r['order']} held went back to its funder: the change it paid for was reverted inside its warranty "
                f"(commit {r['head'][:7]}).")
    if k == "bind" and r.get("org"):
        got = r["settled"]
        more = f" {len(got)} held payment{'s' if len(got) != 1 else ''}, {_usdc(sum(s['amount'] - s['fee'] for s in got))} in all, went there." if got else ""
        return f"GitHub organisation id {r['user_id']} is now paid at {r['wallet']} (its member with id {r['by']} ran the claim).{more}"
    if k == "key" and "issuer" in r:
        did = ("registered with the verifier: it verifies after a day's wait, once the guardian has approved it" if r["added"]
               else "refreshed: the verifier keeps it 30 days from now" if r["refreshed"] else "already known to the verifier")
        return f"Key {r['key']} of the issuer {r['issuer']} {did}."
    if k == "fund" and "faucet" in r:
        what = ("the pull request that closes this issue is merged and meets the bounty's terms" if r["mode"] == 0
                else "the issue's acceptance checks pass on a pull request that meets the bounty's terms")
        money = "test USDC" if r["faucet"] else f"from balance {r['balance']}"
        return (f"{_usdc(r['amount'])} {money} is in escrow for issue #{r['issue']}, paid when {what}. "
                f"Unpaid by {_day(r['deadline'])}, it goes back to its funder. Job {r['job']}.")
    if k == "pay" and "payee_id" in r:
        from ..settle.v2 import pay
        sent, held = [p for p in r["paid"] if p["to"]], [p for p in r["paid"] if not p["to"]]
        test = {str(pay.faucet_mint()), str(pay.USDC_DEVNET)}       # the two mints that are test USDC; any other is named by nothing here
        net = lambda ps: _usdc(sum(p["amount"] - p["fee"] for p in ps)) + (" test USDC" if all(p["mint"] in test for p in ps) else "")  # noqa: E731
        out = [f"{net(sent)} was paid to {sent[0]['to']} for issue #{r['issue']} (GitHub user id {r['payee_id']})."] if sent else []
        if held:
            out.append(f"{net(held)} is held for GitHub user id {r['payee_id']} for issue #{r['issue']} until {_day(held[0]['held_until'])}. "
                       "It is sent once they name a wallet: `knos claim <their Solana address>`, or "
                       "https://drexthealpha.github.io/Knos/#claim. After that date it goes back to its funder.")
        return " ".join(out)
    if k == "bind":
        got = r["settled"]
        more = f" {len(got)} held payment{'s' if len(got) != 1 else ''}, {_usdc(sum(s['amount'] - s['fee'] for s in got))} in all, went there." if got else ""
        return f"GitHub user id {r['user_id']} is now paid at {r['wallet']}.{more}"
    if k == "key" and "refreshed" in r:
        did = ("registered with the second verifier: it verifies after a day's wait, once the guardian has approved it" if r["added"]
               else "refreshed: the second verifier keeps it 30 days from now" if r["refreshed"]
               else f"not taken by the second verifier ({r['why']})" if r.get("why") else "already known to the second verifier")
        return f"Key {r['key']} {did}." + (" The first deployment added it." if (r.get("first") or {}).get("added") else "")
    if k == "eval" and "buyer_id" in r:
        verdict = "accepted" if r["accepted"] else "rejected"
        return (f"Counted: buyer {r['buyer_id']}, seller {r['seller_id']}, artifact {r['artifact']}, milestone {r['milestone']}, {verdict}. "
                f"Fee {_usdc(r['fee'])} from the buyer's credits; month {r['month']}.")
    if k in ("batch", "claim") and "root" in r:
        whose = "the seller's own count, at no fee" if k == "claim" else f"the buyer's count, fee {_usdc(r['fee'])} from the buyer's credits"
        return (f"Counted batch {r['seq']} of month {r['month']} for buyer {r['buyer_id']} and seller {r['seller_id']}: {r['count']} "
                f"evaluation{'s' if r['count'] != 1 else ''}, {r['accepted']} accepted ({whose}). Merkle root {r['root']}.")
    if k == "passkey-fund":
        from ..settle.v2 import relay as second
        return second.passkey_fund_reply(r).removeprefix("Knos: ")
    if k == "gate":
        return (f"Recorded at the upgrade gate: GitHub's runner built the executable {r['hash']} for program {r['program']} from commit {r['commit']} "
                f"(run {r['run_id']}). Record {r['record']}.")
    if k == "withdraw":
        return f"{r['amount']} of mint {r['mint']} (its smallest units) went from passkey wallet {r['wallet']} to {r['to']}, as its withdrawal number {r['nonce']}."
    if k == "verify":
        return (f"Verified. Account {r['account']} (payer {r['payer']}) holds the token's claims for a program to read "
                f"until {_day(r['exp'] + 3600)}.")
    return None


def note(r: dict) -> str:
    """One sentence for the verdict comment."""
    k = r["kind"]
    words = _note2(r)
    if words is not None:
        return words
    wait = lambda s: "at once" if not s else f"{s // 3600} h after" if s >= 3600 else f"{s} s after"  # noqa: E731
    if k == "fund":
        what = "a maintainer merges the pull request that closes this issue" if r["mode"] == 0 else "the acceptance checks pass"
        held = f" The payment is released {wait(r.get('review', 0))} that; until then /knos veto takes it back." if r.get("review") else ""
        return f"{_usdc(r['amount'])} test USDC is in escrow for issue #{r['issue']}, paid when {what}.{held} Job {r['job']}."
    if k == "pay":
        net = sum(p["amount"] - p["fee"] for p in r["paid"])
        hold = max(p["waits"] for p in r["paid"])
        when = "is now waiting under" if not hold else f"will be released in {wait(hold).replace(' after', '')} (a maintainer's /knos veto on the issue takes it back) to"
        return (f"{_usdc(net)} {when} GitHub user id {r['author_id']} for issue #{r['issue']}. "
                f"Claim it to any address: https://drexthealpha.github.io/Knos/#claim")
    if k == "veto":
        return f"{len(r['vetoed'])} payment(s) taken back."
    if k == "claim":
        return "Sent " + ", ".join(f"{_usdc(c['amount'])} of {c['mint'][:4]}…" for c in r["claimed"]) + f" to {r['address']}."
    return f"Key {r['key']} {'added' if r.get('added') else 'already known'}."


STAGES = ("queue", "workflow", "wait", "chain", "tries")       # the four stages, in seconds, and how many tries the token took when more than one


def stages(jwt: str, created: float | None, picked: float, done: float, get=None) -> dict[str, int]:
    """Where a carried token's time went, in whole seconds, each stage only when it could be measured: `queue` (the
    comment or the merge that started the workflow run, to the run's start) and `workflow` (the run's start to the
    token's comment) from GitHub's record of the run the token names (`repository`, `run_id`: one public read);
    `wait` (the token's comment to this relay picking it up) and `chain` (pickup to the last confirmation) from this
    relay's own clock. `created`: when the comment was posted; `get(path)` reads GitHub's API."""
    out: dict[str, int] = {}
    try:
        c = claims(jwt)
        run: Any = (get or _api)(f"repos/{c['repository']}/actions/runs/{int(c['run_id'])}")
        asked, began = _unix(run.get("created_at")), _unix(run.get("run_started_at"))
        if str(run.get("run_attempt", c.get("run_attempt", "1"))) == "1" and asked is not None and began is not None and began >= asked:
            out["queue"] = round(began - asked)        # (a re-run keeps the first attempt's creation time: its queue is not this)
        if began is not None and created is not None and created >= began:
            out["workflow"] = round(created - began)
    except Exception:  # noqa: BLE001, S110 - not a token, a private repository, or GitHub did not answer: those two are left out
        pass
    if created is not None and picked >= created:
        out["wait"] = round(picked - created)
    if done >= picked:
        out["chain"] = round(done - picked)
    return out


TIMES = ("queued_at", "seen_at", "sent_at", "confirmed_at")     # on every ok line, Unix seconds; `-` where this relay measured none


class Timed:
    """A ledger that notes when a relay handed it the first transaction and when the last one confirmed: the two
    times no relay's result carries. Everything else is the ledger's own (a method it lacks is still lacking).
    `start()` before each token; then `sent` and `confirmed` are that token's, or None when nothing was sent."""

    def __init__(self, ledger, clock=time.time) -> None:
        self.__dict__.update(_ledger=ledger, _clock=clock, sent=None, confirmed=None)

    def start(self) -> "Timed":
        self.__dict__.update(sent=None, confirmed=None)
        return self

    def __getattr__(self, name: str):
        got = getattr(self._ledger, name)
        if name not in ("send", "send_all"):
            return got

        def timed(*args, **kw):
            if self.sent is None:
                self.__dict__["sent"] = self._clock()
            out = got(*args, **kw)
            self.__dict__["confirmed"] = self._clock()
            return out
        return timed

    def __setattr__(self, name: str, value) -> None:
        setattr(self._ledger, name, value)          # (a relay turns `takes_v1` off on the ledger it was given)


def times(r: dict, queued: float | None, seen: float, done: float, ledger=None) -> dict:
    """The four times of one relayed token, for `log_line`: `queued` (its comment's creation; None: it was handed
    over, which is when it was seen), `seen` (picked up), then the first send and the last confirmation as `ledger`
    (a `Timed`) noted them. A relay that sent through something else is taken to have sent when it picked the token
    up and confirmed when it answered. A token the chain already showed done, or one that needed nothing sent, has
    neither: this relay sent nothing."""
    sent, confirmed = getattr(ledger, "sent", None), getattr(ledger, "confirmed", None)
    if r.get("already") or not r.get("sigs"):
        sent = confirmed = None
    elif sent is None or confirmed is None:
        sent, confirmed = seen, done
    return {"queued_at": seen if queued is None else queued, "seen_at": seen, "sent_at": sent, "confirmed_at": confirmed}


def log_line(kind: str, repo: str, n: int, jwt: str, r: dict, t: int | None = None, parts: dict | None = None,
             times: dict | None = None) -> str:
    """The public log's line for one token. `t`: seconds from its comment's creation to its last transaction.
    `parts`: what `stages` measured; `times`: the four of TIMES (`times(...)`), a tenth of a second fine, `-` for
    one that was not measured. Both are written before the note (which may hold any words)."""
    head = f"knos-relay {kind} {repo}#{n} {token_id(jwt)}"
    if not r["ok"]:
        return f"{head} fail {' '.join(str(r['why']).split())}"
    first = " (another relayer carried it first)" if r.get("already") else ""
    spent = "".join(f" {k}={int(parts[k])}" for k in STAGES if parts and k in parts)
    spent += "".join(f" {k}={'-' if times.get(k) is None else format(float(times[k]), '.1f')}" for k in TIMES) if times is not None else ""
    return f"{head} ok sig={','.join(r['sigs'][-3:]) or 'none'}{spent} note={r['note']}{first}" + (f" t={t}" if t is not None else "")


def own_line(kind: str, repo: str, n: int, jwt: str, r: dict, queued: float | None, seen: float, done: float, ledger=None) -> str:
    """`log_line` for a relay that reads no comment (a job that relays its own token, `knos relay --token-file`):
    the same line the worker writes, with the same four times, so one reader covers every payment."""
    return log_line(kind, repo, n, jwt, {**r, "note": r.get("note") or (note(r) if r.get("ok") else "")}, max(0, round(done - (seen if queued is None else queued))) if r.get("ok") else None,
                    None, times(r, queued, seen, done, ledger))


_LOG: dict[str, int] = {}
_LOG_BODY: dict[str, str] = {}      # the body of a log issue as it was found, until `post_log` has seen that it says what it is


def _log_issue(repo: str = "", get=None) -> int | None:
    """The open issue labelled knos-relay in a repository: where its relay log is. None when it has none."""
    repo = repo or HOME_REPO
    if repo not in _LOG:
        res = (get or _api)(f"repos/{repo}/issues?labels={LOG_LABEL}&state=open&per_page=1")
        if not res:
            return None
        _LOG[repo] = int(res[0]["number"])
        _LOG_BODY[repo] = str(res[0].get("body") or "")
    return _LOG[repo]


def post_log(lines: list[str]) -> None:
    """Append lines to this relay's public log, as one comment. The log issue is made on first use."""
    if not lines:
        return
    n = _log_issue()
    if n is None:
        try:
            _HUB.send(f"repos/{HOME_REPO}/labels", {"name": LOG_LABEL, "color": "ededed"})
        except RuntimeError:
            pass        # the label is there already
        n = _LOG[HOME_REPO] = int(_HUB.send(f"repos/{HOME_REPO}/issues", {
            "title": "Knos relay log", "labels": [LOG_LABEL],
            "body": ghwords.MACHINE + "One line per token the always-on worker relayed (see src/knos/proof/ghrelay.py)."})["number"])
    elif HOME_REPO in _LOG_BODY:        # a log opened before 0.3.18 does not say it is one: its body is edited once to say so
        ghwords.say_machine(_HUB.send, f"repos/{HOME_REPO}/issues/{n}", _LOG_BODY.pop(HOME_REPO))
    while lines:                # a comment holds 65,536 characters
        take = max(1, next((i for i in range(1, len(lines) + 1) if sum(len(ln) + 1 for ln in lines[:i]) > 60_000), len(lines) + 1) - 1)
        _HUB.send(f"repos/{HOME_REPO}/issues/{n}/comments", {"body": "\n".join(lines[:take])})
        lines = lines[take:]


def wait_for(token_id: str, log_repo: str, timeout: float, every: float = 3.0, get=None) -> str | None:
    """The worker's log line for a token: `knos-relay <kind> <owner/repo>#<n> <token id> ok sig=... [queue= workflow=
    wait= chain=] note=... t=...` or `... fail <reason>`. Reads the public log of `log_repo` every `every` seconds for up to `timeout` seconds; None
    when no relayer has reported on the token by then. `get(path)` reads GitHub's API (default: this module's
    conditional reader, for which a log with nothing new costs nothing). Only lines the log repository's own workflow
    wrote count: anyone can comment on a public issue."""
    get = get or _api
    since, end = _stamp(time.time() - 300), time.monotonic() + timeout     # this clock and GitHub's may differ a little
    while True:
        try:
            n = _log_issue(log_repo, get)
            for page in range(1, 11) if n is not None else ():
                got = get(f"repos/{log_repo}/issues/{n}/comments?since={since}&per_page=100" + (f"&page={page}" if page > 1 else ""))
                for c in got:
                    if (c.get("user") or {}).get("login") != LOG_BOT:
                        continue
                    for line in (c.get("body") or "").splitlines():
                        if line.startswith("knos-relay ") and f" {token_id} " in line:
                            return line
                if len(got) < 100:
                    break
        except Exception:  # noqa: BLE001, S110 - GitHub did not answer: ask again
            pass
        left = end - time.monotonic()
        if left <= 0:
            return None
        time.sleep(min(every, left))


def answer(kind: str, jwt: str) -> str:
    """What `logged` holds for a comment's token: its marker and the token's id. A copy of the token posted under
    another marker is another matter (the `seen` notes keep them apart too), so its line never answers for this one."""
    return f"{kind} {token_id(jwt)}"


def logged(since: str, get=None) -> set[str]:
    """The tokens this relay's own log has a verdict on, as `answer` names them (marker and token id): the lines its
    workflow wrote since `since`. worker.yml starts the next run before this one stops, so two runs relay together for
    a few seconds: what the log answers already is neither carried nor logged again. Raises when GitHub does not
    answer."""
    get = get or _api
    n, out = _log_issue(HOME_REPO, get), set[str]()
    for page in range(1, 11) if n is not None else ():
        got = get(f"repos/{HOME_REPO}/issues/{n}/comments?since={since}&per_page=100" + (f"&page={page}" if page > 1 else ""))
        for c in got:
            if (c.get("user") or {}).get("login") == LOG_BOT:
                out.update(f"{m.group(1)} {m.group(2)}" for m in re.finditer(r"^knos-relay (\S+) \S+ ([0-9a-f]{16}) ", c.get("body") or "", re.M))
        if len(got) < 100:
            break
    return out


def _state_path() -> Path:
    from .. import paths
    return paths.home() / "ghrelay.json"


def _save(sp: Path, state: dict) -> None:
    """The notes, written whole or not at all: to a file beside them, then moved over them. A relay killed while it
    writes leaves the notes it had."""
    sp.parent.mkdir(parents=True, exist_ok=True)
    tmp = sp.with_name(sp.name + ".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, sp)


def expires(jwt: str) -> float | None:
    """When the chain stops taking a token: LATE after its `exp`. None when it does not say (not a token)."""
    try:
        return float(claims(jwt)["exp"]) + LATE
    except Exception:  # noqa: BLE001 - a passkey's line, or no token at all
        return None


def backoff(tries: int) -> int:
    """Seconds a token is left alone after its `tries`-th failure that may clear: 0, 0, 10, 20, ... up to BACKOFF_MOST.
    (Zero means the next pass, `--every` seconds later.) Nothing random: under a fake clock the times are the same."""
    return max(0, min(BACKOFF_MOST, 10 * (tries - 2)))


WAITING = ("sending", "waiting", "queued", "leased")        # a journal entry that has no answer yet: in flight when the notes were written, or to be tried again


def status_line(state: dict, now: float) -> str:
    """The relay's own account of itself, from its notes: when its last pass ran and how long it took, what waits,
    and what the last 24 hours saw. One line of the public log, rewritten in place (`publish_status`)."""
    journal, last = dict(state.get("journal", {})), dict(state.get("round", {}))
    # (a token whose comment was deleted, or left the hour the relay reads, is never tried again: it stops counting as waiting)
    waiting = [e for e in journal.values() if e.get("state") in WAITING and now - e.get("last", 0) <= HORIZON]
    recent = [e for e in journal.values() if now - e.get("last", 0) <= 86_400]
    oldest = max((now - e.get("seen", now) for e in waiting), default=0)
    return (f"knos-relay status - - ok at={_stamp(last.get('at', now))} round={int(last.get('took', 0))} tokens={int(last.get('tokens', 0))} "
            f"waiting={len(waiting)} oldest={int(oldest)} retried={sum(max(0, int(e.get('tries', 1)) - 1) for e in recent)} "
            f"refused={sum(1 for e in recent if e.get('state') in ('refused', 'expired'))}")


def rounds(state: dict, now: float, most: int = ROUNDS) -> list[str]:
    """The last `most` tokens the relay took up, newest first, one line each: where, the order or job when the relay
    named one, the journal's state, and the seconds from the token's comment to its answer (to `now` while it has
    none). So a round is found in the status comment without reading the notes. Never more than `most` lines of at
    most 230 characters."""
    out = []
    for e in sorted(dict(state.get("journal", {})).values(), key=lambda e: -float(e.get("last", 0)))[:max(0, most)]:
        open_ = e.get("state") in WAITING
        took = max(0, int(now - e.get("seen", now))) if open_ or e.get("took") is None else int(e["took"])
        out.append(f"knos-relay round {str(e.get('where') or '-')[:80]} {str(e.get('id') or '-')[:8]} ok order={str(e.get('order') or '-')[:44]} "
                   f"state={str(e.get('state') or '-')[:12]} seconds={took} kind={str(e.get('kind') or '-')[:16]}")
    return out


def publishes_status(env=None) -> bool:
    """Whether this relay writes a status line: the log repository's own worker does (GitHub says which workflow of
    which repository a run is: worker.yml of HOME_REPO), and nobody else, since only that workflow's lines count in
    the log. KNOS_RELAY_STATUS=1 turns it on for a relay of one's own that may write to its log; =0 turns it off."""
    env = os.environ if env is None else env
    asked = env.get("KNOS_RELAY_STATUS", "")
    if asked in ("0", "1"):
        return asked == "1"
    return env.get("GITHUB_REPOSITORY") == HOME_REPO and f"{HOME_REPO}/.github/workflows/worker.yml@" in env.get("GITHUB_WORKFLOW_REF", "")


def shares_notes(env=None) -> bool:
    """Whether this relay keeps its notes in the relay log too (`relayq.LogStore`), so that a runner with another disk
    sees them: the log repository's own worker does, in both its jobs, since only that workflow's lines count in the
    log. KNOS_RELAY_SHARED_NOTES=1 turns it on for a relay of one's own that may write to its log; =0 turns it off."""
    env = os.environ if env is None else env
    asked = env.get("KNOS_RELAY_SHARED_NOTES", "")
    if asked in ("0", "1"):
        return asked == "1"
    return env.get("GITHUB_REPOSITORY") == HOME_REPO and f"{HOME_REPO}/.github/workflows/worker.yml@" in env.get("GITHUB_WORKFLOW_REF", "")


_STORE: dict[str, Any] = {}         # the one store of this process, kept from pass to pass: what it read stays read


def log_store(env=None):
    """This process's `relayq.LogStore` on the relay log; None when this relay shares no notes there (`shares_notes`)."""
    if not shares_notes(env):
        return None
    if HOME_REPO not in _STORE:
        from ..settle.v2 import relayq
        _STORE[HOME_REPO] = relayq.LogStore(HOME_REPO, _api, _HUB.send, lambda: _log_issue(HOME_REPO), LOG_BOT)
    return _STORE[HOME_REPO]


def _github(path: str, data: dict | None = None, method: str | None = None):
    """GitHub as `knos.flow.Run` reaches it, through the worker's own reader: every GET is conditional, so a listing
    the worker holds already costs a 304. What the reader raises is an OSError here, as flow's own door raises."""
    try:
        return _HUB.send(path, data, method or "POST") if data is not None else _HUB.get(path)
    except RuntimeError as why:
        raise OSError(str(why)) from None


def claim_repos(env=None) -> set[str]:
    """The repositories this relay's PASS answers unfunded claims of payment in (knos.claim_guard): the ones
    KNOS_CLAIM_REPOS names, for a relay of one's own whose GitHub token may comment there. Nobody else's relay answers
    anything. The log repository's own worker names none: its sweep is a job of its own that holds no key
    (.github/workflows/worker.yml, job `claims`), so the job that pays fees never needs to write to a pull request."""
    env = os.environ if env is None else env
    return {r.strip() for r in env.get("KNOS_CLAIM_REPOS", "").split(",") if "/" in r}


def _claims(state: dict, now: float, ledger) -> list[dict]:
    """The claim guard's sweep, on this pass, for each of `claim_repos` that is due (at most once in
    claim_guard.SWEEP_EVERY seconds for one repository; when, is in the notes under `claims`). GitHub's timer for
    claims.yml is not kept to any time (docs/RELAY.md, "The claim guard on the worker"); this pass is. A listing that
    could not be read is an error line on the run's page, never silence, and is asked again a minute later."""
    repos = claim_repos()
    if not repos:
        return []
    from .. import claim_guard, flow
    swept = {r: t for r, t in dict(state.get("claims", {})).items() if r in repos}
    try:
        return claim_guard.sweep_served(lambda repo: flow.Run(repo, {}, github=_github, ledger=ledger), repos, swept, now,
                                        say=lambda words: print(words, file=sys.stderr))
    except claim_guard.Unread as why:
        print(f"::error title=claim guard::{why}", file=sys.stderr)
        return why.done
    finally:
        state["claims"] = swept


def publish_status(now: float | None = None) -> str | None:
    """Writes `status_line` into the log, with `rounds` under it: one comment, rewritten each time (its id is kept
    in the notes), so the log grows by nothing. A comment that is gone is posted anew. Returns the line; None when this relay writes none
    (`publishes_status`) or GitHub did not take it (the next minute tries again, and the status a reader sees is then
    old, which is itself the news)."""
    if not publishes_status():
        return None
    sp = _state_path()
    try:
        state = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None                 # no pass has finished yet: nothing to say
    line = status_line(state, now or time.time())
    body = "\n".join([line, *rounds(state, now or time.time())])
    try:
        n = _log_issue()
        if n is None:
            return None             # the log issue is made by the first line of a token
        try:
            if not state.get("status_comment"):
                raise RuntimeError("no status comment yet")
            _HUB.send(f"repos/{HOME_REPO}/issues/comments/{int(state['status_comment'])}", {"body": body}, "PATCH")
        except RuntimeError:
            state["status_comment"] = int(_HUB.send(f"repos/{HOME_REPO}/issues/{n}/comments", {"body": body})["id"])
            _save(sp, state)
    except Exception as why:  # noqa: BLE001 - GitHub said no: the status is a minute older
        print(f"relay status: {why}", file=sys.stderr)
        return None
    return line


def _origin(jwt: str, repo: str) -> str:
    """Where a verify-only token was issued: GitHub's repository id (GitLab's project id) as the token itself says,
    else the repository its comment is in."""
    try:
        c = claims(jwt)
    except Exception:  # noqa: BLE001 - not a token: the relay says so
        return repo
    return str(c["repository_id"]) if c.get("repository_id") else f"gitlab:{c['project_id']}" if c.get("project_id") else repo


def _repo_id(repo: str, state: dict, get=None) -> int | None:
    """GitHub's id of a repository, which is what the chain knows it by: asked once and kept in `state`. None when
    GitHub did not say."""
    ids = state.setdefault("ids", {})
    if repo not in ids:
        try:
            got: Any = (get or _api)(f"repos/{repo}")
            ids[repo] = int(got["id"])
        except Exception:  # noqa: BLE001 - GitHub did not answer, or the repository is gone: asked again on a later pass
            return None
    return ids[repo]


def _reply(repo: str, n: int, words: str) -> bool:
    """Answers a passkey's funding line on its own issue. The public worker's GitHub token writes only to the worker's
    repository, so there the answer is the log line alone; a relay whose token may write to `repo` (a repository that
    relays for itself) answers where the line was posted."""
    try:
        _HUB.send(f"repos/{repo}/issues/{n}/comments", {"body": words})
        return True
    except Exception as why:  # noqa: BLE001 - no write access there: the log has the verdict
        print(f"passkey-fund reply on {repo}#{n}: {why}", file=sys.stderr)
        return False


def _post(lines: list[str], state: dict) -> None:
    """Log lines now; the ones GitHub would not take are kept for the next pass, so that no verdict is lost."""
    try:
        post_log(lines)
    except Exception as why:  # noqa: BLE001 - GitHub said no, or answered something else: the lines are kept
        print(f"relay log: {why}", file=sys.stderr)
        state["unposted"] = (state.get("unposted", []) + lines)[-200:]


def _held(state: dict, now: float, since: str) -> list[str]:
    """The lines kept back about tokens someone else carried (`ALREADY_WAIT`): the ones the log answers for by now are
    dropped, the ones whose wait is over are posted (and returned), the rest stay in the notes."""
    held = list(state.get("held", []))
    if not held:
        return []
    try:
        answered = logged(since)
    except Exception:  # noqa: BLE001 - GitHub did not answer: a line whose wait is over is posted, the others wait on
        answered = set()
    due = [h for h in held if h.get("answer") not in answered and now >= h.get("until", 0)]
    state["held"] = [h for h in held if h.get("answer") not in answered and now < h.get("until", 0)]
    out = [str(h["line"]) for h in due]
    if out:
        _post(out, state)
    return out


def _cranks(ledger, payer, others=()) -> list[str]:
    """What needs no token, on both deployments: a proven payment whose wait is over, a bounty or a work order nobody
    proved in time, a held payment whose payee has bound a wallet since, a holdback whose warranty is over, and the
    rent of this relayer's stale token accounts, of spent tokens' markers and of the meter's marks of months past.
    `others`: the relay's further fee payers (KNOS_RELAY_KEYS): each takes back the rent of what it paid for."""
    from ..settle import relay as first
    from ..settle.v2 import relay as second
    now = int(ledger.now())
    rounds = (("settle", lambda: first.settle_due(ledger, payer, now), "a proven bounty's review window passed; paid"),
              ("refund", lambda: first.refund_due(ledger, payer, now), "a bounty passed its deadline unproven; refunded"),
              ("refund", lambda: second.refund_due(ledger, payer, now), "a bounty nobody could be paid from any more went back to its funder"),
              ("settle", lambda: second.settle_held(ledger, payer), "a held payment went to the wallet its payee has bound"),
              ("refund", lambda: second.refund_orders_due(ledger, payer, now), "a work order nobody could be paid from any more went back to its funder"),
              ("settle", lambda: second.settle_orders_held(ledger, payer), "a held work order went to the wallet its payee has bound"),
              ("release", lambda: second.release_orders_due(ledger, payer, now), "a work order's warranty ended with no revert; what it held back went to its payees"),
              ("sweep", lambda: second.sweep(ledger, payer, now), None),
              ("sweep", lambda: second.close_markers(ledger, payer, now), None),
              ("sweep", lambda: second.close_marks(ledger, payer, now), None),
              *(("sweep", lambda key=key, send=send: send(ledger, key, now), None)
                for key in others for send in (second.sweep, second.close_markers, second.close_marks)))
    lines = []
    for kind, send, words in rounds:
        try:
            lines += [f"knos-relay {kind} - - ok sig={sig} note={words}" for sig in send() if words]
        except Exception as why:  # noqa: BLE001 - best effort; the next round tries again
            print(f"{kind}: {why}", file=sys.stderr)
    return lines


def once(ledger=None, payer=None, now: float | None = None, crank: bool = True, workers: int | None = None) -> list[str]:
    """One pass: read what the repositories posted, queue each new token and carry what the queue holds, up to
    `workers` at once (knos.settle.v2.relayq; default its WORKERS, or KNOS_RELAY_WORKERS); send what needs no token
    (`crank`), and log the verdicts. Returns this pass's log lines.

    The journal is the queue. A token is queued (written down) when its comment is read, leased to a worker before
    its first transaction, and answered done, to be tried again, or dead with the reason. Tokens of one owner leave
    one at a time in the order GitHub issued them (`_lane`); tokens of different owners do not wait for each other, so
    one confirmation that takes a minute holds its own owner's tokens and nobody else's. Each token is tried at most
    once in a pass: one to be tried again waits for a later pass. When the queue is full, no comment is read until
    the time the pass says; what is posted meanwhile stays in its comment.

    verify, withdraw and passkey-fund lines are on the queue too, each in a lane of its own repository, so the day's
    limit of each is counted one at a time as before."""
    from ..settle.v2 import relayq
    sp = _state_path()
    skew = now - time.time() if now else 0.0            # a caller that gives the time (a drill, a test) gets its stages on that clock
    now = now or time.time()
    at: float = now
    hands = max(1, workers or int(os.environ.get("KNOS_RELAY_WORKERS") or relayq.WORKERS))
    me = f"sweep-{os.environ.get('GITHUB_RUN_ID') or os.getpid()}"
    # the pass's own time is the queue's: a wait of 10 s ends for the pass that starts 10 s later, on every run the same
    # what this run shares with others (an event run, the sweep run it takes over from): append-only, merged by key
    # and, where this relay may write the relay log, a line there for each lease and each answer: an event run on
    # another runner reads those, and this pass reads its lines in the comments it fetches anyway (`read`, below)
    store = log_store()
    shared = relayq.Notes(Path(os.environ.get("KNOS_RELAY_NOTES") or sp.with_name(f"{sp.stem}-notes")), me, lambda: at, store=store)
    queue = relayq.Queue(sp, lambda: at, limit=relayq.LIMIT, workers=hands, max_tries=None, strict=False, notes=shared)
    queue.release(me)               # leases of this run's own workers: a pass has ended, so a lease it left was a worker killed
    shared.prune()
    state = queue.notes()
    began = time.monotonic()
    since = _stamp(now - HORIZON)
    order = list(state.get("seen", []))                 # what was done already (each token as it was posted), oldest first
    seen = set(order)
    tries = dict(state.get("tries", {}))
    hold = {t: until for t, until in dict(state.get("hold", {})).items() if until > now}      # tokens not to be tried again before a time
    known = {r: t for r, t in dict(state.get("repos", {})).items() if now - t <= KNOWN_FOR}
    for named in shared.repos() - set(known):
        known[named] = now          # where an event run read: swept from now on
    day = _stamp(now)[:10]
    verified = dict(state.get("verify", {}).get("n", {})) if state.get("verify", {}).get("day") == day else {}
    if ledger is None:
        from .. import chain
        ledger, payer = chain.ledger(), chain.key()
    pool = relayq.payers(payer)     # one key, or several (KNOS_RELAY_KEYS): a lane pays from one of them, always the same
    plock = threading.RLock()       # the pass's notes (state, seen, tries, hold, verified, lines), which several workers change

    def keep() -> None:
        """The notes as they stand, beside the journal (which the queue writes). A token whose answer is not in yet
        is not in `seen`: whoever reads these notes next finds it in the journal, or in its comment."""
        queue.note(_stamp_notes)

    def _stamp_notes(disk: dict) -> None:
        with plock:
            state.update(seen=[t for t in dict.fromkeys(order) if t in seen][-2000:], tries=dict(list(tries.items())[-500:]), repos=dict(known),
                         hold=dict(list(hold.items())[-500:]), verify={"day": day, "n": dict(verified)}, run=run_id)
            mine = copy.deepcopy(state)
        for k in [k for k in disk if k not in mine]:
            del disk[k]
        disk.update(mine)

    run_id = os.environ.get("GITHUB_RUN_ID") or ""
    if state.get("unposted"):
        _post(state.pop("unposted"), state)
    raw = ledger._ledger if isinstance(ledger, Timed) else ledger
    ledger = ledger if isinstance(ledger, Timed) else Timed(ledger, lambda: time.time() + skew)
    from ..settle.v2 import relay as second
    # which knos_pay is live is asked anew by each pass, once: the fee a funding must hold, the markers a quorum counts
    # and who is a judge all follow that answer, and an upgrade that executed since the last pass is met by this one
    second.forget(ledger)
    lines, later = _held(state, now, since), []
    if lines:
        keep()                      # what was posted is out of the notes before anything else can stop this pass
    answered: set[str] = set()
    if state.get("run", run_id) != run_id:      # another run's notes: it may still be relaying (worker.yml overlaps two runs)
        try:
            answered = logged(since)
        except Exception:  # noqa: BLE001 - GitHub did not answer: a token the chain shows done is looked up one by one
            answered = set()
    listed: list = []
    repos: set[str] = set()

    def read(repo: str):
        try:
            if store is None or repo != HOME_REPO:
                return repo, found(repo, since)
            fetched: list = []          # the log repository's comments, fetched for their tokens: the other runners' notes are in them

            def getter(path: str):
                got = _api(path)
                fetched.extend(got if isinstance(got, list) else [])
                return got
            items = found(repo, since, getter)
            store.take(fetched)
            return repo, items
        except Exception:  # noqa: BLE001 - GitHub did not answer for this one: the next pass asks again
            return repo, []

    def read_all() -> list:
        with ThreadPoolExecutor(max_workers=8) as readers:
            return list(readers.map(read, sorted(repos)))
    if float(state.get("resting", 0)) > now:
        print(f"relay: the queue was full; comments are read again at {_stamp(float(state['resting']))} "
              f"(in {math.ceil(float(state['resting']) - now)} seconds). What is queued is carried meanwhile.", file=sys.stderr)
    else:
        state.pop("resting", None)
        newest = sorted(known, key=lambda r: (-known[r], r))
        rest = sorted(newest[EVERY_PASS:])
        turn = int(state.get("turn", 0)) % max(len(rest), 1)
        state["turn"] = turn + IN_TURN
        repos = {ROTATE_REPO, HOME_REPO} | {r.strip() for r in os.environ.get("KNOS_RELAY_REPOS", "").split(",") if "/" in r}
        repos |= set(newest[:EVERY_PASS]) | set((rest + rest)[turn:turn + IN_TURN])
        repos |= watched(ledger, state, now)                # found on chain, with no search: where a proof is awaited
        if now - state.get("searched", 0) >= SEARCH_EVERY:
            repos |= set(discover(since, state))
            state["searched"] = now
        listed = read_all()

    def issued(item) -> int:
        try:
            return int(claims(item[2]).get("iat", 0))
        except Exception:  # noqa: BLE001 - not a token: relay_one reports it
            return 0

    def queue_found(listed: list) -> int:
        """Queues every token of `listed` that is new here; returns how many. Called for the pass's first read, and
        again (`relayq.work`'s feed) while a worker still carries: the pass's notes are changed under their lock, and
        the queue is never asked while that lock is held (a worker's answer takes the two the other way round)."""
        had, others, queued = queue.entries(), shared.merged(), 0
        # oldest first, whatever repository it is in: a balance takes its fund tokens in the order GitHub issued them
        for repo, item in sorted(((repo, item) for repo, items in listed for item in items), key=lambda found: issued(found[1])):
            kind, n, jwt, _who = item
            terms, created = getattr(item, "terms", None), getattr(item, "created", None)
            # a token is done once as it was posted: under this marker, with these terms. A copy posted another way is
            # another matter, so nobody's copy can use up, or speak for, the token of the comment that posts it rightly
            astray = kind == "withdraw" and not repo.endswith(CLAIM_REPO)       # a copy of a request, posted where none is read: it is not the request
            # (a passkey's funding line is its own on each issue it is pasted on: a copy elsewhere never uses up the line on the issue it funds)
            place = repo.encode() if astray else f"{repo}#{n}".encode() if kind == "passkey-fund" else b""
            tid = hashlib.sha256(f"{kind}\n{jwt}\n".encode() + (terms or b"") + place).hexdigest()[:16]
            with plock:
                known[repo] = now
                if tid in seen:
                    continue
                if tid in had and "item" in had[tid]:           # in the journal: queued here on an earlier pass, or by an event run
                    if had[tid].get("state") not in relayq.OPEN:
                        seen.add(tid)                           # and answered there: its line is whoever carried it's to write
                        order.append(tid)
                    continue
                theirs = others.get(tid)
                if theirs is not None and theirs["by"] != shared.runner and theirs["state"] in ("confirmed", "refused"):
                    seen.add(tid)                               # another run's notes have its answer: that run wrote its line
                    order.append(tid)
                    continue
                if answer(kind, jwt) in answered:   # the log has its verdict, under this marker: the run before this one carried it
                    seen.add(tid)
                    order.append(tid)
                    continue
                wrong = ("a withdrawal request is read only on an issue of a repository named knos-claim" if astray else None) if kind == "withdraw" \
                    else None if kind == "passkey-fund" else misposted(kind, jwt, terms)
                if wrong:                   # logged without the token's id: whoever waits for that token is not answered by this
                    seen.add(tid)
                    order.append(tid)
                    lines.append(f"knos-relay {kind} {repo}#{n} - fail this comment cannot carry its token ({token_id(jwt)[:8]}...): {wrong}")
                    later.append(lines[-1])
                    continue
            what = {"kind": kind, "repo": repo, "n": n, "jwt": jwt, "terms": terms.decode() if terms else None, "created": created}
            try:                        # journaled before the first transaction: a relay killed from here on finds the token again
                queued += int(queue.put(tid, _lane(kind, jwt, repo), what, id=token_id(jwt), kind=kind, where=f"{repo}#{n}"))
            except relayq.Full as full:
                # backpressure: nothing more is read until the queue has had time to empty. The tokens stay in their comments.
                with plock:
                    state["resting"] = now + full.retry_after
                print(f"relay: the queue is full ({queue.pending()} tokens wait and it holds {queue.limit}), because Solana or GitHub is answering slowly. "
                      f"No comment is read for {full.retry_after} seconds; reading starts again at {_stamp(state['resting'])}. "
                      "Nothing is lost: a token that was not taken is still in its comment.", file=sys.stderr)
                break
        return queued

    def feed() -> int:
        """While a worker still carries (a confirmation can take a minute): the same repositories are read again and
        what is new is queued, so a free worker carries it now and not after the slowest token of this pass."""
        if not repos or float(state.get("resting", 0)) > now:
            return 0
        return queue_found(read_all())
    queue_found(listed)
    keep()
    killed: list[BaseException] = []

    def carry_one(entry: dict) -> dict:
        """One entry to the chain, and what its answer means for the notes and the log: `relayq.work`'s handler."""
        item = entry["item"]
        kind, repo, n, jwt, tid = str(item["kind"]), str(item["repo"]), int(item["n"]), str(item["jwt"]), str(entry["key"])
        terms = str(item["terms"]).encode() if item.get("terms") else None
        created = item.get("created")
        timed = Timed(raw, lambda: time.time() + skew)      # this token's own first send and last confirmation
        picked = time.time() + skew
        origin = f"{kind}:{repo}" if kind in ("withdraw", "passkey-fund") else _origin(jwt, repo)
        with plock:
            rid = _repo_id(repo, state) if kind == "passkey-fund" else None
            had_today = verified.get(origin, 0)
        try:
            if kind == "withdraw" and had_today >= WITHDRAW_PER_DAY:
                r: dict[str, Any] = {"ok": False, "kind": "withdraw", "why": f"{WITHDRAW_PER_DAY} withdrawals a day are sent for one repository, and this one has had "
                                                             "them; post it again after midnight UTC, or send it yourself (anyone can pay its fee)"}
            elif kind == "passkey-fund" and had_today >= PASSKEY_FUND_PER_DAY:
                r = {"ok": False, "kind": kind, "why": f"{PASSKEY_FUND_PER_DAY} passkey fundings a day are sent for one repository, and this one has had "
                                                       "them; post the line again after midnight UTC while its slot lasts, or sign again then"}
            elif kind == "passkey-fund" and rid is None:
                r = {"ok": False, "kind": kind, "retry": True, "transient": True, "why": f"GitHub did not say which repository {repo} is"}
            elif kind == "passkey-fund" and rid is not None:
                with pool.hold(str(entry.get("lane") or tid)) as key:
                    r = dict(relay_one(timed, key, kind, jwt, where=(rid, n)))
            elif kind == "verify" and had_today >= VERIFY_PER_DAY:
                r = {"ok": False, "kind": "verify", "why": f"{VERIFY_PER_DAY} tokens a day are verified for one repository, and this one has had "
                                                           "them; post it again after midnight UTC, or relay it yourself (anyone can)"}
            else:
                more: dict[str, Any] = {"terms": terms} if terms else {}
                with pool.hold(str(entry.get("lane") or tid)) as key:      # this lane's fee payer, held while its token is carried
                    r = dict(relay_one(timed, key, kind, jwt, **more))
        except Exception as why:  # noqa: BLE001 - what a relay raises says nothing about the token: tried again as any failure that may clear
            r = {"ok": False, "kind": kind, "retry": True, "transient": True, "why": f"{type(why).__name__}: {why}"}
        except BaseException as gone:  # noqa: BLE001 - the process is being stopped: nothing is noted, the lease stays, the next pass sends again
            killed.append(gone)
            raise
        finished = time.time() + skew
        with plock:
            return settle(entry, r, kind, repo, n, jwt, tid, created, origin, picked, finished, timed)

    def settle(entry: dict, r: dict, kind: str, repo: str, n: int, jwt: str, tid: str, created, origin: str, picked: float, finished: float, timed) -> dict:
        """What the queue is told (`relayq.Queue.finish`), after the notes and the log have what this answer means."""
        q: dict[str, Any] = {"ok": bool(r.get("ok")) and not r.get("retry"), "order": r.get("order"), "job": r.get("job"), "why": r.get("why"),
                             "took": max(0, round(finished - (picked if created is None else created))), "took_s": max(0.0, finished - picked)}
        if r.get("retry"):          # the faucet's minute, or the cluster dropped it: a later pass tries again
            if r.get("transient"):  # only a failure counts toward giving up; waiting out the limit does not
                tries[tid] = tries.get(tid, 0) + 1
            dead = expires(jwt)
            # a failure that says nothing about the token never ends it while the chain would still take it; one whose
            # expiry cannot be read gets MAX_TRIES passes. So does one the program itself answered (a twin run's
            # interference clears in a pass or two; what does not clear is the program's refusal, and is not sent for an hour)
            if tries.get(tid, 0) < MAX_TRIES or (dead is not None and now < dead and not r.get("answered")):
                # the relay says how long to wait, when it knows; a failure that keeps coming is given more room each
                # time, so that passes a few seconds apart do not give a token up within the same minute of trouble
                wait = r.get("wait") or (backoff(tries[tid]) if r.get("transient") else 0)
                if wait > 0:
                    hold[tid] = now + wait
                return {**q, "retry": True, "wait": wait}
            q["gave_up"] = True
            r["why"] = (f"{r.get('why')} (gave up after {tries[tid]} passes; run the workflow again for a fresh token)" if dead is None or r.get("answered") else
                        f"{r.get('why')} (tried {tries[tid]} times until the token expired; run the workflow again for a fresh token)")
            q["why"] = r["why"]
        tries.pop(tid, None)
        hold.pop(tid, None)
        seen.add(tid)               # answered: never taken up again from its comment
        order.append(tid)
        # carried already, or refused: when two runs overlap, the loser of the race sees one or the other (a passkey
        # withdrawal has no `already`: once the winner sent it, the wallet's nonce has moved on and the loser is refused)
        if not r.get("ok") or r.get("already"):
            try:
                told = answer(kind, jwt) in logged(since)
            except Exception:  # noqa: BLE001 - GitHub did not answer: the line says what the chain shows
                told = False
            if told:
                return q            # another run of this relay carried it, and its line is in the log
        if r.get("ok") and not r.get("sigs") and not r.get("already"):
            return q                # nothing had to be done (a key the chain already has): no log line
        if kind in ("verify", "withdraw", "passkey-fund") and r.get("ok") and r.get("sigs"):
            verified[origin] = verified.get(origin, 0) + 1
        if kind == "passkey-fund":
            from ..settle.v2 import relay as second
            _reply(repo, n, second.passkey_fund_reply(r))
            if r.get("astray"):     # a line the passkey signed for another issue: this comment is not that funding, and its line answers nobody who waits for it
                lines.append(f"knos-relay {kind} {repo}#{n} - fail this comment cannot carry its line ({token_id(jwt)[:8]}...): {' '.join(str(r['why']).split())}")
                later.append(lines[-1])
                return q
        took = max(0, round(finished - created)) if r.get("ok") and created is not None else None
        parts = stages(jwt, created, picked, finished) if r.get("ok") else None
        if parts is not None and int(entry["tries"]) > 1:
            parts["tries"] = int(entry["tries"])    # carried on a later try: the log says how many it took
        line = log_line(kind, repo, n, jwt, r, took, parts, times(r, created, picked, finished, timed) if r.get("ok") else None)
        if r.get("ok") and r.get("already") and int(entry["tries"]) <= 1:
            # someone carried it before this relay sent anything. When that someone is another run of this relay (two
            # overlap at a handover) its own line is on its way: this one waits for it, and is posted only if none comes.
            # (A token this relay had already tried is its own doing, cut short: a relay killed after its send. Nobody
            # else will log that one, so its line is written at once.)
            state["held"] = [*state.get("held", []), {"line": line, "answer": answer(kind, jwt), "until": now + ALREADY_WAIT}][-200:]
            return q
        lines.append(line)
        if r["ok"]:
            _post([line], state)    # at once: someone is waiting for it
        else:
            later.append(line)
        state.setdefault("owners", [])
        if r["ok"] and repo.split("/")[0] not in state["owners"]:
            state["owners"].append(repo.split("/")[0])
        return q

    relayq.work(queue, carry_one, hands, drain=False, owner=me, stop=lambda: bool(killed), note=_stamp_notes, feed=feed,
                feed_every=float(os.environ.get("KNOS_RELAY_REREAD") or relayq.FEED_EVERY))
    if killed:
        raise killed[0]             # the pass ends as the process would have: what it held is leased in the notes, and sent again next time
    if crank:
        try:
            more = _cranks(ledger, payer, pool.keys[1:]) if len(pool) > 1 else _cranks(ledger, payer)
        except Exception as why:  # noqa: BLE001 - the chain's clock could not be read; the next pass tries again
            more = []
            print(f"settle/refund: {why}", file=sys.stderr)
        lines += more
        later += more
    if later:
        _post(later, state)
    try:
        _claims(state, now, raw)    # unfunded claims of payment in the repositories this relay may write to, each at most once in 5 minutes
    except Exception as why:  # noqa: BLE001 - the guard never stops a pass: the tokens were carried
        print(f"::error title=claim guard::{type(why).__name__}: {why}", file=sys.stderr)
    state["round"] = {"at": now, "took": round(time.monotonic() - began, 1), "tokens": sum(1 for ln in lines if " ok sig=" in ln and " - - " not in ln)}
    keep()
    for ln in lines:
        print(ln)
    return lines


def _lane(kind: str, jwt: str, repo: str) -> str:
    """The lane a token leaves in when the sweep carries several at once: its owner's (`knos.settle.v2.relay.lane`),
    so two transactions that may write one account never run together and leave in the order GitHub issued them.
    A token that names no owner cannot be shown to share nothing with another: all of those leave one at a time, as
    every token did before. A verify-only token, a withdrawal request and a passkey's funding line leave in a lane of
    their repository, so the day's limit for it is counted one at a time."""
    if kind in ("verify", "withdraw", "passkey-fund"):
        return f"{kind}:{repo if kind != 'verify' else _origin(jwt, repo)}"
    from ..settle.v2 import relay as second
    lane = str(second.lane(jwt))
    return "unowned" if lane.startswith("alone:") else lane


def serve(seconds: float, every: float = 3.0, ledger=None, payer=None, clock=time.monotonic, sleep=time.sleep) -> int:
    """Passes for `seconds`, each starting `every` seconds after the one before (at once, when that one took longer):
    what worker.yml runs. The repositories' ETags are kept from pass to pass, so a pass that finds nothing new costs
    a 304 for each repository it knows. What needs no token is sent once a minute. Returns the number of lines logged."""
    if ledger is None:
        from .. import chain
        ledger, payer = chain.ledger(), chain.key()
    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        print("relay: no GH_TOKEN, so GitHub allows 60 requests an hour: most passes will read nothing. Set GH_TOKEN (any token; public reads).", file=sys.stderr)
    end, cranked, logged = clock() + seconds, None, 0
    while clock() < end:
        began = clock()
        crank = cranked is None or began - cranked >= CRANK_EVERY
        try:
            logged += len(once(ledger, payer, crank=crank))
        except Exception as why:  # noqa: BLE001 - one bad pass never stops the worker
            print(f"relay pass: {type(why).__name__}: {why}", file=sys.stderr)
        if crank:
            publish_status()
        cranked = began if crank else cranked
        sleep(max(0.0, min(every - (clock() - began), end - clock())))
    return logged


if __name__ == "__main__":
    once()
