# The upgrade gate: put your program behind it

## One pull request

The three lines your gate changes (`adopt.py init` writes them; nothing else in the crate changes):

```rust
solana_program::declare_id!("GATE_ADDRESS");
pub const KNOS_REPO_ID: u64 = 123456789;
pub const WORKFLOW: &[u8] = b"OWNER/REPO/.github/workflows/knos-gate.yml@";
```

The install link: `init --link OWNER/REPO` (command 1 below) prints a link to GitHub's page that adds
`.github/workflows/knos-gate.yml` to your repository, filled in, as a pull request: the same kind of link the site's
Install page builds for `knos.yml` (`installLink` in [`web/install.js`](../web/install.js)). That workflow builds your
program on a GitHub-hosted runner on `main` and on release tags, and has your gate record the build. It needs one
secret, `GATE_FEE_PAYER`: a key with a little devnet SOL that can do nothing else.

What it proves, for each build it records: GitHub's runner, running that workflow file of that repository at a
named commit of `main` or a release tag, built bytes whose executable hash is the one in the record
`["build", program, hash]`. `check` then shows, before a vote, whether each pending upgrade's buffer holds recorded
bytes. It does not prove the commit is good, and nothing on chain makes the multisig wait for a record ("What it
cannot do", below).

Before the pull request: deploy your gate once (command 1) and hand your program to a time-locked multisig
(command 2). Teams that already build in a workflow of their own can add the job in `my_gate/gate-job.yml` to it
instead; `--workflow` then names that file.

The gate makes a program upgrade wait a public delay, and lets anyone check that the new bytes are the ones GitHub's
runner built from a named commit. It is for any Solana team whose program is upgradeable. Devnet only.

It is three parts. Two exist already; you deploy one.

| part | whose | what it does |
|---|---|---|
| a Squads v4 multisig with a time lock | yours | holds your program's upgrade authority; an approved upgrade waits the time lock, in public, and a vote can cancel it |
| `knos-oidc` on devnet, `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | already deployed | checks GitHub's signature on a workflow's token, on chain |
| a gate program, [`examples/upgrade_gate`](../examples/upgrade_gate) with three lines changed | yours | writes the record `["build", program, executable hash]` only on a token from YOUR build workflow, on `main` or a release tag, on a GitHub-hosted runner |

Adopters today: 0 ([COMPOSE.md](COMPOSE.md), "Who uses the upgrade gate"). Knos's own four programs are behind it
([GOVERNANCE.md](GOVERNANCE.md)).

## Three commands

Before them, once: a Squads v4 multisig whose time lock is your delay. The time lock is a number of seconds on the
multisig account (`timeLock` of `multisigCreateV2` in the Squads SDK; `SetTimeLock` in a config transaction:
[Squads documentation](https://docs.squads.so/main/development/cli/commands)). Knos uses 172,800 s, 48 hours. You
also need the Knos repository checked out and installed (`pip install .`), and the Solana command line.

**1. Make your gate.** No network; it writes a crate of your own and the job your build workflow adds.

```bash
python examples/upgrade_gate/adopt.py init --repo-id 123456789 --workflow OWNER/REPO/.github/workflows/knos-gate.yml --gate-id GATE_ADDRESS --out my_gate --link OWNER/REPO
```

`--repo-id` is `gh api repos/OWNER/REPO --jq .id`; `--gate-id` is `solana address -k gate.json` of a key you made.
Then build and deploy it with your own key, as any program:
`cd my_gate && cargo build-sbf && solana program deploy -u devnet --program-id gate.json target/deploy/upgrade_gate.so`.
Open the link it printed and propose the file as a pull request (or copy `my_gate/.github/workflows/knos-gate.yml`
by hand; set `PROGRAM` and `MANIFEST` in it to your program). After each build on `main` or a tag it asks GitHub to
sign `gate:<program>:<hash>` and has the gate record it (`adopt.py record`, fees from a key that holds no power).

**2. Hand your program to the multisig's vault.** This is the step that cannot be undone by you alone.

```bash
solana program set-upgrade-authority PROGRAM_ADDRESS --new-upgrade-authority VAULT_ADDRESS --skip-new-upgrade-authority-signer-check
```

From here only a proposal the members approved, and that waited the time lock, can change the program.

**3. Check before every vote.**

```bash
python examples/upgrade_gate/adopt.py check --gate GATE_ADDRESS --program PROGRAM_ADDRESS --multisig MULTISIG_ADDRESS --json upgrades.json
```

It reads every pending upgrade of the program in the multisig and prints, for each, whether the gate holds a
record for the bytes in its buffer, and from which commit. Exit 0 only when every one is recorded. A member who
votes without running it has only their own rebuild to go by.

## An upgrade, afterwards

```bash
solana program write-buffer target/deploy/PROGRAM.so --buffer buffer.json
solana program set-buffer-authority BUFFER_ADDRESS --new-buffer-authority VAULT_ADDRESS
python examples/upgrade_gate/adopt.py expect --gate GATE_ADDRESS --program PROGRAM_ADDRESS target/deploy/PROGRAM.so
python examples/upgrade_gate/adopt.py check --gate GATE_ADDRESS --program PROGRAM_ADDRESS --buffer BUFFER_ADDRESS
```

`expect` prints the executable hash (what `solana-verify get-executable-hash` prints), the audience your workflow
signs and the record's address. Write the build your workflow made, not one from your machine: the record is of
those bytes. Then propose the loader's `Upgrade` in your multisig (a vault transaction), vote, wait, execute.

Knos does the same steps for its own programs with one script that also proposes and votes:
`bash scripts/deploy_v2.sh --propose`, then `node scripts/governance.mjs upgrade execute <index>`. That script names
Knos's four programs and its own multisig; it does not take another team's.

## The feed and the banner

`check --json upgrades.json` writes what it found: the multisig's time lock and threshold, and for each pending
upgrade its buffer, whether it is recorded, the sentence above, and `earliest_execution` (unix seconds; null until
approved). Run it on a schedule and publish the file beside your site. This banner reads it:

```html
<p id="upgrade-banner" hidden></p>
<script type="module">
  const f = await (await fetch("upgrades.json")).json(), p = f.entries ?? [];
  const el = document.getElementById("upgrade-banner");
  if (p.length) {
    const due = Math.min(...p.map((e) => e.earliest_execution ?? Infinity));
    el.textContent = `${p.length} program upgrade${p.length === 1 ? "" : "s"} pending`
      + (Number.isFinite(due) ? `, can run from ${new Date(due * 1000).toISOString().slice(0, 16)}Z` : ", not approved yet")
      + (f.ok ? "" : ". NOT every build is recorded by the gate.");
    el.hidden = false;
  }
</script>
```

Knos's own feed is richer: [`web/upgrades.json`](../web/upgrades.json) and the Atom feed `web/upgrades.xml` keep
every proposal, executed and replaced ones too ([`scripts/upgrade_feed.py`](../scripts/upgrade_feed.py)). The same
script writes that full feed for your programs:

```
python scripts/upgrade_feed.py --ids my_ids.json --gate GATE_ADDRESS --out my_feed
```

`my_ids.json` is `{"upgrade_multisig": "MULTISIG_ADDRESS", "programs": {"my_program": "PROGRAM_ADDRESS"}}`. The feed's
title and links are still worded for Knos: edit the two files' headings before you publish them.

## What it has shown

- **A defect found inside the delay.** The 0.3.13 build of `knos_pay` let a pay token that had paid one order pay a
  second. It was found while the proposal waited and withdrawn before it could run; no order was exposed
  ([CHANGELOG.md](../CHANGELOG.md), 0.3.14; [GOVERNANCE.md](GOVERNANCE.md), section 3). The delay gave the time; a
  person still had to look.
- **An execution that did not happen.** Proposals 3 to 6 are in the feed with the time each could first run and
  the time the multisig marked it executed. The second is about five hours after the first: the run arranged for
  the first time failed before it sent anything, and nothing announced that. The feed showed four proposals still
  `pending` after their time, which is how it was seen ([`web/upgrades.json`](../web/upgrades.json), `entries`:
  `earliest_execution_utc` and `since`).

## What it cannot do

- **It does not say the commit is good.** A record says which commit to read. Nobody is made to read it.
- **Nothing on chain enforces the record.** The Squads program executes any approved upgrade after the time lock.
  The record is checked by `check`, by people. A team that wants it enforced must check the record in a program.
- **The delay is notice, not oversight,** unless the multisig's members are different people. Knos's are not:
  all three keys are the founder's ([GOVERNANCE.md](GOVERNANCE.md)).
- **It trusts GitHub:** its signing keys, its hosted runners, and that your workflow file builds what it says.
- **It depends on `knos-oidc`,** which Knos's multisig can upgrade after 48 hours, and whose signing keys expire 30
  days after their last refresh ([GOVERNANCE.md](GOVERNANCE.md), section 8). If it stops, no new record can be
  written; your multisig and its delay go on.
- **Nobody is told.** The file and the banner reach someone who looks.
- **Not run by anyone else yet.** `init`, `expect` and `check` are tested here, and `record` against Knos's own
  gate in a simulator ([`tests/test_gate_adopt.py`](../tests/test_gate_adopt.py)). A gate made by `init` has not
  been built from the tag or deployed, and `record` has not been sent to devnet for another team's gate. The
  workflow `init` writes and its link are checked here ([`tests/test_gate_link.py`](../tests/test_gate_link.py)); it
  has not run in any repository.
- **Devnet only.** `knos-oidc` is not on mainnet.

To be listed as an adopter: [COMPOSE.md](COMPOSE.md), "Who uses the upgrade gate".
