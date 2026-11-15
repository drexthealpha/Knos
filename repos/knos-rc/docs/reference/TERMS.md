# Knos Terms 1

Terms a contract can cite by hash. The terms of an order are a short JSON text. Its sha256 is fixed in the order when
it is funded, and the order pays only on a signed token that carries the same hash. This page says what the fields
mean, which exact bytes are hashed, and how a published template is named, so that a contract between two companies
can point at one and both sides can check it.

Two formats exist: Knos Terms 1 (the short terms every order carries) and Knos Terms 3 (a longer contract
document). There is no Terms 2.

Money on devnet is test USDC. Nothing here is legal advice, and no contract is known to cite these terms yet.

## The sentence a contract carries

    Acceptance is governed by Knos Terms 1, template <name> version <n>, sha256 <hash>

`<name>` and `<n>` name a file of the registry, `terms/<name>/<n>.json`. `<hash>` is the sha256 of that file's
`terms_json`, in lower-case hex. The hash is what binds: the name and version are there so a person can find the file.

    python scripts/terms_registry.py cite bugfix

prints the sentence for the newest version and the address of its file on the site.

## The fields

One JSON object. The first seven fields are always there; the last four only when the order needs them.

| Field | Meaning |
| --- | --- |
| `v` | The version of this format: `1`. |
| `mode` | `merge`: paid when a maintainer merges. `tests`: paid when the acceptance suite passes. |
| `checks` | What must have concluded `success` at the pull request's last commit: each `{"app", "name"}`. |
| `paths` | When not empty, every changed file must match one of these globs. |
| `deny` | No changed file may match one of these globs. |
| `accept` | `tests` mode: the sha256 of the acceptance suite's folder. Empty in `merge` mode. |
| `reserve` | Days a reservation of the issue lasts, 0 to 90. 0: it cannot be reserved. |
| `image` | Optional, `tests` mode only: the judge's container image, pinned by digest. |
| `policy` | Optional: the sha256 of the repository's policy file as it was at funding. |
| `vendor` | Optional: the GitHub account id of the one account a standing offer pays. |
| `contract` | Optional: the sha256 of the Knos Terms 3 document the order is funded under (below). |

A check's `app` is the id of the GitHub App that must have produced it; `0` means a commit status with that name;
`-1` means any source. Globs are GitHub's own, as in a workflow's `paths:` filter.

The amount, the deadline, a holdback, a warranty and a quorum are not in the terms. They belong to the order, and the
token that funds it signs them as well. A template's `comment` shows the ones it was published with.

## The bytes that are hashed

The hash is the sha256 of the canonical form, and of nothing else. The canonical form is one JSON object written this way
(`knos.terms.canonical` in `src/knos/terms.py` writes it; `knos.terms.parse` refuses every other form):

- the keys in sorted order, at every level: `accept`, `checks`, `deny`, `image`, `mode`, `paths`, `policy`,
  `reserve`, `v`, `vendor`; `contract`, when it is there, between `checks` and `deny`; inside a check, `app` then
  `name`;
- the separators `,` and `:` with no space and no line break;
- ASCII only: every other character is written `\uXXXX` in lower-case hex, as Python's `json` writes it;
- every list sorted with no repeat: `deny` and `paths` by code point, `checks` by name and then by app;
- at most 600 bytes.

An example, whole:

    {"accept":"","checks":[{"app":15368,"name":"lint"},{"app":15368,"name":"unit"}],"deny":[".github/**",".knos/**"],"mode":"merge","paths":["src/**","tests/**"],"reserve":7,"v":1}

Its sha256 is `91c3adb2adc12c66beb852fe809a096d4dd7028c0bc77ec209b6879ca753f2e3`: the template `bugfix`, version 1.

## The registry

`terms/index.json` lists every published version: `name`, `version`, `hash`, the one `sentence` that says it in plain
words, the `comment` that funds it, what it trusts, and `file_sha256`, the sha256 of the version's file as it was
published. `terms/<name>/<version>.json` holds the version itself: the same fields, `terms` as an object,
`terms_json` as the exact canonical text, `terms_hash`, the contract sentence under `cite`, and `assumes`.

`assumes` matters. The terms of a real order carry facts of the repository it is funded in: which GitHub App produces
each check, the hash of its own acceptance suite, the hash of its own policy, the vendor's account id. A template was
made with sample facts, and says which. An order has a template's hash only when its terms are the same bytes. So a
contract that cites `bugfix` version 1 says: checks named `lint` and `unit`, both GitHub Actions jobs, and only
`src/` and `tests/` may change. An order funded with other checks has other terms and another hash, and the reply to
the funding comment shows that hash.

## How a version is named

A template has a name (lower-case letters, digits and `-`) and versions 1, 2, 3 and so on. A published version never
changes. When a template's terms or its comment change, the next number is published beside the old one, and the old
file stays as it was. `tests/test_terms_registry.py` reads every listed file again and fails when its bytes are not
the ones the index recorded.

