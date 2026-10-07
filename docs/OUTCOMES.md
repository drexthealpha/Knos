# Outcomes other than a merged pull request

Each domain needs its own acceptance model; Knos supplies the fixed terms, the signed run and the count, not the model.

An order pays, or the meter counts, when a pinned suite passes on an artifact. Nothing in that sentence says "pull
request". What the artifact is, and what a suite must do to deserve the word "accepted", differs for every kind of
work, and somebody who knows the work has to write it. This page shows three such models that run in this repository
and one that is not built, with the reason. One of the three is also signed by an issuer that is not a forge:
[a Kubernetes cluster](#a-kubernetes-cluster-signs-an-outcome).

| Outcome | Artifact | What the suite checks | What it cannot check | Status |
|---|---|---|---|---|
| [Data labelling](../examples/outcomes/data-labelling/) | `labels.csv`: a label for each of 400 items | Schema; accuracy at least 0.90 on 120 gold items never shown; recall at least 0.80 for each class; the 40 visible examples no more than 0.10 above the gold ones (copied answers) | The 280 items outside both samples, except by inference; whether the gold labels are right; secrecy of the gold file from a labeller who can read the repository | Example runs here; never used by a customer |
| [Data transformation](../examples/outcomes/data-transformation/) | `transform.sql` | On 40 input tables made from fixed seeds: schema, one row per key, every input customer and charge counted once, totals equal to the input's to the cent, each row equal to a reference | Inputs shaped unlike the generator's; speed at production volume; other database engines | Example runs here; never used by a customer |
| [Reproducible research](../examples/outcomes/reproducible-research/) | `analysis.py` and `RESULT.json`, the number it is said to give | Run again in the sandbox with the order's seed: the number matches within 0.000001; a second run agrees; when the input is moved by a known amount the number moves by it (a pasted number does not) | Whether the method answers the question; whether the data are real; whether the seed or the method was chosen after looking | Example runs here; never used by a customer |
| Support-ticket resolution | none that Knos can read | nothing | see below | Not built |

`tests/test_outcomes.py` puts every submission of the three examples through `knos proof judge`. Each example holds
the black-box suite and, beside it, a naive check that looks only at what the supplier was shown. The honest submission
is accepted by both. The cheating submission (copied visible labels; the worked example's answer written down; a
result pasted into the script) is accepted by the naive check and refused by the black-box suite.

## Funded by a comment, paid by the suite

Each example is an order the ordinary flow funds and pays: a comment, a pull request, the black-box verdict, the
payment. Put the example's `base/` in a repository (its suite becomes `.knos/acceptance/<issue>/` for the issue you
fund), then comment on that issue:

| Outcome | The comment | The terms it funds |
|---|---|---|
| Data labelling | `/knos fund 40 checks: none` | `knos terms show data-labelling` |
| Data transformation | `/knos fund 150 checks: none` | `knos terms show data-transformation` |
| Reproducible research | `/knos fund 90 checks: none` | `knos terms show reproducible-research` |

`checks: none` because the suite is the acceptance: the terms are in tests mode and carry the suite's hash, and the
reply to the comment says so. 150 is more than the devnet faucet gives per comment (100), so that one needs a Balance.
Each `terms show` prints the terms as bytes and their hash; they are the example's own `terms.json`
(`tests/test_flow_quorum3.py::test_each_outcome_has_a_template_whose_terms_are_the_examples_own`).

**What was run.** One test, for data labelling, from the comment to the payment:
`tests/test_flow_quorum3.py::test_a_labelled_dataset_is_funded_by_a_comment_and_only_the_honest_file_is_paid`.
The comment funds a work order whose terms are byte for byte the example's; the cheating `labels.csv` (the 40 visible
answers copied) passes the naive check and is refused by the suite, so nothing is signed and nothing is paid; the
honest file passes, the job after the judge signs for its commit, and the order pays 40 test USDC in full. The test
then names what the meter would count: one deliverable, `sha256(order || milestone)`, and two evaluations under one
policy version (the hash of the terms), one rejected and one accepted, with the audience the meter's token carries.

**What was not run.** GitHub and the relay in that test are stand-ins (`tests/_flow.py`), and the program is the
real `knos_pay` build in a simulator (LiteSVM), funded there with the same terms bytes and paid on a token with the
same fields. The pull requests are stand-ins too: the judge ran on the example's folders, not on commits. All of it ran in tests:
never on devnet, and never by a customer. The transformation and research examples have a template and a verdict
test (`tests/test_outcomes.py`) and no flow test of their own. No evaluation of these was sent to the meter.

## A Kubernetes cluster signs an outcome

