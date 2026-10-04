//! What the handler tests of the four programs share (each ../handlers/tests/knos_*.rs takes this file in by path).
//!
//! A scenario is one file of this directory, written by scripts/rust_test_vectors.py from the Python harnesses: the
//! programs to load, then steps in order. `Replay` runs them in LiteSVM (the litesvm crate) against the test binaries
//! in tests/fixtures, which are what `cargo build-sbf` made of this source:
//!   airdrop, account, clock, expire   the chain is put where the scenario had it
//!   tx        the signed transaction, byte for byte as the scenario sent it, with signature checking on. The answer
//!             must be the recorded one: accepted, or refused by that instruction with that custom error
//!   check     the named token balances, lamports and account data must be what the scenario read at that point
//! A test runs to a named transaction (`to`), gets its answer back and asserts its own numbers on top.
#![allow(dead_code)]

use litesvm::LiteSVM;
use serde_json::Value;
use solana_account::Account;
use solana_clock::Clock;
use solana_program::{instruction::InstructionError, pubkey::Pubkey};
use solana_transaction::versioned::VersionedTransaction;
use solana_transaction_error::TransactionError;
use std::path::PathBuf;

/// What a transaction got: accepted, or refused by the instruction at `ix` with the program's error `code`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Answer { Accepted, Refused { ix: u8, code: u32 } }

pub struct Replay { pub svm: LiteSVM, doc: Value, next: usize, name: String }

