# The verifier: any RS256 workload identity, checked on Solana

`knos-oidc` is a Solana program that checks the RS256 signature of an OpenID Connect token on chain and leaves the
issuer's claims in an account any program can read. It is not a GitHub feature: GitHub Actions is one issuer, and the
same three calls serve GitLab CI, a cloud's workload identity, another CI system or a company's identity provider.

| | |
|---|---|
| program (devnet) | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` (`knos-oidc`, second deployment; upgradeable only through a multisig with a public 48-hour delay) |
| it takes | RS256, a 2048- or 4096-bit key (no other size: 1024 and 3072 are refused), a token of at most 8,192 bytes, an `exp` at most a day ahead |
| it does not take | ES256, ES384, ES512, PS256, HS256, EdDSA |
| who reads it today | Knos's own programs and examples. No program outside this repository is known to read it yet |

## The three calls

**1. Register an issuer's key, by the issuer's URL.** A key is the modulus `n` of one RS256 key in the issuer's key
set, filed under the issuer's `iss`. Two ways, and they are not the same promise:

```python
from knos.settle.v2 import oidc            # JavaScript: verifier(program) in sdk/settle, the same names in camelCase
ISS = "https://accounts.google.com"
# a public key: GitHub signed that the pinned rotate workflow found `n` at ISS. Anyone may send this, but only the
# attester's run counts, and the key then waits a day and the guardian's approval. Ask for an issuer in an issue.
ixs = [oidc.register_issuer_key_ix(payer, ISS, n, attest, attest_key), oidc.key_params_ix(payer, ISS, n)]
# a private key: your wallet says so, now, and nobody checks it. Every token it verifies carries your wallet's address.
ixs = [oidc.register_private_key_ix(wallet, ISS, n), oidc.key_params_ix(wallet, ISS, n, registrant=wallet)]
```

GitHub Actions and gitlab.com have numbers of their own (0 and 1) and need no call from you. Every key expires 30
days after it was last attested; `knos keys` prints the keys the verifier holds now.

**2. Verify a token.** Anyone can carry a token to the chain; the account it is verified in belongs to whoever paid.

```python
tid = oidc.token_id(jwt)
write = oidc.write_ixs(payer, tid, jwt)                                   # the token's bytes, 880 per instruction
steps = [oidc.step_ix(payer, tid, oidc.key_pda(ISS, n), squarings) for squarings in oidc.step_plan(n.bit_length())]
token_account = oidc.token_pda(payer, tid)                                # VERIFIED after the last step
```

The signature check is two `Step` transactions under a 2048-bit key (six under a 4096-bit key). The relay in this
repository sends a whole token of up to about 3,700 bytes in two transactions where 4,096-byte transactions are
accepted, and otherwise the `Write`s first ([OIDC.md](OIDC.md), "Put a token on chain"; [BENCH.md](BENCH.md)).

**3. Read it from your program**, with [`knos-oidc-interface`](../crates/knos-oidc-interface) (no dependency, no CPI):

```rust
let tok = Token::read(&token.owner.to_bytes(), &token.try_borrow_data()?, now).map_err(|e| ProgramError::Custom(e.code()))?;
tok.check_key(&key.key.to_bytes(), &key.owner.to_bytes(), &key.try_borrow_data()?, now).map_err(|e| ProgramError::Custom(e.code()))?;
let google = tok.issuer() == ISSUER_OTHER && tok.issuer_hash() == Some(&hash(b"https://accounts.google.com").to_bytes());
if !google || !tok.claim("sub").is_some_and(|v| v.is(SERVICE_ACCOUNT)) || !tok.audience().is_some_and(|a| a.starts_with("my-app:")) {
    return Err(ProgramError::InvalidArgument);
}
```

The program to copy is [`examples/oidc_gate/template.rs`](../examples/oidc_gate/template.rs); its
[README](../examples/oidc_gate/README.md) has the steps and the `cargo` commands.

## Issuers

Each row was read on the web on 2026-10-05: the claims from the linked page, the key sizes from the issuer's
published key set. "Gate on" lists claims the reader can read: top-level strings and whole numbers. A list, an
object or a boolean is not read. Each issuer has an example in [`examples/issuers`](../examples/issuers), and
`tests/test_issuers.py` verifies a token of each shape in the test build of the verifier. Those tokens are signed
with a test key, not by the issuer, and "verified here" means the program takes the format. This release registers
no key on devnet for any issuer below GitLab's row; `knos keys` prints the keys the verifier holds.

| issuer | `iss` | signs with | verified here | gate on | not read | claims read on |
|---|---|---|---|---|---|---|
| [GitHub Actions](../examples/issuers/github/README.md) | `https://token.actions.githubusercontent.com` | RS256; four 2048-bit | yes | `repository_id`, `repository_owner_id`, `job_workflow_ref`, `job_workflow_sha`, `ref`, `sha`, `event_name`, `runner_environment`, `aud` |  | [2026-10-05](https://docs.github.com/en/actions/reference/security/oidc) |
| [GitLab CI (gitlab.com)](../examples/issuers/gitlab/README.md) | `https://gitlab.com` | RS256; one 4096-bit, two 2048-bit | yes | `project_id`, `namespace_id`, `ref_path`, `ref_protected`, `ci_config_ref_uri`, `ci_config_sha`, `sha`, `runner_environment`, `aud` | `groups_direct` | [2026-10-05](https://docs.gitlab.com/ci/secrets/id_token_authentication/) |
| [Google Cloud (service account and workload ID tokens)](../examples/issuers/google/README.md) | `https://accounts.google.com` | RS256; two 2048-bit | yes | `sub`, `email`, `azp`, `aud` | `email_verified` | [2026-10-05](https://docs.cloud.google.com/docs/authentication/get-id-token) |
| [Microsoft Entra ID (app and managed identity tokens)](../examples/issuers/entra/README.md) | `https://login.microsoftonline.com/<tenant id>/v2.0` | RS256; seven 2048-bit | yes | `tid`, `oid`, `azp`, `aud` | `roles` | [2026-10-05](https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference) |
| [AWS (IAM outbound identity federation)](../examples/issuers/aws/README.md) | `https://<account's id>.tokens.sts.global.api.aws` | RS256 on request; key size not measured | in part: RS256 only when asked for: AWS recommends ES384, which is not verified. The RSA key size is not in AWS's documentation and was not measured (the issuer is per account). | `sub`, `aud` | `https://sts.amazonaws.com/` | [2026-10-05](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_outbound_token_claims.html) |
| [Kubernetes service account tokens (EKS, GKE, self-managed)](../examples/issuers/kubernetes/README.md) | `https://oidc.eks.<region>.amazonaws.com/id/<cluster id>` | RS256, ES256, ES384 or ES512, as the cluster is set; key size per cluster | in part: RS256 clusters only (a cluster may sign ES256, ES384 or ES512). `aud` is a list, so only `sub` can be gated on. | `sub` | `aud`, `kubernetes.io` | [2026-10-05](https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/) |
| [Buildkite](../examples/issuers/buildkite/README.md) | `https://agent.buildkite.com` | RS256; one 2048-bit | yes | `organization_id`, `pipeline_id`, `build_branch`, `build_commit`, `step_key`, `runner_environment`, `aud` |  | [2026-10-05](https://buildkite.com/docs/agent/cli/reference/oidc) |
| [CircleCI](../examples/issuers/circleci/README.md) | `https://oidc.circleci.com/org/<organization id>` | RS256; one 2048-bit | yes | `oidc.circleci.com/project-id`, `oidc.circleci.com/vcs-origin`, `oidc.circleci.com/vcs-ref`, `aud` | `oidc.circleci.com/context-ids`, `oidc.circleci.com/ssh-rerun` | [2026-10-05](https://circleci.com/docs/guides/permissions-authentication/openid-connect-tokens/) |
| [Okta](../examples/issuers/okta/README.md) | `https://<Okta domain>/oauth2/<authorization server id>` | RS256; two 2048-bit | yes | `cid`, `sub`, `aud` | `scp` | [2026-10-05](https://developer.okta.com/docs/api/openapi/okta-oauth/guides/overview/) |
| [Auth0](../examples/issuers/auth0/README.md) | `https://<tenant domain>/` | RS256; two 2048-bit | yes | `sub`, `azp`, `aud` |  | [2026-10-05](https://auth0.com/docs/secure/tokens/access-tokens/access-token-profiles) |

Not verified at all: any issuer that signs only with an elliptic-curve key or with PS256. AWS's default for
outbound federation (ES384) and a Kubernetes cluster with an ECDSA key are the two in this table. For Entra, CircleCI,
Okta and Auth0 the key sizes were read at one tenant or at the shared endpoint each example names, not at yours.

## What it proves, and what it does not

It proves that the issuer's key signed exactly these claims, for this audience, and that the token had not expired
by more than an hour when your program read it. Nothing more.

It does not prove that the claims are true about the world. GitHub signs which workflow file ran at which commit,
not what that workflow read or decided; a cloud signs which service account asked, not what the code behind it
does. It does not make a token single-use (bind it to one action in the audience and record the action), it does
not stop a token minted for another program (require your own audience prefix), and a key the issuer has lost is
trusted until it is revoked or expires. A private key proves only what the wallet that registered it says.
[SECURITY.md](SECURITY.md) has the whole list and [OIDC.md](OIDC.md) the reader's API and the trust root.
