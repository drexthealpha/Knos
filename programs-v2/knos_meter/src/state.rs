//! The accounts this program owns (their layouts and addresses) and the small helpers every instruction uses.
//! Every account is a PDA of this program, created by it, and is read only at the address its seeds derive, so one
//! kind can never be read as another. All integers are little-endian; bytes not named below are zero.
use crate::{err, E_CREDITS};
use solana_program::{
    account_info::AccountInfo,
    entrypoint::ProgramResult,
    program::{invoke, invoke_signed},
    program_error::ProgramError,
    pubkey::Pubkey,
    rent::Rent,
    system_instruction, system_program,
    sysvar::Sysvar,
};

// Credits ["cr", owner_id, authority, mint]: what a wallet prepaid for the evaluations of one GitHub owner (the buyer)
pub const C_VERSION: usize = 0;     // 1
pub const C_BUMP: usize = 1;
pub const C_T22: usize = 2;         // 0 Token, 1 Token-2022
pub const C_DECIMALS: usize = 3;    // the mint's
pub const C_OWNER_ID: usize = 8;    // the GitHub id of the buyer (a user or an organisation) whose evaluations it pays for
pub const C_AUTHORITY: usize = 16;  // the wallet that opened it: the only one that can re-pin or withdraw it
pub const C_MINT: usize = 48;
pub const C_SPENT: usize = 80;      // every fee it ever paid
pub const C_EVALS: usize = 88;      // the billable evaluations recorded against it, the free ones included
pub const C_WF_REPO: usize = 96;    // sha256 of "owner/name": the repository that holds attest.yml and prove.yml
pub const C_WF_SHA: usize = 128;    // their commit, 40 hex characters: only that commit's runs spend these credits
pub const CREDITS_LEN: usize = 168;

// Plan ["plan", owner_id]: the owner's rate under a contract, and how many evaluations it recorded this month
pub const P_VERSION: usize = 0;     // 1
pub const P_BUMP: usize = 1;
pub const P_TIER: usize = 2;        // a label for the contract (0: none); the contract itself is off chain
pub const P_MONTH: usize = 4;       // u32 yyyymm: the month `used` counts
pub const P_OWNER_ID: usize = 8;
pub const P_RATE: usize = 16;       // per evaluation, in millionths of a whole unit of the mint (0: no plan)
pub const P_EXPIRY: usize = 24;     // the rate holds before this time
pub const P_USED: usize = 32;       // billable evaluations of this owner in `month`: the first FREE_PER_MONTH cost nothing
pub const PLAN_LEN: usize = 40;

// Mark ["k", buyer_id, sha256(work order || artifact || policy || milestone u32)]: this evaluation was billed. It holds
// the rent of whoever relayed it, and gives it back (CloseMark) once it has nothing left to guard.
pub const K_VERSION: usize = 0;     // 2
pub const K_VERDICT: usize = 1;     // 1 accepted, 0 rejected
pub const K_MONTH: usize = 4;       // u32 yyyymm it was counted in
pub const K_BUYER: usize = 8;
pub const K_SELLER: usize = 16;
pub const K_TIME: usize = 24;
pub const K_RATE: usize = 32;       // the value the token declared for an accepted outcome
pub const K_FEE: usize = 40;        // what the credits paid for it
pub const K_PAYER: usize = 48;      // who paid its rent: the only signer that closes it, and the only address the rent goes to
pub const K_CLOSE_AFTER: usize = 80; // from this time on, no token GitHub issued in the month of the count is accepted any more
pub const MARK_LEN: usize = 88;
/// A mark written before CloseMark existed (version 1: the first 48 bytes above, no payer). It stays where it is:
/// its evaluation stays billed, and nobody can close it.
pub const MARK_LEN_1: usize = 48;

// Month ["m", buyer_id, seller_id, yyyymm u32]: the count of one buyer and one seller in one month
pub const M_VERSION: usize = 0;     // 1
pub const M_BUMP: usize = 1;
pub const M_MONTH: usize = 4;       // u32 yyyymm
pub const M_BUYER: usize = 8;
pub const M_SELLER: usize = 16;
pub const M_EVALS: usize = 24;      // billable evaluations: accepted + rejected
pub const M_ACCEPTED: usize = 32;
pub const M_REJECTED: usize = 40;
pub const M_VALUE: usize = 48;      // declared value: the sum of `rate` over the accepted
pub const M_FEES: usize = 56;       // what these evaluations cost in credits
pub const MONTH_LEN: usize = 64;

