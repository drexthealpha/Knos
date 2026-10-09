"""The enforcement matrix: every route that can set money aside or move it, against every restriction a buyer can
state, and for each pair exactly one answer to "what stops it".

    python -m knos.enforce --write      docs/ENFORCEMENT.md, from the table below
    python -m knos.enforce --check      ends 1 when that file is not what the table says
    python -m knos.enforce --json       the same table for a page: {routes, restrictions, cells[route][restriction]}
    knos controls matrix [--json]       prints it

A cell is one of four classes:

    program     an instruction of a deployed program refuses it. The cell names the instruction and the check.
    workflow    a job of the pinned workflows refuses it before GitHub is asked to sign. The cell names the job and
                the function. It holds for whoever funds through that workflow, and for nobody else: a wallet that
                calls the program, or a workflow file changed on the default branch, is not asked.
    advisory    a file or a command says so, and nothing stops it.
    outside     intentionally outside the policy boundary. The cell says why.

Every cell that is not `outside` names a test that tries to get round it by another route and asserts what really
happens (tests/test_enforcement.py holds the table to that, and to the source it names). Nothing here claims that
the program enforces what only a workflow does.

Standard library only: the table is data, and the signing path never imports this module.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import NamedTuple

CLASSES = ("program", "workflow", "advisory", "outside")
DOC = "docs/ENFORCEMENT.md"


class Cell(NamedTuple):
    cls: str        # one of CLASSES
    by: str         # program: the instruction and the check; workflow: the job and the function; advisory: the file or command; outside: why
    test: str       # tests/<file>.py::<function>; "" only for `outside`


ROUTES: tuple[tuple[str, str, str], ...] = (
    ("wallet", "Wallet funding", "A wallet calls knos_pay itself: FundOrderWallet (15), or FundWallet (4) for a job. Its own money."),
    ("vault", "Enterprise vault, by vote", "An organisation's money in a Squads v4 vault: a requester's key proposes, the threshold of voting keys "
     "approves, an Execute key executes after the time lock, and only then does the vault sign FundOrderWallet (15), TopUp (23), "
     "OpenBalance (0) or SetBalance (1). `knos boundary plan` writes the vault's settings from the approval policy."),
    ("vault_balance", "Enterprise vault's Balance", "A knos_pay Balance the vault opened by vote: `/knos fund` spends it as Funding by comment "
     "does, and its cap, limits, spenders and workflow pin change only by the vault's vote."),
    ("allowance", "A Squads allowance", "Squads v4 SpendingLimitUse: a key the config authority listed moves up to an amount a period to "
     "listed destinations, with no vote. `knos boundary plan` adds none unless the boundary file asks."),
    ("comment", "Funding by comment", "`/knos fund <amount>`: fund.yml job `command` has GitHub sign, and FundOrderBalance (16) spends a Balance."),
    ("tip", "A tip by comment", "`/knos tip <amount>` on a merged pull request: the same job; FundBalance (3) opens a job that lasts one day."),
    ("offer", "A standing offer", "`/knos offer @vendor rate R budget B`: the same job; an order that pays one rate each time the agreed checks pass at merge."),
    ("topup", "A top-up", "TopUp (23) adds to an open order. `/knos raise` only says how: a comment cannot sign for a wallet."),
    ("private", "A private order", "`/knos fund` in a private repository, answered by its attestor's run of fund.yml job `command`."),
    ("balance", "A Balance", "OpenBalance (0), SetBalance (1), SetBalanceX (13), Withdraw (2): money a wallet sets aside for one GitHub owner."),
    ("netted", "A netted release", "`knos net`: small outcomes accumulate in a book both sides keep; one order pays their net."),
    ("advance", "An advance", "Assign (24): a payee names the wallet that receives an order's payment, for money a third party pays now."),
    ("passkey", "The passkey relay", "`/knos passkey-fund` and `knos-withdraw:`: a relay sends and pays for what a passkey signed (knos_passkey)."),
    ("direct", "A direct call by anyone", "Any instruction, sent by any wallet: a relayer carrying a token, RefundOrder (22), Release (18)."),
)

RESTRICTIONS: tuple[tuple[str, str], ...] = (
    ("who", "Who may fund"),
    ("order_limit", "Limit per order"),
    ("period_limit", "Limit per period"),
    ("approvers", "Approver count"),
    ("rate_card", "Rate card"),
    ("envelope", "Envelope or budget"),
    ("suppliers", "Supplier allow-list"),
    ("terms", "Terms fixed at funding"),
    ("deadline", "Deadline"),
)

_OC, _CT, _P2, _E = "tests/test_order_chain.py::", "tests/test_controls.py::", "tests/test_pay2_chain.py::", "tests/test_enforcement.py::"
_B = "tests/test_boundary.py::"
_SQ_VOTE = _B + "test_squads_refuses_a_funding_from_the_vault_without_the_threshold"
_SQ_HOLDS = _B + "test_the_vault_cannot_fund_past_what_it_holds"
_SQ_ALLOW = _B + "test_squads_refuses_an_allowance_over_its_limit_to_another_destination_or_by_another_key"
_SQ_VBAL = _B + "test_a_balance_the_vault_opened_is_changed_only_by_the_vault"
_LIMITS = _CT + "test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first"
_DEADLINE = _OC + "test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before"
_WALLET = _OC + "test_what_a_funding_wallet_cannot_do"
_PLAIN = _E + "test_a_plain_fund_cannot_go_round_the_approval_a_standing_offer_needs"
_NO_CARD = _E + "test_a_plain_order_is_held_to_no_rate_card_and_no_envelope"
_PIN = _E + "test_a_token_from_a_changed_workflow_is_stopped_only_by_the_balances_own_pin"
_TOPUP = _E + "test_a_top_up_goes_past_the_balances_cap_and_limits_and_only_its_wallet_signs_it"
_NET_CLI = "tests/test_netting.py::test_the_command_line_opens_adds_disputes_closes_and_states"
_NET_CAP = "tests/test_netting.py::test_an_outcome_is_added_once_in_any_period_and_never_past_the_cap"
_NET_ONE = "tests/test_netting.py::test_a_thousand_outcomes_settle_as_one_release_on_the_programs_as_they_are"
_PAYEES = "tests/test_flow_orders.py::test_a_policy_that_names_payees_is_enforced_and_every_address_is_screened_before_a_payout"
_OFFER = ("tests/test_flow_wire17.py::test_a_standing_offer_funds_only_when_the_buyers_procurement_files_approve_it_and_with_none_"
          "nothing_changes")

_NO_FILE = "No file of a repository is read on this route: the program sees accounts and signatures, never `.knos/`."
_OWN = "The wallet's signature is the approval. When the wallet is a multisig its threshold is the multisig's own rule, which Knos reads back (`knos audit show`) and does not enforce."
_BOUNDS = "an order holds 5.00 to 100,000.00 of its money (error 81)"
_STORED = "the hash of the terms is stored in the order, and PayOrder (17) takes only a token whose audience carries that hash (error 87)"
_REFUND = "the work time is 60 seconds to 90 days (error 81); after the deadline nothing pays the order and RefundOrder (22) returns the money to where it came from"
_SPENDER = ("GitHub's token must name the Balance's owner as the repository's owner and the commenter as that owner or a spender its wallet "
            "listed (error 92)")
_BAL_CAP = "the Balance's cap for one order (error 93)"
_BAL_X = "the Balance's daily and total limits count the amount and the fee (error 100)"
_UNPINNED = ("Read by the pinned workflow only. A token from a run that skipped it (a workflow file changed on the default branch) is refused by "
             "nothing but the Balance's own limits and its workflows pin (`X_WF_SHA`, error 86), which its wallet sets with `knos budget set --pin-workflows`.")
_NO_ENVELOPE = ("`knos budget envelope FILE --fund N` prints the envelope before and after and refuses over its limit. It sends nothing, the "
                "workflow reads no envelope for this, and an envelope's figures are typed. The Balance's limits are what holds.")
_NO_CARD_TEXT = "This names no rate card. `knos budget offer` and the console show a card's price; nothing compares this amount with one."


def _p(by: str, test: str) -> Cell:
    return Cell("program", by, test)


def _w(by: str, test: str) -> Cell:
    return Cell("workflow", by, test)


def _a(by: str, test: str) -> Cell:
    return Cell("advisory", by, test)


def _o(why: str, test: str = "") -> Cell:
    return Cell("outside", why, test)


CELLS: dict[str, dict[str, Cell]] = {
    "wallet": {
        "who": _p("knos_pay FundOrderWallet (15), FundWallet (4): the funder's own signature spends the funder's own token account (error 80 "
                  "without it). No GitHub account, policy file or approval is asked: the money is the wallet's.", _WALLET),
        "order_limit": _p(f"knos_pay FundOrderWallet (15): {_BOUNDS}. No cap of an organisation applies: a cap belongs to a Balance.",
                          _E + "test_a_wallet_is_held_to_the_programs_bounds_and_to_no_file"),
        "period_limit": _o("A wallet has no period: it spends what it holds. A limit per period on an organisation's money is a Balance's (the "
                           "row Funding by comment), or the wallet's own rule when it is a multisig."),
        "approvers": _o(_OWN),
        "rate_card": _o(_NO_FILE),
        "envelope": _o(_NO_FILE),
        "suppliers": _o("Who is paid is decided at payment, by the signed run of the workflows the order names. The repository's "
                        "`.knos/policy.yml` is not the wallet's, and the wallet states no list."),
        "terms": _p(f"knos_pay FundOrderWallet (15): the terms are logged, {_STORED}.", _E + "test_a_wallet_is_held_to_the_programs_bounds_and_to_no_file"),
        "deadline": _p(f"knos_pay FundOrderWallet (15): {_REFUND}.", _DEADLINE),
    },
    "vault": {
        "who": _p("knos_pay FundOrderWallet (15) takes the vault's signature as the funder's (error 80 without it), and the vault signs only "
                  "inside Squads v4 VaultTransactionExecute: a key that is no member cannot propose (NotAMember), and nothing executes short "
                  "of the threshold.", _SQ_VOTE),
        "order_limit": _o("A vote of the threshold is the organisation deciding: it can fund up to knos_pay's bounds (an order holds 5.00 to "
                          "100,000.00, error 81). The cap a requester meets is the vault's Balance (row Enterprise vault's Balance), which "
                          "only a vote changes."),
        "period_limit": _o("Same reason: the threshold may spend what the vault holds. A limit per period that binds requesters is the "
                           "vault's Balance; one that binds a key without a vote is an allowance (row A Squads allowance)."),
        "approvers": _p("knos_pay FundOrderWallet (15) is reached only through Squads v4 VaultTransactionExecute, after ProposalApprove: "
                        "only keys with the Vote permission count, a requester's key cannot vote (Unauthorized), execution waits for the "
                        "threshold (InvalidProposalStatus) and for the time lock after the last vote (TimeLockNotReleased). Only the "
                        "config authority changes members, threshold or time lock.", _SQ_VOTE),
        "rate_card": _a("`knos boundary bind` puts the amount in the commitment the approvers sign. Nothing compares it with a rate card.",
                        _B + "test_an_approval_funds_the_one_commitment_it_names"),
        "envelope": _p("knos_pay FundOrderWallet (15) moves the amount and the fee from the vault's token account into the order when the "
                       "funding executes, before any work; the token program refuses what the vault does not hold, so two approved "
                       "fundings cannot both take the last of it. `knos boundary reserve` also holds a budget at approval, in a file.",
                       _SQ_HOLDS),
        "suppliers": _w("prove.yml job `settle` and attest.yml job `attest`: `flow._cleared` refuses a payee that `payees` in "
                        "`.knos/policy.yml` does not list. The payee an approval names (`knos boundary bind`) is checked by "
                        "`boundary.payee_allowed`, which no workflow asks yet.", _E + "test_a_neutral_run_refuses_a_payee_the_policy_file_does_not_list"),
        "terms": _p(f"knos_pay FundOrderWallet (15): the terms are logged, {_STORED}. Squads v4 VaultTransactionCreate stores the message "
                    "the members vote on, so the votes are for those bytes.", _E + "test_a_wallet_is_held_to_the_programs_bounds_and_to_no_file"),
        "deadline": _p(f"knos_pay FundOrderWallet (15): {_REFUND}: to the vault.", _DEADLINE),
    },
    "vault_balance": {
        "who": _p(f"knos_pay FundOrderBalance (16): {_SPENDER}. SetBalance (1) and SetBalanceX (13) take only the vault's signature "
                  "(error 98), so neither a requester's nor an approver's own key adds a spender.", _SQ_VBAL),
        "order_limit": _p(f"knos_pay FundOrderBalance (16): {_BAL_CAP}. Only a vote of the vault raises it (SetBalance (1)).", _SQ_VBAL),
        "period_limit": _p(f"knos_pay FundOrderBalance (16): {_BAL_X}. Only a vote of the vault changes them (SetBalanceX (13)).", _LIMITS),
        "approvers": _w("fund.yml job `command`: `flow._gated` asks `approvals.gate_order`, as for Funding by comment. "
                        "`boundary.gate_bound` (one approval, one commitment) is not asked by the workflow yet.", _PLAIN),
        "rate_card": _a(_NO_CARD_TEXT, _NO_CARD),
        "envelope": _p("knos_pay FundOrderBalance (16) takes the amount from the Balance's token account into the order at funding; the "
                       "Balance holds only what a vote of the vault moved into it, and the token program refuses more.", _SQ_VBAL),
        "suppliers": _w("prove.yml job `settle` and attest.yml job `attest`: `flow._cleared`, as for Funding by comment.",
                        _E + "test_a_neutral_run_refuses_a_payee_the_policy_file_does_not_list"),
        "terms": _p(f"knos_pay FundOrderBalance (16): GitHub signs the amount, the terms' hash and the Balance in one audience; {_STORED}.",
                    "tests/test_pay_chain.py::test_every_wrong_proof_is_refused"),
        "deadline": _p(f"knos_pay FundOrderBalance (16): {_REFUND}: to the Balance, which only the vault's vote withdraws (Withdraw (2)).",
                       _DEADLINE),
    },
    "allowance": {
        "who": _p("Squads v4 SpendingLimitUse: only a key the allowance lists (Unauthorized otherwise), and only the config authority "
                  "adds or removes an allowance. It takes no vote: the allowance is a standing approval.", _SQ_ALLOW),
        "order_limit": _p("Squads v4 SpendingLimitUse: never more than what is left of the period's amount (SpendingLimitExceeded).", _SQ_ALLOW),
        "period_limit": _p("Squads v4 SpendingLimitUse: the amount comes back after a day, a week or 30 days, never sooner; a one-time "
                           "allowance never.", _SQ_ALLOW),
        "approvers": _o("An allowance is approved once, by the config authority that adds it; its uses take no vote. That is what it is for, "
                        "and why the plan adds none unless asked."),
        "rate_card": _o(_NO_FILE),
        "envelope": _p("Squads v4 SpendingLimitUse: the allowance's amount is its own budget, and the vault's token account is the floor.",
                       _SQ_ALLOW),
        "suppliers": _p("Squads v4 SpendingLimitUse: only to a destination the allowance lists (InvalidDestination). A destination is the "
                        "owner of the receiving token account, and every Balance and order of knos_pay has the same owner, so an allowance "
                        "cannot be narrowed to one Balance: the plan points allowances at a supplier's own wallet.", _SQ_ALLOW),
        "terms": _o("An allowance moves tokens; no order and no terms are involved. Paying through Knos is the row Enterprise vault, by vote."),
        "deadline": _o("An allowance has no deadline. The config authority removes it."),
    },
    "comment": {
        "who": _p(f"knos_pay FundOrderBalance (16): {_SPENDER}. Before that the workflow asks more: write access (`flow._can_write`), "
                  "`who_may_fund` in `.knos/policy.yml` (`flow._order_plan`), the requester role when the repository has procurement files "
                  "(`flow._gated`). On devnet the faucet's Balance lists no spender: whoever the workflow lets fund spends test USDC.", _LIMITS),
        "order_limit": _p(f"knos_pay FundOrderBalance (16): {_BAL_CAP}, and {_BOUNDS}. `cap_per_order` in `.knos/policy.yml` is the "
                          "workflow's, asked first (`flow._order_plan`).", _LIMITS),
        "period_limit": _p(f"knos_pay FundOrderBalance (16): {_BAL_X}. `monthly_budget` in `.knos/policy.yml` is the workflow's "
                           "(`flow._order_plan`).", _LIMITS),
        "approvers": _w("fund.yml job `command`: `flow._gated` asks `approvals.gate_order`. With `.knos/procurement/policy.yaml` on the default "
                        "branch, the commenter holds the requester role and the approvals the amount needs for `issue:<number>` are in the "
                        "log and still on the forge. With no such file nothing more is asked.", _PLAIN),
        "rate_card": _a(_NO_CARD_TEXT, _NO_CARD),
        "envelope": _a(_NO_ENVELOPE, _NO_CARD),
        "suppliers": _w("prove.yml job `settle` and attest.yml job `attest`: `flow._cleared` refuses a payee that `payees` in "
                        "`.knos/policy.yml` does not list. A neutral run in another repository (`flow.attest`) reads the buyer's file too "
                        "and signs nothing for such a payee.", _E + "test_a_neutral_run_refuses_a_payee_the_policy_file_does_not_list"),
        "terms": _p(f"knos_pay FundOrderBalance (16): GitHub signs the amount, the mode, the terms' hash, the Balance and the work time in one "
                    f"audience; {_STORED}.", "tests/test_pay_chain.py::test_every_wrong_proof_is_refused"),
        "deadline": _p(f"knos_pay FundOrderBalance (16): {_REFUND}.", _DEADLINE),
    },
    "tip": {
        "who": _p(f"knos_pay FundBalance (3): {_SPENDER}. The workflow asks write access (`flow._can_write`) and, with procurement files, the "
                  "requester role (`flow._gated`). `who_may_fund` in `.knos/policy.yml` is not asked for a tip.",
                  _P2 + "test_only_the_owner_and_the_listed_spenders_spend_a_balance"),
        "order_limit": _p("knos_pay FundBalance (3): the Balance's cap for one job (error 93). `cap_per_order` in `.knos/policy.yml` is not "
                          "asked for a tip.", _P2 + "test_a_cap_per_job_is_enforced"),
        "period_limit": _p(f"knos_pay FundBalance (3): {_BAL_X}. `monthly_budget` in `.knos/policy.yml` is not asked for a tip.", _LIMITS),
        "approvers": _w("fund.yml job `command`: `flow._gated` asks `approvals.gate_order` for `tip:<pull request>`, as for a plain order. "
                        "With no procurement file nothing more is asked.", _E + "test_a_tip_is_held_to_the_approval_policy_too"),
        "rate_card": _o("A tip is a gift for one merged pull request: no outcome is priced."),
        "envelope": _a(_NO_ENVELOPE, _E + "test_a_tip_is_held_to_the_approval_policy_too"),
        "suppliers": _w("prove.yml job `settle`: `flow._cleared` refuses a payee that `payees` in `.knos/policy.yml` does not list. A tip is a "
                        "job, and no neutral run pays a job.", _PAYEES),
        "terms": _p("knos_pay FundBalance (3): a tip's terms ask for nothing, their hash is stored in the job, and Pay (5) takes only a "
                    "token that carries it (error 87).", "tests/test_pay_chain.py::test_every_wrong_proof_is_refused"),
        "deadline": _p("knos_pay FundBalance (3): GitHub signs the work time (one day for a tip); after it Refund (7) returns the money.",
                       _P2 + "test_with_no_proof_by_the_deadline_the_money_goes_back_where_it_came_from"),
    },
    "offer": {
        "who": _p(f"knos_pay FundOrderBalance (16): {_SPENDER}. The workflow asks write access, `who_may_fund`, and that the offer file's "
                  "requester holds the requester role (`flow._gated`).", _LIMITS),
        "order_limit": _p(f"knos_pay FundOrderBalance (16): {_BAL_CAP} holds the offer's budget, and PayOrder (17) pays one rate, signed in "
                          "the order's options, each time the agreed checks pass at merge.",
                          "tests/test_order_terms.py::test_a_standing_order_pays_its_rate_once_per_pull_request_until_less_than_one_rate_is_left"),
        "period_limit": _p(f"knos_pay FundOrderBalance (16): {_BAL_X}. An offer file's cap by period is one funding a period: the program "
                           "holds a budget until its deadline, 90 days at most.", _LIMITS),
        "approvers": _w("fund.yml job `command`: `flow._gated` asks `approvals.gate`. An offer file must name this vendor, rate and cap, and "
                        "the approvals its whole commitment needs must be in the log and still on the forge.", _OFFER),
        "rate_card": _w("fund.yml job `command`: `flow._gated` asks `approvals.gate`. The comment's rate must be the price of the offer's "
                        "outcome in the rate card the offer names, and the card must cite published terms by hash.", _OFFER),
        "envelope": _a("`approvals.gate` reads the envelope the offer names and refuses one that is not sound. It does not compare the "
                       "commitment with what the envelope has left: `knos budget offer FILE` does, and an envelope's figures are typed.",
                       _E + "test_an_offer_over_its_envelope_still_funds_once_it_is_approved"),
        "suppliers": _w("fund.yml job `command`: `flow._gated` asks `approvals.gate` (the offer file's `suppliers` must name the vendor), after "
                        "`vendors` in `.knos/policy.yml` (`flow._order_plan`). The vendor's GitHub id is in the terms the order's hash covers.",
                        "tests/test_procurement.py::test_the_gate_a_funding_workflow_can_ask"),
        "terms": _p(f"knos_pay FundOrderBalance (16): GitHub signs the amount, the terms' hash and the options (the rate) in one audience; {_STORED}.",
                    "tests/test_pay_chain.py::test_every_wrong_proof_is_refused"),
        "deadline": _p(f"knos_pay FundOrderBalance (16): {_REFUND}. The offer file's `starts` and `ends` are the workflow's (`approvals.gate`).",
                       _DEADLINE),
    },
    "topup": {
        "who": _p("knos_pay TopUp (23): only the wallet that funded the order signs, or the wallet that opened the Balance it came from "
                  "(errors 80 and 98). A comment cannot: `/knos raise` replies with how (`flow._order_word`).", _TOPUP),
        "order_limit": _o("TopUp checks one bound: the new whole amount is at most 100,000.00 (error 81). The Balance's cap for one order is "
                          "not asked, so a top-up can take an order past it. Outside on purpose: the one wallet that may sign a top-up is the "
                          "wallet that sets the cap.", _TOPUP),
        "period_limit": _o("TopUp does not count against the Balance's daily or total limit. Outside for the same reason: only the wallet "
                           "that sets those limits can sign it.", _TOPUP),
        "approvers": _o(_OWN, _TOPUP),
        "rate_card": _o(_NO_FILE),
        "envelope": _o(_NO_FILE + " Whoever owns an envelope adds a top-up to it by hand."),
        "suppliers": _o("A top-up adds money to an order. Who that order pays is not changed by it."),
        "terms": _p("knos_pay TopUp (23): it changes the amount and the fee and nothing else. The terms' hash stored at funding stays.", _TOPUP),
        "deadline": _p("knos_pay TopUp (23): refused once the order's deadline has passed (error 83), and it never moves the deadline.",
                       _OC + "test_top_up_adds_to_the_amount_and_the_fee_from_where_the_money_came"),
    },
    "private": {
        "who": _p("knos_pay FundOrderBalance (16): the token names the attestor repository and who started its run; the Balance must list "
                  "that account (error 92) and, when it lists repositories, that repository (error 92). The workflow asks that the list is "
                  "there (`flow._listed_for`), write access in the private repository and `who_may_fund` in the attestor's policy.", _LIMITS),
        "order_limit": _p(f"knos_pay FundOrderBalance (16): {_BAL_CAP}, and {_BOUNDS}.", _LIMITS),
        "period_limit": _p(f"knos_pay FundOrderBalance (16): {_BAL_X}.", _LIMITS),
        "approvers": _w("fund.yml job `command` in the attestor: `flow._attestor_command` runs `flow._fund`, whose `flow._gated` asks "
                        "`approvals.gate_order` of the private repository's own procurement files.",
                        _E + "test_a_private_order_is_held_to_the_approval_policy_of_its_own_repository"),
        "rate_card": _a(_NO_CARD_TEXT + " A standing offer is not private yet.", _E + "test_a_private_order_is_held_to_the_approval_policy_of_its_own_repository"),
        "envelope": _a(_NO_ENVELOPE, _E + "test_a_private_order_is_held_to_the_approval_policy_of_its_own_repository"),
        "suppliers": _w("prove.yml job `settle` in the attestor: `flow._attestor_settle` runs `flow._settle_one`, whose `flow._cleared` refuses "
                        "a payee the attestor's `.knos/policy.yml` does not list. A private order is never neutral: no other run pays it.", _PAYEES),
        "terms": _p("knos_pay FundOrderBalance (16), private: the order stores a hash of its salted scope and of its terms and nothing else, "
                    "and PayOrder (17) takes only a token that carries it.",
                    _OC + "test_a_private_order_stores_no_repository_no_issue_and_a_hash_of_its_terms"),
        "deadline": _p(f"knos_pay FundOrderBalance (16): {_REFUND}.", _DEADLINE),
    },
    "balance": {
        "who": _p("knos_pay OpenBalance (0): any wallet opens a Balance for any GitHub owner, with its own money. SetBalance (1), "
                  "SetBalanceX (13) and Withdraw (2): only the wallet that opened it signs (error 98), and Withdraw pays only a token account "
                  "of that wallet. A comment spends a Balance only in test USDC, or when its wallet is bound to the commenter or to the "
                  "repository's owner (`flow._ours`).", _P2 + "test_unspent_money_goes_back_only_to_the_wallet_that_opened_the_balance"),
        "order_limit": _p("knos_pay SetBalance (1): only the wallet that opened the Balance sets its cap and its spenders (error 98).",
                          _P2 + "test_only_the_wallet_that_opened_a_balance_changes_its_cap_and_spenders"),
        "period_limit": _p("knos_pay SetBalanceX (13): only that wallet sets the daily limit, the total limit, the repositories and the "
                           "workflows commit (error 98). Lowering a limit does not reset what was spent.",
                           _CT + "test_only_the_wallet_that_opened_the_balance_can_send_what_budget_set_builds"),
        "approvers": _o("One wallet's signature opens, limits and withdraws. Two people over a Balance is a multisig as that wallet: its "
                        "threshold is the multisig's rule."),
        "rate_card": _o(_NO_FILE),
        "envelope": _o("An envelope is a file and a Balance is the money. Nothing ties one to the other: the Balance's limits are the ones that hold."),
        "suppliers": _o("No supplier is paid on this route: Withdraw pays only the wallet that opened the Balance."),
        "terms": _o("A Balance has no terms: it is money set aside. Terms are fixed when an order is funded from it."),
        "deadline": _o("A Balance has no deadline. Its wallet withdraws unspent money at any time, paused or not."),
    },
    "netted": {
        "who": _p("The release is one order: knos_pay FundOrderBalance (16) or FundOrderWallet (15), held as the rows Funding by comment and "
                  "Wallet funding say. Until it is funded nothing is set aside: the supplier carries the buyer's credit inside the period, "
                  "up to the book's cap.", _NET_ONE),
        "order_limit": _a("Each outcome is under 20.00 and a period has a cap: `knos net add` refuses past either, in the book both sides "
                          "keep. No program reads a line. The one release is held to the Balance's cap (error 93).", _NET_CAP),
        "period_limit": _a("The period's cap is the book's: `knos net add` refuses an outcome that would pass it, and no program reads the book.",
                           _NET_CAP),
        "approvers": _a("No approval is asked while outcomes accumulate. The one release is a funding: by comment it is held as the row "
                        "Funding by comment says, for the net amount.", _NET_CLI),
        "rate_card": _a("An outcome's value is what its line in the book says. Nothing compares it with a rate card.", _NET_CLI),
        "envelope": _a("The book's cap is not an envelope, and no envelope is read when outcomes are added or the period closes.", _NET_CLI),
        "suppliers": _a("A book is between one buyer and one supplier, and its header names them. No program reads the header.", _NET_CLI),
        "terms": _p("The release's terms name the batch root, the three numbers and the pair; knos_pay stores their hash at funding and "
                    "PayOrder (17) takes only a token that carries it. The link from the release to each line is a reader's comparison, "
                    "never the program's.", _NET_ONE),
        "deadline": _p(f"The release is one order of knos_pay: {_REFUND}. When a period closes is the book's.", _DEADLINE),
    },
    "advance": {
        "who": _p("knos_pay Assign (24): the first time the payee's bound wallet signs; after that only the assignee can change it. The "
                  "advancer's payment to the supplier is the advancer's own transfer, in the same transaction.",
                  "tests/test_order_terms.py::test_a_payee_assigns_an_orders_payment_and_only_the_assignee_can_change_it"),
        "order_limit": _o("No buyer money moves: an advance is the advancer's own money, and the order's amount does not change."),
        "period_limit": _o("No buyer money moves, so no limit of the buyer's is spent."),
        "approvers": _o("The buyer is not asked. Assign changes which wallet receives a payment the buyer already funded, never whether or "
                        "how much. What an advancer accepts is its own offer file (`knos advance offer`)."),
        "rate_card": _o(_NO_FILE),
        "envelope": _o(_NO_FILE),
        "suppliers": _o("The payee stays the account the order accepted. The receiving wallet was always the payee's to choose: Assign makes "
                        "that choice for one order and stops the payee from taking it back."),
        "terms": _p("knos_pay Assign (24): it records one wallet for one payee of one order. The amount and the terms' hash stay, and the "
                    "order pays or refunds exactly as it would have.",
                    "tests/test_advance.py::test_an_assignment_before_acceptance_pays_the_financier_at_acceptance_and_at_release_and_never_the_seller"),
        "deadline": _o("An assignment adds no deadline: the order's own stands. After it the funder is refunded and the advancer collects "
                       "nothing, with no claim on chain."),
    },
    "passkey": {
        "who": _p("knos_passkey Fund and Withdraw: only a WebAuthn assertion by the wallet's own passkey over exactly this instruction, with "
                  "the wallet's next nonce, checked by the secp256r1 precompile. The relay pays the fee and decides nothing. The money is the "
                  "passkey holder's: no Balance, policy file or approval is asked.",
                  "tests/test_passkey_chain.py::test_another_passkeys_signature_is_refused"),
        "order_limit": _o("The passkey spends what its wallet holds. Fund carries knos_pay's FundOrderWallet (15) whole, so the row Wallet "
                          "funding holds; no cap of an organisation applies."),
        "period_limit": _o("A passkey wallet has no period: it spends what it holds."),
        "approvers": _o("The passkey's signature is the approval: one person, one device."),
        "rate_card": _o(_NO_FILE),
        "envelope": _o(_NO_FILE),
        "suppliers": _o("A withdrawal goes to the token account the passkey signed, and a funding to the order it signed. No list is read."),
        "terms": _p("knos_passkey Fund and Withdraw: the passkey signs the whole instruction (the amount, the destination, the mint, the "
                    "terms), and a changed byte is refused.", "tests/test_passkey_chain.py::test_a_changed_amount_destination_or_mint_is_refused"),
        "deadline": _p("knos_passkey Fund and Withdraw: one assertion works once (the nonce), and a funding's assertion names the last slot "
                       "it can land in. The order's own deadline is the row Wallet funding.",
                       "tests/test_passkey_chain.py::test_withdrawals_follow_one_another_and_none_can_be_sent_twice"),
    },
    "direct": {
        "who": _p("Anyone may send any instruction of knos_pay. Money moves only on the signature of the wallet whose money it is, or on a token GitHub "
                  "signed for this exact audience, verified by knos_oidc and used once (errors 84 to 87 and 91). A relayer carries a token "
                  "and decides nothing. RefundOrder (22) and Release (18) pay only where the order already says.",
                  "tests/test_pay_chain.py::test_nobody_can_claim_another_accounts_money"),
        "order_limit": _p(f"knos_pay FundOrderBalance (16): {_BAL_CAP}, whoever carries the token.", _LIMITS),
        "period_limit": _p(f"knos_pay FundOrderBalance (16): {_BAL_X}, whoever carries the token.", _LIMITS),
        "approvers": _a("`.knos/procurement/`: " + _UNPINNED, _PIN),
        "rate_card": _a("`.knos/procurement/rate-cards/`: " + _UNPINNED, _PIN),
        "envelope": _a("`.knos/procurement/envelopes/`: " + _UNPINNED, _PIN),
        "suppliers": _a("`.knos/policy.yml` and the offer files: " + _UNPINNED, _PIN),
        "terms": _p(f"knos_pay: every funding stores the terms' hash, and {_STORED}. A token works once (error 91).",
                    _P2 + "test_a_fund_token_works_once"),
        "deadline": _p(f"knos_pay: {_REFUND}. RefundOrder is open to anyone and pays only the funder.", _DEADLINE),
    },
}

NOTES = (
    "What `workflow` is worth. The pinned workflow asks before GitHub signs, so a comment the gate refuses funds nothing. It binds whoever "
    "funds through that workflow. It does not bind a wallet that calls the program with its own money, and it does not bind someone who can "
    "change the workflow file on the repository's default branch: for them the Balance's limits and its workflows pin are what hold.",
    "What an approval is. A comment by the named account on the forge, read back through the forge's API. Knos adds no key: whoever controls "
    "the approver's account controls the approval, and whoever can rewrite `.knos/procurement/policy.yaml` can name a new approver.",
    "One approval, one subject, one amount. An approval names `offer:<name>`, `issue:<number>` or `tip:<number>` and an amount. A second "
    "order of the same amount on the same issue is covered by the same approval: the Balance's limits bound how often.",
    "A repository with no file under `.knos/procurement/` is asked nothing more than before: the gate is one question to the forge, answered no.",
    "Enterprise-controlled funds. The rows Enterprise vault, by vote, Enterprise vault's Balance and A Squads allowance are an "
    "organisation's money in a Squads v4 vault (Squads Labs' deployed program; Knos changes nothing in it). Their `program` cells are "
    "Squads' and knos_pay's checks, run by tests/test_boundary.py against the deployed Squads build in the simulator. A person's own "
    "wallet stays outside: it is their money, and an organisation's policy cannot bind it.",
    "Deployed and exercised. The program checks named here are those of the knos_pay and knos_passkey sources in this repository, run by the "
    "named tests against the committed builds. The workflow checks are in this release's workflows; no round on the public cluster has "
    "exercised the gate on a plain order, a tip or a private order, nor a funding from a Squads vault planned by `knos boundary`.",
)


ENTERPRISE = ("vault", "vault_balance", "allowance")   # the routes of enterprise-controlled funds: money in a Squads v4 vault (NOTES names all three)


def as_json() -> dict:
    """The table for a page. Keys are stable: `routes`, `restrictions`, `cells[route][restriction] = {class, by, test}`."""
    return {"version": 1, "classes": list(CLASSES),
            "routes": [{"id": i, "name": n, "how": h, **({"group": "enterprise"} if i in ENTERPRISE else {})} for i, n, h in ROUTES],
            "groups": {"enterprise": "Enterprise-controlled funds (Squads vault)"},
            "restrictions": [{"id": i, "name": n} for i, n in RESTRICTIONS],
            "cells": {r: {x: {"class": c.cls, "by": c.by, "test": c.test} for x, c in row.items()} for r, row in CELLS.items()},
            "counts": counts(), "notes": list(NOTES)}


def counts() -> dict[str, int]:
    out = {c: 0 for c in CLASSES}
    for row in CELLS.values():
        for cell in row.values():
            out[cell.cls] += 1
    return out


def problems() -> list[str]:
    """What is wrong with the table's own shape ([]: nothing): every route has every restriction once, every class is
    one of the four, every cell says by what, and every cell that is not `outside` names a test."""
    out: list[str] = []
    for rid, _name, _how in ROUTES:
        row = CELLS.get(rid, {})
        out += [f"{rid} x {x}: no cell" for x, _n in RESTRICTIONS if x not in row]
        out += [f"{rid} x {x}: not a restriction" for x in row if x not in {i for i, _n in RESTRICTIONS}]
        for x, c in row.items():
            if c.cls not in CLASSES:
                out.append(f"{rid} x {x}: `{c.cls}` is not a class")
            if not c.by.strip():
                out.append(f"{rid} x {x}: says nothing")
            if c.cls != "outside" and "::" not in c.test:
                out.append(f"{rid} x {x}: names no test")
    out += [f"{r}: not a route" for r in CELLS if r not in {i for i, _n, _h in ROUTES}]
    return out


OUTSIDE_MATRIX = (     # two gaps between what the program allows and what the contract says, each with the command that shows it
    ("The Plan floor",
     "knos_pay lets FEE_OWNER set a Plan for one owner's orders down to 10 basis points (`PLAN_BPS_MIN`); the price book's floor is "
     "0.20%. The program allows 10 bps; Knos signs no Plan below 20 bps; the check proves which Plans exist. `knos.plan_floor.build` "
     "is the one Knos builder of SetPlan and refuses below 20; `knos fees plans --check` reads every Plan account on the cluster "
     "(one getProgramAccounts, by the Plan's 24-byte length) and exits 1 when one in force is below 20. Test: "
     "`tests/test_plan_floor.py`."),
    ("The workflow-strip hole",
     "A buyer who controls the repository can remove or edit the Knos workflow in the pull request it merges, so the check never runs. "
     "`knos protect --check-strip OWNER/REPO` reads GitHub's rules for the default branch and says: closed (a ruleset's `workflows` "
     "rule requires the Knos workflow, which then runs from the pinned file, not the pull request's copy), partly (a required status "
     "check names a Knos check: the merge waits for it, but a pull request can change the workflow behind it), or open. Closed never "
     "holds against those who can edit or bypass the ruleset: organisation owners for an organisation ruleset, repository admins for "
     "a repository one. Requiring workflows through rulesets is a GitHub Enterprise Cloud feature "
     "(https://github.blog/changelog/2023-10-11-requiring-workflows-with-repository-rules-is-generally-available/); the rule shapes "
     "are in https://docs.github.com/en/rest/repos/rules. Test: `tests/test_strip_check.py`."),
)


def _cell_md(text: str) -> str:
    return text.replace("|", "\\|")


def render() -> str:
    """docs/ENFORCEMENT.md, whole."""
    n = counts()
    total = sum(n.values())
    lines = [
        "# The enforcement matrix",
        "",
        "<!-- Written by `python -m knos.enforce --write` from src/knos/enforce.py. Do not edit: change the table there. -->",
        "",
        "Every route that can set money aside or move it, against every restriction a buyer can state. Each cell is one of:",
        "",
        "| class | what it means |",
        "|---|---|",
        "| **program** | An instruction of a deployed program refuses it. The cell names the instruction and the check. |",
        "| **workflow** | A job of the pinned workflows refuses it before GitHub is asked to sign. The cell names the job and the function. |",
        "| **advisory** | A file or a command says so, and nothing stops it. |",
        "| **outside** | Intentionally outside the policy boundary. The cell says why. |",
        "",
        f"{total} cells: {n['program']} program, {n['workflow']} workflow, {n['advisory']} advisory, {n['outside']} outside. Every cell that is "
        "not `outside` names a test that tries to get round it and asserts what really happens; `tests/test_enforcement.py` holds this page "
        "to the table, the table to the tests it names, and the instructions and functions it names to the source.",
        "",
        "## At a glance",
        "",
        "| route | " + " | ".join(name for _i, name in RESTRICTIONS) + " |",
        "|---|" + "---|" * len(RESTRICTIONS),
    ]
    for rid, name, _how in ROUTES:
        lines.append(f"| [{name}](#{rid}) | " + " | ".join(CELLS[rid][x].cls for x, _n in RESTRICTIONS) + " |")
    lines += ["", "## What to keep in mind", ""]
    lines += [f"- {_cell_md(note)}" for note in NOTES]
    lines += [f"- Outside the matrix: {name.lower()}. {_cell_md(note)}" for name, note in OUTSIDE_MATRIX]
    for rid, name, how in ROUTES:
        lines += ["", f'<a id="{rid}"></a>', "", f"## {name}", "", how, "", "| restriction | class | by what | test |", "|---|---|---|---|"]
        for x, xname in RESTRICTIONS:
            c = CELLS[rid][x]
            lines.append(f"| {xname} | {c.cls} | {_cell_md(c.by)} | {('`' + c.test + '`') if c.test else ''} |")
    return "\n".join(lines) + "\n"


def text() -> str:
    """What `knos controls matrix` prints: the grid of classes, then each cell on a line of its own."""
    wide = max(len(name) for _i, name, _h in ROUTES)
    col = {x: max(len(x), max(len(c) for c in CLASSES)) for x, _n in RESTRICTIONS}
    out = [(" " * wide + "  " + "  ".join(x.ljust(col[x]) for x, _n in RESTRICTIONS)).rstrip()]
    for rid, name, _how in ROUTES:
        out.append((name.ljust(wide) + "  " + "  ".join(CELLS[rid][x].cls.ljust(col[x]) for x, _n in RESTRICTIONS)).rstrip())
    for rid, name, _how in ROUTES:
        out.append("")
        out.append(name)
        out += [f"  {xname}: {CELLS[rid][x].cls}. {CELLS[rid][x].by}" for x, xname in RESTRICTIONS]
    return "\n".join(out)


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    bad = problems()
    if bad:
        print("\n".join(bad), file=sys.stderr)
        return 1
    if args == ["--json"]:
        print(json.dumps(as_json(), indent=1, sort_keys=True))
        return 0
    if args == ["--write"]:
        (_root() / DOC).write_text(render(), encoding="utf-8", newline="\n")
        print(f"Wrote {DOC}.")
        return 0
    if args == ["--check"]:
        file = _root() / DOC
        if not file.is_file() or file.read_text(encoding="utf-8") != render():
            print(f"{DOC} is not what src/knos/enforce.py says. Run: python -m knos.enforce --write", file=sys.stderr)
            return 1
        print(f"{DOC} is what the table says.")
        return 0
    if not args:
        print(text())
        return 0
    print("usage: python -m knos.enforce [--write | --check | --json]", file=sys.stderr)
    return 2


def register(app, help_lines: list | None = None) -> None:
    """`knos controls matrix`, on the main app. `help_lines`: cli._HELP, which gets the group's line."""
    import importlib
    typer = importlib.import_module("typer")       # named here and not imported: this module is standard library only at import

    group = typer.Typer(add_completion=False, no_args_is_help=True, help="What stops money on each route: the enforcement matrix.")
    app.add_typer(group, name="controls")
    if help_lines is not None:
        help_lines.append(("controls", "For money", "The enforcement matrix: each route that moves money, each restriction, and what stops it."))

    @group.command("matrix")
    def matrix_(as_json_: bool = typer.Option(False, "--json", help="print the table as JSON")) -> None:
        """Print the enforcement matrix: for every route that can set money aside or move it, and every restriction, whether a program, the pinned workflow, or nothing enforces it, and the test that tries to get round it."""
        typer.echo(json.dumps(as_json(), indent=1, sort_keys=True) if as_json_ else text())


if __name__ == "__main__":
    sys.exit(main())
