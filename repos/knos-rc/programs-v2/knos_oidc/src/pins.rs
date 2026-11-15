//! Everything this program trusts, fixed in the binary. No instruction changes any of it. An upgrade could: the
//! program is upgradeable only through a multisig with a public 48-hour delay, until an outside review (after it
//! the upgrade authority is removed). To check the trust root, compare these constants with the issuers' public key
//! sets, reproduce the build, and read the program's upgrade authority on chain.
//!
//! GENESIS: sha256 of the big-endian modulus of each RS256 key in GitHub's JWKS on 2 Oct 2026.
//!   GitHub Actions  https://token.actions.githubusercontent.com/.well-known/jwks
//! GitLab's keys are not here: GitHub's signature admits every key, so GitHub's keys are the root and every other
//! key (a GitLab key, a key GitHub adds later) comes in through the attested path below. Register all four when the
//! program is deployed: a genesis hash nobody has registered can still be registered later, with a full KEY_TTL
//! from that day.
//!
//! The attested path. A run of the pinned rotate workflow (ROTATE_REF at commit ROTATE_SHA, on a GitHub-hosted
//! runner) reads the issuer's JWKS and asks GitHub for a token whose audience names a key's hash. This program
//! accepts that token, verified against a key it already has, only when GitHub also signed that the run happened in
//! one of the attester's own repositories (ATTEST_OWNER_ID, ATTEST_REPO_IDS: the first deployment took the token
//! from any repository that called the workflow) and was started by the schedule or by hand. A key admitted this
//! way waits KEY_DELAY and needs the guardian's approval before it verifies anything.
//!
//! Refresh also takes a run of the same pinned workflow started by hand by anyone in a repository of their own
//! (ANYONE_EVENT): the system does not depend on one account's schedule to stay alive. RegisterKey does not.
//!
//! Every key, genesis or attested, expires KEY_TTL after it was registered or last attested (Refresh): a key the
//! issuer has retired stops being named by the rotate workflow and expires KEY_TTL later.
//!
//! GUARDIAN can approve an attested key and revoke any key, and nothing else: see lib.rs.
use solana_program::{pubkey, pubkey::Pubkey};

pub const ISSUER_GITHUB: u8 = 0;
pub const ISSUER_GITLAB: u8 = 1;
pub const ISSUERS: [&[u8]; 2] = [b"https://token.actions.githubusercontent.com", b"https://gitlab.com"];
/// The issuer number of a key, and of a token it verified, when the issuer is not one of the two above: any RS256
/// issuer admitted by RegisterIssuerKey. Which issuer is said by the hash of its URL, in the key account and in the
/// token account, never by this number alone.
pub const ISSUER_OTHER: u8 = 2;
/// The issuer number of a PRIVATE key and of a token it verified: registered by a wallet with no attestation
/// (RegisterPrivateKey). Nobody vouches for it; the wallet's address is beside the issuer's hash.
pub const ISSUER_PRIVATE: u8 = 3;

const fn h(s: &str) -> [u8; 32] {
    let b = s.as_bytes();
    let mut o = [0u8; 32];
    let mut i = 0;
    while i < 32 {
        let hi = b[2 * i]; let lo = b[2 * i + 1];
        let hi = if hi <= b'9' { hi - b'0' } else { hi - b'a' + 10 };
        let lo = if lo <= b'9' { lo - b'0' } else { lo - b'a' + 10 };
        o[i] = hi << 4 | lo;
        i += 1;
    }
    o
}

pub const GENESIS: &[(u8, [u8; 32])] = &[
    // GitHub Actions (kid, then sha256 of the modulus)
    (0, h("29dfb1c0b82f6c6f770f45a7a78b73a30dfe33980f4a82a6fb4280ccf7417e1a")), // cc413527-173f-5a05-976e-9c52b1d7b431
    (0, h("dc2cea85e2a48ec836bbde7177dff1de2a77fe17faef2276ff0d9460d7a73565")), // 38826b17-6a30-5f9b-b169-8beb8202f723
    (0, h("e0bfde8963254fb2f7871c4d80d968fc25e272687fd72ad90d89b3e51ea240af")), // 38E9B30B3A023A1B72309921A69A42FCC496C42C
    (0, h("478592fecdfacedd7b679f9f428586b22785ec752b6bea6cc1b793ae134975fb")), // 4F3E9AD8C9A6F5EB3173006F4FA630E28F43DCE9
];

/// The rotate workflow: `job_workflow_ref` must start with ROTATE_REF and `job_workflow_sha` must equal ROTATE_SHA.
/// A commit sha fixes the workflow file's content, so its repository's owner cannot change what runs under this pin.
pub const ROTATE_REF: &[u8] = b"drexthealpha/knos-oidc-rotate/.github/workflows/rotate.yml@";
// PIN: the commit of drexthealpha/knos-oidc-rotate that holds rotate.yml (programs-v2/program_ids.json, rotate_sha).
pub const ROTATE_SHA: &[u8; 40] = b"6ddf031b64febecfcd510763ecee37637a8047fa";
/// The later commit of the same workflow, accepted beside ROTATE_SHA: it adds the `issuer` input (any RS256 issuer by its
/// URL, audience knos-oidc:ikey:...) and documents the run by hand in one's own repository. What it attests for
/// GitHub and GitLab is byte for byte what ROTATE_SHA attests.
pub const ROTATE_SHA2: &[u8; 40] = b"212f9eb5f584eb6f8cd2d6673878132fc0011e27";

