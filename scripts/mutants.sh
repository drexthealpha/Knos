#!/usr/bin/env bash
# Mutation testing of the two programs' Rust: cargo-mutants changes the source one small piece at a time and runs the
# crate's unit tests on each change; a mutant no test notices is a line the tests do not really check.
#
#   bash scripts/mutants.sh [knos_pay|knos_oidc|all] [--timeout SECONDS]      default: all, 60 s per mutant
#   bash scripts/mutants.sh chain                                             the chain invariants alone (below)
#
# It takes hours on a laptop (one build and test run per mutant), so it is not part of the default suite. It writes
# mutants/<crate>/outcomes.json (cargo-mutants' own report) and prints one line per crate:
#     knos_pay: caught 211, missed 9, unviable 34, timeout 0
# Needs: cargo install cargo-mutants --locked (27.x). The unit tests it runs are the crates' own (`cargo test`), with
# the testkeys feature. After knos_pay's mutants it runs the chain invariants once: the state machine and the gap
# tests (CHAIN_TESTS below) on the compiled test build, tests/fixtures/knos_pay_v2_test.so, and prints
#     knos_pay: chain invariants ok
# cargo-mutants cannot run them per mutant (each needs an SBF build). For a mutant the unit tests missed: apply its
# diff (mutants/knos_pay/mutants.out/diff), `bash scripts/build_programs_v2.sh pay`, `bash scripts/mutants.sh chain`,
# then put the source and the fixtures back (git checkout). KNOS_MACHINE_STEPS and KNOS_MACHINE_SEEDS scale the machine.
set -euo pipefail
cd "$(dirname "$0")/.."
what="${1:-all}"; shift || true
timeout=60
[ "${1:-}" = "--timeout" ] && timeout="$2"
CHAIN_TESTS="tests/test_invariants_machine.py tests/test_invariants_gaps.py"
chain() {
  # shellcheck disable=SC2086
  if PYTHONPATH="$PWD/src" "${PYTHON:-python3}" -m pytest -q -p no:cacheprovider $CHAIN_TESTS; then
    echo "knos_pay: chain invariants ok"
  else
    echo "knos_pay: chain invariants FAILED"; return 1
  fi
}
[ "$what" = "chain" ] && { chain; exit $?; }
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
  all) run knos_pay; chain; run knos_oidc ;;
  knos_pay) run knos_pay; chain ;;
  knos_oidc) run knos_oidc ;;
  *) echo "usage: bash scripts/mutants.sh [knos_pay|knos_oidc|all|chain] [--timeout SECONDS]" >&2; exit 2 ;;
esac
