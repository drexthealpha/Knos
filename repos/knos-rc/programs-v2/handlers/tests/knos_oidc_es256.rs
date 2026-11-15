//! knos_oidc's ES256 handlers (src/es256.rs), run from Rust: the test build (tests/fixtures/knos_oidc_v2_test.so) in
//! LiteSVM with its secp256r1 precompile. The keys, the tokens and their signatures are fixed: tests/_es256.py writes
//! them into programs-v2/testdata/es256.json (two P-256 keys from fixed seeds, RFC 6979 nonces). The transactions are
//! built here, unsigned: the wallets' signatures are not what is tested, so LiteSVM's check of them is off, and every
//! other check of a cluster, the precompile among them, is on. Run: cd programs-v2/handlers && cargo test --release
//! --test knos_oidc_es256 -- --nocapture (it prints the compute units and the transaction sizes).
use knos_oidc::es256::{ec_audience, EC_ACCOUNT, EC_IHASH, EC_KEY, EC_MARK, E_EC_KEY, E_PRECOMPILE, E_SIGNER, SECP256R1_ID, SIG_LEN, SIG_TEXT};
use knos_oidc::{claims, pins, strict, E_ALG, E_ATTEST, E_GUARDIAN, E_INACTIVE, E_ISS, E_KEY, E_REVOKED, E_STAGE, F_APPROVED, F_GENESIS, F_PRIVATE,
                K_ACTIVE, K_EXPIRES, K_FLAGS, K_HDR, K_ISSUER, K_LIMBS, K_STATE, T_DONE, T_EXP, T_ISSUER, T_JWT, T_KEY, T_LEN, T_LIMBS, T_PLEN, T_POFF,
                T_STAGE, VERIFIED};
use litesvm::LiteSVM;
use serde_json::Value;
use solana_account::Account;
use solana_clock::Clock;
use solana_program::{
    hash::hashv,
    instruction::{AccountMeta, Instruction, InstructionError},
    message::Message,
    pubkey::Pubkey,
    system_instruction, system_program, sysvar,
};
use solana_transaction::Transaction;
use solana_transaction_error::TransactionError;
use std::path::PathBuf;

const PRECOMPILE_BAD_SIGNATURE: u32 = 2; // the secp256r1 precompile's own error for a signature that does not verify
const LEGACY_LIMIT: usize = 1232;        // the bytes of a legacy transaction
const SELF: u16 = u16::MAX;

