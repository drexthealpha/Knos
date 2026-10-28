# For the supplier: know the rules before you are refused

You did the work, or your agent did. This page is what Knos owes you before, during and after a verdict: the rules
said up front, every refusal in plain words, a way to dispute one that costs you nothing, and your own copy of the
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
| Which paths are protected | the terms' `deny`; for an order paid on acceptance checks, also what the referee protects |
| Which checks are named | the terms' `checks`. They run on your pull request. Preflight cannot pass them for you |
| What your change touches that would be refused | each file, the refusal's code, its two sentences, and the exact line of the terms that says so |
| What is allowed and not counted | a test file you add. The referee runs the buyer's tests, so yours is welcome and decides nothing |
| `Ready`, or the list of fixes | exit code 0 only when ready |

What it does not do: it does not run the acceptance checks (it names the command that does), and it cannot know
whether the named checks will pass.

An agent asks the same question through the MCP server: the tool `knos_preflight` takes `path` and `terms` (or
`issue`) and returns the same report.

### What you are owed before you start

Preflight also reads the terms for four things a supplier is owed, and prints each as held, LACKED or not checked,
with how it is enforced. `program` means a check inside the payment program; `workflow` means a job of the pinned
workflow; `advisory` means a file or a command says so and nothing stops the other side.

<!-- protections: begin (scripts/supplier_docs.py) -->
| You are owed | How | Enforced by | When the terms lack it, preflight says |
| --- | --- | --- | --- |
| Fixed criteria | Terms are fixed when the order is funded. | program | These terms name no check and no acceptance suite: the only criterion is that the buyer merges, for any reason or none. |
| Acceptance deadline | Passing work is paid without a merge. | program | These terms have no acceptance deadline: the buyer can wait forever, and at the order's deadline the money goes back to the buyer. |
| No arbitrary rejection | A rejection has a reason and a free appeal. | workflow | These terms let the buyer reject by not merging, and name nobody to appeal to: an appeal would be recorded and decide nothing. |
| Predictable payment | The order is funded before work starts. | program | Not checked from a terms file: an order holds its whole price from funding. Read a funded one with `--issue`. |
| Predictable payment, netted work | Netted work is covered by a bound reserve. | advisory | This work is netted with no reserve bound: you carry the buyer's credit until the period closes. |
<!-- protections: end -->

```
knos preflight --terms terms.json --strict            # exit 1 when the terms lack one, even if your change is ready
knos preflight --terms terms.json --strict --auto     # the order pays passing work without a merge (`/knos fund ... auto`)
knos preflight --terms terms.json --arbiter ruth      # the order names an arbiter for an appeal
knos preflight --terms terms.json --netted --reserve  # netted work, in a period bound to a funded reserve
```

Three things an order's short terms (at most 600 bytes) do not carry are told to preflight, because the order's options carry
them: whether passing work is paid without a merge (`--auto`), who the arbiter is (`--arbiter`), and whether netted work has
a reserve (`--netted --reserve`).

A Knos Terms 3 document given as `--terms` supplies its deadline, its appeal window and its arbiter itself. What preflight
was not told it does not assume: an acceptance deadline nobody confirmed is printed as lacked.

What these four do not give you. The appeal is free and recorded, and nothing forces the neutral run or the arbiter
to answer: with no verdict by the order's deadline the money goes back to the buyer ([DISPUTES.md](DISPUTES.md)). A
cancelled order's deadline moves to at most 7 days away, and an acceptance inside that notice still pays
([SECURITY.md](SECURITY.md)).

A reserve for netted work is kept by the period's book, not by the program.

### What it remembers

Preflight recalls what was refused before under the same terms in this repository, and says so before you repeat it:

```
Remembered: 3 earlier submissions were refused for touching tests/conftest.py: your change touches it too.
```

It also remembers each preflight result, and `--by <login>` recalls your own record here (accepted, rejected, appealed, overturned). All of it
lives in Sibyl Labs' memory engine, a local database (`sibyl-memory-client`), looked up with the engine's own search inside one category;
there is no side file. With the engine absent, preflight works the same and says `Memory is off`.

`--no-memory` recalls and remembers nothing.

## 2. A refusal, in plain words

Every refusal has a code, one sentence saying what happened and one saying what to do. The command line and the
comments Knos writes read the same table, printed here from the module that holds it (`knos.ghwords.REFUSALS`). A
test fails when a refusal exists without its two sentences.

