//! PAY AFTER PROOF FROM ANY SOURCE (0.3.34). Until this build every work order was judged by a forge: a workflow at a
//! pinned commit, run on GitHub or gitlab.com (order_judge.rs). This file adds two judges that are not forges. The
//! funder fixes one when he funds the order, and it is stored in the order's spare bytes (O_JUDGE, O_PIN): zero in
//! every order of an earlier build, which therefore pays, refunds and is judged exactly as before. No instruction
//! number is new: these ride on FundOrderWallet (15), PayOrder (17) and RefundOrder (22), as written below.
//!
//!   ATTESTED  a container image, by its digest. PayOrder (17, the same accounts) pays it on a Google Confidential
//!             Space attestation token (cs.rs) whose `submods.container.image_digest` is the pinned image and whose
//!             audience is knos3:proof:<order>:<evidence sha256 hex>:<terms hash hex>:<payees>. The image is the
//!             judge: it reads the evidence, runs the sealed tests or the analysis, and asks for the token only when
//!             the terms hold. Whose Google Cloud project ran it does not matter.
//!   PANEL     m of n referee keys (Ed25519), for evidence no issuer signs: a paper, a dataset, a lab's files. The
//!             order pins sha256("knos3:panel" || m || n || the n keys). Each referee signs the VERDICT DIGEST
//!               sha256("knos3:verdict" || program id || order || the order's stamp i64 LE || terms hash || evidence || verdict)
//!             where `verdict` is the payees text for a PASS and the four bytes "FAIL" for a FAIL (no payees text is
//!             "FAIL": it has no dot). The signatures are checked by Solana's Ed25519 precompile in the same
//!             transaction and read here by instruction introspection (issuers::ed25519). Each distinct panel key
//!             counts once; signatures may arrive in several transactions, recorded in the verdict's tally
//!             ["vd", order, digest] until m distinct referees have signed; the transaction that brings the m-th
//!             pays (PASS) or refunds (FAIL). The digest names the order's address AND its stamp (state::stamp,
//!             different for every funding of one address), so a verdict for one order pays no other order, and none
//!             funded later at the same address. Payees are GitHub ids or ORCID iDs (issuers::payees_any).
//!
//! HOW EACH IS SENT
//!   Funding      FundOrderWallet (15) with options byte 35 = 1 (ATTESTED) or 2 (PANEL), `wf_repo` = the pin (the
//!                image digest, or the panel's hash) and `wf_sha` forty '0' characters, mode 1. The order stores zero
//!                bytes as its workflows repository (no forge token's pin is ever zero: it is sha256 of a name), the
//!                pin in O_PIN. Every other option must be zero but the presentation grace (`order::opts_of`). The
//!                program cannot see the panel's keys at funding (only their hash): a panel that cannot sign leaves the
//!                order to RefundOrder at its deadline.
//!   ATTESTED     PayOrder (17), no data, the Confidential Space token account and the key that verified it in the
//!                token's and the key's places.
//!   PANEL, PASS  PayOrder (17) WITH data: m u8, n u8, keys [n][32], evidence [32], payees text. The token's place
//!                holds the instructions sysvar, the key's place the verdict's tally (w); `used` is not read. Then the
//!                payees' accounts as for any payment.
//!   PANEL, FAIL  RefundOrder (22) WITH data: m u8, n u8, keys [n][32], evidence [32]. After its eight accounts:
//!                the instructions sysvar, the system program, the verdict's tally (w); the relayer is writable (it pays
//!                the tally's rent). At m: everything the order holds goes back to the funding wallet now.
//!                After the deadline RefundOrder with no data needs no signature: the funder gets his money back on
//!                a FAIL or on expiry.
//!   Refusals     E_CLAIMS: no signature over this digest by a key of this panel, another panel than the pinned one,
//!                or the verdict path on an order that is not PANEL; E_REPLAY: every signer is counted already;
//!                E_STATE: not OPEN, past the deadline, or in the funding's slot.
//!
//! WHAT THE FUNDER CANNOT ADD to such an order: a forge judge, a quorum, a neutral run, a standing rate, AUTO, a
//! holdback (a revert needs a forge judge), a kill fee or a reservation (a command needs one), an arbiter, a judge
//! repository, privacy salt. Only the presentation grace (ATTESTED: a token issued by the deadline). A Balance funds
//! none (FundOrderBalance refuses byte 35). Money is the same as any wallet's order.
//! LOGS: knos3:judge order= kind= pin=   knos3:proof order= evidence= image=   knos3:verdict order= verdict= evidence= have= of=
use crate::{err, issuers::{self, Family}, order::*, order_pay::{pay_or_hold, Judge, Payout}, state::*, token::*, *};
use solana_program::{account_info::AccountInfo, entrypoint::ProgramResult, hash::hashv, msg, program_error::ProgramError, pubkey::Pubkey,
                     system_program, sysvar::instructions};

