//! The reader against a real token account: a GitHub-shaped token that the test build of knos-oidc verified in
//! LiteSVM, saved as it stood (scripts/interface_fixture.py). What must be found in it is in verified_token.json,
//! read here with serde_json, so the crate's own JSON reader is checked against another one. The account every test
//! reads is the second deployment's (the crate's default); a second fixture is the same token from the same payer,
//! verified by the test build of the first deployment and read by naming it.
use knos_oidc_interface::{fields, v1, v2, verified, Error, Token, ID, ID_STR, ISSUERS, ISSUER_GITHUB, LATE, T_JWT, T_KEY, T_PAYER, T_PLEN, T_POFF, T_STAGE, VERIFIED};
use serde_json::Value;

const ACCOUNT: &[u8] = include_bytes!("fixtures/verified_token_v2.bin");
const ACCOUNT_V1: &[u8] = include_bytes!("fixtures/verified_token.bin");

fn want() -> Value { serde_json::from_str(include_str!("fixtures/verified_token_v2.json")).unwrap() }
fn now() -> i64 { want()["now"].as_i64().unwrap() }

#[test]
fn the_fixture_reads_as_verified_with_the_expected_issuer_expiry_and_claims() {
    let w = want();
    assert_eq!(w["owner"], ID_STR);
    let tok = Token::read(&ID, ACCOUNT, now()).unwrap();
    assert_eq!(tok.issuer(), ISSUER_GITHUB);
    assert_eq!(tok.issuer() as i64, w["issuer"].as_i64().unwrap());
    assert_eq!(tok.exp(), w["exp"].as_i64().unwrap());
    assert_eq!(serde_json::from_slice::<Value>(tok.payload()).unwrap(), w["claims"]);
    let claims = w["claims"].as_object().unwrap();
    assert!(claims.len() > 25);
    for (name, value) in claims {
        match value {
            Value::String(s) => {
                let t = tok.claim(name).unwrap();
                assert!(t.is(s) && t.len() == s.len() && t.as_plain() == Some(s.as_bytes()), "{name}");
                // GitHub sends ids as strings of digits: they read as numbers too
                assert_eq!(tok.claim_u64(name), s.parse::<u64>().ok().filter(|n| n.to_string() == *s), "{name}");
            }
            Value::Number(n) => {
                assert_eq!(tok.claim_u64(name), n.as_u64(), "{name}");
                assert!(tok.claim(name).is_none(), "{name} is not a string");
            }
            other => panic!("{name}: {other}"),
        }
    }
    assert!(tok.audience().unwrap().is("oidc-gate:release"));
    assert!(tok.claim("iss").unwrap().is(ISSUERS[ISSUER_GITHUB as usize]));
    assert_eq!(tok.claim_u64("repository_id"), Some(424242001));
    assert_eq!(tok.claim_u64("exp"), Some(tok.exp() as u64));
    assert!(tok.claim("job_workflow_ref").unwrap().starts_with("octo/widgets/.github/workflows/release.yml@"));
    // several claims in one pass
    let [repo, sha, runner] = tok.claims([b"repository_id", b"sha", b"runner_environment"]).unwrap();
    assert_eq!(knos_oidc_interface::number(repo), Ok(424242001));
    assert!(knos_oidc_interface::text(sha).unwrap().is([b'5'; 40]) && knos_oidc_interface::text(runner).unwrap().is("github-hosted"));
}

#[test]
fn a_claim_that_is_absent_returns_none() {
    let tok = Token::read(&ID, ACCOUNT, now()).unwrap();
    assert!(tok.claim("environment").is_none() && tok.claim_u64("environment").is_none());
    assert!(tok.claim("").is_none() && tok.claim("repository_i").is_none() && tok.claim("Sha").is_none());
    assert!(tok.claims([b"environment"]).unwrap()[0].is_none());
}

#[test]
fn an_unverified_stage_reads_as_an_error() {
    for stage in [0u8, 1, 3, 255] {
        let mut d = ACCOUNT.to_vec();
        d[T_STAGE] = stage;
        assert_eq!(Token::read(&ID, &d, now()).unwrap_err(), Error::NotVerified, "stage {stage}");
        assert!(verified(&d).is_none());
    }
    assert_eq!(ACCOUNT[T_STAGE], VERIFIED);
}

