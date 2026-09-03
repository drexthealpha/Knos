# Good first issues

Four things Knos does not do today, written out so you can pick one up
without reading the whole codebase first. Each names the file to copy from
and what the pull request needs to contain.

Open an issue for the one you want before you start, so two people do not
write the same parser — which is, as it happens, the problem this project
exists to solve.

---

## 1. `Read Codex CLI session history`

**Labels:** `good first issue`, `adapter`

Knos reads Claude Code transcripts and Cursor's history. It reads neither
Codex nor Gemini CLI, so a decision made in either is invisible to every
other agent — which is the whole point of the tool. This issue is Codex
only; Gemini CLI is issue 2, and they are separate parsers with separate
file formats, so they are separate pull requests.

`src/knos/sessions.py` has both existing readers. `read_claude` is the one to
copy: it finds the transcript folder, filters to folders that could concern
this repo, and yields `Turn(client, session, role, text, when, cwd)`. About
40 lines.

Needed in the PR:
- Where Codex stores history, per OS, with a link to its docs.
- One test like `test_a_session_started_above_the_repo_is_still_found`,
  building a throwaway history directory rather than reading yours.
- Confirmation the per-repo filter works, so one project's sessions never
  answer another project's questions.
- A row changed from `no` to `yes` in the README coverage table, because that
  table is the honest count and must stay honest.

---

## 2. `Read Gemini CLI session history`

**Labels:** `good first issue`, `adapter`

The same shape as issue 1, for Gemini CLI. Separate parser, separate file
format, separate pull request — take either one without waiting for the
other.

`read_claude` in `src/knos/sessions.py` is again the one to copy, and the
same three things are needed in the PR: where Gemini CLI stores history per
OS with a link to its docs, one test that builds a throwaway history
directory, and the README coverage row flipped to `yes`.

---

## 3. `knos status does not say which agents have knos wired`

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

## 4. `A claim on a path should cover the files under it`

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
