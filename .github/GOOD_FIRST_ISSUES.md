# Three issues to file the moment the repo is public

Paste each as a new issue. Titles and labels are given. They are real gaps,
not make-work: each one is something Knos does not do today.

---

## 1. `Read Gemini CLI and Codex session history`

**Labels:** `good first issue`, `adapter`

Knos reads Claude Code transcripts and Cursor's history. It does not read
Gemini CLI or Codex, so a decision made in either is invisible to every other
agent — which is the whole point of the tool.

`src/knos/sessions.py` has both existing readers. `read_claude` is the one to
copy: it finds the transcript folder, filters to folders that could concern
this repo, and yields `Turn(client, session, role, text, when, cwd)`. About
40 lines each.

Needed in the PR:
- Where that client stores history, per OS, with a link to its docs.
- A test like `test_a_session_started_above_the_repo_is_still_found`, building
  a throwaway history directory rather than reading yours.
- Confirmation the per-repo filter works, so one project's sessions never
  answer another project's questions.

---

## 2. `knos status does not say which agents have knos wired`

**Labels:** `good first issue`, `docs`

`knos status` prints what was read, who holds what, and how full the store
is. It does not say which clients are actually connected, so the commonest
failure — installed, but the editor was never restarted — looks identical to
working.

`_already_connected()` in `src/knos/cli.py` already reads every client config
and knows the answer for all four. Print one line per client: connected, or
not connected.

Needed in the PR: a test that writes throwaway configs for two clients, one
with knos and one without, and asserts both are named correctly.

---

## 3. `A claim on a path should cover the files under it`

**Labels:** `good first issue`, `enhancement`

`knos claim "the parser"` matches on word stems, so it holds anything a
question mentions "parser" in. Claiming a *path* — `knos claim src/auth/` —
does not hold questions about `src/auth/tokens.py`, because the stem of a
path segment is not the stem of a filename.

`_same_subject` in `src/knos/mcp.py` compares stem sets. A claim that looks
like a path (contains `/` or matches a tracked file) should also match any
question naming a file beneath it.

Careful: it must not become greedy. `knos claim src/` holding the entire repo
is technically correct and useless. `test_stemming_does_not_make_the_claim_greedy`
in `tests/test_intent.py` is the test to extend.
