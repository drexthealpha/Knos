//! What an order can promise beyond "paid on a judge's token" (2.1): a holdback kept through a warranty, a standing
//! offer paid once per pull request, a reservation, a cancellation with notice and a kill fee, an assigned payment,
//! and the markers that can be closed once they no longer matter. order_pay.rs calls this file from its hooks.
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
//!   Done ["done", order, pr u64]  65 bytes: this standing order has paid this pull request.
//!   As   ["as", order, payee id]  88 bytes: the wallet this order pays for that payee instead of the payee's own.
//! PayOrder takes, after its payees' accounts: one ["as", order, payee] per payee, in the payees' order (it need not
//! exist, but it cannot be left out: a relayer cannot hide an assignment), then ["done", order, pr](w) for a STANDING
//! order, or ["hb", order](w) for one with a holdback. SettleOrder takes ["as", order, payee] after its sixteen.
//! RefundOrder takes, after its eight, the taker's bind and a token account of his wallet (w) when a kill fee is due.
//!
//! INSTRUCTIONS (the first byte of the data is the tag; (s) signs, (w) is writable):
//!   18 Release     relayer(s,w) order(w) ov(w) hb(w) tip_token(w) fee_token(w) auth rent_to(w) hb_payer(w) mint token_program
//!                  system ata_program, then for each recorded payee, in the record's order: wallet dest_token(w)
//!                  Anyone, once the warranty is over: each recorded wallet receives its part of the holdback (its
//!                  associated token account is created here when it does not exist), the relayer the tip, FEE_OWNER
//!                  what is left; the order, its token account and the record are closed.
//!   19 Revert      relayer(s) revert_token key order(w) ov(w) hb(w) refund_token(w) auth rent_to(w) hb_payer(w) mint token_program
//!                  Inside the warranty, on a token of judge a, b or c (order_judge::judge: the order's own
//!                  repository, a NEUTRAL attest.yml by hand in the runner's own repository, the judge repository)
//!                  issued after the payment with audience knos3:revert:<order>:<head sha>: everything the order
//!                  holds goes back to its funder; all closed. The arbiter rules on payments, not on reverts.
//!   20 Reserve     relayer(s) take_token key order(w)
//!                  A command's token (order_judge::command) with audience knos3:take:<order>:<taker id>:<days>, days
//!                  1..=the order's reserve_days: the pinned fund.yml (the COMMAND job) or prove.yml run in the order's
//!                  own repository, or, for a NEUTRAL order, the pinned attest.yml started by hand in the taker's own
//!                  repository. Its `actor_id` is the taker it names: a person reserves for himself. The order (OPEN,
//!                  not cancelled, not reserved now) is reserved for the taker.
//!   21 Cancel      signer(s) order(w) [cancel_token key]
//!                  A wallet's order: the funding wallet signs. A Balance's order: a command's token with audience
//!                  knos3:cancel:<order> from the pinned fund.yml or prove.yml run in the order's own repository,
//!                  whose actor funded the order or owns the Balance. Once, on an OPEN order: the deadline becomes
//!                  min(deadline, now + NOTICE). PayOrder is not changed by it.
//!   24 Assign      signer(s,w) order bind as(w) system        data: payee id u64, to [32]
//!                  The payee's bound wallet signs (or, once an assignment is set, its current assignee): this
//!                  order's payment for that payee goes to `to`.
//!   27 CloseMarker marker(w) rent_to(w) order
//!                  Anyone. A ["used", ...] marker once no token it stands for can be accepted any more (`order` is
//!                  not read), or a ["done", ...] marker once its order (`order`) is closed: its rent to who paid it.
//!
//! LOGS: knos3:warranty order= held= until=      knos3:released order= payee= amount= to=      knos3:reverted order= amount= head=
//!       knos3:reserved order= taker= until=     knos3:cancelled order= at= deadline=          knos3:kill order= taker= amount= held=
//!       knos3:assigned order= payee= to=
use crate::{err, gh::*, order::*, order_judge::command, order_pay::{judge_ok, Judge, Payee}, pay::bound, state::*, token::*, *};
use knos_oidc::claims::{self, parts};
use solana_program::{account_info::AccountInfo, entrypoint::ProgramResult, msg, program_error::ProgramError, pubkey::Pubkey, system_program};

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
pub const D_ORDER: usize = 33;      // the order: the marker can be closed once nothing is at that address
pub const DONE_LEN: usize = 65;
// As ["as", order, payee id]
pub const A_VERSION: usize = 0;     // 1
pub const A_BUMP: usize = 1;
pub const A_PAYEE: usize = 8;
pub const A_ORDER: usize = 16;
pub const A_TO: usize = 48;         // the wallet that is paid
pub const A_SINCE: usize = 80;      // i64: the `not_before` of the order it was made for: a later order at the same address ignores it
pub const AS_LEN: usize = 88;

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
/// when nothing is left. `per`: the accounts after PayOrder's thirteen (SettleOrder's eleven); `paid`: the order's
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
        mark_done(program_id, relayer, per.get(n * PER + n).ok_or(ProgramError::NotEnoughAccountKeys)?, sys, order.key, pr)?;
        if paid < o.amount {
            // A standing order is kept as what is left of it: `amount` what its payees can still receive, `fee` what
            // is still escrowed for it, `paid` zero. So the fee share of every payment is taken from the fee that is
            // really there, whatever a TopUp did to the amount and the fee in between (the floor makes the fee rate
            // of a small order higher than that of the larger order it is topped up to).
            let share = |p: u64| (o.fee as u128 * p as u128 / o.amount as u128) as u64;
            let (left, took) = (o.amount - paid, share(paid) - share(o.paid));
            let mut d = order.try_borrow_mut_data()?;
            put_u64(&mut d, O_AMOUNT, left); put_u64(&mut d, O_FEE, o.fee - took); put_u64(&mut d, O_PAID, 0);
            if left < o.rate { put_i64(&mut d, O_DEADLINE, o.deadline.min(now - 1)); }
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

/// Marks a pull request as paid by a standing order: creates ["done", order, pr] (rent from `payer`), or refuses with
/// E_REPLAY when it exists. It stores who paid its rent and its order, which is what CloseMarker needs.
fn mark_done<'a>(program_id: &Pubkey, payer: &AccountInfo<'a>, done: &AccountInfo<'a>, sys: &AccountInfo<'a>, order: &Pubkey, pr: u64) -> ProgramResult {
    let prb = pr.to_le_bytes();
    let (key, bump) = Pubkey::find_program_address(&[b"done", order.as_ref(), &prb], program_id);
    if *done.key != key { return Err(err(E_ACCOUNTS)); }
    if done.owner == program_id { return Err(err(E_REPLAY)); }
    if !done.data_is_empty() || *done.owner != system_program::ID { return Err(err(E_ACCOUNTS)); }
    create_pda(payer, done, sys, program_id, DONE_LEN, &[b"done", order.as_ref(), &prb, &[bump]])?;
    let mut d = done.try_borrow_mut_data()?;
    d[0] = 1;
    put_key(&mut d, D_PAYER, payer.key); put_key(&mut d, D_ORDER, order);
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

/// 19 Revert: inside the warranty a judge says the accepted change was reverted: the holdback, and the fee on it,
/// go back to where the order's money came from. The token is a judge's as PayOrder's is (a the order's own
/// repository, b a NEUTRAL attest.yml by hand in the runner's own repository, c the judge repository), issued after
/// the payment. Whoever signs it, the only thing it can do is return what the order still holds to its funder, and
/// only inside the warranty: what was paid stays paid. A ruling is not a revert, so the arbiter signs none.
pub fn revert(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, tok, key, order, ov, hb, refund_tok, auth, rent_to, hb_payer, mint, token] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer { return Err(err(E_ACCOUNTS)); }
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
    let [relayer, tok, key, order] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer { return Err(err(E_ACCOUNTS)); }
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
        let [tok, key] = take(accounts.get(2..).ok_or(ProgramError::NotEnoughAccountKeys)?)?;
        let g = github(tok, key, now)?;
        if g.iat < o.not_before { return Err(err(E_STATE)); }
        if command(&o, &g)? != Judge::Own || (g.actor_id != o.funder_id && g.actor_id != o.owner_id) { return Err(err(E_CLAIMS)); }
        aud_of::<3>(&g.aud, b"cancel", order.key)?;
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
/// same funder, issue and seq, funded again) is not this order's.
pub fn assigned(program_id: &Pubkey, order: &Pubkey, o: &Order, a: &AccountInfo, payee: u64) -> Result<Option<Pubkey>, ProgramError> {
    if *a.key != as_key(program_id, order, payee).0 { return Err(err(E_PAYEE)); }
    if a.owner != program_id || a.data_len() != AS_LEN { return Ok(None); }
    let d = a.try_borrow_data()?;
    Ok(if i64_at(&d, A_SINCE) == o.not_before { Some(key_at(&d, A_TO)) } else { None })
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
    put_u64(&mut d, A_PAYEE, payee); put_key(&mut d, A_ORDER, order.key); put_key(&mut d, A_TO, &to); put_i64(&mut d, A_SINCE, o.not_before);
    msg!("knos3:assigned order={} payee={} to={}", b58(order.key), payee, b58(&to));
    Ok(())
}

// ---- 5. markers ------------------------------------------------------------------------------------------------

/// 27 CloseMarker: a marker that can no longer matter is closed and its rent goes back to whoever paid it. The two
/// kinds are told by their length (no other account of this program has either):
///   ["used", sig]: after the time stored in it, by which no instruction can accept a token used when it was made
///                  (state::mark_used: an hour after the latest such a token can expire, plus the verifier's lateness);
///   ["done", order, pr]: once nothing is at its order's address (the order was paid out or refunded).
pub fn close_marker(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [marker, rent_to, order] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if marker.owner != program_id { return Err(err(E_ACCOUNTS)); }
    let (payer, free) = {
        let d = marker.try_borrow_data()?;
        match d.len() {
            USED_LEN => (key_at(&d, U_PAYER), now > i64_at(&d, U_AFTER)),
            DONE_LEN => (key_at(&d, D_PAYER), *order.key == key_at(&d, D_ORDER) && order.owner != program_id),
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
                refund_to: Pubkey::default(), rent_to: Pubkey::default(), mint: Pubkey::default(), terms: [0; 32], wf_repo: [0; 32], wf_sha: [0; 40] }
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
        let mut lens = [BALANCE_LEN, JOB_LEN, BIND_LEN, REP_LEN, PAIR_LEN, BALX_LEN, PLAN_LEN, ORDER_LEN, USED_LEN, PAUSE_LEN, RATE_LEN, HB_LEN, DONE_LEN, AS_LEN];
        lens.sort_unstable();
        assert!(lens.windows(2).all(|w| w[0] != w[1]));
        assert_eq!(H_ENTRIES + MAX_PAYEES * H_ENTRY, HB_LEN);
    }
}