"Knos Terms 1" is the version of the format, the `v` field. A format that reads these bytes another way would be
Knos Terms 2, with its own page. None was published under that name. Knos Terms 3, below, does not read these bytes
another way: it is a longer document that an order's terms point at.

## Checking one yourself

    python scripts/terms_registry.py verify <file or sha256>

answers with the template and version, or `not a published template`. A file may be the terms JSON alone or a file
that carries it under `terms`; it is put in canonical form before it is hashed, so spacing and key order do not
matter. The Terms page of the site does the same in the browser, from `terms/index.json`.

With no Knos code at all: take `terms_json` from the version's file, hash those bytes with any sha256 tool, and
compare with the hash in the contract.

    python scripts/terms_registry.py build           publish the templates in the code that are not published yet
    python scripts/terms_registry.py build --check   fail when the registry is behind the code or a published file changed

# Knos Terms 3

Acceptance as a versioned contract. The 600 bytes above say which checks decide. They do not say what one
deliverable is, who may judge, who may appeal and to whom, or who may change the terms. A Knos Terms 3 document says
all of it, in ten required fields, and an order points at one version of it by hash.

Nothing published as Knos Terms 1 changes. Those files keep their bytes and their hashes, and an order funded on
one stays valid. `src/knos/terms3.py` reads and writes the format; `tests/test_terms3.py` holds it.

No contract is known to cite a Knos Terms 3 document. The workflow that funds an order reads the repository's own
(`.knos/terms.json`) and funds nothing that differs from it ("What is not enforced yet", below, says where that stops).

## The ten fields

One JSON object: `"standard": "Knos Terms 3"`, `"v": 3`, a `name`, a `version`, and these ten. Each field holds its
facts and one plain line under `says`.

| Field | The question it answers | What it must name |
| --- | --- | --- |
| `deliverable` | What is one deliverable? | its `kind` (`pull-request`, `batch`, `resolution`) and what there is one of it for; the line says how a retry is told from a new deliverable |
| `evidence` | Whose signature counts? | `sources`: each an `issuer` and a `workflow` |
| `checks` | What decides? | `mode`, the `deciding` checks, the acceptance suite's hash, and `authority`: where the authoritative copy lives. Optional (0.3.21): `min_assurance`, one of `reported`, `rerun`, `agreed`: nothing is paid on a receipt below that level ([RECEIPT.md](RECEIPT.md), assurance), and the funding workflow sends no payment its evaluator cannot reach it with. Terms without the key keep the hash they had |
| `window` | How long can it be reopened? | `warranty_days` and `holdback_percent`; both zero, or both not. Optional (0.3.21): `period_close`, with `buyer_key` and `supplier_key` (two different Ed25519 keys, in base 58) and `silence_days`: a month closes when both keys signed its last line, or one did and closed it alone after that many days of silence ([EVENTS.md](EVENTS.md)). Terms without the key keep the hash they had |
| `changes` | What may change? | `paths` allowed, `protected` paths, and `may_add`: what a contributor may add without asking |
| `dispute` | Who may appeal, and to whom? | `who` (the supplier), the `evaluator` (one of `evaluators.list`, or `arbiter`), `within_days`, where the `money` stays, and what happens with `no_answer` |
| `evaluators` | Who may judge? | `quorum`, and a `list`: each a `name`, an `issuer`, a `repository`, a `workflow` and an `owner`. Optional: `related`, the accounts the parties declare to be one party, as groups of numeric account ids (`[[7001, 8002]]`); two evaluators declared related never count as two ([RECEIPT.md](RECEIPT.md), assurance). Terms without the key keep the hash they had |
| `price` | What does it pay? | `amount` and `currency` |
| `deadline` | When does it end? | `days`, and what happens to a token presented `late` |
| `policy` | Who may change these terms? | `may_change`: the logins or teams who may publish a new version, and `how` |

Four rules keep a document from promising what the code does not do:

- **A line is written from its facts.** `says` is not free text. `knos.terms3.say` writes it from the field, and a
  file whose line differs from its facts is refused with the line it must carry. The wording of the lines is
  therefore part of the format: other wording would be another format with another number.
- **What the program fixes cannot be written otherwise.** `deadline.late` is `refused`, `dispute.money` is `order`,
  `dispute.no_answer` is `refund-at-deadline`, `price.currency` is `test USDC`, `policy.how` is `new-version`. Each
  has one permitted value, because that is what happens whatever a document says.
- **A quorum needs different owners.** With `quorum` 2 or 3 the list must hold that many evaluators whose owners
  differ. Two judges with one owner are one judge.
