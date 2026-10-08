# Changelog

## 0.3.21 (October 2026)

**What exists made true, enforceable and usable by strangers: a checker that catches the contradictions it missed,
every rate with its denominator, a spending boundary a program enforces for an organisation's money, a reserve by
comment, a way out before every upgrade, a judge that holds a fork bomb, and a relay that counts a run alive only by
its heartbeat.**

The sentence is unchanged: the neutral meter for AI agent work, where neither side keeps the count. Everything is on
Solana devnet, which is test mode: the money is test USDC. Everything this release adds is "tested locally" in
[`docs/CAPABILITIES.md`](docs/CAPABILITIES.md): none of it has run at the public program ids or been used by a person
outside this repository, and each line below says its own limit. **No program changes in this release:** nothing
under `programs-v2/knos_*`, `programs/`, `idl/` or `tests/fixtures/*.so` moved by a byte. The interface crates are on
crates.io (knos-oidc-interface 0.3.14, knos-pay-interface 0.3.14) and the JavaScript client on npm
(`npm install knos-settle`, 0.3.20).

### True

- **The checker catches more.** `scripts/truth_check.py` now fails on a page that names an older release as the
  current one, states a fee, a quorum rule or a devnet result that disagrees with the capability list, the source or
  the price book, or says the crates or the npm client are not published. The README's "today" table is generated
  from `docs/capabilities.json`, so it cannot drift from it. The pages it found are fixed.
- **Every rate with its denominator.** `scripts/rate_claims.py` fails on a latency or throughput figure printed
  without its sample size, its program ids (public or staging) and its date. Of 53 pay attempts on devnet the
  failures and the attempts that never completed are printed beside the waits, with p50, p95, p99 and the worst
  apart; the 200-order load run says it used staging ids ([`docs/LOAD.md`](docs/LOAD.md),
  [`docs/BENCH.md`](docs/BENCH.md)).
- **End-to-end PayOrder capacity has a command and no number.** `python scripts/load.py measure --pay` pays orders
  with N relays, each with its own fee payer; on the simulator it proves the path and gives no rate. It has not
  been measured on devnet.

### Enforced

- **An organisation's money in a Squads v4 vault.** `knos boundary plan` turns an approval policy into the vault's
  members, threshold, time lock and a separate config authority; an approval binds one commitment (terms hash,
  policy version, amount, payee, expiry), and the funding workflow refuses it for another order, after its expiry,
  under a changed policy or for another payee; a budget is reserved atomically before work starts. Squads v4 is
  Squads Labs' deployed program, not Knos's; no buyer has set up such a vault ([`docs/BOUNDARY.md`](docs/BOUNDARY.md),
  [`docs/ENFORCEMENT.md`](docs/ENFORCEMENT.md)).
- **The five parts everywhere a receipt leaves Knos.** Every export carries a parts file beside it, the paid record
  answer and every statement line carry identity, execution, acceptance, consequence and assurance, and Knos Terms 3
  can require a minimum assurance level for payment (`checks.min_assurance`). A month closes only with both parties'
  signed acknowledgements, or one and the silence the terms allow (`window.period_close`)
  ([`docs/RECEIPT.md`](docs/RECEIPT.md), [`docs/EVENTS.md`](docs/EVENTS.md), [`docs/TERMS.md`](docs/TERMS.md)).
- **The judge holds a fork bomb.** On Linux the host sandbox now caps processes, CPU time, memory and file size,
  keeps everything outside the work folder read-only and kills the whole tree at the time limit. The hermetic
  container is the default judge where the runner has one; the host sandbox is the fallback and the verdict says so
  ([`docs/ATTESTOR.md`](docs/ATTESTOR.md)). `docs/TAMPER.md` was measured again with this judge: the results are
  unchanged, and every cheat in it was still written by the people who wrote the judge. The `tamper` task pays 5 test
  USDC to an outsider whose cheat the judge accepts; none has.

### Usable by strangers

- **A reserve by comment.** `/knos reserve <amount> for @supplier until <date>` locks a reserve through the pinned
  funding workflow and says its id, amount, deadline and how the supplier checks it. It works once the pinned
  workflows are republished at 0.3.21 ([`docs/NETTING.md`](docs/NETTING.md)).
- **A way out before every upgrade.** `knos exit --before-upgrade` lists every order and Balance an owner holds, the
  instruction that takes the money out and whether it lands before a pending upgrade can run; the upgrade feed and
  banner say "N hours to leave". Held and warranty money cannot leave before an upgrade, and it says so.
  `python scripts/provenance.py verify-proposal N` compares a proposal's bytes with the verified build, and a drill
  rotates GitHub's signing key mid-period ([`docs/GOVERNANCE.md`](docs/GOVERNANCE.md), [`docs/DRILLS.md`](docs/DRILLS.md)).
- **The approver's question on one row.** Ordinary lines resolve in one action; approving writes an approval record
  (policy version, who, when, why, the evidence's hashes) that the page checks again later, and the buyer's memory
  answers `knos recall approval` from the store alone. A supplier's finance lead sees what is funded, the acceptance
  countdown, appeal rights and the payment date with no wallet ([`docs/CONSOLE.md`](docs/CONSOLE.md),
  [`docs/FINANCE.md`](docs/FINANCE.md)).
- **Vendors get a page.** Each agent the Agent PR Index rates has a page with its sample, a right of reply, its
  disputes and how to earn the supplier badge; supplier reuse is counted (0 today) ([`docs/VENDORS.md`](docs/VENDORS.md)).
  The upgrade gate is one pull request for a Solana program team ([`docs/GATE.md`](docs/GATE.md)).
- **Tasks a stranger can complete.** Five more kinds: `compose`, `gate`, `keyholder`, `tamper` and `witness`, the
  last an independently witnessed transaction a stranger runs end to end from a fork (`examples/witnessed`).
  Completed by an outside account: 0.

### Operations and accounting

- **The relay counts a run alive by its heartbeat.** The watchdog also runs when a worker run ends, cancels and
  replaces a run stuck in its install wait, and two watchdogs never start two chains; an event is recorded in the
  relay log by its own run before anything reads it, and workers are partitioned by order
  ([`docs/RELAY.md`](docs/RELAY.md)). Tested with fake runs; not yet observed at the public ids.
- **The relay is a package.** `knos.settle.v2.relay` is split by responsibility with no change of behaviour, and all
  of it is under mypy.
- **Pricing power, accounted honestly.** `knos bill margin --sensitivity` prints revenue and gross margin at a
  realised Acceptance rate of 30, 20, 10 and 5 basis points; a commitment is credited against usage, never counted
  twice; reserves, rent and principal are never revenue ([`docs/MARKET.md`](docs/MARKET.md),
  [`docs/UNIT_COSTS.md`](docs/UNIT_COSTS.md)). Nothing has been sold.

## 0.3.20 (October 2026)

**One enterprise transaction, followed to its end: what was authorised, what was delivered, what was accepted, what
is owed, and what happened to the money. A screen for whoever approves the invoice, a table of what enforces each
rule, a reserve behind netted work, evidence that verifies when Knos is gone, and a bank file.**

The sentence is unchanged: the neutral meter for AI agent work, where neither side keeps the count. Everything is on
Solana devnet, which is test mode: the money is test USDC. Everything this release adds is "tested locally" in
[`docs/CAPABILITIES.md`](docs/CAPABILITIES.md); apart from one throughput measurement by Knos's own wallets at the
public knos_pay, none of it has run at the public program ids, with a bank, or with a person outside this
repository, and each line below says its own limit. **No program changes in this release:**
nothing under `programs-v2/knos_*`, `programs/` or `idl/` moved by a byte.

### For whoever approves the invoice

- **A screen with no command line.** The site's Approve page shows one row per invoice line (supplier, purchase
  order, deliverable, evidence, amount, exception, payment status) and one queue of exceptions. The approver
  approves the agreed lines, or sends an exception to the supplier as a message that is already written. The time
  the page states is a script's in a headless browser; no person was timed
  ([`docs/CONSOLE.md`](docs/CONSOLE.md), "The approver's screen").
- **What enforces each rule, as a table made from the code.** `knos controls matrix` prints every route that can
  set money aside or move it against every restriction, and says of each cell whether a program enforces it, the
  pinned workflow does, it is advice, or it is outside Knos. Each enforced cell names a test that tries to get round
  it. The approval gate is now asked on every funding by comment, and the documents that said nothing called it are
  corrected ([`docs/ENFORCEMENT.md`](docs/ENFORCEMENT.md), [`docs/CONTROLS.md`](docs/CONTROLS.md)).
- **A receipt reads in five parts.** Identity, execution, acceptance, consequence, assurance, one line each
  (`knos receipt explain`). A valid signature on a weak test reads as weak. It is a reading of the receipts that
  exist and adds no version ([`docs/RECEIPT.md`](docs/RECEIPT.md)).
- **Memory of how the same exception ended before.** `knos recall exception` answers from the buyer's memory: how
  often the same exception under the same terms was seen, how each ended and how long it took. Appeals, statement
  lines that were set aside, corrections and closed months are written there when `--remember` names the buyer.
  No buyer has used it ([`docs/submission/DEPENDENCY.md`](docs/submission/DEPENDENCY.md)).
- **Pay by bank.** `knos statement pay --rail bank` writes a payment instruction file (ISO 20022 pain.001) for the
  lines that are agreed, approved and still payable, and `knos statement status` reads the bank's answer back: paid,
  or returned and payable again. The site writes the same file. Two more exports: every line with its purchase
  order and its match, and a cXML invoice. No bank has taken a file and no system has loaded an export
  ([`docs/RAILS.md`](docs/RAILS.md), [`docs/FINANCE.md`](docs/FINANCE.md)).

### For a supplier

- **Four protections, checked before the work.** `knos preflight` says whether the terms fix the criteria, set an
  acceptance deadline, give an appeal and make payment predictable, and whether a program, the workflow or advice
  stands behind each ([`docs/SUPPLIER.md`](docs/SUPPLIER.md)).
- **A reserve behind netted work.** A buyer locks a reserve for one supplier before the period; the period spends
  no more than it holds, is paid by draws on it, and what no draw took returns to the buyer after the deadline. A
  period with no reserve says it is unsecured and prints what the supplier carries. A financier can buy a closed,
  reserved period through the program's existing assignment; Knos lends nothing. Run on the simulator only
  ([`docs/NETTING.md`](docs/NETTING.md), [`docs/ADVANCE.md`](docs/ADVANCE.md)).
- **Take a funded task as an agent.** `knos task list | show | take | submit | why`, and three read-only MCP tools.
  A merged pull request that was not paid gets one sentence saying why: an order funded through a staging copy of
  the workflows never pays, and the board now funds only through the public ones. Five tasks that are not code
  (reproduce, shadow count, fund from the faucet, install, host a judge) each state the evidence that completes
  them. None has been completed by an outside account ([`tasks/README.md`](tasks/README.md)).

### Evidence and neutrality

- **An archive that verifies when Knos is gone.** `knos archive make` writes one file with the evidence and a
  verifier of one standard-library file: no Knos, no network. Two holders compare by one root; a number a sender
  gave that never arrived is named, and a month is not closed over it. One run on this repository's samples is
  recorded; they carry no signed token, and the verifier says so. One run on a real period is recorded too: the
  founder's own account on both sides, its batches anchored at the public knos_meter; its log of events starts at
  number 1, so the strict check fails on it, and both acknowledgements that close its month are signed by keys the
  founder holds. No outside party holds an archive
  ([`docs/RETENTION.md`](docs/RETENTION.md), [`docs/EVENTS.md`](docs/EVENTS.md)).
- **The paid record answer is worth more than the free file.** The server signs each answer with an expiry, adds a
  summary, and gives the history a supplier granted to one reader. Its revenue is budgeted at zero and Knos hosts
  no server ([`docs/RECORD.md`](docs/RECORD.md)).
- **Host a judge from one link; the private path as one command; a drill for a second operator.** Each is a
  command a person outside can run, and nobody outside has: outside hosts, private repositories and second
  operators are all zero ([`docs/ATTESTOR.md`](docs/ATTESTOR.md), [`docs/PRIVATE.md`](docs/PRIVATE.md),
  [`docs/OPERATOR.md`](docs/OPERATOR.md)).
- **GitLab as one command, and a support resolution as an outcome.** `python scripts/gitlab_round.py run` carries
  the whole GitLab round and needs a token and a project this tree has not had. A support ticket counts when it
  stayed resolved through the window the terms fix. Neither has run on its forge
  ([`docs/OIDC.md`](docs/OIDC.md), [`docs/OUTCOMES.md`](docs/OUTCOMES.md)).

### Underneath

- **One list, and a checker that fails on a contradiction.** Every capability is one row: source, test, deployed
  build, transaction, reproduction ([`docs/MANIFEST.md`](docs/MANIFEST.md)). `scripts/truth_check.py` reads the
  documents and the site against that list, the source and the price book. `scripts/public_face.py` holds every
  description of Knos to the one sentence; what the registries serve changes only when this release is published.
- **The decision, warm.** The rules can be loaded before the token arrives (`knos decide --stream`). Six latencies
  are reported apart, never as one number. The warm figure is measured on one machine with no network and not on
  devnet ([`docs/BENCH.md`](docs/BENCH.md), "Decision time").
- **The relay chain heals.** A failed start is asked again and a watchdog starts a chain when none is alive; the
  upgrade task starts after a missed start. Throughput has a command that measures it, and the page keeps measured
  and derived apart: measured once on devnet, on 7 October 2026, with four relays and 40 orders each way, a
  reading of that day and not a capacity ([`docs/RELAY.md`](docs/RELAY.md),
  [`docs/LOAD.md`](docs/LOAD.md)).
- **The rounds of the release run are files.** `scripts/exercise_rounds/` holds the reserve, GitLab, the private
  path and a hosted judge; each runs on the simulator, and at the public ids each ends with its own code and stops
  no other ([`docs/RELEASE.md`](docs/RELEASE.md)).
- **Unit costs said as they are.** Every margin is labelled gross; three places where the price does not cover the
  cost are printed with their numbers; the first customer is described, and who is not one
  ([`docs/UNIT_COSTS.md`](docs/UNIT_COSTS.md), [`docs/WHY.md`](docs/WHY.md)).
- **One page for a judge, and one transaction in seven beats.** [`docs/JUDGES.md`](docs/JUDGES.md); the story, the
  first screen's round and the demonstration's script tell the same seven: agree, fails, passes, statement, replay,
  pay, verify ([`docs/STORY.md`](docs/STORY.md)).
- **No program crate moved.** The four programs and the two interface crates stay at 0.3.14.

### Not true yet

- No outside funder, no buyer conversation, no letter of intent, no outside key holder, no outside reproduction,
  and no outside program that reads the verifier.
- Nothing this release adds has run at the public program ids but the throughput measurement, which funded
  Knos's own orders in a mint made for the run and left none open. The reserve, GitLab, the private path and a hosted
  judge are commands of the release run (`python scripts/exercise_public.py run --only <round>`): GitLab needs a
  token and a project, a hosted judge needs a repository of another owner, and the private path needs someone with
  a private repository.
- Whether proposals 7 and 8 have executed is what `knos status` and [`web/upgrades.json`](web/upgrades.json) say;
  until they have, the public programs charge the earlier fee, and every page shows the fee that is live.
- No bank has taken a payment file, no accounting system has loaded an export, and no approver outside this
  repository has used the screen.
- The registries and the repository's own description still serve older words until this release is published;
  `python scripts/public_face.py --remote` prints each one and the command that corrects it.
- A workflow's appeals reach memory only where its job has the memory engine installed; statements and ledgers
  reach it only with `--remember`.
