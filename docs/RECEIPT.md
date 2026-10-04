# The acceptance receipt

A settlement on Knos leaves three public facts: a work order, a token GitHub or GitLab signed that says the order's
terms were met, and a transaction that paid. The **acceptance receipt** is one JSON document that joins them. It
holds nothing private and nothing that is not already public, so anyone can rebuild it from the chain and compare
digests. It is what a buyer files, what a seller shows, and what a third party attests to.

A signature proves who signed, not that what was signed is true. So a receipt says four separate things, always in
this order and under these headings, in the JSON and in what `knos receipt` prints:

1. **What the issuer authenticated** (`issuer_authenticated`). GitHub or GitLab signed: which workflow file, at which
   commit, ran in which repository, for which event, and when. `verified` names the `knos_oidc` program, the key
   account and the transaction in which that signature was verified on chain.
2. **What the evaluator observed** (`evaluator_observed`). The pinned judge's verdict, the named checks and their
   conclusions, the accepted commit and pull request, and the judge's version (the commit of its workflow).
3. **Which policy produced the verdict** (`policy`). The hash of the terms fixed at funding, the mode, the allowed
   and denied paths, and the terms' version.
4. **What trust remains** (`trust_remaining`). The list, in plain words: the host's signing key and its runner; the
   code of the pinned workflow; the repository's administrators for a merge-mode order; the account that ran the
   judge when it was not the order's own repository; and Knos's upgrade multisig (the programs are upgradeable only
   through a multisig with a public 48-hour delay, until an outside review). The list follows from the provider, the
   mode and the judge, and a receipt that leaves one out is not valid.

Then `amendments`: every change of the order's terms between its funding and this payment (a top-up, an assignment
of the payment, a reservation, a cancellation, a change of the funder's plan), oldest first, each with its
transaction, so an order's terms history is explicit. Then the payment itself.

- Schema: [`docs/receipt/acceptance-receipt.v2.schema.json`](receipt/acceptance-receipt.v2.schema.json) (JSON Schema
  2020-12); version 1: [`acceptance-receipt.v1.schema.json`](receipt/acceptance-receipt.v1.schema.json)
- Conformance vectors: [`docs/receipt/vectors.json`](receipt/vectors.json): of version 1, five receipts a reader
  must accept, with their digests, and nine a reader must refuse; of version 2, the same five and eight to refuse
- Reference code: [`src/knos/receipt.py`](../src/knos/receipt.py) (`build2`, `upgrade`, `check`, `render`,
  `canonical`, `digest`); the tests are `tests/test_receipt.py` and `tests/test_bundle.py`
- Commands: `knos receipt FILE` (check and print), `knos receipt mirror --out DIR`, `knos receipt verify ORDER
  [--mirror DIR]`, `knos bundle make ORDER [--verdict FILE]`, `knos bundle verify FILE [--rpc URL] [--mirror DIR]`

## Version 2

