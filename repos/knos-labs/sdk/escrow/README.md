# @knos/escrow

Instruction builders and a job decoder for the Knos escrow program on Solana. The package is `"private": true`, so it is not published to npm yet.

The program's layout is in [`programs/knos_escrow/idl.json`](../../programs/knos_escrow/idl.json), an Anchor-format IDL (spec 0.1.0). The program is native: each instruction's discriminator is a one-byte tag, and accounts have no discriminator.

```js
import { PublicKey, TransactionInstruction } from "@solana/web3.js";
import { createEscrow, decodeJob } from "@knos/escrow";

const escrow = createEscrow({ PublicKey });            // devnet program by default; pass programId to override
const claim = new TransactionInstruction(escrow.claim({ worker, jobId, workerToken, vaultToken }));
const job = decodeJob((await connection.getAccountInfo(escrow.pdas.job(jobId))).data, PublicKey);
```

Builders: `post` (with an optional `verifier`), `claim`, `deliver`, `accept`, `release`, `verifyRelease`, `reject`, `refund`, `verifyReject` and `settle` (the deadline crank). `jobId`, `brief`, `result`, `resultHash` and `proofRoot` each take 32 bytes, as a hex string or as bytes.

Tests run offline with `node --test sdk/escrow/test.mjs`. They check every encoding byte for byte against `fixtures.json`, which `python scripts/escrow_fixtures.py` writes from the Python builders in `src/knos/jobs/sol.py`. They also check the account table against `idl.json`.
