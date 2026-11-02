//! More unit tests: one change to a token, a funding message or the key set per test, each refused with the
//! contract's own reason, or accepted where the rule says it should be. "adversarial" marks an attack.

use super::*;

fn with(f: impl Fn(&mut serde_json::Value)) -> String {
    let mut c = claims("j-more");
    f(&mut c);
    token_with(&keys().0, "gh1", &c)
}

fn header(h: &str) -> String {
    sign_raw(&keys().0, h, &claims("j-more").to_string())
}

fn funded() -> Knos {
    let mut c = contract();
    fund(&mut c, "m");
    c
}

fn fund_json(f: impl Fn(&mut serde_json::Value)) -> String {
    let mut v: serde_json::Value = serde_json::from_str(&fund_msg("f", "near", "payee.testnet", NOW + 3600)).unwrap();
    f(&mut v);
    v.to_string()
}

fn fund_raw(c: &mut Knos, msg: String) {
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(5_000_000), msg);
}

/// A release that must be refused with `$why`
macro_rules! refused {
    ($name:ident, $why:literal, $tok:expr) => {
        #[test]
        #[should_panic(expected = $why)]
        fn $name() {
            let mut c = funded();
            let t: String = $tok;
            release(&mut c, "m", &t);
        }
    };
}

/// A funding message that must be refused with `$why`
macro_rules! refused_fund {
    ($name:ident, $why:literal, $msg:expr) => {
        #[test]
        #[should_panic(expected = $why)]
        fn $name() {
            let mut c = contract();
            fund_raw(&mut c, $msg);
        }
    };
}

/// A release that must pay
macro_rules! accepted {
    ($name:ident, $tok:expr) => {
        #[test]
        fn $name() {
            let mut c = funded();
            let t: String = $tok;
            release(&mut c, "m", &t);
            assert_eq!(state(&c, "m"), State::Releasing);
        }
    };
}

// ---- the issuer ------------------------------------------------------------------------------------------------------
refused!(adversarial_an_issuer_with_a_trailing_slash, "not GitHub's", with(|c| c["iss"] = "https://token.actions.githubusercontent.com/".into()));
refused!(adversarial_an_issuer_over_http, "not GitHub's", with(|c| c["iss"] = "http://token.actions.githubusercontent.com".into()));
refused!(adversarial_an_issuer_in_capitals, "not GitHub's", with(|c| c["iss"] = "https://TOKEN.actions.githubusercontent.com".into()));
refused!(adversarial_an_empty_issuer, "not GitHub's", with(|c| c["iss"] = "".into()));
refused!(adversarial_a_lookalike_issuer, "not GitHub's", with(|c| c["iss"] = "https://token.actions.githubusercontent.com.evil.example".into()));

// ---- the audience ----------------------------------------------------------------------------------------------------
refused!(adversarial_an_empty_audience, "audience is not this contract", with(|c| c["aud"] = "".into()));
refused!(adversarial_an_audience_with_a_suffix, "audience is not this contract", with(|c| c["aud"] = "knos.testnet.evil".into()));
refused!(adversarial_an_audience_with_a_prefix, "audience is not this contract", with(|c| c["aud"] = "evil.knos.testnet".into()));
refused!(adversarial_an_audience_in_capitals, "audience is not this contract", with(|c| c["aud"] = "KNOS.testnet".into()));
refused!(adversarial_the_token_contract_as_audience, "audience is not this contract", with(|c| c["aud"] = USDC.into()));

// ---- expiry ----------------------------------------------------------------------------------------------------------
refused!(adversarial_a_token_expiring_this_second, "expired", with(|c| c["exp"] = NOW.into()));
refused!(adversarial_a_token_with_expiry_zero, "expired", with(|c| c["exp"] = 0.into()));
refused!(adversarial_an_expiry_as_a_string, "the token's claims", with(|c| c["exp"] = format!("{}", NOW + 600).into()));
accepted!(a_token_valid_for_one_more_second_pays, with(|c| c["exp"] = (NOW + 1).into()));

// ---- the repository --------------------------------------------------------------------------------------------------
refused!(adversarial_the_same_name_under_another_owner, "another repository", with(|c| c["repository"] = "evil/knos-demo".into()));
refused!(adversarial_a_fork_with_a_suffix, "another repository", with(|c| c["repository"] = "drexthealpha/knos-demo-fork".into()));
refused!(adversarial_an_empty_repository, "another repository", with(|c| c["repository"] = "".into()));
refused!(adversarial_a_repository_with_a_trailing_slash, "another repository", with(|c| c["repository"] = "drexthealpha/knos-demo/".into()));
accepted!(the_repository_matches_without_case, with(|c| c["repository"] = "DrexTheAlpha/Knos-Demo".into()));

