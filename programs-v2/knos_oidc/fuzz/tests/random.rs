//! The fuzz target's check under `cargo test` on stable: documents made at random from a fixed seed (every wanted
//! claim in every spelling, twice, nested, damaged), read by both copies of the claim reader and by serde_json.
use knos_oidc_fuzz::{agree, oracle::{document, Rng}};

#[test]
fn both_readers_agree_with_each_other_and_with_serde_json_on_300_000_random_documents() {
    let mut r = Rng(0x6b6e_6f73_2d66_757a);
    for _ in 0..300_000 { agree(&document(&mut r)); }
}

#[test]
fn both_readers_agree_on_bytes_that_are_not_json_at_all() {
    let mut r = Rng(7);
    for _ in 0..200_000 {
        let noise: Vec<u8> = (0..r.below(48)).map(|_| if r.one_in(3) { b"{}[]\",:\\u0 aud"[r.below(14)] } else { r.next() as u8 }).collect();
        agree(&noise);
    }
}

/// A JSON string for `name` with the characters at the positions set in `mask` written as \u escapes.
fn spelled(name: &[u8], mask: u32, upper: bool) -> String {
    let mut s = String::from("\"");
    for (i, c) in name.iter().enumerate() {
        if mask >> i & 1 == 0 { s.push(*c as char); continue; }
        s.push_str(&if upper { format!("\\u{:04X}", c) } else { format!("\\u{:04x}", c) });
    }
    s + "\""
}

/// The three voices on the one thing the second deployment's reader changed: a key is the text it spells. Every
/// wanted claim, under its plain name and under spellings with one, two or all characters escaped: found by
/// claims.rs, by the interface crate and by serde_json alike; and written twice under two spellings, refused by both
/// readers (`agree` holds each to serde_json's view, which has the claim twice).
#[test]
fn all_three_read_a_wanted_claim_under_every_spelling_of_its_name_and_see_a_second_copy_behind_any() {
    use knos_oidc_fuzz::{interface, oracle::{Read, WANT}, program};
    let mut r = Rng(0x7370_656c_6c65_6421);
    let (mut found, mut refused) = (0u32, 0u32);
    for (k, name) in WANT.iter().enumerate() {
        let all = (1u32 << name.len()) - 1;
        let mut masks = vec![0, all];
        masks.extend((0..name.len()).map(|i| 1 << i));
        masks.extend((0..24).map(|_| r.next() as u32 & all));
        for (m, &mask) in masks.iter().enumerate() {
            let key = spelled(name, mask, m % 2 == 1);
            for value in ["\"x\"", "17", "\"1790000300\"", "true"] {
                let once = format!("{{\"sub\":1,{key}:{value}}}");
                agree(once.as_bytes());
                match (program(once.as_bytes()), interface(once.as_bytes())) {
                    (Read::Claims(p), Read::Claims(i)) => { assert!(p[k].is_some() && i[k].is_some(), "{once}"); found += 1; }
                    other => panic!("{once}: {other:?}"),
                }
                // the same claim again, under another spelling, before it and after it
                let other = spelled(name, masks[(m + 1) % masks.len()], m % 2 == 0);
                for twice in [format!("{{{key}:{value},\"sub\":1,{other}:\"y\"}}"), format!("{{{other}:null,{key}:{value}}}")] {
                    agree(twice.as_bytes());
                    assert_eq!((program(twice.as_bytes()), interface(twice.as_bytes())), (Read::Refused(62), Read::Refused(62)), "{twice}");
                    refused += 1;
                }
            }
        }
    }
    assert!(found > 1_500 && refused > 3_000, "{found} {refused}");
}

/// The first two tests again from sixteen other seeds: the same check on documents and on noise no earlier run made.
#[test]
fn the_three_agree_from_sixteen_other_seeds() {
    for seed in 1..=16u64 {
        let mut r = Rng(seed.wrapping_mul(0x9e37_79b9_7f4a_7c15) | 1);
        for _ in 0..40_000 { agree(&document(&mut r)); }
        for _ in 0..20_000 {
            let mut doc = document(&mut r);
            // what a mutating fuzzer does to an input that parsed: splice a piece of another one into it
            let other = document(&mut r);
            if !doc.is_empty() && !other.is_empty() {
                let (at, from) = (r.below(doc.len()), r.below(other.len()));
                let piece = &other[from..(from + 1 + r.below(12)).min(other.len())];
                doc.splice(at..at, piece.iter().copied());
            }
            agree(&doc);
        }
    }
}
