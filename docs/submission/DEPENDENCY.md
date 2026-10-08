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

# The dependency on the memory engine

Everything Knos remembers is kept by one outside library: the Sibyl memory engine, `sibyl-memory-client`
([PyPI](https://pypi.org/project/sibyl-memory-client/), [source](https://github.com/Sibyl-Labs/Sibyl-Memory)), pinned
at 0.8.1 or later in `pyproject.toml`. It is one SQLite file on the machine that runs Knos, searched with SQLite's
FTS5; there is no service to call and no model. Knos keeps no second store, no cache and no side file. This part says
what the engine is used for, call by call, and what stops working without it.

A receipt, a count and a payment do not depend on it: they are checked from signed evidence and the chain. Memory
adds what was learned from earlier work.

## What it is used for, with the calls

All of it goes through `src/knos/proof/history.py` (`SibylStore`), and that class calls only these:

| the engine's tier | the client's call | what Knos keeps there |
|---|---|---|
| HOT, state documents | `set_state`, `get_state` | the running count of claims and refusals in a repository; the buyer's live exception queue |
| WARM, entities | `set_entity`, `get_entity`, `list_entities`, `search_entities(category=...)` | proof rules, tamper lessons, how each order ended, refusals under given terms, appeals, a supplier's record, one entity per supplier-and-terms holding how their exceptions ended, one entity per commitment holding every approval record given for it, and in a supplier's tenant the results each buyer granted and each buyer's onboarding times |
| COLD, journal | `write_event`, `read_events` | every verdict of the Stop hook; every resolution of an exception; every approval record, which the entity of its commitment is checked against; every granted result. Appended, never rewritten |
| REFERENCE | `set_reference`, `get_reference` | the text of the terms an exception was judged under, by its hash |
| ARCHIVE | `archive_entity` | a closed statement period: what its exceptions came to; a grant its buyer withdrew |
| all tiers | `search` | finding a past refusal by its words |
| tenants | `MemoryClient.local(..., tenant_id=...)`, `set_tenant` | one tenant per repository for the hook and the judge; one per buyer organisation for exceptions and approvals (`knos.store.buyer_tenant`); one per supplier for what buyers granted it (`knos.store.supplier_tenant`) |

Two things the client does not offer at 0.8.1 and Knos works around in the open: it has no call that lists the
archive, so `SibylStore.archived` reads the engine's own `archived_entities` table through the client's storage
handle; and the engine's self-learning and linter need a paid account, so Knos calls `learn()` only when one is
there and never depends on it.

## What a buyer sees it do

`knos recall exception --buyer ORG --terms HASH --reason CODE [--supplier ID]` answers how the same exception under
the same terms ended before: how often, each ending (accepted on appeal, corrected and passed, refused), how long it
took, and the evidence ids. `--json` prints the row the approver's exception queue draws (`web/recall.js`).

What it answers from is written where the thing happens (`tests/test_recall_wired.py`):

| Where | What is remembered |
|---|---|
| an appeal the workflow handles (`knos.appeal.remember`) | the appeal as an exception under its terms: open, then ended accepted on appeal or refused |
| `knos statement make --remember ORG` | each line that is not agreed, on the live queue |
| `knos statement pay --remember ORG` | a line that had been set aside and was paid: accepted on appeal; refunded: refused |
| `knos meter correct --remember ORG` | the correction: a verdict corrected to accepted is corrected and passed; any other is refused |
| `knos meter close --remember ORG` | an agreed month's ended exceptions, moved to the archive |

Nothing is remembered unless `--remember` names the buyer organisation, and a workflow's appeals are remembered
only where the job has the memory engine installed. A statement and a meter ledger name no terms: without
`--terms HASH` their exceptions are kept under a hash of the two parties' names, so a recall is of the same buyer
and supplier and of no other pair. No buyer has used any of this.

## The approver's defence, six months later

`knos recall keep-approval FILE --buyer ORG` keeps one approval record (who, the commitment, the amount, the purchase
order, the beneficiary, the policy version, when, until when, why, and the sha256 of the evidence the approver saw)
in the buyer's tenant. `knos recall approval COMMITMENT --buyer ORG [--evidence FILE]` answers from the store alone,
in a process started later: who approved it, what amount, under which policy version, whether the record still
agrees word for word with the journal, and whether the evidence as it stands now still hashes to what was approved.
An entity rewritten after the fact is caught: the journal still holds the record as it was kept
(`tests/test_history_defence.py`). The evidence hash is sha256 over the evidence object written as JSON with sorted
keys and no spaces (`history.evidence_hash`).

## Supplier reuse

A supplier has its own tenant. `knos recall grant --supplier ID --buyer ORG --terms HASH --outcome accepted --ref DLV`
is the only way a result enters it: a buyer grants that one result may be shown to the supplier's other buyers. A
grant withdrawn goes to the archive and stops showing. `knos recall supplier ID --buyer ORG` answers what the supplier
brings from its other buyers (never the asking buyer's own results), and the onboarding counter: each buyer's time
from first order to first payment, kept as a hash of the buyer's name, and what the second buyer saved against the
first. The times are written by `knos.recall.order_funded` and `order_paid`; no workflow calls them yet, so the
counter is 0 until one does. No supplier and no buyer has used any of this.

## What stops working without it

`history.NullStore` is the same code with no memory. Swapped in, these answers come back empty
(`tests/test_recall.py::test_with_no_memory_every_answer_disappears`): how the exception ended before, how long it
took, the evidence ids, the journal's line, the live queue, the text of the terms, the closed periods, who approved
a commitment and whether its evidence matches, and what a supplier brings from its other buyers
(`tests/test_history_defence.py::test_with_no_memory_both_answers_disappear`). Deleting the
store's file has the same effect, and a second process recalls nothing
(`test_a_recall_survives_a_restart_and_the_store_is_the_only_place_it_is_kept`). The older answers go the same way
(`tests/test_sibyl_is_load_bearing.py`): the check a false "done" made required, the tamper lessons, the refusals a
preflight warns about.

## Its limits, measured here

- The engine's free tier holds 5,242,880 bytes for one account (`free_tier_status()` at 0.8.1). An empty store is
  282,624 bytes. Writing 300 resolutions for 30 suppliers grew it to 1,904,640 bytes, about 5,400 bytes each, so a
  free store holds on the order of 900 resolutions before the engine refuses a write. Past that the buyer needs an
  activated Sibyl account, or a store per period.
- On the same run one resolution took 13 ms to write and one recall 18 ms to read, on a shared two-core machine.
- One entity keeps the newest 200 cases of one supplier under one terms hash, and a count of all of them.
- Memory is local to the machine that holds the file. Two approvers on two machines do not share it; nothing
  replicates it. The judge's lessons travel between runs as issue comments (`knos.proof.memory`); exceptions do not
  travel yet.
- An approval is checked against the newest 100,000 journal events of the buyer's tenant; one older than that reads
  as not matching the journal.
- Sibyl's newest version on PyPI is 0.8.1, published 7 September 2026
  ([PyPI](https://pypi.org/project/sibyl-memory-client/), read 8 October 2026). Its documentation describes the
  same five tiers, FTS5 search and tenants used here, and no vector index
  ([docs](https://docs.sibyllabs.org/memory)).
- The engine is another party's code under an MIT licence. If it were withdrawn, the pinned version still installs
  from any mirror that has it, and the file is plain SQLite.
