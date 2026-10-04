# The acceptance receipt

A settlement on Knos leaves three public facts: a work order, a token GitHub signed that says the order's terms were
met, and a transaction that paid. The **acceptance receipt** is one JSON document that joins them: who signed what,
about which artifact, under which terms, and what was paid for it. It holds nothing private and nothing that is not
already public, so anyone can rebuild it from the chain and compare digests. It is what a buyer files, what a seller
shows, and what a third party attests to.

- Schema: [`docs/receipt/acceptance-receipt.v1.schema.json`](receipt/acceptance-receipt.v1.schema.json) (JSON Schema 2020-12)
- Conformance vectors: [`docs/receipt/vectors.json`](receipt/vectors.json): five receipts a reader must accept, with
  their digests, and nine a reader must refuse
- Reference code: [`src/knos/receipt.py`](../src/knos/receipt.py) (`build`, `check`, `canonical`, `digest`); the
  test is `tests/test_receipt.py`

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
| `type`, `version` | `knos.acceptance-receipt`, `1`. A reader refuses a version it does not know | |
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
characters not escaped (`json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`). Version 1
holds only strings, integers below 2^53, `null`, arrays and objects, so every JSON library writes the same bytes.
The digest of the receipt above is `00d1d55151775720cdbc70e6a44902ea6588ddb6450f887f266c981938824265`.

## What a receipt is not

It is not a signature and proves nothing by itself: it is an index to things that do (GitHub's signature, verified
on chain; the program's transfer). A reader who needs proof follows `transaction.signature` and `judge.key`. It says
the terms were attested as met, not that the work is good.

## As a Solana Attestation Service attestation

A receipt can be written on chain as an attestation of the
[Solana Attestation Service](https://solana.com/docs/tools/attestations), so that other programs and indexers find
it where they look for attestations. `scripts/sas_receipt.mjs` does it:

```
node scripts/sas_receipt.mjs receipt.json                           # dry run: prints the three instructions
node scripts/sas_receipt.mjs receipt.json --send --keypair KEY.json  # devnet only
```

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
instructions have not been accepted by the deployed program; `expiry` is sent as 0 on the assumption that 0 means
"does not expire"; and the attestation is the word of the credential's authority, not of a program. Having the
escrow itself attest by CPI (a program address among the credential's signers) is described by the service and is
not built here.
