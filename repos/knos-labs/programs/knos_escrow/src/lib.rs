//! Knos escrow: pay-on-acceptance (or pay-on-proof) escrow for AI agent jobs on Solana (SPL tokens).
//! Same state machine as KnosEscrow.sol on Tempo:
//!   post -> claim -> deliver -> accept | verify_release | reject | release | refund.
//! Native program (no framework). The Knos escrow program (devnet: GwmbMFvyHHwHug5em9dv26oXz2zTgXKGsNdrBxPayRPq).
//!
//! 0.3.9: an issuer registry (25 RegisterIssuer; keys scoped per issuer: GitHub Actions, GitLab CI), FundWithToken
//! (26, devnet: a fund.yml token funds a github job with minted test USDC), the version in the binary (29 Version).
//!
//! 0.3.4: a job may name a verifier key at post; the verifier alone can release a delivered job by naming the exact
//! result hash the worker committed (and a proof root, stored in the job). Minimum job and minimum fee; a per-job cap
//! the admin can only lower; a pause that stops new posts only. The config moved to a new PDA ["config2"].
//!
//! 0.3.5: a job that names a verifier settles only by its verifier (VerifyRelease on pass, VerifyReject on fail) or
//! the deadline; its buyer cannot reject it. Settle (anyone) at the deadline: delivered work with no verdict pays the
//! worker, undelivered work refunds the buyer. A buyer cannot claim its own job. Claim takes a worker stake (10% of the
//! price, at least 0.1 USDC) back on delivery, the buyer's if the claim times out. Every settlement closes the job
//! account and returns its rent to the buyer. The config layout is unchanged.
use solana_program::{
    account_info::{next_account_info, AccountInfo},
    clock::Clock,
    entrypoint::ProgramResult,
    instruction::{AccountMeta, Instruction},
    msg,
    program::{invoke, invoke_signed},
    program_error::ProgramError,
    pubkey::Pubkey,
    rent::Rent,
    system_instruction, system_program,
    sysvar::Sysvar,
};

pub mod github;

#[cfg(not(feature = "no-entrypoint"))]
solana_program::entrypoint!(process);

#[cfg(not(feature = "no-entrypoint"))]
solana_security_txt::security_txt! {
    name: "Knos",
    project_url: "https://github.com/drexthealpha/Knos",
    contacts: "link:https://github.com/drexthealpha/Knos/security/advisories/new",
    policy: "https://github.com/drexthealpha/Knos/blob/main/SECURITY.md",
    source_code: "https://github.com/drexthealpha/Knos",
    source_release: "v0.3.9"
}

/// The program's version, in the binary: clients read it from the program data and refuse a mismatch.
pub const VERSION: &str = "knos-escrow 0.3.9";

mod bounty;

pub const TOKEN_PROGRAM: Pubkey = solana_program::pubkey!("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA");
const LEGACY_CONFIG_LEN: usize = 32 + 32 + 32 + 2 + 1; // ["config"]: admin, mint, fee_token, fee_bps, bump (retired)
// ["config2"]: admin, mint, fee_token, fee_bps u16, min_fee u64, min_amount u64, max_amount u64, paused u8, bump u8
const CONFIG_LEN: usize = 32 + 32 + 32 + 2 + 8 + 8 + 8 + 1 + 1;
// state, buyer, worker, amount, deadline, review, brief, result, verifier, proof, stake
const JOB_LEN: usize = 1 + 32 + 32 + 8 + 8 + 8 + 32 + 32 + 32 + 32 + 8;
const MINT_JOB_LEN: usize = JOB_LEN + 32; // 0.3.7: a job in a registered mint stores the mint after the stake
const V034_JOB_LEN: usize = 217;   // jobs posted by 0.3.4: no stake field (claimed without a stake); they settle as before
const LEGACY_JOB_LEN: usize = 153; // jobs posted before 0.3.4: no verifier, no proof; they settle as before
// The worker's stake at claim: 10% of the price, at least 0.1 USDC (6 decimals), held in the vault.
const STAKE_BPS: u64 = 1_000;
const MIN_STAKE: u64 = 100_000;
fn stake_for(amount: u64) -> u64 { (((amount as u128) * (STAKE_BPS as u128) / 10_000) as u64).max(MIN_STAKE) }

#[repr(u8)]
#[derive(PartialEq, Clone, Copy)]
enum S { None = 0, Open = 1, Claimed = 2, Delivered = 3, Released = 4, Refunded = 5 }

