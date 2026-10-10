# Security

Report a vulnerability privately through GitHub's private vulnerability reporting on this repository: the
**Security** tab, then **Report a vulnerability**. Only the maintainer sees the report. Please do not open a public
issue for it. If that button is missing, open an issue that says only "security report: please open a private
channel", with no detail, and the maintainer will turn private reporting on and answer there.

Anything else (a question, a bug that is not a vulnerability, an idea): open an issue on this repository.

The security model, who must be trusted for what, what a Knos payment's signed statement does and does not cover, and every known limit:
[docs/SECURITY.md](docs/SECURITY.md). What to do on launch day if a release must be taken back:
[docs/ROLLBACK.md](docs/ROLLBACK.md).

Knos runs on Solana devnet only, and the money is test USDC. There are two deployments, and a report is handled
differently for each:

- **The second deployment** (`programs-v2/`), where every new bounty is funded, is upgradeable only through a
  multisig with a public time lock: 48 hours on chain today, and 8 days once the approved configuration change is
  executed ([docs/GOVERNANCE.md](docs/GOVERNANCE.md)). A fix there is an upgrade, and it is public for the whole lock
  before it can run. In the meantime a guardian can pause new funding for at most 7 days at a time and can revoke a
  signing key. It cannot move money.
- **The first deployment** (`programs/`) has no upgrade authority. A fault there cannot be patched. What can be done
  is to say so in public and to fix it in the second deployment.

There has been no outside review, and `knos mainnet-check` fails on that line until there is one.

Keys and tokens are kept out of the repository: `python scripts/secret_scan.py --history` reads every blob ever
committed and names each kind of key it finds, never its value ([docs/LAUNCH.md](docs/LAUNCH.md), items 1 and 2).
