//! Money leaving a work order (2.1): PayOrder (to its payees, on a judge's signed token), SettleOrder (a held order,
//! once its payee has a wallet), RefundOrder (back to its funder after the deadline).
//!
//! Tokens leave an order's account ["ov", order] only by these transfers, each a TransferChecked in the order's mint:
//!   -> a token account of each payee's wallet     PayOrder, SettleOrder: that payee's share of the amount, whole
//!   -> a token account of the relayer             PayOrder, SettleOrder: the tip, out of the fee
//!   -> a token account of FEE_OWNER               PayOrder, SettleOrder: the rest of the fee
//!   -> where the order's money came from          RefundOrder: everything the account holds
//! The last payment and a refund empty the account, close it and close the order, both rents back to `rent_to`.
//! Tokens someone sent to an order's account directly go with the fee (the last payment) or with the refund, so
//! nobody can stop an order from closing by sending it dust.
//!
//! HOOKS for what is built on top of this file, each marked `HOOK`: `judge_ok` (judges b, c, d), `due_now` and
//! `not_yet` (standing orders, the holdback), `after_pay` (the holdback's side account, the done marker), and
//! `refund_first` (the kill fee).
use crate::{err, gh::*, order::*, pay::{bound, record, Paid}, state::*, token::*, *};
use knos_oidc::claims::{self, parts};
use solana_program::{account_info::AccountInfo, entrypoint::ProgramResult, msg, program_error::ProgramError, pubkey::Pubkey, system_program};

/// Who signed a pay token, of the four the design allows.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Judge { Own = 0, Neutral = 1, Private = 2, Arbiter = 3 }

/// HOOK. Which judge signed this token for this order, or a refusal. Always: the workflow is in the order's pinned
/// repository at the order's pinned commit, and the run is a first attempt (`github` has already required a
/// GitHub-hosted runner). Then one of the judges the design allows: the rule is order_judge.rs.
pub fn judge_ok(o: &Order, g: &Gh) -> Result<Judge, ProgramError> { crate::order_judge::judge(o, g) }

/// HOOK. What one accepted token pays: all that is left of the amount; a STANDING order's rate; with a holdback,
/// what is left less the holdback (order_terms.rs).
pub fn due_now(o: &Order) -> u64 { crate::order_terms::due_now(o) }

/// HOOK. What is refused before any money moves (order_terms.rs): an order that is both STANDING and has a holdback
/// (E_LATER: its money waits and goes back at the deadline), and a payee without a wallet on a STANDING order or one
/// with a holdback (those are never held). `per`: the accounts after PayOrder's thirteen.
pub fn not_yet(program_id: &Pubkey, o: &Order, payees: &[Payee], per: &[AccountInfo]) -> ProgramResult {
    crate::order_terms::not_yet(program_id, o, payees, per)
}

/// HOOK. Called after the payees, the tip and the fee of one payment were sent and `paid` was raised, before the
/// order is closed when nothing is left. `paid`: the order's `paid` after this payment. order_terms.rs marks a
/// standing order's pull request, records a holdback and starts its warranty, and ends a paid taker's reservation.
#[allow(clippy::too_many_arguments)]
fn after_pay<'a>(program_id: &Pubkey, a: &Payout<'a, '_>, o: &Order, per: &[AccountInfo<'a>], payees: &[Payee], wallets: &[Pubkey], pr: u64, paid: u64,
                 now: i64) -> ProgramResult {
    crate::order_terms::after_pay(program_id, a.relayer, a.order, a.sys, o, per, payees, wallets, pr, paid, now)
}

/// HOOK. Called by RefundOrder before the money goes back: pays the kill fee of an order cancelled while reserved
/// (order_terms.rs). Returns true when the order must stay open: the kill fee is held in it for a taker without a
/// wallet, and everything else has already gone back.
pub fn refund_first<'a>(program_id: &Pubkey, o: &Order, accounts: &[AccountInfo<'a>], m: &Mint, bump: u8, now: i64) -> Result<bool, ProgramError> {
    crate::order_terms::refund_first(program_id, o, accounts, m, bump, now)
}