```json
{
 "type": "knos.acceptance-receipt",
 "version": 2,
 "cluster": "localnet",
 "program": "5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k",
 "order": "J222WNWuZwhfgRBMc4jDu9MjGG6eCc2Up8P4FFADWVYp",
 "scope": "3ada113468f7cf3424704252860379fc4bc42653cb46236bc7fec4484b71f9dc",
 "repository": {
  "id": 987654321,
  "issue": 77
 },
 "issuer_authenticated": {
  "provider": "github",
  "issuer": "https://token.actions.githubusercontent.com",
  "claims": {
   "actor_id": "555000",
   "event_name": "pull_request_target",
   "exp": 1790003880,
   "iat": 1790003580,
   "job_workflow_ref": "drexthealpha/Knos/.github/workflows/prove.yml@refs/tags/v0.3.13",
   "job_workflow_sha": "cccccccccccccccccccccccccccccccccccccccc",
   "repository_id": "987654321",
   "repository_owner_id": "424242",
   "run_attempt": "1",
   "run_id": "36905461215",
   "runner_environment": "github-hosted"
  },
  "token_sha256": "00903b35b33dc80d9058e53bea6d93acca59e2dbd81e4dd47a346422c51729f2",
  "verified": {
   "program": "FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W",
   "key": "H8ThtUzgUFkhKKjSvjJdHHWWeYozVDPt5E36bTS7bzrE",
   "transaction": "uiy2jsRXoDV8p9AB2zSuwmYvPqAREwfiThScSKFgTdx4dVa473s3HjkAwPRPZ9ecArMYcCbzWAE9aVP96f3Ywme"
  }
 },
 "evaluator_observed": {
  "judge": {
   "kind": "repository",
   "version": "cccccccccccccccccccccccccccccccccccccccc"
  },
  "verdict": "accepted",
  "checks": [
   {
    "name": "build",
    "conclusion": "passed"
   },
   {
    "name": "test",
    "conclusion": "passed"
   }
  ],
  "artifact": {
   "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
   "pull_request": 12
  }
 },
 "policy": {
  "terms_hash": "4d7df9bff60d312cce46c0ebf923575cc54e92181f4a38638154b2ebcbe17b81",
  "mode": "merge",
  "allowed_paths": [
   "src/**"
  ],
  "denied_paths": [
   ".github/**",
   ".knos/**"
  ],
  "version": 1
 },
 "trust_remaining": [
  "GitHub's signing key and its hosted runner: whoever holds that key, or a runner that lies about which workflow ran, could forge the token.",
  "The code of the pinned workflow at the commit named above: it decides what counts as accepted. Read it at that commit.",
  "The administrators of the repository: in merge mode the merge is the acceptance, and whoever may merge or change the branch rules can accept.",
  "Knos's upgrade multisig: the programs are upgradeable only through a multisig with a public 48-hour delay, until an outside review."
 ],
 "amendments": [],
 "payees": [
  {
   "github_id": 5550123,
   "bps": 10000,
   "amount": "20000000",
   "to": "6JhaGdekBjU2RfiYWSjYdQAibx4LfSfTNFEeMUHnUVz7"
  }
 ],
 "amounts": {
  "mint": "2KW2XRd9kwqet15Aha2oK3tYvd3nWbTFH1MBiRAv1BE1",
  "decimals": 6,
  "paid": "20000000",
  "of": "20000000",
  "fee": "200000",
  "tip": "300000"
 },
 "transaction": {
  "signature": "35uS8fqUd1ARccqYuFaEbZy2kbFHr9uGcWLSg8FP1358V5Y8EEThyu4USBfHEhMjxd3QMKoNUMtHuhtMYKBXWcye",
  "slot": 412,
  "time": 1790003600
 }
}
```

Its digest is `e6a72d9d5760a99a824c48a7923a7a771d2cd26d54253fbe61005a236d711add`.

| field | what it is | where it comes from |
|---|---|---|
| `type`, `version` | `knos.acceptance-receipt`, `2`. A reader refuses a version it does not know | |
| `cluster`, `program`, `order`, `scope`, `repository` | as in version 1, below | |
| `issuer_authenticated.provider`, `.issuer` | `github` or `gitlab`, and the issuer's URL | the token |
| `issuer_authenticated.claims` | the claims as the issuer signed them. GitHub: the eleven of version 1. GitLab: `ci_config_ref_uri`, `ci_config_sha`, `exp`, `iat`, `namespace_id`, `pipeline_id`, `pipeline_source`, `project_id`, `project_path`, `ref`, `ref_path`, `ref_protected`, `ref_type`, `runner_environment`, `sha`, `user_id`: every claim the program reads (`programs-v2/knos_pay/src/gl.rs`). The program reads a GitLab project and user as 900000000000000000 + id and a namespace as 800000000000000000 + id, so a GitLab receipt's `repository.id`, its `scope` and its payees carry those ids, and `check` holds the claims to them | the token |
| `issuer_authenticated.token_sha256` | sha256 of the token's signature bytes | the token |
| `issuer_authenticated.verified` | the `knos_oidc` program, its key account that verified the signature, and the transaction of the last verification step | the token account's transactions |
| `evaluator_observed.judge` | `kind` as in version 1, and `version`: the commit of the judge's workflow, the same the issuer signed | the `knos3:settled` log line, the token |
| `evaluator_observed.verdict` | `accepted`: a receipt exists only for a payment | |
| `evaluator_observed.checks` | the checks the terms name, each `{name, conclusion}`. The judge signs only when each passed at the accepted commit, so each is `passed`; the conclusions as fetched are in the evidence bundle | the terms |
| `evaluator_observed.artifact` | the accepted commit and the pull request that carried it | the token's audience |
| `policy` | `terms_hash`, `mode`, `allowed_paths`, `denied_paths`, `version`. The last three are `null` when the terms are not public | the Order account, the `knos3:terms` log line |
| `trust_remaining` | the list above | `knos.receipt.trust_of` |
| `amendments` | `{kind, transaction, time, detail}`; `kind` is `topup`, `assign`, `reserve`, `cancel` or `plan`; `detail` is the log line's own fields as strings | the `knos3:topup`, `assigned`, `reserved`, `cancelled` and `knos2:plan` log lines |
| `payees`, `amounts`, `transaction` | as in version 1 | |

