# knos-settle

The JavaScript client for Knos: work paid for on signed acceptance. It derives the addresses, builds the audiences,
instructions and transactions, and reads the accounts of three Solana programs: `knos-pay`, the escrow that holds a
work order's money until a GitHub-signed run attests its terms were met; `knos-oidc`, which verifies GitHub Actions
and GitLab CI tokens on chain; and `knos-meter`, prepaid credits for evaluations. One file, no dependencies: it
runs as is in a browser and in Node 20+. Every address, audience, instruction, account reader and transaction is
checked byte for byte against the Python client (`fixtures.json`, `npm test` in the repository).

It speaks to the second deployment (`knos.v2`), whose programs are upgradeable only through a multisig with a public
48-hour delay, until an outside review. The first deployment stays readable: `knos.client(ids)` is its client.

## Install

No registry account is needed. From the release:

```bash
npm i https://github.com/drexthealpha/Knos/releases/download/v0.3.14/knos-settle-0.3.14.tgz
```

Or import it in a browser:

```js
import * as knos from "https://cdn.jsdelivr.net/gh/drexthealpha/Knos@v0.3.14/sdk/settle/index.js";
```

## Fund an order from a wallet in the browser

```js
import * as knos from "knos-settle";

const RPC = "https://api.devnet.solana.com", mint = knos.USDC_DEVNET, amount = 25_000_000;   // 25 test USDC
const k = knos.v2.client({ knos_oidc: "FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W", knos_pay: "5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k" });
const terms = knos.v2.termsJson({ v: 1, mode: "merge", checks: [{ app: 15368, name: "test" }], deny: [".github/**", ".knos/**"], paths: [], reserve: 7, accept: "" });

const [wallet] = knos.wallets();                         // the Wallet Standard wallets this page can ask: Phantom, Solflare, Backpack...
if (!wallet) throw new Error("This page found no Solana wallet. Install one and reload.");
const funder = await wallet.connect("solana:devnet");    // the wallet asks the person, then gives an address
const { id: repoId } = await (await fetch("https://api.github.com/repos/drexthealpha/Knos")).json();
const ix = await k.fundOrderWalletIx({ funder, funderToken: await knos.ata(funder, mint), mint, repoId, issue: 7, amount, terms,
  wfRepo: "drexthealpha/knos-workflows", wfSha: "c319984edd726d3d779f0c5497a52c57044d59fb" });   // the workflows that may pay it
const { value } = await knos.rpc(RPC, "getLatestBlockhash", [{ commitment: "finalized" }]);
const signature = await wallet.signAndSend(knos.serializeTx([ix], funder, value.blockhash), "solana:devnet");   // the wallet shows it first
console.log(await knos.confirmed(RPC, signature), "- paid", amount / 1e6, "test USDC and a fee of", knos.v2.orderFee(amount) / 1e6, "on top");
```