/// One payee of a pay token: a GitHub id, its share in basis points, and the address the token carries for it.
pub struct Payee { pub id: u64, pub bps: u64, pub address: Option<Pubkey> }
/// knos3:pay:<order address>:<head sha>:<terms hash hex>:<mode>:<pr>:<payees>
/// `payees`: 1..=4 entries `id.bps.address` joined by `,`; the shares add up to 10000; `address` is a wallet as
/// Solana prints it, or `-` (the id's bound wallet; with none, the order is held for the id).
pub struct PayAud { pub order: Pubkey, pub terms: [u8; 32], pub mode: u8, pub pr: u64, pub payees: Vec<Payee> }
pub fn pay_order_aud(aud: &[u8]) -> Result<PayAud, ProgramError> {
    let bad = || err(E_AUD);
    let [k, p, order, head, terms, mode, pr, list] = parts::<8>(aud).ok_or_else(bad)?;
    if k != b"knos3" || p != b"pay" || !claims::is_hex(head, 40) || (mode != b"0" && mode != b"1") { return Err(bad()); }
    Ok(PayAud { order: Pubkey::new_from_array(claims::b58_32(order).ok_or_else(bad)?), terms: claims::unhex32(terms).ok_or_else(bad)?,
                mode: mode[0] - b'0', pr: n(pr)?, payees: payees_of(list)? })
}
/// The payees of an audience: between 1 and MAX_PAYEES, each id once and not 0, each share at least 1, 10000 in all.
pub fn payees_of(list: &[u8]) -> Result<Vec<Payee>, ProgramError> {
    let bad = || err(E_AUD);
    let mut out: Vec<Payee> = Vec::with_capacity(MAX_PAYEES);
    for entry in list.split(|&c| c == b',') {
        let mut it = entry.split(|&c| c == b'.');
        let (Some(id), Some(bps), Some(address), None) = (it.next(), it.next(), it.next(), it.next()) else { return Err(bad()) };
        let (id, bps) = (n(id)?, n(bps)?);
        let address = if address == b"-" { None } else { Some(Pubkey::new_from_array(claims::b58_32(address).ok_or_else(bad)?)) };
        if out.len() == MAX_PAYEES || id == 0 || bps == 0 || bps > 10_000 || out.iter().any(|p| p.id == id) { return Err(bad()); }
        out.push(Payee { id, bps, address });
    }
    if out.iter().map(|p| p.bps).sum::<u64>() != 10_000 { return Err(bad()); }
    Ok(out)
}

/// The accounts of a payment that every payee shares, as PayOrder and SettleOrder list them.
struct Payout<'a, 'b> {
    relayer: &'b AccountInfo<'a>, order: &'b AccountInfo<'a>, ov: &'b AccountInfo<'a>, tip_tok: &'b AccountInfo<'a>, fee_tok: &'b AccountInfo<'a>,
    auth: &'b AccountInfo<'a>, rent_to: &'b AccountInfo<'a>, mint: &'b AccountInfo<'a>, token: &'b AccountInfo<'a>, sys: &'b AccountInfo<'a>,
    ata_program: &'b AccountInfo<'a>,
}
/// The five accounts of one payee, in this order: bind, wallet, dest_token, rep, pair.
const PER_PAYEE: usize = 5;

