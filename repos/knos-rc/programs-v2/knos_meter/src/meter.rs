//! The instructions: OpenCredits, WithdrawCredits, SetPlan, Record, CloseMark, RecordBatch, ClaimBatch and Version.
use crate::{err, gh::*, state::*, token::*, *};
use knos_oidc_interface::is_hex;
use solana_program::{account_info::AccountInfo, entrypoint::ProgramResult, msg, program_error::ProgramError, pubkey::Pubkey, system_program};

/// Opens a wallet's Credits for one GitHub owner in one mint, or, sent again by that wallet, pins other workflows.
/// The address holds the wallet, so only its own signature reaches its account.
pub fn open_credits(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let [authority, credits, crtok, mint, auth, token, sys] = take(accounts)?;
    if data.len() != 80 { return Err(ProgramError::InvalidInstructionData); }
    let (owner_id, wf_repo, wf_sha) = (u64_at(data, 0), &data[8..40], &data[40..80]);
    if !authority.is_signer || !authority.is_writable || *auth.key != auth_key(program_id).0 { return Err(err(E_ACCOUNTS)); }
    if owner_id == 0 || !is_hex(wf_sha, 40) { return Err(err(E_TERMS)); }
    let (new, bump) = open(program_id, authority, credits, sys, CREDITS_LEN, &[b"cr", &data[0..8], authority.key.as_ref(), mint.key.as_ref()], E_CREDITS)?;
    if new {
        if !ANY_MINT && !FEE_MINTS.contains(mint.key) { return Err(err(E_MINT)); }
        let m = mint_of(mint, token, true)?;
        let (tk, tb) = crtok_key(program_id, credits.key);
        if *crtok.key != tk { return Err(err(E_ACCOUNTS)); }
        ensure_token_pda(authority, crtok, mint, auth, token, sys, &m, &[b"crtok", credits.key.as_ref(), &[tb]])?;
        let mut d = credits.try_borrow_mut_data()?;
        d[C_VERSION] = 1; d[C_BUMP] = bump; d[C_T22] = m.t22 as u8; d[C_DECIMALS] = m.decimals;
        put_u64(&mut d, C_OWNER_ID, owner_id); put_key(&mut d, C_AUTHORITY, authority.key); put_key(&mut d, C_MINT, mint.key);
    }
    let mut d = credits.try_borrow_mut_data()?;
    d[C_WF_REPO..C_WF_REPO + 32].copy_from_slice(wf_repo);
    d[C_WF_SHA..C_WF_SHA + 40].copy_from_slice(wf_sha);
    msg!("knosm:credits owner={} authority={} mint={} wf={}", owner_id, b58(authority.key), b58(mint.key), String::from_utf8_lossy(wf_sha));
    Ok(())
}

/// Unspent credits go back only to a token account of the wallet that opened them.
pub fn withdraw_credits(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let [authority, credits, crtok, dest, mint, auth, token] = take(accounts)?;
    if data.len() != 8 { return Err(ProgramError::InvalidInstructionData); }
    let c = load_credits(program_id, credits)?;
    if !authority.is_signer || *authority.key != c.authority { return Err(err(E_CREDITS)); }
    let (ak, ab) = auth_key(program_id);
    if *auth.key != ak || *mint.key != c.mint || *crtok.key != crtok_key(program_id, credits.key).0 { return Err(err(E_ACCOUNTS)); }
    let m = mint_of(mint, token, false)?;
    let held = amount_of(crtok, token.key, E_ACCOUNTS)?;
    if !is_owned(dest, token.key, &c.mint, &c.authority) { return Err(err(E_FEE)); }
    let amount = match u64_at(data, 0) { 0 => held, a => a };
    if amount > held { return Err(err(E_FUNDS)); }
    transfer(token, crtok, mint, dest, auth, amount, m.decimals, ab)?;
    msg!("knosm:withdrawn owner={} authority={} mint={} amount={}", c.owner_id, b58(&c.authority), b58(&c.mint), amount);
    Ok(())
}

