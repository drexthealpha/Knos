//! Money going out of escrow: Pay and Settle (to the payee), Refund (back to the funder), and Bind (the wallet a
//! GitHub user is paid at).
use crate::{err, gh::*, state::*, token::*, *};
use solana_program::{account_info::AccountInfo, entrypoint::ProgramResult, hash::hashv, msg, program_error::ProgramError, pubkey::Pubkey};

/// The accounts of a payment, as Pay and Settle list them after the job.
struct Payout<'a, 'b> {
    relayer: &'b AccountInfo<'a>, job: &'b AccountInfo<'a>, dest: &'b AccountInfo<'a>, rep: &'b AccountInfo<'a>, pair: &'b AccountInfo<'a>,
    vault: &'b AccountInfo<'a>, fee_tok: &'b AccountInfo<'a>, auth: &'b AccountInfo<'a>, rent_to: &'b AccountInfo<'a>, mint: &'b AccountInfo<'a>,
    token: &'b AccountInfo<'a>, sys: &'b AccountInfo<'a>,
}

/// The wallet bound to a GitHub user, from ["bind", user]; None when the user has not bound one. The account must be
/// that address: a relayer cannot hide a Bind by passing something else.
pub fn bound(program_id: &Pubkey, bind: &AccountInfo, user: u64) -> Result<Option<Pubkey>, ProgramError> {
    if *bind.key != Pubkey::find_program_address(&[b"bind", &user.to_le_bytes()], program_id).0 { return Err(err(E_PAYEE)); }
    if bind.owner != program_id || bind.data_len() != BIND_LEN { return Ok(None); }
    Ok(Some(key_at(&bind.try_borrow_data()?, BD_WALLET)))
}
/// The mint's vault and ["auth"], by address. Returns the bump ["auth"] signs with.
fn vault_of(program_id: &Pubkey, vault: &AccountInfo, auth: &AccountInfo, mint: &Pubkey) -> Result<u8, ProgramError> {
    let (ak, ab) = auth_key(program_id);
    if *vault.key != vault_key(program_id, mint).0 || *auth.key != ak { return Err(err(E_ACCOUNTS)); }
    Ok(ab)
}
/// The job's own mint and token program, and the account its rent goes back to.
fn job_accounts(j: &Job, mint: &AccountInfo, token: &AccountInfo, rent_to: &AccountInfo) -> Result<Mint, ProgramError> {
    if *rent_to.key != j.rent_to || *mint.key != j.mint { return Err(err(E_ACCOUNTS)); }
    let m = mint_of(mint, token, false)?;
    if m.t22 != j.t22 { return Err(err(E_MINT)); }
    Ok(m)
}

/// Pays a job: the fee to a token account of FEE_OWNER, the rest to a token account of `wallet`, both of the job's
/// mint; the payee's record updated; the job closed, its rent back to whoever paid it. Exactly the job's amount
/// leaves the vault.
fn pay_out<'a>(program_id: &Pubkey, a: &Payout<'a, '_>, j: &Job, payee: u64, wallet: &Pubkey, now: i64) -> ProgramResult {
    let m = job_accounts(j, a.mint, a.token, a.rent_to)?;
    let bump = vault_of(program_id, a.vault, a.auth, &j.mint)?;
    // never into this program's own accounts (a vault, a Balance): money sent there would belong to no job
    if wallet == a.auth.key || !is_owned(a.dest, a.token.key, &j.mint, wallet) || !is_owned(a.fee_tok, a.token.key, &j.mint, &FEE_OWNER) {
        return Err(err(E_PAYEE));
    }
    let fee = fee_of(j.amount, m.decimals);
    let net = j.amount - fee;
    if fee > 0 { transfer(a.token, a.vault, a.mint, a.fee_tok, a.auth, fee, m.decimals, Some(bump))?; }
    if net > 0 { transfer(a.token, a.vault, a.mint, a.dest, a.auth, net, m.decimals, Some(bump))?; }
    let p = Paid { faucet: j.faucet, kind: j.kind, owner_id: j.owner_id, funder_id: j.funder_id, source: &j.source, mint: &j.mint };
    record(program_id, a.relayer, a.rep, a.pair, a.sys, &p, payee, wallet, net, now)?;
    msg!("knos2:paid repo={} issue={} payee={} amount={} fee={} to={}", j.repo, j.issue, payee, net, fee, b58(wallet));
    close(a.job, a.rent_to)
}

/// What the record needs to know of the job or the order a payment came from.
pub struct Paid<'x> { pub faucet: bool, pub kind: u8, pub owner_id: u64, pub funder_id: u64, pub source: &'x Pubkey, pub mint: &'x Pubkey }

