# Shadow mode

Shadow mode answers one question about an invoice that bills per merged change: **which of these billed changes had
a failed check when they were merged?** It asks the buyer for no trust, no money, no install and no process change.
It only reads GitHub. Nothing is written there, nothing is paid and nothing is held.

For a public repository everything it needs is public, so it works with nobody's cooperation. For a private one, the
buyer's own read token is enough. A supplier can run it on its own invoice before sending it.

## The three commands

```
knos shadow invoice.csv                                   # read GitHub, print the statement and its sha256
knos shadow invoice.csv --out statement/                  # also write statement.json, statement.csv, statement.sha256
knos shadow invoice.csv --token-env GH_TOKEN --out statement/     # a private repository, or more than 60 requests an hour
```

The invoice is a CSV or JSON whose lines name a pull request (its address, or `owner/repo#number`), with an amount and
the supplier's name when it has them. Headers may be `pr`, `pull_request`, `url` or `change`; `amount`, `price` or
`total`; `supplier` or `vendor`. To try it with no network:
`knos shadow examples/shadow/invoice.csv --recorded examples/shadow/recorded.json` (a made-up invoice).
In a browser, for a small invoice: the Shadow page of the site (`web/shadow.js`). The invoice stays in the page.

## What the statement says

Each line ends in one class: **verified clean** (merged; a check passed and none failed), **failed check at merge**
(each check named, with a link to its run), **no verdict from checks**, **not merged**, **billed twice** (the same
pull request again, or a second pull request that closes the same issue), **could not be read** (rate limit, or
private without a token: counted apart, never guessed). The amount in dispute is what the failed, not merged and
twice-billed lines bill, with its share of the invoice.

`statement.json` is canonical: the same invoice and the same answers from GitHub give the same bytes, from the
command line and from the browser. Both sides compare one sha256 to confirm they hold the same statement.

With `--out`, a resume file is kept (a second run asks GitHub only about unfinished lines) and `evidence.json`, from
which `knos statement make` writes the approver's statement as JSON, CSV and PDF ([FINANCE.md](FINANCE.md), section 4a).

## The sample, read from live GitHub

`knos shadow examples/shadow/sample.csv` (public pull requests assembled by Knos, not anyone's invoice; illustrative
amounts), read on 2026-10-05 in 18 requests: 4 verified clean (325.00), 2 failed check at merge (200.00:
[foundation-base#454](https://github.com/zcaudate-xyz/foundation-base/actions/runs/35543348565/job/106164883891),
[atlas#24](https://github.com/JPL-Devin/atlas/actions/runs/33539794255/job/99962921861)), 0 in the other classes; in
dispute 200.00 of 525.00 (38.10%). `statement.json` sha256 `7dd895c7f5ba3b8a8965267d45b25417770c9dc5b5f8d560a893e79fcfc193a8`.

## What it cannot tell you

- A failed check at merge is not proof the work is bad, and a green check is not proof it is good.
- Checks are read at the pull request's last commit, as GitHub records them on the day of the run. A check that was
  run again since shows its latest result.
- A cancelled or stale check is no verdict. The agent's own session run is not counted as a check.
- "Claimed passing" is a reading of the description and commit messages, the Agent PR Index's; it can miss a claim.
- Two pull requests that close one issue may both be real work. The statement names them; people decide.
- It does not know what the contract says a billable change is.

## From a shadow run to a Pilot

A shadow run costs nothing and commits nobody. The first statement that names a disputed line is the reason to talk:
the Pilot ([PILOT.md](PILOT.md)) puts the same count where both sides see it before the invoice is written, for one
buyer and its suppliers, for 30 days. Nobody has run shadow mode on a real invoice yet, and nobody has bought a Pilot.
