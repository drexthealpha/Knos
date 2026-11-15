# Knos's own runs (never counted)

Files here are runs of `knos reproduce` that Knos made itself, in a repository of `drexthealpha` or started by an
account of `scripts/own_github_ids.json`. **None is a reproduction. None is counted. None moves a capability.**

Why they exist: a stranger's path has five steps (the report, GitHub's signature for its hash, the second workflow,
the file, the check). Every step refuses Knos's own account, so that path had never been run to its end. Knos's own
run now completes and lands here, so a break is found before a stranger meets it.

**This folder holds 0 files.** The first is filed by the release run (docs/reference/REPRODUCE.md, "Knos's own run").

- Every count of outside reproductions reads `reproductions/*.json` and no deeper.
- `knos.reproduce.verified(..., ours=True)` accepts here only a run that is Knos's own, with GitHub's signature over
  the report's hash, and gives it no capability. Someone else's file placed here is refused.
- A file of an own run placed directly under `reproductions/` is refused, as before.