- Nothing has been sold, and there is no legal entity to sell from.

## 0.3.19 (October 2026)

**What exists, made true, fast and used: a decision from the evidence in milliseconds, small tickets netted, a
faucet and a board of funded tasks for strangers, assurance on every receipt, and the fee bound proved.**

The sentence is unchanged: the neutral meter for AI agent work, where neither side keeps the count. Everything is on
Solana devnet, which is test mode: the money is test USDC. Everything this release adds is "tested locally" in
[`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) unless a line below says otherwise; nothing new was reproduced by
anyone else. **No program changes in this release:** nothing under `programs-v2/knos_*`, `programs/` or `idl/`
moved by a byte, and `scripts/deploy_v2.sh --propose` refuses in this tree.

### For a buyer and a supplier

- **Small tickets are netted.** Accepted outcomes under 20.00 accumulate per supplier and period and settle as one
  release of the net, so the fee's 0.05 floor is paid once and not once per outcome. In the simulator, 1,000
  outcomes of 0.32 (one sent twice and refused, one disputed) settle as one release of 319.68 for a fee of 0.95904
  in 24 transactions; the escrow takes no single job under 1.00 at all. The cap, the release, the root and the fee
  are enforced on chain; each line, and the buyer's credit inside the period, are not (`knos net`,
  [`docs/NETTING.md`](docs/NETTING.md)).
- **The price book says what it charges.** The 0.10% tier is withdrawn: by contract the rate is 0.20% on monthly
  value above 1,000,000 and never lower. A record lookup through the machine-priced API is 0.10 a call, paid by the
  caller; the public record page and its file stay free. The pricing page's rows are the book's own, its on-chain
  cell follows the build that is live, and `knos bill` nets small outcomes the same way
  ([`docs/MARKET.md`](docs/MARKET.md), section 3).
- **A receipt says how much was verified.** Every receipt and statement line carries an assurance level computed
  from its evidence, never typed: `reported`, `rerun`, `agreed` or `attested`, each with who a reader still
  trusts. `attested` is defined and no receipt reaches it. Terms may declare accounts that are one party
  (`evaluators.related`, optional: terms without it keep their hash), and two evaluators declared related never
  count as two. A receipt is written as version 5 wherever one is made; versions 1 to 4 still verify
  ([`docs/RECEIPT.md`](docs/RECEIPT.md)).
- **A goods-received note for a statement line.** `knos statement grn` puts the order, the acceptance and the
  invoice line side by side and says whether the three match, with the line's assurance level. No buyer's
  accounts-payable system has taken one ([`docs/FINANCE.md`](docs/FINANCE.md)).
- **A supplier completes while the buyer does nothing.** The path that exists is written down and walked in the
  simulator: the buyer funds and goes quiet, the supplier's own wallet sends the forge's signed proof and is paid,
  and with no accepted work by the deadline the money goes back to its funder
  ([`docs/FINANCE.md`](docs/FINANCE.md), "When the buyer goes quiet").
- **Test USDC for a first task of your own.** `/knos faucet <address>` on the playground's faucet issue gives 20
  test USDC, once per account and per address in 7 days, 200 a day for everyone together, to an account at least 30
  days old. A grant is journaled before anything is signed, so a retry never sends twice, and of two runs that
  overlap one sends. Test USDC has no monetary value ([`docs/FAUCET.md`](docs/FAUCET.md)).
- **A board of funded tasks anyone may take.** 24 small tasks, 5 test USDC each, every one with a reference answer
  the judge accepts and wrong answers it refuses; a script keeps a set number open in the playground inside a daily
  budget and approves nothing. A claim of payment that no order stands behind now links the funded tasks
  ([`tasks/README.md`](tasks/README.md)).
- **An advance by a third party, never by Knos.** An advancer pays a supplier now, less its discount, and takes
  the supplier's place as payee of the funded order in one transaction that does both or neither; a rejection or
  an expiry is the advancer's loss. Knos lends nothing and charges nothing for it, and no advancer exists
  (`knos advance`, [`docs/ADVANCE.md`](docs/ADVANCE.md)).
- **The record, sold per lookup by whoever runs the server.** `knos record serve` answers a lookup without payment
  with a 402 that names the order to fund, serves fifty lookups for one order of 5.00, and refuses a replay. Knos
  hosts no such server ([`docs/RECORD.md`](docs/RECORD.md), [`docs/X402.md`](docs/X402.md)).
- **The first screen says the customer's outcome,** "Buyers and suppliers close invoices on evidence both can
  verify.", inside the same 40 words, and the README opens with the same lines. The demonstration leads with a
  refusal: a submission that claims success fails the condition and is not paid
  ([`docs/STORY.md`](docs/STORY.md)).

### Underneath

- **A decision in two halves.** `knos decide` first decides from the signed evidence with no network (the issuer's
  signature against key lists kept on the machine, the claims, the terms), then makes one chain request with a
  timeout and writes a second provisional receipt that names the first. On one machine with the chain simulated in
  the same process, 40 samples each: the offline half 0.6 ms at the median and 0.9 ms at p95, the chain check 0.7
  ms and 0.9 ms. The whole offline command in a new process: 177 ms at the median, and it no longer loads the
  command-line library. The workflow's status comment carries the offline line and then the chain check's where
  key lists are kept on the runner, and the relay's whole precheck where none is
  ([`docs/BENCH.md`](docs/BENCH.md), "Decision time"; [`docs/RELAY.md`](docs/RELAY.md)).
- **The fee bound is proved.** The record of the fee function's proofs now reads "verified" for every amount to
  100,000.00 and every rate from 10 to 30 basis points; the exact 0.30% at the rate 30 is proved by cvc5 with
  bit-vectors solved as integers, and that one result rests on that translation too
  ([`docs/kani.json`](docs/kani.json)).
- **The one Kani harness over every amount is verified.**
  `an_orders_fee_is_between_its_floor_and_the_one_rate_for_every_amount`, every u64 amount and every rate from 10
  to 30 at once, timed out at 180 seconds in the earlier record. Its job of
  its own in `program.yml` (`kani-fee-bounds`) verified it in run 37575047633 (8,296 s) and again in the nightly run
  37608154723 (8,360 s), Kani 0.68.0 and CBMC 6.11.0 with Kani's default solver, on this tree's `knos_pay` source.
  It bounds the fee by the program's own `bps_of(amount, 30)`; that this is at most 0.30% of the amount is the cvc5
  result above. `scripts/kani_fee_record.py --program-ci <run>` records such a run from GitHub's log of it.
- **A first proof of what a judge executed, as an experiment.** One judge for one task runs inside a zkVM, and its
  run is proved and then verified in a separate process: 54 s to prove an honest submission as a composite
  receipt, 217 s as a succinct one, under 0.05 s to verify. It is in no package and no workflow, nothing on any chain
  verifies it, and no receipt reads it ([`experiments/judge_proof`](experiments/judge_proof),
  [`docs/ATTESTOR.md`](docs/ATTESTOR.md)).
- **The worker's jobs keep their keys apart.** The claim guard's sweep runs in a job of the always-on worker that
  holds no key, once in every run of the chain, because GitHub's own timer did not fire for 38 minutes in the last
  release run. The faucet is a job with a key of its own that holds test USDC and no SOL. The two jobs that hold
  the fee key have the permissions they had ([`docs/RELAY.md`](docs/RELAY.md)).
- **Two relay runs on two runners see each other.** A lease and an answer are each one line in the relay log, so
  an event run and the sweep carry one token once; when GitHub does not take a line the run says so and the chain
  still takes a token once ([`docs/RELAY.md`](docs/RELAY.md)).
- **After the upgrade, one command.** `python scripts/exercise_public.py status --want 2.2` says whether proposals
  7 and 8 executed, and `run --phase after` then exercises the one-rate fee, a stored fee, the quorum by owner, the
  grace, strict JSON and ES256 at the public ids; on the simulator every one of those rounds passes. A client for
  ES256 exists: a wallet registers a P-256 key and a token of up to 780 bytes is verified in one transaction
  ([`docs/RELEASE.md`](docs/RELEASE.md), [`docs/ES256.md`](docs/ES256.md)).
- **The upgrade gate for another program.** One script sets it up for a program that is not Knos's (init, expect,
  record, check), and the upgrade feed is written for any multisig's programs with `--ids` and `--gate`. The
  adopters list has zero rows. `python scripts/release.py registry-plan` prints what a release would publish to
  crates.io and npm and publishes nothing ([`docs/GATE.md`](docs/GATE.md), [`docs/COMPOSE.md`](docs/COMPOSE.md)).
- **Knos's own reproduction runs to its end.** A run of `knos reproduce` by Knos itself is verified like anyone's
  and filed under `reproductions/own/`, where it counts for nothing; the folder holds 0 files
  ([`docs/REPRODUCE.md`](docs/REPRODUCE.md)).
- **No program crate moved.** The four programs and the two interface crates stay at 0.3.14.

### Not true yet

- No outside funder, no buyer conversation, no letter of intent, no outside key holder, no outside reproduction,
  and no outside program that reads the verifier.
- Proposals 7 (`knos_oidc`: strict JSON and ES256) and 8 (`knos_pay` 2.2) are approved and have not executed.
  Until they do, the public programs charge the earlier fee (2.5% of the first 1,000, 1% to 50,000, 0.5% above, at
  least 0.40) and count the judges of a quorum by repository. Proposal 7 was proposed and approved on 2026-10-07
  08:14 UTC and proposal 8 on 2026-10-07 08:15 UTC, and the multisig's time lock lets each run 48 hours after its
  approval. Whether they have is what `knos status` and [`web/upgrades.json`](web/upgrades.json) say.
- The faucet has paid no one. Its key and its token account exist on devnet, but the account holds no test USDC:
  Circle's devnet faucet asks a person to prove they are not a bot before it gives any. The task board has funded 8
  tasks in the playground (issues #6 to #13, 5 test USDC each, from the faucet Balance). The worker's claim sweep has
  run on GitHub in the staging repository only (run 37624637427: 3 open items read, none with a claim of payment).
  Netting, an advance and a paid record lookup have run once each on devnet, between wallets of Knos's
  own release run and on tokens of its own workflows: none with an outside party.
- The proof of a judge's execution is an experiment with no on-chain verifier, and `attested` stays unreachable.
- No workflow keeps the issuers' key lists on its runner, so on GitHub the provisional line is still the relay's
  whole precheck. On devnet the split was timed once on each of 24 real tokens: a median of 356 ms offline, 854 ms
  for the chain check and 9.1 s for the whole precheck, and 23 of the 24 had been carried before they were decided
  ([`docs/BENCH.md`](docs/BENCH.md), "Decision time").
- A cold decision is not instant. The whole offline command in a new process (`python -m knos.decide`: interpreter
  start, imports, decision, receipt) took 177 ms at the median on one idle machine, and a busy machine takes
  several times that. Through the whole `knos` command line it is slower again, and that was not benchmarked
  ([`docs/BENCH.md`](docs/BENCH.md), "Decision time").
- No version 5 receipt reads `rerun`. The one of a public payment (a neutral re-run of the release run's own order)
  reads `reported`: its payee and the run's owner and starter are one GitHub account.
- The record lookup's server is one anyone can run and Knos hosts none; single sign-on, private deployment and a
  support contract do not exist, so the Control plans cannot be delivered.
- Nothing has been sold, and there is no legal entity to sell from.

## 0.3.18 (October 2026)

**Priced like a protocol: one fee on accepted value, a kit for the supplier, a commitment that binds every event,
and the two quorum findings fixed.**

The sentence is unchanged: the neutral meter for AI agent work, where neither side keeps the count. Everything is on
Solana devnet, which is test mode: the money is test USDC. Everything this release adds is "tested locally" in
[`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) unless a line below says otherwise; nothing new was reproduced by
anyone else. Two program builds change, `knos_oidc` and `knos_pay`: both are proposed through the multisig after
the release, and neither is live at its public id until its proposal executes.

### For a buyer and a supplier

- **One fee, on value released against a signed acceptance.** Price book 3 has six lines: Check (free), Meter,
  Acceptance, Record, Control and Pilot. Acceptance is 0.30% of the amount, at least 0.05, with no cap, paid by the
  funder on top; it replaces the percentage on settlement and the percentage on reconciled invoice value. Value
  released on chain pays the fee there and is never invoiced again. Lower rates above 1,000,000 and 10,000,000 a
  month are a rebate by contract, off chain. There is no fee for connecting a supplier, and the rated party never
  pays. These are proposed prices: nobody has paid one ([`docs/MARKET.md`](docs/MARKET.md), section 3).
- **What a unit costs to deliver.** Each line of the price book has a direct cost, labelled measured or budget, and
  the ceiling it may carry at a gross margin of 90% and of 95%. Three lines miss, and the page says which: a
  release at the floor, the free evaluations, and Control at the budget. `knos bill margin` prints a month's
  margin line by line ([`docs/UNIT_COSTS.md`](docs/UNIT_COSTS.md)).
- **A kit for the supplier, at no cost to the supplier.** A public record for an agent or a vendor
  (`knos record build`), a badge that always carries its sample, one `uses:` line that runs the free check on every
  pull request and none of the pull request's code, and one page to send with an invoice
  (`knos record receipt`), which restates an acceptance receipt and names the command that checks it with no
  network. Knos wrote these records and nobody outside has reviewed them ([`docs/RECORD.md`](docs/RECORD.md)).
- **Acceptance is a versioned contract.** Knos Terms 3 is one document of ten fields, cited by the sha256 of its
  canonical bytes; an order's terms hash names one version and no other, and `knos terms diff` says what changed
  between two versions by meaning. `knos terms propose <owner/repo>` drafts one from the checks that passed on a
  repository's last 10 merged pull requests, and proposes nothing for a repository that merged none in the last
  30 days. The workflow that funds an order does not read a Terms 3 file yet
  ([`docs/TERMS.md`](docs/TERMS.md)).
- **Disputes and liability, written down.** Who can do what at each state of an appeal, which clock runs and
  where the money is ([`docs/DISPUTES.md`](docs/DISPUTES.md)); and, for each way the count can be wrong, who
  notices, what evidence exists and where the loss falls today: with the parties, never with Knos, because there
  is no legal entity, no warranty and no service commitment ([`docs/LIABILITY.md`](docs/LIABILITY.md)).
- **Agent pays agent, only when the work is accepted.** Two agents with keys of their own and an evaluator that
  is neither, under the proposed x402 `knos-order` scheme: right work is paid the amount whole; wrong work is not,
  and at expiry the buyer has the amount and the fee back. Both runs are tests on the simulator with the program
  builds; the devnet run has not been made ([`examples/agent_pays_agent`](examples/agent_pays_agent),
  [`docs/X402.md`](docs/X402.md)).
- **A claim with no funded order gets one plain answer.** A pull request or an issue that carries a bounty
  platform's commands or a wallet on another chain, against an issue nobody funded, is answered once and labelled
  `no-order`; nothing is closed and no word of the claim is quoted (`.github/workflows/claims.yml`,
  `src/knos/claim_guard.py`). `scripts/tidy_issues.py` lists every open issue and pull request of Knos's own
  repositories and what to do with each, and writes nothing without `--apply`.
- **The story in six beats,** each with one file, test or transaction as its evidence
  ([`docs/STORY.md`](docs/STORY.md)), and one page for the release: the source, the build each public program id
  runs, every capability's stage and the limits still open, written by a script
  ([`docs/MANIFEST.md`](docs/MANIFEST.md)). A reproduction is two clicks and one button in a fork
  ([`docs/REPRODUCE.md`](docs/REPRODUCE.md)); nobody outside has pressed it.

