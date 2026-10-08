# Hold a key

**Outside key holders today: 0.** One person, the founder, holds all three member keys of both multisigs
([GOVERNANCE.md](GOVERNANCE.md)). This page is for the first person who is not the founder: what a key is for, what
it can never do, and the three steps to ask for one. Everything is on Solana devnet, in test money.

The count is the list `outside` in [`web/keyholders.json`](../web/keyholders.json). It changes only after the
proposal that adds a key has executed on chain.

## What the key is

Knos's four programs can be replaced only by the **upgrade multisig**
`9HcsMEo2o6zZu9t1kbFWpnyKn7hiHaZYYFwNHZSpmWqK`: 2 of its 3 member keys must approve, and the approved upgrade can
run 48 hours later and not before. A second multisig, the **guardian**
`EwqWNR3XwE9RMsJQdH7pZJSx4WERXCKLQdBpMnr8jFx5` (2 of 3, no delay), approves or revokes the signing keys the verifier
accepts and can pause new funding for at most 7 days. A key holder holds one member key.

## What your key can do

- **Cast one vote for a program upgrade,** after checking the build. The four checks, on your own machine, are in
  [GOVERNANCE.md](GOVERNANCE.md), section 4: the bytes, the gate record, the diff, the tests.
- **Not vote.** Nothing obliges you to approve, and nothing expires if you do not.
- **Cast one vote to cancel** an approved upgrade during its 48 hours, or to reject one still collecting approvals.
- **On the guardian, if you hold a key there too:** one vote to approve or revoke a signing key, or to pause new
  funding.

## What your key cannot do

Each line was checked against the programs' source and is tested where a test is named.

| it cannot | why |
|---|---|
| move an order's money | No instruction of `knos_pay` takes a member key. Money leaves an order only by the transfers listed under "WHERE MONEY CAN GO" at the top of [`knos_pay/src/lib.rs`](../programs-v2/knos_pay/src/lib.rs): to the payee a signed token names, to the fee account, or back to where it came from. |
| change an order's terms, payee, amount or deadline | The program has no such instruction ([INVARIANTS.md](INVARIANTS.md)). |
| block a refund | `RefundOrder`, `Refund` and `Withdraw` need no token and no key of Knos's, and the guardian's pause does not apply to them: `Pause` stops `FundBalance`, `FundWallet`, the two order fundings and `TopUp`, and nothing else ([`fund.rs`](../programs-v2/knos_pay/src/fund.rs)). |
| approve an upgrade alone | The threshold is 2. One key is one vote (`scripts/governance.test.mjs`, "the key that writes a build buffer cannot authorise the upgrade, and one member key cannot either"). |
| refuse an upgrade alone, **today** | With one outside key of three, the founder's two keys still meet the threshold. `node scripts/governance.mjs replace-member` prints this before anything is proposed. See "What one outside key changes" below. |

**What two keys together can do.** Two member keys can replace a program, 48 hours after voting in public, and a
replaced program can do anything, including taking every order's money. That is the power the multisig exists to
guard, and it is why your check of the build matters.

## What it costs, and how long it takes

