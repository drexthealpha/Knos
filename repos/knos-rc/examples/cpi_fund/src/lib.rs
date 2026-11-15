//! Example funder of Knos work orders: a treasury that pays for merged changes. The treasury is a PDA of this
//! program, so no private key holds its money; its admin (a DAO's governance address, a multisig) decides what to
//! fund, and knos_pay decides, on GitHub's signature, whether the work was delivered. If it was not, anyone sends
//! knos_pay's RefundOrder after the deadline and everything, the fee included, is back in the treasury.
//!
//! The whole integration is `knos::fund_order_wallet` and `invoke_signed` in `fund`, then `knos::Order::read`: its
//! only dependency on Knos is the interface crate (crates/knos-pay-interface), which depends on solana-program alone.
//! (A funder that is a wallet and not a PDA sends the same instruction with `invoke`, or straight from a client.)
//!
//!   0 Init    admin(s,w) config(w) system
//!             Once. config = ["config"]: the admin's address. The treasury is ["treasury"], a plain system account:
//!             send it SOL for the rent of the orders it funds, and tokens to its associated token account.
//!   1 Fund    admin(s) config treasury(w) order(w) ov(w) treasury_token(w) mint auth token_program system pause knos_pay
//!             data: repo_id u64, issue u64, amount u64, seq u32, wf_repo [32], wf_sha [40], terms JSON
//!             The treasury funds a work order for one issue: `amount` for whoever delivers, the fee on top.
//!   2 TopUp   admin(s) config treasury(w) order(w) ov(w) treasury_token(w) mint auth token_program pause knos_pay
//!             data: add u64
//!             The treasury raises an order it funded.
use knos_pay_interface as knos;
use solana_program::{
    account_info::{next_account_info, AccountInfo},
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

entrypoint!(process);

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let (&tag, data) = data.split_first().ok_or(ProgramError::InvalidInstructionData)?;
    let it = &mut accounts.iter();
    let admin = next_account_info(it)?; let config = next_account_info(it)?;
    let (ck, cb) = Pubkey::find_program_address(&[b"config"], program_id);
    if *config.key != ck || !admin.is_signer { return Err(ProgramError::InvalidSeeds); }
    if tag == 0 {
        let sys = next_account_info(it)?;
        if config.owner == program_id { return Err(ProgramError::AccountAlreadyInitialized); }
        invoke_signed(&system_instruction::create_account(admin.key, config.key, Rent::get()?.minimum_balance(32), 32, program_id),
                      &[admin.clone(), config.clone(), sys.clone()], &[&[b"config", &[cb]]])?;
        config.try_borrow_mut_data()?.copy_from_slice(admin.key.as_ref());
        return Ok(());
    }
    if config.owner != program_id || config.try_borrow_data()?[..] != admin.key.to_bytes() { return Err(ProgramError::IllegalOwner); }
    let treasury = next_account_info(it)?; let order = next_account_info(it)?; let rest = it.as_slice();
    let (tk, tb) = Pubkey::find_program_address(&[b"treasury"], program_id);
    if *treasury.key != tk { return Err(ProgramError::InvalidSeeds); }
    // rest: ov treasury_token mint auth token_program ...; knos_pay checks every one of them itself
    let [_ov, treasury_token, mint, _auth, token_program, ..] = rest else { return Err(ProgramError::NotEnoughAccountKeys) };
    let mut infos = vec![treasury.clone(), order.clone()];
    infos.extend(rest.iter().cloned());
    match tag {
        1 => fund(treasury, order, treasury_token, mint, token_program, &infos, tb, data),
        2 => {
            let add = u64::from_le_bytes(data.try_into().map_err(|_| ProgramError::InvalidInstructionData)?);
            let o = knos::Order::read(order.key, order.owner, &order.try_borrow_data()?, &knos::ID).ok_or(ProgramError::InvalidAccountData)?;
            invoke_signed(&knos::top_up(&knos::ID, treasury.key, order.key, &o, add, Some(treasury_token.key)), &infos, &[&[b"treasury", &[tb]]])
        }
        _ => Err(ProgramError::InvalidInstructionData),
    }
}

#[allow(clippy::too_many_arguments)]
fn fund<'a>(treasury: &AccountInfo<'a>, order: &AccountInfo<'a>, treasury_token: &AccountInfo<'a>, mint: &AccountInfo<'a>, token_program: &AccountInfo<'a>,
            infos: &[AccountInfo<'a>], bump: u8, data: &[u8]) -> ProgramResult {
    if data.len() < 100 { return Err(ProgramError::InvalidInstructionData); }
    let n = |o: usize| u64::from_le_bytes(data[o..o + 8].try_into().unwrap());
    let (repo_id, issue, amount, seq) = (n(0), n(8), n(16), u32::from_le_bytes(data[24..28].try_into().unwrap()));
    // ---- the integration ----
    let f = knos::FundOrder { repo_id, issue, amount, seq, wf_repo: data[28..60].try_into().unwrap(), wf_sha: data[60..100].try_into().unwrap(),
                              ..Default::default() };
    let ix = knos::fund_order_wallet(&knos::ID, treasury.key, treasury_token.key, mint.key, token_program.key, &f, &data[100..]);
    invoke_signed(&ix, infos, &[&[b"treasury", &[bump]]])?;
    let o = knos::Order::read(order.key, order.owner, &order.try_borrow_data()?, &knos::ID).ok_or(ProgramError::InvalidAccountData)?;
    // ---- what it now knows, from the order itself ----
    if o.amount != amount || o.refund_to != *treasury.key || o.rent_to != *treasury.key { return Err(ProgramError::InvalidAccountData); }
    msg!("cpi_fund: order {} for issue {} of repository {}: {} to the payees, {} fee, refundable after {}", order.key, issue, repo_id, o.amount, o.fee, o.deadline);
    Ok(())
}
