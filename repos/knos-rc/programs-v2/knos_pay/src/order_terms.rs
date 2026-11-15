//! What an order can promise beyond "paid on a judge's token" (2.1): a holdback kept through a warranty, a standing
//! offer paid once per pull request, a reservation, a cancellation with notice and a kill fee, an assigned payment,
//! a quorum of judges, and the markers that can be closed once they no longer matter. order_pay.rs calls this file from its hooks.
//!
//! WHERE AN ORDER'S MONEY CAN GO, beyond the four transfers order_pay.rs lists (all from ["ov", order], in its mint):
//!   -> a token account of each wallet ["hb", order] recorded     Release: that payee's part of the holdback, whole
//!   -> a token account of the relayer, then of FEE_OWNER         Release: the tip, then everything left (the fee's rest)
//!   -> where the order's money came from                         Revert: everything it holds (the holdback and its fee)
//!   -> a token account of the taker's bound wallet               RefundOrder: the kill fee, before the refund
//! PayOrder pays a payee at the wallet ["as", order, payee] names when there is one (Assign), else as before.
//!
//! ACCOUNTS (PDAs of this program, created here; integers little-endian):
//!   Hb   ["hb", order]            240 bytes: where the holdback of an order in WARRANTY goes. Closed with the order.
//!   Done ["done", order, pr u64]  73 bytes: this standing order, as funded now, has paid this pull request.
//!   As   ["as", order, payee id]  88 bytes: the wallet this order pays for that payee instead of the payee's own.
//!   Q    ["q", order, kind u8]    122 bytes: judge `kind` (0 own repository, 1 neutral run, 2 judge repository) passed
//!                                 this artifact for an order with a QUORUM, and whose run it was (the owner of the
//!                                 repository, the account that started it). Closed by CloseMarker once it cannot count.
//! INCARNATION. Done, As and Q are named by their order's address, and an address is funded again once its order was
//! paid or refunded. Each therefore carries the STAMP of the order it was made for (state::stamp: the slot of that
//! order's funding), and counts only for the order that has that stamp: none outlives its order. A marker of 2.1
//! (65 or 106 bytes) is made whole in place, its rent topped up by whoever relays, when it is written again.
//! PayOrder takes, after its payees' accounts: one ["as", order, payee] per payee, in the payees' order (it need not
//! exist, but it cannot be left out: a relayer cannot hide an assignment), then ["done", order, pr](w) for a STANDING
//! order, or ["hb", order](w) for one with a holdback; then, for an order with a QUORUM, the three ["q", order, kind](w),
//! kinds 0, 1, 2, last. SettleOrder takes ["as", order, payee] after its sixteen.
//! RefundOrder takes, after its eight, the taker's bind and a token account of his wallet (w) when a kill fee is due.
//!
//! INSTRUCTIONS (the first byte of the data is the tag; (s) signs, (w) is writable):
//!   18 Release     relayer(s,w) order(w) ov(w) hb(w) tip_token(w) fee_token(w) auth rent_to(w) hb_payer(w) mint token_program
//!                  system ata_program, then for each recorded payee, in the record's order: wallet dest_token(w)
//!                  Anyone, once the warranty is over: each recorded wallet receives its part of the holdback (its
//!                  associated token account is created here when it does not exist), the relayer the tip, FEE_OWNER
//!                  what is left; the order, its token account and the record are closed.
//!   19 Revert      relayer(s,w) revert_token key order(w) ov(w) hb(w) refund_token(w) auth rent_to(w) hb_payer(w) mint token_program
//!                  system used(w)
//!                  Inside the warranty, on a token of judge a, b or c (order_judge::judge: the order's own
//!                  repository, a NEUTRAL attest.yml by hand in the runner's own repository, the judge repository)
//!                  issued after the payment with audience knos3:revert:<order>:<head sha>: everything the order
//!                  holds goes back to its funder; all closed. The arbiter rules on payments, not on reverts.
//!                  This is also the CHALLENGE of a payment (see `revert`): anyone re-runs the pinned judge.
//!   20 Reserve     relayer(s,w) take_token key order(w) system used(w)
//!                  A command's token (order_judge::command) with audience knos3:take:<order>:<taker id>:<days>, days
//!                  1..=the order's reserve_days: the pinned fund.yml (the COMMAND job) or prove.yml run in the order's
//!                  own repository, or, for a NEUTRAL order, the pinned attest.yml started by hand in the taker's own
//!                  repository. Its `actor_id` is the taker it names: a person reserves for himself. The order (OPEN,
//!                  not cancelled, not reserved now) is reserved for the taker.
//!   21 Cancel      signer(s,w) order(w) [cancel_token key system used(w)]
//!                  A wallet's order: the funding wallet signs. A Balance's order: a command's token with audience
//!                  knos3:cancel:<order> from the pinned fund.yml or prove.yml run in the order's own repository,
//!                  whose actor funded the order or owns the Balance. Once, on an OPEN order: the deadline becomes
//!                  min(deadline, now + NOTICE). PayOrder is not changed by it. With a token the signer pays the rent
//!                  of its marker `used`, and only then must it be writable.
//!   24 Assign      signer(s,w) order bind as(w) system        data: payee id u64, to [32]
//!                  The payee's bound wallet signs (or, once an assignment is set, its current assignee): this
//!                  order's payment for that payee goes to `to`.
//!   27 CloseMarker marker(w) rent_to(w) order
//!                  Anyone. A ["used", ...] marker once no token it stands for can be accepted any more (`order` is
//!                  not read), or a ["done", ...] marker once its order (`order`) is closed, or a ["q", ...] marker
//!                  once its order is no longer the OPEN order it was made for: its rent to who paid it.
//!
//! LOGS: knos3:warranty order= held= until=      knos3:released order= payee= amount= to=      knos3:reverted order= amount= head=
//!       knos3:reserved order= taker= until=     knos3:cancelled order= at= deadline=          knos3:kill order= taker= amount= held=
//!       knos3:assigned order= payee= to=             knos3:quorum order= judge= have= of=
use crate::{err, gh::*, order::*, order_judge::command, order_pay::{judge_ok, Judge, Payee}, pay::bound, state::*, token::*, *};
use knos_oidc::claims::{self, parts};
use solana_program::{account_info::AccountInfo, entrypoint::ProgramResult, msg, program_error::ProgramError, pubkey::Pubkey, system_program, sysvar::Sysvar};

