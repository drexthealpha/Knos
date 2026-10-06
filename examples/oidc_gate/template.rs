//! Copy this file into your program as `src/lib.rs`, change the three lines marked CHANGE, build. Your instruction then
//! runs only when a verified token says "repository X, branch main, workflow Y" (or "Google Cloud service account Z"):
//! no CPI, no oracle, no key of anyone's. README.md beside this file has the steps and the cargo commands.
//!
//! Cargo.toml:   solana-program = "2.2"
//!               knos-oidc-interface = { git = "https://github.com/drexthealpha/Knos", tag = "v0.3.17" }
//!
//! Accounts:     0  token  read-only   the token account knos-oidc wrote (the client verifies the token first)
//!               1  key    read-only   the key account that verified it: its address is inside the token account
//!               ... your own accounts
use knos_oidc_interface::{Token, ISSUER_GITHUB, ISSUER_OTHER};
use solana_program::{account_info::{next_account_info, AccountInfo}, clock::Clock, entrypoint, entrypoint::ProgramResult,
                     hash::hash, program_error::ProgramError, pubkey::Pubkey, sysvar::Sysvar};

const AUDIENCE: &str = "my-app:release:";      // CHANGE: a prefix only your program uses
const REPOSITORY_ID: u64 = 0;                  // CHANGE: repository X (GitHub's numeric id: a name can change hands)
const WORKFLOW: &str = "octo/widgets/.github/workflows/release.yml@refs/heads/main";      // CHANGE: workflow Y, on main
const SERVICE_ACCOUNT: &str = "";              // optional: service account Z (its numeric unique id); empty for none

entrypoint!(process);

/// GitHub signed: this repository, on branch main, this workflow file, on a GitHub-hosted runner.
fn from_ci(tok: &Token) -> bool {
    tok.issuer() == ISSUER_GITHUB && tok.claim_u64("repository_id") == Some(REPOSITORY_ID)
        && tok.claim("ref").is_some_and(|v| v.is("refs/heads/main")) && tok.claim("job_workflow_ref").is_some_and(|v| v.is(WORKFLOW))
        && tok.claim("runner_environment").is_some_and(|v| v.is("github-hosted"))
}

/// Google signed: this service account. Any issuer but GitHub and gitlab.com is named by the hash of its URL.
fn from_cloud(tok: &Token) -> bool {
    !SERVICE_ACCOUNT.is_empty() && tok.issuer() == ISSUER_OTHER && tok.claim("sub").is_some_and(|v| v.is(SERVICE_ACCOUNT))
        && tok.issuer_hash() == Some(&hash(b"https://accounts.google.com").to_bytes())
}

pub fn process(_program_id: &Pubkey, accounts: &[AccountInfo], _data: &[u8]) -> ProgramResult {
    let it = &mut accounts.iter();
    let (token, key) = (next_account_info(it)?, next_account_info(it)?);
    let now = Clock::get()?.unix_timestamp;
    let data = token.try_borrow_data()?;
    // 1. the account is knos-oidc's (second deployment), the signature was checked to the end, and the token is fresh
    let tok = Token::read(&token.owner.to_bytes(), &data, now).map_err(|e| ProgramError::Custom(e.code()))?;
    // 2. the key that verified it has not expired and was not revoked: without this a revoked key works for up to 25 hours
    tok.check_key(&key.key.to_bytes(), &key.owner.to_bytes(), &key.try_borrow_data()?, now).map_err(|e| ProgramError::Custom(e.code()))?;
    // 3. it was asked for your program and nobody else's, by the workload you trust
    if !tok.audience().is_some_and(|aud| aud.starts_with(AUDIENCE)) || !(from_ci(&tok) || from_cloud(&tok)) {
        return Err(ProgramError::InvalidArgument);
    }
    // 4. YOUR action goes here. Put what it does after the prefix of the audience (an amount, a recipient, a nonce),
    //    compare it with what this instruction is about to do, and record that it was done (an account at a PDA of
    //    the nonce): a verified token can be read by anyone, any number of times, until an hour after it expires.
    Ok(())
}