fn err(code: u32, m: &str) -> ProgramError { msg!("knos_escrow: {}", m); ProgramError::Custom(code) }

struct Job {
    state: u8, buyer: Pubkey, worker: Pubkey, amount: u64, deadline: i64, review: i64, brief: [u8; 32], result: [u8; 32],
    verifier: Pubkey, proof: [u8; 32], stake: u64, mint: Pubkey,
}
impl Job {
    fn load(d: &[u8]) -> Result<Job, ProgramError> {
        if d.len() != MINT_JOB_LEN && d.len() != github::GH_MINT_JOB_LEN && d.len() != github::GH_JOB_LEN && d.len() != github::GH_V037_JOB_LEN && d.len() != JOB_LEN && d.len() != V034_JOB_LEN && d.len() != LEGACY_JOB_LEN { return Err(err(13, "not a job account")); }
        let pk = |o: usize| Pubkey::new_from_array(d[o..o + 32].try_into().unwrap());
        let u = |o: usize| u64::from_le_bytes(d[o..o + 8].try_into().unwrap());
        let full = d.len() >= V034_JOB_LEN;
        Ok(Job { state: d[0], buyer: pk(1), worker: pk(33), amount: u(65), deadline: u(73) as i64, review: u(81) as i64,
                 brief: d[89..121].try_into().unwrap(), result: d[121..153].try_into().unwrap(),
                 verifier: if full { pk(153) } else { Pubkey::default() },
                 proof: if full { d[185..217].try_into().unwrap() } else { [0; 32] },
                 stake: if d.len() >= JOB_LEN { u(217) } else { 0 },
                 mint: if d.len() == MINT_JOB_LEN { pk(225) } else if d.len() == github::GH_MINT_JOB_LEN { pk(github::GH_JOB_LEN) } else { Pubkey::default() } })
    }
    fn store(&self, d: &mut [u8]) {
        d[0] = self.state; d[1..33].copy_from_slice(self.buyer.as_ref()); d[33..65].copy_from_slice(self.worker.as_ref());
        d[65..73].copy_from_slice(&self.amount.to_le_bytes()); d[73..81].copy_from_slice(&(self.deadline as u64).to_le_bytes());
        d[81..89].copy_from_slice(&(self.review as u64).to_le_bytes()); d[89..121].copy_from_slice(&self.brief);
        d[121..153].copy_from_slice(&self.result);
        if d.len() >= V034_JOB_LEN { d[153..185].copy_from_slice(self.verifier.as_ref()); d[185..217].copy_from_slice(&self.proof); }
        if d.len() >= JOB_LEN { d[217..225].copy_from_slice(&self.stake.to_le_bytes()); }
        if d.len() == MINT_JOB_LEN { d[225..257].copy_from_slice(self.mint.as_ref()); }
        if d.len() == github::GH_MINT_JOB_LEN { d[github::GH_JOB_LEN..].copy_from_slice(self.mint.as_ref()); }
    }
}

struct Config { admin: Pubkey, mint: Pubkey, fee_token: Pubkey, fee_bps: u64, min_fee: u64, min_amount: u64, max_amount: u64, paused: bool }
impl Config {
    fn load(acc: &AccountInfo, program_id: &Pubkey, key: &Pubkey) -> Result<Config, ProgramError> {
        if acc.key != key || acc.owner != program_id { return Err(err(14, "config")); }
        let d = acc.try_borrow_data()?;
        if d.len() != CONFIG_LEN { return Err(err(14, "config")); }
        let pk = |o: usize| Pubkey::new_from_array(d[o..o + 32].try_into().unwrap());
        let u = |o: usize| u64::from_le_bytes(d[o..o + 8].try_into().unwrap());
        Ok(Config { admin: pk(0), mint: pk(32), fee_token: pk(64), fee_bps: u16::from_le_bytes(d[96..98].try_into().unwrap()) as u64,
                    min_fee: u(98), min_amount: u(106), max_amount: u(114), paused: d[122] != 0 })
    }
    /// fee = max(fee_bps of the price, min_fee). A job under the minimum (only jobs posted before 0.3.4) pays the
    /// percentage alone, so the floor never takes a legacy job's whole price.
    fn fee(&self, amount: u64) -> u64 {
        let pct = ((amount as u128) * (self.fee_bps as u128) / 10_000) as u64;
        if amount >= self.min_amount && pct < self.min_fee { self.min_fee } else { pct }
    }
}

