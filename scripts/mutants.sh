#!/usr/bin/env bash
# Mutation testing of the two programs' Rust: cargo-mutants changes the source one small piece at a time and runs the
# crate's unit tests on each change; a mutant no test notices is a line the tests do not really check.
#
#   bash scripts/mutants.sh [knos_pay|knos_oidc|all] [--timeout SECONDS]      default: all, 60 s per mutant
#
# It takes hours on a laptop (one build and test run per mutant), so it is not part of the default suite. It writes
# mutants/<crate>/outcomes.json (cargo-mutants' own report) and prints one line per crate:
#     knos_pay: caught 211, missed 9, unviable 34, timeout 0
# Needs: cargo install cargo-mutants --locked (27.x). The unit tests it runs are the crates' own (`cargo test`), with
# the testkeys feature; the Python tests on the compiled programs are a second net this run does not use.
set -euo pipefail
cd "$(dirname "$0")/.."
what="${1:-all}"; shift || true
timeout=60
[ "${1:-}" = "--timeout" ] && timeout="$2"
command -v cargo-mutants >/dev/null || { echo "cargo-mutants is not installed: cargo install cargo-mutants --locked" >&2; exit 2; }
run() {
  local crate="$1"
  mkdir -p "mutants/$crate"
  (cd "programs-v2/$crate" && cargo mutants --features testkeys --timeout "$timeout" --output "../../mutants/$crate" --no-shuffle) || true
  python3 - "$crate" <<'PY'
import json, sys, pathlib
crate = sys.argv[1]
f = next(pathlib.Path("mutants", crate).rglob("outcomes.json"), None)
if not f:
    print(f"{crate}: no report"); sys.exit(1)
n = {}
for o in json.loads(f.read_text()).get("outcomes", []):
    if o.get("scenario") == "Baseline": continue
    n[o.get("summary", "?")] = n.get(o.get("summary", "?"), 0) + 1
print(f"{crate}: caught {n.get('CaughtMutant', 0)}, missed {n.get('MissedMutant', 0)}, unviable {n.get('Unviable', 0)}, timeout {n.get('Timeout', 0)}")
PY
}
case "$what" in
  all) run knos_pay; run knos_oidc ;;
  knos_pay|knos_oidc) run "$what" ;;
  *) echo "usage: bash scripts/mutants.sh [knos_pay|knos_oidc|all] [--timeout SECONDS]" >&2; exit 2 ;;
esac
