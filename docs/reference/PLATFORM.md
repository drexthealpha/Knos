# Knos on today's Solana: sBPF v3, one-transaction verification, v1 transactions (v0.3.29)

**In plain words.** Every Knos program ever built was built for the oldest program format, sBPF v0 (no commit ever
targeted another; the AUDIT page has the history). This release builds the four programs for sBPF v3, which devnet runs
today and which future upgrades will require.

A build for sBPF v2 also checks a GitHub token's RSA signature in ONE
transaction instead of two (measured on devnet: 882,519 compute units); today's v3 cannot, for lack of a 128-bit
multiply, so it keeps two.

The new builds are written to devnet and handed to the
upgrade multisig; they replace the live programs only when a Squads proposal passes its 8-day time lock.
Nothing on this page has replaced a live program yet.

## 1. What devnet runs (13 Oct 2026)

Read from devnet's feature accounts; the AUDIT table in the release notes has the slots and ids.

| feature | on devnet | what Knos does with it |
|---|---|---|
| sBPF v3 deployment and execution (`5cC3fo…`) | active | the four programs are built for v3 (`scripts/build_sbf.sh v3`) |
| sBPF v2 (`F6UVKh…`) | active | its PQR instructions (64 x 64 -> 128-bit product) make one-transaction RSA possible; the v3 of Agave 4.4 lacks them |
| v1 transactions, 4,096 bytes (SIMD-0385, `txv1aq…`) | active | a token and its verification in one transaction (section 4) |
| secp256r1 precompile (SIMD-0075) | active | ES256 tokens (section 5) |
| `big_mod_exp` syscall | **not active** (no feature account) | not used by any deployed build; a build with the crate feature `big_mod_exp` exists for a cluster that has it |
| SIMD-0500: no new deployments of sBPF v0, v1, v2 (`B8JJXC…`) | not active yet | the reason the v3 buffers are prepared now (section 7) |
| Agave version | 4.4.0-beta.0 (`solana cluster-version -u devnet`) | the local measurements use the same release |

## 2. Builds

`bash scripts/build_sbf.sh v3 deploy` builds the four programs with a pinned toolchain (cargo-build-sbf 4.4.0 from the Agave 4.4.0-beta.0
release, platform-tools v1.57, `--locked`, file paths remapped so the bytes do not depend on where the checkout is) and writes their hashes to
`deploy/upgrade-0329/HASHES-v3.txt`.

The ELF header's `e_flags` is the sBPF version; the script refuses a file whose version is not the one asked for.

**Not the 2.3 toolchain.** An sBPF v3 file built by cargo-build-sbf 2.3.13 with platform-tools v1.48 (the toolchain the repository used until
now) does not load in Agave 4.4: `solana-test-validator` 4.4.0-beta.0 stops with "ELF error: Failed to parse ELF file: invalid file header".

The v3 format devnet activated (feature `5cC3fo…`) is a later one than the 2.3 toolchain writes. So v3 needs the 4.4 toolchain. The v2 test
build of the 2.3 toolchain loads in both solders 0.29's LiteSVM and Agave 4.4.

The Python tests load `tests/fixtures/platform/knos_oidc_v2_test.so`, the test build (`--features testkeys`) for sBPF v2, built with the
repository's pinned 2.3 toolchain (`cd programs-v2/knos_oidc && cargo build-sbf --arch v2 --features testkeys`): LiteSVM as solders 0.29.0
ships cannot load an sBPF v3 file ("invalid file header"), so v3 is measured in `solana-test-validator` 4.4.0-beta.0.

The verified (docker) build is `solana-verify build "$PWD" --workspace-path "$PWD/programs-v2" --library-name <name>
--arch v3 --base-image <image>`. This machine has no docker, so that build was not run here: the members compare the
buffers with their own rebuild (STEPS.md says how).

The v3 deploy builds (cargo-build-sbf 4.4.0, platform-tools v1.57; `deploy/upgrade-0329/HASHES-v3.txt`), each smaller
than the program data account it would replace on devnet (oidc 279,360, pay 408,280, meter 317,600, passkey 214,176
bytes), so no ExtendProgram is needed:

| program | e_flags (sBPF) | bytes | executable hash (`solana-verify get-executable-hash`) |
|---|---|---|---|
| knos_oidc | 3 | 172,952 | `d565487fc00c71b6b03a441915067075eb710d6509f6b8108aa31eaa9975298a` |
| knos_pay | 3 | 362,512 | `95fa02b2b16e6336a5a9cd8cb1fe1a8246c55a2176e8a875b7099d49b86d6fb5` |
| knos_meter | 3 | 158,368 | `0c400e6bb0f975e9a7af633a0b6e3d7e2af3528109431154799b946c7d0cc80c` |
| knos_passkey | 3 | 108,232 | `d5a5db160eab9fbfdd70712f14898b06daeb1b068eaa1f442f82fe492e5b1c73` |

