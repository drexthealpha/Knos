# Building on Knos

Knos is three things other software can use without asking anyone: a program that verifies an OIDC token on Solana
(`knos-oidc`), an escrow that pays on such a token (`knos_pay`), and the public record both leave. Nothing below
needs a key of Knos's, an account with Knos, or a change to the programs. Everything runs on devnet with test USDC;
the programs are upgradeable only through a multisig with a public 48-hour delay, until an outside review. Work orders,
the meter and the passkey wallet are new in 0.3.13: [SECURITY.md](SECURITY.md), section 8, says what is live when,
and [ASSURANCE.md](ASSURANCE.md) which test holds which rule.

**Start with [VERIFIER.md](VERIFIER.md)**: one page on the verifier as a primitive of its own. It verifies any RS256
workload identity (GitHub Actions, GitLab CI, Google Cloud, Microsoft Entra ID, Buildkite, CircleCI, Okta, Auth0, and
AWS and Kubernetes in part), and the page has the three calls, the issuer table and what a verified token does and
does not prove. [`examples/issuers`](../examples/issuers) has one example per issuer.

| you want to | use | a whole example, with its test |
|---|---|---|
| require a fact an issuer signed in your own program (which repository, branch and workflow; which cloud service account) | [`crates/knos-oidc-interface`](../crates/knos-oidc-interface): no dependency, reads a verified token account; no CPI | [`examples/oidc_gate`](../examples/oidc_gate) (`tests/test_oidc_gate.py`): a release gate, and the template to copy; [`examples/issuers`](../examples/issuers) (`tests/test_issuers.py`): ten issuers |
| start a program of your own that reads the verifier | the same crate, by tag, from outside this repository | [`examples/reader_template`](../examples/reader_template) (`tests/test_reader_template.py`): a whole program in a workspace of its own. Copy the folder, change two constants, build, deploy with your own key. Its README lists the five mistakes a reader can make and the line that prevents each |
| decide something in an application from a Knos receipt, with no program | `knos.badge.verified(receipt)` in Python; `renderVerified` of [`web/badge.js`](../web/badge.js) | [`examples/receipt_consumer/show_badge.py`](../examples/receipt_consumer/show_badge.py) (`tests/test_badge.py`): 55 lines that show the "Knos-verified" badge only when the receipt checks and its verdict is accepted. The badge cannot be bought |
| decide in another language, with no Knos package and no Knos site, whether an order is paid, by which transaction, under which terms hash | the receipt's JSON Schema ([`docs/receipt/`](receipt)), the IDL ([`idl/knos_pay_v2.json`](../idl/knos_pay_v2.json)) and any Solana RPC endpoint | [`examples/consumer`](../examples/consumer) (`node --test examples/consumer/test.mjs`, `tests/test_consumer.py`): Node with no package; a receipt or a statement's status file in, a decision and what it trusts out |
| hold tokens that only a workflow can spend, with no private key | the same crate, with the key account so a revoked key stops at once | [`examples/workflow_vault`](../examples/workflow_vault) (`tests/test_workflow_vault.py`): a vault that pays on `vault:<vault>:<to>:<amount>:<nonce>` from one workflow file at one commit |
| state on chain that GitHub's runner built an executable from a commit, and gate upgrades on it | the same crate | [`examples/upgrade_gate`](../examples/upgrade_gate) (`tests/test_upgrade_gate.py`); `scripts/governance.mjs upgrade propose` refuses a buffer without a record unless `--ungated` |
| fund a work order from your own program (a DAO treasury, a grants program) | [`crates/knos-pay-interface`](../crates/knos-pay-interface): `solana-program` only; ids, addresses, FundOrderWallet, TopUp, RefundOrder, the Order reader | [`examples/cpi_fund`](../examples/cpi_fund) (`tests/test_cpi_fund.py`): a treasury PDA funds, tops up, and is refunded |
| fund a work order from a multisig | [`scripts/squads_fund.mjs`](../scripts/squads_fund.mjs): a Squads v4 vault transaction; its dry run prints the instruction | `tests/test_squads_fund.py` |
| sell work over HTTP and be paid on acceptance, not before delivery | [X402.md](X402.md): "knos-order", a proposed x402 scheme (not part of x402); `live.mjs --rpc <url>` runs it against any cluster | [`examples/x402_attested`](../examples/x402_attested) (`node --test examples/x402_attested/test.mjs`, `tests/test_x402_attested.py`) |
| let one agent pay another only when a third party accepted the work | the same scheme, two scripts with keys of their own and an evaluator; nothing is released on wrong work and the buyer is refunded at expiry | [`examples/agent_pays_agent`](../examples/agent_pays_agent) (`tests/test_agent_pays_agent.py`): both endings on the simulator; the devnet run has not been made |
| file, show or attest a settlement | [RECEIPT.md](RECEIPT.md): the acceptance receipt, its JSON Schema and vectors; [`scripts/sas_receipt.mjs`](../scripts/sas_receipt.mjs) writes one as a Solana Attestation Service attestation | `tests/test_receipt.py` |
| build a client in JavaScript or Python | [`sdk/settle`](../sdk/settle) (one file, no dependency) and `knos.settle.v2`; the instructions and layouts are in [`idl/`](../idl) | `sdk/settle/test.mjs`, `tests/test_idl.py` |
| count accepted outcomes without escrow | `knos_meter` ([`programs-v2/knos_meter`](../programs-v2/knos_meter)) reads tokens through the same interface crate | `tests/test_meter_chain.py` |
| pay a person who has no wallet app | `knos_passkey` ([`programs-v2/knos_passkey`](../programs-v2/knos_passkey)): a wallet at an address a WebAuthn passkey derives; [`sdk/settle/passkey.js`](../sdk/settle/passkey.js) and `knos.settle.v2.passkey` | `tests/test_passkey_chain.py`, `sdk/settle/passkey.test.mjs` |
| list funded work, or show an account's or a repository's record | the static files the site publishes, written by [`scripts/pages_data.py`](../scripts/pages_data.py): `bounties.json`, `u/<login>.json`, `r/<owner>/<repo>.json`, `badge/...`, `rank/...` | `tests/test_pages_data.py` |
| let a coding agent find, take, fund and settle work | `knos mcp`: ten tools; the ones that act return the comment or transaction to send ([INSTALL.md](INSTALL.md)) | `tests/test_mcp.py` |

