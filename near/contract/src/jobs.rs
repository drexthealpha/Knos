//! Open jobs and agent budgets. A payer funds a job with `ft_transfer_call` (msg `{"open_job": ...}`): the bid waits
//! here against the hash of a locked test, with no payee yet. Agents `take` it and `submit` the sha256 of their output,
//! each in its own transaction. A Knos checker runs the locked test on one output; only when it passes does the
//! checker sign a token naming the job, the agent and that output's hash, and `release_job` pays that agent the bid. The
//! checker's keys are set like GitHub's: 2 of the 3 owners send the same key. An agent that never passes is paid
//! nothing; after the deadline the payer gets the bid back.
//!
//! A budget (msg `{"budget": {"agent": ..., "cap": ...}}`) holds test units an agent may `spend`, never more than its
//! cap in all: a payment over the cap is refused here, on chain.

use crate::*;

/// The issuer of a Knos checker's token
pub const CHECKER_ISS: &str = "https://knos.onrender.com/checker";
pub const MAX_TAKERS: usize = 20;

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, PartialEq)]
pub enum JobState {
    Open,
    Paying,
    Paid,
    Refunding,
    Refunded,
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug)]
pub struct Attempt {
    pub agent: AccountId,
    /// sha256 hex of the agent's output, as it submitted it
    pub output_sha256: String,
    pub at_ns: U64,
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug)]
pub struct Job {
    pub id: String,
    pub payer: AccountId,
    pub amount: U128,
    /// sha256 hex of the locked test, fixed at funding
    pub criteria_hash: String,
    pub deadline_ns: U64,
    pub state: JobState,
    pub takers: Vec<AccountId>,
    pub attempts: Vec<Attempt>,
    pub paid_to: Option<AccountId>,
    pub proof_jti: Option<String>,
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug)]
pub struct Budget {
    pub owner: AccountId,
    pub cap: U128,
    pub spent: U128,
    pub balance: U128,
}

/// What a payer puts in ft_transfer_call's msg to open a job
#[near(serializers = [json])]
pub struct OpenJob {
    pub id: String,
    pub criteria_hash: String,
    pub deadline_ns: U64,
}

#[near(serializers = [json])]
pub struct BudgetFor {
    pub agent: AccountId,
    pub cap: U128,
}

#[near(serializers = [json])]
pub enum FundMsg {
    #[serde(rename = "open_job")]
    OpenJob(OpenJob),
    #[serde(rename = "budget")]
    Budget(BudgetFor),
}

#[near]
impl Knos {
    /// An agent takes an open job. Anyone but the payer may, up to MAX_TAKERS, before the deadline.
    pub fn take(&mut self, id: String) -> String {
        let me = env::predecessor_account_id();
        let mut j = self.jobs.get(&id).cloned().unwrap_or_else(|| env::panic_str("no such job"));
        require!(j.state == JobState::Open, "the job is not open");
        require!(env::block_timestamp() < j.deadline_ns.0, "the deadline has passed");
        require!(me != j.payer, "the payer cannot take its own job");
        require!(!j.takers.contains(&me), "already taken by this agent");
        require!(j.takers.len() < MAX_TAKERS, "the job has its most takers");
        j.takers.push(me.clone());
        self.jobs.insert(id.clone(), j);
        format!("{me} took {id}")
    }

    /// A taker records the sha256 of its output: its attempt, on chain. A second submit replaces its first.
    pub fn submit(&mut self, id: String, output_sha256: String) -> String {
        let me = env::predecessor_account_id();
        let mut j = self.jobs.get(&id).cloned().unwrap_or_else(|| env::panic_str("no such job"));
        require!(j.state == JobState::Open, "the job is not open");
        require!(env::block_timestamp() < j.deadline_ns.0, "the deadline has passed");
        require!(j.takers.contains(&me), "only an agent that took the job submits");
        let h = output_sha256.to_ascii_lowercase();
        require!(is_hex(&h, 64), "output_sha256 must be 64 hex");
        j.attempts.retain(|a| a.agent != me);
        j.attempts.push(Attempt { agent: me.clone(), output_sha256: h, at_ns: U64(env::block_timestamp()) });
        self.jobs.insert(id.clone(), j);
        format!("{me} submitted for {id}")
    }

