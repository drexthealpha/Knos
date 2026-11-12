//! A yes/no claim market for one Knos claim, priced by Hanson's logarithmic market scoring rule (LMSR).
//!
//! Each market follows one milestone of the Knos contract (`source`, e.g. knos-pay-1103.testnet): the claim's test is
//! the milestone's criteria hash, locked when it was funded, and the milestone is released only by its named GitHub
//! Actions workflow's own OIDC token. The market settles from that milestone's state and nothing else: Released means
//! Yes, Refunded (the deadline passed with no passing run) means No. No vote, no owner and no edit can settle it.
//!
//! Price (token units, 6 decimals; b = 100 test tokens = 100_000_000 units, seeded by Knos):
//!   cost C(q_yes, q_no) = b * ln(e^(q_yes / b) + e^(q_no / b))
//!   price of Yes        = e^(q_yes / b) / (e^(q_yes / b) + e^(q_no / b)), shown in cents ("Yes 62c")
//!   a buy of Yes for c  : the new q_yes solves C(q_yes', q_no) - C(q_yes, q_no) = c
//!                         q_yes' = b * ln(e^(c / b) * (e^(q_yes / b) + e^(q_no / b)) - e^(q_no / b))
//! Each winning share pays 1 unit. Knos's worst-case loss is the seed, b * ln 2 (about 69.31 test tokens).
//!
//! Two kinds of market follow a claim. The truth market ("job:<id>") settles from the claim's job: Yes when the agent
//! whose output passed the claim's locked test was paid. The demand market ("demand:<claim>:<opened, unix seconds>")
//! asks whether at least 100 test tokens are put behind proving the claim within 7 days of the market opening: anyone
//! puts tokens behind a claim by sending them here (msg "back"), which records them on chain and passes them on to the
//! agent and the fee account named, so the demand market settles from this contract's own record and nothing else.
//! The split is the contract's rule, not the sender's: 90% to the agent whose work passed, 10% to Knos (amount / 10,
//! rounded down; the agent gets the rest), so every receipt on NEAR shows exactly that split.
//! Each market counts its traders (accounts that bought, from this version on), so a thin market says it is thin.

use near_contract_standards::fungible_token::core::ext_ft_core;
use near_contract_standards::fungible_token::receiver::FungibleTokenReceiver;
use near_sdk::json_types::U128;
use near_sdk::store::{IterableMap, LookupMap};
use near_sdk::{env, near, require, AccountId, Gas, NearToken, PanicOnDefault, Promise, PromiseError, PromiseOrValue};

pub const B: u128 = 100_000_000; // 100 test tokens at 6 decimals
pub const SEED_MIN: u128 = 69_314_719; // b * ln 2, rounded up
const GAS: Gas = Gas::from_tgas(15);
pub const JOBS: &str = "jobs.knos-swarm-1105.testnet"; // the jobs contract a "job:" market follows
pub const DEMAND: u128 = 100_000_000; // a demand market's bar: 100 test tokens behind proving the claim
pub const WEEK: u64 = 7 * 24 * 3600; // within 7 days of the demand market opening

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug)]
pub struct Market {
    pub id: String,
    pub question: String,
    pub b: U128,
    pub q_yes: U128,
    pub q_no: U128,
    /// the seed plus every buy: what the market holds to pay the winning shares
    pub pool: U128,
    /// None while the locked check has not run; Some(true) = Yes won
    pub outcome: Option<bool>,
    pub trades: u32,
}

#[near(serializers = [json])]
pub struct View {
    pub market: Market,
    /// the price of Yes in millionths of a token (1_000_000 = $1.00, so cents = price / 10_000)
    pub yes_price: U128,
    pub no_price: U128,
}

#[near(serializers = [json])]
#[derive(Default)]
pub struct Holding {
    pub yes: U128,
    pub no: U128,
}

#[near(serializers = [json])]
pub enum Msg {
    /// Knos (the owner) opens a market on a milestone of `source` with its seed
    #[serde(rename = "seed")]
    Seed { id: String, question: String },
    /// anyone buys Yes or No with the tokens sent
    #[serde(rename = "buy")]
    Buy { id: String, side: String },
    /// anyone puts the tokens sent behind proving a claim: recorded here, then passed on in full to the accounts named
    #[serde(rename = "back")]
    Back { claim: String, to: Vec<(AccountId, U128)> },
}

