"""Carries one GitHub-signed token to the second deployment: has knos-oidc verify it, and sends the knos-pay
instruction its audience asks for. Anyone can run this and pay the fees; the money goes where the token and the chain
say, never where the relayer says. A workflow that has a relay key calls `submit` itself (knos.flow); Knos's public
worker calls it for every token a workflow posts instead (knos.proof.ghrelay).

    withdraw(ledger, payer, request)   a passkey wallet's withdrawal request (no token): see `withdraw`
    passkey_fund(ledger, payer, request, repo_id=None, issue=None)   the comment `/knos passkey-fund <base64url>` (no token):
                         a passkey wallet funds a work order and this relay pays the order's rent and the fee: see `passkey_fund`
    submit(ledger, payer, jwt, terms=None, jwks=None, now=None)
      knos2:fund:...     {"ok": True, "kind": "fund", "sigs", "job", "repo_id", "issue", "amount", "mode", "faucet", "balance", "deadline"}
      knos2:pay:...      {"ok": True, "kind": "pay", "sigs", "repo_id", "issue", "payee_id", "head",
                          "paid": [{"job", "amount", "fee", "mint", "to": wallet or None, "held_until": time or None}]}
      knos2:bind:...     {"ok": True, "kind": "bind", "sigs", "user_id", "wallet", "settled": [{"job", "amount", "fee", "mint"}]}
      knos3:fund:...     {"ok": True, "kind": "fund", "sigs", "order", "repo_id", "issue", "seq", "amount", "fee", "mode", "faucet", "balance", "deadline"}
                         a PRIVATE order adds "private": True: its "issue" is 0 and its "repo_id" is its judge repository's, where
                         the comment was; `terms` is then its scope and its terms hash (`private_terms`), not a terms JSON
      knos3:pay:...      {"ok": True, "kind": "pay", "sigs", "order", "repo_id", "issue", "mint", "head", "pr",
                          "paid": [{"payee_id", "amount", "to": wallet or None, "held_until": time or None}]}   (work orders, 2.1)
                         each row also has "id" (the same as "payee_id"); a standing order adds "left", one with a
                         holdback "held_back" and "warranty_until". Judges: the order's own repository, a neutral run
                         of attest.yml, the order's judge repository.
      knos3:auto:...     as knos3:pay, with "auto": True: an AUTO order's unmerged pull request, paid on its black-box suite alone
                         (an order with a quorum, before its last judge: "paid": [], "quorum": {"have", "of"})
      knos3:rule:...     {"ok": True, "kind": "rule", "sigs", "order", "repo_id", "issue", "mint", "paid": [as for knos3:pay]}   (the arbiter's ruling)
      knos3:take:...     {"ok": True, "kind": "take", "sigs", "order", "repo_id", "issue", "taker_id", "days", "reserved_until"}
      knos3:cancel:...   {"ok": True, "kind": "cancel", "sigs", "order", "repo_id", "issue", "cancel_at", "deadline"}
      knos3:revert:...   {"ok": True, "kind": "revert", "sigs", "order", "head", "repo_id", "issue", "mint", "amount"}   (what went back to the funder)
      knos3:bind:...     {"ok": True, "kind": "bind", "sigs", "user_id" (the organisation's id), "wallet", "org": True, "by", "settled": [...]}
      knosm:eval:...     {"ok": True, "kind": "eval", "sigs", "buyer_id", "seller_id", "order", "artifact", "milestone", "accepted", "rate", "fee", "month"}
                         (knos_meter Record: one billable evaluation, paid from the buyer's credits)
      knosm:batch:...    {"ok": True, "kind": "batch", "sigs", "buyer_id", "seller_id", "month", "seq", "count", "accepted", "value", "root", "fee", "chain"}
      knosm:claim:...    the same with "kind": "claim" (knos_meter RecordBatch, the buyer's count; ClaimBatch, the seller's own, no fee)
      gate:...           {"ok": True, "kind": "gate", "sigs", "program", "hash", "commit", "run_id", "record"}: upgrade_gate's record
                         that GitHub's runner built the executable with this hash for this program (program.yml's gate job)
      knos-oidc:ikey:... {"ok": True, "kind": "key", "sigs", "key", "added", "refreshed", "issuer"}: a key of any RS256 issuer,
                         named by its URL, which comes as `terms` (the `knos-issuer:` line of the token's comment)
      knos-oidc:key:...  {"ok": True, "kind": "key", "sigs", "key", "added": bool, "refreshed": bool, "first": {...}}
                         carried to both deployments. `key`, `added` (RegisterKey: the key now waits a day and the
                         guardian) and `refreshed` (Refresh: it lives 30 days from now) are the second verifier's;
                         `first` is what knos.settle.relay answered. When only the first deployment took the token,
                         "why" says what the second refused it for.
      refused            {"ok": False, "kind", "why"}; "retry": True when the same token may succeed later ("wait":
                         seconds, when that is known), and "transient": True when the cluster, not the token, was why;
                         with it "answered": True when the program itself refused in a way a twin run can cause
                         (67, 69, 84): tried a few passes, never for the token's whole life
      done before        the same result with "already": True and no fee spent, when the chain already shows what the
                         token asks for (another relayer carried it)

A token of an issuer that is not GitHub or GitLab (its `iss` is another URL) is verified under a key the verifier
holds for that URL (`other_keys`): a registered issuer's, or a PRIVATE one some wallet registered itself. The chain is
the key set: nothing is fetched from a URL a token names. `verify_only` carries any such token. The escrow takes one
in a single case: a pay token under a private key pays a PRIVATE order funded from the Balance that the key's own
registrant opened (never a ruling); everything else of the escrow's is GitHub's alone, and is refused here for nothing.

`terms` is the terms JSON whose hash a fund token's audience carries. `jwks` maps an issuer id (or, for any other
issuer, its URL) to its JWKS document (fetched from the issuer and kept ten minutes when not given). `now` is the chain's time (read from it when not given).

Before a fee is spent, `precheck` asks everything the two programs will ask, with reads alone: the claims, the
audience, the workflow, the key that signed, the job, the Balance, the faucet's rate, and GitHub's signature itself
(the same arithmetic as on chain, done here). Anyone can have GitHub sign any audience from a repository of their own
and post it where a relayer looks, so a relayer that paid first and asked later could be made to pay for nothing.

Round trips. On a 2.1 cluster (`version` answers 1) with a ledger that sends v1 transactions (4,096 bytes), a GitHub
token of the usual size (the harness's are 1,770 to 1,910 bytes) takes two transactions and two waits, whatever it
asks for:

    1  Write, Step(8)             the whole token, and the first half of the RSA verification
    2  Step(8), <escrow>, Close   the second half, what the audience asks for, and the token account closed again

A token longer than about 3,700 bytes has its head written first, in Writes side by side. Where v1 transactions cannot
be used (the deployed 2.0 escrow, a ledger without them, or a cluster that refused one: the relay then falls back by
itself and stays there) the same token takes four legacy transactions and three waits:

    1  Write | Write              the head of the token, side by side (one Write for a token up to 1,756 bytes)
    2  Write, Step(8)             the rest of it, and the first half of the RSA verification
    3  Step(8), <escrow>, Close   the second half, what the audience asks for, and the token account closed again

The first deployment's relay sends each chunk, each step, the escrow instruction and the close in a transaction of
its own and waits for each: seven and seven for the same token. The last Step and the escrow share a transaction when
both fit in its bytes and in 1,400,000 compute units; on the legacy path a fund with the longest terms (600 bytes)
does not, and takes two more. tests/test_relay2.py counts every path's transactions, waits and compute units, and
prints them with -s.

`ledger` needs send(ixs, payer) -> signature, account(address) -> bytes | None, program_accounts(program, size,
{offset: bytes}) -> [(address, data)] and now(); it is used better when it also has send_all, infos, recent, logs, simulate
(without it the cluster is taken for 2.0) and `takes_v1` with send(..., v1=True) (knos.chain.Ledger has them all).

The package, by responsibility (each module imports only the ones above it):

    pins        workflow pins, compute units, the verifier's error words, refusals and how a failure is read
    build       which knos-pay the cluster runs (`version`, `forget`)
    tokens      a token's claims, the key that signed it, its lane
    reads       reads of the chain: jobs, Balances, keys, credits, orders, logs
    plans       what a plan is made of (`Group`, `_Plan`, `_Ask`) and the bounds of a funding
    jobs        plans for jobs (fund, pay, bind) and for the verifier's keys
    workorders  plans for work orders (fund, pay, take, cancel, revert, an organisation's wallet)
    metering    plans for knos_meter and the upgrade gate
    kinds       the audiences carried (`KINDS`), a token opened against its kind, `precheck`
    send        the transactions a plan becomes, `submit`, `verify_only`
    upkeep      a worker's pass without a token (`sweep`, refunds, releases, markers closed)
    wallets     passkey wallets (`withdraw`, `passkey_fund`)

Every name of every module is a name of this package too, as when the relay was one file: `knos.settle.v2.relay.X`.
Setting one here (a test's monkeypatch, a script's override of `ATTESTERS`) sets it in every module that holds it,
so each function sees what it saw when the relay was one module.
"""
from __future__ import annotations

