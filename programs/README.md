# programs/: the first deployment (nobody can change it)

This folder holds the source of Knos's **first** two programs on Solana [devnet](../docs/WORDS.md#devnet). They were
deployed with no upgrade authority, so nobody can change them, not even the founder. They stay here so anyone can
rebuild them and compare the result with the chain.

**Build on [`programs-v2/`](../programs-v2/README.md), not on this folder.** Nothing new is funded here.

## Why there are two folders

A [program id](../docs/WORDS.md#program-id) on Solana is tied to its deployment. A program with no upgrade authority
can never get new code. So the fixes and new features went into a second set of programs, at new ids, in
[`programs-v2/`](../programs-v2/README.md). The two folders are two different sets of programs on chain, not two
versions of one. "v2" means "second deployment", not "version 2".

## What is here

| program | what it does | devnet address | can it change? |
|---|---|---|---|
| `knos_oidc` | checks that a login token from GitHub Actions or GitLab CI ([OIDC](../docs/WORDS.md#token-oidc)) is really signed by them | `vpWym9azbPU5f2PH2a6n8c4RfmsyUeW2dMuWr1DSHcE` | no: it has no upgrade authority |
| `knos_pay` | a [payment program](../docs/WORDS.md#money-held-until-the-proof-passes): holds money for a GitHub issue and pays when a token signed by GitHub proves the work | `9UzPFbh2A4e4sEPgngKG523FfYLnQ3qPfFVfFTTAdfDi` | no: it has no upgrade authority |

These two have no version number of their own. The addresses are in [`program_ids.json`](program_ids.json).

Their known limits cannot be fixed, because the code cannot change. [SECURITY.md](../SECURITY.md) lists them. The
second deployment fixes them, and [docs/reference/OIDC.md](../docs/reference/OIDC.md) compares the two.

## Rebuild and check

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