/// FEE_OWNER lowers one owner's rate until an expiry. The contract is off chain; the rate is on chain.
pub fn set_plan(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let [fee_owner, payer, plan, sys] = take(accounts)?;
    if data.len() != 25 { return Err(ProgramError::InvalidInstructionData); }
    let (owner_id, tier, rate, expiry) = (u64_at(data, 0), data[8], u64_at(data, 9), i64_at(data, 17));
    if !fee_owner.is_signer || (*fee_owner.key != FEE_OWNER && Some(*fee_owner.key) != TEST_FEE_OWNER) { return Err(err(E_FEE_OWNER)); }
    if !payer.is_signer || !payer.is_writable { return Err(err(E_ACCOUNTS)); }
    if owner_id == 0 || !(PLAN_MIN..=FEE).contains(&rate) { return Err(err(E_TERMS)); }
    let (new, bump) = open(program_id, payer, plan, sys, PLAN_LEN, &[b"plan", &data[0..8]], E_ACCOUNTS)?;
    let mut d = plan.try_borrow_mut_data()?;
    if new { d[P_VERSION] = 1; d[P_BUMP] = bump; put_u64(&mut d, P_OWNER_ID, owner_id); }
    d[P_TIER] = tier; put_u64(&mut d, P_RATE, rate); put_i64(&mut d, P_EXPIRY, expiry);
    msg!("knosm:plan owner={} tier={} rate={} expiry={}", owner_id, tier, rate, expiry);
    Ok(())
}

/// The owner's count of this month goes up by `by` (the Plan account, created on first use, started again when the
/// month changes). Returns (the count, the rate that applies now, in millionths of a whole unit).
#[allow(clippy::too_many_arguments)] fn count_month<'a>(program_id: &Pubkey, payer: &AccountInfo<'a>, plan: &AccountInfo<'a>, sys: &AccountInfo<'a>, owner_id: u64, month: u32,
                   now: i64, by: u64) -> Result<(u64, u64), ProgramError> {
    let (new, bump) = open(program_id, payer, plan, sys, PLAN_LEN, &[b"plan", &owner_id.to_le_bytes()], E_ACCOUNTS)?;
    let mut d = plan.try_borrow_mut_data()?;
    if new { d[P_VERSION] = 1; d[P_BUMP] = bump; put_u64(&mut d, P_OWNER_ID, owner_id); }
    if u32_at(&d, P_MONTH) != month { put_u32(&mut d, P_MONTH, month); put_u64(&mut d, P_USED, 0); }
    add(&mut d, P_USED, by)?;
    let rate = u64_at(&d, P_RATE);
    Ok((u64_at(&d, P_USED), if rate != 0 && now < i64_at(&d, P_EXPIRY) { rate } else { FEE }))
}

