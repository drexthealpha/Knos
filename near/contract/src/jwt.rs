//! A compact JWT split and decoded: the header's alg and kid, the signed part, the signature, and the claims a release
//! checks. serde refuses a token that names one of those claims twice.

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use serde::Deserialize;

#[derive(Deserialize)]
struct Header {
    alg: String,
    kid: String,
}

#[derive(Deserialize, Debug, Clone)]
pub struct Claims {
    pub iss: String,
    pub aud: String,
    pub exp: u64,
    pub jti: String,
    pub repository: String,
    pub job_workflow_ref: String,
    pub sha: String,
}

pub struct Token {
    pub alg: String,
    pub kid: String,
    /// header.payload, the bytes the signature covers
    pub signed: String,
    pub sig: Vec<u8>,
    pub claims: Claims,
}

pub fn parse(token: &str) -> Result<Token, &'static str> {
    if token.len() > 8192 {
        return Err("the token is too long");
    }
    let mut it = token.split('.');
    let (h, p, s) = match (it.next(), it.next(), it.next(), it.next()) {
        (Some(h), Some(p), Some(s), None) => (h, p, s),
        _ => return Err("the token is not header.payload.signature"),
    };
    let header: Header = serde_json::from_slice(&URL_SAFE_NO_PAD.decode(h).map_err(|_| "header encoding")?).map_err(|_| "header")?;
    let claims: Claims = serde_json::from_slice(&URL_SAFE_NO_PAD.decode(p).map_err(|_| "payload encoding")?).map_err(|_| "the token's claims")?;
    let sig = URL_SAFE_NO_PAD.decode(s).map_err(|_| "signature encoding")?;
    Ok(Token { alg: header.alg, kid: header.kid, signed: format!("{h}.{p}"), sig, claims })
}
