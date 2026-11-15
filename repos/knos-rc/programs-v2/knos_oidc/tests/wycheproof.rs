//! Project Wycheproof's RSASSA-PKCS1-v1_5 SHA-256 verification vectors (C2SP/wycheproof, testvectors_v1), run against
//! the same RSA code the program runs on chain. Every "valid" vector must verify and every "invalid" one must be
//! refused. The one "acceptable" vector (a DigestInfo without the NULL parameter) is refused too: this verifier
//! compares the whole encoding byte for byte. Groups whose public exponent is not 65537 are outside what OIDC
//! issuers use and are counted as skipped.
use knos_oidc::rsa::verify_native;
use solana_program::hash::hash;

fn run(file: &str) -> (usize, usize, usize, usize) {
    let v: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(file).unwrap()).unwrap();
    let (mut valid, mut invalid, mut acceptable, mut skipped) = (0, 0, 0, 0);
    for g in v["testGroups"].as_array().unwrap() {
        let tests = g["tests"].as_array().unwrap();
        if g["publicKey"]["publicExponent"].as_str().unwrap() != "010001" { skipped += tests.len(); continue; }
        let mut n = hex::decode(g["publicKey"]["modulus"].as_str().unwrap()).unwrap();
        while n.len() > 1 && n[0] == 0 { n.remove(0); }
        for t in tests {
            let msg = hex::decode(t["msg"].as_str().unwrap()).unwrap();
            let sig = hex::decode(t["sig"].as_str().unwrap()).unwrap();
            let got = verify_native(&n, &sig, &hash(&msg).to_bytes());
            let id = t["tcId"].as_u64().unwrap();
            match t["result"].as_str().unwrap() {
                "valid" => { assert!(got, "{file} tcId {id} is valid but was refused"); valid += 1; }
                "invalid" => { assert!(!got, "{file} tcId {id} is invalid but was accepted: {}", t["comment"]); invalid += 1; }
                _ => { assert!(!got, "{file} tcId {id} (acceptable) must be refused by a strict verifier"); acceptable += 1; }
            }
        }
    }
    (valid, invalid, acceptable, skipped)
}

#[test]
fn wycheproof_rsa_2048_sha256() {
    let r = run("tests/vectors/rsa_signature_2048_sha256_test.json");
    println!("2048: valid {} verified, invalid {} refused, acceptable {} refused, skipped (e != 65537) {}", r.0, r.1, r.2, r.3);
    assert!(r.0 >= 7 && r.1 >= 240);
}

#[test]
fn wycheproof_rsa_4096_sha256() {
    let r = run("tests/vectors/rsa_signature_4096_sha256_test.json");
    println!("4096: valid {} verified, invalid {} refused, acceptable {} refused, skipped (e != 65537) {}", r.0, r.1, r.2, r.3);
    assert!(r.0 >= 7 && r.1 >= 240);
}
