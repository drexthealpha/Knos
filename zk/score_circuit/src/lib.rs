//! The Knos private-score circuit: "the submission scored at least `threshold` on the sealed hidden test set",
//! proven without revealing the set or the submission.
//!
//! PRIVATE inputs (the witness): the N hidden labels and the salt of the sealed spec, the N predictions of the
//! submission and their salt.
//! PUBLIC inputs, in this order (each a BN254 scalar, 32 bytes big-endian on chain):
//!   0 spec_hash  = H(1, spec_salt, label_0 .. label_{N-1})   committed before any work starts (the sealed spec)
//!   1 pred_hash  = H(2, pred_salt, pred_0 .. pred_{N-1})     the worker's own commitment to its submission
//!   2 threshold  the bar: at least this many predictions equal their label (0 <= threshold < 2^16)
//! The proof exists only if count(pred_i == label_i) >= threshold; it says nothing else about the set.
//!
//! H is MiMC-7 (x^7, 91 rounds, the circomlib MultiMiMC7 chaining r' = r + x + MiMC7(x, r)), with round constants
//! c_0 = 0 and c_i = sha256("knos-zk-mimc7:" || i as u32 big-endian) mod r. src/knos/zk/mimc.py computes the same.
//! Salts are full field elements, so a set of a few labels cannot be found by trying every set against the hash.

use ark_bn254::Fr;
use ark_ff::{AdditiveGroup, Field, PrimeField};
use ark_r1cs_std::{
    alloc::AllocVar, boolean::Boolean, eq::EqGadget, fields::fp::FpVar, fields::FieldVar,
};
use ark_relations::r1cs::{ConstraintSynthesizer, ConstraintSystemRef, SynthesisError};
use sha2::{Digest, Sha256};

pub const MIMC_ROUNDS: usize = 91;
pub const DOMAIN_SPEC: u64 = 1;
pub const DOMAIN_PRED: u64 = 2;
/// threshold and the margin (count - threshold) must each fit this many bits
pub const RANGE_BITS: usize = 16;

pub fn mimc_constants() -> Vec<Fr> {
    let mut c = vec![Fr::ZERO];
    for i in 1..MIMC_ROUNDS as u32 {
        let mut h = Sha256::new();
        h.update(b"knos-zk-mimc7:");
        h.update(i.to_be_bytes());
        c.push(Fr::from_be_bytes_mod_order(&h.finalize()));
    }
    c
}

pub fn mimc7(x: Fr, k: Fr, c: &[Fr]) -> Fr {
    let mut x = x;
    for ci in c {
        let t = x + k + ci;
        let t2 = t.square();
        let t4 = t2.square();
        x = t4 * t2 * t;
    }
    x + k
}

/// H(domain, salt, xs) natively
pub fn multi_mimc(domain: u64, salt: Fr, xs: &[Fr]) -> Fr {
    let c = mimc_constants();
    let mut r = Fr::ZERO;
    for x in [Fr::from(domain), salt].iter().chain(xs.iter()) {
        r = r + x + mimc7(*x, r, &c);
    }
    r
}

fn mimc7_var(x: &FpVar<Fr>, k: &FpVar<Fr>, c: &[Fr]) -> Result<FpVar<Fr>, SynthesisError> {
    let mut x = x.clone();
    for ci in c {
        let t = &x + k + FpVar::constant(*ci);
        let t2 = t.square()?;
        let t4 = t2.square()?;
        x = &t4 * &t2 * &t;
    }
    Ok(x + k)
}

fn multi_mimc_var(domain: u64, salt: &FpVar<Fr>, xs: &[FpVar<Fr>], c: &[Fr]) -> Result<FpVar<Fr>, SynthesisError> {
    let mut r = FpVar::constant(Fr::ZERO);
    let d = FpVar::constant(Fr::from(domain));
    for x in [&d, salt].into_iter().chain(xs.iter()) {
        let m = mimc7_var(x, &r, c)?;
        r = &r + x + m;
    }
    Ok(r)
}

/// v fits RANGE_BITS bits: witness the bits, recompose, compare
fn range_check(cs: &ConstraintSystemRef<Fr>, v: &FpVar<Fr>, value: Option<Fr>) -> Result<(), SynthesisError> {
    let n = value.map(|f| f.into_bigint());
    let mut acc = FpVar::constant(Fr::ZERO);
    let mut pow = Fr::ONE;
    for i in 0..RANGE_BITS {
        let bit = Boolean::new_witness(cs.clone(), || {
            n.map(|b| {
                let limb = b.0[i / 64];
                (limb >> (i % 64)) & 1 == 1
            })
            .ok_or(SynthesisError::AssignmentMissing)
        })?;
        acc += FpVar::from(bit) * FpVar::constant(pow);
        pow.double_in_place();
    }
    acc.enforce_equal(v)
}

#[derive(Clone)]
pub struct ScoreCircuit {
    pub labels: Vec<Fr>,
    pub preds: Vec<Fr>,
    pub spec_salt: Fr,
    pub pred_salt: Fr,
    pub threshold: u64,
}

impl ScoreCircuit {
    pub fn correct(&self) -> u64 {
        self.labels.iter().zip(&self.preds).filter(|(a, b)| a == b).count() as u64
    }
    pub fn public_inputs(&self) -> Vec<Fr> {
        vec![
            multi_mimc(DOMAIN_SPEC, self.spec_salt, &self.labels),
            multi_mimc(DOMAIN_PRED, self.pred_salt, &self.preds),
            Fr::from(self.threshold),
        ]
    }
}

