# oidc_gate: require a GitHub-signed fact in your own Solana program

This example is Knos's own. It shows what any other program would write, and [`template.rs`](template.rs) is that
code with nothing else around it: copy it, change three lines, build.

`knos-oidc` checks an OIDC token's RS256 signature on chain and leaves the result in an account it owns. Your
program is passed that account and reads it. There is no CPI, no oracle and no key of anyone's to trust.

| deployment of `knos-oidc` on devnet | address | read it with |
|---|---|---|
| second (keys expire and can be revoked) | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` | `Token::read` (the crate's default) |
| first | `vpWym9azbPU5f2PH2a6n8c4RfmsyUeW2dMuWr1DSHcE` | `v1::read` |

## The lines a program needs

```toml
[dependencies]
knos-oidc-interface = { git = "https://github.com/drexthealpha/Knos", tag = "v0.3.15" }   # no dependency of its own
```

```rust
use knos_oidc_interface::{Token, ISSUER_GITHUB};

// accounts: token (read-only), key (read-only), then your own
let now = Clock::get()?.unix_timestamp;
let data = token.try_borrow_data()?;
let tok = Token::read(&token.owner.to_bytes(), &data, now).map_err(|e| ProgramError::Custom(e.code()))?;
tok.check_key(&key.key.to_bytes(), &key.owner.to_bytes(), &key.try_borrow_data()?, now)
    .map_err(|e| ProgramError::Custom(e.code()))?;
if tok.issuer() != ISSUER_GITHUB { return Err(ProgramError::InvalidAccountData); }
let aud = tok.audience().ok_or(ProgramError::InvalidArgument)?;
let wf = tok.claim("job_workflow_ref").ok_or(ProgramError::InvalidArgument)?;
if !aud.starts_with("my-app:release:")
    || !wf.starts_with("octo/widgets/.github/workflows/release.yml@")
    || tok.claim_u64("repository_id") != Some(MY_REPOSITORY_ID) {
    return Err(ProgramError::InvalidArgument);
}
// from here on: GitHub signed that this workflow file ran in this repository and asked for this audience
```

## The accounts to pass

| account | writable | what it is |
|---|---|---|
| token | no | `["tok", payer, sha256(token)]` under `knos-oidc`: the account the token was written to and verified in. Whoever sends your instruction verifies the token first ([docs/OIDC.md](../../docs/OIDC.md), "Put a token on chain") |
| key | no | the key account that verified the token. Its address is in the token account (`tok.key()`), so the client reads it from there; `check_key` refuses any other |

## What each check means

| check | what it refuses |
|---|---|
| `Token::read` | an account `knos-oidc` does not own (anyone can create an account holding the same bytes); a token whose signature was not checked to the end; a token more than an hour past its `exp`; a token that a privately registered key verified |
| `check_key` | a token whose key has since expired (nothing attested it for 30 days) or was revoked. Without it a revoked key still works until the token is stale |
| `issuer()` | a token GitLab or another issuer signed, when you mean GitHub |
| `aud` starts with your prefix | a token minted for another program. Give your program a prefix nobody else uses |
| `job_workflow_ref` | a run of any other workflow file. The file at the path is what decided to ask for the token |
| `repository_id` | another repository. Compare the numeric id: a repository's name can be given to someone else |
| `sha`, `ref`, `runner_environment`, `actor_id`, ... | read any further claim GitHub signs with `tok.claim("...")` or `tok.claim_u64("...")` |

One thing the crate cannot do for you: a verified token can be read by anyone, any number of times, until an hour
after it expires. Put the action's own details after your audience prefix (an amount, a recipient, a nonce), compare
them with what the instruction is about to do, and record that it was done.
[`examples/workflow_vault`](../workflow_vault) does exactly that.

## This example

`src/lib.rs` is a release gate: per repository, it records the last commit for which GitHub signed "a workflow ran
here on a GitHub-hosted runner with audience `oidc-gate:release`". It reads the first deployment (`v1::read`), to
show how a deployment is named. `tests/test_oidc_gate.py` runs it in LiteSVM against the real verifier build;
`bash scripts/build_programs_v2.sh examples` rebuilds it. The example program is not deployed anywhere, and no
program outside this repository is known to read a token yet.
