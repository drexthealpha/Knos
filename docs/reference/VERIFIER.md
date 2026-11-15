# The verifier: signed identity tokens, checked on Solana

`knos-oidc` is a Solana program that checks the signature (RS256: RSA with SHA-256) of an OpenID Connect token on chain and leaves the
issuer's claims in an account any program can read.

It is not a GitHub feature: GitHub Actions is one issuer, and the same three calls serve GitLab CI, a cloud's workload identity,
another CI system or a company's identity provider.

| | |
|---|---|
| program (devnet) | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` (`knos-oidc`, second deployment; upgradeable only through a multisig with a public 8-day delay) |
| it takes | RS256, a 2048- or 4096-bit key (no other size: 1024 and 3072 are refused), a token of at most 8,192 bytes, an `exp` at most a day ahead |
| it does not take | ES384, ES512, PS256, HS256, EdDSA. ES256 (P-256 keys) is live since knos_oidc 2.2 (9 Oct 2026), for tokens small enough for one transaction ([ES256.md](ES256.md)) |
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

**3. Read it from your program**, with [`knos-oidc-interface`](../../crates/knos-oidc-interface) (no extra library, and no call into another program):

```rust
let tok = Token::read(&token.owner.to_bytes(), &token.try_borrow_data()?, now).map_err(|e| ProgramError::Custom(e.code()))?;
tok.check_key(&key.key.to_bytes(), &key.owner.to_bytes(), &key.try_borrow_data()?, now).map_err(|e| ProgramError::Custom(e.code()))?;
let google = tok.issuer() == ISSUER_OTHER && tok.issuer_hash() == Some(&hash(b"https://accounts.google.com").to_bytes());
if !google || !tok.claim("sub").is_some_and(|v| v.is(SERVICE_ACCOUNT)) || !tok.audience().is_some_and(|a| a.starts_with("my-app:")) {
    return Err(ProgramError::InvalidArgument);
}
```

The program to copy is [`examples/oidc_gate/template.rs`](../../examples/oidc_gate/template.rs); its
[README](../../examples/oidc_gate/README.md) has the steps and the `cargo` commands.

## Issuers

Each row was read on the web on 2026-10-05 (Vercel's on 2026-10-06): the claims from the linked page, the key sizes from the issuer's
published key set. "Gate on" lists claims the reader can read: top-level strings and whole numbers. A list, an object or a boolean is
not read.

Each issuer has an example in [`examples/issuers`](../../examples/issuers), and `tests/test_issuers.py` verifies a token of each
shape in the test build of the verifier. Those tokens are signed with a test key, not by the issuer, and "verified here" means the
program takes the format.

This release registers no key on devnet for any issuer below GitLab's row; `knos keys` prints the keys the verifier holds.

| issuer | `iss` | signs with | verified here | gate on | not read | claims read on |
|---|---|---|---|---|---|---|
| [GitHub Actions](../../examples/issuers/github/README.md) | `https://token.actions.githubusercontent.com` | RS256; four 2048-bit | yes | `repository_id`, `repository_owner_id`, `job_workflow_ref`, `job_workflow_sha`, `ref`, `sha`, `event_name`, `runner_environment`, `aud` |  | [2026-10-05](https://docs.github.com/en/actions/reference/security/oidc) |
| [GitLab CI (gitlab.com)](../../examples/issuers/gitlab/README.md) | `https://gitlab.com` | RS256; one 4096-bit, two 2048-bit | yes | `project_id`, `namespace_id`, `ref_path`, `ref_protected`, `ci_config_ref_uri`, `ci_config_sha`, `sha`, `runner_environment`, `aud` | `groups_direct` | [2026-10-05](https://docs.gitlab.com/ci/secrets/id_token_authentication/) |
| [Google Cloud (service account and workload ID tokens)](../../examples/issuers/google/README.md) | `https://accounts.google.com` | RS256; two 2048-bit | yes | `sub`, `email`, `azp`, `aud` | `email_verified` | [2026-10-05](https://docs.cloud.google.com/docs/authentication/get-id-token) |
| [Microsoft Entra ID (app and managed identity tokens)](../../examples/issuers/entra/README.md) | `https://login.microsoftonline.com/<tenant id>/v2.0` | RS256; seven 2048-bit | yes | `tid`, `oid`, `azp`, `aud` | `roles` | [2026-10-05](https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference) |
| [AWS (IAM outbound identity federation)](../../examples/issuers/aws/README.md) | `https://<account's id>.tokens.sts.global.api.aws` | RS256 on request; key size not measured | in part: RS256 only when asked for: AWS recommends ES384, which is not verified. The RSA key size is not in AWS's documentation and was not measured (the issuer is per account). | `sub`, `aud` | `https://sts.amazonaws.com/` | [2026-10-05](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_outbound_token_claims.html) |
| [Kubernetes service account tokens (EKS, GKE, self-managed)](../../examples/issuers/kubernetes/README.md) | `https://oidc.eks.<region>.amazonaws.com/id/<cluster id>` | RS256, ES256, ES384 or ES512, as the cluster is set; key size per cluster | in part: RS256 clusters, and ES256 clusters for small tokens (a cluster may also sign ES384 or ES512). `aud` is a list, so only `sub` can be gated on. | `sub` | `aud`, `kubernetes.io` | [2026-10-05](https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/) |
| [Buildkite](../../examples/issuers/buildkite/README.md) | `https://agent.buildkite.com` | RS256; one 2048-bit | yes | `organization_id`, `pipeline_id`, `build_branch`, `build_commit`, `step_key`, `runner_environment`, `aud` |  | [2026-10-05](https://buildkite.com/docs/agent/cli/reference/oidc) |
| [CircleCI](../../examples/issuers/circleci/README.md) | `https://oidc.circleci.com/org/<organization id>` | RS256; one 2048-bit | yes | `oidc.circleci.com/project-id`, `oidc.circleci.com/vcs-origin`, `oidc.circleci.com/vcs-ref`, `aud` | `oidc.circleci.com/context-ids`, `oidc.circleci.com/ssh-rerun` | [2026-10-05](https://circleci.com/docs/guides/permissions-authentication/openid-connect-tokens/) |
| [Okta](../../examples/issuers/okta/README.md) | `https://<Okta domain>/oauth2/<authorization server id>` | RS256; two 2048-bit | yes | `cid`, `sub`, `aud` | `scp` | [2026-10-05](https://developer.okta.com/docs/api/openapi/okta-oauth/guides/overview/) |
| [Auth0](../../examples/issuers/auth0/README.md) | `https://<tenant domain>/` | RS256; two 2048-bit | yes | `sub`, `azp`, `aud` |  | [2026-10-05](https://auth0.com/docs/secure/tokens/access-tokens/access-token-profiles) |
| [Vercel (deployment OIDC tokens)](../../examples/issuers/vercel/README.md) | `https://oidc.vercel.com/<team slug>` or `https://oidc.vercel.com` | RS256; one 2048-bit | yes | `owner_id`, `project_id`, `environment`, `sub`, `aud` |  | [2026-10-06](https://vercel.com/docs/oidc/reference) |

Not verified: an issuer that signs only with ES384, ES512, EdDSA or PS256, and ES256 tokens too large for one
transaction. AWS's default for outbound federation (ES384) and a Kubernetes cluster with an ES384 or ES512 key are the
two in this table.

For Entra, CircleCI, Okta and Auth0 the key sizes were read at one tenant or at the shared endpoint each example
names, not at yours.

## What each issuer's discovery document publishes

The column "signs with" above came from documentation and key sets. This table is the issuer's own
`/.well-known/openid-configuration`, fetched on 2026-10-06, and its `id_token_signing_alg_values_supported`.

"Accepted today" is about the format the verifier takes (RS256 under a 2048- or 4096-bit key). **No live token of
any issuer in this table was verified**: a row says what a token of that issuer would need, not that one was tried.

| issuer | discovery document | algorithms it lists | key sizes | accepted today |
|---|---|---|---|---|
| GitHub Actions | [token.actions.githubusercontent.com](https://token.actions.githubusercontent.com/.well-known/openid-configuration) | RS256 | 2048 (key set, 2026-10-05) | yes; live tokens of this issuer are what Knos verifies on devnet |
| GitLab.com | [gitlab.com](https://gitlab.com/.well-known/openid-configuration) | RS256 | 4096 and 2048 (key set, 2026-10-05) | yes |
| Google | [accounts.google.com](https://accounts.google.com/.well-known/openid-configuration) | RS256 | 2048 (key set, 2026-10-05) | yes |
| Microsoft Entra ID | [login.microsoftonline.com/common/v2.0](https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration) (the shared endpoint; its `issuer` is `https://login.microsoftonline.com/{tenantid}/v2.0`) | RS256 | 2048 (shared key set, 2026-10-05) | yes |
| Vercel | [oidc.vercel.com](https://oidc.vercel.com/.well-known/openid-configuration) | RS256 | 2048: the one key of [its key set](https://oidc.vercel.com/.well-known/jwks), measured 2026-10-06 | yes |
| Buildkite | `https://agent.buildkite.com/.well-known/openid-configuration` | not read: the host's robots.txt refused Knos's reader | 2048 (key set, 2026-10-05) | yes, by its [documentation](https://buildkite.com/docs/agent/cli/reference/oidc) (RS256) |
| CircleCI | one per organisation: `https://oidc.circleci.com/org/<organization id>/.well-known/openid-configuration` | not read (needs an organisation's id) | 2048 at one organisation (2026-10-05) | yes, by its [documentation](https://circleci.com/docs/guides/permissions-authentication/openid-connect-tokens/) (RS256) |
| AWS, IAM outbound identity federation | one per account: `https://<account's id>.tokens.sts.global.api.aws/.well-known/openid-configuration` | not read (needs an account). [Documentation](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_outbound_token_claims.html): ES384 recommended, RS256 on request | not measured | in part: an RS256 token if its key is 2048 or 4096 bits; **ES384: not yet** |
| Kubernetes (EKS, GKE, self-managed, kind) | one per cluster: `<iss>/.well-known/openid-configuration`, key set at `/openid/v1/jwks` | per cluster. The API server signs RS256, ES256, ES384 or ES512 by the type of its key ([Kubernetes](https://kubernetes.io/docs/reference/access-authn-authz/service-accounts-admin/)) | per cluster; kubeadm's default is RSA-2048 ([kubeadm](https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta4/), `encryptionAlgorithm`) | in part: an RS256 cluster yes; **ES256, ES384, ES512: not yet**. `aud` is a list, which no program on chain reads |
| Fly.io | one per organisation: `https://oidc.fly.io/<org name>/.well-known/openid-configuration` ([Fly.io](https://docs.fly.io/security/openid-connect)) | not read (needs an organisation); the page does not name the algorithm | not measured | not known: no entry in `examples/issuers` until it is measured |

Not yet, for any issuer: ES384, ES512, PS256, EdDSA. The deployed verifier checks RS256 (RSA PKCS#1 v1.5 with
SHA-256) and, for small tokens, ES256 (knos_oidc 2.2, live since 9 Oct 2026; [ES256.md](ES256.md)).

**One issuer that is not a forge was taken end to end in tests, and verified offline once in staging.** `.github/workflows/outcome-k8s.yml` starts a
Kubernetes cluster and has its service-account issuer sign an evaluation; `scripts/outcome_k8s.py` checks that token
offline by this verifier's rule and carries it to devnet under a private key.

Here that is tested with a token of a
projected service-account token's shape, signed by a test key (`tests/test_outcome_k8s.py`, in the test build of the
verifier).

A kind cluster's token was verified offline in run 38701801687 of drexthealpha/Knos (branch knos-0.3.34); the
devnet part runs when the release run executes it, and the meter does not count such a token on chain:
[OUTCOMES.md](OUTCOMES.md#a-kubernetes-cluster-signs-an-outcome).

## What it proves, and what it does not

It proves that the issuer's key signed exactly these claims, for this audience, and that the token had not expired
by more than an hour when your program read it. Nothing more.

It does not prove that the claims are true about the world. GitHub signs which workflow file ran at which commit,
not what that workflow read or decided; a cloud signs which service account asked, not what the code behind it
does.

It does not make a token single-use (bind it to one action in the audience and record the action), it does not
stop a token minted for another program (require your own audience prefix), and a key the issuer has lost is
trusted until it is revoked or expires.

A private key proves only what the wallet that registered it says. [SECURITY.md](SECURITY.md) has the whole list
and [OIDC.md](OIDC.md) the reader's API and the trust root.

## Sources: signed results from systems other than CI

**In plain words.** Knos counts work when a trusted system signs a result. Until now that system was CI (the
automatic checks that run on each change). This page is about other systems. Knos takes a result from one only if
anyone can check the signature. A new word? See [the word list](../WORDS.md).

### The one rule

A result is neutral evidence only if a third party can check it. That person needs no secret and no help from us.

- **A public key can do this.** The system signs with a private key (a secret only it holds). It publishes the
  matching public key (a key anyone may hold). Anyone can then check the signature.
- **A shared secret cannot.** Many webhooks (messages one system sends another) are signed with a secret both ends
  hold. This is called an HMAC. It proves the message to the one receiver. It proves nothing to anyone else. The
  receiver holds the secret, so the receiver could have made the message too.

### Which sources can be neutral evidence

| source | how it signs | neutral evidence? | why |
|---|---|---|---|
| GitHub Actions and GitLab sign-in tokens | Public keys in a key list ([GitHub's](https://token.actions.githubusercontent.com/.well-known/jwks), [GitLab's](https://gitlab.com/oauth/discovery/keys)) | yes | The Knos program checks GitHub's on chain today ([OIDC.md](OIDC.md)). GitLab's: tested here, not yet run on gitlab.com. |
| Sigstore build records (npm and GitHub provenance) | A short-lived certificate from Sigstore's authority, and an entry in Rekor, a public log ([Sigstore](https://docs.sigstore.dev/logging/overview/)) | yes | The keys are published. The log is public. **Knos reads these today** (below). |
| npm's own publish record | npm's public key ([npm](https://docs.npmjs.com/generating-provenance-statements)) | could be | A public key, so it can be checked. No adapter reads it yet. |
| GitHub webhooks | HMAC-SHA256 with a shared secret, header `X-Hub-Signature-256` ([GitHub](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)) | no | Only the receiver holds the secret. |
| Stripe webhooks | A secret shared with your endpoint ([Stripe](https://docs.stripe.com/webhooks/signature)) | no | The same reason. |
| Linear webhooks | HMAC-SHA256 with a shared secret ([Linear](https://linear.app/developers/webhooks)) | no | The same reason. |

### The Sigstore adapter

npm and GitHub can publish a build record for a package. It says: "this file was built from this commit, by this
workflow, in this run". The workflow signs it inside GitHub Actions. Sigstore certifies who signed. Rekor records it
in public. The code is [`src/knos/sources/sigstore.py`](../../src/knos/sources/sigstore.py).

It checks five things, with no network:

1. Sigstore's authority issued the signing certificate. The log recorded the entry while the certificate was valid.
2. GitHub Actions vouched for the signer. The build ran on a machine GitHub hosts, not one the owner controls.
3. The statement's signature checks against the certificate.
4. Rekor recorded this exact signature. Rekor's own key signed that record and the tree it sits in.
5. The statement is a build record (SLSA provenance v1). Its repository and commit match the certificate.

The keys come from Sigstore's published key file (its "trusted root"). Knos keeps a copy in
[`src/knos/sources/sigstore_trusted_root.json`](../../src/knos/sources/sigstore_trusted_root.json). The code pins that
copy by its sha256 (a fingerprint of the file). It was taken from Sigstore's key server,
`https://tuf-repo-cdn.sigstore.dev`, on 10 Oct 2026.

If the record matches the order's terms, it becomes one meter line. The line says "accepted". Its artifact is the
commit. Its `evidence` field is the record's sha256. The terms name the repository. They may also name the workflow
file and the built file's digest.

#### What it does not check

- That the key file is still current. Sigstore can change its keys. Copy the new file and change the pin.
- The certificate's own log stamp (a second, separate public log).
- Entries in Rekor's newer log, signed with another kind of key. The adapter refuses them and says why.
- That the build is good. A build record says where and from what a file was built. It says nothing about quality.

#### Tested with real records

The tests use two real records, taken from npm's registry on 10 Oct 2026:

| package | built by | Rekor entry |
|---|---|---|
| `knos-settle` 0.3.25 | this repository's release workflow, commit `095f52ae` | [3177480388](https://search.sigstore.dev/?logIndex=3177480388) |
| `sigstore` 3.0.0 | the `sigstore-js` release workflow, commit `3a57a741` | [139985224](https://search.sigstore.dev/?logIndex=139985224) |

Both are in [`tests/data/sources/`](../../tests/data/sources). [`tests/test_sources.py`](../../tests/test_sources.py)
checks that both pass. It changes one signed part at a time and checks that each change is refused. It checks the
signature maths against OpenSSL. The `knos-settle` record names the same file npm serves: its sha512 equals the
`integrity` value in npm's listing.

#### What this is not

The Knos program on chain does not read these records. A Sigstore record becomes a meter line, counted off chain.
To pay on chain, the order still needs a signed run of the pinned workflow. No outside party sends Knos these records today.

### Write an adapter

An adapter is a class with a `name` and two methods ([`src/knos/sources/__init__.py`](../../src/knos/sources/__init__.py)):

- `fetch(ref)` gets the signed record as bytes. Only this step uses the network.
- `verify(raw)` checks the signature against the issuer's published keys. It returns an `Evidence`, or raises
  `Refused` with the reason in plain words.

`knos.sources.line(evidence, terms)` then makes the meter line. Use it in your own code:

```python
from knos import sources
src = sources.adapter("sigstore")
ev = src.verify(src.fetch("npm:knos-settle@0.3.25"))
row = sources.line(ev, sources.Terms(buyer=1, seller=2, order="ab" * 32, policy="cd" * 32, milestone=1,
                                     rate=5_000_000, repository="https://github.com/drexthealpha/Knos"))
print(row.line())
```

An adapter for a shared-secret webhook will not be accepted. It cannot be neutral evidence.
