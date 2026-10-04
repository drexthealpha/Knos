//! Fund and read a Knos work order from another Solana program.
//!
//! knos_pay holds a work order's money in escrow and pays it when GitHub signs that the order's terms were met
//! (the token is verified on chain by knos-oidc). This crate is what a program needs to be a FUNDER by CPI: the
//! program ids, the addresses, the three instructions a funder sends (FundOrderWallet, TopUp, RefundOrder) and a
//! reader of the Order account. It depends on solana-program and nothing else, and none of knos_pay's code.
//!
//! The funder of an order is whoever signs FundOrderWallet. When that is a PDA of your program (a treasury), your
//! program signs with `invoke_signed`; the order then refunds to a token account of that PDA and nowhere else, and
//! its rent comes back to the PDA. The PDA must be a plain system account (no data): it pays the rent of the order.
//!
//! ```ignore
//! use knos_pay_interface as knos;
//! let f = knos::FundOrder { repo_id, issue, amount, wf_repo: knos::wf_repo_hash("drexthealpha/Knos"), wf_sha, ..Default::default() };
//! let ix = knos::fund_order_wallet(&knos::ID, treasury.key, treasury_token.key, mint.key, token_program.key, &f, terms_json);
//! invoke_signed(&ix, &[treasury, order, ov, treasury_token, mint, auth, token_program, system, pause], &[&[b"treasury", &[bump]]])?;
//! let o = knos::Order::read(order.key, order.owner, &order.try_borrow_data()?, &knos::ID).ok_or(MyError::Order)?;
//! assert!(o.amount == amount && o.refund_to == *treasury.key);
//! ```
//!
//! The bytes this crate writes are checked against the Python client's (src/knos/settle/v2/pay.py) through
//! tests/fixtures/pay_interface.json, which scripts/pay_interface_fixture.py generates; the Order in it is one the
//! test build of knos_pay wrote.
use solana_program::{
    hash::hashv,
    instruction::{AccountMeta, Instruction},
    pubkey,
    pubkey::Pubkey,
    system_program,
};

/// knos_pay, the second deployment (devnet). Upgradeable only through a multisig with a public 48-hour delay, until
/// an outside review. Every function here takes the program's id, so another cluster is another argument.
pub const ID: Pubkey = pubkey!("5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k");
pub const ID_STR: &str = "5y7iWJ1VAMJjnnWbbdo2a2PsWJEwTExSNpzrvQSEnS8k";
/// Fees go to a token account owned by this address. It has no other power.
pub const FEE_OWNER: Pubkey = pubkey!("4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo");
pub const TOKEN: Pubkey = pubkey!("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA");
pub const TOKEN_2022: Pubkey = pubkey!("TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb");
pub const ATA_PROGRAM: Pubkey = pubkey!("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL");
/// Circle's USDC: the only mints the public record counts as real money.
pub const USDC_DEVNET: Pubkey = pubkey!("4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU");
pub const USDC_MAINNET: Pubkey = pubkey!("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v");

// Prices and bounds, in millionths of ONE WHOLE UNIT of the mint (`units` turns them into the mint's smallest units).
pub const FEE_BPS: u64 = 250;
pub const ORDER_FEE_MIN: u64 = 400_000;
pub const ORDER_FEE_MAX: u64 = 25_000_000;
pub const ORDER_MIN_AMOUNT: u64 = 5_000_000;
pub const MAX_AMOUNT: u64 = 500_000_000;
pub const MIN_WORK: i64 = 60;
pub const MAX_WORK: i64 = 90 * 86_400;
pub const MAX_TERMS: usize = 600;

pub const MERGE: u8 = 0; // mode: paid when the pull request that closes the issue is merged with the funded checks green
pub const TESTS: u8 = 1; // mode: paid when the funded acceptance tests pass at the merged commit
pub const OPEN: u8 = 1; // states
pub const HELD: u8 = 3;
pub const WARRANTY: u8 = 4;
pub const F_FAUCET: u8 = 1; // flags; the program sets FAUCET and TOKEN2022, the funder the others (Opts)
pub const F_PRIVATE: u8 = 2;
pub const F_NEUTRAL: u8 = 4;
pub const F_STANDING: u8 = 8;
pub const F_TOKEN2022: u8 = 16;
pub const ORDER_LEN: usize = 512;
pub const OPTS_LEN: usize = 48;

