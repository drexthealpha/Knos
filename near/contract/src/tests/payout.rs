//! The Solana payout: which messages the contract will have the MPC signer sign, and which it refuses.

use super::*;
use crate::solana;

const DEST: &str = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin";
const OWNER: &str = "8sLbNZoA1cfnvMJLPfp98ZLAnFSYCFApfJKMbiXNLwxj";
const SRC: &str = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU";
const SYSTEM: [u8; 32] = [0; 32];

fn k(s: &str) -> [u8; 32] {
    solana::b58_32(s).unwrap()
}

/// A legacy message: keys [owner, source, destination, mint, program], one instruction over them
fn message(f: impl Fn(&mut Vec<[u8; 32]>, &mut Vec<u8>, &mut Vec<u8>, &mut [u8; 3], &mut usize)) -> Vec<u8> {
    let mut keys = vec![k(OWNER), k(SRC), k(DEST), k(MINT), solana::TOKEN_PROGRAM];
    let mut accts = vec![1u8, 3, 2, 0];
    let mut data = vec![12u8];
    data.extend_from_slice(&5_000_000u64.to_le_bytes());
    data.push(6);
    let mut header = [1u8, 0, 2];
    let mut ixs = 1usize;
    f(&mut keys, &mut accts, &mut data, &mut header, &mut ixs);
    let mut m = header.to_vec();
    m.push(keys.len() as u8);
    keys.iter().for_each(|x| m.extend_from_slice(x));
    m.extend_from_slice(&[7u8; 32]);
    m.push(ixs as u8);
    for _ in 0..ixs {
        m.push(4);
        m.push(accts.len() as u8);
        m.extend_from_slice(&accts);
        m.push(data.len() as u8);
        m.extend_from_slice(&data);
    }
    m
}

fn std_b64(m: &[u8]) -> String {
    base64::engine::general_purpose::STANDARD.encode(m)
}

/// A milestone paid on Solana, funded and released
fn released() -> Knos {
    let mut c = contract();
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(5_000_000), fund_msg("s", "solana", DEST, NOW + 3600));
    release(&mut c, "s", &token("j-sol"));
    c
}

fn sign(c: &mut Knos, msg: String) {
    ctx("relayer.testnet", NOW);
    let _ = c.sign_payout("s".into(), msg);
}

macro_rules! refused_payout {
    ($name:ident, $why:literal, $msg:expr) => {
        #[test]
        #[should_panic(expected = $why)]
        fn $name() {
            let mut c = released();
            sign(&mut c, $msg);
        }
    };
}

#[test]
fn the_token_program_constant_is_tokenkeg() {
    assert_eq!(solana::b58_32("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"), Some(solana::TOKEN_PROGRAM));
}

#[test]
fn base58_refuses_a_letter_outside_its_alphabet() {
    assert_eq!(solana::b58_32("0OIl"), None);
}

#[test]
fn the_exact_transfer_is_sent_to_the_signer() {
    let mut c = released();
    sign(&mut c, good_std());
    let p = c.get_payout("s".into()).unwrap();
    assert!(p.signing && p.signature.is_none());
}

#[test]
fn the_signers_answer_is_kept() {
    let mut c = released();
    sign(&mut c, good_std());
    ctx(CONTRACT, NOW);
    c.on_payout_signed("s".into(), Ok(serde_json::json!({"scheme": "Ed25519", "signature": [1, 2, 3]})));
    assert!(c.get_payout("s".into()).unwrap().signature.unwrap().contains("Ed25519"));
}

#[test]
fn a_signer_that_did_not_answer_leaves_the_payout_open() {
    let mut c = released();
    sign(&mut c, good_std());
    ctx(CONTRACT, NOW);
    c.on_payout_signed("s".into(), Err(PromiseError::Failed));
    let p = c.get_payout("s".into()).unwrap();
    assert!(!p.signing && p.signature.is_none());
    sign(&mut c, good_std());
    assert!(c.get_payout("s".into()).unwrap().signing);
}

fn good_std() -> String {
    raw(|_, _, _, _, _| {})
}

/// The same message as `message`, in standard base64
fn raw(f: impl Fn(&mut Vec<[u8; 32]>, &mut Vec<u8>, &mut Vec<u8>, &mut [u8; 3], &mut usize)) -> String {
    std_b64(&message(f))
}

