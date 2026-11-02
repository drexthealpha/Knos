//! RS256 (RSA-2048, PKCS#1 v1.5, SHA-256) in pure Rust: s^65537 mod n in Montgomery form, then every byte of the
//! encoding compared. Taken from programs-v2/knos_oidc/src/rsa.rs (the Solana verifier), where it runs in steps; here
//! one call does it all. Numbers are little-endian u32 limbs.

pub const LIMBS: usize = 64;

pub fn be_to_limbs(b: &[u8], out: &mut [u32]) {
    let l = out.len();
    for (i, o) in out.iter_mut().enumerate() {
        let p = 4 * (l - 1 - i);
        *o = u32::from_be_bytes([b[p], b[p + 1], b[p + 2], b[p + 3]]);
    }
}

pub fn limbs_to_be(x: &[u32], out: &mut [u8]) {
    let l = x.len();
    for (i, v) in x.iter().enumerate() {
        let p = 4 * (l - 1 - i);
        out[p..p + 4].copy_from_slice(&v.to_be_bytes());
    }
}

/// a >= b (same length)
pub fn geq(a: &[u32], b: &[u32]) -> bool {
    for i in (0..b.len()).rev() {
        if a[i] != b[i] {
            return a[i] > b[i];
        }
    }
    true
}

/// a -= b (mod 2^(32 l))
pub fn sub_in(a: &mut [u32], b: &[u32]) {
    let mut borrow = 0u64;
    for (x, y) in a.iter_mut().zip(b.iter()) {
        let d = (*x as u64).wrapping_sub(*y as u64).wrapping_sub(borrow);
        *x = d as u32;
        borrow = (d >> 63) & 1;
    }
}

/// out = a * b * R^-1 mod n (R = 2^(32 l)), for a, b < n. `t` is scratch of at least l + 2 limbs.
pub fn mont_mul(out: &mut [u32], a: &[u32], b: &[u32], n: &[u32], n0inv: u32, t: &mut [u32]) {
    let l = n.len();
    let t = &mut t[..l + 2];
    for v in t.iter_mut() {
        *v = 0;
    }
    for &ai in a[..l].iter() {
        let ai = ai as u64;
        let mut c = 0u64;
        for (tj, &bj) in t[..l].iter_mut().zip(b[..l].iter()) {
            let s = *tj as u64 + ai * bj as u64 + c;
            *tj = s as u32;
            c = s >> 32;
        }
        let s = t[l] as u64 + c;
        t[l] = s as u32;
        t[l + 1] = (s >> 32) as u32;
        let m = t[0].wrapping_mul(n0inv) as u64;
        let mut c = (t[0] as u64 + m * n[0] as u64) >> 32;
        for j in 1..l {
            let s = t[j] as u64 + m * n[j] as u64 + c;
            t[j - 1] = s as u32;
            c = s >> 32;
        }
        let s = t[l] as u64 + c;
        t[l - 1] = s as u32;
        t[l] = t[l + 1].wrapping_add((s >> 32) as u32);
        t[l + 1] = 0;
    }
    out[..l].copy_from_slice(&t[..l]);
    if t[l] != 0 || geq(&out[..l], n) {
        sub_in(&mut out[..l], n);
    }
}

/// The Montgomery constants of a modulus: n0inv = -n^-1 mod 2^32 and r2 = R^2 mod n. None unless n is a 2048-bit odd
/// number with its top bit set. Computed once, when the owners set the key.
pub fn constants(n_be: &[u8]) -> Option<(Vec<u32>, u32, Vec<u32>)> {
    if n_be.len() != 4 * LIMBS {
        return None;
    }
    let l = LIMBS;
    let mut n = vec![0u32; l];
    be_to_limbs(n_be, &mut n);
    if n[0] & 1 == 0 || n[l - 1] >> 31 == 0 {
        return None;
    }
    let mut inv: u32 = 1;
    for _ in 0..5 {
        inv = inv.wrapping_mul(2u32.wrapping_sub(n[0].wrapping_mul(inv)));
    }
    let n0inv = inv.wrapping_neg();
    // r2 = 2^(64 l) mod n, by doubling 1 modulo n
    let mut r2 = vec![0u32; l];
    r2[0] = 1;
    for _ in 0..64 * l {
        let top = r2[l - 1] >> 31;
        let mut carry = 0u32;
        for v in r2.iter_mut() {
            let w = *v;
            *v = (w << 1) | carry;
            carry = w >> 31;
        }
        if top != 0 || geq(&r2, &n) {
            sub_in(&mut r2, &n);
        }
    }
    Some((n, n0inv, r2))
}

const DIGEST_INFO: [u8; 19] = [0x30, 0x31, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01, 0x05, 0x00, 0x04, 0x20];

/// `em` is exactly the PKCS#1 v1.5 encoding of a SHA-256 digest: 00 01 FF..FF 00 DigestInfo digest, every byte compared.
pub fn pkcs1_sha256_ok(em: &[u8], digest: &[u8]) -> bool {
    let k = em.len();
    if k < 11 + 19 + 32 || digest.len() != 32 {
        return false;
    }
    let ps_end = k - 32 - 19 - 1;
    em[0] == 0 && em[1] == 1 && em[2..ps_end].iter().all(|&c| c == 0xff) && em[ps_end] == 0
        && em[ps_end + 1..ps_end + 20] == DIGEST_INFO && em[k - 32..] == digest[..]
}

/// The signature `sig_be` (256 bytes, big-endian) over a message whose SHA-256 is `digest`, under the key (n, n0inv, r2).
pub fn verify(n: &[u32], n0inv: u32, r2: &[u32], sig_be: &[u8], digest: &[u8]) -> bool {
    let l = n.len();
    if l != LIMBS || r2.len() != l || sig_be.len() != 4 * l {
        return false;
    }
    let mut s = vec![0u32; l];
    be_to_limbs(sig_be, &mut s);
    if geq(&s, n) {
        return false;
    }
    let (mut x, mut y, mut t) = (vec![0u32; l], vec![0u32; l], vec![0u32; l + 2]);
    mont_mul(&mut x, &s, r2, n, n0inv, &mut t); // s in Montgomery form
    for _ in 0..16 {
        mont_mul(&mut y, &x, &x, n, n0inv, &mut t);
        core::mem::swap(&mut x, &mut y);
    }
    mont_mul(&mut y, &x, &s, n, n0inv, &mut t); // s^65537, back out of Montgomery form
    let mut em = vec![0u8; 4 * l];
    limbs_to_be(&y, &mut em);
    pkcs1_sha256_ok(&em, digest)
}
