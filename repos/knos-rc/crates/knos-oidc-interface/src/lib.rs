//! Read a token that knos-oidc verified. knos-oidc is a Solana program that checks the RS256 signature of an OIDC
//! token (GitHub Actions, GitLab CI, any other RS256 issuer it admitted) on chain and leaves the result in an
//! account it owns. Your program takes that account and reads the claims the issuer signed: which repository, which
//! commit, which workflow, which audience. There is no CPI and no oracle.
//!
//! This crate has no dependency and does not allocate: bytes in, values out. It works with solana-program,
//! pinocchio or anchor of any version, and off chain.
//!
//! There are two deployments of knos-oidc, and this crate reads the SECOND unless you name the first: `ID`,
//! `Token::read` and `Token::read_any` are the second deployment's (`v2` is the same thing by name). It admits
//! signing keys on GitHub's own signature, lets them expire and lets a guardian revoke them; it is upgradeable only
//! through a multisig with a public 48-hour delay, until an outside review. The first deployment (`v1::ID`,
//! `v1::read`) is immutable: no key of it expires and none can be revoked, so a program reads it only by naming it.
//! A token account has the same layout under both; a token one deployment verified says nothing under the other.
//!
//! ```ignore
//! let data = token_account.try_borrow_data()?;
//! let tok = Token::read(&token_account.owner.to_bytes(), &data, clock.unix_timestamp).map_err(|_| MyError::Token)?;
//! if tok.issuer() != ISSUER_GITHUB { return Err(MyError::Token.into()); }
//! let repo = tok.claim_u64("repository_id").ok_or(MyError::Claims)?;
//! ```
#![no_std]
#[cfg(feature = "alloc")]
extern crate alloc;

/// The knos-oidc program this crate reads by default: the second deployment (devnet), as bytes. A token account
/// must be owned by it.
pub const ID: [u8; 32] = [
    0xdb, 0x45, 0x49, 0x36, 0x35, 0xef, 0x28, 0x0d, 0xfb, 0xbe, 0x73, 0x6a, 0x6d, 0xfa, 0xd8, 0xbc,
    0xf8, 0x60, 0x38, 0xc2, 0xa5, 0x39, 0x74, 0xf7, 0x64, 0x1d, 0x78, 0x42, 0xb8, 0xaa, 0x41, 0x71,
];
/// The same address as Solana prints it.
pub const ID_STR: &str = "FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W";

/// The second deployment of knos-oidc by name: the same address and the same reader as the crate's defaults, for a
/// program that wants its choice written out.
pub mod v2 {
    use super::{Error, Token};

    pub const ID: [u8; 32] = super::ID;
    pub const ID_STR: &str = super::ID_STR;

    /// `Token::read`: the account is owned by the second deployment, VERIFIED, at most `LATE` seconds past its
    /// expiry, and not verified by a private key.
    pub fn read<'a>(owner: &[u8; 32], data: &'a [u8], now: i64) -> Result<Token<'a>, Error> {
        Token::read_from(&ID, owner, data, now)
    }
}

/// The first deployment of knos-oidc: immutable, with GitHub's and GitLab's keys of its day fixed in it, no expiry
/// and no revocation. Nothing in this crate reads it unless you write `v1`.
pub mod v1 {
    use super::{Error, Token};

    /// The first deployment's address (devnet), as bytes.
    pub const ID: [u8; 32] = [
        0x0d, 0xc9, 0x82, 0xa8, 0x4f, 0x3b, 0x4e, 0xae, 0x63, 0x8e, 0x01, 0x8f, 0xe3, 0x9a, 0x96, 0xd0,
        0x6b, 0xd7, 0xe9, 0x53, 0x33, 0x1c, 0xda, 0x76, 0x0d, 0x51, 0x66, 0xb4, 0x0b, 0x34, 0x2b, 0xa3,
    ];
    /// The same address as Solana prints it.
    pub const ID_STR: &str = "vpWym9azbPU5f2PH2a6n8c4RfmsyUeW2dMuWr1DSHcE";

    /// The three checks against the first deployment: owned by `v1::ID`, VERIFIED, at most `LATE` past its expiry.
    pub fn read<'a>(owner: &[u8; 32], data: &'a [u8], now: i64) -> Result<Token<'a>, Error> {
        Token::read_from(&ID, owner, data, now)
    }
}

pub const ISSUER_GITHUB: u8 = 0;
pub const ISSUER_GITLAB: u8 = 1;
/// Any other RS256 issuer that the second deployment admitted on an attestation (RegisterIssuerKey). The number says
/// only "not GitHub, not GitLab": which issuer is `Token::issuer_hash` (sha256 of its URL), and knos-oidc checked
/// that the token's `iss` is that URL.
pub const ISSUER_OTHER: u8 = 2;
/// A PRIVATE key verified the token: a key some wallet registered itself, with no attestation (RegisterPrivateKey),
/// for an issuer no public runner can reach. Nobody vouches for it. `Token::read` refuses such a token; a program
/// that wants them reads with `Token::read_any` and accepts one only from a `registrant` it trusts for that purpose.
pub const ISSUER_PRIVATE: u8 = 3;
/// The `iss` claim of each numbered issuer, by its number.
pub const ISSUERS: [&[u8]; 2] = [b"https://token.actions.githubusercontent.com", b"https://gitlab.com"];

