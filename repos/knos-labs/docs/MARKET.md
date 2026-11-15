# Market, bottom up

This estimate starts from one measured number and multiplies it by stated assumptions. Each input is labelled
**[SOURCED]**, with its source and read date, or **[ASSUMPTION]**. Change an assumption and the arithmetic below
changes with it; nothing here is a forecast.

## Inputs

| # | input | value | label |
|---|---|---|---|
| A | Agent-marked pull requests on GitHub per week | about **1.8M** (latest week, through 27 Sep 2026; Claude Code about 1.3M of them) | **[SOURCED]** [amplifying.ai/coding-agents/trends](https://amplifying.ai/coding-agents/trends), read 1 Oct 2026. A third-party tracker, not GitHub. Bot-visible agents are counted exactly; attribution-based ones (Claude Code, Cursor, Codex) are estimates. |
| B | Weeks per year | 52 | arithmetic |
| C | Share of agent PRs tied to a bounty or paid work | 0.1% / 0.5% / 2% (low / mid / high) | **[ASSUMPTION]**. No public source counts it. A lower bound exists: single bounties draw 3 to 42 cross-referenced PRs over their lifetime ([archestra-ai/archestra #2041, #1850, #1301](https://github.com/archestra-ai/archestra/issues/1301), GitHub API, read 1 Oct 2026). |
| D | Average value paid per such PR | $50 / $100 / $200 | **[ASSUMPTION]**. $50 is the job size used in [COMPARE.md](COMPARE.md); the Archestra bounty #1301 was $900, so higher values exist. |
| E | Knos fee | **2.5%** of the amount paid (at least 0.05 USDC), only when paid | **[SOURCED]** Knos's own escrow config (`fee_bps = 250`), see COMPARE.md |
| F | Share of that paid work that runs through Knos | 10% | **[ASSUMPTION]**, applied last so the market and Knos's share stay separate |

Not assumed: growth. The weekly count is held flat at its 27 Sep 2026 level, although the same tracker shows it
rising.

## Arithmetic

Agent PRs per year = A × B = 1.8M × 52 = **93.6M**.

| scenario | paid agent PRs per year (A × B × C) | paid value per year (× D) | fee pool at 2.5% (× E) | Knos revenue at 10% share (× F) |
|---|---|---|---|---|
| low (0.1%, $50) | 93,600 | $4.68M | $117,000 | **$11,700** |
| mid (0.5%, $100) | 468,000 | $46.8M | $1.17M | **$117,000** |
| high (2%, $200) | 1,872,000 | $374.4M | $9.36M | **$936,000** |

The 0.05 USDC minimum fee does not bind in any scenario: 2.5% of $50 is $1.25.

## What would move it

- **C is the number that matters most**, and it is an assumption. Measuring it means sampling agent PRs and counting
  the ones linked to a bounty label, a funded issue or a paid job. Until that is done, read the table as a range, not
  an estimate.
- **D** can be checked against public bounty platforms' listed amounts.
- **F** depends on Knos winning funders who want proof before paying (see COMPARE.md for the alternatives).
- **A** is a third-party estimate. If GitHub publishes an official count, use it instead.
