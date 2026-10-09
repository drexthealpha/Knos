# knos-oidc: OIDC on Solana

A Solana program that verifies an OpenID Connect token (a JWT signed RS256) on chain: from **GitHub Actions**, and
since 2.1 from **any RS256 issuer** whose key has been admitted (GitLab, a company's own GitHub Enterprise Server,
another CI system, a cloud's workload identity). Once a token is verified, any other program can read its claims
and trust them as much as it trusts the issuer and the account the workflow ran in: which repository, which commit,
which workflow file at which commit, which account started the run, and any audience string the workflow asked for.

2.1 is the upgrade Knos 0.3.14 proposed. Until it executes, the second deployment on devnet is 0.3.12's: GitHub's
and GitLab's keys only, and no private keys ([SECURITY.md](SECURITY.md), section 8).

**2.2** is the build Knos 0.3.16 made first, and it is proposed after the push of Knos 0.3.18. It changes one thing: the token's header and payload must be JSON
in every byte. 2.1 reads the claims it needs and steps over every other value by its brackets and quotes, so it
verifies a payload the issuer really signed that is not strict JSON in a value nobody reads (`tru`, a number with a
leading zero, brackets that do not match, a control character, bytes that are not UTF-8, `NaN`, a comment: 13
shapes in [the differential test](../tests/test_oidc_differential.py)). That is not a forgery, since only the
issuer's key can sign one, but two readers of one verified token can disagree about it. 2.2 checks every value
against RFC 8259 as it passes it, refuses a name that appears twice in the top-level object (error 62), and takes at
most 64 levels of nesting and 128 top-level members (error 61). Nothing else changes: the same instructions, the
same accounts, the same token account layout, the same error codes, so a program that reads a verified token reads
it as before. It costs no more compute than 2.1 ([ASSURANCE.md](ASSURANCE.md), "The claim reader: strict since 2.2").
The strict reader is [`strict.rs`](../programs-v2/knos_oidc/src/strict.rs), and only the verifier's own instructions
call it: Step reads the header and the payload with it before it marks the token account VERIFIED. The reader a
consumer compiles in, [`claims.rs`](../programs-v2/knos_oidc/src/claims.rs), is 2.1's source unchanged and still
passes over the values it is not asked for; `knos_pay` links it, and a change to it would change `knos_pay`'s bytes,
which this release does not. It does not need the strictness: the verifier refuses a payload that is not strict JSON
at verification, so no such payload ever reaches the account `knos_pay` reads. For the same reason the `knos_oidc`
crate's version stays 0.3.14 (a crate's version is in the bytes of what depends on it); the program is 2.2 by its
`VERSION` constant and its `security.txt`.
Until a 2.2 proposal has executed after its 48-hour delay, devnet runs a build that is lenient in the values it does
not read: 2.1, since the 2.1 proposal (proposal 3) executed. Which build is live is in [`web/upgrades.json`](../web/upgrades.json), not on this page. A 2.2 build says so
in its bytes: its `security.txt` carries `source_release: knos-oidc 2.2`.

It charges nothing and does not know Knos's escrow exists. There are two deployments on devnet:

| | first deployment ([`programs/knos_oidc`](../programs/knos_oidc)) | second deployment ([`programs-v2/knos_oidc`](../programs-v2/knos_oidc)) |
|---|---|---|
| address | `vpWym9azbPU5f2PH2a6n8c4RfmsyUeW2dMuWr1DSHcE` | `FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W` |
| who can change it | nobody: it has no upgrade authority | Knos, only through a multisig with a public 48-hour delay, until an outside review; after it the upgrade authority is removed |
| the keys it starts from | GitHub's four and GitLab's three of 2 Oct 2026 | GitHub's four of 2 Oct 2026 |
| a later key | named by a GitHub-signed token of the rotate workflow, from any repository that calls it | named by such a token from one of two repositories of one account; then a day's wait and a guardian's approval |
| another issuer's key | GitLab's only, fixed in the binary | 2.1: any RS256 issuer, the same way, with the issuer's URL stored on chain and checked against each token's `iss` |
| how long a key lives | for ever; it cannot be revoked | 30 days after it was last attested; the guardian can revoke it. 2.1: anyone can refresh a key the issuer still publishes |
| a key nobody vouches for | none | 2.1: a private key, registered by any wallet, marked private in every token it verifies |

