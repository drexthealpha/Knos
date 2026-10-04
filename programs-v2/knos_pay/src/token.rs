//! The two token programs this escrow accepts (SPL Token and Token-2022), what it checks of a mint and of a token
//! account, and the only token instructions it ever sends: TransferChecked, InitializeAccount3, GetAccountDataSize
//! CloseAccount (an order's own token account, once empty) and, for the devnet faucet, InitializeMint2 and MintTo. It
//! also asks the Associated Token Account program to create a payee's token account (PayOrder, SettleOrder).
use crate::{err, state::*, E_ACCOUNTS, E_MINT};
use solana_program::{
    account_info::AccountInfo,
    entrypoint::ProgramResult,
    instruction::{AccountMeta, Instruction},
    program::{get_return_data, invoke, invoke_signed},
    program_error::ProgramError,
    pubkey,
    pubkey::Pubkey,
};

pub const TOKEN: Pubkey = pubkey!("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA");
pub const TOKEN_2022: Pubkey = pubkey!("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb");
pub const ATA_PROGRAM: Pubkey = pubkey!("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL");
pub const MINT_LEN: usize = 82;
pub const ACCOUNT_LEN: usize = 165;
const MULTISIG_LEN: usize = 355; // Token-2022 never gives a mint or an account with extensions this length

pub struct Mint { pub decimals: u8, pub t22: bool }

/// The mint, checked: `token` is SPL Token or Token-2022 and owns it, and it is an initialised mint. With `funding`
/// (money is about to enter in this mint) a Token-2022 mint's extensions are walked too, see `extensions_ok`. Money
/// leaving is never held to that: what is in escrow must always be able to go out.
pub fn mint_of(mint: &AccountInfo, token: &AccountInfo, funding: bool) -> Result<Mint, ProgramError> {
    let t22 = *token.key == TOKEN_2022;
    if (!t22 && *token.key != TOKEN) || mint.owner != token.key { return Err(err(E_MINT)); }
    let d = mint.try_borrow_data()?;
    let extended = t22 && d.len() > ACCOUNT_LEN && d.len() != MULTISIG_LEN && d[ACCOUNT_LEN] == 1; // account type 1: a mint
    if !(d.len() == MINT_LEN || extended) || d[45] != 1 { return Err(err(E_MINT)); }
    if funding && extended && !extensions_ok(&d[ACCOUNT_LEN + 1..]) { return Err(err(E_MINT)); }
    Ok(Mint { decimals: d[44], t22 })
}

/// A Token-2022 mint's extensions are a list of (type u16, length u16, value). Money enters only in a mint whose
/// every extension is on ALLOWED: the ones that change nothing about who holds how much or whether a transfer goes
/// through. Every other is refused whatever it holds, also a transfer hook that names only an authority (the
/// authority can set a program later), a transfer fee of zero (it can be raised), a permanent delegate, a default
/// account state, Pausable, and every type this program has never heard of: an extension added to Token-2022 after
/// this was written is refused until someone has read what it does. A list that does not parse is refused.
///   3 MintCloseAuthority (a mint closes only at supply zero)   4 ConfidentialTransferMint   10 InterestBearingConfig
///   and 25 ScaledUiAmount (how an amount is displayed)          18 MetadataPointer  19 TokenMetadata  20 GroupPointer
///   21 TokenGroup  22 GroupMemberPointer  23 TokenGroupMember
pub const ALLOWED: [u16; 10] = [3, 4, 10, 18, 19, 20, 21, 22, 23, 25];
fn extensions_ok(mut t: &[u8]) -> bool {
    while t.len() >= 4 {
        let (ty, len) = (u16::from_le_bytes([t[0], t[1]]), u16::from_le_bytes([t[2], t[3]]) as usize);
        if ty == 0 { break; } // uninitialised: the end of the list
        if !ALLOWED.contains(&ty) || t.len() < 4 + len { return false; }
        t = &t[4 + len..];
    }
    true
}

