# Why a chain?

"Could this be built without crypto?" For one machine: yes, and Knos stays fully local there. Solo use needs no
chain, no key and no network.

For a team, the question is who holds the list of claims. A server could hold it. Someone would then have to run it,
secure it, keep it reachable from every laptop, every contractor and every vendor's cloud sandbox, and be trusted by
all of them not to rewrite it. Every vendor now ships coordination for its own agents only (Claude Code Projects,
Cursor Projects, GitHub Agent HQ). None of them will host the list for the others.

Solana replaces that server:

- **Nobody operates it.** A team is one Solana Attestation Service credential. There is no Knos server, and there is
  nothing to host, patch or pay for beyond the transaction fees.
- **Every sandbox can reach it.** A cloud agent needs `pip install knos`, a member key and outbound access to one RPC
  host. See [CLOUD.md](CLOUD.md).
- **Exactly one agent wins a claim.** A claim is an attestation whose address is derived from a salted hash of the
  file. Solana refuses a second account at the same address, so two agents cannot both create the same claim. Claims
  that merely overlap (a file and its folder) are ordered by slot, then by address. The protocol is in
  `src/knos/team/protocol.py` and is property-tested (see [BENCH.md](BENCH.md)).
- **Outsiders can verify the record.** Each agent's day is written as a record: counters plus a Merkle root over its
  salted log, signed by its key. Anyone can read it (`knos agent record`).
- **Budgets hold when the software is bypassed.** An agent's Tempo access key or Solana delegate is limited by the
  chain itself. Signing directly with the agent's key, with no Knos code involved, is refused past the limit
  (`tests/test_chain_budgets.py`, and the Tempo Moderato runs in [BENCH.md](BENCH.md)).

## What the chain holds, and what it does not

Only salted hashes, public keys, counters, times and sealed boxes. No path, repo name, org, user name or description
is ever written in plaintext. The team salt is sealed to each member's key (a PyNaCl sealed box); display names are
encrypted with a key derived from that salt.

## What you are trusting

Said plainly:

- **Members are trusted not to sabotage.** Any member key can close any claim in the team (that is how lapsed claims
  are swept), so a hostile member could close yours. The record shows who closed what. Remove a member with
  `knos team remove`.
- **Blocking the RPC is a bypass.** If a machine cannot reach the chain, its edits go ahead locally with a one-line
  warning, because Knos never blocks work on an outage. Other members see that machine's claims lapse.
- **The owner key controls membership.** It is encrypted at rest and is unlocked only by a passphrase typed at a
  terminal.

## What it costs

Measured on the local validator (see [BENCH.md](BENCH.md)): a 5,000-lamport fee to place a claim, plus a rent
deposit of about 0.0028 SOL that is refunded when the claim is released. A member key keeps a small float for
deposits: by default 20 live claims' worth plus 0.005 SOL for fees, about 0.065 SOL. Devnet costs nothing.

## Why jobs settle on a chain

Paying an agent for work needs someone to hold the money between "here is the job" and "I accept it". On Fiverr or
Upwork that is the marketplace, and the worker waits days after approval (see [COMPARE.md](COMPARE.md)). On Knos it is
an escrow program: the buyer's one signature moves the price into a vault only the program's rules can open, and the
buyer's accept moves 95% to the worker in that same transaction. Nobody, including Knos, can move job money any other
way, and every job's outcome is a public account, so an agent's record (paid, rejected, expired) is recomputed from the
chain by anyone (`knos jobs stats --agents`), not read from a database someone could edit.

### Alpenglow and finality

Before Alpenglow, `finalized` trails `confirmed` by about 32 slots (~13 s), so a payment app settles on `confirmed`
and accepts a small rollback risk. On 1 Oct 2026 we measured the gap at 0 slots on devnet and testnet and 32 on
mainnet-beta (consistent with Alpenglow active on devnet and testnet only). Knos measures the gap at start-up: where it
is 2 slots or less it waits for `finalized`, which cannot roll back, at no cost in time; elsewhere it uses `confirmed`.
`knos doctor` prints which, and why. Devnet bench, same code, both modes: accept 2.6 s (`finalized`) vs 3.0 s
(`confirmed`), wall clock from Lagos.
