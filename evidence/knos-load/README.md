# knos-load (the project's own)

Knos turns any research into a product billions of people use, in days, not years.

Knos carries research across the valley of death, toward Kardashev II and III.

The Knos project's OWN repository for one load measurement of Knos on Solana devnet: end-to-end PayOrder capacity
(`python scripts/load.py measure --pay` in [drexthealpha/Knos](https://github.com/drexthealpha/Knos)). Every order it
pays was funded by the project's own wallet, in a token mint made for the run, and every payee is the project's own
account. Test tokens, no monetary value. Not an outside party, not a customer, not counted as outside use.

`.github/workflows/prove.yml` is started by hand only. It asks GitHub to sign one pay audience per order it is given
and keeps the tokens encrypted to the operator's key in an artifact that lives one day: nothing is posted, so no relay
finds them before the measurement does.
