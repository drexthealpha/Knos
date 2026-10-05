//! cargo +nightly fuzz run rsa_verify: any bytes at all as a key, a digest and a signature (or an encoded message the test key
//! signs), put to the program's RSA arithmetic, to big integers and to the `rsa` crate. See ../src/rsa_diff.rs.
#![no_main]
use libfuzzer_sys::fuzz_target;

fuzz_target!(|data: &[u8]| knos_oidc_fuzz::rsa_diff::agree(data));
