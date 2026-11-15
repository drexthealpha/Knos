"""What every plan is made of: a group of instructions (`Group`), the plan itself (`_Plan`), what a planner is asked
(`_Ask`), and the bounds a funding must meet."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from .. import oidc, pay

from .pins import _no
from .tokens import _Token, _ints, _units


# -- what each audience asks of the escrow, decided with reads alone ----------------------------------------------------
Group = tuple[list[Instruction], int]       # instructions that go in one transaction together, and their compute units


@dataclass
class _Plan:
    t: _Token
    groups: list[Group]                     # the escrow's instructions, in order
    done: Callable[[list[str]], dict]       # the result, once they have all landed
    token: bool = True                      # whether they need the token verified (and its account closed behind them)
    alone: bool = False                     # whether the transactions after the one with the last Step depend on nothing but it
    lead: bool = False                      # whether the first group must land before the others whatever else is so (a Bind, then the payments it frees)
    closes: bool = False                    # whether a group already closes the token account
    have: bytes | None = None               # the token account as it stands
    v1: bool = False                        # whether its transactions go out as v1 ones (4,096 bytes): a 2.1 cluster, and a ledger that sends them
    register: list[Instruction] = field(default_factory=list)   # a signing key the chain needs first (a genesis key it has not seen)
    soon: str | None = None                 # what to say when the program answers 83 to a plan every read allowed: tried again on the next pass


def _github_token(t: _Token, now: int, private: bool = False) -> None:
    """What knos-pay asks of every token before it reads the audience (gh.rs): GitHub's, a GitHub-hosted runner, and
    times that GitHub's clock wrote. `private`: the kind also takes a token under a key some wallet registered itself,
    where its planner finds that wallet to be the one whose money it pays out (`_own_key`)."""
    if t.issuer != oidc.GITHUB and not (private and any(k.private for _a, k in t.held)):
        raise _no(t.kind, "the escrow takes GitHub's tokens only" + ("" if t.url is None else
                          ": a token of another issuer is verified for other programs to read (post it as `knos-verify:`), and a pay token under a "
                          "key a wallet registered itself pays a private order of that wallet's own balance"))
    if t.c.get("runner_environment") != "github-hosted":
        raise _no(t.kind, "not from a GitHub-hosted runner")
    try:
        iat, exp = _ints(t.c, "iat", "exp")
    except (KeyError, ValueError, TypeError):
        raise _no(t.kind, "malformed audience or claims") from None
    if iat > now + pay.TOKEN_AHEAD or exp - iat > pay.TOKEN_LIFE:
        raise _no(t.kind, "the token's times are not GitHub's: it is dated ahead of the chain's clock, or lives longer than an hour")


def _decimals(mint: bytes | None) -> int:
    """A mint's decimals (either token program); 6 when the mint could not be read."""
    return mint[44] if mint and len(mint) >= 82 else 6


def _bounds(kind: str, amount: int, decimals: int, least: int = pay.MIN_AMOUNT, what: str = "a bounty") -> None:
    """The escrow's limits are whole units of the mint, whatever its decimals."""
    low, high, one = pay.units(least, decimals), pay.units(pay.MAX_AMOUNT, decimals), 10 ** decimals
    if not low <= amount <= high:
        raise _no(kind, f"{what} is from {low / one:,.2f} to {high / one:,.2f}; this token asks for {amount / one:,.2f}")


def _limits(kind: str, x: pay.BalanceX | None, amount: int, repo_id: int, wf_sha: str, now: int) -> None:
    """What a Balance's side account asks of a funding (2.1): its repositories, its workflows commit, and what it may
    spend in a day and in all."""
    if x is None:
        return
    if x.repos and repo_id not in x.repos:
        raise _no(kind, "that balance lists the repositories that may spend it, and this one is not among them")
    if x.wf_sha and x.wf_sha != wf_sha:
        raise _no(kind, "that balance is spent only by the workflows at the commit its wallet pinned, and this run used another")
    today = x.day_spent if x.day == now // 86_400 else 0
    if (x.day_limit and today + amount > x.day_limit) or (x.total_limit and x.total_spent + amount > x.total_limit):
        raise _no(kind, f"{pay.ERRORS[100]}: {_units(today)} of {_units(x.day_limit)} spent today, {_units(x.total_spent)} of {_units(x.total_limit)} in all "
                        "(a limit of 0.00 is no limit)")


# -- work orders (2.1): knos3:fund, knos3:pay -----------------------------------------------------------------------------
@dataclass
class _Ask:
    """One token, and what a handler plans it with."""
    ledger: Any                 # what `ledger` is in this package: see its docstring
    payer: Keypair
    me: Pubkey
    t: _Token
    now: int
    v: int                      # the escrow's version on this cluster
    terms: bytes | None = None
    jwks: dict | None = None
