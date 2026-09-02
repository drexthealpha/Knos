---
name: Something is wrong
about: Knos answered wrongly, refused when it should not have, or fell over
labels: bug
---

**What you ran**

```
knos ...
```

**What you expected, and what happened instead**

**Which client** — Claude Code / Cursor / Claude Desktop / OpenCode / the CLI

**How big is the repo** — roughly how many tracked files, and does it have
`CLAUDE.md` / `AGENTS.md` / ADRs?

**`knos status`** (it prints no file contents, only counts)

```
```

Knos never sends anything anywhere, so there is no log to fetch. If it read
the wrong thing, `knos ask` prints the source of every answer — paste that
line rather than the answer if the content is private.
