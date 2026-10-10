# Rollback: taking a release back on launch day

What to do, surface by surface, when a release of Knos must be taken back. Everything is on Solana devnet with test
USDC. Every key, account and vote named here is the founder's: there is no other maintainer, and outside key holders
today are 0 ([KEYHOLDER.md](KEYHOLDER.md)). So "who can run it" is the founder in every row, with the credential the
row names.

Rule one: **never move or delete a published tag, and never try to replace a published file.** PyPI and npm refuse a
second upload of a version, and the workflows a commit pins install the package by version and hash. Taking a release
back always means two things: mark the bad version, and publish the previous code as the next version.

## The surfaces

| surface | fastest safe step | what it does, and what it does not | credential |
|---|---|---|---|
| PyPI (`knos`) | yank the version | installers skip it, except where it is pinned with `==` | PyPI owner of `knos` |
| npm (`knos-settle`) | `npm deprecate` | every install of it warns; it stays installable | npm owner of `knos-settle` |
| crates.io | nothing in this release | the interface crates stay at 0.3.14 on crates.io; this release uploads no crate | crates.io owner |
| git tag and GitHub release | revert on `main`, release the next version | the tag stays; the next tag carries the fix | write access to the repository |
| the site (GitHub Pages) | revert on `main`; the `pages` workflow redeploys | the site is built from `main` only | write access |
| the relay (`worker.yml`) | disable two workflows | Knos's relay stops; anyone can still relay | admin of the repository |
| the programs | guardian pause of new funding | refuses new funding for at most 7 days; payments, refunds and withdrawals go on | 2 of 3 guardian keys |
| the programs, code | an upgrade back to the previous build | waits for the time lock: 48 hours today, 8 days once applied | 2 of 3 upgrade member keys |

## 1. PyPI: yank

On `https://pypi.org/manage/project/knos/releases/`: **Options** next to the version, **Yank**, and give the reason
(it is shown on the release page and to installers). A yank is not a deletion: installers ignore a yanked release
unless it is the only one that matches a `==` or `===` specifier
([PyPI: yanking](https://docs.pypi.org/project-management/yanking/),
[the file yanking specification](https://packaging.python.org/en/latest/specifications/file-yanking/)). So
`pip install knos` falls back to the version before, while every workflow that pins `knos==<version>` by hash keeps
installing it. That is wanted: a pinned workflow keeps working until its pin moves.

A file on PyPI can never be replaced ([RELEASE.md](RELEASE.md)), so the fix is the next version:

```
git revert --no-edit <the release commit>              # on main
python scripts/bump_version.py <next version>          # writes the version everywhere
python scripts/bump_version.py --check
python scripts/release.py wheel                        # then the order of RELEASE.md ("The commit"): lock, publish,
python scripts/release.py publish                      # cutoff, workflows, stamp; publish needs UV_PUBLISH_TOKEN set
git commit                                             # the one commit, after the cutoff and the stamp
python scripts/release.py pypi-check                   # PyPI's index lists the wheel: only then the push
git push origin main
git tag v<next version> && git push origin v<next version>     # starts release.yml
```

## 2. npm: deprecate

```
npm deprecate knos-settle@<version> "<what is wrong>; use <previous version>"
npm deprecate knos-settle@<version> ""                 # takes the warning back
```

Only an owner of the package can run it, from a machine signed in to npm (`npm whoami` answers with a name); the
release workflow publishes without a stored token and cannot deprecate. A deprecated version stays installable and
warns on install ([npm deprecate](https://docs.npmjs.com/cli/v11/commands/npm-deprecate)). `npm unpublish` is not the
way back: after 72 hours it needs no dependents, fewer than 300 downloads in the last week and a single owner, and a
version number once used can never be used again ([npm unpublish policy](https://docs.npmjs.com/policies/unpublish/)).

## 3. The git tag, the GitHub release and the site

The tag stays where it is. On the GitHub release of the bad version, untick "Set as the latest release" and say in
its notes which version replaces it. The fix is the revert and the next release (section 1). Pinned copies of the
workflows in `drexthealpha/knos-workflows` move only when a new set is built and committed there
(`python scripts/pinned_workflows.py build DIR`, then `stamp SHA`), as [RELEASE.md](RELEASE.md) describes.

The site is built from `main` by `.github/workflows/network.yml` (workflow `pages`) on every push that touches `web/`,
every 30 minutes, and when `release.yml` starts it. A reverted `web/` on `main` is therefore the only change that
sticks; to deploy it at once, run the `pages` workflow by hand (Actions, `pages`, **Run workflow**).

## 4. The relay

There is no pause flag in the relay. Two ways stop Knos's own relay, and either is undone by reversing it:

- **Disable the workflows** `always-on worker` (`worker.yml`) and `relay watchdog` (`watchdog.yml`) on the repository's
  Actions page (**...**, **Disable workflow**). Both must go: the watchdog starts a worker run when none holds the
  chain.
- **Remove the secrets** `KNOS_RELAY_KEY` and `KNOS_WORKER_KEY`. Every relay step then prints "no KNOS_RELAY_KEY
  secret: skipped" and sends nothing. The key file itself stays with the founder.

What it does not stop: the relay decides nothing, and anyone can carry a token with `knos relay --token-file` and a
key of their own ([RELAY.md](RELAY.md)). A token posted while the relay is stopped can expire before it is carried;
running the workflow that minted it again gives a fresh one.

## 5. The programs

**Pause new funding** (knos_pay; the guardian multisig, 2 of 3 keys):

```
node scripts/governance.mjs guardian pause 604800      # 7 days, the most one pause allows
node scripts/governance.mjs guardian pause 0           # lifts it
```

While paused, new funding is refused (error 96); payments, refunds, withdrawals and binds go on, and every open order
keeps the terms and the fee stored when it was funded. A pause can be set again when it runs out.

**Upgrade back to the previous build** (the upgrade multisig, 2 of 3 member keys). It waits for the time lock: 48
hours on chain today; 8 days once the approved configuration change is executed ([GOVERNANCE.md](GOVERNANCE.md)).
With an 8-day lock, a 7-day pause does not cover the wait by itself: set it again before it ends.

```
python scripts/exercise_public.py status --rpc https://api.devnet.solana.com      # which build runs now, by hash
git checkout <the tag that built the previous version>
bash scripts/drill_upgrade.sh --from-devnet            # rehearse on a local validator first
bash scripts/deploy_v2.sh --propose --replace          # KNOS_CHANGES names the program(s) to take back
node scripts/governance.mjs upgrade execute <index> --expect-hash <build hash>     # after the lock
```

`deploy_v2.sh --propose` waits for the build's record at the upgrade gate; a build made on a release tag has one.
`--ungated` is for an emergency only and says so in the proposal. Orders funded under the later build keep their
stored terms and fee. **Not drilled:** an upgrade back to an older build of knos_pay; the previous build must read
every account the later one wrote, and that is to be shown on a local validator before it is proposed.

## What is not covered

- The first deployment (`programs/`) has no upgrade authority and no pause: it cannot be taken back.
- The MCP registry listing and the Gemini extension move with the next release; there is no step that withdraws one.
- No drill of this page has been run end to end.
