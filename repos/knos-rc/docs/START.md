<img src="../web/brand/mark.svg" height="40" alt="Knos">

# Start here: Knos in five minutes

**In plain words.** First, check a pull request in your browser to see if its tests really passed. Then put test money on a task with one comment, and the worker is paid when the work is merged. Last, add Knos to your coding agent with one command.

```mermaid
flowchart TB
    check["1. Check a pull request in your browser"]
    fund["2. Put test money on a task with one comment"]
    paid["3. The work is merged and the worker is paid"]
    install["4. Add Knos to your coding agent"]
    check --> fund --> paid --> install
```
*Four steps. Only steps 2 and 3 move money, and it is test money.*

Everything here runs on [devnet](WORDS.md#devnet), Solana's practice network.

The money is [test USDC](WORDS.md#test-usdc), which is worth nothing. No step needs a sign-up.

## 1. Check a pull request

Open [the check](https://drexthealpha.github.io/Knos/check/) in your browser.

Paste the link to an AI agent's [pull request](WORDS.md#pull-request), such as
`github.com/owner/repo/pull/123`, and press **Check**.

It reads what the pull request says, and the checks GitHub ran on its last commit. **It tells you if a test,
build, lint or type check failed, even when the pull request says the tests pass.**

It asks GitHub only. Nothing is sent to Knos, and it is free.

From a terminal, the same check is one command:

```bash
uvx knos check owner/repo#123
```

## 2. Fund a task with one comment

First, once per repository, add the Knos workflow file with one pull request.

Open [Install with one pull request](https://drexthealpha.github.io/Knos/#install) on the site, type your
repository, and commit the file GitHub fills in. Then merge that pull request.

Now comment on an issue:

```text
/knos fund 20 checks: test
```

That puts 20 test USDC on the issue. The work is paid only if the check named `test` passes.

On devnet a faucet hands out the test USDC, so you need no wallet. Knos replies with the terms it fixed.

`/knos help` lists every command. [What Knos costs](PRICING.md) gives the fee.

## 3. Get paid

Do the work and open a pull request whose description says `Fixes #<issue>`.

Then say where to be paid, in a comment on your pull request:

```text
/knos address <your Solana address>
```

When your pull request is merged and its checks passed, a [program](WORDS.md#program) on Solana pays you.

From merge to payment took 28 seconds at the median, over 56 payments, measured 10 Oct 2026.

No wallet? The site's [Get paid](https://drexthealpha.github.io/Knos/#claim) section makes one from a
[passkey](WORDS.md#passkey). Without an address the money waits for you, 180 days at most.

## 4. Add Knos to your coding agent

Install the command, then let it set up every agent it finds:

```bash
pip install knos && knos init
```

It adds a Stop hook: before your agent may say "done", Knos checks that the tests really passed.

It also adds the MCP server, the tools an agent uses to find paid tasks and check pull requests.

It finds Claude Code, Codex, Cursor and Gemini CLI. `knos init --undo` takes it all out again.

Other agents and editors, one line each, are in [the install guide](reference/INSTALL.md).

## Where next

- [What Knos costs](PRICING.md): the check is free; a fee only when money moves.
- [Trust](TRUST.md): who holds the keys, and what is tested.
- [The story](STORY.md): one task in seven steps, each with its proof.
- [Check every claim yourself](JUDGES.md): each claim, one click from its source.
- [Words](WORDS.md): pull request, devnet, multisig and more, in plain words.
