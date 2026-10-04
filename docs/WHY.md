# Why Knos

The argument, with its sources. Every outside source was read on 2 or 3 Oct 2026; a date beside a link is the
source's own date. "Secondary" marks a number read in coverage of the original, not in the original.

## 1. An agent's word costs nothing, so it is not evidence

Coding agents open a large share of pull requests. One tracker counts about 1.7 million a week across the six
agents it follows, and marks 32.5% of the pull requests it sampled as agent-made
([amplifying.ai](https://amplifying.ai/coding-agents/trends), data to 27 Sep 2026; the total is our sum of its
per-agent figures, and three of those are its estimates from declared attribution).

We measured what those pull requests say against what happened. In 826 repositories, the first agent pull request
whose description said tests or CI pass had a failing check at its head commit in 147 (17.8%). Counting every such
pull request instead of one per repository gives 660 of 2,431 (27.1%); that figure leans on a few busy repositories,
so we quote the first ([BENCH.md](BENCH.md), measured 2 Oct 2026; a new scan is scheduled every 6 hours). A failing
check is GitHub's record. It does not say why the check failed, and a description can be written before CI finishes.
What it shows is that the description is not evidence.

Others found the same from the inside:

- 63% of one model's successful SWE-bench Pro resolutions had retrieved the fix rather than derived it. With git
  history sealed and the network restricted, scores fell sharply
  ([Cursor, 25 Jun 2026](https://cursor.com/blog/reward-hacking-coding-benchmarks)).
- METR had 4 maintainers of 3 repositories review agent patches that passed the tests of SWE-bench Verified, 296
  pull requests in all. Roughly half would not have been merged, and the maintainers' decisions ran about 24
  points below the benchmark's scores
  ([METR, 10 Mar 2026](https://metr.org/notes/2026-03-10-many-swe-bench-passing-prs-would-not-be-merged-into-main/)).
  METR adds that the agents had one attempt and no feedback.

Spence described this in 1973 ("Job Market Signaling", Quarterly Journal of Economics 87): a signal carries
information only if it is costly to fake. "All tests pass" in a description costs nothing to write.

## 2. So paid work for strangers breaks down

Akerlof (1970) showed what happens when a buyer cannot tell good from bad: "the presence of people who wish to pawn
bad wares as good wares tends to drive out the legitimate business"
([The Market for "Lemons"](https://www.sfu.ca/~allen/Ackerlof.pdf), Quarterly Journal of Economics 84). It is
happening to paid open-source work now:

- On the Algora board, settled payouts fell from 1,470 in 2025 to 175 in 2026 up to 10 Aug, with 2 in the 30 days
  before that date ([incubagent, 10 Aug 2026](https://incubagent.com/research/agent-bounty-market/); in its words,
  "one venue on one date").
- curl ended its bug bounty on 31 Jan 2026, after 87 confirmed vulnerabilities and over 100,000 USD paid. The share
  of reports that were real fell from "north of 15%" to "below 5%" in 2025
  ([Stenberg, 26 Jan 2026](https://daniel.haxx.se/blog/2026/01/26/the-end-of-the-curl-bug-bounty/)).
- OnlyDust closed after paying 18 million USD in grants to 4,000 contributors over four years: "Low-skill
  contributors were flooding them with AI-generated code" ([onlydust.com](https://www.onlydust.com/)).
- Across every board, 59 verified bounties worth 64,291 USD were open on 2 Oct 2026
  ([BountyOS](https://bountyos.rovidev.com/en/github-bounty-board/)).

Supply is not what is missing. Agents will answer any bounty. What is missing is a way for a buyer to pay only for
work that held up, and for a worker to know the money is there.

## 3. Paying per result already exists, where the seller keeps the meter

Intercom charges 0.99 USD per outcome for its support agent, Fin, which has passed 100 million USD of annual
recurring revenue ([Sacra](https://sacra.com/research/intercom), secondary). For code, Sourcegraph began billing one product per merged changeset on 14 Sep 2026: "If it doesn't get
merged, you don't pay" ([changelog](https://sourcegraph.com/changelog/agentic-batch-changes-ga),
[its note on pricing, 16 Sep 2026](https://sourcegraph.com/blog/agentic-batch-changes-pricing)). In both the
seller's own system counts the results. Buyers object to that: "Attribution disputes are where these contracts
fall apart" (a director at Twilio, in
[CIO, 16 Jun 2026](https://www.cio.com/article/4184688/it-hurtles-toward-the-great-enterprise-pricing-reset.html)).

Code has something support does not: a third party that already records the result. GitHub records who opened a
pull request, what its checks concluded and who merged it, and it signs statements about a workflow run for free.
What was missing is a way to move money on that signature, for any seller, with nobody in the middle who could
forge it or keep the money.

## 4. What has been tried before, and the rule Knos takes from each

The first two parts are the history that explains the design, in one page. The rest are single lessons.

### Letters of credit: payment against documents a third party signed

A seller in one port and a buyer in another cannot see each other's goods or money. The letter of credit solved
that. A bank promises to pay the seller against documents that someone other than the seller signed, above all the
carrier's bill of lading. The seller ships because the bank's promise does not depend on the buyer's mood. The
buyer accepts because the bank pays only on the documents the credit names. In 2011 letters of credit covered
12.5% of world trade, 2.3 trillion USD
([Niepmann and Schmidt-Eisenlohr, VoxEU, 11 Jun 2016](https://cepr.org/voxeu/columns/trade-finance-around-world)).
The banks' rules are the UCP 600, the 2007 revision
([text](https://pacliirms.austlii.edu.au/pits/en/treaty_database/2006/14.html)).

| UCP 600 | the rule Knos takes |
|---|---|
| Article 4: "A credit by its nature is a separate transaction from the sale or other contract on which it may be based." | The escrow is separate from any argument about the work. It hears no disputes. |
| Article 5: "Banks deal with documents and not with goods, services or performance to which the documents may relate." Article 14(a): they examine "on the basis of the documents alone". | The program reads GitHub's signed statement and the order's terms, and nothing else. It never looks at the code. |
| Article 15(a): "When an issuing bank determines that a presentation is complying, it must honour." | A pay token that matches the terms is paid in the transaction that verifies it. Nobody can veto it. |
| Article 14(b): the bank has "a maximum of five banking days" to examine. Article 16: a refusal needs a single notice that states "each discrepancy"; a bank that fails to give it "shall be precluded from claiming that the documents do not constitute a complying presentation". | The time to object is fixed and comes first. A maintainer who does not want a pull request to be paid says so before merging (`/knos reject`, with the reason). Merging is acceptance. |
| A credit has an expiry date. With no complying presentation by then, the bank owes nothing. | With no payment by the deadline, the funder is refunded. The refund needs no token. |

**The strict-compliance rule.** A bank pays only when the documents match the credit. The English courts put it
this way in 1926: "There is no room for documents which are almost the same, or which will do just as well"
(Viscount Sumner in Equitable Trust Co of New York v Dawson Partners, quoted in
[Fortis Bank v Indian Overseas Bank, 2009, paragraph 18](https://caselaw.nationalarchives.gov.uk/ewhc/comm/2009/2303)).
The UCP 600 softens the wording, not the idea: data "need not be identical to, but must not conflict with" the
credit (Article 14(d)). The rule is harsh on a seller with a typing error, and it is why the instrument works: a
bank that needs no judgment can promise payment to a stranger.

Knos applies the rule to a machine-readable document. The terms are hashed when the order is funded. The pay token
must carry that hash, the head commit, the payees and the order's address, signed by the workflow commit the order
recorded. A token that is almost the same is refused. No instruction changes what must be true for payment after
funding. A funder can add money, or cancel with 7 days' notice during which a valid pay token still pays.

**What the rule cannot do.** The documents can be in order and the goods bad. Article 5 says so in terms: the bank
does not deal with the goods. For Knos the checks can pass and the change can still be poor. That is why the
default also asks for a person's merge, and why a funder can keep part of the money back for a warranty period,
set at funding and public before the work starts.

### Escrow in marketplaces, and where disputes arise

Stand-alone escrow lost to payment built into the marketplace. In 2001 "only 6% of online auction buyers" had paid
through an online escrow service. Escrow.com charged 3% by cheque or money order and 6% by card, and the authors
found that stand-alone escrow "may have difficulty surviving" where expected fraud is low
([Hu, Lin, Whinston and Zhang, Information Systems Research 15(3), 2004](https://www.scheller.gatech.edu/directory/research/information-technology-management/zhang/pdf/isr-escrow.pdf)).
What won was a payment inside the marketplace's own flow: in July 2002 "about 60 percent of PayPal's business"
came from eBay users ([Associated Press, 8 Jul 2002](https://www.paypalobjects.com/html/press/070802APEbayBuys.html)).

Escrow inside a marketplace moves the dispute to the moment of release. On Upwork a fixed-price dispute opens in
two cases: a client ends a contract "with a deposited balance and requests a refund", or the freelancer "submitted
work for a contract or milestone, but the client hasn't released the payment". A party has "seven calendar days"
to file. An agent then gives "a non-binding resolution", and the last step is "a binding arbitration service"
that the parties buy
([Upwork](https://support.upwork.com/hc/en-us/articles/211068528-Dispute-a-fixed-price-contract)). Both cases
have one cause: the money is in escrow, and what counts as done was left to a person to decide afterwards.

Where the buyer decides alone, the seller carries the risk. On Mechanical Turk, "Requesters have the right to
reject a Turker's completed work without payment" while "retaining ownership rights to the rejected work", and the
platform "is not involved in resolving any labor disputes". Workers answer by avoiding requesters they do not know
and by choosing tasks with concrete criteria
([McInnis, Cosley, Nam and Leshed, CHI 2016](https://bpb-us-w2.wpmucdn.com/sites.coecis.cornell.edu/dist/1/6/files/2016/06/p2271-mcinnis-16rd8kx.pdf);
437 comments from 391 workers).

The rules Knos takes:

- **No separate place to go.** Funding is a comment on the issue, or one transaction from a wallet. Payment
  follows the merge. The result is a comment on the pull request.
- **Done is defined before the work, by a record neither side writes.** Release is not a button the buyer
  presses. That removes "submitted, but not released".
- **Once the work is accepted, the buyer cannot take the money back.** The only money that can return after a
  merge is a holdback the funder set at funding, and only if the change is reverted inside the warranty.
- **The buyer cannot withhold the evidence either.** After a merge the seller can have the pinned workflow read
  GitHub's public record from a repository of the seller's own.
- **Ending early has a price and a notice.** A funder can cancel with 7 days' notice. A valid pay token inside the
  notice still pays. If the order was reserved, the share named at funding goes to the person who held it.
- **Who rules on a dispute is chosen at funding, or nobody is.** An order may name an arbiter. An order that named
  none has no such path.

What Knos does not fix: before the merge a maintainer can still read a pull request, decline it and write the same
change. The merge button stays with the buyer.

### Bountysource: the custodian was the risk

Bountysource announced terms, to start on 1 Jul 2020, under which a bounty with no accepted solution after two
years "will be retained by Bountysource"; it withdrew them after protest
([borg issue 5230](https://github.com/borgbackup/borg/issues/5230)). From June 2023 payout requests went
unanswered. At least 21,702.10 USD of completed work was left unpaid, and its owner announced bankruptcy in 2023
([boehs.org, 3 May 2024](https://boehs.org/node/bountysource)).

The rule: no company holds the money. It sits in a program. Money with no payment returns to the funder at the
deadline, without a token and without an operator. A payment held for a payee who gave no address returns after
180 days. A prefunded balance can be withdrawn only by the wallet that opened it. One custodian risk remains and
is stated: until an outside review, Knos can change the program through a multisig after a public 48-hour delay.

### tea.xyz: a reward computed from countable things gets farmed

Over 150,000 npm packages were published to farm tea's rewards, "artificially inflating package metrics through
automated replication and dependency chains"
([AWS Security Blog, 13 Nov 2025](https://aws.amazon.com/blogs/security/amazon-inspector-detects-over-150000-malicious-packages-linked-to-token-farming-campaign/)).

The rule: Knos computes no reward and pays from no pool. Every payment is one funder's own money for one merge in
the repository that funder chose. The public record counts distinct funders, and keeps self-payment and test money
out of its totals.

### curl's bounty: cash plus free submission floods the examiner

curl's numbers are in section 2. The cost fell on the people who had to read every report.

The rule: an order can be reserved. An assigned issue pays only its assignee, and `/knos take` reserves an
unassigned one for 7 days unless the funder set another number. The free check marks a false "tests pass" before a
person reads the pull request. Knos does not remove the review work. A maintainer who is flooded should also use
GitHub's own limits ([COMPARE.md](COMPARE.md)).

### Akerlof: a third party's certificate counters a market for lemons

Akerlof's remedies are guarantees, brand names and licensing: someone other than the seller vouches for quality.

The rule: GitHub's signature is the certificate. It certifies only what GitHub records, and section 6 says what
that leaves out.

### Holmström, and Holmström and Milgrom: pay on every informative signal, not only the measurable one

Holmström (1979): "an optimal contract should link payment to all outcomes that can potentially provide
information about actions that have been taken". Holmström and Milgrom (1991): pay teachers on test scores and
they "might spend too little time teaching equally important (but harder to measure) skills"
([the Nobel committee's summary, 2016](https://nobelprize.org/uploads/2018/06/popular-economicsciences2016-1.pdf)).

The rule: pay on two signals together, a maintainer's merge and the funded checks at the merged pull request's
head commit. Payment without a merge ("tests mode") is offered only when the acceptance bundle is black-box: the submission runs
as a separate process and only its output is compared. Everything else is funded in merge mode
([TAMPER.md](TAMPER.md) has the measured reason).

### METR: a patch that passes the tests is often not one a maintainer would merge

About half, in METR's review (section 1).

The rule: the default acceptance is the merge. Checks are necessary and not sufficient.

## 5. Why a chain, and why Solana

A chain gives this three things a company cannot promise. The money is committed before the work, in a program and
not in a company's account (Bountysource). The payee needs no account with a payment company, only a GitHub account
and an address, which can be a wallet made from a passkey. And the verifier is a program any other program can call ([OIDC.md](OIDC.md)). A company running
the same escrow would be one more party to trust. Until an outside review Knos is still such a party, through its
multisig (section 4, Bountysource).

Solana, for two reasons. Verifying GitHub's RSA-2048 signature on chain takes 2 transactions of under 1 million
compute units each, and on the first deployment carrying a whole token took 7 transactions and 35,000 lamports of
fees ([BENCH.md](BENCH.md), measured). And agent payments already run there: by Artemis data that Solana posted on
22 Sep 2026, Solana carried 23.2 million x402 transactions in four weeks, 76% of the count
([Solana Compass, 22 Sep 2026](https://solanacompass.com/news/solana-processes-76-of-all-x402-ai-agent-transactions-232-million-in-four-weeks)).
That figure counts transactions, not money, and it says nothing about whether any work was done. A payment rail
moves money when someone says so. Knos is about who may say so.

## 6. What Knos does not cover

**A signature authenticates a statement, not the truth of the world.** GitHub's signature says that GitHub issued
this token to this workflow, at this commit, in this repository. It does not say that the merged code is good.
It does not say that the maintainer and the author are independent people. And GitHub does not sign what the
workflow read: which checks passed and who the author is are the workflow's reading of GitHub's record, as
trustworthy as the repository it ran in.

**Finite tests do not establish that software does everything intended.** A check that passed shows that this
check passed. Of 63 cheating pull requests in [TAMPER.md](TAMPER.md) (21 ideas in each of three sample
repositories), plain CI was fooled by 56. METR's maintainers
would not have merged about half of the patches that passed. That is why the default asks for a person's merge as
well, and why a merge is still only that person's judgment.

**A program that depends on GitHub inherits GitHub's failures.** If GitHub is down, pay tokens wait. If GitHub signs
something false, or one of its signing keys leaks, the program believes it until the key expires or the guardian
revokes it. If GitHub changes its tokens or its rules for workflows, Knos has to change too. If GitHub closes an
account, its owner cannot bind a wallet. One thing does not depend on GitHub: a refund at the deadline needs no
token.

[SECURITY.md](SECURITY.md) says who has to be trusted for what.
