# Auth0

**Supported.** RS256, the default; two 2048-bit keys. A tenant set to HS256 or PS256 is not verified. Key sizes read from the issuer's key set on 2026-10-05 (at `https://auth0.auth0.com/.well-known/jwks.json`).

| | |
|---|---|
| `iss` | `https://<tenant domain>/` |
| key set | `<iss>.well-known/jwks.json` |
| claims, from | https://auth0.com/docs/secure/tokens/access-tokens/access-token-profiles |

## Get a token

In a machine-to-machine application authorised for the API `my-app` (https://auth0.com/docs/get-started/authentication-and-authorization-flow/client-credentials-flow/call-your-api-using-the-client-credentials-flow):

```bash
curl --request POST --url 'https://acme.us.auth0.com/oauth/token' --header 'content-type: application/x-www-form-urlencoded' --data grant_type=client_credentials --data client_id=$CLIENT_ID --data client_secret=$CLIENT_SECRET --data audience=my-app | jq -r .access_token
```

## What it signs

The names and types are the issuer's; the values are examples.

```json
{
  "iss": "https://acme.us.auth0.com/",
  "sub": "Zk3mPq7RtXw2Yb9Lc4Nd8Vf1Hg6Js0Ae@clients",
  "aud": "my-app",
  "azp": "Zk3mPq7RtXw2Yb9Lc4Nd8Vf1Hg6Js0Ae",
  "scope": "mint",
  "gty": "client-credentials",
  "iat": 1790000000,
  "exp": 1790000300
}
```

Worth gating on: `sub`, `azp`, `aud`.
Every claim above is a top-level string or whole number, so each can be read.
The final slash of `iss` is part of it. `aud` can be a list: then it is not read. Access tokens last 86,400 seconds by default (https://auth0.com/docs/secure/tokens/access-tokens/update-access-token-lifetime), the longest the verifier takes: set a shorter lifetime.

## Register its key

A public key (one any program can rely on) needs GitHub's signature first. Knos's pinned rotate workflow, run
with the input `issuer: https://acme.us.auth0.com/`, fetches the issuer's key set over HTTPS, and GitHub
signs which key it found. The key then waits one day and needs the guardian's approval (the guardian is a key that
can approve or revoke keys; one person holds it today). You cannot do this alone: ask for it in an issue on
drexthealpha/Knos. The last step is this call:

```python
from knos.settle.v2 import oidc
ISS = "https://acme.us.auth0.com/"
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
if tok.issuer() != ISSUER_OTHER || tok.issuer_hash() != Some(&hash(b"https://acme.us.auth0.com/").to_bytes()) {
    return Err(ProgramError::InvalidAccountData);
}
let ok = tok.claim("sub").is_some_and(|v| v.is("Zk3mPq7RtXw2Yb9Lc4Nd8Vf1Hg6Js0Ae@clients"))
    && tok.claim("azp").is_some_and(|v| v.is("Zk3mPq7RtXw2Yb9Lc4Nd8Vf1Hg6Js0Ae"))
    && tok.audience().is_some_and(|a| a.starts_with("my-app"));
if !ok { return Err(ProgramError::InvalidArgument); }
```

The whole program around these lines is [`examples/oidc_gate/template.rs`](../../oidc_gate/template.rs).

## Tested

`tests/test_issuers.py` registers a key for this issuer in the test build of the verifier, verifies a token with exactly
the claims above and reads them back. That token is signed with a test key derived from a fixed seed, not by the issuer.
The test shows the verifier accepts a token of this shape. It does not show the issuer ever issued one.
