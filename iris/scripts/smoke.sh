#!/usr/bin/env bash
# The first proof, end to end: the health route, then lock the code brief and send its passing check run.
# Prints the decision and its Visual Trace URL.   bash iris/scripts/smoke.sh [http://localhost:52773]
set -euo pipefail
base="${1:-http://localhost:52773}"
here="$(cd "$(dirname "$0")/.." && pwd)"
auth="_SYSTEM:${IRIS_PASSWORD:-SYS}"
echo "health: $(curl -fsS -u "$auth" "$base/api/knos/health")"
brief=$(cat "$here/fixtures/briefs/code.json")
curl -fsS -u "$auth" -H 'Content-Type: application/json' -X POST "$base/api/knos/brief" \
  -d "{\"id\":\"github:example/shop\",\"amount_usdc\":20,\"brief\":$brief}"
echo
out=$(curl -fsS -u "$auth" -H 'Content-Type: application/json' -X POST "$base/api/knos/proof" \
  -d "{\"id\":\"github:example/shop\",\"kind\":\"checkrun\",\"payload\":$(cat "$here/fixtures/checkruns/pass.json")}")
echo "decision: $out"
PY=python3; "$PY" -c "" 2>/dev/null || PY=py
printf '%s' "$out" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print("gate:", d["gate"]); print("visual trace:", d["visual_trace"])'