#[near(serializers = [json])]
pub struct Backed {
    /// the tokens put behind the claim in the window asked
    pub total: U128,
    /// how many times tokens were put behind it in that window
    pub count: u32,
}

/// Records kept beside the contract's state (their own storage prefixes), so the state written by the first version
/// still reads: every time tokens were put behind a claim (unix seconds, amount), and each market's trader count.
fn backs() -> LookupMap<String, Vec<(u64, u128)>> {
    LookupMap::new(b"k")
}
fn traders() -> LookupMap<String, u32> {
    LookupMap::new(b"t")
}

/// "demand:<claim>:<opened>" gives (claim, opened).
fn demand_of(id: &str) -> Option<(String, u64)> {
    let rest = id.strip_prefix("demand:")?;
    let (claim, opened) = rest.rsplit_once(':')?;
    Some((claim.to_string(), opened.parse().ok()?))
}

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Contract {
    owner: AccountId,
    token: AccountId,
    source: AccountId,
    markets: IterableMap<String, Market>,
    holdings: LookupMap<String, (u128, u128)>,
}

fn key(id: &str, who: &AccountId) -> String {
    format!("{id}|{who}")
}

/// q_side after a buy of `c` units on that side, by the LMSR cost function (log-sum-exp kept stable).
pub fn after_buy(q_side: u128, q_other: u128, b: u128, c: u128) -> u128 {
    let (qs, qo, b, c) = (q_side as f64, q_other as f64, b as f64, c as f64);
    let m = qs.max(qo) / b;
    let (es, eo) = ((qs / b - m).exp(), (qo / b - m).exp());
    let e = (c / b).exp() * (es + eo) - eo;
    let q = b * (m + e.ln());
    if q.is_finite() && q > qs { q.floor() as u128 } else { q_side }
}

/// The price of Yes in millionths of a token.
pub fn yes_price(q_yes: u128, q_no: u128, b: u128) -> u128 {
    let d = (q_no as f64 - q_yes as f64) / b as f64;
    (1_000_000.0 / (1.0 + d.exp())).round() as u128
}

#[near]
impl Contract {
    #[init]
    pub fn new(token: AccountId, source: AccountId, owner: AccountId) -> Self {
        Self { owner, token, source, markets: IterableMap::new(b"m"), holdings: LookupMap::new(b"h") }
    }

    pub fn get_market(&self, id: String) -> Option<View> {
        self.markets.get(&id).map(|m| {
            let p = yes_price(m.q_yes.0, m.q_no.0, m.b.0);
            View { market: m.clone(), yes_price: U128(p), no_price: U128(1_000_000 - p) }
        })
    }

    pub fn get_markets(&self) -> Vec<String> {
        self.markets.keys().cloned().collect()
    }

    /// The tokens put behind a claim between two times (unix seconds, inclusive).
    pub fn get_backed(&self, claim: String, from: u64, until: u64) -> Backed {
        let mut out = Backed { total: U128(0), count: 0 };
        for (at, amount) in backs().get(&claim).map(|v| v.as_slice()).unwrap_or(&[]) {
            if *at >= from && *at <= until {
                out.total = U128(out.total.0 + amount);
                out.count += 1;
            }
        }
        out
    }

    /// Every time tokens were put behind a claim, oldest first: (unix seconds, amount), `limit` from `from_index`.
    pub fn get_backs(&self, claim: String, from_index: u32, limit: u32) -> Vec<(u64, U128)> {
        backs().get(&claim).map(|v| v.iter().skip(from_index as usize).take(limit.min(500) as usize).map(|(t, a)| (*t, U128(*a))).collect()).unwrap_or_default()
    }

    /// How many accounts bought in a market (counted from the version that added this count).
    pub fn get_traders(&self, id: String) -> u32 {
        traders().get(&id).copied().unwrap_or(0)
    }

    pub fn get_holding(&self, id: String, account: AccountId) -> Holding {
        self.holdings.get(&key(&id, &account)).map(|h| Holding { yes: U128(h.0), no: U128(h.1) }).unwrap_or_default()
    }

