//! The accounts this program owns (their layouts and addresses) and the small helpers every instruction uses.
//! Every account is a PDA of this program, created by it, and is read only at the address its seeds derive, so one
//! kind can never be read as another. All integers are little-endian; bytes not named below are zero.
use crate::{err, E_ACCOUNTS, E_BALANCE, E_JOB, E_REPLAY, TOKEN_AHEAD, TOKEN_LIFE};
use solana_program::{
    account_info::AccountInfo,
    entrypoint::ProgramResult,
    program::{invoke, invoke_signed},
    program_error::ProgramError,
    pubkey::Pubkey,
    rent::Rent,
    clock::Clock,
    system_instruction, system_program,
    sysvar::Sysvar,
};

// Balance ["bal", owner_id, authority, mint]: money a wallet set aside for the bounties of one repository owner
pub const B_VERSION: usize = 0;     // 1
pub const B_BUMP: usize = 1;
pub const B_FAUCET: usize = 2;      // 1: the devnet faucet's balance (test money: any actor spends it, nobody withdraws it)
pub const B_X: usize = 3;           // 1: it has a side account ["balx", balance]; every funding from it must pass that account
pub const B_OWNER_ID: usize = 8;    // the GitHub id of the repository owner (a user or an organisation)
pub const B_AUTHORITY: usize = 16;  // the wallet that opened it: the only one that can change or withdraw it
pub const B_MINT: usize = 48;
pub const B_CAP: usize = 80;        // the most one job may take (0: no cap)
pub const B_LAST_IAT: usize = 88;   // the `iat` of the last fund token that spent it
pub const B_SPENDERS: usize = 96;   // [u64; 4]: GitHub ids that may spend it besides the owner (0: empty)
pub const B_SPENT: usize = 128;     // everything it ever put into jobs
pub const BALANCE_LEN: usize = 160;

// Job ["job", repo_id, issue, source]: one bounty; source is the Balance it was funded from, or the funding wallet
pub const OPEN: u8 = 1;
pub const HELD: u8 = 3;
pub const J_STATE: usize = 0;       // OPEN, or HELD (proven, waiting for the payee to bind a wallet)
pub const J_MODE: usize = 1;        // 0 merge, 1 tests
pub const J_KIND: usize = 2;        // 0 funded by a wallet, 1 from a Balance
pub const J_BUMP: usize = 3;
pub const J_TOKEN_PROGRAM: usize = 6; // 0 Token, 1 Token-2022
pub const J_FAUCET: usize = 7;      // 1: the mint is the devnet faucet's (test money)
pub const J_REPO: usize = 8;
pub const J_ISSUE: usize = 16;
pub const J_AMOUNT: usize = 24;     // what the vault received for this job
pub const J_DEADLINE: usize = 32;
pub const J_HOLD_UNTIL: usize = 48;
pub const J_PAYEE: usize = 56;      // HELD: the GitHub id the money waits for
pub const J_FUNDER_ID: usize = 64;  // the GitHub id of whoever wrote the funding comment (0 for a wallet)
pub const J_NOT_BEFORE: usize = 72; // a pay token must be issued at or after this
pub const J_OWNER_ID: usize = 80;   // the Balance's owner id (0 for a wallet): the funder the record counts
pub const J_SOURCE: usize = 88;
pub const J_REFUND_TO: usize = 120; // the Balance's token account, or the funding wallet
pub const J_RENT_TO: usize = 152;   // who paid this account's rent and gets it back
pub const J_MINT: usize = 184;
pub const J_TERMS: usize = 216;     // sha256 of the terms JSON logged at funding
pub const J_WF_REPO: usize = 248;   // sha256 of "owner/name": the repository that holds the workflows
pub const J_WF_SHA: usize = 280;    // their commit, 40 hex characters
pub const JOB_LEN: usize = 320;

