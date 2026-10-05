# Okta

**Supported.** RS256; two 2048-bit keys. Key sizes read from the issuer's key set on 2026-10-05 (at `https://okta.okta.com/oauth2/v1/keys`).

| | |
|---|---|
| `iss` | `https://<Okta domain>/oauth2/<authorization server id>` |
| key set | `<iss>/v1/keys` |
| claims, from | https://developer.okta.com/docs/api/openapi/okta-oauth/guides/overview/ |

## Get a token

In a service app on a custom authorization server with one custom scope (https://developer.okta.com/docs/guides/implement-grant-type/clientcreds/main/):

```bash
curl --request POST --url https://acme.okta.com/oauth2/default/v1/token --header 'accept: application/json' --header "authorization: Basic $(printf %s "$CLIENT_ID:$CLIENT_SECRET" | base64 -w0)" --header 'content-type: application/x-www-form-urlencoded' --data 'grant_type=client_credentials&scope=mint' | jq -r .access_token
```

## What it signs

The names and types are the issuer's; the values are examples.

```json
{
  "ver": 1,
  "jti": "AT.0mP4JKAZX1iACIT4vbEDF7LpvDVjxypPMf0D7uX39RE",
  "iss": "https://acme.okta.com/oauth2/default",
  "aud": "api://my-app",
  "cid": "0oa1b2c3d4E5f6G7h8i9",
  "scp": [
    "mint"
  ],
  "sub": "0oa1b2c3d4E5f6G7h8i9",
  "iat": 1790000000,
  "exp": 1790000300
}
```

Worth gating on: `cid`, `sub`, `aud`.
Not read (a list, an object or a boolean; the reader takes top-level strings and whole numbers): `scp`.
The org server's `iss` is the domain alone. What `sub` names (an app or a person) is the administrator's choice. `aud` is set per authorization server, so it names your program and not one action.

## Register its key

A public key, one any program can rely on, is admitted on GitHub's signature: the attester's run of the pinned
rotate workflow with the input `issuer: https://acme.okta.com/oauth2/default` reads the key set over TLS, GitHub signs which key it found, and
the key then waits a day and the guardian's approval. You cannot do that alone; ask for it in an issue. The call it ends in:

```python
from knos.settle.v2 import oidc
ISS = "https://acme.okta.com/oauth2/default"
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
if tok.issuer() != ISSUER_OTHER || tok.issuer_hash() != Some(&hash(b"https://acme.okta.com/oauth2/default").to_bytes()) {
    return Err(ProgramError::InvalidAccountData);
}
let ok = tok.claim("cid").is_some_and(|v| v.is("0oa1b2c3d4E5f6G7h8i9"))
    && tok.claim("sub").is_some_and(|v| v.is("0oa1b2c3d4E5f6G7h8i9"))
    && tok.audience().is_some_and(|a| a.starts_with("my-app"));
if !ok { return Err(ProgramError::InvalidArgument); }
```

The whole program around these lines is [`examples/oidc_gate/template.rs`](../../oidc_gate/template.rs).

## Tested

`tests/test_issuers.py` registers a key for this issuer in the test build of the verifier, verifies a token with exactly
the claims above and reads them back. That token is signed with a test key derived from a fixed seed, not by the issuer:
the test shows the program takes this shape, not that the issuer issued anything.
