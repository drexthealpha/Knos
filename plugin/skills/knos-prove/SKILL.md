---
name: knos-prove
description: Ask Knos what is proved about a research claim, or order a proof on NEAR testnet, and get back the claim, the locked test's sha256 and the NEAR receipt as JSON. Use when an agent needs to know whether a paper's result really holds before building on it.
---

# Knos: proved research claims, with their NEAR receipts

Install (one line, from the root of the repository the agent works in):

    curl -fsSL https://raw.githubusercontent.com/drexthealpha/Knos/main/plugin/skills/knos-prove/SKILL.md -o .claude/skills/knos-prove/SKILL.md --create-dirs

## What is proved

    curl -s https://knos.onrender.com/api/near/claims

Each claim with its truth market (`outcome`, the job that proved it, `last_proof`) and what outside backers put behind
it. The four claims and their papers: https://drexthealpha.github.io/Knos/claims/

## Prove a claim (test money, about 25 s)

    curl -s -X POST https://knos.onrender.com/api/near/claim/flow -H "Content-Type: application/json" \
      -d '{"url": "https://arxiv.org/abs/1406.2294", "amount": 3}'

The answer is JSON: `claim`, `test_sha256` (the test NEAR locked before any agent started), `verdict.holds`,
`verdict.agent_a` and `verdict.ai_reviewer` (the private model on NEAR AI Cloud), `paid`, `settled`, and `receipt`
with each NEAR transaction (`fee_url`, `agent_pay_url`). `reused: true` means the last verified proof was returned and
no new run happened. A paper Knos has no claim for answers `look.known: false` with what a person would charge.

## Memory across sessions

Knos's memory for an agent is a file in its own repository, `.knos/memory.jsonl`. Before asking, read it: a claim
already proved in an earlier session has its receipt there. After an answer, append one line:

    {"at": "<UTC time>", "asked": "<paper or question>", "claim": "<claim>", "holds": true, "test_sha256": "...", "job": "...", "receipt": "<fee_url>"}

Nothing is sent anywhere else; the receipt itself is public on NEAR testnet.

## Rules

- Test money on NEAR testnet only; no key, account or wallet is needed.
- Say what the verdict checked and what it did not (`verdict.checked`, `verdict.not_checked`), never more.
