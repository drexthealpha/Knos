# A second person runs it

How to operate Knos on Solana devnet from a clean machine, with nothing of the founder's: no key, no file, no
access to the founder's GitHub account. It is a checklist.

**Not yet run by a second person.** Nobody but the founder has followed this page. The drill at the end is its
test; until a second person has run it, every step here is the founder's description of his own setup.

## What a second operator can and cannot do today

| duty | without the founder? | why |
|---|---|---|
| Carry signed tokens to the chain (the relay) | **yes** | `knos relay` needs any Solana key with a little devnet SOL. A relay decides nothing ([RELAY.md](RELAY.md)). |
| Send refunds, settlements and releases that are due | **yes** | they need no token and no key of Knos's; one pass of `knos relay` sends every one that is due. |
| Keep the verifier's signing keys from expiring (`Refresh`) | **yes, while the pinned rotate workflow can be fetched** | anyone may run it by hand from a repository of their own ([GOVERNANCE.md](GOVERNANCE.md), section 8). |
| Serve the site | **yes, at another address** | `bash scripts/build_site.sh` writes a static folder; any host serves it. |
| Fund and pay an order in a repository of their own | **yes** | install, comment, merge ([INSTALL.md](INSTALL.md)). |
| Register a new signing key of an issuer | **no** | the verifier takes that attestation only from repositories of one GitHub account, id 142920951 (`ATTEST_OWNER_ID` in [`pins.rs`](../programs-v2/knos_oidc/src/pins.rs)). |
| Approve, cancel or execute an upgrade; revoke a key; pause funding | **no** | all three member keys of both multisigs are the founder's. Outside key holders today: 0 ([KEYHOLDER.md](KEYHOLDER.md)). |
| Keep the published pinned workflows available | **no** | they are files in the founder's account; section 5 is what to do about it. |

## 1. A clean machine

- [ ] Python 3.10 or later, `git`, and the Solana command line (`solana`, `solana-keygen`).
- [ ] `pip install knos` (from PyPI, not from GitHub), or `git clone https://github.com/drexthealpha/Knos` and
      `pip install -e .` in the clone.
- [ ] `knos status` prints the four programs, their upgrade authority, every signing key with its expiry, and every
      pending upgrade. It reads the chain and needs no key. If it fails, stop and read what it names.

## 2. A fee payer, funded from the faucet

The fee payer pays transaction fees and holds nobody's money.

- [ ] `solana-keygen new --no-bip39-passphrase --outfile relay.json`
- [ ] `solana airdrop 2 "$(solana-keygen pubkey relay.json)" --url https://api.devnet.solana.com`, or paste the
      address into <https://faucet.solana.com>. The faucets limit how often they give; if one refuses, use the
      other or wait.
- [ ] `solana balance "$(solana-keygen pubkey relay.json)" --url https://api.devnet.solana.com` shows the SOL.

## 3. The relay

- [ ] One pass, by hand: `KNOS_RELAY_KEY="$(cat relay.json)" knos relay`. `KNOS_RELAY_KEY` is the key file's
      contents, not its path. With no key set, `knos relay` makes one in `~/.knos/relay-key.json` on first use.
- [ ] Keep it running: `KNOS_RELAY_KEY="$(cat relay.json)" knos relay --serve 3600`, restarted by a timer of your
      own (cron, a systemd timer). The founder's runs as [`worker.yml`](../.github/workflows/worker.yml), every 5
      minutes, with the key in the repository secret `KNOS_RELAY_KEY`; a fork of the repository with that secret
      set runs the same workflow.
- [ ] One token, by hand: `knos relay --token-file FILE` prints the result as JSON and exits 1 if Solana did not
      take it. A token sent twice pays nobody twice.

## 4. The workflows, and what each is for

All are in [`.github/workflows`](../.github/workflows) of the repository.

