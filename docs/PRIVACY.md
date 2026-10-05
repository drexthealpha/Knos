# Privacy: what Knos puts in public, and what it does not

A chain is public and permanent. Nothing written to it can be erased or corrected, and anyone can read it without
asking. This page says, for each way of using Knos, what a stranger can learn, so a buyer can decide before the
first order. Everything here is on Solana devnet with test USDC. [SECURITY.md](SECURITY.md) section 12 and
[CONTROLS.md](CONTROLS.md) hold the same facts with the tests that check them.

## 1. What a payment reveals, even for a private repository

Hiding the repository's name does not hide the business. Whatever the mode, a payment shows:

| what | where it is | what someone can do with it |
|---|---|---|
| **Ids** | the GitHub id of the paying organisation and of the account that funded; each payee's GitHub id; the id of the repository whose run signed | An id is a public number: GitHub's API turns it into a name. Ids do not change when an account is renamed. |
| **Amounts** | the order's amount, the fee, the relayer's tip, every top-up and every refund | Add up what an organisation spends, and what a seller earns. |
| **Timing** | the block time of the funding, of each amendment, of the payment; the deadline | Count orders per week, see how long work takes, see when a team is busy. |
| **The payee's wallet** | the address each share was paid to | Follow that wallet: its other income, its balance, where the money goes next. |
| **Counterparties** | funder and payee in one transaction; the judge's repository; the arbiter's id if one was named | List a company's vendors and a vendor's customers. |
| **The signed token** | the whole token is written to `knos_oidc` to be verified, and stays in the history of those transactions after the account is closed | Read every claim the host signed: for a public order, the repository's name, the branch, the commit, the workflow path and the account that acted. |

A public order adds the repository's id, the issue's number, the pull request's number, the accepted commit and the
terms as JSON (the names of the required checks and the allowed paths).

Never on chain, in any mode: code, the text of an issue or a pull request, a check's output or logs.

## 2. What the private (attestor) mode hides, and what it does not

A private order is judged by one attestor repository the organisation chose, which reads the private repository
with a token the organisation gave it.

It hides:

- the private repository's name and id, and the issue's number: the order is found by a hash of both with a
  32-byte salt, so the hash cannot be guessed from a known repository id;
- the terms: only their hash is on chain, so the names of the checks and the path globs are not;
- the pull request's number: a number derived from the salt stands in its place.

It does not hide:

- that the organisation pays, whom, how much and when (section 1, every row);
- the attestor repository: its id, and in its tokens its name, branch, workflow commit and the account that started
  each run. A public attestor's policy file names the repositories it attests for: keep the attestor private if
  those names are secret;
- the hash of the accepted commit. It says nothing to someone without access to the repository, and it confirms a
  guess to someone who has the commit.

It also changes who is trusted: nobody outside the organisation can check what the attestor read. That is on the
receipt, under "What trust remains".

A private repository that relays its own tokens with its own key posts nothing as a comment and writes nothing to
the public relay's log. `knos receipt mirror` and `knos bundle make` build nothing for a private order, so neither
publishes one.

## 3. The batched meter: evaluations stay in your own storage

The meter counts attested evaluations. In its individual mode each evaluation is one account on chain, with the
buyer's id, the seller's id, the order, the artifact, the policy, the milestone and the verdict.

In batch mode none of that is on chain per evaluation. Each evaluation is one line of a ledger file that the buyer
keeps, and the seller keeps its own, wherever each chooses: a repository, a bucket, a disk. The chain receives one
record per batch: the buyer's id, the seller's id, the month, a sequence number, how many evaluations, how many
accepted, their value, and a 32-byte Merkle root of the evaluations' ids.

So the chain shows that these two parties did this much business this month, and nothing about which orders,
which artifacts or which verdicts. A party who holds the ledger can prove one evaluation was counted (an inclusion
proof against the root) without showing the others. A seller's own count of the same month is on chain beside the
buyer's, so a difference between them is public as two numbers; which evaluations differ is in the ledgers only.

## 4. Retention

