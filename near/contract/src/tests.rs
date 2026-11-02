//! Unit tests. A 2048-bit RSA key is made once per run (no key is kept in the repository) and signs GitHub-shaped
//! OIDC tokens; the contract verifies them with its own RSA code. "adversarial" marks the attacks of N2 and N3.

use super::*;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use near_sdk::test_utils::{accounts, VMContextBuilder};
use near_sdk::testing_env;
use ::rsa::pkcs1v15::SigningKey;
use ::rsa::signature::{SignatureEncoding, Signer};
use ::rsa::traits::PublicKeyParts;
use ::rsa::RsaPrivateKey;
use sha2::Sha256;
use std::sync::OnceLock;

const CONTRACT: &str = "knos.testnet";
const USDC: &str = "usdc.testnet";
const REPO: &str = "drexthealpha/knos-demo";
const WF: &str = "drexthealpha/knos-demo/.github/workflows/proof.yml@refs/heads/main";
const HASH: &str = "ea54c35ca50d76df0000000000000000000000000000000000000000000000ab";
const SEC: u64 = 1_000_000_000;
const NOW: u64 = 1_793_500_000; // seconds

fn keys() -> &'static (RsaPrivateKey, RsaPrivateKey) {
    static K: OnceLock<(RsaPrivateKey, RsaPrivateKey)> = OnceLock::new();
    K.get_or_init(|| {
        let mut rng = rand::thread_rng();
        (RsaPrivateKey::new(&mut rng, 2048).unwrap(), RsaPrivateKey::new(&mut rng, 2048).unwrap())
    })
}

fn n_hex(k: &RsaPrivateKey) -> String {
    k.n().to_bytes_be().iter().map(|b| format!("{b:02x}")).collect()
}

fn acct(s: &str) -> AccountId {
    s.parse().unwrap()
}

fn ctx(pred: &str, now_s: u64) {
    let mut b = VMContextBuilder::new();
    b.current_account_id(acct(CONTRACT)).predecessor_account_id(acct(pred)).block_timestamp(now_s * SEC);
    testing_env!(b.build());
}

fn claims(jti: &str) -> serde_json::Value {
    serde_json::json!({"iss": GITHUB_ISS, "aud": CONTRACT, "exp": NOW + 600, "iat": NOW - 10, "jti": jti,
        "repository": REPO, "job_workflow_ref": WF, "sha": "0123456789abcdef0123456789abcdef01234567",
        "repository_owner": "drexthealpha", "event_name": "push"})
}

fn sign_raw(k: &RsaPrivateKey, header: &str, payload: &str) -> String {
    let h = URL_SAFE_NO_PAD.encode(header);
    let p = URL_SAFE_NO_PAD.encode(payload);
    let sig = SigningKey::<Sha256>::new(k.clone()).sign(format!("{h}.{p}").as_bytes()).to_bytes();
    format!("{h}.{p}.{}", URL_SAFE_NO_PAD.encode(sig))
}

