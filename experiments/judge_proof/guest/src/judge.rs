//! The judge itself: no input but the two byte strings, no clock, no randomness, no I/O. The guest and the host's
//! plain run both compile this file, so "what the proof says" and "what the checks say" are one text.
//!
//! checks:      a header line, then one line per case: `<input> => <expected output>`
//! submission:  one line per case, in order: what the submitted function returned for that case's input
//! A case passes when the submission's line is, byte for byte, the expected output. Anything else (a missing line,
//! an extra line, a line with a carriage return) fails; nothing panics, so a failing verdict can be proved too.

pub const VERSION: u8 = 1;
pub const JOURNAL_LEN: usize = 70;

pub struct Verdict {
    pub passed: u16,
    pub total: u16,
}

impl Verdict {
    pub fn ok(&self) -> bool {
        self.total > 0 && self.passed == self.total
    }
}

fn lines(bytes: &[u8]) -> Vec<&[u8]> {
    let body = bytes.strip_suffix(b"\n").unwrap_or(bytes);
    if body.is_empty() && bytes.len() <= 1 {
        return Vec::new();
    }
    body.split(|b| *b == b'\n').collect()
}

fn expected(case: &[u8]) -> Option<&[u8]> {
    let mark = b" => ";
    (0..case.len().saturating_sub(mark.len() - 1))
        .rev()
        .find(|i| case[*i..].starts_with(mark))
        .map(|i| &case[i + mark.len()..])
}

pub fn judge(checks: &[u8], submission: &[u8]) -> Verdict {
    let all = lines(checks);
    let cases = if all.is_empty() { &all[..] } else { &all[1..] };
    let got = lines(submission);
    let total = cases.len().min(u16::MAX as usize) as u16;
    let mut passed = 0u16;
    if got.len() == cases.len() {
        for (case, line) in cases.iter().zip(got.iter()) {
            if expected(case) == Some(*line) {
                passed += 1;
            }
        }
    }
    Verdict { passed, total }
}

/// version | sha256(submission) | sha256(checks) | verdict (1 passed, 0 not) | cases passed | cases, little endian
pub fn journal(submission_hash: &[u8; 32], checks_hash: &[u8; 32], v: &Verdict) -> [u8; JOURNAL_LEN] {
    let mut out = [0u8; JOURNAL_LEN];
    out[0] = VERSION;
    out[1..33].copy_from_slice(submission_hash);
    out[33..65].copy_from_slice(checks_hash);
    out[65] = v.ok() as u8;
    out[66..68].copy_from_slice(&v.passed.to_le_bytes());
    out[68..70].copy_from_slice(&v.total.to_le_bytes());
    out
}