Three rules hold for every consumer of the verifier, and the examples show each: give your program its own audience
prefix, so a token minted for another program is useless to yours; bind the token to one action and record that the
action was done, because a verified token can be read by anyone until an hour after it expires; and take the key
account when a revoked key must stop at once. [OIDC.md](OIDC.md) has the reader's API and
[SECURITY.md](SECURITY.md) what the verifier does and does not promise.

## Use it from your program in ten minutes

The verifier on devnet is `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` (`knos-oidc`, second deployment;
`programs-v2/program_ids.json`). Nothing has to be deployed, registered or asked for on Knos's side.

1. **Two minutes: the dependency.** `knos-oidc-interface = { git = "https://github.com/drexthealpha/Knos", tag =
   "v0.3.14" }`. It depends on nothing and does not allocate, so it sits beside any version of `solana-program`,
   `pinocchio` or `anchor`.
2. **Five minutes: the check.** Copy [`examples/oidc_gate/template.rs`](../examples/oidc_gate/template.rs) and
   change the three marked lines: your audience prefix, the repository's numeric id, the workflow file (or name a
   Google Cloud service account: for another issuer, the lines are in [`examples/issuers`](../examples/issuers)). Your
   instruction takes two more read-only accounts, the token account and its key account;
   [`examples/oidc_gate/README.md`](../examples/oidc_gate/README.md) has the lines and what each check refuses.
3. **Three minutes: the token.** In the workflow that may act, give the job `id-token: write` and ask GitHub for a
   token with your audience ([OIDC.md](OIDC.md), "Put a token on chain"). The sender writes it to `knos-oidc` and
   verifies it (`Write`, then two `Step` for GitHub's RSA-2048 key), then sends your instruction with the token
   account and `readToken(data).key`. In JavaScript that is `verifier(program)` of [`sdk/settle`](../sdk/settle); in
   Python, `knos.settle.v2.oidc`.

What you then hold in your program is GitHub's signature over which repository, which commit, which workflow file at
which commit and which audience, checked by a program on chain. It is the issuer's word that these claims were
signed, not proof of what the workflow read or decided ([VERIFIER.md](VERIFIER.md)).

## Use the record without Knos

A receipt and a statement's status file can be checked by an application that has neither Knos's Python package nor
its site. [`examples/consumer`](../examples/consumer) is one, in Node with no package:

```bash
node examples/consumer/consumer.mjs receipt RECEIPT.json --rpc https://api.devnet.solana.com
node examples/consumer/consumer.mjs status STATUS.json --rpc https://api.devnet.solana.com
```

**What it verifies.** The receipt fits its published schema. The transaction it names is finalized, did not fail,
and holds knos_pay's PayOrder, SettleOrder or Release of that order (the IDL's tags and account places). knos_pay's
own log lines, not another program's, paid those wallets those amounts, that fee and that tip; the token balances
agree when the answer has them. The order's funding fixed the terms hash the receipt states: the sha256 of the terms
the funding logged, or a private order's hash from its funding instruction. The deliverable and settlement ids are
the ones the order and the transaction give. For a status file, each payment on chain is checked the same way and
tied to its line's deliverable and settlement ids.