// Bind ["bind", user_id]: the wallet a GitHub user chose to be paid at
pub const BD_VERSION: usize = 0;    // 1
pub const BD_BUMP: usize = 1;
pub const BD_USER: usize = 8;
pub const BD_WALLET: usize = 16;
pub const BD_IAT: usize = 48;       // the `iat` of the bind token that set it
pub const BIND_LEN: usize = 56;

// Rep ["rep", user_id]: a GitHub user's public record
pub const R_PAID: usize = 0;        // u32: payments in real money from someone else
pub const R_FUNDERS: usize = 4;     // u32: distinct funders among them
pub const R_TOTAL: usize = 8;       // what those payments put in the user's wallet
pub const R_TEST_PAID: usize = 16;  // u32: payments in the faucet's test money
pub const R_SELF_PAID: usize = 20;  // u32: payments whose funder was the payee
pub const R_TEST_TOTAL: usize = 32;
pub const R_FIRST: usize = 40;      // the time of the first and of the latest payment counted in `paid`
pub const R_LAST: usize = 48;
pub const REP_LEN: usize = 64;

// BalX ["balx", balance]: more rules for spending a Balance, set by its authority (SetBalanceX), and what it spent.
// Limits are in the mint's smallest units, as the Balance's cap is; 0: no limit.
pub const X_VERSION: usize = 0;     // 1
pub const X_BUMP: usize = 1;
pub const X_DAY_LIMIT: usize = 8;   // the most it may spend in one day (UTC)
pub const X_TOTAL_LIMIT: usize = 16; // the most it may spend from the day the side account was made
pub const X_REPOS: usize = 24;      // [u64; 8]: the only repository ids that may spend it (all zero: any repository of the owner)
pub const X_WF_SHA: usize = 88;     // [u8; 40]: if set, the only commit of the pinned workflows that may spend it (all zero: any)
pub const X_DAY: usize = 128;       // i64: the day (unix time / 86400) `day_spent` counts
pub const X_DAY_SPENT: usize = 136;
pub const X_TOTAL_SPENT: usize = 144;
pub const BALX_LEN: usize = 152;

// Plan ["plan", owner_id]: a lower fee rate for the orders of one repository owner until `expires`, set by FEE_OWNER
pub const P_VERSION: usize = 0;     // 1
pub const P_BUMP: usize = 1;
pub const P_BPS: usize = 2;         // u16: PLAN_BPS_MIN..=FEE_BPS
pub const P_OWNER: usize = 8;
pub const P_EXPIRES: usize = 16;    // i64: the rate holds while now < expires
pub const PLAN_LEN: usize = 24;

// Used ["used", sha256(a token's signature bytes)]: byte 0 is 1; exists once that token was used by an instruction
// that takes a token once (2.0 Pay, FundOrderBalance). It keeps what CloseMarker needs to give its rent back.
pub const U_PAYER: usize = 1;       // who paid its rent
pub const U_AFTER: usize = 33;      // i64: after this time no instruction can accept the token, and the marker may be closed
pub const USED_LEN: usize = 41;

