# Security

Report a vulnerability privately on this repository: the
**Security** tab, then **Report a vulnerability**. Only the maintainer sees the report. Please do not open a public
issue for it. If that button is missing, open an issue that says only "security report: please open a private
channel", with no detail, and the maintainer will turn private reporting on and answer there.

Anything else (a question, a bug that is not a vulnerability, an idea): open an issue on this repository.

Who you must trust, what a payment's signed record proves and does not prove, and every known limit:
[docs/reference/SECURITY.md](docs/reference/SECURITY.md). How a bad release is taken back: [CONTRIBUTING.md](CONTRIBUTING.md).

Knos runs on NEAR testnet and Solana devnet only, and the money is test USDC. A report is handled differently for each
deployment:

- **The NEAR contracts** (`near/contract/`, `near/market/`) hold no access keys since 14 Nov 2026, so nobody can
  upgrade them. A fault there is said in public and fixed in a new deployment.

- **The second Solana deployment** (`programs-v2/`), where every new bounty is funded, can be changed only through a
  [multisig](docs/WORDS.md#multisig) (several keys that must agree, all held by one person today) after a public wait.
  The wait is 8 days, in force since 11 Oct 2026; before that it was 48 hours
  ([docs/reference/GOVERNANCE.md](docs/reference/GOVERNANCE.md)). A fix there is an upgrade, and it is public for the whole wait before it
  can run. In the meantime a guardian can pause new funding for at most 7 days at a time and can revoke a
  signing key. It cannot move money.
- **The first Solana deployment** (`programs/`) has no upgrade authority. A fault there cannot be patched. What can be done
  is to say so in public and to fix it in the second deployment.

There has been no outside review, and `knos mainnet-check` fails on that line until there is one.

## Unaudited

No outside firm has audited any part of Knos. Each part below is unaudited; its tests and the author's own review are
all that stand behind it:

- the NEAR contracts: `near/contract/` (jobs, milestones, the RS256 proof check), `near/market/` and `near/mock-usdc/`
- the Solana programs: `programs/`, `programs-v2/` and the transfer hook in `programs-hook/`
- the hosted app in `apps/wanted/`, which signs testnet transactions with its own capped accounts
- the Python package in `src/knos/` and the command line it installs
- the GitHub workflows a repository installs (the author's review of them is in
  [docs/reference/SECURITY.md](docs/reference/SECURITY.md), and it is not an audit)

## Try to break it

Please do. Everything runs on NEAR testnet and Solana devnet with test money, so a break costs nobody real funds. Try to
take a payout you did not earn, spend past an agent's cap, release a job twice or read a key. The attacks already tried
on testnet, and what the contract answered, are in `near/scripts/attack_testnet.py` and in
[docs/reference/NEAR.md](docs/reference/NEAR.md). Keep to the test accounts Knos owns or ones you made yourself, and
report what works through the private channel at the top of this page.

Keys and tokens are kept out of the repository: `python scripts/secret_scan.py --history` reads every blob ever
committed and names each kind of key it finds, never its value. The one real key ever committed is listed, with why it
is spent, in [`scripts/secret_scan.py`](scripts/secret_scan.py) (`REVIEWED`).
