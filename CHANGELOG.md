# Changelog

Prices and figures in older entries are superseded; the current price book is [docs/MARKET.md](docs/MARKET.md), section "The price book", and each GitHub release's notes are its entry here.

## 0.3.26 (October 2026)

**Knos in plain words: the README and seven first documents explained for a newcomer, with diagrams and the mark; a
list of every technical word; and three plans written down before anything is built: an upgrade, the keys and a fair
test of a paid pilot.**

The sentence is unchanged: the neutral meter for AI agent work, where neither side keeps the count. Everything is on
Solana devnet, which is test mode: the money is test USDC. Nothing in this release has been used by a person outside
this repository. **No program changes in this release:** nothing under `programs-v2/knos_*`, `programs/`, `idl/` or
`tests/fixtures/*.so` moved by a byte. The interface crates stay at 0.3.14.

### Plain words

- **The README is rewritten** for a reader who has never heard of GitHub, Solana or escrow. Under the logo and the
  sentence, a new line says what a buyer gets: "Pay AI agents only when your checks pass." The site's first screen
  says the same line. Then four parts: how it works, the ten-second check, why nobody can fudge the
  count, and whether it is real. Two of them have a diagram.
- **Seven documents** now open with the mark and three sentences in plain words: the map of the documents, the story,
  the judges' page, governance, the meter, finance and the one transaction. Six of them have a diagram.
- **[`docs/WORDS.md`](docs/WORDS.md)** explains 33 words, from "AI agent" to "Warranty", each in under 20 words. The
  README and the new documents link to it.
- **Tests keep it plain.** `tests/test_readme_plain.py` measures the README with the Flesch-Kincaid grade: it reads
  at grade 4.4, with 10.6 words a sentence (the limits are 8 and 16). `tests/test_docs_plain.py` holds each of the
  seven summaries at grade 8 or lower; they read at 2.3 to 6.9. Both tests also require the mark and an italic caption
  under every diagram.
- **Diagrams are Mermaid.** GitHub draws them, in light and dark. `scripts/diagrams.py render` also draws each one as
  a picture in [`docs/diagrams/`](docs/diagrams), and `--check` fails when a diagram has no picture of its text.
- **PyPI shows the diagrams as pictures.** PyPI cannot draw Mermaid, so the package's page (`README.pypi.md`, written
  by `scripts/bump_version.py`) shows each of the README's diagrams as its picture at the tag.
- **For judges** ([`docs/JUDGES.md`](docs/JUDGES.md)): the 350-word limit now counts what a reader reads; a diagram's
  source and the mark's HTML are not counted.

### Plans, written down, not built

- **A proposed upgrade, knos_pay 2.3** ([`docs/PROPOSAL-2.3.md`](docs/PROPOSAL-2.3.md)): pay when the checks pass,
  with a window in which the buyer can object only by posting a bond; a fee charged at funding, so it does not depend
  on the verdict; the files that judge fixed by their hash at funding, with secret tests committed by their hash; and part of
  the pay held for a warranty. For each change it names the accounts and instructions, what stays the same for open
  orders, the migration, the notice and the risks. It is proposed, not built, not tested and not deployed.
  `tests/test_proposal_docs.py` checks that every name it uses for today's program exists, and that its new names do
  not.
- **The keys** ([`docs/KEYS.md`](docs/KEYS.md)): today one person holds every key. The plan, in four steps: a key held
  by someone who is not the founder, then no change on the founder's word alone, then separate keys for code and for
  fees, then a guardian that can only pause. None of the steps has been taken, and no outside key holder exists.
- **A fair test of a paid pilot** ([`docs/PILOT.md`](docs/PILOT.md)): within each buyer, tasks are drawn by chance
  into Knos terms or the buyer's usual way; the measures, success and failure are written before any task starts; the
  analysis is to be run again by someone outside Knos. `scripts/pilot_plan.py assign` makes the draw from a published
  seed and prints its sha256; `power` says how many tasks are needed: 311 in each group to find a fall from 3.7% (9 of
  241) to 0.5%. Nothing has been run, no buyer has seen it, and nobody outside has agreed to check it.

### Safer defaults

- **The files that judge are protected by default, as before.** A pull request that edits `.github/**` or `.knos/**`
  is refused, however its checks ended; in tests mode the buyer's acceptance tests are fixed by their hash at funding.
  `tests/test_terms_defaults.py` now holds both as the default.
- **A default holdback is written, not switched on.** `knos.terms.window` gives a new work order 10% held back for 14
  days unless the comment or the policy says otherwise. Funding does not call it in this release, because it would
  change what public rounds and plain orders pay: a work order still holds nothing back unless someone asks.

### Prices

- **0.20% is marginal.** By contract, 0.20% applies only to the part of a month's value above 1,000,000 USD. A month
  of 1,500,000 pays 3,000 on the first million and 1,000 on the rest: 4,000 in all. `billing.py` computes it that way,
  and a test holds it ([`docs/MARKET.md`](docs/MARKET.md)).
- **The price in force at funding applies.** Off chain, `billing.py` charges each deliverable the price in force on
  the day its order was funded (`price_at`). A rise needs 90 days' notice, and `check_prices` refuses a list of prices
  that breaks that. The book has one price so far. The 90 days are a term for contracts; none is signed, and the
  program cannot enforce them.

### Fixed

