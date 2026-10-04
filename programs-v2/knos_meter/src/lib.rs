//! knos-meter: acceptance without escrow. For a buyer who pays a vendor by invoice and wants a neutral count of what
//! was accepted, and for a vendor who bills per accepted outcome. It moves no customer money: it counts evaluations
//! that GitHub itself signed (a token verified on chain by knos-oidc, OIDC_ID) and takes its own fee for each from
//! credits somebody prepaid. This program is upgradeable only through a multisig with a public 48-hour delay, until
//! an outside review. No key of Knos's changes a count or takes credits: FEE_OWNER receives the fees and can lower one
//! owner's rate (SetPlan), and nothing else.
//!
//! WHAT IS COUNTED. An evaluation is one run of attest.yml or prove.yml, at the commit the Credits account pins, in a
//! repository of the BUYER, on a GitHub-hosted runner: the buyer's own account ran the pinned check, and GitHub signed
//! what it found. A BILLABLE EVALUATION is one (work order, artifact, policy, milestone) of one buyer: it is counted
//! and billed once, the first time a token for it is recorded, whatever the verdict (a rejection is work done, and is
//! billed). A later token for the same four (a retry, a duplicate, a relay sent twice) is free and changes nothing
//! while its Mark stands: the first verdict stands. A change to the artifact is a new evaluation.
//!
//! THE MARK AND ITS RENT. What makes a retry free is the Mark account, and Solana holds rent against an account: more
//! for a Mark than the fee of the evaluation it guards. The relayer puts that rent up, the Mark names the relayer, and
//! CloseMark gives all of it back to that relayer and to nobody else. A Mark can be closed from the first second of
//! the next UTC month plus MARK_GRACE (TOKEN_LIFE and the hour the verifier allows a token past its expiry): by then
//! no token GitHub issued in the month of the count is accepted any more. So a retry is free for the whole calendar
//! month of the count, and a token issued in that month is never billed twice, whenever it is relayed. Only the
//! relayer that paid closes a Mark; one it leaves open keeps the evaluation billed for as long as it stays. After a
//! Mark is closed, a token GitHub issues in a LATER month for the same four (a new first run of the pinned workflow
//! in the buyer's repository) is a new billable evaluation of that later month; both knosm:eval lines name the four.
//! Why the Mark and not a filter in the month's count: a Bloom filter says "billed before" of some evaluations that
//! never were, which would drop them from a count that must be exact, and a list of keys in the Month account holds
//! rent that nobody gets back.
//!
//! TWO MODES. The INDIVIDUAL mode above (Record) keeps one Mark per evaluation, and a Mark's rent is more than the fee
//! it guards. The BATCH mode (RecordBatch) writes no account per evaluation: one signed token carries the count of
//! many evaluations, how many were accepted, their declared value and the root of a Merkle tree over their keys, and
//! one Ledger account per (buyer, seller, month) keeps the totals and a running hash of every batch. The evaluations
//! themselves are in a ledger file off chain; anyone who holds it recomputes each root and the running hash and
//! compares them with the account. A batch token is taken once because its `seq` must be the Ledger's `next_seq`.
//! The program does not see the evaluations of a batch, so it cannot tell that one was also recorded by Record or in
//! another batch: the off-chain ledger shows that (leaves are sorted and never repeat inside a batch), the chain does
//! not. ClaimBatch is the SELLER's own count of the same month, in an account of its own, at no fee: a buyer who
//! leaves evaluations out is visible on chain as two counts that differ, and the two ledger files say which.
//!
//! THE TREE (the program stores the root and never computes it). RFC 6962: leaf = sha256(0x00 || id),
//! node = sha256(0x01 || left || right), split at the largest power of two below the number of leaves. id is the key
//! of the individual mode: sha256(work order || artifact (40 hex characters) || policy || milestone u32). Leaves are
//! sorted ascending by id and none repeats.
//!
//! THE RUNNING HASH. A new Ledger's `chain` is 32 zero bytes. Each batch sets
//!   chain = sha256(chain || root || seq u64 || count u64 || accepted u64 || value u64)      integers little-endian
//!
//! WHERE MONEY CAN GO. Tokens leave a Credits token account only by these two transfers, each a TransferChecked:
//!   crtok -> a token account of FEE_OWNER                      Record: the fee of one billable evaluation; RecordBatch: of a batch
//!   crtok -> a token account of the wallet that opened it      WithdrawCredits, that wallet signs
//! A fee that the credits do not hold is refused, and the evaluation with it: credits never go below zero and no
//! debt is kept. Money enters by a plain token transfer to crtok, from anyone.
//!
//! ACCOUNTS. All are PDAs of this program, created by it; layouts are in state.rs; ids in seeds are u64 little-endian.
//!   auth     ["auth"]                            owns every Credits token account; holds nothing
//!   Credits  ["cr", owner id, authority, mint]   what a wallet (authority) prepaid for the evaluations of one GitHub
//!                                                owner, and the commit of the workflows whose runs may spend it
//!   crtok    ["crtok", credits]                  its token account. Anyone adds money with a plain transfer to it.
//!   Plan     ["plan", owner id]                  the owner's rate under a contract, and its evaluations this month
//!   Mark     ["k", buyer id, key]                this evaluation was billed; key = sha256(work order || artifact (40
//!                                                hex characters) || policy || milestone u32). Closed by CloseMark.
//!   Month    ["m", buyer id, seller id, yyyymm u32]   the count of one buyer and one seller in one month (UTC)
//!   Ledger   ["l", buyer id, seller id, yyyymm u32]   the batches the BUYER's runs recorded for that month (RecordBatch)
//!   Ledger   ["lc", buyer id, seller id, yyyymm u32]  the batches the SELLER's runs claimed for it (ClaimBatch); same layout
//!
//! THE TOKEN. A GitHub Actions OIDC token in an account that knos-oidc owns and marked VERIFIED, read through
//! knos-oidc-interface. Required, in gh.rs: issuer GitHub; at most an hour past its expiry; `iat` at most TOKEN_AHEAD
//! ahead of the chain's clock and `exp` at most TOKEN_LIFE after `iat`; `runner_environment` github-hosted. And the
//! key that verified it must still be good: the instruction takes knos-oidc's key account (`key`) right after the
//! token account, and it must be the account the token account names (its bytes 18..50), owned by knos-oidc, ready,
//! not revoked (78), active (76), not expired (77), and of a kind this program knows (E_KEY_KIND): a private key, one
//! a wallet registered with no attestation, counts nothing here. The audience (`aud`):
//!   knosm:eval:<buyer owner id>:<seller id>:<work order hex32>:<artifact hex40>:<policy hex32>:<milestone>:<verdict 0|1>:<rate>
//! `rate` is what the seller bills for this outcome if it is accepted, in the smallest units of whatever the two
//! settle in. The batch mode's two audiences (gh.rs has the rules of each field):
//!   knosm:batch:<buyer owner id>:<seller id>:<month yyyymm>:<seq>:<count>:<accepted>:<value>:<root hex32>
//!   knosm:claim:<buyer owner id>:<seller id>:<month yyyymm>:<seq>:<count>:<accepted>:<value>:<root hex32> A token is not a secret: anyone may relay one, and what it can do is fixed by its claims and audience.
//!
//! PRICES, in whole units of the mint (read from the mint's decimals). FEE 0.05 per billable evaluation; under a Plan
//! that has not expired, the Plan's rate, PLAN_MIN 0.02 ..= FEE; the first FREE_PER_MONTH (10,000) billable
//! evaluations of an owner in a calendar month (UTC) cost nothing. Rates are kept in millionths of a whole unit.
//!
//! INSTRUCTIONS. The first byte of the data is the tag; integers are little-endian; (s) signs, (w) is writable.
//!   0 OpenCredits      authority(s,w) credits(w) crtok(w) mint auth token_program system
//!                      data: owner_id u64, wf_repo [u8; 32], wf_sha [u8; 40]
//!                      Any wallet, for any GitHub owner id but 0: it is the wallet's own money. Creates the Credits
//!                      account and its token account, both empty, and pins the workflows whose runs may spend it:
//!                      sha256 of the "owner/name" of the repository that holds attest.yml and prove.yml, and their
//!                      commit (40 hex characters). Sent again by the same wallet, it sets a new pin and nothing else.
//!                      The mint must pass the mint rules. No money moves.
//!   1 WithdrawCredits  authority(s) credits crtok(w) dest_token(w) mint auth token_program
//!                      data: amount u64
//!                      The wallet that opened the Credits takes unspent money back (amount 0: all of it). dest_token
//!                      must be a token account of the Credits' mint owned by that same wallet.
//!   2 SetPlan          fee_owner(s) payer(s,w) plan(w) system
//!                      data: owner_id u64, tier u8, rate u64, expiry i64
//!                      FEE_OWNER signs. Until `expiry` the owner pays `rate` per billable evaluation (millionths of
//!                      a whole unit, PLAN_MIN..=FEE). tier is a label for the contract, which is off chain. The
//!                      owner's count of this month is kept.
//!   3 Record           relayer(s,w) token key credits(w) crtok(w) plan(w) mark(w) month(w) fee_token(w) mint auth token_program system
//!                      Anyone relays. The token: workflow file attest.yml or prove.yml of the repository the Credits
//!                      account pins, at the commit it pins; `run_attempt` 1 (a re-run keeps the first run's name
//!                      whoever starts it); `repository_owner_id` is the audience's buyer and the Credits' owner. The
//!                      Mark of (buyer, work order, artifact, policy, milestone) exists: nothing else happens (logs
//!                      knosm:retry). Else it is created; the owner's count of the month goes up by one (Plan, created
//!                      on first use, reset when the month changes); past FREE_PER_MONTH the fee goes from crtok to
//!                      fee_token, a token account of the Credits' mint owned by FEE_OWNER (not read while the
//!                      evaluation is free), and credits that hold less are refused (E_FUNDS); the Month of (buyer,
//!                      seller, this month) counts the evaluation, its verdict and, when accepted, its rate.
//!                      The Mark keeps the relayer's address and the time from which it can be closed.
//!   4 CloseMark        payer(s,w) mark(w)
//!                      The relayer that paid a Mark's rent takes it back, all of it, from the time the Mark names
//!                      (E_EARLY before it; E_MARK for another signer or another account). The account is gone.
//!   5 RecordBatch      relayer(s,w) token key credits(w) crtok(w) plan(w) ledger(w) fee_token(w) mint auth token_program system
//!                      Anyone relays. The token: as for Record (the pinned attest.yml or prove.yml, first attempt, a
//!                      repository of the buyer, credits prepaid for that buyer), with a knosm:batch audience. count
//!                      is 1..=MAX_BATCH, accepted is at most count, month is the chain's month or the one before it
//!                      (E_BATCH), and seq is the Ledger's next_seq (E_SEQ: the same token again, a batch out of
//!                      order). The Ledger is created on first use (rent from the relayer; it is never closed). The
//!                      owner's count of the chain's month goes up by `count` (Plan); the part of the batch above
//!                      FREE_PER_MONTH costs the rate each, from crtok to fee_token, and credits that hold less
//!                      refuse the whole batch (E_FUNDS). The Ledger adds the batch to its totals and its chain.
//!   6 ClaimBatch       relayer(s,w) token key claim(w) system
//!                      Anyone relays. The token: verified as above, from any workflow run in a repository whose
//!                      `repository_owner_id` is the audience's SELLER (E_OWNER), with a knosm:claim audience and the
//!                      same bounds and seq rule. It is the seller's own statement: no pin, no fee, no credits. Writes
//!                      the Ledger at ["lc", ...] exactly as RecordBatch writes the one at ["l", ...].
//!   7 Version
//!                      Logs `knosm:version 1.1`. A client simulates it to learn which build is live.
//!
//! MINT RULES (token.rs). Credits are opened only in Circle's USDC (FEE_MINTS; a test build takes any mint). The
//! mint's owner is SPL Token or Token-2022 and the token program passed is that owner; 2 to 18 decimals; a Token-2022
//! mint may carry only the extensions on the list in token.rs, and any other is refused, among them a transfer hook
//! that only names an authority, Pausable, and ids added later. Withdrawing is never held to these rules.
//!
//! LOGS, one line each, for an indexer (ids and amounts in decimal, addresses in base58, hashes in hex). A statement
//! is recomputed from the knosm:eval lines alone:
//!   knosm:credits owner= authority= mint= wf=           credits were opened, or pinned to another commit
//!   knosm:withdrawn owner= authority= mint= amount=
//!   knosm:plan owner= tier= rate= expiry=
//!   knosm:eval buyer= seller= order= artifact= policy= milestone= verdict= rate= fee= month= n= mint=
//!                                                       a billable evaluation; n: the owner's count this month
//!   knosm:retry buyer= key=                             an evaluation that was billed before: free, not counted
//!   knosm:closed buyer= month= lamports=                a Mark was closed and its rent returned to the relayer that paid it
//!   knosm:batch buyer= seller= month= seq= count= accepted= value= root= billable= fee= n= chain= mint=
//!                                                       a batch was recorded; billable: how many of it cost the rate;
//!                                                       n: the owner's count this month; chain: the running hash after it
//!   knosm:claim buyer= seller= month= seq= count= accepted= value= root= chain=      the seller claimed a batch
//!   knosm:version 1.1
pub mod gh;
pub mod meter;
pub mod state;
pub mod token;

