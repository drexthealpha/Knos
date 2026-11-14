//! Open jobs and budgets: two agents take one job, only the one whose output passed the locked test is paid; a budget
//! refuses a payment over its cap. "adversarial" marks the attacks.

use super::*;
use crate::jobs::{recover_signer, JobState, CHECKER_ISS, CIRCLE_USDC};

const OUT_A: &str = "aaaa000000000000000000000000000000000000000000000000000000000001";
const OUT_B: &str = "bbbb000000000000000000000000000000000000000000000000000000000002";

/// The contract with GitHub's key and a checker key "ck1" (the second test key) set by owners 0 and 1
fn with_checker() -> Knos {
    let mut c = contract();
    let n = n_hex(&keys().1);
    ctx(accounts(0).as_str(), NOW);
    c.propose_checker_key("ck1".into(), Some(n.clone()));
    ctx(accounts(1).as_str(), NOW);
    c.propose_checker_key("ck1".into(), Some(n));
    c
}

fn job_msg(id: &str, deadline_s: u64) -> String {
    serde_json::json!({"open_job": {"id": id, "criteria_hash": HASH, "deadline_ns": (deadline_s * SEC).to_string()}}).to_string()
}

fn open(c: &mut Knos, id: &str) {
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(3_000_000), job_msg(id, NOW + 3600));
}

fn take_and_submit(c: &mut Knos, id: &str, agent: &str, out: &str) {
    ctx(agent, NOW);
    c.take(id.into());
    c.submit(id.into(), out.into());
}

fn checker(job: &str, payee: &str, out: &str, jti: &str) -> serde_json::Value {
    serde_json::json!({"iss": CHECKER_ISS, "aud": CONTRACT, "exp": NOW + 600, "iat": NOW - 5, "jti": jti,
        "job": job, "payee": payee, "output_sha256": out, "criteria_hash": HASH})
}

fn ctoken(c: &serde_json::Value) -> String {
    token_with(&keys().1, "ck1", c)
}

/// The job of U3: two agents took it and submitted; the passing one's token
fn two_agents() -> Knos {
    let mut c = with_checker();
    open(&mut c, "j1");
    take_and_submit(&mut c, "j1", "agent-a.testnet", OUT_A);
    take_and_submit(&mut c, "j1", "agent-b.testnet", OUT_B);
    c
}

#[test]
fn a_job_opens_with_no_payee_and_both_attempts_are_on_record() {
    let c = two_agents();
    let j = c.get_job("j1".into()).unwrap();
    assert_eq!(j.state, JobState::Open);
    assert_eq!(j.amount.0, 3_000_000);
    assert_eq!(j.takers, vec![acct("agent-a.testnet"), acct("agent-b.testnet")]);
    assert_eq!(j.attempts.len(), 2);
    assert_eq!(j.attempts[1].output_sha256, OUT_B);
    assert!(j.paid_to.is_none());
}

#[test]
fn the_checker_token_pays_the_agent_whose_output_passed() {
    let mut c = two_agents();
    ctx("relayer.testnet", NOW);
    let _ = c.release_job("j1".into(), ctoken(&checker("j1", "agent-a.testnet", OUT_A, "c-1")));
    let j = c.get_job("j1".into()).unwrap();
    assert_eq!(j.state, JobState::Paying);
    assert_eq!(j.paid_to, Some(acct("agent-a.testnet")));
}

#[test]
#[should_panic(expected = "the token checked another output than the payee submitted")]
fn adversarial_a_token_for_one_output_cannot_pay_an_agent_that_submitted_another() {
    let mut c = two_agents();
    ctx("agent-b.testnet", NOW);
    let _ = c.release_job("j1".into(), ctoken(&checker("j1", "agent-b.testnet", OUT_A, "c-2")));
}

#[test]
#[should_panic(expected = "the payee submitted no output")]
fn adversarial_an_agent_that_submitted_nothing_is_not_paid() {
    let mut c = two_agents();
    ctx("relayer.testnet", NOW);
    let _ = c.release_job("j1".into(), ctoken(&checker("j1", "mallory.testnet", OUT_A, "c-3")));
}

