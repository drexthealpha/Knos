//! upgrade_gate: a public, on-chain statement that GitHub's runner built these exact bytes from that commit.
//!
//! Knos's programs are upgradeable only through a multisig with a public 48-hour delay, until an outside review.
//! The members compare a buffer's hash with a build they made themselves; this program adds a statement nobody
//! at Knos can write by hand. A record ["build", program, hash] exists only if GitHub signed a token for a run of
//! Knos's own program.yml, at a commit of main or of a release tag, on a GitHub-hosted runner, whose audience is
//! gate:<program>:<hash hex>: the workflow built the program at that commit and asked GitHub to sign the hash of
//! what it built. knos-oidc verified GitHub's signature on chain; this program reads the claims and writes the
//! record. scripts/governance.mjs refuses to propose an upgrade whose buffer has no record (unless --ungated),
//! and `knos status` says whether a pending upgrade's buffer has one.
//!
//! What a record does NOT say: that the commit is good. It says which commit to read. The workflow file is the one
//! at that commit (`job_workflow_sha` is the commit built), so a commit that changed program.yml to sign another
//! hash shows that change in its own diff.
//!
//!   Record  payer(s,w) token key record(w) system        (no data: the program and the hash are the audience's)
//!           record = ["build", program [32], hash [32]], 136 bytes: version u8 (1), bump u8, run_id u64 @8,
//!           time i64 @16, slot u64 @24, program @32, hash @64, sha [40] @96 (the commit, as 40 hex characters).
//!           Written once: the first commit GitHub built these bytes from stays.
//!
//! `hash` is sha256 of the executable without its trailing zero bytes: what `solana-verify get-executable-hash`
//! prints for the .so file, for a buffer and for a deployed program alike.
use knos_oidc_interface::{b58_32, number, parts, text, unhex32, Error, Token, ISSUER_GITHUB};
use solana_program::{
    account_info::{next_account_info, AccountInfo},
    clock::Clock,
    entrypoint,
    entrypoint::ProgramResult,
    msg,
    program::invoke_signed,
    program_error::ProgramError,
    pubkey::Pubkey,
    rent::Rent,
    system_instruction,
    sysvar::Sysvar,
};

solana_program::declare_id!("2DfVEuBMWvvh3kXZaQwk2SoszJsoV1PTiK1VGCkB55HW");

/// drexthealpha/Knos, by the id GitHub signs (a repository's name can change hands; its id cannot).
pub const KNOS_REPO_ID: u64 = 1_353_152_983;
/// The workflow that builds the programs: a token's `job_workflow_ref` must start with this.
pub const WORKFLOW: &[u8] = b"drexthealpha/Knos/.github/workflows/program.yml@";
pub const RECORD_LEN: usize = 136;
pub const E_RUN: u32 = 1;       // not a run of Knos's program.yml on a GitHub-hosted runner at a commit of main or a release tag
pub const E_AUDIENCE: u32 = 2;  // the audience is not gate:<program>:<hash hex>

entrypoint!(process);

