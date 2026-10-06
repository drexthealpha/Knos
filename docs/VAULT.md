# The vault: evidence that outlives devnet and the operator

An evidence bundle (`knos bundle make`) holds everything a payment's verdict was derived from: the receipt, the token
the issuer signed, the key, the terms, and an archived copy of the chain record. [RECEIPT.md](RECEIPT.md) says what
`knos bundle verify --no-chain` proves from it when the cluster is gone. This page is about keeping it: sealed to the
people who may open it, exported in plain for the customer, removed on a schedule, and checkpointed so that anyone
can later show a bundle existed.

Nothing here needs a server, an account, a cluster or Knos's operator. The code is `src/knos/vault.py` and
`src/knos/vault_crypto.py`; the tests are `tests/test_vault.py`.

What has and has not happened: the commands are implemented and tested here with fixed keys. No customer keeps a
vault, and no checkpoint root has been anchored anywhere outside a test.

## The commands

| command | what it does |
|---|---|
| `knos vault keygen buyer` | one party's key pair. The file stays with that party; the line it prints (`buyer=<64 hex>`) is what the others seal to |
| `knos vault seal FILE --to buyer=... --to supplier=... --to auditor=...` | seals one bundle into the vault folder as `<sha256 of the bundle>.vault`. Each recipient opens it alone |
| `knos vault open FILE.vault --key buyer.vaultkey.json` | the bundle again, checked against the hash in the header |
| `knos vault export VAULT --key KEYFILE --out knos-evidence.tar` | a plain archive of every bundle, with a checkpoint. Not encrypted: the customer's own copy |
| `knos vault restore knos-evidence.tar --to DIR` | the bundles out of that archive, each checked against the archive's checkpoint |
| `knos vault retain VAULT --policy FILE [--dry-run]` | applies a retention policy; `--dry-run` prints what would go and touches nothing |
| `knos vault checkpoint VAULT [--previous FILE] [--sign KEYPAIR]` | one hash over every bundle hash, and the line to write down |
| `knos vault verify CHECKPOINT [--against VAULT, ARCHIVE or DIR] [--key KEYFILE] [--root ROOT]` | checks the checkpoint and that everything it lists is held. No chain, no network |

## The sealed file, version 1

One JSON object on one line, keys in order, no spaces. `type` is `knos.vault`, `version` is 1.

| field | what it is |
|---|---|
| `kem`, `aead` | `x25519-hkdf-sha256`, `chacha20-poly1305`. A reader refuses any other value by name |
| `name` | the bundle's file name: letters, digits, dot, dash, underscore |
| `plain_sha256`, `size` | the SHA-256 and the length of the bundle before sealing |
| `sealed_at` | seconds since 1970 |
| `ephemeral` | base64 of a 32-byte X25519 public key made for this file alone |
| `recipients` | in order of label: `{id, label, public, wrapped}`. `public` is the recipient's X25519 key, `id` the first 16 hex characters of its SHA-256, `wrapped` the content key sealed for that recipient (48 bytes) |
| `nonce` | base64 of 12 random bytes |
| `ciphertext` | base64 of the bundle under ChaCha20-Poly1305, its 16-byte tag at the end |

How it is made:

1. Draw 32 random bytes for an ephemeral X25519 private key, 32 for the content key, 12 for the nonce.
2. `bound` = SHA-256 of the canonical JSON of the header: `type, version, kem, aead, name, plain_sha256, size,
   sealed_at, ephemeral` and each recipient's `id, label, public`.
3. For each recipient: `shared = X25519(ephemeral private, recipient public)`;
   `key = HKDF-SHA256(shared, salt = ephemeral public || recipient public, info = "knos.vault.v1 key wrap")`, 32 bytes;
   `wrapped = ChaCha20-Poly1305(key, nonce = 12 zero bytes, content key, associated data = bound)`. Each wrapping key
   is used for exactly one message, which is why a fixed nonce is safe there.
4. `ciphertext = ChaCha20-Poly1305(content key, nonce, bundle, associated data = bound)`.

Because both seals carry `bound`, changing the name, the date, the size, a label, or adding or dropping a recipient
makes every open fail. A public key that would give an all-zero shared secret is refused.

