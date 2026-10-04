//! Example consumer of knos-oidc: a vault with NO private key. Nobody holds a key that moves its tokens, and it has
//! no admin. It releases tokens only when GitHub signed that one workflow file, at one commit, of one repository,
//! asked for exactly that release: a deploy bot's budget, a treasury held by CI. Whoever may start that workflow
//! (its own `on:` rules at that commit, the repository's branch protection, its environment reviewers) is who may
//! spend, and every release names the run that asked for it.
//!
//! The vault's address is derived from its rule, so the address itself says what can spend it; a different rule
//! is a different vault. A second, independent consumer of the verifier beside knos_pay: its only dependency on
//! Knos is the interface crate (crates/knos-oidc-interface, which depends on nothing). It reads the second
//! deployment of knos-oidc, and takes the key account too, so a key the guardian revoked stops paying at once.
//!
//!   0 Open     payer(s,w) vault(w) mint system
//!              data: repo_id u64, wf_sha [40], workflow (bytes: "owner/name/.github/workflows/file.yml")
//!              vault = ["vault", sha256(repo_id || sha256(workflow) || wf_sha || mint)]. Anyone opens one; the
//!              rule can never change. Its money is in any token account the vault PDA owns (its associated token
//!              account); anyone adds to it with a plain transfer.
//!   1 Release  token key vault(w) from(w) mint to(w) token_program
//!              Anyone relays. The token: verified by knos-oidc (not by a private key), GitHub's, its key still
//!              usable; `repository_id`, the file of `job_workflow_ref` and `job_workflow_sha` are the vault's;
//!              `runner_environment` github-hosted; audience vault:<vault>:<to>:<amount>:<nonce>, where <to> is
//!              the token account that receives, <amount> is in the mint's smallest units and <nonce> is greater
//!              than the last one this vault used (a token works once, and an old one never works again).
//!
//!   Vault (136 bytes): version u8 (1), bump u8, repo_id u64 @8, nonce u64 @16, sha256(workflow) @24, wf_sha [40] @56,
//!   mint @96, released u64 @128 (the sum of every release).
use knos_oidc_interface::{b58_32, number, parse_u64, parts, text, Error, Token, ISSUER_GITHUB};
use solana_program::{
    account_info::{next_account_info, AccountInfo},
    clock::Clock,
    entrypoint,
    entrypoint::ProgramResult,
    hash::hashv,
    instruction::{AccountMeta, Instruction},
    msg,
    program::invoke_signed,
    program_error::ProgramError,
    pubkey::Pubkey,
    rent::Rent,
    system_instruction,
    sysvar::Sysvar,
};

pub const VAULT_LEN: usize = 136;
pub const E_RULE: u32 = 1;      // the token is not from the vault's repository, workflow file and commit, on a hosted runner
pub const E_AUDIENCE: u32 = 2;  // the audience does not name this vault, this destination and an amount
pub const E_NONCE: u32 = 3;     // the nonce is not greater than the last one used: this token, or a newer one, was used already

entrypoint!(process);

/// The interface's errors as program errors; a claim or key error keeps knos-oidc's code (61 to 63, 68, 76 to 78).
fn refused(e: Error) -> ProgramError {
    match e {
        Error::NotOidc => ProgramError::IllegalOwner,
        Error::NotVerified | Error::Stale | Error::Private => ProgramError::InvalidAccountData,
        other => ProgramError::Custom(other.code()),
    }
}

/// What a vault's address commits to.
fn rule(repo: u64, wf: &[u8; 32], wf_sha: &[u8], mint: &Pubkey) -> [u8; 32] { hashv(&[&repo.to_le_bytes(), wf, wf_sha, mint.as_ref()]).to_bytes() }

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    match data.split_first() {
        Some((0, rest)) => open(program_id, accounts, rest),
        Some((1, [])) => release(program_id, accounts),
        _ => Err(ProgramError::InvalidInstructionData),
    }
}

fn open(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let it = &mut accounts.iter();
    let payer = next_account_info(it)?; let vault = next_account_info(it)?; let mint = next_account_info(it)?; let sys = next_account_info(it)?;
    if data.len() <= 48 || data.len() > 48 + 200 { return Err(ProgramError::InvalidInstructionData); }
    let (repo, wf_sha, workflow) = (u64::from_le_bytes(data[..8].try_into().unwrap()), &data[8..48], &data[48..]);
    let hex = wf_sha.iter().all(|c| matches!(c, b'0'..=b'9' | b'a'..=b'f'));
    if repo == 0 || !hex || !workflow.ends_with(b".yml") && !workflow.ends_with(b".yaml") || workflow.contains(&b'@') { return Err(ProgramError::InvalidArgument); }
    let wf = hashv(&[workflow]).to_bytes();
    let r = rule(repo, &wf, wf_sha, mint.key);
    let (vk, bump) = Pubkey::find_program_address(&[b"vault", &r], program_id);
    if *vault.key != vk || !payer.is_signer { return Err(ProgramError::InvalidSeeds); }
    if vault.owner == program_id { return Err(ProgramError::AccountAlreadyInitialized); }
    let seeds: &[&[u8]] = &[b"vault", &r, &[bump]];
    // an address can be sent lamports before it exists: top up, allocate and assign instead of create_account
    let need = Rent::get()?.minimum_balance(VAULT_LEN).saturating_sub(vault.lamports());
    if need > 0 { invoke_signed(&system_instruction::transfer(payer.key, vault.key, need), &[payer.clone(), vault.clone(), sys.clone()], &[])?; }
    invoke_signed(&system_instruction::allocate(vault.key, VAULT_LEN as u64), &[vault.clone(), sys.clone()], &[seeds])?;
    invoke_signed(&system_instruction::assign(vault.key, program_id), &[vault.clone(), sys.clone()], &[seeds])?;
    let mut v = vault.try_borrow_mut_data()?;
    v[0] = 1; v[1] = bump;
    v[8..16].copy_from_slice(&repo.to_le_bytes());
    v[24..56].copy_from_slice(&wf);
    v[56..96].copy_from_slice(wf_sha);
    v[96..128].copy_from_slice(mint.key.as_ref());
    Ok(())
}

