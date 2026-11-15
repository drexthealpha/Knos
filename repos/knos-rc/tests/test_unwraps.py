"""Every place in the four programs where a panic is written down: docs/reference/UNWRAPS.md is made from this file.

A panic in a Solana program aborts the instruction and with it the whole transaction: the runtime keeps none of the
transaction's account changes, so no state is written and no token moves. What a panic costs is the fee and an error
that names no cause. The question for each place is therefore "can it be reached, and by whom", not "is money lost".

What is listed, for programs-v2/knos_{oidc,pay,meter,passkey}/src:
  - every `unwrap()`, `expect(`, `unreachable!`, `panic!`, `todo!`, `unimplemented!` and `assert` in program code,
    by file and line, with the reason it cannot fail or what happens when it does (WHY below: a place with no
    reason fails the test, and so does a reason that matches no place);
  - how many more are in unit tests and proof harnesses, which are in no build of a program;
  - for indexing (`d[a..b]`, `d[k]`), which panics out of range: the number of lines that index, by file. They are
    counted, not explained one by one.

    python tests/test_unwraps.py --write     # docs/reference/UNWRAPS.md again, after a program's source changed

The test fails when the document is not what this file writes today: a new `unwrap()`, one that moved, or a file
that indexes on more or fewer lines, all change it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "reference" / "UNWRAPS.md"
PROGRAMS = ("knos_oidc", "knos_pay", "knos_meter", "knos_passkey")
PANICS = re.compile(r"\bunwrap\(\)|\bexpect\(|\bunreachable!|\bpanic!|\btodo!|\bunimplemented!|\b(?:debug_)?assert(?:_eq|_ne)?!")
INDEX = re.compile(r"[\w)\]]\[(?!\.\.\])")           # d[..]: an index or a range with a bound; `[..]` alone cannot panic
# A file that is in no build of a program: knos_pay/src/lib.rs declares it `#[cfg(any(kani, test))] mod proofs;`
NOT_BUILT = {"programs-v2/knos_pay/src/proofs.rs": "#[cfg(any(kani, test))] mod proofs;"}

EXACT = ("A slice of a width written in the same expression (`d[o..o + N]`) made into an array of that width: the conversion cannot fail. "
         "The slicing before it panics if the data is shorter than `o + N`")
# (file, a piece of the line) -> why this place cannot fail, or what happens when it does. Checked from the first to
# the last; a place takes the first reason whose file and piece it matches.
WHY: list[tuple[str, str, str]] = [
    # -- knos_oidc (read line by line for this list)
    ("programs-v2/knos_oidc/src/claims.rs", "debug_assert_eq!(w - from, out_len)",
     "A debug assertion: it is not compiled into a release build, which is what `cargo build-sbf` makes. In a test build it says the decoder wrote as many bytes as `b64_len` promised."),
    ("programs-v2/knos_oidc/src/lib.rs", "fn i64_at(",
     EXACT + ". Every caller reads `K_ACTIVE` (8) or `K_EXPIRES` (16) of a key account after `key_limbs` accepted it, which requires its length to be `K_HDR` (40) plus the limbs: it is never shorter."),
    ("programs-v2/knos_oidc/src/lib.rs", "n0inv: u32::from_le_bytes(d[K_N0INV..K_N0INV + 4]",
     EXACT + ". `load_key` runs `key_limbs` first, so the account holds at least its 40-byte header: it is never shorter."),
    ("programs-v2/knos_oidc/src/lib.rs", "let n0inv = u32::from_le_bytes(rest[0..4]",
     EXACT + ". The line before refuses instruction data whose length is not `4 + 4 * l`: it is never shorter."),
    ("programs-v2/knos_oidc/src/lib.rs", "ikey_audience(d[K_HDR + 8 * l..K_HDR + 8 * l + 32]",
     EXACT + ". `key_limbs` accepted the account, and for an issuer number of ISSUER_OTHER or above that requires 64 bytes after the limbs: it is never shorter."),
    # -- knos_passkey (the guard named is the one on the lines just before)
    ("programs-v2/knos_passkey/src/lib.rs", "d[W_KEY..W_KEY + webauthn::KEY_LEN]", EXACT + ". `wallet_key` refuses an account whose length is not `WALLET_LEN` first."),
    ("programs-v2/knos_passkey/src/lib.rs", "d[W_NONCE..W_NONCE + 8]", EXACT + ". `wallet_key` refuses an account whose length is not `WALLET_LEN` first."),
    ("programs-v2/knos_passkey/src/lib.rs", "fund_data[17..25]", EXACT + ". Data shorter than `FUND_MIN` (158 bytes) was refused before the wallet signed anything."),
    ("programs-v2/knos_passkey/src/lib.rs", "data[0..8]", EXACT + ". The line before refuses instruction data shorter than 16 bytes (18 in `fund`)."),
    ("programs-v2/knos_passkey/src/lib.rs", "data[8..16]", EXACT + ". The line before refuses instruction data shorter than 16 bytes (18 in `fund`)."),
    ("programs-v2/knos_passkey/src/token.rs", "d[o..o + 32]", EXACT + ". `o` is 0 or 32, and the line before returns unless the account is at least `ACCOUNT_LEN` (165) bytes."),
    ("programs-v2/knos_passkey/src/token.rs", "d.get(64..72)", "`get(64..72)` gives eight bytes or nothing, and nothing is answered with InvalidAccountData: the conversion of eight bytes cannot fail."),
    # -- knos_meter and knos_pay
    ("programs-v2/knos_meter/src/gh.rs", "artifact.try_into().unwrap()", "Two lines above, the audience is refused unless `is_hex(artifact, 40)`, which is false for any length but 40: the conversion to 40 bytes cannot fail."),
    ("", "k.chunks(4)", "`k` is a 32-byte public key, so every chunk is four bytes: the conversion cannot fail."),
    ("", "size.len() == 8 =>", "The same match arm requires `size.len() == 8`: the conversion of eight bytes cannot fail."),
    ("programs-v2/knos_pay/src/order.rs", "rest[..32].try_into().unwrap(), rest[32..]", "The line before refuses the instruction unless `rest.len() == 64`: both halves are 32 bytes, and neither conversion can fail."),
    ("programs-v2/knos_pay/src/order_judge.rs", "data[..32].try_into().unwrap(), terms: data[32..]", "Three lines above, the instruction is refused unless `data.len() == 64`: both halves are 32 bytes, and neither conversion can fail."),
    ("", "pub fn u32_at(", EXACT + ". The helper is called with constant offsets into an account or instruction data; this list does not re-derive each caller's length check. Short data aborts the transaction."),
    ("", "pub fn u64_at(", EXACT + ". As `u32_at`."),
    ("", "pub fn i64_at(", EXACT + ". As `u32_at`."),
    ("", "pub fn key_at(", EXACT + ". As `u32_at`."),
    # every other `d[A..A + N].try_into().unwrap()` in the three other programs
    ("", ".try_into().unwrap()", EXACT + ": a constant offset into account data. This list does not re-derive the reader's length check; short data aborts the transaction."),
]


def sources() -> list[Path]:
    return sorted(p for name in PROGRAMS for p in (ROOT / "programs-v2" / name / "src").glob("*.rs"))


def split(path: Path) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """(the lines of program code, the lines of tests and proofs), each (number, text) with comments cut off."""
    rel = path.relative_to(ROOT).as_posix()
    code: list[tuple[int, str]] = []
    tests: list[tuple[int, str]] = []
    in_tests = rel in NOT_BUILT
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("#[cfg(test)]"):                # the unit tests are the end of each file
            in_tests = True
        text = re.sub(r"\s*//.*$", "", line)               # no string in these sources holds `//` before a panic or an index
        (tests if in_tests else code).append((number, text))
    return code, tests


def places() -> list[tuple[str, int, int, str]]:
    """(file, line, how many on the line, the line) of every written panic in program code."""
    return [(path.relative_to(ROOT).as_posix(), number, len(PANICS.findall(text)), text.strip())
            for path in sources() for number, text in split(path)[0] if PANICS.search(text)]


def why(rel: str, text: str) -> str | None:
    return next((reason for file, piece, reason in WHY if rel.endswith(file) and piece in text), None)


def counts() -> list[tuple[str, int, int, int]]:
    """(file, written panics in program code, written panics in tests and proofs, lines of program code that index)."""
    out = []
    for path in sources():
        code, tests = split(path)
        out.append((path.relative_to(ROOT).as_posix(), sum(len(PANICS.findall(t)) for _, t in code), sum(len(PANICS.findall(t)) for _, t in tests),
                    sum(1 for _, t in code if INDEX.search(t) and not t.lstrip().startswith("#["))))
    return out


def render() -> str:
    found, table = places(), counts()
    unwraps = sum(len(re.findall(r"\bunwrap\(\)", t)) for path in sources() for part in split(path) for _, t in part)
    in_code = sum(len(re.findall(r"\bunwrap\(\)", t)) for path in sources() for _, t in split(path)[0])
    out = ["# Where a program can panic", "",
           "Written by `python tests/test_unwraps.py --write` from the programs' source; `tests/test_unwraps.py` fails when this page is not what that command",
           "writes. Do not edit it by hand: the reasons are in that file.", "",
           "A panic in a Solana program aborts the instruction and with it the whole transaction. The runtime keeps none of the transaction's account",
           "changes: no state is written and no token moves. What a panic costs is the transaction fee and an error that names no cause. So the question for",
           "each place below is whether it can be reached, and the answer wanted is no.", "",
           f"The four programs' source holds {unwraps} `unwrap()` calls. {in_code} are in program code, on the {sum(1 for _, _, _, t in found if 'unwrap()' in t)} lines listed below; "
           f"the other {unwraps - in_code} are in unit tests and proof harnesses",
           "(`#[cfg(test)]` at the end of each file, and `knos_pay/src/proofs.rs`, which is compiled only for tests and for the Kani model checker), which are in",
           "no build of a program. No program code holds an `expect(`, an `unreachable!`, a `panic!`, a `todo!` or an `assert!`; one `debug_assert_eq!` is listed.",
           "`knos_oidc`'s places were read line by line: none can be reached, so none was replaced. For the three other programs (`knos_pay`, `knos_meter`,",
           "`knos_passkey`) a reason names the guard where it is on the lines just before, and says so where the guard is a caller's.", "",
           "## Every written panic in program code", "",
           "| Place | The line | Why it cannot fail, or what happens if it does |", "| --- | --- | --- |"]
    for rel, number, n, text in found:
        shown = text if len(text) <= 150 else text[:147] + "..."
        out.append(f"| `{rel.removeprefix('programs-v2/')}:{number}`{f' ({n} on the line)' if n > 1 else ''} | `{shown.replace('|', chr(92) + '|')}` | {why(rel, text)} |")
    out += ["", "## Indexing", "",
            "`d[k]` and `d[a..b]` panic when the index is past the end. They are counted here by file (lines of program code that index a slice, an array or a",
            "`Vec`; a line can index several times), not explained one by one. What keeps them in range, by kind: an account's data is read at constant offsets",
            "after its owner and its length were checked (`key_limbs` and `T_JWT + len` in `knos_oidc`; the `*_LEN` checks of the other programs); instruction data",
            "is measured before it is cut; the claim readers and the base64 decoders (`knos_oidc/src/strict.rs` and `claims.rs`) index inside loops bounded by the slice's length, and",
            "are run on 1,560,000 random documents and by two fuzz targets ([ASSURANCE.md](ASSURANCE.md)); the RSA limbs (`rsa.rs`) are vectors sized from the key's",
            "own limb count. An index that is out of range all the same aborts the transaction, as above.", "",
            "The table's middle column counts every written panic in tests and proofs, not only `unwrap()`.", "",
            "| File | Written panics in program code | In tests and proofs | Lines of program code that index |", "| --- | ---: | ---: | ---: |"]
    out += [f"| `{rel.removeprefix('programs-v2/')}` | {a} | {b} | {c} |" for rel, a, b, c in table]
    out.append(f"| all | {sum(a for _, a, _, _ in table)} | {sum(b for _, _, b, _ in table)} | {sum(c for _, _, _, c in table)} |")
    return "\n".join(out) + "\n"


def test_every_written_panic_in_program_code_has_a_reason_and_every_reason_a_place():
    found = places()
    assert found and all(why(rel, text) for rel, _, _, text in found), [(rel, n) for rel, n, _, text in found if not why(rel, text)]
    # a reason that no place takes is stale (a place takes the first reason it matches)
    taken = {next(k for k, (file, piece, _) in enumerate(WHY) if rel.endswith(file) and piece in text) for rel, _, _, text in found}
    assert taken == set(range(len(WHY))), [WHY[k][:2] for k in set(range(len(WHY))) - taken]
    # the page says in words which kinds there are: unwraps, and one debug assertion
    assert {kind for _, _, _, text in found for kind in PANICS.findall(text)} == {"unwrap()", "debug_assert_eq!"}
    assert sum("debug_assert_eq!" in text for _, _, _, text in found) == 1
    # in knos_oidc, no reason is the general one: each was read
    assert all(why(rel, text) is not WHY[-1][2] for rel, _, _, text in found if "/knos_oidc/" in rel)


def test_the_page_is_what_the_source_says_today():
    assert DOC.read_text(encoding="utf-8").replace("\r\n", "\n") == render(), "run: python tests/test_unwraps.py --write"


def test_what_is_called_a_test_or_a_proof_is_in_no_build_of_a_program():
    for rel, declared in NOT_BUILT.items():
        assert declared in (ROOT / rel).with_name("lib.rs").read_text(encoding="utf-8"), rel
    for path in sources():
        text = path.read_text(encoding="utf-8")
        if "#[cfg(test)]" in text:                         # the first one opens the tests, and what follows it is tests to the end
            tail = text[text.index("\n#[cfg(test)]"):]
            assert re.match(r"\n#\[cfg\(test\)\]\n(pub )?mod \w+ \{", tail), path.name
    # the scan sees a panic where there is one, and none in a comment or in the tests
    code, tests = split(ROOT / "programs-v2" / "knos_oidc" / "src" / "claims.rs")
    assert any("unwrap()" in t for _, t in tests) and not any("unwrap()" in t for _, t in code)
    assert PANICS.findall("x.unwrap(); y.expect(\"z\"); unreachable!(); assert!(a); debug_assert_eq!(a, b)") == ["unwrap()", "expect(", "unreachable!", "assert!", "debug_assert_eq!"]
    assert not PANICS.search("x.unwrap_or(0); y.unwrap_or_else(|| 1); z.ok_or_else(bad)?")
    assert INDEX.search("d[K_STATE]") and INDEX.search("&d[a..b]") and INDEX.search("f(x)[0]") and not INDEX.search("let a: &[u8] = &x[..]; vec![0u8; 4]")


if __name__ == "__main__":
    if sys.argv[1:] == ["--write"]:
        DOC.write_text(render(), encoding="utf-8", newline="\n")
        print(f"wrote {DOC.relative_to(ROOT)}: {len(places())} places")
    else:
        sys.exit("usage: python tests/test_unwraps.py --write")
