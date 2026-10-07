## Summary
The issue requests adding a log entry for each token the always-on worker relayed. In `src/knos/proof/ghrelay.py`, the `_on_relayed_token` method already records tokens to `RelayStats`, but doesn't produce a one-line-per-token log entry suitable for relay log output. 

This change adds structured logging via the existing `logger` instance so each relayed token produces one clear log line containing the token account address and the transaction signature. The `RelayStats.record()` call is preserved, and the new log line follows the format:

```
Relayed token <token_account> sig=<signature>
```

This satisfies the requirement of "one line per token the always-on worker relayed" as stated in the issue.

Closes #17
/attempt
/claim #17

Closes #17

/opire try
/claim #17

Bounty Reward Wallet: 0x00000000000000000000000000000000000000Aa (Base / EVM)