use solana_program::{account_info::AccountInfo, clock::Clock, entrypoint::ProgramResult, program_error::ProgramError, pubkey, pubkey::Pubkey, sysvar::Sysvar};

/// The knos-oidc program whose VERIFIED token accounts this program accepts (programs-v2/program_ids.json).
pub const OIDC_ID: Pubkey = pubkey!("FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W");
/// Fees go to a token account owned by this address (Knos's Squads vault). It also sets Plans, and nothing else.
pub const FEE_OWNER: Pubkey = pubkey!("4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo");
/// The mints credits are opened in: Circle's USDC on devnet and on mainnet. A fee paid in a mint anyone can make
/// would be no fee.
pub const FEE_MINTS: [Pubkey; 2] = [pubkey!("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"), pubkey!("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")];

/// Test builds only (`--features testkeys`): credits open in any mint that passes the mint rules, and SetPlan also
/// takes the ed25519 key of the seed [7; 32] in FEE_OWNER's place. Never deploy a testkeys build.
pub const ANY_MINT: bool = cfg!(feature = "testkeys");
#[cfg(feature = "testkeys")]
pub const TEST_FEE_OWNER: Option<Pubkey> = Some(Pubkey::new_from_array([
    234, 74, 108, 99, 226, 156, 82, 10, 190, 245, 80, 123, 19, 46, 197, 249, 149, 71, 118, 174, 190, 190, 123, 146, 66, 30, 234, 105, 20, 70, 210, 44,
]));
#[cfg(not(feature = "testkeys"))]
pub const TEST_FEE_OWNER: Option<Pubkey> = None;

