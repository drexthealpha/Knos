//! A program that does one thing ("release") only when GitHub signed that YOUR workflow in YOUR repository asked
//! this program for it, and knos-oidc checked that signature on chain. Copy the folder, change the two constants
//! marked CHANGE, build, deploy with your own key. README.md has the steps and the five mistakes to avoid.
//!
//!   Release   payer(signer, writable)  token  key  done(writable)  system        (no data)
//!     token  the account knos-oidc verified the token in          key   the key account that token names
//!     done   ["done", sha256(the token's claims)] under this program: repository_id u64, slot u64, sha[40]
//!
//! The workflow asks GitHub for a token whose audience is `release:<this program's address>`.
use knos_oidc_interface::{b58_32, Error, Token, ISSUER_GITHUB};
use solana_program::{
    account_info::{next_account_info, AccountInfo},
    clock::Clock,
    entrypoint,
    entrypoint::ProgramResult,
    hash::hash,
    program::invoke_signed,
    program_error::ProgramError,
    pubkey::Pubkey,
    rent::Rent,
    system_instruction,
    sysvar::Sysvar,
};

const REPOSITORY_ID: u64 = 424242001; // CHANGE: your repository's numeric id (`gh api repos/OWNER/REPO --jq .id`)
const WORKFLOW: &str = "octo/widgets/.github/workflows/release.yml@refs/heads/main"; // CHANGE: the one workflow file that may act

pub const AUDIENCE: &[u8] = b"release:";
pub const DONE_LEN: usize = 56;
/// Why this program refused, as a custom error. A smaller number is knos-oidc-interface's own (`Error::code`).
pub const E_ISSUER: u32 = 100;
pub const E_AUDIENCE: u32 = 101;
pub const E_REPOSITORY: u32 = 102;
pub const E_WORKFLOW: u32 = 103;
pub const E_USED: u32 = 104;
pub const E_ACCOUNTS: u32 = 105;

fn no(code: u32) -> ProgramError { ProgramError::Custom(code) }
fn refused(e: Error) -> ProgramError { no(e.code()) }

entrypoint!(process);

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], _data: &[u8]) -> ProgramResult {
    let it = &mut accounts.iter();
    let (payer, token, key, done, sys) =
        (next_account_info(it)?, next_account_info(it)?, next_account_info(it)?, next_account_info(it)?, next_account_info(it)?);
    let clock = Clock::get()?;
    let now = clock.unix_timestamp;
    let data = token.try_borrow_data()?;

    // [M1] [M2] [M5] the account is owned by knos-oidc at the address the crate pins (not "some program"), its
    // signature was checked to the end, and it is at most an hour past its expiry
    let tok = Token::read(&token.owner.to_bytes(), &data, now).map_err(refused)?;
    // [M2] the key that verified it has not expired and was not revoked since
    tok.check_key(&key.key.to_bytes(), &key.owner.to_bytes(), &key.try_borrow_data()?, now).map_err(refused)?;

    // [M3] knos-oidc checked the signature and the expiry, nothing else. Who signed, for whom, from where: yours.
    if tok.issuer() != ISSUER_GITHUB { return Err(no(E_ISSUER)); }
    let aud = tok.audience().and_then(|a| a.as_plain()).ok_or(no(E_AUDIENCE))?;
    let for_me = aud.strip_prefix(AUDIENCE).and_then(b58_32).is_some_and(|id| id == program_id.to_bytes());
    if !for_me { return Err(no(E_AUDIENCE)); }
    if tok.claim_u64("repository_id") != Some(REPOSITORY_ID) { return Err(no(E_REPOSITORY)); }
    if !tok.claim("job_workflow_ref").is_some_and(|w| w.is(WORKFLOW)) { return Err(no(E_WORKFLOW)); }
    let sha = tok.claim("sha").filter(|s| s.len() == 40).ok_or(refused(Error::Claim))?;

    // [M4] one token, one release: the record's address is the hash of the token's claims, and it is made once
    let id = hash(tok.payload()).to_bytes();
    let (address, bump) = Pubkey::find_program_address(&[b"done", &id], program_id);
    if *done.key != address || !payer.is_signer || !solana_program::system_program::check_id(sys.key) { return Err(no(E_ACCOUNTS)); }
    if done.owner == program_id { return Err(no(E_USED)); }
    let seeds: &[&[u8]] = &[b"done", &id, &[bump]];
    let rent = Rent::get()?.minimum_balance(DONE_LEN).saturating_sub(done.lamports());
    invoke_signed(&system_instruction::transfer(payer.key, done.key, rent), &[payer.clone(), done.clone(), sys.clone()], &[])?;
    invoke_signed(&system_instruction::allocate(done.key, DONE_LEN as u64), &[done.clone(), sys.clone()], &[seeds])?;
    invoke_signed(&system_instruction::assign(done.key, program_id), &[done.clone(), sys.clone()], &[seeds])?;

    // YOUR ACTION goes here (mint, unlock, upgrade). This one writes down what was released.
    let mut d = done.try_borrow_mut_data()?;
    d[0..8].copy_from_slice(&REPOSITORY_ID.to_le_bytes());
    d[8..16].copy_from_slice(&clock.slot.to_le_bytes());
    sha.copy_to(&mut d[16..56]).ok_or(refused(Error::Claim))?;
    Ok(())
}