/// `micro` millionths of one whole unit of a mint with `decimals` decimals, in the mint's smallest units.
pub fn units(micro: u64, decimals: u8) -> u64 {
    if micro == 0 { return 0; }
    let v = match 10u128.checked_pow(decimals as u32) { Some(p) => (micro as u128).saturating_mul(p) / 1_000_000, None => u128::MAX };
    v.min(u64::MAX as u128) as u64
}
/// The fee a funder pays ON TOP of an order's amount: `bps` of it (FEE_BPS for a wallet's order), at least
/// ORDER_FEE_MIN and at most ORDER_FEE_MAX of a whole unit. FundOrderWallet moves amount + order_fee(amount).
pub fn order_fee(amount: u64, bps: u64, decimals: u8) -> u64 {
    (amount / 10_000 * bps + amount % 10_000 * bps / 10_000).max(units(ORDER_FEE_MIN, decimals)).min(units(ORDER_FEE_MAX, decimals))
}

/// sha256 of the terms JSON: what the order stores and a pay token must carry.
pub fn terms_hash(json: &[u8]) -> [u8; 32] { hashv(&[json]).to_bytes() }
/// sha256 of "owner/name": the repository that holds the workflows an order pins.
pub fn wf_repo_hash(repository: &str) -> [u8; 32] { hashv(&[repository.as_bytes()]).to_bytes() }
/// The scope of a public order: sha256("knos3:scope" || repo id || issue).
pub fn scope(repo_id: u64, issue: u64) -> [u8; 32] { hashv(&[b"knos3:scope", &repo_id.to_le_bytes(), &issue.to_le_bytes()]).to_bytes() }
/// The scope of a private order: sha256(salt || repo id || issue); the salt stays off chain.
pub fn private_scope(salt: &[u8; 32], repo_id: u64, issue: u64) -> [u8; 32] { hashv(&[salt, &repo_id.to_le_bytes(), &issue.to_le_bytes()]).to_bytes() }

/// ["auth"]: owns every token account of the program. Only the program signs for it.
pub fn auth(program: &Pubkey) -> Pubkey { Pubkey::find_program_address(&[b"auth"], program).0 }
/// ["pause"]: new funding is refused until the time in it. FundOrderWallet and TopUp take it; it need not exist.
pub fn pause(program: &Pubkey) -> Pubkey { Pubkey::find_program_address(&[b"pause"], program).0 }
/// ["ord", scope, source, seq]: `source` is the funding wallet (or PDA); `seq` is the funder's own counter, so one
/// funder can fund an issue more than once.
pub fn order(program: &Pubkey, scope: &[u8; 32], source: &Pubkey, seq: u32) -> Pubkey {
    Pubkey::find_program_address(&[b"ord", scope, source.as_ref(), &seq.to_le_bytes()], program).0
}
/// ["ov", order]: the token account that holds one order's money and nothing else.
pub fn ov(program: &Pubkey, order: &Pubkey) -> Pubkey { Pubkey::find_program_address(&[b"ov", order.as_ref()], program).0 }
/// The associated token account of `owner` for `mint` (an owner off the curve, a PDA, has one too).
pub fn ata(owner: &Pubkey, mint: &Pubkey, token_program: &Pubkey) -> Pubkey {
    Pubkey::find_program_address(&[owner.as_ref(), token_program.as_ref(), mint.as_ref()], &ATA_PROGRAM).0
}

/// What a funder fixes beside the amount and the terms (48 bytes on the wire). Limits: holdback_bps <= 5000 and only
/// with a warranty, warranty_days <= 90, kill_bps <= 2000; a STANDING order has a rate in 1..=amount, any other none.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Opts {
    pub flags: u8, pub holdback_bps: u16, pub warranty_days: u16, pub kill_bps: u16, pub reserve_days: u8, pub rate: u64, pub arbiter_id: u64,
    pub judge_repo_id: u64, pub salted: bool,
}
impl Opts {
    pub fn to_bytes(&self) -> [u8; OPTS_LEN] {
        let mut o = [0u8; OPTS_LEN];
        o[0] = self.flags;
        o[1..3].copy_from_slice(&self.holdback_bps.to_le_bytes());
        o[3..5].copy_from_slice(&self.warranty_days.to_le_bytes());
        o[5..7].copy_from_slice(&self.kill_bps.to_le_bytes());
        o[7] = self.reserve_days;
        o[8..16].copy_from_slice(&self.rate.to_le_bytes());
        o[16..24].copy_from_slice(&self.arbiter_id.to_le_bytes());
        o[24..32].copy_from_slice(&self.judge_repo_id.to_le_bytes());
        o[32] = self.salted as u8;
        o
    }
}

