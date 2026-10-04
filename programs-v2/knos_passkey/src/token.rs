//! The two token programs a wallet can be paid in (SPL Token and Token-2022), what is checked of a mint and of a
//! token account, and the one token instruction this program ever sends: TransferChecked, signed by the wallet.
use crate::{err, E_MINT};
use solana_program::{
    account_info::AccountInfo,
    entrypoint::ProgramResult,
    instruction::{AccountMeta, Instruction},
    program::invoke_signed,
    program_error::ProgramError,
    pubkey,
    pubkey::Pubkey,
};

pub const TOKEN: Pubkey = pubkey!("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA");
pub const TOKEN_2022: Pubkey = pubkey!("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb");
pub const MINT_LEN: usize = 82;
pub const ACCOUNT_LEN: usize = 165;
const MULTISIG_LEN: usize = 355; // Token-2022 never gives a mint or an account with extensions this length

/// The Token-2022 mint extensions a withdrawal accepts; a mint with any other is refused, also one added to
/// Token-2022 after this was written. None of these can take from, block or redirect a transfer:
/// 3 MintCloseAuthority, 4 ConfidentialTransferMint, 10 InterestBearingConfig, 18 MetadataPointer, 19 TokenMetadata,
/// 20 GroupPointer, 21 TokenGroup, 22 GroupMemberPointer, 23 TokenGroupMember, 24 ConfidentialMintBurn,
/// 25 ScaledUiAmount. Not on it, among others: 1 TransferFeeConfig, 6 DefaultAccountState, 9 NonTransferable,
/// 12 PermanentDelegate, 14 TransferHook (also one that only names an authority), 16 ConfidentialTransferFeeConfig,
/// 26 Pausable.
pub const ALLOWED: [u16; 11] = [3, 4, 10, 18, 19, 20, 21, 22, 23, 24, 25];

/// The mint's decimals, once checked: `token` is SPL Token or Token-2022 and owns it, it is an initialised mint, and
/// a Token-2022 mint carries no extension outside ALLOWED.
pub fn mint_of(mint: &AccountInfo, token: &AccountInfo) -> Result<u8, ProgramError> {
    let t22 = *token.key == TOKEN_2022;
    if (!t22 && *token.key != TOKEN) || mint.owner != token.key { return Err(err(E_MINT)); }
    let d = mint.try_borrow_data()?;
    let extended = t22 && d.len() > ACCOUNT_LEN && d.len() != MULTISIG_LEN && d[ACCOUNT_LEN] == 1; // account type 1: a mint
    if !(d.len() == MINT_LEN || extended) || d[45] != 1 { return Err(err(E_MINT)); }
    if extended && !extensions_ok(&d[ACCOUNT_LEN + 1..]) { return Err(err(E_MINT)); }
    Ok(d[44])
}

/// A Token-2022 mint's extensions are a list of (type u16, length u16, value); type 0 ends it.
fn extensions_ok(mut t: &[u8]) -> bool {
    while t.len() >= 4 {
        let (ty, len) = (u16::from_le_bytes([t[0], t[1]]), u16::from_le_bytes([t[2], t[3]]) as usize);
        if ty == 0 { break; }
        if !ALLOWED.contains(&ty) || t.len() < 4 + len { return false; }
        t = &t[4 + len..];
    }
    true
}

/// (mint, owner) of an initialised token account of the program `token`; None for anything else.
pub fn token_account(a: &AccountInfo, token: &Pubkey) -> Option<(Pubkey, Pubkey)> {
    if a.owner != token { return None; }
    let d = a.try_borrow_data().ok()?;
    let extended = *token == TOKEN_2022 && d.len() > ACCOUNT_LEN && d.len() != MULTISIG_LEN && d[ACCOUNT_LEN] == 2; // account type 2
    if !(d.len() == ACCOUNT_LEN || extended) || d[108] == 0 { return None; }
    let key = |o: usize| Pubkey::new_from_array(d[o..o + 32].try_into().unwrap());
    Some((key(0), key(32)))
}