// Hb ["hb", order]
pub const H_VERSION: usize = 0;     // 1
pub const H_BUMP: usize = 1;
pub const H_N: usize = 2;           // how many payees follow (1..=MAX_PAYEES)
pub const H_PAYER: usize = 8;       // who paid this account's rent and gets it back
pub const H_UNTIL: usize = 40;      // i64: the end of the warranty (the order's hold_until)
pub const H_ENTRIES: usize = 48;    // MAX_PAYEES x (payee id u64 @0, wallet [32] @8, amount u64 @40)
pub const H_ENTRY: usize = 48;
pub const HB_LEN: usize = 240;
// Done ["done", order, pr u64]
pub const D_PAYER: usize = 1;       // byte 0 is 1; who paid the rent
pub const D_ORDER: usize = 33;      // the order: the marker can be closed once the order it was made for is not at that address
pub const D_STAMP: usize = 65;      // i64: the stamp of the order it was made for (state::stamp): one funded later at the address ignores it
pub const DONE_LEN: usize = 73;
pub const DONE_LEN_21: usize = 65;  // as 2.1 wrote it, without a stamp: it counts for an order of 2.1 and for no other
// As ["as", order, payee id]
pub const A_VERSION: usize = 0;     // 1
pub const A_BUMP: usize = 1;
pub const A_PAYEE: usize = 8;
pub const A_ORDER: usize = 16;
pub const A_TO: usize = 48;         // the wallet that is paid
pub const A_SINCE: usize = 80;      // i64: the stamp of the order it was made for (state::stamp): a later order at the same address ignores it
pub const AS_LEN: usize = 88;
// Q ["q", order, kind u8]
pub const Q_BUMP: usize = 0;
pub const Q_KIND: usize = 1;        // 0 the order's own repository (judges a and e), 1 a neutral run (b), 2 the judge repository (c)
pub const Q_PAYER: usize = 2;       // who paid the rent
pub const Q_ORDER: usize = 34;
pub const Q_SINCE: usize = 66;      // i64: the stamp of the order it was made for (state::stamp): a later order at the same address ignores it
pub const Q_ART: usize = 74;        // [32]: sha256 of what the judge passed: the audience after the order's address
pub const Q_OWNER: usize = 106;     // u64: `repository_owner_id` of the judge's run: who owns the repository it ran in
pub const Q_ACTOR: usize = 114;     // u64: `actor_id` of the judge's run: the account that started it
pub const Q_LEN: usize = 122;
pub const Q_LEN_21: usize = 106;    // as 2.1 wrote it, without owner and actor: it counts for nothing, and is made whole when its judge signs again

/// A cancelled order still takes a pay token for this long (or until its own deadline, if that is sooner).
pub const NOTICE: i64 = 7 * 86_400;
/// The accounts of one payee in PayOrder and SettleOrder (order_pay.rs): bind, wallet, dest_token, rep, pair.
const PER: usize = 5;

pub fn hb_key(program_id: &Pubkey, order: &Pubkey) -> (Pubkey, u8) { Pubkey::find_program_address(&[b"hb", order.as_ref()], program_id) }
pub fn as_key(program_id: &Pubkey, order: &Pubkey, payee: u64) -> (Pubkey, u8) {
    Pubkey::find_program_address(&[b"as", order.as_ref(), &payee.to_le_bytes()], program_id)
}

// ---- 1. holdback and warranty; 2. standing orders: the hooks of order_pay.rs -------------------------------------

/// What one accepted token pays. A STANDING order: its rate, while at least one rate is left (then nothing: the
/// rest goes back). An order with a holdback: what is left less the holdback, which stays in the order. Any other:
/// all that is left.
pub fn due_now(o: &Order) -> u64 {
    let left = o.amount - o.paid;
    if o.is(F_STANDING) { return if left >= o.rate { o.rate } else { 0 }; }
    left - bps_of(left, o.holdback_bps as u64)
}

/// What PayOrder refuses before any money moves. An order that is both STANDING and has a holdback is not built
/// (E_LATER): its money waits and goes back at the deadline. A STANDING order, and one with a holdback, is never
/// HELD: every payee must have a wallet now (the address the token carries, or a Bind), else E_PAYEE and nothing
/// changes. Why refused and not handled: a held order waits up to HOLD for a wallet and is then paid without a token,
/// so a held standing order would stop every other contributor for that long and could not mark its pull request,
/// and a held holdback would have no wallet to record and a warranty that ran out while it waited. The payee binds a
/// wallet and a judge signs again. (Funding cannot refuse this: it does not know who will be paid.)
pub fn not_yet(program_id: &Pubkey, o: &Order, payees: &[Payee], per: &[AccountInfo]) -> ProgramResult {
    if !o.is(F_STANDING) && o.holdback_bps == 0 { return Ok(()); }
    if o.is(F_STANDING) && o.holdback_bps != 0 { return Err(err(E_LATER)); }
    for (k, p) in payees.iter().enumerate() {
        let bind = per.get(k * PER).ok_or(ProgramError::NotEnoughAccountKeys)?;
        if p.address.is_none() && bound(program_id, bind, p.id)?.is_none() { return Err(err(E_PAYEE)); }
    }
    Ok(())
}

