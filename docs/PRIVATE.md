# Private repositories: a neutral count without showing the code

A company whose repositories are private cannot hand its source to a third party to get an independent verdict.
And a judge that the buyer alone controls does not protect the supplier: the buyer could say "rejected" and nobody
could check. This page is the path between the two.

**No private-repository customer has run this.** Everything below is implemented and tested in this repository with
keys the tests hold (`tests/test_private_path.py`, `tests/test_vault.py`). No GitHub Enterprise Server and no
self-managed GitLab has signed a token for it, and the record it produces does not pay anything yet.

## The idea in four lines

1. The agreed acceptance runs on a runner **inside the customer's network**.
2. Only three things leave: **the verdict, hashes, and the issuer's signed token**.
3. The attestor that ran it was **approved by both parties beforehand**, by name.
4. What a dispute would need to see is **sealed to both parties**, so either can open it and nobody else can.

## One command, against a simulator

```
python -m knos.private run --repo PATH_TO_THE_WORK --attestors examples/private/attestors.json
```

It runs the whole path on one machine and prints each step as it happens: the attestors both parties approved, a
vault key for each party, the evaluation, the evidence sealed to both, the record that may leave, a signed token,
the offline check with the evidence the supplier opened, the retention rule as a dry run, and a dispute opened by
one party and resolved by both. It writes a folder (`--out`, default `knos-private-run`) and nothing in `--repo`.

**No private customer has run it.** What the command simulates, said on its first line: the issuer is an RSA key
made on the spot, not a forge; both parties are one process; and without `--verdict FILE` (the judge's own verdict,
from `knos proof judge --evidence`) no suite is run, so the record names no checks and no assurance. Every other
step is the function the real path uses (`tests/test_private_path.py`, "one command").

The release run exercises the real path in a private repository Knos owns. None exists yet, so the stage stays
`tested` until this has run. It needs two private repositories (an attestor and a target), a self-hosted Linux runner
registered to the attestor (the workflow asks for one), the secret `KNOS_READ_TOKEN`, the variables
`KNOS_VAULT_BUYER` and `KNOS_VAULT_SUPPLIER`, and `terms.json` and `attestors.json` in the attestor, whose entry
names the issuer `https://token.actions.githubusercontent.com` as run by a `third party`:

```
gh workflow run knos-private.yml -R OWNER/ATTESTOR -f repository=OWNER/TARGET -f pull=1 -f issue=1
gh run download -R OWNER/ATTESTOR -n knos-private-verdict -D verdict
curl -sSf https://token.actions.githubusercontent.com/.well-known/jwks -o jwks.json
python -m knos.private check --record verdict/record.json --token verdict/token.jwt --attestors attestors.json --jwks jwks.json
```

That would show one thing the simulator cannot: a forge's own signature over a record of private work. It would
still be Knos's repository, not a customer's.

## What leaves, exactly

The workflow is [`examples/private/knos-private.yml`](../examples/private/knos-private.yml). Its last artifact
holds two files:

| file | what is in it |
|---|---|
| `record.json` | `verdict` (accepted, rejected, insufficient evidence or disputed, as `knos.ids` spells them) and hashes: of the terms, of the attestors file, of the two source trees, of the acceptance checks, of the sealed evidence, the image digest of a hermetic run, and the accepted commit's id |
| `token.jwt` | the forge's own signed statement of which workflow ran, in which repository, with the audience `knos-private:<sha256 of record.json>` |

No source, diff, file name, check name, repository name or log line is in the record. `knos.private.record` builds
it from a fixed set of fields and `knos.private.leaks` refuses any other field or any value that is not a verdict
word or a hash; the signing job checks the shape once more before it asks for the token. A judge that did not reach
an answer gives `insufficient_evidence`, never a rejection.

Two things the record does tell an outsider. A commit id confirms a guess to someone who already has the commit.
And the token names the attestor repository and the account that started the run, as every token does
([PRIVACY.md](PRIVACY.md), section 2).

Check a record anywhere, with no chain and no network:

```
python -m knos.private check --record record.json --token token.jwt --attestors attestors.json --jwks jwks.json
```

It says which approved attestor signed, that the audience is this record's hash, and that the RS256 signature holds
under the key the token names in the key set you gave. Without `--jwks` it says, as a limit, that the signature was
not checked.

