# Access.sol

Who may read which of your folders. One record, so neither person has to
trust the other's copy of it.

The permission itself is OpenZeppelin's `AccessControl`. This contract only
names the roles: one per owner and path, so sharing `./src` says nothing
about anyone else's `./src`, and a stranger can neither hand out nor take
back your readers.

No Merkle roots, no sub accounts, no spend permissions, no join flow.

## Build and test

```bash
forge install OpenZeppelin/openzeppelin-contracts --no-git
forge test
```

9 tests, including a fuzz run over arbitrary readers.

## Live

Base Sepolia, `0x955fa320D60D9172CF048141ed7eEE442da66E52`
([deploy](https://sepolia.basescan.org/tx/0xdcc25ff7460a09a080ec32016b39121b6a34b741f03411bcfdc2ee2a93b31d21)).

Grant and revoke, run against that deployment:

| | |
|---|---|
| [grant](https://sepolia.basescan.org/tx/0x84e11e21315b51e9e6b6453d226a44bcabf5a80f4c0085ba6f5b56ed169a92b6) | `0x84e11e21…` |
| [revoke](https://sepolia.basescan.org/tx/0xb3ea6920c0a7bf7fa9dde64e6f0c2275e149f976bf20c909098a2431417adfb4) | `0xb3ea6920…` |

Between those two, a teammate's agent asking about the shared folder got
answers out of `crates/`. After the second, the same question returned
`Nothing shared with you.`

Testnet only. Nothing here costs anything.