import base64 as base64
import hashlib as hashlib
import json as json
import re as re
import sys
import time as time
import types
import urllib.request  # noqa: F401 - `relay.urllib`, as in the one-module relay
import weakref as weakref
from dataclasses import dataclass as dataclass, field as field
from datetime import datetime as datetime, timezone as timezone
from typing import Callable as Callable

from solders.instruction import AccountMeta as AccountMeta, Instruction as Instruction
from solders.keypair import Keypair as Keypair
from solders.pubkey import Pubkey as Pubkey

from .... import chain as chain, fees as fees, receipt as receipt
from ... import oidc as first_oidc  # noqa: F401 - a name of the one-module relay
from ... import relay as first  # noqa: F401 - a name of the one-module relay
from ...relay import claims_of as claims_of, header_of as header_of
from .. import gate as gate, live as live, meter as meter, oidc as oidc, order_auto as order_auto, pay as pay, passkey as passkey
from .. import passkey_fund as pkfund  # noqa: F401 - a name of the one-module relay

from . import pins
from . import build
from . import tokens
from . import reads
from . import plans
from . import jobs
from . import workorders
from . import metering
from . import kinds
from . import send
from . import upkeep
from . import wallets
from .pins import (ATTESTERS as ATTESTERS, CLAIM_REF as CLAIM_REF, CLAIM_SHAS as CLAIM_SHAS, GENESIS as GENESIS,
    JWKS_TTL as JWKS_TTL, ORG_CLAIM_SHAS as ORG_CLAIM_SHAS, REFRESH_AFTER as REFRESH_AFTER, ROOM as ROOM,
    ROOM_V1 as ROOM_V1, ROTATE_REF as ROTATE_REF, ROTATE_SHAS as ROTATE_SHAS, ROTATE_SHAS2 as ROTATE_SHAS2,
    _BROKE as _BROKE, _CU as _CU, _DIGEST_INFO as _DIGEST_INFO, _HEX40 as _HEX40, _HEX64 as _HEX64,
    _LAST_STEP as _LAST_STEP, _SPARE as _SPARE, _Stop as _Stop, _T_ID as _T_ID, _T_PAYER as _T_PAYER, _U64 as _U64,
    _VERIFIER as _VERIFIER, _code as _code, _failed as _failed, _no as _no, _out_of_compute as _out_of_compute,
    answered as answered, transient as transient, why_failed as why_failed)
