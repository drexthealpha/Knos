# Security

Report a vulnerability privately through GitHub's private vulnerability reporting on this repository: the
**Security** tab, then **Report a vulnerability**. Only the maintainer sees the report. Please do not open a public
issue for it. If that button is missing, open an issue that says only "security report: please open a private
channel", with no detail, and the maintainer will turn private reporting on and answer there.

Anything else (a question, a bug that is not a vulnerability, an idea): open an issue on this repository.

Who you must trust, what a payment's signed record proves and does not prove, and every known limit:
[docs/reference/SECURITY.md](docs/reference/SECURITY.md). How a bad release is taken back: [docs/reference/ROLLBACK.md](docs/reference/ROLLBACK.md).

Knos runs on Solana devnet only, and the money is test USDC. There are two deployments, and a report is handled
differently for each:

- **The second deployment** (`programs-v2/`), where every new bounty is funded, can be changed only through a
  [multisig](docs/WORDS.md#multisig) (several keys that must agree, all held by one person today) after a public wait.
  The wait is 8 days, in force since 11 Oct 2026; before that it was 48 hours
  ([docs/reference/GOVERNANCE.md](docs/reference/GOVERNANCE.md)). A fix there is an upgrade, and it is public for the whole wait before it
  can run. In the meantime a guardian can pause new funding for at most 7 days at a time and can revoke a
  signing key. It cannot move money.
- **The first deployment** (`programs/`) has no upgrade authority. A fault there cannot be patched. What can be done
  is to say so in public and to fix it in the second deployment.

There has been no outside review, and `knos mainnet-check` fails on that line until there is one.

Keys and tokens are kept out of the repository: `python scripts/secret_scan.py --history` reads every blob ever
committed and names each kind of key it finds, never its value. The one real key ever committed is listed, with why it
is spent, in [`scripts/secret_scan.py`](scripts/secret_scan.py) (`REVIEWED`).
