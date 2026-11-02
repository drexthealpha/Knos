//! Knos on NEAR: a funded research milestone. A payer sends testnet USDC with `ft_transfer_call`; the milestone locks
//! the payee (a chain and an address), the amount, the criteria hash of the Ready brief and the GitHub workflow whose
//! run is the proof, with a deadline. `release` pays only on a GitHub Actions OIDC token (RS256) verified here, in pure
//! Rust: its signature under a key the owners set, its issuer, its audience (this contract), its repository and
//! workflow, its commit and expiry, and a `jti` never used before. `refund` returns the money to the payer once the
//! deadline has passed with no release. The fee is 0. The key set changes only when 2 of the 3 owners send the same key.

mod jwt;
pub mod rsa;

use near_contract_standards::fungible_token::core::ext_ft_core;
use near_contract_standards::fungible_token::receiver::FungibleTokenReceiver;
use near_sdk::json_types::{U128, U64};
use near_sdk::store::{LookupMap, LookupSet};
use near_sdk::{env, near, require, AccountId, BorshStorageKey, Gas, NearToken, PanicOnDefault, Promise, PromiseError, PromiseOrValue};

pub const GITHUB_ISS: &str = "https://token.actions.githubusercontent.com";
const PAY_GAS: Gas = Gas::from_tgas(15);
const CALLBACK_GAS: Gas = Gas::from_tgas(15);

#[near(serializers = [borsh])]
#[derive(BorshStorageKey)]
enum Key {
    Milestones,
    Keys,
    Proposals,
    Used,
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, PartialEq)]
pub enum State {
    Funded,
    Releasing,
    Released,
    Refunding,
    Refunded,
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug)]
pub struct Milestone {
    pub id: String,
    pub payer: AccountId,
    /// "near" pays the address on NEAR; another chain (solana, ethereum) is paid by a Chain Signatures payout
    pub payee_chain: String,
    pub payee_address: String,
    pub amount: U128,
    /// sha256 hex of the Ready brief's criteria, locked at funding
    pub criteria_hash: String,
    /// "owner/repo", lower case
    pub repository: String,
    /// the token's job_workflow_ref, exactly: "owner/repo/.github/workflows/file.yml@refs/heads/main"
    pub workflow: String,
    pub deadline_ns: U64,
    pub state: State,
    /// the commit the paying token named
    pub proof_sha: Option<String>,
    pub proof_jti: Option<String>,
}

/// What the payer puts in ft_transfer_call's msg
#[near(serializers = [json])]
pub struct Fund {
    pub id: String,
    pub payee_chain: String,
    pub payee_address: String,
    pub criteria_hash: String,
    pub repository: String,
    pub workflow: String,
    pub deadline_ns: U64,
}

#[near(serializers = [borsh])]
pub struct RsaKey {
    n: Vec<u32>,
    n0inv: u32,
    r2: Vec<u32>,
    n_hex: String,
}

/// A change to the key set waiting for a second owner: Some(n hex) sets kid, None removes it
#[near(serializers = [borsh])]
pub struct Proposal {
    n_hex: Option<String>,
    by: AccountId,
}

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Knos {
    usdc: AccountId,
    owners: Vec<AccountId>,
    milestones: LookupMap<String, Milestone>,
    keys: LookupMap<String, RsaKey>,
    kids: Vec<String>,
    proposals: LookupMap<String, Proposal>,
    used_jti: LookupSet<String>,
}

fn is_hex(s: &str, len: usize) -> bool {
    s.len() == len && s.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}

fn unhex(s: &str) -> Option<Vec<u8>> {
    if s.len() % 2 != 0 || !s.bytes().all(|c| c.is_ascii_hexdigit()) {
        return None;
    }
    (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).ok()).collect()
}

#[near]
impl Knos {
    #[init]
    pub fn new(usdc: AccountId, owners: Vec<AccountId>) -> Self {
        require!(owners.len() == 3, "three owners");
        require!(owners[0] != owners[1] && owners[1] != owners[2] && owners[0] != owners[2], "three different owners");
        Self {
            usdc,
            owners,
            milestones: LookupMap::new(Key::Milestones),
            keys: LookupMap::new(Key::Keys),
            kids: Vec::new(),
            proposals: LookupMap::new(Key::Proposals),
            used_jti: LookupSet::new(Key::Used),
        }
    }

    // ---- the key set: 2 of 3 owners ------------------------------------------------------------------------------

