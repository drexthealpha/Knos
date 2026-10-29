#!/usr/bin/env bash
# I1 test_iris_up: from a fresh clone and the README's own commands: load and retag the image, `docker compose up -d
# --build`, then the health route within 180 s of the container starting (production Running, java ok, vector ok,
# fhir off), then the 5 core decisions right (iris/tests/test_iris_decision.py, its first 5 cases), with the peak memory
# measured during the build and the run (the Docker VM's used memory and the container's own, every 5 s) under 2.5 GB.
#   bash iris/tests/test_iris_up.sh <image tar> <commit sha> <result file>
set -uo pipefail
tar="$1"; sha="$2"; out="$3"
work="$(mktemp -d)"
log() { echo "$1" | tee -a "$out"; }
PY=python3; "$PY" -c "" 2>/dev/null || PY=py
git clone -q https://github.com/drexthealpha/Knos "$work/Knos" && git -C "$work/Knos" checkout -q "$sha" || { log "FAIL test_iris_up: the clone at $sha"; exit 1; }
cd "$work/Knos/iris"
# the memory sampler: the VM's used memory (MiB) and knos-iris's own, the largest of each kept
peak="$work/peak.txt"; echo "0 0" > "$peak"
( while :; do
    vm=$(wsl.exe -d docker-desktop -e free -m 2>/dev/null | tr -d '\r' | awk '/^Mem:/ {print $3}')
    ct=$(docker stats --no-stream --format '{{.MemUsage}}' knos-iris 2>/dev/null | awk '{v=$1; if (v ~ /GiB/) {sub(/GiB/,"",v); v*=1024} else {sub(/MiB/,"",v)}; print int(v)}')
    read -r pv pc < "$peak"; [ "${vm:-0}" -gt "$pv" ] && pv=$vm; [ "${ct:-0}" -gt "$pc" ] && pc=$ct; echo "$pv $pc" > "$peak"
    sleep 5
  done ) & sampler=$!
trap 'kill $sampler 2>/dev/null' EXIT
# the README's commands, as it gives them (section "Run it")
bash scripts/load-image.sh "$tar" | tail -2 | while read -r l; do log "     $l"; done
cp .env.example .env
docker builder prune -f >/dev/null 2>&1
t0=$(date +%s)
docker compose up -d --build >"$work/build.log" 2>&1 || { log "FAIL test_iris_up: docker compose up: $(tail -3 "$work/build.log" | tr '\n' ' ')"; exit 1; }
built=$(( $(date +%s) - t0 ))
log "ok   built and started in ${built} s"
start=$(date +%s); health=""
while [ $(( $(date +%s) - start )) -lt 180 ]; do
  health=$(curl -fsS -m 10 -u _SYSTEM:SYS http://localhost:52773/api/knos/health 2>/dev/null) && break
  sleep 5
done
waited=$(( $(date +%s) - start ))
ok=$(printf '%s' "$health" | "$PY" -c 'import json,sys
try: h=json.load(sys.stdin)
except Exception: print("no"); sys.exit()
print("yes" if h.get("production")=="Running" and h.get("fhir")=="off" and h.get("java")=="ok" and h.get("vector")=="ok" else "no")' 2>/dev/null || echo no)
log "$([ "$ok" = yes ] && echo 'ok  ' || echo 'FAIL') health after ${waited} s: ${health:-no answer}"
"$PY" tests/test_iris_decision.py http://localhost:52773 > "$work/decisions.txt" 2>&1
right=$(head -n 20 "$work/decisions.txt" | grep -E "^(ok  |FAIL) (a passing|a failing|an altered|injection|an ORU)" | grep -c "^ok  ")
grep -E "^(ok  |FAIL) (a passing|a failing|an altered|injection|an ORU)" "$work/decisions.txt" | while read -r l; do log "     $l"; done
sleep 20
read -r pv pc < "$peak"
log "     peak memory: the Docker VM used ${pv} MiB, knos-iris ${pc} MiB (sampled every 5 s through the build and the run)"
if [ "$ok" = yes ] && [ "$right" = 5 ] && [ "$pc" -gt 0 ] && [ "$pc" -lt 2560 ]; then
  log "PASS test_iris_up: built in ${built} s from the README's commands, healthy ${waited} s after start with fhir off, 5 of 5 decisions right, peak docker stats ${pc} MiB (the VM ${pv} MiB)"; exit 0
fi
log "FAIL test_iris_up: health $([ "$ok" = yes ] && echo green || echo 'not green within 180 s'), ${right} of 5 decisions right, peak docker stats ${pc} MiB (under 2560 wanted; the VM ${pv} MiB)"
exit 1