/// The payee's public record ["rep", payee]. Test money (the faucet's mint) counts apart. A mint that is neither the
/// faucet's nor Circle's USDC (`counted`) is anybody's token: its payment is counted as a test payment and its amount
/// is not added to anything, so nobody mints himself a record. In Circle's USDC, a payment whose funder is the payee
/// (the Balance's owner or the funding commenter is the payee, or the money goes back to the wallet that funded it)
/// counts apart too. Any other payment is real: it adds to `paid` and `total`, and to `funders` the first time this
/// funder pays this payee, which the Pair account ["pair", payee, funder key] remembers.
#[allow(clippy::too_many_arguments)]
pub fn record<'a>(program_id: &Pubkey, relayer: &AccountInfo<'a>, rep: &AccountInfo<'a>, pair: &AccountInfo<'a>, sys: &AccountInfo<'a>, p: &Paid,
                  payee: u64, wallet: &Pubkey, net: u64, now: i64) -> ProgramResult {
    let pb = payee.to_le_bytes();
    open(program_id, relayer, rep, sys, REP_LEN, &[b"rep", &pb], E_PAYEE)?;
    let own = p.owner_id == payee || p.funder_id == payee || (p.kind == 0 && p.source == wallet);
    if p.faucet {
        let mut d = rep.try_borrow_mut_data()?;
        count(&mut d, R_TEST_PAID); add(&mut d, R_TEST_TOTAL, net);
    } else if !counted(p.mint) {
        count(&mut rep.try_borrow_mut_data()?, R_TEST_PAID);
    } else if own {
        count(&mut rep.try_borrow_mut_data()?, R_SELF_PAID);
    } else {
        // the funder: the wallet, or the GitHub owner of the Balance (as sha256("gh" || owner id))
        let funder = if p.kind == 0 { p.source.to_bytes() } else { hashv(&[b"gh", &p.owner_id.to_le_bytes()]).to_bytes() };
        let (first, _) = open(program_id, relayer, pair, sys, PAIR_LEN, &[b"pair", &pb, &funder], E_PAYEE)?;
        if first { pair.try_borrow_mut_data()?[0] = 1; }
        let mut d = rep.try_borrow_mut_data()?;
        count(&mut d, R_PAID); add(&mut d, R_TOTAL, net);
        if first { count(&mut d, R_FUNDERS); }
        if i64_at(&d, R_FIRST) == 0 { put_i64(&mut d, R_FIRST, now); }
        put_i64(&mut d, R_LAST, now);
    }
    Ok(())
}

fn count(d: &mut [u8], o: usize) { let v = u32_at(d, o).saturating_add(1); put_u32(d, o, v); }
fn add(d: &mut [u8], o: usize, by: u64) { let v = u64_at(d, o).saturating_add(by); put_u64(d, o, v); }

/// A pay token from the job's pinned prove.yml: the funded terms were met at the merged commit by this payee.
pub fn pay(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, tok, key, job, bind, dest, rep, pair, vault, fee_tok, auth, rent_to, mint, token, sys, used] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
    let j = load_job(program_id, job)?;
    let g = github(tok, key, now)?;
    if j.state != OPEN || now > j.deadline { return Err(err(E_STATE)); }
    // the workflow is the one the job pinned at funding: this repository's prove.yml at this commit, and it ran in
    // the job's repository
    if g.wf_file != b"prove.yml" || g.wf_repo != j.wf_repo || g.wf_sha[..] != j.wf_sha[..] { return Err(err(E_WORKFLOW)); }
    if g.repo_id != j.repo { return Err(err(E_CLAIMS)); }
    // issued after the funding: a proof made before this job existed cannot pay it
    if g.iat < j.not_before { return Err(err(E_STATE)); }
    let p = pay_aud(&g.aud)?;
    if p.repo != j.repo || p.issue != j.issue || p.terms != j.terms || p.mode != j.mode { return Err(err(E_AUD)); }
    // a pay token pays, or holds, exactly one job: its marker is made here, and a second job is refused with it
    mark_used(program_id, relayer, used, sys, &sig_hash(tok)?, USED, false)?;
    // where the money goes: the payee's bound wallet; else the address the token carries; else nowhere yet
    match bound(program_id, bind, p.payee)?.or(p.address) {
        Some(wallet) => pay_out(program_id, &Payout { relayer, job, dest, rep, pair, vault, fee_tok, auth, rent_to, mint, token, sys }, &j, p.payee, &wallet, now),
        None => {
            let until = now.saturating_add(HOLD);
            let mut d = job.try_borrow_mut_data()?;
            d[J_STATE] = HELD;
            put_u64(&mut d, J_PAYEE, p.payee); put_i64(&mut d, J_HOLD_UNTIL, until);
            msg!("knos2:held repo={} issue={} payee={} until={}", j.repo, j.issue, p.payee, until);
            Ok(())
        }
    }
}