/// After the payees, the tip and the fee of one payment were sent and `paid` was raised, before the order is closed
/// when nothing is left. `per`: the accounts after PayOrder's fourteen (SettleOrder's eleven); `paid`: the order's
/// `paid` after this payment.
///   - the taker was paid: his reservation is over, and with it any kill fee;
///   - a STANDING order: this pull request is marked ["done", order, pr] (E_REPLAY if it was paid before); the order
///     is rewritten as what is left of it (amount, fee; paid 0); when less than one rate is left the deadline
///     becomes the past, so RefundOrder returns the rest at once;
///   - an order with a holdback: what was kept is recorded in ["hb", order] for the wallets just paid, in the same
///     shares, and the order is in WARRANTY until now + warranty_s.
#[allow(clippy::too_many_arguments)]
pub fn after_pay<'a>(program_id: &Pubkey, relayer: &AccountInfo<'a>, order: &AccountInfo<'a>, sys: &AccountInfo<'a>, o: &Order, per: &[AccountInfo<'a>],
                     payees: &[Payee], wallets: &[Pubkey], pr: u64, paid: u64, now: i64) -> ProgramResult {
    let n = payees.len();
    if o.reserved_by != 0 && payees.iter().any(|p| p.id == o.reserved_by) {
        let mut d = order.try_borrow_mut_data()?;
        put_u64(&mut d, O_RESERVED_BY, 0); put_i64(&mut d, O_RESERVED_UNTIL, 0);
    }
    if o.is(F_STANDING) {
        o.settled()?;
        mark_done(program_id, relayer, per.get(n * PER + n).ok_or(ProgramError::NotEnoughAccountKeys)?, sys, order.key, o, pr)?;
        if paid < o.amount {
            // A standing order is kept as what is left of it: `amount` what its payees can still receive, `fee` what
            // is still escrowed for it, `paid` zero. So the fee share of every payment is taken from the fee that is
            // really there, whatever a TopUp did to the amount and the fee in between (the floor makes the fee rate
            // of a small order higher than that of the larger order it is topped up to).
            let share = |p: u64| (o.fee as u128 * p as u128 / o.amount as u128) as u64;
            let (left, took) = (o.amount - paid, share(paid) - share(o.paid));
            let mut d = order.try_borrow_mut_data()?;
            put_u64(&mut d, O_AMOUNT, left); put_u64(&mut d, O_FEE, o.fee - took); put_u64(&mut d, O_PAID, 0);
            // (an order with the presentation grace: far enough back that the grace is over too)
            if left < o.rate { put_i64(&mut d, O_DEADLINE, o.deadline.min(now - 1 - if o.grace { GRACE } else { 0 })); }
        }
        return Ok(());
    }
    if o.holdback_bps == 0 || paid >= o.amount { return Ok(()); }
    let hb = per.get(n * PER + n).ok_or(ProgramError::NotEnoughAccountKeys)?;
    let (new, bump) = open(program_id, relayer, hb, sys, HB_LEN, &[b"hb", order.key.as_ref()], E_ACCOUNTS)?;
    if !new { return Err(err(E_STATE)); }
    let (held, until) = (o.amount - paid, now.saturating_add(o.warranty_s));
    {
        let mut d = hb.try_borrow_mut_data()?;
        d[H_VERSION] = 1; d[H_BUMP] = bump; d[H_N] = n as u8;
        put_key(&mut d, H_PAYER, relayer.key); put_i64(&mut d, H_UNTIL, until);
        // each part rounded down; the last payee's is what rounding left, so the parts are exactly what was kept
        let mut given = 0u64;
        for (k, (p, w)) in payees.iter().zip(wallets).enumerate() {
            let part = if k + 1 == n { held - given } else { bps_of(held, p.bps) };
            given += part;
            let at = H_ENTRIES + k * H_ENTRY;
            put_u64(&mut d, at, p.id); put_key(&mut d, at + 8, w); put_u64(&mut d, at + 40, part);
        }
    }
    let mut d = order.try_borrow_mut_data()?;
    d[O_STATE] = WARRANTY;
    put_i64(&mut d, O_HOLD_UNTIL, until);
    msg!("knos3:warranty order={} held={} until={}", b58(order.key), held, until);
    Ok(())
}

/// Makes a marker of 2.1 (`from` bytes) as long as this build writes it (`to` bytes, the new ones zero): the rent of
/// the longer account is topped up by `payer`. What it held stays where it was.
fn grow<'a>(payer: &AccountInfo<'a>, acct: &AccountInfo<'a>, sys: &AccountInfo<'a>, to: usize) -> ProgramResult {
    let need = solana_program::rent::Rent::get()?.minimum_balance(to);
    if acct.lamports() < need {
        solana_program::program::invoke(&solana_program::system_instruction::transfer(payer.key, acct.key, need - acct.lamports()), &[payer.clone(), acct.clone(), sys.clone()])?;
    }
    acct.resize(to)
}

/// Marks a pull request as paid by a standing order: creates ["done", order, pr] (rent from `payer`), or refuses with
/// E_REPLAY when it is there FOR THIS ORDER: it carries this order's stamp (or, on an order of 2.1, is a marker as
/// 2.1 wrote it). A marker of an order that was at this address before is rewritten for this one; its rent stays
/// whose it was. It stores who paid its rent, its order and that order's stamp, which is what CloseMarker needs.
fn mark_done<'a>(program_id: &Pubkey, payer: &AccountInfo<'a>, done: &AccountInfo<'a>, sys: &AccountInfo<'a>, order: &Pubkey, o: &Order, pr: u64) -> ProgramResult {
    let prb = pr.to_le_bytes();
    let (key, bump) = Pubkey::find_program_address(&[b"done", order.as_ref(), &prb], program_id);
    if *done.key != key { return Err(err(E_ACCOUNTS)); }
    if done.owner == program_id {
        let len = done.data_len();
        let this = match len { DONE_LEN => i64_at(&done.try_borrow_data()?, D_STAMP) == o.stamp(), DONE_LEN_21 => o.inc == 0, _ => return Err(err(E_ACCOUNTS)) };
        if this { return Err(err(E_REPLAY)); }
        if len != DONE_LEN { grow(payer, done, sys, DONE_LEN)?; }
    } else {
        if !done.data_is_empty() || *done.owner != system_program::ID { return Err(err(E_ACCOUNTS)); }
        create_pda(payer, done, sys, program_id, DONE_LEN, &[b"done", order.as_ref(), &prb, &[bump]])?;
        put_key(&mut done.try_borrow_mut_data()?, D_PAYER, payer.key);
    }
    let mut d = done.try_borrow_mut_data()?;
    d[0] = 1;
    put_key(&mut d, D_ORDER, order); put_i64(&mut d, D_STAMP, o.stamp());
    Ok(())
}

/// The record of a holdback: who paid its rent, and (payee id, wallet, amount) for each payee.
pub struct Hb { pub payer: Pubkey, pub entries: Vec<(u64, Pubkey, u64)> }
/// ["hb", order], read after checking that this program owns it, its length, and that it is this order's.
pub fn load_hb(program_id: &Pubkey, hb: &AccountInfo, order: &Pubkey) -> Result<Hb, ProgramError> {
    if hb.owner != program_id || hb.data_len() != HB_LEN { return Err(err(E_ACCOUNTS)); }
    let d = hb.try_borrow_data()?;
    if d[H_VERSION] != 1 || Pubkey::create_program_address(&[b"hb", order.as_ref(), &[d[H_BUMP]]], program_id) != Ok(*hb.key) || d[H_N] as usize > MAX_PAYEES {
        return Err(err(E_ACCOUNTS));
    }
    let entries = (0..d[H_N] as usize).map(|k| H_ENTRIES + k * H_ENTRY).map(|at| (u64_at(&d, at), key_at(&d, at + 8), u64_at(&d, at + 40))).collect();
    Ok(Hb { payer: key_at(&d, H_PAYER), entries })
}

