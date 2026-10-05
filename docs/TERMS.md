# Knos Terms 1

Terms a contract can cite by hash. The terms of an order are a short JSON text. Its sha256 is fixed in the order when
it is funded, and the order pays only on a signed token that carries the same hash. This page says what the fields
mean, which exact bytes are hashed, and how a published template is named, so that a contract between two companies
can point at one and both sides can check it.

Money on devnet is test USDC. Nothing here is legal advice, and no contract is known to cite these terms yet.

## The sentence a contract carries

    Acceptance is governed by Knos Terms 1, template <name> version <n>, sha256 <hash>

`<name>` and `<n>` name a file of the registry, `terms/<name>/<n>.json`. `<hash>` is the sha256 of that file's
`terms_json`, in lower-case hex. The hash is what binds: the name and version are there so a person can find the file.

    python scripts/terms_registry.py cite bugfix

prints the sentence for the newest version and the address of its file on the site.

## The fields

One JSON object. The first seven fields are always there; the last three only when the order needs them.

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

A check's `app` is the id of the GitHub App that must have produced it; `0` means a commit status with that name;
`-1` means any source. Globs are GitHub's own, as in a workflow's `paths:` filter.

The amount, the deadline, a holdback, a warranty and a quorum are not in the terms. They belong to the order, and the
token that funds it signs them as well. A template's `comment` shows the ones it was published with.

## The bytes that are hashed

The hash is the sha256 of the canonical form, and of nothing else. The canonical form is one JSON object written this way
(`knos.terms.canonical` in `src/knos/terms.py` writes it; `knos.terms.parse` refuses every other form):

- the keys in sorted order, at every level: `accept`, `checks`, `deny`, `image`, `mode`, `paths`, `policy`,
  `reserve`, `v`, `vendor`; inside a check, `app` then `name`;
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
Knos Terms 2, with its own page.

## Checking one yourself

    python scripts/terms_registry.py verify <file or sha256>

answers with the template and version, or `not a published template`. A file may be the terms JSON alone or a file
that carries it under `terms`; it is put in canonical form before it is hashed, so spacing and key order do not
matter. The Terms page of the site does the same in the browser, from `terms/index.json`.

With no Knos code at all: take `terms_json` from the version's file, hash those bytes with any sha256 tool, and
compare with the hash in the contract.

    python scripts/terms_registry.py build           publish the templates in the code that are not published yet
    python scripts/terms_registry.py build --check   fail when the registry is behind the code or a published file changed
