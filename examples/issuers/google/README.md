# Google Cloud (service account and workload ID tokens)

**Supported.** RS256; two 2048-bit keys. Key sizes read from the issuer's key set on 2026-10-05.

| | |
|---|---|
| `iss` | `https://accounts.google.com` |
| key set | `https://www.googleapis.com/oauth2/v3/certs` |
| claims, from | https://docs.cloud.google.com/docs/authentication/get-id-token |

## Get a token

In a VM, Cloud Run service or GKE pod that runs as the service account:

```bash
curl -H "Metadata-Flavor: Google" 'http://metadata/computeMetadata/v1/instance/service-accounts/default/identity?audience=my-app:mint:42'
```

## What it signs

The names and types are the issuer's; the values are examples.

```json
{
  "iss": "https://accounts.google.com",
  "azp": "104029292853099978293",
  "aud": "my-app:mint:42",
  "sub": "104029292853099978293",
  "email": "minter@my-project.iam.gserviceaccount.com",
  "email_verified": true,
  "iat": 1790000000,
  "exp": 1790000300
}
```

Worth gating on: `sub`, `email`, `azp`, `aud`.
Not read (a list, an object or a boolean; the reader takes top-level strings and whole numbers): `email_verified`.
Google signs people's sign-ins under the same issuer: gate on one service account's `sub`, never on the issuer alone. With `format=full` the VM's details are nested under `google` and are not read.

## Register its key

A public key, one any program can rely on, is admitted on GitHub's signature: the attester's run of the pinned
rotate workflow with the input `issuer: https://accounts.google.com` reads the key set over TLS, GitHub signs which key it found, and
the key then waits a day and the guardian's approval. You cannot do that alone; ask for it in an issue. The call it ends in:

```python
from knos.settle.v2 import oidc
ISS = "https://accounts.google.com"
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
if tok.issuer() != ISSUER_OTHER || tok.issuer_hash() != Some(&hash(b"https://accounts.google.com").to_bytes()) {
    return Err(ProgramError::InvalidAccountData);
}
let ok = tok.claim("sub").is_some_and(|v| v.is("104029292853099978293"))
    && tok.claim("email").is_some_and(|v| v.is("minter@my-project.iam.gserviceaccount.com"))
    && tok.claim("azp").is_some_and(|v| v.is("104029292853099978293"))
    && tok.audience().is_some_and(|a| a.starts_with("my-app"));
if !ok { return Err(ProgramError::InvalidArgument); }
```

The whole program around these lines is [`examples/oidc_gate/template.rs`](../../oidc_gate/template.rs).

## Tested

`tests/test_issuers.py` registers a key for this issuer in the test build of the verifier, verifies a token with exactly
the claims above and reads them back. That token is signed with a test key derived from a fixed seed, not by the issuer:
the test shows the program takes this shape, not that the issuer issued anything.
