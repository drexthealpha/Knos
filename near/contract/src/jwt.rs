//! A compact JWT split and decoded: the header's alg and kid, the signed part, the signature, and the claims a release
//! checks. serde refuses a token that names one of those claims twice.

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use serde::de::DeserializeOwned;
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

/// The claims of a Knos checker's token: the checker ran the job's locked test on one agent's output and it passed
#[derive(Deserialize, Debug, Clone)]
pub struct CheckerClaims {
    pub iss: String,
    pub aud: String,
    pub exp: u64,
    pub jti: String,
    pub job: String,
    pub payee: String,
    pub output_sha256: String,
    pub criteria_hash: String,
    /// the text NEAR AI Cloud signed for the model call that wrote this output ("request hash:response hash"); when the
    /// checker names it, `release_job_verified` pays only on a signature of exactly this text
    #[serde(default)]
    pub model_text: Option<String>,
}

pub struct Token<C = Claims> {
    pub alg: String,
    pub kid: String,
    /// header.payload, the bytes the signature covers
    pub signed: String,
    pub sig: Vec<u8>,
    pub claims: C,
}

pub fn parse<C: DeserializeOwned>(token: &str) -> Result<Token<C>, &'static str> {
    if token.len() > 8192 {
        return Err("the token is too long");
    }
    let mut it = token.split('.');
    let (h, p, s) = match (it.next(), it.next(), it.next(), it.next()) {
        (Some(h), Some(p), Some(s), None) => (h, p, s),
        _ => return Err("the token is not header.payload.signature"),
    };
    let header: Header = serde_json::from_slice(&URL_SAFE_NO_PAD.decode(h).map_err(|_| "header encoding")?).map_err(|_| "header")?;
    let claims: C = serde_json::from_slice(&URL_SAFE_NO_PAD.decode(p).map_err(|_| "payload encoding")?).map_err(|_| "the token's claims")?;
    let sig = URL_SAFE_NO_PAD.decode(s).map_err(|_| "signature encoding")?;
    Ok(Token { alg: header.alg, kid: header.kid, signed: format!("{h}.{p}"), sig, claims })
}
