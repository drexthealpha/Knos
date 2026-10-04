//! Work orders (2.1): what an order is on chain (`Order`, `load_order`, the options a funder fixes, the fund audience)
//! and money coming into one: FundOrderWallet, FundOrderBalance, TopUp. Money leaving an order is in order_pay.rs.
//!
//! An order's money is alone in its own token account ["ov", order], owned by ["auth"]: the amount the payees will
//! receive plus the fee, which the funder pays on top. Nothing else is ever credited to an order: funding and TopUp
//! require that the account received exactly what they asked for.
use crate::{err, fund::*, gh::*, state::*, token::*, *};
use knos_oidc::claims::{self, parts};
use solana_program::{account_info::AccountInfo, entrypoint::ProgramResult, hash::hashv, msg, program_error::ProgramError, pubkey::Pubkey};

pub const OPTS_LEN: usize = 48;
/// What a funder fixes beside the amount and the terms. 48 bytes: flags u8 @0 (PRIVATE 2, NEUTRAL 4, STANDING 8; the
/// program sets FAUCET and TOKEN2022 itself), holdback_bps u16 @1, warranty_days u16 @3, kill_bps u16 @5,
/// reserve_days u8 @7, rate u64 @8, arbiter_id u64 @16, judge_repo_id u64 @24, salted u8 @32 (1: a private order,
/// whose 32-byte scope follows in the instruction data), 15 zero bytes.
pub struct Opts {
    pub flags: u8, pub holdback_bps: u16, pub warranty_days: u16, pub kill_bps: u16, pub reserve_days: u8, pub rate: u64, pub arbiter_id: u64,
    pub judge_repo_id: u64, pub salted: bool,
}
/// The options, read and checked: holdback at most MAX_HOLDBACK_BPS and only with a warranty, warranty at most
/// MAX_WARRANTY_DAYS, kill fee at most MAX_KILL_BPS; a STANDING order has a rate between 1 and its amount, any other
/// has none; PRIVATE and `salted` go together and need a judge repository (no run in the order's own repository can
/// be told, since its id is not on chain); no bit and no byte that means nothing yet.
pub fn opts_of(o: &[u8], amount: u64) -> Result<Opts, ProgramError> {
    if o.len() != OPTS_LEN { return Err(ProgramError::InvalidInstructionData); }
    let v = Opts { flags: o[0], holdback_bps: u16_at(o, 1), warranty_days: u16_at(o, 3), kill_bps: u16_at(o, 5), reserve_days: o[7], rate: u64_at(o, 8),
                   arbiter_id: u64_at(o, 16), judge_repo_id: u64_at(o, 24), salted: o[32] == 1 };
    let standing = v.flags & F_STANDING != 0;
    let private = v.flags & F_PRIVATE != 0;
    let ok = v.flags & !(F_PRIVATE | F_NEUTRAL | F_STANDING) == 0 && o[32] <= 1 && o[33..] == [0u8; 15]
        && v.holdback_bps <= MAX_HOLDBACK_BPS && v.warranty_days <= MAX_WARRANTY_DAYS && v.kill_bps <= MAX_KILL_BPS
        && (v.holdback_bps == 0 || v.warranty_days > 0)
        && (if standing { v.rate >= 1 && v.rate <= amount } else { v.rate == 0 })
        && private == v.salted && (!private || v.judge_repo_id != 0);
    if !ok { return Err(err(E_TERMS)); }
    Ok(v)
}

/// The scope of a public order: sha256("knos3:scope" || repo_id u64 LE || issue u64 LE).
pub fn public_scope(repo: u64, issue: u64) -> [u8; 32] { hashv(&[b"knos3:scope", &repo.to_le_bytes(), &issue.to_le_bytes()]).to_bytes() }

