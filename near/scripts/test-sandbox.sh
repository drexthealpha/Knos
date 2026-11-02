#!/usr/bin/env bash
# Builds the contract and the sandbox test token to wasm with cargo-near, then runs every test, the sandbox one included.
#   bash near/scripts/test-sandbox.sh            (needs cargo-near 0.22.0 and the wasm32-unknown-unknown target)
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$here/target}"
for c in contract mock-usdc; do
  (cd "$here/$c" && cargo near build non-reproducible-wasm --no-abi)
done
export KNOS_WASM="$CARGO_TARGET_DIR/near/knos_near.wasm" USDC_WASM="$CARGO_TARGET_DIR/near/knos_mock_usdc.wasm"
ls -l "$KNOS_WASM" "$USDC_WASM"
(cd "$here/contract" && cargo test)
cd "$here/sandbox" && cargo test -- --include-ignored --nocapture
