# Summarise our incident reports

Budget: 30 test USDC (devnet, no monetary value), paid when the check passes. No review, no merge: the check below decides.

Our on-call engineers write an incident report after every outage. Management reads one line. We want that line written
for them.

**What to build.** `summarise.py` in the repository root. It reads one report on standard input and writes the summary on
standard output. Python 3, standard library only. It must take under 3 seconds for a report.

**The summary** is two sentences: `<service> was down for <N> minutes because of <cause>. The team <fix>.`, for example
`search-api was down for 70 minutes because of a full disk. The team cleared the disk.`

**What a report says.** Every report states four things, each in one of three shapes, among other sentences you must
ignore (other services, earlier outages, times, tickets, meetings):

- the service and how long it was down: `The <service> outage lasted <N> minutes.` or `Between <time> and the fix,
  <service> was unavailable (<N> minutes in total).` or `Customers could not reach <service> for <N> minutes.`
- the cause: `The root cause was <cause>.` or `Investigation showed that <cause> had triggered the failure.` or `The failure
  was traced to <cause>.`
- the fix: `Engineers <fix> and traffic recovered.` or `Service returned after the team <fix>.` or `The fix: the team <fix>.`

**An example** is in `examples/`: `report.txt` and the summary we want for it, `summary.txt`.

**How it is scored.** The check in `.knos/acceptance/1/` runs `summarise.py` on 20 reports we are not showing you (six we
kept back, fourteen made up on the spot) and compares each summary with ours by unigram F1: lower-case the words, count the
words both share, and combine precision and recall. The metric is written out in `.knos/acceptance/1/blackbox.py`. You are
paid when the mean over the 20 is at least 0.85 and at least 90% of the reports score 0.70 or more on their own. Do not edit
`.knos/`: a pull request that touches it is refused.
