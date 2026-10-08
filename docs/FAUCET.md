# Test USDC for your first task

Test USDC is devnet money. It has no monetary value, and it never will.

## The path, start to end

1. **Get test USDC.** Comment on the faucet issue of the playground
   ([find it](https://github.com/drexthealpha/knos-playground/issues?q=is%3Aissue+is%3Aopen+label%3Afaucet)):

   ```
   /knos faucet <your Solana address>
   ```

   The Buy page of the site shows the address of your passkey wallet; `knos faucet request <address>` prints the same
   line. `/knos faucet passkey` sends to the address your account bound with `/knos address`. The reply names the
   transaction. It gives 20 test USDC.
2. **Install the workflow in YOUR repository.** One pull request: the Install page builds the link, or follow
   [INSTALL.md](INSTALL.md).
3. **Fund a task.** On an issue of your repository, comment `/knos fund 5`. With a passkey wallet, sign the order on
   the Buy page instead: the money then comes from your wallet, and the relay pays the transaction fee.
4. **A merged pull request is paid.** The pull request that closes the issue is paid when it merges and its checks
   pass. Nobody delivers by the deadline: the money goes back to where it came from.

## The rules of the faucet

| rule | value |
|---|---|
| amount | 20 test USDC, one fixed amount |
| per account | once per forge account in 7 days |
| per address | once per receiving address in 7 days |
| daily cap | 200 test USDC in one UTC day, for everyone together |
| who may ask | a person's account (not a bot, not an organisation), at least 30 days old, with at least one public repository or gist |
| where | only the issue labelled `faucet` in `drexthealpha/knos-playground` |

The last-but-one row is the anti-drain rule. It reads one public answer, `GET /users/{login}` (the fields `type`,
`created_at`, `public_repos`, `public_gists`), which costs one unauthenticated request. It does not stop a patient
person with several old accounts; the daily cap bounds what that person can take to 200 test USDC a day, of money
with no monetary value.

The daily cap follows the source. Circle's devnet faucet gives 20 USDC every 2 hours per address
([faucet.circle.com](https://faucet.circle.com/)), so one faucet key can be filled with at most 240 a day.

## A retry never sends twice

Every grant is a row in a journal, kept in the Sibyl store and carried in the faucet's own replies on the issue (a
runner keeps no disk between runs). The row is written before anything is signed. The transfer's signature is written
to the row, and to the reply, before the transfer is sent. A later run that finds a row in flight asks the cluster
about that one signature. It signs a new transfer only when the first failed or its last valid block height has
passed, when the first can never land. `tests/test_faucet.py` holds each of these cases.

Two runs at once send once. The worker runs one faucet job at a time (its concurrency group, `knos-faucet`). Should
two overlap all the same, the signature posted first is the lock: each run posts its reply with the signature, then
reads the issue again, and a run that finds an earlier reply of the faucet's own for the same account or address
sends nothing and takes its row back. When that second read fails, nothing is sent.

## The faucet key (setup for the release run)

The faucet key holds test USDC and nothing else: no SOL, no authority over any program, no fee income. It is never the
fee payer, the fee owner or the guardian; the code refuses to start when it is. The relay's key pays each transfer's
fee and the rent of a new receiving account (about 0.002 SOL each, so at most about 0.02 SOL a day at the cap).

1. Make the key: `solana-keygen new --no-bip39-passphrase -o faucet.json`. Send it no SOL.
2. Make its token account, paid by the relay's key:
   `spl-token create-account 4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU --owner <faucet address> --fee-payer relay.json --url devnet`.
   The mint is Circle's devnet USDC, the one mint Knos calls test USDC besides the program's own.
3. Fill it: ask [faucet.circle.com](https://faucet.circle.com/) for USDC on Solana Devnet to the faucet address
   (20 every 2 hours), or send devnet USDC from a wallet that holds some.
4. Store the key as the secret `KNOS_FAUCET_KEY` of the repository that runs the worker, readable by the faucet job
   only. Delete `faucet.json`.
5. In `drexthealpha/knos-playground`, open one issue titled "Faucet: test USDC for your first task", label it
   `faucet`, and pin it. Its text is step 1 above and the table of rules.
6. Rebuild the playground: `python scripts/small_repos.py build knos-playground DIR` writes
   `.github/workflows/knos-faucet.yml` there, so a rebuild keeps it. That file is the worker's `faucet` job alone
   ([`worker.yml`](../.github/workflows/worker.yml), byte for byte; a test compares): it runs on `issue_comment` in
   the playground and nowhere else (the variable `KNOS_FAUCET_REPO` names another repository; `KNOS_FAUCET_REF` the
   commit of Knos whose code it runs, `main` when unset), with the secrets `KNOS_FAUCET_KEY` and `KNOS_RELAY_KEY`. It
   runs `python -m knos.faucet --event "$GITHUB_EVENT_PATH"`, and without either secret it says so and ends green. The
   repository's own Knos workflow says nothing to a faucet request on that issue, so there is one reply. No relay job
   runs in the playground: the faucet workflow holds none.
7. Check with a comment from an account that is not Knos's own, then `knos faucet status`.

Until step 6 is done the faucet answers nobody. The 0.3.19 release set it up in the playground with a key of its own; it has
given nothing yet, because that key's account holds no test USDC (step 3 is still to do).

## How a faucet-funded task is counted

An account that funds a task in its own repository with faucet tokens is an outside funder, and the count labels it
"faucet tokens". An account of Knos's own never is, whatever funds it. A task funded from the program's free devnet
mint, which `/knos fund` draws on when the repository's owner has opened no Balance, is test activity and not an
outside funder: nothing left a wallet the account controls.