/// TransferChecked: `amount` of `mint` from `from` to `to`, signed by the wallet PDA with `seeds`.
#[allow(clippy::too_many_arguments)]
pub fn transfer<'a>(token: &AccountInfo<'a>, from: &AccountInfo<'a>, mint: &AccountInfo<'a>, to: &AccountInfo<'a>, wallet: &AccountInfo<'a>,
                    amount: u64, decimals: u8, seeds: &[&[u8]]) -> ProgramResult {
    let mut d = vec![12u8]; d.extend_from_slice(&amount.to_le_bytes()); d.push(decimals);
    let ix = Instruction { program_id: *token.key, data: d,
        accounts: vec![AccountMeta::new(*from.key, false), AccountMeta::new_readonly(*mint.key, false), AccountMeta::new(*to.key, false),
                       AccountMeta::new_readonly(*wallet.key, true)] };
    invoke_signed(&ix, &[from.clone(), mint.clone(), to.clone(), wallet.clone(), token.clone()], &[seeds])
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
    fn a_mint_with_any_extension_off_the_list_is_refused() {
        for ty in ALLOWED { assert!(extensions_ok(&tlv(ty, &[5; 40])), "{ty}"); }
        assert!(extensions_ok(&[]) && extensions_ok(&[tlv(18, &[1; 64]), tlv(19, &[2; 90]), tlv(3, &[3; 32]), vec![0; 9]].concat()));
        // every other id: the ones that take, freeze or block, the account-only ones, and ids not assigned yet
        for ty in (1..=40u16).chain([999, u16::MAX - 2, u16::MAX]).filter(|t| !ALLOWED.contains(t)) {
            assert!(!extensions_ok(&tlv(ty, &[0; 64])), "{ty}");
            assert!(!extensions_ok(&[tlv(18, &[1; 64]), tlv(ty, &[]), tlv(19, &[2; 8])].concat()), "{ty} after an allowed one");
        }
        // a transfer hook that only names an authority and has no program; a transfer fee of nothing; a pause that is off
        let mut hook = vec![9u8; 32]; hook.extend_from_slice(&[0; 32]);
        assert!(!extensions_ok(&tlv(14, &hook)) && !extensions_ok(&tlv(1, &[0; 108])) && !extensions_ok(&tlv(26, &[0; 33])));
        // a length that runs past the data; what follows the end marker is padding, never read
        assert!(!extensions_ok(&[18, 0, 200, 0, 1, 2, 3]));
        assert!(extensions_ok(&[tlv(18, &[1; 64]), vec![0, 0, 0, 0], tlv(14, &hook)].concat()));
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
        let check = |owner: &Pubkey, mut d: Vec<u8>, token: &AccountInfo| { let mut lam = 1u64; mint_of(&account(&k, owner, &mut lam, &mut d), token).ok() };
        assert_eq!(check(&TOKEN, mint(82, 0), &classic), Some(6));
        assert_eq!(check(&TOKEN_2022, mint(82, 0), &t22), Some(6));
        assert_eq!(check(&TOKEN_2022, mint(300, 1), &t22), Some(6));
        // the other program; a token account (type 2) or a multisig-sized account; an SPL Token account that is too long; not initialised
        assert_eq!(check(&TOKEN, mint(82, 0), &t22), None);
        assert_eq!(check(&TOKEN_2022, mint(82, 0), &classic), None);
        assert_eq!(check(&TOKEN_2022, mint(300, 2), &t22), None);
        assert_eq!(check(&TOKEN_2022, mint(355, 1), &t22), None);
        assert_eq!(check(&TOKEN, mint(300, 1), &classic), None);
        assert_eq!(check(&TOKEN, vec![0u8; 82], &classic), None);
        assert_eq!(check(&k, mint(82, 0), &classic), None);
        let mut bad = mint(166, 1);
        bad.extend_from_slice(&tlv(12, &[7; 32]));
        assert_eq!(check(&TOKEN_2022, bad, &t22), None);
    }

    #[test]
    fn a_token_account_is_read_only_from_its_own_program() {
        let (k, mint, owner) = (Pubkey::new_unique(), Pubkey::new_unique(), Pubkey::new_unique());
        let tok = |len: usize, state: u8, kind: u8| {
            let mut d = vec![0u8; len];
            d[0..32].copy_from_slice(mint.as_ref()); d[32..64].copy_from_slice(owner.as_ref());
            d[108] = state; if len > ACCOUNT_LEN { d[ACCOUNT_LEN] = kind; }
            d
        };
        let read = |program: &Pubkey, mut d: Vec<u8>, token: &Pubkey| { let mut lam = 1u64; token_account(&account(&k, program, &mut lam, &mut d), token) };
        assert_eq!(read(&TOKEN, tok(165, 1, 0), &TOKEN), Some((mint, owner)));
        assert_eq!(read(&TOKEN_2022, tok(182, 1, 2), &TOKEN_2022), Some((mint, owner)));
        assert_eq!(read(&TOKEN, tok(165, 1, 0), &TOKEN_2022), None);
        assert_eq!(read(&TOKEN, tok(165, 0, 0), &TOKEN), None);          // not initialised
        assert_eq!(read(&TOKEN, tok(182, 1, 2), &TOKEN), None);          // SPL Token accounts are 165 bytes
        assert_eq!(read(&TOKEN_2022, tok(182, 1, 1), &TOKEN_2022), None); // a mint
        assert_eq!(read(&TOKEN_2022, tok(355, 1, 2), &TOKEN_2022), None);
    }
}