#[test]
fn a_wrong_owner_is_refused() {
    // the same bytes in an account some other program owns: anyone can make one
    let mut other = ID;
    other[31] ^= 1;
    assert_eq!(Token::read(&other, ACCOUNT, now()).unwrap_err(), Error::NotOidc);
    assert_eq!(Token::read(&[0; 32], ACCOUNT, now()).unwrap_err(), Error::NotOidc);
}

#[test]
fn a_stale_token_is_refused() {
    let exp = want()["exp"].as_i64().unwrap();
    assert!(Token::read(&ID, ACCOUNT, exp).is_ok());
    assert!(Token::read(&ID, ACCOUNT, exp + LATE - 1).is_ok());
    assert_eq!(Token::read(&ID, ACCOUNT, exp + LATE).unwrap_err(), Error::Stale);
    assert_eq!(Token::read(&ID, ACCOUNT, i64::MAX).unwrap_err(), Error::Stale);
}

#[test]
fn truncated_data_is_refused() {
    let v = verified(ACCOUNT).unwrap();
    let end = u16::from_le_bytes([ACCOUNT[T_POFF], ACCOUNT[T_POFF + 1]]) as usize + u16::from_le_bytes([ACCOUNT[T_PLEN], ACCOUNT[T_PLEN + 1]]) as usize;
    assert!(end > T_JWT && end <= ACCOUNT.len());
    // every length that cuts into the header or the payload
    for n in 0..end {
        assert_eq!(Token::read(&ID, &ACCOUNT[..n], now()).unwrap_err(), Error::NotVerified, "{n} bytes");
    }
    assert!(Token::read(&ID, &ACCOUNT[..end], now()).is_ok());
    // a payload cut short on its own is not a JSON object
    assert_eq!(fields(&v.payload[..v.payload.len() - 1], [b"aud"]).unwrap_err(), Error::Json);
}

#[test]
fn the_first_deployment_wrote_the_same_account_for_the_same_token_and_is_read_only_by_name() {
    let w: Value = serde_json::from_str(include_str!("fixtures/verified_token.json")).unwrap();
    assert_eq!(w["owner"], v1::ID_STR);
    assert_eq!(want()["owner"], v2::ID_STR);
    let (second, first) = (Token::read(&ID, ACCOUNT, now()).unwrap(), v1::read(&v1::ID, ACCOUNT_V1, now()).unwrap());
    assert_eq!((second.issuer(), second.exp(), second.payload()), (first.issuer(), first.exp(), first.payload()));
    assert_eq!(serde_json::from_slice::<Value>(first.payload()).unwrap(), w["claims"]);
    assert_eq!(w["claims"], want()["claims"]);
    assert!(first.audience().unwrap().is("oidc-gate:release") && first.claim_u64("repository_id") == Some(424242001));
    // every byte is the same but the address of the key account, which is derived from the program's address
    assert_eq!(ACCOUNT_V1.len(), ACCOUNT.len());
    assert_eq!(ACCOUNT_V1[..T_KEY], ACCOUNT[..T_KEY]);
    assert_eq!(ACCOUNT_V1[T_PAYER..], ACCOUNT[T_PAYER..]);
    assert_ne!(ACCOUNT_V1[T_KEY..T_PAYER], ACCOUNT[T_KEY..T_PAYER]);
    assert_eq!(second.key(), &ACCOUNT[T_KEY..T_PAYER]);
    // no default takes the first deployment's account, whatever its bytes say, and `v1` takes no other
    assert_eq!(Token::read(&v1::ID, ACCOUNT_V1, now()).unwrap_err(), Error::NotOidc);
    assert_eq!(Token::read_any(&v1::ID, ACCOUNT_V1, now()).unwrap_err(), Error::NotOidc);
    assert_eq!(v2::read(&v1::ID, ACCOUNT_V1, now()).unwrap_err(), Error::NotOidc);
    assert_eq!(v1::read(&ID, ACCOUNT, now()).unwrap_err(), Error::NotOidc);
    assert_eq!(v1::read(&v1::ID, ACCOUNT_V1, w["exp"].as_i64().unwrap() + LATE).unwrap_err(), Error::Stale);
    // a GitHub token of either deployment is nobody's private word
    assert!(!second.is_private() && second.registrant().is_none() && second.issuer_hash().is_none() && !first.is_private());
}
