//! knos-pay: pay on proof. A funder escrows a bounty for one issue of one GitHub repository. It is paid to the pull
//! request author's GitHub account only when GitHub itself signs a token saying the funder's pinned prove.yml
//! workflow passed for that pull request; the token is verified on chain by knos-oidc. There is no admin, no key of
//! Knos's in the path, and no wallet needed to earn: the money waits under the author's GitHub user id until they
//! claim it with a token from a workflow in their own repository.
//!
//! Tokens are GitHub Actions OIDC tokens already VERIFIED by knos-oidc (an account owned by that program). Every
//! token must come from a GitHub-hosted runner and be at most an hour past its expiry (knos_oidc::LATE); each
//! instruction has its own replay guard, described where it is handled. Audiences (the `aud` claim), all "knos:"-prefixed:
//!   fund   knos:fund:<issue>:<amount>:<mode>:<checks hash hex>:<work secs>:<review secs>       from fund.yml
//!   pay    knos:pay:<repository id>:<issue>:<author id>:<head sha>:<checks hash hex>:<mode>   from prove.yml
//!   veto   knos:veto:<repository id>:<issue>                                                  from fund.yml
//!   claim  knos:claim:<solana address>              from any workflow_dispatch run in a repository the actor owns
//! A job pins its workflows: the repository that holds them (sha256 of "owner/name") and their commit sha. A pay or
//! veto token must be from that repository's prove.yml / fund.yml at exactly that commit.
//!
//! mode 0 (merge): prove.yml mints the pay token when a maintainer merges the pull request that closes the issue.
//! mode 1 (tests): prove.yml mints it when the funder's acceptance checks (checks hash) pass on the pull request.
//! In both modes a proven payment waits the job's `review` seconds (0 = paid at once), during which the funder can
//! veto: the pull request's own description names the issue it closes, so a merge alone does not prove the
//! maintainers meant it to take this bounty. fund.yml's default is an hour for merge mode and a day for tests mode.
//!
//! Instructions (first byte is the tag):
//!   0 Fund           funder(s,w) job(w) funder_token(w) vault_token(w) mint auth token system
//!                    data: repo_id u64, issue u64, amount u64, work i64, review i64, mode u8, checks[32],
//!                          wf_repo_hash[32], wf_sha[40]
//!   1 FundWithToken  payer(s,w) fund_token job(w) vault_token(w) mint(w) auth token system rate(w)   (devnet only)
//!                    Mints test USDC into the vault for the job the token describes. One per repository per minute.
//!   2 Pay            relayer(s,w) pay_token job(w) due(w) rep(w) vault_token(w) fee_token(w) auth rent_to(w) token system
//!   3 Settle         relayer(s,w) job(w) due(w) rep(w) vault_token(w) fee_token(w) auth rent_to(w) token system
//!                    A proven job, after its review window.
//!   4 Veto           signer(s) job(w) [veto_token]      the funder's wallet signs, or a veto token is given
//!   5 Refund         relayer(s,w) job(w) vault_token(w) dest(w) auth rent_to(w) token system
//!                    After the deadline with no proof: back to the funder's token account (wallet-funded), or to
//!                    the funding repository owner's GitHub id (token-funded; `dest` is that due account).
//!   6 Claim          relayer(s,w) claim_token due(w) vault_token(w) dest_token(w) auth token
//!   7 InitFaucet     payer(s,w) mint(w) auth token system                                          (devnet only)
//! Anyone may relay tags 2, 3, 5 and 6 and pay their gas.
use knos_oidc::claims::{self, err, fields, number, parts, text};
use solana_program::{
    account_info::{next_account_info, AccountInfo},
    clock::Clock,
    entrypoint::ProgramResult,
    hash::hashv,
    instruction::{AccountMeta, Instruction},
    msg,
    program::{invoke, invoke_signed},
    program_error::ProgramError,
    pubkey,
    pubkey::Pubkey,
    rent::Rent,
    system_instruction, system_program,
    sysvar::Sysvar,
};

/// The knos-oidc program whose VERIFIED token accounts this program accepts. PIN: set at deploy (programs/program_ids.json).
pub const OIDC_ID: Pubkey = pubkey!("vpWym9azbPU5f2PH2a6n8c4RfmsyUeW2dMuWr1DSHcE");
/// Fees go to a token account owned by this address (Knos's Squads vault). It has no other power.
pub const FEE_OWNER: Pubkey = pubkey!("4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo");
pub const TOKEN_PROGRAM: Pubkey = pubkey!("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA");

pub const FEE_BPS: u64 = 250;             // 2.5%
pub const FEE_MIN: u64 = 50_000;          // 0.05 (6 decimals), never more than the amount
pub const MIN_AMOUNT: u64 = 1_000_000;    // 1.00; a job of 0 is allowed (a proof with no money)
pub const MAX_AMOUNT: u64 = 500_000_000;  // 500.00 per job until an outside review
pub const MAX_WORK: i64 = 90 * 86_400;
pub const MAX_REVIEW: i64 = 7 * 86_400;
pub const FAUCET_CAP: u64 = 100_000_000;  // devnet: at most 100 test USDC per funding
pub const FUND_PERIOD: i64 = 60;          // devnet: one token funding per repository per minute
pub const CLOCK_SLACK: i64 = 30;          // the chain's clock and GitHub's can differ by this much
pub const DEVNET: bool = cfg!(feature = "devnet");