**One deliverable, two ids.** A deliverable id is made from a scope and a milestone ([CONFORMANCE.md](CONFORMANCE.md)).
Two published forms give the same milestone different scopes. A receipt and a meter ledger use the order's address,
as 64 hex characters. An audit export (`knos audit export`) uses the line's billing key: the order and the transaction
that funded it. A witnessed statement takes its lines from that export. So one paid milestone can carry two
deliverable ids. Changing either form would change ids already written in receipts and statements, so this release
changes neither. The consumer accepts both, and says which form named the line. The milestone is 0, or a standing
order's pull request, which the payment logs.

**What it trusts.** The cluster's answers (ask a second endpoint to remove that); that the program at the IDL's
address is knos_pay as published, whose upgrades pass a multisig with a public delay; and the acceptance itself, which
the forge signed and knos_oidc checked on chain before knos_pay paid, and which this program does not re-read.

## Who reads the verifier

**Programs outside this repository that read `knos-oidc`: 0.** Applications outside it that consume a receipt: 0.
x402 facilitators other than Knos's own example that implement `knos-order`: 0 ([X402.md](X402.md)). Every example
here is Knos's own; no program outside it is known to read a token yet. The numbers change when a row below
exists, and not before.

| program id | cluster | what it gates | a transaction in which it read a verified token | source |
|---|---|---|---|---|
| none yet | | | | |

To be listed, open a pull request that adds one row: your program's address, the cluster, one line on what it gates,
the signature of one transaction in which your program read a token `knos-oidc` verified, and a link to your source
if it is public. The row is merged when the transaction is on the cluster, your program is in it, and a token
account owned by `knos-oidc` is among its accounts. Nothing else is asked: no fee, no agreement, no contact first.
The fastest way to a first row is [`examples/reader_template`](../examples/reader_template): its test shows the
whole path in a simulator, and its README the four commands to devnet.

## Who uses the upgrade gate

**Programs outside this repository behind the upgrade gate: 0.** Knos's own four programs are behind it.
[GATE.md](GATE.md) is the page: three commands put a program of yours behind a public delay and a record of which
commit GitHub's runner built its bytes from.

| program id | cluster | its gate | a gated upgrade (the transaction that executed it) | source |
|---|---|---|---|---|
| none yet | | | | |

To be listed, open a pull request that adds one row: your program's address, the cluster, your gate's address, and
the signature of one transaction in which your multisig executed an upgrade of that program whose bytes your gate had
recorded. The row is merged when the transaction is on the cluster, the program's upgrade authority is a Squads vault
whose multisig has a time lock above zero, and the record `["build", program, hash]` exists under your gate for the
bytes that upgrade deployed. No fee, no agreement, no contact first.

## Install from a registry

Both interface crates are on crates.io at 0.3.14 ([knos-oidc-interface](https://crates.io/crates/knos-oidc-interface),
[knos-pay-interface](https://crates.io/crates/knos-pay-interface)), and the JavaScript client is on npm at 0.3.20
([knos-settle](https://www.npmjs.com/package/knos-settle)). The git and tarball lines above still work.

```toml
knos-oidc-interface = "0.3.14"
knos-pay-interface = "0.3.14"
```

```bash
npm install knos-settle@0.3.21
```

`python scripts/release.py registry-plan` prints what would be published where and checks, with no network, that
each package packs and that its README has no link that works only inside the repository. It publishes nothing.
The release run adds `--online` (is each name free, or which versions does the registry hold), then
`cargo owner --list <crate>` and `npm owner ls knos-settle`. The interface crates stay at 0.3.14
while the programs that link them do; the JavaScript client moves with each release.

To rebuild the example programs and re-pin their test binaries: `bash scripts/build_programs_v2.sh examples`.
