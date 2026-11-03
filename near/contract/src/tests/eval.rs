//! The locked eval (near/eval/attempts.json, its sha256 committed before this ran): every attempt through the
//! contract's own release, against plain CI pass/fail. Prints caught counts with 95% Wilson intervals; writes them to
//! KNOS_EVAL_OUT when set.

use super::*;
use std::panic::{catch_unwind, AssertUnwindSafe};

const ATTEMPTS: &str = include_str!("../../../eval/attempts.json");

fn wilson(k: usize, n: usize) -> (f64, f64) {
    let (k, n, z) = (k as f64, n as f64, 1.96f64);
    let p = k / n;
    let d = 1.0 + z * z / n;
    let c = (p + z * z / (2.0 * n)) / d;
    let h = z * ((p * (1.0 - p) / n) + z * z / (4.0 * n * n)).sqrt() / d;
    (c - h, c + h)
}

#[test]
fn locked_eval_of_60_attempts() {
    let attempts: Vec<serde_json::Value> = serde_json::from_str(ATTEMPTS).unwrap();
    assert_eq!(attempts.len(), 60);
    let mut c = contract();
    let mut rows = vec![];
    for a in &attempts {
        let id = a["id"].as_str().unwrap();
        ctx(USDC, NOW);
        let msg = serde_json::json!({"id": id, "payee_chain": "near", "payee_address": "payee.testnet", "criteria_hash": HASH,
            "repository": a["repository"], "workflow": a["workflow"], "deadline_ns": ((NOW + 3600) * SEC).to_string()});
        let _ = c.ft_on_transfer(acct("payer.testnet"), U128(1_000), msg.to_string());
        let t = &a["token"];
        let mut cl = claims(t["jti"].as_str().unwrap());
        cl["repository"] = t["repository"].clone();
        cl["job_workflow_ref"] = t["job_workflow_ref"].clone();
        let tok = token_with(&keys().0, "gh1", &cl);
        let crit = if a["criteria"] == "altered" { "f".repeat(64) } else { HASH.to_string() };
        let paid = catch_unwind(AssertUnwindSafe(|| {
            ctx("relayer.testnet", NOW);
            let _ = c.release(id.into(), tok.clone(), crit.clone());
        }))
        .is_ok();
        rows.push((a["kind"].as_str().unwrap().to_string(), a["attack"].as_str().unwrap_or("").to_string(), paid, a["ci_passed"].as_bool().unwrap()));
    }
    let honest = rows.iter().filter(|r| r.0 == "honest").count();
    let cheats = rows.iter().filter(|r| r.0 == "cheat").count();
    let honest_paid = rows.iter().filter(|r| r.0 == "honest" && r.2).count();
    let knos_caught = rows.iter().filter(|r| r.0 == "cheat" && !r.2).count();
    let ci_caught = rows.iter().filter(|r| r.0 == "cheat" && !r.3).count();
    let (kl, kh) = wilson(knos_caught, cheats);
    let (cl_, ch) = wilson(ci_caught, cheats);
    let (hl, hh) = wilson(honest_paid, honest);
    let mut by: std::collections::BTreeMap<String, (usize, usize)> = Default::default();
    for r in rows.iter().filter(|r| r.0 == "cheat") {
        let e = by.entry(r.1.clone()).or_default();
        e.0 += !r.2 as usize;
        e.1 += 1;
    }
    let report = serde_json::json!({
        "attempts": 60, "honest": honest, "cheats": cheats,
        "knos": {"cheats_caught": knos_caught, "ci95": [kl, kh], "honest_paid": honest_paid, "honest_ci95": [hl, hh]},
        "plain_ci": {"cheats_caught": ci_caught, "ci95": [cl_, ch], "honest_paid": honest},
        "ai_only_judge": "not run: needs a model key, and no key is used here",
        "by_attack": by.iter().map(|(k, v)| (k.clone(), format!("{} of {}", v.0, v.1))).collect::<std::collections::BTreeMap<_, _>>(),
    });
    println!("EVAL {report}");
    if let Ok(p) = std::env::var("KNOS_EVAL_OUT") {
        std::fs::write(p, serde_json::to_string_pretty(&report).unwrap()).unwrap();
    }
    // the counts the README states are these assertions, not typed numbers
    assert_eq!((honest, cheats), (30, 30), "the locked file holds 30 honest and 30 cheating attempts");
    assert_eq!(knos_caught, cheats, "every cheating attempt is refused by the contract");
    assert_eq!(ci_caught, 0, "every cheating attempt carries a green CI run, so plain CI pays it");
    assert_eq!(honest_paid, honest, "every honest attempt is paid");
}