    /// An owner proposes GitHub's key `kid` (n as hex, 2048 bits) or, with no n, its removal. A second, different owner
    /// sending the same change applies it. Anyone else is refused.
    pub fn propose_key(&mut self, kid: String, n_hex: Option<String>) -> String {
        let me = env::predecessor_account_id();
        require!(self.owners.contains(&me), "only an owner changes the key set");
        require!(!kid.is_empty() && kid.len() <= 128, "kid");
        let n_hex = n_hex.map(|h| h.to_ascii_lowercase());
        if let Some(h) = &n_hex {
            let n = unhex(h).unwrap_or_default();
            require!(rsa::constants(&n).is_some(), "n must be a 2048-bit RSA modulus");
        }
        if let Some(p) = self.proposals.get(&kid) {
            if p.by != me && p.n_hex == n_hex {
                self.proposals.remove(&kid);
                return self.apply_key(kid, n_hex);
            }
        }
        self.proposals.insert(kid.clone(), Proposal { n_hex, by: me });
        format!("proposed {kid}: waiting for a second owner")
    }

    fn apply_key(&mut self, kid: String, n_hex: Option<String>) -> String {
        match n_hex {
            Some(h) => {
                let (n, n0inv, r2) = rsa::constants(&unhex(&h).unwrap()).unwrap();
                self.keys.insert(kid.clone(), RsaKey { n, n0inv, r2, n_hex: h });
                if !self.kids.contains(&kid) {
                    self.kids.push(kid.clone());
                }
                format!("key {kid} set by 2 owners")
            }
            None => {
                self.keys.remove(&kid);
                self.kids.retain(|k| k != &kid);
                format!("key {kid} removed by 2 owners")
            }
        }
    }

    // ---- the milestone -------------------------------------------------------------------------------------------

    /// Pays the payee when `token` is a GitHub Actions OIDC token for this milestone and `criteria_hash` is the hash
    /// locked at funding. Anyone may send it (a relayer, the payee, a bot).
    pub fn release(&mut self, id: String, token: String, criteria_hash: String) -> PromiseOrValue<String> {
        let mut m = self.milestones.get(&id).cloned().unwrap_or_else(|| env::panic_str("no such milestone"));
        require!(m.state == State::Funded, "the milestone is not funded and open");
        require!(criteria_hash == m.criteria_hash, "the criteria are not the ones locked at funding");
        let now_ns = env::block_timestamp();
        require!(now_ns < m.deadline_ns.0, "the deadline has passed: only a refund is possible");
        let c = self.check_token(&token);
        require!(c.repository.to_ascii_lowercase() == m.repository, "the token comes from another repository");
        require!(c.job_workflow_ref == m.workflow, "the token comes from another workflow");
        require!(is_hex(&c.sha, 40), "the token names no commit");
        require!(!self.used_jti.contains(&c.jti), "this token was already used");
        self.used_jti.insert(c.jti.clone());
        m.proof_sha = Some(c.sha);
        m.proof_jti = Some(c.jti);
        if m.payee_chain == "near" {
            m.state = State::Releasing;
            let to: AccountId = m.payee_address.parse().unwrap_or_else(|_| env::panic_str("payee address"));
            let amount = m.amount;
            self.milestones.insert(id.clone(), m);
            PromiseOrValue::Promise(
                ext_ft_core::ext(self.usdc.clone())
                    .with_attached_deposit(NearToken::from_yoctonear(1))
                    .with_static_gas(PAY_GAS)
                    .ft_transfer(to, amount, Some(format!("knos release {id}")))
                    .then(Self::ext(env::current_account_id()).with_static_gas(CALLBACK_GAS).on_paid(id, false)),
            )
        } else {
            // paid on the payee's chain from the contract's Chain Signatures address (near/relayer broadcasts it)
            m.state = State::Released;
            self.milestones.insert(id.clone(), m);
            PromiseOrValue::Value(format!("released {id}: the payout on the payee's chain awaits its signature"))
        }
    }

    /// Returns the money to the payer once the deadline has passed with no release. Anyone may send it.
    pub fn refund(&mut self, id: String) -> Promise {
        let mut m = self.milestones.get(&id).cloned().unwrap_or_else(|| env::panic_str("no such milestone"));
        require!(m.state == State::Funded, "the milestone is not funded and open");
        require!(env::block_timestamp() >= m.deadline_ns.0, "the deadline has not passed");
        m.state = State::Refunding;
        let (to, amount) = (m.payer.clone(), m.amount);
        self.milestones.insert(id.clone(), m);
        ext_ft_core::ext(self.usdc.clone())
            .with_attached_deposit(NearToken::from_yoctonear(1))
            .with_static_gas(PAY_GAS)
            .ft_transfer(to, amount, Some(format!("knos refund {id}")))
            .then(Self::ext(env::current_account_id()).with_static_gas(CALLBACK_GAS).on_paid(id, true))
    }

