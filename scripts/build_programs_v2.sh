#!/usr/bin/env bash
# Build the second deployment's programs (programs-v2) and refresh the binaries the tests load.
#
#   bash scripts/build_programs_v2.sh [oidc|pay|meter|passkey|examples|all]     # default: all. Needs cargo build-sbf on PATH
#
#   programs-v2/knos_oidc   test build (--features testkeys)                  -> tests/fixtures/knos_oidc_v2_test.so
#                           real build (no features)                          -> tests/fixtures/knos_oidc_v2_real.so
#                                                                                and $target/deploy/knos_oidc.so
#   programs-v2/knos_pay    test build (--features testkeys, devnet on)       -> tests/fixtures/knos_pay_v2_test.so
#                           test build, real-money rules (no devnet feature)  -> tests/fixtures/knos_pay_v2_nodevnet.so
#                           devnet build (default features)                   -> $target/deploy/knos_pay.so
#   programs-v2/knos_meter  test build (--features testkeys)                  -> tests/fixtures/knos_meter_test.so
#                           real build (no features)                          -> $target/deploy/knos_meter.so
#   programs-v2/knos_passkey  the one build (no features: it trusts no key)   -> tests/fixtures/knos_passkey_v2_real.so
#                                                                                and $target/deploy/knos_passkey.so
#   examples/cpi_fund       a treasury funds a work order by CPI               -> tests/fixtures/cpi_fund_v2_real.so
#   examples/workflow_vault a vault only one workflow at one commit can spend  -> tests/fixtures/workflow_vault_v2_real.so
#   examples/upgrade_gate   records which commit GitHub built an executable from -> tests/fixtures/upgrade_gate_v2_real.so
#                           (the examples have no test feature, so each is the one build, named real: they read the real
#                           program ids, and their tests run them beside the test builds of knos-oidc and knos_pay)
#
# $target is CARGO_TARGET_DIR when it is set, and programs-v2/target otherwise.
#
# A testkeys build also trusts two seed-derived signing keys, a test rotate pin, the test harness's repository as
# an attester and a test guardian (programs-v2/knos_oidc/src/pins.rs); a testkeys build of knos_meter opens credits in
# any mint and takes a test key for SetPlan; it is never deployed. The real build is
# built LAST for each program, so what is left in $target/deploy is the binary to try on a cluster. The binary that
# is deployed is the reproducible one, program.yml's command run from the repository's root
# (`solana-verify build "$PWD" --workspace-path "$PWD/programs-v2" --library-name <name>`), not this one.
#
# Each fixture is copied right after its own build: the next build overwrites $target/deploy/<name>.so. The hashes
# of the fixtures are pinned in tests/fixtures/SHA256SUMS; this script rewrites the lines of the ones it built, so a
# changed binary shows up in review as a changed pin. Run it again after changing a program id
# (programs-v2/program_ids.json, OIDC_ID in knos_pay), a pin in pins.rs, or any source file of a program.
set -euo pipefail
cd "$(dirname "$0")/.."
what="${1:-all}"
fix=tests/fixtures
target="${CARGO_TARGET_DIR:-$PWD/programs-v2/target}"
built=()

# build <crate> <fixture name, or - for none> [cargo build-sbf arguments]
build() {
  local crate="$1" out="$2"; shift 2
  # cargo build-sbf leaves a deployed file alone when it looks newer than what was just built: remove the last one, so
  # that what is copied below is this build and never the one before it
  rm -f "$target/deploy/$crate.so"
  (cd "programs-v2/$crate" && cargo build-sbf "$@")
  if [ "$out" != "-" ]; then
    cp "$target/deploy/$crate.so" "$fix/$out"
    built+=("$fix/$out")
  fi
}

# the pin of one fixture: replace its line in SHA256SUMS, or add it
pin() {
  local sum; sum="$(sha256sum "$1" | cut -d' ' -f1)"
  grep -v "  $1\$" "$fix/SHA256SUMS" > "$fix/SHA256SUMS.new" || true
  echo "$sum  $1" >> "$fix/SHA256SUMS.new"
  mv "$fix/SHA256SUMS.new" "$fix/SHA256SUMS"
}

# example <name> <fixture name>: an example program (examples/<name>). The three share one target directory
# (CARGO_TARGET_DIR, else examples/target), so their dependencies compile once and programs-v2/target/deploy holds
# the programs and nothing else.
example() {
  local name="$1" out="$2" to="${CARGO_TARGET_DIR:-$PWD/examples/target}"
  rm -f "$to/deploy/$name.so"
  (cd "examples/$name" && CARGO_TARGET_DIR="$to" cargo build-sbf)
  cp "$to/deploy/$name.so" "$fix/$out"
  built+=("$fix/$out")
}

case "$what" in oidc|pay|meter|passkey|examples|all) ;; *) echo "usage: bash scripts/build_programs_v2.sh [oidc|pay|meter|passkey|examples|all]" >&2; exit 2 ;; esac

if [ "$what" = oidc ] || [ "$what" = all ]; then
  build knos_oidc knos_oidc_v2_test.so --features testkeys
  build knos_oidc knos_oidc_v2_real.so
fi

if [ "$what" = pay ] || [ "$what" = all ]; then
  build knos_pay knos_pay_v2_nodevnet.so --no-default-features --features testkeys
  build knos_pay knos_pay_v2_test.so --features testkeys
  build knos_pay -
fi

if [ "$what" = meter ] || [ "$what" = all ]; then
  build knos_meter knos_meter_test.so --features testkeys
  build knos_meter -
fi

if [ "$what" = passkey ] || [ "$what" = all ]; then
  build knos_passkey knos_passkey_v2_real.so
fi

if [ "$what" = examples ] || [ "$what" = all ]; then
  example cpi_fund cpi_fund_v2_real.so
  example workflow_vault workflow_vault_v2_real.so
  example upgrade_gate upgrade_gate_v2_real.so
  example reader_template reader_template_v2_real.so
fi

for f in "${built[@]}"; do pin "$f"; done
sha256sum "${built[@]}"
ls "$target/deploy/"*.so | xargs sha256sum