pub struct Order {
    pub state: u8, pub mode: u8, pub kind: u8, pub flags: u8, pub decimals: u8, pub reserve_days: u8, pub repo: u64, pub issue: u64, pub scope: [u8; 32],
    pub seq: u32, pub holdback_bps: u16, pub kill_bps: u16, pub fee_bps: u16, pub amount: u64, pub fee: u64, pub rate: u64, pub paid: u64,
    pub deadline: i64, pub not_before: i64, pub hold_until: i64, pub warranty_s: i64, pub reserved_by: u64, pub reserved_until: i64, pub cancel_at: i64,
    pub payee: u64, pub funder_id: u64, pub owner_id: u64, pub arbiter_id: u64, pub judge_repo_id: u64, pub source: Pubkey, pub refund_to: Pubkey,
    pub rent_to: Pubkey, pub mint: Pubkey, pub terms: [u8; 32], pub wf_repo: [u8; 32], pub wf_sha: [u8; 40],
}
impl Order {
    pub fn is(&self, flag: u8) -> bool { self.flags & flag != 0 }
}
/// An order, read after checking that this program owns the account, that it has an order's length and version, and
/// that its address is the one its own fields derive. An order that was paid out or refunded is gone.
pub fn load_order(program_id: &Pubkey, a: &AccountInfo) -> Result<Order, ProgramError> {
    if a.owner != program_id || a.data_len() != ORDER_LEN { return Err(err(E_ORDER)); }
    let d = a.try_borrow_data()?;
    let seeds: [&[u8]; 5] = [b"ord", &d[O_SCOPE..O_SCOPE + 32], &d[O_SOURCE..O_SOURCE + 32], &d[O_SEQ..O_SEQ + 4], &[d[O_BUMP]]];
    if d[O_VERSION] != 2 || Pubkey::create_program_address(&seeds, program_id) != Ok(*a.key) { return Err(err(E_ORDER)); }
    Ok(Order {
        state: d[O_STATE], mode: d[O_MODE], kind: d[O_KIND], flags: d[O_FLAGS], decimals: d[O_DECIMALS], reserve_days: d[O_RESERVE_DAYS],
        repo: u64_at(&d, O_REPO), issue: u64_at(&d, O_ISSUE), scope: d[O_SCOPE..O_SCOPE + 32].try_into().unwrap(), seq: u32_at(&d, O_SEQ),
        holdback_bps: u16_at(&d, O_HOLDBACK_BPS), kill_bps: u16_at(&d, O_KILL_BPS), fee_bps: u16_at(&d, O_FEE_BPS), amount: u64_at(&d, O_AMOUNT),
        fee: u64_at(&d, O_FEE), rate: u64_at(&d, O_RATE), paid: u64_at(&d, O_PAID), deadline: i64_at(&d, O_DEADLINE),
        not_before: i64_at(&d, O_NOT_BEFORE), hold_until: i64_at(&d, O_HOLD_UNTIL), warranty_s: i64_at(&d, O_WARRANTY_S),
        reserved_by: u64_at(&d, O_RESERVED_BY), reserved_until: i64_at(&d, O_RESERVED_UNTIL), cancel_at: i64_at(&d, O_CANCEL_AT),
        payee: u64_at(&d, O_PAYEE), funder_id: u64_at(&d, O_FUNDER_ID), owner_id: u64_at(&d, O_OWNER_ID), arbiter_id: u64_at(&d, O_ARBITER_ID),
        judge_repo_id: u64_at(&d, O_JUDGE_REPO), source: key_at(&d, O_SOURCE), refund_to: key_at(&d, O_REFUND_TO), rent_to: key_at(&d, O_RENT_TO),
        mint: key_at(&d, O_MINT), terms: d[O_TERMS..O_TERMS + 32].try_into().unwrap(), wf_repo: d[O_WF_REPO..O_WF_REPO + 32].try_into().unwrap(),
        wf_sha: d[O_WF_SHA..O_WF_SHA + 40].try_into().unwrap(),
    })
}
/// The order's own accounts, as every instruction on an existing order takes them: its token account ["ov", order],
/// ["auth"], its mint and that mint's token program. Returns the mint and the bump ["auth"] signs with.
pub fn order_accounts(program_id: &Pubkey, o: &Order, order: &Pubkey, ov: &AccountInfo, auth: &AccountInfo, mint: &AccountInfo,
                      token: &AccountInfo) -> Result<(Mint, u8), ProgramError> {
    let (ak, ab) = auth_key(program_id);
    if *ov.key != ov_key(program_id, order).0 || *auth.key != ak || *mint.key != o.mint { return Err(err(E_ACCOUNTS)); }
    let m = mint_of(mint, token, false)?;
    if m.t22 != o.is(F_TOKEN2022) { return Err(err(E_MINT)); }
    Ok((m, ab))
}

