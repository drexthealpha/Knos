# Vercel (deployment OIDC tokens)

**Supported.** RS256; one 2048-bit key. Key sizes read from the issuer's key set on 2026-10-06.

| | |
|---|---|
| `iss` | `https://oidc.vercel.com/<team slug> (team issuer mode) or https://oidc.vercel.com (global)` |
| key set | `https://oidc.vercel.com/.well-known/jwks` |
| claims, from | https://vercel.com/docs/oidc/reference |
| discovery document | `https://oidc.vercel.com/.well-known/openid-configuration` listed `RS256` and no other algorithm on 2026-10-06 |

## Get a token

In a Vercel build (the variable VERCEL_OIDC_TOKEN) or a Vercel function (the header x-vercel-oidc-token):

```js
const jwt = await getVercelOidcToken({ audience: "my-app:release" });   // import { getVercelOidcToken } from "@vercel/oidc"
```

## What it signs

The names and types are the issuer's; the values are examples.

```json
{
  "iss": "https://oidc.vercel.com/acme",
  "aud": "my-app:release",
  "sub": "owner:acme:project:acme_website:environment:production",
  "nbf": 1790000000,
  "owner": "acme",
  "owner_id": "team_7Gw5ZMzpQA8h90F832KGp7nwbuh3",
  "project": "acme_website",
  "project_id": "prj_7Gw5ZMBpQA8h9GF832KGp7nwbuh3",
  "environment": "production",
  "iat": 1790000000,
  "exp": 1790000300
}
```

Worth gating on: `owner_id`, `project_id`, `environment`, `sub`, `aud`.
Every claim above is a top-level string or whole number, so each can be read.
`owner` and `project` are names and change when a team or a project is renamed: gate on `owner_id` and `project_id`. In the global issuer mode one `iss` serves every team, so the two ids are the only thing that names yours. The key size was read at the global key set, not at a team's. A build's token lives one hour, a function's two, a development token twelve (the same page).

## Register its key

A public key (one any program can rely on) needs GitHub's signature first. Knos's pinned rotate workflow, run
with the input `issuer: https://oidc.vercel.com/acme`, fetches the issuer's key set over HTTPS, and GitHub
signs which key it found. The key then waits one day and needs the guardian's approval (the guardian is a key that
can approve or revoke keys; one person holds it today). You cannot do this alone: ask for it in an issue on
drexthealpha/Knos. The last step is this call:

```python
from knos.settle.v2 import oidc
ISS = "https://oidc.vercel.com/acme"
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
if tok.issuer() != ISSUER_OTHER || tok.issuer_hash() != Some(&hash(b"https://oidc.vercel.com/acme").to_bytes()) {
    return Err(ProgramError::InvalidAccountData);
}
let ok = tok.claim("owner_id").is_some_and(|v| v.is("team_7Gw5ZMzpQA8h90F832KGp7nwbuh3"))
    && tok.claim("project_id").is_some_and(|v| v.is("prj_7Gw5ZMBpQA8h9GF832KGp7nwbuh3"))
    && tok.claim("environment").is_some_and(|v| v.is("production"))
    && tok.audience().is_some_and(|a| a.starts_with("my-app"));
if !ok { return Err(ProgramError::InvalidArgument); }
```

The whole program around these lines is [`examples/oidc_gate/template.rs`](../../oidc_gate/template.rs).

## Tested

`tests/test_issuers.py` registers a key for this issuer in the test build of the verifier, verifies a token with exactly
the claims above and reads them back. That token is signed with a test key derived from a fixed seed, not by the issuer.
The test shows the verifier accepts a token of this shape. It does not show the issuer ever issued one.
