"""The protected enterprise spending boundary: an organisation's money in a Squads v4 vault, approvals bound to one
commitment, and a budget reserved before work starts.

    knos boundary plan  .knos/procurement/policy.yaml [--boundary FILE] [--json]
    knos boundary bind  --repo-id N --issue N --funder ADDRESS --terms FILE --amount 1200 --payee octocat --expires 2026-11-01
                        [--seq N] [--policy FILE]
    knos boundary reserve  --db FILE --budget NAME --request ID --amount 1200 [--total 50000]
    knos boundary release  --db FILE --request ID   |   knos boundary spend --db FILE --request ID
    knos boundary status   --db FILE --budget NAME

What holds, and by what (docs/BOUNDARY.md says it for a reader; knos.enforce cell by cell):

- The money is in a Squads v4 vault (program SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf, deployed and audited; Knos
  changes nothing in it). `plan` turns the buyer's approval policy (.knos/procurement/policy.yaml) and a boundary
  file (.knos/procurement/boundary.yaml: the key each account signs with, the config authority, the time lock, the
  vault's Balance and any allowance) into the multisig's settings: requesters may only propose (Initiate), approvers
  and finance vote (Vote), the threshold is the most votes any amount of the policy needs, a time lock, and a config
  authority that is nobody's member key. Squads refuses a vault transaction short of the threshold, a vote by a key
  without Vote, an execution before the time lock, and any change of members, threshold, time lock or spending limit
  not signed by the config authority (a controlled multisig takes no config transaction from its members).
- The limits a requester meets are a knos_pay Balance the VAULT opened: its cap per order, daily and total limits,
  spenders and workflow pin are knos_pay's checks (FundOrderBalance), and only the vault, by vote, changes them.
- A Squads spending limit is an allowance: its members move up to its amount per period to its destinations WITHOUT a
  vote. `plan` writes one only where the boundary file asks for it, and says that it loosens the threshold.
- `bind`: an approval names `order:<digest>`, the sha256 of one commitment (repository, issue, sequence, funder,
  terms hash, policy hash, amount, beneficiary, expiry). `gate_bound` refuses an approval reused for another order,
  after its expiry, under a changed policy or for another payee, each in its own sentence.
- `Reservations`: a budget is held when a request is approved, before work starts, in one SQLite transaction that
  takes the write lock first; two writers cannot both take the last of it. On chain the same holds by itself: a
  funding moves the money into the order, and the token program refuses what the vault does not hold.

What stays advisory: per-holder limits and dates, the self-approval limit (a requester's key cannot vote at all,
which is stricter), finance as a separate count (Squads counts votes, not roles), rate cards and envelope files.
A person's own wallet is outside: it is their money, and no policy of an organisation can bind it.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from . import approvals, controls
from .controls import day_of, money, units_of

SQUADS = "SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf"
INITIATE, VOTE, EXECUTE = 1, 2, 4                       # Squads v4 Permission bits (state/multisig.rs)
MAX_TIME_LOCK = 3 * 30 * 24 * 60 * 60                   # Squads v4 MAX_TIME_LOCK: 7,776,000 seconds
PERIODS = ("once", "day", "week", "month")              # Squads v4 Period: OneTime, Day, Week, Month (30 days)
BOUNDARY_FIELDS = ("version", "kind", "keys", "config_authority", "executors", "time_lock_hours", "vault_index", "balance", "allowances")
BALANCE_FIELDS = ("owner_id", "cap_per_order", "per_day", "total", "spenders", "repos", "workflows_commit")
ALLOWANCE_FIELDS = ("name", "destination", "mint", "amount", "period", "members")
BOUNDARY_FILE = "boundary.yaml"
_B58 = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
COMMITMENT = "knos.boundary.commitment.v1"


class Refused(ValueError):
    """The plan cannot be made; the message is one sentence."""


def _key(v) -> bool:
    if not isinstance(v, str) or not _B58.fullmatch(v):
        return False
    try:
        from solders.pubkey import Pubkey
        Pubkey.from_string(v)
    except (ImportError, ValueError):
        return False
    return True


def boundary_problems(doc) -> list[str]:
    """What is wrong with a boundary file, in sentences ([]: nothing)."""
    out = controls._head(doc, "spending-boundary", "a boundary file", BOUNDARY_FIELDS)
    if not isinstance(doc, dict):
        return out
    rows = doc.get("keys")
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) and set(r) == {"account", "key"} for r in rows):
        out.append("`keys` lists, for each account of the policy, `account` and the Solana `key` it signs the vault's proposals with.")
    else:
        seen: dict[str, str] = {}
        for r in rows:
            a, k = str(r["account"]), r["key"]
            if not controls._is(controls._LOGIN, a):
                out.append(f"`keys`: `{a}` is not a forge account.")
            elif not _key(k):
                out.append(f"`keys`: @{a} is not given a Solana address.")
            elif k in seen:
                out.append(f"`keys`: @{seen[k]} and @{a} share one key, and Squads would count it once.")
            seen.setdefault(str(k), a)
    if not _key(doc.get("config_authority")):
        out.append("`config_authority` is the Solana address that alone may change the vault's members, threshold, time lock and limits.")
    if not isinstance(doc.get("executors", []), list) or not all(_key(k) for k in doc.get("executors", [])):
        out.append("`executors` is a list of Solana addresses.")
    hours = doc.get("time_lock_hours", 0)
    if isinstance(hours, bool) or not isinstance(hours, int) or not 0 <= hours * 3600 <= MAX_TIME_LOCK:
        out.append(f"`time_lock_hours` is a whole number from 0 to {MAX_TIME_LOCK // 3600} (Squads allows three months at most).")
    vi = doc.get("vault_index", 0)
    if isinstance(vi, bool) or not isinstance(vi, int) or not 0 <= vi <= 255:
        out.append("`vault_index` is 0 to 255.")
    bal = doc.get("balance")
    if bal is not None:
        if not isinstance(bal, dict):
            out.append("`balance` is a block of `key: value` lines.")
        else:
            out += [f"`balance.{k}` is not a field." for k in bal if k not in BALANCE_FIELDS]
            if isinstance(bal.get("owner_id"), bool) or not isinstance(bal.get("owner_id"), int) or bal.get("owner_id", 0) <= 0:
                out.append("`balance.owner_id` is the GitHub id of the account that owns the repositories.")
            for k in ("cap_per_order", "per_day", "total"):
                if k in bal and units_of(bal[k]) is None:
                    out.append(f"`balance.{k}` is an amount, like 10000 or 2500.50.")
            sp = bal.get("spenders", [])
            if not isinstance(sp, list) or len(sp) > 4 or not all(isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in sp):
                out.append("`balance.spenders` is at most 4 GitHub ids: knos_pay keeps four.")
            rp = bal.get("repos", [])
            if not isinstance(rp, list) or len(rp) > 8 or not all(isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in rp):
                out.append("`balance.repos` is at most 8 repository ids.")
            if "workflows_commit" in bal and not controls._is(_HEX40, bal["workflows_commit"]):
                out.append("`balance.workflows_commit` is the commit of the pinned workflows: 40 lowercase hex characters.")
    for n, a in enumerate(doc.get("allowances") or [], 1):
        if not isinstance(a, dict):
            out.append(f"Allowance {n} is a block of `key: value` lines.")
            continue
        out += [f"Allowance {n}: `{k}` is not a field." for k in a if k not in ALLOWANCE_FIELDS]
        if not _key(a.get("destination")) or not _key(a.get("mint")):
            out.append(f"Allowance {n}: `destination` and `mint` are Solana addresses.")
        if units_of(a.get("amount")) in (None, 0):
            out.append(f"Allowance {n}: `amount` is an amount above 0.")
        if a.get("period") not in PERIODS:
            out.append(f"Allowance {n}: `period` is once, day, week or month.")
        if not isinstance(a.get("members"), list) or not a["members"] or not all(isinstance(m, str) for m in a["members"]):
            out.append(f"Allowance {n}: `members` lists the accounts that may use it.")
    return out


def _threshold(policy: dict) -> int:
    return max(int(t.get("approvers", 0)) + int(t.get("finance", 0)) for t in policy["thresholds"])


def plan(policy: dict, boundary: dict) -> dict:
    """The vault's settings for an approval policy and a boundary file, or Refused (one sentence). Keys of the
    result: squads {program, create {config_authority, threshold, time_lock, members, rent_collector}, vault_index,
    spending_limits}, balance (knos_pay OpenBalance/SetBalance/SetBalanceX, signed by the vault), hard, advisory."""
    bad = approvals.policy_problems(policy)
    if bad:
        raise Refused(f"The approval policy is not sound. {bad[0]}")
    bad = boundary_problems(boundary)
    if bad:
        raise Refused(f"The boundary file is not sound. {bad[0]}")
    keys = {str(r["account"]).lower(): str(r["key"]) for r in boundary["keys"]}
    roles: dict[str, set[str]] = {}
    for role in approvals.ROLES:
        for h in approvals.holders(policy, role):
            roles.setdefault(str(h["account"]).lower(), set()).add(role)
    masks: dict[str, int] = {}
    for account, held in sorted(roles.items()):
        if held == {"auditor"}:
            continue                                     # an auditor reads; the vault does not need the key
        if account not in keys:
            raise Refused(f"@{account} holds a role and `keys` gives no Solana key for it.")
        if "requester" in held and held & set(approvals.SIGNING):
            raise Refused(f"@{account} both requests and approves: Squads lets the creator of a proposal vote on it, so give a requester no Vote.")
        masks[keys[account]] = (INITIATE if "requester" in held else 0) | (VOTE if held & set(approvals.SIGNING) else 0)
    executors = [str(k) for k in boundary.get("executors") or []]
    for k in executors:
        masks[k] = masks.get(k, 0) | EXECUTE
    if not executors:
        for k, m in masks.items():
            if m & VOTE:
                masks[k] = m | EXECUTE
    authority = str(boundary["config_authority"])
    if authority in masks:
        raise Refused("The config authority is also a member's key. It must be a separate key (a board's own multisig vault is the usual one).")
    voters = sum(1 for m in masks.values() if m & VOTE)
    need = _threshold(policy)
    if need < 1:
        raise Refused("The policy asks for no approval at any amount, and a Squads threshold is at least 1.")
    if need > voters:
        raise Refused(f"The policy asks for {need} votes and only {voters} keys may vote.")
    members = [{"key": k, "accounts": sorted(a for a, kk in keys.items() if kk == k), "mask": m,
                "permissions": [p for p, bit in (("initiate", INITIATE), ("vote", VOTE), ("execute", EXECUTE)) if m & bit]}
               for k, m in sorted(masks.items())]
    limits = []
    for a in boundary.get("allowances") or []:
        who = []
        for m in a["members"]:
            if str(m).lower() not in keys:
                raise Refused(f"Allowance `{a.get('name', '')}` names @{m}, and `keys` gives no key for it.")
            who.append(keys[str(m).lower()])
        limits.append({"name": str(a.get("name", "")), "mint": a["mint"], "amount": units_of(a["amount"]), "period": a["period"],
                       "period_index": PERIODS.index(a["period"]), "members": who, "destinations": [a["destination"]],
                       "vault_index": int(boundary.get("vault_index", 0)),
                       "note": "Moves up to this amount per period to this destination WITHOUT a vote: an allowance loosens the threshold."})
    bal = boundary.get("balance")
    balance = None
    if bal is not None:
        balance = {"authority": "the vault", "owner_id": bal["owner_id"], "cap": units_of(bal.get("cap_per_order", 0)) or 0,
                   "spenders": list(bal.get("spenders") or []), "day_limit": units_of(bal.get("per_day", 0)) or 0,
                   "total_limit": units_of(bal.get("total", 0)) or 0, "repos": list(bal.get("repos") or []),
                   "workflows_commit": bal.get("workflows_commit", "")}
    lock = int(boundary.get("time_lock_hours", 0)) * 3600
    tiers = sorted({int(t.get("approvers", 0)) + int(t.get("finance", 0)) for t in policy["thresholds"]})
    hard = [f"Squads v4: a vault transaction executes only with {need} votes of {voters} voting keys"
            + (f", and not before {lock // 3600} hours after the last vote" if lock else "") + ".",
            "Squads v4: a requester's key proposes and cannot vote; only an Execute key executes.",
            "Squads v4: only the config authority changes members, threshold, time lock or spending limits; members cannot.",
            "Token program: a funding moves the money from the vault into the order before work starts, and the vault cannot spend what it does not hold."]
    if balance:
        hard.append("knos_pay: the vault's Balance refuses an order over its cap, a day or total over its limits, an unlisted spender and an unpinned "
                    "workflow; only the vault, by vote, changes them.")
    advisory = ["Each holder's own limit and dates, and the self-approval limit: Squads keeps no dates or per-person limits (a requester cannot vote at all).",
                "Finance as a separate signature: Squads counts votes, not roles."]
    if len(tiers) > 1:
        advisory.append(f"Tiers by amount: Squads has one threshold, so every vault transaction needs {need} votes, the policy's highest step.")
    if limits:
        advisory.append("Allowances: each is a hard cap on itself and spends without a vote.")
    return {"squads": {"program": SQUADS, "vault_index": int(boundary.get("vault_index", 0)),
                       "create": {"config_authority": authority, "threshold": need, "time_lock": lock, "members": members, "rent_collector": None},
                       "spending_limits": limits},
            "balance": balance, "hard": hard, "advisory": advisory}


def plan_lines(p: dict) -> list[str]:
    s = p["squads"]["create"]
    out = [f"Squads v4 multisig ({p['squads']['program']}), vault {p['squads']['vault_index']}:",
           f"  threshold {s['threshold']}, time lock {s['time_lock']} s, config authority {s['config_authority']}"]
    out += [f"  member {m['key']} ({', '.join('@' + a for a in m['accounts']) or 'executor'}): {', '.join(m['permissions'])}" for m in s["members"]]
    for sl in p["squads"]["spending_limits"]:
        out.append(f"  allowance {sl['name']}: {money(sl['amount'])} a {sl['period']} to {sl['destinations'][0]}, by {len(sl['members'])} key(s), without a vote")
    if p["balance"]:
        b = p["balance"]
        out.append(f"knos_pay Balance opened by the vault for owner {b['owner_id']}: cap {money(b['cap'])} an order, {money(b['day_limit'])} a day, "
                   f"{money(b['total_limit'])} in all (0: none), spenders {b['spenders'] or 'none'}")
    out += ["Hard:"] + [f"  {h}" for h in p["hard"]] + ["Not hard:"] + [f"  {a}" for a in p["advisory"]]
    return out


# ---- approvals bound to one commitment ----------------------------------------------------------------------------------
def commitment(*, repo_id: int, issue: int, seq: int, funder: str, terms_sha256: str, policy_sha256: str, amount: int, beneficiary: str,
               expires: str) -> dict:
    """One commitment and its digest. `amount` in millionths; `beneficiary` a forge account; `expires` a date (the last
    day the approval may fund)."""
    if not _HEX64.fullmatch(terms_sha256) or not _HEX64.fullmatch(policy_sha256) or day_of(expires) is None or amount <= 0:
        raise ValueError("A commitment needs the terms' sha256, the policy's sha256, an amount above 0 and an expiry date.")
    body = {"type": COMMITMENT, "repo_id": int(repo_id), "issue": int(issue), "seq": int(seq), "funder": str(funder),
            "terms_sha256": terms_sha256, "policy_sha256": policy_sha256, "amount": int(amount), "beneficiary": str(beneficiary).lower(),
            "expires": expires}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**body, "digest": digest, "subject": f"order:{digest}"}


_WHAT = (("repo_id", "the repository"), ("issue", "the issue"), ("seq", "the order's sequence"), ("funder", "the funder"),
         ("terms_sha256", "the terms"))


def gate_bound(files: dict[str, str], *, order: dict, requester: str, on: str, fetch=None) -> tuple[bool, str]:
    """Whether an order may be funded by approvals bound to its commitment: (ok, one sentence). `files`: {path: text}
    under .knos/procurement/ on the default branch, with `requests/*.json`, each a commitment as `commitment` makes
    it. `order`: what the funding is about to do: repo_id, issue, seq, funder, terms_sha256, amount, beneficiary.
    Refused, each in its own words: an approval made for another order, after its expiry, under a changed policy, for
    another payee or another amount; and one whose approvals do not meet the policy (approvals.chain)."""
    root = controls.PROCUREMENT
    text = files.get(f"{root}/policy.yaml")
    if text is None:
        return True, ""
    try:
        policy = controls.read_yaml(text)
    except controls.Unread as why:
        return False, f"Refused: {root}/policy.yaml: {why}"
    bad = approvals.policy_problems(policy)
    if bad:
        return False, f"Refused: {root}/policy.yaml is not sound. {bad[0]}"
    now_sha = approvals.sha256_hex(text)
    asked = []
    for path in sorted(files):
        if path.startswith(f"{root}/requests/") and path.endswith(".json"):
            try:
                doc = json.loads(files[path])
            except ValueError:
                continue
            if isinstance(doc, dict) and doc.get("type") == COMMITMENT:
                asked.append(doc)
    if not asked:
        return False, f"Refused: no approval request under {root}/requests/ names this order."
    mine = [r for r in asked if all(str(r.get(k)) == str(order.get(k)) for k, _w in _WHAT)]
    if not mine:
        near = asked[0]
        k = next(w for k, w in _WHAT if str(near.get(k)) != str(order.get(k)))
        return False, f"Refused: the approval request is for another order ({k} differs). An approval covers one commitment."
    for r in mine:
        try:
            again = commitment(**{k: r[k] for k in ("repo_id", "issue", "seq", "funder", "terms_sha256", "policy_sha256", "amount", "beneficiary", "expires")})
        except (KeyError, TypeError, ValueError):
            continue
        if again["digest"] != r.get("digest"):
            return False, "Refused: the approval request was changed after its digest was taken."
        if str(order.get("beneficiary", "")).lower() != again["beneficiary"]:
            return False, f"Refused: the approval is for a payment to @{again['beneficiary']}, not to @{order.get('beneficiary')}."
        if int(order.get("amount", 0)) != again["amount"]:
            return False, f"Refused: the approval is for {money(again['amount'])}, and this order holds {money(int(order.get('amount', 0)))}."
        if (day_of(on) or 0) > (day_of(again["expires"]) or 0):
            return False, f"Refused: the approval expired on {again['expires']}."
        if again["policy_sha256"] != now_sha:
            return False, "Refused: the approval policy changed after this approval was given. Ask for it again under the policy in force."
        events = [e for e in approvals.read_log(files.get(f"{root}/{approvals.LOG}", ""))
                  if fetch is None or approvals.verified(e, fetch(int((e.get("source") or {}).get("comment_id") or 0)) or {})]
        got = approvals.chain(policy, subject=again["subject"], requester=requester, amount=again["amount"], events=events, on=on)
        if not got["met"]:
            return False, f"Refused: `{again['subject'][:18]}...` is not approved. {got['sentence']}"
        return True, got["sentence"]
    return False, "Refused: the approval request is not a commitment `knos boundary bind` made."


def payee_allowed(files: dict[str, str], *, order: dict, payee: str) -> tuple[bool, str]:
    """At payment: whether `payee` is the beneficiary the approved commitment of this order names. No request for the
    order (or no policy): (True, "")."""
    root = controls.PROCUREMENT
    if f"{root}/policy.yaml" not in files:
        return True, ""
    for path in sorted(files):
        if path.startswith(f"{root}/requests/") and path.endswith(".json"):
            try:
                r = json.loads(files[path])
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("type") == COMMITMENT and all(str(r.get(k)) == str(order.get(k)) for k, _w in _WHAT):
                if str(r.get("beneficiary", "")).lower() != str(payee).lower():
                    return False, f"Refused: the approval for this order names @{r.get('beneficiary')} as the payee, not @{payee}."
                return True, f"@{payee} is the payee the approval names."
    return True, ""


# ---- budgets reserved before work starts ----------------------------------------------------------------------------------
class Reservations:
    """A budget and what is held against it, in one SQLite file. Every change takes the write lock before it reads
    (BEGIN IMMEDIATE), so two writers never both see the same room left."""

    def __init__(self, path: str | Path, timeout: float = 30.0):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, timeout=timeout, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS budget (name TEXT PRIMARY KEY, total INTEGER NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS held (request TEXT PRIMARY KEY, budget TEXT NOT NULL, amount INTEGER NOT NULL, "
                        "state TEXT NOT NULL CHECK (state IN ('held','spent','released')))")

    def close(self) -> None:
        self.db.close()

    def _tx(self, fn):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            out = fn()
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")
        return out

    def set_budget(self, name: str, total: int) -> None:
        self._tx(lambda: self.db.execute("INSERT INTO budget(name, total) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET total = excluded.total", (name, total)))

    def taken(self, name: str) -> int:
        return int(self.db.execute("SELECT COALESCE(SUM(amount), 0) FROM held WHERE budget = ? AND state != 'released'", (name,)).fetchone()[0])

    def reserve(self, name: str, request: str, amount: int) -> tuple[bool, str]:
        """Hold `amount` (millionths) of budget `name` for `request`: (ok, one sentence). The same request held again
        with the same amount is the same hold."""
        def go():
            row = self.db.execute("SELECT total FROM budget WHERE name = ?", (name,)).fetchone()
            if row is None:
                return False, f"Refused: there is no budget `{name}`."
            had = self.db.execute("SELECT budget, amount, state FROM held WHERE request = ?", (request,)).fetchone()
            if had is not None:
                if had[0] == name and had[1] == amount and had[2] != "released":
                    return True, f"`{request}` already holds {money(amount)} of `{name}`."
                return False, f"Refused: `{request}` already has a hold of {money(had[1])} on `{had[0]}` ({had[2]})."
            left = int(row[0]) - self.taken(name)
            if amount <= 0 or amount > left:
                return False, f"Refused: `{name}` has {money(max(left, 0))} left, and `{request}` asks for {money(amount)}."
            self.db.execute("INSERT INTO held(request, budget, amount, state) VALUES (?, ?, ?, 'held')", (request, name, amount))
            return True, f"Held {money(amount)} of `{name}` for `{request}`; {money(left - amount)} left."
        return self._tx(go)

    def _move(self, request: str, to: str) -> tuple[bool, str]:
        def go():
            had = self.db.execute("SELECT state FROM held WHERE request = ?", (request,)).fetchone()
            if had is None or had[0] != "held":
                return False, f"Refused: `{request}` holds nothing" + (f" (it is {had[0]})." if had else ".")
            self.db.execute("UPDATE held SET state = ? WHERE request = ?", (to, request))
            return True, f"`{request}` is {to}."
        return self._tx(go)

    def release(self, request: str) -> tuple[bool, str]:
        return self._move(request, "released")

    def spend(self, request: str) -> tuple[bool, str]:
        return self._move(request, "spent")

    def status(self, name: str) -> dict:
        row = self.db.execute("SELECT total FROM budget WHERE name = ?", (name,)).fetchone()
        total = int(row[0]) if row else 0
        holds = [{"request": r, "amount": a, "state": s} for r, a, s in
                 self.db.execute("SELECT request, amount, state FROM held WHERE budget = ? ORDER BY request", (name,))]
        return {"budget": name, "total": total, "taken": self.taken(name), "left": total - self.taken(name), "holds": holds}


# ---- the command line -----------------------------------------------------------------------------------------------------
def register(app, help_lines: list | None = None) -> None:
    """`knos boundary ...` on the main app. `help_lines`: cli._HELP, which gets the group's line."""
    import importlib
    typer = importlib.import_module("typer")

    group = typer.Typer(add_completion=False, no_args_is_help=True, help="The enterprise spending boundary: a Squads vault, bound approvals, reserved budgets.")
    app.add_typer(group, name="boundary")
    if help_lines is not None:
        help_lines.append(("boundary", "For money", "Hold an organisation's money in a Squads vault: plan its settings, bind approvals, reserve budgets."))

    def stop(sentence: str) -> None:
        typer.echo(sentence, err=True)
        raise typer.Exit(1)

    def load(path: Path) -> tuple[dict, str]:
        try:
            text = path.read_text(encoding="utf-8")
            return controls.read_yaml(text), text
        except (OSError, controls.Unread) as why:
            stop(f"Refused: {path}: {why}")
        raise AssertionError

    @group.command("plan")
    def plan_(policy: Path = typer.Argument(..., help="the approval policy, .knos/procurement/policy.yaml"),
              boundary: Path = typer.Option(None, "--boundary", help=f"the boundary file (default: {BOUNDARY_FILE} beside the policy)"),
              as_json: bool = typer.Option(False, "--json", help="print the plan as JSON")) -> None:
        """Turn the approval policy into a Squads v4 vault's settings and the vault's knos_pay Balance, and say what is hard and what is not."""
        doc, _t = load(policy)
        bdoc, _t = load(boundary or policy.with_name(BOUNDARY_FILE))
        try:
            p = plan(doc, bdoc)
        except Refused as why:
            stop(f"Refused: {why}")
        typer.echo(json.dumps(p, indent=1, sort_keys=True) if as_json else "\n".join(plan_lines(p)))

    @group.command("bind")
    def bind_(repo_id: int = typer.Option(..., "--repo-id"), issue: int = typer.Option(..., "--issue"), seq: int = typer.Option(0, "--seq"),
              funder: str = typer.Option(..., "--funder", help="the vault or Balance the order is funded from"),
              terms: Path = typer.Option(..., "--terms", help="the terms JSON the order is funded under"),
              amount: str = typer.Option(..., "--amount"), payee: str = typer.Option(..., "--payee", help="the forge account to be paid"),
              expires: str = typer.Option(..., "--expires", help="the last day the approval may fund, like 2026-11-01"),
              policy: Path = typer.Option(Path(controls.PROCUREMENT) / "policy.yaml", "--policy")) -> None:
        """Print the approval request for one commitment: approvers comment `/knos approve order:<digest>`; save it under .knos/procurement/requests/."""
        units = units_of(amount)
        if units is None:
            stop("Refused: --amount is an amount, like 1200 or 1200.50.")
        try:
            terms_sha = hashlib.sha256(terms.read_bytes().strip()).hexdigest()
            policy_sha = approvals.sha256_hex(policy.read_text(encoding="utf-8"))
            c = commitment(repo_id=repo_id, issue=issue, seq=seq, funder=funder, terms_sha256=terms_sha, policy_sha256=policy_sha,
                           amount=int(units or 0), beneficiary=payee, expires=expires)
        except (OSError, ValueError) as why:
            stop(f"Refused: {why}")
        typer.echo(json.dumps(c, indent=1, sort_keys=True))
        typer.echo(f"Approvers comment: {approvals.comment_line(c['subject'])}", err=True)

    def store(db: Path) -> Reservations:
        return Reservations(db)

    @group.command("reserve")
    def reserve_(db: Path = typer.Option(..., "--db"), budget: str = typer.Option(..., "--budget"), request: str = typer.Option(..., "--request"),
                 amount: str = typer.Option(..., "--amount"), total: str = typer.Option(None, "--total", help="set the budget's total first")) -> None:
        """Hold part of a budget for an approved request, before work starts. Two requests never both take the last of it."""
        r = store(db)
        if total is not None:
            t = units_of(total)
            if t is None:
                stop("Refused: --total is an amount.")
            r.set_budget(budget, int(t or 0))
        units = units_of(amount)
        ok, sentence = r.reserve(budget, request, int(units or 0)) if units is not None else (False, "Refused: --amount is an amount.")
        typer.echo(sentence)
        if not ok:
            raise typer.Exit(1)

    @group.command("release")
    def release_(db: Path = typer.Option(..., "--db"), request: str = typer.Option(..., "--request")) -> None:
        """Give a hold back to its budget (the request was refused or cancelled)."""
        ok, sentence = store(db).release(request)
        typer.echo(sentence)
        if not ok:
            raise typer.Exit(1)

    @group.command("spend")
    def spend_(db: Path = typer.Option(..., "--db"), request: str = typer.Option(..., "--request")) -> None:
        """Mark a hold spent: the order was funded."""
        ok, sentence = store(db).spend(request)
        typer.echo(sentence)
        if not ok:
            raise typer.Exit(1)

    @group.command("status")
    def status_(db: Path = typer.Option(..., "--db"), budget: str = typer.Option(..., "--budget")) -> None:
        """What a budget holds, what is taken and what is left."""
        typer.echo(json.dumps(store(db).status(budget), indent=1, sort_keys=True))
