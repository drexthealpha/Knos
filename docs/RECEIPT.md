# The acceptance receipt

A settlement on Knos leaves three public facts: a work order, a token GitHub or GitLab signed that says the order's
terms were met, and a transaction that paid. The **acceptance receipt** is one JSON document that joins them. It
holds nothing private and nothing that is not already public, so anyone can rebuild it from the chain and compare
digests. It is what a buyer files, what a seller shows, and what a third party attests to.

A signature proves who signed, not that what was signed is true. So a receipt keeps five things apart, always in
this order and under these headings, in the JSON and in what `knos receipt` prints (versions 3 and 4; version 2 has the
four that are not the commercial authorisation, and `knos receipt` prints all five headings for it and says what it
does not carry):

1. **What the issuer authenticated** (`issuer_authenticated`). GitHub or GitLab signed: which workflow file, at which
   commit, ran in which repository, for which event, and when. `verified` names the `knos_oidc` program, the key
   account and the transaction in which that signature was verified on chain.
2. **What the evaluator observed** (`evaluator_observed`). The pinned judge's verdict, the named checks and their
   conclusions, the accepted commit and pull request, and the judge's version (the commit of its workflow). And who
   controls each judge that spoke, recorded and not asserted ([Evaluator independence](#evaluator-independence)).
3. **Which policy produced the verdict** (`policy`). The hash of the terms fixed at funding, the mode, the allowed
   and denied paths, and the terms' version.
4. **Who authorised the money, and under which limit** (`commercial_authorisation`). Who funded, from what, under
   which limit that funding passed, whether the funder was the Balance's owner or a listed spender, and whether this
   deliverable (the order and its milestone) was paid before ([Version 3](#version-3)).
5. **What trust remains** (`trust_remaining`). The list, in plain words: the host's signing key and its runner; the
   code of the pinned workflow; the repository's administrators for a merge-mode order; the account that ran the
   judge when it was not the order's own repository; and Knos's upgrade multisig (the programs are upgradeable only
   through a multisig with a public 48-hour delay, until an outside review). The list follows from the provider, the
   mode and the judge, and a receipt that leaves one out is not valid.

Beside the verdict itself `knos receipt` prints the trusted parties in one line, so nobody reads "accepted" without
them:

```
   The pinned judge (repository, version cccc...) gave the verdict: accepted.
   trusted: GitHub's signing key and runner; the pinned workflow at cccc...; the repository's administrators (the merge is the acceptance); Knos's upgrade multisig (public 48-hour delay).
```

Then `amendments`: every change of the order's terms between its funding and this payment (a top-up, an assignment
of the payment, a reservation, a cancellation, a change of the funder's plan), oldest first, each with its
transaction, so an order's terms history is explicit. Then the payment itself.

- Schema: [`docs/receipt/acceptance-receipt.v4.schema.json`](receipt/acceptance-receipt.v4.schema.json) (JSON Schema
  2020-12); version 3: [`acceptance-receipt.v3.schema.json`](receipt/acceptance-receipt.v3.schema.json); version 2: [`acceptance-receipt.v2.schema.json`](receipt/acceptance-receipt.v2.schema.json); version 1:
  [`acceptance-receipt.v1.schema.json`](receipt/acceptance-receipt.v1.schema.json). A reader accepts all four.
- Conformance vectors: [`docs/receipt/vectors.json`](receipt/vectors.json): of version 1, five receipts a reader
  must accept, with their digests, and nine a reader must refuse; of version 2, the same five and eight to refuse;
  of version 3, five to accept and twelve to refuse. Version 4:
  [`docs/receipt/vectors.v4.json`](receipt/vectors.v4.json), twelve to accept (each with its verdict and whether it
  authorises payment) and twenty-four to refuse
- Reference code: [`src/knos/receipt.py`](../src/knos/receipt.py) (`build2`, `build3`, `build4`, `unpaid4`, `dispute`,
  `authorises_payment`, `exposed`, `limitations_of`, `ids_of`, `authorisation`, `evaluator`, `independence_of`,
  `upgrade`, `as2`, `as3`, `check`, `render`, `canonical`, `digest`); the tests are `tests/test_receipt.py`,
  `tests/test_verdicts_ids.py`, `tests/test_bundle.py` and `tests/test_receipt_offline.py`
- Commands: `knos receipt FILE` (check and print), `knos receipt explain FILE [--json]` (the five parts, below),
  `knos receipt mirror --out DIR`, `knos receipt verify ORDER
  [--mirror DIR]`, `knos bundle make ORDER [--verdict FILE]`, `knos bundle verify FILE [--rpc URL] [--mirror DIR]`,
  and with the chain gone `knos bundle verify FILE --no-chain` and `knos receipt verify FILE --no-chain`

## The five parts of a receipt

Every receipt of version 4 or 5 reads in five parts. This is a view (`knos.receipt.parts`), not a version: it adds
nothing to a receipt, changes no digest, and is computed from the receipt's own fields.

| Part | It answers | It is read from |
| --- | --- | --- |
| Identity | Who produced the evidence: the issuer, the repository, the workflow, the run | `issuer_authenticated` (or, when nobody signed, `evidence_source`) |
| Execution | Which evaluator ran, on which inputs, by hash | `evaluator_observed.judge`, `.artifact`, `.evaluators`, their `reexecution` |
| Acceptance | Which agreed test passed, under which terms hash | `evaluator_observed.verdict`, `.checks`, `policy`, `disputed` |
| Consequence | What amount became payable, to whom, in which order | `amounts`, `payees`, `order`, `transaction`, `ids` |
| Assurance | The level, and in plain words what stayed trusted or outside the evaluation | `assurance` (computed for version 4), `limitations`, the evaluators' ids against the payees' and the funder's |

```
knos receipt explain receipt.json          # five numbered parts, each one line, then what stands behind it
knos receipt explain receipt.json --json   # the same as data: {kind: "knos-receipt-parts", v: 1, weak, parts: [...]}
```

Each part is `{id, title, asks, line, facts, more}`: `line` is one sentence, `facts` the fields behind it, `more` the
sentences a reader opens. The site's Verifier page shows the same five rows for a pasted receipt
(`web/verifier.js`, `receiptParts`); `tests/data/receipt_parts.json` holds receipts and the answer, and both readers
are held to it word for word. The page reads and does not check the receipt's rules or a signature.

**A valid signature on a weak test reads as weak.** `weak` is true, and the Assurance line starts with `WEAK`, when
any of these holds, each computed and none typed:

- nobody outside the supplier's reach ran the checks again (the level is `reported`);
- no issuer signed anything (the evidence is the run's own record);
- the terms name no check and the order is paid on a merge, so the merge alone was the acceptance;
- an evaluator's owner or starter is a payee ("The evaluator's account is the payee's"), or the funder;
- the evaluators that spoke are one party.

Every receipt, weak or not, also lists what stayed outside the evaluation: that the workflow file decides what it
reads (the issuer signed which workflow ran, not what it ran), that the order's own repository judged when it did,
and that nothing shows the terms asked for the right thing. A receipt that is not weak is not a proof that the work
is right: its Assurance part still names who is trusted at its level.

Versions 1 and 2 are not read this way (they do not say who funded); a version 3 receipt is read as the version 4
receipt `build4` makes of it. An account id above 2^53 (a GitLab id as the program stores it) is read exactly by the
command and rounded by a browser's JSON reader: for those, use the command.

## Version 5

Version 4 says what was concluded. Version 5 says **how much was verified**. It is version 4 with one more field,
`assurance`, and `knos.receipt.build5` writes it from a version 4 receipt:

```json
"assurance": {
  "level": "rerun",
  "trusted": ["The issuer, for which workflow ran, ...", "The one evaluator that ran the suite again, ..."],
  "declared_related": [[9001, 31337]]
}
```

**The level is computed from the evidence, never typed.** `knos.receipt.assurance_of` reads the receipt's own
fields, and `check` computes the level again and refuses a receipt that says another.

| level | what the evidence shows | who is still trusted |
|---|---|---|
| `reported` | A workflow reported the result. Every receipt reaches this. | The issuer, for which workflow ran. The run that reported, and whoever controls its repository, workflow and runner. The supplier, as far as the suite ran where the supplier's change could reach it. Whoever wrote the terms. |
| `rerun` | An evaluator outside the order's repository, whose owner and starter are no payee and not declared one party with a payee, says by its run's own word (`reexecution.reexecuted`) that it ran the pinned suite itself. | The issuer. That one evaluator, its operator and its runner: nobody else repeated it. Whoever wrote the terms. |
| `agreed` | Two such evaluators, with different owners and starters and not declared one party, each ran the suite, and the verdict they stand behind is accepted. | The issuer. That the two are not one party behind accounts nobody declared related. Their runners. Whoever wrote the terms. |
| `attested` | An attestation of the execution itself stands behind the result. | The root the attestation chains to, and the maker of the hardware or prover behind it. Whoever wrote the terms. |

`attested` is defined and unreachable. Nothing Knos records today is an attestation of execution, so
no receipt may say `attested`: `check` refuses one. The level exists so that a reader knows what is missing.

The rerun is the run's own word. The issuer signs which workflow ran, not what it did; `check` holds the run and
repository those words name to the ones the issuer signed, and no more. `rerun` therefore still trusts that one
evaluator, and the table says so.

**Declared control relationships.** Each entry of `evaluator_observed.evaluators` names the evaluator's repository
owner (`owner_id`) and actor (`actor_id`), as in version 3. `same_controller` is true when two evaluators share an
id. Two accounts run by one person share none, so the terms can declare them: `assurance.declared_related` is a
list of groups of account ids that are one party, each group and the list in rising order, overlapping groups
merged (`knos.receipt.related`). `knos.receipt.independence_of(evaluators, declared)` then answers for both: a
shared id, or a declared group. Two evaluators are never `agreed` if their owners match or the terms declare them
related, and an evaluator declared one party with a payee is not outside the supplier's control. A relationship
nobody declared cannot be found by any receipt; that is the trust the `agreed` row names.

**Older receipts.** Versions 1 to 4 still check, with the digests they always had. `assurance_of` reads the level
of any version: an older receipt is `reported` unless its evidence shows more (a version 3 or 4 receipt whose
evaluator entry carries a re-execution reads as `rerun`). `as4` gives a reader of version 4 the version 4 receipt a
version 5 one holds. A mirror's copy, made from the chain alone, does not carry the runs' own words and reads
`reported` (`chain_only`). A disputed version 5 receipt contests the version 5 form of the receipt it contests; a
dispute does not move the level, which is of the evidence.

Version 5 is what is written since 0.3.19: `knos bundle make`, `knos receipt mirror`, the relay's attestation of a
payment and the receipt `knos attest` leaves for a run that paid nothing all write it (`build5` over the version 4
receipt, so the level is computed and never typed). `knos bundle make --terms3 FILE` reads the declared control
relationships from the Knos Terms 3 document the order cites, and refuses a document the order does not cite; a run
of `knos attest` reads them from the repository's own copy of that document. Without one, nothing is declared.
`knos bundle verify` takes versions 2 to 5, and so do the webhook verifiers (`integrations/webhook`). One version 5
receipt of a public payment has been written (0.3.19): `knos bundle make` of an order a neutral attest.yml run in
drexthealpha/knos-attest judged again and [paid](https://explorer.solana.com/tx/3i37jK6P7hWyMntNgEKT3TsiSQQcHzNh7Dku4zsZC3m1E53ynAJZvzBgKUyahH7C9eH2A6ctRHwuSdTSqFkWfGND?cluster=devnet).
Its evaluator entry says `reexecuted: true`, and its level is `reported`, not `rerun`: the run's owner and starter
and the payee are one GitHub account, the only one Knos's release run has. No `rerun` receipt exists yet.

- Schema: [`docs/receipt/acceptance-receipt.v5.schema.json`](receipt/acceptance-receipt.v5.schema.json).
- Conformance vectors: [`docs/receipt/vectors.v5.json`](receipt/vectors.v5.json): seven to accept, each with its
  level, and twelve to refuse (a level typed higher or lower than the evidence gives, `attested`, a trusted party
  left out, a declared relationship dropped or added, a malformed group).

## Version 4

Versions 1 to 3 are receipts of one thing: an accepted deliverable that was paid. Version 4 is a receipt of an
**evaluation**, whatever it concluded. It has everything version 3 has, and four more fields.

**The verdict is one of four words** (`evaluator_observed.verdict`, [`src/knos/ids.py`](../src/knos/ids.py)):

| verdict | what it means | payment |
|---|---|---|
| `accepted` | the policy's conditions were met at this commit | the receipt records the payment and stands behind it |
| `rejected` | they were not met, as this evaluator saw it | none recorded, none authorised |
| `insufficient_evidence` | the run could not tell: a check has no run, a record is missing | none recorded, none authorised; it is not an acceptance and it is not the supplier's failure |
| `disputed` | somebody contested a verdict and nobody has resolved it | none authorised; a payment already made stays on record |

A receipt that says rejected or insufficient evidence is a **valid receipt**: `check` accepts it, it has a digest,
a mirror keeps it. What it never does is authorise payment: `knos.receipt.authorises_payment` is true for a valid
receipt whose verdict is `accepted` and for no other. Such a receipt has `transaction` null, `amounts.paid`, `fee`
and `tip` "0", every payee's amount "0" and `ids.settlement` null. A named check's `conclusion` is `passed`,
`failed` or `missing`; an accepted receipt has every one `passed`.

**Every receipt answers six questions**, and `knos.receipt.exposed` gives them for a receipt of any version:

| question | field (version 4) |
|---|---|
| which artifact | `evaluator_observed.artifact`: the commit and the pull request |
| which policy version | `policy`: the terms' hash and `version` |
| what the evidence is | `evidence_source` |
| who evaluated | `evaluator_observed.judge` (the kind and the workflow's commit) and `evaluators` (who controls each) |
| the verdict | `evaluator_observed.verdict` |
| what the evidence does not show | `limitations` |

**`evidence_source`** is `{kind, reference, signed_by}`. `issuer_token`: a token the issuer signed and `knos_oidc`
verified; `reference` is its sha256 and `signed_by` its issuer. `run_record`: the run's own record, signed by
nobody; `reference` is the record's sha256 or null, `signed_by` is null, `issuer_authenticated` and
`commercial_authorisation` are null and no controller of the evaluator is recorded. A run's own record can say
rejected or insufficient evidence. It can never say accepted: an accepted receipt records the token and the payment.

**`limitations`** is a list of plain sentences: what this evidence does not show. The first ones follow from the
evidence source, the verdict, the mode, whether the evaluator's entry says how it reached its verdict, and whether
money moved (`knos.receipt.limitations_of`), and a receipt that leaves one out is not valid. Up to eight of the
writer's own may follow. For a signed, accepted receipt of a merge-mode order they begin:

- The issuer signs which workflow ran, in which repository and run, not what it read, ran or concluded.
- The verdict is the pinned workflow's under the policy named here. It does not show that the policy asked for the right thing.
- In merge mode the merge is the acceptance: no test was run for this receipt, and it does not show that the code works.
- Accepted means the policy's conditions were met at this commit. It does not show that the work has no defect.
- This receipt does not record whether the evaluator ran the acceptance suite itself or read another run's record.

**`ids`** names four things by ids of their own, so that a milestone carried by ten pull requests is never
confused with one of them (docs/METER.md, [Four ids on every surface](METER.md#four-ids-on-every-surface)):
`deliverable` (the order and the milestone), `evaluation` (that deliverable, the commit, the terms' hash, the
evaluator as `<judge>@<workflow commit>` and the run the issuer signed for), `invoice_line` (the supplier's line,
or null) and `settlement` (the paying transaction, or null when nothing was paid). `check` computes the first, the
second and the fourth again from the receipt's own fields, and refuses an id of one kind in the place of another.

**`disputed`** is null unless the verdict is `disputed`. Then it says who contested, when, why, and the receipt
contested:

    "disputed": {"by": {"role": "buyer", "id": "424242"}, "at": 1790090000, "reason": "...",
                 "contests": {"sha256": "<the contested receipt's digest>", "verdict": "accepted"}}

`role` is buyer, supplier, evaluator or other. A disputed receipt is the contested one with the verdict replaced, so
`check` rebuilds the contested receipt from it and holds `contests.sha256` to its digest (`knos.receipt.contested`
returns it). A dispute of a paid receipt is dated after the payment and keeps the payment on record. The receipt
does not say how a dispute ends: the resolution is a new receipt, or a correction in the meter's ledger.

The parts of a receipt nothing was paid for, here the vector "rejected: a check failed":

```json
{
  "evaluator_observed": {
    "verdict": "rejected",
    "checks": [
      {
        "name": "build",
        "conclusion": "passed"
      },
      {
        "name": "test",
        "conclusion": "failed"
      }
    ]
  },
  "ids": {
    "deliverable": "dlv_ad4acb4e779aaf12f543a1c5",
    "evaluation": "evl_77909506260b3e3ec98e28f0",
    "invoice_line": null,
    "settlement": null
  },
  "evidence_source": {
    "kind": "run_record",
    "reference": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
    "signed_by": null
  },
  "limitations": [
    "No issuer signed this: the verdict is the run's own record, and whoever controls the run or its record could have written another.",
    "The verdict is the pinned workflow's under the policy named here. It does not show that the policy asked for the right thing.",
    "The named checks are what was looked at, at this commit and in the run's own environment. Nothing outside them was looked at.",
    "Rejected means the policy's conditions were not met at this commit, as this evaluator saw it. It does not show that the work is wrong. It authorises no payment.",
    "This receipt does not record whether the evaluator ran the acceptance suite itself or read another run's record.",
    "No payment is recorded here: this receipt does not show that anything was paid, or that anything is owed."
  ],
  "disputed": null,
  "transaction": null
}
```

What version 4 does not change: the digest rule, the five parts and their order, and every rule of version 3,
which a version 4 receipt of a signed run is held to as it stands (`as3` gives the version 3 receipt an accepted,
paid one holds, byte for byte). What is not done yet, said plainly: `knos bundle make` and the relay still write
version 3 (an accepted payment); `build4` writes that receipt as version 4, and nothing in a pinned workflow
writes a rejected or an insufficient receipt yet. The Solana Attestation Service script takes versions 1 to 3.

## Version 3

A version 3 receipt is a version 2 receipt (below) of the same payment with two additions: the fifth part,
`commercial_authorisation`, between `policy` and `trust_remaining`, and inside `evaluator_observed` the record of who
controls each judge. `knos bundle make` and `knos receipt mirror` write version 3. Versions 1 and 2 still verify;
`knos.receipt.build3` writes a version 2 receipt as version 3 and `knos.receipt.as2` gives back the version 2 one it
holds (the Solana Attestation Service attestation is still written from that version 2 form).

The fifth part of the first version 3 vector (digest `sha256:b5e2275e4ed2a1b19ca2eb5dc79ba3a1303f321ad5db4784c42970f6d0ea1fa1`):

```json
{
 "funder": {
  "github_id": 424242,
  "login": "octo",
  "wallet": null
 },
 "source": {
  "kind": "balance",
  "address": "7tj9biW3KRJ7EEWmVUGigHiouCTXhV2dzcyvwma7Cyu7",
  "owner_id": 424242
 },
 "limit": {
  "cap_per_order": "50000000",
  "daily": "200000000",
  "total": "0",
  "repositories": [
   987654321
  ]
 },
 "role": "owner",
 "deliverable": {
  "order": "J222WNWuZwhfgRBMc4jDu9MjGG6eCc2Up8P4FFADWVYp",
  "milestone": 0
 },
 "billed_before": false,
 "funded": "32acN4jvkNEGnU1QuTZx2U8BFLdxJMfJPtyVHsDnvGxgnC8Kn9gVd6TpbofWWjCuXiEZyesEaSgHs3njsZxr3tLk"
}
```

| field | what it is | where it comes from |
|---|---|---|
| `funder` | who funded: a GitHub account (`github_id`, and `login` as the funding token named it, `null` when the token's transactions are no longer in the records read), or a `wallet` | the `by=` field of the `knos3:funded` log line; the `actor` claim of the funding token |
| `source` | from what: `wallet` (the funder's own money), `balance` (an organisation's Balance, with `owner_id`, its owner's id) or `passkey` (a passkey wallet) | the `source=` field of that line; the `knos2:balance` line; the `knosp:funded` line |
| `limit` | the limit that funding passed under: the Balance's cap for one order, its daily and total limits (`"0"`: none of that kind) and its repository allow-list. `"no limit set"` when none is set, and for a wallet; `null` when the Balance was opened before the history read | the Balance's opening instruction (the cap); the `knos2:balancex` line and its instruction (the `balx` side account: daily, total, repositories), as last set before the funding |
| `role` | `owner` when the funder is the Balance's owner, `spender` when the Balance lists it as one, `wallet` or `passkey` when the money's own key signed | computed: the program lets only the owner or a listed spender spend a Balance |
| `deliverable` | what was bought: the `order` and its `milestone` (0, or the pull request of a standing order's payment). One identity, however many pull requests carried the work | the order; the token's audience |
| `billed_before` | `false`, or the transaction of an earlier payment of this order and milestone | the escrow's history. The program pays an order's milestone once, so anything but `false` is a finding |
| `funded` | the funding transaction, `null` when the history read does not reach it | the `knos3:funded` line |

What this part does not show, said plainly. The cap is the one the Balance was opened with: the instruction that
changes a cap or the spenders afterwards (SetBalance) prints no log line, so a later change is not in the record a
receipt is built from. And the limits are the chain's record of what was set; whether the person who set them had
the authority inside their company to do so is not something a chain can know.

### Evaluator independence

Two accounts run by one person are one judge. A receipt cannot know who is behind an account, so it does not say
that judges are independent: it records who controls each judge that spoke, from the ids its issuer signed, and
computes two flags from them. The judges of the third version 3 vector, a quorum of two:

```json
{
 "evaluators": [
  {
   "kind": "repository",
   "repository_id": 1353152983,
   "owner_id": 640000,
   "actor_id": 7001,
   "runner": "github-hosted",
   "independent_of_buyer": false,
   "independent_of_seller": false
  },
  {
   "kind": "neutral",
   "repository_id": 900100200,
   "owner_id": 7001,
   "actor_id": 7001,
   "runner": "github-hosted",
   "independent_of_buyer": true,
   "independent_of_seller": false
  }
 ],
 "same_controller": true,
 "independence": "These judges are not independent of each other: account 7001 owns or started more than one of them. Two accounts run by one person are one judge, and so are two runs of one account: count this quorum as one judge."
}
```

| field | what it is |
|---|---|
| `kind` | which judge: `repository` (a run in the buyer's repository, the order's own), `neutral` (a run its starter owns), `attestor` (the judge repository the order named), `arbiter` |
| `repository_id`, `owner_id` | the repository the run was in, and the id of its owner (`repository_owner_id` in the token) |
| `actor_id` | who started the run |
| `runner` | the token's `runner_environment`: `github-hosted`, or `self-hosted` (the program pays only on a hosted runner's token, so a receipt of a payment says hosted; the field is the signed value, not an assumption) |
| `independent_of_buyer` | `true` when neither the owner nor the starter is the funder or the Balance's owner. Always `false` for the order's own repository: the buyer chose it and its administrators can accept. `null` when the funder is a wallet, which has no account id to compare with |
| `independent_of_seller` | `true` when neither the owner nor the starter is a payee |
| `same_controller` | on the quorum: `true` when two judges share an owner or a starter (or the starter of one owns the other). `knos receipt` then prints `SAME CONTROLLER.` and the sentence in `independence`: count the quorum as one judge |

The flags are computed, not chosen: `check` computes them again and refuses a receipt whose flags differ, and the
last entry must be the judge whose token paid, with the ids that token carries. A flag that says `true` says two
ids differ. It does not say two people differ.

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
| `receipt.json` | the receipt, version 3, in canonical form (a bundle with a version 2 receipt still verifies) |
| `token.jwt` | the raw token the issuer signed, read back from the transactions that wrote it to `knos_oidc` |
| `key.json` | the issuer's public key that verified it (`issuer`, `kid`, `n`, `e`) and its key account |
| `terms.json` | the order's terms: the bytes hashed at funding |
| `checks.json` | the check runs, commit statuses and changed files of the accepted commit, as fetched, reduced to the fields a verdict reads and put in one order |
| `judge.json` | the judge's kind and version, and `inputs_sha256`: the sha256 of `checks.json` |
| `verdict.json` | optional, for an order in tests mode: the judge's verdict, added by `--verdict FILE` (below) |
| `chain.json` | the archived copy of the chain record: the paying transaction, the funding transaction and the one that verified the token, each as the cluster gave it (logs, instructions, accounts) with its slot, block time and blockhash; and the verifier's key account |
| `keys.json` | the list of keys the issuer published (GitHub: `https://token.actions.githubusercontent.com/.well-known/jwks`), as fetched, with `retrieved_at`. Left out when the list could not be fetched |

A bundle that holds `chain.json` or `keys.json` says version 2 in its manifest; a bundle without them is version 1,
the layout earlier releases wrote, and both verify.

`knos bundle make <order> --verdict FILE` puts the judge's own verdict in the bundle as `verdict.json`. `FILE` is what
`knos proof judge --evidence` wrote: the hashes of the two trees the judge ran on, the hash of the acceptance checks,
its assurance (in-process, black-box or hermetic), and the image digest when it ran in one. The trees are not in the
bundle. `verify` refuses a `verdict.json` that is not a passed verdict on the acceptance checks hashed at funding, or
that names another image than the terms do, and `knos judge rerun <bundle> --base DIR --pr DIR` runs the judge again
on trees you check out and says when they are not the ones the verdict names. Without `--verdict`, a bundle of a
tests-mode order says "assurance: not said by this bundle"; in merge mode no judge ran the code and it says that none
is claimed.

The tar is deterministic: names in order, times zero, mode 0644, no owner. Two builds of one order are the same
bytes, whoever makes them (the test builds it twice with the host answering in another order), with one exception:
`keys.json` carries the time the issuer's key list was fetched, so two builds made at different times differ in that
file and in the manifest's line for it. Every other file is the same.

`knos bundle verify <tar>` uses no network. It checks every file against the manifest; the token's RS256 signature
against the included key; that the key is the one at the key account the receipt names (the address is derived from
the key); the claims, the order, the commit, the terms hash and the payees against the token; `terms.json` against
the terms hash; and then derives the verdict again from the terms and the checks. It prints the five parts.

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

## Verifying with the chain gone

```
knos bundle verify FILE --no-chain              # no cluster is asked; the issuer's key list is, when the network is there
knos bundle verify FILE --no-chain --no-network # nothing is asked of anyone
knos receipt verify FILE --no-chain             # the same, under `knos receipt`
knos receipt verify ORDER --no-chain --mirror DIR   # the receipt alone, from a mirror
```

`--no-chain` proves from the bundle alone everything that does not need a cluster, and prints three lists so that
nobody mistakes one kind of statement for another:

1. **Verified from signatures.** The token's RS256 signature against the key in `key.json`; that the key is the
   one whose address the receipt names (the address is derived from the key); the audience the issuer signed
   against the order, the artifact (commit and pull request), the terms hash and the payees; `terms.json` against
   that terms hash; and, when the network is there, that the issuer serves this key now.
2. **Resting on an archived copy in the bundle, signed by nobody.** The verdict derived again from `checks.json`
   (what the host answered when the bundle was made). The key's identity against the issuer's published list in
   `keys.json`, with the time it was retrieved. The wallets paid, the amounts, the fee and the tip against the
   archived paying transaction, printed with its slot and blockhash. The verifier's key account as it was. For a
   version 3 receipt, the funder and the source of the money against the archived funding transaction.
3. **Could not be checked without a cluster.** That a cluster holds the paying transaction at that slot; that the
   key account holds this key today and has not been revoked since; that the token's single-use marker is on chain.

An issuer's keys rotate out. When the issuer no longer serves the key that signed, `--no-chain` says so and falls
back to the archived list, labelled as the archive. When a list names the key's id with another key, that is not a
rotation and the check fails. When neither list has the key (the bundle was made after the rotation), the line
moves to the third list and names what is left: the verifier's key account, in the archived chain record.

The limit, in the command's own words: the archive is a copy and nobody signed it, so whoever rebuilds a bundle can
rewrite the archive together with the receipt. What holds it is the other party's copy (compare the bundle's
sha256, which `verify` prints) or a mirror's digest of the receipt (`--mirror`). The blockhash is recorded as
fetched; with the cluster gone nothing can be compared with it.

`tests/test_receipt_offline.py` builds a bundle on the LiteSVM harness with the programs as built, throws the
harness away, verifies with no chain, then changes each archived piece in turn (seventeen changes, each with its
manifest rebuilt, and a flipped byte in each of the eight files) and checks that the failure names the piece.

## What survives a devnet reset

Devnet is a test cluster and its ledger can be reset
([Solana's cluster documentation](https://solana.com/docs/references/clusters)). After a reset:

- **The receipt** still checks against the rules of this document and still has its digest.
- **The bundle** still verifies with `--no-chain`: the issuer's signature, the terms, the audience and the verdict
  need no cluster.
- **The mirror** still serves every receipt it was given, checked against its own index.
- **The chain record becomes an archived copy.** The transaction and its logs are in `chain.json` as they were
  fetched, with the slot and blockhash, and every line that rests on them says so. The order's accounts, the
  token's single-use marker and the key account are gone with the ledger, and a version 1 bundle (made before
  0.3.15) has no `chain.json`: its wallets and amounts are then the receipt's word.

Nothing a customer is invoiced for depends on devnet staying up: an invoice line is a deliverable with its
evaluation and its receipt, and those verify from signatures. Money on devnet is test USDC; a reset loses test
balances and open test orders, not the evidence of what was accepted. What a reset does take is the ability to ask
a third party (the cluster) whether a rewritten bundle is the true one, which is why both sides hold the same
bundle and a mirror holds its receipt's digest.

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

Version 4 adds (each has a vector in `vectors.v4.json`): an accepted receipt records the issuer's token and the
payment, with every named check passed; a rejected or insufficient receipt records no payment; `ids` are the ones
the receipt's own fields give, each of its own kind; `evidence_source` names the token when there is one and
nothing signed when there is none; `limitations` begins with the sentences the evidence leaves; and a disputed
receipt contests exactly the receipt its `contests.sha256` names, after any payment it records.

## The digest

`sha256` over the canonical form: the JSON with every object's keys sorted, no white space, UTF-8, non-ASCII
characters not escaped (`json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`). A receipt
holds only strings, integers below 2^53, `null`, arrays and objects, so every JSON library writes the same bytes.
The digest of the version 1 receipt above is `00d1d55151775720cdbc70e6a44902ea6588ddb6450f887f266c981938824265`.

## What a receipt is not

It is not a signature and proves nothing by itself: it is an index to things that do (GitHub's signature, verified
on chain; the program's transfer). A reader who needs proof follows `transaction.signature` and `judge.key`. It says
the terms were attested as met, not that the work is good. A version 4 receipt says this itself, in `limitations`.

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