// ---- the workflow ----------------------------------------------------------------------------------------------------
refused!(adversarial_the_workflow_at_a_tag, "another workflow", with(|c| c["job_workflow_ref"] = "drexthealpha/knos-demo/.github/workflows/proof.yml@refs/tags/v1".into()));
refused!(adversarial_the_workflow_on_a_pull_request, "another workflow", with(|c| c["job_workflow_ref"] = "drexthealpha/knos-demo/.github/workflows/proof.yml@refs/pull/1/merge".into()));
refused!(adversarial_another_workflow_file, "another workflow", with(|c| c["job_workflow_ref"] = "drexthealpha/knos-demo/.github/workflows/release.yml@refs/heads/main".into()));
refused!(adversarial_a_workflow_with_a_trailing_space, "another workflow", with(|c| c["job_workflow_ref"] = format!("{WF} ").into()));
refused!(adversarial_the_workflow_path_in_capitals, "another workflow", with(|c| c["job_workflow_ref"] = WF.to_ascii_uppercase().into()));
refused!(adversarial_a_reusable_workflow_from_a_fork, "another workflow", with(|c| c["job_workflow_ref"] = "evil/knos-demo/.github/workflows/proof.yml@refs/heads/main".into()));

// ---- the commit ------------------------------------------------------------------------------------------------------
refused!(adversarial_a_commit_of_39_characters, "names no commit", with(|c| c["sha"] = "0123456789abcdef0123456789abcdef0123456".into()));
refused!(adversarial_a_commit_of_41_characters, "names no commit", with(|c| c["sha"] = "0123456789abcdef0123456789abcdef012345678".into()));
refused!(adversarial_a_commit_in_capitals, "names no commit", with(|c| c["sha"] = "0123456789ABCDEF0123456789ABCDEF01234567".into()));
refused!(adversarial_a_commit_that_is_not_hex, "names no commit", with(|c| c["sha"] = "g123456789abcdef0123456789abcdef01234567".into()));
refused!(adversarial_an_empty_commit, "names no commit", with(|c| c["sha"] = "".into()));

