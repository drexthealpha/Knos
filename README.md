# Knos

**AI agent work gets paid only when GitHub's own signature, checked by Solana, proves it passed.**

A maintainer funds an issue with one comment: `/knos bounty 20`. Whoever's pull request is merged for that issue,
and holds up when its claims are checked against GitHub's own record, is paid to their **GitHub account**: no
wallet, no sign-up and no address in the pull request. The money sits in a program on Solana, not with Knos. The
program releases it only on a token GitHub itself signed ("this pull request, by this account, was merged in this
repository"), and it checks GitHub's RSA signature on chain. Nobody can change that program, Knos included: it has
no admin and no upgrade authority.

Try it: [drexthealpha.github.io/Knos](https://drexthealpha.github.io/Knos/). Paste any agent pull request to see
whether its "tests pass" is true; protect a repo in two clicks; fund an issue with one comment. Everything is on
**Solana devnet** and the money is test USDC.

## Why

Coding agents open pull requests by the million, and a pull request's own description is not evidence.

<!-- bench:market -->
**Agent PR Index, 2026-10-02:** in 826 repositories, the first pull request by an AI coding agent whose description said tests or CI pass had **a failing check in 147 (17.8%)** (95% Wilson interval 15.3%–20.5%). Counting every such pull request instead of one per repository, it is 660 of 2,431 (27.2%); that figure leans on a few busy repositories, so the per-repository one is the one to quote. Pull requests created 2026-06-04 – 2026-10-01 whose CI had finished at the head commit; 9,207 on repositories owned by the pull request's author or the person who assigned the agent were left out. A failing check is GitHub's record, not a judgment of why it failed. Published as `index.json` on the Pages site; rebuilt every 6 hours by `.github/workflows/index.yml`.

| agent | repositories | first claiming PR failed CI | 95% interval | all claiming PRs | failed CI |
|---|---|---|---|---|---|
| GitHub Copilot coding agent | 341 | 85 (24.9%) | 20.6%–29.8% | 787 | 194 (24.6%) |
| Devin | 78 | 13 (16.7%) | 10.0%–26.5% | 520 | 270 (51.9%) |
| Claude GitHub app | 182 | 17 (9.3%) | 5.9%–14.4% | 716 | 68 (9.5%) |
| Claude Code | 191 | 17 (8.9%) | 5.6%–13.8% | 206 | 17 (8.2%) |
| OpenAI Codex | 40 | 17 (42.5%) | 28.5%–57.8% | 202 | 111 (54.9%) |
| **all** | **826** | **147 (17.8%)** | **15.3%–20.5%** | 2,431 | 660 (27.2%) |
<!-- /bench:market -->

Coding agents are sold by the seat or the token, whatever comes out. Where a seller can define the outcome, buyers
already pay per outcome; for code they cannot, because an agent grading its own work has the problem in the table
above. But code has what no other agent work has: a neutral party that already signs the outcome. Trade between
strangers was built on exactly that, the letter of credit: the bank pays against a document a third party signed,
never against the seller's word. Knos is that for agent work. The document is GitHub's signature; the bank is a
program nobody controls. ([docs/WHY.md](docs/WHY.md) has the sources and the argument;
[docs/MARKET.md](docs/MARKET.md) says how small the bounty market is today and where the money is.)

## How it works

1. **Protect a repo.** One workflow file ([examples/knos-workflow.yml](examples/knos-workflow.yml)); the site
   prefills it. No secret, wallet or app in the repo. Only want the check, with no money anywhere?
   [examples/knos-check.yml](examples/knos-check.yml) is that alone.
2. **Fund an issue.** A maintainer comments `/knos bounty 20` (or writes that line in a new issue). GitHub signs a
   token that says so; anyone can carry it to Solana, and Knos's public worker does; the escrow opens.
3. **Every pull request for that issue gets a Knos check**, on GitHub, running none of its code: the repo's own
   CONTRIBUTING rules, what the repo's history made required, and whether a "tests pass" in the description is true
   at the head commit.
4. **A maintainer merges the one they want.** The check runs once more at the merged commit: a description that
   says tests pass is paid only if GitHub's record of that commit bears it out. If it holds, GitHub signs the merge, Solana verifies the signature, and an hour later
   the bounty belongs to the author's GitHub account (until then `/knos veto` takes it back, because the pull
   request itself says which issue it closes). A pull request an agent opened under a bot account pays the person
   who ran it. 2.5% fee (at least 0.05 USDC), only when someone is paid.
5. **The author claims it** whenever they like, to any Solana address, with one command: `knos claim <address>`
   (or in the browser). GitHub signs the claim from a repository they own; nobody else can get that signature.

No merge needed? Put acceptance checks in `.knos/acceptance/<issue>/` before funding. They run in a sandbox against
each pull request (Python, Node, Go, Rust, Ruby, any command, or a black-box check that cannot be forged from inside); a
pass is paid after 24 hours unless vetoed. With no proof by the deadline (14 days), the funder gets everything back.

## What is in this repository

| | |
|---|---|
| [`programs/knos_oidc`](programs/knos_oidc) | **OIDC on Solana.** Verifies a GitHub Actions or GitLab CI token (RS256, 2048- and 4096-bit) on chain. Any program can then require a fact GitHub signed. No admin; new issuer keys enter only on GitHub's own signature. |
| [`programs/knos_pay`](programs/knos_pay) | **Pay on proof.** The escrow: funds per issue, pays a GitHub account, refunds on deadline. No admin. |
| [`examples/oidc_gate`](examples/oidc_gate) | A second program built on knos-oidc: it records the last commit GitHub signed for a repository. |
| [`.github/workflows`](.github/workflows) | `fund.yml`, `prove.yml`, `relay.yml`: the reusable workflows a protected repo calls, pinned by commit. |
| [`crates/knos-oidc-interface`](crates/knos-oidc-interface) | What another team's program depends on to read a verified token: a Rust crate with no dependency. [`idl/`](idl) has both programs' IDLs. |
| [`src/knos`](src/knos) | The judge (`knos proof gate`, `knos proof judge`), the relay anyone can run (`knos relay`), `knos claim`, the Stop hook, and `knos mcp`. |
| [`sdk/settle`](sdk/settle) | A JavaScript client with no dependency, checked byte for byte against the Python client; an npm tarball on every release. |
| [`web`](web) | The site. It reads GitHub and Solana in the browser; there is no Knos server. |

## Free, for your own agent

```
pipx install knos        # or: uv tool install knos
knos init                # a Stop hook and an MCP server for your coding agents; undo with: knos init --undo
```

- **The Stop hook** (Claude Code, Codex). When your agent says tests pass, CI is green, it shipped or it is done,
  Knos runs that check itself before the agent may stop, and remembers each repo's past false "done" in
  [Sibyl](https://sibyllabs.org) as a check it now requires. A hook is a local aid and a person can remove it. The
  same check at the merge, on GitHub, is what a repo can require and what a payment depends on.
- **`knos mcp`** (Claude Code, Codex, Cursor, Gemini CLI). A read-only MCP server: the agent can list funded issues
  it could take, check whether a pull request's claims are true, and see what its operator is owed. The agent needs
  no wallet; whoever runs it is paid to their GitHub account.

## What can go wrong, and what it costs

- [docs/SECURITY.md](docs/SECURITY.md): who has to be trusted for what, what a proof proves and what it does not,
  the known limits of this version, and what the mainnet version changes.
- [docs/TAMPER.md](docs/TAMPER.md): 21 cheating pull requests against three judges.
- [docs/BENCH.md](docs/BENCH.md): every measured number, and how to re-run it.
- [docs/MARKET.md](docs/MARKET.md): the market, bottom up, with every assumption labelled; the fee and what a payout costs.
- [docs/COMPARE.md](docs/COMPARE.md): MergePay, GH Bounty, Algora, Octasol and CodeRabbit, from their own code and pages.
- [docs/OIDC.md](docs/OIDC.md): build on knos-oidc.
- `knos mainnet-check` prints every gate that must hold before real money, with its evidence. One fails today on
  purpose: there has been no outside audit. Mainnet stays locked until there is.

## History

Knos 0.1 (1–7 Sep 2026, before this hackathon) was shared memory for coding agents and won the Sibyl Labs hackathon.
0.2 and 0.3.0–0.3.9 (29 Sep – 2 Oct) were built during it and tried coordination, budgets and a jobs market before
the measurement above showed where the real problem was. Since 0.3.10 it is one product; the earlier ones are in
[drexthealpha/knos-labs](https://github.com/drexthealpha/knos-labs). [docs/DISCLOSURE.md](docs/DISCLOSURE.md) says
what was built when, and what came from elsewhere.

MIT, all of it. Built by drexthealpha. Its memory engine is [Sibyl](https://sibyllabs.org).
<!-- mcp-name: io.github.drexthealpha/knos -->