/// An order to fund. `amount` is what the payees receive (the fee comes on top); `work_s` is how long the order
/// stays open before it can be refunded; `wf_repo` and `wf_sha` pin the workflows whose signed run can pay it.
/// A PRIVATE order: `opts` with F_PRIVATE and `salted`, `private_scope` set, `repo_id` and `issue` 0, and the
/// `terms` passed to `fund_order_wallet` are the 32-byte terms hash instead of the JSON.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FundOrder {
    pub repo_id: u64, pub issue: u64, pub amount: u64, pub mode: u8, pub work_s: i64, pub seq: u32, pub opts: Opts, pub wf_repo: [u8; 32],
    pub wf_sha: [u8; 40], pub private_scope: Option<[u8; 32]>,
}
impl Default for FundOrder {
    fn default() -> Self {
        FundOrder { repo_id: 0, issue: 0, amount: 0, mode: MERGE, work_s: 14 * 86_400, seq: 0, opts: Opts::default(), wf_repo: [0; 32], wf_sha: [b'0'; 40],
                    private_scope: None }
    }
}
impl FundOrder {
    pub fn scope(&self) -> [u8; 32] { self.private_scope.unwrap_or_else(|| scope(self.repo_id, self.issue)) }
    /// The address of the order this funds from `funder`.
    pub fn address(&self, program: &Pubkey, funder: &Pubkey) -> Pubkey { order(program, &self.scope(), funder, self.seq) }
}

/// 15 FundOrderWallet. Accounts: funder(s,w) order(w) ov(w) funder_token(w) mint auth token_program system pause.
/// Moves amount + order_fee(amount) from `funder_token` to the order's own token account and creates both; the
/// funder pays their rent and gets it back when the order closes.
pub fn fund_order_wallet(program: &Pubkey, funder: &Pubkey, funder_token: &Pubkey, mint: &Pubkey, token_program: &Pubkey, f: &FundOrder,
                         terms: &[u8]) -> Instruction {
    let order = f.address(program, funder);
    let mut data = Vec::with_capacity(190 + terms.len());
    data.push(15);
    data.extend_from_slice(&f.issue.to_le_bytes());
    data.extend_from_slice(&f.repo_id.to_le_bytes());
    data.extend_from_slice(&f.amount.to_le_bytes());
    data.push(f.mode);
    data.extend_from_slice(&f.work_s.to_le_bytes());
    data.extend_from_slice(&f.seq.to_le_bytes());
    data.extend_from_slice(&f.opts.to_bytes());
    data.extend_from_slice(&f.wf_repo);
    data.extend_from_slice(&f.wf_sha);
    if let Some(s) = &f.private_scope { data.extend_from_slice(s); }
    data.extend_from_slice(terms);
    Instruction { program_id: *program, data, accounts: vec![
        AccountMeta::new(*funder, true), AccountMeta::new(order, false), AccountMeta::new(ov(program, &order), false),
        AccountMeta::new(*funder_token, false), AccountMeta::new_readonly(*mint, false), AccountMeta::new_readonly(auth(program), false),
        AccountMeta::new_readonly(*token_program, false), AccountMeta::new_readonly(system_program::ID, false),
        AccountMeta::new_readonly(pause(program), false),
    ] }
}

/// 23 TopUp. Accounts: signer(s,w) order(w) ov(w) from_token(w) balance mint auth token_program pause. Adds `add` to
/// an open order's amount, and the fee on the new amount less the fee already there. `signer` is the order's
/// source (the funding wallet or PDA); `from_token`: a token account of it (default: its associated token account).
pub fn top_up(program: &Pubkey, signer: &Pubkey, order: &Pubkey, o: &Order, add: u64, from_token: Option<&Pubkey>) -> Instruction {
    let tp = o.token_program();
    let from = match from_token { Some(k) => *k, None if o.from_balance => o.refund_to, None => ata(&o.source, &o.mint, &tp) };
    let mut data = vec![23];
    data.extend_from_slice(&add.to_le_bytes());
    Instruction { program_id: *program, data, accounts: vec![
        AccountMeta::new(*signer, true), AccountMeta::new(*order, false), AccountMeta::new(ov(program, order), false), AccountMeta::new(from, false),
        AccountMeta::new_readonly(o.source, false), AccountMeta::new_readonly(o.mint, false), AccountMeta::new_readonly(auth(program), false),
        AccountMeta::new_readonly(tp, false), AccountMeta::new_readonly(pause(program), false),
    ] }
}

/// 22 RefundOrder. Accounts: relayer(s,w) order(w) ov(w) refund_token(w) auth rent_to(w) mint token_program. Anyone
/// sends it and no token is needed: an open order past its deadline (or a held one past its hold) gives everything
/// it holds back to a token account of its funder (default: the funder's associated token account).
pub fn refund_order(program: &Pubkey, relayer: &Pubkey, order: &Pubkey, o: &Order, refund_token: Option<&Pubkey>) -> Instruction {
    let tp = o.token_program();
    let dest = match refund_token { Some(k) => *k, None if o.from_balance => o.refund_to, None => ata(&o.refund_to, &o.mint, &tp) };
    Instruction { program_id: *program, data: vec![22], accounts: vec![
        AccountMeta::new(*relayer, true), AccountMeta::new(*order, false), AccountMeta::new(ov(program, order), false), AccountMeta::new(dest, false),
        AccountMeta::new_readonly(auth(program), false), AccountMeta::new(o.rent_to, false), AccountMeta::new_readonly(o.mint, false),
        AccountMeta::new_readonly(tp, false),
    ] }
}

