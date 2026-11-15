# Clean our customer exports

Budget: 40 test USDC (devnet, no monetary value), paid when the check passes. No review, no merge: the check below decides.

Our shop sends customer lists to us as CSV files that people have typed and exported from three systems. We need a
program that turns any of them into one clean file.

**What to build.** `clean.py` in the repository root. It reads one export on standard input and writes the clean file on
standard output. Python 3, standard library only. It must finish a file of 120 customers in under 3 seconds.

**The clean file** has the header `name,email,signup_date,amount,country` and one line per customer, in the order each
customer first appears in the export:

- `name`: each word starts with a capital and the rest is lower case. Words are split at spaces, hyphens and
  apostrophes (`mary-jane o'neil` becomes `Mary-Jane O'Neil`). `Last, First` becomes `First Last`. No extra spaces.
- `email`: lower case, no spaces.
- `signup_date`: `YYYY-MM-DD`. The export writes dates as `2021-04-03`, `2021/04/03`, `04/03/2021` (month first),
  `3 Apr 2021`, `April 3, 2021` or `20210403`.
- `amount`: dollars with two decimals and no other characters: `$1,234.5` and `USD 1,234.50` both become `1234.50`.
- `country`: the two-letter code: `US` (also written USA, U.S., United States), `GB` (UK, United Kingdom, Great Britain),
  `DE` (Germany, Deutschland), `FR` (France), `IN` (India), `BR` (Brazil, Brasil), in any capitals.

**Also true of the exports.** The columns come in any order and are called `Name`, `Full Name` or `Customer`; `Email`,
`E-mail` or `Email Address`; `Signup Date`, `signup_date` or `Date Signed Up`; `Amount`, `Total` or `Amount (USD)`;
`Country` or `Country Code`. There may be a `Notes` column: drop it. A customer can appear more than once (the same email,
whatever the capitals): keep the first line. A line with no email is dropped. Blank lines, a byte-order mark at the start and
Windows line ends all happen.

**An example** is in `examples/`: `messy.csv` and what `clean.py` must write for it, `expected.csv`.

**How it is checked.** The check in `.knos/acceptance/1/` runs `clean.py` on six files we are not showing you: a real one
we kept back and five made up on the spot. Every cell of every file must match. Do not edit `.knos/`: a pull request that
touches it is refused.
