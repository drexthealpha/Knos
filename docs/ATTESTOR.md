# What the signature proves, and what it does not

A payment in Knos rests on a token a forge signed. This page says exactly what that signature covers, what it leaves
to a machine nobody signed for, and the five ways of narrowing that gap: what each costs, what it proves, what stays
trusted, and how mature it is today. Two of the five exist in this repository. Three do not, and the last section
says in which order Knos intends to take them. For the fifth there is one experiment outside the product: a judge
for one small task whose run was proved and the proof verified, with the time, memory and size measured here.
Outside pages were read on 2026-10-06 unless a line says otherwise (the proved run and its sources: 2026-10-07);
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

## Under every rung: what the workflow's shape enforces

The ladder is about who could make a false statement. Below it is a floor that needs no new trust, only the shape of
the workflow files, and it is held by tests ([SECURITY.md](SECURITY.md), "Where untrusted code runs"):

- **Enforced by shape.** A pull request's code runs only in a job with a token that reads, no secret and no
  `id-token`: it cannot ask the forge to sign anything. The job that signs has no checkout, no git and no artifact:
  it installs `knos` by the hash of every file and runs none of that code. What crosses between them is one line of
  fixed fields with no free text, which the signing job reads strictly, holds to its own run, pull request, issue
  and two commits, and checks again against the forge's record (the head commit, the acceptance bundle's hash, the
  judge's rule on every changed path) before the command that can sign starts. Every action is named by a full
  commit.
- **Not enforced by shape.**
  - *A compromised runner image.* The label `ubuntu-24.04` is not a digest and the token does not name the image
    (the example above). The verdict records the image's version as the machine reports it; nothing signs it.
  - *The forge itself.* It runs both jobs, carries the output between them, answers the API the second job checks
    against, and signs. A forge that lies is outside every rung but d and e.
  - *The judge's own code being wrong.* The signing job proves which `knos` it installed, not that `classify_path`
    or the sandbox is right. That is what the tamper corpus ([TAMPER.md](TAMPER.md)) and a second, different
    judge are for.
  - *That the suite passed.* One bit, for one pull request at one commit against one bundle, is still the word of
    the machine that ran the code. Rungs a and b are how a second machine says it too.

**Escape and substitution tests a reviewer should run.** Each is independent of Knos's own tests; a reviewer should
write the hostile input rather than reuse ours.

1. *Out of the sandbox.* In a fork, open a pull request whose code, under the acceptance suite, tries: a TCP
   connection by address, a DNS lookup, reading `/proc/1/environ` and `$GITHUB_*`, `sudo -n true`, writing outside
   its tree, and reading the runner's work folder. Expect every one to fail and the judge job's log to hold no token.
2. *From the judge to the signer.* With a copy of the workflows in a staging repository, replace the judge's last
   step with one that prints a verdict for another pull request, another head commit, another issue, another run id;
   then one with a key twice, one of 1 MB, one whose `image` is a shell command. Expect the signing job to end at
   the step before `knos settle`, and no token comment.
3. *Past the rule.* A pull request that edits an existing test, one that renames it away, one that adds a workflow
   file, each with a judge patched to say "passed". Expect the signing job to refuse by the path's code.
4. *A stale verdict.* Push a commit to the pull request between the judge and the signer (hold the signer with the
   `knos-settle` line). Expect "no longer the one that was judged".
5. *Across runs.* Start two runs for two pull requests at once and confirm neither signer accepts the other's
   verdict; run a failed `rerun` job of `attest.yml` again and confirm the second attempt's artifact has its own
   name.
6. *The shape itself.* Read each published file at the commit an order records and confirm by eye what
   `tests/test_workflows2.py` asserts: no job has both `id-token: write` and a checkout, a fetch or a download.

## Where the pull request's code runs: a container first, the host sandbox second

`knos proof judge --sandbox hermetic` (src/knos/judge.py `judge`, `default_image`) runs a black-box check whose terms
name no image in `DEFAULT_IMAGE` (Python 3.12 on Alpine, pinned by digest) when the machine runs containers: no
network, a read-only root, the tree read-only, another user, no capabilities, memory, CPU, process and time limits
(`container_argv`). Terms that name an image always run in that image, or not at all. Everywhere else the host
sandbox judges, the verdict's `judged_in` says `host sandbox (fallback: <why>)`, and its `assurance` stays
`black-box`, never `hermetic`. The fallbacks: a machine that is not Linux, an in-process runner (pytest, node:test, go
test, cargo test, minitest load the pull request's code into the runner, so only a black-box check can put it in a
container), a tree with another language's manifest (package.json, go.mod, Cargo.toml, ...: the default image holds
Python only), and no runtime that answers.

