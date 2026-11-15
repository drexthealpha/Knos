#!/usr/bin/env bash
# Rehearse the second deployment's money flows on a Surfpool fork of mainnet-beta, at no cost: nothing is sent to a
# cluster and no key of ours is used. Wallet funding, a Balance, a bounty by comment, a payment and a refund after the
# fork's clock has been moved, each result printed; the first thing that is not as it should be stops the run.
#
#   bash scripts/rehearse_fork.sh
#
# Surfpool is a local copy of mainnet-beta that reads an account from mainnet-beta the first time it is asked for it, so
# the USDC mint (Circle's), the token programs and the Squads program on it are the real ones. This script puts into the
# fork a wallet (SOL, and USDC from the surfnet_setTokenAccount cheatcode) and the two programs at their pinned ids: the
# test build of knos-oidc and the no-faucet test build of knos-pay from tests/fixtures, written with surfnet_writeProgram.
# The fork's clock is moved with surfnet_timeTravel for the refund. scripts/rehearse_fork.py holds the nine steps and says
# what the run proves and what it does not (it does not prove GitHub's signatures: a test key plays GitHub).
#
# What it reads
#   KNOS_FORK_RPC    the RPC address of a Surfpool you started yourself (surfpool start): used as it is, and left running.
#                    Without it this script starts the embedded Surfpool (scripts/surfnet.mjs) and stops it at the end
#   KNOS_FORK_FROM   the cluster the embedded fork reads accounts from (default https://api.mainnet-beta.solana.com; a
#                    provider's endpoint rate-limits less)
#   PYTHON           the Python that has this repository's requirements and its test requirements (default python3;
#                    pip install -e '.[dev]')
#
# Needs: Python as above; and node 20 or later with `npm ci --prefix scripts` done, unless KNOS_FORK_RPC is set. The embedded
# Surfpool runs on Linux (x64) and macOS; on Windows run this in WSL. The fork reads mainnet-beta over https, and sends nothing to it.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD

case "${1:-}" in
  "") ;;
  -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
  *) echo "usage: bash scripts/rehearse_fork.sh" >&2; exit 2 ;;
esac

PYTHON="${PYTHON:-python3}"
FROM="${KNOS_FORK_FROM:-https://api.mainnet-beta.solana.com}"
RPC="${KNOS_FORK_RPC:-}"
WORK="" SURF=""

die() { echo "stopped: $*" >&2; exit 1; }

# stops the embedded Surfpool by its own process id (never by name: that could be somebody else's)
cleanup() {
  if [ -n "$SURF" ]; then kill "$SURF" 2>/dev/null || true; wait "$SURF" 2>/dev/null || true; fi
  if [ -n "$WORK" ]; then rm -rf "$WORK"; fi
}
trap cleanup EXIT

command -v "$PYTHON" >/dev/null 2>&1 || die "$PYTHON is not on PATH. Set PYTHON to the Python that has this repository's requirements."
"$PYTHON" -c 'import solders, cryptography' 2>/dev/null \
  || die "$PYTHON lacks this repository's requirements (solders) or its test requirements (cryptography). Run: pip install -e '.[dev]'"

if [ -z "$RPC" ]; then
  command -v node >/dev/null 2>&1 || die "node is not on PATH. Install Node 20 or later and run: npm ci --prefix scripts. Or start Surfpool yourself (surfpool start) and set KNOS_FORK_RPC to its address."
  [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 20 ] || die "node $(node --version) is older than 20."
  [ -d "$ROOT/scripts/node_modules/@solana/surfpool" ] \
    || die "the embedded Surfpool is not installed. Run: npm ci --prefix scripts (it installs on Linux x64 and macOS; on Windows use WSL). Or start Surfpool yourself (surfpool start) and set KNOS_FORK_RPC to its address."
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/knos-fork.XXXXXX")"
  node "$ROOT/scripts/surfnet.mjs" --fork "$FROM" --url-file "$WORK/url" > "$WORK/surfpool.log" 2>&1 &
  SURF=$!
  for _ in $(seq 60); do
    [ -s "$WORK/url" ] && break
    kill -0 "$SURF" 2>/dev/null || { cat "$WORK/surfpool.log" >&2; die "the embedded Surfpool did not start."; }
    sleep 0.5
  done
  [ -s "$WORK/url" ] || die "the embedded Surfpool gave no address in 30 seconds."
  RPC="$(head -n 1 "$WORK/url")"
  echo "Surfpool (embedded) is running a fork of $FROM at $RPC"
else
  echo "Surfpool at $RPC (KNOS_FORK_RPC): used as it is"
fi

# the driver's own exit code is this script's: 0 only when all nine steps passed
PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" "$ROOT/scripts/rehearse_fork.py" --rpc "$RPC"