from .build import (_TIERED as _TIERED, _UPGRADEABLE as _UPGRADEABLE, _VERSION as _VERSION,
    _VERSION_LINE as _VERSION_LINE, _built as _built, _drop as _drop, _keep as _keep, _where as _where, forget as forget,
    version as version)
from .tokens import (ORDER_LANES as ORDER_LANES, _KEPT as _KEPT, _Token as _Token, _address as _address, _exp as _exp, _ints as _ints,
    _jwks as _jwks, _units as _units, _when as _when, _workflow as _workflow, lane as lane, other_keys as other_keys,
    signed as signed)
from .reads import (_amount as _amount, _batch_taken as _batch_taken, _data as _data, _funded_by as _funded_by,
    _last as _last, _read as _read, _said_in as _said_in, _said_since as _said_since, balances_for as balances_for,
    credits_for as credits_for, held_for as held_for, jobs_for as jobs_for, keys as keys,
    open_repositories as open_repositories, orders as orders)
from .plans import (Group as Group, _Ask as _Ask, _Plan as _Plan, _bounds as _bounds, _decimals as _decimals,
    _github_token as _github_token, _limits as _limits)
from .jobs import (_attests as _attests, _fetch as _fetch, _fund_run as _fund_run, _issuer_keys as _issuer_keys,
    _paid_before as _paid_before, _payout as _payout, _plan_bind as _plan_bind, _plan_fund as _plan_fund,
    _plan_issuer_key as _plan_issuer_key, _plan_key as _plan_key, _plan_pay as _plan_pay)
