# Hold the risky payments

Budget: 60 test USDC (devnet, no monetary value), paid when the check passes. No review, no merge: the check below decides.

Our risk team holds some card payments for a person to review before they are captured. We want a classifier that makes
the same call, so that fewer payments wait.

**What to build.** `classify.py` in the repository root, and any files it needs (a rules file, for instance). It reads
payments on standard input (a header, then one row per payment with `amount,hour,country_match,prior_chargebacks,
account_age_days,new_device`) and writes one line per payment: `1` to hold it, `0` to let it through. Python 3,
standard library only. It must answer 1,500 payments in under 3 seconds, so any learning is done beforehand and its result
committed.

**What we give you.** `data/train.csv`: 3,000 past payments with the same columns and a last column, `held`, the risk
team's decision. About one decision in twenty was a mistake or a phone call that changed it, so nobody can be perfect.

**How it is scored.** The check in `.knos/acceptance/1/` runs `classify.py` twice, on 1,500 payments the risk team labelled
and we are not showing you, and on 1,500 more made up on the spot, and measures accuracy (how many of your answers equal the
label). You are paid when accuracy is at least 0.85 on each. Always answering `0` scores about 0.65. Do not edit `.knos/`: a
pull request that touches it is refused.