/// Pays `due` of an order to its payees, each to a token account of the wallet resolved for it (`wallets`, in the
/// payees' order), the tip to the relayer and the rest of the fee to FEE_OWNER; records each payment; closes the
/// order and its token account when the whole amount is paid.
#[allow(clippy::too_many_arguments)]
fn pay_out<'a>(program_id: &Pubkey, a: &Payout<'a, '_>, o: &Order, per: &[AccountInfo<'a>], payees: &[Payee], wallets: &[Pubkey], due: u64,
               judge: Option<Judge>, pr: u64, now: i64) -> ProgramResult {
    if *a.rent_to.key != o.rent_to { return Err(err(E_ACCOUNTS)); }
    let (m, bump) = order_accounts(program_id, o, a.order.key, a.ov, a.auth, a.mint, a.token)?;
    // the tip goes to a token account of whoever signed and paid for this transaction, the fee to FEE_OWNER's
    if !is_owned(a.tip_tok, a.token.key, &o.mint, a.relayer.key) || !is_owned(a.fee_tok, a.token.key, &o.mint, &FEE_OWNER) || a.relayer.key == a.auth.key {
        return Err(err(E_PAYEE));
    }
    let paid = o.paid.checked_add(due).filter(|p| due > 0 && *p <= o.amount).ok_or_else(|| err(E_STATE))?;
    let last = paid == o.amount;
    let p = Paid { faucet: o.is(F_FAUCET), kind: o.kind, owner_id: o.owner_id, funder_id: o.funder_id, source: &o.source, mint: &o.mint };
    let (mut created, mut sent) = (false, 0u64);
    for (k, (payee, wallet)) in payees.iter().zip(wallets).enumerate() {
        let [_, wallet_acc, dest, rep, pair] = &per[k * PER_PAYEE..(k + 1) * PER_PAYEE] else { return Err(ProgramError::NotEnoughAccountKeys) };
        // never into this program's own accounts (an order's account, a vault, a Balance): they belong to ["auth"]
        if wallet_acc.key != wallet || wallet == a.auth.key { return Err(err(E_PAYEE)); }
        if dest.data_is_empty() && *dest.owner == system_program::ID {
            create_ata(a.ata_program, a.relayer, dest, wallet_acc, a.mint, a.sys, a.token)?;
            created = true;
        }
        if !is_owned(dest, a.token.key, &o.mint, wallet) { return Err(err(E_PAYEE)); }
        // each share rounded down; the last payee takes what rounding left, so exactly `due` is paid
        let share = if k + 1 == payees.len() { due - sent } else { bps_of(due, payee.bps) };
        sent += share;
        if share > 0 { transfer(a.token, a.ov, a.mint, dest, a.auth, share, m.decimals, Some(bump))?; }
        record(program_id, a.relayer, rep, pair, a.sys, &p, payee.id, wallet, share, now)?;
        msg!("knos3:paid order={} pr={} payee={} amount={} to={}", b58(a.order.key), pr, payee.id, share, b58(wallet));
    }
    // the fee of this payment: the whole fee with the last of the amount; before that, the paid share of it
    let fee_before = (o.fee as u128 * o.paid as u128 / o.amount as u128) as u64;
    let fee = if last { o.fee - fee_before } else { (o.fee as u128 * paid as u128 / o.amount as u128) as u64 - fee_before };
    let tip = units(if created { TIP_FIRST } else { TIP }, m.decimals).min(fee);
    if tip > 0 { transfer(a.token, a.ov, a.mint, a.tip_tok, a.auth, tip, m.decimals, Some(bump))?; }
    // with the last payment FEE_OWNER takes everything that is left, so the account can close whatever was sent to it
    let rest = if last { amount_of(a.ov, a.token.key, E_ACCOUNTS)? } else { fee - tip };
    if rest > 0 { transfer(a.token, a.ov, a.mint, a.fee_tok, a.auth, rest, m.decimals, Some(bump))?; }
    msg!("knos3:settled order={} paid={} of={} fee={} tip={} judge={}", b58(a.order.key), paid, o.amount, rest, tip, judge.map_or(9, |j| j as u8));
    {
        let mut d = a.order.try_borrow_mut_data()?;
        d[O_STATE] = OPEN;
        put_u64(&mut d, O_PAID, paid);
    }
    after_pay(program_id, a, o, per, payees, wallets, pr, paid, now)?;
    if last {
        close_token(a.token, a.ov, a.rent_to, a.auth, bump)?;
        close(a.order, a.rent_to)?;
    }
    Ok(())
}