/// (mint, owner, amount) of an initialised token account of the program `token`; None for anything else.
pub fn token_account(a: &AccountInfo, token: &Pubkey) -> Option<(Pubkey, Pubkey, u64)> {
    if a.owner != token { return None; }
    let d = a.try_borrow_data().ok()?;
    let extended = *token == TOKEN_2022 && d.len() > ACCOUNT_LEN && d.len() != MULTISIG_LEN && d[ACCOUNT_LEN] == 2; // account type 2
    if !(d.len() == ACCOUNT_LEN || extended) || d[108] == 0 { return None; }
    Some((key_at(&d, 0), key_at(&d, 32), u64_at(&d, 64)))
}
/// What a token account holds; `bad` when it is not a token account of `token`.
pub fn amount_of(a: &AccountInfo, token: &Pubkey, bad: u32) -> Result<u64, ProgramError> {
    token_account(a, token).map(|t| t.2).ok_or_else(|| err(bad))
}
/// Whether `a` is a token account of `mint` that belongs to `owner`.
pub fn is_owned(a: &AccountInfo, token: &Pubkey, mint: &Pubkey, owner: &Pubkey) -> bool {
    matches!(token_account(a, token), Some((m, o, _)) if m == *mint && o == *owner)
}

/// The size a token account of this mint needs: 165 bytes for SPL Token, what GetAccountDataSize says for Token-2022
/// (a mint's extensions can require account extensions).
fn account_size<'a>(mint: &AccountInfo<'a>, token: &AccountInfo<'a>, m: &Mint) -> Result<usize, ProgramError> {
    if !m.t22 { return Ok(ACCOUNT_LEN); }
    let ix = Instruction { program_id: *token.key, data: vec![21], accounts: vec![AccountMeta::new_readonly(*mint.key, false)] };
    invoke(&ix, &[mint.clone(), token.clone()])?;
    match get_return_data() {
        Some((by, size)) if by == *token.key && size.len() == 8 => Ok(u64::from_le_bytes(size.try_into().unwrap()) as usize),
        _ => Err(err(E_MINT)),
    }
}

/// The token account at a PDA of this program (`seeds`, bump included; the caller has checked `acct` is that
/// address): of `mint`, owned by ["auth"]. Created on first use (rent from `payer`), then checked to be exactly that.
#[allow(clippy::too_many_arguments)]
pub fn ensure_token_pda<'a>(payer: &AccountInfo<'a>, acct: &AccountInfo<'a>, mint: &AccountInfo<'a>, auth: &AccountInfo<'a>, token: &AccountInfo<'a>,
                            sys: &AccountInfo<'a>, m: &Mint, seeds: &[&[u8]]) -> ProgramResult {
    if acct.data_is_empty() {
        create_pda(payer, acct, sys, token.key, account_size(mint, token, m)?, seeds)?;
        let mut d = vec![18u8]; d.extend_from_slice(auth.key.as_ref()); // InitializeAccount3: the owner is in the data
        invoke(&Instruction { program_id: *token.key, data: d, accounts: vec![AccountMeta::new(*acct.key, false), AccountMeta::new_readonly(*mint.key, false)] },
               &[acct.clone(), mint.clone(), token.clone()])?;
    }
    if !is_owned(acct, token.key, mint.key, auth.key) { return Err(err(E_ACCOUNTS)); }
    Ok(())
}

/// TransferChecked: `amount` of `mint` from `from` to `to`. With `auth_bump` the ["auth"] PDA signs (money leaving a
/// vault or a Balance); without it `authority` signed the transaction itself (a wallet funding a job).
#[allow(clippy::too_many_arguments)]
pub fn transfer<'a>(token: &AccountInfo<'a>, from: &AccountInfo<'a>, mint: &AccountInfo<'a>, to: &AccountInfo<'a>, authority: &AccountInfo<'a>,
                    amount: u64, decimals: u8, auth_bump: Option<u8>) -> ProgramResult {
    let mut d = vec![12u8]; d.extend_from_slice(&amount.to_le_bytes()); d.push(decimals);
    let ix = Instruction { program_id: *token.key, data: d,
        accounts: vec![AccountMeta::new(*from.key, false), AccountMeta::new_readonly(*mint.key, false), AccountMeta::new(*to.key, false),
                       AccountMeta::new_readonly(*authority.key, true)] };
    let infos = [from.clone(), mint.clone(), to.clone(), authority.clone(), token.clone()];
    match auth_bump { Some(b) => invoke_signed(&ix, &infos, &[&[b"auth", &[b]]]), None => invoke(&ix, &infos) }
}

