//! cargo +nightly fuzz run claims: any bytes at all, read by both copies of the claim reader and by serde_json.
#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| knos_oidc_fuzz::agree(data));
