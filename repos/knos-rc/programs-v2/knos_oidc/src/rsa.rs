//! RSA signature check (s^65537 mod n) for 2048- and 4096-bit keys, in Montgomery form, split so that it fits
//! Solana's per-transaction compute limit. Numbers are little-endian u32 limbs; `n.len()` is the limb count (64 or
//! 128). All scratch space is passed in, so nothing is allocated here.

pub const MAX_LIMBS: usize = 128;

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
pub fn load(d: &[u8], out: &mut [u32]) {
    for (i, o) in out.iter_mut().enumerate() { *o = u32::from_le_bytes([d[4 * i], d[4 * i + 1], d[4 * i + 2], d[4 * i + 3]]); }
}
pub fn store(d: &mut [u8], x: &[u32]) {
    for (i, v) in x.iter().enumerate() { d[4 * i..4 * i + 4].copy_from_slice(&v.to_le_bytes()); }
}
/// a >= b (same length)
pub fn geq(a: &[u32], b: &[u32]) -> bool {
    for i in (0..b.len()).rev() {
        if a[i] != b[i] { return a[i] > b[i]; }
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
    for v in t.iter_mut() { *v = 0; }
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
    if t[l] != 0 || geq(&out[..l], n) { sub_in(&mut out[..l], n); }
}

/// out = a^2 * R^-1 mod n for a < n: each cross product once, doubled, then one Montgomery reduction.
/// `t` is scratch of at least 2 l + 1 limbs.
pub fn mont_sqr(out: &mut [u32], a: &[u32], n: &[u32], n0inv: u32, t: &mut [u32]) {
    let l = n.len();
    let t = &mut t[..2 * l + 1];
    for v in t.iter_mut() { *v = 0; }
    for i in 0..l {
        let ai = a[i] as u64;
        let mut c = 0u64;
        for (tj, &aj) in t[2 * i + 1..i + l].iter_mut().zip(a[i + 1..l].iter()) {
            let s = *tj as u64 + ai * aj as u64 + c;
            *tj = s as u32;
            c = s >> 32;
        }
        t[i + l] = c as u32;
    }
    let mut top = 0u32;
    for v in t[..2 * l].iter_mut() {
        let w = *v;
        *v = (w << 1) | top;
        top = w >> 31;
    }
    let mut c = 0u64;
    for i in 0..l {
        let d = a[i] as u64 * a[i] as u64;
        let s = t[2 * i] as u64 + (d & 0xffff_ffff) + c;
        t[2 * i] = s as u32;
        let s = t[2 * i + 1] as u64 + (d >> 32) + (s >> 32);
        t[2 * i + 1] = s as u32;
        c = s >> 32;
    }
    let mut hi = 0u64;
    for i in 0..l {
        let m = t[i].wrapping_mul(n0inv) as u64;
        let mut c = 0u64;
        for (tj, &nj) in t[i..i + l].iter_mut().zip(n.iter()) {
            let s = *tj as u64 + m * nj as u64 + c;
            *tj = s as u32;
            c = s >> 32;
        }
        let s = t[i + l] as u64 + c + hi;
        t[i + l] = s as u32;
        hi = s >> 32;
    }
    out[..l].copy_from_slice(&t[l..2 * l]);
    if hi != 0 || geq(&out[..l], n) { sub_in(&mut out[..l], n); }
}

/// The key's parameters are right: n is odd with its top bit set, n0inv = -n^-1 mod 2^32, and r2 = R^2 mod n
/// (checked as r2 < n and r2 * R^-1 == R mod n, where R mod n = 2^(32 l) - n because n > R / 2).
/// `a`, `b` are scratch of l limbs, `t` of l + 2.
pub fn params_ok(n: &[u32], r2: &[u32], n0inv: u32, a: &mut [u32], b: &mut [u32], t: &mut [u32]) -> bool {
    let l = n.len();
    if (l != 64 && l != 128) || r2.len() != l { return false; }
    if n[0] & 1 == 0 || n[l - 1] >> 31 == 0 { return false; }
    if n[0].wrapping_mul(n0inv) != u32::MAX { return false; }
    if geq(r2, n) { return false; }
    for v in a[..l].iter_mut() { *v = 0; }
    a[0] = 1;
    mont_mul(b, r2, &a[..l], n, n0inv, t); // b = r2 * R^-1
    for v in a[..l].iter_mut() { *v = 0; }
    sub_in(&mut a[..l], n); // a = 2^(32 l) - n
    a[..l] == b[..l]
}

const DIGEST_INFO: [u8; 19] = [0x30, 0x31, 0x30, 0x0d, 0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01, 0x05, 0x00, 0x04, 0x20];
/// `em` (as long as the modulus) is exactly the PKCS#1 v1.5 encoding of a SHA-256 digest:
/// 00 01 FF..FF 00 DigestInfo digest. Every byte is compared, so no lenient parsing is possible.
pub fn pkcs1_sha256_ok(em: &[u8], digest: &[u8; 32]) -> bool {
    let k = em.len();
    if k < 11 + 19 + 32 { return false; }
    let ps_end = k - 32 - 19 - 1;
    em[0] == 0 && em[1] == 1 && em[2..ps_end].iter().all(|&c| c == 0xff) && em[ps_end] == 0
        && em[ps_end + 1..ps_end + 20] == DIGEST_INFO && em[k - 32..] == digest[..]
}

/// A whole verification in one call (used by the native tests; on chain it is split into steps).
/// n, sig are big-endian, the same length (256 or 512 bytes). r2 and n0inv are computed here the slow way.
#[cfg(not(target_os = "solana"))]
pub fn verify_native(n_be: &[u8], sig_be: &[u8], digest: &[u8; 32]) -> bool {
    let k = n_be.len();
    if (k != 256 && k != 512) || sig_be.len() != k { return false; }
    let l = k / 4;
    let mut n = vec![0u32; l]; be_to_limbs(n_be, &mut n);
    let mut s = vec![0u32; l]; be_to_limbs(sig_be, &mut s);
    if n[0] & 1 == 0 || n[l - 1] >> 31 == 0 || geq(&s, &n) { return false; }
    let mut inv: u32 = 1;
    for _ in 0..5 { inv = inv.wrapping_mul(2u32.wrapping_sub(n[0].wrapping_mul(inv))); }
    let n0inv = inv.wrapping_neg();
    // r2 = 2^(64 l) mod n by doubling 1 modulo n
    let mut r2 = vec![0u32; l]; r2[0] = 1;
    for _ in 0..64 * l {
        let top = r2[l - 1] >> 31;
        let mut carry = 0u32;
        for v in r2.iter_mut() { let w = *v; *v = (w << 1) | carry; carry = w >> 31; }
        if top != 0 || geq(&r2, &n) { sub_in(&mut r2, &n); }
    }
    let (mut a, mut b, mut t) = (vec![0u32; l], vec![0u32; l], vec![0u32; 2 * l + 2]);
    if !params_ok(&n, &r2, n0inv, &mut a, &mut b, &mut t) { return false; }
    let mut x = vec![0u32; l]; let mut y = vec![0u32; l];
    mont_mul(&mut x, &s, &r2, &n, n0inv, &mut t);
    for _ in 0..16 { mont_sqr(&mut y, &x, &n, n0inv, &mut t); core::mem::swap(&mut x, &mut y); }
    mont_mul(&mut y, &x, &s, &n, n0inv, &mut t);
    let mut em = vec![0u8; k]; limbs_to_be(&y, &mut em);
    pkcs1_sha256_ok(&em, digest)
}
