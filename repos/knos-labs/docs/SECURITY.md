# Security model

AI agent work gets paid only when GitHub's own signature, checked by Solana, proves it passed. This page says what Knos defends, against whom, and what it does not.

Report a vulnerability privately through GitHub's security advisories on this repository.

## Threat model

### What is protected

- **Job money** in the escrow (the Solana program and the Tempo contract);
- **the truth of "done"**: a proof verdict, its evidence root and its receipt;
- **the repo**: files an agent never read, and anything outside it.

### Who attacks, and what stops them

| attacker | wants | what stops it | where it is tested |
|---|---|---|---|
| a worker | to be paid for work that was never proven | only the job's own verifier key can release with a proof root; anyone else signing VerifyRelease is refused | escrow attack tests: "verifier releases unproven work: refused" |
| a worker | to be paid twice, or more than the price | released, refunded and closed are terminal states; payout = price − fee, from the job's own vault | fuzz: no double payout, conservation |
| a buyer | to keep the work and the money | delivery is on chain before review; verifier release needs no buyer step; silence past the review window pays the worker | escrow tests |
| a buyer | to lock the worker's money forever | after its deadline a job always settles one way or the other; no state lacks an exit | fuzz: no stuck funds |
| the verifier | to release work that failed | the evidence root goes on chain with the release and in a SAS receipt, so anyone can re-run the checks; the escrow refuses a release whose result hash is not the one the worker committed | escrow tests |
| Knos itself | to take more than the fee | the fee is max(2.5%, 0.05 USDC), set at init; the fee account is fixed; a per-job cap holds; Knos never holds job money | fuzz: conservation |
| an upgrader | to swap the program | the devnet upgrade authority is a Squads v4 vault (2-of-3, 300 s time lock), but all 3 members are Knos keys; mainnet stays locked until `knos mainnet-check` sees an outside signer and a 24 h time lock | `tests/test_mainnet_check.py` |
| anyone, in an incident | to drain the escrow during an exploit | the pause switch stops new posts and claims; refunds still work while paused | escrow tests |
| a coding agent | to say "done" when it is not | the Stop hook re-runs each claimed check itself (tests in a fresh venv, every CI job, PyPI, URLs, deletions, author) and blocks; Sibyl turns each past false "done" into a required check | `tests/test_proof.py`, release replay |
| a coding agent | to overwrite a file it never read, or delete outside the repo | the PreToolUse safety guard refuses (exit 2) | `tests/test_proof.py` |

### Invariants, fuzzed

Each night, `tests/test_escrow_fuzz.py` runs at least 10,000 random sequences of every escrow instruction against the
real native program in LiteSVM. It runs with random signers, amounts and clock jumps, and after every step it checks:

- **conservation:** vault + paid out + refunded + fees = deposited;
- **no double payout:** a job pays its worker at most once, and never both pays and refunds;
- **no stuck funds:** after every deadline passes, every job can settle and every vault drains to zero.

**Why not Trident.** Trident's stable release (0.12.0) supports Anchor programs only. Native support exists only in
the 0.13 release candidates, and even there it needs a hand-written Anchor-format IDL. The Knos escrow is a native
program with one-byte instruction tags, so the fuzzing uses LiteSVM with the built `.so` instead. Trident can be
adopted when 0.13 is final.

### Not defended

- **Bad checks.** A proof is only as strong as its checks. A repo whose tests assert nothing proves nothing, and
  `.knos/proof.toml` is the place to add stronger checks.
- **A colluding buyer and verifier.** They can release to a worker the buyer chose; it is their money.
- **Hooks removed by a person.** The Stop hook is enforced only where it is installed (see below).
- **The verifier key itself.** It is a hot key on the verifier's machine; a stolen verifier key can release jobs that
  name it until those jobs settle.

## What a Knos proof proves

A GitHub-posted job (0.3.8) is paid on a proof with these parts:

- **GitHub's OIDC token for the pinned workflow.** The token is minted by GitHub Actions for a run of Knos's
  `.github/workflows/prove.yml` at a pinned commit (its `job_workflow_ref`), and is issued by
  `https://token.actions.githubusercontent.com`. A pull request cannot mint it from a workflow of its own.