fn release(program_id: &Pubkey, accounts: &[AccountInfo]) -> ProgramResult {
    let it = &mut accounts.iter();
    let token = next_account_info(it)?; let key = next_account_info(it)?; let vault = next_account_info(it)?; let from = next_account_info(it)?;
    let mint = next_account_info(it)?; let to = next_account_info(it)?; let token_program = next_account_info(it)?;
    if vault.owner != program_id || vault.data_len() != VAULT_LEN { return Err(ProgramError::InvalidAccountData); }
    let now = Clock::get()?.unix_timestamp;
    let (amount, nonce) = {
        let v = vault.try_borrow_data()?;
        if v[0] != 1 || *mint.key.as_ref() != v[96..128] { return Err(ProgramError::InvalidAccountData); }
        // ---- the integration: a token knos-oidc verified, from a key that is still good, with GitHub's own claims ----
        let data = token.try_borrow_data()?;
        let tok = Token::read(&token.owner.to_bytes(), &data, now).map_err(refused)?;
        if tok.issuer() != ISSUER_GITHUB { return Err(ProgramError::InvalidAccountData); }
        tok.check_key(&key.key.to_bytes(), &key.owner.to_bytes(), &key.try_borrow_data()?, now).map_err(refused)?;
        let [repo, wf_ref, wf_sha, runner, aud] =
            tok.claims([b"repository_id", b"job_workflow_ref", b"job_workflow_sha", b"runner_environment", b"aud"]).map_err(refused)?;
        // ---- the rule: this repository, this workflow file, this commit, a runner GitHub hosts ----
        let wf_ref = text(wf_ref).map_err(refused)?.as_plain().ok_or(ProgramError::Custom(E_RULE))?;
        let file = wf_ref.split(|&c| c == b'@').next().unwrap_or(&[]);
        let ok = number(repo).map_err(refused)?.to_le_bytes() == v[8..16] && hashv(&[file]).to_bytes() == v[24..56]
            && text(wf_sha).map_err(refused)?.is(&v[56..96]) && text(runner).map_err(refused)?.is("github-hosted");
        if !ok { return Err(ProgramError::Custom(E_RULE)); }
        // ---- what it asked for: vault:<vault>:<to>:<amount>:<nonce> ----
        let aud = text(aud).map_err(refused)?.as_plain().ok_or(ProgramError::Custom(E_AUDIENCE))?;
        let [k, named, dest, amount, nonce] = parts::<5>(aud).ok_or(ProgramError::Custom(E_AUDIENCE))?;
        let (amount, nonce) = (parse_u64(amount).ok_or(ProgramError::Custom(E_AUDIENCE))?, parse_u64(nonce).ok_or(ProgramError::Custom(E_AUDIENCE))?);
        if k != b"vault" || b58_32(named) != Some(vault.key.to_bytes()) || b58_32(dest) != Some(to.key.to_bytes()) || amount == 0 {
            return Err(ProgramError::Custom(E_AUDIENCE));
        }
        if nonce <= u64::from_le_bytes(v[16..24].try_into().unwrap()) { return Err(ProgramError::Custom(E_NONCE)); }
        msg!("vault: release {} to {} nonce {}", amount, to.key, nonce);
        (amount, nonce)
    };
    // ---- pay: TransferChecked signed by the vault PDA; the token program checks that `from` is the vault's ----
    if mint.data_len() < 82 || mint.owner != token_program.key { return Err(ProgramError::InvalidAccountData); }
    let decimals = mint.try_borrow_data()?[44];
    let mut data = vec![12u8];
    data.extend_from_slice(&amount.to_le_bytes());
    data.push(decimals);
    let ix = Instruction { program_id: *token_program.key, data, accounts: vec![
        AccountMeta::new(*from.key, false), AccountMeta::new_readonly(*mint.key, false), AccountMeta::new(*to.key, false),
        AccountMeta::new_readonly(*vault.key, true)] };
    let (r, bump) = { let v = vault.try_borrow_data()?; (rule(u64::from_le_bytes(v[8..16].try_into().unwrap()), v[24..56].try_into().unwrap(), &v[56..96], mint.key), v[1]) };
    invoke_signed(&ix, &[from.clone(), mint.clone(), to.clone(), vault.clone(), token_program.clone()], &[&[b"vault", &r, &[bump]]])?;
    let mut v = vault.try_borrow_mut_data()?;
    v[16..24].copy_from_slice(&nonce.to_le_bytes());
    let released = u64::from_le_bytes(v[128..136].try_into().unwrap()).saturating_add(amount);
    v[128..136].copy_from_slice(&released.to_le_bytes());
    Ok(())
}