// ---- missing claims --------------------------------------------------------------------------------------------------
refused!(adversarial_a_token_without_jti, "the token's claims", with(|c| { c.as_object_mut().unwrap().remove("jti"); }));
refused!(adversarial_a_token_without_commit, "the token's claims", with(|c| { c.as_object_mut().unwrap().remove("sha"); }));
refused!(adversarial_a_token_without_workflow, "the token's claims", with(|c| { c.as_object_mut().unwrap().remove("job_workflow_ref"); }));
refused!(adversarial_a_token_without_audience, "the token's claims", with(|c| { c.as_object_mut().unwrap().remove("aud"); }));
refused!(adversarial_a_payload_that_is_an_array, "the token's claims", sign_raw(&keys().0, r#"{"alg":"RS256","kid":"gh1"}"#, "[1,2,3]"));

// ---- the header ------------------------------------------------------------------------------------------------------
refused!(adversarial_alg_in_lower_case, "not RS256", header(r#"{"alg":"rs256","kid":"gh1"}"#));
refused!(adversarial_alg_ps256, "not RS256", header(r#"{"alg":"PS256","kid":"gh1"}"#));
refused!(adversarial_alg_es256, "not RS256", header(r#"{"alg":"ES256","kid":"gh1"}"#));
refused!(adversarial_alg_none, "not RS256", header(r#"{"alg":"none","kid":"gh1"}"#));
refused!(adversarial_a_header_without_kid, "header", header(r#"{"alg":"RS256"}"#));
refused!(adversarial_a_kid_that_was_never_set, "not in the key set", header(r#"{"alg":"RS256","kid":"gh2"}"#));
refused!(adversarial_a_header_that_is_not_json, "header", sign_raw(&keys().0, "not json", &claims("j-more").to_string()));

// ---- the token's form ------------------------------------------------------------------------------------------------
refused!(adversarial_a_token_of_two_parts, "header.payload.signature", "eyJhbGciOiJSUzI1NiJ9.e30".to_string());
refused!(adversarial_an_empty_token, "header", String::new());
refused!(adversarial_a_header_that_is_not_base64, "header encoding", format!("***.{}", token("j-more").split_once('.').unwrap().1));
refused!(adversarial_a_payload_that_is_not_base64, "payload encoding", {
    let t = token("j-more");
    let p: Vec<&str> = t.split('.').collect();
    format!("{}.***.{}", p[0], p[2])
});
refused!(adversarial_a_signature_that_is_not_base64, "signature encoding", {
    let t = token("j-more");
    format!("{}.***", t.rsplit_once('.').unwrap().0)
});
refused!(adversarial_a_token_over_8192_bytes, "too long", with(|c| c["pad"] = "x".repeat(9000).into()));

// ---- the signature ---------------------------------------------------------------------------------------------------
fn resign(f: impl Fn(&mut Vec<u8>)) -> String {
    let t = token("j-more");
    let (head, s) = t.rsplit_once('.').unwrap();
    let mut sig = URL_SAFE_NO_PAD.decode(s).unwrap();
    f(&mut sig);
    format!("{head}.{}", URL_SAFE_NO_PAD.encode(sig))
}
refused!(adversarial_a_signature_of_zeros, "does not verify", resign(|s| s.iter_mut().for_each(|b| *b = 0)));
refused!(adversarial_one_bit_flipped_in_the_signature, "does not verify", resign(|s| s[200] ^= 1));
refused!(adversarial_an_empty_signature, "does not verify", resign(|s| s.clear()));
refused!(adversarial_a_signature_twice_as_long, "does not verify", resign(|s| { let c = s.clone(); s.extend(c); }));
refused!(adversarial_a_signature_moved_from_another_token, "does not verify", {
    let a = token("j-a");
    let b = with(|c| c["repository"] = "drexthealpha/knos-demo".into());
    format!("{}.{}", b.rsplit_once('.').unwrap().0, a.rsplit_once('.').unwrap().1)
});
refused!(adversarial_a_token_under_the_second_test_key, "does not verify", token_with(&keys().1, "gh1", &claims("j-more")));

// ---- the release call ------------------------------------------------------------------------------------------------
#[test]
#[should_panic(expected = "criteria are not the ones locked")]
fn adversarial_the_criteria_hash_in_capitals() {
    let mut c = funded();
    ctx("relayer.testnet", NOW);
    let _ = c.release("m".into(), token("j-more"), HASH.to_ascii_uppercase());
}

#[test]
#[should_panic(expected = "criteria are not the ones locked")]
fn adversarial_an_empty_criteria_hash() {
    let mut c = funded();
    ctx("relayer.testnet", NOW);
    let _ = c.release("m".into(), token("j-more"), String::new());
}

#[test]
#[should_panic(expected = "no such milestone")]
fn adversarial_a_release_for_an_unknown_milestone() {
    let mut c = funded();
    release(&mut c, "other", &token("j-more"));
}

#[test]
#[should_panic(expected = "deadline has passed")]
fn adversarial_a_release_at_the_deadline_itself() {
    let mut c = funded();
    ctx("relayer.testnet", NOW + 3600);
    let _ = c.release("m".into(), token("j-more"), HASH.into());
}

#[test]
#[should_panic(expected = "not funded and open")]
fn adversarial_a_release_while_the_payout_is_in_flight() {
    let mut c = funded();
    release(&mut c, "m", &token("j-1"));
    release(&mut c, "m", &token("j-2"));
}

#[test]
#[should_panic(expected = "not funded and open")]
fn adversarial_a_release_while_the_refund_is_in_flight() {
    let mut c = funded();
    ctx("anyone.testnet", NOW + 3600);
    let _ = c.refund("m".into());
    ctx("relayer.testnet", NOW + 10);
    let _ = c.release("m".into(), token("j-more"), HASH.into());
}

#[test]
#[should_panic(expected = "already used")]
fn adversarial_one_token_for_two_milestones() {
    let mut c = funded();
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(1), fund_msg("m2", "near", "payee.testnet", NOW + 3600));
    let t = token("j-shared");
    release(&mut c, "m", &t);
    release(&mut c, "m2", &t);
}

#[test]
#[should_panic(expected = "already used")]
fn adversarial_a_token_used_on_another_chain_cannot_pay_on_near() {
    let mut c = contract();
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(1), fund_msg("sol", "solana", "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin", NOW + 3600));
    fund(&mut c, "m");
    let t = token("j-x");
    release(&mut c, "sol", &t);
    release(&mut c, "m", &t);
}

#[test]
fn anyone_may_send_the_release() {
    let mut c = funded();
    ctx("a-stranger.testnet", NOW);
    let _ = c.release("m".into(), token("j-more"), HASH.into());
    assert_eq!(state(&c, "m"), State::Releasing);
}

#[test]
fn a_release_keeps_the_commit_and_the_jti() {
    let mut c = funded();
    release(&mut c, "m", &token("j-kept"));
    let m = c.get_milestone("m".into()).unwrap();
    assert_eq!(m.proof_jti.as_deref(), Some("j-kept"));
    assert_eq!(m.proof_sha.as_deref(), Some("0123456789abcdef0123456789abcdef01234567"));
}

#[test]
fn a_paid_release_ends_released() {
    let mut c = funded();
    release(&mut c, "m", &token("j-more"));
    ctx(CONTRACT, NOW);
    c.on_paid("m".into(), false, Ok(()));
    assert_eq!(state(&c, "m"), State::Released);
}

#[test]
fn an_ethereum_payout_is_released_for_its_signature() {
    let mut c = contract();
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(7), fund_msg("eth", "ethereum", "0x580C000000000000000000000000000000bB3A", NOW + 3600));
    release(&mut c, "eth", &token("j-eth"));
    assert_eq!(state(&c, "eth"), State::Released);
}

// ---- refunds ---------------------------------------------------------------------------------------------------------
#[test]
fn a_refund_at_the_deadline_itself_is_allowed() {
    let mut c = funded();
    ctx("anyone.testnet", NOW + 3600);
    let _ = c.refund("m".into());
    assert_eq!(state(&c, "m"), State::Refunding);
}

#[test]
#[should_panic(expected = "has not passed")]
fn adversarial_a_refund_one_second_early() {
    let mut c = funded();
    ctx("anyone.testnet", NOW + 3599);
    let _ = c.refund("m".into());
}

#[test]
#[should_panic(expected = "no such milestone")]
fn adversarial_a_refund_for_an_unknown_milestone() {
    let mut c = funded();
    ctx("anyone.testnet", NOW + 3600);
    let _ = c.refund("nope".into());
}

#[test]
#[should_panic(expected = "not funded and open")]
fn adversarial_a_second_refund_while_the_first_is_in_flight() {
    let mut c = funded();
    ctx("anyone.testnet", NOW + 3600);
    let _ = c.refund("m".into());
    let _ = c.refund("m".into());
}

#[test]
#[should_panic(expected = "not funded and open")]
fn adversarial_a_refund_after_a_release() {
    let mut c = funded();
    release(&mut c, "m", &token("j-more"));
    ctx("anyone.testnet", NOW + 3600);
    let _ = c.refund("m".into());
}

#[test]
fn a_failed_refund_reopens_the_milestone() {
    let mut c = funded();
    ctx("anyone.testnet", NOW + 3600);
    let _ = c.refund("m".into());
    ctx(CONTRACT, NOW + 3600);
    c.on_paid("m".into(), true, Err(PromiseError::Failed));
    assert_eq!(state(&c, "m"), State::Funded);
}

// ---- funding ---------------------------------------------------------------------------------------------------------
#[test]
#[should_panic(expected = "amount")]
fn adversarial_funding_with_zero() {
    let mut c = contract();
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(0), fund_msg("z", "near", "payee.testnet", NOW + 3600));
}

#[test]
#[should_panic(expected = "only the configured USDC")]
fn adversarial_a_payer_calling_the_receiver_directly() {
    let mut c = contract();
    ctx("payer.testnet", NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(5), fund_msg("d", "near", "payee.testnet", NOW + 3600));
}

refused_fund!(adversarial_a_message_that_is_not_json, "msg is not a milestone", "pay me".to_string());
refused_fund!(adversarial_a_message_without_a_deadline, "msg is not a milestone", fund_json(|v| { v.as_object_mut().unwrap().remove("deadline_ns"); }));
refused_fund!(adversarial_an_empty_id, "id", fund_json(|v| v["id"] = "".into()));
refused_fund!(adversarial_an_id_of_65_characters, "id", fund_json(|v| v["id"] = "x".repeat(65).into()));
refused_fund!(adversarial_criteria_in_capitals, "64 hex", fund_json(|v| v["criteria_hash"] = HASH.to_ascii_uppercase().into()));
refused_fund!(adversarial_criteria_of_63_characters, "64 hex", fund_json(|v| v["criteria_hash"] = HASH[..63].into()));
refused_fund!(adversarial_criteria_that_are_not_hex, "64 hex", fund_json(|v| v["criteria_hash"] = format!("z{}", &HASH[1..]).into()));
refused_fund!(adversarial_a_chain_in_capitals, "payee_chain", fund_json(|v| v["payee_chain"] = "Near".into()));
refused_fund!(adversarial_an_empty_chain, "payee_chain", fund_json(|v| v["payee_chain"] = "".into()));
refused_fund!(adversarial_a_near_payee_that_is_not_an_account, "payee address", fund_json(|v| v["payee_address"] = "Bad Address".into()));
refused_fund!(adversarial_a_repository_without_owner, "repository and workflow", fund_json(|v| { v["repository"] = "knos".into(); v["workflow"] = "knos/.github/workflows/p.yml@refs/heads/main".into(); }));
refused_fund!(adversarial_a_workflow_in_a_lookalike_repository, "repository and workflow", fund_json(|v| v["workflow"] = "drexthealpha/knos-demo2/.github/workflows/proof.yml@refs/heads/main".into()));
refused_fund!(adversarial_a_workflow_equal_to_the_repository, "repository and workflow", fund_json(|v| v["workflow"] = REPO.into()));
refused_fund!(adversarial_a_deadline_equal_to_now, "in the past", fund_json(|v| v["deadline_ns"] = (NOW * SEC).to_string().into()));
refused_fund!(adversarial_a_deadline_of_zero, "in the past", fund_json(|v| v["deadline_ns"] = "0".into()));

#[test]
fn an_id_of_64_characters_is_accepted() {
    let mut c = contract();
    fund_raw(&mut c, fund_json(|v| v["id"] = "x".repeat(64).into()));
    assert_eq!(state(&c, &"x".repeat(64)), State::Funded);
}

#[test]
fn a_solana_payee_takes_a_solana_address() {
    let mut c = contract();
    fund_raw(&mut c, fund_json(|v| { v["payee_chain"] = "solana".into(); v["payee_address"] = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin".into(); }));
    assert_eq!(c.get_milestone("f".into()).unwrap().payee_chain, "solana");
}

#[test]
fn the_repository_is_kept_in_lower_case() {
    let mut c = contract();
    fund_raw(&mut c, fund_json(|v| { v["repository"] = "DrexTheAlpha/Knos-Demo".into(); v["workflow"] = format!("DrexTheAlpha/Knos-Demo/.github/workflows/proof.yml@refs/heads/main").into(); }));
    assert_eq!(c.get_milestone("f".into()).unwrap().repository, "drexthealpha/knos-demo");
}

#[test]
fn funding_keeps_the_payer_the_amount_and_the_deadline() {
    let mut c = contract();
    fund_raw(&mut c, fund_json(|_| {}));
    let m = c.get_milestone("f".into()).unwrap();
    assert_eq!((m.payer.as_str(), m.amount.0, m.deadline_ns.0), ("payer.testnet", 5_000_000, (NOW + 3600) * SEC));
}

// ---- the key set -----------------------------------------------------------------------------------------------------
fn propose(c: &mut Knos, who: usize, kid: &str, n: Option<String>) -> String {
    ctx(accounts(who).as_str(), NOW);
    c.propose_key(kid.into(), n)
}

#[test]
#[should_panic(expected = "kid")]
fn adversarial_an_empty_kid() {
    let mut c = contract();
    propose(&mut c, 0, "", Some(n_hex(&keys().1)));
}

#[test]
#[should_panic(expected = "kid")]
fn adversarial_a_kid_of_129_characters() {
    let mut c = contract();
    propose(&mut c, 0, &"k".repeat(129), Some(n_hex(&keys().1)));
}

#[test]
fn a_kid_of_128_characters_waits_for_a_second_owner() {
    let mut c = contract();
    assert!(propose(&mut c, 0, &"k".repeat(128), Some(n_hex(&keys().1))).contains("waiting for a second owner"));
}

#[test]
#[should_panic(expected = "2048-bit")]
fn adversarial_a_modulus_of_odd_hex_length() {
    let mut c = contract();
    propose(&mut c, 0, "gh2", Some(format!("{}0", n_hex(&keys().1))));
}

#[test]
#[should_panic(expected = "2048-bit")]
fn adversarial_a_modulus_that_is_not_hex() {
    let mut c = contract();
    propose(&mut c, 0, "gh2", Some(format!("zz{}", &n_hex(&keys().1)[2..])));
}

#[test]
#[should_panic(expected = "2048-bit")]
fn adversarial_an_even_modulus() {
    let mut c = contract();
    let mut n = n_hex(&keys().1);
    n.pop();
    n.push('0');
    propose(&mut c, 0, "gh2", Some(n));
}

#[test]
#[should_panic(expected = "2048-bit")]
fn adversarial_a_modulus_one_byte_short() {
    let mut c = contract();
    propose(&mut c, 0, "gh2", Some(n_hex(&keys().1)[2..].to_string()));
}

#[test]
#[should_panic(expected = "only an owner")]
fn adversarial_a_stranger_removing_a_key() {
    let mut c = contract();
    ctx("stranger.testnet", NOW);
    c.propose_key("gh1".into(), None);
}

#[test]
fn two_owners_proposing_different_keys_set_nothing() {
    let mut c = contract();
    propose(&mut c, 0, "gh2", Some(n_hex(&keys().1)));
    let mut other = n_hex(&keys().0);
    other.replace_range(0..2, "ff");
    let r = propose(&mut c, 1, "gh2", Some(other));
    assert!(r.contains("waiting"));
    assert!(!c.kids.contains(&"gh2".to_string()));
}

#[test]
fn one_owner_alone_cannot_remove_a_key() {
    let mut c = funded();
    propose(&mut c, 2, "gh1", None);
    release(&mut c, "m", &token("j-more"));
    assert_eq!(state(&c, "m"), State::Releasing);
}

#[test]
fn a_second_key_verifies_beside_the_first() {
    let mut c = funded();
    propose(&mut c, 1, "gh2", Some(n_hex(&keys().1)));
    propose(&mut c, 2, "gh2", Some(n_hex(&keys().1)));
    release(&mut c, "m", &token_with(&keys().1, "gh2", &claims("j-gh2")));
    assert_eq!(state(&c, "m"), State::Releasing);
}

#[test]
fn removing_one_key_keeps_the_other() {
    let mut c = funded();
    propose(&mut c, 1, "gh2", Some(n_hex(&keys().1)));
    propose(&mut c, 2, "gh2", Some(n_hex(&keys().1)));
    propose(&mut c, 0, "gh1", None);
    propose(&mut c, 2, "gh1", None);
    release(&mut c, "m", &token_with(&keys().1, "gh2", &claims("j-gh2")));
    assert_eq!(state(&c, "m"), State::Releasing);
}

#[test]
fn a_modulus_in_capitals_is_the_same_key() {
    let mut c = funded();
    propose(&mut c, 1, "gh2", Some(n_hex(&keys().1).to_ascii_uppercase()));
    propose(&mut c, 2, "gh2", Some(n_hex(&keys().1)));
    release(&mut c, "m", &token_with(&keys().1, "gh2", &claims("j-gh2")));
    assert_eq!(state(&c, "m"), State::Releasing);
}

#[test]
fn a_later_proposal_replaces_an_earlier_one() {
    let mut c = contract();
    propose(&mut c, 0, "gh2", Some(n_hex(&keys().1)));
    propose(&mut c, 1, "gh2", None);
    assert!(propose(&mut c, 2, "gh2", Some(n_hex(&keys().1))).contains("waiting"));
    assert!(!c.kids.contains(&"gh2".to_string()));
}

// ---- reading ---------------------------------------------------------------------------------------------------------
#[test]
fn the_rules_list_each_key_with_its_modulus() {
    let c = contract();
    let r = c.get_rules();
    assert_eq!(r["keys"][0]["kid"], "gh1");
    assert_eq!(r["keys"][0]["n"], n_hex(&keys().0));
}

#[test]
fn the_rules_name_the_contract_as_audience_and_the_token() {
    let c = contract();
    let r = c.get_rules();
    assert_eq!(r["audience"], CONTRACT);
    assert_eq!(r["usdc"], USDC);
}

#[test]
fn an_unknown_milestone_reads_as_none() {
    let c = contract();
    assert!(c.get_milestone("nope".into()).is_none());
}
