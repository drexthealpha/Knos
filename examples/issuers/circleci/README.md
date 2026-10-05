# CircleCI

**Supported.** RS256; one 2048-bit key. Key sizes read from the issuer's key set on 2026-10-05 (at `https://oidc.circleci.com/org/00000000-0000-0000-0000-000000000000/.well-known/jwks-pub.json`).

| | |
|---|---|
| `iss` | `https://oidc.circleci.com/org/<organization id>` |
| key set | `<iss>/.well-known/jwks-pub.json` |
| claims, from | https://circleci.com/docs/guides/permissions-authentication/openid-connect-tokens/ |

## Get a token

In a CircleCI job; the default token (audience: the organisation's id) is in `$CIRCLE_OIDC_TOKEN` (the command is from https://circleci.com/docs/guides/permissions-authentication/oidc-tokens-with-custom-claims/):

```bash
circleci run oidc get --claims '{"aud": "my-app:release:v1.2.0"}'
```

## What it signs

The names and types are the issuer's; the values are examples.

```json
{
  "iss": "https://oidc.circleci.com/org/c9035eb6-6eb2-4c85-8a81-d9ed6a1d1d1e",
  "sub": "org/c9035eb6-6eb2-4c85-8a81-d9ed6a1d1d1e/project/3a2f5b1c-7d4e-4f6a-9b8c-0d1e2f3a4b5c/user/5e6f7a8b-9c0d-4e1f-a2b3-c4d5e6f7a8b9",
  "aud": "my-app:release:v1.2.0",
  "oidc.circleci.com/context-ids": [
    "7b6a5c4d-3e2f-4a1b-8c9d-0e1f2a3b4c5d"
  ],
  "oidc.circleci.com/job-id": "1f2e3d4c-5b6a-4978-8695-a4b3c2d1e0f9",
  "oidc.circleci.com/org-id": "c9035eb6-6eb2-4c85-8a81-d9ed6a1d1d1e",
  "oidc.circleci.com/pipeline-definition-id": "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
  "oidc.circleci.com/pipeline-id": "9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f",
  "oidc.circleci.com/project-id": "3a2f5b1c-7d4e-4f6a-9b8c-0d1e2f3a4b5c",
  "oidc.circleci.com/ssh-rerun": false,
  "oidc.circleci.com/vcs-origin": "github.com/octo/widgets",
  "oidc.circleci.com/vcs-ref": "refs/heads/main",
  "oidc.circleci.com/workflow-id": "2b3c4d5e-6f7a-4b8c-9d0e-1f2a3b4c5d6e",
  "iat": 1790000000,
  "exp": 1790000300
}
```

Worth gating on: `oidc.circleci.com/project-id`, `oidc.circleci.com/vcs-origin`, `oidc.circleci.com/vcs-ref`, `aud`.
Not read (a list, an object or a boolean; the reader takes top-level strings and whole numbers): `oidc.circleci.com/context-ids`, `oidc.circleci.com/ssh-rerun`.
One issuer URL per organisation. A job re-run with SSH carries `ssh-rerun` true, a boolean this reader does not read: a person could have typed the command.

## Register its key

A public key, one any program can rely on, is admitted on GitHub's signature: the attester's run of the pinned
rotate workflow with the input `issuer: https://oidc.circleci.com/org/c9035eb6-6eb2-4c85-8a81-d9ed6a1d1d1e` reads the key set over TLS, GitHub signs which key it found, and
the key then waits a day and the guardian's approval. You cannot do that alone; ask for it in an issue. The call it ends in:

```python
from knos.settle.v2 import oidc
ISS = "https://oidc.circleci.com/org/c9035eb6-6eb2-4c85-8a81-d9ed6a1d1d1e"
# attest: the verified token account of that run; attest_key: the key account that verified it
ixs = [oidc.register_issuer_key_ix(payer, ISS, n, attest, attest_key), oidc.key_params_ix(payer, ISS, n)]
```

A key of your own, usable at once, with nobody vouching for it (your program must then read with `Token::read_any`
and require `tok.registrant()` to be your wallet):

```python
ixs = [oidc.register_private_key_ix(wallet, ISS, n), oidc.key_params_ix(wallet, ISS, n, registrant=wallet)]
```

`n` is the modulus of the issuer's RS256 key, as an integer. In JavaScript the same calls are `registerIssuerKeyIx`,
`registerPrivateKeyIx` and `keyParamsIx` of `verifier(program)` in [`sdk/settle`](../../../sdk/settle).

## Gate on it

```rust
let tok = Token::read(&token.owner.to_bytes(), &data, now).map_err(|e| ProgramError::Custom(e.code()))?;
// any issuer but GitHub and gitlab.com is named by sha256 of its URL (solana_program::hash::hash)
if tok.issuer() != ISSUER_OTHER || tok.issuer_hash() != Some(&hash(b"https://oidc.circleci.com/org/c9035eb6-6eb2-4c85-8a81-d9ed6a1d1d1e").to_bytes()) {
    return Err(ProgramError::InvalidAccountData);
}
let ok = tok.claim("oidc.circleci.com/project-id").is_some_and(|v| v.is("3a2f5b1c-7d4e-4f6a-9b8c-0d1e2f3a4b5c"))
    && tok.claim("oidc.circleci.com/vcs-origin").is_some_and(|v| v.is("github.com/octo/widgets"))
    && tok.claim("oidc.circleci.com/vcs-ref").is_some_and(|v| v.is("refs/heads/main"))
    && tok.audience().is_some_and(|a| a.starts_with("my-app"));
if !ok { return Err(ProgramError::InvalidArgument); }
```

The whole program around these lines is [`examples/oidc_gate/template.rs`](../../oidc_gate/template.rs).

## Tested

`tests/test_issuers.py` registers a key for this issuer in the test build of the verifier, verifies a token with exactly
the claims above and reads them back. That token is signed with a test key derived from a fixed seed, not by the issuer:
the test shows the program takes this shape, not that the issuer issued anything.