// Order ["ord", scope, source, seq u32]: one work order (2.1). 512 bytes. Its money (amount + fee, less what was
// paid) is alone in its own token account ["ov", order]. `scope` is sha256("knos3:scope" || repo_id || issue) for a
// public order; a private one stores a scope its funder computed (sha256(salt || repo_id || issue)) and zero in
// `repo` and `issue`. `source` is the Balance it was funded from, or the funding wallet.
pub const WARRANTY: u8 = 4;
pub const F_FAUCET: u8 = 1;         // flags. FAUCET and TOKEN2022 are set by the program; the others by the funder (opts)
pub const F_PRIVATE: u8 = 2;
pub const F_NEUTRAL: u8 = 4;
pub const F_STANDING: u8 = 8;
pub const F_TOKEN2022: u8 = 16;
pub const O_VERSION: usize = 0;     // 2
pub const O_STATE: usize = 1;       // OPEN 1, HELD 3 (proven, waits for its one payee to bind a wallet), WARRANTY 4
pub const O_MODE: usize = 2;        // 0 merge, 1 tests
pub const O_KIND: usize = 3;        // source kind: 0 a wallet, 1 a Balance
pub const O_FLAGS: usize = 4;
pub const O_BUMP: usize = 5;
pub const O_DECIMALS: usize = 6;    // the mint's, at funding
pub const O_RESERVE_DAYS: usize = 7; // opts: how long a reservation (Reserve) lasts
pub const O_REPO: usize = 8;        // u64 (0: private)
pub const O_ISSUE: usize = 16;      // u64 (0: private)
pub const O_SCOPE: usize = 24;      // [u8; 32]
pub const O_SEQ: usize = 56;        // u32
pub const O_HOLDBACK_BPS: usize = 60; // u16, opts: this share of a payment stays in the order for `warranty_s`
pub const O_KILL_BPS: usize = 62;   // u16, opts: this share goes to the taker when a reserved order is cancelled
pub const O_AMOUNT: usize = 64;     // what payees receive in total
pub const O_FEE: usize = 72;        // escrowed on top of the amount: the relayer's tip and Knos's fee
pub const O_RATE: usize = 80;       // opts, STANDING: what one accepted change is paid
pub const O_PAID: usize = 88;       // of `amount`, so far
pub const O_DEADLINE: usize = 96;   // i64
pub const O_NOT_BEFORE: usize = 104; // i64: a token must be issued at or after this
pub const O_HOLD_UNTIL: usize = 112; // i64, HELD
pub const O_WARRANTY_S: usize = 120; // i64, opts: warranty days * 86400
pub const O_RESERVED_BY: usize = 128; // u64: the GitHub id that took it (Reserve)
pub const O_RESERVED_UNTIL: usize = 136; // i64
pub const O_CANCEL_AT: usize = 144; // i64: when Cancel was sent (0: never)
pub const O_PAYEE: usize = 152;     // u64, HELD: the GitHub id the money waits for
pub const O_FUNDER_ID: usize = 160; // the GitHub id of whoever wrote the funding comment (0 for a wallet)
pub const O_OWNER_ID: usize = 168;  // the Balance's owner id (0 for a wallet)
pub const O_ARBITER_ID: usize = 176; // opts: the GitHub id whose ruling pays it (0: none)
pub const O_JUDGE_REPO: usize = 184; // opts: the repository id whose runs may judge it (0: none)
pub const O_SOURCE: usize = 192;
pub const O_REFUND_TO: usize = 224; // the Balance's token account, or the funding wallet
pub const O_RENT_TO: usize = 256;   // who paid the rent of the order and of its token account, and gets both back
pub const O_MINT: usize = 288;
pub const O_TERMS: usize = 320;     // sha256 of the terms JSON
pub const O_WF_REPO: usize = 352;   // sha256 of "owner/name": the repository that holds the pinned workflows
pub const O_WF_SHA: usize = 384;    // their commit, 40 hex characters
pub const O_FEE_BPS: usize = 424;   // u16: the fee rate fixed at funding (TopUp charges the same)
pub const O_RESERVED: usize = 432;  // 80 bytes, zero: for what comes later
pub const ORDER_LEN: usize = 512;

// Pair ["pair", payee_id, funder key]: one byte (1); exists once this funder has paid this payee in real money
pub const PAIR_LEN: usize = 1;
// Rate ["rate", repo_id]: the devnet faucet's last use by this repository: chain time i64, that token's iat i64
pub const RATE_LEN: usize = 16;
// Pause ["pause"]: new funding is refused until this time (i64)
pub const PAUSE_LEN: usize = 8;