/// knos3:fund:<issue>:<amount units>:<mode 0|1>:<terms hash hex>:<work seconds>:<balance address>:<seq>:<opts hex>
pub struct OrderFundAud { pub issue: u64, pub amount: u64, pub mode: u8, pub terms: [u8; 32], pub work: i64, pub seq: u32, pub opts: [u8; OPTS_LEN] }
/// `balance`: the Balance the instruction is about to spend or fill; the audience must name it as Solana prints it.
pub fn order_fund_aud(aud: &[u8], balance: &Pubkey) -> Result<OrderFundAud, ProgramError> {
    let [k, f, issue, amount, mode, terms, work, named, seq, opts] = parts::<10>(aud).ok_or_else(|| err(E_AUD))?;
    if k != b"knos3" || f != b"fund" || (mode != b"0" && mode != b"1") || named != b58(balance).as_bytes() || !claims::is_hex(opts, 2 * OPTS_LEN) {
        return Err(err(E_AUD));
    }
    let hex = |c: u8| if c <= b'9' { c - b'0' } else { c - b'a' + 10 };
    let mut o = [0u8; OPTS_LEN];
    for (k, b) in o.iter_mut().enumerate() { *b = hex(opts[2 * k]) << 4 | hex(opts[2 * k + 1]); }
    let seq = u32::try_from(n(seq)?).map_err(|_| err(E_AUD))?;
    Ok(OrderFundAud { issue: n(issue)?, amount: n(amount)?, mode: mode[0] - b'0', terms: claims::unhex32(terms).ok_or_else(|| err(E_AUD))?,
                      work: n(work)? as i64, seq, opts: o })
}

/// What a new order is, beyond what its accounts say. `bps`: the fee rate (FEE_BPS, or the owner's Plan).
struct NewOrder<'x> {
    repo: u64, issue: u64, scope: [u8; 32], seq: u32, amount: u64, bps: u64, work: i64, mode: u8, kind: u8, faucet: bool, funder_id: u64, owner_id: u64,
    not_before: i64, source: &'x Pubkey, refund_to: &'x Pubkey, terms: [u8; 32], wf_repo: &'x [u8], wf_sha: &'x [u8], opts: Opts,
}
/// The accounts of an order's funding. `auth_signs`: the money comes from a Balance's token account (["auth"] signs
/// the transfer); otherwise from a token account whose authority signed the transaction.
struct Escrow<'a, 'b> {
    payer: &'b AccountInfo<'a>, order: &'b AccountInfo<'a>, ov: &'b AccountInfo<'a>, from: &'b AccountInfo<'a>, authority: &'b AccountInfo<'a>,
    mint: &'b AccountInfo<'a>, auth: &'b AccountInfo<'a>, token: &'b AccountInfo<'a>, sys: &'b AccountInfo<'a>, auth_signs: bool,
}

/// An order's bounds: the amount between ORDER_MIN_AMOUNT and MAX_AMOUNT whole units of its mint, the work time and
/// the mode as a job's.
pub fn order_terms_ok(amount: u64, work: i64, mode: u8, decimals: u8) -> bool {
    (units(ORDER_MIN_AMOUNT, decimals)..=units(MAX_AMOUNT, decimals)).contains(&amount) && (MIN_WORK..=MAX_WORK).contains(&work) && mode <= 1
}

/// Moves `amount` from `from` into the order's token account and requires that it arrived whole: an order is never
/// credited with more than its account holds, nor with less than its funder was charged.
#[allow(clippy::too_many_arguments)]
fn pay_in<'a>(token: &AccountInfo<'a>, from: &AccountInfo<'a>, mint: &AccountInfo<'a>, ov: &AccountInfo<'a>, authority: &AccountInfo<'a>, amount: u64,
              m: &Mint, auth_bump: Option<u8>) -> ProgramResult {
    let before = amount_of(ov, token.key, E_ACCOUNTS)?;
    transfer(token, from, mint, ov, authority, amount, m.decimals, auth_bump)?;
    if amount_of(ov, token.key, E_ACCOUNTS)?.checked_sub(before) != Some(amount) { return Err(err(E_MINT)); }
    Ok(())
}

