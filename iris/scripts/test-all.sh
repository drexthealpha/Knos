#!/usr/bin/env bash
# Every IRIS test in one command, in replay mode (no key): build and start, health, the decisions, the one-trace test and
# the bonuses test. Prints seconds and the container's peak memory; exits 0 only when every step passes.
#   bash iris/scripts/test-all.sh [result file]
set -uo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:-/tmp/iris-test-all.txt}"
t0=$(date +%s); fails=0
log() { echo "$(date -u +%T) $*" | tee -a "$out"; }
step() { local name="$1"; shift; local t=$(date +%s); if "$@" >> "$out.log" 2>&1; then log "PASS $name $(( $(date +%s) - t )) s"; else log "FAIL $name $(( $(date +%s) - t )) s (see $out.log)"; fails=$((fails + 1)); fi; }

cd "$here"
# one run at a time: a second copy would share the container and the inbox
exec 9>/tmp/iris-test-all.lock; flock -n 9 || { echo "another test-all.sh is running"; exit 3; }
[ -f .env ] || cp .env.example .env
grep -q '^KNOS_AI_MODE=live' .env && { log "FAIL .env asks for live mode; this script runs replay only"; exit 2; }

# the container's memory, every 5 s, the largest kept
peak=/tmp/iris-peak.txt; echo 0 > "$peak"
( while :; do
    m=$(docker stats --no-stream --format '{{.MemUsage}}' knos-iris 2>/dev/null | awk '{v=$1; if (v ~ /GiB/) {sub(/GiB/,"",v); v*=1024} else {sub(/MiB/,"",v)}; print int(v)}')
    [ "${m:-0}" -gt "$(cat "$peak")" ] && echo "$m" > "$peak"; sleep 5
  done ) & sampler=$!
trap 'kill $sampler 2>/dev/null' EXIT

step build docker compose build --progress plain
tu=$(date +%s); docker compose up -d >> "$out.log" 2>&1
health=""
for i in $(seq 1 120); do
  health=$(python3 -I scripts/knos_http.py http://localhost:52773/api/knos/health 2>/dev/null | tail -1)
  case "$health" in *'"production":"Running"'*'"java":"ok"'*'"vector":"ok"'*) break;; esac
  sleep 5
done
case "$health" in
  *'"production":"Running"'*'"java":"ok"'*'"vector":"ok"'*) hl="PASS health $(( $(date +%s) - tu )) s after start: $health"; log "$hl";;
  *) log "FAIL health after $(( $(date +%s) - tu )) s: $health"; fails=$((fails + 1));;
esac
step decisions python3 tests/test_iris_decision.py http://localhost:52773 /tmp/iris-decisions.txt
step one_trace python3 tests/test_iris_one_trace.py knos-iris /tmp/iris-one-trace.txt
# IPM (ZPM) is not in the image: InterSystems' v0.10.10 installer, checked by its sha256
zpm=/tmp/zpm-0.10.10.xml
[ -s "$zpm" ] || curl -fsSL -o "$zpm" https://github.com/intersystems/ipm/releases/download/v0.10.10/zpm-0.10.10.xml
echo "daa2adabd66b488f57187d29712e54b0c25bbe000794fbf2a35a882c458b788a  $zpm" | sha256sum -c --quiet && export KNOS_ZPM_XML="$zpm"
step bonuses python3 tests/test_iris_bonuses.py knos-iris /tmp/iris-bonuses.txt "${hl:-}"
step dashboard bash -c 'curl -fsS http://localhost:52773/knos/ | grep -q "Knos Referee" && test "$(curl -s -o /dev/null -w %{http_code} http://localhost:52773/api/knos/decisions)" = 401 && curl -fsS -u _SYSTEM:SYS http://localhost:52773/api/knos/decisions | python3 -c "import json,sys; d=json.load(sys.stdin); assert isinstance(d, list) and d, d"'

log "total $(( $(date +%s) - t0 )) s, peak $(cat "$peak") MiB, $fails failed"
[ "$fails" = 0 ]
