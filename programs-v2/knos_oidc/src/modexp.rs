//! s^65537 mod n for Step, in whichever arithmetic this build has (v0.3.29; v3 since v0.3.30).
//!   - sBPF v2 and v3 builds (build.rs sets `knos_wide`) and native builds: rsa64.rs, 64-bit limbs. One 2048-bit
//!     verification fits ONE transaction: Step(16) does the Montgomery entry, all 16 squarings, the last product and
//!     the token's checks in one call. The v3 of Agave 4.4 has no `uhmul64`: there each 128-bit product is four 32-bit
//!     ones (rsa64::h), and Step(16) fits a token of up to 5,000 bytes, not MAX_JWT (docs/reference/PLATFORM.md).
//!   - sBPF v0 and v1 builds: rsa.rs, 32-bit limbs, as before (two transactions for a 2048-bit key: Step(8),
//!     Step(8)).
//!   - feature `big_mod_exp`: the runtime's sol_big_mod_exp syscall does the whole power in one call. Only for a
//!     cluster where that syscall is active: on one where it is not, a program that names it does not even load.
//!     Devnet does not have it active (docs/reference/PLATFORM.md), so no deployed build enables this feature.
//!
//! The running power is kept in the token account (T_X) as the same 512 little-endian bytes in every arithmetic,
//! so the steps of one token may run under different builds of this program (an upgrade between two Steps).

#[cfg(any(knos_wide, not(target_os = "solana")))]
use crate::rsa64 as w;
#[cfg(any(knos_wide, not(target_os = "solana")))]
type Limb = u64;
#[cfg(not(any(knos_wide, not(target_os = "solana"))))]
use crate::rsa as w;
#[cfg(not(any(knos_wide, not(target_os = "solana"))))]
type Limb = u32;

/// The limb width of this build: 64 (sBPF v2+ and native) or 32.
pub const LIMB_BITS: u32 = Limb::BITS;

pub struct Pow { n: Vec<Limb>, n0: Limb, s: Vec<Limb>, x: Vec<Limb>, y: Vec<Limb>, t: Vec<Limb> }

impl Pow {
    /// The key (n, its n0inv, as rsa.rs limbs) and the signature s < n (rsa.rs limbs).
    pub fn new(n32: &[u32], n0inv32: u32, s32: &[u32]) -> Pow {
        let l32 = n32.len();
        let l = l32 * 32 / Limb::BITS as usize;
        let (n, s) = (conv(n32, l), conv(s32, l));
        let n0 = n0_of(&n, n0inv32);
        Pow { n, n0, s, x: vec![0; l], y: vec![0; l], t: vec![0; 2 * l + 2] }
    }
    /// x = s in Montgomery form (s r2 R^-1 = s R).
    pub fn enter(&mut self, r2_32: &[u32]) {
        let r2 = conv(r2_32, self.n.len());
        w::mont_mul(&mut self.x, &self.s, &r2, &self.n, self.n0, &mut self.t);
    }
    pub fn load(&mut self, d: &[u8]) { w::load(d, &mut self.x); }
    pub fn store(&self, d: &mut [u8]) { w::store(d, &self.x); }
    pub fn square(&mut self, times: usize) {
        for _ in 0..times {
            w::mont_sqr(&mut self.y, &self.x, &self.n, self.n0, &mut self.t);
            core::mem::swap(&mut self.x, &mut self.y);
        }
    }
    /// After 16 squarings: s^65536 R times s, out of Montgomery form: s^65537 mod n, big-endian.
    pub fn finish(&mut self, out: &mut [u8]) {
        w::mont_mul(&mut self.y, &self.x, &self.s, &self.n, self.n0, &mut self.t);
        let mut y32 = vec![0u32; out.len() / 4];
        back(&self.y, &mut y32);
        crate::rsa::limbs_to_be(&y32, out);
    }
}

#[cfg(any(knos_wide, not(target_os = "solana")))]
fn conv(x: &[u32], l: usize) -> Vec<u64> { let mut o = vec![0u64; l]; crate::rsa64::from32(x, &mut o); o }
#[cfg(any(knos_wide, not(target_os = "solana")))]
fn back(x: &[u64], o: &mut [u32]) { crate::rsa64::to32(x, o) }
#[cfg(any(knos_wide, not(target_os = "solana")))]
fn n0_of(n: &[u64], n0inv32: u32) -> u64 {
    let v = crate::rsa64::n0inv64(n[0]);
    debug_assert_eq!(v as u32, n0inv32);
    v
}
#[cfg(not(any(knos_wide, not(target_os = "solana"))))]
fn conv(x: &[u32], _l: usize) -> Vec<u32> { x.to_vec() }
#[cfg(not(any(knos_wide, not(target_os = "solana"))))]
fn back(x: &[u32], o: &mut [u32]) { o.copy_from_slice(x) }
#[cfg(not(any(knos_wide, not(target_os = "solana"))))]
fn n0_of(_n: &[u32], n0inv32: u32) -> u32 { n0inv32 }

/// s^65537 mod n by the runtime's syscall (feature `big_mod_exp`), big-endian, as long as n.
#[cfg(feature = "big_mod_exp")]
pub fn syscall(sig_be: &[u8], n_be: &[u8], out: &mut [u8]) {
    let r = solana_program::big_mod_exp::big_mod_exp(sig_be, &[1, 0, 1], n_be);
    // the syscall returns the result left-padded to the modulus's length
    out.fill(0);
    let k = out.len().min(r.len());
    let at = out.len() - k;
    out[at..].copy_from_slice(&r[r.len() - k..]);
}

/// How many Step transactions a key of `bits` needs in this build: what the client's plan must match.
pub const fn one_transaction(bits: usize) -> bool {
    cfg!(feature = "big_mod_exp") || (LIMB_BITS == 64 && bits == 2048)
}