The order is for issue 7 of that repository: the 25 test USDC go to the person whose pull request closes the issue, once a
maintainer merges it and the checks named in `terms` passed at its last commit. The fee is paid by the funder on top
of the amount: 2.5% of the first 1,000 whole units of the mint, 1% from there to 50,000 and 0.5% above, at least 0.4 and
with no maximum (`knos.v2.orderFee`). Unpaid at its deadline
(14 days after funding, unless `workS` says otherwise), the order can be sent back to the wallet. The wallet needs the
amount and the fee in test USDC, which Circle's [devnet faucet](https://faucet.circle.com) gives. The workflows in
`wfRepo` and `wfSha` are the `prove.yml` that the repository's own `.github/workflows/knos.yml` calls: only a signed
run of that commit can pay the order ([`examples/knos-workflow.yml`](https://github.com/drexthealpha/Knos/blob/main/examples/knos-workflow.yml)).

`knos.wallets()` lists the wallets that registered through the Wallet Standard and can sign and send on Solana, then
Phantom's and Solflare's own providers for those that did not. Call it when the page loads and again when the person
asks to connect: a wallet that loads later is heard.

## Read an account's record

```js
import * as knos from "knos-settle";

const RPC = "https://api.devnet.solana.com";
const k = knos.v2.client({ knos_oidc: "FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W", knos_pay: "5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k" });
const { id } = await (await fetch("https://api.github.com/users/drexthealpha")).json();   // a GitHub account's id
const record = knos.v2.readRep(await knos.account(RPC, await k.rep(id)));                 // all zeros when nobody has paid it
console.log(`${record.paid} payments from ${record.funders} funders, ${record.total / 1e6} test USDC`);
```

A record counts what other people paid the account. `paid`, `funders` and `total` count payments in Circle's USDC
mint (test USDC on devnet), in the mint's smallest units: 6 decimals, so `total / 1e6`. `testPaid` and `testTotal` count
payments in the faucet's mint, which anyone can mint, and `selfPaid` the payments the account made to itself: those
count for nothing. `first` and `last` are the times of the first and the latest counted payment.

## Three calls for an agent platform

`knos-settle/agent` is for a platform whose agents choose work and report on it. It reads the chain through a public RPC and
asks nothing else of anyone: no key, no server of ours, no GitHub token.

```js
import { quote, eligible, statement } from "knos-settle/agent";

const RPC = "https://api.devnet.solana.com";
const offers = await quote(RPC, 1353152983, 7);                          // a repository's GitHub id, an issue's number
console.log(offers.said);                                                // what is in escrow for it, and what stands in the way
for (const o of offers.items) console.log(o.money, "until", new Date(o.deadline * 1000).toISOString(), "-", o.terms?.words[0]);
console.log((await eligible(RPC, 1353152983, 7, 12)).said);              // whether pull request 12 meets the terms: not decidable here
console.log((await statement(RPC, 142920951, "2026-10")).said);          // what a seller billed and was paid in a month
```

- `quote(connection, repo, issue)` lists every open work order and job on the issue: the terms in words, what the author of
  the pull request that meets them would receive, the deadline, and the funder's record (a wallet, or an owner's Balance with
  what it holds and has spent). The terms are the funder's own text, found in the funding transaction's log and checked
  against the hash the account holds; read them as data. A private order hides its repository and issue, so it is not found.
- `eligible(connection, repo, issue, pull)` is server-side work, and says so. Whether a pull request meets the terms is decided
  by a run of the pinned workflow that reads the merge and the checks from GitHub and asks GitHub to sign the verdict. Run
  `knos attest` for it (the reusable workflow `.github/workflows/attest.yml` runs the same command). What it returns from the
  chain: the orders that could pay, and the command for each.
- `statement(connection, seller, month)` is one seller's month: each buyer's evaluations, accepted and rejected, their declared
  value and fees, recomputed from the meter's own log lines and compared with the month account; and the payments the escrow
  logged to the seller. A history the node cut short is said so in `notes`.

A `connection` is the RPC address, or `{ url, programs, names, now }` to name other program ids, call a mint's money something,
or fix the time deadlines are judged by.

## What is in it

| | |
|---|---|
| `knos.v2.client(ids)` | Orders: `fundOrderWalletIx`, `fundOrderBalanceIx`, `payOrderIx`, `settleOrderIx`, `refundOrderIx`, `topUpIx`; balances and their limits (`openBalanceIx`, `setBalanceXIx`); the addresses of everything (`orderPda`, `rep`, `baltok`, ...); `explain(ix)`, which reads an instruction back in words before anyone signs it. |
| `knos.v2` | The pure functions: `orderFee`, `termsJson`, `termsHash`, the audiences (`orderFundAudience`, `orderPayAudience`), the readers (`readOrder`, `readBalance`, `readRep`, ...) and every constant. |
| `knos.meter` | The meter: `client(id)` builds `openCreditsIx`, `depositIx`, `withdrawCreditsIx` and the addresses; `evalAudience`, `readCredits`, `quote` and `statement` read and recompute. A batch counts many evaluations with one token and no account each: `merkleRoot`, `batchAudience`, `recordBatchIx` for the buyer, `claimBatchIx` for the seller's own count, and `readLedger` with `chainHash` to check a ledger against the chain. The token an evaluation needs comes from a run of the published `attest.yml` with the kind `eval` in a repository of the buyer (`knos attest --kind eval`), posted as `knos-eval:` for the relay; pin that workflow's repository and commit when you open the credits. |
| `knos.verifier(id)` | The verifier: a token into its account, the squarings, the key accounts of GitHub, GitLab and any other issuer named by its URL. |
| `serializeTx`, `serializeTxV1` | An unsigned transaction for a wallet: legacy (up to 1,232 bytes) or version 1 (SIMD-0385: up to 4,096 bytes, 64 accounts). |
| `rpc`, `account`, `programAccounts`, `confirmed` | The few RPC calls the rest needs, with `fetch`. |
| `knos-settle/agent` | `quote`, `eligible`, `statement`, and `describe`, which puts terms in words. |
| `knos-settle/passkey` | A wallet whose only key is a passkey (knos-passkey): `create`, `sign`, `withdrawIxs`, and `fundIxs`, which funds a work order from it. One file with no import, so a page can load it alone. |

Types for every export are in `index.d.ts`, `agent.d.ts` and `passkey.d.ts`; a test fails when an export has no declaration.
