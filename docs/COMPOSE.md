# Building on Knos

Knos is three things other software can use without asking anyone: a program that verifies an OIDC token on Solana
(`knos-oidc`), an escrow that pays on such a token (`knos_pay`), and the public record both leave. Nothing below
needs a key of Knos's, an account with Knos, or a change to the programs. Everything runs on devnet with test USDC;
the programs are upgradeable only through a multisig with a public 48-hour delay, until an outside review. Work orders,
the meter and the passkey wallet are new in 0.3.13: [SECURITY.md](SECURITY.md), section 8, says what is live when,
and [ASSURANCE.md](ASSURANCE.md) which test holds which rule.

| you want to | use | a whole example, with its test |
|---|---|---|
| require a GitHub-signed fact in your own program (which repository, commit, workflow, audience) | [`crates/knos-oidc-interface`](../crates/knos-oidc-interface): no dependency, reads a verified token account; no CPI | [`examples/oidc_gate`](../examples/oidc_gate) (`tests/test_oidc_gate.py`): a release gate |
| hold tokens that only a workflow can spend, with no private key | the same crate, with the key account so a revoked key stops at once | [`examples/workflow_vault`](../examples/workflow_vault) (`tests/test_workflow_vault.py`): a vault that pays on `vault:<vault>:<to>:<amount>:<nonce>` from one workflow file at one commit |
| state on chain that GitHub's runner built an executable from a commit, and gate upgrades on it | the same crate | [`examples/upgrade_gate`](../examples/upgrade_gate) (`tests/test_upgrade_gate.py`); `scripts/governance.mjs upgrade propose` refuses a buffer without a record unless `--ungated` |
| fund a work order from your own program (a DAO treasury, a grants program) | [`crates/knos-pay-interface`](../crates/knos-pay-interface): `solana-program` only; ids, addresses, FundOrderWallet, TopUp, RefundOrder, the Order reader | [`examples/cpi_fund`](../examples/cpi_fund) (`tests/test_cpi_fund.py`): a treasury PDA funds, tops up, and is refunded |
| fund a work order from a multisig | [`scripts/squads_fund.mjs`](../scripts/squads_fund.mjs): a Squads v4 vault transaction; its dry run prints the instruction | `tests/test_squads_fund.py` |
| sell work over HTTP and be paid on acceptance, not before delivery | [X402.md](X402.md): "attested", a proposed x402 scheme (not part of x402) | [`examples/x402_attested`](../examples/x402_attested) (`node --test examples/x402_attested/test.mjs`) |
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

To rebuild the example programs and re-pin their test binaries: `bash scripts/build_programs_v2.sh examples`.
