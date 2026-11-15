# Buildkite

**Supported.** RS256; one 2048-bit key. Key sizes read from the issuer's key set on 2026-10-05.

| | |
|---|---|
| `iss` | `https://agent.buildkite.com` |
| key set | `https://agent.buildkite.com/.well-known/jwks` |
| claims, from | https://buildkite.com/docs/agent/cli/reference/oidc |

## Get a token

In a step of a Buildkite job:

```bash
buildkite-agent oidc request-token --audience my-app:release:v1.2.0 --lifetime 300
```

## What it signs

The names and types are the issuer's; the values are examples.

```json
{
  "iss": "https://agent.buildkite.com",
  "sub": "organization:acme-inc:pipeline:super-duper-app:ref:refs/heads/main:commit:9f3182061f1e2cca4702c368cbc039b7dc9d4485:step:build",
  "aud": "my-app:release:v1.2.0",
  "jti": "0184990a-4550-7000-8000-000000000001",
  "organization_id": "0184990a-477b-4fa8-9968-496074483cec",
  "organization_slug": "acme-inc",
  "pipeline_id": "0184990a-4782-42b5-afc1-16715b10b1b0",
  "pipeline_slug": "super-duper-app",
  "build_id": "019583d7-3737-4e38-af67-f7cc356bd580",
  "build_number": 1,
  "build_branch": "main",
  "build_commit": "9f3182061f1e2cca4702c368cbc039b7dc9d4485",
  "step_key": "build_step",
  "job_id": "0184990a-477b-4fa8-9968-496074483cee",
  "agent_id": "0184990a-4782-42b5-afc1-16715b10b8ff",
  "runner_environment": "self-hosted",
  "build_source": "webhook",
  "iat": 1790000000,
  "exp": 1790000300
}
```

Worth gating on: `organization_id`, `pipeline_id`, `build_branch`, `build_commit`, `step_key`, `runner_environment`, `aud`.
Every claim above is a top-level string or whole number, so each can be read.
One issuer for every organisation: always gate on `organization_id` and `pipeline_id`.

## Register its key

A public key (one any program can rely on) needs GitHub's signature first. Knos's pinned rotate workflow, run
with the input `issuer: https://agent.buildkite.com`, fetches the issuer's key set over HTTPS, and GitHub
signs which key it found. The key then waits one day and needs the guardian's approval (the guardian is a key that
can approve or revoke keys; one person holds it today). You cannot do this alone: ask for it in an issue on
drexthealpha/Knos. The last step is this call:

```python
from knos.settle.v2 import oidc
ISS = "https://agent.buildkite.com"
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
if tok.issuer() != ISSUER_OTHER || tok.issuer_hash() != Some(&hash(b"https://agent.buildkite.com").to_bytes()) {
    return Err(ProgramError::InvalidAccountData);
}
let ok = tok.claim("organization_id").is_some_and(|v| v.is("0184990a-477b-4fa8-9968-496074483cec"))
    && tok.claim("pipeline_id").is_some_and(|v| v.is("0184990a-4782-42b5-afc1-16715b10b1b0"))
    && tok.claim("build_branch").is_some_and(|v| v.is("main"))
    && tok.claim("build_commit").is_some_and(|v| v.is("9f3182061f1e2cca4702c368cbc039b7dc9d4485"))
    && tok.claim("step_key").is_some_and(|v| v.is("build_step"))
    && tok.claim("runner_environment").is_some_and(|v| v.is("self-hosted"))
    && tok.audience().is_some_and(|a| a.starts_with("my-app"));
if !ok { return Err(ProgramError::InvalidArgument); }
```

The whole program around these lines is [`examples/oidc_gate/template.rs`](../../oidc_gate/template.rs).

## Tested

`tests/test_issuers.py` registers a key for this issuer in the test build of the verifier, verifies a token with exactly
the claims above and reads them back. That token is signed with a test key derived from a fixed seed, not by the issuer.
The test shows the verifier accepts a token of this shape. It does not show the issuer ever issued one.
