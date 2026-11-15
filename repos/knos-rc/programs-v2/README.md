# programs-v2/: the programs Knos runs today

This folder holds the source of Knos's **second** deployment on Solana [devnet](../docs/WORDS.md#devnet): the four
programs in use. "v2" means the second deployment, not a version number. Everything here runs on **devnet only**. No
program runs on mainnet, and no customer uses them yet.

## Why there are two folders

The first deployment, in [`programs/`](../programs), was deployed with no upgrade authority, so nobody can change it.
Its fixes and the new features could only go into new programs at new addresses: these. Both folders stay, because
anyone can rebuild either one and compare it with the chain. Build on this folder, not on `programs/`.

## What is live, and at which build

| folder | what it does | devnet address | runs | build hash | built from commit | live since |
|---|---|---|---|---|---|---|
| `knos_oidc` | the verifier: checks on chain that a CI login token ([OIDC](../docs/WORDS.md#token-oidc)) was signed by its issuer, RS256 or ES256 | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | 2.2 | `a2df952d…f34e632` | `f03ec515d866` | 9 Oct 2026 (proposal 7) |
| `knos_pay` | the [escrow](../docs/WORDS.md#escrow): holds money for a task and pays when a GitHub-signed token proves the work | `5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k` | 2.2 | `8b3c0440…f99867c` | `f8bcd9d51eda` | 9 Oct 2026 (proposal 8) |
| `knos_meter` | the [meter](../docs/WORDS.md#meter): counts each GitHub-signed check and charges it from prepaid credits | `FUMKkcE95x2kZUj1zZTCbgcYBmJ3WXPHL8pyA8J6anX` | 1.1 | `10f2b6cb…1a5e995e4` | `6eb81dd152bd` | 7 Oct 2026 (proposal 5) |
| `knos_passkey` | a [wallet](../docs/WORDS.md#wallet) that only a [passkey](../docs/WORDS.md#passkey) can spend from | `FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85` | 1.1 | `a9ce7a06…cac7cf81` | `6eb81dd152bd` | 7 Oct 2026 (proposal 6) |

The full hashes and commits, and the transactions that exercised each build, are in
[docs/reference/PROVENANCE.md](../docs/reference/PROVENANCE.md). Every upgrade proposal is in [`web/upgrades.json`](../web/upgrades.json).
The addresses are in [`program_ids.json`](program_ids.json).

The live build is the one built from the commit in the table, not necessarily from the code in this folder today.

## Rebuild and check one yourself

From the root of a clone, on a Linux file system, with docker and `solana-verify`. This is the command in
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

These programs can be [upgraded](../docs/WORDS.md#upgrade). Only one account can do it: a 2-of-3
[multisig](../docs/WORDS.md#multisig), and only after a public 8-day [time lock](../docs/WORDS.md#time-lock) (since 11 Oct 2026; 48 hours before).
**Today one person, the founder, holds all three keys.** So the delay gives everyone notice of a change, but it does
not stop him. [docs/reference/GOVERNANCE.md](../docs/reference/GOVERNANCE.md) says what each key can and cannot do. The multisig's address
is `upgrade_multisig` in [`program_ids.json`](program_ids.json).

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

This folder holds the source of Knos's **first** two programs on Solana [devnet](../docs/WORDS.md#devnet). They were
deployed with no upgrade authority, so nobody can change them, not even the founder. They stay here so anyone can
rebuild them and compare the result with the chain.

**Build on [`programs-v2/`](../programs-v2), not on this folder.** Nothing new is funded here.

### Why there are two folders

A [program id](../docs/WORDS.md#program-id) on Solana is tied to its deployment. A program with no upgrade authority
can never get new code. So the fixes and new features went into a second set of programs, at new ids, in
[`programs-v2/`](../programs-v2). The two folders are two different sets of programs on chain, not two versions of one.
"v2" means "second deployment", not "version 2".

### What is here

| program | what it does | devnet address | can it change? |
|---|---|---|---|
| `knos_oidc` | checks that a login token from GitHub Actions or GitLab CI ([OIDC](../docs/WORDS.md#token-oidc)) is really signed by them | `vpWym9azbPU5f2PH2a6n8c4RfmsyUeW2dMuWr1DSHcE` | no: it has no upgrade authority |
| `knos_pay` | an [escrow](../docs/WORDS.md#escrow): holds money for a GitHub issue and pays when a token signed by GitHub proves the work | `9UzPFbh2A4e4sEPgngKG523FfYLnQ3qPfFVfFTTAdfDi` | no: it has no upgrade authority |

These two have no version number of their own. The addresses are in [`program_ids.json`](program_ids.json).

Their known limits cannot be fixed, because the code cannot change. [SECURITY.md](../SECURITY.md) lists them. The
second deployment fixes them, and [docs/reference/OIDC.md](../docs/reference/OIDC.md) compares the two.

### Rebuild and check

- Build: `bash scripts/build_programs.sh` (needs `cargo build-sbf` from agave 2.3). It also refreshes the test builds
  in `tests/fixtures/`.
- Tests: `knos_oidc/tests/wycheproof.rs` runs Google's Project Wycheproof RSA test cases against the verifier's RSA
  code. CI runs it in `.github/workflows/program.yml`.
- Compare with the chain: `solana-verify get-program-hash -u devnet <address>` prints the hash of what runs. The
  comment at the top of [`Cargo.toml`](Cargo.toml) names the reproducible build: `solana-verify build programs
  --library-name <name>`. This repository records no verified build hash for these two programs, so nobody has
  recorded that the two hashes match. If you check it, you are the first.
- Interfaces (how to call them): [`idl/knos_oidc.json`](../idl/knos_oidc.json), [`idl/knos_pay.json`](../idl/knos_pay.json).

**Same names, two folders.** The crates here have the same names as two crates in `programs-v2/`. When you build the
second deployment with `solana-verify`, check that its line `Building manifest path` names `programs-v2/<name>`, not
this folder ([docs/reference/ASSURANCE.md](../docs/reference/ASSURANCE.md) explains why).
