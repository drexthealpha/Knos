//! The two token programs this meter accepts (SPL Token and Token-2022), what it checks of a mint and of a token
//! account, and the only token instructions it ever sends: TransferChecked, InitializeAccount3 and GetAccountDataSize.
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
pub const MINT_LEN: usize = 82;
pub const ACCOUNT_LEN: usize = 165;
const MULTISIG_LEN: usize = 355; // Token-2022 never gives a mint or an account with extensions this length
/// Prices are in whole units of the mint. A mint needs two decimals to hold 0.02, and eighteen is the most that
/// keeps a fee inside 64 bits.
pub const MIN_DECIMALS: u8 = 2;
pub const MAX_DECIMALS: u8 = 18;

/// The Token-2022 mint extensions a mint of credits may carry. A list of what is allowed, not of what is refused:
/// a mint with any other extension is refused, among them a transfer fee, a default account state, a permanent
/// delegate, a transfer hook (even one that only names an authority: the authority can set a program later),
/// Pausable, and every id Token-2022 adds after this was written.
///   3 MintCloseAuthority   4 ConfidentialTransferMint   10 InterestBearingConfig   18 MetadataPointer   19 TokenMetadata
///   20 GroupPointer   21 TokenGroup   22 GroupMemberPointer   23 TokenGroupMember   25 ScaledUiAmount
/// None of these can stop, tax or take a transfer.
pub const EXTENSIONS: [u16; 10] = [3, 4, 10, 18, 19, 20, 21, 22, 23, 25];

pub struct Mint { pub decimals: u8, pub t22: bool }

/// The mint, checked: `token` is SPL Token or Token-2022 and owns it, and it is an initialised mint. With `opening`
/// (credits are being opened in this mint) its decimals are held to MIN_DECIMALS..=MAX_DECIMALS and a Token-2022
/// mint's extensions to the list above. Money leaving is never held to that: what was deposited can always be
/// withdrawn.
pub fn mint_of(mint: &AccountInfo, token: &AccountInfo, opening: bool) -> Result<Mint, ProgramError> {
    let t22 = *token.key == TOKEN_2022;
    if (!t22 && *token.key != TOKEN) || mint.owner != token.key { return Err(err(E_MINT)); }
    let d = mint.try_borrow_data()?;
    let extended = t22 && d.len() > ACCOUNT_LEN && d.len() != MULTISIG_LEN && d[ACCOUNT_LEN] == 1; // account type 1: a mint
    if !(d.len() == MINT_LEN || extended) || d[45] != 1 { return Err(err(E_MINT)); }
    if opening && (!(MIN_DECIMALS..=MAX_DECIMALS).contains(&d[44]) || (extended && !extensions_ok(&d[ACCOUNT_LEN + 1..]))) { return Err(err(E_MINT)); }
    Ok(Mint { decimals: d[44], t22 })
}

