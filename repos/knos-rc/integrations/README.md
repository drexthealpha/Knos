# Integrations

What a bounty platform, a work platform or any repository can take from Knos and use. The research behind it and the table of
platforms are in [`docs/reference/INTEGRATIONS.md`](../docs/reference/INTEGRATIONS.md).

| Folder | What |
| --- | --- |
| [`../.github/actions/knos-verify`](../.github/actions/knos-verify/action.yml) | the action: one step, a verdict on a pull request from GitHub's record of its checks |
| [`workflows/knos-verify.yml`](workflows/knos-verify.yml) | a workflow that uses it, to copy into `.github/workflows/` |
| [`webhook/`](webhook/README.md) | `verify(evidence, jwks)`: check a Knos receipt offline, in Python or TypeScript, with no dependency |
| [`badge/`](badge/README.md) | "paid on proof" beside a bounty: the picture and the link |

The action's verdict, as its `verdict` output and in the file its `json` output names:

    {"schema":"knos.verify/1","knos":"<version>","pr":"octo/widgets#7","head":"<sha>","commit":"<sha>","at":"head",
     "claim":{"verdict":"true","said":"...","claims":["tests pass"]},"checks":{"test":"passed","lint":"passed"},
     "reasons":[],"passed":true,"untrusted":{"failed_checks":[]}}

`checks` holds one of `passed`, `failed`, `skipped`, `pending`, `absent`, `unreadable` for each name asked for.
`passed` is true when no claim in the description is false and every named check passed. Names of checks that
GitHub returned and nobody asked for are only inside `untrusted`: a workflow file wrote them.