- **Run on the PR head, with the funder's checks.** The run checks out the pull request's head commit, then overlays
  `tests/`, the CI configuration and `.knos/proof.toml` from the base branch. The pull request cannot rewrite the
  tests or checks it is judged by.
- **Held-out acceptance tests, fail to pass.** The funder's acceptance tests fail on the base commit and pass on the
  PR head. A change that leaves them failing, or tests that already passed before the change, prove nothing and are
  refused.
- **Test count and sentinel.** The run records how many tests ran and checks a sentinel, so a suite that silently
  collects zero tests, or a run that skips the acceptance tests, does not pass.
- **Verified on chain.** The escrow program verifies GitHub's RSA signature over the token on Solana, against
  GitHub's JWKS keys registered with the escrow. No Knos server, maintainer or LLM sits between the token and the
  payout.
- **The audience binds the payment.** The token's `aud` binds the job, the head commit SHA, the hash of the checks
  that ran, and the payout account. A token minted for one job, commit, check set or recipient cannot pay another.

## What it does not prove

- **Code quality beyond the tests.** Readability, design, performance and security are not checked unless a test or
  a `.knos/proof.toml` check asserts them.
- **Tests the funder didn't write.** Only the funder's held-out tests and checks are evidence. Tests the PR adds can
  run, but they are not what the payment rests on.
- **That GitHub, or its signing keys, is honest.** The proof trusts GitHub Actions to have run the workflow it says
  it ran, and trusts GitHub's OIDC keys. A compromised or dishonest GitHub, or a leaked GitHub signing key, can forge
  a proof.
- **That the implementation is real.** A stub that special-cases weak tests (returns the expected values, detects
  the test harness) satisfies them. The defence is stronger held-out tests, not the proof.
- **That the runner was not compromised.** The checks run on a GitHub-hosted runner. Code running on that runner
  during the check job, including the pull request's own code under test, could interfere with the run. The token is
  minted in a separate job that does not run PR code, but a compromised runner image or a GitHub-side compromise is
  outside the proof.

## The Stop hook offline

`knos hook proof` (`src/knos/proof/hook.py`) runs when an agent tries to stop. With no network, it behaves as follows:

- **Nothing to prove: allowed.** If the agent's last message does not claim the work is done, or the directory is not
  a git repository, the stop is allowed with no checks run, online or offline.
- **No check is skipped for being offline.** Only the checks the agent's claim calls for run (plus the repo's rules
  and `.knos/proof.toml` checks). A network check that cannot reach the network fails; it does not pass:
  - `ci` (`gh run list` for HEAD) fails with "gh could not list runs" (60 s timeout per `gh` call);
  - `pypi` fails with HTTP 0 (20 s timeout);
  - `urls` fails for each URL with code 0 (20 s timeout each);
  - `tests` fails if the project cannot be installed into a fresh venv without the network (280 s timeout). It can
    pass if every dependency is already in the local uv or pip cache.
  - Local checks run as usual: `deleted`, `author`, the repo's rules (from the local Sibyl store, or none if it
    cannot open), and custom `[[check]]` commands.
- **It never blocks forever.** Each block records a digest of the failing evidence for the session. Offline failures
  give the same evidence each time (the same HTTP 0, the same SHA, the same exit code), so the digest does not change.
  After `MAX_BLOCKS` = 3 blocks on unchanged evidence, the next stop is allowed, with a warning that names the
  unproven claim and asks the agent to say plainly what is not done.
- **A Knos error allows.** Any exception in the hook is logged to `~/.knos/hook.log` and the stop is allowed. A broken
  install must never trap an agent.

## The upgrade multisig is not yet independent

The devnet program's upgrade authority is the Squads v4 vault `4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo` of
multisig `2zpWe4223nNp6gPnHSAjdwGcu2cGPQtT5jcxf25MSYvV` (threshold 2, time lock 300 s). All 3 members are Knos keys
today: `3AwCof…`, `EwSxyJ…` and `9TGQPf…`. So the multisig is not yet independent: Knos alone can approve and execute
an upgrade.

`knos mainnet-check` therefore has two gates that FAIL today, by design:

