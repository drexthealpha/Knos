//! Open jobs and agent budgets. A payer funds a job with `ft_transfer_call` (msg `{"open_job": ...}`): the price waits
//! here against the hash of a locked test, with no payee yet. Agents `take` it and `submit` the sha256 of their output,
//! each in its own transaction. A Knos checker runs the locked test on one output; only when it passes does the
//! checker sign a token naming the job, the agent and that output's hash, and `release_job` pays: 9 parts in 10 to that
//! agent and 1 part in 10 to Knos, both sent by this contract. The checker's keys are set like GitHub's: 2 of the 3
//! owners send the same key. An agent that never passes is paid nothing; after the deadline the payer gets it all back.
//! `release_job_verified` pays the same way only on a NEAR AI Cloud signature, checked here with `ecrecover`, of the
//! model call the checker's token names.
//!
//! A budget (msg `{"budget": {"agent": ..., "cap": ...}}`) holds test units an agent may `spend`: never more than its
//! cap in all, nor its daily cap in a day, only to payees on its allow-list, a spend over its hold line waits for the
//! approver, and nothing moves while an owner has paused the contract. Each refusal is the contract's own, on chain.

use crate::*;

/// The issuer of a Knos checker's token
pub const CHECKER_ISS: &str = "https://knos.onrender.com/checker";
pub const MAX_TAKERS: usize = 20;
/// Knos's test account, paid 1 part in 10 of each released job by this contract
pub const FEE_ACCOUNT: &str = "knos-payer-1102.testnet";
pub const FEE_PARTS: u128 = 10;
/// Circle's testnet USDC on NEAR: a job may be funded in it as well as in the configured test USDC
pub const CIRCLE_USDC: &str = "3e2210e1184b45b64c8a434c0a7e7b23cc04ea7eb7a6c3c32520d03d4afcb8af";
const DAY_NS: u64 = 86_400_000_000_000;
/// the callback that records the payment and then sends Knos's part needs room for that transfer
const PAID_CALLBACK_GAS: Gas = Gas::from_tgas(40);

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

/// An agent's passes and fails: a pass is a job it was paid for, a fail an attempt on a job paid to another or refunded,
/// and a rejection a solution the AI reviewer refused (recorded by the job's payer)
#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, Default)]
pub struct AgentRecord {
    pub passes: u32,
    pub fails: u32,
    pub rejected: u32,
}

/// The rules a budget's owner sets for its agent: 0 means no daily cap and no hold line; an empty list, any payee
#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, Default)]
pub struct AgentRules {
    pub daily_cap: U128,
    pub hold_over: U128,
    pub allow: Vec<AccountId>,
}

/// The owners' switches: paused stops take, submit, release and spend (a refund still runs); the approver releases
/// held spends; the NEAR AI signing addresses a model signature may come from
#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, Default)]
pub struct Switches {
    pub paused: bool,
    pub approver: Option<AccountId>,
    pub model_signers: Vec<String>,
    pub next_hold: u64,
}