/// One evaluation that GitHub signed: counted and billed the first time, free and without effect after that.
pub fn record(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, tok, key, credits, crtok, plan, mark, month, fee_tok, mint, auth, token, sys] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
    let c = load_credits(program_id, credits)?;
    let g = github(tok, key, now)?;
    // the workflows are the ones these credits pin: that repository's attest.yml or prove.yml, at that commit
    if (g.wf_file != b"attest.yml" && g.wf_file != b"prove.yml") || g.wf_repo != c.wf_repo || g.wf_sha[..] != c.wf_sha[..] { return Err(err(E_WORKFLOW)); }
    // a re-run keeps the first run's name and inputs whoever starts it: only a first attempt counts
    if !g.first_attempt { return Err(err(E_CLAIMS)); }
    let e = eval_aud(&g.aud)?;
    // the run was in a repository of the buyer it names, and these credits were prepaid for that buyer: nobody else's
    // runs spend them, and nobody else writes this buyer's count
    if g.owner_id != e.buyer || c.owner_id != e.buyer { return Err(err(E_OWNER)); }
    let (ak, ab) = auth_key(program_id);
    if *auth.key != ak || *mint.key != c.mint || *crtok.key != crtok_key(program_id, credits.key).0 { return Err(err(E_ACCOUNTS)); }
    let m = mint_of(mint, token, false)?;

    let (bb, sb, k) = (e.buyer.to_le_bytes(), e.seller.to_le_bytes(), e.key());
    // a mark written before CloseMark existed is shorter and names no payer: it stands, and so does what it billed
    let len = if mark.owner == program_id && mark.data_len() == MARK_LEN_1 { MARK_LEN_1 } else { MARK_LEN };
    let (first, _) = open(program_id, relayer, mark, sys, len, &[b"k", &bb, &k], E_ACCOUNTS)?;
    if !first {
        msg!("knosm:retry buyer={} key={}", e.buyer, hex(&k));
        return Ok(());
    }
    let ym = yyyymm(now);
    let (n, rate) = count_month(program_id, relayer, plan, sys, e.buyer, ym, now, 1)?;
    let fee = if n <= FREE_PER_MONTH { 0 } else { fee_units(rate, m.decimals) };
    if fee > 0 {
        // credits never go below zero: an evaluation they cannot pay for is refused whole, and can be sent again
        if amount_of(crtok, token.key, E_ACCOUNTS)? < fee { return Err(err(E_FUNDS)); }
        if !is_owned(fee_tok, token.key, &c.mint, &FEE_OWNER) { return Err(err(E_FEE)); }
        transfer(token, crtok, mint, fee_tok, auth, fee, m.decimals, ab)?;
    }
    {
        let (new, bump) = open(program_id, relayer, month, sys, MONTH_LEN, &[b"m", &bb, &sb, &ym.to_le_bytes()], E_ACCOUNTS)?;
        let mut d = month.try_borrow_mut_data()?;
        if new { d[M_VERSION] = 1; d[M_BUMP] = bump; put_u32(&mut d, M_MONTH, ym); put_u64(&mut d, M_BUYER, e.buyer); put_u64(&mut d, M_SELLER, e.seller); }
        add(&mut d, M_EVALS, 1)?;
        add(&mut d, if e.accepted { M_ACCEPTED } else { M_REJECTED }, 1)?;
        if e.accepted { add(&mut d, M_VALUE, e.rate)?; }
        add(&mut d, M_FEES, fee)?;
    }
    {
        let mut d = mark.try_borrow_mut_data()?;
        d[K_VERSION] = 2; d[K_VERDICT] = e.accepted as u8;
        put_u32(&mut d, K_MONTH, ym); put_u64(&mut d, K_BUYER, e.buyer); put_u64(&mut d, K_SELLER, e.seller); put_i64(&mut d, K_TIME, now);
        put_u64(&mut d, K_RATE, e.rate); put_u64(&mut d, K_FEE, fee);
        // the relayer's rent comes back when the month of the count has closed and its last token has stopped working
        put_key(&mut d, K_PAYER, relayer.key); put_i64(&mut d, K_CLOSE_AFTER, next_month(now).saturating_add(MARK_GRACE));
    }
    {
        let mut d = credits.try_borrow_mut_data()?;
        add(&mut d, C_SPENT, fee)?;
        add(&mut d, C_EVALS, 1)?;
    }
    msg!("knosm:eval buyer={} seller={} order={} artifact={} policy={} milestone={} verdict={} rate={} fee={} month={} n={} mint={}",
         e.buyer, e.seller, hex(&e.order), String::from_utf8_lossy(&e.artifact), hex(&e.policy), e.milestone, e.accepted as u8, e.rate, fee, ym, n, b58(&c.mint));
    Ok(())
}

