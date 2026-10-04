//! knos-passkey: a wallet from a passkey. A person with no wallet app and no seed phrase creates a WebAuthn passkey
//! (a P-256 key that never leaves the device or its keychain); the wallet is this program's account at the address
//! that key derives, and it can be paid before it exists on chain, like any address. Money leaves it only on an
//! assertion of that passkey that names the mint, the destination, the amount and a number used once. This program
//! is upgradeable only through a multisig with a public 48-hour delay, until an outside review. No key of Knos's is
//! named in it: nothing here pays, pauses, or chooses a destination but the passkey's own signature.
//!
//! HOW A SIGNATURE IS CHECKED. This program does no elliptic-curve arithmetic. Solana's secp256r1 precompile
//! (SIMD-0075, program Secp256r1SigVerify1111111111111111111111111) verifies P-256 signatures as an instruction of
//! its own, and a transaction in which it fails does not run. (It answers on mainnet-beta and on devnet: simulated
//! on both on 2026-10-03, a good signature passed and one with a high s failed with the precompile's error 2. Layout:
//! https://github.com/solana-foundation/solana-improvement-documents/blob/main/proposals/0075-precompile-for-secp256r1-sigverify.md)
//! Withdraw requires that the instruction right before it
//! in the same transaction is that precompile, with exactly one signature whose key, signature and message are in
//! that instruction's own data (webauthn.rs), and reads from it WHAT was verified:
//!   the key      must be this wallet's key;
//!   the message  must be authenticatorData || sha256(clientDataJSON), as WebAuthn signs: the clientDataJSON is in
//!                Withdraw's data and is hashed here; authenticatorData's flags must have "user present" set;
//!   the client data's `type` must be "webauthn.get" and its `challenge` the unpadded base64url of
//!                sha256("knos-passkey" || wallet || mint || to || amount u64 LE || nonce u64 LE)
//!                for the accounts and the data of this very Withdraw.
//! The signature's s must be in the lower half of the curve order (the precompile enforces it; it is checked again
//! here), so an assertion has one valid encoding. The nonce must be the wallet's nonce plus one and becomes the
//! wallet's nonce, so an assertion moves money once and assertions are spent in order. The relying party (the site
//! the passkey belongs to) is not pinned: an authenticator signs for a passkey only on that site, and the challenge
//! names this program's wallet, so an assertion made for anything else never has this challenge.
//!
//! WHERE MONEY CAN GO. Tokens leave a token account owned by a wallet only by Withdraw's one TransferChecked (the
//! mint is named, its decimals checked), to the token account the passkey signed for, in the amount it signed for.
//! Nothing is created by Withdraw and no lamports leave the wallet: whoever sends the transaction pays its fee and
//! the rent of anything it creates in other instructions (the destination's token account, say), so a relay can
//! carry it. A wallet's lamports beyond its rent stay where they are: no instruction moves them.
//!
//! ACCOUNTS.
//!   Wallet  ["pk", sha256(key)]   key: the passkey's public key, SEC1 compressed (33 bytes). 48 bytes:
//!                                 version u8 (1), bump u8, key [u8; 33], padding [u8; 5], nonce u64.
//! The wallet's money is in ordinary token accounts whose owner is the wallet's address: its associated token
//! account for a mint is where anyone pays it. They are created by whoever pays the wallet, never by this program.
//!
//! INSTRUCTIONS. The first byte of the data is the tag; integers are little-endian; (s) signs, (w) is writable.
//!   0 Open      payer(s,w) wallet(w) system
//!               data: key [u8; 33]
//!               Anyone, for any key (its first byte must be 2 or 3). Creates the wallet with nonce 0; the payer pays
//!               its rent. A wallet that is open already is left as it is. Needed once, before the first Withdraw.
//!   1 Withdraw  wallet(w) from(w) mint to(w) token_program instructions
//!               data: amount u64, nonce u64, clientDataJSON bytes
//!               Nobody signs the instruction: anyone may send it, and the passkey's assertion is the authority. The
//!               instruction before this one is the precompile and verified what the header says. `from` is a token
//!               account of `mint` owned by the wallet; `to` is another token account (the token program requires
//!               it to be of the same mint); `token_program` is SPL Token or Token-2022 and owns `mint`; a
//!               Token-2022 mint carries no extension outside token.rs's ALLOWED; `instructions` is the instructions
//!               sysvar. Money: amount, from -> to.
//!
//! MINT RULES (token.rs). A Token-2022 mint with any extension off the list is refused, so a withdrawal cannot be
//! taxed, hooked or redirected by the mint. Tokens of such a mint that someone sends to a wallet stay there until an
//! upgrade of this program widens the list.
//!
//! LOGS, one line each (addresses in base58, numbers in decimal):
//!   knosp:opened wallet=                               knosp:withdrawn wallet= mint= to= amount= nonce=
pub mod token;
pub mod webauthn;