pub const MICRO: u64 = 1_000_000;         // rates are in millionths of a whole unit of the mint
pub const FEE: u64 = 50_000;              // 0.05 per billable evaluation
pub const PLAN_MIN: u64 = 20_000;         // 0.02: the lowest rate a Plan can set
pub const FREE_PER_MONTH: u64 = 10_000;   // an owner's first billable evaluations of a month cost nothing
pub const TOKEN_AHEAD: i64 = 300;         // a token's `iat` may be this far ahead of the chain's clock (the clock can lag)
pub const TOKEN_LIFE: i64 = 3600;         // a token's `exp` is at most this long after its `iat` (GitHub's is 300 seconds)
pub const MAX_BATCH: u64 = 100_000;       // the most evaluations one batch token carries
pub const VERSION: &str = "1.1";          // what Version logs
pub const MARK_GRACE: i64 = 7200;         // TOKEN_LIFE + the verifier's LATE: how long past a month's end a token issued in it can still be accepted

// errors 61-63 are the claim reader's (knos-oidc-interface); 76-78 are knos-oidc's: the key that verified a token is
// not active yet, has expired, or was revoked (gh.rs)
pub const E_ACCOUNTS: u32 = 110;  // a wrong account, or a missing signature
pub const E_TERMS: u32 = 111;     // owner id, workflow commit, rate or tier not allowed
pub const E_CREDITS: u32 = 112;   // not a Credits account, or the signer is not the wallet that opened it
pub const E_TOKEN: u32 = 113;     // the token is not verified by knos-oidc, not GitHub's, or expired
pub const E_CLAIMS: u32 = 114;    // the token's claims do not allow this: the runner, or a re-run instead of a first run
pub const E_WORKFLOW: u32 = 115;  // the token is not from attest.yml or prove.yml at the commit the Credits account pins
pub const E_AUD: u32 = 116;       // the audience is not a knosm:eval audience
pub const E_OWNER: u32 = 117;     // the run was not in a repository of the buyer, or the credits are another owner's
pub const E_FUNDS: u32 = 118;     // the credits do not hold that much
pub const E_MINT: u32 = 119;      // the mint or the token program is not accepted
pub const E_FEE: u32 = 120;       // fee_token is not a token account of the mint owned by FEE_OWNER, or dest_token not the authority's
pub const E_FEE_OWNER: u32 = 121; // not FEE_OWNER
pub const E_KEY_KIND: u32 = 122;  // the key that verified the token is private, or of a kind this program does not know
pub const E_MARK: u32 = 123;      // not a Mark that can be closed, or the signer is not the relayer that paid its rent
pub const E_EARLY: u32 = 124;     // the Mark cannot be closed yet: its month has not closed, or a token issued in it could still be relayed
pub const E_SEQ: u32 = 125;       // the batch's seq is not the Ledger's next: this token was taken before, or a batch before it is missing
pub const E_BATCH: u32 = 126;     // a batch of no evaluations or of more than MAX_BATCH, more accepted than counted, or a month that is neither this one nor the last