pub fn u16_at(d: &[u8], o: usize) -> u16 { u16::from_le_bytes([d[o], d[o + 1]]) }
pub fn put_u16(d: &mut [u8], o: usize, v: u16) { d[o..o + 2].copy_from_slice(&v.to_le_bytes()); }
pub fn u32_at(d: &[u8], o: usize) -> u32 { u32::from_le_bytes(d[o..o + 4].try_into().unwrap()) }
pub fn u64_at(d: &[u8], o: usize) -> u64 { u64::from_le_bytes(d[o..o + 8].try_into().unwrap()) }
pub fn i64_at(d: &[u8], o: usize) -> i64 { i64::from_le_bytes(d[o..o + 8].try_into().unwrap()) }
pub fn key_at(d: &[u8], o: usize) -> Pubkey { Pubkey::new_from_array(d[o..o + 32].try_into().unwrap()) }
pub fn put_u32(d: &mut [u8], o: usize, v: u32) { d[o..o + 4].copy_from_slice(&v.to_le_bytes()); }
pub fn put_u64(d: &mut [u8], o: usize, v: u64) { d[o..o + 8].copy_from_slice(&v.to_le_bytes()); }
pub fn put_i64(d: &mut [u8], o: usize, v: i64) { d[o..o + 8].copy_from_slice(&v.to_le_bytes()); }
pub fn put_key(d: &mut [u8], o: usize, k: &Pubkey) { d[o..o + 32].copy_from_slice(k.as_ref()); }

/// The first N accounts of an instruction, in the order the module documentation lists them.
pub fn take<'a, 'b, const N: usize>(accounts: &'b [AccountInfo<'a>]) -> Result<&'b [AccountInfo<'a>; N], ProgramError> {
    accounts.get(..N).and_then(|s| s.try_into().ok()).ok_or(ProgramError::NotEnoughAccountKeys)
}

/// ["auth"]: the owner of every vault and of every Balance's token account. Only this program signs for it.
pub fn auth_key(program_id: &Pubkey) -> (Pubkey, u8) { Pubkey::find_program_address(&[b"auth"], program_id) }
pub fn vault_key(program_id: &Pubkey, mint: &Pubkey) -> (Pubkey, u8) { Pubkey::find_program_address(&[b"vault", mint.as_ref()], program_id) }
pub fn balx_key(program_id: &Pubkey, balance: &Pubkey) -> (Pubkey, u8) { Pubkey::find_program_address(&[b"balx", balance.as_ref()], program_id) }
/// ["ov", order]: the token account that holds one order's money and nothing else.
pub fn ov_key(program_id: &Pubkey, order: &Pubkey) -> (Pubkey, u8) { Pubkey::find_program_address(&[b"ov", order.as_ref()], program_id) }
pub fn baltok_key(program_id: &Pubkey, balance: &Pubkey) -> (Pubkey, u8) { Pubkey::find_program_address(&[b"baltok", balance.as_ref()], program_id) }
/// ["mint"]: the devnet faucet's test-USDC mint. No account can exist at this address on a build without the faucet.
pub fn faucet_mint(program_id: &Pubkey) -> (Pubkey, u8) { Pubkey::find_program_address(&[b"mint"], program_id) }

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
    if !acct.data_is_empty() || *acct.owner != system_program::ID { return Err(err(bad)); }
    let b = [bump];
    let mut signer: Vec<&[u8]> = seeds.to_vec();
    signer.push(&b);
    create_pda(payer, acct, sys, program_id, len, &signer)?;
    Ok((true, bump))
}

/// Closes an account of this program: its lamports to `to`, its data gone.
pub fn close<'a>(acct: &AccountInfo<'a>, to: &AccountInfo<'a>) -> ProgramResult {
    **to.try_borrow_mut_lamports()? = to.lamports().checked_add(acct.lamports()).ok_or(ProgramError::ArithmeticOverflow)?;
    **acct.try_borrow_mut_lamports()? = 0;
    acct.resize(0)?;
    acct.assign(&system_program::ID);
    Ok(())
}