/// The longest token knos-oidc takes.
pub const MAX_JWT: usize = 8192;
/// How long after its `exp` a token is still accepted by knos-oidc and by `fresh`. The issuers' tokens live five
/// minutes, which is shorter than it can take to land the transactions that verify one.
pub const LATE: i64 = 3600;
pub fn fresh(exp: i64, now: i64) -> bool { now < exp.saturating_add(LATE) }

// token account: stage u8 (0 writing, 1 stepping, 2 VERIFIED), issuer u8, squarings done u8, limbs u8, jwt_len u16,
// payload_off u16, payload_len u16, exp i64, key[32], payer[32], id[32], x (the running power, 512 bytes), jwt
pub const T_STAGE: usize = 0;
pub const T_ISSUER: usize = 1;
pub const T_DONE: usize = 2;
pub const T_LIMBS: usize = 3;
pub const T_LEN: usize = 4;
pub const T_POFF: usize = 6;
pub const T_PLEN: usize = 8;
pub const T_EXP: usize = 10;
pub const T_KEY: usize = 18;
pub const T_PAYER: usize = 50;
pub const T_ID: usize = 82;
pub const T_X: usize = 114;
pub const T_JWT: usize = 626;
pub const VERIFIED: u8 = 2;
/// In a VERIFIED account whose issuer is ISSUER_OTHER or ISSUER_PRIVATE: sha256 of the issuer's URL, and for a
/// private key the wallet that registered it (zero otherwise). They stand where the running power was.
pub const T_IHASH: usize = T_X;
pub const T_REGISTRANT: usize = T_X + 32;

// key account (second deployment): state u8 (1 ready), issuer u8, limbs u8, bump u8, n0inv u32, active_at i64,
// expires_at i64, flags u8, 15 zero bytes, then the modulus and R^2
pub const K_STATE: usize = 0;
pub const K_ACTIVE: usize = 8;
pub const K_EXPIRES: usize = 16;
pub const K_FLAGS: usize = 24;
pub const K_HDR: usize = 40;
pub const F_APPROVED: u8 = 1;
pub const F_REVOKED: u8 = 2;
pub const F_GENESIS: u8 = 4;
pub const F_PRIVATE: u8 = 8;

/// Why a token or a claim was refused. `code()` is the number to put in a program error: 61 to 63 are the codes
/// knos-oidc's own claims reader returns for the same bytes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u32)]
pub enum Error {
    /// The account is not owned by knos-oidc: anyone can create an account holding the same bytes.
    NotOidc = 1,
    /// Not a token account, or its signature has not been checked to the end.
    NotVerified = 2,
    /// More than `LATE` seconds past the token's `exp`.
    Stale = 3,
    /// A private key verified the token (`ISSUER_PRIVATE`): it is one wallet's word, and `Token::read` does not take
    /// it. Read it with `Token::read_any` and check `registrant()`.
    Private = 4,
    /// Not the key account the token names, or not an account of the same knos-oidc.
    Key = 68,
    /// The key that verified the token is not active (the same codes as knos-oidc's Step: 76, 77, 78).
    KeyNotActive = 76,
    /// The key that verified the token has expired: nothing attested it for 30 days.
    KeyExpired = 77,
    /// The guardian (or a private key's registrant) revoked the key that verified the token.
    KeyRevoked = 78,
    /// The claims are not a JSON object.
    Json = 61,
    /// A claim that was asked for appears twice.
    Duplicate = 62,
    /// The claim is missing or of the wrong type.
    Claim = 63,
}
impl Error {
    pub const fn code(self) -> u32 { self as u32 }
}

/// What a token account holds once it is VERIFIED: the issuer's number, the expiry, and the decoded claims (JSON).
#[derive(Clone, Copy, Debug)]
pub struct Verified<'a> { pub issuer: u8, pub exp: i64, pub payload: &'a [u8] }
/// None unless the account's bytes are a VERIFIED token. The caller must have checked the account's owner.
pub fn verified(d: &[u8]) -> Option<Verified<'_>> {
    if d.len() < T_JWT || d[T_STAGE] != VERIFIED { return None; }
    let off = u16::from_le_bytes([d[T_POFF], d[T_POFF + 1]]) as usize;
    let len = u16::from_le_bytes([d[T_PLEN], d[T_PLEN + 1]]) as usize;
    let payload = d.get(off..off + len)?;
    Some(Verified { issuer: d[T_ISSUER], exp: i64::from_le_bytes(d[T_EXP..T_EXP + 8].try_into().ok()?), payload })
}

