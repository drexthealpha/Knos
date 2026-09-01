# Registering the offering

> **Status: registered, provider running.** Agent
> `01a05b97-a776-760a-9165-e9893e4091dc`, wallet `0xd535a882…e0de`, page
> https://app.virtuals.io/acp/agents/01a05b97-a776-760a-9165-e9893e4091dc
>
> `npm run register` starts the provider and prints
> `knos is answering questions at 0.01 USDC each.` The steps below are the
> record of how it was set up. Nothing has bought an answer yet.

One offering, registered once, in a browser. Nothing here can be done from
code: the service registry is a web form.

Runs on Base mainnet, which is what Virtuals recommends for the SDK. Every
other part of knos stays on Base Sepolia and stays free.

## 1. Register the agent

Open <https://app.virtuals.io/acp/new> and enter:

| Field | Value |
|---|---|
| Name | knos |
| Description | One memory for every coding agent on a developer's machine. Ask it what a past session decided, who changed a file and why, or how the code is put together. Every answer names its source. |
| Role | Provider |
| Chain | Base |

## 2. Add the offering

On the agent's page, add **one** offering:

| Field | Value |
|---|---|
| Name | Answer a question from my memory |
| Description | Ask a question about the repository this agent has read. The reply is the passage that answers it and where it came from: a file and line, a session and date, or a commit. |
| Price | 0.01 USDC |
| Input | `question` (string, required) — what you want to know |
| Output | The passage, and its source |

## 3. Collect three things

- **Signers** tab → **+ Add Signer** → **Copy Key**. That is `signerPrivateKey`.
- The same tab shows `walletId`.
- **Settings** tab shows `builderCode` (`bc-...`). Optional, but it attributes
  the transactions on base.dev, so take it.

## 4. Write them down, outside the repo

`~/.knos-keys/acp.json`

```json
{
  "walletAddress": "0x... the agent's wallet, from its page",
  "walletId": "...",
  "signerPrivateKey": "...",
  "builderCode": "bc-...",
  "knos": "the full path to your knos executable"
}
```

That folder is outside the repository and is not in git.

## 5. Fund it

The agent's wallet needs about **$1 of USDC on Base mainnet** — a hundred
questions at a penny each. Its address is on the agent's page, from step 1.

## 6. Answer jobs

```bash
cd agent
npm install
npm run register
```

It prints `knos is answering questions at 0.01 USDC each.` and waits. It only
ever acts on a job somebody created; it does nothing on its own, and closing
it stops it.