pub fn err(code: u32) -> ProgramError { ProgramError::Custom(code) }

#[cfg(not(feature = "no-entrypoint"))]
solana_program::entrypoint!(process);

#[cfg(not(feature = "no-entrypoint"))]
solana_security_txt::security_txt! {
    name: "knos-meter",
    project_url: "https://github.com/drexthealpha/Knos",
    contacts: "link:https://github.com/drexthealpha/Knos/security/advisories/new",
    policy: "https://github.com/drexthealpha/Knos/blob/main/SECURITY.md",
    source_code: "https://github.com/drexthealpha/Knos"
}

/// A rate (millionths of a whole unit) in the smallest units of a mint with these decimals, rounded down. With two
/// decimals or more (the mint rules) PLAN_MIN is at least two units: a billable evaluation past the free ones never
/// costs nothing.
pub fn fee_units(rate: u64, decimals: u8) -> u64 { (rate as u128 * 10u128.pow(decimals as u32) / MICRO as u128) as u64 }

/// The calendar month of a unix time, UTC, as yyyymm (days to civil date, the usual era arithmetic).
pub fn yyyymm(t: i64) -> u32 {
    let z = t.max(0).div_euclid(86_400) + 719_468;
    let (era, doe) = (z.div_euclid(146_097), z.rem_euclid(146_097));
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    ((yoe + era * 400 + (m <= 2) as i64) * 100 + m) as u32
}

