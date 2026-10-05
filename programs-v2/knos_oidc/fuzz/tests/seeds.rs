//! The committed seed corpus (fuzz/seeds, written by `python tests/test_oidc_differential.py --seeds`: every kind of
//! forged token of that test, and Project Wycheproof's vectors under their own keys) through both fuzz targets'
//! checks, under `cargo test` on stable. The nightly job starts the fuzzer from the same files.
use std::{fs, path::Path};

fn each(dir: &str, mut f: impl FnMut(&str, &[u8])) -> usize {
    let mut names: Vec<_> = fs::read_dir(Path::new(env!("CARGO_MANIFEST_DIR")).join("seeds").join(dir)).unwrap().map(|e| e.unwrap().path()).collect();
    names.sort();
    for p in &names { f(p.file_name().unwrap().to_str().unwrap(), &fs::read(p).unwrap()); }
    names.len()
}

#[test]
fn the_three_voices_agree_on_every_rsa_seed_and_the_valid_ones_are_called_valid() {
    let (mut valid, mut invalid) = (0, 0);
    let n = each("rsa_verify", |name, data| {
        knos_oidc_fuzz::rsa_diff::agree(data);
        if data[0] & 2 != 0 { return; }
        let k = if data[0] & 1 == 0 { 256 } else { 512 };
        let ok = knos_oidc::rsa::verify_native(&data[33..33 + k], &data[33 + k..], &data[1..33].try_into().unwrap());
        if ok { valid += 1 } else { invalid += 1 }
        // a seed named for a valid token is one, and a forgery is not
        if name.starts_with("valid") || name.starts_with("header_") || name.ends_with("_spelled_with_escapes") { assert!(ok, "{name}"); }
        if name.starts_with("em_") || name.starts_with("signature_") || name == "cube_root_forgery" { assert!(!ok, "{name}"); }
    });
    assert!(n >= 300 && valid >= 20 && invalid >= 250, "{n} seeds, {valid} valid, {invalid} invalid");
}

#[test]
fn the_fuzzer_can_reach_a_wrong_encoding_by_writing_what_the_test_keys_signature_opens_to() {
    use knos_oidc_fuzz::rsa_diff::{agree, encoding};
    let digest = [7u8; 32];
    let good = encoding(256, &digest);
    let input = |em: &[u8]| [&[2u8][..], &digest[..], em].concat();
    agree(&input(&good));
    for at in 0..256 {
        for bit in [0x01u8, 0x80] {
            let mut em = good.clone();
            em[at] ^= bit;
            agree(&input(&em));          // below the modulus or not, the voices agree, and none calls it valid (checked inside)
        }
    }
    agree(&input(&good[..200]));
    agree(&[2u8; 33]);
    agree(&[]);
}

#[test]
fn both_claim_readers_and_serde_json_agree_on_every_claims_seed() {
    assert!(each("claims", |_, data| knos_oidc_fuzz::agree(data)) >= 150);
}