/// A Token-2022 mint's extensions are a list of (type u16, length u16, value), ended by type 0 or by the end of the
/// data. Every one must be on the list, and the list must parse to its end.
fn extensions_ok(mut t: &[u8]) -> bool {
    while t.len() >= 4 {
        let (ty, len) = (u16::from_le_bytes([t[0], t[1]]), u16::from_le_bytes([t[2], t[3]]) as usize);
        if ty == 0 { return true; } // uninitialised: the end of the list; what follows is padding
        if !EXTENSIONS.contains(&ty) || t.len() < 4 + len { return false; }
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

/// The size a token account of this mint needs: 165 bytes for SPL Token, what GetAccountDataSize says for Token-2022.
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

/// TransferChecked: `amount` of `mint` from a Credits token account to `to`, signed by ["auth"].
#[allow(clippy::too_many_arguments)]
pub fn transfer<'a>(token: &AccountInfo<'a>, from: &AccountInfo<'a>, mint: &AccountInfo<'a>, to: &AccountInfo<'a>, auth: &AccountInfo<'a>,
                    amount: u64, decimals: u8, auth_bump: u8) -> ProgramResult {
    let mut d = vec![12u8]; d.extend_from_slice(&amount.to_le_bytes()); d.push(decimals);
    let ix = Instruction { program_id: *token.key, data: d,
        accounts: vec![AccountMeta::new(*from.key, false), AccountMeta::new_readonly(*mint.key, false), AccountMeta::new(*to.key, false),
                       AccountMeta::new_readonly(*auth.key, true)] };
    invoke_signed(&ix, &[from.clone(), mint.clone(), to.clone(), auth.clone(), token.clone()], &[&[b"auth", &[auth_bump]]])
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

    #[test]
    fn only_the_listed_extensions_pass() {
        for ty in 1..=40u16 {
            assert_eq!(extensions_ok(&tlv(ty, &[5u8; 40])), EXTENSIONS.contains(&ty), "{ty}");
        }
        // what the list leaves out on purpose: a fee, a default state, non-transferable, a permanent delegate, a
        // hook that names only an authority, a confidential fee, Pausable, an id nobody has heard of
        for (ty, len) in [(1u16, 108usize), (6, 1), (9, 0), (12, 32), (14, 64), (16, 129), (26, 33), (999, 3), (u16::MAX - 2, 0)] {
            assert!(!extensions_ok(&tlv(ty, &vec![0u8; len])), "{ty}");
        }
        assert!(extensions_ok(&[]) && extensions_ok(&[tlv(3, &[5u8; 32]), tlv(18, &[5u8; 64]), tlv(19, &[5u8; 90])].concat()));
        // a refused one after accepted ones; a length that runs past the data
        assert!(!extensions_ok(&[tlv(3, &[5u8; 32]), tlv(18, &[5u8; 64]), tlv(14, &[0u8; 64])].concat()));
        assert!(!extensions_ok(&[3, 0, 200, 0, 1, 2, 3]));
        // what follows the uninitialised type 0 is padding, never read
        assert!(extensions_ok(&[tlv(3, &[5u8; 32]), vec![0, 0, 0, 0], tlv(9, &[])].concat()));
    }

    fn account<'a>(key: &'a Pubkey, owner: &'a Pubkey, lamports: &'a mut u64, data: &'a mut [u8]) -> AccountInfo<'a> {
        AccountInfo::new(key, false, false, lamports, data, owner, false, 0)
    }

    #[test]
    fn a_mint_of_credits_has_two_to_eighteen_decimals_and_only_listed_extensions() {
        let (k, mut l, mut none) = (Pubkey::new_unique(), 1u64, [0u8; 0]);
        let (mut l2, mut none2) = (1u64, [0u8; 0]);
        let classic = account(&TOKEN, &TOKEN, &mut l, &mut none);
        let t22 = account(&TOKEN_2022, &TOKEN_2022, &mut l2, &mut none2);
        let mint = |len: usize, kind: u8, decimals: u8| { let mut d = vec![0u8; len]; d[44] = decimals; d[45] = 1; if len > ACCOUNT_LEN { d[ACCOUNT_LEN] = kind; } d };
        let check = |owner: &Pubkey, mut d: Vec<u8>, token: &AccountInfo, opening: bool| {
            let mut lam = 1u64;
            mint_of(&account(&k, owner, &mut lam, &mut d), token, opening).map(|m| (m.decimals, m.t22)).ok()
        };
        assert_eq!(check(&TOKEN, mint(82, 0, 6), &classic, true), Some((6, false)));
        assert_eq!(check(&TOKEN_2022, mint(300, 1, 6), &t22, true), Some((6, true)));
        for (decimals, ok) in [(0u8, false), (1, false), (2, true), (9, true), (18, true), (19, false)] {
            assert_eq!(check(&TOKEN, mint(82, 0, decimals), &classic, true).is_some(), ok, "{decimals}");
            assert!(check(&TOKEN, mint(82, 0, decimals), &classic, false).is_some());      // leaving: never held to it
        }
        assert_eq!(check(&TOKEN, mint(82, 0, 6), &t22, true), None);
        assert_eq!(check(&TOKEN_2022, mint(300, 2, 6), &t22, true), None);
        assert_eq!(check(&TOKEN_2022, mint(355, 1, 6), &t22, true), None);
        assert_eq!(check(&TOKEN, vec![0u8; 82], &classic, true), None);
        assert_eq!(check(&k, mint(82, 0, 6), &classic, true), None);
        let mut bad = mint(166, 1, 6);
        bad.extend_from_slice(&tlv(26, &[0u8; 33]));
        assert_eq!(check(&TOKEN_2022, bad.clone(), &t22, true), None);
        assert_eq!(check(&TOKEN_2022, bad, &t22, false), Some((6, true)));
    }
}