    /// Pays the bid to the agent the checker's token names, when the token is a Knos checker's for this job, that
    /// agent's submitted output and the test locked at funding. Anyone may send it.
    pub fn release_job(&mut self, id: String, token: String) -> Promise {
        let mut j = self.jobs.get(&id).cloned().unwrap_or_else(|| env::panic_str("no such job"));
        require!(j.state == JobState::Open, "the job is not open");
        require!(env::block_timestamp() < j.deadline_ns.0, "the deadline has passed: only a refund is possible");
        let c = self.check_checker_token(&token);
        require!(c.job == id, "the token is for another job");
        require!(c.criteria_hash == j.criteria_hash, "the token checked another test than the one locked at funding");
        let payee: AccountId = c.payee.parse().unwrap_or_else(|_| env::panic_str("payee"));
        let a = j.attempts.iter().find(|a| a.agent == payee).unwrap_or_else(|| env::panic_str("the payee submitted no output"));
        require!(a.output_sha256 == c.output_sha256.to_ascii_lowercase(), "the token checked another output than the payee submitted");
        require!(!self.used_jti.contains(&c.jti), "this token was already used");
        self.used_jti.insert(c.jti.clone());
        j.state = JobState::Paying;
        j.paid_to = Some(payee.clone());
        j.proof_jti = Some(c.jti);
        let amount = j.amount;
        self.jobs.insert(id.clone(), j);
        ext_ft_core::ext(self.usdc.clone())
            .with_attached_deposit(NearToken::from_yoctonear(1))
            .with_static_gas(PAY_GAS)
            .ft_transfer(payee, amount, Some(format!("knos job {id}")))
            .then(Self::ext(env::current_account_id()).with_static_gas(CALLBACK_GAS).on_job_paid(id, false))
    }

    /// After the deadline with no release, the bid goes back to the payer. Anyone may send it.
    pub fn refund_job(&mut self, id: String) -> Promise {
        let mut j = self.jobs.get(&id).cloned().unwrap_or_else(|| env::panic_str("no such job"));
        require!(j.state == JobState::Open, "the job is not open");
        require!(env::block_timestamp() >= j.deadline_ns.0, "the deadline has not passed");
        j.state = JobState::Refunding;
        let (to, amount) = (j.payer.clone(), j.amount);
        self.jobs.insert(id.clone(), j);
        ext_ft_core::ext(self.usdc.clone())
            .with_attached_deposit(NearToken::from_yoctonear(1))
            .with_static_gas(PAY_GAS)
            .ft_transfer(to, amount, Some(format!("knos job refund {id}")))
            .then(Self::ext(env::current_account_id()).with_static_gas(CALLBACK_GAS).on_job_paid(id, true))
    }

    /// The payment runs here, after the token moved: Paid or Refunded; if the transfer failed, the job is open again
    /// and the same token may be sent once more.
    #[private]
    pub fn on_job_paid(&mut self, id: String, refund: bool, #[callback_result] r: Result<(), PromiseError>) -> String {
        let mut j = self.jobs.get(&id).cloned().unwrap();
        if r.is_ok() {
            j.state = if refund { JobState::Refunded } else { JobState::Paid };
        } else {
            if let Some(t) = j.proof_jti.take() {
                self.used_jti.remove(&t);
            }
            j.paid_to = None;
            j.state = JobState::Open;
        }
        let s = format!("{id}: {:?}", j.state);
        self.jobs.insert(id, j);
        s
    }

    /// An agent pays from its budget: refused, on chain, when it would spend more than its cap in all.
    pub fn spend(&mut self, to: AccountId, amount: U128) -> Promise {
        let me = env::predecessor_account_id();
        let mut b = self.budgets.get(&me).cloned().unwrap_or_else(|| env::panic_str("this agent has no budget"));
        require!(amount.0 > 0, "amount");
        let after = b.spent.0.checked_add(amount.0).unwrap_or_else(|| env::panic_str("amount"));
        if after > b.cap.0 {
            env::panic_str(&format!("over the spend cap: {} spent, {} asked, cap {}", b.spent.0, amount.0, b.cap.0));
        }
        require!(amount.0 <= b.balance.0, "the budget holds less than that");
        b.spent = U128(after);
        b.balance = U128(b.balance.0 - amount.0);
        self.budgets.insert(me.clone(), b);
        ext_ft_core::ext(self.usdc.clone())
            .with_attached_deposit(NearToken::from_yoctonear(1))
            .with_static_gas(PAY_GAS)
            .ft_transfer(to, amount, Some(format!("knos budget of {me}")))
            .then(Self::ext(env::current_account_id()).with_static_gas(CALLBACK_GAS).on_spent(me, amount))
    }

