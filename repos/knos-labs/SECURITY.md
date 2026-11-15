# Security

## Reporting a vulnerability

Please report security issues privately, through GitHub's "Report a vulnerability" on this repository (Security →
Advisories), not in a public issue. Expect a reply within a few days.

## What Knos touches

- **Reads:** your repo, your coding agents' local transcripts (Claude Code, Codex, Cursor), and their spend logs.
- **Writes:** only under `~/.knos`, plus the agent configuration files `knos init` edits. It backs each one up
  first, and `knos init --undo` restores it.
- **Never sent to your agents:** secrets (`.env`, keys, certificates, `.ssh`, `.aws`, and paths added with
  `knos private`).
- **Network:** for coding agents, answering, claiming and guarding never use it unless the repo is in a team (then
  one Solana RPC). Jobs use a Solana or Tempo RPC and the relay that holds briefs and sealed deliveries. Knos Pro
  commands make public RPC reads to check payments, and send payments that you or an agent's wallet sign.
- **Agent wallet keys:** kept in `~/.knos/wallets`, owner-only, never printed or logged. An agent wallet should hold
  only what you are willing for that agent to spend.

## Jobs (escrow) — what protects whom

- **Non-custodial.** Job money is in a program-owned vault (Solana, `GwmbMFvy…RPq` on devnet) or the escrow contract
  (Tempo). Knos holds no key that can move it. The fee account and fee (5%) are fixed when the escrow is initialised.
- **Refused by the program, tested:** a second claim, delivery by anyone but the worker, accept or reject by anyone but
  the buyer, release before the review window ends, double settlement, reposting an id, a foreign vault, dust amounts.
  Solana: `tests/test_escrow_sol.py` (11 attacks, 1,000-step conservation fuzz). Tempo: `contracts/test` (Foundry,
  1,000-run fuzz) and `tests/test_jobs_tempo.py`.
- **Mainnet is locked** (`KNOS_ALLOW_MAINNET=1` to unlock) and capped at 500 USDC per job until an external audit; on
  Tempo the cap is in the contract, and its guardian can only lower it or pause new posts, never touch funds.
- **Privacy.** Briefs, deliverables and buyer memory never go on chain, only their hashes. Deliverables are sealed to
  the buyer (PyNaCl sealed boxes), so a relay cannot read them, and every read is checked against the hash on chain,
  so a relay cannot swap them. Buyer preferences stay on the buyer's machine and go into a brief only with
  `--share-memory`, after the CLI shows them; a brief is readable by anyone with the relay.
- **Actions/Blinks.** The server builds unsigned transactions; only the wallet signs. A test checks every transaction
  asks for exactly one signature, the connected wallet's, and the program checks who may accept.
- **Not audited.** The escrow program and contract have had no external audit yet.
