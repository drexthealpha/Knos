# For the supplier: know the rules before you are refused

You did the work, or your agent did. This page is what Knos owes you before, during and after a verdict: the rules
said up front, every refusal in plain words, a way to contest one that costs you nothing, and your own copy of the
evidence. Money on devnet is test USDC.

## 1. Before you open a pull request: `knos preflight`

Run it in your checkout. It reads the order's terms and your change, and asks the network for nothing when you give
it the terms as a file.

```
knos preflight --terms terms.json            # the JSON of the order's `knos-terms:` line, or a file from terms/
knos preflight --issue acme/app#12           # reads the terms from the funded issue instead
knos preflight --terms terms.json --json     # the same report as data
```

It answers five things:

| It says | Where it comes from |
| --- | --- |
| Which paths are protected | the terms' `deny`; for an order paid on acceptance checks, also what the judge protects |
| Which checks are named | the terms' `checks`. They run on your pull request. Preflight cannot pass them for you |
| What your change touches that would be refused | each file, the refusal's code, its two sentences, and the exact line of the terms that says so |
| What is allowed and not counted | a test file you add. The judge runs the buyer's tests, so yours is welcome and decides nothing |
| `Ready`, or the list of fixes | exit code 0 only when ready |

What it does not do: it does not run the acceptance checks (it names the command that does), and it cannot know
whether the named checks will pass.

An agent asks the same question through the MCP server: the tool `knos_preflight` takes `path` and `terms` (or
`issue`) and returns the same report.

### What it remembers

Preflight recalls what was refused before under the same terms in this repository, and says so before you repeat it:

```
Remembered: 3 earlier submissions were refused for touching tests/conftest.py: your change touches it too.
```

It also remembers each preflight result, and `--by <login>` recalls your own record here (accepted, rejected,
appealed, overturned). All of it lives in the memory engine (sibyl-memory-client), looked up with the engine's own
search inside one category; there is no side file. With the engine absent, preflight works the same and says
`Memory is off`. `--no-memory` recalls and remembers nothing.

## 2. A refusal, in plain words

Every refusal has a code, one sentence saying what happened and one saying what to do. The command line and the
comments Knos writes read the same table, printed here from the module that holds it (`knos.ghwords.REFUSALS`). A
test fails when a refusal exists without its two sentences.

