# The meter: what is counted, and who can check it

`knos_meter` counts **evaluations**. An evaluation is one judgment of one piece of work: a work order, an artifact
(a commit), the policy it was judged under and a milestone, with a verdict (accepted or rejected) and the rate the
seller bills when it is accepted. The buyer's pinned workflow asks GitHub to sign that judgment; the program checks
the signature on chain and counts it. Those four fields give the evaluation its id,

    id = sha256(work order, 32 bytes || artifact, its 40 characters || policy, 32 bytes || milestone, u32 little-endian)

(`EvalAud::key` in [`programs-v2/knos_meter/src/gh.rs`](../programs-v2/knos_meter/src/gh.rs)), and an id is billed
once. The count is of evaluations, accepted and rejected alike. The value is the sum of the accepted ones' rates,
in whatever the two parties settle in; the meter adds it up and moves none of it.

Everything here is on Solana devnet with test USDC. `knos_meter` 1.1 with the batch mode is in this release's source;
it is upgradeable only through a multisig with a public 48-hour delay, until an outside review. The whole path below
(ledger file, the workflow's command, the signed audience, the relay, the two accounts, `verify` and `reconcile`
reading them back) runs in `tests/test_meter_e2e.py` against the program in LiteSVM. It has run on devnet once, on
the release's staging deployment of knos_meter 1.1, with tokens GitHub signed for a staging copy of the workflows:
5,000 evaluations in two batches, the seller's claim of 5,003, and a reconcile that named the 3 the buyer left out
([CAPABILITIES.md](CAPABILITIES.md), "The 0.3.14 rehearsal on devnet"). The pinned knos_meter runs 1.0 until its upgrade
executes.

## Two modes

