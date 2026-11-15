# Integrations: what a bounty or work platform can take from Knos

No platform named here uses Knos, has endorsed it or has been asked. This page is research and three reusable
pieces; it records what each platform's public source says and where a check of the work could fit. Nothing was
opened on any of these repositories.

## The pieces

| Piece | Where | What it does | What it needs |
| --- | --- | --- | --- |
| The `knos-verify` action | [`.github/actions/knos-verify`](../../.github/actions/knos-verify/action.yml) | One step: reads a pull request from GitHub's own record and gives a verdict as JSON, a job summary and a pass or fail. It answers two questions. Does a "tests pass" or "CI is green" in the description agree with the checks on the pull request's latest (head) commit? Did each check you name pass on that commit or on the merge commit? | A job token that can read checks. No secret, no id-token, no wallet, no chain write. Knos is installed from PyPI at one exact version |
| The receipt verifier | [`integrations/webhook`](../../integrations/webhook/README.md) | `verify(evidence, jwks)` in one Python file and one TypeScript file with no dependency: checks offline that a Knos receipt matches the token GitHub signed, and that it is for the repository, pull request and payee the platform expects | The issuer's public keys, as the platform trusts them. No network |
| The "Knos-verified" badge | `knos.badge.verified(receipt)`; [`examples/receipt_consumer/show_badge.py`](../../examples/receipt_consumer/show_badge.py); `renderVerified` of [`web/badge.js`](../../web/badge.js) | Says one deliverable was accepted, links to the transaction the signature was verified in, and is drawn only from a receipt that passes every rule of [RECEIPT.md](RECEIPT.md) with the verdict accepted. It cannot be bought. A receipt that does not check is "insufficient evidence", never a rejection | The receipt, and nothing from Knos at run time |
| The reader template | [`examples/reader_template`](../../examples/reader_template/README.md) | A whole Solana program, in a workspace of its own, that performs one action, and only when a named CI workflow asked for it: for a platform that releases on chain | Two constants, `cargo build-sbf`, a devnet key |
| The badge | [`integrations/badge`](../../integrations/badge/README.md) | "paid on proof" beside a bounty: the SVG and the link to the public record of the payment | A payment the platform checked first |

An example workflow that uses the action is [`integrations/workflows/knos-verify.yml`](../../integrations/workflows/knos-verify.yml).
The tests of these pieces are [`tests/test_integrations.py`](../../tests/test_integrations.py) and
`node --experimental-strip-types integrations/webhook/test.mjs`.

What the action's verdict is not: it does not run the pull request's code, it does not judge the work, and a
repository's administrators can still change what a check name means. It says what GitHub recorded for a commit.

## How a platform would use them

The smallest useful integration is the same almost everywhere: the platform already waits for "merged"; it adds an
optional, off-by-default "and this named check passed at the commit". The check can be the repository's own test
job, or a job that runs `knos-verify`. The platform reads the result from GitHub (a check run on the commit), so it
takes no dependency on Knos. A platform that also wants to show a payment Knos made can check its receipt with the
verifier and show the badge.

## The platforms

Read on 5 October 2026. "Last commit" is the newest commit on the default branch of an anonymous `git clone` made
that day. "Outside pull requests" is what the most recent 80 commits show, not a promise about review. A platform
with no row for source could not be cloned anonymously under the names tried, or publishes no application source
that was found.

### Open source and active

