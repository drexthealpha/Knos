//! The crate's claim reader against serde_json on documents made at random from a fixed seed: every claim a consumer
//! asks for, in every spelling JSON allows, twice, nested, damaged. The rule and the documents are the ones knos-oidc's
//! own reader is tested with (programs-v2/knos_oidc/tests/oracle/mod.rs), so this test needs the repository around
//! it and is left out of the published package. The fuzz target in programs-v2/knos_oidc/fuzz asks both readers at
//! once and requires the same answer of them on every input.
#[path = "../../../programs-v2/knos_oidc/tests/oracle/mod.rs"]
mod oracle;

use knos_oidc_interface::{fields, number, text};
use oracle::{check, document, Claim, Read, Rng, WANT};

fn read(b: &[u8]) -> Read {
    match fields(b, WANT) {
        Err(e) => Read::Refused(e.code()),
        Ok(got) => Read::Claims(got.iter().map(|g| g.map(|r| Claim {
            is_str: r.is_str, raw: r.bytes.to_vec(), text: text(Some(r)).ok().map(|t| t.bytes().collect()), number: number(Some(r)).ok() })).collect()),
    }
}

#[test]
fn every_wanted_claim_is_what_serde_json_reads_on_300_000_random_documents() {
    let mut r = Rng(0x6b6e_6f73_2d69_6661);
    let mut found = 0usize;
    for _ in 0..300_000 {
        let doc = document(&mut r);
        let got = read(&doc);
        check(&doc, &got, "knos-oidc-interface");
        if let Read::Claims(c) = got { found += c.iter().flatten().count(); }
    }
    assert!(found > 200_000, "{found}");
}