| workflow | what it does | what it needs |
|---|---|---|
| `worker.yml` | the public relay, every 5 minutes | secret `KNOS_RELAY_KEY` |
| `keys.yml` | once a day: the key refresh, as a second schedule beside the rotate repository's own | none of ours: GitHub signs the run |
| `fund.yml`, `prove.yml`, `attest.yml`, `check.yml` | the workflows a paying repository calls at a pinned commit | published in `drexthealpha/knos-workflows`; optional secret `KNOS_RELAY_KEY` in the calling repository |
| `program.yml` | builds the programs; its gate job has GitHub sign the build's hash | none |
| `release.yml` | the release | the founder's package and site credentials: not transferable by this page |
| `tests.yml`, `hermetic.yml`, `index.yml`, `network.yml`, `reproductions.yml`, `knos.yml`, `knos-check.yml`, `knos-reproduce.yml` | tests, the judge's image, the index, the Numbers page, outside reproductions, and Knos used on its own repository | none beyond GitHub's own token |

- [ ] In a repository of your own: install the workflow ([INSTALL.md](INSTALL.md), three steps), merge it, and
      comment `/knos fund 20` on an issue. On devnet the program's faucet gives the test USDC.

## 5. Where state lives

| what | where | if it is lost |
|---|---|---|
| Orders, balances, payments, signing keys, upgrade proposals | Solana devnet, in accounts of the four programs and of Squads | not ours to lose; devnet itself can be reset by its operators |
| The relay's log | the open issue labelled `knos-relay` in the repository that runs the relay | nothing on chain depends on it: a token the chain already took is never taken twice |
| The fee payer's key | your `relay.json`, or a repository secret | make another and fund it: it holds only fees |
| The multisig member keys, the two create keys, the deploy fee payer | the founder's key folder (`.knos-keys`, never committed), on the founder's machine | no upgrade, no key approval, no revocation, ever ([GOVERNANCE.md](GOVERNANCE.md), section 8) |
| What Knos remembers between runs (past refusals, a supplier's record) | the Sibyl store (`sibyl.db`) of the machine or run that judged; `KNOS_HOME` (default `~/.knos`) holds the hook's state and the relay's key | rebuilt from the chain and from GitHub where it can be; the rest is gone |
| The site | built from the repository by `scripts/build_site.sh`; served by GitHub Pages of the founder's account | build it anywhere; it is static |

## 6. How to rotate

- [ ] **The fee payer.** Make a new key (section 2), fund it, replace the secret or the environment variable, and
      move what SOL is left: `solana transfer <new address> ALL --keypair relay.json --url
      https://api.devnet.solana.com --allow-unfunded-recipient`. Nothing on chain names the old key.
- [ ] **A signing key of GitHub's or GitLab's.** Nothing to do by hand: the daily refresh keeps a published key
      alive for 30 more days, and `knos status` fails when one has under 7 days left. A new key needs the
      founder's account and the guardian ([GOVERNANCE.md](GOVERNANCE.md), section 8).
- [ ] **A multisig member key.** `node scripts/governance.mjs replace-member <old> <new>` prints the proposal and
      what will be true after it; `--send` creates it. It needs two member keys, so today it needs the founder.
- [ ] **An agent's payout key.** `knos agent rotate` ([AGENTS.md](AGENTS.md)).

## The drill: `second operator`

**Status: not yet run by a second person.** No result exists.

- **Who:** someone who is not the founder, on a machine that has never held a file of the founder's.
- **Starts from:** a clean clone (or `pip install knos`) and this page. No message to the founder.
- **Reaches:** "relay handles one devnet order": an order funded in the operator's own repository is paid, or
  refunded after its deadline, by a transaction the operator's own relay key sent.
- **Passes when:** (1) `knos status` exits 0; (2) the operator's fee payer holds faucet SOL; (3) the paying or
  refunding transaction's fee payer is the operator's address, as a block explorer shows it; (4) the operator
  lists every step where this page was not enough. A page that needed a question to the founder fails the drill.
- **Recorded as:** the date, the operator's handle, the transaction signature, the minutes from clone to
  payment, and the list from (4), in [DRILLS.md](DRILLS.md).
