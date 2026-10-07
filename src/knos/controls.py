"""The budget owner's controls: what a Balance may spend, who may spend it, who may change that, and whether one
funding would pass, all read from the chain; and the three files procurement keeps in the buyer's repository.

    knos budget show  --owner <org>
    knos budget set   --owner <org> [--cap N] [--per-day N] [--total N] [--repo owner/name ...] [--spender login ...] [--pin-workflows]
    knos budget check --owner <org> --repo owner/name --amount N --by <login>
    knos budget who   --owner <org>
    knos budget card     FILE                    is this rate card sound, and does it cite published terms
    knos budget envelope FILE                    an envelope's limit, committed, spent, held and left
    knos budget offer    FILE [--write]          is this standing offer sound, the envelope before and after, the comments that fund it

Nothing here is a rule of its own. The rules are the program's (programs-v2/knos_pay/src: `may_spend`, the cap, and
`spend_x` over the Balance's side account), and `decide` repeats them in the program's order so that `budget check`
names the rule that WOULD refuse before anything is sent: tests/test_controls.py sends the same funding to the
program and compares. web/controls_data.js is the same function for the site; tests/data/controls_cases.json holds
the cases both must answer alike.

What the program checks when a comment funds an order from a Balance, in this order (the number is its error):

    owner       92   the run was not in a repository of the Balance's owner
    spender     92   the commenter is not the owner and not one of the (at most 4) spenders
    cap         93   the amount is more than the cap per order
    repository  92   the side account lists repositories (at most 8) and this is not one
    workflows   86   the side account names one workflows commit and the run was at another
    day         100  amount + fee, with what was spent today (UTC), is more than the daily limit
    total       100  amount + fee, with everything spent since the limits were first set, is more than the total limit
    funds       94   the Balance holds less than amount + fee
    amount      81   the amount is under 5 or over 100,000 whole units

The cap counts the amount; the two limits count what leaves the Balance, which is the amount and the fee on top.
Only the wallet that opened the Balance (its authority) signs a change: SetBalance for the cap and the spenders,
SetBalanceX for the limits, the repositories and the workflows commit. `budget set` builds both with the builders of
knos.settle.v2.pay, sends them when it has that wallet's key, and otherwise prints them (`--dry-run`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from solders.pubkey import Pubkey

from . import commands, fees
from .settle.v2 import pay

RULES = {"owner": 92, "spender": 92, "cap": 93, "repository": 92, "workflows": 86, "day": 100, "total": 100, "funds": 94, "amount": 81, "ok": 0}
MAX_AMOUNT = 100_000_000_000        # millionths of a whole unit: 100,000 an order on devnet (lib.rs MAX_AMOUNT)
FEE_TABLE = (5, 20, 1_000, 5_000, 50_000)      # the amounts the price book shows the effective fee for
DAY = 86_400
ORDER_MIN = pay.ORDER_MIN_AMOUNT       # millionths: the least one order holds (5)


def money(units: int, decimals: int = 6) -> str:
    """An amount as people write it: 400000 -> "0.40", 5000000000 -> "5,000.00"; at least two decimals, no zeros past them."""
    whole, frac = divmod(int(units), 10 ** decimals)
    return f"{whole:,}." + str(frac).rjust(decimals, "0").rstrip("0").ljust(2, "0")


def percent(fee: int, amount: int) -> str:
    """The fee as a share of the amount, in hundredths of a percent, rounded half up: (400000, 5000000) -> "8.00"."""
    h = (fee * 10_000 + amount // 2) // amount if amount > 0 else 0
    return f"{h // 100}.{h % 100:02d}"


def fee_table(bps: int | None = None, decimals: int = 6, rule: fees.Rule = fees.NEW) -> list[dict]:
    """The effective fee at the price book's amounts: [{amount, fee, total, effective_pct}], in the mint's units, under
    `rule` (knos.fees: the tree's by default; pass fees.live(ledger) for the one the cluster's program applies now)."""
    return [{"amount": a, "fee": f, "total": a + f, "effective_pct": percent(f, a)} for a, f in fees.table(FEE_TABLE, rule, bps, decimals)]


@dataclass(frozen=True)
class Decision:
    ok: bool
    rule: str               # a key of RULES: the first rule that refuses, or "ok"
    code: int               # the program's error for it (0: none)
    sentence: str           # what happens and what to do, in plain words
    fee: int                # what the funder pays on top, in the mint's units
    total: int              # amount + fee: what leaves the Balance
    effective_pct: str      # the fee as a percentage of the amount, like "0.30"
    bps: int                # the rate in use: the standard one or the owner's Plan

    def as_json(self) -> dict:
        """The keys web/controls_data.js answers with."""
        return {"ok": self.ok, "rule": self.rule, "code": self.code, "sentence": self.sentence, "fee": self.fee, "total": self.total,
                "effectivePct": self.effective_pct, "bps": self.bps}


def spent_today(x: pay.BalanceX | None, now: int) -> int:
    """What the side account counts for the UTC day of `now`: its counter, or nothing when the counter is of another day."""
    return x.day_spent if x is not None and x.day == now // DAY else 0


def decide(balance: pay.Balance, x: pay.BalanceX | None, repo_id: int, amount: int, by_id: int, now: int, *, plan: pay.Plan | None = None,
           holds: int | None = None, repo_owner_id: int | None = None, wf_sha: str | None = None, decimals: int = 6,
           rule: fees.Rule = fees.NEW) -> Decision:
    """Whether a comment by GitHub id `by_id` in repository `repo_id` may fund an order of `amount` from this Balance at
    `now`, and which rule decides: the program's checks in the program's order (the module's table). `x` is the side
    account (None: the Balance has none), `plan` the owner's Plan, `holds` what the Balance holds, `repo_owner_id` the
    id of the repository's owner and `wf_sha` the commit of the workflows the run would use; a rule whose fact is
    not given (None) is not judged. `rule`: the fee rule (knos.fees) of the program that would be asked."""
    bps = rule.plan_bps(plan, now)
    fee = rule.order(amount, bps, decimals)
    total, m = amount + fee, lambda u: money(u, decimals)
    cost = f"{m(amount)} and a fee of {m(fee)} ({percent(fee, amount)}%) leave the Balance: {m(total)}"

    def no(rule: str, sentence: str) -> Decision:
        return Decision(False, rule, RULES[rule], sentence, fee, total, percent(fee, amount), bps)

    if repo_owner_id is not None and repo_owner_id != balance.owner_id:
        return no("owner", f"Refused: the repository belongs to GitHub id {repo_owner_id}, and this Balance is for the repositories of GitHub id "
                           f"{balance.owner_id}. Fund from a repository of that owner.")
    if by_id == 0 or not (balance.faucet or by_id == balance.owner_id or by_id in balance.spenders):
        return no("spender", f"Refused: GitHub id {by_id} is not the owner ({balance.owner_id}) and is not one of this Balance's spenders "
                             f"({', '.join(map(str, balance.spenders)) or 'none'}). The Balance's wallet can add a spender: knos budget set --spender.")
    if balance.cap_per_job and amount > balance.cap_per_job:
        return no("cap", f"Refused: {m(amount)} is over the cap of {m(balance.cap_per_job)} for one order. Fund less, or the Balance's wallet "
                         "raises the cap: knos budget set --cap.")
    if balance.has_x and x is not None:
        if x.repos and repo_id not in x.repos:
            return no("repository", f"Refused: repository id {repo_id} is not one of the {len(x.repos)} this Balance allows "
                                    f"({', '.join(map(str, x.repos))}). The Balance's wallet can allow it: knos budget set --repo.")
        if x.wf_sha and wf_sha is not None and wf_sha != x.wf_sha:
            return no("workflows", f"Refused: this Balance accepts only runs of the workflows at commit {x.wf_sha}, and this run is at {wf_sha}. "
                                   "Point the repository's workflow file at that commit, or the Balance's wallet pins another: knos budget set --pin-workflows.")
        today = spent_today(x, now)
        if x.day_limit and today + total > x.day_limit:
            return no("day", f"Refused: {cost}, which with the {m(today)} already spent today is over the daily limit of {m(x.day_limit)}. "
                             f"{m(max(x.day_limit - today, 0))} is left until midnight UTC. Fund less, wait, or the Balance's wallet raises it: "
                             "knos budget set --per-day.")
        if x.total_limit and x.total_spent + total > x.total_limit:
            return no("total", f"Refused: {cost}, which with the {m(x.total_spent)} spent so far is over the total limit of {m(x.total_limit)}. "
                               f"{m(max(x.total_limit - x.total_spent, 0))} is left. Fund less, or the Balance's wallet raises it: knos budget set --total.")
    if holds is not None and holds < total:
        return no("funds", f"Refused: {cost}, and the Balance holds {m(holds)}. Add money to it: knos balance deposit.")
    if not pay.units(pay.ORDER_MIN_AMOUNT, decimals) <= amount <= pay.units(MAX_AMOUNT, decimals):
        return no("amount", f"Refused: an order holds between {m(pay.units(pay.ORDER_MIN_AMOUNT, decimals))} and {m(pay.units(MAX_AMOUNT, decimals))}, "
                            f"and {m(amount)} is outside that.")
    return Decision(True, "ok", 0, f"Fine: {cost}.", fee, total, percent(fee, amount), bps)


def authority_of(order: dict, balance: pay.Balance | dict | None = None) -> dict:
    """Who authorised an order's money, for a row of the audit export. `order`: one of knos.records.orders_of.
    `balance`: the Balance it was funded from as it is now (pay.Balance, or a dict with `spenders`), when known.

        funder_id      the GitHub id whose comment funded it (0: a wallet funded it itself)
        role           owner, spender, faucet (test money any commenter spends) or wallet
        listed_now     a spender only: whether today's list still names that id (None: the Balance was not given)
        authorised_by  one cell: "gh:555000 (spender)", "gh:424242 (owner)", "wallet:<address>"

    The role is the program's finding at funding: it accepts a comment only from the owner or a listed spender, so a
    funder who is not the owner WAS a spender then, whatever the list says today."""
    by, owner = int(order.get("by") or 0), int(order.get("owner") or 0)
    if not order.get("from_balance"):
        return {"funder_id": 0, "role": "wallet", "listed_now": None, "authorised_by": f"wallet:{order.get('source', '')}"}
    if by and by == owner:
        role = "owner"
    elif order.get("faucet") or (getattr(balance, "faucet", False) if not isinstance(balance, dict) else balance.get("faucet")):
        role = "faucet"
    else:
        role = "spender" if by else "owner"         # a line that names no commenter is the owner's own Balance, spent by the owner
    spenders = None if balance is None else balance.get("spenders", ()) if isinstance(balance, dict) else balance.spenders
    listed = (by in tuple(spenders)) if role == "spender" and spenders is not None else None
    return {"funder_id": by or owner, "role": role, "listed_now": listed, "authorised_by": f"gh:{by or owner} ({role})"}


# ---- the chain ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Budget:
    """One Balance with everything that limits it, as the chain has it at `now`."""
    address: Pubkey
    balance: pay.Balance
    x: pay.BalanceX | None
    plan: pay.Plan | None
    holds: int
    decimals: int
    now: int
    rule: fees.Rule = fees.NEW      # the fee rule of the program this was read from (knos.fees.live)


def budgets(ledger, owner_id: int) -> list[Budget]:
    """Every Balance set aside for one GitHub owner's repositories (each wallet's, and on devnet the faucet's)."""
    from .settle.v2 import relay
    now, plan = int(ledger.now()), pay.read_plan(ledger.account(pay.plan_pda(owner_id)))
    out, live = [], fees.live(ledger)        # the fee shown follows the build the cluster runs
    for address, b, holds in relay.balances_for(ledger, owner_id):
        mint = ledger.account(b.mint)
        out.append(Budget(address, b, pay.read_balx(ledger.account(pay.balx_pda(address))) if b.has_x else None, plan, holds,
                          mint[44] if mint and len(mint) >= 82 else 6, now, live))
    return out


def pick(found: list[Budget], wallet: Pubkey | None = None, address: str | None = None) -> Budget:
    """The one Balance a command is about: the one at `address`, else the one `wallet` opened, else the only one a
    wallet opened (the faucet's when there is no other). ValueError, in words, when that does not name one."""
    if address:
        got = [b for b in found if str(b.address) == address]
    elif wallet is not None:
        got = [b for b in found if b.balance.authority == wallet and not b.balance.faucet]
    else:
        got = [b for b in found if not b.balance.faucet] or found
    if len(got) == 1:
        return got[0]
    if not got:
        raise ValueError("No such Balance: " + ("this owner has none." if not found else "this owner's are " + ", ".join(str(b.address) for b in found) + "."))
    raise ValueError("This owner has several Balances; name one with --balance: " + ", ".join(f"{b.address} (wallet {b.balance.authority})" for b in got) + ".")


def settings(b: Budget) -> dict:
    """What `budget set` can change, as it stands."""
    x = b.x
    return {"cap": b.balance.cap_per_job, "spenders": tuple(b.balance.spenders), "per_day": x.day_limit if x else 0, "total": x.total_limit if x else 0,
            "repos": tuple(x.repos) if x else (), "workflows": x.wf_sha if x else ""}


def changes(b: Budget, *, cap: int | None = None, spenders=None, per_day: int | None = None, total: int | None = None, repos=None,
            workflows: str | None = None) -> tuple[list, dict, dict]:
    """(the instructions the Balance's authority must sign, the settings before, the settings after). What is None
    stays as it is; 0, () and "" lift a rule. SetBalance carries the cap and the spenders together, SetBalanceX the
    limits, the repositories and the workflows commit together, so each is rebuilt whole from what the chain has."""
    before = settings(b)
    given = {"cap": cap, "spenders": None if spenders is None else tuple(spenders), "per_day": per_day, "total": total,
             "repos": None if repos is None else tuple(repos), "workflows": workflows}
    after: dict = {k: before[k] if v is None else v for k, v in given.items()}
    if len(after["spenders"]) > 4:
        raise ValueError("A Balance has at most 4 spenders besides its owner.")
    if len(after["repos"]) > 8:
        raise ValueError("A Balance lists at most 8 repositories.")
    if 0 in after["spenders"] or 0 in after["repos"]:
        raise ValueError("0 is not a GitHub id.")
    if after["per_day"] and after["total"] and after["per_day"] > after["total"]:
        raise ValueError("The daily limit is more than the total limit, so it would never be reached.")
    ixs, who = [], b.balance.authority
    if (after["cap"], after["spenders"]) != (before["cap"], before["spenders"]):
        ixs.append(pay.set_balance_ix(who, b.address, after["cap"], after["spenders"]))
    side = ("per_day", "total", "repos", "workflows")
    if any(after[k] != before[k] for k in side):
        ixs.append(pay.set_balance_x_ix(who, b.address, after["per_day"], after["total"], after["repos"], after["workflows"]))
    return ixs, before, after


def check(b: Budget, repo_id: int, amount: int, by_id: int, *, repo_owner_id: int | None = None, wf_sha: str | None = None) -> Decision:
    """`decide` over what the chain has now."""
    return decide(b.balance, b.x, repo_id, amount, by_id, b.now, plan=b.plan, holds=b.holds, repo_owner_id=repo_owner_id, wf_sha=wf_sha,
                  decimals=b.decimals, rule=b.rule)


# ---- words --------------------------------------------------------------------------------------------------------------
def _when(t: int) -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))


