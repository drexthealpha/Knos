//! Sandbox tests: the contract and a NEP-141 test token deployed on a local near-sandbox node, a milestone funded with
//! ft_transfer_call, released on a signed OIDC token (with the gas it burns), refused on a replay and a forged token,
//! and refunded after its deadline. Needs the two wasm files: run near/scripts/test-sandbox.sh.

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use near_api::types::{AccountId, NearGas, NearToken};
use near_api::{Contract, NetworkConfig, Signer};
use near_sandbox::{GenesisAccount, Sandbox, SandboxConfig};
use rsa::pkcs1v15::SigningKey;
use rsa::signature::{SignatureEncoding, Signer as _};
use rsa::traits::PublicKeyParts;
use rsa::RsaPrivateKey;
use serde_json::{json, Value};
use sha2::Sha256;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

const HASH: &str = "ea54c35ca50d76df0000000000000000000000000000000000000000000000ab";
const REPO: &str = "drexthealpha/knos-demo";
const WF: &str = "drexthealpha/knos-demo/.github/workflows/proof.yml@refs/heads/main";

struct World {
    net: NetworkConfig,
    sandbox: Sandbox,
    usdc: AccountId,
    knos: AccountId,
    payer: (AccountId, Arc<Signer>),
    payee: AccountId,
    owners: Vec<(AccountId, Arc<Signer>)>,
    key: RsaPrivateKey,
}

fn wasm(var: &str) -> Vec<u8> {
    std::fs::read(std::env::var(var).unwrap_or_else(|_| panic!("{var} is not set: run near/scripts/test-sandbox.sh"))).unwrap()
}

fn now_s() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs()
}

fn signer(a: &GenesisAccount) -> Arc<Signer> {
    Signer::from_secret_key(a.private_key.parse().unwrap()).unwrap()
}