- **The workflows' install date hid each new release from the jobs that install it.** Those jobs install knos from
  PyPI and take nothing uploaded after a cutoff (`UV_EXCLUDE_NEWER`). 0.3.25 set it by hand to midnight, and its
  wheel reached PyPI three hours later. So the claims check, the review and judge jobs of the acceptance suite, and every attest run
  failed wherever the 0.3.25 workflows were used; funding and pay on merge still worked. The test meant to catch it
  compared the cutoff with the date of 0.3.11. Now the release uploads the wheel first, then writes the cutoff ten
  minutes after the time PyPI took it (`python scripts/pinned_workflows.py cutoff`), then the workflows.
  `release.py publish` builds the wheel again and uploads it only if it is the locked one.
  `tests/test_release_order.py` fails when a cutoff comes before the upload of the release it names
  ([`docs/RELEASE.md`](docs/RELEASE.md)).
- **The site's numbers read only the newest 1,000 transactions.** So merge to paid timed 8 of 68 payments, and
  showed a misleading 32 s. The build now reads each program's whole history, a page at a time, within a number of
  pages and a time it is given, and says so when either stops it. It keeps what it read, so the next build reads only
  what is new. The documents keep the dated 26 s over 51 payments.
- **The consumer could not read the relay's transactions.** `examples/consumer` asked devnet in a way that refuses
  version 1 transactions, and Knos's relay sends version 1. It now reads legacy, version 0 and version 1. It also
  accepts both ids one deliverable can have, and says which one it met
  ([`docs/COMPOSE.md`](docs/COMPOSE.md)): changing either id would change ids already written, so neither moved.
- **`knos receipt verify` seemed never to answer.** It read up to 1,000 transactions one by one, with no limit on the
  time. Now it reads, of those, only the ones a receipt is built from: the order's own, its Balance's opening and side
  account, and its owner's plan, each found in that account's own list. All of its requests together get 120 seconds;
  at that time, it says so in one line. An AUTO order's payment of an open pull request is named as what it is: no
  receipt version has its judge, so none is built for it.
- **The index scan ran out of GitHub's hourly limit.** Its workflow had been red since 5 October. The scan now reads
  only what is new, asks about 20 pull requests in one request, and stops before the limit. The next run goes on from
  there, and a stop is a note, not a failure. It fits GitHub's own token; a read-only `KNOS_INDEX_TOKEN` stays
  optional. It has not yet run on GitHub.
- **The strip check on a personal repository.** Only an organisation on GitHub Enterprise Cloud can have a rule that
  requires a workflow; on a personal repository GitHub refuses it. So PARTLY is the most such a repository can reach.
  `knos protect --check-strip` now says that, and what PARTLY still leaves open ([`docs/LAUNCH.md`](docs/LAUNCH.md)).
- **Who pays the fee, said the way the program does it.** On a work order the funder pays the fee on top, and the
  payees get the whole amount (`order_fee`). On a job, which a tip makes, the fee comes out of the amount and is never
  more than it (`fee_of`): the payee gets the rest. Pages that said "the payee pays nothing" now say this, on the
  pricing view too ([`docs/MARKET.md`](docs/MARKET.md)).
- **Old figures stated as current are gone.** The backtest table now says it is the scan's first reading, and gives
  the second reading's 9 of 241 beside it. The security page says the knos_pay 2.2 upgrade has run. The submission
  counts commits and lines at 0.3.25. `scripts/stale_check.py` finds a retired figure in any public file, the tests
  run it on the whole tree, and the claims job runs it on every change.
- **The meter's two prices, side by side.** The price book proposes 100,000 evaluations a month free, then 0.002
  USD each. The deployed meter program charges 0.05 after 10,000 free. Every page that gives the first now gives the
  second beside it.
- **The secret scan asks the right question first.** A key a person reviewed and passed now fails the scan if its
  address ever becomes one Knos operates with. Launch item 2 is done.

### Found by search engines

- **A title for a person**: "Knos. Pay AI agents only when your checks pass.", the line under the sentence on the
  first screen. Every description begins with the sentence.
- **Facts a search engine reads** (JSON-LD): what Knos is, its licence (MIT), and that the software costs nothing to
  install. No rating or review is claimed: none exists.
- **Eight questions with short answers**: the same words on [`web/faq.html`](web/faq.html), in its facts for search
  engines and in the README's new "Questions".
- **Two pages a search engine can list**: the questions and [the ten-second check](web/check/index.html). Each has its
  own title, address, heading and links. The first screen's foot links both.
- **A sitemap and llms.txt** ([`docs/SEO.md`](docs/SEO.md)). Each page's "Last updated" date is stamped by the build
  from the commit it is built from: nobody types it. Only the founder can submit the sitemap to a search engine.

### For judges and buyers

- **The market's size, on one page** ([`docs/submission/MARKET_SIZE.md`](docs/submission/MARKET_SIZE.md)): a formula,
  each outside figure with its link, date and label, and every assumption labelled as one. Knos claims no share of
  it; nothing has been sold.
- **Three things to try, in order** ([`docs/submission/FLOWS.md`](docs/submission/FLOWS.md)): check one pull request,
  follow one paid task link by link, and see two copies of a record give one bill. The judges' page starts with it.
- **The index method, version 2 draft** ([`docs/INDEX_METHOD.md`](docs/INDEX_METHOD.md)): the funnel from search to
  count, intervals that treat pull requests of one repository as related, and a blind re-read of 20 pull requests the
  count leaves out. None of the 20 flipped: 16 agreed, 2 could not be told without logging in, 2 could not be read.
  Version 1 stays frozen, and the lead number is unchanged.