<!-- refusals: begin (scripts/supplier_docs.py) -->
| Code | What happened | What to do |
| --- | --- | --- |
| `judge.protected-path` | The change touches a path the referee protects. | Take that file out; add new tests as new files. |
| `judge.existing-test-edited` | The change edits or deletes a test that already existed. | Restore that test; put your own tests in a new file. |
| `judge.test-config` | The change edits a file that decides how tests run. | Restore that file; ask the buyer to change it. |
| `judge.terms` | The change touches the terms or the acceptance checks. | Take that file out; both were fixed at funding. |
| `judge.workflow` | The change touches a workflow under `.github/`. | Take that file out; ask the buyer to change it. |
| `judge.not-from-base` | The change touches a file the run reads from your copy. | Take that file out; ask the buyer to change it. |
| `judge.scripts` | The change edits the scripts of `package.json`. | Restore the scripts; ask the buyer to change them. |
| `judge.protected-test-edited` | The change edits a test that already existed. | Restore that test; put your own tests in a new file. |
| `judge.protected-test-deleted` | The change deletes a test that already existed. | Restore that test; put your own tests in a new file. |
| `judge.bad-issue` | The issue given to the referee is not an issue number. | Run the referee again with the issue's number. |
| `judge.no-bundle` | The default branch holds no acceptance checks for this issue. | Ask the buyer to restore `.knos/acceptance/<issue>/`. |
| `judge.runner` | The repository names a test runner Knos does not have. | Ask the buyer to fix `runner` in `.knos/proof.toml`. |
| `judge.image` | The referee's container image could not be pulled or run. | Run it again; nothing is held against you. |
| `judge.no-sandbox` | This machine has no sandbox to run your code in. | Run on Linux with setpriv and unshare, or in the workflow. |
| `judge.sandbox-python` | The sandbox user cannot run this Python. | Install knos where every user can reach it. |
| `judge.no-report` | The test run ended without writing a report. | Look for a crash or a timeout, then submit again. |
| `judge.sentinel` | The referee's own passing test did not run and pass. | Remove whatever changes which tests are collected. |
| `judge.canary` | The referee's own failing test did not fail. | Remove whatever makes every test pass. |
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
| `terms.check-failed` | A check the order names failed at your last commit. | Fix it and push; the newest commit is checked. |
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
| `rerun.other` | The neutral referee's run was about another order or commit. | Start the neutral referee again for this pull request. |
| `rerun.failed` | The acceptance suite did not pass when the neutral referee ran it. | Read its reasons; appeal if they are wrong. |
| `rerun.no-trees` | The neutral referee's verdict does not name the two trees checked. | Start the neutral referee again. |
| `rerun.image` | The neutral referee did not run the suite in the funded image. | Start the neutral referee again on a runner with containers. |
| `rerun.not-black-box` | The neutral referee did not run your code black-box. | Start the neutral referee again. |
| `rerun.bundle-changed` | The acceptance checks at the base commit are not the funded ones. | Ask the buyer which commit holds the funded checks. |
| `rerun.cannot-run` | The neutral referee could not run on its machine. | Run it again; nothing is held against you. |
| `rerun.insufficient-evidence` | This run could not decide (insufficient evidence). | Run the workflow again; nothing is paid or held against you. |
| `appeal.nothing` | An accepted verdict leaves nothing to appeal. | Read `/knos status` for when the money moves. |
| `appeal.unjudged` | No verdict on this pull request is on record yet. | Comment it again once the pull request is settled. |
| `appeal.not-supplier` | Only the account that did the work can appeal. | Ask the pull request's author to comment it. |
| `appeal.no-reason` | The appeal gives no reason. | Comment `/knos appeal <reason>` with one sentence. |
| `appeal.open` | An appeal of this verdict is open already. | Wait for the neutral referee's run to end. |
| `appeal.closed` | This appeal has ended, and its verdict stands. | Open a new pull request to be checked again. |
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
2. The money stays where the order's terms put it: held, until the appeal ends or the order's deadline.
3. The neutral referee runs the funded acceptance checks again, itself, on a runner the buyer does not configure
   (`knos settle --neutral <pull request URL>`, or knos-attest.yml by hand with kind `pay`).
