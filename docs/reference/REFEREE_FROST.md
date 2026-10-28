# The referee panel as one FROST threshold key

A milestone's held money on knos_pay is released by a referee PANEL: the order pins m of n Ed25519 keys and the program
counts their signatures through Solana's Ed25519 precompile (section 3 below). Until now Knos's devnet panel was three
keys on one server.

It is now ONE key that no machine holds: the Zcash Foundation's FROST
([frost-ed25519](https://crates.io/crates/frost-ed25519) 3.0.0, RFC 9591 FROST(Ed25519, SHA-512)) splits it into three
key shares on three hosts, and any two of them produce one standard Ed25519 signature under the group key.

| host | holds | where |
|---|---|---|
| 1 render | one share | the Knos app server (knos.onrender.com), a Render secret file (`KNOS_REFEREE_FROST_SHARE`) |
| 2 gh | one share | GitHub Actions in drexthealpha/Knos, repository secret `KNOS_REFEREE_FROST_SHARE`, `.github/workflows/referee.yml` |
| 3 operator | one share | host 3, run by the operator on a separate machine (`python -m knos.threshold serve`) |

Hosts 1 and 2 complete a release when host 3 is offline.

## What the deployed program accepts

`order_proof.rs` `panel_of` accepts any panel with `1 <= m <= n <= 10` distinct non-zero keys, and the tally pays at
`m` distinct panel keys that signed the verdict digest in the transaction.

A **1-of-1 panel whose one key is the FROST group key** is therefore a valid PANEL order on the knos_pay 0.3.34 test
program `FaMHCjzyUexFncZrmNyFQNz3gBdsLbhTLke7QBFykJY4`, with no program change: one precompile entry (group key,
aggregated signature) releases it in one transaction. Tested in LiteSVM against
`tests/fixtures/knos_pay_v2_0334_test.so` (`tests/test_threshold_frost.py`).

The group key (devnet test): `CZ599fmDD6ATkRsbUbdZiAQE7uF9sJrGFmJ6k54ujb4E`, panel `1:CZ599fmD…`, public record
`config/referee-frost.json`, also in `config/referees.yaml`.

## How a release is signed

1. The maker posts evidence (`POST /api/milestone`). The app server checks it, opens a signing session for the stage's
   verdict digest and signs as host 1. Hosts 2 and 3 poll `/api/referee/pending`: `referee.yml` runs on a cron every
   5 minutes (and on workflow_dispatch), host 3 every 30 s. No hand-made token starts host 2.
2. Each host **re-checks the milestone itself** (`knos.threshold.check`): it reads the order on devnet, fetches the
   evidence page (https, public address, no redirects), requires the claim id in it and recomputes the digest. A host
   never signs a digest the coordinator hands it.
3. FROST round 1: each host posts its commitments (`/api/referee/commit`). At two, the coordinator fixes the signing
   package. Round 2: the two chosen hosts post signature shares (`/api/referee/share`). Every post carries the host's
   transport signature (an Ed25519 key in its share record, public key in the group record). Host 2's posts also
   carry the job's GitHub Actions OIDC token (audience `knos-referee`); the app server verifies it against GitHub's
   published keys and requires repository `drexthealpha/Knos` (by repository and owner id), workflow
   `.github/workflows/referee.yml@refs/heads/main`, ref `refs/heads/main` and a schedule or workflow_dispatch run
   (`knos.threshold.ghoidc`).
4. The coordinator aggregates (frost verifies every share), checks the signature under the group key and sends it as an
   ordinary verdict of the group key (`knos.ideas.commit.release`).

Nonces live only in the signing process's memory and are used once. One share alone produces no signature.

## Key generation

`python -m knos.threshold dkg-local --out DIR` runs FROST's distributed key generation (no dealer) as three separate
processes. They exchange round-2 packages encrypted to each other (X25519, HKDF-SHA256, ChaCha20-Poly1305) through a
relay that sees only public packages and ciphertexts.

The devnet group was made this way on host 3, run by the operator on a separate machine, because hosts 1 and 2 run
this code only after the next push. Until the Render and GitHub shares were uploaded and deleted from it, that one
machine held all three shares.

## The code referee's attestation (GitHub Actions, knos_oidc on chain, Sigstore)

The referee is code: `knos.threshold.check.milestone_digest`, run by each host itself. Host 2 runs it in GitHub
Actions, and that run is attested with no account anywhere (`knos.threshold.codeattest`):

1. **The verdict.** For every session whose digest its own check recomputed, `referee.yml`'s job `sign` writes one
   verdict file (canonical JSON): the session, the digest the FROST group signs, the order, the evidence page's
   sha256, and the run's repository, `workflow_ref`, commit and run id. It is kept as the run's artifact
   `referee-verdicts`.
2. **The attestation.** Job `attest` holds no key share and no secret. It runs `actions/attest-build-provenance`
   v4.2.2 over the verdict files: a SLSA v1 provenance statement, signed keyless through Sigstore's public-good
   instance (a Fulcio certificate for the run's OIDC identity, logged in Rekor). The app server checks the bundle
   against Sigstore's public trust root with Knos's own Sigstore adapter (`knos.sources.sigstore`, whose trusted
   root is pinned by sha256). For a bundle in a Rekor log that adapter cannot read, it uses sigstore-python 4.5.0.
   The certificate identity must be
   `https://github.com/drexthealpha/Knos/.github/workflows/referee.yml@refs/heads/main`, issued by GitHub Actions, at
   the verdict's commit, and the statement's subject must be the verdict's sha256. Anyone can check the same:
   `gh attestation verify verdict-<session>.json -R drexthealpha/Knos`, or
   `python -m knos.threshold.codeattest verify verdict-<session>.json`.
3. **On chain.** The same job asks for an OIDC token with the audience `knos-referee:verdict:<sha256 of the verdict>`
   and posts it with the verdict to `POST /api/referee/attest`. The server verifies it (`knos.threshold.ghoidc`:
   referee.yml on main of drexthealpha/Knos, by repository and owner id). Then the deployed knos_oidc verifies it on
   devnet (`knos.settle.v2.relay.verify_only`: Write, then Step, RS256 under GitHub's key; the relayer pays the fee).
   The token account `["tok", relayer, sha256(token)]` is then VERIFIED, owned by knos_oidc, and holds the decoded
   claims: `repository`, `workflow_ref`, `sha`, `run_id`, and the audience that names the verdict's hash. No program
   was changed for this. It is the verify path that knos_oidc already has.
4. **The release** is unchanged: 2 of the 3 hosts sign the digest the verdict names.

The session records all of this (`code_referee`), and the project milestone page shows four links per order: the
referee run, the knos_oidc verification transaction, the Sigstore attestation (GitHub's attestation page and its Rekor
entry) and the FROST release transaction.

`knos.threshold.attest` (a Google Confidential Space token verifier) is **unused**: nothing calls its `verify`.
ghoidc uses its RS256 helpers. It is kept only because it is tested. Knos runs no Confidential Space referee and
claims none.

## Limits

- The game's sample payments (`apps/wanted/knos_wanted/tasks.py`, paid from Knos's own devnet test wallet) use the
  FROST group too: the round's verdict is published on its evidence page, and 2 of the 3 hosts fetch and re-check that page
  before they sign. Without the FROST group configured, 2 of the server's 3 keys sign as before.
- Project milestones (`apps/wanted/knos_wanted/valley.py`) pin the FROST group too: once the result and the
  independent check are in, the review (both pages' URLs and sha256s, every funded order's claim id) is published at
  `/api/project/evidence?id=`, one session opens per funded order, and the second share releases it to the maker and
  the referrer's share. Orders made before the group was configured keep the 3 server keys until they settle.
- FAIL verdicts: refunds after the deadline need no verdict. A threshold FAIL verdict is not built.

## Pay on proof from any source

Until 0.3.34 every Knos work order was released by a forge: a workflow at a pinned commit, run on GitHub or
gitlab.com, whose token `knos_oidc` verified on chain. Research does not all live on a forge.

This page is what knos_pay 0.3.34 adds so that the machine referee pays on proof from any source, and what it
does not do yet.

**Status.** Built and tested in LiteSVM (test builds). The referee-panel path ran on devnet at a test program id this
build's agent owns (section 8). The real knos_pay program (`5y7iWJ1V…`) is NOT changed: its upgrade buffer (written, held by the vault) waits for
the Squads vote (section 9).

No real ORCID id_token has been
verified: those paths are tested with test issuer keys registered for the issuers' real URLs. Synthetic data only.

### 1. One door, one reader per issuer family

Every instruction that takes a token goes through `issuers::checked` (programs-v2/knos_pay/src/issuers.rs): the
account is knos-oidc's and VERIFIED, its issuer family is one the instruction accepts, it is fresh, and the key that
verified it is still usable. Then the family's own reader reads the claims.

| family | told by | reader | what it may do |
|---|---|---|---|
| GitHub Actions | knos-oidc issuer number 0 | gh.rs | everything it did before (unchanged) |
| gitlab.com CI | issuer number 1 | gl.rs | fund and pay a work order (unchanged) |
| private key | issuer number 3 + registrant | gh.rs | pay a private order of the registrant's Balance (unchanged) |
| Google Confidential Space | issuer 2, sha256 of `https://confidentialcomputing.googleapis.com` | cs.rs | pay an order that pins a container image |
| ORCID | issuer 2, sha256 of `https://orcid.org` | orcid.rs | bind an ORCID iD to a wallet (Bind) |

A private key registered under Google's or ORCID's URL stays PRIVATE: the number is read first.

**No new instruction number.** The new paths ride on instructions that exist: FundOrderWallet (15) with options byte
35, PayOrder (17) with a Confidential Space token or with a verdict as data, RefundOrder (22) with a FAIL verdict as
data, and Bind (8) with an ORCID id_token. One account kind is new: a verdict's tally (80 bytes).

**Compatibility.** GitHub and GitLab tokens pass the same checks in the same order with the same error codes; orders of
earlier builds have zero in the new referee byte and take the old path.

Checked three ways: the Rust replay vectors of
2.2's scenarios (`programs-v2/testdata/*.json`, answers and account bytes) regenerate byte-identical against the
0.3.34 test build; the existing order, job, quorum, relay, GitLab, Bind and IDL tests pass against it; and the unit
tests of the program pass unchanged.

### 3. Referees for evidence no issuer signs (m of n)

An order funded with referee 2 pins a panel: `sha256("knos3:panel" || m || n || n Ed25519 keys)`, 1 <= m <= n <= 10.
Each referee signs the 32-byte verdict digest

    sha256("knos3:verdict" || program id || order || order stamp i64 LE || terms hash || evidence sha256 || verdict)

where `verdict` is the payees text for a PASS and `FAIL` for a FAIL. PayOrder with data (a PASS) and RefundOrder with
data (a FAIL) read Solana's Ed25519 precompile in the same transaction by instruction introspection: only entries whose
key, signature and message are in the precompile's own data count.

Distinct panel keys are counted; below m the signers are recorded in a tally `["vd", order, digest]`; the transaction
that brings the m-th pays the payees (PASS) or returns everything to the funder (FAIL). After the deadline RefundOrder
needs no signature.

The stamp changes with every funding of an address, so a verdict acts only on the order and the funding it was signed
for.

| attempt | answer |
|---|---|
| one referee signing twice in one transaction | counted once (below m: recorded, nothing paid) |
| the same referee again later | E_REPLAY (91) |
| a verdict signed for another order | E_CLAIMS (85) |
| old signatures after the order was refunded and funded again at the same address | E_CLAIMS (85) |
| a key outside the panel, or another m | E_CLAIMS (85) |
| one referee's PASS and another's FAIL | two verdicts, one signer each: nothing moves |
| after the deadline | E_STATE (83); RefundOrder with no data refunds |

One signature per transaction fits the 1,232 bytes of a v0 transaction with a 3-key panel and one payee; two in one
transaction were 1,298 bytes in the test (a v1 transaction, 4,096 bytes, takes them).

The off-chain mirror is `knos.platform.verdict`: `message(job, evidence_hash, verdict, amount, recipient, expiry,
nonce)`, `parse`, `outcome` ("release" for PASS, "refund" for FAIL) and `check(message, sigs, keys, m, now=, used=)`. On
chain the job is the order's address, the nonce its funding stamp, the expiry its deadline.

`check` spends the verdict it accepts: (job, nonce) goes into the caller's `used` set (or a process-wide store when none
is given), so checking the same verdict again is refused as a replay, as knos_pay refuses it on chain (E_REPLAY).

### 3a. Trust model: who decides the money

Said plainly: **whoever holds the panel keys decides the money.** On chain a referee-panel order pays, or refunds,
whatever m of its pinned keys sign. The chain does not read the oracle (a referee signs whatever its own reading says)
and does not know who holds the keys.

If the funder holds the keys, the funder can refund a stage that was met; if the keys collude with a payee, they can
name that payee. In 0.3.34 the payees are named by the verdict. They are not fixed at funding.

What Knos's client tools do about it:

- **A published referee registry**, `config/referees.yaml`: the public keys Knos accepts as referees, each labelled.
  Today it holds three DEVNET TEST keys (made by the build agent, test money only). Knos has published no production
  referee key.
- **The panel rule** (`knos.platform.referees.panel_rule`), applied by `knos.platform.verdict.check`, the idea panel
  tools (`knos.ideas.wanted.fund_panel_ix`, `stage_verdict_ixs`, `python -m knos.ideas.devnet_panel`) and the MCP tool
  `knos_graduate`:
  - a panel holding the funder's or a payee's own key is refused (that party would check itself);
  - a panel with keys outside the registry is refused by the command-line and MCP tools;
  - `--unlisted-panel` (`unlisted_panel=True` in Python, `"unlisted_panel": true` in a graduation verdict) uses such a
    panel anyway, and every output then says `UNLISTED PANEL`. Python callers written before the registry, which pass
    no choice, get the label and a warning.
- **`knos_graduate` (MCP) needs a signed verdict**: m signatures of a registry panel over
  `knos.graduation.graduation_message(claim_id, spec_hash, expiry)`. An unsigned `{"passed": true}` is refused.
- **Spent verdicts persist**: `knos.platform.verdict.check` keeps every verdict it accepts in
  `KNOS_HOME/verdicts/spent` (one file per verdict, created atomically), so a second check is refused in any process on
  the machine. A caller that passes its own `used` set keeps its own.

What none of this does: it does not stop a funder who writes his own client and pins his own keys. Against that, only
what is on chain helps. Until payees are pinned at funding, the payee is whoever the m referees name.

### 4. ORCID iDs as payees

Bind (8) takes an ORCID id_token (issuer `https://orcid.org`, RS256, one RSA-2048 key; discovery fetched 14 Oct 2026) whose
`aud` is Knos's own ORCID client id, whose `nonce` is `knos3:bind:<wallet>`, and whose `sub` is a well-formed iD with a good
check character (ISO 7064 MOD 11-2).

It writes `["bind", OR_BASE + the first fifteen digits]` (OR_BASE = 10^18: above every GitHub and GitLab id). Proofs and
verdicts then name a payee by iD: `0000-0002-1825-0097.10000.-`.

The token lives 24 hours in ORCID's own example ([ORCID's OpenID Connect
guide](https://github.com/ORCID/ORCID-Source/blob/main/orcid-web/ORCID_AUTH_WITH_OPENID_CONNECT.md)), so its marker is kept
until it cannot be fresh; a Bind is replaced only by a later sign-in. Knos's ORCID public API client is not
registered and `orcid.rs` `ORCID_CLIENTS` pins none, so a real build binds nothing today.

### 5. What a checked order cannot have

No forge referee (its workflows repository is zero bytes), quorum, neutral run, standing rate, AUTO, holdback, kill
fee, reservation, arbiter, referee repository or privacy salt: each needs a forge token. The presentation grace is
allowed. A Balance funds none. Money moves as for any wallet's order: in by the funder's transfer, out to payees, tip
and fee, back by RefundOrder.

### 6. Compute units (LiteSVM, test build, knos_pay's own instructions)

The referee path's numbers on devnet are in section 8 (fund about 45,000; one signature recorded about 35,000; the
m-th pays about 81,000 with one payee). In LiteSVM, with the test build and test issuer keys:

| path | CU |
|---|---|
| PayOrder on a Confidential Space token (one payee, its token account created) | 176,482 |
| Bind with an ORCID token | 56,508 |

Verifying the RS256 token itself is knos_oidc's cost (PLATFORM.md).

### 7. Keys and accounts this needs

- Google Confidential Space's and ORCID's keys in knos-oidc: RegisterIssuerKey by the pinned rotate workflow, the
  guardian's approval, Refresh every 30 days (actions on the real program by the attester and the guardian).
- Knos's ORCID client id (not registered).

Tests: `tests/test_proof_issuers.py`, `tests/test_platform_verdict.py`, `programs-v2/handlers/tests/knos_pay_proof.rs`
(replays `programs-v2/testdata/pay_on_proof.json`), unit tests in `programs-v2/knos_pay/src/{issuers,cs,orcid,order_proof}.rs`.
Clients: `src/knos/proof/issuers.py`, `src/knos/platform/verdict.py`.

### 8. Devnet

The sBPF v3 deploy build (executable hash `9ae13fb9ae35262a959a903fae7b742e07a425ab97fc05fcf38b7db1bd1f0c62`, 413,400 bytes) runs at a TEST
program id the build agent deployed, `FaMHCjzyUexFncZrmNyFQNz3gBdsLbhTLke7QBFykJY4` (deploy
`3vuk1dtYquZf4jinzXcu7h36MAQs2n4X8k5NKec9U1q14oqSwXUJUFcjCrSNLoG8LXbKgRk3C3F9qayLiiMCSM6w`; bytes read back equal to the build).
Its upgrade authority moved from that agent's key to the Squads vault `CKCrTBN542pVhizxuSPVg8tvdnPooNxt9B7o97VuTjz2` on 26 Oct 2026
([the transaction](https://explorer.solana.com/tx/5j6WHnmt6qRD3KwafVYDQJLqzEPTZeZsyUimQwk6ccoaTUPJxCGWHHdvM1eT9JN7PgTtQZEe8ZPkmrjXcP2ZXYL8?cluster=devnet)): an upgrade now waits out the vault's 8-day time lock.

Labelled internal dogfooding: a test mint of the agent's own (6 decimals, no value), synthetic evidence, three fresh referee keys, payee named by
ORCID's example iD with an address.

| step | signature | bytes | knos_pay CU |
|---|---|---|---|
| fund an order checked by a 2-of-3 panel | `2Fw9aQZS59v4eaYo41suAHavYLwSQrhSVjrfPBajHGLZtBHkA3qnpHn6krQpcbBu8dhTVXnx955gyKKjx5cArnr9` | 681 | 45,167 |
| PASS, referee 1 of 2: recorded | `2AZVrYsELBNSACYCFnG3XeydRDK5VTrvBG9H7LRAjwgQpVobhYtx9haxvEXrYZyMY7AsBPEy5j2LycFxM9EAgHXn` | 1,157 | 34,657 |
| PASS, referee 2 of 2: 5.00 test units paid | `MDntcyKymFgrcUeZTkWg2JKtwxCzXGPvd8Ph3HXLjhQTKwEMh7z3TPoq7cS8LKEZ4d2WARFKXRdHtQxwqnbG2di` | 1,157 | 81,043 |
| fund a second order (the fail case) | `2oAntj2KHZZgPtwAMuQcP9LbNxxkPAprcZRLMU7xfeq5zRkq4Jonu2SUHdcR2rRwWZrQqkHBm8s9caFRKQXvPPxw` | 681 | 45,178 |
| FAIL, referee 1 of 2: recorded | `3uzX5db7g85AD762qnkjtcb3hx1UrUrpijQxHDfi7AT5Gy63HG2TzEhm3sDpMYGz5vagYhTRbdg8zmoNzdHFp2UL` | 822 | 25,911 |
| FAIL, referee 2 of 2: refunded to the funder | `WEF3zVbup4znZGL9MHwaFszTKJTi2rPqLoWp3XYvRTJRVuhrLpAj6LpskqmGKCJjCS9bZkRaRBMscs8VPoVVxgM` | 822 | 33,095 |

The CU column is what the knos_pay instruction itself used (the Ed25519 precompile is not a program call). The
Confidential Space and ORCID paths were not run on devnet: no Google or ORCID key is registered in the devnet
knos-oidc, and registering one is the attester's and the guardian's act on the real verifier.

### 9. The Squads steps for the real knos_pay

Nothing was proposed and nothing was signed. The upgrade buffer `Dfo5pYRLY8z9yvuXDQjJQtaoqJeL7Atso8zhWy9Ehkfj` is written (with the build team's own devnet test SOL)
and its authority is handed to the upgrade vault `CKCrTBN542pVhizxuSPVg8tvdnPooNxt9B7o97VuTjz2` (multisig
`9HcsMEo2o6zZu9t1kbFWpnyKn7hiHaZYYFwNHZSpmWqK`).
