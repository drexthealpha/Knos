# knos-pay-interface

Fund, top up, refund and read a Knos work order from another Solana program.

`knos_pay` holds a work order's money in escrow and pays it when GitHub signs that the order's terms were met; the
signature is checked on chain by `knos-oidc`. This crate is what a program needs to be the FUNDER of an order by
CPI: a DAO treasury that pays for a merged change, a grants program, a vault. It holds the program ids, the
addresses, the three instructions a funder sends and a reader of the Order account. Its only dependency is
`solana-program`; it carries none of `knos_pay`'s code.

```toml
knos-pay-interface = { git = "https://github.com/drexthealpha/Knos", tag = "v0.3.26" }
```

```rust
use knos_pay_interface as knos;
use solana_program::program::invoke_signed;

// accounts, in this order: treasury (a PDA of this program, a plain system account that holds SOL), the order, its
// token account, the treasury's token account, the mint, knos_pay's ["auth"], the token program, the system
// program, knos_pay's ["pause"]; and the knos_pay program itself somewhere in the transaction.
let f = knos::FundOrder {
    repo_id, issue, amount,                                   // which issue of which repository, and what its payees receive
    wf_repo: knos::wf_repo_hash("drexthealpha/Knos"), wf_sha, // the workflows whose signed run can pay it, pinned by commit
    ..Default::default()                                      // merge mode, 14 days of work, no options
};
let ix = knos::fund_order_wallet(&knos::ID, treasury.key, treasury_token.key, mint.key, token_program.key, &f, terms_json);
invoke_signed(&ix, &[treasury.clone(), order.clone(), ov.clone(), treasury_token.clone(), mint.clone(), auth.clone(),
                     token_program.clone(), system.clone(), pause.clone()], &[&[b"treasury", &[bump]]])?;
let o = knos::Order::read(order.key, order.owner, &order.try_borrow_data()?, &knos::ID).ok_or(ProgramError::InvalidAccountData)?;
if o.amount != amount || o.refund_to != *treasury.key { return Err(ProgramError::InvalidAccountData); }
```

The treasury is debited `amount + order_fee(amount, FEE_BPS, decimals)`: the payees receive the amount whole and the
funder pays the fee on top (knos_pay 2.2: 0.30% of the amount, at least 0.05, no maximum; a program still at 2.1
charges its own older fee, and the order's account holds what was charged). The order is at
`f.address(&knos::ID, treasury.key)` and its money at `knos::ov(&knos::ID, &order)`.

## What is in it

| | |
|---|---|
| ids | `ID` (knos_pay, the second deployment, devnet), `FEE_OWNER`, `TOKEN`, `TOKEN_2022`, `ATA_PROGRAM`, `USDC_DEVNET`, `USDC_MAINNET` |
| addresses | `scope`, `private_scope`, `order`, `ov`, `auth`, `pause`, `ata` |
| instructions | `fund_order_wallet` (15), `top_up` (23), `refund_order` (22) |
| reading | `Order::read` (on chain: checks the owner and that the address is the one the fields derive), `Order::parse` (off chain), `Order::refundable` |
| money | `order_fee`, `units`, the bounds (`ORDER_MIN_AMOUNT`, `MAX_AMOUNT`, `MIN_WORK`, `MAX_WORK`, `MAX_TERMS`) |

Every function takes the program's id, so a deployment on another cluster is another argument, not another crate.

## What your program must know

1. **The funder is the signer of `fund_order_wallet`.** Only it can top the order up, and a refund goes only to a
   token account it owns. A PDA funder must be a plain system account with no data: it pays the rent of the order
   and of the order's token account (about 0.0065 SOL together at today's rent: examples/cpi_fund's test measures it), and gets both back when the order
   closes.
2. **A refund needs nobody's permission.** After the deadline (`now + work_s` at funding) anyone may send
   `refund_order`; everything the order holds, the fee included, returns to the funder. Nothing your program does
   can lose it and nothing Knos does can keep it.
3. **Payment is not your program's call.** The order is paid when a judge's GitHub-signed token arrives
   (`PayOrder`, which any relayer sends). To act on the outcome, read the order: while it exists it is open, held
   or under warranty; once paid out or refunded the account is gone, and the `knos3:paid` and `knos3:settled` log
   lines say who received what.
4. **The terms are a JSON document of at most 600 printable ASCII bytes**, hashed into the order and logged. A
   pay token must carry the same hash, so the terms cannot change after funding.
5. **Bounds.** The amount is 5 to 500 whole units of the mint, the work time 60 seconds to 90 days. A Token-2022
   mint passes only with extensions that change nothing about who holds how much.

## How it is checked

`scripts/pay_interface_fixture.py` writes `tests/fixtures/pay_interface.json` from the Python client
(`src/knos/settle/v2/pay.py`): every address, every instruction for fixed inputs, and one Order account as the test
build of `knos_pay` wrote it in LiteSVM. `cargo test` rebuilds all of it with this crate and compares bytes;
`tests/test_pay_interface.py` fails when the committed fixture is not what the script writes now.
A whole program built on this crate, with its test: [`examples/cpi_fund`](https://github.com/drexthealpha/Knos/tree/main/examples/cpi_fund).

MIT.
