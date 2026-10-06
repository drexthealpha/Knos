# Who builds Knos, and who it needs

The neutral meter for AI agent work: neither side keeps the count.

Everything below the first section is a plan, and no part of it is a fact.

## Today: one person

Each line is said once here, with what would change it.

| today | what would change it |
|---|---|
| **One founder, pseudonymous:** the GitHub account [drexthealpha](https://github.com/drexthealpha). No legal name is published. | The founder publishes a name, or a second person is named here. |
| **No co-founder,** employee, adviser or contractor. | A person joins and agrees to be named on this page. |
| **No legal entity.** | A company is formed; its name and registration are printed here. |
| **No legal advice taken.** | A lawyer is engaged; [REGULATION.md](REGULATION.md) says who and on what. |
| **No outside review** of the code, the workflows or the documents. | A reviewer publishes findings; [ASSURANCE.md](ASSURANCE.md) links them. |
| **Outside key holders today: 0.** All three member keys of both multisigs, the account the pinned workflows live in, and the relay are the founder's. | One person opens a "Key holder request" ([KEYHOLDER.md](KEYHOLDER.md)) and the founder runs one command ([GOVERNANCE.md](GOVERNANCE.md), section 5). |
| **No second operator.** | Someone else runs the checklist in [OPERATOR.md](OPERATOR.md) and its drill is recorded. |

The commits are written with coding agents; he reviews and commits each one and is responsible for it
([DISCLOSURE.md](DISCLOSURE.md), "How the code is written").

### What he has shipped

Dates are the release commits' dates in UTC (`git log`) and the dates [CHANGELOG.md](../CHANGELOG.md) prints.

| when | release | what it was |
|---|---|---|
| 1 to 7 Sep 2026 | Knos 0.1.0 to 0.1.8 | a shared local memory for coding agents, a different product ([DISCLOSURE.md](DISCLOSURE.md) has what of it remains) |
| 30 Sep 2026 | 0.2.0, 0.2.1, 0.3.0 | claims enforced at edit time; the first turn toward paid work |
| 1 Oct 2026 | 0.3.1 to 0.3.7 | several products tried in one day around one measured fact, that an agent's "tests pass" is often false; the first on-chain check of GitHub's signature |
| 2 Oct 2026 | 0.3.9, 0.3.10, 0.3.11 | one product kept: two programs on devnet, payment on a merge that GitHub signs, the free check, the site |
| 3 Oct 2026 | 0.3.12 | the second deployment, upgradeable only through a multisig with a public 48-hour delay |
| 4 Oct 2026 | 0.3.13, 0.3.14 | work orders, the meter, the passkey wallet; then a defect of his own found during the upgrade delay, before the build ran, and corrected |
| 5 Oct 2026 | 0.3.15 | a console for whoever approves the invoice, billing by deliverable, and evidence that verifies without devnet |

What that history shows: he ships quickly, writes down what is not done, and found and disclosed his own
double-payment defect. What it does not show: that he has sold anything to anyone, run a security review, or
kept a service running for a customer. He has done none of those for Knos.

[CAPABILITIES.md](CAPABILITIES.md) says how far each thing shipped has got.

## The three roles the plan needs first

**None of the three is hired, engaged, committed or in conversation.** These are descriptions of gaps, in the
order the plan needs them filled.

### 1. Someone who has sold to engineering or finance leaders

The buyer is the person who authorises a supplier's invoice. The founder has never sold to that person.

First 90 days, this person would own:

- Ten conversations from the kit in [submission/INTERVIEWS.md](submission/INTERVIEWS.md), and the published
  count of who said yes, no, and why.
- The first [Pilot](PILOT.md) sold and run, and its four before-and-after measurements.
- The decision, from those results, on whether the price book survives contact with buyers
  ([MARKET.md](MARKET.md), section 3).
- With the founder: forming the legal entity that a Pilot's invoice needs.

### 2. A security lead, to run an outside review

The founder cannot review his own work independently.

First 90 days, this person would own:

- Choosing an outside firm, scoping the review from [ASSURANCE.md](ASSURANCE.md) and
  [INVARIANTS.md](INVARIANTS.md), and publishing its findings and the fixes.
- Holding one key of each multisig, so that no single person can approve an upgrade
  ([GOVERNANCE.md](GOVERNANCE.md)).
- The reporting address, and a rehearsed answer to a report when the founder is away
  ([DRILLS.md](DRILLS.md)).

### 3. Agent-vendor partnerships

The suppliers are agent vendors and agencies that bill per accepted outcome. A supplier that integrates once and
is reused by unrelated buyers is the first advantage that could be earned ([MARKET.md](MARKET.md), section 7).

First 90 days, this person would own:

- One vendor or agency running the count beside its own invoices for a month, and a published comparison of the
  two counts.
- The supplier's side of the first Pilot: the ledger each supplier keeps, and what made it hard to keep.
- The first measurement of supplier reuse: whether any supplier serves a second, unrelated buyer in the same
  format.

## Founder and market: what fits, and what does not

For: he works with coding agents every day, and the problem is his own, since his agents reported passing tests
that had not passed. He measured it on public data before building for it ([BENCH.md](BENCH.md)). He ships, in
public, and writes down what is not done.

Against: the buyer is the person who approves a supplier's invoice, and he has never sold to that person, has
not spoken to one about this, and has never worked in procurement or finance. A procurement process may refuse
a pseudonym. So the fit is with the supplier's side and with the engineering. The buyer's side
is the first role above, and it is empty.

## What an outside key holder would do

A plan. **Nobody holds this role and nobody has been asked.** [KEYHOLDER.md](KEYHOLDER.md) is the page for the
person who would; [GOVERNANCE.md](GOVERNANCE.md), section 4, is the job in full. In short, an outside key holder:

- holds one member key of each multisig, on a device only they control, and is not paid by a buyer or a supplier;
- before voting for an upgrade, rebuilds the program from the proposed commit and compares the hash with the
  proposal's buffer, reads the gate record, reads the diff of the programs, and checks the tests at that commit;
- votes, or does not; and votes to cancel if something is wrong after approval;
- for the guardian, checks a new signing key against the issuer's own published key set before approving it;
- holds nobody's money: no member key can move an order.

One outside key of three gives a second pair of eyes and does not bind the founder, who would still hold two.
Two outside keys of three would. `node scripts/governance.mjs replace-member` prints which of the two a change
leads to before anything is proposed.

## From a personal account to an organisation account

This is a plan. **None of it has been done**, and its first step waits on a second person.

Today the pinned workflows, the key-rotation and claim workflows, the relay, the site and the source all live in
one personal GitHub account. If that account were suspended or lost, funded orders could only be refunded.
[GOVERNANCE.md](GOVERNANCE.md), section 9, has the steps with what changes in the pins and what a paying
repository must re-pin; [submission/DEPENDENCY.md](submission/DEPENDENCY.md) has what each step needs. In short:

1. Create a GitHub organisation with two owners, the founder and one other person, each with their own
   second factor, and move the source, the site and the releases there. This changes nothing on chain. One owner
   alone would change little: the organisation would depend on that one account as the personal account does now.
2. Publish the pinned workflows from the organisation, and have the programs accept a workflow pin under either
   owner for a period, so that orders funded under the old pin still pay. This is a program upgrade and passes
   through the public 48-hour delay.
3. Move the rotation and claim workflows the same way.
4. Run the relay from the organisation, and a second relay somewhere that is not GitHub.
5. Remove the personal account from every pin once the last order funded under it is paid or refunded.
6. Put the multisig's keys in more than one person's hands before any real money moves.

Steps 3 and 5 need program changes that are not in this release.