refused_payout!(adversarial_a_payout_to_another_account, "another account", raw(|keys, _, _, _, _| keys[2] = k(SRC)));
refused_payout!(adversarial_a_payout_in_another_mint, "another mint", raw(|keys, _, _, _, _| keys[3] = k(SRC)));
refused_payout!(adversarial_a_payout_of_another_amount, "another amount", raw(|_, _, data, _, _| data[1..9].copy_from_slice(&5_000_001u64.to_le_bytes())));
refused_payout!(adversarial_a_payout_of_a_smaller_amount, "another amount", raw(|_, _, data, _, _| data[1..9].copy_from_slice(&1u64.to_le_bytes())));
refused_payout!(adversarial_a_second_instruction, "one instruction", raw(|_, _, _, _, ixs| *ixs = 2));
refused_payout!(adversarial_a_system_program_transfer, "SPL Token transfer", raw(|keys, _, _, _, _| keys[4] = SYSTEM));
refused_payout!(adversarial_a_plain_transfer_not_checked, "TransferChecked", raw(|_, _, data, _, _| data[0] = 3));
refused_payout!(adversarial_an_approve_instruction, "TransferChecked", raw(|_, _, data, _, _| data[0] = 4));
refused_payout!(adversarial_a_versioned_message, "legacy Solana message", {
    let mut m = message(|_, _, _, _, _| {});
    m.insert(0, 0x80);
    std_b64(&m)
});
refused_payout!(adversarial_two_signers, "one signer", raw(|_, _, _, h, _| h[0] = 2));
refused_payout!(adversarial_an_owner_that_is_not_the_signer, "owner must be its signer", raw(|_, accts, _, _, _| accts[3] = 1));
refused_payout!(adversarial_bytes_after_the_instruction, "message", {
    let mut m = message(|_, _, _, _, _| {});
    m.push(0);
    std_b64(&m)
});
refused_payout!(adversarial_a_cut_message, "message", {
    let m = message(|_, _, _, _, _| {});
    std_b64(&m[..m.len() - 4])
});
refused_payout!(adversarial_a_message_that_is_not_base64, "message_b64", "***".to_string());
refused_payout!(adversarial_a_message_over_1232_bytes, "longer than 1232", std_b64(&[1u8; 1300]));

#[test]
#[should_panic(expected = "is being signed")]
fn adversarial_a_second_signature_while_the_first_is_asked() {
    let mut c = released();
    sign(&mut c, good_std());
    sign(&mut c, good_std());
}

#[test]
#[should_panic(expected = "already signed")]
fn adversarial_a_second_signature_after_the_first() {
    let mut c = released();
    sign(&mut c, good_std());
    ctx(CONTRACT, NOW);
    c.on_payout_signed("s".into(), Ok(serde_json::json!({"signature": [1]})));
    sign(&mut c, good_std());
}

#[test]
#[should_panic(expected = "not released")]
fn adversarial_a_payout_before_the_release() {
    let mut c = contract();
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(5_000_000), fund_msg("s", "solana", DEST, NOW + 3600));
    sign(&mut c, good_std());
}

#[test]
#[should_panic(expected = "not paid on Solana")]
fn adversarial_a_solana_payout_for_a_near_milestone() {
    let mut c = contract();
    fund(&mut c, "s");
    release(&mut c, "s", &token("j-near"));
    sign(&mut c, good_std());
}

#[test]
#[should_panic(expected = "no such milestone")]
fn adversarial_a_payout_for_an_unknown_milestone() {
    let mut c = released();
    ctx("relayer.testnet", NOW);
    let _ = c.sign_payout("nope".into(), good_std());
}

#[test]
#[should_panic(expected = "needs payee_mint")]
fn adversarial_a_solana_payee_without_a_mint() {
    let mut c = contract();
    ctx(USDC, NOW);
    let msg = fund_msg("s", "solana", DEST, NOW + 3600).replace(&format!(",\"payee_mint\":\"{MINT}\""), "");
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(5), msg);
}

#[test]
#[should_panic(expected = "payee address")]
fn adversarial_a_solana_payee_that_is_not_an_address() {
    let mut c = contract();
    ctx(USDC, NOW);
    let _ = c.ft_on_transfer(acct("payer.testnet"), U128(5), fund_msg("s", "solana", "not-base58-0OIl", NOW + 3600));
}