- **An appeal goes where it can be heard.** An order decided by an acceptance suite is appealed to an evaluator who
  runs it again. An order paid on a merge has nothing to run again, so its appeal goes to `arbiter`, named or not
  ([DISPUTES.md](DISPUTES.md)).

## Verifying, and what a refusal says

    knos terms verify .knos/terms.json

A file missing a field is refused, and the refusal names every missing field and what it is for:

    This terms 3 file is missing `dispute` (who may appeal, to which evaluator, by when, and where money stays meanwhile).

A complete file prints its sha256 and its ten answers. It also says whether it is one of the published templates;
a repository's own terms usually are not, and that is not an error.

## The version, and how an order cites it

The version of a document is the sha256 of its canonical bytes: sorted keys, `,` and `:` with no space, ASCII, every
list in order. `knos.terms3.digest` computes it. A contract carries:

    Acceptance is governed by Knos Terms 3, <name> version <n>, sha256 <hash>

An order cites it in its own 600 bytes: `knos.terms3.order_terms` writes the deciding checks, the paths and the
protected paths as Knos Terms 1 fields and adds `"contract": "<hash>"`. The order's terms hash, which the program
keeps and every pay token must carry, therefore names one version of the document and no other. Change any of the
ten fields and the order's hash changes.

Who may change the terms is `policy.may_change`. How is always the same: a published version never changes, a
change is the next version with its own hash, and an order keeps the version it was funded on.

    knos terms diff bug-fix migration
    knos terms diff .knos/terms.json new-terms.json

prints what changed between two versions, by meaning and not by text: one sentence a difference, each tagged with
its field, in the order of the ten questions. Key order and list order change nothing.

## The templates

`terms/index.json` lists them under `terms3`, each with its `hash`, its file's `file_sha256`, the sentence to cite
and the comment that funds it. The files are `terms/3/<name>/<version>.json`.

| Template | What it is for | Its defaults |
| --- | --- | --- |
| `bug-fix` | a fix to one issue | two named checks, only `src/` and `tests/` may change, paid on the merge, nothing held |
| `migration` | a change that may touch anything | one named check, any path, a share held for a warranty and returned on a revert |
| `dataset-batch` | a batch of labelled data | an acceptance suite decides, on items never shown; an appeal is a neutral run of the same suite |
| `support-resolution` | a resolved support ticket | not built: needs a signing system of record. It is published to say exactly that, and it funds nothing |

The defaults are the cautious choice in each field: the order's own repository judges, no arbiter is named, the
checks and the terms themselves are protected paths, and only the repository's owner may publish a new version.
They were made with sample facts (a repository named `acme/widgets`); a real repository's terms name its own.

## Proposed from a repository

    knos terms propose <owner/repo>
    knos terms propose <owner/repo> --out .knos/terms.json

writes a filled draft from what a public repository already shows, so that nobody starts from an empty file:

- the checks that passed on every one of its last 10 merged pull requests become the deciding checks;
- its test directories become protected paths, so work cannot pass by changing its own tests;
- the owners its CODEOWNERS file names for every file may publish a new version;
- every other field is the template's default.

Under each answer the draft says where it came from, and which checks were left out and why. The buyer edits the
file, runs `knos terms verify` on it, and commits it. Making a proposal funds nothing, posts nothing and opens
nothing in the repository that was read.

It reads GitHub's public REST API without signing in, with at most 17 requests. GitHub allows 60 an hour to a reader
who has not signed in ([GitHub's rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)).
The Terms page of the site does the same in the browser (`web/propose_terms.js`), and one fixture holds both to the
same answer, hash included.

Nothing is proposed for a repository that merged no pull request in the last 30 days. Its record is too old to say
which checks decide today. The date of the last merge is in every proposal and in every refusal.

## What is not enforced yet

- The workflow that funds an order (`knos.flow`) reads `.knos/terms.json` on the default branch. When that file is
  Knos Terms 3, an order that says anything the document does not (`knos.terms3.check_order`) is not funded, and
  `/knos fund terms` funds exactly the order the document describes; the order's terms then carry the document's hash
  as `contract`. A repository with no such file funds as before. A private order (an attestor's) does not read the
  file yet.
- The run that signs a payment for such an order must be an evaluator the document names
  (`knos.terms3.evaluator_allowed`, asked of the token GitHub signed). This is the rule of `knos settle` and
  `knos attest`, not of the program: a token from a workflow that does not run them is held only to what the program
  checks.
- The program enforces what it always did: the terms hash, the deadline, the holdback and warranty, the quorum and
  the single use of a token. It does not read `evaluators`, `dispute` or `policy`; those bind through the hash and
  through the workflow that signs.
- The time to appeal (`dispute.within_days`): `/knos appeal` refuses a late appeal of such an order and says why,
  counting from the rejection the judge's memory holds. `knos appeal open` on the command line does not check it.
- `support-resolution` cannot be used. No system of record signs that a ticket was resolved.