/// A work order as knos_pay stores it (512 bytes, version 2). An order that was paid out or refunded is gone.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Order {
    pub state: u8, pub mode: u8, pub from_balance: bool, pub flags: u8, pub bump: u8, pub decimals: u8, pub reserve_days: u8, pub repo_id: u64,
    pub issue: u64, pub scope: [u8; 32], pub seq: u32, pub holdback_bps: u16, pub kill_bps: u16, pub amount: u64, pub fee: u64, pub rate: u64,
    pub paid: u64, pub deadline: i64, pub not_before: i64, pub hold_until: i64, pub warranty_s: i64, pub reserved_by: u64, pub reserved_until: i64,
    pub cancel_at: i64, pub payee_id: u64, pub funder_id: u64, pub owner_id: u64, pub arbiter_id: u64, pub judge_repo_id: u64, pub source: Pubkey,
    pub refund_to: Pubkey, pub rent_to: Pubkey, pub mint: Pubkey, pub terms: [u8; 32], pub wf_repo: [u8; 32], pub wf_sha: [u8; 40], pub fee_bps: u16,
}
impl Order {
    /// The order's fields, with no check of where the bytes came from: only their length and version.
    pub fn parse(d: &[u8]) -> Option<Order> {
        if d.len() != ORDER_LEN || d[0] != 2 { return None; }
        let u16_at = |o: usize| u16::from_le_bytes([d[o], d[o + 1]]);
        let u64_at = |o: usize| u64::from_le_bytes(d[o..o + 8].try_into().unwrap());
        let i64_at = |o: usize| i64::from_le_bytes(d[o..o + 8].try_into().unwrap());
        let key = |o: usize| Pubkey::new_from_array(d[o..o + 32].try_into().unwrap());
        Some(Order {
            state: d[1], mode: d[2], from_balance: d[3] == 1, flags: d[4], bump: d[5], decimals: d[6], reserve_days: d[7], repo_id: u64_at(8),
            issue: u64_at(16), scope: d[24..56].try_into().unwrap(), seq: u32::from_le_bytes(d[56..60].try_into().unwrap()), holdback_bps: u16_at(60),
            kill_bps: u16_at(62), amount: u64_at(64), fee: u64_at(72), rate: u64_at(80), paid: u64_at(88), deadline: i64_at(96), not_before: i64_at(104),
            hold_until: i64_at(112), warranty_s: i64_at(120), reserved_by: u64_at(128), reserved_until: i64_at(136), cancel_at: i64_at(144),
            payee_id: u64_at(152), funder_id: u64_at(160), owner_id: u64_at(168), arbiter_id: u64_at(176), judge_repo_id: u64_at(184), source: key(192),
            refund_to: key(224), rent_to: key(256), mint: key(288), terms: d[320..352].try_into().unwrap(), wf_repo: d[352..384].try_into().unwrap(),
            wf_sha: d[384..424].try_into().unwrap(), fee_bps: u16_at(424),
        })
    }
    /// An order read ON CHAIN from an account another program was handed: the account's owner is `program`, and
    /// its address is the one its own fields derive, so nothing else can pass for an order.
    pub fn read(address: &Pubkey, owner: &Pubkey, data: &[u8], program: &Pubkey) -> Option<Order> {
        if owner != program { return None; }
        let o = Order::parse(data)?;
        let at = Pubkey::create_program_address(&[b"ord", &o.scope, o.source.as_ref(), &o.seq.to_le_bytes(), &[o.bump]], program).ok()?;
        if at == *address { Some(o) } else { None }
    }
    pub fn is(&self, flag: u8) -> bool { self.flags & flag != 0 }
    pub fn token_program(&self) -> Pubkey { if self.is(F_TOKEN2022) { TOKEN_2022 } else { TOKEN } }
    pub fn address(&self, program: &Pubkey) -> Pubkey { order(program, &self.scope, &self.source, self.seq) }
    /// Whether RefundOrder would be accepted at `now`: open past the deadline, or held past the hold.
    pub fn refundable(&self, now: i64) -> bool { (self.state == OPEN && now > self.deadline) || (self.state == HELD && now > self.hold_until) }
}