/// Creates the order ["ord", scope, source, seq] (it must not exist) and its token account ["ov", order], and moves
/// the amount plus the fee into it. Returns the fee.
fn escrow<'a>(program_id: &Pubkey, e: &Escrow<'a, '_>, m: &Mint, n: &NewOrder, json: Option<&[u8]>, now: i64) -> Result<u64, ProgramError> {
    let (ak, ab) = auth_key(program_id);
    if *e.auth.key != ak { return Err(err(E_ACCOUNTS)); }
    if !order_terms_ok(n.amount, n.work, n.mode, m.decimals) { return Err(err(E_TERMS)); }
    let seq = n.seq.to_le_bytes();
    let (new, bump) = open(program_id, e.payer, e.order, e.sys, ORDER_LEN, &[b"ord", &n.scope, n.source.as_ref(), &seq], E_ORDER)?;
    if !new { return Err(err(E_ORDER)); }
    let (ok, ob) = ov_key(program_id, e.order.key);
    if *e.ov.key != ok || !e.ov.data_is_empty() { return Err(err(E_ACCOUNTS)); }
    ensure_token_pda(e.payer, e.ov, e.mint, e.auth, e.token, e.sys, m, &[b"ov", e.order.key.as_ref(), &[ob]])?;
    let fee = order_fee(n.amount, n.bps, m.decimals);
    let total = n.amount.checked_add(fee).ok_or(ProgramError::ArithmeticOverflow)?;
    pay_in(e.token, e.from, e.mint, e.ov, e.authority, total, m, if e.auth_signs { Some(ab) } else { None })?;
    let flags = n.opts.flags | if n.faucet { F_FAUCET } else { 0 } | if m.t22 { F_TOKEN2022 } else { 0 };
    let deadline = now.saturating_add(n.work);
    let mut d = e.order.try_borrow_mut_data()?;
    d[O_VERSION] = 2; d[O_STATE] = OPEN; d[O_MODE] = n.mode; d[O_KIND] = n.kind; d[O_FLAGS] = flags; d[O_BUMP] = bump; d[O_DECIMALS] = m.decimals;
    d[O_RESERVE_DAYS] = n.opts.reserve_days;
    put_u64(&mut d, O_REPO, n.repo); put_u64(&mut d, O_ISSUE, n.issue); d[O_SCOPE..O_SCOPE + 32].copy_from_slice(&n.scope);
    put_u32(&mut d, O_SEQ, n.seq); put_u16(&mut d, O_HOLDBACK_BPS, n.opts.holdback_bps); put_u16(&mut d, O_KILL_BPS, n.opts.kill_bps);
    put_u64(&mut d, O_AMOUNT, n.amount); put_u64(&mut d, O_FEE, fee); put_u64(&mut d, O_RATE, n.opts.rate);
    put_i64(&mut d, O_DEADLINE, deadline); put_i64(&mut d, O_NOT_BEFORE, n.not_before);
    put_i64(&mut d, O_WARRANTY_S, n.opts.warranty_days as i64 * 86_400);
    put_u64(&mut d, O_FUNDER_ID, n.funder_id); put_u64(&mut d, O_OWNER_ID, n.owner_id); put_u64(&mut d, O_ARBITER_ID, n.opts.arbiter_id);
    put_u64(&mut d, O_JUDGE_REPO, n.opts.judge_repo_id);
    put_key(&mut d, O_SOURCE, n.source); put_key(&mut d, O_REFUND_TO, n.refund_to); put_key(&mut d, O_RENT_TO, e.payer.key);
    put_key(&mut d, O_MINT, e.mint.key);
    d[O_TERMS..O_TERMS + 32].copy_from_slice(&n.terms);
    d[O_WF_REPO..O_WF_REPO + 32].copy_from_slice(n.wf_repo);
    d[O_WF_SHA..O_WF_SHA + 40].copy_from_slice(n.wf_sha);
    put_u16(&mut d, O_FEE_BPS, n.bps as u16);
    msg!("knos3:funded order={} repo={} issue={} seq={} amount={} fee={} mode={} by={} source={} flags={} deadline={}", b58(e.order.key), n.repo, n.issue,
         n.seq, n.amount, fee, n.mode, n.funder_id, b58(n.source), flags, deadline);
    // the terms of a public order are public and cannot change; a private order's are a hash only (it is in the account)
    if let Some(json) = json { msg!("knos3:terms {}", core::str::from_utf8(json).map_err(|_| err(E_TERMS))?); }
    Ok(fee)
}