/// A HELD job is paid once its payee has bound a wallet. No token is needed: the proof was checked when it was held.
pub fn settle(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, job, bind, dest, rep, pair, vault, fee_tok, auth, rent_to, mint, token, sys] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
    let j = load_job(program_id, job)?;
    if j.state != HELD || now > j.hold_until { return Err(err(E_STATE)); }
    let wallet = bound(program_id, bind, j.payee)?.ok_or_else(|| err(E_PAYEE))?;
    pay_out(program_id, &Payout { relayer, job, dest, rep, pair, vault, fee_tok, auth, rent_to, mint, token, sys }, &j, j.payee, &wallet, now)
}

/// The job's money back to where it came from, once nobody else can have it: OPEN past its deadline, or HELD past its
/// hold. No token is needed, so a refund never depends on GitHub or on anyone's keys.
pub fn refund(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, job, vault, refund_tok, auth, rent_to, mint, token] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer { return Err(err(E_ACCOUNTS)); }
    let j = load_job(program_id, job)?;
    let due = match j.state { OPEN => now > j.deadline, HELD => now > j.hold_until, _ => false };
    if !due { return Err(err(E_STATE)); }
    let m = job_accounts(&j, mint, token, rent_to)?;
    let bump = vault_of(program_id, vault, auth, &j.mint)?;
    // a Balance's job: exactly that Balance's token account. A wallet's job: a token account of that wallet.
    let ok = if j.kind == 1 { *refund_tok.key == j.refund_to } else { is_owned(refund_tok, token.key, &j.mint, &j.refund_to) };
    if !ok { return Err(err(E_PAYEE)); }
    transfer(token, vault, mint, refund_tok, auth, j.amount, m.decimals, Some(bump))?;
    msg!("knos2:refunded repo={} issue={} amount={}", j.repo, j.issue, j.amount);
    close(job, rent_to)
}

/// Binds a wallet to a GitHub user. The token is from the pinned claim workflow (CLAIM_REF at CLAIM_SHA), from a run
/// the user started by hand in a repository of their own named knos-claim: nobody else can get GitHub to sign that.
/// Only `workflow_dispatch` counts. A push does not, not even the one that creates the repository: a link can open
/// GitHub's new-repository form already filled in (name, description), so a first push can be someone else's choice
/// of address made with the owner's click. A run started by hand has the address typed by the owner as its input.
pub fn bind(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], now: i64) -> ProgramResult {
    let [relayer, tok, key, bind, sys, used] = take(accounts)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
    let g = github(tok, key, now)?;
    let sha_ok = g.wf_sha[..] == CLAIM_SHA[..] || TEST_CLAIM_SHA.is_some_and(|t| g.wf_sha[..] == t[..]);
    if !g.wf_ref.starts_with(CLAIM_REF) || !sha_ok { return Err(err(E_WORKFLOW)); }
    // the actor owns the repository (so it is a personal account, and theirs), the repository is their knos-claim,
    // and they started the run themselves, by hand. Not a re-run: that keeps the first actor's name whoever starts it.
    let own = g.actor_id != 0 && g.actor_id == g.owner_id;
    let named = g.repository.as_deref().is_some_and(|r| r.ends_with(b"/knos-claim"));
    let started = g.first_attempt && g.event == b"workflow_dispatch";
    if !own || !named || !started { return Err(err(E_CLAIMS)); }
    let wallet = bind_aud(&g.aud)?;
    let (first, bump) = open(program_id, relayer, bind, sys, BIND_LEN, &[b"bind", &g.actor_id.to_le_bytes()], E_ACCOUNTS)?;
    // a later token rebinds; the same or an older one does nothing
    if !first && g.iat <= i64_at(&bind.try_borrow_data()?, BD_IAT) { return Err(err(E_REPLAY)); }
    mark_used(program_id, relayer, used, sys, &sig_hash(tok)?, USED, false)?;
    let mut d = bind.try_borrow_mut_data()?;
    d[BD_VERSION] = 1; d[BD_BUMP] = bump;
    put_u64(&mut d, BD_USER, g.actor_id); put_key(&mut d, BD_WALLET, &wallet); put_i64(&mut d, BD_IAT, g.iat);
    msg!("knos2:bound user={} wallet={}", g.actor_id, b58(&wallet));
    Ok(())
}
