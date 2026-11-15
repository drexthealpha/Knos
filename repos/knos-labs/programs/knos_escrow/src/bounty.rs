//! 0.3.7: the devnet faucet, the mint registry (multi-mint escrow) and bounties.
//!
//!   20 Faucet         wallet(s,w) faucet mint(w) wallet_token(w) drip(w) token system      data: amount u64
//!                     Mints test USDC from the ["faucet"] PDA (the mint's authority): at most the faucet's cap per call,
//!                     once per wallet per hour (PDA ["drip", wallet] holds the last time). Devnet builds only.
//!   21 InitFaucetMint admin(s,w) config2 faucet(w) mint system                            data: cap u64
//!                     Records the faucet's mint (its mint authority must already be the ["faucet"] PDA). Devnet only.
//!   22 AddMint        admin(s,w) config2 registry(w) mint vault_token system
//!                     Registers a mint: PDA ["mint", mint] = mint(32) vault(32) bump(1). The vault is a token account of
//!                     that mint owned by the PDA ["vault", mint] (each registered mint has its own vault authority, so a
//!                     job in one mint can never be paid from another mint's vault).
//!   23 PostBounty     same accounts as Post (1); the price may be 0 (a bounty funded later or paid by proof); the
//!                     worker still stakes stake_for(price) at claim.
//!
//! A job posted with a registry account (Post or PostBounty, 8th account) is 257 bytes: the 225-byte job + mint(32).
//! Jobs without a stored mint are the config mint's and use the ["vault"] authority, exactly as before.
//!
//! The `devnet` cargo feature (default on: this build is the devnet build) enables 20 and 21; a build with
//! `--no-default-features` refuses them ("faucet: devnet only").
use solana_program::{
    account_info::{next_account_info, AccountInfo},
    clock::Clock,
    entrypoint::ProgramResult,
    instruction::{AccountMeta, Instruction},
    program::invoke_signed,
    program_error::ProgramError,
    pubkey::Pubkey,
    system_program,
    sysvar::Sysvar,
};

use crate::{create_pda, err, token_owner_mint, u64_at, Config, TOKEN_PROGRAM};

pub const FAUCET_LEN: usize = 32 + 8 + 1;   // mint, cap, bump
pub const DRIP_LEN: usize = 8;              // last drip (unix seconds)
pub const REGISTRY_LEN: usize = 32 + 32 + 1; // mint, vault, bump
pub const DRIP_PERIOD: i64 = 3600;

pub const DEVNET: bool = cfg!(feature = "devnet");

/// The vault authority for a job's mint: the legacy ["vault"] for config-mint jobs (no stored mint), else
/// ["vault", mint]. Returns the bump after checking `vauth` is that authority.
pub fn vault_bump_for(mint: &Pubkey, vauth: &Pubkey, program_id: &Pubkey, legacy: (Pubkey, u8)) -> Result<u8, ProgramError> {
    let (k, b) = if *mint == Pubkey::default() { legacy } else { Pubkey::find_program_address(&[b"vault", mint.as_ref()], program_id) };
    if *vauth != k { return Err(err(7, "vault authority for the job's mint")); }
    Ok(b)
}

/// A registered mint's vault, from its registry account; refuses an unregistered mint or a forged registry.
pub fn registry_vault(reg: &AccountInfo, mint: &Pubkey, program_id: &Pubkey) -> Result<Pubkey, ProgramError> {
    let (k, _) = Pubkey::find_program_address(&[b"mint", mint.as_ref()], program_id);
    if *reg.key != k || reg.owner != program_id { return Err(err(50, "mint not registered")); }
    let d = reg.try_borrow_data()?;
    if d.len() != REGISTRY_LEN || d[0..32] != mint.as_ref()[..] { return Err(err(50, "mint not registered")); }
    Ok(Pubkey::new_from_array(d[32..64].try_into().unwrap()))
}

fn admin_check(admin: &AccountInfo, config: &AccountInfo, program_id: &Pubkey, config_key: &Pubkey) -> Result<Config, ProgramError> {
    let cfg = Config::load(config, program_id, config_key)?;
    if !admin.is_signer || *admin.key != cfg.admin { return Err(err(15, "admin only")); }
    Ok(cfg)
}

pub fn add_mint(program_id: &Pubkey, accounts: &[AccountInfo], config_key: &Pubkey) -> ProgramResult {
    let it = &mut accounts.iter();
    let admin = next_account_info(it)?; let config = next_account_info(it)?; let reg = next_account_info(it)?;
    let mint = next_account_info(it)?; let vault = next_account_info(it)?; let sys = next_account_info(it)?;
    let cfg = admin_check(admin, config, program_id, config_key)?;
    if *sys.key != system_program::ID || *mint.owner != TOKEN_PROGRAM { return Err(err(51, "add mint accounts")); }
    if *mint.key == cfg.mint { return Err(err(51, "the config mint is already the escrow's")); }
    let (rk, rb) = Pubkey::find_program_address(&[b"mint", mint.key.as_ref()], program_id);
    if *reg.key != rk { return Err(err(51, "registry address")); }
    if !reg.data_is_empty() || *reg.owner != system_program::ID { return Err(err(6, "mint already registered")); }
    let (va, _) = Pubkey::find_program_address(&[b"vault", mint.key.as_ref()], program_id);
    let (vo, vm) = token_owner_mint(vault)?;
    if vo != va || vm != *mint.key { return Err(err(7, "vault or mint")); }
    create_pda(admin, reg, sys, program_id, REGISTRY_LEN, &[b"mint", mint.key.as_ref(), &[rb]])?;
    let mut d = reg.try_borrow_mut_data()?;
    d[0..32].copy_from_slice(mint.key.as_ref()); d[32..64].copy_from_slice(vault.key.as_ref()); d[64] = rb;
    Ok(())
}

