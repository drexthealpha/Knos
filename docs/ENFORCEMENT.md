# The enforcement matrix

<!-- Written by `python -m knos.enforce --write` from src/knos/enforce.py. Do not edit: change the table there. -->

Every route that can set money aside or move it, against every restriction a buyer can state. Each cell is one of:

| class | what it means |
|---|---|
| **program** | An instruction of a deployed program refuses it. The cell names the instruction and the check. |
| **workflow** | A job of the pinned workflows refuses it before GitHub is asked to sign. The cell names the job and the function. |
| **advisory** | A file or a command says so, and nothing stops it. |
| **outside** | Intentionally outside the policy boundary. The cell says why. |

126 cells: 59 program, 12 workflow, 18 advisory, 37 outside. Every cell that is not `outside` names a test that tries to get round it and asserts what really happens; `tests/test_enforcement.py` holds this page to the table, the table to the tests it names, and the instructions and functions it names to the source.

## At a glance

| route | Who may fund | Limit per order | Limit per period | Approver count | Rate card | Envelope or budget | Supplier allow-list | Terms fixed at funding | Deadline |
|---|---|---|---|---|---|---|---|---|---|
| [Wallet funding](#wallet) | program | program | outside | outside | outside | outside | outside | program | program |
| [Enterprise vault, by vote](#vault) | program | outside | outside | program | advisory | program | workflow | program | program |
| [Enterprise vault's Balance](#vault_balance) | program | program | program | workflow | advisory | program | workflow | program | program |
| [A Squads allowance](#allowance) | program | program | program | outside | outside | program | program | outside | outside |
| [Funding by comment](#comment) | program | program | program | workflow | advisory | advisory | workflow | program | program |
| [A tip by comment](#tip) | program | program | program | workflow | outside | advisory | workflow | program | program |
| [A standing offer](#offer) | program | program | program | workflow | workflow | advisory | workflow | program | program |
| [A top-up](#topup) | program | outside | outside | outside | outside | outside | outside | program | program |
| [A private order](#private) | program | program | program | workflow | advisory | advisory | workflow | program | program |
| [A Balance](#balance) | program | program | program | outside | outside | outside | outside | outside | outside |
| [A netted release](#netted) | program | advisory | advisory | advisory | advisory | advisory | advisory | program | program |
| [An advance](#advance) | program | outside | outside | outside | outside | outside | outside | program | outside |
| [The passkey relay](#passkey) | program | outside | outside | outside | outside | outside | outside | program | program |
| [A direct call by anyone](#direct) | program | program | program | advisory | advisory | advisory | advisory | program | program |

## What to keep in mind

- What `workflow` is worth. The pinned workflow asks before GitHub signs, so a comment the gate refuses funds nothing. It binds whoever funds through that workflow. It does not bind a wallet that calls the program with its own money, and it does not bind someone who can change the workflow file on the repository's default branch: for them the Balance's limits and its workflows pin are what hold.
- What an approval is. A comment by the named account on the forge, read back through the forge's API. Knos adds no key: whoever controls the approver's account controls the approval, and whoever can rewrite `.knos/procurement/policy.yaml` can name a new approver.
- One approval, one subject, one amount. An approval names `offer:<name>`, `issue:<number>` or `tip:<number>` and an amount. A second order of the same amount on the same issue is covered by the same approval: the Balance's limits bound how often.
- A repository with no file under `.knos/procurement/` is asked nothing more than before: the gate is one question to the forge, answered no.
- Enterprise-controlled funds. The rows Enterprise vault, by vote, Enterprise vault's Balance and A Squads allowance are an organisation's money in a Squads v4 vault (Squads Labs' deployed program; Knos changes nothing in it). Their `program` cells are Squads' and knos_pay's checks, run by tests/test_boundary.py against the deployed Squads build in the simulator. A person's own wallet stays outside: it is their money, and an organisation's policy cannot bind it.
- Deployed and exercised. The program checks named here are those of the knos_pay and knos_passkey sources in this repository, run by the named tests against the committed builds. The workflow checks are in this release's workflows; no round on the public cluster has exercised the gate on a plain order, a tip or a private order, nor a funding from a Squads vault planned by `knos boundary`.

<a id="wallet"></a>

## Wallet funding

A wallet calls knos_pay itself: FundOrderWallet (15), or FundWallet (4) for a job. Its own money.

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | knos_pay FundOrderWallet (15), FundWallet (4): the funder's own signature spends the funder's own token account (error 80 without it). No GitHub account, policy file or approval is asked: the money is the wallet's. | `tests/test_order_chain.py::test_what_a_funding_wallet_cannot_do` |
| Limit per order | program | knos_pay FundOrderWallet (15): an order holds 5.00 to 100,000.00 of its money (error 81). No cap of an organisation applies: a cap belongs to a Balance. | `tests/test_enforcement.py::test_a_wallet_is_held_to_the_programs_bounds_and_to_no_file` |
| Limit per period | outside | A wallet has no period: it spends what it holds. A limit per period on an organisation's money is a Balance's (the row Funding by comment), or the wallet's own rule when it is a multisig. |  |
| Approver count | outside | The wallet's signature is the approval. When the wallet is a multisig its threshold is the multisig's own rule, which Knos reads back (`knos audit show`) and does not enforce. |  |
| Rate card | outside | No file of a repository is read on this route: the program sees accounts and signatures, never `.knos/`. |  |
| Envelope or budget | outside | No file of a repository is read on this route: the program sees accounts and signatures, never `.knos/`. |  |
| Supplier allow-list | outside | Who is paid is decided at payment, by the signed run of the workflows the order names. The repository's `.knos/policy.yml` is not the wallet's, and the wallet states no list. |  |
| Terms fixed at funding | program | knos_pay FundOrderWallet (15): the terms are logged, the hash of the terms is stored in the order, and PayOrder (17) takes only a token whose audience carries that hash (error 87). | `tests/test_enforcement.py::test_a_wallet_is_held_to_the_programs_bounds_and_to_no_file` |
| Deadline | program | knos_pay FundOrderWallet (15): the work time is 60 seconds to 90 days (error 81); after the deadline nothing pays the order and RefundOrder (22) returns the money to where it came from. | `tests/test_order_chain.py::test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before` |

<a id="vault"></a>

## Enterprise vault, by vote

An organisation's money in a Squads v4 vault: a requester's key proposes, the threshold of voting keys approves, an Execute key executes after the time lock, and only then does the vault sign FundOrderWallet (15), TopUp (23), OpenBalance (0) or SetBalance (1). `knos boundary plan` writes the vault's settings from the approval policy.

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | knos_pay FundOrderWallet (15) takes the vault's signature as the funder's (error 80 without it), and the vault signs only inside Squads v4 VaultTransactionExecute: a key that is no member cannot propose (NotAMember), and nothing executes short of the threshold. | `tests/test_boundary.py::test_squads_refuses_a_funding_from_the_vault_without_the_threshold` |
| Limit per order | outside | A vote of the threshold is the organisation deciding: it can fund up to knos_pay's bounds (an order holds 5.00 to 100,000.00, error 81). The cap a requester meets is the vault's Balance (row Enterprise vault's Balance), which only a vote changes. |  |
| Limit per period | outside | Same reason: the threshold may spend what the vault holds. A limit per period that binds requesters is the vault's Balance; one that binds a key without a vote is an allowance (row A Squads allowance). |  |
| Approver count | program | knos_pay FundOrderWallet (15) is reached only through Squads v4 VaultTransactionExecute, after ProposalApprove: only keys with the Vote permission count, a requester's key cannot vote (Unauthorized), execution waits for the threshold (InvalidProposalStatus) and for the time lock after the last vote (TimeLockNotReleased). Only the config authority changes members, threshold or time lock. | `tests/test_boundary.py::test_squads_refuses_a_funding_from_the_vault_without_the_threshold` |
| Rate card | advisory | `knos boundary bind` puts the amount in the commitment the approvers sign. Nothing compares it with a rate card. | `tests/test_boundary.py::test_an_approval_funds_the_one_commitment_it_names` |
| Envelope or budget | program | knos_pay FundOrderWallet (15) moves the amount and the fee from the vault's token account into the order when the funding executes, before any work; the token program refuses what the vault does not hold, so two approved fundings cannot both take the last of it. `knos boundary reserve` also holds a budget at approval, in a file. | `tests/test_boundary.py::test_the_vault_cannot_fund_past_what_it_holds` |
| Supplier allow-list | workflow | prove.yml job `settle` and attest.yml job `attest`: `flow._cleared` refuses a payee that `payees` in `.knos/policy.yml` does not list. The payee an approval names (`knos boundary bind`) is checked by `boundary.payee_allowed`, which no workflow asks yet. | `tests/test_enforcement.py::test_a_neutral_run_refuses_a_payee_the_policy_file_does_not_list` |
| Terms fixed at funding | program | knos_pay FundOrderWallet (15): the terms are logged, the hash of the terms is stored in the order, and PayOrder (17) takes only a token whose audience carries that hash (error 87). Squads v4 VaultTransactionCreate stores the message the members vote on, so the votes are for those bytes. | `tests/test_enforcement.py::test_a_wallet_is_held_to_the_programs_bounds_and_to_no_file` |
| Deadline | program | knos_pay FundOrderWallet (15): the work time is 60 seconds to 90 days (error 81); after the deadline nothing pays the order and RefundOrder (22) returns the money to where it came from: to the vault. | `tests/test_order_chain.py::test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before` |

<a id="vault_balance"></a>

## Enterprise vault's Balance

A knos_pay Balance the vault opened by vote: `/knos fund` spends it as Funding by comment does, and its cap, limits, spenders and workflow pin change only by the vault's vote.

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | knos_pay FundOrderBalance (16): GitHub's token must name the Balance's owner as the repository's owner and the commenter as that owner or a spender its wallet listed (error 92). SetBalance (1) and SetBalanceX (13) take only the vault's signature (error 98), so neither a requester's nor an approver's own key adds a spender. | `tests/test_boundary.py::test_a_balance_the_vault_opened_is_changed_only_by_the_vault` |
| Limit per order | program | knos_pay FundOrderBalance (16): the Balance's cap for one order (error 93). Only a vote of the vault raises it (SetBalance (1)). | `tests/test_boundary.py::test_a_balance_the_vault_opened_is_changed_only_by_the_vault` |
| Limit per period | program | knos_pay FundOrderBalance (16): the Balance's daily and total limits count the amount and the fee (error 100). Only a vote of the vault changes them (SetBalanceX (13)). | `tests/test_controls.py::test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first` |
| Approver count | workflow | fund.yml job `command`: `flow._gated` asks `approvals.gate_order`, as for Funding by comment. `boundary.gate_bound` (one approval, one commitment) is not asked by the workflow yet. | `tests/test_enforcement.py::test_a_plain_fund_cannot_go_round_the_approval_a_standing_offer_needs` |
| Rate card | advisory | This names no rate card. `knos budget offer` and the console show a card's price; nothing compares this amount with one. | `tests/test_enforcement.py::test_a_plain_order_is_held_to_no_rate_card_and_no_envelope` |
| Envelope or budget | program | knos_pay FundOrderBalance (16) takes the amount from the Balance's token account into the order at funding; the Balance holds only what a vote of the vault moved into it, and the token program refuses more. | `tests/test_boundary.py::test_a_balance_the_vault_opened_is_changed_only_by_the_vault` |
| Supplier allow-list | workflow | prove.yml job `settle` and attest.yml job `attest`: `flow._cleared`, as for Funding by comment. | `tests/test_enforcement.py::test_a_neutral_run_refuses_a_payee_the_policy_file_does_not_list` |
| Terms fixed at funding | program | knos_pay FundOrderBalance (16): GitHub signs the amount, the terms' hash and the Balance in one audience; the hash of the terms is stored in the order, and PayOrder (17) takes only a token whose audience carries that hash (error 87). | `tests/test_pay_chain.py::test_every_wrong_proof_is_refused` |
| Deadline | program | knos_pay FundOrderBalance (16): the work time is 60 seconds to 90 days (error 81); after the deadline nothing pays the order and RefundOrder (22) returns the money to where it came from: to the Balance, which only the vault's vote withdraws (Withdraw (2)). | `tests/test_order_chain.py::test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before` |

<a id="allowance"></a>

## A Squads allowance

Squads v4 SpendingLimitUse: a key the config authority listed moves up to an amount a period to listed destinations, with no vote. `knos boundary plan` adds none unless the boundary file asks.

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | Squads v4 SpendingLimitUse: only a key the allowance lists (Unauthorized otherwise), and only the config authority adds or removes an allowance. It takes no vote: the allowance is a standing approval. | `tests/test_boundary.py::test_squads_refuses_an_allowance_over_its_limit_to_another_destination_or_by_another_key` |
| Limit per order | program | Squads v4 SpendingLimitUse: never more than what is left of the period's amount (SpendingLimitExceeded). | `tests/test_boundary.py::test_squads_refuses_an_allowance_over_its_limit_to_another_destination_or_by_another_key` |
| Limit per period | program | Squads v4 SpendingLimitUse: the amount comes back after a day, a week or 30 days, never sooner; a one-time allowance never. | `tests/test_boundary.py::test_squads_refuses_an_allowance_over_its_limit_to_another_destination_or_by_another_key` |
| Approver count | outside | An allowance is approved once, by the config authority that adds it; its uses take no vote. That is what it is for, and why the plan adds none unless asked. |  |
| Rate card | outside | No file of a repository is read on this route: the program sees accounts and signatures, never `.knos/`. |  |
| Envelope or budget | program | Squads v4 SpendingLimitUse: the allowance's amount is its own budget, and the vault's token account is the floor. | `tests/test_boundary.py::test_squads_refuses_an_allowance_over_its_limit_to_another_destination_or_by_another_key` |
| Supplier allow-list | program | Squads v4 SpendingLimitUse: only to a destination the allowance lists (InvalidDestination). A destination is the owner of the receiving token account, and every Balance and order of knos_pay has the same owner, so an allowance cannot be narrowed to one Balance: the plan points allowances at a supplier's own wallet. | `tests/test_boundary.py::test_squads_refuses_an_allowance_over_its_limit_to_another_destination_or_by_another_key` |
| Terms fixed at funding | outside | An allowance moves tokens; no order and no terms are involved. Paying through Knos is the row Enterprise vault, by vote. |  |
| Deadline | outside | An allowance has no deadline. The config authority removes it. |  |

<a id="comment"></a>

## Funding by comment

`/knos fund <amount>`: fund.yml job `command` has GitHub sign, and FundOrderBalance (16) spends a Balance.

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | knos_pay FundOrderBalance (16): GitHub's token must name the Balance's owner as the repository's owner and the commenter as that owner or a spender its wallet listed (error 92). Before that the workflow asks more: write access (`flow._can_write`), `who_may_fund` in `.knos/policy.yml` (`flow._order_plan`), the requester role when the repository has procurement files (`flow._gated`). On devnet the faucet's Balance lists no spender: whoever the workflow lets fund spends test USDC. | `tests/test_controls.py::test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first` |
| Limit per order | program | knos_pay FundOrderBalance (16): the Balance's cap for one order (error 93), and an order holds 5.00 to 100,000.00 of its money (error 81). `cap_per_order` in `.knos/policy.yml` is the workflow's, asked first (`flow._order_plan`). | `tests/test_controls.py::test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first` |
| Limit per period | program | knos_pay FundOrderBalance (16): the Balance's daily and total limits count the amount and the fee (error 100). `monthly_budget` in `.knos/policy.yml` is the workflow's (`flow._order_plan`). | `tests/test_controls.py::test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first` |
| Approver count | workflow | fund.yml job `command`: `flow._gated` asks `approvals.gate_order`. With `.knos/procurement/policy.yaml` on the default branch, the commenter holds the requester role and the approvals the amount needs for `issue:<number>` are in the log and still on the forge. With no such file nothing more is asked. | `tests/test_enforcement.py::test_a_plain_fund_cannot_go_round_the_approval_a_standing_offer_needs` |
| Rate card | advisory | This names no rate card. `knos budget offer` and the console show a card's price; nothing compares this amount with one. | `tests/test_enforcement.py::test_a_plain_order_is_held_to_no_rate_card_and_no_envelope` |
| Envelope or budget | advisory | `knos budget envelope FILE --fund N` prints the envelope before and after and refuses over its limit. It sends nothing, the workflow reads no envelope for this, and an envelope's figures are typed. The Balance's limits are what holds. | `tests/test_enforcement.py::test_a_plain_order_is_held_to_no_rate_card_and_no_envelope` |
| Supplier allow-list | workflow | prove.yml job `settle` and attest.yml job `attest`: `flow._cleared` refuses a payee that `payees` in `.knos/policy.yml` does not list. A neutral run in another repository (`flow.attest`) reads the buyer's file too and signs nothing for such a payee. | `tests/test_enforcement.py::test_a_neutral_run_refuses_a_payee_the_policy_file_does_not_list` |
| Terms fixed at funding | program | knos_pay FundOrderBalance (16): GitHub signs the amount, the mode, the terms' hash, the Balance and the work time in one audience; the hash of the terms is stored in the order, and PayOrder (17) takes only a token whose audience carries that hash (error 87). | `tests/test_pay_chain.py::test_every_wrong_proof_is_refused` |
| Deadline | program | knos_pay FundOrderBalance (16): the work time is 60 seconds to 90 days (error 81); after the deadline nothing pays the order and RefundOrder (22) returns the money to where it came from. | `tests/test_order_chain.py::test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before` |

<a id="tip"></a>

## A tip by comment

`/knos tip <amount>` on a merged pull request: the same job; FundBalance (3) opens a job that lasts one day.

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | knos_pay FundBalance (3): GitHub's token must name the Balance's owner as the repository's owner and the commenter as that owner or a spender its wallet listed (error 92). The workflow asks write access (`flow._can_write`) and, with procurement files, the requester role (`flow._gated`). `who_may_fund` in `.knos/policy.yml` is not asked for a tip. | `tests/test_pay2_chain.py::test_only_the_owner_and_the_listed_spenders_spend_a_balance` |
| Limit per order | program | knos_pay FundBalance (3): the Balance's cap for one job (error 93). `cap_per_order` in `.knos/policy.yml` is not asked for a tip. | `tests/test_pay2_chain.py::test_a_cap_per_job_is_enforced` |
| Limit per period | program | knos_pay FundBalance (3): the Balance's daily and total limits count the amount and the fee (error 100). `monthly_budget` in `.knos/policy.yml` is not asked for a tip. | `tests/test_controls.py::test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first` |
| Approver count | workflow | fund.yml job `command`: `flow._gated` asks `approvals.gate_order` for `tip:<pull request>`, as for a plain order. With no procurement file nothing more is asked. | `tests/test_enforcement.py::test_a_tip_is_held_to_the_approval_policy_too` |
| Rate card | outside | A tip is a gift for one merged pull request: no outcome is priced. |  |
| Envelope or budget | advisory | `knos budget envelope FILE --fund N` prints the envelope before and after and refuses over its limit. It sends nothing, the workflow reads no envelope for this, and an envelope's figures are typed. The Balance's limits are what holds. | `tests/test_enforcement.py::test_a_tip_is_held_to_the_approval_policy_too` |
| Supplier allow-list | workflow | prove.yml job `settle`: `flow._cleared` refuses a payee that `payees` in `.knos/policy.yml` does not list. A tip is a job, and no neutral run pays a job. | `tests/test_flow_orders.py::test_a_policy_that_names_payees_is_enforced_and_every_address_is_screened_before_a_payout` |
| Terms fixed at funding | program | knos_pay FundBalance (3): a tip's terms ask for nothing, their hash is stored in the job, and Pay (5) takes only a token that carries it (error 87). | `tests/test_pay_chain.py::test_every_wrong_proof_is_refused` |
| Deadline | program | knos_pay FundBalance (3): GitHub signs the work time (one day for a tip); after it Refund (7) returns the money. | `tests/test_pay2_chain.py::test_with_no_proof_by_the_deadline_the_money_goes_back_where_it_came_from` |

<a id="offer"></a>

## A standing offer

`/knos offer @vendor rate R budget B`: the same job; an order that pays one rate per accepted pull request.

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | knos_pay FundOrderBalance (16): GitHub's token must name the Balance's owner as the repository's owner and the commenter as that owner or a spender its wallet listed (error 92). The workflow asks write access, `who_may_fund`, and that the offer file's requester holds the requester role (`flow._gated`). | `tests/test_controls.py::test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first` |
| Limit per order | program | knos_pay FundOrderBalance (16): the Balance's cap for one order (error 93) holds the offer's budget, and PayOrder (17) pays one rate, signed in the order's options, per accepted pull request. | `tests/test_order_terms.py::test_a_standing_order_pays_its_rate_once_per_pull_request_until_less_than_one_rate_is_left` |
| Limit per period | program | knos_pay FundOrderBalance (16): the Balance's daily and total limits count the amount and the fee (error 100). An offer file's cap by period is one funding a period: the program holds a budget until its deadline, 90 days at most. | `tests/test_controls.py::test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first` |
| Approver count | workflow | fund.yml job `command`: `flow._gated` asks `approvals.gate`. An offer file must name this vendor, rate and cap, and the approvals its whole commitment needs must be in the log and still on the forge. | `tests/test_flow_wire17.py::test_a_standing_offer_funds_only_when_the_buyers_procurement_files_approve_it_and_with_none_nothing_changes` |
| Rate card | workflow | fund.yml job `command`: `flow._gated` asks `approvals.gate`. The comment's rate must be the price of the offer's outcome in the rate card the offer names, and the card must cite published terms by hash. | `tests/test_flow_wire17.py::test_a_standing_offer_funds_only_when_the_buyers_procurement_files_approve_it_and_with_none_nothing_changes` |
| Envelope or budget | advisory | `approvals.gate` reads the envelope the offer names and refuses one that is not sound. It does not compare the commitment with what the envelope has left: `knos budget offer FILE` does, and an envelope's figures are typed. | `tests/test_enforcement.py::test_an_offer_over_its_envelope_still_funds_once_it_is_approved` |
| Supplier allow-list | workflow | fund.yml job `command`: `flow._gated` asks `approvals.gate` (the offer file's `suppliers` must name the vendor), after `vendors` in `.knos/policy.yml` (`flow._order_plan`). The vendor's GitHub id is in the terms the order's hash covers. | `tests/test_procurement.py::test_the_gate_a_funding_workflow_can_ask` |
| Terms fixed at funding | program | knos_pay FundOrderBalance (16): GitHub signs the amount, the terms' hash and the options (the rate) in one audience; the hash of the terms is stored in the order, and PayOrder (17) takes only a token whose audience carries that hash (error 87). | `tests/test_pay_chain.py::test_every_wrong_proof_is_refused` |
| Deadline | program | knos_pay FundOrderBalance (16): the work time is 60 seconds to 90 days (error 81); after the deadline nothing pays the order and RefundOrder (22) returns the money to where it came from. The offer file's `starts` and `ends` are the workflow's (`approvals.gate`). | `tests/test_order_chain.py::test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before` |

<a id="topup"></a>

## A top-up

TopUp (23) adds to an open order. `/knos raise` only says how: a comment cannot sign for a wallet.

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | knos_pay TopUp (23): only the wallet that funded the order signs, or the wallet that opened the Balance it came from (errors 80 and 98). A comment cannot: `/knos raise` replies with how (`flow._order_word`). | `tests/test_enforcement.py::test_a_top_up_goes_past_the_balances_cap_and_limits_and_only_its_wallet_signs_it` |
| Limit per order | outside | TopUp checks one bound: the new whole amount is at most 100,000.00 (error 81). The Balance's cap for one order is not asked, so a top-up can take an order past it. Outside on purpose: the one wallet that may sign a top-up is the wallet that sets the cap. | `tests/test_enforcement.py::test_a_top_up_goes_past_the_balances_cap_and_limits_and_only_its_wallet_signs_it` |
| Limit per period | outside | TopUp does not count against the Balance's daily or total limit. Outside for the same reason: only the wallet that sets those limits can sign it. | `tests/test_enforcement.py::test_a_top_up_goes_past_the_balances_cap_and_limits_and_only_its_wallet_signs_it` |
| Approver count | outside | The wallet's signature is the approval. When the wallet is a multisig its threshold is the multisig's own rule, which Knos reads back (`knos audit show`) and does not enforce. | `tests/test_enforcement.py::test_a_top_up_goes_past_the_balances_cap_and_limits_and_only_its_wallet_signs_it` |
| Rate card | outside | No file of a repository is read on this route: the program sees accounts and signatures, never `.knos/`. |  |
| Envelope or budget | outside | No file of a repository is read on this route: the program sees accounts and signatures, never `.knos/`. Whoever owns an envelope adds a top-up to it by hand. |  |
| Supplier allow-list | outside | A top-up adds money to an order. Who that order pays is not changed by it. |  |
| Terms fixed at funding | program | knos_pay TopUp (23): it changes the amount and the fee and nothing else. The terms' hash stored at funding stays. | `tests/test_enforcement.py::test_a_top_up_goes_past_the_balances_cap_and_limits_and_only_its_wallet_signs_it` |
| Deadline | program | knos_pay TopUp (23): refused once the order's deadline has passed (error 83), and it never moves the deadline. | `tests/test_order_chain.py::test_top_up_adds_to_the_amount_and_the_fee_from_where_the_money_came` |

<a id="private"></a>

## A private order

`/knos fund` in a private repository, answered by its attestor's run of fund.yml job `command`.

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | knos_pay FundOrderBalance (16): the token names the attestor repository and who started its run; the Balance must list that account (error 92) and, when it lists repositories, that repository (error 92). The workflow asks that the list is there (`flow._listed_for`), write access in the private repository and `who_may_fund` in the attestor's policy. | `tests/test_controls.py::test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first` |
| Limit per order | program | knos_pay FundOrderBalance (16): the Balance's cap for one order (error 93), and an order holds 5.00 to 100,000.00 of its money (error 81). | `tests/test_controls.py::test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first` |
| Limit per period | program | knos_pay FundOrderBalance (16): the Balance's daily and total limits count the amount and the fee (error 100). | `tests/test_controls.py::test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first` |
| Approver count | workflow | fund.yml job `command` in the attestor: `flow._attestor_command` runs `flow._fund`, whose `flow._gated` asks `approvals.gate_order` of the private repository's own procurement files. | `tests/test_enforcement.py::test_a_private_order_is_held_to_the_approval_policy_of_its_own_repository` |
| Rate card | advisory | This names no rate card. `knos budget offer` and the console show a card's price; nothing compares this amount with one. A standing offer is not private yet. | `tests/test_enforcement.py::test_a_private_order_is_held_to_the_approval_policy_of_its_own_repository` |
| Envelope or budget | advisory | `knos budget envelope FILE --fund N` prints the envelope before and after and refuses over its limit. It sends nothing, the workflow reads no envelope for this, and an envelope's figures are typed. The Balance's limits are what holds. | `tests/test_enforcement.py::test_a_private_order_is_held_to_the_approval_policy_of_its_own_repository` |
| Supplier allow-list | workflow | prove.yml job `settle` in the attestor: `flow._attestor_settle` runs `flow._settle_one`, whose `flow._cleared` refuses a payee the attestor's `.knos/policy.yml` does not list. A private order is never neutral: no other run pays it. | `tests/test_flow_orders.py::test_a_policy_that_names_payees_is_enforced_and_every_address_is_screened_before_a_payout` |
| Terms fixed at funding | program | knos_pay FundOrderBalance (16), private: the order stores a hash of its salted scope and of its terms and nothing else, and PayOrder (17) takes only a token that carries it. | `tests/test_order_chain.py::test_a_private_order_stores_no_repository_no_issue_and_a_hash_of_its_terms` |
| Deadline | program | knos_pay FundOrderBalance (16): the work time is 60 seconds to 90 days (error 81); after the deadline nothing pays the order and RefundOrder (22) returns the money to where it came from. | `tests/test_order_chain.py::test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before` |

<a id="balance"></a>

## A Balance

OpenBalance (0), SetBalance (1), SetBalanceX (13), Withdraw (2): money a wallet sets aside for one GitHub owner.

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | knos_pay OpenBalance (0): any wallet opens a Balance for any GitHub owner, with its own money. SetBalance (1), SetBalanceX (13) and Withdraw (2): only the wallet that opened it signs (error 98), and Withdraw pays only a token account of that wallet. A comment spends a Balance only in test USDC, or when its wallet is bound to the commenter or to the repository's owner (`flow._ours`). | `tests/test_pay2_chain.py::test_unspent_money_goes_back_only_to_the_wallet_that_opened_the_balance` |
| Limit per order | program | knos_pay SetBalance (1): only the wallet that opened the Balance sets its cap and its spenders (error 98). | `tests/test_pay2_chain.py::test_only_the_wallet_that_opened_a_balance_changes_its_cap_and_spenders` |
| Limit per period | program | knos_pay SetBalanceX (13): only that wallet sets the daily limit, the total limit, the repositories and the workflows commit (error 98). Lowering a limit does not reset what was spent. | `tests/test_controls.py::test_only_the_wallet_that_opened_the_balance_can_send_what_budget_set_builds` |
| Approver count | outside | One wallet's signature opens, limits and withdraws. Two people over a Balance is a multisig as that wallet: its threshold is the multisig's rule. |  |
| Rate card | outside | No file of a repository is read on this route: the program sees accounts and signatures, never `.knos/`. |  |
| Envelope or budget | outside | An envelope is a file and a Balance is the money. Nothing ties one to the other: the Balance's limits are the ones that hold. |  |
| Supplier allow-list | outside | No supplier is paid on this route: Withdraw pays only the wallet that opened the Balance. |  |
| Terms fixed at funding | outside | A Balance has no terms: it is money set aside. Terms are fixed when an order is funded from it. |  |
| Deadline | outside | A Balance has no deadline. Its wallet withdraws unspent money at any time, paused or not. |  |

<a id="netted"></a>

## A netted release

`knos net`: small outcomes accumulate in a book both sides keep; one order pays their net.

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | The release is one order: knos_pay FundOrderBalance (16) or FundOrderWallet (15), held as the rows Funding by comment and Wallet funding say. Until it is funded nothing is set aside: the supplier carries the buyer's credit inside the period, up to the book's cap. | `tests/test_netting.py::test_a_thousand_outcomes_settle_as_one_release_on_the_programs_as_they_are` |
| Limit per order | advisory | Each outcome is under 20.00 and a period has a cap: `knos net add` refuses past either, in the book both sides keep. No program reads a line. The one release is held to the Balance's cap (error 93). | `tests/test_netting.py::test_an_outcome_is_added_once_in_any_period_and_never_past_the_cap` |
| Limit per period | advisory | The period's cap is the book's: `knos net add` refuses an outcome that would pass it, and no program reads the book. | `tests/test_netting.py::test_an_outcome_is_added_once_in_any_period_and_never_past_the_cap` |
| Approver count | advisory | No approval is asked while outcomes accumulate. The one release is a funding: by comment it is held as the row Funding by comment says, for the net amount. | `tests/test_netting.py::test_the_command_line_opens_adds_disputes_closes_and_states` |
| Rate card | advisory | An outcome's value is what its line in the book says. Nothing compares it with a rate card. | `tests/test_netting.py::test_the_command_line_opens_adds_disputes_closes_and_states` |
| Envelope or budget | advisory | The book's cap is not an envelope, and no envelope is read when outcomes are added or the period closes. | `tests/test_netting.py::test_the_command_line_opens_adds_disputes_closes_and_states` |
| Supplier allow-list | advisory | A book is between one buyer and one supplier, and its header names them. No program reads the header. | `tests/test_netting.py::test_the_command_line_opens_adds_disputes_closes_and_states` |
| Terms fixed at funding | program | The release's terms name the batch root, the three numbers and the pair; knos_pay stores their hash at funding and PayOrder (17) takes only a token that carries it. The link from the release to each line is a reader's comparison, never the program's. | `tests/test_netting.py::test_a_thousand_outcomes_settle_as_one_release_on_the_programs_as_they_are` |
| Deadline | program | The release is one order of knos_pay: the work time is 60 seconds to 90 days (error 81); after the deadline nothing pays the order and RefundOrder (22) returns the money to where it came from. When a period closes is the book's. | `tests/test_order_chain.py::test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before` |

<a id="advance"></a>

## An advance

Assign (24): a payee names the wallet that receives an order's payment, for money a third party pays now.

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | knos_pay Assign (24): the first time the payee's bound wallet signs; after that only the assignee can change it. The advancer's payment to the supplier is the advancer's own transfer, in the same transaction. | `tests/test_order_terms.py::test_a_payee_assigns_an_orders_payment_and_only_the_assignee_can_change_it` |
| Limit per order | outside | No buyer money moves: an advance is the advancer's own money, and the order's amount does not change. |  |
| Limit per period | outside | No buyer money moves, so no limit of the buyer's is spent. |  |
| Approver count | outside | The buyer is not asked. Assign changes which wallet receives a payment the buyer already funded, never whether or how much. What an advancer accepts is its own offer file (`knos advance offer`). |  |
| Rate card | outside | No file of a repository is read on this route: the program sees accounts and signatures, never `.knos/`. |  |
| Envelope or budget | outside | No file of a repository is read on this route: the program sees accounts and signatures, never `.knos/`. |  |
| Supplier allow-list | outside | The payee stays the account the order accepted. The receiving wallet was always the payee's to choose: Assign makes that choice for one order and stops the payee from taking it back. |  |
| Terms fixed at funding | program | knos_pay Assign (24): it records one wallet for one payee of one order. The amount and the terms' hash stay, and the order pays or refunds exactly as it would have. | `tests/test_advance.py::test_an_assignment_before_acceptance_pays_the_financier_at_acceptance_and_at_release_and_never_the_seller` |
| Deadline | outside | An assignment adds no deadline: the order's own stands. After it the funder is refunded and the advancer collects nothing, with no claim on chain. |  |

<a id="passkey"></a>

## The passkey relay

`/knos passkey-fund` and `knos-withdraw:`: a relay sends and pays for what a passkey signed (knos_passkey).

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | knos_passkey Fund and Withdraw: only a WebAuthn assertion by the wallet's own passkey over exactly this instruction, with the wallet's next nonce, checked by the secp256r1 precompile. The relay pays the fee and decides nothing. The money is the passkey holder's: no Balance, policy file or approval is asked. | `tests/test_passkey_chain.py::test_another_passkeys_signature_is_refused` |
| Limit per order | outside | The passkey spends what its wallet holds. Fund carries knos_pay's FundOrderWallet (15) whole, so the row Wallet funding holds; no cap of an organisation applies. |  |
| Limit per period | outside | A passkey wallet has no period: it spends what it holds. |  |
| Approver count | outside | The passkey's signature is the approval: one person, one device. |  |
| Rate card | outside | No file of a repository is read on this route: the program sees accounts and signatures, never `.knos/`. |  |
| Envelope or budget | outside | No file of a repository is read on this route: the program sees accounts and signatures, never `.knos/`. |  |
| Supplier allow-list | outside | A withdrawal goes to the token account the passkey signed, and a funding to the order it signed. No list is read. |  |
| Terms fixed at funding | program | knos_passkey Fund and Withdraw: the passkey signs the whole instruction (the amount, the destination, the mint, the terms), and a changed byte is refused. | `tests/test_passkey_chain.py::test_a_changed_amount_destination_or_mint_is_refused` |
| Deadline | program | knos_passkey Fund and Withdraw: one assertion works once (the nonce), and a funding's assertion names the last slot it can land in. The order's own deadline is the row Wallet funding. | `tests/test_passkey_chain.py::test_withdrawals_follow_one_another_and_none_can_be_sent_twice` |

<a id="direct"></a>

## A direct call by anyone

Any instruction, sent by any wallet: a relayer carrying a token, RefundOrder (22), Release (18).

| restriction | class | by what | test |
|---|---|---|---|
| Who may fund | program | Anyone may send any instruction of knos_pay. Money moves only on the signature of the wallet whose money it is, or on a token GitHub signed for this exact audience, verified by knos_oidc and used once (errors 84 to 87 and 91). A relayer carries a token and decides nothing. RefundOrder (22) and Release (18) pay only where the order already says. | `tests/test_pay_chain.py::test_nobody_can_claim_another_accounts_money` |
| Limit per order | program | knos_pay FundOrderBalance (16): the Balance's cap for one order (error 93), whoever carries the token. | `tests/test_controls.py::test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first` |
| Limit per period | program | knos_pay FundOrderBalance (16): the Balance's daily and total limits count the amount and the fee (error 100), whoever carries the token. | `tests/test_controls.py::test_limits_set_with_budget_set_are_enforced_by_the_program_and_budget_check_names_the_rule_first` |
| Approver count | advisory | `.knos/procurement/`: Read by the pinned workflow only. A token from a run that skipped it (a workflow file changed on the default branch) is refused by nothing but the Balance's own limits and its workflows pin (`X_WF_SHA`, error 86), which its wallet sets with `knos budget set --pin-workflows`. | `tests/test_enforcement.py::test_a_token_from_a_changed_workflow_is_stopped_only_by_the_balances_own_pin` |
| Rate card | advisory | `.knos/procurement/rate-cards/`: Read by the pinned workflow only. A token from a run that skipped it (a workflow file changed on the default branch) is refused by nothing but the Balance's own limits and its workflows pin (`X_WF_SHA`, error 86), which its wallet sets with `knos budget set --pin-workflows`. | `tests/test_enforcement.py::test_a_token_from_a_changed_workflow_is_stopped_only_by_the_balances_own_pin` |
| Envelope or budget | advisory | `.knos/procurement/envelopes/`: Read by the pinned workflow only. A token from a run that skipped it (a workflow file changed on the default branch) is refused by nothing but the Balance's own limits and its workflows pin (`X_WF_SHA`, error 86), which its wallet sets with `knos budget set --pin-workflows`. | `tests/test_enforcement.py::test_a_token_from_a_changed_workflow_is_stopped_only_by_the_balances_own_pin` |
| Supplier allow-list | advisory | `.knos/policy.yml` and the offer files: Read by the pinned workflow only. A token from a run that skipped it (a workflow file changed on the default branch) is refused by nothing but the Balance's own limits and its workflows pin (`X_WF_SHA`, error 86), which its wallet sets with `knos budget set --pin-workflows`. | `tests/test_enforcement.py::test_a_token_from_a_changed_workflow_is_stopped_only_by_the_balances_own_pin` |
| Terms fixed at funding | program | knos_pay: every funding stores the terms' hash, and the hash of the terms is stored in the order, and PayOrder (17) takes only a token whose audience carries that hash (error 87). A token works once (error 91). | `tests/test_pay2_chain.py::test_a_fund_token_works_once` |
| Deadline | program | knos_pay: the work time is 60 seconds to 90 days (error 81); after the deadline nothing pays the order and RefundOrder (22) returns the money to where it came from. RefundOrder is open to anyone and pays only the funder. | `tests/test_order_chain.py::test_an_order_goes_back_to_its_funder_after_the_deadline_and_not_before` |
