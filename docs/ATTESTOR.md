# What the signature proves, and what it does not

A payment in Knos rests on a token a forge signed. This page says exactly what that signature covers, what it leaves
to a machine nobody signed for, and the five ways of narrowing that gap: what each costs, what it proves, what stays
trusted, and how mature it is today. Two of the five exist in this repository. Three do not, and the last section
says in which order Knos intends to take them. Outside pages were read on 2026-10-06 unless a line says otherwise;
every figure about another system carries its link.

## The gap, exactly

**Signed by the forge.** Which workflow file ran (`job_workflow_ref`), at which commit (`job_workflow_sha`), in which
repository (`repository_id`, `repository_owner_id`), started by which account and how (`actor_id`, `event_name`),
on which attempt (`run_attempt`), on what kind of runner (`runner_environment`), and when (`iat`, `exp`).
`knos_oidc` checks that signature on chain. [SECURITY.md](SECURITY.md), section 1, has the table.

**Not signed by anyone.** What that workflow read and what it computed. The text a payment acts on is the token's
`aud`, for example `knos3:pay:<order>:<head commit>:<terms hash>:<mode>:<pull request>:<payees>`. The workflow chose
that text after it asked the forge's API which pull request was merged and how its checks ended, or after it ran the
acceptance suite itself. GitHub signs that this run asked for that audience. It does not sign that the API said so,
that the suite passed, or that the machine ran the pinned file's commands the way the file wrote them.

So three things are taken on trust between the pinned file and the signed audience:

1. **The machine.** That the runner executed the file's steps unaltered.
2. **The answers.** That the bytes the job received from `api.github.com` are what GitHub's record holds.
3. **The code the job installed.** That `knos` on the runner is the release the workflow's hashes name.

