# knos-oidc-rotate

Two workflows that the [Knos](https://github.com/drexthealpha/Knos) programs on Solana name by commit sha. A commit
sha fixes a file's content, so what these workflows do cannot be changed without the programs refusing the result.

## [`rotate.yml`](.github/workflows/rotate.yml): issuer keys

knos-oidc verifies GitHub Actions and GitLab CI tokens on chain, and tokens of any other RS256 issuer. It has to learn
the keys those issuers sign with. This workflow reads an issuer's public key set on a GitHub-hosted runner and asks
GitHub to sign a token naming each key's hash. A key reaches the program only on such a token, signed by a GitHub key
it already trusts.

- With no input it reads GitHub's and GitLab's key sets. The token's audience is
  `knos-oidc:key:<issuer id>:<sha256 of the key's modulus, hex>`.
- With the input `issuer` (an `https://` URL, written as the issuer writes `iss`) it reads that issuer's key set
  instead. The audience is `knos-oidc:ikey:<sha256 of the issuer's URL, hex>:<sha256 of the key's modulus, hex>`, and
  each comment that carries tokens begins with a line `knos-issuer: <url>`. The job fetches
  `<issuer>/.well-known/openid-configuration` over TLS, checks that its `issuer` is that URL, then fetches the
  `jwks_uri` named there, which must be on the same host. It follows no redirect and attests at most 20 keys.
- The caller can name an issuer and nothing else. The workflow has no checkout and no secret, and the hash of every key
  it attests comes from a key set the job fetched itself.
- The first deployment (immutable) accepts the token from any repository that calls this file at the pinned commit.
- The second deployment also requires GitHub's signature to say the run happened in a repository of this account
  (`repository_id` and `repository_owner_id`), then holds the key for a day in public view, needs the guardian's
  approval, and lets every key expire unless this workflow names it again. The guardian can remove a key and can
  never add one. A new issuer, too, enters only through a run in one of this account's repositories.

### Keeping a key alive from your own repository

Anyone can refresh a key that is already registered, so keys do not depend on one account's schedule. Start a run by
hand (`workflow_dispatch`) of a workflow in a repository of your own that calls `rotate.yml` at the commit knos-oidc
pins. The program accepts such a run only if it is yours (you started it, in a repository you own) and ran on a
GitHub-hosted runner. It can only refresh: it cannot register a key. Issues must be turned on in that repository (a
fork has them off), because the tokens are posted there as comments for any relayer to carry.

```yaml
# .github/workflows/refresh-keys.yml in any repository you own
on:
  workflow_dispatch:
    inputs: { issuer: { description: "https URL of the issuer, or empty for GitHub and GitLab", required: false, type: string, default: "" } }
permissions: {}
jobs:
  refresh:
    permissions: { id-token: write, issues: write }
    uses: drexthealpha/knos-oidc-rotate/.github/workflows/rotate.yml@<the commit knos-oidc pins>
    with: { issuer: "${{ inputs.issuer }}" }
```

## [`claim.yml`](.github/workflows/claim.yml): where an account is paid

A GitHub account names the Solana address its Knos payments go to by running this file from a repository named
`knos-claim` that it owns. knos-pay accepts the token only from this file at the pinned commit, from a run started
by hand (`workflow_dispatch`). The input `kind` says whose wallet it is:

- `user` (the default): a personal account. The audience is `knos2:bind:<address>`, and the run must have been started
  by the owner of the repository it ran in. Nobody else can get GitHub to sign that for your account.
- `org`: an organisation. The audience is `knos3:bind:<address>`, and the `knos-claim` repository must belong to an
  organisation (its owner is not the person who started the run). **Anyone who can start a workflow by hand in that
  repository can bind the organisation's wallet**, which GitHub gives to everyone with write access to it, and a later
  run replaces the address of an earlier one. Give write access to an organisation's `knos-claim` repository only to
  people it trusts with where its payments go.

```yaml
# .github/workflows/claim.yml in <you>/knos-claim
on:
  workflow_dispatch:
    inputs:
      address: { description: Solana address, required: true, type: string }
      kind: { description: "user for a personal account, org for an organisation", required: false, type: choice, options: [user, org], default: user }
permissions: {}
jobs:
  claim:
    permissions: { id-token: write, issues: write }
    uses: drexthealpha/knos-oidc-rotate/.github/workflows/claim.yml@<the commit knos-pay pins>
    with: { address: "${{ inputs.address }}", kind: "${{ inputs.kind }}" }
```

Neither workflow takes a secret. Both post the tokens in public: each names one key hash or one address and nothing
else, and a relayer who carries it only pays the fee.
