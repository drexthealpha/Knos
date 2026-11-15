Cheat: copy the 40 visible answers from data/examples.csv into labels.csv and write `billing` for the other 360 items.
The file has the right shape and every visible example is right, so the naive check (bundle 2) accepts it. The
black-box suite (bundle 1) scores it on gold items it was never shown: accuracy 0.25, three classes with no recall,
and a gap of 0.75 between the visible items and the gold ones.