fn root() -> PathBuf { PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..") }

struct World { svm: LiteSVM, id: Pubkey, payer: Pubkey, doc: Value, sent: u8 }
/// What a transaction got: the compute units it used, or the instruction that refused it and its error.
type Got = Result<u64, (u8, u32)>;

impl World {
    fn new() -> World {
        let doc: Value = serde_json::from_str(&std::fs::read_to_string(root().join("programs-v2/testdata/es256.json")).unwrap()).unwrap();
        let ids: Value = serde_json::from_str(&std::fs::read_to_string(root().join("programs-v2/program_ids.json")).unwrap()).unwrap();
        let id: Pubkey = ids["knos_oidc"].as_str().unwrap().parse().unwrap();
        let fixtures = std::env::var_os("KNOS_FIXTURES").map(PathBuf::from).unwrap_or_else(|| root().join("tests/fixtures"));
        let mut svm = LiteSVM::new().with_sigverify(false).with_blockhash_check(false);
        svm.add_program_from_file(id, fixtures.join("knos_oidc_v2_test.so")).unwrap();
        let payer = Pubkey::new_from_array([0x51; 32]);
        svm.airdrop(&payer, 10_000_000_000).unwrap();
        let mut w = World { svm, id, payer, doc, sent: 0 };
        let now = w.doc["now"].as_i64().unwrap();
        w.clock(now);
        w
    }
    fn now(&self) -> i64 { self.svm.get_sysvar::<Clock>().unix_timestamp }
    fn clock(&mut self, unix: i64) {
        let mut c = self.svm.get_sysvar::<Clock>();
        c.unix_timestamp = unix;
        self.svm.set_sysvar(&c);
    }
    fn hex(&self, name: &str) -> Vec<u8> { hex::decode(self.doc[name].as_str().unwrap()).unwrap() }
    fn key_a(&self) -> Vec<u8> { self.hex("key_a") }
    fn key_b(&self) -> Vec<u8> { self.hex("key_b") }
    fn issuer(&self) -> Vec<u8> { self.doc["issuer"].as_str().unwrap().as_bytes().to_vec() }
    /// A token's signing input and key A's signature of it (the lower s).
    fn token(&self, name: &str) -> (Vec<u8>, Vec<u8>) {
        let t = &self.doc["tokens"][name];
        (t["input"].as_str().unwrap().as_bytes().to_vec(), hex::decode(t["sig_a"].as_str().unwrap()).unwrap())
    }
    fn data(&self, at: &Pubkey) -> Option<Vec<u8>> { self.svm.get_account(at).filter(|a| a.lamports > 0).map(|a| a.data) }

    fn tx(&mut self, ixs: &[Instruction]) -> Transaction {
        let mut tx = Transaction::new_unsigned(Message::new(ixs, Some(&self.payer)));
        // nobody signs here; a different filler each time, so that no transaction is taken for one already sent
        self.sent += 1;
        for s in tx.signatures.iter_mut() { *s = [self.sent; 64].into(); }
        tx
    }
    fn send(&mut self, ixs: &[Instruction]) -> Got {
        let tx = self.tx(ixs);
        match self.svm.send_transaction(tx) {
            Ok(meta) => Ok(meta.compute_units_consumed),
            Err(f) => match f.err {
                TransactionError::InstructionError(ix, InstructionError::Custom(code)) => Err((ix, code)),
                other => panic!("refused without a program error: {other:?}\n{}", f.meta.logs.join("\n")),
            },
        }
    }

    // -- addresses
    fn private_key(&self, registrant: &Pubkey, url: &[u8], key: &[u8]) -> Pubkey {
        Pubkey::find_program_address(&[b"epkey", registrant.as_ref(), hashv(&[url]).as_ref(), hashv(&[key]).as_ref()], &self.id).0
    }
    fn attested_key(&self, url: &[u8], key: &[u8]) -> Pubkey {
        Pubkey::find_program_address(&[b"eckey", hashv(&[url]).as_ref(), hashv(&[key]).as_ref()], &self.id).0
    }
    fn token_account(&self, input: &[u8]) -> Pubkey {
        Pubkey::find_program_address(&[b"tok", self.payer.as_ref(), hashv(&[input]).as_ref()], &self.id).0
    }

    // -- instructions
    fn register_private(&self, url: &[u8], key: &[u8]) -> Instruction {
        let data = [&[11u8, url.len() as u8][..], url, key].concat();
        Instruction { program_id: self.id, data, accounts: vec![AccountMeta::new(self.payer, true), AccountMeta::new(self.private_key(&self.payer, url, key), false),
                                                                AccountMeta::new_readonly(system_program::ID, false)] }
    }
    fn verify(&self, input: &[u8], key: &Pubkey) -> Instruction {
        Instruction { program_id: self.id, data: vec![15], accounts: vec![
            AccountMeta::new(self.payer, true), AccountMeta::new(self.token_account(input), false), AccountMeta::new_readonly(*key, false),
            AccountMeta::new_readonly(system_program::ID, false), AccountMeta::new_readonly(sysvar::instructions::ID, false)] }
    }
    /// Key A registered as the payer's private key for the issuer: the key account.
    fn with_private_key(&mut self) -> Pubkey {
        let (url, key) = (self.issuer(), self.key_a());
        self.send(&[self.register_private(&url, &key)]).unwrap();
        self.private_key(&self.payer, &url, &key)
    }
    /// The precompile and VerifyEs256, as a relay sends a token.
    fn carry(&mut self, key_account: &Pubkey, key: &[u8], sig: &[u8], input: &[u8]) -> Got {
        self.send(&[precompile(key, sig, input), self.verify(input, key_account)])
    }
}

/// The precompile's instruction: one signature, every part in its own data.
fn precompile(key: &[u8], sig: &[u8], msg: &[u8]) -> Instruction {
    let mut d = vec![1u8, 0];
    for v in [16 + 33, SELF, 16, SELF, 16 + 33 + 64, msg.len() as u16, SELF] { d.extend_from_slice(&v.to_le_bytes()); }
    Instruction { program_id: SECP256R1_ID, accounts: vec![], data: [d, key.to_vec(), sig.to_vec(), msg.to_vec()].concat() }
}

/// The guardian a test build also takes (pins.rs TEST_GUARDIAN under `testkeys`). This crate links knos_oidc without
/// that feature, so the address is written here.
fn test_guardian() -> Pubkey {
    Pubkey::new_from_array([0xea, 0x4a, 0x6c, 0x63, 0xe2, 0x9c, 0x52, 0x0a, 0xbe, 0xf5, 0x50, 0x7b, 0x13, 0x2e, 0xc5, 0xf9,
                            0x95, 0x47, 0x76, 0xae, 0xbe, 0xbe, 0x7b, 0x92, 0x42, 0x1e, 0xea, 0x69, 0x14, 0x46, 0xd2, 0x2c])
}

fn i64_at(d: &[u8], at: usize) -> i64 { i64::from_le_bytes(d[at..at + 8].try_into().unwrap()) }
fn u16_at(d: &[u8], at: usize) -> usize { u16::from_le_bytes([d[at], d[at + 1]]) as usize }

/// A good token of a registered P-256 key is VERIFIED in one transaction, into the account an RS256 token gets: the
/// payload a consumer reads is the one that was signed, the key and the issuer are named, and the signature is there
/// in the one spelling a consumer names its single-use marker by.
#[test]
fn a_good_token_is_verified_in_one_transaction() {
    let mut w = World::new();
    let key = w.with_private_key();
    let k = w.data(&key).unwrap();
    assert_eq!((k.len(), k[K_STATE], k[K_ISSUER], k[K_LIMBS], k[K_FLAGS]), (EC_ACCOUNT, 1, pins::ISSUER_PRIVATE, EC_MARK, F_PRIVATE));
    assert_eq!((&k[EC_KEY..EC_IHASH], i64_at(&k, K_ACTIVE), i64_at(&k, K_EXPIRES)), (&w.key_a()[..], w.now(), w.now() + pins::KEY_TTL));

    let (input, sig) = w.token("good");
    let cu = w.carry(&key, &w.key_a(), &sig, &input).unwrap();
    println!("VerifyEs256, a {}-byte signing input: {cu} compute units for the transaction (the precompile uses none of them)", input.len());
    assert!(cu < 200_000, "inside the default limit of one instruction: no compute budget instruction is needed");

    let t = w.data(&w.token_account(&input)).unwrap();
    let v = knos_oidc::verified(&t).unwrap();
    assert_eq!((v.issuer, v.exp), (pins::ISSUER_PRIVATE, w.now() + 300));
    let payload: Value = serde_json::from_slice(v.payload).unwrap();
    assert_eq!((payload["iss"].as_str().unwrap().as_bytes(), payload["sub"].as_str().unwrap()), (&w.issuer()[..], "spiffe://issuer.example/workload"));
    assert_eq!(knos_oidc::issuer_hash(&t).unwrap(), &hashv(&[&w.issuer()]).to_bytes());
    assert!(knos_oidc::is_private(&t));
    assert_eq!(knos_oidc::registrant(&t).unwrap(), &w.payer.to_bytes());
    assert_eq!((&t[T_KEY..T_KEY + 32], t[T_STAGE], t[T_DONE], t[T_LIMBS]), (key.as_ref(), VERIFIED, 0, 0));
    // the account holds header.payload.signature; what follows the last dot is the signature the precompile verified,
    // read here the way knos_pay reads it to name ["used", sha256(signature)]
    let len = u16_at(&t, T_LEN);
    assert_eq!((len, t.len()), (input.len() + 1 + SIG_TEXT, T_JWT + input.len() + 1 + SIG_TEXT));
    let jwt = &t[T_JWT..T_JWT + len];
    let dot = jwt.iter().rposition(|&c| c == b'.').unwrap();
    let mut back = [0u8; SIG_LEN];
    claims::b64url_into(&jwt[dot + 1..], &mut back).unwrap();
    assert_eq!(&back[..], &sig[..]);
    // and the header is still the text that was signed
    assert_eq!(&jwt[..input.iter().position(|&c| c == b'.').unwrap()], &input[..input.iter().position(|&c| c == b'.').unwrap()]);
    assert_eq!((u16_at(&t, T_POFF), u16_at(&t, T_PLEN), i64_at(&t, T_EXP)), (T_JWT + input.iter().position(|&c| c == b'.').unwrap() + 1, v.payload.len(), v.exp));
    assert!(strict::fields(v.payload, [b"iss"]).is_ok());

    // Close gives the rent back, as for any token account
    let before = w.svm.get_account(&w.payer).unwrap().lamports;
    let close = Instruction { program_id: w.id, data: [&[2u8][..], hashv(&[&input]).as_ref()].concat(),
                              accounts: vec![AccountMeta::new(w.payer, true), AccountMeta::new(w.token_account(&input), false)] };
    w.send(&[close]).unwrap();
    assert!(w.data(&w.token_account(&input)).is_none() && w.svm.get_account(&w.payer).unwrap().lamports > before);
}

/// The largest token a legacy transaction carries: a signing input of 780 bytes makes a transaction of exactly 1,232.
#[test]
fn the_largest_token_fills_a_legacy_transaction() {
    let mut w = World::new();
    let key = w.with_private_key();
    let max = w.doc["max_signing_input"].as_u64().unwrap() as usize;
    let (largest, sig) = w.token("largest");
    let (over, _) = w.token("over");
    assert_eq!((max, largest.len(), over.len()), (780, 780, 781));
    let size = |w: &mut World, input: &[u8]| { let tx = w.tx(&[precompile(&w.key_a(), &sig, input), w.verify(input, &key)]); bincode::serialize(&tx).unwrap().len() };
    assert_eq!((size(&mut w, &largest), size(&mut w, &over)), (LEGACY_LIMIT, LEGACY_LIMIT + 1));
    let (good, _) = w.token("good");
    println!("transaction bytes: {} without the signing input; {} with the test token ({} bytes); {} with the largest ({} bytes)",
             LEGACY_LIMIT - max, size(&mut w, &good), good.len(), LEGACY_LIMIT, max);
    let cu = w.carry(&key, &w.key_a(), &sig, &largest).unwrap();
    println!("VerifyEs256, the largest signing input ({max} bytes): {cu} compute units for the transaction");
    assert!(cu < 200_000);
    assert_eq!(knos_oidc::verified(&w.data(&w.token_account(&largest)).unwrap()).unwrap().exp, w.now() + 300);
}

/// A signature of another key: under the registered key the precompile refuses the transaction before the program
/// runs; under its signer's own key the precompile passes and the program refuses, because that is not the key account's.
#[test]
fn a_token_signed_by_another_key_is_refused() {
    let mut w = World::new();
    let key = w.with_private_key();
    let (input, _) = w.token("good");
    let sig_b = w.hex("good_sig_b");
    assert_eq!(w.carry(&key, &w.key_a(), &sig_b, &input), Err((0, PRECOMPILE_BAD_SIGNATURE)));
    assert_eq!(w.carry(&key, &w.key_b(), &sig_b, &input), Err((1, E_SIGNER)));
    // key B is somebody's registered key too, for another issuer: the token says the first issuer, so E_ISS
    let other = b"https://other.example".to_vec();
    w.send(&[w.register_private(&other, &w.key_b())]).unwrap();
    let key_b = w.private_key(&w.payer, &other, &w.key_b());
    assert_eq!(w.carry(&key_b, &w.key_b(), &sig_b, &input), Err((1, E_ISS)));
    assert!(w.data(&w.token_account(&input)).is_none());
}

/// A payload that is not the one signed, and a signature made for another message: the precompile refuses both.
#[test]
fn an_altered_payload_and_a_signature_for_another_message_are_refused() {
    let mut w = World::new();
    let key = w.with_private_key();
    let ((good, good_sig), (other, other_sig)) = (w.token("good"), w.token("other"));
    let mut altered = good.clone();
    let last = altered.len() - 2;
    altered[last] = if altered[last] == b'A' { b'B' } else { b'A' };
    assert_eq!(w.carry(&key, &w.key_a(), &good_sig, &altered), Err((0, PRECOMPILE_BAD_SIGNATURE)));
    assert_eq!(w.carry(&key, &w.key_a(), &good_sig, &other), Err((0, PRECOMPILE_BAD_SIGNATURE)));
    assert_eq!(w.carry(&key, &w.key_a(), &other_sig, &good), Err((0, PRECOMPILE_BAD_SIGNATURE)));
    // the precompile verified one token and VerifyEs256 is asked for the account of another: the address is the
    // hash of what was verified, so the account named is not that token's
    assert_eq!(w.send(&[precompile(&w.key_a(), &other_sig, &other), w.verify(&good, &key)]), Err((1, knos_oidc::E_ACCOUNTS)));
    assert!(w.data(&w.token_account(&good)).is_none() && w.data(&w.token_account(&other)).is_none());
}

/// No precompile instruction, another instruction in its place, or the precompile anywhere but right before: refused.
#[test]
fn the_precompile_must_be_the_instruction_right_before() {
    let mut w = World::new();
    let key = w.with_private_key();
    let (input, sig) = w.token("good");
    let (pre, verify) = (precompile(&w.key_a(), &sig, &input), w.verify(&input, &key));
    let other = system_instruction::transfer(&w.payer, &Pubkey::new_from_array([9; 32]), 1_000_000);
    assert_eq!(w.send(&[verify.clone()]), Err((0, E_PRECOMPILE)), "absent, and nothing before");
    assert_eq!(w.send(&[other.clone(), verify.clone()]), Err((1, E_PRECOMPILE)), "absent, another instruction before");
    assert_eq!(w.send(&[pre.clone(), other.clone(), verify.clone()]), Err((2, E_PRECOMPILE)), "two before");
    assert_eq!(w.send(&[verify.clone(), pre.clone()]), Err((0, E_PRECOMPILE)), "after");
    assert_eq!(w.send(&[other.clone(), verify.clone(), pre.clone()]), Err((1, E_PRECOMPILE)), "after, another before");
    assert!(w.data(&w.token_account(&input)).is_none());
    // and with it right before, wherever that is in the transaction
    assert!(w.send(&[other, pre, verify]).is_ok());
}

/// The precompile verifies the bytes its offsets name, in whatever instruction they name. A record that sends it to
/// another instruction's data for the signature, the key or the message passes the precompile (those bytes are a
/// good signature) while its own data holds something nobody signed: VerifyEs256 refuses each.
#[test]
fn offsets_that_point_at_another_instructions_data_are_refused() {
    let mut w = World::new();
    let key = w.with_private_key();
    let ((good, good_sig), (other, other_sig)) = (w.token("good"), w.token("other"));
    let (key_a, key_b) = (w.key_a(), w.key_b());
    // instruction 0: a Write of knos_oidc (any instruction with free data would do) whose chunk carries key A, its
    // signature of `other`, and `other`
    let carried = [&key_a[..], &other_sig, &other].concat();
    let id = [7u8; 32];
    let scratch = Pubkey::find_program_address(&[b"tok", w.payer.as_ref(), &id], &w.id).0;
    let write = Instruction { program_id: w.id, data: [&[0u8][..], &id, &(carried.len() as u16).to_le_bytes(), &0u16.to_le_bytes(), &carried].concat(),
                              accounts: vec![AccountMeta::new(w.payer, true), AccountMeta::new(scratch, false), AccountMeta::new_readonly(system_program::ID, false)] };
    let at = 37u16; // where the chunk starts in the Write's data
    // (the field of the record that leaves, where it goes in instruction 0, and the precompile's own key, signature, message)
    let cases: [(usize, u16, &[u8], &[u8], &[u8]); 3] = [
        (0, at + 33, &key_a, &good_sig, &other),      // the signature is taken from instruction 0; its own is another message's
        (2, at, &key_b, &other_sig, &other),          // the key is taken from instruction 0; its own is key B
        (4, at + 33 + 64, &key_a, &other_sig, &good), // the message is taken from instruction 0; its own was never signed with this signature
    ];
    for (field, offset, own_key, own_sig, own_msg) in cases {
        let mut pre = precompile(own_key, own_sig, own_msg);
        pre.data[2 + 2 * field..4 + 2 * field].copy_from_slice(&offset.to_le_bytes());
        let index = if field == 4 { 6 } else { field + 1 };
        pre.data[2 + 2 * index..4 + 2 * index].copy_from_slice(&0u16.to_le_bytes());
        if field == 4 { pre.data[12..14].copy_from_slice(&(other.len() as u16).to_le_bytes()); }
        // the precompile itself is content (instructions 0 and 1 run), and the program is not
        assert_eq!(w.send(&[write.clone(), pre.clone(), w.verify(own_msg, &key)]), Err((2, E_PRECOMPILE)), "field {field}");
        // the same record with every part its own does not verify at all: its own data is not a good signature
        assert_eq!(w.send(&[write.clone(), precompile(own_key, own_sig, own_msg), w.verify(own_msg, &key)]).map_err(|e| e.0), Err(1), "field {field}");
    }
    // two signatures in one precompile instruction, both good: which one is the token is not ours to choose
    let mut two = precompile(&key_a, &good_sig, &good);
    two.data[0] = 2;
    let shift = 14u16;
    let mut record = Vec::new();
    for v in [16 + 33 + shift, SELF, 16 + shift, SELF, 16 + 33 + 64 + shift, good.len() as u16, SELF] { record.extend_from_slice(&v.to_le_bytes()); }
    two.data = [&two.data[..2], &record, &record, &two.data[16..]].concat();
    assert_eq!(w.send(&[two, w.verify(&good, &key)]), Err((1, E_PRECOMPILE)));
    assert!(w.data(&w.token_account(&good)).is_none() && w.data(&w.token_account(&other)).is_none());
}

/// A header that does not say ES256, says it twice, a token of another issuer, and an expiry too far ahead: the
/// signature is good in every case, and the program refuses.
#[test]
fn a_well_signed_token_is_still_read_strictly() {
    let mut w = World::new();
    let key = w.with_private_key();
    for (name, code) in [("rs256", E_ALG), ("twice", claims::E_DUP), ("elsewhere", E_ISS), ("late", claims::E_CLAIM)] {
        let (input, sig) = w.token(name);
        assert_eq!(w.carry(&key, &w.key_a(), &sig, &input), Err((1, code)), "{name}");
        assert!(w.data(&w.token_account(&input)).is_none(), "{name}");
    }
}

/// One payer verifies one token once: the second time its account is there. The other spelling of the same
/// signature (the upper s) never reaches the program, so a token has one signature for a consumer's marker.
#[test]
fn a_token_already_used_is_refused() {
    let mut w = World::new();
    let key = w.with_private_key();
    let (input, sig) = w.token("good");
    assert!(w.carry(&key, &w.key_a(), &sig, &input).is_ok());
    let first = w.data(&w.token_account(&input)).unwrap();
    assert_eq!(w.carry(&key, &w.key_a(), &sig, &input), Err((1, E_STAGE)));
    let high = w.hex("good_sig_a_high");
    assert!(high[..32] == sig[..32] && high[32..] != sig[32..]);
    assert_eq!(w.carry(&key, &w.key_a(), &high, &input).map_err(|e| e.0), Err(0), "the precompile refuses the upper s");
    assert_eq!(w.data(&w.token_account(&input)).unwrap(), first);
    // nor can Write or Step touch a VERIFIED account
    let id = hashv(&[&input]).to_bytes();
    let write = Instruction { program_id: w.id, data: [&[0u8][..], &id, &(first.len() as u16 - T_JWT as u16).to_le_bytes(), &0u16.to_le_bytes(), b"x"].concat(),
                              accounts: vec![AccountMeta::new(w.payer, true), AccountMeta::new(w.token_account(&input), false), AccountMeta::new_readonly(system_program::ID, false)] };
    assert_eq!(w.send(&[write]), Err((0, E_STAGE)));
}

/// An RSA key's account is not taken for a P-256 key by VerifyEs256, and a P-256 key's account is not taken for an
/// RSA key by Step: each path reads only its own kind.
#[test]
fn an_rsa_key_is_not_an_es256_key_and_the_reverse() {
    let mut w = World::new();
    let ec = w.with_private_key();
    let (input, sig) = w.token("good");
    // an RSA key of the same issuer, registered by the same wallet (RegisterPrivateKey), and one that is ready and
    // approved, put there by hand with the same issuer hash
    let (url, n) = (w.issuer(), [0x81u8; 256]);
    let rsa = Pubkey::find_program_address(&[b"pkey", w.payer.as_ref(), hashv(&[&url]).as_ref(), hashv(&[&n]).as_ref()], &w.id).0;
    let register = Instruction { program_id: w.id, data: [&[9u8, url.len() as u8][..], &url, &n].concat(),
                                 accounts: vec![AccountMeta::new(w.payer, true), AccountMeta::new(rsa, false), AccountMeta::new_readonly(system_program::ID, false)] };
    w.send(&[register]).unwrap();
    assert_eq!(w.carry(&rsa, &w.key_a(), &sig, &input), Err((1, E_EC_KEY)));
    let ready = Pubkey::new_from_array([0x52; 32]);
    let mut d = vec![0u8; K_HDR + 8 * 64 + 64];
    d[K_STATE] = 1; d[K_ISSUER] = pins::ISSUER_OTHER; d[K_LIMBS] = 64; d[K_FLAGS] = F_GENESIS | F_APPROVED;
    d[K_EXPIRES..K_EXPIRES + 8].copy_from_slice(&(w.now() + 1000).to_le_bytes());
    d[K_HDR..K_HDR + 33].copy_from_slice(&w.key_a()); // even with the P-256 key's bytes where its modulus is
    let tail = d.len() - 64;
    d[tail..tail + 32].copy_from_slice(hashv(&[&url]).as_ref());
    w.svm.set_account(ready, Account { lamports: 10_000_000, data: d, owner: w.id, executable: false, rent_epoch: 0 }).unwrap();
    assert_eq!(w.carry(&ready, &w.key_a(), &sig, &input), Err((1, E_EC_KEY)));
    assert!(w.data(&w.token_account(&input)).is_none());

    // the reverse: an RS256 token's Step under the P-256 key account, and the guardian's RSA instructions on it
    let (id, jwt) = ([3u8; 32], b"aaaa.bbbb.cccc".to_vec());
    let tok = Pubkey::find_program_address(&[b"tok", w.payer.as_ref(), &id], &w.id).0;
    let write = Instruction { program_id: w.id, data: [&[0u8][..], &id, &(jwt.len() as u16).to_le_bytes(), &0u16.to_le_bytes(), &jwt].concat(),
                              accounts: vec![AccountMeta::new(w.payer, true), AccountMeta::new(tok, false), AccountMeta::new_readonly(system_program::ID, false)] };
    let step = Instruction { program_id: w.id, data: [&[1u8][..], &id, &[8]].concat(),
                             accounts: vec![AccountMeta::new(w.payer, true), AccountMeta::new(tok, false), AccountMeta::new_readonly(ec, false)] };
    assert_eq!(w.send(&[write, step]), Err((1, E_KEY)));
    let guardian = test_guardian();
    w.svm.airdrop(&guardian, 1_000_000_000).unwrap();
    for tag in [6u8, 7] {
        let ix = Instruction { program_id: w.id, data: vec![tag], accounts: vec![AccountMeta::new(guardian, true), AccountMeta::new(ec, false)] };
        assert_eq!(w.send(&[ix]), Err((0, E_KEY)), "tag {tag}");
    }
    // KeyParams (4) would write Montgomery constants into a key in state 0: a P-256 key is never in that state
    let params = Instruction { program_id: w.id, data: [&[4u8][..], &[0u8; 4 + 256]].concat(), accounts: vec![AccountMeta::new(w.payer, true), AccountMeta::new(ec, false)] };
    assert_eq!(w.send(&[params]), Err((0, E_STAGE)));
    assert_eq!(w.carry(&ec, &w.key_a(), &sig, &input).map(|_| ()), Ok(()), "and the key is as it was");
}

/// A key that GitHub's signature admits: it waits a day and for the guardian, verifies, is refreshed, and stops for
/// ever when the guardian revokes it. The attestation (a VERIFIED GitHub token of the rotate workflow, and the RSA
/// key that verified it) is put there by hand: how such an account comes to be is knos_oidc.rs's test.
#[test]
fn an_attested_key_waits_is_approved_verifies_and_is_revoked() {
    let mut w = World::new();
    let (url, key_a, now) = (w.issuer(), w.key_a(), w.now());
    let (ih, kh) = (hashv(&[&url]).to_bytes(), hashv(&[&key_a]).to_bytes());
    let (akey, guardian) = (Pubkey::new_from_array([0x61; 32]), test_guardian());
    w.svm.airdrop(&guardian, 1_000_000_000).unwrap();
    let mut d = vec![0u8; K_HDR + 8 * 64];
    d[K_STATE] = 1; d[K_ISSUER] = pins::ISSUER_GITHUB; d[K_LIMBS] = 64; d[K_FLAGS] = F_GENESIS | F_APPROVED;
    d[K_EXPIRES..K_EXPIRES + 8].copy_from_slice(&(now + 40 * 86_400).to_le_bytes());
    w.svm.set_account(akey, Account { lamports: 10_000_000, data: d, owner: w.id, executable: false, rent_epoch: 0 }).unwrap();
    let attest = |w: &mut World, at: u8, aud: &[u8], exp: i64| -> Pubkey {
        let payload = format!(r#"{{"job_workflow_ref":"{}refs/heads/main","job_workflow_sha":"{}","runner_environment":"github-hosted","repository_owner_id":"424242","repository_id":"987654321","event_name":"schedule","actor_id":"1","aud":"{}"}}"#,
                              String::from_utf8_lossy(pins::ROTATE_REF), "1".repeat(40), String::from_utf8_lossy(aud));
        let mut d = vec![0u8; T_JWT + payload.len()];
        d[T_STAGE] = VERIFIED; d[T_ISSUER] = pins::ISSUER_GITHUB;
        d[T_POFF..T_POFF + 2].copy_from_slice(&(T_JWT as u16).to_le_bytes());
        d[T_PLEN..T_PLEN + 2].copy_from_slice(&(payload.len() as u16).to_le_bytes());
        d[T_EXP..T_EXP + 8].copy_from_slice(&exp.to_le_bytes());
        d[T_KEY..T_KEY + 32].copy_from_slice(akey.as_ref());
        d[T_JWT..].copy_from_slice(payload.as_bytes());
        let at = Pubkey::new_from_array([at; 32]);
        w.svm.set_account(at, Account { lamports: 10_000_000, data: d, owner: w.id, executable: false, rent_epoch: 0 }).unwrap();
        at
    };
    let key = w.attested_key(&url, &key_a);
    let iss = Pubkey::find_program_address(&[b"iss", &ih], &w.id).0;
    let register = |w: &World, attest: Pubkey| Instruction { program_id: w.id, data: [&[10u8, url.len() as u8][..], &url, &key_a].concat(), accounts: vec![
        AccountMeta::new(w.payer, true), AccountMeta::new(key, false), AccountMeta::new(iss, false), AccountMeta::new_readonly(system_program::ID, false),
        AccountMeta::new_readonly(attest, false), AccountMeta::new_readonly(akey, false)] };
    // an attestation of an RSA key of the same hashes (RegisterIssuerKey's audience) admits no P-256 key
    let rsa_aud = format!("knos-oidc:ikey:{}:{}", hex::encode(ih), hex::encode(kh));
    let wrong = attest(&mut w, 0x62, rsa_aud.as_bytes(), now + 300);
    assert_eq!(w.send(&[register(&w, wrong)]), Err((0, E_ATTEST)));
    let good = attest(&mut w, 0x63, &ec_audience(&ih, &kh), now + 300);
    w.send(&[register(&w, good)]).unwrap();
    let k = w.data(&key).unwrap();
    assert_eq!((k[K_ISSUER], k[K_FLAGS], i64_at(&k, K_ACTIVE), i64_at(&k, K_EXPIRES)), (pins::ISSUER_OTHER, 0, now + pins::KEY_DELAY, now + pins::KEY_DELAY + pins::KEY_TTL));
    assert_eq!(&w.data(&iss).unwrap()[4..], &url[..]);
    assert_eq!(w.send(&[register(&w, good)]), Err((0, knos_oidc::E_ACCOUNTS)), "registered once");

    let (input, sig) = w.token("good");
    let (wid, payer) = (w.id, w.payer); // copied: the closures below must not hold `w`
    let call = |tag: u8, who: Pubkey| Instruction { program_id: wid, data: vec![tag], accounts: vec![AccountMeta::new(who, true), AccountMeta::new(key, false)] };
    assert_eq!(w.carry(&key, &key_a, &sig, &input), Err((1, E_INACTIVE)), "not approved, and inside its delay");
    assert_eq!(w.send(&[call(13, w.payer)]), Err((0, E_GUARDIAN)), "only the guardian approves");
    w.send(&[call(13, guardian)]).unwrap();
    assert_eq!(w.data(&key).unwrap()[K_FLAGS], F_APPROVED);
    assert_eq!(w.carry(&key, &key_a, &sig, &input), Err((1, E_INACTIVE)), "approved, and still inside its delay");
    w.clock(now + pins::KEY_DELAY);
    let cu = w.carry(&key, &key_a, &sig, &input).unwrap();
    println!("VerifyEs256 under an attested key: {cu} compute units for the transaction");
    let t = w.data(&w.token_account(&input)).unwrap();
    assert_eq!((knos_oidc::verified(&t).unwrap().issuer, knos_oidc::is_private(&t)), (pins::ISSUER_OTHER, false));
    assert_eq!(knos_oidc::issuer_hash(&t).unwrap(), &ih);

    // Refresh: the same audience, a later run; the expiry moves to now + KEY_TTL
    let later = w.now() + 86_400;
    w.clock(later);
    let again = attest(&mut w, 0x64, &ec_audience(&ih, &kh), later + 300);
    let refresh = |a: Pubkey| Instruction { program_id: wid, data: vec![12], accounts: vec![
        AccountMeta::new(payer, true), AccountMeta::new(key, false), AccountMeta::new_readonly(a, false), AccountMeta::new_readonly(akey, false)] };
    let stale = attest(&mut w, 0x65, rsa_aud.as_bytes(), later + 300);
    assert_eq!(w.send(&[refresh(stale)]), Err((0, E_ATTEST)));
    w.send(&[refresh(again)]).unwrap();
    assert_eq!(i64_at(&w.data(&key).unwrap(), K_EXPIRES), later + pins::KEY_TTL);

    // Revoke: the guardian only, and for ever
    assert_eq!(w.send(&[call(14, w.payer)]), Err((0, E_GUARDIAN)));
    w.send(&[call(14, guardian)]).unwrap();
    let (other, other_sig) = w.token("other");
    assert_eq!(w.carry(&key, &key_a, &other_sig, &other), Err((1, E_REVOKED)));
    assert_eq!(w.send(&[call(13, guardian)]), Err((0, E_REVOKED)));
    assert_eq!(w.send(&[refresh(again)]), Err((0, E_REVOKED)));
}

/// A private key is renewed and revoked by the wallet that registered it, and by no other wallet.
#[test]
fn a_private_key_is_its_registrants() {
    let mut w = World::new();
    let key = w.with_private_key();
    let (url, key_a, now) = (w.issuer(), w.key_a(), w.now());
    w.clock(now + 1000);
    w.send(&[w.register_private(&url, &key_a)]).unwrap();
    assert_eq!(i64_at(&w.data(&key).unwrap(), K_EXPIRES), now + 1000 + pins::KEY_TTL);
    let stranger = Pubkey::new_from_array([0x71; 32]);
    w.svm.airdrop(&stranger, 1_000_000_000).unwrap();
    let wid = w.id; // copied: the closure below must not hold `w`
    let call = |tag: u8, who: Pubkey| Instruction { program_id: wid, data: vec![tag], accounts: vec![AccountMeta::new(who, true), AccountMeta::new(key, false)] };
    assert_eq!(w.send(&[call(14, stranger)]), Err((0, E_GUARDIAN)));
    let guardian = test_guardian();
    w.svm.airdrop(&guardian, 1_000_000_000).unwrap();
    assert_eq!(w.send(&[call(13, guardian)]), Err((0, E_KEY)), "the guardian's approval is not for a private key");
    // the stranger's own registration of the same key is another account, and the first is untouched
    let mut theirs = w.register_private(&url, &key_a);
    theirs.accounts[0] = AccountMeta::new(stranger, true);
    assert_eq!(w.send(&[theirs.clone()]), Err((0, knos_oidc::E_ACCOUNTS)), "not at the first wallet's address");
    theirs.accounts[1] = AccountMeta::new(w.private_key(&stranger, &url, &key_a), false);
    w.send(&[theirs]).unwrap();
    w.send(&[call(14, w.payer)]).unwrap();
    let (input, sig) = w.token("good");
    assert_eq!(w.carry(&key, &key_a, &sig, &input), Err((1, E_REVOKED)));
    assert_eq!(w.send(&[w.register_private(&url, &key_a)]), Err((0, E_REVOKED)), "a revoked key stays revoked");
    // a key that is not a compressed point is not registered
    let mut bad = key_a.clone();
    bad[0] = 4;
    let mut ix = w.register_private(&url, &bad);
    ix.accounts[1] = AccountMeta::new(w.private_key(&w.payer, &url, &bad), false);
    assert_eq!(w.send(&[ix]), Err((0, E_EC_KEY)));
}
