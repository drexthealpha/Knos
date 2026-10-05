"""The budget owner's controls: what a Balance may spend, who may spend it, who may change that, and whether one
funding would pass, all read from the chain.

    knos budget show  --owner <org>
    knos budget set   --owner <org> [--cap N] [--per-day N] [--total N] [--repo owner/name ...] [--spender login ...] [--pin-workflows]
    knos budget check --owner <org> --repo owner/name --amount N --by <login>
    knos budget who   --owner <org>

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

from dataclasses import dataclass
from pathlib import Path

from solders.pubkey import Pubkey

from .settle.v2 import pay

RULES = {"owner": 92, "spender": 92, "cap": 93, "repository": 92, "workflows": 86, "day": 100, "total": 100, "funds": 94, "amount": 81, "ok": 0}
MAX_AMOUNT = 100_000_000_000        # millionths of a whole unit: 100,000 an order on devnet (lib.rs MAX_AMOUNT)
FEE_TABLE = (5, 20, 1_000, 5_000, 50_000)      # the amounts the price book shows the effective fee for
DAY = 86_400


def money(units: int, decimals: int = 6) -> str:
    """An amount as people write it: 400000 -> "0.40", 5000000000 -> "5,000.00"; at least two decimals, no zeros past them."""
    whole, frac = divmod(int(units), 10 ** decimals)
    return f"{whole:,}." + str(frac).rjust(decimals, "0").rstrip("0").ljust(2, "0")


def percent(fee: int, amount: int) -> str:
    """The fee as a share of the amount, in hundredths of a percent, rounded half up: (400000, 5000000) -> "8.00"."""
    h = (fee * 10_000 + amount // 2) // amount if amount > 0 else 0
    return f"{h // 100}.{h % 100:02d}"


def fee_table(bps: int = pay.FEE_BPS, decimals: int = 6) -> list[dict]:
    """The effective settle fee at the price book's amounts: [{amount, fee, total, effective_pct}], in the mint's units."""
    unit = 10 ** decimals
    return [{"amount": a * unit, "fee": (f := pay.order_fee(a * unit, bps, decimals)), "total": a * unit + f, "effective_pct": percent(f, a * unit)}
            for a in FEE_TABLE]


@dataclass(frozen=True)
class Decision:
    ok: bool
    rule: str               # a key of RULES: the first rule that refuses, or "ok"
    code: int               # the program's error for it (0: none)
    sentence: str           # what happens and what to do, in plain words
    fee: int                # what the funder pays on top, in the mint's units
    total: int              # amount + fee: what leaves the Balance
    effective_pct: str      # the fee as a percentage of the amount, like "2.50"
    bps: int                # the first tier's rate in use: the standard one or the owner's Plan

    def as_json(self) -> dict:
        """The keys web/controls_data.js answers with."""
        return {"ok": self.ok, "rule": self.rule, "code": self.code, "sentence": self.sentence, "fee": self.fee, "total": self.total,
                "effectivePct": self.effective_pct, "bps": self.bps}


def spent_today(x: pay.BalanceX | None, now: int) -> int:
    """What the side account counts for the UTC day of `now`: its counter, or nothing when the counter is of another day."""
    return x.day_spent if x is not None and x.day == now // DAY else 0


def decide(balance: pay.Balance, x: pay.BalanceX | None, repo_id: int, amount: int, by_id: int, now: int, *, plan: pay.Plan | None = None,
           holds: int | None = None, repo_owner_id: int | None = None, wf_sha: str | None = None, decimals: int = 6) -> Decision:
    """Whether a comment by GitHub id `by_id` in repository `repo_id` may fund an order of `amount` from this Balance at
    `now`, and which rule decides: the program's checks in the program's order (the module's table). `x` is the side
    account (None: the Balance has none), `plan` the owner's Plan, `holds` what the Balance holds, `repo_owner_id` the
    id of the repository's owner and `wf_sha` the commit of the workflows the run would use; a rule whose fact is
    not given (None) is not judged."""
    bps = pay.plan_bps(plan, now)
    fee = pay.order_fee(amount, bps, decimals)
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


def budgets(ledger, owner_id: int) -> list[Budget]:
    """Every Balance set aside for one GitHub owner's repositories (each wallet's, and on devnet the faucet's)."""
    from .settle.v2 import relay
    now, plan = int(ledger.now()), pay.read_plan(ledger.account(pay.plan_pda(owner_id)))
    out = []
    for address, b, holds in relay.balances_for(ledger, owner_id):
        mint = ledger.account(b.mint)
        out.append(Budget(address, b, pay.read_balx(ledger.account(pay.balx_pda(address))) if b.has_x else None, plan, holds,
                          mint[44] if mint and len(mint) >= 82 else 6, now))
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
                  decimals=b.decimals)


# ---- words --------------------------------------------------------------------------------------------------------------
def _when(t: int) -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))


def _named(ids, name) -> str:
    return ", ".join(f"{n} (id {i})" if (n := name(i)) else f"id {i}" for i in ids)


def show_lines(b: Budget, repo_name=lambda i: "", login=lambda i: "", unit: str = "test USDC") -> list[str]:
    """`knos budget show` for one Balance. `repo_name` and `login`: GitHub's names for ids ("" when unknown)."""
    m, bal, x = (lambda u: money(u, b.decimals)), b.balance, b.x
    today, bps = spent_today(x, b.now), pay.plan_bps(b.plan, b.now)
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
        out.append(f"  fee                  a Plan: {bps / 100:g}% of the first 1,000 until {_when(b.plan.expires)}, then the standard 2.5%")
    else:
        out.append(f"  fee                  standard: {bps / 100:g}% of the first 1,000, 1% to 50,000, 0.5% above, at least 0.40"
                   + (f" (a Plan ended {_when(b.plan.expires)})" if b.plan is not None else " (no Plan)"))
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


# ---- the commands -------------------------------------------------------------------------------------------------------
def register(app, help_lines: list | None = None) -> None:
    """`knos budget show | set | check | who`, on the main app. `help_lines`: cli._HELP, which gets the group's line."""
    import json
    import os

    import typer

    budget_app = typer.Typer(add_completion=False, no_args_is_help=True,
                             help="A Balance's limits: see them, set them, ask whether a funding would pass, and see who has authority.")
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