def _named(ids, name) -> str:
    return ", ".join(f"{n} (id {i})" if (n := name(i)) else f"id {i}" for i in ids)


def show_lines(b: Budget, repo_name=lambda i: "", login=lambda i: "", unit: str = "test USDC") -> list[str]:
    """`knos budget show` for one Balance. `repo_name` and `login`: GitHub's names for ids ("" when unknown)."""
    m, bal, x = (lambda u: money(u, b.decimals)), b.balance, b.x
    today, bps = spent_today(x, b.now), b.rule.plan_bps(b.plan, b.now)
    out = [f"Balance {b.address}: holds {m(b.holds)} {unit}, for the repositories of GitHub id {bal.owner_id}"
           + (f" ({n})" if (n := login(bal.owner_id)) else "") + ".",
           f"  cap per order        {m(bal.cap_per_job) if bal.cap_per_job else 'none'}"]
    if x is None:
        out.append("  daily limit          none (no limits are set: knos budget set --per-day N --total N)")
        out.append(f"  total limit          none; {m(bal.spent)} spent since the Balance was opened")
        out.append("  allowed repositories any repository of the owner")
        out.append("  workflows commit     any")
    else:
        out.append(f"  daily limit          {m(x.day_limit) + f'; {m(today)} spent today (UTC), {m(max(x.day_limit - today, 0))} left' if x.day_limit else f'none; {m(today)} spent today (UTC)'}")
        out.append(f"  total limit          {m(x.total_limit) + f'; {m(x.total_spent)} spent, {m(max(x.total_limit - x.total_spent, 0))} left' if x.total_limit else f'none; {m(x.total_spent)} spent since the limits were first set'}")
        out.append(f"  allowed repositories {_named(x.repos, repo_name) if x.repos else 'any repository of the owner'}")
        out.append(f"  workflows commit     {x.wf_sha or 'any'}")
    out.append("  spenders             " + ("any commenter in the owner's repositories (the devnet faucet: test money)" if bal.faucet else
                                           (_named(bal.spenders, login) if bal.spenders else "none") + ", besides the owner"))
    if b.plan is not None and b.now < b.plan.expires:
        out.append(f"  fee                  a Plan: {b.rule.rate(bps)} until {_when(b.plan.expires)}, then the standard {fees.pct(b.rule.bps)}")
    else:
        out.append(f"  fee                  standard: {b.rule.rate()}"
                   + (f" (a Plan ended {_when(b.plan.expires)})" if b.plan is not None else " (no Plan)"))
    out.append(f"                       the {b.rule.release} fee, which knos_pay {b.rule.build} charges"
               + ("" if b.rule is fees.NEW else f"; from knos_pay {fees.NEW.build}: {fees.NEW.rate()}") + f". {fees.KEEPS}")
    out.append("  The limits count what leaves the Balance (amount and fee); the cap counts the amount.")
    return out