use solana_program::{
    account_info::AccountInfo,
    entrypoint::ProgramResult,
    hash::hashv,
    msg,
    program::{invoke, invoke_signed},
    program_error::ProgramError,
    pubkey,
    pubkey::Pubkey,
    rent::Rent,
    system_instruction, system_program,
    sysvar::{instructions, Sysvar},
};

/// Solana's secp256r1 signature verification precompile (SIMD-0075).
pub const SECP256R1_ID: Pubkey = pubkey!("Secp256r1SigVerify1111111111111111111111111");
/// What every challenge starts with, so that no other use of the passkey signs one.
pub const DOMAIN: &[u8] = b"knos-passkey";
pub const CLIENT_TYPE: &[u8] = b"webauthn.get";

pub const W_VERSION: usize = 0; // 1
pub const W_BUMP: usize = 1;
pub const W_KEY: usize = 2;     // the passkey's public key, SEC1 compressed
pub const W_NONCE: usize = 40;  // the nonce of the last withdrawal; the next one must carry this plus one
pub const WALLET_LEN: usize = 48;

pub const E_ACCOUNTS: u32 = 110;    // a wrong account, or a missing signature
pub const E_KEY: u32 = 111;         // not a compressed P-256 public key
pub const E_WALLET: u32 = 112;      // not a wallet of this program
pub const E_PRECOMPILE: u32 = 113;  // the instruction before this one is not one secp256r1 verification of its own data
pub const E_SIGNER: u32 = 114;      // the signature verified is another key's, not this wallet's
pub const E_MESSAGE: u32 = 115;     // what was signed is not authenticatorData || sha256(this clientDataJSON)
pub const E_PRESENT: u32 = 116;     // the authenticator did not report that a person was present
pub const E_CLIENT_DATA: u32 = 117; // the client data is not that of a "webauthn.get" with a challenge
pub const E_CHALLENGE: u32 = 118;   // the challenge is not the one for this wallet, mint, destination, amount and nonce
pub const E_NONCE: u32 = 119;       // the nonce is not the wallet's nonce plus one
pub const E_MINT: u32 = 120;        // the mint or the token program is not accepted
pub const E_HIGH_S: u32 = 121;      // the signature's s is in the upper half of the curve order
pub const E_FROM: u32 = 122;        // `from` is not a token account of this mint owned by the wallet, or is the destination

pub fn err(code: u32) -> ProgramError { ProgramError::Custom(code) }

#[cfg(not(feature = "no-entrypoint"))]
solana_program::entrypoint!(process);

#[cfg(not(feature = "no-entrypoint"))]
solana_security_txt::security_txt! {
    name: "knos-passkey",
    project_url: "https://github.com/drexthealpha/Knos",
    contacts: "link:https://github.com/drexthealpha/Knos/security/advisories/new",
    policy: "https://github.com/drexthealpha/Knos/blob/main/SECURITY.md",
    source_code: "https://github.com/drexthealpha/Knos"
}

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let (&tag, rest) = data.split_first().ok_or(ProgramError::InvalidInstructionData)?;
    match tag {
        0 => open(program_id, accounts, rest),
        1 => withdraw(program_id, accounts, rest),
        _ => Err(ProgramError::InvalidInstructionData),
    }
}