/// 18 Release: the warranty is over and nobody reverted: the holdback goes to the wallets recorded at payment.
pub fn release(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, order, ov, hb, tip_tok, fee_tok, auth, rent_to, hb_payer, mint, token, sys, ata_program] = take(accounts)?;
    let per = &accounts[13..];
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
    let o = load_order(program_id, order)?;
    if o.state != WARRANTY || now <= o.hold_until { return Err(err(E_STATE)); }
    let (m, bump) = order_accounts(program_id, &o, order.key, ov, auth, mint, token)?;
    let h = load_hb(program_id, hb, order.key)?;
    if *rent_to.key != o.rent_to || *hb_payer.key != h.payer { return Err(err(E_ACCOUNTS)); }
    if !is_owned(tip_tok, token.key, &o.mint, relayer.key) || !is_owned(fee_tok, token.key, &o.mint, &FEE_OWNER) || relayer.key == auth.key {
        return Err(err(E_PAYEE));
    }
    let mut created = false;
    for (k, (id, wallet, amount)) in h.entries.iter().enumerate() {
        let [wallet_acc, dest] = take(per.get(2 * k..).ok_or(ProgramError::NotEnoughAccountKeys)?)?;
        if wallet_acc.key != wallet || wallet == auth.key { return Err(err(E_PAYEE)); }
        if dest.data_is_empty() && *dest.owner == system_program::ID {
            create_ata(ata_program, relayer, dest, wallet_acc, mint, sys, token)?;
            created = true;
        }
        if !is_owned(dest, token.key, &o.mint, wallet) { return Err(err(E_PAYEE)); }
        if *amount > 0 { transfer(token, ov, mint, dest, auth, *amount, m.decimals, Some(bump))?; }
        msg!("knos3:released order={} payee={} amount={} to={}", b58(order.key), id, amount, b58(wallet));
    }
    // what is left is the fee on the holdback (and anything sent to the account directly): the tip, then FEE_OWNER
    let left = amount_of(ov, token.key, E_ACCOUNTS)?;
    let tip = units(if created { TIP_FIRST } else { TIP }, m.decimals).min(left);
    if tip > 0 { transfer(token, ov, mint, tip_tok, auth, tip, m.decimals, Some(bump))?; }
    if left > tip { transfer(token, ov, mint, fee_tok, auth, left - tip, m.decimals, Some(bump))?; }
    msg!("knos3:settled order={} paid={} of={} fee={} tip={} judge=9", b58(order.key), o.amount, o.amount, left - tip, tip);
    close_token(token, ov, rent_to, auth, bump)?;
    close(order, rent_to)?;
    close(hb, hb_payer)
}

/// knos3:<word>:<order address>, then `N - 3` more parts: an audience of this file names its order as Solana prints it.
fn aud_of<'x, const N: usize>(aud: &'x [u8], word: &[u8], order: &Pubkey) -> Result<[&'x [u8]; N], ProgramError> {
    let p = parts::<N>(aud).ok_or_else(|| err(E_AUD))?;
    if p[0] != b"knos3" || p[1] != word || p[2] != b58(order).as_bytes() { return Err(err(E_AUD)); }
    Ok(p)
}

/// 19 Revert: inside the warranty a judge says the accepted change was reverted, or does not pass after all: the
/// holdback, and the fee on it, go back to where the order's money came from.
///
/// THE CHALLENGE. For an order that allows a neutral run (flag NEUTRAL), "a judge" includes anyone: a stranger starts
/// the pinned attest.yml by hand in a repository of his own (judge b), it runs the pinned judge again on the head
/// that was paid, and it signs knos3:revert:<order>:<head> only when that head fails the order's terms. No bond is
/// asked of a challenger, because a false challenge cannot be made: the token is GitHub's signature over a run of
/// the pinned file at the pinned commit on a GitHub-hosted runner, and that file decides what it signs, not the
/// person who started it. A challenge costs its sender one transaction fee and a marker's rent. After the warranty
/// Release pays and no challenge is heard (E_STATE). What the program itself checks is the judge and the window:
/// the order keeps no record of the head it paid, so that the head named is the one that was paid is the pinned
/// workflow's word. An order without NEUTRAL is challenged only from its own or its judge repository.
/// The token is a judge's as PayOrder's is (a the order's own
/// repository, b a NEUTRAL attest.yml by hand in the runner's own repository, c the judge repository), issued after
/// the payment. Whoever signs it, the only thing it can do is return what the order still holds to its funder, and
/// only inside the warranty: what was paid stays paid. A ruling is not a revert, so the arbiter signs none.
pub fn revert(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, tok, key, order, ov, hb, refund_tok, auth, rent_to, hb_payer, mint, token, sys, used] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
    let o = load_order(program_id, order)?;
    let g = github(tok, key, now)?;
    if o.state != WARRANTY || now > o.hold_until || g.iat < o.hold_until - o.warranty_s { return Err(err(E_STATE)); }
    if !matches!(judge_ok(&o, &g)?, Judge::Own | Judge::Neutral | Judge::Private) { return Err(err(E_CLAIMS)); }
    let [_, _, _, head] = aud_of::<4>(&g.aud, b"revert", order.key)?;
    if !claims::is_hex(head, 40) { return Err(err(E_AUD)); }
    let (m, bump) = order_accounts(program_id, &o, order.key, ov, auth, mint, token)?;
    let h = load_hb(program_id, hb, order.key)?;
    if *rent_to.key != o.rent_to || *hb_payer.key != h.payer { return Err(err(E_ACCOUNTS)); }
    let ok = if o.kind == 1 { *refund_tok.key == o.refund_to } else { is_owned(refund_tok, token.key, &o.mint, &o.refund_to) };
    if !ok { return Err(err(E_PAYEE)); }
    mark_used(program_id, relayer, used, sys, &sig_hash(tok)?, USED, false)?;
    let amount = amount_of(ov, token.key, E_ACCOUNTS)?;
    if amount > 0 { transfer(token, ov, mint, refund_tok, auth, amount, m.decimals, Some(bump))?; }
    msg!("knos3:reverted order={} amount={} head={}", b58(order.key), amount, core::str::from_utf8(head).map_err(|_| err(E_AUD))?);
    close_token(token, ov, rent_to, auth, bump)?;
    close(order, rent_to)?;
    close(hb, hb_payer)
}

// ---- 3. reserve, cancel, kill fee ---------------------------------------------------------------------------------

/// 20 Reserve: a person takes the order for himself, for how many days he says (at most the order's reserve_days; an
/// order funded with 0 cannot be reserved). The token is a command's: the order's own repository answered his comment
/// (the pinned fund.yml) or his pull request (prove.yml), or, for a NEUTRAL order, he started the pinned attest.yml
/// by hand in a repository of his own. Whichever run it is, the taker it names is the account GitHub says started
/// it: nobody reserves in another's name, so nobody can park an order under a taker who never asked, or collect a
/// kill fee for one. An order is reserved by one taker at a time, and not after a Cancel: a kill fee is for a taker
/// who was working when the funder cancelled, not for one who arrives afterwards.
pub fn reserve(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, tok, key, order, sys, used] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
    let o = load_order(program_id, order)?;
    let g = github(tok, key, now)?;
    if o.state != OPEN || now > o.deadline || o.cancel_at != 0 || (o.reserved_by != 0 && now <= o.reserved_until) || g.iat < o.not_before {
        return Err(err(E_STATE));
    }
    command(&o, &g)?;
    let [_, _, _, taker, days] = aud_of::<5>(&g.aud, b"take", order.key)?;
    let (taker, days) = (n(taker)?, n(days)?);
    if taker == 0 || days == 0 || days > o.reserve_days as u64 { return Err(err(E_AUD)); }
    if g.actor_id != taker { return Err(err(E_CLAIMS)); }
    // a take token reserves once: when its reservation has run out, the same token does not start another
    mark_used(program_id, relayer, used, sys, &sig_hash(tok)?, USED, false)?;
    let until = now.saturating_add(days as i64 * 86_400);
    let mut d = order.try_borrow_mut_data()?;
    put_u64(&mut d, O_RESERVED_BY, taker); put_i64(&mut d, O_RESERVED_UNTIL, until);
    msg!("knos3:reserved order={} taker={} until={}", b58(order.key), taker, until);
    Ok(())
}