fn token_owner_mint(acc: &AccountInfo) -> Result<(Pubkey, Pubkey), ProgramError> {
    if *acc.owner != TOKEN_PROGRAM { return Err(err(10, "not a token account")); }
    let d = acc.try_borrow_data()?;
    if d.len() < 72 { return Err(err(11, "bad token account")); }
    Ok((Pubkey::new_from_array(d[32..64].try_into().unwrap()), Pubkey::new_from_array(d[0..32].try_into().unwrap())))
}

fn token_transfer<'a>(token_prog: &AccountInfo<'a>, from: &AccountInfo<'a>, to: &AccountInfo<'a>, auth: &AccountInfo<'a>, amount: u64,
                  seeds: Option<&[&[u8]]>) -> ProgramResult {
    let mut data = vec![3u8]; data.extend_from_slice(&amount.to_le_bytes()); // SPL Token Transfer
    let ix = Instruction { program_id: TOKEN_PROGRAM, data,
        accounts: vec![AccountMeta::new(*from.key, false), AccountMeta::new(*to.key, false), AccountMeta::new_readonly(*auth.key, true)] };
    match seeds {
        Some(s) => invoke_signed(&ix, &[from.clone(), to.clone(), auth.clone(), token_prog.clone()], &[s]),
        None => invoke(&ix, &[from.clone(), to.clone(), auth.clone(), token_prog.clone()]),
    }
}

/// Create a PDA even if someone pre-funded its address with dust (create_account would fail on lamports > 0).
fn create_pda<'a>(payer: &AccountInfo<'a>, acc: &AccountInfo<'a>, sys: &AccountInfo<'a>, owner: &Pubkey, len: usize, seeds: &[&[u8]]) -> ProgramResult {
    let need = Rent::get()?.minimum_balance(len);
    if acc.lamports() == 0 {
        return invoke_signed(&system_instruction::create_account(payer.key, acc.key, need, len as u64, owner), &[payer.clone(), acc.clone(), sys.clone()], &[seeds]);
    }
    if acc.lamports() < need { invoke(&system_instruction::transfer(payer.key, acc.key, need - acc.lamports()), &[payer.clone(), acc.clone(), sys.clone()])?; }
    invoke_signed(&system_instruction::allocate(acc.key, len as u64), &[acc.clone(), sys.clone()], &[seeds])?;
    invoke_signed(&system_instruction::assign(acc.key, owner), &[acc.clone(), sys.clone()], &[seeds])
}

fn arr32(d: &[u8], o: usize) -> Result<[u8; 32], ProgramError> {
    d.get(o..o + 32).ok_or(ProgramError::InvalidInstructionData).map(|s| s.try_into().unwrap())
}
fn u64_at(d: &[u8], o: usize) -> Result<u64, ProgramError> {
    d.get(o..o + 8).ok_or(ProgramError::InvalidInstructionData).map(|s| u64::from_le_bytes(s.try_into().unwrap()))
}

/// Pay a delivered job: worker net, fee to the fee account. Shared by Accept, Release and VerifyRelease.
#[allow(clippy::too_many_arguments)]
fn pay_out<'a>(j: &mut Job, job: &AccountInfo<'a>, cfg: &Config, vault_tok: &AccountInfo<'a>, vauth: &AccountInfo<'a>,
               worker_tok: &AccountInfo<'a>, fee_tok: &AccountInfo<'a>, token: &AccountInfo<'a>, vault_bump: u8) -> ProgramResult {
    let (wo, _) = token_owner_mint(worker_tok)?;
    if wo != j.worker { return Err(err(33, "payee")); }
    if j.mint == Pubkey::default() {
        if *fee_tok.key != cfg.fee_token { return Err(err(33, "payee")); }
    } else {
        // A registered mint's fee goes to a token account of that mint owned by the admin.
        let (fo, fm) = token_owner_mint(fee_tok)?;
        if fo != cfg.admin || fm != j.mint { return Err(err(33, "payee")); }
    }
    let fee = cfg.fee(j.amount).min(j.amount);
    j.state = S::Released as u8; j.store(&mut job.try_borrow_mut_data()?);
    let b = [vault_bump]; let seeds = vseeds(&j.mint, &b);
    token_transfer(token, vault_tok, worker_tok, vauth, j.amount - fee, Some(&seeds[..]))?;
    if fee > 0 { token_transfer(token, vault_tok, fee_tok, vauth, fee, Some(&seeds[..]))?; }
    Ok(())
}