#[test]
#[should_panic(expected = "the token's key is not a checker key")]
fn adversarial_a_github_key_cannot_sign_a_checker_token() {
    let mut c = two_agents();
    ctx("relayer.testnet", NOW);
    let _ = c.release_job("j1".into(), token_with(&keys().0, "gh1", &checker("j1", "agent-a.testnet", OUT_A, "c-4")));
}

#[test]
#[should_panic(expected = "the token's claims")]
fn adversarial_a_github_token_is_not_a_checker_token() {
    let mut c = two_agents();
    ctx("relayer.testnet", NOW);
    let _ = c.release_job("j1".into(), token_with(&keys().1, "ck1", &claims("gh-jti")));
}

#[test]
#[should_panic(expected = "the token is not a Knos checker's")]
fn adversarial_another_issuer_is_refused() {
    let mut c = two_agents();
    let mut v = checker("j1", "agent-a.testnet", OUT_A, "c-5");
    v["iss"] = GITHUB_ISS.into();
    ctx("relayer.testnet", NOW);
    let _ = c.release_job("j1".into(), ctoken(&v));
}

#[test]
#[should_panic(expected = "the token checked another test than the one locked at funding")]
fn adversarial_a_token_for_another_test_is_refused() {
    let mut c = two_agents();
    let mut v = checker("j1", "agent-a.testnet", OUT_A, "c-6");
    v["criteria_hash"] = "ff".repeat(32).into();
    ctx("relayer.testnet", NOW);
    let _ = c.release_job("j1".into(), ctoken(&v));
}

#[test]
#[should_panic(expected = "the token is for another job")]
fn adversarial_a_token_for_another_job_is_refused() {
    let mut c = two_agents();
    ctx("relayer.testnet", NOW);
    let _ = c.release_job("j1".into(), ctoken(&checker("j2", "agent-a.testnet", OUT_A, "c-7")));
}

#[test]
#[should_panic(expected = "the token's signature does not verify")]
fn adversarial_a_changed_payee_breaks_the_signature() {
    let mut c = two_agents();
    let t = ctoken(&checker("j1", "agent-a.testnet", OUT_A, "c-8"));
    let parts: Vec<&str> = t.split('.').collect();
    let forged = URL_SAFE_NO_PAD.encode(checker("j1", "agent-b.testnet", OUT_A, "c-8").to_string());
    ctx("relayer.testnet", NOW);
    let _ = c.release_job("j1".into(), format!("{}.{}.{}", parts[0], forged, parts[2]));
}

#[test]
#[should_panic(expected = "the job is not open")]
fn adversarial_a_paid_job_cannot_pay_twice() {
    let mut c = two_agents();
    ctx("relayer.testnet", NOW);
    let _ = c.release_job("j1".into(), ctoken(&checker("j1", "agent-a.testnet", OUT_A, "c-9")));
    let _ = c.release_job("j1".into(), ctoken(&checker("j1", "agent-a.testnet", OUT_A, "c-10")));
}

#[test]
#[should_panic(expected = "only an agent that took the job submits")]
fn adversarial_submitting_without_taking_is_refused() {
    let mut c = with_checker();
    open(&mut c, "j1");
    ctx("agent-c.testnet", NOW);
    c.submit("j1".into(), OUT_A.into());
}

#[test]
#[should_panic(expected = "the payer cannot take its own job")]
fn adversarial_the_payer_cannot_take_its_own_job() {
    let mut c = with_checker();
    open(&mut c, "j1");
    ctx("payer.testnet", NOW);
    c.take("j1".into());
}

#[test]
#[should_panic(expected = "the deadline has passed: only a refund is possible")]
fn adversarial_no_release_after_the_deadline() {
    let mut c = two_agents();
    ctx("relayer.testnet", NOW + 3601);
    let _ = c.release_job("j1".into(), ctoken(&checker("j1", "agent-a.testnet", OUT_A, "c-11")));
}