/// 17 PayOrder: a pay token from a judge of this order (`judge_ok`): the terms fixed at funding were met.
/// accounts: relayer(s,w) pay_token key order(w) ov(w) tip_token(w) fee_token(w) auth rent_to(w) mint token_program
///           system ata_program, then for each payee of the audience, in its order: bind wallet dest_token(w) rep(w) pair(w)
/// Each payee is paid at the address the token carries for it; with `-`, at the wallet in its Bind; with neither, the
/// order becomes HELD for it (one payee only: a split with a payee who cannot be paid is refused, and nothing moves).
pub fn pay_order(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, tok, key, order, ov, tip_tok, fee_tok, auth, rent_to, mint, token, sys, ata_program] = take(accounts)?;
    let per = &accounts[13..];
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
    let o = load_order(program_id, order)?;
    let g = crate::order_judge::token(program_id, &o, tok, key, now)?;
    if o.state != OPEN || now > o.deadline { return Err(err(E_STATE)); }
    let judge = judge_ok(&o, &g)?;
    // issued after the funding: a proof made before this order existed cannot pay it
    if g.iat < o.not_before { return Err(err(E_STATE)); }
    let a = crate::order_judge::audience(&o, judge, &g.aud)?;
    if a.order != *order.key || a.terms != o.terms || a.mode != o.mode { return Err(err(E_AUD)); }
    not_yet(program_id, &o, &a.payees, per)?;
    if per.len() < a.payees.len() * PER_PAYEE { return Err(ProgramError::NotEnoughAccountKeys); }
    // where each payee's money goes: the address the token carries; else the payee's bound wallet; else nowhere yet.
    // The bind account must be ["bind", id] itself (`bound`), so a Bind cannot be hidden.
    let mut wallets = Vec::with_capacity(a.payees.len());
    for (k, p) in a.payees.iter().enumerate() {
        let at = bound(program_id, &per[k * PER_PAYEE], p.id)?;
        match p.address.or(at) { Some(w) => wallets.push(w), None => break }
    }
    if wallets.len() < a.payees.len() {
        if a.payees.len() != 1 { return Err(err(E_PAYEE)); }
        let until = now.saturating_add(HOLD);
        let mut d = order.try_borrow_mut_data()?;
        d[O_STATE] = HELD;
        put_u64(&mut d, O_PAYEE, a.payees[0].id); put_i64(&mut d, O_HOLD_UNTIL, until);
        msg!("knos3:held order={} pr={} payee={} until={}", b58(order.key), a.pr, a.payees[0].id, until);
        return Ok(());
    }
    pay_out(program_id, &Payout { relayer, order, ov, tip_tok, fee_tok, auth, rent_to, mint, token, sys, ata_program }, &o, per, &a.payees,
            &crate::order_terms::routed(program_id, order.key, &o, &a.payees, wallets, per)?, due_now(&o), Some(judge), a.pr, now)
}

/// 26 SettleOrder: a HELD order is paid once its payee has bound a wallet. No token is needed: the proof was checked
/// when the order was held. Anyone relays, and takes the tip.
/// accounts: relayer(s,w) order(w) ov(w) tip_token(w) fee_token(w) auth rent_to(w) mint token_program system
///           ata_program bind wallet dest_token(w) rep(w) pair(w)
pub fn settle_order(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, order, ov, tip_tok, fee_tok, auth, rent_to, mint, token, sys, ata_program] = take(accounts)?;
    let per = accounts.get(11..11 + PER_PAYEE).ok_or(ProgramError::NotEnoughAccountKeys)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
    let o = load_order(program_id, order)?;
    if o.state != HELD || now > o.hold_until { return Err(err(E_STATE)); }
    let wallet = bound(program_id, &per[0], o.payee)?.ok_or_else(|| err(E_PAYEE))?;
    let payee = [Payee { id: o.payee, bps: 10_000, address: None }];
    pay_out(program_id, &Payout { relayer, order, ov, tip_tok, fee_tok, auth, rent_to, mint, token, sys, ata_program }, &o, per, &payee,
            &crate::order_terms::routed(program_id, order.key, &o, &payee, vec![wallet], &accounts[11..])?, due_now(&o), None, 0, now)
}