/// Refund a job to its buyer: the price, plus a timed-out claim's stake. Shared by Reject, Refund, VerifyReject, Settle.
fn refund_out<'a>(j: &mut Job, job: &AccountInfo<'a>, vault_tok: &AccountInfo<'a>, vauth: &AccountInfo<'a>,
                  buyer_tok: &AccountInfo<'a>, token: &AccountInfo<'a>, vault_bump: u8) -> ProgramResult {
    let (bo, _) = token_owner_mint(buyer_tok)?;
    if bo != j.buyer { return Err(err(42, "refund to buyer only")); }
    let total = j.amount.checked_add(j.stake).ok_or(ProgramError::ArithmeticOverflow)?;
    j.state = S::Refunded as u8; j.stake = 0; j.store(&mut job.try_borrow_mut_data()?);
    let b = [vault_bump]; let seeds = vseeds(&j.mint, &b);
    token_transfer(token, vault_tok, buyer_tok, vauth, total, Some(&seeds[..]))
}

/// The vault authority's signer seeds for a job's mint: ["vault"] (config mint) or ["vault", mint].
fn vseeds<'s>(mint: &'s Pubkey, bump: &'s [u8; 1]) -> Vec<&'s [u8]> {
    if *mint == Pubkey::default() { vec![&b"vault"[..], &bump[..]] } else { vec![&b"vault"[..], mint.as_ref(), &bump[..]] }
}