/// 21 Cancel: the funder gives notice. The deadline becomes min(deadline, now + NOTICE); until then a pay token
/// still pays, and after it RefundOrder returns the money (less the kill fee, if the order was reserved now).
/// A wallet's order: the funding wallet signs. A Balance's order: a command's token from the order's own repository
/// (the pinned fund.yml answering a comment, or prove.yml) whose actor is the commenter who funded it or the Balance's
/// owner. A NEUTRAL run cancels nothing: it is anyone's. Once per order.
pub fn cancel(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [signer, order] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !signer.is_signer { return Err(err(E_ACCOUNTS)); }
    let o = load_order(program_id, order)?;
    if o.state != OPEN || now > o.deadline || o.cancel_at != 0 { return Err(err(E_STATE)); }
    if o.kind == 0 {
        if *signer.key != o.source { return Err(err(E_ACCOUNTS)); }
    } else {
        let [tok, key, sys, used] = take(accounts.get(2..).ok_or(ProgramError::NotEnoughAccountKeys)?)?;
        let g = github(tok, key, now)?;
        if g.iat < o.not_before { return Err(err(E_STATE)); }
        if command(&o, &g)? != Judge::Own || (g.actor_id != o.funder_id && g.actor_id != o.owner_id) { return Err(err(E_CLAIMS)); }
        aud_of::<3>(&g.aud, b"cancel", order.key)?;
        // a cancel token cancels once: an order funded later at this address is not cancelled by it
        mark_used(program_id, signer, used, sys, &sig_hash(tok)?, USED, false)?;
    }
    let deadline = o.deadline.min(now.saturating_add(NOTICE));
    let mut d = order.try_borrow_mut_data()?;
    put_i64(&mut d, O_CANCEL_AT, now); put_i64(&mut d, O_DEADLINE, deadline);
    msg!("knos3:cancelled order={} at={} deadline={}", b58(order.key), now, deadline);
    Ok(())
}

/// The kill fee a refund owes first: kill_bps of the amount (at most what is left of it), when an OPEN order was
/// cancelled while a reservation was running. Nothing otherwise.
pub fn kill_fee(o: &Order) -> u64 {
    if o.state != OPEN || o.kill_bps == 0 || o.cancel_at == 0 || o.reserved_by == 0 || o.cancel_at > o.reserved_until { return 0; }
    bps_of(o.amount, o.kill_bps as u64).min(o.amount - o.paid)
}

/// Called by RefundOrder before the money goes back. `accounts`: RefundOrder's; after its eight come the taker's
/// bind and a token account of his bound wallet (w). With a kill fee due:
///   - the taker has a bound wallet and that token account is his: the fee is sent there, and the refund goes on
///     (returns false);
///   - otherwise (no wallet, or the account passed is not a token account of it): the fee stays in the order's
///     account, everything else goes back to the funder now, and the order becomes HELD for the taker with the fee
///     as its whole amount and no fee of its own (returns true: the order is not closed). It closes as any held
///     order does: SettleOrder pays the taker once he has a wallet; after HOLD, RefundOrder returns it to the funder.
///
/// So a kill fee never stops a refund: whoever relays can always take the second way.
pub fn refund_first<'a>(program_id: &Pubkey, o: &Order, accounts: &[AccountInfo<'a>], m: &Mint, bump: u8, now: i64) -> Result<bool, ProgramError> {
    let kill = kill_fee(o);
    if kill == 0 { return Ok(false); }
    let [_, order, ov, refund_tok, auth, _, mint, token] = take(accounts)?;
    let [bind, dest] = take(accounts.get(8..).ok_or(ProgramError::NotEnoughAccountKeys)?)?;
    if let Some(wallet) = bound(program_id, bind, o.reserved_by)? {
        if wallet != *auth.key && is_owned(dest, token.key, &o.mint, &wallet) {
            transfer(token, ov, mint, dest, auth, kill, m.decimals, Some(bump))?;
            msg!("knos3:kill order={} taker={} amount={} held=0", b58(order.key), o.reserved_by, kill);
            return Ok(false);
        }
    }
    let back = amount_of(ov, token.key, E_ACCOUNTS)?.checked_sub(kill).ok_or_else(|| err(E_STATE))?;
    if back > 0 { transfer(token, ov, mint, refund_tok, auth, back, m.decimals, Some(bump))?; }
    let until = now.saturating_add(HOLD);
    let mut d = order.try_borrow_mut_data()?;
    d[O_STATE] = HELD; d[O_FLAGS] &= !F_STANDING;
    put_u16(&mut d, O_HOLDBACK_BPS, 0); put_u16(&mut d, O_KILL_BPS, 0);
    put_u64(&mut d, O_AMOUNT, kill); put_u64(&mut d, O_FEE, 0); put_u64(&mut d, O_RATE, 0); put_u64(&mut d, O_PAID, 0);
    put_u64(&mut d, O_PAYEE, o.reserved_by); put_i64(&mut d, O_HOLD_UNTIL, until);
    put_u64(&mut d, O_RESERVED_BY, 0); put_i64(&mut d, O_RESERVED_UNTIL, 0);
    msg!("knos3:refunded order={} amount={}", b58(order.key), back);
    msg!("knos3:kill order={} taker={} amount={} held=1", b58(order.key), o.reserved_by, kill);
    msg!("knos3:held order={} pr=0 payee={} until={}", b58(order.key), o.reserved_by, until);
    Ok(true)
}

// ---- 4. assign -------------------------------------------------------------------------------------------------

/// The wallet ["as", order, payee] names for this order, if one was set since this order was funded. The account
/// must be that address, so an assignment cannot be hidden; one made for an earlier order at the same address (the
/// same funder, issue and seq, funded again) is not this order's: it carries that order's stamp, not this one's.
pub fn assigned(program_id: &Pubkey, order: &Pubkey, o: &Order, a: &AccountInfo, payee: u64) -> Result<Option<Pubkey>, ProgramError> {
    if *a.key != as_key(program_id, order, payee).0 { return Err(err(E_PAYEE)); }
    if a.owner != program_id || a.data_len() != AS_LEN { return Ok(None); }
    let d = a.try_borrow_data()?;
    Ok(if i64_at(&d, A_SINCE) == o.stamp() { Some(key_at(&d, A_TO)) } else { None })
}

