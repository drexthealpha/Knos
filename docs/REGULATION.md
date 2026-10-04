# Regulation: what has been examined, and what has not

**This is not legal advice.** It was written by the people who built Knos, from public documents. No lawyer has
read it. Counsel is needed before any real money moves, and none has been asked. Knos runs on Solana devnet, and
its money is test USDC.

Three questions were examined, each only as far as one public source goes: whether holding money in a program is
money transmission under United States federal rules; what a payer owes in tax reporting when it pays a
contractor; and what sanctions law asks before a payout. Everything else is listed at the end as not examined.
Sources were read on 3 Oct 2026. What the product does was brought in line with Knos 0.3.14 on 4 Oct 2026; no source
was read again for it, and no conclusion below was checked by anyone outside Knos.

## 1. Is the escrow money transmission?

### What the product does

- A funder moves USDC into a token account that belongs to one order. The address is derived by the program. No
  person holds a key to it.
- The program pays the payee when it has verified a GitHub-signed token that matches the order's terms. With no
  payment by the deadline, anyone can send the refund, and it goes back to the funder.
- In normal operation Knos has no instruction that moves an order's money. Its guardian can pause new funding and
  revoke a signing key. It cannot pay, redirect or take ([SECURITY.md](SECURITY.md), section 6).
- Knos receives a fee, into its own token account, when an order is paid. The funder pays it on top of the amount:
  2.5% of the first 1,000, 1% from 1,000 to 50,000, 0.5% above, at least 0.40. A refund returns it.
- An order holds at most 100,000 on devnet (it was 500 before 0.3.14). A mainnet cap is not decided. The size of
  a single payment bears on every question on this page, and none was examined at that size.
- **Knos can change the program** through a multisig, after a public 48-hour delay. An upgrade "could do anything,
  including taking every vault" ([SECURITY.md](SECURITY.md), section 7). The multisig is 2-of-3 and every member
  key is the founder's: no second person has to agree ([GOVERNANCE.md](GOVERNANCE.md)).
- **That does not end with an outside review.** The decision recorded in [GOVERNANCE.md](GOVERNANCE.md), section 7,
  is that the verifier is frozen after a review and the escrow stays upgradeable behind the delay. So Knos keeps
  the power to replace the program that holds the money, with notice, for as long as that decision stands.
- A funder with only a passkey can fund an order from a passkey wallet. A relayer, today Knos's, pays the network
  fee of that transaction; it cannot change the amount, the order or the destination, which the passkey signed.
- An order can belong to a GitLab project as well as to a GitHub repository. Nothing below depends on which.
- The meter (`knos_meter`) moves no customer money. It holds credits a customer prepaid to Knos for Knos's own
  fee, per evaluation or per batch of evaluations.

### What the guidance says