    /// After the token moved: Released or Refunded; if the transfer failed, the milestone is open again and a
    /// release's token may be sent once more.
    #[private]
    pub fn on_paid(&mut self, id: String, refund: bool, #[callback_result] r: Result<(), PromiseError>) -> String {
        let mut m = self.milestones.get(&id).cloned().unwrap();
        if r.is_ok() {
            m.state = if refund { State::Refunded } else { State::Released };
        } else {
            if let Some(j) = m.proof_jti.take() {
                self.used_jti.remove(&j);
            }
            m.proof_sha = None;
            m.state = State::Funded;
        }
        let s = format!("{id}: {:?}", m.state);
        self.milestones.insert(id, m);
        s
    }

    // ---- reading, for anyone -------------------------------------------------------------------------------------

    pub fn get_milestone(&self, id: String) -> Option<Milestone> {
        self.milestones.get(&id).cloned()
    }

    /// The rules anyone can read: the token, the owners, the issuer, the key ids with their moduli, the fee.
    pub fn get_rules(&self) -> serde_json::Value {
        let keys: Vec<serde_json::Value> = self
            .kids
            .iter()
            .map(|k| serde_json::json!({"kid": k, "n": self.keys.get(k).map(|x| x.n_hex.clone())}))
            .collect();
        serde_json::json!({
            "usdc": self.usdc, "owners": self.owners, "issuer": GITHUB_ISS, "audience": env::current_account_id(),
            "keys": keys, "fee": "0", "key_change": "2 of 3 owners send the same key",
            "release": "a GitHub Actions OIDC token: signature, issuer, audience, repository, workflow, commit, expiry, unused jti; the locked criteria hash; before the deadline",
            "refund": "to the payer, by anyone, once the deadline has passed with no release"
        })
    }
}

impl Knos {
    fn check_token(&self, token: &str) -> jwt::Claims {
        let t = jwt::parse(token).unwrap_or_else(|e| env::panic_str(e));
        require!(t.alg == "RS256", "the token is not RS256");
        let k = self.keys.get(&t.kid).unwrap_or_else(|| env::panic_str("the token's key is not in the key set"));
        let digest = env::sha256(t.signed.as_bytes());
        require!(rsa::verify(&k.n, k.n0inv, &k.r2, &t.sig, &digest), "the token's signature does not verify");
        let c = t.claims;
        require!(c.iss == GITHUB_ISS, "the token is not GitHub's");
        require!(c.aud == env::current_account_id().as_str(), "the token's audience is not this contract");
        require!(c.exp > env::block_timestamp() / 1_000_000_000, "the token has expired");
        c
    }
}

#[near]
impl FungibleTokenReceiver for Knos {
    /// Funding: only the configured USDC; msg is a `Fund`. Any refusal panics, so the token returns the whole amount.
    fn ft_on_transfer(&mut self, sender_id: AccountId, amount: U128, msg: String) -> PromiseOrValue<U128> {
        require!(env::predecessor_account_id() == self.usdc, "only the configured USDC funds a milestone");
        require!(amount.0 > 0, "amount");
        let f: Fund = serde_json::from_str(&msg).unwrap_or_else(|_| env::panic_str("msg is not a milestone"));
        require!(!f.id.is_empty() && f.id.len() <= 64, "id");
        require!(!self.milestones.contains_key(&f.id), "a milestone with this id exists");
        require!(is_hex(&f.criteria_hash, 64), "criteria_hash must be 64 hex");
        require!(["near", "solana", "ethereum"].contains(&f.payee_chain.as_str()), "payee_chain");
        if f.payee_chain == "near" {
            require!(f.payee_address.parse::<AccountId>().is_ok(), "payee address");
        }
        require!(f.repository.contains('/') && f.workflow.starts_with(&format!("{}/", f.repository)), "repository and workflow");
        require!(f.deadline_ns.0 > env::block_timestamp(), "the deadline is in the past");
        let m = Milestone {
            id: f.id.clone(),
            payer: sender_id,
            payee_chain: f.payee_chain,
            payee_address: f.payee_address,
            amount,
            criteria_hash: f.criteria_hash,
            repository: f.repository.to_ascii_lowercase(),
            workflow: f.workflow,
            deadline_ns: f.deadline_ns,
            state: State::Funded,
            proof_sha: None,
            proof_jti: None,
        };
        self.milestones.insert(f.id, m);
        PromiseOrValue::Value(U128(0))
    }
}

#[cfg(test)]
mod tests;
