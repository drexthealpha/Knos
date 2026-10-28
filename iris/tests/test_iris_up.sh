#!/usr/bin/env bash
# I1 test_iris_up: from a fresh clone, load and retag the image, `docker compose up -d --build`, then the health route
# within 180 s of the container starting (production Running, fhir ok, java ok, vector ok), then smoke.sh's decision
# and Visual Trace URL.   bash iris/tests/test_iris_up.sh <image tar> <commit sha> <result file>
set -uo pipefail
tar="$1"; sha="$2"; out="$3"
work="$(mktemp -d)"
log() { echo "$1" | tee -a "$out"; }
git clone -q https://github.com/drexthealpha/Knos "$work/Knos" && git -C "$work/Knos" checkout -q "$sha" || { log "FAIL test_iris_up: the clone at $sha"; exit 1; }
cd "$work/Knos/iris"
bash scripts/load-image.sh "$tar" | tail -2 | while read -r l; do log "     $l"; done
cp .env.example .env
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
ok=$(printf '%s' "$health" | python3 -c 'import json,sys
try: h=json.load(sys.stdin)
except Exception: print("no"); sys.exit()
print("yes" if h.get("production")=="Running" and h.get("fhir")=="ok" and h.get("java")=="ok" and h.get("vector")=="ok" else "no")' 2>/dev/null || echo no)
log "$([ "$ok" = yes ] && echo 'ok  ' || echo 'FAIL') health after ${waited} s: ${health:-no answer}"
smoke=$(bash scripts/smoke.sh 2>&1 | tail -3)
log "     $smoke"
if [ "$ok" = yes ] && printf '%s' "$smoke" | grep -q "visual trace: http"; then
  log "PASS test_iris_up: built in ${built} s, healthy ${waited} s after start, smoke.sh printed a decision and its Visual Trace URL"; exit 0
fi
log "FAIL test_iris_up: health $([ "$ok" = yes ] && echo green || echo 'not green within 180 s'), smoke $(printf '%s' "$smoke" | grep -q 'visual trace' && echo ok || echo 'gave no trace URL')"
exit 1