fn root() -> PathBuf { PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..") }
fn key(hex_key: &str) -> Pubkey { Pubkey::new_from_array(hex::decode(hex_key).unwrap().try_into().unwrap()) }
fn n(v: &Value) -> u64 { v.as_u64().unwrap_or_else(|| panic!("not a number: {v}")) }

impl Replay {
    /// Loads programs-v2/testdata/<name>.json and the programs it names. The binaries come from tests/fixtures, or
    /// from the directory KNOS_FIXTURES names.
    pub fn load(name: &str) -> Replay {
        let path = root().join("programs-v2/testdata").join(format!("{name}.json"));
        let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("{}: {e}. Write it: python scripts/rust_test_vectors.py", path.display()));
        let doc: Value = serde_json::from_str(&text).unwrap();
        let fixtures = std::env::var_os("KNOS_FIXTURES").map(PathBuf::from).unwrap_or_else(|| root().join("tests/fixtures"));
        // the transactions carry the blockhash of the chain that recorded them; every other check of a cluster stays on
        let mut svm = LiteSVM::new().with_sigverify(true).with_blockhash_check(false);
        for p in doc["programs"].as_array().unwrap() {
            let file = fixtures.join(p["file"].as_str().unwrap());
            svm.add_program_from_file(key(p["id"].as_str().unwrap()), &file)
                .unwrap_or_else(|e| panic!("{}: {e:?}. Build it: bash scripts/build_programs_v2.sh all", file.display()));
        }
        Replay { svm, doc, next: 0, name: name.to_string() }
    }

    /// The address the scenario gave this name.
    pub fn key(&self, name: &str) -> Pubkey {
        key(self.doc["names"][name].as_str().unwrap_or_else(|| panic!("{}: no address named {name}", self.name)))
    }
    /// An account's data; None when nothing is there.
    pub fn data(&self, name: &str) -> Option<Vec<u8>> {
        self.svm.get_account(&self.key(name)).filter(|a| a.lamports > 0).map(|a| a.data)
    }
    /// What an SPL token account holds; 0 when it is not there.
    pub fn tokens(&self, name: &str) -> u64 {
        self.data(name).filter(|d| d.len() >= 165).map_or(0, |d| u64::from_le_bytes(d[64..72].try_into().unwrap()))
    }
    pub fn lamports(&self, name: &str) -> u64 { self.svm.get_account(&self.key(name)).map_or(0, |a| a.lamports) }
    pub fn now(&self) -> i64 { self.svm.get_sysvar::<Clock>().unix_timestamp }

    /// Runs every step up to and including the transaction with this label, and the checks written right after it.
    /// Returns what that transaction got (already compared with the recorded answer, as every one before it was).
    pub fn to(&mut self, label: &str) -> Answer {
        loop {
            let step = self.doc["steps"].get(self.next).cloned().unwrap_or_else(|| panic!("{}: no transaction labelled {label}", self.name));
            self.next += 1;
            let got = self.step(&step);
            if step["label"] == label && step["op"] == "tx" {
                while self.doc["steps"].get(self.next).is_some_and(|s| s["op"] == "check") {
                    let check = self.doc["steps"][self.next].clone();
                    self.next += 1;
                    self.step(&check);
                }
                return got.unwrap();
            }
        }
    }

    /// Runs what is left of the scenario.
    pub fn finish(&mut self) {
        while let Some(step) = self.doc["steps"].get(self.next).cloned() {
            self.next += 1;
            self.step(&step);
        }
    }

    fn step(&mut self, s: &Value) -> Option<Answer> {
        let at = format!("{} step {} ({})", self.name, self.next - 1, s["label"].as_str().unwrap_or("-"));
        match s["op"].as_str().unwrap() {
            "airdrop" => { self.svm.airdrop(&key(s["to"].as_str().unwrap()), n(&s["lamports"])).unwrap_or_else(|e| panic!("{at}: {:?}", e.err)); }
            "account" => {
                let account = Account { lamports: n(&s["lamports"]), data: hex::decode(s["data"].as_str().unwrap()).unwrap(),
                                        owner: key(s["owner"].as_str().unwrap()), executable: s["executable"].as_bool().unwrap(), rent_epoch: 0 };
                self.svm.set_account(key(s["at"].as_str().unwrap()), account).unwrap_or_else(|e| panic!("{at}: {e:?}"));
            }
            "clock" => self.svm.set_sysvar(&Clock { slot: n(&s["slot"]), epoch_start_timestamp: s["epoch_start"].as_i64().unwrap(), epoch: n(&s["epoch"]),
                                                    leader_schedule_epoch: n(&s["leader_epoch"]), unix_timestamp: s["unix"].as_i64().unwrap() }),
            "expire" => self.svm.expire_blockhash(),
            "tx" => {
                let tx: VersionedTransaction = bincode::deserialize(&hex::decode(s["tx"].as_str().unwrap()).unwrap()).unwrap();
                let got = match self.svm.send_transaction(tx) {
                    Ok(_) => Answer::Accepted,
                    Err(f) => match f.err {
                        TransactionError::InstructionError(ix, InstructionError::Custom(code)) => Answer::Refused { ix, code },
                        other => panic!("{at}: refused without a program error: {other:?}\n{}", f.meta.logs.join("\n")),
                    },
                };
                let want = if s["ok"].as_bool().unwrap() { Answer::Accepted } else { Answer::Refused { ix: n(&s["ix"]) as u8, code: n(&s["code"]) as u32 } };
                assert_eq!(got, want, "{at}: the program answered differently here than in the scenario");
                return Some(got);
            }
            "check" => {
                for (name, want) in s["tokens"].as_object().unwrap() { assert_eq!(self.tokens(name), n(want), "{at}: tokens of {name}"); }
                for (name, want) in s["lamports"].as_object().unwrap() { assert_eq!(self.lamports(name), n(want), "{at}: lamports of {name}"); }
                for (name, want) in s["data"].as_object().unwrap() {
                    assert_eq!(self.data(name).map(hex::encode), want.as_str().map(str::to_string), "{at}: data of {name}");
                }
            }
            other => panic!("{at}: unknown step {other}"),
        }
        None
    }
}

pub fn u64_at(d: &[u8], at: usize) -> u64 { u64::from_le_bytes(d[at..at + 8].try_into().unwrap()) }
pub fn i64_at(d: &[u8], at: usize) -> i64 { i64::from_le_bytes(d[at..at + 8].try_into().unwrap()) }