fn token(w: &World, jti: &str, key: &RsaPrivateKey) -> String {
    let h = URL_SAFE_NO_PAD.encode(r#"{"alg":"RS256","kid":"gh1","typ":"JWT"}"#);
    let p = URL_SAFE_NO_PAD.encode(
        json!({"iss": "https://token.actions.githubusercontent.com", "aud": w.knos.as_str(), "exp": now_s() + 600,
            "jti": jti, "repository": REPO, "job_workflow_ref": WF, "sha": "0123456789abcdef0123456789abcdef01234567"})
        .to_string(),
    );
    let sig = SigningKey::<Sha256>::new(key.clone()).sign(format!("{h}.{p}").as_bytes()).to_bytes();
    format!("{h}.{p}.{}", URL_SAFE_NO_PAD.encode(sig))
}

async fn call(w: &World, contract: &AccountId, method: &str, args: Value, who: &(AccountId, Arc<Signer>), yocto: u128) -> Result<near_api::types::transaction::result::ExecutionSuccess, String> {
    Contract(contract.clone())
        .call_function(method, args)
        .unwrap()
        .transaction()
        .gas(NearGas::from_tgas(300))
        .deposit(NearToken::from_yoctonear(yocto))
        .with_signer(who.0.clone(), who.1.clone())
        .send_to(&w.net)
        .await
        .map_err(|e| e.to_string())?
        .into_result()
        .map_err(|e| format!("{e:?}"))
}

async fn view(w: &World, contract: &AccountId, method: &str, args: Value) -> Value {
    Contract(contract.clone()).call_function(method, args).unwrap().read_only().fetch_from(&w.net).await.unwrap().data
}

async fn balance(w: &World, of: &AccountId) -> u128 {
    view(w, &w.usdc, "ft_balance_of", json!({"account_id": of})).await.as_str().unwrap().parse().unwrap()
}

async fn fund(w: &World, id: &str, deadline_s: u64, amount: u128) -> Result<(), String> {
    let msg = json!({"id": id, "payee_chain": "near", "payee_address": w.payee, "criteria_hash": HASH, "repository": REPO,
        "workflow": WF, "deadline_ns": (deadline_s * 1_000_000_000).to_string()})
    .to_string();
    call(w, &w.usdc, "ft_transfer_call", json!({"receiver_id": w.knos, "amount": amount.to_string(), "msg": msg}), &w.payer, 1)
        .await
        .map(|_| ())
}

async fn world() -> World {
    let names = ["usdc", "knos", "payer", "payee", "owner1", "owner2", "owner3"];
    let accts: Vec<GenesisAccount> = names.iter().map(|n| GenesisAccount::generate_with_name(n.parse().unwrap())).collect();
    let sandbox = Sandbox::start_sandbox_with_config(SandboxConfig { additional_accounts: accts.clone(), ..Default::default() })
        .await
        .unwrap();
    let net = NetworkConfig::from_rpc_url("sandbox", sandbox.rpc_addr.parse().unwrap());
    let id = |i: usize| -> AccountId { accts[i].account_id.as_str().parse().unwrap() };
    let key = RsaPrivateKey::new(&mut rand::thread_rng(), 2048).unwrap();
    let w = World {
        usdc: id(0),
        knos: id(1),
        payer: (id(2), signer(&accts[2])),
        payee: id(3),
        owners: (4..7).map(|i| (id(i), signer(&accts[i]))).collect(),
        key,
        net,
        sandbox,
    };
    Contract::deploy(w.usdc.clone())
        .use_code(wasm("USDC_WASM"))
        .with_init_call("new", json!({"owner_id": w.payer.0, "total_supply": "1000000000"}))
        .unwrap()
        .with_signer(signer(&accts[0]))
        .send_to(&w.net)
        .await
        .unwrap()
        .assert_success();
    Contract::deploy(w.knos.clone())
        .use_code(wasm("KNOS_WASM"))
        .with_init_call("new", json!({"usdc": w.usdc, "owners": w.owners.iter().map(|o| o.0.clone()).collect::<Vec<_>>()}))
        .unwrap()
        .with_signer(signer(&accts[1]))
        .send_to(&w.net)
        .await
        .unwrap()
        .assert_success();
    for a in [&w.knos, &w.payee] {
        call(&w, &w.usdc, "storage_deposit", json!({"account_id": a}), &w.payer, 1_250_000_000_000_000_000_000).await.unwrap();
    }
    let n: String = w.key.n().to_bytes_be().iter().map(|b| format!("{b:02x}")).collect();
    for o in &w.owners[..2] {
        call(&w, &w.knos, "propose_key", json!({"kid": "gh1", "n_hex": n}), o, 0).await.unwrap();
    }
    w
}

#[tokio::test]
#[ignore = "needs KNOS_WASM and USDC_WASM: near/scripts/test-sandbox.sh"]
async fn sandbox_fund_release_replay_forgery_refund() {
    let w = world().await;
    let mut lines = vec![];

    // a key set by owner 3 alone would wait; the two owners above applied it
    let rules = view(&w, &w.knos, "get_rules", json!({})).await;
    assert_eq!(rules["keys"][0]["kid"], "gh1");

    // fund and release
    fund(&w, "m1", now_s() + 3600, 5_000_000).await.unwrap();
    assert_eq!(balance(&w, &w.knos).await, 5_000_000);
    let t1 = token(&w, "jti-1", &w.key);
    let r = call(&w, &w.knos, "release", json!({"id": "m1", "token": t1, "criteria_hash": HASH}), &w.owners[2], 0).await.unwrap();
    let verify_gas = r.outcomes().iter().map(|o| o.gas_burnt.as_gas()).max().unwrap();
    let total = r.total_gas_burnt.as_gas();
    lines.push(format!("release: payee balance {}, the release receipt burnt {:.2} Tgas, the whole transaction {:.2} Tgas",
        balance(&w, &w.payee).await, verify_gas as f64 / 1e12, total as f64 / 1e12));
    assert_eq!(balance(&w, &w.payee).await, 5_000_000);
    assert_eq!(view(&w, &w.knos, "get_milestone", json!({"id": "m1"})).await["state"], "Released");
    assert!(verify_gas < 300_000_000_000_000, "verify under 300 Tgas");

    // the same token on a second milestone
    fund(&w, "m2", now_s() + 3600, 1_000_000).await.unwrap();
    let e = call(&w, &w.knos, "release", json!({"id": "m2", "token": t1, "criteria_hash": HASH}), &w.owners[2], 0).await.unwrap_err();
    assert!(e.contains("already used"), "{e}");
    lines.push("replayed token: refused".into());

    // a token signed by another key under the same kid
    let other = RsaPrivateKey::new(&mut rand::thread_rng(), 2048).unwrap();
    let e = call(&w, &w.knos, "release", json!({"id": "m2", "token": token(&w, "jti-2", &other), "criteria_hash": HASH}), &w.owners[2], 0)
        .await
        .unwrap_err();
    assert!(e.contains("does not verify"), "{e}");
    lines.push("forged token: refused".into());

    // a non-owner cannot change the key set
    let e = call(&w, &w.knos, "propose_key", json!({"kid": "gh1", "n_hex": null}), &w.payer, 0).await.unwrap_err();
    assert!(e.contains("only an owner"), "{e}");

    // refund after the deadline
    fund(&w, "m3", now_s() + 30, 2_000_000).await.unwrap();
    let before = balance(&w, &w.payer.0).await;
    let e = call(&w, &w.knos, "refund", json!({"id": "m3"}), &w.anyone(), 0).await;
    assert!(e.is_err(), "refund before the deadline must fail");
    tokio::time::sleep(std::time::Duration::from_secs(35)).await;
    w.sandbox.fast_forward(20).await.unwrap();
    call(&w, &w.knos, "refund", json!({"id": "m3"}), &w.owners[2], 0).await.unwrap();
    assert_eq!(balance(&w, &w.payer.0).await, before + 2_000_000);
    assert_eq!(view(&w, &w.knos, "get_milestone", json!({"id": "m3"})).await["state"], "Refunded");
    lines.push("refund after the deadline: the payer got 2000000 back".into());
    let e = call(&w, &w.knos, "release", json!({"id": "m3", "token": token(&w, "jti-3", &w.key), "criteria_hash": HASH}), &w.owners[2], 0)
        .await
        .unwrap_err();
    assert!(e.contains("not funded and open"), "{e}");
    lines.push("release after the refund: refused".into());
    println!("SANDBOX {}", lines.join(" | "));
    if let Ok(f) = std::env::var("KNOS_SANDBOX_REPORT") {
        std::fs::write(f, lines.join("\n") + "\n").unwrap();
    }
}

impl World {
    /// any account other than the payer may ask for a refund; owner 1 stands in for "anyone"
    fn anyone(&self) -> (AccountId, Arc<Signer>) {
        self.owners[0].clone()
    }
}