The host sandbox (`Box.wrap`), on Linux with `setpriv`, `unshare`, `prlimit` and root or passwordless sudo:

| What the submission tries | What stops it |
|---|---|
| a fork bomb | RLIMIT_NPROC 256 for the sandbox user (uid 65534): `fork` fails with "Resource temporarily unavailable" |
| leaving processes behind | a PID namespace: when the run ends or its time limit kills it, every process it started is killed |
| writing outside its folder (/tmp, /var/tmp, any folder any user may write) | a mount namespace in which every mount but the box's own folder is read-only; /dev/shm is an empty tmpfs of its own. The run is refused (exit 125) if / or /tmp is still writable |
| burning CPU | RLIMIT_CPU 600 seconds per process, then SIGKILL |
| filling memory | RLIMIT_DATA 4 GiB per process (heap and private writable mappings; a container's limit is per container) |
| filling the disk | RLIMIT_FSIZE 1 GiB per file, then "File too large" |
| calling out | a network namespace with only a loopback (the dependency install alone has the network) |
| reading the judge's secrets | another user, an empty environment |

tests/test_judge_box.py runs a fork bomb, an outside write, a file past the size limit, a CPU loop and a run past
its time limit, and checks each is stopped and nothing outlives the run; the escape table in [TAMPER.md](TAMPER.md)
measures the same places.

What other runners can enforce. GitHub runs container jobs and service containers on Linux runners only
([Use Docker service containers](https://docs.github.com/en/actions/tutorials/use-containerized-services/use-docker-service-containers)),
so on macOS and Windows the judge is never hermetic. On **macOS** without the sandbox the command gets the CPU and file
size limits (`setrlimit`, which POSIX defines) and a session that is killed whole on the time limit; there is no
mount or network namespace, so it can write wherever the judge's user can and can call out, and a process count limit
is not set because RLIMIT_NPROC there counts every process of the judge's own user. On **Windows** the judge sets
none of these: a job object could limit processes, memory and CPU, and Knos does not create one yet; writes are
bounded only by the account's file permissions. `--sandbox require`, and `hermetic`, which falls back to it, refuse
to judge on either.

## The ladder

| Rung | Closes | Still trusted | Today |
|---|---|---|---|
| a. Quorum of judges in repositories different parties control | one runner, one maintainer | the forge; that the parties are different people | built and tested in a simulator; never run on the public program ids. In each judge, the job that runs the code cannot sign (shape, above) |
| b. Re-execution by a neutral judge from pinned inputs | a check result that lies | the forge's hosted runner for a personal account; the suite itself; that the re-execution's one bit is true | built; one public payment was judged again this way, by Knos's own account, so its receipt reads `reported` ([RECEIPT.md](RECEIPT.md)). No outside account has hosted the judge. Its verdict is read strictly and held to the order by the job that signs (shape, above) |
| c. Build provenance of the judge | what code the judge installed | the forge as builder and signer; the machine (see the example above) | not built here; the parts exist at GitHub and Sigstore |
| d. Proof of what the forge's API returned | the answers | a notary or a proxy, or the proof system | not built; no system we found checks a transcript on Solana |
| e. Proof of what the judge executed: an attested enclave, or a proved run | the machine | enclave: the chip vendor's root key, side channels, the cloud. Proved run: the proof system and its setup; that the checks are the right ones | not built in the product; GitHub offers no attested runner. One experiment: a judge for one task, proved and verified off chain (below) |

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

**Maturity.** Built; tested against stand-ins for GitHub and the chain, and run once for a public payment from
Knos's own account ([RECEIPT.md](RECEIPT.md), "Version 5"). The verdict it writes is not signed by GitHub: it is the
workflow's own account of how it decided.

**Who hosts it.** A receipt's level is computed from account ids (`knos.receipt.assurance_of`). It reads `rerun`
only when the judge that ran the suite is owned and started by an account that is not a payee, and `agreed` only
when two such judges have different owners. One account that funds, delivers and evaluates reads `reported`
however often it runs the suite: that is every receipt so far. So the judge has to be hosted by someone else, and
[`examples/host_a_judge`](../examples/host_a_judge/README.md) makes that one link and one button:

- **The host** makes a repository from the template (one file, [`examples/knos-attest.yml`](../examples/knos-attest.yml);
  no secret, wallet or key) and presses Run workflow after the merge. `python -m knos.host_judge link` prints the link.
- **The buyer** names it: `/knos fund 20 checks: unit quorum 2 judge: <host>/knos-judge`. An order funded without
  `judge:` and without `neutral off` takes the host's run as its neutral run.
- **What the host is paid.** Nothing by the order: the program has no judge's share. The relayer's tip (0.05 test
  USDC out of the fee; 0.30 when the paying transaction creates a payee's token account: `TIP` and `TIP_FIRST` in
  [`knos_pay/src/lib.rs`](../programs-v2/knos_pay/src/lib.rs)) goes to whoever paid for the paying transaction,
  which is the host only if the host also runs a relay.
- **What the host can do.** Run or not run. A quorum that names a host who never runs is refunded at its deadline.
- **What the host cannot do.** Get signed what GitHub's public record does not support (the run is the pinned
  workflow at the commit the order recorded), change the payees or the terms, touch the money, raise the level for
  work the host is paid for, or count twice with two repositories.
- **What does not raise the level.** The order's own repository (the buyer chose it), and an order paid on the
  merge (there is no suite to run, and the host's run reads GitHub's record).

`python -m knos.host_judge level --payee ID --host ID [--host ID]` says the level a set of accounts would give.
`tests/test_host_a_judge.py` runs the host's two jobs in the simulator for two owners and checks `rerun` and `agreed`
on receipts. No outside account has done it: outside hosts today, 0.

**Enforced by shape, and not.** The `rerun` job cannot sign and the `attest` job runs none of the code; the verdict
between them is held to one reading (small, plain characters, each key once, only a verdict's fields) before
`knos attest` holds it to the order, the pull request, the two commits and the bundle. Not enforced: that `rerun`'s
"passed" is true. A pull request that escaped the sandbox there could write it; it could not make it name another
order, and the same escape would have to work in every judge of a quorum.

### c. Build provenance of the judge itself

**What it is.** A signed statement that an artifact (the `knos` wheel, a judge's container image) was built by a
named workflow at a named commit. GitHub's artifact attestations are Sigstore bundles: a short-lived certificate
whose identity GitHub's OIDC issuer sets, over an in-toto statement with a SLSA provenance predicate. Public
repositories use the Sigstore public instance and its transparency log; private ones use GitHub's own instance,
which has no transparency log. Alone they reach SLSA v1 Build Level 2; built through a reusable workflow, Level 3
([GitHub: artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations)).
GitHub's own sentence about them: "artifact attestations are *not* a guarantee that an artifact is secure."
Read again on 2026-10-07: an attestation carries the workflow, the repository, the commit, the event that started
the run and the token's claims. It is the cheapest step on this page, and it says which workflow emitted a file,
never what that workflow computed.

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

### e. Proof of what the judge executed

Two routes answer gap (1) for a judge in an organisation's hands. In the first the machine signs for itself. In the
second no machine is believed: the run carries a proof that anyone checks.

#### An attested enclave runs the judge

Hardware measures what was loaded and signs the measurement with a key the chip vendor certifies.

| Platform | What is signed | Signature | Root of trust |
|---|---|---|---|
| [AWS Nitro Enclaves](https://docs.aws.amazon.com/enclaves/latest/user/verify-root.html) | a CBOR attestation document: the enclave image's measurements (PCRs), up to 1,024 bytes each of `user_data`, `nonce` and `public_key` | COSE_Sign1 with ECDSA P-384 (ES384, header `{1: -35}`), digest SHA384 | the AWS Nitro Enclaves root certificate, 30 years, through a chain carried in the document |
| Intel TDX | a quote: the measurements of the trust domain and 64 bytes of report data | ECDSA P-256 by the quoting enclave's attestation key ([`tdx-quote`](https://docs.rs/tdx-quote), quote versions 4 and 5) | Intel's provisioning certification key chain |
| AMD SEV-SNP | an attestation report: the guest's launch measurement and report data | by the chip's VCEK; ECDSA P-384 in AMD's specification (not re-read on this date) | AMD Root CA, then AMD SEV CA, then the VCEK ([Edgeless Systems](https://docs.edgeless.systems/contrast/architecture/snp)) |
| [Azure confidential VMs](https://learn.microsoft.com/en-us/azure/confidential-computing/guest-attestation-confidential-virtual-machines-design) | a virtual TPM quote, with a SEV-SNP (1,184 bytes) or TDX (1,024 bytes) hardware report beneath it | the TPM quote by an RSA attestation key Azure certifies | AMD's or Intel's chain, and Azure's CA for the virtual TPM |

**GitHub's position.** We found none. GitHub documents no attested or confidential hosted runner, its 2026 roadmap
does not mention one, and the discussion that reports the larger-runner finding had no staff answer when read.
Read again on 2026-10-07: the page that lists the hosted runners names no enclave, no confidential machine and no
attestation of the runner; the standard Linux runner for a public repository has 4 CPUs and 16 GB of memory
([GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)). An
attested judge today would be a self-hosted runner inside an enclave, and `knos_pay` refuses self-hosted runners,
rightly: without the attestation a self-hosted runner is the operator's word.

**How the verifier could check an attestation.** `knos_oidc` verifies RS256 by doing the RSA arithmetic itself,
and in this release's build ES256 through Solana's secp256r1 precompile, for a token whose signing input is at
most 780 bytes ([ES256.md](ES256.md)). Against that:

- **Nitro does not fit.** ES384 is a different curve. Solana's precompile is P-256 only, and we found no P-384
  precompile or proposal for one (the three precompiles are Ed25519, secp256k1 and secp256r1:
  [Solana: precompiled programs](https://solana.com/docs/core/programs/precompiles), read 2026-10-07). The document is CBOR in COSE, not a JSON token, and its certificate chain alone
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

#### A proved run of the judge

A zero-knowledge virtual machine runs a program compiled for RISC-V and produces a proof that this program, on some
input, wrote this output. The program is named by a hash (the image id); the output (the journal) is public; the
verifier needs neither the machine nor its operator. For a judge that is a fixed program this is gap (1) closed
with no signer added.

**The two systems with a verifier written for Solana**, as their own pages stood on 2026-10-07:

| | RISC Zero | SP1 |
|---|---|---|
| Newest release on crates.io | `risc0-zkvm` 3.0.6 | `sp1-sdk` 6.8.1 |
| The proof a chain can check | Groth16 over BN254: 256 bytes (64 + 128 + 64) and five public inputs, from the image id and the SHA-256 of the journal ([verifier source](https://github.com/boundless-xyz/risc0-solana/blob/832954160f12a5b292a33a7aa4f1afb649a1df23/solana-verifier/programs/groth_16_verifier/src/lib.rs)) | Groth16, "~260 bytes" ([proof types](https://docs.succinct.xyz/docs/sp1/generating-proofs/proof-types)) |
| Verifier for Solana | [`boundless-xyz/risc0-solana`](https://github.com/boundless-xyz/risc0-solana): a Groth16 verifier and a router, built against `risc0-zkvm` 3.0.3; Apache-2.0; audited ([report of 20 March 2025](https://reports.zksecurity.xyz/reports/risc0-solana-contracts)); last commit on `main` 2025-10-23 | [`succinctlabs/sp1-solana`](https://github.com/succinctlabs/sp1-solana) 0.1.0; MIT; "This repository is not audited for production use."; last commit on `main` 2025-08-14; it carries verification keys up to SP1 5.0.0 and none for 6 |
| Compute units to verify on Solana | none published that we found; RISC Zero's [list of verifier deployments](https://dev.risczero.com/api/blockchain-integration/contracts/verifier) names no Solana address | "around 280K compute units", above the default limit of 200K |
| Proving on a CPU, as documented | "less than 10 GB" of memory may need a smaller segment; the Groth16 step "only works on x86" ([local proving](https://dev.risczero.com/api/generating-proofs/local-proving)) | "16+" cores and "16GB+" of memory; Groth16 "16GB+" ([hardware requirements](https://docs.succinct.xyz/docs/sp1/getting-started/hardware-requirements)) |
| Stated security | 96 bits for the RISC-V prover, 99 for recursion; the Groth16 step rests on a trusted setup ceremony ([security model](https://dev.risczero.com/api/security-model)) | Groth16 rests on a trusted setup ceremony (the same page as the proof types) |

Both verifiers sit on Solana's `alt_bn128` syscalls. The library under `sp1-solana` gives its own figure for the
pairing check alone: "A plain Groth16 verify costs 78,293–108,762 CU", for one to eight public inputs
([`groth16-solana`](https://github.com/Lightprotocol/groth16-solana), Apache-2.0). Neither verifier repository
changed in the 30 days before this was read, so Knos opens nothing on either and recommends neither as maintained:
building on one means carrying its verifier here.

**What exists here.** [`experiments/judge_proof`](../experiments/judge_proof/README.md), outside the package and
outside every wheel. Its guest program is a judge for one task of the playground's kind (`count_words`): seven
fixed cases, each an input and the output a correct function returns. The input is the submission: the outputs a
supplier's function gave, one line a case. The guest hashes the submission, compares it with the cases byte for
byte, and commits 70 bytes: a version, the SHA-256 of the submission, the SHA-256 of the checks, the verdict, and
how many cases passed of how many. The same rule in plain Python ([`reference.py`](../experiments/judge_proof/reference.py))
gives the same 70 bytes, and a test holds the two together.

**Measured on 2026-10-07** ([`results.json`](../experiments/judge_proof/results.json)): RISC Zero 3.0.6, its
`r0vm` prover, 2 CPUs of a shared virtual machine with 8 GB of memory, no GPU. The machine was busy with other
work, so the wall-clock seconds are an upper figure and the CPU seconds the steadier one. The run is 6,941 cycles
of the judge in one segment of 32,768. Image id
`e95d5440dce55f43c566b0ee20f8fc08b2fd6c1cf7f5d1722c31ea54b4325617`.

| Run | Receipt | Prove, wall clock | Prove, CPU | Prover's peak memory | Receipt size | Verify |
|---|---|---|---|---|---|---|
| honest submission, verdict passed | composite (one STARK) | 54 s | 42 s | 0.32 GB | 209,702 bytes | 0.03 s |
| honest submission, verdict passed | succinct (constant size) | 217 s | 163 s | 1.46 GB | 223,366 bytes | 0.04 s |
| one wrong output, verdict failed | succinct | 138 s | 161 s | 1.46 GB | 223,366 bytes | 0.03 s |

Each receipt was verified by a second process that holds only the receipt and the image id. The same receipt
against another image id is refused ("claim digest does not match the expected digest"). The whole toolchain took
about 1.2 GB of disk: the prover binary from the project's release (Apache-2.0), the two crates' builds, and the
guest compiled by an ordinary nightly Rust, whose target `riscv32im-risc0-zkvm-elf` is upstream. Building both from nothing took 21
minutes on this machine. A standard hosted runner has more of everything this run used; it was not run on one.

**Not measured, and why.** The 256-byte Groth16 form, which is the only one the Solana verifiers take: the step
that makes it is a further download and a further prover that this machine could not fetch (the project's installer
does not accept the certificate of the proxy this machine reaches the network through), and its memory is not
stated in the page we read. So this page gives no time for it and no compute units. No on-chain verifier is
deployed, on any cluster, by this release.

**What a verified receipt proves.** These checks (by hash, and by the image id that names the program holding
them), over this submission (by hash), gave this verdict. Nothing about who ran it or where.

**What it does not prove.**

- *That the checks are the right ones.* Seven cases stand for a task; a table can be met by a function that is
  wrong everywhere else. That is the buyer's terms, as it is at every rung.
- *That the submitted function produced the outputs.* The guest reads outputs. Running the supplier's code inside
  the proof needs that code compiled into the guest, or an interpreter for it there; neither exists here.
- *Anything about a repository's own test suite.* A suite that needs an interpreter, a package index, a clock, a
  file system or the network is not this program. The cost above is for seven thousand cycles; a Python
  interpreter's start is not measured here and is not small.
- *That the submission is the pull request.* Tying the hash in the journal to a commit is the forge's word or one
  more statement inside the proof.
- *That the proof system is sound.* The verifier trusts the circuits, and for the on-chain form a trusted setup.

**The order of work to an on-chain `attested` level.** No receipt of Knos's says `attested` today, and no judge of
Knos's is attested: the level stays out of the product until a verifier is live on the public program ids.

1. Make the Groth16 receipt of this same run on an x86 machine with the memory it needs, and measure it.
2. Verify it in the simulator the handler tests use, with the Groth16 verifier's code vendored at a pinned commit,
   and measure the compute units. One transaction is the bound: 256 bytes of proof and 70 of journal fit.
3. Name the judge in the terms: the image id and the checks' hash go into the hash a funding commits to, so a
   proof for other checks pays nothing.
4. A program change, proposed and time-locked like any other: an instruction that takes the proof and the journal,
   recomputes the journal's hash, asks the verifier, and records a judge of a new kind for a quorum. This release
   changes no program.
5. Run the supplier's function inside the guest for one language with a small interpreter, and measure again.
   Until then the level could only say "these outputs met these checks".
6. Only then the word: a receipt's assurance line reads `attested` when, and only when, that instruction accepted
   a proof on the public program ids.

**What stays trusted.** The proof system and its setup; the verifier's code on chain; the checks.

**Maturity.** One experiment, off chain, on one machine. Nothing in the product reads a proof.

## Assurance levels on every accepted line

`src/knos/assurance.py` gives each receipt and each statement line one of four levels, lowest first, computed from its
evidence and never typed (`knos assurance FILE` prints them):

| Level | What it means | Reached today |
|---|---|---|
| workflow-reported | the forge signed which workflow ran; that run reported the result | yes: every signed receipt |
| re-executed | an evaluator outside the supplier's control ran the pinned inputs again (rung b; receipt levels `rerun` and `agreed`) | yes, when rung b ran |
| independently attested | a party other than buyer and supplier signed the result | no: no such party exists today, and no line may say it |
| proved | a proof of the property itself, checked on chain | only the forge's signature of the workflow identity, which knos_oidc checks in the paying transaction; an acceptance result is never proved |

A line's level is therefore at most re-executed. Whether the chain checked the signature is said beside it
(`identity_proved`), not as a level of the result. A shadow statement's lines (GitHub's answers, which GitHub does
not sign) reach no level until a receipt is recorded for them.

## Four words a statement keeps apart

- **Agreement**: both sides reconstruct the same lines from the recorded events. Two ledgers can agree and both miss
  the same event.
- **Completeness**: the record has no gap. A log of events (`knos events`) checks sequence numbers per stream, signed
  corrections and the parties' acknowledgements of a month's last line; a shadow statement or a closed month carries
  no sequence and says "not checked".
- **Correctness**: the acceptance decision matches the terms hashed at funding; the level of each accepted line says
  how it was checked.
- **Commercial satisfaction**: whether the buyer got what it wanted. Knos never claims it, at any level.

## The workflow-strip hole

A buyer who controls the repository can remove or edit the Knos workflow in the very pull request it merges, so the
check never runs and nothing is signed. `knos protect --check-strip OWNER/REPO` (`src/knos/strip_check.py`) reads
GitHub's rules for the default branch (GET /repos/{owner}/{repo}/rules/branches/{branch}, rule shapes in
[GitHub's REST reference](https://docs.github.com/en/rest/repos/rules), read 2026-10-09) and says one of three things.

- **closed**: a ruleset (a set of GitHub rules for a branch) requires the Knos workflow. The workflow then runs from
  the file the rule pins, not the pull request's copy. Closed never holds against those who can edit or bypass the
  ruleset: organisation owners for an organisation ruleset, repository admins for a repository one.
- **partly**: a required check names a Knos check. The merge waits for that check, so removing the workflow alone
  blocks the merge. Still open: a pull request can change the workflow that runs that check, and an admin can remove
  the requirement.
- **open**: neither. Nothing on GitHub stops the buyer removing the workflow.

**On a personal repository, PARTLY is the most GitHub allows.** Only an organisation or enterprise ruleset on GitHub
Enterprise Cloud can require a workflow ([GitHub's list of rules, Enterprise Cloud edition](https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-workflows-to-pass-before-merging),
read 2026-10-10; the [Free, Pro and Team edition](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
has no such rule). On a personal repository GitHub refuses the rule with HTTP 422 "Invalid rule 'workflows'". That
happened on `drexthealpha/knos-witness` on 10 October 2026: its ruleset now requires the check `check / claims`, and
`knos protect --check-strip drexthealpha/knos-witness` reads PARTLY there.

A required check has a side effect. GitHub wants it to pass before any change reaches the branch
([GitHub](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-status-checks-to-pass-before-merging)),
so a direct push to that branch is refused too. To push straight to it, add yourself to the ruleset's bypass list.

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
   to build on. For a judge that is a fixed, small program the intention is the proved run, in the order the
   section above gives, because it adds no signer. For a judge that runs a repository's own suite the intention is
   the indirect shape of the enclave: an attestation checked off chain, a small token on chain. If GitHub puts the
   runner group or an image measurement into the token, most of the enclave route becomes a one-line rule in
   `knos_pay`, which is one more reason not to build it first.

What the ladder never removes: a signature authenticates a statement, not the truth
([SECURITY.md](SECURITY.md), "Known limits"). Each rung narrows who could make a false statement and what it would
cost them.
