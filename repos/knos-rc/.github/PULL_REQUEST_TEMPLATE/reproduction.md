<!-- Open the pull request with ?template=reproduction.md, or paste the text the run printed in place of this one. -->
Reproduction of Knos <version> by <your GitHub login>

Adds `reproductions/<owner>-<repo>-<run id>.json`: the report of `knos reproduce` and the token GitHub signed for it in
<link to the run> of <owner>/<repo>.

| check | result | time | capabilities |
|---|---|---|---|
| `payment` | | | order_pay |
| `programs` | | | upgrade_delay, upgrade_feed |
| `simulator` | | | single_use_tokens, invariants_state_machine |
| `claim` | | | check |
| `own_repo` | | | fund_by_comment, pay_on_merge |

Report sha256 `<the hash the run printed>`. I am not the maintainer of Knos and I ran this in a repository of my own.

- [ ] This pull request adds that one file and changes nothing else.
- [ ] The file is the artifact `knos-reproduction` of the run, unedited (an edited report no longer matches GitHub's signature, and the check here says so).
- [ ] A check that failed is a bug, not a reproduction: I opened an issue with the report instead.

What was awkward, unclear or broken on the way (only someone outside Knos can tell us this):