/// O_JUDGE: who judges the order. FORGE (0) is every order of an earlier build.
pub const FORGE: u8 = 0;
pub const ATTESTED: u8 = 1;
pub const PANEL: u8 = 2;
/// In the order's spare bytes (state.rs O_RESERVED, zero in every order of an earlier build).
pub const O_JUDGE: usize = O_RESERVED;          // u8
pub const O_PIN: usize = O_RESERVED + 8;        // [32]: the image digest, or the panel's hash
pub const MAX_REFEREES: usize = 10;

// The tally of one verdict ["vd", order, digest]: 80 bytes, a length no other account of this program has.
pub const V_PAYER: usize = 0;       // who paid its rent: CloseMarker gives it back
pub const V_ORDER: usize = 32;
pub const V_INC: usize = 64;        // u64: the incarnation (O_INC) of the order it counts for
pub const V_BITS: usize = 72;       // u32: which panel keys (by their place in the panel) have signed
pub const VOTE_LEN: usize = 80;
/// The verdict text of a FAIL: what the referees sign in the payees' place.
pub const FAIL: &[u8] = b"FAIL";

const _: [(); 0 - !(O_PIN + 32 <= ORDER_LEN && O_RESERVED + 64 == ORDER_LEN) as usize] = [];   // compile-time layout check

/// The judge byte of an order account (already loaded by load_order).
pub fn judge_kind(order: &AccountInfo) -> Result<u8, ProgramError> { Ok(order.try_borrow_data()?[O_JUDGE]) }
fn pin_of(order: &AccountInfo) -> Result<[u8; 32], ProgramError> { Ok(order.try_borrow_data()?[O_PIN..O_PIN + 32].try_into().unwrap()) }

/// HOOK of FundOrderWallet, once the order is held: a judged order records its judge and its pin, and logs them.
pub fn judged(order: &AccountInfo, kind: u8, pin: &[u8]) -> ProgramResult {
    let mut d = order.try_borrow_mut_data()?;
    d[O_JUDGE] = kind;
    d[O_PIN..O_PIN + 32].copy_from_slice(pin);
    let mut hex = [0u8; 64];
    knos_oidc::claims::hex_into(pin, &mut hex);
    msg!("knos3:judge order={} kind={} pin={}", b58(order.key), kind, core::str::from_utf8(&hex).unwrap());
    Ok(())
}

/// sha256("knos3:panel" || m || n || keys): what a PANEL order pins.
pub fn panel_pin(m: u8, keys: &[[u8; 32]]) -> [u8; 32] {
    let n = [keys.len() as u8];
    let mut v: Vec<&[u8]> = vec![b"knos3:panel", core::slice::from_ref(&m), &n];
    for k in keys { v.push(k); }
    hashv(&v).to_bytes()
}

