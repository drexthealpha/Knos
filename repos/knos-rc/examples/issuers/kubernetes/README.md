# Kubernetes service account tokens (EKS, GKE, self-managed)

**Supported in part.** RS256 clusters only (a cluster may sign ES256, ES384 or ES512). `aud` is a list, so only `sub` can be gated on.

| | |
|---|---|
| `iss` | `https://oidc.eks.<region>.amazonaws.com/id/<cluster id>` |
| key set | `<iss>/openid/v1/jwks on the API server; on EKS <iss>/keys` |
| claims, from | https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/ |

## Get a token

In anyone allowed to create tokens for the service account; a pod reads a projected token from its volume:

```bash
kubectl create token build-robot --audience my-app --duration 10m
```

## What it signs

The names and types are the issuer's; the values are examples.

```json
{
  "aud": [
    "my-app"
  ],
  "iss": "https://oidc.eks.us-west-2.amazonaws.com/id/8EBD0000000000000000000000BAE",
  "jti": "aed34954-b33a-4142-b1ec-389d6bbb4936",
  "kubernetes.io": {
    "namespace": "my-namespace",
    "node": {
      "name": "my-node",
      "uid": "646e7c5e-32d6-4d42-9dbd-e504e6cbe6b1"
    },
    "pod": {
      "name": "my-pod",
      "uid": "5e0bd49b-f040-43b0-99b7-22765a53f7f3"
    },
    "serviceaccount": {
      "name": "my-serviceaccount",
      "uid": "14ee3fa4-a7e2-420f-9f9a-dbc4507c3798"
    }
  },
  "sub": "system:serviceaccount:my-namespace:my-serviceaccount",
  "iat": 1790000000,
  "exp": 1790000300
}
```

Worth gating on: `sub`.
Not read (a list, an object or a boolean; the reader takes top-level strings and whole numbers): `aud`, `kubernetes.io`.
The `iss` shown is EKS's; elsewhere it is the cluster's `--service-account-issuer`. With no readable audience a token cannot be bound to your program or to one action: any token of that service account passes. EKS changes its signing key every seven days (https://docs.aws.amazon.com/eks/latest/userguide/irsa-fetch-keys.html), and each new key waits a day here. A cluster whose issuer is not a public https URL can only be a private key.

## Register its key

A public key (one any program can rely on) needs GitHub's signature first. Knos's pinned rotate workflow, run
with the input `issuer: https://oidc.eks.us-west-2.amazonaws.com/id/8EBD0000000000000000000000BAE`, fetches the issuer's key set over HTTPS, and GitHub
signs which key it found. The key then waits one day and needs the guardian's approval (the guardian is a key that
can approve or revoke keys; one person holds it today). You cannot do this alone: ask for it in an issue on
drexthealpha/Knos. The last step is this call:

```python
from knos.settle.v2 import oidc
ISS = "https://oidc.eks.us-west-2.amazonaws.com/id/8EBD0000000000000000000000BAE"
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
if tok.issuer() != ISSUER_OTHER || tok.issuer_hash() != Some(&hash(b"https://oidc.eks.us-west-2.amazonaws.com/id/8EBD0000000000000000000000BAE").to_bytes()) {
    return Err(ProgramError::InvalidAccountData);
}
let ok = tok.claim("sub").is_some_and(|v| v.is("system:serviceaccount:my-namespace:my-serviceaccount"));
if !ok { return Err(ProgramError::InvalidArgument); }
```

The whole program around these lines is [`examples/oidc_gate/template.rs`](../../oidc_gate/template.rs).

## Tested

`tests/test_issuers.py` registers a key for this issuer in the test build of the verifier, verifies a token with exactly
the claims above and reads them back. That token is signed with a test key derived from a fixed seed, not by the issuer.
The test shows the verifier accepts a token of this shape. It does not show the issuer ever issued one.
