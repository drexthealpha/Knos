//! Copies the fee arithmetic out of the program's source, as text, into OUT_DIR/fee.rs: the constants of the fee
//! schedule, `bps_of` and `order_fee` from ../knos_pay/src/lib.rs, and `units` from ../knos_pay/src/state.rs. A line
//! that is missing stops the build: the proofs are about the program's lines or about nothing.
use std::{env, fs, path::Path};

const CONSTS: [&str; 9] = ["FEE_BPS", "MAX_AMOUNT", "ORDER_FEE_MIN", "FEE_TIER_1", "FEE_TIER_2", "FEE_BPS_2", "FEE_BPS_3", "ORDER_MIN_AMOUNT", "PLAN_BPS_MIN"];

/// The item that starts with `head` at the start of a line, up to the end of that line (`one_line`) or to the first
/// line that is `}` alone.
fn item(source: &str, head: &str, one_line: bool) -> String {
    let mut out = String::new();
    let mut lines = source.lines().skip_while(|l| !l.starts_with(head));
    for line in &mut lines {
        out.push_str(line);
        out.push('\n');
        if one_line || line == "}" { return out; }
    }
    panic!("no `{head}` in the program's source");
}

fn main() {
    let dir = Path::new(&env::var("CARGO_MANIFEST_DIR").unwrap()).join("../knos_pay/src");
    let (lib, state) = (dir.join("lib.rs"), dir.join("state.rs"));
    println!("cargo:rerun-if-changed={}", lib.display());
    println!("cargo:rerun-if-changed={}", state.display());
    let (lib, state) = (fs::read_to_string(lib).unwrap(), fs::read_to_string(state).unwrap());
    let mut out = String::from("// Copied by build.rs from programs-v2/knos_pay/src/lib.rs and state.rs. Not edited by hand.\n");
    for name in CONSTS { out.push_str(&item(&lib, &format!("pub const {name}: u64 = "), true)); }
    out.push_str(&item(&lib, "pub fn bps_of(", true));
    out.push_str(&item(&lib, "pub fn order_fee(", false));
    out.push_str("pub mod state {\n");
    out.push_str(&item(&state, "pub fn units(", false));
    out.push_str("}\n");
    fs::write(Path::new(&env::var("OUT_DIR").unwrap()).join("fee.rs"), out).unwrap();
}