| where | how long | who decides |
|---|---|---|
| The chain | For ever on a live cluster. Devnet can be reset by its operators, and public RPC nodes drop old transactions; neither is deletion you can rely on. | nobody |
| Closed accounts | An order's or a token's account can be closed and its rent returned. The transactions that created it, with their data and logs, stay. | nobody |
| The receipt mirror | Until whoever serves it removes a file. `knos receipt mirror` never removes one. A copy someone else took is theirs. | the mirror's owner |
| Evidence bundles | Until each holder deletes its copy. A bundle holds the signed token, so treat it as you treat the token's claims. | each holder |
| Batch ledgers | As long as the party who keeps them decides. Knos keeps none. | the buyer and the seller, each for its own |
| The host | Workflow logs, check runs and comments follow GitHub's or GitLab's retention and the repository's settings. | the repository's owner |

Knos runs no server that stores evaluations, receipts or ledgers. The public relay is a workflow in a public
repository: what it relays is in that repository's public run history.

If a ledger is deleted, the root on chain stays and can no longer be opened by anyone. That is the retention you
chose, and it is also the end of your ability to prove what the batch held.

## 5. What a hash proves

A hash on chain (of the terms, of a scope, a Merkle root, a receipt's digest) proves **correspondence**: that the
data someone shows you now is the data that was hashed then. It proves two things less than people expect:

- **Not availability.** The hash does not hold the data and cannot give it back. If the terms' JSON, the salt or the
  ledger is lost, the hash proves nothing to anyone. Keep the data, and agree before the work who else keeps it.
- **Not confidentiality.** A hash of something guessable is no secret: whoever can guess the input can confirm it.
  A repository's id and an issue's number are guessable, which is why a private scope has a salt. A commit's hash,
  a short list of check names and an amount from a price list are guessable too. Whoever is given the data to check
  it against the hash then has the data.

## 6. What an outsider sees

`knos observe <order address | transaction>` plays the outsider. It reads only what anyone can read with no account
and no permission: the transactions and accounts of the Knos programs, and GitHub's public API with no credential
(`--offline` skips that). For each fact it says whether the outsider learns it, learns only a hash of it, or does
not, and which log line, account field or token claim it was read from. `knos observe --graph <owner id>` does the
same for an organisation's whole history; `--json` prints either as data.

The three tables below are that command's output for one recorded history: three work orders funded from one
organisation's Balance on the programs' test builds (LiteSVM), kept in `tests/data/observe.json`. They are written
between the marks by `python -m knos.observe --render-doc`, and `tests/test_observe.py` fails when they are stale or
when the programs no longer write what the record holds. The ids, names and addresses are the test's own; the
amounts are test money. Names were not looked up (`--offline`), so a name is shown only where a signed token
carried it.

### A public order

Every fact is public, by design: that is what lets a stranger check the payment.

<!-- observe:public -->
| fact | does an outsider learn it? | what they read | from where |
| --- | --- | --- | --- |
| buyer organisation: GitHub id | yes | `424242` | `owner=` of the Balance's `knos2:balance` log line; bytes 168..176 of the order's account, while the order is open; `repository_owner_id` in the funding token GitHub signed (knos_oidc instruction data) |
| buyer organisation: name | yes | `octo` | `repository_owner` in the funding token GitHub signed (knos_oidc instruction data); GitHub's public API, `user/424242`: an id is a public number, and this turns it into a name |
| who gave the funding command | yes | `555000` | `by=` of the `knos3:funded` log line; `actor` in the funding token GitHub signed (knos_oidc instruction data) |
| where the money came from (a Balance or a wallet) | yes | `13xReTVGCp5MsD5owvmkMkVConuswJNrdQ3w24Asbj6N` | `source=` of the `knos3:funded` log line |
| repository: id | yes | `987654321` | `repo=` of the `knos3:funded` log line |
| repository: name | yes | `octo/widgets` | `repository` in the funding token GitHub signed (knos_oidc instruction data); `repository` in the pay token GitHub signed (knos_oidc instruction data); GitHub's public API, `repositories/987654321`: an id is a public number, and this turns it into a name |
| issue | yes | `3107` | `issue=` of the `knos3:funded` log line |
| pull request | yes | `7` | `pr=` of the `knos3:paid` log line |
| branch | yes | `refs/heads/main` | `ref` in the pay token GitHub signed (knos_oidc instruction data); `ref` in the funding token GitHub signed (knos_oidc instruction data) |
| supplier (payee): GitHub id | yes | `1234567` | `payee=` of the `knos3:paid` log line |
| supplier (payee): name | yes | `not looked up (--offline)` | GitHub's public API, `user/1234567`: an id is a public number, and this turns it into a name |
| supplier (payee): wallet | yes | `FMUEmtxhU46GzhKF4FW9MLJdQWiLgjiXP9TYRWSrqTpV` | `to=` of the `knos3:paid` log line |
| amount | yes | `20.000000` | `amount=` of the `knos3:funded` log line; bytes 64..72 of the order's account, while the order is open |
| fee | yes | `0.500000 on top, paid by the funder` | `fee=` of the `knos3:funded` log line; `fee=` and `tip=` of the `knos3:settled` log line |
| mint (which money) | yes | `2KW2XRd9kwqet15Aha2oK3tYvd3nWbTFH1MBiRAv1BE1` | `mint=` of the Balance's `knos2:balance` log line; bytes 288..320 of the order's account, while the order is open |
| funding time | yes | `2026-09-21 14:13:21 UTC` | the block time of the funding transaction |
| acceptance time | yes | `2026-09-21 15:13:21 UTC` | the block time of the paying transaction |
| review window | yes | `1 h 00 min from funding to payment; open for work until 2026-10-05 14:13:21 UTC` | the two block times; `deadline=` of the `knos3:funded` log line |
| checks named in the terms | yes | `build-and-test` | `checks` in the `knos3:terms` log line |
| allowed paths | yes | `src/billing/**` | `paths` in the `knos3:terms` log line |
| terms text | yes | `{"accept":"","checks":[{"app":15368,"name":"build-and-test"}],"mode":"merge","paths":["src/billing/**"],"v":2}` | the `knos3:terms` log line, whole |
| workflow commit | yes | `cccccccccccccccccccccccccccccccccccccccc` | bytes 384..424 of the order's account, while the order is open; `job_workflow_sha` in the pay token GitHub signed (knos_oidc instruction data); `job_workflow_sha` in the funding token GitHub signed (knos_oidc instruction data) |
| accepted commit | yes | `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` | the head commit in the pay token's audience |
| whether a reservation named someone | yes | `GitHub id 1234567, until 2026-09-23 14:13:21 UTC` | `taker=` of the `knos3:reserved` log line; bytes 128..136 of the order's account, while the order is open; `actor` in the reserving token GitHub signed (knos_oidc instruction data) |
| judge (attestor) repository | yes | `octo/widgets (id 987654321)` | `repository` in the pay token GitHub signed (knos_oidc instruction data); `judge=` of the `knos3:settled` log line |
| who started the run that judged it | yes | `mona (id 1234567)` | `actor` in the pay token GitHub signed (knos_oidc instruction data) |
| other orders of the same Balance or wallet | yes | `3 in all, 95.000000 funded` | `source=` of the `knos3:funded` log line, the same on each |
| order sizes with this supplier | yes | `2 payments: 20.000000, 40.000000` | `amount=` and `payee=` across those orders: repeated sizes mark a standing relationship |
<!-- /observe:public -->

### A private (attestor) order

The same organisation, the same supplier, a private repository. The repository, the issue, the pull request and the
terms are on chain only as hashes, and the branch, the check names and the paths are nowhere: the test searches
every account of the programs, every log line and all instruction data for them. Everything else is as public as
before.

<!-- observe:private -->
| fact | does an outsider learn it? | what they read | from where |
| --- | --- | --- | --- |
| buyer organisation: GitHub id | yes | `424242` | `owner=` of the Balance's `knos2:balance` log line; bytes 168..176 of the order's account, while the order is open; `repository_owner_id` in the funding token GitHub signed (knos_oidc instruction data) |
| buyer organisation: name | yes | `octo` | `repository_owner` in the funding token GitHub signed (knos_oidc instruction data); GitHub's public API, `user/424242`: an id is a public number, and this turns it into a name |
| who gave the funding command | yes | `555000` | `by=` of the `knos3:funded` log line; `actor` in the funding token GitHub signed (knos_oidc instruction data) |
| where the money came from (a Balance or a wallet) | yes | `13xReTVGCp5MsD5owvmkMkVConuswJNrdQ3w24Asbj6N` | `source=` of the `knos3:funded` log line |
| repository: id | only a hash | `09ae8393cad4e2f3eacde3c2efd342e52cdf5a062f1b2a9a1ac5047a1bcd0fc4` | bytes 24..56 of the order's account, while the order is open: sha256(salt, repository id, issue); the salt is not on chain; the funding instruction's data: the same salted hash |
| repository: name | no |  | no id to look up, and no token names it: the tokens are the attestor repository's |
| issue | only a hash | `09ae8393cad4e2f3eacde3c2efd342e52cdf5a062f1b2a9a1ac5047a1bcd0fc4` | the same salted hash as the repository |
| pull request | only a hash | `258254167399157` | `pr=` of the `knos3:paid` log line: a number made from the salt and the pull request's, not the number itself |
| branch | no |  | the tokens name the attestor repository's branch, never the private repository's |
| supplier (payee): GitHub id | yes | `1234567` | `payee=` of the `knos3:paid` log line |
| supplier (payee): name | yes | `not looked up (--offline)` | GitHub's public API, `user/1234567`: an id is a public number, and this turns it into a name |
| supplier (payee): wallet | yes | `FMUEmtxhU46GzhKF4FW9MLJdQWiLgjiXP9TYRWSrqTpV` | `to=` of the `knos3:paid` log line |
| amount | yes | `40.000000` | `amount=` of the `knos3:funded` log line; bytes 64..72 of the order's account, while the order is open |
| fee | yes | `1.000000 on top, paid by the funder` | `fee=` of the `knos3:funded` log line; `fee=` and `tip=` of the `knos3:settled` log line |
| mint (which money) | yes | `2KW2XRd9kwqet15Aha2oK3tYvd3nWbTFH1MBiRAv1BE1` | `mint=` of the Balance's `knos2:balance` log line; bytes 288..320 of the order's account, while the order is open |
| funding time | yes | `2026-09-22 15:13:22 UTC` | the block time of the funding transaction |
| acceptance time | yes | `2026-09-22 17:13:22 UTC` | the block time of the paying transaction |
| review window | yes | `2 h 00 min from funding to payment; open for work until 2026-10-06 15:13:22 UTC` | the two block times; `deadline=` of the `knos3:funded` log line |
| checks named in the terms | only a hash | `5f27f93680b5012c4340ab848702fdf1c08b076b97ef06d73377fd5d2d70586a` | bytes 320..352 of the order's account, while the order is open: the hash of the terms; the terms hash in the pay token's audience; the funding instruction's data: the hash of the terms |
| allowed paths | only a hash | `5f27f93680b5012c4340ab848702fdf1c08b076b97ef06d73377fd5d2d70586a` | the same hash of the terms |
| terms text | only a hash | `5f27f93680b5012c4340ab848702fdf1c08b076b97ef06d73377fd5d2d70586a` | the same hash of the terms |
| workflow commit | yes | `cccccccccccccccccccccccccccccccccccccccc` | bytes 384..424 of the order's account, while the order is open; `job_workflow_sha` in the pay token GitHub signed (knos_oidc instruction data); `job_workflow_sha` in the funding token GitHub signed (knos_oidc instruction data) |
| accepted commit | yes | `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` | the head commit in the pay token's audience: it says nothing without the repository, and confirms a guess |
| whether a reservation named someone | yes | `none was made` | no `knos3:reserved` log line names this order |
| judge (attestor) repository | yes | `octo/knos-settle (id 31313131)` | `repository` in the pay token GitHub signed (knos_oidc instruction data); bytes 184..192 of the order's account, while the order is open |
| who started the run that judged it | yes | `mona (id 1234567)` | `actor` in the pay token GitHub signed (knos_oidc instruction data) |
| other orders of the same Balance or wallet | yes | `3 in all, 95.000000 funded` | `source=` of the `knos3:funded` log line, the same on each |
| order sizes with this supplier | yes | `2 payments: 20.000000, 40.000000` | `amount=` and `payee=` across those orders: repeated sizes mark a standing relationship |
<!-- /observe:private -->

So a private order still tells an outsider: which organisation paid, which GitHub account was paid and at which
wallet, how much, the fee, when it was funded and when it was accepted, which attestor repository judged it and who
started that run, the commit that was accepted (as a hash), and that it came from the same Balance as the
organisation's other orders. Two orders of similar size to one payee a day apart are a supplier relationship,
whatever the repository is called.

### The whole history of one organisation

`knos observe --graph 424242` on the same record: the supplier list, what each was paid, the size of each payment
and the cadence. One of the three orders is the private one; it is counted like the others.

<!-- observe:graph -->
| direction | counterparty (GitHub id) | wallets paid | orders | total | sizes | first payment | last payment | median days between |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pays | 1234567 | `FMUEmtxhU46GzhKF4FW9MLJdQWiLgjiXP9TYRWSrqTpV` | 2 | 60.000000 | 20.000000, 40.000000 | 2026-09-21 15:13:21 UTC | 2026-09-22 17:13:22 UTC | 1.08 |
| pays | 7654321 | `6TcyBfPdBt1kjsvDZLzmBFnuMaLWiTaAt4RjUr9VA5YD` | 1 | 35.000000 | 35.000000 | 2026-09-28 17:43:23 UTC | 2026-09-28 17:43:23 UTC |  |
<!-- /observe:graph -->

## 7. What to do if that is too much

Each of these puts less on a public chain. None of them is a privacy guarantee, and each has a cost.

| what you do | what an outsider no longer sees | what it costs | what it still shows |
|---|---|---|---|
| **Count with the batched meter** (section 3; [METER.md](METER.md)) | Anything per evaluation: no order, artifact, policy, verdict or time of each. | You and the supplier each keep the ledger; lose it and the root proves nothing. | The buyer's id and the seller's id, the month, how many evaluations, how many accepted, their value, and a root. That the two of you do this much business is public. |
| **Settle off chain, use Knos only for the count** | Any payment: no amount in escrow, no payee wallet, no payment time. | The chain no longer pays or holds anything: you pay the invoice as you pay any other, and trust between the parties does the rest. | Whatever the count shows (the line above). |
| **Pool payments**: one payment for a period instead of one per order | The size and time of each order, and how many there were. | The supplier waits for the period's end; an order is no longer paid on its own acceptance. | The period's total, the payee, the wallet and the payment's time. |
| **A fresh payee wallet per supplier**: the supplier binds (`knos claim`) a wallet it uses for nothing else | The link from these payments to the supplier's other income and spending through the wallet. | One wallet is bound to a GitHub account at a time, so it is one wallet for all of that account's customers, not one per customer. The program can send one order's payment to another wallet, but the bound wallet signs that, so the link between the two is public, and no `knos` command does it yet. Moving the money on to a known wallet joins them again. | The payee's GitHub id on every payment, which links them all whatever the wallet. |

What none of these hide: the GitHub ids of the two parties wherever the programs record them, the wallet of
whoever pays the transaction fees, the attestor or judge repository of any token that reaches the chain, and the
fact, the time and the size of every transaction that does. A chain is the wrong place for a relationship whose
existence is the secret.

Confidential evidence stays in the customer's storage: code, logs, check output, the terms' text and salt of a
private order, and a batch's ledger are never sent to the chain, and Knos runs no server that receives them
(section 4). What the chain holds of them is a hash, which proves correspondence and nothing more (section 5).

Nothing on this page is a privacy guarantee. It lists what the command found in what the programs write today; a
careful outsider with other data (GitHub's public activity, a wallet's other transactions, the timing of releases)
may infer more.

## What is not done

- Amounts, ids and wallets are in the clear in every mode. No confidential transfer is used.
- There is no scoped or time-limited access to evidence: whoever holds a bundle or a ledger holds all of it.
- Nothing here has been reviewed by an outside party.