The rules of version 1 hold for version 2 (they are checked by the same code), and these too:

1. `trust_remaining` is exactly the list for this provider, mode and judge.
2. `evaluator_observed.judge.version` is the workflow commit in the signed claims.
3. Checks are in order of name, each once; amendments are oldest first.
4. A GitLab receipt is for a pipeline of the order's own project on a protected branch (`ref_protected` is `true`).
   Its `scope` is not recomputed by a reader, since the program namespaces GitLab's ids by issuer.

A receipt is built from chain facts only (`knos.bundle.gather`), for a public order paid by a judge's pay token.
What is not built here: a receipt for a private order (its terms and repository are not public), for a payment an
arbiter's ruling made (a ruling names no commit), and for a holdback released after its warranty (it has no token
of its own). A version 1 receipt still checks, and `knos.receipt.upgrade` writes it as version 2.

## The evidence bundle

`knos bundle make <order or paying transaction>` writes one `.tar` that the buyer and the seller both can hold:

| file | what it is |
|---|---|
| `MANIFEST.json` | the sha256 of every other file |
| `receipt.json` | the receipt, version 2, in canonical form |
| `token.jwt` | the raw token the issuer signed, read back from the transactions that wrote it to `knos_oidc` |
| `key.json` | the issuer's public key that verified it (`issuer`, `kid`, `n`, `e`) and its key account |
| `terms.json` | the order's terms: the bytes hashed at funding |
| `checks.json` | the check runs, commit statuses and changed files of the accepted commit, as fetched, reduced to the fields a verdict reads and put in one order |
| `judge.json` | the judge's kind and version, and `inputs_sha256`: the sha256 of `checks.json` |
| `verdict.json` | optional, for an order in tests mode: the judge's verdict, added by `--verdict FILE` (below) |

`knos bundle make <order> --verdict FILE` puts the judge's own verdict in the bundle as `verdict.json`. `FILE` is what
`knos proof judge --evidence` wrote: the hashes of the two trees the judge ran on, the hash of the acceptance checks,
its assurance (in-process, black-box or hermetic), and the image digest when it ran in one. The trees are not in the
bundle. `verify` refuses a `verdict.json` that is not a passed verdict on the acceptance checks hashed at funding, or
that names another image than the terms do, and `knos judge rerun <bundle> --base DIR --pr DIR` runs the judge again
on trees you check out and says when they are not the ones the verdict names. Without `--verdict`, a bundle of a
tests-mode order says "assurance: not said by this bundle"; in merge mode no judge ran the code and it says that none
is claimed.

The tar is deterministic: names in order, times zero, mode 0644, no owner. Two builds of one order are the same
bytes, whoever makes them (the test builds it twice with the host answering in another order).

`knos bundle verify <tar>` uses no network. It checks every file against the manifest; the token's RS256 signature
against the included key; that the key is the one at the key account the receipt names (the address is derived from
the key); the claims, the order, the commit, the terms hash and the payees against the token; `terms.json` against
the terms hash; and then derives the verdict again from the terms and the checks. It prints the four parts.