def who_lines(b: Budget, login=lambda i: "") -> list[str]:
    """`knos budget who` for one Balance: who may spend, who may change the limits."""
    bal = b.balance
    if bal.faucet:
        return [f"Balance {b.address} is the devnet faucet's: test money.",
                "  May spend: any commenter in the owner's repositories, as that repository's workflow lets through.",
                "  May change its limits or withdraw: nobody."]
    owner = f"{n} (id {bal.owner_id})" if (n := login(bal.owner_id)) else f"GitHub id {bal.owner_id}"
    return [f"Balance {b.address}",
            f"  May spend, by a comment in a repository of {owner}, within the limits:",
            f"    the owner: {owner}",
            *(f"    a spender: {_named([s], login)}" for s in bal.spenders),
            *([] if bal.spenders else ["    no spender is listed"]),
            "  May change the cap, the limits, the repositories, the spenders and the workflows commit, and withdraw:",
            f"    wallet {bal.authority}, which opened the Balance. Nobody else: not a spender, not the owner's GitHub account, not Knos.",
            "  If that wallet is a multisig's vault, its members and threshold are the approval; Knos adds no second approver.",
            "  Knos's fee wallet can set a lower fee rate for the owner (a Plan). It cannot spend, raise a limit or take money."]


def change_lines(before: dict, after: dict, decimals: int = 6, repo_name=lambda i: "", login=lambda i: "") -> list[str]:
    """What `budget set` would change, one line per setting: before -> after."""
    m = lambda u: money(u, decimals) if u else "none"  # noqa: E731
    say = {"cap": ("cap per order", m), "per_day": ("daily limit", m), "total": ("total limit", m),
           "repos": ("allowed repositories", lambda v: _named(v, repo_name) if v else "any repository of the owner"),
           "spenders": ("spenders", lambda v: _named(v, login) if v else "none"), "workflows": ("workflows commit", lambda v: v or "any")}
    return [f"  {say[k][0]:<21}{say[k][1](before[k])}" + ("  (unchanged)" if before[k] == after[k] else f"  ->  {say[k][1](after[k])}") for k in say]


def ix_json(ix) -> dict:
    """An instruction as data, for a wallet that signs elsewhere (a multisig's proposal)."""
    return {"program": str(ix.program_id), "data_hex": bytes(ix.data).hex(),
            "accounts": [{"address": str(a.pubkey), "signer": a.is_signer, "writable": a.is_writable} for a in ix.accounts]}


# ---- procurement: a rate card, a standing offer and a budget envelope, each a small file in the buyer's repository -----
# Nothing here is a second model. A rate card's outcome cites a published terms template by its hash (terms/,
# knos.terms_templates); a standing offer becomes the `/knos offer` comment knos.commands already reads, one per
# supplier and period; an envelope is the finance owner's limit over the same money `decide` judges on chain, and it
# counts what leaves the Balance: the amount and the fee on top. The files are a small, fixed part of YAML that this
# module and web/procure.js read with the same few lines and judge with the same sentences
# (tests/data/procure_cases.json holds both to one answer). docs/CONTROLS.md, "Procurement files", is the schema.
PROCUREMENT = ".knos/procurement"           # the directory in the buyer's repository
FILES = {"rate-card": "rate-cards", "standing-offer": "offers", "budget-envelope": "envelopes"}     # kind -> subdirectory; the policy is policy.yaml
PERIODS = {"week": 7, "month": 30, "quarter": 90}       # a cap's period in days: at most what one order may wait (knos_pay MAX_WORK)
UNIT6 = 1_000_000
MAX_RETRIES = 20
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")
_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_]*):(?: +(.*))?")
_INT = re.compile(r"-?(?:0|[1-9][0-9]{0,14})")
_BARE = re.compile(r"[A-Za-z_@/][A-Za-z0-9_./@-]*(?: [A-Za-z0-9_./@-]+)*")


class Unread(ValueError):
    """The file is not the part of YAML these files are written in; the message names the line."""


def _uncomment(line: str) -> str:
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"' and (i == 0 or line[i - 1] != "\\"):
            quoted = not quoted
        elif ch == "#" and not quoted and (i == 0 or line[i - 1] == " "):
            return line[:i]
    return line


def _items(inner: str) -> list[str]:
    out, quoted, start = [], False, 0
    for i, ch in enumerate(inner):
        if ch == '"' and (i == 0 or inner[i - 1] != "\\"):
            quoted = not quoted
        elif ch == "," and not quoted:
            out.append(inner[start:i])
            start = i + 1
    return out + [inner[start:]]