/// ["pk", sha256(key)]: the wallet of a passkey.
pub fn wallet_of(program_id: &Pubkey, key: &[u8]) -> (Pubkey, u8) {
    Pubkey::find_program_address(&[b"pk", hashv(&[key]).as_ref()], program_id)
}

/// What the passkey signs to withdraw: sha256("knos-passkey" || wallet || mint || to || amount LE || nonce LE).
pub fn challenge(wallet: &Pubkey, mint: &Pubkey, to: &Pubkey, amount: u64, nonce: u64) -> [u8; 32] {
    hashv(&[DOMAIN, wallet.as_ref(), mint.as_ref(), to.as_ref(), &amount.to_le_bytes(), &nonce.to_le_bytes()]).to_bytes()
}

fn open(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let [payer, wallet, sys] = accounts else { return Err(err(E_ACCOUNTS)) };
    if !payer.is_signer || *sys.key != system_program::ID { return Err(err(E_ACCOUNTS)); }
    if data.len() != webauthn::KEY_LEN || !matches!(data[0], 2 | 3) { return Err(err(E_KEY)); }
    let seed = hashv(&[data]);
    let (at, bump) = Pubkey::find_program_address(&[b"pk", seed.as_ref()], program_id);
    if *wallet.key != at { return Err(err(E_ACCOUNTS)); }
    if wallet.owner == program_id { return Ok(()); } // open already: only this instruction creates one, with this key
    if !wallet.data_is_empty() || *wallet.owner != system_program::ID { return Err(err(E_WALLET)); }
    // an address can be sent lamports before it exists: top up, allocate and assign instead of create_account
    let (need, have) = (Rent::get()?.minimum_balance(WALLET_LEN), wallet.lamports());
    if have < need { invoke(&system_instruction::transfer(payer.key, wallet.key, need - have), &[payer.clone(), wallet.clone(), sys.clone()])?; }
    let seeds: &[&[u8]] = &[b"pk", seed.as_ref(), &[bump]];
    invoke_signed(&system_instruction::allocate(wallet.key, WALLET_LEN as u64), &[wallet.clone(), sys.clone()], &[seeds])?;
    invoke_signed(&system_instruction::assign(wallet.key, program_id), &[wallet.clone(), sys.clone()], &[seeds])?;
    let mut d = wallet.try_borrow_mut_data()?;
    d[W_VERSION] = 1;
    d[W_BUMP] = bump;
    d[W_KEY..W_KEY + webauthn::KEY_LEN].copy_from_slice(data);
    msg!("knosp:opened wallet={}", wallet.key);
    Ok(())
}