/// Where each payee of a payment is paid: the wallet it assigned this order's payment to, else `wallets[k]` (what
/// PayOrder and SettleOrder resolved). `per`: the payees' accounts, then one ["as", order, payee] for each payee.
pub fn routed(program_id: &Pubkey, order: &Pubkey, o: &Order, payees: &[Payee], mut wallets: Vec<Pubkey>, per: &[AccountInfo]) -> Result<Vec<Pubkey>, ProgramError> {
    for (k, p) in payees.iter().enumerate() {
        let a = per.get(payees.len() * PER + k).ok_or(ProgramError::NotEnoughAccountKeys)?;
        if let Some(to) = assigned(program_id, order, o, a, p.id)? { wallets[k] = to; }
    }
    Ok(wallets)
}

/// 24 Assign: a payee names the wallet that receives this order's payment in his place (whoever advanced him the
/// money). The first time, the payee's bound wallet signs; after that only the current assignee can change it, so
/// what was assigned cannot be taken back or assigned twice by the payee.
pub fn assign(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let [signer, order, bind, asg, sys] = take(accounts)?;
    if data.len() != 40 { return Err(ProgramError::InvalidInstructionData); }
    if !signer.is_signer || !signer.is_writable { return Err(err(E_ACCOUNTS)); }
    let o = load_order(program_id, order)?;
    o.settled()?;
    let (payee, to) = (u64_at(data, 0), key_at(data, 8));
    if payee == 0 || to == Pubkey::default() || to == auth_key(program_id).0 { return Err(err(E_PAYEE)); }
    let may = match assigned(program_id, order.key, &o, asg, payee)? {
        Some(current) => current,
        None => bound(program_id, bind, payee)?.ok_or_else(|| err(E_PAYEE))?,
    };
    if *signer.key != may { return Err(err(E_ACCOUNTS)); }
    let pb = payee.to_le_bytes();
    let (_, bump) = open(program_id, signer, asg, sys, AS_LEN, &[b"as", order.key.as_ref(), &pb], E_ACCOUNTS)?;
    let mut d = asg.try_borrow_mut_data()?;
    d[A_VERSION] = 1; d[A_BUMP] = bump;
    put_u64(&mut d, A_PAYEE, payee); put_key(&mut d, A_ORDER, order.key); put_key(&mut d, A_TO, &to); put_i64(&mut d, A_SINCE, o.stamp());
    msg!("knos3:assigned order={} payee={} to={}", b58(order.key), payee, b58(&to));
    Ok(())
}

// ---- 5. quorum -------------------------------------------------------------------------------------------------

pub fn q_key(program_id: &Pubkey, order: &Pubkey, kind: u8) -> (Pubkey, u8) { Pubkey::find_program_address(&[b"q", order.as_ref(), &[kind]], program_id) }

/// What a judge passed, as two judges must agree on it: sha256 of the audience after its order's address, which is
/// <head sha>:<terms hash hex>:<mode>:<pr>:<payees>. A pay token and an AUTO order's token (knos3:auto) of the same
/// commit, pull request and payees are the same artifact.
fn artifact(aud: &[u8]) -> Result<[u8; 32], ProgramError> {
    let at = aud.iter().enumerate().filter(|(_, c)| **c == b':').nth(2).ok_or_else(|| err(E_AUD))?.0;
    Ok(solana_program::hash::hashv(&[&aud[at + 1..]]).to_bytes())
}

/// The run behind the marker of judge `kind` for this order as it is funded now, when that marker says `art`: (the
/// owner of the repository the run was in, the account that started it). None when the judge has not passed this
/// artifact for this funding. The account must be that marker's address whether or not it exists: a relayer can
/// neither count one judge's marker as another's nor hide one that is there (which would use up the last judge's
/// token without paying). A marker as 2.1 wrote it names nobody, so it counts for nothing.
fn said(program_id: &Pubkey, q: &AccountInfo, order: &Pubkey, o: &Order, kind: u8, art: &[u8; 32]) -> Result<Option<(u64, u64)>, ProgramError> {
    if *q.key != q_key(program_id, order, kind).0 { return Err(err(E_ACCOUNTS)); }
    if q.owner != program_id || q.data_len() != Q_LEN { return Ok(None); }
    let d = q.try_borrow_data()?;
    Ok(if i64_at(&d, Q_SINCE) == o.stamp() && d[Q_ART..Q_ART + 32] == art[..] { Some((u64_at(&d, Q_OWNER), u64_at(&d, Q_ACTOR))) } else { None })
}

/// HOW MANY JUDGES these are. `who`: for each kind (0 the order's own repository, 1 a neutral run, 2 the judge
/// repository) the run that passed the artifact, as (`repository_owner_id`, `actor_id`), or None. `order_owner`: the
/// owner of the order's repository when the order itself knows it (a Balance's order: the Balance's owner id; a
/// wallet's order: 0, since a wallet names a repository and GitHub signed nothing at its funding).
///
/// The same rule for every order, however it was funded (a wallet, a passkey, a comment on a forge, a Balance):
///   1. Judges whose runs were in repositories of ONE OWNER are one judge. Two repositories of one account or one
///      organisation are that account's word twice.
///   2. The neutral judge counts only as a third party to the order's repository: its owner (who, for a neutral run,
///      is the account that started it) is not the owner of the order's repository, and the account that started it
///      is not the account that started the run in the order's repository. The owner of the order's repository is
///      `order_owner`, and the owner the own run's token names; when neither is known (a wallet's order whose own
///      repository has not judged this artifact) nothing shows that the neutral run is a third party's, and it does
///      not count until the own repository has spoken.
///
/// WHAT THIS IS AND IS NOT. It is a statement about forge accounts: `have` judges means `have` different owners of
/// repositories, and a neutral runner who is neither the order repository's owner nor the account that started its
/// run. It is not a statement about people: one person with two accounts, or two accounts that agreed, are two
/// judges here. A forge signs no more than account ids.
pub fn distinct(order_owner: u64, who: &[Option<(u64, u64)>; 3]) -> u8 {
    let [own, neutral, named] = *who;
    let neutral = neutral.filter(|n| {
        (order_owner != 0 || own.is_some()) && n.0 != order_owner && own.is_none_or(|a| n.0 != a.0 && n.1 != a.1)
    });
    let counted = [own, neutral, named];
    let mut have = 0u8;
    for (k, w) in counted.iter().enumerate() {
        if let Some(w) = w {
            if !counted[..k].iter().flatten().any(|e| e.0 == w.0) { have += 1; }
        }
    }
    have
}

