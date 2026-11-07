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

use near_contract_standards::fungible_token::core::ext_ft_core;
use near_contract_standards::fungible_token::receiver::FungibleTokenReceiver;
use near_sdk::json_types::U128;
use near_sdk::store::{IterableMap, LookupMap};
use near_sdk::{env, near, require, AccountId, Gas, NearToken, PanicOnDefault, Promise, PromiseError, PromiseOrValue};

pub const B: u128 = 100_000_000; // 100 test tokens at 6 decimals
pub const SEED_MIN: u128 = 69_314_719; // b * ln 2, rounded up
const GAS: Gas = Gas::from_tgas(15);
pub const JOBS: &str = "jobs.knos-swarm-1105.testnet"; // the jobs contract a "job:" market follows

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

    pub fn get_holding(&self, id: String, account: AccountId) -> Holding {
        self.holdings.get(&key(&id, &account)).map(|h| Holding { yes: U128(h.0), no: U128(h.1) }).unwrap_or_default()
    }

    /// Settles the market from its milestone on `source`: anyone may send it; the answer is the chain's, not the sender's.
    pub fn resolve(&mut self, id: String) -> Promise {
        let m = self.markets.get(&id).unwrap_or_else(|| env::panic_str("no such market"));
        require!(m.outcome.is_none(), "this market is already settled");
        // "job:<id>" follows a job of the jobs contract (paid only to the helper whose output passed its locked test);
        // any other id follows a milestone of `source` (released only by its named workflow's own token)
        let (to, method, key) = match id.strip_prefix("job:") {
            Some(job) => (JOBS.parse::<AccountId>().unwrap_or_else(|_| env::panic_str("jobs")), "get_job", job.to_string()),
            None => (self.source.clone(), "get_milestone", id.clone()),
        };
        Promise::new(to)
            .function_call(method.to_string(), serde_json::json!({ "id": key }).to_string().into_bytes(), NearToken::from_yoctonear(0), GAS)
            .then(Self::ext(env::current_account_id()).with_static_gas(GAS).on_resolve(id))
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
        }
        PromiseOrValue::Value(U128(0))
    }
}