pub fn u32_at(d: &[u8], o: usize) -> u32 { u32::from_le_bytes(d[o..o + 4].try_into().unwrap()) }
pub fn u64_at(d: &[u8], o: usize) -> u64 { u64::from_le_bytes(d[o..o + 8].try_into().unwrap()) }
pub fn i64_at(d: &[u8], o: usize) -> i64 { i64::from_le_bytes(d[o..o + 8].try_into().unwrap()) }
pub fn key_at(d: &[u8], o: usize) -> Pubkey { Pubkey::new_from_array(d[o..o + 32].try_into().unwrap()) }
pub fn put_u32(d: &mut [u8], o: usize, v: u32) { d[o..o + 4].copy_from_slice(&v.to_le_bytes()); }
pub fn put_u64(d: &mut [u8], o: usize, v: u64) { d[o..o + 8].copy_from_slice(&v.to_le_bytes()); }
pub fn put_i64(d: &mut [u8], o: usize, v: i64) { d[o..o + 8].copy_from_slice(&v.to_le_bytes()); }
pub fn put_key(d: &mut [u8], o: usize, k: &Pubkey) { d[o..o + 32].copy_from_slice(k.as_ref()); }
/// Adds to a counter. A counter that would pass u64 is refused: a count is never silently wrong.
pub fn add(d: &mut [u8], o: usize, by: u64) -> ProgramResult {
    let v = u64_at(d, o).checked_add(by).ok_or(ProgramError::ArithmeticOverflow)?;
    put_u64(d, o, v);
    Ok(())
}

/// The first N accounts of an instruction, in the order the module documentation lists them.
pub fn take<'a, 'b, const N: usize>(accounts: &'b [AccountInfo<'a>]) -> Result<&'b [AccountInfo<'a>; N], ProgramError> {
    accounts.get(..N).and_then(|s| s.try_into().ok()).ok_or(ProgramError::NotEnoughAccountKeys)
}

/// ["auth"]: the owner of every Credits token account. Only this program signs for it.
pub fn auth_key(program_id: &Pubkey) -> (Pubkey, u8) { Pubkey::find_program_address(&[b"auth"], program_id) }
pub fn crtok_key(program_id: &Pubkey, credits: &Pubkey) -> (Pubkey, u8) { Pubkey::find_program_address(&[b"crtok", credits.as_ref()], program_id) }

pub fn create_pda<'a>(payer: &AccountInfo<'a>, acct: &AccountInfo<'a>, sys: &AccountInfo<'a>, owner: &Pubkey, space: usize, seeds: &[&[u8]]) -> ProgramResult {
    let need = Rent::get()?.minimum_balance(space);
    // an address can be sent lamports before it exists: top up, allocate and assign instead of create_account
    let have = acct.lamports();
    if have < need { invoke(&system_instruction::transfer(payer.key, acct.key, need - have), &[payer.clone(), acct.clone(), sys.clone()])?; }
    invoke_signed(&system_instruction::allocate(acct.key, space as u64), &[acct.clone(), sys.clone()], &[seeds])?;
    invoke_signed(&system_instruction::assign(acct.key, owner), &[acct.clone(), sys.clone()], &[seeds])
}

/// The account at this program's PDA of `seeds`, `len` bytes long: created here (zeroed, its rent from `payer`) when
/// it does not exist. Returns (created now, bump). Any other account in its place is refused with `bad`.
pub fn open<'a>(program_id: &Pubkey, payer: &AccountInfo<'a>, acct: &AccountInfo<'a>, sys: &AccountInfo<'a>, len: usize, seeds: &[&[u8]],
                bad: u32) -> Result<(bool, u8), ProgramError> {
    let (k, bump) = Pubkey::find_program_address(seeds, program_id);
    if *acct.key != k { return Err(err(bad)); }
    if acct.owner == program_id { return if acct.data_len() == len { Ok((false, bump)) } else { Err(err(bad)) }; }
    if !acct.data_is_empty() || *acct.owner != system_program::ID || *sys.key != system_program::ID { return Err(err(bad)); }
    let b = [bump];
    let mut signer: Vec<&[u8]> = seeds.to_vec();
    signer.push(&b);
    create_pda(payer, acct, sys, program_id, len, &signer)?;
    Ok((true, bump))
}