/// The rent of a Mark goes back to the relayer that paid it, all of it, once the Mark guards nothing: the month it
/// was counted in has closed and no token GitHub issued in that month is accepted any more (K_CLOSE_AFTER). Only that
/// relayer signs for it: a relayer that leaves a Mark open keeps its evaluation billed for as long as it likes, and
/// nobody else can take a Mark away to have an evaluation billed again.
pub fn close_mark(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [payer, mark] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !payer.is_signer || !payer.is_writable || payer.key == mark.key { return Err(err(E_ACCOUNTS)); }
    // this program creates every account it owns at its kind's length and no two kinds share one: this length is a Mark
    if mark.owner != program_id || mark.data_len() != MARK_LEN { return Err(err(E_MARK)); }
    let (buyer, month) = {
        let d = mark.try_borrow_data()?;
        if d[K_VERSION] != 2 || key_at(&d, K_PAYER) != *payer.key { return Err(err(E_MARK)); }
        if now < i64_at(&d, K_CLOSE_AFTER) { return Err(err(E_EARLY)); }
        (u64_at(&d, K_BUYER), u32_at(&d, K_MONTH))
    };
    let rent = mark.lamports();
    **payer.try_borrow_mut_lamports()? = payer.lamports().checked_add(rent).ok_or(ProgramError::ArithmeticOverflow)?;
    **mark.try_borrow_mut_lamports()? = 0;
    mark.assign(&system_program::ID);
    mark.resize(0)?;
    msg!("knosm:closed buyer={} month={} lamports={}", buyer, month, rent);
    Ok(())
}

/// What every batch is held to, whoever signed it: 1..=MAX_BATCH evaluations, no more accepted than counted, and a
/// month that is the chain's or the one before it (a batch for last month may arrive in the first days of this one).
fn batch_bounds(b: &BatchAud, now: i64) -> ProgramResult {
    let ym = yyyymm(now);
    if b.count == 0 || b.count > MAX_BATCH || b.accepted > b.count || (b.month != ym && b.month != prev_month(ym)) { return Err(err(E_BATCH)); }
    Ok(())
}

/// The Ledger of the batch's (buyer, seller, month) under `seed` (b"l" recorded, b"lc" claimed), created on first use
/// with the relayer's rent, and the one rule that makes a batch token single-use: its seq is the Ledger's next.
fn ledger_open<'a>(program_id: &Pubkey, payer: &AccountInfo<'a>, ledger: &AccountInfo<'a>, sys: &AccountInfo<'a>, seed: &[u8], b: &BatchAud) -> ProgramResult {
    let (new, bump) = open(program_id, payer, ledger, sys, LEDGER_LEN, &[seed, &b.buyer.to_le_bytes(), &b.seller.to_le_bytes(), &b.month.to_le_bytes()], E_ACCOUNTS)?;
    let mut d = ledger.try_borrow_mut_data()?;
    if new {
        d[L_VERSION] = 1; d[L_BUMP] = bump; d[L_KIND] = (seed == b"lc") as u8;
        put_u32(&mut d, L_MONTH, b.month); put_u64(&mut d, L_BUYER, b.buyer); put_u64(&mut d, L_SELLER, b.seller);
    }
    if u64_at(&d, L_NEXT_SEQ) != b.seq { return Err(err(E_SEQ)); }
    Ok(())
}

/// Adds a batch to its Ledger: the totals, the next seq and the running hash. Returns the hash.
fn ledger_add(ledger: &AccountInfo, b: &BatchAud, fee: u64) -> Result<[u8; 32], ProgramError> {
    let mut d = ledger.try_borrow_mut_data()?;
    let chain = b.chain(&d[L_CHAIN..L_CHAIN + 32]);
    add(&mut d, L_NEXT_SEQ, 1)?; add(&mut d, L_EVALS, b.count)?; add(&mut d, L_ACCEPTED, b.accepted)?; add(&mut d, L_VALUE, b.value)?; add(&mut d, L_FEES, fee)?;
    d[L_CHAIN..L_CHAIN + 32].copy_from_slice(&chain);
    Ok(chain)
}