/// A verified, fresh token. `read` does the three checks every consumer must do: the account is owned by knos-oidc
/// (the second deployment, unless you read with `v1::read` or `read_from`), it is VERIFIED, and it is at most `LATE`
/// seconds past its expiry (`now` is the chain's clock).
///
/// What remains your program's job, because knos-oidc only says the token is genuine:
/// - the issuer (`issuer()`): GitHub and GitLab sign different claims;
/// - the claims your statement depends on: the repository (`repository_id`), the workflow file and its commit
///   (`job_workflow_ref`, `job_workflow_sha`), and `runner_environment` if a self-hosted runner must not count;
/// - the audience: give your program its own prefix and require it, so a token minted for another program cannot
///   be used with yours;
/// - your own replay guard: the same verified token can be read by any program, any number of times, until an
///   hour after its expiry. Bind the token to one action in the audience and record that the action was done.
/// - if a revoked or expired signing key must stop its tokens at once: take the key account too and call
///   `check_key`. Without it a token account is good for up to 25 hours after its key stopped.
///
/// `read` never returns a token that a PRIVATE key verified. `read_any` does, and then `is_private()` is the check
/// your program must not forget: such a token is the word of `registrant()`, not of the issuer its claims name.
#[derive(Clone, Copy, Debug)]
pub struct Token<'a> { v: Verified<'a>, data: &'a [u8], program: [u8; 32] }
impl<'a> Token<'a> {
    /// The second deployment's token accounts (`ID`). For the first deployment, write `v1::read`.
    pub fn read(owner: &[u8; 32], data: &'a [u8], now: i64) -> Result<Token<'a>, Error> { Self::read_from(&ID, owner, data, now) }
    /// The same three checks against one deployment of knos-oidc that you name: `ID` or `v1::ID`. A token that one
    /// deployment verified says nothing under the other's address, so name exactly the one your program trusts.
    /// A token that a private key verified is refused (`Error::Private`).
    pub fn read_from(program: &[u8; 32], owner: &[u8; 32], data: &'a [u8], now: i64) -> Result<Token<'a>, Error> {
        let tok = Self::read_any_from(program, owner, data, now)?;
        if tok.v.issuer > ISSUER_OTHER { return Err(Error::Private); }
        Ok(tok)
    }
    /// `read`, and tokens that a private key verified too. Ask `is_private()` of what this returns.
    pub fn read_any(owner: &[u8; 32], data: &'a [u8], now: i64) -> Result<Token<'a>, Error> { Self::read_any_from(&ID, owner, data, now) }
    pub fn read_any_from(program: &[u8; 32], owner: &[u8; 32], data: &'a [u8], now: i64) -> Result<Token<'a>, Error> {
        if owner != program { return Err(Error::NotOidc); }
        let v = verified(data).ok_or(Error::NotVerified)?;
        if !fresh(v.exp, now) { return Err(Error::Stale); }
        Ok(Token { v, data, program: *program })
    }
    /// ISSUER_GITHUB, ISSUER_GITLAB, ISSUER_OTHER (see `issuer_hash`) or ISSUER_PRIVATE (see `registrant`).
    pub fn issuer(&self) -> u8 { self.v.issuer }
    pub fn exp(&self) -> i64 { self.v.exp }
    /// Whether a private key verified this token: a key a wallet registered itself, which nobody vouches for. The
    /// claims may name any issuer, GitHub included; they are the registrant's word. True for any issuer number this
    /// crate does not know, so that a newer kind of key is never taken for a public one.
    pub fn is_private(&self) -> bool { self.v.issuer > ISSUER_OTHER }
    /// The wallet that registered the private key; None for a token that is not private.
    pub fn registrant(&self) -> Option<&'a [u8; 32]> {
        if self.v.issuer != ISSUER_PRIVATE { return None; }
        self.data[T_REGISTRANT..T_REGISTRANT + 32].try_into().ok()
    }
    /// sha256 of the issuer's URL, for ISSUER_OTHER and ISSUER_PRIVATE; None for GitHub and GitLab by number.
    pub fn issuer_hash(&self) -> Option<&'a [u8; 32]> {
        if self.v.issuer < ISSUER_OTHER { return None; }
        self.data[T_IHASH..T_IHASH + 32].try_into().ok()
    }
    /// The address of the key account that verified the token.
    pub fn key(&self) -> &'a [u8; 32] { self.data[T_KEY..T_KEY + 32].try_into().unwrap() }
    /// Whether the key that verified the token may still verify at `now`, by knos-oidc's own rule. Pass the key
    /// account: its address must be the one the token names and its owner the same knos-oidc. Second deployment
    /// only (the first has no expiry and no revocation). Errors: `Key`, `KeyNotActive`, `KeyExpired`, `KeyRevoked`.
    pub fn check_key(&self, key_address: &[u8; 32], key_owner: &[u8; 32], key_data: &[u8], now: i64) -> Result<(), Error> {
        if key_address != self.key() || *key_owner != self.program || key_data.len() < K_HDR || key_data[K_STATE] != 1 { return Err(Error::Key); }
        let at = |o: usize| i64::from_le_bytes(key_data[o..o + 8].try_into().unwrap());
        key_usable(key_data[K_FLAGS], at(K_ACTIVE), at(K_EXPIRES), now)
    }
    /// The claims as the issuer signed them (a JSON object).
    pub fn payload(&self) -> &'a [u8] { self.v.payload }
    /// Several claims in one pass over the payload. A wanted claim that appears twice is an error.
    pub fn claims<const N: usize>(&self, want: [&[u8]; N]) -> Result<[Option<Raw<'a>>; N], Error> { fields(self.v.payload, want) }
    /// A string claim. None if it is absent, appears twice or is not a string.
    pub fn claim(&self, name: &str) -> Option<Text<'a>> {
        let [f] = self.claims([name.as_bytes()]).ok()?;
        text(f).ok()
    }
    /// A non-negative integer claim, given as a number or as a string of digits (GitHub sends ids as strings).
    pub fn claim_u64(&self, name: &str) -> Option<u64> {
        let [f] = self.claims([name.as_bytes()]).ok()?;
        number(f).ok()
    }
    /// The `aud` claim when it is one string, which is what GitHub Actions and GitLab CI sign.
    pub fn audience(&self) -> Option<Text<'a>> { self.claim("aud") }
}

/// knos-oidc's rule for a ready key, from its flags and times: revoked first, then not active (not a genesis key,
/// not approved, not private, or before its time), then expired.
pub fn key_usable(flags: u8, active_at: i64, expires_at: i64, now: i64) -> Result<(), Error> {
    if flags & F_REVOKED != 0 { return Err(Error::KeyRevoked); }
    if flags & (F_GENESIS | F_APPROVED | F_PRIVATE) == 0 || now < active_at { return Err(Error::KeyNotActive); }
    if now >= expires_at { return Err(Error::KeyExpired); }
    Ok(())
}

fn ws(b: &[u8], mut i: usize) -> usize {
    while i < b.len() && matches!(b[i], b' ' | b'\t' | b'\n' | b'\r') { i += 1; }
    i
}
/// b[i] == '"': the string's raw content range and the index after its closing quote.
fn jstr(b: &[u8], i: usize) -> Result<(usize, usize, usize), Error> {
    if b.get(i) != Some(&b'"') { return Err(Error::Json); }
    let mut k = i + 1;
    while k < b.len() {
        match b[k] {
            b'\\' => k += 2,
            b'"' => return Ok((i + 1, k, k + 1)),
            _ => k += 1,
        }
    }
    Err(Error::Json)
}
fn skip_value(b: &[u8], i: usize) -> Result<usize, Error> {
    match b.get(i) {
        Some(b'"') => Ok(jstr(b, i)?.2),
        Some(b'{') | Some(b'[') => {
            let mut depth = 0usize;
            let mut k = i;
            while k < b.len() {
                match b[k] {
                    b'"' => { k = jstr(b, k)?.2; continue; }
                    b'{' | b'[' => depth += 1,
                    b'}' | b']' => { depth -= 1; if depth == 0 { return Ok(k + 1); } }
                    _ => {}
                }
                k += 1;
            }
            Err(Error::Json)
        }
        Some(_) => {
            let mut k = i;
            while k < b.len() && !matches!(b[k], b',' | b'}' | b']' | b' ' | b'\t' | b'\n' | b'\r') { k += 1; }
            if k == i { Err(Error::Json) } else { Ok(k) }
        }
        None => Err(Error::Json),
    }
}

/// A claim's value as it stands in the JSON: the raw content of a string, or the raw token of a number/literal.
#[derive(Clone, Copy, Debug)]
pub struct Raw<'a> { pub bytes: &'a [u8], pub is_str: bool }

/// Whether a key whose raw content is `raw` is the name `want` (printable ASCII), however it is spelled: a JSON
/// reader that decodes escapes takes "a\u0075d" for "aud", so this one does too. An escape `unescape` refuses
/// stands for a character no wanted name has.
fn key_is(raw: &[u8], escaped: bool, want: &[u8]) -> bool {
    if !escaped { return raw == want; }
    let (mut i, mut k) = (0, 0);
    while i < raw.len() {
        let Ok((c, next)) = unescape(raw, i) else { return false };
        if want.get(k) != Some(&c) { return false; }
        i = next; k += 1;
    }
    k == want.len()
}

/// One pass over a flat JSON object: for each wanted top-level key, its value. A wanted key that appears twice is
/// refused, the whole object must parse, and nothing may follow it. A key is compared as the text it spells (its
/// escapes decoded), so that this reader and any other JSON reader find the same claim under the same name. The
/// same code as the second knos-oidc's, so it gives the same answer on the same bytes.
pub fn fields<'a, const N: usize>(b: &'a [u8], want: [&[u8]; N]) -> Result<[Option<Raw<'a>>; N], Error> {
    let mut got: [Option<Raw<'a>>; N] = [None; N];
    let mut i = ws(b, 0);
    if b.get(i) != Some(&b'{') { return Err(Error::Json); }
    i = ws(b, i + 1);
    if b.get(i) != Some(&b'}') {
        loop {
            let (ks, ke, next) = jstr(b, i)?;
            i = ws(b, next);
            if b.get(i) != Some(&b':') { return Err(Error::Json); }
            let vs = ws(b, i + 1);
            let ve = skip_value(b, vs)?;
            let key = &b[ks..ke];
            let escaped = key.contains(&b'\\');
            for (w, g) in want.iter().zip(got.iter_mut()) {
                if key_is(key, escaped, w) {
                    if g.is_some() { return Err(Error::Duplicate); }
                    *g = Some(if b[vs] == b'"' { Raw { bytes: &b[vs + 1..ve - 1], is_str: true } } else { Raw { bytes: &b[vs..ve], is_str: false } });
                }
            }
            i = ws(b, ve);
            match b.get(i) {
                Some(b',') => i = ws(b, i + 1),
                Some(b'}') => break,
                _ => return Err(Error::Json),
            }
        }
    }
    if ws(b, i + 1) != b.len() { return Err(Error::Json); }
    Ok(got)
}

/// The byte at r[i] of a JSON string's raw content, decoded, and the index after it.
fn unescape(r: &[u8], i: usize) -> Result<(u8, usize), Error> {
    if r[i] != b'\\' { return Ok((r[i], i + 1)); }
    match r.get(i + 1) {
        Some(b'/') => Ok((b'/', i + 2)),
        Some(b'\\') => Ok((b'\\', i + 2)),
        Some(b'"') => Ok((b'"', i + 2)),
        Some(b'u') => {
            let h = r.get(i + 2..i + 6).ok_or(Error::Claim)?;
            let mut v = 0u32;
            for &c in h {
                v = v << 4 | match c { b'0'..=b'9' => c - b'0', b'a'..=b'f' => c - b'a' + 10, b'A'..=b'F' => c - b'A' + 10, _ => return Err(Error::Claim) } as u32;
            }
            if !(0x20..0x7f).contains(&v) { return Err(Error::Claim); }
            Ok((v as u8, i + 6))
        }
        _ => Err(Error::Claim),
    }
}

/// A string claim's text, read without copying it. Its escapes were checked by `text`, so reading it cannot fail.
#[derive(Clone, Copy, Debug)]
pub struct Text<'a> { raw: &'a [u8], len: usize }
impl<'a> Text<'a> {
    /// The text's length in bytes, escapes decoded.
    pub fn len(&self) -> usize { self.len }
    pub fn is_empty(&self) -> bool { self.len == 0 }
    pub fn bytes(&self) -> TextBytes<'a> { TextBytes { raw: self.raw, at: 0 } }
    /// Whether the text is exactly `want` (a byte string or a str).
    pub fn is(&self, want: impl AsRef<[u8]>) -> bool {
        let w = want.as_ref();
        match self.as_plain() {
            Some(t) => t == w,
            None => w.len() == self.len && self.bytes().eq(w.iter().copied()),
        }
    }
    pub fn starts_with(&self, prefix: impl AsRef<[u8]>) -> bool {
        let p = prefix.as_ref();
        match self.as_plain() {
            Some(t) => t.starts_with(p),
            None => p.len() <= self.len && self.bytes().take(p.len()).eq(p.iter().copied()),
        }
    }
    /// The text itself when the issuer wrote it with no escapes (the usual case), borrowed from the account.
    pub fn as_plain(&self) -> Option<&'a [u8]> { if self.raw.len() == self.len { Some(self.raw) } else { None } }
    /// Copies the text to the start of `out` and returns that part; None if `out` is too short.
    pub fn copy_to<'b>(&self, out: &'b mut [u8]) -> Option<&'b [u8]> {
        let o = out.get_mut(..self.len)?;
        match self.as_plain() {
            Some(t) => o.copy_from_slice(t),
            None => for (d, s) in o.iter_mut().zip(self.bytes()) { *d = s; },
        }
        Some(o)
    }
    #[cfg(feature = "alloc")]
    pub fn to_vec(&self) -> alloc::vec::Vec<u8> { self.bytes().collect() }
}
pub struct TextBytes<'a> { raw: &'a [u8], at: usize }
impl Iterator for TextBytes<'_> {
    type Item = u8;
    fn next(&mut self) -> Option<u8> {
        if self.at >= self.raw.len() { return None; }
        let (c, next) = unescape(self.raw, self.at).ok()?;
        self.at = next;
        Some(c)
    }
}

