# knos-workflows

The workflows that [Knos](https://github.com/drexthealpha/Knos) bounties pin by commit. A comment funds an issue,
and the pull request that closes it is paid from money held on Solana when GitHub itself signs the facts. A bounty on
chain names this repository and one commit of it: the commit its `fund.yml` ran at. Only `prove.yml` of this
repository at that same commit can pay it.

| File | Called for | Runs |
|---|---|---|
| `.github/workflows/fund.yml` | a `/knos` comment, or a new issue that funds itself; in an organisation's attestor repository, a run by hand or a timer | `knos command` |
| `.github/workflows/prove.yml` | a merge, a run started by hand, `/knos settle`, and the review after the check; in an attestor repository, a timer | `knos settle`, `knos review`, `knos proof judge` |
| `.github/workflows/check.yml` | every pull request (optional, read-only) | `knos check` |
| `.github/workflows/attest.yml` | a seller, by hand, after a merge: GitHub signs that a work order's terms were met; a buyer, by hand: one evaluation for `knos_meter` (kind `eval`, posted as `knos-eval:`) | `knos attest` |

Call them by a full commit sha, never by a branch or a tag. The first three take no inputs; `attest.yml` takes a
repository, a pull request, an order, a kind and optional payees, which name facts and never code. Every job installs
knos 0.4.1 from PyPI, as exactly that release, so a caller cannot change which code judges.

The jobs that sign (`fund.yml`, `settle` and `attest` in `prove.yml`, and `attest.yml`) install from a list in which every file is
named by its sha256, `uv pip install --require-hashes`: that list is written into the workflow and is also
`requirements/sign.txt` here, so this commit names the hash of everything they install.

The files to copy into your repository (`knos.yml`, and optionally `knos-check.yml`; for private repositories, `knos-attestor.yml` in one
repository of the organisation) are in
[drexthealpha/Knos/examples](https://github.com/drexthealpha/Knos/tree/main/examples). Their comments say what each
trigger does and what the file can and cannot do in your repository.

Nothing is edited here. These files are copied from `.github/workflows/` in drexthealpha/Knos at a release, where they
are tested. In a checkout of that repository, `python scripts/pinned_workflows.py check <a checkout of this one>`
shows that this copy is the same, byte for byte.
