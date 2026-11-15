# programs-v2/: the programs Knos runs today

The goal: Knos turns any research into a product billions of people use, in days, not years.

Knos carries research across the valley of death, toward Kardashev II and III.

This folder holds the source of Knos's **second** deployment on Solana [devnet](../docs/WORDS.md#devnet): the four
programs the site and CLI use, plus `knos_zk` (a Groth16 verifier deployed apart, see
[docs/reference/ZK.md](../docs/reference/ZK.md)). "v2" means the second deployment, not a version number. Everything here runs on **devnet only**. No
program runs on mainnet, and no customer uses them yet.

## Why there are two folders

The first deployment, in [`programs/`](../programs), was deployed with no upgrade authority, so nobody can change it.
Its fixes and the new features could only go into new programs at new addresses: these. Both folders stay, because
anyone can rebuild either one and compare it with the chain. Build on this folder, not on `programs/`.

## What is live, and at which build

| folder | what it does | devnet address | runs | build hash | built from commit | live since |
|---|---|---|---|---|---|---|
| `knos_oidc` | the verifier: checks on chain that a CI login token ([OIDC](../docs/WORDS.md#token-oidc)) was signed by its issuer, RS256 or ES256 | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | 2.2 | `a2df952d…f34e632` | `f03ec515d866` | 9 Oct 2026 (proposal 7) |
| `knos_pay` | the [payment program](../docs/WORDS.md#money-held-until-the-proof-passes): holds money for a task and pays when a GitHub-signed token proves the work | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | 2.2 | `8b3c0440…f99867c` | `f8bcd9d51eda` | 9 Oct 2026 (proposal 8) |
| `knos_meter` | the [meter](../docs/WORDS.md#meter): keeps an on-chain count of GitHub-signed checks, drawn from prepaid test credits (a devnet program) | `FUMKkcE95x2kZUj1zZTCbgcYBmJ3WXPHL8pyA8J6anX` | 1.1 | `10f2b6cb…1a5e995e4` | `6eb81dd152bd` | 7 Oct 2026 (proposal 5) |
| `knos_passkey` | a [wallet](../docs/WORDS.md#wallet) that only a [passkey](../docs/WORDS.md#passkey) can spend from | `FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85` | 1.1 | `a9ce7a06…cac7cf81` | `6eb81dd152bd` | 7 Oct 2026 (proposal 6) |

The full hashes and commits, and the transactions that exercised each build, are in
[docs/reference/PROVENANCE.md](../docs/reference/PROVENANCE.md). Every upgrade proposal is in [`web/upgrades.json`](../web/upgrades.json).
The addresses are in [`program_ids.json`](program_ids.json).

`knos_zk` is not in the table: it was deployed apart, at `5M67Aqw1JHNSVrhFxCSzTmewdpysRKDtBKkTLrb192bk`
(its devnet runs: [`zk/fixtures/score64/devnet.json`](../zk/fixtures/score64/devnet.json)).

The live build is the one built from the commit in the table, not necessarily from the code in this folder today.

## Rebuild and check one yourself

An upgrade's buffer is built by [`scripts/build_sbf.sh`](../scripts/build_sbf.sh), not by the `solana-verify` command
below: upgrades are sBPF v3 builds, and the image below (cargo-build-sbf 2.3) cannot make a v3 file that Agave 4.4 loads.
To check an upgrade proposal, check out the commit it names, then run:

```
bash scripts/build_sbf.sh v3 deploy
```

It needs cargo-build-sbf 4.4.0 with platform-tools v1.57 (the `v3-build` job of
[`.github/workflows/program.yml`](../.github/workflows/program.yml) installs both by sha256). The last column of
`programs-v2/target/arch-v3/HASHES-v3.txt` must equal what `node scripts/governance.mjs upgrade propose` printed for the
proposal's buffer.

For the deployed builds of this folder, from the root of a clone, on a Linux file system, with docker and `solana-verify`. This is the command in
[docs/reference/ASSURANCE.md](../docs/reference/ASSURANCE.md), which `scripts/deploy_v2.sh` and CI also run. First check out the commit in
the table.

```
rm -f programs-v2/target/deploy/knos_pay.so programs-v2/target/deploy/knos_oidc.so
solana-verify build "$PWD" --workspace-path "$PWD/programs-v2" --library-name knos_pay --base-image solanafoundation/solana-verifiable-build:2.3.11
solana-verify build "$PWD" --workspace-path "$PWD/programs-v2" --library-name knos_oidc --base-image solanafoundation/solana-verifiable-build:2.3.11
solana-verify get-executable-hash programs-v2/target/deploy/knos_pay.so
solana-verify get-program-hash -u devnet 5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k
```

The last two hashes must be equal. Do the same for `knos_oidc` and its address, and with `--library-name knos_meter` or
`knos_passkey` for the other two. The line `Building manifest path` must name `programs-v2/<name>/Cargo.toml`.
`programs/` has crates with the same names, and on some file systems (NTFS, so WSL under `/mnt/c`) it gets built
instead. [docs/reference/ASSURANCE.md](../docs/reference/ASSURANCE.md) explains this and shows how to hash the program without
`solana-verify`. [docs/reference/REPRODUCE.md](../docs/reference/REPRODUCE.md) is the one-button way.

## Who can change them today

The four programs in the table can be [upgraded](../docs/WORDS.md#upgrade). Only one account can do it: a 2-of-3
[multisig](../docs/WORDS.md#multisig), and only after a public 8-day [time lock](../docs/WORDS.md#time-lock) (since 11 Oct 2026; 48 hours before).
**Today one person, the founder, holds all three keys.** So the delay gives everyone notice of a change, but it does
not stop him. [docs/reference/GOVERNANCE.md](../docs/reference/GOVERNANCE.md) says what each key can and cannot do. The multisig's address
is `upgrade_multisig` in [`program_ids.json`](program_ids.json).

`knos_zk` is upgraded by one key, `DqH5N34nJQydHFDMjiMyWjfSsQUnKrcjwDhcWdMgk5Cp`, with no multisig and no time lock
(its upgrade authority as devnet reported it on 15 Nov 2026).

## Tests and tools in this folder (none of them is deployed)

| folder | what it is | run it |
|---|---|---|
| `handlers/` | Rust tests that send recorded transactions to the built programs in LiteSVM (a local Solana simulator) | `cd programs-v2/handlers && cargo test --locked` |
| `testdata/` | the recorded transactions those tests replay, written by `scripts/rust_test_vectors.py` and `scripts/adversarial_vectors.py` | |
| `fee_proofs/` | machine-checked proofs (Kani) that an order's fee stays within its limits, copied as text from `knos_pay/src` | `python3 scripts/kani_fee_record.py --ci` (needs Kani) |
| `knos_oidc/fuzz/` | fuzz tests: random inputs to the verifier's JSON reader and RSA code, compared with reference libraries | `cd programs-v2/knos_oidc/fuzz && cargo test --release --locked --test random --test seeds` |

Interfaces (IDL files): [`idl/`](../idl). Build the test binaries: `bash scripts/build_programs_v2.sh`. CI:
`.github/workflows/program.yml`.

## The first deployment, in programs/ (nobody can change it)

The first deployment has its own page: [programs/README.md](../programs/README.md).
