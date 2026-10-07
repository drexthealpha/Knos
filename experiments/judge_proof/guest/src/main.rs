//! The guest: a judge for one task, run inside the zkVM. Its input is the submission's bytes; the checks are part of
//! the program, so the image id names them. It commits `judge::journal` and nothing else.
#![no_main]

mod judge;

use risc0_zkvm::guest::env;
use risc0_zkvm::sha::{Impl, Sha256};
use std::io::Read;

const CHECKS: &[u8] = include_bytes!("../../checks.txt");

risc0_zkvm::guest::entry!(main);

fn digest(bytes: &[u8]) -> [u8; 32] {
    let mut out = [0u8; 32];
    out.copy_from_slice(Impl::hash_bytes(bytes).as_bytes());
    out
}

fn main() {
    let mut submission = Vec::new();
    env::stdin().read_to_end(&mut submission).expect("the submission is read whole");
    let verdict = judge::judge(CHECKS, &submission);
    env::commit_slice(&judge::journal(&digest(&submission), &digest(CHECKS), &verdict));
}
