//! claims.rs against serde_json on documents made at random from a fixed seed: every wanted claim, in every spelling
//! JSON allows, twice, nested, damaged. The rule is in tests/oracle/mod.rs. This runs under `cargo test` on stable;
//! the coverage-guided version of the same check is the fuzz target in fuzz/ (`cargo +nightly fuzz run claims`).
mod oracle;

use knos_oidc::claims::{fields, number, text};
use oracle::{check, document, pairs, Claim, Read, Rng, WANT};
use solana_program::program_error::ProgramError;

fn read(b: &[u8]) -> Read {
    match fields(b, WANT) {
        Err(ProgramError::Custom(code)) => Read::Refused(code),
        Err(e) => panic!("claims.rs returns its own codes only: {e:?}"),
        Ok(got) => Read::Claims(got.iter().map(|g| g.map(|r| Claim {
            is_str: r.is_str, raw: r.bytes.to_vec(), text: text(Some(r)).ok(), number: number(Some(r)).ok() })).collect()),
    }
}

#[test]
fn every_wanted_claim_is_what_serde_json_reads_on_300_000_random_documents() {
    let mut r = Rng(0x6b6e_6f73_2d6f_6964);
    let (mut objects, mut found, mut twice, mut refused) = (0u32, 0u32, 0u32, 0u32);
    for _ in 0..300_000 {
        let doc = document(&mut r);
        let got = read(&doc);
        check(&doc, &got, "claims.rs");
        if pairs(&doc).is_some() { objects += 1; }
        match got {
            Read::Claims(c) => found += c.iter().flatten().count() as u32,
            Read::Refused(62) => twice += 1,
            Read::Refused(_) => refused += 1,
        }
    }
    // the documents did exercise the reader: most are objects, many claims were found, some were refused each way
    assert!(objects > 150_000 && found > 200_000 && twice > 10_000 && refused > 10_000, "{objects} {found} {twice} {refused}");
}

#[test]
fn a_claim_is_found_under_every_spelling_of_its_name_and_a_second_copy_cannot_hide_behind_one() {
    for spelled in [r#""aud""#, r#""a\u0075d""#, r#""\u0061\u0075\u0064""#, r#""a\u0075\u0064""#, r#""\u0061ud""#] {
        let doc = format!(r#"{{{spelled}:"x","exp":7}}"#);
        let [aud, exp] = fields(doc.as_bytes(), [b"aud", b"exp"]).unwrap();
        assert_eq!((text(aud).unwrap(), number(exp).unwrap()), (b"x".to_vec(), 7), "{doc}");
        check(doc.as_bytes(), &read(doc.as_bytes()), "claims.rs");
        // the same claim again under the plain name, before it or after it: refused, as serde_json would see two
        for two in [format!(r#"{{"aud":"mine",{spelled}:"x"}}"#), format!(r#"{{{spelled}:"x","aud":"mine"}}"#)] {
            assert_eq!(fields(two.as_bytes(), [b"aud"]).unwrap_err(), ProgramError::Custom(62), "{two}");
        }
    }
    // a key that spells another name is another name; an escape no wanted name has is not an error in a key
    for other in [r#"{"a\u0075dx":"x"}"#, r#"{"a\u0075":"x"}"#, r#"{"aud\n":"x"}"#, r#"{"a\u00fcd":"x"}"#, r#"{"https:\/\/example.com\/aud":"x"}"#, r#"{"a\u0055d":"x"}"#] {
        assert!(fields(other.as_bytes(), [b"aud"]).unwrap()[0].is_none(), "{other}");
        check(other.as_bytes(), &read(other.as_bytes()), "claims.rs");
    }
}