/// The interface's errors as program errors; a claim or key error keeps knos-oidc's code (61 to 63, 68, 76 to 78).
fn refused(e: Error) -> ProgramError {
    match e {
        Error::NotOidc => ProgramError::IllegalOwner,
        Error::NotVerified | Error::Stale | Error::Private => ProgramError::InvalidAccountData,
        other => ProgramError::Custom(other.code()),
    }
}

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let it = &mut accounts.iter();
    let payer = next_account_info(it)?; let token = next_account_info(it)?; let key = next_account_info(it)?; let record = next_account_info(it)?;
    let sys = next_account_info(it)?;
    if !data.is_empty() { return Err(ProgramError::InvalidInstructionData); }
    let clock = Clock::get()?;
    // ---- a token knos-oidc verified, GitHub's, from a key that is still good ----
    let d = token.try_borrow_data()?;
    let tok = Token::read(&token.owner.to_bytes(), &d, clock.unix_timestamp).map_err(refused)?;
    if tok.issuer() != ISSUER_GITHUB { return Err(ProgramError::InvalidAccountData); }
    tok.check_key(&key.key.to_bytes(), &key.owner.to_bytes(), &key.try_borrow_data()?, clock.unix_timestamp).map_err(refused)?;
    let [repo, wf_ref, wf_sha, runner, git_ref, sha, run, aud] = tok.claims([b"repository_id", b"job_workflow_ref", b"job_workflow_sha", b"runner_environment",
                                                                           b"ref", b"sha", b"run_id", b"aud"]).map_err(refused)?;
    // ---- Knos's program.yml, as it is at the commit it built, on main or a release tag, on GitHub's own runner ----
    let (git_ref, sha) = (text(git_ref).map_err(refused)?, text(sha).map_err(refused)?);
    let mut commit = [0u8; 40];
    let ok = number(repo).map_err(refused)? == KNOS_REPO_ID && text(wf_ref).map_err(refused)?.starts_with(WORKFLOW)
        && text(runner).map_err(refused)?.is("github-hosted") && (git_ref.is("refs/heads/main") || git_ref.starts_with("refs/tags/v"))
        && sha.len() == 40 && sha.copy_to(&mut commit).is_some() && commit.iter().all(|c| matches!(c, b'0'..=b'9' | b'a'..=b'f'))
        && text(wf_sha).map_err(refused)?.is(commit);
    if !ok { return Err(ProgramError::Custom(E_RUN)); }
    // ---- what it built: gate:<program>:<hash hex> ----
    let aud = text(aud).map_err(refused)?.as_plain().ok_or(ProgramError::Custom(E_AUDIENCE))?;
    let [k, program, hash] = parts::<3>(aud).ok_or(ProgramError::Custom(E_AUDIENCE))?;
    let (program, hash) = (b58_32(program).ok_or(ProgramError::Custom(E_AUDIENCE))?, unhex32(hash).ok_or(ProgramError::Custom(E_AUDIENCE))?);
    if k != b"gate" { return Err(ProgramError::Custom(E_AUDIENCE)); }
    // ---- record it, once ----
    let (rk, bump) = Pubkey::find_program_address(&[b"build", &program, &hash], program_id);
    if *record.key != rk || !payer.is_signer { return Err(ProgramError::InvalidSeeds); }
    if record.owner == program_id { return Err(ProgramError::AccountAlreadyInitialized); }
    let seeds: &[&[u8]] = &[b"build", &program, &hash, &[bump]];
    let need = Rent::get()?.minimum_balance(RECORD_LEN).saturating_sub(record.lamports());
    if need > 0 { invoke_signed(&system_instruction::transfer(payer.key, record.key, need), &[payer.clone(), record.clone(), sys.clone()], &[])?; }
    invoke_signed(&system_instruction::allocate(record.key, RECORD_LEN as u64), &[record.clone(), sys.clone()], &[seeds])?;
    invoke_signed(&system_instruction::assign(record.key, program_id), &[record.clone(), sys.clone()], &[seeds])?;
    let run = number(run).map_err(refused)?;
    let mut r = record.try_borrow_mut_data()?;
    r[0] = 1; r[1] = bump;
    r[8..16].copy_from_slice(&run.to_le_bytes());
    r[16..24].copy_from_slice(&clock.unix_timestamp.to_le_bytes());
    r[24..32].copy_from_slice(&clock.slot.to_le_bytes());
    r[32..64].copy_from_slice(&program);
    r[64..96].copy_from_slice(&hash);
    r[96..136].copy_from_slice(&commit);
    msg!("gate: build program={} hash={} commit={} run={}", Pubkey::new_from_array(program), core::str::from_utf8(aud).unwrap_or("").rsplit(':').next().unwrap_or(""),
         core::str::from_utf8(&commit).unwrap_or(""), run);
    Ok(())
}