/// Where the rotate workflow must have run: `repository_owner_id` and `repository_id` as GitHub signs them. The
/// owner is the personal account drexthealpha; the repositories are drexthealpha/Knos and
/// drexthealpha/knos-oidc-rotate. A personal account cannot have larger runners, so `runner_environment` says what
/// it seems to say there; in a paid organisation that called the same workflow it would not.
pub const ATTEST_OWNER_ID: u64 = 142_920_951;
pub const ATTEST_REPO_IDS: [u64; 2] = [1_353_152_983, 1_401_432_540];
/// `event_name` of an attesting run: the schedule, or a run started by hand. Not a push, not a pull request.
pub const ATTEST_EVENTS: [&[u8]; 2] = [b"schedule", b"workflow_dispatch"];
/// Refresh by anyone: `event_name` of a run of the pinned rotate workflow that anyone may use to keep a key alive.
/// The run must be in a repository owned by the person who started it (`repository_owner_id == actor_id`). That is a
/// personal account, which cannot have self-hosted or custom-image runners that carry a hosted label, so
/// `runner_environment` says what it seems to say; an organisation is never an actor, so no organisation passes.
/// The workflow file is fixed by ROTATE_SHA whoever calls it. Such a run only extends the life of a key that is
/// already admitted and not revoked: it registers nothing.
pub const ANYONE_EVENT: &[u8] = b"workflow_dispatch";

/// A key admitted by an attestation verifies nothing for this long: time for anyone to see it on chain and for
/// the guardian to look at it.
pub const KEY_DELAY: i64 = 86_400;
/// A key expires this long after it was last attested (RegisterKey, Refresh).
pub const KEY_TTL: i64 = 30 * 86_400;

/// The guardian: a Squads vault (multisig EwqWNR3XwE9RMsJQdH7pZJSx4WERXCKLQdBpMnr8jFx5, no time lock, so that a
/// revocation is not delayed). Approve and Revoke need its signature.
pub const GUARDIAN: Pubkey = pubkey!("AT1aKj1DpgaWerxmS4YjDkNpWPNUtCCKVDvxLhFxg5Jc");

/// Test builds only (`--features testkeys`): two test moduli, a test rotate pin, the test harness's repository and
/// a test guardian. The keys are derived from a fixed seed in tests/_settle.py (SeedKey); no key file is committed.
/// A testkeys build is never deployed.
#[cfg(feature = "testkeys")]
pub const TEST_GENESIS: &[(u8, [u8; 32])] = &[
    (0, h("f3a805ad569307a02fadcca4b05a85592aef8bb71dc8f49185e8e449ce43c023")), // SeedKey(2048), as a GitHub key
    (1, h("68b22a9b72fd4d5fbe462cdbbfc396c492a694e26c81e770a858192f4501740f")), // SeedKey(4096), as a GitLab key
];
#[cfg(not(feature = "testkeys"))]
pub const TEST_GENESIS: &[(u8, [u8; 32])] = &[];
#[cfg(feature = "testkeys")]
pub const TEST_ROTATE_SHA: Option<&[u8; 40]> = Some(b"1111111111111111111111111111111111111111");
#[cfg(not(feature = "testkeys"))]
pub const TEST_ROTATE_SHA: Option<&[u8; 40]> = None;
/// (repository_owner_id, repository_id) of the test harness's claims (tests/_settle.py, github_claims).
#[cfg(feature = "testkeys")]
pub const TEST_ATTEST: Option<(u64, u64)> = Some((424_242, 987_654_321));
#[cfg(not(feature = "testkeys"))]
pub const TEST_ATTEST: Option<(u64, u64)> = None;
/// The ed25519 public key of the keypair whose seed is [7; 32] (GmaDrppBC7P5ARKV8g3djiwP89vz1jLK23V2GBjuAEGB).
#[cfg(feature = "testkeys")]
pub const TEST_GUARDIAN: Option<Pubkey> = Some(Pubkey::new_from_array([
    0xea, 0x4a, 0x6c, 0x63, 0xe2, 0x9c, 0x52, 0x0a, 0xbe, 0xf5, 0x50, 0x7b, 0x13, 0x2e, 0xc5, 0xf9,
    0x95, 0x47, 0x76, 0xae, 0xbe, 0xbe, 0x7b, 0x92, 0x42, 0x1e, 0xea, 0x69, 0x14, 0x46, 0xd2, 0x2c,
]));
#[cfg(not(feature = "testkeys"))]
pub const TEST_GUARDIAN: Option<Pubkey> = None;

/// Whether GitHub signed that the attesting run happened in one of the attester's repositories.
pub fn attester(owner_id: u64, repo_id: u64) -> bool {
    (owner_id == ATTEST_OWNER_ID && ATTEST_REPO_IDS.contains(&repo_id)) || TEST_ATTEST == Some((owner_id, repo_id))
}
pub fn is_guardian(key: &Pubkey) -> bool { *key == GUARDIAN || TEST_GUARDIAN.as_ref() == Some(key) }
