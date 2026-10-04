# The dependency on one personal GitHub account, and the plan to end it

Knos depends on one personal GitHub account, `drexthealpha`, which belongs to the founder. This page says what
lives there, what would happen if the account were suspended or lost, and what moves to an organisation and when.
None of the moves below has been made.

## What lives in the account today

| what | where | what depends on it |
|---|---|---|
| The pinned workflows a repository calls (`fund.yml`, `prove.yml`, `attest.yml`, `check.yml`) | `drexthealpha/knos-workflows`, at one pinned commit that every order records | Every payment. The escrow accepts a token only from that workflow file at that commit. |
| The key-rotation workflow | `drexthealpha/knos-oidc-rotate`; the verifier accepts its attestation only from repositories of this one account (GitHub id 142920951) | Registering a new signing key of an issuer. A registered key expires after 30 days unless it is attested again. |
| The claim workflow and its template | `drexthealpha/knos-oidc-rotate` (`claim.yml`, pinned in `knos-pay`) and `drexthealpha/knos-claim` | A payee binding a wallet to a GitHub account. |
| The public relay | run from the account | Carrying a signed token to the chain when the repository's own run did not. Anyone can relay, and the program tips whoever does. |
| The site, the source and the releases | `drexthealpha/Knos` and its GitHub Pages | The forms, the Numbers page, the recording. |

## What happens if the account is suspended

- **Funded orders can only be refunded.** With the account suspended its repositories are unavailable, so the
  pinned workflows cannot be called, no new token comes from them, and the escrow accepts no other. Nothing can be
  paid.
- **Refunds still work.** A refund needs no token, no GitHub and no action by Knos: at an order's deadline the
  instruction that returns the amount and the fee to the funder can be sent without any of them. No money is lost;
  it is late.
- **Keys lapse.** With nobody able to run the rotation workflow, the registered signing keys expire after 30 days,
  and after that the verifier accepts no token until a key is attested again, which needs the account or an upgrade.
- **The way back is an upgrade.** The programs are upgradeable only through a multisig with a public 48-hour delay,
  until an outside review. An upgrade can pin workflows in another account. It takes at least those 48 hours, and
  every key of that multisig is the founder's today.
- **What is not affected:** the programs themselves, the record on chain, and a count already recorded.

A lost password or a deleted repository has the same effect as a suspension. So does a GitHub decision that the
account breaks its terms, whether or not it does.

## What moves to an organisation, and when

Each step is a public change. Steps 2 and 3 are program upgrades and pass through the 48-hour delay like any other.

| step | what moves | when | what it needs |
|---|---|---|---|
| 1 | A GitHub organisation is created with two owners. The source, the site and the releases move there. GitHub redirects the old addresses. | First, before any real money. It changes nothing on chain. | A second person. There is none today. |
| 2 | The pinned workflows are published from the organisation, and the programs accept a workflow pin under either owner id for a period, so that orders funded under the old pin still pay. | With the first upgrade after step 1. | An upgrade. New orders record the organisation's pin; old ones finish on the old. |
| 3 | The rotation and claim workflows move, and the verifier accepts attestations from the organisation's id as well as the account's, then only the organisation's. | With the same upgrade, or the next. | An upgrade, and the guardian's approval of the first key attested from the new place. |
| 4 | The relay runs from the organisation, and a second relay runs somewhere that is not GitHub at all. | After step 2. | Nothing on chain: anyone can relay. |
| 5 | The personal account is removed from every pin. | After the last order funded under the old pin has been paid or refunded, holdbacks included. | An upgrade. |
| 6 | The multisig's keys are held by more than one person. | Before any real money. | Outside signers. There are none today. |

An organisation removes the single password and the single person. It does not remove GitHub: an organisation can
be suspended too. Two things reduce that, and neither is built for payment today: a second issuer (the verifier
already checks GitLab's tokens) and a workflow pin under more than one owner at a time, which step 2 introduces.

## What is not promised

No date is given for step 1, because it waits on a second person. Until then the plain statement is the one at the
top: one personal account, and if it were suspended, funded orders could only be refunded.
