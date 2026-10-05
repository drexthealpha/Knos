# Microsoft Entra ID (app and managed identity tokens)

**Supported.** RS256; seven 2048-bit keys. Key sizes read from the issuer's key set on 2026-10-05 (at `https://login.microsoftonline.com/common/discovery/v2.0/keys`).

| | |
|---|---|
| `iss` | `https://login.microsoftonline.com/<tenant id>/v2.0` |
| key set | `https://login.microsoftonline.com/<tenant id>/discovery/v2.0/keys` |
| claims, from | https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference |

## Get a token

In an Azure resource with a managed identity (the command is from https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/how-to-use-vm-token):

```bash
curl 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=api%3A%2F%2Fmy-app' -H Metadata:true -s | jq -r .access_token
```

## What it signs

The names and types are the issuer's; the values are examples.

```json
{
  "aud": "api://my-app",
  "iss": "https://login.microsoftonline.com/72f988bf-86f1-41af-91ab-2d7cd011db47/v2.0",
  "azp": "6e74172b-be56-4843-9ff4-e66a39bb12e3",
  "oid": "a1b2c3d4-0000-4000-8000-123456789abc",
  "sub": "a1b2c3d4-0000-4000-8000-123456789abc",
  "tid": "72f988bf-86f1-41af-91ab-2d7cd011db47",
  "ver": "2.0",
  "roles": [
    "Mint.Run"
  ],
  "iat": 1790000000,
  "exp": 1790000300
}
```

Worth gating on: `tid`, `oid`, `azp`, `aud`.
Not read (a list, an object or a boolean; the reader takes top-level strings and whole numbers): `roles`.
One issuer URL per tenant. A resource that takes version 1.0 tokens gets `iss` `https://sts.windows.net/<tenant id>/`: register that URL instead. `aud` is the resource asked for, so it names your program and not one action.

## Register its key

A public key, one any program can rely on, is admitted on GitHub's signature: the attester's run of the pinned
rotate workflow with the input `issuer: https://login.microsoftonline.com/72f988bf-86f1-41af-91ab-2d7cd011db47/v2.0` reads the key set over TLS, GitHub signs which key it found, and
the key then waits a day and the guardian's approval. You cannot do that alone; ask for it in an issue. The call it ends in:

```python
from knos.settle.v2 import oidc
ISS = "https://login.microsoftonline.com/72f988bf-86f1-41af-91ab-2d7cd011db47/v2.0"
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
if tok.issuer() != ISSUER_OTHER || tok.issuer_hash() != Some(&hash(b"https://login.microsoftonline.com/72f988bf-86f1-41af-91ab-2d7cd011db47/v2.0").to_bytes()) {
    return Err(ProgramError::InvalidAccountData);
}
let ok = tok.claim("tid").is_some_and(|v| v.is("72f988bf-86f1-41af-91ab-2d7cd011db47"))
    && tok.claim("oid").is_some_and(|v| v.is("a1b2c3d4-0000-4000-8000-123456789abc"))
    && tok.claim("azp").is_some_and(|v| v.is("6e74172b-be56-4843-9ff4-e66a39bb12e3"))
    && tok.audience().is_some_and(|a| a.starts_with("my-app"));
if !ok { return Err(ProgramError::InvalidArgument); }
```

The whole program around these lines is [`examples/oidc_gate/template.rs`](../../oidc_gate/template.rs).

## Tested

`tests/test_issuers.py` registers a key for this issuer in the test build of the verifier, verifies a token with exactly
the claims above and reads them back. That token is signed with a test key derived from a fixed seed, not by the issuer:
the test shows the program takes this shape, not that the issuer issued anything.
