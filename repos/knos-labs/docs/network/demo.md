# A recorded run on Solana devnet

Two machines (two homes, two clones of one repo) and two vendors' agents, on devnet, with no server. Recorded
2026-09-30 15:10 UTC to 2026-09-30 15:12 UTC by the maintainer's script (throwaway homes, devnet test keys). Every transaction
that touched the team's credential is linked below.

- **Team:** `knos-ca29f8d10cccc0b2`, credential
  [`Ah6tvRgh1u2e5CvUJqJHHHLC51TYVcv9qDGn9X76cx7X`](https://explorer.solana.com/address/Ah6tvRgh1u2e5CvUJqJHHHLC51TYVcv9qDGn9X76cx7X?cluster=devnet).
  Created in 51.9 s: the credential, four schemas, the owner's member record and its key float.
- **Bob joined:** his `knos init` printed a join code with fingerprint `focus-garlic-nutmeg-frost-blade-dance`. The owner ran
  `knos team add`: added · funded key · sealed team secret on chain.
- **Alice's Claude Code edited `src/billing/tax.py`:** its PreToolUse hook placed a claim on chain and allowed the
  edit (exit 0, 12.1 s including a cold Python start).
- **Bob's Codex, on the other machine, sent an `apply_patch` to the same file:** refused (exit
  2, 5.5 s):

  ```
  src/billing/tax.py is claimed by alice/claude-code since 16:11 (Knos). Ask them, or take other work.
  ```

- **Bob then wrote the file with a raw shell command and tried to commit:** git's pre-commit hook stopped it
  (exit 1).
- **Alice released her claim:** closed compare-then-close, with the rent back to her key. Bob's patch then went
  through (exit 0).

Nothing in the transactions is plaintext: the file is a salted hash, the names are sealed.

| # | slot | transaction | result |
|---|---|---|---|
| 1 | slot 505945317 | [58kssszrkQ1FKA86y9nW…](https://explorer.solana.com/tx/58kssszrkQ1FKA86y9nWT2yHjSgKAUdDmjPtKSCQ1ogLSMFp7tiR8Er8h8HWgdWmZ9uWww9RsNy8H5FHBFHS5hk1?cluster=devnet) | ok |
| 2 | slot 505945341 | [5XukXPp9TxDW5MyiviBu…](https://explorer.solana.com/tx/5XukXPp9TxDW5MyiviBu9vCmH21rFoJmnmL1dMQELxBc7JZAj6Vh7kxNHdZYCzXNHM52qm3tSRU94a74Ww52hLCD?cluster=devnet) | ok |
| 3 | slot 505945353 | [45f91xa6D66yrsCQjeGt…](https://explorer.solana.com/tx/45f91xa6D66yrsCQjeGtFXXVY1R2AteAZqJRtJM1DDRscqwPyht9vikkUcNqGp8BT93A3Nt5c4PoqM7ZVPcm8wFK?cluster=devnet) | ok |
| 4 | slot 505945390 | [VaAqdmwGLXydMEtiutcv…](https://explorer.solana.com/tx/VaAqdmwGLXydMEtiutcvrqr1Dp6rxxMDpqRbqCzxaNj7nZkRZmP2wMWk7vZfVeWSf9UfCxdGfkY8x96N78nJ6oL?cluster=devnet) | ok |
| 5 | slot 505945429 | [2GpDrMvNFiYfsSug82TX…](https://explorer.solana.com/tx/2GpDrMvNFiYfsSug82TXvKwLhRcxh2KeehAuHAy8cL84uRCLWt6wfZUMEqA8aK6iqiE1NpM6RyNuCoWqWFyJ9Js8?cluster=devnet) | ok |
| 6 | slot 505945476 | [UTwLuur3T8AqYTp5QxxX…](https://explorer.solana.com/tx/UTwLuur3T8AqYTp5QxxXcBbUhDpNJHwUy26NZFcDY6xYWoYaWWNDw2LU3EdfGJiC6fvKM9G1kdC6DpuxczWAFTS?cluster=devnet) | ok |
| 7 | slot 505945512 | [2RQwM12BSJwRQ5qxBUMi…](https://explorer.solana.com/tx/2RQwM12BSJwRQ5qxBUMirXxVLKSVhsmw3zD3qRtm3pgsxw1Gqa7oPFp8gwBJHeFR45sgkXEjNCjpbtZmg42pfe1J?cluster=devnet) | ok |
| 8 | slot 505945604 | [3DmTzNLbEFEHcLgEgnyw…](https://explorer.solana.com/tx/3DmTzNLbEFEHcLgEgnywbdyr7h9vUC3amj6JaE3VUMfcGmAVvx5i1EZ9TJmCbUShykayBwKP1aGjsNEcVUQX1u45?cluster=devnet) | ok |
| 9 | slot 505945644 | [r5pCjwx6vRj2GLGGT1u4…](https://explorer.solana.com/tx/r5pCjwx6vRj2GLGGT1u4jKECCMBNB825EHcbPnLaurk9suLEF6Ug94LAkVjtw6yJjDQYaaESa2eWj7xV6CwpzF5?cluster=devnet) | ok |

Re-run the claim protocol yourself on a local validator: `bash scripts/devchain.sh start && pytest
tests/test_team_two_homes.py`.