Every outcome above is judged in a workflow, and the forge signs for the run. The verifier takes any RS256 issuer
([VERIFIER.md](VERIFIER.md)), so the signer does not have to be a forge. This section takes the data-transformation
example and has a Kubernetes cluster sign its evaluation: a workload identity, and no code under review.

| Step | What happens | Where it is | State |
|---|---|---|---|
| 1. The cluster | A kind cluster starts on a GitHub-hosted runner with the service-account issuer `https://kind.knos-outcome.invalid` | [`outcome-k8s.yml`](../.github/workflows/outcome-k8s.yml) | run in staging: [run 37483745385](https://github.com/drexthealpha/knos-rc/actions/runs/37483745385) of drexthealpha/knos-rc, commit 92f6197, started the kind cluster on a GitHub-hosted runner; nothing of it is on devnet |
| 2. The Job | The example's black-box suite judges `transform.sql` in a Kubernetes Job under the service account `knos-judge` | [`outcome_k8s_job.yaml`](../scripts/outcome_k8s_job.yaml), `scripts/outcome_k8s.py job` | the judging step is tested here outside a cluster; the Job ran in the kind cluster of staging [run 37483745385](https://github.com/drexthealpha/knos-rc/actions/runs/37483745385) |
| 3. The token | The pod asks its own cluster (the TokenRequest API) for a token of `knos-judge` whose audience is the evaluation, `knosm:eval:...`, the meter's audience | `scripts/outcome_k8s.py job` | the kind cluster of staging [run 37483745385](https://github.com/drexthealpha/knos-rc/actions/runs/37483745385) issued it |
| 4. Offline check | The token is checked against the cluster's key set (`kubectl get --raw /openid/v1/jwks`) by the on-chain verifier's rule, and a receipt is written | `scripts/outcome_k8s.py verify` | tested here on a token of the same shape signed by a test key; the kind cluster's token of staging [run 37483745385](https://github.com/drexthealpha/knos-rc/actions/runs/37483745385) verified offline against that cluster's key set |
| 5. Devnet | A wallet registers the cluster's key as a private key, the token is written and stepped, and its account is VERIFIED | `scripts/outcome_k8s.py chain` | implemented; tested here in the test build of the verifier (LiteSVM); sent to devnet only by the release run (the `issuer` round of `scripts/exercise_public.py`) |
| 6. The count | The evaluation is one line of the seller's ledger | `knos meter batch --claim` | the line is written by step 5; see "What the meter does with it" |

The run uploads one artifact, `outcome-k8s`: `token`, `jwks.json`, `openid-configuration.json`, `issuer`,
`verdict.json` (the verdict, the suite's hash, the hash of each file judged), `receipt.json`, `cluster.txt` (the
versions of kind and Kubernetes and the image's id) and `SHA256SUMS`.

**What the receipt says.** `issuer_authenticated` names the cluster as the issuer (`provider: kubernetes`,
`forge: false`), the key's size and hash, and the claims: which service account, which pod, which audience.
`evaluator_observed` is the verdict and what was judged. `ids` are the deliverable's and the evaluation's
(`knos.ids`). And `limitations`, always:

- The cluster ran on a runner that Knos started: one party ran the cluster, the Job and the judge.
- The issuer is self-hosted. Its URL does not resolve and its key set was read from the cluster's own API server, so
  nobody outside that run can fetch the key and compare it.
- This shows that the path works for a workload identity that is not a forge. It does not show that an independent
  party ran it.
- The cluster signed which service account asked for this audience. It did not sign what the Job read or decided.
- The buyer, the seller and the work order are the example's sample values. Nobody bought this.

**What the meter does with it.** Not what it does with a forge's token, and the difference is the program's.
`knos_meter` Record takes a token of GitHub's from a pinned workflow and refuses a token verified under a private
key (error 122). A cluster nobody outside can reach can only be a private key: the wallet that registers it says
whose it is. And a service-account token's `aud` is a list, which the reader on chain does not read, so no program
there can require the audience; the offline check does. So on chain there is a VERIFIED token account that names the
cluster's URL by its hash and the registering wallet, and the evaluation is counted as a line of the seller's
ledger, the seller's own claim ([METER.md](METER.md), `ClaimBatch`). A count of cluster-signed evaluations that the
buyer's credits pay for needs a change to the meter: an attested key for the issuer, and an audience read from a
one-element list. That is not in this release. And with the example's sample buyer and seller the batch stays a
ledger file: a ClaimBatch on chain needs a seller id that owns the repository the claim's workflow runs in, and
nothing here does that for this outcome.

### Run it

In the repository, on GitHub (no key, no secret):

    gh workflow run outcome-k8s.yml
    gh run watch "$(gh run list --workflow outcome-k8s.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
    gh run download --name outcome-k8s --dir out

Check the artifact again on your own machine; nothing is sent:

    (cd out && sha256sum -c SHA256SUMS)
    python scripts/outcome_k8s.py verify --token out/token --jwks out/jwks.json --issuer "$(cat out/issuer)" \
        --verdict out/verdict.json --out out/receipt.json

Then devnet, with a devnet wallet, on the verifier's 2.1 build, which the public id runs since proposal 3 executed
(private keys are part of 2.1). The token is asked for six hours and the verifier reads one until an hour after it expires, so this follows
the run the same day. The first command lists the transactions and sends none; `--send` sends them:

    python scripts/outcome_k8s.py chain --token out/token --jwks out/jwks.json --issuer "$(cat out/issuer)" \
        --receipt out/receipt.json --keypair ~/.config/solana/id.json
    python scripts/outcome_k8s.py chain --token out/token --jwks out/jwks.json --issuer "$(cat out/issuer)" \
        --receipt out/receipt.json --keypair ~/.config/solana/id.json --send
    knos meter batch out/evaluation.jsonl --ledger outcomes.ledger --month "$(date -u +%Y-%m)" --claim

`chain` checks the token again before any fee, registers the key (RegisterPrivateKey, KeyParams), writes the token
and runs the two steps, reads the token account back, and adds the program, the key account, the token account, the
wallet and the transactions to the receipt under `issuer_authenticated.verified.onchain`. It refuses any cluster of
Solana but devnet or a localnet.

**What was run here.** `tests/test_outcome_k8s.py`: a token with the claims of a projected service-account token
(`aud` a list, a nested `kubernetes.io`), signed by a fixed test key, passes the offline rule and gets the receipt
above; sixteen wrong ones are refused (ES256, another key, a broken signature, a 1024-bit key, an elliptic-curve
key set, a key id the set lacks, another issuer, an `exp` too far ahead or not a number, an expired token, another audience, two audiences,
another service account, a claim written twice, a payload that is not strict JSON); and the test build of the
verifier verifies the same token under a private key through the instructions `chain` builds, and refuses another
key's signature with the program's own error. **What ran in staging:** [run 37483745385](https://github.com/drexthealpha/knos-rc/actions/runs/37483745385) of drexthealpha/knos-rc (commit 92f6197) started a kind cluster, ran the
Job in it and had the cluster issue the token by the TokenRequest API; `scripts/outcome_k8s.py verify` verified that
token offline against the cluster's own key set (`https://kind.knos-outcome.invalid`, RS256). **What was not run:**
anything on devnet. No transaction carries a cluster's token, and the meter does not count it on chain.

**What was looked up, and where** (read 2026-10-06):

| Fact | Source |
|---|---|
| A service-account token is a JWT with `aud` as a list and a nested `kubernetes.io`; the API server signs RS256, ES256, ES384 or ES512 by the type of its key; a requested token lives at least 600 seconds | [Kubernetes, Managing Service Accounts](https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/) |
| The issuer must be an `https` URL; the API server serves `/.well-known/openid-configuration` and `/openid/v1/jwks`, readable by every service account | [Kubernetes, Configure Service Accounts for Pods](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/) |
| `--service-account-issuer` is the `iss` of issued tokens; `--service-account-max-token-expiration` caps a requested lifetime | [kube-apiserver reference](https://kubernetes.io/docs/reference/command-line-tools-reference/kube-apiserver/) |
| kubeadm makes keys RSA-2048 unless `encryptionAlgorithm` says otherwise | [kubeadm configuration (v1beta4)](https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta4/) |
| A kind cluster takes API server flags through `kubeadmConfigPatches` (`ClusterConfiguration`, `apiServer.extraArgs`) | [kind, Configuration](https://kind.sigs.k8s.io/docs/user/configuration/) |
| kind v0.33.0 writes kubeadm's v1beta4 config from Kubernetes v1.36, where `extraArgs` is a list of `name` and `value`; its node image for v1.37.0 is `kindest/node:v1.37.0@sha256:a1ed56cf…`, which the workflow pins | [kind v0.33.0](https://github.com/kubernetes-sigs/kind/releases/tag/v0.33.0) |
| The `ubuntu-24.04` runner image has Kind 0.33.0, Kubectl 1.37.0 and Docker 28.0.4 (image 20260907.300.1), so the workflow adds no action | [actions/runner-images](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md) |

What the sources do not settle and the run will: that this version of kind accepts the patch as written, and that
this cluster's key is RSA. The workflow fails in plain words on either (the key set is printed with each key's type
and size). The Job's base image is `python:3.12-slim`: the run pulls the tag, builds the Job's image from the digest
that pull got, and records that digest in `cluster.txt`. The pod is privileged, because the judge's sandbox takes
the network from the submission with `unshare -n`; the cluster is deleted when the job ends.

## What is the same in every domain

- **The terms are fixed before the work.** Each example's `terms.json` holds the hash of its suite (`accept`). Change a
  threshold, a gold label or a seed and the hash changes, so the suite funded is the suite that judges.
- **The run is the judge's.** The suite runs outside the submission's tree and reaches it only through `$KNOS_RUN`,
  in the sandbox: a file is read out, a script is run, a SQL file is executed, and only the output is compared. The
  suite's own data (gold labels, the reference, the trial's rows) are taken out of the tree first.
- **The count is the meter's.** An evaluation is identified by four fields whatever was delivered, and is billed once:

      id = sha256(order || artifact digest || policy version || milestone)

  Each example's `evaluations.jsonl` holds two lines in the ledger format of [METER.md](METER.md), one for the honest
  submission (accepted) and one for the cheating one (rejected). They share the order, the policy (the hash of the
  terms) and the milestone, and differ in the artifact, so they are two evaluations. Judging the same artifact again
  under the same policy is the same evaluation and is not counted twice.

## What is different, and stays the buyer's work

The thresholds, the gold set, the invariants, the perturbation: these are the acceptance model, and they are the part
with judgment in it. Knos does not know that 0.90 is the right accuracy for a labelling job or that a shifted treatment
arm is the right test of a computed effect. `knos.judge.black_box` checks only that a bundle is built so that the
submission cannot reach the verdict except through its output. A suite can be black-box and still be a poor model of
"done"; the fourth column of the table is each example's own list of that.

One limit of the count is the program's and is not changed here: the meter's artifact field holds 40 characters, the
size of a commit id. A deliverable that is a file is judged in a commit, and the commit is the artifact. The examples
are folders, not commits, so their ledger lines carry the first 40 hex characters of a hash of the submission's files.

## Support-ticket resolution: not built

Vendors of support agents bill per resolution, and each counts its own. A neutral count would be worth having. A
"resolved" webhook is not an acceptance model, for three reasons.

**Who says it is resolved.** The webhook is sent by the system that is being paid, or by a help desk configured by
one of the two parties. Knos would authenticate the run that received the event and nothing about the event itself:
[ADAPTERS.md](ADAPTERS.md) draws that line for every external source. A count of unauthenticated events is the
vendor's count with a signature on the envelope.

**Resolved is a state, not a fact.** Tickets reopen. A customer who got a wrong answer and gave up looks the same in
the event stream as one who was helped. One vendor's published definition counts a resolution when the customer
confirms, or when the customer "exits the conversation without requesting further assistance", and takes the
resolution back if the customer later returns to the same conversation
([Intercom, "Fin resolutions"](https://www.intercom.com/help/en/articles/8205718-fin-resolutions), read 5 October
2026). So the number that is billed is settled only after a window, and a reopen rate is part of the outcome.

**The customer's confirmation is the evidence, and it is not in the webhook.** The person who can say the problem is
solved is a third party to the order. Their confirmation, or their silence over a stated period, has to be read from
where it is recorded, not from a message that says it happened.

What a real model would need:

1. **The system of record's own word.** A pinned workflow that reads the ticket from the help desk's API with the
   buyer's credential: its state, its history of reopens, who closed it, whether the customer answered. Or an event
   signed by the help desk itself (not by the agent vendor) with a public key the buyer pins. The trackers that
   [ADAPTERS.md](ADAPTERS.md) covers sign their webhooks with a shared secret, which a program on a public chain
   cannot check, so today only the first route is open: re-read the API, believe nothing that was sent.
2. **A stated definition in the terms.** Which states count, who may set them, and whether a confirmation from the
   customer is required or silence is enough. That is a field of the terms, hashed like a suite.
3. **A reopen window as a warranty.** The evaluation is made when the window closes, or an accepted outcome is
   reversed by a later evaluation of the same deliverable if the ticket reopens inside it. The meter today has no
   reversal: an accepted evaluation stays accepted. So the first form (judge after the window) is the one that fits
   without a program change.
4. **A sample a person reads.** Whether an answer was right is not in any ticket state. A buyer who pays per
   resolution audits a sample, and the terms should say how large and what follows from a failed one.

None of this is built. There is no help-desk adapter, no signed-event verifier for one, no reopen window, and no
example under `examples/outcomes/` for it, because an example driven by a made-up webhook would show the thing this
section says not to trust.