    /// A spend whose transfer failed is given back to the budget
    #[private]
    pub fn on_spent(&mut self, agent: AccountId, amount: U128, #[callback_result] r: Result<(), PromiseError>) -> String {
        if r.is_err() {
            let mut b = self.budgets.get(&agent).cloned().unwrap();
            b.spent = U128(b.spent.0 - amount.0);
            b.balance = U128(b.balance.0 + amount.0);
            self.budgets.insert(agent.clone(), b);
            return format!("{agent}: the payment failed and was given back to the budget");
        }
        format!("{agent}: paid {}", amount.0)
    }

    /// An owner proposes a Knos checker key (n as hex, 2048 bits) or its removal; a second owner sending the same
    /// change applies it. Checker keys sign only checker tokens: a checker key never passes as GitHub's.
    pub fn propose_checker_key(&mut self, kid: String, n_hex: Option<String>) -> String {
        let me = env::predecessor_account_id();
        require!(self.owners.contains(&me), "only an owner changes the key set");
        require!(!kid.is_empty() && kid.len() <= 128, "kid");
        let n_hex = n_hex.map(|h| h.to_ascii_lowercase());
        if let Some(h) = &n_hex {
            require!(rsa::constants(&unhex(h).unwrap_or_default()).is_some(), "n must be a 2048-bit RSA modulus");
        }
        let slot = format!("checker/{kid}");
        if let Some(p) = self.proposals.get(&slot) {
            if p.by != me && p.n_hex == n_hex {
                self.proposals.remove(&slot);
                return match n_hex {
                    Some(h) => {
                        let (n, n0inv, r2) = rsa::constants(&unhex(&h).unwrap()).unwrap();
                        self.checker_keys.insert(kid.clone(), RsaKey { n, n0inv, r2, n_hex: h });
                        format!("checker key {kid} set by 2 owners")
                    }
                    None => {
                        self.checker_keys.remove(&kid);
                        format!("checker key {kid} removed by 2 owners")
                    }
                };
            }
        }
        self.proposals.insert(slot, Proposal { n_hex, by: me });
        format!("proposed checker key {kid}: waiting for a second owner")
    }

    pub fn get_job(&self, id: String) -> Option<Job> {
        self.jobs.get(&id).cloned()
    }

    pub fn get_budget(&self, agent: AccountId) -> Option<Budget> {
        self.budgets.get(&agent).cloned()
    }
}

impl Knos {
    fn check_checker_token(&self, token: &str) -> jwt::CheckerClaims {
        let t: jwt::Token<jwt::CheckerClaims> = jwt::parse(token).unwrap_or_else(|e| env::panic_str(e));
        require!(t.alg == "RS256", "the token is not RS256");
        let k = self.checker_keys.get(&t.kid).unwrap_or_else(|| env::panic_str("the token's key is not a checker key"));
        let digest = env::sha256(t.signed.as_bytes());
        require!(rsa::verify(&k.n, k.n0inv, &k.r2, &t.sig, &digest), "the token's signature does not verify");
        let c = t.claims;
        require!(c.iss == CHECKER_ISS, "the token is not a Knos checker's");
        require!(c.aud == env::current_account_id().as_str(), "the token's audience is not this contract");
        require!(c.exp > env::block_timestamp() / 1_000_000_000, "the token has expired");
        c
    }

    /// ft_on_transfer for a msg that is not a milestone: a job or a budget. Panics on anything else.
    pub(crate) fn fund_other(&mut self, sender_id: AccountId, amount: U128, msg: FundMsg) {
        match msg {
            FundMsg::OpenJob(o) => {
                require!(!o.id.is_empty() && o.id.len() <= 64, "id");
                require!(!self.jobs.contains_key(&o.id) && !self.milestones.contains_key(&o.id), "a job or milestone with this id exists");
                let h = o.criteria_hash.to_ascii_lowercase();
                require!(is_hex(&h, 64), "criteria_hash must be 64 hex");
                require!(o.deadline_ns.0 > env::block_timestamp(), "the deadline is in the past");
                self.jobs.insert(o.id.clone(), Job {
                    id: o.id, payer: sender_id, amount, criteria_hash: h, deadline_ns: o.deadline_ns, state: JobState::Open,
                    takers: Vec::new(), attempts: Vec::new(), paid_to: None, proof_jti: None,
                });
            }
            FundMsg::Budget(b) => {
                let mut cur = self.budgets.get(&b.agent).cloned()
                    .unwrap_or(Budget { owner: sender_id.clone(), cap: b.cap, spent: U128(0), balance: U128(0) });
                require!(cur.owner == sender_id, "this agent's budget belongs to another owner");
                cur.cap = b.cap;
                cur.balance = U128(cur.balance.0 + amount.0);
                self.budgets.insert(b.agent, cur);
            }
        }
    }
}
