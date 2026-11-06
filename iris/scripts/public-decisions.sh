#!/usr/bin/env bash
# Three decisions on public data (iris/data/public, sources and licences in SOURCES.md): a Synthea FHIR Observation, an
# HL7 ORU^R01 lab message and a real GitHub check run, each against its own locked brief. Prints each decision.
#   bash iris/scripts/public-decisions.sh [http://localhost:52773]
set -euo pipefail
base="${1:-http://localhost:52773}"
here="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$here/.env" ] && { set -a; . "$here/.env"; set +a; }
auth="_SYSTEM:${IRIS_PASSWORD:?set IRIS_PASSWORD in iris/.env}"
d="$here/data/public"
PY=python3; "$PY" -c "" 2>/dev/null || PY=py
run=$(date +%s)
send() {   # <brief id> <brief file> <kind> <proof file> [signed]
  local id="$1-$run" brief="$2" kind="$3" proof="$4"
  curl -fsS -u "$auth" -H 'Content-Type: application/json' -X POST "$base/api/knos/brief" \
    -d "{\"id\":\"$id\",\"amount_usdc\":20,\"brief\":$(cat "$d/$brief")}" > /dev/null
  body=$("$PY" -c 'import json,sys; k=sys.argv[3]; p=open(sys.argv[4],encoding="utf-8").read(); print(json.dumps({"id":sys.argv[1],"kind":k,"payload":(p if k=="oru" else json.loads(p))}, separators=(",",":")))' "$id" x "$kind" "$d/$proof")
  hdr=()
  if [ "${5:-}" = signed ]; then
    sig=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "${KNOS_WEBHOOK_SECRET:?set KNOS_WEBHOOK_SECRET in iris/.env}" | sed 's/^.* //')
    hdr=(-H "X-Hub-Signature-256: sha256=$sig")
  fi
  out=$(curl -fsS -u "$auth" -H 'Content-Type: application/json' "${hdr[@]}" -X POST "$base/api/knos/proof" --data-binary "$body")
  printf '%s' "$out" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); m=(d.get("milestones") or [{}])[0]; print(sys.argv[1]+":", d["decision"], d["gate"], "-", m.get("reason",""), "- session", d["session"])' "$kind"
}
send "synthea:lorinda137" brief-glucose.json observation synthea-glucose-observation.json
send "hl7:lab-oru-1" brief-hematocrit.json oru lab-oru-1.hl7
send "github:drexthealpha/Knos" brief-ci.json checkrun github-check-run.json signed