/// CloseAccount: an empty token account of ["auth"] is closed, its rent to `to`.
pub fn close_token<'a>(token: &AccountInfo<'a>, acct: &AccountInfo<'a>, to: &AccountInfo<'a>, auth: &AccountInfo<'a>, auth_bump: u8) -> ProgramResult {
    invoke_signed(&Instruction { program_id: *token.key, data: vec![9],
        accounts: vec![AccountMeta::new(*acct.key, false), AccountMeta::new(*to.key, false), AccountMeta::new_readonly(*auth.key, true)] },
        &[acct.clone(), to.clone(), auth.clone(), token.clone()], &[&[b"auth", &[auth_bump]]])
}

/// Creates `wallet`'s associated token account of `mint` at `ata` (the Associated Token Account program refuses any
/// other address), its rent from `payer`, who signed the transaction.
#[allow(clippy::too_many_arguments)]
pub fn create_ata<'a>(ata_program: &AccountInfo<'a>, payer: &AccountInfo<'a>, ata: &AccountInfo<'a>, wallet: &AccountInfo<'a>, mint: &AccountInfo<'a>,
                      sys: &AccountInfo<'a>, token: &AccountInfo<'a>) -> ProgramResult {
    if *ata_program.key != ATA_PROGRAM { return Err(err(E_ACCOUNTS)); }
    invoke(&Instruction { program_id: ATA_PROGRAM, data: vec![0],
        accounts: vec![AccountMeta::new(*payer.key, true), AccountMeta::new(*ata.key, false), AccountMeta::new_readonly(*wallet.key, false),
                       AccountMeta::new_readonly(*mint.key, false), AccountMeta::new_readonly(*sys.key, false), AccountMeta::new_readonly(*token.key, false)] },
        &[payer.clone(), ata.clone(), wallet.clone(), mint.clone(), sys.clone(), token.clone(), ata_program.clone()])
}

