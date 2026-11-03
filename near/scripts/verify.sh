#!/usr/bin/env bash
# Every NEAR test in one command: the contract's unit tests, then both wasm builds and the near-sandbox flow.
# Prints N/N and the attack count; exits 0 only when every test passes.
#   bash near/scripts/verify.sh
set -uo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-/tmp/near-target}"
log=$(mktemp)
attacks=$(cat "$here"/contract/src/tests.rs "$here"/contract/src/tests/*.rs | grep -cE '(refused|refused_fund|refused_payout)!\(adversarial_|fn adversarial_')
bash "$here/scripts/test-sandbox.sh" > "$log" 2>&1; rc=$?
passed=$(grep -oE 'test result: [a-zA-Z]+\. [0-9]+ passed' "$log" | awk '{s += $4} END {print s + 0}')
failed=$(grep -oE '[0-9]+ failed' "$log" | awk '{s += $1} END {print s + 0}')
grep -E '^SANDBOX ' "$log"
line="$passed/$((passed + failed)) tests passed ($attacks of them attacks)"
echo "$line, exit $rc"
[ "$rc" = 0 ] && [ "$failed" = 0 ] && [ "$passed" -gt 0 ] || exit 1
# the README's test line is this print, never a number typed apart from it
want="It prints \`$line\`"
grep -qF "$want" "$here/README.md" || { echo "near/README.md does not say: $want"; exit 1; }