from .workorders import (_ASKS as _ASKS, _command as _command, _judge as _judge, _number as _number,
    _options as _options, _order_paid as _order_paid, _order_token as _order_token, _org_made as _org_made,
    _own_key as _own_key, _payees as _payees, _plan_cancel as _plan_cancel, _plan_order_fund as _plan_order_fund,
    _plan_order_pay as _plan_order_pay, _plan_org_bind as _plan_org_bind, _plan_revert as _plan_revert,
    _plan_take as _plan_take, _fee_account as _fee_account, _routed as _routed, _run as _run, _shares as _shares, _tip_accounts as _tip_accounts,
    carries_terms as carries_terms, private_terms as private_terms)
from .metering import (_plan_batch as _plan_batch, _plan_eval as _plan_eval, _plan_gate as _plan_gate)
from .kinds import (KINDS as KINDS, Kind as Kind, _handler as _handler, _handler_of as _handler_of, _open as _open,
    _open_other as _open_other, _plan as _plan, _signer as _signer, kind_of as kind_of, precheck as precheck)
from .send import (_carry as _carry, _first as _first, _fits as _fits, _land as _land, _round as _round,
    _send as _send, _someone_else as _someone_else, _steps as _steps, _verification as _verification,
    _write_ix as _write_ix, submit as submit, verify_only as verify_only)
from .upkeep import (_each as _each, close_markers as close_markers, close_marks as close_marks,
    refund_due as refund_due, refund_orders_due as refund_orders_due, register_missing as register_missing,
    release_orders_due as release_orders_due, settle_held as settle_held, settle_orders_held as settle_orders_held,
    sweep as sweep)
from .wallets import (_rent as _rent, passkey_fund as passkey_fund, passkey_fund_reply as passkey_fund_reply,
    withdraw as withdraw)

_PARTS = (pins, build, tokens, reads, plans, jobs, workorders, metering, kinds, send, upkeep, wallets)


class _Package(types.ModuleType):
    """This package as a module whose names reach its parts: setting or deleting a name here does the same in every part
    that holds it, so a part's functions read what the one-module relay's would have read."""

    def __setattr__(self, name: str, value: object) -> None:
        for part in _PARTS:
            if name in vars(part):
                vars(part)[name] = value
        super().__setattr__(name, value)

    def __delattr__(self, name: str) -> None:
        for part in _PARTS:
            vars(part).pop(name, None)
        super().__delattr__(name)


sys.modules[__name__].__class__ = _Package
