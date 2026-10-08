# oidc_gate: let an instruction run only for a verified workload

Copy [`template.rs`](template.rs), change the marked lines, build. Your instruction then runs only when a token that
`knos-oidc` verified on chain says "repository X, branch main, workflow Y", or "Google Cloud service account Z".
There is no CPI, no oracle and no key of anyone's to trust. [docs/VERIFIER.md](../../docs/VERIFIER.md) is the one
page on the verifier and lists the other issuers; [`examples/issuers`](../issuers) has the lines for each.

This example is Knos's own, and no program outside this repository is known to read a token yet. For a whole program
to copy, in a workspace of its own with its test and the five mistakes to avoid, take
[`examples/reader_template`](../reader_template) instead; this folder is the shortest form of the same check.

## The steps

```bash
git clone --depth 1 https://github.com/drexthealpha/Knos
cargo new --lib my_gate
cp Knos/examples/oidc_gate/template.rs my_gate/src/lib.rs
cd my_gate
```

Add to `Cargo.toml`:

```toml
[lib]
crate-type = ["cdylib", "lib"]

[dependencies]
solana-program = "=2.2.1"
knos-oidc-interface = { git = "https://github.com/drexthealpha/Knos", tag = "v0.3.22" }   # no dependency of its own

[lints.rust]
unexpected_cfgs = { level = "allow" }
```

In `src/lib.rs` change the three lines marked CHANGE: your audience prefix, the repository's numeric id
(`gh api repos/OWNER/REPO --jq .id`) and the workflow file. Set the service account if you want one. Then:

```bash
cargo check                                   # the template as it stands compiles
cargo build-sbf                               # target/deploy/my_gate.so
solana program deploy --url devnet target/deploy/my_gate.so
```

`cargo check` of the unchanged template against the interface crate of this repository (by path) is what was run
for this release; `cargo build-sbf` and a deployment of the template were not. The crate itself is built for Solana
in every release: [`src/lib.rs`](src/lib.rs) here uses it and `tests/test_oidc_gate.py` runs that build.

In the workflow that may act, ask GitHub for a token with your audience (the job needs `id-token: write`):

```bash
curl -sSf -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
  "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=my-app:release:v1.2.0" | jq -r .value
```

Whoever sends your instruction writes that token to `knos-oidc` and verifies it first (`Write`, then two `Step`:
[docs/VERIFIER.md](../../docs/VERIFIER.md), call 2), then passes the two accounts below.

## The lines that do it

```rust
let tok = Token::read(&token.owner.to_bytes(), &data, now).map_err(|e| ProgramError::Custom(e.code()))?;
tok.check_key(&key.key.to_bytes(), &key.owner.to_bytes(), &key.try_borrow_data()?, now).map_err(|e| ProgramError::Custom(e.code()))?;
let from_ci = tok.issuer() == ISSUER_GITHUB && tok.claim_u64("repository_id") == Some(REPOSITORY_ID)
    && tok.claim("ref").is_some_and(|v| v.is("refs/heads/main")) && tok.claim("job_workflow_ref").is_some_and(|v| v.is(WORKFLOW))
    && tok.claim("runner_environment").is_some_and(|v| v.is("github-hosted"));
if !tok.audience().is_some_and(|aud| aud.starts_with(AUDIENCE)) || !from_ci {
    return Err(ProgramError::InvalidArgument);
}
// from here on: GitHub signed that this workflow file ran in this repository, on main, and asked for this audience
```

## Three things to build with it

- Upgrade a program only from a build your CI verified.
- Release a grant when the grantee's repository ships a tagged release.
- Mint only when a named cloud workload asks.

## The accounts to pass

| account | writable | what it is |
|---|---|---|
| token | no | `["tok", payer, sha256(token)]` under `knos-oidc`: the account the token was written to and verified in |
| key | no | the key account that verified the token. Its address is in the token account (`tok.key()`), so the client reads it from there; `check_key` refuses any other |

`knos-oidc` on devnet is `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` (the second deployment; `Token::read`, the
crate's default). The first deployment is `vpWym9azbPU5f2PH2a6n8c4RfmsyUeW2dMuWr1DSHcE` and is read with `v1::read`.

## What each check refuses

| check | what it refuses |
|---|---|
| `Token::read` | an account `knos-oidc` does not own (anyone can create an account holding the same bytes); a token whose signature was not checked to the end; a token more than an hour past its `exp`; a token that a privately registered key verified |
| `check_key` | a token whose key has since expired (nothing attested it for 30 days) or was revoked. Without it a revoked key still works for up to 25 hours |
| the audience prefix | a token minted for another program. Give your program a prefix nobody else uses |
| `issuer()` | a token another issuer signed. GitHub and gitlab.com have numbers; any other issuer is `ISSUER_OTHER`, and `issuer_hash()` is sha256 of its URL |
| `repository_id` | another repository. Compare the numeric id: a repository's name can be given to someone else |
| `ref` | a run on another branch or on a tag |
| `job_workflow_ref` | a run of any other workflow file, or of that file from another branch. The file at the path is what decided to ask for the token |
| `runner_environment` | a run on a machine its owner controls |
| `sub`, for a cloud | another service account. Google signs people's sign-ins under the same issuer, so the issuer alone says nothing |

One thing the crate cannot do for you: a verified token can be read by anyone, any number of times, until an hour
after it expires. Put the action's own details after your audience prefix (an amount, a recipient, a nonce), compare
them with what the instruction is about to do, and record that it was done.
[`examples/workflow_vault`](../workflow_vault) does exactly that.

What a verified token proves is that the issuer signed these claims. It does not prove what the workflow read or
decided, or what the code behind a service account does.

## This example

`src/lib.rs` is a release gate: per repository, it records the last commit for which GitHub signed "a workflow ran
here on a GitHub-hosted runner with audience `oidc-gate:release`". It reads the first deployment (`v1::read`), to
show how a deployment is named. `tests/test_oidc_gate.py` runs it in LiteSVM against the real verifier build;
`bash scripts/build_programs_v2.sh examples` rebuilds it. The example program is not deployed anywhere.