fn token_with(k: &RsaPrivateKey, kid: &str, c: &serde_json::Value) -> String {
    sign_raw(k, &format!(r#"{{"alg":"RS256","kid":"{kid}","typ":"JWT"}}"#), &c.to_string())
}

fn token(jti: &str) -> String {
    token_with(&keys().0, "gh1", &claims(jti))
}

fn owners() -> Vec<AccountId> {
    vec![accounts(0), accounts(1), accounts(2)]
}

/// A contract with GitHub's key "gh1" set by owners 0 and 1
fn contract() -> Knos {
    ctx("alice", NOW);
    let mut c = Knos::new(acct(USDC), owners());
    let n = n_hex(&keys().0);
    ctx(accounts(0).as_str(), NOW);
    c.propose_key("gh1".into(), Some(n.clone()));
    ctx(accounts(1).as_str(), NOW);
    c.propose_key("gh1".into(), Some(n));
    c
}

/// A Solana test mint address (any valid 32-byte base58 key)
const MINT: &str = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU";

fn fund_msg(id: &str, chain: &str, to: &str, deadline_s: u64) -> String {
    let mut v = serde_json::json!({"id": id, "payee_chain": chain, "payee_address": to, "criteria_hash": HASH,
        "repository": REPO, "workflow": WF, "deadline_ns": (deadline_s * SEC).to_string()});
    if chain == "solana" {
        v["payee_mint"] = MINT.into();
    }
    v.to_string()
}

fn fund(c: &mut Knos, id: &str) {
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(5_000_000), fund_msg(id, "near", "payee.testnet", NOW + 3600));
}

fn state(c: &Knos, id: &str) -> State {
    c.get_milestone(id.into()).unwrap().state
}

fn release(c: &mut Knos, id: &str, t: &str) {
    ctx("relayer.testnet", NOW);
    let _ = c.release(id.into(), t.into(), HASH.into());
}

// ---- setup and funding ----------------------------------------------------------------------------------------------

#[test]
#[should_panic(expected = "three different owners")]
fn new_needs_three_different_owners() {
    ctx("alice", NOW);
    Knos::new(acct(USDC), vec![accounts(0), accounts(0), accounts(2)]);
}

#[test]
fn funding_locks_the_milestone() {
    let mut c = contract();
    fund(&mut c, "m1");
    let m = c.get_milestone("m1".into()).unwrap();
    assert_eq!(m.state, State::Funded);
    assert_eq!(m.amount.0, 5_000_000);
    assert_eq!(m.criteria_hash, HASH);
    assert_eq!(m.payer, acct("payer.testnet"));
}

#[test]
#[should_panic(expected = "only the configured USDC")]
fn adversarial_funding_with_another_token_is_refused() {
    let mut c = contract();
    ctx("fake-usdc.testnet", NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(5), fund_msg("m1", "near", "payee.testnet", NOW + 3600));
}

#[test]
#[should_panic(expected = "criteria_hash must be 64 hex")]
fn funding_without_a_criteria_hash_is_refused() {
    let mut c = contract();
    ctx(USDC, NOW);
    let msg = fund_msg("m1", "near", "payee.testnet", NOW + 3600).replace(HASH, "abc");
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(5), msg);
}

#[test]
#[should_panic(expected = "a milestone with this id exists")]
fn funding_the_same_id_twice_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    fund(&mut c, "m1");
}

#[test]
#[should_panic(expected = "the deadline is in the past")]
fn funding_with_a_past_deadline_is_refused() {
    let mut c = contract();
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(5), fund_msg("m1", "near", "payee.testnet", NOW - 1));
}

#[test]
#[should_panic(expected = "payee_chain")]
fn funding_for_an_unknown_chain_is_refused() {
    let mut c = contract();
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(5), fund_msg("m1", "dogecoin", "x", NOW + 60));
}

#[test]
#[should_panic(expected = "repository and workflow")]
fn funding_with_a_workflow_outside_the_repository_is_refused() {
    let mut c = contract();
    ctx(USDC, NOW);
    let msg = fund_msg("m1", "near", "payee.testnet", NOW + 60).replace(WF, "someone/else/.github/workflows/x.yml@refs/heads/main");
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(5), msg);
}

// ---- the key set ----------------------------------------------------------------------------------------------------

#[test]
#[should_panic(expected = "the token's key is not in the key set")]
fn one_owner_alone_does_not_set_a_key() {
    ctx("alice", NOW);
    let mut c = Knos::new(acct(USDC), owners());
    ctx(accounts(0).as_str(), NOW);
    c.propose_key("gh1".into(), Some(n_hex(&keys().0)));
    fund(&mut c, "m1");
    release(&mut c, "m1", &token("j1"));
}

#[test]
fn two_owners_set_a_key() {
    let c = contract();
    let r = c.get_rules();
    assert_eq!(r["keys"][0]["kid"], "gh1");
    assert_eq!(r["keys"][0]["n"], n_hex(&keys().0));
}

#[test]
#[should_panic(expected = "only an owner changes the key set")]
fn adversarial_a_non_owner_cannot_change_the_key_set() {
    let mut c = contract();
    ctx("mallory.testnet", NOW);
    c.propose_key("gh1".into(), Some(n_hex(&keys().1)));
}

#[test]
fn the_same_owner_twice_does_not_apply_a_change() {
    let mut c = contract();
    ctx(accounts(2).as_str(), NOW);
    c.propose_key("evil".into(), Some(n_hex(&keys().1)));
    let r = c.propose_key("evil".into(), Some(n_hex(&keys().1)));
    assert!(r.contains("waiting"));
    assert_eq!(c.get_rules()["keys"].as_array().unwrap().len(), 1);
}

#[test]
#[should_panic(expected = "2048-bit RSA modulus")]
fn a_modulus_that_is_not_2048_bits_is_refused() {
    let mut c = contract();
    ctx(accounts(0).as_str(), NOW);
    c.propose_key("small".into(), Some("ff".repeat(128)));
}