4. The appeal ends **accepted** (the rejection is overturned) or **rejected** (it stands), with the reason in the
   words of the table above. A referee that could not run decides nothing: the verdict stays disputed until someone starts the neutral referee again.

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

## 5. For your finance lead: when you are paid

The supplier page of the site has a view for the person who books the money: paste the funding comment (or the
order's address) and it reads the order's own account on devnet, with no wallet.

It shows four rows: what is funded (with the funding transaction), the acceptance window counting down, how to appeal
and who decides, and the payment date (with a holdback, the part kept back and the day it is released).

[COMPANIES.md](COMPANIES.md#statements), section 6, says what each row is read from.

## What is not here yet

- `/knos appeal` is recorded by the workflow, and nothing starts the neutral run for you: you, the buyer or anyone
  starts it (section 3).
- No order's options are read by `knos preflight` from the chain: `--auto`, `--arbiter` and `--netted --reserve` are
  told to it, and what is not told is printed as lacked or not checked.
- The referee's refusals reach the supplier's memory when the workflow records them with
  `knos.proof.history.refused`; until then preflight recalls only what this machine saw.

## Collecting a held payout

A merged pull request pays the address bound to its author's GitHub account. With none bound, knos_pay holds the
money for that account, and the reply on the pull request links to `#payee=<login>` on the site (web/payee.js).

### What the page does

1. Reads what is held for the login: held jobs (their amount less the job fee) and held orders (what they have not
   paid yet), found on devnet by the account's numeric GitHub id.
2. Makes a passkey in the browser (WebAuthn, P-256: the same kind of key a phone uses to sign in to a website). Its address is a knos_passkey account: no seed phrase, no
   wallet app. The address is copied. The Get paid page (`#claim`) withdraws from the same address later.
3. Gives one link at a time: GitHub's new-repository form filled in (owner, name `knos-claim`, public, empty) while
   that repository does not exist; then GitHub's new-file page in it with the claim workflow filled in (examples/knos-claim.yml,
   the same file as [`templates/knos-claim`](../../templates/knos-claim)); then the claim workflow's page. No template
   repository is involved since 0.3.31.
4. Check reads the account's Bind on devnet and says whether it names this passkey's address. The relay then sends
   what was held.

The page signs and sends nothing. It reads api.github.com and Solana devnet, only when opened.

### Clicks to a first payout

| | Before (docs, wallet app) | Now (`#payee`) |
| --- | --- | --- |
| Address | install a wallet app; create a wallet and write down its seed phrase; copy its address (3) | Make a passkey; confirm on the device (2; the address is copied) |
| Repository | open the template; Use this template; Create a new repository; type the name; Create repository (5) | the page's link; Create repository; the page's second link; Commit changes (4) |
| Bind | Actions; knos claim; Run workflow; paste the address; Run workflow (5) | the page's link; Run workflow; paste the address; Run workflow (4) |
| Total | 13 | 10 (4 when the repository exists already) |

Counted on the screens as `web/payee.js` `CLICKS` lists them; tests/web/payee.mjs checks the page shows 13 and 10.
It was 8 while a template repository put the file in; adding the file by its own link costs two clicks and keeps
everything in one repository.

### Why it is not one click

The deployed knos_pay (2.2 since 9 October 2026; the rule is unchanged since Knos 0.3.12) takes a Bind token only from the pinned claim workflow,
in the account's own repository named `knos-claim`, in a run its owner started by hand (`workflow_dispatch`, first attempt):
`programs-v2/knos_pay/src/pay.rs`, `bind`. A push does not count, not even the commit that adds the workflow file.

That is deliberate: GitHub's new-repository form can be filled in from a link ([query
parameters](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)), so a push could carry an
address the link's author chose, made with the owner's click. The address must be the run's input, pasted by its owner. So the claim workflow
keeps `workflow_dispatch` as its only trigger.

A push workflow that starts the claim workflow with `GITHUB_TOKEN` would run (GitHub lets `GITHUB_TOKEN` create
`workflow_dispatch` runs: [triggering a workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)),
but its address would come from the repository, which is the hole above. Knos does not do it.

### What a program change would need (not made)

Fewer clicks safely needs an address that GitHub shows the owner typed, from somewhere a link cannot fill. A comment
on an existing issue is one: GitHub fills a new issue's body from a link but not a comment box.

