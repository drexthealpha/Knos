# Reproductions

One JSON file per run of `knos reproduce` that someone outside Knos made in a repository of their own:
`<owner>-<repo>-<run id>.json`, holding the report and the token GitHub signed for it. How to make one (a fork, one button,
one link) and what each check proves: [docs/REPRODUCE.md](../docs/REPRODUCE.md).

**This folder is empty: 0 reproductions. Nobody outside has sent a reproduction yet.** The count of outside
reproductions, wherever Knos states one, is the number of `.json` files here and nothing else. Knos does not add files here: a run in an
account of `scripts/own_github_ids.json`, or in a repository of drexthealpha, is refused by the same check that
accepts everyone else's. So no capability in [docs/capabilities.json](../docs/capabilities.json) is `reproduced`.

Knos's own runs of the same path are kept apart in [`own/`](own/README.md) (0 files today). They are not
reproductions: no count reads that folder, and a file there gives no capability.

A file here is checked three times, never by taking anyone's word:

1. When it arrives, `.github/workflows/reproductions.yml` checks GitHub's signature on the token, that the token's
   audience is `knos-repro:<sha256 of the report>`, that the run is not Knos's own, and that no check failed. It runs
   nothing from the pull request.
2. On every `python scripts/capabilities.py check`, offline, against GitHub's keys as archived in
   `scripts/github_oidc_keys.json`. A file that does not hold fails the check.
3. With `check --rpc`, GitHub is also asked whether it still publishes the key under that id.

A capability moves to `reproduced` only by naming a file here in which a check that supports it passed:
`"reproduced": {"file": "reproductions/<name>.json"}`.

What a file proves: GitHub signed that the run happened in that repository, started by that account, for exactly that
report. What it does not prove: that the account is independent of Knos (only the listed own accounts are refused), or
that the workflow file was the example unchanged (the token names the workflow and its commit, which anyone can read).