/// A spend over its agent's hold line, waiting for the approver
#[near(serializers = [borsh, json])]
#[derive(Clone, Debug)]
pub struct Hold {
    pub agent: AccountId,
    pub to: AccountId,
    pub amount: U128,
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

fn event(kind: &str, data: serde_json::Value) {
    env::log_str(&format!("EVENT_JSON:{}", serde_json::json!({"standard": "knos", "version": "1.0.0", "event": kind, "data": [data]})));
}

#[near]
impl Knos {
    /// An agent takes an open job. Anyone but the payer may, up to MAX_TAKERS, before the deadline.
    pub fn take(&mut self, id: String) -> String {
        self.not_paused();
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
        self.not_paused();
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

    /// Pays the job, 9 parts to the agent the checker's token names and 1 to Knos, when the token is a Knos checker's
    /// for this job, that agent's submitted output and the test locked at funding. Anyone may send it. With no model
    /// signature checked, the release says so: "fixed rule, no model signature".
    pub fn release_job(&mut self, id: String, token: String) -> Promise {
        let (j, payee, _) = self.checked_release(&id, &token);
        event("release", serde_json::json!({"job": id, "agent": payee, "model": "fixed rule, no model signature"}));
        self.pay_job(id, j, payee)
    }

    /// The same release, paid only when `model_signature` is NEAR AI Cloud's ECDSA signature (Ethereum personal_sign,
    /// 65 bytes hex) of `model_text`, the checker's token names that same text, and the signing address is one the
    /// owners added. Logs `model_verified` with the address.
    pub fn release_job_verified(&mut self, id: String, token: String, model_text: String, model_signature: String) -> Promise {
        let (j, payee, named) = self.checked_release(&id, &token);
        require!(named.as_deref() == Some(model_text.as_str()), "the checker's token names another model call");
        let address = recover_signer(&model_text, &model_signature);
        if !self.switches().model_signers.contains(&address) {
            env::panic_str(&format!("0x{address} is not a NEAR AI signing address the owners added"));
        }
        event("model_verified", serde_json::json!({"job": id, "agent": payee, "signer": format!("0x{address}"), "text": model_text}));
        self.pay_job(id, j, payee)
    }

    /// After the deadline with no release, the price goes back to the payer. Anyone may send it.
    pub fn refund_job(&mut self, id: String) -> Promise {
        let mut j = self.jobs.get(&id).cloned().unwrap_or_else(|| env::panic_str("no such job"));
        require!(j.state == JobState::Open, "the job is not open");
        require!(env::block_timestamp() >= j.deadline_ns.0, "the deadline has not passed");
        j.state = JobState::Refunding;
        let (to, amount) = (j.payer.clone(), j.amount);
        self.jobs.insert(id.clone(), j);
        ext_ft_core::ext(self.job_token(&id))
            .with_attached_deposit(NearToken::from_yoctonear(1))
            .with_static_gas(PAY_GAS)
            .ft_transfer(to, amount, Some(format!("knos job refund {id}")))
            .then(Self::ext(env::current_account_id()).with_static_gas(PAID_CALLBACK_GAS).on_job_paid(id, true, U128(0)))
    }

    /// After the token moved: Paid or Refunded, the totals and the agents' records; then Knos's part, also from this
    /// contract. If the transfer failed, the job is open again and the same token may be sent once more.
    #[private]
    pub fn on_job_paid(&mut self, id: String, refund: bool, fee: U128, #[callback_result] r: Result<(), PromiseError>) -> PromiseOrValue<String> {
        let mut j = self.jobs.get(&id).cloned().unwrap();
        if r.is_err() {
            if let Some(t) = j.proof_jti.take() {
                self.used_jti.remove(&t);
            }
            j.paid_to = None;
            j.state = JobState::Open;
            self.jobs.insert(id.clone(), j);
            return PromiseOrValue::Value(format!("{id}: the transfer failed; the job is open again"));
        }
        j.state = if refund { JobState::Refunded } else { JobState::Paid };
        let token = self.job_token(&id);
        if self.counted(&id) {
            self.add_total("open", &token, j.amount.0, false);
            self.add_total(if refund { "refunded" } else { "paid" }, &token, j.amount.0, true);
        }
        let mut recs: LookupMap<AccountId, AgentRecord> = LookupMap::new(Key::Records);
        for a in &j.attempts {
            let mut rec = recs.get(&a.agent).cloned().unwrap_or_default();
            if !refund && j.paid_to.as_ref() == Some(&a.agent) { rec.passes += 1 } else { rec.fails += 1 }
            recs.insert(a.agent.clone(), rec);
        }
        recs.flush();
        let s = format!("{id}: {:?}", j.state);
        self.jobs.insert(id.clone(), j);
        if refund || fee.0 == 0 {
            return PromiseOrValue::Value(s);
        }
        PromiseOrValue::Promise(
            ext_ft_core::ext(token)
                .with_attached_deposit(NearToken::from_yoctonear(1))
                .with_static_gas(PAY_GAS)
                .ft_transfer(FEE_ACCOUNT.parse().unwrap(), fee, Some(format!("knos fee, job {id}"))),
        )
    }

    /// An agent pays from its budget. Refused, on chain, when paused, over its cap in all, over its daily cap, or to a
    /// payee not on its allow-list; a spend over its hold line waits for the approver.
    pub fn spend(&mut self, to: AccountId, amount: U128) -> PromiseOrValue<String> {
        self.not_paused();
        let me = env::predecessor_account_id();
        let mut b = self.budgets.get(&me).cloned().unwrap_or_else(|| env::panic_str("this agent has no budget"));
        require!(amount.0 > 0, "amount");
        let after = b.spent.0.checked_add(amount.0).unwrap_or_else(|| env::panic_str("amount"));
        if after > b.cap.0 {
            env::panic_str(&format!("over the spend cap: {} spent, {} asked, cap {}", b.spent.0, amount.0, b.cap.0));
        }
        let rules = self.agent_rules(&me);
        if !rules.allow.is_empty() && !rules.allow.contains(&to) {
            env::panic_str(&format!("{to} is not on {me}'s payee allow-list"));
        }
        let day = env::block_timestamp() / DAY_NS;
        let mut daily: LookupMap<AccountId, (u64, u128)> = LookupMap::new(Key::Daily);
        let today = daily.get(&me).filter(|d| d.0 == day).map(|d| d.1).unwrap_or(0);
        if rules.daily_cap.0 > 0 && today + amount.0 > rules.daily_cap.0 {
            env::panic_str(&format!("over the daily cap: {} spent today, {} asked, daily cap {}", today, amount.0, rules.daily_cap.0));
        }
        require!(amount.0 <= b.balance.0, "the budget holds less than that");
        daily.insert(me.clone(), (day, today + amount.0));
        daily.flush();
        b.spent = U128(after);
        b.balance = U128(b.balance.0 - amount.0);
        self.budgets.insert(me.clone(), b);
        if rules.hold_over.0 > 0 && amount.0 > rules.hold_over.0 {
            let mut sw = self.switches();
            let n = sw.next_hold;
            sw.next_hold += 1;
            let approver = sw.approver.clone();
            self.set_switches(sw);
            let mut holds: LookupMap<u64, Hold> = LookupMap::new(Key::Holds);
            holds.insert(n, Hold { agent: me.clone(), to: to.clone(), amount });
            holds.flush();
            event("spend_held", serde_json::json!({"hold": n, "agent": me, "to": to, "amount": amount, "approver": approver}));
            return PromiseOrValue::Value(format!("held: spend {n} of {} by {me} to {to} waits for the approver", amount.0));
        }
        PromiseOrValue::Promise(self.pay_spend(me, to, amount))
    }

    /// The approver releases a held spend
    pub fn approve_spend(&mut self, hold: U64) -> Promise {
        self.not_paused();
        let sw = self.switches();
        require!(sw.approver.as_ref() == Some(&env::predecessor_account_id()), "only the approver releases a held spend");
        let mut holds: LookupMap<u64, Hold> = LookupMap::new(Key::Holds);
        let h = holds.remove(&hold.0).unwrap_or_else(|| env::panic_str("no such held spend"));
        holds.flush();
        event("spend_approved", serde_json::json!({"hold": hold, "agent": h.agent, "to": h.to, "amount": h.amount}));
        self.pay_spend(h.agent, h.to, h.amount)
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

    /// A budget's owner sets its agent's daily cap, hold line and payee allow-list
    pub fn set_agent_rules(&mut self, agent: AccountId, daily_cap: U128, hold_over: U128, allow: Vec<AccountId>) -> String {
        let b = self.budgets.get(&agent).cloned().unwrap_or_else(|| env::panic_str("this agent has no budget"));
        require!(b.owner == env::predecessor_account_id(), "only the budget's owner sets its agent's rules");
        require!(allow.len() <= 20, "at most 20 payees");
        let mut m: LookupMap<AccountId, AgentRules> = LookupMap::new(Key::AgentRules);
        m.insert(agent.clone(), AgentRules { daily_cap, hold_over, allow });
        m.flush();
        format!("rules set for {agent}")
    }

    /// An owner pauses or resumes take, submit, release and spend; a refund still runs
    pub fn pause(&mut self, paused: bool) -> String {
        self.only_owner();
        let mut sw = self.switches();
        sw.paused = paused;
        self.set_switches(sw);
        event("paused", serde_json::json!({"paused": paused, "by": env::predecessor_account_id()}));
        format!("paused: {paused}")
    }

    /// An owner names the account that releases held spends
    pub fn set_approver(&mut self, approver: AccountId) -> String {
        self.only_owner();
        let mut sw = self.switches();
        sw.approver = Some(approver.clone());
        self.set_switches(sw);
        format!("approver: {approver}")
    }

    /// An owner adds a NEAR AI Cloud signing address (from the model's attestation report), 0x and 40 hex
    pub fn add_model_signer(&mut self, address: String) -> String {
        self.only_owner();
        let a = address.trim_start_matches("0x").to_ascii_lowercase();
        require!(is_hex(&a, 40), "an address is 0x and 40 hex");
        let mut sw = self.switches();
        if !sw.model_signers.contains(&a) {
            sw.model_signers.push(a.clone());
        }
        self.set_switches(sw);
        format!("model signer 0x{a} added")
    }

    /// The job's payer (or an owner) records a solution the AI reviewer rejected, for hard-coding or reading the test:
    /// an event on chain and a rejection on the agent's record
    pub fn record_rejection(&mut self, id: String, agent: AccountId, output_sha256: String, reason: String) -> String {
        let j = self.jobs.get(&id).cloned().unwrap_or_else(|| env::panic_str("no such job"));
        let me = env::predecessor_account_id();
        require!(me == j.payer || self.owners.contains(&me), "only the job's payer or an owner records a rejection");
        require!(!reason.is_empty() && reason.len() <= 300, "reason");
        let h = output_sha256.to_ascii_lowercase();
        require!(is_hex(&h, 64), "output_sha256 must be 64 hex");
        let mut recs: LookupMap<AccountId, AgentRecord> = LookupMap::new(Key::Records);
        let mut rec = recs.get(&agent).cloned().unwrap_or_default();
        rec.rejected += 1;
        recs.insert(agent.clone(), rec);
        recs.flush();
        event("review_rejected", serde_json::json!({"job": id, "agent": agent, "output_sha256": h, "reason": reason}));
        format!("rejection recorded for {agent} on {id}")
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

    pub fn get_agent_rules(&self, agent: AccountId) -> AgentRules {
        self.agent_rules(&agent)
    }

    pub fn get_switches(&self) -> Switches {
        self.switches()
    }

    pub fn get_hold(&self, hold: U64) -> Option<Hold> {
        let holds: LookupMap<u64, Hold> = LookupMap::new(Key::Holds);
        holds.get(&hold.0).cloned()
    }

    /// An agent's passes, fails and rejections, counted since the 14 Nov 2026 upgrade
    pub fn get_agent_record(&self, agent: AccountId) -> AgentRecord {
        let recs: LookupMap<AccountId, AgentRecord> = LookupMap::new(Key::Records);
        recs.get(&agent).cloned().unwrap_or_default()
    }

    /// Per token, the test USDC locked in jobs opened since the 14 Nov 2026 upgrade, paid out, refunded and still open;
    /// conserved when locked = paid + refunded + open
    pub fn get_totals(&self) -> serde_json::Value {
        let mut out = serde_json::Map::new();
        for token in [self.usdc.to_string(), CIRCLE_USDC.to_string()] {
            let [locked, paid, refunded, open] = ["locked", "paid", "refunded", "open"].map(|k| self.total(k, &token));
            out.insert(token, serde_json::json!({"locked": U128(locked), "paid": U128(paid), "refunded": U128(refunded), "open": U128(open),
                "conserved": locked == paid + refunded + open}));
        }
        serde_json::Value::Object(out)
    }
}

/// The address that signed `text` with Ethereum's personal_sign: keccak256 of the prefixed text, ecrecover, then the
/// last 20 bytes of keccak256 of the public key (hex, no 0x)
pub fn recover_signer(text: &str, signature_hex: &str) -> String {
    let sig = unhex(&signature_hex.trim_start_matches("0x").to_ascii_lowercase()).unwrap_or_else(|| env::panic_str("the signature is not hex"));
    require!(sig.len() == 65, "the signature is not 65 bytes");
    let v = match sig[64] { 27 | 28 => sig[64] - 27, 0 | 1 => sig[64], _ => env::panic_str("the signature's v is not 27 or 28") };
    let msg = format!("\x19Ethereum Signed Message:\n{}{}", text.len(), text);
    let hash = env::keccak256_array(msg.as_bytes());
    let mut rs = [0u8; 64];
    rs.copy_from_slice(&sig[..64]);
    let pk = env::ecrecover(&hash, &rs, v, true).unwrap_or_else(|| env::panic_str("the model signature does not recover a key"));
    let a = env::keccak256_array(&pk);
    a[12..].iter().map(|b| format!("{b:02x}")).collect()
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

    /// The checks every release makes; marks the job Paying for its payee
    fn checked_release(&mut self, id: &str, token: &str) -> (Job, AccountId, Option<String>) {
        self.not_paused();
        let mut j = self.jobs.get(id).cloned().unwrap_or_else(|| env::panic_str("no such job"));
        require!(j.state == JobState::Open, "the job is not open");
        require!(env::block_timestamp() < j.deadline_ns.0, "the deadline has passed: only a refund is possible");
        let c = self.check_checker_token(token);
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
        self.jobs.insert(id.to_string(), j.clone());
        (j, payee, c.model_text)
    }

    /// 9 parts to the agent now; Knos's 1 part follows in the callback, both from this contract
    fn pay_job(&mut self, id: String, j: Job, payee: AccountId) -> Promise {
        let fee = j.amount.0 / FEE_PARTS;
        let to_agent = j.amount.0 - fee;
        ext_ft_core::ext(self.job_token(&id))
            .with_attached_deposit(NearToken::from_yoctonear(1))
            .with_static_gas(PAY_GAS)
            .ft_transfer(payee, U128(to_agent), Some(format!("knos job {id}")))
            .then(Self::ext(env::current_account_id()).with_static_gas(PAID_CALLBACK_GAS).on_job_paid(id, false, U128(fee)))
    }

    fn pay_spend(&mut self, agent: AccountId, to: AccountId, amount: U128) -> Promise {
        ext_ft_core::ext(self.usdc.clone())
            .with_attached_deposit(NearToken::from_yoctonear(1))
            .with_static_gas(PAY_GAS)
            .ft_transfer(to, amount, Some(format!("knos budget of {agent}")))
            .then(Self::ext(env::current_account_id()).with_static_gas(CALLBACK_GAS).on_spent(agent, amount))
    }

    fn not_paused(&self) {
        require!(!self.switches().paused, "Knos is paused by an owner: nothing moves but refunds");
    }

    fn only_owner(&self) {
        require!(self.owners.contains(&env::predecessor_account_id()), "only an owner may");
    }

    fn switches(&self) -> Switches {
        let m: LookupMap<String, Switches> = LookupMap::new(Key::Rules);
        m.get("switches").cloned().unwrap_or_default()
    }

    fn set_switches(&mut self, s: Switches) {
        let mut m: LookupMap<String, Switches> = LookupMap::new(Key::Rules);
        m.insert("switches".to_string(), s);
        m.flush();
    }

    fn agent_rules(&self, agent: &AccountId) -> AgentRules {
        let m: LookupMap<AccountId, AgentRules> = LookupMap::new(Key::AgentRules);
        m.get(agent).cloned().unwrap_or_default()
    }

    /// The token a job was funded in: recorded for every job opened since the upgrade; an older job is in the configured USDC
    fn job_token(&self, id: &str) -> AccountId {
        let m: LookupMap<String, AccountId> = LookupMap::new(Key::JobToken);
        m.get(id).cloned().unwrap_or_else(|| self.usdc.clone())
    }

    fn counted(&self, id: &str) -> bool {
        let m: LookupMap<String, AccountId> = LookupMap::new(Key::JobToken);
        m.contains_key(id)
    }

    fn total(&self, kind: &str, token: &str) -> u128 {
        let m: LookupMap<String, U128> = LookupMap::new(Key::Totals);
        m.get(&format!("{kind}/{token}")).map(|v| v.0).unwrap_or(0)
    }

    fn add_total(&mut self, kind: &str, token: &AccountId, amount: u128, up: bool) {
        let mut m: LookupMap<String, U128> = LookupMap::new(Key::Totals);
        let k = format!("{kind}/{token}");
        let cur = m.get(&k).map(|v| v.0).unwrap_or(0);
        m.insert(k, U128(if up { cur + amount } else { cur.saturating_sub(amount) }));
        m.flush();
    }

    /// ft_on_transfer for a msg that is not a milestone: a job or a budget. Panics on anything else.
    pub(crate) fn fund_other(&mut self, sender_id: AccountId, amount: U128, msg: FundMsg, token: AccountId) {
        match msg {
            FundMsg::OpenJob(o) => {
                require!(!o.id.is_empty() && o.id.len() <= 64, "id");
                require!(!self.jobs.contains_key(&o.id) && !self.milestones.contains_key(&o.id), "a job or milestone with this id exists");
                let h = o.criteria_hash.to_ascii_lowercase();
                require!(is_hex(&h, 64), "criteria_hash must be 64 hex");
                require!(o.deadline_ns.0 > env::block_timestamp(), "the deadline is in the past");
                let mut tokens: LookupMap<String, AccountId> = LookupMap::new(Key::JobToken);
                tokens.insert(o.id.clone(), token.clone());
                tokens.flush();
                self.add_total("locked", &token, amount.0, true);
                self.add_total("open", &token, amount.0, true);
                self.jobs.insert(o.id.clone(), Job {
                    id: o.id, payer: sender_id, amount, criteria_hash: h, deadline_ns: o.deadline_ns, state: JobState::Open,
                    takers: Vec::new(), attempts: Vec::new(), paid_to: None, proof_jti: None,
                });
            }
            FundMsg::Budget(b) => {
                require!(token == self.usdc, "a budget is funded in the configured USDC");
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