A new knos_pay instruction could take a bind token from a pinned Knos workflow on `issue_comment` (created, not
edited), with `actor_id` the commenter, carrying `knos2:bind:<address>` from the comment. The payee would then make a
passkey, paste `/knos address <address>` as a comment on the pull request and press Comment: 4 clicks, no repository.

That is a program upgrade (multisig, public 8-day delay) and has not been built.

## The supplier's kit: a public record, a badge, one line to install, a receipt for the invoice

**Knos carries research across the valley of death: see who wants it and where, then get paid only on proof.**

The party whose work is rated (an agent builder, an agency, a vendor) gets four things from Knos and pays for none of
them. The buyer still pays ([PRICING.md](../PRICING.md)); the rated party never pays, and a record cannot
be bought or changed for money.

One limit, first: Knos wrote these records and nobody outside Knos has reviewed them.

| what | command | what it writes |
|---|---|---|
| the record | `knos record build <supplier>` | `docs/records/<slug>.json`, and its badge beside it |
| the badge | `knos badge record <slug>` | an SVG, and the Markdown line that links it to the record's page |
| the install | one `uses:` line (below) | the free check on every pull request, posted once, with its receipt |
| the receipt for an invoice | `knos record receipt <acceptance receipt file>` | one PDF page and its JSON |

The record's page on the site is `#record=<slug>`. The file and its page are free, static and unsigned, and each says
the day it was built.

