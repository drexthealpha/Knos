"""What `knos mcp` serves beside its tools (MCP 2026-07-28, read 14 Oct 2026 at modelcontextprotocol.io/specification):

    resources            data an agent (or the person) reads without calling a tool, each a JSON document:
        knos://fees                         every Knos fee and its status (config/fees.yaml): what a payer pays
        knos://cheats                       the cheat rules Knos Gate and the referee refuse: read them BEFORE writing the work
    resource templates
        knos://bounty/{owner}/{repo}/{issue}   what is held on one issue, its state and terms (what knos_bounty returns)
        knos://due/{login}                     what waits and what was paid for a GitHub account (knos_due)
        knos://token/{address}                 whether a mint can hold money until the proof passes, or a token account receive a payout
                                               (Token-2022 extensions: knos.platform.token22)
    prompts              the three jobs a person asks an agent to do with Knos, as ready messages:
        earn_a_bounty     find funded work, reserve it, verify before the pull request, open it, collect
        fund_a_bounty     put money on an issue, with the fee and the terms said first
        before_pull_request   run knos_verify and paste the receipt lines
    confirmation         (elicitation through a multi-round-trip request) before a tool posts to GitHub as the person's
                         account, a client that declared `elicitation` is asked to show the exact request and get a yes:
                         the tool answers `resultType: "input_required"` with an `elicitation/create` form; the retry
                         carries the answer and a `requestState` this server signed, so only the bytes the person saw
                         are ever posted. KNOS_AGENT_CONFIRM=0 turns it off (an unattended agent on an `auto` order).

Nothing here signs, pays or posts: resources and prompts read public data, the confirmation only stops a post."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time

CAPS_KEY = "io.modelcontextprotocol/clientCapabilities"
LIST_TTL_MS = 300_000
READ_TTL_MS = 30_000            # vault state changes; a client may keep a read this long
CONFIRM_TTL_S = 600
_SECRET = os.urandom(32)        # signs requestState; a restart only means the person is asked again

RESOURCES = [
    {"uri": "knos://fees", "name": "fees", "title": "Knos fees",
     "description": "Every Knos fee, from config/fees.yaml, with each line's status (live, decided, placeholder). On devnet all money is test money.",
     "mimeType": "application/json"},
    {"uri": "knos://cheats", "name": "cheats", "title": "Cheat rules",
     "description": "The rules Knos refuses work by (editing tests, skipping them, touching workflows, out-of-scope files, ...): read before writing the change.",
     "mimeType": "application/json"},
]
TEMPLATES = [
    {"uriTemplate": "knos://bounty/{owner}/{repo}/{issue}", "name": "bounty", "title": "Held money on one issue",
     "description": "What is held for owner/repo#issue: each job's state and its terms in words.", "mimeType": "application/json"},
    {"uriTemplate": "knos://due/{login}", "name": "due", "title": "Waiting for a GitHub account",
     "description": "Where a GitHub account is paid, what is held for it and its record.", "mimeType": "application/json"},
    {"uriTemplate": "knos://token/{address}", "name": "token", "title": "Token safety",
     "description": "Whether a mint can hold money until the proof passes (no permanent delegate, pause, transfer hook, fee, frozen default) or a token account can receive a payout (no required memo, not frozen).",
     "mimeType": "application/json"},
]
_PARTS = {"bounty": re.compile(r"knos://bounty/([A-Za-z0-9][A-Za-z0-9-]{0,38})/([\w.-]{1,100})/(\d{1,10})"),
          "due": re.compile(r"knos://due/([A-Za-z0-9][A-Za-z0-9-]{0,38}(?:\[bot\])?)"),
          "token": re.compile(r"knos://token/([1-9A-HJ-NP-Za-km-z]{32,44})")}

PROMPTS = [
    {"name": "earn_a_bounty", "title": "Earn a bounty",
     "description": "Find funded work, reserve it, do it, verify it, open the pull request and collect the payment.",
     "arguments": [{"name": "repo", "description": "only this repository (owner/name); empty: any", "required": False}]},
    {"name": "fund_a_bounty", "title": "Fund a bounty",
     "description": "Put money on a GitHub issue, saying the fee and the terms before anything is posted.",
     "arguments": [{"name": "issue", "description": "owner/repo#number", "required": True},
                   {"name": "amount", "description": "in test USDC, like 20 or 12.5", "required": True}]},
    {"name": "before_pull_request", "title": "Verify before the pull request",
     "description": "Run Knos on the committed change and paste the receipt lines into the description.", "arguments": []},
]


def capabilities() -> dict:
    return {"tools": {}, "resources": {}, "prompts": {}}


class NotFound(Exception):
    pass


def read(uri: str, server) -> dict:
    """resources/read: {contents: [{uri, mimeType, text}]}. `server` is the knos.mcp.Server (its tools answer)."""
    if not isinstance(uri, str):
        raise NotFound("resources/read needs a uri")
    if uri == "knos://fees":
        from .money import fees_config
        body = fees_config.load().public()
    elif uri == "knos://cheats":
        body = cheats()
    elif (m := _PARTS["bounty"].fullmatch(uri)):
        body = server._bounty({"issue": f"{m.group(1)}/{m.group(2)}#{m.group(3)}"})
    elif (m := _PARTS["due"].fullmatch(uri)):
        body = server._due({"login": m.group(1)})
    elif (m := _PARTS["token"].fullmatch(uri)):
        body = token(m.group(1), server)
    else:
        raise NotFound(f"no resource {uri[:120]}")
    return {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(body, indent=1, default=str)}]}


def cheats() -> dict:
    try:
        from . import cheats as lib
        rows = [{"id": r.id, "category": r.category, "title": r.title, "severity": r.severity, "kind": r.kind} for r in lib.rules()]
        source = "knos.cheats (docs/reference/REFEREE.md)"
    except ImportError:
        rows, source = [], "knos.cheats is not installed"
    from .gate.cheatlib import RULES
    gate = [{"id": k, "category": c, "title": t, "severity": "refuse", "kind": "gate"} for k, (c, t) in RULES.items()]
    return {"rules": rows + gate, "source": source, "said": "A change that matches a rule with severity refuse is not paid, whatever its tests say."}


def token(address: str, server) -> dict:
    from solders.pubkey import Pubkey
    from .platform import token22
    got = server._chain(lambda ledger: ledger.infos([Pubkey.from_string(address)]))[0]
    if got is None:
        return {"address": address, "kind": "missing", "ok": False, "risks": [], "said": "no such account on this cluster"}
    return {"address": address, **token22.check(str(got[0]), bytes(got[1]))}


def prompt(name: str | None, args: dict) -> dict:
    args = {k: str(v) for k, v in (args or {}).items() if isinstance(v, (str, int))}
    if name == "earn_a_bounty":
        where = f" in {args['repo']}" if args.get("repo") else ""
        text = (f"Find funded work{where} with knos_find_work{' (repo: ' + args['repo'] + ')' if args.get('repo') else ''}, and pick one whose "
                "terms you can meet. Read knos://cheats first: a change that edits tests, skips them, touches workflows or files outside the "
                "terms is refused and not paid. Reserve it with knos_take_work. Do the work in a branch, commit it, run knos_verify and fix "
                "what it refuses. Then knos_submit_work opens the pull request only when the order's acceptance passes locally. After the "
                "merge, knos_collect says what is held or paid for your account. Say plainly what you did; never say tests pass unless they did.")
        return _msg("Earn a bounty with Knos", text)
    if name == "fund_a_bounty":
        if not args.get("issue") or not args.get("amount"):
            raise NotFound("fund_a_bounty needs issue and amount")
        text = (f"Put a bounty of {args['amount']} test USDC on {args['issue']}. First read knos://fees and say the fee, then call knos_fund "
                f"with issue {args['issue']} and amount {args['amount']} and show me the exact comment and the terms it locks in. Post nothing "
                "until I say yes.")
        return _msg("Fund a bounty with Knos", text)
    if name == "before_pull_request":
        return _msg("Verify before the pull request", "Run knos_verify on the committed change in this repository. If it refuses, fix "
                    "what it names and run it again. When it passes, paste its pr_markdown lines into the pull request description.")
    raise NotFound(f"no prompt {str(name)[:80]}")


def _msg(description: str, text: str) -> dict:
    return {"description": description, "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}


# -- confirmation before a post (elicitation through a multi-round-trip request) ------------------------------------
class NeedInput(Exception):
    """Raised where a tool would post: the person has not yet approved these exact bytes."""

    def __init__(self, tool: str, posted: dict, state: dict):
        super().__init__(tool)
        self.tool, self.posted, self.state = tool, posted, state


def asks(params: dict) -> bool:
    """Whether this call should be confirmed: the client said it can elicit (form mode), and the operator did not turn
    confirmation off."""
    if os.environ.get("KNOS_AGENT_CONFIRM", "").strip() == "0":
        return False
    meta = params.get("_meta")
    meta = meta if isinstance(meta, dict) else {}
    caps = meta.get(CAPS_KEY)
    caps = caps if isinstance(caps, dict) else {}
    el = caps.get("elicitation")
    return isinstance(el, dict) and (not el or "form" in el)


def digest(tool: str, args: dict, posted: dict, exp: int) -> str:
    body = json.dumps([tool, args, posted, exp], sort_keys=True, separators=(",", ":"), default=str).encode()
    return hmac.new(_SECRET, body, hashlib.sha256).hexdigest()


def approved(tool: str, params: dict) -> tuple[set[str], str | None, int | None]:
    """(the digests the person approved, a sentence when they declined, the state's expiry) from a retry's
    requestState and inputResponses. A state this server did not seal, for another tool, or expired, approves nothing."""
    raw = params.get("requestState")
    if not isinstance(raw, str) or len(raw) > 8192:
        return set(), None, None
    try:
        st = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except (ValueError, TypeError):
        return set(), None, None
    if not isinstance(st, dict) or st.get("tool") != tool or not isinstance(st.get("exp"), int) or st["exp"] < time.time() \
            or not isinstance(st.get("seals"), dict):
        return set(), None, None
    exp, seals = st["exp"], st["seals"]

    def sealed(d, role: str) -> bool:      # the seal names the role: a pending post moved to "approved" is not approved
        return isinstance(d, str) and hmac.compare_digest(str(seals.get(d, "")), _seal(d, exp, role))
    good = {d for d in st.get("approved", []) if sealed(d, "approved")}
    pending = st.get("pending")
    responses = params.get("inputResponses")
    responses = responses if isinstance(responses, dict) else {}
    answer = responses.get("confirm")
    answer = answer if isinstance(answer, dict) else {}
    action = answer.get("action")
    if sealed(pending, "pending") and action is not None:
        if action == "accept" and isinstance(answer.get("content"), dict) and answer["content"].get("post") is True:
            good.add(pending)
        else:
            return good, f"{tool}: nothing was sent; the person did not approve it ({action}).", exp
    return good, None, exp


def _seal(d: str, exp: int, role: str) -> str:
    return hmac.new(_SECRET, f"{role}:{d}:{exp}".encode(), hashlib.sha256).hexdigest()


def input_required(need: NeedInput, args: dict, have: set[str]) -> dict:
    exp = need.state["exp"]
    pend = digest(need.tool, args, need.posted, exp)
    st = {"tool": need.tool, "exp": exp, "pending": pend, "approved": sorted(have),
          "seals": {**{d: _seal(d, exp, "approved") for d in have}, pend: _seal(pend, exp, "pending")}}
    shown = json.dumps(need.posted.get("body"), indent=1)[:1500]
    msg = (f"{need.tool} will send this to GitHub as your account:\n{need.posted['method']} /{need.posted['path']}\n{shown}\n\n"
           "Post it?")
    return {"resultType": "input_required",
            "inputRequests": {"confirm": {"method": "elicitation/create", "params": {
                "mode": "form", "message": msg,
                "requestedSchema": {"type": "object", "properties": {
                    "post": {"type": "boolean", "title": "Post it", "description": "Yes: send exactly this. No: send nothing."}},
                    "required": ["post"]}}}},
            "requestState": base64.urlsafe_b64encode(json.dumps(st, separators=(",", ":")).encode()).decode()}


def new_exp() -> int:
    """When a confirmation that starts now stops counting: a retry after that asks again."""
    return int(time.time()) + CONFIRM_TTL_S