A token account has the same layout under both, so the same code reads it. Build on the second. The first cannot
be fixed, and [SECURITY.md](SECURITY.md) says what is wrong with its key rules.

## What you can build with it

- **Pay on a signed fact.** `knos-pay` in this repository: an escrow that pays the author of a pull request when
  the funder's workflow reads the merge and the check results from GitHub, and GitHub signs that workflow run.
- **A release gate.** [`examples/oidc_gate`](../examples/oidc_gate): records, per repository, the last commit for
  which GitHub signed "a workflow ran here". An upgrade multisig or a DAO can then require that the binary it is
  about to deploy was built by CI from that commit. It is written against the first deployment.
- **A vault with no private key, and a record of what CI built.** [`examples/workflow_vault`](../examples/workflow_vault)
  releases tokens only on a token from one workflow file at one commit of one repository;
  [`examples/upgrade_gate`](../examples/upgrade_gate) records that GitHub's runner built an executable from a commit,
  and the upgrade script refuses a buffer without that record. Both read the second deployment.
  [COMPOSE.md](COMPOSE.md) lists every way to build on Knos, with an example for each.
- **Anything addressed to a GitHub account.** Grants, airdrops to contributors, access passes: the recipient shows
  who they are by running a workflow in a repository they own.

## Use it from a program

A verified token is an account owned by knos-oidc. Your program reads it. There is no CPI and no oracle.

The interface crate, [`crates/knos-oidc-interface`](../crates/knos-oidc-interface), has no dependency and does not
allocate, so it builds with solana-program, pinocchio or anchor of any version:

```toml
knos-oidc-interface = { git = "https://github.com/drexthealpha/Knos", tag = "v0.3.24" }
```

```rust
use knos_oidc_interface::{Token, ISSUER_GITHUB};

let data = token.try_borrow_data()?;
// refuses an account the second deployment does not own, a token not verified to the end, one over an hour past
// its expiry, and one a private key verified. `Token::read` is the second deployment's (`v2::read` is the same by
// name); the first deployment is read only by naming it, `v1::read`
let tok = Token::read(&token.owner.to_bytes(), &data, clock.unix_timestamp).map_err(|_| ProgramError::InvalidAccountData)?;
if tok.issuer() != ISSUER_GITHUB { return Err(ProgramError::InvalidAccountData); }
let repo = tok.claim_u64("repository_id").ok_or(ProgramError::InvalidArgument)?;
let sha = tok.claim("sha").ok_or(ProgramError::InvalidArgument)?;
let aud = tok.audience().ok_or(ProgramError::InvalidArgument)?;
if repo != MY_REPOSITORY_ID || !aud.is("my-app:release") { return Err(ProgramError::InvalidArgument); }
// GitHub signed that a workflow in that repository, at commit `sha`, asked for this audience
```

[`examples/oidc_gate`](../examples/oidc_gate) is a whole program written this way, with its test; reading a verified
token costs it 21,632 compute units. The instructions and account layouts of both deployments are in
[`idl/`](../idl) (Shank format, checked against the clients by `tests/test_idl.py`). From JavaScript:
[`sdk/settle`](../sdk/settle), one file with no dependency, attached to every release as an npm tarball.

Six things your program must decide for itself, because knos-oidc only says the token is genuine:

1. **Who ran the workflow.** Pin the repository (`repository_id`) or its owner (`repository_owner_id`). These are
   the claims an outsider cannot get GitHub to sign.
2. **What code ran.** Check the workflow file and its commit (`job_workflow_ref`, `job_workflow_sha`) if the
   statement depends on it. A commit fixes the file's content.
3. **Not the runner alone.** `runner_environment` says `github-hosted` for a runner whose image an organisation on a
   paid plan built itself, and a reusable workflow's runner is chosen in the caller's account. So a pinned workflow
   called from a stranger's repository tells you little: whoever owns the repository the run happened in can have
   decided what the workflow saw ([SECURITY.md](SECURITY.md), section 1). Treat what a workflow derived as that
   repository's own word.
4. **The audience, and replay.** Give your program its own audience prefix and require it, so a token minted for
   another program cannot be used with yours. A verified token can be read by any program, any number of times,
   until an hour after its expiry. Bind it to one action in the audience and keep a guard, as `knos-pay` does for
   each of its instructions.