    /// Settles the market from the chain: anyone may send it; the answer is the chain's, not the sender's. A demand
    /// market settles here from this contract's record of the tokens put behind its claim.
    pub fn resolve(&mut self, id: String) -> PromiseOrValue<String> {
        let m = self.markets.get(&id).unwrap_or_else(|| env::panic_str("no such market"));
        require!(m.outcome.is_none(), "this market is already settled");
        if let Some((claim, opened)) = demand_of(&id) {
            let now = env::block_timestamp() / 1_000_000_000;
            let until = opened + WEEK;
            let got = self.get_backed(claim.clone(), opened, until.min(now));
            let yes = if got.total.0 >= DEMAND {
                true
            } else if now > until {
                false
            } else {
                env::panic_str(&format!("not settled yet: {} of {} behind {claim}, {} s left", got.total.0, DEMAND, until - now))
            };
            let mut m = m.clone();
            m.outcome = Some(yes);
            self.markets.insert(id.clone(), m);
            return PromiseOrValue::Value(format!("{id} settled {} by the record: {} put behind {claim} {} times", if yes { "Yes" } else { "No" }, got.total.0, got.count));
        }
        // "job:<id>" follows a job of the jobs contract (paid only to the helper whose output passed its locked test);
        // any other id follows a milestone of `source` (released only by its named workflow's own token)
        let (to, method, key) = match id.strip_prefix("job:") {
            Some(job) => (JOBS.parse::<AccountId>().unwrap_or_else(|_| env::panic_str("jobs")), "get_job", job.to_string()),
            None => (self.source.clone(), "get_milestone", id.clone()),
        };
        PromiseOrValue::Promise(
            Promise::new(to)
                .function_call(method.to_string(), serde_json::json!({ "id": key }).to_string().into_bytes(), NearToken::from_yoctonear(0), GAS)
                .then(Self::ext(env::current_account_id()).with_static_gas(GAS).on_resolve(id)),
        )
    }

    #[private]
    pub fn on_resolve(&mut self, id: String, #[callback_result] r: Result<Option<serde_json::Value>, PromiseError>) -> String {
        let ms = r.ok().flatten().unwrap_or_else(|| env::panic_str("the milestone could not be read"));
        let state = ms.get("state").and_then(|s| s.as_str()).unwrap_or("");
        let yes = match state {
            "Released" | "Paid" => true,
            "Refunded" => false,
            _ => env::panic_str(&format!("not settled: the locked check has not run (it is {state})")),
        };
        let mut m = self.markets.get(&id).cloned().unwrap_or_else(|| env::panic_str("no such market"));
        m.outcome = Some(yes);
        self.markets.insert(id.clone(), m);
        format!("{id} settled {} by its locked check ({state})", if yes { "Yes" } else { "No" })
    }

    /// Pays the caller's winning shares, 1 unit each.
    pub fn redeem(&mut self, id: String) -> Promise {
        let who = env::predecessor_account_id();
        let mut m = self.markets.get(&id).cloned().unwrap_or_else(|| env::panic_str("no such market"));
        let yes = m.outcome.unwrap_or_else(|| env::panic_str("not settled yet: the locked check has not run"));
        let k = key(&id, &who);
        let h = self.holdings.get(&k).copied().unwrap_or((0, 0));
        let pay = if yes { h.0 } else { h.1 };
        require!(pay > 0, "no winning shares to pay");
        require!(pay <= m.pool.0, "the pool is short");
        m.pool = U128(m.pool.0 - pay);
        self.markets.insert(id.clone(), m);
        self.holdings.insert(k, if yes { (0, h.1) } else { (h.0, 0) });
        ext_ft_core::ext(self.token.clone())
            .with_attached_deposit(NearToken::from_yoctonear(1))
            .with_static_gas(GAS)
            .ft_transfer(who, U128(pay), Some(format!("knos market {id}: winning shares")))
    }

    /// Refused, always: the market settles only by its locked check.
    pub fn vote(&mut self, id: String, outcome: bool) {
        let _ = (id, outcome);
        env::panic_str("refused: this market settles only by its locked check, never by vote");
    }

    /// Refused, always: the claim's test is the criteria hash locked when its milestone was funded.
    pub fn set_test(&mut self, id: String, criteria_hash: String) {
        let _ = (id, criteria_hash);
        env::panic_str("refused: the test is locked at funding and no one can change it");
    }
}