- **Money: nothing.** Devnet has no real money. A vote is a transaction whose fee is paid in devnet SOL, which the
  public faucet gives away (<https://faucet.solana.com>).
- **Joining: three steps,** below. Making the key takes seconds. The proposal that adds your key to the upgrade
  multisig then waits that multisig's own 48 hours.
- **Each upgrade: four checks.** How long they take an outside person has not been measured: nobody outside has
  done them. The longest is rebuilding the program from source ([ASSURANCE.md](ASSURANCE.md) has the commands).
- **How often:** [`web/upgrades.json`](../web/upgrades.json) lists every proposal so far, with its dates.

## The three steps

### 1. Make a key on your own machine

Either of these. Nobody else must ever see the file it makes.

**With the Solana command line:**

```
solana-keygen new --outfile knos-member.json
solana-keygen pubkey knos-member.json
```

The second command prints the public key, an address of 32 to 44 letters and digits.

**In a browser, on the site's "Hold a key" page** (`web/keyholder.js`). The page makes an Ed25519 key with the
browser's own WebCrypto, shows the public key, and saves the private key as `knos-member.json`, the same file format
`solana-keygen` writes. It sends the key nowhere and stores nothing; once the file is saved the page forgets the
private half. This needs Chrome or Edge 137, Firefox 129, Safari 17, or later
([caniuse: SubtleCrypto generateKey, Ed25519](https://caniuse.com/mdn-api_subtlecrypto_generatekey_ed25519)); an older
browser is told so and shown the commands above.

A key made in a web page is only as private as the page and the browser. For devnet that is enough. Before any real
money a key holder's key is made on a hardware wallet, and this page will say so.

### 2. Keep the private key file

Keep `knos-member.json` where only you can read it, and keep a copy. If it is lost, your vote is lost with it; the
other members can replace your key by a vote. Knos never asks for the file, its contents, or a seed phrase.

### 3. Open a "Key holder request"

Open an issue on the repository with the template **Key holder request**
(<https://github.com/drexthealpha/Knos/issues/new?template=key_holder.md>; the site's page fills it in). It asks for
three things: your **public key**, a **name or handle**, and **how to reach you**. The issue is public.

## What happens after you ask

1. The founder confirms, over the contact you gave, that the public key in the issue is yours.
2. The founder prints the change and what will be true after it, and posts that output on your issue:
   `node scripts/governance.mjs replace-member <one of the founder's keys> <your public key>`.
   It sends nothing. Your key gets the permission to vote and no other.
3. The same command with `--send` creates the proposal on each multisig and casts the founder's two votes. On the
   upgrade multisig it can execute 48 hours later; on the guardian, at once.
4. After it executes, `node scripts/governance.mjs show --check` prints the new members, your entry is added to
   `web/keyholders.json`, and the count on this page and on the site becomes 1.

To vote afterwards: `node scripts/governance.mjs approve upgrade <index> --member knos-member.json --fee-payer
<a key with devnet SOL>`, or `cancel` in place of `approve`. `knos status` and the feed
[`web/upgrades.xml`](../web/upgrades.xml) show every pending proposal.

## What one outside key changes, and what it does not

While the founder holds two of the three keys and the threshold is 2, exactly this is true of one outside holder:

| one outside holder of 1 of 3 | can they? | why |
|---|---|---|
| see every proposal, rebuild it, and say in public what they found and how they voted | **yes** | proposals and votes are on chain; the four checks need no permission |
| add one approval to an upgrade | **yes, and it changes nothing** | the founder's two approvals already meet the threshold |
| approve an upgrade alone | **no** | one vote of the two needed |
| block or cancel an upgrade alone | **no** | a proposal fails only when the keys that have not approved are too few to reach the threshold: with three members and a threshold of 2 that takes two rejections, and the founder's two keys can approve whatever the third does ([Squads v4, `cutoff`](https://github.com/Squads-Protocol/v4/blob/main/programs/squads_multisig_program/src/state/multisig.rs): voters minus threshold plus one) |
| pause funding, or approve or revoke a signing key, alone (guardian) | **no** | the guardian is 2 of 3 as well |
| stop the founder replacing their key | **no** | changing members takes two votes, which the founder has |

So today's honest description is: **a witness with a vote, not a check.** Nobody may describe one outside key of
three as independent approval, a veto or shared control.

One outside key of three is a second person who sees every proposal and can say in public that they did not
approve it. It does not bind the founder, who would still hold two keys and can approve alone. The founder stops
being able to approve alone when a second outside key replaces a second founder key, or when the threshold becomes
3 of 3. `node scripts/governance.mjs replace-member` and `set-threshold` print which of the two states a change
leads to ("the founder alone can STILL approve" or "can NOT"), and what a threshold of 3 of 3 costs: one lost key
and nothing can be approved again.

## What a key holder is not

Not an employee, an adviser, an auditor or a co-founder, and not paid by Knos, a buyer or a supplier. Holding a key
is not a review of the code and nobody may describe it as one.