/// A panel as data carries it: m u8, n u8, then n keys. Returns (m, keys, the bytes after them).
#[allow(clippy::type_complexity, clippy::manual_contains)] pub fn panel_of(d: &[u8]) -> Result<(u8, Vec<[u8; 32]>, &[u8]), ProgramError> {
    let bad = || ProgramError::InvalidInstructionData;
    let (&m, rest) = d.split_first().ok_or_else(bad)?;
    let (&n, rest) = rest.split_first().ok_or_else(bad)?;
    let n = n as usize;
    if rest.len() < 32 * n { return Err(bad()); }
    let keys: Vec<[u8; 32]> = rest[..32 * n].chunks(32).map(|c| c.try_into().unwrap()).collect();
    if m == 0 || m as usize > n || n > MAX_REFEREES || keys.iter().any(|k| *k == [0u8; 32])
        || keys.iter().enumerate().any(|(i, k)| keys[..i].contains(k)) { return Err(err(E_TERMS)); }
    Ok((m, keys, &rest[32 * n..]))
}

/// What the referees sign: sha256("knos3:verdict" || program id || order || stamp i64 LE || terms || evidence || verdict).
pub fn verdict_digest(program_id: &Pubkey, order: &Pubkey, stamp: i64, terms: &[u8; 32], evidence: &[u8; 32], verdict: &[u8]) -> [u8; 32] {
    hashv(&[b"knos3:verdict", program_id.as_ref(), order.as_ref(), &stamp.to_le_bytes(), terms, evidence, verdict]).to_bytes()
}

/// PayOrder (17) on an ATTESTED order, everything before the token's marker: the Confidential Space token is fresh,
/// its key usable, it is a production container in a TEE of the pinned image, issued in time, and its audience names
/// this order and its terms. Returns the payees it names.
pub fn attested(o: &Order, order: &AccountInfo, tok: &AccountInfo, key: &AccountInfo, now: i64) -> Result<Vec<crate::order_pay::Payee>, ProgramError> {
    let c = issuers::checked(tok, key, now, |_, f, _| f == Family::ConfidentialSpace, |_, payload, exp| crate::cs::read(payload, exp, now))?;
    if o.state != OPEN || !o.in_time(c.iat, now) || c.iat < o.not_before { return Err(err(E_STATE)); }
    if c.image_digest != pin_of(order)? { return Err(err(E_WORKFLOW)); }
    let (named, evidence, terms, list) = issuers::proof_aud(&c.aud)?;
    if named != *order.key || terms != o.terms { return Err(err(E_AUD)); }
    let payees = issuers::payees_any(list)?;
    let (mut e, mut i) = ([0u8; 64], [0u8; 64]);
    knos_oidc::claims::hex_into(&evidence, &mut e);
    knos_oidc::claims::hex_into(&c.image_digest, &mut i);
    msg!("knos3:proof order={} evidence={} image=sha256:{}", b58(order.key), core::str::from_utf8(&e).unwrap(), core::str::from_utf8(&i).unwrap());
    Ok(payees)
}

/// Which panel keys (bit k: keys[k]) signed `digest` in an Ed25519 precompile instruction of this transaction.
fn signed_in_tx(ixs: &AccountInfo, keys: &[[u8; 32]], digest: &[u8; 32]) -> Result<u32, ProgramError> {
    let mut bits = 0u32;
    let count = { let d = ixs.try_borrow_data()?; u16::from_le_bytes([d[0], d[1]]) as usize };
    for i in 0..count {
        let ix = instructions::load_instruction_at_checked(i, ixs)?;
        if ix.program_id != issuers::ED25519_ID { continue; }
        for (key, msg) in issuers::ed25519(&ix.data) {
            if msg != &digest[..] { continue; }
            if let Some(k) = keys.iter().position(|p| *p == key) { bits |= 1 << k; }
        }
    }
    Ok(bits)
}

