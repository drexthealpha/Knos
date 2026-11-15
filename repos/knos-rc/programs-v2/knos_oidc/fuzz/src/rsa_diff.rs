//! One question for every input, asked of three voices: is this an RS256 signature? The program's arithmetic
//! (programs-v2/knos_oidc/src/rsa.rs: Montgomery multiplication on 32-bit limbs, written by hand), big integers
//! (s^65537 mod n by `modpow`, and the encoding of RFC 8017 section 9.2 made again and compared), and the `rsa`
//! crate's own PKCS#1 v1.5 verification. `agree` is what the nightly fuzz target `rsa_verify` calls on any bytes and what
//! tests/seeds.rs calls on the committed seeds under `cargo test` on stable.
//!
//! An input is: one byte of flags, the 32 bytes of a digest, then
//!   flags & 2 == 0   a modulus of 256 bytes (512 when flags & 1) and a signature of any length: anybody's key, as
//!                    a Wycheproof vector gives it. The modulus is the fuzzer's to choose, so the arithmetic is asked
//!                    under moduli no test wrote down; where the program takes the modulus at all (odd, top bit set)
//!                    the value s^65537 mod n is compared whole, not only the verdict;
//!   flags & 2 != 0   an encoded message of 256 bytes, which the 2048-bit test key (the seed key of tests/_settle.py)
//!                    signs here: the fuzzer writes what the signature OPENS to, which is how a wrong encoding is
//!                    reached (a random signature opens to noise). Bytes missing at the end are zero.
use knos_oidc::rsa as program;
use rsa::{BigUint, Pkcs1v15Sign, RsaPublicKey};

const P: &str = "f55808985a3bd0420821f7444729fd56705a2efbe9625e0de2bc0d95c08e75f3eb7002fcf657a03fa25cb7a84204e1788f66ba06a9be9a9e78aea4f6a6c1992b9a825e67492d787b3f7952680b84c964069c7b03239cec0eb98ca64b848ec6f8c60e2fb752b4f1c314f24c5917a38bfd00e99ed454cf445361f577186a144b8d";
const Q: &str = "eb6a15a0efc90803653f7b78f600312406802224da42a880ee720fd62063ea9bc036962f1861a3fc2111043bdb99a47bbde9385c9e08056b4f047f4bb80d8cfae88fb80ea75aabf7f6ec0b5ee821d651b48eea9c783fcc5833a5b9df8f774a6532d7c2c543eb7100ae05538dd820ad8851556b299e37de598cbf44e0788eada5";
/// DigestInfo for SHA-256 (RFC 8017 section 9.2, note 1), written here and not taken from the program.
const T: [u8; 19] = [0x30, 0x31, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01, 0x05, 0x00, 0x04, 0x20];

fn hex(s: &str) -> BigUint { BigUint::parse_bytes(s.as_bytes(), 16).unwrap() }
fn be(x: &BigUint, k: usize) -> Vec<u8> {
    let b = x.to_bytes_be();
    let mut out = vec![0u8; k - b.len()];
    out.extend_from_slice(&b);
    out
}

/// EMSA-PKCS1-v1_5 of a SHA-256 digest, k bytes.
pub fn encoding(k: usize, digest: &[u8; 32]) -> Vec<u8> {
    let mut em = vec![0xffu8; k];
    em[0] = 0; em[1] = 1; em[k - 52] = 0;
    em[k - 51..k - 32].copy_from_slice(&T);
    em[k - 32..].copy_from_slice(digest);
    em
}

/// s^65537 mod n as the chain computes it: the key's parameters, s into Montgomery form, sixteen squarings, one
/// multiplication, in the program's own functions. For a modulus the program takes and s below it.
pub fn stepped(n_be: &[u8], sig: &[u8]) -> Vec<u8> {
    let (k, l) = (n_be.len(), n_be.len() / 4);
    let (mut n, mut s, mut r2) = (vec![0u32; l], vec![0u32; l], vec![0u32; l]);
    program::be_to_limbs(n_be, &mut n);
    program::be_to_limbs(sig, &mut s);
    program::be_to_limbs(&be(&((BigUint::from(1u8) << (64 * l)) % BigUint::from_bytes_be(n_be)), k), &mut r2);
    let mut inv: u32 = 1;
    for _ in 0..5 { inv = inv.wrapping_mul(2u32.wrapping_sub(n[0].wrapping_mul(inv))); }
    let n0inv = inv.wrapping_neg();
    let (mut a, mut b, mut t) = (vec![0u32; l], vec![0u32; l], vec![0u32; 2 * l + 2]);
    assert!(program::params_ok(&n, &r2, n0inv, &mut a, &mut b, &mut t), "params_ok refuses the right parameters of {n_be:02x?}");
    let (mut x, mut y) = (vec![0u32; l], vec![0u32; l]);
    program::mont_mul(&mut x, &s, &r2, &n, n0inv, &mut t);
    for _ in 0..16 { program::mont_sqr(&mut y, &x, &n, n0inv, &mut t); core::mem::swap(&mut x, &mut y); }
    program::mont_mul(&mut y, &x, &s, &n, n0inv, &mut t);
    let mut em = vec![0u8; k];
    program::limbs_to_be(&y, &mut em);
    em
}