/// 15 FundOrderWallet: any wallet funds an order for an issue of any public repository with its own money, naming the
/// workflows whose signed run can pay it. Nothing is needed in that repository.
/// data: issue u64 @0, repo_id u64 @8, amount u64 @16, mode u8 @24, work i64 @25, seq u32 @33, opts [48] @37,
/// wf_repo [32] @85, wf_sha [40] @117, then the terms JSON @157. A PRIVATE order (opts): repo_id and issue are 0, the
/// scope [32] is @157 and the terms are their 32-byte hash @189.
pub fn fund_order_wallet(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [funder, order, ov, funder_tok, mint, auth, token, sys, pause] = take(accounts)?;
    if data.len() < 157 { return Err(ProgramError::InvalidInstructionData); }
    if !funder.is_signer || !funder.is_writable { return Err(err(E_ACCOUNTS)); }
    not_paused(program_id, pause, now)?;
    let m = mint_of(mint, token, true)?;
    let (issue, repo, amount, mode, work, seq) = (u64_at(data, 0), u64_at(data, 8), u64_at(data, 16), data[24], i64_at(data, 25), u32_at(data, 33));
    let opts = opts_of(&data[37..85], amount)?;
    let (wf_repo, wf_sha, rest) = (&data[85..117], &data[117..157], &data[157..]);
    if !claims::is_hex(wf_sha, 40) { return Err(err(E_TERMS)); }
    let (scope, terms, json) = if opts.salted {
        if rest.len() != 64 || repo != 0 || issue != 0 { return Err(err(E_TERMS)); }
        (rest[..32].try_into().unwrap(), rest[32..].try_into().unwrap(), None)
    } else {
        if repo == 0 { return Err(err(E_TERMS)); }
        (public_scope(repo, issue), terms_hash(rest)?, Some(rest))
    };
    let faucet = DEVNET && *mint.key == faucet_mint(program_id).0;
    escrow(program_id, &Escrow { payer: funder, order, ov, from: funder_tok, authority: funder, mint, auth, token, sys, auth_signs: false }, &m,
           &NewOrder { repo, issue, scope, seq, amount, bps: FEE_BPS, work, mode, kind: 0, faucet, funder_id: 0, owner_id: 0,
                       not_before: now.saturating_sub(CLOCK_SLACK), source: funder.key, refund_to: funder.key, terms, wf_repo, wf_sha, opts }, json, now)?;
    Ok(())
}