impl ConstraintSynthesizer<Fr> for ScoreCircuit {
    fn generate_constraints(self, cs: ConstraintSystemRef<Fr>) -> Result<(), SynthesisError> {
        assert_eq!(self.labels.len(), self.preds.len());
        let c = mimc_constants();
        let public = self.public_inputs();
        let spec_hash = FpVar::new_input(cs.clone(), || Ok(public[0]))?;
        let pred_hash = FpVar::new_input(cs.clone(), || Ok(public[1]))?;
        let threshold = FpVar::new_input(cs.clone(), || Ok(public[2]))?;

        let spec_salt = FpVar::new_witness(cs.clone(), || Ok(self.spec_salt))?;
        let pred_salt = FpVar::new_witness(cs.clone(), || Ok(self.pred_salt))?;
        let labels = self
            .labels
            .iter()
            .map(|v| FpVar::new_witness(cs.clone(), || Ok(*v)))
            .collect::<Result<Vec<_>, _>>()?;
        let preds = self
            .preds
            .iter()
            .map(|v| FpVar::new_witness(cs.clone(), || Ok(*v)))
            .collect::<Result<Vec<_>, _>>()?;

        multi_mimc_var(DOMAIN_SPEC, &spec_salt, &labels, &c)?.enforce_equal(&spec_hash)?;
        multi_mimc_var(DOMAIN_PRED, &pred_salt, &preds, &c)?.enforce_equal(&pred_hash)?;

        let mut correct = FpVar::constant(Fr::ZERO);
        for (l, p) in labels.iter().zip(&preds) {
            correct += FpVar::from(l.is_eq(p)?);
        }
        // threshold < 2^16 and correct - threshold in [0, 2^16): with correct <= N < 2^16, a threshold above the
        // count makes the difference wrap to a field element far above 2^16, and no bits recompose to it.
        range_check(&cs, &threshold, Some(public[2]))?;
        let margin = &correct - &threshold;
        let margin_value = Fr::from(self.correct()) - public[2];
        range_check(&cs, &margin, Some(margin_value))?;
        Ok(())
    }
}

// ---- byte encodings (big-endian, the alt_bn128 syscall / EIP-197 layout) ----

pub fn fr_be(x: &Fr) -> [u8; 32] {
    use ark_ff::BigInteger;
    let v = x.into_bigint().to_bytes_be();
    let mut out = [0u8; 32];
    out[32 - v.len()..].copy_from_slice(&v);
    out
}

pub fn fq_be(x: &ark_bn254::Fq) -> [u8; 32] {
    use ark_ff::BigInteger;
    let v = x.into_bigint().to_bytes_be();
    let mut out = [0u8; 32];
    out[32 - v.len()..].copy_from_slice(&v);
    out
}

pub fn g1_be(p: &ark_bn254::G1Affine) -> [u8; 64] {
    let mut out = [0u8; 64];
    out[..32].copy_from_slice(&fq_be(&p.x));
    out[32..].copy_from_slice(&fq_be(&p.y));
    out
}

/// G2 as (x.c1, x.c0, y.c1, y.c0), the order the alt_bn128 pairing syscall reads
pub fn g2_be(p: &ark_bn254::G2Affine) -> [u8; 128] {
    let mut out = [0u8; 128];
    out[..32].copy_from_slice(&fq_be(&p.x.c1));
    out[32..64].copy_from_slice(&fq_be(&p.x.c0));
    out[64..96].copy_from_slice(&fq_be(&p.y.c1));
    out[96..].copy_from_slice(&fq_be(&p.y.c0));
    out
}

/// the SYNTHETIC sample: N labels in 0..10 from a fixed seed, a submission that gets `correct` of them right
pub fn synthetic_sample(n: usize, correct: usize, threshold: u64) -> ScoreCircuit {
    let seed = |tag: &str, i: u64| -> u64 {
        let mut h = Sha256::new();
        h.update(b"knos-zk-synthetic:");
        h.update(tag.as_bytes());
        h.update(i.to_be_bytes());
        u64::from_be_bytes(h.finalize()[..8].try_into().unwrap())
    };
    let labels: Vec<u64> = (0..n as u64).map(|i| seed("label", i) % 10).collect();
    let preds: Vec<u64> = labels
        .iter()
        .enumerate()
        .map(|(i, l)| if i < correct { *l } else { (*l + 1 + seed("miss", i as u64) % 9) % 10 })
        .collect();
    let salt = |tag: &str| {
        let mut h = Sha256::new();
        h.update(b"knos-zk-synthetic-salt:");
        h.update(tag.as_bytes());
        Fr::from_be_bytes_mod_order(&h.finalize())
    };
    ScoreCircuit {
        labels: labels.into_iter().map(Fr::from).collect(),
        preds: preds.into_iter().map(Fr::from).collect(),
        spec_salt: salt("spec"),
        pred_salt: salt("pred"),
        threshold,
    }
}

pub const SAMPLE_N: usize = 64;
pub const SAMPLE_CORRECT: usize = 52;
pub const SAMPLE_THRESHOLD: u64 = 48;
/// the toy setup's seed. A FIXED seed means anyone can recompute the toxic waste: this setup is for tests and the
/// devnet demo only. A deployment that pays real money needs a multi-party setup ceremony (docs/reference/ZK.md).
pub const TOY_SETUP_SEED: u64 = 0x4b4e_4f53_5a4b_0329;