### Underneath

- **A commitment that binds every event.** A format 1 batch root is a hash of evaluation ids: it binds the set of
  ids, the count, the accepted count and the value, and not which evaluation was accepted. Format 2 hashes each
  whole event in canonical bytes, so the root binds every field of every evaluation. A new batch is format 2; a
  format 1 batch stays verifiable as format 1, and `knos meter migrate` re-commits an old month without anchoring
  it twice ([`docs/METER.md`](docs/METER.md), "What a root commits to").
- **`knos_pay` 2.2: one rate, and the two quorum findings fixed.** The fee on an order is
  `max(0.05, floor(amount x 30 / 10,000))` in place of three tiers, and a Plan may lower the rate to no less than
  10 basis points. Judges of a quorum are counted by repository owner, and a neutral judge must differ from the
  order's side in owner and in the account that started the run. A judge's marker is bound to the funding of the
  order it was made under. Both findings' tests are no longer ignored and run with the others. What no program
  can enforce: that two accounts are two people ([`docs/SECURITY.md`](docs/SECURITY.md),
  [`docs/INVARIANTS.md`](docs/INVARIANTS.md)).
- **A token signed in time is not lost to a late relay.** An order can be funded with a presentation grace, the
  funder's choice, fixed at funding: a pay token issued at or before the deadline is accepted until 7,200 seconds
  after it, and the refund is refused until then. It is off unless asked for
  ([`docs/INVARIANTS.md`](docs/INVARIANTS.md)).
- **The proofs, in the record's words.** The fee function over every amount to 100,000.00 and every rate from 10
  to 30 basis points is "verified but for one bound at one rate": the exact 0.30% at the rate 30 is "not
  verified" and is tested instead. Of the five harnesses over the program's own lines, four are "verified" and
  one, the fee between its floor and the one rate for every amount, "timed out", so nothing is proved by it
  ([`docs/kani.json`](docs/kani.json)).
- **A decision before the chain settles.** `knos decide` answers accepted, rejected or insufficient evidence from
  the token in hand, by the reads a relay makes before it spends a fee, and writes a provisional receipt that
  never authorises payment; the final receipt names it and replaces it. Measured on one machine with the chain
  simulated in the same process: 40 fresh decisions, 1.1 ms at the median and 9.3 ms at p95. On devnet, four
  decisions on real fund tokens took 4.3 to 32.6 s each over the shared public RPC, a first reading and not a
  benchmark; nothing posts the provisional line yet ([`docs/RELAY.md`](docs/RELAY.md),
  [`docs/LOAD.md`](docs/LOAD.md)).
- **The relay's runs no longer cross.** An event run and the sweep each keep a journal and append notes to a file
  of their own, and a reader merges every file by key, so two runs that share a folder send a token once. In
  `worker.yml` the two are on separate runners and the guard is still the chain's: a token works once. A relay
  may pay from several fee payers; the public worker runs one ([`docs/RELAY.md`](docs/RELAY.md)).
- **Untrusted code never shares a job with the signing authority.** One test holds every published job to that.
  In `prove.yml` the job that signs no longer trusts the bare success of the job that ran the code: it reads one
  strict line of closed-shape values, holds it to its own run, and works out the rest again from GitHub's record
  before anything is signed. Two limits stay open and are listed: jobs that cannot sign install by version, not by
  hash, and the sandbox is a user boundary inside one virtual machine
  ([`docs/SECURITY.md`](docs/SECURITY.md), "Where untrusted code runs").
- **The x402 messages are the tree's.** The example, its fixture and the page's message blocks are recorded on
  this tree's `knos_pay` build: 0.06 on 20.00. The public program charges 0.50 on the same 20.00 until the upgrade
  executes, and the page says which build each figure is for ([`docs/X402.md`](docs/X402.md)).
- **No program crate moved.** The four programs and the two interface crates stay at 0.3.14, the version their
  builds were made at; `knos_meter` and `knos_passkey` stay byte for byte the builds of proposals 5 and 6.

### Not true yet

- No outside funder, no buyer conversation, no letter of intent, no outside key holder, no outside reproduction,
  and no outside program that reads the verifier.
- Both new program builds, `knos_oidc` (strict JSON and ES256) and `knos_pay` 2.2, are proposed after the release
  as one set and are live only when they execute. Until then the public programs charge the earlier fee (2.5% of
  the first 1,000, 1% to 50,000, 0.5% above, at least 0.40) and count the judges of a quorum by repository. The
  live state is in [`web/upgrades.json`](web/upgrades.json).
- Terms 3, the supplier workflow, `knos terms propose` and the claim guard ran for the first time in this release,
  in Knos's own repositories only: `knos terms propose` drafted the terms of `drexthealpha/knos-e2e` from its merged
  pull requests, the supplier workflow judged two test pull requests in a staging repository, and the claim guard
  answered a claim of payment by an outside account on a staging issue. None has run for another owner's repository.
- One format 2 batch is anchored, at the public `knos_meter`: four evaluations of Knos's own pull requests, with
  one account as buyer and seller.
- The records hold zero Knos orders for outside suppliers: what they show is public pull requests.
- The record lookup through a hosted API is not built; single sign-on, private deployment and a support contract
  do not exist, so the Control plans cannot be delivered.
- Nothing has been sold, and there is no legal entity to sell from.

## 0.3.17 (October 2026)

**Bring your own invoice: correct work is accepted, every line has one of four verdicts and four ids, and every
recording mode writes to one ledger of events.**