/// 16 FundOrderBalance: one comment funds an order from a Balance. Anyone may relay the token; what it can do is fixed
/// by GitHub's signature, and it does it once: its marker ["used", sha256(signature)] is made here.
/// data: the terms JSON, whose hash the audience carries. A PRIVATE order: its scope [32] then its terms hash [32]
/// (order_judge::funded).
pub fn fund_order_balance(program_id: &Pubkey, accounts: &[AccountInfo], json: &[u8], now: i64) -> ProgramResult {
    let [relayer, tok, key, balance, baltok, balx, plan, order, ov, used, mint, auth, token, sys, pause] = take(accounts)?;
    if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
    not_paused(program_id, pause, now)?;
    let b = load_balance(program_id, balance)?;
    if *mint.key != b.mint || *baltok.key != baltok_key(program_id, balance.key).0 { return Err(err(E_ACCOUNTS)); }
    let m = mint_of(mint, token, true)?;
    let g = crate::fund::fund_run_any(tok, key, now)?;
    let f = order_fund_aud(&g.aud, balance.key)?;
    may_spend(&b, &g)?;
    let opts = opts_of(&f.opts, f.amount)?;
    // a run by hand or by schedule funds a PRIVATE order only (its attestor has no comment to react to)
    if crate::fund::by_hand_or_schedule(&g) && opts.flags & F_PRIVATE == 0 { return Err(err(E_CLAIMS)); }
    // what is funded: a public order of the token's repository, or a private one of its judge repository (order_judge.rs)
    let n = crate::order_judge::funded(&opts, &f, &g, json)?;
    if b.cap != 0 && f.amount > b.cap { return Err(err(E_CAP)); }
    let bps = plan_bps(program_id, plan, b.owner_id, now)?;
    let total = f.amount.checked_add(order_fee(f.amount, bps, m.decimals)).ok_or(ProgramError::ArithmeticOverflow)?;
    // the limits count what leaves the Balance: the amount and the fee on top of it
    spend_x(program_id, &b, balance.key, Some(balx), g.repo_id, &g.wf_sha, total, now)?;
    mark_used(program_id, relayer, used, sys, &sig_hash(tok)?)?;
    if amount_of(baltok, token.key, E_ACCOUNTS)? < total { return Err(err(E_FUNDS)); }
    let faucet = b.faucet || (DEVNET && *mint.key == faucet_mint(program_id).0);
    escrow(program_id, &Escrow { payer: relayer, order, ov, from: baltok, authority: auth, mint, auth, token, sys, auth_signs: true }, &m,
           &NewOrder { repo: n.repo, issue: n.issue, scope: n.scope, seq: f.seq, amount: f.amount, bps, work: f.work,
                       mode: f.mode, kind: 1, faucet, funder_id: g.actor_id, owner_id: b.owner_id, not_before: g.iat, source: balance.key,
                       refund_to: baltok.key, terms: n.terms, wf_repo: &g.wf_repo, wf_sha: &g.wf_sha, opts }, n.json, now)?;
    let mut d = balance.try_borrow_mut_data()?;
    let spent = u64_at(&d, B_SPENT).saturating_add(total);
    put_u64(&mut d, B_SPENT, spent);
    Ok(())
}

