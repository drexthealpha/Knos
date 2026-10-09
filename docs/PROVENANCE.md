# Provenance: from source to a run on chain

A test that passes on source says nothing about a deployed program unless the two are tied together. This page is
that tie for each of the four programs of the second deployment, as one chain a stranger can follow link by link:

    source commit -> verified-build run -> build hash -> the hash on chain at the public program id
                  -> the upgrade proposal and its execution transaction -> one exercised scenario

The block below is written by [`scripts/provenance.py`](../scripts/provenance.py) from files of this repository and
from nothing else; `tests/test_provenance.py` fails when it is not what those files give. A link the records do not
hold is printed as **MISSING** with the reason. Nothing is filled in.

## How to check each link yourself

1. **Source commit.** Open the commit. It is the tree the build was made from.
2. **Verified-build run.** The `verified-build` job of `.github/workflows/program.yml` builds each program with
   `solana-verify build` in a pinned image and hands the hash to `upgrade_gate`, a program on chain that writes it
   down with the commit and the run's number only when GitHub's signed token says that run built it. The record is
   an account anyone can read: `python scripts/provenance.py --rpc` prints it for the hash each program runs.
3. **Build hash.** Make the build yourself from the commit ([ASSURANCE.md](ASSURANCE.md), "compare a deployed program
   with the source") and compare the hash. Nobody outside Knos has reported doing so.
4. **Hash on chain.** `python scripts/provenance.py --rpc` reads the program's data account at the public id and
   prints its hash; `solana-verify get-program-hash <id> -u devnet` reads the same bytes without Knos's code.
5. **Upgrade proposal and execution.** The proposal is an account of the Squads multisig; its state, its approvals
   and the buffer it would deploy are in [`web/upgrades.json`](../web/upgrades.json) and on chain
   ([GOVERNANCE.md](GOVERNANCE.md)). Once it has executed, the transaction that did it is found from the proposal
   account and kept in `docs/provenance.json`.
6. **Exercised scenario.** A transaction at the public id that used the build and succeeded, taken from
   [`docs/capabilities.json`](capabilities.json). A run on a staging deployment of the same build is not one.

## Check one upgrade proposal yourself

    python scripts/provenance.py verify-proposal N --so programs-v2/target/deploy/<program>.so

It reads proposal N of the upgrade multisig from the cluster (`--rpc`, default devnet's public endpoint), the bytes
in the buffer it would deploy (or, once it has run and the buffer is closed, the bytes the program runs), the
record `upgrade_gate` holds for exactly those bytes, and the hash [`web/upgrades.json`](../web/upgrades.json)
printed. With `--so` (or `--hash`) it compares them with a build you made yourself; without, it prints the four
commands that make that build from the recorded commit, in the pinned image of `program.yml`'s verified-build job.
It says VERIFIED, and exits 0, only when a verified-build run recorded these bytes, the feed agrees, and your build
(when given) is the same; it exits 1 otherwise and 2 when the cluster cannot be read. It sends nothing and needs no
key. Tested on fixture accounts (`tests/test_provenance_verify.py`); nobody outside Knos has run it.

Each program's section opens with one table: the source commit, the verified build hash, the program id, the
proposal's number, the slot in which the build went live at the public id, and the transactions that exercised it
there. The last two are filled by `python scripts/exercise_public.py record`, and only for a program whose hash on
chain is the proposal's build: until then they say so.

knos_oidc and knos_pay have a second row in that table: the build this release proposes for them, as one set. Its
source commit and its verified build hash are what `upgrade_gate` recorded for the build the release run made
(`python scripts/exercise_public.py propose` writes them into `docs/provenance.json`, `next`, and
`python scripts/provenance.py --write` fills the row). Until that run has made the build the row says **MISSING**,
and until the proposal has executed it says `not live yet`.

What the chain does not show: that the build does what its source says (that is what the tests, the fuzzing and the
proofs are for), or that anyone outside Knos has followed it. Everything here is devnet.

## The chains

<!-- provenance:begin -->

Assembled by `python scripts/provenance.py --write` from web/upgrades.json (the multisig's accounts as the feed read them; its `generated` says when), docs/capabilities.json, programs-v2/program_ids.json, docs/facts.json, CHANGELOG.md and docs/provenance.json (one read of the cluster; its `read` says when).
Cluster: devnet. Upgrade multisig: `9HcsMEo2o6zZu9t1kbFWpnyKn7hiHaZYYFwNHZSpmWqK`, 2 of 3, time lock 48 hours (web/upgrades.json `time_lock`; docs/facts.json checks 48 hours against the cluster at release).

| program | public id | devnet runs, as docs/capabilities.json records it | the chain is about | links recorded | complete |
|---|---|---|---|---|---|
| knos_oidc | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | 2.2 | proposal 7 (executed in web/upgrades.json), knos_oidc 2.2 | 7 of 7 | yes |
| knos_pay | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | 2.2 | proposal 8 (executed in web/upgrades.json), knos_pay 2.2 | 7 of 7 | yes |
| knos_meter | `FUMKkcE95x2kZUj1zZTCbgcYBmJ3WXPHL8pyA8J6anX` | 1.1 | proposal 5 (executed in web/upgrades.json), knos_meter 1.1 | 7 of 7 | yes |
| knos_passkey | `FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85` | 1.1 | proposal 6 (executed in web/upgrades.json), knos_passkey 1.1 | 7 of 7 | yes |

### knos_oidc

Public id `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W`. docs/capabilities.json records version 2.2 running there. The chain below is the build of proposal 7, knos_oidc 2.2, which runs there now. Release note: CHANGELOG.md, 0.3.16.

What the public id ran when docs/provenance.json was read: `a2df952d262c48edacf2f594a01321e805c28f1dc523cb6efa75f2c45f34e632`; upgrade_gate's record ties that build to commit `f03ec515d8666c46e3fdc6bb0123bc0786d5dd75` and run `37523515307`.

| source commit | verified build hash | program id | proposal | slot it went live | exercise transactions |
|---|---|---|---|---|---|
| `f03ec515d8666c46e3fdc6bb0123bc0786d5dd75` | `a2df952d262c48edacf2f594a01321e805c28f1dc523cb6efa75f2c45f34e632` | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | 7 | 509118532 | [4G2Zew7L...](https://explorer.solana.com/tx/4G2Zew7LgfNJ7v6KjaKceCFRRLBmK5LD7qYK3oUi58b9X3iMhR7dXD7oqr2FuNcvewy65R6N8k7iVD6JbrG5eJJV?cluster=devnet) (`verify_github`), [59bmRFKd...](https://explorer.solana.com/tx/59bmRFKddsFS7uodRzpEUEyahPDwzCU3NrpCQSPN7XcvDpZ6WimHVgMG26jnpY1XUN3sRguFhCp6wfjcUPferAmM?cluster=devnet) (`oidc_strict_json`), [31HzWxXF...](https://explorer.solana.com/tx/31HzWxXFoya7ZKphG9Tb9czvhKT9dZiCGP4F3sSvgkek9x7FLGATqsA1Mba45gpQpNFa8ELLcEUJyXCXZ2f92okk?cluster=devnet) (`outcome_not_code`), [2L4YLehp...](https://explorer.solana.com/tx/2L4YLehpwZ3bKn9corLPDQptRU3Td91tvjs63EanQDDWE26wSQHXYmKu1BgiQ41jQ3MafCtKvAC2N7aJTNNgJABD?cluster=devnet) (`es256_tokens`) |
| MISSING (the release run's verified build is not recorded yet) | MISSING (the release run's verified build is not recorded yet) | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | not proposed yet | not live yet | none: the public id does not run this build yet (not built yet) |

| # | link | what is recorded | recorded in |
|---|---|---|---|
| 1 | source commit | [`f03ec515d8666c46e3fdc6bb0123bc0786d5dd75`](https://github.com/drexthealpha/Knos/commit/f03ec515d8666c46e3fdc6bb0123bc0786d5dd75) | web/upgrades.json |
| 2 | verified-build run | run `37523515307` of `.github/workflows/program.yml` (job `verified-build`), which upgrade_gate recorded on chain with the commit; the record holds the run's number and not its repository: the release reads runs of drexthealpha/Knos, so look at https://github.com/drexthealpha/Knos/actions/runs/37523515307 | web/upgrades.json |
| 3 | build hash | `a2df952d262c48edacf2f594a01321e805c28f1dc523cb6efa75f2c45f34e632` (sha256 of the executable; read from the earlier feed) | web/upgrades.json |
| 4 | hash on chain | `a2df952d262c48edacf2f594a01321e805c28f1dc523cb6efa75f2c45f34e632` (the build above; when it was read is `read` in docs/provenance.json) | docs/provenance.json |
| 5 | upgrade proposal | proposal 7 (73mz8V7F42yLx8ZBXBbikP6nfiozxPC4gY8AREiEczwh): Executed, approved by 2 of 2 | web/upgrades.json |
| 6 | execution transaction | [`2ub9zBNXJKmPh5ikqBxoR5TXuK86YfCT846WTEq8R6VVQhxvYAmAiHqDdbBbyyZmKrBUgft6fiq66wPoq2B53KsT`](https://explorer.solana.com/tx/2ub9zBNXJKmPh5ikqBxoR5TXuK86YfCT846WTEq8R6VVQhxvYAmAiHqDdbBbyyZmKrBUgft6fiq66wPoq2B53KsT?cluster=devnet) | docs/provenance.json |
| 7 | exercised scenario | [`4G2Zew7LgfNJ7v6KjaKceCFRRLBmK5LD7qYK3oUi58b9X3iMhR7dXD7oqr2FuNcvewy65R6N8k7iVD6JbrG5eJJV`](https://explorer.solana.com/tx/4G2Zew7LgfNJ7v6KjaKceCFRRLBmK5LD7qYK3oUi58b9X3iMhR7dXD7oqr2FuNcvewy65R6N8k7iVD6JbrG5eJJV?cluster=devnet) (verify_github: A program on Solana verifies a GitHub Actions OpenID Connect token and other programs read the result.) | docs/capabilities.json |

Every link is recorded and the hash on chain is this build's.

### knos_pay

Public id `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k`. docs/capabilities.json records version 2.2 running there. The chain below is the build of proposal 8, knos_pay 2.2, which runs there now. Release note: **MISSING**: no section of CHANGELOG.md names this build.

What the public id ran when docs/provenance.json was read: `8b3c044024eac6e00cf10930c325465d5682c3fb7273fe2f0d59c6e01f99867c`; upgrade_gate's record ties that build to commit `f8bcd9d51eda5e093cc92b0bcf0c8cc3676fa556` and run `37589002080`.

| source commit | verified build hash | program id | proposal | slot it went live | exercise transactions |
|---|---|---|---|---|---|
| `f8bcd9d51eda5e093cc92b0bcf0c8cc3676fa556` | `8b3c044024eac6e00cf10930c325465d5682c3fb7273fe2f0d59c6e01f99867c` | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | 8 | 509118717 | [4Q1cvM78...](https://explorer.solana.com/tx/4Q1cvM785mimadqAPQTwQyYWHBMZbFWzZ5W1w1zVQZsx3TUEKwesdyQoSimQCiUVJvUhUP6TFW9on5xLKzEn41sK?cluster=devnet) (`fund_from_wallet`), [57E3wRPG...](https://explorer.solana.com/tx/57E3wRPGfY34MFq89Uxi75AS9PMoCT7eFwnXgnfsFpVg9mbtoHB4FVJ5bYNMGLPANuvrYygwc32Su2W8jE5XtVeY?cluster=devnet) (`refund`), [177CEpZ8...](https://explorer.solana.com/tx/177CEpZ8N4r5CGNjSEWBEouTTqMDwAao9LFzwSNYiFjJZUfJdtLDeusHbmmawWxzKLp1SozNAyNCEeGxSvvBm5s?cluster=devnet) (`work_orders`), [59AfaYHT...](https://explorer.solana.com/tx/59AfaYHTvWHhbAhiiNHCbCfEcGCxG1kCydJwfRNjZqry9bCnMF3ox6bd4P7favA9hjgzB5nk283g2Mdq3LruyNWV?cluster=devnet) (`order_pay`), [55Gxtqyo...](https://explorer.solana.com/tx/55GxtqyoErGS6fJgJNNSe87qxJF3sUwgoZZkAQfTQ1eXQYhnqQaB861AQS6u1FXwuBBwY2dmQdWwgH9Zps1YfTVm?cluster=devnet) (`tests_mode`), [55Gxtqyo...](https://explorer.solana.com/tx/55GxtqyoErGS6fJgJNNSe87qxJF3sUwgoZZkAQfTQ1eXQYhnqQaB861AQS6u1FXwuBBwY2dmQdWwgH9Zps1YfTVm?cluster=devnet) (`order_auto_accept`), [3o7qVyZJ...](https://explorer.solana.com/tx/3o7qVyZJ7C2hip61C4NGZ58Bw2Pc6Nk8Rg4S4SnL8WRqwwKaDEfYXcSopdHFPL9CuktBoPQ7fZq59BDcXK5895DP?cluster=devnet) (`holdback_release`), [432L2F98...](https://explorer.solana.com/tx/432L2F987ADLGHRPLuHMoULKQr8pYRMNyb9k2PAMZ5H7CJsix4JgqKbMHLx7yyY5kDmJnAt1Lb6fz5nMwEFhCCQJ?cluster=devnet) (`top_up`), [177CEpZ8...](https://explorer.solana.com/tx/177CEpZ8N4r5CGNjSEWBEouTTqMDwAao9LFzwSNYiFjJZUfJdtLDeusHbmmawWxzKLp1SozNAyNCEeGxSvvBm5s?cluster=devnet) (`single_use_tokens`), [2noSVLKX...](https://explorer.solana.com/tx/2noSVLKXsSDc9iL72m6H4geVenuoDvrH7YiQ4FUEwLUYgEbWpqxk9TZxf6GQegSXCsZUR33GT2gn6HEUbkKTpwsX?cluster=devnet) (`x402_knos_order`), [49ibrvKH...](https://explorer.solana.com/tx/49ibrvKHtWorUFnsCsRb62WMtMqRP3iq5AnRyZwL7CiY8kcBy8yUJo13iN5w88xu4hrQqf7E2FFBc299wwBmzBAf?cluster=devnet) (`presentation_grace`) |
| MISSING (the release run's verified build is not recorded yet) | MISSING (the release run's verified build is not recorded yet) | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | not proposed yet | not live yet | none: the public id does not run this build yet (not built yet) |

| # | link | what is recorded | recorded in |
|---|---|---|---|
| 1 | source commit | [`f8bcd9d51eda5e093cc92b0bcf0c8cc3676fa556`](https://github.com/drexthealpha/Knos/commit/f8bcd9d51eda5e093cc92b0bcf0c8cc3676fa556) | web/upgrades.json |
| 2 | verified-build run | run `37589002080` of `.github/workflows/program.yml` (job `verified-build`), which upgrade_gate recorded on chain with the commit; the record holds the run's number and not its repository: the release reads runs of drexthealpha/Knos, so look at https://github.com/drexthealpha/Knos/actions/runs/37589002080 | web/upgrades.json |
| 3 | build hash | `8b3c044024eac6e00cf10930c325465d5682c3fb7273fe2f0d59c6e01f99867c` (sha256 of the executable; read from the earlier feed) | web/upgrades.json |
| 4 | hash on chain | `8b3c044024eac6e00cf10930c325465d5682c3fb7273fe2f0d59c6e01f99867c` (the build above; when it was read is `read` in docs/provenance.json) | docs/provenance.json |
| 5 | upgrade proposal | proposal 8 (B2Zp53Drtu8H16WBMApdcKa7zBcVjQzqsDo9s3pmw4e6): Executed, approved by 2 of 2 | web/upgrades.json |
| 6 | execution transaction | [`444mkydj88tL7HMQ1S97Rviw8YrZAERjUzkXJtk6phV96wE1JDDx6frgK8v1p2hxWsBT9ZyniR78x5g7zMFW3ibt`](https://explorer.solana.com/tx/444mkydj88tL7HMQ1S97Rviw8YrZAERjUzkXJtk6phV96wE1JDDx6frgK8v1p2hxWsBT9ZyniR78x5g7zMFW3ibt?cluster=devnet) | docs/provenance.json |
| 7 | exercised scenario | [`4Q1cvM785mimadqAPQTwQyYWHBMZbFWzZ5W1w1zVQZsx3TUEKwesdyQoSimQCiUVJvUhUP6TFW9on5xLKzEn41sK`](https://explorer.solana.com/tx/4Q1cvM785mimadqAPQTwQyYWHBMZbFWzZ5W1w1zVQZsx3TUEKwesdyQoSimQCiUVJvUhUP6TFW9on5xLKzEn41sK?cluster=devnet) (fund_from_wallet: A wallet funds a task with its own money.) | docs/capabilities.json |

Every link is recorded and the hash on chain is this build's.

### knos_meter

Public id `FUMKkcE95x2kZUj1zZTCbgcYBmJ3WXPHL8pyA8J6anX`. docs/capabilities.json records version 1.1 running there. The chain below is the build of proposal 5, knos_meter 1.1, which runs there now. Release note: CHANGELOG.md, 0.3.14.

What the public id ran when docs/provenance.json was read: `10f2b6cbb4983527a82225b29491941b77961da32245b449c9c1b151a5e995e4`; upgrade_gate's record ties that build to commit `6eb81dd152bd6cf752ee6c151b692f4a08815ae5` and run `37237561915`.

| source commit | verified build hash | program id | proposal | slot it went live | exercise transactions |
|---|---|---|---|---|---|
| `6eb81dd152bd6cf752ee6c151b692f4a08815ae5` | `10f2b6cbb4983527a82225b29491941b77961da32245b449c9c1b151a5e995e4` | `FUMKkcE95x2kZUj1zZTCbgcYBmJ3WXPHL8pyA8J6anX` | 5 | 508314467 | [4FxxZjQD...](https://explorer.solana.com/tx/4FxxZjQD8aqqTNRuiT3nS5e3Hh1f1UitCcRmfhBbMiiTj6w9wgRP5HDFUHicpXyCt5vmrue53oyGQM9unQgPWSzR?cluster=devnet) (`meter_batch`), [3zJVYD2y...](https://explorer.solana.com/tx/3zJVYD2yxjz4vgi4NsED3cvjRnToboXdM9YPz2xyawkCUKcbUSNNY4rVhYuNMyNNY6LyTPwzFhrNzFdNn1i8N4Hc?cluster=devnet) (`meter_seller_claim`) |

| # | link | what is recorded | recorded in |
|---|---|---|---|
| 1 | source commit | [`6eb81dd152bd6cf752ee6c151b692f4a08815ae5`](https://github.com/drexthealpha/Knos/commit/6eb81dd152bd6cf752ee6c151b692f4a08815ae5) | web/upgrades.json |
| 2 | verified-build run | run `37237561915` of `.github/workflows/program.yml` (job `verified-build`), which upgrade_gate recorded on chain with the commit; the record holds the run's number and not its repository: the release reads runs of drexthealpha/Knos, so look at https://github.com/drexthealpha/Knos/actions/runs/37237561915 | web/upgrades.json |
| 3 | build hash | `10f2b6cbb4983527a82225b29491941b77961da32245b449c9c1b151a5e995e4` (sha256 of the executable; read from the earlier feed) | web/upgrades.json |
| 4 | hash on chain | `10f2b6cbb4983527a82225b29491941b77961da32245b449c9c1b151a5e995e4` (the build above; when it was read is `read` in docs/provenance.json) | docs/provenance.json |
| 5 | upgrade proposal | proposal 5 (244HX9wyPMjypMLPkiSr2qJgv9vg4sVH1Jrz7oq24p3z): Executed, approved by 2 of 2 | web/upgrades.json |
| 6 | execution transaction | [`3K2h2Q4DMHp1gSf7rgAprAmt5VFfuDUzUMEDmCjMrnpF2AkBf3dp4B6htszgXu6mY1Zo1JCt7fSwTnFEHb4n3g5Z`](https://explorer.solana.com/tx/3K2h2Q4DMHp1gSf7rgAprAmt5VFfuDUzUMEDmCjMrnpF2AkBf3dp4B6htszgXu6mY1Zo1JCt7fSwTnFEHb4n3g5Z?cluster=devnet) | docs/provenance.json |
| 7 | exercised scenario | [`4FxxZjQD8aqqTNRuiT3nS5e3Hh1f1UitCcRmfhBbMiiTj6w9wgRP5HDFUHicpXyCt5vmrue53oyGQM9unQgPWSzR`](https://explorer.solana.com/tx/4FxxZjQD8aqqTNRuiT3nS5e3Hh1f1UitCcRmfhBbMiiTj6w9wgRP5HDFUHicpXyCt5vmrue53oyGQM9unQgPWSzR?cluster=devnet) (meter_batch: One signed token counts a batch of evaluations under a Merkle root.) | docs/capabilities.json |

Every link is recorded and the hash on chain is this build's.

### knos_passkey

Public id `FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85`. docs/capabilities.json records version 1.1 running there. The chain below is the build of proposal 6, knos_passkey 1.1, which runs there now. Release note: CHANGELOG.md, 0.3.14.

What the public id ran when docs/provenance.json was read: `a9ce7a06fb99196ce6a9516b7c52951e48e4ce8cfde256646c6e50cfcac7cf81`; upgrade_gate's record ties that build to commit `6eb81dd152bd6cf752ee6c151b692f4a08815ae5` and run `37237561915`.

| source commit | verified build hash | program id | proposal | slot it went live | exercise transactions |
|---|---|---|---|---|---|
| `6eb81dd152bd6cf752ee6c151b692f4a08815ae5` | `a9ce7a06fb99196ce6a9516b7c52951e48e4ce8cfde256646c6e50cfcac7cf81` | `FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85` | 6 | 508314496 | [3oTzLPyD...](https://explorer.solana.com/tx/3oTzLPyDoqerUgRKdqEBEirtLCYhwTb5keUpjECPsD92Zf3UjwkS72s9KNcZntUuE1dKZhMs8cwJyhx7kcYEqdmC?cluster=devnet) (`passkey_funder`), [3oTzLPyD...](https://explorer.solana.com/tx/3oTzLPyDoqerUgRKdqEBEirtLCYhwTb5keUpjECPsD92Zf3UjwkS72s9KNcZntUuE1dKZhMs8cwJyhx7kcYEqdmC?cluster=devnet) (`passkey_fund_relay`), [3oTzLPyD...](https://explorer.solana.com/tx/3oTzLPyDoqerUgRKdqEBEirtLCYhwTb5keUpjECPsD92Zf3UjwkS72s9KNcZntUuE1dKZhMs8cwJyhx7kcYEqdmC?cluster=devnet) (`buyer_page`) |

| # | link | what is recorded | recorded in |
|---|---|---|---|
| 1 | source commit | [`6eb81dd152bd6cf752ee6c151b692f4a08815ae5`](https://github.com/drexthealpha/Knos/commit/6eb81dd152bd6cf752ee6c151b692f4a08815ae5) | web/upgrades.json |
| 2 | verified-build run | run `37237561915` of `.github/workflows/program.yml` (job `verified-build`), which upgrade_gate recorded on chain with the commit; the record holds the run's number and not its repository: the release reads runs of drexthealpha/Knos, so look at https://github.com/drexthealpha/Knos/actions/runs/37237561915 | web/upgrades.json |
| 3 | build hash | `a9ce7a06fb99196ce6a9516b7c52951e48e4ce8cfde256646c6e50cfcac7cf81` (sha256 of the executable; read from the earlier feed) | web/upgrades.json |
| 4 | hash on chain | `a9ce7a06fb99196ce6a9516b7c52951e48e4ce8cfde256646c6e50cfcac7cf81` (the build above; when it was read is `read` in docs/provenance.json) | docs/provenance.json |
| 5 | upgrade proposal | proposal 6 (DQ35JZ6CSq1iwzG78x6xn4wyTBYsFPnS3kDkrt4BWkVb): Executed, approved by 2 of 2 | web/upgrades.json |
| 6 | execution transaction | [`4AgyQUDedwhkC8pQMQUPbiKcrLwnpM828ThbVybxZ4eRrhvZD1p2kfURBXrXUHibKxzQv68E85eMKyWf77BgG6fn`](https://explorer.solana.com/tx/4AgyQUDedwhkC8pQMQUPbiKcrLwnpM828ThbVybxZ4eRrhvZD1p2kfURBXrXUHibKxzQv68E85eMKyWf77BgG6fn?cluster=devnet) | docs/provenance.json |
| 7 | exercised scenario | [`3oTzLPyDoqerUgRKdqEBEirtLCYhwTb5keUpjECPsD92Zf3UjwkS72s9KNcZntUuE1dKZhMs8cwJyhx7kcYEqdmC`](https://explorer.solana.com/tx/3oTzLPyDoqerUgRKdqEBEirtLCYhwTb5keUpjECPsD92Zf3UjwkS72s9KNcZntUuE1dKZhMs8cwJyhx7kcYEqdmC?cluster=devnet) (passkey_funder: A funder with only a passkey funds an order and a relayer pays the transaction fee.) | docs/capabilities.json |

Every link is recorded and the hash on chain is this build's.

<!-- provenance:end -->

## Keeping it current

After the upgrade has executed, `python scripts/exercise_public.py run` exercises the builds at the public ids and
`record` writes the slot each went live and the exercise transactions ([RELEASE.md](RELEASE.md), "After the upgrade
executes"). The release runs `python scripts/provenance.py --rpc --record --write` after `scripts/upgrade_feed.py`: the first
reads the cluster into `docs/provenance.json` with the time of the read, the second rewrites the block above. Between
releases the block is as old as the reads it names. `python scripts/provenance.py --rpc` prints the live state
without writing anything, and `--strict` exits 1 while any chain is incomplete.
