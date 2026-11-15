#!/usr/bin/env bash
# A local Solana validator with the devnet-deployed programs Knos composes: the Solana Attestation Service and
# Lighthouse. SPL Token, ATA and Memo are already in the validator's genesis. Tests and the bench run here, because
# devnet airdrops are rate-limited; the recorded demo runs on devnet.
#
#   scripts/devchain.sh start    # clone both programs from devnet, start on 127.0.0.1:8899, wait until healthy
#   scripts/devchain.sh stop
#   scripts/devchain.sh status
#
# Needs the Solana CLI (Anza installer). Set KNOS_DEVCHAIN_DIR to move the ledger (default ~/.knos-devchain).
set -euo pipefail

SAS=22zoJMtdu4tQc2PzL74ZUT7FrwgB1Udec8DdW4yw4BdG
LIGHTHOUSE=L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95
DIR="${KNOS_DEVCHAIN_DIR:-$HOME/.knos-devchain}"
URL=http://127.0.0.1:8899
export PATH="$HOME/.local/share/solana/install/active_release/bin:$PATH"

healthy() {
  curl -s -m 2 -X POST -H 'Content-Type: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}' "$URL" 2>/dev/null | grep -q '"ok"'
}

case "${1:-start}" in
  start)
    if healthy; then echo "devchain already running at $URL"; exit 0; fi
    mkdir -p "$DIR"
    # --limit-ledger-size keeps the ledger small: tests only need current state, and an unbounded ledger grows by
    # gigabytes an hour, which a slow disk cannot keep up with.
    nohup solana-test-validator --reset --quiet --ledger "$DIR/ledger" --limit-ledger-size 10000 \
      --clone-upgradeable-program "$SAS" --clone-upgradeable-program "$LIGHTHOUSE" --url devnet \
      >"$DIR/validator.log" 2>&1 &
    echo $! >"$DIR/pid"
    for _ in $(seq 1 120); do
      if healthy; then echo "devchain up at $URL (SAS and Lighthouse cloned from devnet)"; exit 0; fi
      if ! kill -0 "$(cat "$DIR/pid")" 2>/dev/null; then echo "validator exited; see $DIR/validator.log" >&2; exit 1; fi
      sleep 1
    done
    echo "validator not healthy after 120s; see $DIR/validator.log" >&2; exit 1 ;;
  stop)
    if [ -f "$DIR/pid" ]; then kill "$(cat "$DIR/pid")" 2>/dev/null || true; rm -f "$DIR/pid"; fi
    echo "devchain stopped" ;;
  status)
    if healthy; then echo "up at $URL"; else echo "down"; exit 1; fi ;;
  *) echo "usage: $0 start|stop|status" >&2; exit 2 ;;
esac