/// 23 TopUp: more money for an open order from where its money came: the funding wallet signs (a wallet's order), or
/// the wallet that opened the Balance signs and the Balance's token account pays (a Balance's order: `balance` is
/// that Balance; for a wallet's order the account is not read). The fee on the new amount is charged at the rate
/// fixed at funding. Not paused; the order is OPEN before its deadline; the new amount is within MAX_AMOUNT.
/// data: add u64 (what is added to the amount; the fee comes on top).
pub fn top_up(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [signer, order, ov, from, balance, mint, auth, token, pause] = take(accounts)?;
    if data.len() != 8 { return Err(ProgramError::InvalidInstructionData); }
    if !signer.is_signer { return Err(err(E_ACCOUNTS)); }
    not_paused(program_id, pause, now)?;
    let o = load_order(program_id, order)?;
    if o.state != OPEN || now > o.deadline { return Err(err(E_STATE)); }
    let (m, ab) = order_accounts(program_id, &o, order.key, ov, auth, mint, token)?;
    let add = u64_at(data, 0);
    let amount = o.amount.checked_add(add).filter(|a| add > 0 && *a <= units(MAX_AMOUNT, m.decimals)).ok_or_else(|| err(E_TERMS))?;
    let fee = order_fee(amount, o.fee_bps as u64, m.decimals).max(o.fee);
    let total = add.checked_add(fee - o.fee).ok_or(ProgramError::ArithmeticOverflow)?;
    if o.kind == 1 {
        let b = load_balance(program_id, balance)?;
        if *balance.key != o.source || *signer.key != b.authority || *from.key != o.refund_to { return Err(err(E_BALANCE)); }
        pay_in(token, from, mint, ov, auth, total, &m, Some(ab))?;
    } else {
        if *signer.key != o.source { return Err(err(E_ACCOUNTS)); }
        pay_in(token, from, mint, ov, signer, total, &m, None)?;
    }
    let mut d = order.try_borrow_mut_data()?;
    put_u64(&mut d, O_AMOUNT, amount); put_u64(&mut d, O_FEE, fee);
    msg!("knos3:topup order={} add={} amount={} fee={}", b58(order.key), add, amount, fee);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn opts(flags: u8, holdback: u16, warranty: u16, kill: u16, rate: u64, judge: u64, salted: u8) -> [u8; OPTS_LEN] {
        let mut o = [0u8; OPTS_LEN];
        o[0] = flags; o[1..3].copy_from_slice(&holdback.to_le_bytes()); o[3..5].copy_from_slice(&warranty.to_le_bytes());
        o[5..7].copy_from_slice(&kill.to_le_bytes()); o[7] = 7; o[8..16].copy_from_slice(&rate.to_le_bytes());
        o[16..24].copy_from_slice(&77u64.to_le_bytes()); o[24..32].copy_from_slice(&judge.to_le_bytes()); o[32] = salted;
        o
    }

    #[test]
    fn options_are_read_and_bounded() {
        let v = opts_of(&opts(F_NEUTRAL | F_STANDING, 5000, 90, 2000, 5, 9, 0), 10).ok().unwrap();
        assert_eq!((v.flags, v.holdback_bps, v.warranty_days, v.kill_bps, v.reserve_days, v.rate, v.arbiter_id, v.judge_repo_id, v.salted),
                   (F_NEUTRAL | F_STANDING, 5000, 90, 2000, 7, 5, 77, 9, false));
        assert!(opts_of(&opts(0, 0, 0, 0, 0, 0, 0), 10).is_ok() && opts_of(&opts(F_PRIVATE, 0, 0, 0, 0, 9, 1), 10).is_ok());
        let mut junk = opts(0, 0, 0, 0, 0, 0, 0);
        junk[40] = 1;
        for bad in [opts(0, 5001, 90, 0, 0, 0, 0), opts(0, 100, 91, 0, 0, 0, 0), opts(0, 0, 0, 2001, 0, 0, 0), opts(0, 100, 0, 0, 0, 0, 0),
                    opts(F_STANDING, 0, 0, 0, 0, 0, 0), opts(F_STANDING, 0, 0, 0, 11, 0, 0), opts(0, 0, 0, 0, 5, 0, 0), opts(F_FAUCET, 0, 0, 0, 0, 0, 0),
                    opts(F_TOKEN2022, 0, 0, 0, 0, 0, 0), opts(32, 0, 0, 0, 0, 0, 0), opts(F_PRIVATE, 0, 0, 0, 0, 9, 0), opts(0, 0, 0, 0, 0, 9, 1),
                    opts(F_PRIVATE, 0, 0, 0, 0, 0, 1), opts(0, 0, 0, 0, 0, 0, 2), junk] {
            assert!(opts_of(&bad, 10).err() == Some(err(E_TERMS)), "{bad:?}");
        }
    }

    #[test]
    fn a_fund_audience_of_an_order_names_its_balance_its_seq_and_its_options() {
        let (terms, key, o) = ("ab".repeat(32), Pubkey::new_from_array([7; 32]), opts(F_NEUTRAL, 1000, 30, 500, 0, 0, 0));
        let hex: String = o.iter().map(|b| format!("{b:02x}")).collect();
        let aud = format!("knos3:fund:7:5000000:1:{terms}:3600:{key}:3:{hex}");
        let f = order_fund_aud(aud.as_bytes(), &key).ok().unwrap();
        assert_eq!((f.issue, f.amount, f.mode, f.terms, f.work, f.seq, f.opts), (7, 5_000_000, 1, [0xab; 32], 3600, 3, o));
        for bad in [aud.replace("knos3", "knos2"), aud.replace(":3:", ":4294967296:"), format!("{aud}00"), aud[..aud.len() - 2].to_string(),
                    aud.to_uppercase(), format!("{aud}:x"), format!("knos3:fund:7:5000000:1:{terms}:3600:{key}:{hex}")] {
            assert!(order_fund_aud(bad.as_bytes(), &key).is_err(), "{bad}");
        }
        assert!(order_fund_aud(aud.as_bytes(), &Pubkey::new_from_array([8; 32])).is_err());
        assert_ne!(public_scope(1, 2), public_scope(2, 1));
    }
}