pub const OPEN: u8 = 1;
pub const PROVEN: u8 = 2;
// job ["job", repo_id, issue, by]
pub const J_STATE: usize = 0;
pub const J_MODE: usize = 1;
pub const J_KIND: usize = 2;       // funder: 0 a wallet, 1 a GitHub account (token-funded)
pub const J_REPO: usize = 8;
pub const J_ISSUE: usize = 16;
pub const J_AMOUNT: usize = 24;
pub const J_DEADLINE: usize = 32;
pub const J_REVIEW: usize = 40;
pub const J_PAY_AFTER: usize = 48;
pub const J_AUTHOR: usize = 56;
pub const J_FUNDER_ID: usize = 64;
pub const J_NOT_BEFORE: usize = 72; // a pay token must be issued after this (the funding, or the last veto)
pub const J_VETOES: usize = 80;
pub const J_FUNDER: usize = 88;     // the wallet that funded (refund target) or paid the job's rent
pub const J_MINT: usize = 120;
pub const J_CHECKS: usize = 152;
pub const J_WF_REPO: usize = 184;
pub const J_WF_SHA: usize = 216;
pub const JOB_LEN: usize = 256;
// due ["due", github user id, mint]: amount u64, user u64, mint[32]
pub const DUE_LEN: usize = 48;
// rep ["rep", github user id]: paid jobs u32, vetoed u32, total paid u64, distinct repositories u32, last repo u64
pub const REP_LEN: usize = 32;
// rate ["rate", repo_id]: last token funding (chain time) i64, that fund token's iat i64
pub const RATE_LEN: usize = 16;

// errors 60-63 are knos-oidc's claim errors. 80 accounts; 81 terms; 82 job exists or is not this job; 83 state or
// time; 84 token not verified by knos-oidc, not GitHub's, or expired; 85 token claims; 86 workflow is not the job's
// pinned one; 87 audience; 88 payee or fee account; 89 devnet only; 90 rate limit; 91 nothing due
pub const E_ACCOUNTS: u32 = 80;
pub const E_TERMS: u32 = 81;
pub const E_JOB: u32 = 82;
pub const E_STATE: u32 = 83;
pub const E_TOKEN: u32 = 84;
pub const E_CLAIMS: u32 = 85;
pub const E_WORKFLOW: u32 = 86;
pub const E_AUD: u32 = 87;
pub const E_PAYEE: u32 = 88;
pub const E_DEVNET: u32 = 89;
pub const E_RATE: u32 = 90;
pub const E_NOTHING: u32 = 91;

#[cfg(not(feature = "no-entrypoint"))]
solana_program::entrypoint!(process);

#[cfg(not(feature = "no-entrypoint"))]
solana_security_txt::security_txt! {
    name: "knos-pay",
    project_url: "https://github.com/drexthealpha/Knos",
    contacts: "link:https://github.com/drexthealpha/Knos/security/advisories/new",
    policy: "https://github.com/drexthealpha/Knos/blob/main/SECURITY.md",
    source_code: "https://github.com/drexthealpha/Knos"
}

fn u64_at(d: &[u8], o: usize) -> u64 { u64::from_le_bytes(d[o..o + 8].try_into().unwrap()) }
fn i64_at(d: &[u8], o: usize) -> i64 { i64::from_le_bytes(d[o..o + 8].try_into().unwrap()) }
fn put_u64(d: &mut [u8], o: usize, v: u64) { d[o..o + 8].copy_from_slice(&v.to_le_bytes()); }
fn put_i64(d: &mut [u8], o: usize, v: i64) { d[o..o + 8].copy_from_slice(&v.to_le_bytes()); }
pub fn fee_of(amount: u64) -> u64 { (amount / 10_000 * FEE_BPS + amount % 10_000 * FEE_BPS / 10_000).max(FEE_MIN).min(amount) }

fn create_pda<'a>(payer: &AccountInfo<'a>, acct: &AccountInfo<'a>, sys: &AccountInfo<'a>, owner: &Pubkey, space: usize, seeds: &[&[u8]]) -> ProgramResult {
    let need = Rent::get()?.minimum_balance(space);
    let have = acct.lamports();
    if have < need { invoke(&system_instruction::transfer(payer.key, acct.key, need - have), &[payer.clone(), acct.clone(), sys.clone()])?; }
    invoke_signed(&system_instruction::allocate(acct.key, space as u64), &[acct.clone(), sys.clone()], &[seeds])?;
    invoke_signed(&system_instruction::assign(acct.key, owner), &[acct.clone(), sys.clone()], &[seeds])
}
fn close<'a>(acct: &AccountInfo<'a>, to: &AccountInfo<'a>) -> ProgramResult {
    **to.try_borrow_mut_lamports()? = to.lamports().checked_add(acct.lamports()).ok_or(ProgramError::ArithmeticOverflow)?;
    **acct.try_borrow_mut_lamports()? = 0;
    acct.resize(0)?;
    acct.assign(&system_program::ID);
    Ok(())
}
/// (owner, mint) of an SPL token account.
fn token_owner_mint(a: &AccountInfo) -> Result<(Pubkey, Pubkey), ProgramError> {
    if *a.owner != TOKEN_PROGRAM || a.data_len() != 165 { return Err(err(E_ACCOUNTS)); }
    let d = a.try_borrow_data()?;
    Ok((Pubkey::new_from_array(d[32..64].try_into().unwrap()), Pubkey::new_from_array(d[0..32].try_into().unwrap())))
}
fn auth_key(program_id: &Pubkey) -> (Pubkey, u8) { Pubkey::find_program_address(&[b"auth"], program_id) }