pub struct Balance { pub faucet: bool, pub x: bool, pub owner_id: u64, pub authority: Pubkey, pub mint: Pubkey, pub cap: u64, pub last_iat: i64, pub spenders: [u64; 4] }
/// A Balance, read after checking that this program owns the account, that it has a Balance's length, and that its
/// address is the one its own fields derive.
pub fn load_balance(program_id: &Pubkey, a: &AccountInfo) -> Result<Balance, ProgramError> {
    if a.owner != program_id || a.data_len() != BALANCE_LEN { return Err(err(E_BALANCE)); }
    let d = a.try_borrow_data()?;
    let seeds: [&[u8]; 5] = [b"bal", &d[B_OWNER_ID..B_OWNER_ID + 8], &d[B_AUTHORITY..B_AUTHORITY + 32], &d[B_MINT..B_MINT + 32], &[d[B_BUMP]]];
    let at = Pubkey::create_program_address(&seeds, program_id);
    if d[B_VERSION] != 1 || at != Ok(*a.key) { return Err(err(E_BALANCE)); }
    let mut spenders = [0u64; 4];
    for (k, s) in spenders.iter_mut().enumerate() { *s = u64_at(&d, B_SPENDERS + 8 * k); }
    Ok(Balance { faucet: d[B_FAUCET] == 1, x: d[B_X] == 1, owner_id: u64_at(&d, B_OWNER_ID), authority: key_at(&d, B_AUTHORITY), mint: key_at(&d, B_MINT),
                 cap: u64_at(&d, B_CAP), last_iat: i64_at(&d, B_LAST_IAT), spenders })
}

pub struct Job {
    pub state: u8, pub mode: u8, pub kind: u8, pub t22: bool, pub faucet: bool, pub repo: u64, pub issue: u64, pub amount: u64,
    pub deadline: i64, pub hold_until: i64, pub payee: u64, pub funder_id: u64, pub not_before: i64, pub owner_id: u64,
    pub source: Pubkey, pub refund_to: Pubkey, pub rent_to: Pubkey, pub mint: Pubkey, pub terms: [u8; 32], pub wf_repo: [u8; 32], pub wf_sha: [u8; 40],
}
/// A job, read after the same three checks. A job that was paid or refunded is gone: its address holds nothing.
pub fn load_job(program_id: &Pubkey, a: &AccountInfo) -> Result<Job, ProgramError> {
    if a.owner != program_id || a.data_len() != JOB_LEN { return Err(err(E_JOB)); }
    let d = a.try_borrow_data()?;
    let seeds: [&[u8]; 5] = [b"job", &d[J_REPO..J_REPO + 8], &d[J_ISSUE..J_ISSUE + 8], &d[J_SOURCE..J_SOURCE + 32], &[d[J_BUMP]]];
    let at = Pubkey::create_program_address(&seeds, program_id);
    if at != Ok(*a.key) { return Err(err(E_JOB)); }
    Ok(Job {
        state: d[J_STATE], mode: d[J_MODE], kind: d[J_KIND], t22: d[J_TOKEN_PROGRAM] == 1, faucet: d[J_FAUCET] == 1,
        repo: u64_at(&d, J_REPO), issue: u64_at(&d, J_ISSUE), amount: u64_at(&d, J_AMOUNT), deadline: i64_at(&d, J_DEADLINE),
        hold_until: i64_at(&d, J_HOLD_UNTIL), payee: u64_at(&d, J_PAYEE), funder_id: u64_at(&d, J_FUNDER_ID),
        not_before: i64_at(&d, J_NOT_BEFORE), owner_id: u64_at(&d, J_OWNER_ID), source: key_at(&d, J_SOURCE),
        refund_to: key_at(&d, J_REFUND_TO), rent_to: key_at(&d, J_RENT_TO), mint: key_at(&d, J_MINT),
        terms: d[J_TERMS..J_TERMS + 32].try_into().unwrap(), wf_repo: d[J_WF_REPO..J_WF_REPO + 32].try_into().unwrap(),
        wf_sha: d[J_WF_SHA..J_WF_SHA + 40].try_into().unwrap(),
    })
}