These are built from this release's source with the PLATFORM changes uncommitted; the hashes change if anything in
programs-v2 changes before the commit. Rebuild at the release commit and compare before proposing. Agave 4.4 refuses the v3 builds of the 2.3 toolchain.

## 3. One-transaction RS256 verification

knos-oidc computes s^65537 mod n (16 squarings and one product) in Montgomery form. The v0 build does it on 32-bit
limbs (`rsa.rs`): a 2048-bit squaring is 64 x 64 limb products plus the reduction, and the whole verification costs
more than one transaction's 1,400,000 compute units, so the client sends Step(8), Step(8).

The v2 build does the same arithmetic on 64-bit limbs (`rsa64.rs`, chosen by `build.rs` for an sBPF v2 target,
`modexp.rs`): the PQR instructions make each 64 x 64 -> 128-bit product two instructions, and a squaring is 32 x 32
limb products, a quarter of the multiplications. One Step(16) then does everything in one transaction.

The token account is unchanged, and the running power is the same bytes in both arithmetics, so a token stepped
halfway under one build finishes under the other (an upgrade between two Steps changes nothing;
`tests/test_platform_verify.py`).

**sBPF v3 (v0.3.30): one transaction too, for a token of up to 5,000 bytes.** The v3 that Agave 4.4 runs (SIMD-0178,
SIMD-0189, SIMD-0377) has no high-half multiply. A v3 build of platform-tools v1.57 holds `mul64` and no `uhmul64`
(`llvm-objdump -d`), where the v2 build holds 21 `uhmul64`.

LLVM compiles a u128 product for v3 into a call to
compiler-rt's `__multi3`.

The first v3 build with 64-bit limbs (v0.3.29) did exactly that and was slower than 32-bit
limbs (table below). v0.3.30 keeps the same 64-bit-limb Montgomery code (same rows, same reductions, same token
bytes) and only changes how each t + a b + c is formed on v3 (`rsa64.rs`, module `h`; `build.rs` sets `knos_mulhi32`
for an sBPF v3 target).

It uses four inline 32 x 32 -> 64-bit `mul64`s on halves that are loaded and stored as 32-bit words
(`ldxw`/`stxw`, one instruction each, instead of shifts). They are summed in an order in which no u64 can overflow, so there
are no carry tests (the bounds are written beside the code).

The v3 deploy build holds 90 `mul64`, no `uhmul64` and
no `__multi3` call. The v0 and v2 builds are byte for byte what they were (same sha256 as the knos-0.3.29 source, built
with the same toolchain), and a native test checks the v3 arithmetic against the u128 one limb for limb.

`big_mod_exp` is not active on devnet, so no deployed build uses it. The crate feature `big_mod_exp` does the power
in one syscall for a cluster where it is active; a program that names an inactive syscall does not load.

**Measured** in LiteSVM (solders 0.29.0) with the test builds (`--features testkeys`) and a GitHub-shaped token signed
by the tests' seed-derived 2048-bit key (synthetic tokens, real arithmetic; `pytest -s tests/test_platform_verify.py`
prints every figure). Compute units per transaction; a transaction may use 1,400,000.

| build | plan | 1,922-byte token | 3,500 bytes | 8,192 bytes (the most the program takes) |
|---|---|---|---|---|
| sBPF v0, 32-bit limbs (what devnet runs) | Step(8), Step(8) | 762,618 + 828,096 = 1,590,714 in two transactions | | |
| sBPF v0, 32-bit limbs | Step(16) | refused: out of compute units | | |
| sBPF v2, 64-bit limbs | Step(8), Step(8) | 425,513 + 491,167 | | |
| sBPF v2, 64-bit limbs | **Step(16), one transaction** | **881,617** | 941,261 | 1,117,916 |
| sBPF v2, 64-bit limbs | Write (whole token) + Step(16) in ONE v1 transaction of 2,322 bytes | **893,664** | | |

