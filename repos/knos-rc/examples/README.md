# Examples

Each line is one example: what it shows, and who it is for. Everything here runs on Solana devnet with test USDC,
which has no monetary value. Folders named `cheats/` and `near_misses/` are not examples: they are wrong submissions
that the tests run, to show that the checks refuse them ([docs/reference/TAMPER.md](../docs/reference/TAMPER.md)).

## Workflow files to copy into a repository

| example | what it shows | for |
|---|---|---|
| [knos-install.yml](knos-install.yml) | The whole payment flow in 21 lines: a comment funds an issue, the merged pull request is paid. | a maintainer who wants to fund issues |
| [knos-workflow.yml](knos-workflow.yml) | The same file, with every line explained. | a maintainer who wants to read before installing |
| [knos-check.yml](knos-check.yml) | The free Knos check on every pull request; reads only, needs no secret. | any repository |
| [knos-claim.yml](knos-claim.yml) | Names the Solana address Knos pays your GitHub account at. | a person who gets paid |
| [knos-claim-org.yml](knos-claim-org.yml) | The same, for an organisation's account. | an organisation that gets paid |
| [knos-attest.yml](knos-attest.yml) | Asks GitHub to sign that an order's terms were met, so you can ask for your payment yourself. | a seller, or someone hosting a judge |
| [knos-attestor.yml](knos-attestor.yml) | Knos for an organisation's private repositories, from one attestor repository. | an organisation with private code |
| [knos-meter-batch.yml](knos-meter-batch.yml) | Has GitHub sign one batch of a meter ledger, so the meter program counts it. | a buyer or seller using the meter |
| [knos-supplier.yml](knos-supplier.yml) | The supplier's kit in one line: the free check, its result and its receipt. | a supplier |
| [knos-reproduce.yml](knos-reproduce.yml) | Re-runs what Knos says it does, in your own repository, with GitHub signing the result. | anyone who wants to check Knos |
| [knos-canary.yml](knos-canary.yml) | Measures how long Knos takes to pay, every 30 minutes; the published merge-to-paid times come from it. | anyone who wants to check the speed figure |
| [adapters/](adapters) | Accept a pull request on another signal (a Jira, Linear or Notion item, a deployment, a release, an attestation, a workflow run), or count it at the meter. | a team whose "done" lives outside GitHub |
| [gitlab/](gitlab) | Fund and pay a work order from a gitlab.com project. | a GitLab user |
| [private/](private) | Run the agreed acceptance inside the customer's own network. | a buyer whose code must stay private |

## Paying for work that passes a check

| example | what it shows | for |
|---|---|---|
| [acceptance/](acceptance) | Three tasks (classify, clean-csv, summarise), each with the buyer's repository, a black-box check and an honest solution. | a buyer writing a task an agent can be paid for |
| [acceptance/hermetic/](acceptance/hermetic) | What to add so the check runs in a container pinned by digest, and can be run again with the same verdict. | a buyer who wants a repeatable judge |
| [outcomes/](outcomes) | Orders whose deliverable is not merged code: data labelling, a data transformation, a reproducible result, support tickets. | a buyer paying for outcomes |
| [terms/](terms) | Ready terms for common orders: a bug fix, a feature with a black-box check, a milestone, a standing rate. | a buyer writing terms |
| [host_a_judge/](host_a_judge) | Run an order's checks again in your own repository and have GitHub sign the result. | someone who wants to be an independent judge |
| [witnessed/](witnessed) | One whole transaction, from funding to payment, run and recorded by you. | anyone who wants to see it work end to end |

## Agents paying agents

| example | what it shows | for |
|---|---|---|
| [agent_pays_agent/](agent_pays_agent) | One agent pays another from escrow, only when the work is accepted. | an agent builder |
| [x402_attested/](x402_attested) | `knos-order`, Knos's proposed scheme for x402 (paying over HTTP with status 402), runnable. | an agent or API builder |
| [record_api/](record_api) | A server that sells a supplier's record as a paid lookup. | someone selling data to agents |

## Reading the record without Knos

| example | what it shows | for |
|---|---|---|
| [consumer/](consumer) | A separate Node program decides from the chain alone whether an order was paid. | an integrator who trusts nothing of Knos's |
| [receipt_consumer/](receipt_consumer) | Draws the "Knos-verified" badge from a receipt, offline. | a platform that shows badges |
| [shadow/](shadow) | What Knos would have paid on an invoice or a sample of pull requests, with no money moved. | a buyer trying Knos on past work |
| [meter/](meter) | A buyer's and a seller's ledger of evaluations for one month, to verify and reconcile. | a buyer or seller using the meter |
| [advance/](advance) | A financier pays the seller now and collects from the order later. | a financier |

## Solana programs built on Knos

| example | what it shows | for |
|---|---|---|
| [reader_template/](reader_template) | A complete program to copy: it acts only when your CI workflow asked for it. | a Solana developer, start here |
| [oidc_gate/](oidc_gate) | The shortest form of the same check, as a template to paste. | a Solana developer |
| [issuers/](issuers) | The same verifier for eleven sources of identity (GitHub, GitLab, Google, AWS and more). | a developer whose CI is not GitHub |
| [workflow_vault/](workflow_vault) | A token vault with no private key: it pays only on one workflow's signed request. | a team managing a CI budget |
| [cpi_fund/](cpi_fund) | A treasury no key controls funds a work order, and gets its money back if the work is not delivered. | a DAO or grants program |
| [upgrade_gate/](upgrade_gate) | An on-chain record of which commit a program's bytes were built from. | a multisig deciding on an upgrade |
