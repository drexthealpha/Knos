#!/usr/bin/env bash
# Is Knos ready? Waits up to 5 minutes for IRIS, then says what to open, or what is wrong and the next step.
#   bash scripts/ready.sh [http://localhost:52773]      (from iris/)
set -uo pipefail
base="${1:-http://localhost:52773}"
here="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$here/.env" ] && { set -a; . "$here/.env"; set +a; }
if command -v docker >/dev/null && ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx knos-iris; then
  echo "NOT READY: the knos-iris container is not running. Next: docker compose up -d --build (in iris/)"; exit 1
fi
for i in $(seq 1 60); do
  h=$(curl -fsS -u "_SYSTEM:${IRIS_PASSWORD:-}" "$base/api/knos/health" 2>/dev/null) && break
  code=$(curl -s -o /dev/null -w '%{http_code}' -u "_SYSTEM:${IRIS_PASSWORD:-}" "$base/api/knos/health" 2>/dev/null)
  if [ "$code" = 401 ]; then echo "NOT READY: IRIS refused the password. Next: check IRIS_PASSWORD in iris/.env, then docker compose up -d"; exit 1; fi
  [ "$i" = 1 ] && echo "IRIS is starting; waiting (up to 5 minutes)..."
  sleep 5
done
[ -n "${h:-}" ] || { echo "NOT READY: no answer from $base after 5 minutes. Next: docker compose logs iris | tail -40"; exit 1; }
field() { printf '%s' "$h" | sed -n "s/.*\"$1\":\"\\([^\"]*\\)\".*/\\1/p"; }
prod=$(field production); agent=$(field agent)
if [ "$prod" != "Running" ]; then echo "NOT READY: the production is ${prod:-unknown}. Next: docker compose restart iris, then run this again"; exit 1; fi
if [ "$agent" = replay ]; then
  echo "READY: open $base/knos/ and press a sample button (the built-in demo in replay mode: no key and no sign-in)."
else
  echo "READY: open $base/knos/ and sign in as _SYSTEM with the IRIS_PASSWORD line of iris/.env (agent: $agent)."
fi
