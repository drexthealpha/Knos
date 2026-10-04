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

## What is not done

- Amounts, ids and wallets are in the clear in every mode. No confidential transfer is used.
- There is no scoped or time-limited access to evidence: whoever holds a bundle or a ledger holds all of it.
- Nothing here has been reviewed by an outside party.