/// Close a settled job: every lamport (its rent) goes to the buyer who funded it; the account is emptied and handed
/// back to the system program, so nothing can act on it again and its address can be reused only by a fresh post.
fn close_job<'a>(j: &Job, job: &AccountInfo<'a>, buyer: &AccountInfo<'a>) -> ProgramResult {
    if *buyer.key != j.buyer || !buyer.is_writable { return Err(err(44, "rent back to the buyer only")); }
    let lamports = job.lamports();
    **buyer.try_borrow_mut_lamports()? = buyer.lamports().checked_add(lamports).ok_or(ProgramError::ArithmeticOverflow)?;
    **job.try_borrow_mut_lamports()? = 0;
    job.resize(0)?;
    job.assign(&system_program::ID);
    Ok(())
}

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let (&tag, rest) = data.split_first().ok_or(ProgramError::InvalidInstructionData)?;
    let it = &mut accounts.iter();
    let (config_key, config_bump) = Pubkey::find_program_address(&[b"config2"], program_id);
    let (vault_auth, vault_bump) = Pubkey::find_program_address(&[b"vault"], program_id);
    match tag {
        // 0 Init (the ["config"] layout) is retired: Init2 below.
        0 => Err(err(1, "retired: use Init2")),
        // 8 Init2: admin(s,w), config2(w), fee_token, system, legacy_config.
        //   data: fee_bps u16, min_fee u64, min_amount u64, max_amount u64 (0 = no cap), paused u8
        //   If the legacy ["config"] exists, only its admin may run Init2 (no front-running an in-place upgrade).
        8 => {
            let admin = next_account_info(it)?; let config = next_account_info(it)?; let fee_token = next_account_info(it)?;
            let sys = next_account_info(it)?; let legacy = next_account_info(it)?;
            let (legacy_key, _) = Pubkey::find_program_address(&[b"config"], program_id);
            if !admin.is_signer || *config.key != config_key || *sys.key != system_program::ID || *legacy.key != legacy_key {
                return Err(err(1, "init accounts"));
            }
            if legacy.owner == program_id && legacy.data_len() >= LEGACY_CONFIG_LEN {
                let d = legacy.try_borrow_data()?;
                if d[0..32] != admin.key.as_ref()[..] { return Err(err(1, "only the existing admin")); }
            }
            if !config.data_is_empty() || *config.owner != system_program::ID { return Err(err(6, "config exists")); }
            let (_, mint) = token_owner_mint(fee_token)?;
            if rest.len() < 2 + 8 + 8 + 8 + 1 { return Err(ProgramError::InvalidInstructionData); }
            let fee_bps = u16::from_le_bytes(rest[0..2].try_into().unwrap());
            let (min_fee, min_amount, max_amount) = (u64_at(rest, 2)?, u64_at(rest, 10)?, u64_at(rest, 18)?);
            if fee_bps > 2000 { return Err(err(2, "fee too high")); }
            if min_amount == 0 || min_fee > min_amount || (max_amount != 0 && max_amount < min_amount) { return Err(err(2, "bad limits")); }
            create_pda(admin, config, sys, program_id, CONFIG_LEN, &[b"config2", &[config_bump]])?;
            let mut d = config.try_borrow_mut_data()?;
            d[0..32].copy_from_slice(admin.key.as_ref()); d[32..64].copy_from_slice(mint.as_ref());
            d[64..96].copy_from_slice(fee_token.key.as_ref()); d[96..98].copy_from_slice(&fee_bps.to_le_bytes());
            d[98..106].copy_from_slice(&min_fee.to_le_bytes()); d[106..114].copy_from_slice(&min_amount.to_le_bytes());
            d[114..122].copy_from_slice(&max_amount.to_le_bytes()); d[122] = (rest[26] != 0) as u8; d[123] = config_bump;
            Ok(())
        }
        // 9 SetPause: admin(s), config2(w). data: paused u8. Stops new posts only; settlement and refunds never pause.
        // 10 LowerCap: admin(s), config2(w). data: max_amount u64 (non-zero; never above the current cap).
        // 14 LowerFee: admin(s), config2(w). data: fee_bps u16 (never above the current fee).
        9 | 10 | 14 => {
            let admin = next_account_info(it)?; let config = next_account_info(it)?;
            let cfg = Config::load(config, program_id, &config_key)?;
            if !admin.is_signer || *admin.key != cfg.admin { return Err(err(15, "admin only")); }
            let mut d = config.try_borrow_mut_data()?;
            if tag == 9 {
                d[122] = (*rest.first().ok_or(ProgramError::InvalidInstructionData)? != 0) as u8;
            } else if tag == 14 {
                if rest.len() < 2 { return Err(ProgramError::InvalidInstructionData); }
                let bps = u16::from_le_bytes(rest[0..2].try_into().unwrap());
                if bps as u64 > cfg.fee_bps { return Err(err(17, "fee only goes down")); }
                d[96..98].copy_from_slice(&bps.to_le_bytes());
            } else {
                let cap = u64_at(rest, 0)?;
                if cap == 0 || (cfg.max_amount != 0 && cap > cfg.max_amount) || cap < cfg.min_amount { return Err(err(16, "cap only goes down")); }
                d[114..122].copy_from_slice(&cap.to_le_bytes());
            }
            Ok(())
        }
        // 1 Post: buyer(s,w), job(w), buyer_token(w), vault_token(w), config2, token, system.
        //   data: id[32] amount u64 work i64 review i64 brief[32] [verifier[32]] (absent or zero = no verifier)
        1 | 23 => {
            let buyer = next_account_info(it)?; let job = next_account_info(it)?; let buyer_tok = next_account_info(it)?;
            let vault_tok = next_account_info(it)?; let config = next_account_info(it)?; let token = next_account_info(it)?; let sys = next_account_info(it)?;
            if rest.len() < 32 + 8 + 8 + 8 + 32 { return Err(ProgramError::InvalidInstructionData); }
            let id: [u8; 32] = rest[0..32].try_into().unwrap();
            let amount = u64::from_le_bytes(rest[32..40].try_into().unwrap());
            let work = i64::from_le_bytes(rest[40..48].try_into().unwrap());
            let review = i64::from_le_bytes(rest[48..56].try_into().unwrap());
            let brief: [u8; 32] = rest[56..88].try_into().unwrap();
            let verifier = if rest.len() >= 120 { Pubkey::new_from_array(arr32(rest, 88)?) } else { Pubkey::default() };
            if !buyer.is_signer || *token.key != TOKEN_PROGRAM || *sys.key != system_program::ID { return Err(err(3, "post accounts")); }
            let cfg = Config::load(config, program_id, &config_key)?;
            if cfg.paused { return Err(err(17, "paused: no new jobs")); }
            // 23 PostBounty: a bounty may be funded with any amount, 0 included (paid on proof, the stake still applies).
            if tag != 23 && amount < cfg.min_amount { return Err(err(18, "below the minimum job")); }
            if cfg.max_amount != 0 && amount > cfg.max_amount { return Err(err(19, "over the per-job cap")); }
            if work <= 0 || review <= 0 { return Err(err(4, "bad terms")); }
            let (job_key, bump) = Pubkey::find_program_address(&[b"job", &id], program_id);
            if *job.key != job_key { return Err(err(5, "job address")); }
            if !job.data_is_empty() || *job.owner != system_program::ID { return Err(err(6, "job exists")); }
            let (vo, vm) = token_owner_mint(vault_tok)?; let (_, bm) = token_owner_mint(buyer_tok)?;
            // 8th account (0.3.7): the mint registry ["mint", mint] -> a job in that registered mint (257 bytes).
            let (mint, len) = match next_account_info(it) {
                Ok(reg) if bm != cfg.mint => {
                    let rv = bounty::registry_vault(reg, &bm, program_id)?;
                    let (va, _) = Pubkey::find_program_address(&[b"vault", bm.as_ref()], program_id);
                    if *vault_tok.key != rv || vo != va || vm != bm { return Err(err(7, "vault or mint")); }
                    (bm, MINT_JOB_LEN)
                }
                _ => {
                    if vo != vault_auth || vm != cfg.mint || bm != cfg.mint { return Err(err(7, "vault or mint")); }
                    (Pubkey::default(), JOB_LEN)
                }
            };
            create_pda(buyer, job, sys, program_id, len, &[b"job", &id, &[bump]])?;
            token_transfer(token, buyer_tok, vault_tok, buyer, amount, None)?;
            let now = Clock::get()?.unix_timestamp;
            Job { state: S::Open as u8, buyer: *buyer.key, worker: Pubkey::default(), amount, deadline: now.saturating_add(work), review,
                  brief, result: [0; 32], verifier, proof: [0; 32], stake: 0, mint }
                .store(&mut job.try_borrow_mut_data()?);
            Ok(())
        }
        // 2 Claim: worker(s), job(w), worker_token(w), vault_token(w), config2, token
        //   The worker stakes max(10% of the price, 0.1 USDC) into the vault; never the buyer. The claim times out at
        //   the job's work deadline: undelivered by then, the price and the stake go to the buyer.
        2 => {
            let worker = next_account_info(it)?; let job = next_account_info(it)?; let worker_tok = next_account_info(it)?;
            let vault_tok = next_account_info(it)?; let config = next_account_info(it)?; let token = next_account_info(it)?;
            if *job.owner != *program_id || !worker.is_signer || *token.key != TOKEN_PROGRAM { return Err(err(8, "claim accounts")); }
            let cfg = Config::load(config, program_id, &config_key)?;
            let mut j = Job::load(&job.try_borrow_data()?)?; let now = Clock::get()?.unix_timestamp;
            if j.state != S::Open as u8 || now > j.deadline { return Err(err(20, "not open")); }
            if *worker.key == j.buyer { return Err(err(22, "a buyer cannot claim its own job")); }
            if *worker.key == j.verifier { return Err(err(36, "a worker cannot verify its own work")); }
            if github::is_gh_job(job.data_len()) && job.try_borrow_data()?[github::GH_STAKE_REQ] == 0 {
                return Err(err(78, "no claim on this github job: proofs are permissionless"));
            }
            let (vo, vm) = token_owner_mint(vault_tok)?; let (_, wm) = token_owner_mint(worker_tok)?;
            let jm = if j.mint == Pubkey::default() { cfg.mint } else { j.mint };
            bounty::vault_bump_for(&j.mint, &vo, program_id, (vault_auth, vault_bump))?;
            if vm != jm || wm != jm { return Err(err(7, "vault or mint")); }
            let stake = if job.data_len() >= JOB_LEN { stake_for(j.amount) } else { 0 };   // pre-0.3.5 jobs: no stake
            j.worker = *worker.key; j.state = S::Claimed as u8; j.stake = stake;
            j.store(&mut job.try_borrow_mut_data()?);
            if stake > 0 { token_transfer(token, worker_tok, vault_tok, worker, stake, None)?; }
            Ok(())
        }
        // 3 Deliver: worker(s), job(w), worker_token(w), vault_token(w), vault_auth, token; data result[32]
        //   Before the claim times out. The stake goes back to the worker.
        3 => {
            let worker = next_account_info(it)?; let job = next_account_info(it)?; let worker_tok = next_account_info(it)?;
            let vault_tok = next_account_info(it)?; let vauth = next_account_info(it)?; let token = next_account_info(it)?;
            if *job.owner != *program_id || !worker.is_signer || *token.key != TOKEN_PROGRAM {
                return Err(err(8, "deliver accounts"));
            }
            let mut j = Job::load(&job.try_borrow_data()?)?; let now = Clock::get()?.unix_timestamp;
            let vb = bounty::vault_bump_for(&j.mint, vauth.key, program_id, (vault_auth, vault_bump))?;
            if j.state != S::Claimed as u8 || *worker.key != j.worker { return Err(err(21, "not worker")); }
            if github::is_gh_job(job.data_len()) || job.data_len() == github::GH_V037_JOB_LEN { return Err(err(77, "a github job settles by proof, not delivery")); }
            if now > j.deadline { return Err(err(23, "the claim timed out")); }
            let (wo, _) = token_owner_mint(worker_tok)?;
            if wo != j.worker { return Err(err(33, "stake back to the worker only")); }
            let stake = j.stake;
            j.result = arr32(rest, 0)?; j.stake = 0;
            j.state = S::Delivered as u8; j.deadline = now.saturating_add(j.review);
            j.store(&mut job.try_borrow_mut_data()?);
            let b = [vb]; let seeds = vseeds(&j.mint, &b);
            if stake > 0 { token_transfer(token, vault_tok, worker_tok, vauth, stake, Some(&seeds[..]))?; }
            Ok(())
        }
        // 4 Accept: buyer(s), job(w), vault_token(w), vault_auth, worker_token(w), fee_token(w), config2, token, buyer(w)
        // 5 Release: same accounts, anyone, after the review window
        // 11 VerifyRelease: verifier(s), same accounts. data: result_hash[32] proof_root[32]. Paid on proof.
        // Each closes the job: its rent goes back to the buyer.
        4 | 5 | 11 => {
            let who = next_account_info(it)?; let job = next_account_info(it)?; let vault_tok = next_account_info(it)?; let vauth = next_account_info(it)?;
            let worker_tok = next_account_info(it)?; let fee_tok = next_account_info(it)?; let config = next_account_info(it)?; let token = next_account_info(it)?;
            let buyer = next_account_info(it)?;
            if *job.owner != *program_id || !who.is_signer || *token.key != TOKEN_PROGRAM { return Err(err(9, "release accounts")); }
            let cfg = Config::load(config, program_id, &config_key)?;
            let mut j = Job::load(&job.try_borrow_data()?)?; let now = Clock::get()?.unix_timestamp;
            let vb = bounty::vault_bump_for(&j.mint, vauth.key, program_id, (vault_auth, vault_bump))?;
            if tag == 11 {
                let (result_hash, proof_root) = (arr32(rest, 0)?, arr32(rest, 32)?);
                if j.verifier == Pubkey::default() || *who.key != j.verifier { return Err(err(34, "not the job's verifier")); }
                if *who.key == j.worker { return Err(err(36, "a worker cannot verify its own work")); }
                if j.state != S::Delivered as u8 { return Err(err(30, "not delivered")); }
                if result_hash != j.result { return Err(err(35, "verifier releases unproven work")); }
                j.proof = proof_root;
            } else {
                if j.state != S::Delivered as u8 { return Err(err(30, "not delivered")); }
                if tag == 4 && *who.key != j.buyer { return Err(err(31, "not buyer")); }
                if tag == 5 && now <= j.deadline { return Err(err(32, "in review")); }
            }
            pay_out(&mut j, job, &cfg, vault_tok, vauth, worker_tok, fee_tok, token, vb)?;
            close_job(&j, job, buyer)
        }
        // 6 Reject: buyer(s,w), job(w), vault_token(w), vault_auth, buyer_token(w), token  (inside the review window;
        //   never on a job that names a verifier: only the verifier or the deadline settles that one)
        // 7 Refund: same accounts (open/claimed past the work deadline; a timed-out claim's stake goes to the buyer)
        // 12 VerifyReject: verifier(s), job(w), vault_token(w), vault_auth, buyer_token(w), token, buyer(w).
        //   data: proof_root[32]. The job's verifier fails delivered work inside the review window: buyer refunded.
        // Each closes the job: its rent goes back to the buyer.
        6 | 7 | 12 => {
            let who = next_account_info(it)?; let job = next_account_info(it)?; let vault_tok = next_account_info(it)?; let vauth = next_account_info(it)?;
            let buyer_tok = next_account_info(it)?; let token = next_account_info(it)?;
            let buyer = if tag == 12 { next_account_info(it)? } else { who };
            if *job.owner != *program_id || !who.is_signer || *token.key != TOKEN_PROGRAM { return Err(err(12, "refund accounts")); }
            let mut j = Job::load(&job.try_borrow_data()?)?; let now = Clock::get()?.unix_timestamp;
            let vb = bounty::vault_bump_for(&j.mint, vauth.key, program_id, (vault_auth, vault_bump))?;
            if tag == 12 {
                if j.verifier == Pubkey::default() || *who.key != j.verifier { return Err(err(34, "not the job's verifier")); }
                j.proof = arr32(rest, 0)?;
            } else if *who.key != j.buyer { return Err(err(40, "not buyer")); }
            if tag == 6 && j.verifier != Pubkey::default() { return Err(err(43, "a verified job: only its verifier can reject")); }
            let ok = if tag == 7 { (j.state == S::Open as u8 || j.state == S::Claimed as u8) && now > j.deadline }
                     else { j.state == S::Delivered as u8 && now <= j.deadline };
            if !ok { return Err(err(41, "not refundable")); }
            refund_out(&mut j, job, vault_tok, vauth, buyer_tok, token, vb)?;
            close_job(&j, job, buyer)
        }
        // 13 Settle (the deadline crank, anyone): signer(s), job(w), vault_token(w), vault_auth, worker_token(w),
        //   fee_token(w), buyer_token(w), buyer(w), config2, token.
        //   Delivered and past the review deadline with no verdict: the worker is paid. Open or claimed past the work
        //   deadline: the buyer is refunded (with a timed-out claim's stake). Closes the job.
        13 => {
            let who = next_account_info(it)?; let job = next_account_info(it)?; let vault_tok = next_account_info(it)?; let vauth = next_account_info(it)?;
            let worker_tok = next_account_info(it)?; let fee_tok = next_account_info(it)?; let buyer_tok = next_account_info(it)?;
            let buyer = next_account_info(it)?; let config = next_account_info(it)?; let token = next_account_info(it)?;
            if *job.owner != *program_id || !who.is_signer || *token.key != TOKEN_PROGRAM { return Err(err(9, "settle accounts")); }
            let cfg = Config::load(config, program_id, &config_key)?;
            let mut j = Job::load(&job.try_borrow_data()?)?; let now = Clock::get()?.unix_timestamp;
            let vb = bounty::vault_bump_for(&j.mint, vauth.key, program_id, (vault_auth, vault_bump))?;
            if now <= j.deadline { return Err(err(32, "not past the deadline")); }
            if j.state == S::Delivered as u8 {
                pay_out(&mut j, job, &cfg, vault_tok, vauth, worker_tok, fee_tok, token, vb)?;
            } else if j.state == S::Open as u8 || j.state == S::Claimed as u8 {
                refund_out(&mut j, job, vault_tok, vauth, buyer_tok, token, vb)?;
            } else {
                return Err(err(41, "nothing to settle"));
            }
            close_job(&j, job, buyer)
        }
        // 15 RegisterKey, 16 BufferWrite, 17 VerifyStep1, 18 VerifyStep2, 19 PostGithub: see github.rs
        // 26 FundWithToken (devnet): a fund.yml token funds a github job with minted test USDC; see github.rs
        15..=19 | 26 => github::process(program_id, accounts, tag, rest, &config_key, &vault_auth, vault_bump),
        // 25 RegisterIssuer (admin): an OIDC issuer (GitHub, GitLab CI) keys can be scoped to; see github.rs
        25 => github::register_issuer(program_id, accounts, rest, &config_key),
        // 29 Version: logs the program's version ("knos-escrow X.Y.Z"); no accounts.
        29 => { msg!("{}", VERSION); Ok(()) }
        // 20 Faucet, 21 InitFaucetMint (devnet builds only), 22 AddMint: see bounty.rs.
        20 => bounty::faucet(program_id, accounts, rest),
        21 => bounty::init_faucet_mint(program_id, accounts, rest, &config_key),
        22 => bounty::add_mint(program_id, accounts, &config_key),
        24 => github::set_workflow(program_id, accounts, rest, &config_key),
        // 27 SetAdmin: admin(s), config2(w). data: new_admin[32] (non-zero; e.g. a Squads vault PDA). The current
        //   admin signs; from then on only the new admin passes any admin check.
        // 28 SetFeeAccount: admin(s), config2(w), fee_token. The new fee account must be a token account of the
        //   config mint.
        27 | 28 => {
            let admin = next_account_info(it)?; let config = next_account_info(it)?;
            let cfg = Config::load(config, program_id, &config_key)?;
            if !admin.is_signer || *admin.key != cfg.admin { return Err(err(15, "admin only")); }
            if tag == 27 {
                let new_admin = arr32(rest, 0)?;
                if new_admin == [0u8; 32] { return Err(err(2, "admin cannot be zero")); }
                config.try_borrow_mut_data()?[0..32].copy_from_slice(&new_admin);
            } else {
                let fee_token = next_account_info(it)?;
                let (_, fm) = token_owner_mint(fee_token)?;
                if fm != cfg.mint { return Err(err(7, "fee account mint")); }
                config.try_borrow_mut_data()?[64..96].copy_from_slice(fee_token.key.as_ref());
            }
            Ok(())
        }
        _ => Err(ProgramError::InvalidInstructionData),
    }
}