- **Relay replies that say what to do next.** When a request fails for a reason of the asker's own (the issue is
  funded already, nothing is in escrow, an old workflow), the reply says what to do. Those are counted apart from
  failures, and the completion rate is also given over what could have been done
  ([`docs/OPERATIONS.md`](docs/OPERATIONS.md)).
- **The charter** ([`docs/CHARTER.md`](docs/CHARTER.md)): 8 rights, each enforced by a named test, and 4 promises
  that no code holds yet, marked so. Its fingerprint (sha256) is in its footer, and a test checks it.
- **The standard** ([`docs/STANDARD.md`](docs/STANDARD.md)): the signals, cause codes and steps before a supplier is
  banned (mostly a plan, marked so), and the supplier's menu of three tiers.
- **One account is one judge.** The relay no longer completes a quorum when two of its judges' runs were started by
  one account. The program would count them as two; the refusal is the relay's. Knos's own public quorum rounds still
  run: when the funder and every run's starter are the operator's own accounts, the relay carries it, and the payment's
  comment says it is an own round, not independent evidence.
- **Close one invoice in 30 seconds.** On the approver, Enter approves, "Go to approval" jumps there, and one button
  saves the accounting file of the approved lines. A script measured it at 360 and 1280 px: at most 4 clicks, under 30
  seconds on a slowed phone with a person's pace added. No person was timed ([`docs/FINANCE.md`](docs/FINANCE.md)).
  The accounting file bills only approved lines that nothing holds: a line over its purchase order is left out.
- **Signed results from beyond CI** ([`docs/SOURCES.md`](docs/SOURCES.md)): a result counts only when anyone can check
  its signature. The Sigstore adapter checks a build record against Sigstore's published keys. It is tested on two real
  npm records, kept in the tests; no outside source feeds a meter yet.
- **Single sign-on for the self-host bundle**: through any OpenID Connect provider, with roles viewer, approver and
  admin. Each approval and export is a line in a hash-chained audit log in the memory engine, and the approver writes
  it when sign-in is on. Tested against a stand-in provider only: no real provider has been tried, and the bundle has
  never been deployed ([`docs/SELFHOST.md`](docs/SELFHOST.md)).

### Capabilities

- **Eleven new rows** in [`docs/CAPABILITIES.md`](docs/CAPABILITIES.md): the pilot's draw, the judged files refused,
  the price at funding, the whole history read, the index scan within the hourly limit, receipt verify's time limit,
  the cutoff written after the upload, the pages for search engines, the Sigstore adapter and single sign-on (each
  tested here), and the default holdback (written, not wired). Nothing new went to exercised (26 of 271): the same 26
  as before; 3 are deployed only, 238 tested here only and 4 written, not tested.
- **Five rows said "not exercised at the public id" under evidence that they were**: the passkey payee wallet,
  funding by one comment, pay on merge, the pause and one counted evaluation. The notes now agree with the stage.
- **Tests mode, said plainly.** The README called it "orders judged by hidden tests", and its row said the author
  cannot see the tests. The buyer's acceptance tests sit in the repository, so anyone can read them in a public one.
  Both now say what is true: the buyer's black-box tests, fixed by their hash at funding.

## 0.3.25 (October 2026)

**Check any public agent pull request in the browser in about ten seconds and share the result; and ready for a
stranger on launch day: the twenty pre-launch checks answered one by one, a record that survives
missing, late and duplicated evidence, a file for the accounting system, and a reproduction and a consumer that need
nothing of Knos.**