/// The vault of `mint`: the token account ["vault", mint], owned by ["auth"]. Created here on first use.
fn vault<'a>(program_id: &Pubkey, payer: &AccountInfo<'a>, vault_tok: &AccountInfo<'a>, mint: &AccountInfo<'a>, auth: &AccountInfo<'a>,
             token: &AccountInfo<'a>, sys: &AccountInfo<'a>) -> ProgramResult {
    let (vk, vb) = Pubkey::find_program_address(&[b"vault", mint.key.as_ref()], program_id);
    if *vault_tok.key != vk || *auth.key != auth_key(program_id).0 || *token.key != TOKEN_PROGRAM || *sys.key != system_program::ID { return Err(err(E_ACCOUNTS)); }
    if *mint.owner != TOKEN_PROGRAM || mint.data_len() != 82 { return Err(err(E_ACCOUNTS)); }
    if vault_tok.data_is_empty() {
        create_pda(payer, vault_tok, sys, &TOKEN_PROGRAM, 165, &[b"vault", mint.key.as_ref(), &[vb]])?;
        let mut d = vec![18u8]; d.extend_from_slice(auth.key.as_ref()); // InitializeAccount3
        invoke(&Instruction { program_id: TOKEN_PROGRAM, data: d, accounts: vec![AccountMeta::new(vk, false), AccountMeta::new_readonly(*mint.key, false)] },
               &[vault_tok.clone(), mint.clone(), token.clone()])?;
    }
    let (o, m) = token_owner_mint(vault_tok)?;
    if o != *auth.key || m != *mint.key { return Err(err(E_ACCOUNTS)); }
    Ok(())
}
fn vault_of(program_id: &Pubkey, vault_tok: &AccountInfo, auth: &AccountInfo, mint: &Pubkey) -> Result<u8, ProgramError> {
    let (ak, ab) = auth_key(program_id);
    if *vault_tok.key != Pubkey::find_program_address(&[b"vault", mint.as_ref()], program_id).0 || *auth.key != ak { return Err(err(E_ACCOUNTS)); }
    Ok(ab)
}
fn pay_out<'a>(token: &AccountInfo<'a>, vault_tok: &AccountInfo<'a>, to: &AccountInfo<'a>, auth: &AccountInfo<'a>, amount: u64, bump: u8) -> ProgramResult {
    let mut d = vec![3u8]; d.extend_from_slice(&amount.to_le_bytes()); // Transfer
    invoke_signed(&Instruction { program_id: TOKEN_PROGRAM, data: d,
        accounts: vec![AccountMeta::new(*vault_tok.key, false), AccountMeta::new(*to.key, false), AccountMeta::new_readonly(*auth.key, true)] },
        &[vault_tok.clone(), to.clone(), auth.clone(), token.clone()], &[&[b"auth", &[bump]]])
}

/// The claims of a GitHub token that knos-oidc verified, read once.
struct Gh { repo_id: u64, owner_id: u64, actor_id: u64, iat: i64, wf_repo: [u8; 32], wf_file: Vec<u8>, wf_sha: Vec<u8>, aud: Vec<u8>, event: Vec<u8> }
fn github(tok: &AccountInfo, now: i64) -> Result<Gh, ProgramError> {
    if *tok.owner != OIDC_ID { return Err(err(E_TOKEN)); }
    let d = tok.try_borrow_data()?;
    let v = knos_oidc::verified(&d).ok_or_else(|| err(E_TOKEN))?;
    if v.issuer != knos_oidc::pins::ISSUER_GITHUB || !knos_oidc::fresh(v.exp, now) { return Err(err(E_TOKEN)); }
    let [repo_id, owner_id, actor_id, iat, wref, wsha, runner, aud, event] = fields(v.payload,
        [b"repository_id", b"repository_owner_id", b"actor_id", b"iat", b"job_workflow_ref", b"job_workflow_sha", b"runner_environment", b"aud", b"event_name"])?;
    if text(runner)? != b"github-hosted" { return Err(err(E_CLAIMS)); }
    // job_workflow_ref = "<owner>/<name>/.github/workflows/<file>@<ref>"
    let wref = text(wref)?;
    const MID: &[u8] = b"/.github/workflows/";
    let at = wref.windows(MID.len()).position(|w| w == MID).ok_or_else(|| err(E_CLAIMS))?;
    let rest = &wref[at + MID.len()..];
    let end = rest.iter().position(|&c| c == b'@').ok_or_else(|| err(E_CLAIMS))?;
    let wsha = text(wsha)?;
    if !claims::is_hex(&wsha, 40) { return Err(err(E_CLAIMS)); }
    Ok(Gh { repo_id: number(repo_id)?, owner_id: number(owner_id)?, actor_id: number(actor_id)?, iat: number(iat)? as i64,
            wf_repo: hashv(&[&wref[..at]]).to_bytes(), wf_file: rest[..end].to_vec(), wf_sha: wsha, aud: text(aud)?, event: text(event)? })
}