- **an outside signer is a member**: at least one member is not in Knos's own key list;
- **time lock >= 86,400 s**: a 24 h window between approval and execution, so users can leave before an upgrade lands.

Mainnet stays locked until both pass, along with every other gate.

## Keys

| key | where | protection | what it can do |
|---|---|---|---|
| team owner | `~/.knos/team/owner.keystore` | encrypted: scrypt (N = 2^17, r = 8, p = 1) + AES-256-GCM; passphrase typed at a terminal | change the signer list, add and remove members |
| member key (one per person) | `~/.knos/team/member.json`, owner-only | hot: it signs every claim, so it cannot be passphrase-locked; it holds a small SOL float | create, renew and close claims; write records |
| cloud member key | the sandbox's secret `KNOS_MEMBER_KEY` | revocable with `knos team remove` | same as a member key; it cannot change signers or move budgets |
| Tempo budget root | `~/.knos/budget/tempo-root.keystore` | encrypted, as the owner key | authorize and revoke agents' access keys |
| Solana budget vault owner | `~/.knos/budget/solana-root.keystore` | encrypted, as the owner key | approve and revoke agents' delegates |
| agent limited key | `~/.knos/wallets/<agent>-<chain>-limited.json`, owner-only | the chain limits it | spend up to its limit, and nothing else |

Passphrases are read only from an interactive terminal. Knos refuses if stdin is not a TTY, or if `CLAUDECODE`,
`CODEX_*` or `CI` is set, and says "run this in your own terminal". So an agent cannot unlock a root key. The test
escape (`KNOS_TEST_PASSPHRASE_FILE`) works only for keystores under `~/.knos-test-wallets/` on a local or test
cluster (`tests/test_keystore.py`).

## Member trust

Any member key can close any claim in its team. That is how claims left behind by a crashed agent are swept. Every
close is compare-then-close: a Lighthouse assertion on the exact bytes of the attestation runs in the same
transaction, so a claim that was renewed in between is never closed by mistake. The rent goes back to the claim's own
signer, never to the closer. A member who closes others' live claims on purpose is visible in the transaction
history. Remove them with `knos team remove`.

## Each guard's scope

| guard | host | sees | does not see |
|---|---|---|---|
| edit guard | Claude Code (PreToolUse on Edit, Write, MultiEdit, NotebookEdit) | its file edits | shell commands that write files |
| edit guard | Codex (PreToolUse on apply_patch and Bash) | patches, and shell commands with visible write targets (`>`, `tee`, `sed -i`, `cp`, `mv`, `rm`, `git mv`, ...) | a program that writes files itself (`python -c ...`) |
| edit guard | Cursor (preToolUse), OpenCode (tool.execute.before), Copilot cloud agent (`.github/hooks`, template) | their edit tools | shell writes |
| commit guard | git pre-commit and pre-push, any host | every staged or pushed file | writes that are never committed |

Edit-time for hook tools; commit-time for raw shell writes. `git commit --no-verify` skips the commit guard, as it
skips every git hook, and nothing records that it was used.

## Known bypasses, stated

- **Blocking the RPC.** Knos never blocks work on an outage, so a machine that cannot reach the chain edits in
  local-only mode with a warning.
- **Disabling hooks.** A person can remove a host's hooks, or run an agent without them. `knos doctor` lists the
  hosts and machines that are unguarded.
- **Hot member keys.** Member keys sit on disk unencrypted so that agents can claim without a person present. A
  stolen member key can claim and close in that team until removed; it cannot touch budgets.
- **Budgets are chain-enforced; caps are not.** The per-agent Tempo and Solana limits hold even if Knos is bypassed.
  The 0.2 spend cap across agents (`knos budget set 20 --per day`) is enforced by the edit guard, so it is advisory
  against an agent that ignores hooks.

## Sibyl credentials

Read only from your own `~/.sibyl-memory/credentials.json` and handed only to Sibyl's own cap gate when a store
opens; never printed, never sent anywhere by Knos. Knos never routes around Sibyl's tier gate or its free-tier cap.
Sibyl Pro that Knos buys for a paying wallet (knos.sibyl_pro) is simulated on testnets, so Sibyl's cap still applies
there.
