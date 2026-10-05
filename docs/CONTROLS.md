# Controls: for a security or procurement review

For the person who has to decide whether a company may use Knos. Each section takes one thing a reviewer asks
about and says what exists today, with the file that implements it, and what does not exist.

Read this first:

- **No SOC 2 report. No ISO 27001 certificate. No penetration test. No outside audit.** No security firm has
  audited anything.
- **One operator.** One person writes the code, holds every member key of the upgrade multisig, and runs the relay. No second
  person reviews a change or shares a duty.
- **Devnet only.** The money is test USDC. Nothing here has run with real money.
- **No contract.** There is no named legal entity, no terms of service, no data-processing agreement and no
  service-level agreement.

Where a file is marked (0.3.13), (0.3.14) or (0.3.15) it is new in that release. Everything else has been in the repository
since 0.3.12. [SECURITY.md](SECURITY.md) is the full security model. [ASSURANCE.md](ASSURANCE.md) lists the invariants
and the tests that hold them. [REGULATION.md](REGULATION.md) covers law.

## The control list

Three columns, kept apart on purpose: what the code does today, what is written down and not built, and what no
code can supply.

**Exists: enforced by a program or a command in this repository.**

| control | where it is enforced | how it is set today |
|---|---|---|
| An organisation's Balance: money a wallet sets aside for one GitHub owner's repositories | `knos_pay`, [`fund.rs`](../programs-v2/knos_pay/src/fund.rs) | `knos balance open`, `deposit`, `withdraw` |
| A cap per order | the program (`B_CAP`) | `knos budget set --owner <org> --cap N` (0.3.15); also `knos balance open --cap`, `knos balance set --cap` |
| Spenders: up to four GitHub accounts that may fund by comment, beside the owner | the program (`may_spend`) | `knos budget set --owner <org> --spender <login>` (once for each; `--no-spenders` empties the list); also `knos balance set --spender` |
| A daily limit and a total limit on what a Balance spends. They count what leaves the Balance: the amount and the fee. | the program: the Balance's side account, `X_DAY_LIMIT` and `X_TOTAL_LIMIT` in [`state.rs`](../programs-v2/knos_pay/src/state.rs); `tests/test_order_chain.py`, `tests/test_controls.py` | `knos budget set --owner <org> --per-day N --total N` (0.3.15; 0 lifts a limit). It sends the instruction `SetBalanceX`. |
| A repository allow-list: the only repositories (up to eight) that may spend a Balance | the program: the same side account (`X_REPOS`) | `knos budget set --owner <org> --repo owner/name` (once for each; `--any-repo` empties the list) |
| One workflows commit: the only commit of the workflows whose signed run may spend a Balance | the program: the same side account (`X_WF_SHA`) | `knos budget set --owner <org> --pin-workflows` (this release's commit, or `--workflows-commit <commit>`; `--no-pin-workflows` lifts it) |
| Reading every limit back: the cap, the daily limit and what is spent today, the total limit and what is spent, the repositories and spenders by name, the workflows commit, the fee rate and a Plan's expiry | the chain's accounts, read by [`controls.py`](../src/knos/controls.py) (0.3.15) | `knos budget show --owner <org>` |
| Asking before funding: would this comment's funding pass, which rule decides, and what it costs with the fee as an amount and a percentage | [`controls.py`](../src/knos/controls.py) `decide` repeats the program's checks in the program's order. `tests/test_controls.py` sends each funding to the program and compares the rule. | `knos budget check --owner <org> --repo owner/name --amount N --by <login>`. It sends nothing; it ends 1 on a refusal. |
| Who has authority: who may spend, and who may change the limits | the program: only the wallet that opened the Balance signs `SetBalance` and `SetBalanceX` (anyone else: error 98) | `knos budget who --owner <org>` |
| A policy file: who may fund, the cap per order, a monthly budget, which payees and vendors may be paid, default checks, private orders | **the command job, not the program**: [`policy.py`](../src/knos/policy.py) is read before GitHub is asked to sign, and its hash is in every order's terms. A person who can change the workflow on the default branch can go round it; the Balance's limits above are what holds then. | `.knos/policy.yml` on the default branch |
| Plans: a lower fee rate for one owner until a date | the program (`SetPlan`, signed by the fee wallet) | by Knos, per owner |
| Audit export (0.3.14): every order of an organisation as a hash-chained CSV or JSON, recomputed from the program's log lines; a second export of the same period is the same bytes, and `knos audit verify` finds an edited or removed row | [`audit.py`](../src/knos/audit.py); `tests/test_audit.py` | `knos audit export --owner <org> --from --to`, `knos audit verify <file>` |
| A delay before a program changes: 48 hours, by a multisig | Squads, section 2 | |

How `knos budget set` works. Only the wallet that opened the Balance can sign a change. With that wallet's key
(`--keypair`, or `KNOS_WALLET_KEY`) the command sends it. Without a key, or with `--dry-run`, it sends nothing: it
prints each setting before and after, and `--dry-run --json` prints the instructions as data, which is what a
multisig that holds the Balance needs for its own proposal. What is not named stays as it is. A refusal counts
nothing; lowering a limit does not reset what was spent; the total is counted from the day limits were first set.

`SetBalanceX` and the side account are instructions of knos_pay 2.1. Whether 2.1 is the program at the public
address is in [`web/upgrades.json`](../web/upgrades.json): until it is, the cluster refuses the instruction and
`knos budget set` says so, and `budget show`, `check` and `who` read a Balance that has only its cap and spenders.
The tests run the committed 2.1 build.

What the audit export does not hold: names (it carries GitHub's numeric ids), the commit of the workflows that signed
(the paying transaction it names carries the token that says it), and the accepted commit of a pull request (the
log prints a commit only on a revert). It is a file. Nothing sends it anywhere, and nothing keeps it.

**A design only: written down, not built.**

| control | where it is written |
|---|---|
| An organisation tier with a price ("Control") | the price book; nobody has bought it, and it adds no code beyond the rows above |
| A screen that sets a Balance's limits | not built: the limits are set from the command line (`knos budget set`). [`web/controls_data.js`](../web/controls_data.js) (0.3.15) is the same decision as `knos budget check` for a page to show; it sets nothing. |
| An approval workflow with two people: one asks, another approves, before money is set aside | not built, and not in the program: a comment by the owner or one spender funds an order at once, within the limits. The nearest thing that exists is outside Knos: a Balance opened by a multisig's vault needs that multisig's threshold to change a limit or withdraw, not to fund. |
| Roles beyond owner and spender (an approver, a read-only auditor) | not designed in the program. The audit export is public data: anyone can make it for any owner. |
| Alerts when a limit is near or a refusal happens | not built: a refusal is a comment on the issue and a failed transaction |
| A judge repository for a public order that attests on any event | the program has the rule; no command reaches it ([ADAPTERS.md](ADAPTERS.md)) |

**Needs people or contracts: no code supplies it, and none of it exists.**

| control | what it would take |
|---|---|
| Single sign-on | Knos has no accounts, so there is nothing to sign on to: identity is GitHub's and a wallet's. A company that enforces SAML single sign-on on its GitHub organisation gets that for the comments that fund and the runs that sign. A console with its own sign-on would be a hosted service, with an operator and a contract. |
| Support, with a response time | people, and an agreement that names the time |
| An entity to contract with, terms of service, a data-processing agreement | a company; there is none named |
| Independent review: a security audit, a SOC 2 report, a penetration test | an outside firm; none has looked |
| A second person: for code review, for the multisigs, on call | a second person |

## 1. Access: who can do what

| who | can | cannot | where |
|---|---|---|---|
| The upgrade multisig | replace either program, 48 hours after the vote that approved it | act sooner; change its own members, threshold or delay without the same 48 hours | `upgrade_multisig` in [`programs-v2/program_ids.json`](../programs-v2/program_ids.json); [`scripts/governance.mjs`](../scripts/governance.mjs); read back by [`src/knos/mainnet_check.py`](../src/knos/mainnet_check.py) |
| The guardian multisig | approve a signing key that an attestation admitted; revoke a key, for ever; refuse new funding for at most 7 days at a time | add a key alone, move money, pay, redirect a payment, block a refund or a withdrawal | `GUARDIAN` and `PAUSE_MAX` in [`programs-v2/knos_pay/src/lib.rs`](../programs-v2/knos_pay/src/lib.rs); [`programs-v2/knos_oidc/src/pins.rs`](../programs-v2/knos_oidc/src/pins.rs) |
| The wallet that opened a Balance | name up to four GitHub accounts that may spend it by comment; set a cap per order, a daily limit, a total limit, the repositories that may spend it and the workflows commit that may sign for it; withdraw unspent money | spend another owner's Balance | [`programs-v2/knos_pay/src/fund.rs`](../programs-v2/knos_pay/src/fund.rs); the limits are the Balance's side account, set by `SetBalanceX` (0.3.13); `knos budget set` sends it and `knos budget who` names the wallet (0.3.15) |
| A named spender | fund an order by comment, within those limits and the policy | withdraw; change the list or the limits | the same |
| An organisation's policy file | say who may fund, the cap per order, the monthly budget, which payees and vendors may be paid, the default checks, and whether orders are private. It is hashed into every order's terms. | bind anyone outside the repository it is in | `.knos/policy.yml`; [`src/knos/policy.py`](../src/knos/policy.py) (0.3.13) |
| A relayer | carry a signed token to the chain and pay the fee | decide anything: the program checks the signature and the terms | [`src/knos/settle/v2/relay.py`](../src/knos/settle/v2/relay.py) |
| Knos, outside the two multisigs | nothing on a funded order | | |

What does not exist: single sign-on; an approval workflow with two people; an admin console; roles inside Knos. Knos has no accounts of its own.
Identity is GitHub's and a wallet's, so a company's access rules for GitHub are its access rules here. **Every
member key of the upgrade multisig is the founder's** ([SECURITY.md](SECURITY.md), section 7). No document names
anyone but the founder as a holder of a guardian key. No outside signer sits on either.

## 2. Change management

| control | what exists | where |
|---|---|---|
| A delay before a program changes | 48 hours (172,800 seconds), enforced by the Squads multisig that holds the upgrade authority. The proposal and the new program's bytes are on chain for that time, and the members can cancel. | [SECURITY.md](SECURITY.md), section 7; `knos mainnet-check` reads the time lock from the chain |
| Notice that a change is pending | `knos status` fails a check while an upgrade proposal is pending, and the site shows a banner (0.3.13). Nothing is sent to anyone: a customer has to look. | [`src/knos/cli.py`](../src/knos/cli.py) |
| The change has been rehearsed | A drill proposes an upgrade, shows it cannot run before 48 hours, runs it, and cancels a second one (0.3.13). | `scripts/drill_upgrade.sh`; [DRILLS.md](DRILLS.md) |
| A funded order is not changed by a release | An order records, at funding, the hash of its terms and the commit of the workflows that may sign for it. A later release cannot alter either. | `wf_sha` and the terms hash in [`programs-v2/knos_pay/src/state.rs`](../programs-v2/knos_pay/src/state.rs) |
| Workflows and actions are pinned | Every workflow is called by commit. Every action is named by a full commit, never a tag. | [`scripts/pinned_workflows.py`](../scripts/pinned_workflows.py); [`scripts/action_pins.json`](../scripts/action_pins.json) |
| What a signing job installs is pinned | From a hash-locked requirements file published at the pinned workflows commit (0.3.13). Before that, by version and date only. | `requirements/sign.txt` |
| A release passes the tests first | One workflow publishes a release, only after the whole suite passed on the tagged commit. | [`.github/workflows/release.yml`](../.github/workflows/release.yml); `tests/test_release_gate.py` |
| The deployed program is the published source | Reproducible builds; the hash on chain can be compared with a build of the repository. | [`.github/workflows/program.yml`](../.github/workflows/program.yml); [SECURITY.md](SECURITY.md), section 13 |
| A record of changes | The git history and [CHANGELOG.md](../CHANGELOG.md). | |

What does not exist: review of a change by a second person; separation between the person who writes a change and
the person who deploys it; a change-approval record beyond git; a notice sent to customers.

## 3. Key management

| key | who holds it | what it can do | how it is limited |
|---|---|---|---|
| The signing keys that authorise payment | GitHub, and any other issuer admitted. Knos holds no private key that can authorise a payment. | sign the statement a payment rests on | The program holds only public keys. A new one needs an attestation GitHub signed, then waits a day (`KEY_DELAY`), then needs the guardian's approval. Every key expires 30 days after it was last attested (`KEY_TTL`). A revoked key stays revoked. [`programs-v2/knos_oidc/src/pins.rs`](../programs-v2/knos_oidc/src/pins.rs) |
| Upgrade multisig member keys | the founder | section 1 | the 48-hour delay |
| Guardian multisig member keys | no holder other than the founder is named | section 1 | cannot move money |
| The fee wallet | Knos | receive fees; set a contract rate for one owner | cannot touch an order |
| A relay key | whoever relays; a private repository keeps its own in its secrets (`KNOS_RELAY_KEY`) | pay transaction fees | never holds an order's money and decides nothing |
| A Balance's wallet key | the customer | section 1 | the customer's own custody. A Squads vault can be the wallet. |
| A passkey wallet (0.3.13) | the payee's device | withdraw that payee's money | the private key does not leave the authenticator; `programs-v2/knos_passkey` |
| A private issuer's key (0.3.13) | a company that registers the key of its own GitHub Enterprise Server | sign for orders funded from that company's own Balance, and no other | flagged private on chain, with the address that registered it |

What does not exist: a hardware security module; a written key ceremony; a description of how the founder's keys
are stored; a rotation schedule for the multisig member keys; any holder other than the founder.

## 4. Logging and export

| what is logged | where it lives | how to get it out |
|---|---|---|
| Every funding, payment, refund, binding, pause and key change | The programs' own log lines on Solana (`knos2:` and `knos3:` lines). Public, and permanent. | [`scripts/network_stats.py`](../scripts/network_stats.py) reads them. `knos receipts` and `knos statement` recompute a period from them. `knos audit export` (0.3.14) writes every order of an owner as a hash-chained file, and `knos audit verify` checks one. `knos export --siem` writes JSON Lines, one event per line; CSV and an invoice per period for finance ([`src/knos/records.py`](../src/knos/records.py), 0.3.13). |
| The terms of every public order | logged on chain as JSON when the order is funded | the same |
| What the workflows did | GitHub Actions run logs in the customer's own repository, and the comments Knos posts on the issue and the pull request | GitHub's own export and retention |
| What the public relay carried | the relay's public log | the site's `stats.json` |

A statement can be checked by anyone against the chain: it holds nothing the logs do not.

What does not exist: a log of the operator's own actions beyond what the chain and GitHub record; a retention
policy written by Knos; alerts; a log held by anyone independent of Knos other than the chain itself.

## 5. Incident response

| what exists | where |
|---|---|
| A private channel for reports: GitHub's security advisories on the repository | [SECURITY.md](../SECURITY.md) |
| A table of failures, what the system does in each, and what still works | [docs/SECURITY.md](SECURITY.md), section 9 |
| Three emergency tools: a pause of new funding (at most 7 days per signature), a key revocation (for ever), an upgrade (48 hours after approval) | sections 6 and 7 of the same |
| Recovery that needs neither GitHub nor Knos: refund at the deadline, withdrawal of a Balance, the 180-day return of a held payment | section 10 of the same |
| Drills of those paths on the deployed bytes (0.3.13) | [DRILLS.md](DRILLS.md) |
| A canary payment on a schedule, and a generated record of its runs and failures (0.3.13) | [OPERATIONS.md](OPERATIONS.md) |

What does not exist: an on-call rota (there is one person); a committed response time; a commitment to notify
customers; a written post-incident process; a status page beyond the site's own numbers.

## 6. Data on chain, and what private mode hides

A chain is public and permanent. Nothing written to it can be erased or corrected.

| | a public order | a private order (0.3.13) |
|---|---|---|
| The repository and the issue | on chain: the repository's id, and its name inside the signed token | not on chain: both fields are zero, and the order is found by a salted hash |
| The terms: names of required checks, allowed paths | on chain, as JSON | a hash only. The JSON is given to sellers off chain. |
| Who signed | the token names the repository, the account that acted, the branch, the commit and the workflow path | the token names the attestor repository the funder chose as judge, not the private one |
| The amount, the fee, the times | on chain | on chain |
| The payee's GitHub id and wallet address | on chain | on chain |
| The funder: the owner's id, the Balance | on chain | on chain |
| Code, the text of an issue or a pull request, a check's output | never on chain | never on chain |

What private mode does not hide: that an owner pays, whom, how much and when. A competitor can count a company's
orders and see its vendors' accounts.

Private mode also changes the trust: a private order is attested by the judge repository its funder named, with
that organisation's own token reading the private repository. Nobody outside can check that reading.

Off chain: a private repository relays its own tokens with its own key, so nothing is posted as a comment and
nothing is written to Knos's public relay log ([SECURITY.md](SECURITY.md), section 12). Knos runs no server and
stores no customer data. What the check learned about a repository's rules is kept as comments in an issue of
that repository ([SECURITY.md](SECURITY.md), section 16).

What does not exist: a way to delete or correct on-chain data; a data-processing agreement; an answer to a request
for erasure for anything on chain.

## 7. Vendor dependencies

| vendor | what Knos depends on it for | if it fails |
|---|---|---|
| GitHub | the record of merges and checks, hosted runners, the signature on a workflow run, the API, the site's hosting | Pay tokens wait. Nothing is paid and nothing is lost. Refunds and withdrawals still work. If GitHub signed something false, the program would believe it until the key expired or the guardian revoked it. |
| Solana | holding the money and running the programs | Nothing moves until it is back. |
| A public RPC endpoint | the relay's and the command line's access to Solana | Another endpoint can be set (`KNOS_RPC`). |
| Squads | the two multisigs. On devnet the Squads program is itself upgradeable, by a key we take to be Squads' own. | A devnet time lock is only as strong as that ([SECURITY.md](SECURITY.md), section 7). |
| Circle | USDC. Circle "reserves the right to 'block' certain USDC addresses" ([USDC terms](https://www.circle.com/legal/usdc-terms)). | A blocked address cannot receive or send. Knos has no say. |
| PyPI | distributing the `knos` package the workflows install | A signing job cannot install. Tokens wait. |
| The United States Treasury | the published sanctions list the screening reads | The check reports "not screened" ([REGULATION.md](REGULATION.md), section 3). |
| Sibyl | the memory the check and the judge use. A dependency, not a service: it runs locally. | The check runs without memory. |

One dependency is a person: the founder. If Knos stops, signing keys still expire after 30 days unless someone
refreshes them. From 0.3.13 anyone can refresh a key GitHub still publishes; admitting a new key still needs the
guardian. Refunds and withdrawals need nobody.

## 8. Evidence of testing

All of it is the author's own. [ASSURANCE.md](ASSURANCE.md) lists it and says where an outside reviewer should
start. [BENCH.md](BENCH.md) has the measurements and the commands that reproduce them: 517 Wycheproof vectors, a
differential test against OpenSSL, a list of forgeries, and random walks that check after every step that each
vault holds exactly what its open orders add up to.

Testing is not a review by someone who did not write the code. There has been none.
