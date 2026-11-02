#!/usr/bin/env bash
# Prepare a GitHub Codespace to build and test the NEAR contract.
#   bash near/scripts/codespace-setup.sh
# Builds and tests only: no NEAR key enters the codespace. Deploys run from a machine that holds the keys.
set -euo pipefail
log() { echo "$(date -u +%T) $*"; }
command -v cargo >/dev/null || { curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal; }
. "$HOME/.cargo/env"
rustup target add wasm32-unknown-unknown
command -v cargo-near >/dev/null && cargo near --version | grep -q 0.22.0 || cargo install --locked cargo-near --version 0.22.0
export CARGO_TARGET_DIR=/tmp/near-target
log "ready: $(rustc --version), $(cargo near --version), target $CARGO_TARGET_DIR"
