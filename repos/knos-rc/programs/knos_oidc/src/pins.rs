//! Everything this program trusts, fixed in the binary. There is no admin and no instruction that changes any of it:
//! to check the trust root, compare these constants with the issuers' public key sets and reproduce the build.
//!
//! GENESIS: sha256 of the big-endian modulus of each RS256 key in the issuer's JWKS on 2 Oct 2026.
//!   GitHub Actions  https://token.actions.githubusercontent.com/.well-known/jwks
//!   GitLab CI       https://gitlab.com/oauth/discovery/keys
//! `scripts/oidc_pins.py --check` fetches both and compares.
//!
//! Later keys are added by GitHub's own signature: a run of the pinned rotate workflow (ROTATE_REF at commit
//! ROTATE_SHA, on a GitHub-hosted runner) reads the issuer's JWKS and asks GitHub for a token whose audience names
//! the new key's hash. RegisterKey accepts that token, verified by this program against a key it already has.

pub const ISSUER_GITHUB: u8 = 0;
pub const ISSUER_GITLAB: u8 = 1;
pub const ISSUERS: [&[u8]; 2] = [b"https://token.actions.githubusercontent.com", b"https://gitlab.com"];

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
    // GitLab CI
    (1, h("d16bf70b719150522fea985bf295575eb71ab347281f68d4437fd7152de89e9e")), // kewiQq9j… (4096-bit)
    (1, h("0f631a8ef6f9cedfa3c312b9d792c5c42a995f9d67937d5572c3ea8f592c3910")), // 4i3sFE7s…
    (1, h("d999c9b3e7a6fbd869bd1158686f038bf122f2d031d0a09155311b25f044b58a")), // i3ZOa_TG…
];

/// The rotate workflow: `job_workflow_ref` must start with ROTATE_REF and `job_workflow_sha` must equal ROTATE_SHA.
/// A commit sha fixes the workflow file's content, so nobody (its repository's owner included) can change what runs.
pub const ROTATE_REF: &[u8] = b"drexthealpha/knos-oidc-rotate/.github/workflows/rotate.yml@";
// PIN: the commit of drexthealpha/knos-oidc-rotate that holds rotate.yml (set once, before the verified build).
pub const ROTATE_SHA: &[u8; 40] = b"6ddf031b64febecfcd510763ecee37637a8047fa";

/// Test builds only (`--features testkeys`): two test moduli and a test rotate pin. The keys are derived from a
/// fixed seed in tests/_settle.py (SeedKey); no key file is committed.
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
