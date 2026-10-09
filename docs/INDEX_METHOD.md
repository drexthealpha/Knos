# Agent pull request count: the method

Version: 1

Frozen on 2026-10-09. `python scripts/backtest.py --check` fails if this file changes while the version above stays 1:
its sha256 is recorded in [backtest.json](backtest.json) (`method`). A change of method is a new version with a new
hash, and the counts made under version 1 stay as they were.

## Population

Pull requests opened by five AI coding agents, found with GitHub's issue search, created 2026-07-03 to 2026-09-30, read
on 2026-10-01 ([agent_pr_ci.json](agent_pr_ci.json), written by `scripts/agent_pr_ci.py`). An agent is told apart by:

| Agent | Search qualifier | Told by |
| --- | --- | --- |
| `copilot` | `author:app/copilot-swe-agent` | the pull request's author is the GitHub App `copilot-swe-agent` (GitHub Copilot's cloud agent) |
| `devin` | `author:app/devin-ai-integration` | the author is the GitHub App `devin-ai-integration` (Devin's default: it opens pull requests as itself) |
| `claude-bot` | `author:app/claude` | the author is the GitHub App `claude` (Claude Code run from GitHub: the Action, or an @claude mention) |
| `claude-code` | `"Generated with Claude Code" in:body -author:app/claude` | the description holds the line "Generated with Claude Code" and the author is not the app `claude` (Claude Code run on a person's machine, under their account) |
| `codex` | `"chatgpt.com/codex/tasks" in:body` | the description holds a `chatgpt.com/codex/tasks` link (the task link Codex's cloud agent writes) |

A person who pastes the line or the link is counted as that agent.

## The claim

A pull request claims passing tests when a line of its description (HTML comments and a quoted original prompt removed)
matches `CLAIM_RE` and not `NONCLAIM_RE` (after `_BOILER_RE` is blanked). An unticked box is no claim; a ticked box is
the agent's claim, template or not.

```
(?:\ball\s+(?:\w+\s+){0,2}tests?\s+(?:are\s+|now\s+)*(?:pass(?:es|ed|ing)?|green)|\btests?\s+(?:are\s+|now\s+|still\s+)*(?:pass(?:es|ed|ing)?|green)\b|\btests?\b[^\n.]{0,40}?\band\s+passing\b|\bCI\b(?:[\s:/,]+(?:is|are|now|run|runs|job|jobs|checks?|build|pipeline|workflows?|all|CD|#?\d+))*[\s:,]+(?:pass(?:es|ed|ing)?|green)\b|\b(?:all\s+(?:CI\s+)?checks?|(?:CI\s+)?checks)\s+(?:are\s+|have\s+)?(?:pass(?:es|ed|ing)?|green)\b|\bpass(?:es|ed|ing)?\s+all\s+(?:\w+\s+){0,2}(?:tests|checks|CI)\b|`[^`\n]*test[^`\n]*`\s*(?:[-:—]\s*)?(?:all\s+)?(?:pass(?:es|ed|ing)?|green)\b|\b\d[\d,]*\s*(?:/\s*\d[\d,]*\s*)?(?:\w+\s+){0,2}passed\b|✅\s*[^\n]{0,40}?\btests?\b|\btests?\b[^\n]{0,30}?✅)
```

```
^[ \t]*(?:>[ \t]*)*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+)+\[ \](?:[ \t]|$)|\b(ensure|make sure|verify that|should|would|will|to confirm|until|once|if|before|whether|need|needs|must|expect|expected|todo|not|fail|fails|failing|failed|failure|failures|errors?|except|unless|pending|flaky|skip|red|broken)\b|n't\b
```

```
\*\*Your PR cannot be merged unless tests pass\*\*|\bfail[- ](?:closed|safe|fast|open)\b|\b0 failed\b
```

## The checks

Read at the head commit when the pull request was read. Check runs whose name matches `AGENT_RUN_RE` (the agent's own
session) are left out:

```
^(copilot|claude|claude[-_ ]?(code|review|code[-_ ]review|pr[-_ ]review)|codex|devin)$
```

A pull request is counted when its CI had finished (class `failed`, `passed` or `other`) and its merge state is known.

- `any_check_failed`: a check run concluded failure, timed_out or startup_failure, or a commit status is failure or error.
- `test_or_build_check_failed` (the strict count): a failed check whose name matches `TESTISH_RE` and not `ANCILLARY_RE`.

```
test|build|compil|\bci\b|unit|integration|e2e|pytest|jest|vitest|lint|clippy|rustfmt|fmt|typecheck|tsc|linux|windows|macos|ubuntu|cargo|gradle|maven|mvn|smoke|julia|python|node|run:|benchmark|analy[sz]e
```

```
vercel|netlify|cloudflare|workers builds|deploy|publish|label|\bcla\b|metadata|commitlint|contributor|review|lighthouse|snyk|codecov|sonar|security|audit|title|changelog|governance|evidence|non-empty|gate|lifecycle|compliance|aegis|ci-success
```

## The counts

Denominator: the merged pull requests among those counted (241). Shares carry a 95% Wilson interval.

## The second reading

Every pull request in either numerator is read again by hand on its github.com page, and the result is written to
[index_review.json](index_review.json); the recorded scan is never edited. A pull request leaves the reviewed count when:

- R1: it is not merged when read again;
- R2: it was merged into a branch other than the repository's default branch;
- R3: its claim does not cover the check that failed (a template box limited to required checks when the failed check
  is not required; a box about manual tests; a description that itself reports the failing job);
- R4: the page read again shows every check passed and none failed, so the recorded failure cannot be confirmed;
- R5: its page cannot be read.

The pull requests with no failed check are not read again, so the denominator stays 241 and the review can only lower
the counts. The reviewed counts lead; the recorded ones are stated beside them.
