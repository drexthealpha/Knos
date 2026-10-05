# Issuers: the same verifier, ten sources of identity

`knos-oidc` verifies an RS256 token whoever signed it. Each folder here is one issuer: the documented way to get a
token there, the claims it signs, which of them a program can gate on, the call that registers its key, and the lines
of Rust that gate on it. [docs/VERIFIER.md](../../docs/VERIFIER.md) is the one page and the table;
[`issuers.json`](issuers.json) is the same table for a machine.

| issuer | verified by `knos-oidc` |
|---|---|
| [GitHub Actions](github/README.md) | yes |
| [GitLab CI (gitlab.com)](gitlab/README.md) | yes |
| [Google Cloud](google/README.md) | yes |
| [Microsoft Entra ID](entra/README.md) | yes |
| [AWS, IAM outbound identity federation](aws/README.md) | in part: only a token asked for with RS256 (AWS recommends ES384) |
| [Kubernetes service account tokens](kubernetes/README.md) | in part: RS256 clusters, and only `sub` can be read |
| [Buildkite](buildkite/README.md) | yes |
| [CircleCI](circleci/README.md) | yes |
| [Okta](okta/README.md) | yes |
| [Auth0](auth0/README.md) | yes |

"Verified" means the program takes the format: RS256 under a 2048- or 4096-bit key. `tests/test_issuers.py` verifies
a token of each issuer's shape in the test build of the verifier, and every one of those tokens is signed with a test
key, not by the issuer. The claim shapes were read from each issuer's documentation, and the key sizes from its
published key set, on 2026-10-05. The same test refuses a key used under another issuer's URL, an RS256 key of 1024
or 3072 bits, and ES256, ES384 and PS256 tokens.

These examples are Knos's own. No program outside this repository is known to read a token yet.
