# knos-oidc-interface

Read an OIDC token (GitHub Actions, GitLab CI, or any other RS256 issuer) that the knos-oidc program verified on Solana.

knos-oidc checks the token's RS256 signature on chain and leaves the result in an account it owns. Your program
takes that account and reads the claims the issuer signed: which repository, which commit, which workflow file at
which commit, which audience. There is no CPI and no oracle.

This crate has no dependency and does not allocate, so it builds with solana-program, pinocchio or anchor of any
version, and off chain. It reads the second deployment of knos-oidc unless you name the first (see below); a token
account has the same layout under both.

```toml
knos-oidc-interface = { git = "https://github.com/drexthealpha/Knos", tag = "v0.3.24" }
```

```rust
use knos_oidc_interface::{Token, ISSUER_GITHUB};

// token: the AccountInfo of a token account; now: Clock::get()?.unix_timestamp
let data = token.try_borrow_data()?;
// refuses an account the second deployment of knos-oidc does not own, a token not verified to the end, one over an
// hour past its expiry, and one a private key verified
let tok = Token::read(&token.owner.to_bytes(), &data, now).map_err(|_| ProgramError::InvalidAccountData)?;
if tok.issuer() != ISSUER_GITHUB { return Err(ProgramError::InvalidAccountData); }

let repo = tok.claim_u64("repository_id").ok_or(ProgramError::InvalidArgument)?;   // GitHub sends ids as strings
let sha = tok.claim("sha").ok_or(ProgramError::InvalidArgument)?;                  // the commit the workflow ran on
let runner = tok.claim("runner_environment").ok_or(ProgramError::InvalidArgument)?;
let aud = tok.audience().ok_or(ProgramError::InvalidArgument)?;
if !runner.is("github-hosted") || !aud.is("my-app:release") || sha.len() != 40 {
    return Err(ProgramError::InvalidArgument);
}
```

`tok.claims([b"repository_id", b"sha", b"aud"])` reads several claims in one pass over the payload, which costs
fewer compute units than one `claim` call each.

## What stays your program's job

knos-oidc only says the token is genuine. `Token::read` only adds that the account is knos-oidc's and the token is
fresh. Your program decides the rest:

1. **The issuer.** `issuer()` is `ISSUER_GITHUB`, `ISSUER_GITLAB`, or `ISSUER_OTHER` for any other issuer the
   program admitted: then `issuer_hash()` is sha256 of the issuer's URL, and you name the hashes you accept. They
   sign different claims.
2. **The claims that matter.** The repository (`repository_id`), the workflow file and its commit
   (`job_workflow_ref`, `job_workflow_sha`) if the statement depends on what code ran, and `runner_environment`.
3. **The audience.** Give your program its own audience prefix and require it, so a token minted for another
   program cannot be used with yours.
4. **Replay.** A verified token can be read by any program, any number of times, until an hour after its expiry.
   Bind it to one action in the audience and record that the action was done.
5. **The key, if a revoked key must stop at once.** A token account stays verified for up to 25 hours after its
   signing key was revoked or expired. Take the key account too (`tok.key()` is its address) and call
   `tok.check_key(&key.key.to_bytes(), &key.owner.to_bytes(), &key.try_borrow_data()?, now)`.

## Private keys

Any wallet can register a signing key of its own with knos-oidc, with no attestation, for an issuer no public runner
can reach (a company's GitHub Enterprise Server). Nobody vouches for such a key: a token it verified is the word of
the wallet that registered it, whatever issuer its claims name, GitHub included. `Token::read` refuses these tokens
(`Error::Private`). A program that wants them reads with `Token::read_any` and must then ask:

```rust
let tok = Token::read_any(&token.owner.to_bytes(), &data, now).map_err(|_| ProgramError::InvalidAccountData)?;
if tok.is_private() {
    // accept it only from the one wallet this program trusts for this purpose
    if tok.registrant() != Some(&expected_wallet.to_bytes()) { return Err(ProgramError::InvalidAccountData); }
}
```

A consumer that calls `read_any` and checks neither `is_private()` nor `issuer()` is the one way such a token is
taken for an issuer's.

## The two deployments

The crate's defaults (`ID`, `Token::read`, `Token::read_any`; `v2::read` is the same by name) read the second
deployment of knos-oidc. A key that GitHub's signature admits waits a day and a guardian's approval, every key
expires 30 days after it was last attested, and the guardian can revoke a key. It is upgradeable only through a
multisig with a public 48-hour delay, until an outside review.

The first deployment is immutable: its keys never expire and cannot be revoked. A token account has the same layout
under both, so the same code reads it, but nothing in this crate takes a first-deployment account unless you write
`v1`:

```rust
// refuses an account the first deployment does not own (a token the second deployment verified included)
let tok = knos_oidc_interface::v1::read(&token.owner.to_bytes(), &data, now).map_err(|_| ProgramError::InvalidAccountData)?;
```

A program trusts one deployment for a given token account, and says which.

## The program

| | |
|---|---|
| address (devnet), the second deployment | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` (`ID`, `ID_STR`; also `v2::ID`) |
| instructions and accounts | [`idl/knos_oidc_v2.json`](https://github.com/drexthealpha/Knos/blob/main/idl/knos_oidc_v2.json) |
| address of the first deployment | `vpWym9azbPU5f2PH2a6n8c4RfmsyUeW2dMuWr1DSHcE` (`v1::ID`, `v1::ID_STR`) |
| its instructions and accounts | [`idl/knos_oidc.json`](https://github.com/drexthealpha/Knos/blob/main/idl/knos_oidc.json) |
| how a token gets on chain, and the trust root | [`docs/OIDC.md`](https://github.com/drexthealpha/Knos/blob/main/docs/OIDC.md) |
| a complete consumer | [`examples/oidc_gate`](https://github.com/drexthealpha/Knos/tree/main/examples/oidc_gate) |

## Tests

`cargo test` reads the bytes of a real verified token account (`tests/fixtures/verified_token_v2.bin`, written by
`scripts/interface_fixture.py` from the test build of the second deployment) and checks every claim against a second
JSON parser. `tests/fixtures/verified_token.bin` is the same token verified by the test build of the first
deployment: the two accounts differ only in the address of the key account. `tests/differential.rs` asks the claims
reader and serde_json about 300,000 documents made at random from a fixed seed; the fuzz target in
`programs-v2/knos_oidc/fuzz` asks this crate's reader and the program's own on any bytes and requires the same answer.
