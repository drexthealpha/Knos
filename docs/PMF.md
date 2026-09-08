# Evidence, and what it is not

Knos has **no retained users**. That is the first line of this file because it
should be, and nothing below is arranged to hide it.

What follows is what does exist, separated into three piles: people who acted,
the size of the problem, and numbers that look like traction and are not. The
third pile is here because leaving it out is how the first two stop being
believable.

## 0. Who this is for, named

**Developers who run more than one coding agent on one repository.** Not
"developers". Somebody with Claude Code in one terminal and Cursor in another,
or an agent running in CI while they work, on a machine where those two have no
way to know about each other. That is a real and countable population - every
one of the pull requests below came from that world - and it is small enough
that a wrong guess about it would show.

The pain, in their words rather than mine, is in the issues quoted in section
2: two agents editing the same file, an agent redoing work another finished, a
decision reversed in one session and still being built on in the next.

What knos asks of them is one line in an MCP config, and what it gives back is
that the second agent is told rather than left to find out. Nobody has kept it
a week yet. That is section 3.

## 1. People who acted

The strongest signal available to a project this young is not a click. It is
somebody with commit rights deciding your work is worth carrying.

### Listed in the MCP directory, by its owner

[punkpeye/awesome-mcp-servers#13480](https://github.com/punkpeye/awesome-mcp-servers/pull/13480)
was merged on 7 Sep 2026 by `punkpeye`, the owner, into the index most people
reach for when they go looking for an MCP server. 94,508 stars.

**What this is:** the one distribution surface this project has, and somebody
who did not have to said yes to it.
**What this is not:** a user. A line in a directory is a door, not a visit.
There is no way to count who walked through it and I am not going to guess.

### Two pull requests merged into third-party repositories

| Repo | PR | Merged | By |
|---|---|---|---|
| [caura-ai/caura](https://github.com/caura-ai/caura) (486 stars) | [#1299](https://github.com/caura-ai/caura/pull/1299) | 5 Sep 2026, 5h16m after opening | `Eldad-Caura`, after `erni-a` approved |
| [drt-hub/drt](https://github.com/drt-hub/drt) | [#1098](https://github.com/drt-hub/drt/pull/1098) | 5 Sep 2026 | `masukai` |

`drt#1098` is the more interesting of the two. It is a behaviour fix with two
regression tests, reviewed line by line, with a change requested and turned
around. The maintainer's words on merging:

> Merged - thanks for the fix, and welcome to your first drt contribution!
> This closes #1096 cleanly.
>
> If you're around, we'd love to have you back for another one.

`author_association` in both repositories is now `CONTRIBUTOR` rather than
`NONE`.

**What this is:** two maintainers reviewed work from a stranger and took it.
**What this is not:** anybody adopting Knos. Neither diff contains Knos. It is
evidence about the builder, not about demand for the product, and it is filed
here rather than in the judge guide's headline for that reason.

### Six more open, in real repositories

[repomix#1837](https://github.com/yamadashy/repomix/pull/1837) (28k stars,
CI green) · [toolport#864](https://github.com/btsouth/toolport/pull/864) (a
regression the reviewer caught and I fixed) ·
[stacktale#231](https://github.com/stacktale/stacktale/pull/231) (a hole the
maintainer found in the guard I wrote, reproduced and closed) ·
[taskuary#35](https://github.com/ldbumble/taskuary/pull/35) ·
[loop-engineering#587](https://github.com/cobusgreyling/loop-engineering/pull/587) ·
[awesome-hermes-agent#382](https://github.com/0xNyk/awesome-hermes-agent/pull/382)

### And the failure that came before them

Thirty-four earlier pull requests asked repositories to adopt Knos by adding
it to a config file. **None merged.** All were withdrawn with an apology on
each thread, because the shape was wrong: a product pitch dressed as a
contribution, with no issue behind it.

That is in this file deliberately. A page that lists nine open and merged pull
requests without mentioning thirty-four failures is a page that has been
arranged.

## 2. The size of the problem

Whether anybody wants *Knos* is unproven. Whether the problem is real is
measured.

**100,057 unique open GitHub issues** were sampled across 97 phrasings and 13
date windows, deduplicated and verified. **1,254 of them - one in eighty -
describe agents colliding on the same work or losing decisions between runs**,
in the words of the person hitting it. Method, classifier and counts:
[`evidence/problem-scale.md`](evidence/problem-scale.md).

The same failure at a frontier lab: during an OpenAI security evaluation
[reported 6 August 2026](https://www.theregister.com/security/2026/08/06/openai-reveals-its-rogue-agent-swarm-went-a-little-bit-borg-ahead-of-hugging-face-hack/5283741),
the models "stepped on each other's toes when one overwrote another's
repository", then coordinated over an unauthenticated board where names could
be forged. That is the argument for binding a hold to a connection rather than
a name, which is what `mcp._is_holder` does.

**And the finding that cuts against us**, from the same study: reading those
1,254 by hand against the question *"would adding Knos close this issue"*, the
answer was **no, in almost every case**. They are feature requests against the
host product's own architecture - "add hooks to our CLI", "put leases on our
Task type". People want their tool fixed, not a new dependency.

That finding is why [`knos.core`](../src/knos/core.py) exists as an importable
library and why the GitHub Action needs nothing installed. It is a real market
signal, it was expensive to learn, and it says the current packaging is wrong
for the demand rather than the demand being absent.

## 3. Numbers that look like traction and are not

- **841 PyPI downloads in the last week** against **1 GitHub star and 0
  watchers.** That ratio is automated: Glama's Docker rebuilds, the MCP
  registry crawler, mirrors, and my own clean-venv checks. A human who installs
  a tool and keeps it usually stars it. This is listed so nobody has to
  discover it themselves.
- **1 ACP job sold, for real USDC, on the real marketplace.** The buyer was my
  own test agent.
- **Four Base mainnet purchases.** All mine.
- Listed on [Glama](https://glama.ai/mcp/servers/drexthealpha/Knos), the MCP
  registry, and [PyPI](https://pypi.org/project/knos/). Presence, not use.

## What would actually count, and does not exist

One person who is not me, running `knos connect` on a repo they care about,
and still having it a week later. Zero of those. Everything above is a
proxy, and proxies are what people show when they do not have the thing.

## Why this file is shaped like this

Every number here survives being checked, and several of them are worse than
the numbers a more careful writer would have chosen. That is the trade: the
ablation table says 12/12 because it is 12/12, the spend figure says 5.41x
because the 10.82x it first printed came from a bug, and this page leads with
"no retained users" because that is the state.

A judge who tests one claim and finds it soft should assume the rest are soft.
Nothing here is soft.