/// HOOK of PayOrder, once the token is accepted and marked used. An order with a QUORUM of n pays only when n
/// DISTINCT judges have passed the same artifact: a the order's own repository (prove.yml; an AUTO order's unmerged
/// run counts as this one), b a neutral run, c the judge repository; and distinct means what `distinct` says, for
/// every order. Returns true when the payment goes on: the order has no quorum, or the token is the arbiter's ruling
/// (he decides alone, as both sides agreed at funding), or with this judge enough distinct ones have spoken.
/// Otherwise this judge's marker ["q", order, kind] is written (the relayer pays its rent; CloseMarker returns it)
/// and nothing is paid: false.
///   - Two tokens of one kind count once: the second rewrites the same marker. A judge who passes another artifact
///     later (another head, pull request or payee) replaces his earlier word; the others' markers then say something
///     else and do not count with it.
///   - A neutral run in the order's own repository, or (a Balance's order) started by the account that funded the
///     order or owns its Balance, is refused outright (E_CLAIMS), as before. A judge whose run does not add a
///     distinct judge is accepted and recorded: its token is used, and nothing is paid.
///   - A marker counts only for the order it was written for: it carries that order's stamp (state::stamp), and
///     nothing is written or counted in the slot the order was funded in (`Order::settled`: E_STATE, one slot).
///   - `accounts`: PayOrder's; the last three are the markers of kinds 0, 1, 2, each at its own address whether it
///     exists or not, so none is counted twice and none is hidden.
#[allow(clippy::too_many_arguments)]
pub fn quorum<'a>(program_id: &Pubkey, relayer: &AccountInfo<'a>, order: &AccountInfo<'a>, sys: &AccountInfo<'a>, o: &Order, g: &Gh, judge: Judge,
                  accounts: &[AccountInfo<'a>]) -> Result<bool, ProgramError> {
    let need = o.quorum();
    let kind = match judge { Judge::Arbiter => return Ok(true), Judge::Own | Judge::Auto => 0u8, Judge::Neutral => 1, Judge::Private => 2 };
    if need == 0 { return Ok(true); }
    o.settled()?;
    if judge == Judge::Neutral && (g.repo_id == o.repo || (o.kind == 1 && (g.actor_id == o.funder_id || g.actor_id == o.owner_id))) { return Err(err(E_CLAIMS)); }
    if accounts.len() < 17 { return Err(ProgramError::NotEnoughAccountKeys); }
    let qs = &accounts[accounts.len() - 3..];
    let art = artifact(&g.aud)?;
    let mut who = [None; 3];
    for k in 0..3u8 {
        who[k as usize] = if k == kind { Some((g.owner_id, g.actor_id)) } else { said(program_id, &qs[k as usize], order.key, o, k, &art)? };
    }
    let have = distinct(o.owner_id, &who);
    if have >= need { return Ok(true); }
    let mine = &qs[kind as usize];
    let (key, bump) = q_key(program_id, order.key, kind);
    if *mine.key != key { return Err(err(E_ACCOUNTS)); }
    if mine.owner == program_id {
        match mine.data_len() { Q_LEN => {}, Q_LEN_21 => grow(relayer, mine, sys, Q_LEN)?, _ => return Err(err(E_ACCOUNTS)) }
    } else {
        open(program_id, relayer, mine, sys, Q_LEN, &[b"q", order.key.as_ref(), &[kind]], E_ACCOUNTS)?;
    }
    let mut d = mine.try_borrow_mut_data()?;
    // a marker left by an earlier order at this address, or by this judge for another artifact, is rewritten; its
    // rent stays whose it was (a marker never written has no payer yet)
    if d[Q_PAYER..Q_PAYER + 32] == [0u8; 32] { put_key(&mut d, Q_PAYER, relayer.key); }
    d[Q_BUMP] = bump; d[Q_KIND] = kind;
    put_key(&mut d, Q_ORDER, order.key); put_i64(&mut d, Q_SINCE, o.stamp());
    d[Q_ART..Q_ART + 32].copy_from_slice(&art);
    put_u64(&mut d, Q_OWNER, g.owner_id); put_u64(&mut d, Q_ACTOR, g.actor_id);
    msg!("knos3:quorum order={} judge={} have={} of={}", b58(order.key), kind, have, need);
    Ok(false)
}

// ---- 6. markers ------------------------------------------------------------------------------------------------

