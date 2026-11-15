#!/usr/bin/env bash
# Build the two programs of the first deployment and the example, and refresh the binaries the tests load.
# (The second deployment, programs-v2, is built by scripts/build_programs_v2.sh.)
#
#   bash scripts/build_programs.sh          # needs cargo build-sbf (agave 2.3) on PATH
#
#   programs/knos_oidc    real build (no features)            -> programs/target/deploy/knos_oidc.so
#                         test build (--features testkeys)    -> tests/fixtures/knos_oidc_test.so
#   programs/knos_pay     devnet build (default features)     -> programs/target/deploy/knos_pay.so
#                                                                and tests/fixtures/knos_pay_test.so
#                         real-money build (no faucet)        -> tests/fixtures/knos_pay_nodevnet.so
#   examples/oidc_gate    the example consumer                -> tests/fixtures/oidc_gate_test.so
#                         (reads tokens with crates/knos-oidc-interface, not with the program's crate)
#
# The test build of knos-oidc also trusts two seed-derived test keys; it is never deployed. The real build is built
# LAST for each program, so what is left in target/deploy is the binary to deploy. Run this again after changing a
# program id (programs/program_ids.json, OIDC_ID in knos_pay, ID in crates/knos-oidc-interface) or ROTATE_SHA: the
# ids are compiled in.
#
# With CARGO_TARGET_DIR set (an absolute path), cargo writes there and every binary is taken from
# $CARGO_TARGET_DIR/deploy instead of programs/target/deploy and examples/oidc_gate/target/deploy.
set -euo pipefail
cd "$(dirname "$0")/.."
fix=tests/fixtures
deploy="${CARGO_TARGET_DIR:-programs/target}/deploy"

# build <crate directory> <its deploy directory> <name in tests/fixtures, or - for none> [cargo build-sbf arguments]
build() {
  local crate="$1" as="$3" out
  out="$2/$(basename "$1").so"
  shift 3
  # cargo build-sbf leaves deploy/<crate>.so alone when that file is newer than what it built. Removed first, the
  # file that is copied below can only be this build, never one that was left there.
  rm -f "$out"
  (cd "$crate" && cargo build-sbf "$@")
  if [ "$as" != - ]; then cp "$out" "$fix/$as"; fi
}

build programs/knos_oidc "$deploy" knos_oidc_test.so --features testkeys
build programs/knos_oidc "$deploy" -

build programs/knos_pay "$deploy" knos_pay_nodevnet.so --no-default-features
build programs/knos_pay "$deploy" knos_pay_test.so

build examples/oidc_gate "${CARGO_TARGET_DIR:-examples/oidc_gate/target}/deploy" oidc_gate_test.so

sha256sum "$deploy/knos_oidc.so" "$deploy/knos_pay.so" "$fix"/*.so
