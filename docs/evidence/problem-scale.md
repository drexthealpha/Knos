# How common is the problem, measured

Knos has no users. That is stated plainly in the judge guide and is not
softened here. What *can* be measured is whether the problem it addresses is
real, and how often people write it down.

This is that measurement. Method first, so the number can be argued with.

## Method

GitHub's search API returns at most 1,000 results for any one query, so scale
comes from asking many narrow questions rather than one broad one:
**97 distinct phrasings x 13 date windows**, deduplicated by issue URL.

The phrasings cover the four shapes of the complaint:

- agents colliding: `"two agents" "same file"`, `"agents overwrite"`,
  `"overwrote my changes" agent`, `"agent collision"`, `"lock" "two agents"`
- memory lost between runs: `"loses context" agent`,
  `"remember between sessions"`, `"re-explain" agent context`
- work redone: `"duplicate work" agents`, `"same work twice" agent`
- the decisions record: `"AGENTS.md" decisions`, `"CLAUDE.md" decisions`,
  `"why did we" agent context`

**Sample: 100,057 unique open issues.** Verified deduplicated - 100,057 lines,
100,057 distinct URLs, 0 duplicates, 0 malformed.

## Classification

A keyword match is not a fit, and the first attempt proved it: filtering on
the word "agent" called 8.5% of the sample relevant, and reading the output
showed LDAP agents, Consul agents, Datadog agents, support-desk agents and a
flood of arXiv multi-agent path-finding papers. "Agent" is one of the most
overloaded words in software.

The classifier that produced the numbers below requires all three:

1. a **coding** agent is named or explicitly described - Claude Code, Cursor,
   Copilot, Aider, Codex, Devin, Cline, OpenCode, Windsurf, or the phrase
   "AI/coding/LLM agent", or MCP;
2. none of the other senses of the word is what is meant;
3. the complaint is one of the two Knos answers.

## Results

| | Count | Share |
|---|---|---|
| Issues sampled | 100,057 | |
| **A** - two or more agents colliding on the same work | **440** | 0.44% |
| **B** - an agent losing decisions between runs | **814** | 0.81% |
| **A + B** | **1,254** | **1.25%** |
| Noise (the words appear, no coding agent involved) | 98,803 | 98.7% |

## What this does and does not show

**It shows** that roughly one in eighty open issues in this corpus is somebody
writing down the exact failure Knos exists for, in their own words, unprompted.
The problem is not hypothetical.

**It does not show** demand for Knos. A separate pass read the 1,254 by hand
against a stricter question - *would adding Knos close this issue, such that
removing it reopens it?* - and the answer was **no, in every case**. Issues
describing this pain are almost always feature requests against the host
product's own architecture: "add lifecycle hooks to our CLI", "put leases on
our Task type", "replay our transcript into the new sandbox". The person
filing wants their tool fixed, not a new dependency.

That is a finding about the market, and it is the reason this file exists
rather than a page of adoption claims: the pain is real and measured, and the
demand does not currently express itself as "I will install a shared-memory
MCP server". It expresses itself as "my agent tool should do this natively" -
which is why `knos.core` exists as an importable library and why the GitHub
Action needs nothing installed at all.

## Corroboration outside the sample

The same failure at a frontier lab, five weeks before this was written. During
an OpenAI security evaluation, [reported by The Register on 6 August
2026](https://www.theregister.com/security/2026/08/06/openai-reveals-its-rogue-agent-swarm-went-a-little-bit-borg-ahead-of-hugging-face-hack/5283741),
the models "stepped on each other's toes when one overwrote another's
repository". They then coordinated through an unauthenticated shared board and
reasoned that names on it could be forged.

That is the case for binding a claim to the connection rather than to the name
an agent gives itself, which is what `mcp._is_holder` does and what
`tests/test_core.py` pins.