/// 27 CloseMarker: a marker that can no longer matter is closed and its rent goes back to whoever paid it. The
/// kinds are told by their length (no other account of this program has either):
///   ["used", sig]: after the time stored in it, by which no instruction can accept a token used when it was made
///                  (state::mark_used: an hour after the latest such a token can expire, plus the verifier's lateness);
///   ["done", order, pr]: once the order it was made for is not at its order's address: nothing is there (the order
///                  was paid out or refunded), or the order there was funded later (another stamp);
///   ["q", order, kind]: once its order is not the OPEN order it was made for: nothing is at that address, or the
///                  order there was funded later (another stamp), or it is no longer OPEN (paid and in WARRANTY, or HELD).
/// Markers as 2.1 wrote them (65 and 106 bytes) are closed by the same rules.
pub fn close_marker(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [marker, rent_to, order] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if marker.owner != program_id { return Err(err(E_ACCOUNTS)); }
    let (payer, free) = {
        let d = marker.try_borrow_data()?;
        match d.len() {
            USED_LEN => (key_at(&d, U_PAYER), now > i64_at(&d, U_AFTER)),
            DONE_LEN_21 => (key_at(&d, D_PAYER), *order.key == key_at(&d, D_ORDER) && {
                let o = order.try_borrow_data()?;
                order.owner != program_id || o.len() != ORDER_LEN || u64_at(&o, O_INC) != 0
            }),
            DONE_LEN => (key_at(&d, D_PAYER), *order.key == key_at(&d, D_ORDER) && {
                let o = order.try_borrow_data()?;
                order.owner != program_id || o.len() != ORDER_LEN || stamp(&o) != i64_at(&d, D_STAMP)
            }),
            Q_LEN | Q_LEN_21 => (key_at(&d, Q_PAYER), *order.key == key_at(&d, Q_ORDER) && {
                let o = order.try_borrow_data()?;
                order.owner != program_id || o.len() != ORDER_LEN || o[O_STATE] != OPEN || stamp(&o) != i64_at(&d, Q_SINCE)
            }),
            _ => return Err(err(E_ACCOUNTS)),
        }
    };
    if !free { return Err(err(E_STATE)); }
    if *rent_to.key != payer { return Err(err(E_ACCOUNTS)); }
    close(marker, rent_to)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn order(flags: u8, holdback: u16, amount: u64, rate: u64, paid: u64) -> Order {
        Order { state: OPEN, mode: 0, kind: 0, flags, decimals: 6, reserve_days: 0, repo: 1, issue: 1, scope: [0; 32], seq: 0, holdback_bps: holdback,
                kill_bps: 0, fee_bps: 250, amount, fee: 0, rate, paid, deadline: 0, not_before: 0, hold_until: 0, warranty_s: 0, reserved_by: 0,
                reserved_until: 0, cancel_at: 0, payee: 0, funder_id: 0, owner_id: 0, arbiter_id: 0, judge_repo_id: 0, source: Pubkey::default(),
                refund_to: Pubkey::default(), rent_to: Pubkey::default(), mint: Pubkey::default(), terms: [0; 32], wf_repo: [0; 32], wf_sha: [0; 40], inc: 1, grace: false }
    }

    #[test]
    fn what_one_token_pays() {
        assert_eq!(due_now(&order(0, 0, 20, 0, 0)), 20);
        assert_eq!((due_now(&order(0, 1000, 20_000_000, 0, 0)), due_now(&order(0, 5000, 7, 0, 0)), due_now(&order(0, 1, 5, 0, 0))), (18_000_000, 4, 5));
        assert_eq!((due_now(&order(F_STANDING, 0, 20, 6, 0)), due_now(&order(F_STANDING, 0, 20, 6, 12)), due_now(&order(F_STANDING, 0, 20, 6, 18))), (6, 6, 0));
    }

    #[test]
    fn a_kill_fee_is_owed_only_to_a_taker_who_held_the_order_when_it_was_cancelled() {
        let mut o = order(0, 0, 20_000_000, 0, 0);
        (o.kill_bps, o.reserved_by, o.reserved_until, o.cancel_at) = (1000, 5, 100, 50);
        assert_eq!(kill_fee(&o), 2_000_000);
        let changes: [fn(&mut Order); 5] = [|o: &mut Order| o.cancel_at = 0, |o: &mut Order| o.cancel_at = 101, |o: &mut Order| o.reserved_by = 0, |o: &mut Order| o.kill_bps = 0,
                       |o: &mut Order| o.state = HELD];
        for change in changes {
            let mut x = order(0, 0, 20_000_000, 0, 0);
            (x.kill_bps, x.reserved_by, x.reserved_until, x.cancel_at) = (1000, 5, 100, 50);
            change(&mut x);
            assert_eq!(kill_fee(&x), 0);
        }
        o.paid = 19_000_000;
        assert_eq!(kill_fee(&o), 1_000_000);
        // every kind of account that is told by its length has its own
        let mut lens = [BALANCE_LEN, JOB_LEN, BIND_LEN, REP_LEN, PAIR_LEN, BALX_LEN, PLAN_LEN, ORDER_LEN, USED_LEN, PAUSE_LEN, RATE_LEN, HB_LEN, DONE_LEN, DONE_LEN_21, AS_LEN, Q_LEN,
                        Q_LEN_21];
        lens.sort_unstable();
        assert!(lens.windows(2).all(|w| w[0] != w[1]));
        assert_eq!(H_ENTRIES + MAX_PAYEES * H_ENTRY, HB_LEN);
        // an artifact is what follows the order's address, whichever word the audience carries
        let tail = format!("{}:{}:1:7:5.10000.-", "a".repeat(40), "ab".repeat(32));
        assert!(artifact(format!("knos3:pay:x:{tail}").as_bytes()) == artifact(format!("knos3:auto:yy:{tail}").as_bytes()));
        assert!(artifact(format!("knos3:pay:x:{tail}").as_bytes()) != artifact(format!("knos3:pay:x:{}", tail.replace(":7:", ":8:")).as_bytes()));
        assert!(artifact(b"knos3:pay").is_err() && Q_ART + 32 == Q_OWNER && Q_ACTOR + 8 == Q_LEN && D_STAMP + 8 == DONE_LEN && D_ORDER + 32 == DONE_LEN_21);
    }

    /// FINDING 1, as arithmetic. (owner of the repository the run was in, account that started it) per judge:
    /// own repository, neutral, judge repository.
    #[test]
    fn judges_are_counted_by_the_owners_of_their_repositories_and_a_neutral_one_only_as_a_third_party() {
        const BUYER: u64 = 424_242;      // owns the order's repository
        const MAINTAINER: u64 = 555;     // starts the run there
        const SELLER: u64 = 1_234_567;   // a neutral runner: owner and actor of his own run
        const FIRM: u64 = 9_000;         // owns the judge repository
        let own = Some((BUYER, MAINTAINER));
        let neutral = |who: u64| Some((who, who));
        for (order_owner, who, have) in [
            // one judge is one
            (0, [own, None, None], 1), (BUYER, [None, None, Some((FIRM, 7))], 1),
            // two and three different owners
            (0, [own, neutral(SELLER), None], 2), (BUYER, [own, neutral(SELLER), None], 2), (0, [own, None, Some((FIRM, 7))], 2),
            (0, [own, neutral(SELLER), Some((FIRM, 7))], 3), (BUYER, [own, neutral(SELLER), Some((FIRM, 7))], 3),
            // THE FINDING: the account that started the own run starts the neutral one, in a repository it owns
            (0, [own, neutral(MAINTAINER), None], 1), (BUYER, [own, neutral(MAINTAINER), None], 1),
            // the owner of the order's repository is no third party, whoever started the own run
            (0, [own, neutral(BUYER), None], 1), (BUYER, [None, neutral(BUYER), Some((FIRM, 7))], 1),
            (0, [Some((BUYER, BUYER)), neutral(BUYER), None], 1),
            // the same owner, two repositories: the order's and the judge repository; and a neutral runner who owns the judge repository
            (0, [own, None, Some((BUYER, 7))], 1), (BUYER, [own, None, Some((BUYER, MAINTAINER))], 1), (BUYER, [None, neutral(FIRM), Some((FIRM, 7))], 1),
            (0, [own, neutral(SELLER), Some((BUYER, 7))], 2), (0, [own, neutral(FIRM), Some((FIRM, 7))], 2),
            // a wallet's order whose own repository has not spoken: nothing says the neutral run is a third party's
            (0, [None, neutral(SELLER), Some((FIRM, 7))], 1), (0, [None, neutral(SELLER), None], 0),
            // a Balance's order knows its owner: the neutral run and the judge repository are two
            (BUYER, [None, neutral(SELLER), Some((FIRM, 7))], 2), (BUYER, [None, neutral(SELLER), None], 1),
            // the judge repository's run may be started by anyone: only owners are compared there
            (0, [own, None, Some((FIRM, MAINTAINER))], 2),
            (0, [None, None, None], 0),
        ] {
            assert_eq!(distinct(order_owner, &who), have, "{order_owner} {who:?}");
        }
    }
}