/// Devnet faucet: creates the test-USDC mint ["mint"] (SPL Token, 6 decimals, mint authority ["auth"], no freeze authority).
pub fn init_mint<'a>(payer: &AccountInfo<'a>, mint: &AccountInfo<'a>, auth: &AccountInfo<'a>, token: &AccountInfo<'a>, sys: &AccountInfo<'a>,
                     bump: u8) -> ProgramResult {
    create_pda(payer, mint, sys, &TOKEN, MINT_LEN, &[b"mint", &[bump]])?;
    let mut d = vec![20u8, 6]; d.extend_from_slice(auth.key.as_ref()); d.push(0); // InitializeMint2
    invoke(&Instruction { program_id: TOKEN, data: d, accounts: vec![AccountMeta::new(*mint.key, false)] }, &[mint.clone(), token.clone()])
}
/// Devnet faucet: MintTo, signed by ["auth"].
pub fn mint_to<'a>(token: &AccountInfo<'a>, mint: &AccountInfo<'a>, to: &AccountInfo<'a>, auth: &AccountInfo<'a>, amount: u64, auth_bump: u8) -> ProgramResult {
    let mut d = vec![7u8]; d.extend_from_slice(&amount.to_le_bytes());
    invoke_signed(&Instruction { program_id: TOKEN, data: d,
        accounts: vec![AccountMeta::new(*mint.key, false), AccountMeta::new(*to.key, false), AccountMeta::new_readonly(*auth.key, true)] },
        &[mint.clone(), to.clone(), auth.clone(), token.clone()], &[&[b"auth", &[auth_bump]]])
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tlv(ty: u16, value: &[u8]) -> Vec<u8> {
        let mut out = ty.to_le_bytes().to_vec();
        out.extend_from_slice(&(value.len() as u16).to_le_bytes());
        out.extend_from_slice(value);
        out
    }
    /// A TransferFeeConfig value: two authorities, the withheld amount, then the older and the newer fee.
    fn fee_config(older: (u64, u16), newer: (u64, u16)) -> Vec<u8> {
        let mut v = vec![7u8; 72];
        for (max, bps) in [older, newer] {
            v.extend_from_slice(&500u64.to_le_bytes());
            v.extend_from_slice(&max.to_le_bytes());
            v.extend_from_slice(&bps.to_le_bytes());
        }
        v
    }

    #[test]
    fn only_the_listed_extensions_are_accepted() {
        let hook = |program: u8| { let mut v = vec![9u8; 32]; v.extend_from_slice(&[program; 32]); v };
        let ok: Vec<Vec<u8>> = vec![
            vec![],
            tlv(3, &[5u8; 32]),                                     // MintCloseAuthority
            tlv(4, &[5u8; 65]),                                     // ConfidentialTransferMint
            tlv(10, &[5u8; 52]), tlv(25, &[5u8; 56]),               // how an amount is displayed
            [tlv(18, &[5u8; 64]), tlv(19, &[5u8; 90]), tlv(20, &[5u8; 64]), tlv(21, &[5u8; 80]), tlv(22, &[5u8; 64]), tlv(23, &[5u8; 72]), vec![0u8; 12]].concat(),
        ];
        for t in &ok { assert!(extensions_ok(t), "{t:?}"); }
        let mut refused: Vec<Vec<u8>> = vec![
            tlv(9, &[]),                                            // NonTransferable
            tlv(6, &[1]), tlv(6, &[2]),                             // a default account state, whatever it is today
            tlv(14, &hook(1)),                                      // a transfer hook program
            tlv(14, &hook(0)),                                      // a transfer hook that names only an authority
            tlv(1, &fee_config((0, 0), (0, 0))),                    // a transfer fee of nothing: its authority can raise it
            tlv(1, &fee_config((1, 1), (0, 0))),
            tlv(12, &[5u8; 32]),                                    // PermanentDelegate
            tlv(16, &[0u8; 129]),                                   // ConfidentialTransferFeeConfig
            tlv(26, &[5u8; 33]),                                    // Pausable
            tlv(24, &[5u8; 97]), tlv(28, &[5u8; 32]),
            tlv(29, &[1, 2, 3]), tlv(999, &[1, 2, 3]),              // ids this program has never heard of
            vec![3, 0, 200, 0, 1, 2, 3],                            // a length that runs past the data
            [tlv(3, &[5u8; 32]), tlv(4, &[5u8; 65]), tlv(26, &[5u8; 33])].concat(),   // a refused one after accepted ones
        ];
        for ty in (1..=64u16).filter(|t| !ALLOWED.contains(t)) { refused.push(tlv(ty, &[0u8; 8])); }
        for t in &refused { assert!(!extensions_ok(t), "{t:?}"); }
        // what follows the uninitialised type 0 is padding, never read
        assert!(extensions_ok(&[tlv(3, &[5u8; 32]), vec![0, 0, 0, 0], tlv(9, &[])].concat()));
    }

    fn account<'a>(key: &'a Pubkey, owner: &'a Pubkey, lamports: &'a mut u64, data: &'a mut [u8]) -> AccountInfo<'a> {
        AccountInfo::new(key, false, false, lamports, data, owner, false, 0)
    }

    #[test]
    fn a_mint_is_an_initialised_mint_of_the_token_program_passed() {
        let (k, mut l, mut none) = (Pubkey::new_unique(), 1u64, [0u8; 0]);
        let (mut l2, mut none2) = (1u64, [0u8; 0]);
        let classic = account(&TOKEN, &TOKEN, &mut l, &mut none);
        let t22 = account(&TOKEN_2022, &TOKEN_2022, &mut l2, &mut none2);
        let mint = |len: usize, kind: u8| { let mut d = vec![0u8; len]; d[44] = 6; d[45] = 1; if len > ACCOUNT_LEN { d[ACCOUNT_LEN] = kind; } d };
        let check = |owner: &Pubkey, mut d: Vec<u8>, token: &AccountInfo, funding: bool| {
            let mut lam = 1u64;
            mint_of(&account(&k, owner, &mut lam, &mut d), token, funding).map(|m| (m.decimals, m.t22)).ok()
        };
        assert_eq!(check(&TOKEN, mint(82, 0), &classic, true), Some((6, false)));
        assert_eq!(check(&TOKEN_2022, mint(82, 0), &t22, true), Some((6, true)));
        assert_eq!(check(&TOKEN_2022, mint(300, 1), &t22, true), Some((6, true)));
        // the other program; a token account (type 2) or a multisig-sized account; an SPL Token account that is too long; not initialised
        assert_eq!(check(&TOKEN, mint(82, 0), &t22, true), None);
        assert_eq!(check(&TOKEN_2022, mint(82, 0), &classic, true), None);
        assert_eq!(check(&TOKEN_2022, mint(300, 2), &t22, true), None);
        assert_eq!(check(&TOKEN_2022, mint(355, 1), &t22, true), None);
        assert_eq!(check(&TOKEN_2022, mint(165, 0), &t22, true), None);
        assert_eq!(check(&TOKEN, mint(300, 1), &classic, true), None);
        assert_eq!(check(&TOKEN, vec![0u8; 82], &classic, true), None);
        assert_eq!(check(&k, mint(82, 0), &classic, true), None);
        // extensions are walked only when money is about to enter
        let mut bad = mint(166, 1);
        bad.extend_from_slice(&tlv(9, &[]));
        assert_eq!(check(&TOKEN_2022, bad.clone(), &t22, true), None);
        assert_eq!(check(&TOKEN_2022, bad, &t22, false), Some((6, true)));
    }

    #[test]
    fn a_token_account_is_read_only_from_its_own_program() {
        let (k, mint, owner) = (Pubkey::new_unique(), Pubkey::new_unique(), Pubkey::new_unique());
        let tok = |len: usize, state: u8, kind: u8| {
            let mut d = vec![0u8; len];
            d[0..32].copy_from_slice(mint.as_ref()); d[32..64].copy_from_slice(owner.as_ref()); d[64..72].copy_from_slice(&77u64.to_le_bytes());
            d[108] = state; if len > ACCOUNT_LEN { d[ACCOUNT_LEN] = kind; }
            d
        };
        let read = |program: &Pubkey, mut d: Vec<u8>, token: &Pubkey| { let mut lam = 1u64; token_account(&account(&k, program, &mut lam, &mut d), token) };
        assert_eq!(read(&TOKEN, tok(165, 1, 0), &TOKEN), Some((mint, owner, 77)));
        assert_eq!(read(&TOKEN_2022, tok(165, 2, 0), &TOKEN_2022), Some((mint, owner, 77)));      // frozen is still an account
        assert_eq!(read(&TOKEN_2022, tok(182, 1, 2), &TOKEN_2022), Some((mint, owner, 77)));
        assert_eq!(read(&TOKEN, tok(165, 1, 0), &TOKEN_2022), None);
        assert_eq!(read(&TOKEN, tok(165, 0, 0), &TOKEN), None);                                    // not initialised
        assert_eq!(read(&TOKEN, tok(182, 1, 2), &TOKEN), None);                                    // SPL Token accounts are 165 bytes
        assert_eq!(read(&TOKEN_2022, tok(182, 1, 1), &TOKEN_2022), None);                          // a mint
        assert_eq!(read(&TOKEN_2022, tok(355, 1, 2), &TOKEN_2022), None);
        assert_eq!(read(&TOKEN, vec![0u8; 82], &TOKEN), None);
        let mut lam = 1u64;
        let mut d = tok(165, 1, 0);
        let a = account(&k, &TOKEN, &mut lam, &mut d);
        assert!(is_owned(&a, &TOKEN, &mint, &owner) && !is_owned(&a, &TOKEN, &owner, &owner) && !is_owned(&a, &TOKEN, &mint, &mint));
    }
}