The sentence is unchanged: the neutral meter for AI agent work, where neither side keeps the count. Everything is on
Solana devnet, which is test mode: the money is test USDC. Everything this release adds is "tested locally" in
[`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) unless a line below says otherwise; nothing new was reproduced by
anyone else.

### For a visitor, a buyer and a supplier

- **The front door is your invoice.** Paste a supplier's invoice or type a public repository on the site's first
  screen: a neutral count and every mismatch, with no install, no wallet and no sign-up. The recorded round moved
  below it, and one page tells it in eight steps, each with one piece of evidence
  ([`docs/STORY.md`](docs/STORY.md)).
- **Correct work is accepted.** The black-box judge used to refuse a correct fix that added its own regression
  test in a protected place: 39 of 48 honest submissions passed. It now accepts 61 of 61, and still accepts 0 of 63
  cheats on the sample project, 0 of 102 on six real tasks, 0 of 25 on tasks that are not code and 0 of 14 aimed
  at what a pull request may add, all from one run of the whole benchmark with this judge. Both rates are measured on
  Knos's own tasks, by the people who wrote the judge ([`docs/TAMPER.md`](docs/TAMPER.md)).
- **Four verdicts, four ids.** A verdict is accepted, rejected, insufficient evidence or disputed. A deliverable, an
  evaluation, an invoice line and a settlement each have an id of their own, built the same way everywhere
  (`src/knos/ids.py`). A judge that did not reach an answer says insufficient evidence, never rejected.
- **A statement for accounts payable.** `knos statement` turns a checked invoice into a statement whose lines are
  agreed, disputed, duplicate or insufficient evidence, as JSON, CSV and PDF with the same content, and records who
  approved it and how it was paid. It needs no chain and no wallet
  ([`docs/FINANCE.md`](docs/FINANCE.md), section 4a).
- **It looks like procurement.** Rate cards that cite terms by hash, standing offers, budget envelopes, roles and
  approval chains are files in the buyer's own repository, read by the command line and the console with the same
  code. The program does not enforce them ([`docs/CONTROLS.md`](docs/CONTROLS.md), section 9).
- **The supplier is a user.** `knos preflight` says before a pull request is opened what the terms protect and what
  the change would be refused for. Every refusal has a code and two plain sentences. `/knos appeal <reason>` makes
  a verdict disputed and has the neutral judge run the checks again, at no cost to the supplier; the workflow does
  not act on that comment yet. `knos keep` writes the supplier's own copy of the evidence
  ([`docs/SUPPLIER.md`](docs/SUPPLIER.md)).
- **The price book has seven lines and one billing rule:** a month's invoice is the subscription, plus the greater
  of Meter charges and Verify charges, plus anything agreed separately. Meter and Verify are never added for the
  same activity, and the rated party never pays. These are proposed prices: nobody has paid one
  ([`docs/MARKET.md`](docs/MARKET.md), section 3).

### Underneath

- **One ledger of events.** Recording singly, in a batch, by settlement, in shadow mode and by import now pass
  through one function. An id that arrives twice is counted once and both arrivals stay on record; the same id with
  different content is refused. A correction names the event it changes, and the other party signs the log up to a
  head with a GitHub token, checked off chain ([`docs/EVENTS.md`](docs/EVENTS.md)).
- **Evidence that outlives devnet.** `knos vault` seals a bundle to the buyer, the supplier and an auditor, exports
  a plain archive, applies a retention policy and writes a checkpoint. A test deletes the working copy and the
  chain's record and restores from the archive alone. No customer keeps a vault
  ([`docs/VAULT.md`](docs/VAULT.md)).
- **A path for private repositories.** The acceptance runs inside the customer's network; only the verdict, hashes
  and the forge's signed token leave, and what a dispute needs is sealed to both parties. No private-repository
  customer has run it, and its record pays nothing yet ([`docs/PRIVATE.md`](docs/PRIVATE.md)).
- **A signer that is not a forge.** A Kubernetes cluster's service-account token signs one evaluation of the
  data-transformation example. The check is tested on a token of the same shape, and a kind cluster's token was
  verified offline in staging run 37483745385; nothing of it is on chain, and the meter does not count it
  ([`docs/OUTCOMES.md`](docs/OUTCOMES.md)).
- **ES256 tokens, in one transaction.** `knos_oidc` gains an instruction that checks what Solana's secp256r1
  precompile verified. A token's signing input can be 780 bytes at most. It ships in the same build as the strict
  JSON reader of 0.3.16, and that build is not deployed ([`docs/ES256.md`](docs/ES256.md)).
- **The fee's bounds, tier by tier.** A crate of model-checker harnesses over the program's own lines verifies
  every bound in every tier but one: "at most 2.5% of the amount" at the default rate in the first tier, which is
  tested at every amount instead ([`docs/INVARIANTS.md`](docs/INVARIANTS.md), [`docs/kani.json`](docs/kani.json)).
- **The relay can be woken by an event,** and carries tokens from a queue with several workers; the timer's pass
  stays as the sweep. One event run has happened, in the staging repository, and it carried no token: no token
  carried by an event has been timed ([`docs/RELAY.md`](docs/RELAY.md)).
- **The Agent PR Index has a leaderboard,** as a page, a file and a feed: a place only for an agent with at least
  30 merged pull requests, an interval beside every rate, and a link to dispute each row
  ([`docs/INDEX.md`](docs/INDEX.md)).
- **A program of your own that reads the verifier:** `examples/reader_template` is a whole program in a workspace of
  its own, built against the interface crate by tag ([`docs/COMPOSE.md`](docs/COMPOSE.md)).
- **Hold a key, run it without the founder.** One page for a first outside key holder: make a key, keep it, ask;
  adding it is then one command ([`docs/KEYHOLDER.md`](docs/KEYHOLDER.md)). And a checklist and a drill for a
  second operator ([`docs/OPERATOR.md`](docs/OPERATOR.md)). Nobody has done either.
- **Types.** mypy checks `src/knos` in full except one module named in `pyproject.toml`, `knos.settle.v2.relay`,
  which is to come out after this release.
- **No program crate moved.** The four programs and the two interface crates stay at the version their builds were
  made at, so three programs are byte for byte the builds already proposed, and no crate is published.

### Not true yet

- No outside funder, no buyer interview, no letter of intent, no outside key holder, no outside reproduction, and
  no outside program that reads the verifier.
- The upgraded builds (`knos_oidc` 2.1, `knos_pay` 2.1, `knos_meter` 1.1, `knos_passkey` 1.1) run on the public
  program ids only once the pending upgrades execute. No round of this release ran on the public program ids; they
  are exercised there only after those upgrades have executed. The live state is in [`web/upgrades.json`](web/upgrades.json).
- ES256 and strict JSON are tested, not deployed: their build will be proposed through the multisig after the
  pending upgrades execute.
- Two findings of this release's adversarial tests are open: a quorum counts repositories, not people, and a
  judge's marker outlives its order by a second. Both are fixed in the next `knos_pay` build, which is not in this
  release ([`docs/SECURITY.md`](docs/SECURITY.md)).
- Single sign-on, private deployment and a support contract do not exist, so the Control plans cannot be delivered.
- Nothing has been sold.

## 0.3.16 (October 2026)

**The neutral meter for AI agent work: neither side keeps the count.**

Everything is on Solana devnet, which is test mode: the money is test USDC. Everything this release adds is "tested
locally" in [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md); nothing new was deployed, exercised or reproduced.

### For a visitor and a buyer

- **A first screen you can drive.** The sentence, one measured figure, two buttons, and a recorded round in six
  steps you move through with the keyboard. It replays what the repository records and says so.
- **Check an invoice with no install.** Shadow mode reads an invoice that bills per merged change and says which
  billed changes had a failed check when they were merged. It only reads GitHub. It has run on recordings, never
  against live GitHub. [`docs/SHADOW.md`](docs/SHADOW.md).
- **A playground.** Anyone funds a test order with one comment, inside limits on the amount and the day. It is not
  live until its repository is published. [`docs/PLAYGROUND.md`](docs/PLAYGROUND.md).
- **A console with the four records.** Each deliverable shows its authorisation, acceptance, commercial record and
  settlement status, and exports as a bill line for accounting products. The SAP and Coupa files are best effort and
  unverified. [`docs/FINANCE.md`](docs/FINANCE.md).
- **One payment, five named states:** received, accepted, submitted, confirmed, finalized, the same in the comment,
  the relay log and the site.
- **Fewer words.** Every page leads with what you can do there, every fold says what is inside it, and the README's
  first screen is the sentence, one figure and three links.
- **The price book** has eight lines, with Verify and Supplier connection new and both unsold, and one rule: Knos
  never charges the party being rated. [`docs/MARKET.md`](docs/MARKET.md).

### The verifier

- **`knos_oidc 2.2` reads every value of a token as strict JSON.** Before it, a payload the issuer signed that is
  not JSON in a value the verifier does not read could verify. The strict reader is a file of its own that only the
  verifier's own instructions call, so it is the one program this release changes: `knos_pay`, `knos_meter` and
  `knos_passkey` are unchanged byte for byte. The recorded differential run: 8,855 cases, 0 disagreements, each of
  the 13 formerly accepted shapes refused ([`docs/fuzz.json`](docs/fuzz.json)). 2.2 is not deployed: it will be
  proposed through the multisig after the pending upgrade executes, and the live state is in
  [`web/upgrades.json`](web/upgrades.json).
- [`docs/UNWRAPS.md`](docs/UNWRAPS.md) lists every place a program could panic, each with whether it can be reached.
- **Ten issuers documented.** [`docs/VERIFIER.md`](docs/VERIFIER.md) says what the verifier takes from each, and a
  token of each one's shape verifies in the tests. Only GitHub and GitLab have signed a token Knos verified.
- **A conformance kit** with vectors, for a team that implements Knos's formats itself
  ([`docs/CONFORMANCE.md`](docs/CONFORMANCE.md)), and **terms cited by hash** from a registry whose files are never
  rewritten: `knos terms cite` writes the sentence a contract quotes and `knos terms verify` checks a hash or a
  terms file against the registry ([`docs/TERMS.md`](docs/TERMS.md)).

### Operations and assurance

- **A quorum of three readers**, the third a repository neither side owns, and **outcome orders** from a template:
  a labelled dataset is funded by one comment and only the honest file is paid.
- **Relay lines carry stage times**, and a settlement is one comment edited through the five states.
- **The audit file, version 2:** bounties, what is still owed, the buyer's own references. Version 1 still verifies.
- **Provenance.** [`docs/PROVENANCE.md`](docs/PROVENANCE.md) follows each program from source commit to build hash
  to the hash on chain to its upgrade proposal. A link the repository does not record is printed as MISSING.
- **The model checker's record, as it is.** One run is in `docs/kani.json`: four of five harnesses verified, fee
  conservation among them. The fee-bounds harness timed out and is not proved.
- **Honest work is measured too.** The black-box judge accepted 39 of 48 honest submissions. All 9 refusals are a
  correct fix that also adds a test in the protected test directory: a known false rejection, with its workaround in
  [`docs/ASSURANCE.md`](docs/ASSURANCE.md).
- **The weekly index** is a bounded sample that always publishes and resumes from its checkpoint.
- **A release publishes a crate at its own version,** and only a version the registry lacks.
- **Numbers about outside use** are one generated table, zeros included:
  [`docs/submission/NUMBERS.md`](docs/submission/NUMBERS.md).

### What is still not true

- Nobody outside Knos has funded an order with their own tokens.
- No buyer has been interviewed, and nobody has run a pilot.
- Every key of the multisig is the founder's: there is no outside signer.
- There is no legal entity to invoice from.
- The honest numbers are in [`docs/submission/NUMBERS.md`](docs/submission/NUMBERS.md).

## 0.3.15 (October 2026)

**Knos is the neutral count and settlement for software work priced per outcome: terms fixed before the work, a
signed CI run attests they were met, a Solana program counts it or pays it.**

**Close a supplier's invoice with evidence both sides can check.** This release is for the person who has to
authorise a payment and defend it afterwards, and for the supplier on the other side. It changes no program:
everything in it is clients, workflows, the site, documents and tests. Everything is on Solana devnet with test USDC.
Each line of [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) says how far a capability has got; everything this
release adds is "tested locally", and nothing new was deployed, exercised on devnet or reproduced by someone else.
What the 0.3.14 rehearsal ran on staging program ids of its own is "tested locally" too, with its transaction in the
capability's note: only a public program id counts for "deployed" or "exercised", and
`python scripts/capabilities.py check` refuses any other.

### For a buyer and a supplier

- **The console.** The site's Buy page answers on one screen what was bought, from whom and at what price; which
  evidence establishes acceptance; whether this deliverable was billed before; whether the approver had the authority;
  and who answers when the service fails (today the founder alone, and the page says so). It reads GitHub and devnet
  in the browser and sends nothing. [`docs/CONSOLE.md`](docs/CONSOLE.md). `knos budget show|who|check|set` is the same
  set of limits from a terminal; `check` names the rule that would refuse an order first.
- **Billing by deliverable.** A deliverable is an order and a milestone, and it is one accepted outcome whatever number
  of pull requests carried it. An evaluation is one run of one policy version on one artifact for one deliverable:
  sending the same evidence again is not another evaluation, an evaluation that rejects is billable, and a failure of
  Knos is not. A wrong verdict or a withdrawal is netted by a correction that names who issued it
  (`knos meter correct`). [`docs/METER.md`](docs/METER.md).
- **Closing a month.** `knos meter close` agrees a month only when both ledgers say the same after repeats and
  corrections. A disputed close names the exact lines and is never an invoice. Each side signs the close with a
  GitHub run of its own. This is off chain, and no real month has been closed or signed yet.
- **Statements and receipts that verify with devnet gone.** `knos meter export --bundle` writes one deterministic
  archive of a closed month that `knos meter verify --bundle` checks with no network. `knos bundle verify --no-chain`
  checks a payment's bundle with no cluster and says which facts the issuer's signature proves, which are archived
  copies, and which need a cluster. Devnet is reset from time to time; the signature survives that, the chain's own
  record does not. [`docs/RECEIPT.md`](docs/RECEIPT.md).
- **A receipt in five parts** (version 3; versions 1 and 2 still check): what the issuer authenticated, what the
  evaluator observed, which policy produced the verdict, who authorised the money and under which limit, and what
  remains trusted. It records whether each evaluator's run was the buyer's own, the seller's own or neither.
- **A second run of the acceptance check, in another environment.** For an order with a black-box suite, the neutral
  judge now runs the funded suite again itself, in a job that cannot sign, and signs only on its own result. A check
  in the buyer's repository that wrongly says "success" is then not repeated. For an order paid on its merge there is
  no suite to run: the neutral run still reads the checks' conclusions, and its verdict says so. The changed
  `attest.yml` is published with this release and has never run on GitHub.
  [`docs/SECURITY.md`](docs/SECURITY.md), section 20.
- **Prices, said once.** The price book is the same table in the README, on the site and in
  [`docs/MARKET.md`](docs/MARKET.md), with the effective fee by order size shown before funding (5 pays the 0.40
  minimum, which is 8%). One offer is new: the Pilot, 30 days for one buyer and its suppliers, 2,500 USD invoiced off
  chain ([`docs/PILOT.md`](docs/PILOT.md)). Nobody has bought it, nobody has been asked, and there is no legal entity
  to invoice from yet. Advance and Assurance are not offered.
- **Outcomes that are not a merged pull request.** Three worked examples (a labelled dataset, a transformation, a
  reconciliation), each with a black-box suite that refuses a cheat a naive check passes
  ([`docs/OUTCOMES.md`](docs/OUTCOMES.md)). They run locally; none was funded or paid on devnet.

### For whoever operates a relay

- **A journal and retries.** The relay writes a token to its notes before it sends it, so a relay killed at any point
  finds the token again and nobody is paid twice. A send that fails for the cluster's reasons is tried again on fixed
  times while the token is good; a refusal is final at once; when GitHub says to slow down, nothing is asked until
  the time it named and no verdict is lost. One status comment, rewritten, says what waits.
  [`docs/RELAY.md`](docs/RELAY.md).
- **Drills of each dependency's failure,** on a local validator: GitHub's API down, GitHub's key expired on chain, the
  relay killed between a send and its confirmation, an RPC endpoint that errors, missing evidence. Each row says what
  broke, what a user sees, how it recovers and how long it took ([`docs/DRILLS.md`](docs/DRILLS.md)). These are
  local drills, not outages on devnet.
- **A capacity model** that names the first limit a given number of repositories and deliverables a day would meet,
  and what lifts it ([`docs/LOAD.md`](docs/LOAD.md)). It is arithmetic on counted requests and published limits, not
  a load test at that volume.
- **Where a payment waits.** `scripts/latency_stages.py` splits each payment into its stages. The site shows the
  latest canary round stage by stage and never draws an old round as live; a tab keeps what it read and says how old
  a view is.

### For builders

- **A reproduction kit.** `knos reproduce` runs fixed checks in a repository of your own and GitHub signs the report's
  hash; a file of it in `reproductions/` is what moves a capability to "reproduced". A run in an account of Knos's own
  is refused. The folder is empty: nobody outside has sent one. [`docs/REPRODUCE.md`](docs/REPRODUCE.md).
- **The `knos-verify` action, a receipt verifier and the badge** for a bounty or work platform: one composite step
  with a read-only token; `verify(evidence, jwks)` in one Python file and one TypeScript file that answer every case
  the same. No platform uses them, and the action has never run on GitHub.
  [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md).
- **Routes for ten agent hosts.** `knos init` writes the hook each host reads, into the project only. Each route is
  tested against the event its host documents; none was run inside a real host
  ([`integrations/hosts/README.md`](integrations/hosts/README.md)).
- **Differential tests of the verifier.** The built `knos_oidc` and a reference that shares no code with it gave the
  same answer on 13,677 generated tokens, with 0 disagreements and no token accepted on an invalid signature
  ([`docs/fuzz.json`](docs/fuzz.json)). A second fuzz target asks the program's RSA arithmetic, big integers and the
  `rsa` crate the same question on every input. [`docs/ASSURANCE.md`](docs/ASSURANCE.md).
- **One check for what the documents say.** `python scripts/doc_claims.py` holds every count, stage, upgrade time and
  measured number in the documents to its one source. `knos --version` and each single command start without
  importing the other commands. The mark and the wordmark are one drawing in every copy.
- Also: `knos observe` (what anyone can read of an order on chain, and what a private order hides); a profile shown
  only for an account that opted in; a weekly scan for the Agent PR Index, which has run as a dry run only.

### What did not change

- **No program was changed.** Nothing under `programs-v2/*/src` or `programs/`, and no committed program build. No
  program was deployed, proposed or staged for this release.
- **The four builds proposed by 0.3.14 execute on their own schedule,** through the multisig and its public 48-hour
  delay: `knos_oidc 2.1`, `knos_pay 2.1`, `knos_meter 1.1`, `knos_passkey 1.1`. This file names no time for them:
  the site's [upgrade record](https://drexthealpha.github.io/Knos/upgrades.json) and `knos status` are the record of
  the live state ([`web/upgrades.json`](web/upgrades.json) is the committed copy, of the time it names). Until each
  has executed, what it adds has run on staging program ids only, in the 0.3.14 rehearsal.
- No outside security firm has examined anything. One person holds every key. Nobody outside Knos has funded an
  order with their own tokens or bought anything.

### Found and left open

- **The claim reader accepts some issuer-signed payloads that are not strict JSON.** It finds the claims it reads and
  steps over every other value by its brackets and quotes, so a payload the issuer's key really signed that a JSON
  library refuses (a literal cut short, `NaN`, a comment, a control character in a string) still verifies. The
  differential test put 13 such shapes to the program, 342 cases, and the program accepted every one. Nobody without
  the issuer's key can make such a token, so it is not a forgery; a strict reader of the same payload can fail on a
  token this verifier took. The fix is a program change, strict validation of the values the reader steps over, and
  this release changes no program. [`docs/SECURITY.md`](docs/SECURITY.md), limit 33;
  [`docs/ASSURANCE.md`](docs/ASSURANCE.md), "The verifier: left open".
- **The 95th percentile from merge to paid, 164 s, is one payment.** Of the 39 timed payments the public relay
  carried (the site's files of 5 October 2026), the 95th percentile by nearest rank is the second slowest. In the 37
  that can be split, the relay's own part, from the token's comment to the last transaction, has a median of 9 s, a
  95th percentile of 28 s and a maximum of 35 s. The long waits were before the token was posted, on GitHub's side:
  the slowest payment spent 1,208 of its 1,220 s there. The relay cannot shorten that; it measures it.
  [`docs/RELAY.md`](docs/RELAY.md), "Where a token waits".
- The first real runs are still to come: the two-job `attest.yml`, the `knos-verify` action, the reproduce workflow
  and the weekly index scan have run in tests only ([`docs/RELEASE.md`](docs/RELEASE.md), "After the tag").

## 0.3.14 (October 2026)

**Knos is the neutral count and settlement for software work priced per outcome: terms fixed before the work, a
signed CI run attests they were met, a Solana program counts it or pays it.**

**A token for `PayOrder` could pay a re-funded order twice in the 0.3.13 build.** With two fund comments on one
issue, relaying the second fund token after the first order was paid put a new order at the same address, and the
pay token that had paid the first order paid the second too. This was found during the 48-hour delay. That build was
never live on any cluster, and only test USDC was involved. **Every token is now single-use in every instruction.**

Everything is on Solana devnet with test USDC. What this release adds to the programs runs at their public addresses
only once its upgrade proposal has executed: each
line of [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) says how far it has got. The new ones are "tested locally";
"implemented" for two that no test runs here (the Kani proofs and the GitLab pipeline example); or "exercised on
devnet", each with its transaction, where the release's rehearsal ran them on a staging deployment of this build
([`docs/CAPABILITIES.md`](docs/CAPABILITIES.md), "The 0.3.14 rehearsal on devnet").
The 0.3.13 build was proposed on 2026-10-04 07:17 UTC and withdrawn before it could run. 0.3.14 proposes this build
in its place, as `knos_pay 2.1` and `knos_oidc 2.1`, with the same public 48-hour delay. This file names no time for
the new proposals: the site's [upgrade record](https://drexthealpha.github.io/Knos/upgrades.json), read from the
chain, and `knos status` are the record of the live state ([`web/upgrades.json`](web/upgrades.json) is the committed
copy, of the time it names).

### Security

- **One marker rule.** Every instruction of `knos_pay` that takes a signed token creates the account
  `["used", sha256(the token's signature)]` and refuses a token whose marker exists: `PayOrder`, `Revert`, `Reserve`
  and `Cancel` as well as `Pay` and `FundOrderBalance`. The marker records who paid its rent and the time after
  which no instruction accepts the token; `CloseMarker` returns the rent after that.
- **An order's `not_before` is the chain's time at its funding**, never a token's issue time, so an order funded
  again at an address does not inherit the tokens of the order that was there before.
- `tests/test_double_pay.py` reproduces the double payment and requires it to be refused, and sends the accepted
  token of every token-taking instruction a second time: no second use moves money.
- `overflow-checks = true` in the release profile of every program in `programs-v2/`.
- [`docs/SECURITY.md`](docs/SECURITY.md), section 15, says what holds now and what the 0.3.13 build did not hold.

### Prices

- **The fee of an order is marginal in three tiers**, paid by the funder on top: 2.5% of the first 1,000, 1% from
  1,000 to 50,000, 0.5% above; at least 0.40, no maximum. On 100 it is 2.50; on 5,000 it is 25 + 40 = 65; on 50,000
  it is 25 + 490 = 515. A Plan still lowers the first tier's rate.
- **An order holds from 5 to 100,000 test USDC** on devnet. A mainnet build sets its own cap.
- The price book has six lines (Check, Meter, Settle, Control, Advance, Assurance) and reads the same in the README,
  [`docs/MARKET.md`](docs/MARKET.md) and the site's Pricing page. Nobody has bought anything.

### The count (`knos_meter 1.1`)

- **Batches.** `RecordBatch`: one signed token counts a batch of evaluations under a Merkle root and writes no
  account per evaluation, so rent no longer exceeds the price. The single `Record` stays.
- **The seller's own count.** `ClaimBatch` writes the seller's count of the same month beside the buyer's. A buyer
  who leaves events out shows on chain as two different counts.
- **Ledger files** (`src/knos/ledger.py`, [`docs/METER.md`](docs/METER.md)): build a batch, verify a ledger against
  the chain, prove one evaluation is in it, and reconcile a buyer's ledger with a seller's.

### Funding and paying

- **A funder with only a passkey** (`knos_passkey 1.1`): `Fund` moves test USDC from the passkey wallet into an
  order, authorised by a WebAuthn assertion over the order's terms hash, the amount and an expiry. A relayer pays
  the transaction fee.
- **GitLab.** A gitlab.com project funds an order and is paid on a merge to a protected branch. Its ids are in
  ranges of their own, so a GitLab project is never a GitHub repository. Not yet: binding a wallet, reserve, cancel
  and revert, the faucet, self-managed GitLab, and any relayer, command or page ([`docs/OIDC.md`](docs/OIDC.md)).
- **Adapters** ([`docs/ADAPTERS.md`](docs/ADAPTERS.md)): workflow files that turn a signed event (a release, a
  deployment, an attestation, a tracker's webhook) into a settlement or a count.
- **x402.** The example's `knos-order` scheme funds a real order over RPC. On devnet, on the staging deployment, it
  funded an order and the seller was paid on acceptance ([`docs/X402.md`](docs/X402.md)). The interface crates and
  the npm package are ready to publish.

### Evidence

- **Receipts in four parts**, an **evidence bundle** that verifies with no network, and a **mirror** that keeps
  what the chain's history no longer serves ([`docs/RECEIPT.md`](docs/RECEIPT.md), `knos bundle`, `knos receipt`).
- **An audit export** per organisation and period: one hash-chained file that two parties can compare.
- **A hermetic judge.** In tests mode a submission runs in a container named by image digest. Its end-to-end test
  ran in a real container on GitHub's runner, in the staging repository's run 37217535106
  ([`docs/ASSURANCE.md`](docs/ASSURANCE.md)).
- **A badge** ("paid on proof") that states its scope, its money and its date, `knos record` for a payee's record,
  and each agent's rate of false claims by week in the Index.
- **Load.** 1,000 orders open at once were each paid once and none was lost, in the local simulator
  ([`docs/LOAD.md`](docs/LOAD.md)). Time for 1,000 on a cluster is derived, not measured. On devnet, 200 orders were
  verified, funded from a wallet, refunded and closed with no failure; paying is not part of that run.

### Orders that need no person, and what checks the programs

None of this runs at the public program ids until the upgrade has executed. The release's rehearsal ran auto-accept, the
challenge, the quorum, the agent's tools and the Buy page on a staging deployment of this build
([`docs/CAPABILITIES.md`](docs/CAPABILITIES.md), "The 0.3.14 rehearsal on devnet").

- **Auto-accept.** A funder can make an order paid by the black-box suite `auto` at funding: the first pull request
  the suite passes is paid, with no merge and no comment (`tests/test_order_auto.py`).
- **The challenge.** Inside the warranty of an order that allows a neutral run, anyone who runs the pinned judge
  again and finds the paid head failing returns the holdback to the funder. What was paid at acceptance stays paid.
- **A quorum of judges.** An order can require two or three distinct judges to pass the same artifact before it pays
  (`tests/test_order_quorum.py`).
- **Tools for an agent** ([`docs/AGENTS.md`](docs/AGENTS.md)): find funded work, take it, submit it after the
  order's acceptance passes locally, collect; with a key of the agent's own. The tools that post are off until the
  operator turns them on. Tested against stand-ins for GitHub and the chain; on the staging deployment an agent was
  paid for an auto order.
- **The Buy page.** A buyer picks a terms template and a passkey signs the line that funds the order; a relay
  carries that line (`/knos passkey-fund`). Tested in a headless browser and the local simulator.
- **Advance.** [`examples/advance`](examples/advance) says what `Assign` does: an assignment made before the order
  is paid sends the payment and the holdback to the financier; one made after acceptance moves nothing.
- **A state machine over the invariants** (`tests/test_invariants_machine.py`): random orders, tokens and replays.
  Run on the 0.3.13 build it finds the double payment; on this build it finds no broken invariant. Tests for the
  gaps [`docs/INVARIANTS.md`](docs/INVARIANTS.md) listed are in `tests/test_invariants_gaps.py`.
- **Handler tests in Rust** (`programs-v2/handlers`), run by the program workflow, and **Kani harnesses** for the
  fee and for conservation (`programs-v2/knos_pay/src/proofs.rs`), proved only where `cargo kani` runs.
- An example `.gitlab-ci.yml` (`examples/gitlab`). It has never run on GitLab.

### Operations

- The public relay runs on the lean signing install and fails loudly; a repository can relay in its own merging run.
- **Install by one pull request**: a link that opens GitHub's editor with the workflow file filled in, and five
  terms templates (`knos init --pr`, `knos terms`, the site's Install page).
- **The upgrade feed.** Every proposal of the upgrade multisig is in `web/upgrades.json` and an Atom feed, with the
  program, the build hash, the source commit and the earliest time it can run.
- [`docs/GOVERNANCE.md`](docs/GOVERNANCE.md) says who can change what today, and
  [`docs/INVARIANTS.md`](docs/INVARIANTS.md) what the programs guarantee while they are unchanged.

### The site

- Pages for Install and Capabilities; the badge and the program's own record on a repository's and an account's
  record; a copy button beside every address and hash; no page scrolls sideways.
- The Numbers page's merge-to-paid time was measured over no merges, because the Pages build read GitHub without a
  token. The build now passes one.

## 0.3.13 (October 2026)

**Knos pays for software work on signed acceptance: terms fixed before the work, a GitHub-signed run attests they
were met, a Solana program settles.** The unit is now a work order. A bounty on an issue is the smallest one.

This release fixes seven defects in 0.3.12; each is listed under [Security](#security) with its fix. No outside
security firm has examined anything.

### What is live, and when

The escrow and the verifier are upgraded at their existing addresses, through the multisig, with its public 48-hour
delay. That upgrade was proposed on 2026-10-04 07:17 UTC and withdrawn by 0.3.14 before 2026-10-06 07:17 UTC, when
it could have run: it never ran ([`docs/GOVERNANCE.md`](docs/GOVERNANCE.md), section 3).
`knos status` and the site's banner show a proposal while it is pending.

| | live |
|---|---|
| The workflows of this release (installs by hash, `attest.yml`), the command line, the MCP tools that act, the site, records, statements and exports, the policy file, screening, the interface crates and examples | with the release |
| `knos-meter` and `knos-passkey`: new programs at new addresses | once the release run has deployed them |
| Everything below that names a work order: the fee on top, the four judges and the seller's own settlement, warranty, arbiter, split, standing offers, cancellation, top-up, assignment, organisation wallets, private orders | when the upgrade executes |
| The fixes to 0.3.12 bounties: whole-unit limits, the extension list, a Balance's limits, single-use pay tokens | when the upgrade executes |
| Any-issuer keys, Refresh by anyone, private keys | when the upgrade executes |

Until the upgrade executes, `/knos fund` opens a bounty exactly as 0.3.12 did. A bounty funded before it finishes
as it was funded: every 0.3.12 instruction keeps its bytes and its behaviour, apart from the fixes above. Tokens of
the new paths carry audiences that start `knos3:`, so a token of one generation is good for nothing in the other.

### If you fund work

- **You pay the fee on top; the payee receives the posted amount.** 2.5%, at least 0.40 and at most 25 USDC (replaced
  in 0.3.14, before this build ever ran, by three tiers with no maximum). It is
  escrowed with the amount and returned with it if nobody is paid. An order holds between 5 and 500 USDC (replaced in 0.3.14 by 5 to 100,000 on devnet).
- **Each order's money is in a token account of its own.** No vault is shared between orders.
- **Fund any public issue from a wallet, with no file in that repository** ("Fund any issue" on the site, and
  `FundOrderWallet` for a program or a multisig).
- **New options on `/knos fund`:** `warranty N holdback N` keeps a share of each payment (at most 50%) in the order
  for N days (at most 90); it returns to you if your repository attests a revert in that time, and goes to the
  payee otherwise. `arbiter @login` names who rules on a dispute. `neutral off` lets only your own repository sign.
- **`/knos offer @vendor rate R budget B`:** a standing order that pays one vendor R for each accepted change
  until B is spent. No comment per issue.
- **`/knos split @a 60 @b 40`** before a merge: one payment, up to four payees.
- **`/knos cancel`:** the order ends in 7 days at most. A valid payment inside the notice still pays. If someone
  had reserved it, a kill fee fixed at funding (at most 20%) goes to them first.
- **`/knos raise <amount>`** tells you how to top an order up. The top-up itself is signed by the wallet the money
  came from.
- **You can no longer withhold a payment after merging in a public repository.** See the next section.

### If you do the work

- **After a merge you can settle yourself.** `knos settle --neutral <pull request URL>` starts the pinned
  `attest.yml` by hand in a repository of your own. It reads GitHub's public record of the pull request, and the
  escrow pays on that run. The buyer's workflow is not needed. This holds for a public repository and an order
  that was not funded with `neutral off`; the funding reply says which it is.
- **You receive the full posted amount.**
- **No wallet app needed.** The site makes a passkey, and the address it derives can be paid like any other.
  Withdrawing needs only the passkey. The site shows and withdraws both of devnet's test mints: Circle's USDC and
  the faucet's test USDC that a bounty funded by comment pays. The public relay carries a withdrawal from the moment
  `knos-passkey` is deployed; it does not wait for the escrow's upgrade, which that program never calls. Read
  [SECURITY.md](docs/SECURITY.md), section 17, before keeping money there.
- **An organisation can be paid.** A member binds its wallet by hand, from a `knos-claim` repository the
  organisation owns, and a bot's pull request can then pay the organisation that runs it.
- **You can assign a payment.** The bound wallet of a payee signs one order's payment over to another wallet, so
  anyone can advance money against accepted work.
- **A reservation is on chain.** `/knos take` reserves an order for its `reserve` days, and a cancellation while
  you hold it pays you the kill fee.
- **Before you start:** the MCP tool `knos_can_pay` says whether a repository can still pay an issue, and why not.

### If you run a company

- **A count without an escrow.** `knos-meter` counts each evaluation GitHub signed, once, for a buyer and a seller
  in a month: accepted, rejected, and the declared value. It moves no customer money. 0.05 per billable evaluation
  from prepaid credits, 0.02 at volume, and the first 10,000 of a month free. An evaluation is a run of the
  published `attest.yml` with the kind `eval`, started in a repository of the buyer: GitHub's record of a pull request
  there is the verdict (merged: accepted; closed unmerged: rejected), and it is posted as `knos-eval:` for the relay,
  which carries it from the moment the meter is deployed, whatever the escrow's version. `knos statement --meter
  --buyer X --seller Y --month YYYY-MM` recomputes one buyer's and one seller's month from the program's logs.
- **Private orders.** Funded from your organisation's Balance by a comment in a judge repository you choose. The
  chain shows the amounts, the payees and that repository, and no name, issue number, check name or path of the
  private one ([SECURITY.md](docs/SECURITY.md), section 12).
- **Your own issuer.** A wallet registers the key of a server no public runner can reach, such as GitHub
  Enterprise Server. Its tokens pay only private orders funded from that wallet's own Balance.
- **`.knos/policy.yml`:** who may fund, a cap per order, a monthly budget, allowed payees and vendors, default
  checks, standing offers, warranty defaults. A fund comment it refuses is told the line.
- **A Balance has limits:** per day, in total, the repositories that may spend it, and the workflows commit.
- **Records for finance:** `knos receipts` and `knos statement` (CSV among their formats), `knos invoice` (a page
  and a CSV of its lines) and `knos export` (JSON Lines for a SIEM), all recomputed from the escrow's logs.
- **Screening:** a payout to an address on the United States Treasury's sanctions list is refused and held.
- **A lower rate under a contract** is a `Plan` account on chain, 0.5% to 2.5%, until an expiry.

### If you build on it

- **Any RS256 issuer.** `knos-oidc` admits a key of any issuer on GitHub's signature over the pinned rotate
  workflow's run, with the same delay, approval, expiry and revocation as before.
- **`knos-oidc-interface` now reads the second deployment by default.** The first is `v1::read`. It exposes
  `is_private()`, `registrant()`, `issuer_hash()` and `key_usable()`.
- **`knos-pay-interface`:** fund, top up and refund a work order from your own program
  ([`examples/cpi_fund`](examples/cpi_fund)).
- **Examples with tests:** a vault only a workflow can spend ([`examples/workflow_vault`](examples/workflow_vault)),
  a record that GitHub's runner built an executable ([`examples/upgrade_gate`](examples/upgrade_gate)), a proposed
  x402 scheme that pays on attestation ([docs/X402.md](docs/X402.md)), receipts as Solana Attestation Service
  attestations ([docs/RECEIPT.md](docs/RECEIPT.md)), funding from a Squads vault. [docs/COMPOSE.md](docs/COMPOSE.md)
  lists them.
- **MCP tools that act:** `knos_take`, `knos_address`, `knos_fund`, `knos_settle`, `knos_quote`, `knos_can_pay`.
  Each returns the exact comment or transaction to send and sends nothing. Text a repository wrote comes back in a
  field named `untrusted`.
- **Static data on the site:** `bounties.json`, a file per account and per repository, badges and rankings.
- **`knos accept init`** scaffolds a black-box acceptance bundle from a reference implementation;
  [`examples/acceptance`](examples/acceptance) has three tasks that are not code review.
- **Relaying costs less and pays.** A token is two transactions, and a payment tips the relayer out of the fee.

### Security

Seven defects in 0.3.12, and what this release does about each:

| the defect in 0.3.12 | this release |
|---|---|
| Amount limits and the fee floor ignored a mint's decimals, and the record summed raw units across mints. | Limits and the fee floor are whole units, read from the mint. The record counts money as real only in Circle's USDC; every other mint counts as test. |
| A Token-2022 mint with a transfer-hook authority but no program passed the screen, and Pausable was not screened. | A list of allowed extensions. A mint with any other extension is refused when money enters, including ones added to Token-2022 later. |
| A Balance had a cap per bounty but no limit per day or in total, and any repository of its owner could spend it. | A side account its wallet sets: a limit per day, a limit in total, the repositories that may spend it, the workflows commit. A Balance without one is as before. |
| A pay token was not single-use: one token could pay several bounties on one issue with matching terms. | A pay token pays, or holds, exactly one. A marker keyed by the token's signature refuses a second use. |
| The job that signs installed `knos` from PyPI by version, without hashes. | Every job that signs installs by sha256 from a list in the workflow at the pinned commit, imports the standard library and one package, and uses no cache. The two jobs that cannot sign still install by version. |
| The interface crate's `Token::read` defaulted to the first deployment's verifier, which took key attestations from any repository. | It defaults to the second deployment. |
| Keys expired after 30 days unless one personal account's scheduled job attested them again, and one person holds every key of the upgrade multisig. | Anyone can refresh a key GitHub still publishes, by running the pinned workflow by hand in a repository of their own. New keys still need that one account and the guardian. The multisig is unchanged: every member key is still the founder's. |

Also:

- An attestation that registers or refreshes a key counts only while the key that verified it is itself usable.
- The claim parser has unit tests and a fuzz target that compares it with `serde_json`; a nightly job runs it.
- `knos check`, the free check and `knos_check_pr` read a pull request's checklist as the site does: a ticked
  "My PR passes all CI/CD checks" is the author's claim and is held to GitHub's record, and an unticked box, an
  HTML comment or an agent's quoted prompt claims nothing. Nor does a sentence that hedges, negates or instructs
  ("tests should pass", "make sure CI is green"), in the Agent PR Index's words, and the site and the index skip
  an unticked box of any list marker. A description of any shape is read in time linear in its length.
- A proposed upgrade is refused by the proposing script unless GitHub signed that Knos's own workflow built those
  bytes from a commit, and `knos status` says whether a pending upgrade has that record.
- The MCP server marks third-party text as untrusted and can be restricted to named repositories.
- [docs/DRILLS.md](docs/DRILLS.md): refund, the 180-day return, key expiry, the guardian's pause and revocation,
  and a proposed, waited, executed and cancelled upgrade, run against the bytes deployed on devnet in a simulator.
  The rows that need real GitHub tokens were not run.

What is still open is in [docs/SECURITY.md](docs/SECURITY.md), "Known limits".

## 0.3.12 (October 2026)

**The first deployment was made immutable too early.** 0.3.10 deployed two programs and removed their upgrade
authority the same day, before anyone outside had read them. Three outside reviews then found defects that cannot
be patched there. 0.3.12 does not touch it: `programs/` is byte for byte what was deployed, and the bounties funded
on it finish on it. Everything new is a second pair of programs, `programs-v2`, with new addresses. It stays
changeable until an outside review, only through a multisig with a public 48-hour delay, and is then made immutable.

Defects in the first deployment, and what the second does instead:

| the defect | the second deployment |
|---|---|
| A funder could merge a pull request and then veto, taking the money back. | No veto and no review window. A maintainer says no before merging (`/knos reject`); once the pay token exists the payment is final. |
| A merge payment's condition was what the description claimed. It was not fixed on chain. | Terms fixed at funding: the checks that must have passed at the merged commit and the paths that may change. The funding transaction logs them, the bounty stores their hash, and a payment must carry it. |
| A payment was credited to the author's GitHub id inside the program and claimed later, in a second step. | Paid straight to a wallet in the paying instruction. With no wallet known, the bounty is held for that person for 180 days and then returns to the funder. |
| A signing key the program trusted never expired and could not be revoked. | A key expires 30 days after it was last attested, and a guardian can revoke it. Revoking a key also stops the payments that depend on tokens it signed. |
| A new key was admitted on a GitHub-signed token from any repository that called the rotate workflow. A hosted runner with a custom image can carry a standard label in a paid organisation, so that token said less than it seemed to. | The attestation counts only from two repositories of one personal account, started by the schedule or by hand. The key then waits a day and needs the guardian's approval. |
| Real money needed a wallet transaction for every bounty. | A balance: a wallet sets money aside for one GitHub owner, with a cap per bounty and up to four accounts that may spend it by comment. Unspent money goes back only to that wallet. |
| Only classic SPL tokens. | SPL Token and Token-2022 mints. A mint that could tax or block a payout is refused when money enters. |
| The public record did not tell real money from test money or self-payment. | It counts them apart, and counts distinct funders. |
| Nothing could be done about a fault. | A guardian can pause new funding for at most 7 days at a time. The pause does not reach payments, refunds, withdrawals or wallet bindings, and the guardian cannot add a key or move money. |

### If you fund work

- **`/knos fund <amount> [checks: a, b] [paths: glob, ...] [days N] [reserve N]`** on an issue (`/knos bounty` still
  works). The reply states the terms in plain sentences before any money moves. With no checks named, the terms
  take the default branch's required checks, else the checks that ran on its latest commit. A repository with no
  checks is told so: "your merge alone is the acceptance".
- **Six states of evidence.** At the merge each required check is passed, failed, skipped, pending, absent or
  unreadable at the pull request's last commit. Only passed for all of them is acceptance. A check of the same name
  from another app does not count, and neither do Knos's own jobs.
- **`/knos reject [reason]`** on a pull request, before merging: it does not take the bounty.
- **Payment without a merge ("tests mode") is offered only for a black-box check:** the submission runs as a
  separate process and only its output is compared. Everything else is funded in merge mode. The reason is measured
  in [docs/TAMPER.md](docs/TAMPER.md): of 63 cheating pull requests, plain CI passed 56, in-process acceptance
  tests 7 and the black-box check none.
- **`/knos tip <amount>`** on a merged pull request: a small bounty funded and paid at once.
- **A pull request merged before the bounty was funded is not paid.** A pay token must be issued after the funding.
- On devnet a faucet in the program mints the test USDC, so one comment is still all it takes.

### If you do the work

- **Paid to a wallet.** The wallet bound to your GitHub account, else the address in your own
  `/knos address <address>` comment on the pull request. Binding is by hand only: create a repository from the
  template `drexthealpha/knos-claim`, run its "knos claim" workflow from the Actions tab and paste your address
  yourself, or run `knos claim <address>`, which does both. The program takes only a run started by hand, and no
  link, repository description or push carries an address in, because an address in a link could be someone else's.
- **`/knos take`** reserves an unassigned funded issue for the bounty's `reserve` days; **`/knos release`** gives it
  back. An assigned issue pays only its assignee's pull request.
- **A coding agent's pull request pays a person only on an act GitHub authenticates:** the issue's assignee, a
  maintainer's `/knos pay @login`, or `/knos mine` from a person named in the pull request's assignees. 0.3.11 paid
  the login a line in the description named; an agent can be talked into writing such a line. Those lines are now
  shown as a hint and decide nothing. An edited comment never counts.
- **`/knos settle`** tries a merged pull request's payment again. **`/knos status`** says what is in escrow.
- **Every `/knos` comment gets a reply**, including an unknown command, a malformed one and one from someone who may
  not use it. The reply says what was understood and what to type instead.

### If you install it

- **One workflow file for the whole payment flow**, `.github/workflows/knos.yml`: comments and new issues, the push
  a merge makes, a run by hand. A second, optional file puts the check on every pull request.
- **No `pull_request_target`.** From 2 Nov 2026 GitHub blocks workflows it triggers on public repositories unless an
  admin allows them, and a fork's `pull_request` run gets no token. A merge is now read from the push it makes.
- **The workflows are published at one commit of `drexthealpha/knos-workflows`** and install the judge as the exact
  PyPI release. They take no inputs, so a calling repository cannot change which code judges. A bounty records
  that commit and is paid only by it.
- **The check's memory is an issue.** Since 26 Jun 2026 GitHub denies cache saves to the runs that could write it,
  so what the check learned is kept as comments in an issue labelled `knos-memory`, written by GitHub Actions and
  read by every run. Comments by anyone else, and edited ones, are ignored.
- **Private repositories.** With a relay key in the repository's secrets the job carries its own tokens to Solana,
  and nothing is posted in public.
- **Install routes**, each tested: a plugin for Claude Code and Codex, an extension for Gemini CLI, links for Cursor
  and VS Code, the free check as a GitHub Action, the JavaScript client, the Rust interface crate
  ([docs/INSTALL.md](docs/INSTALL.md)).
- **One gate for a release.** `release.yml` runs the whole test workflow on the tagged commit before anything is
  published, and every publishing job needs it. PyPI takes the upload by trusted publishing first, and by the
  repository secret `PYPI_API_TOKEN` when that does not work; with neither the job fails and names both.
- **No cache in a job that signs or holds a secret.** A cache written by a run of pull request code could be read by
  a job that signs, so these jobs install with `enable-cache: false`. A test fails if one does not.
- **Node 24.** GitHub removed Node 20 from Actions runners on 23 Sep 2026. Every pinned action that runs on Node is now a
  release that runs on Node 24, and `scripts/action_pins.json` names each by its commit.

### For other programs

- `knos-oidc-interface` reads a token of either deployment (`Token::read`, `v2::read`); IDLs for both in `idl/`.
- The verifier's arithmetic and claim reader are unchanged, byte for byte, between the deployments.

### Corrections to what 0.3.11 said

- **"Nobody can change it" and "no admin" are true of the first deployment only.** The second can be changed by
  Knos, through the multisig, after 48 hours, until an outside review. Today every key of that multisig is the
  founder's.
- **17.8% is "a failed check of any kind"**, not "failed CI": 147 of 826 repositories. Counting only a failed test,
  build, lint or type-check job, by its name, it is 80 of 826, 9.7%. Both are published under those names.
- **The index is not "rebuilt every 6 hours".** A scan is scheduled every 6 hours and replaces the published list
  only when it has finished. Before, a run that counted too few pull requests ended green and published nothing;
  now it fails in the open.
- **RSA-4096 tokens above about 5,000 bytes could not be verified by 0.3.11's client.** Its last step ran out of
  compute units. The plan is now 2, 3, 3, 3, 4 and 1 squarings, and every size up to 8,192 bytes verifies, on both
  deployments ([docs/BENCH.md](docs/BENCH.md)).
- **The history.** The public repository's history starts on 1 Sep 2026, and 83 of its 209 commits up to 0.3.11
  predate the hackathon ([docs/DISCLOSURE.md](docs/DISCLOSURE.md) has the counts and the commands).
- **The market.** The unsourced figure for agent spending is gone; [docs/MARKET.md](docs/MARKET.md) is bottom-up
  with every input labelled.

### Measured

- The tamper benchmark now has three sample repositories, in Python, JavaScript and Ruby: 63 cheating pull
  requests. Plain CI passed 56, the in-process judge 7, the black-box check none ([docs/TAMPER.md](docs/TAMPER.md)).
- Of 241 merged agent pull requests whose description said tests pass, 30 had a failed check at the head commit
  ([docs/BENCH.md](docs/BENCH.md), "Merged anyway").
- Compute units of every instruction of the second deployment, four random walks of 2,500 steps over its escrow,
  and the first deployment's record on devnet are in [docs/BENCH.md](docs/BENCH.md).

### From outside

Three pull requests by another GitHub account, `jaystay-bot`, written for bounties Knos funded on this repository:
`knos_bounties` says what each bounty is about (#32), a repository's own record in the Agent PR Index on the site
(#33), and a Ruby runner for the judge (#34).

### Not done

No outside review. No mainnet. No real money has moved, and by 3 Oct 2026 no outside repository had funded a task.
[docs/SECURITY.md](docs/SECURITY.md) lists every known limit.

## 0.3.11 (2 Oct 2026)

No change to the two programs: they are immutable, and `programs/` is byte for byte what was deployed.

- **A merge alone no longer pays.** The check every bounty pull request gets runs once more at the merged commit,
  in the job that asks GitHub for the token and runs no pull request code. A description that says tests pass
  mints a token only if GitHub's record of that commit bears it out: a failed check, checks still running or an
  unreadable record all mint nothing. A pull request that claims nothing is paid on the merge and the repository's
  rules.
- **An agent's pull request pays the person who ran it.** A pull request opened under a bot account (Copilot, Devin,
  Jules, Cursor) names its operator in different ways: an assignee, a `Requested by: @login` line, the co-author of
  the head commit. Knos reads each, or an explicit `Knos-Pay-To: @login`; a description that names two people, or a
  name GitHub does not confirm, pays nobody. Before, a bot's pull request with no assignee failed.
- **An assigned issue pays only its assignee.** An unassigned bounty is open to anyone; assigning it reserves it.
- **The check alone, with no money.** `check.yml` and `examples/knos-check.yml`: one file, and every pull request's
  "tests pass" is compared with GitHub's record. No token, no wallet, no chain. The site offers both installs.
- **`knos claim <address>`.** One command does what took five steps in the browser: it uses your `gh` login, runs
  the claim in a repository you own, and waits until the money has arrived.
- **`knos mcp`.** A read-only MCP server, registered by `knos init` for Claude Code, Codex, Cursor and Gemini CLI:
  an agent can list funded issues it could take, check a pull request's claims, and see what its operator is owed.
  Listed in the MCP registry on release.
- **For other programs.** `crates/knos-oidc-interface`, a Rust crate with no dependency that reads a verified
  token (the example now uses it: 21,632 compute units); IDLs for both programs in `idl/`; the JavaScript client as
  an npm tarball on every release.
- **The relay survives a race.** On devnet, two runs carried one proof at once and both gave up. A failure that
  says nothing about the token is now tried again on the next pass; every transaction asks for the compute units
  it needs (a cluster gives 200,000 unless asked, which the local test chain had not enforced).
- **Every action is pinned to a commit**, in every workflow and example.
- **The measurement is restated.** One pull request per repository: 147 of 826 (17.8%). The earlier figure, 660 of
  2,431 pull requests (27.2%), leaned on a few busy repositories; both are published, the first is quoted.
- **The docs say what this version cannot do**: a trusted key cannot be revoked, rotation depends on timing, and
  bugs are for ever ([docs/SECURITY.md](docs/SECURITY.md)), with what the mainnet version changes. The market
  section now says how small the bounty market is and where the money is ([docs/MARKET.md](docs/MARKET.md)).
- Knos runs on its own repository (`.github/workflows/knos.yml`, pinned to the previous release, since a repository
  cannot name its own commit before it exists).
- Windows: Sibyl's database handles are closed after each call, so the store can be moved or deleted.

## 0.3.10 (2 Oct 2026)

AI agent work gets paid only when GitHub's own signature, checked by Solana, proves it passed.

One product. Everything else moved to [drexthealpha/knos-labs](https://github.com/drexthealpha/knos-labs).

- **Nobody controls the proof.** Two new programs replace the escrow: `knos-oidc` verifies GitHub Actions and GitLab
  CI tokens on chain, and `knos-pay` holds and pays bounties. Neither has an admin instruction, and both are made
  immutable after deployment. The issuers' keys are constants in the binary; a new key enters only on GitHub's own
  signature, from a rotate workflow whose commit is fixed in the binary and which anyone can call.
- **Paid to a GitHub account.** A bounty is paid to the pull request author's GitHub user id. No wallet, stake or
  address is needed to do the work. The author claims later, to any address, by running one workflow in a
  repository they own.
- **Funded with one comment.** `/knos bounty 20` on an issue, or as a line of a new issue.
- **Paid on merge, in any language.** The default mode pays when a maintainer merges the pull request that closes
  the issue, an hour later unless a maintainer vetoes (the pull request's own description names the issue, so a
  wrong claim can be taken back). `review 0` pays at once.
- **A check on every bounty pull request**, running none of its code: the repo's CONTRIBUTING rules, what its
  history made required, and whether "tests pass" in the description is true at the head commit. This is the Stop
  hook's check at the place an agent cannot remove it.
- **Tests mode, hardened.** Python, Node, Go, Rust, any command, and a black-box runner whose verdict the pull
  request's code cannot touch. Pull request code runs in a sandbox: another user, an empty environment, no network
  during tests. The judge is the code at the workflow's own commit; the calling repository cannot swap it.
- **The real tokens fit.** Tokens up to 8,192 bytes (0.3.9 refused GitHub's real tokens: its limit was 2,048 and
  they are about 2,100 to 2,300). RSA-4096 for GitLab.
- **Tested like something that will not be changed.** 517 Wycheproof vectors, a differential test against OpenSSL,
  a 10,000-step random walk over the escrow, 21 cheating pull requests against three judges
  ([docs/BENCH.md](docs/BENCH.md), [docs/TAMPER.md](docs/TAMPER.md)).
- **A relayer cannot be made to burn money**: it refuses, by reading the chain, tokens that could not pay, before
  spending a fee, and always takes its rent back.
- **The site**: fund, read an escrow, see what is waiting for a GitHub account, claim, and the public numbers with
  outside use counted apart from Knos's own. A JavaScript client with no dependency (`sdk/settle`).
- **`knos mainnet-check`** now checks immutability and provenance. It fails on one line on purpose: no outside audit.
- **Removed**: the admin-registered escrow and its Squads multisig, coordination claims and the edit guard, the MCP
  server, budgets, Knos Pro, the jobs market, Tempo. `knos init` now installs only the Stop hook and removes what
  earlier versions installed.

## 0.3.9 (2 Oct 2026)

AI agent work gets paid only when GitHub's own signature, checked by Solana, proves it passed.

- **FundWithToken.** A bounty can be funded straight from a token account in one instruction.
- **Issuer registry, GitHub and GitLab.** The escrow keeps a registry of OIDC issuers and their keys; GitHub Actions
  and GitLab CI tokens are both accepted, each checked against its own registered issuer.
- **Program version check.** The client reads the deployed program's version and refuses to talk to one it does not
  know.
- **Verified build pin.** The program is built with solana-verify in docker, and `knos mainnet-check` compares that
  hash with the on-chain program hash.
- **Squads vault upgrade authority.** The devnet upgrade authority is the Squads v4 vault
  `4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo` (2-of-3, 300 s time lock). All 3 members are Knos keys today, so
  `knos mainnet-check` adds two gates that fail until an outside signer joins and the time lock is at least 24 h
  ([docs/SECURITY.md](docs/SECURITY.md)). Mainnet stays locked.
- **IDL on chain.** The escrow's IDL is published as a Program Metadata account.
- **Sibyl store in the judge.** The judge reads the repo's rules and past rejections from the Sibyl store before it
  rules.
- **Claims check.** `python scripts/claims_check.py` checks every number in the README's opening, the home page hero,
  the submission and the pitch script against devnet, GitHub or a file in the repo, and fails on any sentence with a
  number it does not cover. CI runs it on every push.

## 0.3.7 (1 Oct 2026)

AI agent work gets paid only when GitHub's own signature, checked by Solana, proves it passed.

- **GitHub's proof, verified on chain.** The escrow verifies GitHub Actions OIDC tokens itself.
  - The signature check is RSA-2048, done in Montgomery form in two transactions (1,148,681 and 1,193,853 compute
    units). The token is written through a buffer account first.
  - The program checks the issuer, the pinned `prove.yml` tag (`job_workflow_ref`), the repository, the ref and
    `aud = knos:<job>`. Each proof can be used once.
  - GitHub's 4 JWKS keys are registered on devnet; r2 is checked once, when a key is registered.
  - A "github" job pays the worker only on a verified token. With no proof by the deadline, the buyer gets the price
    back plus the claim stake.
  - Tests cover tampered claims and signatures, wrong keys, workflows, audiences, repositories and refs, and replay,
    plus a 10,000-step fuzz with 0 violations.
- **`prove.yml`, a reusable workflow.**
  - Job 1 runs `.knos/proof.toml`, read from the base branch, on the PR head with no token.
  - Job 2 runs no PR code. It mints a token for `knos:<job>` and calls `knos prove`.
  - `knos proof run` runs a repo's checks. Knos proves its own work with `prove-demo.yml`.
- **Front door, nothing to install.** The home page is "Paste an agent PR". Your browser asks GitHub directly and shows
  in 0.95–2.5 s whether the PR's "tests pass" is true at its head commit, along with that agent's record. "Protect
  this repo" opens GitHub's new-file page with the workflow already filled in: 2 clicks. The Agent PR Index (per
  agent: claimed green, actually failed) is rebuilt every 30 minutes into the Pages site, with no data commits, and
  each batch root is attested on devnet SAS.
- **Bonded PR bounties.**
  - A maintainer funds an issue; a 0 bounty is allowed.
  - An agent claims it with a stake, and the proof transaction pays the bounty plus the stake back.
  - The escrow takes several mints (AddMint).
  - A devnet-only faucet mints test USDC from a program-owned mint.
  - The web wallet is a passkey guarding a throwaway devnet gas key, topped up by `POST /gas`.
- **Sibyl on the money path.** Before a proof is minted, the checks recall the repo's rules from Sibyl:
  CONTRIBUTING.md, plus past rejections. `lint` fails a PR that breaks one and cites the line; `learn` makes each
  flagged rule a required check.
- **Compared against** CodeRabbit, Algora, Vouch, Virtuals ACP and Upwork ([docs/COMPARE.md](docs/COMPARE.md)).
- **Fee:** 2.5% everywhere. The pitch is Solana only.
- **Next** (not in 0.3.7):
  - LazorKit's paymaster with a call into the Knos escrow (untested; the gas-key wallet is used instead);
  - a Squads upgrade authority with a timelock, a solana-verify build, and the IDL on chain;
  - agent verdicts written to Solana Agent Registry reputation;
  - list 257-byte multi-mint jobs in the web app's "My jobs".

## 0.3.6 (1 Oct 2026)

AI agent work gets paid only when someone other than the agent proves it.

- **The escrow enforces proof (live on devnet).**
  - When a job names a verifier, the buyer cannot reject it; only the verifier (pass or fail) or the deadline settles
    it.
  - At the deadline, delivered work with no verdict pays the worker, and undelivered work refunds the buyer
    (`knos jobs settle`, which anyone may run).
  - A buyer cannot claim their own job.
  - A claim takes a worker stake (10% of the price, at least 0.1 USDC). The stake comes back on delivery and goes to
    the buyer if the claim times out.
  - Every settle closes the job account and returns its rent to the buyer.

  Every old attack test passes, plus one test per rule, along with a 10,000-step fuzz with 0 violations.
- **Built, tested and deployed in Actions** (`.github/workflows/program.yml`): a pinned, cached agave runs
  `cargo build-sbf`, the attack tests and the fuzz. Then, from main only, it upgrades the devnet escrow and prints the
  upgrade signature and the program hash. Nothing in the release path depends on a local machine.
- **The fee is max(2.5%, 0.05 USDC)** (it was 5%). A new admin instruction, LowerFee, can only lower the fee, never
  raise it.
- **Always on:** the reference worker and verifier run in public Actions every 5 minutes and settle jobs past their
  deadline. RPC calls back off on 429.
- **Measured on devnet** (1 Oct 2026):
  - A job posted from the web app was paid by its verifier 167.9 s after first visit, with nobody clicking accept.
  - A delivery that broke a recalled "no emojis" preference was rejected, citing line 2, and the buyer got 1.00 USDC
    back in the same transaction.
  - Upgrade `4Ze3XMVV…oidiYpQD`; program sha256 `92bdd991…70be71`.

- **A verified job's delivery is one envelope:** a copy sealed to the buyer and one to the verifier, both checked
  against the digest the chain commits to. The verifier reads exactly the work the buyer gets.
- **ERC-8183 on Tempo** ([docs/ERC8183.md](docs/ERC8183.md)): KnosEscrow on Moderato
  (`0x8B913C5946a4C1CD95089D7a563dB864d46b694E`) implements the ERC-8183 job interface with the Knos verifier rule.
  The evaluator can never be the provider, only the evaluator or expiry settles a funded job, and `claimRefund` after
  expiry cannot be blocked. The fee is 2.5%.
- **For builders:**
  - an Anchor-format IDL (`programs/knos_escrow/idl.json`, checked against the Python builders);
  - `@knos/escrow` (`sdk/escrow`, unpublished), with instruction builders tested byte for byte;
  - a CPI example (`examples/cpi_escrow`): an on-chain agent that claims and delivers a job.
- **Next:** move the devnet upgrade authority to a Squads multisig with a timelock, and have program.yml propose
  upgrades to it.

## 0.3.5 (1 Oct 2026)

AI agent work gets paid only when someone other than the agent proves it. The Stop hook for coding agents is the
free way in.

- **A verifier, wired.**
  - `knos jobs post --verify knos|KEY` names who decides.
  - `knos verify JOB` (or `--all --once`) re-runs the brief's checks: code briefs in a clean venv, plus the buyer's
    preferences recalled from Sibyl. It commits the evidence root and signs a pass or a fail. A delivery that
    contradicts a recalled preference fails, and the failure cites the line.
  - The web post form has a "Verified by" choice; the Knos reference verifier is the default.
- **Always-on worker workflow** (`.github/workflows/worker.yml`): the reference worker and verifier in public
  Actions. It finds the live relay from the devnet pointer memo. It runs by hand until its key secrets are set.
- **CI under 5 minutes** on pull requests:
  - uv with a cache, `pytest -n auto`, and the Solana CLI pinned and cached;
  - 10 property rounds on PRs (200 nightly);
  - mac and windows on 3.12 only, with Windows in two shards (the full matrix runs nightly);
  - superseded runs are cancelled.

  Per job, chain went from 829 s to 169 s, macOS 3.12 from 184 s to 68 s, Ubuntu 3.12 from 74 s to 39 s, and
  Windows 3.12 from 382 s to two parallel halves.
- **COMPARE.md** compares Knos with Upwork, Fiverr, Gitcoin, Virtuals ACP / ERC-8183, Devin and Codex on fee, time
  to payment, refund, who verifies, accounts and cost, from their own pages read 1 Oct 2026.
- **The pitch** is one sentence. Team claims, budgets, Pro and x402 stay in the code and in the reference docs.
- **Next** (not in 0.3.5):
  - **Escrow 0.3.5 is written but not shipped.** Its rules:
    - the buyer cannot reject a job that names a verifier;
    - delivered work with no verdict pays the worker at the deadline;
    - a buyer cannot claim their own job;
    - claims need a worker stake and time out;
    - every settle closes the job account and returns the rent.

    The program could not be built or upgraded on devnet in this release window, so devnet still runs the 0.3.4
    escrow. Until then, a failed verdict on devnet is a refund at the deadline.
  - Turn on the always-on worker's 5-minute schedule (it needs the worker and verifier key secrets), and show the
    measured pickup time on the web.
  - Measure first visit to first paid devnet job (target: under 60 s).
  - Map ERC-8183 onto the Tempo contract with the verifier rule.
  - An IDL, an npm `@knos/escrow`, and a CPI example.
  - Move the devnet upgrade authority to a Squads multisig with a timelock.

## 0.3.4 (1 Oct 2026)

AI agent work counts only when Knos proves it: your coding agent cannot say done, and a hired agent cannot get paid,
until the proof is real.

- **Proof hook.** `knos init` adds a Stop hook to Claude Code and Codex. It reads the agent's last message, and when
  that message claims something Knos cannot prove, the agent is not allowed to finish. Knos runs every check itself:
  - tests in a fresh venv;
  - every job of every CI run for HEAD (`gh run view`);
  - the PyPI version live;
  - each URL answering 200;
  - deleted files gone;
  - the commit author, with no AI trailers;
  - anything in `.knos/proof.toml`.

  After 3 blocks on unchanged evidence it lets the agent stop, with a warning. A PreToolUse guard refuses overwriting
  a file the agent never read, and deleting outside the repo.
- **Sibyl keeps each repo's proof history.** `knos proof learn` turns a past false "done" into a check that is
  required from then on, and `knos proof lint` flags claims the evidence contradicts. Replaying releases 0.3.0 to
  0.3.3:
  - with Sibyl, Knos blocks 0.3.1 and 0.3.2, whose CI failed, and passes 0.3.0 and 0.3.3;
  - with a null store and local pytest alone, it passes all four.
- **Paid on proof.** A job can name a verifier key. When the proof passes, the escrow releases with no human step;
  when it fails, the escrow refunds after the deadline; a dispute re-runs the checks. Every proven "done" can get a
  devnet SAS receipt (the Merkle root of its evidence) and a receipt page (`web/receipt.html`).
- **Guarded launch.** The escrow has a per-job cap and a pause switch. Mainnet stays locked.
- **Economics.** The minimum job is 1 USDC, and the fee is max(5%, 0.05 USDC). Measured margin per 1 USDC job: $0.049 on devnet and $0.050 on Moderato ([docs/ECONOMICS.md](docs/ECONOMICS.md)).
- **Security.** A threat model ([docs/SECURITY.md](docs/SECURITY.md)) and a nightly fuzz of 10,000 escrow steps in LiteSVM checking conservation, no double payout and no stuck funds.
- **Market number.** 18.2% of agent PRs that say tests pass had failing CI at that commit ([docs/BENCH.md](docs/BENCH.md)).
- **One benchmark source.** Every benchmark number in the docs is generated from `docs/bench.json`, and a test fails
  on drift. This fixes the 14→22 and 19/24 figures that disagreed between pages. Modelled baselines are labelled as
  models.
- **Licence.** Everything that can be judged is MIT: the hooks, the proof engine, the escrow, the SDKs, the receipts
  and the web app. Only the paid conveniences in `src/knos/pro/` are FSL-1.1-MIT.
- **Next** (not in 0.3.4):
  - `knos mainnet-check`, a solana-verify verified build, and moving the devnet upgrade authority to the Squads
    multisig (the multisig exists; the transfer has only been simulated).
  - Publish the Claude Code plugin marketplace and MCP registry listings, and fix the plugin's silent failure when
    `knos` is not on PATH.
  - A close instruction so settled job accounts return their rent.
- **Disclosure.**
  - Knos 0.1.0–0.1.8 (shared local memory for coding agents, with topic claims) was written and released 1–7 Sep
    2026, before 14 Sep, and won the Sibyl Labs hackathon.
  - Everything from 0.2.0 on was built from 29 Sep 2026.
  - Scope freezes on 8 Oct 2026.

## 0.3.3 (Oct 2026)

- **Installs everywhere again.** x402 payments on Solana are built in with solders (the same `exact` transaction the
  reference x402 client builds), so `knos[agentpay]` no longer pulls `solana<0.40`, which pinned solders below 0.28 and
  broke every install of `.[dev]` in 0.3.1 and 0.3.2.
- **Sibyl Pro comes with every payment.** Pro, a Team seat, or the 5% fee on an accepted job: the paying wallet has
  Sibyl Pro for the 30 days after that payment, bought by Knos from it (`knos.sibyl_pro`; simulated on testnets,
  built and locked on mainnet). Pro is 22 USDC / 30 days (208 / year) and Team 32 per seat, Sibyl Pro included. The
  second checkout, `sibyl upgrade` prompts and the $12 threshold are gone; `knos jobs sibyl` shows yours.
- **Recall is used.** Session ingest indexes every turn for `knos.recall`; MCP `search` and `sdk.Knos.recall` return
  what it finds; the reference worker remembers its deliveries and recalls similar past jobs into each prompt.
- **`knos work --tempo`** takes jobs on the Tempo escrow (Moderato) too, including the web app's passkey jobs.
- **The web app reads the chain itself.** Jobs, agents and payouts come from devnet in the browser, and post, accept
  and reject transactions are built there, so Pages works with no Knos server; the relay's current address is a
  devnet memo the app reads. The network view separates Knos's own task feed from everyone else's jobs.
- **Removed:** `knos serve` and `knos init --remote` (the 0.2 team server; teams are the Solana registry), the Sibyl
  bundle and second checkout, tier detection, TRACTION, and functions nothing called.
- Acceptance benchmark with a live Gemini worker (gemini-3.5-flash-lite): 19/24 with Sibyl memory, 1/24 without.

## 0.3.2 (Oct 2026)

- Web app: **pay with a passkey on Tempo**. No wallet, extension or seed phrase: a passkey on the device signs Tempo
  testnet transactions (viem `viem/tempo` WebAuthn accounts), Tempo's faucet funds it, and the job goes into the Knos
  escrow contract on Moderato. My jobs shows Tempo jobs with accept and reject.
- `knos.recall`: no-LLM recall over Sibyl. LongMemEval_s held-out (370 questions): 96.8% top-10 (was 81.5%),
  assistant-said 88.4% (was 51.8%), preferences 83.3% (was 50.0%), median 5,656 tokens.
- Reference worker: Gemini uses the native API with retries and a lite fallback (`gemini:gemini-3.8-flash`).

## 0.3.1 (Oct 2026)

Knos becomes the work network for AI agents: hire any AI agent in one step and pay only for work you accept.

### Jobs, paid only on acceptance
- `programs/knos_escrow`: a native Solana escrow program. Post (the price moves into a program-owned vault), claim
  (exactly one worker), deliver (the sealed deliverable's sha256 on chain), accept (95% to the worker, 5% fee, one
  transaction), reject inside the review window (full refund), release by anyone after a silent review window, refund
  after the work deadline. Deployed on devnet at `GwmbMFvyHHwHug5em9dv26oXz2zTgXKGsNdrBxPayRPq`. Tested in the Solana
  runtime (LiteSVM): 11 attacks, edge paths and a 1,000-step conservation fuzz, in about a second.
- `contracts/KnosEscrow.sol`: the same state machine on Tempo, with a guardian that can pause new posts and only ever
  lower a per-job cap (mainnet: 500 USDC until an external audit). Foundry tests incl. a 1,000-run fuzz; deployed on
  Moderato at `0x888d39bB186cC718481E98080Bdb5fd8Df27Ab49`; a Python client (`knos.jobs.tempo`).
- `knos jobs post|list|get|accept|reject|release|refund|prefs|perks|stats|serve|relay` and `knos work`, the reference
  worker: polls, claims, does the job with the operator's own model key (Anthropic, OpenAI, OpenRouter, Groq, Gemini,
  or the operator's own Claude Code / Codex), runs the brief's checks and the buyer's shared preferences locally, and
  never delivers work that fails them.
- Briefs and deliverables live on a content-addressed relay anyone can run; only hashes are on chain. Deliverables are
  sealed (PyNaCl sealed boxes) to the buyer's key, or to a key the web app derives from a wallet signature.
- MCP tools `post_job`, `find_jobs`, `claim_job`, `deliver_job`; Python `knos.jobs.api.serve(agent)` and TypeScript
  `Knos.work(agent)`: a worker in under 10 lines.
- Solana Actions (Blinks) for posting and reviewing a job; `knos jobs serve` hosts them with the network API, the
  relay and the web app on one port.
- `web/`: a static app (wallet-standard): hire, my jobs (open sealed work in the browser, accept, reject), every
  agent's record recomputed from job accounts, and the network. Dark and light.
- `knos bench jobs` (`--live` devnet, `--tempo` anvil).
- Settlement waits for `finalized` where it is within 2 slots of `confirmed` (measured, devnet today), otherwise
  `confirmed`; `knos doctor` says which.

### Memory that makes work accepted
- A buyer's standing preferences are captured as Sibyl `preference` entities, one tenant per wallet, on the buyer's
  machine, and shared with a worker only per job (`--share-memory`). On the 24-job acceptance benchmark: 72 of 72
  preferences recalled (was 54) and 22 of 24 jobs accepted (was 14). Held-out capture set: 21 of 24, no false hits.
- Brief lint before money moves; Sibyl Pro paid by Knos for every $12 of a buyer's fees (checkout simulated in this
  release: Sibyl's partner checkout is not live).

### Tests
- The default suite runs in under 3 minutes on 4 cores (`-n auto`); validator, live-network and long property runs
  are marked `chain`, `live` and `slow`.

## 0.3.0 (Oct 2026)

Knos becomes the coordination and memory layer for the agent economy: who works on what (claims), what is known
(Sibyl memory), what each agent may spend (budgets the chain enforces) and who did what (records anyone can verify).

### Teams on Solana, with no server
- `knos team create|add|remove|leave|status`, `knos team key export|import`. A team is one Solana Attestation Service
  credential (`knos-<16 hex>`), with its own schemas `knos.claim.v1`, `knos.renew.v1`, `knos.member.v1` and
  `knos.record.v1`, and `.knos/team.json` committed to the repo.
- Claims across machines and vendors. A claim is an attestation whose address comes from a salted hash of the unit,
  so two creates cannot both succeed. Overlapping units are ordered by (slot, address). Closes are
  compare-then-close with Lighthouse. Renewals never re-create. Lapsed claims are swept by chain time only.
- Property-tested on a local validator running the devnet-deployed SAS and Lighthouse: five signers, overlapping files
  and folders, a lagging RPC, dust on claim addresses and crashing claimers. Zero double winners and zero blocks of a
  winner (see docs/BENCH.md).
- Nothing in plaintext on chain: paths, repo, names and descriptions are salted hashes or sealed boxes.
- If the chain cannot be reached, edits go ahead locally with a one-line warning. Knos never blocks work on an
  outage.
- `knos mirror`: a background copy of the team's claims, so the guard reads a local table and not the chain.

### Guards everywhere
- Codex: a `PreToolUse` hook on `apply_patch` and Bash writes (`~/.codex/hooks.json`, and `.codex/hooks.json` in
  the repo).
- A git pre-commit and pre-push guard for anything no hook sees. Edit-time for hook tools; commit-time for raw shell
  writes.
- `knos init --team` commits the guard with the repo: `.claude/settings.json` hooks (cloud sessions run these), the
  plugin at project scope, `.codex/hooks.json` and the git hooks. `init --undo` restores every file byte for byte.
- A template for the Copilot cloud agent (`.github/hooks/knos.json.example`). One answer per `tool_use_id` when the
  plugin and repo hooks both run.
- Refusals end with "(Knos)".

### Budgets the chain enforces (Pro)
- `knos budget set <agent> 5/day --chain tempo` authorizes a Tempo AccountKeychain access key with a periodic limit
  and a single allowed call (`transferWithMemo`). `knos budget show` reads `getRemainingLimitWithPeriod`.
  `knos budget revoke` calls `revokeKey`.
- `knos budget set <agent> 20 --chain solana` sets an SPL delegate on a per-agent vault.
- Root keys are encrypted at rest (scrypt N=2^17 + AES-256-GCM). Passphrases are read only at an interactive terminal,
  never inside an agent or CI.

### Records
- One `knos.record.v1` per agent per day: counters plus a Merkle root over its salted events and new Sibyl journal
  entries. `knos agent record <agent>` checks them against the chain.

### Sibyl, load-bearing, and bought in the same command
- `knos learn` (Sibyl's self-learning into team playbooks under `.knos/playbooks/`, imported by every machine) and
  `knos lint` (Sibyl's linter, plus a cross-agent contradiction check built on Sibyl's multi_record search). Both
  call only `MemoryClient`, and on the free tier they say how to get Pro.
- Memory moved into Sibyl's own store (`~/.sibyl-memory/memory.db`, one tenant per repo), where Sibyl's account-wide
  free cap counts it. 0.2 stores are migrated once and kept as `memory.db.migrated`.
- `knos pro buy` then gets Sibyl Pro through Sibyl's own `sibyl upgrade` if Sibyl says you are on the free tier, and
  skips it for Pro and Staker accounts.

### Agents beyond code
- `knos.sdk`: `claim`, `release`, `remember`, `recall`, `budget`, `record`, with generic units (`task:`, `market:`,
  `wallet:`).
- `examples/langgraph_team.py`: two LangGraph agents on Sibyl's own `BaseStore`, never working the same task.

### Public numbers
- `scripts/network_stats.py` and the `network` workflow publish every Knos team on Solana to GitHub Pages,
  split by devnet and mainnet.
- `knos doctor` shows what is guarded and what is not.

## 0.2.1 (30 Sep 2026)

- macOS: a `ctags` that is not Universal Ctags (macOS ships BSD ctags) is no longer used; knos reads the code
  itself, so code-structure answers work on a stock Mac.
- Windows: a licence that expires "now" counts as expired (the clock can return the same instant twice).

## 0.2.0 (30 Sep 2026)

One product: shared memory, file claims and an edit guard for every coding agent on the machine, with Knos Pro for
spend and payments. Built 29 Sep - Oct 2026 on top of 0.1.8.

### Fixed (each has a regression test in `tests/test_v1_fixes.py`)
1. `knos point` deleted the store (and left its -wal/-shm files). Reading is now incremental and never deletes. Starting
   over is `knos reset --yes`, which backs up first.
2. The guard could block the agent holding a claim: the MCP server and the hooks disagreed on who an agent was. One
   identity now, (host, session), shared by MCP, hooks and CLI. The session hook records the session against the host
   process, and the server finds that process on Windows, macOS and Linux.
3. `done` released every claim in the repo. It releases only your own now; `knos done --all` asks first.
4. Claims matched words, so "update the readme" blocked `scripts/update_deps.py`. Claims are now path globs taken in
   one transaction (exactly one winner). A claim naming no resolvable file or symbol is advisory and never blocks.
5. Answers about claimed work were withheld, and `about` leaked them anyway. Nothing is withheld now: answers are
   annotated with who holds which files.
6. The server answered from the last repo anybody pointed at. It answers for the repo it runs in, or says there is
   none.
7. `knos demo` crashed, and errors printed as tracebacks. The console script is `main()`, and every error is one line
   with the fix.
8. `knos remember` said "Noted" when a full store had written nothing. It says so and exits 1.
9. `connect` crashed on some configs and pinned an interpreter path. `knos init` replaces it: it writes the `knos`
   command, backs up every file, never overwrites a file it cannot parse, runs a self-test, and undoes byte for byte.
10. Cursor's guard ran on reads. It guards edits only. The claim that "a pull request is told" is gone.

Also fixed:
- Cursor turns are dated when they were said, not by the database's mtime.
- A session in a parent folder no longer leaks into a child repo.
- Claude Code project folders with `.`, `_` or spaces in the path are found.
- A re-taken claim no longer counts as a new one.
- A search no longer rescans PATH for ctags each time; under WSL that was ~400 ms.

### Added
- `knos init [--undo] [--hosts]`, including Codex (`~/.codex/config.toml`).
- Codex sessions are read into memory.
- `knos claim -p`, `knos reset --yes`, `knos compact`, `knos board`, `knos bench`.
- Knos Pro (`src/knos/pro/`, FSL-1.1-MIT):
  - the spend meter (`knos spend`, from Claude Code and Codex logs);
  - one cap across tokens and agent payments (`knos budget`), enforced by the edit guard;
  - `knos pro buy` with Solana Pay (USDC) or Tempo (`transferWithMemo`), verified on chain;
  - signed licence codes;
  - agent budget wallets (`knos budget fund/agents/sweep`);
  - agents paying APIs over MPP (Tempo) and x402 (Solana) with `knos pay` and the `pay` tool.
- Knos Team: `knos serve`, a self-hosted server for claims, notes and one pooled spend cap across machines, joined with
  `knos init --remote`.
  - Seat tokens are stored as hashes.
  - Host names are checked against an allow-list, and it binds to loopback by default.
  - Every error comes back as JSON.
  - Machines fail open when the server is unreachable.

### Removed
The plane (gateway, control plane, on-chain program and TypeScript agents), withholding, overrides and stand-downs,
`knos changed/reconsider/held/at/verify/why/receipts`, the GitHub Action, and the Knos-own store: Sibyl is the only
memory store.
## 0.1.x (unreleased notes kept for history)

The length of a claim is learned. Every hold used to be thirty minutes,
whoever made it, which is wrong in both directions: an agent that closes its
work loses it mid-task, and an agent that claims and dies blocks the file for
the full half hour every time without the store getting any wiser. The hold is
now a function of the share of claims that agent has actually closed, read out
of the COLD journal - fifteen minutes for an agent that never finishes, forty
five for one that always does, and the old flat thirty for anyone knos has
seen fewer than twice. `knos who` shows the table.

Over one seeded working day with four agents, two of which mostly do not
finish: 29% less time blocked on work nobody was doing, in
`docs/evidence/contention.json`.

Fixed: renaming a claimed file walked straight past the guard. `git mv
risk_guard.py helper.py` and the edit went through, because the guard matched
the path's name against the claim's words. It now recognises the rename -
from git when git has spotted it, and otherwise by comparing the new file
against the committed bytes of the one that vanished. The first version of
that fix called every new untracked file a rename of the missing one, which
refused honest work with a sentence that was not true; both directions are
pinned in `tests/test_rename_bypass.py`.

The README was 1,058 lines and a 43 minute read. It is now about 130 lines,
and the long version moved unchanged to `docs/GUIDE.md`.

## 0.1.8

`knos demo` shows cold-start recall rather than describing it. A separate
interpreter, handed nothing but the repo path, prints its own pid alongside the
repo's commit hash and the wall clock and then reads back what an earlier
process wrote; the next beat deletes the store and every refusal stops. Recall
across a process boundary was always true and was never on screen, so the
strongest half of the argument rested on prose.

This is why the release exists. 0.1.7's README told you to run `knos demo` and
then described a beat that release did not have.

`scripts/collide.py` counts double-grants instead of asserting exclusion.
Sixteen operating-system processes reach for one topic at the same instant,
eight rounds: 0 double-grants in 128 attempts, every refusal naming the agent
actually holding it. The ablated condition is sharing rather than the file -
deleting the store proves nothing, because the next agent recreates it and the
lock works again. Give each agent its own memory instead, which is what an
agent has today, and all sixteen take the same work.

## 0.1.7

`knos demo` runs the whole product on a throwaway repo in about a minute and
then deletes its memory, so the last thing on screen is every refusal
stopping. Every line is a real call rather than a transcript, and the tests
assert the live values appear.

The memory now decides whether money moves. `knos.gate` is asked before any
purchase and answers one of four ways: it refuses to spend while somebody
holds the topic, refuses while the work rests on a reversed decision, serves
what was already bought for nothing, and only otherwise buys. Measured over an
ordinary day of five agents: 5.41x more expensive without the store.

`knos changed` reverses a decision and holds everything reasoned from it - the
edit is refused and the purchase is refused - until `knos reconsider` says
somebody looked. The old wording is archived rather than dropped. `knos held`
lists what is waiting.

`knos restore` rebuilds a repo's decisions from the `.knos/decisions.md` it
commits, so a fresh clone on a machine that has never run knos carries them.
Claims are deliberately not restored: a hold rebuilt elsewhere would assert a
collision that is not happening.

Also: the ablation grew to twelve arms with numbers in
`docs/evidence/ablation.json`, and a judge guide, verification, architecture,
memory-model and evidence ledger under `docs/`.

Fixed: the gate served the wrong asset. It searched rather than reading the
exact topic, so a store holding `market brief: BTC` answered a request for
`market brief: ETH` for free. Saving a cent by returning something true about
a different subject is worse than paying.

## 0.1.6

The bot never answers with silence. Anything it does not recognise - a typo'd
command, or a person saying hello - now gets a sentence and the list of what
does work. Falling off the end of the handler was indistinguishable from a
dead process.

A failed subprocess is no longer returned as though it were an answer. stdout
and stderr were collected into one string, so a Python traceback reached the
chat as content; they are separate now and the exit code decides which the
reader sees.

No path prints a seller's payload verbatim any more: the last fallback in the
formatter used to dump the raw body when it met an unfamiliar shape.

A reply cut at Telegram's length limit says that it was cut, instead of
stopping mid-word.

## 0.1.5

`knos guard --install` refuses the edit, not only the answer. Claude Code,
Cursor and OpenCode each run a hook before a tool call, and a hook can say no,
so an agent about to edit work another agent has claimed is stopped and told
who holds it. It also reads the rules this repo already gave knos and enforces
the ones a machine can check — a prohibition with a path in backticks. Off
until you run it, and `knos guard --uninstall` takes it back out. It fails
open: an unreadable store allows the edit.

`knos export --to <path>` writes the shared record where a repo already keeps
its decisions, instead of insisting on `.knos/decisions.md`. Anything knos
already reads back is still read back, and `knos export` says so plainly when
the path you chose is not.

The Claude Desktop extension now uses the `uv` runtime, so installing it no
longer asks you to find and paste a Python path.

## 0.1.4

Claims are a compare-and-swap: two agents reaching for the same work in the
same second cannot both hold it, and the loser is told who does. A full store
now refuses a claim in words instead of dropping it silently. `knos status`
reports the claims held and says FULL at 5 MB. The pull request Action reports
decisions as well as claims, takes a `github-token` input, and documents its
`pull_request_target` safety. `pytest` runs the critical path in about 25
seconds; `pytest -m ""` runs all of it.

`knos --version` prints the installed version, the same number the MCP
handshake reports — one value, read from package metadata, so the two cannot
drift apart.

`knos export` keeps the shared file to the readable part of a note. What an
agent pays for is a whole API response and the store still holds all of it,
but a decision record other people commit is not the place for a JSON body
and a receipt.

`.knos/decisions.md` is no longer ignored. The file the Action reads out of a
checkout could not be committed in this repository, which meant nothing here
could carry the record it asks other repositories to carry. The store and the
keys stay ignored.

The agent (`agent/bot.ts`) and the x402 payer (`src/knos/buy402.py`) are in
the repository. The README linked both and neither was there, so a clean
clone could not run what it was told to run.

**Use `drexthealpha/Knos/action@v0.1.4`.** `v0.1.3` was tagged before these
Action changes and serves the older file.

## 0.1.3

Declare MCP tool annotations (read-only, destructive, idempotent, open-world) on `search`, `about` and `remember`, and report the installed version in the handshake.
