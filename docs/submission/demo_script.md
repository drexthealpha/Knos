# Demo (three minutes): the shot list

Seven shots. Every shot is a screen recording of the real thing on Solana devnet, in test USDC, with nothing
staged, so that each transaction shown can be found afterwards on the site's Numbers page
(https://drexthealpha.github.io/Knos/#network), which is read from the programs' own logs.

Two rules for the recording:

- **A shot whose feature is not marked as exercised on devnet in `docs/capabilities.json` on the day is cut, not
  staged.** The narration of the shots that remain is not changed to cover for it.
- A number that only the release run can give is a slot, `[[stat: name]]`.

Where each shot stands in `docs/capabilities.json` when this was written (the stage is the manifest's; the release
moves a line only with a devnet transaction):

| shot | capability | stage today | if it is not exercised on the day |
|---|---|---|---|
| A | `buyer_page`, `terms_templates`, `passkey_funder`, `passkey_fund_relay` | tested locally: a headless browser with a virtual passkey, and the local simulator | fund with the comment `/knos fund` instead (`fund_by_comment`), and say so |
| B | `check`, `pay_on_merge` | deployed on devnet | none needed once a transaction of the day is recorded |
| C | `receipt`, `work_orders` | tested locally | cut |
| D | `pay_on_merge`; `order_pay` for a work order | deployed; tested locally | show a bounty, not a work order |
| E | `single_use_tokens` | tested locally | show the closed bounty refusing the token, and say that is what it is |
| F | `statements`, `meter_batch`, `meter_seller_claim`, `refund`, `warranty_revert` | tested locally, but for `refund`, which is deployed | the refund only |
| G | `mainnet_check` | tested locally | it reads the chain and sends nothing: shown as it is |

One more shot exists in the tree and is not in the three minutes until it is exercised on devnet. **Auto-accept**
(`order_auto_accept`, `agent_tools`; tested locally): an order funded as auto on a black-box suite; an agent with
its own key finds it, takes it, submits a pull request after the local check passes, and is paid when the suite
passes, with no merge and no human step. If it is exercised by the day of recording it replaces shots B and C, with
this narration: "Nobody merged this. The buyer chose, at funding, to pay the first pull request that passes a suite
the author cannot see. The agent found the order, took it, and was paid." The challenge that goes with it
(`order_challenge`: a neutral failing run inside the warranty returns the holdback) is the alternative exception
of shot F.

Caption under the first shot, no narration: "Built during the hackathon: everything shown. Older work is listed in
docs/DISCLOSURE.md."

| shot | starts | ends | what it shows |
|---|---|---|---|
| A | (0:00) | (0:25) | a buyer sets the task, the budget and the acceptance terms from a template |
| B | (0:25) | (0:55) | a submission that claims success is refused, with the exact failed check |
| C | (0:55) | (1:30) | a valid one passes: artifact, policy, evaluator and evidence on one screen |
| D | (1:30) | (1:50) | the signed token pays on devnet |
| E | (1:50) | (2:05) | the same token is replayed and refused |
| F | (2:05) | (2:35) | buyer and seller compute the same statement, and an exception path |
| G | (2:35) | (3:00) | the offer and the roadmap |

## A. The buyer sets the terms (0:00, 25 seconds)

**On screen.** The site's funding form. The buyer picks a terms template, and the form fills: the task (an issue's
address), the budget, the checks that must pass, the paths that may change, the deadline. She changes one value.
The page shows what she will pay: the amount, and the fee on top. She funds it; the passkey prompt; the order's
account in the explorer and the log line that carries the hash of the terms.

**Narration.** A buyer who has to approve a supplier's invoice starts here. She picks a template, sets the budget
and the checks that decide whether the work is done, and funds the order. Those terms are hashed into the order
now. Nobody can change them after the work, not her and not the seller.

**Must be visible.** The terms in plain sentences before she funds. The same hash in the page and in the explorer.

## B. A submission that claims success is refused (0:25, 30 seconds)

**On screen.** A pull request for the task. Its description says "all tests pass". The check `test` is red at its
head commit. She merges it anyway. The workflow runs. Knos's comment on the pull request: not paid, the required
check `test` failed at this commit. The order on the site: still open, the money still in it.

**Narration.** This submission says the tests pass. They did not. She merges it all the same, and nothing is paid.
The refusal names the check that failed and the commit it failed at. The money has not moved.

**Must be visible.** The words of the claim, the name of the failed check, and the unchanged balance of the order.

## C. A valid one passes, with the evidence on one screen (0:55, 35 seconds)

**On screen.** A second pull request: `test` is green. She merges it. Then the receipt, on one screen, in its four
parts: the artifact (the head commit and its digest), the policy (the terms and their hash), the evaluator (the
workflow file, its pinned commit, the runner), the evidence (each named check with its conclusion, and the token
the forge signed, decoded: `repository_id`, `job_workflow_ref`, `job_workflow_sha`, `run_attempt`, and the `aud`
line that names the order, the head commit and the hash of the terms).

**Narration.** This one meets the terms. One screen says what was delivered, which policy judged it, who ran the
judgment, and the evidence. The forge signed which workflow ran, at which commit, in which repository. It did not
sign what the workflow read: that part is the pinned workflow's reading, and the receipt says so.

**Must be visible.** All four parts at once, without scrolling, and the line that says what the signature does not
cover.

## D. The signed token pays (1:30, 20 seconds)

**On screen.** Knos's comment with the payment's transaction. The explorer: the verifier program checking the RSA
signature, then the escrow paying the full amount to the seller's wallet, and the fee split between the relayer's
tip and Knos.

**Narration.** A Solana program checks the forge's signature itself and pays the seller the posted amount. The
buyer paid the fee on top. Nobody approved this payment after the merge.

**Must be visible.** The seller's balance before and after, and the two program names in the transaction.

## E. The same token is replayed and refused (1:50, 15 seconds)

**On screen.** A terminal. The pay token of shot D, unchanged, sent again. The program's refusal as it is printed:
this token was used already. The seller's balance: unchanged. The marker account for that token in the explorer.

**Narration.** Now the same signed token, sent a second time. It is refused. Every token leaves a marker, and no
instruction accepts a token whose marker exists.

**Must be visible.** The error as the program returns it, and the balance not moving.

## F. Both sides compute the same statement, and an exception (2:05, 30 seconds)

**On screen.** Two terminals side by side, labelled buyer and seller. Each runs the statement for the month from
its own ledger and the chain: the same totals, to the last unit. Then the exception. Either a refund: a second
order whose deadline has passed with no accepted work, and the transaction that returns the amount and the fee to
the buyer, with no token and no action by Knos. Or a revert: an order with a warranty, the merged change reverted
inside the period, and the holdback going back to the buyer. One of the two is shown; the caption names the other.

**Narration.** At the end of the month the buyer and the seller each compute the statement, from their own
records and the chain. They get the same number. And when something goes wrong there is a path fixed at funding:
an order that was never fulfilled returns to the buyer, fee included, with nobody's permission.

**Must be visible.** The two totals, equal. The refund or the returned holdback as a transaction.

## G. The offer and the roadmap (2:35, 25 seconds)

**On screen.** The price book on the site's Pricing page. Then three lines: count first, settle second, capital
third. Then `knos mainnet-check` with the gate that fails: no outside review.

**Narration.** The check is free. The count is sold first, because it needs no customer money on chain. Settlement
is second, capital third. What this does not show: it is devnet and test money, there is no outside review, one
person holds the keys behind a public 48-hour delay, and nobody has bought anything. Outside funders so far: 0.

**Must be visible.** The price book as printed in docs/MARKET.md, and the failing gate.
