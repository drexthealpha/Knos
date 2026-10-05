# GitHub Actions

**Supported.** RS256; four 2048-bit keys. Key sizes read from the issuer's key set on 2026-10-05.

| | |
|---|---|
| `iss` | `https://token.actions.githubusercontent.com` |
| key set | `https://token.actions.githubusercontent.com/.well-known/jwks` |
| claims, from | https://docs.github.com/en/actions/reference/security/oidc |

## Get a token

In a job with `permissions: id-token: write`:

```bash
curl -sSf -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=my-app:release:v1.2.0" | jq -r .value
```

## What it signs

The names and types are the issuer's; the values are examples.

```json
{
  "jti": "8b2c1f0e-6a4d-4c3b-9e2a-5d7f1c0b9a8e",
  "sub": "repo:octo/widgets:ref:refs/heads/main",
  "aud": "my-app:release:v1.2.0",
  "ref": "refs/heads/main",
  "sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "repository": "octo/widgets",
  "repository_owner": "octo",
  "repository_owner_id": "424242",
  "run_id": "36905461215",
  "run_number": "17",
  "run_attempt": "1",
  "repository_visibility": "public",
  "repository_id": "987654321",
  "actor_id": "1234567",
  "actor": "mona",
  "workflow": "release",
  "head_ref": "",
  "base_ref": "",
  "event_name": "push",
  "ref_protected": "true",
  "ref_type": "branch",
  "workflow_ref": "octo/widgets/.github/workflows/release.yml@refs/heads/main",
  "workflow_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "job_workflow_ref": "octo/widgets/.github/workflows/release.yml@refs/heads/main",
  "job_workflow_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "runner_environment": "github-hosted",
  "check_run_id": "5550001",
  "iss": "https://token.actions.githubusercontent.com",
  "iat": 1790000000,
  "exp": 1790000300
}
```

Worth gating on: `repository_id`, `repository_owner_id`, `job_workflow_ref`, `job_workflow_sha`, `ref`, `sha`, `event_name`, `runner_environment`, `aud`.
Every claim above is a top-level string or whole number, so each can be read.
Compare `repository_id`, not `repository`: a name can pass to someone else.

## Register its key

Nothing to do on devnet: this issuer has a number of its own, 0 (GitHub), and its keys are kept registered by the
rotate workflow ([docs/OIDC.md](../../../docs/OIDC.md), "The trust root of the second deployment"). `knos keys` prints the
keys the verifier holds now. In a local test:

```python
from knos.settle.v2 import oidc
issuer = oidc.GITHUB
ixs = [oidc.register_key_ix(payer, issuer, n, attest, attest_key), oidc.key_params_ix(payer, issuer, n)]
```

## Gate on it

```rust
let tok = Token::read(&token.owner.to_bytes(), &data, now).map_err(|e| ProgramError::Custom(e.code()))?;
if tok.issuer() != ISSUER_GITHUB { return Err(ProgramError::InvalidAccountData); }
let ok = tok.claim_u64("repository_id") == Some(987654321)
    && tok.claim_u64("repository_owner_id") == Some(424242)
    && tok.claim("job_workflow_ref").is_some_and(|v| v.is("octo/widgets/.github/workflows/release.yml@refs/heads/main"))
    && tok.claim("job_workflow_sha").is_some_and(|v| v.is("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"))
    && tok.claim("ref").is_some_and(|v| v.is("refs/heads/main"))
    && tok.claim("sha").is_some_and(|v| v.is("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"))
    && tok.claim("event_name").is_some_and(|v| v.is("push"))
    && tok.claim("runner_environment").is_some_and(|v| v.is("github-hosted"))
    && tok.audience().is_some_and(|a| a.starts_with("my-app"));
if !ok { return Err(ProgramError::InvalidArgument); }
```

The whole program around these lines is [`examples/oidc_gate/template.rs`](../../oidc_gate/template.rs).

## Tested

`tests/test_issuers.py` registers a key for this issuer in the test build of the verifier, verifies a token with exactly
the claims above and reads them back. That token is signed with a test key derived from a fixed seed, not by the issuer:
the test shows the program takes this shape, not that the issuer issued anything.