<!-- refusals: begin (scripts/supplier_docs.py) -->
| Code | What happened | What to do |
| --- | --- | --- |
| `judge.protected-path` | The change touches a path the judge protects. | Take that file out; add new tests as new files. |
| `judge.existing-test-edited` | The change edits or deletes a test that already existed. | Restore that test; put your own tests in a new file. |
| `judge.test-config` | The change edits a file that decides how tests run. | Restore that file; ask the buyer to change it. |
| `judge.terms` | The change touches the terms or the acceptance checks. | Take that file out; both were fixed at funding. |
| `judge.workflow` | The change touches a workflow under `.github/`. | Take that file out; ask the buyer to change it. |
| `judge.not-from-base` | The change touches a file the run reads from your copy. | Take that file out; ask the buyer to change it. |
| `judge.scripts` | The change edits the scripts of `package.json`. | Restore the scripts; ask the buyer to change them. |
| `judge.protected-test-edited` | The change edits a test that already existed. | Restore that test; put your own tests in a new file. |
| `judge.protected-test-deleted` | The change deletes a test that already existed. | Restore that test; put your own tests in a new file. |
| `judge.bad-issue` | The issue given to the judge is not an issue number. | Run the judge again with the issue's number. |
| `judge.no-bundle` | The default branch holds no acceptance checks for this issue. | Ask the buyer to restore `.knos/acceptance/<issue>/`. |
| `judge.runner` | The repository names a test runner Knos does not have. | Ask the buyer to fix `runner` in `.knos/proof.toml`. |
| `judge.image` | The judge's container image could not be pulled or run. | Run it again; nothing is held against you. |
| `judge.no-sandbox` | This machine has no sandbox to run your code in. | Run on Linux with setpriv and unshare, or in the workflow. |
| `judge.sandbox-python` | The sandbox user cannot run this Python. | Install knos where every user can reach it. |
| `judge.no-report` | The test run ended without writing a report. | Look for a crash or a timeout, then submit again. |
| `judge.sentinel` | The judge's own passing test did not run and pass. | Remove whatever changes which tests are collected. |
| `judge.canary` | The judge's own failing test did not fail. | Remove whatever makes every test pass. |
| `judge.no-acceptance-ran` | No acceptance check ran on your change. | Make sure your change does not break test collection. |
| `judge.acceptance-missing` | Acceptance checks that ran on the base did not run here. | Restore what those checks need to be collected. |
| `judge.acceptance-failed` | Your change does not pass the acceptance checks. | Read the named checks, fix the code, submit again. |
| `judge.not-fail-to-pass` | The acceptance checks already pass without your change. | Ask the buyer: the order has nothing left to accept. |
| `judge.fewer-tests` | Your change collects fewer tests than the base. | Restore the tests that no longer run. |
| `judge.pass-to-pass` | A test that passed before your change now fails. | Fix the regression the reason names. |
| `judge.repo-rule` | The change breaks a rule of the repository's CONTRIBUTING file. | Follow the rule and the line the reason names. |
| `judge.false-claim` | The description claims passing checks, and GitHub's record disagrees. | Fix the failed check, or correct the description. |
| `judge.merge-mode` | This order pays on a merge, not on acceptance checks. | Wait for a maintainer to merge. |
| `judge.bundle-changed` | The acceptance checks on the base are not the funded ones. | Ask the buyer to restore them, or to fund again. |
| `terms.check-failed` | A check the order names failed at your last commit. | Fix it and push; the newest commit is judged. |
| `terms.check-pending` | A check the order names has not finished. | Wait for it to finish, then ask again. |
| `terms.check-skipped` | A check the order names was skipped; skipped is not passed. | Make that check run on your pull request. |
| `terms.check-absent` | A check the order names did not run on your commit. | Push a commit that starts it, or ask a maintainer. |
| `terms.check-unreadable` | GitHub did not give the result of a named check. | Run it again; nothing is held against you. |
| `terms.denied-path` | The change touches a path the order forbids. | Take that file out of the change. |
| `terms.out-of-scope` | The change touches a file outside the order's paths. | Keep the change inside the listed paths. |
| `terms.files-unread` | GitHub did not list the changed files. | Run it again; nothing is held against you. |
| `who.payee` | Nobody can be named as the account to pay. | Comment `/knos mine` on the pull request. |
| `who.assigned` | The issue is reserved for, or assigned to, someone else. | Wait until the reservation lapses, or ask a maintainer. |
| `who.rejected` | A maintainer rejected this pull request for the order. | Ask the maintainer, or comment `/knos appeal <reason>`. |
| `who.issue` | The pull request does not close the funded issue. | Write `Closes #<issue>` in the description before the merge. |
| `who.unmerged` | A tip is paid only after the merge. | Wait for the merge, then ask again. |
| `who.unread` | GitHub did not give a fact the payment rests on. | Run it again; nothing is held against you. |
| `command.unknown` | The word after `/knos` is not a command. | Comment `/knos help` to list the commands. |
| `command.malformed` | The command was not written in its form. | Type it the way the reply shows. |
| `command.not_allowed` | This command belongs to someone else. | Use the command the reply offers instead. |
| `command.misplaced` | The command was written in the wrong place. | Comment it on the issue or pull request named. |
| `rerun.other` | The neutral judge's run was about another order or commit. | Start the neutral judge again for this pull request. |
| `rerun.failed` | The acceptance suite did not pass when the neutral judge ran it. | Read its reasons; appeal if they are wrong. |
| `rerun.no-trees` | The neutral judge's verdict does not name the two trees judged. | Start the neutral judge again. |
| `rerun.image` | The neutral judge did not run the suite in the funded image. | Start the neutral judge again on a runner with containers. |
| `rerun.not-black-box` | The neutral judge did not run your code black-box. | Start the neutral judge again. |
| `rerun.bundle-changed` | The acceptance checks at the base commit are not the funded ones. | Ask the buyer which commit holds the funded checks. |
| `rerun.cannot-run` | The neutral judge could not run on its machine. | Run it again; nothing is held against you. |
| `rerun.insufficient-evidence` | This run could not decide (insufficient evidence). | Run the workflow again; nothing is paid or held against you. |
| `appeal.nothing` | An accepted verdict leaves nothing to appeal. | Read `/knos status` for when the money moves. |
| `appeal.unjudged` | No verdict on this pull request is on record yet. | Comment it again once the pull request is settled. |
| `appeal.not-supplier` | Only the account that did the work can appeal. | Ask the pull request's author to comment it. |
| `appeal.no-reason` | The appeal gives no reason. | Comment `/knos appeal <reason>` with one sentence. |
| `appeal.open` | An appeal of this verdict is open already. | Wait for the neutral judge's run to end. |
| `appeal.closed` | This appeal has ended, and its verdict stands. | Open a new pull request to be judged again. |
| `pay.76` | The signing key is not active on chain yet. | Try again after its delay and the guardian's approval. |
| `pay.77` | The signing key has expired on chain. | Run the rotate workflow, then relay the token again. |
| `pay.78` | The signing key was revoked on chain. | Run the workflow again for a token from another key. |
| `pay.80` | An account is wrong, or a signature is missing. | Build the instruction again with this client. |
| `pay.81` | An amount, a time, the mode or the terms is outside limits. | Change the value to one the limits allow. |
| `pay.82` | This funder already has a job on this issue. | Raise or cancel the one that exists. |
| `pay.83` | The job is not in the state this step needs. | Comment `/knos status`, then act on what it says. |
| `pay.84` | The signed token is not verified, expired, or not GitHub's. | Start a new run for a new token. |
| `pay.85` | The token's claims do not allow this action. | Comment again; a re-run of a job never counts. |
| `pay.86` | The token comes from another workflow than the order pinned. | Run the workflow the order names. |
| `pay.87` | The token's audience does not match this action. | Start a new run for this action. |
| `pay.88` | A destination account is wrong, or the payee has no wallet. | Bind a wallet with `knos claim`, then settle again. |
| `pay.89` | This instruction works on a devnet build only. | Use devnet. |
| `pay.90` | The faucet serves each repository once a minute. | Wait a minute and comment again. |
| `pay.91` | The token is not newer than the last one used. | Comment again for a new token. |
| `pay.92` | This comment cannot spend that balance. | Ask the balance's wallet to list you as a spender. |
| `pay.93` | The amount is more than the balance allows for one job. | Fund less, or ask its wallet to raise the limit. |
| `pay.94` | The balance does not hold that much. | Add money to it, or fund less. |
| `pay.95` | This mint cannot be used here. | Use a mint that cannot block or tax a transfer. |
| `pay.96` | New funding is paused. | Wait; payments, refunds and withdrawals go on. |
| `pay.97` | Only the guardian can pause. | Sign with the guardian's key. |
| `pay.98` | The balance exists already, or the signer did not open it. | Sign with the wallet that opened it. |
| `pay.99` | A faucet balance cannot be withdrawn. | Spend it on test orders. |
| `pay.100` | The balance's limit for a day or in total is reached. | Fund less, or ask its wallet to raise the limit. |
| `pay.101` | This order exists already. | Fund it under another seq. |
| `pay.102` | Only the fee owner sets a plan. | Sign with the fee owner's key. |
| `pay.103` | The order is standing and also has a holdback. | Fund a new order with one of the two. |
| `pay1.80` | An account in the instruction is wrong. | Build the instruction again with this client. |
| `pay1.81` | The terms are not what the job was funded with. | Send the terms the funding comment recorded. |
| `pay1.82` | The job exists already, or the account is another job. | Raise or cancel the one that exists. |
| `pay1.83` | The job is not in the state or time this needs. | Comment `/knos status`, then act on what it says. |
| `pay1.84` | The signed token is not verified, expired, or not GitHub's. | Start a new run for a new token. |
| `pay1.85` | The token's claims do not allow this action. | Comment again; a re-run of a job never counts. |
| `pay1.86` | The token comes from another workflow than the job pinned. | Run the workflow the job names. |
| `pay1.87` | The token's audience does not match this action. | Start a new run for this action. |
| `pay1.88` | The payee's account or the fee account is wrong. | Bind a wallet with `knos claim`, then settle again. |
| `pay1.89` | This instruction works on devnet only. | Use devnet. |
| `pay1.90` | A repository is funded once a minute. | Wait a minute and comment again. |
| `pay1.91` | Nothing is due on this job. | Comment `/knos status` to see what was paid. |
| `oidc.64` | The token is longer than the verifier takes. | Start a new run; shorten the audience if you set it. |
| `oidc.65` | The signature is not as long as its key. | Start a new run for a new token. |
| `oidc.67` | A verifier account is wrong, or another run moved it. | Send the token again. |
| `oidc.68` | The signing key is not ready on chain. | Wait for the key's rotation, then send again. |
| `oidc.69` | Another run moved this token's account. | Send the token again. |
| `oidc.70` | The signature is not the issuer's. | Start a new run for a new token. |
| `oidc.71` | The token is not signed with RS256. | Use an issuer that signs with RS256. |
| `oidc.72` | The token's issuer is not the key's issuer. | Send the token with its own issuer's key. |
| `oidc.73` | The chain does not trust this signing key. | Run the rotate workflow, then send again. |
| `oidc.74` | The key's attestation is not the rotate workflow's. | Run the rotate workflow in the attester's repository. |
| `oidc.75` | The key's attestation has expired. | Run the rotate workflow again. |
| `meter.61` | The token's claims are not a JSON object. | Start a new run for a new token. |
| `meter.62` | A claim the meter reads appears twice in the token. | Use an issuer that writes each claim once. |
| `meter.63` | A claim the meter reads is missing from the token. | Run the workflow the credits pin. |
| `meter.76` | The signing key is not active on chain yet. | Try again after its delay and the guardian's approval. |
| `meter.77` | The signing key has expired on chain. | Run the rotate workflow, then relay the token again. |
| `meter.78` | The signing key was revoked on chain. | Run the workflow again for a token from another key. |
| `meter.110` | An account is wrong, or a signature is missing. | Build the instruction again with this client. |
| `meter.111` | The owner, the commit, the rate or the tier is outside limits. | Change the value to one the limits allow. |
| `meter.112` | This is not a credits account the signer opened. | Sign with the wallet that opened the credits. |
| `meter.113` | The signed token is not verified, expired, or not GitHub's. | Start a new run for a new token. |
| `meter.114` | The token is from a re-run, or another kind of runner. | Start a new run on GitHub's own runner. |
| `meter.115` | The token is not from the workflow commit the credits pin. | Open the credits again to pin this commit. |
| `meter.116` | The token's audience is not an evaluation's. | Run the workflow with kind `eval`. |
| `meter.117` | The run was not in a repository of the named buyer. | Run it in a repository the buyer owns. |
| `meter.118` | The credits do not hold that much. | Add money to the credits, then send this again. |
| `meter.119` | This mint cannot be used for credits. | Use Circle's USDC. |
| `meter.120` | The fee account or the destination account is wrong. | Build the instruction again with this client. |
| `meter.121` | Only the fee owner sets a plan. | Sign with the fee owner's key. |
| `meter.122` | The meter does not count tokens signed by this kind of key. | Use a key of a public issuer. |
| `meter.123` | This mark cannot be closed by this signer. | Sign with the wallet the mark names. |
| `meter.124` | This mark cannot be closed yet. | Send this again after the time the mark names. |
| `meter.125` | This batch is not the ledger's next one. | Read `next_seq` from the ledger and send that batch. |
| `meter.126` | The batch's counts are outside what a batch may hold. | Send 1 to 100,000 evaluations for this month or the last. |
| `passkey.110` | An account in the instruction is wrong. | Build the instruction again with this client. |
| `passkey.111` | That is not a compressed P-256 public key. | Give the 33 bytes the passkey reported. |
| `passkey.112` | That account is not a passkey wallet. | Open the wallet first. |
| `passkey.113` | The passkey's signature check is not right before the withdrawal. | Build both instructions with this client. |
| `passkey.114` | The signature is another passkey's. | Sign with the passkey that opened this wallet. |
| `passkey.115` | The signed message is not what the passkey signed. | Sign again and send what the device returned. |
| `passkey.116` | The device did not report that a person was present. | Sign again and confirm on the device. |
| `passkey.117` | The client data is not a passkey signature's. | Sign again with the page's own request. |
| `passkey.118` | The passkey signed for another withdrawal or funding. | Sign again for this one. |
| `passkey.119` | The nonce is not the wallet's next one. | Read the wallet and sign again. |
| `passkey.120` | This mint cannot be withdrawn. | Use a mint the program accepts. |
| `passkey.121` | The signature's s is in the upper half. | Send n minus s, as this client's builders do. |
| `passkey.122` | The source is not this wallet's token account. | Name the wallet's own account of this mint. |
| `passkey.123` | The slot is past the expiry the passkey signed for. | Sign again. |
| `passkey.124` | The funding instruction is not this deployment's. | Build the funding with this client. |
| `unknown` | Knos has no plain words for this refusal yet. | Open an issue on Knos and quote the reason. |
<!-- refusals: end -->

