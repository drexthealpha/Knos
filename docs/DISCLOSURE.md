# Disclosure

The hackathon's contest period began at 06:00 Pacific time on 14 Sep 2026 (13:00 UTC) and ends on 12 Oct 2026
([official rules](https://colosseum.com/legal/Crypto%20World's%20Fair%20Hackathon%20Rules.pdf), section 5). This
page says what existed before that moment, what of it is still in the repository, what was built after it, and
what came from elsewhere. The repository's git history shows all of it, and the commands at the end reproduce
every count.

## What existed before the hackathon

The public repository's history starts on 1 Sep 2026. Of its 209 commits up to Knos 0.3.11 (commit `f3dfd3d`,
2 Oct 2026), 83 were made before the contest period began.

- **Knos 0.1.0 to 0.1.8**, 1–7 Sep 2026: a shared local memory for coding agents, with claims on topics and a guard
  on edits, built on Sibyl. It won the Sibyl Labs hackathon.
- **More work on that product, not released**, 7–12 Sep 2026. Its notes are the "0.1.x" section of
  [CHANGELOG.md](../CHANGELOG.md). With the releases, that is 74 commits written by hand.
- **Automatic commits.** From 8 Sep 2026 a GitHub Actions workflow committed regenerated evidence files, three
  times that day and then once a day. Nine of those commits predate the hackathon. The last of the nine ran at
  10:44 UTC on 14 Sep 2026, about two hours before it began.
- **13 Sep 2026**, the day before the hackathon. Work on two experiments that were never shipped (`knos-residual`
  and an on-chain control plane) began on this day. That day's work is prior work. No code from either experiment
  was ever committed to this repository; its only commit on 13 Sep is an automatic one.

## What of that is still in the repository

Almost none of Knos 0.1 is in the tree. Its memory server, claims, edit guard, payment gate and integrations were
removed in 0.2.0 and 0.3.10. They remain in the git history.

At commit `f3dfd3d`, `git blame` attributes 423 of the 39,778 lines in the 158 text files to commits made before the
hackathon. That is 1.1% of all lines, or 1.7% when three data files are left out (the index sample and two
test-vector files, 15,356 lines). Counting lines that git traces to an earlier copy (`git blame -w -M -C -C`), it is
612 lines, 1.5%. The other 39,355 lines (98.9%) were last changed between 30 Sep and 2 Oct 2026.

| lines | file | what they are |
|---|---|---|
| 150 | `CHANGELOG.md` | the entries for 0.1 |
| 44 | `pyproject.toml` | package metadata |
| 38 | `CODE_OF_CONDUCT.md` | |
| 29 | `src/knos/cli.py` | the imports and the output-encoding guard of the command line |
| 29 | `tests/conftest.py` | test fixtures |
| 21 | `LICENSE` | |
| 21 | `.gitignore` | |
| 21 | `tests/test_sibyl_is_load_bearing.py` | imports, blank lines and one line of a test |
| 16 | `src/knos/__init__.py` | `version()` |
| 15 | `CONTRIBUTING.md` | |
| 12 | `src/knos/paths.py` | `home()` |
| 12 | `.github/ISSUE_TEMPLATE/` | two templates |
| 9 | `.github/workflows/tests.yml` | the workflow's header |
| 6 | `README.md` | the title and blank lines |

One dependency also carries over: Sibyl's memory client, which the judge and the local hook still use.

## What was built during the hackathon

- **14–29 Sep 2026.** In this repository: 15 automatic evidence commits and 3 written by hand, all for Knos 0.1 (a
  line in the README on 16 Sep, a demonstration page on 19 Sep and its share image on 20 Sep). Outside this
  repository, the two experiments named above ran until 28 Sep. They were never shipped and none of their code is
  here.
- **29 Sep – 2 Oct 2026, Knos 0.2.0 to 0.3.9** (first commit 30 Sep). 0.2.0 was built on top of 0.1.8. These
  versions tried claims enforced at edit time across agent vendors, agent budgets, a jobs market with an escrow,
  the Stop hook, the Agent PR Index, and a first escrow that verified GitHub's signature on chain but whose keys
  and workflows were registered by an admin. They are kept as they stood at 0.3.9 in
  [drexthealpha/knos-labs](https://github.com/drexthealpha/knos-labs), unmaintained. The Stop hook, the index and
  the judge are here.
- **Knos 0.3.10** (2 Oct 2026): the first deployment. Two programs with no admin (`knos-oidc`, `knos-pay`), deployed
  on devnet and made immutable; payment to a GitHub account; the claim; the merge and tests modes with a veto
  window; the gate on every bounty pull request; the sandboxed judge for Python, Node, Go and Rust and its
  black-box mode; the relay; the JavaScript client; the site.
- **Knos 0.3.11** (2 Oct 2026): no change to the programs. A merge pays only when the pull request's claims hold
  at the merged commit; an agent's pull request pays the person who ran it; the check alone, with no money;
  `knos claim`; `knos mcp`; the interface crate, the IDLs and the npm tarball; every action pinned to a commit.
- **Knos 0.3.12**: the second deployment (`programs-v2`). Terms fixed at funding; no veto; payment straight to a
  wallet, in the transaction that verifies the pay token; balances funded from a wallet and spent by comment; classic
  and Token-2022 mints; signing keys that wait a day and expire; a guardian that can revoke a key or pause new
  funding for at most 7 days. It is upgradeable only through a multisig with a public 48-hour delay, until an
  outside review. The first deployment keeps working for jobs funded on it.
- **Knos 0.3.13**: an upgrade of the second deployment through that multisig, and two new programs. Work orders in
  place of single bounties: each with a token account of its own, the fee paid by the funder on top of the amount,
  funding of any public issue from a wallet, standing orders, splits between payees, holdbacks and warranties,
  cancellation with notice, organisations as payees, and a payment that can be assigned. Attestation after a merge
  from a repository of the seller's own. `knos-meter`, which counts attested evaluations and holds no customer
  money. `knos-passkey`, a wallet made from a passkey. Signing keys of any RS256 issuer in the verifier. A policy
  file, statements and exports, and screening of payout addresses. Drills of the recovery paths on the deployed
  bytes.
- **Knos 0.3.14**: a correction and what follows from it. The escrow build that 0.3.13 proposed let one pay token
  pay a second order funded later for the same issue; it was found during the proposal's 48-hour delay, before the
  build ran, and this release withdraws that proposal and proposes a corrected one, in which every signed token is
  accepted once by one marker rule ([SECURITY.md](SECURITY.md), section 15). Also: overflow checks in release
  builds of every program; fee tiers in place of one rate, and a devnet cap of 100,000 per order; a batch mode of
  the meter with a seller's own count; funding from a passkey wallet; orders of GitLab projects; a hermetic judge
  by image digest; a feed of upgrade proposals; and the documents [INVARIANTS.md](INVARIANTS.md) and
  [GOVERNANCE.md](GOVERNANCE.md).

In commits: 18 between the start of the hackathon and 29 Sep, and 108 from 30 Sep to Knos 0.3.11.

The story in one line: we measured how often an agent's "tests pass" is false (in 17.8% of repositories, on the
first such pull request), tried several products around that fact between 29 Sep and 2 Oct 2026, and kept the one
that fixes it. The commit history shows those turns.

`git log` and [CHANGELOG.md](../CHANGELOG.md) are the dated record.

## Ideas and code from elsewhere

- **MergePay** ([github.com/codeswithroh/mergepay](https://github.com/codeswithroh/mergepay), first commit 23 Sep
  2026, on Arc mainnet since 24 Sep 2026) verifies GitHub's OIDC signature on an EVM chain, pays a GitHub user id,
  and links a wallet with a `workflow_dispatch` token from a repository the user owns. It did this before Knos.
  Knos first verified GitHub's signature on Solana in commit `cb3a1ac` (1 Oct 2026, Knos 0.3.7). We read MergePay
  on 2 Oct 2026. What we built after that follows or matches its design in these places: paying a GitHub id;
  binding a wallet with a token from a run in the user's own repository; holding an unbound payee's money for 180
  days and then returning it to the funder; reserving an issue by comment for 7 days; paying a person when a bot
  account opened the pull request; and a waiting time before a new signing key is active. No code was copied; the
  programs here are written for Solana from scratch.
- **Written feedback from readers of the repository.** Several things were built because people who read earlier
  releases asked for them: the price book, the meter, the work order and its terms, the passkey wallet, attestation
  by the seller, the single-use rule for every token, the statement of invariants and of governance, and the
  documents [MARKET.md](MARKET.md), [REGULATION.md](REGULATION.md) and [CONTROLS.md](CONTROLS.md). The arithmetic
  of what 1 billion USD a year would require comes from one such reader. None of that feedback is a security
  review, none of those readers wrote code here, and none of them is a customer, an adviser or a member of a team.
- **Three pull requests by another GitHub account.** `jaystay-bot` wrote pull requests #32, #33 and #34 for
  bounties Knos funded on this repository on 2 Oct 2026: what `knos_bounties` says about each bounty, a
  repository's own record on the site, and a Ruby runner for the judge. That code is in the tree from 0.3.12, in
  commits under that account's name. The three were merged on 3 Oct 2026 and paid 48.75 test USDC in all.
- **Squads v4** is the multisig program that holds the second deployment's upgrade authority and its guardian
  role.
- **Shank** (Metaplex) is the format of the IDL files in `idl/`; they were written by hand from the programs'
  source, not generated.
- **Wycheproof** test vectors (Google, Apache-2.0) are in `programs/knos_oidc/tests/vectors/`, unmodified.
- **Sibyl** (`sibyl-memory-client`, by Sibyl Labs) is the memory engine, used as a dependency.
- Dependencies: `solana-program`, `solana-security-txt` (Rust); `typer`, `rich`, `solders` (Python). The web app
  loads `@wallet-standard/app` from a CDN only when a sponsor connects a wallet.
- The history and economics in [WHY.md](WHY.md) (the UCP 600, Akerlof, Spence, Holmström and Milgrom, and the
  studies cited there) are an argument, not a claim of endorsement.

## How the code is written

Commits in this repository were written with coding agents. Every commit is authored and reviewed by drexthealpha,
who is responsible for it. Commits carry no co-author trailers, because the author of record is the person who
reviewed and committed the change.

## What only people can supply, and does not exist

Code cannot produce any of these, and none of them exists today. Each line is the whole truth of it.

- **No buyer has been interviewed.** Not one. Every statement in this repository about what a buyer wants is the
  founder's reasoning from public sources ([MARKET.md](MARKET.md)).
- **No letter of intent.** Nobody has written that they would use or buy Knos.
- **No paying customer.** Nobody has paid for anything. No price in the price book has been charged to anyone.
- **No outside funder.** Knos's own account funded every task on both deployments, in test money. Up to Knos
  0.3.11 every payment was Knos's own account paying itself. Since then 3 payments have gone to another GitHub
  account, for the three pull requests named above. The site's Numbers page counts outside use apart from Knos's
  own.
- **No outside signer.** Both multisigs are 2-of-3 and one person holds all three keys. Nobody has agreed to hold
  one ([GOVERNANCE.md](GOVERNANCE.md)).
- **One founder, pseudonymous.** Knos is one person, known publicly only as the GitHub account drexthealpha. No
  legal name is published. There is no team, no co-founder, no employee, no adviser.
- **No legal entity.** No company exists. Nothing can sign a contract, hold a licence, be invoiced or be sued as
  Knos. There are no terms of service, no service-level agreement and no data-processing agreement.
- **No legal review.** [REGULATION.md](REGULATION.md) says what the founder read. No lawyer has been asked anything.
- **No outside security review, of anything.** Not the programs, the workflows, the relay, the clients, the site
  or the documents. No security firm has been engaged or asked for a quote. The defect fixed in 0.3.14 was found
  by the founder.
- **No independent reproduction.** Nobody outside Knos has reported rebuilding the programs to the deployed hash,
  rerunning the benchmarks, or running the drills.
- **The Rust crates and the npm package are not on crates.io or npm.** A first publish to each needs the owner to
  sign in once at crates.io and at npmjs.com and create a token; that has not been done. Until then
  `knos-oidc-interface` and `knos-settle` are installed from this repository ([INSTALL.md](INSTALL.md)). The Python
  package is on PyPI.

## What else has not been done

- **No mainnet deployment.** No real money has moved.
- **No second person on call.** If the founder is unavailable, nobody answers a report, approves a key or
  cancels a proposal.
- **No organisation account.** The pinned workflows and the relay live in one personal GitHub account; if it is
  suspended, funded orders can only be refunded ([GOVERNANCE.md](GOVERNANCE.md), section 9).
- The first deployment cannot be changed, so its known limits stay ([SECURITY.md](SECURITY.md)). The second
  deployment can be changed, by Knos, only through a multisig with a public 48-hour delay, until an outside review.

## Reproduce the counts

```
git clone https://github.com/drexthealpha/Knos && cd Knos
C=f3dfd3dca73b91d7b3b503e61edc0575e351b99d
T=$(date -u -d '2026-09-14T13:00:00Z' +%s)                      # 06:00 Pacific time on 14 Sep 2026
git rev-list --count $C                                         # 209 commits
git log $C --format=%at | awk -v t=$T '$1 < t' | wc -l          # 83 of them before the hackathon
git log $C --reverse --format=%aI | head -1                     # the first: 2026-09-01T06:14:57+01:00
git ls-tree -r --name-only $C | while read -r f; do             # every text file at that commit
  git diff --numstat 4b825dc642cb6eb9a060e54bf8d69288fbee4904 $C -- "$f" | grep -q '^-' && continue
  git blame --line-porcelain $C -- "$f" | awk -v t=$T '/^author-time /{n++; if ($2 < t) o++} END {print n+0, o+0}'
done | awk '{n += $1; o += $2} END {print o, "of", n}'           # 423 of 39778
```

Counted by commit time before 00:00 UTC on 14 Sep 2026 instead, 82 commits predate the hackathon; the line count
is the same.
