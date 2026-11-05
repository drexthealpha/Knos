//! Open jobs and budgets: two agents take one job, only the one whose output passed the locked test is paid; a budget
//! refuses a payment over its cap. "adversarial" marks the attacks.

use super::*;
use crate::jobs::{JobState, CHECKER_ISS};

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
