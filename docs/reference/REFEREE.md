<img src="../../web/brand/mark.svg" height="40" alt="Knos">

# The referee: Works, Wanted, Makeable

**In plain words.** The referee answers three questions about a piece of research or code: does it work, does anyone
want it, and can it be made at a profit. A verdict passes only when all three do.

The person or agent doing the work
cannot see the tests that referee it, cannot change the referee, and is refused when it tries one of the known cheats.
Every verdict and every cheat caught can be written to Knos Record ([SUPPLIER.md](SUPPLIER.md)).

Code: `src/knos/referee/` and `src/knos/cheats/`. Tests: `tests/test_referee_*.py`.

## Works

`referee.works(base, pr, seal, hidden_dir=...)` runs five checks in order; the first that fails decides.

| step | what it checks | refused as |
| --- | --- | --- |
| sealed tests | the hidden bundle's hash is the `spec_hash` sealed before work began (`referee.seal`) | `sealed_tests_changed` |
| locked referee | the hash of the checking code that runs (`knos/judge.py`, `knos/referee/`, `knos/cheats/`) is the sealed `judge_hash` | `judge_drift` |
| cheat rules | the cheat library on the change; no code of the change has run yet | the rule's category |
| hidden tests | `knos.judge.judge` on the hidden bundle, unchanged: fail-to-pass, sentinel and canary, sandbox, the base's tests overlaid | `rejected` or `insufficient_evidence` |
| re-run | the same judgment again, fresh; the verdicts agree, and a number agrees within the sealed tolerance (`abs`, `rel`) | `rerun_mismatch` |

The hidden bundle is kept outside the repository (a private repository or a secret) and is copied into a temporary copy
of the base only for the run, so the worker's tree never holds it. What a worker is shown (`referee.judge_candidate`)
is pass or fail and the rule's name; what the sealed suite printed is withheld.

A second machine is a `judge_fn` that referees there; the re-run on this machine already uses fresh inputs, because a
black-box bundle draws its own.

The referee is never weaker than the referee: the referee's own path rule is the first rule of the library, and the referee
still runs on everything the rules let through.

## The cheat library

`cheats.scan(base, pr)` (two trees) and `cheats.scan_diff(diff, base_dir=...)` (a `git diff`) run every change rule;
`cheats.scan_outcome(funded, now)` runs the outcome rules. `knos cheats list` prints each rule; `knos cheats red-team`
runs every known case. A new cheat type becomes a rule with `cheats.add_rule` together with its known-bad case and a
test; ids are never reused and rules are never removed.

The first 63 entries are the tamper benchmark's attacks on the slugify sample, 21 in each of Python, JavaScript and
Ruby ([TAMPER.md](TAMPER.md)). Each names the rule that refuses it, and `tests/test_referee_cheats.py` builds every one
and checks that rule fires before any code runs.

The cases that no text rule could see in principle (a no-op claim, constants for the visible examples, forgery from
inside the test process) are also checked with the rules switched off, and the sealed black-box tests refuse each of
them on their own.

The 63 cases by the category of the rule that refuses them:

| category | cases |
| --- | --- |
| spec_tampering | 21 |
| runner_forgery | 18 |
| runner_tampering | 10 |
| test_edited | 5 |
| hardcoded_answers | 3 |
| no_change | 3 |
| workflow_edited | 3 |

The rules on a change:

| rule | category | what it catches |
| --- | --- | --- |
| spec_file_edited, workflow_edited, test_edited, test_deleted, unrestored_test_config | spec_tampering, workflow_edited, test_edited, runner_tampering | the referee's own path rule (`knos.judge.classify_path`), word for word |
| detects_test_runner | runner_forgery | code that checks whether a test runner loaded it |
| references_sealed_bundle | runner_forgery | code that names the acceptance bundle's folder |
| runner_patch | runner_forgery | code that patches pytest, minitest or node:test |
| assert_disarmed | runner_forgery | code that makes assertions stop failing |
| exit_in_test_process | runner_forgery | a file the runner loads ends the process |
| forged_test_report | runner_forgery | a test report added to the tree |
| skip_added, trivial_assertion | test_edited | tests skipped, deferred or asserting nothing |
| runner_options_tampered, test_script_changed | runner_tampering | options or scripts that change which tests run |
| hardcoded_answers | hardcoded_answers | an input and its expected answer from the same visible test line, written into the code |
| no_source_change | no_change | documentation only, for a claim that the work is done |
| out_of_scope | out_of_scope | a file outside the paths the issue allows (a new test beside the protected ones is allowed) |
| core_path_touched | core_path | a trusted-core path (the self loop's referee, programs, workflows) |
| assertion_removed, detector_marker_removed | assertion_removed | assertions or `knos:detector` markers removed from an existing test |

The outcome rules: `outcome_spec_hash_changed`, `outcome_window_changed`,
`outcome_salt_changed`, `outcome_control_drift` (beyond the agreed tolerance), `outcome_measurement_code_drift` and
`outcome_data_tampered` (data that existed at funding edited or removed; new data is not refused).

How the rules read a change. The repository's language (which directories hold its tests) comes from the base tree
and its `.knos/proof.toml`, never from the files the change adds.

A `git diff` is read with git's quoted paths (non-ASCII names, spaces) and with files that have no `diff --git` line;
a `package.json` edit in a diff counts as a test-script change only when an added or removed line names a test
script.

A rule that crashes, or a diff header that cannot be read, is a refusing `rule_error` finding: the library fails
closed, never open.

Changed in v0.3.31: two rules refused honest work, and both were narrowed. `cheats/` is trusted
core, so a referee change waits for the signature on the release. What changed:

- `hardcoded_answers` counts a visible test line only when the test holding that line exercises the changed file.
  "Exercises" means the test imports the file (Python by module name; JavaScript and Ruby by the file's name in a
  `require`/`import` path; the runner's helpers such as `conftest.py` or `test_helper.rb` count for every test), names
  the file in a string ("calc.py"), or runs it with `-m`. It also covers another changed file that such a file
  imports, so moving the answers into a new module that the tested code imports is still refused. Field names
  (`x["amount"]`, `.get("key")`, dict keys) are left out of a test line's literals because they describe the
  protocol's shape, not an input or an answer. A test with no import line, Go and Rust tests, and a `.json` fixture
  with no test reading it by name keep the strict 0.3.30 reading.
- `references_sealed_bundle` passes a literal that names a specific other file under `.knos/` (`.knos/gate.yml`,
  `.knos/proof.toml`). It still refuses the folder itself (`".knos"`, `".knos/"`), anything under `.knos/acceptance`,
  dynamic or relative names (`f".knos/{x}"`, `.knos/../`), and a line it cannot read.
- `red_team()` still catches 63 of 63. Without `hardcoded_answers` the count drops to 60, as before.
  `tests/test_referee_cheatfp.py` holds the known-good cases and the known-bad ones that are still refused.

Limits that remain: a test that reaches code only through a hub module (a CLI that imports every command) still counts
as exercising whatever that hub imports. A write guard that names the whole `.knos/` folder reads, as text, the same
as the forgery, so it is still refused.

Measured on three 0.3.31 patches (scanned as diffs against a4ea15cf), these two
rules refused 22 files before the change and 12 after: hardcoded_answers went from 20 to 11 and
references_sealed_bundle from 2 to 1.

What is not stopped: the rules read text, so a cheat written in a way no rule names can pass them. That is why the
sealed black-box tests run after them; the benchmark measures how the two walls do together, and the honest
submissions of the benchmark are checked against the rules too (none is refused).

## Wanted

`referee.DemandBook().lock(spec_hash, buyer, amount, escrow_ref=...)` records a pre-order;
`referee.wanted(orders, min_buyers=N, min_locked=X)` passes when N distinct buyers have X locked. Only orders with an
held-money reference count (a pledge is shown and not counted), each buyer counts once, and the bar is set by whoever asks.
Amounts are integers in the currency's smallest unit.

## Makeable

`referee.makeable(quotes, locked_price=P, min_margin=m, fees=f)` passes when the quotes' cost plus fees is at most
`P * (1 - m)`. Every quote must name its source; an expired quote, a missing required kind or mixed currencies refuse.
Fees come from the one fee config (MONEY), passed in.

## The verdict

`referee.verdict(works, wanted, makeable, spec_hash=...)` passes only when all three pass, and writes one `verdict`
entry and one `cheat` entry per cheat caught to Knos Record when the install has it.

`referee.reward(check)` gives an evolving agent 1 for work that passed, 0 for work that failed, and -1 for work a
cheat rule refused, so cheating is never better than failing (the referee as a referee for skill evolution and training
environments).

## Free maintainer mode

The free Knos check (`action.yml`) gains `maintainer-mode`: `off` (the default), `comment`, `label` or `close`.

With it on, the check reads the pull request's diff with the cheat library and labels a pull request that edits
existing tests, touches files outside `scope`, or fails the check; `close` also closes it with one comment naming the
rule and asking for a new pull request.

Knos's own labels whose cause a later push removed are taken off again. The `scope` globs reach Knos as written (the
shell never expands them). No money, no wallet and no chain are involved, and none of the pull request's code runs.

Install: add the Knos check workflow from [INSTALL.md](INSTALL.md), give the job `pull-requests: write` and
`issues: write`, and add `with: maintainer-mode: label` (or `close`) to the `uses: drexthealpha/Knos@...` step; add
`scope: "src/** docs/**"` to name the paths outside contributors may touch.

The decision is made by `knos referee maintainer --base DIR --diff FILE --mode MODE`; the action applies it with
the job's own token.

## Knos Gate in GitHub's own places: code scanning, annotations, attestations, a required check

Knos Gate refuses a pull request that cheats (edits a test, touches a workflow, writes outside the scope the
maintainer set). Since 0.3.31 each refused finding also appears where a maintainer already looks on GitHub, and a
maintainer can make the check required in one command.

Everything here is off unless you turn it on, except the line annotations, which cost nothing.

| what | where it shows | how to turn it on | GitHub documentation (read 14 Oct 2026) |
| --- | --- | --- | --- |
| line annotations | on the "Knos Gate" check, at the first line the pull request changed in each refused file | on by default (Action: `::error` workflow commands; App: `output.annotations` of the check run, 50 per request) | [Checks API](https://docs.github.com/en/rest/checks/runs) |
| code-scanning alerts | the Security tab and the pull request's "Code scanning" section | Action input `code-scanning: "true"` and `permissions: security-events: write`; the App uploads when it holds `security_events: write` (in its manifest since 0.3.31) | [SARIF upload](https://docs.github.com/en/rest/code-scanning/code-scanning#upload-an-analysis-as-sarif-data), [SARIF support](https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/sarif-support-for-code-scanning) |
| receipt attestation | `gh attestation verify receipt.json -R OWNER/REPO` | Action input `attest: "true"` and `permissions: id-token: write, attestations: write` (public repositories, or private ones on GitHub Enterprise Cloud) | [artifact attestations](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds) |
| required check | the branch's merge box: "Knos Gate" must pass | `knos gate require OWNER/REPO --apply` (a token with administration on the repository; without `--apply` it prints the ruleset and changes nothing) | [Rulesets](https://docs.github.com/en/rest/repos/rules) |

### What is in the SARIF log

`knos gate run` writes `knos-gate.sarif` (SARIF 2.1.0) and `annotations.json` beside `verdict.json`
(`src/knos/gate/sarif.py`). One result per finding whose severity is `refuse`, at the first line the pull request
added in that file (line 1 for a file it only removed from).

Each result carries `partialFingerprints.knosFinding/v1`, a hash of the rule and the path, so the same cheat on the
next push stays the same alert. A passing run uploads an empty log, which closes the alerts an earlier push opened.
The log's `automationDetails.id` is `knos-gate/`, so Gate's analyses never mix with CodeQL's.

Nothing in the log is new information: it holds the rule, the category, the path and the sentence the comment
already shows. Like the comment, its text is checked against the hidden tests' lines before it is written; a log that
would quote one is replaced by an empty one.

### The attestation

With `attest: "true"` the Action runs `actions/attest` (pinned to v4.2.2) with the signed receipt as both subject and
predicate (predicate type `https://github.com/drexthealpha/Knos/blob/main/docs/reference/RECEIPT.md#knos-receipt-v1`).
The receipt's own ed25519 signature says which key signed it; the attestation adds a Sigstore record that this
repository's workflow produced exactly these bytes. Anyone checks it with:

```
gh attestation verify receipt.json -R OWNER/REPO --predicate-type https://github.com/drexthealpha/Knos/blob/main/docs/reference/RECEIPT.md#knos-receipt-v1
```

### Not shown live

These features were tested against recorded GitHub request shapes (`tests/test_gate_sarif.py`), not by uploading to a
live repository: the Knos rules for this version allow writes only to branches, pull requests and issues of the test
repository. The first maintainer who turns on `code-scanning` is the first live run.

## Knos Gate: hidden tests on every outside pull request

**In plain words.** You keep some tests secret. Knos Gate runs them on each pull request from outside and says pass or fail in one check and one comment. The author never sees the secret tests, only how many passed.

1. An outside pull request arrives.
2. Cheat checks run on the diff: test edits, scope, data, workflows.
3. The sealed hidden tests run in a sandbox with no network and no token.
4. Gate posts one check and one comment, edited in place.
5. A signed receipt that anyone can verify offline.
*One pull request through Gate. A refused cheat stops it before any of its code runs.*

This section is not the upgrade gate for a Solana program ([`examples/upgrade_gate`](../../examples/upgrade_gate)).

### Why

Maintainers are closing their doors because checking work now costs more than producing it (sources as of 13 Oct 2026):
curl ended its bug bounty on 31 Jan 2026 after valid reports fell below 5%; Google stopped OSS VRP submissions on 1 Oct
2026 ("vast majority not valid"); Sovereign Tech paused its bounty (790+ reports, about 80 accepted).

Others: tldraw auto-closes external pull requests; Ghostty bans drive-by AI pull requests and
uses Vouch; GitHub shipped settings to disable or cap outside pull requests (13 Feb and 17 Jun 2026).

Every filter shipped so far referees WHO sent the work (Vouch, collaborator-only, pull request caps). None checks whether
the work is CORRECT against tests the sender could not see. Gate does that, and works beside those filters: a passing
Gate check can be the bypass signal a maintainer opts into (`pass_label`).

Unsolicited bot pull requests are merged far less often (Greenkeeper 32%, ASE 2017) than opted-in ones (Dependabot
about 70%, median about 4 hours, arXiv 2206.07230). Gate is opt-in by the maintainer and needs no wallet, no token and
no held money.

### Install

Two files and two secrets, all in your repository:

1. `.knos/gate.yml` (`knos gate init` writes a starting one). The schema is `src/knos/gate/gate.schema.json`; an
   example is `actions/gate/example/.knos/gate.yml`.
2. Seal your hidden tests: `knos gate seal path/to/hidden-tests --secret-out hidden.b64` prints the sha256 for
   `hidden_tests.sha256`; store the bundle with `gh secret set KNOS_GATE_HIDDEN < hidden.b64` and delete the file.
   A secret holds at most 48 KB; a larger suite goes in a private repository (`source: repo`, pinned `ref`).
3. Copy `actions/gate/knos-gate.yml` to `.github/workflows/knos-gate.yml` and pin the action to a full commit sha.
4. Optional: a receipt key, `knos gate receipt keygen key.json` then `gh secret set KNOS_RECEIPT_KEY < key.json`.

The GitHub App (two clicks: install, pick repositories) is built but not registered: see "Register the App" below.

### What it checks, in order

| step | runs pull request code? | refuses when |
|---|---|---|
| config | no | `.knos/gate.yml` on the BASE commit is missing or invalid |
| outside only | no | (an owner, member or collaborator is not checked with `outside_only: true`; the check says so) |
| cheat checks | no | a rule of the cheat library refuses (REFEREE's `knos.cheats` when installed, else Gate's local rules: test edited, workflow edited, `.knos/` edited, hidden folder written, runner tampering, out of scope, data tampering, core path, no change) |
| hidden tests | yes, sandboxed | the bundle is not the sealed one, or a hidden test fails, or the re-run disagrees |
| public tests | yes, sandboxed | a public test fails |

`on_fail` decides what a refusal does: `comment`, `label` or `close`. In bounties mode a failing claim is always closed.

### What leaves the runner

Counts only: total, passed, failed, errors, skipped. Never a test's name, message or output. The suites' output and
reports are deleted before the artifact is uploaded, and every text Gate posts is checked against the hidden files'
lines first; a text that would quote one is not posted (`gate.leak_guard`).

### The sandbox, and its limits

The hidden tests run as a user of their own (`knos-sandbox`) in a network namespace with no network, with an
environment of PATH, HOME and LANG only: no GitHub token and no secret. That user cannot write the runner's files, so
it cannot reach `$GITHUB_ENV` or the Knos install that computes the verdict.

`setup` runs from the base commit before the pull request's code is on disk.

The Action fails closed: when the runner cannot make this sandbox (passwordless sudo and `unshare`), Gate stops with
exit 2 and runs nothing. The sandbox writes only a fresh folder of its own; the runner reads its report there without
following links and writes its own files elsewhere. A pass needs exit code 0 AND a report with no failure.

What it does not stop: the pull request's code runs in the same process as the hidden tests, so it can read them while they run and can try to fake their result, because the exit
code and the report both come from that process.

It cannot send them anywhere (no network, no token, no output shown), and the cheat library refuses the edits that fake a result (test runner configuration, `conftest.py`, `.pth`
files). A maintainer who needs more runs the hidden tests in a separate process or machine; that is not built in this version.

### Knos Receipt

Each run writes a receipt (`knos.receipt2`): the repository, pull request and commits; `mode` (hidden, or "public tests
only", said in words); the seal of the hidden tests; counts; the cheat library and its rules; the runner as the run's
environment reports it (not signed by GitHub in this receipt); the re-run; the verdict and its rule.

It is signed with Ed25519. `knos gate receipt verify FILE` checks it with Python's standard library alone
(`src/knos/receipt2/ed25519.py`, RFC 8032), from the JSON or from the saved receipt page. A valid signature by a key not
in `src/knos/receipt2/issuers.json` shows only that its holder signed.

The one listed key was generated for the v0.3.29 sample. It holds no money.

An author can get a receipt for their own pull request to a repository without Gate: `knos gate receipt self` runs the
repository's own public tests and the cheat checks and signs with the author's own key. That receipt says "public
tests only" and that the author issued it.

### Bounties mode

`bounties.enabled: true` adds two things. A pull request that says it closes an issue ("Fixes #12") and fails Gate is
closed.

The payment program is the existing knos_pay one on Solana devnet (`knos fund-wallet OWNER/REPO#N AMOUNT`): the program pays the
merged pull request whose GitHub-signed run met the terms, and takes its fee for the treasury, a token account of Knos's
Squads vault.

`knos gate bounty quote AMOUNT` reads the fee from `config/fees.yaml` (through `knos.money.fees_config`) and `knos gate
bounty treasury MINT` names the fee account. Gate signs no payment and holds no key. There is no fiat on-ramp or
off-ramp.

### The sample, 13 Oct 2026 (synthetic tasks, devnet test tokens)

In the owner's new private test repository `drexthealpha/knos-v0329-gate` (a synthetic `slug()` task, three hidden
tests), with the Action alone. Every run used the `nonet,user` sandbox:

| pull request | Gate | run |
|---|---|---|
| #2 edits the public test | refused, `gate.test_edited`, closed; no test ran | run 38432746562 |
| #3 correct fix plus `setup.py` | refused, `gate.out_of_scope`, closed | run 38432754483 |
| #4 passes the public test only (claims #1) | refused, `gate.hidden_tests_failed` (1 of 3 hidden passed), closed | run 38432762375 |
| #5 correct fix, then a second commit | passed (3/3 hidden, 1/1 public, re-run agreed), signed receipt; one comment, edited in place | run 38432780017 |

The repository is private, so those links open for its owner only; its files (its main, ccf45c30) are in Knos as
[evidence/knos-v0329-gate](../../evidence/knos-v0329-gate) (with the sample pull requests' heads in its SOURCE.json).

The bounty ran in the public test repository `drexthealpha/knos-e2e`, issue [#273](https://github.com/drexthealpha/knos-e2e/issues/273), with a test token minted on
devnet (no value), whose terms require the `Knos Gate` check and allow only `gate_slug.py`:

| step | evidence |
|---|---|
| 5.00 held from the Gate sample wallet `H3iUwqY9aKKD1H9m5MmTYNcwcv8xUkGDDDfps6XjXtBP` | [funding transaction](https://explorer.solana.com/tx/4xurN74ZuqE8Uz9dqUhomSLMA5ko8LAr1gnS2Btafe9oiUHJwz2StfmF6dWBxGqX7VDDr9J1iKc2d242LiTV33fG?cluster=devnet) |
| a claim that fails the hidden tests is closed | [#274](https://github.com/drexthealpha/knos-e2e/pull/274), [run 38433820579](https://github.com/drexthealpha/knos-e2e/actions/runs/38433820579) |
| the correct claim passes Gate and is merged | [#275](https://github.com/drexthealpha/knos-e2e/pull/275), [run 38433833108](https://github.com/drexthealpha/knos-e2e/actions/runs/38433833108) |
| paid 51 s after the merge: 4.95 to the author's bound wallet, 0.05 fee to the treasury account `DkEX9RMi4NvJJTTr8463hctJo2tnS83g9Ti6sqEPCHT9` (owner: the Squads vault) | [payment transaction](https://explorer.solana.com/tx/2MbUhEUKdzLvyHe4WEd8cLqv1HGcKV91GGTNqF8y8EWN4jYTAw36n2nvsLBTsCw8ep9BBZLs3279TaN9Zobt9h1x?cluster=devnet) |

The author of both claims is the repository's owner (`outside_only: false` for the sample); there is no outside user.

### Register the App

The App's code is `github-app/server.py` (logic: `src/knos/gate/app.py`) and its manifest is
`github-app/app-manifest.json`. Nobody has registered it. To run it yourself:

1. Choose the host that will serve `https://<host>/webhook` and replace `REPLACE-WITH-YOUR-HOST` in the manifest.
2. Create the App from the manifest (GitHub: Settings, Developer settings, GitHub Apps, or the manifest flow
   `https://github.com/settings/apps/new?manifest=...`). Choose its name.
3. Download the App's private key and set a webhook secret. Keep both off the repository.
4. On the host: `pip install knos -r github-app/requirements.txt`, set `KNOS_APP_ID`, `KNOS_APP_KEY_FILE`,
   `KNOS_APP_WEBHOOK_SECRET_FILE`, run `python github-app/server.py --port 8787` behind TLS.
5. A repository using the App adds `github-app/knos-gate.yml` as `.github/workflows/knos-gate.yml` and its secrets.

### Commands

`knos gate init | validate | schema | seal | run`, `knos gate receipt verify | keygen | page | self`,
`knos gate bounty quote | treasury`.

## Task packages: a merged fix as a sealed, verified task

**In plain words.** When a maintainer merges a pull request that fixes an issue and adds tests, that pair is a good
task: a real problem, a real fix, and tests that tell right from wrong. `knos taskpack export` packs it. The tests are
sealed, so a solver cannot see them.

Knos checks that the tests fail before the fix and pass after it. Anyone holding
the package can then grade a new attempt, and attempts that edit the tests or wander outside the fix's files are refused.

Only the maintainer opts a task in. Nothing here offers or sells a task package.

### Why

AI labs buy software tasks to train and test agents. Epoch AI reported prices of $200 to $2,000 per task, and that
resistance to reward hacking is the first thing buyers ask for (Epoch AI, 12 Jan 2026).

A task whose hidden tests come from the fix that was actually merged, with cheat rules applied before any test runs,
is that kind of task.

### Export

```
knos taskpack export owner/repo#PR --repo-dir CLONE [--opt-in --maintainer LOGIN] [--encrypt] [--price MICRO_USDC]
```

- Reads the pull request and the issue it closes from GitHub (or offline: `--merge SHA --issue N --issue-title ...`).
- **Opt-in**: `.knos/taskpack.yml` with `export: true` at the merge commit, or `--opt-in` from the maintainer running it.
  Without either, nothing is exported.
- Splits the fix into test files (sealed) and the rest (the reference fix, sealed too).
- Runs the tests at the base commit (they must FAIL) and at the merge (they must PASS), each in a copy unpacked with
  `git archive`. The clone is only read.
- Reads the licence (`LICENSE` / `COPYING`). No licence: the package is for the copyright holder's own use and is marked
  not sellable.
- Fee: the split of a sale comes from the one fee config, `config/fees.yaml`, through `knos.money.fees_config`
  (`task_package`). No price is set, so without `--price` only the source is recorded.

```
<task_id>/public/task.json        manifest: source, licence, opt-in, statement, scope, judge, sealed hashes, the check, fee
<task_id>/public/statement.md     what the solver reads
<task_id>/sealed/tests.tar        the hidden tests (with --encrypt: tests.tar.enc, ChaCha20-Poly1305, key written beside the package as `<task_id>.key`, never inside it)
<task_id>/sealed/reference.patch  the merged fix without its tests
```

The task id comes from the spec hash: sha256 of the manifest, which commits to the sealed files' hashes.
`knos taskpack verify PACK` recomputes both. Nothing in `public/` shows a hidden test's name or content.

### Grade

```
knos taskpack grade PACK --patch candidate.patch --repo-dir CLONE
```

Cheat rules first, and no candidate code runs when one fires: `test_edited`, `out_of_scope` (outside the folders the
fix touched), `workflow_edited` (`.github/`, `.knos/`), `no_change`. When the referee's cheat library is installed
(`knos.cheats.scan_diff`) its findings count too. Then the hidden tests run at the base commit with the patch applied.
The output names counts and rules, never a hidden test.

Reward on the referee's scale: 1.0 pass, 0.0 fail, -1.0 cheat.

### For training environments and the referee

`knos taskpack rows PACK... --out tasks.jsonl` writes one row per package: the statement, repository, base commit,
scope and sealed hashes. `knos.taskpack.atropos.score(row, clone, patch)` returns the reward, for a Hermes Atropos
environment. `knos.taskpack.atropos.referee_spec(pack)` gives the referee the spec hash, hidden-test hash, referee and
rules. Devnet and sample use only.

### Shown on the owner's own repository

On 13 Oct 2026, on a read-only clone of `drexthealpha/knos-e2e`, pull request #272 (closes #271):

- without opt-in: refused;
- with `--opt-in --maintainer drexthealpha`: package `knos-task-9f777dfb79758fdd`, 1 hidden test file, failing before
  the fix and passing after it; no licence file, so marked not sellable;
- grading: the merged fix 1.0, a patch that rewrites the test -1.0 (`test_edited`), a wrong fix 0.0.

The manifest, the three candidate patches, their grading output, the training row and `run.sh` are in
[evidence/repro-0329/](evidence/repro-0329/run.sh). Grading runs the candidate's code on the grading machine without a
sandbox: grade untrusted patches inside a disposable container or VM. A training row holds no path to the package.

Source: `src/knos/taskpack/`, tests `tests/test_taskpack_*.py`.