#[near]
impl FungibleTokenReceiver for Contract {
    fn ft_on_transfer(&mut self, sender_id: AccountId, amount: U128, msg: String) -> PromiseOrValue<U128> {
        require!(env::predecessor_account_id() == self.token, "only the configured test token");
        let msg: Msg = serde_json::from_str(&msg).unwrap_or_else(|_| env::panic_str("msg: seed or buy"));
        match msg {
            Msg::Seed { id, question } => {
                require!(sender_id == self.owner, "only Knos seeds a market");
                require!(!id.is_empty() && id.len() <= 64 && question.len() <= 200, "id and question");
                require!(!self.markets.contains_key(&id), "this market exists");
                require!(amount.0 >= SEED_MIN, "the seed must cover b * ln 2");
                let m = Market { id: id.clone(), question, b: U128(B), q_yes: U128(0), q_no: U128(0), pool: amount, outcome: None, trades: 0 };
                self.markets.insert(id, m);
            }
            Msg::Buy { id, side } => {
                let mut m = self.markets.get(&id).cloned().unwrap_or_else(|| env::panic_str("no such market"));
                require!(m.outcome.is_none(), "this market is settled");
                require!(amount.0 >= 10_000, "the smallest buy is 0.01 test token");
                let yes = match side.as_str() { "yes" => true, "no" => false, _ => env::panic_str("side: yes or no") };
                let k = key(&id, &sender_id);
                let h = self.holdings.get(&k).copied().unwrap_or((0, 0));
                if h == (0, 0) {
                    let mut t = traders();
                    let n = t.get(&id).copied().unwrap_or(0);
                    t.insert(id.clone(), n + 1);
                }
                if yes {
                    let q = after_buy(m.q_yes.0, m.q_no.0, m.b.0, amount.0);
                    self.holdings.insert(k, (h.0 + (q - m.q_yes.0), h.1));
                    m.q_yes = U128(q);
                } else {
                    let q = after_buy(m.q_no.0, m.q_yes.0, m.b.0, amount.0);
                    self.holdings.insert(k, (h.0, h.1 + (q - m.q_no.0)));
                    m.q_no = U128(q);
                }
                m.pool = U128(m.pool.0 + amount.0);
                m.trades += 1;
                self.markets.insert(id, m);
            }
            Msg::Back { claim, to } => {
                require!(!claim.is_empty() && claim.len() <= 64, "claim");
                require!(to.len() == 2, "to: the agent, then Knos");
                let sum = to.iter().try_fold(0u128, |s, (_, a)| s.checked_add(a.0)).unwrap_or_else(|| env::panic_str("amounts"));
                require!(sum == amount.0, "the amounts named must add up to the tokens sent");
                let fee = amount.0 / 10;
                require!(to[1].1 .0 == fee && to[0].1 .0 == amount.0 - fee, "a proof pays 90% to the agent and 10% to Knos");
                let now = env::block_timestamp() / 1_000_000_000;
                let mut b = backs();
                let mut v = b.get(&claim).cloned().unwrap_or_default();
                v.push((now, amount.0));
                b.insert(claim.clone(), v);
                for (who, a) in to {
                    if a.0 > 0 {
                        // sent when this call ends (a promise runs once it is dropped)
                        let _ = ext_ft_core::ext(self.token.clone())
                            .with_attached_deposit(NearToken::from_yoctonear(1))
                            .with_static_gas(GAS)
                            .ft_transfer(who, a, Some(format!("knos: put behind {claim}")));
                    }
                }
            }
        }
        PromiseOrValue::Value(U128(0))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use near_sdk::test_utils::VMContextBuilder;
    use near_sdk::testing_env;

    fn at(who: &str, secs: u64) {
        testing_env!(VMContextBuilder::new()
            .predecessor_account_id("token.testnet".parse().unwrap())
            .current_account_id("market.testnet".parse().unwrap())
            .block_timestamp(secs * 1_000_000_000)
            .signer_account_id(who.parse().unwrap())
            .build());
    }

    fn c() -> Contract {
        at("knos.testnet", 1_000);
        Contract::new("token.testnet".parse().unwrap(), "src.testnet".parse().unwrap(), "knos.testnet".parse().unwrap())
    }

    fn send(k: &mut Contract, from: &str, amount: u128, msg: serde_json::Value) {
        let _ = k.ft_on_transfer(from.parse().unwrap(), U128(amount), msg.to_string());
    }

    #[test]
    fn backing_is_recorded_and_must_add_up() {
        let mut k = c();
        at("buyer.testnet", 2_000);
        send(&mut k, "buyer.testnet", 10_000_000, serde_json::json!({"back": {"claim": "jump", "to": [["agent.testnet", "9000000"], ["fee.testnet", "1000000"]]}}));
        let b = k.get_backed("jump".into(), 0, 10_000);
        assert_eq!((b.total.0, b.count), (10_000_000, 1));
        assert_eq!(k.get_backed("jump".into(), 3_000, 10_000).count, 0);
        assert_eq!(k.get_backs("jump".into(), 0, 10).iter().map(|(t, a)| (*t, a.0)).collect::<Vec<_>>(), vec![(2_000, 10_000_000)]);
    }

    #[test]
    #[should_panic(expected = "add up")]
    fn backing_that_does_not_add_up_is_refused() {
        let mut k = c();
        send(&mut k, "buyer.testnet", 10_000_000, serde_json::json!({"back": {"claim": "jump", "to": [["agent.testnet", "1"], ["fee.testnet", "1"]]}}));
    }

    #[test]
    #[should_panic(expected = "90% to the agent and 10% to Knos")]
    fn any_split_but_ninety_ten_is_refused() {
        let mut k = c();
        send(&mut k, "buyer.testnet", 3_000_000, serde_json::json!({"back": {"claim": "jump", "to": [["agent.testnet", "60000"], ["fee.testnet", "2940000"]]}}));
    }

    #[test]
    fn three_test_usdc_pay_2_70_to_the_agent_and_0_30_to_knos() {
        let mut k = c();
        send(&mut k, "buyer.testnet", 3_000_000, serde_json::json!({"back": {"claim": "jump", "to": [["agent.testnet", "2700000"], ["fee.testnet", "300000"]]}}));
        assert_eq!(k.get_backed("jump".into(), 0, u64::MAX).total.0, 3_000_000);
    }

    #[test]
    fn a_demand_market_settles_yes_at_100_and_no_after_7_days() {
        let mut k = c();
        send(&mut k, "knos.testnet", SEED_MIN, serde_json::json!({"seed": {"id": "demand:jump:1000", "question": "q"}}));
        send(&mut k, "knos.testnet", SEED_MIN, serde_json::json!({"seed": {"id": "demand:xor:1000", "question": "q"}}));
        at("buyer.testnet", 2_000);
        send(&mut k, "buyer.testnet", DEMAND, serde_json::json!({"back": {"claim": "jump", "to": [["agent.testnet", (DEMAND - DEMAND / 10).to_string()], ["fee.testnet", (DEMAND / 10).to_string()]]}}));
        assert!(matches!(k.resolve("demand:jump:1000".into()), PromiseOrValue::Value(_)));
        assert_eq!(k.get_market("demand:jump:1000".into()).unwrap().market.outcome, Some(true));
        at("anyone.testnet", 1_000 + WEEK + 1);
        let _ = k.resolve("demand:xor:1000".into());
        assert_eq!(k.get_market("demand:xor:1000".into()).unwrap().market.outcome, Some(false));
    }

    #[test]
    #[should_panic(expected = "not settled yet")]
    fn a_demand_market_does_not_settle_early_below_the_bar() {
        let mut k = c();
        send(&mut k, "knos.testnet", SEED_MIN, serde_json::json!({"seed": {"id": "demand:jump:1000", "question": "q"}}));
        at("anyone.testnet", 5_000);
        let _ = k.resolve("demand:jump:1000".into());
    }

    #[test]
    fn traders_are_counted_once_each() {
        let mut k = c();
        send(&mut k, "knos.testnet", SEED_MIN, serde_json::json!({"seed": {"id": "job:j1", "question": "q"}}));
        for who in ["a.testnet", "a.testnet", "b.testnet"] {
            send(&mut k, who, 1_000_000, serde_json::json!({"buy": {"id": "job:j1", "side": "yes"}}));
        }
        assert_eq!(k.get_traders("job:j1".into()), 2);
        assert_eq!(k.get_market("job:j1".into()).unwrap().market.trades, 3);
    }
}