## Attestors both parties approved

[`examples/private/attestors.json`](../examples/private/attestors.json) is the shape. For each attestor it names the
issuer (the token's `iss`), who runs that issuer (`buyer`, `supplier` or `third party`), the repository's id, the
workflow file as the issuer signs it, who administers the repository and its runners, and who approved it. An
attestor counts only when `approved_by` holds both parties. The file's hash is in every record, and the token is
signed for the record's hash, so a verdict cannot be moved to another list afterwards. The parties put the file's
SHA-256 in their order or contract; that is the approval.

Who runs an issuer and who administers a repository are the parties' own statements. No token carries them.

### Two organisations agreeing is not the same as two evaluators

`knos.private.arrangement` reads the list and says which of five things it is, and how many independent judges to
count:

| arrangement | when | counts as | why |
|---|---|---|---|
| no attestor both approved | every attestor was named by one party only | 0 | a verdict from an attestor one side chose protects only that side |
| one attestor | one attestor, approved by both | 1 | both accepted it; if a party runs its issuer, the verdict is that party's word and the other side's protection is the sealed evidence |
| one administrator | two or more attestors that one person or team can change | 1 | one judge run twice |
| one issuer | two or more attestors whose tokens one party's own server signs, whatever the team names | 1 | whoever administers that server can sign any claim for either |
| independent organisations | two or more attestors with different administrators, and no one party's server signs for two of them | the number of them | a false verdict needs all of them to fail or to collude |

Two examples of the last row: each party attests on its own server (two organisations agreeing, each one's verdict
its own word); or two outside assessors on a public forge that neither party runs.

### What a receipt shows for each

A receipt ([RECEIPT.md](RECEIPT.md); `src/knos/receipt.py`) records, for every judge that spoke, the repository's
id, its owner's id, the id of the account that started the run, and the runner's kind. From those ids alone it
computes `independent_of_buyer`, `independent_of_seller` and `same_controller`.

| arrangement | what the receipt records |
|---|---|
| two organisations, different accounts, one forge | `same_controller: false`, and the sentence that the judges have different owners and starters by account id |
| two judges one account owns or started | `same_controller: true`: "count this quorum as one judge" |
| one administrator behind two accounts | `same_controller: false`. The receipt says so itself: two accounts run by one person are one judge, and no receipt can show that they are not |
| two judges on two different instances | not comparable. Each GitHub Enterprise Server or GitLab instance numbers its own accounts, so equal ids on two instances are two accounts and one person has a different id on each. The comparison is by id only and does not look at the issuer |
| an issuer a party runs | the ids are whatever that server's administrators signed. The receipt names the issuer; it cannot show who administers it |

So the receipt answers "is one account behind two judges on one forge". The attestors file answers the rest, as a
statement both parties made, and `python -m knos.private check` prints its sentence beside the verdict.

## GitHub Enterprise Server and self-managed GitLab

Read on the web on 2026-10-06. Neither was reached from here: these are the vendors' documented forms.

| | GitHub Enterprise Server | self-managed GitLab |
|---|---|---|
| `iss` | `https://HOSTNAME/_services/token` | the instance's address, for example `https://gitlab.example.com` ("the domain of the GitLab instance") |
| discovery | `https://HOSTNAME/_services/token/.well-known/openid-configuration` | `https://gitlab.example.com/.well-known/openid-configuration` |
| key set | the `jwks_uri` of that discovery document. The page read here does not print it; read it from your instance | `https://gitlab.example.com/oauth/discovery/keys` |
| signs with | RS256 in the documented example token. Key size: not measured | RS256. Key size: per instance, not measured |
| claims to gate on | `repository_id`, `repository_owner_id`, `job_workflow_ref`, `runner_environment`, `aud` | `project_id`, `namespace_id`, `ci_config_ref_uri`, `ci_config_sha`, `runner_environment`, `aud` |
| source | [GitHub Enterprise Server 3.17, OpenID Connect reference](https://docs.github.com/en/enterprise-server@3.17/actions/reference/security/oidc) | [ID token authentication](https://docs.gitlab.com/ci/secrets/id_token_authentication/), [OpenID Connect in AWS](https://docs.gitlab.com/ci/cloud_services/aws/) |

A GitLab instance that is not reachable from outside can publish its discovery document and its keys elsewhere and
sign under that address: GitLab documents the setting `ci_id_tokens_issuer_url` for this, from GitLab 18.1 (the AWS
page above).

### How such an issuer is admitted to the verifier

[VERIFIER.md](VERIFIER.md) has the three calls and [`examples/issuers`](../examples/issuers) one folder for each
issuer already described; both are unchanged by this page. For an enterprise instance:

1. **Check the format.** The verifier takes RS256 under a 2048- or 4096-bit key and a token of at most 8,192 bytes.
   Read the `alg` and the size of the modulus in your instance's key set. Another algorithm or size is refused.
2. **Register the key as a private key.** The public route in VERIFIER.md has GitHub's hosted runners fetch the key
   from the issuer's address, which an instance behind a firewall does not allow. The private route is one call,
   `oidc.register_private_key_ix(wallet, ISS, n)`, with `ISS` the exact `iss` above and `n` the modulus. Nobody
   checks it, and every token it verifies carries the registering wallet's address.
3. **Make that registration mutual.** Each party reads the modulus from the key set itself (the supplier needs it
   sent, or network access), and both compare it with the key account on chain before relying on it. A key that
   only the buyer registered and only the buyer saw is the buyer's word.
4. **Rotate by hand.** A key expires on chain 30 days after it was registered, and an instance rotates its keys on
   its own schedule. Nothing refreshes a private key automatically.

Offline, none of that is needed: `python -m knos.private check --jwks FILE` verifies the same signature from a copy
of the key set.

What stays true however it is admitted: the instance's administrators hold the signing key. A token from a
customer's own server proves which workflow that server says ran. It is the customer's statement, signed.

## The dispute path, in plain words

This describes the mechanism. It is not legal advice, and the contract between the parties decides what it says.

- **What is sealed.** The verdict file, the terms, the attestors file and the pull request's diff, as one archive,
  encrypted to the buyer's key and the supplier's key (and an auditor's, if both add one). [VAULT.md](VAULT.md) has
  the format.
- **Who can open it.** Each recipient, alone, with their own key file: `knos vault open FILE.vault --key KEYFILE`.
  Nobody else can, including whoever stores the file and whoever runs Knos.
- **When.** The file has no lock in time: a recipient can open it at any moment. The contract says when they may
  use what they find, typically once a line is marked disputed. A supplier's key opens the buyer's diff of the
  supplier's own work, so agree beforehand what goes in the archive.
- **What it settles.** The opened archive's SHA-256 is in the signed record, so neither side can swap it. Either
  side can run the same acceptance again on the same trees (`knos judge rerun`) and compare. If the results differ,
  the line is `disputed`; Knos does not decide who is right, and whoever the contract names does.
- **How it is opened and closed.** `knos.private.dispute_open` takes the archive a party opened with its own key
  and refuses any other bytes, so only someone the evidence was sealed to can open a dispute. The opener signs it
  (Ed25519, the key of a Solana wallet file; the parties exchange public keys beforehand, as they do vault keys).
  `dispute_resolve` names what the record comes to, `accepted` or `rejected`, and `dispute_check` accepts it only
  with **both** parties' signatures over the same outcome. One party alone cannot close it, and Knos signs nothing.
  The dispute is a file the two parties hold. Nothing publishes it and no program reads it.
- **The money meanwhile.** A disputed line is not an accepted one: it is not billed and it is not paid. Lines that
  are not disputed are approved and paid as usual. For an order held in escrow on devnet, the test USDC stays in
  escrow until a signed acceptance pays it or the deadline returns it to the funder ([DRILLS.md](DRILLS.md), "refund
  only after the deadline"). Paying from a private record is not built, so today the record informs an invoice;
  it does not move money.

## What is not done

- No customer has run the workflow, and no enterprise instance's token has been verified, on chain or off.
- The one command above has run only against its simulator. The release run's four lines have not run: Knos owns no
  private repository with a self-hosted runner yet.
- A dispute file is checked, not enforced: no program and no invoice reads it yet, so honouring it is the contract's.
- The record is not accepted by the escrow program. That program's audiences are in [OIDC.md](OIDC.md).
- The key size of an enterprise instance was not measured. A 3072-bit key would be refused.
- Nothing checks that an administrator named in the attestors file is who the file says.
- GitLab has no example pipeline for this path yet; the attestors file and the check take a GitLab token's claims.
