"""The zero-secret GitHub relay: the always-on worker (worker.yml) carries proof and fund tokens that repos' own
workflows minted, to the escrow, and pays the gas.

Transport (caller -> worker). A repo that installed Knos (examples/knos-workflow.yml) has NO Knos secret, so it cannot
call the Knos repo or its API with auth. Its workflow posts the GitHub Actions OIDC token it minted as a comment with
its own GITHUB_TOKEN:

    knos-fund: <jwt>      on the issue, after a maintainer's `/knos bounty <amount> [stake]`
    knos-proof: <jwt>     on the pull request, after prove.yml's checks passed

Posting the token in public is acceptable ONLY because it is not a general bearer credential here: its audience binds
it to one action (knos:fund:<issue>:<units>:<checks>:<stake> or knos:<job>:<head sha>:<checks>:<payout>), it expires
in about 5 minutes, it is valid only from Knos's workflow at the pinned commit (job_workflow_sha), and the escrow
consumes it once. Whoever relays it first only pays the gas; the money goes where the audience says.

Discovery (worker finds the comments). Public reads, no install: GitHub issue search for the markers, plus the repos
in KNOS_RELAY_REPOS, plus every recently pushed repo of an owner the relay has served before (kept in KNOS_HOME).
For each repo it reads issue comments since the last scan (REST, public).

Result (worker -> caller). The worker cannot write to other repos. It appends one line per relayed token to the open
issue labelled `knos-relay` in the Knos repo (its own GITHUB_TOKEN can do that):

    knos-relay <kind> <owner/repo>#<n> <token id> ok job=<hex> sig=<s1>[,<s2>] [receipt=<url>]
    knos-relay <kind> <owner/repo>#<n> <token id> fail <reason>

The caller's last job polls that issue (public) for its token id and comments the verdict with its own token.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

TOKEN = re.compile(r"knos-(proof|fund):\s*(eyJ[\w-]+\.[\w-]+\.[\w-]+)")
LOG_LABEL = "knos-relay"
HOME_REPO = "drexthealpha/Knos"


def claims(jwt: str) -> dict:
    body = jwt.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def token_id(jwt: str) -> str:
    """What the relay log names a token by (never the token itself)."""
    return hashlib.sha256(jwt.strip().encode()).hexdigest()[:16]


def parse_aud(aud: str) -> dict:
    """knos:fund:<issue>:<units>:<checks>:<0|1> or knos:<job hex>:<head sha>:<checks>:<payout>."""
    p = aud.split(":")
    if len(p) == 6 and p[0] == "knos" and p[1] == "fund":
        return {"kind": "fund", "issue": int(p[2]), "units": int(p[3]), "checks": p[4], "stake": p[5] == "1"}
    if len(p) == 5 and p[0] == "knos" and re.fullmatch(r"[0-9a-f]{64}", p[1]):
        return {"kind": "proof", "job": p[1], "sha": p[2], "checks": p[3], "payout": p[4]}
    raise ValueError(f"not a Knos audience: {aud!r}")


def checks_hash(root: Path) -> str:
    """sha256 over the acceptance directory: for each file, sorted by its posix path relative to `root`,
    "<path>\\0<sha256 hex of the bytes>\\n". fund.yml computes the same with the identical inline Python."""
    h = hashlib.sha256()
    for f in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.relative_to(root).as_posix()):
        h.update(f"{f.relative_to(root).as_posix()}\0{hashlib.sha256(f.read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()


# ---- GitHub (gh CLI; GH_TOKEN is the worker's own GITHUB_TOKEN, used only for rate limits and its own log) --------

def gh(*args: str, inp: str | None = None) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=inp, timeout=60, check=False)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    return r.stdout


def _api(path: str) -> list | dict:
    return json.loads(gh("api", "-X", "GET", path) or "null")


def discover(since: str, state: dict, getter=_api) -> set[str]:
    repos = {r.strip() for r in os.environ.get("KNOS_RELAY_REPOS", "").split(",") if "/" in r}
    for marker in ("knos-fund", "knos-proof"):
        try:
            res = getter(f"search/issues?q=%22{marker}%22+in:comments+updated:%3E={since[:10]}&per_page=50")
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
    repos.discard(HOME_REPO)
    return repos


def found(repo: str, since: str, getter=_api) -> list[tuple[str, int, str, str]]:
    """(kind, issue/PR number, jwt, comment author) for every marker comment in `repo` since `since`."""
    out = []
    for c in getter(f"repos/{repo}/issues/comments?since={since}&per_page=100&sort=created&direction=desc"):
        for kind, jwt in TOKEN.findall(c.get("body") or ""):
            out.append((kind, int(c["issue_url"].rsplit("/", 1)[1]), jwt, c["user"]["login"]))
    return out


# ---- the relay -----------------------------------------------------------------------------------------------------

def relay_one(ledger, payer, kind: str, jwt: str, market=None, receipt=None) -> dict:
    """Send one token to the escrow. Returns {"ok", "job", "sigs", "receipt"?, "why"?}."""
    if market is None:
        from ..jobs import market
    c = claims(jwt)
    a = parse_aud(c["aud"] if isinstance(c["aud"], str) else c["aud"][0])
    if a["kind"] != kind:
        return {"ok": False, "why": f"marker {kind} but audience {a['kind']}"}
    if c.get("exp", 0) < time.time():
        return {"ok": False, "why": "token expired"}
    try:
        if kind == "fund":
            job_id, sig = market.fund_with_token(ledger, payer, jwt)
            return {"ok": True, "job": job_id.hex(), "sigs": [sig]}
        job_id = bytes.fromhex(a["job"])
        s1, s2 = market.prove_github(ledger, payer, job_id, jwt)
        out = {"ok": True, "job": a["job"], "sigs": [s1, s2]}
        if receipt is not None:
            try:
                out["receipt"] = receipt(job_id, a, c)
            except Exception:  # noqa: BLE001, S110 - the payment happened; the receipt is a convenience
                pass
        return out
    except Exception as why:  # noqa: BLE001 - one bad token never stops the loop
        return {"ok": False, "why": f"{type(why).__name__}: {str(why)[:160]}"}


def log_line(kind: str, repo: str, n: int, jwt: str, r: dict) -> str:
    head = f"knos-relay {kind} {repo}#{n} {token_id(jwt)}"
    if not r["ok"]:
        return f"{head} fail {r['why']}"
    line = f"{head} ok job={r['job']} sig={','.join(r['sigs'])}"
    return line + (f" receipt={r['receipt']}" if r.get("receipt") else "")


def _log_issue() -> int:
    res = _api(f"repos/{HOME_REPO}/issues?labels={LOG_LABEL}&state=open&per_page=1")
    if res:
        return res[0]["number"]
    try:
        gh("label", "create", LOG_LABEL, "--repo", HOME_REPO, "--force")
    except RuntimeError:
        pass
    url = gh("issue", "create", "--repo", HOME_REPO, "--title", "Knos relay log", "--label", LOG_LABEL,
             "--body", "One line per token the always-on worker relayed (see src/knos/proof/ghrelay.py).")
    return int(url.strip().rsplit("/", 1)[1])


def post_log(lines: list[str]) -> None:
    if lines:
        gh("issue", "comment", str(_log_issue()), "--repo", HOME_REPO, "--body-file", "-", inp="\n".join(lines))


def _state_path() -> Path:
    from .. import paths
    return paths.home() / "ghrelay.json"


def receipt_root(aud: str) -> bytes:
    """The receipt's evidence root for a paid proof: sha256 of its audience (job, head, checks hash, payout)."""
    return hashlib.sha256(aud.encode()).digest()