/// A job's address: ["job", repo_id, issue, by]. `by` is the funding wallet, or 32 zero bytes for the repository's own
/// token-funded bounty. So nobody can take an issue's address before its maintainers do, and anyone can add a bounty
/// of their own to an issue: the same proof pays each job that pins the same workflow.
const OWN: [u8; 32] = [0; 32];
fn job_key(program_id: &Pubkey, repo_id: u64, issue: u64, by: &[u8]) -> (Pubkey, u8) {
    Pubkey::find_program_address(&[b"job", &repo_id.to_le_bytes(), &issue.to_le_bytes(), by], program_id)
}
fn load_job(program_id: &Pubkey, job: &AccountInfo) -> Result<(), ProgramError> {
    if job.owner != program_id || job.data_len() != JOB_LEN { return Err(err(E_JOB)); }
    let d = job.try_borrow_data()?;
    let by: &[u8] = if d[J_KIND] == 0 { &d[J_FUNDER..J_FUNDER + 32] } else { &OWN };
    if *job.key != job_key(program_id, u64_at(&d, J_REPO), u64_at(&d, J_ISSUE), by).0 { return Err(err(E_JOB)); }
    Ok(())
}
fn terms_ok(amount: u64, work: i64, review: i64, mode: u8) -> bool {
    (amount == 0 || (MIN_AMOUNT..=MAX_AMOUNT).contains(&amount)) && (60..=MAX_WORK).contains(&work) && (0..=MAX_REVIEW).contains(&review) && mode <= 1
}

/// due[user, mint] += amount, creating the account (rent from `payer`) on first use.
fn credit<'a>(program_id: &Pubkey, payer: &AccountInfo<'a>, due: &AccountInfo<'a>, sys: &AccountInfo<'a>, user: u64, mint: &Pubkey, amount: u64) -> ProgramResult {
    let ub = user.to_le_bytes();
    let (dk, db) = Pubkey::find_program_address(&[b"due", &ub, mint.as_ref()], program_id);
    if *due.key != dk || *sys.key != system_program::ID { return Err(err(E_PAYEE)); }
    if due.owner != program_id {
        if !due.data_is_empty() || *due.owner != system_program::ID { return Err(err(E_PAYEE)); }
        create_pda(payer, due, sys, program_id, DUE_LEN, &[b"due", &ub, mint.as_ref(), &[db]])?;
        let mut d = due.try_borrow_mut_data()?;
        put_u64(&mut d, 8, user);
        d[16..48].copy_from_slice(mint.as_ref());
    }
    let mut d = due.try_borrow_mut_data()?;
    let new = u64_at(&d, 0).checked_add(amount).ok_or(ProgramError::ArithmeticOverflow)?;
    put_u64(&mut d, 0, new);
    Ok(())
}