/// What both verdict paths check before they count: the relayer signs and pays, `ixs` is the instructions sysvar,
/// the order is a PANEL order, OPEN, by its deadline, not in its funding's slot, and the panel in the data is the
/// pinned one. Returns the order, m, the keys, the evidence and the rest of the data after it.
#[allow(clippy::type_complexity)]
fn panel_order<'d>(program_id: &Pubkey, relayer: &AccountInfo, ixs: &AccountInfo, order: &AccountInfo, data: &'d [u8], now: i64)
                   -> Result<(Order, u8, Vec<[u8; 32]>, [u8; 32], &'d [u8]), ProgramError> {
    if !relayer.is_signer || !relayer.is_writable || *ixs.key != instructions::ID { return Err(err(E_ACCOUNTS)); }
    let o = load_order(program_id, order)?;
    if judge_kind(order)? != PANEL { return Err(err(E_CLAIMS)); }
    if o.state != OPEN || now > o.deadline { return Err(err(E_STATE)); }
    o.settled()?;
    let (m, keys, rest) = panel_of(data)?;
    if panel_pin(m, &keys) != pin_of(order)? { return Err(err(E_CLAIMS)); }
    if rest.len() < 32 { return Err(ProgramError::InvalidInstructionData); }
    Ok((o, m, keys, rest[..32].try_into().unwrap(), &rest[32..]))
}

/// THE TALLY. Counts the distinct panel keys that signed `digest` in this transaction, with those the tally
/// ["vd", order, digest] already holds for this funding. E_CLAIMS: none in this transaction; E_REPLAY: none new.
/// Below m the tally is written (its rent from `relayer`) and false is returned; at m, true.
#[allow(clippy::too_many_arguments)]
fn tally<'a>(program_id: &Pubkey, relayer: &AccountInfo<'a>, ixs: &AccountInfo<'a>, order: &AccountInfo<'a>, vote: &AccountInfo<'a>, sys: &AccountInfo<'a>,
             o: &Order, m: u8, keys: &[[u8; 32]], digest: &[u8; 32], evidence: &[u8; 32], word: &str) -> Result<bool, ProgramError> {
    let new = signed_in_tx(ixs, keys, digest)?;
    if new == 0 { return Err(err(E_CLAIMS)); }
    let (vk, vbump) = Pubkey::find_program_address(&[b"vd", order.key.as_ref(), digest], program_id);
    if *vote.key != vk { return Err(err(E_ACCOUNTS)); }
    let before = if vote.owner == program_id {
        let d = vote.try_borrow_data()?;
        if d.len() != VOTE_LEN { return Err(err(E_ACCOUNTS)); }
        if u64_at(&d, V_INC) == o.inc { u32_at(&d, V_BITS) } else { 0 }
    } else { 0 };
    if new & !before == 0 { return Err(err(E_REPLAY)); }
    let all = new | before;
    let have = all.count_ones() as u8;
    let mut e = [0u8; 64];
    knos_oidc::claims::hex_into(evidence, &mut e);
    msg!("knos3:verdict order={} verdict={} evidence={} have={} of={}", b58(order.key), word, core::str::from_utf8(&e).unwrap(), have, m);
    if have >= m { return Ok(true); }
    if vote.owner != program_id {
        if !vote.data_is_empty() || *vote.owner != system_program::ID { return Err(err(E_ACCOUNTS)); }
        create_pda(relayer, vote, sys, program_id, VOTE_LEN, &[b"vd", order.key.as_ref(), digest, &[vbump]])?;
        put_key(&mut vote.try_borrow_mut_data()?, V_PAYER, relayer.key);
    }
    let mut v = vote.try_borrow_mut_data()?;
    put_key(&mut v, V_ORDER, order.key); put_u64(&mut v, V_INC, o.inc); put_u32(&mut v, V_BITS, all);
    Ok(false)
}

/// PayOrder (17) with data: a PANEL order's PASS. See the module documentation for the accounts.
pub fn pay_order_verdict(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, ixs, vote, order, ov, tip_tok, fee_tok, auth, rent_to, mint, token, sys, ata_program, _used] = take(accounts)?;
    let per = &accounts[14..];
    let (o, m, keys, evidence, list) = panel_order(program_id, relayer, ixs, order, data, now)?;
    let payees = issuers::payees_any(list)?;
    let digest = verdict_digest(program_id, order.key, o.stamp(), &o.terms, &evidence, list);
    if !tally(program_id, relayer, ixs, order, vote, sys, &o, m, &keys, &digest, &evidence, "PASS")? { return Ok(()); }
    pay_or_hold(program_id, &Payout { relayer, order, ov, tip_tok, fee_tok, auth, rent_to, mint, token, sys, ata_program }, &o, per, &payees, Judge::Panel, 0, now)
}