The price book's Record line (0.10 USD a lookup, paid per call) is a server anyone can run and Knos does not host;
its answer adds a signature with an expiry, a summary and the history a supplier grants: [section
5](#5-the-lookup-priced-for-machines). Record budget: zero revenue until someone buys it.

### 1. The record

`docs/records/<slug>.json`, schema `knos.supplier-record/1`. It has two parts, kept apart, and each says where it
came from.

**`orders`: work settled through Knos.** Seven counts: accepted, rejected, insufficient evidence, disputed, appealed,
overturned on appeal, reverted. Each count is `{"n", "from", "evidence"}`: `n` is the length of `evidence`, and
`from` names its source.

| source | read with | what it counts | the evidence behind a count |
|---|---|---|---|
| the events log (`src/knos/events.py`) | `--events <log>`, `--id <the supplier's name in the log>` | deliverables: each once, under the verdict it has after every correction; an event a correction voided is `reverted` | the event's id, its line and that line's sha256 in the chain, and where the issuer's evidence is (a transaction, a batch and its root) |
| the supplier's history, stored with Sibyl Labs' memory engine (a local database Knos uses) (`knos.proof.history` `supplier_record`, `appeals`) | `--memory <folder>`, `--repo owner/repo` | pull requests accepted and rejected under funded orders, appeals, rejections overturned | the pull requests, and an appeal's id |

Accepted and rejected come from the log when it holds the supplier, and from the memory otherwise: they are never
added, because both would count the same work. Insufficient evidence, disputed and reverted are the log's; appealed
and overturned are the memory's. `orders.parts` says which sources were read, the log's head and the repositories
recalled.

`orders.sample`, `orders.period` and `orders.category` stand beside the counts.

**`public`: from public pull requests, not from Knos orders.** For an agent the Agent PR Index measures
([INDEX.md](INDEX.md)), it gives that agent's row of the newest week.

The row holds the merged pull requests that claimed passing tests (`sample`),
how many had a failed check, the share, the range the true rate is 95% likely to fall in (a Wilson interval), the weeks read, and the link that disputes the row.

`scripts/agent_pr_index.py board` writes these files for every agent of the index, from the index alone; its
`--check` fails when one is behind.

Nothing in the file is a score. `sha256` is the SHA-256 of the file's canonical JSON without that field
(`knos.record_page.check`). The file is not signed: the evidence a count links to is.

What the records hold today: one file for each agent the index ranks, and each holds its index row only. The
`public` part is that row: the merged pull requests that claimed passing tests, how many had a failed check, the
interval, the weeks read.

Every count of `orders` is zero with sample zero, and the file says so: no work has been settled through Knos for
any ranked agent, and **no record holds a Knos order of an outside supplier yet**. A record is therefore not yet
something to price a supplier on.

### 2. The badge

`knos badge record <slug>` draws the record as an SVG in the drawing every Knos badge uses (`knos.badge`), with no
script, no link and no font of its own. `web/badge.js` `recordBadgeSvg` writes the same bytes.

- With work settled through Knos (an example only): `Knos-verified: 14 accepted, 0 reverted, sample 16, 2026-07 to 2026-09`. Green
  only when something was accepted.
- Without: `Knos record: no Knos orders yet; public PRs: <failed> of <sample> had a failed check, week of <Monday>`.
  Grey.

The sample is always in the badge. The command prints the Markdown that links the picture to the record's page; it
goes in a README or a pull request's description.

### 3. One line to install

In the supplier's own repository, `.github/workflows/knos-supplier.yml` ([examples/knos-supplier.yml](../../examples/knos-supplier.yml)):

```yaml
name: knos supplier check
on:
  pull_request:
    types: [opened, synchronize, reopened, edited]
permissions: {}
jobs:
  knos:
    permissions:
      contents: read
      checks: read
      pull-requests: write
    uses: drexthealpha/Knos/.github/workflows/supplier.yml@v0.4.0
```

The last line is the install. It runs the free check on every pull request and none of the pull request's code, posts
the result as one comment that later runs rewrite, and attaches the receipt as the artifact `knos-receipt-<pull
request>` (`knos.check-receipt/1`: the repository, the pull request, the head commit, the result, the referee's
evidence and its sha256).

A pull request from a fork runs with a token that can only read: no comment is posted then, and the result is the
job's summary and conclusion. That receipt is the check's own record, signed by nobody; it is not an acceptance
receipt and nothing is paid on it.

Name the workflow by a full commit sha instead of the tag when a moved tag must not change what runs.

### 4. The receipt to send with an invoice

`knos record receipt <file> [--invoice INV-7] [--out path]` reads one acceptance receipt ([RECEIPT.md](RECEIPT.md),
version 2 or later) and writes one A4 page and its JSON (`knos.invoice-receipt/1`).

Both carry what was agreed (the order, the terms' hash, the amount), what was delivered (the repository, the pull
request, the commit), what was accepted (the verdict, the checks, when, what was paid), by which evaluator (its kind
and version, the issuer that signed for it, its independence), and the evidence hashes.

A receipt that does not check gets no page. The page names the one command that checks the receipt file with no
network:

```
knos receipt <file>
```

The page restates the receipt; the receipt file is the evidence, and the supplier's finance operator sends both.

### 5. The lookup, priced for machines

`knos record serve <offer.json>` (`python -m knos.record_api`, [`examples/record_api`](../../examples/record_api)) serves the
records two ways: `/records/<slug>.json` free, and `/lookup/<slug>` for 0.10 test USDC a call, paid through the proposed x402
`knos-order` scheme ([X402.md](X402.md), "Record").

One order buys fifty lookups (50 x 0.10 = 5.00), because the program takes no order under 5.00; each call is signed by the
wallet that funded the order, and a replayed call is refused. The reader pays. The rated supplier never pays, for its record
or for a grant.

**budget: zero revenue until someone buys it.** Knos hosts no such server, no referee signs for lookups served, and
nobody outside has paid for one. The paid answer below is built and tested here; it has not been served on devnet.

#### The free file and the paid answer, row by row

| | the free file | the paid answer |
|---|---|---|
| where | `docs/records/<slug>.json`, the page `#record=<slug>` | `GET /lookup/<slug>` on a server someone runs |
| price | free | 0.10 test USDC a lookup, a pack of fifty an order |
| who pays | nobody | the reader; never the rated supplier |
| the record | the counts, each with its evidence | the same file, byte for byte, inside the answer |
| signature | none: `sha256` of the file only | Ed25519, by a key the operator supplies (`--key`); with no key the answer says it is unsigned |
| freshness | the day it was built (`as_of`) | the cluster time and slot the server read, when it produced the answer, and when the answer expires (one hour unless the operator sets `--ttl`) |
| checked with | `knos.record_page.check` (the hash) | `knos record verify <answer>`: no network; prints fresh, stale, unsigned or invalid |
| summary | none: the reader works out rates | `knos.record-summary/1`: every count as `k` of `n` with its share and the range the true rate is 95% likely to fall in (a Wilson interval), the same denominators for every supplier |
| history | none | four fields, each only with the supplier's signed grant to this reader; otherwise `not granted` |
| availability | a static file in a public repository | what the operator promises, stated in the answer: nothing, on devnet; `knos record serve --health` |
| revenue | none | budgeted at zero |

#### Signed freshness

The answer (`knos.record-answer/1`) is signed over the record's `sha256`, the events log's head when the record was
built from one, the cluster time and slot the server read from the Clock account, `produced` and `expires`. The three
times work like a certificate's validity check ([RFC 6960](https://www.rfc-editor.org/rfc/rfc6960)): made at, valid
from, valid until (producedAt, thisUpdate, nextUpdate).

The reader holds the answer to its own clock.

```
knos record verify answer.json --operator <the operator's public key>
```

| it prints | when | exit |
|---|---|---|
| fresh | the record hashes to what was signed, the summary is the record's, the signature is the key's, and the time is inside `produced` to `expires` | 0 |
| stale | all of that, and past `expires` | 1 |
| unsigned | the server had no key, or the file is the free record | 1 |
| invalid | anything was changed, the key is not the operator named, or the times do not stand | 1 |

The signature shows which key answered and when. It does not show that the operator's records are complete: the
operator serves the files it was given. Name the operator's key with `--operator`; without it the command says whose
key signed and asks the reader to check it.

#### Permissioned history

`knos record history <supplier> [--events <log>] [--id <name>] [--memory <folder>] [--repo owner/repo] [--times <file>]`
writes `<slug>.history.json` (`knos.record-history/1`). It is never put in the free folder. Its four fields:

| field | what it holds | read from |
|---|---|---|
| `per_buyer` | the counts for each repository an order was funded in (its owner is the buyer), and by month | the supplier's history, stored with Sibyl Labs' memory engine (a local database Knos uses); the events log, which names no buyer, by month |
| `disputes` | each disputed deliverable; each appeal with its state, its reason and how it ended | the events log; `knos.proof.history` `appeals` |
| `corrections` | every correction that names one of the supplier's events: what it changed and why | the events log |
| `time_to_accept` | the count, the fastest, the median, the ninetieth percentile, the slowest, four buckets | a times file the supplier gives: the events log keeps no times |

The supplier releases fields to one reader with a grant it signs (`knos.record-grant/1`):

```
knos record grant <slug> --reader <the reader's wallet> --field disputes --field corrections --key supplier.json --days 30
```

The reader sends the grant with its paid call (header `Record-Grant`). The server releases a field only when the
grant is signed by the key its operator holds for that supplier (`--suppliers`, a file of slug and public key), names
the wallet that paid, names the field, and is in force.

Otherwise the field reads `not granted`, with what it would hold and never the data. The operator decides which key
is a supplier's: nothing on chain binds the two yet.

#### The summary

One function for every supplier (`knos.record_answer.summary`): accepted, rejected, insufficient evidence and
disputed over deliverables with a verdict; reverted over deliverables on record; overturned over rejections appealed;
failed checks over merged pull requests that claimed passing tests. Each is `{k, n, of, share, ci95}`, the interval
computed as the Agent PR Index computes it ([INDEX.md](INDEX.md)).

`score` is `null`: nothing is weighted or added into one figure. Not a rating of defect-free work.

#### Availability

The answer carries the operator's promise. The default, and the only one on devnet: uptime none, support none,
retention none. An operator states its own in the offer's `availability`.

`knos record serve --health` (and `GET /health`) says whether the records are readable, whether the chain answers,
whether answers are signed and by which key, and whether the count of each order survives a restart; it exits 0
only when the server can answer.

### What this does not show

- A failed check is not always a failed test or a false claim; the interval and the dispute link stay beside a rate.
- Accepted means the agreed checks passed. It does not show that the work has no defect.
- Nothing recorded is not the same as nothing done.
- The supplier's memory is kept by whoever ran the referee: a record built from it is as complete as that memory.

### Search (0.3.31)

`knos record search QUERY [--json]` searches the record in Sibyl's store across its tiers with Sibyl's own cross-tier
search (sibyl-memory-client 0.8.1, `MemoryClient.search`), which returns a verdict with the rows: how many matched,
or that nothing matched, or that the store is empty (`verdicts.refine_zero`). It also prints the store's size against
its tier's soft cap (`free_tier_status`). Tests: `tests/test_record_search.py`.
