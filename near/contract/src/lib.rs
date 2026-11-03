//! Knos on NEAR: a funded research milestone. A payer sends testnet USDC with `ft_transfer_call`; the milestone locks
//! the payee (a chain and an address), the amount, the criteria hash of the Ready brief and the GitHub workflow whose
//! run is the proof, with a deadline. `release` pays only on a GitHub Actions OIDC token (RS256) verified here, in pure
//! Rust: its signature under a key the owners set, its issuer, its audience (this contract), its repository and
//! workflow, its commit and expiry, and a `jti` never used before. `refund` returns the money to the payer once the
//! deadline has passed with no release. The fee is 0. The key set changes only when 2 of the 3 owners send the same key.

mod jwt;
pub mod rsa;
pub mod solana;

use near_contract_standards::fungible_token::core::ext_ft_core;
use near_contract_standards::fungible_token::receiver::FungibleTokenReceiver;
use near_sdk::json_types::{U128, U64};
use near_sdk::store::{LookupMap, LookupSet};
use near_sdk::{env, near, require, AccountId, BorshStorageKey, Gas, NearToken, PanicOnDefault, Promise, PromiseError, PromiseOrValue};

pub const GITHUB_ISS: &str = "https://token.actions.githubusercontent.com";
const PAY_GAS: Gas = Gas::from_tgas(15);
const CALLBACK_GAS: Gas = Gas::from_tgas(15);
/// Chain Signatures on testnet; domain 1 is Ed25519 (Solana)
pub const SIGNER: &str = "v1.signer-prod.testnet";
pub const SOLANA_PATH: &str = "knos-solana-1";
const SIGN_GAS: Gas = Gas::from_tgas(50);

#[near(serializers = [borsh])]
#[derive(BorshStorageKey)]
enum Key {
    Milestones,
    Keys,
    Proposals,
    Used,
    Payouts,
}

/// A Solana payout of a released milestone: the message the contract asked the MPC network to sign, and the answer
#[near(serializers = [borsh, json])]
#[derive(Clone, Debug)]
pub struct Payout {
    pub message_b64: String,
    pub signing: bool,
    /// the signer's answer as it came back (Ed25519, 64 bytes), once signed
    pub signature: Option<String>,
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
    /// for a Solana payee: the SPL mint the payout must use (payee_address is then the payee's token account)
    pub payee_mint: Option<String>,
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
    #[serde(default)]
    pub payee_mint: Option<String>,
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
    payouts: LookupMap<String, Payout>,
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
            payouts: LookupMap::new(Key::Payouts),
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
    /// A milestone released for a payee on another chain counts as unpaid until its payout is signed: with no
    /// signature (and none being asked for) by the deadline, it is refunded too, so it never stays locked.
    pub fn refund(&mut self, id: String) -> Promise {
        let mut m = self.milestones.get(&id).cloned().unwrap_or_else(|| env::panic_str("no such milestone"));
        if m.state == State::Released && m.payee_chain != "near" {
            if let Some(p) = self.payouts.get(&id) {
                require!(p.signature.is_none(), "the payout is signed: it is paid on the payee's chain, not refunded");
                require!(!p.signing, "the payout is being signed");
            }
        } else {
            require!(m.state == State::Funded, "the milestone is not funded and open");
        }
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
        } else if refund && m.payee_chain != "near" && m.proof_sha.is_some() {
            m.state = State::Released; // a refund of a released milestone that failed: released again, as it was
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

    // ---- the payout on Solana, by Chain Signatures ---------------------------------------------------------------

    /// For a released Solana milestone: anyone sends the unsigned Solana message (base64) that pays it. The contract
    /// checks it is one SPL TransferChecked of exactly the milestone's amount, in the mint and to the token account
    /// locked at funding, then asks the MPC signer for an Ed25519 signature under this contract's key for SOLANA_PATH.
    /// A relayer adds the signature and broadcasts it; the contract never holds a Solana key.
    pub fn sign_payout(&mut self, id: String, message_b64: String) -> Promise {
        let m = self.milestones.get(&id).cloned().unwrap_or_else(|| env::panic_str("no such milestone"));
        require!(m.payee_chain == "solana", "the milestone is not paid on Solana");
        require!(m.state == State::Released, "the milestone is not released");
        if let Some(p) = self.payouts.get(&id) {
            require!(p.signature.is_none(), "the payout is already signed");
            require!(!p.signing, "the payout is being signed");
        }
        let msg = base64::Engine::decode(&base64::engine::general_purpose::STANDARD, &message_b64)
            .unwrap_or_else(|_| env::panic_str("message_b64"));
        require!(msg.len() <= 1232, "the message is longer than 1232 bytes");
        let t = solana::parse_transfer(&msg).unwrap_or_else(|e| env::panic_str(e));
        require!(Some(t.destination) == solana::b58_32(&m.payee_address), "the payout goes to another account");
        require!(Some(t.mint) == m.payee_mint.as_deref().and_then(solana::b58_32), "the payout is in another mint");
        require!(t.amount as u128 == m.amount.0, "the payout is another amount");
        self.payouts.insert(id.clone(), Payout { message_b64, signing: true, signature: None });
        let hex: String = msg.iter().map(|b| format!("{b:02x}")).collect();
        let args = serde_json::json!({"request": {"payload_v2": {"Eddsa": hex}, "path": SOLANA_PATH, "domain_id": 1}});
        Promise::new(SIGNER.parse().unwrap())
            .function_call("sign".to_string(), args.to_string().into_bytes(), NearToken::from_yoctonear(1), SIGN_GAS)
            .then(Self::ext(env::current_account_id()).with_static_gas(CALLBACK_GAS).on_payout_signed(id))
    }

    /// The signer's answer: kept when it came, or the payout is open to be asked again
    #[private]
    pub fn on_payout_signed(&mut self, id: String, #[callback_result] r: Result<serde_json::Value, PromiseError>) -> String {
        let mut p = self.payouts.get(&id).cloned().unwrap();
        p.signing = false;
        let out = match r {
            Ok(v) => {
                p.signature = Some(v.to_string());
                format!("{id}: payout signed")
            }
            Err(_) => format!("{id}: the signer did not answer; ask again"),
        };
        self.payouts.insert(id, p);
        out
    }

    pub fn get_payout(&self, id: String) -> Option<Payout> {
        self.payouts.get(&id).cloned()
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
        if f.payee_chain == "solana" {
            require!(solana::b58_32(&f.payee_address).is_some(), "payee address");
            require!(f.payee_mint.as_deref().and_then(solana::b58_32).is_some(), "a Solana payee needs payee_mint");
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
            payee_mint: f.payee_mint,
        };
        self.milestones.insert(f.id, m);
        PromiseOrValue::Value(U128(0))
    }
}

#[cfg(test)]
mod tests;
