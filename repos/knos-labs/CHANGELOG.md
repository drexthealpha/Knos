# Changelog

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