#[test]
#[should_panic(expected = "the token's key is not in the key set")]
fn two_owners_remove_a_key_and_its_tokens_stop_verifying() {
    let mut c = contract();
    ctx(accounts(1).as_str(), NOW);
    c.propose_key("gh1".into(), None);
    ctx(accounts(2).as_str(), NOW);
    c.propose_key("gh1".into(), None);
    fund(&mut c, "m1");
    release(&mut c, "m1", &token("j1"));
}

// ---- release ------------------------------------------------------------------------------------------------------

#[test]
fn a_valid_token_pays_the_payee_on_near() {
    let mut c = contract();
    fund(&mut c, "m1");
    release(&mut c, "m1", &token("j1"));
    assert_eq!(state(&c, "m1"), State::Releasing);
    assert_eq!(c.get_milestone("m1".into()).unwrap().proof_sha.unwrap(), "0123456789abcdef0123456789abcdef01234567");
    ctx(CONTRACT, NOW);
    c.on_paid("m1".into(), false, Ok(()));
    assert_eq!(state(&c, "m1"), State::Released);
}

#[test]
fn a_valid_token_releases_a_payout_on_another_chain() {
    let mut c = contract();
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(7), fund_msg("s1", "solana", "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin", NOW + 60));
    release(&mut c, "s1", &token("j1"));
    assert_eq!(state(&c, "s1"), State::Released);
}

#[test]
#[should_panic(expected = "this token was already used")]
fn adversarial_a_replayed_token_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    fund(&mut c, "m2");
    release(&mut c, "m1", &token("j1"));
    release(&mut c, "m2", &token("j1"));
}

#[test]
#[should_panic(expected = "the token comes from another repository")]
fn adversarial_a_token_from_another_repository_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    let mut cl = claims("j1");
    cl["repository"] = "attacker/knos-demo".into();
    release(&mut c, "m1", &token_with(&keys().0, "gh1", &cl));
}

#[test]
#[should_panic(expected = "the token comes from another workflow")]
fn adversarial_a_token_from_another_workflow_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    let mut cl = claims("j1");
    cl["job_workflow_ref"] = "drexthealpha/knos-demo/.github/workflows/always-green.yml@refs/heads/main".into();
    release(&mut c, "m1", &token_with(&keys().0, "gh1", &cl));
}

#[test]
#[should_panic(expected = "the criteria are not the ones locked at funding")]
fn adversarial_altered_criteria_are_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    ctx("relayer.testnet", NOW);
    let _ = c.release("m1".into(), token("j1"), HASH.replace("ab", "cd"));
}

#[test]
#[should_panic(expected = "the deadline has not passed")]
fn adversarial_an_early_refund_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    ctx("payer.testnet", NOW + 10);
    let _ = c.refund("m1".into());
}

#[test]
#[should_panic(expected = "the milestone is not funded and open")]
fn adversarial_a_second_payment_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    release(&mut c, "m1", &token("j1"));
    ctx(CONTRACT, NOW);
    c.on_paid("m1".into(), false, Ok(()));
    release(&mut c, "m1", &token("j2"));
}

#[test]
#[should_panic(expected = "the token has expired")]
fn adversarial_an_expired_token_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    let mut cl = claims("j1");
    cl["exp"] = (NOW - 1).into();
    release(&mut c, "m1", &token_with(&keys().0, "gh1", &cl));
}

#[test]
#[should_panic(expected = "the token's audience is not this contract")]
fn adversarial_a_token_for_another_audience_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    let mut cl = claims("j1");
    cl["aud"] = "https://github.com/drexthealpha".into();
    release(&mut c, "m1", &token_with(&keys().0, "gh1", &cl));
}

#[test]
#[should_panic(expected = "the milestone is not funded and open")]
fn adversarial_a_release_after_the_refund_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    ctx("anyone.testnet", NOW + 3600);
    let _ = c.refund("m1".into());
    ctx(CONTRACT, NOW + 3600);
    c.on_paid("m1".into(), true, Ok(()));
    release(&mut c, "m1", &token("j1"));
}

#[test]
#[should_panic(expected = "the token's signature does not verify")]
fn adversarial_a_forged_token_under_another_key_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    release(&mut c, "m1", &token_with(&keys().1, "gh1", &claims("j1")));
}

#[test]
#[should_panic(expected = "the token's signature does not verify")]
fn adversarial_a_re_signed_token_with_an_altered_payload_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    let good = token("j1");
    let parts: Vec<&str> = good.split('.').collect();
    let mut cl = claims("j1");
    cl["repository"] = REPO.into();
    cl["sha"] = "ffffffffffffffffffffffffffffffffffffffff".into();
    let altered = format!("{}.{}.{}", parts[0], URL_SAFE_NO_PAD.encode(cl.to_string()), parts[2]);
    release(&mut c, "m1", &altered);
}