5. **Whether the key is still good** (second deployment). A token account that was verified stays verified if its
   key is revoked or expires afterwards. To refuse such a token, take the key account the token account names (its
   bytes 18 to 50) and ask `key_usable` (the interface crate has `key()`, `check_key()` and `key_usable()`), as
   `key_good` does in [`programs-v2/knos_pay/src/gh.rs`](../programs-v2/knos_pay/src/gh.rs).
6. **Which issuer, and whether the key is private** (2.1). `issuer()` is GitHub, GitLab, another registered issuer
   or a private key's. For a registered issuer compare `issuer_hash()` with the sha256 of the URL you accept. A
   private key says only what the wallet that registered it says: `Token::read` refuses its tokens, and a program
   that wants them calls `Token::read_any`, asks `is_private()`, and accepts the token only from the `registrant()`
   it trusts for that purpose. `knos-pay` does that for one case: a private order paid out of the registrant's own
   Balance.

## Put a token on chain

From a workflow, ask GitHub for a token with your audience (`id-token: write`):

```bash
curl -sSf -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
  "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=my-app:release" | jq -r .value
```

Then anyone can carry it to the chain. It is three kinds of instruction, the same bytes for both deployments (the
Python client is [`src/knos/settle/v2/oidc.py`](../src/knos/settle/v2/oidc.py); the instruction bytes are in
[`sdk/settle/fixtures.json`](../sdk/settle/fixtures.json)):

| instruction | what it does | how many |
|---|---|---|
| `Write` | copies the token's bytes into an account derived from the payer and the token's hash | 880 bytes each: 3 for a GitHub token of about 2,100 bytes |
| `Step` | checks the RSA signature in Montgomery form, a few squarings at a time; the last one also checks the header and the issuer and decodes the claims | 2 for RSA-2048 (8 and 8 squarings), 6 for RSA-4096 (2, 3, 3, 3, 4 and 1), each in a transaction of its own |
| `Close` | returns the account's rent to the payer | 1 |

A token account belongs to whoever paid for it; nobody else can write or close it. [BENCH.md](BENCH.md) has the
compute units of every step.

Those are the instructions. How many transactions carry them is the sender's choice. The relay in this repository
puts a whole token of up to about 3,700 bytes beside its first `Step`, and the last `Step`, the consumer's
instruction and `Close` together, so a token is two transactions. It does that only where 4,096-byte transactions
are accepted and `knos-pay` 2.1 answers; elsewhere it falls back to the smaller ones ([BENCH.md](BENCH.md)).

## The trust root of the second deployment

Fixed in [`programs-v2/knos_oidc/src/pins.rs`](../programs-v2/knos_oidc/src/pins.rs); the module documentation of
[`lib.rs`](../programs-v2/knos_oidc/src/lib.rs) lists every instruction.

- **Genesis keys.** The sha256 of the modulus of each of the four RS256 keys GitHub Actions published on 2 Oct 2026
  is a constant in the binary. `RegisterKey` creates a key account for a modulus with one of those hashes, for
  anyone who pays the rent. Such a key verifies at once.
- **Every other key**, a GitLab key or one GitHub adds later, needs a verified GitHub token of the rotate workflow
  (`drexthealpha/knos-oidc-rotate/.github/workflows/rotate.yml` at the one commit in the binary), run by its
  schedule or by hand in one of two repositories of the account drexthealpha, whose audience names the key's hash.
  That key verifies nothing for a day, and nothing at all until the guardian approves it.
- **Any other RS256 issuer** (2.1, `RegisterIssuerKey`): the same run fetched the issuer's
  `/.well-known/openid-configuration` and its key set over TLS and named the issuer's URL and the key. The URL is
  stored with the issuer's first key, and `Step` requires each token's `iss` to be that URL. The same day's wait,
  approval, expiry and revocation apply.
- **Every key expires** 30 days after it was registered or last attested. `Refresh` takes the same attestation and
  moves the expiry forward. Anyone may send it. Since 2.1 anyone can also make the attestation that refreshes a key:
  the same pinned workflow, started by hand in a repository owned by the person who started it. That run never
  registers a key.
- **An attestation counts only while the key that verified it is usable** (2.1): `RegisterKey`, `RegisterIssuerKey`
  and `Refresh` take that key's account.
- **A private key** (2.1, `RegisterPrivateKey`): any wallet, no attestation, for an issuer no public runner can
  reach. It is usable at once, expires like any key unless its registrant sends it again, and the registrant or the
  guardian revokes it. Its tokens attest nothing here.