#[test]
fn after_the_deadline_the_bid_goes_back_to_the_payer() {
    let mut c = two_agents();
    ctx("anyone.testnet", NOW + 3601);
    let _ = c.refund_job("j1".into());
    assert_eq!(c.get_job("j1".into()).unwrap().state, JobState::Refunding);
}

#[test]
#[should_panic(expected = "the deadline has not passed")]
fn adversarial_no_refund_before_the_deadline() {
    let mut c = two_agents();
    ctx("payer.testnet", NOW);
    let _ = c.refund_job("j1".into());
}

#[test]
#[should_panic(expected = "only an owner changes the key set")]
fn adversarial_a_stranger_cannot_set_a_checker_key() {
    let mut c = contract();
    ctx("mallory.testnet", NOW);
    c.propose_checker_key("ck9".into(), Some(n_hex(&keys().1)));
}

#[test]
fn one_owner_alone_does_not_set_a_checker_key() {
    let mut c = contract();
    ctx(accounts(0).as_str(), NOW);
    let s = c.propose_checker_key("ck1".into(), Some(n_hex(&keys().1)));
    assert!(s.contains("waiting for a second owner"));
}

// ---- budgets ------------------------------------------------------------------------------------------------------

fn budget(c: &mut Knos, agent: &str, cap: u128, amount: u128) {
    ctx(USDC, NOW);
    let msg = serde_json::json!({"budget": {"agent": agent, "cap": cap.to_string()}}).to_string();
    let _ = c.ft_on_transfer(acct("owner.testnet"), U128(amount), msg);
}

#[test]
fn a_spend_under_the_cap_is_paid_from_the_budget() {
    let mut c = with_checker();
    budget(&mut c, "agent-b.testnet", 1, 5);
    ctx("agent-b.testnet", NOW);
    let _ = c.spend(acct("shop.testnet"), U128(1));
    let b = c.get_budget(acct("agent-b.testnet")).unwrap();
    assert_eq!((b.spent.0, b.balance.0, b.cap.0), (1, 4, 1));
}

#[test]
#[should_panic(expected = "over the spend cap: 0 spent, 2 asked, cap 1")]
fn adversarial_a_spend_over_the_cap_is_refused() {
    let mut c = with_checker();
    budget(&mut c, "agent-b.testnet", 1, 5);
    ctx("agent-b.testnet", NOW);
    let _ = c.spend(acct("shop.testnet"), U128(2));
}

#[test]
#[should_panic(expected = "over the spend cap: 1 spent, 1 asked, cap 1")]
fn adversarial_spends_add_up_against_the_cap() {
    let mut c = with_checker();
    budget(&mut c, "agent-b.testnet", 1, 5);
    ctx("agent-b.testnet", NOW);
    let _ = c.spend(acct("shop.testnet"), U128(1));
    let _ = c.spend(acct("shop.testnet"), U128(1));
}

#[test]
#[should_panic(expected = "this agent has no budget")]
fn adversarial_an_account_with_no_budget_cannot_spend() {
    let mut c = with_checker();
    budget(&mut c, "agent-b.testnet", 1, 5);
    ctx("mallory.testnet", NOW);
    let _ = c.spend(acct("mallory.testnet"), U128(1));
}

#[test]
#[should_panic(expected = "this agent's budget belongs to another owner")]
fn adversarial_another_owner_cannot_raise_an_agents_cap() {
    let mut c = with_checker();
    budget(&mut c, "agent-b.testnet", 1, 5);
    ctx(USDC, NOW);
    let msg = serde_json::json!({"budget": {"agent": "agent-b.testnet", "cap": "1000"}}).to_string();
    let _ = c.ft_on_transfer(acct("mallory.testnet"), U128(1), msg);
}