fn withdraw(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let [wallet, from, mint, to, token_program, ixs] = accounts else { return Err(err(E_ACCOUNTS)) };
    if data.len() < 16 { return Err(ProgramError::InvalidInstructionData); }
    let amount = u64::from_le_bytes(data[0..8].try_into().unwrap());
    let nonce = u64::from_le_bytes(data[8..16].try_into().unwrap());
    let client_data = &data[16..];

    // the wallet: this program's account, at the address its own key derives
    if wallet.owner != program_id || wallet.data_len() != WALLET_LEN { return Err(err(E_WALLET)); }
    let (key, bump, last) = {
        let d = wallet.try_borrow_data()?;
        if d[W_VERSION] != 1 { return Err(err(E_WALLET)); }
        let key: [u8; webauthn::KEY_LEN] = d[W_KEY..W_KEY + webauthn::KEY_LEN].try_into().unwrap();
        (key, d[W_BUMP], u64::from_le_bytes(d[W_NONCE..W_NONCE + 8].try_into().unwrap()))
    };
    let seed = hashv(&[&key]);
    let seeds: &[&[u8]] = &[b"pk", seed.as_ref(), &[bump]];
    if Pubkey::create_program_address(seeds, program_id) != Ok(*wallet.key) { return Err(err(E_WALLET)); }
    if last.checked_add(1) != Some(nonce) { return Err(err(E_NONCE)); }

    // what the precompile verified, in the instruction right before this one
    if *ixs.key != instructions::ID { return Err(err(E_ACCOUNTS)); }
    let at = instructions::load_current_index_checked(ixs)? as usize;
    if at == 0 { return Err(err(E_PRECOMPILE)); }
    let before = instructions::load_instruction_at_checked(at - 1, ixs)?;
    if before.program_id != SECP256R1_ID { return Err(err(E_PRECOMPILE)); }
    let v = webauthn::verified(&before.data).ok_or_else(|| err(E_PRECOMPILE))?;
    if v.key != key { return Err(err(E_SIGNER)); }
    if !webauthn::low_s(v.signature) { return Err(err(E_HIGH_S)); }

    // the message is authenticatorData || sha256(clientDataJSON), and the client data is the one in this instruction
    if v.message.len() < webauthn::AUTH_MIN + 32 { return Err(err(E_MESSAGE)); }
    let (auth, hash) = v.message.split_at(v.message.len() - 32);
    if hash != hashv(&[client_data]).as_ref() { return Err(err(E_MESSAGE)); }
    if auth[32] & webauthn::USER_PRESENT == 0 { return Err(err(E_PRESENT)); }
    let (ty, signed) = webauthn::client_data(client_data).ok_or_else(|| err(E_CLIENT_DATA))?;
    if ty != CLIENT_TYPE { return Err(err(E_CLIENT_DATA)); }
    if signed != webauthn::b64url(&challenge(wallet.key, mint.key, to.key, amount, nonce)) { return Err(err(E_CHALLENGE)); }

    // the money
    let decimals = token::mint_of(mint, token_program)?;
    if token::token_account(from, token_program.key) != Some((*mint.key, *wallet.key)) || from.key == to.key { return Err(err(E_FROM)); }
    wallet.try_borrow_mut_data()?[W_NONCE..W_NONCE + 8].copy_from_slice(&nonce.to_le_bytes());
    token::transfer(token_program, from, mint, to, wallet, amount, decimals, seeds)?;
    msg!("knosp:withdrawn wallet={} mint={} to={} amount={} nonce={}", wallet.key, mint.key, to.key, amount, nonce);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_challenge_names_the_wallet_the_mint_the_destination_the_amount_and_the_nonce() {
        let (w, m, t) = (Pubkey::new_from_array([1; 32]), Pubkey::new_from_array([2; 32]), Pubkey::new_from_array([3; 32]));
        let base = challenge(&w, &m, &t, 5_000_000, 1);
        let mut raw = b"knos-passkey".to_vec();
        for part in [&[1u8; 32][..], &[2; 32], &[3; 32], &5_000_000u64.to_le_bytes(), &1u64.to_le_bytes()] { raw.extend_from_slice(part); }
        assert_eq!(base, hashv(&[&raw]).to_bytes());
        for other in [challenge(&m, &m, &t, 5_000_000, 1), challenge(&w, &w, &t, 5_000_000, 1), challenge(&w, &m, &w, 5_000_000, 1),
                      challenge(&w, &m, &t, 5_000_001, 1), challenge(&w, &m, &t, 5_000_000, 2), challenge(&w, &m, &t, 1, 5_000_000)] {
            assert_ne!(base, other);
        }
    }

    #[test]
    fn a_wallets_address_is_fixed_by_its_key() {
        let id = pubkey!("FQPX9i5kQxLYKZyyPgM2fVK9am3w1LSk1Cuoer1sSY85");
        let (mut a, mut b) = ([2u8; 33], [2u8; 33]);
        b[0] = 3; // the same x, the other y: another key
        assert_ne!(wallet_of(&id, &a).0, wallet_of(&id, &b).0);
        a[32] ^= 1;
        assert_ne!(wallet_of(&id, &a).0, wallet_of(&id, &[2u8; 33]).0);
        assert_eq!(WALLET_LEN, W_NONCE + 8);
        const { assert!(W_KEY + webauthn::KEY_LEN <= W_NONCE) };
    }
}