| Platform | Source | License | Stack | Last commit | Outside pull requests | Where "work accepted" is decided | Smallest useful integration |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GitPay | [worknenjoy/gitpay](https://github.com/worknenjoy/gitpay) | [`LICENSE.md`](https://github.com/worknenjoy/gitpay/blob/master/LICENSE.md) is CC BY-NC-ND 4.0; [`CONTRIBUTING.md`](https://github.com/worknenjoy/gitpay/blob/master/CONTRIBUTING.md) says contributions are MIT | TypeScript, Node, Express, Sequelize, React | 2026-10-02 | Invited by the guide; commits by three authors other than the maintainer and dependabot | `src/modules/tasks/taskSolutionFetchData.ts` (five flags, one of them `isPRMerged`) and `src/app/controllers/pull-request.ts` (`verifyPullRequestMerged`) | An optional environment variable naming one check that must have passed at the pull request's head commit |
| MergePay | [codeswithroh/mergepay](https://github.com/codeswithroh/mergepay) | MIT | Solidity, GitHub Actions, TypeScript | 2026-09-30 | None seen; one maintainer. The [guide](https://github.com/codeswithroh/mergepay/blob/main/CONTRIBUTING.md) invites them and asks for an issue before changing the pinned workflows | `.github/workflows/award.yml`: runs when the pull request is merged, then the contract verifies GitHub's token | A second example workflow whose award job needs a `knos-verify` job; nothing pinned changes |
| Superteam Earn | [SuperteamDAO/earn](https://github.com/SuperteamDAO/earn) | AGPL-3.0 | TypeScript, Next.js, Prisma | 2026-10-03 | Merges come from branches of the organisation; the [guide](https://github.com/SuperteamDAO/earn/blob/main/CONTRIBUTING.md) asks for pull requests against `staging` | A sponsor picks winners among submitted links in the sponsor dashboard; no code decides that tests passed | None that is a patch: a submission that links a pull request could show its checks, which is a feature to propose in an issue |
| Drips | [drips-network/app](https://github.com/drips-network/app) | GPL-3.0 | TypeScript, SvelteKit | 2026-10-03 | Not seen; no contribution guide at the root | Not in this repository: its commits refer to a separate Wave service | Not looked into further |
| Polar | [polarsource/polar](https://github.com/polarsource/polar) | Apache-2.0 | Python, TypeScript | 2026-10-03 | The [guide](https://github.com/polarsource/polar/blob/main/CONTRIBUTING.md) requires an assigned issue before any code change | Nowhere now: the server has no module for funding issues | None; it is a billing product today |

<!-- not-active -->
### Open source, not active enough to review a pull request

| Platform | Source | License | Stack | Last commit | Note |
| --- | --- | --- | --- | --- | --- |
| Algora | [algora-io/algora](https://github.com/algora-io/algora) | AGPL-3.0 | Elixir, Phoenix | 2026-07-18 | No pull request merged since #347 on 2026-06-26 (`upstream_check.py`, 7 Oct 2026). A claim is approved and, with autopay, charged at the merge (`lib/algora_web/controllers/webhooks/github_controller.ex`, `pull_request.closed`) |
| bounty.new | [bountydotnew/bounty.new](https://github.com/bountydotnew/bounty.new) | MIT | TypeScript | 2026-05-15 | Its [`RULES.md`](https://github.com/bountydotnew/bounty.new/blob/main/RULES.md) blocks content with wallet addresses and warns on accounts with few merged pull requests. Left alone |
| Ubiquity OS rewards | [ubiquity-os-marketplace/text-conversation-rewards](https://github.com/ubiquity-os-marketplace/text-conversation-rewards) | MIT (in `package.json`) | TypeScript | 2026-04-28 | A plugin that prices a contribution from its conversation; the earlier [UbiquiBot](https://github.com/ubiquity/ubiquibot) says it is deprecated |
| tea | [teaxyz/chai](https://github.com/teaxyz/chai) | MIT | Python | 2026-01-11 | Package data, not a flow where a pull request is accepted and paid |
| sphinx-tribes | [stakwork/sphinx-tribes](https://github.com/stakwork/sphinx-tribes) | ISC (in `package.json`) | Go | 2025-10-22 | Merged outside pull requests in its history |
| Octasol | [Octasol/octasol](https://github.com/Octasol/octasol) | GPL-3.0 | TypeScript, Next.js, Prisma | 2025-04-28 | Solana; one outside pull request in its recent history |
| Allo (Gitcoin) | [allo-protocol/allo-v2](https://github.com/allo-protocol/allo-v2) | AGPL-3.0 | Solidity | 2025-04-08 | Grant allocation contracts, not pull request bounties |
| OpenQ | [OpenQDev/OpenQ-Frontend](https://github.com/OpenQDev/OpenQ-Frontend) | BUSL-1.1 (in `package.json`) | TypeScript | 2024-03-11 | Not read further |
| Gitcoin bounties | [gitcoinco/web](https://github.com/gitcoinco/web) | AGPL-3.0 | Python, Django | 2023-08-01 | Not read further |
| Bountysource | [bountysource/core](https://github.com/bountysource/core) | MIT | Ruby | 2021-08-17 | Not read further |

<!-- /not-active -->
### No public application source found

Opire (its organisation shows one public repository, of guidelines), OnlyDust (the repositories tried could not
be cloned anonymously), IssueHunt, Boss.dev, BountyHub (a public command-line client,
<!-- not-active -->[bountyhub-org/bh](https://github.com/bountyhub-org/bh)<!-- /not-active -->, with no pull request merged since 2026-01-31, and no platform source), Replit Bounties, Dework (public
forks last updated in 2022, no application), Layer3 and Wonderverse. For these the action and the badge still work
from the repository's side, since both need only GitHub.

## The 30-day gate

Knos only contacts, opens anything on, or recommends a repository it does not own if that repository merged a pull
request in the last 30 days. One script decides:

```
python scripts/upstream_check.py --docs docs/reference/INTEGRATIONS.md docs/reference/X402.md --list     # the outside repositories these pages name
python scripts/upstream_check.py --docs docs/reference/INTEGRATIONS.md docs/reference/X402.md            # exit 0 only if every one merged in 30 days
```

It prints, for each repository, the date of its newest merged pull request, and it treats a repository it cannot
read as a refusal. The table "not active enough to review a pull request" sits between
`not-active` markers, so the check skips it (`--marked` includes it). "Last commit" is a commit date from an anonymous clone, not a merged pull request.
The second command was run against GitHub on 7 October 2026: six repositories had merged a pull request in the last
30 days and two had not, algora-io/algora (last #347, 26 June 2026) and bountyhub-org/bh (last #38, 31 January
2026). Both are now marked as not active, and nothing is opened on either. A repository the script refuses later
moves to the marked table the same way, with the date it printed. Every repository on this page is named as
research, not as a recommendation to use it.

## What is not done

Nothing has been proposed to any of these projects, so nothing has been accepted. The action has been run against a
stand-in for GitHub in the tests and not yet in a workflow on GitHub. The verifier's TypeScript file is tested with
Node 22; it has not been run in Deno, Bun or a Worker.
