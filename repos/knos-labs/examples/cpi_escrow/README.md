# An on-chain agent that takes Knos jobs (CPI example)

`src/lib.rs` is a minimal native Solana program. It acts as a worker: it CPIs into the Knos escrow's `claim` (tag 2) and `deliver` (tag 3). Its account metas match [`programs/knos_escrow/idl.json`](../../programs/knos_escrow/idl.json).

- The worker is the PDA `["agent"]` of this program, and it signs both escrow calls with `invoke_signed`.
- The agent's token account must be owned by that PDA and hold the escrow mint. `claim` takes the stake from it, which is 10% of the price and at least 0.1 USDC. `deliver` pays the stake back into it.

| tag | instruction | accounts | data |
|---|---|---|---|
| 0 | TakeJob | agent, job (w), agent_token (w), vault_token (w), config2, token_program, escrow_program | none |
| 1 | DeliverJob | agent, job (w), agent_token (w), vault_token (w), vault_authority, token_program, escrow_program | result_hash[32] |

`config2` is the escrow PDA `["config2"]`. `vault_authority` is `["vault"]`. The job is `["job", id]`. The program checks that the job account is owned by the escrow program it is asked to call.

To check that it compiles:

```
cd examples/cpi_escrow && cargo check
```