/// 22 RefundOrder: the order's money back to where it came from, once nobody else can have it: OPEN past its
/// deadline, or HELD past its hold. No token is needed, so a refund never depends on GitHub or on anyone's keys.
/// Everything the order's account holds goes back: what is left of the amount, and the fee on it.
/// accounts: relayer(s) order(w) ov(w) refund_token(w) auth rent_to(w) mint token_program
pub fn refund_order(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, order, ov, refund_tok, auth, rent_to, mint, token] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer { return Err(err(E_ACCOUNTS)); }
    let o = load_order(program_id, order)?;
    let due = match o.state { OPEN => now > o.deadline, HELD => now > o.hold_until, _ => false };
    if !due { return Err(err(E_STATE)); }
    if *rent_to.key != o.rent_to { return Err(err(E_ACCOUNTS)); }
    let (m, bump) = order_accounts(program_id, &o, order.key, ov, auth, mint, token)?;
    // a Balance's order: exactly that Balance's token account. A wallet's order: a token account of that wallet.
    let ok = if o.kind == 1 { *refund_tok.key == o.refund_to } else { is_owned(refund_tok, token.key, &o.mint, &o.refund_to) };
    if !ok { return Err(err(E_PAYEE)); }
    if refund_first(program_id, &o, accounts, &m, bump, now)? { return Ok(()); }
    let amount = amount_of(ov, token.key, E_ACCOUNTS)?;
    if amount > 0 { transfer(token, ov, mint, refund_tok, auth, amount, m.decimals, Some(bump))?; }
    msg!("knos3:refunded order={} amount={}", b58(order.key), amount);
    close_token(token, ov, rent_to, auth, bump)?;
    close(order, rent_to)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_pay_audience_names_the_order_and_up_to_four_payees_whose_shares_are_the_whole() {
        let (order, w, terms, head) = (Pubkey::new_from_array([7; 32]), Pubkey::new_from_array([9; 32]), "ab".repeat(32), "c".repeat(40));
        let aud = |list: &str| format!("knos3:pay:{order}:{head}:{terms}:1:42:{list}");
        let a = pay_order_aud(aud(&format!("5.7000.{w},6.3000.-")).as_bytes()).ok().unwrap();
        assert_eq!((a.order, a.terms, a.mode, a.pr, a.payees.len()), (order, [0xab; 32], 1, 42, 2));
        assert_eq!((a.payees[0].id, a.payees[0].bps, a.payees[0].address, a.payees[1].id, a.payees[1].bps, a.payees[1].address), (5, 7000, Some(w), 6, 3000, None));
        assert_eq!(pay_order_aud(aud("1.2500.-,2.2500.-,3.2500.-,4.2500.-").as_bytes()).ok().unwrap().payees.len(), 4);
        for list in ["", "5.10000", "5.9999.-", "5.10001.-", "5.5000.-,5.5000.-", "0.10000.-", "5.0.-,6.10000.-", "5.10000.-,", "5.10000.-.x", "5.10000.x",
                     "1.2000.-,2.2000.-,3.2000.-,4.2000.-,5.2000.-", "5.5000.-;6.5000.-", "5.10000.-:1", "05.10000.-", "5.5000.-,6.6000.-"] {
            assert!(pay_order_aud(aud(list).as_bytes()).err() == Some(err(E_AUD)), "{list}");
        }
        for bad in [aud("5.10000.-").replace("knos3", "knos2"), aud("5.10000.-").replace(":1:42:", ":2:42:"), aud("5.10000.-").replace(&head, "zz")] {
            assert!(pay_order_aud(bad.as_bytes()).is_err(), "{bad}");
        }
    }
}
