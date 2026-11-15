# AWS (IAM outbound identity federation)

**Supported in part.** RS256 only when asked for: AWS recommends ES384, which is not verified. The RSA key size is not in AWS's documentation and was not measured (the issuer is per account).

| | |
|---|---|
| `iss` | `https://<account's id>.tokens.sts.global.api.aws` |
| key set | `<iss>/.well-known/jwks.json` |
| claims, from | https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_outbound_token_claims.html |

## Get a token

In any IAM principal, once `aws iam enable-outbound-web-identity-federation` has been run in the account (https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_outbound_getting_started.html):

```bash
aws sts get-web-identity-token --audience my-app:mint:42 --signing-algorithm RS256 --duration-seconds 300
```

## What it signs

The names and types are the issuer's; the values are examples.

```json
{
  "iss": "https://abc123-def456-ghi789-jkl012.tokens.sts.global.api.aws",
  "aud": "my-app:mint:42",
  "sub": "arn:aws:iam::123456789012:role/DataProcessingRole",
  "jti": "xyz123-def456-ghi789-jkl012",
  "https://sts.amazonaws.com/": {
    "aws_account": "123456789012",
    "source_region": "us-east-1",
    "org_id": "o-abc1234567",
    "principal_tags": {
      "environment": "production"
    },
    "lambda_source_function_arn": "arn:aws:lambda:us-east-1:123456789012:function:process-data"
  },
  "iat": 1790000000,
  "exp": 1790000300
}
```

Worth gating on: `sub`, `aud`.
Not read (a list, an object or a boolean; the reader takes top-level strings and whole numbers): `https://sts.amazonaws.com/`.
The account, organisation, tags and the Lambda or EC2 source are nested under `https://sts.amazonaws.com/` and are not read. `sub` (the role's ARN) carries the account.

## Register its key

A public key (one any program can rely on) needs GitHub's signature first. Knos's pinned rotate workflow, run
with the input `issuer: https://abc123-def456-ghi789-jkl012.tokens.sts.global.api.aws`, fetches the issuer's key set over HTTPS, and GitHub
signs which key it found. The key then waits one day and needs the guardian's approval (the guardian is a key that
can approve or revoke keys; one person holds it today). You cannot do this alone: ask for it in an issue on
drexthealpha/Knos. The last step is this call:

```python
from knos.settle.v2 import oidc
ISS = "https://abc123-def456-ghi789-jkl012.tokens.sts.global.api.aws"
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
if tok.issuer() != ISSUER_OTHER || tok.issuer_hash() != Some(&hash(b"https://abc123-def456-ghi789-jkl012.tokens.sts.global.api.aws").to_bytes()) {
    return Err(ProgramError::InvalidAccountData);
}
let ok = tok.claim("sub").is_some_and(|v| v.is("arn:aws:iam::123456789012:role/DataProcessingRole"))
    && tok.audience().is_some_and(|a| a.starts_with("my-app"));
if !ok { return Err(ProgramError::InvalidArgument); }
```

The whole program around these lines is [`examples/oidc_gate/template.rs`](../../oidc_gate/template.rs).

## Tested

`tests/test_issuers.py` registers a key for this issuer in the test build of the verifier, verifies a token with exactly
the claims above and reads them back. That token is signed with a test key derived from a fixed seed, not by the issuer.
The test shows the verifier accepts a token of this shape. It does not show the issuer ever issued one.