/// `micro` millionths of one whole unit of a mint with `decimals` decimals, in the mint's smallest units: the bounds
/// and the fee floors are written for a whole unit (one USDC), whatever the mint's decimals are.
pub fn units(micro: u64, decimals: u8) -> u64 {
    if micro == 0 { return 0; }
    let v = match 10u128.checked_pow(decimals as u32) { Some(p) => (micro as u128).saturating_mul(p) / 1_000_000, None => u128::MAX };
    v.min(u64::MAX as u128) as u64
}

/// Takes a token that works once: creates its marker ["used", sig] (rent from `payer`), and refuses with E_REPLAY
/// when the marker exists. `sig`: gh::sig_hash, sha256 of the token's signature bytes. The marker stores who paid for it
/// and when it stops mattering: a token accepted now was issued at most TOKEN_AHEAD from now, expires at most
/// TOKEN_LIFE after that, and is refused from knos_oidc::LATE after its expiry; an hour after that latest moment
/// (which is not before "an hour after the token's own expiry plus the lateness") CloseMarker may close it.
pub fn mark_used<'a>(program_id: &Pubkey, payer: &AccountInfo<'a>, used: &AccountInfo<'a>, sys: &AccountInfo<'a>, sig: &[u8; 32]) -> ProgramResult {
    let (key, bump) = Pubkey::find_program_address(&[b"used", sig], program_id);
    if *used.key != key { return Err(err(E_ACCOUNTS)); }
    if used.owner == program_id { return Err(err(E_REPLAY)); }
    if !used.data_is_empty() || *used.owner != system_program::ID { return Err(err(E_ACCOUNTS)); }
    create_pda(payer, used, sys, program_id, USED_LEN, &[b"used", sig, &[bump]])?;
    let mut d = used.try_borrow_mut_data()?;
    d[0] = 1;
    put_key(&mut d, U_PAYER, payer.key);
    put_i64(&mut d, U_AFTER, Clock::get()?.unix_timestamp.saturating_add(TOKEN_AHEAD + TOKEN_LIFE + knos_oidc::LATE + 3600));
    Ok(())
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
    fn b58_prints_a_key_as_solana_does() {
        let mut x = 0x9e37_79b9_7f4a_7c15u64;
        let mut next = move || { x ^= x << 13; x ^= x >> 7; x ^= x << 17; x };
        for i in 0..20_000usize {
            let mut k = [0u8; 32];
            for c in k.chunks_mut(8) { c.copy_from_slice(&next().to_le_bytes()); }
            for b in k.iter_mut().take(i % 34) { *b = 0; }      // every count of leading zero bytes, the zero key included
            if i % 7 == 0 { k[31] = (i % 3) as u8; }
            let key = Pubkey::new_from_array(k);
            assert_eq!(b58(&key), key.to_string());
        }
        for k in [[0u8; 32], [255u8; 32], [1u8; 32]] {
            assert_eq!(b58(&Pubkey::new_from_array(k)), Pubkey::new_from_array(k).to_string());
        }
        assert_eq!(b58(&Pubkey::new_from_array([0u8; 32])), "1".repeat(32));
    }

    #[test]
    fn a_whole_unit_is_ten_to_the_decimals() {
        assert_eq!((units(1_000_000, 6), units(50_000, 6), units(1_000_000, 9), units(50_000, 9), units(1_000_000, 0), units(50_000, 0), units(400_000, 2)),
                   (1_000_000, 50_000, 1_000_000_000, 50_000_000, 1, 0, 40));
        assert_eq!((units(5_000_000, 18), units(500_000_000, 18), units(1, 255), units(0, 255)), (5 * 10u64.pow(18), u64::MAX, u64::MAX, 0));
    }

    #[test]
    fn layouts_do_not_overlap_and_fill_their_lengths() {
        // (offset, size) of every field, in order, and the account's length
        let job = [(J_STATE, 1), (J_MODE, 1), (J_KIND, 1), (J_BUMP, 1), (J_TOKEN_PROGRAM, 1), (J_FAUCET, 1), (J_REPO, 8), (J_ISSUE, 8), (J_AMOUNT, 8),
                   (J_DEADLINE, 8), (J_HOLD_UNTIL, 8), (J_PAYEE, 8), (J_FUNDER_ID, 8), (J_NOT_BEFORE, 8), (J_OWNER_ID, 8), (J_SOURCE, 32),
                   (J_REFUND_TO, 32), (J_RENT_TO, 32), (J_MINT, 32), (J_TERMS, 32), (J_WF_REPO, 32), (J_WF_SHA, 40)];
        let balance = [(B_VERSION, 1), (B_BUMP, 1), (B_FAUCET, 1), (B_X, 1), (B_OWNER_ID, 8), (B_AUTHORITY, 32), (B_MINT, 32), (B_CAP, 8), (B_LAST_IAT, 8),
                       (B_SPENDERS, 32), (B_SPENT, 8)];
        let bind = [(BD_VERSION, 1), (BD_BUMP, 1), (BD_USER, 8), (BD_WALLET, 32), (BD_IAT, 8)];
        let rep = [(R_PAID, 4), (R_FUNDERS, 4), (R_TOTAL, 8), (R_TEST_PAID, 4), (R_SELF_PAID, 4), (R_TEST_TOTAL, 8), (R_FIRST, 8), (R_LAST, 8)];
        let balx = [(X_VERSION, 1), (X_BUMP, 1), (X_DAY_LIMIT, 8), (X_TOTAL_LIMIT, 8), (X_REPOS, 64), (X_WF_SHA, 40), (X_DAY, 8), (X_DAY_SPENT, 8), (X_TOTAL_SPENT, 8)];
        let plan = [(P_VERSION, 1), (P_BUMP, 1), (P_BPS, 2), (P_OWNER, 8), (P_EXPIRES, 8)];
        let order = [(O_VERSION, 1), (O_STATE, 1), (O_MODE, 1), (O_KIND, 1), (O_FLAGS, 1), (O_BUMP, 1), (O_DECIMALS, 1), (O_RESERVE_DAYS, 1), (O_REPO, 8),
                     (O_ISSUE, 8), (O_SCOPE, 32), (O_SEQ, 4), (O_HOLDBACK_BPS, 2), (O_KILL_BPS, 2), (O_AMOUNT, 8), (O_FEE, 8), (O_RATE, 8), (O_PAID, 8),
                     (O_DEADLINE, 8), (O_NOT_BEFORE, 8), (O_HOLD_UNTIL, 8), (O_WARRANTY_S, 8), (O_RESERVED_BY, 8), (O_RESERVED_UNTIL, 8), (O_CANCEL_AT, 8),
                     (O_PAYEE, 8), (O_FUNDER_ID, 8), (O_OWNER_ID, 8), (O_ARBITER_ID, 8), (O_JUDGE_REPO, 8), (O_SOURCE, 32), (O_REFUND_TO, 32),
                     (O_RENT_TO, 32), (O_MINT, 32), (O_TERMS, 32), (O_WF_REPO, 32), (O_WF_SHA, 40), (O_FEE_BPS, 2), (O_RESERVED, 80)];
        assert_eq!(O_RESERVED + 80, ORDER_LEN);
        for (fields, len) in [(&job[..], JOB_LEN), (&balance[..], BALANCE_LEN), (&bind[..], BIND_LEN), (&rep[..], REP_LEN), (&balx[..], BALX_LEN),
                              (&plan[..], PLAN_LEN), (&order[..], ORDER_LEN)] {
            let mut end = 0;
            for &(at, size) in fields {
                assert!(at >= end, "a field starts inside the one before it");
                end = at + size;
            }
            assert!(end <= len);
        }
        assert_eq!(J_WF_SHA + 40, JOB_LEN);
        // the kinds that are read by their own content also differ in length
        let mut lens = [BALANCE_LEN, JOB_LEN, BIND_LEN, REP_LEN, PAIR_LEN, BALX_LEN, PLAN_LEN, ORDER_LEN];
        lens.sort_unstable();
        assert!(lens.windows(2).all(|w| w[0] != w[1]));
    }
}