/// The first second of the UTC calendar month after the one `t` is in (civil date to days, the same era arithmetic).
pub fn next_month(t: i64) -> i64 {
    let ym = yyyymm(t) as i64;
    let (y, m) = if ym % 100 == 12 { (ym / 100 + 1, 1) } else { (ym / 100, ym % 100 + 1) };
    let y = y - (m <= 2) as i64;
    let (era, yoe, mp) = (y.div_euclid(400), y.rem_euclid(400), (m + 9) % 12);
    (era * 146_097 + yoe * 365 + yoe / 4 - yoe / 100 + (153 * mp + 2) / 5 - 719_468) * 86_400
}

/// The month before a yyyymm.
pub fn prev_month(ym: u32) -> u32 { if ym % 100 == 1 { ym - 89 } else { ym - 1 } }

pub fn process(program_id: &Pubkey, accounts: &[AccountInfo], data: &[u8]) -> ProgramResult {
    let (&tag, rest) = data.split_first().ok_or(ProgramError::InvalidInstructionData)?;
    let now = Clock::get()?.unix_timestamp;
    match tag {
        0 => meter::open_credits(program_id, accounts, rest),
        1 => meter::withdraw_credits(program_id, accounts, rest),
        2 => meter::set_plan(program_id, accounts, rest),
        3 => meter::record(program_id, accounts, rest, now),
        4 => meter::close_mark(program_id, accounts, rest, now),
        5 => meter::record_batch(program_id, accounts, rest, now),
        6 => meter::claim_batch(program_id, accounts, rest, now),
        7 => meter::version(rest),
        _ => Err(ProgramError::InvalidInstructionData),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_month_is_the_utc_calendar_month() {
        for (t, month) in [(0, 197001), (951_782_399, 200002), (951_782_400, 200002), (951_868_799, 200002), (951_868_800, 200003),   // 29 Feb 2000
                           (1_790_000_000, 202609), (1_790_812_799, 202609), (1_790_812_800, 202610), (1_798_761_599, 202612), (1_798_761_600, 202701),
                           (4_102_444_799, 209912), (4_102_444_800, 210001), (4_107_542_399, 210002), (4_107_542_400, 210003), (-5, 197001)] {  // 2100: no leap day
            assert_eq!(yyyymm(t), month, "{t}");
        }
    }

    #[test]
    fn a_mark_can_be_closed_once_the_month_has_closed_and_its_last_token_has_stopped_working() {
        for (t, next) in [(0, 2_678_400), (-5, 2_678_400), (951_782_399, 951_868_800), (951_782_400, 951_868_800), (951_868_800, 954_547_200),
                          (1_790_812_799, 1_790_812_800), (1_790_812_800, 1_793_491_200), (1_798_761_599, 1_798_761_600), (4_102_444_799, 4_102_444_800),
                          (4_107_542_399, 4_107_542_400)] {
            assert_eq!(next_month(t), next, "{t}");
        }
        // every 11 hours and 7 seconds for 140 years: the month ends where the next one starts, 28 to 31 days on
        let mut t = 0i64;
        while t < 4_420_000_000 {
            let n = next_month(t);
            assert!(n > t && n - t <= 31 * 86_400 && n % 86_400 == 0, "{t}");
            assert!(yyyymm(n - 1) == yyyymm(t) && yyyymm(n) != yyyymm(t) && next_month(n - 1) == n, "{t}");
            t += 40_027;
        }
        assert_eq!(MARK_GRACE, TOKEN_LIFE + knos_oidc_interface::LATE);
    }

    #[test]
    fn the_month_before() {
        assert_eq!((prev_month(202610), prev_month(202701), prev_month(202612), prev_month(197001)), (202609, 202612, 202611, 196912));
    }

    #[test]
    fn the_prices_are_the_price_books() {
        assert_eq!((FEE, PLAN_MIN, FREE_PER_MONTH), (50_000, 20_000, 10_000));
        assert_eq!((fee_units(FEE, 6), fee_units(PLAN_MIN, 6), fee_units(25_000, 6)), (50_000, 20_000, 25_000));
        assert_eq!((fee_units(FEE, 2), fee_units(PLAN_MIN, 2), fee_units(25_000, 2)), (5, 2, 2));
        assert_eq!((fee_units(FEE, 9), fee_units(FEE, 18)), (50_000_000, 50_000_000_000_000_000));
        assert!(fee_units(PLAN_MIN, token::MIN_DECIMALS) >= 1);
        assert!(!FEE_MINTS.contains(&Pubkey::default()) && TEST_FEE_OWNER.is_none() != ANY_MINT);
    }
}