**The offline limit.** Offline, the paid wallet is not checked against the chain. No signed token carries the wallet
each payee was paid at or the amounts (the token names accounts and shares), so a bundle whose receipt names another
wallet, with its manifest rebuilt, still passes `knos bundle verify <tar>` with no option. The command says so
itself, in a line that starts `limit:`. Two options close it, each as far as it goes:

```
knos bundle verify FILE --rpc URL      # asks the chain
knos bundle verify FILE --mirror DIR   # DIR, or the https URL a mirror is served at
```

- `--rpc URL` reads the key's account on that cluster and refuses a key that is missing, revoked or another key,
  then reads the paying transaction and refuses a receipt whose wallets, amounts, fee or tip are not the ones the
  escrow logged. When the cluster no longer has the transaction the command refuses and says that; `--mirror` is then what is left.
- `--mirror DIR` compares the receipt with the one the mirror holds for the paying transaction, by digest, and
  refuses a bundle whose receipt the mirror does not hold. This uses the network only when the mirror is a URL. It
  shows that the bundle and the mirror agree, on the word of whoever serves the mirror; it does not ask the chain.

What the bundle does not prove: the wallet each payee was paid at and the amounts are the chain's, not the
token's, so they are confirmed by comparing the receipt's digest with the one the chain or a mirror gives; and
`checks.json` is what the host answered when the bundle was made, which only the host can vouch for.

## The mirror

Devnet can be reset, and a public RPC keeps only so much history. So every receipt is also written off chain:

```
knos receipt mirror --out DIR          # every receipt the chain shows now, added to what DIR already holds
knos receipt verify ORDER --mirror DIR  # DIR, or the https URL it is served at
```

`DIR/<order>.json` holds an order's receipts (a standing order is paid more than once) and `DIR/index.json` lists
every order with each receipt's digest, transaction and time. The files are canonical JSON, so the same receipts
give the same bytes and a GitHub Pages branch or any bucket can serve the folder. A run never removes a receipt:
what the chain has lost stays. `verify` rebuilds the receipt from the chain; when the chain no longer has the
transaction it reads the mirror, checks the receipt against the mirror's index and the rules, and says
`from mirror, chain record unavailable`. A mirror is a copy, not a proof: it shows what the chain said, on the
word of whoever serves it, and a bundle made while the chain had the record is what can still be checked.

## Version 1

```json
{
 "type": "knos.acceptance-receipt",
 "version": 1,
 "cluster": "localnet",
 "program": "5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k",
 "order": "J222WNWuZwhfgRBMc4jDu9MjGG6eCc2Up8P4FFADWVYp",
 "scope": "3ada113468f7cf3424704252860379fc4bc42653cb46236bc7fec4484b71f9dc",
 "repository": {
  "id": 987654321,
  "issue": 77
 },
 "artifact": {
  "commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "pull_request": 12
 },
 "terms": {
  "hash": "4d7df9bff60d312cce46c0ebf923575cc54e92181f4a38638154b2ebcbe17b81",
  "mode": "merge"
 },
 "judge": {
  "kind": "repository",
  "issuer": "https://token.actions.githubusercontent.com",
  "claims": {
   "actor_id": "555000",
   "event_name": "pull_request_target",
   "exp": 1790003880,
   "iat": 1790003580,
   "job_workflow_ref": "drexthealpha/Knos/.github/workflows/prove.yml@refs/tags/v0.3.13",
   "job_workflow_sha": "cccccccccccccccccccccccccccccccccccccccc",
   "repository_id": "987654321",
   "repository_owner_id": "424242",
   "run_attempt": "1",
   "run_id": "36905461215",
   "runner_environment": "github-hosted"
  },
  "token_sha256": "00903b35b33dc80d9058e53bea6d93acca59e2dbd81e4dd47a346422c51729f2",
  "key": "H8ThtUzgUFkhKKjSvjJdHHWWeYozVDPt5E36bTS7bzrE"
 },
 "payees": [
  {
   "github_id": 5550123,
   "bps": 10000,
   "amount": "20000000",
   "to": "6JhaGdekBjU2RfiYWSjYdQAibx4LfSfTNFEeMUHnUVz7"
  }
 ],
 "amounts": {
  "mint": "2KW2XRd9kwqet15Aha2oK3tYvd3nWbTFH1MBiRAv1BE1",
  "decimals": 6,
  "paid": "20000000",
  "of": "20000000",
  "fee": "200000",
  "tip": "300000"
 },
 "transaction": {
  "signature": "35uS8fqUd1ARccqYuFaEbZy2kbFHr9uGcWLSg8FP1358V5Y8EEThyu4USBfHEhMjxd3QMKoNUMtHuhtMYKBXWcye",
  "slot": 412,
  "time": 1790003600
 }
}
```