/// Many evaluations in one token that GitHub signed for a run of the buyer: counted and billed once, by seq, with no
/// account per evaluation. The token is held to everything Record holds one to.
pub fn record_batch(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, tok, key, credits, crtok, plan, ledger, fee_tok, mint, auth, token, sys] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
    let c = load_credits(program_id, credits)?;
    let g = github(tok, key, now)?;
    if (g.wf_file != b"attest.yml" && g.wf_file != b"prove.yml") || g.wf_repo != c.wf_repo || g.wf_sha[..] != c.wf_sha[..] { return Err(err(E_WORKFLOW)); }
    if !g.first_attempt { return Err(err(E_CLAIMS)); }
    let b = batch_aud(&g.aud, b"batch")?;
    if g.owner_id != b.buyer || c.owner_id != b.buyer { return Err(err(E_OWNER)); }
    batch_bounds(&b, now)?;
    let (ak, ab) = auth_key(program_id);
    if *auth.key != ak || *mint.key != c.mint || *crtok.key != crtok_key(program_id, credits.key).0 { return Err(err(E_ACCOUNTS)); }
    let m = mint_of(mint, token, false)?;
    ledger_open(program_id, relayer, ledger, sys, b"l", &b)?;

    // the free allowance is the owner's, in the month of the chain's clock, as Record counts it: only the part of this
    // batch that lies above it costs the rate
    let (n, rate) = count_month(program_id, relayer, plan, sys, b.buyer, yyyymm(now), now, b.count)?;
    let billable = n.saturating_sub(FREE_PER_MONTH.max(n - b.count));
    let fee = billable.checked_mul(fee_units(rate, m.decimals)).ok_or(ProgramError::ArithmeticOverflow)?;
    if fee > 0 {
        // credits never go below zero: a batch they cannot pay for is refused whole, and can be sent again
        if amount_of(crtok, token.key, E_ACCOUNTS)? < fee { return Err(err(E_FUNDS)); }
        if !is_owned(fee_tok, token.key, &c.mint, &FEE_OWNER) { return Err(err(E_FEE)); }
        transfer(token, crtok, mint, fee_tok, auth, fee, m.decimals, ab)?;
    }
    let chain = ledger_add(ledger, &b, fee)?;
    {
        let mut d = credits.try_borrow_mut_data()?;
        add(&mut d, C_SPENT, fee)?;
        add(&mut d, C_EVALS, b.count)?;
    }
    msg!("knosm:batch buyer={} seller={} month={} seq={} count={} accepted={} value={} root={} billable={} fee={} n={} chain={} mint={}",
         b.buyer, b.seller, b.month, b.seq, b.count, b.accepted, b.value, hex(&b.root), billable, fee, n, hex(&chain), b58(&c.mint));
    Ok(())
}

/// The seller's own count of the same month, from a run in a repository the seller owns. It costs nothing and moves
/// nothing: it stands beside the buyer's Ledger so that the two can be compared.
pub fn claim_batch(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, tok, key, claim, sys] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
    let g = github(tok, key, now)?;
    let b = batch_aud(&g.aud, b"claim")?;
    // only the seller's own repositories speak for the seller: not the buyer's, not a third party's
    if g.owner_id != b.seller { return Err(err(E_OWNER)); }
    batch_bounds(&b, now)?;
    ledger_open(program_id, relayer, claim, sys, b"lc", &b)?;
    let chain = ledger_add(claim, &b, 0)?;
    msg!("knosm:claim buyer={} seller={} month={} seq={} count={} accepted={} value={} root={} chain={}",
         b.buyer, b.seller, b.month, b.seq, b.count, b.accepted, b.value, hex(&b.root), hex(&chain));
    Ok(())
}

/// Which build this is.
pub fn version(data: &[u8]) -> ProgramResult {
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    msg!("knosm:version {}", VERSION);
    Ok(())
}