`pay`, `pay1`, `oidc`, `meter` and `passkey` codes are the programs' own error numbers. A refusal with no row is
said as `unknown`, never guessed.

## 3. Contesting a verdict: `/knos appeal <reason>`

Comment it on your pull request, or run `knos appeal "<reason>" --repo owner/name --pull N --by <your login>`.

1. The verdict becomes **disputed**. Who appealed, when and why are recorded.
2. The money stays where the order's terms put it: in escrow, until the appeal ends or the order's deadline.
3. The neutral judge runs the funded acceptance checks again, itself, on a runner the buyer does not configure
   (`knos settle --neutral <pull request URL>`, or knos-attest.yml by hand with kind `pay`).
4. The appeal ends **accepted** (the rejection is overturned) or **rejected** (it stands), with the reason in the
   words of the table above. A judge that could not run decides nothing: the verdict stays disputed and it is asked again.

An order paid on a merge has no suite to run again. The arbiter the order names rules instead (kind `rule`).

An appeal never costs the supplier anything, whatever its outcome, and its re-execution is not billed to them. Only
the account that did the work can appeal, and an accepted verdict leaves nothing to appeal. `knos appeal --out FILE`
writes the record for you to keep; `knos appeal --record <login> --repo owner/name` prints a supplier's record.

## 4. Your own copy of the evidence: `knos keep`

```
knos keep <order address or paying transaction> --out my-copy --by <your login>
```

It writes `evidence.bundle.tar` (what `knos bundle make` writes: the receipt, the signed token, the key that verified
it, the terms, the check conclusions), `supplier.json` (what memory holds of your preflights and appeals here, and
your record) and `REFUSALS.md`. `knos bundle verify my-copy/evidence.bundle.tar` checks the bundle offline, with
nobody's help.

## What is not here yet

- The workflow does not act on `/knos appeal` until the comment parser and the workflow call `knos.appeal` (the
  state machine and its record are in place and tested).
- The judge's refusals reach the supplier's memory when the workflow records them with
  `knos.proof.history.refused`; until then preflight recalls only what this machine saw.