#[test]
#[should_panic(expected = "the token's key is not in the key set")]
fn a_token_under_an_unknown_kid_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    release(&mut c, "m1", &token_with(&keys().0, "gh9", &claims("j1")));
}

#[test]
#[should_panic(expected = "the token is not GitHub's")]
fn a_token_from_another_issuer_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    let mut cl = claims("j1");
    cl["iss"] = "https://gitlab.com".into();
    release(&mut c, "m1", &token_with(&keys().0, "gh1", &cl));
}

#[test]
#[should_panic(expected = "the token is not RS256")]
fn a_token_that_is_not_rs256_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    release(&mut c, "m1", &sign_raw(&keys().0, r#"{"alg":"none","kid":"gh1"}"#, &claims("j1").to_string()));
}

#[test]
#[should_panic(expected = "the deadline has passed")]
fn a_release_after_the_deadline_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    ctx("relayer.testnet", NOW + 3600);
    let _ = c.release("m1".into(), token("j1"), HASH.into());
}

#[test]
#[should_panic(expected = "the token's claims")]
fn a_token_that_names_a_claim_twice_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    let body = claims("j1").to_string().replacen('{', r#"{"repository":"attacker/x","#, 1);
    release(&mut c, "m1", &sign_raw(&keys().0, r#"{"alg":"RS256","kid":"gh1"}"#, &body));
}

#[test]
#[should_panic(expected = "header.payload.signature")]
fn a_token_with_four_parts_is_refused() {
    let mut c = contract();
    fund(&mut c, "m1");
    release(&mut c, "m1", &format!("{}.x", token("j1")));
}

#[test]
fn a_failed_payout_reopens_the_milestone_and_frees_its_token() {
    let mut c = contract();
    fund(&mut c, "m1");
    let t = token("j1");
    release(&mut c, "m1", &t);
    ctx(CONTRACT, NOW);
    c.on_paid("m1".into(), false, Err(PromiseError::Failed));
    assert_eq!(state(&c, "m1"), State::Funded);
    release(&mut c, "m1", &t);
    assert_eq!(state(&c, "m1"), State::Releasing);
}

#[test]
fn a_refund_after_the_deadline_returns_the_money_to_the_payer() {
    let mut c = contract();
    fund(&mut c, "m1");
    ctx("anyone.testnet", NOW + 3600);
    let _ = c.refund("m1".into());
    assert_eq!(state(&c, "m1"), State::Refunding);
    ctx(CONTRACT, NOW + 3600);
    c.on_paid("m1".into(), true, Ok(()));
    assert_eq!(state(&c, "m1"), State::Refunded);
}

#[test]
fn the_rules_are_readable_and_the_fee_is_zero() {
    let c = contract();
    let r = c.get_rules();
    assert_eq!(r["fee"], "0");
    assert_eq!(r["issuer"], GITHUB_ISS);
    assert_eq!(r["audience"], CONTRACT);
    assert_eq!(r["owners"].as_array().unwrap().len(), 3);
}

// ---- the RSA code itself -------------------------------------------------------------------------------------------

#[test]
fn rsa_refuses_a_signature_not_below_the_modulus() {
    let k = &keys().0;
    let n = k.n().to_bytes_be();
    let (nl, n0inv, r2) = crate::rsa::constants(&n).unwrap();
    assert!(!crate::rsa::verify(&nl, n0inv, &r2, &n, &[0u8; 32]));
}

#[test]
fn rsa_constants_need_a_2048_bit_odd_modulus() {
    assert!(crate::rsa::constants(&[0xffu8; 128]).is_none());
    let mut even = vec![0xffu8; 256];
    even[255] = 0xfe;
    assert!(crate::rsa::constants(&even).is_none());
}

#[test]
fn rsa_verifies_what_the_rsa_crate_signs() {
    let k = &keys().0;
    let msg = b"knos";
    let sig = SigningKey::<Sha256>::new(k.clone()).sign(msg).to_bytes();
    let digest = <Sha256 as sha2::Digest>::digest(msg);
    let (n, n0inv, r2) = crate::rsa::constants(&k.n().to_bytes_be()).unwrap();
    assert!(crate::rsa::verify(&n, n0inv, &r2, &sig, &digest));
    let mut bad = sig.to_vec();
    bad[100] ^= 1;
    assert!(!crate::rsa::verify(&n, n0inv, &r2, &bad, &digest));
}

mod more;
mod payout;
