# Check a Knos receipt offline

One function, in two files that need nothing installed:

| File | For |
| --- | --- |
| [`knos_verify.py`](knos_verify.py) | Python 3 (tested with 3.11), standard library only |
| [`knos-verify.ts`](knos-verify.ts) | TypeScript on anything with WebCrypto (`crypto.subtle`); tested with Node 22 |

Copy one into a backend, or call it from a webhook handler:

```python
from knos_verify import verify

got = verify({"token": token, "receipt": receipt, "terms": terms}, jwks,
             expect={"repository_id": 987654321, "pull_request": 12, "payee": 5550123})
if got["ok"]:
    mark_paid_on_proof(got["facts"])        # order, commit, pull_request, repository_id, terms_hash, mode, payees
else:
    log(got["refused"], got["why"])         # the step that failed, and a sentence
```

```ts
import { verify } from "./knos-verify.ts";

const got = await verify({ token, receipt, terms }, jwks, { repository_id: 987654321 });
```

`token`, `receipt` and `terms` are `token.jwt`, `receipt.json` and `terms.json` of a Knos evidence bundle
(`knos bundle make ORDER`; see [`docs/reference/RECEIPT.md`](../../docs/reference/RECEIPT.md)). The token alone is enough for the
signed facts. `jwks` is GitHub's published keys
(`https://token.actions.githubusercontent.com/.well-known/jwks`) as you fetched and kept them, or the bundle's
`key.json`. The function opens no connection.

## What it checks

1. **token**: an RS256 token whose signature is the one of the key in `jwks` with its `kid` (2048 bits or more).
2. **issuer**: GitHub signed it, for a run of the workflow you expect. By default that is a workflow of
   `drexthealpha/Knos`; pass `expect={"workflow": "..."}` to pin a file or a tag. Without this step anyone's
   workflow could ask GitHub for a token with the same audience.
3. **audience**: it was signed for one Knos payment: an order, a commit, a terms hash, a mode, a pull request and
   its payees.
4. **receipt**, when given: it names this token by its sha256, carries its claims, and agrees with the audience.
5. **terms**, when given: their sha256 is the terms hash, and they say what the receipt's policy says.
6. **expect**: each of `repository_id`, `order`, `commit`, `pull_request`, `terms_hash`, `mode`, `payee` you give.

## What it does not check

Every answer carries these in `limits`:

- The wallets paid and the amounts are the receipt's word. No signed token carries them.
- The key is the one you gave. It was not compared with the key account on chain.
- The named checks were not evaluated again, and an expired token is still accepted, because a receipt
  records a payment in the past.

`knos bundle verify FILE --rpc URL` does all three from the bundle and the chain. Use this function to decide
whether to show a badge or a line of text; use the bundle check before anything that moves money.

## Tests

[`fixtures.json`](fixtures.json) holds 19 cases, each with the answer both files must give: five that hold and
fourteen that are refused, each for its own reason. The key in it is a test key, never GitHub's.

    python -m pytest tests/test_integrations.py
    node --experimental-strip-types integrations/webhook/test.mjs