def _scalar(text: str, n: int):
    s = text.strip()
    if s in ("", "null", "~"):
        return None
    if s[0] == '"':
        try:
            got = json.loads(s)
        except ValueError:
            got = None
        if not isinstance(got, str):
            raise Unread(f"Line {n}: the quoted text does not end where the line does.")
        return got
    if s[0] == "[":
        if not s.endswith("]"):
            raise Unread(f"Line {n}: a list in brackets ends on its own line.")
        inner = s[1:-1].strip()
        return [_scalar(p, n) for p in _items(inner)] if inner else []
    if s[0] in "{|>&*!'%`":
        raise Unread(f"Line {n}: these files use plain keys, lists and values only; `{s[0]}` starts something else.")
    if s in ("true", "false"):
        return s == "true"
    return int(s) if _INT.fullmatch(s) else s


def _map(rows: list, i: int, indent: int) -> tuple[dict, int]:
    out: dict = {}
    while i < len(rows) and rows[i][0] == indent and not rows[i][1].startswith("- "):
        _ind, s, n = rows[i]
        m = _KEY.fullmatch(s)
        if not m:
            raise Unread(f"Line {n}: expected `key: value`.")
        key, rest = m.group(1), m.group(2)
        if key in out:
            raise Unread(f"Line {n}: `{key}` is written twice.")
        i += 1
        if rest:
            out[key] = _scalar(rest, n)
        elif i < len(rows) and (rows[i][0] > indent or (rows[i][0] == indent and rows[i][1].startswith("- "))):
            out[key], i = _block(rows, i)
        else:
            out[key] = None
    return out, i


def _block(rows: list, i: int) -> tuple[dict | list, int]:
    indent = rows[i][0]
    if not rows[i][1].startswith("- "):
        return _map(rows, i, indent)
    out: list = []
    while i < len(rows) and rows[i][0] == indent and rows[i][1].startswith("- "):
        _ind, s, n = rows[i]
        body = s[2:].lstrip(" ")
        if _KEY.fullmatch(body):
            inner = indent + len(s) - len(body)
            rows[i] = (inner, body, n)
            item, i = _map(rows, i, inner)
            out.append(item)
        else:
            out.append(_scalar(body, n))
            i += 1
    return out, i


def read_yaml(text: str):
    """One procurement file as data. The part of YAML read: `key: value`, nested keys, `- item` lists (of values or of
    keys), `[a, b]` lists, "quoted text", whole numbers, true, false, null and `#` comments. Dates and amounts with a
    decimal point stay text. Anything else is refused with its line (Unread)."""
    rows = []
    for n, raw in enumerate(str(text).replace("\r\n", "\n").split("\n"), 1):
        line = _uncomment(raw).rstrip(" ")
        if "\t" in line:
            raise Unread(f"Line {n}: indent with spaces, not tabs.")
        if line.strip(" ") in ("", "---"):
            continue
        rows.append((len(line) - len(line.lstrip(" ")), line.strip(" "), n))
    if not rows:
        raise Unread("The file is empty.")
    value, i = _block(rows, 0)
    if i != len(rows):
        raise Unread(f"Line {rows[i][2]}: the indentation matches nothing above it.")
    return value


