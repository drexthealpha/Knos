//! Copy this file into your program as `src/lib.rs` and change the three lines marked CHANGE. It is the whole of what
//! a Solana program needs to act only on a fact GitHub signed: no CPI, no oracle, no key of anyone's.
//!
//! Cargo.toml:   solana-program = "2.2"
//!               knos-oidc-interface = { git = "https://github.com/drexthealpha/Knos", tag = "v0.3.15" }
//!
//! Accounts:     0  token  read-only   the token account knos-oidc wrote (the client verifies the token first)
//!               1  key    read-only   the key account that verified it: its address is inside the token account
//!               ... your own accounts
use knos_oidc_interface::{Error, Token, ISSUER_GITHUB};
use solana_program::{account_info::{next_account_info, AccountInfo}, clock::Clock, entrypoint, entrypoint::ProgramResult,
                     program_error::ProgramError, pubkey::Pubkey, sysvar::Sysvar};

const AUDIENCE: &str = "my-app:release:";      // CHANGE: a prefix only your program uses
const REPOSITORY_ID: u64 = 0;                  // CHANGE: the repository whose workflow may do this (GitHub's numeric id)
const WORKFLOW: &str = "octo/widgets/.github/workflows/release.yml@";      // CHANGE: the workflow file that may ask

entrypoint!(process);

fn refused(e: Error) -> ProgramError { ProgramError::Custom(e.code()) }

pub fn process(_program_id: &Pubkey, accounts: &[AccountInfo], _data: &[u8]) -> ProgramResult {
    let it = &mut accounts.iter();
    let (token, key) = (next_account_info(it)?, next_account_info(it)?);
    let now = Clock::get()?.unix_timestamp;
    let data = token.try_borrow_data()?;
    // 1. the account is knos-oidc's (second deployment), the signature was checked to the end, and the token is fresh
    let tok = Token::read(&token.owner.to_bytes(), &data, now).map_err(refused)?;
    // 2. the key that verified it has not expired and was not revoked: without this a revoked key works for an hour more
    tok.check_key(&key.key.to_bytes(), &key.owner.to_bytes(), &key.try_borrow_data()?, now).map_err(refused)?;
    // 3. GitHub signed it, for your program and nobody else's, from the repository and the workflow file you trust
    if tok.issuer() != ISSUER_GITHUB { return Err(ProgramError::InvalidAccountData); }
    let aud = tok.audience().ok_or(ProgramError::InvalidArgument)?;
    let wf = tok.claim("job_workflow_ref").ok_or(ProgramError::InvalidArgument)?;
    if !aud.starts_with(AUDIENCE) || !wf.starts_with(WORKFLOW) || tok.claim_u64("repository_id") != Some(REPOSITORY_ID) {
        return Err(ProgramError::InvalidArgument);
    }
    // 4. YOUR action goes here. Put what it does after the prefix of the audience (an amount, a recipient, a nonce),
    //    compare it with what this instruction is about to do, and record that it was done (an account at a PDA of
    //    the nonce): a verified token can be read by anyone, any number of times, until an hour after it expires.
    Ok(())
}