**The repository's own example of (1).** In August 2026 a researcher showed that an organisation on a paid plan can
create a GitHub-hosted larger runner with an image of its own, give it the name of a standard label, and have it
serve jobs pinned to that label. A shell function in the image rewrote a source file before the compiler saw it and
restored it afterwards; the build's attestation verified, with `--deny-self-hosted-runners`, against a commit the
binary was not built from. Every signed field of the honest run and the altered run was the same, including
`runner_environment: github-hosted`
([research note](https://github.com/amiller/github-zktls/blob/master/tasks/substitution-demo/research-note.md), runs
of 21 to 24 August 2026; [community discussion 205732](https://github.com/orgs/community/discussions/205732), opened
24 August 2026, with no answer from GitHub's staff when read). The one fact that tells the two runs apart,
`runner_group_id` in the jobs API, is not in the token. Custom images are for organisations and enterprises on the
Team and Enterprise Cloud plans
([GitHub's documentation](https://docs.github.com/en/actions/how-tos/manage-runners/larger-runners/use-custom-images)),
which is why the neutral judge accepts only a run in a repository a personal account owns. That rule is GitHub's
product boundary, not a signature: [SECURITY.md](SECURITY.md) says what breaks if it moves.

For Knos the same move would be an organisation's runner that makes `prove.yml` report a passing suite, or answer
"merged, checks green" for a pull request that is neither. The token would verify.

## The ladder

| Rung | Closes | Still trusted | Today |
|---|---|---|---|
| a. Quorum of judges in repositories different parties control | one runner, one maintainer | the forge; that the parties are different people | built and tested in a simulator; never run on the public program ids |
| b. Re-execution by a neutral judge from pinned inputs | a check result that lies | the forge's hosted runner for a personal account; the suite itself | built; the re-execution has run only in tests |
| c. Build provenance of the judge | what code the judge installed | the forge as builder and signer; the machine (see the example above) | not built here; the parts exist at GitHub and Sigstore |
| d. Proof of what the forge's API returned | the answers | a notary or a proxy, or the proof system | not built; no system we found checks a transcript on Solana |
| e. An attested enclave runs the judge | the machine | the chip vendor's root key; side channels; the cloud | not built; GitHub offers no attested runner |

### a. A quorum of judges

**What exists.** `/knos fund ... quorum 2`: `PayOrder` pays only when that many distinct judges have each passed the
same head commit, terms, mode, pull request and payees ([SECURITY.md](SECURITY.md), section 19).

**What the chain enforces.** The judges are of different kinds (the order's own repository, a neutral run, a judge
repository), each from the pinned workflow at the pinned commit on a first attempt. A neutral run counts only when
it is outside the order's repository and was not started by the account that funded the order or owns its Balance.
Two tokens of one kind count once.

**What only the receipt records.** Whether the judges share a controller. One forge account that can start the run
in the order's repository and the run in the neutral repository satisfies a quorum of 2; the receipt then says
`same_controller: true` and `knos receipt` prints `SAME CONTROLLER.` ([RECEIPT.md](RECEIPT.md)). The chain does not
refuse it. This is the first of the two findings in [SECURITY.md](SECURITY.md); its fix is in the next `knos_pay`
build, which this release does not contain.

**Cost.** A second run by hand (`knos settle --neutral`) and about 120,000 compute units for the judge who is
recorded ([SECURITY.md](SECURITY.md), section 19, measured in the simulator).

**What it proves.** That two runners in two repositories reached the same verdict. Against the larger-runner move
that matters: an organisation's image decides its own run and not a stranger's.

**What stays trusted.** GitHub, for both. And the independence of the parties: the forge signs an account id, not a
person.

**Maturity.** Tested in a simulator on builds made for testing. No quorum has run on the public program ids.

### b. Re-execution by a neutral judge

**What exists.** [`attest.yml`](../.github/workflows/attest.yml) has a `rerun` job with a read-only token and no
signing permission. For an order paid by its acceptance checks it fetches the two commits by their ids, checks that
the acceptance bundle hashes to the `accept` of the funded terms, and runs the suite itself, in the sandbox or in a
container named by digest. The `attest` job asks for the token only when that verdict passed
([SECURITY.md](SECURITY.md), section 20).

**Cost.** One more run of the suite, in the neutral party's minutes.

**What it proves.** That the suite passed on a second machine the buyer does not configure, from inputs named by
hash: a commit id is a hash of its content, and the bundle is checked against the terms. So rung b removes most of
gap (2) for a tests-mode order: the judge no longer believes an API's "success", it believes a hash it recomputed.

**What it does not.** An order paid on its merge is not re-executed: its checks are the repository's own, and the
neutral run still reads their conclusions (`reexecuted: false`). The order itself and the pull request's state are
still read through the API. Both runs are GitHub's runners and the same `knos` release.

**Maturity.** Built; tested against stand-ins for GitHub and the chain. The verdict it writes is not signed by
GitHub: it is the workflow's own account of how it decided.

### c. Build provenance of the judge itself

**What it is.** A signed statement that an artifact (the `knos` wheel, a judge's container image) was built by a
named workflow at a named commit. GitHub's artifact attestations are Sigstore bundles: a short-lived certificate
whose identity GitHub's OIDC issuer sets, over an in-toto statement with a SLSA provenance predicate. Public
repositories use the Sigstore public instance and its transparency log; private ones use GitHub's own instance,
which has no transparency log. Alone they reach SLSA v1 Build Level 2; built through a reusable workflow, Level 3
([GitHub: artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations)).
GitHub's own sentence about them: "artifact attestations are *not* a guarantee that an artifact is secure."

**What a verifier could check off chain.** `gh attestation verify <file> --repo <owner>/<repo>`, with
`--signer-workflow` to require the reusable workflow, before a judge installs or runs anything. For a release:
immutable releases, generally available since 28 October 2025, fix a release's assets and tag and carry a release
attestation that any Sigstore tool can check
([GitHub changelog](https://github.blog/changelog/2025-10-28-immutable-releases-are-now-generally-available/)).

**What a verifier could check on chain.** Less than it seems. A Sigstore bundle is an X.509 chain and an inclusion
proof; the practical form on chain is a digest. An order's terms can already name the judge's image by its sha256
digest (the hermetic judge, [SECURITY.md](SECURITY.md), section 13), and the order already records the workflows'
commit. What provenance would add is a second fact beside that digest, checked by the judge and written in the
verdict: "this digest was built by this workflow at this commit".

**Pinned digests and pinned actions.** Every action in every workflow here is named by a full commit
([`scripts/action_pins.json`](../scripts/action_pins.json)), and every signing job installs by sha256 hash.
GitHub can enforce the first for a whole organisation since 15 August 2025: "any workflow that attempts to use an
action that isn't pinned will fail"
([GitHub changelog](https://github.blog/changelog/2025-08-15-github-actions-policy-now-supports-blocking-and-sha-pinning-actions/)).
Its 2026 security roadmap (26 March 2026) adds workflow dependency locking and a native egress firewall, in preview
within months of that date; when read it said nothing about signing the runner or its image
([GitHub blog](https://github.blog/news-insights/product-news/whats-coming-to-our-github-actions-2026-security-roadmap/)).

**Cost.** One reusable workflow and one verification step. No program change.

**What it proves.** Gap (3): which source the judge's code came from.

**What stays trusted.** GitHub, twice: as the builder and as the issuer of the signing identity. And the machine:
the August 2026 finding is a build whose provenance verified and whose bytes were wrong. Provenance from a
repository a personal account owns stands on the same product boundary as the neutral judge.

**Maturity.** Knos publishes no artifact attestation today and no judge checks one. The parts are generally
available at GitHub.

### d. Proof of what the forge's API returned

This is gap (2) attacked directly: a third party is convinced that a given response came from `api.github.com` over
TLS, without trusting the machine that made the request.

| System | How | Who is trusted | State when read |
|---|---|---|---|
| [TLSNotary](https://tlsnotary.org/docs/faq) | The prover and a verifier run the TLS client together in multi-party computation; neither holds the session key alone | the verifier, or a notary that stands in for it, not to collude with the prover | `v0.1.0-alpha.15`, a pre-release ([releases](https://github.com/tlsnotary/tlsn/releases), 21 May 2026). "TLSNotary currently supports TLS 1.2. Support for TLS 1.3 is on the roadmap." |
| TLSNotary, proxy mode | The verifier forwards the encrypted traffic and the prover then proves in zero knowledge that it matches the session | the verifier's network path to the server ("If you run the verifier yourself, you do not need to trust anybody else"); DNS and routing | announced 22 April 2026, shipped in alpha.15 ([blog](https://tlsnotary.org/blog/2026/04/22/proxy-mode)); TLS 1.2 |
| [Reclaim](https://blog.reclaimprotocol.org/posts/proxying-is-enough) | A proxy (the attestor) sees the encrypted exchange and signs it; the user proves in zero knowledge what the plaintext held | the attestor, to be honest and not to collude with the user; its network path | a deployed product and a paper; "Reclaim attests to a 1200kB response in 7.28s" ([ePrint 2026/2187](https://eprint.iacr.org/2026/2187), 23 September 2026) |
| [zkPass](https://docs.zkpass.org/developer-guides/js-sdk/generate-proof-and-verify-the-result/solana.md) | Three-party TLS with a validator node; the result carries an allocator's and a validator's signature | the allocator's fixed key and the validator it assigned | signatures are secp256k1 over keccak-256; for Solana the documentation gives "the reference code for js verification" only |
| DECO | The three-party handshake that this line of work starts from ([paper](https://arxiv.org/abs/1909.00938), not re-read on this date) | the verifier not to collude with the prover | a paper; we found no public verifier to build against |

Opacity and Primus belong on this list. Their documentation did not return technical detail to our reader on this
date, so nothing is stated about them here.

**Does GitHub's API work with them?** In principle. GitHub disabled TLS 1.0 and 1.1 in February 2018 for "all HTTPS
connections, including web, API, and git connections to https://github.com and https://api.github.com"
([GitHub blog](https://github.blog/news-insights/product-news/crypto-removal-notice/)), so a TLS 1.2 client is
accepted, which is what TLSNotary needs. We did not test which versions and cipher suites `api.github.com`
negotiates today, and we have not produced a TLSNotary or Reclaim proof of a GitHub API response. Two practical
limits are documented by the projects themselves: servers that block data-centre addresses hurt the proxy designs,
and the computation in the multi-party design is bound by bandwidth (for a 1 KB request and a 100 KB response the
prover uploads about 39 MB, [TLSNotary FAQ](https://tlsnotary.org/docs/faq)).

**Does any of it verify on Solana today?** Not the transcript. TLSNotary's own answer: "At the moment the most
practical way to verify data on-chain is to prove the data directly to an off-chain application-specific
verifier." What reaches a chain in the deployed systems is an attestor's signature over a claim. Reclaim documents
a Solana program for that (`8rYXFrtST4ePpMWcEqhazFyRG2DtCUqgtFmKT7FdjRyp`, in a starter that uses devnet,
[Reclaim's Solana page](https://docs.reclaimprotocol.org/onchain/solana/front-end)). A secp256k1 signature is cheap
for a Solana program to check. It is also the same kind of fact Knos has now: a named signer said so. The signer
changes from "GitHub, about a workflow" to "an attestor, about a response".

**Proof sizes and verification cost.** We found no published size for a TLSNotary presentation or a Reclaim proof
in a primary source, and no measured cost of verifying either inside a Solana program. This page gives none.

**Cost for Knos.** A prover beside every judge run, an attestor or notary somebody operates, and a new instruction
that accepts the attestor's signature. For a quorum it would be one more kind of judge.

**What it proves.** That the response the judge acted on came from GitHub's server, as far as the notary or proxy
is honest.

**What stays trusted.** The notary or the proxy; GitHub's record itself (a truthful transcript of a wrong record is
still wrong); the request (a proof of the wrong question's answer proves nothing about the right one).

**Maturity.** Research and early products. Nothing in Knos.

### e. An attested enclave runs the judge

The machine signs for itself: hardware measures what was loaded and signs the measurement with a key the chip
vendor certifies. This is the only rung that answers gap (1) for a judge in an organisation's hands.

| Platform | What is signed | Signature | Root of trust |
|---|---|---|---|
| [AWS Nitro Enclaves](https://docs.aws.amazon.com/enclaves/latest/user/verify-root.html) | a CBOR attestation document: the enclave image's measurements (PCRs), up to 1,024 bytes each of `user_data`, `nonce` and `public_key` | COSE_Sign1 with ECDSA P-384 (ES384, header `{1: -35}`), digest SHA384 | the AWS Nitro Enclaves root certificate, 30 years, through a chain carried in the document |
| Intel TDX | a quote: the measurements of the trust domain and 64 bytes of report data | ECDSA P-256 by the quoting enclave's attestation key ([`tdx-quote`](https://docs.rs/tdx-quote), quote versions 4 and 5) | Intel's provisioning certification key chain |
| AMD SEV-SNP | an attestation report: the guest's launch measurement and report data | by the chip's VCEK; ECDSA P-384 in AMD's specification (not re-read on this date) | AMD Root CA, then AMD SEV CA, then the VCEK ([Edgeless Systems](https://docs.edgeless.systems/contrast/architecture/snp)) |
| [Azure confidential VMs](https://learn.microsoft.com/en-us/azure/confidential-computing/guest-attestation-confidential-virtual-machines-design) | a virtual TPM quote, with a SEV-SNP (1,184 bytes) or TDX (1,024 bytes) hardware report beneath it | the TPM quote by an RSA attestation key Azure certifies | AMD's or Intel's chain, and Azure's CA for the virtual TPM |

**GitHub's position.** We found none. GitHub documents no attested or confidential hosted runner, its 2026 roadmap
does not mention one, and the discussion that reports the larger-runner finding had no staff answer when read. An
attested judge today would be a self-hosted runner inside an enclave, and `knos_pay` refuses self-hosted runners,
rightly: without the attestation a self-hosted runner is the operator's word.

**How the verifier could check an attestation.** `knos_oidc` verifies RS256 by doing the RSA arithmetic itself,
and in this release's build ES256 through Solana's secp256r1 precompile, for a token whose signing input is at
most 780 bytes ([ES256.md](ES256.md)). Against that:

- **Nitro does not fit.** ES384 is a different curve. Solana's precompile is P-256 only, and we found no P-384
  precompile or proposal for one. The document is CBOR in COSE, not a JSON token, and its certificate chain alone
  exceeds one transaction. Doing P-384 inside a program is possible in principle and unmeasured here; on another
  chain a team measured about 12 to 13 million gas for each certificate and under 70 million for the whole
  document after optimisation
  ([Marlin, 11 April 2024](https://blog.marlin.org/on-chain-verification-of-aws-nitro-enclave-attestations)).
- **TDX is the nearest in curve** (P-256), but the hardware report alone is 1,024 bytes in Azure's layout: over
  the 780-byte bound before any certificate, and what must be checked is a chain of signatures rather than one.
- **The Azure path ends in RSA**, which is the arithmetic `knos_oidc` already does, through a vendor's CA rather
  than a published key set.
- **The shape that fits the verifier as built** is indirect: a service checks the hardware evidence off chain and
  issues an ordinary signed token about it (RS256, or ES256 under the size bound), registered as one more issuer.
  That is cheap and it adds the service to the trusted parties. The alternative is to verify the evidence once on
  chain, in pieces, and register the enclave's own key for later tokens; that is the Marlin approach, and it is a
  program of its own.

**Cost.** An enclave image built reproducibly, so that its measurement can be recomputed from source; a place to
run it; a verifier path as above. This is the most work of the five.

**What it proves.** That a specific image produced the verdict, on hardware the vendor vouches for. Combined with
rung d inside the enclave it also covers the answers.

**What stays trusted.** The vendor's root key and its firmware; the cloud that hosts the hardware; the absence of a
side channel or a physical attack that the vendor's threat model excludes; and the image's own code.

**Maturity.** The platforms are generally available. Nothing in Knos uses one.

## The order Knos intends, and why

These are intentions. None of them is a date, and none exists beyond what the sections above say exists.

1. **Finish rung a where it is weakest.** Ship the `knos_pay` build that fixes the two findings, then run a quorum
   on the public program ids with a neutral repository the funder does not control. It costs no new trust and it is
   the one rung whose remaining gap is a known defect rather than a missing technology.
2. **Widen rung b.** Re-execution already replaces "the API said success" with "the suite passed here" for
   tests-mode orders. The intention is to make that the recommended mode for any order above a size the buyer
   chooses, and to have the neutral judge read `runner_group_id` and write it in the verdict, said plainly as the
   API's word and not a signature.
3. **Add rung c for the judge's own code.** Build the release through a reusable workflow, publish its
   attestation, and have the hermetic judge verify it before it runs. Small, no program change, and it makes gap
   (3) checkable by a stranger.
4. **Prototype rung d as a third kind of judge, off chain first.** One proof of one API response (the pull
   request's merge state), kept beside the verdict and checked by `knos receipt`. A program accepts an attestor's
   signature only after the transcript proof has been useful off chain, because on chain it would add a trusted
   signer, and the reason for the whole ladder is to have fewer of those.
5. **Rung e last.** It is the only complete answer to gap (1) and the most expensive, and the forge offers nothing
   to build on. The intention is the indirect shape: an attestation checked off chain, a small token on chain. If
   GitHub puts the runner group or an image measurement into the token, most of this rung becomes a one-line rule
   in `knos_pay`, which is one more reason not to build it first.

What the ladder never removes: a signature authenticates a statement, not the truth
([SECURITY.md](SECURITY.md), "Known limits"). Each rung narrows who could make a false statement and what it would
cost them.