#[test]
#[should_panic(expected = "msg is not a milestone, a job or a budget")]
fn adversarial_a_msg_that_is_none_of_the_three_is_refused() {
    let mut c = with_checker();
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(1), r#"{"pay_me":{}}"#.into());
}

// ---- Round 11: the split, the totals, the spending rules, the rejection record and the model signature ----

fn rules(c: &mut Knos, agent: &str, daily: u128, hold: u128, allow: &[&str]) {
    ctx("owner.testnet", NOW);
    c.set_agent_rules(acct(agent), U128(daily), U128(hold), allow.iter().map(|a| acct(a)).collect());
}

#[test]
fn a_job_opened_since_the_upgrade_is_in_the_totals_and_they_add_up() {
    let c = two_agents();
    let t = c.get_totals();
    assert_eq!(t[USDC]["locked"], "3000000");
    assert_eq!(t[USDC]["open"], "3000000");
    assert_eq!(t[USDC]["conserved"], true);
}

#[test]
fn a_job_funded_in_circle_usdc_is_counted_in_circle_usdc() {
    let mut c = with_checker();
    ctx(CIRCLE_USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(500_000), job_msg("jc", NOW + 3600));
    assert_eq!(c.get_totals()[CIRCLE_USDC]["locked"], "500000");
}

#[test]
#[should_panic(expected = "a budget is funded in the configured USDC")]
fn adversarial_a_budget_in_another_token_is_refused() {
    let mut c = with_checker();
    ctx(CIRCLE_USDC, NOW);
    let msg = serde_json::json!({"budget": {"agent": "agent-b.testnet", "cap": "5"}}).to_string();
    let _ = c.ft_on_transfer(acct("owner.testnet"), U128(5), msg);
}

#[test]
#[should_panic(expected = "over the daily cap: 2 spent today, 2 asked, daily cap 3")]
fn adversarial_a_spend_over_the_daily_cap_is_refused() {
    let mut c = with_checker();
    budget(&mut c, "agent-b.testnet", 10, 10);
    rules(&mut c, "agent-b.testnet", 3, 0, &[]);
    ctx("agent-b.testnet", NOW);
    let _ = c.spend(acct("shop.testnet"), U128(2));
    let _ = c.spend(acct("shop.testnet"), U128(2));
}

#[test]
#[should_panic(expected = "agent-a3.testnet is not on agent-b.testnet's payee allow-list")]
fn adversarial_a_payout_to_a_lookalike_off_the_allow_list_is_refused() {
    let mut c = with_checker();
    budget(&mut c, "agent-b.testnet", 10, 10);
    rules(&mut c, "agent-b.testnet", 0, 0, &["agent-a2.testnet"]);
    ctx("agent-b.testnet", NOW);
    let _ = c.spend(acct("agent-a3.testnet"), U128(1));
}

#[test]
fn a_spend_over_the_hold_line_waits_for_the_approver() {
    let mut c = with_checker();
    budget(&mut c, "agent-b.testnet", 10, 10);
    rules(&mut c, "agent-b.testnet", 0, 2, &[]);
    ctx(accounts(0).as_str(), NOW);
    c.set_approver(acct("approver.testnet"));
    ctx("agent-b.testnet", NOW);
    let _ = c.spend(acct("shop.testnet"), U128(3));
    let h = c.get_hold(U64(0)).unwrap();
    assert_eq!((h.agent, h.amount.0), (acct("agent-b.testnet"), 3));
}

#[test]
#[should_panic(expected = "only the approver releases a held spend")]
fn adversarial_only_the_approver_releases_a_held_spend() {
    let mut c = with_checker();
    budget(&mut c, "agent-b.testnet", 10, 10);
    rules(&mut c, "agent-b.testnet", 0, 2, &[]);
    ctx(accounts(0).as_str(), NOW);
    c.set_approver(acct("approver.testnet"));
    ctx("agent-b.testnet", NOW);
    let _ = c.spend(acct("shop.testnet"), U128(3));
    let _ = c.approve_spend(U64(0));
}