pub struct Credits { pub t22: bool, pub decimals: u8, pub owner_id: u64, pub authority: Pubkey, pub mint: Pubkey, pub wf_repo: [u8; 32], pub wf_sha: [u8; 40] }
/// A Credits account, read after checking that this program owns the account, that it has a Credits account's length,
/// and that its address is the one its own fields derive.
pub fn load_credits(program_id: &Pubkey, a: &AccountInfo) -> Result<Credits, ProgramError> {
    if a.owner != program_id || a.data_len() != CREDITS_LEN { return Err(err(E_CREDITS)); }
    let d = a.try_borrow_data()?;
    let seeds: [&[u8]; 5] = [b"cr", &d[C_OWNER_ID..C_OWNER_ID + 8], &d[C_AUTHORITY..C_AUTHORITY + 32], &d[C_MINT..C_MINT + 32], &[d[C_BUMP]]];
    let at = Pubkey::create_program_address(&seeds, program_id);
    if d[C_VERSION] != 1 || at != Ok(*a.key) { return Err(err(E_CREDITS)); }
    Ok(Credits { t22: d[C_T22] == 1, decimals: d[C_DECIMALS], owner_id: u64_at(&d, C_OWNER_ID), authority: key_at(&d, C_AUTHORITY), mint: key_at(&d, C_MINT),
                 wf_repo: d[C_WF_REPO..C_WF_REPO + 32].try_into().unwrap(), wf_sha: d[C_WF_SHA..C_WF_SHA + 40].try_into().unwrap() })
}

/// Bytes as lowercase hex, for the log lines.
pub fn hex(b: &[u8]) -> String {
    const H: &[u8; 16] = b"0123456789abcdef";
    let mut s = String::with_capacity(2 * b.len());
    for &c in b { s.push(H[(c >> 4) as usize] as char); s.push(H[(c & 15) as usize] as char); }
    s
}

/// A key as Solana prints it (base58), for the log lines. Five digits at a time: 58^5 fits in 32 bits.
pub fn b58(k: &Pubkey) -> String {
    const ALPHABET: &[u8; 58] = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    const BASE: u64 = 58 * 58 * 58 * 58 * 58;
    let k = k.to_bytes();
    let mut n = [0u32; 8]; // the key as a number, most significant limb first
    for (limb, c) in n.iter_mut().zip(k.chunks(4)) { *limb = u32::from_be_bytes(c.try_into().unwrap()); }
    let mut out = [b'1'; 45];
    let mut at = out.len();
    for _ in 0..9 {
        let mut rem = 0u64;
        for limb in n.iter_mut() {
            let cur = rem << 32 | *limb as u64;
            *limb = (cur / BASE) as u32;
            rem = cur % BASE;
        }
        for _ in 0..5 { at -= 1; out[at] = ALPHABET[(rem % 58) as usize]; rem /= 58; }
    }
    // each leading zero byte prints as one '1'; every other leading '1' is padding
    let zeros = k.iter().take_while(|&&b| b == 0).count();
    let first = out.iter().position(|&c| c != b'1').unwrap_or(out.len());
    String::from_utf8_lossy(&out[first - zeros.min(first)..]).into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn layouts_do_not_overlap_and_the_kinds_differ_in_length() {
        let credits = [(C_VERSION, 1), (C_BUMP, 1), (C_T22, 1), (C_DECIMALS, 1), (C_OWNER_ID, 8), (C_AUTHORITY, 32), (C_MINT, 32), (C_SPENT, 8), (C_EVALS, 8),
                       (C_WF_REPO, 32), (C_WF_SHA, 40)];
        let plan = [(P_VERSION, 1), (P_BUMP, 1), (P_TIER, 1), (P_MONTH, 4), (P_OWNER_ID, 8), (P_RATE, 8), (P_EXPIRY, 8), (P_USED, 8)];
        let mark = [(K_VERSION, 1), (K_VERDICT, 1), (K_MONTH, 4), (K_BUYER, 8), (K_SELLER, 8), (K_TIME, 8), (K_RATE, 8), (K_FEE, 8), (K_PAYER, 32), (K_CLOSE_AFTER, 8)];
        let month = [(M_VERSION, 1), (M_BUMP, 1), (M_MONTH, 4), (M_BUYER, 8), (M_SELLER, 8), (M_EVALS, 8), (M_ACCEPTED, 8), (M_REJECTED, 8), (M_VALUE, 8), (M_FEES, 8)];
        for (fields, len) in [(&credits[..], CREDITS_LEN), (&plan[..], PLAN_LEN), (&mark[..], MARK_LEN), (&month[..], MONTH_LEN)] {
            let mut end = 0;
            for &(at, size) in fields {
                assert!(at >= end, "a field starts inside the one before it");
                end = at + size;
            }
            assert_eq!(end, len);
        }
        let mut lens = [CREDITS_LEN, PLAN_LEN, MARK_LEN, MARK_LEN_1, MONTH_LEN];   // CloseMark tells a Mark by its length
        lens.sort_unstable();
        assert!(lens.windows(2).all(|w| w[0] != w[1]));
    }

    #[test]
    fn hex_and_b58_print_as_everyone_else_does() {
        assert_eq!(hex(&[0, 1, 0xab, 0xff]), "0001abff");
        for k in [[0u8; 32], [255u8; 32], [1u8; 32], [7u8; 32]] {
            assert_eq!(b58(&Pubkey::new_from_array(k)), Pubkey::new_from_array(k).to_string());
        }
    }
}
