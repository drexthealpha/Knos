# Outcomes other than a merged pull request

Each domain needs its own acceptance model; Knos supplies the fixed terms, the signed run and the count, not the model.

An order pays, or the meter counts, when a pinned suite passes on an artifact. Nothing in that sentence says "pull
request". What the artifact is, and what a suite must do to deserve the word "accepted", differs for every kind of
work, and somebody who knows the work has to write it. This page shows four such models that run in this repository:
three whose deliverable is a file a suite judges, and [support resolutions](#support-resolutions), judged from a
ticket's own record on made-up tickets. One of the first three is also signed by an issuer that is not a forge:
[a Kubernetes cluster](#a-kubernetes-cluster-signs-an-outcome).

## Five kinds of work, and the evidence each needs

| Kind of work | An outcome | The evidence an acceptance needs | Runs today |
|---|---|---|---|
| Software delivery | a merged pull request | the forge's own record: the merge, the head commit, the named checks' results; for tests mode, a black-box suite run by the judge | Yes, on devnet at the public program ids: [CAPABILITIES.md](CAPABILITIES.md) |
| Customer operations | a support ticket resolved | the help desk's own record of the ticket: who solved it, whether a person took over, whether the customer came back inside a stated window | In part: the rule, the count, the signed run and the statement run on made-up tickets ([below](#support-resolutions)). No help desk is read |
| Data operations | a labelled dataset; a transformation | held-out gold items; seeded inputs with invariants to the cent | Yes, as examples in the simulator: [data-labelling](../examples/outcomes/data-labelling/), [data-transformation](../examples/outcomes/data-transformation/). Never on devnet |
| Back-office processing | an invoice matched, a claim adjudicated, a record reconciled | the system of record's entry before and after, a control total that must tie, and a sample a person reads | No. Nothing is built |
| Agent services | a task one agent bought from another | whatever the task's kind above needs; the order names the suite or the record before the work | In part: an order bought over HTTP and paid on a merge ([`examples/x402_attested`](../examples/x402_attested), [`examples/agent_pays_agent`](../examples/agent_pays_agent)). No other kind of task |

Every row needs the same three things from Knos (terms fixed before the work, a run somebody else signed, a count
made once) and one thing Knos does not supply: a record of the outcome that the party being paid cannot write.

## The models that run here

| Outcome | Artifact | What the suite checks | What it cannot check | Status |
|---|---|---|---|---|
| [Data labelling](../examples/outcomes/data-labelling/) | `labels.csv`: a label for each of 400 items | Schema; accuracy at least 0.90 on 120 gold items never shown; recall at least 0.80 for each class; the 40 visible examples no more than 0.10 above the gold ones (copied answers) | The 280 items outside both samples, except by inference; whether the gold labels are right; secrecy of the gold file from a labeller who can read the repository | Example runs here; never used by a customer |
| [Data transformation](../examples/outcomes/data-transformation/) | `transform.sql` | On 40 input tables made from fixed seeds: schema, one row per key, every input customer and charge counted once, totals equal to the input's to the cent, each row equal to a reference | Inputs shaped unlike the generator's; speed at production volume; other database engines | Example runs here; never used by a customer |
| [Reproducible research](../examples/outcomes/reproducible-research/) | `analysis.py` and `RESULT.json`, the number it is said to give | Run again in the sandbox with the order's seed: the number matches within 0.000001; a second run agrees; when the input is moved by a known amount the number moves by it (a pasted number does not) | Whether the method answers the question; whether the data are real; whether the seed or the method was chosen after looking | Example runs here; never used by a customer |
| [Support resolutions](../examples/outcomes/support-resolution/) | a ticket's record, as the help desk exported it | Solved by the agent; no escalation and no human reply; no reopening and no customer message inside 72 hours; the window has closed | Whether the export is the help desk's true record; whether the answer was right | Runs here on made-up tickets; no help desk read; never used by a customer |

`tests/test_outcomes.py` puts every submission of the first three examples through `knos proof judge`. Each example holds
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

## Support resolutions

Vendors of support agents bill per resolution, and each counts its own. This is a neutral count of the same thing:
the definition is in terms both sides hold, the count is the meter's, and the run that made it is signed by
somebody else. It runs here on made-up tickets ([`examples/outcomes/support-resolution`](../examples/outcomes/support-resolution/)).

**The definition, and where it comes from.** Two vendors publish how they count. Intercom counts a resolution when
the customer confirms the answer helped, or "exits the conversation without requesting further assistance"; does not
count one when the customer asks for a person; takes it back when the customer returns to the conversation; and bills
a conversation at most once ([Intercom, "Fin AI Agent resolutions"](https://www.intercom.com/help/en/articles/8205718-fin-ai-agent-resolutions)).
Zendesk counts an automated resolution "when a customer's issue is successfully resolved without live-agent
intervention", evaluates only conversations that were not escalated, waits for a period of inactivity (72 hours for
email and web forms) and counts per conversation
([Zendesk, "About the automated resolutions platform"](https://support.zendesk.com/hc/en-us/articles/5352026794010)).
Both read 7 October 2026. The example's terms mirror them:

| The terms say | In the example | Mirrors |
|---|---|---|
| the agent marked the ticket solved | required | both |
| nobody took it over: no escalation, no human reply | required | Zendesk "without live-agent intervention"; Intercom's request for a person |
| the customer did not come back inside the window | no reopening, no customer message for 72 hours after `solved` | Intercom's deduction when the customer returns; Zendesk's 72 hours |
| the customer's confirmation | `or_silence`: a confirmation, or leaving without asking for more | Intercom's confirmed and assumed resolutions |
| one ticket, one resolution | a ticket is one deliverable, billed once | both |
| a reopening after the window | takes nothing back; a new deliverable only if the terms say so | none: the vendors do not say |

One thing is stricter than either vendor. A ticket has no verdict until its window has closed, so it is not in the
count and nothing is billed on it. A resolution that can still be undone is never billed and then taken back.

**Run it.**

    python scripts/outcome_support.py evaluate      # a verdict and a reason for every ticket
    python scripts/outcome_support.py batch         # the meter's batch, and the audience a workflow has GitHub sign
    python scripts/outcome_support.py statement --out out    # the supplier's invoice set against the count

The example holds ten made-up tickets, one of them exported twice, terms at 0.99 a resolution (one vendor's published
price, used as a sample), and a supplier's invoice of eight lines. What the commands print: 4 accepted, 5 rejected,
1 not judged yet; a batch of 9 evaluations worth 3.96; and a statement in which 4 lines are agreed (3.96 of 7.92
billed), 2 are disputed (a reopened ticket, an escalated one), 1 is a duplicate and 1 has insufficient evidence
(its window is open). `tests/test_outcome_support.py` holds each of those numbers and each rule.

**The signed run.** [`outcome-support.yml`](../.github/workflows/outcome-support.yml) has three jobs. `count` judges
the tickets and prints the batch's audience, `knosm:claim:<buyer>:<seller>:<yyyymm>:<seq>:<count>:<accepted>:<value>:<root>`,
with the repository's owner as the seller. `sign` asks GitHub to sign that audience and runs nothing from the
repository. `receipt` makes the count again, holds the token to it with the on-chain verifier's rule, and writes the
receipt and the statement. That audience is the one `knos_meter`'s ClaimBatch reads for a seller's own count.
**The workflow has not run, and the token has not been carried to Solana**: the test signs a GitHub-shaped token with
a test key.

**What this does not show**, and what a real count needs:

1. **The system of record's own word.** The script reads a file. A real count re-reads each ticket from the help
   desk's API with the buyer's credential, in the pinned run: its state, its reopens, who closed it. No help-desk
   adapter is built, and no verifier for an event a help desk signs. GitHub signs which workflow ran at which commit
   and the count it asked for; it does not sign that a ticket file is true. A count of events the paid party sent
   is that party's count with a signature on the envelope ([ADAPTERS.md](ADAPTERS.md) draws the line).
2. **Whether the answer was right.** No ticket state says so. A customer who got a wrong answer and gave up looks
   like one who was helped. A buyer who pays per resolution reads a sample; the terms here do not say how large.
3. **Reversal after the fact.** Judging after the window needs none. A correction of an accepted evaluation exists
   in the ledger ([METER.md](METER.md)) and is not used here.
4. **A customer.** The buyer, the seller and every ticket are sample values. Nobody bought this.