#[test]
#[should_panic(expected = "Knos is paused by an owner: nothing moves but refunds")]
fn adversarial_nothing_is_taken_while_paused() {
    let mut c = with_checker();
    open(&mut c, "j1");
    ctx(accounts(0).as_str(), NOW);
    c.pause(true);
    ctx("agent-a.testnet", NOW);
    c.take("j1".into());
}

#[test]
#[should_panic(expected = "only an owner may")]
fn adversarial_a_stranger_cannot_pause() {
    let mut c = with_checker();
    ctx("mallory.testnet", NOW);
    c.pause(true);
}

#[test]
fn the_payer_records_a_rejected_solution_on_the_agents_record() {
    let mut c = two_agents();
    ctx("payer.testnet", NOW);
    c.record_rejection("j1".into(), acct("agent-b.testnet"), OUT_B.into(), "hard-codes the answer the test checks".into());
    assert_eq!(c.get_agent_record(acct("agent-b.testnet")).rejected, 1);
}

#[test]
#[should_panic(expected = "only the job's payer or an owner records a rejection")]
fn adversarial_a_stranger_cannot_record_a_rejection() {
    let mut c = two_agents();
    ctx("mallory.testnet", NOW);
    c.record_rejection("j1".into(), acct("agent-b.testnet"), OUT_B.into(), "x".into());
}

#[test]
fn the_model_signature_recovers_its_signer() {
    // the example of web3.js eth.accounts.sign("Some data", key) for the address 0x2c7536E3605D9C16a7a3D7b1898e529396a65c23
    ctx("alice", NOW);
    let sig = "0xb91467e570a6466aa9e9876cbcd013baba02900b8979d43fe208a4a4f339f5fd6007e74cd82e037b800186422fc2da167c747ef045e5d18a5f5d4300f8e1a0291c";
    assert_eq!(recover_signer("Some data", sig), "2c7536e3605d9c16a7a3d7b1898e529396a65c23");
}

#[test]
#[should_panic(expected = "is not a NEAR AI signing address the owners added")]
fn adversarial_a_model_signature_from_an_address_not_added_is_refused() {
    let mut c = two_agents();
    let mut cl = checker("j1", "agent-a.testnet", OUT_A, "c-m");
    cl["model_text"] = "Some data".into();
    ctx("relayer.testnet", NOW);
    let sig = "0xb91467e570a6466aa9e9876cbcd013baba02900b8979d43fe208a4a4f339f5fd6007e74cd82e037b800186422fc2da167c747ef045e5d18a5f5d4300f8e1a0291c";
    let _ = c.release_job_verified("j1".into(), ctoken(&cl), "Some data".into(), sig.into());
}

#[test]
fn a_model_signature_from_an_added_address_releases_the_job() {
    let mut c = two_agents();
    ctx(accounts(0).as_str(), NOW);
    c.add_model_signer("0x2c7536E3605D9C16a7a3D7b1898e529396a65c23".into());
    let mut cl = checker("j1", "agent-a.testnet", OUT_A, "c-v");
    cl["model_text"] = "Some data".into();
    ctx("relayer.testnet", NOW);
    let sig = "0xb91467e570a6466aa9e9876cbcd013baba02900b8979d43fe208a4a4f339f5fd6007e74cd82e037b800186422fc2da167c747ef045e5d18a5f5d4300f8e1a0291c";
    let _ = c.release_job_verified("j1".into(), ctoken(&cl), "Some data".into(), sig.into());
    assert_eq!(c.get_job("j1".into()).unwrap().state, JobState::Paying);
}

#[test]
#[should_panic(expected = "the checker's token names another model call")]
fn adversarial_a_signature_for_another_model_call_is_refused() {
    let mut c = two_agents();
    let cl = checker("j1", "agent-a.testnet", OUT_A, "c-w");
    ctx("relayer.testnet", NOW);
    let _ = c.release_job_verified("j1".into(), ctoken(&cl), "Some data".into(), "00".into());
}
