# Demo (under three minutes, all screen)

One buyer, one work order, a refusal, a payment, a second order settled by the seller alone, a forgery refused, the
records, and what is not proven. Every scene is a screen recording of the real thing on Solana devnet, in test USDC,
with nothing staged, so that each transaction shown can be found afterwards on the site's Numbers page
(https://drexthealpha.github.io/Knos/#network), which is read from the programs' own logs. A number that only the
release run can give is a slot, `[[stat: name]]`. It is recorded after the upgrade of the escrow has executed, since
scenes 2 to 7 show work orders.

Caption under the first scene, no narration: "Built during the hackathon: everything shown. Older work is listed in
docs/DISCLOSURE.md."

## 1. The buyer's cost today (0:00, 20 seconds)

**On screen.** The site. The button "A claim that is false": a real pull request whose description says it passes
all CI, and the failed check at its latest commit. Then the Agent PR Index figure.

**Narration.** This is what a buyer of agent work pays for today: a person reading every pull request, because the
description cannot be trusted. In 826 repositories, the first agent pull request that said its tests pass had a
failed check in 147.

## 2. Fund a work order, with terms (0:20, 22 seconds)

**On screen.** A GitHub issue. The buyer types `/knos fund 20 checks: test` and sends it. Knos's reply: the amount in
escrow, the fee she pays on top, the terms in plain sentences, the deadline, and that the seller can settle after a
merge. Then the order's account in the explorer and the log line `knos3:terms`.

**Narration.** One comment funds a work order and names the check that must pass. She pays the fee on top, so the
seller receives the full amount. The terms are on chain now, and nothing changes them.

## 3. A submission that fails is refused, and told why (0:42, 20 seconds)

**On screen.** A pull request for the issue whose check `test` is red. She merges it anyway. The workflow runs.
Knos's comment on the pull request: not paid, the required check `test` failed at this commit. The order is still
open on the site.

**Narration.** This pull request does not meet the terms. She merges it all the same, and nothing is paid. The
comment says exactly why. The money has not moved.

## 4. The valid one is merged, and paid (1:02, 25 seconds)

**On screen.** A second pull request: `test` is green, and its author has commented `/knos address <address>`. She
merges it. Knos's comment follows with the payment's transaction. The explorer: the full amount to the author's
wallet, the fee split between the relayer's tip and Knos. Then the token GitHub signed, decoded: `repository_id`,
`job_workflow_ref`, `job_workflow_sha`, `event_name`, `run_attempt`, and the `aud` line that names the order, the
head commit and the hash of the terms.

**Narration.** This one passes. She merges it, and that is the last thing anyone does. A pinned workflow reads
GitHub's record and asks GitHub to sign what it found. The program checks the signature and pays. From merge to paid
took 24 seconds at the median.

## 5. The buyer deletes the workflow, and the seller still settles (1:27, 30 seconds)

**On screen.** A second order on another issue. The buyer deletes `.github/workflows/knos.yml`, and the commit that
removes it is shown. She merges the seller's pull request. No workflow runs in her repository. The seller's
terminal: `knos settle --neutral <pull request URL>`. The Actions tab of a repository the seller owns: `attest.yml`,
started by hand. The explorer: the payment, and the log line `knos3:settled` ending `judge=1`.

**Narration.** Now the case that used to cost the seller everything. The buyer removes the workflow and merges. Her
repository will never ask for the payment. So the seller asks. He runs the pinned workflow by hand in a repository
of his own. It reads GitHub's public record of the merge, GitHub signs that run, and the program pays.
The order allowed this from the day it was funded.

## 6. A forged token and a replayed one are refused (1:57, 18 seconds)

**On screen.** A terminal. The pay token of scene 4 with its payee changed: the verifier refuses the signature. The
same, unchanged token sent again: the escrow refuses it, the order is closed. Both refusals, as they are printed.

**Narration.** Change one character of a signed token and the verifier refuses it: it is no longer GitHub's. Send a
good token twice and the second pays nothing.

## 7. The receipt and the statement (2:15, 18 seconds)

**On screen.** `knos receipts --owner <buyer>`: one row per payment, with the payee, the amount, the fee, the terms'
hash and the transaction. `knos statement --seller <seller> --month 2026-10`. Then the same on the site, under
Records: "A statement for a month".

**Narration.** For the person who signs off the spend: a receipt for each payment and a statement for the month,
recomputed from the chain's own logs. Either side can run it.

## 8. What is not proven (2:33, 22 seconds)

**On screen.** `knos mainnet-check`: every gate with its evidence, and the one that fails, no outside review. Then
docs/SECURITY.md, "Known limits".

**Narration.** What this does not show. It is devnet and test money. No outside security firm has reviewed it, and
until one has, I can change these programs, through a multisig, after a public 48-hour delay. In a private
repository a buyer can still withhold. Outside funders so far: 0.