| field | what it is | where it comes from |
|---|---|---|
| `type`, `version` | `knos.acceptance-receipt`, `1`. A reader still accepts it | |
| `cluster`, `program` | which chain, and the `knos_pay` program that held the escrow | the transaction |
| `order` | the order's address | the pay token's audience, the `knos3:paid` log line |
| `scope` | the order's scope, 64 hex characters | the Order account |
| `repository` | `{id, issue}` of the issue the order was for, by GitHub's ids; `null` for a private order, whose scope hides them | the Order account |
| `artifact` | the commit that was accepted (`commit`, the head sha) and the pull request that carried it | the pay token's audience |
| `terms` | the sha256 of the terms the order was funded under, and how they were judged (`merge` or `tests`). The terms themselves are in the funding transaction's `knos3:terms` log line | the Order account |
| `judge.kind` | who was entitled to sign: `repository` (a run in the order's own repository), `neutral` (the pinned attest workflow run by hand in a repository its starter owns), `attestor` (a private order's judge repository), `arbiter` (the arbiter the order named) | the `knos3:settled` log line |
| `judge.issuer`, `judge.claims` | the signer's claims as the issuer signed them: which repository and owner, which actor, which workflow file at which commit, which run. Ids are strings, as GitHub sends them; `iat` and `exp` are numbers | the verified token account |
| `judge.token_sha256` | sha256 of the token's signature bytes: the same token can be recognised without being republished | the token |
| `judge.key` | the `knos-oidc` key account that verified the signature on chain | the token account |
| `payees` | one to four: GitHub id, share in basis points, what it received, and the wallet that received it | the `knos3:paid` log lines |
| `amounts` | the mint and its decimals; `paid` (to the payees), `of` (the order's amount), `fee` (to Knos) and `tip` (to whoever relayed the paying transaction) | the `knos3:settled` log line |
| `transaction` | the paying transaction: signature, slot, block time | the cluster |

Amounts are decimal strings in the mint's smallest units, because a 64-bit amount does not fit a JSON number. Ids
and counts are JSON numbers.

## The rules a schema cannot say

A valid receipt also holds these (all are in `knos.receipt.check`, and each has a vector that breaks it):

1. The payees' shares add up to 10000 basis points, and what they received adds up to `amounts.paid`, which is more
   than zero and at most `amounts.of`.
2. A public receipt's `scope` is `sha256("knos3:scope" || repository id || issue)`, both as 64-bit little-endian.
3. A `repository` judge's `repository_id` is the order's repository. A `neutral` judge and an `arbiter` ran
   `workflow_dispatch` in a repository the actor owns (`repository_owner_id` equals `actor_id`). A private order is
   judged by its `attestor`.
4. The run was a first attempt on a GitHub-hosted runner, and the workflow is pinned by a 40-character commit.
5. The payment is not earlier than the token's `iat`.
6. No field is missing and none is unknown.

## The digest

`sha256` over the canonical form: the JSON with every object's keys sorted, no white space, UTF-8, non-ASCII
characters not escaped (`json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`). A receipt
holds only strings, integers below 2^53, `null`, arrays and objects, so every JSON library writes the same bytes.
The digest of the version 1 receipt above is `00d1d55151775720cdbc70e6a44902ea6588ddb6450f887f266c981938824265`.

## What a receipt is not

It is not a signature and proves nothing by itself: it is an index to things that do (GitHub's signature, verified
on chain; the program's transfer). A reader who needs proof follows `transaction.signature` and `judge.key`. It says
the terms were attested as met, not that the work is good.

## As a Solana Attestation Service attestation

A receipt is written on chain as an attestation of the
[Solana Attestation Service](https://solana.com/docs/tools/attestations), so that other programs and indexers find
it where they look for attestations. `scripts/sas_receipt.mjs` does it, for a receipt of either version:

```
node scripts/sas_receipt.mjs receipt.json                           # dry run: prints the three instructions
node scripts/sas_receipt.mjs receipt.json --send --keypair KEY.json  # devnet only
node scripts/sas_receipt.mjs --init --send --keypair KEY.json        # the release step: the credential and the schema
```

Issuing it is **on by default** wherever Knos issues a receipt: `knos.receipt.attest(receipt)` runs the script with
`--send`, and `knos receipt mirror` calls it for every order new to the mirror. The opt-out is `--no-attest`, or
`KNOS_NO_SAS=1`. It fails soft: it runs after the paying transaction is confirmed and after the mirror's files are
written, it never raises, and a payment never waits on it. An order attested already is a clean no-op. It needs
`KNOS_SAS_KEYPAIR` (the key file of the credential's authority, funded with devnet SOL) and Node with
`npm ci --prefix scripts`; without them it says so and nothing else changes.

The release step, once, with the key that will be the credential's authority:

```
npm ci --prefix scripts
node scripts/sas_receipt.mjs --init --send --keypair KEY.json
```

It creates the credential `knos` and the schema `acceptance-receipt` version 1 when they do not exist, and sends
nothing when they do. Then `KNOS_SAS_KEYPAIR` is set where receipts are issued. The public relay does not call
`attest` yet: it settles and exits, and the attestation is written by the next `knos receipt mirror` run.

| | |
|---|---|
| program | `22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG` |
| library | `sas-lib` 1.0.10 (`deriveCredentialPda`, `deriveSchemaPda`, `deriveAttestationPda`, `getCreateCredentialInstruction`, `getCreateSchemaInstruction`, `getCreateAttestationInstruction`, `serializeAttestationData`) |
| credential | name `knos`; its authority and only signer is the key that runs the script |
| schema | name `acceptance-receipt`, version 1 |
| attestation nonce | the order's address: one attestation per order, at an address anyone derives from the order |

| schema field | layout code | from the receipt |
|---|---|---|
| `receipt_sha256` | 13 (bytes) | the digest above |
| `order` | 12 (string) | `order` |
| `scope` | 13 | `scope` |
| `repository_id`, `issue` | 3 (u64) | `repository`; both 0 for a private order |
| `commit` | 12 | `artifact.commit` |
| `pull_request` | 3 | `artifact.pull_request` |
| `terms_hash` | 13 | `terms.hash` |
| `judge_kind` | 0 (u8) | 0 repository, 1 neutral, 2 attestor, 3 arbiter |
| `judge_run_id` | 3 | `judge.claims.run_id` |
| `payees` | 12 | `id.bps.amount.wallet`, joined by `,` |
| `mint` | 12 | `amounts.mint` |
| `paid`, `fee` | 3 | `amounts.paid`, `amounts.fee` |
| `transaction` | 12 | `transaction.signature` |

What was confirmed on 3 October 2026, and how: the program's address is the `declare_id!` in
[`program/src/lib.rs`](https://github.com/solana-foundation/solana-attestation-service/blob/master/program/src/lib.rs)
of the service's repository, and `getAccountInfo` on the public RPC of devnet and of mainnet returns an executable
program at that address on both; `sas-lib` 1.0.10 is the version the npm registry serves, and the function names,
their inputs and the layout codes were read in its published files. The script's dry run builds all three
instructions with that library and its digest equals the Python one (the test checks both).

What was **not** confirmed: no attestation was sent to devnet from here (it needs a funded devnet key), so the
credential and the schema do not exist on devnet until the release step above is run, and the instructions have not been accepted by the deployed program; `expiry` is sent as 0 on the assumption that 0 means
"does not expire"; and the attestation is the word of the credential's authority, not of a program. Having the
escrow itself attest by CPI (a program address among the credential's signers) is described by the service and is
not built here.