/// Pays a job: amount - fee to the author's due account, the fee to Knos's fee account, the author's record
/// updated, the job closed (its rent back to whoever paid it).
#[allow(clippy::too_many_arguments)]
fn settle<'a>(program_id: &Pubkey, relayer: &AccountInfo<'a>, job: &AccountInfo<'a>, due: &AccountInfo<'a>, rep: &AccountInfo<'a>,
              vault_tok: &AccountInfo<'a>, fee_tok: &AccountInfo<'a>, auth: &AccountInfo<'a>, rent_to: &AccountInfo<'a>,
              token: &AccountInfo<'a>, sys: &AccountInfo<'a>, author: u64) -> ProgramResult {
    let (amount, mint, funder, repo, issue) = {
        let d = job.try_borrow_data()?;
        (u64_at(&d, J_AMOUNT), Pubkey::new_from_array(d[J_MINT..J_MINT + 32].try_into().unwrap()),
         Pubkey::new_from_array(d[J_FUNDER..J_FUNDER + 32].try_into().unwrap()), u64_at(&d, J_REPO), u64_at(&d, J_ISSUE))
    };
    if *rent_to.key != funder || *token.key != TOKEN_PROGRAM { return Err(err(E_ACCOUNTS)); }
    let bump = vault_of(program_id, vault_tok, auth, &mint)?;
    let fee = fee_of(amount);
    credit(program_id, relayer, due, sys, author, &mint, amount - fee)?;
    if fee > 0 {
        let (fo, fm) = token_owner_mint(fee_tok)?;
        if fo != FEE_OWNER || fm != mint { return Err(err(E_PAYEE)); }
        pay_out(token, vault_tok, fee_tok, auth, fee, bump)?;
    }
    // the author's public record: jobs paid, total, distinct repositories (counted when the repository changes)
    let ab = author.to_le_bytes();
    let (rk, rb) = Pubkey::find_program_address(&[b"rep", &ab], program_id);
    if *rep.key != rk { return Err(err(E_PAYEE)); }
    if rep.owner != program_id {
        if !rep.data_is_empty() || *rep.owner != system_program::ID { return Err(err(E_PAYEE)); }
        create_pda(relayer, rep, sys, program_id, REP_LEN, &[b"rep", &ab, &[rb]])?;
    }
    {
        let mut d = rep.try_borrow_mut_data()?;
        let paid = u32::from_le_bytes(d[0..4].try_into().unwrap()).saturating_add(1);
        d[0..4].copy_from_slice(&paid.to_le_bytes());
        let total = u64_at(&d, 8).saturating_add(amount - fee);
        put_u64(&mut d, 8, total);
        if u64_at(&d, 24) != repo {
            let distinct = u32::from_le_bytes(d[16..20].try_into().unwrap()).saturating_add(1);
            d[16..20].copy_from_slice(&distinct.to_le_bytes());
            put_u64(&mut d, 24, repo);
        }
    }
    msg!("knos:paid repo={} issue={} author={} amount={} fee={}", repo, issue, author, amount - fee, fee);
    close(job, rent_to)
}

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let (&tag, rest) = data.split_first().ok_or(ProgramError::InvalidInstructionData)?;
    let it = &mut accounts.iter();
    let now = Clock::get()?.unix_timestamp;
    match tag {
        0 => {
            let funder = next_account_info(it)?; let job = next_account_info(it)?; let funder_tok = next_account_info(it)?;
            let vault_tok = next_account_info(it)?; let mint = next_account_info(it)?; let auth = next_account_info(it)?;
            let token = next_account_info(it)?; let sys = next_account_info(it)?;
            if rest.len() != 145 { return Err(ProgramError::InvalidInstructionData); }
            let (repo_id, issue, amount) = (u64_at(rest, 0), u64_at(rest, 8), u64_at(rest, 16));
            let (work, review, mode) = (i64_at(rest, 24), i64_at(rest, 32), rest[40]);
            if !funder.is_signer || !funder.is_writable { return Err(err(E_ACCOUNTS)); }
            if !terms_ok(amount, work, review, mode) || repo_id == 0 || !claims::is_hex(&rest[105..145], 40) { return Err(err(E_TERMS)); }
            let (jk, jb) = job_key(program_id, repo_id, issue, funder.key.as_ref());
            if *job.key != jk || !job.data_is_empty() || *job.owner != system_program::ID { return Err(err(E_JOB)); }
            vault(program_id, funder, vault_tok, mint, auth, token, sys)?;
            create_pda(funder, job, sys, program_id, JOB_LEN, &[b"job", &repo_id.to_le_bytes(), &issue.to_le_bytes(), funder.key.as_ref(), &[jb]])?;
            if amount > 0 {
                let mut d = vec![3u8]; d.extend_from_slice(&amount.to_le_bytes());
                invoke(&Instruction { program_id: TOKEN_PROGRAM, data: d,
                    accounts: vec![AccountMeta::new(*funder_tok.key, false), AccountMeta::new(*vault_tok.key, false), AccountMeta::new_readonly(*funder.key, true)] },
                    &[funder_tok.clone(), vault_tok.clone(), funder.clone(), token.clone()])?;
            }
            let mut d = job.try_borrow_mut_data()?;
            d[J_STATE] = OPEN; d[J_MODE] = mode; d[J_KIND] = 0;
            put_u64(&mut d, J_REPO, repo_id); put_u64(&mut d, J_ISSUE, issue); put_u64(&mut d, J_AMOUNT, amount);
            put_i64(&mut d, J_DEADLINE, now.saturating_add(work)); put_i64(&mut d, J_REVIEW, review);
            put_i64(&mut d, J_NOT_BEFORE, now.saturating_sub(CLOCK_SLACK));
            d[J_FUNDER..J_FUNDER + 32].copy_from_slice(funder.key.as_ref());
            d[J_MINT..J_MINT + 32].copy_from_slice(mint.key.as_ref());
            d[J_CHECKS..J_CHECKS + 104].copy_from_slice(&rest[41..145]); // checks, wf_repo_hash, wf_sha
            msg!("knos:funded repo={} issue={} amount={} mode={}", repo_id, issue, amount, mode);
            Ok(())
        }
        1 => {
            if !DEVNET { return Err(err(E_DEVNET)); }
            let payer = next_account_info(it)?; let tok = next_account_info(it)?; let job = next_account_info(it)?;
            let vault_tok = next_account_info(it)?; let mint = next_account_info(it)?; let auth = next_account_info(it)?;
            let token = next_account_info(it)?; let sys = next_account_info(it)?; let rate = next_account_info(it)?;
            if !payer.is_signer || !payer.is_writable { return Err(err(E_ACCOUNTS)); }
            if *mint.key != Pubkey::find_program_address(&[b"mint"], program_id).0 { return Err(err(E_ACCOUNTS)); }
            let g = github(tok, now)?;
            if g.wf_file != b"fund.yml" { return Err(err(E_WORKFLOW)); }
            // knos:fund:<issue>:<amount>:<mode>:<checks hex>:<work>:<review>
            let [k, f, issue, amount, mode, checks, work, review] = parts::<8>(&g.aud).ok_or_else(|| err(E_AUD))?;
            if k != b"knos" || f != b"fund" || mode.len() != 1 { return Err(err(E_AUD)); }
            let p = |s: &[u8]| claims::parse_u64(s).ok_or_else(|| err(E_AUD));
            let (issue, amount, mode, work, review) = (p(issue)?, p(amount)?, mode[0].wrapping_sub(b'0'), p(work)? as i64, p(review)? as i64);
            let checks = claims::unhex32(checks).ok_or_else(|| err(E_AUD))?;
            if !terms_ok(amount, work, review, mode) || amount > FAUCET_CAP { return Err(err(E_TERMS)); }
            let rb = g.repo_id.to_le_bytes();
            let (rk, rbump) = Pubkey::find_program_address(&[b"rate", &rb], program_id);
            if *rate.key != rk { return Err(err(E_ACCOUNTS)); }
            // one funding per repository per minute, and each fund token only once: a repository's fund tokens must
            // be used in the order GitHub issued them, so a token seen in public cannot fund the same issue again
            if rate.owner == program_id {
                let d = rate.try_borrow_data()?;
                if now < i64_at(&d, 0).saturating_add(FUND_PERIOD) || g.iat <= i64_at(&d, 8) { return Err(err(E_RATE)); }
            } else {
                create_pda(payer, rate, sys, program_id, RATE_LEN, &[b"rate", &rb, &[rbump]])?;
            }
            {
                let mut d = rate.try_borrow_mut_data()?;
                put_i64(&mut d, 0, now); put_i64(&mut d, 8, g.iat);
            }
            let (jk, jb) = job_key(program_id, g.repo_id, issue, &OWN);
            if *job.key != jk || !job.data_is_empty() || *job.owner != system_program::ID { return Err(err(E_JOB)); }
            vault(program_id, payer, vault_tok, mint, auth, token, sys)?;
            create_pda(payer, job, sys, program_id, JOB_LEN, &[b"job", &rb, &issue.to_le_bytes(), &OWN, &[jb]])?;
            if amount > 0 {
                let mut d = vec![7u8]; d.extend_from_slice(&amount.to_le_bytes()); // MintTo
                invoke_signed(&Instruction { program_id: TOKEN_PROGRAM, data: d,
                    accounts: vec![AccountMeta::new(*mint.key, false), AccountMeta::new(*vault_tok.key, false), AccountMeta::new_readonly(*auth.key, true)] },
                    &[mint.clone(), vault_tok.clone(), auth.clone(), token.clone()], &[&[b"auth", &[auth_key(program_id).1]]])?;
            }
            let mut d = job.try_borrow_mut_data()?;
            d[J_STATE] = OPEN; d[J_MODE] = mode; d[J_KIND] = 1;
            put_u64(&mut d, J_REPO, g.repo_id); put_u64(&mut d, J_ISSUE, issue); put_u64(&mut d, J_AMOUNT, amount);
            put_i64(&mut d, J_DEADLINE, now.saturating_add(work)); put_i64(&mut d, J_REVIEW, review); put_i64(&mut d, J_NOT_BEFORE, g.iat);
            put_u64(&mut d, J_FUNDER_ID, g.owner_id);
            d[J_FUNDER..J_FUNDER + 32].copy_from_slice(payer.key.as_ref());
            d[J_MINT..J_MINT + 32].copy_from_slice(mint.key.as_ref());
            d[J_CHECKS..J_CHECKS + 32].copy_from_slice(&checks);
            d[J_WF_REPO..J_WF_REPO + 32].copy_from_slice(&g.wf_repo);
            d[J_WF_SHA..J_WF_SHA + 40].copy_from_slice(&g.wf_sha);
            msg!("knos:funded repo={} issue={} amount={} mode={} by={}", g.repo_id, issue, amount, mode, g.owner_id);
            Ok(())
        }
        2 => {
            let relayer = next_account_info(it)?; let tok = next_account_info(it)?; let job = next_account_info(it)?;
            let due = next_account_info(it)?; let rep = next_account_info(it)?; let vault_tok = next_account_info(it)?;
            let fee_tok = next_account_info(it)?; let auth = next_account_info(it)?; let rent_to = next_account_info(it)?;
            let token = next_account_info(it)?; let sys = next_account_info(it)?;
            if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
            load_job(program_id, job)?;
            let g = github(tok, now)?;
            let (author, wait) = {
                let d = job.try_borrow_data()?;
                if d[J_STATE] != OPEN || now > i64_at(&d, J_DEADLINE) { return Err(err(E_STATE)); }
                if g.wf_file != b"prove.yml" || g.wf_repo != d[J_WF_REPO..J_WF_REPO + 32] || g.wf_sha[..] != d[J_WF_SHA..J_WF_SHA + 40] { return Err(err(E_WORKFLOW)); }
                if g.repo_id != u64_at(&d, J_REPO) { return Err(err(E_CLAIMS)); }
                // issued after the funding, and strictly after the last veto: an old proof cannot pay a new or vetoed job
                let vetoed = d[J_VETOES..J_VETOES + 4] != [0; 4];
                if g.iat < i64_at(&d, J_NOT_BEFORE) || (vetoed && g.iat == i64_at(&d, J_NOT_BEFORE)) { return Err(err(E_STATE)); }
                // knos:pay:<repo id>:<issue>:<author id>:<head sha>:<checks hex>:<mode>
                let [k, p, repo, issue, author, head, checks, mode] = parts::<8>(&g.aud).ok_or_else(|| err(E_AUD))?;
                let n = |s: &[u8]| claims::parse_u64(s).ok_or_else(|| err(E_AUD));
                if k != b"knos" || p != b"pay" || n(repo)? != g.repo_id || n(issue)? != u64_at(&d, J_ISSUE) || !claims::is_hex(head, 40) { return Err(err(E_AUD)); }
                if claims::unhex32(checks).ok_or_else(|| err(E_AUD))?[..] != d[J_CHECKS..J_CHECKS + 32] || mode != [b'0' + d[J_MODE]] { return Err(err(E_AUD)); }
                let author = n(author)?;
                if author == 0 { return Err(err(E_AUD)); }
                (author, i64_at(&d, J_REVIEW))
            };
            if wait > 0 {
                let mut d = job.try_borrow_mut_data()?;
                d[J_STATE] = PROVEN;
                put_u64(&mut d, J_AUTHOR, author);
                put_i64(&mut d, J_PAY_AFTER, now.saturating_add(wait));
                msg!("knos:proven author={} pays_after={}", author, now.saturating_add(wait));
                return Ok(());
            }
            settle(program_id, relayer, job, due, rep, vault_tok, fee_tok, auth, rent_to, token, sys, author)
        }
        3 => {
            let relayer = next_account_info(it)?; let job = next_account_info(it)?;
            let due = next_account_info(it)?; let rep = next_account_info(it)?; let vault_tok = next_account_info(it)?;
            let fee_tok = next_account_info(it)?; let auth = next_account_info(it)?; let rent_to = next_account_info(it)?;
            let token = next_account_info(it)?; let sys = next_account_info(it)?;
            if !relayer.is_signer || !relayer.is_writable { return Err(err(E_ACCOUNTS)); }
            load_job(program_id, job)?;
            let author = {
                let d = job.try_borrow_data()?;
                if d[J_STATE] != PROVEN || now < i64_at(&d, J_PAY_AFTER) { return Err(err(E_STATE)); }
                u64_at(&d, J_AUTHOR)
            };
            settle(program_id, relayer, job, due, rep, vault_tok, fee_tok, auth, rent_to, token, sys, author)
        }
        4 => {
            let signer = next_account_info(it)?; let job = next_account_info(it)?;
            if !signer.is_signer { return Err(err(E_ACCOUNTS)); }
            load_job(program_id, job)?;
            let by_wallet = {
                let d = job.try_borrow_data()?;
                if d[J_STATE] != PROVEN || now >= i64_at(&d, J_PAY_AFTER) { return Err(err(E_STATE)); }
                d[J_KIND] == 0 && d[J_FUNDER..J_FUNDER + 32] == signer.key.as_ref()[..]
            };
            if !by_wallet {
                let g = github(next_account_info(it).map_err(|_| err(E_TOKEN))?, now)?;
                let d = job.try_borrow_data()?;
                if g.wf_file != b"fund.yml" || g.wf_repo != d[J_WF_REPO..J_WF_REPO + 32] || g.wf_sha[..] != d[J_WF_SHA..J_WF_SHA + 40] { return Err(err(E_WORKFLOW)); }
                let [k, v, repo, issue] = parts::<4>(&g.aud).ok_or_else(|| err(E_AUD))?;
                if k != b"knos" || v != b"veto" || claims::parse_u64(repo) != Some(u64_at(&d, J_REPO)) || g.repo_id != u64_at(&d, J_REPO)
                    || claims::parse_u64(issue) != Some(u64_at(&d, J_ISSUE)) { return Err(err(E_AUD)); }
                // issued after the proof it vetoes landed (less the clock slack): an old veto cannot be replayed on a new proof
                if g.iat < (i64_at(&d, J_PAY_AFTER) - i64_at(&d, J_REVIEW)).saturating_sub(CLOCK_SLACK) { return Err(err(E_STATE)); }
            }
            let mut d = job.try_borrow_mut_data()?;
            // the vetoed author's record shows it
            d[J_STATE] = OPEN;
            put_u64(&mut d, J_AUTHOR, 0); put_i64(&mut d, J_PAY_AFTER, 0); put_i64(&mut d, J_NOT_BEFORE, now);
            let v = u32::from_le_bytes(d[J_VETOES..J_VETOES + 4].try_into().unwrap()).saturating_add(1);
            d[J_VETOES..J_VETOES + 4].copy_from_slice(&v.to_le_bytes());
            msg!("knos:vetoed vetoes={}", v);
            Ok(())
        }
        5 => {
            let relayer = next_account_info(it)?; let job = next_account_info(it)?; let vault_tok = next_account_info(it)?;
            let dest = next_account_info(it)?; let auth = next_account_info(it)?; let rent_to = next_account_info(it)?;
            let token = next_account_info(it)?; let sys = next_account_info(it)?;
            if !relayer.is_signer || !relayer.is_writable || *token.key != TOKEN_PROGRAM { return Err(err(E_ACCOUNTS)); }
            load_job(program_id, job)?;
            let (kind, amount, mint, funder, funder_id) = {
                let d = job.try_borrow_data()?;
                if d[J_STATE] != OPEN || now <= i64_at(&d, J_DEADLINE) { return Err(err(E_STATE)); }
                (d[J_KIND], u64_at(&d, J_AMOUNT), Pubkey::new_from_array(d[J_MINT..J_MINT + 32].try_into().unwrap()),
                 Pubkey::new_from_array(d[J_FUNDER..J_FUNDER + 32].try_into().unwrap()), u64_at(&d, J_FUNDER_ID))
            };
            if *rent_to.key != funder { return Err(err(E_ACCOUNTS)); }
            let bump = vault_of(program_id, vault_tok, auth, &mint)?;
            if kind == 0 {
                let (o, m) = token_owner_mint(dest)?;
                if o != funder || m != mint { return Err(err(E_PAYEE)); }
                if amount > 0 { pay_out(token, vault_tok, dest, auth, amount, bump)?; }
            } else {
                credit(program_id, relayer, dest, sys, funder_id, &mint, amount)?;
            }
            msg!("knos:refunded amount={}", amount);
            close(job, rent_to)
        }
        6 => {
            let relayer = next_account_info(it)?; let tok = next_account_info(it)?; let due = next_account_info(it)?;
            let vault_tok = next_account_info(it)?; let dest = next_account_info(it)?; let auth = next_account_info(it)?;
            let token = next_account_info(it)?;
            if !relayer.is_signer || !relayer.is_writable || *token.key != TOKEN_PROGRAM { return Err(err(E_ACCOUNTS)); }
            let g = github(tok, now)?;
            // the account's owner ran this by hand in a repository they own: nobody else can produce that
            if g.event != b"workflow_dispatch" || g.actor_id != g.owner_id || g.actor_id == 0 { return Err(err(E_CLAIMS)); }
            let [k, c, addr] = parts::<3>(&g.aud).ok_or_else(|| err(E_AUD))?;
            if k != b"knos" || c != b"claim" { return Err(err(E_AUD)); }
            let addr = Pubkey::new_from_array(claims::b58_32(addr).ok_or_else(|| err(E_AUD))?);
            if due.owner != program_id || due.data_len() != DUE_LEN { return Err(err(E_NOTHING)); }
            let (amount, mint) = {
                let d = due.try_borrow_data()?;
                if u64_at(&d, 8) != g.actor_id { return Err(err(E_PAYEE)); }
                (u64_at(&d, 0), Pubkey::new_from_array(d[16..48].try_into().unwrap()))
            };
            if *due.key != Pubkey::find_program_address(&[b"due", &g.actor_id.to_le_bytes(), mint.as_ref()], program_id).0 { return Err(err(E_PAYEE)); }
            let (o, m) = token_owner_mint(dest)?;
            if o != addr || m != mint { return Err(err(E_PAYEE)); }
            let bump = vault_of(program_id, vault_tok, auth, &mint)?;
            if amount > 0 { pay_out(token, vault_tok, dest, auth, amount, bump)?; }
            msg!("knos:claimed user={} amount={}", g.actor_id, amount);
            close(due, relayer)
        }
        7 => {
            if !DEVNET { return Err(err(E_DEVNET)); }
            let payer = next_account_info(it)?; let mint = next_account_info(it)?; let auth = next_account_info(it)?;
            let token = next_account_info(it)?; let sys = next_account_info(it)?;
            let (mk, mb) = Pubkey::find_program_address(&[b"mint"], program_id);
            if !payer.is_signer || *mint.key != mk || *auth.key != auth_key(program_id).0 || *token.key != TOKEN_PROGRAM
                || *sys.key != system_program::ID || !mint.data_is_empty() { return Err(err(E_ACCOUNTS)); }
            create_pda(payer, mint, sys, &TOKEN_PROGRAM, 82, &[b"mint", &[mb]])?;
            let mut d = vec![20u8, 6]; d.extend_from_slice(auth.key.as_ref()); d.push(0); // InitializeMint2: 6 decimals, no freeze
            invoke(&Instruction { program_id: TOKEN_PROGRAM, data: d, accounts: vec![AccountMeta::new(mk, false)] }, &[mint.clone(), token.clone()])
        }
        _ => Err(ProgramError::InvalidInstructionData),
    }
}