/// A string claim's text. JSON escapes for printable ASCII are decoded (\/ \\ \" and \u00XX), so a value compares
/// equal however the issuer chose to escape it; any other escape is refused.
pub fn text(f: Option<Raw<'_>>) -> Result<Text<'_>, Error> {
    let r = match f { Some(r) if r.is_str => r.bytes, _ => return Err(Error::Claim) };
    // the usual case has no escape: nothing to decode, and the text can be compared and copied as it stands
    if !r.contains(&b'\\') { return Ok(Text { raw: r, len: r.len() }); }
    let (mut i, mut len) = (0, 0);
    while i < r.len() {
        i = unescape(r, i)?.1;
        len += 1;
    }
    Ok(Text { raw: r, len })
}
/// A non-negative integer claim, given as a JSON number or as a string of digits (GitHub sends ids as strings).
/// No sign, no leading zero, no fraction; at most 18 digits.
pub fn number(f: Option<Raw>) -> Result<u64, Error> {
    let r = f.ok_or(Error::Claim)?;
    parse_u64(r.bytes).ok_or(Error::Claim)
}
pub fn parse_u64(s: &[u8]) -> Option<u64> {
    if s.is_empty() || s.len() > 18 || !s.iter().all(|c| c.is_ascii_digit()) || (s.len() > 1 && s[0] == b'0') { return None; }
    Some(s.iter().fold(0u64, |a, c| a * 10 + (c - b'0') as u64))
}

// What an audience is usually made of: parts split on ':', lowercase hex, a Solana address.
pub fn is_hex(s: &[u8], len: usize) -> bool { s.len() == len && s.iter().all(|c| matches!(c, b'0'..=b'9' | b'a'..=b'f')) }
pub fn unhex32(s: &[u8]) -> Option<[u8; 32]> {
    if !is_hex(s, 64) { return None; }
    let v = |c: u8| if c <= b'9' { c - b'0' } else { c - b'a' + 10 };
    let mut o = [0u8; 32];
    for (k, b) in o.iter_mut().enumerate() { *b = v(s[2 * k]) << 4 | v(s[2 * k + 1]); }
    Some(o)
}
/// A canonical base58 32-byte public key (as Solana prints it); None for anything else.
pub fn b58_32(s: &[u8]) -> Option<[u8; 32]> {
    const A: &[u8] = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
    if s.len() < 32 || s.len() > 44 { return None; }
    let mut out = [0u8; 32];
    for &c in s {
        let mut carry = A.iter().position(|&x| x == c)? as u32;
        for b in out.iter_mut().rev() {
            carry += (*b as u32) * 58;
            *b = carry as u8;
            carry >>= 8;
        }
        if carry != 0 { return None; }
    }
    let ones = s.iter().take_while(|&&c| c == b'1').count();
    let zeros = out.iter().take_while(|&&b| b == 0).count();
    if ones != zeros { return None; }
    Some(out)
}
/// Splits `s` on ':' into exactly N parts.
pub fn parts<const N: usize>(s: &[u8]) -> Option<[&[u8]; N]> {
    let mut out: [&[u8]; N] = [&[]; N];
    let mut it = s.split(|&c| c == b':');
    for o in out.iter_mut() { *o = it.next()?; }
    if it.next().is_some() { return None; }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_id_is_the_deployed_address() {
        assert_eq!(b58_32(ID_STR.as_bytes()), Some(ID));
        assert_eq!(b58_32(v1::ID_STR.as_bytes()), Some(v1::ID));
    }

    #[test]
    fn every_default_is_the_second_deployment_and_the_first_is_read_only_by_name() {
        assert_eq!((ID_STR, v2::ID_STR, v1::ID_STR), ("FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W", "FkwZdsYCmzicJMtHLTkPK76bYNVG4WNwkWJBiVWNtF3W",
                                                       "vpWym9azbPU5f2PH2a6n8c4RfmsyUeW2dMuWr1DSHcE"));
        assert!(v2::ID == ID && v1::ID != ID);
        let (d, len) = account(ISSUER_GITHUB, br#"{"aud":"x","exp":1000}"#, 1000);
        let d = &d[..len];
        // an account the first deployment owns: every reader that does not say `v1` refuses it
        assert_eq!(Token::read(&v1::ID, d, 1000).unwrap_err(), Error::NotOidc);
        assert_eq!(Token::read_any(&v1::ID, d, 1000).unwrap_err(), Error::NotOidc);
        assert_eq!(v2::read(&v1::ID, d, 1000).unwrap_err(), Error::NotOidc);
        assert!(v1::read(&v1::ID, d, 1000).is_ok() && Token::read_from(&v1::ID, &v1::ID, d, 1000).is_ok());
        // an account the second owns: read by every default, refused under the first's name
        assert!(Token::read(&ID, d, 1000).is_ok() && Token::read_any(&ID, d, 1000).is_ok() && v2::read(&ID, d, 1000).is_ok());
        assert_eq!(v1::read(&ID, d, 1000).unwrap_err(), Error::NotOidc);
    }

    #[test]
    fn the_two_deployments_have_their_own_addresses_and_read_the_same_layout() {
        assert_eq!(b58_32(v2::ID_STR.as_bytes()), Some(v2::ID));
        assert_ne!(v2::ID, v1::ID);
        // a VERIFIED token account, as small as one can be: the header, then the claims
        let payload = br#"{"aud":"x","exp":1000}"#;
        let mut d = [0u8; T_JWT + 22];
        d[T_STAGE] = VERIFIED;
        d[T_ISSUER] = ISSUER_GITLAB;
        d[T_POFF..T_POFF + 2].copy_from_slice(&(T_JWT as u16).to_le_bytes());
        d[T_PLEN..T_PLEN + 2].copy_from_slice(&(payload.len() as u16).to_le_bytes());
        d[T_EXP..T_EXP + 8].copy_from_slice(&1000i64.to_le_bytes());
        d[T_JWT..].copy_from_slice(payload);
        // each reader takes its own deployment's account and refuses the other's
        let tok = v2::read(&v2::ID, &d, 1000).unwrap();
        assert!(tok.issuer() == ISSUER_GITLAB && tok.exp() == 1000 && tok.audience().unwrap().is("x") && tok.claim_u64("exp") == Some(1000));
        assert_eq!(v2::read(&v1::ID, &d, 1000).unwrap_err(), Error::NotOidc);
        assert_eq!(v1::read(&v2::ID, &d, 1000).unwrap_err(), Error::NotOidc);
        assert!(v1::read(&v1::ID, &d, 1000).is_ok() && Token::read_from(&v2::ID, &v2::ID, &d, 1000).is_ok());
        assert_eq!(Token::read_from(&v2::ID, &[0; 32], &d, 1000).unwrap_err(), Error::NotOidc);
        // the other two checks are the same ones
        assert_eq!(v2::read(&v2::ID, &d, 1000 + LATE).unwrap_err(), Error::Stale);
        d[T_STAGE] = 1;
        assert_eq!(v2::read(&v2::ID, &d, 1000).unwrap_err(), Error::NotVerified);
    }

    /// A VERIFIED token account of the second deployment, as small as one can be.
    fn account(issuer: u8, payload: &[u8], exp: i64) -> ([u8; T_JWT + 160], usize) {
        let mut d = [0u8; T_JWT + 160];
        d[T_STAGE] = VERIFIED;
        d[T_ISSUER] = issuer;
        d[T_POFF..T_POFF + 2].copy_from_slice(&(T_JWT as u16).to_le_bytes());
        d[T_PLEN..T_PLEN + 2].copy_from_slice(&(payload.len() as u16).to_le_bytes());
        d[T_EXP..T_EXP + 8].copy_from_slice(&exp.to_le_bytes());
        d[T_KEY..T_KEY + 32].copy_from_slice(&[9; 32]);
        d[T_JWT..T_JWT + payload.len()].copy_from_slice(payload);
        (d, T_JWT + payload.len())
    }

    #[test]
    fn a_private_token_is_refused_by_read_and_marked_for_whoever_reads_any() {
        // every claim is what GitHub would sign; a wallet's own key signed it and knos-oidc marked the account
        let payload = br#"{"iss":"https://token.actions.githubusercontent.com","aud":"gate:release","repository_id":"1","exp":1000}"#;
        let (mut d, len) = account(ISSUER_PRIVATE, payload, 1000);
        d[T_IHASH..T_IHASH + 32].copy_from_slice(&[0xaa; 32]);
        d[T_REGISTRANT..T_REGISTRANT + 32].copy_from_slice(&[0xbb; 32]);
        let d = &d[..len];
        assert_eq!(v2::read(&v2::ID, d, 1000).unwrap_err(), Error::Private);
        assert_eq!(Token::read_from(&v2::ID, &v2::ID, d, 1000).unwrap_err(), Error::Private);
        let tok = Token::read_any_from(&v2::ID, &v2::ID, d, 1000).unwrap();
        assert!(tok.is_private() && tok.registrant() == Some(&[0xbb; 32]) && tok.issuer_hash() == Some(&[0xaa; 32]));
        assert!(tok.issuer() == ISSUER_PRIVATE && tok.issuer() != ISSUER_GITHUB);
        // The one way to be fooled: read_any, then the claims alone. Each of the two checks alone stops it.
        let forgetful = |t: &Token| t.claim("iss").is_some_and(|i| i.is(ISSUERS[0])) && t.audience().is_some_and(|a| a.is("gate:release"));
        assert!(forgetful(&tok));
        let fooled_past_is_private = forgetful(&tok) && !tok.is_private();
        let fooled_past_the_issuer = forgetful(&tok) && tok.issuer() == ISSUER_GITHUB;
        assert!(!fooled_past_is_private);
        assert!(!fooled_past_the_issuer);
        // the other two checks of read_any are read's
        assert_eq!(Token::read_any_from(&v2::ID, &[1; 32], d, 1000).unwrap_err(), Error::NotOidc);
        assert_eq!(Token::read_any_from(&v2::ID, &v2::ID, d, 1000 + LATE).unwrap_err(), Error::Stale);
        // a public token: not private, no registrant; GitHub and GitLab have no hash, any other issuer has one
        for (issuer, hash) in [(ISSUER_GITHUB, None), (ISSUER_GITLAB, None), (ISSUER_OTHER, Some(&[0xaa; 32]))] {
            let (mut d, len) = account(issuer, payload, 1000);
            d[T_IHASH..T_IHASH + 32].copy_from_slice(&[0xaa; 32]);
            let tok = v2::read(&v2::ID, &d[..len], 1000).unwrap();
            assert!(!tok.is_private() && tok.registrant().is_none() && tok.issuer_hash() == hash && tok.issuer() == issuer && tok.key() == &[9; 32]);
        }
        // an issuer number from a later knos-oidc is never taken for a public one
        for issuer in [4u8, 200, 255] {
            let (d, len) = account(issuer, payload, 1000);
            assert_eq!(v2::read(&v2::ID, &d[..len], 1000).unwrap_err(), Error::Private);
            assert!(Token::read_any_from(&v2::ID, &v2::ID, &d[..len], 1000).unwrap().is_private());
        }
    }

    #[test]
    fn check_key_is_knos_oidcs_rule_on_the_key_account_the_token_names() {
        let (d, len) = account(ISSUER_GITHUB, br#"{"exp":1000}"#, 1000);
        let tok = v2::read(&v2::ID, &d[..len], 1000).unwrap();
        let key = |state: u8, flags: u8, active: i64, expires: i64| {
            let mut k = [0u8; K_HDR + 8];
            k[K_STATE] = state; k[K_FLAGS] = flags;
            k[K_ACTIVE..K_ACTIVE + 8].copy_from_slice(&active.to_le_bytes());
            k[K_EXPIRES..K_EXPIRES + 8].copy_from_slice(&expires.to_le_bytes());
            k
        };
        let good = key(1, F_GENESIS | F_APPROVED, 500, 2000);
        assert_eq!(tok.check_key(&[9; 32], &v2::ID, &good, 1000), Ok(()));
        assert_eq!(tok.check_key(&[8; 32], &v2::ID, &good, 1000), Err(Error::Key));      // another key account
        assert_eq!(tok.check_key(&[9; 32], &[7; 32], &good, 1000), Err(Error::Key));     // another program's account
        assert_eq!(tok.check_key(&[9; 32], &v2::ID, &good[..K_HDR - 1], 1000), Err(Error::Key));
        assert_eq!(tok.check_key(&[9; 32], &v2::ID, &key(0, F_GENESIS, 500, 2000), 1000), Err(Error::Key));
        assert_eq!(tok.check_key(&[9; 32], &v2::ID, &good, 499), Err(Error::KeyNotActive));
        assert_eq!(tok.check_key(&[9; 32], &v2::ID, &key(1, 0, 500, 2000), 1000), Err(Error::KeyNotActive));
        assert_eq!(tok.check_key(&[9; 32], &v2::ID, &good, 2000), Err(Error::KeyExpired));
        assert_eq!(tok.check_key(&[9; 32], &v2::ID, &key(1, F_APPROVED | F_REVOKED, 500, 2000), 1000), Err(Error::KeyRevoked));
        assert_eq!(tok.check_key(&[9; 32], &v2::ID, &key(1, F_PRIVATE, 500, 2000), 1000), Ok(()));
        assert_eq!((Error::Key.code(), Error::KeyNotActive.code(), Error::KeyExpired.code(), Error::KeyRevoked.code()), (68, 76, 77, 78));
    }

    #[test]
    fn fields_reads_a_flat_object_in_one_pass() {
        let b = br#" { "a" : "x" , "n":12, "t":true, "o":{"a":"inner","k":[1,"}"]}, "s":"7" } "#;
        let [a, n, t, o, s, none] = fields(b, [b"a", b"n", b"t", b"o", b"s", b"zz"]).unwrap();
        assert!(text(a).unwrap().is("x") && number(n) == Ok(12) && number(s) == Ok(7) && none.is_none());
        assert!(!t.unwrap().is_str && t.unwrap().bytes == b"true" && o.unwrap().bytes == br#"{"a":"inner","k":[1,"}"]}"#);
        assert_eq!(text(n).unwrap_err(), Error::Claim);      // a number is not a string
        assert_eq!(number(t).unwrap_err(), Error::Claim);
        assert!(fields(b"{}", [b"a"]).unwrap()[0].is_none());
    }

    #[test]
    fn fields_refuses_what_knos_oidc_refuses() {
        let json = |b: &[u8]| fields(b, [b"a"]).unwrap_err();
        assert_eq!(json(br#"{"a":"x","a":"y"}"#), Error::Duplicate);
        assert!(fields(br#"{"b":1,"b":2}"#, [b"a"]).is_ok());   // only a wanted key is checked for a second copy
        // a key is the text it spells: a claim is found under an escaped spelling, and a second copy cannot hide behind one
        let [a] = fields(br#"{"\u0061":"x"}"#, [b"a"]).unwrap();
        assert!(text(a).unwrap().is("x"));
        assert_eq!(json(br#"{"a":"x","\u0061":"y"}"#), Error::Duplicate);
        assert!(fields(br#"{"\u0061b":"x","\n":1}"#, [b"a"]).unwrap()[0].is_none());
        for bad in [&b""[..], b"[]", b"{", br#"{"a"}"#, br#"{"a":}"#, br#"{"a":"x"} x"#, br#"{"a":"x",}"#, br#"{"a":"x"#,
                    br#"{"a":[1,2"#,br#"{a:1}"#, br#"{"a":1 "b":2}"#] {
            assert_eq!(json(bad), Error::Json, "{:?}", core::str::from_utf8(bad));
        }
    }

    #[test]
    fn text_decodes_the_escapes_of_printable_ascii_and_no_other() {
        let t = |b: &'static [u8]| text(fields(b, [b"a"]).unwrap()[0]);
        let v = t(br#"{"a":"octo\/widgets \u0041\u007e \\ \" end"}"#).unwrap();
        let want = br#"octo/widgets A~ \ " end"#;
        assert!(v.is(want) && v.len() == want.len() && v.starts_with("octo/") && !v.starts_with("octo\\"));
        assert!(v.as_plain().is_none() && !v.is(&want[1..]) && !v.is("") && !v.is_empty());
        let mut buf = [0u8; 64];
        assert_eq!(v.copy_to(&mut buf), Some(&want[..]));
        assert!(v.copy_to(&mut buf[..want.len() - 1]).is_none());
        assert_eq!(t(br#"{"a":"plain"}"#).unwrap().as_plain(), Some(&b"plain"[..]));
        assert!(t(br#"{"a":""}"#).unwrap().is_empty());
        for bad in [&br#"{"a":"\n"}"#[..], br#"{"a":"\u001f"}"#, br#"{"a":"\u007f"}"#, br#"{"a":"\u00e9"}"#, br#"{"a":"\u00g1"}"#, br#"{"a":"\u004"}"#] {
            assert_eq!(t(bad).unwrap_err(), Error::Claim, "{:?}", core::str::from_utf8(bad));
        }
        assert_eq!(text(None).unwrap_err(), Error::Claim);
    }

    #[test]
    fn numbers_and_the_parts_of_an_audience() {
        assert_eq!(parse_u64(b"0"), Some(0));
        assert_eq!(parse_u64(b"999999999999999999"), Some(999_999_999_999_999_999));
        for bad in [&b""[..], b"01", b"-1", b"1.0", b"1e3", b"1234567890123456789", b" 1"] { assert_eq!(parse_u64(bad), None); }
        assert_eq!(parts::<3>(b"knos:claim:abc"), Some([&b"knos"[..], b"claim", b"abc"]));
        assert!(parts::<3>(b"knos:claim").is_none() && parts::<3>(b"a:b:c:d").is_none());
        assert!(is_hex(&[b'a'; 40], 40) && !is_hex(&[b'A'; 40], 40) && !is_hex(&[b'a'; 39], 40));
        assert_eq!(unhex32(&[b'f'; 64]), Some([0xff; 32]));
        assert!(unhex32(&[b'f'; 63]).is_none());
        assert_eq!(b58_32(b"11111111111111111111111111111111"), Some([0; 32]));
        assert!(b58_32(b"1111111111111111111111111111111").is_none() && b58_32(b"0OIl").is_none());
        assert!(fresh(100, 100 + LATE - 1) && !fresh(100, 100 + LATE) && fresh(i64::MAX, 0));
        assert_eq!((Error::Json.code(), Error::Duplicate.code(), Error::Claim.code()), (61, 62, 63));
    }
}
