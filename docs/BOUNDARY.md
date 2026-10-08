# The enterprise spending boundary

What stops an organisation's money, and what only says so. The cell-by-cell answer is
[ENFORCEMENT.md](ENFORCEMENT.md) (rows *Enterprise vault, by vote*, *Enterprise vault's Balance* and *A Squads
allowance*); this page says it for the people who sign. Devnet only: the money in every test is test USDC.

## The shape

1. **The money is in a Squads v4 vault.** Squads v4 (`SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf`) is Squads
   Labs' multisig program; Knos changes nothing in it. Squads lists its audits and two formal verifications
   ([security](https://docs.squads.so/main/basics/security)) and says nobody, Squads Labs included, can change the
   mainnet program since November 2024. The devnet program still has an upgrade authority (read from its ProgramData account), so the
   tests pin its bytes (`scripts/squads_program.py`).
2. **`knos boundary plan .knos/procurement/policy.yaml`** turns the approval policy, with
   `.knos/procurement/boundary.yaml` (each account's signing key, the config authority, the time lock, the
   vault's Balance, any allowance), into the vault's settings:
   - requesters get **Initiate** only: they propose and cannot vote or execute;
   - approvers and finance get **Vote** (and **Execute**, unless `executors` names other keys);
   - the **threshold** is the most votes any amount of the policy needs;
   - a **time lock** between the last vote and execution (at most 7,776,000 seconds,
     [`MAX_TIME_LOCK`](https://github.com/Squads-Protocol/v4/blob/main/programs/squads_multisig_program/src/state/multisig.rs));
   - a **config authority** that is nobody's member key. In a "controlled" multisig only that key changes
     members, threshold, time lock or spending limits, and members cannot propose such a change at all. Make it
     a board's own multisig vault.
   The plan refuses what Squads could not hold: a person who both requests and approves (Squads lets a
   proposal's creator vote), two accounts on one key, a config authority that is also a member.
3. **The limits a requester meets are a knos_pay Balance the vault opened.** `/knos fund` spends it as before;
   knos_pay refuses an order over its cap, a day or a total over its limits, an unlisted spender and an
   unpinned workflow. Only the vault, by vote, changes them or withdraws.
4. **An approval covers one commitment.** `knos boundary bind` prints an approval request: the sha256 of the
   repository, issue, sequence, funder, terms hash, policy hash, amount, payee and expiry. Approvers comment
   `/knos approve order:<digest>`. `boundary.gate_bound` refuses that approval for another order, after its
   expiry, under a changed policy, for another payee or another amount, each in its own sentence.
5. **A budget is reserved before work starts.** On chain, a funding moves the money from the vault into the
   order when it executes, and the token program refuses what the vault does not hold: two approved fundings
   cannot both take the last of it. Before that, `knos boundary reserve` holds part of a budget when a request is
   approved, in one SQLite transaction that takes the write lock first: two writers never both take the last of
   it.

## Hard controls, and for whom

| What | Enforced by | Binds |
|---|---|---|
| Nothing leaves the vault short of the threshold | Squads v4 (VaultTransactionExecute, ProposalApprove) | everyone, members included |
| A requester cannot vote or execute | Squads v4 permissions | requesters |
| Time lock after the last vote | Squads v4 | everyone |
| Policy changes only by the config authority | Squads v4 (controlled multisig) | every member |
| Cap per order, limits per day and in all, spenders, workflow pin | knos_pay FundOrderBalance on the vault's Balance | whoever funds by comment |
| The vault cannot spend what it does not hold | the token program, inside knos_pay's funding | everyone |
| An allowance's amount, period, keys and destinations | Squads v4 SpendingLimitUse | the allowance's keys |

## Advisory, and why

- **Each holder's own limit and dates, and the self-approval limit.** Squads keeps no dates or per-person
  limits. A requester's key cannot vote at all, which is stricter than the self-approval limit.
- **Finance as a separate signature, and tiers by amount.** Squads counts votes, not roles, and has one
  threshold: every vault transaction needs the policy's highest step.
- **Rate cards and envelope files.** Nothing on chain reads a file.
- **The bound approval in the workflow.** `boundary.gate_bound` and `boundary.payee_allowed` are code and
  tests; the funding and payment workflows do not ask them yet.
- **The reservation file.** It is the buyer's own SQLite file; the chain does not read it.

## Allowances loosen, they do not cap

A Squads spending limit lets its keys move up to an amount per day, week, 30 days or once, to listed
destinations, **without a vote**
([`spending_limit.rs`](https://github.com/Squads-Protocol/v4/blob/main/programs/squads_multisig_program/src/state/spending_limit.rs)).
A threshold-approved transaction is not limited by it. A destination is the owner of the receiving token
account, and every knos_pay Balance and order has the same owner, so an allowance cannot be narrowed to one
Balance. The plan adds an allowance only when the boundary file asks for one, and points it at a supplier's own
wallet.

## Outside: a person's own wallet

A wallet funding an order with its own money is outside the boundary on purpose: it is that person's money, and
no policy of an organisation can bind it. The boundary covers money the organisation put in its vault.

## What the tests show

`tests/test_boundary.py` runs the deployed Squads v4 build in the simulator beside the test build of knos_pay
(`python scripts/squads_program.py fetch` first; skipped without it): a requester's vote refused, one vote of two
executes nothing, the time lock holds, a vault cannot fund past what it holds, an allowance refused over its
amount, to another destination or by another key, a member cannot change the threshold, and a Balance the vault
opened changes only by its vote. `tests/test_squads_fund.py` sends the instruction `scripts/squads_fund.mjs`
prints through the same Squads build. No round on the public cluster has run a vault planned by `knos boundary`.
