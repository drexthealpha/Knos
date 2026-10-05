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

What the chain does not show: that the build does what its source says (that is what the tests, the fuzzing and the
proofs are for), or that anyone outside Knos has followed it. Everything here is devnet.

## The chains

<!-- provenance:begin -->

Assembled by `python scripts/provenance.py --write` from web/upgrades.json (the multisig's accounts as the feed read them; its `generated` says when), docs/capabilities.json, programs-v2/program_ids.json, docs/facts.json, CHANGELOG.md and docs/provenance.json (one read of the cluster; its `read` says when).
Cluster: devnet. Upgrade multisig: `9HcsMEo2o6zZu9t1kbFWpnyKn7hiHaZYYFwNHZSpmWqK`, 2 of 3, time lock 48 hours (web/upgrades.json `time_lock`; docs/facts.json checks 48 hours against the cluster at release).

| program | public id | devnet runs, as docs/capabilities.json records it | the chain is about | links recorded | complete |
|---|---|---|---|---|---|
| knos_oidc | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | 2.0 | proposal 3 (pending in web/upgrades.json), knos_oidc 2.1 | 5 of 7 | no |
| knos_pay | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | 2.0 | proposal 4 (pending in web/upgrades.json), knos_pay 2.1 | 5 of 7 | no |
| knos_meter | `FUMKkcE95x2kZUj1zZTCbgcYBmJ3WXPHL8pyA8J6anX` | 1.0 | proposal 5 (pending in web/upgrades.json), knos_meter 1.1 | 5 of 7 | no |
| knos_passkey | `FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85` | 1.0 | proposal 6 (pending in web/upgrades.json), knos_passkey 1.1 | 5 of 7 | no |

### knos_oidc

Public id `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W`. docs/capabilities.json records version 2.0 running there. The chain below is the build of proposal 3, knos_oidc 2.1, which was approved and had not executed when web/upgrades.json was generated: the public id runs the older build until it does, and the live state is in web/upgrades.json. Release note: CHANGELOG.md, 0.3.14.

What the public id ran when docs/provenance.json was read: `71f8fe068c94ce69262e7fa250f65fc149334d60f6742ad66ac6b91624c0d1df`; the commit and the run that built it are **MISSING**: upgrade_gate holds no build record for that hash, so nothing on chain ties that build to a commit.

| # | link | what is recorded | recorded in |
|---|---|---|---|
| 1 | source commit | [`6eb81dd152bd6cf752ee6c151b692f4a08815ae5`](https://github.com/drexthealpha/Knos/commit/6eb81dd152bd6cf752ee6c151b692f4a08815ae5) | web/upgrades.json |
| 2 | verified-build run | run `37237561915` of `.github/workflows/program.yml` (job `verified-build`), which upgrade_gate recorded on chain with the commit; the record holds the run's number and not its repository: the release reads runs of drexthealpha/Knos, so look at https://github.com/drexthealpha/Knos/actions/runs/37237561915 | web/upgrades.json |
| 3 | build hash | `3758348d1051feab739b4dc776ffb597fe9ecef7d50e93abd3c460fa5e9f7d4d` (sha256 of the executable; read from the buffer) | web/upgrades.json |
| 4 | hash on chain | `71f8fe068c94ce69262e7fa250f65fc149334d60f6742ad66ac6b91624c0d1df` (NOT the build above: its proposal had not executed; when it was read is `read` in docs/provenance.json) | docs/provenance.json |
| 5 | upgrade proposal | proposal 3 (3n6Vu67CRaUYK9sBYVwnKu9FexF5ZP9yKREnaizKaeLr): Approved, approved by 2 of 2, can execute once the time lock has run (`earliest_execution_utc` of this entry in the feed says when) | web/upgrades.json |
| 6 | execution transaction | **MISSING**: the proposal had not executed when web/upgrades.json was generated | docs/provenance.json |
| 7 | exercised scenario | **MISSING**: nothing can be exercised at the public id before the proposal executes; a run on a staging deployment is not evidence | docs/capabilities.json |

Not complete: 2 of 7 links are MISSING (execution transaction, exercised scenario).

### knos_pay

Public id `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k`. docs/capabilities.json records version 2.0 running there. The chain below is the build of proposal 4, knos_pay 2.1, which was approved and had not executed when web/upgrades.json was generated: the public id runs the older build until it does, and the live state is in web/upgrades.json. Release note: CHANGELOG.md, 0.3.14.

What the public id ran when docs/provenance.json was read: `75d7eb959f75575f6816942ad18a97c93a01690782e2b82ce01d7823c94e0a69`; the commit and the run that built it are **MISSING**: upgrade_gate holds no build record for that hash, so nothing on chain ties that build to a commit.

| # | link | what is recorded | recorded in |
|---|---|---|---|
| 1 | source commit | [`6eb81dd152bd6cf752ee6c151b692f4a08815ae5`](https://github.com/drexthealpha/Knos/commit/6eb81dd152bd6cf752ee6c151b692f4a08815ae5) | web/upgrades.json |
| 2 | verified-build run | run `37237561915` of `.github/workflows/program.yml` (job `verified-build`), which upgrade_gate recorded on chain with the commit; the record holds the run's number and not its repository: the release reads runs of drexthealpha/Knos, so look at https://github.com/drexthealpha/Knos/actions/runs/37237561915 | web/upgrades.json |
| 3 | build hash | `2ed301a2bc99fc6e58abc0dcb767cb35e640898a75f154b2d90c09171143d507` (sha256 of the executable; read from the buffer) | web/upgrades.json |
| 4 | hash on chain | `75d7eb959f75575f6816942ad18a97c93a01690782e2b82ce01d7823c94e0a69` (NOT the build above: its proposal had not executed; when it was read is `read` in docs/provenance.json) | docs/provenance.json |
| 5 | upgrade proposal | proposal 4 (4nDjbSWXPGsqHRzyPgcoYSdaXPqhM7hURN3Enr8Js7nA): Approved, approved by 2 of 2, can execute once the time lock has run (`earliest_execution_utc` of this entry in the feed says when) | web/upgrades.json |
| 6 | execution transaction | **MISSING**: the proposal had not executed when web/upgrades.json was generated | docs/provenance.json |
| 7 | exercised scenario | **MISSING**: nothing can be exercised at the public id before the proposal executes; a run on a staging deployment is not evidence | docs/capabilities.json |

Not complete: 2 of 7 links are MISSING (execution transaction, exercised scenario).

### knos_meter

Public id `FUMKkcE95x2kZUj1zZTCbgcYBmJ3WXPHL8pyA8J6anX`. docs/capabilities.json records version 1.0 running there. The chain below is the build of proposal 5, knos_meter 1.1, which was approved and had not executed when web/upgrades.json was generated: the public id runs the older build until it does, and the live state is in web/upgrades.json. Release note: CHANGELOG.md, 0.3.14.

What the public id ran when docs/provenance.json was read: `0253391fe7558df98e3f11d66f5902d2e4d7d0ae6606a3156ccadb61e93eacde`; upgrade_gate's record ties that build to commit `567fd12ca41af083f422b0e3f19e5c26cb8a3144` and run `37190964532`.

| # | link | what is recorded | recorded in |
|---|---|---|---|
| 1 | source commit | [`6eb81dd152bd6cf752ee6c151b692f4a08815ae5`](https://github.com/drexthealpha/Knos/commit/6eb81dd152bd6cf752ee6c151b692f4a08815ae5) | web/upgrades.json |
| 2 | verified-build run | run `37237561915` of `.github/workflows/program.yml` (job `verified-build`), which upgrade_gate recorded on chain with the commit; the record holds the run's number and not its repository: the release reads runs of drexthealpha/Knos, so look at https://github.com/drexthealpha/Knos/actions/runs/37237561915 | web/upgrades.json |
| 3 | build hash | `10f2b6cbb4983527a82225b29491941b77961da32245b449c9c1b151a5e995e4` (sha256 of the executable; read from the buffer) | web/upgrades.json |
| 4 | hash on chain | `0253391fe7558df98e3f11d66f5902d2e4d7d0ae6606a3156ccadb61e93eacde` (NOT the build above: its proposal had not executed; when it was read is `read` in docs/provenance.json) | docs/provenance.json |
| 5 | upgrade proposal | proposal 5 (244HX9wyPMjypMLPkiSr2qJgv9vg4sVH1Jrz7oq24p3z): Approved, approved by 2 of 2, can execute once the time lock has run (`earliest_execution_utc` of this entry in the feed says when) | web/upgrades.json |
| 6 | execution transaction | **MISSING**: the proposal had not executed when web/upgrades.json was generated | docs/provenance.json |
| 7 | exercised scenario | **MISSING**: nothing can be exercised at the public id before the proposal executes; a run on a staging deployment is not evidence | docs/capabilities.json |

Not complete: 2 of 7 links are MISSING (execution transaction, exercised scenario).

### knos_passkey

Public id `FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85`. docs/capabilities.json records version 1.0 running there. The chain below is the build of proposal 6, knos_passkey 1.1, which was approved and had not executed when web/upgrades.json was generated: the public id runs the older build until it does, and the live state is in web/upgrades.json. Release note: CHANGELOG.md, 0.3.14.

What the public id ran when docs/provenance.json was read: `888d3b68d3f80d4e512f58cf566c0e0123f4e92eaccd59c507be8486b59c84d5`; upgrade_gate's record ties that build to commit `567fd12ca41af083f422b0e3f19e5c26cb8a3144` and run `37190964532`.

| # | link | what is recorded | recorded in |
|---|---|---|---|
| 1 | source commit | [`6eb81dd152bd6cf752ee6c151b692f4a08815ae5`](https://github.com/drexthealpha/Knos/commit/6eb81dd152bd6cf752ee6c151b692f4a08815ae5) | web/upgrades.json |
| 2 | verified-build run | run `37237561915` of `.github/workflows/program.yml` (job `verified-build`), which upgrade_gate recorded on chain with the commit; the record holds the run's number and not its repository: the release reads runs of drexthealpha/Knos, so look at https://github.com/drexthealpha/Knos/actions/runs/37237561915 | web/upgrades.json |
| 3 | build hash | `a9ce7a06fb99196ce6a9516b7c52951e48e4ce8cfde256646c6e50cfcac7cf81` (sha256 of the executable; read from the buffer) | web/upgrades.json |
| 4 | hash on chain | `888d3b68d3f80d4e512f58cf566c0e0123f4e92eaccd59c507be8486b59c84d5` (NOT the build above: its proposal had not executed; when it was read is `read` in docs/provenance.json) | docs/provenance.json |
| 5 | upgrade proposal | proposal 6 (DQ35JZ6CSq1iwzG78x6xn4wyTBYsFPnS3kDkrt4BWkVb): Approved, approved by 2 of 2, can execute once the time lock has run (`earliest_execution_utc` of this entry in the feed says when) | web/upgrades.json |
| 6 | execution transaction | **MISSING**: the proposal had not executed when web/upgrades.json was generated | docs/provenance.json |
| 7 | exercised scenario | **MISSING**: nothing can be exercised at the public id before the proposal executes; a run on a staging deployment is not evidence | docs/capabilities.json |

Not complete: 2 of 7 links are MISSING (execution transaction, exercised scenario).

<!-- provenance:end -->

## Keeping it current

The release runs `python scripts/provenance.py --rpc --record --write` after `scripts/upgrade_feed.py`: the first
reads the cluster into `docs/provenance.json` with the time of the read, the second rewrites the block above. Between
releases the block is as old as the reads it names. `python scripts/provenance.py --rpc` prints the live state
without writing anything, and `--strict` exits 1 while any chain is incomplete.
