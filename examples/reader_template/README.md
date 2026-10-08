# reader_template: do one thing only when your CI asked for it

A complete Solana program, on its own, that releases once when GitHub signed that one workflow of one repository
asked this program to. `knos-oidc` checked GitHub's signature on chain; this program reads the result. It takes one
crate from Knos (`knos-oidc-interface = "0.3.14"` from [crates.io](https://crates.io/crates/knos-oidc-interface), no dependency of its own) and nothing else: no call into Knos, no
key of Knos's, nobody to ask. Devnet only: the verifier is `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W`.

## Use this template

```bash
git clone --depth 1 https://github.com/drexthealpha/Knos && cp -r Knos/examples/reader_template my_reader && cd my_reader
$EDITOR src/lib.rs            # change the two constants marked CHANGE: REPOSITORY_ID and WORKFLOW
cargo build-sbf               # target/deploy/reader_template.so
solana-keygen new -o program.json && solana-keygen new -o me.json && solana airdrop 2 -k me.json -u devnet
solana program deploy -u devnet -k me.json --program-id program.json target/deploy/reader_template.so
```

`REPOSITORY_ID` is `gh api repos/OWNER/REPO --jq .id`. `WORKFLOW` is `OWNER/REPO/.github/workflows/FILE@refs/heads/main`.
In that workflow, give the job `id-token: write` and ask GitHub for a token for your program:

```bash
curl -sSf -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
  "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=release:$(solana address -k program.json)" | jq -r .value
```

Whoever sends your instruction writes that token to `knos-oidc` and has it verified (`verifier(program)` in
[`sdk/settle`](../../sdk/settle), `knos.settle.v2.oidc` in Python: [docs/VERIFIER.md](../../docs/VERIFIER.md), call
2), then sends `Release` with five accounts: payer, the token account, its key account (`readToken(data).key`), the
record at `["done", sha256(claims)]` under your program, and the system program. Then put your own action where
`src/lib.rs` says YOUR ACTION.

Built here with `cargo build-sbf` (the fixture was built from the v0.3.14 tag; the crates.io release is the same version) and run in a simulator against the verifier
(`tests/test_reader_template.py`, 2 tests). It has not been deployed to devnet, and no program outside this
repository is known to use it. Built something on it? [docs/COMPOSE.md](../../docs/COMPOSE.md) says how to be listed, and the playground's `compose` task
([tasks/outside/compose.json](../../tasks/outside/compose.json)) pays 5 test USDC for one devnet transaction of it.

## Five mistakes a reader can make, and the line that prevents each

Each is marked in [`src/lib.rs`](src/lib.rs) and tried in the test, which sees the program refuse.

| | the mistake | what goes wrong | the line |
|---|---|---|---|
| M1 | not checking the account's owner | anyone can create an account holding the bytes of a verified token | `Token::read(&token.owner.to_bytes(), ..)` refuses any owner but `knos-oidc` (error 1) |
| M2 | not checking freshness | a token from last month, or one whose signing key was revoked since, still releases | `Token::read(.., now)` refuses a token an hour past its `exp` (3); `tok.check_key(..)` refuses an expired or revoked key (77, 78) and any key account but the token's own (68) |
| M3 | trusting a claim the verifier does not check | `knos-oidc` checks the signature and the expiry. It does not check who the token is for, or from where: a token from any repository on GitHub would release | `tok.issuer()`, the audience (`release:<this program>`), `repository_id` (the number: a name can change hands) and `job_workflow_ref` are compared here (100 to 103) |
| M4 | reusing a result twice | a verified token can be read by anyone, any number of times, until an hour after it expires | the record's address is the hash of the token's claims, and `done.owner == program_id` refuses the second time (104) |
| M5 | reading the wrong program id | a token another deployment verified says nothing here; an owner taken from an instruction argument says nothing at all | the owner is compared with the address the crate pins (`knos_oidc_interface::ID`), never with an account the caller passes |

What stays true after all five: the token is GitHub's word that this workflow ran and asked. It is not proof of
what the workflow read or decided.
