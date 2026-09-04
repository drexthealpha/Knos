# Running the proofs yourself

Two scripts. Neither needs an editor, a GUI, or an API key, and both exit
non-zero if the thing they describe does not happen.

## `withhold.py` — the claim gate, in two real processes

```bash
python scripts/withhold.py
```

Starts a separate OS process for each agent, against one store on disk:

1. agent A claims `the parser`
2. agent B asks about it and is **refused** — it gets the holder's name, not
   the answer
3. agent B tries to claim it too and is refused again: one claim, one holder
4. agent A releases it
5. agent B asks again and the answer comes back
6. `knos export` writes `.knos/decisions.md`, the file a repo commits

Nothing is mocked. Two processes and one SQLite file is the only arrangement
that proves anything about two agents on one machine.

## `gate.py` — delete the store, watch it break

```bash
python scripts/gate.py
```

Writes a fact, claims a topic, counts what could be sold, deletes the SQLite
file, and asserts that both are gone:

- **the withhold path** — no claim can be held or read, so nobody is refused
- **the paid path** — the deliverable an ACP job or an x402 request would
  have sold came out of that file, so there is nothing to sell

What survives is commits and files, because those were never Knos's. Refill
with `knos point`.

This is the honest version of "the memory is load-bearing": not a claim in a
README, a script that breaks the product on purpose and fails if it does not.

## The whole loop end to end

```bash
python scripts/withhold.py                  # 1. claim, withhold, release, export
npm --prefix agent run bot                  # 2. one process: ACP + x402 + chat
#   then in Telegram or the console:
#     /brief BTC                            # 3. pays 0.01 USDC on Base, keeps the brief
npm --prefix agent run buy -- "a question"  # 4. an ACP job, answered from knos, settles
#     /jobs                                 #    the sale, read back out of knos
python scripts/gate.py                      # 5. delete the store; 1, 3 and 4 all die
knos point                                  # put it back
```

Step 2 prints `Telegram: polling.` straight away and `ACP: answering jobs.`
a minute or two later — the chat half never waits for the marketplace. Step 4
is a real job against the provider running inside that same process: the
deliverable is whatever `knos ask` returns, and the money settles on Base.

Steps 3 and 4 need real credentials in `~/.knos-keys/`. Without them each
says which one is missing rather than pretending.

## What the agent adds

`agent/bot.ts` is one process that is three things at once, all against the
same store:

| | What it does | Where the memory comes in |
|---|---|---|
| ACP provider | answers paid jobs from the Virtuals marketplace | the deliverable is read out of Knos |
| Telegram, or the console | `/ask`, `/brief`, `/status` | `/ask` reads Knos; work another agent claimed is withheld here too, the bot gets no special access |
| x402 payer | `/brief` buys something on Base | what it bought is written back with `knos remember`, so the next agent gets it free |

### Running it

```bash
npm --prefix agent run bot -- /status     # one command, printed, then exit
npm --prefix agent run bot                # stays up: ACP + Telegram, or the console
```

On Git Bash or MSYS, prefix the one-shot form with `MSYS_NO_PATHCONV=1`, or
write `//status`. Without it the shell rewrites `/status` into a Windows path
before Node sees it, the command matches nothing, and you get silence rather
than an error. PowerShell and Linux shells need neither.

With no `telegramToken` it reads commands from the console instead, which is
how you exercise the whole thing without a Telegram account. The ACP half
starts in the background and reports when it is up — it takes a few minutes
to connect, and the chat half answers immediately either way.

### `~/.knos-keys/bot.json`

Not in this repository, and it should never be. Every key:

| Key | What it is |
|---|---|
| `telegramToken` | from @BotFather. Leave empty to use the console instead. |
| (no private key) | payments sign with the keystore at `~/.knos-keys/owner`, so no key is stored in this file. |
| `payNetwork` | `eip155:8453`, Base mainnet. |
| `paidEndpoint` | what `/brief` buys from. Defaults to the merchant below. |
| `python` | the interpreter that has knos installed. |
| `knos` | the full path to your knos executable. |

### Where `/brief` buys from

The endpoint in `paidEndpoint`, an x402 seller on **Base mainnet**: ask it
without paying and it answers `402 Payment Required` with
`network: eip155:8453`. The payment is real USDC on mainnet, not testnet
credit, and it settles on chain with a transaction hash the receipt keeps.
Point `paidEndpoint` somewhere else and the bot buys there instead.

The payment itself is [`src/knos/buy402.py`](../src/knos/buy402.py), the
official x402 client. The bot shells out to it exactly as the ACP provider
shells out to `knos ask`. It is Python because the Node client still speaks
x402 v1 and the merchants speak v2.

Whatever comes back is written into Knos with `knos remember`, receipt and
all — so the point of paying is that nobody on this machine pays twice.
`python scripts/gate.py` deletes the store and that is gone with everything
else.