- **The guardian**, a multisig vault, can approve an attested key and revoke any key for ever. It cannot add one.
- **The arithmetic.** RS256 is PKCS#1 v1.5 with SHA-256. The verifier accepts exactly one encoding, exponent 65537
  only, and is tested against Google's Wycheproof vectors and against OpenSSL ([BENCH.md](BENCH.md)).

`Step` refuses a key that is not ready, is revoked, is neither a genesis key nor approved, is before its start or
past its expiry (errors 68 and 76 to 78). [SECURITY.md](SECURITY.md), sections 5 to 7, says who can do what to a
key and to the program.

## Issuers you can use today

"Use" means: a token of that issuer becomes a verified account on the second deployment, and a program reads it.
Who may add a key is the program's rule ([The trust root](#the-trust-root-of-the-second-deployment)); the cost is
the rent of the key's account, measured in the simulator with Solana's rent rule, plus each transaction's fee.

| Issuer | What it takes | Who may | Cost | What reads it | Tested |
|---|---|---|---|---|---|
| GitHub Actions (RS256) | Nothing: its keys are genesis keys. `curl` the token in a job with `id-token: write` ([above](#put-a-token-on-chain)) | anyone | no key rent; the token's own transactions ([BENCH.md](BENCH.md)) | `knos_pay`, `knos_meter`, any program | Exercised at the public ids ([CAPABILITIES.md](CAPABILITIES.md), `verify_github`) |
| GitLab CI, gitlab.com (RS256) | Nothing for the reader: `id_tokens:` in `.gitlab-ci.yml`. Its keys are named by the rotate workflow and approved by the guardian; `knos keys` prints whether each is usable now | anyone, once a key is usable | no key rent for the reader | `knos_pay` (fund an order, pay an order), any program | Simulator: `tests/test_gitlab_pay.py`, `tests/test_gitlab_round.py`. Not run against gitlab.com: [one command does](#the-round-as-one-command) |
| Another RS256 issuer with a public URL (Google, Entra, Buildkite, a self-managed GitLab, ...) | A run of the rotate workflow with `issuer: <url>` names the key (`RegisterIssuerKey`), then one day's wait and the guardian's approval | the account drexthealpha only, then the guardian | 5,178,240 lamports of rent for a 2048-bit key (616 bytes), 8,741,760 for a 4096-bit key (1,128 bytes) | any program that compares `issuer_hash()`; not `knos_pay`, not `knos_meter` | Simulator, with test keys: `tests/test_issuers.py` (eleven shapes). No such issuer has a key at the public id: not tested there |
| Any RS256 issuer, as a private key (a cluster, an issuer no runner can reach) | `RegisterPrivateKey` and `KeyParams` from your wallet: `python scripts/outcome_k8s.py chain --token T --jwks J --issuer URL --receipt R --keypair FILE --send` sends both, then the token | any wallet; nobody vouches for the key | the same rent, paid by that wallet | a program that calls `Token::read_any` and trusts that `registrant()`; `knos_pay` for one case (a private order paid from the registrant's Balance) | Simulator: `tests/test_outcome_k8s.py`. At the public id: the round `issuer` of `scripts/exercise_public.py` ([OUTCOMES.md](OUTCOMES.md)) |
| An ES256 issuer, as a private key (SPIRE, Supabase) | `RegisterPrivateEs256Key`, then the precompile's instruction and `VerifyEs256` in one transaction (`register_private_es256_key_ix`, `verify_es256_ixs` in [`oidc.py`](../src/knos/settle/v2/oidc.py)); no `knos` command | any wallet, once the build that carries it is live | not measured here | a program that calls `Token::read_any` | Simulator: `tests/test_es256_client.py`. Not deployed until proposal 7 executes ([ES256.md](ES256.md)) |
| An ES256 issuer admitted by an attestation | not possible yet: no pinned workflow asks for that audience, and there is no client | nobody | | | not tested |
| ES384, ES512, PS256, EdDSA | not verified | | | | refused in `tests/test_issuers.py` |

## GitLab

knos-oidc verifies a gitlab.com ID token as it verifies GitHub's. `knos-pay` 2.1, the build of proposal 4 of the
upgrade multisig, reads one too ([`programs-v2/knos_pay/src/gl.rs`](../programs-v2/knos_pay/src/gl.rs)), for two things: funding a work order
from a Balance, and paying one. It is tested in LiteSVM against tokens shaped as GitLab documents them
([`tests/test_gitlab_pay.py`](../tests/test_gitlab_pay.py)); it has not run against a token gitlab.com signed, and
[`examples/gitlab/.gitlab-ci.yml`](../examples/gitlab/.gitlab-ci.yml) has not run in a project. Running it there is
[one command](#the-round-as-one-command). The claims are
GitLab's own list, read on 4 Oct 2026:
[OpenID Connect (OIDC) Authentication Using ID Tokens](https://docs.gitlab.com/ci/secrets/id_token_authentication/).

| what the escrow asks | GitHub's claim | GitLab's claim | how it is read |
|---|---|---|---|
| which repository | `repository_id` | `project_id` | 900000000000000000 + the id |
| whose Balance pays | `repository_owner_id` | `namespace_id` | 800000000000000000 + the id |
| who asked, who is paid | `actor_id` | `user_id` | 900000000000000000 + the id |
| which file ran | `job_workflow_ref` | `ci_config_ref_uri` | whole (project path, file, ref); the order stores its sha256 |
| at which commit | `job_workflow_sha` | `ci_config_sha` | 40 hex characters; the order stores it |
| on whose machine | `runner_environment` `github-hosted` | `runner_environment` `gitlab-hosted` | anything else is refused |
| what started it | `event_name` | `pipeline_source` | `web` funds, `pipeline` pays, nothing else does either |
| a protected ref | not asked | `ref_type` `branch`, `ref_protected` `"true"` | required of every GitLab token |
| a first attempt | `run_attempt` 1 | none | see below |
| the audience | `aud` | `aud` (`id_tokens: aud:`) | `knos3:fund:...` or `knos3:pay:...` only |

**Ids cannot meet.** A GitLab id is read into a range of its own, and the escrow refuses a GitHub token (and a
token under a private key) whose repository, owner or actor id is 800000000000000000 or more. GitHub's ids are
around ten digits today. The ranges are decimal so that an audience, which carries ids as at most 18 digits, can
name a GitLab payee: user 4242 is payee `900000000000004242`. GitLab numbers users and namespaces apart (a user's
own namespace has another number than the user), so they get two ranges, and no GitLab token passes a rule that
asks whether the actor owns the repository.

**The pin.** `ci_config_ref_uri` and `ci_config_sha` are null when the CI file is kept in another project; such a
token is refused. When it is in the project, `ci_config_sha` is the commit the pipeline ran on: GitLab signs no
commit for a file kept apart from the code, as GitHub's `job_workflow_sha` is. So the pinned file lives on a
protected branch that does not move (the example calls it `knos`). The order stores the URI's hash and that
commit, and pays only on a token of exactly that file, branch and commit. The default branch's own pipeline after
a merge has another commit and is refused; it starts the pinned one (`trigger:`, which GitLab signs as
`pipeline_source` `pipeline`:
[downstream pipelines](https://docs.gitlab.com/ci/pipelines/downstream_pipelines/)), and the pinned job reads the
merge request from GitLab's API before it lets the token out.

**What GitLab does not sign, and what follows.**

- *Which branch is the default one, and that a merge request was merged.* No claim says either. The escrow asks
  for a protected branch and for a pipeline that a pipeline started; that the merge request was merged into the
  protected default branch, and by whom it was written, is read by the pinned job, as GitHub's pinned workflow
  reads it.
- *An attempt number.* GitLab says of a retry: "The new job associates with the user who initiated the retry,
  not the user who created the original pipeline" ([Retry jobs](https://docs.gitlab.com/ci/jobs/)), so `user_id` is
  the person who asked, which is what the first-attempt rule protects on GitHub. A retried paying job does give a
  second token with the same claims; an order pays once whatever the number of tokens.
- *That a namespace is one person's own.* So nothing that rests on it is offered: no neutral run started by the
  seller, no arbiter's ruling, and a Balance's owner is not a spender unless listed.
- *An event for an issue or a comment.* A person funds from a Balance by running the pinned pipeline by hand. An
  order can also be funded from a wallet with no pipeline at all: the wallet names the project (900000000000000000 +
  its id) and pins the CI file's URI and commit, and the pinned pipeline pays it
  (`tests/test_gitlab_round.py`).

### The round as one command

    python scripts/gitlab_round.py check
    GITLAB_TOKEN=... KNOS_GITLAB_PROJECT=group/name python scripts/gitlab_round.py run --rpc <devnet rpc> --keys <keys>
    python scripts/gitlab_round.py run --simulate

`run` pushes the example's file to the branch `knos` and protects it, adds the trigger job to the default
branch when the project has no CI file, opens and merges one merge request whose description names an address, funds
an order for it from the wallet `<keys>/funder.json`, starts a pipeline on the default branch with the pay audience
(its trigger job starts the pinned pipeline, which GitLab signs as `pipeline_source` `pipeline`), reads the token the
pinned job left, holds it to the escrow's rules for nothing, has `knos_oidc` verify it and sends `PayOrder`. Each step
is kept, so a second run takes up where the first stopped. It exits 3, having sent nothing, and says exactly what is
missing when there is no token, no project, no usable GitLab key at the public `knos_oidc`, or a pipeline that has
not finished. `--simulate` runs the same steps in the simulator against a stand-in for gitlab.com written in the
script, with tokens the test key signs: evidence of nothing on gitlab.com.

**Not seen on gitlab.com yet**, and the first real run settles each: that a `trigger:` job naming the pipeline's own
project gives the downstream pipeline the source `pipeline` (GitLab documents that source "for multi-project
pipelines": [`CI_PIPELINE_SOURCE`](https://docs.gitlab.com/ci/jobs/job_rules/)); that a token for a pay audience of
about 240 characters fits the verifier's 8,192 bytes for the user who runs it (`groups_direct` lists up to 200
groups); that GitLab's keys are usable at the public id on the day. The command checks the second and third before a
fee is spent and names the claim that is off for the first.

**What a GitLab project cannot do yet.** Bind a wallet (the pay token must carry the payee's address; with none
the order is held and goes back to its funder when the hold ends); reserve, cancel or revert an order, or fund a
2.0 job (a GitLab token with any other audience is refused); use the devnet faucet (send test USDC to the Balance,
or fund from a wallet); pin a file on a self-managed GitLab (gitlab.com only); use a runner of its own. The always-on
relay refuses a GitLab token for the escrow, there is no `knos` command and no page: the token is carried by
`scripts/gitlab_round.py`, or with the client in `src/knos/settle/v2`. The example's paying job does not check the
order's terms on Solana; it says so where it would. The carrier does check the order's project, pin and terms before
it sends, which is the carrier's word and not the judge's.

**No longer on that list** (no program change was needed): a command that carries the token; funding without a
person starting a pipeline in a browser (a wallet-funded order); and the example's check that the default branch is
protected, which asked an endpoint that needs a token the job does not have and now reads the branch itself
([`GET /projects/:id/repository/branches/:branch`](https://docs.gitlab.com/api/branches/), open for a public project).

## Limits

- Tokens up to 8,192 bytes. RS256 with 2048- or 4096-bit keys is what the public program ids verify. ES256 is
  built and tested, not deployed: one transaction, Solana's secp256r1 instruction checks the signature and
  `VerifyEs256` checks what it verified, for a token whose signing input is at most 780 bytes
  ([ES256.md](ES256.md)). ES384, ES512, PS256 and EdDSA tokens are not verified.
- Since 2.2 a token's header and payload are each one JSON object of RFC 8259, at most 64 levels deep, with at most
  128 members at the top level and no name there twice (the GitHub-shaped token of the tests has 31 members and
  one level). A name twice inside a nested object is not looked for. Before 2.2 a value the verifier does not read is not checked.
- A key of an issuer other than GitHub is registered only by the one account whose run counts, and then approved by
  the guardian. Nobody else can admit an issuer, except as a private key.
- A token is accepted until one hour after its `exp` (the issuers' tokens live five minutes; relaying takes time).
- On the second deployment a token of any issuer but GitHub verifies only once a key of that issuer has been
  attested and approved. None is a genesis key there. `knos keys` prints the keys the verifier holds and whether each can be used now.
- The second deployment's keys need attesting at least every 30 days. If that stops, nothing verifies until an
  upgrade ([SECURITY.md](SECURITY.md), "When keys run out").
- The first deployment is immutable, so its faults are for ever: a key it trusts never expires and cannot be
  revoked, and a key attestation counts from any repository.
- Devnet only, and no outside review yet. Mainnet waits for one.