**Individual.** One token per evaluation (`Record`). The program writes a marker account of 88 bytes for the id, so
a second token for the same evaluation changes nothing. Every evaluation is on chain by itself; nothing else is
needed to check the count. The marker's rent is locked until two hours into the next month and is more than the
price of the evaluation (the arithmetic is [below](#what-an-evaluation-costs-in-each-mode)).

**Batched.** One token per batch (`RecordBatch`). The token carries the buyer, the seller, the month, a sequence
number, the count, how many were accepted, their value and a 32-byte Merkle root. The program writes no account per
evaluation. It adds the numbers to one Ledger account for (buyer, seller, month) and folds the root into a running
hash:

    chain = sha256(chain || root || seq || count || accepted || value)        numbers as u64 little-endian; chain starts as 32 zero bytes

A token is taken once because its `seq` must be the account's next one (error 125 otherwise; `seq` starts at 0).
Which evaluations stand behind the numbers is in a **ledger file**, off chain. The seller anchors its own count the
same way (`ClaimBatch`, no fee) into a second account, from a repository the seller owns.

The token's audience is the batch, ten parts, numbers in decimal with no leading zero, the root as 64 lowercase hex
characters:

    knosm:batch:<buyer>:<seller>:<yyyymm>:<seq>:<count>:<accepted>:<value>:<root>      the buyer's count (RecordBatch)
    knosm:claim:<buyer>:<seller>:<yyyymm>:<seq>:<count>:<accepted>:<value>:<root>      the seller's own (ClaimBatch)

A batch holds 1 to 100,000 evaluations, no more accepted than counted, for the chain's month or the one before it
(error 126 otherwise).

**The Ledger account** is 96 bytes: the month, the buyer, the seller, `next_seq`, the evaluations, how many were
accepted, their value, the fees the batches cost, and the running hash. There is one per buyer, seller and month for
the buyer's count (seeds `"l"`, buyer, seller, month) and one for the seller's claim (`"lc"`, the same). The relayer
of the first batch pays its rent, once; the program has no instruction that closes it, so the account stays and the
rent is not returned. It is the record: the totals and the running hash of a month stay readable.

The tree is RFC 6962's: leaf = sha256(0x00 || id), node = sha256(0x01 || left || right), over the batch's ids sorted
ascending, each once.

## The ledger file

JSON Lines. A batch is a header line and then one canonical line per evaluation (keys sorted, no spaces, integers
and lowercase hex only), so two parties who hold the same facts hold the same bytes:

    {"batch":{"accepted":3,"buyer":424242,"count":4,"month":202610,"root":"<64 hex>","seller":555000,"seq":0,"value":6000000}}
    {"accepted":1,"artifact":"<40 hex>","buyer":424242,"id":"<64 hex>","milestone":0,"order":"<64 hex>","policy":"<64 hex>","rate":2000000,"seller":555000}

Code: [`src/knos/ledger.py`](../src/knos/ledger.py), standard library only. Tests: `tests/test_ledger.py`.

| command | what it does |
|---|---|
| `knos meter batch <events> --ledger <file> --month YYYY-MM` | adds a batch (the next `seq`) from evaluation lines or `knosm:eval:...` audiences, and prints the root, the totals and the audience the token must be signed for; `--claim` for the seller's own count |
| `knos meter verify <ledger> [--rpc <url>] [--claim]` | recomputes every root, every total and the running hash; with `--rpc` it reads the Ledger account of every month in the file from that node and holds the file to it (the buyer's account, or with `--claim` the seller's), and prints the two on-chain counts side by side; exit 1 if anything differs. `--onchain totals.json` takes the account's five values from a file instead |
| `knos meter prove <ledger> <id>` | the inclusion proof of one evaluation, as JSON; `knos meter prove --check <proof>` checks one without the ledger |
| `knos meter reconcile <buyer ledger> <seller ledger> [--rpc <url>]` | what only one side has, what they judged differently, what was entered twice, and the statement; with `--rpc`, each month's two on-chain counts side by side and how far apart they are |
| `knos meter export <ledger>` | one CSV row per evaluation |

The file commands need only the standard library. `--rpc` uses Knos's Solana client
([`src/knos/settle/v2/meter.py`](../src/knos/settle/v2/meter.py): the addresses, the account reader and the
`RecordBatch` and `ClaimBatch` instructions). The audience and the Merkle tree are written once, in `ledger.py`, and
the client uses those.

## From the file to the chain

1. **The file is in a repository of its owner.** The buyer keeps its ledger in a repository of the buyer, the seller
   in one of the seller's. `knos meter batch` adds a batch on your own machine; commit the file.
2. **A run signs one batch.** [`examples/knos-meter-batch.yml`](../examples/knos-meter-batch.yml), installed as
   `.github/workflows/knos-meter-batch.yml`, runs once a day and by hand. It calls Knos's published `attest.yml` at a
   pinned commit with the kind `batch` (a buyer) or `claim` (a seller; set the repository variable
   `KNOS_METER_KIND` to `claim`). That job runs `knos attest --kind batch --repository <this one> --order <path>`:
   it reads the file through GitHub's API (no checkout), recomputes every root and total, refuses a file that does
   not hold or whose buyer (seller, for a claim) is not the owner of the repository the run is in, and asks GitHub to
   sign the audience of the first batch the chain has not taken (or the one named: `<path>:<yyyymm>.<seq>`). One
   batch a run. A run that finds nothing new signs nothing and succeeds.
3. **The token is posted** as a `knos-eval:` comment on the repository's "knos tokens" issue. It is no secret.
4. **A relayer carries it** (`knos relay`, or Knos's public relay): two transactions verify GitHub's signature, one
   sends `RecordBatch` or `ClaimBatch`. The relay reads the audience, refuses before sending what the program would
   refuse (a wrong seq, a re-run, another owner's repository, credits that cannot pay), and reports the fee and the
   running hash.
5. **Anyone checks**: `knos meter verify <file> --rpc https://api.devnet.solana.com`.

What the program asks of each token. `RecordBatch`: GitHub's signature, a GitHub-hosted runner, the run's first
attempt, the workflow file `attest.yml` or `prove.yml` of the repository and at the commit the buyer's Credits pin,
in a repository whose owner is the audience's buyer. The same rule as `Record`. `ClaimBatch`: GitHub's signature, a
GitHub-hosted runner, a repository whose owner is the audience's seller. No workflow pin.

Not done: reading the ledger from a workflow artifact (the command reads a file in the repository); a batch larger
than GitHub's API serves as one file (100 MB, about 300,000 evaluations; a batch token carries at most 100,000).

**Where the file is kept.** In the customer's own storage: the buyer keeps the buyer's, the seller keeps the
seller's. Knos needs no copy and keeps none; the commands above run on a laptop with no network. The cost of that is
plain: the chain holds totals and roots, not evaluations, so a party that loses its file can still show how many it
anchored and can no longer show which. Because each side keeps its own, one lost file leaves the other.

## What each party can check alone

| who | with what | can check |
|---|---|---|
| the buyer | its ledger and the chain | that the Ledger account's count, accepted, value and running hash are exactly its batches (`verify`); that the fee taken matches the count |
| the seller | its ledger and the chain | the same for its own claim; and, **without seeing the buyer's file**, whether the buyer's count for the month differs from its own, because both totals are public |
| either | one proof and one anchored root | that a named evaluation is in a batch (`prove --check`): at most 13 hashes for a batch of 5,000 |
| an auditor | one ledger and the chain | everything that side can |
| anyone | both ledgers | which evaluations differ, and the statement (`reconcile`) |

Nobody can say *which* evaluations differ from the chain alone. That takes both files.

## A buyer who leaves events out

[`examples/meter/`](../examples/meter) holds a buyer's ledger and a seller's for October 2026. The seller judged
seven evaluations. The buyer anchored six, and recorded one of those as rejected. Each file holds on its own:

    $ knos meter verify examples/meter/buyer.jsonl
    202610: 2 batch(es), 6 evaluation(s), 4 accepted, value 8000000, running hash edb2b3579305b5f2121fb4b539f991603f802c1040b56b482384f70d82ddce0c
    $ knos meter verify examples/meter/seller.jsonl
    202610: 2 batch(es), 7 evaluation(s), 6 accepted, value 12000000, running hash 1fa7e587e37168574bd1bded132314f0cd6a73dafd5067ba82f5a7893af496db

Once both are anchored, the chain shows two counts for the same month, 6 and 7, and two values, 8 and 12. That is
all the chain shows, and it is enough for the seller to know there is something to settle before it has seen the
buyer's file. The files say what:

    $ knos meter reconcile examples/meter/buyer.jsonl examples/meter/seller.jsonl
    202610 a84efce01a23db3635166e574a8bb99b1ffcc55491dd67d03f9322f35dbdbac4 only the seller has (missing from the buyer's count): accepted, rate 2000000
    202610 c9f06a898bc6dae84b02d8fabf6d608fa54706fbe1b356de72362c84019f3648 differs in verdict: buyer rejected at 2000000 in 202610, seller accepted at 2000000 in 202610
    buyer,424242
    seller,555000
    rate,50000
    free,10000
    month,count,accepted,value,fee,buyer_only,seller_only,disputed
    202610,5,4,8000000,0,0,1,1
    sha256,9e2185fec401d8bf8cfdb7b12c31fa7d320313077867a875b58a73b265a4538e
    The two ledgers differ. The statement counts only what both have and describe alike; settle the lines above between you.

The statement counts what both sides have and describe alike, and beside it how many each side has alone and how
many they dispute. It names the two roles, never "mine" and "theirs", and sorts by id, so the buyer and the seller
get the same bytes and can compare the last line. `fee` is the price book's Meter line: the first 10,000 evaluations
of a month are free, then 0.05 USD each (`--rate 20000` for a committed-volume plan), in millionths of a USD. The
free allowance is the buyer's for the month across all its sellers; a buyer with several passes what is left with
`--free`.

A seller whose event is missing has three things to show: its own line for the evaluation, the proof that the line
is in a batch it anchored (`knos meter prove`), and the GitHub-signed run that produced the verdict. What happens
next (the buyer adds the event in a later batch, or disputes it) is between the two; the path is agreed in the
contract before the work, not decided by the program.

## What the chain does not prove

The program authenticates **which workflow spoke**: a token GitHub signed, for a workflow file at a pinned commit, in
a repository owned by the buyer (for `RecordBatch`) or by the seller (for `ClaimBatch`), taken once. It does not
prove that what the workflow said is true.

- It does not check that a root is the root of real evaluations, or of any. A workflow can anchor a count of 5,000
  over a root of nothing; only a party holding the lines can tell.
- It does not check that a batch's count, accepted and value are those of the lines under its root. `verify` does.
- In batch mode it cannot see an evaluation entered in two batches, because it keeps no account per evaluation.
  `verify` refuses a ledger with one; `reconcile` lists them.
- It cannot see an evaluation recorded both singly (`Record`) and in a batch: the marker of the single mode and the
  root of the batch do not know of each other, so it is counted and billed in both. Only the ledger file shows it.
  A buyer and a seller use one mode for one work order.
- It does not say the verdict was right. That is the judge's and the policy's, named in each line.
- It does not keep the data. If both files are lost, the totals remain and the evaluations behind them do not.
- A buyer's count and a seller's claim are two statements by two parties. The chain records both and takes neither
  side.

An order that needs each evaluation to stand on chain by itself uses the individual mode.

## Design choices

**The free allowance is counted in the month of the chain's clock.** A batch may be for this month or the last one
(a batch for September can arrive on 2 October). The 10,000 free evaluations and the plan's count are the buyer's
for the month in which the batch is *recorded*, as `Record` counts a single evaluation. So a September batch
recorded in October uses October's allowance, and the Ledger account it is added to is September's. The fee of a
batch is `count` past what is left of the allowance, times the rate, taken from the buyer's credits; a batch the
credits cannot pay is refused whole and the same token can be sent again while it is good.

**`ClaimBatch` needs no workflow pin.** A claim is the seller's statement about its own work. It costs nothing,
moves nothing and is written to an account of its own, so there is nothing a pinned workflow would protect: the
program asks only that GitHub signed it for a run in a repository the seller owns. The example workflow still calls
the published `attest.yml`, because that command checks the file before it signs; a seller may use any workflow.
What follows: a claim is exactly as good as the seller's care for its own repository.

**An evaluation recorded both singly and in a batch is visible only in the ledger.** See above. The program keeps no
per-evaluation account in batch mode, which is the point of the mode.

**One batch, one token, in order.** `seq` must be the account's `next_seq`, so batches are recorded in the file's
order and a token cannot be replayed. A batch skipped on chain blocks the ones after it until it is sent.

## What an evaluation costs in each mode

Inputs. A transaction costs 5,000 lamports per signature ([Solana docs](https://solana.com/docs/core/fees)). Rent
is (128 + bytes) × 5,080 lamports on the clusters today: `getMinimumBalanceForRentExemption(88)` returned 1,097,280
lamports and `getMinimumBalanceForRentExemption(96)` 1,137,920 from `api.devnet.solana.com`, and 1,137,920 for 96
bytes from `api.mainnet-beta.solana.com`, on 4 Oct 2026. (The older rule, (128 + bytes) × 6,960, gives 1,503,360 and
1,559,040; it is what LiteSVM charges in the tests and not what either cluster charges today.) SOL is taken at
121.50 USD: [CoinGecko](https://www.coingecko.com/en/coins/solana) quoted 121.49 and
[Coinbase](https://www.coinbase.com/price/solana) 121.46 on 4 Oct 2026. One lamport is a billionth of a SOL.
Carrying one GitHub-signed token is three transactions of one signature each: two to verify a token signed with an
RSA-2048 key ([BENCH.md](BENCH.md), "The verifier on chain") and one for the instruction.

Compute units of the instruction itself, measured in LiteSVM (`tests/test_meter_batch.py` prints the first pair):
`RecordBatch` 77,035 for the first batch of a ledger (it creates the account) and 70,692 for a later one, each
with a fee transfer; `ClaimBatch` 57,412 and 50,946. The relay asks for 110,000 and 60,000. All are under the 200,000 a transaction gets by default.

| | individual (`Record`) | batched (`RecordBatch`), 5,000 in a batch |
|---|---|---|
| transactions per token | 3 | 3 |
| fees spent per evaluation | 3 × 5,000 = 15,000 lamports = 0.0018 USD | 15,000 ÷ 5,000 = 3 lamports = 0.00000036 USD |
| rent per evaluation | (128 + 88) × 5,080 = 1,097,280 lamports = 0.1333 USD, locked, returned to the relayer from two hours into the next month | none |
| rent per buyer, seller and month | none beyond the above (the month's count account, 64 bytes, is not in this table) | (128 + 96) × 5,080 = 1,137,920 lamports = 0.138 USD, once, not returned |
| Knos's fee per evaluation past the free 10,000 | 0.05 USD (0.02 on a plan) | the same |
| against the 0.05 USD price | the locked rent is 2.7 times the price | fee and rent together are about a hundred-thousandth of the price at 1,000,000 a month |

The share of the instruction's own signature is 5,000 ÷ 5,000 = 1 lamport per evaluation; the other two lamports are
the verification. 5,000 is an example size: a batch may hold up to 100,000, which divides the same 15,000 lamports
further. The seller's `ClaimBatch` costs its relayer the same three transactions per batch, the rent of the claim
account once a month (1,137,920 lamports), and no Knos fee.

## Working capital at 1,000,000 evaluations a month

One buyer, one seller, 1,000,000 evaluations in the month, SOL at 121.50 USD.

| | individual | batched, 200 batches of 5,000 |
|---|---|---|
| SOL locked in rent at month end | 1,000,000 × 1,097,280 lamports = 1,097.28 SOL = 133,320 USD, put up by the relayer, returned from two hours into the next month | none |
| SOL spent on rent | none (the markers' rent comes back) | 1,137,920 lamports = 0.00114 SOL = 0.14 USD for the buyer's Ledger account; the same again for the seller's claim |
| SOL spent on transaction fees | 1,000,000 × 15,000 lamports = 15 SOL = 1,822.50 USD | 200 × 15,000 lamports = 0.003 SOL = 0.36 USD |
| Knos's fee for the month | 990,000 × 0.05 = 49,500 USD (19,800 at 0.02) | the same |
| credits that must be prepaid at one time | 0.05 USD: each evaluation is paid as it is recorded | 250 USD: a batch of 5,000 past the allowance is paid whole (100 USD at 0.02) |

So the individual mode ties up about 133,000 USD of somebody's SOL for a month to count 49,500 USD of fees, and the
batch mode ties up nothing per evaluation. What the batch mode gives up is in "What the chain does not prove".

Not in the tables, and not measured: the rent held against a verified token's account while it exists (it is closed
after the instruction); priority fees; and any of this on devnet with tokens GitHub signed.