The sentence is unchanged: the neutral meter for AI agent work, where neither side keeps the count. Everything is on
Solana devnet, which is test mode: the money is test USDC. Everything this release adds is "tested locally" in
[`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) unless a line says otherwise; none of it has been used by a person
outside this repository. **No program changes in this release:** nothing under `programs-v2/knos_*`, `programs/`,
`idl/` or `tests/fixtures/*.so` moved by a byte. The interface crates stay at 0.3.14.

### The ten-second check

- **The check** (`#check`, [`web/check.js`](web/check.js)): paste a public GitHub pull request link on the site's first
  screen and the browser reads its description and the checks at its head commit from GitHub's public API, then
  answers: does the description claim the tests pass (the sentence quoted), which checks failed (test, build, lint or
  type, or other), and the verdict in one line. No install, no login, no wallet; nothing is sent to Knos. The rules
  are the index's own: [`web/check_rules.js`](web/check_rules.js) is a port of `scripts/agent_pr_ci.py`, and
  `tests/test_check_rules.py` runs both on all 349 recorded pull requests of
  [`docs/agent_pr_ci.json`](docs/agent_pr_ci.json): they agree on every one.
- **Sharing** ([`docs/SHARE.md`](docs/SHARE.md), [`web/share.js`](web/share.js)): the link
  `#check=owner/repo/123` checks the same pull request again for whoever opens it; "Copy the result" copies the
  verdict, the claim, the counts and the link; "Post on X" opens X's own compose box with them filled in (nothing is
  posted automatically: the reader presses X's own button, or not); "Download the card" draws a 1200 x 630 PNG in the
  browser; a static README badge links to the check of a repository's pull requests, offered only to a repository
  that merged one in the last 30 days.
- **Measured:** from the first paint of the landing page to the verdict drawn, 2.7 s at the median of 3 runs (2,695
  ms; slowest 2,702 ms) on the android profile (360 x 740, processor 4 times slower, slow 4G for the site's files) with
  GitHub's answers recorded ([`docs/perf.json`](docs/perf.json) `first_verdict`). Landing to X's compose box is two
  presses: paste the link (the check runs as it lands), then "Post on X" (`tests/web/front_door.mjs` counts them).
- **Limits:** GitHub answers 60 requests an hour to a reader without a login, and one check costs three, so about
  twenty checks an hour from one address; the page says when the limit is hit and when it resets. A shared link's
  preview on X or elsewhere shows the site's own card, not the verdict: crawlers run no script and never see what
  follows `#`. Attach the downloaded card to show the verdict. Nobody outside this repository has used the check yet.

### The twenty checks

- **[`docs/LAUNCH.md`](docs/LAUNCH.md) answers a common pre-launch list item by item:** 12 done, 5 partly, 3 not
  applicable (Knos has no accounts, no passwords, no email and calls no AI provider), each with its evidence and what
  is not done. `python scripts/launch_check.py` checks offline that every file and test it names exists, that the
  tree holds no key and that the site and package gain no analytics script, email sender or AI provider client.
- **Keys in history.** `scripts/secret_scan.py --history` reads every blob ever committed and reports hits by kind,
  never by value. It found one real key, a program keypair from a build of an example, never on `main` or on any
  published tag, whose address holds no role; it is treated as spent. No GitHub, npm, PyPI or cloud token was found.
- **Rollback.** [`docs/ROLLBACK.md`](docs/ROLLBACK.md): PyPI yank, npm deprecate, the tag, the site, the relay and the
  programs (a guardian pause of new funding, at most 7 days; an upgrade back waits for the time lock), with the
  commands from the tree. No drill of the whole page has been run.
- **Contact.** `SECURITY.md` gives a private reporting path; the README and the site's privacy page give a public one.

### The record API, hardened

- **`knos record serve`** keeps a token bucket per client (2 requests a second, 30 at once by default; 429 with
  Retry-After), states each route and who may call it (anything else is 404), checks every input (400 with one line)
  and never answers with a stack trace: `--debug` or `KNOS_DEBUG=1` prints it on the operator's terminal only. The CLI
  says one line the same way.
- **Tenants.** In the self-host bundle one tenant never reads another's records or counts. The public record page
  shows public chain data and public pull requests, by design.
- **Backup and restore.** `knos archive make` with the event log, ledgers and statements; unzip and run
  `python verify.py` to restore and check. A test backs up, deletes, restores and gets byte-identical statements.

### A record that survives bad evidence

- **Completeness.** `knos statement complete` compares a statement with its sources (the chain's orders and the GitHub
  events its receipts name) and lists each exception: deleted (the pull request or run is gone), omitted (an order paid
  in the period with no line), late (carried to the next period, never silently added) and duplicated (one deliverable
  under two ids: counted once, flagged). A resolution is remembered through the memory engine and recalled when the
  same source comes back. The sources are given as a file; nothing fetches them yet.
- **Finality.** A retried webhook, a delayed or repeated bank status, a transaction dropped before finality and one the
  cluster has only processed never make two or contradictory records; a payment is booked once, when finalized
  ([`docs/INVARIANTS.md`](docs/INVARIANTS.md)).
- **What an upgrade cannot change.** An order keeps the fee schedule stored at its funding; a test reads it from an
  order funded under knos_pay 2.1.

### Use it without Knos

- **Signed reproduction for anyone.** [`docs/REPRODUCE.md`](docs/REPRODUCE.md): a workflow a stranger runs in their
  own repository installs knos from PyPI, runs `knos reproduce` against devnet and has GitHub sign the result.
  `knos reproduce --verify` checks such a run offline against GitHub's keys; `scripts/reproductions.py` lists verified
  ones by owner, Knos's own excluded. Reproductions recorded: 0.
- **A second application.** [`examples/consumer`](examples/consumer) is a Node program with no dependency that reads a
  receipt or statement and the chain and decides alone whether an order is paid, by which transaction and under which
  terms hash, from the published schema and the IDL ([`docs/COMPOSE.md`](docs/COMPOSE.md)). Tested on recorded devnet
  answers; no outsider has used it.

### Finance

- **`knos statement export --to xero|quickbooks|netsuite|csv`** writes the bill-import file of each system, one bill
  per agreed line with its four steps and assurance in the memo, and a held sheet beside it for every disputed, owed,
  duplicate or unsupported line. The statement page has one control: Download for your accounting system. A file
  export: nobody has imported one into any of these products, and Xero's columns were read in a published guide, not
  on Xero's own page ([`docs/FINANCE.md`](docs/FINANCE.md)).
- **Fixed: an owed line was billed.** `--format quickbooks`, `netsuite` and `ariba` billed a line whose policy was met
  but the buyer refused (owed to the supplier). Owed and disputed lines never go into a payable now, on the site too.

### Operations

- **Fan-out.** Every signed transaction a relay sends now goes to the configured endpoint and any second one
  (`KNOS_RPC_SECOND`), is sent again every 2 s until an endpoint takes it and is confirmed by its signature status, one
  status request a poll for every transaction the process waits on; a lost answer is never taken as a refusal. On a
  stand-in devnet that drops answers as devnet did, the burst pays 40 of 40, each once. On devnet on 9 Oct the burst
  paid 22 of 40 (RPC drops, timeouts, HTTP 408) and priority-fee 40 of 40, every PayOrder priced. On 10 Oct, at the
  public program ids with own wallets, the burst with the fan-out paid 40 of 40, with no failure; a first run that day,
  with each transaction's status asked apart every 0.5 s, had its status requests answered HTTP 429 and was stopped at
  11 of 40, which is why one request now serves them all. The runs are in [`docs/LOAD.md`](docs/LOAD.md).
- **The worker's event job** retries its install with `--refresh`, as the claims job does.
- **The grace round** reads a refund someone else sent first and passes with it noted. Run at the public ids on
  10 Oct: its order had been refunded by the public relay 41 s after the grace ended, and the round passed.
- **The task board** funds a task stranded by a new workflow pin again in place and closes none. Not yet run on the
  eight open in the playground.
- **Rounds for the capabilities deployed and not exercised:** tip, meter-single, passkey-payee, gate, guardian, pause
  and gitlab. Run at the public ids on 10 Oct with own wallets, before this release's commit: tip, meter-single,
  passkey-payee, gate and pause passed, and `record` moved funding by one comment, pay on merge, one counted
  evaluation, a payee's passkey wallet, the upgrade gate and the pause to exercised (26 of 260). The guardian round
  did not run (no signing key waits for the guardian at the public knos_oidc), nor the gitlab round (no GitLab project
  of the maintainer's own is noted). hold_and_bind cannot be exercised by one owner, and its note says why.

### The site

- **A 404 page** of the site's own, and a retry line on every page when a data file does not load.
- **A cheap Android phone,** emulated (360 x 740, CPU 4x slower, 1.6 Mbps, 150 ms): first paint 1,392 ms, usable
  1,829 ms; the Console (#buy) drawn 2,549 ms after it opens, from 3,718 ms, by asking for its files at once and for
  the statement's code only when used ([`docs/perf.json`](docs/perf.json)). Not measured on a phone.
- **Privacy and terms** on one short page, linked from the foot; shared links carry their card and tags.
- **The fee fold of #fund** states knos_pay 2.2's rule and follows the program's answer; the statement page's
  assurance column uses the words of `knos assurance`.

### The submission

- **A two-minute cut** of the pitch ([`docs/submission/pitch_script_120.md`](docs/submission/pitch_script_120.md));
  a test bounds its spoken length under 120 s. Every link the submission gives a judge names the release tag.

## 0.3.24 (October 2026)

**The lead number survives a second reading: 9 of 241, not 30. Every accepted line says how much stands behind it,
the witnessed transaction records its settlement, version-1 transactions carry their priority fee, and a payee
collects through one page.**

The sentence is unchanged: the neutral meter for AI agent work, where neither side keeps the count. Everything is on
Solana devnet, which is test mode: the money is test USDC. Everything this release adds is "tested locally" in
[`docs/CAPABILITIES.md`](docs/CAPABILITIES.md) unless a line says otherwise; none of it has been used by a person
outside this repository. **No program changes in this release:** nothing under `programs-v2/knos_*`, `programs/`,
`idl/` or `tests/fixtures/*.so` moved by a byte. The interface crates stay at 0.3.14.

### The upgrade ran

- **knos_oidc 2.2 and knos_pay 2.2 run at the public program ids** since 9 Oct: upgrade proposals 7 and 8 were
  executed by the scheduled run. `python scripts/exercise_public.py status --want 2.2` reads it from the chain.
- **The after rounds ran there and are recorded.** Newly exercised at the public ids: strict JSON and ES256 tokens
  at knos_oidc, the presentation grace at knos_pay and a holdback's release
  ([`docs/CAPABILITIES.md`](docs/CAPABILITIES.md)). The rounds that need a second repository owner, more test USDC
  than the wallet holds or an arranged clock say `cannot`; those waiting on a deadline say `needs time`.
- **The 8-day upgrade time lock is approved, not applied.** Its Squads configuration transaction (proposal 9) was
  created and approved by two member keys; the Squads program executes it only once the present 48-hour lock has run,
  and until then the lock on chain is 48 hours ([`docs/GOVERNANCE.md`](docs/GOVERNANCE.md)).

### The number, read again

- **The lead fell from 30 to 9.** The scan of 1 Oct counted 30 of 241 merged agent pull requests that claimed
  passing tests with a failed check at the head commit, 16 of them a failed test, build, lint or type-check job.
  Each of the 30 was read again by hand on 9 Oct: was it merged, into the default branch, was the claim the agent's,
  did the failure hold. 11 of the 30 were excluded. The lead is now the strict count after that reading: 9 of 241
  (3.7%, 95% interval 2.0% to 6.9%); 19 of 241 (7.9%) had a failed check of any kind. Every one of the 30 is listed
  with its finding and decision in [`docs/index_review.json`](docs/index_review.json); the excluded ones are shown,
  not dropped. The 211 with no failed check were not read again.
- **The method is frozen.** [`docs/INDEX_METHOD.md`](docs/INDEX_METHOD.md) is version 1; its sha256 is in
  `docs/backtest.json` and `scripts/backtest.py --check` fails when the file changes under the same version.
- **`knos reproduce`'s example** is a pull request that is plainly merged.

### Assurance, said per line

- **Four levels.** `knos assurance FILE` prints, for a receipt or each statement line, workflow-reported,
  re-executed, independently attested or proved. Only the first two are reachable today; the other two are defined
  and shown as not reached. A statement keeps four things apart: agreement on the recorded events, completeness of the
  record, correctness of the acceptance decision, and commercial satisfaction, which is never claimed.
- **The Plan floor.** The program lets a Plan lower the fee to 10 basis points; the price book's floor is 20.
  Knos's own Plan builder refuses below 20, and `knos fees plans --check` reads every Plan on the cluster and exits 1
  when one in force is below it. The program still allows 10: the floor is Knos's signer, checked against the chain.
- **The workflow-strip hole.** A buyer who controls the repository can remove the Knos workflow before merging.
  `knos protect --check-strip OWNER/REPO` says closed (a ruleset requires the workflow), partly (a required check
  only) or open, and never closed for those who can edit the ruleset. Tested on recorded GitHub answers.
- **Exceptional review is priced apart:** its own invoice line per case, by contract, never inside the unit prices.

### Witnessed

- **The funding reply is the flow's.** The witnessed script read the token comment posted first as the funding
  reply; it now parses only the flow's reply.
- **The settlement goes into the statement.** `knos statement settle-sync` reads the PayOrder transaction, checks
  amount, payee and order, and records it as the line's settled step. Offline only: the run of 9 Oct, whose line
  still shows "settled" open, predates it.
- **Installs are retried.** The settle job, the worker's claims job and the attest and refused jobs of the neutral judge try the
  install 3 times, the second and third with `--refresh`, because PyPI's index can lag a release's upload.

### Capacity

- **Version-1 transactions are priced.** A compute unit price asked for is now written into a version-1 message as
  its priority fee (`knos.chain.message_v1`), so the relay prices them as it does legacy ones. On 9 Oct the
  priority-fee scenario paid 40 of 40 with version-1 transactions unpriced; that result stands until a rerun.
- **Burst backs off.** The burst scenario now waits with jitter and refreshes the blockhash before a resend; in the
  simulator it pays 40 of 40, each once. On devnet on 9 Oct it paid 13 of 40 (public RPC rate limits and expired
  blockhashes), and that stays the recorded result until the release reruns it.
- **The 9 Oct runs are recorded** in [`docs/LOAD.md`](docs/LOAD.md): hot-funder 40 of 40 (0.185 a second),
  rpc-faults 40 of 40 with 17 retries and no double payment (0.127), priority-fee 40 of 40 (0.173), burst 13 of 40
  (0.039). Own wallets, public program ids.

### The payee

- **One page to collect.** A held payment's reply now links to `#payee=<login>`: make a passkey wallet (no seed
  phrase), open one link to create the claim repository, and start its run with the address pasted. That is 8 clicks,
  4 when the repository exists; it was 13. It is not one click because the program binds a wallet only from a run the
  owner starts; fewer clicks safely needs a program change, which this release does not make
  ([`docs/PAYEE.md`](docs/PAYEE.md)). Not exercised at the public ids. The supplier finance page moved to `#finance`.

### The submission

- **The PyPI page's links work:** its description is the README with every link pinned to the tag (`README.pypi.md`,
  written by `scripts/bump_version.py`).
- **Witnessed links point to the 0.3.23 run** (knos-witness #9 and #10).
- **One transaction, end to end,** for a finance reader: [`docs/submission/TRANSACTION.md`](docs/submission/TRANSACTION.md),
  and a fold on the front door. [`docs/submission/CHECKLIST.md`](docs/submission/CHECKLIST.md) lists what each entry
  needs; the submission names what was built inside the hackathon window and what came before.
- **Python 3.13.** A test failed there because 3.13's traceback quotes the source line that held the text it looked
  for; it now looks for text the source does not hold. The suite runs on 3.13 in CI.

## 0.3.23 (October 2026)

**One story, told the same way everywhere: a line's four steps kept apart, money owed to a supplier said as owed, a
witnessed script that makes a statement with a line, capacity measured with more than one relay, a plan for the
upgrade gap, and a bundle a buyer can run itself.**

The sentence is unchanged: the neutral meter for AI agent work, where neither side keeps the count. Everything is on
Solana devnet, which is test mode: the money is test USDC. Everything this release adds is "tested locally" in
[`docs/CAPABILITIES.md`](docs/CAPABILITIES.md): none of it has run at the public program ids or been used by a person
outside this repository, and each line below says its own limit. **No program changes in this release:** nothing
under `programs-v2/knos_*`, `programs/`, `idl/` or `tests/fixtures/*.so` moved by a byte. The interface crates stay
at 0.3.14.

### Four steps, and owed both ways

- **"Policy met" is not "approved".** In the public sample two lines totalling 650 read "agreed" while nobody had
  approved them. Every statement line now shows four steps, each recorded apart: policy satisfied (the evidence met
  the terms), parties accepted (who, when), payment authorised (by whom, under which policy) and settled (the
  transaction or the bank's file). A line whose only step is the first says "policy met". Files written before keep
  reading: the key `agreed` stays and older words map to it (`knos.ids.line_state`; `tests/test_line_states.py`).
- **Owed to the supplier.** A line whose policy is met that the buyer refused, or left unauthorised past the
  acceptance window (30 days unless given), is shown as owed to the supplier with the appeal one click away, and the
  statement counts these wrongful refusals beside the unsupported charges. Tested both ways.
- **Decisions are remembered.** An approval or a refusal can be kept through the memory engine
  (`knos.proof.history`) and is recalled when the same supplier and terms come back; the approver's row says so.
  With no memory nothing is kept or recalled.
- **The site shows the steps.** The front door's sample, the approver and the statement page draw the four steps as
  one row; a change of step animates and holds still under reduced motion.

### Witnessed

- **The witnessed script makes a statement with a line.** The 0.3.22 run's statements had no lines because the
  settle mode carries only the settlement; the script now takes the paid line from `knos audit export` with the
  judge's verdict and the supplier's invoice line into a log of events, and stops with a sentence when the payment
  is not on chain yet. It reads the faucet's replies by their exact sentences, and when the faucet has already given
  the account its weekly grant it moves 10 test USDC from a key the operator names (`--fund-from KEYFILE`, never
  printed) or stops and says so. A command's limit is `--timeout` (600 s by default). It has not been run again on
  devnet in this release.
- **`knos audit export` reads only the owner's part.** It lists the owner's Balances and reads their histories, a
  few transactions at once, instead of the escrow's newest thousand one by one: on a simulated history the size of
  the witnessed run it makes at most 8 calls and writes the same bytes (`tests/test_audit_speed.py`). It has not
  been timed against devnet.
- **The settle job waits for PyPI** with `scripts/pypi_wait.py`, as the claims job does, before it installs the
  version its lock pins.
- **The logo on PyPI.** The README's wordmark uses absolute addresses pinned to the release tag, and
  `scripts/bump_version.py` moves them.

### Capacity, measured

- **Two measured rates.** At the public ids on 8 October: 40 of 40 PayOrder payments in 211.27 s, 0.189 a second,
  with 4 relays and 4 fee accounts (p50 11.45 s, p95 22.61 s, worst 34.9 s; the relays paid 16, 8, 5 and 11; the fee
  accounts took 14, 9, 9 and 8), against 0.097 a second through one relay ([`docs/LOAD.md`](docs/LOAD.md)). Both runs
  used the project's own wallets and one owner's tokens.
- **Contention scenarios.** `scripts/load.py measure --pay --scenario hot-funder|rpc-faults|priority-fee|burst`
  adds one kind of contention, with faults injected on the way to the simulator. Each is simulated here and gives no
  rate; none has run on devnet yet.
- **The manifest names the fee schedule.** [`docs/MANIFEST.md`](docs/MANIFEST.md) opens with one line per program:
  source, build hash, deployed version, transactions, fee schedule; and it says, for every recorded order at the
  public knos_pay, which fee schedule applied and how that is known.

### Governance and lifecycle

- **The upgrade gap, and its plan.** A seven-day notice can outlast the 48-hour upgrade delay.
  `scripts/timelock_plan.py` prints the Squads configuration transaction that sets the time lock to 8 days, above the
  minimum of the notice plus the grace, and refuses while any upgrade proposal is open or approved and not executed.
  It is planned, not applied: the time lock on chain is still 48 hours ([`docs/GOVERNANCE.md`](docs/GOVERNANCE.md)).
- **One deliverable pays once.** [`docs/INVARIANTS.md`](docs/INVARIANTS.md) has a row for each of refund, reopen,
  standing order, assignment, warranty holdback, partial payments and the bank rail, each naming its test. A bank
  that pays a transfer it first reported as rejected is detected and said, not prevented.
- **An unclear bank answer is held.** A timeout, "unknown" or a status code nobody knows holds each line of the
  transfer as unknown, with a row of its own in the statement; no payment file names it until a later answer says
  paid or returned, and a second instruction under the same settlement id is refused.

### Customer-hosted

- **One bundle a buyer runs.** `deploy/` holds one image (bases pinned by digest, packages installed by hash) and a
  compose file for three roles: the record API, the relay worker over the buyer's own fee payer, and the static site
  with the approver, configured from one `knos.toml` that names keys by file path. `knos selfhost check` validates
  the file and says which keys it needs; `knos selfhost plan` prints the services. It has not been run in any cloud,
  and it has no single sign-on: it listens on 127.0.0.1 for the buyer's own identity proxy
  ([`docs/SELFHOST.md`](docs/SELFHOST.md)).

### The pitch

- **One story.** The spoken script opens on the Agent PR Index finding, follows one transaction, states the founder's
  first place of 92 at the Sibyl Labs hackathon in one sentence, and says the zeros. A judge's single entry is the
  manifest and the witnessed transaction's links, in [`docs/JUDGES.md`](docs/JUDGES.md), the README and the site.
- **Micro-outcomes.** On a 0.99 outcome Knos would earn about 0.00497 (0.30% netted, plus one 0.002 evaluation), so at
  95% gross the direct cost must stay below about 0.00025 ([`docs/UNIT_COSTS.md`](docs/UNIT_COSTS.md)). Netting moves
  transfers, not evaluation cost. The netting example now counts as the program does, in base units: from 17 outcomes
  of 0.99 to one payee the rate, not the floor, is the fee.

## 0.3.22 (October 2026)

**Seven answers to three outside readings: a fee account that is not a bottleneck, a witnessed script that finishes,
facts that stay current, the economics side by side, a fee kept out of the verdict, a site with one "How it works",
and memory that changes a decision.**

The sentence is unchanged: the neutral meter for AI agent work, where neither side keeps the count. Everything is on
Solana devnet, which is test mode: the money is test USDC. Everything this release adds is "tested locally" in
[`docs/CAPABILITIES.md`](docs/CAPABILITIES.md): none of it has run at the public program ids or been used by a person
outside this repository, and each line below says its own limit. **No program changes in this release:** nothing
under `programs-v2/knos_*`, `programs/`, `idl/` or `tests/fixtures/*.so` moved by a byte. The interface crates stay
at 0.3.14 on crates.io and the JavaScript client is on npm (`npm install knos-settle`, 0.3.21, published by trusted
publishing with provenance).

### Capacity

- **The fee account is not a protocol bottleneck.** knos_pay takes any token account of the order's mint that its
  fee owner holds, so the relay now pays each order's fee into one of K such accounts, picked by the order, with no
  program change. `knos relay fee-accounts --k N` prints the plan and sends nothing; `--execute` makes the missing
  accounts. The fees stay the fee owner's in every account; moving them into one is a transfer the Squads vault
  signs ([`docs/RELAY.md`](docs/RELAY.md)). Six seeded fee accounts exist on devnet since 8 October 2026: K = 4 for
  Circle's devnet USDC and for the faucet's test USDC, owned by the fee owner, made by the project's own relayer key
  (addresses and transactions in [`docs/RELAY.md`](docs/RELAY.md)). The public worker still runs with K = 1, so no
  payment has used them.
- **Pay work by order, not by owner.** A token that pays, rules on, cancels or reverts an order travels in that
  order's lane, so one owner's orders spread over several relays; a funding from a Balance keeps its owner's lane.
  `tests/test_fee_shards.py` pays into a seeded account on the 2.1 and 2.2 builds and spreads one owner's 40 orders
  over 4 relays with none taken twice. The only measured rate is still one relay's: 40 of 40 paid in 412.74 s, 0.097
  a second, at the public ids on 8 Oct; the several-relay rate is not measured ([`docs/LOAD.md`](docs/LOAD.md)).

### Witnessed

- **The witnessed script finishes.** `examples/witnessed/witness.py` writes its funding as the command grammar
  reads it (`/knos fund 5 checks: none auto`), and its test drives the script's own comments through the parser and
  the flow fakes. The playground's task page says the same line.
- **The worker's claims job waits for PyPI.** It installs the release only once that version can be installed from
  the index, retrying with backoff (`scripts/pypi_wait.py`).
- **npm's page says npm.** The client's README and [`docs/INSTALL.md`](docs/INSTALL.md) say `npm install
  knos-settle`, with the release tarball as the fallback, and claim no attestation.

### True

- **The checkers read what registries show.** `scripts/truth_check.py` and `scripts/public_face.py` also read each
  SDK README and the descriptions in `package.json`, `server.json` and the plugin manifests; a stale price, an older
  release named as current or a word no Knos document uses fails there too.
- **The Index names its basis.** Every place that prints a share says whether it counts every claiming pull request
  or the first one per repository, and the site shows the basis under the board.
- **A cached copy says which release it is.** The README's generated table has a "This copy" row from
  `pyproject.toml` and this file, and a note above this history says older prices are superseded.

### Economics

- **Budget against requirement.** [`docs/UNIT_COSTS.md`](docs/UNIT_COSTS.md) sets each unit's cost today beside
  what the price book requires and the design that closes the gap; `knos bill margin` prints it. Every figure but
  the chain fees is a budget, not a measurement.
- **Gross fee against cash kept.** `knos.billing` separates the protocol fee from what Knos would keep after relayer
  tips, discounts, credits and channel commissions, and says that fee counters on chain are not company cash.
- **The market from the bottom.** [`docs/MARKET.md`](docs/MARKET.md) builds the Acceptance line as customers ×
  eligible work × adopted share × realised fee, each input sourced or labelled an assumption; no input is measured.
  Stripe, Amazon Web Services and Coinbase were read again on 8 Oct, with what Knos sells beyond each.

### Neutral

- **Knos is paid on acceptance and does not decide it.** [`docs/DISPUTES.md`](docs/DISPUTES.md) says what keeps Knos
  out of the verdict, and `tests/test_neutrality.py` checks it on the source: the fee account only receives fees and
  lowers a rate, the modules that make verdicts know no fee, and the fee reads the amount and the rate only. The
  founder still writes the pinned judge and holds every upgrade key; the separation is in the code and in public.
- **The founder's record, the claim and the checklist.** [`docs/TEAM.md`](docs/TEAM.md) states the founder's first
  place at the Sibyl Labs hackathon with Knos's earlier memory product, and
  [`docs/submission/SUBMISSION.md`](docs/submission/SUBMISSION.md) says what predates the window.

### Memory that changes a decision

- **Preflight recommends from memory.** When the memory engine recalls that work under these terms, or by this
  supplier, ended in a dispute, was won on appeal or was accepted late, `knos preflight`, its MCP tool and the
  supplier's page say "Recommended from memory: ..." with the protection that covers it and the recalled evidence.
  With no memory it recommends nothing ([`docs/submission/DEPENDENCY.md`](docs/submission/DEPENDENCY.md)).
- **The approver's queue is ranked from memory.** An exception that ended the same way before is ranked first and
  labelled ("ended accepted on appeal 3 of 3 times before"); with no memory, no label.

### Site

- **One "How it works", three steps.** Agree the terms; a third party signs the result; both sides get the same bill
  and the money moves. Versioned terms, holdbacks, the five parts of a receipt, netting, reserves and exits each sit
  behind one fold, on the first page and on the Buy, Supplier and upgrade views.
- **The two-sided promise** stands under the buyer and supplier split: buyers can defend the bill; suppliers can
  defend what they are owed.

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
