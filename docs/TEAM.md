# Who builds Knos, and who it needs

## Today: one person

Knos is built by one founder, known publicly only as the GitHub account
[drexthealpha](https://github.com/drexthealpha). That is a pseudonym; no legal name is published. There is no
co-founder, no employee, no adviser, no contractor and no company. Every upgrade key, the account the pinned
workflows live in, and the relay are his alone ([GOVERNANCE.md](GOVERNANCE.md),
[submission/DEPENDENCY.md](submission/DEPENDENCY.md)).

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

What that history shows: he ships quickly, writes down what is not done, and found and disclosed his own
double-payment defect. What it does not show: that he has sold anything to anyone, run a security review, or
kept a service running for a customer. He has done none of those for Knos.

[CAPABILITIES.md](CAPABILITIES.md) says how far each thing shipped has got.

## The three roles the plan needs first

**None of the three is hired, engaged, committed or in conversation.** Nobody has been approached. These are
descriptions of gaps, in the order the plan needs them filled.

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

No one outside Knos has reviewed the programs, the workflows, the relay or the clients. The founder cannot review
his own work independently.

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

## From a personal account to an organisation account

This is a plan. **None of it has been done**, and its first step waits on a second person.

Today the pinned workflows, the key-rotation and claim workflows, the relay, the site and the source all live in
one personal GitHub account. If that account were suspended or lost, funded orders could only be refunded.
[submission/DEPENDENCY.md](submission/DEPENDENCY.md) has the full plan and what each step needs; in short:

1. Create a GitHub organisation with two owners, and move the source, the site and the releases there. This
   changes nothing on chain.
2. Publish the pinned workflows from the organisation, and have the programs accept a workflow pin under either
   owner for a period, so that orders funded under the old pin still pay. This is a program upgrade and passes
   through the public 48-hour delay.
3. Move the rotation and claim workflows the same way.
4. Run the relay from the organisation, and a second relay somewhere that is not GitHub.
5. Remove the personal account from every pin once the last order funded under it is paid or refunded.
6. Put the multisig's keys in more than one person's hands before any real money moves.

No date is given, because step 1 needs a person who does not exist yet. Steps 2, 3 and 5 need program changes that
are not in this release.