The primitives are X25519 ([RFC 7748](https://www.rfc-editor.org/rfc/rfc7748)), HKDF-SHA256
([RFC 5869](https://www.rfc-editor.org/rfc/rfc5869)) and ChaCha20-Poly1305
([RFC 8439](https://www.rfc-editor.org/rfc/rfc8439)). Knos has no runtime dependency for cryptography, so they are
written out in `vault_crypto.py` from the standard library and tested against the RFCs' vectors. When the
`cryptography` package is installed it is used instead, and a test holds the two to the same bytes.

### Test vector

[`tests/data/vault_v1.json`](../tests/data/vault_v1.json) holds three private keys, the ephemeral key, the content
key, the nonce, a plaintext and the sealed file they give. Every secret in it is SHA-256 of a label and is used for
nothing else.

| | |
|---|---|
| plaintext SHA-256 | `d1dc5cedfce749fffcf06e1d72f6f2769f37eac4fcd5450a2795b4ef325237c8` |
| sealed file SHA-256 | `a5dffe21caac592812621178bae1e611504e7ac220aa8d4797630ac87086962a` |
| checkpoint root over that one bundle | `c330ddd000ea9483afabe1ed1499414c4e5ec37e339fdaa9ceb4e3ea9dd355ff` |

An implementation in another language is right when it writes that sealed file from those inputs and opens it with
each of the three keys.

## What the header shows, and to whom

The header is in the clear on purpose: a checkpoint and a retention policy work without any key. Whoever stores a
sealed file therefore sees how many bundles there are, how large, when each was sealed, and the labels and public
keys of the recipients. They do not see a repository, an amount, a payee or a verdict. If the labels themselves are
confidential, use neutral ones (`a`, `b`, `c`).

## Checkpoints

A checkpoint is `{type: knos.vault-checkpoint, version: 1, at, count, entries, root, previous, signature}`.
`entries` are the bundles' SHA-256 hashes in order. `root` is the SHA-256 of the bytes `knos.vault.checkpoint.v1`,
one zero byte, the count as 8 bytes (big-endian), and the hashes as raw bytes in order. `previous` is the root of the
checkpoint before, so a series of them forms a chain. With `--sign` the checkpoint carries an Ed25519 signature made
with a Solana keypair file; without it, it is a hash.

The command prints one line, `knos-vault-checkpoint:v1:<root>`. Put it somewhere both parties will find it later
and neither can rewrite alone: an email to the other side, a transaction memo, a notary's register. That is all
"anchoring" means here, and no place is required.

What `knos vault verify` then shows: the root is the hash of the entries, the signature holds if there is one, and
every listed bundle is held (in a vault folder, an export archive or a folder of plain bundles). With `--root` it
also holds the checkpoint to the root you wrote down. It shows that a bundle held today is one of those that existed
when the root was written down. It does not show that the bundle is true; `knos bundle verify` does that, from the
issuer's signature. A signature says a key's holder made the checkpoint; who holds the key is not in the file.

## Retention

A policy is one file ([`examples/private/retention.json`](../examples/private/retention.json)):

```json
{"type": "knos.retention-policy", "version": 1, "keep_years": 7, "then": "hashes"}
```

`keep_years` counts years of 365 days from `sealed_at`. `then` is `delete` (the sealed file is removed and nothing
is kept) or `hashes` (the sealed file is removed and its hash, name, size and dates stay in `hashes.json`, so older
checkpoints still verify and say "hash only"). `--dry-run` prints each bundle with its age and what would happen.

Three limits. The age comes from the header, which only a key holder can confirm. Removing a file from one folder
removes it from that folder: a copy the other party or an auditor holds is theirs. And a bundle whose hash alone is
kept can no longer prove anything about its contents to anyone.

## The restore test

`tests/test_vault.py::test_restore_from_the_export_alone_after_the_working_copy_and_the_chain_are_gone`, and the row
"devnet is reset and the operator's copies are deleted" in [DRILLS.md](DRILLS.md): a bundle is sealed to three keys
and exported; the working folder is deleted and the chain forgets the order; the archive alone is restored; and
`knos bundle verify --no-chain --no-network` passes on every restored receipt. The test chain holds one order, so
"every" is one bundle there. It has not been rehearsed with a customer's archive.

Once on a real bundle, on 6 Oct 2026: the bundle of a work order paid on devnet at the staging program ids (transaction
`63wT5rhY…`, 40,960 bytes, sha256 `fae63726…`, made by `knos bundle make` on 5 Oct) was sealed to three keys made for the
run with `knos vault keygen`; each of the three opened it to the same bytes; it was exported, the vault folder was
deleted, and `knos vault restore` gave it back from the archive alone, checked against the archive's checkpoint
(`knos-vault-checkpoint:v1:72680419…`). `knos bundle verify --no-chain --no-network` passed on the restored copy, with
`KNOS_PROGRAM_IDS` naming the staging ids it was paid on. Without them it is refused, and the refusal says the bundle
is from another deployment of the programs. The keys and the archive were the founder's: nobody else held one.

## Limits

- The standard-library code is not constant-time; nothing written in Python is. Sealing and opening are done by a
  person on their own machine. On a shared machine, install `cryptography`.
- There is no key recovery. A lost key file opens nothing; that is why a bundle is sealed to more than one party.
- A recipient cannot be removed from a file that was already handed out. Seal again to the new set and delete the old
  file where you can.
- An export is plain. It is the customer's durable copy and must be kept like a contract.
- This is evidence of what was signed and recorded. Money on devnet is test USDC, and none of it is recovered by a
  restore.
