//! Example consumer of knos-oidc: a release gate. It records, per GitHub repository, the last commit for which
//! GitHub signed "a workflow ran here on a GitHub-hosted runner with audience oidc-gate:release". Anything on Solana
//! (an upgrade multisig, a DAO, a token unlock) can then require "the commit being deployed is the one CI ran on".
//!
//! The whole integration is the 7 lines in `process`, and its only dependency on Knos is the interface crate
//! (crates/knos-oidc-interface, which depends on nothing): `v1::read` checks that the token account's owner is
//! knos-oidc (here the first deployment, named: the crate's defaults read the second), that the token is verified
//! and that it is fresh; then read the claims you care about. No oracle, no CPI, no admin.
//!
//!   Record  payer(s,w) token gate(w) system        (no data)
//!           gate = ["gate", repository_id (u64 LE)] : repository_id u64, slot u64, sha[40]
use knos_oidc_interface::{number, text, v1, Error, ISSUER_GITHUB};
use solana_program::{
    account_info::{next_account_info, AccountInfo},
    clock::Clock,
    entrypoint,
    entrypoint::ProgramResult,
    program::{invoke, invoke_signed},
    program_error::ProgramError,
    pubkey::Pubkey,
    rent::Rent,
    system_instruction,
    sysvar::Sysvar,
};

pub const GATE_LEN: usize = 56;

entrypoint!(process);

/// The interface's errors as program errors; a claim error keeps knos-oidc's code (61 to 63).
fn refused(e: Error) -> ProgramError {
    match e {
        Error::NotOidc => ProgramError::IllegalOwner,
        Error::NotVerified | Error::Stale => ProgramError::InvalidAccountData,
        claim => ProgramError::Custom(claim.code()),
    }
}

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], _data: &[u8]) -> ProgramResult {
    let it = &mut accounts.iter();
    let payer = next_account_info(it)?; let token = next_account_info(it)?; let gate = next_account_info(it)?;
    let sys = next_account_info(it)?;
    let clock = Clock::get()?;
    // ---- the integration ----
    let data = token.try_borrow_data()?;
    let tok = v1::read(&token.owner.to_bytes(), &data, clock.unix_timestamp).map_err(refused)?;
    if tok.issuer() != ISSUER_GITHUB { return Err(ProgramError::InvalidAccountData); }
    let [repo, sha, runner, aud] = tok.claims([b"repository_id", b"sha", b"runner_environment", b"aud"]).map_err(refused)?;
    if !text(runner).map_err(refused)?.is("github-hosted") || !text(aud).map_err(refused)?.is("oidc-gate:release") { return Err(ProgramError::InvalidArgument); }
    let (repo, sha) = (number(repo).map_err(refused)?, text(sha).map_err(refused)?);    // facts GitHub signed
    if sha.len() != 40 { return Err(ProgramError::InvalidArgument); }
    // ---- record it ----
    let rb = repo.to_le_bytes();
    let (gk, bump) = Pubkey::find_program_address(&[b"gate", &rb], program_id);
    if *gate.key != gk || !payer.is_signer { return Err(ProgramError::InvalidSeeds); }
    if gate.owner != program_id {
        let need = Rent::get()?.minimum_balance(GATE_LEN);
        invoke(&system_instruction::transfer(payer.key, gate.key, need.saturating_sub(gate.lamports())), &[payer.clone(), gate.clone(), sys.clone()])?;
        invoke_signed(&system_instruction::allocate(gate.key, GATE_LEN as u64), &[gate.clone(), sys.clone()], &[&[b"gate", &rb, &[bump]]])?;
        invoke_signed(&system_instruction::assign(gate.key, program_id), &[gate.clone(), sys.clone()], &[&[b"gate", &rb, &[bump]]])?;
    }
    let mut g = gate.try_borrow_mut_data()?;
    g[0..8].copy_from_slice(&rb);
    g[8..16].copy_from_slice(&clock.slot.to_le_bytes());
    sha.copy_to(&mut g[16..56]).ok_or(ProgramError::InvalidArgument)?;
    Ok(())
}