A 4096-bit key (GitLab's) under the v2 build: Step(4) four times, at most 971,533 compute units a transaction for a
2,379-byte token and 1,193,424 for 8,191 bytes: four transactions where the v0 build needs six. A tampered signature is
refused by the one-step path (error 70; 65 when the changed signature is not below the modulus).

**Measured on devnet** (13 Oct 2026, Agave 4.4.0-beta.0): the same sBPF v2 test build deployed at a program id of
our own, `2V9M2NyfQGGUxpdSXiVjgUfpTrdy4xgkZ7KowBX753j9` (deploy `5Zw8aGyr…`; upgrade authority the PLATFORM wallet
`42agkcTx…`; a TEST build: it trusts only the tests' seed keys, and it is no Knos program). Compute units as the
cluster reports them (`getTransaction` `computeUnitsConsumed`), 1,921-byte token:

| what | transaction | compute units |
|---|---|---|
| Step(8), then Step(8) (the old plan, under the v2 build) | `RKfE4QjG…`, `3HxyvjzJ…` | 427,192 + 492,140 |
| **Step(16): the whole verification in ONE transaction** | `44AdiYqa…` | **882,519** |
| **Write (whole token) + Step(16) in ONE v1 transaction of 2,279 bytes** | `3N3TyGNC…` | **889,651** |

Full signatures: RegisterKey `2dHLQhq4noXF7q5VkGwpTdUs1nd7HAMnq8hLHfsJRXrDLhopCibVc4SBFAxajhT8EEq34tVHGPJ7KiVcHAVaKR1F`,
KeyParams `4idQiQZmHtM7Rp8zxmWTgZfWgEi4aPNynsM7BfCVcPoLtmESZ5fSz1JHrE9SwkZmPXHhU415u4Qm2vjj9ANRm8Uh`, Step(8)
`RKfE4QjGYHES2keLNJAH6CiX5h4jr8Cv6HCrBLbuVFkyd4CGc2vv39fznarYRPiUbvt8GYvtFJET2y9rozj5B8d` and
`3HxyvjzJWBZGoyRtRGUezLRa5k8TWKdjwHssUWfr42WFwEkCicdvMuMYeseyo1cpJQGNuSSzqZZRHwGvLU23rgq7`, Step(16)
`44AdiYqamWoJ5ak2xa2orGu1uRpJUwuh2hujMdWxfVVTD2mS1EaATWwAnygvRXZsNQgN9SH7F1Vm6z3v99BpR3X6`, v1
`3N3TyGNCgdTQ8MBcFadxiMUiCy8F3CiFAdE44wFLuD3kXGn1X3BCojMzZFf1QGMRQnAskEnhNC3JAGeUNZ3cxwDs`, deploy
`5Zw8aGyrYY5ukXWnjBb1xL3V9C5cGhK2RWQ2Rs6Ajv9Nxm1i1ieDpZPv4TDgKjKAo5i7kb7E9rnRcEpJRxSTSZ87`.

**All three formats side by side** in `solana-test-validator` 4.4.0-beta.0 (the release devnet runs, every feature
active, including SIMD-0500 and SIMD-0385), each test build at its own program id, the same 1,921-byte token
(compute units from `getTransaction`):

| build | Step(8) + Step(8) | Step(16), one transaction | Write + Step(16), one v1 transaction |
|---|---|---|---|
| sBPF v0, 32-bit limbs (today) | 761,805 + 826,794 | out of compute units (1,399,850 consumed) | out of compute units |
| sBPF v2, 64-bit limbs | 421,797 + 488,638 | **881,415** | **896,314** (2,279 bytes) |
| sBPF v3, 32-bit limbs (the v0.3.29 v3 deploy builds) | 719,805 + 781,472 | out of compute units | out of compute units |
| sBPF v3, 64-bit limbs via `__multi3` (v0.3.29 attempt, discarded) | 1,027,779 + 1,086,730 | out of compute units | out of compute units |
| **sBPF v3, 64-bit limbs, products from 32-bit halves (v0.3.30)** | 631,262 + 691,200 | **1,291,845** (1,952-byte token) | **1,301,807** (2,308 bytes) |

**sBPF v3, v0.3.30, by token size** (local `solana-test-validator` 4.4.0-beta.0 from the Agave 4.4 release, nothing
on devnet; the knos_oidc v3 test build at a fresh program id; synthetic tokens signed by the tests' seed keys; 14 Oct 2026):

| 2048-bit key, Step(16) in one transaction | 1,952 bytes | 3,500 | 4,000 | 4,500 | 5,000 | 5,500 | 8,192 (MAX_JWT) |
|---|---|---|---|---|---|---|---|
| compute units | 1,291,845 | 1,343,659 | 1,361,438 | 1,373,076 | 1,390,608 | out of compute units | out of compute units |

A token the v1 transaction carries whole is about 3,600 bytes at most, so every one-transaction (Write + Step(16))
verification fits; the margin for other instructions is about 98,000 compute units at the usual size and shrinks with
the token.

`knos.platform.verify.plan(..., "auto", elf, token_bytes)` takes one Step for a v3 build up to `V3_ONE_STEP_MAX` =
4,000 bytes and Step(8), Step(8) above (8,192 bytes: 667,386 + 891,286). A 4096-bit key keeps the two-step plan on v3
(six Steps, at most 1,031,214 compute units a transaction for a 2,409-byte token and 1,071,940 for 8,191 bytes): its
Step(4) runs out.

A forged signature is refused (1,237,747 consumed, error, nothing verified). The v3 deploy build of knos_oidc is now
the line `scripts/build_sbf.sh v3 deploy` writes for it (executable hash `d565487f…`): the v3 buffer written on 13-14 Oct for the
old build no longer matches it.

So: **before** 761,637 + 826,670 = 1,588,307 compute units in two transactions (LiteSVM, today's v0 test build,
1,893-byte token; 761,805 + 826,794 in the validator); **after**, with the v2 build, 882,519 in ONE transaction on
devnet (`44AdiYqa…` above), and with the v0.3.30 v3 build 1,291,845 in ONE transaction on a local Agave 4.4 validator
(not measured on devnet).

The client keeps the old path: `KNOS_OIDC_VERIFY=two` (the default until the upgrade has executed) sends Step(8),
Step(8), which every build takes; `one` sends Step(16); `auto` reads the deployed build's sBPF version
(`knos.platform.verify.plan`). Switch the default to `auto` once the upgrade proposal has executed.

## 4. v1 transactions (4,096 bytes)

`knos.chain` already sends v1 transactions (SIMD-0385) when a message is too big for 1,232 bytes, with the compute
limit and the priority fee (a lamport total) in the message. New here: `knos.platform.verify.one_transaction_ixs`
puts the whole token (one Write) and Step(16) in ONE v1 transaction.

The chunked Write path stays for a cluster or an endpoint that refuses v1 (`chain.v1_refused`), which the relay falls
back to.

Measured in LiteSVM (`tests/test_platform_verify.py`): a 1,922-byte token written whole and verified by Step(16) in one
v1 transaction of 2,322 bytes, 893,664 compute units, under the sBPF v2 build. The same instructions weigh more than
1,232 bytes, so no legacy transaction can carry them.

## 5. ES256 (secp256r1 precompile)

knos-oidc's VerifyEs256 (instruction 15, `es256.rs`) already verifies ES256 tokens through the secp256r1 precompile
at top level: it reads the instruction before it from the instructions sysvar and checks that it is the precompile
over this token's signing input and this key. A legacy transaction leaves 780 bytes for the signing input.

`knos.platform.verify.es256_v1_ixs` sends the same two instructions in a v1 transaction, where the signing input can
be about 3,400 bytes or more (`tests/test_platform_es256.py`).

Measured in LiteSVM (`tests/test_platform_es256.py`), one v1 transaction each, under today's v0 test build and the v2
build: a 781-byte signing input (1,287-byte transaction) 40,183 and 41,013 compute units; 2,000 bytes (2,506) 75,320 and
78,870; 3,000 bytes (3,506) 104,082 and 107,132. A signature over other bytes is refused by the precompile: the
transaction does not run.

## 6. Per-claim accounts, rent, finality

- **Per-claim accounts.** A block gives each writable account at most 12,000,000 compute units (Agave's cost
  tracker). What one claim writes is its own: the token account `["tok", payer, sha256(token)]`, the order and its
  money `["ord", …]`, `["ov", order]`, the markers `["used", sha256(signature)]`, `["done", order, pr]`, `["q", …]`,
  `["as", …]`, `["hb", order]`. Shared by design: the fee account of a mint (orders are spread over several,
  `knos.settle.v2.fee_accounts`), the relayer that pays, and, for the 2.0 job instructions only, the per-mint vault
  `["vault", mint]`; orders do not use it. `knos.platform.claims.shared_writable` checks a set of instructions for
  accounts two claims both write (`tests/test_platform_claims.py`).
- **Rent.** Devnet's rent-exempt minimum is 5,080 lamports a byte including the 128-byte overhead (`solana rent`,
  13 Oct 2026), where it was 6,960: about 27% less, not the 90% of the proposal. The relay now asks the cluster
  (`getMinimumBalanceForRentExemption`, `Ledger.rent`) instead of using 6,960, so any cut is used the day it is live.
- **Finality.** `KNOS_COMMITMENT` = processed, confirmed or finalized (`knos.platform.finality`). Unset, Knos asks
  each cluster `getAgGenesisCert` once: a certificate (Alpenglow) means `finalized`, null or "Method not found" means
  `confirmed` as before. Every wait and read in `knos.chain`, the fan-out ledger and the readers uses it. See
  [PLATFORM.md](PLATFORM.md).

## 7. The upgrade

The buffers are on devnet, handed to the upgrade vault `CKCrTB…` (multisig `9HcsMEo2…`, time lock 691,200 s); a v3
or a v2 knos_oidc is still to be chosen. Nothing was proposed, approved or executed, and no key signed anything.

SIMD-0500 (`B8JJXC…`, not active on devnet on 13 Oct 2026) will refuse v0, v1 and v2 deployments once active; programs
already deployed keep running.

## 8. What is not done

- The verified (docker) build of the v3 programs: no docker on this machine. The program.yml change (`--arch v3`, a
  4.4 toolchain image) is not made yet.
- One-transaction RSA on sBPF v3 (v0.3.30): measured on a local validator only, not on devnet. It does not cover a
  2048-bit token over 5,000 bytes nor a 4096-bit key in four Steps; those keep more Steps. More room would come from
  limbs below 32 bits (e.g. 28-bit, so products are summed without carries) or a hand-scheduled row loop; not attempted.
- `big_mod_exp`: inactive on devnet; the crate feature is written but no build of it was compiled or run here.
- The relay still estimates the last Step's compute units with the two-step figures (`_LAST_STEP`); with
  `KNOS_OIDC_VERIFY=one` a Step(16) that does not fit beside other instructions is sent alone (the relay's existing
  fallback).
- Per-claim accounts: the 2.0 job instructions keep the per-mint vault (orders do not use it); moving jobs to per-job
  token accounts is a program change to the money path, left for a reviewed release.

## Alpenglow: paid and final

**In plain words.** Solana devnet now runs Alpenglow, a new way for validators to agree. A payment there is final
about a second after Knos sends it, not 13 seconds later. Knos asks each cluster which way it runs and, on Alpenglow,
waits until a payment is final before it says "paid".

On a cluster that has not moved yet, nothing changes.

### How Knos tells

Knos asks the cluster's RPC `getAgGenesisCert` once per RPC address (`knos.platform.finality`):

| The answer | What it means | What Knos waits for |
| --- | --- | --- |
| a certificate `{block: {slot, blockId}, signature: {signature, bitmap}}` | Alpenglow is active | `finalized` |
| `null` | the cluster still runs TowerBFT | `confirmed`, as before |
| error -32601 "Method not found" | a node older than Agave 4.3, which cannot run Alpenglow | `confirmed`, as before |
| no answer | nothing is known | `confirmed`, asked again after 60 s |

Knos never decides by a date or a version string. A certificate is kept for the life of the process; a `null` is
asked again after 10 minutes, so a relay that runs through a migration switches by itself.
`KNOS_COMMITMENT` still wins when it is set; `KNOS_ALPENGLOW=on|off` lets an operator override the detection.

Sources, read 14 Oct 2026: the method page [solana.com/docs/rpc/http/getaggenesiscert](https://solana.com/docs/rpc/http/getaggenesiscert)
(no parameters; `null` while the cluster runs TowerBFT; -32601 on a node older than Agave 4.3); Agave `rpc/src/rpc.rs`
`get_ag_genesis_cert` at commit 722c8f4b, which reads the finalized bank; `@solana/kit` `packages/rpc-api/src/getAgGenesisCert.ts`.

Also read: [solana.com/upgrades/alpenglow](https://solana.com/upgrades/alpenglow) (under Alpenglow `confirmed` and `finalized` are the same state,
new code should use `finalized`, and `confirmed` will be deprecated and removed; target finality about 150 ms, "an expectation, not a
constant").

**What devnet said** (14 Oct 2026, `api.devnet.solana.com`, solana-core 4.4.0-beta.0): a certificate for block slot
504,148,999, block id `13f09ed2…de31677`, signed by 13 validators (the bitmap's set bits). Mainnet-beta (4.3.0)
answered `null`; testnet answered a certificate.

### What switched to `finalized` on Alpenglow

Every place Knos waited or read at a hard-coded `confirmed` now asks `knos.platform.finality`:

- sending and waiting: `knos.chain.Ledger` (blockhash, preflight, the wait, reads), `chain.wait` / `wait_all`, the
  fan-out ledger the relays use (release of held money, payouts, Gate bounty payments, refunds), the WebSocket wait;
- Knos Record anchors (`knos.record.anchoring`), x402 settlement confirmation (`knos.money.x402_exact`), the faucet;
- the readers: receipts rebuilt from the chain (`knos.receipt`, `knos.bundle`), statements, audit, observe and the
  ZK client ask the cluster once; the plan floor reads at its ledger's commitment; a ledger that only reads, the
  payment history reader (`knos.records`) and the mainnet check never add a request of their own and read at
  `finalized` once the process knows the cluster runs Alpenglow (`finality.cached`), else at `confirmed`, which is
  the same state there.

The other `confirmed` words in the code are names of states (the relay queue's "confirmed", the five payment states)
or texts about spreadsheet formats; they are not commitments and did not change.

### Waits retuned

- The first look at a payment just sent comes after 0.25 s on Alpenglow (0.5 s on TowerBFT). Later looks stay at
  0.5 s: the public devnet RPC takes 40 requests of one method per 10 s.
- After a payment is reported, the job waits at most 10 s for `finalized` on Alpenglow (40 s, `FINAL_WAIT`, on
  TowerBFT). A payment Knos already waited for at `finalized` is final at once: nothing is asked again.
- The wait for a sent transaction keeps its own ceiling (`knos.chain.wait`), which is not the blockhash's life: with
  200 ms slots (SIMD-0525) a blockhash lasts about 33 s on devnet, measured on 14 Oct 2026 as lastValidBlockHeight
  minus the `confirmed` block height over the block rate ([PLATFORM.md](PLATFORM.md),
  `python -m knos.platform.blockhash`). A transaction that must wait for another signer uses a durable nonce instead.

### "Paid and final in N ms"

The payment comment on a pull request adds one line once the payment is final:
`Paid and final in N ms after it was sent to Solana.` A Record anchor keeps `commitment` and `final_ms`. The site's
live page and `stats.json` (`finality`) show the cluster's consensus and the measured figures below.

### Measured on devnet

Our own test traffic, labelled "internal dogfooding" everywhere (`docs/finality.json`, every signature listed there).
`scripts/alpenglow_latency.py` signs each transaction, subscribes to it at `confirmed` and at `finalized` over one
WebSocket, sends it through Knos's ledger, then runs Knos's own wait. 49 transactions on 14 Oct 2026, one machine,
the public RPC:

| Transactions | n | send to finalized, p50 | p95 |
| --- | --- | --- | --- |
| all | 49 | 1,205 ms | 2,449 ms |
| Knos Record anchors | 30 | 1,213 ms | 3,040 ms |
| funding held money (knos_pay FundWallet, 60 s deadline, test mint) | 15 | 1,134 ms | 2,449 ms |
| refund of held money after the deadline | 4 | 1,249 ms | 1,322 ms |

The `confirmed` and `finalized` notifications came at the same moment for every one of the 49, which is the "same
state" the Alpenglow page describes. The figure includes the trip to the RPC and its notification, not only the
validators' vote. Knos's own polling wait returned at p50 1,852 ms and p95 3,798 ms (`KNOS_WS=1` waits on the
WebSocket instead).

No payout is in the sample: a payout needs a GitHub OIDC token of a signed workflow run. Of 15 test jobs, 4 were
refunded by this script and 11 by another relayer first.

### Transaction counts and slot streams

Knos's dashboards count Knos's own programs' transactions (`scripts/network_stats.py`), never the cluster's
transaction count, so vote transactions leaving blocks under Alpenglow change none of its numbers. Knos does not
stream slots, blocks, shreds or Geyser updates (it reads single transactions and uses `signatureSubscribe` only), so
there is no per-(slot, bank_id) buffer to add and no ticks are counted.

## Durable nonces: sign a funding now, send it later

A Solana transaction names a recent blockhash and is refused once the cluster's block height passes the
`lastValidBlockHeight` that came with it ([confirmation docs](https://solana.com/docs/advanced/confirmation): the most
recent 151 stored hashes).

The window is counted in blocks, so it shrank in seconds when devnet moved to 200 ms slots (SIMD-0525,
`proposals/0525-reduce-slot-times.md`: "any user-facing ... behavior measured in number of slots may become shorter in
wall-clock time").

**Measured on devnet, 14 Oct 2026** (`python -m knos.platform.blockhash`, raw output kept by the build): the
`confirmed` block height was 134 to 146 blocks (mean 143) below `lastValidBlockHeight` while it rose 232 blocks in
54.0 s (4.297 a second; `getRecentPerformanceSamples` gave 236 to 240 ms a slot).

A blockhash fetched at `confirmed`
therefore had **about 33 s** left, not the minute older pages assumed.

That is too short for a funder whose approver signs on another machine, a hardware or cold wallet, or an agent whose owner approves its funding.

A durable nonce replaces the blockhash with a value kept in a nonce account; the transaction's first instruction
advances it, so the signed bytes stay good until they land, and land once.

### Use

| step | call | who signs |
|---|---|---|
| make a nonce account | `python -m knos.platform.nonce create PAYER_KEY NONCE_KEY [AUTHORITY]` | the payer and the new nonce key |
| build the message | `knos.platform.nonce.message(ixs, fee_payer, nonce, authority, value, v1=True)` | nobody yet |
| first signature | `nonce.sign_part(msg, [funder])`, written with `nonce.encode` | the funder, on their machine |
| more signatures | `python -m knos.platform.nonce cosign TX_FILE KEY` | each co-signer, when they can |
| send | `python -m knos.platform.nonce send TX_FILE` (refused while a signature is missing) | nobody: the bytes are complete |

`nonce.still_good(ledger, tx)` says whether the nonce still holds the value the transaction signed over; once the
transaction lands it does not, so the same bytes can never pay twice. Messages are v1 by default (SIMD-0385: the
compute limit in the message, 4,096 bytes, no lookup tables, so the nonce account is always a static key as SIMD-0242
requires).

### On devnet (14 Oct 2026, own test keys, synthetic Token-2022 mint `4Fx2QgywyiAyHTMqkFRLEnF2hPW89MfWi9TEqwXjEYSa`)

`scripts/capabilities_devnet.py KEYDIR nonce` made nonce account `7XD6BDC2G676KQ85vkp34vgrSy8whk5EsvAGJJj9SZZJ`
([`5s2w28fa…`](https://explorer.solana.com/tx/5s2w28fa1B9wp2qdMaC8Jh5UQWyj2XJm1GRxXzeYjY38rstgpbstRB2TA4uZhemnJqYUw7oeUXPnKAfJKFcc8bWB?cluster=devnet)),
then had the funder sign a knos_pay `FundOrderWallet` alone and the relay add its fee-payer signature and send it 56.9 s later, well past any
blockhash's life:
[`3LT3NScV…`](https://explorer.solana.com/tx/3LT3NScVpHQLbrh7n1A7y7aFta8ZVm2aUUq3bifEk8pzwd2yYBm6Yy54N5dHjTwcQxq4mcoAULBwR5qM5wvcWibq?cluster=devnet)
funded order `GNqQRH9mZabN43vynzgFoJFRq7ETpuY8eujQYEGM8uyv`.

A second run 59.0 s apart,
[`618qYsba…`](https://explorer.solana.com/tx/618qYsba2M4EcAgk8kdVpVokTzVszH2zN4z1BhfqEn5d8NQFKkf3twpjebD1D3PQ8NXX6QzqAtvL3Nn9MrjK6Smg?cluster=devnet),
then read the nonce back: it had moved on, so those bytes can never land again.

Both orders hold 5 synthetic test units in a Token-2022 mint with no extensions (`python -m knos.platform.token22` passes it) and are refunded at their
deadline.

Tests: `tests/test_platform_nonce_v34.py`.

## Priority fees sized to the work, and a WebSocket wait

Two switches for whoever runs a Knos relay or sends Knos transactions (`src/knos/platform/priority.py`). Both are off
unless set, so nothing changes for anyone who does not ask.

| variable | what it does |
| --- | --- |
| `KNOS_PRIORITY=auto` | before a transaction is sent: a simulation measures the compute units it uses, the limit is set to that plus 15%, and the price is the 75th percentile of `getRecentPrioritizationFees` for the accounts it writes |
| `KNOS_PRIORITY=<number>` | the same limit, at that many micro-lamports a compute unit |
| `KNOS_PRIORITY_MAX` | the most it will pay a unit (default 200,000 micro-lamports) |
| `KNOS_WS=1` | wait for confirmation with one `signatureSubscribe` over the cluster's WebSocket, after one status read, instead of asking `getSignatureStatuses` every 0.4 s; falls back to asking if the WebSocket cannot be used |

Why the limit matters: a priority fee is paid on the compute-unit LIMIT, not on what was used ([compute
budget](https://solana.com/docs/core/fees/compute-budget), read 14 Oct 2026). Knos's default limit is the most a
transaction may use, 1,400,000 units.

On a v1 transaction the two compute budget instructions do nothing; `knos.chain.message_v1` already reads their
values into the message's own limit and priority fee, so the same setting serves both formats.

Why the WebSocket matters: the public devnet endpoint allows 100 requests in 10 seconds per address
([clusters](https://solana.com/docs/references/clusters)); polling a slow payout spends that allowance.

### On devnet (14 Oct 2026, memo transactions from a test wallet, synthetic text)

| setting | transaction | fee (lamports) | units used |
| --- | --- | --- | --- |
| `auto` (the devnet estimate was 0: limit only) | `5DQE7BExKrFDLz1MpxF8bs5PTcaRvJrDq784QE7JavGqq6pt1Cdhq2U5JDjfJsntmPfVfVpfUyctQYvAhLuqzMPH` | 5,000 | 34,772 |
| `5000` micro-lamports a unit | `3fbKZsan5n4Fto5o4AnE8vvisYcvYYHyaW4jR9CkWpvTWRmkttR9GXQXvy2UPsqacA2SFjZiHW3L7JheehxV2Wvg` | 5,202 | 34,922 |

The second paid 202 lamports of priority fee on a limit of about 40,400 units. At the same price on the old limit of
1,400,000 units it would have paid 7,000. A `signatureSubscribe` over `wss://api.devnet.solana.com` for
`2YzenZTX7aAUFoWeF3sm5jEXkpbqSxbeBgc7Gb1D29r8gRHwKsBA1EASwSPQAZA2nJUtz3XLPBUXp6kX9QG8QoLW` was notified 1.6 seconds
after the transaction was sent (one run, not a benchmark).

## Token safety: mints that can be held, accounts a payout can reach

knos_pay holds a bounty in a token account of its own and pays it with one transfer. Token-2022 lets a mint carry
extensions that change what a transfer does, and some of them let somebody other than the funder and the referee decide
what happens to held money.

Since 0.3.31 Knos reads a mint's extensions before it holds a bounty in it (`knos fund-wallet` refuses), and anyone
can check a mint or a payee's token account first (`src/knos/platform/token22.py`). The extensions are described at
[solana.com/docs/tokens/extensions](https://solana.com/docs/tokens/extensions) (read 14 Oct 2026).

| extension | on | why it matters to held money | Knos |
| --- | --- | --- | --- |
| PermanentDelegate | mint | the delegate can move or burn the tokens in any account, the payment program's too | refuses to fund |
| Pausable | mint | the pause authority can stop every transfer, the payout's too | refuses to fund |
| TransferHook | mint | every transfer runs another program with accounts the payout does not pass | refuses to fund |
| NonTransferable | mint | the tokens cannot move | refuses to fund |
| TransferFeeConfig (a fee above 0) | mint | the payee receives less than the terms say | refuses to fund |
| DefaultAccountState frozen | mint | a payee's new account starts frozen | refuses to fund |
| ConfidentialTransferMint, MintCloseAuthority, InterestBearingConfig, ScaledUiAmount | mint | amounts can move encrypted afterwards, the mint can be closed at zero supply, or wallets show a different number | warns |
| MemoTransfer (required) | payee's account | an incoming transfer needs a Memo instruction right before it; the payout carries none | the account cannot receive a payout |
| frozen | payee's account | a frozen account receives nothing | the account cannot receive a payout |

Classic SPL Token mints (test USDC among them) have no extensions; nothing changes for them.

### Check one

```
python -m knos.platform.token22 MINT_OR_TOKEN_ACCOUNT [...]      # one JSON line each; exit 1 when one is refused
```

An agent reads the same answer from the MCP resource `knos://token/{address}` ([MCP_SERVER.md](MCP_SERVER.md)).

### On devnet (14 Oct 2026, mints made for this test, synthetic)

| address | made with `spl-token` 5.3.0 | what the check says |
| --- | --- | --- |
| `DCtFdxWfiEPFp3TP4HqQ4N3LYvi7VXYA44D3HdshrTqX` | Token-2022, no extension | ok |
| `EtbPvaxwXBKUvcjfU5yAxNckzKAxSkifCwQkjVdcTxfS` | `--enable-permanent-delegate` | refused: PermanentDelegate; `knos fund-wallet ... --mint` stops before anything is sent |
| `EQcDmUQXjjbtbnSH7GcKzM1vkP1kKTLR4tkj22YF7aXH` | a 50 basis point transfer fee | refused: TransferFeeConfig |
| `CU3aX9mni6T3WPwHqgWHuSmKmgVgGWoNJUYsWebeo36W` | a token account with `enable-required-transfer-memos` (transaction `4r2pAwf8cTD86EPf2wcBj26Kne6PjStYNEQ1Q3i6NCruYPqcZzetMoxtAaAsjvQc4cS6NAkfHnSLztXiLo8su4TL`) | cannot receive a payout: MemoTransfer |

The payout's failure on a memo-required account follows from the Token-2022 rule (the Memo must be the instruction
right before the transfer, at the same level) and from knos_pay issuing no Memo; a payout into such an account was not
attempted on devnet.

## The hash devnet runs

Rebuild knos_oidc and knos_pay, the programs that check the proof and pay, and compare: the hash devnet runs equals the verified build hash recorded for each ([PROVENANCE](PROVENANCE.md)). Read on 27 Oct 2026.

```sh
solana-verify get-program-hash -u devnet FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W   # knos_oidc: a2df952d262c48edacf2f594a01321e805c28f1dc523cb6efa75f2c45f34e632
solana-verify get-program-hash -u devnet 5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k   # knos_pay: 8b3c044024eac6e00cf10930c325465d5682c3fb7273fe2f0d59c6e01f99867c
```

| program | id | verified build hash, and the hash devnet runs |
|---|---|---|
| knos_oidc | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | `a2df952d262c48edacf2f594a01321e805c28f1dc523cb6efa75f2c45f34e632` |
| knos_pay | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | `8b3c044024eac6e00cf10930c325465d5682c3fb7273fe2f0d59c6e01f99867c` |
