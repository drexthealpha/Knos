# Decisions and current work

<!-- Written by `knos export`. Commit this file. -->

A second clone reads this on its first question — it is one of the decision
records knos looks for. Nothing here is private: secrets and private paths
never reach it.


## Decisions

- **acp sales** — Sold an ACP job for 0.01 USDC. Asked: what does knos withhold?  _(recorded 2026-09-04)_
- **base mainnet** — Payments run on Base mainnet, eip155:8453, signing from the keystore at ~/.knos-keys/owner. No private key is stored in any config file.  _(recorded 2026-09-03)_
- **worktree identity** — Every worktree of a repo shares one memory, keyed on git rev-parse --git-common-dir rather than --show-toplevel, which returns the worktree root and would fragment a repo's memory once per worktree.  _(recorded 2026-09-03)_
- **action is non-blocking** — The Action never fails a build. action/knos_pr_check.py returns 0 on every path, including when it finds a conflict and when it crashes, so adopting it can never red someone's CI.  _(recorded 2026-09-03)_
- **claim lapse** — Claims lapse after 30 minutes, or on knos done. The lapse is deliberate: a crashed agent must not be able to hold work forever.  _(recorded 2026-09-03)_
- **lexical retrieval** — Retrieval stays lexical. Sibyl searches with SQLite FTS5 and there are no embeddings at any tier, so every answer is a passage someone actually wrote and can be traced to its source.  _(recorded 2026-09-03)_
- **market brief: BTC** — Bought over x402 on Base: https://x402-seller-m8nx.onrender.com/brief?symbol=BTC. Receipt: eyJzdWNjZXNzIjp0cnVlLCJwYXllciI6IjB4ZWNhMzVhMGMwNTg1ZTE5ZWFhOWJmYzVhZjk3NTFkMmNhN2NjNDhjMSIsInRyYW5zYWN0aW9uIjoiMHhhNWIwNWZiYWFmYmIxNjNlODg5OTk2MDViYjZkNGU1YWJh.  _(recorded 2026-09-03)_

## Being worked on right now

_Nothing claimed._

---
<sub>knos export, 2026-09-04 08:20 UTC. Claims lapse after 30 minutes.</sub>

