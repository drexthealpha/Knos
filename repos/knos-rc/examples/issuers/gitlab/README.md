# GitLab CI (gitlab.com)

**Supported.** RS256; one 4096-bit and two 2048-bit keys. Key sizes read from the issuer's key set on 2026-10-05.

| | |
|---|---|
| `iss` | `https://gitlab.com` |
| key set | `https://gitlab.com/oauth/discovery/keys` |
| claims, from | https://docs.gitlab.com/ci/secrets/id_token_authentication/ |

## Get a token

In the job's entry in `.gitlab-ci.yml`; the token is in `$KNOS_TOKEN`:

```yaml
id_tokens:
  KNOS_TOKEN:
    aud: my-app:release:v1.2.0
```

## What it signs

The names and types are the issuer's; the values are examples.

```json
{
  "namespace_id": "72",
  "namespace_path": "my-group",
  "project_id": "20",
  "project_path": "my-group/my-project",
  "user_id": "1",
  "user_login": "sample-user",
  "user_email": "sample-user@example.com",
  "user_access_level": "owner",
  "pipeline_id": "574",
  "pipeline_source": "push",
  "job_id": "302",
  "ref": "main",
  "ref_type": "branch",
  "ref_path": "refs/heads/main",
  "ref_protected": "true",
  "groups_direct": [
    "my-group/my-subgroup"
  ],
  "runner_id": 1,
  "runner_environment": "gitlab-hosted",
  "sha": "dddddddddddddddddddddddddddddddddddddddd",
  "project_visibility": "public",
  "ci_config_ref_uri": "gitlab.com/my-group/my-project//.gitlab-ci.yml@refs/heads/main",
  "ci_config_sha": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "jti": "235b3a54-b797-45c7-ae9a-f72d7bc6ef5b",
  "iss": "https://gitlab.com",
  "sub": "project_path:my-group/my-project:ref_type:branch:ref:main",
  "aud": "my-app:release:v1.2.0",
  "iat": 1790000000,
  "exp": 1790000300
}
```

Worth gating on: `project_id`, `namespace_id`, `ref_path`, `ref_protected`, `ci_config_ref_uri`, `ci_config_sha`, `sha`, `runner_environment`, `aud`.
Not read (a list, an object or a boolean; the reader takes top-level strings and whole numbers): `groups_direct`.
A self-managed GitLab signs with its own URL as `iss`: register that URL as any other issuer.

## Register its key

Nothing to do on devnet: this issuer has a number of its own, 1 (gitlab.com), and its keys are kept registered by the
rotate workflow ([docs/reference/OIDC.md](../../../docs/reference/OIDC.md), "The trust root of the second deployment"). `knos keys` prints the
keys the verifier holds now. In a local test:

```python
from knos.settle.v2 import oidc
issuer = oidc.GITLAB
ixs = [oidc.register_key_ix(payer, issuer, n, attest, attest_key), oidc.key_params_ix(payer, issuer, n)]
```

## Gate on it

```rust
let tok = Token::read(&token.owner.to_bytes(), &data, now).map_err(|e| ProgramError::Custom(e.code()))?;
if tok.issuer() != ISSUER_GITLAB { return Err(ProgramError::InvalidAccountData); }
let ok = tok.claim_u64("project_id") == Some(20)
    && tok.claim_u64("namespace_id") == Some(72)
    && tok.claim("ref_path").is_some_and(|v| v.is("refs/heads/main"))
    && tok.claim("ref_protected").is_some_and(|v| v.is("true"))
    && tok.claim("ci_config_ref_uri").is_some_and(|v| v.is("gitlab.com/my-group/my-project//.gitlab-ci.yml@refs/heads/main"))
    && tok.claim("ci_config_sha").is_some_and(|v| v.is("eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"))
    && tok.claim("sha").is_some_and(|v| v.is("dddddddddddddddddddddddddddddddddddddddd"))
    && tok.claim("runner_environment").is_some_and(|v| v.is("gitlab-hosted"))
    && tok.audience().is_some_and(|a| a.starts_with("my-app"));
if !ok { return Err(ProgramError::InvalidArgument); }
```

The whole program around these lines is [`examples/oidc_gate/template.rs`](../../oidc_gate/template.rs).

## Tested

`tests/test_issuers.py` registers a key for this issuer in the test build of the verifier, verifies a token with exactly
the claims above and reads them back. That token is signed with a test key derived from a fixed seed, not by the issuer.
The test shows the verifier accepts a token of this shape. It does not show the issuer ever issued one.