def _receipt_for(payer, repo: str, n: int):
    """A paid proof gets a SAS receipt on devnet, attested by the relaying key: root = sha256(audience), commit = the
    PR head, claim = what was paid. Returns the receipt page URL."""
    def publish(job_id: bytes, a: dict, c: dict) -> str:
        from ..team import rpc
        from . import receipt as rc
        aud = c["aud"] if isinstance(c["aud"], str) else c["aud"][0]
        claim = f"{repo}#{n} passed .knos/acceptance and was paid: job {a['job']} to {a['payout']}"
        _sig, att = rc.publish(rpc.CLUSTERS["devnet"], payer, receipt_root(aud), a["sha"], claim)
        return rc.page_url(att)
    return publish


def once(ledger=None, payer=None, now: float | None = None) -> list[str]:
    sp = _state_path()
    try:
        state = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    now = now or time.time()
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 15 * 60))   # tokens live ~5 min
    seen = set(state.get("seen", []))
    if ledger is None:
        from ..jobs import net
        ledger, payer = net.ledger(), net.key()
    lines = []
    for repo in sorted(discover(since, state)):
        try:
            items = found(repo, since)
        except Exception:  # noqa: BLE001, S112
            continue
        for kind, n, jwt, _who in items:
            tid = token_id(jwt)
            if tid in seen:
                continue
            seen.add(tid)
            r = relay_one(ledger, payer, kind, jwt, receipt=_receipt_for(payer, repo, n))
            lines.append(log_line(kind, repo, n, jwt, r))
            state.setdefault("owners", [])
            if r["ok"] and repo.split("/")[0] not in state["owners"]:
                state["owners"].append(repo.split("/")[0])
    state["seen"] = sorted(seen)[-2000:]
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(state), encoding="utf-8")
    try:
        post_log(lines)
    except RuntimeError as why:
        print(f"relay log: {why}", file=sys.stderr)
    for ln in lines:
        print(ln)
    return lines


if __name__ == "__main__":
    once()