/// The 2048-bit test key, worked out once: n, p, q, d mod (p-1), d mod (q-1), q^-1 mod p.
fn test_key() -> &'static [BigUint; 6] {
    static KEY: std::sync::OnceLock<[BigUint; 6]> = std::sync::OnceLock::new();
    KEY.get_or_init(|| {
        let (p, q, one, e) = (hex(P), hex(Q), BigUint::from(1u8), BigUint::from(65537u32));
        let phi = (&p - &one) * (&q - &one);
        // d = e^-1 mod (p-1)(q-1): e*d = 1 + j*phi for the one j below e that makes the right side a multiple of e
        let d = (1u32..65537).map(|j| &one + &phi * BigUint::from(j)).find(|v| (v % &e) == BigUint::from(0u8)).unwrap() / &e;
        let qinv = q.modpow(&(&p - BigUint::from(2u8)), &p);          // p is prime
        [&p * &q, p.clone(), q.clone(), &d % (&p - &one), &d % (&q - &one), qinv]
    })
}

/// The test key's modulus, and its signature that opens to `em` (None when `em` is not below the modulus).
fn test_key_signs(em: &[u8]) -> (Vec<u8>, Option<Vec<u8>>) {
    let [n, p, q, dp, dq, qinv] = test_key();
    let m = BigUint::from_bytes_be(em);
    if m >= *n { return (be(n, 256), None); }
    let (sp, sq) = (m.modpow(dp, p), m.modpow(dq, q));
    // Garner: s = sq + q * ((sp - sq) * q^-1 mod p)
    let h = ((&sp + p - (&sq % p)) % p) * qinv % p;
    (be(n, 256), Some(be(&(sq + q * h), 256)))
}

/// Panics if the three voices differ on `data`.
pub fn agree(data: &[u8]) {
    if data.len() < 33 { return; }
    let (flags, digest, rest) = (data[0], <[u8; 32]>::try_from(&data[1..33]).unwrap(), &data[33..]);
    let (n_be, sig) = if flags & 2 != 0 {
        let mut em = [0u8; 256];
        let take = rest.len().min(256);
        em[..take].copy_from_slice(&rest[..take]);
        match test_key_signs(&em) {
            (n, Some(sig)) => {
                assert_eq!(stepped(&n, &sig), em, "the signature the test key made does not open to what it signed");
                (n, sig)
            }
            (_, None) => return,
        }
    } else {
        let k = if flags & 1 == 0 { 256 } else { 512 };
        if rest.len() < k { return; }
        (rest[..k].to_vec(), rest[k..].to_vec())
    };
    let k = n_be.len();
    let got = program::verify_native(&n_be, &sig, &digest);

    // big integers: RFC 8017 section 8.2.2, for the moduli the program takes (odd, as long as they say)
    let (n, s) = (BigUint::from_bytes_be(&n_be), BigUint::from_bytes_be(&sig));
    let taken = n_be[0] & 0x80 != 0 && n_be[k - 1] & 1 == 1;
    let opened = (taken && sig.len() == k && s < n).then(|| be(&s.modpow(&BigUint::from(65537u32), &n), k));
    let want = opened.as_ref().is_some_and(|em| *em == encoding(k, &digest));
    assert_eq!(got, want, "rsa.rs says {got}, big integers say {want}: modulus {n_be:02x?} signature {sig:02x?} digest {digest:02x?}");
    if let Some(em) = &opened {
        assert_eq!(&stepped(&n_be, &sig), em, "s^65537 mod n differs: modulus {n_be:02x?} signature {sig:02x?}");
    }

    // the rsa crate, where it takes the key (it refuses none the program takes: the size is at most 4096 bits)
    if taken {
        let key = RsaPublicKey::new(n, BigUint::from(65537u32)).expect("a modulus of 2048 or 4096 bits");
        let theirs = key.verify(Pkcs1v15Sign::new::<rsa::sha2::Sha256>(), &digest, &sig).is_ok();
        assert_eq!(got, theirs, "rsa.rs says {got}, the rsa crate says {theirs}: modulus {n_be:02x?} signature {sig:02x?} digest {digest:02x?}");
    }
}