/// RefundOrder (22) with data: a PANEL order's FAIL. See the module documentation for the accounts.
pub fn refund_order_verdict(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, order, ov, refund_tok, auth, rent_to, mint, token, ixs, sys, vote] = take(accounts)?;
    let (o, m, keys, evidence, rest) = panel_order(program_id, relayer, ixs, order, data, now)?;
    if !rest.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    let digest = verdict_digest(program_id, order.key, o.stamp(), &o.terms, &evidence, FAIL);
    if !tally(program_id, relayer, ixs, order, vote, sys, &o, m, &keys, &digest, &evidence, "FAIL")? { return Ok(()); }
    if *rent_to.key != o.rent_to { return Err(err(E_ACCOUNTS)); }
    let (mm, bump) = order_accounts(program_id, &o, order.key, ov, auth, mint, token)?;
    if !is_owned(refund_tok, token.key, &o.mint, &o.refund_to) { return Err(err(E_PAYEE)); }
    let amount = amount_of(ov, token.key, E_ACCOUNTS)?;
    if amount > 0 { transfer(token, ov, mint, refund_tok, auth, amount, mm.decimals, Some(bump))?; }
    msg!("knos3:refunded order={} amount={}", b58(order.key), amount);
    close_token(token, ov, rent_to, auth, bump)?;
    close(order, rent_to)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_panel_is_one_to_ten_distinct_keys_and_its_pin_and_digest_name_everything_they_cover() {
        let key = |b: u8| [b; 32];
        let data = |m: u8, keys: &[[u8; 32]]| { let mut d = vec![m, keys.len() as u8]; for k in keys { d.extend_from_slice(k); } d.extend_from_slice(b"tail"); d };
        let three = data(2, &[key(1), key(2), key(3)]);
        let (m, keys, rest) = panel_of(&three).ok().unwrap();
        assert_eq!((m, keys.len(), rest), (2, 3, &b"tail"[..]));
        for bad in [data(0, &[key(1)]), data(2, &[key(1)]), data(1, &[key(1), key(1)]), data(1, &[key(0)]), data(1, &(1..=11).map(key).collect::<Vec<_>>())] {
            assert!(panel_of(&bad).err() == Some(err(E_TERMS)));
        }
        assert!(panel_of(&[1, 2, 1]).is_err());
        let p = panel_pin(2, &keys);
        assert!(p != panel_pin(3, &keys) && p != panel_pin(2, &keys[..2]) && p != panel_pin(2, &[key(2), key(1), key(3)]));
        let (prog, a, b) = (Pubkey::new_from_array([1; 32]), Pubkey::new_from_array([2; 32]), Pubkey::new_from_array([3; 32]));
        let d = verdict_digest(&prog, &a, -5, &[7; 32], &[8; 32], b"5.10000.-");
        for other in [verdict_digest(&prog, &b, -5, &[7; 32], &[8; 32], b"5.10000.-"), verdict_digest(&prog, &a, -6, &[7; 32], &[8; 32], b"5.10000.-"),
                      verdict_digest(&prog, &a, -5, &[9; 32], &[8; 32], b"5.10000.-"), verdict_digest(&prog, &a, -5, &[7; 32], &[9; 32], b"5.10000.-"),
                      verdict_digest(&prog, &a, -5, &[7; 32], &[8; 32], b"6.10000.-"), verdict_digest(&b, &a, -5, &[7; 32], &[8; 32], b"5.10000.-"),
                      verdict_digest(&prog, &a, -5, &[7; 32], &[8; 32], FAIL)] {
            assert_ne!(d, other);
        }
        // a FAIL is never a payees text, so a PASS and a FAIL never share a digest
        assert!(crate::issuers::payees_any(FAIL).is_err());
        const { assert!(O_JUDGE > O_GRACE && VOTE_LEN == V_BITS + 8) };
    }
}