pub fn init_faucet_mint(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8], config_key: &Pubkey) -> ProgramResult {
    if !DEVNET { return Err(err(60, "faucet: devnet only")); }
    let it = &mut accounts.iter();
    let admin = next_account_info(it)?; let config = next_account_info(it)?; let faucet = next_account_info(it)?;
    let mint = next_account_info(it)?; let sys = next_account_info(it)?;
    admin_check(admin, config, program_id, config_key)?;
    let cap = u64_at(data, 0)?;
    let (fk, fb) = Pubkey::find_program_address(&[b"faucet"], program_id);
    if *faucet.key != fk || *sys.key != system_program::ID || *mint.owner != TOKEN_PROGRAM || cap == 0 { return Err(err(61, "faucet accounts")); }
    if !faucet.data_is_empty() || *faucet.owner != system_program::ID { return Err(err(6, "faucet exists")); }
    {
        let m = mint.try_borrow_data()?;
        // SPL Mint: mint_authority COption<Pubkey> (4 + 32), supply u64, decimals u8, ...
        if m.len() != 82 || m[0..4] != [1, 0, 0, 0] || m[4..36] != fk.as_ref()[..] { return Err(err(62, "the mint's authority must be the faucet")); }
    }
    create_pda(admin, faucet, sys, program_id, FAUCET_LEN, &[b"faucet", &[fb]])?;
    let mut d = faucet.try_borrow_mut_data()?;
    d[0..32].copy_from_slice(mint.key.as_ref()); d[32..40].copy_from_slice(&cap.to_le_bytes()); d[40] = fb;
    Ok(())
}

pub fn faucet(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    if !DEVNET { return Err(err(60, "faucet: devnet only")); }
    let it = &mut accounts.iter();
    let wallet = next_account_info(it)?; let faucet = next_account_info(it)?; let mint = next_account_info(it)?;
    let wallet_tok = next_account_info(it)?; let drip = next_account_info(it)?; let token = next_account_info(it)?;
    let sys = next_account_info(it)?;
    let amount = u64_at(data, 0)?;
    let (fk, _) = Pubkey::find_program_address(&[b"faucet"], program_id);
    if !wallet.is_signer || *faucet.key != fk || faucet.owner != program_id || *token.key != TOKEN_PROGRAM || *sys.key != system_program::ID {
        return Err(err(61, "faucet accounts"));
    }
    let (fmint, cap, fb) = {
        let d = faucet.try_borrow_data()?;
        if d.len() != FAUCET_LEN { return Err(err(61, "faucet accounts")); }
        (Pubkey::new_from_array(d[0..32].try_into().unwrap()), u64_at(&d, 32)?, d[40])
    };
    if *mint.key != fmint { return Err(err(61, "not the faucet's mint")); }
    if amount == 0 || amount > cap { return Err(err(63, "over the faucet's per-call cap")); }
    let (wo, wm) = token_owner_mint(wallet_tok)?;
    if wo != *wallet.key || wm != fmint { return Err(err(64, "drip to the signer's own account")); }
    let (dk, db) = Pubkey::find_program_address(&[b"drip", wallet.key.as_ref()], program_id);
    if *drip.key != dk { return Err(err(61, "drip address")); }
    let now = Clock::get()?.unix_timestamp;
    if drip.owner == program_id && drip.data_len() == DRIP_LEN {
        let last = u64_at(&drip.try_borrow_data()?, 0)? as i64;
        if now < last.saturating_add(DRIP_PERIOD) { return Err(err(65, "one drip per wallet per hour")); }
    } else {
        create_pda(wallet, drip, sys, program_id, DRIP_LEN, &[b"drip", wallet.key.as_ref(), &[db]])?;
    }
    drip.try_borrow_mut_data()?[0..8].copy_from_slice(&(now as u64).to_le_bytes());
    let mut ixd = vec![7u8]; ixd.extend_from_slice(&amount.to_le_bytes()); // SPL Token MintTo
    let ix = Instruction { program_id: TOKEN_PROGRAM, data: ixd,
        accounts: vec![AccountMeta::new(*mint.key, false), AccountMeta::new(*wallet_tok.key, false), AccountMeta::new_readonly(fk, true)] };
    invoke_signed(&ix, &[mint.clone(), wallet_tok.clone(), faucet.clone(), token.clone()], &[&[b"faucet", &[fb]]])
}