FinCEN's guidance of 9 May 2019, FIN-2019-G001, "Application of FinCEN's Regulations to Certain Business Models
Involving Convertible Virtual Currencies"
([text](https://www.fincen.gov/sites/default/files/2019-05/FinCEN%20Guidance%20CVC%20FINAL%20508.pdf)):

| section | what it says |
|---|---|
| 4.2.1, wallets | How a wallet is treated depends on four things: "(a) who owns the value; (b) where the value is stored; (c) whether the owner interacts directly with the payment system where the CVC runs; and, (d) whether the person acting as intermediary has total independent control over the value." |
| 4.2.1, users | "In so far as the person conducting a transaction through the unhosted wallet is doing so to purchase goods or services on the user's own behalf, they are not a money transmitter." |
| 4.2.2, multiple-signature wallets | A provider that "restricts its role to creating un-hosted wallets that require adding a second authorization key to the wallet owner's private key in order to validate and complete transactions" is "not a money transmitter because it does not accept and transmit value." If it "combines the services of a multiple-signature wallet provider and a hosted wallet provider", it is one. |
| 5.2.2, applications | Developing an application is "outside the definition of money transmission". But "if the developer of the DApp uses or deploys it to engage in money transmission, then the developer will qualify as a money transmitter." |
| 2, exemptions | A person who only provides "the delivery, communication, or network access services used by a money transmitter", and a person who accepts and transmits funds "only integral to the sale of goods or the provision of services, other than money transmission services", are exempt. |

### What it does not say

The guidance has no passage on an escrow program that holds money with no custodian and releases it on a
condition. Any conclusion for Knos is our inference, not the guidance's.

| pointing away from transmission | pointing toward it |
|---|---|
| The funder is buying a service on its own behalf (4.2.1, users). | Knos wrote the program and deployed it (5.2.2). |
| Knos holds no key to an order's money and cannot move it in normal operation (4.2.1, factor d). | Knos takes a fee from each payment. |
| The funder and the payee interact with the chain directly, or through a relay that decides nothing (factor c). | Until an outside review Knos can replace the program, after 48 hours, and a replacement could move the money. That bears on "total independent control". |
| | Knos runs the public relay. A relay decides nothing, but today it is the one that carries the tokens, and for a passkey funder it also pays the network fee. |
| | One person holds every key that can replace the program. |

This is the first question for counsel. The answer may differ once independent people hold keys of the multisig,
and it does not go away after an outside review, because the escrow is meant to stay upgradeable.

### Not examined

- State money-transmitter laws in the United States. The guidance does not cover them.
- Any other country's rules on payment services, electronic money or crypto-asset services.
- Whether prepaid meter credits are a stored-value product.
- Whether paying a funder's network fee, or holding money in a wallet derived from a funder's passkey, changes who
  is the intermediary.
- Whether an advance against an assigned payment is lending, and for whom.

## 2. Paying contractors: tax reporting

A work order paid to someone outside the funder's company is a payment for services. The funder is the payer. Knos
is not a party to the payment. That, too, is our reading and a question for counsel.

### What was read

- **The payer, in the United States.** Form 1099-NEC is filed "for each person in the course of your business
  during the year to whom you have paid at least $2,000". The threshold rose to 2,000 USD for tax years that begin
  after 2025 ([IRS, instructions for Forms 1099-MISC and 1099-NEC, revision of December 2026](https://www.irs.gov/instructions/i1099mec)).
  Those instructions say nothing about a payment made in a digital asset. We found no IRS page that tells a payer
  how to report one.
- **The payee, in the United States.** "For payments you receive as an independent contractor, report the digital
  asset income on Schedule C", at "the fair market value as measured in U.S. dollars"
  ([IRS, digital assets](https://www.irs.gov/filing/digital-assets)). Form 1099-DA, on the same page, is for
  brokers, not for someone who pays a contractor.

### What the product does

- It keeps a record a payer can file from. `knos receipts`, `knos statement` and `knos export` write, for each
  payment: the time, the repository, the payee, the amount, the fee and the transaction. CSV for finance, JSON
  Lines for a log system, an invoice per period ([`src/knos/records.py`](../src/knos/records.py)). Everything in them is recomputed from the programs' own
  logs, so anyone can check a statement against the chain.
- An organisation's policy file can name who may be paid ([`src/knos/policy.py`](../src/knos/policy.py)).

### What the product does not do

- It collects no tax form and no taxpayer number. A payee is a GitHub account and an address. Knos gives the payer
  no name and no country.
- It withholds nothing and files nothing.
- It does not decide whether a payee is a contractor or an employee.
- It does not add up what one payer paid one payee in a year against a reporting threshold. With orders of up to
  100,000, one order can pass it.

### Not examined

- Withholding on payments to people outside the United States.
- Value-added and sales taxes.
- Tax reporting in any other country.
- How Knos's own fee income is taxed.

## 3. Sanctions

### What was read

The Office of Foreign Assets Control's "Sanctions Compliance Guidance for the Virtual Currency Industry", October
2021 ([text](https://ofac.treasury.gov/media/913571/download?inline)):

- "All U.S. persons are required to comply with OFAC regulations."
- OFAC "may impose civil penalties for sanctions violations generally based on a strict liability legal
  standard": a person "may be held civilly liable for sanctions violations even without having knowledge or reason
  to know it was engaging in such a violation."
- "In 2018, OFAC began including certain known virtual currency addresses as identifying information for persons
  listed on the SDN List."
- Companies should "employ tools sufficient to identify and block transactions associated with blocked persons,
  including transactions associated with those virtual currency addresses included on the SDN List."

Separately, the issuer of USDC can act on its own: "Circle reserves the right to 'block' certain USDC addresses"
([USDC terms, 12 Dec 2025](https://www.circle.com/legal/usdc-terms)). That control is Circle's, not Knos's.

### What the product does

Before a workflow asks for a pay token, it checks the payout address against the digital-currency addresses on
OFAC's list ([`src/knos/screen.py`](../src/knos/screen.py)). A listed address is refused, the reply says so, and
the money is held. When the list cannot be fetched the check says "not screened" and does not pretend to have
passed.

### What the product does not do

- **It matches addresses, nothing else.** An address that is not on the list is not cleared. Nobody's name,
  country or ownership is checked. A GitHub account is not an identity document.
- **The program does not enforce it.** The check runs in the workflow. A funder may pin other workflows than the
  published ones, and a token from a workflow that does not screen is still a valid token.
- **No monitoring.** Nothing watches where money goes after a payout.
- **No identity checks of funders or payees**, and no programme, officer or training of the kind the guidance
  describes.

### Not examined

- Whether Knos, a funder, or a relayer is the person who must comply for a given payment.
- Sanctions lists other than OFAC's.
- Anti-money-laundering rules beyond the question in section 1.

## 4. Other law, not examined

- Consumer protection, and the terms a funder and a payee would agree to. There are no terms of service.
- Data protection. A public chain keeps what is written to it for ever: GitHub account ids, addresses, amounts,
  and for a public order the repository and the terms. None of it can be erased on request
  ([CONTROLS.md](CONTROLS.md), "Data on chain").
- Securities and commodities law. Knos has no token and issues nothing.
- Employment law, where a standing order pays the same person month after month.
- Export controls.

## 5. Before real money

1. Counsel on sections 1 to 3, for the country Knos is run from and for the first customers' countries.
2. A decision, in writing, on who the payer of record is for a payment and who screens it.
3. A named legal entity as the operator, and terms of service. Neither exists today: Knos is one person, known
   publicly by a GitHub account, and no company has been formed ([DISCLOSURE.md](DISCLOSURE.md)).
4. A review of the programs by a security firm. No security firm has audited anything
   ([SECURITY.md](SECURITY.md)). That is a separate gate from this page, and `knos mainnet-check` fails on it on
   purpose.
5. Keys of the upgrade multisig held by more than one person, so that the question of control in section 1 has a
   different answer than "one person".