def _plain(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    return s if _DATE.fullmatch(s) or (_BARE.fullmatch(s) and s not in ("true", "false", "null")) else json.dumps(s, ensure_ascii=True)


def dump_yaml(doc: dict, indent: int = 0) -> str:
    """The file `read_yaml` reads back to `doc`: keys in the order given, a list of values on one line."""
    out, pad = [], " " * indent
    for k, v in doc.items():
        if isinstance(v, dict):
            out += [f"{pad}{k}:", dump_yaml(v, indent + 2)[:-1]]
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            out.append(f"{pad}{k}:")
            for item in v:
                first, *rest = dump_yaml(item, indent + 4)[:-1].split("\n")
                out += [f"{pad}  - {first.strip(' ')}", *rest]
        elif isinstance(v, list):
            out.append(f"{pad}{k}: [{', '.join(_plain(x) for x in v)}]")
        else:
            out.append(f"{pad}{k}: {_plain(v)}")
    return "\n".join(out) + "\n"


def units_of(v) -> int | None:
    """Whole units as a file writes them (50, "12.5") in millionths, or None when it is not an amount."""
    m = re.fullmatch(r"([0-9]{1,9})(?:\.([0-9]{1,6}))?", str(v)) if isinstance(v, (int, str)) and not isinstance(v, bool) else None
    return None if not m else int(m.group(1)) * UNIT6 + int((m.group(2) or "").ljust(6, "0"))


def day_of(v) -> int | None:
    """A date written 2026-10-01 as a day number (days since 1970-01-01), or None when it is not a date."""
    import datetime
    if not isinstance(v, str) or not _DATE.fullmatch(v):
        return None
    try:
        return datetime.date.fromisoformat(v).toordinal() - 719_163
    except ValueError:
        return None


def _is(pattern: re.Pattern, v) -> bool:
    return isinstance(v, str) and bool(pattern.fullmatch(v))


def _head(doc, kind: str, what: str, fields: tuple[str, ...]) -> list[str]:
    """What every file starts with: a mapping, `version: 1`, its `kind`, a `name`, and no field nobody reads."""
    if not isinstance(doc, dict):
        return [f"{what.capitalize()} is a list of `key: value` lines, and this is not."]
    out = [f"`{k}` is not a field of {what}." for k in doc if k not in fields]
    if doc.get("version") != 1 or isinstance(doc.get("version"), bool):
        out.append("`version` must be 1.")
    if doc.get("kind") != kind:
        out.append(f"`kind` must be {kind}.")
    if "name" in fields and not _is(_SLUG, doc.get("name")):
        out.append("`name` is lower-case letters, digits and hyphens, like eng-2026q4.")
    if "currency" in fields and doc.get("currency") != "test USDC":
        out.append("`currency` must be test USDC: this is devnet.")
    return out


def _span(doc: dict, a: str, b: str) -> list[str]:
    da, db = day_of(doc.get(a)), day_of(doc.get(b))
    out = [f"`{k}` is a date like 2026-10-01." for k, d in ((a, da), (b, db)) if d is None]
    if da is not None and db is not None and da > db:
        out.append(f"`{a}` is after `{b}`.")
    return out


CARD_FIELDS = ("version", "kind", "name", "currency", "valid_from", "valid_to", "outcomes")
OUTCOME_FIELDS = ("name", "price", "unit", "terms", "terms_hash")
OFFER_FIELDS = ("version", "kind", "name", "rate_card", "outcome", "suppliers", "cap", "period", "starts", "ends", "envelope", "requested_by", "retries", "reopened")
ENVELOPE_FIELDS = ("version", "kind", "name", "owner", "cost_centre", "currency", "period_from", "period_to", "limit", "committed", "spent", "held", "left", "as_of")
REOPENED = {"same": "Reopened work is the same deliverable: it is not billed again.", "new": "Reopened work is a new deliverable: it needs a new approval."}


def card_problems(doc, published: dict | None = None) -> list[str]:
    """What is wrong with a rate card, in sentences ([]: nothing). `published`: {terms template: its hash}, when known."""
    out = _head(doc, "rate-card", "a rate card", CARD_FIELDS)
    if not isinstance(doc, dict):
        return out
    out += _span(doc, "valid_from", "valid_to")
    rows = doc.get("outcomes")
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        return out + ["`outcomes` lists at least one outcome, each with a name, a price, a unit and its terms."]
    seen: set = set()
    for n, r in enumerate(rows, 1):
        name = r.get("name")
        me = f"Outcome `{name}`" if _is(_SLUG, name) else f"Outcome {n}"
        out += [f"{me}: `{k}` is not a field of an outcome." for k in r if k not in OUTCOME_FIELDS]
        if not _is(_SLUG, name):
            out.append(f"{me}: `name` is lower-case letters, digits and hyphens.")
        elif name in seen:
            out.append(f"{me} is listed twice.")
        seen.add(name)
        price = units_of(r.get("price"))
        if not price:
            out.append(f"{me}: `price` is an amount above zero, like 50 or 12.5.")
        elif not ORDER_MIN <= price <= MAX_AMOUNT:
            out.append(f"{me}: devnet pays between {money(ORDER_MIN)} and {money(MAX_AMOUNT)} for one outcome.")
        if not isinstance(r.get("unit"), str) or not 0 < len(r["unit"]) <= 60:
            out.append(f"{me}: `unit` says what is counted, like accepted pull request.")
        if not _is(_SLUG, r.get("terms")) or not _is(_HEX64, r.get("terms_hash")):
            out.append(f"{me}: `terms` names a template of terms/, and `terms_hash` is its 64 hex characters.")
        elif published is not None and r["terms"] not in published:
            out.append(f"{me}: terms/ has no template `{r['terms']}`.")
        elif published is not None and published[r["terms"]] != r["terms_hash"]:
            out.append(f"{me}: `terms_hash` is not the published hash of `{r['terms']}`.")
    return out


def outcome_of(card: dict, name) -> dict | None:
    return next((r for r in card.get("outcomes") or [] if isinstance(r, dict) and r.get("name") == name), None)


def offer_problems(doc, card: dict | None = None) -> list[str]:
    """What is wrong with a standing offer ([]: nothing). `card`: the rate card it names, already found sound."""
    out = _head(doc, "standing-offer", "a standing offer", OFFER_FIELDS)
    if not isinstance(doc, dict):
        return out
    out += _span(doc, "starts", "ends")
    who = doc.get("suppliers")
    if who != "anyone" and not (isinstance(who, list) and who and all(_is(_LOGIN, w) for w in who) and len({str(w).lower() for w in who}) == len(who)):
        out.append("`suppliers` is anyone, or a list of forge accounts, each once.")
    cap = units_of(doc.get("cap"))
    if not cap:
        out.append("`cap` is an amount above zero: the most one supplier is paid in one period.")
    elif cap > MAX_AMOUNT:
        out.append(f"`cap` is over {money(MAX_AMOUNT)}, the most devnet holds in one order.")
    if doc.get("period") not in PERIODS:
        out.append("`period` is week, month or quarter.")
    for k in ("rate_card", "envelope"):
        if not _is(_SLUG, doc.get(k)):
            out.append(f"`{k}` is the name of a file beside this one.")
    if not _is(_SLUG, doc.get("outcome")):
        out.append("`outcome` names one outcome of the rate card.")
    if not _is(_LOGIN, doc.get("requested_by")):
        out.append("`requested_by` is the forge account of whoever asks for this.")
    retries = doc.get("retries")
    if isinstance(retries, bool) or not isinstance(retries, int) or not 1 <= retries <= MAX_RETRIES:
        out.append(f"`retries` is how many evaluations one deliverable may take: 1 to {MAX_RETRIES}.")
    if doc.get("reopened") not in REOPENED:
        out.append("`reopened` is same (not billed again) or new (a new deliverable).")
    if card is not None and not out:
        row = outcome_of(card, doc["outcome"])
        if doc["rate_card"] != card.get("name"):
            out.append(f"The offer names rate card `{doc['rate_card']}`, and this card is `{card.get('name')}`.")
        elif row is None:
            out.append(f"Rate card `{card['name']}` has no outcome `{doc['outcome']}`.")
        else:
            if cap is not None and cap < (units_of(row.get("price")) or 0):       # (no problem was found above, so the cap was read)
                out.append(f"The cap of {money(cap)} is less than one `{row['name']}` at {money(units_of(row['price']) or 0)}.")
            if (day_of(doc["starts"]) or 0) < (day_of(card.get("valid_from")) or 0) or (day_of(doc["ends"]) or 0) > (day_of(card.get("valid_to")) or 0):
                out.append(f"The offer runs outside the rate card, which is valid {card.get('valid_from')} to {card.get('valid_to')}.")
    return out


def envelope_state(doc: dict) -> dict:
    """An envelope's five amounts in millionths: {limit, committed, spent, held, left}. Committed: promised by open
    offers and funded orders, not yet accepted. Spent: paid for accepted work. Held: accepted, and waiting (a
    holdback, or a supplier with no payout address). Left: the limit less the three; never typed, always worked out."""
    limit, committed, spent, held = (units_of(doc.get(k, 0)) or 0 for k in ("limit", "committed", "spent", "held"))
    return {"limit": limit, "committed": committed, "spent": spent, "held": held, "left": limit - committed - spent - held}


def envelope_problems(doc) -> list[str]:
    """What is wrong with a budget envelope ([]: nothing)."""
    out = _head(doc, "budget-envelope", "a budget envelope", ENVELOPE_FIELDS)
    if not isinstance(doc, dict):
        return out
    out += _span(doc, "period_from", "period_to")
    if not _is(_LOGIN, doc.get("owner")):
        out.append("`owner` is the forge account of whoever answers for this budget.")
    if not isinstance(doc.get("cost_centre"), str) or not 0 < len(doc["cost_centre"]) <= 40:
        out.append("`cost_centre` is your own code for it, like ENG-410.")
    if not units_of(doc.get("limit")):
        out.append("`limit` is an amount above zero.")
    bad = [k for k in ("committed", "spent", "held") if k in doc and units_of(doc[k]) is None]
    out += [f"`{k}` is an amount, like 0 or 250.5." for k in bad]
    if "as_of" in doc and day_of(doc["as_of"]) is None:
        out.append("`as_of` is a date like 2026-10-01.")
    if not bad and units_of(doc.get("limit")):
        s = envelope_state(doc)
        if s["left"] < 0:
            out.append(f"The envelope is over its limit by {money(-s['left'])}.")
        elif "left" in doc and units_of(doc["left"]) != s["left"]:
            out.append(f"`left` says {doc['left']}, and the limit less committed, spent and held is {money(s['left'])}.")
    return out


def periods_of(offer: dict) -> int:
    """How many periods a sound offer spans: the nearest whole number, at least one (a quarter is three months)."""
    days, one = (day_of(offer["ends"]) or 0) - (day_of(offer["starts"]) or 0) + 1, PERIODS[offer["period"]]
    return max(1, (days + one // 2) // one)


def commitment(offer: dict, bps: int | None = None, rule: fees.Rule = fees.NEW) -> dict:
    """What opening a sound offer promises, in millionths: {suppliers, periods, cap, fee, value, leaves}. The cap is
    one supplier's for one period, and each is funded by one comment, so `fee` is the fee of one cap under `rule`; `value`
    is caps alone (what an approval is asked for) and `leaves` adds the fees (what an envelope counts)."""
    cap = units_of(offer["cap"]) or 0
    n, periods, fee = (1 if offer["suppliers"] == "anyone" else len(offer["suppliers"])), periods_of(offer), rule.order(cap, bps)
    return {"suppliers": n, "periods": periods, "cap": cap, "fee": fee, "value": cap * n * periods, "leaves": (cap + fee) * n * periods}


def fit(envelope: dict, leaves: int, decision: Decision | None = None) -> dict:
    """Whether `leaves` more (amount and fee, in millionths) fits a sound envelope, shown before anything starts:
    {ok, over, before, after, sentence}. Over the limit it is refused with the amount it is over by. `decision`: what
    `decide` said of the same funding on chain, when asked; its refusal stands first."""
    before = envelope_state(envelope)
    after = {**before, "committed": before["committed"] + leaves, "left": before["left"] - leaves}
    over, name = max(0, -after["left"]), envelope.get("name")
    if decision is not None and not decision.ok:
        return {"ok": False, "over": over, "before": before, "after": before, "sentence": decision.sentence}
    if over:
        return {"ok": False, "over": over, "before": before, "after": before,
                "sentence": f"Refused: this is {money(over)} over envelope `{name}`. {money(max(before['left'], 0))} of {money(before['limit'])} is left."}
    return {"ok": True, "over": 0, "before": before, "after": after,
            "sentence": f"Fits: {money(leaves)} is committed, and {money(after['left'])} stays in envelope `{name}`."}


def offer_parts(offer: dict, card: dict, supplier: str, template: dict) -> dict:
    """One supplier's share of a sound offer in the shape web/buyer_templates.json gives a template's `parts`, so the
    comment is built as every other is: the outcome's price is the rate, the cap the budget, the period the days, and
    the checks and paths are those of the terms template the outcome cites (`template`: its parts)."""
    row = outcome_of(card, offer["outcome"]) or {}
    return {**template, "kind": "offer", "vendor": supplier, "rate": commands.amount(units_of(row.get("price")) or 0),
            "amount": commands.amount(units_of(offer["cap"]) or 0), "holdback": 0, "warranty": 0, "days": PERIODS[offer["period"]]}


def offer_comment(parts: dict, default_days: int = commands.DAYS) -> str:
    """The comment that funds one supplier's cap for one period on devnet, as web/buyer.js commentOf writes it."""
    return " ".join(filter(None, [f"/knos offer @{parts['vendor']} rate {parts['rate']} budget {parts['amount']}",
                                  f"checks: {', '.join(parts['checks'])}" if parts["checks"] else "", f"paths: {', '.join(parts['paths'])}" if parts["paths"] else "",
                                  f"days {parts['days']}" if int(parts["days"]) != default_days else ""]))


def policy_lines(offer: dict, card: dict, template: dict) -> str:
    """The `offers:` entries for `.knos/policy.yml` (knos.policy), one per supplier: the file the funding workflow
    already holds every `/knos offer` to. Its budget is by the calendar month, so a monthly cap is carried whole."""
    row = outcome_of(card, offer["outcome"]) or {}
    rows = [{"vendor": who, "rate": commands.amount(units_of(row.get("price")) or 0), "budget": commands.amount(units_of(offer["cap"]) or 0), **({"checks": template["checks"]} if template["checks"] else {})}
            for who in ([] if offer["suppliers"] == "anyone" else offer["suppliers"])]
    return "".join(f"  - vendor: {r['vendor']}\n    rate: {r['rate']}\n    budget: {r['budget']}\n" + (f"    checks: [{', '.join(r['checks'])}]\n" if "checks" in r else "") for r in rows)


def published_terms() -> dict:
    """{terms template: the sha256 of its canonical terms}, for the templates terms/ publishes."""
    from . import terms_templates as tt
    return {name: tt.export(name)["terms_hash"] for name in tt.TEMPLATES}


def template_parts(name: str) -> dict:
    """The checks, paths and mode of a published terms template, as scripts/buyer_templates.py writes its `parts`."""
    from . import terms_templates as tt
    cmd, tm = tt.command(tt.get(name)), tt.terms_of(tt.get(name))
    return {"mode": tm["mode"], "checks": list(cmd.checks or ()), "paths": list(cmd.paths or ())}


SAMPLE_REPOSITORY = "drexthealpha/knos-playground"     # where the sample below is set: web/buyer.js PLAYGROUND


def sample() -> dict:
    """One small organisation's four files and its approvals so far, as data: what the console shows before a
    repository is named, and what the tests and docs/CONTROLS.md use. It is set in this project's own playground
    repository, drexthealpha/knos-playground, so that no link of the console leads to somebody else's; the files and the
    people in them (the -acme accounts) are made up."""
    hashes = published_terms()
    card = {"version": 1, "kind": "rate-card", "name": "maintenance-2026q4", "currency": "test USDC", "valid_from": "2026-10-01", "valid_to": "2026-12-31",
            "outcomes": [{"name": "bug-fix", "price": 50, "unit": "accepted pull request", "terms": "bugfix", "terms_hash": hashes["bugfix"]},
                         {"name": "feature", "price": 80, "unit": "accepted pull request", "terms": "feature-blackbox", "terms_hash": hashes["feature-blackbox"]}]}
    envelope = {"version": 1, "kind": "budget-envelope", "name": "eng-2026q4", "owner": "dana-acme", "cost_centre": "ENG-410", "currency": "test USDC",
                "period_from": "2026-10-01", "period_to": "2026-12-31", "limit": 5000, "committed": 1200, "spent": 850, "held": 150, "as_of": "2026-10-05"}
    offer = {"version": 1, "kind": "standing-offer", "name": "bug-fix-octocat", "rate_card": "maintenance-2026q4", "outcome": "bug-fix", "suppliers": ["octocat"],
             "cap": 400, "period": "month", "starts": "2026-10-01", "ends": "2026-12-31", "envelope": "eng-2026q4", "requested_by": "ravi-acme",
             "retries": 3, "reopened": "same"}
    holder = lambda who, **more: {"account": who, "from": "2026-01-01", "until": "2026-12-31", **more}  # noqa: E731
    policy = {"version": 1, "kind": "approval-policy", "currency": "test USDC", "self_approval_limit": 0,
              "roles": {"requester": [holder("ravi-acme"), holder("mei-acme")], "approver": [holder("mei-acme", limit=25000), holder("sam-acme"), {"account": "lee-acme", "from": "2026-01-01", "until": "2026-06-30"}],
                        "finance": [holder("dana-acme")], "auditor": [holder("noor-acme")]},
              "thresholds": [{"up_to": 1000, "approvers": 1}, {"up_to": 25000, "approvers": 2}, {"approvers": 2, "finance": 1}]}
    return {"owner": "drexthealpha", "repository": SAMPLE_REPOSITORY, "branch": "main", "today": "2026-10-06", "rate_card": card, "envelope": envelope, "offers": [offer], "policy": policy}


# ---- the commands -------------------------------------------------------------------------------------------------------
def register(app, help_lines: list | None = None) -> None:
    """`knos budget show | set | check | who`, on the main app. `help_lines`: cli._HELP, which gets the group's line."""
    import json
    import os

    import importlib
    typer = importlib.import_module("typer")       # the command line's package, named here and not imported: the relay reaches this module on an install without it

    budget_app = typer.Typer(add_completion=False, no_args_is_help=True,
                             help="A Balance's limits: see them, set them, ask whether a funding would pass, and see who has authority. Rate cards, standing offers and budget envelopes: check the files.")
    app.add_typer(budget_app, name="budget")
    if help_lines is not None:
        help_lines.append(("budget", "For money", "A Balance's cap, daily and total limits, repositories and spenders: show, set, check, who."))
    owner_opt = typer.Option(..., "--owner", help="the GitHub login or id of the organisation whose repositories spend the Balance")
    balance_opt = typer.Option(None, "--balance", help="the Balance's address, when the owner has several")
    names_opt = typer.Option(False, "--no-names", help="do not ask GitHub for names: ids only")

    def found(cli, ledger, owner: str) -> tuple[int, list[Budget]]:
        oid = cli._owner(owner)
        got = budgets(ledger, oid)
        if not got:
            raise cli.Stop(f"No Balance is set aside for GitHub owner id {oid}.", f"A wallet opens one: knos balance open {owner} --keypair FILE")
        return oid, got

    def one(cli, got: list[Budget], wallet=None, address: str | None = None) -> Budget:
        try:
            return pick(got, wallet, address)
        except ValueError as why:
            raise cli.Stop(str(why)) from None

    def namers(cli, no_names: bool):
        names = cli._names(no_names)
        return names, (lambda i: str(names.repo(i).get("full_name", ""))), names.user

    def repo_of(cli, text: str) -> tuple[int, int | None]:
        """(the repository's id, its owner's id when GitHub was asked) for owner/name or a numeric id."""
        if text.isdigit():
            return int(text), None
        if "/" not in text:
            raise cli.Stop(f"Name a repository as owner/name or by its numeric id; {text!r} is neither.")
        got = cli._github(f"repos/{text}")
        return int(got["id"]), int((got.get("owner") or {}).get("id") or 0) or None

    def unit(b: Budget) -> str:
        return "test USDC" if b.balance.mint in (pay.USDC_DEVNET, pay.faucet_mint()) else f"of mint {b.balance.mint}"

    @budget_app.command("show")
    def show_(owner: str = owner_opt, balance: str = balance_opt, no_names: bool = names_opt) -> None:
        """Every limit of an organisation's Balance, read from the chain: the cap per order, the daily limit and what is spent today, the total limit and what is spent, the repositories that may spend it, the spenders, the pinned workflows commit, and the fee rate with a Plan's expiry."""
        from . import cli
        _oid, got = found(cli, cli._ledger(), owner)
        names, repo_name, login = namers(cli, no_names)
        for b in ([one(cli, got, address=balance)] if balance else got):
            for line in show_lines(b, repo_name, login, unit(b)):
                cli.out.print(line, markup=False)
        cli._said(names)

    @budget_app.command("who")
    def who_(owner: str = owner_opt, balance: str = balance_opt, no_names: bool = names_opt) -> None:
        """Who may spend an organisation's Balance, and who may change its limits: the wallet that opened it, and nobody else."""
        from . import cli
        _oid, got = found(cli, cli._ledger(), owner)
        names, _repo_name, login = namers(cli, no_names)
        for b in ([one(cli, got, address=balance)] if balance else got):
            for line in who_lines(b, login):
                cli.out.print(line, markup=False)
        cli._said(names)

    @budget_app.command("check")
    def check_(owner: str = owner_opt, repo: str = typer.Option(..., "--repo", help="the repository the funding comment would be in: owner/name, or its id"),
               amount: str = typer.Option(..., "--amount", help="how much the order would hold, like 500 or 12.5"),
               by: str = typer.Option(..., "--by", help="the GitHub login or id of the person who would comment"),
               workflows: str = typer.Option(None, "--workflows-commit", help="the commit of the workflows the run would use (judged only when given)"),
               balance: str = balance_opt, as_json: bool = typer.Option(False, "--json", help="print the answer as JSON")) -> None:
        """Would this funding pass? Nothing is sent. Says which rule decides (not a spender; over the cap; repository not allowed; over today's limit; over the total limit; fine) and what it would cost, the fee as an amount and as a percentage. Exit status 1 when it would be refused."""
        from . import cli
        _oid, got = found(cli, cli._ledger(), owner)
        b = one(cli, got, address=balance)
        repo_id, repo_owner = repo_of(cli, repo)
        d = check(b, repo_id, cli._units(amount, b.decimals), cli._owner(by), repo_owner_id=repo_owner, wf_sha=workflows)
        if as_json:
            typer.echo(json.dumps({"balance": str(b.address), **d.as_json()}, sort_keys=True))
        else:
            cli.out.print(d.sentence, markup=False)
            cli.out.print(f"  rule: {d.rule}" + (f" (the program's error {d.code})" if d.code else "") + f"; amount {money(d.total - d.fee, b.decimals)}, "
                          f"fee {money(d.fee, b.decimals)} ({d.effective_pct}% of the amount), together {money(d.total, b.decimals)} {unit(b)}", markup=False)
            cli.out.print(f"  Balance {b.address}, as the chain has it at {_when(b.now)}. Nothing was sent.", markup=False)
        if not d.ok:
            raise typer.Exit(1)

    @budget_app.command("set")
    def set_(owner: str = owner_opt, cap: str = typer.Option(None, "--cap", help="the most one order may hold; 0 for no cap"),
             per_day: str = typer.Option(None, "--per-day", help="the most the Balance may spend in one UTC day, fees included; 0 for no limit"),
             total: str = typer.Option(None, "--total", help="the most it may spend in all, counted from when limits were first set; 0 for no limit"),
             repo: list[str] = typer.Option(None, "--repo", help="a repository that may spend it (owner/name or id): these replace the list (up to 8)"),
             any_repo: bool = typer.Option(False, "--any-repo", help="empty the list: any repository of the owner may spend it"),
             spender: list[str] = typer.Option(None, "--spender", help="who may spend it besides the owner: these replace the list (up to 4)"),
             no_spenders: bool = typer.Option(False, "--no-spenders", help="empty the list: only the owner spends it"),
             pin: bool = typer.Option(None, "--pin-workflows/--no-pin-workflows", help="accept only runs of this release's workflows commit / of any commit"),
             commit: str = typer.Option(None, "--workflows-commit", help="with --pin-workflows: that commit (40 hex characters) and not this release's"),
             balance: str = balance_opt, dry_run: bool = typer.Option(False, "--dry-run", help="print what would change and the instructions; send nothing (the default without a key)"),
             as_json: bool = typer.Option(False, "--json", help="with --dry-run: the instructions as JSON, for a wallet that signs elsewhere"),
             keypair: Path = typer.Option(None, "--keypair", help="the wallet that opened the Balance: a Solana keypair file (default: KNOS_WALLET_KEY)"),
             no_names: bool = names_opt) -> None:
        """Set a Balance's cap per order, its daily and total limits, the repositories and spenders that may spend it, and the one workflows commit that may sign for it. What is not named stays as it is. Only the wallet that opened the Balance can sign this; without its key the command prints what would change, before and after, and the instructions to sign."""
        import re

        from . import cli
        if all(v is None for v in (cap, per_day, total, pin, commit)) and not (repo or any_repo or spender or no_spenders):
            raise cli.Stop("Say what to change: --cap N, --per-day N, --total N, --repo owner/name, --any-repo, --spender LOGIN, --no-spenders, "
                           "--pin-workflows or --no-pin-workflows.")
        if commit is not None and not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise cli.Stop("--workflows-commit is a full commit: 40 hex characters in lower case.")
        dry = dry_run or not (keypair or os.environ.get("KNOS_WALLET_KEY"))
        wallet, ledger = (None if dry else cli._wallet(keypair)), cli._ledger()
        _oid, got = found(cli, ledger, owner)
        b = one(cli, got, None if wallet is None else wallet.pubkey(), balance)
        if b.balance.faucet:
            raise cli.Stop("That is the devnet faucet's Balance: nobody sets its limits.")
        if wallet is not None and wallet.pubkey() != b.balance.authority:
            raise cli.Stop(f"Balance {b.address} was opened by wallet {b.balance.authority}; this key is {wallet.pubkey()}. Only that wallet changes it.")
        amount = lambda text: None if text is None else cli._units(text, b.decimals)  # noqa: E731
        sha = None if pin is None and commit is None else "" if pin is False else commit or cli._release_pin()[1]
        try:
            ixs, before, after = changes(b, cap=amount(cap), per_day=amount(per_day), total=amount(total),
                                         repos=() if any_repo else [repo_of(cli, r)[0] for r in repo] if repo else None,
                                         spenders=() if no_spenders else [cli._owner(s) for s in spender] if spender else None, workflows=sha)
        except ValueError as why:
            raise cli.Stop(str(why)) from None
        names, repo_name, login = namers(cli, no_names)
        if as_json and dry:
            typer.echo(json.dumps({"balance": str(b.address), "authority": str(b.balance.authority), "before": before, "after": after,
                                   "instructions": [ix_json(ix) for ix in ixs]}, sort_keys=True))
            return
        cli.out.print(f"Balance {b.address} ({unit(b)}), before and after:", markup=False)
        for line in change_lines(before, after, b.decimals, repo_name, login):
            cli.out.print(line, markup=False)
        cli._said(names)
        if not ixs:
            cli.out.print("Nothing changes: the chain already has these settings.", markup=False)
            return
        if dry:
            cli.out.print(f"Nothing was sent. Wallet {b.balance.authority} must sign {len(ixs)} instruction(s): run this again with --keypair FILE "
                          "(or KNOS_WALLET_KEY), or give a multisig the instructions: --dry-run --json.", markup=False)
            for ix in ixs:
                cli.out.print(f"  {'SetBalanceX' if ix.data[0] == 13 else 'SetBalance'}: program {ix.program_id}, data {bytes(ix.data).hex()}", markup=False)
            return
        from .settle.v2 import relay
        if any(ix.data[0] == 13 for ix in ixs) and relay.version(ledger, wallet) == 0:
            raise cli.Stop("The program at the public address is not knos_pay 2.1 yet, and the daily limit, the total limit, the repositories and the "
                           "workflows commit are 2.1's (SetBalanceX). Nothing was sent. web/upgrades.json says when 2.1 is live.",
                           "The cap and the spenders can be set today: run this again with only --cap and --spender.")
        sig = cli._send(ledger, ixs, wallet)
        cli.out.print("Set. Every funding from this Balance is held to it from now on; what was already spent still counts.", markup=False)
        cli.out.print(cli._tx(sig), markup=False)

    # ---- procurement files: no chain is read, and nothing is sent ---------------------------------------------------------
    file_arg = typer.Argument(..., help=f"the file, under {PROCUREMENT}/ in your repository")

    def load(cli, path: Path, what: str, problems) -> dict:
        try:
            doc = read_yaml(path.read_text(encoding="utf-8"))
        except OSError:
            raise cli.Stop(f"There is no {what} at {path}.") from None
        except Unread as why:
            raise cli.Stop(f"{path}: {why}") from None
        bad = problems(doc)
        if bad:
            raise cli.Stop(f"{path} is not a sound {what}:", "\n".join(f"  {b}" for b in bad))
        return doc

    def bars(cli, state: dict, label: str) -> None:
        cli.out.print(f"  {label:<7}limit {money(state['limit'])}: committed {money(state['committed'])}, spent {money(state['spent'])}, "
                      f"held {money(state['held'])}, left {money(state['left'])}", markup=False)

    @budget_app.command("card")
    def card_(file: Path = file_arg) -> None:
        """Is this rate card sound? Every outcome needs a name, a price, a unit and the terms template it cites by hash; the hash must be the one terms/ publishes. Exit status 1 with one sentence per problem."""
        from . import cli
        card = load(cli, file, "rate card", lambda d: card_problems(d, published_terms()))
        cli.out.print(f"Rate card {card['name']}, valid {card['valid_from']} to {card['valid_to']}:", markup=False)
        for r in card["outcomes"]:
            cli.out.print(f"  {r['name']:<20}{money(units_of(r['price']) or 0)} test USDC per {r['unit']}; terms {r['terms']} ({r['terms_hash'][:12]})", markup=False)

    @budget_app.command("envelope")
    def envelope_(file: Path = file_arg, as_json: bool = typer.Option(False, "--json", help="print the five amounts as JSON, in millionths"),
                  fund: str = typer.Option(None, "--fund", help="an amount one task would be funded with, like 500: show the envelope before and after")) -> None:
        """An envelope's limit and what is committed, spent, held and left. Left is always worked out: the limit less the other three. With --fund, the envelope before and after one task of that amount, fee on top; over the limit it is refused with the amount over, exit status 1. Nothing is sent or written."""
        from . import cli
        env = load(cli, file, "budget envelope", envelope_problems)
        if fund is not None:
            amount = cli._units(fund, 6)
            fee, was = fees.NEW.order(amount), fees.OLD.order(amount)
            got = fit(env, amount + fee)
            if as_json:
                typer.echo(json.dumps({"name": env["name"], **got}, sort_keys=True))
            else:
                cli.out.print(f"Envelope {env['name']}: one task of {money(amount)}, fee {money(fee)} on top"
                              + ("." if fee == was else f" ({money(was)} until knos_pay {fees.NEW.build} is live: `knos status` says which build runs)."), markup=False)
                bars(cli, got["before"], "before")
                bars(cli, got["after"], "after")
                cli.out.print(got["sentence"], markup=False)
            if not got["ok"]:
                raise typer.Exit(1)
            return
        if as_json:
            typer.echo(json.dumps({"name": env["name"], **envelope_state(env)}, sort_keys=True))
            return
        cli.out.print(f"Envelope {env['name']} ({env['cost_centre']}), owner @{env['owner']}, {env['period_from']} to {env['period_to']}, test USDC:", markup=False)
        bars(cli, envelope_state(env), "now")

    @budget_app.command("offer")
    def offer_(file: Path = file_arg, write: bool = typer.Option(False, "--write", help="add what the offer commits to the envelope's file")) -> None:
        """Is this standing offer sound, and does it fit its envelope? Reads the rate card and the envelope it names from beside it, shows the envelope before and after, and refuses over the limit with the amount it is over by. Then the comment that funds each supplier for one period on devnet. Nothing is sent. Exit status 1 when refused."""
        from . import cli
        root = file.resolve().parent.parent
        offer = load(cli, file, "standing offer", offer_problems)
        card = load(cli, root / FILES["rate-card"] / f"{offer['rate_card']}.yaml", "rate card", lambda d: card_problems(d, published_terms()))
        load(cli, file, "standing offer", lambda d: offer_problems(d, card))
        where = root / FILES["budget-envelope"] / f"{offer['envelope']}.yaml"
        env, c = load(cli, where, "budget envelope", envelope_problems), commitment(offer)
        got = fit(env, c["leaves"])
        cli.out.print(f"Offer {offer['name']}: {money(c['cap'])} a {offer['period']} for {c['suppliers']} supplier(s), {c['periods']} period(s); "
                      f"fees {money(c['leaves'] - c['value'])} on top.", markup=False)
        cli.out.print(f"Envelope {env['name']}:", markup=False)
        bars(cli, got["before"], "before")
        bars(cli, got["after"], "after")
        cli.out.print(got["sentence"], markup=False)
        if not got["ok"]:
            raise typer.Exit(1)
        cli.out.print(f"An approval is asked for {money(c['value'])}: knos approve status --offer {file}", markup=False)
        row = outcome_of(card, offer["outcome"]) or {}
        for who in ([] if offer["suppliers"] == "anyone" else offer["suppliers"]):
            cli.out.print("  " + offer_comment(offer_parts(offer, card, who, template_parts(row["terms"]))), markup=False)
        if offer["suppliers"] != "anyone" and offer["period"] == "month":
            cli.out.print("The funding workflow holds each comment to .knos/policy.yml. Under `offers:` there, add:", markup=False)
            cli.out.print(policy_lines(offer, card, template_parts(row["terms"])).rstrip("\n"), markup=False)
        if offer["suppliers"] == "anyone":
            cli.out.print("  Devnet funds one named supplier per comment: an offer to anyone is recorded here and funded task by task.", markup=False)
        if write:
            env["committed"] = commands.amount(got["after"]["committed"])
            env.pop("left", None)
            where.write_text(dump_yaml(env), encoding="utf-8", newline="")
            cli.out.print(f"Wrote {where}: committed is now {money(got['after']['committed'])}. Commit it with the offer.", markup=False)
