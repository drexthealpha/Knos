#!/usr/bin/env bash
# Knos on IRIS from a fresh clone, in one command: load the IRIS image, make iris/.env with random secrets,
# build and start both containers, wait for the production, then run three decisions on public data.
#   bash start.sh <irishealth-community-2026.3.0AI.154.0-docker.tar.gz>
set -euo pipefail
cd "$(dirname "$0")"
tar="${1:-}"
want="irishealth-community:2026.3.0AI.154.0"
say() { echo "== $*"; }
if ! docker image inspect "$want" > /dev/null 2>&1; then
  [ -n "$tar" ] || { echo "usage: bash start.sh <the build 154 image tar> (README step 0 says where to download it)" >&2; exit 2; }
  say "loading the IRIS image from $tar"
  bash scripts/load-image.sh "$tar"
fi
if [ ! -f .env ]; then
  say "making iris/.env (random password and signing secrets; the agent runs on the local model, no key)"
  cp .env.example .env && bash scripts/env-secrets.sh > /dev/null
fi
say "building and starting IRIS and the local model (the first start pulls the model, about 1 GB)"
docker compose up -d --build
set -a; . ./.env; set +a
say "waiting for the production"
for _ in $(seq 1 180); do
  h=$(curl -s -m 5 -u "_SYSTEM:$IRIS_PASSWORD" localhost:52773/api/knos/health || true)
  case "$h" in *'"production":"Running"'*) break;; esac
  sleep 5
done
case "$h" in *'"production":"Running"'*) echo "health: $h";; *) echo "IRIS did not report Running; see: docker compose logs iris" >&2; exit 1;; esac
say "three decisions on public data (iris/data/public/SOURCES.md)"
bash scripts/public-decisions.sh
say "open http://localhost:52773/knos/ and sign in as _SYSTEM with the IRIS_PASSWORD line of iris/.env"
